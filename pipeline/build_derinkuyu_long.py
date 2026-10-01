#!/usr/bin/env python3
"""Build Derinkuyu long-form documentary (EN, ~10-12 min, 16:9)."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from infra.env_loader import load_project_env

load_project_env()

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT = PROJECT_DIR / "long_form" / "derinkuyu_project"
TOPIC = "Derinkuyu: How 20,000 People Lived Underground"
BGM_PATH = Path(r"C:\Users\sunse\Downloads\ES_Boiling Point - Hampus Naeselius.mp3")
VOICE = "en-US-GuyNeural"
SUBTITLE_STYLE = "hormozi"

CHAPTERS = [
    (
        "Chapter 1: The Impossible City",
        "Open with the scale hook: a city for twenty thousand people carved under volcanic rock. "
        "Place it in Cappadocia, Turkey. Establish multi-level tunnels and why this still disturbs modern history.",
    ),
    (
        "Chapter 2: Discovery and Depth",
        "How Derinkuyu was rediscovered in the 1960s. Describe roughly twelve levels, about sixty meters deep, "
        "ventilation shafts, wells, storage rooms, churches, and rolling stone doors. Engineering without modern machines.",
    ),
    (
        "Chapter 3: Refuge Under Siege",
        "Why people went underground: raids in the 7th-8th centuries and later threats. Christian communities sealing doors. "
        "Daily life in darkness: air, water, livestock, silence, fear. How a family survived weeks below.",
    ),
    (
        "Chapter 4: Network of Hidden Cities",
        "Derinkuyu as part of a larger underground network in Cappadocia (Kaymakli connection as carefully framed). "
        "Compare to other subterranean refuges. What archaeologists still debate about dating and peak occupation.",
    ),
    (
        "Chapter 5: Legacy and Open Questions",
        "Later sealing, modern reopening, tourism and heritage. What Derinkuyu proves about ancient engineering and survival. "
        "End with an open question for comments — no long subscribe CTA.",
    ),
]


def _clean_model_text(raw: str) -> str:
    text = (raw or "").strip()
    if "```" in text:
        text = re.sub(r"```[a-zA-Z]*", "", text).replace("```", "")
    return text.strip()


def _split_paragraphs(text: str, need: int = 6) -> list[str]:
    pars = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 20]
    if len(pars) < need - 2:
        pars = [p.strip() for p in text.split("\n") if len(p.strip()) > 20]
    # Hard-cap verbosity: keep first ~40 words per paragraph
    clipped: list[str] = []
    for p in pars:
        words = p.split()
        if len(words) > 45:
            p = " ".join(words[:42]).rstrip(",;:") + "."
        clipped.append(p)
    pars = clipped[:need]
    while len(pars) < need:
        pars.append(
            pars[-1]
            if pars
            else "Deep beneath Cappadocia, the tunnels keep their silence."
        )
    return pars


def _trim_segments_to_word_budget(segments: list[dict], max_words: int = 1600) -> list[dict]:
    """Keep segment order but drop trailing segments once word budget is hit."""
    kept: list[dict] = []
    total = 0
    for s in segments:
        w = len((s.get("text") or "").split())
        if kept and total + w > max_words:
            break
        kept.append(s)
        total += w
    # reindex
    for i, s in enumerate(kept, 1):
        s["segment_id"] = i
        s["assigned_filename"] = f"seg_{i:03d}"
    return kept


def _log(msg: str) -> None:
    print(msg, flush=True)


def _save_storyboard(storyboard: dict) -> None:
    (OUT / "storyboard.json").write_text(
        json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def generate_storyboard_and_tts() -> dict:
    from ai.groq_client import GroqAiClient
    from pydub import AudioSegment
    from pipeline.tts_generator import TextToSpeechGenerator

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "project_media").mkdir(exist_ok=True)
    media_tmp = OUT / "temp" / "generated_media"
    media_tmp.mkdir(parents=True, exist_ok=True)

    client = GroqAiClient()
    if not getattr(client, "client", None):
        raise RuntimeError("Groq client not available")

    all_segments: list[dict] = []
    full_script_parts: list[str] = []
    seg_id = 1

    for chap_i, (chap_title, chap_brief) in enumerate(CHAPTERS, 1):
        _log(f"\n=== [{chap_i}/{len(CHAPTERS)}] {chap_title} ===")
        script_prompt = f"""You write documentary narration for YouTube long-form (English, Stunning Revelations channel).

Topic: {TOPIC}
Section: {chap_title}
Brief: {chap_brief}

HARD LIMITS (non-negotiable):
1. Write ONLY spoken narration text (no stage directions, no narrator labels).
2. TOTAL for this section: 180-200 words MAX.
3. EXACTLY 6 short paragraphs.
4. Each paragraph: 28-35 words MAX.
5. Separate paragraphs with a blank line.
6. Documentary tone: sober, mysterious, credible.
7. No "subscribe", no "in this video", no listicle filler.
8. Include concrete numbers and proper names where accurate.
9. Return ONLY the 6 paragraphs — nothing else.
"""
        raw = client._generate(script_prompt, max_tokens=700, task_type="script_quality")
        if not raw or str(raw).startswith("ERROR"):
            raise RuntimeError(f"Chapter failed: {chap_title}: {raw}")
        pars = _split_paragraphs(_clean_model_text(raw), need=6)
        words = sum(len(p.split()) for p in pars)
        _log(f"  paragraphs={len(pars)} words={words}")

        batch_text = "\n\n".join(f"SEGMENT {i+1}:\n{p}" for i, p in enumerate(pars))
        visual_prompt_req = f"""For each of the 6 documentary narration segments about Derinkuyu underground city, write ONE English image prompt.

RULES:
- Cinematic documentary photorealism, horizontal 16:9 composition, dramatic lighting, historical accuracy for Cappadocia / Byzantine-era underground city.
- No modern anachronisms unless the segment is modern tourism/archaeology.
- End every prompt with: no text, no writing, no signs, no captions, no watermarks
- Return ONLY valid JSON array of 6 objects with keys text and visual_prompt.
- text must match the original paragraph.
- Keep each visual_prompt under 60 words.

SEGMENTS:
{batch_text}
"""
        vraw = client._generate(visual_prompt_req, max_tokens=1800, task_type="script_quality")
        vraw = _clean_model_text(vraw)
        try:
            vdata = json.loads(vraw)
            if not isinstance(vdata, list):
                raise ValueError("not a list")
        except Exception as e:
            _log(f"  visual JSON fallback ({e})")
            vdata = [
                {
                    "text": p,
                    "visual_prompt": (
                        f"Cinematic documentary view of Derinkuyu underground city Cappadocia related to: {p[:120]}, "
                        "photorealistic 35mm, atmospheric torchlight, no text, no writing, no signs, no captions, no watermarks"
                    ),
                }
                for p in pars
            ]

        for i, p in enumerate(pars):
            item = vdata[i] if i < len(vdata) else {}
            vp = item.get("visual_prompt") or (
                "Cinematic Derinkuyu underground scene, photorealistic, no text, no watermarks"
            )
            if "no text" not in vp.lower():
                vp += ", no text, no writing, no signs, no captions, no watermarks"
            all_segments.append(
                {
                    "segment_id": seg_id,
                    "chapter": chap_title,
                    "text": p,
                    "narration_text": p,
                    "visual_prompt": vp,
                    "assigned_filename": f"seg_{seg_id:03d}",
                    "sfx_tag": "none",
                    "overlay_tag": "none",
                }
            )
            full_script_parts.append(p)
            seg_id += 1

        # Checkpoint after each chapter (before TTS)
        partial = {
            "topic": TOPIC,
            "category": "Lost Civilizations",
            "storyboard_format": "long_form_16_9",
            "platform": "youtube_long",
            "script": " ".join(full_script_parts),
            "segments": all_segments,
            "status": f"script_partial_chapter_{chap_i}",
            "language": "en",
            "_subtitle_style": SUBTITLE_STYLE,
            "_project_path": str(OUT.resolve()),
        }
        _save_storyboard(partial)
        _log(f"  checkpoint saved ({len(all_segments)} segs)")

    all_segments = _trim_segments_to_word_budget(all_segments, max_words=1600)
    full_script_parts = [s["text"] for s in all_segments]
    full_script = " ".join(full_script_parts)
    _log(f"\nTOTAL segments after budget trim: {len(all_segments)}")
    _log(f"TOTAL words: {len(full_script.split())}")
    _log(f"Est. @140 wpm: {len(full_script.split()) / 140:.1f} min")

    # TTS by chapter chunks to avoid long hangs
    _log("\nGenerating TTS by chapter chunks...")
    tts = TextToSpeechGenerator()
    chapter_audio_paths: list[Path] = []
    by_chapter: dict[str, list[str]] = {}
    for s in all_segments:
        by_chapter.setdefault(s["chapter"], []).append(s["text"])

    for i, (chap_title, _) in enumerate(CHAPTERS, 1):
        chap_pars = by_chapter.get(chap_title, [])
        if not chap_pars:
            continue
        chap_text = " ".join(chap_pars)
        chap_audio = media_tmp / f"chapter_{i:02d}.mp3"
        _log(f"  TTS chapter {i}/{len(CHAPTERS)} -> {chap_audio.name} ({len(chap_text.split())} words)")
        ok = tts.generate_narration(
            chap_text, str(chap_audio), voice_id=VOICE, rate="+5%"
        )
        if not ok or not chap_audio.exists() or chap_audio.stat().st_size < 1000:
            raise RuntimeError(f"TTS failed for chapter {i}")
        chapter_audio_paths.append(chap_audio)
        _log(f"    ok size={chap_audio.stat().st_size}")

    audio_path = media_tmp / "narration.mp3"
    combined = AudioSegment.empty()
    for p in chapter_audio_paths:
        combined += AudioSegment.from_file(str(p))
    combined.export(str(audio_path), format="mp3")
    dur_s = len(combined) / 1000.0
    _log(f"Audio duration: {dur_s:.1f}s ({dur_s/60:.2f} min) -> {audio_path}")

    total_words = sum(max(1, len(s["text"].split())) for s in all_segments)
    t = 0.0
    for s in all_segments:
        w = max(1, len(s["text"].split()))
        d = dur_s * (w / total_words)
        s["start"] = t
        s["end"] = t + d
        s["duration"] = d
        s["start_time"] = t
        s["end_time"] = t + d
        t += d

    storyboard = {
        "topic": TOPIC,
        "category": "Lost Civilizations",
        "storyboard_format": "long_form_16_9",
        "platform": "youtube_long",
        "script": full_script,
        "audio_path": str(audio_path.resolve()),
        "segments": all_segments,
        "source_short": "https://youtube.com/shorts/nB9sOizqRO0",
        "target_duration_min": 10,
        "language": "en",
        "status": "storyboard_ready",
        "_subtitle_style": SUBTITLE_STYLE,
        "_project_path": str(OUT.resolve()),
    }
    if BGM_PATH.exists():
        storyboard["_manual_bgm_path"] = str(BGM_PATH)

    _save_storyboard(storyboard)
    (OUT / "idea.json").write_text(
        json.dumps(
            {
                "title": TOPIC,
                "category": "Lost Civilizations",
                "source_short": "20,000 Hidden: Derinkuyu's Secret City",
                "format": "long_form_10_12_min",
                "url_short": "https://youtube.com/shorts/nB9sOizqRO0",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _log(f"Saved storyboard -> {OUT / 'storyboard.json'}")
    return storyboard


def generate_images(storyboard: dict, image_provider: str = "flux_dev") -> dict:
    from pipeline.daily_short_pipeline import generate_images_for_draft, save_storyboard

    _log(f"\nGenerating images with provider={image_provider}...")
    sb, state = generate_images_for_draft(
        OUT,
        storyboard,
        image_provider=image_provider,
        visual_style="Photorealism",
        platform="youtube_long",
    )
    save_storyboard(OUT, sb)
    ready = sum(1 for s in sb.get("segments", []) if s.get("image_path"))
    _log(f"Images ready: {ready}/{len(sb.get('segments', []))}")
    _log(f"State: {state.get('status') if isinstance(state, dict) else state}")
    return sb


def assemble(storyboard: dict) -> str:
    from pipeline.daily_short_pipeline import assemble_video

    bgm = storyboard.get("_manual_bgm_path")
    if bgm and Path(bgm).exists():
        storyboard["_manual_bgm_path"] = bgm
    elif BGM_PATH.exists():
        storyboard["_manual_bgm_path"] = str(BGM_PATH)

    _log("\nAssembling long-form video...")
    video = assemble_video(
        storyboard,
        OUT,
        image_provider="auto",
        video_provider="none",
        pregenerate_images=False,
        strict_existing_visuals=True,
        platform="youtube_long",
        subtitle_style=SUBTITLE_STYLE,
        transition_type="Fade Smooth",
        transition_duration=0.3,
        visual_style="Photorealism",
    )
    _log(f"VIDEO: {video}")
    if video:
        final = OUT / "DERINKUYU_DOCUMENTARY.mp4"
        shutil.copy2(video, final)
        _log(f"Final copy: {final}")
        return str(final)
    return ""


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    mode = argv[0] if argv else "all"
    # modes: script | images | assemble | all

    sb_path = OUT / "storyboard.json"
    if mode in ("all", "script"):
        sb = generate_storyboard_and_tts()
    elif sb_path.exists():
        sb = json.loads(sb_path.read_text(encoding="utf-8"))
        _log(f"Loaded existing storyboard ({len(sb.get('segments', []))} segs)")
    else:
        sb = generate_storyboard_and_tts()

    if mode in ("all", "images"):
        provider = "flux_dev"
        if len(argv) > 1:
            provider = argv[1]
        sb = generate_images(sb, image_provider=provider)

    if mode in ("all", "assemble"):
        # reload latest sb
        if sb_path.exists():
            sb = json.loads(sb_path.read_text(encoding="utf-8"))
        assemble(sb)

    _log("\nDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
