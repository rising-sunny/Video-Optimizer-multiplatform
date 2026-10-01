"""Manual Studio categories and their editorial instructions."""
import unicodedata

MYSTERY_CATEGORY = "Misterios y Conspiraciones"
MYSTERY_DESCRIPTION = (
    "Relatos y teorías documentados: distingue hechos, hipótesis y lo que sigue sin confirmar. "
    "Que algo no haya sido refutado no significa que esté demostrado."
)
FALLBACK_CATEGORIES = [
    "Historia militar/guerras", "Historia antigua/civilizaciones", "Documentales",
    "Eventos naturales extremos", "Ciencia/Tecnologia actual", "Misterios con datos",
    "Conspiraciones verificables", "Actualidad cientifica",
]


def is_mystery_inquiry(category):
    name = unicodedata.normalize("NFKD", str(category or ""))
    name = "".join(c for c in name if not unicodedata.combining(c))
    return " ".join(name.casefold().split()) == MYSTERY_CATEGORY.casefold()


def get_studio_category_names():
    """The extra category is opt-in; automated channel topic lists stay unchanged."""
    try:
        from channel_strategy import get_all_category_names
        names = list(get_all_category_names())
    except Exception:
        names = []
    names = names or list(FALLBACK_CATEGORIES)
    names = [n for n in names if not is_mystery_inquiry(n)]
    return names + [MYSTERY_CATEGORY]


def mystery_editorial_instructions(category, language="es"):
    if not is_mystery_inquiry(category):
        return ""
    if language == "en":
        return """
EDITORIAL MODE — MYSTERIES AND CONSPIRACIES (explicitly selected by the user):
- This selection permits investigating documented mysteries, traditions and conspiracy theories,
  including explanations that remain unproven and are not conclusively refuted. It takes precedence
  over the channel's general exclusion of mystery topics FOR THIS VIDEO ONLY.
- Tell a cinematic investigative story: intriguing source account → documented context → evidence
  and rival explanations → what remains unresolved. An open ending is allowed; do not force a solution.
- Distinguish DOCUMENTED FACT, SOURCE ACCOUNT/BELIEF, HYPOTHESIS and UNKNOWN throughout the narration.
  Identify the actual source of an account or theory; never invent researchers, testimony or citations.
- A religious text, chronicle or legend documents that an account exists; it does not independently
  prove that every event or supernatural cause in that account happened. Attribute its numbers too.
- Unproven does NOT mean false; not refuted does NOT mean demonstrated or equally probable.
  Do not invent uncertainty or say "never disproven", "science cannot explain it" or "proof" without support.
- Explore serious competing explanations, their supporting evidence and limits, proportionately.
  Include documented objections without ridicule. Do not revive a conclusively refuted claim as viable.
- Avoid both forced debunking and credulous certainty. Suspense comes from the evidence and its gaps,
  not fabricated secrets, motives, witnesses, accusations or events.
- Titles, opening hooks and cover text must preserve the same uncertainty. Questions must not smuggle
  in a false premise. Visuals illustrate accounts or hypotheses; invented imagery is never evidence.
- Close by stating what we know, what we do not, and what evidence could distinguish the explanations.
"""
    return """
MODO EDITORIAL — MISTERIOS Y CONSPIRACIONES (elegido expresamente por el usuario):
- Se permite investigar misterios, tradiciones y teorías conspirativas documentados, incluidas
  explicaciones no comprobadas y no refutadas concluyentemente. Esta selección prevalece sobre la
  exclusión general de misterios del canal SOLO PARA ESTE VIDEO.
- Narra una investigación cinematográfica: relato intrigante → contexto documentado → evidencia
  y explicaciones rivales → lo que sigue abierto. Se permite un cierre abierto; no fuerces una solución.
- Distingue HECHO DOCUMENTADO, RELATO/CREENCIA DE UNA FUENTE, HIPÓTESIS y DESCONOCIDO en la narración.
  Identifica la fuente real del relato o teoría; no inventes investigadores, testimonios ni citas.
- Un texto religioso, crónica o leyenda documenta la existencia del relato, pero no demuestra por sí
  solo todos sus sucesos ni una causa sobrenatural. Atribuye también las cifras al relato que las da.
- No comprobado NO significa falso; no refutado NO significa demostrado ni igualmente probable.
  No inventes incertidumbre ni digas "jamás refutado", "la ciencia no puede explicarlo" o "prueba" sin respaldo.
- Examina explicaciones alternativas serias, la evidencia que las respalda y sus límites, de forma
  proporcionada. Incluye objeciones documentadas sin burlas. No revivas una tesis refutada como vigente.
- Evita tanto la refutación forzada como la certeza crédula. El suspenso nace de las pruebas y sus vacíos,
  no de secretos, motivos, testigos, acusaciones o sucesos inventados.
- Título, gancho inicial y texto de portada deben conservar la incertidumbre del guion. Las preguntas
  no pueden introducir una premisa falsa. Las imágenes ilustran relatos o hipótesis; no son evidencia.
- Cierra aclarando qué sabemos, qué desconocemos y qué evidencia permitiría distinguir las explicaciones.
"""
