# pexels_video_search_dialog.py
"""
DiÃ¡logo PexelsVideoSearchDialog.
ExtraÃ­do de timeline_editor_widget.py para mejorar la organizaciÃ³n del cÃ³digo.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QMessageBox, QScrollArea, QWidget, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QIcon, QColor, QPainter, QPen, QFont
from pathlib import Path
import os
import requests
import warnings

# Importar cliente de Pexels y verificar disponibilidad
try:
    from pipeline.auto_video_generator_v2 import ResourceDownloader
    PEXELS_AVAILABLE = True
except ImportError:
    PEXELS_AVAILABLE = False
    ResourceDownloader = None

# Importar worker desde timeline_workers
try:
    from timeline_workers import PexelsVideoSearchWorker
except ImportError:
    PexelsVideoSearchWorker = None
    if PEXELS_AVAILABLE:
        print("âš ï¸ timeline_workers.py no encontrado. PexelsVideoSearchWorker no estarÃ¡ disponible.")

class PexelsThumbnailWorker(QThread):
    """Worker para descargar miniaturas de Pexels sin bloquear la UI."""
    thumbnail_loaded = pyqtSignal(object, object, str)  # item, image_bytes, title
    thumbnail_failed = pyqtSignal(object, str)  # item, title

    def __init__(self, item, thumbnail_url, title):
        super().__init__()
        self.item = item
        self.thumbnail_url = thumbnail_url
        self.title = title

    def run(self):
        try:
            response = requests.get(
                self.thumbnail_url,
                timeout=10,
                headers={'User-Agent': 'VideoOptimizerPro/1.0'}
            )
            response.raise_for_status()
            self.thumbnail_loaded.emit(self.item, response.content, self.title)
        except Exception:
            self.thumbnail_failed.emit(self.item, self.title)


class PexelsVideoSearchDialog(QDialog):
    """DiÃ¡logo para buscar y seleccionar videos de Pexels"""
    
    # Variable de clase para mantener resultados entre instancias
    _previous_results = {}  # {query: [videos]}
    
    def __init__(self, parent=None, segment_data=None):
        super().__init__(parent)
        self.segment_data = segment_data or {}
        self.selected_video_path = None
        self.videos = []
        self.worker = None  # Inicializar worker como None
        self.thumbnail_workers = []
        
        self.setWindowTitle("ðŸŽ¬ Buscar Videos en Pexels")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 900)  # TamaÃ±o inicial mÃ¡s grande
        
        self.setup_ui()
        
        # Cargar resultados anteriores si existen
        self.load_previous_results()
    
    def closeEvent(self, event):
        """Limpia recursos al cerrar el diÃ¡logo"""
        try:
            # Detener worker si estÃ¡ ejecutÃ¡ndose
            if self.worker and self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(1000)  # Esperar hasta 1 segundo
            for thumb_worker in list(self.thumbnail_workers):
                try:
                    if thumb_worker and thumb_worker.isRunning():
                        thumb_worker.terminate()
                        thumb_worker.wait(500)
                except Exception:
                    pass
            self.thumbnail_workers.clear()
        except Exception as e:
            print(f"âš ï¸ Error limpiando worker: {e}")
        finally:
            event.accept()
    
    def setup_ui(self):
        """Configura la interfaz del diÃ¡logo"""
        layout = QVBoxLayout(self)
        
        # Campo de bÃºsqueda
        search_layout = QHBoxLayout()
        search_label = QLabel("ðŸ” Buscar:")
        search_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Ej: nature, ocean, city, etc.")
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
        # TamaÃ±o mÃ¡s grande para las miniaturas de video
        self.results_list.setIconSize(QPixmap(300, 200).size())
        self.results_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.results_list.setSpacing(15)  # Espaciado entre items (aumentado)
        self.results_list.setGridSize(QPixmap(350, 300).size())  # TamaÃ±o de la celda aumentado
        self.results_list.itemDoubleClicked.connect(self.select_video)
        # Hacer que el Ã¡rea de resultados use todo el espacio disponible
        scroll_layout.addWidget(self.results_list, 1)
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)  # El Ã¡rea de scroll usa todo el espacio disponible
        
        # InformaciÃ³n sobre duraciÃ³n del segmento
        segment_duration = self.segment_data.get('duration', 0) or (
            self.segment_data.get('end', 0) - self.segment_data.get('start', 0)
        )
        if segment_duration > 0:
            info_label = QLabel(
                f"â±ï¸ DuraciÃ³n del segmento: {segment_duration:.1f}s\n"
                "El video se ajustarÃ¡ automÃ¡ticamente (recortar o loop) para calzar con esta duraciÃ³n."
            )
            info_label.setStyleSheet("color: #14a085; font-size: 9pt; padding: 5px;")
            layout.addWidget(info_label)
        
        # Botones
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
        
        layout.addLayout(buttons_layout)
        
        # Conectar selecciÃ³n de item
        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)
    
    def load_previous_results(self):
        """Carga resultados de bÃºsquedas anteriores"""
        if self._previous_results:
            for query, videos in self._previous_results.items():
                for video in videos:
                    item = QListWidgetItem()
                    video_title = f"Video de Pexels"
                    item.setText(video_title)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setData(Qt.ItemDataRole.UserRole, video)
                    
                    # Intentar cargar miniatura (Pexels no proporciona miniaturas directamente,
                    # pero podemos mostrar un icono de video)
                    item.setIcon(QIcon("ðŸŽ¬"))  # Icono simple
                    
                    self.results_list.addItem(item)
                    self.videos.append(video)
            
            if self._previous_results:
                separator = QListWidgetItem("â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”")
                separator.setFlags(Qt.ItemFlag.NoItemFlags)
                self.results_list.insertItem(0, separator)
    
    def perform_search(self):
        """Realiza la bÃºsqueda de videos"""
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "BÃºsqueda VacÃ­a", "Por favor ingresa un tÃ©rmino de bÃºsqueda.")
            return
        
        if not PEXELS_AVAILABLE:
            QMessageBox.warning(
                self,
                "Pexels no disponible",
                "El cliente de Pexels no estÃ¡ disponible.\n"
                "AsegÃºrate de que auto_video_generator_v2.py estÃ© en el directorio del proyecto.\n\n"
                "TambiÃ©n necesitas configurar PEXELS_API_KEY en tu archivo .env"
            )
            return
        
        if not PexelsVideoSearchWorker:
            QMessageBox.warning(
                self,
                "Pexels no disponible",
                "El worker de bÃºsqueda de Pexels no estÃ¡ disponible.\n"
                "AsegÃºrate de que timeline_workers.py estÃ© en el directorio del proyecto."
            )
            return
        
        # Limpiar resultados anteriores
        self.results_list.clear()
        self.videos = []
        self.select_btn.setEnabled(False)
        
        # Mostrar progreso
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminado
        self.search_btn.setEnabled(False)
        
        # Obtener texto de narraciÃ³n del segmento
        narration_text = self.segment_data.get('text', '') if self.segment_data else ''
        
        # Crear worker y buscar
        try:
            self.worker = PexelsVideoSearchWorker(query, narration_text)
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
        
        # Guardar resultados anteriores
        query = self.search_input.text().strip()
        if query and videos:
            if query not in self._previous_results:
                self._previous_results[query] = []
            existing_urls = {v.get('url') for v in self._previous_results[query]}
            new_videos = [v for v in videos if v.get('url') not in existing_urls]
            self._previous_results[query].extend(new_videos)
        
        # Agregar nuevos videos a la lista actual
        self.videos.extend(videos)
        
        # Mostrar resultados
        for video in videos:
            item = QListWidgetItem()
            item.setText("ðŸŽ¬ Video de Pexels")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setData(Qt.ItemDataRole.UserRole, video)
            
            # Agregar item primero
            self.results_list.addItem(item)
            
            # Cargar miniatura de forma asÃ­ncrona
            thumbnail_url = video.get('image')
            if thumbnail_url and thumbnail_url.startswith(('http://', 'https://')):
                self.load_thumbnail_async(item, thumbnail_url, "Video de Pexels")
            else:
                self._set_fallback_thumbnail(item, "Video de Pexels")
        
        if not videos:
            QMessageBox.information(
                self,
                "Sin Resultados",
                f"No se encontraron videos para: {query}\n\n"
                "Intenta con tÃ©rminos mÃ¡s generales o en inglÃ©s."
            )
    
    def _set_fallback_thumbnail(self, item, title):
        """Asigna un thumbnail de fallback cuando no hay imagen."""
        try:
            pixmap = QPixmap(300, 200)
            pixmap.fill(QColor(30, 30, 30))
            painter = QPainter(pixmap)
            painter.setPen(QPen(QColor(220, 220, 220), 2))
            painter.setFont(QFont("Arial", 18))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "VIDEO")
            painter.end()
            item.setIcon(QIcon(pixmap))
            item.setText(title)
        except Exception as e:
            print(f"Error asignando thumbnail fallback: {e}")

    def _cleanup_thumbnail_worker(self, worker):
        """Limpia referencias de workers de miniaturas finalizados."""
        try:
            if worker in self.thumbnail_workers:
                self.thumbnail_workers.remove(worker)
        except Exception:
            pass

    def _on_thumbnail_loaded(self, item, image_bytes, title):
        """Callback cuando la miniatura se descarga correctamente."""
        try:
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_bytes):
                self._set_fallback_thumbnail(item, title)
                return

            scaled = pixmap.scaled(
                300,
                200,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            item.setIcon(QIcon(scaled))
            item.setText(title)
        except Exception:
            self._set_fallback_thumbnail(item, title)

    def _on_thumbnail_failed(self, item, title):
        """Callback cuando falla la descarga de miniatura."""
        self._set_fallback_thumbnail(item, title)

    def load_thumbnail_async(self, item, thumbnail_url, title):
        """Descarga miniatura en segundo plano y actualiza el item al finalizar."""
        self._set_fallback_thumbnail(item, title)

        worker = PexelsThumbnailWorker(item, thumbnail_url, title)
        worker.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        worker.thumbnail_failed.connect(self._on_thumbnail_failed)
        worker.finished.connect(lambda w=worker: self._cleanup_thumbnail_worker(w))
        self.thumbnail_workers.append(worker)
        worker.start()

    def on_search_error(self, error_msg):
        """Callback cuando hay un error en la bÃºsqueda"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        QMessageBox.warning(self, "Error en BÃºsqueda", error_msg)
    
    def on_selection_changed(self):
        """Callback cuando cambia la selecciÃ³n"""
        has_selection = len(self.results_list.selectedItems()) > 0
        self.select_btn.setEnabled(has_selection)
        if hasattr(self, 'preview_btn'):
            self.preview_btn.setEnabled(has_selection)
    
    def preview_selected_video(self):
        """Abre un diÃ¡logo para previsualizar el video seleccionado"""
        selected_items = self.results_list.selectedItems()
        if not selected_items:
            return
        
        selected_item = selected_items[0]
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
        """Selecciona el video actualmente seleccionado en la lista"""
        selected_items = self.results_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Sin SelecciÃ³n", "Por favor selecciona un video de la lista.")
            return
        
        item = selected_items[0]
        video_data = item.data(Qt.ItemDataRole.UserRole)
        self.select_video(video_data)
    
    def select_video(self, video_data_or_item):
        """Descarga y selecciona un video, ajustando su duraciÃ³n si es necesario"""
        # Manejar si se pasa el item o los datos directamente
        if isinstance(video_data_or_item, QListWidgetItem):
            video_data = video_data_or_item.data(Qt.ItemDataRole.UserRole)
        else:
            video_data = video_data_or_item
        
        if not video_data:
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.select_btn.setEnabled(False)
        
        try:
            # Crear directorio para videos de Pexels si no existe
            pexels_dir = Path("auto_videos") / "videos" / "pexels"
            pexels_dir.mkdir(parents=True, exist_ok=True)
            
            # Generar nombre de archivo Ãºnico
            video_url = video_data.get('url', '')
            filename = f"pexels_{hash(video_url) % 100000}.mp4"
            output_path = pexels_dir / filename
            
            # Si el archivo ya existe, verificar si necesita ajuste de duraciÃ³n
            if os.path.exists(output_path):
                segment_duration = self.segment_data.get('duration', 0) or (
                    self.segment_data.get('end', 0) - self.segment_data.get('start', 0)
                )
                if segment_duration > 0:
                    try:
                        from moviepy.editor import VideoFileClip
                        video_clip = VideoFileClip(str(output_path))
                        video_duration = video_clip.duration
                        video_clip.close()
                        
                        # Si la duraciÃ³n no coincide, necesitamos ajustar
                        if abs(video_duration - segment_duration) > 0.5:  # Tolerancia de 0.5s
                            # Continuar con el ajuste
                            pass
                        else:
                            # La duraciÃ³n ya es correcta
                            self.selected_video_path = str(output_path)
                            self.progress_bar.setVisible(False)
                            self.accept()
                            return
                    except:
                        # Si falla la verificaciÃ³n, usar el archivo tal cual
                        self.selected_video_path = str(output_path)
                        self.progress_bar.setVisible(False)
                        self.accept()
                        return
                else:
                    # Sin duraciÃ³n especÃ­fica, usar el video tal cual
                    self.selected_video_path = str(output_path)
                    self.progress_bar.setVisible(False)
                    self.accept()
                    return
            
            # Descargar video
            from pipeline.auto_video_generator_v2 import ResourceDownloader
            # Alias para compatibilidad
            StockMediaDownloader = ResourceDownloader
            downloader = StockMediaDownloader()
            downloaded_path = downloader.download_video(video_data, str(output_path))
            
            if downloaded_path and os.path.exists(downloaded_path):
                # Ajustar duraciÃ³n del video si es necesario
                segment_duration = self.segment_data.get('duration', 0) or (
                    self.segment_data.get('end', 0) - self.segment_data.get('start', 0)
                )
                
                if segment_duration > 0:
                    try:
                        from moviepy.editor import VideoFileClip
                        import moviepy.video.fx.all as vfx
                        
                        video_clip = VideoFileClip(downloaded_path)
                        video_duration = video_clip.duration
                        
                        # Si el video es mÃ¡s corto que la duraciÃ³n requerida, hacer loop
                        if video_duration < segment_duration:
                            # Hacer loop del video
                            adjusted_path = str(output_path).replace('.mp4', '_adjusted.mp4')
                            looped_clip = video_clip.fx(vfx.loop, duration=segment_duration)
                            looped_clip.write_videofile(
                                adjusted_path,
                                codec='libx264',
                                audio_codec='aac',
                                verbose=False,
                                logger=None
                            )
                            looped_clip.close()
                            video_clip.close()
                            
                            # Reemplazar el archivo original con el ajustado
                            if os.path.exists(adjusted_path):
                                if os.path.exists(output_path):
                                    os.remove(output_path)
                                os.rename(adjusted_path, output_path)
                            
                            self.selected_video_path = str(output_path)
                        # Si el video es mÃ¡s largo, recortarlo
                        elif video_duration > segment_duration:
                            adjusted_path = str(output_path).replace('.mp4', '_adjusted.mp4')
                            trimmed_clip = video_clip.subclip(0, segment_duration)
                            trimmed_clip.write_videofile(
                                adjusted_path,
                                codec='libx264',
                                audio_codec='aac',
                                verbose=False,
                                logger=None
                            )
                            trimmed_clip.close()
                            video_clip.close()
                            
                            # Reemplazar el archivo original con el ajustado
                            if os.path.exists(adjusted_path):
                                if os.path.exists(output_path):
                                    os.remove(output_path)
                                os.rename(adjusted_path, output_path)
                            
                            self.selected_video_path = str(output_path)
                        else:
                            # La duraciÃ³n es exacta, usar el video tal cual
                            self.selected_video_path = str(output_path)
                            video_clip.close()
                    except Exception as e:
                        # Si falla el ajuste, usar el video original
                        print(f"âš ï¸ Advertencia: No se pudo ajustar la duraciÃ³n del video: {e}")
                        self.selected_video_path = str(output_path)
                else:
                    # Sin duraciÃ³n especÃ­fica, usar el video tal cual
                    self.selected_video_path = str(output_path)
                
                self.progress_bar.setVisible(False)
                self.accept()
            else:
                self.progress_bar.setVisible(False)
                self.select_btn.setEnabled(True)
                QMessageBox.critical(
                    self,
                    "Error",
                    "No se pudo descargar el video. Intenta con otro."
                )
        
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.select_btn.setEnabled(True)
            QMessageBox.critical(
                self,
                "Error",
                f"Error descargando video:\n{str(e)}"
            )


# ========== VIDEO PREVIEW DIALOG ==========

