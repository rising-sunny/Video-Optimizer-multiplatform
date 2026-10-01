# bing_images_search_dialog.py
"""
Dialogo para buscar y seleccionar imagenes usando Openverse (gratis).
"""

from pathlib import Path
import os
import requests
import warnings

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget
)

try:
    from media.bing_images_client import BingImagesClient
    BING_IMAGES_AVAILABLE = True
except ImportError:
    BingImagesClient = None
    BING_IMAGES_AVAILABLE = False

try:
    from studio.timeline_workers import BingImagesSearchWorker
except ImportError:
    # Compatibilidad con versiones donde el worker aun se llama GoogleImagesSearchWorker
    try:
        from studio.timeline_workers import GoogleImagesSearchWorker as BingImagesSearchWorker
    except ImportError:
        BingImagesSearchWorker = None


class BingImagesSearchDialog(QDialog):
    """Dialogo para buscar y seleccionar imagenes de Openverse."""

    _previous_results = {}

    def __init__(self, parent=None, segment_data=None):
        super().__init__(parent)
        self.segment_data = segment_data or {}
        self.selected_image_path = None
        self.images = []
        self.worker = None
        self._preview_queue = []
        self._preview_loader_active = False
        self._preview_load_interval_ms = 1200
        self._preview_retry_limit = 3
        self._max_preview_items = 12

        self.setWindowTitle(" Buscar Imagenes en Openverse (Gratis)")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 900)
        self.setup_ui()
        self.load_previous_results()

    def closeEvent(self, event):
        try:
            if self.worker and self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(1000)
        except Exception:
            pass
        finally:
            event.accept()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel(" Buscar:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Ej: Pearl Harbor 1941, Battle of Marathon")
        self.search_input.returnPressed.connect(self.perform_search)
        search_layout.addWidget(self.search_input)
        self.search_btn = QPushButton(" Buscar")
        self.search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(self.search_btn)
        layout.addLayout(search_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        scroll_layout.addWidget(QLabel("Resultados:"))
        self.results_list = QListWidget()
        self.results_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.results_list.setIconSize(QPixmap(400, 400).size())
        self.results_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.results_list.setSpacing(15)
        self.results_list.setGridSize(QPixmap(450, 480).size())
        self.results_list.itemDoubleClicked.connect(self.select_image)
        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)
        scroll_layout.addWidget(self.results_list, 1)

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        self.select_btn = QPushButton(" Seleccionar Imagen")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.select_current_image)
        buttons_layout.addWidget(self.select_btn)
        cancel_btn = QPushButton(" Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        layout.addLayout(buttons_layout)

    def perform_search(self):
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Busqueda Vacia", "Por favor ingresa un termino de busqueda.")
            return

        if not BING_IMAGES_AVAILABLE:
            QMessageBox.warning(
                self,
                "Openverse no disponible",
                "El cliente de imagenes no esta disponible.\nAsegurate de que bing_images_client.py exista."
            )
            return

        if not BingImagesSearchWorker:
            QMessageBox.warning(
                self,
                "Openverse no disponible",
                "El worker de busqueda no esta disponible.\nAsegurate de que timeline_workers.py este actualizado."
            )
            return

        self.results_list.clear()
        self.images = []
        self._preview_queue.clear()
        self._preview_loader_active = False
        self.select_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.search_btn.setEnabled(False)

        narration_text = self.segment_data.get("text", "") if self.segment_data else ""
        try:
            self.worker = BingImagesSearchWorker(query, narration_text)
            self.worker.finished.connect(self.on_search_finished)
            self.worker.error.connect(self.on_search_error)
            self.worker.progress.connect(lambda msg: self.progress_bar.setFormat(msg))
            self.worker.start()
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.search_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", f"Error al iniciar la busqueda:\n{e}")

    def load_previous_results(self):
        preview_count = 0
        for _, images in self._previous_results.items():
            for img in images:
                item = QListWidgetItem()
                image_title = img.get("title", "Sin titulo").strip()
                if len(image_title) > 60:
                    image_title = image_title[:57] + "..."
                item.setText(image_title)
                item.setData(Qt.ItemDataRole.UserRole, img)
                self.results_list.addItem(item)
                image_url = img.get("thumbnail", "") or img.get("url", "")
                if (
                    image_url
                    and image_url.startswith(("http://", "https://"))
                    and preview_count < self._max_preview_items
                ):
                    self.load_image_async(item, image_url, image_title)
                    preview_count += 1
                self.images.append(img)

    def on_search_finished(self, images):
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)

        query = self.search_input.text().strip()
        if query and images:
            if query not in self._previous_results:
                self._previous_results[query] = []
            existing_urls = {img.get("url") for img in self._previous_results[query]}
            new_images = [img for img in images if img.get("url") not in existing_urls]
            self._previous_results[query].extend(new_images)

        self.images.extend(images)
        for idx, img in enumerate(images):
            item = QListWidgetItem()
            image_title = img.get("title", "Sin titulo").strip()
            if len(image_title) > 60:
                image_title = image_title[:57] + "..."
            item.setText(image_title)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setData(Qt.ItemDataRole.UserRole, img)
            self.results_list.addItem(item)
            image_url = img.get("thumbnail", "") or img.get("url", "")
            if (
                idx < self._max_preview_items
                and image_url
                and image_url.startswith(("http://", "https://"))
            ):
                self.load_image_async(item, image_url, image_title)

        if images:
            QMessageBox.information(self, "Busqueda Completada", f"Se encontraron {len(images)} imagenes.")
        else:
            QMessageBox.information(self, "Sin Resultados", "No se encontraron imagenes.")

    def on_search_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        QMessageBox.critical(self, "Error en Busqueda", error_msg)

    @staticmethod
    def _retry_after_to_ms(retry_after_value):
        if not retry_after_value:
            return None
        try:
            seconds = float(retry_after_value)
            return int(seconds * 1000) if seconds >= 0 else None
        except (TypeError, ValueError):
            return None

    def _process_next_preview_image(self):
        if not self._preview_queue:
            self._preview_loader_active = False
            return

        item, image_url, image_title, retry_count = self._preview_queue.pop(0)
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            }
            print(f" Cargando imagen: {image_title[:50]}...")
            response = requests.get(image_url, timeout=10, headers=headers)

            if response.status_code == 200:
                image_data = response.content
                if image_data:
                    pixmap = QPixmap()
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message=".*fromIccProfile.*")
                        warnings.filterwarnings("ignore", message=".*ICC.*")
                        warnings.filterwarnings("ignore", category=UserWarning)
                        if pixmap.loadFromData(image_data) and not pixmap.isNull():
                            scaled = pixmap.scaled(
                                400, 400,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            )
                            item.setIcon(QIcon(scaled))
                            print(f" Imagen cargada: {image_title[:50]}")
            elif response.status_code == 429 and retry_count < self._preview_retry_limit:
                retry_after_ms = self._retry_after_to_ms(response.headers.get("Retry-After"))
                backoff_ms = retry_after_ms if retry_after_ms is not None else int((2 ** retry_count) * 2000)
                print(f"️ Error HTTP 429 para: {image_title[:50]} (reintento en {backoff_ms / 1000:.1f}s)")
                self._preview_queue.insert(0, (item, image_url, image_title, retry_count + 1))
                QTimer.singleShot(backoff_ms, self._process_next_preview_image)
                return
            else:
                print(f"️ Error HTTP {response.status_code} para: {image_title[:50]}")
        except Exception as e:
            print(f"️ Error cargando preview de Openverse: {e}")

        QTimer.singleShot(self._preview_load_interval_ms, self._process_next_preview_image)

    def load_image_async(self, item, image_url, image_title):
        self._preview_queue.append((item, image_url, image_title, 0))
        if not self._preview_loader_active:
            self._preview_loader_active = True
            QTimer.singleShot(0, self._process_next_preview_image)

    def on_selection_changed(self):
        self.select_btn.setEnabled(self.results_list.currentItem() is not None)

    def select_current_image(self):
        current_item = self.results_list.currentItem()
        if current_item:
            self.select_image(current_item)

    def select_image(self, item):
        try:
            image_data = item.data(Qt.ItemDataRole.UserRole)
            if not image_data:
                return

            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            self.select_btn.setEnabled(False)

            output_dir = Path("auto_videos") / "images" / "bing_images"
            output_dir.mkdir(parents=True, exist_ok=True)
            image_title = str(image_data.get("title", "image"))
            for char in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
                image_title = image_title.replace(char, "_")
            image_title = "_".join(image_title.split())[:50]
            image_url = str(image_data.get("url", "")).strip()
            if not image_url:
                raise Exception("No hay URL de descarga disponible")

            url_hash = abs(hash(image_url)) % 100000
            output_path = output_dir / f"bing_{url_hash}_{image_title}.jpg"

            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            response = requests.get(image_url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not content_type.startswith("image/"):
                raise Exception(f"El archivo descargado no es una imagen (tipo: {content_type})")

            max_size = 50 * 1024 * 1024
            downloaded = 0
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        downloaded += len(chunk)
                        if downloaded > max_size:
                            raise Exception("La imagen es demasiado grande (maximo 50MB)")
                        f.write(chunk)

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise Exception("El archivo descargado esta vacio")

            self.selected_image_path = str(output_path)
            self.progress_bar.setVisible(False)
            self.accept()

        except Exception as e:
            self.progress_bar.setVisible(False)
            self.select_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", f"Error descargando imagen:\n{e}")


# Compatibilidad para imports legacy
GoogleImagesSearchDialog = BingImagesSearchDialog
