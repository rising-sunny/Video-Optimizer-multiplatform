"""Resolve the project's committed render instead of a stale GUI reference."""
import json
from pathlib import Path
from project_media_paths import resolve_project_media


def saved_video_result(project_path):
    if not project_path:
        return None
    path = Path(project_path)
    try:
        project = json.loads(path.read_text(encoding='utf-8'))
        data = dict(project.get('generated_video_data') or {})
        video = resolve_project_media(project.get('video_path') or data.get('video_path'), path)
        if video:
            data['video_path'] = video
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None
