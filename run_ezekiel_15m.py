import os
import sys
import json
import time
from pathlib import Path
from pydub import AudioSegment

sys.path.append(str(Path(__file__).resolve().parent))

from auto_video_generator_v2 import AutoVideoGenerator
from daily_short_pipeline import save_storyboard, save_pipeline_state
from local_paths import BGM

def create_looped_audio(input_path, output_path, repeats=10, crossfade_ms=4000):
    print(f"Looping audio {input_path} with crossfade...")
    track = AudioSegment.from_file(input_path)
    looped = track
    for _ in range(repeats - 1):
        looped = looped.append(track, crossfade=crossfade_ms)
    
    looped.export(output_path, format="mp3")
    print(f"Looped audio saved to {output_path}")
    return output_path

def main():
    topic = "The Vision of the Prophet Ezekiel"
    category = "History / Biblical Mysteries"
    duration = 900  # 15 minutes
    
    output_dir = Path(__file__).resolve().parent / "daily_shorts" / "ezekiel_15m"
    output_dir.mkdir(parents=True, exist_ok=True)

    input_audio = str(BGM["ezekiel"])
    looped_audio = output_dir / "ES_Horn_looped.mp3"

    if not looped_audio.exists():
        create_looped_audio(input_audio, str(looped_audio), repeats=10, crossfade_ms=4000)

    generator = AutoVideoGenerator(parent_window=None)
    
    # 1. Load existing storyboard
    print("Loading existing storyboard...")
    sb_path = output_dir / "storyboard.json"
    with open(sb_path, "r", encoding="utf-8") as f:
        sb = json.load(f)
    
    # 2. Pre-generate images with Google AI (Gemini)
    print("Pre-generating images using Google AI (Gemini)...")
    sb = generator.generate_all_images_for_storyboard(
        storyboard_data=sb,
        platform="youtube_long",
        use_real_images=True,
        use_google_images=True,
        image_provider="stability_core",
        style="Photorealism",
        project_path=str(output_dir)
    )
    
    save_storyboard(output_dir, sb)
    
    # 3. Assemble
    print("Assembling video...")
    from dynamic_subtitle_wrapper import patch_subtitle_generation
    patch_subtitle_generation(generator, subtitle_style="hormozi")
    
    res = generator.assemble_video_from_storyboard(
        storyboard_data=sb,
        platform="youtube_long",
        add_subtitles=True,
        subtitle_style="hormozi",
        add_overlays=True,
        manual_bgm_path=str(looped_audio),
        transition_type="Film Burn (Overlay)",
        transition_duration=0.25,
        use_real_images=True,
        use_google_images=True,
        image_provider="stability_core",
        video_provider="none",
        allow_visual_regeneration=False
    )
    
    print(f"Done! Result: {res}")

if __name__ == "__main__":
    main()
