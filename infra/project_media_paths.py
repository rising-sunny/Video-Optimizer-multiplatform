"""Project directories may end in .json and may be reached through junctions."""
import os
from pathlib import Path


def project_directory(hint):
    path = Path(hint).resolve()
    return path if path.is_dir() else path.parent if path.suffix.lower() == '.json' else path


def normalize_project_path(path):
    return os.path.normcase(str(Path(path).resolve())) if path else None


def resolve_project_media(value, root):
    if not value:
        return None
    path = Path(value)
    candidates = [path] if path.is_absolute() else [project_directory(root) / path, path]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def prepare_existing_media(storyboard, root):
    missing = []
    for index, segment in enumerate(storyboard.get('segments', []), 1):
        ready = False
        for field in ('video_path', 'image_path'):
            if field == 'image_path' and segment.get('image_deleted'):
                continue
            resolved = resolve_project_media(segment.get(field), root)
            if resolved:
                segment[field] = resolved
                ready = True
        if not ready and not segment.get('image_deleted') and not segment.get('cover_frame'):
            missing.append(str(index))
    if missing:
        raise ValueError('Ensamblaje detenido: faltan medios en los segmentos ' + ', '.join(missing)
                         + '. No se generará un video con reemplazos negros.')
    return storyboard
