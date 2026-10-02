import sys
import os
import json
import argparse
import time
import re
import unicodedata
from pathlib import Path
from datetime import datetime
from infra.env_loader import load_project_env
from infra.video_config import VideoConfig
from channel.channel_strategy import (
    get_channel_name,
    get_channel_strategy,
    get_shorts_rules,
    get_all_category_names,
    get_categories_by_priority,
    build_category_weight_map,
    validate_duration,
    validate_hook,
)


# Importes internos desde daily_short_pipeline (se resuelven porque este modulo
# se importa al FINAL de daily_short_pipeline.py, cuando todo ya esta definido).
from pipeline.daily_short_pipeline import (
    log, create_output_dir, _safe_read_json, _write_json, _storyboard_for_disk,
    save_storyboard, get_draft_state, _normalize_title, find_similar_title, get_used_titles,
    STORYBOARD_FILENAME, PIPELINE_STATE_FILENAME, YOUTUBE_METADATA_FILENAME,
    FACEBOOK_METADATA_FILENAME, INSTAGRAM_METADATA_FILENAME, LEGACY_METADATA_FILENAME,
)


def _extract_generated_json(text: str) -> dict:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]
    return json.loads(raw)


def _normalize_tags(values, limit: int = 22) -> list[str]:
    tags = []
    seen = set()
    for item in values or []:
        text = str(item).strip().lstrip("#")
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        tags.append(text)
        if len(tags) >= limit:
            break
    return tags


def _sanitize_description_text(text: str) -> str:
    """Normalize a model-generated description.

    Some LLM/JSON round-trips leave literal escape sequences (the two chars
    backslash+n) instead of real line breaks, which render as ugly "\\n" in the
    published description. Convert those to real newlines and collapse runs of
    blank lines. Safe on already-clean text (real newlines don't match "\\n").
    """
    if not text:
        return ""
    s = str(text)
    s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _is_longform_storyboard(storyboard: dict) -> bool:
    """Detect a long-form (documentary) storyboard vs a Short."""
    fmt = str(storyboard.get("storyboard_format") or "").lower()
    plat = str(storyboard.get("platform") or "").lower()
    if "long" in fmt or "long" in plat:
        return True
    try:
        if float(storyboard.get("target_duration_min") or 0) >= 3:
            return True
    except (TypeError, ValueError):
        pass
    return False


def build_youtube_chapters(storyboard: dict) -> str:
    """Build a YouTube 'CHAPTERS' block from storyboard segments.

    Uses each segment's ``chapter`` label and ``start_time`` (falling back to
    ``start``). Returns "" when there aren't at least 3 distinct chapters, since
    YouTube ignores chapter lists shorter than that. The first timestamp is
    forced to 0:00 as YouTube requires.
    """
    segs = storyboard.get("segments") or storyboard.get("scenes") or []
    first_start: dict[str, float] = {}
    order: list[str] = []
    for s in segs:
        ch = str(s.get("chapter") or "").strip()
        if not ch:
            continue
        st = s.get("start_time", s.get("start"))
        if st is None:
            continue
        if ch not in first_start:
            first_start[ch] = float(st)
            order.append(ch)
        else:
            first_start[ch] = min(first_start[ch], float(st))

    if len(order) < 3:
        return ""

    order.sort(key=lambda c: first_start[c])

    def _clean(name: str) -> str:
        cleaned = re.sub(r"^\s*chapter\s*\d+\s*[:\-–]\s*", "", name, flags=re.IGNORECASE).strip()
        return cleaned or name

    def _fmt(t: float) -> str:
        t = int(round(t or 0))
        h, rem = divmod(t, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    lines = ["CHAPTERS"]
    for i, ch in enumerate(order):
        ts = 0 if i == 0 else first_start[ch]
        lines.append(f"{_fmt(ts)} {_clean(ch)}")
    return "\n".join(lines)


def _normalize_youtube_metadata(payload: dict, topic: str) -> dict:
    return {
        "title": str(payload.get("title") or topic or get_channel_name()).strip(),
        "description": _sanitize_description_text(payload.get("description") or ""),
        "tags": _normalize_tags(payload.get("tags"), limit=22),
    }


def _normalize_facebook_metadata(payload: dict, topic: str) -> dict:
    return {
        "title": str(payload.get("title") or topic or get_channel_name()).strip()[:255],
        "description": _sanitize_description_text(payload.get("description") or "")[:2200],
    }


def _normalize_instagram_metadata(payload: dict, topic: str) -> dict:
    return {
        "title": str(payload.get("title") or topic or get_channel_name()).strip()[:120],
        "description": _sanitize_description_text(payload.get("description") or "")[:2200],
    }


def _youtube_metadata_fallback(storyboard: dict) -> dict:
    return {
        "title": storyboard.get("topic", get_channel_name()),
        "description": f"Discover the truth about {storyboard.get('topic', 'this mystery')}. #history #mystery #shorts",
        "tags": ["history", "mystery", "conspiracy", "paranormal", "shorts"],
        "is_short": True,
    }


def _place_chapters(description: str, chapters_block: str) -> str:
    """Insert a chapters block above the hashtags (else append at the end)."""
    if not chapters_block or "0:00" in (description or ""):
        return description
    desc = description or ""

    # Case 1: hashtags on their own line(s).
    lines = desc.split("\n")
    hash_idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith("#")), None)
    if hash_idx is not None:
        head = "\n".join(lines[:hash_idx]).rstrip()
        tail = "\n".join(lines[hash_idx:]).lstrip()
        return f"{head}\n\n{chapters_block}\n\n{tail}"

    # Case 2: a trailing run of hashtags glued to the text (e.g. "...world.#A #B").
    m = re.search(r"#\w[\w]*(?:\s+#\w[\w]*)*\s*$", desc)
    if m and desc[:m.start()].rstrip():
        head = desc[:m.start()].rstrip()
        tail = desc[m.start():].strip()
        return f"{head}\n\n{chapters_block}\n\n{tail}"

    return f"{desc.rstrip()}\n\n{chapters_block}"


def _youtube_longform_metadata_fallback(storyboard: dict) -> dict:
    topic = storyboard.get("topic", get_channel_name())
    script = str(storyboard.get("script") or "").strip()
    intro = script[:300].strip() or f"The full story behind {topic}."
    desc = (
        f"{intro}\n\nSubscribe to {get_channel_name()} for more forgotten history, "
        "lost civilizations, and mysteries that still disturb the modern world."
    )
    desc = _place_chapters(desc, build_youtube_chapters(storyboard))
    return {
        "title": str(topic)[:100],
        "description": _sanitize_description_text(desc),
        "tags": _normalize_tags([
            "documentary", "history documentary", "history", "mystery",
            "lost civilizations", "ancient history", "archaeology",
            "stunning revelations",
        ], limit=22),
        "is_short": False,
    }


def _generate_longform_youtube_metadata(storyboard: dict, output_dir: Path,
                                        used_titles: list = None) -> dict:
    """YouTube metadata for a long-form documentary (no #shorts, auto chapters)."""
    log("Generando metadata para YouTube LONG-FORM (documental)...", "STEP")
    used_titles = used_titles or []
    topic = storyboard.get("topic", "")
    category = storyboard.get("category", "")
    script = str(storyboard.get("script") or "")
    chapters_block = build_youtube_chapters(storyboard)

    try:
        from ai.groq_client import GroqAiClient
        groq = GroqAiClient()
        if not getattr(groq, "client", None):
            raise RuntimeError("Groq no disponible")

        used_str = "\n".join(f"  - {t}" for t in set(used_titles)) if used_titles else "None"
        prompt = f"""You are a YouTube SEO expert for LONG-FORM documentaries on the channel {get_channel_name()} (forgotten history, lost civilizations, dark mysteries).

This is a full documentary (8-15 min), NOT a Short. Never use #shorts anywhere.

CURRENT VIDEO:
- Topic: {topic}
- Category: {category}
- Script (first 700 chars): {script[:700]}

Already-published titles (avoid duplicates):
{used_str}

Generate JSON with:
1. "title": A searchable documentary title, 50-70 chars. Lead with the main SEARCH KEYWORD (a proper name or place people type), include one concrete number when natural. No #shorts. Examples: "Derinkuyu: The Underground City That Hid 20,000 People", "The Wow! Signal: 72 Seconds That Never Came Back".
2. "description": 3-5 sentences with REAL line breaks between paragraphs. Sentence 1 = the hook/scale. Then what the documentary covers. End with the line: "Subscribe to {get_channel_name()} for more forgotten history, lost civilizations, and mysteries that still disturb the modern world." Do NOT invent chapter timestamps (they are added automatically). Finish with 6-8 topical hashtags, never #shorts.
3. "tags": Array of 12-18 lowercase SEO tags. Include "documentary", "history documentary", the main subject/place, and "stunning revelations". Never include "shorts".

Respond ONLY with valid JSON, no markdown."""

        response = groq._generate(prompt)
        if not response or not response.strip():
            raise RuntimeError("Groq returned empty response for long-form metadata")

        meta = _normalize_youtube_metadata(_extract_generated_json(response), topic)
        meta["tags"] = [t for t in meta["tags"] if t.lower().lstrip("#") != "shorts"]
        meta["description"] = _sanitize_description_text(
            _place_chapters(meta["description"], chapters_block)
        )
        meta["is_short"] = False
        log(f"Título long-form: {meta.get('title', '?')}", "OK")
        log(f"Capítulos: {'incluidos' if chapters_block else 'omitidos (faltan chapter+start_time en segmentos)'}", "OK")
        return meta

    except Exception as e:
        log(f"Metadata long-form falló, usando fallback: {e}", "WARN")
        return _youtube_longform_metadata_fallback(storyboard)


def _facebook_metadata_fallback(storyboard: dict, youtube_metadata: dict | None = None) -> dict:
    # Los hashtags investigados y la marca de la pagina los agrega facebook_uploader al
    # publicar (facebook_metadata); aca no va '#Mystery' ni una marca fija.
    from publish.facebook_metadata import trim_at_boundary
    topic = storyboard.get("topic", get_channel_name())
    script = str(storyboard.get("script") or "").strip()
    preview = trim_at_boundary(script, 260)
    description = (
        f"{preview}\n\nWhat do you think really happened?\n\n#History"
        if preview
        else f"The real story behind {topic} is stranger than most people realize.\n\nWhat do you think really happened?\n\n#History"
    )
    return {
        "title": str((youtube_metadata or {}).get("title") or topic).strip()[:255],
        "description": description[:2200],
    }


def _instagram_metadata_fallback(storyboard: dict, youtube_metadata: dict | None = None,
                                 facebook_metadata: dict | None = None) -> dict:
    # Hashtags investigados y marca de la cuenta: los agrega instagram_uploader al publicar.
    from publish.facebook_metadata import trim_at_boundary
    topic = storyboard.get("topic", get_channel_name())
    script = str(storyboard.get("script") or "").strip()
    preview = trim_at_boundary(script, 320)
    description = (
        f"{preview}\n\nWhat do you think really happened?\n\n#History"
        if preview
        else f"The real story behind {topic} is stranger than most people realize.\n\nWhat do you think really happened?\n\n#History"
    )
    return {
        "title": str(
            (facebook_metadata or {}).get("title")
            or (youtube_metadata or {}).get("title")
            or topic
        ).strip()[:120],
        "description": description[:2200],
    }


def _save_platform_metadata_files(output_dir: Path, youtube_metadata: dict, facebook_metadata: dict,
                                  instagram_metadata: dict) -> None:
    output_dir = Path(output_dir)
    _write_json(output_dir / LEGACY_METADATA_FILENAME, youtube_metadata)
    _write_json(output_dir / YOUTUBE_METADATA_FILENAME, youtube_metadata)
    _write_json(output_dir / FACEBOOK_METADATA_FILENAME, facebook_metadata)
    _write_json(output_dir / INSTAGRAM_METADATA_FILENAME, instagram_metadata)


def generate_youtube_metadata(storyboard: dict, output_dir: Path, used_titles: list = None) -> dict:
    """Genera metadata optimizada para YouTube (Shorts o documental long-form)."""
    if _is_longform_storyboard(storyboard):
        if used_titles is None:
            used_titles = []
        return _generate_longform_youtube_metadata(storyboard, output_dir, used_titles)
    log("Generando metadata para YouTube Shorts (data-driven)...", "STEP")
    
    if used_titles is None:
        used_titles = []

    try:
        from ai.groq_client import GroqAiClient
        groq = GroqAiClient()
        if not groq.client:
            raise RuntimeError("Groq no disponible")

        topic = storyboard.get("topic", "")
        category = storyboard.get("category", "")
        script = storyboard.get("script", "")

        perf = CHANNEL_PERFORMANCE
        title_patterns = perf.get("title_patterns", {})
        desc_patterns = perf.get("description_patterns", {})
        tag_strategy = perf.get("tag_strategy", {})
        top_categories = perf.get("best_performing_categories", [])

        title_examples = title_patterns.get("top_title_examples", [])
        examples_str = "\n".join(f"  - {t}" for t in title_examples) if title_examples else "  (no examples available)"
        high_keywords = title_patterns.get("high_performing_keywords", [])
        keywords_str = ", ".join(high_keywords) if high_keywords else "mystery, secret, ancient, shocking"
        effective_hashtags = desc_patterns.get("effective_hashtags", ["#shorts", "#history", "#facts"])
        hashtags_str = " ".join(effective_hashtags[:8])
        always_tags = tag_strategy.get("always_include", ["stunning revelations", "shorts"])
        always_tags_str = ", ".join(always_tags)

        cat_ranking = ""
        for cat in top_categories[:5]:
            cat_ranking += f"  - {cat['name']} ({cat.get('avg_views', '?')} avg views): {cat.get('notes', '')}\n"

        used_str = "\n".join(f"  - {t}" for t in set(used_titles)) if used_titles else "None"

        # Bucle de reintentos para deduplicación
        max_retries = 3
        response = None
        for attempt in range(max_retries):
            prompt = f"""You are a YouTube Shorts SEO expert optimizing for the channel {get_channel_name()}.

CHANNEL ANALYTICS (real data from YouTube Studio):
- Shorts get 4x more views and 3.5x more subscribers than long videos
- Best categories by performance:
{cat_ranking}
TITLE RULES (from analyzing top 27 videos with 500+ views):
- 52% of top titles contain specific NUMBERS
- 63% use COLONS to separate subject from hook
- Average length: 47 characters (ideal range: 40-55 chars)
- Winning formula: [Specific Event/Subject]: [Hook with numbers/superlatives]
- High-performing keywords: {keywords_str}
- Examples of titles that got 500+ views:
{examples_str}

CRITICAL DEDUPLICATION RULE:
DO NOT generate any title that is identical or highly similar to these already published titles:
{used_str}

CURRENT VIDEO:
- Topic: {topic}
- Category: {category}
- Script (first 500 chars): {script[:500]}

Generate a JSON with:
1. "title": Follow the winning formula above. MUST include a specific number/data point. Use a colon to separate. 40-55 chars. Add 1 emoji max. Make it IMPOSSIBLE to scroll past. DO NOT COPY USED TITLES.
2. "description":
   - Line 1: Hook question that creates curiosity gap
   - Line 2-3: Key facts from the script (specific data points)
   - Line 4: Call to action ("Follow for more stunning revelations!")
   - Line 5: Hashtags: {hashtags_str}
3. "tags": Array of 18-22 tags structured as:
   - Always include: {always_tags_str}
   - 3-4 broad category tags
   - 4-5 topic-specific tags
   - 3-4 trending/current event tags
   - 2-3 question-format tags ("what happened to...", "why did...")

Respond ONLY with valid JSON, no markdown."""

            response = groq._generate(prompt)
            if response:
                import json
                try:
                    data = json.loads(response)
                    gen_title = data.get("title", "")
                    similar = find_similar_title(gen_title, used_titles)
                    if similar and attempt < max_retries - 1:
                        log(f"Título generado '{gen_title}' es muy similar a '{similar}'. Reintentando...", "WARNING")
                        continue
                    break
                except Exception:
                    pass
            break
        if not response or not response.strip():
            raise RuntimeError("Groq returned empty response for metadata")

        metadata = _normalize_youtube_metadata(_extract_generated_json(response), topic)
        metadata["is_short"] = True
        log(f"Título YouTube: {metadata.get('title', '?')}", "OK")
        log(f"Tags YouTube: {len(metadata.get('tags', []))} tags", "OK")
        return metadata

    except Exception as e:
        log(f"Metadata YouTube falló: {e}", "WARN")
        return _youtube_metadata_fallback(storyboard)


def generate_facebook_metadata(storyboard: dict, output_dir: Path,
                               youtube_metadata: dict | None = None, used_titles: list = None) -> dict:
    """Genera metadata específica para Facebook Reels."""
    log("Generando metadata para Facebook Reel...", "STEP")

    try:
        from ai.groq_client import GroqAiClient
        groq = GroqAiClient()
        if not groq.client:
            raise RuntimeError("Groq no disponible")

        topic = storyboard.get("topic", "")
        category = storyboard.get("category", "")
        script = storyboard.get("script", "")
        youtube_title = (youtube_metadata or {}).get("title", "")

        prompt = f"""You are a Facebook Reels growth strategist for the page {get_channel_name()}.
Return ONLY valid JSON.

CURRENT VIDEO:
- Topic: {topic}
- Category: {category}
- Existing YouTube title for reference: {youtube_title}
- Script (first 700 chars): {script[:700]}

TASK:
Create metadata specifically for Facebook Reel distribution in ENGLISH.

STRICT RULES:
- Keep the title distinct from the YouTube title while covering the same core topic.
- title: 45-90 chars, documentary tone, curiosity-driven, no fake urgency, no "subscribe to the channel".
- description: 3 short blocks maximum.
- description block 1: strongest hook or surprising fact tied to the reel.
- description block 2: 1-2 concise context sentences grounded in the script.
- description block 3: conversation CTA for comments, plus 3-5 relevant hashtags max.
- Avoid YouTube-specific wording like "subscribe", "watch till the end", "link in bio", or huge hashtag walls.
- Favor discussion prompts like "What do you think happened?" or "Would you trust the official version?"

JSON schema:
{{
  "title": "string",
  "description": "string"
}}"""

        response = groq._generate(prompt)
        if not response or not response.strip():
            raise RuntimeError("Groq returned empty response for Facebook metadata")

        metadata = _normalize_facebook_metadata(_extract_generated_json(response), topic)
        log(f"Título Facebook: {metadata.get('title', '?')}", "OK")
        return metadata

    except Exception as e:
        log(f"Metadata Facebook falló: {e}", "WARN")
        return _facebook_metadata_fallback(storyboard, youtube_metadata=youtube_metadata)


def generate_instagram_metadata(storyboard: dict, output_dir: Path, youtube_metadata: dict = None, facebook_metadata: dict = None, used_titles: list = None) -> dict:
    """Genera metadata específica para Instagram Reels."""
    log("Generando metadata para Instagram Reel...", "STEP")

    try:
        from ai.groq_client import GroqAiClient
        groq = GroqAiClient()
        if not groq.client:
            raise RuntimeError("Groq no disponible")

        topic = storyboard.get("topic", "")
        category = storyboard.get("category", "")
        script = storyboard.get("script", "")
        youtube_title = (youtube_metadata or {}).get("title", "")
        facebook_title = (facebook_metadata or {}).get("title", "")

        prompt = f"""You are an Instagram Reels copy strategist for the account {get_channel_name()}.
Return ONLY valid JSON.

CURRENT VIDEO:
- Topic: {topic}
- Category: {category}
- Existing YouTube title for reference: {youtube_title}
- Existing Facebook title for reference: {facebook_title}
- Script (first 700 chars): {script[:700]}

TASK:
Create metadata specifically for Instagram Reels distribution in ENGLISH.

STRICT RULES:
- title: 35-80 chars, hooky but documentary, clean enough to work as caption line 1.
- title should feel native to Instagram and not read like YouTube SEO stuffing.
- description: 2 short blocks max.
- block 1: strongest hook or reveal tied to the reel.
- block 2: brief context plus comment CTA and 4-6 relevant hashtags max.
- Avoid "subscribe", "watch till the end", links, or giant hashtag walls.
- Favor intrigue, discussion, and clean mobile readability.

JSON schema:
{{
  "title": "string",
  "description": "string"
}}"""

        response = groq._generate(prompt)
        if not response or not response.strip():
            raise RuntimeError("Groq returned empty response for Instagram metadata")

        metadata = _normalize_instagram_metadata(_extract_generated_json(response), topic)
        log(f"Título Instagram: {metadata.get('title', '?')}", "OK")
        return metadata

    except Exception as e:
        log(f"Metadata Instagram falló: {e}", "WARN")
        return _instagram_metadata_fallback(
            storyboard,
            youtube_metadata=youtube_metadata,
            facebook_metadata=facebook_metadata,
        )


def generate_platform_metadata(storyboard: dict, output_dir: Path) -> tuple[dict, dict, dict]:
    """Genera y guarda metadata separada para YouTube, Facebook e Instagram."""
    output_dir = Path(output_dir)
    used_titles = get_used_titles()
    youtube_metadata = generate_youtube_metadata(storyboard, output_dir, used_titles=used_titles)
    from channel.channel_profiles import active_channel
    youtube_metadata['channel_profile'] = storyboard.get('channel_profile') or active_channel()
    # Atribucion de la musica automatica de Jamendo (CC BY la exige); cada uploader la
    # pega al final de la descripcion ya optimizada. Ver music_license.
    music_attribution = ""
    if storyboard.get("music_data"):
        try:
            from publish.music_license import attribution_text
            music_attribution = attribution_text(storyboard["music_data"])
        except Exception as e:
            log(f"Atribucion de musica omitida: {e}", "WARN")
    if music_attribution:
        youtube_metadata["music_attribution"] = music_attribution
    
    if _is_longform_storyboard(storyboard):
        _save_platform_metadata_files(output_dir, youtube_metadata, {}, {})
        log(f"Metadata YouTube (Long-form) guardada: {output_dir / YOUTUBE_METADATA_FILENAME}", "OK")
        return youtube_metadata, {}, {}

    facebook_metadata = generate_facebook_metadata(
        storyboard,
        output_dir,
        youtube_metadata=youtube_metadata,
        used_titles=used_titles
    )
    instagram_metadata = generate_instagram_metadata(
        storyboard,
        output_dir,
        youtube_metadata=youtube_metadata,
        facebook_metadata=facebook_metadata,
        used_titles=used_titles
    )
    if music_attribution:
        facebook_metadata["music_attribution"] = music_attribution
        instagram_metadata["music_attribution"] = music_attribution
    _save_platform_metadata_files(output_dir, youtube_metadata, facebook_metadata, instagram_metadata)
    log(f"Metadata YouTube guardada: {output_dir / YOUTUBE_METADATA_FILENAME}", "OK")
    log(f"Metadata Facebook guardada: {output_dir / FACEBOOK_METADATA_FILENAME}", "OK")
    log(f"Metadata Instagram guardada: {output_dir / INSTAGRAM_METADATA_FILENAME}", "OK")
    return youtube_metadata, facebook_metadata, instagram_metadata


def generate_metadata(storyboard: dict, output_dir: Path) -> dict:
    """Genera título, descripción y tags optimizados para YouTube usando datos de rendimiento del canal."""
    youtube_metadata, _facebook_metadata, _instagram_metadata = generate_platform_metadata(storyboard, output_dir)
    return youtube_metadata

