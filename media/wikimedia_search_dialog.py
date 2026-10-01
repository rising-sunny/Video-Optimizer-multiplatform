# wikimedia_search_dialog.py
"""
DiÃ¡logo WikimediaSearchDialog.
ExtraÃ­do de timeline_editor_widget.py para mejorar la organizaciÃ³n del cÃ³digo.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QMessageBox, QScrollArea, QWidget, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QIcon
from pathlib import Path
import os
import requests
import warnings
import hashlib
import time
from urllib.parse import urlparse, quote, unquote
from io import BytesIO

try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    Image = None
    PIL_AVAILABLE = False


class ThumbnailDownloadWorker(QThread):
    """Descarga una miniatura fuera del hilo de UI."""
    finished = pyqtSignal(int, str, int, object, str, str)  # token, url, status, bytes|None, retry_after, error

    def __init__(
        self,
        token,
        image_url,
        timeout=10,
        is_tiff=False,
        image_title="",
        debug_tiff=False
    ):
        super().__init__()
        self.token = token
        self.image_url = image_url
        self.timeout = timeout
        self.is_tiff = bool(is_tiff)
        self.image_title = image_title or ""
        self.debug_tiff = bool(debug_tiff)

    def run(self):
        if self.isInterruptionRequested():
            return
        if self.debug_tiff and self.is_tiff:
            print(
                f"[TIFF-DEBUG] worker:start | token={self.token} | "
                f"timeout={self.timeout}s | url={self.image_url[:180]} | "
                f"title={self.image_title[:90]}"
            )
        headers = {
            'User-Agent': 'VideoOptimizerPro/1.0',
            'Accept': 'image/*,*/*;q=0.8'
        }
        if self.isInterruptionRequested():
            return
        try:
            response = requests.get(self.image_url, timeout=self.timeout, headers=headers)
            if self.isInterruptionRequested():
                return
            retry_after = response.headers.get('Retry-After', '')
            status = int(response.status_code)
            if self.debug_tiff and self.is_tiff:
                print(
                    f"[TIFF-DEBUG] worker:response | token={self.token} | "
                    f"attempt=1/1 | status={status} | "
                    f"retry_after={retry_after or '-'} | "
                    f"bytes={len(response.content) if response.content else 0}"
                )
            payload = response.content if status == 200 else None
            self.finished.emit(self.token, self.image_url, status, payload, retry_after, "")
            return
        except Exception as e:
            last_error = str(e)
            if self.debug_tiff and self.is_tiff:
                print(
                    f"[TIFF-DEBUG] worker:error | token={self.token} | "
                    f"attempt=1/1 | error={last_error}"
                )
        if self.debug_tiff and self.is_tiff:
            print(
                f"[TIFF-DEBUG] worker:failed | token={self.token} | "
                f"error={last_error or 'thumbnail download failed'}"
            )
        self.finished.emit(self.token, self.image_url, 0, None, "", last_error or "thumbnail download failed")


class WikimediaImageDownloadWorker(QThread):
    """Descarga imagen final seleccionada fuera del hilo de UI."""
    finished = pyqtSignal(str)  # output_path
    error = pyqtSignal(str)

    def __init__(self, image_data, output_path):
        super().__init__()
        self.image_data = image_data or {}
        self.output_path = output_path

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            if not WIKIMEDIA_AVAILABLE or WikimediaClient is None:
                self.error.emit("Wikimedia client no disponible")
                return

            wikimedia_client = WikimediaClient()
            downloaded_path = wikimedia_client.download_image(self.image_data, self.output_path)
            if self.isInterruptionRequested():
                return
            if downloaded_path and os.path.exists(downloaded_path):
                self.finished.emit(downloaded_path)
            else:
                self.error.emit("No se pudo descargar la imagen. Intenta con otra.")
        except Exception as e:
            self.error.emit(str(e))

# Importar WikimediaClient y verificar disponibilidad
try:
    from media.wikimedia_client import WikimediaClient
    WIKIMEDIA_AVAILABLE = True
except ImportError:
    WIKIMEDIA_AVAILABLE = False
    WikimediaClient = None

# Importar worker desde timeline_workers
try:
    from timeline_workers import WikimediaSearchWorker
except ImportError:
    WikimediaSearchWorker = None
    if WIKIMEDIA_AVAILABLE:
        print("âš ï¸ timeline_workers.py no encontrado. WikimediaSearchWorker no estarÃ¡ disponible.")

class WikimediaSearchDialog(QDialog):
    """DiÃ¡logo para buscar y seleccionar imÃ¡genes de Wikimedia Commons"""
    
    # Variable de clase para mantener resultados entre instancias
    _previous_results = {}  # {query: [images]}
    _MAX_PREVIOUS_QUERIES = 6
    _MAX_PREVIOUS_ITEMS_PER_QUERY = 10
    _MAX_PRELOADED_ITEMS_ON_OPEN = 24
    _MAX_PREVIEW_IMAGE_BYTES = 24 * 1024 * 1024
    _TIFF_429_STRIKE_LIMIT = 2
    _TIFF_429_COOLDOWN_MS = 5 * 60 * 1000
    _tiff_429_cooldowns = {}  # {rate_key: until_ms}
    _tiff_429_strikes = {}    # {rate_key: count}
    
    def __init__(self, parent=None, segment_data=None):
        super().__init__(parent)
        self.segment_data = segment_data or {}
        self.selected_image_path = None
        self.images = []
        self._preview_queue = []
        self._preview_workers = {}
        self._preview_item_by_token = {}
        self._preview_meta_by_token = {}
        self._preview_token_by_item_id = {}
        self._preview_token_counter = 0
        self._max_parallel_preview_workers = 3
        self._preview_load_interval_ms = 180
        self._preview_retry_limit = 4
        self._preview_pause_until_ms = 0
        self._download_worker = None
        self._preview_cache_dir = Path("auto_videos") / "cache" / "wikimedia_thumbs"
        self._preview_cache_dir.mkdir(parents=True, exist_ok=True)
        self._closing = False
        self._tiff_debug_enabled = str(
            os.getenv("WIKIMEDIA_TIFF_DEBUG", "1")
        ).strip().lower() not in ("0", "false", "no", "off")
        
        self.setWindowTitle("ðŸ“š Buscar ImÃ¡genes en Wikimedia Commons")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 900)  # TamaÃ±o inicial mÃ¡s grande
        
        self.setup_ui()
        
        # Cargar resultados anteriores si existen
        self.load_previous_results()
        
        # NO auto-buscar - dejar la barra de bÃºsqueda vacÃ­a para que el usuario escriba su propia bÃºsqueda
    
    def setup_ui(self):
        """Configura la interfaz del diÃ¡logo"""
        layout = QVBoxLayout(self)
        
        # Campo de bÃºsqueda (fijo en la parte superior)
        search_layout = QHBoxLayout()
        search_label = QLabel("ðŸ” Buscar:")
        search_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Ej: Pearl Harbor 1941, Battle of Marathon, etc.")
        self.search_input.returnPressed.connect(self.perform_search)
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("ðŸ” Buscar")
        self.search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(self.search_btn)
        
        layout.addLayout(search_layout)
        
        # Barra de progreso (fija)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Ãrea de scroll para el contenido principal
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Widget contenedor para el contenido desplazable
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        # Lista de resultados
        results_label = QLabel("Resultados:")
        scroll_layout.addWidget(results_label)
        
        self.results_list = QListWidget()
        self.results_list.setViewMode(QListWidget.ViewMode.IconMode)
        # TamaÃ±o mÃ¡s grande para las imÃ¡genes (400x400 para que se vean completas)
        self.results_list.setIconSize(QPixmap(400, 400).size())
        self.results_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.results_list.setSpacing(15)  # Espaciado entre items (aumentado)
        self.results_list.setGridSize(QPixmap(450, 480).size())  # TamaÃ±o de la celda (imagen + texto) - aumentado
        self.results_list.itemDoubleClicked.connect(self.select_image)
        # Hacer que el Ã¡rea de resultados use todo el espacio disponible
        scroll_layout.addWidget(self.results_list, 1)
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)  # El Ã¡rea de scroll usa todo el espacio disponible
        
        # Botones (fijos en la parte inferior)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        self.select_btn = QPushButton("âœ… Seleccionar Imagen")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.select_current_image)
        buttons_layout.addWidget(self.select_btn)
        
        cancel_btn = QPushButton("âŒ Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        
        layout.addLayout(buttons_layout)
        
        # Conectar selecciÃ³n de item
        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)

    def _trim_previous_results_cache(self):
        """Limita el cache de resultados previos para mantener UI ágil."""
        if not self._previous_results:
            return

        recent_items = list(self._previous_results.items())[-self._MAX_PREVIOUS_QUERIES:]
        trimmed_cache = {}
        for query, images in recent_items:
            if not isinstance(images, list):
                continue
            trimmed_cache[query] = images[-self._MAX_PREVIOUS_ITEMS_PER_QUERY:]
        self._previous_results = trimmed_cache

    def _create_generic_image_icon(self):
        pixmap = QPixmap(400, 400)
        pixmap.fill(Qt.GlobalColor.darkGray)
        return QIcon(pixmap)

    @staticmethod
    def _is_tiff_title(title):
        title_lower = str(title or "").lower()
        return ".tif" in title_lower or ".tiff" in title_lower

    @staticmethod
    def _is_tiff_url(url):
        return ".tif" in str(url or "").lower() or ".tiff" in str(url or "").lower()

    def _debug_tiff(self, message, title="", url="", token=None, force=False):
        if not self._tiff_debug_enabled:
            return
        if not force and not (self._is_tiff_title(title) or self._is_tiff_url(url)):
            return
        parts = [f"[TIFF-DEBUG] {message}"]
        if token is not None:
            parts.append(f"token={token}")
        if title:
            parts.append(f"title={str(title)[:90]}")
        if url:
            parts.append(f"url={str(url)[:180]}")
        print(" | ".join(parts))

    @classmethod
    def _is_tiff_key_in_cooldown(cls, rate_key, now_ms):
        if not rate_key:
            return False
        until = int(cls._tiff_429_cooldowns.get(rate_key, 0) or 0)
        if until <= 0:
            return False
        if now_ms >= until:
            cls._tiff_429_cooldowns.pop(rate_key, None)
            cls._tiff_429_strikes.pop(rate_key, None)
            return False
        return True

    @classmethod
    def _register_tiff_429(cls, rate_key, now_ms):
        if not rate_key:
            return 0
        strikes = int(cls._tiff_429_strikes.get(rate_key, 0) or 0) + 1
        cls._tiff_429_strikes[rate_key] = strikes
        if strikes >= cls._TIFF_429_STRIKE_LIMIT:
            cls._tiff_429_cooldowns[rate_key] = now_ms + cls._TIFF_429_COOLDOWN_MS
        return strikes

    @classmethod
    def _clear_tiff_429(cls, rate_key):
        if not rate_key:
            return
        cls._tiff_429_strikes.pop(rate_key, None)
        cls._tiff_429_cooldowns.pop(rate_key, None)

    def _finalize_preview_token(self, token):
        item = self._preview_item_by_token.pop(token, None)
        self._preview_meta_by_token.pop(token, None)
        if item is not None:
            self._preview_token_by_item_id.pop(id(item), None)

    def _pick_preview_url_from_image(self, img):
        raw_title = str(img.get('title', '') or '')
        title_lower = raw_title.lower()
        is_tiff = '.tif' in title_lower or '.tiff' in title_lower
        if is_tiff:
            self._debug_tiff(
                "pick_preview:start",
                title=raw_title,
                url=img.get('url', ''),
                force=True
            )
        # Para TIFF conviene priorizar derivados /thumb/ para evitar rate-limit.
        candidates = [
            img.get('thumburl', ''),
            img.get('thumbnail_url', ''),
            img.get('thumbnail', ''),
            img.get('image', ''),
            img.get('url', ''),
            img.get('file_url', ''),
            img.get('source_url', ''),
            img.get('original_url', ''),
            img.get('descriptionurl', ''),
            img.get('fullurl', ''),
        ]
        for idx, candidate in enumerate(candidates):
            normalized = self._normalize_preview_url(candidate)
            if is_tiff:
                self._debug_tiff(
                    f"pick_preview:candidate[{idx}] normalized={'yes' if normalized else 'no'}",
                    title=raw_title,
                    url=normalized or candidate,
                    force=True
                )
            if not normalized:
                continue
            if is_tiff and "/thumb/" in normalized:
                normalized = self._build_tiff_preview_url(
                    source_url=img.get('url', '') or normalized,
                    fallback_url=normalized,
                    width=480
                )
                self._debug_tiff(
                    "pick_preview:choose-thumb-candidate",
                    title=raw_title,
                    url=normalized,
                    force=True
                )
                return normalized
            if is_tiff and ('.tif' in normalized.lower() or '.tiff' in normalized.lower()):
                thumb_from_upload = self._to_upload_thumb_wikimedia_url(normalized, width=640)
                if thumb_from_upload:
                    self._debug_tiff(
                        "pick_preview:choose-upload-thumb-from-original",
                        title=raw_title,
                        url=thumb_from_upload,
                        force=True
                    )
                    return thumb_from_upload
                self._debug_tiff(
                    "pick_preview:choose-original-tiff-fallback",
                    title=raw_title,
                    url=normalized,
                    force=True
                )
                return normalized

            safe_url = self._to_preview_safe_wikimedia_url(normalized, width=640)
            if is_tiff:
                self._debug_tiff(
                    "pick_preview:choose-safe-preview-url",
                    title=raw_title,
                    url=safe_url,
                    force=True
                )
            return safe_url

        # Fallback robusto: construir preview desde el titulo de archivo.
        fallback_title = raw_title.replace('File:', '').strip()
        if fallback_title:
            try:
                fallback_url = (
                    f"https://commons.wikimedia.org/wiki/Special:FilePath/"
                    f"{quote(fallback_title, safe='')}?width=640"
                )
                if is_tiff:
                    self._debug_tiff(
                        "pick_preview:fallback-from-title",
                        title=raw_title,
                        url=fallback_url,
                        force=True
                    )
                return fallback_url
            except Exception:
                pass
        if is_tiff:
            self._debug_tiff(
                "pick_preview:no-url-selected",
                title=raw_title,
                force=True
            )
        return ""

    def _decode_pixmap_from_bytes(self, image_data, prefer_pil=False, debug_ctx=""):
        is_tiff_binary = (
            isinstance(image_data, (bytes, bytearray)) and
            (image_data[:4] in (b'II*\x00', b'MM\x00*'))
        )
        use_pil_first = prefer_pil or is_tiff_binary
        if debug_ctx:
            self._debug_tiff(
                f"decode:start | bytes={len(image_data) if image_data else 0} | "
                f"prefer_pil={prefer_pil} | tiff_magic={is_tiff_binary} | pil_first={use_pil_first}",
                force=True
            )

        if not use_pil_first:
            pixmap = QPixmap()
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='.*fromIccProfile.*')
                warnings.filterwarnings('ignore', message='.*ICC.*')
                warnings.filterwarnings('ignore', category=UserWarning)
                if pixmap.loadFromData(image_data) and not pixmap.isNull():
                    if debug_ctx:
                        self._debug_tiff(
                            f"decode:qt-success | size={pixmap.width()}x{pixmap.height()}",
                            force=True
                        )
                    return pixmap
            if debug_ctx:
                self._debug_tiff("decode:qt-failed-initial", force=True)

        # Fallback robusto para formatos que Qt no decodifica bien.
        if PIL_AVAILABLE:
            try:
                with Image.open(BytesIO(image_data)) as pil_img:
                    # Reducir antes de serializar evita límite de asignación de Qt.
                    if hasattr(Image, "Resampling"):
                        resample = Image.Resampling.LANCZOS
                    else:
                        resample = Image.LANCZOS
                    pil_img.thumbnail((1200, 1200), resample=resample)
                    if pil_img.mode not in ("RGB", "RGBA"):
                        pil_img = pil_img.convert("RGB")
                    buf = BytesIO()
                    pil_img.save(buf, format="JPEG", quality=88, optimize=True)
                    raw = buf.getvalue()
                    pixmap2 = QPixmap()
                    if pixmap2.loadFromData(raw) and not pixmap2.isNull():
                        if debug_ctx:
                            self._debug_tiff(
                                f"decode:pil-success | mode={pil_img.mode} | "
                                f"jpeg_bytes={len(raw)} | size={pixmap2.width()}x{pixmap2.height()}",
                                force=True
                            )
                        return pixmap2
                    if debug_ctx:
                        self._debug_tiff("decode:pil-produced-null-pixmap", force=True)
            except Exception as e:
                if debug_ctx:
                    self._debug_tiff(f"decode:pil-error | error={e}", force=True)
        elif debug_ctx:
            self._debug_tiff("decode:pil-not-available", force=True)

        if not use_pil_first:
            pixmap = QPixmap()
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='.*fromIccProfile.*')
                warnings.filterwarnings('ignore', message='.*ICC.*')
                warnings.filterwarnings('ignore', category=UserWarning)
                if pixmap.loadFromData(image_data) and not pixmap.isNull():
                    if debug_ctx:
                        self._debug_tiff(
                            f"decode:qt-success-fallback | size={pixmap.width()}x{pixmap.height()}",
                            force=True
                        )
                    return pixmap
            if debug_ctx:
                self._debug_tiff("decode:qt-fallback-failed", force=True)

        if debug_ctx:
            self._debug_tiff("decode:failed-return-none", force=True)
        return None
    
    def load_previous_results(self):
        """Carga resultados de bÃºsquedas anteriores"""
        if not self._previous_results:
            return

        self._trim_previous_results_cache()

        loaded_count = 0
        recent_items = list(self._previous_results.items())[-self._MAX_PREVIOUS_QUERIES:]

        # Agregar resultados anteriores a la lista (solo subset reciente)
        for _, images in recent_items:
            for img in images:
                if loaded_count >= self._MAX_PRELOADED_ITEMS_ON_OPEN:
                    break

                item = QListWidgetItem()
                image_title = img.get('title', 'Sin tÃ­tulo').replace('File:', '').strip()
                if len(image_title) > 60:
                    image_title = image_title[:57] + "..."
                item.setText(image_title)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, img)
                item.setIcon(self._create_generic_image_icon())

                self.results_list.addItem(item)

                image_url = self._pick_preview_url_from_image(img)
                if image_url:
                    self.load_image_async(item, image_url, image_title)
                self.images.append(img)
                loaded_count += 1

            if loaded_count >= self._MAX_PRELOADED_ITEMS_ON_OPEN:
                break

        if loaded_count > 0:
            separator = QListWidgetItem("â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”")
            separator.setFlags(Qt.ItemFlag.NoItemFlags)  # No seleccionable
            self.results_list.insertItem(0, separator)
    
    def suggest_query_from_segment(self, segment_data):
        """Sugiere un tÃ©rmino de bÃºsqueda basado en el segmento"""
        # Priorizar el texto de narraciÃ³n
        narration = segment_data.get('text', '')
        visual_prompt = segment_data.get('visual_prompt', '')
        
        # Si hay narraciÃ³n, usar las primeras palabras clave
        if narration:
            # Extraer palabras clave (nombres propios, fechas, eventos)
            words = narration.split()
            # Filtrar palabras comunes y tomar las mÃ¡s relevantes
            stop_words = {'el', 'la', 'los', 'las', 'un', 'una', 'de', 'en', 'y', 'a', 'que', 'es', 'fue', 'son', 'the', 'a', 'an', 'the', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by'}
            keywords = [w for w in words if w.lower() not in stop_words and len(w) > 3][:5]
            if keywords:
                return ' '.join(keywords)
        
        # Fallback al visual prompt
        if visual_prompt:
            # Limpiar el prompt visual de palabras artÃ­sticas
            words = visual_prompt.split()
            keywords = [w for w in words if w.lower() not in ['cinematic', 'stunning', 'beautiful', 'epic', 'dramatic', 'view', 'scene', 'showing', 'depicting'] and len(w) > 3][:5]
            if keywords:
                return ' '.join(keywords)
        
        return ""
    
    def perform_search(self):
        """Realiza la bÃºsqueda de imÃ¡genes"""
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "BÃºsqueda VacÃ­a", "Por favor ingresa un tÃ©rmino de bÃºsqueda.")
            return
        
        if not WIKIMEDIA_AVAILABLE:
            QMessageBox.warning(
                self,
                "Wikimedia no disponible",
                "El cliente de Wikimedia no estÃ¡ disponible.\n"
                "AsegÃºrate de que wikimedia_client.py estÃ© en el directorio del proyecto."
            )
            return
        
        if not WikimediaSearchWorker:
            QMessageBox.warning(
                self,
                "Wikimedia no disponible",
                "El worker de bÃºsqueda de Wikimedia no estÃ¡ disponible.\n"
                "AsegÃºrate de que timeline_workers.py estÃ© en el directorio del proyecto."
            )
            return
        
        # Limpiar resultados anteriores
        self.results_list.clear()
        self.images = []
        self._cancel_preview_loaders()
        self.select_btn.setEnabled(False)
        
        # Mostrar progreso
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminado
        self.search_btn.setEnabled(False)
        
        # Obtener texto de narraciÃ³n del segmento
        narration_text = self.segment_data.get('text', '') if self.segment_data else ''
        
        # Crear worker y buscar
        try:
            self.worker = WikimediaSearchWorker(query, narration_text)
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
    
    def on_search_finished(self, images):
        """Callback cuando la bÃºsqueda termina exitosamente"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        
        # Guardar resultados anteriores antes de agregar nuevos
        query = self.search_input.text().strip()
        if query and images:
            # Agregar a resultados previos (no reemplazar, sino agregar)
            if query not in self._previous_results:
                self._previous_results[query] = []
            # Agregar solo imÃ¡genes nuevas que no estÃ©n ya en la lista
            existing_urls = {img.get('url') for img in self._previous_results[query]}
            new_images = [img for img in images if img.get('url') not in existing_urls]
            self._previous_results[query].extend(new_images)
            # Mantener solo subset reciente por query y global.
            self._previous_results[query] = self._previous_results[query][-self._MAX_PREVIOUS_ITEMS_PER_QUERY:]
            self._trim_previous_results_cache()
        
        # Agregar nuevas imÃ¡genes a la lista actual
        self.images.extend(images)
        
        # Mostrar resultados (solo los nuevos)
        for img in images:
            item = QListWidgetItem()
            # Mostrar solo el nombre de la imagen (sin dimensiones)
            image_title = img.get('title', 'Sin tÃ­tulo').replace('File:', '').strip()
            # Limitar longitud del tÃ­tulo para que quepa bien
            if len(image_title) > 60:
                image_title = image_title[:57] + "..."
            item.setText(image_title)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)  # Centrar el texto
            item.setData(Qt.ItemDataRole.UserRole, img)
            item.setIcon(self._create_generic_image_icon())
            
            # Agregar item primero para que aparezca en la lista
            self.results_list.addItem(item)
            
            # Cargar la imagen de forma asÃ­ncrona despuÃ©s de agregar el item
            image_url = self._pick_preview_url_from_image(img)
            
            if not image_url:
                print(f"âš ï¸ No hay URL disponible para: {image_title}")
                continue
            
            # Cargar imagen en un hilo separado para no bloquear la UI
            self.load_image_async(item, image_url, image_title)
        
        if images:
            QMessageBox.information(
                self,
                "BÃºsqueda Completada",
                f"Se encontraron {len(images)} imÃ¡genes."
            )
        else:
            QMessageBox.information(
                self,
                "Sin Resultados",
                "No se encontraron imÃ¡genes. Intenta con otros tÃ©rminos de bÃºsqueda."
            )
    
    def on_search_error(self, error_msg):
        """Callback cuando hay un error en la bÃºsqueda"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        QMessageBox.critical(self, "Error en BÃºsqueda", error_msg)
    
    def _retry_after_to_ms(self, retry_after_value):
        """Convierte Retry-After a milisegundos si es posible."""
        if not retry_after_value:
            return None
        try:
            seconds = float(retry_after_value)
            if seconds >= 0:
                return int(seconds * 1000)
        except (TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _to_original_wikimedia_url(url):
        """Convierte URL /thumb/ de Wikimedia a URL original cuando sea posible."""
        if not isinstance(url, str):
            return url
        if "/thumb/" not in url:
            return url
        try:
            base, tail = url.split("/thumb/", 1)
            original_tail = tail.rsplit("/", 1)[0] if "/" in tail else tail
            return f"{base}/{original_tail}"
        except Exception:
            return url

    def _process_next_preview_image(self):
        """Compatibilidad: ahora la carga se hace con workers."""
        self._start_preview_workers()

    def load_image_async(self, item, image_url, image_title):
        """Encola la descarga de miniatura en segundo plano."""
        item_id = id(item)
        existing_token = self._preview_token_by_item_id.get(item_id)
        if existing_token and existing_token in self._preview_meta_by_token:
            return

        normalized_url = self._normalize_preview_url(image_url)
        if not normalized_url:
            if self._is_tiff_title(image_title):
                self._debug_tiff(
                    "queue:skip-empty-normalized-url",
                    title=image_title,
                    url=image_url,
                    force=True
                )
            return
        is_tiff = self._is_tiff_title(image_title) or self._is_tiff_url(normalized_url)
        if is_tiff:
            self._debug_tiff(
                "queue:start",
                title=image_title,
                url=normalized_url,
                force=True
            )
            now_ms = self._now_ms()
            rate_key = (image_url or normalized_url or "").strip()
            if self._is_tiff_key_in_cooldown(rate_key, now_ms):
                self._debug_tiff(
                    "queue:skip-cooldown-active",
                    title=image_title,
                    url=normalized_url,
                    force=True
                )
                return
        if is_tiff:
            # Para TIFF, arrancar directamente con preview reducido evita descargar
            # originales enormes (decenas de MB) que no sirven para miniatura.
            if "/thumb/" not in normalized_url:
                normalized_url = self._build_tiff_preview_url(
                    source_url=image_url,
                    fallback_url=normalized_url,
                    width=640
                )
            self._debug_tiff(
                "queue:normalized-to-safe-preview",
                title=image_title,
                url=normalized_url,
                force=True
            )

        cache_path = self._get_preview_cache_path(normalized_url)
        if cache_path.exists():
            try:
                if cache_path.stat().st_size > self._MAX_PREVIEW_IMAGE_BYTES:
                    cache_path.unlink(missing_ok=True)
                    raise ValueError("cache thumbnail too large")
                data = cache_path.read_bytes()
                if is_tiff:
                    self._debug_tiff(
                        f"cache:hit | bytes={len(data)} | path={cache_path}",
                        title=image_title,
                        url=normalized_url,
                        force=True
                    )
                pixmap = self._decode_pixmap_from_bytes(
                    data,
                    prefer_pil=is_tiff,
                    debug_ctx=image_title if is_tiff else ""
                )
                if pixmap is not None:
                    scaled_pixmap = pixmap.scaled(
                        400, 400,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    item.setIcon(QIcon(scaled_pixmap))
                    if is_tiff:
                        self._debug_tiff(
                            "cache:decode-success",
                            title=image_title,
                            url=normalized_url,
                            force=True
                        )
                    return
                if is_tiff:
                    self._debug_tiff(
                        "cache:decode-failed",
                        title=image_title,
                        url=normalized_url,
                        force=True
                    )
            except Exception:
                if is_tiff:
                    self._debug_tiff(
                        f"cache:error | path={cache_path}",
                        title=image_title,
                        url=normalized_url,
                        force=True
                    )
        elif is_tiff:
            self._debug_tiff(
                "cache:miss",
                title=image_title,
                url=normalized_url,
                force=True
            )

        self._preview_token_counter += 1
        token = self._preview_token_counter
        self._preview_item_by_token[token] = item
        self._preview_token_by_item_id[item_id] = token
        self._preview_meta_by_token[token] = {
            'url': normalized_url,
            'source_url': image_url or normalized_url,
            'rate_key': (image_url or normalized_url or "").strip(),
            'title': image_title or '',
            'retry_count': 0,
            'is_tiff': is_tiff,
        }
        self._preview_queue.append(token)
        if is_tiff:
            self._debug_tiff(
                f"queue:enqueued | retry=0 | queue_size={len(self._preview_queue)}",
                title=image_title,
                url=normalized_url,
                token=token,
                force=True
            )
        self._start_preview_workers()

    @staticmethod
    def _now_ms():
        return int(time.monotonic() * 1000)

    def _get_preview_cache_path(self, image_url):
        key = hashlib.sha1(image_url.encode("utf-8", errors="ignore")).hexdigest()
        return self._preview_cache_dir / f"{key}.bin"

    @staticmethod
    def _normalize_preview_url(image_url):
        if not isinstance(image_url, str):
            return ""
        url = image_url.strip()
        if not url:
            return ""
        if url.startswith('//'):
            url = f"https:{url}"
        elif url.startswith('/'):
            url = f"https://commons.wikimedia.org{url}"
        if url.startswith(('http://', 'https://')):
            return url
        return ""

    @staticmethod
    def _to_preview_safe_wikimedia_url(url, width=640):
        """Devuelve URL de preview segura (evita originales TIFF enormes)."""
        if not isinstance(url, str):
            return ""
        candidate = url.strip()
        if not candidate:
            return ""
        if "/thumb/" in candidate:
            return candidate
        try:
            parsed = urlparse(candidate)
            filename = os.path.basename(parsed.path or "")
            if not filename:
                return candidate
            # Evita doble-encoding cuando el nombre ya viene con %XX desde la API.
            decoded_filename = unquote(filename)
            quoted_filename = quote(decoded_filename, safe="")
            return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quoted_filename}?width={int(width)}"
        except Exception:
            return candidate

    @staticmethod
    def _to_upload_thumb_wikimedia_url(url, width=640):
        """
        Construye URL directa de thumbnail desde una URL original de upload.wikimedia.org.
        """
        if not isinstance(url, str):
            return ""
        candidate = url.strip()
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
            suffix = path.replace("/wikipedia/commons", "", 1)
            return (
                f"{parsed.scheme}://{parsed.netloc}"
                f"/wikipedia/commons/thumb{suffix}"
                f"/{int(width)}px-{filename}.jpg"
            )
        except Exception:
            return ""

    def _build_tiff_preview_url(self, source_url, fallback_url, width=640):
        """
        Genera la mejor URL de preview para TIFF priorizando upload/thumb.
        """
        base_original = self._to_original_wikimedia_url(source_url or fallback_url or "")
        safe_preview = self._to_preview_safe_wikimedia_url(base_original, width=width)
        if safe_preview:
            return safe_preview
        upload_thumb = self._to_upload_thumb_wikimedia_url(base_original, width=width)
        if upload_thumb:
            return upload_thumb
        return base_original

    def _start_preview_workers(self):
        if self._closing:
            return

        now_ms = self._now_ms()
        if self._preview_pause_until_ms > now_ms:
            delay_ms = max(80, self._preview_pause_until_ms - now_ms)
            QTimer.singleShot(delay_ms, self._start_preview_workers)
            return

        while self._preview_queue and len(self._preview_workers) < self._max_parallel_preview_workers:
            token = self._preview_queue.pop(0)
            meta = self._preview_meta_by_token.get(token)
            item = self._preview_item_by_token.get(token)
            if not meta or item is None:
                continue

            is_tiff = bool(meta.get('is_tiff', False))
            timeout_s = 12 if is_tiff else 10
            if is_tiff:
                self._debug_tiff(
                    f"worker:spawn | retry={meta.get('retry_count', 0)} | "
                    f"timeout={timeout_s}s | queue_left={len(self._preview_queue)}",
                    title=meta.get('title', ''),
                    url=meta.get('url', ''),
                    token=token,
                    force=True
                )
            worker = ThumbnailDownloadWorker(
                token,
                meta.get('url', ''),
                timeout=timeout_s,
                is_tiff=is_tiff,
                image_title=meta.get('title', ''),
                debug_tiff=self._tiff_debug_enabled
            )
            worker.finished.connect(self._on_preview_download_finished)
            worker.finished.connect(lambda *_, w=worker: w.deleteLater())
            self._preview_workers[token] = worker
            worker.start()

    def _on_preview_download_finished(self, token, image_url, status_code, image_data, retry_after, error_msg):
        worker = self._preview_workers.pop(token, None)
        if worker and worker.isRunning():
            worker.quit()
            worker.wait(50)

        if self._closing:
            return

        item = self._preview_item_by_token.get(token)
        meta = self._preview_meta_by_token.get(token, {})
        if item is None or not meta:
            self._start_preview_workers()
            return

        retry_count = int(meta.get('retry_count', 0) or 0)
        image_title = meta.get('title', '')
        source_url = meta.get('source_url', '')
        rate_key = meta.get('rate_key', source_url or image_url or '')
        is_tiff = bool(meta.get('is_tiff', False))
        retry_limit = 2 if is_tiff else self._preview_retry_limit
        error_lower = (error_msg or "").lower()
        if is_tiff:
            self._debug_tiff(
                f"worker:finished | status={status_code} | bytes={len(image_data) if image_data else 0} | "
                f"retry={retry_count}/{retry_limit} | retry_after={retry_after or '-'} | "
                f"error={error_msg or '-'}",
                title=image_title,
                url=image_url,
                token=token,
                force=True
            )

        if status_code == 200 and image_data:
            if is_tiff:
                self._clear_tiff_429(rate_key)
            if len(image_data) > self._MAX_PREVIEW_IMAGE_BYTES and retry_count < retry_limit:
                retry_width = 240 if is_tiff else 480
                if is_tiff:
                    meta['url'] = self._build_tiff_preview_url(
                        source_url=source_url,
                        fallback_url=image_url,
                        width=retry_width
                    )
                else:
                    meta['url'] = self._to_preview_safe_wikimedia_url(image_url, width=retry_width)
                meta['retry_count'] = retry_count + 1
                self._preview_meta_by_token[token] = meta
                if is_tiff:
                    self._debug_tiff(
                        f"retry:payload-too-large | bytes={len(image_data)} | next_width={retry_width}",
                        title=image_title,
                        url=meta.get('url', ''),
                        token=token,
                        force=True
                    )
                QTimer.singleShot(1200, lambda t=token: self._requeue_preview_token(t))
                QTimer.singleShot(self._preview_load_interval_ms, self._start_preview_workers)
                return
            pixmap = self._decode_pixmap_from_bytes(
                image_data,
                prefer_pil=is_tiff,
                debug_ctx=image_title if is_tiff else ""
            )
            if pixmap is None and retry_count < retry_limit:
                widths = [640, 480, 320, 240, 160]
                width_idx = min(retry_count + 1, len(widths) - 1)
                if is_tiff:
                    meta['url'] = self._build_tiff_preview_url(
                        source_url=source_url,
                        fallback_url=image_url,
                        width=widths[width_idx]
                    )
                else:
                    meta['url'] = self._to_preview_safe_wikimedia_url(image_url, width=widths[width_idx])
                meta['retry_count'] = retry_count + 1
                self._preview_meta_by_token[token] = meta
                if is_tiff:
                    self._debug_tiff(
                        f"retry:decode-failed | next_width={widths[width_idx]} | "
                        f"next_url={meta.get('url', '')}",
                        title=image_title,
                        url=image_url,
                        token=token,
                        force=True
                    )
                QTimer.singleShot(1200, lambda t=token: self._requeue_preview_token(t))
                QTimer.singleShot(self._preview_load_interval_ms, self._start_preview_workers)
                return

            if pixmap is not None:
                try:
                    cache_path = self._get_preview_cache_path(image_url)
                    cache_path.write_bytes(image_data)
                    if is_tiff:
                        self._debug_tiff(
                            f"cache:write-success | path={cache_path} | bytes={len(image_data)}",
                            title=image_title,
                            url=image_url,
                            token=token,
                            force=True
                        )
                except Exception:
                    pass
                scaled_pixmap = pixmap.scaled(
                    400, 400,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                item.setIcon(QIcon(scaled_pixmap))
                if is_tiff:
                    self._debug_tiff(
                        f"icon:set-success | scaled={scaled_pixmap.width()}x{scaled_pixmap.height()}",
                        title=image_title,
                        url=image_url,
                        token=token,
                        force=True
                    )
            else:
                item.setIcon(self._create_generic_image_icon())
                if is_tiff:
                    self._debug_tiff(
                        "icon:set-placeholder-after-decode-failure",
                        title=image_title,
                        url=image_url,
                        token=token,
                        force=True
                    )

            self._finalize_preview_token(token)
            if is_tiff:
                self._debug_tiff(
                    "token:completed-and-removed",
                    title=image_title,
                    url=image_url,
                    token=token,
                    force=True
                )
        elif status_code == 429 and retry_count < retry_limit:
            if is_tiff:
                strikes = self._register_tiff_429(rate_key, self._now_ms())
                if strikes >= self._TIFF_429_STRIKE_LIMIT:
                    self._debug_tiff(
                        f"circuit-breaker:429-cooldown | strikes={strikes} | "
                        f"cooldown_ms={self._TIFF_429_COOLDOWN_MS}",
                        title=image_title,
                        url=image_url,
                        token=token,
                        force=True
                    )
                    self._finalize_preview_token(token)
                    QTimer.singleShot(self._preview_load_interval_ms, self._start_preview_workers)
                    return
            retry_after_ms = self._retry_after_to_ms(retry_after)
            if retry_after_ms is not None:
                backoff_ms = retry_after_ms
            else:
                base = 1500 if is_tiff else 6000
                backoff_ms = int((2 ** min(retry_count, 5)) * base)
            if not is_tiff:
                now_ms = self._now_ms()
                self._preview_pause_until_ms = max(self._preview_pause_until_ms, now_ms + backoff_ms)
            retry_width = 320 if is_tiff else 640
            if is_tiff:
                meta['url'] = self._build_tiff_preview_url(
                    source_url=source_url,
                    fallback_url=image_url,
                    width=retry_width
                )
            else:
                meta['url'] = self._to_preview_safe_wikimedia_url(image_url, width=retry_width)
            meta['retry_count'] = retry_count + 1
            self._preview_meta_by_token[token] = meta
            if is_tiff:
                self._debug_tiff(
                    f"retry:429 | backoff_ms={backoff_ms} | next_url={meta.get('url', '')}",
                    title=image_title,
                    url=image_url,
                    token=token,
                    force=True
                )
            QTimer.singleShot(backoff_ms, lambda t=token: self._requeue_preview_token(t))
        elif status_code in (0, 403, 404) and retry_count < retry_limit:
            # Si el worker agotó retries por 429, tratarlo como rate limit global.
            if status_code == 0 and "429" in error_lower:
                if is_tiff:
                    strikes = self._register_tiff_429(rate_key, self._now_ms())
                    if strikes >= self._TIFF_429_STRIKE_LIMIT:
                        self._debug_tiff(
                            f"circuit-breaker:status0-from-429-cooldown | strikes={strikes} | "
                            f"cooldown_ms={self._TIFF_429_COOLDOWN_MS}",
                            title=image_title,
                            url=image_url,
                            token=token,
                            force=True
                        )
                        self._finalize_preview_token(token)
                        QTimer.singleShot(self._preview_load_interval_ms, self._start_preview_workers)
                        return
                base = 1500 if is_tiff else 6000
                backoff_ms = int((2 ** min(retry_count, 5)) * base)
                if not is_tiff:
                    now_ms = self._now_ms()
                    self._preview_pause_until_ms = max(self._preview_pause_until_ms, now_ms + backoff_ms)
                retry_width = 240 if is_tiff else 480
                if is_tiff:
                    meta['url'] = self._build_tiff_preview_url(
                        source_url=source_url,
                        fallback_url=image_url,
                        width=retry_width
                    )
                else:
                    meta['url'] = self._to_preview_safe_wikimedia_url(image_url, width=retry_width)
                meta['retry_count'] = retry_count + 1
                self._preview_meta_by_token[token] = meta
                if is_tiff:
                    self._debug_tiff(
                        f"retry:status0-from-429 | backoff_ms={backoff_ms} | next_url={meta.get('url', '')}",
                        title=image_title,
                        url=image_url,
                        token=token,
                        force=True
                    )
                QTimer.singleShot(backoff_ms, lambda t=token: self._requeue_preview_token(t))
                QTimer.singleShot(self._preview_load_interval_ms, self._start_preview_workers)
                return
            # Reintentar una variante de URL para thumbnails que fallen por hotlink/proxy.
            retry_width = 240 if is_tiff else 480
            if is_tiff:
                meta['url'] = self._build_tiff_preview_url(
                    source_url=source_url,
                    fallback_url=image_url,
                    width=retry_width
                )
            else:
                meta['url'] = self._to_preview_safe_wikimedia_url(image_url, width=retry_width)
            meta['retry_count'] = retry_count + 1
            self._preview_meta_by_token[token] = meta
            if is_tiff:
                self._debug_tiff(
                    f"retry:status-{status_code} | next_url={meta.get('url', '')}",
                    title=image_title,
                    url=image_url,
                    token=token,
                    force=True
                )
            QTimer.singleShot(1200, lambda t=token: self._requeue_preview_token(t))
        else:
            if error_msg:
                print(f"️ Error cargando miniatura '{image_title[:50]}': {error_msg}")
            elif status_code and status_code != 200:
                print(f"️ Miniatura sin cargar ({status_code}) para: {image_title[:50]}")
            if is_tiff:
                self._debug_tiff(
                    f"token:discarded-finally | status={status_code} | error={error_msg or '-'}",
                    title=image_title,
                    url=image_url,
                    token=token,
                    force=True
                )
            self._finalize_preview_token(token)

        QTimer.singleShot(self._preview_load_interval_ms, self._start_preview_workers)

    def _requeue_preview_token(self, token):
        if self._closing:
            return
        if token not in self._preview_item_by_token or token not in self._preview_meta_by_token:
            return
        meta = self._preview_meta_by_token.get(token, {})
        if token in self._preview_queue:
            return
        if meta and bool(meta.get('is_tiff', False)):
            rate_key = meta.get('rate_key', '')
            if self._is_tiff_key_in_cooldown(rate_key, self._now_ms()):
                self._debug_tiff(
                    "queue:requeue-skipped-cooldown-active",
                    title=meta.get('title', ''),
                    url=meta.get('url', ''),
                    token=token,
                    force=True
                )
                self._finalize_preview_token(token)
                QTimer.singleShot(self._preview_load_interval_ms, self._start_preview_workers)
                return
        if meta and bool(meta.get('is_tiff', False)):
            self._debug_tiff(
                f"queue:requeued | retry={meta.get('retry_count', 0)} | queue_size={len(self._preview_queue) + 1}",
                title=meta.get('title', ''),
                url=meta.get('url', ''),
                token=token,
                force=True
            )
        self._preview_queue.append(token)
        self._start_preview_workers()

    def _cancel_preview_loaders(self):
        self._preview_queue.clear()
        self._preview_pause_until_ms = 0
        for _, worker in list(self._preview_workers.items()):
            try:
                worker.requestInterruption()
                worker.wait(150)
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(150)
            except Exception:
                pass
        self._preview_workers.clear()
        self._preview_item_by_token.clear()
        self._preview_meta_by_token.clear()
        self._preview_token_by_item_id.clear()

    def on_selection_changed(self):
        """Callback cuando cambia la selecciÃ³n"""
        self.select_btn.setEnabled(self.results_list.currentItem() is not None)
    
    def select_current_image(self):
        """Selecciona la imagen actualmente seleccionada"""
        current_item = self.results_list.currentItem()
        if current_item:
            self.select_image(current_item)
    
    def select_image(self, item):
        """Selecciona una imagen y la descarga"""
        if self._download_worker and self._download_worker.isRunning():
            return

        image_data = item.data(Qt.ItemDataRole.UserRole)
        if not image_data:
            return
        
        # Mostrar progreso
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.select_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.results_list.setEnabled(False)
        
        try:
            # Crear directorio para imÃ¡genes de Wikimedia si no existe
            wikimedia_dir = Path("auto_videos") / "images" / "wikimedia"
            wikimedia_dir.mkdir(parents=True, exist_ok=True)
            
            # Generar nombre de archivo Ãºnico
            image_title = image_data.get('title', 'image').replace('File:', '').replace('/', '_')
            filename = f"wikimedia_{hash(image_data.get('url', '')) % 100000}_{image_title[:50]}.jpg"
            output_path = wikimedia_dir / filename
            
            # Descargar en background para no bloquear la UI
            self._download_worker = WikimediaImageDownloadWorker(image_data, str(output_path))
            self._download_worker.finished.connect(self._on_image_download_finished)
            self._download_worker.error.connect(self._on_image_download_error)
            self._download_worker.finished.connect(self._on_image_download_worker_done)
            self._download_worker.error.connect(self._on_image_download_worker_done)
            self._download_worker.start()
        
        except Exception as e:
            self._on_image_download_error(str(e))

    def _on_image_download_finished(self, downloaded_path):
        """Procesa descarga de imagen completada."""
        self.selected_image_path = downloaded_path
        self.progress_bar.setVisible(False)
        self.accept()

    def _on_image_download_error(self, error_msg):
        """Procesa error de descarga de imagen."""
        self.progress_bar.setVisible(False)
        self.select_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        self.results_list.setEnabled(True)
        QMessageBox.critical(
            self,
            "Error",
            f"Error descargando imagen:\n{str(error_msg)}"
        )

    def _on_image_download_worker_done(self, *_):
        """Limpia estado del worker de descarga."""
        self.search_btn.setEnabled(True)
        self.results_list.setEnabled(True)
        worker = self._download_worker
        self._download_worker = None
        if worker:
            try:
                worker.deleteLater()
            except Exception:
                pass

    def closeEvent(self, event):
        """Limpia workers de miniaturas y búsqueda al cerrar."""
        self._closing = True
        self._cancel_preview_loaders()
        try:
            if self._download_worker and self._download_worker.isRunning():
                self._download_worker.requestInterruption()
                self._download_worker.wait(200)
                if self._download_worker.isRunning():
                    self._download_worker.terminate()
                    self._download_worker.wait(200)
        except Exception:
            pass
        try:
            if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
                self.worker.requestInterruption()
                self.worker.wait(200)
                if self.worker.isRunning():
                    self.worker.terminate()
                    self.worker.wait(200)
        except Exception:
            pass
        event.accept()


