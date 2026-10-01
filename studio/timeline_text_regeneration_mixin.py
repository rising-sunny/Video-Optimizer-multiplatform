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


class TimelineTextRegenerationMixin:
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
            from ai.gemini_ai_client import GeminiAiClient
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
