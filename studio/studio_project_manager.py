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


from studio.project_thumbnail_state_mixin import ProjectThumbnailStateMixin


class StudioProjectManager(ProjectThumbnailStateMixin, ProjectLoadMixin, ProjectSaveMixin, ProjectMediaMixin):
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















