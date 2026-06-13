import os
from pathlib import Path
from PIL import Image

from local_paths import ARTIFACTS_DIR

ROOT = Path(__file__).resolve().parent
src_dir = str(ARTIFACTS_DIR)
dst_dir = str(ROOT / "daily_shorts" / "abaddon_60s" / "generated_media")

os.makedirs(dst_dir, exist_ok=True)

files = [
    ("cover_frame_abaddon_1781232108445.png", "cover_frame.jpg"),
    ("segment_001_abaddon_1781232116237.png", "segment_001.jpg"),
    ("segment_002_abaddon_1781232124792.png", "segment_002.jpg"),
    ("segment_003_abaddon_1781232134816.png", "segment_003.jpg"),
    ("segment_004_abaddon_1781232145533.png", "segment_004.jpg"),
    ("segment_005_abaddon_1781232154751.png", "segment_005.jpg"),
    ("segment_006_abaddon_1781232165029.png", "segment_006.jpg"),
    ("segment_007_abaddon_1781232172913.png", "segment_007.jpg"),
    ("segment_001_abaddon_1781232116237.png", "segment_008.jpg"),  # reuse 1 for 8 due to quota limit
]

for src_name, dst_name in files:
    src_path = os.path.join(src_dir, src_name)
    dst_path = os.path.join(dst_dir, dst_name)
    
    if os.path.exists(src_path):
        with Image.open(src_path) as img:
            rgb_im = img.convert('RGB')
            rgb_im.save(dst_path, 'JPEG', quality=95)
            print(f"Saved {dst_path}")
    else:
        print(f"Not found: {src_path}")
