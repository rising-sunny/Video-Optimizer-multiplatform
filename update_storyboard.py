import json
import os
import glob
from pathlib import Path

from local_paths import ARTIFACTS_DIR

ROOT = Path(__file__).resolve().parent
artifacts_dir = ARTIFACTS_DIR
draft_dir = ROOT / "daily_shorts" / "2026-06-10"
storyboard_path = draft_dir / "storyboard.json"

with open(storyboard_path, 'r', encoding='utf-8') as f:
    sb = json.load(f)

# Find the images in artifacts
def get_image(prefix):
    matches = list(artifacts_dir.glob(f"{prefix}_*.png"))
    if matches:
        # Get the latest one if multiple
        matches.sort(key=os.path.getmtime)
        return str(matches[-1])
    return None

for seg in sb.get('segments', []):
    prefix = seg.get('assigned_filename', '')
    img_path = get_image(prefix)
    if img_path:
        seg['image_path'] = img_path
        # Remove video fallbacks so it strictly uses our new image
        seg.pop('video_path', None)
        seg.pop('video_source', None)

with open(storyboard_path, 'w', encoding='utf-8') as f:
    json.dump(sb, f, indent=2, ensure_ascii=False)

print("Storyboard updated successfully with new generated images.")
