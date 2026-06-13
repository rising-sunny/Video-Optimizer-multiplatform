# studio_video_assembly_handlers.py
"""
Handlers para el ensamblaje de video en AutoVideoStudioTab
"""

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QMessageBox
import os
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from auto_video_generator_pyqt6_adapter import VideoGenerationWorker


class StudioVideoAssemblyHandlers:
    """Helper class para manejar handlers de ensamblaje de video de AutoVideoStudioTab"""

    def __init__(self, studio_tab):
        """Inicializa el handler con una referencia a AutoVideoStudioTab"""
        self.studio_tab = studio_tab

    def _safe_float(self, value, default=0.0) -> float:
        """Convierte un valor a float de forma segura."""
        try:
            if value is None:
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _is_short_form_platform(self, platform_name: str) -> bool:
        """Detecta plataformas de short vertical que requieren sync preciso."""
        return str(platform_name or "").strip().lower() in {"youtube_short", "tiktok", "reels"}

    def _requires_precise_subtitle_sync(self, platform_targets, add_subtitles: bool) -> bool:
        """Los shorts con subtitulos solo se exportan con sync preciso."""
        if not add_subtitles:
            return False
        return any(self._is_short_form_platform(platform) for platform in (platform_targets or []))

    def _ensure_precise_subtitle_sync_ready(self, platform_targets, add_subtitles: bool) -> bool:
        """Bloquea temprano si falta Whisper/torch/ffmpeg para shorts con subtitulos."""
        if not self._requires_precise_subtitle_sync(platform_targets, add_subtitles):
            return True

        try:
            from dynamic_subtitle_wrapper import probe_precise_subtitle_dependencies
            health = probe_precise_subtitle_dependencies()
        except Exception as exc:
            health = {
                'ready': False,
                'missing': ['subtitle_probe'],
                'error': str(exc),
            }

        if health.get('ready'):
            self.studio_tab.log(
                " Short con subtítulos: sincronización precisa Whisper verificada."
            )
            return True

        missing = ", ".join(health.get('missing') or ['dependencias desconocidas'])
        self.studio_tab.log(
            " Exportación bloqueada: los shorts con subtítulos requieren sincronización precisa."
        )
        self.studio_tab.log(f"   Dependencias faltantes: {missing}")
        QMessageBox.warning(
            self.studio_tab,
            "Sincronización Precisa Requerida",
            "Los shorts con subtítulos sólo se exportan con sincronización precisa.\n\n"
            f"Faltan dependencias: {missing}.\n\n"
            "Repara Whisper/torch/FFmpeg o exporta el short sin subtítulos."
        )
        return False

    def _resolve_storyboard_media_path(self, raw_path, storyboard: dict = None) -> str:
        """
        Resuelve rutas de media (audio/imágenes) en forma robusta:
        - Ruta absoluta existente -> absoluta normalizada.
        - Ruta relativa -> intenta resolver contra carpeta de proyecto, CWD y raíz del repo.
        Si no encuentra un archivo real, devuelve el valor original.
        """
        if not raw_path:
            return raw_path

        try:
            original = str(raw_path).strip()
        except Exception:
            return raw_path

        if not original:
            return raw_path

        if os.path.exists(original):
            try:
                return str(Path(original).resolve())
            except Exception:
                return original

        raw = Path(original)
        if raw.is_absolute():
            return original

        candidate_bases = []

        def _append_base(base_path):
            if not base_path:
                return
            try:
                base = Path(base_path)
            except Exception:
                return
            if base.suffix.lower() == '.json':
                base = base.parent
            candidate_bases.append(base)

        if isinstance(storyboard, dict):
            _append_base(storyboard.get('_project_path'))

        if hasattr(self.studio_tab, 'current_project_path'):
            _append_base(getattr(self.studio_tab, 'current_project_path', None))

        _append_base(Path.cwd())
        _append_base(Path(__file__).resolve().parent)

        seen = set()
        for base in candidate_bases:
            try:
                key = str(base.resolve())
            except Exception:
                key = str(base)
            if key in seen:
                continue
            seen.add(key)

            candidate = base / raw
            if candidate.exists():
                try:
                    return str(candidate.resolve())
                except Exception:
                    return str(candidate)

        return original

    def _resolve_voice_selection(self, storyboard: dict, selected_voice=None, voice_id=None):
        """
        Resuelve voz efectiva evitando caer en IDs vacíos que terminan en voz incorrecta.
        Prioridad:
        1) Voz seleccionada en UI (si tiene id).
        2) Voz guardada en storyboard.
        3) Primera voz disponible.
        4) gTTS fallback.
        """
        voices_map = getattr(self.studio_tab, 'elevenlabs_voices', {}) or {}

        if selected_voice is None and hasattr(self.studio_tab, 'voice_combo'):
            try:
                selected_voice = (self.studio_tab.voice_combo.currentText() or "").strip()
            except Exception:
                selected_voice = ""

        if selected_voice == "Cargando voces...":
            selected_voice = ""

        if voice_id is None and selected_voice and isinstance(voices_map, dict):
            voice_info = voices_map.get(selected_voice, {})
            if isinstance(voice_info, dict):
                voice_id = voice_info.get('id')

        # Compatibilidad: si el combo retorna directamente un id.
        if not voice_id and selected_voice:
            if selected_voice.startswith("gtts_") or ("Neural" in selected_voice) or len(selected_voice) >= 20:
                voice_id = selected_voice

        storyboard_voice_id = storyboard.get('voice_id') if isinstance(storyboard, dict) else None
        storyboard_voice_name = storyboard.get('voice_name') if isinstance(storyboard, dict) else None

        if not voice_id and storyboard_voice_id:
            return storyboard_voice_name or selected_voice or "Storyboard Voice", storyboard_voice_id, "storyboard"

        if not voice_id and isinstance(voices_map, dict):
            for name, info in voices_map.items():
                if isinstance(info, dict) and info.get('id'):
                    return name, info.get('id'), "first_available"

        if not voice_id:
            return selected_voice or storyboard_voice_name or "gTTS (Español)", "gtts_fallback", "fallback"

        return selected_voice or storyboard_voice_name or "Selected Voice", voice_id, "selected"

    def _extract_segment_text(self, segment: dict) -> str:
        """Obtiene texto narrativo canónico de un segmento."""
        if not isinstance(segment, dict):
            return ""

        for key in ("text", "narration_text", "narration"):
            raw = segment.get(key, "")
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                return text
        return ""

    def _normalize_storyboard_segments_for_narration(self, storyboard: dict):
        """
        Normaliza texto y tiempos de segmentos para mantener coherencia entre
        edición de timeline, regeneración de audio y subtítulos.
        """
        segments = storyboard.get('segments', []) if isinstance(storyboard, dict) else []
        normalized_segments = []

        for index, segment in enumerate(segments):
            normalized = segment.copy() if isinstance(segment, dict) else {}

            text = self._extract_segment_text(normalized)
            normalized['text'] = text
            normalized['narration_text'] = text

            start = self._safe_float(
                normalized.get('start', normalized.get('start_time', 0.0)),
                0.0
            )
            raw_end = normalized.get('end', normalized.get('end_time'))
            if raw_end is None:
                duration = self._safe_float(normalized.get('duration', 5.0), 5.0)
                end = start + max(duration, 0.0)
            else:
                end = self._safe_float(raw_end, start)

            if end < start:
                end = start

            duration = max(end - start, 0.0)

            normalized['start'] = start
            normalized['end'] = end
            normalized['start_time'] = start
            normalized['end_time'] = end
            normalized['timestamp_start'] = start
            normalized['timestamp_end'] = end
            normalized['duration'] = duration
            normalized['segment_id'] = index + 1

            if not normalized.get('assigned_filename'):
                normalized['assigned_filename'] = f"segment_{index + 1:03d}"

            normalized_segments.append(normalized)

        if isinstance(storyboard, dict):
            storyboard['segments'] = normalized_segments

        return normalized_segments

    def _build_script_from_segments(self, segments) -> str:
        """Construye script completo desde textos de segmentos."""
        parts = []
        for segment in segments or []:
            text = self._extract_segment_text(segment)
            if text:
                parts.append(text)
        return " ".join(parts).strip()

    def _compute_narrative_signature(self, segments) -> str:
        """Calcula una firma estable de la narrativa (texto + tiempos)."""
        payload = []
        for index, segment in enumerate(segments or []):
            payload.append({
                'index': index,
                'text': self._extract_segment_text(segment),
                'start': round(self._safe_float(segment.get('start', 0.0), 0.0), 3),
                'end': round(self._safe_float(segment.get('end', 0.0), 0.0), 3),
            })

        source = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha1(source.encode('utf-8')).hexdigest()

    def _probe_audio_duration_seconds(self, audio_path: str) -> float:
        """Obtiene duración de audio en segundos (ffprobe -> pydub fallback)."""
        if not audio_path or not os.path.exists(audio_path):
            return 0.0

        # Intento 1: ffprobe
        try:
            ffprobe_cmd = "ffprobe"
            try:
                from video_config import VideoConfig
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

            cmd = [
                ffprobe_cmd,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode == 0 and result.stdout.strip():
                value = float(result.stdout.strip())
                if value > 0:
                    return value
        except Exception:
            pass

        # Intento 2: pydub
        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(audio_path)
            return max(0.0, len(seg) / 1000.0)
        except Exception:
            return 0.0

    def _rescale_segments_to_audio_duration(self, segments, audio_duration: float) -> bool:
        """
        Reescala start/end de segmentos para coincidir con duración real del audio.
        Retorna True si aplicó cambios.
        """
        if not segments or audio_duration <= 0:
            return False

        durations = []
        starts = []
        ends = []
        for seg in segments:
            start = self._safe_float(seg.get('start', seg.get('start_time', 0.0)), 0.0)
            end = self._safe_float(seg.get('end', seg.get('end_time', start)), start)
            starts.append(start)
            ends.append(end)
            durations.append(max(0.05, end - start))

        base_total = sum(durations)
        if base_total <= 0:
            return False

        timeline_span = max(0.0, (max(ends) - min(starts))) if starts and ends else base_total
        timing_gap = max(0.0, timeline_span - base_total)
        ratio = audio_duration / base_total

        # Evitar tocar timings cuando el ajuste es despreciable.
        # Si hay huecos grandes entre segmentos, forzar normalización aunque la suma de
        # duraciones parezca cercana al audio (evita desfase progresivo en subtítulos).
        negligible_delta = abs(base_total - audio_duration) < 1.0
        negligible_ratio = abs(ratio - 1.0) < 0.03
        small_gap = timing_gap < max(1.0, audio_duration * 0.01)
        if negligible_delta and negligible_ratio and small_gap:
            return False

        current = 0.0
        for idx, seg in enumerate(segments):
            new_duration = max(0.05, durations[idx] * ratio)
            start = current
            end = start + new_duration

            seg['start'] = start
            seg['end'] = end
            seg['start_time'] = start
            seg['end_time'] = end
            seg['timestamp_start'] = start
            seg['timestamp_end'] = end
            seg['duration'] = new_duration
            current = end

        # Ajustar último segmento al exacto de audio para evitar drift.
        if segments:
            tail = segments[-1]
            tail_start = self._safe_float(tail.get('start', 0.0), 0.0)
            tail_end = max(tail_start, audio_duration)
            tail['end'] = tail_end
            tail['end_time'] = tail_end
            tail['timestamp_end'] = tail_end
            tail['duration'] = max(0.05, tail_end - tail_start)

        return True

    def _segments_total_duration(self, segments) -> float:
        """Duración total aproximada; considera también huecos del timeline."""
        if not segments:
            return 0.0
        total = 0.0
        min_start = None
        max_end = 0.0
        for seg in segments:
            start = self._safe_float(seg.get('start', seg.get('start_time', 0.0)), 0.0)
            end = self._safe_float(seg.get('end', seg.get('end_time', start)), start)
            total += max(0.0, end - start)
            if min_start is None or start < min_start:
                min_start = start
            if end > max_end:
                max_end = end

        if min_start is None:
            return total

        timeline_span = max(0.0, max_end - min_start)
        return max(total, timeline_span)

    def _prepare_storyboard_for_audio_sync(self, storyboard: dict) -> bool:
        """
        Sincroniza script/firma del storyboard y determina si hay que regenerar audio.

        Returns:
            bool: True si hay que regenerar audio para mantener sincronía.
        """
        if not isinstance(storyboard, dict):
            return False

        segments = self._normalize_storyboard_segments_for_narration(storyboard)
        if not segments:
            return False

        # Mantener script en línea con los segmentos editados.
        script_from_segments = self._build_script_from_segments(segments)
        if script_from_segments and storyboard.get('script', '').strip() != script_from_segments:
            storyboard['script'] = script_from_segments

        previous_signature = storyboard.get('segments_narrative_signature')
        current_signature = self._compute_narrative_signature(segments)
        storyboard['segments_narrative_signature'] = current_signature

        explicit_pending = bool(
            storyboard.get('audio_needs_regeneration') or
            storyboard.get('subtitles_need_regeneration')
        )

        # Si hay firma previa y cambió, la narrativa cambió.
        signature_changed = bool(previous_signature and previous_signature != current_signature)

        # Compatibilidad: si existe firma sincronizada y ya no coincide.
        synced_signature = storyboard.get('audio_synced_signature')
        synced_mismatch = bool(synced_signature and synced_signature != current_signature)
        missing_sync_baseline = bool(storyboard.get('audio_path') and not synced_signature)

        needs_regeneration = explicit_pending or signature_changed or synced_mismatch or missing_sync_baseline

        if needs_regeneration:
            storyboard['audio_needs_regeneration'] = True
            storyboard['subtitles_need_regeneration'] = True
            storyboard['audio_sync_status'] = 'pending'
            if not storyboard.get('audio_sync_reason'):
                storyboard['audio_sync_reason'] = "segment_narrative_changed"
            storyboard['audio_sync_requested_at'] = datetime.now(timezone.utc).isoformat()

        return needs_regeneration

    def regenerate_storyboard_audio_sync(self, storyboard_data=None, voice_id=None, selected_voice=None, force=True) -> bool:
        """
        Regenera audio/subtÃ­tulos del storyboard para mantener sincronÃ­a con segmentos editados.

        Args:
            storyboard_data: Storyboard a sincronizar. Si es None, usa last_storyboard_data.
            voice_id: Voice ID opcional. Si es None, usa la voz seleccionada en UI.
            selected_voice: Nombre de voz opcional para metadatos.
            force: Si True, fuerza regeneraciÃ³n aunque no detecte cambios.

        Returns:
            bool: True si la regeneraciÃ³n fue exitosa.
        """
        storyboard = storyboard_data if isinstance(storyboard_data, dict) else self.studio_tab.last_storyboard_data
        if not isinstance(storyboard, dict):
            return False

        audio_sync_pending = self._prepare_storyboard_for_audio_sync(storyboard)

        selected_voice, voice_id, voice_source = self._resolve_voice_selection(
            storyboard,
            selected_voice=selected_voice,
            voice_id=voice_id
        )
        if voice_source in ("storyboard", "fallback"):
            self.studio_tab.log(f"️ Resolución de voz: {voice_source} -> {selected_voice} ({voice_id})")

        storyboard['voice_id'] = voice_id
        storyboard['voice_name'] = selected_voice

        must_regenerate = force or audio_sync_pending
        if not must_regenerate:
            return True

        return self._regenerate_audio(storyboard, voice_id, selected_voice)

    def _sync_open_timeline_editor_state(self):
        """
        Fuerza sincronizaciÃ³n del estado actual del Timeline Editor abierto
        (incluyendo posibles cambios no persistidos del segmento en ediciÃ³n)
        hacia last_storyboard_data antes de ensamblar.
        """
        timeline_editor = None
        try:
            if hasattr(self.studio_tab, 'timeline_editor_window') and self.studio_tab.timeline_editor_window:
                win = self.studio_tab.timeline_editor_window
                if hasattr(win, 'timeline_editor') and win.timeline_editor:
                    timeline_editor = win.timeline_editor

            if timeline_editor is None and hasattr(self.studio_tab, 'timeline_editor'):
                timeline_editor = self.studio_tab.timeline_editor
        except Exception:
            timeline_editor = None

        if not timeline_editor or not hasattr(timeline_editor, 'segments'):
            return

        # Guardar segmento activo del panel derecho si estÃ¡ en ediciÃ³n.
        try:
            if hasattr(timeline_editor, 'segment_editor') and timeline_editor.segment_editor:
                if timeline_editor.segment_editor.current_segment:
                    committed = False
                    if hasattr(timeline_editor, 'commit_active_segment_edits'):
                        committed = bool(timeline_editor.commit_active_segment_edits())
                    if not committed:
                        timeline_editor.segment_editor.save_changes()
        except Exception:
            pass

        segments = timeline_editor.segments if isinstance(timeline_editor.segments, list) else []
        if not segments:
            return

        if not isinstance(self.studio_tab.last_storyboard_data, dict):
            self.studio_tab.last_storyboard_data = {}

        storyboard = self.studio_tab.last_storyboard_data
        normalized_segments = self._normalize_storyboard_segments_for_narration({'segments': segments})
        current_signature = self._compute_narrative_signature(normalized_segments)
        previous_signature = storyboard.get('segments_narrative_signature')

        storyboard['segments'] = [seg.copy() for seg in normalized_segments]
        storyboard['segments_narrative_signature'] = current_signature

        script_from_segments = self._build_script_from_segments(normalized_segments)
        if script_from_segments:
            storyboard['script'] = script_from_segments

        synced_signature = storyboard.get('audio_synced_signature')
        has_audio = bool(storyboard.get('audio_path'))
        if (
            (previous_signature and previous_signature != current_signature) or
            (has_audio and (not synced_signature or synced_signature != current_signature))
        ):
            storyboard['audio_needs_regeneration'] = True
            storyboard['subtitles_need_regeneration'] = True
            storyboard['audio_sync_status'] = 'pending'
            storyboard['audio_sync_reason'] = 'segment_narrative_changed'
            storyboard['audio_sync_requested_at'] = datetime.now(timezone.utc).isoformat()

    def _stop_background_media_players(self):
        """Detiene reproductores VLC/Qt en segundo plano para evitar access violations nativas."""
        # OPTIMIZACIÓN: Usar findChildren de Qt en lugar de gc.get_objects().
        # gc.get_objects() escanea TODOS los objetos Python en memoria — extremadamente
        # lento en aplicaciones grandes (5-30s). findChildren busca solo en el árbol
        # de widgets Qt y es prácticamente instantáneo.
        try:
            from music_browser_dialog import MusicBrowserDialog
            for dialog in self.studio_tab.findChildren(MusicBrowserDialog):
                try:
                    if hasattr(dialog, '_vlc_player') and dialog._vlc_player:
                        dialog._vlc_player.stop()
                    if hasattr(dialog, '_qt_player') and dialog._qt_player:
                        dialog._qt_player.stop()
                    if hasattr(dialog, 'music_timer') and dialog.music_timer:
                        dialog.music_timer.stop()
                    if hasattr(dialog, '_ffplay_process') and dialog._ffplay_process:
                        try:
                            dialog._ffplay_process.terminate()
                        except Exception:
                            pass
                except Exception:
                    continue
        except Exception:
            pass

    def assemble_video(self):
        """Ensambla el video (Paso 2)"""
        # Detener reproductores multimedia en segundo plano para evitar
        # access violations nativas (VLC) durante el ensamblaje FFmpeg.
        self._stop_background_media_players()

        # Capturar últimos cambios del Timeline Editor antes de cualquier decisión.
        self._sync_open_timeline_editor_state()

        # Preflight ligero: el estado del timeline ya fue sincronizado por
        # _sync_open_timeline_editor_state() arriba. El auto-guardado completo
        # (con copia de media) se difiere a después del ensamblado para evitar
        # I/O pesado que bloquea la UI durante varios segundos/minutos.
        try:
            if hasattr(self.studio_tab, 'project_manager') and self.studio_tab.project_manager:
                self.studio_tab.log("️ Preflight: timeline sincronizado, auto-guardado diferido a post-ensamblado")
        except Exception as e:
            self.studio_tab.log(f"️ Preflight: {e}")

        if not self.studio_tab.last_storyboard_data:
            QMessageBox.warning(self, "Sin Storyboard",
                              "Primero genera el storyboard (Paso 1)")
            return

        # Los segmentos ya están actualizados en last_storyboard_data
        # gracias a on_timeline_modified()
        modified_storyboard = self.studio_tab.last_storyboard_data
        # Hint de proyecto para resolver rutas relativas (project_media/...) durante ensamblaje.
        if hasattr(self.studio_tab, 'current_project_path') and self.studio_tab.current_project_path:
            modified_storyboard['_project_path'] = self.studio_tab.current_project_path
        resolved_audio_path = self._resolve_storyboard_media_path(
            modified_storyboard.get('audio_path'),
            modified_storyboard
        )
        if resolved_audio_path and resolved_audio_path != modified_storyboard.get('audio_path'):
            modified_storyboard['audio_path'] = resolved_audio_path
            self.studio_tab.log(f" Audio resuelto: {resolved_audio_path}")

        # Asegurar coherencia narrativa (segmentos -> script/firma) antes de decidir el audio.
        audio_sync_pending = self._prepare_storyboard_for_audio_sync(modified_storyboard)
        if audio_sync_pending:
            self.studio_tab.log(" Cambios narrativos detectados en segmentos: se regenerará audio para mantener sincronía de subtítulos.")

        # Si ya existe audio pero los timings están claramente fuera de rango,
        # ajustar segmentos sin necesidad de regenerar voz.
        if not audio_sync_pending:
            existing_audio = self._resolve_storyboard_media_path(
                modified_storyboard.get('audio_path'),
                modified_storyboard
            )
            if existing_audio and existing_audio != modified_storyboard.get('audio_path'):
                modified_storyboard['audio_path'] = existing_audio
            if existing_audio and os.path.exists(existing_audio):
                segments_for_check = modified_storyboard.get('segments', [])
                audio_duration = self._probe_audio_duration_seconds(existing_audio)
                segments_duration = self._segments_total_duration(segments_for_check)
                if audio_duration > 0 and segments_duration > 0 and abs(audio_duration - segments_duration) > 3.0:
                    if self._rescale_segments_to_audio_duration(segments_for_check, audio_duration):
                        timing_signature = self._compute_narrative_signature(segments_for_check)
                        sync_done_at = datetime.now(timezone.utc).isoformat()
                        modified_storyboard['segments_narrative_signature'] = timing_signature
                        modified_storyboard['audio_synced_signature'] = timing_signature
                        modified_storyboard['audio_needs_regeneration'] = False
                        modified_storyboard['subtitles_need_regeneration'] = False
                        modified_storyboard['audio_sync_status'] = 'synced'
                        modified_storyboard['audio_sync_reason'] = 'timing_rescaled_to_audio'
                        modified_storyboard['audio_sync_completed_at'] = sync_done_at
                        self.studio_tab.log(
                            f" Ajuste automático de timing: segmentos {segments_duration:.1f}s -> "
                            f"audio {audio_duration:.1f}s"
                        )

        # Resolver voz efectiva (UI -> storyboard -> fallback)
        selected_voice, voice_id, voice_source = self._resolve_voice_selection(modified_storyboard)
        if voice_source in ("storyboard", "fallback"):
            self.studio_tab.log(f"️ Resolución de voz: {voice_source} -> {selected_voice} ({voice_id})")
        
        # Verificar si la voz cambió o si el storyboard no tiene voz asociada
        storyboard_voice_id = modified_storyboard.get('voice_id')
        storyboard_voice_name = modified_storyboard.get('voice_name')
        # Solo marcar voz como desconocida si además no hay audio válido existente.
        # Esto evita regeneraciones TTS innecesarias (10-60s) en proyectos con audio
        # válido pero sin metadata de voz completa.
        _existing_audio = self._resolve_storyboard_media_path(
            modified_storyboard.get('audio_path', ''), modified_storyboard
        )
        _has_valid_audio = bool(_existing_audio and os.path.exists(_existing_audio))
        voice_unknown = (not storyboard_voice_id or not storyboard_voice_name) and not _has_valid_audio
        # Solo comparar IDs de voz (los nombres pueden tener diferencias cosméticas)
        voice_mismatch = bool(storyboard_voice_id and voice_id and storyboard_voice_id != voice_id)
        
        # Regenerar si: no hay voz y no hay audio válido, o si el ID de voz realmente cambió
        voice_regen_required = bool(voice_id and (voice_unknown or voice_mismatch))
        if voice_regen_required:
            if voice_unknown:
                self.studio_tab.log(f"️ Voz del proyecto no definida en el storyboard; regenerando audio con: {selected_voice}")
            else:
                self.studio_tab.log(f"️ Voz seleccionada: {selected_voice} ({voice_id})")
            
            # Actualizar voice_id en el storyboard
            modified_storyboard['voice_id'] = voice_id
            modified_storyboard['voice_name'] = selected_voice
            
        elif voice_id:
            # La voz no cambió, pero asegurémonos de que esté en el storyboard
            if not storyboard_voice_id:
                modified_storyboard['voice_id'] = voice_id
                modified_storyboard['voice_name'] = selected_voice
            self.studio_tab.log(f"️ Usando voz: {selected_voice} ({voice_id})")
        else:
            self.studio_tab.log(f"️ No se pudo obtener voice_id de la voz seleccionada: {selected_voice}")

        # Regeneración por cambios narrativos o por cambio de voz.
        must_regenerate_audio = voice_regen_required or audio_sync_pending
        if must_regenerate_audio:
            if not voice_id:
                selected_voice, voice_id, _ = self._resolve_voice_selection(modified_storyboard)
                modified_storyboard['voice_id'] = voice_id
                modified_storyboard['voice_name'] = selected_voice

            regen_ok = self._regenerate_audio(modified_storyboard, voice_id, selected_voice)
            if not regen_ok and audio_sync_pending:
                self.studio_tab.log(" No se pudo resincronizar audio/subtítulos con los segmentos editados.")
                QMessageBox.critical(
                    self.studio_tab,
                    "Audio Fuera de Sincronía",
                    "No se pudo regenerar el audio con los cambios del Timeline Editor.\n"
                    "Corrige el texto/voz y vuelve a intentar ensamblar."
                )
                return

        # Verificar si falta el audio y regenerarlo automáticamente
        current_audio_path = self._resolve_storyboard_media_path(
            modified_storyboard.get('audio_path'),
            modified_storyboard
        )
        if current_audio_path and current_audio_path != modified_storyboard.get('audio_path'):
            modified_storyboard['audio_path'] = current_audio_path

        if not current_audio_path or not os.path.exists(current_audio_path):
            self.studio_tab.log("️ Audio no encontrado o inválido. Intentando regenerar...")
            
            # Intentar obtener voz por defecto si no hay
            if not voice_id:
                 selected_voice, voice_id, _ = self._resolve_voice_selection(modified_storyboard)
                 
            regen_ok = self._regenerate_audio(modified_storyboard, voice_id, selected_voice)
            
            current_audio_path = self._resolve_storyboard_media_path(
                modified_storyboard.get('audio_path'),
                modified_storyboard
            )
            if current_audio_path and current_audio_path != modified_storyboard.get('audio_path'):
                modified_storyboard['audio_path'] = current_audio_path

            if (not regen_ok or
                not current_audio_path or
                not os.path.exists(current_audio_path)):
                self.studio_tab.log(" Error crítico: No se pudo generar el audio para el video.")
                QMessageBox.critical(self.studio_tab, "Error de Audio", 
                                   "No se encontró el archivo de audio y falló la regeneración automática.\n"
                                   "Por favor intenta regenerar el Storyboard (Paso 1).")
                return

        # Obtener configuración
        output_profiles = (
            self.studio_tab.get_selected_output_profiles()
            if hasattr(self.studio_tab, 'get_selected_output_profiles')
            else [{
                'video_format': (
                    self.studio_tab.get_selected_video_format()
                    if hasattr(self.studio_tab, 'get_selected_video_format')
                    else '16:9'
                ),
                'platform': (
                    self.studio_tab.get_selected_platform_key()
                    if hasattr(self.studio_tab, 'get_selected_platform_key')
                    else self.studio_tab.platform_combo.currentText()
                ),
                'resolution': (
                    self.studio_tab.get_selected_resolution()
                    if hasattr(self.studio_tab, 'get_selected_resolution')
                    else (1920, 1080)
                )
            }]
        )
        output_profiles = [p for p in output_profiles if isinstance(p, dict)]
        if not output_profiles:
            output_profiles = [{'video_format': '16:9', 'platform': 'youtube', 'resolution': (1920, 1080)}]

        format_targets = [p.get('video_format', '16:9') for p in output_profiles]
        platform_targets = [p.get('platform', 'youtube') for p in output_profiles]
        primary_platform = platform_targets[0] if platform_targets else 'youtube'
        video_format = "+".join(format_targets)
        resolution = output_profiles[0].get('resolution', (1920, 1080))
        is_multi_format = len(platform_targets) > 1

        add_subtitles = self.studio_tab.subtitles_check.isChecked()
        add_overlays = False  # Overlays deshabilitados

        visual_mode = 'static' if self.studio_tab.visual_static.isChecked() else 'mixed'

        # Obtener estilo de subtítulos dinámicos
        subtitle_style_display = self.studio_tab.get_subtitle_style_name()
        subtitle_style = subtitle_style_display
        try:
            from dynamic_subtitle_wrapper import normalize_subtitle_style
            subtitle_style = normalize_subtitle_style(subtitle_style_display)
        except Exception:
            pass

        self.studio_tab.log(
            f" Estilo de subtítulos: {subtitle_style_display} -> {subtitle_style}")

        requires_precise_subtitle_sync = self._requires_precise_subtitle_sync(
            platform_targets,
            add_subtitles
        )
        if not self._ensure_precise_subtitle_sync_ready(platform_targets, add_subtitles):
            return

        if requires_precise_subtitle_sync:
            modified_storyboard['_require_precise_subtitle_sync'] = True
            modified_storyboard['_force_whisper_subtitles'] = True
        else:
            modified_storyboard.pop('_require_precise_subtitle_sync', None)
            modified_storyboard.pop('_force_whisper_subtitles', None)

        # Aplicar patch de subtítulos dinámicos si están activados
        if add_subtitles:
            try:
                from dynamic_subtitle_wrapper import patch_subtitle_generation
                patch_subtitle_generation(self.studio_tab.generator, subtitle_style)
                self.studio_tab.log(
                    f" Subtítulos dinámicos activados (estilo: {subtitle_style})")
            except Exception as e:
                self.studio_tab.log(f" No se pudo activar subtítulos dinámicos: {e}")
                self.studio_tab.log(f"   ADVERTENCIA: Es posible que el video se genere SIN subtítulos")

        # Deshabilitar botones
        self.studio_tab.btn_storyboard.setEnabled(False)
        self.studio_tab.btn_assemble.setEnabled(False)
        if hasattr(self.studio_tab, 'btn_play_video'):
            self.studio_tab.btn_play_video.setEnabled(False)
        if hasattr(self.studio_tab, 'btn_publish'):
            self.studio_tab.btn_publish.setEnabled(False)
        self.studio_tab._show_progress_indicator()

        # Short teaser se genera desde el botón en "Pipeline de Generación"
        generate_short_teaser = False

        # Obtener configuración de fuentes de imágenes
        # Openverse y Wikimedia ahora son manuales (desde Timeline Editor)
        enable_real_images_mix = self.studio_tab.enable_real_images_mix_check.isChecked(
        ) if hasattr(self.studio_tab, 'enable_real_images_mix_check') else False
        use_google_images = False  # Manual desde Timeline Editor
        use_wikimedia = False  # Manual desde Timeline Editor
        use_real_images = False  # No usar Pexels/Pixabay
        disable_wikimedia = False  # No deshabilitar Wikimedia
        
        self.studio_tab.log(f"   ️ Imágenes: Manual (usa botones  y  en Timeline Editor)")
        self.studio_tab.log(f"    IA Generativa: SÍ (proveedor seleccionado)")

        # Obtener proveedor de imágenes seleccionado
        image_provider_text = self.studio_tab.image_provider_combo.currentText(
        ) if hasattr(self.studio_tab, 'image_provider_combo') else "Recraft AI"

        # Mapear texto del combo a valor del proveedor
        image_provider_map = {
            "Recraft AI": "recraft",
            "FAL - Flux dev (calidad)": "flux_dev",
            "FAL - Flux schnell (rapido)": "flux_schnell",
            "ComfyUI - FLUX Dev (alta calidad)": "comfy_dev",
            "ComfyUI - FLUX Schnell": "comfy_schnell",
            "Fal.ai (FLUX.1 schnell)": "flux_schnell",     # legacy/compat
            "Fal.ai (FLUX.1 schnell) âš¡": "flux_schnell",  # legacy/compat
            "Google AI (Gemini API)": "google_ai",
            "Manual (Gratuito)": "manual",
            "Manual (Gratuito) - Gemini Veo/Copilot/etc.": "manual"
        }
        image_provider_value = image_provider_map.get(
            image_provider_text, "recraft")

        # Proveedor de video opcional (I2V con FAL Kling/Luma o Runway).
        video_provider_value = "none"
        fal_video_model = None
        try:
            if hasattr(self.studio_tab, '_normalize_video_provider_key'):
                video_provider_value, fal_video_model = self.studio_tab._normalize_video_provider_key()
            else:
                # Fallback: leer del storyboard si la pipeline anterior lo dejo grabado.
                vp = modified_storyboard.get('video_pipeline') if isinstance(modified_storyboard, dict) else None
                if isinstance(vp, dict):
                    video_provider_value = str(vp.get('video_provider') or 'none').lower()
                    fal_video_model = vp.get('fal_video_model')
        except Exception as exc:
            self.studio_tab.log(f"    Video provider: fallback a 'none' ({exc})")
            video_provider_value, fal_video_model = ("none", None)

        self.studio_tab.log(f"\n{'='*50}")
        self.studio_tab.log(f" PASO 2: ENSAMBLANDO VIDEO")
        if is_multi_format:
            self.studio_tab.log(f"   Formatos: {', '.join(format_targets)}")
            self.studio_tab.log(f"   Plataformas internas: {', '.join(platform_targets)}")
            self.studio_tab.log(
                f"   Assets base: {output_profiles[0].get('video_format', '16:9')} "
                f"({resolution[0]}x{resolution[1]})"
            )
        else:
            self.studio_tab.log(f"   Formato: {video_format} ({resolution[0]}x{resolution[1]})")
            self.studio_tab.log(f"   Motor interno: {primary_platform}")
        self.studio_tab.log(f"   Modo Visual: {visual_mode.upper()}")
        self.studio_tab.log(f"   Proveedor IA: {image_provider_text}")
        if video_provider_value and video_provider_value != 'none':
            modelo_str = f" ({fal_video_model})" if fal_video_model else ""
            self.studio_tab.log(
                f"    Proveedor VIDEO: {video_provider_value}{modelo_str} (I2V por segmento)"
            )
        else:
            self.studio_tab.log(f"    Proveedor VIDEO: ninguno (imagen estatica + Ken Burns)")
        self.studio_tab.log(
            f"   Subtítulos: {'SÍ (' + subtitle_style_display + ' -> ' + subtitle_style + ')' if add_subtitles else 'NO'}")
        if use_wikimedia:
            self.studio_tab.log(f"    Wikimedia: SÍ (priorizar imágenes reales)")
        if generate_short_teaser:
            self.studio_tab.log(f"    Short Teaser: SÍ (se generará en paralelo)")
        self.studio_tab.log(f"{'='*50}\n")

        # Asegurarse de que el thread anterior termine antes de crear uno nuevo
        if self.studio_tab.current_thread and self.studio_tab.current_thread.isRunning():
            self.studio_tab.log(" Esperando que termine el proceso anterior...")
            self.studio_tab.current_thread.quit()
            if not self.studio_tab.current_thread.wait(5000):  # Esperar máximo 5 segundos
                self.studio_tab.log("️ Forzando terminación del thread anterior...")
                self.studio_tab.current_thread.terminate()
                self.studio_tab.current_thread.wait()

        # Crear worker
        worker_operation = "assemble_multi" if is_multi_format else "assemble"
        self.studio_tab.current_worker = VideoGenerationWorker(self.studio_tab.generator, worker_operation)
        worker_params = dict(
            storyboard_data=modified_storyboard,
            add_subtitles=add_subtitles,
            subtitle_style=subtitle_style,  #  Pasar estilo canónico
            add_overlays=add_overlays,
            manual_bgm_paths=getattr(self.studio_tab, 'selected_music_paths', None) or (
                [self.studio_tab.selected_music_path]
                if getattr(self.studio_tab, 'selected_music_path', None) else None
            ),
            manual_bgm_path=self.studio_tab.selected_music_path if hasattr(
                self.studio_tab, 'selected_music_path'
            ) and self.studio_tab.selected_music_path else None,
            manual_bgm_metadata=self.studio_tab.selected_music_metadata if hasattr(
                self.studio_tab, 'selected_music_metadata'
            ) and self.studio_tab.selected_music_metadata else None,
            assembly_mode='auto',
            visual_mode=visual_mode,
            apply_cinematic=self.studio_tab.cinematic_check.isChecked(),
            cinematic_preset=self.studio_tab.cinematic_preset_combo.currentText().lower(),
            transition_type=self.studio_tab.transition_type_combo.currentText(),
            transition_duration=self.studio_tab.transition_duration_spin.value(),
            generate_short_teaser=generate_short_teaser,
            use_wikimedia=use_wikimedia,  #  Nuevo parámetro para Wikimedia
            disable_wikimedia=disable_wikimedia,  #  Desactivar completamente Wikimedia
            use_real_images=use_real_images,  #  Usar imágenes reales de stock
            #  Usar Openverse (compatibilidad legacy)
            use_google_images=use_google_images,
            #  Mezcla inteligente (nuevo)
            enable_real_images_mix=enable_real_images_mix,
            image_provider=image_provider_value,  #  Proveedor de IA seleccionado
            video_provider=video_provider_value,  #  Proveedor de video (I2V) opcional
            fal_video_model=fal_video_model,      #  kling / kling-pro / luma
            allow_visual_regeneration=False  #  No regenerar IA al ensamblar
        )
        if is_multi_format:
            worker_params['platforms'] = platform_targets
        else:
            worker_params['platform'] = primary_platform
        self.studio_tab.current_worker.set_params(**worker_params)
        if hasattr(self.studio_tab, '_bind_current_worker_to_project'):
            self.studio_tab._bind_current_worker_to_project()

        # Asegurarse de que el thread anterior termine antes de crear uno nuevo
        if self.studio_tab.current_thread and self.studio_tab.current_thread.isRunning():
            self.studio_tab.log(" Esperando que termine el proceso anterior...")
            self.studio_tab.current_thread.quit()
            if not self.studio_tab.current_thread.wait(5000):  # Esperar máximo 5 segundos
                self.studio_tab.log("️ Forzando terminación del thread anterior...")
                self.studio_tab.current_thread.terminate()
                self.studio_tab.current_thread.wait()

        # Conectar señales (los callbacks se mantienen como delegaciones en AutoVideoStudioTab)
        self.studio_tab.current_worker.finished.connect(self.studio_tab.on_assemble_finished)
        self.studio_tab.current_worker.error.connect(self.studio_tab.on_assemble_error)
        self.studio_tab.current_worker.progress.connect(self.studio_tab.log)

        # Ejecutar en thread
        self.studio_tab.current_thread = QThread()
        self.studio_tab.current_worker.moveToThread(self.studio_tab.current_thread)
        self.studio_tab.current_thread.started.connect(self.studio_tab.current_worker.run)
        self.studio_tab.current_thread.start()


    def _regenerate_audio(self, modified_storyboard, voice_id, selected_voice):
        """Regenera el audio del storyboard."""
        self.studio_tab.log("Regenerando audio con la voz seleccionada...")
        try:
            from tts_generator import TextToSpeechGenerator
            from video_config import VideoConfig
            import time

            # Re-normalizar segmentos y script para que TTS use texto actualizado.
            segments = self._normalize_storyboard_segments_for_narration(modified_storyboard)
            script_from_segments = self._build_script_from_segments(segments)
            script = script_from_segments or str(modified_storyboard.get('script', '')).strip()

            if not script:
                self.studio_tab.log("No hay script para generar audio")
                modified_storyboard['audio_sync_status'] = 'error'
                modified_storyboard['audio_sync_error_at'] = datetime.now(timezone.utc).isoformat()
                return False

            modified_storyboard['script'] = script

            tts = TextToSpeechGenerator()
            language = 'es' if self.studio_tab.lang_es.isChecked() else 'en'

            # Generar nuevo audio
            audio_filename = f"auto_{int(time.time())}.mp3"
            audio_path_str = str(VideoConfig.AUDIO_DIR / audio_filename)

            voice_rate = self.studio_tab.get_selected_voice_rate() if hasattr(self.studio_tab, 'get_selected_voice_rate') else "+0%"

            # --- Ejecutar TTS en hilo secundario para no congelar la UI ---
            # generate_narration() es una llamada API que puede tomar 10-60+ segundos.
            # Ejecutarla en el hilo principal bloquea completamente la interfaz.
            import threading
            from PyQt6.QtWidgets import QProgressDialog, QApplication
            from PyQt6.QtCore import Qt

            _tts_result = [None]
            _tts_error = [None]

            def _tts_worker():
                try:
                    _tts_result[0] = tts.generate_narration(
                        script,
                        audio_path_str,
                        voice_id,
                        language=language,
                        rate=voice_rate
                    )
                except Exception as e:
                    _tts_error[0] = e

            _progress = QProgressDialog(
                "Generando narración con la voz seleccionada...\n"
                "Esto puede tomar entre 10 y 60 segundos.",
                None, 0, 0, self.studio_tab
            )
            _progress.setWindowTitle("Generación de Audio")
            _progress.setWindowModality(Qt.WindowModality.WindowModal)
            _progress.setCancelButton(None)
            _progress.setMinimumDuration(0)
            _progress.show()
            QApplication.processEvents()

            _t = threading.Thread(target=_tts_worker, daemon=True)
            _t.start()
            while _t.is_alive():
                QApplication.processEvents()
                _t.join(timeout=0.05)
            _progress.close()

            if _tts_error[0]:
                raise _tts_error[0]
            new_audio_path = _tts_result[0]

            if new_audio_path and os.path.exists(new_audio_path):
                # Auto-velocidad solo para plataformas short-form: si excede 180s, acelerar con FFmpeg
                platform_key = self.studio_tab.get_selected_platform_key() if hasattr(self.studio_tab, 'get_selected_platform_key') else 'youtube'
                if self._is_short_form_platform(platform_key):
                    try:
                        gen = self.studio_tab.generator
                        sb_gen = getattr(getattr(gen, '_generator', gen), 'storyboard_generator', None)
                        if sb_gen and hasattr(sb_gen, '_enforce_max_audio_duration'):
                            new_audio_path, speed_factor = sb_gen._enforce_max_audio_duration(new_audio_path, 180.0)
                            if speed_factor > 1.0:
                                self.studio_tab.log(f"    Audio acelerado ×{speed_factor:.2f} para short-form vertical (máx 180s)")
                    except Exception as e:
                        self.studio_tab.log(f"   ️ Auto-velocidad no disponible: {e}")

                old_audio_path = modified_storyboard.get('audio_path')
                modified_storyboard['audio_path'] = new_audio_path
                modified_storyboard['voice_id'] = voice_id
                modified_storyboard['voice_name'] = selected_voice

                # Importante: si cambió velocidad de la voz, ajustar timings de segmentos
                # para mantener sincronía de subtítulos y ensamblado.
                audio_duration = self._probe_audio_duration_seconds(new_audio_path)
                if audio_duration > 0:
                    timings_updated = self._rescale_segments_to_audio_duration(segments, audio_duration)
                    if timings_updated:
                        self.studio_tab.log(
                            f" Tiempos de segmentos reescalados a duración de audio: "
                            f"{audio_duration:.1f}s (voz: {selected_voice})"
                        )
                    else:
                        self.studio_tab.log(
                            f"ℹ️ Duración de audio verificada ({audio_duration:.1f}s), "
                            f"sin cambios de timing necesarios"
                        )

                # Marcar estado de sincronizacion como completado.
                signature = self._compute_narrative_signature(segments)
                sync_done_at = datetime.now(timezone.utc).isoformat()
                modified_storyboard['segments_narrative_signature'] = signature
                modified_storyboard['audio_synced_signature'] = signature
                modified_storyboard['audio_needs_regeneration'] = False
                modified_storyboard['subtitles_need_regeneration'] = False
                modified_storyboard['audio_sync_status'] = 'synced'
                modified_storyboard['audio_sync_completed_at'] = sync_done_at

                # Actualizar last_storyboard_data tambien
                if self.studio_tab.last_storyboard_data is not None:
                    self.studio_tab.last_storyboard_data.update({
                        'segments': [seg.copy() for seg in segments],
                        'script': script,
                        'audio_path': new_audio_path,
                        'voice_id': voice_id,
                        'voice_name': selected_voice,
                        'segments_narrative_signature': signature,
                        'audio_synced_signature': signature,
                        'audio_needs_regeneration': False,
                        'subtitles_need_regeneration': False,
                        'audio_sync_status': 'synced',
                        'audio_sync_completed_at': sync_done_at
                    })

                self.studio_tab.log(f"Audio regenerado con la voz: {selected_voice}")
                self.studio_tab.log(f"   Nuevo audio: {os.path.basename(new_audio_path)}")

                if old_audio_path and old_audio_path != new_audio_path and os.path.exists(old_audio_path):
                    try:
                        self.studio_tab.log(f"   Audio anterior: {os.path.basename(old_audio_path)}")
                    except Exception:
                        pass

                return True

            self.studio_tab.log("No se pudo regenerar el audio. Usando audio existente.")
            modified_storyboard['audio_sync_status'] = 'error'
            modified_storyboard['audio_sync_error_at'] = datetime.now(timezone.utc).isoformat()
            return False
        except Exception as e:
            self.studio_tab.log(f"Error regenerando audio: {e}")
            modified_storyboard['audio_sync_status'] = 'error'
            modified_storyboard['audio_sync_error_at'] = datetime.now(timezone.utc).isoformat()
            import traceback
            traceback.print_exc()
            return False

    def on_assemble_finished(self, result):
        """Callback cuando el video está ensamblado"""
        self.studio_tab.log(f"\n PASO 2 COMPLETADO")

        video_path = result.get('video_path')
        video_paths_by_platform = result.get('video_paths_by_platform') or {}
        if (not video_path) and video_paths_by_platform:
            video_path = next((p for p in video_paths_by_platform.values() if p), None)
        if not video_path:
            # Si no hay ruta de video, algo falló en el ensamblaje
            self.studio_tab.log(" ERROR: No se pudo ensamblar el video (video_path es None).")
            QMessageBox.critical(
                self.studio_tab,
                "Error en Ensamblaje",
                "No se pudo ensamblar el video final.\n\n"
                "Revisa los logs para más detalles (posible error en MoviePy o en el audio)."
            )
            # Rehabilitar botones y limpiar thread
            self.studio_tab.btn_storyboard.setEnabled(True)
            self.studio_tab.btn_assemble.setEnabled(True)
            self.studio_tab._hide_progress_indicator()
            self.studio_tab.update_status("Error en ensamblaje de video")
            self.studio_tab.cleanup_thread()
            return

        self.studio_tab.log(f" Video guardado en: {video_path}")
        if video_paths_by_platform:
            for platform_name, path in video_paths_by_platform.items():
                if path:
                    self.studio_tab.log(f"   • {platform_name}: {path}")

        # Guardar referencia al video generado para poder generar teaser
        # después
        self.studio_tab.last_generated_video_data = result

        # Auto-guardar si está habilitado
        if self.studio_tab.auto_save_enabled:
            self.studio_tab.auto_save_project("Paso 2 completado (Video ensamblado)")

        # Cargar video en la pestaña de preview si está disponible
        try:
            # Acceder a la ventana principal a través del parent_gui
            parent_window = self.studio_tab.parent_gui if hasattr(
                self.studio_tab, 'parent_gui') else self.studio_tab.parent()
            if parent_window and hasattr(
    parent_window,
     'video_preview_tab') and parent_window.video_preview_tab:
                # Obtener información del audio y segmentos
                audio_path = None
                segments_data = []

                # Intentar obtener el audio del storyboard
                if self.studio_tab.last_storyboard_data:
                    audio_path = self._resolve_storyboard_media_path(
                        self.studio_tab.last_storyboard_data.get('audio_path'),
                        self.studio_tab.last_storyboard_data
                    )
                    segments_data = self.studio_tab.last_storyboard_data.get(
                        'segments', [])

                # IMPORTANTE: El video_path ya incluye los subtítulos quemados (si se aplicaron)
                # Los subtítulos dinámicos se queman en el video usando FFmpeg durante el ensamblaje
                # Por lo tanto, el preview mostrará el video exactamente como
                # se exportó, con subtítulos incluidos

                # Obtener información del teaser si está disponible
                teaser_video_path = result.get('teaser_video_path')
                teaser_audio_path = None
                teaser_segments = []

                if teaser_video_path:
                    # Intentar obtener los segmentos del teaser desde los metadatos del resultado
                    # El teaser se genera con su propio storyboard que incluye
                    # los segmentos
                    teaser_metadata = result.get('teaser_metadata', {})
                    if not teaser_metadata:
                        # Si no hay metadata, intentar desde el storyboard del teaser guardado
                        # El teaser tiene su propio storyboard con segmentos
                        pass

                    teaser_segments = teaser_metadata.get('segments', [])

                    # Si no hay segmentos en metadata, intentar obtenerlos del
                    # storyboard del teaser
                    if not teaser_segments and hasattr(
                        self.studio_tab, 'last_teaser_storyboard'):
                        teaser_segments = self.studio_tab.last_teaser_storyboard.get(
                            'segments', [])
                        teaser_audio_path = self.studio_tab.last_teaser_storyboard.get(
                            'audio_path')
                    elif teaser_segments and len(teaser_segments) > 0:
                        # El audio del teaser generalmente está en el primer
                        # segmento o en el storyboard
                        teaser_audio_path = teaser_segments[0].get(
                            'audio_path')
                        if not teaser_audio_path:
                            # Intentar desde metadata
                            teaser_audio_path = teaser_metadata.get(
                                'audio_path')

                # Cargar el video en el preview (incluyendo teaser si está
                # disponible)
                parent_window.video_preview_tab.load_video(
                    video_path=video_path,
                    audio_path=audio_path,
                    segments_data=segments_data,
                    teaser_video_path=teaser_video_path,
                    teaser_audio_path=teaser_audio_path,
                    teaser_segments=teaser_segments
                )

                # Cambiar a la pestaña de preview
                if hasattr(parent_window, 'tabs'):
                    for i in range(parent_window.tabs.count()):
                        if parent_window.tabs.tabText(
                            i) == " Preview del Video":
                            parent_window.tabs.setCurrentIndex(i)
                            break

                self.studio_tab.log(" Video cargado en la pestaña de Preview")
        except Exception as e:
            self.studio_tab.log(f"️ Error cargando video en preview: {e}")
            import traceback
            traceback.print_exc()

        # Registrar video en el sistema de registro
        try:
            from video_registry import VideoRegistry
            registry = VideoRegistry()

            # Obtener información del video
            platform = result.get('platform', 'youtube')
            video_type = 'short' if 'short' in platform else 'long'
            title = result.get('title') or self.studio_tab.last_storyboard_data.get(
    'topic', 'Video sin título') if self.studio_tab.last_storyboard_data else 'Video sin título'
            topic = result.get('topic') or (
    self.studio_tab.last_storyboard_data.get(
        'topic', '') if self.studio_tab.last_storyboard_data else '')
            category = result.get('category') or (
    self.studio_tab.last_storyboard_data.get(
        'category', '') if self.studio_tab.last_storyboard_data else '')
            duration = result.get('duration')
            resolution = result.get('resolution')
            language = result.get('language', 'es')

            # Registrar video principal
            # Guardar storyboard en metadatos para poder generar teasers
            # después
            metadata = {
                'subtitle_style': result.get('subtitle_style'),
                'has_subtitles': result.get('has_subtitles', False),
                'has_overlays': result.get('has_overlays', False),
            }

            # Guardar storyboard completo si está disponible
            if self.studio_tab.last_storyboard_data:
                metadata['script'] = self.studio_tab.last_storyboard_data.get(
                    'script', '')
                metadata['segments'] = self.studio_tab.last_storyboard_data.get(
                    'segments', [])

            video_id = registry.register_video(
                video_path=video_path,
                video_type=video_type,
                title=title,
                topic=topic,
                category=category,
                platform=platform,
                duration=duration,
                resolution=resolution,
                language=language,
                metadata=metadata
            )

            self.studio_tab.log(f" Video registrado con ID: {video_id}")

            # Registrar formatos alternos cuando se genera salida múltiple.
            if video_paths_by_platform:
                for alt_platform, alt_path in video_paths_by_platform.items():
                    if not alt_path or alt_path == video_path:
                        continue
                    try:
                        alt_video_type = 'short' if 'short' in str(alt_platform) else 'long'
                        alt_id = registry.register_video(
                            video_path=alt_path,
                            video_type=alt_video_type,
                            title=f"{title} [{alt_platform}]",
                            topic=topic,
                            category=category,
                            platform=alt_platform,
                            duration=duration,
                            resolution=resolution,
                            language=language,
                            parent_video_id=video_id,
                            relation_type='alternate_format',
                            metadata={
                                'alternate_of': video_id,
                                'source_platform': platform
                            }
                        )
                        self.studio_tab.log(f" Formato alterno registrado ({alt_platform}) con ID: {alt_id}")
                    except Exception as alt_error:
                        self.studio_tab.log(f"️ No se pudo registrar formato alterno {alt_platform}: {alt_error}")

            # Verificar si se generó un short teaser
            if 'teaser_video_path' in result:
                self.studio_tab.log(f"\n SHORT TEASER GENERADO")
                self.studio_tab.log(
                    f" Teaser guardado en: {result['teaser_video_path']}")

                # Registrar el teaser relacionado con el video largo
                teaser_id = registry.register_video(
                    video_path=result['teaser_video_path'],
                    video_type='teaser',
                    title=f"{title} - Teaser",
                    topic=topic,
                    category=category,
                    platform='youtube_short',
                    duration=result.get('teaser_duration'),
                    resolution='1080x1920',
                    language=language,
                    parent_video_id=video_id,
                    relation_type='teaser',
                    metadata={
                        'is_teaser': True,
                        'parent_video_id': video_id
                    }
                )

                self.studio_tab.log(f" Teaser registrado con ID: {teaser_id}")
                teaser_msg = f"\n\n Short Teaser también generado:\n{result['teaser_video_path']}"
            else:
                teaser_msg = ""
        except Exception as e:
            self.studio_tab.log(f"️ Error registrando video: {e}")
            import traceback
            traceback.print_exc()
            teaser_msg = ""

        self.studio_tab.last_generated_video_data = result

        # Habilitar botones
        self.studio_tab.btn_storyboard.setEnabled(True)
        self.studio_tab.btn_assemble.setEnabled(True)
        self.studio_tab.btn_generate_teaser.setEnabled(True)  # Habilitar botón de teaser
        if hasattr(self.studio_tab, 'btn_play_video'):
            self.studio_tab.btn_play_video.setEnabled(True)
        if hasattr(self.studio_tab, 'btn_publish'):
            self.studio_tab.btn_publish.setEnabled(True)
            for chk in ('chk_publish_youtube', 'chk_publish_facebook', 'chk_publish_instagram'):
                if hasattr(self.studio_tab, chk):
                    getattr(self.studio_tab, chk).setEnabled(True)
        self.studio_tab._hide_progress_indicator()

        self.studio_tab.update_status("Video listo para reproducir")

        extra_paths_msg = ""
        if video_paths_by_platform and len(video_paths_by_platform) > 1:
            lines = [
                f"{platform_name}: {path}"
                for platform_name, path in video_paths_by_platform.items()
                if path
            ]
            if lines:
                extra_paths_msg = "\n\nFormatos generados:\n" + "\n".join(lines)

        self.studio_tab.log(f" Video listo: {video_path}{extra_paths_msg}{teaser_msg}")
        self.studio_tab.update_status("Video listo")

        self.studio_tab.cleanup_thread()


    def on_assemble_error(self, error):
        """Callback cuando hay error ensamblando video"""
        self.studio_tab.log(f"\n ERROR ENSAMBLANDO VIDEO:\n{error}")
        self.studio_tab.btn_storyboard.setEnabled(True)
        self.studio_tab.btn_assemble.setEnabled(True)
        self.studio_tab._hide_progress_indicator()
        QMessageBox.critical(
            self.studio_tab, "Error", f"Error ensamblando video:\n{error}")
        self.studio_tab.cleanup_thread()
