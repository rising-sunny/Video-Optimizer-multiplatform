# timeline_editor_widget.py
"""
Timeline Editor profesional para Video Optimizer Pro.
Permite editar segmentos despuÃ©s de generar el storyboard.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QScrollArea, QFrame, QSplitter, QLineEdit,
    QSpinBox, QDoubleSpinBox, QGroupBox, QMessageBox, QMenu,
    QDialog, QGridLayout, QListWidget, QListWidgetItem, QProgressBar, QCheckBox,
    QDialogButtonBox, QAbstractItemView
)
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QPoint, QUrl, QSize
from PyQt6.QtGui import QDrag, QPainter, QColor, QPen, QFont, QPixmap, QCursor, QIcon
from PyQt6.QtWidgets import QApplication

# Intentar importar QMediaPlayer para preview de videos
# Hacer la importaciÃ³n de forma mÃ¡s segura para evitar crashes
MEDIA_PLAYER_AVAILABLE = False
QMediaPlayer = None
QVideoWidget = None
QAudioOutput = None

try:
    import sys
    # Intentar importar solo si estamos en un entorno que lo soporta
    if hasattr(sys, 'platform'):
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PyQt6.QtMultimediaWidgets import QVideoWidget
            # Verificar que las clases se importaron correctamente
            if QMediaPlayer and QVideoWidget and QAudioOutput:
                MEDIA_PLAYER_AVAILABLE = True
        except (ImportError, AttributeError, RuntimeError, OSError):
            # Silenciar el error para evitar crashes
            pass
except Exception:
    # Silenciar cualquier otro error
    pass
import json
import os
import requests
import warnings
import logging
import hashlib
import difflib
import re
import tempfile
from datetime import datetime, timezone
from collections import deque
from pathlib import Path

# Suprimir warnings de Qt sobre perfiles ICC
warnings.filterwarnings('ignore', category=RuntimeWarning, message='.*fromIccProfile.*')
# TambiÃ©n suprimir en el logger de Qt
logging.getLogger('qt.gui.icc').setLevel(logging.ERROR)

try:
    from media.wikimedia_client import WikimediaClient
    WIKIMEDIA_AVAILABLE = True
except ImportError:
    WIKIMEDIA_AVAILABLE = False
    WikimediaClient = None

try:
    from media.bing_images_client import BingImagesClient
    BING_IMAGES_AVAILABLE = True
except ImportError:
    BING_IMAGES_AVAILABLE = False
    BingImagesClient = None

try:
    from pipeline.auto_video_generator_v2 import ResourceDownloader
    # Alias para compatibilidad
    StockMediaDownloader = ResourceDownloader
    PEXELS_AVAILABLE = True
except ImportError:
    PEXELS_AVAILABLE = False
    StockMediaDownloader = None
    ResourceDownloader = None

try:
    from media.wikimedia_client import WikimediaClient
    WIKIMEDIA_VIDEO_AVAILABLE = True
except ImportError:
    WIKIMEDIA_VIDEO_AVAILABLE = False
    WikimediaClient = None

try:
    from media.internet_archive_client import InternetArchiveClient
    INTERNET_ARCHIVE_AVAILABLE = True
except ImportError:
    INTERNET_ARCHIVE_AVAILABLE = False
    InternetArchiveClient = None

try:
    from media.youtube_video_client import YouTubeVideoClient, YT_DLP_AVAILABLE
    YOUTUBE_VIDEO_AVAILABLE = True
except ImportError:
    YOUTUBE_VIDEO_AVAILABLE = False
    YouTubeVideoClient = None
    YT_DLP_AVAILABLE = False

try:
    from infra.video_config import VideoConfig
    VIDEO_CONFIG_AVAILABLE = True
except ImportError:
    VIDEO_CONFIG_AVAILABLE = False
    VideoConfig = None

# Importar Workers desde mÃ³dulo separado
from studio.timeline_workers import (
    VideoFrameExtractorWorker,
    AIImageRegenerationWorker,
    ContextualAIImageRegenerationWorker,
    WikimediaSearchWorker,
    BingImagesSearchWorker,
    GoogleImagesSearchWorker,
    PexelsVideoSearchWorker,
    WikimediaVideoSearchWorker,
    InternetArchiveVideoSearchWorker,
    YouTubeVideoSearchWorker
)

# Importar DiÃ¡logos desde mÃ³dulos separados
from media.wikimedia_search_dialog import WikimediaSearchDialog
from media.bing_images_search_dialog import BingImagesSearchDialog
from media.pexels_video_search_dialog import PexelsVideoSearchDialog
from app.video_preview_dialog import VideoPreviewDialog
from media.wikimedia_video_search_dialog import WikimediaVideoSearchDialog
from media.internet_archive_search_dialog import InternetArchiveVideoSearchDialog
from media.youtube_video_search_dialog import YouTubeVideoSearchDialog
from media.local_video_picker_dialog import LocalVideoPickerDialog

# Compatibilidad para imports legacy que aún usan el nombre GoogleImagesSearchDialog
GoogleImagesSearchDialog = BingImagesSearchDialog

# Importar widgets del timeline desde mÃ³dulos separados
from studio.timeline_video_widget import VideoTimelineWidget
from studio.timeline_segment_widget import TimelineSegment, GroupedSegmentsWidget
from studio.timeline_segment_editor import SegmentEditor
try:
    from ai.text_correction_engine import TextCorrectionEngine
    TEXT_CORRECTION_AVAILABLE = True
except ImportError:
    TextCorrectionEngine = None
    TEXT_CORRECTION_AVAILABLE = False


SUPPORTED_CLIPBOARD_IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".avif", ".gif", ".tif", ".tiff"
}

TIMELINE_AI_IMAGE_SOURCES = {
    "fal_ai",
    "fal",
    "leonardo",
    "leonardo_ai",
    "recraft_ai",
    "recraft_compat_leonardo",
    "google_ai",
    "vertex_imagen",
    "existing",
    "runway",
    "eden",
}

TIMELINE_MANUAL_IMAGE_SOURCES = {
    "local",
    "wikimedia",
    "bing_images",
    "google_images",
    "openverse",
}

TIMELINE_AI_PATH_HINTS = (
    "generated_media",
    "leonardo",
    "runway",
    "fal",
    "eden",
    "thumb_",
)


class SubtitlePreview(QLabel):
    """Widget para previsualizar subtÃ­tulos"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 200);
                color: #ffffff;
                font-size: 16pt;
                font-weight: bold;
                padding: 15px;
                border-radius: 8px;
                border: 2px solid #3d3d3d;
                min-height: 60px;
            }
        """)
        self.setText("Vista previa de subtÃ­tulos")


class SharedImageRangeDialog(QDialog):
    """Elige cuántos segmentos consecutivos cubre una still, viendo el texto."""

    def __init__(self, parent, segments, start_index, default_count=1):
        super().__init__(parent)
        self.setWindowTitle("Imagen compartida")
        self.setMinimumSize(560, 420)
        self._start_index = int(start_index)
        self._candidates = []
        remaining = list(segments[start_index:])
        for offset, seg in enumerate(remaining):
            if not isinstance(seg, dict):
                seg = {}
            abs_idx = start_index + offset
            text = (seg.get("text") or seg.get("narration_text") or "").strip()
            start_t = seg.get("start", seg.get("start_time"))
            end_t = seg.get("end", seg.get("end_time"))
            timing = ""
            try:
                if start_t is not None and end_t is not None:
                    timing = f"{float(start_t):.1f}s–{float(end_t):.1f}s"
            except (TypeError, ValueError):
                timing = ""
            preview = " ".join(text.split())
            if len(preview) > 110:
                preview = preview[:107] + "..."
            self._candidates.append({
                "index": abs_idx,
                "timing": timing,
                "preview": preview or "(sin texto)",
            })

        max_count = max(1, len(self._candidates))
        self._count = max(1, min(int(default_count or 1), max_count))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Esta still empieza en el segmento #{start_index + 1}.\n"
            "Marca hasta dónde llega (los resaltados la compartirán)."
        ))

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for i, item in enumerate(self._candidates):
            timing = f"  ·  {item['timing']}" if item["timing"] else ""
            row = QListWidgetItem(f"#{item['index'] + 1}{timing}\n    {item['preview']}")
            row.setData(Qt.ItemDataRole.UserRole, i + 1)
            self.list_widget.addItem(row)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget, 1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Cubrir"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, max_count)
        self.count_spin.setValue(self._count)
        self.count_spin.valueChanged.connect(self._on_spin_changed)
        controls.addWidget(self.count_spin)
        controls.addWidget(QLabel("segmentos, hasta el #"))
        self.until_label = QLabel("")
        controls.addWidget(self.until_label)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Aplicar")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        only_one = buttons.addButton("Solo este", QDialogButtonBox.ButtonRole.ActionRole)
        only_one.clicked.connect(self._choose_only_one)
        layout.addWidget(buttons)

        self._refresh_highlight()

    def _choose_only_one(self):
        self.count_spin.setValue(1)
        self.accept()

    def _on_item_clicked(self, item):
        count = item.data(Qt.ItemDataRole.UserRole)
        if count:
            self.count_spin.setValue(int(count))

    def _on_spin_changed(self, value):
        self._count = int(value)
        self._refresh_highlight()

    def _refresh_highlight(self):
        until_idx = self._start_index + self._count
        self.until_label.setText(str(until_idx))
        self.summary_label.setText(
            f"La imagen cubrirá los segmentos #{self._start_index + 1}–#{until_idx} "
            f"({self._count} en total)."
        )
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            covered = row < self._count
            item.setSelected(covered)
            if covered:
                item.setBackground(QColor("#2d4a6f"))
            else:
                item.setBackground(QColor("#1e1e1e"))

    def selected_count(self) -> int:
        return int(self._count)


from studio.timeline_image_generation_mixin import TimelineImageGenerationMixin


class TimelineSearchDialogsMixin:
    def open_wikimedia_search(self, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de Wikimedia para un segmento"""
        if not WIKIMEDIA_AVAILABLE:
            QMessageBox.warning(
                self,
                "Wikimedia no disponible",
                "El cliente de Wikimedia no estÃ¡ disponible.\n"
                "AsegÃºrate de que wikimedia_client.py estÃ© en el directorio del proyecto."
            )
            return
        
        if segment_index >= len(self.segments):
            return
        
        segment = self.segments[segment_index]
        self._open_wikimedia_dialog_for_segment(segment, segment_index)


    def on_segment_editor_wikimedia_search(self, segment_data):
        """Maneja la solicitud de bÃºsqueda de Wikimedia desde el editor de segmentos"""
        # Encontrar el Ã­ndice del segmento actual
        segment_index = None
        for i, seg in enumerate(self.segments):
            if seg == segment_data or (seg.get('assigned_filename') == segment_data.get('assigned_filename')):
                segment_index = i
                break
        
        if segment_index is None:
            QMessageBox.warning(
                self,
                "Segmento no encontrado",
                "No se pudo encontrar el segmento en el timeline."
            )
            return
        
        self._open_wikimedia_dialog_for_segment(segment_data, segment_index)


    def _open_wikimedia_dialog_for_segment(self, segment, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de Wikimedia para un segmento especÃ­fico"""
        if not WIKIMEDIA_AVAILABLE:
            QMessageBox.warning(
                self,
                "Wikimedia no disponible",
                "El cliente de Wikimedia no estÃ¡ disponible.\n"
                "AsegÃºrate de que wikimedia_client.py estÃ© en el directorio del proyecto."
            )
            return
        
        # Crear y mostrar el diÃ¡logo
        dialog = WikimediaSearchDialog(self, segment)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Obtener la imagen seleccionada
            selected_image_path = dialog.selected_image_path
            if selected_image_path:
                # Actualizar el segmento en la lista
                if segment_index < len(self.segments):
                    self.segments[segment_index]['image_path'] = selected_image_path
                    self.segments[segment_index]['image_source'] = 'wikimedia'  # Marcar como de Wikimedia
                    self.segments[segment_index].pop('video_path', None)
                    self.segments[segment_index].pop('video_source', None)
                    
                    # Eliminar flag de imagen eliminada si existe (para que se muestre el preview)
                    if 'image_deleted' in self.segments[segment_index]:
                        del self.segments[segment_index]['image_deleted']
                    
                    self._refresh_media_widgets(
                        [segment_index],
                        {segment_index: selected_image_path},
                    )
                    
                    # Actualizar el editor de segmentos si estÃ¡ mostrando este segmento
                    if self.selected_index == segment_index:
                        self.segment_editor.load_segment(self.segments[segment_index])
                
                QMessageBox.information(
                    self,
                    "Imagen Asignada",
                    f"Se asignÃ³ una imagen de Wikimedia al segmento #{segment_index + 1}."
                )
                # Activar auto-guardado automÃ¡tico
                self._trigger_auto_save("despuÃ©s de agregar imagen de Wikimedia")


    def open_openverse_search(self, segment_index):
        """Abre el dialogo de busqueda de Openverse para un segmento."""
        if not BING_IMAGES_AVAILABLE:
            QMessageBox.warning(
                self,
                "Openverse no disponible",
                "El cliente de Openverse no esta disponible.\n"
                "AsegÃºrate de que bing_images_client.py estÃ© en el directorio del proyecto.\n\n"
                "El backend por defecto es Openverse (sin API key)."
            )
            return
        
        if segment_index >= len(self.segments):
            return
        
        segment = self.segments[segment_index]
        self._open_openverse_dialog_for_segment(segment, segment_index)


    def on_segment_editor_openverse_search(self, segment_data):
        """Maneja la solicitud de busqueda de Openverse desde el editor de segmentos."""
        # Encontrar el Ã­ndice del segmento actual
        segment_index = None
        for i, seg in enumerate(self.segments):
            if seg == segment_data or (seg.get('assigned_filename') == segment_data.get('assigned_filename')):
                segment_index = i
                break
        
        if segment_index is None:
            QMessageBox.warning(
                self,
                "Segmento no encontrado",
                "No se pudo encontrar el segmento en el timeline."
            )
            return
        
        self._open_openverse_dialog_for_segment(segment_data, segment_index)


    def _open_openverse_dialog_for_segment(self, segment, segment_index):
        """Abre el dialogo de busqueda de Openverse para un segmento especifico."""
        try:
            if not BING_IMAGES_AVAILABLE:
                QMessageBox.warning(
                    self,
                    "Openverse no disponible",
                    "El cliente de Openverse no esta disponible.\n"
                    "AsegÃºrate de que bing_images_client.py estÃ© en el directorio del proyecto.\n\n"
                    "El backend por defecto es Openverse (sin API key)."
                )
                return
            
            # Validar que segment_index sea vÃ¡lido
            if segment_index < 0 or segment_index >= len(self.segments):
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Ãndice de segmento invÃ¡lido: {segment_index}"
                )
                return
            
            # Crear y mostrar el diÃ¡logo
            dialog = BingImagesSearchDialog(self, segment)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Obtener la imagen seleccionada
                selected_image_path = dialog.selected_image_path
                if selected_image_path and os.path.exists(selected_image_path):
                    # Validar nuevamente el Ã­ndice antes de actualizar
                    if 0 <= segment_index < len(self.segments):
                        # Actualizar el segmento en la lista
                        self.segments[segment_index]['image_path'] = selected_image_path
                        self.segments[segment_index]['image_source'] = 'bing_images'  # Marcar como de Openverse
                        self.segments[segment_index].pop('video_path', None)
                        self.segments[segment_index].pop('video_source', None)
                        
                        # Eliminar flag de imagen eliminada si existe (para que se muestre el preview)
                        if 'image_deleted' in self.segments[segment_index]:
                            del self.segments[segment_index]['image_deleted']
                        
                        # Actualizar el widget del segmento
                        if 0 <= segment_index < len(self.segment_widgets):
                            try:
                                self._refresh_media_widgets(
                                    [segment_index],
                                    {segment_index: selected_image_path},
                                )
                            except Exception as e:
                                print(f"âš ï¸ Error actualizando widget del segmento: {e}")
                        
                        # Actualizar el editor de segmentos si estÃ¡ mostrando este segmento
                        if hasattr(self, 'selected_index') and self.selected_index == segment_index:
                            try:
                                if hasattr(self, 'segment_editor') and self.segment_editor:
                                    self.segment_editor.load_segment(self.segments[segment_index])
                            except Exception as e:
                                print(f"âš ï¸ Error actualizando editor de segmentos: {e}")
                    
                        QMessageBox.information(
                            self,
                            "Imagen Asignada",
                            f"Se asignÃ³ una imagen de Openverse al segmento #{segment_index + 1}."
                        )
                        # Activar auto-guardado automÃ¡tico
                        self._trigger_auto_save("despuÃ©s de agregar imagen de Openverse")
                    else:
                        QMessageBox.warning(
                            self,
                            "Error",
                            f"Ãndice de segmento fuera de rango: {segment_index}"
                        )
                elif selected_image_path:
                    QMessageBox.warning(
                        self,
                        "Error",
                        f"La imagen seleccionada no existe: {selected_image_path}"
                    )
        except Exception as e:
            import traceback
            error_msg = f"Error al agregar imagen de Openverse:\n{str(e)}\n\n{traceback.format_exc()}"
            print(f"âŒ {error_msg}")
            QMessageBox.critical(
                self,
                "Error CrÃ­tico",
                f"OcurriÃ³ un error al agregar la imagen:\n\n{str(e)}\n\nRevisa la consola para mÃ¡s detalles."
            )


    def open_pexels_video_search(self, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de videos de Pexels para un segmento"""
        if not PEXELS_AVAILABLE:
            QMessageBox.warning(
                self,
                "Pexels no disponible",
                "El cliente de Pexels no estÃ¡ disponible.\n"
                "AsegÃºrate de que auto_video_generator_v2.py estÃ© en el directorio del proyecto.\n\n"
                "TambiÃ©n necesitas configurar PEXELS_API_KEY en tu archivo .env"
            )
            return
        
        if segment_index >= len(self.segments):
            return
        
        segment = self.segments[segment_index]
        self._open_pexels_video_dialog_for_segment(segment, segment_index)


    def on_segment_editor_pexels_video_search(self, segment_data):
        """Maneja la solicitud de bÃºsqueda de videos de Pexels desde el editor de segmentos"""
        # Encontrar el Ã­ndice del segmento actual
        segment_index = None
        for i, seg in enumerate(self.segments):
            if seg == segment_data or (seg.get('assigned_filename') == segment_data.get('assigned_filename')):
                segment_index = i
                break
        
        if segment_index is None:
            QMessageBox.warning(
                self,
                "Segmento no encontrado",
                "No se pudo encontrar el segmento en el timeline."
            )
            return
        
        self._open_pexels_video_dialog_for_segment(segment_data, segment_index)


    def open_wikimedia_video_search(self, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de videos histÃ³ricos en Wikimedia para un segmento"""
        if not WIKIMEDIA_VIDEO_AVAILABLE:
            QMessageBox.warning(
                self,
                "Wikimedia no disponible",
                "El cliente de Wikimedia no estÃ¡ disponible.\n"
                "AsegÃºrate de que wikimedia_client.py estÃ© en el directorio del proyecto."
            )
            return
        
        if segment_index >= len(self.segments):
            return
        
        segment = self.segments[segment_index]
        self._open_wikimedia_video_dialog_for_segment(segment, segment_index)


    def open_internet_archive_video_search(self, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de videos histÃ³ricos en Internet Archive para un segmento"""
        if not INTERNET_ARCHIVE_AVAILABLE:
            QMessageBox.warning(
                self,
                "Internet Archive no disponible",
                "El cliente de Internet Archive no estÃ¡ disponible.\n"
                "AsegÃºrate de que internet_archive_client.py estÃ© en el directorio del proyecto."
            )
            return
        
        if segment_index >= len(self.segments):
            return
        
        segment = self.segments[segment_index]
        self._open_internet_archive_video_dialog_for_segment(segment, segment_index)


    def open_youtube_video_search(self, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de videos en YouTube para un segmento"""
        if not YOUTUBE_VIDEO_AVAILABLE:
            QMessageBox.warning(
                self,
                "YouTube no disponible",
                "El cliente de YouTube no estÃ¡ disponible.\n"
                "AsegÃºrate de que youtube_video_client.py estÃ© en el directorio del proyecto.\n\n"
                "TambiÃ©n necesitas:\n"
                "- GOOGLE_API_KEY en tu archivo .env\n"
                "- yt-dlp instalado: pip install yt-dlp"
            )
            return
        
        if segment_index >= len(self.segments):
            return
        
        segment = self.segments[segment_index]
        self._open_youtube_video_dialog_for_segment(segment, segment_index)


    def _open_wikimedia_video_dialog_for_segment(self, segment, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de videos histÃ³ricos en Wikimedia para un segmento especÃ­fico"""
        if not WIKIMEDIA_VIDEO_AVAILABLE:
            QMessageBox.warning(
                self,
                "Wikimedia no disponible",
                "El cliente de Wikimedia no estÃ¡ disponible."
            )
            return
        
        try:
            dialog = WikimediaVideoSearchDialog(self, segment_data=segment)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                video_path = dialog.selected_video_path
                if video_path and os.path.exists(video_path):
                    # Convertir a ruta absoluta para evitar problemas de rutas relativas
                    video_path = os.path.abspath(video_path)
                    # Asignar video al segmento
                    self.segments[segment_index]['video_path'] = video_path
                    self.segments[segment_index]['image_path'] = video_path  # Usar image_path para compatibilidad
                    self.segments[segment_index]['video_source'] = 'wikimedia_video'
                    self.segments[segment_index]['image_source'] = 'wikimedia_video'
                    
                    # Eliminar flag de imagen eliminada si existe
                    if 'image_deleted' in self.segments[segment_index]:
                        del self.segments[segment_index]['image_deleted']
                    
                    self._refresh_media_widgets([segment_index], {segment_index: None})
                    
                    QMessageBox.information(
                        self,
                        "Video Asignado",
                        f"âœ… Video asignado correctamente al segmento #{segment_index + 1}.\n\n"
                        f"ðŸ“ UbicaciÃ³n: {video_path}"
                    )
                    # Activar auto-guardado automÃ¡tico
                    self._trigger_auto_save("despuÃ©s de agregar video de Wikimedia")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Error al abrir el diÃ¡logo de bÃºsqueda de videos:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()


    def _open_youtube_video_dialog_for_segment(self, segment, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de videos en YouTube para un segmento especÃ­fico"""
        if not YOUTUBE_VIDEO_AVAILABLE:
            QMessageBox.warning(
                self,
                "YouTube no disponible",
                "El cliente de YouTube no estÃ¡ disponible.\n"
                "AsegÃºrate de que youtube_video_client.py estÃ© en el directorio del proyecto.\n\n"
                "TambiÃ©n necesitas:\n"
                "- GOOGLE_API_KEY en tu archivo .env\n"
                "- yt-dlp instalado: pip install yt-dlp"
            )
            return
        
        try:
            dialog = YouTubeVideoSearchDialog(self, segment_data=segment)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                video_path = dialog.selected_video_path
                
                if video_path and os.path.exists(video_path):
                    # Convertir a ruta absoluta para evitar problemas de rutas relativas
                    video_path = os.path.abspath(video_path)
                    
                    # Debug: verificar que el video existe
                    print(f"[TimelineEditor] Asignando video de YouTube al segmento #{segment_index + 1}")
                    print(f"  Ruta del video: {video_path}")
                    print(f"  Â¿Existe? {os.path.exists(video_path)}")
                    
                    # Asignar video al segmento
                    self.segments[segment_index]['video_path'] = video_path
                    self.segments[segment_index]['image_path'] = video_path  # Usar image_path para compatibilidad
                    self.segments[segment_index]['video_source'] = 'youtube'
                    self.segments[segment_index]['image_source'] = 'youtube'
                    
                    # Eliminar flag de imagen eliminada si existe
                    if 'image_deleted' in self.segments[segment_index]:
                        del self.segments[segment_index]['image_deleted']
                    
                    self._refresh_media_widgets([segment_index], {segment_index: None})
                    print(f"  Preview actualizado para el segmento #{segment_index + 1}")
                    
                    QMessageBox.information(
                        self,
                        "Video Asignado",
                        f"âœ… Video asignado correctamente al segmento #{segment_index + 1}.\n\n"
                        f"ðŸ“ UbicaciÃ³n: {video_path}"
                    )
                    # Activar auto-guardado automÃ¡tico
                    self._trigger_auto_save("despuÃ©s de agregar video de YouTube")
                else:
                    # El video no se descargÃ³ correctamente o no existe
                    error_msg = f"No se pudo encontrar el video descargado."
                    if video_path:
                        error_msg += f"\n\nRuta esperada: {video_path}\n"
                        error_msg += f"Â¿Existe el archivo? {os.path.exists(video_path)}"
                    else:
                        error_msg += "\n\nEl diÃ¡logo no devolviÃ³ una ruta de video."
                    
                    QMessageBox.warning(
                        self,
                        "Error al Asignar Video",
                        error_msg
                    )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Error al abrir el diÃ¡logo de bÃºsqueda de videos:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()


    def _open_internet_archive_video_dialog_for_segment(self, segment, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de videos histÃ³ricos en Internet Archive para un segmento especÃ­fico"""
        if not INTERNET_ARCHIVE_AVAILABLE:
            QMessageBox.warning(
                self,
                "Internet Archive no disponible",
                "El cliente de Internet Archive no estÃ¡ disponible."
            )
            return
        
        try:
            dialog = InternetArchiveVideoSearchDialog(self, segment_data=segment)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                video_path = dialog.selected_video_path
                
                if video_path and os.path.exists(video_path):
                    # Convertir a ruta absoluta para evitar problemas de rutas relativas
                    video_path = os.path.abspath(video_path)
                    
                    # Asignar video al segmento
                    self.segments[segment_index]['video_path'] = video_path
                    self.segments[segment_index]['image_path'] = video_path  # Usar image_path para compatibilidad
                    self.segments[segment_index]['video_source'] = 'internet_archive'
                    self.segments[segment_index]['image_source'] = 'internet_archive'
                    
                    # Eliminar flag de imagen eliminada si existe
                    if 'image_deleted' in self.segments[segment_index]:
                        del self.segments[segment_index]['image_deleted']
                    
                    self._refresh_media_widgets([segment_index], {segment_index: None})
                    
                    QMessageBox.information(
                        self,
                        "Video Asignado",
                        f"âœ… Video asignado correctamente al segmento #{segment_index + 1}.\n\n"
                        f"ðŸ“ UbicaciÃ³n: {video_path}"
                    )
                    # Activar auto-guardado automÃ¡tico
                    self._trigger_auto_save("despuÃ©s de agregar video de Wikimedia")
                else:
                    # El video no se descargÃ³ correctamente o no existe
                    error_msg = f"No se pudo encontrar el video descargado."
                    if video_path:
                        error_msg += f"\n\nRuta esperada: {video_path}\n"
                        error_msg += f"Â¿Existe el archivo? {os.path.exists(video_path)}"
                    else:
                        error_msg += "\n\nEl diÃ¡logo no devolviÃ³ una ruta de video."
                    
                    QMessageBox.warning(
                        self,
                        "Error al Asignar Video",
                        error_msg
                    )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Error al abrir el diÃ¡logo de bÃºsqueda de videos:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()


    def _open_pexels_video_dialog_for_segment(self, segment, segment_index):
        """Abre el diÃ¡logo de bÃºsqueda de videos de Pexels para un segmento especÃ­fico"""
        if not PEXELS_AVAILABLE:
            QMessageBox.warning(
                self,
                "Pexels no disponible",
                "El cliente de Pexels no estÃ¡ disponible.\n"
                "AsegÃºrate de que auto_video_generator_v2.py estÃ© en el directorio del proyecto.\n\n"
                "TambiÃ©n necesitas configurar PEXELS_API_KEY en tu archivo .env"
            )
            return
        
        # Crear y mostrar el diÃ¡logo
        try:
            dialog = PexelsVideoSearchDialog(self, segment)
            selected_video_path = None
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Obtener el video seleccionado
                selected_video_path = dialog.selected_video_path
            
            if selected_video_path:
                # Actualizar el segmento en la lista
                if segment_index < len(self.segments):
                    # Convertir a ruta absoluta para evitar problemas de rutas relativas
                    selected_video_path = os.path.abspath(selected_video_path)
                    self.segments[segment_index]['image_path'] = selected_video_path  # Usar image_path para compatibilidad
                    self.segments[segment_index]['video_path'] = selected_video_path  # TambiÃ©n guardar como video_path
                    self.segments[segment_index]['image_source'] = 'pexels_video'  # Marcar como video de Pexels
                    self.segments[segment_index]['video_source'] = 'pexels_video'  # TambiÃ©n establecer video_source
                    
                    # Eliminar flag de imagen eliminada si existe (para que se muestre el preview)
                    if 'image_deleted' in self.segments[segment_index]:
                        del self.segments[segment_index]['image_deleted']
                    
                    self._refresh_media_widgets([segment_index], {segment_index: None})
                    
                    # Actualizar el editor de segmentos si estÃ¡ mostrando este segmento
                    if self.selected_index == segment_index:
                        self.segment_editor.load_segment(self.segments[segment_index])
                
                QMessageBox.information(
                    self,
                    "Video Asignado",
                    f"Se asignÃ³ un video de Pexels al segmento #{segment_index + 1}.\n"
                    f"El video se ajustÃ³ automÃ¡ticamente a la duraciÃ³n del segmento."
                )
                # Activar auto-guardado automÃ¡tico
                self._trigger_auto_save("despuÃ©s de agregar video de Pexels")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Error al abrir el diÃ¡logo de bÃºsqueda de videos:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
