import sys, json, os, shutil
from pathlib import Path

ROOT = Path(r"C:\dev\Video-Optimizer-multiplatform")
draft_dir = ROOT / "daily_shorts" / "2026-06-16"
media_dir = draft_dir / "project_media"
media_dir.mkdir(parents=True, exist_ok=True)

artifact_dir = Path(r"C:\Users\sunse\.gemini\antigravity\brain\34a88839-abc4-4a17-a938-b485d3058ead")
img_prefix = "baltic_seg"

for i in range(8):
    files = list(artifact_dir.glob(f"{img_prefix}{i}_*.png"))
    if files:
        # Sort to get the latest if multiple
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        target_name = "cover.png" if i == 0 else f"seg{i}.png"
        shutil.copy(files[0], media_dir / target_name)
        print(f"Copied {files[0].name} to {target_name}")

sb = {
  "topic": "The Baltic Sea Anomaly",
  "style": "documentary",
  "duration_target": 60,
  "segments": [
    {
      "segment_number": 1,
      "text": "What is this massive object hiding at the bottom of the Baltic Sea?",
      "image_path": str(media_dir / "cover.png"),
      "start": 0.0,
      "duration": 5.0
    },
    {
      "segment_number": 2,
      "text": "In 2011, a deep-sea exploration team stumbled upon a 60-meter circular structure, 90 meters below the surface.",
      "image_path": str(media_dir / "seg1.png"),
      "start": 5.0,
      "duration": 7.0
    },
    {
      "segment_number": 3,
      "text": "It looks eerily like a crashed spaceship, complete with a 300-meter skid mark carved into the ocean floor.",
      "image_path": str(media_dir / "seg2.png"),
      "start": 12.0,
      "duration": 7.0
    },
    {
      "segment_number": 4,
      "text": "Divers reported that as they swam closer, their electronic equipment and satellite phones mysteriously shut down.",
      "image_path": str(media_dir / "seg3.png"),
      "start": 19.0,
      "duration": 8.0
    },
    {
      "segment_number": 5,
      "text": "Many experts claim it's just a glacial deposit left behind from the last Ice Age.",
      "image_path": str(media_dir / "seg4.png"),
      "start": 27.0,
      "duration": 6.5
    },
    {
      "segment_number": 6,
      "text": "But others argue its sharp metallic composition and perfect right angles cannot be natural.",
      "image_path": str(media_dir / "seg5.png"),
      "start": 33.5,
      "duration": 8.0
    },
    {
      "segment_number": 7,
      "text": "Could it be a crashed UFO, a secret World War II device, or something far more ancient?",
      "image_path": str(media_dir / "seg6.png"),
      "start": 41.5,
      "duration": 9.0
    },
    {
      "segment_number": 8,
      "text": "The truth remains buried in the cold, murky depths. What do you think this anomaly really is? Let us know in the comments!",
      "image_path": str(media_dir / "seg7.png"),
      "start": 50.5,
      "duration": 9.5
    }
  ]
}

sb["_manual_bgm_path"] = r"C:\Users\sunse\Downloads\ES_Bitterness - Max Anson.mp3"
sb["_project_path"] = str(draft_dir)

sb_path = draft_dir / "storyboard.json"
with open(sb_path, "w", encoding="utf-8") as f:
    json.dump(sb, f, indent=2, ensure_ascii=False)

print("Created storyboard.json")
