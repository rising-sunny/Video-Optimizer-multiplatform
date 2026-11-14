"""Render + metadata in a folder ready for publish.youtube_uploader.upload_from_metadata.

    .venv/bin/python -m codeart.make_short tree            -> auto_videos/codeart/<scene>_<date>/
Upload is a separate, explicit step (unlisted first):
    from publish.youtube_uploader import upload_from_metadata
    upload_from_metadata(folder, privacy_status="unlisted")
"""
import json, sys, time
from pathlib import Path
from .render import render
from .metadata import build_metadata

ROOT = Path(__file__).resolve().parent.parent


def make(scene, seconds=16, params=None, folder=None):
    folder = Path(folder) if folder else ROOT / "auto_videos" / "codeart" / f"{scene}_{time.strftime('%Y%m%d_%H%M%S')}"
    mp4 = render(scene, seconds, folder, params=params)
    info = json.loads((folder / "render_info.json").read_text())
    meta = build_metadata(scene, info["stats"])
    (folder / "metadata.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (folder / "project.json").write_text(json.dumps({"video_path": str(mp4), "config": {"upload_channel": "nostalgic-mood"}}, indent=1))
    (folder / "pad.wav").unlink(missing_ok=True)
    return folder


if __name__ == "__main__":
    print(make(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 16))
