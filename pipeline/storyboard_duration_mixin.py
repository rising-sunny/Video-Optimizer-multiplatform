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


class StoryboardDurationMixin:
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
            self.log(f"   ️ No se pudo medir duración del audio: {e}")
            return audio_path, 1.0

        if duration <= max_seconds:
            self.log(f"    Duración del audio ({duration:.1f}s) dentro del límite ({max_seconds:.0f}s)")
            return audio_path, 1.0

        # ── Calcular factor de aceleración ──
        speed_factor = duration / max_seconds
        # FFmpeg atempo soporta 0.5–2.0 por instancia; limitar a 2.0
        if speed_factor > 2.0:
            self.log(f"   ️ Audio demasiado largo ({duration:.1f}s). "
                     f"Se necesitaría {speed_factor:.2f}x pero el máximo es 2.0x. "
                     f"Se aplicará 2.0x (resultado ~{duration/2.0:.0f}s).")
            speed_factor = 2.0

        self.log(f"    Auto-velocidad: {duration:.1f}s  {duration/speed_factor:.1f}s "
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
                self.log(f"    Audio acelerado ×{speed_factor:.2f} guardado: {Path(audio_path).name}")
                return audio_path, speed_factor
            else:
                self.log(f"   ️ FFmpeg atempo falló: {proc.stderr[:200]}")
                return audio_path, 1.0
        except Exception as e:
            self.log(f"   ️ Error aplicando atempo: {e}")
            return audio_path, 1.0


    def _measure_audio_duration_seconds(self, audio_path: str) -> float:
        """Mide la duración de un audio usando pydub y, si hace falta, ffprobe."""
        if not audio_path or not os.path.exists(audio_path):
            return 0.0

        if PYDUB_AVAILABLE and AudioSegment is not None:
            try:
                return len(AudioSegment.from_file(audio_path)) / 1000.0
            except Exception:
                pass

        import subprocess

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
            return float((result.stdout or "").strip() or 0.0)
        except Exception:
            return 0.0


    @staticmethod
    def _normalize_scene_durations(scene_durations: List[float],
                                   total_duration: float,
                                   min_duration: float = 0.05) -> List[float]:
        """
        Reescala duraciones por escena para que sumen exactamente el audio total.
        """
        if not scene_durations:
            return []

        cleaned = []
        for raw_duration in scene_durations:
            try:
                cleaned.append(max(min_duration, float(raw_duration)))
            except Exception:
                cleaned.append(min_duration)

        if total_duration <= 0:
            return cleaned

        total_raw = sum(cleaned)
        if total_raw <= 0:
            even_duration = max(min_duration, total_duration / len(cleaned))
            normalized = [even_duration] * len(cleaned)
        else:
            scale = total_duration / total_raw
            normalized = [max(min_duration, duration * scale) for duration in cleaned]

        drift = total_duration - sum(normalized)
        normalized[-1] = max(min_duration, normalized[-1] + drift)

        if len(normalized) > 1 and normalized[-1] <= 0:
            normalized[-1] = min_duration

        return normalized


    @staticmethod
    def _build_segments_from_scene_metadata(scene_metadata: List[Dict],
                                            scene_durations: List[float],
                                            total_duration: float,
                                            timing_source: str) -> List[Dict]:
        """Construye segmentos con timestamps coherentes para storyboard y subtítulos."""
        if not scene_metadata:
            return []

        segments = []
        current_time = 0.0
        total_scenes = len(scene_metadata)

        for i, meta in enumerate(scene_metadata):
            seg_start = max(0.0, current_time)
            planned_duration = scene_durations[i] if i < len(scene_durations) else 0.05
            planned_duration = max(0.05, float(planned_duration))

            if i == total_scenes - 1:
                seg_end = max(seg_start, float(total_duration))
            else:
                seg_end = max(seg_start, min(float(total_duration), seg_start + planned_duration))

            duration = max(0.05, seg_end - seg_start)
            seg_start = round(seg_start, 6)
            seg_end = round(seg_end, 6)
            duration = round(duration, 6)

            segments.append({
                'start': seg_start,
                'end': seg_end,
                'start_time': seg_start,
                'end_time': seg_end,
                'timestamp_start': seg_start,
                'timestamp_end': seg_end,
                'duration': duration,
                'text': meta['text'],
                'narration_text': meta['text'],
                'visual_prompt': meta['visual_prompt'],
                'sfx_tag': meta['sfx_tag'],
                'overlay_tag': meta['overlay_tag'],
                'assigned_filename': f"segment_{i+1:03d}",
                'timing_source': timing_source,
            })

            current_time = seg_end

        return segments


    def _estimate_scene_durations_with_selected_tts(self,
                                                    scene_metadata: List[Dict],
                                                    voice_id: Optional[str],
                                                    language: str,
                                                    rate: str) -> Optional[List[float]]:
        # Medir cada escena con TTS real esta DESACTIVADO: colgaba en Windows por
        # asyncio, y desde entonces las duraciones salen del reparto proporcional por
        # palabras (ver AI_VIDEO_PLAYBOOK, "cortes de imagen vs voz"). La medicion
        # real quedo en git antes de la limpieza del 2026-09-14 si se quiere retomar.
        return None
