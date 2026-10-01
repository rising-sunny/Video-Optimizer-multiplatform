# timeline_editor_window.py
"""
Ventana separada para el Timeline Editor.
"""

import os

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel, QFrame

# Utilidades para manejar errores de Google Drive
try:
    from media.gdrive_file_utils import safe_import_module
except ImportError:
    safe_import_module = None  # Fallback si no existe el modulo


def _normalize_project_path(project_path):
    """Normaliza rutas de project.json para comparaciones robustas."""
    if not project_path:
        return None
    try:
        return os.path.normcase(os.path.realpath(str(project_path)))
    except Exception:
        return str(project_path)


class TimelineEditorWindow(QMainWindow):
    """Ventana separada para el Timeline Editor."""

    def __init__(self, parent=None):
        try:
            super().__init__(parent)
            print("[TimelineEditorWindow] Inicializando...")

            # IMPORTANTE: Guardar referencia al studio_tab (el parent suele ser AutoVideoStudioTab)
            self.studio_tab = parent if parent and hasattr(parent, "project_manager") else None
            if not self.studio_tab:
                p = parent
                while p:
                    if hasattr(p, "project_manager"):
                        self.studio_tab = p
                        break
                    p = p.parent() if hasattr(p, "parent") else None

            self.setWindowTitle("Editor de timeline")
            self.setMinimumSize(1200, 800)
            self.resize(1400, 900)

            self.setStyleSheet(
                """
                QMainWindow {
                    background-color: #f8f8f6;
                }
                QWidget {
                    color: #1f2831;
                    font-family: 'Segoe UI', 'Noto Sans', sans-serif;
                }
                QFrame#infoCard {
                    background-color: #ffffff;
                    border: 1px solid #dde3e9;
                    border-radius: 10px;
                    padding: 12px;
                }
                QLabel#infoText {
                    color: #6f7c89;
                    font-size: 9pt;
                }
                """
            )

            # Widget central
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            layout = QVBoxLayout(central_widget)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(12)

            # Header informativo
            info_card = QFrame()
            info_card.setObjectName("infoCard")
            info_layout = QVBoxLayout(info_card)
            info_layout.setContentsMargins(10, 8, 10, 8)
            info_layout.setSpacing(4)

            header = QLabel(
                "Edita segmentos, reordena clips y ajusta tiempos en un espacio de trabajo dedicado.\n"
                "Para material externo, usa los botones de cada segmento (Wikimedia, Openverse o pegar desde el portapapeles)."
            )
            header.setObjectName("infoText")
            header.setWordWrap(True)
            info_layout.addWidget(header)
            layout.addWidget(info_card)

            # Importar y crear TimelineEditorWidget con fallback seguro
            print("[TimelineEditorWindow] Importando TimelineEditorWidget...")
            if safe_import_module:
                timeline_module = safe_import_module("studio.timeline_editor_widget")
                TimelineEditorWidget = timeline_module.TimelineEditorWidget
            else:
                from studio.timeline_editor_widget import TimelineEditorWidget

            print("[TimelineEditorWindow] Creando widget del timeline...")
            self.timeline_editor = TimelineEditorWidget(studio_tab=self.studio_tab)
            self.bind_to_project(getattr(self.studio_tab, "current_project_path", None))
            layout.addWidget(self.timeline_editor, stretch=1)

            print("[TimelineEditorWindow] Inicializado correctamente")

        except Exception as e:
            print(f"[TimelineEditorWindow] ERROR critico inicializando: {e}")
            import traceback
            traceback.print_exc()

            if not hasattr(self, "timeline_editor"):
                self.timeline_editor = None

            raise

    def bind_to_project(self, project_path):
        """Asocia la ventana y su widget al proyecto actual."""
        self.bound_project_path = _normalize_project_path(project_path)
        if getattr(self, "timeline_editor", None) and hasattr(self.timeline_editor, "bind_to_project"):
            self.timeline_editor.bind_to_project(project_path)

    def get_bound_project_path(self):
        """Devuelve la ruta del proyecto asociado a esta ventana."""
        if getattr(self, "timeline_editor", None) and hasattr(self.timeline_editor, "get_bound_project_path"):
            return self.timeline_editor.get_bound_project_path()
        return getattr(self, "bound_project_path", None)

    def _should_persist_timeline_state(self):
        """Evita que un timeline viejo guarde sobre otro proyecto."""
        if self.studio_tab and getattr(self.studio_tab, "_loading_project", False):
            print("[TimelineEditorWindow] Omitiendo guardado al cerrar durante carga de proyecto")
            return False
        current_project_path = _normalize_project_path(
            getattr(self.studio_tab, "current_project_path", None) if self.studio_tab else None
        )
        bound_project_path = _normalize_project_path(self.get_bound_project_path())
        if current_project_path and bound_project_path and current_project_path != bound_project_path:
            print(
                "[TimelineEditorWindow] Omitiendo guardado al cerrar: "
                f"timeline={bound_project_path} actual={current_project_path}"
            )
            return False
        return True

    def closeEvent(self, event):
        """Maneja el cierre de la ventana."""
        try:
            print("[TimelineEditorWindow] Cerrando ventana, guardando cambios...")

            if hasattr(self, "timeline_editor") and self.timeline_editor and self._should_persist_timeline_state():
                if hasattr(self.timeline_editor, "force_save_now"):
                    self.timeline_editor.force_save_now()
                else:
                    if hasattr(self, "studio_tab") and self.studio_tab:
                        if hasattr(self.studio_tab, "project_manager"):
                            if hasattr(self.studio_tab.project_manager, "_sync_timeline_editor_to_storyboard"):
                                self.studio_tab.project_manager._sync_timeline_editor_to_storyboard()

                            if self.studio_tab.current_project_path:
                                print("[TimelineEditorWindow] Guardando proyecto antes de cerrar...")
                                try:
                                    self.studio_tab.project_manager.auto_save_project("antes de cerrar Timeline Editor")
                                    print("[TimelineEditorWindow] Proyecto guardado correctamente")
                                except Exception as save_error:
                                    print(f"[TimelineEditorWindow] Error guardando proyecto: {save_error}")

        except Exception as e:
            print(f"[TimelineEditorWindow] Error en closeEvent: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.studio_tab and getattr(self.studio_tab, "timeline_editor_window", None) is self:
                self.studio_tab.timeline_editor_window = None
            event.accept()
