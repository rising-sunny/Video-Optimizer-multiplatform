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

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_PROFILE_PATH = _PROJECT_DIR / "daily_shorts" / "channel_strategy_profile.json"

_cached_strategy: Optional[dict[str, Any]] = None


def get_channel_strategy(*, reload: bool = False) -> dict[str, Any]:
    global _cached_strategy
    if _cached_strategy is not None and not reload:
        return _cached_strategy

    from channel.channel_profiles import active_channel, DEFAULT_CHANNEL, load_profile
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


# Aperturas con fecha: "In 1540,", "On May 29, 1453,", "Around 1600 BC,", "By 1917 ...".
_DATE_OPENER_RE = re.compile(
    r"^\s*(in|on|by|around|during|back in)\s+(the\s+)?"
    r"(?:(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+)?"
    r"(?:the\s+)?(?:year\s+)?\d{2,4}\s*(bc|bce|ad|ce)?\b",
    re.I,
)
_QUESTION_OPENER_RE = re.compile(r"^\s*(how|why|what|where|who|could|did|was|were|is|are)\b", re.I)
_THROAT_CLEARING_RE = re.compile(r"^\s*(did you know|imagine|discover|today we|welcome|in this video)\b", re.I)


def first_sentence(text: str) -> str:
    """Primera frase hablada (corta en . ! ? -- el gancho puede ser una pregunta)."""
    t = (text or "").strip()
    if not t:
        return ""
    m = re.search(r"[.!?](\s|$)", t)
    return (t[:m.start() + 1] if m else t).strip()


def get_first_seconds_rules() -> dict[str, Any]:
    return dict(get_channel_strategy().get("first_seconds") or {})


def hook_report(text: str) -> tuple[bool, list[str]]:
    """Veredicto del gancho contra la regla medida: [OK]/[WARN]/[FAIL] por criterio.

    FAIL solo por patrones prohibidos (listicle, 'today we...'); lo demas es
    WARN: la regla es una preferencia medida, no una prohibicion dura.
    """
    if not text or not text.strip():
        return False, ["[FAIL] gancho vacio"]
    sentence = first_sentence(text)
    lower = sentence.lower()
    lines: list[str] = []
    ok = True
    for phrase in get_hook_patterns().get("prohibited", []):
        if phrase.lower() in lower:
            ok = False
            lines.append(f"[FAIL] patron prohibido: '{phrase}'")
    if _THROAT_CLEARING_RE.search(sentence):
        lines.append("[WARN] arranca carraspeando ('Did you know' / 'Imagine' / 'Discover')")
    # La cifra tiene que estar fuera de la fecha de apertura: "In 1540, a 24-meter
    # obelisk" cuenta (24), "In 1540, the obelisk fell" no.
    rest = _DATE_OPENER_RE.sub("", sentence, count=1)
    has_number = hook_has_number_or_date(rest)
    is_question = sentence.endswith("?") or bool(_QUESTION_OPENER_RE.match(sentence))
    if has_number or is_question:
        lines.append(f"[OK] abre con {'cifra' if has_number else 'pregunta'}")
    else:
        lines.append("[WARN] la primera frase no trae cifra ni pregunta (medido: es lo que retiene)")
    if _DATE_OPENER_RE.match(sentence):
        lines.append("[WARN] abre con fecha ('In 1540, ...'): la fecha va en la segunda frase (medido en Facebook: ~30% vs 50% de retencion)")
    limit = int(get_first_seconds_rules().get("max_words_first_sentence") or 14)
    n_words = len(sentence.split())
    if n_words > limit:
        lines.append(f"[WARN] primera frase de {n_words} palabras (max {limit})")
    return ok, lines


def validate_hook(text: str) -> tuple[bool, str]:
    """Compatibilidad: (ok, mensaje). Ver hook_report para el detalle por criterio."""
    ok, lines = hook_report(text)
    if not ok:
        return False, "; ".join(l for l in lines if l.startswith("[FAIL]"))
    warns = [l for l in lines if l.startswith("[WARN]")]
    if warns:
        return True, "WARNING: " + "; ".join(w[7:] for w in warns)
    return True, "Hook passes validation"


# ---------------------------------------------------------------------------
# Rendimiento medido (performance_feedback.py -> daily_shorts/performance_snapshot.json)
# ---------------------------------------------------------------------------
_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "daily_shorts" / "performance_snapshot.json"


def get_performance_snapshot() -> dict[str, Any]:
    """Lo ultimo que midio performance_feedback.py, o {} si nunca se corrio."""
    try:
        data = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def performance_archetype_weights() -> dict[str, float]:
    return dict((get_performance_snapshot().get("weights") or {}).get("archetypes") or {})


def performance_category_weights() -> dict[str, float]:
    return dict((get_performance_snapshot().get("weights") or {}).get("categories") or {})


def build_performance_prompt_block(snapshot: Optional[dict[str, Any]] = None) -> str:
    """Bloque para el prompt del guion: que esta funcionando AHORA, con la fecha de medicion.

    Vacio si no hay snapshot: el Bible sigue mandando. Con snapshot, el modelo
    sabe que angulos despegan, que encuadres murieron y que pasa en cada red,
    y de donde salen esos numeros.
    """
    snap = snapshot if snapshot is not None else get_performance_snapshot()
    rec = (snap or {}).get("recommendations") or {}
    if not snap or not (rec.get("lean_into") or rec.get("avoid") or rec.get("notes")):
        return ""
    lines = [f"WHAT IS WORKING NOW (measured on this channel, {snap.get('generated_at', '?')}, "
             f"last {snap.get('window_days', '?')} days):"]
    for x in rec.get("lean_into", []):
        lines.append(f"  - LEAN INTO: {x.get('label')} -- {x.get('why')}")
    for x in rec.get("avoid", []):
        lines.append(f"  - AVOID: {x.get('label')} -- {x.get('why')}")
    for n in rec.get("notes", [])[:4]:
        lines.append(f"  - NOTE: {n}")
    winners = ((snap.get("youtube") or {}).get("winners") or [])[:4]
    if winners:
        lines.append("  - Recent winners (title -> views): " + "; ".join(
            "'%s' -> %s" % ((w.get("title") or "")[:60], w.get("views")) for w in winners))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Angulo narrativo (format_archetype): como se cuenta el tema, no que tema es.
# ---------------------------------------------------------------------------
AUTO_ARCHETYPE = "auto"
_active_archetype: str = ""


def get_format_archetypes() -> list[dict[str, Any]]:
    block = get_channel_strategy().get("format_archetypes") or {}
    items = block.get("items") if isinstance(block, dict) else block
    return [a for a in (items or []) if isinstance(a, dict) and a.get("id")]


def get_archetype(archetype_id: Optional[str]) -> dict[str, Any]:
    key = str(archetype_id or "").strip().lower()
    for a in get_format_archetypes():
        if a.get("id") == key:
            return a
    return {}


def archetype_label(archetype_id: Optional[str]) -> str:
    a = get_archetype(archetype_id)
    return a.get("label_es") or a.get("name") or str(archetype_id or "")


def set_active_archetype(archetype_id: Optional[str]) -> str:
    """Fija el angulo para la generacion en curso (lo lee build_hook_prompt_instructions).

    Mismo patron que select_channel: el pipeline construye los prompts en capas
    profundas que no reciben parametros nuevos; el angulo se resuelve antes de
    lanzar el worker y queda tambien en el storyboard (result['format_archetype']).
    """
    global _active_archetype
    key = str(archetype_id or "").strip().lower()
    _active_archetype = key if get_archetype(key) else ""
    return _active_archetype


def get_active_archetype() -> str:
    return _active_archetype


def pick_archetype_auto(topic: str, category: str = "") -> str:
    """'auto': palabras del tema; si no dicen nada, el angulo con mejor peso medido; si no, el fallback del Bible."""
    block = get_channel_strategy().get("format_archetypes") or {}
    rules = (block.get("auto_rules") or {}) if isinstance(block, dict) else {}
    text = f"{topic or ''} {category or ''}".lower()
    keywords = rules.get("keywords") or {}
    best, best_hits = "", 0
    for arche, words in keywords.items():
        hits = sum(1 for w in words if w and w.lower() in text)
        if hits > best_hits and get_archetype(arche):
            best, best_hits = arche, hits
    if best:
        return best
    measured = performance_archetype_weights()
    if measured:
        top = max(measured.items(), key=lambda kv: kv[1])[0]
        if get_archetype(top):
            return top
    fallback = rules.get("fallback") or "scale_event"
    return fallback if get_archetype(fallback) else (get_format_archetypes()[0]["id"] if get_format_archetypes() else "")


def build_archetype_prompt_instructions(archetype_id: Optional[str] = None) -> str:
    """Bloque de prompt del angulo: que es, como abre, plantillas y la evidencia que lo sostiene."""
    a = get_archetype(archetype_id if archetype_id is not None else get_active_archetype())
    if not a:
        return ""
    lines = [f"NARRATIVE ANGLE (chosen for this video): {a.get('name', a['id'])} -- {a.get('description', '')}"]
    if a.get("prompt"):
        lines.append(a["prompt"])
    if a.get("hook_templates"):
        lines.append("Opening-line templates for this angle: " + " | ".join(a["hook_templates"][:3]))
    if a.get("title_templates"):
        lines.append("Title templates for this angle: " + " | ".join(a["title_templates"][:3]))
    if a.get("evidence"):
        lines.append(f"Why this angle (measured): {a['evidence']}")
    return "\n".join(lines)


def archetype_cover_words(archetype_id: Optional[str] = None) -> list[str]:
    a = get_archetype(archetype_id if archetype_id is not None else get_active_archetype())
    return list(a.get("cover_words") or [])


def archetype_thumbnail_brief(archetype_id: Optional[str] = None) -> str:
    a = get_archetype(archetype_id if archetype_id is not None else get_active_archetype())
    return str(a.get("thumbnail") or "")


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

    fs = get_first_seconds_rules()
    if fs.get("rules"):
        lines.append("FIRST SECONDS (measured on this channel -- mandatory):")
        for rule in fs["rules"]:
            lines.append(f"  - {rule}")
        if fs.get("good"):
            lines.append("  Good openers: " + " | ".join(f"\"{g}\"" for g in fs["good"][:3]))
        if fs.get("bad"):
            lines.append("  Bad openers (measured to lose viewers): " + " | ".join(f"\"{b}\"" for b in fs["bad"][:3]))
        if fs.get("evidence"):
            lines.append(f"  Evidence: {fs['evidence']}")
    else:
        lines.append(
            "MANDATORY OPENER (data-driven): The first spoken sentence MUST contain a "
            "concrete number or scale, or a HOW/WHY question -- e.g. \"20,000\", "
            "\"72 seconds\", \"How did 7,000 people live without streets?\". Do NOT open "
            "with a date; the date goes in the second sentence."
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

    angle = build_archetype_prompt_instructions()
    if angle:
        lines.append("")
        lines.append(angle)

    performance = build_performance_prompt_block()
    if performance:
        lines.append("")
        lines.append(performance)

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
    # Lo medido pesa sobre lo declarado: si el snapshot tiene un peso para la
    # categoria (mediana de vistas relativa), se multiplica (acotado a [0.4, 2.0]).
    measured = performance_category_weights()
    if measured:
        lowered = {k.lower(): v for k, v in measured.items()}
        for name in list(weights):
            m = lowered.get(name.lower())
            if isinstance(m, (int, float)) and m > 0:
                weights[name] = round(min(2.0, max(0.4, weights[name] * m)), 3)
    return weights
