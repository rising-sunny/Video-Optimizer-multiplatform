# -*- coding: utf-8 -*-
"""Titulos de YouTube basados en investigacion (lo que hace vidIQ), con puntaje explicado.

Hasta 2026-09-22 el titulo salia de pedirle a Groq "un titulo con gancho, max 50
caracteres, con un numero". Buen gancho, pero sin datos de busqueda: "Hannibal's
30,000 Oxen: 250kg Rations Across the Alps" no contiene lo que la gente escribe
("hannibal crossing the alps").

Este modulo usa la MISMA investigacion que los tags (youtube_tags.gather_research:
autocompletado de YouTube + videos que rankean), sin gastar cuota de nuevo, y:

  1. genera candidatos: el borrador, el borrador con la palabra clave al frente, y
     ~10 del LLM con TODO el contexto (palabra clave, busquedas secundarias, titulos
     que rankean -- para diferenciarse, no copiar --, ganadores propios, plantillas
     del Bible y del angulo, y el guion como unica fuente de cifras);
  2. los puntua de forma deterministica, como el "title score" de vidIQ:
       palabra clave presente (30) y al principio (15), largo en la franja que se
       ve completa (20), cifra RESPALDADA por el guion (10), busquedas secundarias
       (8), encaje con el angulo (5); penaliza palabras que murieron en el canal,
       aperturas prohibidas, copiar a la competencia, emojis, hashtags y MAYUSCULAS.
       Una cifra sin respaldo en el guion invalida el candidato (tambien si cambia
       de unidad: '30 km' de ceniza no respalda '30 eruptions').
  3. elige: en modo 'optimize' cambia el titulo solo si el mejor le gana por 5+
     puntos; en modo 'suggest' deja el titulo del usuario y reporta la mejor
     alternativa con su puntaje.

    .venv\\Scripts\\python.exe youtube_titles.py "tema" "titulo borrador"   # prueba en vivo

Ver `test_youtube_titles.py`.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sys
from typing import Any, Callable, Iterable, Optional

from youtube_tags import _MEDIA_RE, content_tokens, gather_research, normalize_tag

SMALL_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "by", "vs", "with", "from", "as"}
KNOWN_ACRONYMS = {"WWI", "WWII", "WW1", "WW2", "USS", "HMS", "NASA", "CIA", "KGB", "FBI", "USA", "UK", "USSR", "BC",
                  "AD", "BCE", "CE", "IJN", "SS", "UN", "NATO", "TNT", "RAF", "KT", "MI6", "DNA", "UFO", "US",
                  "EU", "RN", "USAF", "NKVD", "GPS"}
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿]")
_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)")


# ----------------------------------------------------------------------------
# utilidades puras
# ----------------------------------------------------------------------------
def smart_title_case(text: str) -> str:
    """'hannibal crossing the alps' -> 'Hannibal Crossing the Alps' (conserva acronimos)."""
    words = str(text or "").split()
    out = []
    for i, w in enumerate(words):
        if w.upper() in KNOWN_ACRONYMS:
            out.append(w.upper())
        elif i > 0 and w.lower() in SMALL_WORDS:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def _norm_number(raw: str) -> str:
    r = raw.replace(",", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):      # 30.000 (miles con punto)
        r = raw.replace(".", "")
    return r.lstrip("0") or "0"


def numbers_in(text: str) -> set[str]:
    return {_norm_number(m.group(1)) for m in _NUM_RE.finditer(str(text or ""))}


# Unidades normalizadas: una cifra de MEDIDA en el guion no puede pasar a contar otra cosa.
# 2026-09-22: el titulo investigado de Pompeii decia "Vesuvius' 30 eruptions" y en el
# guion el 30 era "30 km" de columna de ceniza; la cifra existia y el chequeo pasaba.
_UNITS = {
    **dict.fromkeys(("km", "kms", "kilometer", "kilometers", "kilometre", "kilometres"), "km"),
    **dict.fromkeys(("mi", "mile", "miles"), "mi"),
    **dict.fromkeys(("m", "meter", "meters", "metre", "metres"), "m"),
    "cm": "cm", "mm": "mm",
    **dict.fromkeys(("ft", "foot", "feet"), "ft"),
    **dict.fromkeys(("inch", "inches"), "in"),
    **dict.fromkeys(("kg", "kilo", "kilos", "kilogram", "kilograms", "kilogramme", "kilogrammes"), "kg"),
    **dict.fromkeys(("lb", "lbs", "pound", "pounds"), "lb"),
    **dict.fromkeys(("ton", "tons", "tonne", "tonnes"), "t"),
    **dict.fromkeys(("%", "percent", "per"), "%"),
    **dict.fromkeys(("degree", "degrees"), "deg"),
    **dict.fromkeys(("second", "seconds", "sec", "secs"), "s"),
    **dict.fromkeys(("minute", "minutes", "min", "mins"), "min"),
    **dict.fromkeys(("hour", "hours", "hr", "hrs"), "h"),
    **dict.fromkeys(("day", "days"), "d"),
    **dict.fromkeys(("week", "weeks"), "wk"),
    **dict.fromkeys(("month", "months"), "mo"),
    **dict.fromkeys(("year", "years"), "y"),
    **dict.fromkeys(("decade", "decades"), "dec"),
    **dict.fromkeys(("century", "centuries"), "c"),
    "mph": "mph", **dict.fromkeys(("knot", "knots"), "kn"),
    **dict.fromkeys(("acre", "acres"), "ac"), **dict.fromkeys(("hectare", "hectares"), "ha"),
    **dict.fromkeys(("liter", "liters", "litre", "litres"), "l"),
    **dict.fromkeys(("gallon", "gallons"), "gal"),
}


def _word_after(text: str, match) -> tuple[Optional[str], Optional[str]]:
    """(palabra que sigue a la cifra, su unidad normalizada o None). '250kg' y '30-km' tambien."""
    nxt = re.match(r"[\s-]*(%|[A-Za-z]+)", text[match.end():])
    if not nxt:
        return None, None
    word = nxt.group(1).lower()
    return word, _UNITS.get(word)


def unsupported_numbers(title: str, source_text: str) -> list[str]:
    """Cifras del titulo sin respaldo en el guion/tema: un titulo no inventa datos.

    La cifra tiene que estar Y, si en alguno de los dos lados es una medida (km, kg,
    horas, anos...), la unidad tiene que coincidir. Entre sustantivos no se juzga
    ('100 were launched' respalda '100 suicide subs')."""
    source = str(source_text or "")
    occurrences: dict[str, list[Optional[str]]] = {}
    for m in _NUM_RE.finditer(source):
        occurrences.setdefault(_norm_number(m.group(1)), []).append(_word_after(source, m)[1])
    bad = set()
    title = str(title or "")
    for m in _NUM_RE.finditer(title):
        n = _norm_number(m.group(1))
        if n not in occurrences:
            bad.add(n)
            continue
        word, unit = _word_after(title, m)
        if not any(unit == src_unit for src_unit in occurrences[n]):
            bad.add(f"{n} {word}" if word else n)
    return sorted(bad)


# Palabras comunes que abren un tramo del titulo con mayuscula sin ser nombres propios.
_SEGMENT_STARTERS = {
    "how", "why", "what", "when", "where", "who", "which", "inside", "behind", "beyond", "after", "before",
    "during", "the", "a", "an", "this", "that", "these", "those", "his", "her", "their", "its", "our", "one",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "hundred", "thousand", "million",
    "first", "last", "only", "every", "no", "not", "never", "all", "most", "more", "less", "why", "and", "but",
    "from", "into", "under", "over", "with", "without", "against", "at", "in", "on", "of", "for", "to", "by",
    "is", "was", "were", "are", "did", "does", "do", "can", "could", "would", "will", "real", "true", "secret",
    "hidden", "lost", "forgotten", "deadliest", "biggest", "largest", "strongest", "greatest", "impossible",
    "incredible", "untold", "brutal", "final", "day", "night", "year", "years", "days", "months", "hours",
}


def is_title_case(title: str) -> bool:
    """'Plaster Casts Of Pompeii Reveal Lost Faces': la mayuscula no distingue nombres propios."""
    words = [w for seg in re.split(r"[:|\u2014\u2013?!]", str(title or "")) for w in seg.split()[1:]]
    words = [re.sub(r"[^\w]", "", w) for w in words]
    words = [w for w in words if len(w) > 3 and w[:1].isalpha()]
    if len(words) < 3:
        return False
    return sum(1 for w in words if w[0].isupper()) / len(words) >= 0.7


def unsupported_names(title: str, source_text: str) -> list[str]:
    """Nombres propios del titulo que el guion no menciona ('...shaped Napoleonic logistics').

    Cada palabra con mayuscula se compara (sin plural ni posesivo) contra el guion/tema.
    La primera palabra de cada tramo (inicio y despues de ':') va con mayuscula igual:
    se exceptua solo si es una palabra comun de arranque ('How', 'Inside', 'The').
    Conservador a proposito: descartar un candidato de mas es barato; publicar un dato
    inventado no.
    """
    available = set(content_tokens(source_text))
    out = []
    for segment in re.split(r"[:|\u2014\u2013?!]", str(title or "")):
        for i, w in enumerate(segment.split()):
            core = re.sub(r"[^\w'\-]", "", w)
            if not core or not core[0].isupper() or core.upper() in KNOWN_ACRONYMS:
                continue
            if i == 0 and core.lower().rstrip("'s") in _SEGMENT_STARTERS:
                continue
            toks = content_tokens(core)
            if toks and not all(t in available for t in toks):
                out.append(core)
    return out


def length_band(is_short: bool, bible: Optional[dict[str, Any]] = None) -> tuple[int, int]:
    """Franja de largo: la del Bible para Shorts ('40-55'); 50-70 para videos largos."""
    if not is_short:
        return 50, 70
    rng = str(((bible or {}).get("title_formula") or {}).get("ideal_char_range") or "40-55")
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)", rng)
    return (int(m.group(1)), int(m.group(2))) if m else (40, 55)


def secondary_keywords(research: dict[str, Any], limit: int = 5) -> list[str]:
    """Busquedas reales (autocompletado) relevantes al guion, distintas de la palabra clave."""
    corpus = research.get("corpus") or set()
    kw = research.get("keyword") or ""
    out = []
    for sug, score in sorted((research.get("suggestions") or {}).items(), key=lambda kv: -kv[1]):
        toks = content_tokens(sug)
        if not toks or sug == kw or _MEDIA_RE.search(sug) or any(t not in corpus for t in toks):
            continue
        if set(toks) <= set(content_tokens(kw)):
            continue
        out.append(sug)
        if len(out) >= limit:
            break
    return out


def competitor_titles(research: dict[str, Any], limit: int = 8) -> list[tuple[str, int]]:
    rows = []
    for v in research.get("competitors") or []:
        t = str(v.get("title") or "")
        if not t or _MEDIA_RE.search(t.lower()):
            continue
        if sum(ch.isascii() for ch in t) / max(1, len(t)) < 0.9:
            continue
        rows.append((t, int(v.get("views") or 0)))
    rows.sort(key=lambda r: -r[1])
    return rows[:limit]


# ----------------------------------------------------------------------------
# Redaccion (2026-09-24): el titulo de Trafalgar salio "Nelson Trafalgar how the victory
# secured British seas" -- la busqueda del autocompletado pegada a una frase, sin puntuacion --
# y el del dia anterior "U boat 48 crew survived..." (el guion dice "U-boat"). Ninguna regla
# miraba la redaccion y el LLM habia pegado la clave literal porque el pedido decia "en las
# primeras 3-4 palabras".
# ----------------------------------------------------------------------------
_CLAUSE_STARTERS = {"how", "why", "what", "when", "where", "who", "which", "the", "a", "an", "this",
                    "that", "these", "those", "and", "but"}
_COMPOUND_RE = re.compile(r"\b([A-Za-z0-9]+(?:[-\u2010\u2011][A-Za-z0-9]+)+)\b")


def canonical_forms(script: str) -> dict[str, str]:
    """Compuestos con guion del guion: {'u boat': 'U-boat', 'franco spanish': 'Franco-Spanish'}."""
    out: dict[str, str] = {}
    for m in _COMPOUND_RE.finditer(str(script or "")):
        form = re.sub(r"[\u2010\u2011]", "-", m.group(1))
        if re.search(r"[A-Za-z]", form) and not re.fullmatch(r"[\d-]+", form):
            out.setdefault(form.replace("-", " ").lower(), form)
    return out


def apply_canonical_forms(title: str, forms: dict[str, str]) -> str:
    """'U boat 48 crew' -> 'U-boat 48 crew' con la escritura del guion."""
    # El guion trae guiones no separables (U+2011) y el LLM los copia: al titulo va el guion comun.
    t = re.sub(r"[‐‑]", "-", str(title or ""))
    for spaced, form in forms.items():
        t = re.sub(r"(?i)\b" + r"[\s-]+".join(map(re.escape, spaced.split())) + r"\b", form, t)
    return t


def readability_issues(title: str, keyword: str = "") -> list[str]:
    """Problemas de redaccion que se ven sin LLM. Una busqueda pegada invalida el titulo."""
    t = str(title or "").strip()
    issues: list[str] = []
    if not t:
        return issues
    if t[:1].islower():
        issues.append("empieza en minuscula")
    words = t.split()
    kw_words = normalize_tag(keyword).split() if keyword else []
    head = [re.sub(r"[^\w'-]", "", w).lower() for w in words[:len(kw_words)]]
    if kw_words and head == kw_words and len(words) > len(kw_words):
        joint = words[len(kw_words) - 1]
        nxt = words[len(kw_words)]
        if not re.search(r"[:,;?!\-\u2014\u2013.]$", joint) and (
                nxt.lower() in _CLAUSE_STARTERS and nxt[:1].islower() or nxt[:1].isdigit()):
            issues.append(f"la busqueda '{keyword}' quedo pegada a la frase, sin conector ni puntuacion")
    for i in range(1, len(words) - 2):
        a, b, c = words[i], words[i + 1], words[i + 2]
        if (a[:1].isupper() and b[:1].isupper() and not re.search(r"[:,;?!.]$", b)
                and c.lower() in _CLAUSE_STARTERS and c[:1].islower() and c.lower() not in ("the", "a", "an", "and")):
            issues.append(f"'{a} {b} {c}...': falta un conector o puntuacion")
            break
    if "  " in t or " ," in t or re.search(r":\S", t):
        issues.append("espacios o puntuacion mal puestos")
    return list(dict.fromkeys(issues))


def _keyword_position(title: str, keyword_tokens: list[str]) -> Optional[float]:
    """Posicion relativa (0..1) donde arranca la palabra clave en el titulo, o None."""
    if not keyword_tokens:
        return None
    norm_words = [content_tokens(w)[0] if content_tokens(w) else "" for w in normalize_tag(title).split()]
    kw = set(keyword_tokens)
    if not kw <= set(w for w in norm_words if w):
        return None
    first = min(i for i, w in enumerate(norm_words) if w in kw)
    return first / max(1, len(norm_words))


def score_title(title: str, research: dict[str, Any], source_text: str, *, is_short: bool = True,
                archetype: str = "", bible: Optional[dict[str, Any]] = None,
                competitors: Optional[list[tuple[str, int]]] = None, draft_title: str = "") -> dict[str, Any]:
    """Puntaje 0-100 con desglose. `valid=False` si inventa una cifra o supera 100 caracteres."""
    t = str(title or "").strip()
    reasons: list[str] = []
    parts: dict[str, int] = {"base": 12}
    valid = bool(t) and len(t) <= 100
    if len(t) > 100:
        reasons.append("mas de 100 caracteres (YouTube lo corta)")

    kw = research.get("keyword") or ""
    kw_toks = content_tokens(kw)
    subj_toks = content_tokens(research.get("subject") or "")
    title_toks = set(content_tokens(t))
    pos = _keyword_position(t, kw_toks)
    if kw_toks and set(kw_toks) <= title_toks:
        parts["palabra_clave"] = 30
        if pos is not None and pos <= 0.34:
            parts["al_principio"] = 15
        else:
            parts["al_principio"] = 5
            reasons.append(f"la palabra clave '{kw}' no esta al principio")
    elif subj_toks and set(subj_toks) <= title_toks:
        parts["palabra_clave"] = 15
        reasons.append(f"nombra al sujeto pero no la busqueda '{kw}'")
        spos = _keyword_position(t, subj_toks)
        parts["al_principio"] = 8 if spos is not None and spos <= 0.34 else 3
    else:
        parts["palabra_clave"] = 0
        parts["al_principio"] = 0
        reasons.append(f"no contiene la busqueda '{kw}' ni al sujeto")

    lo, hi = length_band(is_short, bible)
    n = len(t)
    if lo <= n <= hi:
        parts["largo"] = 20
    elif lo - 10 <= n <= hi + 10:
        parts["largo"] = 10
        reasons.append(f"{n} caracteres (ideal {lo}-{hi})")
    else:
        parts["largo"] = 0
        reasons.append(f"{n} caracteres, lejos del ideal {lo}-{hi}")

    if is_title_case(t):
        # En Title Case la mayuscula no dice que palabra es un nombre propio: no se puede
        # verificar. Se prefiere (poco) la version verificable en sentence case.
        parts["verificable"] = -4
        reasons.append("Title Case: nombres no verificables contra el guion")
    else:
        bad_names = unsupported_names(t, f"{source_text} {draft_title}")
        if bad_names:
            valid = False
            reasons.append(f"nombre que no esta en el guion: {', '.join(bad_names)}")
    bad_writing = readability_issues(t, research.get("keyword") or "")
    if bad_writing:
        valid = False
        reasons.extend(f"redaccion: {x}" for x in bad_writing)
    bad_numbers = unsupported_numbers(t, source_text)
    if bad_numbers:
        valid = False
        reasons.append(f"cifra sin respaldo en el guion: {', '.join(bad_numbers)}")
        parts["cifra"] = 0
    else:
        parts["cifra"] = 10 if numbers_in(t) else 0

    sec_hits = 0
    for sec in secondary_keywords(research):
        extra = set(content_tokens(sec)) - set(kw_toks)
        if extra and extra <= title_toks:
            sec_hits += 1
    parts["busquedas_secundarias"] = min(8, 4 * sec_hits)

    a = (archetype or "").lower()
    low = t.lower()
    fits = ((a == "mechanism" and (low.startswith(("how", "why")) or "?" in t))
            or (a == "discovery" and re.search(r"\b(found|discover|unearth|uncovered)", low))
            or (a == "human_story" and re.search(r"\b(who|he|she|man|woman|pilot|soldier|crew|only)\b", low))
            or (a == "scale_event" and numbers_in(t)))
    parts["angulo"] = 5 if fits else 0

    penalty = 0
    formula = (bible or {}).get("title_formula") or {}
    for w in formula.get("avoid_words_measured") or []:
        if re.search(r"\b" + re.escape(w.lower()) + r"\b", low):
            penalty += 15
            reasons.append(f"palabra que murio en el canal: '{w}'")
    for opener in formula.get("avoid_openers") or []:
        if low.startswith(opener.lower()):
            penalty += 15
            reasons.append(f"apertura prohibida: '{opener}'")
    if _EMOJI_RE.search(t):
        penalty += 10
        reasons.append("emoji")
    if "#" in t:
        penalty += 10
        reasons.append("hashtag en el titulo")
    caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", t) if w not in KNOWN_ACRONYMS]
    if caps:
        penalty += min(10, 5 * len(caps))
        reasons.append("palabras en MAYUSCULAS: " + ", ".join(caps[:3]))
    for other, views in competitors or []:
        ratio = difflib.SequenceMatcher(None, normalize_tag(t), normalize_tag(other)).ratio()
        if ratio >= 0.72:
            penalty += 15
            reasons.append(f"casi igual a un titulo que ya rankea: '{other[:50]}'")
            break
    counts: dict[str, int] = {}
    for tok in content_tokens(t):
        counts[tok] = counts.get(tok, 0) + 1
    repeated = [tok for tok, c in counts.items() if c > 1]
    if repeated:
        penalty += 6 * len(repeated)
        reasons.append("palabra repetida: " + ", ".join(repeated[:3]))
    parts["penalizaciones"] = -penalty
    total = max(0, min(100, sum(parts.values())))
    return {"title": t, "score": total, "valid": valid, "parts": parts, "reasons": reasons}


# ----------------------------------------------------------------------------
# candidatos
# ----------------------------------------------------------------------------
def deterministic_candidates(draft: str, research: dict[str, Any], is_short: bool = True,
                             bible: Optional[dict[str, Any]] = None) -> list[str]:
    """Sin LLM: el borrador y el borrador con la palabra clave al frente (si entra)."""
    out = []
    draft = str(draft or "").strip()
    if draft:
        out.append(draft)
    kw = research.get("keyword") or ""
    if not kw:
        return out
    kw_title = smart_title_case(kw)
    lo, hi = length_band(is_short, bible)
    if draft and not set(content_tokens(kw)) <= set(content_tokens(draft)):
        kw_toks = set(content_tokens(kw))
        pieces = [p.strip() for p in re.split(r"[:|\u2014\u2013]", draft) if p.strip()]
        # el pedazo del borrador que aporta mas palabras NUEVAS (el gancho), sin repetir la clave
        pieces.sort(key=lambda p: -len(set(content_tokens(p)) - kw_toks))
        for hook in pieces:
            new_words = set(content_tokens(hook)) - kw_toks
            if len(new_words) < 2:
                continue
            cand = f"{kw_title}: {hook}"
            toks = content_tokens(cand)
            if len(toks) != len(set(toks)):
                continue                           # 'Hannibal Crossing the Alps: ... Across the Alps'
            if len(cand) <= max(hi + 10, 60):
                out.append(cand)
                break
    return out


def build_title_prompt(topic: str, script: str, draft: str, research: dict[str, Any], *, is_short: bool,
                       archetype: str = "", bible: Optional[dict[str, Any]] = None,
                       own_winners: Iterable[str] = (), n: int = 10) -> str:
    lo, hi = length_band(is_short, bible)
    formula = (bible or {}).get("title_formula") or {}
    comps = competitor_titles(research)
    templates = list(formula.get("templates") or [])
    try:
        from channel_strategy import get_archetype
        templates = list((get_archetype(archetype) or {}).get("title_templates") or []) + templates
    except Exception:
        pass
    winners = [w for w in own_winners if w][:5] or list(formula.get("winning_examples_live") or [])[:5]
    forms = sorted(set(canonical_forms(script).values()))[:12]
    return f"""You write YouTube titles for a documented-history channel. Use the research below; do not guess.

VIDEO: {topic}
FORMAT: {'YouTube Short (vertical)' if is_short else 'long documentary (16:9)'}
CURRENT DRAFT TITLE: {draft or '(none)'}

SEARCH RESEARCH (YouTube autocomplete + top-ranking videos):
- Main search keyword (what people type): "{research.get('keyword', '')}"
- Secondary searches: {secondary_keywords(research)}
- Titles already ranking for it (views) -- DIFFERENTIATE, never copy: {[f"{t} ({v:,})" for t, v in comps]}

WHAT WORKS ON THIS CHANNEL (own winners): {winners}
TEMPLATES: {templates[:8]}

FACTS (the ONLY allowed source of numbers, names and claims):
{str(script or '')[:1800]}

RULES:
- The main keyword is what people TYPE in search, not a phrase to paste. Work its words naturally into the
  first 3-5 words of a fluent headline: add connector words, a possessive or punctuation as needed
  (e.g. keyword "nelson trafalgar" -> "Nelson at Trafalgar: ..." or "How Nelson won at Trafalgar ...").
  NEVER write the bare keyword followed directly by a lowercase clause ("Nelson Trafalgar how the ...").
- Every title must read as fluent, grammatical English: articles and verbs where needed, and a colon,
  dash or question mark between two clauses.
- Spell compound terms exactly as in the facts: {forms}.
- {lo}-{hi} characters. Plain English. No emojis, no hashtags, no ALL CAPS words.
- Sentence case: capitalize ONLY the first word and real proper nouns (names, places, ships).
- Use a concrete number ONLY if it appears in the facts. Never invent or round a number differently.
- No "mystery", "mysterious", "curse", "unexplained". No "Uncovering", "Discover the truth", "Let's explore".
- Each title must be a different angle: scale, how/why, the person, the consequence.
Return JSON: {{"titles": ["...", "..."]}} with {n} titles."""


def parse_titles(raw: Any) -> list[str]:
    """Titulos desde la respuesta del LLM: JSON {"titles": [...]}, lista JSON o una por linea."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip())
    if not text:
        return []
    data: Any = None
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except ValueError:
                data = None
    if isinstance(data, dict):
        data = data.get("titles")
    if isinstance(data, list):
        items = data
    else:
        items = [re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", ln) for ln in text.splitlines()]
    return [str(x).strip().strip('"').strip() for x in items if str(x).strip() and len(str(x).strip()) > 8]


def _default_generate(prompt: str) -> list[str]:
    """Groq en modo JSON; si el modo JSON falla (pasa con los modelos que razonan), en texto."""
    from groq_client import GroqAiClient
    client = GroqAiClient()
    if not getattr(client, "client", None):
        return []
    raw = client._generate(prompt + "\nReturn ONLY one JSON object, no markdown.",
                           max_tokens=8192, task_type="script_quality", json_mode=True)
    titles = parse_titles(raw) if raw and not str(raw).startswith("ERROR") else []
    if not titles:
        raw = client._generate(prompt + "\nWrite one title per line, nothing else.",
                               max_tokens=8192, task_type="script_quality", json_mode=False)
        titles = parse_titles(raw) if raw and not str(raw).startswith("ERROR") else []
    return titles


# ----------------------------------------------------------------------------
# Verificacion de hechos del LLM sobre los mejores candidatos
# ----------------------------------------------------------------------------
# 2026-09-22: las reglas atrapan cifras y nombres inventados, pero no una contradiccion:
# para Pompeii gano "Plaster casts of Pompeii hold bodies of over a thousand" y el video
# arranca diciendo que los cuerpos de Pompeya NO son cuerpos. Antes de elegir, el LLM
# revisa los mejores candidatos contra el guion; el que no pasa queda invalido.
FACTCHECK_BATCH = 4
FACTCHECK_ROUNDS = 2


def build_factcheck_prompt(titles: list[str], script: str, topic: str = "") -> str:
    listed = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return f"""You fact-check video titles for a history channel. A title may simplify, but every claim in it
must be supported by the SCRIPT and must not contradict it: numbers must count the same thing the script
counts; no invented causes, counts, superlatives, people or outcomes; nothing the script says is false or a myth.
It must also read as a fluent, grammatical English headline: not a pasted search phrase, no missing words
(articles, verbs, possessives) and correct punctuation between clauses. "natural" is false otherwise.

TOPIC: {topic}
SCRIPT:
{str(script or '')[:6000]}

CANDIDATE TITLES:
{listed}

Return ONLY JSON: {{"results": [{{"n": 1, "supported": true, "natural": true, "reason": "short reason"}}]}}
with one entry per title."""


def parse_factcheck(raw: Any) -> dict[int, tuple[bool, str]]:
    """{indice (0-based): (respaldado, motivo)}. Vacio si la respuesta no se entiende."""
    text = str(raw or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    out: dict[int, tuple[bool, str]] = {}
    for r in data.get("results") or []:
        try:
            i = int(r.get("n")) - 1
        except (TypeError, ValueError):
            continue
        def _yes(v):
            return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "1")
        ok = _yes(r.get("supported"))
        reason = str(r.get("reason") or "").strip()[:160]
        if "natural" in r and not _yes(r.get("natural")):
            ok = False
            reason = f"redaccion: {reason or 'no se lee como un titular natural'}"
        out[i] = (ok, reason)
    return out


def _default_verify(prompt: str) -> str:
    from groq_client import GroqAiClient
    client = GroqAiClient()
    if not getattr(client, "client", None):
        return ""
    return client._generate(prompt + "\nReturn ONLY one JSON object, no markdown.",
                            max_tokens=8192, task_type="script_quality", json_mode=True) or ""


def factcheck_candidates(scored: list[dict[str, Any]], script: str, topic: str, verify_fn: Callable[[str], Any],
                         original: str = "", log: Callable[[str], None] = print) -> int:
    """Marca invalidos los candidatos que el verificador rechaza (en su lugar). Devuelve cuantos."""
    rejected, checked = 0, set()
    for _ in range(FACTCHECK_ROUNDS):
        pending = [r for r in scored if r["valid"] and r["title"] not in checked]
        pending.sort(key=lambda r: (r["title"] != original, -r["score"]))   # el borrador siempre entra
        batch = pending[:FACTCHECK_BATCH]
        if not batch:
            break
        verdicts = parse_factcheck(verify_fn(build_factcheck_prompt([r["title"] for r in batch], script, topic)))
        if not verdicts:
            log("   [Titulo] la verificacion de hechos no respondio; se elige sin ella")
            break
        for i, r in enumerate(batch):
            checked.add(r["title"])
            ok, why = verdicts.get(i, (True, ""))
            r["factcheck"] = ok
            if not ok:
                r["valid"] = False
                r["reasons"].append(f"verificacion: {why or 'no respaldado por el guion'}")
                rejected += 1
        if any(r["valid"] for r in batch):
            break
    return rejected


def _own_winners() -> list[str]:
    try:
        from channel_strategy import get_performance_snapshot
        return [w.get("title") for w in ((get_performance_snapshot().get("youtube") or {}).get("winners") or [])
                if w.get("title")]
    except Exception:
        return []


def optimize_title(topic: str, script: str, draft_title: str, *, research: Optional[dict[str, Any]] = None,
                   is_short: bool = True, archetype: str = "", mode: str = "optimize",
                   generate_fn: Optional[Callable[[str], list[str]]] = None,
                   bible: Optional[dict[str, Any]] = None, own_winners: Optional[list[str]] = None,
                   min_gain: int = 5, log: Callable[[str], None] = print,
                   verify_fn: Optional[Callable[[str], Any]] = None,
                   factcheck: Optional[bool] = None) -> dict[str, Any]:
    """Elige (o sugiere) el titulo. Devuelve {title, original, changed, score, original_score,
    keyword, candidates:[{title, score, valid, parts, reasons}], summary}.

    factcheck: None = segun YOUTUBE_TITLE_FACTCHECK (por defecto si), salvo que se inyecte
    un generate_fn sin verify_fn (tests: no se llama a un LLM real para verificar)."""
    if research is None:
        research = gather_research(topic, draft_title, script, log=log)
    if bible is None:
        try:
            from channel_strategy import get_channel_strategy
            bible = get_channel_strategy()
        except Exception:
            bible = {}
    winners = own_winners if own_winners is not None else _own_winners()
    source_text = f"{topic} {script}"
    comps = competitor_titles(research)

    candidates = deterministic_candidates(draft_title, research, is_short, bible)
    # El titulo con el que se escribio el guion ("How Nelson Won Trafalgar Against a Bigger Fleet")
    # tambien compite: en Trafalgar era mejor que todo lo que se publico.
    if topic and topic.strip() != str(draft_title or "").strip() and 3 <= len(topic.split()) and len(topic) <= 100:
        candidates.append(topic.strip())
    try:
        gen = generate_fn or _default_generate
        prompt = build_title_prompt(topic, script, draft_title, research, is_short=is_short,
                                    archetype=archetype, bible=bible, own_winners=winners)
        candidates += list(gen(prompt) or [])
    except Exception as exc:
        log(f"   [Titulo] el LLM no propuso candidatos ({exc}); se puntuan borrador y variantes")

    forms = canonical_forms(f"{topic} {script}")
    seen, scored = set(), []
    for c in candidates:
        c = apply_canonical_forms(c, forms)
        key = normalize_tag(c)
        if not key or key in seen:
            continue
        seen.add(key)
        scored.append(score_title(c, research, source_text, is_short=is_short, archetype=archetype,
                                  bible=bible, competitors=comps, draft_title=draft_title))
    scored.sort(key=lambda r: (not r["valid"], -r["score"]))

    original = str(draft_title or "").strip()
    if factcheck is None:
        factcheck = (str(os.getenv("YOUTUBE_TITLE_FACTCHECK", "1")).strip().lower() not in ("0", "false", "no", "off")
                     and (generate_fn is None or verify_fn is not None))
    rejected = 0
    if factcheck:
        try:
            rejected = factcheck_candidates(scored, script, topic, verify_fn or _default_verify,
                                            original=original, log=log)
        except Exception as exc:
            log(f"   [Titulo] verificacion de hechos no disponible ({exc}); se elige sin ella")
        scored.sort(key=lambda r: (not r["valid"], -r["score"]))

    orig = next((r for r in scored if r["title"] == original), None) if original else None
    best = next((r for r in scored if r["valid"]), None)
    chosen, changed = original, False
    if mode == "optimize" and best:
        if not orig or not orig["valid"] or best["score"] >= orig["score"] + min_gain:
            chosen, changed = best["title"], best["title"] != original
    if not chosen and best:
        chosen, changed = best["title"], True
    chosen_row = next((r for r in scored if r["title"] == chosen), best)
    summary = (f"'{chosen}' ({chosen_row['score'] if chosen_row else '?'}/100)"
               + (f" <- antes '{original}' ({orig['score'] if orig else '?'}/100)" if changed and original else "")
               + f" | palabra clave '{research.get('keyword', '')}'")
    if mode == "suggest" and best and orig and best["title"] != original and best["score"] > orig["score"]:
        summary += f" | mejor alternativa: '{best['title']}' ({best['score']}/100)"
    if orig and orig.get("factcheck") is False and chosen == original:
        summary += f" | ATENCION: tu titulo no paso la verificacion ({orig['reasons'][-1]})"
    if rejected:
        summary += f" | verificacion descarto {rejected} candidato(s) no respaldado(s) por el guion"
    return {"title": chosen, "original": original, "changed": changed,
            "score": chosen_row["score"] if chosen_row else None,
            "original_score": orig["score"] if orig else None,
            "keyword": research.get("keyword"), "candidates": scored[:10], "summary": summary}


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('Uso: youtube_titles.py "tema" ["titulo borrador"] ["guion"]')
        return 2
    topic = argv[0]
    draft = argv[1] if len(argv) > 1 else ""
    script = argv[2] if len(argv) > 2 else topic
    rep = optimize_title(topic, script, draft)
    print(rep["summary"])
    for c in rep["candidates"]:
        flag = "" if c["valid"] else "  [INVALIDO]"
        print(f"  {c['score']:3d}  {c['title']}{flag}")
        if c["reasons"]:
            print(f"        {'; '.join(c['reasons'][:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
