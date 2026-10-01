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


from studio.timeline_search_dialogs_mixin import TimelineSearchDialogsMixin


class TimelineLocalMediaMixin:
    def _handle_local_image_dropped(self, segment_index, file_path):
        """Selecciona el segmento destino y asigna la imagen soltada."""
        if segment_index < 0 or segment_index >= len(self.segments):
            return False
        if self.selected_index != segment_index:
            self.on_segment_clicked(segment_index)
        return self._apply_local_image_with_range(
            segment_index,
            file_path,
            auto_save_reason="despues de soltar imagen local",
        )


    def _handle_local_video_dropped(self, segment_index, file_path):
        """Selecciona el segmento destino y asigna el video soltado."""
        if segment_index < 0 or segment_index >= len(self.segments):
            return False
        if self.selected_index != segment_index:
            self.on_segment_clicked(segment_index)

        video_path = os.path.abspath(file_path)
        if not os.path.exists(video_path):
            return False

        self.segments[segment_index]['video_path'] = video_path
        self.segments[segment_index]['image_path'] = video_path
        self.segments[segment_index]['video_source'] = 'local'
        self.segments[segment_index]['image_source'] = 'local'

        if 'image_deleted' in self.segments[segment_index]:
            del self.segments[segment_index]['image_deleted']

        self._refresh_media_widgets([segment_index], {segment_index: None})

        if self.selected_index == segment_index:
            self.segment_editor.load_segment(self.segments[segment_index])

        print(f"[TimelineEditor]  Video local asignado (drag & drop) al segmento #{segment_index + 1}: {os.path.basename(video_path)}")
        self._trigger_auto_save("despues de soltar video local")
        return True


    def _save_clipboard_image_to_temp_file(self, image, segment_index):
        """Guarda una imagen del portapapeles en un archivo temporal PNG."""
        if image is None or image.isNull():
            return None

        fd, temp_path = tempfile.mkstemp(
            prefix=f"segment_{segment_index + 1:03d}_clipboard_",
            suffix=".png"
        )
        os.close(fd)

        try:
            if image.save(temp_path, "PNG"):
                return temp_path
        except Exception as e:
            print(f"[TimelineEditor] Error guardando imagen de portapapeles: {e}")

        try:
            os.remove(temp_path)
        except OSError:
            pass
        return None


    def _extract_pasteable_image_from_clipboard(self, segment_index):
        """Extrae una imagen pegable desde el portapapeles.

        Retorna una tupla `(file_path, should_cleanup_temp)`.
        """
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData() if clipboard else None
        if not mime_data:
            return None, False

        try:
            if mime_data.hasUrls():
                for url in mime_data.urls():
                    if not url.isLocalFile():
                        continue
                    local_path = os.path.abspath(url.toLocalFile())
                    if os.path.isfile(local_path) and Path(local_path).suffix.lower() in SUPPORTED_CLIPBOARD_IMAGE_EXTENSIONS:
                        return local_path, False
        except Exception as e:
            print(f"[TimelineEditor] Warning leyendo URLs del portapapeles: {e}")

        clipboard_text = str(mime_data.text() or "").strip().strip('"')
        if (
            clipboard_text and
            os.path.isfile(clipboard_text) and
            Path(clipboard_text).suffix.lower() in SUPPORTED_CLIPBOARD_IMAGE_EXTENSIONS
        ):
            return os.path.abspath(clipboard_text), False

        try:
            if mime_data.hasImage():
                image = clipboard.image()
                temp_path = self._save_clipboard_image_to_temp_file(image, segment_index)
                if temp_path:
                    return temp_path, True
        except Exception as e:
            print(f"[TimelineEditor] Warning leyendo imagen del portapapeles: {e}")

        try:
            pixmap = clipboard.pixmap()
            if pixmap and not pixmap.isNull():
                temp_path = self._save_clipboard_image_to_temp_file(pixmap.toImage(), segment_index)
                if temp_path:
                    return temp_path, True
        except Exception as e:
            print(f"[TimelineEditor] Warning leyendo pixmap del portapapeles: {e}")

        return None, False


    def _paste_clipboard_image_to_segment(self, segment_index):
        """Pega una imagen copiada en el portapapeles directamente en un segmento."""
        if segment_index < 0 or segment_index >= len(self.segments):
            return False

        if self.selected_index != segment_index:
            self.on_segment_clicked(segment_index)

        file_path, should_cleanup_temp = self._extract_pasteable_image_from_clipboard(segment_index)
        if not file_path:
            QMessageBox.information(
                self,
                "Portapapeles sin imagen",
                "No se encontro una imagen pegable en el portapapeles.\n\n"
                "Copia una imagen real o una ruta local de imagen y vuelve a intentarlo."
            )
            return False

        try:
            assigned = self._apply_local_image_with_range(
                segment_index,
                file_path,
                auto_save_reason="despues de pegar imagen desde portapapeles",
            )
        finally:
            if should_cleanup_temp and file_path:
                try:
                    os.remove(file_path)
                except OSError:
                    pass

        if not assigned:
            QMessageBox.warning(
                self,
                "No se pudo pegar la imagen",
                "La imagen del portapapeles no pudo asignarse a este segmento."
            )
            return False

        print(f"[TimelineEditor] Imagen del portapapeles asignada al segmento {segment_index + 1}")
        return True


    def _paste_clipboard_image_to_group(self, indices):
        """Pega la imagen del portapapeles en todos los segmentos de un grupo compartido."""
        valid = sorted({int(i) for i in (indices or []) if isinstance(i, int) and 0 <= i < len(self.segments)})
        if not valid:
            return False

        file_path, should_cleanup_temp = self._extract_pasteable_image_from_clipboard(valid[0])
        if not file_path:
            QMessageBox.information(
                self,
                "Portapapeles sin imagen",
                "No se encontró una imagen pegable en el portapapeles.\n\n"
                "Copia una imagen real o una ruta local de imagen y vuelve a intentarlo."
            )
            return False

        try:
            assigned = self._assign_local_image_to_segments(
                valid,
                file_path,
                auto_save_reason="despues de pegar imagen desde portapapeles en grupo"
            )
        finally:
            if should_cleanup_temp and file_path:
                try:
                    os.remove(file_path)
                except OSError:
                    pass

        if not assigned:
            QMessageBox.warning(self, "No se pudo pegar", "La imagen del portapapeles no pudo asignarse al grupo.")
            return False

        print(f"[TimelineEditor] Imagen del portapapeles asignada al grupo: segmentos {[i+1 for i in valid]}")
        return True


    def _is_video_media_path(self, media_path) -> bool:
        """Determina si la ruta corresponde a un video segun su extension."""
        return str(media_path or "").lower().endswith(
            (".mp4", ".webm", ".avi", ".mov", ".mkv", ".ogv", ".mpeg", ".mpg")
        )


    def _segment_has_movable_manual_image(self, segment) -> bool:
        """Valida si el segmento contiene una imagen manual apta para mover entre segmentos."""
        if not isinstance(segment, dict) or segment.get("image_deleted", False):
            return False

        image_path = segment.get("image_path")
        if not image_path or segment.get("video_path") or self._is_video_media_path(image_path):
            return False

        image_source = str(segment.get("image_source", "")).lower().strip()
        if image_source in TIMELINE_MANUAL_IMAGE_SOURCES:
            return True
        if image_source in TIMELINE_AI_IMAGE_SOURCES:
            return False

        image_path_hint = str(image_path).lower()
        return not any(token in image_path_hint for token in TIMELINE_AI_PATH_HINTS)


    def _move_manual_image_between_segments(self, source_index, target_index):
        """Mueve una imagen manual desde un segmento origen a otro segmento destino."""
        if (
            source_index < 0 or target_index < 0 or
            source_index >= len(self.segments) or target_index >= len(self.segments)
        ):
            return False

        if source_index == target_index:
            return True

        source_segment = self.segments[source_index]
        if not self._segment_has_movable_manual_image(source_segment):
            return False

        if self.selected_index != target_index:
            self.on_segment_clicked(target_index)

        target_segment = self.segments[target_index]
        moved_image_path = source_segment.get("image_path")
        moved_image_source = source_segment.get("image_source")

        target_segment["image_path"] = moved_image_path
        if moved_image_source:
            target_segment["image_source"] = moved_image_source
        else:
            target_segment.pop("image_source", None)
        target_segment.pop("image_deleted", None)
        target_segment.pop("video_path", None)
        target_segment.pop("video_source", None)

        source_segment.pop("image_path", None)
        source_segment.pop("image_source", None)
        source_segment.pop("image_deleted", None)
        source_segment.pop("original_image_path", None)

        self._refresh_media_widgets(
            [source_index, target_index],
            {
                source_index: None,
                target_index: moved_image_path,
            },
        )

        if hasattr(self, "segment_editor") and self.segment_editor:
            if self.selected_index == target_index:
                self.segment_editor.load_segment(target_segment)
            elif self.selected_index == source_index:
                self.segment_editor.load_segment(source_segment)

        self._trigger_auto_save("despues de mover imagen manual entre segmentos")
        print(f"[TimelineEditor] Imagen manual movida: segmento {source_index + 1} -> {target_index + 1}")
        return True


    def _persist_local_image_into_project(self, file_path, segment_index):
        """Copia la imagen local a project_media cuando hay proyecto activo."""
        normalized_path = os.path.abspath(file_path)
        if not os.path.isfile(normalized_path):
            return None
        studio_tab = self.studio_tab or self._get_studio_tab()
        current_project_path = getattr(studio_tab, "current_project_path", None) if studio_tab else None
        if not current_project_path:
            return normalized_path
        try:
            import shutil
            source_path = Path(normalized_path)
            project_dir = Path(current_project_path).parent
            media_dir = project_dir / "project_media"
            media_dir.mkdir(exist_ok=True)
            try:
                source_resolved = source_path.resolve()
                media_resolved = media_dir.resolve()
                if source_resolved.parent == media_resolved:
                    return f"project_media/{source_path.name}"
            except Exception:
                pass
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source_path.stem).strip("._")
            if not safe_stem:
                safe_stem = f"segment_{segment_index + 1:03d}"
            safe_stem = safe_stem[:80]
            extension = source_path.suffix.lower() or ".png"
            filename = f"segment_{segment_index + 1:03d}_{safe_stem}{extension}"
            destination = media_dir / filename
            try:
                same_file = source_path.resolve() == destination.resolve()
            except Exception:
                same_file = str(source_path) == str(destination)
            if not same_file:
                shutil.copy2(source_path, destination)
            return f"project_media/{destination.name}"
        except Exception as e:
            print(f"[TimelineEditor] Warning copying dropped image into project: {e}")
            return normalized_path


    def _should_strip_gemini_watermark(self) -> bool:
        """Indica si el usuario marco el checkbox 'Imagen de Gemini' en el editor."""
        try:
            editor = getattr(self, "segment_editor", None)
            chk = getattr(editor, "chk_gemini_strip", None) if editor else None
            return bool(chk and chk.isChecked())
        except Exception:
            return False


    def _resolve_stored_image_abspath(self, stored_path: str) -> str:
        """Convierte una ruta relativa project_media/... en absoluta si hay proyecto."""
        if not stored_path:
            return stored_path
        if os.path.isabs(stored_path):
            return stored_path
        studio_tab = self.studio_tab or self._get_studio_tab()
        current_project_path = getattr(studio_tab, "current_project_path", None) if studio_tab else None
        if current_project_path:
            project_dir = Path(current_project_path).parent
            return str((project_dir / stored_path).resolve())
        return os.path.abspath(stored_path)


    def _maybe_strip_gemini_watermark(self, stored_path: str) -> None:
        """Aplica eliminacion del watermark de Gemini sobre la imagen persistida."""
        if not self._should_strip_gemini_watermark():
            return
        abs_path = self._resolve_stored_image_abspath(stored_path)
        if not abs_path or not os.path.isfile(abs_path):
            return
        try:
            from ai.gemini_watermark_remover import remove_gemini_watermark
            remove_gemini_watermark(abs_path)
            print(f"[TimelineEditor] Watermark de Gemini removido: {os.path.basename(abs_path)}")
        except Exception as e:
            print(f"[TimelineEditor] Warning removiendo watermark de Gemini: {e}")


    def _image_change_affects_groups(self, segment_index, new_image_path):
        """Indica si el cambio de imagen en un segmento rompe o crea un grupo.

        Se usa para decidir si basta actualizar un solo widget o hay que
        llamar a ``refresh_timeline`` para recomputar los GroupedSegmentsWidget.
        """
        # Estaba en un grupo existente -> refrescar
        if self._segment_is_currently_grouped(segment_index):
            return True
        # Ahora coincide con un vecino -> podria crear grupo
        new_path_norm = self._normalize_groupable_image_path(new_image_path)
        if not new_path_norm:
            return False
        if segment_index > 0:
            prev = self.segments[segment_index - 1] if isinstance(self.segments[segment_index - 1], dict) else {}
            if self._get_groupable_image_path_for_segment(prev) == new_path_norm:
                return True
        if segment_index + 1 < len(self.segments):
            nxt = self.segments[segment_index + 1] if isinstance(self.segments[segment_index + 1], dict) else {}
            if self._get_groupable_image_path_for_segment(nxt) == new_path_norm:
                return True
        return False


    @staticmethod
    def _segment_media_signature(segment):
        """Firma de la media de un segmento. Si cambia, la agrupacion puede cambiar."""
        if not isinstance(segment, dict):
            return (None, None, False)
        return (
            segment.get('image_path'),
            segment.get('video_path'),
            bool(segment.get('image_deleted', False)),
        )


    def _apply_segments_update(self, new_segments, refresh_media=False):
        """Aplica ``new_segments`` actualizando widgets EN SITIO cuando solo cambio el
        contenido (texto, tiempos) y NO la media de ningun segmento.

        La agrupacion del timeline (por imagen compartida y por bloques de ratio)
        depende unicamente de la presencia/ruta de media. Si la firma de media de
        todos los segmentos es identica y la cantidad no cambio, basta refrescar cada
        widget en su lugar (barato) en vez de destruir y recrear N widgets. En
        cualquier otro caso se cae al ``refresh_timeline`` completo (seguro).

        Reemplaza el patron ``self.segments = X; self.refresh_timeline()`` para
        operaciones de solo-texto, evitando el congelamiento del rebuild total.
        """
        try:
            same_count = (
                len(new_segments) == len(self.segments) == len(self.segment_widgets)
            )
            media_unchanged = same_count and all(
                self._segment_media_signature(self.segments[i])
                == self._segment_media_signature(new_segments[i])
                for i in range(len(new_segments))
            )
        except Exception:
            media_unchanged = False

        self.segments = new_segments

        if not media_unchanged:
            self.refresh_timeline()
            return

        # Estructura/agrupacion intactas -> actualizar widgets en sitio sin tocar layout.
        for idx, widget in enumerate(self.segment_widgets):
            try:
                widget.segment_data = self._build_segment_widget_data(self.segments[idx])
                widget.update_display(refresh_media=refresh_media)
            except Exception:
                pass


    def _refresh_media_widgets(self, segment_indices, candidate_paths=None):
        """Refresca widgets puntuales o reconstruye el timeline si cambia un grupo."""
        valid_indices = sorted({
            int(idx) for idx in (segment_indices or [])
            if isinstance(idx, int) and 0 <= idx < len(self.segments)
        })
        if not valid_indices:
            return False

        path_map = candidate_paths if isinstance(candidate_paths, dict) else {}
        needs_full_refresh = any(
            self._image_change_affects_groups(idx, path_map.get(idx))
            for idx in valid_indices
        )
        if needs_full_refresh:
            self.refresh_timeline()
            return True

        for idx in valid_indices:
            if idx < len(self.segment_widgets):
                self.segment_widgets[idx].segment_data = self._build_segment_widget_data(self.segments[idx])
                self.segment_widgets[idx].update_display(refresh_media=True)
        return False


    def _assign_local_image_to_segment(self, segment_index, file_path, auto_save_reason="despues de insertar imagen local", propagate_ratio=True):
        """Asigna una imagen local a un segmento y refresca la UI relacionada.

        Si images_per_segment_ratio > 1, propaga la imagen al grupo alineado completo
        (igual que hace la generación automática), disparando el widget agrupado visual.
        """
        if segment_index < 0 or segment_index >= len(self.segments):
            return False
        if not file_path:
            return False

        # Propagar al grupo alineado si el ratio es > 1
        ratio = self._get_images_per_segment_frequency()
        if propagate_ratio and ratio > 1:
            group_start = (segment_index // ratio) * ratio
            group_end = min(group_start + ratio - 1, len(self.segments) - 1)
            group_indices = list(range(group_start, group_end + 1))
            if len(group_indices) > 1:
                return self._assign_local_image_to_segments(
                    group_indices, file_path, auto_save_reason
                )

        normalized_path = os.path.abspath(file_path)
        if not os.path.isfile(normalized_path):
            return False

        stored_path = self._persist_local_image_into_project(normalized_path, segment_index)
        if not stored_path:
            return False

        # Si el usuario marco que la imagen proviene de Gemini, quitar el watermark.
        self._maybe_strip_gemini_watermark(stored_path)

        segment = self.segments[segment_index]
        segment["image_path"] = stored_path
        segment["image_source"] = "local"

        # Si el segmento tenia un video, al reemplazarlo por una imagen hay que limpiarlo.
        segment.pop("video_path", None)
        segment.pop("video_source", None)
        segment.pop("image_deleted", None)

        self._trigger_auto_save(auto_save_reason)

        self._refresh_media_widgets([segment_index], {segment_index: stored_path})

        if self.selected_index == segment_index and hasattr(self, "segment_editor") and self.segment_editor:
            self.segment_editor.load_segment(segment)

        print(f"[TimelineEditor] Imagen local asignada al segmento {segment_index + 1}: {os.path.basename(stored_path)}")
        return True


    def _assign_local_image_to_segments(self, segment_indices, file_path,
                                         auto_save_reason="despues de insertar imagen local compartida"):
        """Asigna la MISMA imagen local a varios segmentos (consecutivos o no).

        La imagen se persiste una sola vez dentro del proyecto y todos los
        segmentos apuntan a la misma ruta, lo cual dispara la logica de
        agrupacion visual en ``refresh_timeline``.
        """
        if not segment_indices:
            return False
        if not file_path:
            return False

        normalized_path = os.path.abspath(file_path)
        if not os.path.isfile(normalized_path):
            return False

        # Filtrar y ordenar indices validos
        valid_indices = sorted({
            int(idx) for idx in segment_indices
            if isinstance(idx, int) and 0 <= idx < len(self.segments)
        })
        if not valid_indices:
            return False

        # Persistir una sola vez usando el primer segmento como referencia
        first_idx = valid_indices[0]
        stored_path = self._persist_local_image_into_project(normalized_path, first_idx)
        if not stored_path:
            return False

        self._maybe_strip_gemini_watermark(stored_path)

        for idx in valid_indices:
            segment = self.segments[idx]
            segment["image_path"] = stored_path
            segment["image_source"] = "local"
            segment.pop("video_path", None)
            segment.pop("video_source", None)
            segment.pop("image_deleted", None)

        self._trigger_auto_save(auto_save_reason)

        self._refresh_media_widgets(
            valid_indices,
            {idx: stored_path for idx in valid_indices},
        )

        # Mantener seleccion si el segmento seleccionado esta en el rango
        if (self.selected_index in valid_indices
                and hasattr(self, "segment_editor")
                and self.segment_editor):
            self.segment_editor.load_segment(self.segments[self.selected_index])

        print(
            f"[TimelineEditor] Imagen local compartida asignada a {len(valid_indices)} segmento(s): "
            f"{os.path.basename(stored_path)}"
        )
        return True


    def _default_shared_image_count(self, start_index: int) -> int:
        """Default de cobertura: 4 en 16:9 / videos largos, o el spin de frecuencia."""
        remaining = max(1, len(self.segments) - int(start_index))
        default = 1
        studio = getattr(self, "studio_tab", None)
        if studio is not None:
            fmt = ""
            platform = ""
            duration = 0
            if hasattr(studio, "get_selected_video_format"):
                fmt = str(studio.get_selected_video_format() or "")
            if hasattr(studio, "get_selected_platform_key"):
                platform = str(studio.get_selected_platform_key() or "")
            if hasattr(studio, "duration_slider"):
                try:
                    duration = int(studio.duration_slider.value())
                except Exception:
                    duration = 0
            if "16:9" in fmt or platform == "youtube" or duration >= 180:
                default = 4
            if hasattr(studio, "images_per_segment_spin"):
                try:
                    spin_val = int(studio.images_per_segment_spin.value() or 1)
                except Exception:
                    spin_val = 1
                if spin_val > 1:
                    default = spin_val
        return max(1, min(default, remaining))


    def _ask_shared_image_count(self, start_index: int):
        """Muestra el diálogo con preview de textos. None = cancelado."""
        remaining = len(self.segments) - start_index
        if remaining <= 1:
            return 1
        dialog = SharedImageRangeDialog(
            self,
            self.segments,
            start_index,
            default_count=self._default_shared_image_count(start_index),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return max(1, int(dialog.selected_count()))


    def _apply_local_image_with_range(self, segment_index, file_path, auto_save_reason):
        """Asigna una imagen pidiendo el rango consecutivo cuando hay más de un segmento."""
        count = self._ask_shared_image_count(segment_index)
        if count is None:
            return False
        if count <= 1:
            return self._assign_local_image_to_segment(
                segment_index,
                file_path,
                auto_save_reason=auto_save_reason,
                propagate_ratio=False,
            )
        indices = list(range(segment_index, segment_index + count))
        return self._assign_local_image_to_segments(
            indices,
            file_path,
            auto_save_reason=f"{auto_save_reason} x{count}",
        )


    def _open_local_image_dialog_for_segment(self, segment_index):
        """Abre un diálogo para seleccionar una imagen local y su cobertura."""
        if segment_index < 0 or segment_index >= len(self.segments):
            return

        from PyQt6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Imagen Local",
            "",
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.webp *.avif);;Todos los archivos (*.*)"
        )

        if not file_path:
            return

        self._apply_local_image_with_range(
            segment_index,
            file_path,
            auto_save_reason="despues de insertar imagen local",
        )


    def _open_local_video_dialog_for_segment(self, segment_index):
        """Abre el diálogo avanzado para seleccionar y recortar un video local"""
        if segment_index < 0 or segment_index >= len(self.segments):
            return

        segment = self.segments[segment_index]

        try:
            dialog = LocalVideoPickerDialog(self, segment_data=segment)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                video_path = dialog.selected_video_path
                if video_path and os.path.exists(video_path):
                    video_path = os.path.abspath(video_path)
                    self.segments[segment_index]['video_path'] = video_path
                    self.segments[segment_index]['image_path'] = video_path
                    self.segments[segment_index]['video_source'] = 'local'
                    self.segments[segment_index]['image_source'] = 'local'

                    if 'image_deleted' in self.segments[segment_index]:
                        del self.segments[segment_index]['image_deleted']

                    self._refresh_media_widgets([segment_index], {segment_index: None})

                    if self.selected_index == segment_index:
                        self.segment_editor.load_segment(self.segments[segment_index])

                    QMessageBox.information(
                        self,
                        "Video Asignado",
                        f" Video local asignado al segmento #{segment_index + 1}.\n\n"
                        f" {video_path}"
                    )
                    self._trigger_auto_save("después de insertar video local")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Error al abrir el diálogo de video local:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()


    def open_video_edit(self, segment_index):
        """Abre el diÃ¡logo para editar/recortar el video del segmento"""
        if segment_index < 0 or segment_index >= len(self.segments):
            return
        
        segment = self.segments[segment_index]
        
        # Obtener ruta del video
        video_path = segment.get('video_path', None)
        if not video_path:
            # Intentar obtener desde image_path si es un video
            image_path = segment.get('image_path', None)
            if image_path and os.path.exists(image_path):
                # Verificar si es un video por extensiÃ³n
                if image_path.lower().endswith(('.mp4', '.webm', '.avi', '.mov', '.mkv', '.ogv', '.mpeg', '.mpg')):
                    video_path = image_path
        
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(
                self,
                "Sin Video",
                f"El segmento #{segment_index + 1} no tiene un video asignado.\n\n"
                "Usa el menÃº 'Buscar Videos' para asignar un video al segmento."
            )
            return
        
        # Resolver ruta absoluta
        if not os.path.isabs(video_path):
            # Intentar resolver desde el directorio del proyecto
            try:
                parent = self.parent()
                while parent:
                    if hasattr(parent, 'studio_tab') and hasattr(parent.studio_tab, 'current_project_path'):
                        if parent.studio_tab.current_project_path:
                            project_path_obj = Path(parent.studio_tab.current_project_path)
                            project_dir = project_path_obj.parent
                            abs_path = project_dir / video_path
                            if abs_path.exists():
                                video_path = str(abs_path.resolve())
                                break
                    parent = parent.parent() if hasattr(parent, 'parent') else None
            except:
                pass
            
            # Si aÃºn no es absoluta, intentar desde el directorio actual
            if not os.path.isabs(video_path):
                abs_path = Path(video_path).resolve()
                if abs_path.exists():
                    video_path = str(abs_path)
        
        if not os.path.exists(video_path):
            QMessageBox.warning(
                self,
                "Video No Encontrado",
                f"No se pudo encontrar el video:\n{video_path}\n\n"
                "El archivo puede haber sido movido o eliminado."
            )
            return
        
        # Importar y mostrar diÃ¡logo
        try:
            from app.video_edit_dialog import VideoEditDialog
            dialog = VideoEditDialog(self, segment, video_path)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                cropped_video_path = dialog.cropped_video_path
                
                if cropped_video_path and os.path.exists(cropped_video_path):
                    # Actualizar el segmento con el video recortado
                    # Convertir a ruta relativa si es necesario
                    if os.path.isabs(cropped_video_path):
                        try:
                            parent = self.parent()
                            while parent:
                                if hasattr(parent, 'studio_tab') and hasattr(parent.studio_tab, 'current_project_path'):
                                    if parent.studio_tab.current_project_path:
                                        project_path_obj = Path(parent.studio_tab.current_project_path)
                                        project_dir = project_path_obj.parent
                                        try:
                                            rel_path = os.path.relpath(cropped_video_path, project_dir)
                                            if not rel_path.startswith('..'):
                                                cropped_video_path = rel_path.replace('\\', '/')
                                        except:
                                            pass
                                        break
                                parent = parent.parent() if hasattr(parent, 'parent') else None
                        except:
                            pass
                    
                    # Actualizar el segmento
                    self.segments[segment_index]['video_path'] = cropped_video_path
                    self.segments[segment_index]['image_path'] = cropped_video_path  # Actualizar tambiÃ©n image_path si son el mismo
                    
                    self._refresh_media_widgets([segment_index], {segment_index: None})
                    
                    # Actualizar el editor de segmentos si estÃ¡ mostrando este segmento
                    if self.selected_index == segment_index:
                        self.segment_editor.load_segment(self.segments[segment_index])
                    
                    # Activar auto-guardado
                    self._trigger_auto_save("despuÃ©s de editar video")
                    
                    QMessageBox.information(
                        self,
                        "Video Actualizado",
                        f"âœ… El video del segmento #{segment_index + 1} ha sido actualizado con la parte seleccionada."
                    )
        except ImportError as e:
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo importar el diÃ¡logo de ediciÃ³n de video:\n{str(e)}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Error al editar video:\n{str(e)}"
            )
