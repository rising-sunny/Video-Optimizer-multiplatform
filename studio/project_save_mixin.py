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


class ProjectSaveMixin:
    def save_project(self):
        """Guarda el estado actual del proyecto con aislamiento completo"""

        try:
            if getattr(self.studio_tab, '_loading_project', False):
                print("[ProjectSave] Omitiendo guardado manual durante carga de proyecto")
                return

            # Sincronizar segmentos del Timeline Editor con last_storyboard_data antes de guardar
            self._sync_timeline_editor_to_storyboard()

            # Usar el nuevo sistema de gestión de proyectos v2.0
            from app.project_manager_v2 import ProjectManagerV2


            # Recopilar configuraciones actuales

            # Obtener topic y category del parent_gui si están disponibles

            topic = ''

            category = ''

            if hasattr(self.studio_tab, 'parent_gui'):

                if hasattr(self.studio_tab.parent_gui, 'topic_input'):

                    topic = self.studio_tab.parent_gui.topic_input.text().strip()

                if hasattr(self.studio_tab.parent_gui, 'category_combo'):

                    category = self.studio_tab.parent_gui.category_combo.currentText()


            # Obtener voice_id correctamente

            selected_voice = self.studio_tab.voice_combo.currentText()

            voice_id = None

            if selected_voice and selected_voice != "Cargando voces...":

                voice_info = self.studio_tab.elevenlabs_voices.get(selected_voice, {})

                voice_id = voice_info.get('id')


            config = {
                **project_channel_config(self.studio_tab),
                'topic': topic,

                'category': category,

                'platform': self.studio_tab.platform_combo.currentText(),

                'platform_key': self.studio_tab.get_selected_platform_key() if hasattr(self.studio_tab, 'get_selected_platform_key') else self.studio_tab.platform_combo.currentText(),

                'video_format': self.studio_tab.get_selected_video_format() if hasattr(self.studio_tab, 'get_selected_video_format') else '16:9',

                'duration': self.studio_tab.duration_slider.value(),

                'language': 'es' if self.studio_tab.lang_es.isChecked() else 'en',

                'voice_id': voice_id,

                'voice_name': selected_voice if selected_voice and selected_voice != "Cargando voces..." else None,  # Guardar también el nombre para restaurar

                'style': self.studio_tab.style_combo.currentText(),

                'opening_style': self.studio_tab.get_selected_opening_style() if hasattr(self.studio_tab, 'get_selected_opening_style') else 'hook_overlay_v1',

                # Se guarda SIEMPRE, no solo con subtitulos activados: al
                # apagarlos y volver a encenderlos se perdia el estilo elegido.
                'subtitle_style': self.studio_tab.subtitle_style_combo.currentText() if hasattr(self.studio_tab, 'subtitle_style_combo') else None,

                'subtitles_enabled': self.studio_tab.subtitles_check.isChecked(),

                'overlays_enabled': self.studio_tab.overlays_check.isChecked() if hasattr(self.studio_tab, 'overlays_check') else False,

                'research_enabled': self.studio_tab.research_check.isChecked() if hasattr(self.studio_tab, 'research_check') else False,

                'music_enabled': self.studio_tab.music_check.isChecked() if hasattr(self.studio_tab, 'music_check') else False,

                'selected_music_path': getattr(self.studio_tab, 'selected_music_path', None),

                'selected_music_metadata': getattr(self.studio_tab, 'selected_music_metadata', None),

                # Opciones de Auto Video Studio Pro

                'image_provider': self.studio_tab.image_provider_combo.currentText() if hasattr(self.studio_tab, 'image_provider_combo') else "Auto (Inteligente)",

                'visual_mode': 'static' if (hasattr(self.studio_tab, 'visual_static') and self.studio_tab.visual_static.isChecked()) else 'mixed',

                'cinematic_enabled': self.studio_tab.cinematic_check.isChecked() if hasattr(self.studio_tab, 'cinematic_check') else True,

                'cinematic_preset': self.studio_tab.cinematic_preset_combo.currentText() if hasattr(self.studio_tab, 'cinematic_preset_combo') else " Auto-Detect (Inteligente)",

                'cinematic_intensity': self.studio_tab.cinematic_intensity_combo.currentData() if hasattr(self.studio_tab, 'cinematic_intensity_combo') else "auto",

                'transition_type': self.studio_tab.transition_type_combo.currentText() if hasattr(self.studio_tab, 'transition_type_combo') else " Fade Suave",

                'transition_duration': self.studio_tab.transition_duration_spin.value() if hasattr(self.studio_tab, 'transition_duration_spin') else 0.5,

                'transition_sfx_enabled': self.studio_tab.is_transition_sfx_enabled() if hasattr(self.studio_tab, 'is_transition_sfx_enabled') else True,

                'transition_sfx_path': self.studio_tab.get_transition_sfx_path() if hasattr(self.studio_tab, 'get_transition_sfx_path') else None,

                'images_per_segment_ratio': self.studio_tab.images_per_segment_spin.value() if hasattr(self.studio_tab, 'images_per_segment_spin') else 1

            }


            # Determinar progreso

            # Verificar si hay imágenes generadas en los segmentos

            images_done = False

            if self.studio_tab.last_storyboard_data and self.studio_tab.last_storyboard_data.get(

                'segments'):

                segments = self.studio_tab.last_storyboard_data.get('segments', [])

                # Considerar que las imágenes están hechas si al menos un

                # segmento tiene image_path

                images_done = any(seg.get('image_path') for seg in segments)


            progress = {

                'storyboard_done': self.studio_tab.last_storyboard_data is not None,

                'images_done': images_done,

                'video_assembled': self.studio_tab.last_generated_video_data is not None,

                'published': False

            }


            # Obtener snapshot actual del módulo de thumbnails
            thumbnail_path, thumbnail_data = self._get_thumbnail_snapshot()

            # Obtener teaser_metadata si existe
            teaser_metadata = None
            if hasattr(
                self.studio_tab,
                'last_generated_video_data') and self.studio_tab.last_generated_video_data:
                teaser_metadata = self.studio_tab.last_generated_video_data.get(
                    'teaser_metadata')

            # Crear datos del proyecto con el nuevo sistema
            project_data = ProjectManagerV2.create_project_data(
                storyboard_data=self.studio_tab.last_storyboard_data,
                config=config,
                progress=progress,
                thumbnail_path=thumbnail_path,
                thumbnail_data=thumbnail_data,
                music_path=getattr(self.studio_tab, 'selected_music_path', None),
                music_metadata=getattr(self.studio_tab, 'selected_music_metadata', None)
            )

            # Agregar datos del video generado si existe (para restaurar después)
            if self.studio_tab.last_generated_video_data:
                # Guardar solo los datos esenciales (paths, IDs, metadata)
                video_data_to_save = {
                    'video_path': self.studio_tab.last_generated_video_data.get('video_path'),
                    'video_id': self.studio_tab.last_generated_video_data.get('video_id'),
                    'topic': self.studio_tab.last_generated_video_data.get('topic'),
                    'category': self.studio_tab.last_generated_video_data.get('category'),
                    'script': self.studio_tab.last_generated_video_data.get('script'),
                    'duration': self.studio_tab.last_generated_video_data.get('duration'),
                    'segments': self.studio_tab.last_generated_video_data.get('segments'),
                    'audio_path': self.studio_tab.last_generated_video_data.get('audio_path'),
                    'teaser_video_path': self.studio_tab.last_generated_video_data.get('teaser_video_path'),
                    'teaser_metadata': self.studio_tab.last_generated_video_data.get('teaser_metadata')
                }
                project_data['generated_video_data'] = video_data_to_save

            # Donde se publico (ids/urls por red): lo cruza performance_feedback.py
            if getattr(self.studio_tab, 'publish_results', None):
                project_data['publish_results'] = dict(self.studio_tab.publish_results)

            # Agregar teaser_metadata al proyecto si existe (legacy)
            if teaser_metadata:
                project_data['teaser_metadata'] = teaser_metadata

            # Verificar si ya existe un proyecto cargado
            project_path = None
            if hasattr(self.studio_tab, 'current_project_path') and self.studio_tab.current_project_path:
                if os.path.exists(self.studio_tab.current_project_path):
                    # Preguntar si quiere guardar sobre el existente o crear uno nuevo
                    from PyQt6.QtWidgets import QMessageBox
                    reply = QMessageBox.question(
                        self.studio_tab,
                        "Guardar Proyecto",
                        f"¿Deseas guardar sobre el proyecto existente?\n\n"
                        f"Proyecto actual: {os.path.basename(self.studio_tab.current_project_path)}\n\n"
                        f"• Sí: Guarda los cambios en el proyecto actual\n"
                        f"• No: Crea un nuevo proyecto",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Yes
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        # Guardar sobre el proyecto existente
                        project_path = self.studio_tab.current_project_path
                        # Actualizar el proyecto existente
                        try:
                            # Sincronizar Timeline Editor antes de actualizar
                            self._sync_timeline_editor_to_storyboard()
                            
                            # Obtener la carpeta del proyecto desde el path
                            project_folder = Path(project_path).parent
                            
                            # Copiar archivos multimedia manuales antes de actualizar
                            storyboard_data_to_save = self._copy_manual_media_to_project(self.studio_tab.last_storyboard_data)
                            
                            # Copiar archivos multimedia manuales a la carpeta del proyecto
                            if storyboard_data_to_save:
                                storyboard_data_to_save = self._copy_manual_media_files(project_path, storyboard_data_to_save)
                                if storyboard_data_to_save:
                                    project_data['storyboard'] = storyboard_data_to_save
                            
                            # Procesar y copiar archivos multimedia nuevos al proyecto existente
                            from app.project_manager_v2 import ProjectManagerV2
                            updated_project_data = ProjectManagerV2._process_project_media(project_data, project_folder)
                            
                            # Leer el proyecto existente para mantener su estructura
                            with open(project_path, 'r', encoding='utf-8') as f:
                                existing_project = json.load(f)
                            
                            # Actualizar con los nuevos datos (preservar metadatos importantes)
                            if 'project_metadata' in existing_project:
                                # Preservar fecha de creación y carpeta original
                                original_created = existing_project['project_metadata'].get('created')
                                original_folder = existing_project['project_metadata'].get('project_folder')
                                updated_project_data['project_metadata'] = existing_project['project_metadata']
                                updated_project_data['project_metadata']['last_modified'] = datetime.now().isoformat()
                                if original_created:
                                    updated_project_data['project_metadata']['created'] = original_created
                                if original_folder:
                                    updated_project_data['project_metadata']['project_folder'] = original_folder
                            else:
                                updated_project_data['project_metadata'] = {
                                    'version': '2.0',
                                    'created': datetime.now().isoformat(),
                                    'last_modified': datetime.now().isoformat(),
                                    'project_folder': str(project_folder),
                                    'isolation_mode': True
                                }
                            
                            # Guardar el proyecto actualizado
                            with open(project_path, 'w', encoding='utf-8') as f:
                                json.dump(updated_project_data, f, indent=2, ensure_ascii=False)

                            self._sync_selected_music_state(project_path, updated_project_data)
                            self._sync_thumbnail_state(project_path, updated_project_data)
                            
                            self.studio_tab.log(f"\n Proyecto actualizado exitosamente")
                            self.studio_tab.log(f" Ubicación: {project_path}")
                            QMessageBox.information(
                                self.studio_tab,
                                "Proyecto Actualizado",
                                f"Proyecto actualizado exitosamente:\n\n{os.path.basename(project_path)}\n\n"
                                f"Los cambios han sido guardados en el proyecto existente."
                            )
                            return
                        except Exception as e:
                            self.studio_tab.log(f"️ Error actualizando proyecto existente: {e}")
                            import traceback
                            traceback.print_exc()
                            QMessageBox.warning(
                                self.studio_tab,
                                "Error",
                                f"No se pudo actualizar el proyecto existente:\n{str(e)}\n\n"
                                f"Se creará un nuevo proyecto en su lugar."
                            )
                            # Continuar para crear un nuevo proyecto
                    elif reply == QMessageBox.StandardButton.Cancel:
                        return  # Cancelar guardado
            
            # Si no hay proyecto existente o el usuario eligió crear uno nuevo, pedir nombre
            if not project_path:
                from PyQt6.QtWidgets import QInputDialog
                project_name, ok = QInputDialog.getText(
                    self.studio_tab,
                    "Guardar Proyecto",
                    "Nombre del proyecto:",
                    text=config.get('topic', 'Mi_Proyecto').replace(' ', '_')[:30]
                )

                if not ok or not project_name:
                    return

                # Guardar proyecto con el nuevo sistema
                project_path = ProjectManagerV2.save_project(
                    project_data, project_name)

            if project_path:
                # El nuevo sistema ya copia los archivos automáticamente
                # Guardar ruta para auto-guardado futuro
                self.studio_tab.current_project_path = project_path
                self._sync_selected_music_state(project_path)
                self._sync_thumbnail_state(project_path)

                # Guardar ruta del último proyecto
                if hasattr(self.studio_tab, '_save_last_project_path'):
                    self.studio_tab._save_last_project_path(project_path)

                if not os.path.exists(project_path) or project_path != self.studio_tab.current_project_path:
                    # Solo mostrar mensaje si es un proyecto nuevo
                    self.studio_tab.log(f"\n Proyecto guardado exitosamente con aislamiento completo")
                    self.studio_tab.log(f" Ubicación: {project_path}")
                    QMessageBox.information(
                        self.studio_tab,
                        "Proyecto Guardado",
                        f"Proyecto guardado exitosamente:\n\n{project_path}\n\n"
                        f"Todos los archivos están aislados en su propia carpeta.\n"
                        f"Puedes cargarlo más tarde para continuar desde donde quedaste."
                    )
            else:
                QMessageBox.critical(
                    self.studio_tab, "Error", "No se pudo guardar el proyecto")

        except Exception as e:
            self.studio_tab.log(f" Error guardando proyecto: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.studio_tab, "Error", f"Error guardando proyecto:\n\n{str(e)}")


    def _sync_timeline_editor_to_storyboard(self):
        """
        Sincroniza los segmentos del Timeline Editor con last_storyboard_data.
        Esto asegura que las imágenes/videos agregados manualmente se guarden.
        """
        try:
            if getattr(self.studio_tab, '_loading_project', False):
                print("[TimelineSync] Omitiendo sincronización durante carga de proyecto")
                return

            # Si el storyboard acaba de generarse, sus datos son autoritativos.
            # No borrar el flag aquí: se limpia al abrir el timeline con los
            # segmentos nuevos. Si se limpia en el primer auto-save, un timeline
            # viejo de 3 escenas vuelve a pisar el guion de 500+ segmentos.
            if getattr(self.studio_tab, '_storyboard_just_generated', False):
                print("[TimelineSync] Omitiendo sincronización: storyboard recién generado tiene prioridad sobre timeline obsoleto")
                return

            timeline_editor = self._get_timeline_editor()

            current_project_path = self._normalize_project_path(
                getattr(self.studio_tab, 'current_project_path', None)
            )
            bound_project_path = None
            if timeline_editor and hasattr(timeline_editor, 'get_bound_project_path'):
                bound_project_path = self._normalize_project_path(
                    timeline_editor.get_bound_project_path()
                )

            if current_project_path and bound_project_path and current_project_path != bound_project_path:
                print(
                    "[TimelineSync] Omitiendo sincronización de timeline ajeno: "
                    f"timeline={bound_project_path} actual={current_project_path}"
                )
                return
            
            # Si hay Timeline Editor con segmentos, sincronizar
            if timeline_editor and hasattr(timeline_editor, 'segments') and timeline_editor.segments:
                # IMPORTANTE: Hacer copia profunda de los segmentos para preservar todos los campos
                import copy
                segments_copy = copy.deepcopy(timeline_editor.segments)
                
                # IMPORTANTE: Limpiar campos None de los segmentos (si fueron eliminados, no deben estar como None)
                # Esto asegura que los campos eliminados NO se guarden en el JSON
                for seg in segments_copy:
                    # Si ya hay media explicita, un image_deleted heredado es inconsistente.
                    if seg.get('image_deleted', False) and (seg.get('image_path') or seg.get('video_path')):
                        seg.pop('image_deleted', None)
                        seg.pop('original_image_path', None)

                    # Si image_path es None, eliminarlo (no guardar como null en JSON)
                    if 'image_path' in seg and seg.get('image_path') is None:
                        del seg['image_path']
                    # Si video_path es None, eliminarlo
                    if 'video_path' in seg and seg.get('video_path') is None:
                        del seg['video_path']
                    # Si image_source está vacío o es None, eliminarlo
                    if 'image_source' in seg and (not seg.get('image_source') or seg.get('image_source') is None):
                        del seg['image_source']
                    # Si video_source está vacío o es None, eliminarlo
                    if 'video_source' in seg and (not seg.get('video_source') or seg.get('video_source') is None):
                        del seg['video_source']
                
                if not self.studio_tab.last_storyboard_data:
                    # Si no hay storyboard, crear uno nuevo con los segmentos del Timeline
                    self.studio_tab.last_storyboard_data = {
                        'segments': segments_copy,
                        'topic': getattr(self.studio_tab, 'topic', 'Video'),
                        'category': getattr(self.studio_tab, 'category', 'General')
                    }
                    print(" Storyboard creado desde Timeline Editor")
                else:
                    # IMPORTANTE: Antes de reemplazar, preservar image_path/video_path
                    # de last_storyboard_data si el Timeline Editor no los tiene.
                    # Esto evita que la sincronización borre rutas recién generadas
                    # por IA que el Timeline Editor aún no conoce.
                    existing_segments = self.studio_tab.last_storyboard_data.get('segments', [])
                    for i, seg in enumerate(segments_copy):
                        if i < len(existing_segments):
                            existing = existing_segments[i]
                            # Preservar image_path del storyboard si el timeline no lo tiene
                            if not seg.get('image_path') and existing.get('image_path'):
                                seg['image_path'] = existing['image_path']
                                if not seg.get('image_source') and existing.get('image_source'):
                                    seg['image_source'] = existing['image_source']
                            # Preservar video_path del storyboard si el timeline no lo tiene
                            if not seg.get('video_path') and existing.get('video_path'):
                                seg['video_path'] = existing['video_path']
                                if not seg.get('video_source') and existing.get('video_source'):
                                    seg['video_source'] = existing['video_source']

                    if existing_segments and len(segments_copy) < max(3, int(len(existing_segments) * 0.7)):
                        print(
                            "[TimelineSync] Omitiendo sincronización: el timeline tiene "
                            f"{len(segments_copy)} segmentos y el storyboard en memoria tiene "
                            f"{len(existing_segments)}. No se pisa una generación nueva."
                        )
                        return

                    # Actualizar los segmentos en last_storyboard_data
                    self.studio_tab.last_storyboard_data['segments'] = segments_copy
                    print(f" Sincronizados {len(segments_copy)} segmentos del Timeline Editor al storyboard")
                    
                    # Log de segmentos con imágenes/videos para debugging
                    segments_with_media = sum(1 for seg in segments_copy 
                                             if seg.get('image_path') or seg.get('video_path'))
                    if segments_with_media > 0:
                        print(f"    {segments_with_media} segmentos con imágenes/videos sincronizados")
                        for i, seg in enumerate(segments_copy):
                            if seg.get('image_path') or seg.get('video_path'):
                                img_path = seg.get('image_path', 'N/A')
                                vid_path = seg.get('video_path', 'N/A')
                                img_src = seg.get('image_source', 'N/A')
                                vid_src = seg.get('video_source', 'N/A')
                                print(f"      Segmento {i+1}:")
                                print(f"         image_path={img_path}, image_source={img_src}")
                                print(f"         video_path={vid_path}, video_source={vid_src}")
                                if img_path and img_path != 'N/A' and os.path.exists(img_path):
                                    print(f"          image_path existe: {os.path.exists(img_path)}")
                                if vid_path and vid_path != 'N/A' and os.path.exists(vid_path):
                                    print(f"          video_path existe: {os.path.exists(vid_path)}")
        except Exception as e:
            print(f"️ Error sincronizando Timeline Editor: {e}")
            import traceback
            traceback.print_exc()


    def auto_save_project(self, reason=""):
        """Auto-guarda el proyecto sin pedir confirmación"""

        try:
            if getattr(self.studio_tab, '_loading_project', False):
                print(
                    "[ProjectAutoSave] Omitiendo auto-guardado durante carga de proyecto: "
                    f"{reason}"
                )
                return
            # Sincronizar segmentos del Timeline Editor con last_storyboard_data antes de auto-guardar
            self._sync_timeline_editor_to_storyboard()

            topic_widget = getattr(getattr(self.studio_tab, 'parent_gui', None), 'topic_input', None)
            draft_topic = topic_widget.text().strip() if topic_widget else ''
            category_widget = (getattr(self.studio_tab, 'category_combo', None) or
                               getattr(getattr(self.studio_tab, 'parent_gui', None), 'category_combo', None))
            draft_category = category_widget.currentText() if category_widget else ''
            if not self.studio_tab.last_storyboard_data and not draft_topic:
                return True  # Todavía no hay contenido de proyecto.

            if self._storyboard_is_unusable(self.studio_tab.last_storyboard_data):
                print(
                    "[ProjectAutoSave] Abortado: no se persiste un storyboard de rechazo "
                    f"({reason})"
                )
                if hasattr(self.studio_tab, "log"):
                    self.studio_tab.log(
                        " No se guardó el storyboard: el texto es un rechazo del LLM."
                    )
                return

            from app.project_manager_v2 import ProjectManagerV2


            # Si ya hay un proyecto cargado, guardar en la misma ruta

            if self.studio_tab.current_project_path and os.path.exists(

                self.studio_tab.current_project_path):

                # Leer el JSON actual sin disparar el flujo completo de carga/restauracion
                import json
                with open(self.studio_tab.current_project_path, 'r', encoding='utf-8') as f:
                    project_data = json.load(f)

                if project_data:

                    # Actualizar con datos actuales

                    config = project_data.get('config', {})
                    config.update(project_channel_config(self.studio_tab))
                    config['topic'] = draft_topic or config.get('topic', '')
                    if draft_category:
                        config['category'] = draft_category

                    # Actualizar todas las opciones de Auto Video Studio Pro

                    config['image_provider'] = self.studio_tab.image_provider_combo.currentText() if hasattr(

                        self.studio_tab, 'image_provider_combo') else "Auto (Inteligente)"

                    config['visual_mode'] = 'static' if (

                        hasattr(self.studio_tab, 'visual_static') and self.studio_tab.visual_static.isChecked()) else 'mixed'

                    config['cinematic_enabled'] = self.studio_tab.cinematic_check.isChecked(

                    ) if hasattr(self.studio_tab, 'cinematic_check') else True

                    config['cinematic_preset'] = self.studio_tab.cinematic_preset_combo.currentText() if hasattr(

                        self.studio_tab, 'cinematic_preset_combo') else " Auto-Detect (Inteligente)"

                    config['cinematic_intensity'] = self.studio_tab.cinematic_intensity_combo.currentData() if hasattr(

                        self.studio_tab, 'cinematic_intensity_combo') else "auto"

                    config['transition_type'] = self.studio_tab.transition_type_combo.currentText(

                    ) if hasattr(self.studio_tab, 'transition_type_combo') else " Fade Suave"

                    config['transition_duration'] = self.studio_tab.transition_duration_spin.value(

                    ) if hasattr(self.studio_tab, 'transition_duration_spin') else 0.5

                    config['transition_sfx_enabled'] = self.studio_tab.is_transition_sfx_enabled() if hasattr(self.studio_tab, 'is_transition_sfx_enabled') else True

                    config['transition_sfx_path'] = self.studio_tab.get_transition_sfx_path() if hasattr(self.studio_tab, 'get_transition_sfx_path') else None

                    config['images_per_segment_ratio'] = self.studio_tab.images_per_segment_spin.value(

                    ) if hasattr(self.studio_tab, 'images_per_segment_spin') else 1

                    config['duration'] = self.studio_tab.duration_slider.value()

                    config['platform'] = self.studio_tab.platform_combo.currentText()

                    config['platform_key'] = self.studio_tab.get_selected_platform_key() if hasattr(self.studio_tab, 'get_selected_platform_key') else self.studio_tab.platform_combo.currentText()

                    config['video_format'] = self.studio_tab.get_selected_video_format() if hasattr(self.studio_tab, 'get_selected_video_format') else '16:9'

                    config['language'] = 'es' if self.studio_tab.lang_es.isChecked() else 'en'

                    config['style'] = self.studio_tab.style_combo.currentText()

                    config['opening_style'] = self.studio_tab.get_selected_opening_style() if hasattr(
                        self.studio_tab, 'get_selected_opening_style') else 'hook_overlay_v1'

                    config['subtitles_enabled'] = self.studio_tab.subtitles_check.isChecked(

                    ) if hasattr(self.studio_tab, 'subtitles_check') else False

                    # El estilo de subtitulos no se escribia en ESTA ruta de
                    # guardado (si en las otras dos), asi que el auto-guardado
                    # lo perdia. Se guarda siempre, no solo con subtitulos
                    # activados: si se apagan y se vuelven a encender, la
                    # eleccion sigue ahi.

                    config['subtitle_style'] = self.studio_tab.subtitle_style_combo.currentText() if hasattr(

                        self.studio_tab, 'subtitle_style_combo') else None

                    config['music_enabled'] = self.studio_tab.music_check.isChecked(

                    ) if hasattr(self.studio_tab, 'music_check') else False

                    project_data['config'] = config

                    # Actualizar storyboard (copiar imágenes/videos manuales antes)

                    storyboard_data_to_save = self._copy_manual_media_to_project(self.studio_tab.last_storyboard_data)
                    print(
                        f"[ProjectAutoSave] Guardando {len((storyboard_data_to_save or {}).get('segments') or [])} "
                        f"segmentos ({reason})"
                    )

                    # Copiar archivos físicos a la carpeta del proyecto y actualizar rutas

                    updated_storyboard = self._copy_manual_media_files(self.studio_tab.current_project_path, storyboard_data_to_save)

                    if updated_storyboard:

                        project_data['storyboard'] = updated_storyboard

                        # Re-guardar el proyecto con las rutas actualizadas

                        with open(self.studio_tab.current_project_path, 'w', encoding='utf-8') as f:

                            import json

                            json.dump(project_data, f, indent=2, ensure_ascii=False)

                    else:

                        project_data['storyboard'] = storyboard_data_to_save or {}

                    # Actualizar progreso

                    progress = project_data.get('progress', {})

                    if self.studio_tab.last_storyboard_data:

                        progress['storyboard_done'] = True

                        # Verificar si hay imágenes generadas

                        segments = self.studio_tab.last_storyboard_data.get(

                            'segments', [])

                        progress['images_done'] = any(
                            seg.get('image_path') for seg in segments)

                    if self.studio_tab.last_generated_video_data:
                        progress['video_assembled'] = True
                        # Guardar datos del video generado
                        video_data_to_save = {
                            'video_path': self.studio_tab.last_generated_video_data.get('video_path'),
                            'video_id': self.studio_tab.last_generated_video_data.get('video_id'),
                            'topic': self.studio_tab.last_generated_video_data.get('topic'),
                            'category': self.studio_tab.last_generated_video_data.get('category'),
                            'script': self.studio_tab.last_generated_video_data.get('script'),
                            'duration': self.studio_tab.last_generated_video_data.get('duration'),
                            'segments': self.studio_tab.last_generated_video_data.get('segments'),
                            'audio_path': self.studio_tab.last_generated_video_data.get('audio_path'),
                            'teaser_video_path': self.studio_tab.last_generated_video_data.get('teaser_video_path'),
                            'teaser_metadata': self.studio_tab.last_generated_video_data.get('teaser_metadata')
                        }
                        project_data['generated_video_data'] = video_data_to_save

                    if getattr(self.studio_tab, 'publish_results', None):
                        project_data['publish_results'] = dict(self.studio_tab.publish_results)

                    project_data['progress'] = progress

                    project_data = self._persist_selected_music_for_project(
                        self.studio_tab.current_project_path,
                        project_data,
                    )
                    project_data = self._persist_thumbnail_state_for_project(
                        self.studio_tab.current_project_path,
                        project_data,
                    )

                    # Guardar sin pedir nombre
                    with open(self.studio_tab.current_project_path, 'w', encoding='utf-8') as f:
                        import json
                        json.dump(
                            project_data, f, indent=2, ensure_ascii=False)

                    self._sync_thumbnail_state(self.studio_tab.current_project_path, project_data)

                    self.studio_tab.log(
                        f" Auto-guardado: {os.path.basename(self.studio_tab.current_project_path)} {reason}")

                    # Guardar ruta del último proyecto
                    if hasattr(self.studio_tab, '_save_last_project_path'):
                        self.studio_tab._save_last_project_path(self.studio_tab.current_project_path)

                    expected = len((self.studio_tab.last_storyboard_data or {}).get("segments") or [])
                    return self._verify_saved_storyboard(self.studio_tab.current_project_path, expected)

            # Si no hay proyecto cargado, crear uno nuevo con nombre automático
            # Recopilar configuraciones actuales
            topic = ''
            if hasattr(
                self.studio_tab,
                'parent_gui') and hasattr(
                    self.studio_tab.parent_gui,
                    'topic_input'):
                topic = self.studio_tab.parent_gui.topic_input.text().strip()

            config = {
                'topic': topic,
                'category': draft_category,
                **project_channel_config(self.studio_tab),
                'platform': self.studio_tab.platform_combo.currentText(),
                'platform_key': self.studio_tab.get_selected_platform_key() if hasattr(self.studio_tab, 'get_selected_platform_key') else self.studio_tab.platform_combo.currentText(),
                'video_format': self.studio_tab.get_selected_video_format() if hasattr(self.studio_tab, 'get_selected_video_format') else '16:9',
                'duration': self.studio_tab.duration_slider.value(),
                'language': 'es' if self.studio_tab.lang_es.isChecked() else 'en',
                'style': self.studio_tab.style_combo.currentText(),

                'opening_style': self.studio_tab.get_selected_opening_style() if hasattr(self.studio_tab, 'get_selected_opening_style') else 'hook_overlay_v1',
                'subtitle_style': self.studio_tab.subtitle_style_combo.currentText() if hasattr(self.studio_tab, 'subtitle_style_combo') else None,
                # Opciones de Auto Video Studio Pro
                'image_provider': self.studio_tab.image_provider_combo.currentText() if hasattr(self.studio_tab, 'image_provider_combo') else "Auto (Inteligente)",
                'visual_mode': 'static' if (hasattr(self.studio_tab, 'visual_static') and self.studio_tab.visual_static.isChecked()) else 'mixed',
                'cinematic_enabled': self.studio_tab.cinematic_check.isChecked() if hasattr(self.studio_tab, 'cinematic_check') else True,
                'cinematic_preset': self.studio_tab.cinematic_preset_combo.currentText() if hasattr(self.studio_tab, 'cinematic_preset_combo') else " Auto-Detect (Inteligente)",
                'cinematic_intensity': self.studio_tab.cinematic_intensity_combo.currentData() if hasattr(self.studio_tab, 'cinematic_intensity_combo') else "auto",
                'transition_type': self.studio_tab.transition_type_combo.currentText() if hasattr(self.studio_tab, 'transition_type_combo') else " Fade Suave",
                'transition_duration': self.studio_tab.transition_duration_spin.value() if hasattr(self.studio_tab, 'transition_duration_spin') else 0.5,
                'transition_sfx_enabled': self.studio_tab.is_transition_sfx_enabled() if hasattr(self.studio_tab, 'is_transition_sfx_enabled') else True,
                'transition_sfx_path': self.studio_tab.get_transition_sfx_path() if hasattr(self.studio_tab, 'get_transition_sfx_path') else None,
                'subtitles_enabled': self.studio_tab.subtitles_check.isChecked() if hasattr(self.studio_tab, 'subtitles_check') else False,
                'music_enabled': self.studio_tab.music_check.isChecked() if hasattr(self.studio_tab, 'music_check') else False,
                'selected_music_path': getattr(self.studio_tab, 'selected_music_path', None),
                'selected_music_metadata': getattr(self.studio_tab, 'selected_music_metadata', None)
            }

            # Verificar si hay imágenes generadas
            images_done = False
            if self.studio_tab.last_storyboard_data and self.studio_tab.last_storyboard_data.get(
                'segments'):
                segments = self.studio_tab.last_storyboard_data.get('segments', [])
                images_done = any(seg.get('image_path') for seg in segments)

            progress = {
                'storyboard_done': self.studio_tab.last_storyboard_data is not None,
                'images_done': images_done,
                'video_assembled': self.studio_tab.last_generated_video_data is not None,
            }

            # Copiar imágenes/videos manuales antes de crear los datos del proyecto
            storyboard_data_to_save = self._copy_manual_media_to_project(self.studio_tab.last_storyboard_data)
            thumbnail_path, thumbnail_data = self._get_thumbnail_snapshot()
             
            project_data = ProjectManagerV2.create_project_data(
                storyboard_data=storyboard_data_to_save,
                config=config,
                progress=progress,
                thumbnail_path=thumbnail_path,
                thumbnail_data=thumbnail_data,
                music_path=getattr(self.studio_tab, 'selected_music_path', None),
                music_metadata=getattr(self.studio_tab, 'selected_music_metadata', None)
            )

            # Generar nombre autom?tico
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_name = f"{topic or 'Proyecto'}_{timestamp}".replace(' ', '_')[
                                                                :50] + ".json"

            project_path = ProjectManagerV2.save_project(
                project_data, project_name)
            if project_path:
                self.studio_tab.current_project_path = project_path
                self._sync_selected_music_state(project_path)
                self._sync_thumbnail_state(project_path)

                # Guardar ruta del último proyecto
                if hasattr(self.studio_tab, '_save_last_project_path'):
                    self.studio_tab._save_last_project_path(project_path)

                # El nuevo sistema ya maneja la copia de archivos automáticamente
                self.studio_tab.log(f" Auto-guardado: {project_name} {reason}")
                expected = len((self.studio_tab.last_storyboard_data or {}).get("segments") or [])
                return self._verify_saved_storyboard(project_path, expected)
            return False

        except Exception as e:
            # No mostrar error en auto-guardado para no interrumpir el flujo
            self.studio_tab.log(f"️ Error en auto-guardado: {e}")
            return False


    def _persist_selected_music_for_project(self, project_path, project_data):
        """Asegura que la m?sica seleccionada quede guardada dentro de la carpeta del proyecto."""
        if not project_path or not project_data:
            return project_data

        from app.project_manager_v2 import ProjectManagerV2

        project_folder = Path(project_path).parent
        config = project_data.get('config', {})
        if not isinstance(config, dict):
            config = {}
            project_data['config'] = config

        metadata = (
            getattr(self.studio_tab, 'selected_music_metadata', None)
            or config.get('selected_music_metadata')
            or project_data.get('music_metadata')
        )

        candidate_paths = []
        for candidate in (
            getattr(self.studio_tab, 'selected_music_path', None),
            project_data.get('music_path'),
            config.get('selected_music_path'),
        ):
            if candidate:
                candidate_paths.append(candidate)

        persisted_relative_path = None
        for candidate in candidate_paths:
            candidate_path = Path(candidate)
            if not candidate_path.is_absolute():
                project_candidate = project_folder / candidate_path
                if project_candidate.exists():
                    candidate_path = project_candidate.resolve()
                elif candidate_path.exists():
                    candidate_path = candidate_path.resolve()
                else:
                    continue
            elif not candidate_path.exists():
                continue

            persisted_relative_path = ProjectManagerV2.copy_media_to_project(
                project_folder,
                str(candidate_path),
                'audio',
            )
            if persisted_relative_path:
                break

        if not persisted_relative_path:
            return project_data

        project_data['music_path'] = persisted_relative_path
        config['selected_music_path'] = persisted_relative_path

        if metadata:
            project_data['music_metadata'] = metadata
            config['selected_music_metadata'] = metadata
            self.studio_tab.selected_music_metadata = metadata

        project_data['config'] = config
        absolute_music_path = (project_folder / persisted_relative_path).resolve()
        self.studio_tab.selected_music_path = str(absolute_music_path)
        return project_data


    def _sync_selected_music_state(self, project_path, project_data=None):
        """Sincroniza en memoria la pista persistida del proyecto."""
        if not project_path:
            return

        if project_data is None:
            from app.project_manager_v2 import ProjectManagerV2
            project_data = ProjectManagerV2.load_project(project_path)

        if not project_data:
            return

        config = project_data.get('config', {})
        music_path = config.get('selected_music_path') if isinstance(config, dict) else None
        if not music_path:
            music_path = project_data.get('music_path')

        if not music_path:
            return

        music_path_obj = Path(music_path)
        if not music_path_obj.is_absolute():
            music_path_obj = Path(project_path).parent / music_path_obj

        if music_path_obj.exists():
            self.studio_tab.selected_music_path = str(music_path_obj.resolve())

        metadata = config.get('selected_music_metadata') if isinstance(config, dict) else None
        if not metadata:
            metadata = project_data.get('music_metadata')
        if metadata:
            self.studio_tab.selected_music_metadata = metadata
