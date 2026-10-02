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


from pipeline.storyboard_prompt_mixin import StoryboardPromptMixin


from pipeline.storyboard_duration_mixin import StoryboardDurationMixin


from pipeline.storyboard_factcheck_mixin import StoryboardFactCheckMixin


class StoryboardGenerator(StoryboardFactCheckMixin, StoryboardDurationMixin, StoryboardPromptMixin):
    """
    Generador de storyboards y teasers.
    Maneja la generaciÃ³n de guiones, segmentos, prompts visuales y teasers.
    """
    
    def __init__(self, log_callback=None, gemini_client=None, tts=None, 
                 subtitle_gen=None, generated_media_dir=None, jamendo_client_id=None,
                 assemble_video_callback=None):
        """
        Inicializa el generador de storyboards.
        
        Args:
            log_callback: FunciÃ³n para logging (opcional)
            gemini_client: Cliente de Gemini AI (opcional)
            tts: Generador de texto a voz (opcional)
            subtitle_gen: Generador de subtÃ­tulos (opcional)
            generated_media_dir: Directorio para medios generados (opcional)
            jamendo_client_id: ID de cliente de Jamendo (opcional)
            assemble_video_callback: FunciÃ³n para ensamblar video (opcional, necesario para teasers)
        """
        self.log = log_callback or (lambda msg: print(msg))
        self.gemini_client = gemini_client
        self.tts = tts
        self.subtitle_gen = subtitle_gen
        self.generated_media_dir = generated_media_dir or VideoConfig.TEMP_DIR / "generated_media"
        self.jamendo_client_id = jamendo_client_id
        self.assemble_video_callback = assemble_video_callback
        self._last_script_error = None

    def _unusable_script_reason(self, script, duration_seconds) -> str:
        """Return a user-facing error if the text is a refusal or far too short."""
        is_refusal, is_short, min_words = _import_script_quality_guards()
        if not script or not str(script).strip():
            return "El guion está vacío."
        if is_refusal(script):
            return (
                "El LLM devolvió un rechazo ('I can't fulfill that request') "
                "en vez de un guion. No se crearán escenas basura."
            )
        if is_short(script, duration_seconds):
            word_count = len(str(script).split())
            needed = min_words(duration_seconds)
            return (
                f"Guion demasiado corto: {word_count} palabras "
                f"(mínimo {needed} para {duration_seconds}s). Regenera el storyboard."
            )
        return ""

    def _is_long_horizontal_request(self, platform: str, custom_duration: Optional[int]) -> bool:
        """Determina si corresponde aplicar perfil de largo horizontal."""
        return platform == 'youtube'

    def _visual_prompt_aspect_rule(self, video_format=None, platform=None):
        """Ratio de imagen e instrucción para visual_prompt (16:9 / 9:16 / 1:1)."""
        try:
            from pipeline.image_generation_manager import primary_aspect_ratio_from_format
            aspect = primary_aspect_ratio_from_format(video_format, platform)
        except Exception:
            aspect = "16:9"
        leads = {
            "16:9": "cinematic 16:9",
            "9:16": "vertical 9:16",
            "1:1": "square 1:1",
        }
        lead = leads.get(aspect, "cinematic 16:9")
        rule = (
            f'- FORMATO DE IMAGEN (OBLIGATORIO): cada visual_prompt DEBE incluir '
            f'"{aspect}" cerca del inicio (ej: "{lead}, ..."). '
            f'Compone la escena para ese recuadro; no uses otro aspect ratio.'
        )
        return aspect, lead, rule

    def _localize_topic_for_research(self, topic: str, language: str) -> str:
        """Lleva el tema al idioma del guion para investigar y validar.

        No es una traduccion literal: se pide el NOMBRE de uso corriente (el que
        titularia el articulo de Wikipedia). "El Nucleo del Demonio" tiene que
        volverse "Demon core", no "The Demon Nucleus", o la busqueda sigue sin
        encontrar el articulo correcto.

        Si algo falla se devuelve el tema original: el filtro de relevancia de
        `research_search` sigue cubriendo el caso de un articulo equivocado.
        """
        original = (topic or "").strip()
        if not original or not topic_needs_localization(original, language):
            return original

        cache = getattr(self, "_topic_localization_cache", None)
        if cache is None:
            cache = self._topic_localization_cache = {}
        clave = (original.lower(), str(language or "").lower())
        if clave in cache:
            return cache[clave]

        idioma = "English" if str(language or "").lower().startswith("en") else str(language)
        prompt = (
            f"The user typed this video topic in Spanish: \"{original}\"\n\n"
            f"Give ONLY the common {idioma} name for that same subject — the one "
            f"a {idioma} encyclopedia article would use. No explanation, no "
            f"quotes, no punctuation at the end. If it is a proper noun, keep it "
            f"as is. Maximum 8 words."
        )

        resultado = original
        try:
            crudo = self.gemini_client._generate(prompt, max_tokens=60, task_type="general")
            candidato = (crudo or "").strip().strip('"').strip("'").split("\n")[0].strip()
            # Descartar respuestas raras: vacias, larguisimas o con explicacion.
            if candidato and len(candidato) <= 80 and len(candidato.split()) <= 10:
                resultado = candidato
                self.log(f"   Tema para investigar ({idioma}): '{original}' -> '{resultado}'")
            else:
                self.log(f"   [WARN] Traduccion del tema descartada por formato: {candidato[:60]!r}")
        except Exception as exc:
            self.log(f"   [WARN] No se pudo traducir el tema, se usa el original: {exc}")

        cache[clave] = resultado
        return resultado

    def _extract_llm_script_metadata(self) -> dict:
        backend = None
        if hasattr(self, 'gemini_client'):
            backend = getattr(self.gemini_client, 'backend', self.gemini_client)
        return getattr(backend, '_last_script_metadata', {}) if backend else {}

    @staticmethod
    def _is_short_form_platform(platform: Optional[str]) -> bool:
        """Plataformas verticales cortas que deben respetar el limite de Shorts."""
        return str(platform or "").strip().lower() in {"youtube_short", "tiktok", "reels"}

    def _resolve_duration_and_profile(self, platform: str, custom_duration: Optional[int]) -> Dict:
        """
        Resuelve duración objetivo y perfil narrativo.
        Para largos horizontales en YouTube, usa 1800s por defecto (mínimo 30 minutos).
        """
        profile = "default"
        target = custom_duration or VideoConfig.PLATFORM_DURATIONS.get(platform, 60)
        retention_targets = {}

        if self._is_long_horizontal_request(platform, custom_duration):
            profile = "long_horizontal"
            min_long_duration = 1800
            if custom_duration is None:
                target = min_long_duration
            else:
                try:
                    target = max(min_long_duration, int(custom_duration))
                except Exception:
                    target = min_long_duration
            retention_targets = {
                "r30_min": 55.0,
                "r60_min": 35.0
            }

        return {
            "profile": profile,
            "duration_target": int(target),
            "retention_targets": retention_targets,
            "recommended_duration_min": 1800 if profile == "long_horizontal" else None,
            "recommended_duration_max": 2700 if profile == "long_horizontal" else None
        }








    def _estimate_long_intro_quality_score(self, segments: List[Dict]) -> float:
        """
        Heurística local para estimar calidad de retención del primer minuto.
        Devuelve 0-100.
        """
        if not segments:
            return 0.0

        def _seg_start(seg):
            try:
                return float(seg.get('start', 0.0))
            except Exception:
                return 0.0

        def _seg_end(seg):
            start = _seg_start(seg)
            try:
                end = float(seg.get('end', start))
            except Exception:
                end = start
            return end if end >= start else start

        def _seg_text(seg):
            return str(seg.get('text') or seg.get('narration_text') or seg.get('narration') or '').strip()

        first_60 = [s for s in segments if _seg_start(s) < 60]
        first_30 = [s for s in segments if _seg_start(s) < 30]
        first_15 = [s for s in segments if _seg_start(s) < 15]
        if not first_60:
            return 0.0

        durations_60 = [max(0.0, _seg_end(s) - _seg_start(s)) for s in first_60]
        durations_15 = [max(0.0, _seg_end(s) - _seg_start(s)) for s in first_15] or [0.0]
        avg_60 = sum(durations_60) / max(1, len(durations_60))
        longest_15 = max(durations_15)

        text_30 = " ".join(_seg_text(s) for s in first_30).strip()
        words_30 = len(text_30.split())
        hook_markers = [
            "?", "¿", "secreto", "misterio", "descubre", "descubrir",
            "truth", "hidden", "why", "how", "what if"
        ]
        text_30_l = text_30.lower()
        has_hook = any(marker in text_30_l for marker in hook_markers)

        score = 62.0
        if len(first_15) < 4:
            score -= (4 - len(first_15)) * 7.0
        if len(first_30) < 7:
            score -= (7 - len(first_30)) * 4.0
        if longest_15 > 5.0:
            score -= min(15.0, (longest_15 - 5.0) * 4.0)
        if avg_60 > 4.8:
            score -= min(12.0, (avg_60 - 4.8) * 6.0)
        if has_hook:
            score += 6.0
        else:
            score -= 6.0
        if words_30 > 95:
            score -= 6.0
        elif words_30 < 35:
            score -= 4.0

        if score < 0:
            score = 0.0
        if score > 100:
            score = 100.0
        return round(score, 1)

    def _build_narrative_context(self, segments: List[Dict], start_idx: int, end_idx: Optional[int] = None) -> Dict:
        """Construye una ventana narrativa local para mejorar la coherencia del prompt visual."""
        if not segments:
            return {}

        total_segments = len(segments)
        start_idx = max(0, min(start_idx, total_segments - 1))
        end_idx = start_idx if end_idx is None else max(start_idx, min(end_idx, total_segments - 1))

        def _segment_text(seg: Dict) -> str:
            return str(seg.get('text') or seg.get('narration_text') or seg.get('narration') or '').strip()

        def _collect_text(from_idx: int, to_idx: int, max_chars: int) -> str:
            if from_idx > to_idx:
                return ""
            joined = " ".join(
                _segment_text(segments[idx])
                for idx in range(from_idx, to_idx + 1)
                if _segment_text(segments[idx])
            ).strip()
            if len(joined) <= max_chars:
                return joined
            return joined[:max_chars].rstrip() + "..."

        midpoint = ((start_idx + end_idx) / 2.0) + 1.0
        progress = midpoint / max(1, total_segments)
        if progress <= 0.18:
            narrative_role = "opening setup or hook"
        elif progress <= 0.45:
            narrative_role = "early development"
        elif progress <= 0.72:
            narrative_role = "core explanation or escalation"
        elif progress <= 0.9:
            narrative_role = "late development or payoff"
        else:
            narrative_role = "closing beat or conclusion"

        if start_idx == end_idx:
            segment_range = f"segment {start_idx + 1} of {total_segments}"
        else:
            segment_range = f"segments {start_idx + 1}-{end_idx + 1} of {total_segments}"

        return {
            "segment_range": segment_range,
            "narrative_role": narrative_role,
            "previous_context": _collect_text(max(0, start_idx - 2), start_idx - 1, 280),
            "current_focus": _collect_text(start_idx, end_idx, 420),
            "next_context": _collect_text(end_idx + 1, min(total_segments - 1, end_idx + 2), 280),
            "continuity_note": (
                "Use adjacent context only to preserve continuity. The image must depict the current narration beat."
            ),
        }

    def _resolve_prompt_stride(self, generation_profile: str, duration_target: int, segment_count: int) -> int:
        """
        Define cuántos segmentos comparten el mismo prompt visual.
        Reduce llamadas IA para videos largos sin perder coherencia visual.
        """
        if segment_count <= 0:
            return 1
        if generation_profile != "long_horizontal":
            return 1

        # En largos de 30-45 min, apuntar aprox. a 90-180 prompts máximos.
        target_prompt_calls = max(90, min(180, int(max(1, duration_target) / 20)))
        stride = max(1, int(round(segment_count / max(1, target_prompt_calls))))
        return min(8, stride)






    # ------------------------------------------------------------------
    # Channel-bible prompt helpers (used by generate_manual_prompt_text)
    # ------------------------------------------------------------------








    def generate_manual_prompt_text(self, topic, category, duration, language='es',
                                    research_context=None, video_format=None, platform=None,
                                    opening_style="hook_overlay_v1"):
        """
        Genera el texto del prompt para modo manual (JSON).
        
        Args:
            topic: Tema del video
            category: CategorÃ­a del video
            duration: DuraciÃ³n en segundos
            language: Idioma ('es' o 'en')
            research_context: Lista de snippets de investigaciÃ³n (opcional)
            video_format: Formato de video ('9:16', '16:9', etc.)
            platform: Plataforma objetivo ('youtube_short', 'youtube_vertical', etc.)
        
        Returns:
            String con el prompt para la IA
        """
        lang_str = "SPANISH" if language == 'es' else "ENGLISH"
        lang_label = "español" if language == 'es' else "English"
        try:
            duration_value = int(duration)
        except Exception:
            duration_value = 60
        normalized_platform = str(platform or '').strip().lower()
        image_aspect, aspect_lead, aspect_rule = self._visual_prompt_aspect_rule(
            video_format, platform
        )
        is_vertical_format = image_aspect == "9:16"
        is_short_vertical = self._is_short_form_platform(platform) or (
            platform is None and is_vertical_format
        )
        if is_short_vertical and duration_value > 180:
            duration_value = 180
        if is_short_vertical:
            # ~2.5 palabras/seg es el ritmo real de TTS (medido con edge-tts).
            # Antes usábamos 2.2 conservador, pero eso dejaba margen tan apretado
            # que el LLM se quedaba muy por debajo del mínimo. Subir a 2.5 da
            # un objetivo más alcanzable y aún cabe en TTS sin recortes.
            words_estimate = int(duration_value * 2.5)
            estimated_scenes = max(3, min(10, int(duration_value / 7)))
        else:
            words_estimate = int(duration_value * 2.5)
            estimated_scenes = max(3, int(duration_value / 4.5))
        
        # Sección de contexto de investigación
        research_section = ""
        if research_context and len(research_context) > 0:
            research_text = "\n\n".join(f"--- Fuente {i+1} ---\n{snippet}" 
                                        for i, snippet in enumerate(research_context))
            research_section = f"""
CONTEXTO DE INVESTIGACIÓN (usa estas fuentes como base para el guión):
{research_text}

IMPORTANTE: Basa el guión en la información de estas fuentes. Puedes expandir, conectar ideas y
agregar narrativa, pero NO inventes datos que contradigan las fuentes.
"""
        
        # Sección de formato de video
        format_section = ""
        length_contract = ""
        if is_short_vertical:
            # Calcular duración MÍNIMA aceptable: 80% del target. Para 60s = 48s mínimo.
            min_duration = int(max(15, duration_value * 0.80))
            min_words = int(min_duration * 2.5)
            min_words_per_scene = max(12, int(min_words / max(estimated_scenes, 1)))
            target_words_per_scene = max(min_words_per_scene + 3, int(words_estimate / max(estimated_scenes, 1)))

            # CONTRATO de longitud va al TOPE del prompt para máxima saliencia.
            # En tests anteriores, las instrucciones de duración estaban enterradas
            # en el medio del prompt y el LLM las ignoraba (producía 35 palabras
            # cuando el mínimo era 105). Llevarlas arriba + repetirlas con números
            # explícitos + per-scene minimums obliga al LLM a planificar para el largo.
            length_contract = f"""
╔══════════════════════════════════════════════════════════════════╗
║  CONTRATO DE LONGITUD (REQUISITO BLOQUEANTE — LEE ESTO PRIMERO)  ║
╚══════════════════════════════════════════════════════════════════╝

Este Short DEBE tener entre {min_words} y {words_estimate} palabras de narración total.
- Mínimo absoluto: {min_words} palabras ({min_duration}s de audio)  ← NO BAJES de esto
- Objetivo ideal: {words_estimate} palabras ({duration_value}s de audio)
- Distribución: exactamente {estimated_scenes} escenas, cada una entre
  {min_words_per_scene} y {target_words_per_scene + 5} palabras (objetivo: ~{target_words_per_scene}).

Un guion con MENOS de {min_words} palabras será RECHAZADO automáticamente.
Antes de finalizar, CUENTA TUS PALABRAS y verifica que el total está entre
{min_words} y {words_estimate}.

CÓMO LLEGAR AL MÍNIMO SIN INVENTAR: si tras cubrir el hecho principal
te faltan palabras, profundiza con AL MENOS DOS de estos ángulos
documentados (todos verificables en fuentes históricas reales).
OJO CON EL ORDEN: los marcados [TEMPRANO] pueden ir en las primeras
escenas; los marcados [DESPUÉS] SOLO a partir de la escena 4.
  1. [TEMPRANO] PUNTO DE INFLEXIÓN EN DETALLE: cronología precisa del
     momento crítico (hora exacta, datos físicos: temperatura, velocidad,
     magnitud, víctimas)
  2. [TEMPRANO] SOBREVIVIENTES O TESTIGOS REALES: nombres documentados,
     qué vieron en el momento
  3. [TEMPRANO] LA CIFRA QUE NO SE ESPERA: el dato más contraintuitivo
     del hecho, dicho sin rodeos
  4. [DESPUÉS] DECISIONES CRÍTICAS: figuras reales con nombre que tomaron
     decisiones clave (y sus consecuencias documentadas)
  5. [DESPUÉS] CONTEXTO PRE-EVENTO: qué pasaba en las semanas/días previos
  6. [DESPUÉS] CONSECUENCIAS VERIFICABLES: a 1 día, 1 año, décadas vista
  7. [DESPUÉS] LEGADO HISTÓRICO: qué cambió permanentemente como resultado
"""

            format_section = f"""
FORMATO: YouTube Short (vertical 9:16) — duración objetivo {duration_value}s.
- Estructura: {estimated_scenes} escenas × {min_words_per_scene}-{target_words_per_scene + 5} palabras (objetivo {target_words_per_scene}).
- NUNCA menos de {min_words_per_scene} palabras por escena.
- NUNCA menos de {min_words} palabras totales.
- Ritmo rápido: engancha en los primeros 3 segundos y mantén la tensión.

  ESTRUCTURA DE RETENCIÓN (medido en las curvas reales del canal: el hook
  funciona, pero entre el segundo 6 y el 20 se va el 35% de la audiencia,
  justo donde los guiones ponen contexto):
  * Escenas 1, 2 y 3 = TODO CARGA ÚTIL. Cada una entrega un hecho concreto
    con cifra, nombre o consecuencia. Es el tramo donde la gente decide
    quedarse o irse.
  * PROHIBIDO en las escenas 1-3: preparar la escena, describir el clima,
    contar qué pasaba antes, explicar sistemas o procedimientos, presentar
    instituciones. Todo eso es contexto y va de la escena 4 en adelante.
  * Lo que prometas en la escena 1 tiene que OCURRIR como muy tarde en la
    escena 3. Si el hecho central todavía no pasó a los 20 segundos, el
    guion está mal ordenado.
  * El contexto no se elimina: se gana el derecho a explicarlo DESPUÉS de
    haber entregado lo prometido.
- Cada frase debe aportar valor — evita relleno genérico, pero SÍ desarrolla con material documentado.
- Cada visual_prompt debe comenzar con "{aspect_lead}".
"""
        elif is_vertical_format:
            format_section = f"""
FORMATO: Video vertical 9:16 para YouTube (largo).
- Objetivo de duración: {duration_value} segundos.
- Este video NO debe plantearse como un Short; puede superar 180 segundos.
- Mantén composición vertical clara para smartphone, con visuales legibles y foco central.
- Sostén la retención con progresión narrativa, mini-ganchos periódicos y cierres parciales entre escenas.
- Cada visual_prompt debe comenzar con "{aspect_lead}".
"""
        elif image_aspect == "1:1":
            format_section = f"""
FORMATO: Video cuadrado 1:1.
- Objetivo de duración: {duration_value} segundos.
- Cada visual_prompt debe comenzar con "{aspect_lead}" para componer en cuadrado.
"""
        else:
            format_section = f"""
FORMATO: Video horizontal 16:9 para YouTube.
- Objetivo de duración: {duration_value} segundos.
- Cada visual_prompt debe comenzar con "{aspect_lead}" para componer en apaisado.
"""

        # Tone profile drives header, channel bible and tono section.
        tone_profile = self._get_tone_profile_for_category(category)
        tone_header = self._build_tone_header(tone_profile)
        tone_section = self._build_tone_section(tone_profile, lang_label)
        from pipeline.video_opening import opening_script_instructions
        opening_section = opening_script_instructions(
            opening_style, language=language, include_visuals=True
        )

        prompt = f"""{tone_header}
{length_contract}
TAREA: Escribe un guión técnico en formato JSON para un video de {duration_value} segundos sobre:

TEMA: "{topic}"
CATEGORÍA: {category}
PERFIL DE TONO: {tone_profile}
IDIOMA DE NARRACIÓN: {lang_label}
{format_section}{research_section}
{opening_section}

REGLA FUNDAMENTAL — SOLO CASOS DOCUMENTADOS (NO INVENTES):
- El guión debe basarse EXCLUSIVAMENTE en hechos, eventos, personajes, fechas, lugares y testimonios documentados que existan en la realidad.
- NO inventes casos, nombres, fechas, lugares, eventos, citas, instituciones, programas, leyes ni iniciativas. Todo debe ser verificable.
- PROHIBIDO conectar el tema con maldiciones inventadas, OVNIs (salvo categoría de misterios), civilizaciones cruzando océanos sin evidencia, "iniciativas secretas de la UE", artefactos malditos, frecuencias sónicas activadoras, ecos paranormales modernos, etc., A MENOS QUE el PERFIL DE TONO sea "mystery".
- Para perfiles "documentary" y "dramatic_factual": cero contenido paranormal o conspiranoico, incluso disfrazado. Si dudas si algo está documentado, NO lo incluyas.
- Para perfil "mystery": está permitido tratar reportes/testimonios/folklore como posibilidades, pero el caso o reporte mencionado debe haber existido realmente (no inventarlo completo).
- Si mencionas una fecha, nombre o evento específico, debe ser real. Si no estás seguro, usa formulaciones como "según reportes de la época" o "testigos afirmaron que...", o directamente NO lo incluyas.
- ERRORES QUE YA SALIERON PUBLICADOS Y NO PUEDEN REPETIRSE: atribuir una muerte, captura o victoria a quien no corresponde (ej.: "el Victory mató a Villeneuve", cuando Villeneuve fue capturado y el que murió fue Nelson); inventar advertencias, órdenes, diálogos o citas; mover un hecho de fecha o de orden; presentar un mito popular como hecho. Ante la duda, frase general verdadera. El guion se verifica contra Wikipedia antes de la voz.
- Puedes plantear preguntas abiertas ("¿Y si esto fuera verdad?") SOLO en perfil "mystery". En documentary, las preguntas deben ser sobre hechos reales debatidos por historiadores ("¿qué ruta exacta tomó Aníbal por los Alpes?").
- ESTRATEGIA SI TE QUEDAS SIN HECHOS NUEVOS: NO acortes inmediatamente. PRIMERO profundiza
  con material documentado adicional: contexto histórico previo, biografía relevante de los
  protagonistas reales, decisiones críticas con justificación documentada, consecuencias
  verificables (a corto plazo y a años/décadas vista), paralelos reales con eventos similares
  documentados por historiadores, testimonios de fuentes primarias reales, datos verificables
  sobre escala / víctimas / impacto geográfico. Solo si AGOTASTE de buena fe el material
  documentado disponible y aun así no llegas al mínimo, ahí sí acorta. NUNCA inventes.

REGLA VISUAL HISTORICA / TEMPORAL:
- Antes de escribir las escenas, deduce la epoca, region, cultura, tecnologia disponible, vestimenta, arquitectura y objetos permitidos del TEMA y de la investigacion.
- Cada visual_prompt debe incluir explicitamente la epoca/lugar en ingles (ej: "set in Cold War Tehran, 1976" o "set in Bronze Age Sicily, c. 214 BCE").
- No mezcles epocas: ropa, armas, barcos, vehiculos, arquitectura, peinados, joyas, escritura, herramientas y materiales deben corresponder a esa epoca.
- Prohibe anacronismos visibles: smartphones, autos modernos, plastico, pantallas LED, senaletica moderna, relojes, lentes, telas contemporaneas, armas/armaduras de otra epoca, salvo que el tema lo permita. ABSOLUTAMENTE PROHIBIDO incluir turistas, espectadores modernos, ropa actual, mochilas, camaras o elementos contemporaneos observando el evento.
- Si una escena es una llamada a suscribirse, mantenla dentro del mundo visual del video (pergaminos, antorchas, mapas, radios analogicas, documentos, etc.), no uses iconos modernos ni UI.
- CONSISTENCIA NARRATIVA: los visual_prompt deben ser coherentes entre si. Si el guion menciona soldados romanos con armadura especifica, todos los segmentos siguientes que los incluyan deben mostrar exactamente el mismo tipo de soldados. No cambies el estilo visual, la raza de los personajes, la indumentaria ni la arquitectura entre escenas sin que la narrativa lo justifique.

REGLA VISUAL — CALIDAD CINEMATOGRAFICA (OBLIGATORIO):
{aspect_rule}
Cada visual_prompt debe incorporar EXPLICITAMENTE estos 7 elementos, en ingles, separados por comas:
  1. SUJETO PRINCIPAL claro y su accion (ej: "Hannibal Barca on horseback surveying the battlefield"). El sujeto DEBE SER la accion o evento principal descrito (ej: la batalla, la muralla, el desastre), NUNCA enfoques la imagen en narradores, eruditos, escribas, o pergaminos escribiendo sobre el evento. Queremos ver la accion historica real, no a la gente registrandola. Evita escenas vacias sin foco.
  2. AMBIENTE Y EPOCA (ej: "set in 3rd century BCE, plains of Cannae, southern Italy at dawn").
  3. ENCUADRE / PLANO: usa terminologia de cine — "wide establishing shot", "medium shot", "close-up", "low-angle shot", "over-the-shoulder", "Dutch angle". Varia entre escenas.
  4. ILUMINACION especifica (NO solo "dramatic lighting"). Ejemplos validos: "chiaroscuro side lighting from a single torch", "golden-hour rim light", "overcast diffused light", "moonlit with volumetric god rays through dust", "candlelit interior with deep shadows".
  5. PALETA Y MOOD: paleta cromatica (ej: "muted earth tones, ochre and bronze") y mood en 1-2 palabras (ej: "foreboding", "solemn", "tense", "awe-inspiring", "contemplative").
  6. CALIDAD FOTOGRAFICA: usa terminos que empujen hacia realismo coherente — "shot on 35mm film", "shallow depth of field with bokeh", "shot on Arri Alexa", "documentary photography style", "National Geographic photography", "Roger Deakins cinematography", "atmospheric haze with floating dust particles". NO uses "8k" ni "hyperrealistic" (causan artefactos).
  7. ANTI-ARTEFACTO: incluye "natural anatomy, realistic proportions, coherent hands and faces, strictly period-accurate historical attire, ancient setting only, immersive historical reenactment, devoid of contemporary elements" en escenas con personas visibles.
{self._build_visual_guide_for_profile(tone_profile)}

REGLA ABSOLUTA — CERO TEXTO EN LAS IMAGENES:
- PROHIBIDO incluir texto visible de cualquier tipo en el visual_prompt: sin letreros, sin carteles, sin inscripciones legibles, sin papiros con texto, sin subtitulos, sin titulos, sin marcas de agua, sin logos, sin UI, sin numeros, sin letras de ninguna clase.
- Esto incluye: signos, senaletica, escritura cuneiforme visible, jeroglificos legibles, pergaminos con texto, libros abiertos con texto, pizarrones, pantallas con texto, banderas con letras, monedas con inscripciones visibles.
- EXCEPCION UNICA: si el prompt describe un objeto cuya funcion es decorativa y cuyo texto no es legible (ej: "ancient carved stone with worn indistinct symbols"), esta permitido SOLO si los simbolos son ilegibles y no identificables como texto moderno.
- Siempre termina cada visual_prompt con: "no text, no writing, no signs, no captions, no watermarks"

{tone_section}
{self._build_channel_bible_section(is_short_vertical, lang_label, tone_profile, category)}
ESTRUCTURA JSON REQUERIDA (responde SOLO con este JSON, sin texto adicional):
{{
  "title": "Título impactante del video en {lang_label}",{self._build_json_metadata_fields(is_short_vertical)}
  "scenes": [
    {{
      "narration": "Texto completo de narración para esta escena en {lang_label}. Debe ser un párrafo sustancial (varias oraciones).",
      "visual_prompt": "Descripción visual detallada EN INGLÉS para generar imagen con IA. DEBE incluir {image_aspect} cerca del inicio y los 7 elementos de la REGLA VISUAL — CALIDAD CINEMATOGRAFICA (sujeto+accion, ambiente+epoca, encuadre, iluminacion especifica, paleta+mood, calidad fotografica, anti-artefacto). NUNCA incluir texto visible. EJEMPLO COMPLETO: '{aspect_lead}, Roman legionaries in lorica segmentata advancing in tight testudo formation, set in dense foggy Germanic forest at dawn c. 9 AD, low-angle medium shot looking up at their shields, chiaroscuro lighting from breaking sunlight through mist with volumetric god rays, muted earth-tone palette of moss green and tarnished bronze, tense and foreboding mood, shot on 35mm film with shallow depth of field, atmospheric haze and floating dust particles, natural anatomy and realistic proportions, coherent hands and faces, strictly period-accurate historical attire, ancient setting only, immersive historical reenactment, devoid of contemporary elements, Roger Deakins cinematography, no text, no writing, no signs, no captions, no watermarks'",
      "sfx_tag": "Efecto de sonido en inglés (ej: 'thunder', 'suspense', 'wind') o 'none'",
      "overlay_tag": "GIF/sticker descriptivo en inglés o 'none'"
    }}
  ]
}}

REGLAS CRÍTICAS:
1. Genera exactamente {estimated_scenes} escenas (aprox. {duration_value // estimated_scenes}s cada una)
2. Toda la narración en {lang_label}, todos los visual_prompt en INGLÉS
3. Cada escena debe tener narración de ~{words_estimate // estimated_scenes} palabras (ni mucho más, ni frases sueltas)
4. Los visual_prompt deben ser detallados y cinematográficos, históricamente consistentes entre sí, y SIEMPRE terminar con "no text, no writing, no signs, no captions, no watermarks"
5. Responde ÚNICAMENTE con el JSON, sin explicaciones antes o después
6. El total de palabras de narración debe ser aproximadamente {words_estimate}
7. Cada párrafo de narración debe avanzar la historia; nada de relleno genérico ni frases vacías como "a lo largo de la historia" o "como todos sabemos"
8. Usa preguntas retóricas estratégicamente para enganchar ("¿Pero qué pasó realmente esa noche?")
9. Termina con una pregunta abierta o reflexión que deje al espectador queriendo más

✅ AUTO-CHECK FINAL ANTES DE ENVIAR (obligatorio):
   - Suma mentalmente las palabras de todas las narraciones.
   - Si el total NO está en el rango establecido al inicio de este prompt
     (ver CONTRATO DE LONGITUD), REESCRIBE las escenas más cortas profundizando
     con material documentado (ver los 6 ángulos del contrato) antes de enviar.
   - Si una escena tiene menos palabras que el mínimo establecido, EXPÁNDELA
     con detalles factuales reales de los ángulos sugeridos.
   - SOLO envía el JSON cuando todas las escenas cumplan los mínimos."""
        
        return prompt

    def _generate_short_structured(
        self,
        topic: str,
        category: str,
        platform: str,
        duration_target: int,
        voice_id: Optional[str],
        language: str,
        research_context: list,
        find_auto_music: bool,
        rate: str,
        opening_style: str,
    ) -> Optional[Dict]:
        """Generate a Short storyboard via the unified JSON prompt.

        Uses the same prompt as the manual path (generate_manual_prompt_text)
        so both automatic and manual flows share identical quality/structure.
        Visual prompts come inline — no per-segment API calls, no Whisper.

        Falls back to None so the caller can retry with the legacy plain-text
        path if parsing fails.
        """
        import json as _json
        import re as _re

        self.log("   🎯 Modo JSON estructurado para Short (prompt unificado)")

        # 1. Build the unified prompt (same one the user copies for manual)
        prompt = self.generate_manual_prompt_text(
            topic=topic,
            category=category,
            duration=duration_target,
            language=language,
            research_context=research_context or None,
            video_format="9:16",
            platform=platform,
            opening_style=opening_style,
        )

        # 2. Send to LLM with task_type='script_quality' so Groq prefers gpt-oss-120b
        # (mejor para seguir restricciones de longitud que llama-3.3-70b-versatile).
        raw = self.gemini_client._generate(prompt, max_tokens=8000, task_type="script_quality")
        if not raw or str(raw).startswith("ERROR"):
            self.log(f"   ⚠️ LLM no devolvió respuesta válida para JSON estructurado")
            return None

        # 3. Parse JSON from the response
        clean = raw.strip()
        if "```json" in clean:
            clean = clean.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in clean:
            clean = clean.split("```", 1)[1].split("```", 1)[0]
        clean = _re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', clean)
        if '{' in clean and '}' in clean:
            start = clean.find('{')
            end = clean.rfind('}') + 1
            if start >= 0 and end > start:
                clean = clean[start:end]

        try:
            json_data = _json.loads(clean)
        except _json.JSONDecodeError as e:
            self.log(f"   ⚠️ Error parseando JSON del LLM: {e}")
            self.log(f"   ⚠️ Fallback al flujo clásico (texto plano + Whisper)")
            return None

        if "scenes" not in json_data or not json_data["scenes"]:
            self.log("   ⚠️ JSON no contiene escenas válidas — fallback al flujo clásico")
            return None

        scenes = json_data["scenes"]
        self.log(f"   ✅ JSON parseado: {len(scenes)} escenas, título: {json_data.get('title', '?')}")

        # 3.3 .El guion habla del tema pedido? Una investigacion equivocada
        # arrastra al LLM a otro tema y hasta ahora nada lo detectaba: el video
        # se descubria mal recien al verlo.
        try:
            tema_validacion = self._localize_topic_for_research(topic, language)
            # Si el tema necesitaba traduccion y no se logro, NO se valida: el
            # tema quedaria en espanol contra un guion en ingles y marcaria
            # deriva siempre. Una alerta que salta siempre no la mira nadie.
            sin_traducir = (
                topic_needs_localization(topic, language)
                and tema_validacion.strip().lower() == (topic or "").strip().lower()
            )
            if sin_traducir:
                raise RuntimeError(
                    "el tema no pudo llevarse al idioma del guion; se omite la validacion"
                )

            texto_guion = " ".join(scene_narration_text(s) for s in scenes)
            if not texto_guion.strip():
                raise RuntimeError(
                    "no se pudo leer la narracion de las escenas; se omite la validacion"
                )
            coincide, detalle = script_matches_topic(
                tema_validacion, json_data.get("title", ""), texto_guion
            )
            if not coincide:
                self.log("   " + "=" * 58)
                self.log(f"   [FAIL] EL GUION NO HABLA DEL TEMA PEDIDO ('{tema_validacion}')")
                self.log(f"          {detalle}")
                self.log(f"          Titulo generado: {json_data.get('title', '?')}")
                self.log("          Suele venir de investigacion equivocada. Revisa el guion")
                self.log("          antes de gastar imagenes y TTS.")
                self.log("   " + "=" * 58)
            else:
                self.log(f"   ✅ El guion habla del tema ({detalle})")
        except Exception as exc:
            self.log(f"   [WARN] No se pudo validar el tema del guion: {exc}")

        # 3.4 .Lo que DICE el guion es cierto? Las tres validaciones anteriores
        # (rechazo, largo, tema) no miran los datos, y el canal se apoya en
        # cifras: un numero inventado en el gancho es el error mas caro.
        try:
            from ai.script_fact_guard import audit_script, format_report

            texto_para_datos = " ".join(scene_narration_text(s) for s in scenes)
            informe = audit_script(texto_para_datos, research_context)
            self.log("   " + "-" * 58)
            for linea in format_report(informe):
                self.log("   " + linea.strip())
            if informe.verdict == "revisar":
                self.log("          Revisa esas cifras ANTES de gastar imagenes y TTS.")
            self.log("   " + "-" * 58)
        except Exception as exc:
            self.log(f"   [WARN] No se pudo verificar los datos del guion: {exc}")

        # 3.4 Validación de longitud BIDIRECCIONAL (min y max) + auto-retry.
        # En pruebas: gpt-oss-120b se quedaba 5x corto; llama-3.3-70b corrigió pero
        # se pasó 2.5x del techo. Necesitamos validar ambos extremos y hacer
        # expansión O compresión según el caso.
        try:
            min_acceptable_words = int(max(duration_target, 30) * 0.80 * 2.5)
            target_words = int(max(duration_target, 30) * 2.5)
            # Techo absoluto: 110% del target. Si pasamos esto, el video excede
            # la duración objetivo de Shorts (60s YouTube hard limit).
            max_acceptable_words = int(target_words * 1.10)
        except Exception:
            min_acceptable_words = 90
            target_words = 120
            max_acceptable_words = 132

        def _count_words(scs):
            total = 0
            for s in scs:
                txt = str(s.get("narration") or s.get("text") or "")
                total += len([w for w in txt.split() if w])
            return total

        def _reparse_json(raw_text):
            clean_r = raw_text.strip()
            if "```json" in clean_r:
                clean_r = clean_r.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in clean_r:
                clean_r = clean_r.split("```", 1)[1].split("```", 1)[0]
            clean_r = _re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', clean_r)
            if '{' in clean_r and '}' in clean_r:
                rs = clean_r.find('{')
                re_ = clean_r.rfind('}') + 1
                if rs >= 0 and re_ > rs:
                    clean_r = clean_r[rs:re_]
            try:
                return _json.loads(clean_r)
            except _json.JSONDecodeError:
                return None

        current_words = _count_words(scenes)
        attempt = 0
        MAX_TOTAL_RETRIES = 2  # Total expansion + compression attempts combined

        while attempt < MAX_TOTAL_RETRIES:
            below_min = current_words < min_acceptable_words
            above_max = current_words > max_acceptable_words
            if not below_min and not above_max:
                break  # within [min, max] band — done

            attempt += 1
            action = "expansión" if below_min else "compresión"
            self.log(
                f"   ⚠️ Guion fuera de banda: {current_words} palabras "
                f"(necesita {min_acceptable_words}–{max_acceptable_words}). "
                f"Solicitando {action} al LLM (intento {attempt}/{MAX_TOTAL_RETRIES})..."
            )

            min_per_scene = max(12, int(target_words / max(len(scenes), 1)))
            max_per_scene = max(min_per_scene + 5, int(max_acceptable_words / max(len(scenes), 1)))

            scene_word_counts = []
            for idx, s in enumerate(scenes, start=1):
                txt = str(s.get("narration") or s.get("text") or "")
                scene_word_counts.append((idx, len([w for w in txt.split() if w])))

            existing_json_str = _json.dumps(json_data, ensure_ascii=False, indent=2)

            if below_min:
                # EXPANSION prompt
                short_scenes = [
                    f"  - Escena {idx}: {wc} palabras (necesita {min_per_scene}–{max_per_scene})"
                    for idx, wc in scene_word_counts if wc < min_per_scene
                ]
                short_block = "\n".join(short_scenes) if short_scenes else "  (todas las escenas tienen algo, pero el total sigue corto)"
                # Tu respuesta anterior fue X. Necesitas Y. Diferencia = Y - X palabras
                # nuevas a añadir. Reparto entre las escenas cortas.
                deficit = target_words - current_words
                action_prompt = (
                    "❌ Tu respuesta anterior tuvo SOLO " + str(current_words) +
                    " palabras de narración total.\n"
                    "✅ Necesitas AL MENOS " + str(min_acceptable_words) + " palabras "
                    "(ideal: " + str(target_words) + ", máximo: " + str(max_acceptable_words) + ").\n"
                    "📈 Tienes que AGREGAR ~" + str(deficit) + " palabras de contenido documentado.\n\n"
                    "INSTRUCCIÓN DIRECTA:\n"
                    "Para CADA escena que aparece abajo como 'corta', DEBES DOBLAR o TRIPLICAR\n"
                    "su narración actual hasta llegar a " + str(min_per_scene) + "-" + str(max_per_scene) +
                    " palabras por escena. NO basta con cambiar 2-3 palabras: tienes que\n"
                    "AGREGAR datos documentados reales que actualmente faltan.\n\n"
                    "PROFUNDIZA con MATERIAL DOCUMENTADO ADICIONAL (escoge 2-3 ángulos\n"
                    "RELEVANTES por escena, NO inventes):\n"
                    "  1. Contexto pre-evento: qué pasaba en las semanas/días previos\n"
                    "  2. Figuras reales nombradas y sus decisiones documentadas\n"
                    "  3. Cronología: el orden de los hechos y cifras que conozcas con certeza\n"
                    "  4. Sobrevivientes o testigos REALES y lo que documentadamente vivieron\n"
                    "  5. Consecuencias verificables: a 1 día, 1 año, décadas\n"
                    "  6. Legado: qué cambió permanentemente en historia/ciencia\n\n"
                    "⛔ Si NO estás SEGURO de un detalle (hora exacta, cita textual, quién murió,\n"
                    "mató o capturó a quién, una advertencia u orden), NO lo pongas: una frase\n"
                    "general verdadera vale más que un detalle falso. El guion se verifica después\n"
                    "contra Wikipedia y lo inventado se reescribe o frena la subida.\n\n"
                    "Escenas QUE NECESITAN DOBLAR/TRIPLICAR longitud:\n" + short_block + "\n\n"
                    "⚠️ EJEMPLO DE EXPANSIÓN CORRECTA:\n"
                    "   ANTES (4 palabras): 'The volcano erupted suddenly.'\n"
                    "   DESPUÉS (18 palabras): 'On May 8 at 7:50 AM, Mount Pelée's "
                    "northwest flank exploded, releasing a pyroclastic flow at 670 km/h.'\n\n"
                    "⛔ TECHO MÁXIMO: NO superes " + str(max_acceptable_words) + " palabras totales.\n"
                    "⚠️ Tu próxima respuesta SERÁ MEDIDA. Si vuelve a estar bajo " +
                    str(min_acceptable_words) + ", se considera REGRESIÓN y se rechaza."
                )
            else:
                # COMPRESSION prompt
                long_scenes = [
                    f"  - Escena {idx}: {wc} palabras (máximo {max_per_scene})"
                    for idx, wc in scene_word_counts if wc > max_per_scene
                ]
                long_block = "\n".join(long_scenes) if long_scenes else "  (todas las escenas están dentro del máximo individual pero el total se pasa)"
                action_prompt = (
                    "Tu respuesta anterior tenía " + str(current_words) +
                    " palabras de narración, PERO el techo máximo es " + str(max_acceptable_words) +
                    " palabras (ideal: " + str(target_words) + "). "
                    "Te pasaste por " + str(current_words - max_acceptable_words) + " palabras.\n\n"
                    "COMPRIME las escenas más largas conservando los hechos esenciales documentados:\n"
                    "- Recorta detalles secundarios, ejemplos redundantes, frases adornadas.\n"
                    "- Mantén nombres, fechas, datos físicos clave, cifras verificables.\n"
                    "- Cada escena debe quedar entre " + str(min_per_scene) + " y " +
                    str(max_per_scene) + " palabras.\n\n"
                    "Escenas que DEBES comprimir:\n" + long_block + "\n\n"
                    "⛔ MÍNIMO ABSOLUTO: NO bajes de " + str(min_acceptable_words) + " palabras totales."
                )

            full_retry_prompt = (
                action_prompt + "\n\n"
                "REGLAS COMUNES:\n"
                "- NO cambies los visual_prompt, sfx_tag ni overlay_tag.\n"
                "- NO cambies el número de escenas — mantén exactamente " + str(len(scenes)) + ".\n"
                "- Mantén el idioma original (" + language + ").\n"
                "- Tras ajustar, CUENTA tus palabras y verifica que el total está entre " +
                str(min_acceptable_words) + " y " + str(max_acceptable_words) + ".\n\n"
                "Devuelve el JSON COMPLETO ajustado, en el mismo formato.\n"
                "Sin explicaciones antes ni después. Solo JSON.\n\n"
                "JSON actual a ajustar:\n" + existing_json_str
            )

            raw_retry = self.gemini_client._generate(
                full_retry_prompt, max_tokens=8000, task_type="script_quality"
            )
            if not raw_retry or str(raw_retry).startswith("ERROR"):
                self.log(f"   ⚠️ Reintento {attempt}: LLM no respondió. Quedando con guion actual.")
                break

            json_data_retry = _reparse_json(raw_retry)
            if not json_data_retry:
                self.log(f"   ⚠️ Reintento {attempt}: JSON inválido. Quedando con guion previo.")
                break

            scenes_retry = json_data_retry.get("scenes") or []
            if len(scenes_retry) != len(scenes):
                self.log(
                    f"   ⚠️ Reintento {attempt}: el LLM cambió el número de escenas "
                    f"({len(scenes)} → {len(scenes_retry)}). Quedando con guion previo."
                )
                break

            new_words = _count_words(scenes_retry)
            arrow = "↑" if new_words > current_words else ("↓" if new_words < current_words else "=")
            self.log(
                f"   📊 Reintento {attempt}: {current_words} {arrow} {new_words} palabras "
                f"(banda objetivo {min_acceptable_words}–{max_acceptable_words})"
            )

            # Aceptar si: (a) está dentro de la banda, o (b) está MÁS CERCA de la banda que antes
            def _band_distance(words):
                if words < min_acceptable_words:
                    return min_acceptable_words - words
                if words > max_acceptable_words:
                    return words - max_acceptable_words
                return 0
            if _band_distance(new_words) < _band_distance(current_words):
                json_data = json_data_retry
                scenes = scenes_retry
                current_words = new_words
            else:
                self.log(f"   ⚠️ Reintento {attempt} no mejoró respecto a la banda. Quedando con guion previo.")
                break

        if current_words < min_acceptable_words:
            self.log(
                f"   ⚠️ Guion final: {current_words} palabras (< mínimo {min_acceptable_words}). "
                f"El video saldrá más corto que el target."
            )
        elif current_words > max_acceptable_words:
            self.log(
                f"   ⚠️ Guion final: {current_words} palabras (> máximo {max_acceptable_words}). "
                f"El video durará más que el target — verificá."
            )
        else:
            self.log(
                f"   ✅ Guion dentro de banda: {current_words} palabras "
                f"(banda {min_acceptable_words}–{max_acceptable_words})"
            )

        # 3.5 Extract metadata from top-level JSON fields
        _meta_cover_text = str(json_data.get("cover_text", "")).strip().upper()
        _meta_hook_pattern = str(json_data.get("hook_pattern", "")).strip().upper()[:1]
        _meta_category = str(json_data.get("category_fit", category)).strip()
        if is_mystery_inquiry(category):
            _meta_category = category
        _meta_long_form = str(json_data.get("long_form_potential", "NO")).strip().upper()
        _meta_long_angle = str(json_data.get("long_form_angle", "")).strip()
        _meta_series = str(json_data.get("series_fit", "NONE")).strip()

        # 4. Process through the manual-JSON pipeline (TTS + word-ratio timing)
        result = self.process_manual_json(
            json_data,
            voice_id=voice_id,
            language=language,
            rate=rate,
            max_duration=180.0,
            topic=topic,
            research_context=research_context,
        )
        if not result:
            self.log("   ⚠️ process_manual_json falló — fallback al flujo clásico")
            return None

        # 5. Enrich result with metadata and channel strategy validation
        result["topic"] = json_data.get("title", topic)
        result["category"] = _meta_category or category
        result["generation_profile"] = "short_structured"
        result["duration_target"] = duration_target

        # Store metadata on the result for downstream use
        result["script_metadata"] = {
            "cover_text": _meta_cover_text,
            "hook_pattern": _meta_hook_pattern if _meta_hook_pattern in "ABCD" else "",
            "category": _meta_category,
            "long_form_potential": _meta_long_form,
            "long_form_angle": _meta_long_angle,
            "series_fit": _meta_series,
        }

        # 5.5 Duration validation via channel_strategy
        try:
            from channel.channel_strategy import validate_duration as _validate_dur
            _measured = self._measure_audio_duration_seconds(str(result.get("audio_path", "")))
            if _measured > 0:
                _ok, _msg = _validate_dur(_measured)
                self.log(f"   {_msg}")
        except ImportError:
            pass

        # 6. Music search (same as legacy path)
        if find_auto_music and JAMENDO_AVAILABLE:
            self.log("🎵 Buscando música de fondo...")
            try:
                cat, sent = analyze_narration(result.get("script", ""))
                if not cat:
                    cat = category
                    sent = -0.5 if self._get_tone_profile_for_category(category) == "mystery" else 0.5
                if cat:
                    tags = map_ai_to_jamendo_tags(cat, sent)
                    tracks = search_jamendo_api(tags, self.jamendo_client_id, limit=1)
                    if tracks:
                        result["music_data"] = tracks[0]
                        self.log(f"   ✅ Música encontrada: '{tracks[0]['title']}'")
            except Exception as e:
                self.log(f"   ⚠️ Error buscando música: {e}")

        # 7. Arranque (video_opening): sin placa quieta por defecto; el texto de gancho va
        # encima de la escena 1 y la voz arranca en 0.0 s. La placa vieja solo si el Bible
        # apaga `hook_overlay` y deja `cover_frame.enabled`.
        try:
            from pipeline.video_opening import apply_opening
            try:
                from channel.channel_strategy import get_active_archetype
                _arche_now = get_active_archetype() or ""
            except Exception:
                _arche_now = ""
            _segs, _opening = apply_opening(
                result.get("segments", []), script=str(result.get("script") or ""),
                topic=topic, category=category, llm_cover_text=_meta_cover_text,
                archetype=_arche_now, opening_style_id=opening_style, log=self.log,
            )
            result["segments"] = _segs
            result["opening"] = _opening
            if _opening.get("style") == "cover_card":
                result["cover_frame"] = {"cover_text": _opening["cover_text"], "duration": _opening["duration"]}
        except Exception as exc:
            self.log(f"   [Arranque] no se pudo preparar ({exc}); sin texto de gancho")

        self.log("✅ STORYBOARD ESTRUCTURADO COMPLETADO (JSON unificado)")
        return result

    def _generate_long_structured(
        self,
        topic: str,
        category: str,
        platform: str,
        duration_target: int,
        voice_id: Optional[str],
        language: str,
        research_context: list,
        find_auto_music: bool,
        style: str,
        rate: str,
        opening_style: str,
    ) -> Optional[Dict]:
        """Generate a long-form storyboard via batched JSON (same prompt quality as manual).

        Flow:
          1. generate_scenes_json_batched() → script via Groq → batch-convert to JSON scenes
          2. process_manual_json() → TTS + timing (no Whisper)
          3. Music search + retention gate

        Falls back to None so caller can retry with legacy path.
        """
        self.log("   🎯 Modo JSON batched para video largo (prompt unificado)")

        # 1. Generate JSON scenes via batched approach
        json_data = self.generate_scenes_json_batched(
            topic=topic,
            category=category,
            duration=duration_target,
            language=language,
            research_context=research_context or None,
            video_format="16:9",
            platform=platform,
            opening_style=opening_style,
        )
        if not json_data or not json_data.get("scenes"):
            self.log("   ⚠️ generate_scenes_json_batched no produjo escenas")
            return None

        scenes = json_data["scenes"]
        self.log(f"   ✅ JSON batched: {len(scenes)} escenas, título: {json_data.get('title', '?')[:60]}")

        # 2. Process through manual-JSON pipeline (TTS + word-ratio timing)
        result = self.process_manual_json(
            json_data,
            voice_id=voice_id,
            language=language,
            rate=rate,
            max_duration=0,  # no limit for long videos
            topic=topic,
            research_context=research_context,
        )
        if not result:
            self.log("   ⚠️ process_manual_json falló — fallback al flujo clásico")
            return None

        # 3. Enrich result
        result["topic"] = json_data.get("title", topic)
        result["category"] = category
        result["generation_profile"] = "long_structured"
        result["duration_target"] = duration_target

        # 4. Retention gate (for long horizontal)
        intro_score = self._estimate_long_intro_quality_score(result.get("segments", []))
        result["retention_intro_score"] = intro_score
        self.log(f"📈 Gate retención (0-60s) estimado: {intro_score}/100")

        # 5. Music search
        if find_auto_music and JAMENDO_AVAILABLE:
            self.log("🎵 Buscando música de fondo...")
            try:
                cat, sent = analyze_narration(result.get("script", ""))
                if not cat:
                    cat = category
                    sent = -0.5 if self._get_tone_profile_for_category(category) == "mystery" else 0.5
                if cat:
                    tags = map_ai_to_jamendo_tags(cat, sent)
                    if "Cinematic" in style:
                        tags.append("cinematic")
                    tracks = search_jamendo_api(tags, self.jamendo_client_id, limit=1)
                    if tracks:
                        result["music_data"] = tracks[0]
                        self.log(f"   ✅ Música encontrada: '{tracks[0]['title']}'")
            except Exception as e:
                self.log(f"   ⚠️ Error buscando música: {e}")

        try:
            from pipeline.video_opening import apply_opening
            try:
                from channel.channel_strategy import get_active_archetype
                _arche_now = get_active_archetype() or ""
            except Exception:
                _arche_now = ""
            _segs, _opening = apply_opening(
                result.get("segments", []), script=str(result.get("script") or ""),
                topic=topic, category=category,
                llm_cover_text=str((result.get("script_metadata") or {}).get("cover_text") or ""),
                archetype=_arche_now, opening_style_id=opening_style, log=self.log,
            )
            result["segments"] = _segs
            result["opening"] = _opening
            if _opening.get("style") == "cover_card":
                result["cover_frame"] = {
                    "cover_text": _opening["cover_text"],
                    "duration": _opening["duration"],
                }
        except Exception as exc:
            self.log(f"   [Arranque] no se pudo preparar ({exc}); sin texto de gancho")

        self.log("✅ STORYBOARD LARGO ESTRUCTURADO COMPLETADO (JSON batched)")
        return result

    def generate_scenes_json_batched(self, topic, category, duration, language='es',
                                     research_context=None, video_format=None, platform=None,
                                     progress_callback=None,
                                     opening_style="hook_overlay_v1"):
        """
        Genera el JSON completo de escenas usando llamadas batch a Groq para evitar
        el límite de tokens de salida (~12 000 tokens).

        Flujo:
          1. Genera el guion narrativo completo (texto plano) con el LLM.
          2. Divide el guion en grupos de ~BATCH_WORDS palabras.
          3. Por cada grupo llama al LLM pidiéndole JSON de escenas para ese fragmento.
          4. Concatena todas las escenas y devuelve el dict completo.

        Returns:
            dict  { "title": ..., "scenes": [...] }  o None si falla.
        """
        import json as _json
        import re as _re

        BATCH_WORDS = 300   # palabras por batch → ~40-50 escenas de ~6-8 palabras c/u
        # Bumped from 6000 → 12000: visual_prompts now follow the 7-element CALIDAD
        # CINEMATOGRAFICA rule and are ~80 words each (vs ~30 before). For ~50 scenes
        # per batch that's ~4000 narration words + ~4000 visual_prompt words → can easily
        # exceed 6000 output tokens, causing JSON truncation and parsing failure.
        MAX_TOKENS_PER_BATCH = 12000

        log = self.log
        self._last_script_error = None
        log("=" * 70)
        log(f"  GENERANDO JSON DE ESCENAS (batch) — {duration}s, {language.upper()}")
        log("=" * 70)

        if not self.gemini_client:
            log("  Error: cliente LLM no disponible.")
            return None

        # --- 1. Generar guion narrativo ---
        log("  Paso 1/3: generando guion narrativo...")
        try:
            duration_int = int(duration)
        except Exception:
            duration_int = 60

        if research_context:
            script = self.gemini_client.generate_video_script_with_research(
                topic, category, duration_int, research_context,
                language=language,
                narrative_profile="long_horizontal" if duration_int >= 600 else None,
                opening_style=opening_style,
            )
        else:
            script = self.gemini_client.generate_video_script(
                topic, category, duration_int,
                language=language,
                narrative_profile="long_horizontal" if duration_int >= 600 else None,
                opening_style=opening_style,
            )

        if not script or (isinstance(script, str) and script.startswith("ERROR")):
            if script == "ERROR_SCRIPT_REFUSAL":
                self._last_script_error = script
                log("  Error: el LLM rechazó el tema (no se convertirá un 'I can't fulfill' en escenas).")
            elif script == "ERROR_SCRIPT_TOO_SHORT":
                self._last_script_error = script
                log("  Error: el guion quedó muy por debajo del presupuesto de palabras.")
            else:
                log(f"  Error generando guion: {str(script)[:120]}")
            return None

        unusable = self._unusable_script_reason(script, duration_int)
        if unusable:
            if "rechazo" in unusable.lower():
                self._last_script_error = "ERROR_SCRIPT_REFUSAL"
            else:
                self._last_script_error = "ERROR_SCRIPT_TOO_SHORT"
            log(f"  {unusable}")
            return None

        words = script.split()
        log(f"  Guion generado: {len(words)} palabras.")

        # Extraer título tentativo (primera oración / primeras 12 palabras)
        first_sentence = script.split('.')[0].strip()
        tentative_title = ' '.join(first_sentence.split()[:12]) if first_sentence else topic

        # --- 2. Dividir en batches ---
        batches = []
        for start in range(0, len(words), BATCH_WORDS):
            chunk = ' '.join(words[start:start + BATCH_WORDS])
            batches.append(chunk)

        log(f"  Paso 2/3: {len(batches)} batches de ~{BATCH_WORDS} palabras cada uno.")

        # --- 3. Convertir cada batch a JSON de escenas ---
        lang_label = "español" if language == 'es' else "English"
        all_scenes = []
        title_from_llm = tentative_title

        # Tone profile drives header, visual guide, and anti-invention rules per batch.
        tone_profile = self._get_tone_profile_for_category(category)
        tone_header = self._build_tone_header(tone_profile)
        visual_guide = self._build_visual_guide_for_profile(tone_profile)
        image_aspect, aspect_lead, aspect_rule = self._visual_prompt_aspect_rule(
            video_format, platform
        )

        for idx, chunk_text in enumerate(batches):
            batch_num = idx + 1
            log(f"  Batch {batch_num}/{len(batches)}...")
            if progress_callback:
                progress_callback(batch_num, len(batches))

            # Cuántas escenas para este chunk.
            # 6 palabras/escena explotaba el JSON (50 escenas × visual_prompt largo
            # → truncado) y dejaba 500+ segmentos inutilizables en el timeline.
            batch_word_count = len(chunk_text.split())
            words_per_scene_target = 6
            if duration_int >= 600:
                words_per_scene_target = 24
            elif duration_int >= 180:
                words_per_scene_target = 12
            scenes_in_batch = max(3, int(batch_word_count / words_per_scene_target))

            # Contexto anterior para continuidad
            prev_context = ""
            if all_scenes:
                last_scene = all_scenes[-1]
                prev_context = (
                    f"\nCONTINUACIÓN: las escenas anteriores terminaron con: "
                    f"\"{last_scene.get('narration', '')[-200:]}\"\n"
                    f"Mantén la continuidad narrativa y visual.\n"
                )

            title_instruction = (
                f"Esta es la primera parte del video — incluye un campo 'title' con el título del video en {lang_label}."
                if idx == 0 else "NO incluyas campo 'title'."
            )
            if idx == 0:
                from pipeline.video_opening import opening_script_instructions
                opening_batch = opening_script_instructions(
                    opening_style, language=language, include_visuals=True
                )
            else:
                opening_batch = (
                    "The selected opening was already completed in the first batch. "
                    "Continue the chronology without restarting or repeating it."
                )
            response_format = (
                'Responde con JSON así: {"title": "...", "scenes": [...]}'
                if idx == 0 else
                "Responde SOLO con un array JSON de escenas: [{...}, ...]"
            )
            words_per_scene = batch_word_count // scenes_in_batch

            batch_prompt = f"""{tone_header}
Tarea: convierte este fragmento de guion en escenas JSON, conservando el contenido del guion (sin omitir ni inventar texto narrativo).

TEMA DEL VIDEO: "{topic}"
CATEGORÍA: {category}
PERFIL DE TONO: {tone_profile}
IDIOMA DE NARRACIÓN: {lang_label}
{prev_context}
{opening_batch}
{mystery_editorial_instructions(category)}

FRAGMENTO DE GUION A CONVERTIR:
{chunk_text}

Genera exactamente {scenes_in_batch} escenas JSON para este fragmento.
{title_instruction}

REGLAS DE CONVERSIÓN:
1. Cada escena cubre una porción del fragmento — NO omitas, NO añadas contenido nuevo, NO inventes hechos. Solo divide el guion en escenas.
2. narration: el texto de narración en {lang_label}, ~{words_per_scene} palabras.
3. visual_prompt: descripción visual cinematográfica EN INGLÉS (ver REGLA VISUAL más abajo). Debe incluir "{image_aspect}" cerca del inicio (ej: "{aspect_lead}, ..."). Finaliza con "no text, no writing, no signs, no captions, no watermarks".
4. sfx_tag: efecto de sonido en inglés o "none".
5. overlay_tag: GIF/sticker en inglés o "none".

REGLA VISUAL HISTÓRICA / TEMPORAL:
- Cada visual_prompt debe incluir explícitamente la época/lugar en inglés (ej: "set in 3rd century BCE Carthage" o "set in Cold War Tehran, 1976").
- No mezcles épocas: ropa, armas, arquitectura y objetos deben corresponder a la época del tema.
- Prohíbe anacronismos visibles: smartphones, autos modernos, plástico, pantallas LED, señalética moderna.
- CONSISTENCIA: los visual_prompt deben ser coherentes entre sí y con los batches anteriores. No cambies estilo visual, indumentaria, raza de personajes ni arquitectura entre escenas sin que la narrativa lo justifique.

REGLA VISUAL — CALIDAD CINEMATOGRAFICA (OBLIGATORIO):
{aspect_rule}
Cada visual_prompt debe incorporar EXPLICITAMENTE estos 7 elementos en inglés:
  1. SUJETO PRINCIPAL + acción (ej: "Hannibal Barca on horseback surveying the battlefield"). El sujeto DEBE SER la acción histórica directa (ej: la batalla en sí), NUNCA muestres a escribas o historiadores "registrando" el evento a menos que sea estrictamente necesario. Queremos ver la acción real. Evita escenas vacías.
  2. AMBIENTE + ÉPOCA (ej: "set in 3rd century BCE, plains of Cannae southern Italy at dawn").
  3. ENCUADRE: "wide establishing shot", "medium shot", "close-up", "low-angle shot", "over-the-shoulder". Varía entre escenas.
  4. ILUMINACION específica: "chiaroscuro side lighting from a single torch", "golden-hour rim light", "moonlit with volumetric god rays", "candlelit interior with deep shadows" — NO solo "dramatic lighting".
  5. PALETA + MOOD: paleta cromática + 1-2 palabras de mood ("muted earth tones, foreboding").
  6. CALIDAD FOTOGRAFICA: "shot on 35mm film", "shallow depth of field", "Roger Deakins cinematography", "documentary photography style", "atmospheric haze with floating dust particles". NO uses "8k" ni "hyperrealistic".
  7. ANTI-ARTEFACTO: incluye "natural anatomy, realistic proportions, coherent hands and faces" en escenas con personas visibles.

{visual_guide}

REGLA ANTI-INVENCION:
- NO añadas elementos visuales que NO estén en el fragmento de guion (no inventes maldiciones, halos sobrenaturales, OVNIs ni símbolos esotéricos si no aparecen en el texto).
- Para perfil "documentary" y "dramatic_factual": NUNCA inyectes elementos paranormales/fantasy/CGI cartoon en los visual_prompt, aunque el texto narrativo sea ambiguo.
- Para perfil "mystery": ambigüedad visual permitida (sombras, niebla, contraluz), pero sin derivar a fantasy art.

CERO TEXTO EN IMÁGENES:
- PROHIBIDO texto visible en visual_prompt. Sin letreros, carteles, inscripciones, subtítulos, logos, UI, números ni letras.
- SIEMPRE termina cada visual_prompt con: "no text, no writing, no signs, no captions, no watermarks"

{response_format}
Sin explicaciones antes ni después. Solo JSON válido."""

            raw = self._call_llm_generate(batch_prompt, max_tokens=MAX_TOKENS_PER_BATCH)
            if not raw:
                log(f"  Batch {batch_num}: LLM no respondió, saltando.")
                # fallback: crear escenas mínimas con el texto
                chunk_words_list = chunk_text.split()
                chunk_per = max(1, len(chunk_words_list) // scenes_in_batch)
                for si in range(scenes_in_batch):
                    narr = ' '.join(chunk_words_list[si*chunk_per:(si+1)*chunk_per])
                    if narr:
                        all_scenes.append({
                            "narration": narr,
                            "visual_prompt": f"cinematic shot related to {topic}, dramatic lighting, no text, no writing, no signs, no captions, no watermarks",
                            "sfx_tag": "none",
                            "overlay_tag": "none",
                        })
                continue

            # Parsear JSON de la respuesta (tolerante a varios defectos comunes del LLM)
            parsed_scenes = None
            parsed_title = None
            clean = raw.strip()

            # Intentar extraer bloque de código markdown
            md = _re.search(r'```(?:json)?\s*([\s\S]*?)```', clean)
            if md:
                clean = md.group(1).strip()

            # Strip trailing commas before `]` or `}` — common LLM mistake that breaks json.loads.
            def _strip_trailing_commas(s: str) -> str:
                return _re.sub(r',\s*(?=[}\]])', '', s)

            # Use raw_decode so a valid JSON object/array followed by trailing garbage
            # (e.g. extra prose, a second object glued on, partial closing bracket) still parses.
            decoder = _json.JSONDecoder()

            def _try_parse_at(text: str, start_pos: int):
                """Return (parsed_value, end_pos) or (None, None) on failure."""
                try:
                    return decoder.raw_decode(text[start_pos:])
                except _json.JSONDecodeError:
                    return None, None

            def _try_parse_with_repairs(text: str, start_pos: int):
                """Try parsing as-is, then with trailing-comma repair."""
                value, _end = _try_parse_at(text, start_pos)
                if value is not None:
                    return value
                # Repair pass: strip trailing commas from the substring starting at start_pos.
                repaired = _strip_trailing_commas(text[start_pos:])
                try:
                    return decoder.raw_decode(repaired)[0]
                except _json.JSONDecodeError:
                    return None

            # Caso: objeto con title + scenes (primer batch)
            if idx == 0:
                for m in _re.finditer(r'\{', clean):
                    obj = _try_parse_with_repairs(clean, m.start())
                    if isinstance(obj, dict) and 'scenes' in obj:
                        parsed_scenes = obj['scenes']
                        parsed_title = obj.get('title', tentative_title)
                        break

            # Caso: array de escenas (o fallback para primer batch)
            if parsed_scenes is None:
                for m in _re.finditer(r'\[', clean):
                    arr = _try_parse_with_repairs(clean, m.start())
                    if isinstance(arr, list) and arr:
                        parsed_scenes = arr
                        break

            # Final salvage: if the JSON is truncated mid-array (max_tokens hit),
            # try to extract as many complete scene objects as possible.
            if parsed_scenes is None:
                salvaged = []
                # Greedy match of balanced {...} objects with a "narration" field
                for obj_match in _re.finditer(r'\{[^{}]*"narration"[^{}]*"visual_prompt"[^{}]*\}', clean, _re.DOTALL):
                    try:
                        candidate = _strip_trailing_commas(obj_match.group(0))
                        scene = _json.loads(candidate)
                        if isinstance(scene, dict) and scene.get('narration'):
                            salvaged.append(scene)
                    except _json.JSONDecodeError:
                        continue
                if salvaged:
                    log(f"  Batch {batch_num}: JSON truncado, rescatadas {len(salvaged)} escenas completas.")
                    parsed_scenes = salvaged

            if parsed_scenes:
                if parsed_title and idx == 0:
                    title_from_llm = parsed_title
                valid = [s for s in parsed_scenes
                         if isinstance(s, dict) and s.get('narration')]
                all_scenes.extend(valid)
                log(f"  Batch {batch_num}: {len(valid)} escenas añadidas (total: {len(all_scenes)}).")
            else:
                log(f"  Batch {batch_num}: no se pudo parsear JSON. Raw: {raw[:200]}")

        if not all_scenes:
            log("  No se generaron escenas válidas.")
            return None

        combined_narration = " ".join(
            str(scene.get("narration") or "") for scene in all_scenes
        )
        unusable_scenes = self._unusable_script_reason(combined_narration, duration_int)
        if unusable_scenes:
            log(f"  {unusable_scenes}")
            return None

        try:
            from pipeline.image_generation_manager import apply_aspect_ratio_to_visual_prompt
            for scene in all_scenes:
                vp = str(scene.get("visual_prompt") or "").strip()
                if vp:
                    scene["visual_prompt"] = apply_aspect_ratio_to_visual_prompt(
                        vp, image_aspect
                    )
        except Exception as exc:
            log(f"  No se pudo inyectar {image_aspect} en visual_prompts: {exc}")

        result = {"title": title_from_llm, "scenes": all_scenes}
        log(f"  JSON completo: {len(all_scenes)} escenas, título: {title_from_llm[:60]}")
        return result

    def process_manual_json(self, json_data, voice_id=None, language='es', rate="+0%",
                            max_duration: float = 0, topic: str = "", research_context=None):
        """
        Procesa el JSON manual: genera UN audio completo y segmenta con Whisper.
        Usa el mismo flujo probado que generate_storyboard_data.
        
        Args:
            json_data: Diccionario con el JSON del guion manual
            voice_id: ID de voz para TTS (opcional)
            language: Idioma ('es' o 'en')
            rate: Velocidad de habla Edge-TTS, ej: '+0%', '+30%'
            max_duration: Duración máxima en segundos (0 = sin límite). Para shorts 9:16, usar 180.
        
        Returns:
            Diccionario con storyboard o None si falla
        """
        self.log("\n" + "="*70)
        self.log(" PROCESANDO JSON MANUAL...")
        self.log("="*70)

        if 'scenes' not in json_data:
            self.log(" Error: El JSON no contiene la clave 'scenes'")
            return None
        
        scenes = json_data['scenes']
        total_scenes = len(scenes)
        self.log(f" JSON contiene {total_scenes} escenas")
        preview_narration = " ".join(
            str(scene.get("narration") or "") for scene in scenes
        )
        unusable_json = self._unusable_script_reason(
            preview_narration,
            getattr(self, "_last_duration_target", 0) or 0,
        )
        if unusable_json and preview_narration.strip():
            # Only hard-fail when duration is known (long-form batched). Manual JSON
            # without a duration still rejects LLM refusals.
            is_refusal, _, _ = _import_script_quality_guards()
            if is_refusal(preview_narration):
                self.log(f" {unusable_json}")
                return None
        
        # 0.5 Hechos verificados ANTES de la voz (script_fact_check). Aca pasan los
        # tres caminos: short automatico, largo por lotes y el JSON pegado a mano.
        # Sin esto salio publicado "el Victory mato a Villeneuve" (Trafalgar, 2026-09-23).
        scenes, fact_report = self._fact_check_scenes(
            scenes, topic or str(json_data.get('title') or ''), language, research_context,
            title=str(json_data.get('title') or ''))
        # El titulo tambien se verifica (Cannae: "86,000 Dead" cuando pelearon 86.000). El JSON es
        # el mismo objeto que usa quien llamo: result["topic"] sale corregido.
        if fact_report and fact_report.get("title") and fact_report["title"] != fact_report.get("title_original"):
            self.log(f"   Titulo corregido: '{fact_report['title_original']}' -> '{fact_report['title']}'")
            json_data['title'] = fact_report["title"]

        # 1. Combinar todas las narraciones en un guión completo
        full_script = ""
        scene_metadata = []
        for i, scene in enumerate(scenes):
            text = scene_narration_text(scene)
            if not text:
                continue
            full_script += text + " "
            scene_metadata.append({
                'index': i,
                'text': text,
                'word_count': len(text.split()),
                'visual_prompt': scene.get('visual_prompt', 'Cinematic mysterious shot, dark atmosphere, 8k quality'),
                'sfx_tag': scene.get('sfx_tag', 'none'),
                'overlay_tag': scene.get('overlay_tag', 'none'),
            })
        
        full_script = full_script.strip()
        total_words = len(full_script.split())
        self.log(f" Guión combinado: {total_words} palabras de {len(scene_metadata)} escenas")
        
        if not full_script:
            self.log(" Error: No se encontró narración en las escenas")
            return None
        
        # 2. Generar UN solo audio TTS (mismo método que flujo normal)
        self.log(f"️ Generando narración completa ({language})...")
        audio_filename = f"manual_{int(time.time())}.mp3"
        audio_path_str = str(VideoConfig.AUDIO_DIR / audio_filename)
        
        audio_path = self.tts.generate_narration(
            full_script, audio_path_str, voice_id, language=language, rate=rate
        )
        
        if not audio_path:
            self.log(" Error al generar audio.")
            return None
        self.log(f"    Audio guardado: {audio_path}")

        # 2.5. Auto-velocidad si hay límite de duración (ej: 180s para Shorts 9:16)
        if max_duration > 0:
            audio_path, speed_factor = self._enforce_max_audio_duration(audio_path, max_duration)
            if speed_factor > 1.0:
                self.log(f"    Narración acelerada ×{speed_factor:.2f} para encajar en {max_duration:.0f}s")

        # 3. Calcular duración total del audio y distribuir tiempos por escena
        #    Para JSON manual intentamos medir cada escena con la voz real.
        #    Si no es seguro o falla, caemos a una distribución por palabras.
        self.log("️ Calculando tiempos por escena...")
        total_duration = self._measure_audio_duration_seconds(str(audio_path))
        if total_duration <= 0:
            total_duration = total_words / 2.5  # ~2.5 palabras/segundo
        
        self.log(f"   ️ Duración total del audio: {total_duration:.1f}s")

        timing_source = 'word_ratio'
        scene_durations = self._estimate_scene_durations_with_selected_tts(
            scene_metadata,
            voice_id=voice_id,
            language=language,
            rate=rate
        )

        if scene_durations and len(scene_durations) == len(scene_metadata):
            raw_scene_total = sum(scene_durations)
            scene_durations = self._normalize_scene_durations(scene_durations, total_duration)
            timing_source = 'tts_scene_estimate'
            if raw_scene_total > 0:
                self.log(
                    f"    Tiempos por escena ajustados: {raw_scene_total:.1f}s medidos "
                    f" {total_duration:.1f}s finales"
                )
        else:
            self.log("   ℹ️ Usando distribución por palabras como fallback de timing.")
            scene_durations = []
            for meta in scene_metadata:
                word_ratio = meta['word_count'] / total_words if total_words > 0 else 1.0 / len(scene_metadata)
                scene_durations.append(total_duration * word_ratio)
            scene_durations = self._normalize_scene_durations(scene_durations, total_duration)

        segments = self._build_segments_from_scene_metadata(
            scene_metadata,
            scene_durations,
            total_duration=total_duration,
            timing_source=timing_source
        )
        
        self.log(f" Storyboard manual listo: {len(segments)} segmentos")
        
        return {
            "topic": json_data.get('title', 'Video Manual'),
            "category": "Manual",
            "script": full_script,
            "audio_path": str(audio_path),
            "segments": segments,
            "music_data": None,
            "voice_id": voice_id,
            "language": language,
            "segment_timing_source": timing_source,
            "generated_at": time.time(),
            "fact_check": fact_report,
        }
    
    def generate_storyboard_data(self, topic: str, category: str, platform: str = 'youtube',
                                 custom_duration: Optional[int] = None,
                                 voice_id: Optional[str] = None,
                                 find_auto_music: bool = True,
                                 style: str = "Estilo Realista / Cinematográfico",
                                 language: str = 'es',
                                 pre_research_snippets: list = None,
                                 rate: str = "+0%",
                                 format_archetype: str = "",
                                 opening_style: str = "hook_overlay_v1"):
        """
        PASO 1: Genera todos los datos de pre-producción (guion, audio, prompts).
        
        Args:
            topic: Tema del video
            category: CategorÃ­a del video
            platform: Plataforma objetivo ('youtube', 'tiktok', etc.)
            custom_duration: DuraciÃ³n personalizada en segundos (opcional)
            voice_id: ID de voz para TTS (opcional)
            find_auto_music: Si buscar mÃºsica automÃ¡ticamente
            style: Estilo visual
            language: Idioma ('es' o 'en')
            pre_research_snippets: Lista de snippets de investigaciÃ³n pre-seleccionados por el usuario (opcional)
        
        Returns:
            Diccionario con storyboard o None si falla
        """
        self.log("\n" + "="*70)
        self.log(f"ðŸŽ¬ INICIANDO PASO 1: GENERACIÃ“N DE STORYBOARD (Idioma: {language.upper()})")
        self.log("="*70)
        # El ANGULO (como se cuenta el tema) entra a todos los prompts via
        # build_hook_prompt_instructions y queda estampado en el storyboard.
        try:
            from channel.channel_strategy import set_active_archetype, archetype_label
            _arche = set_active_archetype(format_archetype)
            if _arche:
                self.log(f"   Angulo narrativo: {archetype_label(_arche)}")
        except Exception:
            _arche = ""
        
        if not self.gemini_client:
            self.log("âŒ Error CrÃ­tico: Cliente Groq no disponible.")
            return None
        
        # --- 1. Determinar DuraciÃ³n y Perfil ---
        profile_info = self._resolve_duration_and_profile(platform, custom_duration)
        duration_target = profile_info["duration_target"]
        generation_profile = profile_info["profile"]
        retention_targets = profile_info["retention_targets"]
        self.log(f"â³ DuraciÃ³n objetivo: {duration_target}s")
        if generation_profile == "long_horizontal":
            self.log(" Perfil activo: long_horizontal (retención para video largo horizontal)")
            if custom_duration and not (1800 <= int(custom_duration) <= 2700):
                self.log("   â„¹ï¸ Recomendación: usar entre 1800s y 2700s para este perfil")
        
        # --- 2. Generar Guion con Gemini (Basado en InvestigaciÃ³n) ---
        self.log(f"ðŸ§  Generando guion ({language})...")
        
        research_context = []

        # Tema llevado al idioma del guion. La investigacion y la validacion
        # usan ESTE; el nombre del proyecto y la GUI siguen con el original.
        research_topic = self._localize_topic_for_research(topic, language)

        # Usar snippets pre-seleccionados por el usuario si existen
        if pre_research_snippets and len(pre_research_snippets) > 0:
            self.log(f"    Usando {len(pre_research_snippets)} fuentes de investigación seleccionadas por el usuario")
            research_context = list(pre_research_snippets)
        
        # Si no hay snippets pre-seleccionados, buscar automáticamente
        # Opción 1: Wikipedia + DuckDuckGo (gratis, sin API key)
        elif RESEARCH_SEARCH_AVAILABLE:
            self.log("    Investigando en Wikipedia + DuckDuckGo...")
            try:
                research_results = search_research_context(
                    research_topic, category=category, language=language, max_results=8
                )
                for result in research_results:
                    title = ""
                    snippet = ""
                    source_url = ""
                    if "Título:" in result:
                        title = result.split("Título:")[1].split("\n")[0].strip()
                    if "Snippet:" in result:
                        snippet = result.split("Snippet:")[1].split("\n")[0].strip()
                    if "URL:" in result:
                        source_url = result.split("URL:")[1].split("\n")[0].strip()

                    if snippet:
                        context_line = snippet
                        if title:
                            context_line = f"{title}. {context_line}"
                        if source_url:
                            context_line = f"{context_line} (Fuente: {source_url})"
                        research_context.append(context_line)
            except Exception as e:
                self.log(f"   ️ Error en búsqueda Wikipedia/DDG: {e}")
        
        # Opcion 2: Google Search si Wikipedia/DDG no aportaron contexto.
        if not research_context and GOOGLE_SEARCH_AVAILABLE:
            self.log("    Sin resultados de Wikipedia/DDG; investigando en Google...")
            try:
                google_results = search_google_trends(f"{topic} {category}", max_results=8)
                for result in google_results[:6]:
                    title = ""
                    snippet = ""
                    source_url = ""
                    if "Título:" in result:
                        title = result.split("Título:")[1].split("\n")[0].strip()
                    if "Snippet:" in result:
                        snippet = result.split("Snippet:")[1].split("\n")[0].strip()
                    if "URL:" in result:
                        source_url = result.split("URL:")[1].split("\n")[0].strip()

                    if snippet:
                        context_line = snippet
                        if title:
                            context_line = f"{title}. {context_line}"
                        if source_url:
                            context_line = f"{context_line} (Fuente: {source_url})"
                        research_context.append(context_line)
            except Exception as e:
                self.log(f"   ️ Error en búsqueda Google: {e}")
            
        # --- 2a. FLUJO JSON ESTRUCTURADO (shorts y largos) ---
        # Genera JSON con escenas + visual_prompt inline.
        # Elimina Whisper y las llamadas separadas de visual prompt.
        # Fallback al flujo clásico si falla.
        if self._is_short_form_platform(platform):
            structured_result = self._generate_short_structured(
                topic=topic,
                category=category,
                platform=platform,
                duration_target=duration_target,
                voice_id=voice_id,
                language=language,
                research_context=research_context,
                find_auto_music=find_auto_music,
                rate=rate,
                opening_style=opening_style,
            )
            if structured_result:
                if _arche:
                    structured_result["format_archetype"] = _arche
                return structured_result
            self.log("   ⚠️ Flujo JSON estructurado (short) falló — usando flujo clásico como fallback")
        else:
            # Long-form: usar flujo batched (script → batches → JSON scenes)
            structured_result = self._generate_long_structured(
                topic=topic,
                category=category,
                platform=platform,
                duration_target=duration_target,
                voice_id=voice_id,
                language=language,
                research_context=research_context,
                find_auto_music=find_auto_music,
                style=style,
                rate=rate,
                opening_style=opening_style,
            )
            if structured_result:
                if _arche:
                    structured_result["format_archetype"] = _arche
                return structured_result
            script_error = getattr(self, "_last_script_error", None)
            if script_error in {"ERROR_SCRIPT_REFUSAL", "ERROR_SCRIPT_TOO_SHORT"}:
                if script_error == "ERROR_SCRIPT_REFUSAL":
                    error_msg = (
                        "El modelo rechazó el tema en vez de escribir el guion. "
                        "No se abrió el timeline con escenas basura. "
                        "Pulsa Generar Storyboard de nuevo; si se repite, usa un título más claro "
                        "(ej. 'Amorite Wall / Muriq-Tidnim, Shu-Sin, Ur III, ~2038 BC')."
                    )
                else:
                    error_msg = (
                        "El guion quedó demasiado corto para la duración pedida. "
                        "No se abrirá el timeline con 3 escenas de relleno. Regenera el storyboard."
                    )
                self.log(f"âŒ {error_msg}")
                raise Exception(error_msg)
            self.log("   ⚠️ Flujo JSON batched (largo) falló — usando flujo clásico como fallback")

        # --- 2b. Flujo clásico (fallback): texto plano → TTS → Whisper → visual prompts ---
        if research_context:
            script = self.gemini_client.generate_video_script_with_research(
                topic,
                category,
                duration_target,
                research_context,
                language=language,
                narrative_profile=generation_profile,
                opening_style=opening_style,
            )
        else:
            script = self.gemini_client.generate_video_script(
                topic,
                category,
                duration_target,
                language=language,
                narrative_profile=generation_profile,
                opening_style=opening_style,
            )

        if not script or script.startswith("ERROR"):
            if script == "ERROR_QUOTA_EXCEEDED":
                error_msg = "Error generando guion: Groq no disponible o sin respuesta vÃ¡lida"
                self.log(f"âŒ {error_msg}")
                self.log("   ðŸ’¡ Verifica GROQ_API_KEY o intenta nuevamente en unos minutos")
                self.log("   ðŸ’¡ Las cuotas se repondrÃ¡n automÃ¡ticamente. Intenta mÃ¡s tarde.")
                raise Exception(error_msg)
            elif script == "ERROR_SCRIPT_REFUSAL":
                error_msg = (
                    "El modelo rechazó el tema en vez de escribir el guion. "
                    "Prueba de nuevo; si se repite, usa un título más claro "
                    "(ej. 'Amorite Wall / Muriq-Tidnim, Shu-Sin, Ur III')."
                )
                self.log(f"âŒ {error_msg}")
                raise Exception(error_msg)
            elif script == "ERROR_SCRIPT_TOO_SHORT":
                error_msg = (
                    "El guion quedó demasiado corto para la duración pedida. "
                    "No se abrirá el timeline con escenas de relleno. Regenera el storyboard."
                )
                self.log(f"âŒ {error_msg}")
                raise Exception(error_msg)
            elif script:
                self.log(f"âŒ Error de Groq: {script}")
            else:
                self.log("âŒ Error de Groq: No se pudo generar el guion")
            return None
        unusable = self._unusable_script_reason(script, duration_target)
        if unusable:
            self.log(f"âŒ {unusable}")
            raise Exception(unusable)
        self.log(f"   ðŸ“œ Guion generado ({len(script.split())} palabras)")

        # --- 2.5. Revisión IA + limpieza final del guion ---
        self.log("ðŸ§ª Revisando guion con IA para corregir artefactos y ortografía...")
        reviewed_script = self._review_script_with_ai(
            script,
            topic=topic,
            category=category,
            language=language,
            duration_target=duration_target
        )
        if reviewed_script and reviewed_script != script:
            self.log(
                f"   âœ… Guion corregido automÃ¡ticamente ({len(script.split())} â†’ {len(reviewed_script.split())} palabras)"
            )
            script = reviewed_script
        else:
            script = self._sanitize_script_text(script, language=language)
            self.log("   â„¹ï¸ Revisión IA no aplicó cambios relevantes; se usa limpieza local.")

        # --- 2.6. Hechos verificados antes de la voz (script_fact_check) ---
        # Guion en texto plano: cada frase es una "escena" para verificar y reparar.
        _frases = [f for f in re.split(r'(?<=[.!?])\s+', script) if f.strip()]
        _frases, fact_report_classic = self._fact_check_scenes(_frases, topic, language, research_context)
        if fact_report_classic and fact_report_classic.get("corrections"):
            script = " ".join(str(f) for f in _frases if str(f).strip())

        # --- 3. Generar Audio (Voz) ---
        self.log(f"ðŸŽ™ï¸ Generando narraciÃ³n ({language})...")
        # Abortar si el guion sigue siendo críticamente corto tras la revisión.
        # Mínimo: 40% de las palabras objetivo (150 palabras/min).
        _min_words_required = max(40, int((duration_target / 60) * 150 * 0.4))
        if len(script.split()) < _min_words_required:
            self.log(
                f"   ❌ Guion insuficiente ({len(script.split())} palabras) para el objetivo "
                f"de {duration_target}s (mínimo ~{_min_words_required} palabras). "
                f"El modelo no generó contenido suficiente. Intenta de nuevo."
            )
            return None

        audio_filename = f"auto_{int(time.time())}.mp3"
        audio_path_str = str(VideoConfig.AUDIO_DIR / audio_filename)

        # Pasamos el idioma al generador de voz
        audio_path = self.tts.generate_narration(
            script, 
            audio_path_str, 
            voice_id, 
            language=language,
            rate=rate
        )
        
        if not audio_path:
            self.log("âŒ Error al generar audio.")
            return None
        self.log(f"   ðŸŽµ Audio guardado: {audio_path}")

        # --- 3.5. Auto-velocidad para Shorts (9:16) ---
        if self._is_short_form_platform(platform):
            max_short_seconds = 180.0
            audio_path, speed_factor = self._enforce_max_audio_duration(audio_path, max_short_seconds)
            if speed_factor > 1.0:
                self.log(f"    Narración acelerada ×{speed_factor:.2f} para formato vertical corto")

        # --- 3.6. Validación de duración con channel strategy ---
        if self._is_short_form_platform(platform):
            try:
                from channel.channel_strategy import validate_duration as _validate_dur
                _measured = self._measure_audio_duration_seconds(str(audio_path))
                if _measured > 0:
                    _ok, _msg = _validate_dur(_measured)
                    self.log(f"   {_msg}")
                    # Abortar si el audio es críticamente corto (< 35% del objetivo)
                    if "WARNING" in _msg and _measured < duration_target * 0.35:
                        self.log(
                            f"   ❌ Audio demasiado corto ({_measured:.1f}s vs objetivo {duration_target}s). "
                            f"El fallback clásico no generó suficiente contenido. Intenta de nuevo."
                        )
                        return None
            except ImportError:
                pass

        # --- 4. Generar Segmentos (Whisper) ---
        self.log(f"ðŸŽ¤ Transcribiendo para obtener tiempos...")
        # Pasamos el idioma a Whisper para mejorar la precisiÃ³n
        segments = self.subtitle_gen.transcribe_audio(audio_path, language=language)
        
        if not segments:
            self.log("âŒ Error al transcribir audio.")
            return None
        self.log(f"   â±ï¸ {len(segments)} segmentos identificados.")
        
        # --- 4.5. Corregir Errores Comunes de TranscripciÃ³n ---
        self.log(f"ðŸ”§ Corrigiendo errores comunes de transcripciÃ³n...")
        try:
            from ai.text_correction_engine import TextCorrectionEngine
            corrector = TextCorrectionEngine()
            segments = corrector.correct_segments(segments)
        except ImportError:
            self.log("âš ï¸ Motor de correcciÃ³n no disponible, continuando sin correcciones...")
        except Exception as e:
            self.log(f"âš ï¸ Error en correcciÃ³n automÃ¡tica: {e}")

        # --- 4.7. Sincronizar texto final de segmentos con el guion revisado ---
        segments = self._sync_segment_texts_with_script(segments, script)
        self.log("   âœ… Texto de segmentos sincronizado con el guion final")

        # --- 4.6. Gate de Retención para largos horizontales (con reintento estricto) ---
        if generation_profile == "long_horizontal":
            intro_score = self._estimate_long_intro_quality_score(segments)
            self.log(f" Gate retención (0-60s) estimado: {intro_score}/100")

            if intro_score < 55:
                self.log("️ Intro débil detectada para largo horizontal. Reintentando guion en modo estricto...")
                retry_script = None
                if research_context:
                    retry_script = self.gemini_client.generate_video_script_with_research(
                        topic,
                        category,
                        duration_target,
                        research_context,
                        language=language,
                        narrative_profile="long_horizontal_strict",
                        opening_style=opening_style,
                    )
                else:
                    retry_script = self.gemini_client.generate_video_script(
                        topic,
                        category,
                        duration_target,
                        language=language,
                        narrative_profile="long_horizontal_strict",
                        opening_style=opening_style,
                    )

                if retry_script and not str(retry_script).startswith("ERROR"):
                    retry_script = self._review_script_with_ai(
                        retry_script,
                        topic=topic,
                        category=category,
                        language=language,
                        duration_target=duration_target
                    )
                    # El guion del reintento es nuevo: tambien pasa por la verificacion de hechos.
                    _frases_retry = [f for f in re.split(r'(?<=[.!?])\s+', retry_script) if f.strip()]
                    _frases_retry, _retry_report = self._fact_check_scenes(
                        _frases_retry, topic, language, research_context)
                    retry_script = " ".join(str(f) for f in _frases_retry if str(f).strip()) or retry_script
                    retry_audio_filename = f"auto_retry_{int(time.time())}.mp3"
                    retry_audio_path_str = str(VideoConfig.AUDIO_DIR / retry_audio_filename)
                    retry_audio_path = self.tts.generate_narration(
                        retry_script,
                        retry_audio_path_str,
                        voice_id,
                        language=language,
                        rate=rate
                    )
                    if retry_audio_path:
                        retry_segments = self.subtitle_gen.transcribe_audio(retry_audio_path, language=language)
                        if retry_segments:
                            try:
                                from ai.text_correction_engine import TextCorrectionEngine
                                corrector = TextCorrectionEngine()
                                retry_segments = corrector.correct_segments(retry_segments)
                            except Exception:
                                pass

                            retry_segments = self._sync_segment_texts_with_script(
                                retry_segments,
                                retry_script
                            )

                            retry_score = self._estimate_long_intro_quality_score(retry_segments)
                            self.log(f" Gate retención (reintento): {retry_score}/100")
                            if retry_score >= intro_score:
                                script = retry_script
                                fact_report_classic = _retry_report
                                audio_path = retry_audio_path
                                segments = retry_segments
                                intro_score = retry_score
                                self.log(" Reintento aplicado: mejoró o igualó la calidad de intro")
                            else:
                                self.log("ℹ️ Reintento descartado: no mejoró la calidad de intro")
                        else:
                            self.log("️ Reintento: no se pudieron transcribir segmentos")
                    else:
                        self.log("️ Reintento: no se pudo generar audio")

        # --- 5. Generar Prompts Visuales ---
        self.log(f"ðŸ§  Generando prompts visuales, SFX y Overlays...")
        segments_with_prompts = []
        visual_context = None
        extract_visual_context = getattr(self.gemini_client, "_extract_historical_context", None)
        if callable(extract_visual_context):
            try:
                visual_context = extract_visual_context(topic, script, research_context)
                if visual_context:
                    period = visual_context.get("time_period") or "period detected"
                    culture = visual_context.get("cultural_context") or visual_context.get("location") or ""
                    detail = f"{period} ({culture})" if culture else str(period)
                    self.log(f"   Contexto visual temporal detectado: {detail}")
            except Exception as e:
                self.log(f"   No se pudo precalcular contexto visual temporal: {e}")
        prompt_stride = self._resolve_prompt_stride(generation_profile, duration_target, len(segments))
        prompt_requests = 0
        if prompt_stride > 1:
            estimated_requests = (len(segments) + prompt_stride - 1) // prompt_stride
            self.log(
                f"   ️ Modo eficiente para largo horizontal: "
                f"{len(segments)} segmentos, 1 prompt cada {prompt_stride} segmentos "
                f"(~{estimated_requests} llamadas IA)"
            )

        for i in range(0, len(segments), prompt_stride):
            segment_group = segments[i:i + prompt_stride]
            start_idx = i + 1
            end_idx = i + len(segment_group)
            if start_idx == end_idx:
                self.log(f"   ... Segmento {start_idx}/{len(segments)}")
            else:
                self.log(f"   ... Segmentos {start_idx}-{end_idx}/{len(segments)}")

            # Para largos, agrupamos texto de varios segmentos para un único prompt visual.
            grouped_text = " ".join(
                str(seg.get('text', '')).strip() for seg in segment_group if seg.get('text')
            ).strip()
            base_text = grouped_text or str(segment_group[0].get('text', '')).strip()
            narrative_context = self._build_narrative_context(
                segments,
                i,
                i + len(segment_group) - 1
            )

            # Los prompts visuales se piden siempre en inglÃ©s internamente en gemini_ai_client.
            prompt_data = self.gemini_client.generate_prompts_for_segment(
                base_text, category, style,
                topic=topic,  # Tema completo del video
                full_script=script,  # Guion completo para contexto
                research_context=research_context,  # Contexto de investigaciÃ³n
                narrative_context=narrative_context,
                is_long_horizontal=(generation_profile == "long_horizontal"),
            )
            prompt_requests += 1
            if not isinstance(prompt_data, dict):
                prompt_data = {}

            for offset, segment in enumerate(segment_group):
                segment.update(prompt_data)
                segment['assigned_filename'] = f"segment_{i + offset + 1:03d}"
                segments_with_prompts.append(segment)

        if prompt_stride > 1:
            self.log(f"    Prompts IA generados: {prompt_requests} (antes: {len(segments)})")
            
        # --- 6. Encontrar MÃºsica de Fondo (Jamendo) ---
        music_data = None
        if find_auto_music and JAMENDO_AVAILABLE:
            self.log("ðŸŽµ Buscando mÃºsica de fondo...")
            try:
                # 1. Intentar anÃ¡lisis de sentimiento profundo (Requiere Google Cloud)
                cat, sent = analyze_narration(script)
                
                # 2. Fallback Inteligente: Si Google Cloud falla o no estÃ¡ config, usar la categorÃ­a del usuario
                if not cat:
                    self.log("   â„¹ï¸ AnÃ¡lisis de sentimiento no disponible (Google Cloud). Usando categorÃ­a base.")
                    # Mapear categorÃ­a de la GUI a algo que entienda el recomendador
                    cat = category  # Ej: "Historia", "Misterios"
                    sent = -0.5 if self._get_tone_profile_for_category(category) == "mystery" else 0.5
                
                # 3. Buscar en Jamendo
                if cat:
                    tags = map_ai_to_jamendo_tags(cat, sent)
                    # AÃ±adir tags extra segÃºn el estilo visual para afinar
                    if "Cinematic" in style: 
                        tags.append("cinematic")
                    
                    self.log(f"   ðŸ” Tags de bÃºsqueda: {', '.join(tags)}")
                    tracks = search_jamendo_api(tags, self.jamendo_client_id, limit=1)
                    
                    if tracks:
                        music_data = tracks[0]
                        self.log(f"   âœ… MÃºsica encontrada: '{music_data['title']}'")
                    else:
                        self.log("   âš ï¸ No se encontraron pistas en Jamendo.")
            except Exception as e:
                self.log(f"   âš ï¸ Error en mÃ³dulo de mÃºsica: {e}")

        # --- Arranque (video_opening): sin placa, texto de gancho en la escena 1 ---
        cover_frame_data = None
        opening_data = None
        try:
            from pipeline.video_opening import apply_opening
            llm_cover_text = getattr(self.gemini_client, '_last_cover_text', None) if hasattr(self, 'gemini_client') else None
            if not llm_cover_text and hasattr(self, 'gemini_client') and hasattr(self.gemini_client, 'backend'):
                llm_cover_text = getattr(self.gemini_client.backend, '_last_cover_text', None)
            try:
                from channel.channel_strategy import get_active_archetype
                _arche_now = get_active_archetype() or ""
            except Exception:
                _arche_now = ""
            segments_with_prompts, opening_data = apply_opening(
                segments_with_prompts, script=str(script or ""), topic=topic, category=category,
                llm_cover_text=llm_cover_text or "", archetype=_arche_now,
                opening_style_id=opening_style, log=self.log,
            )
            if opening_data.get("style") == "cover_card":
                cover_frame_data = {"cover_text": opening_data["cover_text"], "duration": opening_data["duration"]}
        except Exception as exc:
            self.log(f"   [Arranque] no se pudo preparar ({exc}); sin texto de gancho")

        self.log("âœ… PASO 1: STORYBOARD COMPLETADO")
        self.log("â„¹ï¸ NOTA: Las imÃ¡genes NO se generan en este paso.")
        self.log("   Para generar imÃ¡genes, usa el Paso 1.5 (Generar ImÃ¡genes) despuÃ©s de este.")
        return {
            "topic": topic,
            "category": category,
            "script": script,
            "audio_path": audio_path,
            "segments": segments_with_prompts,
            "music_data": music_data,
            "voice_id": voice_id,  # Guardar voice_id para uso en ensamblaje
            "voice_rate": rate,  # Guardar rate para uso en ensamblaje/teaser
            "generation_profile": generation_profile,
            "duration_target": duration_target,
            "retention_targets": retention_targets,
            "retention_intro_score": intro_score if generation_profile == "long_horizontal" else None,
            "language": language,
            "visual_context": visual_context,
            "cover_frame": cover_frame_data,
            "opening": opening_data,
            "script_metadata": self._extract_llm_script_metadata(),
            "fact_check": fact_report_classic,
        }
    
    def generate_short_teaser_from_long_video(self, long_video_storyboard, language='es', voice_id=None,
                                               disable_wikimedia=False, existing_teaser_storyboard=None,
                                               rate="+0%", mode="standalone"):
        """
        Genera un Short teaser (30-60 segundos) en formato vertical 9:16 a partir de un video largo.
        El teaser incluye un hook, resumen del contenido y CTA al final.

        Args:
            long_video_storyboard: Storyboard del video largo completo
            language: Idioma del teaser
            voice_id: ID de voz para TTS (opcional)
            disable_wikimedia: (OBSOLETO) ParÃ¡metro mantenido por compatibilidad - Openverse (Gratis) y Wikimedia eliminados
            existing_teaser_storyboard: Storyboard del teaser previo (para reutilizar audio/segmentos/imÃ¡genes)

        Returns:
            dict con 'video_path', 'script', 'topic', 'category' del short teaser, o None si falla
        """
        self.log("\n" + "="*70)
        self.log("ðŸŽ¬ GENERANDO SHORT TEASER (Formato Vertical 9:16)")
        self.log("="*70)

        topic = long_video_storyboard.get('topic', 'Video')
        category = long_video_storyboard.get('category', 'General')
        full_script = long_video_storyboard.get('script', '')

        # REUTILIZACIÃ“N: Si existe un teaser previo con audio y segmentos vÃ¡lidos, reutilizarlos
        if existing_teaser_storyboard:
            existing_audio = existing_teaser_storyboard.get('audio_path')
            existing_segments = existing_teaser_storyboard.get('segments', [])
            existing_script = existing_teaser_storyboard.get('script', '')

            # Verificar que el audio existe y los segmentos tienen imÃ¡genes
            if existing_audio and os.path.exists(existing_audio) and existing_segments:
                segments_with_images = [s for s in existing_segments if s.get('image_path') and os.path.exists(s.get('image_path', ''))]

                if len(segments_with_images) == len(existing_segments):
                    self.log("â™»ï¸ REUTILIZANDO TEASER PREVIO (audio, segmentos e imÃ¡genes)")
                    self.log(f"   ðŸ“œ Guion: {len(existing_script.split())} palabras")
                    self.log(f"   ðŸŽµ Audio: {existing_audio}")
                    self.log(f"   ðŸ–¼ï¸ {len(segments_with_images)} imÃ¡genes reutilizadas")

                    # Ir directamente al ensamblaje con el storyboard existente
                    return self._assemble_existing_teaser(
                        existing_teaser_storyboard,
                        long_video_storyboard,
                        disable_wikimedia
                    )
                else:
                    self.log(f"   âš ï¸ Solo {len(segments_with_images)}/{len(existing_segments)} imÃ¡genes disponibles, regenerando...")

        if not self.gemini_client:
            self.log("âŒ Error: Cliente Groq no disponible para generar teaser.")
            return None

        # 1. Generar guion corto del teaser (EXTREMADAMENTE LLAMATIVO tipo trailer)
        self.log("ðŸ§  Generando guion del teaser (TRAILER CINEMATOGRÃFICO EXTREMO)...")
        lang_instr = "WRITE IN ENGLISH." if language == 'en' else "ESCRIBE EN ESPAÃ‘OL."
        
        # Obtener mÃ¡s contexto del script completo
        script_context = full_script[:1000] if len(full_script) > 1000 else full_script

        # MODO STANDALONE (2026-09-21): un Short que vale por si solo. El teaser con
        # CTA "mira el video completo" apunta a un 16:9 que en YouTube no tiene
        # feed (Thera: 52K plays en Facebook, 49 vistas en YouTube). En YouTube lo
        # que retiene es la historia entera con cifra al abrir, no un trailer.
        if mode == "standalone":
            # Primero el angulo del 16:9 (el bloque NARRATIVE ANGLE sale de ahi), despues las reglas.
            _arche = long_video_storyboard.get('format_archetype') or ''
            try:
                from channel.channel_strategy import set_active_archetype as _saa
                if _arche:
                    _saa(_arche)
            except Exception:
                pass
            try:
                from channel.channel_strategy import build_hook_prompt_instructions as _bhpi, get_shorts_rules as _gsr
                _rules = _bhpi()
                _sr = _gsr()
            except Exception:
                _rules, _sr = "", {}
            _min = int(_sr.get('min_duration', 60) or 60)
            _max = int(_sr.get('max_duration', 95) or 95)
            _full_ctx = full_script[:2500]
            standalone_prompt = f"""You write a SELF-CONTAINED vertical Short ({_min}-{_max} seconds, ~150-230 words) for a
documented-history channel, derived from the full script below. It is NOT a trailer: no "watch the full video",
no "subscribe", no cliffhanger that only the long video resolves. Tell the strongest single thread of the story,
complete, with its documented numbers, names and consequence.

{_rules}

Topic: {topic}
Full script (source of facts -- do not add facts that are not here):
{_full_ctx}

RULES:
- Language: {'English' if language == 'en' else 'Spanish'} only.
- First spoken sentence: a concrete number/scale or a HOW/WHY question. The date comes later.
- Second and third concrete facts before second 20. Close on the documented consequence.
- Plain narration only: no brackets, no stage directions, no headings, no emojis.

NOW WRITE THE SHORT:
"""
        else:
            standalone_prompt = None

        teaser_prompt = f"""
        Role: EXPERT TRAILER SCRIPTWRITER for YouTube Shorts.
        Task: Create an EXTREMELY COMPELLING and CINEMATIC TRAILER script (45-60 seconds) for a longer video about "{topic}".
        
        Context from full video script:
        {script_context}
        
        CRITICAL REQUIREMENTS FOR MAXIMUM IMPACT:
        
        1. HOOK (First 3-5 seconds) - MUST BE EXTREMELY GRABBING:
           - Start with a SHOCKING question, bold statement, or intriguing mystery
           - Use dramatic pauses and emphasis
           - Examples: "Â¿SabÃ­as que...?", "Esto cambiarÃ¡ todo lo que creÃ­as sobre...", "La verdad oculta que nadie te ha contado..."
           - MUST create immediate curiosity and stop-scrolling effect
        
        2. TRAILER NARRATIVE (20-40 seconds) - CINEMATIC BUILD-UP:
           - Create SUSPENSE and INTRIGUE, not just a summary
           - Use rhetorical questions: "Â¿QuÃ© pasarÃ­a si...?", "Â¿Y si te dijera que...?"
           - Build emotional tension: "Descubre los secretos que...", "La revelaciÃ³n que cambiarÃ¡ tu perspectiva..."
           - Highlight the MOST SHOCKING or INTERESTING points from the full video
           - Use dramatic language: "revelaciÃ³n", "secreto oculto", "verdad impactante", "descubrimiento asombroso"
           - Create a sense of URGENCY and EXCLUSIVITY: "Solo en el video completo...", "Lo que nadie mÃ¡s te dirÃ¡..."
        
        3. STRONG CALL-TO-ACTION (Last 8-12 seconds) - DIRECT INVITATION:
           - Be VERY DIRECT and CLEAR about watching the full video
           - Use imperative language: "Mira el video completo", "No te pierdas el video completo"
           - Create FOMO: "Descubre toda la verdad en el video completo", "La historia completa te espera en el video principal"
           - Include subscription invitation: "SuscrÃ­bete a {get_channel_name()} para mÃ¡s contenido fascinante"
           - End with urgency: "Haz clic en el enlace de arriba ahora", "El video completo estÃ¡ en el enlace de arriba"
        
        STYLE REQUIREMENTS:
        - Language: {lang_instr}
        - CRITICAL: ALL narration text MUST be in {'English' if language == 'en' else 'Spanish'}
        - Do NOT mix languages. Use ONLY {'English' if language == 'en' else 'Spanish'} throughout the entire script.
        - This applies to ALL parts: hook, build-up, and call-to-action.
        - Total length: ~100-180 words (for 45-60 seconds of narration)
        - Tone: DRAMATIC, CINEMATIC, MYSTERIOUS, COMPELLING
        - Pace: Fast-paced but clear, with strategic pauses for emphasis
        - Format: ONLY the narration text, NO intro/outro notes, NO brackets, NO stage directions
        
        EXAMPLE STRUCTURE (Spanish):
        [Hook impactante] "Â¿SabÃ­as que existe un secreto oculto sobre {topic} que cambiarÃ¡ todo lo que creÃ­as?"
        [Build-up] "En este video descubrirÃ¡s revelaciones asombrosas que nadie mÃ¡s te ha contado. La verdad detrÃ¡s de {topic} es mÃ¡s impactante de lo que imaginas. Â¿QuÃ© pasarÃ­a si te dijera que...?"
        [CTA directo] "Mira el video completo en el enlace de arriba para descubrir toda la verdad. SuscrÃ­bete a {get_channel_name()} para mÃ¡s contenido fascinante. No te pierdas esta revelaciÃ³n impactante."
        
        NOW CREATE THE TRAILER SCRIPT:
        """
        
        teaser_script = self.gemini_client._generate(standalone_prompt or teaser_prompt)
        
        # Verificar si la generaciÃ³n fue exitosa
        if not teaser_script:
            self.log("âŒ Error generando guion del teaser: Groq no devolviÃ³ contenido")
            self.log("   ðŸ’¡ Verifica que GROQ_API_KEY estÃ© configurada y que Groq responda correctamente")
            return None
        
        # Detectar error especÃ­fico de cuotas agotadas
        if isinstance(teaser_script, str) and teaser_script == "ERROR_QUOTA_EXCEEDED":
            error_msg = "Error generando guion del teaser: Groq no disponible o sin respuesta vÃ¡lida"
            self.log(f"âŒ {error_msg}")
            self.log("   ðŸ’¡ Verifica GROQ_API_KEY o intenta nuevamente en unos minutos")
            self.log("   ðŸ’¡ Las cuotas se repondrÃ¡n automÃ¡ticamente. Intenta mÃ¡s tarde.")
            raise Exception(error_msg)
        
        if isinstance(teaser_script, str) and teaser_script.startswith("ERROR"):
            self.log(f"âŒ Error generando guion del teaser: {teaser_script}")
            return None
        
        self.log(f"   ðŸ“œ Guion teaser generado ({len(teaser_script.split())} palabras)")
        
        # 2. Generar audio del teaser
        self.log("ðŸŽ™ï¸ Generando narraciÃ³n del teaser...")
        teaser_audio_filename = f"teaser_{int(time.time())}.mp3"
        teaser_audio_path_str = str(VideoConfig.AUDIO_DIR / teaser_audio_filename)
        
        teaser_audio_path = self.tts.generate_narration(
            teaser_script,
            teaser_audio_path_str,
            voice_id,
            language=language,
            rate=rate
        )
        
        if not teaser_audio_path:
            self.log("âŒ Error al generar audio del teaser.")
            return None
        self.log(f"   ðŸŽµ Audio teaser guardado: {teaser_audio_path}")
        
        # 3. Transcribir para obtener segmentos
        self.log("ðŸŽ¤ Transcribiendo audio del teaser...")
        teaser_segments = self.subtitle_gen.transcribe_audio(teaser_audio_path, language=language)
        
        if not teaser_segments:
            self.log("âŒ Error al transcribir audio del teaser.")
            return None
        self.log(f"   â±ï¸ {len(teaser_segments)} segmentos identificados en el teaser")
        
        # 4. Crear segmentos visuales del teaser basados en los segmentos de audio del teaser
        # IMPORTANTE: El teaser generarÃ¡ sus propias imÃ¡genes en formato 9:16 (576x1024)
        # Usaremos los prompts visuales del video largo como referencia, pero generaremos imÃ¡genes nuevas
        long_segments = long_video_storyboard.get('segments', [])
        teaser_visual_segments = []

        self.log(f"   ðŸ–¼ï¸ Se generarÃ¡n nuevas imÃ¡genes en formato vertical 9:16 para el teaser")

        # Mapear cada segmento de audio del teaser a un prompt visual del video largo
        for i, teaser_audio_seg in enumerate(teaser_segments):
            # Buscar el segmento visual del video largo mÃ¡s apropiado para obtener el prompt
            # Usar el Ã­ndice correspondiente o el primero si no hay suficientes
            long_seg_idx = min(i, len(long_segments) - 1) if long_segments else 0
            long_seg = long_segments[long_seg_idx] if long_segments else {}

            # Crear segmento visual para el teaser
            # NO reutilizar imÃ¡genes del video largo - se generarÃ¡n nuevas en formato 9:16
            teaser_visual_seg = {
                'start': teaser_audio_seg['start'],
                'end': teaser_audio_seg['end'],
                'text': teaser_audio_seg['text'],
                'visual_prompt': long_seg.get('visual_prompt', 'dramatic scene, cinematic lighting'),
                'sfx_tag': long_seg.get('sfx_tag', 'none'),
                'overlay_tag': long_seg.get('overlay_tag', 'none'),
                'assigned_filename': f"teaser_seg_{i+1:03d}",
                'image_path': None,  # Se generarÃ¡ nueva imagen en formato 9:16
                'image_source': None  # Se determinarÃ¡ al generar
            }

            teaser_visual_segments.append(teaser_visual_seg)
        
        # 5. Generar prompts visuales EXTREMADAMENTE LLAMATIVOS para el teaser
        self.log("ðŸ§  Generando prompts visuales CINEMATOGRÃFICOS para el teaser...")
        style = "Estilo Realista / CinematogrÃ¡fico"  # Usar estilo por defecto
        
        for i, seg in enumerate(teaser_visual_segments):
            # Mejorar prompts visuales para que sean mÃ¡s llamativos y tipo trailer
            existing_prompt = seg.get('visual_prompt', '')
            
            if not existing_prompt or len(existing_prompt) < 50:
                # Generar nuevo prompt mejorado con contexto global
                # Obtener el guion completo del video largo si estÃ¡ disponible
                full_script = long_video_storyboard.get('script', '') if long_video_storyboard else None
                narrative_context = self._build_narrative_context(teaser_visual_segments, i, i)
                prompt_data = self.gemini_client.generate_prompts_for_segment(
                    seg.get('text', ''), category, style,
                    topic=topic,  # Tema completo del video
                    full_script=full_script,  # Guion completo para contexto
                    research_context=None,  # No hay investigaciÃ³n para teaser
                    narrative_context=narrative_context,
                    is_long_horizontal=False,  # teaser es 9:16 vertical
                )
                seg.update(prompt_data)
            
            # Mejorar el prompt existente para hacerlo mÃ¡s cinematogrÃ¡fico y llamativo
            current_prompt = seg.get('visual_prompt', '')
            if current_prompt:
                # AÃ±adir elementos cinematogrÃ¡ficos tipo trailer
                enhanced_prompt = f"{current_prompt}, dramatic cinematic lighting, intense atmosphere, movie trailer style, high contrast, epic composition, professional film photography, captivating visual, attention-grabbing, stunning visuals"
                seg['visual_prompt'] = enhanced_prompt
        
        # 6. Ensamblar el short teaser (formato vertical 9:16)
        self.log("ðŸŽ¬ Ensamblando short teaser (formato vertical 9:16)...")

        # Asegurar que los subtÃ­tulos dinÃ¡micos estÃ©n activos para el teaser
        # (estilo capcut para shorts)
        # Nota: Esto requiere acceso a la instancia principal, se manejarÃ¡ en la clase principal

        # Buscar mÃºsica de fondo ya descargada del video largo
        # IMPORTANTE: Usar SOLO temp_bgm.mp3 (mÃºsica pura), NO mix.mp3 (que contiene narraciÃ³n + mÃºsica)
        # Si usamos mix.mp3, la narraciÃ³n del video largo se superpone a la del teaser
        bgm_path = None
        temp_bgm_path = str(self.generated_media_dir / "temp_bgm.mp3")
        if os.path.exists(temp_bgm_path):
            bgm_path = temp_bgm_path
            self.log(f"   ðŸŽµ Reutilizando mÃºsica de fondo (solo mÃºsica): {os.path.basename(temp_bgm_path)}")

        # Crear storyboard para el teaser
        teaser_storyboard = {
            # El Short autonomo lleva el tema tal cual (nombre de archivo con el tema);
            # el teaser legado conserva el sufijo.
            "topic": topic if mode == "standalone" else f"{topic} - Teaser",
            "category": category,
            "script": teaser_script,
            "audio_path": teaser_audio_path,
            "segments": teaser_visual_segments,
            "music_data": long_video_storyboard.get('music_data'),  # Fallback si no hay archivo local
            "format_archetype": long_video_storyboard.get('format_archetype') or '',
            "derived_from_long": True,
            "derivation_mode": mode,
        }

        # Verificar que tenemos el callback para ensamblar
        if not self.assemble_video_callback:
            self.log("âŒ Error: No se proporcionÃ³ callback para ensamblar video")
            return None

        # Ensamblar usando el mÃ©todo principal pero con plataforma 'youtube_short'
        # IMPORTANTE: No generar otro teaser (generate_short_teaser=False)
        # Para teasers, usar solo imÃ¡genes estÃ¡ticas (mÃ¡s rÃ¡pido y confiable que videos)
        teaser_result = self.assemble_video_callback(
            storyboard_data=teaser_storyboard,
            platform='youtube_short',  # Formato vertical
            add_subtitles=True,
            subtitle_style='capcut',  # Estilo dinÃ¡mico para shorts
            add_overlays=True,
            manual_bgm_path=bgm_path,  # Usar mÃºsica ya descargada si existe
            transition_type='ðŸŒŠ Zoom DinÃ¡mico',  # TransiciÃ³n mÃ¡s dinÃ¡mica para teaser
            transition_duration=0.6,  # Transiciones mÃ¡s rÃ¡pidas y dinÃ¡micas
            assembly_mode='auto',
            visual_mode='static',  # âš¡ Solo imÃ¡genes estÃ¡ticas para teaser (mÃ¡s rÃ¡pido y confiable)
            apply_cinematic=True,  # Aplicar efectos cinematogrÃ¡ficos para mÃ¡ximo impacto
            cinematic_preset='dramatic',  # Preset dramÃ¡tico para teaser llamativo
            generate_short_teaser=False,  # No generar teaser del teaser
            use_wikimedia=False,  # El teaser no usa Wikimedia por defecto
            disable_wikimedia=disable_wikimedia,  # Respetar la configuraciÃ³n de desactivaciÃ³n
            use_real_images=False,  # El teaser no usa imÃ¡genes reales por defecto
            use_google_images=False,  # (OBSOLETO) Openverse (Gratis) eliminado
            enable_real_images_mix=False  # El teaser no usa mezcla inteligente por defecto
        )
        
        if teaser_result:
            self.log("âœ… SHORT TEASER GENERADO EXITOSAMENTE")
            self.log(f"ðŸ“¹ Teaser guardado en: {teaser_result['video_path']}")
            return teaser_result
        else:
            self.log("âŒ Error al ensamblar el short teaser")
            return None

    def _assemble_existing_teaser(self, existing_teaser_storyboard, long_video_storyboard, disable_wikimedia=False):
        """
        Ensambla un teaser reutilizando el storyboard existente (audio, segmentos, imÃ¡genes).

        Args:
            existing_teaser_storyboard: Storyboard del teaser previo con audio y segmentos
            long_video_storyboard: Storyboard del video largo (para mÃºsica)
            disable_wikimedia: (OBSOLETO) ParÃ¡metro mantenido por compatibilidad - Openverse (Gratis) y Wikimedia eliminados

        Returns:
            dict con resultado del teaser o None si falla
        """
        self.log("ðŸŽ¬ Ensamblando teaser con datos existentes...")

        topic = long_video_storyboard.get('topic', 'Video')
        category = long_video_storyboard.get('category', 'General')

        # Buscar mÃºsica de fondo ya descargada
        # IMPORTANTE: Usar SOLO temp_bgm.mp3 (mÃºsica pura), NO mix.mp3 (que contiene narraciÃ³n + mÃºsica)
        bgm_path = None
        temp_bgm_path = str(self.generated_media_dir / "temp_bgm.mp3")
        if os.path.exists(temp_bgm_path):
            bgm_path = temp_bgm_path
            self.log(f"   ðŸŽµ Reutilizando mÃºsica de fondo (solo mÃºsica): {os.path.basename(temp_bgm_path)}")

        # Usar el storyboard existente directamente
        teaser_storyboard = {
            "topic": f"{topic} - Teaser",
            "category": category,
            "script": existing_teaser_storyboard.get('script', ''),
            "audio_path": existing_teaser_storyboard.get('audio_path'),
            "segments": existing_teaser_storyboard.get('segments', []),
            "music_data": long_video_storyboard.get('music_data')
        }

        # Verificar que tenemos el callback para ensamblar
        if not self.assemble_video_callback:
            self.log("âŒ Error: No se proporcionÃ³ callback para ensamblar video")
            return None

        # Ensamblar usando el mÃ©todo principal
        # Para teasers, usar solo imÃ¡genes estÃ¡ticas (mÃ¡s rÃ¡pido y confiable que videos)
        teaser_result = self.assemble_video_callback(
            storyboard_data=teaser_storyboard,
            platform='youtube_short',
            add_subtitles=True,
            subtitle_style='capcut',
            add_overlays=True,
            manual_bgm_path=bgm_path,
            transition_type='ðŸŒŠ Zoom DinÃ¡mico',
            transition_duration=0.6,
            assembly_mode='auto',
            visual_mode='static',  # âš¡ Solo imÃ¡genes estÃ¡ticas para teaser (mÃ¡s rÃ¡pido y confiable)
            apply_cinematic=True,
            cinematic_preset='dramatic',
            generate_short_teaser=False,
            use_wikimedia=False,
            disable_wikimedia=disable_wikimedia,
            use_real_images=False,
            use_google_images=False,
            enable_real_images_mix=False
        )

        if teaser_result:
            self.log("âœ… SHORT TEASER REGENERADO EXITOSAMENTE")
            self.log(f"ðŸ“¹ Teaser guardado en: {teaser_result['video_path']}")
            return teaser_result
        else:
            self.log("âŒ Error al ensamblar el short teaser")
            return None


