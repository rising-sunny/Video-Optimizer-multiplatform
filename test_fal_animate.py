"""
Test: Upload + animate test_fal_roman_soldiers.jpg via FAL.AI I2V (Kling-standard).
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

# Load .env
def _load_env():
    for name in (".env", ".env.txt"):
        p = os.path.join(os.path.dirname(__file__), name)
        if os.path.exists(p):
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip())
            print(f"[env] Loaded {name}")
            return
    print("[env] No .env file found")

_load_env()

import fal_client as _fal_sdk
from fal_ai_client import FalAiVideoClient

IMAGE_PATH = os.path.join(os.path.dirname(__file__), "auto_videos", "temp", "test_fal_roman_soldiers.jpg")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "auto_videos", "temp", "test_fal_roman_animation.mp4")
MOTION_PROMPT = (
    "slow dramatic camera push forward through foggy ancient forest, "
    "torches flickering, dust particles and smoke drifting, cinematic lighting, epic atmosphere"
)

def log(msg):
    print(msg)

print(f"[test] Image: {IMAGE_PATH}")
print(f"[test] Exists: {os.path.exists(IMAGE_PATH)}, size: {os.path.getsize(IMAGE_PATH)//1024}KB")

# Step 1: Upload local file to FAL CDN
print("\n[step 1] Uploading image to FAL CDN...")
t0 = time.time()
try:
    image_url = _fal_sdk.upload_file(IMAGE_PATH)
    print(f"[step 1] Uploaded in {time.time()-t0:.1f}s -> {image_url}")
except Exception as e:
    print(f"[step 1] FAILED: {e}")
    sys.exit(1)

# Step 2: Animate via Kling-standard I2V
print("\n[step 2] Generating I2V animation (Kling-standard, 5s, 9:16)...")
vid_client = FalAiVideoClient(log_callback=log)
t1 = time.time()
result = vid_client.image_to_video(
    image_url=image_url,
    prompt=MOTION_PROMPT,
    output_path=OUTPUT_PATH,
    model="kling-standard",
    duration=5,
    aspect_ratio="9:16",
)
elapsed = time.time() - t1

if result:
    size_kb = os.path.getsize(result) // 1024
    print(f"\n[OK] Video saved: {result}")
    print(f"     Size: {size_kb} KB | Generation time: {elapsed:.1f}s")
else:
    print(f"\n[FAILED] {vid_client.last_error}")
    sys.exit(1)
