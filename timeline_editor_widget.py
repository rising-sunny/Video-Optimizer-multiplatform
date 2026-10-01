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
    from wikimedia_client import WikimediaClient
    WIKIMEDIA_AVAILABLE = True
except ImportError:
    WIKIMEDIA_AVAILABLE = False
    WikimediaClient = None

try:
    from bing_images_client import BingImagesClient
    BING_IMAGES_AVAILABLE = True
except ImportError:
    BING_IMAGES_AVAILABLE = False
    BingImagesClient = None

try:
    from auto_video_generator_v2 import ResourceDownloader
    # Alias para compatibilidad
    StockMediaDownloader = ResourceDownloader
    PEXELS_AVAILABLE = True
except ImportError:
    PEXELS_AVAILABLE = False
    StockMediaDownloader = None
    ResourceDownloader = None

try:
    from wikimedia_client import WikimediaClient
    WIKIMEDIA_VIDEO_AVAILABLE = True
except ImportError:
    WIKIMEDIA_VIDEO_AVAILABLE = False
    WikimediaClient = None

try:
    from internet_archive_client import InternetArchiveClient
    INTERNET_ARCHIVE_AVAILABLE = True
except ImportError:
    INTERNET_ARCHIVE_AVAILABLE = False
    InternetArchiveClient = None

try:
    from youtube_video_client import YouTubeVideoClient, YT_DLP_AVAILABLE
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
from timeline_workers import (
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
from wikimedia_search_dialog import WikimediaSearchDialog
from bing_images_search_dialog import BingImagesSearchDialog
from pexels_video_search_dialog import PexelsVideoSearchDialog
from video_preview_dialog import VideoPreviewDialog
from wikimedia_video_search_dialog import WikimediaVideoSearchDialog
from internet_archive_search_dialog import InternetArchiveVideoSearchDialog
from youtube_video_search_dialog import YouTubeVideoSearchDialog
from local_video_picker_dialog import LocalVideoPickerDialog

# Compatibilidad para imports legacy que aún usan el nombre GoogleImagesSearchDialog
GoogleImagesSearchDialog = BingImagesSearchDialog

# Importar widgets del timeline desde mÃ³dulos separados
from timeline_video_widget import VideoTimelineWidget
from timeline_segment_widget import TimelineSegment, GroupedSegmentsWidget
from timeline_segment_editor import SegmentEditor
try:
    from text_correction_engine import TextCorrectionEngine
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


class TimelineEditorWidget(QWidget):
    """
    Widget principal del Timeline Editor.
    Combina la vista de timeline con el editor de segmentos.
    """
    
    segments_modified = pyqtSignal(list)  # Emite la lista de segmentos modificados
    wikimedia_image_selected = pyqtSignal(int, str)  # Emite (segment_index, image_path) cuando se selecciona una imagen de Wikimedia
    
    def __init__(self, parent=None, studio_tab=None):
        super().__init__(parent)
        self.segments = []
        self.segment_widgets = []
        # Wrappers GroupedSegmentsWidget creados por refresh_timeline cuando varios
        # segmentos consecutivos comparten la misma image_path.
        self._grouped_wrappers = []
        self.selected_index = None
        self.selected_indices = set()  # Para selecciÃ³n mÃºltiple
        self._auto_save_timer = QTimer(self)  # Timer reusable para debounce del auto-guardado
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.timeout.connect(self._execute_auto_save)
        self._pending_auto_save_reason = ""
        self._cached_auto_save_studio_tab = None
        self._on_segment_saved_in_progress = False
        self._sync_storyboard_in_progress = False
        self._pending_preview_indices = deque()
        self._preview_loader_timer = QTimer(self)
        self._preview_loader_timer.setSingleShot(False)
        self._preview_loader_timer.timeout.connect(self._process_pending_previews)
        self._segment_regen_ai_client = None
        self._single_ai_regeneration_workers = {}
        self._fal_i2v_workers = {}
        # IMPORTANTE: Guardar referencia al studio_tab para poder guardar proyectos
        self.studio_tab = studio_tab
        self.bound_project_path = self._normalize_project_path(
            getattr(studio_tab, 'current_project_path', None)
        )
        
        self.setup_ui()

    @staticmethod
    def _normalize_project_path(project_path):
        """Normaliza la ruta del proyecto para comparaciones consistentes."""
        if not project_path:
            return None
        try:
            return os.path.normcase(str(Path(project_path).resolve()))
        except Exception:
            try:
                return os.path.normcase(os.path.abspath(str(project_path)))
            except Exception:
                return str(project_path)

    def bind_to_project(self, project_path):
        """Asocia este timeline al project.json actualmente cargado."""
        self.bound_project_path = self._normalize_project_path(project_path)

    def get_bound_project_path(self):
        """Devuelve la ruta normalizada del proyecto asociado al timeline."""
        return self.bound_project_path

    def _build_segment_widget_data(self, segment):
        """Prepara una copia del segmento con pista del directorio del proyecto."""
        segment_data = segment.copy() if isinstance(segment, dict) else {}
        try:
            if self.studio_tab and getattr(self.studio_tab, 'current_project_path', None):
                segment_data['_project_path_hint'] = str(Path(self.studio_tab.current_project_path).parent)
        except Exception:
            pass
        return segment_data

    def _get_selected_image_aspect_ratio(self) -> str:
        """Aspect ratio de imagen según el formato elegido en la GUI principal."""
        from image_generation_manager import primary_aspect_ratio_from_format

        studio = self.studio_tab or self._get_studio_tab()
        video_format = None
        platform = None
        if studio is not None:
            if hasattr(studio, "get_selected_output_profiles"):
                try:
                    profiles = studio.get_selected_output_profiles() or []
                    if profiles:
                        video_format = profiles[0].get("video_format")
                        platform = profiles[0].get("platform")
                except Exception:
                    pass
            if not video_format and hasattr(studio, "get_selected_video_format"):
                try:
                    video_format = studio.get_selected_video_format()
                except Exception:
                    pass
            if not platform and hasattr(studio, "get_selected_platform_key"):
                try:
                    platform = studio.get_selected_platform_key()
                except Exception:
                    pass
        return primary_aspect_ratio_from_format(video_format, platform)

    def _ensure_prompt_has_selected_aspect(self, prompt: str) -> str:
        """Inyecta 16:9 / 9:16 / 1:1 según el combo 'Formato de video' de la GUI."""
        from image_generation_manager import apply_aspect_ratio_to_visual_prompt
        return apply_aspect_ratio_to_visual_prompt(
            prompt,
            self._get_selected_image_aspect_ratio(),
        )

    def _format_label_for_copied_prompts(self) -> str:
        """Etiqueta '16:9  (1920×1080px)' para el texto copiado al portapapeles."""
        ratio = self._get_selected_image_aspect_ratio()
        resolution = (1920, 1080)
        if ratio == "9:16":
            resolution = (1080, 1920)
        elif ratio == "1:1":
            resolution = (1080, 1080)
        studio = self.studio_tab or self._get_studio_tab()
        if studio and hasattr(studio, "get_selected_resolution"):
            try:
                resolution = studio.get_selected_resolution() or resolution
            except Exception:
                pass
        w, h = resolution
        return f"{ratio}  ({w}×{h}px)"

    def _get_recraft_prompt_style(self) -> str:
        """Obtiene el estilo Recraft visible en la UI."""
        try:
            if self.studio_tab and hasattr(self.studio_tab, 'style_combo') and self.studio_tab.style_combo.count() > 0:
                value = (self.studio_tab.style_combo.currentText() or "").strip()
                if value:
                    return value
        except Exception:
            pass
        return "Photorealism"

    def _get_storyboard_for_recraft_prompt_resolution(self):
        """Construye un storyboard actualizado con los segmentos vivos del timeline."""
        storyboard_data = {}
        if isinstance(getattr(self.studio_tab, 'last_storyboard_data', None), dict):
            storyboard_data = self.studio_tab.last_storyboard_data.copy()
        storyboard_data['segments'] = [
            seg.copy() if isinstance(seg, dict) else {}
            for seg in self.segments
        ]
        return storyboard_data

    def _resolve_recraft_prompt_for_segment(self, segment_index):
        """Resuelve el prompt del provider real (no hardcodeado a Recraft) para el segmento."""
        if segment_index < 0 or segment_index >= len(self.segments):
            return None
        if not self.studio_tab:
            return None

        generator = getattr(self.studio_tab, 'generator', None)
        if not generator:
            return None

        resolver = getattr(generator, 'get_recraft_prompt_for_segment', None)
        if resolver is None and hasattr(generator, '_generator'):
            resolver = getattr(generator._generator, 'get_recraft_prompt_for_segment', None)
        if resolver is None:
            return None

        platform = self.studio_tab.get_selected_platform_key() if hasattr(
            self.studio_tab, 'get_selected_platform_key'
        ) else 'youtube'
        images_per_segment_ratio = self.studio_tab.images_per_segment_spin.value() if hasattr(
            self.studio_tab, 'images_per_segment_spin'
        ) else 1.0
        interleave_images = self.studio_tab.interleave_images_check.isChecked() if hasattr(
            self.studio_tab, 'interleave_images_check'
        ) else False

        # Detectar el provider REAL configurado por el usuario en la combo box.
        # Antes el resolver asumía 'recraft', y el prompt copiado venía con los
        # boosters específicos de Recraft aunque el usuario hubiera generado con
        # ComfyUI/FLUX. Ahora pasamos el provider real → el prompt copiado coincide
        # con lo que realmente se mandó al modelo.
        #
        # Fallback = 'comfy_dev' (FLUX) en vez de 'recraft': si la combo no se puede
        # leer, es mucho más probable que el usuario esté generando con FLUX que con
        # Recraft, y FLUX NO inyecta los boosters de Recraft. Así el preview copiado
        # refleja lo que realmente recibe FLUX. Si la combo SÍ dice "Recraft AI", se
        # resuelve a 'recraft' explícitamente y los boosters sí aparecen (correcto).
        FALLBACK_PROVIDER = 'comfy_dev'
        provider_key = FALLBACK_PROVIDER
        try:
            from studio_image_handlers import resolve_image_provider_key
            combo = getattr(self.studio_tab, 'image_provider_combo', None)
            provider_key = resolve_image_provider_key(combo, default=FALLBACK_PROVIDER)
        except Exception as exc:
            print(f"[TimelineEditor] No se pudo detectar provider del usuario ({exc}); usando '{FALLBACK_PROVIDER}'")
        print(f"[TimelineEditor] Provider para 'Copiar Prompts': {provider_key}")

        try:
            return resolver(
                storyboard_data=self._get_storyboard_for_recraft_prompt_resolution(),
                platform=platform,
                segment_index=segment_index,
                images_per_segment_ratio=images_per_segment_ratio,
                interleave_images=interleave_images,
                style=self._get_recraft_prompt_style(),
                regenerate_prompts=False,
                provider_key=provider_key,
            )
        except TypeError:
            # Compatibilidad: si el resolver es una versión vieja que no acepta
            # provider_key, reintentar sin él.
            try:
                return resolver(
                    storyboard_data=self._get_storyboard_for_recraft_prompt_resolution(),
                    platform=platform,
                    segment_index=segment_index,
                    images_per_segment_ratio=images_per_segment_ratio,
                    interleave_images=interleave_images,
                    style=self._get_recraft_prompt_style(),
                    regenerate_prompts=False,
                )
            except Exception as exc:
                print(f"[TimelineEditor] Error resolviendo prompt para segmento {segment_index + 1}: {exc}")
                return None
        except Exception as exc:
            print(f"[TimelineEditor] Error resolviendo prompt para segmento {segment_index + 1}: {exc}")
            return None

    def _copy_text_to_clipboard(self, text, description, segment_index):
        """Copia texto al portapapeles y deja trazabilidad liviana en la UI."""
        clipboard = QApplication.clipboard()
        if not clipboard:
            raise RuntimeError("Portapapeles no disponible")

        clipboard.setText(str(text or ""))
        message = f"{description} copiado para segmento {segment_index + 1}"
        print(f"[TimelineEditor] {message}")
        if self.studio_tab and hasattr(self.studio_tab, 'log'):
            self.studio_tab.log(f" {message}")
        if self.studio_tab and hasattr(self.studio_tab, 'update_status'):
            self.studio_tab.update_status(message)

    def _art_directed_prompts(self, indices):
        """{indice: {'prompt', 'negative_prompt'}} con direccion de arte (visual_art_direction).

        El prompt copiado va a una IA de imagen externa: biblia visual del video +
        un plano por segmento segun su narracion. Si hace falta consultar al modelo,
        lo hace en un hilo con un dialogo de espera. {} si esta apagado o falla:
        entonces se copia el prompt del proveedor interno, como antes.
        """
        ready = self._ensure_art_view(indices)
        if not ready:
            return {}
        vad, view, aspect, style = ready
        out = {}
        for i in indices:
            data = vad.prompt_for_segment(view, i, aspect=aspect, style=style)
            if data and data.get('prompt'):
                out[i] = data
        return out

    def copy_video_prompt_for_segment(self, segment_index):
        """Copia el prompt de video del segmento (para una IA de video externa).

        Sale del mismo plano que el prompt de imagen: arranca en ese cuadro y le suma
        movimiento de camara, del sujeto y del ambiente, la duracion del segmento y
        el sonido. Trae tambien una version 'solo movimiento' para animar la imagen.
        Si la direccion de arte no esta disponible, arma uno con el visual_prompt y
        el motion_prompt del segmento.
        """
        if not (0 <= segment_index < len(self.segments)):
            return
        try:
            import visual_art_direction as vad
        except Exception as exc:
            QMessageBox.warning(self, "Prompt de video", f"No disponible: {exc}")
            return
        data = None
        ready = self._ensure_art_view([segment_index])
        if ready:
            _, view, aspect, style = ready
            data = vad.video_prompt_for_segment(view, segment_index, aspect=aspect, style=style)
        label = "Prompt de video con direccion de arte"
        if not data:
            seg = self.segments[segment_index]
            data = vad.fallback_video_prompt(seg, aspect=self._get_selected_image_aspect_ratio(),
                                             is_opening=segment_index == 0 or bool(seg.get('hook_overlay')))
            label = "Prompt de video (basico: la direccion de arte no respondio)"
        self._copy_text_to_clipboard(
            vad.video_clipboard_text(data, self._format_label_for_copied_prompts()), label, segment_index)

    def _ensure_art_view(self, indices):
        """(vad, vista, aspecto, estilo) con la direccion de arte al dia para esos segmentos, o None."""
        try:
            import visual_art_direction as vad
        except Exception as exc:
            print(f"[TimelineEditor] Direccion de arte no disponible: {exc}")
            return None
        if not vad.enabled() or not self.segments:
            return None
        studio = self.studio_tab
        base = getattr(studio, 'last_storyboard_data', None) if studio else None
        base = base if isinstance(base, dict) else {}
        view = {
            'topic': base.get('topic') or base.get('title') or '',
            'visual_bible': base.get('visual_bible'),
            'segments': self.segments,          # los dicts vivos: el plano queda guardado en cada segmento
        }
        aspect = self._get_selected_image_aspect_ratio()
        style = self._get_recraft_prompt_style()
        if vad.needs_work(view, indices):
            import threading
            from PyQt6.QtWidgets import QProgressDialog
            logs, box = [], {}

            def _work():
                try:
                    box['ready'] = vad.ensure_art_direction(view, indices, aspect=aspect, style=style,
                                                            log=logs.append)
                except Exception as exc:
                    logs.append(f"   [Arte] fallo: {exc}")

            dlg = QProgressDialog("Disenando los planos (biblia visual, luz, paleta, lente)...", None, 0, 0, self)
            dlg.setWindowTitle("Direccion de arte")
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
            dlg.setMinimumDuration(0)
            dlg.show()
            worker = threading.Thread(target=_work, daemon=True)
            worker.start()
            while worker.is_alive():
                QApplication.processEvents()
                worker.join(0.05)
            dlg.close()
            for line in logs:
                print(line)
                if studio and hasattr(studio, 'log'):
                    studio.log(line)
            if view.get('visual_bible') and studio is not None and isinstance(getattr(studio, 'last_storyboard_data', None), dict):
                studio.last_storyboard_data['visual_bible'] = view['visual_bible']
            self._trigger_auto_save("direccion de arte de los prompts")
        return vad, view, aspect, style

    def copy_recraft_prompts_for_segment(self, segment_index):
        """Copia al portapapeles el prompt y negative prompt Recraft del segmento."""
        # Primero el prompt con direccion de arte (para IAs externas); si no hay, el de siempre.
        art = self._art_directed_prompts([segment_index]).get(segment_index)
        if art:
            text_to_copy = (f"Formato: {self._format_label_for_copied_prompts()}\n\n"
                            f"Prompt:\n{art['prompt']}\n\n"
                            f"Negative Prompt:\n{art['negative_prompt']}")
            self._copy_text_to_clipboard(text_to_copy.strip(), "Prompt con direccion de arte", segment_index)
            return

        prompt_data = self._resolve_recraft_prompt_for_segment(segment_index)
        prompt = (prompt_data or {}).get('prompt', '').strip()
        negative_prompt = (prompt_data or {}).get('negative_prompt', '').strip()

        if not prompt:
            prompt = str(
                (self.segments[segment_index] if 0 <= segment_index < len(self.segments) else {})
                .get('visual_prompt') or ''
            ).strip()
        if not negative_prompt and 0 <= segment_index < len(self.segments):
            negative_prompt = str(
                self.segments[segment_index].get('negative_prompt')
                or self.segments[segment_index].get('neg_prompt')
                or ''
            ).strip()

        if prompt:
            prompt = self._ensure_prompt_has_selected_aspect(prompt)
        
        if not prompt and not negative_prompt:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Sin prompts Recraft",
                f"El segmento #{segment_index + 1} no tiene un prompt ni negative prompt Recraft disponible con la configuración actual."
            )
            return

        format_label = self._format_label_for_copied_prompts()
        text_to_copy = f"Formato: {format_label}\n\n"
        if prompt:
            # \n reales (no \\n) para que al pegar se rendericen como saltos de línea
            # y no como los dos caracteres literales backslash+n.
            text_to_copy += f"Prompt:\n{prompt}\n\n"
        if negative_prompt:
            text_to_copy += f"Negative Prompt:\n{negative_prompt}"
            
        self._copy_text_to_clipboard(
            text_to_copy.strip(),
            "Prompt y Negative Prompt Recraft",
            segment_index,
        )

    
    def copy_all_prompts_to_clipboard(self):
        """Copia al portapapeles los prompts Recraft completos (expandidos) de todos los segmentos."""
        if not self.segments:
            QMessageBox.information(self, "Sin segmentos", "No hay segmentos para copiar.")
            return

        # Asegurar que la orientación de los prompts es coherente con el formato actual
        self._fix_segment_prompts_orientation()

        format_label = self._format_label_for_copied_prompts()

        # Contexto del guión desde last_storyboard_data
        storyboard_data = {}
        if self.studio_tab and isinstance(getattr(self.studio_tab, 'last_storyboard_data', None), dict):
            storyboard_data = self.studio_tab.last_storyboard_data
        # El storyboard puede estar anidado bajo 'storyboard'
        sb_inner = storyboard_data.get('storyboard', {}) if isinstance(storyboard_data.get('storyboard'), dict) else {}
        topic    = str(storyboard_data.get('topic') or sb_inner.get('topic') or '').strip()
        category = str(storyboard_data.get('category') or sb_inner.get('category') or '').strip()
        script   = str(storyboard_data.get('script') or sb_inner.get('script') or '').strip()
        title    = str(storyboard_data.get('title') or sb_inner.get('title') or topic).strip()

        # Diálogo de progreso mientras se resuelven los prompts
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("Resolviendo prompts Recraft...", "Cancelar", 0, len(self.segments), self)
        progress.setWindowTitle("Copiando prompts")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        # Construir encabezado de contexto
        header = [f"Formato: {format_label}"]
        if title:
            header.append(f"Tema: {title}")
        if category:
            header.append(f"Categoría: {category}")
        if script:
            # Incluir el guión completo como contexto de época/narrativa
            header.append(f"\nContexto del guión:\n{script}")
        header.append("")

        lines = header[:]
        has_content = False

        # Prompts con direccion de arte para todos (una biblia visual + planos por tandas).
        progress.hide()
        art_prompts = self._art_directed_prompts(list(range(len(self.segments))))
        progress.show()

        for i in range(len(self.segments)):
            if progress.wasCanceled():
                return
            progress.setValue(i)
            progress.setLabelText(f"Resolviendo segmento {i + 1} de {len(self.segments)}...")

            if i in art_prompts:
                has_content = True
                lines.append(f"=== Segmento {i + 1} ===")
                lines.append(f"Prompt:\n{art_prompts[i]['prompt']}")
                lines.append(f"Neg prompt: {art_prompts[i]['negative_prompt']}")
                lines.append("")
                continue

            prompt_data = self._resolve_recraft_prompt_for_segment(i)
            prompt = str((prompt_data or {}).get('prompt') or '').strip()
            neg = str((prompt_data or {}).get('negative_prompt') or '').strip()

            # Fallback al visual_prompt del segmento si Recraft no está disponible
            if not prompt:
                prompt = str(self.segments[i].get('visual_prompt') or self.segments[i].get('prompt') or '').strip()
            if not neg:
                neg = str(self.segments[i].get('negative_prompt') or self.segments[i].get('neg_prompt') or '').strip()

            if prompt:
                prompt = self._ensure_prompt_has_selected_aspect(prompt)

            if not prompt and not neg:
                continue
            has_content = True
            lines.append(f"=== Segmento {i + 1} ===")
            if prompt:
                lines.append(f"Prompt: {prompt}")
            if neg:
                lines.append(f"Neg prompt: {neg}")
            lines.append("")

        progress.setValue(len(self.segments))
        progress.close()

        if not has_content:
            QMessageBox.information(self, "Sin prompts", "Ningún segmento tiene prompt o neg prompt definido.")
            return

        unified = "\n".join(lines).strip()
        QApplication.clipboard().setText(unified)

        msg = f"Prompts Recraft de {len(self.segments)} segmentos copiados al portapapeles ({format_label})."
        print(f"[TimelineEditor] {msg}")
        if self.studio_tab and hasattr(self.studio_tab, 'log'):
            self.studio_tab.log(f" {msg}")
        if self.studio_tab and hasattr(self.studio_tab, 'update_status'):
            self.studio_tab.update_status(msg)

    def closeEvent(self, event):
        """Manejar el evento de cierre para limpiar recursos"""
        self.cleanup()
        super().closeEvent(event)
        
    def cleanup(self):
        """Limpiar recursos y detener workers"""
        try:
            print("[TimelineEditor] Limpiando recursos...")
            
            # 1. Detener temporizador de auto-guardado
            if self._auto_save_timer and self._auto_save_timer.isActive():
                self._auto_save_timer.stop()
            if self._preview_loader_timer and self._preview_loader_timer.isActive():
                self._preview_loader_timer.stop()
            self._pending_preview_indices.clear()
            
            # 2. Forzar guardado final si es necesario
            # self.force_save_now() # Opcional, puede demorar el cierre
            
            # 3. Detener workers de generaciÃ³n de IA activos
            if hasattr(self, 'ai_generation_workers'):
                for worker in self.ai_generation_workers:
                    if worker.isRunning():
                        worker.quit()
                        worker.wait()

            for worker in list(getattr(self, '_single_ai_regeneration_workers', {}).values()):
                try:
                    if worker and worker.isRunning():
                        worker.quit()
                        worker.wait()
                except Exception:
                    pass
            if hasattr(self, '_single_ai_regeneration_workers'):
                self._single_ai_regeneration_workers.clear()
            
            print("[TimelineEditor] Recursos limpiados correctamente")
        except Exception as e:
            print(f"âš ï¸ Error en cleanup: {e}")

    def _trigger_auto_save(self, reason=""):
        """Activa el auto-guardado automÃ¡tico despuÃ©s de un breve delay (debounce)"""
        try:
            # Reutilizar referencia si ya existe para evitar traversal repetido
            studio_tab = self._cached_auto_save_studio_tab or self.studio_tab
            if not studio_tab:
                parent = self.parent()
                while parent:
                    if hasattr(parent, 'studio_tab') and parent.studio_tab:
                        studio_tab = parent.studio_tab
                        break
                    if hasattr(parent, 'parent'):
                        parent = parent.parent()
                    else:
                        break

            if studio_tab and hasattr(studio_tab, 'project_manager'):
                self._cached_auto_save_studio_tab = studio_tab
                if hasattr(studio_tab, '_refresh_assemble_button_state'):
                    studio_tab._refresh_assemble_button_state(reason=reason)
                self._pending_auto_save_reason = reason
                self._auto_save_timer.stop()
                self._auto_save_timer.start(2000)  # 2 segundos de delay
                print(f"[TimelineEditor] Auto-guardado programado en 2 segundos ({reason})")
        except Exception as e:
            print(f"âš ï¸ Error activando auto-guardado: {e}")

    def _execute_auto_save(self):
        """Ejecuta auto-guardado diferido sin recrear timers/lambdas."""
        studio_tab = self._cached_auto_save_studio_tab or self.studio_tab
        if not studio_tab or not hasattr(studio_tab, 'project_manager'):
            return
        try:
            reason = self._pending_auto_save_reason or ""
            studio_tab.project_manager.auto_save_project(f"auto-guardado {reason}")
        except Exception as e:
            print(f"âš ï¸ Error en auto-guardado: {e}")

    def commit_active_segment_edits(self) -> bool:
        """
        Fuerza commit del segmento activo del editor hacia self.segments/storyboard
        sin depender exclusivamente del autosave por seÃ±ales.
        """
        try:
            if not hasattr(self, 'segment_editor') or not self.segment_editor:
                return False
            if not getattr(self.segment_editor, 'current_segment', None):
                return False

            target_index = self.selected_index
            if target_index is None or target_index < 0 or target_index >= len(self.segments):
                return False

            original_segment = self.segments[target_index].copy()

            if hasattr(self.segment_editor, '_snapshot_editor_values'):
                snap = self.segment_editor._snapshot_editor_values()
            else:
                snap = {
                    'start': self.segment_editor.start_spin.value(),
                    'end': self.segment_editor.end_spin.value(),
                    'text': self.segment_editor.text_edit.toPlainText(),
                    'visual_prompt': self.segment_editor.visual_edit.toPlainText(),
                    'sfx_tag': self.segment_editor.sfx_edit.text().strip() or 'none',
                    'overlay_tag': self.segment_editor.overlay_edit.text().strip() or 'none',
                    'assigned_filename': self.segment_editor.filename_edit.text().strip()
                }

            updated_segment = original_segment.copy()
            updated_segment['start'] = snap.get('start', updated_segment.get('start', 0.0))
            updated_segment['end'] = snap.get('end', updated_segment.get('end', updated_segment.get('start', 0.0)))
            updated_segment['text'] = snap.get('text', updated_segment.get('text', ''))
            updated_segment['visual_prompt'] = snap.get('visual_prompt', updated_segment.get('visual_prompt', ''))
            updated_segment['sfx_tag'] = snap.get('sfx_tag', updated_segment.get('sfx_tag', 'none'))
            updated_segment['overlay_tag'] = snap.get('overlay_tag', updated_segment.get('overlay_tag', 'none'))
            updated_segment['assigned_filename'] = snap.get('assigned_filename', updated_segment.get('assigned_filename', ''))

            updated_segment = self._normalize_segment_narrative_fields(updated_segment, target_index)

            self.segments[target_index] = updated_segment

            if target_index < len(self.segment_widgets):
                self.segment_widgets[target_index].segment_data = self._build_segment_widget_data(updated_segment)
                self.segment_widgets[target_index].update_display(refresh_media=False)

            # Mantener el estado interno del editor alineado para evitar falsos "dirty".
            self.segment_editor.current_segment = updated_segment.copy()
            return True
        except Exception as e:
            print(f"[TimelineEditor] âš ï¸ No se pudo forzar commit del segmento activo: {e}")
            return False
    
    
    def force_save_now(self):
        """Fuerza el guardado inmediato sin delay (útil al cerrar)."""
        try:
            if self._auto_save_timer:
                self._auto_save_timer.stop()

            if hasattr(self, 'segment_editor') and self.segment_editor:
                if getattr(self.segment_editor, 'current_segment', None):
                    committed = self.commit_active_segment_edits()
                    if not committed:
                        self.segment_editor.save_changes()
                    if self._auto_save_timer:
                        self._auto_save_timer.stop()

            print("[TimelineEditor]  Iniciando guardado forzado...")

            segments_with_media = [
                (i, seg) for i, seg in enumerate(self.segments)
                if (seg.get('image_path') or seg.get('video_path'))
                and (seg.get('image_source') or seg.get('video_source'))
            ]
            if segments_with_media:
                print(f"[TimelineEditor]  Detectados {len(segments_with_media)} segmentos con videos/imágenes para guardar")
                for i, seg in segments_with_media:
                    print(f"   Segmento {i+1}: image_path={seg.get('image_path')}, video_path={seg.get('video_path')}")
                    print(f"      image_source={seg.get('image_source')}, video_source={seg.get('video_source')}")

            studio_tab = self.studio_tab
            if not studio_tab:
                parent = self.parent()
                while parent:
                    if hasattr(parent, 'studio_tab') and parent.studio_tab:
                        studio_tab = parent.studio_tab
                        break
                    if hasattr(parent, 'project_manager'):
                        studio_tab = parent
                        break
                    if hasattr(parent, 'parent'):
                        parent = parent.parent()
                    else:
                        break

            if studio_tab and hasattr(studio_tab, 'project_manager'):
                print("[TimelineEditor]  Llamando a auto_save_project...")
                studio_tab.project_manager.auto_save_project("guardado forzado desde Timeline Editor")
                print("[TimelineEditor]  Guardado completado")
            else:
                print("️ [TimelineEditor] No se encontró studio_tab o project_manager")
                if hasattr(self, 'studio_tab'):
                    print(f"   self.studio_tab existe: {self.studio_tab is not None}")
                print(f"   studio_tab encontrado: {studio_tab is not None}")
        except Exception as e:
            print(f"️ Error en guardado forzado: {e}")
            import traceback
            traceback.print_exc()

    def setup_ui(self):
        """Configura la interfaz principal"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header con tÃ­tulo y botones de acciÃ³n (fijo en la parte superior)
        header = self.create_header()
        layout.addWidget(header)
        
        # Widget de previsualizaciÃ³n de subtÃ­tulos
        self.subtitle_preview = SubtitlePreview()
        layout.addWidget(self.subtitle_preview)
        
        # Ãrea de scroll principal para el contenido
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Widget contenedor para el contenido desplazable
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        # Splitter principal: Timeline | Editor
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # IMPORTANTE: Configurar el splitter para que no permita colapsar los paneles
        splitter.setChildrenCollapsible(False)  # Evitar que se oculten los paneles
        
        # Panel izquierdo: Timeline
        timeline_panel = self.create_timeline_panel()
        splitter.addWidget(timeline_panel)
        
        # Panel derecho: Editor de segmento
        self.segment_editor = SegmentEditor()
        self.segment_editor.saved.connect(self.on_segment_saved)
        self.segment_editor.wikimedia_search_requested.connect(self.on_segment_editor_wikimedia_search)
        self.segment_editor.openverse_images_search_requested.connect(self.on_segment_editor_openverse_search)
        self.segment_editor.pexels_video_search_requested.connect(self.on_segment_editor_pexels_video_search)
        self.segment_editor.local_image_requested.connect(lambda data: self._open_local_image_dialog_for_segment(self.selected_index))
        self.segment_editor.clipboard_image_requested.connect(lambda data: self._paste_clipboard_image_to_segment(self.selected_index))
        self.segment_editor.local_video_requested.connect(lambda data: self._open_local_video_dialog_for_segment(self.selected_index))
        splitter.addWidget(self.segment_editor)
        
        # IMPORTANTE: Establecer tamaÃ±os mÃ­nimos para asegurar que ambos paneles sean visibles
        timeline_panel.setMinimumWidth(300)  # Ancho mÃ­nimo para el timeline
        self.segment_editor.setMinimumWidth(350)  # Ancho mÃ­nimo para el editor
        
        # IMPORTANTE: Asegurar que el editor sea visible inicialmente
        self.segment_editor.setVisible(True)
        
        # Guardar referencia al splitter y scroll area para poder ajustarlos despuÃ©s
        self.main_splitter = splitter
        self.main_scroll_area = scroll_area
        
        # Proporciones 60/40 - Asegurar que ambos paneles tengan tamaÃ±o suficiente
        splitter.setSizes([600, 400])
        
        scroll_layout.addWidget(splitter)
        
        # Configurar el scroll area con el contenido
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)  # El Ã¡rea de scroll usa todo el espacio disponible
    
    def update_preview(self, text):
        """Actualiza el texto de la vista previa de subtÃ­tulos"""
        if hasattr(self, 'subtitle_preview'):
            if not text:
                self.subtitle_preview.setText("Sin subtÃ­tulo")
                self.subtitle_preview.setStyleSheet(self.subtitle_preview.styleSheet().replace("color: #ffffff;", "color: #888888;"))
            else:
                self.subtitle_preview.setText(text)
                self.subtitle_preview.setStyleSheet(self.subtitle_preview.styleSheet().replace("color: #888888;", "color: #ffffff;"))

    def create_header(self):
        """Crea el header con título y acciones."""
        header = QFrame()
        header.setObjectName("card")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Editor de timeline")
        title.setStyleSheet("font-size: 15pt; font-weight: 600; color: #1f2831;")
        layout.addWidget(title)

        layout.addStretch()

        self.btn_add = QPushButton("Añadir segmento")
        self.btn_add.clicked.connect(self.add_segment)
        layout.addWidget(self.btn_add)

        self.btn_regenerate_script = QPushButton("Regenerar guion (voz+subtitulos)")
        self.btn_regenerate_script.setToolTip(
            "Reconstruye el guion desde los segmentos y regenera narración/subtítulos."
        )
        self.btn_regenerate_script.clicked.connect(self.regenerate_full_script_sync)
        layout.addWidget(self.btn_regenerate_script)

        self.btn_correct_and_regenerate = QPushButton("Corregir textos + regenerar")
        if TEXT_CORRECTION_AVAILABLE:
            self.btn_correct_and_regenerate.setToolTip(
                "Corrige textos de todos los segmentos y luego regenera guion, narracion y subtitulos."
            )
            self.btn_correct_and_regenerate.clicked.connect(self.correct_texts_and_regenerate)
        else:
            self.btn_correct_and_regenerate.setToolTip(
                "Motor de correccion no disponible (text_correction_engine.py)."
            )
            self.btn_correct_and_regenerate.setEnabled(False)
        layout.addWidget(self.btn_correct_and_regenerate)

        self.btn_clear_media_selected = QPushButton("Quitar multimedia seleccionada")
        self.btn_clear_media_selected.setToolTip(
            "Quita completamente la imagen y/o video asignados a los segmentos marcados,\n"
            "dejándolos sin media para poder asignar uno nuevo."
        )
        self.btn_clear_media_selected.clicked.connect(self.clear_media_from_selected)
        self.btn_clear_media_selected.setEnabled(False)
        layout.addWidget(self.btn_clear_media_selected)

        self.btn_delete_ai_images = QPushButton("Limpiar imágenes generadas")
        self.btn_delete_ai_images.clicked.connect(self.delete_all_ai_images)
        layout.addWidget(self.btn_delete_ai_images)

        self.btn_generate_ai_images = QPushButton("Generar imágenes")
        self.btn_generate_ai_images.clicked.connect(self.generate_all_ai_images)
        layout.addWidget(self.btn_generate_ai_images)

        return header
    
    def create_timeline_panel(self):
        """Crea el panel del timeline."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Barra de herramientas con "Seleccionar todos"
        toolbar_layout = QHBoxLayout()

        self.select_all_checkbox = QCheckBox("Seleccionar todos")
        self.select_all_checkbox.stateChanged.connect(self.on_select_all_changed)
        toolbar_layout.addWidget(self.select_all_checkbox)

        toolbar_layout.addStretch()

        copy_prompts_btn = QPushButton("Copiar todos los prompts")
        copy_prompts_btn.setToolTip(
            "Copia al portapapeles los visual prompts de todos los segmentos, "
            "incluyendo el formato de imagen seleccionado en la GUI (16:9, 9:16, 1:1)."
        )
        copy_prompts_btn.setStyleSheet(
            "QPushButton { padding: 3px 10px; font-size: 9pt; border-radius: 4px; }"
        )
        copy_prompts_btn.clicked.connect(self.copy_all_prompts_to_clipboard)
        toolbar_layout.addWidget(copy_prompts_btn)

        layout.addLayout(toolbar_layout)

        info = QLabel("Haz clic en un segmento para editarlo. Arrastra para reordenar y usa clic derecho para más opciones.")
        info.setStyleSheet("color: #6f7c89; font-size: 9pt; padding: 4px 2px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Scroll area para los segmentos
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timeline_scroll = scroll

        self.timeline_container = QWidget()
        self.timeline_layout = QVBoxLayout(self.timeline_container)
        self.timeline_layout.setSpacing(6)
        self.timeline_layout.setContentsMargins(6, 6, 6, 6)
        self.timeline_layout.addStretch()

        scroll.setWidget(self.timeline_container)
        layout.addWidget(scroll)

        return panel
    
    def load_segments(self, segments_list, auto_search_images=False):
        """Carga una lista de segmentos en el timeline
        PRESERVA todos los campos de los segmentos, incluyendo image_path, image_source, video_path, video_source
        """
        # Compatibilidad con callers legacy que envían este argumento.
        _ = auto_search_images
        self.segments = segments_list.copy()  # Esto preserva TODOS los campos, incluyendo image_source y video_source

        # Sanear flags de borrado inconsistentes al abrir el timeline.
        # Si un segmento ya tiene media explicita, image_deleted es obsoleto
        # y no debe bloquear la vista previa.
        for seg in self.segments:
            if seg.get('image_deleted', False):
                has_explicit_media = bool(seg.get('image_path') or seg.get('video_path'))
                if has_explicit_media:
                    seg.pop('image_deleted', None)
                    seg.pop('original_image_path', None)
                else:
                    if 'image_path' in seg and 'original_image_path' not in seg:
                        seg['original_image_path'] = seg.get('image_path')
                    if 'image_path' in seg:
                        del seg['image_path']

        images_count = sum(1 for seg in self.segments if seg.get('image_path') and not seg.get('image_deleted', False))
        videos_count = sum(1 for seg in self.segments if seg.get('video_path'))
        sources_count = sum(1 for seg in self.segments if seg.get('image_source') or seg.get('video_source'))
        
        if images_count > 0 or videos_count > 0:
            print(f"[TimelineEditor] Cargando {len(self.segments)} segmentos:")
            print(f"  - {images_count} con imÃ¡genes vÃ¡lidas")
            print(f"  - {videos_count} con videos")
            print(f"  - {sources_count} con image_source/video_source")
            
            # Mostrar detalles de segmentos con sources para debugging
            if sources_count > 0:
                for i, seg in enumerate(self.segments):
                    if seg.get('image_source') or seg.get('video_source'):
                        print(f"  Segmento {i+1}: image_source={seg.get('image_source')}, video_source={seg.get('video_source')}")
        
        self._fix_segment_prompts_orientation()
        self.refresh_timeline()

    def _fix_segment_prompts_orientation(self):
        """Corrige la orientación de los visual_prompt según el formato de la GUI."""
        ratio = self._get_selected_image_aspect_ratio()
        fixed = 0
        for seg in self.segments:
            prompt = str(seg.get('visual_prompt') or '').strip()
            if not prompt:
                continue
            updated = self._ensure_prompt_has_selected_aspect(prompt)
            if updated != prompt:
                seg['visual_prompt'] = updated
                fixed += 1
        if fixed:
            print(
                f"[TimelineEditor] Orientación de prompts corregida: "
                f"{fixed} segmento(s) actualizados a {ratio}"
            )

    def _normalize_groupable_image_path(self, image_path):
        """Normaliza una ruta candidata para agrupacion visual por imagen."""
        normalized_path = str(image_path or "").strip()
        if not normalized_path or self._is_video_media_path(normalized_path):
            return ""
        return normalized_path

    def _get_groupable_image_path_for_segment(self, segment):
        """Devuelve la image_path utilizable para grupos visuales compartidos."""
        if not isinstance(segment, dict) or segment.get('image_deleted', False):
            return ""
        if segment.get('video_path'):
            return ""
        return self._normalize_groupable_image_path(segment.get('image_path'))

    def _clear_timeline_layout_widgets(self):
        """Vacia el layout visual del timeline y restablece el stretch final."""
        if not hasattr(self, 'timeline_layout') or self.timeline_layout is None:
            return

        while self.timeline_layout.count():
            item = self.timeline_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self.timeline_layout.addStretch()

    def _segment_is_currently_grouped(self, segment_index):
        """Indica si el segmento pertenece actualmente a un GroupedSegmentsWidget."""
        for wrapper in (self._grouped_wrappers or []):
            try:
                if segment_index in wrapper.member_indices:
                    return True
            except Exception:
                continue
        return False
    
    def _detect_shared_image_groups(self):
        """Detecta rachas de segmentos consecutivos que comparten la misma imagen.

        Devuelve una lista de tuplas ``(start_index, end_index_inclusive)``
        para cada grupo con 2+ miembros. Los segmentos huerfanos (un solo
        miembro) no se devuelven, se renderizan en su forma clasica.
        """
        groups = []
        n = len(self.segments)
        i = 0
        while i < n:
            seg = self.segments[i] if isinstance(self.segments[i], dict) else {}
            image_path = self._get_groupable_image_path_for_segment(seg)
            if not image_path:
                i += 1
                continue
            # Extender el grupo mientras el siguiente segmento comparta image_path
            j = i + 1
            while j < n:
                next_seg = self.segments[j] if isinstance(self.segments[j], dict) else {}
                next_path = self._get_groupable_image_path_for_segment(next_seg)
                if next_path != image_path:
                    break
                j += 1
            if j - i >= 2:
                groups.append((i, j - 1))
            i = j if j > i else i + 1
        return groups

    def refresh_timeline(self):
        """Refresca la visualizacion del timeline (con carga progresiva para timelines grandes)"""
        from PyQt6.QtWidgets import QApplication

        # Preservar posición de scroll para no volver al inicio al refrescar
        _scroll_pos = (
            self.timeline_scroll.verticalScrollBar().value()
            if hasattr(self, 'timeline_scroll') and self.timeline_scroll
            else 0
        )

        if self._preview_loader_timer.isActive():
            self._preview_loader_timer.stop()
        self._pending_preview_indices.clear()

        # Limpiar widgets existentes (incluye segmentos y posibles wrappers de grupo)
        self._clear_timeline_layout_widgets()
        self.segment_widgets.clear()
        self._grouped_wrappers = []

        total = len(self.segments)
        BATCH_SIZE = 10  # Procesar eventos cada N segmentos para mantener la UI responsiva
        defer_previews = total > 8

        # Detectar agrupaciones por imagen compartida (consecutivas con misma image_path)
        groups = self._detect_shared_image_groups()
        # indice -> (group_start, group_end) para consulta O(1)
        index_to_group = {}
        for start, end in groups:
            for k in range(start, end + 1):
                index_to_group[k] = (start, end)

        # Si el ratio es > 1, agrupar también los segmentos SIN imagen según
        # los bloques alineados del ratio, para mostrar la estructura antes de
        # que se inserten imágenes.
        ratio = self._get_images_per_segment_frequency()
        if ratio > 1:
            for group_start in range(0, total, ratio):
                group_end = min(group_start + ratio - 1, total - 1)
                if group_end <= group_start:
                    continue
                # Saltar si algún segmento del bloque ya está en un grupo por imagen
                if any(k in index_to_group for k in range(group_start, group_end + 1)):
                    continue
                # Saltar si algún segmento ya tiene imagen (distintas entre sí)
                if any(self.segments[k].get('image_path') for k in range(group_start, group_end + 1)):
                    continue
                for k in range(group_start, group_end + 1):
                    index_to_group[k] = (group_start, group_end)

        # Crear widgets. Los que pertenecen a un grupo se crean en modo compacto
        # y se encapsulan dentro de un GroupedSegmentsWidget.
        _fal_mode = self._is_fal_provider()
        i = 0
        layout_insert_index = 0
        while i < total:
            segment = self.segments[i]

            if i in index_to_group:
                g_start, g_end = index_to_group[i]
                # Construir los N miembros del grupo en modo compacto
                group_members = []
                for k in range(g_start, g_end + 1):
                    member = TimelineSegment(
                        k,
                        self._build_segment_widget_data(self.segments[k]),
                        defer_media_load=defer_previews,
                        compact_image_mode=True,
                        fal_mode=_fal_mode,
                    )
                    self._connect_segment_signals(member)
                    group_members.append(member)
                    self.segment_widgets.append(member)
                    if defer_previews:
                        self._pending_preview_indices.append(k)

                # Construir el wrapper que muestra la imagen grande a la izquierda
                first_seg = self.segments[g_start] if isinstance(self.segments[g_start], dict) else {}
                wrapper = GroupedSegmentsWidget(
                    member_widgets=group_members,
                    shared_image_path=first_seg.get('image_path'),
                    shared_image_source=first_seg.get('image_source'),
                )
                wrapper.grouped_image_change_requested.connect(self._on_grouped_image_change_requested)
                wrapper.grouped_image_remove_requested.connect(self._on_grouped_image_remove_requested)
                wrapper.grouped_image_ungroup_requested.connect(self._on_grouped_image_ungroup_requested)
                wrapper.grouped_image_dropped.connect(self._on_grouped_image_dropped)
                wrapper.grouped_video_dropped.connect(self._on_grouped_video_dropped)
                wrapper.grouped_copy_prompts_requested.connect(self.copy_recraft_prompts_for_segment)
                wrapper.grouped_copy_video_prompt_requested.connect(self.copy_video_prompt_for_segment)
                wrapper.grouped_paste_clipboard_requested.connect(self._paste_clipboard_image_to_group)
                wrapper.grouped_strip_watermark_requested.connect(self._on_grouped_strip_watermark_requested)
                wrapper.grouped_generate_fal_image_requested.connect(self._on_grouped_generate_fal_image)
                wrapper.grouped_animate_fal_video_requested.connect(self._on_grouped_animate_fal_video)
                wrapper.grouped_extend_requested.connect(self._on_grouped_extend_requested)
                wrapper.grouped_shrink_requested.connect(self._on_grouped_shrink_requested)
                wrapper.set_fal_mode(_fal_mode)
                wrapper.set_range_actions_enabled(
                    can_extend=(g_end + 1 < total),
                    can_shrink=(g_end > g_start),
                )
                self._grouped_wrappers.append(wrapper)

                # Insertar secuencialmente antes del stretch final para mantener
                # el orden visual aunque un wrapper represente varios segmentos.
                self.timeline_layout.insertWidget(layout_insert_index, wrapper)
                layout_insert_index += 1

                if total > BATCH_SIZE:
                    QApplication.processEvents()

                i = g_end + 1
                continue

            # Segmento independiente: rendering clasico
            widget = TimelineSegment(
                i,
                self._build_segment_widget_data(segment),
                defer_media_load=defer_previews,
                fal_mode=_fal_mode,
            )
            self._connect_segment_signals(widget)

            self.timeline_layout.insertWidget(layout_insert_index, widget)
            layout_insert_index += 1
            self.segment_widgets.append(widget)
            if defer_previews:
                self._pending_preview_indices.append(i)

            if total > BATCH_SIZE and (i + 1) % BATCH_SIZE == 0:
                QApplication.processEvents()

            i += 1

        # segment_widgets puede quedar desordenado cuando hay grupos (miembros
        # apareados al rebote del wrapper). Reordenar por index para que las
        # consultas self.segment_widgets[idx] sigan funcionando como antes.
        self.segment_widgets.sort(key=lambda w: getattr(w, 'index', 0))

        if defer_previews and self._pending_preview_indices:
            # Cargar previews de forma diferida evita congelar al abrir timelines largos.
            # Intervalo corto (10ms) + presupuesto por tick (ver _process_pending_previews):
            # la UI cede entre lotes pero los previews aparecen ~5.8x mas rapido que antes.
            self._preview_loader_timer.start(10)

        if self.selected_index is not None and 0 <= self.selected_index < len(self.segment_widgets):
            try:
                self.segment_widgets[self.selected_index].set_selected(True)
            except Exception:
                pass

        # Actualizar estado del boton despues de cargar segmentos
        self.update_delete_button_state()

        # Restaurar posición de scroll (diferido para que Qt termine de ajustar el layout)
        if _scroll_pos and hasattr(self, 'timeline_scroll') and self.timeline_scroll:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.timeline_scroll.verticalScrollBar().setValue(_scroll_pos))

    def _connect_segment_signals(self, widget):
        """Conecta las senales estandar de un TimelineSegment al TimelineEditorWidget."""
        widget.clicked.connect(self.on_segment_clicked)
        widget.deleted.connect(self.delete_segment)
        widget.image_deleted.connect(self.delete_segment_image)
        widget.image_removed.connect(self.remove_segment_image)
        widget.image_restored.connect(self.restore_segment_image)
        widget.video_deleted.connect(self.delete_segment_video)
        widget.wikimedia_search_requested.connect(self.open_wikimedia_search)
        widget.openverse_images_search_requested.connect(self.open_openverse_search)
        widget.pexels_video_search_requested.connect(self.open_pexels_video_search)
        widget.wikimedia_video_search_requested.connect(self.open_wikimedia_video_search)
        widget.internet_archive_video_search_requested.connect(self.open_internet_archive_video_search)
        widget.youtube_video_search_requested.connect(self.open_youtube_video_search)
        widget.regenerate_ai_image_requested.connect(self.regenerate_ai_image)
        widget.video_edit_requested.connect(self.open_video_edit)
        widget.local_image_requested.connect(self._open_local_image_dialog_for_segment)
        widget.clipboard_image_requested.connect(self._paste_clipboard_image_to_segment)
        widget.local_image_dropped.connect(self._handle_local_image_dropped)
        widget.manual_image_move_requested.connect(self._move_manual_image_between_segments)
        widget.local_video_requested.connect(self._open_local_video_dialog_for_segment)
        widget.local_video_dropped.connect(self._handle_local_video_dropped)
        widget.regenerate_text_requested.connect(self.regenerate_single_segment_text)
        widget.recraft_prompts_copy_requested.connect(self.copy_recraft_prompts_for_segment)
        widget.video_prompt_copy_requested.connect(self.copy_video_prompt_for_segment)
        widget.generate_fal_image_requested.connect(
            lambda idx: self.regenerate_ai_image(idx, skip_confirmation=True, force_provider='fal')
        )
        widget.animate_fal_video_requested.connect(self.animate_fal_video)

        if hasattr(widget, 'checkbox'):
            widget.checkbox.stateChanged.connect(self.update_delete_button_state)

    # ------------------------------------------------------------------
    # Handlers para la imagen compartida de GroupedSegmentsWidget
    # ------------------------------------------------------------------
    def _on_grouped_image_change_requested(self, indices):
        """Abre el selector y reasigna la nueva imagen a todos los indices."""
        from PyQt6.QtWidgets import QFileDialog
        if not indices:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar nueva imagen compartida",
            "",
            "Imagenes (*.png *.jpg *.jpeg *.bmp *.webp *.avif);;Todos los archivos (*.*)"
        )
        if not file_path:
            return
        self._assign_local_image_to_segments(
            list(indices),
            file_path,
            auto_save_reason="despues de cambiar imagen compartida de grupo",
        )

    def _on_grouped_image_remove_requested(self, indices):
        """Quita la imagen de todos los miembros del grupo."""
        if not indices:
            return
        for idx in indices:
            if 0 <= idx < len(self.segments):
                seg = self.segments[idx]
                seg.pop('image_path', None)
                seg.pop('image_source', None)
                seg.pop('image_deleted', None)
        self._trigger_auto_save("despues de quitar imagen compartida de grupo")
        self.refresh_timeline()

    def _on_grouped_extend_requested(self, indices):
        """Suma el segmento siguiente al grupo, reutilizando la still compartida."""
        valid = sorted({int(i) for i in (indices or []) if isinstance(i, int) and 0 <= i < len(self.segments)})
        if not valid:
            return
        last = valid[-1]
        nxt = last + 1
        if nxt >= len(self.segments):
            return
        first = valid[0]
        image_path = self.segments[first].get("image_path")
        if not image_path:
            return
        next_seg = self.segments[nxt]
        next_img = self._get_groupable_image_path_for_segment(next_seg)
        current_img = self._normalize_groupable_image_path(image_path)
        if next_img and next_img != current_img:
            reply = QMessageBox.question(
                self,
                "Reemplazar imagen",
                (
                    f"El segmento #{nxt + 1} ya tiene otra imagen.\n"
                    "¿Reemplazarla y sumarlo a este grupo?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        next_seg["image_path"] = image_path
        next_seg["image_source"] = self.segments[first].get("image_source") or "local"
        if self.segments[first].get("visual_key"):
            next_seg["visual_key"] = self.segments[first]["visual_key"]
        next_seg.pop("video_path", None)
        next_seg.pop("video_source", None)
        next_seg.pop("image_deleted", None)
        self._trigger_auto_save("despues de extender grupo de imagen compartida")
        self.refresh_timeline()

    def _on_grouped_shrink_requested(self, indices):
        """Quita el último segmento del grupo (deja de usar la still compartida)."""
        valid = sorted({int(i) for i in (indices or []) if isinstance(i, int) and 0 <= i < len(self.segments)})
        if len(valid) < 2:
            return
        last = valid[-1]
        seg = self.segments[last]
        seg.pop("image_path", None)
        seg.pop("image_source", None)
        seg.pop("image_deleted", None)
        self._trigger_auto_save("despues de encoger grupo de imagen compartida")
        self.refresh_timeline()

    def _on_grouped_image_ungroup_requested(self, indices):
        """Mantiene la imagen solo en el primer segmento y la quita del resto."""
        if not indices or len(indices) < 2:
            return
        keep_idx = indices[0]
        for idx in indices[1:]:
            if 0 <= idx < len(self.segments):
                seg = self.segments[idx]
                seg.pop('image_path', None)
                seg.pop('image_source', None)
                seg.pop('image_deleted', None)
        self._trigger_auto_save("despues de desagrupar segmentos con imagen compartida")
        self.refresh_timeline()

    def _on_grouped_image_dropped(self, indices, file_path):
        """Se solto una imagen local sobre la imagen compartida del grupo."""
        if not indices or not file_path:
            return
        self._assign_local_image_to_segments(
            list(indices),
            file_path,
            auto_save_reason="despues de arrastrar imagen compartida al grupo",
        )

    def _on_grouped_strip_watermark_requested(self, indices):
        """Elimina la marca de agua Gemini de la imagen compartida del grupo."""
        if not indices:
            return
        first_idx = next((i for i in indices if 0 <= i < len(self.segments)), None)
        if first_idx is None:
            return
        image_path = self.segments[first_idx].get('image_path')
        if not image_path:
            return
        abs_path = self._resolve_stored_image_abspath(image_path)
        if not abs_path or not os.path.isfile(abs_path):
            return
        try:
            from gemini_watermark_remover import remove_gemini_watermark
            remove_gemini_watermark(abs_path)
            print(f"[TimelineEditor] Watermark Gemini removido del grupo: {os.path.basename(abs_path)}")
            self._refresh_media_widgets(list(indices), {idx: image_path for idx in indices})
        except Exception as e:
            print(f"[TimelineEditor] Error removiendo watermark Gemini del grupo: {e}")

    def _on_grouped_video_dropped(self, indices, file_path):
        """Se soltó un video local sobre la imagen compartida del grupo.

        Si el grupo tiene más de un segmento, el video se divide en clips
        consecutivos (uno por segmento) respetando las duraciones individuales,
        de modo que el video se reproduce de corrido a lo largo del grupo
        en lugar de repetirse en cada segmento.
        """
        if not indices or not file_path:
            return
        video_path = os.path.abspath(file_path)
        if not os.path.exists(video_path):
            return
        valid = sorted({int(i) for i in indices if isinstance(i, int) and 0 <= i < len(self.segments)})
        if not valid:
            return

        if len(valid) == 1:
            idx = valid[0]
            self.segments[idx]['video_path'] = video_path
            self.segments[idx]['image_path'] = video_path
            self.segments[idx]['video_source'] = 'local'
            self.segments[idx]['image_source'] = 'local'
            self.segments[idx].pop('image_deleted', None)
            self._trigger_auto_save("despues de arrastrar video al segmento")
            self._refresh_media_widgets(valid, {idx: None for idx in valid})
            return

        # Múltiples segmentos: dividir el video proporcionalmente a sus duraciones
        durations = []
        for idx in valid:
            seg = self.segments[idx]
            dur = float(seg.get('duration') or seg.get('duration_seconds') or 0)
            durations.append(dur if dur > 0 else 5.0)

        clips = self._split_video_for_group(video_path, valid, durations)

        for i, idx in enumerate(valid):
            clip_path = clips[i] if clips and i < len(clips) else None
            path = clip_path if (clip_path and os.path.exists(clip_path)) else video_path
            self.segments[idx]['video_path'] = path
            self.segments[idx]['image_path'] = path
            self.segments[idx]['video_source'] = 'local'
            self.segments[idx]['image_source'] = 'local'
            self.segments[idx].pop('image_deleted', None)

        self._trigger_auto_save("despues de dividir video en grupo")
        self._refresh_media_widgets(valid, {idx: None for idx in valid})
        label = "dividido en clips" if clips else "asignado completo (sin FFmpeg)"
        print(f"[TimelineEditor] Video {label}: segmentos {[i+1 for i in valid]}")

    def _split_video_for_group(self, video_path: str, segment_indices: list, durations: list):
        """Divide un video en N clips consecutivos usando FFmpeg.

        Si el video es más corto que la duración total de los segmentos, lo
        ralentiza con setpts (+ minterpolate si FFmpeg lo soporta) igual que
        hace el pipeline principal para videos cortos en modo 1:1.
        Devuelve lista de rutas (misma longitud que segment_indices).
        """
        import subprocess as _sp
        from pathlib import Path as _P

        NO_WIN = 0x08000000 if os.name == 'nt' else 0

        # ── Resolver ejecutables ──────────────────────────────────────────────
        try:
            from infra.video_config import VideoConfig
            ffmpeg_dir  = VideoConfig.FFMPEG_BINARY_PATH or ""
            ffprobe_dir = ffmpeg_dir
            ffmpeg_exe  = str(_P(ffmpeg_dir)  / "ffmpeg.exe")  if ffmpeg_dir else "ffmpeg"
            ffprobe_exe = str(_P(ffprobe_dir) / "ffprobe.exe") if ffprobe_dir else "ffprobe"
            if not _P(ffmpeg_exe).exists():
                ffmpeg_exe = "ffmpeg"
            if not _P(ffprobe_exe).exists():
                ffprobe_exe = "ffprobe"
        except Exception:
            ffmpeg_exe  = "ffmpeg"
            ffprobe_exe = "ffprobe"

        # ── Directorio de salida ──────────────────────────────────────────────
        try:
            if self.studio_tab and getattr(self.studio_tab, 'current_project_path', None):
                proj_dir = _P(self.studio_tab.current_project_path).parent
                out_dir  = proj_dir / "project_media"
                out_dir.mkdir(parents=True, exist_ok=True)
            else:
                out_dir = _P(video_path).parent
        except Exception:
            out_dir = _P(video_path).parent

        # ── Sondear duración real del video fuente ────────────────────────────
        def _probe_dur(path):
            try:
                r = _sp.run(
                    [ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path],
                    capture_output=True, text=True, timeout=15, creationflags=NO_WIN
                )
                if r.returncode == 0 and r.stdout.strip():
                    return max(0.0, float(r.stdout.strip().splitlines()[0]))
            except Exception:
                pass
            return 0.0

        def _supports_minterpolate():
            try:
                r = _sp.run([ffmpeg_exe, "-hide_banner", "-filters"],
                            capture_output=True, text=True, timeout=10, creationflags=NO_WIN)
                return r.returncode == 0 and "minterpolate" in r.stdout
            except Exception:
                return False

        # ── Calcular slow_factor ──────────────────────────────────────────────
        total_seg_dur = sum(durations)
        video_dur     = _probe_dur(video_path)
        slow_factor   = 1.0
        if video_dur > 0 and total_seg_dur > video_dur * 1.05:
            slow_factor = total_seg_dur / video_dur
            print(f"   [Split] Video corto ({video_dur:.2f}s) → total segmentos ({total_seg_dur:.2f}s) "
                  f"→ ralentizado ×{slow_factor:.3f}")

        use_minterpolate = slow_factor > 1.05 and _supports_minterpolate()

        # ── Construir atempo para el canal de audio ───────────────────────────
        def _build_atempo(factor):
            """Genera filtros atempo encadenados para el factor dado (rango: 0.5–100)."""
            rate = 1.0 / factor  # ralentizar audio en la misma proporción
            filters = []
            while rate < 0.5:
                filters.append("atempo=0.5")
                rate /= 0.5
            filters.append(f"atempo={rate:.6f}")
            return ",".join(filters)

        ext   = _P(video_path).suffix or '.mp4'
        clips = []
        # Los tiempos se miden en el video ORIGINAL (pre-stretch);
        # cada clip cubre orig_dur segundos del original y se estira a seg_dur.
        orig_start = 0.0

        for i, idx in enumerate(segment_indices):
            seg_dur  = durations[i]
            orig_dur = seg_dur / slow_factor          # cuánto original leer
            filename = self.segments[idx].get('assigned_filename', f'segment_{idx+1:03d}')
            out_path = str(out_dir / f"{filename}_vsplit_{i+1:02d}.mp4")

            if slow_factor <= 1.05:
                # Sin estiramiento: stream copy rápido
                cmd = [
                    ffmpeg_exe, '-y',
                    '-ss', f"{orig_start:.6f}",
                    '-i', video_path,
                    '-t', f"{orig_dur:.6f}",
                    '-c', 'copy', '-avoid_negative_ts', '1',
                    out_path,
                ]
            else:
                # Con estiramiento: re-encode con setpts (+ minterpolate si disponible)
                vf = f"setpts={slow_factor:.6f}*PTS"
                if use_minterpolate:
                    vf += ",minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
                af = _build_atempo(slow_factor)
                cmd = [
                    ffmpeg_exe, '-y',
                    '-ss', f"{orig_start:.6f}",
                    '-i', video_path,
                    '-t', f"{orig_dur:.6f}",
                    '-vf', vf,
                    '-af', af,
                    '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac',
                    '-r', '30',
                    out_path,
                ]

            try:
                result = _sp.run(cmd, capture_output=True, timeout=180, creationflags=NO_WIN)
                if result.returncode == 0 and _P(out_path).exists() and _P(out_path).stat().st_size > 0:
                    clips.append(out_path)
                    mode = f"×{slow_factor:.2f} smooth" if slow_factor > 1.05 else "copy"
                    print(f"   [Split] Clip {i+1}: {orig_start:.2f}s–{orig_start+orig_dur:.2f}s "
                          f"→ {seg_dur:.2f}s [{mode}] → {_P(out_path).name}")
                else:
                    err = result.stderr.decode('utf-8', errors='replace')[-400:]
                    print(f"   [Split] Error clip {i+1}: {err}")
                    clips.append(None)
            except Exception as e:
                print(f"   [Split] Excepción clip {i+1}: {e}")
                clips.append(None)

            orig_start += orig_dur

        return clips

    def _process_pending_previews(self):
        """Carga previews pendientes con presupuesto de tiempo para mantener la UI fluida.

        Antes cargaba 2-4 fijos por tick de 25ms: para 194 segmentos eran ~2.2s solo por
        el ritmo del timer, aunque decodificar un thumbnail cuesta ~1ms. Ahora cargamos
        cuantos quepan en ~12ms por tick (presupuesto adaptativo): si las imagenes son
        rapidas se cargan ~12/tick (timeline listo en ~0.4s); si alguna es lenta, el
        presupuesto corta el lote y la UI no se congela. Medido: ~5.8x mas rapido.
        """
        if not self._pending_preview_indices:
            self._preview_loader_timer.stop()
            return

        import time as _time
        # Presupuesto por tick: <16ms (presupuesto de frame a 60fps) deja la UI fluida.
        deadline = _time.perf_counter() + 0.012
        # Garantiza progreso aunque una sola imagen exceda el presupuesto.
        loaded = 0
        while self._pending_preview_indices and (loaded == 0 or _time.perf_counter() < deadline):
            idx = self._pending_preview_indices.popleft()
            loaded += 1
            if 0 <= idx < len(self.segment_widgets):
                try:
                    self.segment_widgets[idx].update_image_preview()
                except Exception:
                    pass

        if not self._pending_preview_indices:
            self._preview_loader_timer.stop()
    
    def on_segment_clicked(self, index):
        """Maneja el click en un segmento"""
        print(f"[TimelineEditor] on_segment_clicked llamado con Ã­ndice {index}")
        
        # Validar Ã­ndice
        if index < 0 or index >= len(self.segments):
            print(f"âš ï¸ Ãndice invÃ¡lido: {index} (total segmentos: {len(self.segments)})")
            return

        # Guardar cambios pendientes del segmento actualmente seleccionado
        # antes de cambiar a otro. Evita perder ediciones si el debounce
        # de auto-guardado aún no se ejecutó.
        try:
            if (
                self.selected_index is not None and
                self.selected_index != index and
                hasattr(self, 'segment_editor') and
                self.segment_editor and
                getattr(self.segment_editor, 'current_segment', None)
            ):
                self.segment_editor.save_changes()
        except Exception as save_error:
            print(f"️ Error guardando segmento antes de cambiar selección: {save_error}")
        
        # Deseleccionar anterior
        if self.selected_index is not None and self.selected_index < len(self.segment_widgets):
            self.segment_widgets[self.selected_index].set_selected(False)
        
        # Seleccionar nuevo
        self.selected_index = index
        if index < len(self.segment_widgets):
            self.segment_widgets[index].set_selected(True)
            self.segment_widgets[index].segment_data = self._build_segment_widget_data(self.segments[index])
            # Diferir preview de media al siguiente ciclo para no bloquear el click.
            QTimer.singleShot(0, lambda idx=index: self._refresh_selected_segment_preview(idx))
            
            # Actualizar vista previa de subtÃ­tulos
            segment_text = self.segments[index].get('text', '')
            self.update_preview(segment_text)
        
        # Cargar en editor
        if hasattr(self, 'segment_editor') and self.segment_editor:
            print(f"[TimelineEditor] Cargando segmento {index} en editor...")
            
            # Solo aplicar ajustes de visibilidad/layout cuando realmente hace falta.
            needs_editor_layout_fix = not self.segment_editor.isVisible()
            if hasattr(self, 'main_splitter') and self.main_splitter:
                current_sizes = self.main_splitter.sizes()
                total_width = sum(current_sizes) if current_sizes else 1000
                if len(current_sizes) >= 2 and current_sizes[1] < 350:
                    editor_width = max(350, int(total_width * 0.4))
                    timeline_width = total_width - editor_width
                    self.main_splitter.setSizes([timeline_width, editor_width])
                    needs_editor_layout_fix = True
                    print(f"[TimelineEditor] Splitter ajustado: timeline={timeline_width}px, editor={editor_width}px")
                self.main_splitter.setChildrenCollapsible(False)

            if needs_editor_layout_fix:
                self.segment_editor.setVisible(True)
                self.segment_editor.show()
                if hasattr(self, 'main_scroll_area') and self.main_scroll_area:
                    self.main_scroll_area.ensureWidgetVisible(self.segment_editor)
            
            # Ahora cargar el segmento
            self.segment_editor.load_segment(self.segments[index])
            print(f"[TimelineEditor] Segmento cargado y editor habilitado")
        else:
            print(f"âš ï¸ segment_editor no existe o no estÃ¡ disponible")

    def _refresh_selected_segment_preview(self, index: int):
        """Actualiza preview del segmento seleccionado sin bloquear el handler de click."""
        if index < 0 or index >= len(self.segment_widgets):
            return
        if self.selected_index != index:
            return
        try:
            self.segment_widgets[index].update_image_preview()
        except Exception as e:
            print(f"[TimelineEditor] âš ï¸ Error actualizando preview diferido: {e}")
    
    def _get_studio_tab(self):
        """Obtiene referencia al AutoVideoStudioTab asociado."""
        if self.studio_tab:
            return self.studio_tab

        parent = self.parent()
        while parent:
            if hasattr(parent, 'studio_tab') and parent.studio_tab:
                return parent.studio_tab
            if hasattr(parent, 'last_storyboard_data'):
                return parent
            parent = parent.parent() if hasattr(parent, 'parent') else None

        return None

    def _is_fal_provider(self) -> bool:
        """True si el proveedor de imágenes configurado actualmente es FAL.AI."""
        return self._get_current_image_provider_key() in {'fal', 'fal_ai', 'fal.ai'}

    def _get_current_image_provider_key(self) -> str:
        """Obtiene el proveedor de imagenes actualmente configurado en Studio."""
        studio_tab = self._get_studio_tab()
        provider_text = ""
        try:
            if studio_tab and hasattr(studio_tab, "image_provider_combo") and studio_tab.image_provider_combo:
                provider_text = studio_tab.image_provider_combo.currentText().strip()
        except Exception:
            provider_text = ""

        provider_map = {
            "Recraft AI": "recraft",
            "Fal.ai (FLUX.1 schnell)": "fal",
            "Fal.ai (FLUX.1 schnell) âš¡": "fal",
            "Google AI (Gemini API)": "google_ai",
            "Imagen 4 Fast (Vertex AI)": "google_ai",
            "Leonardo AI": "recraft",
            "Leonardo AI (Fallback)": "recraft",
            "Manual (Gratuito)": "manual",
        }
        return provider_map.get(provider_text, "recraft")

    def _get_current_visual_style(self) -> str:
        """Obtiene el estilo visual actualmente seleccionado."""
        studio_tab = self._get_studio_tab()
        try:
            if studio_tab and hasattr(studio_tab, "get_selected_visual_style"):
                style = studio_tab.get_selected_visual_style()
                return style or "Realistic Image"
            if studio_tab and hasattr(studio_tab, "style_combo") and studio_tab.style_combo:
                style = studio_tab.style_combo.currentText().strip()
                if style:
                    return style
        except Exception:
            pass
        return "Realistic Image"

    def _validate_image_provider_for_batch_generation(self, provider_key: str):
        """Valida si el proveedor actual esta disponible antes de lanzar el batch."""
        provider = str(provider_key or "").strip().lower()
        try:
            if provider == "fal":
                from fal_ai_client import FalAiClient
                client = FalAiClient()
                if getattr(client, "client_available", False):
                    return True, ""
                return False, "Configura FAL_KEY o FAL_API_KEY en tu archivo .env para usar Fal.ai."
            if provider == "google_ai":
                from google_ai_image_client import GoogleAiImageClient
                client = GoogleAiImageClient()
                if getattr(client, "client_available", False):
                    return True, ""
                return False, "Configura GEMINI_API_KEY/GOOGLE_API_KEY en tu archivo .env para usar Google AI."

            from recraft_client import RecraftClient
            client = RecraftClient()
            if getattr(client, "api_key", None):
                return True, ""
            return False, "Configura RECRAFT_API_KEY en tu archivo .env para usar Recraft AI."
        except Exception as e:
            return False, str(e)

    def _build_segment_narrative_context(self, segment_index: int) -> dict:
        """Construye una ventana narrativa local para un segmento del timeline."""
        if segment_index < 0 or segment_index >= len(self.segments):
            return {}

        def _segment_text(seg):
            return str(seg.get("text") or seg.get("narration_text") or seg.get("narration") or "").strip()

        def _join_window(from_idx, to_idx, max_chars):
            if from_idx > to_idx:
                return ""
            text = " ".join(
                _segment_text(self.segments[idx])
                for idx in range(from_idx, to_idx + 1)
                if _segment_text(self.segments[idx])
            ).strip()
            if len(text) <= max_chars:
                return text
            return text[:max_chars].rstrip() + "..."

        total = len(self.segments)
        progress = (segment_index + 1) / max(1, total)
        if progress <= 0.18:
            narrative_role = "opening setup or hook"
        elif progress <= 0.45:
            narrative_role = "early development"
        elif progress <= 0.72:
            narrative_role = "core explanation or escalation"
        elif progress <= 0.9:
            narrative_role = "late development or payoff"
        else:
            narrative_role = "closing beat or conclusion"

        return {
            "segment_range": f"segment {segment_index + 1} of {total}",
            "narrative_role": narrative_role,
            "previous_context": _join_window(max(0, segment_index - 2), segment_index - 1, 280),
            "current_focus": _join_window(segment_index, segment_index, 420),
            "next_context": _join_window(segment_index + 1, min(total - 1, segment_index + 2), 280),
            "continuity_note": "Use adjacent context only for continuity. The image must depict the current narration beat.",
        }

    def _safe_float(self, value, default=0.0) -> float:
        """Convierte un valor a float de forma segura."""
        try:
            if value is None:
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _extract_narration_text(self, segment: dict) -> str:
        """Obtiene el texto narrativo canónico de un segmento."""
        if not isinstance(segment, dict):
            return ""

        for key in ("text", "narration_text", "narration"):
            raw = segment.get(key, "")
            if raw is None:
                continue
            value = str(raw).strip()
            if value:
                return value
        return ""

    def _normalize_segment_narrative_fields(self, segment: dict, segment_index: int = None) -> dict:
        """
        Normaliza los campos narrativos y de tiempo para mantener
        consistencia entre timeline, audio y subtítulos.
        """
        normalized = segment.copy() if isinstance(segment, dict) else {}

        text = self._extract_narration_text(normalized)
        normalized['text'] = text
        normalized['narration_text'] = text

        start = self._safe_float(
            normalized.get('start', normalized.get('start_time', 0.0)),
            0.0
        )

        raw_end = normalized.get('end', normalized.get('end_time'))
        if raw_end is None:
            duration = self._safe_float(normalized.get('duration', 5.0), 5.0)
            end = start + max(duration, 0.0)
        else:
            end = self._safe_float(raw_end, start)

        if end < start:
            end = start

        duration = max(end - start, 0.0)

        normalized['start'] = start
        normalized['end'] = end
        normalized['start_time'] = start
        normalized['end_time'] = end
        normalized['timestamp_start'] = start
        normalized['timestamp_end'] = end
        normalized['duration'] = duration

        if segment_index is not None:
            normalized['segment_id'] = segment_index + 1
            if not normalized.get('assigned_filename'):
                normalized['assigned_filename'] = f"segment_{segment_index + 1:03d}"

        return normalized

    def _build_script_from_segments(self, segments) -> str:
        """Construye el script completo concatenando los textos de segmentos."""
        parts = []
        for segment in segments or []:
            text = self._extract_narration_text(segment)
            if text:
                parts.append(text)
        return " ".join(parts).strip()

    def _compute_narrative_signature(self, segments) -> str:
        """Firma estable basada solo en texto y tiempos narrativos."""
        payload = []
        for index, segment in enumerate(segments or []):
            normalized = self._normalize_segment_narrative_fields(segment, index)
            payload.append({
                "index": index,
                "start": round(normalized.get('start', 0.0), 3),
                "end": round(normalized.get('end', 0.0), 3),
                "text": normalized.get('text', '')
            })

        signature_src = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha1(signature_src.encode('utf-8')).hexdigest()

    def _did_narrative_change(self, original_segment: dict, updated_segment: dict) -> bool:
        """Detecta si cambió narración (texto o timing)."""
        before = self._normalize_segment_narrative_fields(original_segment)
        after = self._normalize_segment_narrative_fields(updated_segment)

        if before.get('text', '').strip() != after.get('text', '').strip():
            return True

        if abs(before.get('start', 0.0) - after.get('start', 0.0)) > 0.01:
            return True

        if abs(before.get('end', 0.0) - after.get('end', 0.0)) > 0.01:
            return True

        return False

    def _did_segment_media_change(self, original_segment: dict, updated_segment: dict) -> bool:
        """Detecta cambios de media (imagen/video) para evitar recargas innecesarias."""
        media_keys = ('image_path', 'video_path', 'image_source', 'video_source', 'image_deleted')
        for key in media_keys:
            before_val = original_segment.get(key)
            after_val = updated_segment.get(key)
            if before_val != after_val:
                return True
        return False

    def on_segment_saved(self, updated_data):
        """Callback cuando se guarda un segmento editado"""
        if self._on_segment_saved_in_progress:
            return

        # Resolver índice destino del guardado de forma estable.
        # No depender solo de selected_index, porque puede cambiar mientras un
        # auto-guardado tardío termina de ejecutarse.
        target_index = None
        if isinstance(updated_data, dict):
            seg_id = updated_data.get('segment_id')
            try:
                seg_id_int = int(seg_id)
                if 1 <= seg_id_int <= len(self.segments):
                    target_index = seg_id_int - 1
            except (TypeError, ValueError):
                pass

            if target_index is None:
                assigned_filename = str(updated_data.get('assigned_filename', '') or '').strip()
                if assigned_filename:
                    for i, seg in enumerate(self.segments):
                        if str(seg.get('assigned_filename', '') or '').strip() == assigned_filename:
                            target_index = i
                            break

        if target_index is None:
            target_index = self.selected_index

        if target_index is None or target_index < 0 or target_index >= len(self.segments):
            return

        self._on_segment_saved_in_progress = True
        try:
            # Preservar campos importantes que no se editan en el editor
            original_segment = self.segments[target_index].copy()

            # Preservar campos de video/imagen si existen
            if 'video_path' in original_segment:
                updated_data['video_path'] = original_segment['video_path']
            if 'image_path' in original_segment:
                updated_data['image_path'] = original_segment['image_path']
            if 'video_source' in original_segment:
                updated_data['video_source'] = original_segment['video_source']
            if 'image_source' in original_segment:
                updated_data['image_source'] = original_segment['image_source']
            if 'image_deleted' in original_segment:
                updated_data['image_deleted'] = original_segment['image_deleted']

            # Detectar si cambió la narrativa (texto/tiempos)
            narrative_changed = self._did_narrative_change(original_segment, updated_data)
            media_changed = self._did_segment_media_change(original_segment, updated_data)

            # Normalizar campos narrativos/timestamps del segmento editado
            updated_data = self._normalize_segment_narrative_fields(
                updated_data,
                target_index
            )

            # Actualizar el segmento
            self.segments[target_index] = updated_data

            # Actualizar widget con copia para asegurar que se actualice correctamente
            if target_index < len(self.segment_widgets):
                self.segment_widgets[target_index].segment_data = self._build_segment_widget_data(updated_data)
                self.segment_widgets[target_index].update_display(refresh_media=media_changed)

            # IMPORTANTE: Sincronizar con el studio_tab para que los cambios se reflejen en el ensamblaje final
            self._sync_changes_to_storyboard(
                reason="después de editar segmento",
                narrative_changed=narrative_changed,
                target_index=target_index,
                target_segment=updated_data
            )

            # Activar auto-guardado automático
            self._trigger_auto_save("después de editar segmento")
        finally:
            self._on_segment_saved_in_progress = False
    
    def _sync_changes_to_storyboard(self, reason="", narrative_changed=None, target_index=None, target_segment=None):
        """Sincroniza los cambios de los segmentos con el storyboard data del studio_tab"""
        if self._sync_storyboard_in_progress:
            return
        self._sync_storyboard_in_progress = True
        try:
            studio_tab = self._get_studio_tab()
            
            if studio_tab and hasattr(studio_tab, 'last_storyboard_data') and studio_tab.last_storyboard_data:
                storyboard_data = studio_tab.last_storyboard_data

                # Fast path: cuando no cambia narrativa, sincronizar solo el segmento editado.
                if (
                    narrative_changed is False and
                    target_index is not None and
                    isinstance(target_segment, dict)
                ):
                    existing_segments = storyboard_data.get('segments')
                    if isinstance(existing_segments, list) and 0 <= target_index < len(existing_segments):
                        normalized_target = self._normalize_segment_narrative_fields(target_segment, target_index)
                        self.segments[target_index] = normalized_target
                        existing_segments[target_index] = normalized_target.copy()
                        print(f"[TimelineEditor]  Sincronizado segmento #{target_index + 1} (fast path)")
                        if hasattr(self, 'segments_modified'):
                            self.segments_modified.emit([seg.copy() for seg in self.segments])
                        return

                # Normalizar todos los segmentos para mantener consistencia narrativa.
                normalized_segments = [
                    self._normalize_segment_narrative_fields(seg, i)
                    for i, seg in enumerate(self.segments)
                ]
                self.segments = normalized_segments
                previous_signature = storyboard_data.get('segments_narrative_signature')
                current_signature = self._compute_narrative_signature(normalized_segments)

                # Actualizar los segmentos en el storyboard data
                storyboard_data['segments'] = [seg.copy() for seg in normalized_segments]
                storyboard_data['segments_narrative_signature'] = current_signature

                # Mantener script sincronizado desde los segmentos editados.
                script = self._build_script_from_segments(normalized_segments)
                if script:
                    storyboard_data['script'] = script

                if narrative_changed is None:
                    narrative_changed = bool(previous_signature and previous_signature != current_signature)

                if narrative_changed:
                    timestamp = datetime.now(timezone.utc).isoformat()
                    storyboard_data['audio_needs_regeneration'] = True
                    storyboard_data['subtitles_need_regeneration'] = True
                    storyboard_data['audio_sync_status'] = 'pending'
                    storyboard_data['audio_sync_reason'] = reason or "segment_narrative_changed"
                    storyboard_data['audio_sync_requested_at'] = timestamp
                    print("[TimelineEditor]  Cambios narrativos detectados: audio/subtítulos marcados para resincronizar")

                print(f"[TimelineEditor]  Sincronizados {len(self.segments)} segmentos con storyboard_data")
                
                # Emitir señal para notificar del cambio
                if hasattr(self, 'segments_modified'):
                    self.segments_modified.emit([seg.copy() for seg in normalized_segments])
            else:
                print(f"[TimelineEditor] ️ No se encontró studio_tab.last_storyboard_data para sincronizar")
        except Exception as e:
            print(f"[TimelineEditor]  Error sincronizando cambios: {e}")
        finally:
            self._sync_storyboard_in_progress = False
    
    def add_segment(self):
        """Añade un nuevo segmento al final"""
        # Calcular tiempo de inicio
        if self.segments:
            last_end = self.segments[-1].get('end', 0)
            new_start = last_end
            new_end = new_start + 5  # 5 segundos por defecto
        else:
            new_start = 0
            new_end = 5
        
        new_segment = {
            'start': new_start,
            'end': new_end,
            'text': 'Nuevo segmento',
            'visual_prompt': 'a cinematic scene',
            'sfx_tag': 'none',
            'overlay_tag': 'none',
            'assigned_filename': f'segment_{len(self.segments) + 1:03d}'
        }

        new_segment = self._normalize_segment_narrative_fields(new_segment, len(self.segments))
        self.segments.append(new_segment)
        self.refresh_timeline()

        # Sincronizar inmediatamente para marcar audio/subtitulos pendientes.
        self._sync_changes_to_storyboard(
            reason="despues de añadir segmento",
            narrative_changed=True
        )
        
        # Activar auto-guardado automÃ¡tico
        self._trigger_auto_save("despuÃ©s de aÃ±adir segmento")
    
    def delete_segment(self, index):
        """Elimina un segmento"""
        reply = QMessageBox.question(
            self,
            "Confirmar EliminaciÃ³n",
            f"Â¿Eliminar el segmento #{index + 1}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            del self.segments[index]
            self.selected_index = None
            self.segment_editor.clear()
            self.refresh_timeline()

            # Sincronizar inmediatamente para marcar audio/subtitulos pendientes.
            self._sync_changes_to_storyboard(
                reason="despues de eliminar segmento",
                narrative_changed=True
            )
            
            # Activar auto-guardado automÃ¡tico
            self._trigger_auto_save("despuÃ©s de eliminar segmento")

    def _extract_text_replacement_pairs(self, original_text: str, corrected_text: str):
        """
        Extrae reemplazos frase/palabra entre texto original y corregido.
        Se usa para previsualizacion antes de confirmar.
        """
        original_words = (original_text or "").split()
        corrected_words = (corrected_text or "").split()

        matcher = difflib.SequenceMatcher(None, original_words, corrected_words)
        replacements = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                continue

            old_fragment = " ".join(original_words[i1:i2]).strip()
            new_fragment = " ".join(corrected_words[j1:j2]).strip()

            if old_fragment or new_fragment:
                replacements.append((old_fragment, new_fragment))

        if not replacements and (original_text or "") != (corrected_text or ""):
            replacements.append((original_text or "", corrected_text or ""))

        return replacements

    def _collect_text_correction_changes(self, segments, corrector):
        """Aplica correcciones y devuelve (segmentos_corregidos, cambios_detallados)."""
        corrected_segments = []
        changes = []

        for index, segment in enumerate(segments or []):
            normalized = self._normalize_segment_narrative_fields(segment, index)
            original_text = self._extract_narration_text(normalized)
            corrected_text = corrector.correct_text(original_text) if original_text else original_text

            updated_segment = normalized.copy()
            if corrected_text != original_text:
                updated_segment['text'] = corrected_text
                updated_segment['narration_text'] = corrected_text
                if 'narration' in updated_segment:
                    updated_segment['narration'] = corrected_text
                replacements = self._extract_text_replacement_pairs(original_text, corrected_text)
                changes.append({
                    'index': index,
                    'original_text': original_text,
                    'corrected_text': corrected_text,
                    'replacements': replacements
                })

            corrected_segments.append(self._normalize_segment_narrative_fields(updated_segment, index))

        return corrected_segments, changes

    def _show_text_corrections_confirmation_dialog(self, changes) -> bool:
        """Muestra reemplazos detectados y solicita confirmacion para aplicar + regenerar."""
        preview_lines = []
        total_replacements = 0

        for change in changes:
            segment_number = int(change.get('index', 0)) + 1
            replacements = change.get('replacements', []) or []
            for old_fragment, new_fragment in replacements:
                old_display = old_fragment if old_fragment else "[vacio]"
                new_display = new_fragment if new_fragment else "[eliminado]"
                preview_lines.append(
                    f"Segmento #{segment_number}: \"{old_display}\" -> \"{new_display}\""
                )
                total_replacements += 1

        if not preview_lines:
            for change in changes:
                segment_number = int(change.get('index', 0)) + 1
                preview_lines.append(
                    f"Segmento #{segment_number}: "
                    f"\"{change.get('original_text', '')}\" -> \"{change.get('corrected_text', '')}\""
                )
            total_replacements = len(preview_lines)

        max_lines = 120
        if len(preview_lines) > max_lines:
            hidden_lines = len(preview_lines) - max_lines
            preview_lines = preview_lines[:max_lines]
            preview_lines.append(f"... y {hidden_lines} reemplazos adicionales.")

        dialog = QDialog(self)
        dialog.setWindowTitle("Revisar correcciones detectadas")
        dialog.setModal(True)
        dialog.resize(920, 620)

        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"Se detectaron {total_replacements} reemplazos en {len(changes)} segmentos.\n"
            "Revisa las frases/palabras antes de confirmar:"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        preview_box = QTextEdit()
        preview_box.setReadOnly(True)
        preview_box.setPlainText("\n".join(preview_lines))
        layout.addWidget(preview_box, 1)

        actions = QHBoxLayout()
        actions.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(dialog.reject)
        actions.addWidget(cancel_btn)

        confirm_btn = QPushButton("Aplicar y regenerar")
        confirm_btn.clicked.connect(dialog.accept)
        actions.addWidget(confirm_btn)

        layout.addLayout(actions)

        return dialog.exec() == QDialog.DialogCode.Accepted

    def correct_texts_and_regenerate(self):
        """Corrige texto de todos los segmentos y dispara regeneracion completa."""
        if not self.segments:
            QMessageBox.warning(
                self,
                "Sin Segmentos",
                "No hay segmentos para corregir."
            )
            return

        if not TEXT_CORRECTION_AVAILABLE or TextCorrectionEngine is None:
            QMessageBox.warning(
                self,
                "Motor No Disponible",
                "No se pudo cargar text_correction_engine.py para aplicar correcciones."
            )
            return

        try:
            if hasattr(self, 'segment_editor') and self.segment_editor:
                if getattr(self.segment_editor, 'current_segment', None):
                    committed = self.commit_active_segment_edits()
                    if not committed:
                        self.segment_editor.save_changes()
        except Exception:
            pass

        try:
            corrector = TextCorrectionEngine()
            corrected_segments, changes = self._collect_text_correction_changes(self.segments, corrector)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error de Correccion",
                f"No se pudieron aplicar correcciones automaticas:\n{str(e)}"
            )
            return

        if not changes:
            regenerate_reply = QMessageBox.question(
                self,
                "Sin Cambios Detectados",
                "No se detectaron correcciones automaticas.\n\n"
                "Deseas regenerar narracion y subtitulos de todas formas?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if regenerate_reply == QMessageBox.StandardButton.Yes:
                self.regenerate_full_script_sync()
            return

        if not self._show_text_corrections_confirmation_dialog(changes):
            return

        if hasattr(self, 'btn_correct_and_regenerate') and self.btn_correct_and_regenerate:
            self.btn_correct_and_regenerate.setEnabled(False)

        try:
            # Correccion de textos: la media no cambia, asi que actualizamos los
            # widgets en sitio en vez de reconstruir todo el timeline (evita el
            # congelamiento del rebuild total). Cae a refresh_timeline si por algun
            # motivo la estructura/agrupacion cambiara.
            self._apply_segments_update(corrected_segments, refresh_media=False)

            if (
                self.selected_index is not None and
                0 <= self.selected_index < len(self.segments) and
                hasattr(self, 'segment_editor') and self.segment_editor
            ):
                self.segment_editor.load_segment(self.segments[self.selected_index])

            self._sync_changes_to_storyboard(
                reason="despues de correccion automatica de textos",
                narrative_changed=True
            )
            self._trigger_auto_save("despues de correccion automatica de textos")

            self.regenerate_full_script_sync()
        finally:
            if hasattr(self, 'btn_correct_and_regenerate') and self.btn_correct_and_regenerate:
                self.btn_correct_and_regenerate.setEnabled(TEXT_CORRECTION_AVAILABLE)

    def _detect_script_language(self, script_text: str) -> str:
        """Detecta idioma probable (en/es) usando heuristica ligera."""
        sample = f" {str(script_text or '').lower()} "
        if not sample.strip():
            return "en"

        spanish_markers = (
            " el ", " la ", " los ", " las ", " una ", " que ", " para ",
            " con ", " por ", " del ", " en ", " y ", " de ",
            "cion", "iones", "mente", "á", "é", "í", "ó", "ú", "ñ"
        )
        english_markers = (
            " the ", " and ", " with ", " from ", " that ", " this ",
            " were ", " was ", " into ", " of ", " to ", " in "
        )

        spanish_score = sum(sample.count(token) for token in spanish_markers)
        english_score = sum(sample.count(token) for token in english_markers)
        return "es" if spanish_score > english_score else "en"

    def _clean_regenerated_segment_text(self, raw_text) -> str:
        """Limpia respuesta del LLM para dejar solo el texto narrativo final."""
        text = str(raw_text or "").strip()
        if not text:
            return ""

        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(
            r"^\s*(segmento corregido|segmento regenerado|corrected segment|final segment|resultado)\s*:\s*",
            "",
            text,
            flags=re.IGNORECASE
        ).strip()

        lines = [line.strip(" -*\t") for line in text.replace("\r", "\n").split("\n") if line.strip()]
        if len(lines) > 1:
            text = " ".join(lines)
        elif lines:
            text = lines[0]

        text = text.strip().strip('"').strip("'").strip()
        text = re.sub(r"\s{2,}", " ", text)
        return text

    def _get_segment_regen_ai_client(self):
        """Obtiene cliente de IA para regenerar texto de segmento."""
        if self._segment_regen_ai_client and hasattr(self._segment_regen_ai_client, "_generate"):
            return self._segment_regen_ai_client

        studio_tab = self._get_studio_tab()
        candidate_client = None

        try:
            if studio_tab and hasattr(studio_tab, 'generator'):
                candidate_client = getattr(studio_tab.generator, 'gemini_client', None)
        except Exception:
            candidate_client = None

        if candidate_client and hasattr(candidate_client, "_generate"):
            self._segment_regen_ai_client = candidate_client
            return self._segment_regen_ai_client

        try:
            from gemini_ai_client import GeminiAiClient
            fallback_client = GeminiAiClient()
            if fallback_client and hasattr(fallback_client, "_generate"):
                self._segment_regen_ai_client = fallback_client
                return self._segment_regen_ai_client
        except Exception:
            pass

        return None

    def _build_segment_regeneration_prompt(self, index: int, segments, full_script: str, target_text: str, language: str) -> str:
        """Construye prompt para reescribir un segmento manteniendo contexto completo."""
        prev_text = self._extract_narration_text(segments[index - 1]) if index > 0 else ""
        next_text = self._extract_narration_text(segments[index + 1]) if (index + 1) < len(segments) else ""
        words_count = max(3, len(str(target_text or "").split()))
        min_words = max(3, int(words_count * 0.65))
        max_words = max(min_words + 3, int(words_count * 1.35))
        language_name = "Spanish" if language == "es" else "English"

        return f"""
Role: Senior narration editor.
Task: Rewrite ONLY one target segment to fix spelling/grammar/wording issues while preserving meaning and continuity.

Hard constraints:
- Return ONLY the corrected target segment text (no explanations, no bullets, no quotes).
- Keep language strictly in {language_name}.
- Keep narrative style and factual meaning aligned with the complete script.
- Do not add new facts or remove key facts.
- Keep length similar to the original target segment ({min_words}-{max_words} words).

Complete script context:
{full_script}

Previous segment:
{prev_text if prev_text else "[none]"}

Target segment #{index + 1} (rewrite this one):
{target_text}

Next segment:
{next_text if next_text else "[none]"}
"""

    def regenerate_single_segment_text(self, index):
        """Regenera/corrige un segmento puntual usando contexto completo del guion."""
        if index is None or index < 0 or index >= len(self.segments):
            QMessageBox.warning(self, "Segmento invalido", "No se pudo identificar el segmento a regenerar.")
            return

        try:
            if hasattr(self, 'segment_editor') and self.segment_editor:
                if getattr(self.segment_editor, 'current_segment', None):
                    committed = self.commit_active_segment_edits()
                    if not committed:
                        self.segment_editor.save_changes()
        except Exception:
            pass

        normalized_segments = [
            self._normalize_segment_narrative_fields(seg, i)
            for i, seg in enumerate(self.segments)
        ]
        self.segments = normalized_segments

        original_segment = normalized_segments[index].copy()
        original_text = self._extract_narration_text(original_segment)
        if not original_text:
            QMessageBox.warning(
                self,
                "Sin texto",
                f"El segmento #{index + 1} no tiene texto para regenerar."
            )
            return

        full_script = self._build_script_from_segments(normalized_segments)
        if not full_script:
            full_script = original_text

        action_button = None
        if index < len(self.segment_widgets):
            action_button = getattr(self.segment_widgets[index], 'btn_regenerate_text', None)
            if action_button:
                action_button.setEnabled(False)

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            language = self._detect_script_language(full_script)
            ai_client = self._get_segment_regen_ai_client()
            regenerated_text = ""
            regen_error = ""

            if ai_client and hasattr(ai_client, "_generate"):
                prompt = self._build_segment_regeneration_prompt(
                    index=index,
                    segments=normalized_segments,
                    full_script=full_script,
                    target_text=original_text,
                    language=language
                )
                llm_response = ai_client._generate(prompt, max_tokens=420)
                if llm_response and not str(llm_response).startswith("ERROR"):
                    regenerated_text = self._clean_regenerated_segment_text(llm_response)
                else:
                    regen_error = str(llm_response or "respuesta vacia del modelo")
            else:
                regen_error = "no hay cliente de IA disponible"

            used_fallback = False
            if (not regenerated_text or regenerated_text == original_text) and TEXT_CORRECTION_AVAILABLE and TextCorrectionEngine:
                try:
                    fallback_text = TextCorrectionEngine().correct_text(original_text)
                    fallback_text = self._clean_regenerated_segment_text(fallback_text)
                    if fallback_text and fallback_text != original_text:
                        regenerated_text = fallback_text
                        used_fallback = True
                except Exception:
                    pass

            if not regenerated_text or regenerated_text == original_text:
                details = f"No se detectaron cambios utiles para el segmento #{index + 1}."
                if regen_error:
                    details += f"\n\nDetalle tecnico: {regen_error[:200]}"
                QMessageBox.information(self, "Sin cambios", details)
                return

            updated_segment = original_segment.copy()
            updated_segment['text'] = regenerated_text
            updated_segment['narration_text'] = regenerated_text
            if 'narration' in updated_segment:
                updated_segment['narration'] = regenerated_text
            updated_segment = self._normalize_segment_narrative_fields(updated_segment, index)

            self.segments[index] = updated_segment

            if index < len(self.segment_widgets):
                self.segment_widgets[index].segment_data = self._build_segment_widget_data(updated_segment)
                self.segment_widgets[index].update_display(refresh_media=False)

            if self.selected_index == index and hasattr(self, 'segment_editor') and self.segment_editor:
                self.segment_editor.load_segment(updated_segment)

            self._sync_changes_to_storyboard(
                reason=f"despues de regenerar segmento #{index + 1}",
                narrative_changed=True
            )
            self._trigger_auto_save(f"despues de regenerar segmento #{index + 1}")

            success_msg = (
                f"Segmento #{index + 1} actualizado.\n\n"
                "Cuando termines de corregir otros segmentos, usa 'Regenerar guion' para rearmar narracion y subtitulos."
            )
            if used_fallback:
                success_msg += "\n\nNota: Se aplico correccion local (fallback) por falta de respuesta util de IA."
            QMessageBox.information(self, "Segmento regenerado", success_msg)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo regenerar el segmento #{index + 1}:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
        finally:
            QApplication.restoreOverrideCursor()
            if action_button:
                action_button.setEnabled(True)

    def regenerate_full_script_sync(self):
        """
        Reconstruye el guion completo desde segmentos editados y
        fuerza resincronizaciÃ³n de narraciÃ³n/subtÃ­tulos.
        """
        if not self.segments:
            QMessageBox.warning(
                self,
                "Sin Segmentos",
                "No hay segmentos para regenerar el guion."
            )
            return

        # Guardar cambios pendientes del panel derecho antes de regenerar.
        try:
            if hasattr(self, 'segment_editor') and self.segment_editor and self.segment_editor.current_segment:
                self.segment_editor.save_changes()
        except Exception:
            pass

        studio_tab = self._get_studio_tab()
        if not studio_tab:
            QMessageBox.warning(
                self,
                "Studio No Disponible",
                "No se encontrÃ³ la pestaÃ±a Studio para sincronizar el guion."
            )
            return

        if not hasattr(studio_tab, 'last_storyboard_data') or studio_tab.last_storyboard_data is None:
            studio_tab.last_storyboard_data = {}

        storyboard_data = studio_tab.last_storyboard_data
        normalized_segments = [
            self._normalize_segment_narrative_fields(seg, i)
            for i, seg in enumerate(self.segments)
        ]
        script = self._build_script_from_segments(normalized_segments)

        if not script:
            QMessageBox.warning(
                self,
                "Sin Texto Narrativo",
                "No hay texto en los segmentos para regenerar el guion."
            )
            return

        self.btn_regenerate_script.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        try:
            # Sincronizar segmentos/script en memoria.
            signature = self._compute_narrative_signature(normalized_segments)
            self.segments = normalized_segments
            storyboard_data['segments'] = [seg.copy() for seg in normalized_segments]
            storyboard_data['script'] = script
            storyboard_data['segments_narrative_signature'] = signature
            storyboard_data['audio_needs_regeneration'] = True
            storyboard_data['subtitles_need_regeneration'] = True
            storyboard_data['audio_sync_status'] = 'pending'
            storyboard_data['audio_sync_reason'] = 'manual_full_script_regeneration'
            storyboard_data['audio_sync_requested_at'] = datetime.now(timezone.utc).isoformat()

            selected_voice = (
                studio_tab.voice_combo.currentText()
                if hasattr(studio_tab, 'voice_combo') else "Fallback Voice"
            )
            voice_id = None
            if hasattr(studio_tab, 'elevenlabs_voices') and hasattr(studio_tab, 'voice_combo'):
                voice_id = studio_tab.elevenlabs_voices.get(selected_voice, {}).get('id')

            video_handlers = getattr(studio_tab, 'video_assembly_handlers', None)
            if video_handlers is None:
                QMessageBox.critical(
                    self,
                    "Error de SincronizaciÃ³n",
                    "No se encontrÃ³ el manejador de ensamblaje para regenerar audio/subtÃ­tulos."
                )
                return

            regen_ok = video_handlers.regenerate_storyboard_audio_sync(
                storyboard_data=storyboard_data,
                voice_id=voice_id,
                selected_voice=selected_voice
            )

            if not regen_ok:
                QMessageBox.critical(
                    self,
                    "RegeneraciÃ³n Fallida",
                    "No se pudo regenerar la narraciÃ³n del guion completo.\n"
                    "Revisa voz/conectividad e intÃ©ntalo de nuevo."
                )
                return

            self._sync_changes_to_storyboard(
                reason="regeneracion manual de guion completo",
                narrative_changed=False
            )
            self._trigger_auto_save("despues de regenerar guion completo")

            QMessageBox.information(
                self,
                "Guion Regenerado",
                "Guion, narraciÃ³n y subtÃ­tulos quedaron sincronizados para todo el proyecto."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo regenerar el guion completo:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_regenerate_script.setEnabled(True)
    
    def delete_segment_image(self, index):
        """Elimina la imagen de un segmento (mostrarÃ¡ imagen negra)"""
        if index < len(self.segments):
            # Guardar el image_path original antes de eliminarlo (para poder revertir)
            if 'image_path' in self.segments[index] and self.segments[index]['image_path']:
                self.segments[index]['original_image_path'] = self.segments[index]['image_path']
            
            self.segments[index]['image_deleted'] = True
            # Limpiar image_path para que no se use
            if 'image_path' in self.segments[index]:
                del self.segments[index]['image_path']
            # Activar auto-guardado automÃ¡tico
            self._trigger_auto_save("despuÃ©s de eliminar imagen")
            self._refresh_media_widgets([index], {index: None})
            QMessageBox.information(
                self,
                "Imagen Eliminada",
                f"La imagen del segmento #{index + 1} serÃ¡ reemplazada por una imagen negra en el video final.\n\n"
                "Puedes revertir esta acciÃ³n usando el botÃ³n â†©ï¸ o el menÃº contextual."
            )
    
    def remove_segment_image(self, index):
        """Elimina completamente la imagen de un segmento (permite agregar otra imagen o video despuÃ©s)"""
        if index < 0 or index >= len(self.segments):
            return
        
        # Confirmar eliminaciÃ³n
        reply = QMessageBox.question(
            self,
            "Confirmar EliminaciÃ³n de Imagen",
            f"Â¿Eliminar completamente la imagen del segmento #{index + 1}?\n\n"
            f"DespuÃ©s podrÃ¡s agregar otra imagen o un video al segmento.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        segment = self.segments[index]
        
        # Obtener image_path (si existe y no es video)
        image_path = segment.get('image_path', None)
        if image_path:
            # Verificar que no sea un video
            if image_path.lower().endswith(('.mp4', '.webm', '.avi', '.mov', '.mkv', '.ogv', '.mpeg', '.mpg')):
                # Es un video, no una imagen
                QMessageBox.information(
                    self,
                    "Es un Video",
                    f"El segmento #{index + 1} tiene un video, no una imagen.\n\n"
                    f"Usa 'ðŸ—‘ï¸ Eliminar Video' para eliminar el video."
                )
                return
        
        if image_path:
            # Guardar informaciÃ³n de la imagen original antes de eliminarla
            if 'original_image_path' not in segment:
                segment['original_image_path'] = image_path
        
        # Eliminar image_path
        if 'image_path' in segment:
            del segment['image_path']
        
        # Eliminar image_source
        if 'image_source' in segment:
            del segment['image_source']
        
        # Eliminar flag de eliminada si existe (ya no es necesario)
        if 'image_deleted' in segment:
            del segment['image_deleted']
        
        # Activar auto-guardado automático
        self._trigger_auto_save("después de eliminar imagen completamente")
        self._refresh_media_widgets([index], {index: None})
        
        # Actualizar el editor de segmentos si está mostrando este segmento
        if self.selected_index == index:
            self.segment_editor.load_segment(self.segments[index])
        
        QMessageBox.information(
            self,
            "Imagen Eliminada",
            f"✅ La imagen del segmento #{index + 1} ha sido eliminada completamente.\n\n"
            f"Ahora puedes agregar otra imagen o un video al segmento usando el menú contextual."
        )
    

    
    def clear_media_from_selected(self):
        """Quita completamente imagen y/o video de todos los segmentos seleccionados."""
        selected_indices = [i for i, w in enumerate(self.segment_widgets) if w.is_checked]
        if not selected_indices:
            QMessageBox.warning(self, "Sin selección",
                                "Marca al menos un segmento con el checkbox.")
            return

        reply = QMessageBox.question(
            self,
            "Quitar media de seleccionados",
            f"¿Quitar imagen y video de {len(selected_indices)} segmento(s) seleccionado(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        cleared = 0
        for idx in selected_indices:
            if idx >= len(self.segments):
                continue
            seg = self.segments[idx]
            had_media = bool(seg.get('image_path') or seg.get('video_path'))
            for key in ('image_path', 'image_source', 'image_deleted',
                        'video_path', 'video_source', 'original_image_path'):
                seg.pop(key, None)
            if had_media:
                cleared += 1

        for widget in self.segment_widgets:
            widget.set_checked(False)
        self.update_delete_button_state()
        self._trigger_auto_save("después de quitar media de seleccionados")
        # _refresh_media_widgets ya reconstruye el timeline si la agrupacion cambia
        # (quitar una imagen compartida divide un grupo) o actualiza en sitio si no.
        # El refresh_timeline() extra que habia aqui causaba un doble rebuild garantizado.
        self._refresh_media_widgets(selected_indices, {i: None for i in selected_indices})

    def generate_all_ai_images(self):
        """Genera imagenes inteligentes (solo para la selección actual si hay alguna, o para todo el guion si no hay nada seleccionado)."""
        selected_indices = [i for i, widget in enumerate(self.segment_widgets) if widget.is_checked]
        
        target_indices = []
        if selected_indices:
            # Solo procesar los seleccionados que no tengan imagen manual
            for i in selected_indices:
                segment = self.segments[i]
                image_source = segment.get('image_source', '')
                image_path = segment.get('image_path')
                
                # Ignorar si es manual
                manual_sources = ['wikimedia', 'bing_images', 'google_images', 'pexels_video', 'wikimedia_video', 'internet_archive', 'youtube']
                if image_source in manual_sources:
                    continue
                    
                target_indices.append(i)
        else:
            # Si no hay seleccion, procesar todo el guion (limpiar generadas previas y crear faltantes)
            for i, segment in enumerate(self.segments):
                image_path = segment.get('image_path')
                image_source = segment.get('image_source', '')
                
                if image_path and image_source in TIMELINE_AI_IMAGE_SOURCES:
                    target_indices.append(i)
                elif not image_path or segment.get('image_deleted', False):
                    target_indices.append(i)
        
        if not target_indices:
            QMessageBox.information(
                self,
                "Sin Segmentos para Procesar",
                "No hay segmentos que necesiten imagenes nuevas."
            )
            return
            
        scope_text = "los seleccionados" if selected_indices else "todo el guion"
        
        # Confirmar limpieza y generación
        reply = QMessageBox.question(
            self,
            "Generar imagenes",
            f"¿Generar nuevas imagenes para {len(target_indices)} segmento(s) en {scope_text}?\n\n"
            f"Segmentos a procesar: {', '.join(str(i+1) for i in target_indices[:10])}{'...' if len(target_indices) > 10 else ''}\n\n"
            f"Las imagenes manuales se conservaran.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Generar imágenes para los segmentos filtrados
        self._generate_ai_images_for_segments(target_indices, clean_existing_ai=(not selected_indices))

    def _get_images_per_segment_frequency(self):
        """Obtiene la frecuencia (segmentos por imagen) configurada en Studio."""
        try:
            studio_tab = self._get_studio_tab()
            if studio_tab and hasattr(studio_tab, 'images_per_segment_spin'):
                return max(1, int(studio_tab.images_per_segment_spin.value()))
        except Exception:
            pass
        return 1


    def _generate_ai_images_for_segments(self, segment_indices, clean_existing_ai=True,
                                         segment_groups=None, segments_per_image=1):
        """Genera imagenes para una lista de segmentos."""
        self._ai_batch_clean_mode = bool(clean_existing_ai)
        self._ai_segment_group_map = {}
        self._ai_segments_per_image = max(1, int(segments_per_image or 1))
        self._ai_total_target_segments = 0
        
        provider_key = self._get_current_image_provider_key()
        if provider_key == "manual":
            QMessageBox.warning(
                self,
                "Proveedor manual",
                "El proveedor de imagenes esta en modo manual. Cambialo a Recraft AI, Fal.ai o Google AI."
            )
            return

        provider_ok, provider_error = self._validate_image_provider_for_batch_generation(provider_key)
        if not provider_ok:
            QMessageBox.critical(
                self,
                "Proveedor no disponible",
                f"No se pudo inicializar el motor de generacion actual.\n\n{provider_error}"
            )
            return

        style = self._get_current_visual_style()
        platform = "youtube"
        try:
            studio_tab = self._get_studio_tab()
            if studio_tab and hasattr(studio_tab, "get_selected_platform_key"):
                platform = studio_tab.get_selected_platform_key() or "youtube"
        except Exception:
            platform = "youtube"

        valid_segment_indices = sorted(set(
            idx for idx in segment_indices if isinstance(idx, int) and 0 <= idx < len(self.segments)
        ))
        if not valid_segment_indices:
            QMessageBox.warning(
                self,
                "Sin Segmentos Validos",
                "No se encontraron segmentos validos para generar imagenes."
            )
            return
        
        if clean_existing_ai:
            # LIMPIEZA COMPLETA: Eliminar todas las imagenes generadas existentes primero
            for segment_index in valid_segment_indices:
                segment = self.segments[segment_index]
                image_path = segment.get('image_path')
                image_source = segment.get('image_source', '')
                
                # Eliminar imagen generada existente
                if image_path and image_source in TIMELINE_AI_IMAGE_SOURCES:
                    try:
                        old_path = Path(image_path)
                        if old_path.exists():
                            os.remove(old_path)
                            print(f"   Imagen anterior eliminada: {old_path.name}")
                    except Exception as e:
                        print(f"   No se pudo eliminar imagen anterior: {e}")
                    
                    # Limpiar datos del segmento
                    del segment['image_path']
                    if 'image_source' in segment:
                        del segment['image_source']
                    if 'image_deleted' in segment:
                        del segment['image_deleted']
                    
                    # Actualizar widget inmediatamente
                    if segment_index < len(self.segment_widgets):
                        self.segment_widgets[segment_index].segment_data = segment.copy()
                        self.segment_widgets[segment_index].update_image_preview()

        effective_groups = []
        if segment_groups:
            valid_set = set(valid_segment_indices)
            for group in segment_groups:
                normalized_group = []
                for idx in group:
                    if idx in valid_set and idx not in normalized_group:
                        normalized_group.append(idx)
                if normalized_group:
                    effective_groups.append(normalized_group)
        else:
            effective_groups = [[idx] for idx in valid_segment_indices]

        if not effective_groups:
            QMessageBox.warning(
                self,
                "Sin Segmentos Validos",
                "No se encontraron grupos validos para generar imagenes."
            )
            return

        self._ai_total_target_segments = sum(len(group) for group in effective_groups)
        
        # AHORA generar nuevas imagenes para todos los segmentos
        self.ai_generation_workers = []
        self.ai_generation_completed = 0
        
        for group in effective_groups:
            segment_index = group[0]
            segment = self.segments[segment_index]
            visual_prompt = str(segment.get('visual_prompt', '') or '').strip()

            if len(group) > 1:
                group_prompts = []
                for idx in group:
                    prompt = str(self.segments[idx].get('visual_prompt', '') or '').strip()
                    if prompt and prompt not in group_prompts:
                        group_prompts.append(prompt)
                if group_prompts:
                    visual_prompt = ", ".join(group_prompts[:3])
                    if len(group_prompts) > 3:
                        visual_prompt = f"{visual_prompt}, cohesive scene composition"

            visual_prompt = self._ensure_prompt_has_selected_aspect(visual_prompt)

            # Unificar el prompt (ya corregido) en todos los segmentos del grupo
            for idx in group:
                self.segments[idx]['visual_prompt'] = visual_prompt

            if not visual_prompt:
                print(f"   Segmento {segment_index+1} no tiene prompt visual, omitiendo")
                continue
            
            # Crear worker con nombre Ãºnico
            import time
            unique_filename = f"{segment.get('assigned_filename', f'segment_{segment_index+1:03d}')}_clean_{int(time.time())}"
            generation_config = {
                "image_provider": provider_key,
                "style": style,
                "platform": platform,
                "video_format": self._get_selected_image_aspect_ratio(),
            }
            worker = AIImageRegenerationWorker(
                segment_index,
                visual_prompt,
                unique_filename,
                generation_config=generation_config
            )
            worker.finished.connect(self._on_batch_ai_image_generated)
            worker.error.connect(self._on_batch_ai_image_error)
            worker.progress.connect(lambda msg: print(f"   {msg}"))
            
            self.ai_generation_workers.append(worker)
            self._ai_segment_group_map[segment_index] = group

        # Ajustar total segun grupos realmente encolados (evita desajustes si faltan prompts).
        self._ai_total_target_segments = sum(
            len(group) for group in self._ai_segment_group_map.values()
        )
        
        if not self.ai_generation_workers:
            QMessageBox.warning(
                self,
                "Sin Segmentos VÃ¡lidos",
                "No se encontraron segmentos vÃ¡lidos para generar imÃ¡genes."
            )
            return
        
        # Mostrar progreso
        self.progress_dialog = QMessageBox(self)
        if clean_existing_ai:
            self.progress_dialog.setWindowTitle("Limpiando y generando imagenes")
            self.progress_dialog.setText(f"Eliminando imagenes antiguas...\n\n"
                                       f"Luego generando {len(self.ai_generation_workers)} imagenes nuevas...\n\n"
                                       f"Por favor espera.")
        else:
            self.progress_dialog.setWindowTitle("Generando en seleccionados")
            if self._ai_segments_per_image > 1:
                self.progress_dialog.setText(
                    f"Generando {len(self.ai_generation_workers)} imagen(es) para "
                    f"{self._ai_total_target_segments} segmento(s) seleccionado(s) sin imagen...\n\n"
                    f"Frecuencia: {self._ai_segments_per_image} segmento(s) por imagen.\n\n"
                    f"Por favor espera."
                )
            else:
                self.progress_dialog.setText(
                    f"Generando {len(self.ai_generation_workers)} imagen(es) para segmentos seleccionados sin imagen...\n\n"
                    f"Por favor espera."
                )
        self.progress_dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        close_btn = self.progress_dialog.button(QMessageBox.StandardButton.Close)
        if close_btn:
            close_btn.setEnabled(False)  # Se habilita solo al finalizar
        self.progress_dialog.show()

        # Limitar concurrencia para evitar rate limit 429 de la API.
        self._ai_max_parallel_workers = 2
        self._ai_active_workers = set()
        self._ai_pending_workers = list(self.ai_generation_workers)
        self._start_next_ai_generation_workers()

    def _start_next_ai_generation_workers(self):
        """Inicia workers pendientes respetando limite de concurrencia."""
        if not hasattr(self, '_ai_pending_workers'):
            return
        if not hasattr(self, '_ai_active_workers'):
            self._ai_active_workers = set()
        if not hasattr(self, '_ai_max_parallel_workers'):
            self._ai_max_parallel_workers = 2

        while (
            self._ai_pending_workers
            and len(self._ai_active_workers) < self._ai_max_parallel_workers
        ):
            worker = self._ai_pending_workers.pop(0)
            self._ai_active_workers.add(worker)
            worker.start()

    def _close_progress_dialog_safely(self):
        """Cierra el dialogo de progreso de forma robusta."""
        if not hasattr(self, 'progress_dialog'):
            return
        dialog = self.progress_dialog
        if not dialog:
            return
        try:
            close_btn = dialog.button(QMessageBox.StandardButton.Close)
            if close_btn:
                close_btn.setEnabled(True)
            dialog.hide()
            dialog.done(0)
            dialog.close()
            dialog.deleteLater()
        except Exception:
            pass
        self.progress_dialog = None
    
    def _on_batch_ai_image_generated(self, segment_index, image_path):
        """Callback cuando se genera una imagen en batch"""
        worker = self.sender()
        if hasattr(self, '_ai_active_workers') and worker in self._ai_active_workers:
            self._ai_active_workers.remove(worker)

        if segment_index < 0 or segment_index >= len(self.segments):
            self._start_next_ai_generation_workers()
            return
        
        if not image_path or not os.path.exists(image_path):
            self._start_next_ai_generation_workers()
            return

        target_indices = self._ai_segment_group_map.get(segment_index, [segment_index])
        if not target_indices:
            target_indices = [segment_index]
        
        # Copiar al proyecto si hay uno activo
        final_image_path = image_path
        if hasattr(self, 'studio_tab') and hasattr(self.studio_tab, 'current_project_path') and self.studio_tab.current_project_path:
            from pathlib import Path
            import shutil
            
            project_path_obj = Path(self.studio_tab.current_project_path)
            project_dir = project_path_obj.parent
            
            media_dir = project_dir / "project_media"
            media_dir.mkdir(exist_ok=True)
            
            segment_number = target_indices[0] + 1
            filename = f"project_segment_{segment_number:03d}.jpg"
            dest_path = media_dir / filename
            
            # Generar nombre Ãºnico
            import time
            import hashlib
            timestamp = int(time.time())
            hash_suffix = hashlib.md5(f"{segment_index}_{final_image_path}_{timestamp}".encode()).hexdigest()[:8]
            name_part = Path(filename).stem
            ext = Path(filename).suffix
            filename = f"{name_part}_{timestamp}_{hash_suffix}{ext}"
            dest_path = media_dir / filename
            
            try:
                source_path = Path(image_path)
                if str(source_path.resolve()) != str(dest_path.resolve()):
                    shutil.copy2(source_path, dest_path)
                    final_image_path = f"project_media/{filename}"
                    print(f"ðŸ“ Imagen generada copiada al proyecto: {filename}")
            except Exception as e:
                print(f"âš ï¸ Error copiando imagen al proyecto: {e}")
        
        # Actualizar todos los segmentos del grupo (1 imagen para N segmentos)
        for target_index in target_indices:
            if target_index < 0 or target_index >= len(self.segments):
                continue

            self.segments[target_index]['image_path'] = final_image_path
            generated_source = getattr(worker, 'generated_image_source', '') if worker else ''
            self.segments[target_index]['image_source'] = generated_source or 'recraft_ai'

            if 'image_deleted' in self.segments[target_index]:
                del self.segments[target_index]['image_deleted']

        self._refresh_media_widgets(
            target_indices,
            {target_index: final_image_path for target_index in target_indices},
        )

        # Actualizar editor si estÃ¡ mostrando un segmento del grupo
        if self.selected_index in target_indices:
            self.segment_editor.load_segment(self.segments[self.selected_index])
        
        self.ai_generation_completed += 1
        self._start_next_ai_generation_workers()
        
        # Actualizar progreso
        if hasattr(self, 'progress_dialog'):
            completed = self.ai_generation_completed
            total = len(self.ai_generation_workers)
            if getattr(self, '_ai_batch_clean_mode', True):
                self.progress_dialog.setText(
                    f"Imagenes antiguas eliminadas\n\n"
                    f"Generando imagenes nuevas...\n\n"
                    f"Completado: {completed}/{total} imagenes"
                )
            else:
                total_segments = getattr(self, '_ai_total_target_segments', total)
                if getattr(self, '_ai_segments_per_image', 1) > 1:
                    self.progress_dialog.setText(
                        f"Generando imagenes para seleccionados sin imagen...\n\n"
                        f"Completado: {completed}/{total} imagenes "
                        f"({total_segments} segmentos objetivo)"
                    )
                else:
                    self.progress_dialog.setText(
                        f"Generando imagenes para seleccionados sin imagen...\n\n"
                        f"Completado: {completed}/{total} segmentos"
                    )
        
        # Si todas estÃ¡n completas, cerrar diÃ¡logo y guardar
        if self.ai_generation_completed >= len(self.ai_generation_workers):
            self._close_progress_dialog_safely()
            
            self._trigger_auto_save("despues de generar imagenes en batch")
            
            if getattr(self, '_ai_batch_clean_mode', True):
                QMessageBox.information(
                    self,
                    "Limpieza y generacion completadas",
                    f"Se eliminaron todas las imagenes antiguas.\n\n"
                    f"Se generaron {self.ai_generation_completed} imagenes nuevas.\n\n"
                    f"Las imagenes se guardaron en el proyecto y se restauraran al abrirlo."
                )
            else:
                total_segments = getattr(self, '_ai_total_target_segments', self.ai_generation_completed)
                QMessageBox.information(
                    self,
                    "Generacion completada",
                    f"Se generaron {self.ai_generation_completed} imagenes para {total_segments} segmento(s) seleccionado(s) sin imagen.\n\n"
                    f"Frecuencia aplicada: {getattr(self, '_ai_segments_per_image', 1)} segmento(s) por imagen.\n\n"
                    f"Las demas imagenes existentes se conservaron."
                )
    
    def _on_batch_ai_image_error(self, error_msg):
        """Callback cuando hay error en generaciÃ³n batch"""
        print(f"Error generando imagen: {error_msg}")
        worker = self.sender()
        if hasattr(self, '_ai_active_workers') and worker in self._ai_active_workers:
            self._ai_active_workers.remove(worker)
        
        # Contar como completado para no bloquear el proceso
        self.ai_generation_completed += 1
        self._start_next_ai_generation_workers()
        
        if hasattr(self, 'progress_dialog'):
            completed = self.ai_generation_completed
            total = len(self.ai_generation_workers)
            if getattr(self, '_ai_batch_clean_mode', True):
                self.progress_dialog.setText(
                    f"Imagenes antiguas eliminadas\n\n"
                    f"Generando imagenes nuevas...\n\n"
                    f"Completado: {completed}/{total} imagenes (con errores)"
                )
            else:
                total_segments = getattr(self, '_ai_total_target_segments', total)
                if getattr(self, '_ai_segments_per_image', 1) > 1:
                    self.progress_dialog.setText(
                        f"Generando imagenes para seleccionados sin imagen...\n\n"
                        f"Completado: {completed}/{total} imagenes "
                        f"({total_segments} segmentos objetivo, con errores)"
                    )
                else:
                    self.progress_dialog.setText(
                        f"Generando imagenes para seleccionados sin imagen...\n\n"
                        f"Completado: {completed}/{total} segmentos (con errores)"
                    )
        
        # Si todas estÃ¡n completas (incluso con errores), cerrar diÃ¡logo
        if self.ai_generation_completed >= len(self.ai_generation_workers):
            self._close_progress_dialog_safely()
            
            QMessageBox.warning(
                self,
                "GeneraciÃ³n Completada con Errores",
                f"Se completÃ³ la generaciÃ³n pero algunos segmentos tuvieron errores.\n\n"
                f"Revisa la consola para mÃ¡s detalles."
            )
    
    def delete_all_ai_images(self):
        """Elimina todas las imagenes generadas, conservando solo las insertadas manualmente."""
        # Identificar segmentos con imagenes generadas
        ai_segments = []
        manual_segments = []
        
        for i, segment in enumerate(self.segments):
            image_path = segment.get('image_path', None)
            image_source = segment.get('image_source', 'unknown')
            video_path = segment.get('video_path', None)
            video_source = segment.get('video_source', 'unknown')
            
            # Fuentes manuales que se deben conservar
            manual_sources = ['wikimedia', 'bing_images', 'google_images', 'pexels_video', 'wikimedia_video',
                            'internet_archive', 'youtube']
            
            # Verificar si tiene contenido manual
            has_manual_content = False
            if image_source in manual_sources or video_source in manual_sources:
                has_manual_content = True
            elif image_path and os.path.exists(image_path):
                # Verificar por ruta si es manual (no contiene indicadores de generacion)
                path_lower = image_path.lower()
                if not any(indicator in path_lower for indicator in TIMELINE_AI_PATH_HINTS):
                    has_manual_content = True
            elif video_path and os.path.exists(video_path):
                # Si tiene video_path, probablemente es manual
                has_manual_content = True
            
            # Verificar si es generada
            is_ai_generated = False
            if image_source in TIMELINE_AI_IMAGE_SOURCES:
                is_ai_generated = True
            elif image_path:
                path_lower = image_path.lower()
                if any(indicator in path_lower for indicator in TIMELINE_AI_PATH_HINTS):
                    is_ai_generated = True
            
            if is_ai_generated and not has_manual_content:
                ai_segments.append(i)
            elif has_manual_content:
                manual_segments.append(i)
        
        if not ai_segments:
            QMessageBox.information(
                self,
                "Sin imagenes generadas",
                "No se encontraron imagenes generadas para eliminar.\n\n"
                "Todas las imagenes son de fuentes manuales (Wikimedia, Openverse, videos, etc.)"
            )
            return
        
        # Confirmar eliminaciÃ³n
        reply = QMessageBox.question(
            self,
            "Eliminar imagenes generadas",
            f"¿Eliminar todas las imagenes generadas?\n\n"
            f"Resumen:\n"
            f"  - {len(ai_segments)} segmento(s) con imagenes generadas seran limpiados\n"
            f"  - {len(manual_segments)} segmento(s) con contenido manual se conservaran\n\n"
            f"Esto te permitira regenerar imagenes con un estilo diferente.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            deleted_count = 0
            for index in ai_segments:
                if index < len(self.segments):
                    segment = self.segments[index]
                    
                    # Eliminar image_path si es generada
                    if 'image_path' in segment:
                        image_path = segment.get('image_path', '')
                        image_source = segment.get('image_source', '')
                        
                        # Verificar que realmente es generada
                        is_ai = False
                        if image_source in TIMELINE_AI_IMAGE_SOURCES:
                            is_ai = True
                        elif image_path:
                            path_lower = image_path.lower()
                            if any(indicator in path_lower for indicator in TIMELINE_AI_PATH_HINTS):
                                is_ai = True
                        
                        if is_ai:
                            # Guardar original si no existe
                            if 'original_image_path' not in segment:
                                segment['original_image_path'] = image_path
                            
                            # IMPORTANTE: Eliminar el archivo fÃ­sico del disco
                            # Esto evita que se reutilice la imagen antigua cuando se regenera con otro estilo
                            if image_path and os.path.exists(image_path):
                                try:
                                    os.remove(image_path)
                                    print(f"   ðŸ—‘ï¸ Archivo eliminado: {os.path.basename(image_path)}")
                                except Exception as e:
                                    print(f"   âš ï¸ No se pudo eliminar el archivo {image_path}: {e}")
                            
                            # Eliminar image_path e image_source
                            del segment['image_path']
                            if 'image_source' in segment:
                                del segment['image_source']
                            
                            # Eliminar flag de eliminada si existe (para que no muestre imagen negra)
                            if 'image_deleted' in segment:
                                del segment['image_deleted']
                            
                            deleted_count += 1
                    
                    # Actualizar widget
                    if index < len(self.segment_widgets):
                        self.segment_widgets[index].segment_data = segment.copy()
                        self.segment_widgets[index].update_image_preview()
            
            # Refrescar timeline
            self.refresh_timeline()
            
            # Activar auto-guardado automÃ¡tico
            self._trigger_auto_save("despues de eliminar todas las imagenes generadas")
            
            QMessageBox.information(
                self,
                "EliminaciÃ³n Completada",
                f"Se eliminaron {deleted_count} imagen(es) generada(s).\n\n"
                f"Conservadas:\n"
                f"  - {len(manual_segments)} segmento(s) con contenido manual\n\n"
                f"Ahora puedes regenerar las imagenes con el boton 'Generar imagenes'."
            )
    
    def update_delete_button_state(self):
        """Actualiza el estado del botÃ³n de eliminaciÃ³n masiva y checkbox 'Seleccionar todos'"""
        has_selected = any(widget.is_checked for widget in self.segment_widgets)
        if hasattr(self, 'btn_clear_media_selected'):
            self.btn_clear_media_selected.setEnabled(has_selected)
        
        # Actualizar estado del checkbox "Seleccionar todos"
        if hasattr(self, 'select_all_checkbox'):
            total_segments = len(self.segment_widgets)
            if total_segments == 0:
                self.select_all_checkbox.setChecked(False)
                self.select_all_checkbox.setEnabled(False)
            else:
                self.select_all_checkbox.setEnabled(True)
                # Si todos estÃ¡n seleccionados, marcar "Seleccionar todos"
                all_selected = all(widget.is_checked for widget in self.segment_widgets)
                # Usar blockSignals para evitar loop infinito
                self.select_all_checkbox.blockSignals(True)
                self.select_all_checkbox.setChecked(all_selected)
                self.select_all_checkbox.blockSignals(False)
    
    def on_select_all_changed(self, state):
        """Callback cuando cambia el estado del checkbox 'Seleccionar todos'"""
        is_checked = (state == Qt.CheckState.Checked.value)
        
        # Marcar/desmarcar todos los checkboxes individuales
        for widget in self.segment_widgets:
            widget.set_checked(is_checked)
        
        # Actualizar estado del botÃ³n
        self.update_delete_button_state()
    
    def restore_segment_image(self, index):
        """Restaura la imagen eliminada de un segmento"""
        if index < len(self.segments):
            # Restaurar el image_path original si existe
            if 'original_image_path' in self.segments[index]:
                self.segments[index]['image_path'] = self.segments[index]['original_image_path']
                del self.segments[index]['original_image_path']
            
            # Quitar la marca de eliminada
            self.segments[index]['image_deleted'] = False
            
            # Activar auto-guardado automÃ¡tico
            self._trigger_auto_save("despuÃ©s de restaurar imagen eliminada")
            self._refresh_media_widgets(
                [index],
                {index: self.segments[index].get('image_path')},
            )
            
            QMessageBox.information(
                self,
                "Imagen Restaurada",
                f"La imagen del segmento #{index + 1} ha sido restaurada."
            )
    
    def delete_segment_video(self, index):
        """Elimina el video de un segmento (permite agregar otro video o imagen despuÃ©s)"""
        if index < 0 or index >= len(self.segments):
            return
        
        # Confirmar eliminaciÃ³n
        reply = QMessageBox.question(
            self,
            "Confirmar EliminaciÃ³n de Video",
            f"Â¿Eliminar el video del segmento #{index + 1}?\n\n"
            f"DespuÃ©s podrÃ¡s agregar otro video o una imagen al segmento.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        segment = self.segments[index]
        
        # Guardar informaciÃ³n del video original antes de eliminarlo (por si se quiere restaurar despuÃ©s)
        video_path = segment.get('video_path', None)
        if not video_path:
            # Intentar obtener desde image_path si es un video
            image_path = segment.get('image_path', None)
            if image_path:
                # Verificar si es un video por extensiÃ³n
                if image_path.lower().endswith(('.mp4', '.webm', '.avi', '.mov', '.mkv', '.ogv', '.mpeg', '.mpg')):
                    video_path = image_path
        
        if video_path:
            # Guardar en original_video_path si no existe
            if 'original_video_path' not in segment:
                segment['original_video_path'] = video_path
        
        # Eliminar video_path
        if 'video_path' in segment:
            del segment['video_path']
        
        # Eliminar video_source
        if 'video_source' in segment:
            del segment['video_source']
        
        # Si image_path apunta al mismo archivo que video_path, tambiÃ©n eliminarlo
        image_path = segment.get('image_path', None)
        if image_path and video_path and image_path == video_path:
            # Guardar en original_image_path si no existe
            if 'original_image_path' not in segment:
                segment['original_image_path'] = image_path
            del segment['image_path']
            # TambiÃ©n eliminar image_source si es el mismo que video_source
            if 'image_source' in segment and segment.get('image_source') == segment.get('video_source'):
                del segment['image_source']
        
        # Activar auto-guardado automÃ¡tico
        self._trigger_auto_save("despuÃ©s de eliminar video")
        self._refresh_media_widgets([index], {index: None})
        
        # Actualizar el editor de segmentos si estÃ¡ mostrando este segmento
        if self.selected_index == index:
            self.segment_editor.load_segment(self.segments[index])
        
        QMessageBox.information(
            self,
            "Video Eliminado",
            f"âœ… El video del segmento #{index + 1} ha sido eliminado.\n\n"
            f"Ahora puedes agregar otro video o una imagen al segmento usando el menÃº contextual."
        )
    
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
    
    
    
    def regenerate_ai_image(self, segment_index, skip_confirmation: bool = False,
                            force_provider: str = None):
        """Regenera la imagen IA del segmento seleccionado usando la pipeline central."""
        if segment_index < 0 or segment_index >= len(self.segments):
            return

        try:
            self.commit_active_segment_edits()
        except Exception:
            pass

        if segment_index in self._single_ai_regeneration_workers:
            QMessageBox.information(
                self,
                "Regeneracion en curso",
                f"El segmento #{segment_index + 1} ya se esta regenerando."
            )
            return

        segment = self._normalize_segment_narrative_fields(self.segments[segment_index], segment_index)
        self.segments[segment_index] = segment

        narration_text = self._extract_narration_text(segment)
        visual_prompt = str(segment.get("visual_prompt") or "").strip()
        if not narration_text and not visual_prompt:
            QMessageBox.warning(
                self,
                "Sin contenido visual",
                "Este segmento no tiene narracion ni prompt visual para regenerar la imagen."
            )
            return

        studio_tab = self._get_studio_tab()
        storyboard_data = getattr(studio_tab, "last_storyboard_data", {}) if studio_tab else {}
        image_provider = force_provider or self._get_current_image_provider_key()
        if image_provider == "manual":
            QMessageBox.warning(
                self,
                "Proveedor manual",
                "El proveedor de imagenes esta en modo manual. Cambialo a Recraft AI, Fal.ai o Google AI para regenerar con IA."
            )
            return

        style = self._get_current_visual_style()
        platform = "youtube"
        try:
            if studio_tab and hasattr(studio_tab, "get_selected_platform_key"):
                platform = studio_tab.get_selected_platform_key() or "youtube"
        except Exception:
            platform = "youtube"

        topic = ""
        category = "General"
        full_script = ""
        research_context = None
        if isinstance(storyboard_data, dict):
            topic = storyboard_data.get("topic") or ""
            category = storyboard_data.get("category") or "General"
            full_script = storyboard_data.get("script") or ""
            research_context = storyboard_data.get("research_context")

        narrative_context = self._build_segment_narrative_context(segment_index)
        prompt_preview = visual_prompt or narration_text

        if not skip_confirmation:
            reply = QMessageBox.question(
                self,
                "Regenerar imagen",
                (
                    f"Deseas regenerar la imagen del segmento #{segment_index + 1}?\n\n"
                    f"Se actualizara el prompt visual usando la narracion actual y el contexto local del timeline.\n"
                    f"Proveedor: {image_provider}\n"
                    f"Estilo: {style}\n"
                    f"Plataforma: {platform}\n\n"
                    f"Contexto actual: {prompt_preview[:160]}..."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Mark button as busy
        if 0 <= segment_index < len(self.segment_widgets):
            w = self.segment_widgets[segment_index]
            if hasattr(w, 'set_fal_image_busy'):
                w.set_fal_image_busy(True)

        generation_config = {
            "platform": platform,
            "style": style,
            "image_provider": image_provider,
            "refresh_prompt": True,
            "topic": topic,
            "category": category,
            "full_script": full_script,
            "research_context": research_context,
            "narrative_context": narrative_context,
            "video_format": self._get_selected_image_aspect_ratio(),
        }

        worker = ContextualAIImageRegenerationWorker(segment_index, segment, generation_config)
        worker.finished.connect(self.on_ai_image_generated)
        worker.error.connect(
            lambda msg, idx=segment_index: self._on_single_ai_regeneration_error(idx, msg)
        )
        worker.progress.connect(
            lambda msg, idx=segment_index: print(f"[TimelineEditor][AI Regen #{idx + 1}] {msg}")
        )
        self._single_ai_regeneration_workers[segment_index] = worker
        worker.start()

    def _on_single_ai_regeneration_error(self, segment_index, error_message):
        """Limpia el worker de regeneracion individual y muestra el error."""
        worker = self._single_ai_regeneration_workers.pop(segment_index, None)
        if worker:
            try:
                worker.deleteLater()
            except Exception:
                pass

        if 0 <= segment_index < len(self.segment_widgets):
            w = self.segment_widgets[segment_index]
            if hasattr(w, 'set_fal_image_busy'):
                w.set_fal_image_busy(False)

        QMessageBox.critical(
            self,
            "Error regenerando imagen",
            f"No se pudo regenerar la imagen del segmento #{segment_index + 1}.\n\n{error_message}"
        )

    # ------------------------------------------------------------------
    # FAL.AI I2V — per-slot animation
    # ------------------------------------------------------------------

    def _on_grouped_generate_fal_image(self, indices: list):
        """Genera imagen FAL.AI para un grupo: genera para el primer indice, propaga despues."""
        if not indices:
            return
        first = indices[0]
        self._pending_fal_group_indices = indices  # propagate after generation
        self.regenerate_ai_image(first, skip_confirmation=True, force_provider='fal')

    def _on_grouped_animate_fal_video(self, indices: list):
        """Anima la imagen compartida del grupo a video con FAL.AI."""
        if not indices:
            return
        self.animate_fal_video(indices[0], group_indices=indices)

    def animate_fal_video(self, segment_index: int, group_indices: list = None):
        """Inicia la generacion I2V (imagen → video) con FAL.AI para un segmento."""
        if segment_index < 0 or segment_index >= len(self.segments):
            return
        if segment_index in self._fal_i2v_workers:
            QMessageBox.information(
                self, "I2V en curso",
                f"El segmento #{segment_index + 1} ya esta siendo animado."
            )
            return

        segment = self.segments[segment_index]
        image_path = str(segment.get('image_path') or '').strip()

        # Resolve relative path
        if image_path and not os.path.isabs(image_path):
            try:
                from pathlib import Path as _P
                studio_tab = self._get_studio_tab()
                proj_path = getattr(studio_tab, 'current_project_path', None)
                if proj_path:
                    candidate = _P(proj_path).parent / image_path
                    if candidate.exists():
                        image_path = str(candidate)
            except Exception:
                pass

        if not image_path or not os.path.exists(image_path):
            QMessageBox.warning(self, "Sin imagen", "No se encontro la imagen para animar.")
            return

        motion_prompt = (
            str(segment.get('motion_prompt') or '').strip()
            or str(segment.get('visual_prompt') or '').strip()
            or "Slow dramatic camera motion, cinematic lighting"
        )

        # Determine aspect ratio
        studio_tab = self._get_studio_tab()
        platform = 'youtube'
        try:
            if studio_tab and hasattr(studio_tab, 'get_selected_platform_key'):
                platform = studio_tab.get_selected_platform_key() or 'youtube'
        except Exception:
            pass
        aspect_ratio = "9:16" if platform in ('instagram', 'tiktok', 'shorts') else "16:9"

        # Output path
        import time as _time
        from pathlib import Path as _P
        try:
            proj_path = getattr(self._get_studio_tab(), 'current_project_path', None)
            output_dir = _P(proj_path).parent / 'project_media' if proj_path else _P('auto_videos/temp')
        except Exception:
            output_dir = _P('auto_videos/temp')
        output_dir.mkdir(parents=True, exist_ok=True)
        seg_id = segment.get('assigned_filename') or f'seg_{segment_index + 1:03d}'
        output_path = str(output_dir / f"{seg_id}_i2v_{int(_time.time())}.mp4")

        # Duration from segment
        duration = 5
        try:
            raw = segment.get('duration') or segment.get('duration_seconds')
            if raw:
                duration = 10 if float(raw) > 7 else 5
        except Exception:
            pass

        video_model = os.getenv('FAL_VIDEO_MODEL', 'kling-standard')

        # Mark button busy
        if 0 <= segment_index < len(self.segment_widgets):
            w = self.segment_widgets[segment_index]
            if hasattr(w, 'set_fal_animate_busy'):
                w.set_fal_animate_busy(True)
        for gw in self._grouped_wrappers:
            if segment_index in getattr(gw, 'member_indices', []):
                if hasattr(gw, 'set_fal_animate_busy'):
                    gw.set_fal_animate_busy(True)

        from timeline_workers import FalI2VWorker
        worker = FalI2VWorker(
            segment_index=segment_index,
            image_path=image_path,
            motion_prompt=motion_prompt,
            output_path=output_path,
            aspect_ratio=aspect_ratio,
            duration=duration,
            video_model=video_model,
        )
        worker.finished.connect(
            lambda idx, vp, grp=group_indices: self._on_fal_i2v_done(idx, vp, grp)
        )
        worker.error.connect(self._on_fal_i2v_error)
        worker.progress.connect(
            lambda msg, idx=segment_index: (
                self.studio_tab.log(f"  [FAL I2V #{idx + 1}] {msg}")
                if self.studio_tab and hasattr(self.studio_tab, 'log') else None
            )
        )
        self._fal_i2v_workers[segment_index] = worker
        worker.start()
        if self.studio_tab and hasattr(self.studio_tab, 'log'):
            self.studio_tab.log(f"  [FAL I2V] Animando segmento #{segment_index + 1}...")

    def _on_fal_i2v_done(self, segment_index: int, video_path: str, group_indices: list = None):
        """Callback cuando FAL.AI termina de generar el video I2V."""
        self._fal_i2v_workers.pop(segment_index, None)

        # Reset button
        if 0 <= segment_index < len(self.segment_widgets):
            w = self.segment_widgets[segment_index]
            if hasattr(w, 'set_fal_animate_busy'):
                w.set_fal_animate_busy(False)
        for gw in self._grouped_wrappers:
            if segment_index in getattr(gw, 'member_indices', []):
                if hasattr(gw, 'set_fal_animate_busy'):
                    gw.set_fal_animate_busy(False)

        # Assign video path to all target segments (single or group)
        targets = group_indices if group_indices else [segment_index]
        for idx in targets:
            if 0 <= idx < len(self.segments):
                self.segments[idx]['video_path'] = video_path
                self.segments[idx]['video_source'] = 'fal_ai'

        self._refresh_media_widgets(targets, {})
        self._schedule_auto_save("fal_i2v_done")

        if self.studio_tab and hasattr(self.studio_tab, 'log'):
            self.studio_tab.log(
                f"  [FAL I2V] Segmento #{segment_index + 1} animado: {os.path.basename(video_path)}"
            )

    def _on_fal_i2v_error(self, segment_index: int, error_message: str):
        """Callback cuando FAL.AI I2V falla."""
        self._fal_i2v_workers.pop(segment_index, None)

        if 0 <= segment_index < len(self.segment_widgets):
            w = self.segment_widgets[segment_index]
            if hasattr(w, 'set_fal_animate_busy'):
                w.set_fal_animate_busy(False)
        for gw in self._grouped_wrappers:
            if segment_index in getattr(gw, 'member_indices', []):
                if hasattr(gw, 'set_fal_animate_busy'):
                    gw.set_fal_animate_busy(False)

        QMessageBox.critical(
            self,
            "Error FAL.AI I2V",
            f"No se pudo animar el segmento #{segment_index + 1}:\n{error_message}"
        )

    def on_ai_image_generated(self, segment_index, generated_payload):
        """Callback cuando la pipeline central genera una nueva imagen para un segmento."""
        worker = self._single_ai_regeneration_workers.pop(segment_index, None)
        if worker:
            try:
                worker.deleteLater()
            except Exception:
                pass

        # Reset FAL generate button busy state (set_fal_image_busy clears after image arrives
        # via update_display, but reset here in case generation failed silently)
        if 0 <= segment_index < len(self.segment_widgets):
            w = self.segment_widgets[segment_index]
            if hasattr(w, 'set_fal_image_busy'):
                w.set_fal_image_busy(False)

        if segment_index < 0 or segment_index >= len(self.segments):
            return

        generated_segment = generated_payload.copy() if isinstance(generated_payload, dict) else {}
        image_path = str(
            generated_segment.get("image_path") if generated_segment else (generated_payload or "")
        ).strip()
        if not image_path or not os.path.exists(image_path):
            QMessageBox.critical(
                self,
                "Error",
                "La regeneracion no devolvio una imagen valida para el segmento."
            )
            return

        current_segment = self.segments[segment_index].copy()
        old_image_path = str(current_segment.get("image_path") or "").strip()
        old_image_source = str(current_segment.get("image_source") or "").strip()

        final_image_path = image_path
        studio_tab = self.studio_tab or self._get_studio_tab()
        current_project_path = getattr(studio_tab, "current_project_path", None) if studio_tab else None
        if current_project_path:
            import shutil

            try:
                project_dir = Path(current_project_path).parent
                media_dir = project_dir / "project_media"
                media_dir.mkdir(exist_ok=True)

                segment_number = segment_index + 1
                base_filename = f"project_segment_{segment_number:03d}.jpg"
                timestamp = int(datetime.now(timezone.utc).timestamp())
                hash_suffix = hashlib.md5(
                    f"{segment_index}_{image_path}_{timestamp}".encode()
                ).hexdigest()[:8]
                name_part = Path(base_filename).stem
                extension = Path(base_filename).suffix
                filename = f"{name_part}_{timestamp}_{hash_suffix}{extension}"
                destination = media_dir / filename

                source_path = Path(image_path)
                if str(source_path.resolve()) != str(destination.resolve()):
                    shutil.copy2(source_path, destination)
                final_image_path = f"project_media/{filename}"
                print(f"[TimelineEditor] Imagen regenerada copiada al proyecto: {filename}")
            except Exception as e:
                print(f"[TimelineEditor] Warning copiando imagen regenerada al proyecto: {e}")

        current_segment["image_path"] = final_image_path
        current_segment["image_source"] = (
            str(generated_segment.get("image_source") or "").strip() or "recraft_ai"
        )
        current_segment.pop("image_deleted", None)
        current_segment.pop("video_path", None)
        current_segment.pop("video_source", None)

        for key in ("visual_prompt", "sfx_tag", "overlay_tag"):
            value = generated_segment.get(key) if generated_segment else None
            if value:
                current_segment[key] = value

        current_segment = self._normalize_segment_narrative_fields(current_segment, segment_index)
        self.segments[segment_index] = current_segment

        # Si la generacion fue para un grupo (boton del GroupedSegmentsWidget),
        # propagar la imagen al resto de los miembros del grupo.
        pending_group = getattr(self, '_pending_fal_group_indices', None)
        if pending_group:
            self._pending_fal_group_indices = None
            for grp_idx in pending_group:
                if grp_idx != segment_index and 0 <= grp_idx < len(self.segments):
                    self.segments[grp_idx]['image_path'] = final_image_path
                    self.segments[grp_idx]['image_source'] = current_segment.get('image_source', 'fal_ai')
                    self.segments[grp_idx].pop('image_deleted', None)

        all_affected = list(dict.fromkeys(
            [segment_index] + (pending_group or [])
        ))
        self._refresh_media_widgets(
            all_affected,
            {idx: final_image_path for idx in all_affected},
        )

        if self.selected_index == segment_index:
            self.segment_editor.load_segment(current_segment)

        self._sync_changes_to_storyboard(
            reason="despues de regenerar imagen IA desde timeline",
            narrative_changed=False,
            target_index=segment_index,
            target_segment=current_segment
        )
        self._trigger_auto_save("despues de regenerar imagen IA")

        if old_image_path and old_image_source in TIMELINE_AI_IMAGE_SOURCES:
            try:
                old_path = Path(old_image_path)
                if not old_path.is_absolute() and current_project_path:
                    old_path = Path(current_project_path).parent / old_path
                if old_path.exists():
                    old_path.unlink()
                    print(f"[TimelineEditor] Imagen IA anterior eliminada: {old_path.name}")
            except Exception as e:
                print(f"[TimelineEditor] Warning eliminando imagen IA anterior: {e}")

        QMessageBox.information(
            self,
            "Imagen regenerada",
            (
                f"Se regenero la imagen del segmento #{segment_index + 1}.\n\n"
                f"Archivo: {os.path.basename(final_image_path)}\n"
                f"El prompt visual se actualizo usando la narracion actual y el contexto local del timeline."
            )
        )

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
            from gemini_watermark_remover import remove_gemini_watermark
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
            from video_edit_dialog import VideoEditDialog
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


