# -*- coding: utf-8 -*-
"""Nombre de archivo de los videos exportados.

Antes salian como `youtube_short_1788485267.mp4`: un timestamp Unix que nadie
lee. Con varios videos generados el mismo dia era imposible saber cual era
cual sin abrirlos uno por uno.

Ahora: `youtube_short_20260903_1615_caral_seis_piramides.mp4`

Decisiones y por que:

- La PLATAFORMA va primero para que el listado agrupe por tipo y, dentro de
  cada grupo, quede ordenado por fecha.
- La fecha es legible (`20260903_1615`) en vez del epoch. Se comprobo que
  nada del proyecto parsea el nombre del archivo, asi que cambiarlo es seguro.
- Los segundos entran solo si hacen falta: dos videos del mismo tema en el
  mismo minuto son raros, pero el nombre tiene que ser unico igual.
- El tema va sin tildes ni enies. Windows los acepta, pero este proyecto ya
  perdio tiempo con rutas y consolas en cp1252; no vale la pena arriesgarlo
  en un nombre que despues viaja por scp al VPS.

Es puro: sin PIL, sin red, sin Qt. Ver `test_output_naming.py`.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from typing import Optional

# Windows tiene MAX_PATH de 260 y estos archivos viven en carpetas anidadas
# (`projects/<proyecto>/...`) y ademas se copian a staging temporales.
MAX_SLUG_LEN = 48

# Palabras que no aportan nada para reconocer un video de un vistazo.
_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "y",
    "o", "a", "en", "que", "con", "por", "para", "su", "sus", "al", "lo",
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with",
    "that", "this", "its", "at", "from", "by",
}

_ILEGALES = r'[\\/:*?"<>|]'


def slugify_topic(topic: str, max_len: int = MAX_SLUG_LEN) -> str:
    """Convierte un tema en un fragmento de nombre de archivo legible.

    'Caral: las seis pirámides del valle de Supe' -> 'caral_seis_piramides_valle_supe'
    """
    texto = str(topic or "").strip()
    if not texto:
        return ""

    # NFKD separa la tilde de la letra; al descartar los combinantes queda ASCII.
    plano = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    plano = plano.replace("ñ", "n").replace("Ñ", "N")
    plano = re.sub(_ILEGALES, " ", plano)
    plano = re.sub(r"[^\w\s-]", " ", plano, flags=re.ASCII)

    palabras = [p for p in re.split(r"[\s_-]+", plano.lower()) if p]
    # Las stopwords se sacan solo si queda algo: un tema como "The Wall"
    # no puede terminar vacio.
    utiles = [p for p in palabras if p not in _STOPWORDS]
    if not utiles:
        utiles = palabras
    if not utiles:
        return ""

    slug = ""
    for palabra in utiles:
        candidato = palabra if not slug else slug + "_" + palabra
        if len(candidato) > max_len:
            break
        slug = candidato
    # Un tema de una sola palabra larguisima igual tiene que dar algo.
    if not slug:
        slug = utiles[0][:max_len]
    return slug.strip("_")


def build_video_filename(platform: str, topic: str = "", when: Optional[datetime.datetime] = None,
                         extension: str = ".mp4", include_seconds: bool = True) -> str:
    """`<plataforma>_<fecha>_<tema>.<ext>`, listo para usar como nombre."""
    momento = when or datetime.datetime.now()
    formato = "%Y%m%d_%H%M%S" if include_seconds else "%Y%m%d_%H%M"
    sello = momento.strftime(formato)

    plataforma = re.sub(r"[^\w]+", "_", str(platform or "video").strip().lower()).strip("_")
    plataforma = plataforma or "video"

    slug = slugify_topic(topic)
    partes = [plataforma, sello] + ([slug] if slug else [])
    ext = extension if extension.startswith(".") else "." + extension
    return "_".join(partes) + ext


def build_clip_filename(video_id: str, title: str = "", start: float = 0.0,
                        end: float = 0.0, suffix: str = "", extension: str = ".mp4") -> str:
    """Nombre de UN recorte concreto de un video de origen.

    El bug que arregla (2026-09-04): la descarga se guardaba como
    `youtube_<hash>_<titulo>.mp4`, un nombre que depende solo del VIDEO. Al
    recortar se hacia `os.replace(temp, descargado)`, o sea que el recorte
    pisaba el original. Sacar un segundo fragmento del mismo video daba una de
    dos cosas, las dos malas:

      - se reutilizaba el archivo ya recortado, y pedir 40-60s de un clip de
        10s no da nada util;
      - o se volvia a descargar encima, y el segmento que YA apuntaba a ese
        archivo cambiaba de contenido en silencio.

    Incluyendo inicio y fin en el nombre, cada recorte es un archivo distinto
    y la descarga completa queda intacta para reutilizarla.
    """
    vid = re.sub(r"[^\w-]+", "", str(video_id or "")).strip("-_") or "video"
    slug = slugify_topic(title, max_len=32)
    # Centesimas: dos recortes que empiezan en 10.20 y 10.25 son distintos.
    tramo = "%08.2f-%08.2f" % (max(0.0, float(start or 0)), max(0.0, float(end or 0)))
    tramo = tramo.replace(".", "")

    partes = ["yt", vid[:24], tramo]
    if slug:
        partes.append(slug)
    if suffix:
        partes.append(re.sub(r"[^\w]+", "", str(suffix)))
    ext = extension if extension.startswith(".") else "." + extension
    return "_".join(partes) + ext


__all__ = ["MAX_SLUG_LEN", "slugify_topic", "build_video_filename",
           "build_clip_filename"]
