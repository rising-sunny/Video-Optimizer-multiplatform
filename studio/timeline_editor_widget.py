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


from studio.timeline_local_media_mixin import TimelineLocalMediaMixin


from studio.timeline_text_regeneration_mixin import TimelineTextRegenerationMixin


class TimelineEditorWidget(TimelineTextRegenerationMixin, TimelineLocalMediaMixin, TimelineSearchDialogsMixin, TimelineImageGenerationMixin, QWidget):
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
        from pipeline.image_generation_manager import primary_aspect_ratio_from_format

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
        from pipeline.image_generation_manager import apply_aspect_ratio_to_visual_prompt
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
            from studio.studio_image_handlers import resolve_image_provider_key
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
            from ai import visual_art_direction as vad
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
            from ai import visual_art_direction as vad
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
            from ai.gemini_watermark_remover import remove_gemini_watermark
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
                from ai.fal_ai_client import FalAiClient
                client = FalAiClient()
                if getattr(client, "client_available", False):
                    return True, ""
                return False, "Configura FAL_KEY o FAL_API_KEY en tu archivo .env para usar Fal.ai."
            if provider == "google_ai":
                from ai.google_ai_image_client import GoogleAiImageClient
                client = GoogleAiImageClient()
                if getattr(client, "client_available", False):
                    return True, ""
                return False, "Configura GEMINI_API_KEY/GOOGLE_API_KEY en tu archivo .env para usar Google AI."

            from ai.recraft_client import RecraftClient
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
    
    










    
    
    

    






    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    


    # ------------------------------------------------------------------
    # FAL.AI I2V — per-slot animation
    # ------------------------------------------------------------------

































