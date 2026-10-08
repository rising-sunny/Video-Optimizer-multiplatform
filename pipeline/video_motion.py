"""Tramo con movimiento de un video: detecta cuadros congelados y dice que parte usar.

Un clip de un proyecto real (el avion de "El triangulo de las Bermudas") se movia
2.44 s y repetia el mismo cuadro hasta los 10.64 s: en el video se veia un segundo
de accion y despues una foto. `freezedetect` de FFmpeg lo encuentra; aca se decide
el tramo util y se lo estira para cubrir la escena.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

# Umbral de ruido y duracion minima de un congelamiento (lo usado al medir el caso real).
FREEZE_NOISE = 0.003
FREEZE_MIN_SECONDS = 0.5
# Un tramo mas corto que esto no es "video que se mueve": se deja como esta.
MIN_MOVING_SECONDS = 0.6

_FREEZE_RE = re.compile(r"freeze_(start|end):\s*([0-9.]+)")


def parse_freezes(freezedetect_log: str) -> List[Tuple[float, Optional[float]]]:
    """[(inicio, fin)] de la salida de `freezedetect`; fin=None si sigue congelado al final."""
    freezes: List[Tuple[float, Optional[float]]] = []
    start: Optional[float] = None
    for kind, value in _FREEZE_RE.findall(str(freezedetect_log or "")):
        if kind == "start":
            start = float(value)
        elif start is not None:
            freezes.append((start, float(value)))
            start = None
    if start is not None:
        freezes.append((start, None))
    return freezes


def moving_span(freezes: List[Tuple[float, Optional[float]]], duration: float) -> Tuple[float, float]:
    """(inicio, fin) del tramo mas largo sin congelamientos."""
    duration = max(0.0, float(duration))
    edges, cursor = [], 0.0
    for start, end in sorted(freezes):
        edges.append((cursor, start))
        cursor = duration if end is None else end
    edges.append((cursor, duration))
    best = max(edges, key=lambda span: span[1] - span[0])
    return (round(max(0.0, best[0]), 3), round(min(duration, best[1]), 3))


def _probe_duration(path: str) -> float:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return float((out.stdout or "0").strip().splitlines()[0])
    except Exception:
        return 0.0


@lru_cache(maxsize=256)
def _analyze_cached(path: str, mtime: float, size: int, ffmpeg_exe: str) -> Dict[str, float]:
    duration = _probe_duration(path)
    proc = subprocess.run(
        [ffmpeg_exe, "-hide_banner", "-nostats", "-i", path, "-map", "0:v:0",
         "-vf", f"freezedetect=n={FREEZE_NOISE}:d={FREEZE_MIN_SECONDS}", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    freezes = parse_freezes(proc.stderr)
    start, end = moving_span(freezes, duration) if freezes else (0.0, duration)
    return {"duration": duration, "start": start, "end": end, "frozen": bool(freezes)}


def analyze(path: str, ffmpeg_exe: Optional[str] = None) -> Dict[str, float]:
    """{'duration', 'start', 'end', 'frozen', 'usable'} del video (cacheado por archivo).

    `usable`: hay que recortar al tramo [start, end] (tiene congelamientos y el
    tramo con movimiento alcanza para algo). Si falla, devuelve el video entero.
    """
    try:
        st = os.stat(path)
        info = dict(_analyze_cached(os.path.abspath(path), st.st_mtime, st.st_size,
                                    ffmpeg_exe or shutil.which("ffmpeg") or "ffmpeg"))
    except Exception:
        info = {"duration": 0.0, "start": 0.0, "end": 0.0, "frozen": False}
    info["usable"] = bool(info["frozen"] and info["end"] - info["start"] >= MIN_MOVING_SECONDS)
    return info


def input_window(info: Dict[str, float], needed: float) -> Tuple[float, float, float]:
    """(desde, largo, estirar) para cubrir `needed` segundos con el tramo que se mueve.

    `estirar` > 1 = ralentizar ese tramo (con interpolacion si FFmpeg la trae).
    Sin congelamientos (o sin medir) se usa el video desde 0 tal cual.
    """
    needed = max(0.05, float(needed))
    if info.get("usable"):
        start, length = float(info["start"]), float(info["end"]) - float(info["start"])
    else:
        start, length = 0.0, float(info.get("duration") or 0.0)
    if length <= 0:
        return 0.0, needed, 1.0
    if length >= needed:
        return start, needed, 1.0
    return start, length, needed / length
