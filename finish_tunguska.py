import sys
import json
from pathlib import Path

sys.path.append(r"C:\dev\Video-Optimizer-multiplatform")
from advanced_sfx_mixer import apply_advanced_sfx_to_video

draft_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\daily_shorts\2026-06-16_tunguska")
sb_path = draft_dir / "storyboard.json"

with open(sb_path, "r", encoding="utf-8") as f:
    sb = json.load(f)

mp4_files = list(draft_dir.glob("short_*.mp4"))
mp4_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
latest = mp4_files[0]
final_out = draft_dir / "TUNGUSKA_FINAL.mp4"

print(f"Applying advanced SFX to {latest}...")
apply_advanced_sfx_to_video(
    str(latest),
    sb,
    {"swoosh": r"C:\Users\sunse\Downloads\ES_Swooshes, Whoosh, Classic, Fast, No Bass 03 - Epidemic Sound.mp3"},
    str(final_out)
)
print(f"DONE: {final_out}")
