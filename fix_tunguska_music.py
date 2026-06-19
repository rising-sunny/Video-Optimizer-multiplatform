import sys
import json
from pathlib import Path

sys.path.append(r"C:\dev\Video-Optimizer-multiplatform")
from daily_short_pipeline import assemble_video
from advanced_sfx_mixer import apply_advanced_sfx_to_video

draft_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\daily_shorts\2026-06-16_tunguska")
sb_path = draft_dir / "storyboard.json"

with open(sb_path, "r", encoding="utf-8") as f:
    sb = json.load(f)

# Update the music
sb["_manual_bgm_path"] = r"C:\Users\sunse\Downloads\ES_Boiling Point - Hampus Naeselius.mp3"

# Re-assemble video specifically pointing out the keyword arguments!
print("Re-assembling video with correct kwargs and new music...")
assemble_video(
    sb, 
    draft_dir, 
    transition_type="Film Burn (0.3s)", 
    visual_style="Photorealism"
)

# After assemble, find the newly generated mp4
mp4_files = list(draft_dir.glob("short_*.mp4"))
mp4_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
latest = mp4_files[0]
final_out = draft_dir / "TUNGUSKA_FINAL_V2.mp4"

print(f"Applying advanced SFX to {latest}...")
apply_advanced_sfx_to_video(
    str(latest),
    sb,
    {"swoosh": r"C:\Users\sunse\Downloads\ES_Swooshes, Whoosh, Classic, Fast, No Bass 03 - Epidemic Sound.mp3"},
    str(final_out)
)
print(f"DONE: {final_out}")
