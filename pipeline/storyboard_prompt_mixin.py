# storyboard_generator.py
"""
Generador de storyboards y teasers
Maneja la generaciÃ³n de guiones, segmentos, prompts visuales y teasers
"""

import os
import re
import asyncio
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime

# Verificar dependencias
PYDUB_AVAILABLE = False
JAMENDO_AVAILABLE = False
GOOGLE_SEARCH_AVAILABLE = False

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

try:
    from media.music_recommender import (
        analyze_narration,
        map_ai_to_jamendo_tags,
        search_jamendo_api
    )
    JAMENDO_AVAILABLE = True
except ImportError:
    JAMENDO_AVAILABLE = False

RESEARCH_SEARCH_AVAILABLE = False
try:
    from ai.research_search import search_research_context, RESEARCH_AVAILABLE
    RESEARCH_SEARCH_AVAILABLE = RESEARCH_AVAILABLE
except ImportError:
    pass

# Fallback a Google Search si research_search no está disponible
GOOGLE_SEARCH_AVAILABLE = False
if not RESEARCH_SEARCH_AVAILABLE:
    try:
        from ai.google_search_api import search_google_trends
        GOOGLE_SEARCH_AVAILABLE = True
    except ImportError:
        GOOGLE_SEARCH_AVAILABLE = False

from infra.video_config import VideoConfig
from studio.studio_categories import is_mystery_inquiry, mystery_editorial_instructions


def get_channel_name(default: str = "this channel") -> str:
    """Nombre visible del canal, leido del Channel Bible.

    Import perezoso: este modulo se carga antes que el perfil en algunos flujos.
    """
    try:
        from channel.channel_strategy import get_channel_name as _real
        return _real(default)
    except Exception:
        return default


def _import_script_quality_guards():
    try:
        from ai.claude_client import is_llm_refusal, script_is_too_short, minimum_script_words
        return is_llm_refusal, script_is_too_short, minimum_script_words
    except Exception:
        return (
            lambda _text: False,
            lambda *_args, **_kwargs: False,
            lambda duration, target=None: 0,
        )


def _storyboard_script_text(storyboard) -> str:
    if not isinstance(storyboard, dict):
        return ""
    script = str(storyboard.get("script") or "").strip()
    if script:
        return script
    parts = []
    for segment in storyboard.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        parts.append(
            str(
                segment.get("text")
                or segment.get("narration_text")
                or segment.get("narration")
                or ""
            )
        )
    return " ".join(parts).strip()


def prefer_in_memory_storyboard(memory, disk) -> bool:
    """True when the live storyboard is newer/better than the JSON on disk.

    Opening the timeline used to always reload project.json, which replaced a
    freshly generated long storyboard with the previous 3-scene refusal.
    """
    if not isinstance(memory, dict) or not memory.get("segments"):
        return False
    if not isinstance(disk, dict) or not disk.get("segments"):
        return True

    mem_n = len(memory.get("segments") or [])
    disk_n = len(disk.get("segments") or [])
    is_refusal, _, _ = _import_script_quality_guards()
    mem_script = _storyboard_script_text(memory)
    disk_script = _storyboard_script_text(disk)

    if is_refusal(disk_script) and not is_refusal(mem_script):
        return True
    if is_refusal(mem_script) and not is_refusal(disk_script):
        return False

    try:
        mem_ts = float(memory.get("generated_at") or 0)
    except (TypeError, ValueError):
        mem_ts = 0.0
    try:
        disk_ts = float(disk.get("generated_at") or 0)
    except (TypeError, ValueError):
        disk_ts = 0.0
    if mem_ts and disk_ts:
        return mem_ts >= disk_ts
    return mem_n > disk_n


def storyboard_is_unusable(storyboard) -> bool:
    """True only when the storyboard is an LLM refusal, not when it is empty."""
    if not isinstance(storyboard, dict):
        return False
    if not storyboard.get("segments") and not str(storyboard.get("script") or "").strip():
        return False
    is_refusal, _, _ = _import_script_quality_guards()
    return is_refusal(_storyboard_script_text(storyboard))


_SPANISH_MARKERS = {
    "el", "la", "los", "las", "del", "de", "que", "quien", "quienes", "como",
    "cual", "cuales", "por", "para", "una", "unos", "unas", "fue", "fueron",
    "donde", "cuando", "sobre", "entre", "hacia",
}


def topic_needs_localization(topic: str, language: str) -> bool:
    """.Hay que llevar el tema al idioma del guion antes de investigar?

    Buscar un tema en espanol en la Wikipedia inglesa devuelve cualquier cosa
    (y siempre devuelve algo). Detecta acentos, signos invertidos y articulos
    del espanol para no gastar una llamada al LLM cuando no hace falta.
    """
    texto = (topic or "").strip()
    if not texto:
        return False
    if str(language or "").lower().startswith("es"):
        return False

    if any(c in texto for c in "ñÑ¿¡áéíóúÁÉÍÓÚüÜ"):
        return True

    import re as _re
    palabras = {w.lower() for w in _re.findall(r"[A-Za-zÀ-ÿ]+", texto)}
    return bool(palabras & _SPANISH_MARKERS)


def scene_narration_text(scene) -> str:
    """Narracion de una escena, mire donde mire el JSON.

    El LLM devuelve `narration`, pero el validador de tema leia solo
    `narration_text`/`text`: validaba contra un guion VACIO y marcaba deriva en
    guiones correctos (2026-09-01, 'Nan Madol'). Una alarma que suena siempre
    deja de mirarse, asi que las dos rutas tienen que leer por aca.
    """
    if not isinstance(scene, dict):
        return ""
    for clave in ("narration", "narration_text", "text", "voiceover", "script"):
        valor = scene.get(clave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return ""


def script_matches_topic(topic: str, title: str, script: str):
    """.El guion habla del tema pedido? Devuelve (ok, detalle).

    El 2026-08-26 se pidio "El Nucleo del Demonio" y salio un guion sobre musica
    latina, porque la investigacion habia traido el articulo equivocado. Nada
    fallo hasta que el video estuvo hecho.

    OJO: el tema hay que pasarlo YA en el idioma del guion (ver
    `_localize_topic_for_research`). Comparar "El Nucleo del Demonio" contra un
    guion en ingles no comparte una sola palabra y marcaria todo como error.
    """
    try:
        from ai.research_search import _relevance_tokens
    except Exception:
        return True, "sin validador de tokens disponible"

    del_tema = _relevance_tokens(topic)
    if not del_tema:
        return True, "tema vacio"

    del_texto = _relevance_tokens(f"{title or ''} {script or ''}")
    if not del_texto:
        return True, "guion vacio"

    presentes = del_tema & del_texto
    faltantes = del_tema - del_texto
    cobertura = len(presentes) / len(del_tema)

    # La senal es que aparezca al menos un termino DISTINTIVO del tema, no que
    # coincida un porcentaje. Los temas de este canal son titulares largos
    # ("The Carrington Event: The Day the Sun Almost Ended Civilization") y
    # exigir cobertura marcaba como deriva 12 de 139 guiones correctos.
    #
    # Que sea DISTINTIVO importa: el guion de musica latina se titulaba "The
    # Devil's Core: Latin Music's 2021 Global Surge" y compartia "core" con
    # "Demon core" por casualidad. Lo que nunca aparecia era "demon".
    distintivos = {t for t in del_tema if len(t) >= 5}
    if distintivos:
        acertados = distintivos & del_texto
        if acertados:
            return True, f"coincide en {sorted(presentes)}"
        return False, (
            f"el guion nunca menciona {sorted(distintivos)}; "
            f"solo coincide en {sorted(presentes) or 'nada'}"
        )

    # Temas de palabras cortas (Y2K, DART): no hay termino distintivo que pedir.
    if cobertura >= 0.5:
        return True, f"coincide en {sorted(presentes)}"

    return False, (
        f"el guion no menciona {sorted(faltantes)}; "
        f"terminos del tema encontrados: {sorted(presentes) or 'ninguno'}"
    )


def topics_are_same_project(current_topic, new_topic) -> bool:
    """Loose match so 'Muriq-Tidnim (Muro amorrita)' and 'Amorite Wall / Muriq-Tidnim' stay together."""
    def _norm(value: str) -> str:
        text = str(value or "").lower()
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.sub(r"[^a-z0-9áéíóúñü]+", " ", text)
        return " ".join(text.split())

    current = _norm(current_topic)
    incoming = _norm(new_topic)
    if not current or not incoming:
        return True
    if current == incoming or current in incoming or incoming in current:
        return True
    current_words = {word for word in current.split() if len(word) > 3}
    incoming_words = {word for word in incoming.split() if len(word) > 3}
    if not current_words or not incoming_words:
        return False
    overlap = current_words & incoming_words
    return bool(overlap) and (len(overlap) / min(len(current_words), len(incoming_words)) >= 0.34)


class StoryboardPromptMixin:
    @staticmethod
    def _get_tone_profile_for_category(category: str) -> str:
        """Thin wrapper over tone_profile.get_tone_profile_for_category.

        Lives here for backward-compatible call sites; the canonical mapping is in
        tone_profile.py so claude_client.py shares it.
        """
        from ai.tone_profile import get_tone_profile_for_category
        return get_tone_profile_for_category(category)


    @staticmethod
    def _build_tone_header(tone_profile: str) -> str:
        """First line of the user prompt — sets the LLM's persona by category."""
        if tone_profile == "mystery":
            return (
                'Eres un guionista experto para un canal de YouTube sobre misterios, '
                f'conspiraciones y fenómenos inexplicables llamado "{get_channel_name()}".'
            )
        if tone_profile == "dramatic_factual":
            return (
                'Eres un guionista experto en documentales cinematográficos sobre eventos '
                f'naturales extremos y catástrofes, para el canal "{get_channel_name()}". '
                'Tu estilo es dramático y tenso, pero ESTRICTAMENTE FACTUAL — sin paranormal, '
                'sin maldiciones, sin teorías sin evidencia.'
            )
        # documentary (default)
        return (
            'Eres un historiador y divulgador experto que escribe guiones de documentales '
            f'cinematográficos rigurosos para el canal "{get_channel_name()}". Tu estilo es '
            'serio, narrativo y visualmente oscuro/dramático, pero la base es ESTRICTAMENTE '
            'HISTÓRICA Y FACTUAL — nada de maldiciones inventadas, civilizaciones imposibles, '
            'OVNIs, ni conspiraciones sin evidencia documentada.'
        )


    @staticmethod
    def _tone_section_crudo(tone_profile: str, lang_label: str) -> str:
        """The TONO Y ESTILO block — replaces the previously hardcoded mystery-only version.

        Los bloques usan el marcador __CANAL__ en vez de f-strings: son literales
        triple-quoted con llaves de ejemplo dentro, y convertirlos a f-string las
        romperia. El nombre real se sustituye en `_tone_section_con_canal`.
        """
        if tone_profile == "mystery":
            return """
TONO Y ESTILO:
- Narrativa envolvente, misteriosa e intrigante (NO documental aburrido)
- Presenta las teorías como posibilidades fascinantes: "¿Y si...?", "Lo que pocos saben es..."
- Usa ganchos emocionales y cliffhangers entre escenas
- Mantén al espectador enganchado con revelaciones progresivas
- Al final, incluye una llamada a suscribirse a "__CANAL__" de forma natural"""

        if tone_profile == "dramatic_factual":
            return """
TONO Y ESTILO:
- Narrativa cinematográfica, tensa y de alto contraste — como un documental de catástrofes premium.
- Cada escena debe construir tensión: causa → señales tempranas → punto de inflexión → consecuencia.
- PROHIBIDO especular sobre causas sobrenaturales, maldiciones, profecías o "fuerzas ocultas". Solo física, geología, meteorología, etc.
- Usa cifras, fechas y testimonios reales documentados (víctimas, magnitud, áreas afectadas).
- Ganchos basados en escala real ("el sonido se escuchó a 5000 km"), no en misterio inventado.
- Al final, incluye una llamada a suscribirse a "__CANAL__" de forma natural."""

        # documentary (default)
        return """
TONO Y ESTILO:
- Narrativa de documental cinematográfico riguroso (estilo BBC/Netflix dark history), NO un canal de misterios.
- Tono dramático y narrativo permitido, PERO el contenido debe ser históricamente verificable.
- PROHIBIDO inventar maldiciones, profecías, conspiraciones modernas conectadas al tema, viajes transoceánicos no documentados, tecnologías perdidas inventadas, fenómenos paranormales, "fuerzas ocultas que aún operan hoy".
- PROHIBIDO meter contenido de canal de misterios disfrazado de historia. Si el tema es histórico, el guion es histórico.
- Usa eventos, batallas, personajes, fechas y lugares REALES y documentados por historiadores.
- Puedes usar suspenso narrativo y preguntas retóricas, pero ancladas a hechos: "¿Cómo logró Aníbal cruzar los Alpes con elefantes?" SÍ; "¿Y si Aníbal tenía tecnología perdida?" NO.
- Ganchos válidos: escala real del evento, decisiones humanas críticas, ironías históricas documentadas, consecuencias a largo plazo verificables.
- Al final, incluye una llamada a suscribirse a "__CANAL__" de forma natural."""


    @staticmethod
    def _build_tone_section(tone_profile: str, lang_label: str) -> str:
        """Bloque de tono con el nombre real del canal ya sustituido."""
        crudo = StoryboardPromptMixin._tone_section_crudo(tone_profile, lang_label)
        return crudo.replace("__CANAL__", get_channel_name())


    @staticmethod
    def _build_visual_guide_for_profile(tone_profile: str) -> str:
        """Tone-profile-specific guidance for the visual_prompt aesthetic."""
        if tone_profile == "mystery":
            return (
                "GUIA VISUAL POR PERFIL DE TONO:\n"
                "- Perfil 'mystery': estetica de misterio cinematografico oscuro (niebla densa, luz tenue, sombras profundas, elementos sugerentes pero ambiguos). "
                "Permitido: figuras a contraluz, ambigüedad visual deliberada, sugerencia (NO mostrar) de algo extrano. "
                "Mantener el realismo fotografico — no derivar a fantasy/comic art ni a CGI cartoon."
            )
        if tone_profile == "dramatic_factual":
            return (
                "GUIA VISUAL POR PERFIL DE TONO:\n"
                "- Perfil 'dramatic_factual': estetica de documental de catastrofes premium (referencias: 'Seconds From Disaster', 'Apocalypse colorizado', National Geographic disaster docs). "
                "Enfasis en escala fisica real: humo, ceniza, agua, fuego, viento, tierra removida. Testigos humanos con expresiones genuinas de miedo/sorpresa/dolor. "
                "PROHIBIDO: figuras espectrales, presagios sobrenaturales, halos magicos, brillos misticos."
            )
        # documentary (default)
        return (
            "GUIA VISUAL POR PERFIL DE TONO:\n"
            "- Perfil 'documentary': estetica de documental cinematografico oscuro (referencias: BBC dark history, Apple TV+ documentaries, Ken Burns con paleta moderna desaturada). "
            "La atmosfera oscura viene de iluminacion baja, composicion y paleta cromatica, NO de elementos fantasticos. "
            "PROHIBIDO: brillos magicos, halos sobrenaturales, auras, niebla magica, particulas brillantes flotando sin causa fisica, simbologia esoterica visible, paisajes imposibles, geometrias imposibles, criaturas inventadas, vestimentas de fantasia. "
            "Personas, edificios, herramientas y armas son los reales y documentados de la epoca."
        )


    @staticmethod
    def _build_channel_bible_section(is_short: bool, lang_label: str, tone_profile: str = "mystery",
                                    category: str = "") -> str:
        """Build channel-bible instructions for the unified prompt.

        Includes hook patterns, narrative structure, quality rules,
        editorial filter, and credibility guidelines — all sourced
        from channel.channel_strategy.py when available.
        """
        # The explicitly selected investigation category is a per-video exception
        # to the channel's usual subject exclusions, not a global Bible rewrite.
        if is_mystery_inquiry(category):
            instructions = mystery_editorial_instructions(category)
            if is_short:
                instructions += """
RITMO PARA SHORTS:
- Abre con el enigma concreto y atribuye el relato desde el gancho; nunca conviertas sus cifras en hechos probados.
- Entrega información nueva cada 5-8 segundos: fuente, evidencia, explicación o límite de esa explicación.
- Mantén las escenas breves, con suspenso y precisión. Cierra con lo conocido y la pregunta que sigue abierta.
"""
            return instructions
        sections: list[str] = []

        # ── Channel Bible (hooks, structure, tone) ──
        if is_short:
            try:
                from channel.channel_strategy import (
                    build_hook_prompt_instructions,
                    get_channel_strategy as _get_cs,
                    get_shorts_rules as _get_sr,
                )
                _sr = _get_sr()
                _cs = _get_cs()
                _hook_instr = build_hook_prompt_instructions()
                # El Bible manda: identidad, filtro editorial y temas excluidos
                # salen del perfil, no cableados. Antes esta seccion decia
                # "@Stunning-Revelations" y pedia "que sigue sin explicacion" +
                # "termina con sensacion de misterio", que empujaba al guion al
                # misterio aunque el perfil dijera otra cosa.
                _ident = _cs.get("channel_identity", {})
                _handle = _ident.get("custom_url") or _ident.get("channel_handle") or "el canal"
                _posicion = _ident.get("positioning", "")
                _fuera = _ident.get("out_of_scope") or []
                _principios = _cs.get("editorial_principles") or []
                _filtro = " ".join("¿%s?" % p.strip("¿?") for p in _principios) or \
                    "¿Qué pasó? ¿Qué cambió para siempre?"
                _salto = chr(10)
                _bloque_fuera = ""
                if _fuera:
                    _lista = _salto.join("  - %s" % t for t in _fuera)
                    _bloque_fuera = (
                        _salto + _salto
                        + "FUERA DE ALCANCE — NO escribas sobre esto ni le des ese enfoque:"
                        + _salto + _lista + _salto
                        + "Si el tema solo se sostiene porque nadie sabe la respuesta, NO es "
                          "para este canal. Contamos hechos documentados con consecuencias."
                    )
                sections.append(f"""
REGLAS ESTRICTAS PARA SHORTS — {_handle} Channel Bible:

IDENTIDAD DEL CANAL: {_posicion}{_bloque_fuera}

DURACIÓN: {_sr.get('min_duration', 45)} a {_sr.get('max_duration', 58)} segundos. NUNCA exceder {_sr.get('hard_limit', 60)} segundos.

{_hook_instr}

RITMO Y ESTRUCTURA:
- El guión debe ser de ritmo rápido, diseñado para cortes de escena cada 5-8 segundos.
- Frases cortas y contundentes. Nada de explicaciones largas.
- Cada 5-8 segundos debe introducir un dato nuevo o giro visual.
- Cierra con la CONSECUENCIA: qué cambió por lo que acabás de contar. No cierres
  insinuando un misterio abierto.

CREDIBILIDAD:
- NO presentes especulación como hecho.
- Mantén rigor histórico. Usa fechas, lugares y eventos documentados.
- El canal debe sentirse como una serie documental histórica, NO un canal de listas.

FILTRO EDITORIAL — Cada Short debe responder una de estas preguntas:
{_filtro}""")
            except ImportError:
                sections.append("""
REGLAS ESTRICTAS PARA SHORTS:
- Duración: 45 a 58 segundos. NUNCA exceder 60 segundos.
- Los primeros 1-2 segundos son CRÍTICOS. Abre con un hook brutal o premisa imposible.
  Ejemplo: "Una ciudad entera desapareció sin dejar rastro."
  Ejemplo: "En el año 536, el cielo se oscureció."
- Ritmo rápido, cortes cada 5-8 segundos.
- Frases cortas y contundentes.
- Termina con misterio o continuidad, nunca con resumen.""")

        # ── Quality rules (apply to all formats, but tone-profile-aware) ──
        if tone_profile == "mystery":
            sections.append("""
CALIDAD NARRATIVA (OBLIGATORIO):
- Escribe en tono envolvente, misterioso e intrigante — como un narrador de canal de misterios/conspiraciones.
- Presenta teorías, eventos inexplicables y explicaciones alternativas como posibilidades fascinantes, NO como tonterías desmentidas.
- Usa frases como "algunos investigadores creen", "según ciertas fuentes", "¿y si...?", "¿podría ser que...?",
  "la explicación oficial dice... pero otros sugieren", "testigos afirman", "hay quienes argumentan".
- NO seas escéptico ni despectivo. La audiencia QUIERE explorar misterios y teorías alternativas.
- NO escribas como un verificador de hechos. Escribe como un narrador que explora lo desconocido.
- Sin embargo, NO presentes afirmaciones no verificadas como hechos confirmados. Enmárcalas como posibilidades intrigantes.
- Los casos/testimonios mencionados deben haber sido REALMENTE reportados (libros, prensa, archivos, folklore documentado). NO inventes casos completos.
- Mantén consistencia interna: si mencionas una fecha o nombre, no lo contradigas después.
- Usa nombres, lugares y organizaciones reales cuando existan.
- Construye suspenso y curiosidad — usa cliffhangers entre secciones.
- Cada párrafo debe avanzar la historia; nada de relleno genérico ni repetición.
- Evita frases vacías: "como todos sabemos", "a lo largo de la historia", "sin lugar a dudas".
- Usa preguntas retóricas estratégicamente para enganchar al espectador.
- Termina con una pregunta abierta o reflexión provocadora que deje al espectador queriendo más.""")
        elif tone_profile == "dramatic_factual":
            sections.append("""
CALIDAD NARRATIVA (OBLIGATORIO):
- Escribe como un narrador de documental cinematográfico de catástrofes (estilo "Seconds From Disaster"/"Megadisasters"), con tensión real basada en hechos.
- Cada escena: causa → señales tempranas → punto de inflexión → consecuencia. Construye tensión por escala física, no por misterio inventado.
- Usa fechas, magnitudes (Richter, km², víctimas, velocidad, temperatura), nombres de lugares y de personas reales cuando existan.
- PROHIBIDO atribuir causas a maldiciones, profecías, fuerzas ocultas, OVNIs o conspiraciones — solo causas físicas/geológicas/meteorológicas/biológicas documentadas.
- Permitido el suspenso ("nadie podía imaginar lo que sucedería en las próximas 12 horas") siempre anclado a la cronología real.
- Mantén consistencia interna: cifras, fechas y nombres no se contradicen entre escenas.
- Evita frases vacías: "como todos sabemos", "a lo largo de la historia", "sin lugar a dudas".
- Termina con una reflexión sobre lecciones, riesgos actuales o eventos similares en curso, no con misterio inventado.""")
        else:  # documentary
            sections.append("""
CALIDAD NARRATIVA (OBLIGATORIO):
- Escribe como un historiador/divulgador serio que narra un documental cinematográfico oscuro (estilo BBC, Netflix dark history, Ken Burns), NO como un narrador de misterios/conspiraciones.
- TODO lo que aparece debe ser históricamente verificable: personajes, fechas, batallas, lugares, decisiones, consecuencias.
- PROHIBIDO inventar: maldiciones, OVNIs, civilizaciones cruzando océanos sin evidencia, tecnologías perdidas, profecías, conspiraciones modernas conectadas al tema histórico, "ecos que aún hoy resuenan en la política/UE/etc.", artefactos malditos.
- PROHIBIDO meter contenido de canal de misterios disfrazado. Si el tema es histórico, el guion es 100% histórico.
- Permitido y deseable: drama humano real (Aníbal y su juramento, decisiones de generales, errores estratégicos), ironías históricas documentadas, escala real (número de tropas, duración del asedio), consecuencias verificables (cambios en mapa, instituciones).
- Permitido el tono cinematográfico oscuro y la tensión narrativa, anclados a la realidad: "En la noche del 2 de agosto del 216 AC, 50 000 romanos morirían antes del amanecer" SÍ; "En la noche del 2 de agosto del 216 AC, una fuerza inexplicable cambió el destino de Europa" NO.
- Si te quedas sin hechos nuevos, PRIMERO profundiza con material documentado (contexto previo, biografías, consecuencias verificables, paralelos reales, secuelas a años). Solo acorta si después de profundizar genuinamente no hay material. NUNCA inventes.
- Mantén consistencia: nombres, fechas, lugares y bandos no se contradicen entre escenas.
- Evita frases vacías: "como todos sabemos", "a lo largo de la historia", "sin lugar a dudas", "lo que pocos saben".
- Termina con una reflexión histórica real (consecuencias, paralelos documentados, qué quedó en el mapa actual), NO con preguntas tipo "¿y si los antiguos sabían algo que nosotros no?".""")

        return "\n".join(sections)


    @staticmethod
    def _build_json_metadata_fields(is_short: bool) -> str:
        """Return extra JSON fields for short-form metadata."""
        if not is_short:
            return ""
        return """
  "cover_text": "1-3 palabras poderosas para el frame de portada del video (ej: VANISHED, ERASED, LOST EMPIRE)",
  "hook_pattern": "Patrón de hook usado: A, B, C o D",
  "category_fit": "Categoría que mejor describe este Short",
  "long_form_potential": "YES o NO — ¿podría este tema sostener un video de 8-12 minutos?",
  "long_form_angle": "Si YES, un ángulo breve para la expansión (1 oración)",
  "series_fit": "Serie a la que pertenece (ej: Lost Civilizations, Vanished Empires) o NONE","""
