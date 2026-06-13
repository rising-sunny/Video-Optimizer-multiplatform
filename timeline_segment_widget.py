# timeline_segment_widget.py
"""
Widget individual para cada segmento en el timeline.
ExtraÃ­do de timeline_editor_widget.py para mejorar la organizaciÃ³n del cÃ³digo.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QDialog, QMessageBox, QMenu, QCheckBox, QFileDialog, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QProcess, QEvent, QUrl
from PyQt6.QtGui import QDrag, QPixmap, QCursor, QColor
import os
import tempfile
from pathlib import Path

DEBUG_PREVIEW = str(os.getenv("VIDEO_OPT_DEBUG_PREVIEW", "0")).strip().lower() in ("1", "true", "yes", "on")
SUPPORTED_IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".avif", ".gif", ".tif", ".tiff"
}
SUPPORTED_VIDEO_EXTENSIONS = (
    ".mp4", ".webm", ".avi", ".mov", ".mkv", ".ogv", ".mpeg", ".mpg"
)
MANUAL_IMAGE_DRAG_MIME = "application/x-video-optimizer-manual-image"
MANUAL_IMAGE_SOURCES = {"local", "wikimedia", "bing_images", "google_images", "openverse"}
AI_IMAGE_SOURCES = {"leonardo_ai", "leonardo", "fal_ai", "fal", "runway", "eden"}
AI_IMAGE_PATH_HINTS = ("generated_media", "leonardo", "runway", "fal", "eden", "thumb_")


def _local_abs(path_value) -> str:
    """Normaliza ruta local evitando Path.resolve() (puede derivar a UNC/WebDAV)."""
    return os.path.normpath(os.path.abspath(str(path_value)))


# Cache global de pixmaps para evitar recargar imagenes/thumbnails de video en cada click
# Clave: (ruta_archivo, mtime) -> QPixmap escalado
_pixmap_cache = {}
_PIXMAP_CACHE_MAX = 200  # Maximo de entradas en cache


def _get_cached_pixmap(file_path):
    """Retorna pixmap cacheado si existe y el archivo no cambio, o None."""
    try:
        mtime = os.path.getmtime(file_path)
        key = (file_path, mtime)
        return _pixmap_cache.get(key)
    except OSError:
        return None


def _set_cached_pixmap(file_path, pixmap):
    """Guarda pixmap en cache."""
    try:
        mtime = os.path.getmtime(file_path)
        key = (file_path, mtime)
        if len(_pixmap_cache) >= _PIXMAP_CACHE_MAX:
            # Eliminar la mitad mas vieja
            keys = list(_pixmap_cache.keys())
            for k in keys[:len(keys) // 2]:
                del _pixmap_cache[k]
        _pixmap_cache[key] = pixmap
    except OSError:
        pass


class TimelineSegment(QFrame):
    """
    Widget individual para cada segmento en el timeline.
    Representa un clip visual con su informacion.
    """

    clicked = pyqtSignal(int)  # Emite el Ã­ndice cuando se hace click
    deleted = pyqtSignal(int)  # Emite cuando se elimina
    moved = pyqtSignal(int, int)  # Emite (from_index, to_index) al mover
    image_deleted = pyqtSignal(int)  # Emite cuando se marca la imagen como eliminada (muestra negra)
    image_removed = pyqtSignal(int)  # Emite cuando se elimina completamente la imagen del segmento
    image_restored = pyqtSignal(int)  # Emite cuando se restaura la imagen del segmento
    video_deleted = pyqtSignal(int)  # Emite cuando se elimina el video del segmento
    wikimedia_search_requested = pyqtSignal(int)  # Emite cuando se solicita bÃºsqueda de Wikimedia
    openverse_images_search_requested = pyqtSignal(int)  # Emite cuando se solicita bÃºsqueda de Openverse (Gratis)
    pexels_video_search_requested = pyqtSignal(int)  # Emite cuando se solicita bÃºsqueda de videos de Pexels
    wikimedia_video_search_requested = pyqtSignal(int)  # Emite cuando se solicita bÃºsqueda de videos histÃ³ricos en Wikimedia
    internet_archive_video_search_requested = pyqtSignal(int)  # Emite cuando se solicita bÃºsqueda de videos histÃ³ricos en Internet Archive
    youtube_video_search_requested = pyqtSignal(int)  # Emite cuando se solicita bÃºsqueda de videos en YouTube
    regenerate_ai_image_requested = pyqtSignal(int)  # Emite cuando se solicita regenerar imagen con IA
    video_edit_requested = pyqtSignal(int)  # Emite cuando se solicita editar el video del segmento
    local_image_requested = pyqtSignal(int)  # Emite cuando se solicita insertar imagen local
    clipboard_image_requested = pyqtSignal(int)  # Emite cuando se solicita pegar una imagen del portapapeles
    local_image_dropped = pyqtSignal(int, str)  # Emite cuando se suelta una imagen local sobre el segmento
    manual_image_move_requested = pyqtSignal(int, int)  # Emite (source_index, target_index) al mover una imagen manual
    local_video_requested = pyqtSignal(int)  # Emite cuando se solicita insertar video local
    local_video_dropped = pyqtSignal(int, str)  # Emite cuando se suelta un video local sobre el segmento
    regenerate_text_requested = pyqtSignal(int)  # Emite cuando se solicita regenerar texto narrativo del segmento
    recraft_prompts_copy_requested = pyqtSignal(int)  # Emite cuando se solicita copiar los prompts Recraft
    generate_fal_image_requested = pyqtSignal(int)   # Generar imagen con FAL.AI (boton directo)
    animate_fal_video_requested = pyqtSignal(int)    # Animar imagen a video con FAL.AI I2V

    def __init__(self, index, segment_data, parent=None, defer_media_load=False,
                 compact_image_mode=False, fal_mode=False):
        super().__init__(parent)
        self.index = index
        self.segment_data = segment_data
        self.is_selected = False
        self.is_checked = False  # Para selecciÃ³n mÃºltiple
        self.drag_start_position = None
        self._cached_project_dir = None  # Cache para evitar traversal del arbol de widgets
        self._cached_project_name = None
        self._last_preview_path = None  # Ruta del ultimo preview cargado (para evitar recargas)
        self._thumb_process = None
        self._thumb_temp_path = None
        self._thumb_target_path = None
        self._thumb_request_id = 0
        self._drop_target_active = False
        self._image_drag_start_position = None
        self._image_drag_started = False
        # Modo compacto: oculta el thumbnail propio porque el segmento forma parte
        # de un GroupedSegmentsWidget que muestra una imagen grande compartida.
        self.compact_image_mode = bool(compact_image_mode)
        self._fal_mode = bool(fal_mode)

        # Debug: verificar si el segmento tiene image_path vÃ¡lido (no eliminado)
        if DEBUG_PREVIEW and 'image_path' in segment_data and segment_data['image_path'] and not segment_data.get('image_deleted', False):
            print(f"[TimelineSegment #{index + 1}] Inicializando con image_path: {segment_data['image_path']}")

        self.setup_ui()
        self.update_display(refresh_media=not defer_media_load)

    def _get_project_dir(self):
        """Obtiene el directorio del proyecto con cache para evitar traversal repetido."""
        if self._cached_project_dir is not None:
            return self._cached_project_dir, self._cached_project_name

        # Primero intentar desde _project_path_hint (inyectado por TimelineEditorWidget)
        project_hint = self.segment_data.get('_project_path_hint')
        if project_hint:
            hinted_dir = Path(project_hint)
            if hinted_dir.exists():
                self._cached_project_dir = hinted_dir
                self._cached_project_name = hinted_dir.name
                return self._cached_project_dir, self._cached_project_name

        # Fallback: traversal del arbol de widgets (solo 1 vez)
        try:
            parent = self.parent()
            while parent:
                if hasattr(parent, 'studio_tab') and hasattr(parent.studio_tab, 'current_project_path'):
                    if parent.studio_tab.current_project_path:
                        project_path_obj = Path(parent.studio_tab.current_project_path)
                        self._cached_project_dir = project_path_obj.parent
                        self._cached_project_name = project_path_obj.stem
                        return self._cached_project_dir, self._cached_project_name
                parent = parent.parent() if hasattr(parent, 'parent') else None
        except Exception:
            pass

        return None, None

    def setup_ui(self):
        """Configura la interfaz del segmento"""
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        if self.compact_image_mode:
            # En modo compacto el thumbnail propio se oculta; la imagen la muestra
            # el GroupedSegmentsWidget padre como columna izquierda.
            self.setMinimumHeight(90)
            self.setMaximumHeight(120)
        else:
            self.setMinimumHeight(225)  # Aumentar altura mÃ­nima para acomodar preview mÃ¡s grande
            self.setMaximumHeight(290)  # Aumentar altura mÃ¡xima
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAcceptDrops(True)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # Header con checkbox, nÃºmero y duraciÃ³n
        header_layout = QHBoxLayout()
        
        # Checkbox para selecciÃ³n mÃºltiple
        self.checkbox = QCheckBox()
        self.checkbox.setToolTip("Seleccionar para eliminaciÃ³n masiva")
        self.checkbox.stateChanged.connect(self.on_checkbox_changed)
        header_layout.addWidget(self.checkbox)
        
        self.number_label = QLabel()
        self.number_label.setStyleSheet("""
            QLabel {
                background-color: #f2f4f7;
                color: #1f2831;
                padding: 3px 8px;
                border-radius: 3px;
                font-weight: bold;
                font-size: 11pt;
                border: 1px solid #d6dde5;
            }
        """)
        header_layout.addWidget(self.number_label)
        
        header_layout.addStretch()
        
        self.duration_label = QLabel()
        self.duration_label.setStyleSheet("color: #6f7c89; font-size: 9pt;")
        header_layout.addWidget(self.duration_label)

        self.btn_regenerate_text = QPushButton("Regen texto")
        self.btn_regenerate_text.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.btn_regenerate_text.setToolTip(
            "Regenera el texto narrativo de este segmento usando el contexto completo del guion."
        )
        self.btn_regenerate_text.setMinimumHeight(24)
        self.btn_regenerate_text.setStyleSheet("""
            QPushButton {
                padding: 2px 8px;
                font-size: 8pt;
            }
        """)
        self.btn_regenerate_text.clicked.connect(self._on_regenerate_text_clicked)
        header_layout.addWidget(self.btn_regenerate_text)
        
        layout.addLayout(header_layout)
        
        # Texto del segmento (preview)
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setStyleSheet("""
            QLabel {
                color: #2f3b47;
                font-size: 9pt;
                padding: 4px;
                background-color: #f7f8fa;
                border-radius: 3px;
                border: 1px solid #ebeff3;
            }
        """)
        layout.addWidget(self.text_label)
        
        # Imagen preview (nuevo)
        image_container = QWidget()
        image_container_layout = QVBoxLayout(image_container)
        image_container_layout.setContentsMargins(0, 0, 0, 0)
        image_container_layout.setSpacing(2)
        
        self.image_preview = QLabel()
        # Aumentar tamaÃ±o para que se vea mejor la imagen completa
        self.image_preview.setMinimumSize(200, 150)
        self.image_preview.setMaximumSize(200, 150)
        self.image_preview.setStyleSheet("""
            QLabel {
                background-color: #fbfcfd;
                border: 1px solid #dde3e9;
                border-radius: 4px;
            }
        """)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setText("Sin imagen")
        self.image_preview.setScaledContents(True)  # Esto harÃ¡ que la imagen se escale para llenar el espacio
        self.image_preview.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.image_preview.mousePressEvent = self.on_image_mouse_press
        self.image_preview.mouseMoveEvent = self.on_image_mouse_move
        self.image_preview.mouseReleaseEvent = self.on_image_mouse_release
        image_container_layout.addWidget(self.image_preview)
        
        # Indicador de estado de imagen (generada vs encontrada)
        self.image_status_label = QLabel()
        self.image_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_status_label.setStyleSheet("""
            QLabel {
                color: #6f7c89;
                font-size: 7pt;
                padding: 2px;
            }
        """)
        self.image_status_label.setMaximumHeight(15)
        image_container_layout.addWidget(self.image_status_label)

        prompt_buttons_layout = QHBoxLayout()
        prompt_buttons_layout.setContentsMargins(0, 0, 0, 0)
        prompt_buttons_layout.setSpacing(4)

        self.btn_copy_recraft_prompts = QPushButton("Copiar Prompts")
        self.btn_copy_recraft_prompts.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.btn_copy_recraft_prompts.setToolTip(
            "Copia el prompt y negative prompt Recraft de este segmento."
        )
        self.btn_copy_recraft_prompts.setMinimumHeight(24)
        self.btn_copy_recraft_prompts.setStyleSheet("""
            QPushButton {
                padding: 2px 8px;
                font-size: 8pt;
            }
        """)
        self.btn_copy_recraft_prompts.clicked.connect(self._on_copy_recraft_prompts_clicked)
        prompt_buttons_layout.addWidget(self.btn_copy_recraft_prompts)

        _fal_btn_style = """
            QPushButton {
                padding: 2px 6px;
                font-size: 8pt;
                background-color: #1a1a2e;
                color: #e0e0ff;
                border: 1px solid #4a4aaa;
                border-radius: 3px;
            }
            QPushButton:hover { background-color: #2a2a4e; }
            QPushButton:disabled { background-color: #3a3a4e; color: #888; }
        """
        self.btn_fal_image = QPushButton("Generar")
        self.btn_fal_image.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.btn_fal_image.setToolTip("Genera imagen para este segmento con FAL.AI (sin confirmacion)")
        self.btn_fal_image.setMinimumHeight(24)
        self.btn_fal_image.setStyleSheet(_fal_btn_style)
        self.btn_fal_image.clicked.connect(lambda: self.generate_fal_image_requested.emit(self.index))
        self.btn_fal_image.setVisible(False)
        prompt_buttons_layout.addWidget(self.btn_fal_image)

        self.btn_fal_animate = QPushButton("Animar")
        self.btn_fal_animate.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.btn_fal_animate.setToolTip("Anima la imagen a video con FAL.AI (I2V)")
        self.btn_fal_animate.setMinimumHeight(24)
        self.btn_fal_animate.setStyleSheet(_fal_btn_style)
        self.btn_fal_animate.clicked.connect(lambda: self.animate_fal_video_requested.emit(self.index))
        self.btn_fal_animate.setVisible(False)
        prompt_buttons_layout.addWidget(self.btn_fal_animate)

        image_container_layout.addLayout(prompt_buttons_layout)

        layout.addWidget(image_container)
        # Guardamos referencia para poder ocultar/mostrar todo el bloque de imagen
        # cuando el segmento forma parte de un GroupedSegmentsWidget.
        self.image_container = image_container
        if self.compact_image_mode:
            self.image_container.setVisible(False)

        for drop_target in (
            self,
            self.checkbox,
            self.number_label,
            self.duration_label,
            self.btn_regenerate_text,
            self.text_label,
            image_container,
            self.image_preview,
            self.image_status_label,
            self.btn_copy_recraft_prompts,
        ):
            self._register_drop_target(drop_target)
        
        # Footer eliminado - todas las funciones estÃ¡n en el menÃº contextual (click derecho)
        # No se necesita footer ya que todo estÃ¡ accesible desde el menÃº contextual
        
        # Estilo base
        self.update_style()
    
    def _register_drop_target(self, widget):
        """Habilita drag-and-drop en widgets hijos para captar archivos soltados sobre la tarjeta."""
        if widget is None:
            return
        widget.setAcceptDrops(True)
        if widget is not self:
            widget.installEventFilter(self)

    def _is_video_path(self, media_path) -> bool:
        """Determina si una ruta corresponde a un video segun su extension."""
        return str(media_path or "").lower().endswith(SUPPORTED_VIDEO_EXTENSIONS)

    def _resolve_existing_media_path(self, media_path):
        """Resuelve rutas relativas del proyecto para acciones de UI."""
        if not media_path:
            return None

        media_path_str = str(media_path).strip()
        if not media_path_str:
            return None

        candidate_paths = []
        try:
            media_path_obj = Path(media_path_str)
        except Exception:
            media_path_obj = None

        if os.path.isabs(media_path_str):
            candidate_paths.append(Path(media_path_str))
        else:
            project_dir, project_name = self._get_project_dir()
            if project_dir:
                candidate_paths.append(project_dir / media_path_str)
                if media_path_obj is not None:
                    filename = media_path_obj.name
                    candidate_paths.append(project_dir / "project_media" / filename)
                    if project_name:
                        candidate_paths.append(project_dir / f"{project_name}_media" / filename)

            candidate_paths.append(Path.cwd() / media_path_str)

        candidate_paths.append(Path(_local_abs(media_path_str)))

        seen_paths = set()
        for candidate in candidate_paths:
            try:
                normalized_candidate = _local_abs(candidate)
            except Exception:
                normalized_candidate = str(candidate)
            if normalized_candidate in seen_paths:
                continue
            seen_paths.add(normalized_candidate)
            try:
                if os.path.exists(normalized_candidate):
                    return normalized_candidate
            except OSError:
                continue

        return None

    def _get_resolved_segment_media_paths(self):
        """Resuelve las rutas reales de imagen y video del segmento actual."""
        resolved_image_path = self._resolve_existing_media_path(self.segment_data.get("image_path"))
        resolved_video_path = self._resolve_existing_media_path(self.segment_data.get("video_path"))
        if not resolved_video_path and resolved_image_path and self._is_video_path(resolved_image_path):
            resolved_video_path = resolved_image_path
        return resolved_image_path, resolved_video_path

    def _clipboard_contains_pasteable_image(self):
        """Indica si el portapapeles contiene una imagen utilizable o una ruta local de imagen."""
        try:
            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData() if clipboard else None
            if not mime_data:
                return False

            if mime_data.hasImage():
                return True

            if mime_data.hasUrls():
                for url in mime_data.urls():
                    if not url.isLocalFile():
                        continue
                    local_path = url.toLocalFile()
                    if os.path.isfile(local_path) and Path(local_path).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
                        return True

            text = str(mime_data.text() or "").strip().strip('"')
            if text and os.path.isfile(text) and Path(text).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
                return True
        except Exception:
            return False

        return False

    def _copy_current_image_to_clipboard(self):
        """Copia la imagen actual del segmento al portapapeles para reutilizarla en otro segmento."""
        try:
            if self.segment_data.get("image_deleted", False):
                return False

            image_path, video_path = self._get_resolved_segment_media_paths()
            if not image_path or video_path or self._is_video_path(image_path):
                return False

            clipboard = QApplication.clipboard()
            if not clipboard:
                return False

            mime_data = QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(image_path)])
            mime_data.setText(image_path)

            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                mime_data.setImageData(pixmap.toImage())

            clipboard.setMimeData(mime_data)
            return True
        except Exception:
            return False

    def _on_copy_current_image_requested(self):
        """Maneja la acción de copiar imagen desde el menú contextual."""
        if self._copy_current_image_to_clipboard():
            return

        QMessageBox.warning(
            self,
            "No se pudo copiar la imagen",
            "Este segmento no tiene una imagen copiable o no se pudo acceder al archivo."
        )

    def _has_movable_manual_image(self):
        """Indica si la miniatura actual puede arrastrarse a otro segmento."""
        if self.segment_data.get("image_deleted", False):
            return False

        resolved_image_path, resolved_video_path = self._get_resolved_segment_media_paths()
        if not resolved_image_path or resolved_video_path or self._is_video_path(resolved_image_path):
            return False

        image_source = str(self.segment_data.get("image_source", "")).lower().strip()
        if image_source in MANUAL_IMAGE_SOURCES:
            return True
        if image_source in AI_IMAGE_SOURCES:
            return False

        image_path_hint = str(self.segment_data.get("image_path", "")).lower()
        return not any(token in image_path_hint for token in AI_IMAGE_PATH_HINTS)

    def _extract_internal_manual_image_source_index(self, mime_data):
        """Obtiene el indice del segmento origen desde un drag interno."""
        if mime_data is None or not mime_data.hasFormat(MANUAL_IMAGE_DRAG_MIME):
            return None

        try:
            raw_data = bytes(mime_data.data(MANUAL_IMAGE_DRAG_MIME)).decode("utf-8").strip()
            return int(raw_data)
        except (TypeError, ValueError):
            return None

    def _start_manual_image_drag(self):
        """Inicia el drag interno de la imagen manual actual."""
        if not self._has_movable_manual_image():
            return False

        drag = QDrag(self.image_preview)
        mime_data = QMimeData()
        mime_data.setData(MANUAL_IMAGE_DRAG_MIME, str(self.index).encode("utf-8"))
        drag.setMimeData(mime_data)

        preview_pixmap = self.image_preview.pixmap()
        if preview_pixmap and not preview_pixmap.isNull():
            drag.setPixmap(preview_pixmap)
            drag.setHotSpot(preview_pixmap.rect().center())


    def _extract_dropped_image_path(self, mime_data):
        """Obtiene la primera imagen local valida desde el mime data, si existe."""
        if mime_data is None or not mime_data.hasUrls():
            return None

        for url in mime_data.urls():
            if not url.isLocalFile():
                continue

            file_path = url.toLocalFile()
            if not file_path:
                continue

            normalized_path = _local_abs(file_path)
            if Path(normalized_path).suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            if os.path.isfile(normalized_path):
                return normalized_path

        return None

    def _extract_dropped_video_path(self, mime_data):
        """Obtiene el primer video local valido desde el mime data, si existe."""
        if mime_data is None or not mime_data.hasUrls():
            return None

        for url in mime_data.urls():
            if not url.isLocalFile():
                continue

            file_path = url.toLocalFile()
            if not file_path:
                continue

            normalized_path = _local_abs(file_path)
            if Path(normalized_path).suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
                continue
            if os.path.isfile(normalized_path):
                return normalized_path

        return None

    def _set_drop_target_active(self, active: bool):
        """Activa o desactiva el resaltado visual del segmento como destino de drop."""
        if self._drop_target_active == active:
            return
        self._drop_target_active = active
        self.update_style()

    def _handle_external_image_drag(self, event):
        """Acepta solo drops externos de archivos de imagen."""
        image_path = self._extract_dropped_image_path(getattr(event, "mimeData", lambda: None)())
        if not image_path:
            self._set_drop_target_active(False)
            event.ignore()
            return False

        self._set_drop_target_active(True)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        return True

    def _handle_external_video_drag(self, event):
        """Acepta drops externos de archivos de video."""
        video_path = self._extract_dropped_video_path(getattr(event, "mimeData", lambda: None)())
        if not video_path:
            return False

        self._set_drop_target_active(True)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        return True

    def _handle_internal_manual_image_drag(self, event):
        """Acepta el drag interno de una imagen manual desde otro segmento."""
        source_index = self._extract_internal_manual_image_source_index(
            getattr(event, "mimeData", lambda: None)()
        )
        if source_index is None or source_index == self.index:
            self._set_drop_target_active(False)
            event.ignore()
            return False

        self._set_drop_target_active(True)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        return True

    def _handle_external_image_drop(self, event):
        """Procesa el drop de una imagen local sobre el segmento."""
        image_path = self._extract_dropped_image_path(getattr(event, "mimeData", lambda: None)())
        self._set_drop_target_active(False)
        if not image_path:
            event.ignore()
            return False
        self.local_image_dropped.emit(self.index, image_path)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        return True

    def _handle_external_video_drop(self, event):
        """Procesa el drop de un video local sobre el segmento."""
        video_path = self._extract_dropped_video_path(getattr(event, "mimeData", lambda: None)())
        self._set_drop_target_active(False)
        if not video_path:
            event.ignore()
            return False
        self.local_video_dropped.emit(self.index, video_path)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        return True

    def _handle_internal_manual_image_drop(self, event):
        """Procesa el drop interno de una imagen manual desde otro segmento."""
        source_index = self._extract_internal_manual_image_source_index(
            getattr(event, "mimeData", lambda: None)()
        )
        self._set_drop_target_active(False)
        if source_index is None:
            event.ignore()
            return False

        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if source_index != self.index:
            self.manual_image_move_requested.emit(source_index, self.index)
        return True

    def update_display(self, refresh_media: bool = True):
        """Actualiza la visualizaciÃ³n con los datos del segmento"""
        # NÃºmero y duraciÃ³n
        self.number_label.setText(f"#{self.index + 1}")
        
        start = self.segment_data.get('start', 0)
        end = self.segment_data.get('end', 0)
        duration = end - start
        self.duration_label.setText(f"{duration:.1f}s")
        
        # Texto (primeros 60 caracteres)
        text = self.segment_data.get('text', '')
        preview = text[:60] + "..." if len(text) > 60 else text
        self.text_label.setText(preview)
        
        # Actualizar preview de imagen solo cuando realmente cambia media
        if refresh_media:
            self.update_image_preview()
        self._update_fal_buttons()

    def _load_pixmap_with_fallback(self, image_path: str) -> QPixmap:
        """
        Carga un QPixmap y aplica fallback con Pillow cuando Qt no puede decodificar
        el formato (por ejemplo AVIF sin plugin de imagen en Qt).
        """
        try:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                return pixmap
            if DEBUG_PREVIEW:
                print(f"[TimelineSegment #{self.index + 1}] QPixmap no pudo abrir: {image_path}")
        except Exception:
            pass

        try:
            from PIL import Image, ImageOps

            with Image.open(image_path) as img:
                img = ImageOps.exif_transpose(img)
                if img.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    alpha = img.split()[-1]
                    bg.paste(img, mask=alpha)
                    img = bg
                elif img.mode != "RGB":
                    img = img.convert("RGB")

                fd, tmp_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                try:
                    img.save(tmp_path, "PNG")
                    pixmap = QPixmap(tmp_path)
                    if not pixmap.isNull():
                        if DEBUG_PREVIEW:
                            print(f"[TimelineSegment #{self.index + 1}] Preview cargado vía Pillow: {os.path.basename(image_path)}")
                        return pixmap
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        except Exception as e:
            if DEBUG_PREVIEW:
                print(f"[TimelineSegment #{self.index + 1}] Fallback Pillow falló: {e}")

        # Fallback final: intentar rasterizar con ffmpeg (útil para builds sin soporte AVIF).
        try:
            import shutil
            import subprocess

            ffmpeg_bin = shutil.which("ffmpeg")
            if ffmpeg_bin:
                fd, tmp_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                try:
                    cmd = [ffmpeg_bin, "-y", "-v", "error", "-i", image_path, "-frames:v", "1", tmp_path]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if proc.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                        pixmap = QPixmap(tmp_path)
                        if not pixmap.isNull():
                            if DEBUG_PREVIEW:
                                print(f"[TimelineSegment #{self.index + 1}] Preview cargado vía ffmpeg: {os.path.basename(image_path)}")
                            return pixmap
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        except Exception as e:
            if DEBUG_PREVIEW:
                print(f"[TimelineSegment #{self.index + 1}] Fallback ffmpeg falló: {e}")

        return QPixmap()
    
    def update_image_preview(self):
        """Actualiza el preview de la imagen del segmento"""
        if self.compact_image_mode:
            # El preview visible lo renderiza GroupedSegmentsWidget; evitar trabajo
            # innecesario aqui reduce I/O y evita cargar miniaturas ocultas.
            self._last_raw_media_key = None
            self._last_preview_path = "__compact__"
            return
        # IMPORTANTE: Solo mostrar imÃ¡genes si tienen image_path explÃ­cito
        # NO buscar automÃ¡ticamente por assigned_filename.
        # Las imÃ¡genes solo se agregan cuando se ejecuta la generaciÃ³n de imÃ¡genes.
        image_path = self.segment_data.get('image_path', None)
        video_path = self.segment_data.get('video_path', None)
        is_deleted = self.segment_data.get('image_deleted', False)

        # Early exit: si los datos raw de media no cambiaron, evitar toda la resolucion
        # de rutas (que implica 26+ filesystem checks). Esto es critico para text-only saves.
        _raw_key = (image_path, video_path, is_deleted)
        if hasattr(self, '_last_raw_media_key') and self._last_raw_media_key == _raw_key and self._last_preview_path:
            return
        self._last_raw_media_key = _raw_key

        # Si no hay image_path pero hay video_path, usar video_path
        if not image_path and video_path:
            image_path = video_path
        
        # Si la imagen fue eliminada (marcada como deleted)
        if self.segment_data.get('image_deleted', False):
            # Mostrar imagen negra
            black_pixmap = QPixmap(200, 150)
            black_pixmap.fill(QColor(0, 0, 0))
            self.image_preview.setPixmap(black_pixmap)
            self.image_preview.setText("âš«\nEliminada")
            self._last_preview_path = "__deleted__"
            return
        
        # Si no hay image_path, intentar buscar automaticamente en project_media
        if not image_path:
            project_dir, project_name = self._get_project_dir()
            
            # NO buscar imÃ¡genes automÃ¡ticamente en project_media.
            # Solo usar imÃ¡genes explÃ­citamente asignadas en segment_data['image_path'].
            # La bÃºsqueda automÃ¡tica causaba que imÃ¡genes antiguas de sesiones previas
            # se asignaran incorrectamente a segmentos nuevos.
        
        # Resolver ruta si es relativa o no existe
        if image_path:
            original_path = image_path
            from pathlib import Path

            # Obtener directorio del proyecto (con cache)
            project_dir, project_name = self._get_project_dir()
            
            # Convertir ruta relativa a absoluta si es necesario
            if not os.path.isabs(image_path):
                # Primero intentar desde la carpeta del proyecto si estÃ¡ disponible
                if project_dir:
                    abs_path = project_dir / image_path
                    if abs_path.exists():
                        image_path = _local_abs(abs_path)
                    else:
                        # Intentar desde la carpeta _media del proyecto
                        if project_name:
                            media_dir = project_dir / f"{project_name}_media"
                            if media_dir.exists():
                                filename = Path(image_path).name
                                possible_path = media_dir / filename
                                if possible_path.exists():
                                    image_path = _local_abs(possible_path)
                
                # Si aÃºn no se resolviÃ³, intentar desde el directorio de trabajo actual
                if not os.path.exists(image_path):
                    project_root = Path.cwd()
                    abs_path = project_root / image_path
                    if abs_path.exists():
                        image_path = str(abs_path)
                    else:
                        # Intentar como ruta relativa desde el directorio actual
                        abs_path = Path(_local_abs(image_path))
                        if abs_path.exists():
                            image_path = str(abs_path)
            
            # Si aÃºn no existe (incluso si es absoluta), buscar en mÃºltiples ubicaciones
            if not os.path.exists(image_path):
                filename = os.path.basename(original_path)
                # Verificar si es un video por extensiÃ³n
                is_video = filename.lower().endswith(('.mp4', '.webm', '.avi', '.mov', '.mkv', '.ogv', '.mpeg', '.mpg'))
                
                possible_dirs = []
                
                # Agregar carpetas de medios del proyecto si estÃ¡ disponible
                if project_dir and project_name:
                    # Formato antiguo: {project_name}_media
                    media_dir_old = project_dir / f"{project_name}_media"
                    if media_dir_old.exists():
                        possible_dirs.append(media_dir_old)
                    # Formato nuevo: project_media
                    media_dir_new = project_dir / "project_media"
                    if media_dir_new.exists():
                        possible_dirs.append(media_dir_new)
                
                # Agregar directorios comunes (SOLO TEMP, NO OTROS PROYECTOS)
                possible_dirs.extend([
                    Path("auto_videos/temp/generated_media"),
                    Path("auto_videos/generated_media"),
                    Path("generated_media"),
                    # REMOVED: Path("projects") - Evitar buscar en otros proyectos para prevenir contaminaciÃ³n
                ])
                
                # Si es un video, buscar tambiÃ©n en carpetas de videos (SOLO GENERICAS)
                if is_video:
                    possible_dirs.extend([
                        Path("auto_videos/videos/pexels"),
                        Path("auto_videos/videos/wikimedia"),
                        Path("auto_videos/videos/internet_archive"),
                        Path("auto_videos/videos/youtube"),
                        Path("auto_videos/videos"),
                    ])
                
                # REMOVED: BÃºsqueda recursiva en otros proyectos
                # Esta era la causa principal de que aparecieran imÃ¡genes de otros proyectos
                
                for dir_path in possible_dirs:
                    if dir_path.exists():
                        possible_path = dir_path / filename
                        if possible_path.exists():
                            image_path = _local_abs(possible_path)
                            # Actualizar el segment_data con la ruta corregida
                            self.segment_data['image_path'] = image_path
                            if video_path == original_path:
                                self.segment_data['video_path'] = image_path
                            break
        
        # Debug: verificar estado de la ruta
        if image_path:
            exists = os.path.exists(image_path)
            if DEBUG_PREVIEW:
                print(f"[TimelineSegment #{self.index + 1}] update_image_preview: image_path={image_path}, exists={exists}")
            if not exists:
                if DEBUG_PREVIEW:
                    print(f"   âš ï¸ La ruta no existe, intentando buscar en otras ubicaciones...")
        
        # Cargar imagen o video si existe (con cache de pixmap)
        if image_path and os.path.exists(image_path):
            # Si la ruta no cambio desde la ultima carga, no recargar
            if self._last_preview_path == image_path:
                return
            self._last_preview_path = image_path

            # Verificar cache de pixmap primero (evita recargar la misma imagen)
            cached = _get_cached_pixmap(image_path)
            if cached is not None and not cached.isNull():
                self.image_preview.setPixmap(cached)
                self.image_preview.setText("")
                self._update_media_status_label(image_path)
                return
            try:
                # Verificar si es un video (por extensiÃ³n)
                is_video = image_path.lower().endswith(('.mp4', '.webm', '.avi', '.mov', '.mkv', '.ogv', '.mpeg', '.mpg'))
                
                if is_video:
                    self._start_async_video_thumbnail(image_path)
                    return
                else:
                    # Es una imagen normal
                    # Asegurar que la ruta sea absoluta y estÃ© normalizada para evitar "Protocol unknown"
                    try:
                        abs_image_path = os.path.abspath(image_path)
                        abs_image_path = os.path.normpath(abs_image_path)
                        pixmap = self._load_pixmap_with_fallback(abs_image_path)
                    except Exception as path_error:
                        print(f"âš ï¸ Error normalizando ruta de imagen: {path_error}")
                        # Intentar con la ruta original como fallback
                        pixmap = self._load_pixmap_with_fallback(image_path)
                    if not pixmap.isNull():
                        # Escalar manteniendo aspect ratio - usar tamaÃ±o completo del preview
                        scaled_pixmap = pixmap.scaled(200, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.image_preview.setPixmap(scaled_pixmap)
                        self.image_preview.setText("")
                        _set_cached_pixmap(image_path, scaled_pixmap)

                        # Determinar si es imagen generada o encontrada
                        is_generated = ('generated_media' in image_path or 
                                       'leonardo' in image_path.lower() or 
                                       'runway' in image_path.lower() or 
                                       'fal' in image_path.lower() or 
                                       'eden' in image_path.lower() or
                                       'thumb_' in image_path.lower())
                        
                        if is_generated:
                            self.image_status_label.setText("Generada")
                            self.image_status_label.setStyleSheet("""
                                QLabel {
                                    color: #27ae60;
                                    font-size: 7pt;
                                    padding: 2px;
                                    font-weight: bold;
                                }
                            """)
                            self.image_preview.setToolTip(
                                f"Imagen generada\n{os.path.basename(image_path)}\n\nClick para ver en tamano completo"
                            )
                        else:
                            image_source = str(self.segment_data.get('image_source', '')).lower()
                            if image_source == 'wikimedia':
                                self.image_status_label.setText("Wikimedia")
                                self.image_status_label.setStyleSheet("""
                                    QLabel {
                                        color: #16a085;
                                        font-size: 7pt;
                                        padding: 2px;
                                        font-weight: bold;
                                    }
                                """)
                                self.image_preview.setToolTip(
                                    f"Imagen de Wikimedia Commons\n{os.path.basename(image_path)}\n\nClick para ver en tamano completo"
                                )
                            elif image_source in ('bing_images', 'google_images'):
                                self.image_status_label.setText("Openverse")
                                self.image_status_label.setStyleSheet("""
                                    QLabel {
                                        color: #2980b9;
                                        font-size: 7pt;
                                        padding: 2px;
                                        font-weight: bold;
                                    }
                                """)
                                self.image_preview.setToolTip(
                                    f"Imagen de Openverse\n{os.path.basename(image_path)}\n\nClick para ver en tamano completo"
                                )
                            else:
                                self.image_status_label.setText("Encontrada")
                                self.image_status_label.setStyleSheet("""
                                    QLabel {
                                        color: #f39c12;
                                        font-size: 7pt;
                                        padding: 2px;
                                    }
                                """)
                                self.image_preview.setToolTip(
                                    f"Imagen encontrada\n{os.path.basename(image_path)}\n\nUsa 'Generar imagenes' para crear una nueva\n\nClick para ver en tamano completo"
                                )
                    else:
                        self.image_preview.setText("Error")
                        self.image_status_label.setText("Error")
                        self.image_preview.setToolTip("Error cargando imagen")
            except Exception as e:
                self.image_preview.setText("Error")
                self.image_status_label.setText("Error")
                self.image_preview.setToolTip(f"Error: {str(e)}")
        else:
            self.image_preview.setText("Sin imagen")
            self.image_status_label.setText("Pendiente")
            self._last_preview_path = "__none__"
            self.image_status_label.setStyleSheet("""
                QLabel {
                    color: #95a5a6;
                    font-size: 7pt;
                    padding: 2px;
                }
            """)
            self.image_preview.setToolTip("No hay imagen para este segmento.\n\nUsa el boton 'Generar imagenes' para crear una.")

    def _is_current_media_path(self, image_path: str) -> bool:
        """Verifica que el path siga siendo el media activo del segmento."""
        current_image = self.segment_data.get('image_path', None)
        current_video = self.segment_data.get('video_path', None)
        if not current_image and current_video:
            current_image = current_video
        if not current_image:
            return False
        try:
            return os.path.normcase(os.path.abspath(str(current_image))) == os.path.normcase(os.path.abspath(str(image_path)))
        except Exception:
            return str(current_image) == str(image_path)

    def _cleanup_thumbnail_temp(self, temp_path=None):
        """Limpia archivo temporal de thumbnail si existe."""
        path_to_remove = temp_path or self._thumb_temp_path
        if not path_to_remove:
            return
        try:
            if os.path.exists(path_to_remove):
                os.remove(path_to_remove)
        except Exception:
            pass
        if path_to_remove == self._thumb_temp_path:
            self._thumb_temp_path = None

    def _show_video_fallback(self, image_path):
        """Muestra placeholder de video cuando no se puede extraer miniatura."""
        self.image_preview.setText("Video")
        self.image_status_label.setText("Video")
        self.image_preview.setToolTip(f"Video\n{os.path.basename(image_path)}")
        self._last_preview_path = image_path

    def _on_async_video_thumb_finished(self, image_path, temp_path, request_id):
        """Callback cuando termina la extracciÃ³n asÃ­ncrona de thumbnail."""
        if request_id != self._thumb_request_id:
            return
        try:
            if not self._is_current_media_path(image_path):
                return

            pixmap = QPixmap()
            if temp_path and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                pixmap = QPixmap(temp_path)

            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(200, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.image_preview.setPixmap(scaled_pixmap)
                self.image_preview.setText("")
                _set_cached_pixmap(image_path, scaled_pixmap)
                self._update_media_status_label(image_path)
                self.image_preview.setToolTip(f"Video\n{os.path.basename(image_path)}\n\nClick para ver en tamano completo")
                self._last_preview_path = image_path
            else:
                self._show_video_fallback(image_path)
        except Exception:
            self._show_video_fallback(image_path)
        finally:
            # Invalidar callbacks duplicados para la misma solicitud.
            self._thumb_request_id += 1
            self._cleanup_thumbnail_temp(temp_path)
            self._thumb_process = None
            self._thumb_target_path = None

    def _start_async_video_thumbnail(self, image_path):
        """Extrae thumbnail de video sin bloquear la UI usando QProcess."""
        try:
            import shutil

            # Evitar reprocesar el mismo video si ya hay un proceso en curso
            if (
                self._thumb_process
                and self._thumb_process.state() != QProcess.ProcessState.NotRunning
                and self._thumb_target_path == image_path
            ):
                return

            ffmpeg_bin = shutil.which('ffmpeg')
            if not ffmpeg_bin:
                self._show_video_fallback(image_path)
                return

            # Cancelar proceso anterior si sigue activo
            if self._thumb_process and self._thumb_process.state() != QProcess.ProcessState.NotRunning:
                self._thumb_process.kill()

            self._cleanup_thumbnail_temp()

            temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
            os.close(temp_fd)

            self._thumb_temp_path = temp_path
            self._thumb_target_path = image_path
            self._thumb_process = QProcess(self)
            self._thumb_request_id += 1
            request_id = self._thumb_request_id
            self._thumb_process.setProgram(ffmpeg_bin)
            self._thumb_process.setArguments([
                '-y', '-v', 'error',
                '-ss', '2',
                '-i', os.path.normpath(os.path.abspath(image_path)),
                '-frames:v', '1',
                '-q:v', '5',
                temp_path
            ])

            self.image_preview.setText("Cargando video...")
            self.image_status_label.setText("Video")
            self.image_preview.setToolTip(f"Extrayendo miniatura...\n{os.path.basename(image_path)}")

            self._thumb_process.finished.connect(
                lambda _code, _status, p=image_path, t=temp_path, r=request_id: self._on_async_video_thumb_finished(p, t, r)
            )
            self._thumb_process.errorOccurred.connect(
                lambda _err, p=image_path, t=temp_path, r=request_id: self._on_async_video_thumb_finished(p, t, r)
            )
            self._thumb_process.start()
        except Exception:
            self._show_video_fallback(image_path)
    
    def _update_media_status_label(self, image_path):
        """Actualiza el label de estado segun el tipo de media (usado al retornar desde cache)."""
        is_video = image_path.lower().endswith(('.mp4', '.webm', '.avi', '.mov', '.mkv', '.ogv', '.mpeg', '.mpg'))
        if is_video:
            video_source = self.segment_data.get('video_source', 'unknown')
            source_map = {
                'youtube': ("YouTube", "#e74c3c"),
                'internet_archive': ("Internet Archive", "#d35400"),
                'wikimedia': ("Wikimedia", "#16a085"),
                'pexels': ("Pexels", "#3498db"),
            }
            label_text, color = "Video", "#9b59b6"
            for key, (name, c) in source_map.items():
                if key in video_source:
                    label_text, color = name, c
                    break
            self.image_status_label.setText(label_text)
            self.image_status_label.setStyleSheet(f"QLabel {{ color: {color}; font-size: 7pt; padding: 2px; font-weight: bold; }}")
        else:
            is_generated = any(k in image_path.lower() for k in ('generated_media', 'leonardo', 'runway', 'fal', 'eden', 'thumb_'))
            if is_generated:
                self.image_status_label.setText("Generada")
                self.image_status_label.setStyleSheet("QLabel { color: #27ae60; font-size: 7pt; padding: 2px; font-weight: bold; }")
            else:
                image_source = str(self.segment_data.get('image_source', '')).lower()
                if image_source == 'wikimedia':
                    self.image_status_label.setText("Wikimedia")
                    self.image_status_label.setStyleSheet("QLabel { color: #16a085; font-size: 7pt; padding: 2px; font-weight: bold; }")
                elif image_source in ('bing_images', 'google_images'):
                    self.image_status_label.setText("Openverse")
                    self.image_status_label.setStyleSheet("QLabel { color: #2980b9; font-size: 7pt; padding: 2px; font-weight: bold; }")
                else:
                    self.image_status_label.setText("Encontrada")
                    self.image_status_label.setStyleSheet("QLabel { color: #f39c12; font-size: 7pt; padding: 2px; }")

    def contextMenuEvent(self, event):
        """Muestra el menÃº contextual al hacer click derecho"""
        # Usar el mismo mÃ©todo show_context_menu para mantener consistencia
        self.show_context_menu(event.pos())
        event.accept()
    
    def update_style(self):
        """Actualiza el estilo segÃºn el estado"""
        if self._drop_target_active:
            self.setStyleSheet("""
                TimelineSegment {
                    background-color: #eef8f1;
                    border: 2px dashed #5b8f67;
                    border-radius: 8px;
                }
            """)
        elif self.is_selected:
            self.setStyleSheet("""
                TimelineSegment {
                    background-color: #eaf2f8;
                    border: 2px solid #7f98b2;
                    border-radius: 8px;
                }
            """)
        elif self.is_checked:
            self.setStyleSheet("""
                TimelineSegment {
                    background-color: #eef3f7;
                    border: 2px solid #aebbc8;
                    border-radius: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                TimelineSegment {
                    background-color: #ffffff;
                    border: 1px solid #dde3e9;
                    border-radius: 8px;
                }
                TimelineSegment:hover {
                    background-color: #f6f8fa;
                    border: 1px solid #9baebe;
                }
            """)
    
    def set_selected(self, selected):
        """Establece el estado de selecciÃ³n"""
        self.is_selected = selected
        self.update_style()
    
    def set_checked(self, checked):
        """Establece el estado del checkbox"""
        self.is_checked = checked
        if hasattr(self, 'checkbox'):
            self.checkbox.setChecked(checked)
        self.update_style()
    
    def on_checkbox_changed(self, state):
        """Callback cuando cambia el estado del checkbox"""
        self.is_checked = (state == Qt.CheckState.Checked.value)
        self.update_style()
        # Notificar al TimelineEditorWidget para actualizar el botÃ³n
        parent = self.parent()
        while parent:
            if hasattr(parent, 'update_delete_button_state'):
                parent.update_delete_button_state()
                break
            parent = parent.parent()

    def _on_regenerate_text_clicked(self):
        """Solicita regenerar solo el texto de este segmento."""
        self.clicked.emit(self.index)
        self.regenerate_text_requested.emit(self.index)

    def _on_copy_recraft_prompts_clicked(self):
        """Solicita copiar el prompt y negative prompt Recraft del segmento."""
        self.clicked.emit(self.index)
        self.recraft_prompts_copy_requested.emit(self.index)
    
    def mousePressEvent(self, event):
        """Maneja el click en el segmento"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
            self.drag_start_position = event.pos()
        elif event.button() == Qt.MouseButton.RightButton:
            event.ignore()
            return
    
    def mouseMoveEvent(self, event):
        """Maneja el drag del segmento"""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        
        if not self.drag_start_position:
            return
        
        if (event.pos() - self.drag_start_position).manhattanLength() < 10:
            return
        
        # Iniciar drag
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(str(self.index))
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.MoveAction)

    def eventFilter(self, watched, event):
        """Captura drops sobre widgets hijos del segmento."""
        event_type = event.type()
        if event_type == QEvent.Type.ContextMenu:
            self.show_context_menu(self.mapFromGlobal(event.globalPos()))
            event.accept()
            return True
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self._handle_internal_manual_image_drag(event):
                return True
            if self._handle_external_video_drag(event):
                return True
            return self._handle_external_image_drag(event)
        if event_type == QEvent.Type.Drop:
            if self._handle_internal_manual_image_drop(event):
                return True
            if self._handle_external_video_drop(event):
                return True
            return self._handle_external_image_drop(event)
        if event_type == QEvent.Type.DragLeave:
            self._set_drop_target_active(False)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        """Acepta el arrastre de archivos de imagen o video sobre la tarjeta."""
        if self._handle_internal_manual_image_drag(event):
            return
        if self._handle_external_video_drag(event):
            return
        if self._handle_external_image_drag(event):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """Mantiene activo el estado visual mientras el archivo se mueve sobre el segmento."""
        if self._handle_internal_manual_image_drag(event):
            return
        if self._handle_external_video_drag(event):
            return
        if self._handle_external_image_drag(event):
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        """Limpia el resaltado cuando el puntero sale del segmento."""
        self._set_drop_target_active(False)
        event.accept()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        """Asigna la imagen o video soltado al segmento."""
        if self._handle_internal_manual_image_drop(event):
            return
        if self._handle_external_video_drop(event):
            return
        if self._handle_external_image_drop(event):
            return
        super().dropEvent(event)

    def on_image_mouse_press(self, event):
        """Maneja la seleccion y prepara un posible drag sobre la miniatura."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
            self._image_drag_start_position = event.pos()
            self._image_drag_started = False
            event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            event.ignore()
            return

        event.ignore()

    def on_image_mouse_move(self, event):
        """Inicia el drag interno de la imagen manual al superar el umbral minimo."""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return

        if self._image_drag_start_position is None:
            return

        if (event.pos() - self._image_drag_start_position).manhattanLength() < 10:
            return

        if not self._has_movable_manual_image():
            return

        self._image_drag_started = True
        self._image_drag_start_position = None
        self._start_manual_image_drag()
        event.accept()

    def on_image_mouse_release(self, event):
        """Abre la preview solo cuando el gesto fue un click y no un drag."""
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._image_drag_started:
                self.on_image_clicked(event)
            self._image_drag_start_position = None
            self._image_drag_started = False
            event.accept()
            return

        event.ignore()
    
    def on_image_clicked(self, event):
        """Maneja el click en la imagen para mostrar vista previa"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Solo usar image_path explÃ­cito (asignado en generaciÃ³n de imÃ¡genes)
            # NO buscar automÃ¡ticamente por assigned_filename
            image_path, video_path = self._get_resolved_segment_media_paths()
            
            # Solo mostrar vista previa si hay image_path explÃ­cito
            if image_path and not video_path and not self.segment_data.get('image_deleted', False):
                self.show_image_preview(image_path)
            elif self.segment_data.get('image_deleted', False):
                # Si la imagen fue eliminada, no hacer nada
                pass
            else:
                # No hay imagen disponible
                QMessageBox.information(
                    self,
                    "Sin Imagen",
                    "No hay imagen generada para este segmento.\n\n"
                    "Usa el boton 'Generar imagenes' para crear una imagen."
                )
    
    def show_image_preview(self, image_path):
        """Muestra una ventana con la imagen en tamaÃ±o grande"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Vista Previa - {os.path.basename(image_path)}")
        dialog.setMinimumSize(800, 600)
        dialog.resize(1000, 700)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Label para la imagen
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet("""
            QLabel {
                background-color: #f7f8fa;
                border: 1px solid #dde3e9;
                border-radius: 6px;
            }
        """)
        
        # Cargar la imagen
        original_pixmap = None
        try:
            original_pixmap = self._load_pixmap_with_fallback(image_path)
            if not original_pixmap.isNull():
                # Inicializar con un tamaÃ±o razonable
                initial_pixmap = original_pixmap.scaled(
                    900, 600,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                image_label.setPixmap(initial_pixmap)
            else:
                image_label.setText("Error cargando imagen")
        except Exception as e:
            image_label.setText(f"Error: {str(e)}")
        
        layout.addWidget(image_label)
        
        # BotÃ³n cerrar
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(dialog.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # FunciÃ³n para ajustar el tamaÃ±o de la imagen
        def adjust_image_size():
            if original_pixmap and not original_pixmap.isNull():
                dialog_size = dialog.size()
                # Calcular tamaÃ±o disponible (descontando mÃ¡rgenes y botÃ³n)
                available_width = dialog_size.width() - 40
                available_height = dialog_size.height() - 100
                
                # Escalar manteniendo aspect ratio
                scaled_pixmap = original_pixmap.scaled(
                    available_width,
                    available_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                image_label.setPixmap(scaled_pixmap)
        
        # Conectar el evento de resize
        def resize_event_wrapper(event):
            adjust_image_size()
            QDialog.resizeEvent(dialog, event)
        
        dialog.resizeEvent = resize_event_wrapper
        
        # Ajustar cuando se muestra
        def show_event_wrapper(event):
            adjust_image_size()
            QDialog.showEvent(dialog, event)
        
        dialog.showEvent = show_event_wrapper
        
        dialog.exec()
    
    # ------------------------------------------------------------------
    # FAL.AI per-slot buttons
    # ------------------------------------------------------------------

    def set_fal_mode(self, enabled: bool):
        """Activa/desactiva la visibilidad del boton 'Generar' de FAL.AI."""
        self._fal_mode = bool(enabled)
        self._update_fal_buttons()

    def set_fal_image_busy(self, busy: bool):
        if hasattr(self, 'btn_fal_image'):
            self.btn_fal_image.setEnabled(not busy)
            self.btn_fal_image.setText("Generando..." if busy else "Generar")

    def set_fal_animate_busy(self, busy: bool):
        if hasattr(self, 'btn_fal_animate'):
            self.btn_fal_animate.setEnabled(not busy)
            self.btn_fal_animate.setText("Animando..." if busy else "Animar")

    def _is_fal_generated_image(self) -> bool:
        source = str(self.segment_data.get('image_source') or '').lower()
        if source in {'fal_ai', 'fal', 'fal.ai'}:
            return True
        img_path = str(self.segment_data.get('image_path') or '').replace('\\', '/')
        if 'fal' in img_path.lower() and source not in {
            'wikimedia', 'bing_images', 'google_images', 'openverse', 'local', 'pexels'
        }:
            return True
        return False

    def _update_fal_buttons(self):
        if not hasattr(self, 'btn_fal_image') or self.compact_image_mode:
            return
        has_image = bool(
            self.segment_data.get('image_path')
            and not self.segment_data.get('image_deleted')
        )
        has_video = bool(self.segment_data.get('video_path'))
        # Show generate button only when FAL mode is active AND no image yet
        self.btn_fal_image.setVisible(self._fal_mode and not has_image)
        # Show animate button only when there is a FAL-generated image AND no video yet
        self.btn_fal_animate.setVisible(has_image and self._is_fal_generated_image() and not has_video)

    def show_context_menu(self, position):
        """Muestra menÃº contextual con todas las opciones organizadas"""
        menu = QMenu(self)
        
        # OpciÃ³n de editar
        edit_action = menu.addAction("Editar")
        edit_action.triggered.connect(lambda: self.clicked.emit(self.index))
        regenerate_text_action = menu.addAction("Regenerar texto del segmento")
        regenerate_text_action.setToolTip("Reescribe este segmento con contexto del guion completo")
        regenerate_text_action.triggered.connect(self._on_regenerate_text_clicked)
        copy_recraft_prompts_action = menu.addAction("Copiar prompts Recraft")
        copy_recraft_prompts_action.setToolTip("Copia el prompt y negative prompt Recraft del segmento")
        copy_recraft_prompts_action.triggered.connect(self._on_copy_recraft_prompts_clicked)

        menu.addSeparator()
        
        # Agregar opciÃ³n de vista previa si hay imagen (solo si fue generada explÃ­citamente)
        image_path, video_path = self._get_resolved_segment_media_paths()
        if image_path and not video_path and not self.segment_data.get('image_deleted', False):
            preview_action = menu.addAction("Ver imagen completa")
            preview_action.triggered.connect(lambda: self.show_image_preview(image_path))

            copy_image_action = menu.addAction("Copiar imagen al portapapeles")
            copy_image_action.setToolTip("Copia la imagen de este segmento para pegarla en otro")
            copy_image_action.triggered.connect(self._on_copy_current_image_requested)
            menu.addSeparator()
        
        # Detectar qué tipo de contenido tiene el segmento.
        # Para mostrar/ocultar opciones de borrado se usa segment_data directamente
        # (no la resolución de archivo) — el archivo puede no encontrarse en disco aunque
        # el segmento sí tenga contenido asignado (ruta relativa, archivo movido, etc.)
        raw_image_path = str(self.segment_data.get('image_path') or '').strip()
        raw_video_path = str(self.segment_data.get('video_path') or '').strip()

        # Rutas resueltas (archivo verificado en disco) — para operaciones que necesitan el archivo
        image_path, video_path = self._get_resolved_segment_media_paths()
        if not video_path and image_path and self._is_video_path(image_path):
            video_path = image_path

        # has_image / has_video: archivo encontrado en disco (para preview/copy)
        has_image = bool(image_path and not self._is_video_path(image_path))
        has_video = bool(video_path)

        # has_image_data / has_video_data: segmento tiene ruta asignada (para borrar)
        raw_img_is_video = self._is_video_path(raw_image_path)
        has_image_data = bool(raw_image_path and not raw_img_is_video) or has_image
        has_video_data = bool(raw_video_path) or has_video or bool(raw_image_path and raw_img_is_video)

        has_content = has_image_data or has_video_data or self.segment_data.get('image_deleted', False)

        # Opciones de gestión del contenido actual
        if has_content:
            menu.addSeparator()

            # Opciones para imágenes
            if self.segment_data.get('image_deleted', False):
                restore_image_action = menu.addAction("Restaurar imagen")
                restore_image_action.triggered.connect(lambda: self.image_restored.emit(self.index))
            elif has_image_data:
                # Opción para marcar como eliminada (muestra negra)
                delete_image_action = menu.addAction("Marcar imagen como eliminada")
                delete_image_action.setToolTip("Marca la imagen como eliminada (se mostrará negra en el video)")
                delete_image_action.triggered.connect(lambda: self.image_deleted.emit(self.index))

                # Opción para eliminar completamente (permite agregar otra)
                remove_image_action = menu.addAction("Eliminar imagen")
                remove_image_action.setToolTip("Elimina completamente la imagen para poder agregar otra imagen o video después")
                remove_image_action.triggered.connect(lambda: self.image_removed.emit(self.index))

            # Opciones para videos
            if has_video_data:
                edit_video_action = menu.addAction("Editar video")
                edit_video_action.triggered.connect(lambda: self.video_edit_requested.emit(self.index))

                delete_video_action = menu.addAction("Eliminar video")
                delete_video_action.setToolTip("Elimina completamente el video para poder agregar otro video o una imagen después")
                delete_video_action.triggered.connect(lambda: self.video_deleted.emit(self.index))
        
        menu.addSeparator()
        
        # SecciÃ³n de agregar contenido (siempre visible, mÃ¡s prominente cuando no hay contenido)
        if not has_content:
            add_content_label = menu.addAction("Agregar contenido al segmento")
            add_content_label.setEnabled(False)  # Solo como tÃ­tulo
            menu.addSeparator()
        
        # SubmenÃº de bÃºsqueda de imÃ¡genes (siempre disponible)
        images_menu = menu.addMenu("Agregar imagen")
        if not has_content:
            images_menu.setToolTip("Busca y agrega una imagen al segmento")
        
        local_img_action = images_menu.addAction("Insertar imagen local")
        local_img_action.triggered.connect(lambda: self.local_image_requested.emit(self.index))

        paste_img_action = images_menu.addAction("Pegar imagen del portapapeles")
        paste_img_action.setToolTip("Pega una imagen copiada desde el portapapeles en este segmento")
        paste_img_action.setEnabled(self._clipboard_contains_pasteable_image())
        paste_img_action.triggered.connect(lambda: self.clipboard_image_requested.emit(self.index))
        
        images_menu.addSeparator()

        wikimedia_img_action = images_menu.addAction("Wikimedia Commons")
        wikimedia_img_action.triggered.connect(lambda: self.wikimedia_search_requested.emit(self.index))
        
        bing_img_action = images_menu.addAction("Openverse")
        bing_img_action.triggered.connect(lambda: self.openverse_images_search_requested.emit(self.index))
        
        # SubmenÃº de bÃºsqueda de videos (siempre disponible)
        videos_menu = menu.addMenu("Agregar video")
        if not has_content:
            videos_menu.setToolTip("Busca y agrega un video al segmento")
            
        local_video_action = videos_menu.addAction("Insertar video local")
        local_video_action.triggered.connect(lambda: self.local_video_requested.emit(self.index))
        
        videos_menu.addSeparator()
        
        pexels_video_action = videos_menu.addAction("Pexels")
        pexels_video_action.triggered.connect(lambda: self.pexels_video_search_requested.emit(self.index))
        
        wikimedia_video_action = videos_menu.addAction("Wikimedia Commons")
        wikimedia_video_action.triggered.connect(lambda: self.wikimedia_video_search_requested.emit(self.index))
        
        internet_archive_action = videos_menu.addAction("Internet Archive")
        internet_archive_action.triggered.connect(lambda: self.internet_archive_video_search_requested.emit(self.index))
        
        youtube_action = videos_menu.addAction("YouTube")
        youtube_action.triggered.connect(lambda: self.youtube_video_search_requested.emit(self.index))
        
        menu.addSeparator()
        
        # Regenerar imagen (solo si no hay video; en modo FAL el boton directo es preferible)
        if not has_video:
            regenerate_ai_action = menu.addAction("Regenerar imagen")
            regenerate_ai_action.setToolTip("Genera una nueva imagen para este segmento")
            regenerate_ai_action.triggered.connect(lambda: self.regenerate_ai_image_requested.emit(self.index))
        
        menu.addSeparator()
        
        # Eliminar segmento
        delete_action = menu.addAction("Eliminar segmento")
        delete_action.triggered.connect(lambda: self.deleted.emit(self.index))

        menu.exec(self.mapToGlobal(position))


class GroupedSegmentsWidget(QFrame):
    """
    Agrupa N segmentos consecutivos que comparten la misma imagen.

    Renderiza una imagen grande a la izquierda (rowspan visual) y los N
    paneles de texto apilados verticalmente a la derecha. Ejemplo visual
    solicitado por el usuario:

        +-----------------+-------------------+
        |                 |  SEGMENTO 1       |
        |                 +-------------------+
        |   IMAGEN 1      |  SEGMENTO 2       |
        |  (compartida)   +-------------------+
        |                 |  SEGMENTO 3       |
        +-----------------+-------------------+

    Los segmentos internos deben haberse construido con
    ``TimelineSegment(..., compact_image_mode=True)`` para que oculten su
    thumbnail individual.
    """

    # Solicitudes emitidas con la lista de indices del grupo.
    grouped_image_change_requested = pyqtSignal(list)     # pedir nueva imagen compartida
    grouped_image_remove_requested = pyqtSignal(list)     # quitar imagen del grupo completo
    grouped_image_ungroup_requested = pyqtSignal(list)    # desagrupar (mantener imagen solo en el primero)
    grouped_image_dropped = pyqtSignal(list, str)         # indices + ruta al soltar imagen
    grouped_video_dropped = pyqtSignal(list, str)         # indices + ruta al soltar video
    grouped_copy_prompts_requested = pyqtSignal(int)      # copiar prompt del primer segmento del grupo
    grouped_paste_clipboard_requested = pyqtSignal(list)  # pegar imagen del portapapeles al grupo
    grouped_strip_watermark_requested = pyqtSignal(list)  # eliminar marca de agua Gemini del grupo
    grouped_generate_fal_image_requested = pyqtSignal(list)  # generar imagen con FAL.AI para el grupo
    grouped_animate_fal_video_requested = pyqtSignal(list)   # animar imagen del grupo a video con FAL.AI

    def __init__(self, member_widgets, shared_image_path=None, shared_image_source=None,
                 parent=None):
        super().__init__(parent)
        self.member_widgets = list(member_widgets or [])
        self.shared_image_path = shared_image_path
        self.shared_image_source = (shared_image_source or "").lower()
        self._fal_mode = False

        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setAcceptDrops(True)
        self._setup_ui()
        self._apply_style()
        self.refresh_shared_image()

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    @property
    def member_indices(self):
        """Lista de indices originales de los segmentos agrupados."""
        return [getattr(w, 'index', -1) for w in self.member_widgets]

    def set_fal_mode(self, enabled: bool):
        """Activa/desactiva los botones FAL.AI de este grupo."""
        self._fal_mode = bool(enabled)
        self._update_fal_buttons()

    def set_fal_generate_busy(self, busy: bool):
        if hasattr(self, 'btn_fal_image'):
            self.btn_fal_image.setEnabled(not busy)
            self.btn_fal_image.setText("Generando..." if busy else "Generar imagen")

    def set_fal_animate_busy(self, busy: bool):
        if hasattr(self, 'btn_fal_animate'):
            self.btn_fal_animate.setEnabled(not busy)
            self.btn_fal_animate.setText("Animando..." if busy else "Animar a video")

    def _update_fal_buttons(self):
        if not hasattr(self, 'btn_fal_image'):
            return
        has_image = bool(self.shared_image_path)
        source = self.shared_image_source.lower()
        img_path = str(self.shared_image_path or '').replace('\\', '/').lower()
        is_fal = (
            source in {'fal_ai', 'fal', 'fal.ai'}
            or ('fal' in img_path and source not in {
                'wikimedia', 'bing_images', 'google_images', 'openverse', 'local', 'pexels'
            })
        )
        has_video = any(bool(w.segment_data.get('video_path')) for w in self.member_widgets)
        self.btn_fal_image.setVisible(self._fal_mode and not has_image)
        self.btn_fal_animate.setVisible(has_image and is_fal and not has_video)

    def refresh_shared_image(self, new_path=None):
        """Recarga la imagen compartida mostrada a la izquierda."""
        if new_path is not None:
            self.shared_image_path = new_path

        pixmap = self._load_shared_pixmap(self.shared_image_path)
        if pixmap is not None and not pixmap.isNull():
            self.shared_image_label.setPixmap(pixmap)
            self.shared_image_label.setText("")
        else:
            self.shared_image_label.clear()
            self.shared_image_label.setText("Sin imagen\ncompartida")

        self.badge_label.setText(
            f"Imagen compartida · {len(self.member_widgets)} segmentos"
        )
        self._update_fal_buttons()

    # ------------------------------------------------------------------
    # Construccion visual
    # ------------------------------------------------------------------
    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(8)

        # --- Columna izquierda: imagen compartida + badge ---
        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(4)

        self.shared_image_label = QLabel()
        # Altura proporcional a la cantidad de segmentos agrupados:
        # cada segmento compacto ocupa ~100-120 px, respetamos ese tamano.
        n = max(1, len(self.member_widgets))
        big_height = max(220, 110 * n)
        big_width = 240
        self.shared_image_label.setMinimumSize(big_width, big_height)
        self.shared_image_label.setMaximumWidth(big_width + 20)
        self.shared_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shared_image_label.setScaledContents(True)
        self.shared_image_label.setStyleSheet("""
            QLabel {
                background-color: #fbfcfd;
                border: 1px solid #dde3e9;
                border-radius: 6px;
                color: #6f7c89;
                font-size: 9pt;
            }
        """)
        self.shared_image_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.shared_image_label.setToolTip(
            "Imagen compartida por varios segmentos.\n"
            "Click derecho para cambiarla, quitarla o desagrupar."
        )
        self.shared_image_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.shared_image_label.customContextMenuRequested.connect(self._show_shared_image_menu)
        self.shared_image_label.mousePressEvent = self._on_shared_image_press
        self.shared_image_label.mouseDoubleClickEvent = self._on_shared_image_double_click
        left_column.addWidget(self.shared_image_label)

        self.badge_label = QLabel()
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.setWordWrap(True)
        self.badge_label.setStyleSheet("""
            QLabel {
                background-color: #eef4fb;
                color: #1f3b5c;
                border: 1px solid #c7d7e8;
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 8pt;
                font-weight: bold;
            }
        """)
        left_column.addWidget(self.badge_label)

        self.btn_copy_prompts = QPushButton("Copiar Prompts")
        self.btn_copy_prompts.setToolTip(
            "Copia el prompt y negative prompt de la imagen compartida al portapapeles."
        )
        self.btn_copy_prompts.setMinimumHeight(24)
        self.btn_copy_prompts.setStyleSheet("""
            QPushButton {
                padding: 2px 8px;
                font-size: 8pt;
            }
        """)
        self.btn_copy_prompts.clicked.connect(self._on_copy_prompts_clicked)
        left_column.addWidget(self.btn_copy_prompts)

        _fal_grp_style = """
            QPushButton {
                padding: 2px 8px;
                font-size: 8pt;
                background-color: #1a1a2e;
                color: #e0e0ff;
                border: 1px solid #4a4aaa;
                border-radius: 3px;
            }
            QPushButton:hover { background-color: #2a2a4e; }
            QPushButton:disabled { background-color: #3a3a4e; color: #888; }
        """
        self.btn_fal_image = QPushButton("Generar imagen")
        self.btn_fal_image.setToolTip("Genera imagen compartida para este grupo con FAL.AI")
        self.btn_fal_image.setMinimumHeight(24)
        self.btn_fal_image.setStyleSheet(_fal_grp_style)
        self.btn_fal_image.clicked.connect(
            lambda: self.grouped_generate_fal_image_requested.emit(self.member_indices)
        )
        self.btn_fal_image.setVisible(False)
        left_column.addWidget(self.btn_fal_image)

        self.btn_fal_animate = QPushButton("Animar a video")
        self.btn_fal_animate.setToolTip("Anima la imagen compartida a video con FAL.AI (I2V)")
        self.btn_fal_animate.setMinimumHeight(24)
        self.btn_fal_animate.setStyleSheet(_fal_grp_style)
        self.btn_fal_animate.clicked.connect(
            lambda: self.grouped_animate_fal_video_requested.emit(self.member_indices)
        )
        self.btn_fal_animate.setVisible(False)
        left_column.addWidget(self.btn_fal_animate)

        left_widget = QWidget()
        left_widget.setLayout(left_column)
        # Redirigir drag events del panel izquierdo al GroupedSegmentsWidget padre.
        # En Qt los drag events NO se propagan automáticamente a los padres cuando
        # el hijo no los acepta, por lo que necesitamos un event filter explícito.
        left_widget.setAcceptDrops(True)
        left_widget.installEventFilter(self)
        self.shared_image_label.setAcceptDrops(True)
        self.shared_image_label.installEventFilter(self)
        outer.addWidget(left_widget, 0)

        # --- Columna derecha: segmentos apilados ---
        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(4)
        for seg_widget in self.member_widgets:
            right_column.addWidget(seg_widget)
        right_column.addStretch(1)

        right_widget = QWidget()
        right_widget.setLayout(right_column)
        outer.addWidget(right_widget, 1)

    def _apply_style(self):
        self.setStyleSheet("""
            GroupedSegmentsWidget {
                background-color: #f7faff;
                border: 1px solid #c7d7e8;
                border-radius: 10px;
            }
        """)

    # ------------------------------------------------------------------
    # Imagen compartida: carga + menu contextual
    # ------------------------------------------------------------------
    def _load_shared_pixmap(self, path_value):
        """Carga un QPixmap escalado para la imagen compartida."""
        if not path_value:
            return None

        abs_path = self._resolve_path(path_value)
        if not abs_path:
            return None

        cached = _get_cached_pixmap(abs_path)
        if cached is not None:
            return cached

        pixmap = QPixmap(abs_path)
        if pixmap.isNull():
            # Fallback muy simple via Pillow
            try:
                from PIL import Image, ImageOps
                with Image.open(abs_path) as img:
                    img = ImageOps.exif_transpose(img)
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    fd, tmp_path = tempfile.mkstemp(suffix=".png")
                    os.close(fd)
                    try:
                        img.save(tmp_path, "PNG")
                        pixmap = QPixmap(tmp_path)
                    finally:
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
            except Exception:
                return None

        if pixmap.isNull():
            return None

        _set_cached_pixmap(abs_path, pixmap)
        return pixmap

    def _resolve_path(self, path_value):
        """Resuelve una ruta relativa apoyandose en el primer miembro."""
        if not path_value:
            return None
        raw = str(path_value)
        if os.path.isabs(raw) and os.path.exists(raw):
            return _local_abs(raw)
        # Delegar en el primer miembro, que conoce el proyecto
        for member in self.member_widgets:
            resolver = getattr(member, '_resolve_existing_media_path', None)
            if callable(resolver):
                resolved = resolver(raw)
                if resolved and os.path.exists(resolved):
                    return _local_abs(resolved)
        try:
            if os.path.exists(raw):
                return _local_abs(raw)
        except OSError:
            pass
        return None

    def _on_copy_prompts_clicked(self):
        """Emite señal para copiar prompt+negative prompt del primer segmento del grupo."""
        indices = self.member_indices
        if indices:
            self.grouped_copy_prompts_requested.emit(indices[0])

    def _show_shared_image_menu(self, position):
        menu = QMenu(self.shared_image_label)
        change_action = menu.addAction("Cambiar imagen compartida...")
        change_action.triggered.connect(
            lambda: self.grouped_image_change_requested.emit(self.member_indices)
        )
        paste_action = menu.addAction("Pegar imagen del portapapeles")
        paste_action.triggered.connect(
            lambda: self.grouped_paste_clipboard_requested.emit(self.member_indices)
        )
        strip_action = menu.addAction("Quitar marca de agua (Gemini)")
        strip_action.setToolTip("Elimina la marca de agua de Google Gemini de la imagen compartida.")
        strip_action.setEnabled(bool(self.shared_image_path))
        strip_action.triggered.connect(
            lambda: self.grouped_strip_watermark_requested.emit(self.member_indices)
        )
        remove_action = menu.addAction("Quitar imagen compartida")
        remove_action.triggered.connect(
            lambda: self.grouped_image_remove_requested.emit(self.member_indices)
        )
        menu.addSeparator()
        ungroup_action = menu.addAction("Desagrupar segmentos")
        ungroup_action.setToolTip(
            "Mantiene la imagen solo en el primer segmento y deja los otros sin imagen."
        )
        ungroup_action.triggered.connect(
            lambda: self.grouped_image_ungroup_requested.emit(self.member_indices)
        )
        menu.exec(self.shared_image_label.mapToGlobal(position))

    def _on_shared_image_press(self, event):
        """Click izquierdo: abre preview completo. Clic derecho: menú contextual."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.member_widgets:
                try:
                    # Usar la resolución de rutas del propio miembro (maneja paths relativos)
                    image_path, video_path = self.member_widgets[0]._get_resolved_segment_media_paths()
                    if image_path and not video_path:
                        self.member_widgets[0].show_image_preview(image_path)
                except Exception:
                    pass
            event.accept()
        else:
            event.ignore()

    def _on_shared_image_double_click(self, event):
        """Doble click sobre la imagen abre el selector para cambiarla."""
        try:
            self.grouped_image_change_requested.emit(self.member_indices)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Drag & drop de una nueva imagen compartida
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        """Redirige drag events de los widgets hijos (panel izquierdo) al GroupedSegmentsWidget."""
        from PyQt6.QtCore import QEvent
        t = event.type()
        if t == QEvent.Type.DragEnter:
            self.dragEnterEvent(event)
            return True
        if t == QEvent.Type.DragMove:
            self.dragMoveEvent(event)
            return True
        if t == QEvent.Type.Drop:
            self.dropEvent(event)
            return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime and mime.hasUrls():
            for url in mime.urls():
                if not url.isLocalFile():
                    continue
                ext = Path(url.toLocalFile()).suffix.lower()
                if ext in SUPPORTED_IMAGE_EXTENSIONS or ext in SUPPORTED_VIDEO_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime or not mime.hasUrls():
            event.ignore()
            return
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            ext = Path(local_path).suffix.lower()
            if ext in SUPPORTED_IMAGE_EXTENSIONS:
                event.acceptProposedAction()
                self.grouped_image_dropped.emit(self.member_indices, local_path)
                return
            if ext in SUPPORTED_VIDEO_EXTENSIONS:
                event.acceptProposedAction()
                self.grouped_video_dropped.emit(self.member_indices, local_path)
                return
        event.ignore()
