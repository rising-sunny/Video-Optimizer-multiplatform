import sys, json, shutil
from pathlib import Path

sys.path.append(r"C:\dev\Video-Optimizer-multiplatform")
from daily_short_pipeline import assemble_video
from advanced_sfx_mixer import apply_advanced_sfx_to_video

def main():
    root_dir = Path(r"C:\dev\Video-Optimizer-multiplatform")
    draft_dir = root_dir / "daily_shorts" / "2026-06-16_tunguska"
    media_dir = draft_dir / "project_media"
    media_dir.mkdir(parents=True, exist_ok=True)

    artifact_dir = Path(r"C:\Users\sunse\.gemini\antigravity\brain\34a88839-abc4-4a17-a938-b485d3058ead")
    
    texts_and_durs = [
        ("In 1908, a massive explosion wiped out 80 million trees in Siberia.", 3.5),
        ("The blast was 1,000 times more powerful than the atomic bomb dropped on Hiroshima.", 4.5),
        ("But when scientists finally reached the remote Tunguska region...", 3.0),
        ("...they found something impossible: there was no impact crater.", 3.0),
        ("No meteorite fragments. Nothing but scorched, flattened trees stretching for miles.", 3.5),
        ("Witnesses hundreds of miles away reported the sky splitting in two with fire.", 4.0),
        ("The shockwave knocked people off their feet and broke windows far across Russia.", 4.0),
        ("For days, the night sky over Europe glowed so bright you could read a newspaper.", 4.5),
        ("So, what exactly caused this apocalyptic event?", 2.5),
        ("Some experts believe an icy comet exploded mid-air before hitting the ground.", 4.0),
        ("But others argue a comet would have left a chemical signature...", 3.5),
        ("...and point to something far more sinister or unexplained.", 3.0),
        ("Could it have been a rogue black hole, an antimatter explosion...", 3.5),
        ("...or even an extraterrestrial craft self-destructing high in the atmosphere?", 3.5),
        ("Over a century later, the Tunguska Event remains an unsolved mystery. What do you think happened? Tell us below!", 6.0)
    ]

    # Img mappings
    # 5 is real photo
    img_names = [
        "tunguska_img_1", "tunguska_img_2", "tunguska_img_3", "tunguska_img_4",
        "tunguska_real_1", # 5
        "tunguska_img_6", "tunguska_img_7", "tunguska_img_8", "tunguska_img_9",
        "tunguska_img_10", "tunguska_img_11", "tunguska_img_12", "tunguska_img_13",
        "tunguska_img_14", "tunguska_img_15"
    ]

    segments = []
    current_time = 0.0
    
    for i, (txt, dur) in enumerate(texts_and_durs):
        orig_start = current_time
        orig_end = current_time + dur
        current_time = orig_end
        
        # Apply fix_timings logic
        trans_dur = 0.3
        new_start = orig_start + (trans_dur / 2 if i > 0 else 0)
        new_end = orig_end - (trans_dur / 2 if i < len(texts_and_durs) - 1 else 0)
        clip_dur = new_end - new_start
        
        # Copy image
        img_name = img_names[i]
        src_files = list(artifact_dir.glob(f"{img_name}*.*"))
        if not src_files:
            print(f"ERROR: missing {img_name}")
            return
        src_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        src_file = src_files[0]
        
        ext = src_file.suffix
        target_name = f"seg_{i+1}{ext}"
        target_path = media_dir / target_name
        shutil.copy(src_file, target_path)
        
        segments.append({
            "segment_number": i + 1,
            "text": txt,
            "image_path": str(target_path),
            "assigned_filename": target_name,
            "overlay_tag": "none",
            "start": new_start,
            "duration": clip_dur,
            "end": new_end
        })

    sb = {
        "topic": "The Tunguska Event",
        "category": "history",
        "style": "documentary",
        "duration_target": 60,
        "segments": segments,
        "_manual_bgm_path": r"C:\Users\sunse\Downloads\ES_Bitterness - Max Anson.mp3",
        "_project_path": str(draft_dir)
    }

    # Generate metadata.json
    metadata = {
        "title": "The Tunguska Event: A 1908 Mystery",
        "description": "In 1908, a massive explosion wiped out 80 million trees in Siberia. The blast was 1,000 times more powerful than the Hiroshima bomb, yet left no crater. Was it a comet, a black hole, or a crashed UFO? What do you think happened? #tunguska #mystery #history #unexplained #ufo #siberia #shorts",
        "tags": [
            "tunguska event",
            "mystery",
            "history",
            "unexplained mysteries",
            "ufo",
            "siberia explosion",
            "documentary",
            "shorts",
            "conspiracy"
        ],
        "category_id": "27"
    }
    with open(draft_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    sb_path = draft_dir / "storyboard.json"
    with open(sb_path, "w", encoding="utf-8") as f:
        json.dump(sb, f, indent=2, ensure_ascii=False)

    print("Generating TTS...")
    from tts_generator import TextToSpeechGenerator
    full_script = " ".join([seg["text"] for seg in sb["segments"]])
    audio_out = draft_dir / "audio.mp3"
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

    print("Assemble video...")
    assemble_video(sb, draft_dir, "Film Burn (0.3s)", "Photorealism")
    
    # After assemble, find the mp4
    mp4_files = list(draft_dir.glob("short_*.mp4"))
    if mp4_files:
        mp4_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        latest = mp4_files[0]
        final_out = draft_dir / "TUNGUSKA_FINAL.mp4"
        print("Applying advanced SFX...")
        apply_advanced_sfx_to_video(
            str(latest),
            sb,
            {"swoosh": r"C:\Users\sunse\Downloads\ES_Swooshes And Hits 10 - Epidemic Sound.mp3"},
            str(final_out)
        )
        print(f"DONE: {final_out}")

if __name__ == "__main__":
    main()
