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


class StoryboardFactCheckMixin:
    def _call_llm_generate(self, prompt: str, max_tokens: int = 4096):
        """Llama al generador IA con compatibilidad entre distintas firmas."""
        if not self.gemini_client:
            return None

        generate_fn = getattr(self.gemini_client, "_generate", None)
        if not callable(generate_fn):
            return None

        try:
            return generate_fn(prompt, max_tokens=max_tokens, task_type="script_quality")
        except TypeError:
            try:
                return generate_fn(prompt, max_tokens=max_tokens)
            except TypeError:
                try:
                    return generate_fn(prompt)
                except Exception:
                    return None
        except Exception:
            return None


    def _fact_check_scenes(self, scenes, topic: str, language: str, research_context=None, title: str = ""):
        """Verifica (y repara) los hechos de la narracion ANTES de la voz. Ver script_fact_check.

        Devuelve (escenas, informe). Nunca lanza: si no hay juez, el informe dice
        'unchecked' y la subida vuelve a verificar.
        """
        try:
            from ai.script_fact_check import fact_check_scenes, format_report, default_rewriter
        except Exception as exc:
            self.log(f"   [WARN] Verificacion de hechos no disponible: {exc}")
            return scenes, None
        fallback = None
        generate_fn = getattr(self.gemini_client, "_generate", None) if self.gemini_client else None
        if callable(generate_fn):
            def fallback(prompt):
                return generate_fn(prompt, max_tokens=8000, task_type="script_quality")
        self.log("🔎 Verificando los hechos del guion (Wikipedia + juez externo) antes de la voz...")
        try:
            scenes, report = fact_check_scenes(
                scenes, topic, language=language, research_context=research_context,
                generate_fn=default_rewriter(fallback, log=self.log), log=self.log, title=title)
        except Exception as exc:
            self.log(f"   [WARN] La verificacion de hechos fallo: {exc}")
            return scenes, None
        for line in format_report(report):
            self.log("   " + line)
        if report.get("status") == "needs_review":
            self.log("   ⛔ Quedan afirmaciones falsas o inventadas: corregilas en el timeline "
                     "(la subida queda frenada hasta entonces).")
        return scenes, report


    def _sanitize_script_text(self, script: str, language: str = 'es') -> str:
        """
        Limpia artefactos de guion no narrativos (hashtags, chapter labels, markdown, etc.).
        """
        if not script:
            return ""

        text = str(script).replace('\r\n', '\n').replace('\r', '\n').strip()

        # Bloques y encabezados markdown
        text = re.sub(r'```[\s\S]*?```', ' ', text)
        text = re.sub(r'(?im)^\s*#{1,6}\s+.*$', ' ', text)

        # Etiquetas no narrativas comunes
        text = re.sub(r'(?i)\b(?:chapter|cap[ií]tulo)\s*\d+\s*[:\-–]\s*', '', text)
        text = re.sub(r'(?i)\bhashtags?\b', '', text)
        text = re.sub(r'(?<!\w)#\w+', '', text)
        text = re.sub(r'(?i)\b(?:narrator|narrador)\s*:\s*', '', text)

        # Normalización
        text = re.sub(r'\s+([,.;:!?])', r'\1', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text


    def _review_script_with_ai(
        self,
        script: str,
        topic: str,
        category: str,
        language: str,
        duration_target: int
    ) -> str:
        """
        Revisión automática del guion con la misma IA usada en generación.
        """
        cleaned_script = self._sanitize_script_text(script, language=language)
        if not cleaned_script:
            return cleaned_script

        original_words = len(cleaned_script.split())
        if original_words < 30:
            return cleaned_script

        lang_label = "English" if language == 'en' else "Spanish"
        max_tokens = min(12000, max(1800, int(original_words * 2.2)))
        review_prompt = f"""
Role: Senior script QA editor for a mystery/conspiracy YouTube channel.
Task: Review, correct and polish this narration script for a {duration_target}s video.

NARRATIVE QUALITY CHECK:
- Ensure the tone is engaging, mysterious, and intriguing throughout — NOT dry, skeptical, or dismissive.
- The script should read like captivating storytelling, not like a fact-checking report.
- If the script sounds too skeptical or debunking, rewrite those parts to be more exploratory and open-minded.
- Theories and claims should be framed as "fascinating possibilities" using phrases like "some believe", "witnesses claim", "could it be that".
- Check internal consistency: dates, names, and facts should not contradict each other within the script.
- Fix any obviously wrong real-world facts (e.g., wrong country, wrong century) but do NOT strip out the mystery/conspiracy angle.

CLEANUP RULES:
- Return ONLY the final narration script in {lang_label}.
- Remove artifacts like hashtags, chapter labels (e.g., "Chapter 1:", "Capítulo 1:"), markdown headings, bullets, or meta notes.
- Fix spelling, punctuation and grammar.
- Correct proper nouns (people, places, institutions, events) when clearly inferable from context.
- Preserve meaning, tone, and approximately the same length.
- Do not add explanations, titles, or comments.

Topic: {topic}
Category: {category}

SCRIPT:
{cleaned_script}
"""

        reviewed = self._call_llm_generate(review_prompt, max_tokens=max_tokens)
        if not reviewed or not isinstance(reviewed, str):
            return cleaned_script

        reviewed = reviewed.strip()
        if not reviewed or reviewed.startswith("ERROR"):
            return cleaned_script

        reviewed = self._sanitize_script_text(reviewed, language=language)
        if not reviewed:
            return cleaned_script

        reviewed_words = len(reviewed.split())
        min_words = max(20, int(original_words * 0.45))
        max_words = int(original_words * 1.75) + 120
        if reviewed_words < min_words or reviewed_words > max_words:
            self.log("️ Revisión IA descartada por longitud atípica. Se mantiene guion base.")
            return cleaned_script

        return reviewed


    def _sync_segment_texts_with_script(self, segments: List[Dict], script: str) -> List[Dict]:
        """
        Reasigna el texto de segmentos desde el guion final para evitar errores ASR.
        """
        if not segments or not script:
            return segments

        script_words = [w for w in str(script).split() if w]
        total_words = len(script_words)
        if total_words <= 0:
            return segments

        durations = []
        baseline_counts = []
        total_duration = 0.0

        for seg in segments:
            start = float(seg.get('start', 0.0) or 0.0)
            end = float(seg.get('end', start) or start)
            duration = max(0.0, end - start)
            durations.append(duration)
            total_duration += duration

            raw_text = str(
                seg.get('text') or seg.get('narration_text') or seg.get('narration') or ''
            ).strip()
            baseline_counts.append(len(raw_text.split()))

        if sum(baseline_counts) <= 0:
            if total_duration > 0:
                baseline_counts = [
                    int(round(total_words * (d / total_duration)))
                    for d in durations
                ]
            else:
                baseline_counts = [0 for _ in segments]

        baseline_total = max(1, sum(baseline_counts))
        min_words = 1 if total_words >= len(segments) else 0
        allocations = [
            max(min_words, int(round((count / baseline_total) * total_words)))
            for count in baseline_counts
        ]

        diff = total_words - sum(allocations)
        priority = sorted(
            range(len(segments)),
            key=lambda idx: (durations[idx], baseline_counts[idx]),
            reverse=True
        ) or list(range(len(segments)))

        if diff > 0:
            ptr = 0
            while diff > 0:
                idx = priority[ptr % len(priority)]
                allocations[idx] += 1
                diff -= 1
                ptr += 1
        elif diff < 0:
            ptr = 0
            guard = 0
            max_guard = max(1, len(priority) * 10)
            while diff < 0 and guard < max_guard:
                idx = priority[ptr % len(priority)]
                if allocations[idx] > min_words:
                    allocations[idx] -= 1
                    diff += 1
                ptr += 1
                guard += 1
            if diff < 0:
                for idx in reversed(priority):
                    while diff < 0 and allocations[idx] > 0:
                        allocations[idx] -= 1
                        diff += 1

        # Ajuste de fronteras: mover cortes a límites naturales de frase
        # para evitar cambios abruptos entre escenas.
        if len(segments) > 1 and total_words > 0:
            boundaries = []
            run = 0
            for i in range(len(allocations) - 1):
                run += allocations[i]
                boundaries.append(run)

            min_words_per_segment = min_words
            punct_pattern = re.compile(r'[.!?;:]["\')\]]*$')
            soft_punct_pattern = re.compile(r'[,]["\')\]]*$')

            for b_idx in range(len(boundaries)):
                target = boundaries[b_idx]
                prev_boundary = 0 if b_idx == 0 else boundaries[b_idx - 1]
                remaining_segments = len(boundaries) - b_idx
                lower_bound = prev_boundary + min_words_per_segment
                upper_bound = total_words - (remaining_segments * min_words_per_segment)
                if lower_bound > upper_bound:
                    continue

                search_left = max(lower_bound, target - 8)
                search_right = min(upper_bound, target + 8)
                best = target
                best_score = float("inf")

                for cand in range(search_left, search_right + 1):
                    if cand <= 0 or cand >= total_words:
                        continue
                    prev_token = script_words[cand - 1]
                    score = abs(cand - target)

                    if punct_pattern.search(prev_token):
                        score -= 2.0
                    elif soft_punct_pattern.search(prev_token):
                        score -= 1.0

                    if score < best_score:
                        best = cand
                        best_score = score

                boundaries[b_idx] = best

            # Recalcular allocations a partir de fronteras ajustadas.
            new_allocations = []
            prev = 0
            for b in boundaries:
                new_allocations.append(max(0, b - prev))
                prev = b
            new_allocations.append(max(0, total_words - prev))

            if len(new_allocations) == len(allocations) and sum(new_allocations) == total_words:
                allocations = new_allocations

        fixed_segments = []
        cursor = 0
        for idx, seg in enumerate(segments):
            take = allocations[idx]
            if idx == len(segments) - 1:
                take = max(0, total_words - cursor)
            else:
                take = max(0, min(take, total_words - cursor))

            chunk = " ".join(script_words[cursor:cursor + take]).strip()
            cursor += take

            seg_copy = dict(seg)
            seg_copy['text'] = chunk
            seg_copy['narration_text'] = chunk
            if 'narration' in seg_copy:
                seg_copy['narration'] = chunk
            fixed_segments.append(seg_copy)

        if cursor < total_words and fixed_segments:
            tail = " ".join(script_words[cursor:]).strip()
            if tail:
                merged = f"{fixed_segments[-1].get('text', '').strip()} {tail}".strip()
                fixed_segments[-1]['text'] = merged
                fixed_segments[-1]['narration_text'] = merged
                if 'narration' in fixed_segments[-1]:
                    fixed_segments[-1]['narration'] = merged

        return fixed_segments
