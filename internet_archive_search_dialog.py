# internet_archive_search_dialog.py
"""
Diálogo InternetArchiveVideoSearchDialog.
Extraído de timeline_editor_widget.py para mejorar la organización del código.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QMessageBox, QScrollArea, QWidget, QCheckBox, QGroupBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPixmap, QIcon
from pathlib import Path
import os
import requests
import warnings

# Importar Internet Archive client
try:
    from internet_archive_client import InternetArchiveClient
    INTERNET_ARCHIVE_AVAILABLE = True
except ImportError:
    INTERNET_ARCHIVE_AVAILABLE = False
    InternetArchiveClient = None
    print("️ internet_archive_client.py no encontrado. Internet Archive no estará disponible.")

# Importar VideoTimelineWidget
try:
    from timeline_video_widget import VideoTimelineWidget
except ImportError:
    VideoTimelineWidget = None
    print("️ timeline_video_widget.py no encontrado. VideoTimelineWidget no estará disponible.")

# Importar workers
try:
    from timeline_workers import InternetArchiveVideoSearchWorker, VideoFrameExtractorWorker
except ImportError:
    InternetArchiveVideoSearchWorker = None
    VideoFrameExtractorWorker = None
    print("️ Workers no encontrados en timeline_workers.py")

# Importar attribution manager
try:
    from attribution_manager import get_attribution_manager
    ATTRIBUTION_AVAILABLE = True
except ImportError:
    ATTRIBUTION_AVAILABLE = False
    get_attribution_manager = None

class InternetArchiveVideoSearchDialog(QDialog):
    """Diálogo para buscar y seleccionar videos históricos de Internet Archive"""

    _previous_results = {}

    def __init__(self, parent=None, segment_data=None):
        super().__init__(parent)
        self.segment_data = segment_data or {}
        self.selected_video_path = None
        self.videos = []

        # Variables para reproducción
        self.is_playing = False
        self.current_video_path = None
        self.video_clip = None
        self.playback_timer = None
        self.playback_position = 0.0
        self.video_duration = 0.0

        # Worker para extraer frames del video
        self.frame_extractor_worker = None
        self._current_video_url = None

        self.setWindowTitle("️ Buscar Videos Históricos en Internet Archive")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 900)  # Tamaño inicial más grande

        self.setup_ui()
        self.load_previous_results()

        suggested_query = self.suggest_query_from_segment(self.segment_data)
        if suggested_query:
            self.search_input.setText(suggested_query)
    
    def preview_selected_video(self):
        """Prepara o reproduce el preview inline del video seleccionado."""
        selected_item = self.results_list.currentItem()
        if not selected_item:
            return

        video_data = selected_item.data(Qt.ItemDataRole.UserRole)
        if not video_data:
            QMessageBox.warning(self, "Error", "No se pudo obtener la información del video.")
            return

        if self.current_video_path and self._can_use_media_path(self.current_video_path):
            self.toggle_playback()
            return

        video_source = str(video_data.get('source', '') or '').strip().lower()
        video_url = video_data.get('url', '') or video_data.get('video_url', '')
        preview_url = video_data.get('preview_url', '') or video_url

        if not preview_url:
            QMessageBox.warning(self, "Preview no disponible", "No se encontró una URL válida para previsualizar este video.")
            return

        self._start_frame_extraction(preview_url, video_source or 'internet_archive')

    def setup_ui(self):
        """Configura la interfaz del diálogo"""
        layout = QVBoxLayout(self)
        
        search_layout = QHBoxLayout()
        search_label = QLabel(" Buscar:")
        search_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Ej: World War II, Apollo 11, Berlin Wall 1989, etc.")
        self.search_input.returnPressed.connect(self.perform_search)
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton(" Buscar")
        self.search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(self.search_btn)
        
        layout.addLayout(search_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Área de scroll para el contenido principal
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Widget contenedor para el contenido desplazable
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        results_label = QLabel("Resultados:")
        scroll_layout.addWidget(results_label)
        
        self.results_list = QListWidget()
        # Usar IconMode para mostrar mejor las miniaturas con vista previa
        self.results_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.results_list.setIconSize(QSize(120, 90))  # Tamaño de los thumbnails
        self.results_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.results_list.setSpacing(10)  # Espacio entre items
        self.results_list.setGridSize(QSize(160, 180))  # Tamaño de la celda (thumbnail + texto)
        self.results_list.itemDoubleClicked.connect(self.select_video)
        # Hacer que el área de resultados use todo el espacio disponible
        scroll_layout.addWidget(self.results_list, 1)

        # Grupo de controles de recorte
        crop_group = QGroupBox("️ Recortar Video (Opcional)")
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

        # Widget de video para reproducción
        self.video_label = QLabel()
        self.video_label.setMinimumHeight(200)
        self.video_label.setMaximumHeight(250)
        self.video_label.setStyleSheet("background-color: #0a0a0a; border-radius: 4px;")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setText("Selecciona un video y presiona Play")
        self.video_label.setVisible(True)
        crop_layout.addWidget(self.video_label)

        # Barra de progreso para carga de video
        self.video_loading_progress = QProgressBar()
        self.video_loading_progress.setVisible(False)
        self.video_loading_progress.setTextVisible(True)
        self.video_loading_progress.setFormat("Cargando video... %p%")
        crop_layout.addWidget(self.video_loading_progress)

        # Widget de timeline de video (similar a CapCut)
        self.video_timeline = VideoTimelineWidget()
        self.video_timeline.setEnabled(False)
        self.video_timeline.crop_range_changed.connect(self.on_timeline_crop_changed)
        self.video_timeline.position_clicked.connect(self.on_timeline_position_clicked)
        self.video_timeline.position_dragged.connect(self.on_timeline_position_dragged)
        crop_layout.addWidget(self.video_timeline)

        # Controles de reproducción
        playback_controls_layout = QHBoxLayout()
        playback_controls_layout.addStretch()

        self.play_btn = QPushButton("️ Play")
        self.play_btn.setEnabled(False)
        self.play_btn.setMaximumWidth(80)
        self.play_btn.clicked.connect(self.toggle_playback)
        playback_controls_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("️ Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMaximumWidth(80)
        self.stop_btn.clicked.connect(self.stop_playback)
        playback_controls_layout.addWidget(self.stop_btn)

        # Botón para reproducir solo el tramo recortado
        self.play_crop_btn = QPushButton(" Play Recorte")
        self.play_crop_btn.setEnabled(False)
        self.play_crop_btn.setMaximumWidth(120)
        self.play_crop_btn.setToolTip("Reproducir solo el tramo seleccionado (entre las barras amarillas)")
        self.play_crop_btn.clicked.connect(self.play_crop_range)
        playback_controls_layout.addWidget(self.play_crop_btn)

        playback_controls_layout.addStretch()
        crop_layout.addLayout(playback_controls_layout)

        crop_controls_layout = QHBoxLayout()

        # Inicio
        start_label = QLabel("Inicio:")
        crop_controls_layout.addWidget(start_label)
        self.video_crop_start = QDoubleSpinBox()
        self.video_crop_start.setMinimum(0.0)
        self.video_crop_start.setMaximum(86400.0)  # Máximo 24 horas
        self.video_crop_start.setDecimals(2)
        self.video_crop_start.setSuffix(" s")
        self.video_crop_start.setValue(0.0)
        self.video_crop_start.setEnabled(False)
        self.video_crop_start.valueChanged.connect(self.on_crop_start_changed)
        crop_controls_layout.addWidget(self.video_crop_start)

        crop_controls_layout.addStretch()

        # Fin
        end_label = QLabel("Fin:")
        crop_controls_layout.addWidget(end_label)
        self.video_crop_end = QDoubleSpinBox()
        self.video_crop_end.setMinimum(0.0)
        self.video_crop_end.setMaximum(86400.0)  # Máximo 24 horas
        self.video_crop_end.setDecimals(2)
        self.video_crop_end.setSuffix(" s")
        self.video_crop_end.setValue(0.0)
        self.video_crop_end.setEnabled(False)
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
        layout.addWidget(scroll_area, 1)  # El área de scroll usa todo el espacio disponible

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.preview_btn = QPushButton("️ Preview")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self.preview_selected_video)
        self.preview_btn.setToolTip("Previsualizar el video seleccionado")
        buttons_layout.addWidget(self.preview_btn)

        self.select_btn = QPushButton(" Seleccionar Video")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.select_current_video)
        buttons_layout.addWidget(self.select_btn)

        cancel_btn = QPushButton(" Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)

        layout.addLayout(buttons_layout)

        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)
    
    def load_previous_results(self):
        """Carga resultados de búsquedas anteriores"""
        if self._previous_results:
            for query, videos in self._previous_results.items():
                for video in videos:
                    try:
                        item = QListWidgetItem()
                        title = video.get('title', 'Video histórico') or 'Video histórico'
                        date = video.get('date', '') or ''
                        creator = video.get('creator', '') or ''
                        duration_raw = video.get('duration', 0) or 0
                        thumbnail_url = video.get('thumbnail', '') or video.get('thumbnail_url', '')
                        
                        # Convertir duración a float/int si es string
                        try:
                            duration = float(duration_raw) if duration_raw else 0
                        except (ValueError, TypeError):
                            duration = 0
                        
                        # Formatear duración de forma más legible
                        if duration > 0:
                            hours = int(duration // 3600)
                            minutes = int((duration % 3600) // 60)
                            seconds = int(duration % 60)
                            if hours > 0:
                                duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                            else:
                                duration_str = f"{minutes}:{seconds:02d}"
                        else:
                            duration_str = "N/A"

                        # Formatear texto para IconMode (más compacto) con duración
                        info_text = f"{title[:60]}\n"
                        if date:
                            info_text += f" {date[:20]}\n"
                        if creator:
                            info_text += f" {creator[:30]}\n"
                        info_text += f"️ {duration_str}"

                        item.setText(info_text)
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setData(Qt.ItemDataRole.UserRole, video)

                        # Cargar miniatura si está disponible
                        if thumbnail_url:
                            try:
                                import requests
                                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                                response = requests.get(thumbnail_url, timeout=10, headers=headers, stream=True)
                                if response.status_code == 200:
                                    image_data = response.content
                                    pixmap = QPixmap()
                                    if pixmap.loadFromData(image_data):
                                        if not pixmap.isNull():
                                            scaled_pixmap = pixmap.scaled(
                                                120, 90,
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation
                                            )
                                            icon = QIcon(scaled_pixmap)
                                            item.setIcon(icon)
                            except Exception:
                                pass  # Continuar sin miniatura si falla

                        self.results_list.addItem(item)
                        self.videos.append(video)
                    except Exception as e:
                        print(f"️ Error cargando resultado previo: {e}")
                        continue
    
    def suggest_query_from_segment(self, segment_data):
        """Sugiere un término de búsqueda basado en el segmento"""
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
        """Realiza la búsqueda de videos"""
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Búsqueda Vacía", "Por favor ingresa un término de búsqueda.")
            return
        
        if not INTERNET_ARCHIVE_AVAILABLE:
            QMessageBox.warning(
                self,
                "Internet Archive no disponible",
                "El cliente de Internet Archive no está disponible."
            )
            return
        
        self.results_list.clear()
        self.videos = []
        self.select_btn.setEnabled(False)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.search_btn.setEnabled(False)
        
        narration_text = self.segment_data.get('text', '') if self.segment_data else ''
        
        self.worker = InternetArchiveVideoSearchWorker(query, narration_text)
        self.worker.finished.connect(self.on_search_finished)
        self.worker.error.connect(self.on_search_error)
        self.worker.progress.connect(lambda msg: self.progress_bar.setFormat(msg))
        self.worker.start()
    
    def on_search_finished(self, videos):
        """Callback cuando la búsqueda termina exitosamente"""
        try:
            self.progress_bar.setVisible(False)
            self.search_btn.setEnabled(True)
            
            if not videos:
                return
            
            query = self.search_input.text().strip()
            if query and videos:
                try:
                    if query not in self._previous_results:
                        self._previous_results[query] = []
                    existing_urls = {v.get('url', '') for v in self._previous_results[query] if v.get('url')}
                    new_videos = [v for v in videos if v.get('url') and v.get('url') not in existing_urls]
                    if new_videos:
                        self._previous_results[query].extend(new_videos)
                except Exception as e:
                    print(f"️ Error procesando resultados previos: {e}")
            
            try:
                self.videos.extend(videos)
            except Exception as e:
                print(f"️ Error agregando videos a la lista: {e}")
            
            # Procesar videos de forma segura
            for video in videos:
                try:
                    if not isinstance(video, dict):
                        continue

                    item = QListWidgetItem()
                    title = video.get('title', 'Video histórico') or 'Video histórico'
                    date = video.get('date', '') or ''
                    creator = video.get('creator', '') or ''
                    duration_raw = video.get('duration', 0) or 0
                    thumbnail_url = video.get('thumbnail', '') or video.get('thumbnail_url', '')

                    # Limpiar strings para evitar problemas
                    if isinstance(title, str):
                        title = title[:60]  # Limitar longitud para IconMode
                    if isinstance(date, str):
                        date = date[:20]
                    if isinstance(creator, str):
                        creator = creator[:30]
                    
                    # Convertir duración a float/int si es string
                    try:
                        duration = float(duration_raw) if duration_raw else 0
                    except (ValueError, TypeError):
                        duration = 0
                    
                    # Formatear duración de forma más legible
                    if duration > 0:
                        hours = int(duration // 3600)
                        minutes = int((duration % 3600) // 60)
                        seconds = int(duration % 60)
                        if hours > 0:
                            duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                        else:
                            duration_str = f"{minutes}:{seconds:02d}"
                    else:
                        duration_str = "N/A"

                    # Formatear texto para IconMode (más compacto) con duración
                    info_text = f"{title[:60]}\n"
                    if date:
                        info_text += f" {date}\n"
                    if creator:
                        info_text += f" {creator[:30]}\n"
                    info_text += f"️ {duration_str}"

                    item.setText(info_text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setData(Qt.ItemDataRole.UserRole, video)

                    # Agregar item primero
                    self.results_list.addItem(item)

                    # Cargar thumbnail de forma asíncrona
                    if thumbnail_url and thumbnail_url.startswith(('http://', 'https://')):
                        self.load_thumbnail_async(item, thumbnail_url, title)
                except Exception as e:
                    print(f"️ Error procesando video individual: {e}")
                    continue
            
            try:
                self.on_selection_changed()
            except Exception as e:
                print(f"️ Error actualizando selección: {e}")
        
        except Exception as e:
            print(f" Error crítico en on_search_finished: {e}")
            import traceback
            traceback.print_exc()
            self.progress_bar.setVisible(False)
            self.search_btn.setEnabled(True)
            QMessageBox.warning(
                self,
                "Error",
                f"Error procesando resultados:\n{str(e)}"
            )
    
    def on_search_error(self, error_msg):
        """Callback cuando la búsqueda falla"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        QMessageBox.critical(self, "Error de Búsqueda", f"Error al buscar videos:\n{error_msg}")
    
    def load_thumbnail_async(self, item, thumbnail_url, title):
        """Carga un thumbnail de forma asíncrona usando QTimer para no bloquear la UI"""
        def load_thumbnail():
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                response = requests.get(thumbnail_url, timeout=20, headers=headers, stream=True)
                if response.status_code == 200:
                    image_data = response.content
                    if not image_data:
                        return
                    
                    pixmap = QPixmap()
                    if pixmap.loadFromData(image_data):
                        if not pixmap.isNull():
                            scaled_pixmap = pixmap.scaled(
                                120, 90,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            )
                            icon = QIcon(scaled_pixmap)
                            item.setIcon(icon)
            except Exception as e:
                print(f"️ Error cargando thumbnail de Internet Archive: {e}")
        
        QTimer.singleShot(0, load_thumbnail)
    
    def on_selection_changed(self):
        """Habilita/deshabilita el botón de seleccionar y preview, y actualiza controles de recorte"""
        has_selection = self.results_list.currentItem() is not None
        self.select_btn.setEnabled(has_selection)
        if hasattr(self, 'preview_btn'):
            self.preview_btn.setEnabled(has_selection)

        # Habilitar controles de recorte si hay selección
        if has_selection and hasattr(self, 'enable_crop_checkbox'):
            self.enable_crop_checkbox.setEnabled(True)

            # Obtener duración del video seleccionado
            selected_item = self.results_list.currentItem()
            if selected_item:
                video_data = selected_item.data(Qt.ItemDataRole.UserRole)
                if video_data:
                    video_source = str(video_data.get('source', '') or '').strip().lower()
                    video_duration = video_data.get('duration', 0) or 0
                    # Convertir duration a float si es string
                    try:
                        video_duration = float(video_duration) if video_duration else 0
                    except (ValueError, TypeError):
                        video_duration = 0

                    video_url = video_data.get('url', '') or video_data.get('video_url', '')
                    preview_url = video_data.get('preview_url', '') or video_url
                    self._reset_preview_state(clear_timeline=False)

                    if video_duration > 0:
                        # Actualizar valores máximos y establecer fin al final del video
                        if hasattr(self, 'video_crop_start'):
                            self.video_crop_start.setMaximum(video_duration)
                            self.video_crop_start.setValue(0.0)
                        if hasattr(self, 'video_crop_end'):
                            self.video_crop_end.setMaximum(video_duration)
                            self.video_crop_end.setValue(video_duration)
                        # Actualizar el timeline widget con la duración del video
                        if hasattr(self, 'video_timeline'):
                            self.video_timeline.set_video_duration(video_duration)
                            self.video_timeline.set_crop_range(0.0, video_duration)
                            self.video_timeline.setEnabled(True)

                            if preview_url and preview_url != self._current_video_url:
                                self._start_frame_extraction(preview_url, video_source or 'internet_archive')
                            elif video_source == 'internet_archive':
                                self._show_remote_preview_unavailable(video_duration)
                    else:
                        # Sin duración conocida, deshabilitar timeline
                        if hasattr(self, 'video_timeline'):
                            self.video_timeline.set_video_duration(0)
                            self.video_timeline.setEnabled(False)
        else:
            self._reset_preview_state(clear_timeline=True)
            if hasattr(self, 'enable_crop_checkbox'):
                self.enable_crop_checkbox.setEnabled(False)
                self.enable_crop_checkbox.setChecked(False)
            if hasattr(self, 'video_crop_start'):
                self.video_crop_start.setEnabled(False)
            if hasattr(self, 'video_crop_end'):
                self.video_crop_end.setEnabled(False)
            if hasattr(self, 'reset_crop_btn'):
                self.reset_crop_btn.setEnabled(False)

    def _is_remote_media_path(self, path):
        """Determina si la ruta apunta a un recurso remoto reproducible por FFmpeg."""
        text = str(path or '').strip().lower()
        return text.startswith('http://') or text.startswith('https://')

    def _can_use_media_path(self, path):
        """Valida si una ruta puede usarse para reproducción local o remota."""
        return bool(path) and (self._is_remote_media_path(path) or os.path.exists(path))

    def _set_playback_controls_enabled(self, enabled):
        """Habilita o deshabilita los controles de reproducción del preview."""
        if hasattr(self, 'play_btn'):
            self.play_btn.setEnabled(enabled)
            if not enabled:
                self.play_btn.setText("️ Play")
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(enabled)
        if hasattr(self, 'play_crop_btn'):
            self.play_crop_btn.setEnabled(enabled)

    def _reset_preview_state(self, clear_timeline):
        """Limpia el estado del preview actual para evitar cargas infinitas."""
        self._cancel_frame_extraction()
        self._stop_moviepy_playback()
        self.is_playing = False
        self.current_video_path = None
        self.playback_position = 0.0
        self._loaded_video_path = None

        if self.video_clip:
            try:
                self.video_clip.close()
            except Exception:
                pass
            self.video_clip = None

        self._set_playback_controls_enabled(False)

        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setVisible(False)
            self.video_loading_progress.setRange(0, 100)
            self.video_loading_progress.setValue(0)
            self.video_loading_progress.setFormat("Cargando video... %p%")

        if hasattr(self, 'video_label'):
            self.video_label.setText("Selecciona un video y presiona Play")

        if hasattr(self, 'fit_segment_btn'):
            self.fit_segment_btn.setEnabled(False)

        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()
            if clear_timeline:
                self.video_timeline.set_video_duration(0)
                self.video_timeline.set_video_frames([])
                self.video_timeline.setEnabled(False)

    def _show_remote_preview_unavailable(self, video_duration):
        """Muestra un estado de fallback si no se pudo preparar el preview remoto."""
        notice = (
            "No se pudo cargar el preview remoto de Internet Archive.\n"
            "Prueba otro resultado o descarga el video completo."
        )

        if hasattr(self, 'video_label'):
            self.video_label.setText(
                "No se pudo cargar el preview remoto.\n"
                "Prueba otro resultado o descarga el video."
            )

        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_video_frames([])
            self.video_timeline.set_loading_message(notice)
            self.video_timeline.setEnabled(video_duration > 0)

        if hasattr(self, 'fit_segment_btn'):
            self.fit_segment_btn.setEnabled(video_duration > 0)

    def _show_frame_in_label(self, pixmap):
        """Muestra un frame en el panel de preview respetando el tamaño del label."""
        if not hasattr(self, 'video_label') or self.video_label is None or not pixmap or pixmap.isNull():
            return

        label_size = self.video_label.size()
        scaled_pixmap = pixmap.scaled(
            max(1, label_size.width() - 10),
            max(1, label_size.height() - 10),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.video_label.setPixmap(scaled_pixmap)

    def _start_frame_extraction(self, video_url, video_source):
        """Inicia la extracción de frames del video en segundo plano"""
        self._cancel_frame_extraction()
        self._current_video_url = video_url

        # Mostrar barra de progreso
        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setVisible(True)
            self.video_loading_progress.setRange(0, 0)  # Modo indeterminado
            self.video_loading_progress.setFormat("Descargando video...")

        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_video_frames([])
            self.video_timeline.set_loading_message("Descargando video para preview...")

        # Verificar que VideoFrameExtractorWorker esté disponible
        if VideoFrameExtractorWorker is None:
            print("️ VideoFrameExtractorWorker no disponible, saltando extracción de frames")
            if hasattr(self, 'video_timeline'):
                self.video_timeline.set_loading_message("Preview no disponible")
            if hasattr(self, 'video_loading_progress'):
                self.video_loading_progress.setVisible(False)
            return

        self.frame_extractor_worker = VideoFrameExtractorWorker(video_url, video_source, num_frames=15)
        self.frame_extractor_worker.finished.connect(self._on_frames_extracted)
        self.frame_extractor_worker.error.connect(self._on_frame_extraction_error)
        self.frame_extractor_worker.progress.connect(self._on_frame_extraction_progress)
        self.frame_extractor_worker.start()

    def _cancel_frame_extraction(self):
        """Cancela la extracción de frames en progreso"""
        if self.frame_extractor_worker and self.frame_extractor_worker.isRunning():
            self.frame_extractor_worker.terminate()
            self.frame_extractor_worker.wait(1000)
        self.frame_extractor_worker = None
        self._current_video_url = None

    def _on_frames_extracted(self, video_path, frames):
        """Callback cuando se extraen los frames exitosamente"""
        # Ocultar barra de progreso
        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setVisible(False)

        self.current_video_path = None
        self._set_playback_controls_enabled(False)

        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()
            self.video_timeline.set_video_frames(frames)
            self.current_video_path = video_path
            if frames:
                self._show_frame_in_label(frames[0])

            # Habilitar botones de reproducción
            if hasattr(self, 'play_btn'):
                self.play_btn.setEnabled(True)
            if hasattr(self, 'stop_btn'):
                self.stop_btn.setEnabled(True)
            if hasattr(self, 'play_crop_btn'):
                self.play_crop_btn.setEnabled(True)
            if hasattr(self, 'fit_segment_btn'):
                self.fit_segment_btn.setEnabled(True)

            print(f" Video listo para reproducir: {video_path}")

    def _on_frame_extraction_error(self, error_msg):
        """Callback cuando falla la extracción de frames"""
        print(f"️ Error extrayendo frames: {error_msg}")

        # Ocultar barra de progreso
        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setVisible(False)

        self.current_video_path = None
        self._set_playback_controls_enabled(False)

        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()

    def _on_frame_extraction_progress(self, message):
        """Callback para actualizar el progreso de extracción"""
        # Actualizar barra de progreso con mensaje
        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setFormat(message)

        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_loading_message(message)

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

    def on_crop_start_changed(self, value):
        """Callback cuando se cambia el inicio desde el spinbox"""
        if hasattr(self, 'video_timeline'):
            end_time = self.video_crop_end.value() if hasattr(self, 'video_crop_end') else self.video_timeline.end_time
            self.video_timeline.set_crop_range(value, end_time)

    def on_crop_end_changed(self, value):
        """Callback cuando se cambia el fin desde el spinbox"""
        if hasattr(self, 'video_timeline'):
            start_time = self.video_crop_start.value() if hasattr(self, 'video_crop_start') else self.video_timeline.start_time
            self.video_timeline.set_crop_range(start_time, value)

    def on_crop_checkbox_changed(self, state):
        """Habilita/deshabilita los controles de recorte según el checkbox"""
        enabled = (state == Qt.CheckState.Checked.value)
        if hasattr(self, 'video_crop_start'):
            self.video_crop_start.setEnabled(enabled)
        if hasattr(self, 'video_crop_end'):
            self.video_crop_end.setEnabled(enabled)
        if hasattr(self, 'reset_crop_btn'):
            self.reset_crop_btn.setEnabled(enabled)

    def reset_crop_range(self):
        """Resetea los valores de recorte a los valores por defecto"""
        selected_item = self.results_list.currentItem()
        if selected_item:
            video_data = selected_item.data(Qt.ItemDataRole.UserRole)
            if video_data:
                video_duration = video_data.get('duration', 0) or 0
                # Convertir a float si es necesario (puede venir como string)
                try:
                    video_duration = float(video_duration) if video_duration else 0
                except (ValueError, TypeError):
                    video_duration = 0
                if hasattr(self, 'video_crop_start'):
                    self.video_crop_start.setValue(0.0)
                if hasattr(self, 'video_crop_end'):
                    self.video_crop_end.setValue(video_duration if video_duration > 0 else 0.0)
                if hasattr(self, 'video_timeline'):
                    self.video_timeline.set_crop_range(0.0, video_duration if video_duration > 0 else 0.0)

    def fit_crop_to_segment(self):
        """Ajusta el recorte para que coincida con la duración del segmento"""
        # Obtener la duración del segmento actual
        segment_duration = 0.0
        if hasattr(self, 'segment_data') and self.segment_data:
            # Primero intentar con 'duration' directo
            segment_duration = self.segment_data.get('duration', 0) or 0
            # Si no hay 'duration', calcular desde 'start' y 'end'
            if segment_duration <= 0:
                start = self.segment_data.get('start', 0) or 0
                end = self.segment_data.get('end', 0) or 0
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
            video_duration = self.video_timeline.duration
        elif hasattr(self, 'video_duration'):
            video_duration = self.video_duration

        if video_duration <= 0:
            QMessageBox.warning(self, "Sin video", "Primero selecciona un video.")
            return

        if segment_duration > video_duration:
            QMessageBox.warning(
                self,
                "Segmento muy largo",
                f"La duración del segmento ({segment_duration:.1f}s) es mayor que la del video ({video_duration:.1f}s).\n\n"
                "Se usará todo el video."
            )
            segment_duration = video_duration

        # Obtener posición actual de la barra azul como punto de inicio
        current_position = 0.0
        if hasattr(self, 'video_timeline'):
            current_position = self.video_timeline.current_position
        elif hasattr(self, 'playback_position'):
            current_position = self.playback_position

        # Calcular nuevo inicio y fin
        new_start = current_position
        new_end = new_start + segment_duration

        # Ajustar si se sale del video
        if new_end > video_duration:
            new_end = video_duration
            new_start = max(0.0, video_duration - segment_duration)

        # Aplicar el recorte
        if hasattr(self, 'video_crop_start'):
            self.video_crop_start.setValue(new_start)
        if hasattr(self, 'video_crop_end'):
            self.video_crop_end.setValue(new_end)
        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_crop_range(new_start, new_end)

        print(f" Recorte ajustado a duración del segmento: {new_start:.1f}s - {new_end:.1f}s ({segment_duration:.1f}s)")

    # preview_selected_video ya está definido arriba en __init__ - no duplicar

    def on_timeline_position_clicked(self, position):
        """Callback cuando se hace click en el timeline para cambiar posición"""
        self.playback_position = position
        self.video_timeline.set_current_position(position)
        print(f" Posición cambiada a {position:.1f}s")

        # Si está reproduciendo con moviepy, la posición se usará en el próximo frame
        if self.is_playing and self.video_clip:
            pass

    def on_timeline_position_dragged(self, position):
        """Callback cuando se arrastra la barra azul de posición"""
        self.playback_position = position

        # Si está reproduciendo, detener temporalmente para mostrar el frame actual
        if self.is_playing:
            self._stop_moviepy_playback()
            self.is_playing = False
            if hasattr(self, 'play_btn'):
                self.play_btn.setText("️ Play")

        # Mostrar el frame en la posición actual
        if self.video_clip:
            try:
                from PyQt6.QtGui import QImage, QPixmap
                from PyQt6.QtCore import Qt

                frame = self.video_clip.get_frame(position)
                height, width, channel = frame.shape
                bytes_per_line = 3 * width
                q_img = QImage(frame.tobytes(), width, height, bytes_per_line, QImage.Format.Format_RGB888)

                if hasattr(self, 'video_label') and self.video_label:
                    label_size = self.video_label.size()
                    pixmap = QPixmap.fromImage(q_img)
                    scaled_pixmap = pixmap.scaled(
                        label_size.width() - 10,
                        label_size.height() - 10,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.video_label.setPixmap(scaled_pixmap)
            except Exception as e:
                print(f"️ Error mostrando frame: {e}")

    def play_crop_range(self):
        """Reproduce solo el tramo recortado (entre las barras amarillas)"""
        if not hasattr(self, 'current_video_path') or not self.current_video_path:
            QMessageBox.warning(self, "Sin video", "Primero selecciona un video.")
            return

        if not self._can_use_media_path(self.current_video_path):
            QMessageBox.warning(self, "Video no encontrado", f"El video no se encuentra en:\n{self.current_video_path}")
            return

        # Obtener rango de recorte del timeline
        start_time = self.video_timeline.start_time
        end_time = self.video_timeline.end_time

        if start_time >= end_time:
            QMessageBox.warning(self, "Rango inválido", "El punto de inicio debe ser menor que el punto final.")
            return

        try:
            # Guardar el rango de reproducción
            self._crop_play_start = start_time
            self._crop_play_end = end_time
            self._playing_crop_range = True

            # Posicionar al inicio del recorte
            self.playback_position = start_time
            self.video_timeline.set_current_position(start_time)

            # Iniciar reproducción
            self._start_moviepy_playback()

            print(f" Reproduciendo recorte: {start_time:.1f}s - {end_time:.1f}s")
        except Exception as e:
            print(f"️ Error reproduciendo recorte: {e}")
            QMessageBox.warning(self, "Error", f"No se pudo reproducir el recorte:\n{str(e)}")

    def toggle_playback(self):
        """Alterna entre reproducir y pausar el video usando moviepy"""
        self._playing_crop_range = False

        if not hasattr(self, 'current_video_path') or not self.current_video_path:
            QMessageBox.warning(self, "Sin video", "El video aún se está descargando.\n\nEspera a que se carguen los frames en el timeline.")
            return

        if not self._can_use_media_path(self.current_video_path):
            QMessageBox.warning(self, "Video no encontrado", f"El video no se encuentra en:\n{self.current_video_path}")
            return

        try:
            if self.is_playing:
                # Pausar
                self._stop_moviepy_playback()
                self.is_playing = False
                if hasattr(self, 'play_btn'):
                    self.play_btn.setText("️ Play")
                print("️ Video pausado")
            else:
                # Reproducir
                self._start_moviepy_playback()
        except Exception as e:
            print(f"️ Error en toggle_playback: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Error", f"No se pudo reproducir el video:\n{str(e)}")

    def _start_moviepy_playback(self):
        """Inicia la reproducción usando moviepy para renderizar frames"""
        try:
            from moviepy.editor import VideoFileClip
            from PyQt6.QtCore import QTimer

            print(f"️ Iniciando reproducción con moviepy: {self.current_video_path}")

            # Cargar el video si no está cargado
            if self.video_clip is None or getattr(self, '_loaded_video_path', None) != self.current_video_path:
                if self.video_clip:
                    self.video_clip.close()
                self.video_clip = VideoFileClip(self.current_video_path)
                self._loaded_video_path = self.current_video_path
                self.video_duration = self.video_clip.duration
                self.playback_position = max(0.0, min(self.playback_position, self.video_duration))
                print(f" Video cargado: duración={self.video_duration:.2f}s, fps={self.video_clip.fps}")

            # Configurar timer para actualizar frames
            fps = min(self.video_clip.fps, 24)  # Limitar a 24fps para rendimiento
            interval = int(1000 / fps)  # Intervalo en ms

            if self.playback_timer is None:
                self.playback_timer = QTimer()
                self.playback_timer.timeout.connect(self._update_video_frame)

            self.playback_timer.start(interval)
            self.is_playing = True

            if hasattr(self, 'play_btn'):
                self.play_btn.setText("️ Pause")
            if hasattr(self, 'stop_btn'):
                self.stop_btn.setEnabled(True)

            print(f" Reproducción iniciada a {fps} fps (intervalo: {interval}ms)")

        except Exception as e:
            print(f" Error iniciando reproducción: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Error", f"No se pudo iniciar la reproducción:\n{str(e)}")

    def _update_video_frame(self):
        """Actualiza el frame mostrado en el video_label"""
        try:
            from PyQt6.QtGui import QImage, QPixmap

            if not self.video_clip or not self.is_playing:
                return

            # Verificar si estamos reproduciendo un recorte
            is_crop_mode = getattr(self, '_playing_crop_range', False)
            crop_end = getattr(self, '_crop_play_end', self.video_duration)
            crop_start = getattr(self, '_crop_play_start', 0.0)

            # Verificar límites
            if is_crop_mode:
                # En modo recorte, loop o detener al final del recorte
                if self.playback_position >= crop_end:
                    # Volver al inicio del recorte (loop)
                    self.playback_position = crop_start
            else:
                # Modo normal
                if self.playback_position >= self.video_duration:
                    # Video terminado, reiniciar
                    self.playback_position = 0.0

            frame = self.video_clip.get_frame(self.playback_position)

            # Convertir numpy array a QPixmap
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QImage(frame.tobytes(), width, height, bytes_per_line, QImage.Format.Format_RGB888)

            # Escalar para ajustar al label
            if hasattr(self, 'video_label') and self.video_label:
                label_size = self.video_label.size()
                pixmap = QPixmap.fromImage(q_img)
                scaled_pixmap = pixmap.scaled(
                    label_size.width() - 10,
                    label_size.height() - 10,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.video_label.setPixmap(scaled_pixmap)

            # Actualizar timeline
            if hasattr(self, 'video_timeline'):
                self.video_timeline.set_current_position(self.playback_position)

            # Avanzar posición
            fps = min(self.video_clip.fps, 24)
            self.playback_position += 1.0 / fps

        except Exception as e:
            print(f"️ Error actualizando frame: {e}")

    def _stop_moviepy_playback(self):
        """Detiene la reproducción con moviepy"""
        if self.playback_timer:
            self.playback_timer.stop()


    def stop_playback(self):
        """Detiene la reproducción del video (mantiene la posición actual)"""
        try:
            # Detener reproducción moviepy
            self._stop_moviepy_playback()
            self.is_playing = False

            # Actualizar UI
            if hasattr(self, 'play_btn'):
                self.play_btn.setText("️ Play")
            if hasattr(self, 'video_label') and self.video_label:
                self.video_label.setText(f"Pausado en {self.playback_position:.1f}s")

            print(f"️ Video pausado en {self.playback_position:.1f}s")
        except Exception as e:
            print(f"️ Error en stop_playback: {e}")

    def select_current_video(self):
        """Selecciona el video actualmente resaltado"""
        selected_item = self.results_list.currentItem()
        if selected_item:
            self.select_video(selected_item)
    
    def select_video(self, item):
        """Descarga el video seleccionado y cierra el diálogo"""
        video_data = item.data(Qt.ItemDataRole.UserRole)
        if not video_data:
            QMessageBox.warning(self, "Error", "No se pudo obtener la información del video.")
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.select_btn.setEnabled(False)
        
        try:
            from internet_archive_client import InternetArchiveClient
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
                        print(f"[InternetArchive] Usando carpeta del proyecto: {project_video_dir}")
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
                            print(f"[InternetArchive] Usando carpeta del proyecto: {project_video_dir}")
                            break
                parent = parent.parent()
            
            # Si no hay proyecto, usar carpeta temporal local (no en Google Drive)
            if not project_video_dir:
                temp_base = Path(tempfile.gettempdir())
                archive_video_dir = temp_base / "video_optimizer" / "internet_archive_downloads"
                archive_video_dir.mkdir(parents=True, exist_ok=True)
                print(f"[InternetArchive] Usando carpeta temporal local: {archive_video_dir}")
            else:
                archive_video_dir = project_video_dir
            
            video_title = video_data.get('title', 'archive_video')
            invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
            for char in invalid_chars:
                video_title = video_title.replace(char, '_')
            video_title = '_'.join(video_title.split())[:50]
            
            identifier = video_data.get('identifier', '')
            filename = f"archive_{hash(identifier) % 100000}_{video_title}.mp4"
            output_path = archive_video_dir / filename
            
            # Descargar video
            client = InternetArchiveClient()
            downloaded_path = client.download_video(video_data, str(output_path))

            if downloaded_path and os.path.exists(downloaded_path):
                # Convertir a ruta absoluta
                downloaded_path = os.path.abspath(downloaded_path)
                print(f" Video descargado exitosamente en: {downloaded_path}")
                
                # Verificar duración del video descargado
                try:
                    from moviepy.editor import VideoFileClip
                    clip = VideoFileClip(downloaded_path)
                    video_duration = clip.duration
                    clip.close()
                    print(f" Duración del video descargado: {video_duration:.2f} segundos")
                except Exception as e:
                    print(f"️ Error verificando duración del video: {e}")
                    video_duration = 0
                
                # Verificar si el recorte está habilitado
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
                                "Rango Inválido",
                                f"El tiempo de inicio ({crop_start:.2f}s) debe ser menor que el tiempo de fin ({crop_end:.2f}s).\n\n"
                                "Se descargará el video completo."
                            )
                            crop_enabled = False
                        else:
                            crop_enabled = True
                            print(f"️ Recorte habilitado: {crop_start:.2f}s - {crop_end:.2f}s")
                
                # Aplicar recorte si está habilitado
                if crop_enabled and crop_start >= 0 and crop_end > crop_start and crop_end <= video_duration:
                    try:
                        from moviepy.editor import VideoFileClip
                        clip = None
                        cropped_clip = None
                        temp_output_path = None
                        try:
                            clip = VideoFileClip(downloaded_path)
                            cropped_clip = clip.subclip(crop_start, crop_end)
                            temp_file = tempfile.NamedTemporaryFile(
                                delete=False,
                                suffix=".mp4",
                                prefix=f"{Path(downloaded_path).stem}_crop_",
                                dir=os.path.dirname(downloaded_path)
                            )
                            temp_output_path = temp_file.name
                            temp_file.close()
                            cropped_clip.write_videofile(temp_output_path, codec='libx264', audio_codec='aac', verbose=False, logger=None)
                        finally:
                            if cropped_clip is not None:
                                try:
                                    cropped_clip.close()
                                except Exception:
                                    pass
                            if clip is not None:
                                try:
                                    clip.close()
                                except Exception:
                                    pass
                        if not temp_output_path or not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) <= 0:
                            raise RuntimeError("El video recortado no se genero correctamente.")
                        os.replace(temp_output_path, downloaded_path)
                        print(f"[IA] Video recortado de {video_duration:.2f}s a {crop_end - crop_start:.2f}s ({crop_start:.2f}s - {crop_end:.2f}s)")
                        video_duration = crop_end - crop_start  # Actualizar duracion
                    except Exception as e:
                        print(f"️ Error recortando video: {e}")
                        QMessageBox.warning(
                            self,
                            "Advertencia",
                            f"No se pudo recortar el video:\n{str(e)}\n\n"
                            "Se mantendrá el video completo."
                        )
                
                # NO ajustar automáticamente la duración - descargar el video completo
                # El usuario puede ajustar la duración después si lo desea
                # Solo ajustar si el segmento tiene una duración específica Y el usuario lo solicita
                segment_duration = self.segment_data.get('end', 0) - self.segment_data.get('start', 0)
                
                # Si el segmento tiene duración y el video es más largo, preguntar al usuario
                # (solo si no se aplicó recorte)
                if not crop_enabled and segment_duration > 0 and video_duration > segment_duration:
                    reply = QMessageBox.question(
                        self,
                        "Ajustar Duración",
                        f"El video descargado tiene {video_duration:.1f}s de duración.\n"
                        f"El segmento requiere {segment_duration:.1f}s.\n\n"
                        f"¿Deseas cortar el video a la duración del segmento?\n\n"
                        f"• Sí: Cortar a {segment_duration:.1f}s\n"
                        f"• No: Mantener el video completo ({video_duration:.1f}s)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        try:
                            from moviepy.editor import VideoFileClip
                            clip = None
                            sub_clip = None
                            temp_output_path = None
                            try:
                                clip = VideoFileClip(downloaded_path)
                                sub_clip = clip.subclip(0, segment_duration)
                                temp_file = tempfile.NamedTemporaryFile(
                                    delete=False,
                                    suffix=".mp4",
                                    prefix=f"{Path(downloaded_path).stem}_trim_",
                                    dir=os.path.dirname(downloaded_path)
                                )
                                temp_output_path = temp_file.name
                                temp_file.close()
                                sub_clip.write_videofile(temp_output_path, codec='libx264', audio_codec='aac', verbose=False, logger=None)
                            finally:
                                if sub_clip is not None:
                                    try:
                                        sub_clip.close()
                                    except Exception:
                                        pass
                                if clip is not None:
                                    try:
                                        clip.close()
                                    except Exception:
                                        pass
                            if not temp_output_path or not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) <= 0:
                                raise RuntimeError("El video recortado no se genero correctamente.")
                            os.replace(temp_output_path, downloaded_path)
                            print(f"[IA] Video cortado a {segment_duration:.1f}s")
                            video_duration = segment_duration
                        except Exception as e:
                            print(f"️ Error cortando video: {e}")
                            QMessageBox.warning(
                                self,
                                "Advertencia",
                                f"No se pudo cortar el video:\n{str(e)}\n\n"
                                "Se mantendrá el video completo."
                            )
                elif not crop_enabled and segment_duration > 0 and video_duration < segment_duration:
                    # Si el video es más corto que el segmento, preguntar si hacer loop
                    reply = QMessageBox.question(
                        self,
                        "Extender Duración",
                        f"El video descargado tiene {video_duration:.1f}s de duración.\n"
                        f"El segmento requiere {segment_duration:.1f}s.\n\n"
                        f"¿Deseas hacer loop del video para alcanzar la duración del segmento?\n\n"
                        f"• Sí: Repetir el video hasta {segment_duration:.1f}s\n"
                        f"• No: Mantener el video original ({video_duration:.1f}s)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )

                    if reply == QMessageBox.StandardButton.Yes:
                        try:
                            from moviepy.editor import VideoFileClip
                            from moviepy.video.fx.all import loop
                            clip = None
                            looped_clip = None
                            temp_output_path = None
                            try:
                                clip = VideoFileClip(downloaded_path)
                                looped_clip = clip.fx(loop, duration=segment_duration)
                                temp_file = tempfile.NamedTemporaryFile(
                                    delete=False,
                                    suffix=".mp4",
                                    prefix=f"{Path(downloaded_path).stem}_loop_",
                                    dir=os.path.dirname(downloaded_path)
                                )
                                temp_output_path = temp_file.name
                                temp_file.close()
                                looped_clip.write_videofile(temp_output_path, codec='libx264', audio_codec='aac', verbose=False, logger=None)
                            finally:
                                if looped_clip is not None:
                                    try:
                                        looped_clip.close()
                                    except Exception:
                                        pass
                                if clip is not None:
                                    try:
                                        clip.close()
                                    except Exception:
                                        pass
                            if not temp_output_path or not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) <= 0:
                                raise RuntimeError("El video extendido no se genero correctamente.")
                            os.replace(temp_output_path, downloaded_path)
                            print(f"[IA] Video extendido a {segment_duration:.1f}s mediante loop")
                            video_duration = segment_duration
                        except Exception as e:
                            print(f"️ Error extendiendo video: {e}")
                            QMessageBox.warning(
                                self,
                                "Advertencia",
                                f"No se pudo extender el video:\n{str(e)}\n\n"
                                "Se mantendrá el video original."
                            )

                self.selected_video_path = downloaded_path
                print(f" Ruta asignada al segmento: {self.selected_video_path}")

                # Save attribution for Internet Archive video
                if ATTRIBUTION_AVAILABLE and get_attribution_manager:
                    try:
                        attr_manager = get_attribution_manager()
                        if attr_manager.add_attribution(video_data, source='internet_archive'):
                            print(f" Attribution saved for: {video_data.get('title', 'Unknown')}")
                    except Exception as attr_error:
                        print(f"️ Could not save attribution: {attr_error}")

                self.progress_bar.setVisible(False)
                self.accept()
            else:
                self.progress_bar.setVisible(False)
                self.select_btn.setEnabled(True)
                error_msg = "No se pudo descargar el video."
                if downloaded_path:
                    error_msg += f"\n\nRuta esperada: {downloaded_path}\n¿Existe? {os.path.exists(downloaded_path) if downloaded_path else 'N/A'}"
                QMessageBox.critical(self, "Error", error_msg)
        
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.select_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", f"Error descargando video:\n{str(e)}")

# Agregar esto al final de timeline_editor_widget.py después de la clase InternetArchiveVideoSearchDialog

# ========== YOUTUBE VIDEO SEARCH CLASSES ==========


