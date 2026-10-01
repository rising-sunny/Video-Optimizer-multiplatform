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


from studio.project_load_mixin import ProjectLoadMixin


class ProjectThumbnailStateMixin:
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
