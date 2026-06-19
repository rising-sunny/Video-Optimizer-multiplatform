import sys
from pathlib import Path

sys.path.append(r"C:\dev\Video-Optimizer-multiplatform")

from daily_short_pipeline import (
    upload_to_youtube,
    upload_to_facebook,
    upload_to_instagram
)

def main():
    draft_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\daily_shorts\2026-06-16_tunguska")
    
    print("1. Subiendo a YouTube (Público)...")
    try:
        yt_res = upload_to_youtube(draft_dir, privacy_status="public")
        print(f"Resultado YouTube: {yt_res}")
    except Exception as e:
        print(f"Error YouTube: {e}")

    print("\n2. Subiendo a Facebook (Público)...")
    try:
        fb_res = upload_to_facebook(draft_dir, video_state="PUBLISHED")
        print(f"Resultado Facebook: {fb_res}")
    except Exception as e:
        print(f"Error Facebook: {e}")

    print("\n3. Subiendo a Instagram (Reels Público)...")
    try:
        ig_res = upload_to_instagram(draft_dir)
        print(f"Resultado Instagram: {ig_res}")
    except Exception as e:
        print(f"Error Instagram: {e}")

    print("\n¡Publicación completada!")

if __name__ == "__main__":
    main()
