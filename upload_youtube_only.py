import sys
from pathlib import Path

sys.path.append(r"C:\dev\Video-Optimizer-multiplatform")

from daily_short_pipeline import upload_to_youtube

def main():
    draft_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\daily_shorts\2026-06-16")
    
    print("Subiendo a YouTube (Público)...")
    try:
        yt_res = upload_to_youtube(draft_dir, privacy_status="public")
        print(f"Resultado YouTube: {yt_res}")
    except Exception as e:
        print(f"Error YouTube: {e}")

if __name__ == "__main__":
    main()
