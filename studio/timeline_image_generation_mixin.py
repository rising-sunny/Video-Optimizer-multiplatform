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


class TimelineImageGenerationMixin:
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

        from studio.timeline_workers import FalI2VWorker
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
