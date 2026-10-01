#!/usr/bin/env python3
"""long_form_builder.py — reusable long-form (documentary) builder.

Generates a full 8-15 min YouTube documentary from a *topic*, using the channel
Bible (``channel_strategy.py`` / ``daily_shorts/channel_strategy_profile.json``)
for tone, hook rules, voice, and visual style. It leaves the project ready to
upload — video + ``metadata.json`` / ``youtube_metadata.json`` (long-form aware,
``is_short: False``, auto chapters) — but NEVER auto-uploads.

This is the reusable counterpart to the one-off ``build_derinkuyu_long.py``:
topic and chapter outline are dynamic instead of hardcoded.

CLI:
    python long_form_builder.py "The Antikythera Mechanism" --minutes 10
    python long_form_builder.py "Topic" --minutes 12 --no-assemble   # script + metadata only
    python long_form_builder.py "Topic" --provider flux_dev --category "Lost Civilizations"

Import / agent use:
    from pipeline.long_form_builder import build_long_form
    result = build_long_form("The Antikythera Mechanism", minutes=10)
    # then, only when you decide to publish:
    #   from pipeline.daily_short_pipeline import upload_to_youtube
    #   upload_to_youtube(Path(result["output_dir"]), privacy_status="unlisted")
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from infra.env_loader import load_project_env

load_project_env()

PROJECT_DIR = Path(__file__).resolve().parent.parent

from channel.channel_strategy import (  # noqa: E402
    get_channel_strategy,
    get_narration_tone,
    build_hook_prompt_instructions,
    validate_hook,
)

# Effective narration pace of this TTS setup incl. pauses/SFX (empirical, ~from
# the Derinkuyu build: ~1600 words -> ~14 min). Used only for the word budget
# and provisional timings; real timings come from the generated audio.
EFFECTIVE_WPM = 120


def _log(msg: str) -> None:
    print(msg, flush=True)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").lower()).strip("_")
    return (s or "long_form")[:40]


def _clean_model_text(raw: str) -> str:
    text = (raw or "").strip()
    if "```" in text:
        text = re.sub(r"```[a-zA-Z]*", "", text).replace("```", "")
    return text.strip()


def _split_paragraphs(text: str, need: int) -> list[str]:
    pars = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 20]
    if len(pars) < max(1, need - 2):
        pars = [p.strip() for p in text.split("\n") if len(p.strip()) > 20]
    clipped: list[str] = []
    for p in pars:
        words = p.split()
        if len(words) > 45:
            p = " ".join(words[:42]).rstrip(",;:") + "."
        clipped.append(p)
    pars = clipped[:need]
    while len(pars) < need and pars:
        pars.append(pars[-1])
    return pars


def _extract_json_array(raw: str):
    txt = _clean_model_text(raw)
    try:
        data = json.loads(txt)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    m = re.search(r"\[.*\]", txt, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _resolve_config() -> dict:
    strat = get_channel_strategy()
    ps = strat.get("production_stack", {}) or {}
    tts = strat.get("tts", {}) or {}
    ident = strat.get("channel_identity", {}) or {}
    return {
        "voice": ps.get("voice") or tts.get("default_voice", "en-US-GuyNeural"),
        "voice_rate": ps.get("voice_rate") or tts.get("rate", "+5%"),
        "subtitle_style": ps.get("subtitle_style") or strat.get("subtitle_style", "hormozi"),
        "visual_style": strat.get("visual_style", "Photorealism"),
        "transition_type": strat.get("transition_type", "Fade Smooth"),
        "transition_duration": strat.get("transition_duration", 0.3),
        "language": ident.get("language", "en"),
        "niche": ident.get("niche", "history, historical mysteries"),
    }


def _plan_dimensions(minutes: int) -> tuple[int, int, int]:
    """Return (n_chapters, paragraphs_per_chapter, word_budget)."""
    n_chapters = max(3, min(6, round(minutes / 2.2)))
    target_segments = max(minutes * 5, n_chapters * 5)
    paragraphs_per_chapter = max(5, min(12, round(target_segments / n_chapters)))
    word_budget = int(minutes * 155)
    return n_chapters, paragraphs_per_chapter, word_budget


def _generate_chapter_outline(client, topic: str, category: str, n_chapters: int) -> list[dict]:
    from channel.channel_strategy import get_channel_name, get_channel_audience_line
    prompt = f"""You are a documentary story editor for the YouTube channel "{get_channel_name()}"
(niche: {get_channel_audience_line()}).

Design the chapter outline for a {n_chapters}-chapter long-form documentary about:
"{topic}" (category: {category or 'history'}).

Rules:
- EXACTLY {n_chapters} chapters that build a narrative arc: hook/impossible premise ->
  context/discovery -> development/evidence -> twist or human-scale consequence -> legacy/open question.
- Chapter 1 must be a cold-open hook grounded in a concrete number, scale, or date.
- Titles are short and evocative (no "Chapter N" prefix, no numbering).
- Each brief is 1-2 sentences telling the writer what that chapter covers (concrete, documented).

Return ONLY a JSON array of exactly {n_chapters} objects: {{"title": "...", "brief": "..."}}"""
    try:
        raw = client._generate(prompt, max_tokens=1200, task_type="script_quality")
        data = _extract_json_array(raw)
        if data and len(data) >= 3:
            out = []
            for item in data[:n_chapters]:
                t = str(item.get("title") or "").strip()
                b = str(item.get("brief") or "").strip()
                if t:
                    out.append({"title": t, "brief": b or t})
            if len(out) >= 3:
                return out
    except Exception as e:
        _log(f"  [outline] LLM failed ({e}); using generic structure")

    # Fallback: generic documentary arc
    base = [
        ("The Impossible Premise", f"Open with the scale hook and place {topic} in time and place."),
        ("Discovery and Context", f"How {topic} came to light and the world around it."),
        ("Evidence and Development", f"The core events, evidence, and rival theories about {topic}."),
        ("The Twist", f"The reveal, consequence, or human-scale cost of {topic}."),
        ("Legacy and Open Questions", f"What {topic} left behind and what remains unexplained."),
    ]
    return [{"title": t, "brief": b} for t, b in base[:n_chapters]]


def _generate_chapter_script(client, topic, chap_title, chap_brief,
                             n_paragraphs, is_first, tone_line, hook_instr) -> list[str]:
    hook_block = ""
    if is_first and hook_instr:
        hook_block = (
            "\nThis is the COLD OPEN. Apply these hook rules to the very first paragraph:\n"
            f"{hook_instr}\n"
        )
    from channel.channel_strategy import get_channel_name
    script_prompt = f"""You write documentary narration for YouTube long-form (English, "{get_channel_name()}").

Topic: {topic}
Section: {chap_title}
Brief: {chap_brief}
{hook_block}
HARD LIMITS (non-negotiable):
1. Write ONLY spoken narration text (no stage directions, no narrator labels, no headings).
2. EXACTLY {n_paragraphs} short paragraphs.
3. Each paragraph: 25-34 words.
4. Separate paragraphs with a blank line.
5. Tone: {tone_line}.
6. No "subscribe", no "in this video", no listicle filler.
7. Use concrete numbers, dates, and proper names where accurate.
8. Return ONLY the {n_paragraphs} paragraphs — nothing else.
"""
    raw = client._generate(script_prompt, max_tokens=900, task_type="script_quality")
    if not raw or str(raw).startswith("ERROR"):
        raise RuntimeError(f"Chapter script failed for '{chap_title}': {raw}")
    return _split_paragraphs(_clean_model_text(raw), need=n_paragraphs)


def _generate_visual_prompts(client, topic, paragraphs) -> list[str]:
    batch_text = "\n\n".join(f"SEGMENT {i+1}:\n{p}" for i, p in enumerate(paragraphs))
    req = f"""For each of the {len(paragraphs)} documentary narration segments about "{topic}", write ONE English image prompt.

RULES:
- Cinematic documentary photorealism, horizontal 16:9 composition, dramatic lighting, historically plausible.
- No modern anachronisms unless the segment is explicitly modern (tourism/archaeology).
- End every prompt with: no text, no writing, no signs, no captions, no watermarks
- Keep each prompt under 60 words.
- Return ONLY a valid JSON array of {len(paragraphs)} objects with keys "text" and "visual_prompt". text must match the paragraph.

SEGMENTS:
{batch_text}
"""
    prompts: list[str] = []
    try:
        raw = client._generate(req, max_tokens=2000, task_type="script_quality")
        data = _extract_json_array(raw)
        if isinstance(data, list):
            for i in range(len(paragraphs)):
                vp = ""
                if i < len(data) and isinstance(data[i], dict):
                    vp = str(data[i].get("visual_prompt") or "").strip()
                prompts.append(vp)
    except Exception as e:
        _log(f"  [visuals] batch failed ({e}); using fallback prompts")

    while len(prompts) < len(paragraphs):
        prompts.append("")
    for i, p in enumerate(paragraphs):
        if not prompts[i]:
            prompts[i] = (
                f"Cinematic documentary scene about {topic}, related to: {p[:110]}, "
                "photorealistic 35mm, atmospheric lighting, historical realism"
            )
        if "no text" not in prompts[i].lower():
            prompts[i] += ", no text, no writing, no signs, no captions, no watermarks"
    return prompts


def _assign_provisional_timings(segments: list[dict]) -> None:
    """Estimate start/end from word counts (replaced by real audio timings later)."""
    t = 0.0
    for s in segments:
        w = max(1, len((s.get("text") or "").split()))
        d = max(1.5, w / EFFECTIVE_WPM * 60.0)
        s["start"] = t
        s["end"] = t + d
        s["start_time"] = t
        s["end_time"] = t + d
        s["duration"] = d
        t += d


def build_long_form(
    topic: str,
    minutes: int = 10,
    category: str | None = None,
    output_dir: str | Path | None = None,
    image_provider: str = "flux_dev",
    assemble: bool = True,
    tts: bool | None = None,
    write_metadata: bool = True,
    source_short_url: str | None = None,
    bgm_path: str | None = None,
) -> dict:
    """Build a long-form documentary end-to-end (no upload).

    Args:
        topic: The subject, e.g. "The Antikythera Mechanism".
        minutes: Target length (8-15 recommended). Drives script volume; the real
            duration comes from the generated narration.
        category: Optional channel category label (defaults inferred).
        output_dir: Where to build. Defaults to long_form/<slug>_project.
        image_provider: Image backend for the heavy render step (e.g. "flux_dev").
        assemble: If True, generate images + render the final MP4. If False, only
            storyboard (+ metadata) are produced.
        tts: Generate narration audio (needed for accurate timings). Defaults to
            ``assemble``. Provisional word-based timings are always set so chapters
            work even without audio.
        write_metadata: Generate + save long-form YouTube/FB/IG metadata files.
        source_short_url: Optional winning-short URL this documentary expands.
        bgm_path: Optional background-music file.

    Returns:
        dict with keys: output_dir, storyboard_path, video_path, metadata,
        duration_s, chapters, status.
    """
    if not topic or not topic.strip():
        raise ValueError("topic is required")
    if tts is None:
        tts = assemble

    cfg = _resolve_config()
    category = category or "history"
    out = Path(output_dir) if output_dir else (PROJECT_DIR / "long_form" / f"{_slugify(topic)}_project")
    out.mkdir(parents=True, exist_ok=True)
    (out / "project_media").mkdir(exist_ok=True)

    n_chapters, paras_per_chapter, word_budget = _plan_dimensions(minutes)
    _log(f"\n=== build_long_form: {topic!r} ===")
    _log(f"target ~{minutes} min -> {n_chapters} chapters x {paras_per_chapter} paragraphs "
         f"(word budget ~{word_budget})")

    from ai.groq_client import GroqAiClient
    client = GroqAiClient()
    if not getattr(client, "client", None):
        raise RuntimeError("Groq client not available (check GROQ_API_KEY)")

    tone = get_narration_tone() or {}
    tone_line = ", ".join(tone.get("style", ["documentary", "mysterious", "sober"]))
    hook_instr = build_hook_prompt_instructions()

    outline = _generate_chapter_outline(client, topic, category, n_chapters)
    _log(f"Outline: {len(outline)} chapters")
    for i, ch in enumerate(outline, 1):
        _log(f"  {i}. {ch['title']}")

    all_segments: list[dict] = []
    seg_id = 1
    for ci, ch in enumerate(outline):
        _log(f"\n[{ci+1}/{len(outline)}] Writing: {ch['title']}")
        pars = _generate_chapter_script(
            client, topic, ch["title"], ch["brief"],
            paras_per_chapter, is_first=(ci == 0), tone_line=tone_line, hook_instr=hook_instr,
        )
        if ci == 0 and pars:
            ok, msg = validate_hook(pars[0])
            _log(f"  hook check: {msg}")
        vprompts = _generate_visual_prompts(client, topic, pars)
        for p, vp in zip(pars, vprompts):
            all_segments.append({
                "segment_id": seg_id,
                "chapter": ch["title"],
                "text": p,
                "narration_text": p,
                "visual_prompt": vp,
                "assigned_filename": f"seg_{seg_id:03d}",
                "sfx_tag": "none",
                "overlay_tag": "none",
            })
            seg_id += 1

    # Enforce word budget (drop trailing segments if wildly over)
    total = 0
    kept: list[dict] = []
    for s in all_segments:
        w = len(s["text"].split())
        if kept and total + w > word_budget:
            break
        kept.append(s)
        total += w
    all_segments = kept
    for i, s in enumerate(all_segments, 1):
        s["segment_id"] = i
        s["assigned_filename"] = f"seg_{i:03d}"

    full_script = " ".join(s["text"] for s in all_segments)
    _assign_provisional_timings(all_segments)
    est_min = (all_segments[-1]["end_time"] if all_segments else 0) / 60.0
    _log(f"\nSegments: {len(all_segments)} | words: {len(full_script.split())} | est. ~{est_min:.1f} min")

    from channel.channel_profiles import active_channel
    storyboard = {
        "channel_profile": active_channel(),
        "topic": topic,
        "category": category,
        "storyboard_format": "long_form_16_9",
        "platform": "youtube_long",
        "script": full_script,
        "segments": all_segments,
        "target_duration_min": minutes,
        "language": cfg["language"],
        "status": "storyboard_ready",
        "_subtitle_style": cfg["subtitle_style"],
        "_project_path": str(out.resolve()),
    }
    if source_short_url:
        storyboard["source_short"] = source_short_url
    bgm = bgm_path or ""
    if bgm and Path(bgm).exists():
        storyboard["_manual_bgm_path"] = str(bgm)

    from pipeline.daily_short_pipeline import (
        save_storyboard,
        generate_images_for_draft,
        assemble_video,
        generate_platform_metadata,
    )

    # Narration audio -> accurate timings
    audio_path = None
    if tts:
        audio_path = _run_tts(storyboard, out, cfg, outline)

    save_storyboard(out, storyboard)
    _log(f"Storyboard saved -> {out / 'storyboard.json'}")

    video_path = ""
    if assemble:
        _log("\nGenerating images...")
        sb, _state = generate_images_for_draft(
            out, storyboard, image_provider=image_provider,
            visual_style=cfg["visual_style"], platform="youtube_long",
        )
        save_storyboard(out, sb)
        storyboard = sb
        _log("Assembling final video...")
        video = assemble_video(
            storyboard, out,
            image_provider="auto", video_provider="none",
            pregenerate_images=False, strict_existing_visuals=True,
            platform="youtube_long", subtitle_style=cfg["subtitle_style"],
            transition_type=cfg["transition_type"],
            transition_duration=cfg["transition_duration"],
            visual_style=cfg["visual_style"],
        )
        if video:
            # Copia unica en auto_videos/output (Drive); assemble_video ya dejo la
            # ruta en pipeline_state.json para que la subida la encuentre.
            video_path = str(video)
            _log(f"VIDEO: {video_path}")

    youtube_metadata = None
    if write_metadata:
        # storyboard is long-form -> generate_youtube_metadata routes to the
        # documentary path (no #shorts, is_short:False, auto chapters).
        youtube_metadata, _fb, _ig = generate_platform_metadata(storyboard, out)

    duration_s = all_segments[-1]["end_time"] if all_segments else 0
    result = {
        "output_dir": str(out),
        "storyboard_path": str(out / "storyboard.json"),
        "video_path": video_path,
        "metadata": youtube_metadata,
        "duration_s": duration_s,
        "chapters": [c["title"] for c in outline],
        "status": "ready_to_upload" if (video_path and youtube_metadata) else "built",
    }
    _log("\n=== DONE ===")
    _log(f"output_dir: {result['output_dir']}")
    _log(f"video: {video_path or '(not assembled)'}")
    _log(f"status: {result['status']}")
    if youtube_metadata:
        _log(f"title: {youtube_metadata.get('title')}")
    return result


def _run_tts(storyboard: dict, out: Path, cfg: dict, outline: list[dict]) -> Path | None:
    """Generate narration per chapter, combine, and rewrite accurate timings."""
    try:
        from pipeline.tts_generator import TextToSpeechGenerator
        from pydub import AudioSegment
    except Exception as e:
        _log(f"  [tts] unavailable ({e}); keeping provisional timings")
        return None

    media_tmp = out / "temp" / "generated_media"
    media_tmp.mkdir(parents=True, exist_ok=True)
    tts = TextToSpeechGenerator()

    by_chapter: dict[str, list[str]] = {}
    for s in storyboard["segments"]:
        by_chapter.setdefault(s["chapter"], []).append(s["text"])

    chapter_audio: list[Path] = []
    for i, ch in enumerate(outline, 1):
        pars = by_chapter.get(ch["title"], [])
        if not pars:
            continue
        chap_audio = media_tmp / f"chapter_{i:02d}.mp3"
        ok = tts.generate_narration(" ".join(pars), str(chap_audio),
                                    voice_id=cfg["voice"], rate=cfg["voice_rate"])
        if not ok or not chap_audio.exists() or chap_audio.stat().st_size < 1000:
            raise RuntimeError(f"TTS failed for chapter {i}: {ch['title']}")
        chapter_audio.append(chap_audio)
        _log(f"  [tts] chapter {i}/{len(outline)} ok")

    if not chapter_audio:
        return None
    combined = AudioSegment.empty()
    for p in chapter_audio:
        combined += AudioSegment.from_file(str(p))
    audio_path = media_tmp / "narration.mp3"
    combined.export(str(audio_path), format="mp3")
    dur_s = len(combined) / 1000.0
    storyboard["audio_path"] = str(audio_path.resolve())

    segs = storyboard["segments"]
    total_words = sum(max(1, len(s["text"].split())) for s in segs)
    t = 0.0
    for s in segs:
        w = max(1, len(s["text"].split()))
        d = dur_s * (w / total_words)
        s["start"] = t
        s["end"] = t + d
        s["start_time"] = t
        s["end_time"] = t + d
        s["duration"] = d
        t += d
    _log(f"  [tts] narration {dur_s/60:.1f} min -> timings updated")
    return audio_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a reusable long-form documentary (no upload).")
    ap.add_argument("topic", help="Documentary topic, e.g. 'The Antikythera Mechanism'")
    ap.add_argument("--minutes", type=float, default=None, help="Target minutes (traditional: 10; microdoc: 4.5)")
    ap.add_argument("--format", choices=["traditional", "micro_documentary"], default="traditional")
    from channel.channel_profiles import CHANNELS, DEFAULT_CHANNEL, select_channel
    ap.add_argument("--channel", choices=list(CHANNELS), default=DEFAULT_CHANNEL)
    ap.add_argument("--editorial-json", help="Manual topic provenance, historical sources and uncertainty notes")
    ap.add_argument("--approve-preflight", action="store_true", help="Approve an EXISTING reviewed experiment.json and generate the script")
    ap.add_argument("--category", default=None, help="Channel category label")
    ap.add_argument("--output-dir", default=None, help="Output project dir")
    ap.add_argument("--provider", default="flux_dev", help="Image provider (default flux_dev)")
    ap.add_argument("--no-assemble", action="store_true", help="Script + metadata only (no images/render)")
    ap.add_argument("--no-metadata", action="store_true", help="Skip metadata generation")
    ap.add_argument("--source-short", default=None, help="URL of the winning short this expands")
    ap.add_argument("--bgm", default=None, help="Background music file path")
    args = ap.parse_args(argv)

    select_channel(args.channel)
    if args.format == "micro_documentary":
        from pipeline.micro_documentary import build
        editorial = json.loads(Path(args.editorial_json).read_text(encoding="utf-8")) if args.editorial_json else None
        out = args.output_dir or PROJECT_DIR / "long_form" / args.channel / f"{_slugify(args.topic)}_microdoc"
        result = build(args.topic, out, channel=args.channel, seconds=(args.minutes if args.minutes is not None else 4.5) * 60,
                       editorial=editorial, approve=args.approve_preflight, assemble=not args.no_assemble,
                       image_provider=args.provider)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    result = build_long_form(
        topic=args.topic,
        minutes=args.minutes if args.minutes is not None else 10,
        category=args.category,
        output_dir=args.output_dir,
        image_provider=args.provider,
        assemble=not args.no_assemble,
        write_metadata=not args.no_metadata,
        source_short_url=args.source_short,
        bgm_path=args.bgm,
    )
    print("\n" + json.dumps({k: v for k, v in result.items() if k != "metadata"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
