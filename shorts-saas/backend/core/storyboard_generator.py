# storyboard_generator.py
"""
Generador de storyboards y teasers
Maneja la generaciÃ³n de guiones, segmentos, prompts visuales y teasers
"""

import os
import re
import time
from pathlib import Path
from typing import Optional, Dict, List
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
    from music_recommender import (
        analyze_narration,
        map_ai_to_jamendo_tags,
        search_jamendo_api
    )
    JAMENDO_AVAILABLE = True
except ImportError:
    JAMENDO_AVAILABLE = False

RESEARCH_SEARCH_AVAILABLE = False
try:
    from research_search import search_research_context, RESEARCH_AVAILABLE
    RESEARCH_SEARCH_AVAILABLE = RESEARCH_AVAILABLE
except ImportError:
    pass

# Fallback a Google Search si research_search no está disponible
GOOGLE_SEARCH_AVAILABLE = False
if not RESEARCH_SEARCH_AVAILABLE:
    try:
        from google_search_api import search_google_trends
        GOOGLE_SEARCH_AVAILABLE = True
    except ImportError:
        GOOGLE_SEARCH_AVAILABLE = False

from video_config import VideoConfig


class StoryboardGenerator:
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

    def _is_long_horizontal_request(self, platform: str, custom_duration: Optional[int]) -> bool:
        """Determina si corresponde aplicar perfil de largo horizontal."""
        return platform == 'youtube'

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

    def _enforce_max_audio_duration(self, audio_path: str, max_seconds: float) -> tuple:
        """
        Si el audio excede max_seconds, lo acelera con FFmpeg atempo para que
        encaje en el límite.  Devuelve (audio_path, speed_factor).
        speed_factor == 1.0 indica que no se modificó.
        """
        import subprocess

        if not audio_path or not os.path.exists(audio_path):
            return audio_path, 1.0

        # ── Probar duración real ──
        duration = 0.0
        ffprobe_cmd = "ffprobe"
        try:
            configured_probe = getattr(VideoConfig, 'FFPROBE_BINARY_PATH', None)
            if configured_probe and os.path.exists(configured_probe):
                ffprobe_cmd = configured_probe
            else:
                ffmpeg_dir = getattr(VideoConfig, 'FFMPEG_BINARY_PATH', None)
                if ffmpeg_dir:
                    probe_candidate = os.path.join(ffmpeg_dir, "ffprobe.exe")
                    if os.path.exists(probe_candidate):
                        ffprobe_cmd = probe_candidate
        except Exception:
            pass

        try:
            result = subprocess.run(
                [ffprobe_cmd, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            duration = float(result.stdout.strip())
        except Exception as e:
            self.log(f"   ⚠️ No se pudo medir duración del audio: {e}")
            return audio_path, 1.0

        if duration <= max_seconds:
            self.log(f"   ✅ Duración del audio ({duration:.1f}s) dentro del límite ({max_seconds:.0f}s)")
            return audio_path, 1.0

        # ── Calcular factor de aceleración ──
        speed_factor = duration / max_seconds
        # FFmpeg atempo soporta 0.5–2.0 por instancia; limitar a 2.0
        if speed_factor > 2.0:
            self.log(f"   ⚠️ Audio demasiado largo ({duration:.1f}s). "
                     f"Se necesitaría {speed_factor:.2f}x pero el máximo es 2.0x. "
                     f"Se aplicará 2.0x (resultado ~{duration/2.0:.0f}s).")
            speed_factor = 2.0

        self.log(f"   ⏩ Auto-velocidad: {duration:.1f}s → {duration/speed_factor:.1f}s "
                 f"(×{speed_factor:.2f}) para encajar en {max_seconds:.0f}s")

        # ── Aplicar atempo con FFmpeg ──
        ffmpeg_cmd = "ffmpeg"
        try:
            ffmpeg_dir = getattr(VideoConfig, 'FFMPEG_BINARY_PATH', None)
            if ffmpeg_dir:
                ffmpeg_candidate = os.path.join(ffmpeg_dir, "ffmpeg.exe")
                if os.path.exists(ffmpeg_candidate):
                    ffmpeg_cmd = ffmpeg_candidate
        except Exception:
            pass

        sped_path = audio_path.replace(".mp3", "_fast.mp3")
        if sped_path == audio_path:
            sped_path = audio_path + "_fast.mp3"

        # Construir cadena atempo (si >2.0 encadenamos, pero ya limitamos a 2.0)
        atempo_value = f"{speed_factor:.4f}"

        try:
            cmd = [
                ffmpeg_cmd, "-y", "-i", audio_path,
                "-filter:a", f"atempo={atempo_value}",
                "-vn", sped_path
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if proc.returncode == 0 and os.path.exists(sped_path):
                # Reemplazar original
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
                os.rename(sped_path, audio_path)
                self.log(f"   ✅ Audio acelerado ×{speed_factor:.2f} guardado: {Path(audio_path).name}")
                return audio_path, speed_factor
            else:
                self.log(f"   ⚠️ FFmpeg atempo falló: {proc.stderr[:200]}")
                return audio_path, 1.0
        except Exception as e:
            self.log(f"   ⚠️ Error aplicando atempo: {e}")
            return audio_path, 1.0

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
            self.log("⚠️ Revisión IA descartada por longitud atípica. Se mantiene guion base.")
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
    
    def generate_manual_prompt_text(self, topic, category, duration, language='es',
                                    research_context=None, video_format=None):
        """
        Genera el texto del prompt para modo manual (JSON).
        
        Args:
            topic: Tema del video
            category: CategorÃ­a del video
            duration: DuraciÃ³n en segundos
            language: Idioma ('es' o 'en')
            research_context: Lista de snippets de investigaciÃ³n (opcional)
            video_format: Formato de video ('9:16', '16:9', etc.)
        
        Returns:
            String con el prompt para la IA
        """
        lang_str = "SPANISH" if language == 'es' else "ENGLISH"
        lang_label = "español" if language == 'es' else "English"
        try:
            duration_value = int(duration)
        except Exception:
            duration_value = 60
        # Forzar límite de 180s para formato vertical (YouTube Shorts)
        is_vertical = video_format and '9:16' in str(video_format)
        if is_vertical and duration_value > 180:
            duration_value = 180
        if is_vertical:
            # Shorts: menos escenas y menos palabras para evitar aceleración excesiva
            # ~2.0 palabras/seg da margen; 15-20s por escena mantiene ritmo dinámico
            words_estimate = int(duration_value * 2.0)
            estimated_scenes = max(3, min(12, int(duration_value / 18)))
        else:
            scene_divisor = 12 if duration_value >= 1800 else 6
            estimated_scenes = max(3, int(duration_value / scene_divisor))
            words_estimate = int(duration_value * 2.5)
        
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
        if is_vertical:
            format_section = f"""
FORMATO: YouTube Short (vertical 9:16) — MÁXIMO {duration_value} segundos.
- Este video DEBE durar {duration_value} segundos o menos para ser clasificado como YouTube Short.
- La narración total NO debe superar {words_estimate} palabras ({estimated_scenes} escenas × ~{words_estimate // estimated_scenes} palabras cada una).
- ESTRICTO: si generas más de {words_estimate} palabras en total, el audio será demasiado largo y se rechazará.
- Sé conciso y directo. Cada frase debe aportar valor. No rellenes.
- Ritmo rápido: engancha en los primeros 3 segundos y mantén la tensión.
- Cada escena debe tener ~{words_estimate // estimated_scenes} palabras de narración, NO más.
"""

        prompt = f"""Eres un guionista experto para un canal de YouTube sobre misterios, conspiraciones y fenómenos inexplicables llamado "Stunning Revelations".

TAREA: Escribe un guión técnico en formato JSON para un video de {duration_value} segundos (~{words_estimate} palabras de narración total) sobre:

TEMA: "{topic}"
CATEGORÍA: {category}
IDIOMA DE NARRACIÓN: {lang_label}
{format_section}{research_section}
REGLA FUNDAMENTAL — SOLO CASOS DOCUMENTADOS:
- El guión debe basarse EXCLUSIVAMENTE en casos, eventos, testimonios y datos documentados que existan en la realidad.
- NO inventes casos, nombres, fechas, lugares ni eventos. Todo lo mencionado debe ser verificable o haber sido reportado públicamente.
- Está permitido mencionar casos no confirmados o controversiales, siempre que realmente hayan sido reportados (ej: avistamientos, testimonios, documentos desclasificados).
- Si mencionas una fecha, nombre o evento específico, debe ser real. Si no estás seguro, usa formulaciones como "según reportes de la época" o "testigos afirmaron que...".
- Puedes especular y plantear preguntas abiertas ("¿Y si esto fuera verdad?"), pero la base factual debe ser real.

TONO Y ESTILO:
- Narrativa envolvente, misteriosa e intrigante (NO documental aburrido)
- Presenta las teorías como posibilidades fascinantes: "¿Y si...?", "Lo que pocos saben es..."
- Usa ganchos emocionales y cliffhangers entre escenas
- Mantén al espectador enganchado con revelaciones progresivas
- Al final, incluye una llamada a suscribirse a "Stunning Revelations" de forma natural

ESTRUCTURA JSON REQUERIDA (responde SOLO con este JSON, sin texto adicional):
{{
  "title": "Título impactante del video en {lang_label}",
  "scenes": [
    {{
      "narration": "Texto completo de narración para esta escena en {lang_label}. Debe ser un párrafo sustancial (varias oraciones).",
      "visual_prompt": "Descripción visual detallada EN INGLÉS para generar imagen con IA. Estilo cinematográfico, dramático, misterioso. Ej: 'Aerial view of ancient pyramids at sunset, dramatic golden light, cinematic composition, mysterious atmosphere, 8k quality'",
      "sfx_tag": "Efecto de sonido en inglés (ej: 'thunder', 'suspense', 'wind') o 'none'",
      "overlay_tag": "GIF/sticker descriptivo en inglés o 'none'"
    }}
  ]
}}

REGLAS CRÍTICAS:
1. Genera exactamente {estimated_scenes} escenas (aprox. {duration_value // estimated_scenes}s cada una)
2. Toda la narración en {lang_label}, todos los visual_prompt en INGLÉS
3. Cada escena debe tener narración de ~{words_estimate // estimated_scenes} palabras (ni mucho más, ni frases sueltas)
4. Los visual_prompt deben ser detallados y cinematográficos
5. Responde ÚNICAMENTE con el JSON, sin explicaciones antes o después
6. El total de palabras de narración debe ser aproximadamente {words_estimate}"""
        
        return prompt
    
    def process_manual_json(self, json_data, voice_id=None, language='es', rate="+0%",
                            max_duration: float = 0):
        """
        Procesa el JSON manual: genera UN audio completo y segmenta con Whisper.
        Usa el mismo flujo probado que generate_storyboard_data.
        
        Args:
            json_data: Diccionario con el JSON del guion manual
            voice_id: ID de voz para TTS (opcional)
            language: Idioma ('es' o 'en')
            rate: Velocidad de habla Edge-TTS, ej: '+0%', '+30%'
            max_duration: Duración máxima en segundos (0 = sin límite). Para 9:16 Short, usar 180.
        
        Returns:
            Diccionario con storyboard o None si falla
        """
        self.log("\n" + "="*70)
        self.log("📄 PROCESANDO JSON MANUAL...")
        self.log("="*70)

        if 'scenes' not in json_data:
            self.log("❌ Error: El JSON no contiene la clave 'scenes'")
            return None
        
        scenes = json_data['scenes']
        total_scenes = len(scenes)
        self.log(f"📋 JSON contiene {total_scenes} escenas")
        
        # 1. Combinar todas las narraciones en un guión completo
        full_script = ""
        scene_metadata = []
        for i, scene in enumerate(scenes):
            text = scene.get('narration', '').strip()
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
        self.log(f"📜 Guión combinado: {total_words} palabras de {len(scene_metadata)} escenas")
        
        if not full_script:
            self.log("❌ Error: No se encontró narración en las escenas")
            return None
        
        # 2. Generar UN solo audio TTS (mismo método que flujo normal)
        self.log(f"🎙️ Generando narración completa ({language})...")
        audio_filename = f"manual_{int(time.time())}.mp3"
        audio_path_str = str(VideoConfig.AUDIO_DIR / audio_filename)
        
        audio_path = self.tts.generate_narration(
            full_script, audio_path_str, voice_id, language=language, rate=rate
        )
        
        if not audio_path:
            self.log("❌ Error al generar audio.")
            return None
        self.log(f"   🎵 Audio guardado: {audio_path}")

        # 2.5. Auto-velocidad si hay límite de duración (ej: 180s para Shorts 9:16)
        if max_duration > 0:
            audio_path, speed_factor = self._enforce_max_audio_duration(audio_path, max_duration)
            if speed_factor > 1.0:
                self.log(f"   ⏩ Narración acelerada ×{speed_factor:.2f} para encajar en {max_duration:.0f}s")

        # 3. Calcular duración total del audio y distribuir tiempos por escena
        #    NO usamos Whisper: ya tenemos el texto correcto del JSON.
        #    Whisper sobre-segmenta y produce transcripciones con errores.
        self.log("⏱️ Calculando tiempos por escena...")
        try:
            from pydub import AudioSegment as PydubAudio
            audio_obj = PydubAudio.from_mp3(str(audio_path))
            total_duration = len(audio_obj) / 1000.0
        except Exception:
            total_duration = total_words / 2.5  # ~2.5 palabras/segundo
        
        self.log(f"   ⏱️ Duración total del audio: {total_duration:.1f}s")
        
        # Distribuir tiempos proporcionalmente por conteo de palabras
        segments = []
        current_time = 0.0
        for i, meta in enumerate(scene_metadata):
            word_ratio = meta['word_count'] / total_words if total_words > 0 else 1.0 / len(scene_metadata)
            seg_duration = total_duration * word_ratio
            segments.append({
                'start': current_time,
                'end': current_time + seg_duration,
                'text': meta['text'],
                'narration_text': meta['text'],
                'visual_prompt': meta['visual_prompt'],
                'sfx_tag': meta['sfx_tag'],
                'overlay_tag': meta['overlay_tag'],
                'assigned_filename': f"segment_{i+1:03d}"
            })
            current_time += seg_duration
        
        self.log(f"✅ Storyboard manual listo: {len(segments)} segmentos")
        
        return {
            "topic": json_data.get('title', 'Video Manual'),
            "category": "Manual",
            "script": full_script,
            "audio_path": str(audio_path),
            "segments": segments,
            "music_data": None,
            "voice_id": voice_id,
            "language": language
        }
    
    def generate_storyboard_data(self, topic: str, category: str, platform: str = 'youtube',
                                 custom_duration: Optional[int] = None,
                                 voice_id: Optional[str] = None,
                                 find_auto_music: bool = True,
                                 style: str = "Estilo Realista / Cinematográfico",
                                 language: str = 'es',
                                 pre_research_snippets: list = None,
                                 rate: str = "+0%"):
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
        
        if not self.gemini_client:
            self.log("âŒ Error CrÃ­tico: Cliente Gemini no disponible.")
            return None
        
        # --- 1. Determinar DuraciÃ³n y Perfil ---
        profile_info = self._resolve_duration_and_profile(platform, custom_duration)
        duration_target = profile_info["duration_target"]
        generation_profile = profile_info["profile"]
        retention_targets = profile_info["retention_targets"]
        self.log(f"â³ DuraciÃ³n objetivo: {duration_target}s")
        if generation_profile == "long_horizontal":
            self.log("📺 Perfil activo: long_horizontal (retención para video largo horizontal)")
            if custom_duration and not (1800 <= int(custom_duration) <= 2700):
                self.log("   â„¹ï¸ Recomendación: usar entre 1800s y 2700s para este perfil")
        
        # --- 2. Generar Guion con Gemini (Basado en InvestigaciÃ³n) ---
        self.log(f"ðŸ§  Generando guion ({language})...")
        
        research_context = []
        
        # Usar snippets pre-seleccionados por el usuario si existen
        if pre_research_snippets and len(pre_research_snippets) > 0:
            self.log(f"   📋 Usando {len(pre_research_snippets)} fuentes de investigación seleccionadas por el usuario")
            research_context = list(pre_research_snippets)
        
        # Si no hay snippets pre-seleccionados, buscar automáticamente
        # Opción 1: Wikipedia + DuckDuckGo (gratis, sin API key)
        elif RESEARCH_SEARCH_AVAILABLE:
            self.log("   📚 Investigando en Wikipedia + DuckDuckGo...")
            try:
                research_results = search_research_context(
                    topic, category=category, language=language, max_results=8
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
                self.log(f"   ⚠️ Error en búsqueda Wikipedia/DDG: {e}")
        
        # Opción 2: Google Search como fallback
        elif GOOGLE_SEARCH_AVAILABLE:
            self.log("   🔍 Investigando en Google...")
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
                self.log(f"   ⚠️ Error en búsqueda Google: {e}")
            
        if research_context:
            script = self.gemini_client.generate_video_script_with_research(
                topic,
                category,
                duration_target,
                research_context,
                language=language,
                narrative_profile=generation_profile
            )
        else:
            script = self.gemini_client.generate_video_script(
                topic,
                category,
                duration_target,
                language=language,
                narrative_profile=generation_profile
            )

        if not script or script.startswith("ERROR"):
            if script == "ERROR_QUOTA_EXCEEDED":
                error_msg = "Error generando guion: Cuotas de Claude API agotadas"
                self.log(f"âŒ {error_msg}")
                self.log("   ðŸ’¡ Las cuotas de tu plan de Claude se han agotado")
                self.log("   ðŸ’¡ Las cuotas se repondrÃ¡n automÃ¡ticamente. Intenta mÃ¡s tarde.")
                raise Exception(error_msg)
            elif script:
                self.log(f"âŒ Error de Claude: {script}")
            else:
                self.log("âŒ Error de Claude: No se pudo generar el guion")
            return None
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

        # --- 3. Generar Audio (Voz) ---
        self.log(f"ðŸŽ™ï¸ Generando narraciÃ³n ({language})...")
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
        if platform in ('youtube_short', 'tiktok', 'reels'):
            max_short_seconds = 180.0
            audio_path, speed_factor = self._enforce_max_audio_duration(audio_path, max_short_seconds)
            if speed_factor > 1.0:
                self.log(f"   ⏩ Narración acelerada ×{speed_factor:.2f} para formato vertical corto")

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
            from text_correction_engine import TextCorrectionEngine
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
            self.log(f"📈 Gate retención (0-60s) estimado: {intro_score}/100")

            if intro_score < 55:
                self.log("⚠️ Intro débil detectada para largo horizontal. Reintentando guion en modo estricto...")
                retry_script = None
                if research_context:
                    retry_script = self.gemini_client.generate_video_script_with_research(
                        topic,
                        category,
                        duration_target,
                        research_context,
                        language=language,
                        narrative_profile="long_horizontal_strict"
                    )
                else:
                    retry_script = self.gemini_client.generate_video_script(
                        topic,
                        category,
                        duration_target,
                        language=language,
                        narrative_profile="long_horizontal_strict"
                    )

                if retry_script and not str(retry_script).startswith("ERROR"):
                    retry_script = self._review_script_with_ai(
                        retry_script,
                        topic=topic,
                        category=category,
                        language=language,
                        duration_target=duration_target
                    )
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
                                from text_correction_engine import TextCorrectionEngine
                                corrector = TextCorrectionEngine()
                                retry_segments = corrector.correct_segments(retry_segments)
                            except Exception:
                                pass

                            retry_segments = self._sync_segment_texts_with_script(
                                retry_segments,
                                retry_script
                            )

                            retry_score = self._estimate_long_intro_quality_score(retry_segments)
                            self.log(f"📈 Gate retención (reintento): {retry_score}/100")
                            if retry_score >= intro_score:
                                script = retry_script
                                audio_path = retry_audio_path
                                segments = retry_segments
                                intro_score = retry_score
                                self.log("✅ Reintento aplicado: mejoró o igualó la calidad de intro")
                            else:
                                self.log("ℹ️ Reintento descartado: no mejoró la calidad de intro")
                        else:
                            self.log("⚠️ Reintento: no se pudieron transcribir segmentos")
                    else:
                        self.log("⚠️ Reintento: no se pudo generar audio")

        # --- 5. Generar Prompts Visuales ---
        self.log(f"ðŸ§  Generando prompts visuales, SFX y Overlays...")
        segments_with_prompts = []
        prompt_stride = self._resolve_prompt_stride(generation_profile, duration_target, len(segments))
        prompt_requests = 0
        if prompt_stride > 1:
            estimated_requests = (len(segments) + prompt_stride - 1) // prompt_stride
            self.log(
                f"   ⚙️ Modo eficiente para largo horizontal: "
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
                narrative_context=narrative_context
            )
            prompt_requests += 1
            if not isinstance(prompt_data, dict):
                prompt_data = {}

            for offset, segment in enumerate(segment_group):
                segment.update(prompt_data)
                segment['assigned_filename'] = f"segment_{i + offset + 1:03d}"
                segments_with_prompts.append(segment)

        if prompt_stride > 1:
            self.log(f"   ✅ Prompts IA generados: {prompt_requests} (antes: {len(segments)})")
            
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
                    sent = -0.5 if category in ["Misterios", "Paranormal", "Conspiraciones"] else 0.5
                
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
            "language": language
        }
    
    def generate_short_teaser_from_long_video(self, long_video_storyboard, language='es', voice_id=None,
                                               disable_wikimedia=False, existing_teaser_storyboard=None,
                                               rate="+0%"):
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
            self.log("âŒ Error: Cliente Gemini no disponible para generar teaser.")
            return None

        # 1. Generar guion corto del teaser (EXTREMADAMENTE LLAMATIVO tipo trailer)
        self.log("ðŸ§  Generando guion del teaser (TRAILER CINEMATOGRÃFICO EXTREMO)...")
        lang_instr = "WRITE IN ENGLISH." if language == 'en' else "ESCRIBE EN ESPAÃ‘OL."
        
        # Obtener mÃ¡s contexto del script completo
        script_context = full_script[:1000] if len(full_script) > 1000 else full_script
        
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
           - Include subscription invitation: "SuscrÃ­bete a Stunning Revelations para mÃ¡s contenido fascinante"
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
        [CTA directo] "Mira el video completo en el enlace de arriba para descubrir toda la verdad. SuscrÃ­bete a Stunning Revelations para mÃ¡s contenido fascinante. No te pierdas esta revelaciÃ³n impactante."
        
        NOW CREATE THE TRAILER SCRIPT:
        """
        
        teaser_script = self.gemini_client._generate(teaser_prompt)
        
        # Verificar si la generaciÃ³n fue exitosa
        if not teaser_script:
            self.log("âŒ Error generando guion del teaser: Claude CLI retornÃ³ cÃ³digo de error")
            self.log("   ðŸ’¡ Verifica que Claude Code CLI estÃ© instalado y funcionando correctamente")
            return None
        
        # Detectar error especÃ­fico de cuotas agotadas
        if isinstance(teaser_script, str) and teaser_script == "ERROR_QUOTA_EXCEEDED":
            error_msg = "Error generando guion del teaser: Cuotas de Claude API agotadas"
            self.log(f"âŒ {error_msg}")
            self.log("   ðŸ’¡ Las cuotas de tu plan de Claude se han agotado")
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
                    narrative_context=narrative_context
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
            "topic": f"{topic} - Teaser",
            "category": category,
            "script": teaser_script,
            "audio_path": teaser_audio_path,
            "segments": teaser_visual_segments,
            "music_data": long_video_storyboard.get('music_data')  # Fallback si no hay archivo local
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




