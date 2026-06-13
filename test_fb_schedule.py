import os
import sys
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

import facebook_uploader

def main():
    print("Probando subida a Facebook como SCHEDULED...")
    
    video_path = "test.mp4"
    if not os.path.exists(video_path):
        print(f"Error: No se encontró un video para probar ({video_path}) en el directorio actual.")
        sys.exit(1)
            
    # Try different scheduled times
    times_to_test = [
        ("en 30 minutos", (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("en 60 minutos", (datetime.now(timezone.utc) + timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("en 24 horas", (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("en 48 horas", (datetime.now(timezone.utc) + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        # From user logs
        ("Log exacto del error", "2026-04-14T16:19:14Z"),
    ]

    for label, publish_time in times_to_test:
        print(f"\n--- Probando '{label}' con tiempo {publish_time} ---")
        try:
            resultado = facebook_uploader.upload_video(
                video_path=video_path,
                title=f"Test Schedule {label}",
                description="Testing schedule limit.",
                video_state="SCHEDULED",
                scheduled_publish_time=publish_time
            )
            print("¡ÉXITO!")
            print(f"Video ID: {resultado.get('video_id')}")
        except Exception as e:
            print(f"Error ({label}): {repr(e)}")

if __name__ == "__main__":
    main()
