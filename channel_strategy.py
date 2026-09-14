"""Loader and validator for the channel strategy profile.

Reads ``daily_shorts/channel_strategy_profile.json`` and exposes helper
functions that the pipeline, script generation, and validation layers use
to enforce the channel bible rules.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

_PROJECT_DIR = Path(__file__).resolve().parent
_PROFILE_PATH = _PROJECT_DIR / "daily_shorts" / "channel_strategy_profile.json"

_cached_strategy: Optional[dict[str, Any]] = None


def get_channel_strategy(*, reload: bool = False) -> dict[str, Any]:
    global _cached_strategy
    if _cached_strategy is not None and not reload:
        return _cached_strategy

    from channel_profiles import active_channel, DEFAULT_CHANNEL, load_profile
    if active_channel() != DEFAULT_CHANNEL:
        _cached_strategy = load_profile()
    elif _PROFILE_PATH.exists():
        with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
            _cached_strategy = json.load(f)
    else:
        _cached_strategy = _fallback_config()
    return _cached_strategy


def _fallback_config() -> dict[str, Any]:
    return {
        "channel_identity": {
            "channel_id": "",
            # Fallback si no se puede leer el perfil. Deliberadamente NEUTRO:
            # un default con el canal viejo es una mina para el proximo cambio.
            "channel_handle": "this-channel",
            "language": "en",
        },
        "shorts_rules": {
            "target_duration": 50,
            "min_duration": 45,
            "max_duration": 58,
            "hard_limit": 60,
        },
        "hook_patterns": {"allowed": [], "prohibited": []},
        "categories": [],
        "tts": {"default_voice": "en-US-GuyNeural", "rate": "+5%", "language": "en"},
        "visual_style": "Photorealism",
        "subtitle_style": "capcut",
        "transition_type": "Fade Smooth",
        "transition_duration": 0.3,
    }


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------

def get_shorts_rules() -> dict[str, Any]:
    return get_channel_strategy().get("shorts_rules", {})


def get_hook_patterns() -> dict[str, Any]:
    return get_channel_strategy().get("hook_patterns", {"allowed": [], "prohibited": []})


def get_narrative_structure() -> dict[str, Any]:
    return get_channel_strategy().get("narrative_structure", {})


def get_channel_name(default: str = "this channel") -> str:
    """Nombre visible del canal, para prompts y CTAs.

    Estaba cableado como "Stunning Revelations" en 33 lugares de 3 archivos, asi
    que al cambiar de canal los guiones seguian invitando a suscribirse al viejo.
    """
    try:
        ident = get_channel_strategy().get("channel_identity", {})
    except Exception:
        return default
    return ident.get("channel_name") or ident.get("channel_handle") or default


def get_channel_audience_line(default: str = "general audience") -> str:
    """Nicho y posicionamiento del canal en una linea, para prompts.

    Los prompts de miniatura tenian cableado "mystery, science, hidden history,
    conspiracies, documented unexplained events": el publico del canal ANTERIOR.
    Con el canal nuevo (hechos historicos documentados, explicitamente NO
    misterios ni conspiraciones) eso empujaba las miniaturas justo hacia lo que
    el Channel Bible pone fuera de alcance.
    """
    try:
        ident = get_channel_strategy().get("channel_identity", {})
    except Exception:
        return default
    partes = [ident.get("niche"), ident.get("positioning")]
    linea = ". ".join(str(p).strip() for p in partes if str(p or "").strip())
    return linea or default


def get_cover_frame_config() -> dict[str, Any]:
    return get_channel_strategy().get("cover_frame", {})


def get_narration_tone() -> dict[str, Any]:
    return get_channel_strategy().get("narration_tone", {})


def get_categories_by_priority(priority: Optional[str] = None) -> list[dict[str, Any]]:
    cats = get_channel_strategy().get("categories", [])
    if priority:
        return [c for c in cats if c.get("priority", "").upper() == priority.upper()]
    return sorted(cats, key=lambda c: 0 if c.get("priority", "").upper() == "HIGH" else 1)


def get_all_category_names() -> list[str]:
    cats = get_channel_strategy().get("categories", [])
    names: list[str] = []
    for c in cats:
        names.append(c["name"])
        names.extend(c.get("aliases", []))
    return names


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def validate_duration(seconds: float) -> tuple[bool, str]:
    rules = get_shorts_rules()
    hard_limit = rules.get("hard_limit", 60)
    max_dur = rules.get("max_duration", 58)
    min_dur = rules.get("min_duration", 45)

    if seconds > hard_limit:
        return False, f"Duration {seconds:.1f}s exceeds hard limit of {hard_limit}s"
    if seconds > max_dur:
        return True, f"WARNING: Duration {seconds:.1f}s exceeds recommended max of {max_dur}s (hard limit {hard_limit}s)"
    if seconds < min_dur:
        return True, f"WARNING: Duration {seconds:.1f}s is below recommended min of {min_dur}s"
    return True, f"Duration {seconds:.1f}s OK (target range {min_dur}-{max_dur}s)"


# Signals that a hook opens on a concrete number, scale, or date. Channel
# analytics show these openers retain far more viewers past the first 3s
# (higher swipe/viewed rate): e.g. "20,000", "72 seconds", "In 536 AD".
_HOOK_SIGNAL_RE = re.compile(
    r"\d"
    r"|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"twenty|thirty|forty|fifty|sixty|hundred|hundreds|thousand|thousands|"
    r"million|millions|billion)\b"
    r"|\b(bc|bce|ad|ce)\b"
    r"|\b(century|centuries)\b",
    re.IGNORECASE,
)


def hook_has_number_or_date(text: str) -> bool:
    """True if the first sentence carries a concrete number, scale, or date."""
    if not text or not text.strip():
        return False
    first_sentence = text.strip().split(".")[0]
    return bool(_HOOK_SIGNAL_RE.search(first_sentence))


def validate_hook(text: str) -> tuple[bool, str]:
    if not text or not text.strip():
        return False, "Hook text is empty"

    first_sentence = text.strip().split(".")[0].strip()
    lower = first_sentence.lower()

    prohibited = get_hook_patterns().get("prohibited", [])
    for phrase in prohibited:
        if phrase.lower() in lower:
            return False, f"Hook uses prohibited pattern: '{phrase}'"

    # Non-fatal: warn (don't reject) when the opener lacks a number/date/scale.
    if not hook_has_number_or_date(first_sentence):
        return True, (
            "WARNING: hook has no concrete number, date, or scale in the first "
            "sentence — top-performing hooks open with one (e.g. '20,000', "
            "'72 seconds', 'In 536 AD')"
        )

    return True, "Hook passes validation"


def build_hook_prompt_instructions() -> str:
    patterns = get_hook_patterns()
    allowed = patterns.get("allowed", [])
    prohibited = patterns.get("prohibited", [])
    structure = get_narrative_structure()
    tone = get_narration_tone()

    lines = []
    lines.append("HOOK & NARRATIVE RULES (MANDATORY):")
    lines.append("")

    if structure:
        lines.append("NARRATIVE STRUCTURE (strict timing):")
        for key, val in structure.items():
            if isinstance(val, dict):
                lines.append(f"  - {val.get('start', '?')}-{val.get('end', '?')}s: {val.get('description', key)}")
        lines.append("")

    lines.append("The first 1-2 seconds are CRITICAL. Use one of these hook patterns:")
    lines.append("")
    for p in allowed:
        lines.append(f"  Pattern {p['id']} — {p['name']}: {p['description']}")
        if p.get("examples"):
            for ex in p["examples"][:2]:
                lines.append(f"    Example: \"{ex}\"")
    lines.append("")

    lines.append(
        "MANDATORY OPENER (data-driven): The first spoken sentence MUST contain a "
        "concrete number, scale, or date — e.g. \"20,000\", \"72 seconds\", "
        "\"sixty meters\", \"In 536 AD\". Channel analytics show hooks that open on a "
        "specific number or date keep far more viewers past the first 3 seconds "
        "(the swipe/viewed-rate metric that decides distribution)."
    )
    lines.append("")

    if prohibited:
        lines.append("PROHIBITED opening phrases (NEVER use these):")
        for phrase in prohibited:
            lines.append(f"  - \"{phrase}\"")
        lines.append("")

    if tone:
        tone_styles = tone.get("style", [])
        if tone_styles:
            lines.append(f"TONE: {', '.join(tone_styles)}.")

        avoid_tones = tone.get("avoid", [])
        if avoid_tones:
            lines.append(f"AVOID tone: {', '.join(avoid_tones)}.")

        lines.append(f"PACING: {tone.get('pacing', 'Short sentences. Dramatic pauses.')}")
        lines.append("")

        credibility = tone.get("credibility_phrases", [])
        if credibility:
            lines.append("For uncertain claims, use phrases like:")
            for phrase in credibility[:4]:
                lines.append(f"  - \"{phrase}\"")

        avoid_phrases = tone.get("avoid_phrases", [])
        if avoid_phrases:
            lines.append("NEVER use phrases like:")
            for phrase in avoid_phrases[:4]:
                lines.append(f"  - \"{phrase}\"")

    return "\n".join(lines)


def build_category_weight_map() -> dict[str, float]:
    cats = get_channel_strategy().get("categories", [])
    weights: dict[str, float] = {}
    priority_map = {"HIGH": 1.5, "MEDIUM": 1.0, "LOW": 0.5}
    for cat in cats:
        base = priority_map.get(cat.get("priority", "MEDIUM").upper(), 1.0)
        # production_weight is the data-driven topic mix. It fine-tunes emphasis
        # WITHIN a priority tier: scaled around the typical ~0.15 so a 0.30 weight
        # roughly doubles a category's selection score and a 0.05 weight roughly
        # thirds it (clamped to [0.4, 2.0]). Absent/invalid -> priority only.
        pw = cat.get("production_weight")
        if isinstance(pw, (int, float)) and pw > 0:
            w = base * min(2.0, max(0.4, pw / 0.15))
        else:
            w = base
        weights[cat["name"]] = w
        for alias in cat.get("aliases", []):
            weights[alias] = w
    return weights
