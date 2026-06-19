import json
from pathlib import Path
sb_path = Path(r'C:\dev\Video-Optimizer-multiplatform\daily_shorts\2026-06-16\storyboard.json')
sb = json.load(open(sb_path, encoding='utf-8'))
for i, seg in enumerate(sb['segments']):
    print(f"Seg {i+1}: dur={seg.get('duration')}, start={seg.get('start')}, end={seg.get('end')}")
