import json
from pathlib import Path

draft_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\daily_shorts\2026-06-16")
sb_path = draft_dir / "storyboard.json"

with open(sb_path, "r", encoding="utf-8") as f:
    sb = json.load(f)

# Original timings were defined like this:
orig_timings = [
    (0.0, 2.5), (2.5, 5.0), (5.0, 8.5), (8.5, 12.0),
    (12.0, 15.5), (15.5, 19.0), (19.0, 23.0), (23.0, 27.0),
    (27.0, 30.25), (30.25, 33.5), (33.5, 37.5), (37.5, 41.5),
    (41.5, 46.0), (46.0, 50.5), (50.5, 60.0)
]

trans_dur = 0.30
segments = sb["segments"]

for i, seg in enumerate(segments):
    orig_start, orig_end = orig_timings[i]
    
    new_start = orig_start + (trans_dur / 2 if i > 0 else 0)
    new_end = orig_end - (trans_dur / 2 if i < len(segments) - 1 else 0)
    
    seg["duration"] = new_end - new_start
    seg["start"] = new_start
    seg["end"] = new_end

with open(sb_path, "w", encoding="utf-8") as f:
    json.dump(sb, f, indent=2, ensure_ascii=False)

print("Fixed storyboard durations for Film Burn!")
