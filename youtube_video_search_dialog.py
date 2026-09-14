# youtube_video_search_dialog.py
"""
Diálogo YouTubeVideoSearchDialog.
Extraído de timeline_editor_widget.py para mejorar la organización del código.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QMessageBox, QScrollArea, QWidget, QCheckBox, QGroupBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QSize, QTimer
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from pathlib import Path
import os
import requests
import warnings
import subprocess
import shutil

# Importar worker
from timeline_workers import YouTubeVideoSearchWorker, VideoFrameExtractorWorker

# Importar VideoTimelineWidget
try:
    from timeline_video_widget import VideoTimelineWidget
except ImportError:
    VideoTimelineWidget = None
    print("️ timeline_video_widget.py no encontrado. VideoTimelineWidget no estará disponible.")

# Importar cliente de YouTube
try:
    from youtube_video_client import YouTubeVideoClient, YT_DLP_AVAILABLE
    YOUTUBE_VIDEO_AVAILABLE = True
except ImportError:
    YOUTUBE_VIDEO_AVAILABLE = False
    YouTubeVideoClient = None
    YT_DLP_AVAILABLE = False

try:
    from attribution_manager import get_attribution_manager
    ATTRIBUTION_AVAILABLE = True
except ImportError:
    ATTRIBUTION_AVAILABLE = False
    get_attribution_manager = None


class YouTubeVideoSearchDialog(QDialog):
    """Diálogo para buscar y seleccionar videos de YouTube"""

    _previous_results = {}

    def __init__(self, parent=None, segment_data=None):
        super().__init__(parent)
        self.segment_data = segment_data or {}
        self.selected_video_path = None
        self.region_edit = None
        self._region_video_url = None
        self.videos = []

        # Variables para reproducción
        self.video_player = None
        self.is_playing = False
        self.playback_timer = None
        self.current_video_path = None

        # Worker para extraer frames del video
        self.frame_extractor_worker = None
        self._current_video_url = None  # URL del video actualmente cargando frames
        self._frame_extraction_timeout_timer = None
        self._frame_extraction_timeout_ms = 180000  # 3 minutos de inactividad

        # Fallback FFplay
        self._ffplay_path = None
        self._using_ffplay_fallback = False
        self._ffplay_process = None
        self._check_ffplay()

        self.setWindowTitle("️ Buscar Videos en YouTube (Solo Creative Commons)")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 900)  # Tamaño inicial más grande

        self.setup_ui()
        self.load_previous_results()

        suggested_query = self.suggest_query_from_segment(self.segment_data)
        if suggested_query:
            self.search_input.setText(suggested_query)
    
    def _check_ffplay(self):
        """Verifica si ffplay está disponible"""
        # Buscar en PATH
        if shutil.which("ffplay"):
            self._ffplay_path = "ffplay"
            return

        # Buscar en rutas comunes y junto a ffmpeg/ffprobe del sistema
        common_paths = [
            r"C:\ffmpeg\bin\ffplay.exe",
            r"C:\Program Files\ffmpeg\bin\ffplay.exe",
        ]

        # Buscar junto a ffprobe si existe
        ffprobe_path = shutil.which("ffprobe")
        if ffprobe_path:
            ffplay_beside = os.path.join(os.path.dirname(ffprobe_path), "ffplay.exe")
            common_paths.insert(0, ffplay_beside)

        # Buscar en carpetas de ffmpeg en Program Files
        try:
            program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
            for entry in os.listdir(program_files):
                if "ffmpeg" in entry.lower():
                    candidate = os.path.join(program_files, entry, "bin", "ffplay.exe")
                    if candidate not in common_paths:
                        common_paths.append(candidate)
        except Exception:
            pass

        for path in common_paths:
            if os.path.exists(path):
                self._ffplay_path = path
                return
    
    def preview_selected_video(self):
        """Abre un diálogo para previsualizar el video seleccionado - DESHABILITADO para URLs remotas"""
        selected_item = self.results_list.currentItem()
        if not selected_item:
            return
        
        video_data = selected_item.data(Qt.ItemDataRole.UserRole)
        if not video_data:
            QMessageBox.warning(self, "Error", "No se pudo obtener la información del video.")
            return
        
        # YouTube siempre devuelve URLs remotas - NO crear diálogo de preview (causa crashes)
        # Mostrar mensaje informativo directamente sin intentar crear VideoPreviewDialog
        video_url = video_data.get('url', '')
        QMessageBox.information(
            self,
            "Preview de Video Remoto",
            "ℹ️ Preview de video remoto no disponible por seguridad.\n\n"
            "Los videos de YouTube no se pueden reproducir directamente\n"
            "en el preview para evitar problemas de estabilidad.\n\n"
            f"URL del video: {video_url}\n\n"
            "Opciones:\n"
            "• Usa ' Abrir en Navegador' para ver el video en tu navegador\n"
        )

    def setup_ui(self):
        """Configura la interfaz del di?logo"""
        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        search_label = QLabel("Buscar:")
        search_layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Ej: tutorial python, documental historia o pega una URL de YouTube")
        self.search_input.returnPressed.connect(self.perform_search)
        search_layout.addWidget(self.search_input)
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
        self.results_list.setIconSize(QSize(320, 180))  # Tamaño estándar de thumbnail de YouTube (16:9)
        self.results_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.results_list.setSpacing(15)  # Espaciado entre items (aumentado)
        self.results_list.setGridSize(QSize(360, 280))  # Tamaño de la celda (thumbnail + texto) - aumentado
        self.results_list.itemDoubleClicked.connect(self.select_video)
        # Hacer que el área de resultados use todo el espacio disponible
        scroll_layout.addWidget(self.results_list, 1)
        
        # Grupo de controles de recorte (similar a CapCut con timeline visual)
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

        # Widget de video para reproducción (QLabel + ffmpeg frame rendering)
        self.video_label = QLabel()
        self.video_label.setMinimumHeight(200)
        self.video_label.setMaximumHeight(350)
        self.video_label.setStyleSheet("background-color: #0a0a0a; border-radius: 4px;")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setText("Selecciona un video y presiona Play")
        self.video_label.setVisible(True)
        crop_layout.addWidget(self.video_label)

        # Reproductor ffmpeg inline (frame-by-frame con QTimer)
        self._ffmpeg_playback_timer = None
        self._ffmpeg_playback_fps = 10  # frames por segundo para preview
        self._ffmpeg_playback_process = None

        # Barra de progreso para carga de video
        self.video_loading_progress = QProgressBar()
        self.video_loading_progress.setVisible(False)
        self.video_loading_progress.setTextVisible(True)
        self.video_loading_progress.setFormat("Cargando video... %p%")
        crop_layout.addWidget(self.video_loading_progress)

        # Variables para reproducción
        self.playback_timer = None
        self.playback_position = 0.0
        self.video_duration = 0.0

        # Widget de timeline de video (similar a CapCut)
        if VideoTimelineWidget:
            self.video_timeline = VideoTimelineWidget()
            self.video_timeline.setEnabled(False)
            self.video_timeline.crop_range_changed.connect(self.on_timeline_crop_changed)
            self.video_timeline.position_clicked.connect(self.on_timeline_position_clicked)
            self.video_timeline.position_dragged.connect(self.on_timeline_position_dragged)
            crop_layout.addWidget(self.video_timeline)
        else:
            self.video_timeline = None
            print("️ VideoTimelineWidget no disponible")

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
        self.video_crop_start.setEnabled(False)  # Habilitar solo cuando hay video seleccionado
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
        region_row = QHBoxLayout()
        self.region_edit_btn = QPushButton("Cubrir / quitar marca de agua…")
        self.region_edit_btn.clicked.connect(self.edit_video_region)
        region_row.addWidget(self.region_edit_btn)
        self.region_status = QLabel("Sin efecto sobre el video")
        region_row.addWidget(self.region_status, 1)
        self.region_clear_btn = QPushButton("Quitar efecto")
        self.region_clear_btn.clicked.connect(self.clear_video_region)
        self.region_clear_btn.setEnabled(False)
        region_row.addWidget(self.region_clear_btn)
        crop_layout.addLayout(region_row)
        
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
                        title = video.get('title', 'Video de YouTube') or 'Video de YouTube'
                        channel = video.get('channel', '') or ''
                        duration = video.get('duration', 0) or 0
                        thumbnail_url = video.get('thumbnail', '')
                        
                        # Formatear duraci?n
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

                        item_text = f"{title[:80]}\n"
                        if channel:
                            item_text += f"[Canal] {channel[:40]}\n"
                        item_text += f"[Duracion] {duration_str}"
                        license_type = video.get('license', '')
                        if video.get('direct_url'):
                            item_text += "\n[URL directa]"
                        elif 'Creative Commons' in license_type:
                            item_text += f"\n[CC] {license_type}"

                        item.setText(item_text)
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
                                                320, 180,
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
        if not YOUTUBE_VIDEO_AVAILABLE:
            QMessageBox.warning(
                self,
                "YouTube no disponible",
                "El cliente de YouTube no esta disponible.\n"
                "Asegurate de que youtube_video_client.py este en el directorio del proyecto.\n\n"
                "Tambien necesitas:\n"
                "- yt-dlp instalado para URLs directas y descargas\n"
                "- GOOGLE_API_KEY solo si quieres buscar por texto"
            )
            return
        
        self.results_list.clear()
        self.videos = []
        self.select_btn.setEnabled(False)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.search_btn.setEnabled(False)
        
        narration_text = self.segment_data.get('text', '') if self.segment_data else ''
        
        self.worker = YouTubeVideoSearchWorker(query, narration_text)
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
                    title = video.get('title', 'Video de YouTube') or 'Video de YouTube'
                    channel = video.get('channel', '') or ''
                    duration = video.get('duration', 0) or 0
                    view_count = video.get('view_count', 0) or 0
                    thumbnail_url = video.get('thumbnail', '')
                    
                    # Limpiar strings para evitar problemas
                    if isinstance(title, str):
                        title = title[:80]  # Limitar longitud para que quepa en el item
                    if isinstance(channel, str):
                        channel = channel[:40]
                    
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
                    item_text = f"{title}\n"
                    if channel:
                        item_text += f"[Canal] {channel}\n"
                    item_text += f"[Duracion] {duration_str}"
                    if view_count > 0:
                        view_str = f"{view_count:,}" if view_count < 1000000 else f"{view_count/1000000:.1f}M"
                        item_text += f" | [Vistas] {view_str}"
                    license_type = video.get('license', '')
                    if video.get('direct_url'):
                        item_text += "\n[URL directa]"
                    elif 'Creative Commons' in license_type:
                        item_text += f"\n[CC] {license_type}"
                        item_text += f"\n {license_type}"

                    item.setText(item_text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setData(Qt.ItemDataRole.UserRole, video)
                    
                    # Agregar item primero
                    self.results_list.addItem(item)
                    
                    # Cargar miniatura del video de forma asíncrona
                    if thumbnail_url and thumbnail_url.startswith(('http://', 'https://')):
                        self.load_thumbnail_async(item, thumbnail_url, title)
                except Exception as e:
                    print(f"️ Error procesando video: {e}")
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
                                320, 180,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            )
                            icon = QIcon(scaled_pixmap)
                            item.setIcon(icon)
            except Exception as e:
                print(f"️ Error cargando thumbnail de YouTube: {e}")
        
        QTimer.singleShot(0, load_thumbnail)

    def clear_video_region(self):
        self.region_edit = None
        self.region_status.setText("Sin efecto sobre el video")
        self.region_clear_btn.setEnabled(False)

    def edit_video_region(self):
        if not self.current_video_path or not os.path.isfile(self.current_video_path):
            QMessageBox.information(self, "Video aún no disponible",
                                    "Selecciona un video y espera a que cargue la vista previa.")
            return
        position = getattr(self, 'playback_position', 0.0)
        self.stop_playback()
        try:
            from video_region_editor import VideoRegionEditor
            dialog = VideoRegionEditor(self.current_video_path, position, self.region_edit, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.region_edit = dialog.edit
                label = {'cover': 'Cubrir', 'blur': 'Difuminar', 'remove': 'Quitar (aproximado)'}[dialog.edit['mode']]
                self.region_status.setText(f"{label}: se aplicará al seleccionar el video")
                self.region_clear_btn.setEnabled(True)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo editar la zona", str(exc))

    def on_selection_changed(self):
        """Habilita/deshabilita el botón de seleccionar y preview, y actualiza controles de recorte"""
        has_selection = self.results_list.currentItem() is not None
        selected = self.results_list.currentItem()
        selected_url = (selected.data(Qt.ItemDataRole.UserRole) or {}).get('url') if selected else None
        if selected_url != self._region_video_url:
            self.clear_video_region()
            self.current_video_path = None
            self._region_video_url = selected_url
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
                    video_duration = video_data.get('duration', 0) or 0
                    video_url = video_data.get('url', '')

                    if video_duration > 0:
                        # Actualizar valores máximos y establecer fin al final del video
                        if hasattr(self, 'video_crop_start'):
                            self.video_crop_start.setMaximum(video_duration)
                            self.video_crop_start.setValue(0.0)
                        if hasattr(self, 'video_crop_end'):
                            self.video_crop_end.setMaximum(video_duration)
                            self.video_crop_end.setValue(video_duration)
                        # Actualizar el timeline widget con la duración del video
                        if self.video_timeline:
                            self.video_timeline.set_video_duration(video_duration)
                            self.video_timeline.set_crop_range(0.0, video_duration)
                            self.video_timeline.setEnabled(True)

                            # Iniciar descarga y extracción de frames si es un video diferente
                            if video_url and video_url != self._current_video_url:
                                self._start_frame_extraction(video_url, 'youtube')
                    else:
                        # Sin duración conocida, deshabilitar timeline
                        if self.video_timeline:
                            self.video_timeline.set_video_duration(0)
                            self.video_timeline.setEnabled(False)
        else:
            if hasattr(self, 'enable_crop_checkbox'):
                self.enable_crop_checkbox.setEnabled(False)
                self.enable_crop_checkbox.setChecked(False)
            if hasattr(self, 'video_crop_start'):
                self.video_crop_start.setEnabled(False)
            if hasattr(self, 'video_crop_end'):
                self.video_crop_end.setEnabled(False)
            if hasattr(self, 'reset_crop_btn'):
                self.reset_crop_btn.setEnabled(False)
            # Resetear timeline cuando no hay selección
            if hasattr(self, 'video_timeline'):
                self.video_timeline.set_video_duration(0)
                self.video_timeline.set_video_frames([])
                self.video_timeline.setEnabled(False)
            # Cancelar extracción en progreso
            self._cancel_frame_extraction()

    def _start_frame_extraction(self, video_url, video_source):
        """Inicia la extracción de frames del video en segundo plano"""
        # Cancelar worker anterior si existe
        self._cancel_frame_extraction()

        self._current_video_url = video_url

        # Mostrar barra de progreso
        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setVisible(True)
            self.video_loading_progress.setRange(0, 0)  # Modo indeterminado
            self.video_loading_progress.setFormat("Descargando video...")

        # Mostrar mensaje de carga en el timeline
        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_video_frames([])
            self.video_timeline.set_loading_message("Descargando video para preview...")

        # Crear y ejecutar worker
        self.frame_extractor_worker = VideoFrameExtractorWorker(video_url, video_source, num_frames=15)
        self.frame_extractor_worker.finished.connect(self._on_frames_extracted)
        self.frame_extractor_worker.error.connect(self._on_frame_extraction_error)
        self.frame_extractor_worker.progress.connect(self._on_frame_extraction_progress)
        self.frame_extractor_worker.start()

        # Watchdog: evita quedarse indefinidamente en "Descargando video para preview..."
        if self._frame_extraction_timeout_timer is None:
            self._frame_extraction_timeout_timer = QTimer(self)
            self._frame_extraction_timeout_timer.setSingleShot(True)
            self._frame_extraction_timeout_timer.timeout.connect(self._on_frame_extraction_timeout)
        self._frame_extraction_timeout_timer.start(self._frame_extraction_timeout_ms)

    def _on_frame_extraction_timeout(self):
        """Timeout de extracción de frames: limpiar UI sin bloquear flujo."""
        if self.frame_extractor_worker and self.frame_extractor_worker.isRunning():
            print("️ Timeout en preview de video, cancelando extracción de frames")
            self._cancel_frame_extraction()

            if hasattr(self, 'video_loading_progress'):
                self.video_loading_progress.setVisible(False)
            if hasattr(self, 'video_timeline'):
                self.video_timeline.clear_loading_message()
            if hasattr(self, 'video_label') and self.video_label:
                self.video_label.setText("Preview tardó demasiado. Puedes seleccionar el video igualmente.")

    def _cancel_frame_extraction(self):
        """Cancela la extracción de frames en progreso"""
        if self._frame_extraction_timeout_timer:
            self._frame_extraction_timeout_timer.stop()
        if self.frame_extractor_worker and self.frame_extractor_worker.isRunning():
            self.frame_extractor_worker.terminate()
            self.frame_extractor_worker.wait(1000)
        self.frame_extractor_worker = None
        self._current_video_url = None

    def _on_frames_extracted(self, video_path, frames):
        """Callback cuando se extraen los frames exitosamente"""
        if self._frame_extraction_timeout_timer:
            self._frame_extraction_timeout_timer.stop()
        # Ocultar barra de progreso
        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setVisible(False)

        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()
            self.video_timeline.set_video_frames(frames)
            self.current_video_path = video_path

            # Habilitar botones de reproducción
            if hasattr(self, 'play_btn'):
                self.play_btn.setEnabled(True)
            if hasattr(self, 'stop_btn'):
                self.stop_btn.setEnabled(True)
            if hasattr(self, 'play_crop_btn'):
                self.play_crop_btn.setEnabled(True)
            if hasattr(self, 'fit_segment_btn'):
                self.fit_segment_btn.setEnabled(True)

            # NO pre-inicializar el reproductor aquí - dejarlo para toggle_playback
            # Esto evita problemas de sincronización con el video widget
            print(f" Video listo para reproducir: {video_path}")

    def _on_frame_extraction_error(self, error_msg):
        """Callback cuando falla la extracción de frames"""
        print(f"️ Error extrayendo frames: {error_msg}")
        if self._frame_extraction_timeout_timer:
            self._frame_extraction_timeout_timer.stop()

        # Ocultar barra de progreso
        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setVisible(False)

        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()
            # No mostrar error al usuario, solo limpiar el mensaje de carga
        if hasattr(self, 'video_label') and self.video_label:
            self.video_label.setText("Preview no disponible para este video. Puedes seleccionarlo igualmente.")

    def _on_frame_extraction_progress(self, message):
        """Callback para actualizar el progreso de extracción"""
        # Watchdog por inactividad: renovar timeout cada vez que llega progreso.
        if self._frame_extraction_timeout_timer:
            self._frame_extraction_timeout_timer.start(self._frame_extraction_timeout_ms)

        # Actualizar barra de progreso con mensaje
        if hasattr(self, 'video_loading_progress'):
            self.video_loading_progress.setFormat(message)

        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_loading_message(message)

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
    
    def on_timeline_position_clicked(self, position):
        """Callback cuando se hace click en el timeline para cambiar posición"""
        self.playback_position = position
        self.video_timeline.set_current_position(position)
        # Mostrar frame en esa posición
        self._show_frame_at(position)

    def on_timeline_position_dragged(self, position):
        """Callback cuando se arrastra la barra azul de posición"""
        self.playback_position = position
        if self.is_playing:
            # Si está reproduciendo, el timer seguirá desde la nueva posición
            pass
        else:
            self._show_frame_at(position)

    def play_crop_range(self):
        """Reproduce solo el tramo recortado (entre las barras amarillas)"""
        if not hasattr(self, 'current_video_path') or not self.current_video_path:
            QMessageBox.warning(self, "Sin video", "Primero selecciona un video.")
            return

        if not os.path.exists(self.current_video_path):
            QMessageBox.warning(self, "Video no encontrado", f"El video no se encuentra en:\n{self.current_video_path}")
            return

        start_time = self.video_timeline.start_time
        end_time = self.video_timeline.end_time

        if start_time >= end_time:
            QMessageBox.warning(self, "Rango inválido", "El punto de inicio debe ser menor que el punto final.")
            return

        self._crop_play_start = start_time
        self._crop_play_end = end_time
        self._playing_crop_range = True

        self._start_ffmpeg_playback(position_sec=start_time)
        print(f" Reproduciendo recorte: {start_time:.1f}s - {end_time:.1f}s")

    def toggle_playback(self):
        """Alterna entre reproducir y pausar el video (ffmpeg frame rendering)"""
        if not self.is_playing:
            self._playing_crop_range = False

        if not hasattr(self, 'current_video_path') or not self.current_video_path:
            QMessageBox.warning(self, "Sin video", "El video aún se está descargando.\n\nEspera a que se carguen los frames en el timeline.")
            return

        if not os.path.exists(self.current_video_path):
            QMessageBox.warning(self, "Video no encontrado", f"El video no se encuentra en:\n{self.current_video_path}")
            return

        if self.is_playing:
            self._stop_ffmpeg_playback()
        else:
            self._start_ffmpeg_playback()

    def _get_video_duration_ffprobe(self):
        """Obtiene la duración del video con ffprobe"""
        if getattr(self, '_cached_duration', None) and getattr(self, '_cached_duration_path', None) == self.current_video_path:
            return self._cached_duration
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", self.current_video_path],
                capture_output=True, text=True, timeout=10
            )
            duration = float(result.stdout.strip())
            self._cached_duration = duration
            self._cached_duration_path = self.current_video_path
            return duration
        except Exception:
            return self.video_duration if self.video_duration > 0 else 30.0

    def _start_ffmpeg_playback(self, position_sec=None):
        """Inicia reproducción inline renderizando frames con ffmpeg en un hilo separado"""
        import time as _time
        import threading
        import queue

        if position_sec is not None:
            self.playback_position = position_sec

        self.video_duration = self._get_video_duration_ffprobe()

        # Si la posición excede la duración real del archivo, reiniciar a 0
        if self.playback_position >= self.video_duration:
            print(f"  [play] Posición {self.playback_position:.1f}s excede duración del archivo ({self.video_duration:.1f}s), reiniciando a 0")
            self.playback_position = 0.0

        # Limpiar proceso anterior
        self._stop_ffmpeg_pipe()

        fps = self._ffmpeg_playback_fps
        # Usar tamaño fijo para evitar problemas de layout
        out_w = 480
        # Obtener dimensiones originales para calcular altura
        try:
            probe_cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x", self.current_video_path
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=5)
            orig_w, orig_h = [int(x) for x in probe_result.stdout.strip().split('x')]
            out_h = int(orig_h * out_w / orig_w)
            # ffmpeg scale requiere dimensiones pares
            if out_w % 2 != 0:
                out_w += 1
            if out_h % 2 != 0:
                out_h += 1
        except Exception:
            out_h = int(out_w * 9 / 16)

        self._frame_w = out_w
        self._frame_h = out_h
        self._frame_size = out_w * out_h * 3

        # Usar scale con tamaño exacto para evitar mismatch
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", f"{self.playback_position:.3f}",
            "-i", self.current_video_path,
            "-vf", f"scale={out_w}:{out_h},fps={fps}",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-an",
            "pipe:1"
        ]

        try:
            self._ffmpeg_playback_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=10 * 1024 * 1024
            )
        except Exception as e:
            print(f" Error iniciando ffmpeg playback: {e}")
            QMessageBox.warning(self, "Error", f"No se pudo iniciar la reproducción:\n{e}")
            return

        # Cola para pasar frames del hilo lector al hilo de UI
        self._frame_queue = queue.Queue(maxsize=5)
        self._reader_stop = threading.Event()
        self._playback_start_wall = _time.time()
        self._playback_start_pos = self.playback_position

        # Hilo lector: lee frames de ffmpeg stdout sin bloquear la UI
        def reader_thread(proc, frame_size, q, stop_event):
            try:
                while not stop_event.is_set():
                    raw = proc.stdout.read(frame_size)
                    if not raw or len(raw) < frame_size:
                        break
                    try:
                        q.put(raw, timeout=0.5)
                    except queue.Full:
                        pass  # skip frame si la UI va lenta
            except Exception:
                pass

        self._reader_thread = threading.Thread(
            target=reader_thread,
            args=(self._ffmpeg_playback_process, self._frame_size, self._frame_queue, self._reader_stop),
            daemon=True
        )
        self._reader_thread.start()
        self._render_count = 0

        # Timer para consumir frames de la cola y mostrarlos
        interval = int(1000 / fps)
        if self._ffmpeg_playback_timer is None:
            self._ffmpeg_playback_timer = QTimer(self)
            self._ffmpeg_playback_timer.timeout.connect(self._render_next_frame)
        self._ffmpeg_playback_timer.start(interval)
        print(f"  [play] Timer iniciado (intervalo={interval}ms), reader thread alive={self._reader_thread.is_alive()}")
        print(f"  [play] ffmpeg pid={self._ffmpeg_playback_process.pid}, poll={self._ffmpeg_playback_process.poll()}")

        self.is_playing = True
        if hasattr(self, 'play_btn'):
            self.play_btn.setText("️ Pause")
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(True)
        print(f"️ Reproducción iniciada ({out_w}x{out_h} @ {fps}fps, desde {self.playback_position:.1f}s)")

    def _render_next_frame(self):
        """Consume un frame de la cola y lo muestra en video_label"""
        import time as _time
        import queue as _queue
        from PyQt6.QtGui import QImage, QPixmap

        # Verificar si hay frame disponible (no bloquea)
        try:
            raw = self._frame_queue.get_nowait()
        except _queue.Empty:
            # Verificar si el proceso terminó y la cola está vacía
            proc = self._ffmpeg_playback_process
            if proc and proc.poll() is not None and self._frame_queue.empty():
                self._stop_ffmpeg_playback()
            return

        try:
            q_img = QImage(raw, self._frame_w, self._frame_h, self._frame_w * 3, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)
            self.video_label.setPixmap(pixmap)

            # Actualizar posición basada en el reloj de pared
            elapsed = _time.time() - self._playback_start_wall
            self.playback_position = self._playback_start_pos + elapsed

            if hasattr(self, 'video_timeline') and self.video_timeline:
                self.video_timeline.set_current_position(self.playback_position)

            # Verificar crop range
            if getattr(self, '_playing_crop_range', False):
                end_time = getattr(self, '_crop_play_end', 0)
                if end_time > 0 and self.playback_position >= end_time:
                    self._stop_ffmpeg_playback()
                    return

            # Verificar fin del video
            if self.video_duration > 0 and self.playback_position >= self.video_duration:
                self._stop_ffmpeg_playback()

        except Exception as e:
            print(f"️ Error renderizando frame: {e}")
            import traceback
            traceback.print_exc()

    def _stop_ffmpeg_playback(self):
        """Detiene la reproducción ffmpeg inline"""
        if self._ffmpeg_playback_timer:
            self._ffmpeg_playback_timer.stop()
        # Señalar al hilo lector que pare
        if hasattr(self, '_reader_stop') and self._reader_stop:
            self._reader_stop.set()
        self._stop_ffmpeg_pipe()
        self.is_playing = False
        self._playing_crop_range = False
        if hasattr(self, 'play_btn'):
            self.play_btn.setText("️ Play")

    def _stop_ffmpeg_pipe(self):
        """Mata el proceso ffmpeg de reproducción"""
        if hasattr(self, '_reader_stop') and self._reader_stop:
            self._reader_stop.set()
        if self._ffmpeg_playback_process:
            try:
                self._ffmpeg_playback_process.kill()
                self._ffmpeg_playback_process.wait(timeout=2)
            except Exception:
                pass
            self._ffmpeg_playback_process = None

    def _show_frame_at(self, position_sec):
        """Muestra un solo frame en la posición dada usando ffmpeg"""
        from PyQt6.QtGui import QImage, QPixmap
        if not hasattr(self, 'current_video_path') or not self.current_video_path:
            return
        if not os.path.exists(self.current_video_path):
            return
        try:
            out_w = 480
            probe_cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x", self.current_video_path
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=5)
            orig_w, orig_h = [int(x) for x in probe_result.stdout.strip().split('x')]
            out_h = int(orig_h * out_w / orig_w)
            if out_w % 2 != 0:
                out_w += 1
            if out_h % 2 != 0:
                out_h += 1

            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", f"{position_sec:.3f}",
                "-i", self.current_video_path,
                "-vframes", "1",
                "-vf", f"scale={out_w}:{out_h}",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "pipe:1"
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            frame_size = out_w * out_h * 3
            if result.stdout and len(result.stdout) >= frame_size:
                raw = result.stdout[:frame_size]
                q_img = QImage(raw, out_w, out_h, out_w * 3, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(q_img)
                self.video_label.setPixmap(pixmap)
        except Exception as e:
            print(f"️ Error mostrando frame: {e}")


    def stop_playback(self):
        """Detiene la reproducción del video"""
        # Detener ffmpeg playback inline
        self._stop_ffmpeg_playback()

        # Detener FFplay externo si estaba activo
        if self._ffplay_process:
            try:
                self._ffplay_process.terminate()
                self._ffplay_process = None
            except Exception:
                pass

        self.is_playing = False
        self._playing_crop_range = False

        if hasattr(self, 'play_btn'):
            self.play_btn.setText("️ Play")
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(False)
    
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
            from youtube_video_client import YouTubeVideoClient
            from pathlib import Path
            import tempfile
            
            # Intentar obtener la carpeta del proyecto actual desde el parent
            project_video_dir = None
            parent = self.parent()
            while parent:
                # Buscar timeline_editor que tiene referencia al proyecto
                if hasattr(parent, 'studio_tab') and hasattr(parent.studio_tab, 'current_project_path'):
                    if parent.studio_tab.current_project_path:
                        project_path_obj = Path(parent.studio_tab.current_project_path)
                        project_folder = project_path_obj.parent
                        # Usar carpeta videos/ o temp/ del proyecto
                        project_video_dir = project_folder / "videos"
                        if not project_video_dir.exists():
                            project_video_dir = project_folder / "temp"
                        project_video_dir.mkdir(parents=True, exist_ok=True)
                        print(f"[YouTube] Usando carpeta del proyecto: {project_video_dir}")
                        break
                # Buscar directamente timeline_editor_window
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
                            print(f"[YouTube] Usando carpeta del proyecto: {project_video_dir}")
                            break
                parent = parent.parent()
            
            # Si no hay proyecto, usar carpeta temporal local (no en Google Drive)
            if not project_video_dir:
                # Usar directorio temporal del sistema (generalmente fuera de Google Drive)
                temp_base = Path(tempfile.gettempdir())
                youtube_video_dir = temp_base / "video_optimizer" / "youtube_downloads"
                youtube_video_dir.mkdir(parents=True, exist_ok=True)
                print(f"[YouTube] Usando carpeta temporal local: {youtube_video_dir}")
            else:
                youtube_video_dir = project_video_dir
            
            video_title = video_data.get('title', 'youtube_video')
            invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
            for char in invalid_chars:
                video_title = video_title.replace(char, '_')
            video_title = '_'.join(video_title.split())[:50]
            
            video_id = video_data.get('video_id', '')
            filename = f"youtube_{hash(video_id) % 100000}_{video_title}.mp4"
            output_path = youtube_video_dir / filename
            
            # Descargar video
            client = YouTubeVideoClient()
            downloaded_path = client.download_video(video_data, str(output_path))
            
            if downloaded_path and os.path.exists(downloaded_path):
                # Convertir a ruta absoluta
                downloaded_path = os.path.abspath(downloaded_path)
                # La descarga queda como CACHE de solo lectura: cada recorte se
                # escribe en su propio archivo. Antes se hacia os.replace()
                # sobre ella, asi que sacar un segundo fragmento del mismo
                # video reutilizaba el clip anterior o pisaba el segmento que
                # ya lo estaba usando.
                source_path = downloaded_path
                self.current_video_path = downloaded_path  # Guardar ruta para reproducción
                print(f" Video descargado exitosamente en: {downloaded_path}")
                
                # Verificar duración del video descargado con ffprobe
                try:
                    probe_cmd = [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        downloaded_path
                    ]
                    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
                    video_duration = float(probe_result.stdout.strip())
                    print(f" Duración del video descargado: {video_duration:.2f} segundos")

                    # Cargar frames en el timeline si está disponible
                    if hasattr(self, 'video_timeline'):
                        try:
                            self.video_timeline.load_video_frames(downloaded_path)
                            self.video_timeline.set_video_duration(video_duration)
                            self.video_timeline.set_crop_range(0.0, video_duration)
                            self.video_timeline.setEnabled(True)
                            if hasattr(self, 'play_btn'):
                                self.play_btn.setEnabled(True)
                        except Exception as e:
                            print(f"️ Error cargando frames en timeline: {e}")
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
                # Aplicar recorte si esta habilitado (usando ffmpeg)
                if crop_enabled and crop_start >= 0 and crop_end > crop_start and crop_end <= video_duration:
                    try:
                        from output_naming import build_clip_filename

                        clip_name = build_clip_filename(
                            video_data.get('video_id', ''), video_data.get('title', ''),
                            crop_start, crop_end)
                        clip_path = os.path.join(os.path.dirname(source_path), clip_name)
                        temp_output_path = clip_path + ".part.mp4"
                        duration = crop_end - crop_start
                        crop_cmd = [
                            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                            "-ss", f"{crop_start:.3f}",
                            "-i", source_path,
                            "-t", f"{duration:.3f}",
                            "-c:v", "libx264", "-preset", "fast",
                            "-c:a", "aac",
                            "-avoid_negative_ts", "make_zero",
                            temp_output_path
                        ]
                        result = subprocess.run(crop_cmd, capture_output=True, text=True, timeout=300)
                        if result.returncode != 0:
                            raise RuntimeError(f"ffmpeg error: {result.stderr[:300]}")
                        if not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) <= 0:
                            raise RuntimeError("El video recortado no se genero correctamente.")
                        # Al archivo del recorte, NO sobre la descarga.
                        os.replace(temp_output_path, clip_path)
                        downloaded_path = clip_path
                        print(f"[YouTube] Recorte {crop_start:.2f}s-{crop_end:.2f}s -> {clip_name}")
                        print(f"[YouTube] La descarga completa queda intacta para otros recortes")
                        video_duration = duration
                    except Exception as e:
                        print(f"[WARN] Error recortando video: {e}")
                        # Limpiar temp si existe
                        try:
                            if os.path.exists(temp_output_path):
                                os.remove(temp_output_path)
                        except Exception:
                            pass
                        QMessageBox.warning(
                            self,
                            "Advertencia",
                            f"No se pudo recortar el video:\n{str(e)}\n\n"
                            "Se mantendra el video completo."
                        )

                # NO ajustar autom?ticamente la duraci?n - descargar el video completo
                # El usuario puede ajustar la duraci?n despu?s si lo desea
                # Solo ajustar si el segmento tiene una duraci?n espec?fica Y el usuario lo solicita
                segment_duration = self.segment_data.get('end', 0) - self.segment_data.get('start', 0)

                # Si el segmento tiene duraci?n y el video es m?s largo, preguntar al usuario
                # (solo si no se aplic? recorte)
                if not crop_enabled and segment_duration > 0 and video_duration > segment_duration:
                    reply = QMessageBox.question(
                        self,
                        "Ajustar Duraci?n",
                        f"El video descargado tiene {video_duration:.1f}s de duraci?n.\n"
                        f"El segmento requiere {segment_duration:.1f}s.\n\n"
                        f"?Deseas cortar el video a la duraci?n del segmento?\n\n"
                        f"? S?: Cortar a {segment_duration:.1f}s\n"
                        f"? No: Mantener el video completo ({video_duration:.1f}s)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )

                    if reply == QMessageBox.StandardButton.Yes:
                        try:
                            from output_naming import build_clip_filename

                            trim_name = build_clip_filename(
                                video_data.get('video_id', ''), video_data.get('title', ''),
                                0.0, segment_duration, suffix="trim")
                            trim_path = os.path.join(os.path.dirname(source_path), trim_name)
                            temp_output_path = trim_path + ".part.mp4"
                            trim_cmd = [
                                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                                "-i", downloaded_path,
                                "-t", f"{segment_duration:.3f}",
                                "-c:v", "libx264", "-preset", "fast",
                                "-c:a", "aac",
                                temp_output_path
                            ]
                            result = subprocess.run(trim_cmd, capture_output=True, text=True, timeout=300)
                            if result.returncode != 0:
                                raise RuntimeError(f"ffmpeg error: {result.stderr[:300]}")
                            if not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) <= 0:
                                raise RuntimeError("El video recortado no se genero correctamente.")
                            os.replace(temp_output_path, trim_path)
                            downloaded_path = trim_path
                            print(f"[YouTube] Video cortado a {segment_duration:.1f}s")
                            video_duration = segment_duration
                        except Exception as e:
                            print(f"[WARN] Error cortando video: {e}")
                            try:
                                if os.path.exists(temp_output_path):
                                    os.remove(temp_output_path)
                            except Exception:
                                pass
                            QMessageBox.warning(
                                self,
                                "Advertencia",
                                f"No se pudo cortar el video:\n{str(e)}\n\n"
                                "Se mantendra el video completo."
                            )
                elif segment_duration > 0 and video_duration < segment_duration:
                    # Si el video es m?s corto que el segmento, preguntar si hacer loop
                    reply = QMessageBox.question(
                        self,
                        "Extender Duraci?n",
                        f"El video descargado tiene {video_duration:.1f}s de duraci?n.\n"
                        f"El segmento requiere {segment_duration:.1f}s.\n\n"
                        f"?Deseas hacer loop del video para alcanzar la duraci?n del segmento?\n\n"
                        f"? S?: Repetir el video hasta {segment_duration:.1f}s\n"
                        f"? No: Mantener el video original ({video_duration:.1f}s)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )

                    if reply == QMessageBox.StandardButton.Yes:
                        try:
                            import subprocess as _sp
                            import math
                            # Calcular cuántas repeticiones necesitamos
                            loop_count = math.ceil(segment_duration / video_duration)
                            temp_file = tempfile.NamedTemporaryFile(
                                delete=False,
                                suffix=".mp4",
                                prefix=f"{Path(downloaded_path).stem}_loop_",
                                dir=os.path.dirname(downloaded_path)
                            )
                            temp_output_path = temp_file.name
                            temp_file.close()
                            loop_cmd = [
                                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                                "-stream_loop", str(loop_count - 1),
                                "-i", downloaded_path,
                                "-t", f"{segment_duration:.3f}",
                                "-c:v", "libx264", "-preset", "fast",
                                "-c:a", "aac",
                                "-avoid_negative_ts", "make_zero",
                                temp_output_path
                            ]
                            result = _sp.run(loop_cmd, capture_output=True, text=True, timeout=120)
                            if result.returncode != 0:
                                raise RuntimeError(result.stderr or "ffmpeg loop failed")
                            if not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) <= 0:
                                raise RuntimeError("El video extendido no se genero correctamente.")
                            # A su propio archivo: si el loop pisara la fuente,
                            # el siguiente recorte del mismo video partiria de
                            # un video ya repetido.
                            from output_naming import build_clip_filename

                            loop_name = build_clip_filename(
                                video_data.get('video_id', ''), video_data.get('title', ''),
                                0.0, segment_duration, suffix="loop")
                            loop_path = os.path.join(os.path.dirname(source_path), loop_name)
                            os.replace(temp_output_path, loop_path)
                            downloaded_path = loop_path
                            print(f"[YouTube] Video extendido a {segment_duration:.1f}s mediante loop")
                            video_duration = segment_duration
                        except Exception as e:
                            print(f"[WARN] Error extendiendo video: {e}")
                            QMessageBox.warning(
                                self,
                                "Advertencia",
                                f"No se pudo extender el video:\n{str(e)}\n\n"
                                "Se mantendr? el video original."
                            )

                if self.region_edit:
                    from video_region_editor import export_region_copy
                    downloaded_path = export_region_copy(downloaded_path, self.region_edit, self)
                self.selected_video_path = downloaded_path
                print(f" Ruta asignada al segmento: {self.selected_video_path}")

                # Save attribution for Creative Commons YouTube video
                if ATTRIBUTION_AVAILABLE and get_attribution_manager:
                    try:
                        attr_manager = get_attribution_manager()
                        if attr_manager.add_attribution(video_data, source='youtube'):
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
