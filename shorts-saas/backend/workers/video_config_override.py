"""Override VideoConfig paths for per-project isolation in web mode."""

import os
from pathlib import Path


def configure_for_project(user_id: str, project_id: str):
    """Patch VideoConfig class attributes for this specific project.

    Safe because Celery runs with concurrency=1 (one task per process).
    """
    from core.video_config import VideoConfig

    media_root = Path(os.getenv("APP_MEDIA_DIR", "/app/media"))
    project_dir = media_root / user_id / project_id

    VideoConfig.BASE_DIR = project_dir
    VideoConfig.DOWNLOADS_DIR = project_dir / "downloads"
    VideoConfig.AUDIO_DIR = project_dir / "audio"
    VideoConfig.OUTPUT_DIR = project_dir / "output"
    VideoConfig.TEMP_DIR = project_dir / "temp"
    VideoConfig.BGM_DIR = project_dir / "bgm_library"
    VideoConfig.setup_directories()

    # Ensure FFmpeg is in PATH
    VideoConfig.ensure_ffmpeg_in_path()

    return project_dir
