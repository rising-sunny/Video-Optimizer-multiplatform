# wikimedia_video_search_dialog.py
"""
DiÃ¡logo WikimediaVideoSearchDialog.
ExtraÃ­do de timeline_editor_widget.py para mejorar la organizaciÃ³n del cÃ³digo.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QMessageBox, QScrollArea, QWidget, QCheckBox, QGroupBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPixmap, QIcon, QColor, QPainter, QPen, QFont
from pathlib import Path
import os
import requests
import warnings
import re
import html
import hashlib
import time
from urllib.parse import urlparse, quote, unquote


class VideoThumbnailDownloadWorker(QThread):
    """Descarga miniaturas de video fuera del hilo principal."""
    finished = pyqtSignal(int, str, int, object, str, str)  # token, url, status, bytes|None, retry_after, error

    def __init__(self, token, image_url, timeout=8):
        super().__init__()
        self.token = token
        self.image_url = image_url
        self.timeout = timeout

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            response = requests.get(
                self.image_url,
                timeout=self.timeout,
                headers={
                    'User-Agent': 'VideoOptimizerPro/1.0 (https://commons.wikimedia.org/)',
                    'Accept': 'image/*,*/*;q=0.8',
                    'Referer': 'https://commons.wikimedia.org/'
                }
            )
            if self.isInterruptionRequested():
                return
            retry_after = response.headers.get('Retry-After', '')
            payload = response.content if response.status_code == 200 else None
            self.finished.emit(self.token, self.image_url, int(response.status_code), payload, retry_after, "")
        except Exception as e:
            self.finished.emit(self.token, self.image_url, 0, None, "", str(e))

# Importar WikimediaClient y verificar disponibilidad
try:
    from media.wikimedia_client import WikimediaClient
    WIKIMEDIA_VIDEO_AVAILABLE = True
except ImportError:
    WIKIMEDIA_VIDEO_AVAILABLE = False
    WikimediaClient = None

# Importar workers desde timeline_workers
try:
    from studio.timeline_workers import WikimediaVideoSearchWorker, VideoFrameExtractorWorker
except ImportError:
    WikimediaVideoSearchWorker = None
    VideoFrameExtractorWorker = None
    if WIKIMEDIA_VIDEO_AVAILABLE:
        print("âš ï¸ timeline_workers.py no encontrado. Workers de Wikimedia no estarÃ¡n disponibles.")

# Importar attribution manager
try:
    from infra.attribution_manager import get_attribution_manager
    ATTRIBUTION_AVAILABLE = True
except ImportError:
    ATTRIBUTION_AVAILABLE = False

# Importar VideoTimelineWidget
try:
    from studio.timeline_video_widget import VideoTimelineWidget
except ImportError:
    VideoTimelineWidget = None
    print("âš ï¸ timeline_video_widget.py no encontrado. VideoTimelineWidget no estarÃ¡ disponible.")
    get_attribution_manager = None

class WikimediaVideoSearchDialog(QDialog):
    """DiÃ¡logo para buscar y seleccionar videos histÃ³ricos de Wikimedia Commons"""

    _previous_results = {}
    _MAX_PREVIOUS_QUERIES = 6
    _MAX_PREVIOUS_ITEMS_PER_QUERY = 8
    _MAX_PRELOADED_ITEMS_ON_OPEN = 18
    _THUMB_429_STRIKE_LIMIT = 2
    _THUMB_429_COOLDOWN_MS = 20 * 60 * 1000
    _thumb_429_cooldowns = {}  # {url: until_ms}
    _thumb_429_strikes = {}    # {url: strikes}

    def __init__(self, parent=None, segment_data=None):
        super().__init__(parent)
        self.segment_data = segment_data or {}
        self.selected_video_path = None
        self.videos = []
        self.worker = None  # Inicializar worker como None
        self._thumb_queue = []
        self._thumb_workers = {}
        self._thumb_item_by_token = {}
        self._thumb_meta_by_token = {}
        self._thumb_token_by_item_id = {}
        self._thumb_token_counter = 0
        self._thumb_retry_limit = 4
        self._max_parallel_thumb_workers = 1
        self._thumb_pause_until_ms = 0
        self._thumb_cache_dir = Path("auto_videos") / "cache" / "wikimedia_video_thumbs"
        self._thumb_cache_dir.mkdir(parents=True, exist_ok=True)
        self._closing = False

        # Worker para extraer frames del video
        self.frame_extractor_worker = None
        self._current_video_url = None
        self.playback_timer = None
        self.playback_position = 0.0
        self.is_playing = False
        self.preview_frames = []
        self.preview_video_path = None
        self.preview_video_clip = None
        self.preview_playback_fps = 12.0
        self._playing_crop_range = False
        self._crop_play_start = 0.0
        self._crop_play_end = 0.0

        self.setWindowTitle("ðŸ“¹ Buscar Videos HistÃ³ricos en Wikimedia Commons")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 900)  # TamaÃ±o inicial mÃ¡s grande

        self.setup_ui()
        self.load_previous_results()

        suggested_query = self.suggest_query_from_segment(self.segment_data)
        if suggested_query:
            self.search_input.setText(suggested_query)

    @staticmethod
    def _normalize_duration(duration_value):
        """Convierte duraciÃ³n a segundos (float), devolviendo 0.0 si no es vÃ¡lida."""
        if duration_value is None or isinstance(duration_value, bool):
            return 0.0

        if isinstance(duration_value, (int, float)):
            return float(duration_value) if duration_value > 0 else 0.0

        if isinstance(duration_value, str):
            raw_value = duration_value.strip()
            if not raw_value:
                return 0.0

            normalized = raw_value.replace(",", ".")

            # Soporta formatos tipo mm:ss o hh:mm:ss.
            if ":" in normalized:
                parts = [p.strip() for p in normalized.split(":")]
                values = []
                for part in parts:
                    if not part:
                        return 0.0
                    try:
                        values.append(float(part))
                    except ValueError:
                        values = []
                        break
                if values:
                    total_seconds = 0.0
                    for value in values:
                        total_seconds = total_seconds * 60 + value
                    return total_seconds if total_seconds > 0 else 0.0

            # Soporta strings como "325.8 segundos" extrayendo nÃºmero.
            numeric_text = "".join(ch for ch in normalized if ch.isdigit() or ch == ".")
            if numeric_text:
                try:
                    numeric_value = float(numeric_text)
                    return numeric_value if numeric_value > 0 else 0.0
                except ValueError:
                    return 0.0

        return 0.0

    @staticmethod
    def _format_duration(duration_seconds):
        """Formatea duraciÃ³n numÃ©rica para UI."""
        if duration_seconds <= 0:
            return "N/A"

        total_seconds = int(duration_seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _clean_text(raw_text):
        """Limpia HTML y entidades para mostrar texto legible."""
        if not isinstance(raw_text, str):
            return ""
        text = re.sub(r"<[^>]+>", " ", raw_text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _create_generic_video_icon(self):
        """Crea un Ã­cono de fallback para videos."""
        icon = QIcon()
        pixmap = QPixmap(320, 180)
        pixmap.fill(QColor(30, 30, 30))
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.setFont(QFont("Arial", 24))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "ðŸ“¹\nVideo")
        painter.end()
        icon.addPixmap(pixmap)
        return icon

    def _load_video_thumbnail_icon(self, video):
        """Devuelve ícono placeholder; la miniatura real se carga asíncronamente."""
        return self._create_generic_video_icon()

    @staticmethod
    def _normalize_thumbnail_url(url):
        if not isinstance(url, str):
            return ""
        value = url.strip()
        if not value:
            return ""
        if value.startswith('//'):
            value = f"https:{value}"
        elif value.startswith('/'):
            value = f"https://commons.wikimedia.org{value}"
        if value.startswith(('http://', 'https://')):
            return value
        return ""

    @staticmethod
    def _retry_after_to_ms(retry_after_value):
        if not retry_after_value:
            return None
        try:
            seconds = float(retry_after_value)
            if seconds >= 0:
                return int(seconds * 1000)
        except (TypeError, ValueError):
            return None
        return None

    @classmethod
    def _is_thumb_url_in_cooldown(cls, url, now_ms):
        if not url:
            return False
        until = int(cls._thumb_429_cooldowns.get(url, 0) or 0)
        if until <= 0:
            return False
        if now_ms >= until:
            cls._thumb_429_cooldowns.pop(url, None)
            cls._thumb_429_strikes.pop(url, None)
            return False
        return True

    @classmethod
    def _register_thumb_429(cls, url, now_ms):
        if not url:
            return 0
        strikes = int(cls._thumb_429_strikes.get(url, 0) or 0) + 1
        cls._thumb_429_strikes[url] = strikes
        if strikes >= cls._THUMB_429_STRIKE_LIMIT:
            cls._thumb_429_cooldowns[url] = now_ms + cls._THUMB_429_COOLDOWN_MS
        return strikes

    @classmethod
    def _clear_thumb_429(cls, url):
        if not url:
            return
        cls._thumb_429_cooldowns.pop(url, None)
        cls._thumb_429_strikes.pop(url, None)

    def _finalize_thumb_token(self, token):
        item = self._thumb_item_by_token.pop(token, None)
        self._thumb_meta_by_token.pop(token, None)
        if item is not None:
            self._thumb_token_by_item_id.pop(id(item), None)

    @staticmethod
    def _to_upload_video_thumb_url(video_url, width=320):
        if not isinstance(video_url, str):
            return ""
        candidate = video_url.strip()
        if not candidate:
            return ""
        try:
            parsed = urlparse(candidate)
            if parsed.scheme not in ("http", "https"):
                return ""
            if "upload.wikimedia.org" not in (parsed.netloc or ""):
                return ""
            path = parsed.path or ""
            if "/wikipedia/commons/" not in path:
                return ""
            if "/thumb/" in path:
                return candidate
            filename = os.path.basename(path)
            if not filename:
                return ""
            return (
                f"{parsed.scheme}://{parsed.netloc}"
                f"/wikipedia/commons/thumb{path.replace('/wikipedia/commons', '', 1)}"
                f"/{int(width)}px-{filename}.jpg"
            )
        except Exception:
            return ""

    @staticmethod
    def _to_special_filepath_thumb_url(file_name_or_url, width=320):
        if not isinstance(file_name_or_url, str):
            return ""
        source = file_name_or_url.strip()
        if not source:
            return ""
        try:
            parsed = urlparse(source)
            filename = os.path.basename(parsed.path) if parsed.scheme else source
            if not filename:
                return ""
            decoded = unquote(filename)
            encoded = quote(decoded, safe="")
            return f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded}?width={int(width)}"
        except Exception:
            return ""

    def _build_video_thumbnail_candidates(self, video):
        candidates = []
        for key in ('thumburl', 'thumbnail_url', 'thumbnail', 'image'):
            normalized = self._normalize_thumbnail_url(video.get(key))
            if normalized:
                candidates.append(normalized)

        video_url = self._normalize_thumbnail_url(video.get('url', ''))
        if video_url:
            for w in (640, 320, 240):
                generated = self._to_upload_video_thumb_url(video_url, width=w)
                if generated:
                    candidates.append(generated)
            for w in (640, 320, 240):
                generated = self._to_special_filepath_thumb_url(video_url, width=w)
                if generated:
                    candidates.append(generated)

        title = str(video.get('title', '') or '')
        if title:
            for w in (640, 320, 240):
                generated = self._to_special_filepath_thumb_url(title, width=w)
                if generated:
                    candidates.append(generated)

        unique = []
        seen = set()
        now_ms = self._now_ms()
        for candidate in candidates:
            normalized = self._normalize_thumbnail_url(candidate)
            if not normalized or normalized in seen:
                continue
            if self._is_thumb_url_in_cooldown(normalized, now_ms):
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique

    def _set_video_item_icon_from_bytes(self, item, image_data):
        pixmap = QPixmap()
        if not image_data or not pixmap.loadFromData(image_data) or pixmap.isNull():
            return False
        target_w, target_h = 320, 180
        scaled = pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        canvas = QPixmap(target_w, target_h)
        canvas.fill(QColor(30, 30, 30))
        painter = QPainter(canvas)
        x = (target_w - scaled.width()) // 2
        y = (target_h - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        icon = QIcon()
        icon.addPixmap(canvas)
        item.setIcon(icon)
        return True

    def _queue_video_thumbnail_load(self, item, video):
        if self._closing:
            return

        item_id = id(item)
        existing_token = self._thumb_token_by_item_id.get(item_id)
        if existing_token and existing_token in self._thumb_meta_by_token:
            return

        thumb_candidates = self._build_video_thumbnail_candidates(video)
        if not thumb_candidates:
            return

        for candidate in thumb_candidates:
            cache_path = self._get_thumb_cache_path(candidate)
            if not cache_path.exists():
                continue
            try:
                data = cache_path.read_bytes()
                if self._set_video_item_icon_from_bytes(item, data):
                    return
            except Exception:
                continue

        self._thumb_token_counter += 1
        token = self._thumb_token_counter
        self._thumb_item_by_token[token] = item
        self._thumb_token_by_item_id[item_id] = token
        self._thumb_meta_by_token[token] = {
            'url': thumb_candidates[0],
            'candidates': thumb_candidates,
            'candidate_index': 0,
            'title': str(video.get('title', '') or ''),
            'retry_count': 0
        }
        self._thumb_queue.append(token)
        self._start_video_thumb_workers()

    @staticmethod
    def _now_ms():
        return int(time.monotonic() * 1000)

    def _get_thumb_cache_path(self, image_url):
        key = hashlib.sha1(image_url.encode("utf-8", errors="ignore")).hexdigest()
        return self._thumb_cache_dir / f"{key}.bin"

    def _start_video_thumb_workers(self):
        if self._closing:
            return

        now_ms = self._now_ms()
        if self._thumb_pause_until_ms > now_ms:
            delay_ms = max(80, self._thumb_pause_until_ms - now_ms)
            QTimer.singleShot(delay_ms, self._start_video_thumb_workers)
            return

        while self._thumb_queue and len(self._thumb_workers) < self._max_parallel_thumb_workers:
            token = self._thumb_queue.pop(0)
            meta = self._thumb_meta_by_token.get(token)
            item = self._thumb_item_by_token.get(token)
            if not meta or item is None:
                continue

            worker = VideoThumbnailDownloadWorker(token, meta.get('url', ''), timeout=8)
            worker.finished.connect(self._on_video_thumb_download_finished)
            worker.finished.connect(lambda *_, w=worker: w.deleteLater())
            self._thumb_workers[token] = worker
            worker.start()

    def _on_video_thumb_download_finished(self, token, image_url, status_code, image_data, retry_after, error_msg):
        worker = self._thumb_workers.pop(token, None)
        if worker and worker.isRunning():
            worker.quit()
            worker.wait(50)

        if self._closing:
            return

        item = self._thumb_item_by_token.get(token)
        meta = self._thumb_meta_by_token.get(token, {})
        if item is None or not meta:
            self._start_video_thumb_workers()
            return

        retry_count = int(meta.get('retry_count', 0) or 0)
        candidate_index = int(meta.get('candidate_index', 0) or 0)
        candidates = list(meta.get('candidates', []) or [])
        has_next_candidate = candidate_index + 1 < len(candidates)

        if status_code == 200 and image_data:
            if self._set_video_item_icon_from_bytes(item, image_data):
                self._clear_thumb_429(image_url)
                try:
                    cache_path = self._get_thumb_cache_path(image_url)
                    cache_path.write_bytes(image_data)
                except Exception:
                    pass
                self._finalize_thumb_token(token)
            elif has_next_candidate:
                meta['candidate_index'] = candidate_index + 1
                meta['url'] = candidates[meta['candidate_index']]
                self._thumb_meta_by_token[token] = meta
                QTimer.singleShot(200, lambda t=token: self._requeue_video_thumb_token(t))
            else:
                self._finalize_thumb_token(token)
        elif status_code == 429:
            strikes = self._register_thumb_429(image_url, self._now_ms())
            if has_next_candidate:
                meta['candidate_index'] = candidate_index + 1
                meta['url'] = candidates[meta['candidate_index']]
                self._thumb_meta_by_token[token] = meta
                QTimer.singleShot(250, lambda t=token: self._requeue_video_thumb_token(t))
            elif strikes >= self._THUMB_429_STRIKE_LIMIT or retry_count >= self._thumb_retry_limit:
                self._finalize_thumb_token(token)
            else:
                retry_after_ms = self._retry_after_to_ms(retry_after)
                backoff_ms = retry_after_ms if retry_after_ms is not None else int((2 ** retry_count) * 6000)
                now_ms = self._now_ms()
                self._thumb_pause_until_ms = max(self._thumb_pause_until_ms, now_ms + backoff_ms)
                meta['retry_count'] = retry_count + 1
                self._thumb_meta_by_token[token] = meta
                QTimer.singleShot(backoff_ms, lambda t=token: self._requeue_video_thumb_token(t))
        elif status_code in (0, 403, 404):
            if has_next_candidate:
                meta['candidate_index'] = candidate_index + 1
                meta['url'] = candidates[meta['candidate_index']]
                self._thumb_meta_by_token[token] = meta
                QTimer.singleShot(250, lambda t=token: self._requeue_video_thumb_token(t))
            elif retry_count < self._thumb_retry_limit:
                meta['retry_count'] = retry_count + 1
                self._thumb_meta_by_token[token] = meta
                QTimer.singleShot(1000, lambda t=token: self._requeue_video_thumb_token(t))
            else:
                self._finalize_thumb_token(token)
        elif has_next_candidate:
            meta['candidate_index'] = candidate_index + 1
            meta['url'] = candidates[meta['candidate_index']]
            self._thumb_meta_by_token[token] = meta
            QTimer.singleShot(250, lambda t=token: self._requeue_video_thumb_token(t))
        else:
            if error_msg:
                print(f"️ Error miniatura Wikimedia video: {error_msg}")
            elif status_code and status_code != 200:
                print(f"️ Miniatura video sin cargar ({status_code})")
            self._finalize_thumb_token(token)

        QTimer.singleShot(450, self._start_video_thumb_workers)

    def _requeue_video_thumb_token(self, token):
        if self._closing:
            return
        if token not in self._thumb_item_by_token or token not in self._thumb_meta_by_token:
            return
        if token in self._thumb_queue:
            return
        meta = self._thumb_meta_by_token.get(token, {})
        current_url = str(meta.get('url', '') or '')
        if self._is_thumb_url_in_cooldown(current_url, self._now_ms()):
            self._finalize_thumb_token(token)
            QTimer.singleShot(450, self._start_video_thumb_workers)
            return
        self._thumb_queue.append(token)
        self._start_video_thumb_workers()

    def _cancel_video_thumbnail_loads(self):
        self._thumb_queue.clear()
        self._thumb_pause_until_ms = 0
        for _, worker in list(self._thumb_workers.items()):
            try:
                worker.requestInterruption()
                worker.wait(150)
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(150)
            except Exception:
                pass
        self._thumb_workers.clear()
        self._thumb_item_by_token.clear()
        self._thumb_meta_by_token.clear()
        self._thumb_token_by_item_id.clear()

    @staticmethod
    def _is_video_item(video):
        """Valida de forma defensiva que el resultado sea un video."""
        if not isinstance(video, dict):
            return False

        url = str(video.get('url', '') or '').lower()
        image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.tif', '.tiff')
        if any(url.endswith(ext) for ext in image_exts):
            return False

        mime_type = str(video.get('mime_type', '') or '').lower()
        if mime_type.startswith('video/'):
            return True

        video_exts = ('.webm', '.ogv', '.ogg', '.mp4', '.mov', '.mkv')
        if any(url.endswith(ext) for ext in video_exts):
            return True

        media_type = str(video.get('media_type', '') or '').lower()
        return media_type == 'video' and bool(url)
    
    def setup_ui(self):
        """Configura la interfaz del diÃ¡logo"""
        layout = QVBoxLayout(self)
        
        search_layout = QHBoxLayout()
        search_label = QLabel("ðŸ” Buscar:")
        search_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Ej: World War II, Apollo 11, Berlin Wall, etc.")
        self.search_input.returnPressed.connect(self.perform_search)
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("ðŸ” Buscar")
        self.search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(self.search_btn)
        
        layout.addLayout(search_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Ãrea de scroll para el contenido principal
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Mantener scroll vertical visible para acceder siempre a todas las funciones del diálogo.
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        
        # Widget contenedor para el contenido desplazable
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        results_label = QLabel("Resultados:")
        scroll_layout.addWidget(results_label)
        
        self.results_list = QListWidget()
        # Usar IconMode para mostrar mejor las miniaturas con vista previa
        self.results_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.results_list.setIconSize(QSize(320, 180))  # TamaÃ±o estÃ¡ndar de thumbnail (16:9)
        self.results_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.results_list.setSpacing(15)  # Espaciado entre items (aumentado)
        self.results_list.setGridSize(QSize(360, 280))  # TamaÃ±o de la celda (thumbnail + texto) - aumentado
        self.results_list.itemDoubleClicked.connect(self.select_video)
        # Hacer que el Ã¡rea de resultados use todo el espacio disponible
        scroll_layout.addWidget(self.results_list, 1)
        
        # Grupo de controles de recorte (similar a Jamendo y YouTube)
        crop_group = QGroupBox("âœ‚ï¸ Recortar Video (Opcional)")
        crop_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        crop_layout = QVBoxLayout(crop_group)

        crop_info_label = QLabel("Especifica el rango de tiempo del video que deseas descargar:")
        crop_info_label.setStyleSheet("color: #a0a0a0; font-size: 9pt;")
        crop_info_label.setWordWrap(True)
        crop_layout.addWidget(crop_info_label)

        # Vista previa del video (reproducción ligera con frames extraídos)
        self.video_preview_label = QLabel()
        self.video_preview_label.setMinimumHeight(200)
        self.video_preview_label.setMaximumHeight(250)
        self.video_preview_label.setStyleSheet("background-color: #0a0a0a; border-radius: 4px;")
        self.video_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_preview_label.setText("Selecciona un video para cargar preview")
        crop_layout.addWidget(self.video_preview_label)

        # Widget de timeline de video (similar a CapCut)
        self.video_timeline = VideoTimelineWidget()
        self.video_timeline.setEnabled(False)
        self.video_timeline.crop_range_changed.connect(self.on_timeline_crop_changed)
        self.video_timeline.position_clicked.connect(self.on_timeline_position_clicked)
        self.video_timeline.position_dragged.connect(self.on_timeline_position_dragged)
        crop_layout.addWidget(self.video_timeline)

        # Controles de reproduccion del preview del timeline
        playback_controls_layout = QHBoxLayout()
        playback_controls_layout.addStretch()

        self.play_btn = QPushButton("️ Play")
        self.play_btn.setEnabled(False)
        self.play_btn.setMaximumWidth(90)
        self.play_btn.clicked.connect(self.toggle_playback)
        playback_controls_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("️ Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMaximumWidth(90)
        self.stop_btn.clicked.connect(self.stop_playback)
        playback_controls_layout.addWidget(self.stop_btn)

        self.play_segment_btn = QPushButton(" Play Segmento")
        self.play_segment_btn.setEnabled(False)
        self.play_segment_btn.setMaximumWidth(150)
        self.play_segment_btn.setToolTip("Reproduce solo el tramo Inicio-Fin del recorte")
        self.play_segment_btn.clicked.connect(self.play_crop_range)
        playback_controls_layout.addWidget(self.play_segment_btn)

        playback_controls_layout.addStretch()
        crop_layout.addLayout(playback_controls_layout)

        crop_controls_layout = QHBoxLayout()

        # Inicio
        start_label = QLabel("Inicio:")
        crop_controls_layout.addWidget(start_label)
        self.video_crop_start = QDoubleSpinBox()
        self.video_crop_start.setMinimum(0.0)
        self.video_crop_start.setMaximum(86400.0)  # MÃ¡ximo 24 horas
        self.video_crop_start.setDecimals(2)
        self.video_crop_start.setSuffix(" s")
        self.video_crop_start.setValue(0.0)
        self.video_crop_start.setEnabled(False)  # Habilitar solo cuando hay video seleccionado
        self.video_crop_start.valueChanged.connect(self.on_crop_start_changed)
        crop_controls_layout.addWidget(self.video_crop_start)

        crop_controls_layout.addStretch()

        # Fin
        end_label = QLabel("Fin:")
        crop_controls_layout.addWidget(end_label)
        self.video_crop_end = QDoubleSpinBox()
        self.video_crop_end.setMinimum(0.0)
        self.video_crop_end.setMaximum(86400.0)  # MÃ¡ximo 24 horas
        self.video_crop_end.setDecimals(2)
        self.video_crop_end.setSuffix(" s")
        self.video_crop_end.setValue(0.0)
        self.video_crop_end.setEnabled(False)  # Habilitar solo cuando hay video seleccionado
        self.video_crop_end.valueChanged.connect(self.on_crop_end_changed)
        crop_controls_layout.addWidget(self.video_crop_end)

        crop_layout.addLayout(crop_controls_layout)

        # Checkbox para habilitar recorte
        self.enable_crop_checkbox = QCheckBox("Habilitar recorte de video")
        self.enable_crop_checkbox.setEnabled(False)
        self.enable_crop_checkbox.stateChanged.connect(self.on_crop_checkbox_changed)
        crop_layout.addWidget(self.enable_crop_checkbox)

        # Layout para botones de recorte
        crop_buttons_layout = QHBoxLayout()

        # Botón para ajustar recorte a duración del segmento
        self.fit_segment_btn = QPushButton(" Ajustar a Segmento")
        self.fit_segment_btn.setEnabled(False)
        self.fit_segment_btn.setToolTip("Ajusta el recorte a la duración del segmento actual")
        self.fit_segment_btn.clicked.connect(self.fit_crop_to_segment)
        crop_buttons_layout.addWidget(self.fit_segment_btn)

        # Botón para resetear recorte
        reset_crop_btn = QPushButton("️ Resetear Recorte")
        reset_crop_btn.setEnabled(False)
        reset_crop_btn.clicked.connect(self.reset_crop_range)
        crop_buttons_layout.addWidget(reset_crop_btn)
        self.reset_crop_btn = reset_crop_btn

        crop_layout.addLayout(crop_buttons_layout)

        scroll_layout.addWidget(crop_group)
        
        # Configurar el scroll area con el contenido
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)  # El Ã¡rea de scroll usa todo el espacio disponible

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.preview_btn = QPushButton("ðŸ‘ï¸ Preview")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self.preview_selected_video)
        self.preview_btn.setToolTip("Previsualizar el video seleccionado")
        buttons_layout.addWidget(self.preview_btn)
        
        self.select_btn = QPushButton("âœ… Seleccionar Video")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.select_current_video)
        buttons_layout.addWidget(self.select_btn)
        
        cancel_btn = QPushButton("âŒ Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        
        scroll_layout.addLayout(buttons_layout)
        
        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)

    def _trim_previous_results_cache(self):
        """Limita cache de búsquedas previas para evitar recarga pesada."""
        if not self._previous_results:
            return

        recent_items = list(self._previous_results.items())[-self._MAX_PREVIOUS_QUERIES:]
        trimmed_cache = {}
        for query, videos in recent_items:
            if not isinstance(videos, list):
                continue
            trimmed_cache[query] = videos[-self._MAX_PREVIOUS_ITEMS_PER_QUERY:]
        self._previous_results = trimmed_cache
    
    def load_previous_results(self):
        """Carga resultados de bÃºsquedas anteriores"""
        if not self._previous_results:
            return

        self._trim_previous_results_cache()
        loaded_count = 0
        recent_items = list(self._previous_results.items())[-self._MAX_PREVIOUS_QUERIES:]

        for _, videos in recent_items:
            for video in videos:
                if loaded_count >= self._MAX_PRELOADED_ITEMS_ON_OPEN:
                    break
                try:
                    if not self._is_video_item(video):
                        continue
                    item = QListWidgetItem()
                    title = video.get('title', 'Video histÃ³rico') or 'Video histÃ³rico'
                    duration = self._normalize_duration(video.get('duration', 0))
                    video['duration'] = duration
                    description = self._clean_text(video.get('description', '') or '')
                    duration_str = self._format_duration(duration)

                    item_text = f"{title[:80]}\n"
                    if description:
                        desc_short = description[:60] + "..." if len(description) > 60 else description
                        item_text += f"ðŸ“ {desc_short}\n"
                    item_text += f"â±ï¸ {duration_str}"

                    item.setText(item_text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setData(Qt.ItemDataRole.UserRole, video)
                    item.setIcon(self._load_video_thumbnail_icon(video))

                    self.results_list.addItem(item)
                    self._queue_video_thumbnail_load(item, video)
                    self.videos.append(video)
                    loaded_count += 1
                except Exception as e:
                    print(f"âš ï¸ Error cargando resultado previo: {e}")
                    continue

            if loaded_count >= self._MAX_PRELOADED_ITEMS_ON_OPEN:
                break
    
    def suggest_query_from_segment(self, segment_data):
        """Sugiere un tÃ©rmino de bÃºsqueda basado en el segmento"""
        narration = segment_data.get('text', '')
        visual_prompt = segment_data.get('visual_prompt', '')
        
        if narration:
            words = narration.split()
            stop_words = {'el', 'la', 'los', 'las', 'un', 'una', 'de', 'en', 'y', 'a', 'que', 'es', 'fue', 'son'}
            keywords = [w for w in words if w.lower() not in stop_words and len(w) > 3][:5]
            if keywords:
                return ' '.join(keywords)
        
        if visual_prompt:
            words = visual_prompt.split()
            keywords = [w for w in words if len(w) > 3][:5]
            if keywords:
                return ' '.join(keywords)
        
        return ""
    
    def perform_search(self):
        """Realiza la bÃºsqueda de videos"""
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "BÃºsqueda VacÃ­a", "Por favor ingresa un tÃ©rmino de bÃºsqueda.")
            return
        
        if not WIKIMEDIA_VIDEO_AVAILABLE:
            QMessageBox.warning(
                self,
                "Wikimedia no disponible",
                "El cliente de Wikimedia no estÃ¡ disponible.\n"
                "AsegÃºrate de que wikimedia_client.py estÃ© en el directorio del proyecto."
            )
            return
        
        if not WikimediaVideoSearchWorker:
            QMessageBox.warning(
                self,
                "Wikimedia no disponible",
                "El worker de bÃºsqueda de Wikimedia no estÃ¡ disponible.\n"
                "AsegÃºrate de que timeline_workers.py estÃ© en el directorio del proyecto."
            )
            return
        
        self._cancel_video_thumbnail_loads()
        self.results_list.clear()
        self.videos = []
        self.select_btn.setEnabled(False)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.search_btn.setEnabled(False)
        
        narration_text = self.segment_data.get('text', '') if self.segment_data else ''
        
        try:
            self.worker = WikimediaVideoSearchWorker(query, narration_text)
            self.worker.finished.connect(self.on_search_finished)
            self.worker.error.connect(self.on_search_error)
            self.worker.progress.connect(lambda msg: self.progress_bar.setFormat(msg))
            self.worker.start()
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.search_btn.setEnabled(True)
            QMessageBox.critical(
                self,
                "Error",
                f"Error al iniciar la bÃºsqueda:\n{str(e)}"
            )
    
    def on_search_finished(self, videos):
        """Callback cuando la bÃºsqueda termina exitosamente"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        
        query = self.search_input.text().strip()
        if query and videos:
            if query not in self._previous_results:
                self._previous_results[query] = []
            existing_urls = {v.get('url') for v in self._previous_results[query]}
            new_videos = [v for v in videos if v.get('url') not in existing_urls]
            self._previous_results[query].extend(new_videos)
            self._previous_results[query] = self._previous_results[query][-self._MAX_PREVIOUS_ITEMS_PER_QUERY:]
            self._trim_previous_results_cache()
        
        self.videos.extend(videos)
        
        # Procesar videos de forma segura con thumbnails y duraciÃ³n
        for video in videos:
            try:
                if not self._is_video_item(video):
                    continue
                
                item = QListWidgetItem()
                title = video.get('title', 'Video histÃ³rico') or 'Video histÃ³rico'
                duration = self._normalize_duration(video.get('duration', 0))
                video['duration'] = duration
                description = self._clean_text(video.get('description', '') or '')
                
                # Limpiar strings para evitar problemas
                if isinstance(title, str):
                    title = title[:80]  # Limitar longitud para que quepa en el item
                
                # Formatear duraciÃ³n de forma mÃ¡s legible
                duration_str = self._format_duration(duration)
                
                # Formatear texto del item con duraciÃ³n prominente
                item_text = f"{title}\n"
                if description:
                    desc_short = description[:60] + "..." if len(description) > 60 else description
                    item_text += f"ðŸ“ {desc_short}\n"
                item_text += f"â±ï¸ {duration_str}"
                
                item.setText(item_text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, video)
                item.setIcon(self._load_video_thumbnail_icon(video))
                
                self.results_list.addItem(item)
                self._queue_video_thumbnail_load(item, video)
            except Exception as e:
                print(f"âš ï¸ Error procesando video: {e}")
                continue
        
        self.on_selection_changed()
    
    def on_search_error(self, error_msg):
        """Callback cuando la bÃºsqueda falla"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        QMessageBox.critical(self, "Error de BÃºsqueda", f"Error al buscar videos:\n{error_msg}")

    def on_selection_changed(self):
        """Habilita/deshabilita el botÃ³n de seleccionar y preview, y actualiza controles de recorte"""
        has_selection = self.results_list.currentItem() is not None
        self.select_btn.setEnabled(has_selection)
        if hasattr(self, 'preview_btn'):
            self.preview_btn.setEnabled(has_selection)

        # Habilitar controles de recorte si hay selecciÃ³n
        if has_selection and hasattr(self, 'enable_crop_checkbox'):
            self.enable_crop_checkbox.setEnabled(True)

            # Obtener duraciÃ³n del video seleccionado
            selected_item = self.results_list.currentItem()
            if selected_item:
                video_data = selected_item.data(Qt.ItemDataRole.UserRole)
                if video_data:
                    video_duration = self._normalize_duration(video_data.get('duration', 0))
                    video_data['duration'] = video_duration
                    video_url = video_data.get('url', '') or video_data.get('video_url', '')

                    if video_duration > 0:
                        # Actualizar valores mÃ¡ximos y establecer fin al final del video
                        if hasattr(self, 'video_crop_start'):
                            self.video_crop_start.setMaximum(video_duration)
                            self.video_crop_start.setValue(0.0)
                        if hasattr(self, 'video_crop_end'):
                            self.video_crop_end.setMaximum(video_duration)
                            self.video_crop_end.setValue(video_duration)
                        if hasattr(self, 'fit_segment_btn'):
                            crop_enabled = hasattr(self, 'enable_crop_checkbox') and self.enable_crop_checkbox.isChecked()
                            self.fit_segment_btn.setEnabled(crop_enabled)
                        if hasattr(self, 'play_btn'):
                            self.play_btn.setEnabled(False)
                            self.play_btn.setText("️ Play")
                        if hasattr(self, 'stop_btn'):
                            self.stop_btn.setEnabled(False)
                        if hasattr(self, 'play_segment_btn'):
                            self.play_segment_btn.setEnabled(False)
                        self.playback_position = 0.0
                        self.preview_frames = []
                        if hasattr(self, 'video_preview_label'):
                            self.video_preview_label.setText("Cargando preview del video...")
                            self.video_preview_label.setPixmap(QPixmap())
                        # Actualizar el timeline widget con la duraciÃ³n del video
                        if hasattr(self, 'video_timeline'):
                            self.video_timeline.set_video_duration(video_duration)
                            self.video_timeline.set_current_position(0.0)
                            self.video_timeline.set_crop_range(0.0, video_duration)
                            self.video_timeline.setEnabled(True)

                            # Iniciar descarga y extracciÃ³n de frames si es un video diferente
                            if video_url and video_url != self._current_video_url:
                                self._start_frame_extraction(video_url, 'wikimedia')
                    else:
                        if hasattr(self, 'fit_segment_btn'):
                            self.fit_segment_btn.setEnabled(False)
                        if hasattr(self, 'play_btn'):
                            self.play_btn.setEnabled(False)
                        if hasattr(self, 'stop_btn'):
                            self.stop_btn.setEnabled(False)
                        if hasattr(self, 'play_segment_btn'):
                            self.play_segment_btn.setEnabled(False)
                        self._close_preview_video_clip()
                        self.preview_video_path = None
                        self.preview_frames = []
                        if hasattr(self, 'video_preview_label'):
                            self.video_preview_label.setPixmap(QPixmap())
                            self.video_preview_label.setText("Preview no disponible para este video")
                        # Sin duraciÃ³n conocida, deshabilitar timeline
                        if hasattr(self, 'video_timeline'):
                            self.video_timeline.set_video_duration(0)
                            self.video_timeline.setEnabled(False)
        else:
            self.stop_playback()
            if hasattr(self, 'enable_crop_checkbox'):
                self.enable_crop_checkbox.setEnabled(False)
                self.enable_crop_checkbox.setChecked(False)
            if hasattr(self, 'video_crop_start'):
                self.video_crop_start.setEnabled(False)
            if hasattr(self, 'video_crop_end'):
                self.video_crop_end.setEnabled(False)
            if hasattr(self, 'play_btn'):
                self.play_btn.setEnabled(False)
                self.play_btn.setText("️ Play")
            if hasattr(self, 'stop_btn'):
                self.stop_btn.setEnabled(False)
            if hasattr(self, 'play_segment_btn'):
                self.play_segment_btn.setEnabled(False)
            self._close_preview_video_clip()
            self.preview_video_path = None
            self.preview_frames = []
            if hasattr(self, 'video_preview_label'):
                self.video_preview_label.setPixmap(QPixmap())
                self.video_preview_label.setText("Selecciona un video para cargar preview")
            if hasattr(self, 'fit_segment_btn'):
                self.fit_segment_btn.setEnabled(False)
            if hasattr(self, 'reset_crop_btn'):
                self.reset_crop_btn.setEnabled(False)
            # Resetear timeline cuando no hay selecciÃ³n
            if hasattr(self, 'video_timeline'):
                self.video_timeline.set_video_duration(0)
                self.video_timeline.set_video_frames([])
                self.video_timeline.setEnabled(False)
            # Cancelar extracciÃ³n en progreso
            self._cancel_frame_extraction()

    def _start_frame_extraction(self, video_url, video_source):
        """Inicia la extracciÃ³n de frames del video en segundo plano"""
        self.stop_playback()
        self._close_preview_video_clip()
        self.preview_video_path = None
        self._cancel_frame_extraction()
        self._current_video_url = video_url

        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_video_frames([])
            self.video_timeline.set_loading_message("Descargando video para preview...")

        if not VideoFrameExtractorWorker:
            if hasattr(self, 'video_timeline'):
                self.video_timeline.clear_loading_message()
            print("âš ï¸ VideoFrameExtractorWorker no disponible. Se omite preview de frames.")
            return

        self.frame_extractor_worker = VideoFrameExtractorWorker(video_url, video_source, num_frames=15)
        self.frame_extractor_worker.finished.connect(self._on_frames_extracted)
        self.frame_extractor_worker.error.connect(self._on_frame_extraction_error)
        self.frame_extractor_worker.progress.connect(self._on_frame_extraction_progress)
        self.frame_extractor_worker.start()

    def _cancel_frame_extraction(self):
        """Cancela la extracciÃ³n de frames en progreso"""
        if self.frame_extractor_worker and self.frame_extractor_worker.isRunning():
            self.frame_extractor_worker.terminate()
            self.frame_extractor_worker.wait(1000)
        self.frame_extractor_worker = None
        self._current_video_url = None

    def _on_frames_extracted(self, video_path, frames):
        """Callback cuando se extraen los frames exitosamente"""
        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()
            self.video_timeline.set_video_frames(frames)

        self.preview_video_path = video_path if isinstance(video_path, str) and video_path else None
        self._close_preview_video_clip()
        self.preview_frames = frames or []
        if hasattr(self, 'play_btn'):
            self.play_btn.setEnabled(bool(self.preview_frames))
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(False)
        self._update_play_segment_button_state()
        self.playback_position = self._normalize_duration(getattr(self.video_timeline, 'current_position', 0)) if hasattr(self, 'video_timeline') else 0.0
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

    def _on_frame_extraction_error(self, error_msg):
        """Callback cuando falla la extracciÃ³n de frames"""
        print(f"âš ï¸ Error extrayendo frames: {error_msg}")
        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()
        self._close_preview_video_clip()
        self.preview_video_path = None
        self.preview_frames = []
        if hasattr(self, 'play_btn'):
            self.play_btn.setEnabled(False)
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(False)
        if hasattr(self, 'play_segment_btn'):
            self.play_segment_btn.setEnabled(False)
        if hasattr(self, 'video_preview_label'):
            self.video_preview_label.setPixmap(QPixmap())
            self.video_preview_label.setText("Preview no disponible para este video")

    def _on_frame_extraction_progress(self, message):
        """Callback para actualizar el progreso de extracciÃ³n"""
        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_loading_message(message)

    def _close_preview_video_clip(self):
        """Cierra clip de preview si está abierto."""
        try:
            if self.preview_video_clip:
                self.preview_video_clip.close()
        except Exception:
            pass
        finally:
            self.preview_video_clip = None

    def _open_preview_video_clip(self):
        """Abre (lazy) el clip de preview para renderizado fluido."""
        if self.preview_video_clip:
            return self.preview_video_clip
        if not self.preview_video_path or not os.path.exists(self.preview_video_path):
            return None
        try:
            from moviepy.editor import VideoFileClip
            self.preview_video_clip = VideoFileClip(self.preview_video_path)
            return self.preview_video_clip
        except Exception as open_err:
            print(f"️ No se pudo abrir clip de preview: {open_err}")
            self.preview_video_clip = None
            return None

    def _render_preview_frame_from_video(self, position_seconds):
        """Renderiza frame real del video según la posición actual."""
        if not hasattr(self, 'video_preview_label'):
            return False

        clip = self._open_preview_video_clip()
        if not clip:
            return False

        try:
            import io
            from PIL import Image

            safe_time = max(0.0, float(position_seconds or 0.0))
            clip_duration = self._normalize_duration(getattr(clip, 'duration', 0))
            if clip_duration > 0:
                safe_time = min(safe_time, max(0.0, clip_duration - 0.001))

            frame = clip.get_frame(safe_time)
            pil_image = Image.fromarray(frame.astype('uint8'), 'RGB')

            label_size = self.video_preview_label.size()
            if label_size.width() > 0 and label_size.height() > 0:
                pil_image.thumbnail((label_size.width(), label_size.height()), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            pil_image.save(buffer, format='PNG')
            buffer.seek(0)

            pixmap = QPixmap()
            if not pixmap.loadFromData(buffer.getvalue()) or pixmap.isNull():
                return False

            self.video_preview_label.setText("")
            self.video_preview_label.setPixmap(pixmap)
            return True
        except Exception:
            return False

    def _render_preview_frame(self, position_seconds):
        """Renderiza en QLabel el frame más cercano a la posición actual."""
        if not hasattr(self, 'video_preview_label'):
            return

        if not self.preview_frames:
            self.video_preview_label.setPixmap(QPixmap())
            self.video_preview_label.setText("Preview no disponible para este video")
            return

        if not hasattr(self, 'video_timeline') or not self.video_timeline:
            return

        duration = self._normalize_duration(getattr(self.video_timeline, 'duration', 0))
        if duration <= 0:
            return

        safe_position = self._normalize_duration(position_seconds)
        ratio = 0.0 if duration <= 0 else min(1.0, max(0.0, safe_position / duration))
        frame_idx = int(round(ratio * (len(self.preview_frames) - 1)))
        frame_idx = max(0, min(frame_idx, len(self.preview_frames) - 1))
        frame = self.preview_frames[frame_idx]

        if frame and not frame.isNull():
            label_size = self.video_preview_label.size()
            scaled = frame.scaled(
                label_size.width(),
                label_size.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.video_preview_label.setText("")
            self.video_preview_label.setPixmap(scaled)

    def _get_crop_bounds(self):
        """Obtiene y normaliza el rango Inicio-Fin del recorte actual."""
        start = 0.0
        end = 0.0
        if hasattr(self, 'video_crop_start'):
            start = self._normalize_duration(self.video_crop_start.value())
        if hasattr(self, 'video_crop_end'):
            end = self._normalize_duration(self.video_crop_end.value())
        if end < start:
            start, end = end, start
        return start, end

    def _is_crop_playback_available(self):
        """Determina si se puede reproducir el segmento recortado."""
        has_preview = bool(self.preview_frames or self.preview_video_path)
        if not has_preview:
            return False
        if not hasattr(self, 'enable_crop_checkbox') or not self.enable_crop_checkbox.isChecked():
            return False
        if not hasattr(self, 'video_timeline') or not self.video_timeline:
            return False

        video_duration = self._normalize_duration(getattr(self.video_timeline, 'duration', 0))
        if video_duration <= 0:
            return False

        start, end = self._get_crop_bounds()
        if end - start <= 0.05:
            return False
        if start >= video_duration:
            return False
        return True

    def _update_play_segment_button_state(self):
        """Actualiza estado del botón Play Segmento."""
        if hasattr(self, 'play_segment_btn'):
            self.play_segment_btn.setEnabled(self._is_crop_playback_available())

    def play_crop_range(self):
        """Reproduce solo el tramo de recorte Inicio-Fin."""
        if not self._is_crop_playback_available():
            QMessageBox.warning(
                self,
                "Segmento no disponible",
                "Activa el recorte y define un rango válido para reproducir el segmento."
            )
            return

        if not hasattr(self, 'video_timeline') or not self.video_timeline:
            return

        if self.is_playing:
            self.stop_playback()

        start, end = self._get_crop_bounds()
        video_duration = self._normalize_duration(getattr(self.video_timeline, 'duration', 0))
        start = max(0.0, min(start, video_duration))
        end = max(start + 0.05, min(end, video_duration))

        self._playing_crop_range = True
        self._crop_play_start = start
        self._crop_play_end = end
        self.playback_position = start
        self.video_timeline.set_current_position(start)
        if not self._render_preview_frame_from_video(start):
            self._render_preview_frame(start)

        if self.playback_timer is None:
            self.playback_timer = QTimer(self)
            self.playback_timer.timeout.connect(self._advance_timeline_playback)

        self.is_playing = True
        interval_ms = max(16, int(round(1000.0 / max(1.0, self.preview_playback_fps))))
        self.playback_timer.start(interval_ms)
        if hasattr(self, 'play_btn'):
            self.play_btn.setText("️ Pause")
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(True)

    def toggle_playback(self):
        """Alterna reproducción/pausa del cursor de preview sobre el timeline."""
        if not hasattr(self, 'video_timeline') or not self.video_timeline:
            return

        if not self.preview_frames and not self.preview_video_path:
            QMessageBox.warning(self, "Sin preview", "Espera a que se carguen los frames del video.")
            return

        video_duration = self._normalize_duration(getattr(self.video_timeline, 'duration', 0))
        if video_duration <= 0:
            QMessageBox.warning(self, "Sin video", "Primero selecciona un video con duración válida.")
            return

        if self.is_playing:
            self.stop_playback()
            return

        # Play normal: desactivar modo reproducción por segmento.
        self._playing_crop_range = False

        if self.playback_position < 0 or self.playback_position >= video_duration:
            self.playback_position = self._normalize_duration(getattr(self.video_timeline, 'current_position', 0))
            if self.playback_position >= video_duration:
                self.playback_position = 0.0
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

        if self.playback_timer is None:
            self.playback_timer = QTimer(self)
            self.playback_timer.timeout.connect(self._advance_timeline_playback)

        self.is_playing = True
        interval_ms = max(16, int(round(1000.0 / max(1.0, self.preview_playback_fps))))
        self.playback_timer.start(interval_ms)
        if hasattr(self, 'play_btn'):
            self.play_btn.setText("️ Pause")
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(True)

    def stop_playback(self):
        """Detiene la reproducción del cursor en el timeline."""
        if self.playback_timer:
            self.playback_timer.stop()
        self.is_playing = False
        self._playing_crop_range = False
        self._crop_play_start = 0.0
        self._crop_play_end = 0.0
        if hasattr(self, 'play_btn'):
            self.play_btn.setText("️ Play")
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(False)
        self._update_play_segment_button_state()

    def _advance_timeline_playback(self):
        """Avanza la línea de reproducción azul durante el preview."""
        if not self.is_playing or not hasattr(self, 'video_timeline') or not self.video_timeline:
            return

        video_duration = self._normalize_duration(getattr(self.video_timeline, 'duration', 0))
        if video_duration <= 0:
            self.stop_playback()
            return

        step = 1.0 / max(1.0, self.preview_playback_fps)
        next_position = self.playback_position + step

        if self._playing_crop_range:
            crop_end = self._normalize_duration(self._crop_play_end)
            crop_start = self._normalize_duration(self._crop_play_start)
            if crop_end <= crop_start:
                self.stop_playback()
                return
            if next_position >= crop_end:
                self.playback_position = crop_end
                self.video_timeline.set_current_position(self.playback_position)
                if not self._render_preview_frame_from_video(self.playback_position):
                    self._render_preview_frame(self.playback_position)
                self.stop_playback()
                return
        else:
            if next_position >= video_duration:
                self.playback_position = video_duration
                self.video_timeline.set_current_position(self.playback_position)
                if not self._render_preview_frame_from_video(self.playback_position):
                    self._render_preview_frame(self.playback_position)
                self.stop_playback()
                return

        self.playback_position = next_position
        self.video_timeline.set_current_position(self.playback_position)
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

    def on_timeline_position_clicked(self, position):
        """Mueve la barra azul al hacer click en cualquier parte del timeline."""
        self.playback_position = self._normalize_duration(position)
        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_current_position(self.playback_position)
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

    def on_timeline_position_dragged(self, position):
        """Sincroniza la posición cuando el usuario arrastra la barra azul."""
        self.playback_position = self._normalize_duration(position)
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

    def on_timeline_crop_changed(self, start_time, end_time):
        """Callback cuando se cambia el rango de recorte desde el timeline"""
        if hasattr(self, 'video_crop_start'):
            self.video_crop_start.blockSignals(True)
            self.video_crop_start.setValue(start_time)
            self.video_crop_start.blockSignals(False)
        if hasattr(self, 'video_crop_end'):
            self.video_crop_end.blockSignals(True)
            self.video_crop_end.setValue(end_time)
            self.video_crop_end.blockSignals(False)
        self._update_play_segment_button_state()

    def on_crop_start_changed(self, value):
        """Callback cuando se cambia el inicio desde el spinbox"""
        if hasattr(self, 'video_timeline'):
            end_time = self.video_crop_end.value() if hasattr(self, 'video_crop_end') else self.video_timeline.end_time
            self.video_timeline.set_crop_range(value, end_time)
        self._update_play_segment_button_state()

    def on_crop_end_changed(self, value):
        """Callback cuando se cambia el fin desde el spinbox"""
        if hasattr(self, 'video_timeline'):
            start_time = self.video_crop_start.value() if hasattr(self, 'video_crop_start') else self.video_timeline.start_time
            self.video_timeline.set_crop_range(start_time, value)
        self._update_play_segment_button_state()

    def on_crop_checkbox_changed(self, state):
        """Habilita/deshabilita los controles de recorte segÃºn el checkbox"""
        enabled = (state == Qt.CheckState.Checked.value)
        has_selection = self.results_list.currentItem() is not None
        if hasattr(self, 'video_crop_start'):
            self.video_crop_start.setEnabled(enabled)
        if hasattr(self, 'video_crop_end'):
            self.video_crop_end.setEnabled(enabled)
        if hasattr(self, 'fit_segment_btn'):
            self.fit_segment_btn.setEnabled(enabled and has_selection)
        if hasattr(self, 'reset_crop_btn'):
            self.reset_crop_btn.setEnabled(enabled)
        self._update_play_segment_button_state()

    def reset_crop_range(self):
        """Resetea los valores de recorte a los valores por defecto"""
        selected_item = self.results_list.currentItem()
        if selected_item:
            video_data = selected_item.data(Qt.ItemDataRole.UserRole)
            if video_data:
                video_duration = self._normalize_duration(video_data.get('duration', 0))
                video_data['duration'] = video_duration
                if hasattr(self, 'video_crop_start'):
                    self.video_crop_start.setValue(0.0)
                if hasattr(self, 'video_crop_end'):
                    self.video_crop_end.setValue(video_duration if video_duration > 0 else 0.0)
                if hasattr(self, 'video_timeline'):
                    self.video_timeline.set_crop_range(0.0, video_duration if video_duration > 0 else 0.0)

    def fit_crop_to_segment(self):
        """Ajusta el recorte para que coincida con la duraciÃ³n del segmento"""
        # Obtener la duración del segmento actual
        segment_duration = 0.0
        if hasattr(self, 'segment_data') and self.segment_data:
            segment_duration = self._normalize_duration(self.segment_data.get('duration', 0))
            if segment_duration <= 0:
                start = self._normalize_duration(self.segment_data.get('start', 0))
                end = self._normalize_duration(self.segment_data.get('end', 0))
                if end > start:
                    segment_duration = end - start

        if segment_duration <= 0:
            QMessageBox.warning(
                self,
                "Sin duración de segmento",
                "No se pudo determinar la duración del segmento.\n\n"
                f"Datos del segmento: {self.segment_data}\n\n"
                "Asegúrate de que el segmento tenga una duración definida."
            )
            return

        # Obtener la duración total del video
        video_duration = 0.0
        if hasattr(self, 'video_timeline'):
            video_duration = self._normalize_duration(getattr(self.video_timeline, 'duration', 0))

        if video_duration <= 0:
            selected_item = self.results_list.currentItem()
            if selected_item:
                video_data = selected_item.data(Qt.ItemDataRole.UserRole) or {}
                video_duration = self._normalize_duration(video_data.get('duration', 0))

        if video_duration <= 0:
            QMessageBox.warning(self, "Sin video", "Primero selecciona un video con duración válida.")
            return

        if segment_duration > video_duration:
            QMessageBox.warning(
                self,
                "Segmento muy largo",
                f"La duración del segmento ({segment_duration:.1f}s) es mayor que la del video ({video_duration:.1f}s).\n\n"
                "Se usará todo el video."
            )
            segment_duration = video_duration

        # Tomar posición actual del timeline como punto de inicio
        current_position = 0.0
        if hasattr(self, 'video_timeline'):
            current_position = self._normalize_duration(getattr(self.video_timeline, 'current_position', 0))

        new_start = current_position
        new_end = new_start + segment_duration

        # Ajustar si sobrepasa el final del video
        if new_end > video_duration:
            new_end = video_duration
            new_start = max(0.0, video_duration - segment_duration)

        # Aplicar recorte
        if hasattr(self, 'video_crop_start'):
            self.video_crop_start.setValue(new_start)
        if hasattr(self, 'video_crop_end'):
            self.video_crop_end.setValue(new_end)
        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_crop_range(new_start, new_end)

        print(f" Recorte ajustado a duración del segmento: {new_start:.1f}s - {new_end:.1f}s ({segment_duration:.1f}s)")

    def preview_selected_video(self):
        """Abre un diÃ¡logo para previsualizar el video seleccionado"""
        selected_item = self.results_list.currentItem()
        if not selected_item:
            return
        
        video_data = selected_item.data(Qt.ItemDataRole.UserRole)
        if not video_data:
            QMessageBox.warning(self, "Error", "No se pudo obtener la informaciÃ³n del video.")
            return
        
        # Abrir diÃ¡logo de preview con manejo de errores robusto
        try:
            preview_dialog = VideoPreviewDialog(self, video_data)
            preview_dialog.exec()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo abrir el preview del video:\n{str(e)}\n\n"
                "Puedes usar 'Abrir en Navegador' desde el diÃ¡logo de selecciÃ³n."
            )
    
    def select_current_video(self):
        """Selecciona el video actualmente resaltado"""
        selected_item = self.results_list.currentItem()
        if selected_item:
            self.select_video(selected_item)
    
    def select_video(self, item):
        """Descarga el video seleccionado y cierra el diÃ¡logo"""
        video_data = item.data(Qt.ItemDataRole.UserRole)
        if not video_data:
            QMessageBox.warning(self, "Error", "No se pudo obtener la informaciÃ³n del video.")
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.select_btn.setEnabled(False)
        
        try:
            from media.wikimedia_client import WikimediaClient
            from pathlib import Path
            import tempfile
            
            # Intentar obtener la carpeta del proyecto actual desde el parent
            project_video_dir = None
            parent = self.parent()
            while parent:
                if hasattr(parent, 'studio_tab') and hasattr(parent.studio_tab, 'current_project_path'):
                    if parent.studio_tab.current_project_path:
                        project_path_obj = Path(parent.studio_tab.current_project_path)
                        project_folder = project_path_obj.parent
                        project_video_dir = project_folder / "videos"
                        if not project_video_dir.exists():
                            project_video_dir = project_folder / "temp"
                        project_video_dir.mkdir(parents=True, exist_ok=True)
                        print(f"[Wikimedia] Usando carpeta del proyecto: {project_video_dir}")
                        break
                elif hasattr(parent, 'timeline_editor') and hasattr(parent.timeline_editor, 'parent'):
                    parent2 = parent.timeline_editor.parent()
                    if parent2 and hasattr(parent2, 'studio_tab') and hasattr(parent2.studio_tab, 'current_project_path'):
                        if parent2.studio_tab.current_project_path:
                            project_path_obj = Path(parent2.studio_tab.current_project_path)
                            project_folder = project_path_obj.parent
                            project_video_dir = project_folder / "videos"
                            if not project_video_dir.exists():
                                project_video_dir = project_folder / "temp"
                            project_video_dir.mkdir(parents=True, exist_ok=True)
                            print(f"[Wikimedia] Usando carpeta del proyecto: {project_video_dir}")
                            break
                parent = parent.parent()
            
            # Si no hay proyecto, usar carpeta temporal local (no en Google Drive)
            if not project_video_dir:
                temp_base = Path(tempfile.gettempdir())
                wikimedia_video_dir = temp_base / "video_optimizer" / "wikimedia_downloads"
                wikimedia_video_dir.mkdir(parents=True, exist_ok=True)
                print(f"[Wikimedia] Usando carpeta temporal local: {wikimedia_video_dir}")
            else:
                wikimedia_video_dir = project_video_dir
            
            video_title = video_data.get('title', 'wikimedia_video')
            # Limpiar tÃ­tulo para nombre de archivo
            invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
            for char in invalid_chars:
                video_title = video_title.replace(char, '_')
            video_title = '_'.join(video_title.split())[:50]
            
            video_url = video_data.get('url', '')
            filename = f"wikimedia_{hash(video_url) % 100000}_{video_title}.mp4"
            output_path = wikimedia_video_dir / filename
            
            # Descargar video
            client = WikimediaClient()
            downloaded_path = client.download_video(video_data, str(output_path))
            
            if downloaded_path and os.path.exists(downloaded_path):
                # Convertir a ruta absoluta
                downloaded_path = os.path.abspath(downloaded_path)
                print(f"âœ… Video descargado exitosamente en: {downloaded_path}")
                
                # Helpers para procesar video de forma segura (sin escribir sobre el mismo archivo abierto)
                def _probe_video_duration(path_to_probe):
                    try:
                        from moviepy.editor import VideoFileClip
                        probe_clip = VideoFileClip(path_to_probe)
                        probed_duration = self._normalize_duration(probe_clip.duration)
                        probe_clip.close()
                        return probed_duration
                    except Exception as probe_error:
                        print(f"️ Error verificando duración del video: {probe_error}")
                        return 0.0

                def _rewrite_video_safely(build_processed_clip, label):
                    """
                    build_processed_clip: función que recibe source_clip y devuelve clip procesado.
                    """
                    temp_processed_path = str(
                        Path(downloaded_path).with_name(
                            f"{Path(downloaded_path).stem}_{label}_{int(time.time() * 1000)}.mp4"
                        )
                    )
                    source_clip = None
                    processed_clip = None
                    try:
                        from moviepy.editor import VideoFileClip

                        source_clip = VideoFileClip(downloaded_path)
                        processed_clip = build_processed_clip(source_clip)
                        if processed_clip is None:
                            raise RuntimeError("No se pudo construir el clip procesado")

                        write_kwargs = {
                            'codec': 'libx264',
                            'audio_codec': 'aac',
                            'verbose': False,
                            'logger': None
                        }
                        source_fps = getattr(source_clip, 'fps', 0) or 0
                        if source_fps > 0:
                            write_kwargs['fps'] = float(source_fps)

                        processed_clip.write_videofile(temp_processed_path, **write_kwargs)
                        processed_clip.close()
                        processed_clip = None
                        source_clip.close()
                        source_clip = None

                        # Reemplazo atómico del archivo final
                        os.replace(temp_processed_path, downloaded_path)
                        return True
                    except Exception as process_error:
                        print(f"️ Error procesando video ({label}): {process_error}")
                        return False
                    finally:
                        try:
                            if processed_clip:
                                processed_clip.close()
                        except Exception:
                            pass
                        try:
                            if source_clip:
                                source_clip.close()
                        except Exception:
                            pass
                        try:
                            if os.path.exists(temp_processed_path):
                                os.remove(temp_processed_path)
                        except Exception:
                            pass

                video_duration = _probe_video_duration(downloaded_path)
                print(f" Duración del video descargado: {video_duration:.2f} segundos")
                
                # Verificar si el recorte estÃ¡ habilitado
                crop_enabled = False
                crop_start = 0.0
                crop_end = video_duration
                
                if hasattr(self, 'enable_crop_checkbox') and self.enable_crop_checkbox.isChecked():
                    if hasattr(self, 'video_crop_start') and hasattr(self, 'video_crop_end'):
                        crop_start = self.video_crop_start.value()
                        crop_end = self.video_crop_end.value()
                        
                        # Validar rango de recorte
                        if crop_start < 0:
                            crop_start = 0.0
                        if crop_end > video_duration:
                            crop_end = video_duration
                        if crop_start >= crop_end:
                            QMessageBox.warning(
                                self,
                                "Rango InvÃ¡lido",
                                f"El tiempo de inicio ({crop_start:.2f}s) debe ser menor que el tiempo de fin ({crop_end:.2f}s).\n\n"
                                "Se descargarÃ¡ el video completo."
                            )
                            crop_enabled = False
                        else:
                            crop_enabled = True
                            print(f"âœ‚ï¸ Recorte habilitado: {crop_start:.2f}s - {crop_end:.2f}s")
                
                # Aplicar recorte si está habilitado
                if crop_enabled and crop_start >= 0 and crop_end > crop_start and crop_end <= video_duration:
                    crop_target_duration = max(0.0, crop_end - crop_start)
                    crop_ok = _rewrite_video_safely(
                        lambda source_clip: source_clip.subclip(crop_start, crop_end),
                        "crop"
                    )
                    if crop_ok:
                        video_duration = _probe_video_duration(downloaded_path)
                        print(
                            f"️ Video recortado ({crop_start:.2f}s - {crop_end:.2f}s), "
                            f"duración final: {video_duration:.2f}s (objetivo {crop_target_duration:.2f}s)"
                        )
                    else:
                        QMessageBox.warning(
                            self,
                            "Advertencia",
                            "No se pudo recortar el video.\n\nSe mantendrá el video completo."
                        )
                
                # NO ajustar automÃ¡ticamente la duraciÃ³n - descargar el video completo
                # El usuario puede ajustar la duraciÃ³n despuÃ©s si lo desea
                # Solo ajustar si el segmento tiene una duraciÃ³n especÃ­fica Y el usuario lo solicita
                segment_duration = self._normalize_duration(self.segment_data.get('duration', 0))
                if segment_duration <= 0:
                    segment_start = self._normalize_duration(self.segment_data.get('start', 0))
                    segment_end = self._normalize_duration(self.segment_data.get('end', 0))
                    if segment_end > segment_start:
                        segment_duration = segment_end - segment_start

                # Si el recorte coincide con el segmento (caso típico de "Ajustar a Segmento"),
                # forzar duración final exacta para evitar congelamiento por desajuste.
                if crop_enabled and segment_duration > 0:
                    selected_crop_duration = max(0.0, crop_end - crop_start)
                    if abs(selected_crop_duration - segment_duration) <= 0.25:
                        if video_duration < segment_duration - 0.10:
                            try:
                                from moviepy.editor import vfx
                                from moviepy.audio.fx.all import audio_loop

                                def _build_fit_loop(source_clip):
                                    looped = source_clip.fx(vfx.loop, duration=segment_duration)
                                    if source_clip.audio:
                                        looped = looped.set_audio(audio_loop(source_clip.audio, duration=segment_duration))
                                    return looped

                                if _rewrite_video_safely(_build_fit_loop, "fit_loop"):
                                    video_duration = _probe_video_duration(downloaded_path)
                            except Exception as fit_loop_error:
                                print(f"️ Error corrigiendo duración (fit loop): {fit_loop_error}")
                        elif video_duration > segment_duration + 0.10:
                            if _rewrite_video_safely(
                                lambda source_clip: source_clip.subclip(0, segment_duration),
                                "fit_trim"
                            ):
                                video_duration = _probe_video_duration(downloaded_path)
                
                # Si el segmento tiene duraciÃ³n y el video es mÃ¡s largo, preguntar al usuario
                # (solo si no se aplicÃ³ recorte)
                if not crop_enabled and segment_duration > 0 and video_duration > segment_duration:
                    reply = QMessageBox.question(
                        self,
                        "Ajustar DuraciÃ³n",
                        f"El video descargado tiene {video_duration:.1f}s de duraciÃ³n.\n"
                        f"El segmento requiere {segment_duration:.1f}s.\n\n"
                        f"Â¿Deseas cortar el video a la duraciÃ³n del segmento?\n\n"
                        f"â€¢ SÃ­: Cortar a {segment_duration:.1f}s\n"
                        f"â€¢ No: Mantener el video completo ({video_duration:.1f}s)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        trim_ok = _rewrite_video_safely(
                            lambda source_clip: source_clip.subclip(0, min(segment_duration, source_clip.duration)),
                            "segment_trim"
                        )
                        if trim_ok:
                            video_duration = _probe_video_duration(downloaded_path)
                            print(f"️ Video cortado a {video_duration:.1f}s para ajustar al segmento")
                        else:
                            QMessageBox.warning(
                                self,
                                "Advertencia",
                                "No se pudo cortar el video.\n\nSe mantendrá el video completo."
                            )
                elif not crop_enabled and segment_duration > 0 and video_duration < segment_duration:
                    # Si el video es mÃ¡s corto que el segmento, preguntar si hacer loop
                    reply = QMessageBox.question(
                        self,
                        "Extender DuraciÃ³n",
                        f"El video descargado tiene {video_duration:.1f}s de duraciÃ³n.\n"
                        f"El segmento requiere {segment_duration:.1f}s.\n\n"
                        f"Â¿Deseas hacer loop del video para alcanzar la duraciÃ³n del segmento?\n\n"
                        f"â€¢ SÃ­: Repetir el video hasta {segment_duration:.1f}s\n"
                        f"â€¢ No: Mantener el video original ({video_duration:.1f}s)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )

                    if reply == QMessageBox.StandardButton.Yes:
                        try:
                            from moviepy.editor import vfx
                            from moviepy.audio.fx.all import audio_loop

                            def _build_looped(source_clip):
                                looped = source_clip.fx(vfx.loop, duration=segment_duration)
                                if source_clip.audio:
                                    looped = looped.set_audio(audio_loop(source_clip.audio, duration=segment_duration))
                                return looped

                            loop_ok = _rewrite_video_safely(_build_looped, "segment_loop")
                            if loop_ok:
                                video_duration = _probe_video_duration(downloaded_path)
                                print(f" Video extendido a {video_duration:.1f}s mediante loop")
                            else:
                                QMessageBox.warning(
                                    self,
                                    "Advertencia",
                                    "No se pudo extender el video.\n\nSe mantendrá el video original."
                                )
                        except Exception as e:
                            print(f"️ Error extendiendo video: {e}")
                            QMessageBox.warning(
                                self,
                                "Advertencia",
                                f"No se pudo extender el video:\n{str(e)}\n\n"
                                "Se mantendrá el video original."
                            )

                self.selected_video_path = downloaded_path
                print(f"ðŸ“ Ruta asignada al segmento: {self.selected_video_path}")

                # Save attribution for Wikimedia Commons video
                if ATTRIBUTION_AVAILABLE and get_attribution_manager:
                    try:
                        attr_manager = get_attribution_manager()
                        if attr_manager.add_attribution(video_data, source='wikimedia'):
                            print(f"ðŸ“œ Attribution saved for: {video_data.get('title', 'Unknown')}")
                    except Exception as attr_error:
                        print(f"âš ï¸ Could not save attribution: {attr_error}")

                self.progress_bar.setVisible(False)
                self.accept()
            else:
                self.progress_bar.setVisible(False)
                self.select_btn.setEnabled(True)
                QMessageBox.critical(self, "Error", "No se pudo descargar el video.")
        
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.select_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", f"Error descargando video:\n{str(e)}")
    
    def closeEvent(self, event):
        """Limpia recursos al cerrar el diÃ¡logo"""
        self._closing = True
        self.stop_playback()
        self._close_preview_video_clip()
        self._cancel_video_thumbnail_loads()
        try:
            # Detener worker si estÃ¡ ejecutÃ¡ndose
            if self.worker and self.worker.isRunning():
                self.worker.requestInterruption()
                self.worker.wait(250)
                if self.worker.isRunning():
                    self.worker.terminate()
                    self.worker.wait(1000)  # Esperar hasta 1 segundo
            # Detener frame extractor worker si estÃ¡ ejecutÃ¡ndose
            if hasattr(self, 'frame_extractor_worker') and self.frame_extractor_worker and self.frame_extractor_worker.isRunning():
                self.frame_extractor_worker.requestInterruption()
                self.frame_extractor_worker.wait(250)
                if self.frame_extractor_worker.isRunning():
                    self.frame_extractor_worker.terminate()
                    self.frame_extractor_worker.wait(1000)
        except Exception as e:
            print(f"âš ï¸ Error limpiando workers: {e}")
        finally:
            event.accept()


# ========== INTERNET ARCHIVE VIDEO SEARCH CLASSES ==========
