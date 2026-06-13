import json
import sys
from pathlib import Path

sys.path.append(r"G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform")

from daily_short_pipeline import (
    generate_platform_metadata,
    upload_to_youtube,
    upload_to_facebook,
    upload_to_instagram
)

def main():
    draft_dir = Path(r"G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\daily_shorts\abaddon_60s")
    sb_path = draft_dir / "storyboard.json"

    with open(sb_path, "r", encoding="utf-8") as f:
        sb = json.load(f)

    print("1. Generando metadata para las redes...")
    generate_platform_metadata(sb, draft_dir)

    publish_time = "2026-06-12T07:00:00-04:00"
    
    print(f"\n2. Subiendo a YouTube (Programado para {publish_time})...")
    yt_res = upload_to_youtube(draft_dir, privacy_status="private", publish_at=publish_time)
    print(f"Resultado YouTube: {yt_res}")

    print(f"\n3. Subiendo a Facebook (Programado para {publish_time})...")
    fb_res = upload_to_facebook(draft_dir, video_state="SCHEDULED", publish_at=publish_time)
    print(f"Resultado Facebook: {fb_res}")

    print(f"\n4. Subiendo a Instagram (Programado para {publish_time})...")
    ig_res = upload_to_instagram(draft_dir, publish_at=publish_time)
    print(f"Resultado Instagram: {ig_res}")

    print("\n¡Carga completada!")

if __name__ == "__main__":
    main()
