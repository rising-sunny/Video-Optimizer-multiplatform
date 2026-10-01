# studio_storyboard_handlers.py
"""
Handlers para la generaciÃ³n y manejo de storyboards en AutoVideoStudioTab
"""

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QMessageBox

from studio.auto_video_generator_pyqt6_adapter import VideoGenerationWorker


class StudioStoryboardHandlers:
    """Helper class para manejar handlers de storyboard de AutoVideoStudioTab"""

    def __init__(self, studio_tab):
        """Inicializa el handler con una referencia a AutoVideoStudioTab"""
        self.studio_tab = studio_tab

    def _generate_audio_for_storyboard(self, storyboard_data):
        """Genera el audio de narraciÃ³n para un storyboard cargado manualmente"""
        try:
            import time
            from pathlib import Path
            from pipeline.auto_video_generator_v2 import VideoConfig

            # Obtener el script completo
            script = storyboard_data.get('script', '')
            if not script:
                # Si no hay script, construir desde los segmentos
                segments = storyboard_data.get('segments', [])
                script_parts = []
                for seg in segments:
                    narration = seg.get('narration_text', '')
                    if narration:
                        script_parts.append(narration)
                script = ' '.join(script_parts)

            if not script:
                QMessageBox.critical(self.studio_tab, "Error", "No se encontrÃ³ script en el JSON.\n\n"
                                    "El JSON debe contener un campo 'script' con el texto completo de la narraciÃ³n.")
                return None

            # Determinar idioma
            language = storyboard_data.get('language', 'es')

            # Generar audio usando gTTS (forzado en modo prueba)
            self.studio_tab.log(f"   Generando audio con gTTS ({language})...")
            audio_filename = f"auto_test_{int(time.time())}.mp3"
            audio_path_str = str(VideoConfig.AUDIO_DIR / audio_filename)

            # Usar el generador del sistema
            audio_path = self.studio_tab.generator.tts.generate_narration(
                script,
                audio_path_str,
                voice_id="gtts_fallback",  # Forzar gTTS en modo prueba
                language=language
            )

            if not audio_path:
                QMessageBox.critical(self.studio_tab, "Error", "No se pudo generar el audio.\n\n"
                                    "AsegÃºrate de que gTTS estÃ© instalado: pip install gtts")
                return None

            # Agregar audio_path al storyboard
            storyboard_data['audio_path'] = audio_path
            self.studio_tab.log(f"   âœ… Audio generado: {audio_path}")

            # Asegurar que los segmentos tengan todos los campos necesarios
            segments = storyboard_data.get('segments', [])
            current_time = 0.0

            for i, seg in enumerate(segments):
                # assigned_filename es requerido
                if 'assigned_filename' not in seg:
                    seg['assigned_filename'] = f"seg_{i+1:03d}"

                # narration_text es requerido (puede venir como 'text' o
                # 'narration')
                if 'narration_text' not in seg:
                    if 'text' in seg:
                        seg['narration_text'] = seg['text']
                    elif 'narration' in seg:
                        seg['narration_text'] = seg['narration']
                    else:
                        # Si no hay texto, usar el visual_prompt como fallback
                        seg['narration_text'] = seg.get(
                            'visual_prompt', f"Segmento {i+1}")

                # visual_prompt es requerido
                if 'visual_prompt' not in seg:
                    seg['visual_prompt'] = seg.get(
                        'narration_text', f"Imagen para segmento {i+1}")

                # start_time y duration son requeridos
                if 'start_time' not in seg:
                    seg['start_time'] = current_time
                else:
                    current_time = seg['start_time']

                if 'duration' not in seg:
                    seg['duration'] = 5.0  # DuraciÃ³n por defecto

                # Calcular end_time
                seg['end_time'] = seg['start_time'] + seg['duration']

                # Campos 'start' y 'end' son requeridos por el ensamblador
                # (formato Whisper)
                seg['start'] = seg['start_time']
                seg['end'] = seg['end_time']

                # Actualizar current_time para el siguiente segmento
                current_time = seg['end']

                # Campos adicionales que pueden ser Ãºtiles
                if 'sfx_tag' not in seg:
                    seg['sfx_tag'] = 'none'
                if 'overlay_tag' not in seg:
                    seg['overlay_tag'] = 'none'

            return storyboard_data

        except Exception as e:
            import traceback
            error_msg = f"Error generando audio:\n\n{str(e)}\n\n{traceback.format_exc()}"
            QMessageBox.critical(self.studio_tab, "Error", error_msg)
            self.studio_tab.log(f"âŒ {error_msg}")
            return None

    def generate_storyboard(self):
        """Genera el storyboard (Paso 1)"""
        if hasattr(self.studio_tab, 'format_strategy_combo') and self.studio_tab.format_strategy_combo.currentData() == 'micro_documentary':
            from studio.studio_channel_controls import open_pilot
            open_pilot(self.studio_tab, generate=True)
            return
        # Modo normal: generar con Gemini
        # Obtener tema desde la pestaÃ±a de anÃ¡lisis
        topic = self.studio_tab.parent_gui.topic_input.text().strip()
        if not topic:
            QMessageBox.warning(self.studio_tab, "Entrada VacÃ­a",
                              "Ingresa un tema en la pestaÃ±a de AnÃ¡lisis primero")
            return

        isolated = False
        if hasattr(self.studio_tab, "project_manager"):
            isolated = bool(self.studio_tab.project_manager.prepare_isolated_project_for_topic(topic))
        try:
            from studio.studio_channel_controls import sync_editorial_before_writing
            sync_editorial_before_writing(self.studio_tab, isolated=isolated)
        except Exception as exc:
            self.studio_tab.log(f" No se pudo sincronizar el perfil editorial: {exc}")

        category = self.studio_tab.parent_gui.category_combo.currentText()
        try:
            from studio.studio_channel_controls import resolve_archetype_for_topic
            format_archetype = resolve_archetype_for_topic(self.studio_tab, topic, category)
        except Exception as exc:
            self.studio_tab.log(f" Sin ángulo narrativo ({exc}); sigue el Bible general.")
            format_archetype = ""
        duration = self.studio_tab.duration_slider.value()
        language = 'es' if self.studio_tab.lang_es.isChecked() else 'en'
        style = self.studio_tab.style_combo.currentText()
        video_format = self.studio_tab.get_selected_video_format() if hasattr(self.studio_tab, 'get_selected_video_format') else '16:9'
        platform = self.studio_tab.get_selected_platform_key() if hasattr(self.studio_tab, 'get_selected_platform_key') else 'youtube'
        resolution = self.studio_tab.get_selected_resolution() if hasattr(self.studio_tab, 'get_selected_resolution') else (1920, 1080)
        selected_voice = self.studio_tab.voice_combo.currentText()
        voice_id = self.studio_tab.elevenlabs_voices.get(selected_voice, {}).get('id')

        if hasattr(self.studio_tab, 'clamp_duration_for_selected_platform'):
            duration = int(
                self.studio_tab.clamp_duration_for_selected_platform(
                    duration,
                    sync_slider=True,
                    silent=False,
                )
            )
        elif platform == 'youtube':
            min_duration = getattr(self.studio_tab, 'LONG_HORIZONTAL_MIN_DURATION_SECONDS', 120)
            if int(duration) < int(min_duration):
                self.studio_tab.log(
                    f"ℹ️ Ajustando duración para YouTube horizontal: {duration}s -> {min_duration}s (mínimo 2 min)."
                )
                duration = int(min_duration)
                if hasattr(self.studio_tab, 'duration_slider'):
                    self.studio_tab.duration_slider.setValue(duration)

        find_auto_music = False  # MÃºsica auto deshabilitada, solo se usa mÃºsica manual
        use_research = self.studio_tab.research_check.isChecked()
        
        # Obtener snippets de investigación pre-seleccionados por el usuario
        pre_research_snippets = []
        if hasattr(self.studio_tab.parent_gui, 'get_selected_research_context'):
            pre_research_snippets = self.studio_tab.parent_gui.get_selected_research_context()

        # Deshabilitar botones
        self.studio_tab.btn_storyboard.setEnabled(False)
        self.studio_tab.btn_assemble.setEnabled(False)
        self.studio_tab._show_progress_indicator()

        self.studio_tab.log(f"\n{'='*50}")
        self.studio_tab.log(f"ðŸš€ PASO 1: GENERANDO STORYBOARD")
        self.studio_tab.log(f"   Tema: {topic}")
        self.studio_tab.log(f"   CategorÃ­a: {category}")
        self.studio_tab.log(f"   DuraciÃ³n: {duration}s")
        self.studio_tab.log(f"   Formato: {video_format} ({resolution[0]}x{resolution[1]})")
        if pre_research_snippets:
            self.studio_tab.log(f"    Fuentes seleccionadas: {len(pre_research_snippets)}")
        self.studio_tab.log(f"{'='*50}\n")

        # Crear worker
        self.studio_tab.current_worker = VideoGenerationWorker(
            self.studio_tab.generator, "storyboard")
        voice_rate = self.studio_tab.get_selected_voice_rate() if hasattr(self.studio_tab, 'get_selected_voice_rate') else "+0%"
        opening_style = (
            self.studio_tab.get_selected_opening_style()
            if hasattr(self.studio_tab, 'get_selected_opening_style')
            else 'hook_overlay_v1'
        )
        self.studio_tab.current_worker.set_params(
            topic=topic,
            category=category,
            platform=platform,
            duration_seconds=duration,
            language=language,
            style=style,
            voice_id=voice_id,
            find_auto_music=find_auto_music,
            use_research=use_research,
            pre_research_snippets=pre_research_snippets if pre_research_snippets else None,
            rate=voice_rate,
            format_archetype=format_archetype,
            opening_style=opening_style,
        )
        if hasattr(self.studio_tab, '_bind_current_worker_to_project'):
            self.studio_tab._bind_current_worker_to_project()

        # Asegurarse de que el thread anterior termine antes de crear uno nuevo
        if self.studio_tab.current_thread and self.studio_tab.current_thread.isRunning():
            self.studio_tab.log("â³ Esperando que termine el proceso anterior...")
            self.studio_tab.current_thread.quit()
            if not self.studio_tab.current_thread.wait(5000):  # Esperar mÃ¡ximo 5 segundos
                self.studio_tab.log("âš ï¸ Forzando terminaciÃ³n del thread anterior...")
                self.studio_tab.current_thread.terminate()
                self.studio_tab.current_thread.wait()

        # Conectar seÃ±ales
        self.studio_tab.current_worker.finished.connect(self.studio_tab.on_storyboard_finished)
        self.studio_tab.current_worker.error.connect(self.studio_tab.on_storyboard_error)
        self.studio_tab.current_worker.progress.connect(self.studio_tab.log)

        # Ejecutar en thread
        self.studio_tab.current_thread = QThread()
        self.studio_tab.current_worker.moveToThread(self.studio_tab.current_thread)
        self.studio_tab.current_thread.started.connect(self.studio_tab.current_worker.run)
        self.studio_tab.current_thread.start()

    def on_storyboard_finished(self, result, auto_search_images=False):
        """Callback cuando el storyboard estÃ¡ listo

        Args:
            result: Datos del storyboard generado
            auto_search_images: Si True, busca imÃ¡genes automÃ¡ticamente por assigned_filename.
                               Ãštil al cargar proyectos guardados. Por defecto False.
        """
        # El flujo de JSON pegado manualmente no pasa por generate_storyboard_data.
        # Aplicar aqui la entrada elegida si el backend aun no la preparo.
        if isinstance(result, dict) and not result.get('opening') and result.get('segments'):
            try:
                from pipeline.video_opening import apply_opening
                script = str(result.get('script') or ' '.join(
                    str(seg.get('narration_text') or seg.get('text') or '')
                    for seg in result.get('segments', []) if isinstance(seg, dict)
                ))
                result['segments'], result['opening'] = apply_opening(
                    result['segments'],
                    script=script,
                    topic=str(result.get('topic') or ''),
                    category=str(result.get('category') or ''),
                    opening_style_id=self.studio_tab.get_selected_opening_style(),
                    log=self.studio_tab.log,
                )
            except Exception as exc:
                self.studio_tab.log(f" [Arranque] no se pudo aplicar al JSON manual: {exc}")

        self.studio_tab.log("\nâœ… PASO 1 COMPLETADO")
        if isinstance(result, dict) and result.get('segments'):
            try:
                from pipeline.cinematic_director import direct_storyboard
                level = (
                    self.studio_tab.cinematic_intensity_combo.currentData()
                    if hasattr(self.studio_tab, 'cinematic_intensity_combo') else 'auto'
                )
                preset = (
                    self.studio_tab.cinematic_preset_combo.currentText().lower()
                    if hasattr(self.studio_tab, 'cinematic_preset_combo') else 'auto'
                )
                direct_storyboard(result, level=level, preset=preset)
            except Exception as direction_error:
                self.studio_tab.log(
                    f" [WARN] No se pudo preparar la direccion cinematografica: {direction_error}"
                )
        self.studio_tab.last_storyboard_data = result
        from studio.studio_channel_controls import project_channel_config
        result.setdefault('channel_profile', project_channel_config(self.studio_tab)['channel_profile'])

        # GUARDADO INMEDIATO para prevenir pÃ©rdida de datos en caso de crash
        try:
            self.studio_tab.log("ðŸ’¾ Guardando storyboard inmediatamente...")
            if hasattr(self.studio_tab, 'project_manager'):
                self.studio_tab.project_manager.auto_save_project("Storyboard generado (guardado inmediato)")
            self.studio_tab.log("âœ… Storyboard guardado exitosamente")
        except Exception as e:
            self.studio_tab.log(f"âš ï¸ Error guardando storyboard (continuando): {e}")
            # Continuar aunque falle el guardado

        # ACTUALIZAR TIMELINE EDITOR con los nuevos segmentos corregidos
        try:
            if hasattr(self.studio_tab, 'parent_gui') and hasattr(self.studio_tab.parent_gui, 'timeline_editor_window'):
                timeline_window = self.studio_tab.parent_gui.timeline_editor_window
                if timeline_window and hasattr(timeline_window, 'load_segments_from_project'):
                    self.studio_tab.log("ðŸ”„ Actualizando Timeline Editor con segmentos corregidos...")
                    timeline_window.load_segments_from_project()
                    self.studio_tab.log("âœ… Timeline Editor actualizado con segmentos corregidos")
        except Exception as e:
            self.studio_tab.log(f"âš ï¸ Error actualizando Timeline Editor (continuando): {e}")

        # Poblar panel de revisiÃ³n
        self.populate_review_panel(
            result, auto_search_images=auto_search_images)

        # Habilitar botones
        self.studio_tab.btn_storyboard.setEnabled(True)
        # Habilitar generaciÃ³n de imÃ¡genes
        self.studio_tab.btn_generate_images.setEnabled(True)
        if hasattr(self.studio_tab, 'btn_open_timeline'):
            # Habilitar botÃ³n de Timeline Editor
            self.studio_tab.btn_open_timeline.setEnabled(True)
        self.studio_tab._hide_progress_indicator()

        self.studio_tab.update_status("Storyboard listo - Revisa y edita si deseas")

        # Auto-guardar si estÃ¡ habilitado
        if self.studio_tab.auto_save_enabled:
            if hasattr(self.studio_tab, 'project_manager'):
                self.studio_tab.project_manager.auto_save_project("Paso 1 completado (Storyboard)")

        # Cleanup thread
        self.studio_tab.cleanup_thread()

    def on_storyboard_error(self, error):
        """Callback cuando hay error en storyboard"""
        self.studio_tab.log(f"\nâŒ ERROR EN PASO 1:\n{error}")

        self.studio_tab.btn_storyboard.setEnabled(True)
        self.studio_tab._hide_progress_indicator()
        self.studio_tab.update_status("Error en generaciÃ³n de storyboard")

        QMessageBox.critical(
            self.studio_tab, "Error", f"Error generando storyboard:\n\n{error}")

        self.studio_tab.cleanup_thread()

    def populate_review_panel(self, storyboard_data, auto_search_images=False):
        """Puebla el Timeline Editor con los datos del storyboard

        Args:
            storyboard_data: Datos del storyboard
            auto_search_images: Si True, busca imÃ¡genes automÃ¡ticamente por assigned_filename.
                               Solo debe ser True al cargar proyectos guardados o despuÃ©s de generar imÃ¡genes.
                               Por defecto False para evitar asignar imÃ¡genes antiguas a storyboards nuevos.
        """
        segments = storyboard_data.get('segments', [])

        if not segments:
            self.studio_tab.log("âš ï¸ No hay segmentos para cargar en el Timeline")
            return

        # Normalizar segmentos para el Timeline Editor
        # El Timeline Editor espera: 'text', 'start', 'end'
        # Pero el JSON puede tener: 'narration_text', 'start_time', 'duration'
        # IMPORTANTE: seg.copy() preserva TODOS los campos, incluyendo image_path, image_source, video_path, video_source
        normalized_segments = []
        for seg in segments:
            normalized = seg.copy()  # Esto preserva TODOS los campos del segmento original

            # Normalizar campo de texto
            if 'text' not in normalized:
                if 'narration_text' in normalized:
                    normalized['text'] = normalized['narration_text']
                elif 'narration' in normalized:
                    normalized['text'] = normalized['narration']
                else:
                    normalized['text'] = normalized.get(
                        'visual_prompt', 'Sin texto')

            # Normalizar campos de tiempo
            if 'start' not in normalized or 'end' not in normalized:
                if 'start_time' in normalized:
                    start_time = normalized['start_time']
                    duration = normalized.get('duration', 5.0)
                    normalized['start'] = start_time
                    normalized['end'] = start_time + duration
                else:
                    # Si no hay tiempos, usar valores por defecto
                    normalized['start'] = 0.0
                    normalized['end'] = 5.0

            normalized_segments.append(normalized)
        
        # Debug: verificar que image_source y video_source se preservaron
        segments_with_sources = sum(1 for seg in normalized_segments 
                                   if seg.get('image_source') or seg.get('video_source'))
        if segments_with_sources > 0:
            print(f"[populate_review_panel] âœ… {segments_with_sources} segmento(s) con image_source/video_source preservados")

        # Cargar en Timeline Editor (si estÃ¡ disponible)
        if hasattr(self.studio_tab, 'timeline_editor') and self.studio_tab.timeline_editor:
            try:
                self.studio_tab.timeline_editor.load_segments(
                    normalized_segments, auto_search_images=auto_search_images)
                self.studio_tab.log(
                    f"ðŸ“ Timeline Editor cargado con {len(normalized_segments)} segmentos")
                self.studio_tab.log("ðŸ’¡ Puedes editar, reordenar o eliminar segmentos antes del Paso 2")
                self.studio_tab.log("â„¹ï¸ Las imÃ¡genes se generarÃ¡n en el Paso 1.5 (Generar ImÃ¡genes)")
            except Exception as e:
                self.studio_tab.log(f"âš ï¸ Error cargando segmentos en Timeline Editor: {e}")
                import traceback
                traceback.print_exc()
        else:
            self.studio_tab.log("âš ï¸ Timeline Editor no estÃ¡ disponible")



