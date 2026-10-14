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

# Movimientos de camara de las tomas 3D. 'push' es el clasico (acercarse);
# 'orbit' da la vuelta alrededor del objeto; 'crane' sube la camara.
MOTIONS = ("push", "orbit", "crane")
DEFAULT_MOTION = "push"


def normalize_motion(value: Any) -> str:
    key = str(value or "").strip().lower()
    return key if key in MOTIONS else DEFAULT_MOTION


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


COMMON_MODULE = os.path.join(TEMPLATES_DIR, "_scene_common.py")
_QUALITY_ORDER = ("draft", "normal", "high")

ENVIRONMENTS = {
    # s_per_frame en la UHD 630 a 1080x1920: medido en Borrador (mesa, tablero en
    # Normal, TV y periodico) y estimado en el resto. El tablero necesita Normal
    # como minimo: en Borrador el hilo fino sale serruchado.
    "desk": {"template": "desk_photos.py", "min_quality": None,
             "s_per_frame": {"draft": 1.6, "normal": 3.2, "high": 8.0}},
    "corkboard": {"template": "corkboard.py", "min_quality": "normal",
                  "overrides": {"samples": 8, "shadow_scale": 1.0},
                  "s_per_frame": {"draft": 5.6, "normal": 5.6, "high": 11.0}},
    "crt_tv": {"template": "crt_tv.py", "min_quality": None,
               "s_per_frame": {"draft": 1.5, "normal": 3.0, "high": 7.5}},
    "newspaper": {"template": "newspaper.py", "min_quality": None,
                  "s_per_frame": {"draft": 2.5, "normal": 4.5, "high": 10.0}},
    "map": {"template": "map_old.py", "min_quality": None,
            "s_per_frame": {"draft": 1.8, "normal": 3.4, "high": 8.5}},
    "war_room": {"template": "war_room.py", "min_quality": None,
                 "s_per_frame": {"draft": 2.2, "normal": 4.0, "high": 10.0}},
    "timeline": {"template": "timeline.py", "min_quality": None,
                 "s_per_frame": {"draft": 1.7, "normal": 3.2, "high": 8.0}},

}


def normalize_environment(value: Any) -> str:
    key = str(value or "").strip().lower()
    return key if key in ENVIRONMENTS else "desk"


def effective_quality(environment: str, quality: Any) -> str:
    """La calidad pedida, subida al minimo del ambiente si hace falta."""
    chosen = normalize_quality(quality)
    minimum = ENVIRONMENTS[normalize_environment(environment)].get("min_quality")
    if minimum and _QUALITY_ORDER.index(chosen) < _QUALITY_ORDER.index(minimum):
        return minimum
    return chosen


def template_path(environment: str) -> str:
    return os.path.join(TEMPLATES_DIR, ENVIRONMENTS[normalize_environment(environment)]["template"])


def shot_frames(duration: float, fps: float) -> int:
    return max(2, int(round((float(duration) + TAIL_SECONDS) * float(fps))))


def estimate_seconds(duration: float, fps: float, quality: str = DEFAULT_QUALITY,
                     environment: str = "desk") -> float:
    env = normalize_environment(environment)
    rate = ENVIRONMENTS[env]["s_per_frame"][effective_quality(env, quality)]
    return COMPILE_SECONDS + shot_frames(duration, fps) * rate


def build_params(images: Sequence[str], duration: float, size: Sequence[int], fps: float,
                 quality: str, out_dir: str, seed: int = 7, environment: str = "desk",
                 motion: str = DEFAULT_MOTION) -> Dict[str, Any]:
    env = normalize_environment(environment)
    spec = dict(QUALITY_PRESETS[effective_quality(env, quality)])
    for key, minimum in (ENVIRONMENTS[env].get("overrides") or {}).items():
        spec[key] = max(spec[key], minimum)
    return {
        "environment": env,
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
        "motion": normalize_motion(motion),
    }


def cache_key(params: Dict[str, Any], template: Optional[str] = None) -> str:
    """Cambia si cambian los medios (via mtime/tamano), la toma, la plantilla o lo comun."""
    template = template or template_path(params.get("environment", "desk"))
    digest = hashlib.sha1()
    stable = {k: v for k, v in params.items() if k != "out_dir"}
    digest.update(json.dumps(stable, sort_keys=True).encode("utf-8"))
    for path in list(params.get("images") or []) + [template, COMMON_MODULE]:
        try:
            st = os.stat(path)
            digest.update(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8"))
        except OSError:
            digest.update(f"{path}|missing".encode("utf-8"))
    return digest.hexdigest()[:16]


def prepare_screen_video(video: str, duration: float, fps: float, cache_dir: str,
                         ffmpeg_exe: Optional[str] = None) -> str:
    """El video para la pantalla de la TV: solo el tramo con movimiento, al largo de
    la toma y a `fps` (Blender lo reproduce cuadro a cuadro). Queda en cache."""
    from pipeline import video_motion
    ffmpeg_exe = ffmpeg_exe or shutil.which("ffmpeg") or "ffmpeg"
    needed = shot_frames(duration, fps) / float(fps)
    start, length, stretch = video_motion.input_window(video_motion.analyze(video, ffmpeg_exe), needed)
    st = os.stat(video)
    key = hashlib.sha1(repr((os.path.abspath(video), st.st_size, int(st.st_mtime), round(start, 3),
                             round(length, 3), round(stretch, 4), fps)).encode("utf-8")).hexdigest()[:14]
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, f"screen_{key}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    rate = f"{float(fps):g}"
    vf = f"fps={rate},scale='min(1280,iw)':-2"
    if stretch > 1.001:
        vf = (f"setpts={stretch:.6f}*PTS,minterpolate=fps={rate}:mi_mode=mci:mc_mode=aobmc:"
              f"me_mode=bidir:vsbmc=1,{vf}")
    staging = out + ".part.mp4"
    proc = subprocess.run(
        [ffmpeg_exe, "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", video,
         "-vf", vf, "-t", f"{needed:.3f}", "-an", "-c:v", "libx264", "-crf", "16", "-preset", "fast",
         staging],
        capture_output=True, text=True, timeout=600,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if proc.returncode != 0 or not os.path.exists(staging):
        raise RuntimeError(f"no se pudo preparar el video de la pantalla: {(proc.stderr or '')[-200:]}")
    os.replace(staging, out)
    return out


def render_shot(
    environment: str,
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
    motion: Optional[str] = None,
) -> Dict[str, Any]:
    """Renderiza una toma 3D del `environment` (ver ENVIRONMENTS) con `images[0]` de protagonista.

    `motion` = 'push'|'orbit'|'crane'; None elige segun el seed (variedad entre tomas).
    Devuelve {'ok', 'path', 'seconds', 'cached', 'error', 'quality'}. Nunca lanza:
    un error vuelve con ok=False para que el ensamblaje siga con FFmpeg.
    """
    env = normalize_environment(environment)
    quality = effective_quality(env, quality)
    result: Dict[str, Any] = {"ok": False, "path": None, "seconds": 0.0, "cached": False,
                              "error": "", "quality": quality}
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

    if motion is None:
        motion = MOTIONS[int(seed) % len(MOTIONS)]
    work = tempfile.mkdtemp(prefix="blender_shot_")
    params = build_params(images, duration, size, fps, quality, os.path.join(work, "frames"), seed, env, motion)
    os.makedirs(params["out_dir"], exist_ok=True)
    template = template_path(env)
    out_path = os.path.join(cache_dir, f"{env}_{cache_key(params, template)}.mp4")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        # Tambien se revisa lo cacheado: una toma negra guardada antes de esta
        # validacion se reusaria para siempre.
        if not black_segments(out_path, ffmpeg_exe):
            shutil.rmtree(work, ignore_errors=True)
            result.update(ok=True, path=out_path, cached=True)
            return result
        log("      [3D] La toma del cache tiene cuadros negros: se vuelve a renderizar")
        os.remove(out_path)

    params_path = os.path.join(work, "params.json")
    with open(params_path, "w", encoding="utf-8") as fh:
        json.dump(params, fh)
    log(f"      [3D] Blender ({env}): {params['frames']} cuadros, calidad {QUALITY_PRESETS[quality]['label']} "
        f"(~{estimate_seconds(duration, fps, quality, env) / 60:.0f} min estimados)")
    t0 = time.time()
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            shutil.rmtree(params["out_dir"], ignore_errors=True)
            os.makedirs(params["out_dir"], exist_ok=True)
            partial, error = _run_once(blender_exe, template, params_path, params, ffmpeg_exe,
                                       work, timeout_s, log)
            if partial is None:
                result["error"] = error
                return result
            # La GPU integrada a veces falla A MITAD del render y Blender sigue
            # guardando cuadros NEGROS sin avisar (visto el 2026-10-06: TV negra
            # desde 0.5 s; la repeticion salio bien). Nunca entra al video ni al cache.
            black = black_segments(partial, ffmpeg_exe)
            if not black:
                break
            result["error"] = (f"Blender devolvio cuadros negros ({black[0][0]:.1f}s en adelante)"
                               f"{', reintentando' if attempt < MAX_ATTEMPTS else ''}")
            log(f"      [3D] {result['error']}")
        else:
            return result
        staging = out_path + ".part"     # misma carpeta: el replace es atomico
        shutil.copyfile(partial, staging)
        os.replace(staging, out_path)
        result.update(ok=True, path=out_path, seconds=round(time.time() - t0, 1), error="")
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


MAX_ATTEMPTS = 2
_BLACK_RE = re.compile(r"black_start:\s*([0-9.]+)\s+black_end:\s*([0-9.]+)")


def parse_black_segments(blackdetect_log: str) -> List[tuple]:
    """[(inicio, fin)] de la salida de `blackdetect`."""
    return [(float(a), float(b)) for a, b in _BLACK_RE.findall(str(blackdetect_log or ""))]


def black_segments(video: str, ffmpeg_exe: Optional[str] = None) -> List[tuple]:
    """Tramos negros de >=0.2 s (un cuadro es negro si el 98% de sus pixeles lo son:
    el cuarto oscuro de la TV no cuenta, porque la pantalla esta encendida)."""
    proc = subprocess.run(
        [ffmpeg_exe or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-nostats", "-i", video,
         "-vf", "blackdetect=d=0.2:pic_th=0.98:pix_th=0.10", "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return parse_black_segments(proc.stderr)


def _run_once(blender_exe, template, params_path, params, ffmpeg_exe, work, timeout_s, log):
    """Un render de Blender + encode a mp4. Devuelve (ruta, '') o (None, error)."""
    frames = params["frames"]
    t0 = time.time()
    proc = None
    watchdog = None
    try:
        proc = subprocess.Popen(
            [blender_exe, "-b", "--factory-startup", "-P", template, "--", params_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        # Corta aunque Blender se cuelgue sin imprimir nada (el bucle quedaria esperando).
        watchdog = threading.Timer(timeout_s, proc.kill)
        watchdog.daemon = True
        watchdog.start()
        saved, tail, t_first, finished = 0, [], None, False
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-25:]
            if line.startswith("RENDER_TIME"):
                finished = True
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
            return None, f"Blender supero {timeout_s / 60:.0f} min"
        rendered = sorted(glob.glob(os.path.join(params["out_dir"], "f_*.png")))
        # EEVEE en segundo plano a veces se cae AL CERRAR (EXCEPTION_ACCESS_VIOLATION
        # con drivers Intel) despues de guardar todo: con los cuadros completos y el
        # RENDER_TIME de la plantilla, la toma esta bien y no se tiran minutos.
        crashed_on_exit = proc.returncode != 0 and finished and len(rendered) >= frames
        if (proc.returncode != 0 and not crashed_on_exit) or len(rendered) < frames:
            detail = next((ln for ln in reversed(tail) if "Error" in ln or "Traceback" in ln), tail[-1] if tail else "")
            return None, f"Blender termino con {len(rendered)}/{frames} cuadros: {detail[:200]}"
        if crashed_on_exit:
            log("      [3D] Blender se cerro con error despues de terminar; los cuadros estan completos")

        # Se codifica a un temporal; el que llama lo copia al cache recien validado
        # (un mp4 parcial o con cuadros negros no puede quedar para siempre).
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
            return None, f"no se pudo codificar la toma: {(enc.stderr or '')[-200:]}"
        return partial, ""
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if proc is not None and proc.poll() is None:
            proc.kill()


def render_desk_shot(images: Sequence[str], **kwargs: Any) -> Dict[str, Any]:
    """La mesa con fotos (compatibilidad con el nombre original)."""
    return render_shot("desk", images, **kwargs)
