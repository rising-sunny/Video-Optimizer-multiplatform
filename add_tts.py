import sys, json, os
from pathlib import Path

ROOT = Path(r"C:\dev\Video-Optimizer-multiplatform")
sys.path.insert(0, str(ROOT))

from tts_generator import TextToSpeechGenerator

draft_dir = ROOT / "daily_shorts" / "2026-06-16"
sb_path = draft_dir / "storyboard.json"

with open(sb_path, "r", encoding="utf-8") as f:
    sb = json.load(f)

full_script = " ".join([seg["text"] for seg in sb["segments"]])
audio_out = draft_dir / "audio.mp3"

print("Generating TTS for script:", full_script)

tts = TextToSpeechGenerator()
tts.generate_narration(
    script=full_script,
    filename=str(audio_out),
    voice_id="en-US-GuyNeural",
    language="en",
    rate="+5%"
)

sb["audio_path"] = str(audio_out)
sb["script"] = full_script

with open(sb_path, "w", encoding="utf-8") as f:
    json.dump(sb, f, indent=2, ensure_ascii=False)

print(f"Audio generated: {audio_out}")
