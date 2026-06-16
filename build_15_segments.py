import json, shutil, os
from pathlib import Path

draft_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\daily_shorts\2026-06-16")
sb_path = draft_dir / "storyboard.json"

media_dir = draft_dir / "project_media"

art_dir = Path(r"C:\Users\sunse\.gemini\antigravity\brain\34a88839-abc4-4a17-a938-b485d3058ead")

def get_latest(prefix):
    files = list(art_dir.glob(f"{prefix}_*.png"))
    if not files: return None
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return files[0]

new_imgs = {
    "1b": get_latest("baltic_new2"),
    "2b": get_latest("baltic_new4"),
    "3b": get_latest("baltic_new6"),
    "4b": get_latest("baltic_new8"),
    "5b": get_latest("baltic_new10"),
    "6b": get_latest("baltic_new12"),
    "7b": get_latest("baltic_new14")
}

for k, v in new_imgs.items():
    if v:
        shutil.copy(v, media_dir / f"new_{k}.png")
        print(f"Copied {v.name} to new_{k}.png")

with open(sb_path, "r", encoding="utf-8") as f:
    sb = json.load(f)

new_segments = []

new_segments.append({
    "segment_number": 1,
    "text": "What is this massive object hiding",
    "image_path": str(media_dir / "cover.png"),
    "start": 0.0,
    "duration": 2.5,
    "assigned_filename": "cover.png", "overlay_tag": "none", "sfx_tag": "none"
})
new_segments.append({
    "segment_number": 2,
    "text": "at the bottom of the Baltic Sea?",
    "image_path": str(media_dir / "new_1b.png"),
    "start": 2.5,
    "duration": 2.5,
    "assigned_filename": "new_1b.png", "overlay_tag": "none", "sfx_tag": "none"
})

new_segments.append({
    "segment_number": 3,
    "text": "In 2011, a deep-sea exploration team stumbled upon",
    "image_path": str(media_dir / "seg1.png"),
    "start": 5.0,
    "duration": 3.5,
    "assigned_filename": "seg1.png", "overlay_tag": "none", "sfx_tag": "none"
})
new_segments.append({
    "segment_number": 4,
    "text": "a 60-meter circular structure, 90 meters below the surface.",
    "image_path": str(media_dir / "new_2b.png"),
    "start": 8.5,
    "duration": 3.5,
    "assigned_filename": "new_2b.png", "overlay_tag": "none", "sfx_tag": "none"
})

new_segments.append({
    "segment_number": 5,
    "text": "It looks eerily like a crashed spaceship,",
    "image_path": str(media_dir / "seg2.png"),
    "start": 12.0,
    "duration": 3.5,
    "assigned_filename": "seg2.png", "overlay_tag": "none", "sfx_tag": "none"
})
new_segments.append({
    "segment_number": 6,
    "text": "complete with a 300-meter skid mark carved into the ocean floor.",
    "image_path": str(media_dir / "new_3b.png"),
    "start": 15.5,
    "duration": 3.5,
    "assigned_filename": "new_3b.png", "overlay_tag": "none", "sfx_tag": "none"
})

new_segments.append({
    "segment_number": 7,
    "text": "Divers reported that as they swam closer,",
    "image_path": str(media_dir / "seg3.png"),
    "start": 19.0,
    "duration": 4.0,
    "assigned_filename": "seg3.png", "overlay_tag": "none", "sfx_tag": "none"
})
new_segments.append({
    "segment_number": 8,
    "text": "their electronic equipment and satellite phones mysteriously shut down.",
    "image_path": str(media_dir / "new_4b.png"),
    "start": 23.0,
    "duration": 4.0,
    "assigned_filename": "new_4b.png", "overlay_tag": "none", "sfx_tag": "none"
})

new_segments.append({
    "segment_number": 9,
    "text": "Many experts claim it's just a glacial deposit",
    "image_path": str(media_dir / "seg4.png"),
    "start": 27.0,
    "duration": 3.25,
    "assigned_filename": "seg4.png", "overlay_tag": "none", "sfx_tag": "none"
})
new_segments.append({
    "segment_number": 10,
    "text": "left behind from the last Ice Age.",
    "image_path": str(media_dir / "new_5b.png"),
    "start": 30.25,
    "duration": 3.25,
    "assigned_filename": "new_5b.png", "overlay_tag": "none", "sfx_tag": "none"
})

new_segments.append({
    "segment_number": 11,
    "text": "But others argue its sharp metallic composition",
    "image_path": str(media_dir / "seg5.png"),
    "start": 33.5,
    "duration": 4.0,
    "assigned_filename": "seg5.png", "overlay_tag": "none", "sfx_tag": "none"
})
new_segments.append({
    "segment_number": 12,
    "text": "and perfect right angles cannot be natural.",
    "image_path": str(media_dir / "new_6b.png"),
    "start": 37.5,
    "duration": 4.0,
    "assigned_filename": "new_6b.png", "overlay_tag": "none", "sfx_tag": "none"
})

new_segments.append({
    "segment_number": 13,
    "text": "Could it be a crashed UFO, a secret World War II device,",
    "image_path": str(media_dir / "seg6.png"),
    "start": 41.5,
    "duration": 4.5,
    "assigned_filename": "seg6.png", "overlay_tag": "none", "sfx_tag": "none"
})
new_segments.append({
    "segment_number": 14,
    "text": "or something far more ancient?",
    "image_path": str(media_dir / "new_7b.png"),
    "start": 46.0,
    "duration": 4.5,
    "assigned_filename": "new_7b.png", "overlay_tag": "none", "sfx_tag": "none"
})

new_segments.append({
    "segment_number": 15,
    "text": "The truth remains buried in the cold, murky depths. What do you think this anomaly really is? Let us know in the comments!",
    "image_path": str(media_dir / "seg7.png"),
    "start": 50.5,
    "duration": 9.5,
    "assigned_filename": "seg7.png", "overlay_tag": "none", "sfx_tag": "none"
})

sb["segments"] = new_segments

with open(sb_path, "w", encoding="utf-8") as f:
    json.dump(sb, f, indent=2, ensure_ascii=False)

print("Updated storyboard.json to 15 segments")
