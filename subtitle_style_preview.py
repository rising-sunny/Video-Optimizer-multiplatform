# -*- coding: utf-8 -*-
"""Vistas previas animadas de los estilos de subtitulos, tipo CapCut.

La idea: al elegir un estilo se ve un GIF corto con la frase de ejemplo
animandose de verdad -- karaoke, rebote, zoom, lo que tenga ese estilo.

Decision central: la previa NO se dibuja a mano. Se genera con el MISMO
`DynamicSubtitleEngine` que usa el pipeline y se quema con FFmpeg igual que en
el render final. Una previa pintada aparte se desincroniza del motor real en la
primera modificacion, y entonces miente justo cuando mas confias en ella.

Formato GIF y no MP4 a proposito: es un clip mudo de dos segundos y medio, y
QMovie lo reproduce sin depender del backend multimedia de Qt, que en esta app
ya dio problemas (ver los fallbacks a VLC/ffplay del buscador de musica).

Las previas se cachean: la primera vez cuestan un par de segundos de FFmpeg,
despues son instantaneas.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

# Frase de ejemplo: corta, con una cifra (los ganchos del canal son numericos)
# y con palabras de largo distinto para que se vea como reparte el karaoke.
SAMPLE_TEXT = "20,000 lives in stone"
SAMPLE_DURATION = 2.6

# El ASS se disena sobre 1080x1920 (los tamanos de fuente de cada estilo estan
# calibrados ahi); el GIF se reduce despues. Renderizar chico deformaria las
# proporciones y la previa mentiria sobre el tamano real del texto.
RENDER_W, RENDER_H = 1080, 1920
GIF_W = 360
GIF_FPS = 15

# Fondo neutro: ni negro puro ni claro. En negro puro no se distingue el
# contorno, y en claro no se ven los estilos pensados para video oscuro.
BACKGROUND = "0x232a33"

PREVIEW_VERSION = "v1"


def preview_filename(style_key: str, version: str = PREVIEW_VERSION) -> str:
    """Nombre del GIF cacheado para un estilo."""
    limpio = re.sub(r"[^\w]+", "_", str(style_key or "estilo")).strip("_").lower()
    return "subprev_%s_%s.gif" % (version, limpio or "estilo")


def preview_cache_dir() -> Path:
    """Carpeta de cache. Fuera del proyecto: son artefactos regenerables."""
    base = Path(tempfile.gettempdir()) / "video_optimizer" / "subtitle_previews"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sample_segments(text: str = SAMPLE_TEXT,
                    duration: float = SAMPLE_DURATION) -> List[Dict]:
    """Un segmento con timing por palabra, como el que produce Whisper.

    Se reparte proporcional al largo de cada palabra en vez de en partes
    iguales: asi el karaoke se ve como en un guion real, donde '20,000' dura
    mas que 'in'.
    """
    palabras = [p for p in str(text or "").split() if p]
    if not palabras:
        return []

    pesos = [max(1, len(p)) for p in palabras]
    total = float(sum(pesos))
    words = []
    t = 0.0
    for palabra, peso in zip(palabras, pesos):
        dur = (peso / total) * float(duration)
        words.append({"word": palabra, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur

    return [{
        "text": " ".join(palabras),
        "start": 0.0,
        "end": round(float(duration), 3),
        "words": words,
    }]


def _resolve_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg") or (
        r"C:\ffmpeg-7.1.1-full_build\bin\ffmpeg.exe"
        if os.path.exists(r"C:\ffmpeg-7.1.1-full_build\bin\ffmpeg.exe") else None
    )


def _ass_para_ffmpeg(ruta: str) -> str:
    """Escapa la ruta del ASS para el filtro `subtitles` de FFmpeg.

    En Windows hay que neutralizar la barra invertida y los dos puntos de la
    unidad, o el filtro interpreta 'C:' como separador de opciones.
    """
    p = str(ruta).replace("\\", "/")
    return p.replace(":", "\\:")


def build_preview(style_key: str, cache_dir: Optional[Path] = None,
                  text: str = SAMPLE_TEXT, force: bool = False,
                  timeout: int = 180) -> Optional[str]:
    """Genera (o devuelve de cache) el GIF de ejemplo de un estilo.

    Devuelve la ruta al GIF, o None si no se pudo. Nunca lanza: una previa que
    falla no puede impedir elegir el estilo.
    """
    destino = (cache_dir or preview_cache_dir()) / preview_filename(style_key)
    if destino.exists() and destino.stat().st_size > 0 and not force:
        return str(destino)

    ffmpeg = _resolve_ffmpeg()
    if not ffmpeg:
        return None

    trabajo = Path(tempfile.mkdtemp(prefix="subprev_"))
    try:
        from dynamic_subtitles_generator import DynamicSubtitleEngine

        ass_path = trabajo / "muestra.ass"
        engine = DynamicSubtitleEngine(style=style_key)
        engine.generate_from_segments(
            sample_segments(text), str(ass_path),
            video_width=RENDER_W, video_height=RENDER_H)
        if not ass_path.exists():
            return None

        paleta = trabajo / "paleta.png"
        fondo = "color=c=%s:s=%dx%d:d=%.2f" % (
            BACKGROUND, RENDER_W, RENDER_H, SAMPLE_DURATION + 0.4)
        cadena = "subtitles='%s',scale=%d:-2:flags=lanczos,fps=%d" % (
            _ass_para_ffmpeg(str(ass_path)), GIF_W, GIF_FPS)

        # Dos pasadas: sin paleta propia, un GIF de texto con contorno queda
        # sucio y la previa se ve peor que el resultado real.
        r1 = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", fondo,
             "-vf", cadena + ",palettegen=stats_mode=diff", str(paleta)],
            capture_output=True, text=True, timeout=timeout)
        if r1.returncode != 0 or not paleta.exists():
            return None

        temporal = trabajo / "previa.gif"
        r2 = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", fondo, "-i", str(paleta),
             "-lavfi", cadena + " [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=3",
             "-loop", "0", str(temporal)],
            capture_output=True, text=True, timeout=timeout)
        if r2.returncode != 0 or not temporal.exists() or temporal.stat().st_size == 0:
            return None

        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporal), str(destino))
        return str(destino)
    except Exception:
        return None
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


def style_key_from_label(label: str) -> str:
    """Etiqueta del combo -> clave del estilo, con la misma regla del pipeline."""
    try:
        from dynamic_subtitle_wrapper import normalize_subtitle_style

        return normalize_subtitle_style(label)
    except Exception:
        return "hormozi"


def describe_style(style_key: str) -> str:
    """Una linea con lo que hace el estilo, para acompanar la animacion."""
    try:
        from dynamic_subtitles_generator import SubtitleStyle

        d = SubtitleStyle.get_style(style_key)
    except Exception:
        return ""
    partes = [
        "Fuente %s %s" % (d.get("font", "?"), d.get("font_size", "")),
        "animacion %s" % d.get("animation", "ninguna"),
    ]
    if d.get("karaoke"):
        partes.append("karaoke palabra por palabra")
    if d.get("emojis"):
        partes.append("emojis automaticos")
    return " · ".join(partes)


__all__ = [
    "SAMPLE_TEXT", "SAMPLE_DURATION", "RENDER_W", "RENDER_H", "GIF_W",
    "preview_filename", "preview_cache_dir", "sample_segments",
    "build_preview", "style_key_from_label", "describe_style",
]
