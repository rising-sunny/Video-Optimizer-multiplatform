# -*- coding: utf-8 -*-
"""Encontrar el video de una carpeta de proyecto/draft sin que haya una copia adentro.

Decision (2026-09-14): cada render vive UNA sola vez, en `auto_videos/output/`
(junction a Google Drive), con nombre <plataforma>_<fecha>_<tema>.mp4. Antes, el
pipeline CLI y los microdocumentales ademas COPIABAN el render dentro de la
carpeta del proyecto (`short_HHMMSS.mp4`, `<TEMA>_DOCUMENTARY.mp4`) porque los
uploaders buscaban "el primer *.mp4 de la carpeta". Eso duplicaba cada video
(434 MB solo en Gunnerside) y, en long_form/, lo dejaba en C:.

Ahora el pipeline registra la ruta del render (pipeline_state.json,
project.json, manifest.json) y los uploaders la resuelven desde aca. El glob
queda como compatibilidad con drafts viejos que si tienen la copia adentro.

Puro y testeable: ver `test_output_video_location.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

# Archivos donde el pipeline deja escrita la ruta del render, en orden de confianza.
_STATE_FILES = ("pipeline_state.json", "project.json", "manifest.json", "summary.json", "metadata.json")
VIDEO_PATTERNS = ("*.mp4", "*.mov", "*.mkv", "*.webm", "*.m4v")


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _recorded_candidates(data: dict) -> Iterable[str]:
    yield data.get("video_path") or ""
    nested = data.get("generated_video_data")
    if isinstance(nested, dict):
        yield nested.get("video_path") or ""


def recorded_video_path(output_dir: os.PathLike | str) -> Optional[str]:
    """La ruta que el pipeline dejo registrada, si el archivo todavia existe."""
    folder = Path(output_dir)
    for name in _STATE_FILES:
        for value in _recorded_candidates(_read_json(folder / name)):
            if not value:
                continue
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = folder / candidate
            if candidate.is_file():
                return str(candidate.resolve())
    return None


def newest_video_in(output_dir: os.PathLike | str) -> Optional[str]:
    """Compatibilidad: drafts viejos con la copia del render adentro.

    Si hay varios, el mas reciente -- antes era `videos[0]`, o sea el que
    tocara segun el orden del filesystem.
    """
    folder = Path(output_dir)
    found = []
    for pattern in VIDEO_PATTERNS:
        found.extend(p for p in folder.glob(pattern) if p.is_file())
    if not found:
        return None
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(found[0].resolve())


def find_output_video(output_dir: os.PathLike | str) -> Optional[str]:
    """El video a publicar para esta carpeta: ruta registrada, o el mp4 mas nuevo adentro."""
    return recorded_video_path(output_dir) or newest_video_in(output_dir)


__all__ = ["find_output_video", "recorded_video_path", "newest_video_in", "VIDEO_PATTERNS"]
