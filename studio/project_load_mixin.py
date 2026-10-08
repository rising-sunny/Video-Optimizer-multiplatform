# studio_project_manager.py
"""
Gestor de proyectos para AutoVideoStudioTab.
Extraído de auto_video_integration_pyqt6.py para mejorar la organización del código.
"""

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QDialog
from PyQt6.QtCore import QTimer
import os
import json
import glob
import shutil
import traceback
import copy
from pathlib import Path
from datetime import datetime, timedelta
from studio.studio_channel_controls import project_channel_config, restore_channel_config

# Utilidades para manejar errores de Google Drive
try:
    from media.gdrive_file_utils import safe_copy2
except ImportError:
    safe_copy2 = shutil.copy2  # Fallback si no existe el módulo

from studio.project_media_mixin import ProjectMediaMixin


from studio.project_save_mixin import ProjectSaveMixin


class ProjectLoadMixin:
    def load_project(self):
        """Carga un proyecto guardado, guardando el actual primero si existe"""

        try:
            # Guardar el proyecto actual antes de cargar uno nuevo
            if (hasattr(self.studio_tab, 'current_project_path') and 
                self.studio_tab.current_project_path and
                os.path.exists(self.studio_tab.current_project_path)):
                # Auto-guardar el proyecto actual
                self.auto_save_project("antes de abrir otro proyecto")
                if hasattr(self.studio_tab, 'log'):
                    self.studio_tab.log(" Proyecto actual guardado automáticamente")

            # Usar el nuevo sistema de gestión de proyectos v2.0
            from app.project_manager_v2 import ProjectManagerV2


            # Asegurar que el directorio existe antes de usarlo

            ProjectManagerV2._ensure_projects_dir()


            # Mostrar diálogo para seleccionar proyecto

            projects_dir_str = str(ProjectManagerV2.PROJECTS_DIR.absolute()) if ProjectManagerV2.PROJECTS_DIR.exists() else ""

            project_path, _ = QFileDialog.getOpenFileName(

                self.studio_tab,

                "Cargar Proyecto",

                projects_dir_str,

                "Archivos de Proyecto (*.json);;Todos los archivos (*.*)"

            )


            if not project_path:

                return


            # Cargar proyecto con el nuevo sistema

            project_data = ProjectManagerV2.load_project(project_path)


            if not project_data:

                QMessageBox.critical(
                    self.studio_tab, "Error", "No se pudo cargar el proyecto")
                return

            # Confirmar carga
            reply = QMessageBox.question(
                self.studio_tab,
                "Cargar Proyecto",
                f"¿Deseas cargar este proyecto?\n\n"
                f"Tema: {project_data.get('config', {}).get('topic', 'N/A')}\n"
                f"Creado: {project_data.get('created', 'N/A')}\n\n"
                f"Esto reemplazará cualquier configuración actual.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            # Continuar con load_project_from_path para la carga real
            self.load_project_from_path(project_path)

        except Exception as e:
            self.studio_tab.log(f" Error cargando proyecto: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.studio_tab, "Error", f"Error cargando proyecto:\n\n{str(e)}")


    def manage_projects(self):
        """Abre el diálogo de gestión de proyectos"""

        try:

            from app.project_manager_dialog import ProjectManagerDialog


            dialog = ProjectManagerDialog(self.studio_tab)

            if dialog.exec() == QDialog.DialogCode.Accepted:

                # Si el usuario seleccionó un proyecto y clickeó "Abrir"

                project_path = dialog.get_selected_project_path()

                if project_path:

                    # Cargar el proyecto seleccionado

                    self.studio_tab.load_project_from_path(project_path)

        except ImportError as e:
            QMessageBox.critical(
                self.studio_tab, "Error", f"No se pudo importar ProjectManagerDialog: {e}")
        except Exception as e:
            QMessageBox.critical(
                self.studio_tab, "Error", f"Error gestionando proyectos: {e}")


    def load_project_from_path(self, project_path):
        """Carga un proyecto desde una ruta específica (usado por el diálogo de gestión)"""

        load_token = None
        try:
            from app.project_manager_v2 import ProjectManagerV2

            # Cargar proyecto con el nuevo sistema
            project_data = ProjectManagerV2.load_project(project_path)

            if not project_data:
                if hasattr(self, 'studio_tab') and self.studio_tab:
                    QMessageBox.critical(
                        self.studio_tab, "Error", "No se pudo cargar el proyecto")
                return

            if not hasattr(self, 'studio_tab') or not self.studio_tab:
                print(" Error: studio_tab no está disponible")
                return

            self.studio_tab.log(f"\n Cargando proyecto: {project_path}")

            # Validar archivos referenciados
            validation_warnings = self.validate_project_files(project_data)
            if validation_warnings:
                warning_msg = "️ ADVERTENCIAS:\n\n" + \
                    "\n".join(validation_warnings)
                warning_msg += "\n\n¿Deseas continuar cargando el proyecto?"
                reply = QMessageBox.warning(
                    self.studio_tab,
                    "Archivos Faltantes",
                    warning_msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            if hasattr(self.studio_tab, '_begin_project_load'):
                load_token = self.studio_tab._begin_project_load(project_path)

            # Evita que el timeline del proyecto anterior siga sincronizando
            # segmentos mientras se carga el nuevo JSON.
            self._close_existing_timeline_editor()

            # Restaurar configuraciones
            config = project_data.get('config', {})
            restore_channel_config(self.studio_tab, config)
            self.studio_tab.publish_results = dict(project_data.get('publish_results') or {})

            if hasattr(self.studio_tab, 'parent_gui'):
                if hasattr(self.studio_tab.parent_gui, 'topic_input') and config.get('topic'):
                    self.studio_tab.parent_gui.topic_input.setText(config.get('topic'))

                if hasattr(self.studio_tab.parent_gui, 'category_combo') and config.get('category'):
                    index = self.studio_tab.parent_gui.category_combo.findText(config.get('category'))
                    if index >= 0:
                        self.studio_tab.parent_gui.category_combo.setCurrentIndex(index)

            platform_restored = False
            if config.get('platform_key'):
                platform_key = str(config.get('platform_key')).strip().lower()
                for index in range(self.studio_tab.platform_combo.count()):
                    data = self.studio_tab.platform_combo.itemData(index)
                    if isinstance(data, dict) and str(data.get('platform', '')).strip().lower() == platform_key:
                        self.studio_tab.platform_combo.setCurrentIndex(index)
                        platform_restored = True
                        break

            if (not platform_restored) and config.get('platform'):
                index = self.studio_tab.platform_combo.findText(config.get('platform'))
                if index >= 0:
                    self.studio_tab.platform_combo.setCurrentIndex(index)
                    platform_restored = True

            if (not platform_restored) and config.get('video_format') and hasattr(self.studio_tab, 'set_video_format'):
                self.studio_tab.set_video_format(config.get('video_format'))

            if config.get('duration'):
                self.studio_tab.duration_slider.setValue(config.get('duration'))

            language = config.get('language', 'es')
            if language == 'es':
                self.studio_tab.lang_es.setChecked(True)
            else:
                self.studio_tab.lang_en.setChecked(True)

            # Restaurar voz seleccionada
            if hasattr(self.studio_tab, 'voice_combo'):
                voice_name = config.get('voice_name')
                if not voice_name:
                    voice_id = config.get('voice_id')
                    if voice_id and hasattr(self.studio_tab, 'elevenlabs_voices') and self.studio_tab.elevenlabs_voices:
                        # Buscar el nombre de la voz por su ID
                        for name, info in self.studio_tab.elevenlabs_voices.items():
                            if info.get('id') == voice_id:
                                voice_name = name
                                break
                
                if voice_name:
                    # Verificar si las voces ya están cargadas
                    if hasattr(self.studio_tab, 'elevenlabs_voices') and self.studio_tab.elevenlabs_voices:
                        # Las voces ya están cargadas, seleccionar directamente
                        if voice_name in self.studio_tab.elevenlabs_voices:
                            index = self.studio_tab.voice_combo.findText(voice_name)
                            if index >= 0:
                                self.studio_tab.voice_combo.setCurrentIndex(index)
                                self.studio_tab.log(f" Voz restaurada: {voice_name}")
                            else:
                                self.studio_tab.log(f"️ Voz '{voice_name}' no encontrada en el combo")
                        else:
                            self.studio_tab.log(f"️ Voz '{voice_name}' no disponible")
                    else:
                        # Las voces aún no están cargadas, guardar para aplicar después
                        self.studio_tab.pending_voice_selection = voice_name
                        self.studio_tab.log(f" Voz '{voice_name}' se aplicará cuando las voces estén cargadas")

            self.studio_tab.subtitles_check.setChecked(bool(config.get('subtitles_enabled')))
            # El estilo se restaura SIEMPRE, tambien con los subtitulos
            # apagados: si no, encenderlos despues devolvia el estilo por
            # defecto en vez del que se habia elegido.
            if config.get('subtitle_style') and hasattr(self.studio_tab, 'subtitle_style_combo'):
                index = self.studio_tab.subtitle_style_combo.findText(config.get('subtitle_style'))
                if index >= 0:
                    self.studio_tab.subtitle_style_combo.setCurrentIndex(index)
                    self.studio_tab.log(f" Estilo de subtitulos restaurado: {config.get('subtitle_style')}")

            if hasattr(self.studio_tab, 'overlays_check') and config.get('overlays_enabled') is not None:
                self.studio_tab.overlays_check.setChecked(config.get('overlays_enabled'))

            if hasattr(self.studio_tab, 'research_check') and config.get('research_enabled') is not None:
                self.studio_tab.research_check.setChecked(config.get('research_enabled'))

            if hasattr(self.studio_tab, 'music_check') and config.get('music_enabled') is not None:
                self.studio_tab.music_check.setChecked(config.get('music_enabled'))

            # Restaurar opciones de Auto Video Studio Pro
            if hasattr(self.studio_tab, 'image_provider_combo') and config.get('image_provider'):
                provider_text = str(config.get('image_provider') or '').strip()
                if provider_text.startswith("Fal.ai (FLUX.1 schnell)"):
                    provider_text = "Fal.ai (FLUX.1 schnell)"
                provider_aliases = {
                    "Fal.ai (FLUX.1 schnell) âš¡": "Fal.ai (FLUX.1 schnell)",
                    "Leonardo AI": "Recraft AI",
                    "Leonardo AI (Fallback)": "Recraft AI",
                    "Imagen 4 Fast (Vertex AI)": "Google AI (Gemini API)",
                    "Manual (Gratuito) - Gemini Veo/Copilot/etc.": "Manual (Gratuito)",
                }
                provider_text = provider_aliases.get(provider_text, provider_text)
                index = self.studio_tab.image_provider_combo.findText(provider_text)
                if index >= 0:
                    self.studio_tab.image_provider_combo.setCurrentIndex(index)

            # El estilo visual va DESPUES del proveedor a proposito: cambiar el
            # proveedor dispara `_on_image_provider_changed`, que vacia y vuelve
            # a llenar `style_combo`. Restaurado antes, se perdia.
            if config.get('style') and hasattr(self.studio_tab, 'style_combo'):
                index = self.studio_tab.style_combo.findText(config.get('style'))
                if index >= 0:
                    self.studio_tab.style_combo.setCurrentIndex(index)

            if hasattr(self.studio_tab, 'opening_style_combo'):
                from pipeline.video_opening import normalize_opening_style
                opening_style = normalize_opening_style(config.get('opening_style'))
                for index in range(self.studio_tab.opening_style_combo.count()):
                    if self.studio_tab.opening_style_combo.itemData(index) == opening_style:
                        self.studio_tab.opening_style_combo.setCurrentIndex(index)
                        break

            if hasattr(self.studio_tab, 'visual_static') and hasattr(self.studio_tab, 'visual_mixed'):
                visual_mode = config.get('visual_mode', 'mixed')
                if visual_mode == 'static':
                    self.studio_tab.visual_static.setChecked(True)
                else:
                    self.studio_tab.visual_mixed.setChecked(True)

            if hasattr(self.studio_tab, 'cinematic_check') and config.get('cinematic_enabled') is not None:
                self.studio_tab.cinematic_check.setChecked(config.get('cinematic_enabled'))
                if hasattr(self.studio_tab, 'cinematic_preset_combo'):
                    preset_text = config.get('cinematic_preset', " Auto-Detect (Inteligente)")
                    index = self.studio_tab.cinematic_preset_combo.findText(preset_text)
                    if index >= 0:
                        self.studio_tab.cinematic_preset_combo.setCurrentIndex(index)
                    self.studio_tab.cinematic_preset_combo.setEnabled(self.studio_tab.cinematic_check.isChecked())

                if hasattr(self.studio_tab, 'cinematic_intensity_combo'):
                    intensity = str(config.get('cinematic_intensity', 'auto') or 'auto')
                    index = self.studio_tab.cinematic_intensity_combo.findData(intensity)
                    if index < 0:
                        index = 0
                    self.studio_tab.cinematic_intensity_combo.setCurrentIndex(index)
                    self.studio_tab.cinematic_intensity_combo.setEnabled(
                        self.studio_tab.cinematic_check.isChecked()
                    )

            # Dinamismo y tomas 3D. Un proyecto viejo (sin la clave) queda como se
            # ensamblo siempre: sin composiciones.
            if hasattr(self.studio_tab, 'dynamism_combo'):
                index = self.studio_tab.dynamism_combo.findData(str(config.get('dynamism', 'off') or 'off'))
                self.studio_tab.dynamism_combo.setCurrentIndex(max(0, index))
            if hasattr(self.studio_tab, 'blender_check'):
                self.studio_tab.blender_check.setChecked(bool(config.get('blender_shots', False)))
            if hasattr(self.studio_tab, 'blender_quality_combo'):
                index = self.studio_tab.blender_quality_combo.findData(
                    str(config.get('blender_quality', 'normal') or 'normal'))
                self.studio_tab.blender_quality_combo.setCurrentIndex(max(0, index))
            if hasattr(self.studio_tab, 'blender_environment_combo'):
                index = self.studio_tab.blender_environment_combo.findData(
                    str(config.get('blender_environment', 'auto') or 'auto'))
                self.studio_tab.blender_environment_combo.setCurrentIndex(max(0, index))

            if hasattr(self.studio_tab, 'transition_type_combo') and config.get('transition_type'):
                transition_text = config.get('transition_type')
                index = self.studio_tab.transition_type_combo.findText(transition_text)
                if index >= 0:
                    self.studio_tab.transition_type_combo.setCurrentIndex(index)

            if hasattr(self.studio_tab, 'transition_duration_spin') and config.get('transition_duration') is not None:
                self.studio_tab.transition_duration_spin.setValue(config.get('transition_duration', 0.5))

            if hasattr(self.studio_tab, 'transition_sfx_check') and config.get('transition_sfx_enabled') is not None:
                self.studio_tab.transition_sfx_check.setChecked(bool(config.get('transition_sfx_enabled')))
            if hasattr(self.studio_tab, '_populate_transition_sfx_combo'):
                self.studio_tab._populate_transition_sfx_combo(config.get('transition_sfx_path'))
            if hasattr(self.studio_tab, '_on_transition_sfx_toggled') and hasattr(self.studio_tab, 'transition_sfx_check'):
                self.studio_tab._on_transition_sfx_toggled(self.studio_tab.transition_sfx_check.isChecked())

            # Restaurar ratio de imágenes por segmento
            if hasattr(self.studio_tab, 'images_per_segment_spin') and config.get('images_per_segment_ratio') is not None:
                self.studio_tab.images_per_segment_spin.setValue(config.get('images_per_segment_ratio', 1))

            # Restaurar música seleccionada
            if config.get('selected_music_path'):
                music_path = config.get('selected_music_path')
                if music_path and not os.path.isabs(music_path):
                    from pathlib import Path
                    project_root = Path.cwd()
                    abs_path = project_root / music_path
                    if abs_path.exists():
                        music_path = str(abs_path.resolve())
                    else:
                        abs_path = Path(music_path).resolve()
                        if abs_path.exists():
                            music_path = str(abs_path)

                if music_path and os.path.exists(music_path):
                    self.studio_tab.selected_music_path = music_path
                    self.studio_tab.log(f"    Música restaurada: {os.path.basename(music_path)}")
                    music_metadata = config.get('selected_music_metadata') or project_data.get('music_metadata')
                    if music_metadata:
                        self.studio_tab.selected_music_metadata = music_metadata
                        title = music_metadata.get('title', 'Desconocido')
                        artist = music_metadata.get('artist', 'Desconocido')
                        self.studio_tab.log(f"       {title} - {artist}")
                        
                        if hasattr(self.studio_tab, 'selected_music_label'):
                            crop_info = ""
                            crop_start = music_metadata.get('crop_start', 0.0)
                            crop_end = music_metadata.get('crop_end', music_metadata.get('duration', 0))
                            if crop_start > 0 or crop_end < music_metadata.get('duration', 0):
                                # format_time es un método de studio_tab
                                if hasattr(self.studio_tab, 'format_time'):
                                    crop_info = f" ️ ({self.studio_tab.format_time(crop_start)} - {self.studio_tab.format_time(crop_end)})"
                            self.studio_tab.selected_music_label.setText(f" Pista seleccionada: {title} - {artist}{crop_info}")
                else:
                    self.studio_tab.log(f"   ️ Música no encontrada en: {music_path}")

            # También verificar music_path en el nivel raíz del proyecto
            music_path = project_data.get('music_path')
            if music_path and (not hasattr(self.studio_tab, 'selected_music_path') or not self.studio_tab.selected_music_path):
                if not os.path.isabs(music_path):
                    from pathlib import Path
                    project_root = Path.cwd()
                    abs_path = project_root / music_path
                    if abs_path.exists():
                        music_path = str(abs_path.resolve())
                    else:
                        abs_path = Path(music_path).resolve()
                        if abs_path.exists():
                            music_path = str(abs_path)

                if music_path and os.path.exists(music_path):
                    self.studio_tab.selected_music_path = music_path
                    self.studio_tab.log(f"    Música restaurada desde music_path: {os.path.basename(music_path)}")
                    music_metadata = project_data.get('music_metadata')
                    if music_metadata:
                        self.studio_tab.selected_music_metadata = music_metadata
                        title = music_metadata.get('title', 'Desconocido')
                        artist = music_metadata.get('artist', 'Desconocido')
                        self.studio_tab.log(f"       {title} - {artist}")
                        
                        if hasattr(self.studio_tab, 'selected_music_label'):
                            crop_info = ""
                            crop_start = music_metadata.get('crop_start', 0.0)
                            crop_end = music_metadata.get('crop_end', music_metadata.get('duration', 0))
                            if crop_start > 0 or crop_end < music_metadata.get('duration', 0):
                                if hasattr(self.studio_tab, 'format_time'):
                                    crop_info = f" ️ ({self.studio_tab.format_time(crop_start)} - {self.studio_tab.format_time(crop_end)})"
                            self.studio_tab.selected_music_label.setText(f" Pista seleccionada: {title} - {artist}{crop_info}")

            # Guardar ruta del proyecto cargado para auto-guardado
            self.studio_tab.current_project_path = project_path

            # Guardar ruta del último proyecto
            if hasattr(self.studio_tab, '_save_last_project_path'):
                self.studio_tab._save_last_project_path(project_path)

            # Restaurar storyboard si existe
            storyboard_data = project_data.get('storyboard') or {}
            if self._storyboard_is_unusable(storyboard_data):
                self.studio_tab.log(
                    " El storyboard guardado es un rechazo del LLM. Se ignora y no se abre el timeline."
                )
                print("[ProjectLoad] Storyboard de rechazo ignorado; no se restaura.")
                storyboard_data = {}
                self.studio_tab.last_storyboard_data = None
            if storyboard_data and storyboard_data.get('segments'):
                segments = storyboard_data.get('segments', [])
                self.studio_tab.log(f"    Restaurando storyboard con {len(segments)} segmentos...")

                # Convertir rutas relativas a absolutas para imágenes/videos
                storyboard_data = self._restore_media_paths(project_path, storyboard_data)
                self.studio_tab.last_storyboard_data = storyboard_data

                # Debug: Mostrar cuántos segmentos tienen imágenes restauradas
                images_restored = sum(1 for seg in storyboard_data.get('segments', []) if seg.get('image_path'))
                if images_restored > 0:
                    self.studio_tab.log(f"   ️ {images_restored} segmento(s) con rutas de imagen restauradas")

                # Cargar storyboard en el Timeline Editor
                if hasattr(self.studio_tab, 'apply_loaded_project_storyboard'):
                    try:
                        # Usar storyboard_handlers si existe, sino el método directo
                        if hasattr(self.studio_tab, 'storyboard_handlers'):
                            self.studio_tab.apply_loaded_project_storyboard(storyboard_data, auto_search_images=True)
                        else:
                            self.studio_tab.apply_loaded_project_storyboard(storyboard_data, auto_search_images=True)
                    except Exception as e:
                        print(f"️ Error cargando storyboard: {e}")
                        import traceback
                        traceback.print_exc()

                # Abrir Timeline Editor automáticamente al cargar proyecto
                if storyboard_data and storyboard_data.get('segments'):
                    from PyQt6.QtCore import QTimer
                    if hasattr(self.studio_tab, 'open_timeline_editor'):
                        expected_project_path = self._normalize_project_path(project_path)

                        def _open_loaded_project_timeline():
                            if hasattr(self.studio_tab, '_is_project_context_current'):
                                if not self.studio_tab._is_project_context_current(expected_project_path, load_token):
                                    print(
                                        "[ProjectLoad] Omitiendo apertura diferida del timeline por token/ruta obsoletos: "
                                        f"esperado={expected_project_path}"
                                    )
                                    return
                            current_project_path = self._normalize_project_path(
                                getattr(self.studio_tab, 'current_project_path', None)
                            )
                            if (
                                expected_project_path and
                                current_project_path and
                                expected_project_path != current_project_path
                            ):
                                print(
                                    "[ProjectLoad] Omitiendo apertura diferida del timeline: "
                                    f"esperado={expected_project_path} actual={current_project_path}"
                                )
                                return
                            if getattr(self.studio_tab, '_loading_project', False):
                                print("[ProjectLoad] Omitiendo apertura diferida del timeline: carga aún en progreso")
                                return
                            self.studio_tab.open_timeline_editor()

                        QTimer.singleShot(500, _open_loaded_project_timeline)

                # Verificar imágenes después de la normalización
                if self.studio_tab.last_storyboard_data and self.studio_tab.last_storyboard_data.get('segments'):
                    normalized_segments = self.studio_tab.last_storyboard_data.get('segments', [])
                    images_count = sum(1 for seg in normalized_segments if seg.get('image_path') and os.path.exists(seg.get('image_path')))
                else:
                    images_count = 0

                if images_count > 0:
                    self.studio_tab.log(f"   ️ {images_count} segmento(s) con imágenes encontradas")

                # Habilitar botones según el progreso
                progress = project_data.get('progress', {})
                if progress.get('storyboard_done'):
                    if hasattr(self.studio_tab, 'btn_generate_images'):
                        self.studio_tab.btn_generate_images.setEnabled(True)
                    if hasattr(self.studio_tab, 'btn_change_voice'):
                        self.studio_tab.btn_change_voice.setEnabled(True)
                    if images_count > 0:
                        if hasattr(self.studio_tab, 'btn_assemble'):
                            self.studio_tab.btn_assemble.setEnabled(True)
                        self.studio_tab.log("    Storyboard restaurado con imágenes - Puedes continuar con el ensamblaje de video")
                    else:
                        self.studio_tab.log("    Storyboard restaurado - Puedes continuar con la generación de imágenes")

                if hasattr(self.studio_tab, '_refresh_assemble_button_state'):
                    self.studio_tab._refresh_assemble_button_state()

                # Permitir siempre intentar reproducir o publicar si hay storyboard
                # (el usuario podrá seleccionar el archivo manualmente si no está en memoria)
                if progress.get('storyboard_done'):
                    if hasattr(self.studio_tab, 'btn_generate_teaser'):
                        self.studio_tab.btn_generate_teaser.setEnabled(True)
                    if hasattr(self.studio_tab, 'btn_play_video'):
                        self.studio_tab.btn_play_video.setEnabled(True)
                    if hasattr(self.studio_tab, 'btn_publish'):
                        self.studio_tab.btn_publish.setEnabled(True)
                    for chk_name in ('chk_publish_youtube', 'chk_publish_facebook', 'chk_publish_instagram'):
                        if hasattr(self.studio_tab, chk_name):
                            getattr(self.studio_tab, chk_name).setEnabled(True)
                            
                # Si el video ya fue ensamblado
                if progress.get('video_assembled'):
                    self.studio_tab.log("    Video ya fue ensamblado - Puedes generar el Short Teaser o publicar")

                    # Intentar restaurar referencia al video
                    video_restored = False
                    generated_video_data = project_data.get('generated_video_data')
                    if generated_video_data:
                        video_path = generated_video_data.get('video_path')
                        if video_path:
                            if not os.path.isabs(video_path):
                                from pathlib import Path
                                project_root = Path.cwd()
                                abs_path = project_root / video_path
                                if abs_path.exists():
                                    video_path = str(abs_path.resolve())
                                else:
                                    abs_path = Path(video_path).resolve()
                                    if abs_path.exists():
                                        video_path = str(abs_path)

                            if video_path and os.path.exists(video_path):
                                self.studio_tab.last_generated_video_data = generated_video_data.copy()
                                self.studio_tab.last_generated_video_data['video_path'] = video_path
                                self.studio_tab.log(f"    Referencia al video restaurada desde proyecto: {os.path.basename(video_path)}")
                                video_restored = True

                                if hasattr(self.studio_tab, 'btn_publish_teaser'):
                                    self.studio_tab.btn_publish_teaser.setEnabled(True)
                                
                                # Verificar teaser
                                teaser_video_path = generated_video_data.get('teaser_video_path')
                                if teaser_video_path:
                                    if not os.path.isabs(teaser_video_path):
                                        from pathlib import Path
                                        project_root = Path.cwd()
                                        abs_teaser_path = project_root / teaser_video_path
                                        if abs_teaser_path.exists():
                                            teaser_video_path = str(abs_teaser_path.resolve())
                                        else:
                                            abs_teaser_path = Path(teaser_video_path).resolve()
                                            if abs_teaser_path.exists():
                                                teaser_video_path = str(abs_teaser_path)
                                    
                                    if teaser_video_path and os.path.exists(teaser_video_path):
                                        self.studio_tab.last_generated_video_data['teaser_video_path'] = teaser_video_path
                                        self.studio_tab.log(f"    Short Teaser encontrado: {os.path.basename(teaser_video_path)}")
                                    else:
                                        teaser_found = False
                                        if self.studio_tab.last_generated_video_data.get('video_id'):
                                            try:
                                                from app.video_registry import VideoRegistry
                                                registry = VideoRegistry()
                                                teasers = registry.get_teasers_for_long_video(self.studio_tab.last_generated_video_data['video_id'])
                                                if teasers:
                                                    teaser_data = teasers[0]
                                                    teaser_path = teaser_data.get('video_path')
                                                    if teaser_path and os.path.exists(teaser_path):
                                                        self.studio_tab.last_generated_video_data['teaser_video_path'] = teaser_path
                                                        self.studio_tab.log(f"    Short Teaser encontrado en Registry: {os.path.basename(teaser_path)}")
                                                        teaser_found = True
                                            except Exception as e:
                                                self.studio_tab.log(f"   ️ Error buscando teaser en Registry: {e}")
                                        
                                        if not teaser_found:
                                            self.studio_tab.log("    Botón de publicar teaser habilitado (puedes generar el teaser primero si es necesario)")
                                else:
                                    teaser_found = False
                                    if self.studio_tab.last_generated_video_data.get('video_id'):
                                        try:
                                            from app.video_registry import VideoRegistry
                                            registry = VideoRegistry()
                                            teasers = registry.get_teasers_for_long_video(self.studio_tab.last_generated_video_data['video_id'])
                                            if teasers:
                                                teaser_data = teasers[0]
                                                teaser_path = teaser_data.get('video_path')
                                                if teaser_path and os.path.exists(teaser_path):
                                                    self.studio_tab.last_generated_video_data['teaser_video_path'] = teaser_path
                                                    self.studio_tab.log(f"    Short Teaser encontrado en Registry: {os.path.basename(teaser_path)}")
                                                    teaser_found = True
                                        except Exception as e:
                                            self.studio_tab.log(f"   ️ Error buscando teaser en Registry: {e}")
                                    
                                    if not teaser_found:
                                        self.studio_tab.log("    Botón de publicar teaser habilitado (puedes generar el teaser primero si es necesario)")

                                # Cargar video en preview (simplificado - delegar a studio_tab si tiene método)
                                def load_video_in_preview_method1():
                                    try:
                                        if hasattr(self.studio_tab, '_is_project_context_current'):
                                            if not self.studio_tab._is_project_context_current(project_path, load_token):
                                                return
                                        if hasattr(self.studio_tab, 'parent_gui') and hasattr(self.studio_tab.parent_gui, 'video_preview_tab'):
                                            parent_window = self.studio_tab.parent_gui
                                            video_preview = parent_window.video_preview_tab
                                            if video_preview and hasattr(video_preview, 'load_video'):
                                                audio_path = generated_video_data.get('audio_path')
                                                segments_data = generated_video_data.get('segments')
                                                teaser_video_path = generated_video_data.get('teaser_video_path')
                                                video_path_with_subs = video_path.replace('.mp4', '_with_subs.mp4')
                                                final_video_path = video_path_with_subs if os.path.exists(video_path_with_subs) else video_path
                                                self.studio_tab.log(f"    Cargando video en preview: {os.path.basename(final_video_path)}")
                                                video_preview.load_video(
                                                    video_path=final_video_path,
                                                    audio_path=audio_path,
                                                    segments_data=segments_data,
                                                    teaser_video_path=teaser_video_path
                                                )
                                                self.studio_tab.log(f"    Video cargado en vista previa")
                                                if hasattr(parent_window, 'tabs'):
                                                    for i in range(parent_window.tabs.count()):
                                                        if parent_window.tabs.tabText(i) == " Preview del Video":
                                                            parent_window.tabs.setCurrentIndex(i)
                                                            break
                                    except Exception as preview_error:
                                        self.studio_tab.log(f"   ️ No se pudo cargar en vista previa: {preview_error}")

                                from PyQt6.QtCore import QTimer
                                QTimer.singleShot(1000, load_video_in_preview_method1)

                    # Método 2: Intentar desde VideoRegistry (simplificado)
                    if not video_restored:
                        try:
                            from app.video_registry import VideoRegistry
                            registry = VideoRegistry()
                            topic = storyboard_data.get('topic', '')
                            category = storyboard_data.get('category', '')
                            if topic:
                                videos = registry.get_all_videos(video_type='long', category=category if category else None, limit=10)
                                matching_videos = [v for v in videos if v.get('topic') == topic]
                                if matching_videos:
                                    video_data = matching_videos[0]
                                    video_path = video_data.get('video_path')
                                    if video_path and os.path.exists(video_path):
                                        self.studio_tab.last_generated_video_data = {
                                            'video_path': video_path,
                                            'video_id': video_data.get('video_id'),
                                            'topic': topic,
                                            'category': category,
                                            'script': storyboard_data.get('script', ''),
                                            'duration': video_data.get('duration', 0)
                                        }
                                        self.studio_tab.log(f"    Referencia al video restaurada desde Registry: {os.path.basename(video_path)}")
                                        video_restored = True
                                        if hasattr(self.studio_tab, 'btn_publish_teaser'):
                                            self.studio_tab.btn_publish_teaser.setEnabled(True)
                        except Exception as e:
                            self.studio_tab.log(f"   ️ No se pudo restaurar desde VideoRegistry: {e}")

                    # Método 3: Buscar en directorio de salida (simplificado)
                    if not video_restored:
                        try:
                            from pipeline.auto_video_generator_v2 import VideoConfig
                            import glob
                            from datetime import datetime, timedelta
                            output_dir = VideoConfig.OUTPUT_DIR
                            if output_dir.exists():
                                video_pattern = str(output_dir / "youtube_*.mp4")
                                videos = glob.glob(video_pattern)
                                if videos:
                                    valid_videos = [v for v in videos if os.path.exists(v) and os.path.getsize(v) / (1024 * 1024) > 1]
                                    if valid_videos:
                                        valid_videos.sort(key=lambda v: (not '_with_subs' in v, -os.path.getmtime(v)))
                                        video_path = valid_videos[0]
                                        if video_path and os.path.exists(video_path):
                                            self.studio_tab.last_generated_video_data = {
                                                'video_path': video_path,
                                                'video_id': None,
                                                'topic': storyboard_data.get('topic', ''),
                                                'category': storyboard_data.get('category', ''),
                                                'script': storyboard_data.get('script', ''),
                                                'duration': 0
                                            }
                                            file_size = os.path.getsize(video_path) / (1024 * 1024)
                                            self.studio_tab.log(f"    Video encontrado en directorio de salida: {os.path.basename(video_path)} ({file_size:.1f} MB)")
                                            video_restored = True
                        except Exception as e:
                            self.studio_tab.log(f"   ️ No se pudo buscar video en directorio de salida: {e}")

                    if not video_restored:
                        self.studio_tab.log("   ️ No se pudo encontrar el archivo del video, pero los botones están habilitados")

            # Restaurar estado de thumbnails del proyecto
            self._sync_thumbnail_state(project_path, project_data)

            restored_thumbnail_path = (
                getattr(self.studio_tab, 'selected_thumbnail_path', None)
                or self._resolve_project_media_path(project_path, project_data.get('thumbnail_path'))
            )
            if restored_thumbnail_path and os.path.exists(restored_thumbnail_path):
                self.studio_tab.log(f"   ️ Thumbnail encontrado: {os.path.basename(restored_thumbnail_path)}")
            elif project_data.get('thumbnail_path'):
                self.studio_tab.log(f"   ️ Thumbnail no encontrado en: {project_data.get('thumbnail_path')}")

            self.studio_tab.log(f"\n Proyecto cargado exitosamente")
            return True

        except Exception as e:
            self.studio_tab.log(f" Error cargando proyecto desde ruta: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.studio_tab, "Error", f"Error cargando proyecto:\n\n{str(e)}")
        finally:
            if load_token is not None and hasattr(self.studio_tab, '_end_project_load'):
                self.studio_tab._end_project_load(load_token)
