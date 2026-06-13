import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))

from daily_short_pipeline import assemble_video
from local_paths import BGM

draft_dir = ROOT / "daily_shorts" / "2026-06-10"
sb_path = draft_dir / "storyboard.json"

with open(sb_path, "r", encoding="utf-8") as f:
    sb = json.load(f)

sb["_manual_bgm_path"] = str(BGM["default"])

print("Comenzando el ensamblado estricto del video...")

assemble_video(
    storyboard=sb,
    output_dir=draft_dir,
    subtitle_style="tiktok",
    pregenerate_images=False,
    strict_existing_visuals=True
)

print("Ensamblado completado.")
