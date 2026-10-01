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


class StudioProjectManager(ProjectMediaMixin):
    """Helper class para gestionar proyectos de AutoVideoStudioTab"""
    
    def __init__(self, studio_tab):
        """Inicializa el gestor con una referencia a AutoVideoStudioTab"""
        self.studio_tab = studio_tab

    @staticmethod
    def _normalize_project_path(project_path):
        """Normaliza rutas de project.json para comparaciones seguras."""
        if not project_path:
            return None
        try:
            return os.path.normcase(str(Path(project_path).resolve()))
        except Exception:
            try:
                return os.path.normcase(os.path.abspath(str(project_path)))
            except Exception:
                return str(project_path)

    def _storyboard_is_unusable(self, storyboard) -> bool:
        try:
            from pipeline.storyboard_generator import storyboard_is_unusable
            return bool(storyboard_is_unusable(storyboard))
        except Exception:
            return False

    def record_publish_results(self, results: dict) -> bool:
        """Deja en el project.json que se publico y con que id (para cruzar metricas).

        Se guarda en memoria (tab.publish_results) y en disco de inmediato: el
        staging desde el que se publica se borra al terminar, y hasta 2026-09-21
        el id de YouTube/Facebook no quedaba en ningun lado.
        """
        from publish.publish_record import merge_publish_results

        tab = self.studio_tab
        current = {"publish_results": dict(getattr(tab, "publish_results", None) or {})}
        merged = merge_publish_results(current, results or {})
        tab.publish_results = merged["publish_results"]
        path = getattr(tab, "current_project_path", None)
        if not path or not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data = merge_publish_results(data, results or {})
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            return True
        except Exception as exc:
            print(f"[Project] No se pudo registrar la publicacion: {exc}")
            return False

    def prepare_isolated_project_for_topic(self, topic: str) -> bool:
        """Detach from the current folder when the topic changed or the storyboard is a refusal.

        Returns True if the next save should create a new project folder.
        """
        tab = self.studio_tab
        existing_topic = ""
        memory = getattr(tab, "last_storyboard_data", None)
        if isinstance(memory, dict):
            existing_topic = str(memory.get("topic") or "")

        path = getattr(tab, "current_project_path", None)
        if path and os.path.exists(path) and not existing_topic:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                existing_topic = str((data.get("config") or {}).get("topic") or "")
                if not existing_topic:
                    existing_topic = str((data.get("storyboard") or {}).get("topic") or "")
            except Exception:
                existing_topic = ""

        try:
            from pipeline.storyboard_generator import topics_are_same_project
            same_topic = topics_are_same_project(existing_topic, topic)
        except Exception:
            same_topic = (str(existing_topic or "").strip().lower() == str(topic or "").strip().lower())

        poisoned = self._storyboard_is_unusable(memory)
        topic_changed = bool(path and existing_topic and topic and not same_topic)
        if not poisoned and not topic_changed:
            return False

        reason = (
            "storyboard de rechazo en memoria"
            if poisoned
            else f"tema distinto ('{existing_topic}' → '{topic}')"
        )
        print(f"[Project] Aislando proyecto nuevo: {reason}")
        if hasattr(tab, "log"):
            tab.log(f" Proyecto nuevo aislado: {reason}")
        tab.current_project_path = None
        tab._storyboard_just_generated = True
        tab.publish_results = {}   # el proyecto nuevo no hereda las publicaciones del anterior
        if poisoned:
            tab.last_storyboard_data = None
        self._close_existing_timeline_editor()
        return True

    def _verify_saved_storyboard(self, project_path, expected_segments: int) -> bool:
        try:
            with open(project_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            saved_n = len((data.get("storyboard") or {}).get("segments") or [])
            if int(saved_n) != int(expected_segments):
                print(
                    f"[ProjectAutoSave] VERIFICACIÓN FALLÓ: disco={saved_n} "
                    f"memoria={expected_segments} ({project_path})"
                )
                return False
            print(f"[ProjectAutoSave] Verificado: {saved_n} segmentos en disco")
            return True
        except Exception as exc:
            print(f"[ProjectAutoSave] No se pudo verificar el JSON: {exc}")
            return False

    def _get_timeline_editor(self):
        """Obtiene el Timeline Editor activo si existe."""
        timeline_editor = None

        if hasattr(self.studio_tab, 'timeline_editor_window') and self.studio_tab.timeline_editor_window:
            if hasattr(self.studio_tab.timeline_editor_window, 'timeline_editor'):
                timeline_editor = self.studio_tab.timeline_editor_window.timeline_editor

        if not timeline_editor and hasattr(self.studio_tab, 'timeline_editor'):
            timeline_editor = self.studio_tab.timeline_editor

        return timeline_editor

    def _close_existing_timeline_editor(self):
        """Cierra el Timeline Editor actual antes de cambiar de proyecto."""
        timeline_window = getattr(self.studio_tab, 'timeline_editor_window', None)
        if not timeline_window:
            return

        try:
            print("[ProjectLoad] Cerrando Timeline Editor previo antes de cargar otro proyecto...")
            if hasattr(timeline_window, 'isVisible') and timeline_window.isVisible():
                timeline_window.close()
        except Exception as e:
            print(f"[ProjectLoad] Warning cerrando Timeline Editor previo: {e}")
        finally:
            if getattr(self.studio_tab, 'timeline_editor_window', None) is timeline_window:
                self.studio_tab.timeline_editor_window = None

    def _get_legacy_thumbnail_path(self):
        """Mantiene compatibilidad con el flujo legado de thumbnail del parent GUI."""
        if not hasattr(self.studio_tab, 'parent_gui'):
            return None

        last_raw_image_path = getattr(self.studio_tab.parent_gui, 'last_raw_image_path', None)
        if not last_raw_image_path:
            return None

        raw_path = Path(last_raw_image_path)
        thumb_dir = raw_path.parent
        final_pattern = str(thumb_dir / "*_final.*")
        final_files = glob.glob(final_pattern)
        if final_files:
            return max(final_files, key=os.path.getmtime)
        return None

    def _get_thumbnail_snapshot(self):
        """Obtiene una copia serializable del estado actual de miniaturas del Studio."""
        thumbnail_path = getattr(self.studio_tab, 'selected_thumbnail_path', None) or self._get_legacy_thumbnail_path()

        thumbnail_data = {}
        current_thumbnail_data = getattr(self.studio_tab, 'thumbnail_data', None)
        if isinstance(current_thumbnail_data, dict):
            thumbnail_data = copy.deepcopy(current_thumbnail_data)

        thumbnail_strategy = getattr(self.studio_tab, 'thumbnail_strategy', None)
        if thumbnail_strategy and not thumbnail_data.get('thumbnail_strategy'):
            thumbnail_data['thumbnail_strategy'] = copy.deepcopy(thumbnail_strategy)

        thumbnail_variants = getattr(self.studio_tab, 'thumbnail_variants', None)
        if thumbnail_variants:
            thumbnail_data['thumbnail_variants'] = copy.deepcopy(list(thumbnail_variants))

        selected_variant_id = None
        if thumbnail_path and thumbnail_variants:
            try:
                selected_resolved = str(Path(thumbnail_path).resolve())
            except Exception:
                selected_resolved = str(thumbnail_path)

            for variant in thumbnail_variants:
                variant_path = variant.get('path')
                if not variant_path:
                    continue
                try:
                    variant_resolved = str(Path(variant_path).resolve())
                except Exception:
                    variant_resolved = str(variant_path)
                if variant_resolved == selected_resolved:
                    selected_variant_id = variant.get('id')
                    break

        if not thumbnail_path:
            thumbnail_path = thumbnail_data.get('thumbnail_path')

        if not thumbnail_path and thumbnail_variants:
            stored_variant_id = thumbnail_data.get('selected_variant_id')
            if stored_variant_id:
                for variant in thumbnail_variants:
                    if variant.get('id') == stored_variant_id and variant.get('path'):
                        thumbnail_path = variant.get('path')
                        break

        if thumbnail_path:
            thumbnail_data['thumbnail_path'] = thumbnail_path

        if not selected_variant_id:
            selected_variant_id = thumbnail_data.get('selected_variant_id')
        combo = getattr(self.studio_tab, 'thumbnail_variant_combo', None)
        if not selected_variant_id and combo and thumbnail_variants:
            current_index = combo.currentIndex()
            if 0 <= current_index < len(thumbnail_variants):
                selected_variant_id = thumbnail_variants[current_index].get('id')

        if selected_variant_id:
            thumbnail_data['selected_variant_id'] = selected_variant_id

        if not thumbnail_data and thumbnail_path:
            thumbnail_data = {'thumbnail_path': thumbnail_path}

        return thumbnail_path, thumbnail_data or None

    def _resolve_project_media_path(self, project_path, candidate):
        """Resuelve una ruta de medio relativa/absoluta dentro de un proyecto."""
        if not candidate:
            return None

        candidate_path = Path(candidate)
        if candidate_path.is_absolute() and candidate_path.exists():
            return str(candidate_path.resolve())

        if project_path:
            project_candidate = Path(project_path).parent / candidate_path
            if project_candidate.exists():
                return str(project_candidate.resolve())

        if candidate_path.exists():
            return str(candidate_path.resolve())

        return None

    def _restore_thumbnail_payload_paths(self, project_path, thumbnail_data):
        """Convierte a absolutas las rutas del payload de thumbnails."""
        if not isinstance(thumbnail_data, dict):
            return {}

        restored = copy.deepcopy(thumbnail_data)
        resolved_thumbnail = self._resolve_project_media_path(project_path, restored.get('thumbnail_path'))
        if resolved_thumbnail:
            restored['thumbnail_path'] = resolved_thumbnail

        restored_variants = []
        for variant in restored.get('thumbnail_variants', []) or []:
            if not isinstance(variant, dict):
                continue

            updated_variant = copy.deepcopy(variant)
            for path_key in ('path', 'raw_path'):
                resolved_path = self._resolve_project_media_path(project_path, updated_variant.get(path_key))
                if resolved_path:
                    updated_variant[path_key] = resolved_path
            restored_variants.append(updated_variant)

        if 'thumbnail_variants' in restored:
            restored['thumbnail_variants'] = restored_variants

        return restored

    def _persist_thumbnail_state_for_project(self, project_path, project_data):
        """Asegura que thumbnails seleccionados y variantes queden dentro de la carpeta del proyecto."""
        if not project_path or not project_data:
            return project_data

        from app.project_manager_v2 import ProjectManagerV2

        project_folder = Path(project_path).parent
        selected_thumbnail_path, thumbnail_payload = self._get_thumbnail_snapshot()

        if not thumbnail_payload and isinstance(project_data.get('thumbnail_data'), dict):
            thumbnail_payload = copy.deepcopy(project_data.get('thumbnail_data'))
        if not selected_thumbnail_path:
            selected_thumbnail_path = (
                (thumbnail_payload or {}).get('thumbnail_path')
                or project_data.get('thumbnail_path')
            )

        if not thumbnail_payload and not selected_thumbnail_path:
            return project_data

        if not isinstance(thumbnail_payload, dict):
            thumbnail_payload = {}

        def persist_thumbnail_path(path_value):
            resolved_path = self._resolve_project_media_path(project_path, path_value)
            if not resolved_path:
                return path_value

            persisted_path = ProjectManagerV2.copy_media_to_project(
                project_folder,
                resolved_path,
                'thumbnails',
            )
            return persisted_path or path_value

        persisted_variants = []
        for variant in thumbnail_payload.get('thumbnail_variants', []) or []:
            if not isinstance(variant, dict):
                continue

            updated_variant = copy.deepcopy(variant)
            for path_key in ('path', 'raw_path'):
                if updated_variant.get(path_key):
                    updated_variant[path_key] = persist_thumbnail_path(updated_variant.get(path_key))
            persisted_variants.append(updated_variant)

        if persisted_variants or 'thumbnail_variants' in thumbnail_payload:
            thumbnail_payload['thumbnail_variants'] = persisted_variants

        persisted_thumbnail_path = persist_thumbnail_path(
            selected_thumbnail_path or thumbnail_payload.get('thumbnail_path')
        )

        if not persisted_thumbnail_path:
            selected_variant_id = thumbnail_payload.get('selected_variant_id')
            if selected_variant_id:
                for variant in persisted_variants:
                    if variant.get('id') == selected_variant_id and variant.get('path'):
                        persisted_thumbnail_path = variant.get('path')
                        break

        if not persisted_thumbnail_path:
            for variant in persisted_variants:
                if variant.get('path'):
                    persisted_thumbnail_path = variant.get('path')
                    break

        if persisted_thumbnail_path:
            thumbnail_payload['thumbnail_path'] = persisted_thumbnail_path
            project_data['thumbnail_path'] = persisted_thumbnail_path
        elif project_data.get('thumbnail_path'):
            thumbnail_payload['thumbnail_path'] = project_data.get('thumbnail_path')

        if thumbnail_payload:
            project_data['thumbnail_data'] = thumbnail_payload

        return project_data

    def _sync_thumbnail_state(self, project_path, project_data=None):
        """Sincroniza el estado visual y en memoria del thumbnail seleccionado."""
        if not project_path:
            return

        if project_data is None:
            from app.project_manager_v2 import ProjectManagerV2
            project_data = ProjectManagerV2.load_project(project_path)

        if not project_data:
            return

        thumbnail_data = self._restore_thumbnail_payload_paths(
            project_path,
            project_data.get('thumbnail_data'),
        )
        thumbnail_path = (
            thumbnail_data.get('thumbnail_path')
            if isinstance(thumbnail_data, dict)
            else None
        ) or self._resolve_project_media_path(project_path, project_data.get('thumbnail_path'))

        if hasattr(self.studio_tab, 'restore_thumbnail_state'):
            self.studio_tab.restore_thumbnail_state(
                thumbnail_data=thumbnail_data,
                thumbnail_path=thumbnail_path,
            )
        else:
            self.studio_tab.selected_thumbnail_path = thumbnail_path or None

        if hasattr(self.studio_tab, 'parent_gui'):
            self.studio_tab.parent_gui.last_raw_image_path = thumbnail_path or None
            self.studio_tab.parent_gui.last_thumbnail_path = thumbnail_path or None
            if hasattr(self.studio_tab.parent_gui, '_update_thumbnail_preview'):
                self.studio_tab.parent_gui._update_thumbnail_preview(thumbnail_path)

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

