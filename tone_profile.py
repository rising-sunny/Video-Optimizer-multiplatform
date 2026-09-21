"""Single source of truth for category → tone profile mapping.

Used by both storyboard_generator.py (Spanish prompts) and claude_client.py (English prompts)
so the mapping stays consistent across all script-generation paths (shorts, long videos,
batched chunking).

Profiles:
- 'mystery'          → speculative narrator, "¿y si...?". For: Misterios, Conspiraciones.
- 'dramatic_factual' → cinematic disaster-doc tension, strictly factual. For: Eventos naturales extremos.
- 'documentary'      → rigorous historian/science communicator, pseudohistory FORBIDDEN.
                       For: Historia militar, Historia antigua, Documentales, Ciencia/Tec, Actualidad
                       científica. Default when category is unknown or empty.
"""

# Constants exposed for callers that want to switch on profile values.
PROFILE_DOCUMENTARY = "documentary"
PROFILE_DRAMATIC_FACTUAL = "dramatic_factual"
PROFILE_MYSTERY = "mystery"

TONE_PROFILES = (PROFILE_DOCUMENTARY, PROFILE_DRAMATIC_FACTUAL, PROFILE_MYSTERY)


def get_tone_profile_for_category(category: str) -> str:
    """Map a UI category string (Spanish, free-form) to one of the TONE_PROFILES.

    Matching is keyword-based on the lowercased category, so it tolerates minor
    variations (accents, casing, extra words). When in doubt, defaults to
    'documentary' — the safest choice that forbids fabrication.
    """
    cat = (category or "").strip().lower()
    # Los perfiles de canal nombran las categorias en INGLES ("Historical
    # Disasters", "Historical Mysteries"); hasta 2026-09-21 solo se reconocian
    # las palabras en espanol y todo caia en 'documentary'.
    if any(k in cat for k in ("misterio", "conspiraci", "paranormal", "ovni",
                              "myster", "conspir", "ufo")):
        return PROFILE_MYSTERY
    if any(k in cat for k in ("natural", "desastre", "extremo", "catastrof",
                              "disaster", "catastroph", "extreme")):
        return PROFILE_DRAMATIC_FACTUAL
    if any(k in cat for k in ("historia", "documental", "ciencia", "tecnolog", "actualidad",
                              "histor", "archaeolog", "civiliz", "empire", "science", "technolog", "war")):
        return PROFILE_DOCUMENTARY
    return PROFILE_DOCUMENTARY


__all__ = [
    "PROFILE_DOCUMENTARY",
    "PROFILE_DRAMATIC_FACTUAL",
    "PROFILE_MYSTERY",
    "TONE_PROFILES",
    "get_tone_profile_for_category",
]
