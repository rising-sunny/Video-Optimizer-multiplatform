"""Tomas 3D con Blender (opcional): las renderiza en segundo plano y devuelve un mp4.

La app nunca importa `bpy`: lanza `blender -b` con una plantilla de
`pipeline/blender_templates/` y un JSON de parametros. El mp4 resultante entra
al ensamblaje como un segmento de video comun. Si Blender no esta o falla, el
que llama cae a una composicion de FFmpeg (ver `segment_layouts`).

Tiempos medidos en la PC del usuario (Intel UHD 630, sin GPU dedicada, 1080x1920):
el costo lo ponen las muestras de EEVEE, no la resolucion (~1 s fijo por cuadro).
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_templates")
DESK_TEMPLATE = os.path.join(TEMPLATES_DIR, "desk_photos.py")

QUALITY_PRESETS = {
    # s_per_frame: medido (borrador) o estimado (normal/alta) en la UHD 630.
    "draft": {"label": "Borrador", "resolution_pct": 50, "samples": 4, "shadow_scale": 0.5,
              "s_per_frame": 1.6},
    "normal": {"label": "Normal", "resolution_pct": 75, "samples": 6, "shadow_scale": 0.75,
               "s_per_frame": 3.2},
    "high": {"label": "Alta", "resolution_pct": 100, "samples": 12, "shadow_scale": 1.0,
             "s_per_frame": 8.0},
}
DEFAULT_QUALITY = "normal"
# Un short lleva una toma; un documental largo, dos. Cada una cuesta minutos.
MAX_SHOTS = {"vertical": 1, "horizontal": 2}
TAIL_SECONDS = 0.4          # margen para que el ensamblador no tenga que estirar el clip
COMPILE_SECONDS = 20        # compilacion de shaders al arrancar Blender


def normalize_quality(value: Any) -> str:
    key = str(value or "").strip().lower()
    for name, spec in QUALITY_PRESETS.items():
        if key in (name, spec["label"].lower()):
            return name
    return DEFAULT_QUALITY


def _version_key(path: str) -> tuple:
    found = re.search(r"Blender\s*(\d+)\.(\d+)", path, re.IGNORECASE)
    return tuple(int(v) for v in found.groups()) if found else (0, 0)


def find_blender(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Ruta a blender.exe: BLENDER_PATH, el PATH, o la version mas nueva instalada."""
    env = os.environ if env is None else env
    explicit = str(env.get("BLENDER_PATH") or "").strip().strip('"')
    if explicit and os.path.isfile(explicit):
        return explicit
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    candidates: List[str] = []
    for root in (env.get("ProgramFiles") or r"C:\Program Files",
                 env.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"):
        candidates += glob.glob(os.path.join(root, "Blender Foundation", "Blender*", "blender.exe"))
        candidates += glob.glob(os.path.join(root, "Steam", "steamapps", "common", "Blender", "blender.exe"))
    candidates = [c for c in candidates if os.path.isfile(c)]
    return max(candidates, key=_version_key) if candidates else None


def shot_frames(duration: float, fps: float) -> int:
    return max(2, int(round((float(duration) + TAIL_SECONDS) * float(fps))))


def estimate_seconds(duration: float, fps: float, quality: str = DEFAULT_QUALITY) -> float:
    spec = QUALITY_PRESETS[normalize_quality(quality)]
    return COMPILE_SECONDS + shot_frames(duration, fps) * spec["s_per_frame"]


def build_params(images: Sequence[str], duration: float, size: Sequence[int], fps: float,
                 quality: str, out_dir: str, seed: int = 7) -> Dict[str, Any]:
    spec = QUALITY_PRESETS[normalize_quality(quality)]
    return {
        "images": [os.path.abspath(str(p)) for p in images],
        "frames": shot_frames(duration, fps),
        "fps": int(round(float(fps))),
        "width": int(size[0]),
        "height": int(size[1]),
        "resolution_pct": spec["resolution_pct"],
        "samples": spec["samples"],
        "shadow_scale": spec["shadow_scale"],
        "out_dir": os.path.abspath(out_dir),
        "seed": int(seed),
    }


def cache_key(params: Dict[str, Any], template: str = DESK_TEMPLATE) -> str:
    """Cambia si cambian las imagenes (contenido via mtime/tamano), la toma o la plantilla."""
    digest = hashlib.sha1()
    stable = {k: v for k, v in params.items() if k != "out_dir"}
    digest.update(json.dumps(stable, sort_keys=True).encode("utf-8"))
    for path in list(params.get("images") or []) + [template]:
        try:
            st = os.stat(path)
            digest.update(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8"))
        except OSError:
            digest.update(f"{path}|missing".encode("utf-8"))
    return digest.hexdigest()[:16]


def render_desk_shot(
    images: Sequence[str],
    *,
    duration: float,
    size: Sequence[int],
    fps: float,
    cache_dir: str,
    quality: str = DEFAULT_QUALITY,
    blender_exe: Optional[str] = None,
    ffmpeg_exe: Optional[str] = None,
    log: Callable[[str], None] = print,
    timeout_s: float = 3600,
    seed: int = 7,
) -> Dict[str, Any]:
    """Renderiza 'fotos sobre la mesa' que termina en `images[0]`.

    Devuelve {'ok', 'path', 'seconds', 'cached', 'error'}. Nunca lanza: un
    error vuelve con ok=False para que el ensamblaje siga con FFmpeg.
    """
    result: Dict[str, Any] = {"ok": False, "path": None, "seconds": 0.0, "cached": False, "error": ""}
    images = [str(p) for p in images if p and os.path.exists(str(p))]
    if not images:
        result["error"] = "sin imagenes para la toma"
        return result
    blender_exe = blender_exe or find_blender()
    if not blender_exe:
        result["error"] = "Blender no encontrado (instalalo o defini BLENDER_PATH en .env)"
        return result
    ffmpeg_exe = ffmpeg_exe or shutil.which("ffmpeg") or "ffmpeg"
    os.makedirs(cache_dir, exist_ok=True)

    work = tempfile.mkdtemp(prefix="blender_shot_")
    params = build_params(images, duration, size, fps, quality, os.path.join(work, "frames"), seed)
    os.makedirs(params["out_dir"], exist_ok=True)
    out_path = os.path.join(cache_dir, f"desk_{cache_key(params)}.mp4")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        shutil.rmtree(work, ignore_errors=True)
        result.update(ok=True, path=out_path, cached=True)
        return result

    params_path = os.path.join(work, "params.json")
    with open(params_path, "w", encoding="utf-8") as fh:
        json.dump(params, fh)
    frames = params["frames"]
    log(f"      [3D] Blender: {frames} cuadros, calidad {QUALITY_PRESETS[normalize_quality(quality)]['label']} "
        f"(~{estimate_seconds(duration, fps, quality) / 60:.0f} min estimados)")

    t0 = time.time()
    proc = None
    watchdog = None
    try:
        proc = subprocess.Popen(
            [blender_exe, "-b", "--factory-startup", "-P", DESK_TEMPLATE, "--", params_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        # Corta aunque Blender se cuelgue sin imprimir nada (el bucle quedaria esperando).
        watchdog = threading.Timer(timeout_s, proc.kill)
        watchdog.daemon = True
        watchdog.start()
        saved, tail, t_first = 0, [], None
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-25:]
            if "Saved:" in line:
                saved += 1
                if saved == 1:
                    # El primer cuadro carga la compilacion de shaders (~20 s):
                    # el ritmo se mide desde el segundo.
                    t_first = time.time()
                    log(f"      [3D] primer cuadro listo ({t_first - t0:.0f}s con la carga de Blender)")
                elif saved % 15 == 0 or saved == frames:
                    rate = (time.time() - t_first) / (saved - 1)
                    log(f"      [3D] {saved}/{frames} cuadros, faltan ~{rate * (frames - saved) / 60:.1f} min")
        proc.wait(timeout=60)
        if time.time() - t0 >= timeout_s:
            result["error"] = f"Blender supero {timeout_s / 60:.0f} min"
            return result
        rendered = sorted(glob.glob(os.path.join(params["out_dir"], "f_*.png")))
        if proc.returncode != 0 or len(rendered) < frames:
            detail = next((ln for ln in reversed(tail) if "Error" in ln or "Traceback" in ln), tail[-1] if tail else "")
            result["error"] = f"Blender termino con {len(rendered)}/{frames} cuadros: {detail[:200]}"
            return result

        # Se codifica a un temporal y se renombra al final: un corte a mitad del
        # encode dejaria un mp4 parcial que el cache reusaria para siempre.
        partial = os.path.join(work, "shot.mp4")
        enc = subprocess.run(
            [ffmpeg_exe, "-y", "-v", "error", "-framerate", str(params["fps"]),
             "-i", os.path.join(params["out_dir"], "f_%04d.png"),
             "-vf", f"scale={params['width']}:{params['height']}:flags=lanczos,format=yuv420p",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-an", partial],
            capture_output=True, text=True, timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if enc.returncode != 0 or not os.path.exists(partial):
            result["error"] = f"no se pudo codificar la toma: {(enc.stderr or '')[-200:]}"
            return result
        staging = out_path + ".part"     # misma carpeta: el replace es atomico
        shutil.copyfile(partial, staging)
        os.replace(staging, out_path)
        result.update(ok=True, path=out_path, seconds=round(time.time() - t0, 1))
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if proc is not None and proc.poll() is None:
            proc.kill()
        shutil.rmtree(work, ignore_errors=True)
