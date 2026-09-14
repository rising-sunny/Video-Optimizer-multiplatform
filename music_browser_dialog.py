# music_browser_dialog.py
"""
Diálogo para buscar y seleccionar música de Jamendo con preview y recorte.
Extraído de auto_video_integration_pyqt6.py para mejorar la organización del código.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSlider, QLineEdit, QListWidget, QListWidgetItem,
    QDoubleSpinBox, QGroupBox, QProgressBar, QMessageBox, QWidget,
    QScrollArea, QFileDialog, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QPainter, QColor, QPen, QGuiApplication
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
import subprocess
import shutil

import os
import tempfile
import threading
import time
import hashlib

# Reproductor de audio: VLC (soporta todos los codecs)
try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    VLC_AVAILABLE = False
    print("âŒ python-vlc no disponible - REQUERIDO para reproducir audio")
except OSError as e:
    # Capturar error de DLL no encontrada (comÃºn en Windows con venvs)
    VLC_AVAILABLE = False
    print(f"âš ï¸ Error cargando librerÃ­a VLC (libvlc.dll): {e}")
    print("   AsegÃºrate de tener VLC instalado en el sistema (64-bit).")
except Exception as e:
    VLC_AVAILABLE = False
    print(f"âŒ Error inesperado importando vlc: {e}")


try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("âš ï¸ pydub no disponible. La visualizaciÃ³n de forma de onda y recorte de audio no funcionarÃ¡.")

from waveform_widget import WaveformWidget


class TimelineWidget(QWidget):
    """Widget personalizado para timeline con lÃ­nea de posiciÃ³n"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_position = 0.0
        self.duration = 0.0
        self.setMinimumHeight(30)
        self.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #3d3d3d; border-radius: 4px;")

    def set_position(self, position, duration):
        self.current_position = position
        self.duration = duration
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # Fondo
        painter.fillRect(self.rect(), QColor(42, 42, 42))

        # Dibujar lÃ­nea de posiciÃ³n actual
        if self.duration > 0 and self.current_position >= 0:
            position_x = int(
                (self.current_position / self.duration) * width
            ) if self.duration > 0 else 0
            painter.setPen(QPen(QColor(33, 150, 243), 2))  # Azul brillante
            painter.drawLine(position_x, 0, position_x, height)


class MusicBrowserDialog(QDialog):
    """
    Diálogo para buscar y seleccionar música de Jamendo con preview y recorte.
    """
    
    # Señales para comunicación thread-safe
    _play_file_signal = pyqtSignal(str)
    _download_error_signal = pyqtSignal(str)
    _download_progress_signal = pyqtSignal(int)  # (percentage)
    
    def __init__(self, parent=None, log_callback=None):
        try:
            super().__init__(parent)
            self.log_callback = log_callback or (lambda msg: print(msg))

            self.setWindowTitle(" Buscador de Música - Jamendo")
            self.setMinimumSize(900, 700)
            self.setModal(True)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

            # Resultados de la selección
            self.selected_music_path = None
            self.selected_music_paths = []   # multi-track playlist
            self.selected_music_metadata = None

            # Variables de estado
            self.current_music_track = None
            self.music_results = []
            self.music_duration = 0
            self.music_start_time = 0
            self.music_end_time = 0
            self.music_crop_start_value = 0.0
            self.music_crop_end_value = 0.0
            self._vlc_instance = None
            self._vlc_player = None
            self._qt_player = None
            self._qt_audio_output = None
            self._using_qt_player = False
            self._using_ffplay = False
            self._ffplay_path = None
            self._ffplay_process = None
            self.music_timeline_being_dragged = False

            # Conectar seÃ±ales thread-safe
            self._play_file_signal.connect(self._play_local_file)
            self._download_error_signal.connect(self._on_download_error)
            self._download_progress_signal.connect(self._on_download_progress)

            self.setup_ui()
            # NO inicializar VLC aquÃ­ - se harÃ¡ lazy cuando se necesite
            # self.setup_player()

            # Timer para actualizar timeline (crearlo aquÃ­ para evitar errores)
            self.music_timer = QTimer()
            self.music_timer.timeout.connect(self.update_timeline)
            self.music_timer.setInterval(100)

            # Limpiar al cerrar
            self.finished.connect(self.cleanup_on_close)

            print("âœ… DiÃ¡logo de mÃºsica inicializado correctamente (VLC se cargarÃ¡ bajo demanda)")

        except Exception as e:
            print(f"âŒ ERROR CRÃTICO inicializando diÃ¡logo de mÃºsica: {e}")
            import traceback
            traceback.print_exc()
            # Asegurarnos de que las variables crÃ­ticas existan
            if not hasattr(self, '_vlc_instance'):
                self._vlc_instance = None
            if not hasattr(self, '_vlc_player'):
                self._vlc_player = None
            raise  # Re-lanzar para que el padre pueda manejar el error
    
    def setup_ui(self):
        """Configura la interfaz de usuario"""
        main_layout = QVBoxLayout(self)
        
        # Crear scroll area para permitir desplazamiento vertical
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #1e1e1e;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                min-height: 30px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Widget contenedor para el contenido desplazable
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Campo de búsqueda
        search_layout = QHBoxLayout()
        search_label = QLabel("Buscar:")
        search_layout.addWidget(search_label)
        
        self.music_search_input = QLineEdit()
        self.music_search_input.setPlaceholderText(
            "Ej: cinematic, horror, dark, suspense, epic, orchestral...")
        self.music_search_input.returnPressed.connect(self.search_music)
        search_layout.addWidget(self.music_search_input)
        
        search_btn = QPushButton(" Buscar")
        search_btn.clicked.connect(self.search_music)
        search_layout.addWidget(search_btn)
        
        # Botón para seleccionar música local
        local_music_btn = QPushButton(" Música Local")
        local_music_btn.setToolTip("Seleccionar archivo de música desde tu PC")
        local_music_btn.clicked.connect(self.select_local_music_file)
        search_layout.addWidget(local_music_btn)
        
        layout.addLayout(search_layout)
        
        # Filtros de género y estado de ánimo
        filters_group = QGroupBox("️ Filtros")
        filters_layout = QVBoxLayout(filters_group)
        
        # Fila 1: GÃ©neros
        genre_layout = QHBoxLayout()
        genre_label = QLabel("ðŸŽµ GÃ©nero:")
        genre_label.setMinimumWidth(80)
        genre_layout.addWidget(genre_label)
        
        self.music_genre_combo = QComboBox()
        self.music_genre_combo.addItems([
            "Todos", "ClÃ¡sica", "Rock", "Pop", "ElectrÃ³nica", "Jazz",
            "Hip-Hop", "Ambient", "Cinematic", "Orchestral", "Soundtrack",
            "Folk", "Rock Alternativo", "Indie", "Ads/Comercial"
        ])
        self.music_genre_combo.setCurrentIndex(0)
        genre_layout.addWidget(self.music_genre_combo)
        genre_layout.addStretch()
        filters_layout.addLayout(genre_layout)
        
        # Fila 2: Estado de Ã¡nimo
        mood_layout = QHBoxLayout()
        mood_label = QLabel("ðŸ˜Š Estado de Ã¡nimo:")
        mood_label.setMinimumWidth(80)
        mood_layout.addWidget(mood_label)
        
        self.music_mood_combo = QComboBox()
        self.music_mood_combo.addItems([
            "Todos", "Feliz/Alegre", "Triste/MelancÃ³lico", "Suspenso/TensiÃ³n",
            "Ã‰pico/Inspirador", "Relajante/Calmado", "EnÃ©rgico/Intenso",
            "Oscuro/Siniestro", "RomÃ¡ntico", "NostÃ¡lgico", "Misterioso",
            "Heroico", "DramÃ¡tico", "Neutro"
        ])
        self.music_mood_combo.setCurrentIndex(0)
        mood_layout.addWidget(self.music_mood_combo)
        mood_layout.addStretch()
        filters_layout.addLayout(mood_layout)
        
        layout.addWidget(filters_group)
        
        # Lista de resultados
        results_label = QLabel("Resultados:")
        layout.addWidget(results_label)
        
        self.music_results_list = QListWidget()
        self.music_results_list.itemDoubleClicked.connect(self.select_music)
        layout.addWidget(self.music_results_list)

        self.copyright_filter_label = QLabel(
            "Only Creative Commons tracks are shown. Check NC/ND restrictions before publishing."
        )
        self.copyright_filter_label.setStyleSheet("color: #9ccc65; font-size: 11px;")
        layout.addWidget(self.copyright_filter_label)
        
        # Timeline y controles de preview
        timeline_layout = QHBoxLayout()
        self.music_time_current = QLabel("00:00")
        self.music_time_current.setMinimumWidth(50)
        self.music_time_current.setStyleSheet("color: #ffffff; font-weight: bold;")
        timeline_layout.addWidget(self.music_time_current)
        
        self.music_timeline_widget = TimelineWidget()
        timeline_layout.addWidget(self.music_timeline_widget)
        
        self.music_timeline = QSlider(Qt.Orientation.Horizontal)
        self.music_timeline.setEnabled(False)
        self.music_timeline.setMinimum(0)
        self.music_timeline.setMaximum(100)
        self.music_timeline.setValue(0)
        self.music_timeline.sliderPressed.connect(self.on_timeline_pressed)
        self.music_timeline.sliderReleased.connect(self.on_timeline_released)
        self.music_timeline.valueChanged.connect(self.on_timeline_changed)
        self.music_timeline.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555;
                height: 8px;
                background: #333;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4CAF50;
                border: 1px solid #4CAF50;
                width: 16px;
                height: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #4CAF50;
                border-radius: 4px;
            }
        """)
        timeline_layout.addWidget(self.music_timeline)
        
        self.music_time_total = QLabel("00:00")
        self.music_time_total.setMinimumWidth(50)
        self.music_time_total.setStyleSheet("color: #a0a0a0;")
        timeline_layout.addWidget(self.music_time_total)
        
        layout.addLayout(timeline_layout)
        
        # Widget de forma de onda
        waveform_label = QLabel("ðŸ“Š Forma de Onda:")
        layout.addWidget(waveform_label)
        
        # Barra de progreso para carga de forma de onda
        self.waveform_progress = QProgressBar()
        self.waveform_progress.setVisible(False)
        self.waveform_progress.setRange(0, 100)
        self.waveform_progress.setValue(0)
        self.waveform_progress.setTextVisible(True)
        self.waveform_progress.setFormat("Cargando forma de onda... %p%")
        layout.addWidget(self.waveform_progress)
        
        self.music_waveform = WaveformWidget()
        self.music_waveform.crop_range_changed.connect(self.on_waveform_crop_changed)
        self.music_waveform.position_clicked.connect(self.on_waveform_position_clicked)
        layout.addWidget(self.music_waveform)

        # Resumen del recorte en texto: la onda lo dibuja, pero leer los
        # numeros exactos ahi es incomodo cuando se ajusta fino.
        self.crop_summary_label = QLabel("Arrastra las barras amarillas para elegir el tramo")
        self.crop_summary_label.setStyleSheet(
            "color: #ffd633; font-size: 12px; padding: 4px 2px;")
        layout.addWidget(self.crop_summary_label)
        
        # Controles de recorte
        crop_group = QGroupBox("âœ‚ï¸ Recortar Pista")
        crop_layout = QVBoxLayout(crop_group)
        
        crop_controls_layout = QHBoxLayout()
        
        start_label = QLabel("Inicio:")
        crop_controls_layout.addWidget(start_label)
        self.music_crop_start = QDoubleSpinBox()
        self.music_crop_start.setMinimum(0.0)
        self.music_crop_start.setMaximum(3600.0)
        self.music_crop_start.setDecimals(2)
        self.music_crop_start.setSuffix(" s")
        self.music_crop_start.setEnabled(False)
        self.music_crop_start.valueChanged.connect(self.on_crop_changed)
        crop_controls_layout.addWidget(self.music_crop_start)
        
        crop_controls_layout.addStretch()
        
        end_label = QLabel("Fin:")
        crop_controls_layout.addWidget(end_label)
        self.music_crop_end = QDoubleSpinBox()
        self.music_crop_end.setMinimum(0.0)
        self.music_crop_end.setMaximum(3600.0)
        self.music_crop_end.setDecimals(2)
        self.music_crop_end.setSuffix(" s")
        self.music_crop_end.setEnabled(False)
        self.music_crop_end.valueChanged.connect(self.on_crop_changed)
        crop_controls_layout.addWidget(self.music_crop_end)
        
        crop_layout.addLayout(crop_controls_layout)
        
        # Botones de recorte
        crop_buttons_layout = QHBoxLayout()
        
        reset_crop_btn = QPushButton("â†©ï¸ Resetear Recorte")
        reset_crop_btn.setEnabled(False)
        reset_crop_btn.clicked.connect(self.reset_crop_range)
        reset_crop_btn.setToolTip("Restablece el recorte a toda la pista")
        crop_buttons_layout.addWidget(reset_crop_btn)
        self.reset_crop_btn = reset_crop_btn
        
        # BotÃ³n para aplicar recorte manualmente
        apply_crop_btn = QPushButton("âœ‚ï¸ Aplicar Recorte")
        apply_crop_btn.setEnabled(False)
        apply_crop_btn.clicked.connect(self.apply_crop_preview)
        apply_crop_btn.setToolTip("Aplica el recorte configurado y actualiza la vista")
        crop_buttons_layout.addWidget(apply_crop_btn)
        self.apply_crop_btn = apply_crop_btn
        
        # BotÃ³n para guardar recorte como archivo
        save_crop_btn = QPushButton("ðŸ’¾ Guardar Recorte")
        save_crop_btn.setEnabled(False)
        save_crop_btn.clicked.connect(self.save_cropped_audio)
        save_crop_btn.setToolTip("Guarda la secciÃ³n recortada como un archivo MP3 separado")
        crop_buttons_layout.addWidget(save_crop_btn)
        self.save_crop_btn = save_crop_btn
        
        crop_buttons_layout.addStretch()
        crop_layout.addLayout(crop_buttons_layout)
        
        layout.addWidget(crop_group)
        
        # Controles de preview
        preview_layout = QHBoxLayout()
        self.music_play_btn = QPushButton("â–¶ï¸ Play")
        self.music_play_btn.setEnabled(False)
        self.music_play_btn.clicked.connect(self.play_music_preview)
        preview_layout.addWidget(self.music_play_btn)
        
        self.music_stop_btn = QPushButton("â¹ï¸ Stop")
        self.music_stop_btn.setEnabled(False)
        self.music_stop_btn.clicked.connect(self.stop_music_preview)
        preview_layout.addWidget(self.music_stop_btn)
        
        self.music_play_crop_btn = QPushButton("â–¶ï¸ Play Recorte")
        self.music_play_crop_btn.setEnabled(False)
        self.music_play_crop_btn.setToolTip(
            "Reproduce solo la secciÃ³n entre las barras de inicio y fin")
        self.music_play_crop_btn.clicked.connect(self.play_music_crop)
        preview_layout.addWidget(self.music_play_crop_btn)
        
        preview_layout.addStretch()
        
        self.select_btn = QPushButton("âœ… Seleccionar MÃºsica")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.select_music)
        preview_layout.addWidget(self.select_btn)
        
        layout.addLayout(preview_layout)
        
        # Barra de progreso de descarga
        self.music_download_progress = QProgressBar()
        self.music_download_progress.setVisible(False)
        self.music_download_progress.setRange(0, 100)
        self.music_download_progress.setFormat("Descargando: %p%")
        self.music_download_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 4px;
                text-align: center;
                background-color: #2a2a2a;
                color: #ffffff;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.music_download_progress)
        
        # Info label
        info_label = QLabel("ðŸ’¡ Doble click en una pista para seleccionarla")
        info_label.setStyleSheet("color: #a0a0a0; font-style: italic;")
        layout.addWidget(info_label)

        # AtribuciÃ³n para YouTube
        attribution_group = QGroupBox("YouTube Attribution (English)")
        attribution_layout = QVBoxLayout(attribution_group)

        self.attribution_status_label = QLabel(
            "Select a track to generate attribution text for YouTube description."
        )
        self.attribution_status_label.setStyleSheet("color: #d0d0d0;")
        attribution_layout.addWidget(self.attribution_status_label)

        self.youtube_attribution_text = QTextEdit()
        self.youtube_attribution_text.setReadOnly(True)
        self.youtube_attribution_text.setPlaceholderText(
            "Attribution text will appear here."
        )
        self.youtube_attribution_text.setMinimumHeight(100)
        attribution_layout.addWidget(self.youtube_attribution_text)

        attribution_actions = QHBoxLayout()
        attribution_actions.addStretch()
        self.copy_attribution_btn = QPushButton("Copy Attribution")
        self.copy_attribution_btn.setEnabled(False)
        self.copy_attribution_btn.clicked.connect(self.copy_attribution_to_clipboard)
        attribution_actions.addWidget(self.copy_attribution_btn)
        attribution_layout.addLayout(attribution_actions)

        layout.addWidget(attribution_group)
        
        # Agregar stretch al final para que el contenido no se estire
        layout.addStretch()
        
        # Configurar el scroll area con el contenido
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, 1)  # El Ã¡rea de scroll usa todo el espacio disponible
        
        # Conectar selecciÃ³n de item
        self.music_results_list.itemSelectionChanged.connect(self.on_music_item_selected)
    
    def setup_player(self):
        """Configura el reproductor de audio (VLC, FFplay o QtMultimedia)"""
        # 1. Intentar VLC (Mejor opciÃ³n, nativa y completa)
        if VLC_AVAILABLE:
            try:
                vlc_options = [
                    '--intf', 'dummy',
                    '--no-video',
                    '--aout=directsound',
                    '--quiet',
                    '--no-sub-autodetect-file',
                    '--no-metadata-network-access',
                ]
                print("ðŸŽµ Inicializando reproductor VLC...")
                self._vlc_instance = vlc.Instance(vlc_options)

                if self._vlc_instance:
                    self._vlc_player = self._vlc_instance.media_player_new()
                    if self._vlc_player:
                        print("âœ… Reproductor VLC configurado correctamente")
                        self._using_qt_player = False
                        self._using_ffplay = False
                        return
            except Exception as e:
                print(f"âš ï¸ Error configurando VLC: {e}")
        
        # 2. Intentar FFplay (Segunda mejor opciÃ³n, muy robusta si ffmpeg estÃ¡ instalado)
        print("âš ï¸ VLC no disponible o fallÃ³. Intentando fallback a FFplay...")
        self._check_ffplay()
        if self._ffplay_path:
            self._using_ffplay = True
            self._using_qt_player = False
            print(f"âœ… FFplay encontrado en: {self._ffplay_path}")
            return

        # 3. Intentar QtMultimedia (Ãšltimo recurso, puede ser problemÃ¡tico con codecs)
        print("âš ï¸ FFplay no encontrado. Intentando fallback a QtMultimedia...")
        try:
            # Verificar si hay dispositivos de audio disponibles
            audio_devices = QMediaDevices.audioOutputs()
            if not audio_devices:
                print("âš ï¸ QtMultimedia: No se detectaron dispositivos de salida de audio.")
                raise Exception("No audio devices found")

            self._qt_player = QMediaPlayer()
            self._qt_audio_output = QAudioOutput()
            self._qt_player.setAudioOutput(self._qt_audio_output)
            self._qt_audio_output.setVolume(1.0)
            
            # Conectar seÃ±ales
            self._qt_player.playbackStateChanged.connect(self._on_qt_state_changed)
            self._qt_player.errorOccurred.connect(self._on_qt_error)
            
            self._using_qt_player = True
            self._using_ffplay = False
            print("âœ… Reproductor QtMultimedia configurado correctamente")
            return
            
        except Exception as e:
            print(f"âŒ Error configurando QtMultimedia: {e}")
            self._qt_player = None
            self._using_qt_player = False

        print("âŒ No hay reproductores de audio disponibles.")

    def _check_ffplay(self):
        """Busca ffplay en el sistema"""
        # Buscar en PATH
        ffplay = shutil.which("ffplay")
        if ffplay:
            self._ffplay_path = ffplay
            return

        # Buscar en ubicaciones comunes o relativas a ffmpeg conocido
        common_paths = [
            r"C:\ffmpeg\bin\ffplay.exe",
            r"C:\Program Files\ffmpeg\bin\ffplay.exe",
        ]
        
        # Intentar inferir de la variable de entorno si existe
        # (Asumiendo que el script principal configurÃ³ FFmpeg)
        
        for path in common_paths:
            if os.path.exists(path):
                self._ffplay_path = path
                return
    
    def _on_qt_error(self, error, error_string):
        """Maneja errores de QtMultimedia"""
        print(f"âŒ Error QtMultimedia: {error} - {error_string}")
        # Si ocurre un error, intentar cambiar a FFplay si es posible
        if self._using_qt_player:
             print("   âš ï¸ Fallo en tiempo de ejecuciÃ³n de QtMultimedia. Deshabilitando...")
             self._using_qt_player = False
             if not self._using_ffplay:
                 self._check_ffplay()
                 if self._ffplay_path:
                     self._using_ffplay = True
                     print("   âœ… Cambiado a fallback FFplay")

    def _on_qt_state_changed(self, state):
        """Callback para cambios de estado de QtMultimedia"""
        if state == QMediaPlayer.PlaybackState.StoppedState:
            # Si se detuvo por fin de archivo (y no por stop manual)
            if self._music_is_playing and not self.music_is_paused:
                 # Manejado por el timer update_timeline
                 pass

    def cleanup_on_close(self):
        """Limpia recursos al cerrar el diÃ¡logo"""
        try:
            self.music_timer.stop()
            if hasattr(self, '_vlc_player') and self._vlc_player:
                self._vlc_player.stop()
            
            if hasattr(self, '_qt_player') and self._qt_player:
                self._qt_player.stop()
            
            if hasattr(self, '_ffplay_process') and self._ffplay_process:
                try:
                    self._ffplay_process.terminate()
                    self._ffplay_process = None
                except:
                    pass
                
            if hasattr(self, '_currently_playing_file'):
                delattr(self, '_currently_playing_file')
        except Exception as e:
            print(f"âš ï¸ Error en cleanup: {e}")
    
    def log(self, message):
        """Registra un mensaje usando el callback"""
        self.log_callback(message)

    def _extract_license_code(self, license_url):
        """Normaliza la licencia CC a un codigo corto."""
        if not license_url:
            return "UNKNOWN"

        normalized = str(license_url).lower().strip()
        if "publicdomain/zero" in normalized or "/zero/" in normalized:
            return "CC0"

        for code in ["by-nc-nd", "by-nc-sa", "by-nc", "by-nd", "by-sa", "by"]:
            if f"/licenses/{code}/" in normalized:
                return f"CC {code.upper()}"

        return "UNKNOWN"

    def _is_youtube_safe_license(self, license_url):
        """Acepta licencias CC conocidas (con sus restricciones NC/ND)."""
        return self._extract_license_code(license_url) != "UNKNOWN"

    def _build_youtube_attribution_text(self, track):
        """Genera texto en ingles para pegar en descripcion de YouTube."""
        title = track.get('title', 'Unknown title')
        artist = track.get('artist', 'Unknown artist')
        license_url = track.get('license_url', '')
        license_code = track.get('license_code') or self._extract_license_code(license_url)
        track_url = (
            track.get('share_url')
            or track.get('short_url')
            or (f"https://www.jamendo.com/track/{track.get('track_id')}" if track.get('track_id') else "")
        )

        lines = [
            f"Music: \"{title}\" by {artist}",
        ]
        if track_url:
            lines.append(f"Track link: {track_url}")

        if license_url and license_code != "UNKNOWN":
            lines.append(f"License: {license_code} ({license_url})")
        elif license_url:
            lines.append(f"License: {license_url}")
        else:
            lines.append("License: Not provided")

        lines.append("Source: Jamendo")
        return "\n".join(lines)

    def _build_license_restriction_note(self, license_code):
        """Devuelve advertencia de uso para NC/ND."""
        if not license_code or license_code == "UNKNOWN":
            return "License unknown: verify rights manually before publishing."

        notes = []
        if "-NC" in license_code:
            notes.append("Non-commercial license: avoid monetization on YouTube.")
        if "-ND" in license_code:
            notes.append("No-derivatives license: avoid remixing or editing the music.")

        if notes:
            return " ".join(notes)
        return "Commercial use is generally allowed under this CC license."

    def _update_attribution_panel(self, track):
        """Actualiza UI de atribucion segun la pista seleccionada."""
        if not track:
            self.attribution_status_label.setText(
                "Select a track to generate attribution text for YouTube description."
            )
            self.youtube_attribution_text.clear()
            self.copy_attribution_btn.setEnabled(False)
            return

        if track.get('source') == 'local':
            self.attribution_status_label.setText(
                "Local file selected. Make sure you own rights or license before publishing."
            )
            self.youtube_attribution_text.setPlainText(
                "No automatic attribution for local files.\n"
                "Confirm that you own commercial rights before uploading to YouTube."
            )
            self.copy_attribution_btn.setEnabled(True)
            return

        attribution_text = self._build_youtube_attribution_text(track)
        self.youtube_attribution_text.setPlainText(attribution_text)
        license_note = self._build_license_restriction_note(track.get('license_code', 'UNKNOWN'))

        if track.get('attribution_required', False):
            self.attribution_status_label.setText(
                f"Attribution required: copy and paste this text into your YouTube description. {license_note}"
            )
        else:
            self.attribution_status_label.setText(
                f"Attribution optional for this license, but keeping the credit is recommended. {license_note}"
            )
        self.copy_attribution_btn.setEnabled(True)

    def copy_attribution_to_clipboard(self):
        """Copia la atribucion al portapapeles."""
        text = self.youtube_attribution_text.toPlainText().strip()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self.log("[OK] Attribution text copied to clipboard")
    
    # ========== MÉTODOS DE BÚSQUEDA ==========
    
    def search_music(self):
        """Busca música en Jamendo con filtros de género y estado de ánimo"""
        try:
            from music_recommender import search_jamendo_api
            from dotenv import load_dotenv
            load_dotenv('.env')
        except Exception as e:
            self.log(f"Error importando módulos de búsqueda: {e}")
            QMessageBox.critical(self, "Error", f"No se pudo cargar el módulo de búsqueda de música: {e}")
            return

        genre = self.music_genre_combo.currentText()
        mood = self.music_mood_combo.currentText()
        
        genre_tags_map = {
            "Todos": [],
            "Clásica": ["classical", "orchestral"],
            "Rock": ["rock"],
            "Pop": ["pop", "upbeat", "mainstream"],
            "Electrónica": ["electronic", "dance"],
            "Jazz": ["jazz", "blues", "swing"],
            "Hip-Hop": ["hiphop", "rap", "urban"],
            "Ambient": ["ambient", "chillout", "meditation"],
            "Cinematic": ["cinematic", "epic"],
            "Orchestral": ["orchestral", "classical"],
            "Soundtrack": ["soundtrack", "movie", "cinematic"],
            "Folk": ["folk", "acoustic", "country"],
            "Rock Alternativo": ["alternative", "indie", "rock"],
            "Indie": ["indie", "alternative", "indie rock"],
            "Ads/Comercial": ["advertising", "commercial", "corporate"]
        }
        
        mood_tags_map = {
            "Todos": [],
            "Feliz/Alegre": ["happy", "upbeat", "cheerful", "joyful"],
            "Triste/Melancólico": ["sad", "melancholy", "somber"],
            "Suspenso/Tensión": ["suspense", "tension", "dark", "mysterious"],
            "Épico/Inspirador": ["epic", "inspirational", "uplifting"],
            "Relajante/Calmado": ["relaxed", "calm", "peaceful", "chill"],
            "Enérgico/Intenso": ["energetic", "intense", "powerful", "dynamic"],
            "Oscuro/Siniestro": ["dark", "sinister", "ominous", "horror"],
            "Romántico": ["romantic", "love", "emotional"],
            "Nostálgico": ["nostalgic", "melancholy", "retro"],
            "Misterioso": ["mysterious", "intriguing", "suspense"],
            "Heroico": ["heroic", "victorious", "triumphant"],
            "Dramático": ["dramatic", "emotional", "intense"],
            "Neutro": ["neutral", "ambient", "background"]
        }
        
        tags = []
        if genre in genre_tags_map:
            tags.extend(genre_tags_map[genre])
        if mood in mood_tags_map:
            tags.extend(mood_tags_map[mood])
            
        unique_tags = []
        for tag in tags:
            if tag not in unique_tags:
                unique_tags.append(tag)
        tags = unique_tags
        
        # Agregar búsqueda manual si hay texto
        search_terms = self.music_search_input.text().strip()
        if search_terms:
            manual_tags = [t.strip() for t in search_terms.split(',') if t.strip()]
            tags.extend(manual_tags)
        
        if not tags:
            tags = ["cinematic"]
        
        jamendo_id = os.getenv('JAMENDO_CLIENT_ID', '')
        if not jamendo_id or 'TU_CLIENT_ID' in jamendo_id:
            QMessageBox.warning(
                self, "API no configurada",
                "JAMENDO_CLIENT_ID no está configurado en .env\n\n"
                "Obtén tu Client ID en: https://devportal.jamendo.com/")
            return
        
        self.log(f"[INFO] Buscando musica con tags: {', '.join(tags)}")
        
        try:
            raw_results = search_jamendo_api(tags, jamendo_id, limit=40)
            self.music_results_list.clear()
            self._update_attribution_panel(None)

            filtered_out = 0
            safe_results = []
            for track in raw_results:
                # Etiqueta de origen explícita para reglas posteriores (ej. Shorts >60s).
                track['source'] = 'jamendo'
                license_url = track.get('license_url', '')
                license_code = track.get('license_code') or self._extract_license_code(license_url)
                track['license_code'] = license_code

                youtube_safe = track.get('youtube_safe')
                if youtube_safe is None:
                    youtube_safe = self._is_youtube_safe_license(license_url)
                track['youtube_safe'] = bool(youtube_safe)

                track['attribution_required'] = track.get('attribution_required')
                if track['attribution_required'] is None:
                    track['attribution_required'] = license_code not in {"CC0", "UNKNOWN"}

                if track['youtube_safe']:
                    track['youtube_attribution_text'] = self._build_youtube_attribution_text(track)
                    safe_results.append(track)
                else:
                    filtered_out += 1

            self.music_results = safe_results[:20]
             
            if not self.music_results:
                self.music_results_list.addItem(
                    "No Creative Commons results found for this search."
                )
                if filtered_out > 0:
                    self.log(f"[WARN] Se filtraron {filtered_out} pista(s) sin licencia CC valida")
                return

            for track in self.music_results:
                title = track.get('title', 'Sin título')
                artist = track.get('artist', 'Artista desconocido')
                duration = track.get('duration', 0)
                duration_str = f"{duration//60}:{duration%60:02d}" if duration > 0 else "--:--"
                license_code = track.get('license_code', 'UNKNOWN')
                
                item_text = f"[DL][{license_code}] {title} - {artist} ({duration_str})"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, track)
                self.music_results_list.addItem(item)
            
            if filtered_out > 0:
                self.log(f"[WARN] Se filtraron {filtered_out} pista(s) sin licencia CC valida")
            self.log(f"[OK] Se encontraron {len(self.music_results)} pistas con licencia CC en Jamendo")
            
        except Exception as e:
            self.log(f"Error buscando música: {e}")
            QMessageBox.critical(self, "Error de Búsqueda", f"Ocurrió un error al buscar música: {e}")
    
    def on_music_item_selected(self):
        """Cuando se selecciona un item de música"""
        current_item = self.music_results_list.currentItem()
        track_data = current_item.data(Qt.ItemDataRole.UserRole) if current_item else None

        if current_item and isinstance(track_data, dict):
            self.music_play_btn.setEnabled(True)
            self.music_stop_btn.setEnabled(True)
            self.select_btn.setEnabled(True)
            self.current_music_track = track_data
            self._update_attribution_panel(self.current_music_track)
            
            duration = self.current_music_track.get('duration', 0)
            if duration > 0:
                self.music_timeline.setMaximum(int(duration * 1000))
                self.music_time_total.setText(self.format_time(duration))
                
                self.music_crop_start.setMaximum(duration)
                self.music_crop_end.setMaximum(duration)
                self.music_crop_start.setValue(0.0)
                self.music_crop_end.setValue(duration)
                self.music_crop_start.setEnabled(True)
                self.music_crop_end.setEnabled(True)
                if hasattr(self, 'reset_crop_btn'):
                    self.reset_crop_btn.setEnabled(True)
                if hasattr(self, 'apply_crop_btn'):
                    self.apply_crop_btn.setEnabled(True)
                if hasattr(self, 'save_crop_btn'):
                    self.save_crop_btn.setEnabled(True)
                
                self.music_crop_start_value = 0.0
                self.music_crop_end_value = duration
                self.music_play_crop_btn.setEnabled(True)
                
                self.music_timeline_widget.set_position(0.0, duration)
                self.load_waveform_for_track(self.current_music_track)
            else:
                self.music_timeline.setMaximum(100)
                self.music_time_total.setText("--:--")
                self.music_crop_start.setEnabled(False)
                self.music_crop_end.setEnabled(False)
                if hasattr(self, 'reset_crop_btn'):
                    self.reset_crop_btn.setEnabled(False)
                if hasattr(self, 'apply_crop_btn'):
                    self.apply_crop_btn.setEnabled(False)
                if hasattr(self, 'save_crop_btn'):
                    self.save_crop_btn.setEnabled(False)
            
            self.music_timeline.setValue(0)
            self.music_timeline.setEnabled(True)
            self.music_time_current.setText("00:00")
        else:
            self.current_music_track = None
            self.music_play_btn.setEnabled(False)
            self.music_stop_btn.setEnabled(False)
            self.select_btn.setEnabled(False)
            self.music_timeline.setEnabled(False)
            self.music_crop_start.setEnabled(False)
            self.music_crop_end.setEnabled(False)
            if hasattr(self, 'reset_crop_btn'):
                self.reset_crop_btn.setEnabled(False)
            if hasattr(self, 'apply_crop_btn'):
                self.apply_crop_btn.setEnabled(False)
            if hasattr(self, 'save_crop_btn'):
                self.save_crop_btn.setEnabled(False)
            self._update_attribution_panel(None)
    
    # ========== MÃ‰TODOS DE REPRODUCCIÃ“N ==========
    
    def play_music_preview(self):
        """Reproduce preview de la música seleccionada"""
        if not self.current_music_track:
            return

        # Inicializar reproductores solo cuando el usuario intente reproducir (lazy loading)
        if self._vlc_instance is None and self._qt_player is None and not self._using_ffplay:
            print("ðŸŽµ Primera reproducciÃ³n detectada - inicializando reproductores...")
            self.setup_player()
            
            if self._vlc_instance is None and self._qt_player is None and not self._using_ffplay:
                QMessageBox.warning(
                    self,
                    "Reproductores no disponibles",
                    "No se pudo inicializar ni VLC, ni FFplay, ni el reproductor del sistema (QtMultimedia).\n\n"
                    "Puedes continuar seleccionando mÃºsica sin reproducirla."
                )
                return

        try:
            # Verificar si es un archivo local
            if self.current_music_track.get('source') == 'local':
                local_path = self.current_music_track.get('local_path')
                if not local_path or not os.path.exists(local_path):
                    QMessageBox.warning(self, "Error", "El archivo local no existe o no es accesible")
                    return
                
                # Reproducir directamente el archivo local
                self._play_file_signal.emit(local_path)
                return

            # Para archivos de Jamendo, continuar con la lógica original
            audio_url = self.current_music_track.get('audio_url')
            if not audio_url:
                QMessageBox.warning(
                    self,
                    "Sin URL de audio",
                    "Esta pista no tiene URL de descarga disponible."
                )
                return
            
            self.music_play_btn.setText("â³ Descargando...")
            self.music_play_btn.setEnabled(False)
            
            if hasattr(self, 'music_download_progress'):
                self.music_download_progress.setValue(0)
                self.music_download_progress.setVisible(True)
            
            track_id = self.current_music_track.get('title', 'track').replace(' ', '_').replace('/', '_')
            temp_path = os.path.join(tempfile.gettempdir(), f"jamendo_preview_{track_id}.mp3")
            
            if hasattr(self, '_current_preview_path') and self._current_preview_path == temp_path and os.path.exists(temp_path):
                print(f"ðŸŽµ Usando archivo en cachÃ©: {temp_path}")
                if hasattr(self, '_currently_playing_file') and self._currently_playing_file == temp_path:
                    if self._using_qt_player:
                        if self._qt_player and self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                            print("   â„¹ï¸ La pista ya estÃ¡ reproduciÃ©ndose (Qt)")
                            return
                    elif self._vlc_player and self._vlc_player.is_playing():
                        print("   â„¹ï¸ La pista ya estÃ¡ reproduciÃ©ndose (VLC)")
                        return
                self._play_file_signal.emit(temp_path)
            else:
                self._download_cancelled = False
                
                def download_and_play():
                    try:
                        import requests
                    except Exception as import_error:
                        print(f"âŒ Error importando requests: {import_error}")
                        self._download_error_signal.emit(
                            "No se pudo cargar la librerÃ­a 'requests' para descargar el preview."
                        )
                        return

                    try:
                        print(f"ðŸŽµ Descargando audio desde: {audio_url}")
                        response = requests.get(audio_url, timeout=(10, 15), stream=True)
                        if response.status_code == 200:
                            total_size = int(response.headers.get('content-length', 0))
                            downloaded = 0
                            
                            with open(temp_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    if self._download_cancelled:
                                        print("ðŸ›‘ Descarga cancelada")
                                        return
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if total_size > 0:
                                        pct = int((downloaded / total_size) * 100)
                                        self._download_progress_signal.emit(pct)
                                        if pct % 10 == 0 or downloaded % 51200 < 8192:
                                            print(f"   ðŸ“¥ Descargando: {pct}%")
                            
                            if not self._download_cancelled:
                                self._download_progress_signal.emit(100)
                                self._current_preview_path = temp_path
                                print(f"âœ… Descarga completada: {downloaded/1024:.1f} KB")
                                self._play_file_signal.emit(temp_path)
                        else:
                            print(f"âŒ Error descargando: HTTP {response.status_code}")
                            self._download_error_signal.emit(f"Error HTTP: {response.status_code}")
                    except requests.exceptions.Timeout:
                        print(f"âŒ Timeout en descarga (servidor muy lento)")
                        self._download_error_signal.emit(
                            "Timeout: El servidor de Jamendo estÃ¡ muy lento.\nIntenta con otra pista.")
                    except Exception as e:
                        print(f"âŒ Error descargando: {e}")
                        self._download_error_signal.emit(str(e))
                
                threading.Thread(target=download_and_play, daemon=True).start()
        
        except Exception as e:
            print(f"âŒ Error en play_music_preview: {e}")
            QMessageBox.warning(self, "Error", f"No se pudo reproducir preview:\n{e}")
    
    def _play_local_file(self, file_path):
        """Reproduce un archivo de audio local usando VLC, QtMultimedia o FFplay"""
        if not VLC_AVAILABLE and not self._using_qt_player and not self._using_ffplay:
            self._on_download_error(
                "No hay reproductor de audio disponible.\n"
                "Intenta instalar VLC Media Player o verificar FFmpeg."
            )
            return
        
        if hasattr(self, '_currently_playing_file') and self._currently_playing_file == file_path:
            if self._using_qt_player:
                if self._qt_player and self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    return
            elif self._using_ffplay:
                if self._ffplay_process and self._ffplay_process.poll() is None:
                    return
            elif self._vlc_player and self._vlc_player.is_playing():
                print(f"âš ï¸ Archivo ya se estÃ¡ reproduciendo: {file_path}")
                return
        
        print(f"ðŸŽµ Reproduciendo archivo local: {file_path}")
        
        if not os.path.exists(file_path):
            print(f"âŒ Archivo no encontrado: {file_path}")
            self._on_download_error("Archivo descargado no encontrado")
            return
        
        file_size = os.path.getsize(file_path)
        print(f"   ðŸ“ TamaÃ±o del archivo: {file_size/1024:.1f} KB")
        
        if file_size < 1000:
            print(f"âŒ Archivo demasiado pequeÃ±o, probablemente corrupto")
            self._on_download_error("Archivo descargado parece estar corrupto")
            return
        
        try:
            # Obtener duraciÃ³n con pydub si estÃ¡ disponible
            if PYDUB_AVAILABLE:
                try:
                    audio = AudioSegment.from_mp3(file_path)
                    self.music_duration = len(audio) / 1000.0
                    print(f"   â±ï¸ DuraciÃ³n: {self.music_duration:.1f} segundos")
                except Exception as e:
                    print(f"âš ï¸ No se pudo obtener duraciÃ³n: {e}")
                    if self.current_music_track:
                        self.music_duration = self.current_music_track.get('duration', 0)
                    else:
                        self.music_duration = 0
            else:
                if self.current_music_track:
                    self.music_duration = self.current_music_track.get('duration', 0)
                else:
                    self.music_duration = 0
            
            # Detener cualquier reproducciÃ³n anterior
            if self._vlc_player:
                self._vlc_player.stop()
            if self._qt_player:
                self._qt_player.stop()
            if self._ffplay_process:
                try:
                    self._ffplay_process.terminate()
                    self._ffplay_process = None
                except:
                    pass
            
            # === RUTA FFPLAY ===
            if self._using_ffplay and self._ffplay_path:
                self._play_with_ffplay(file_path)
                return

            # === RUTA QT MULTIMEDIA ===
            if self._using_qt_player and self._qt_player:
                print("   ðŸŽ¬ Iniciando reproducciÃ³n con QtMultimedia...")
                abs_path = os.path.abspath(file_path)
                url = QUrl.fromLocalFile(abs_path)
                self._qt_player.setSource(url)
                self._qt_player.play()
                
                # Ã‰xito inmediato (asumido)
                self._music_is_playing = True
                self._currently_playing_file = file_path
                self.music_start_time = time.time()
                self.music_is_paused = False
                
                # Actualizar UI
                self._update_playback_ui()
                
                # Iniciar timer para actualizar timeline
                if hasattr(self, 'music_timer'):
                    self.music_timer.start(100)
                return

            # === RUTA VLC ===
            # Crear media y cargar archivo
            abs_path = os.path.abspath(file_path)
            media = self._vlc_instance.media_new(abs_path)
            self._vlc_player.set_media(media)
            
            # Configurar volumen (0-100)
            self._vlc_player.audio_set_volume(100)
            
            # Reproducir
            print("   ðŸŽ¬ Iniciando reproducciÃ³n con VLC...")
            result = self._vlc_player.play()

            if result == 0:  # 0 = Ã©xito en la llamada
                # Esperar mÃ¡s tiempo y verificar mÃºltiples veces
                # VLC puede tardar varios segundos en abrir archivos MP3, especialmente con metadatos
                max_attempts = 75
                wait_time = 0.2
                start_wait = time.time()
                max_wait_seconds = 15.0

                for attempt in range(max_attempts):
                    time.sleep(wait_time)

                    state = self._vlc_player.get_state()
                    is_playing = self._vlc_player.is_playing()
                    position_ms = self._vlc_player.get_time()
                    
                    # Verificar si el archivo se abriÃ³ correctamente (duraciÃ³n > 0)
                    duration_ms = self._vlc_player.get_length()
                    file_opened = duration_ms > 0
                    elapsed = time.time() - start_wait

                    print(
                        f"   ðŸ” Intento {attempt + 1}/{max_attempts}: "
                        f"Estado={state}, Playing={is_playing}, "
                        f"Pos={position_ms}ms, Duracion={duration_ms}ms, t={elapsed:.1f}s"
                    )

                    # Considerar Ã©xito si estÃ¡ reproduciendo O si estÃ¡ buffering y el archivo se abriÃ³
                    # Buffering significa que VLC estÃ¡ progresando correctamente
                    if is_playing or state == vlc.State.Playing or position_ms > 0:
                        print("   âœ… ReproducciÃ³n con VLC iniciada correctamente")
                        self._music_is_playing = True
                        self._currently_playing_file = file_path
                        self.music_start_time = (
                            time.time() - (position_ms / 1000.0)
                            if position_ms and position_ms > 0
                            else time.time()
                        )
                        self.music_is_paused = False

                        # Obtener duraciÃ³n desde VLC si no la tenemos
                        if duration_ms > 0 and self.music_duration == 0:
                            self.music_duration = duration_ms / 1000.0
                            print(f"   â±ï¸ DuraciÃ³n desde VLC: {self.music_duration:.1f}s")

                        # Actualizar UI
                        self._update_playback_ui()

                        # Iniciar timer para actualizar timeline
                        if hasattr(self, 'music_timer'):
                            self.music_timer.start(100)

                        return  # Ã‰xito
                    
                    # Si estÃ¡ buffering y el archivo se abriÃ³, es una buena seÃ±al
                    # Continuar esperando ya que estÃ¡ progresando
                    if state in [vlc.State.Opening, vlc.State.Buffering]:
                        if file_opened:
                            print("   â³ VLC aun inicializando (archivo abierto), continuando...")
                        else:
                            print("   â³ VLC aun inicializando, continuando...")
                        if elapsed < max_wait_seconds:
                            continue

                    if state == vlc.State.Paused:
                        print("   âœ… VLC listo en pausa")
                        self._music_is_playing = True
                        self._currently_playing_file = file_path
                        self.music_start_time = time.time()
                        self.music_is_paused = True
                        self._update_playback_ui()
                        if hasattr(self, 'music_timer'):
                            self.music_timer.start(100)
                        return

                    # Si el estado es error, salir inmediatamente
                    if state in [vlc.State.Error, vlc.State.Ended]:
                        print(f"   âŒ VLC entrÃ³ en estado de error: {state}")
                        break

                    if elapsed >= max_wait_seconds:
                        break

                # Si llegamos aquÃ­, no se pudo reproducir con VLC
                print("   âŒ VLC no pudo iniciar reproducciÃ³n despuÃ©s de mÃºltiples intentos")

                # Preferir FFplay antes que QtMultimedia para evitar problemas de codecs.
                print("   ️ Intentando fallback a FFplay...")
                self._check_ffplay()
                if self._ffplay_path:
                    self._using_ffplay = True
                    self._play_with_ffplay(file_path)
                    return

                # Intentar fallback a QtMultimedia si fallÃ³ VLC
                print("   âš ï¸ Intentando fallback a QtMultimedia...")
                try:
                    # Verificar si hay dispositivos antes de intentar
                    if not QMediaDevices.audioOutputs():
                        raise Exception("No audio devices")

                    if not self._qt_player:
                        self._qt_player = QMediaPlayer()
                        self._qt_audio_output = QAudioOutput()
                        self._qt_player.setAudioOutput(self._qt_audio_output)
                        self._qt_audio_output.setVolume(1.0)
                        self._qt_player.playbackStateChanged.connect(self._on_qt_state_changed)
                        self._qt_player.errorOccurred.connect(self._on_qt_error)
                    
                    self._using_qt_player = True
                    # Reintentar recursivamente con el nuevo flag
                    self._play_local_file(file_path)
                    return
                except Exception as e_qt:
                    print(f"   âŒ Fallback a QtMultimedia tambiÃ©n fallÃ³: {e_qt}")
                    
                    # Intentar fallback a FFplay
                    print("   âš ï¸ Intentando fallback a FFplay...")
                    self._check_ffplay()
                    if self._ffplay_path:
                        self._using_ffplay = True
                        self._play_with_ffplay(file_path)
                        return
                
                self._on_download_error(
                    "VLC no pudo reproducir el archivo.\n\n"
                    "Posibles causas:\n"
                    "â€¢ CÃ³dec de audio no soportado\n"
                    "â€¢ Problema con drivers de audio\n"
                    "â€¢ VLC no tiene permisos suficientes\n\n"
                    "Puedes seleccionar la mÃºsica sin reproducirla."
                )
            else:
                print(f"   âŒ Error iniciando VLC: cÃ³digo {result}")
                self._on_download_error(f"Error al reproducir archivo con VLC (cÃ³digo: {result})")
        
        except Exception as e:
            print(f"âŒ Error reproduciendo: {e}")
            import traceback
            traceback.print_exc()
            self._on_download_error(f"Error al reproducir archivo:\n{e}")

    def _play_with_ffplay(self, file_path, start_pos=0.0):
        """Reproduce audio usando ffplay (subprocess)"""
        try:
            # -nodisp: sin ventana
            # -autoexit: salir al terminar
            # -hide_banner: menos log
            # -loglevel panic: ocultar logs
            # -ss pos: iniciar desde posiciÃ³n
            cmd = [self._ffplay_path, '-nodisp', '-autoexit', '-hide_banner', '-loglevel', 'panic', '-ss', str(start_pos), file_path]
            
            print(f"   ðŸŽ¬ Iniciando reproducciÃ³n con FFplay: {file_path} (desde {start_pos}s)")
            
            # CREATE_NO_WINDOW = 0x08000000 para ocultar consola en Windows
            creationflags = 0x08000000 if os.name == 'nt' else 0
            
            self._ffplay_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
            
            self._music_is_playing = True
            self._currently_playing_file = file_path
            self.music_start_time = time.time() - start_pos
            self.music_is_paused = False
            
            self._update_playback_ui()
            
            # Iniciar timer para actualizar timeline (simulado)
            if hasattr(self, 'music_timer'):
                self.music_timer.start(100)
                
        except Exception as e:
            print(f"âŒ Error iniciando FFplay: {e}")
            self._using_ffplay = False # Deshabilitar si falla
            self._on_download_error(f"Error iniciando FFplay: {e}")
    
    
    def _on_download_progress(self, percentage):
        """Actualiza la barra de progreso de descarga"""
        if hasattr(self, 'music_download_progress'):
            self.music_download_progress.setValue(percentage)
            self.music_download_progress.setVisible(True)
            if percentage >= 100:
                QTimer.singleShot(500, lambda: self.music_download_progress.setVisible(False)
                    if hasattr(self, 'music_download_progress') else None)
    
    def _on_download_error(self, error_msg):
        """Maneja errores de descarga"""
        if hasattr(self, 'music_download_progress'):
            self.music_download_progress.setVisible(False)
        self.music_play_btn.setText("â–¶ï¸ Play")
        self.music_play_btn.setEnabled(True)
        QMessageBox.warning(self, "Error de Descarga", f"No se pudo descargar la pista:\n{error_msg}")
    
    
    def _update_playback_ui(self):
        """Actualiza la UI cuando comienza la reproducciÃ³n"""
        if hasattr(self, 'music_download_progress'):
            self.music_download_progress.setVisible(False)
        
        if hasattr(self, 'music_play_btn'):
            self.music_play_btn.setText("â¸ï¸ Pause")
            self.music_play_btn.setEnabled(True)
            try:
                self.music_play_btn.clicked.disconnect()
            except:
                pass
            self.music_play_btn.clicked.connect(self.pause_music_preview)
        
        if hasattr(self, 'music_duration') and self.music_duration > 0:
            if hasattr(self, 'music_timeline'):
                self.music_timeline.setMaximum(int(self.music_duration * 1000))
            if hasattr(self, 'music_time_total'):
                self.music_time_total.setText(self.format_time(self.music_duration))
            
            if hasattr(self, 'music_timer'):
                try:
                    self.music_timer.timeout.disconnect()
                except:
                    pass
                if hasattr(self, 'update_timeline'):
                    self.music_timer.timeout.connect(self.update_timeline)
                self.music_timer.start(100)
    
    def pause_music_preview(self):
        """Pausa el preview usando VLC, QtMultimedia o FFplay"""
        try:
            if self._using_qt_player and self._qt_player:
                if self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self._qt_player.pause()
                    self.music_is_paused = True
                    self.music_timer.stop()
                    
                    if hasattr(self, 'music_start_time') and self.music_duration > 0:
                        elapsed = time.time() - self.music_start_time
                        self.music_paused_position = min(elapsed, self.music_duration)
                    
                    self._update_play_button_to_resume()
                    return

            if self._using_ffplay and self._ffplay_process:
                # Simular pausa matando el proceso y guardando posiciÃ³n
                try:
                    self._ffplay_process.terminate()
                    self._ffplay_process = None
                except:
                    pass
                
                self.music_is_paused = True
                self.music_timer.stop()
                
                if hasattr(self, 'music_start_time') and self.music_duration > 0:
                    elapsed = time.time() - self.music_start_time
                    self.music_paused_position = min(elapsed, self.music_duration)
                
                self._update_play_button_to_resume()
                return

            if VLC_AVAILABLE and self._vlc_player and self._vlc_player.is_playing():
                self._vlc_player.pause()
                self.music_is_paused = True
                self.music_timer.stop()
                
                if hasattr(self, 'music_start_time') and self.music_duration > 0:
                    elapsed = time.time() - self.music_start_time
                    self.music_paused_position = min(elapsed, self.music_duration)
                
                self._update_play_button_to_resume()
        except Exception as e:
            print(f"âš ï¸ Error en pause_music_preview: {e}")

    def _update_play_button_to_resume(self):
        """Actualiza el botÃ³n de play para mostrar 'Play'"""
        if hasattr(self, 'music_play_btn'):
            self.music_play_btn.setText("â–¶ï¸ Play")
            try:
                self.music_play_btn.clicked.disconnect()
            except:
                pass
            self.music_play_btn.clicked.connect(self.resume_music_preview)
    
    def resume_music_preview(self):
        """Reanuda el preview usando VLC, QtMultimedia o FFplay"""
        try:
            if self._using_qt_player and self._qt_player:
                if self.music_is_paused:
                    self._qt_player.play()
                    self.music_is_paused = False
                    self._update_play_button_to_pause()
                    if hasattr(self, 'music_timer'):
                        self.music_timer.start(100)
                    return

            if self._using_ffplay and self.music_is_paused:
                if hasattr(self, '_currently_playing_file') and hasattr(self, 'music_paused_position'):
                    self._play_with_ffplay(self._currently_playing_file, self.music_paused_position)
                    self._update_play_button_to_pause()
                    return

            if VLC_AVAILABLE and self._vlc_player and self.music_is_paused:
                self._vlc_player.play()
                self.music_is_paused = False
                self._update_play_button_to_pause()
                
                if hasattr(self, 'music_timer'):
                    self.music_timer.start(100)
        except Exception as e:
            print(f"âš ï¸ Error en resume_music_preview: {e}")

    def _update_play_button_to_pause(self):
        """Actualiza el botÃ³n de play para mostrar 'Pause'"""
        if hasattr(self, 'music_play_btn'):
            self.music_play_btn.setText("â¸ï¸ Pause")
            try:
                self.music_play_btn.clicked.disconnect()
            except:
                pass
            self.music_play_btn.clicked.connect(self.pause_music_preview)

    def stop_music_preview(self):
        """Detiene el preview usando VLC, QtMultimedia o FFplay"""
        self._music_is_playing = False
        
        try:
            # Obtener posiciÃ³n actual antes de detener
            current_position_sec = 0.0
            
            if self._using_qt_player and self._qt_player:
                position_ms = self._qt_player.position()
                if position_ms > 0:
                    current_position_sec = position_ms / 1000.0
                self._qt_player.stop()
            elif self._using_ffplay and self._ffplay_process:
                # Estimar posiciÃ³n basada en tiempo transcurrido
                if hasattr(self, 'music_start_time'):
                    elapsed = time.time() - self.music_start_time
                    # Restar pausas si implementamos lÃ³gica de pausas compleja
                    current_position_sec = min(elapsed, self.music_duration)
                
                try:
                    self._ffplay_process.terminate()
                    self._ffplay_process = None
                except:
                    pass
            elif VLC_AVAILABLE and self._vlc_player:
                # Obtener posiciÃ³n actual en milisegundos y convertir a segundos
                position_ms = self._vlc_player.get_time()
                if position_ms > 0:
                    current_position_sec = position_ms / 1000.0
                self._vlc_player.stop()
            
            # Si no hay posiciÃ³n, intentar obtenerla del timeline
            if current_position_sec == 0.0 and hasattr(self, 'music_timeline'):
                current_position_sec = self.music_timeline.value() / 1000.0
            
            self.music_timer.stop()
            self._cleanup_temp_audio_files()
            self.music_is_paused = False
            
            # Mantener la posiciÃ³n actual en lugar de resetear a 0
            # No resetear el timeline, mantener su valor actual
            
            if hasattr(self, 'music_time_current'):
                self.music_time_current.setText(self.format_time(current_position_sec))
            
            if hasattr(self, 'music_play_btn'):
                self.music_play_btn.setText("â–¶ï¸ Play")
                try:
                    self.music_play_btn.clicked.disconnect()
                except:
                    pass
                self.music_play_btn.clicked.connect(self.play_music_preview)
            
            if hasattr(self, '_currently_playing_file'):
                delattr(self, '_currently_playing_file')
            
            if hasattr(self, 'music_paused_position'):
                delattr(self, 'music_paused_position')
            
            # Mantener la posiciÃ³n en el timeline widget
            if hasattr(self, 'music_timeline_widget'):
                duration = self.music_timeline_widget.duration if hasattr(self.music_timeline_widget, 'duration') else 0.0
                if duration > 0:
                    self.music_timeline_widget.set_position(current_position_sec, duration)
            
            # Mantener la posiciÃ³n en la forma de onda (NO resetear a 0)
            if hasattr(self, 'music_waveform') and self.music_waveform:
                if current_position_sec > 0 or hasattr(self.music_waveform, 'current_position'):
                    # Si hay posiciÃ³n actual, mantenerla; si no, mantener la que ya tiene
                    if current_position_sec > 0:
                        self.music_waveform.set_current_position(current_position_sec)
                    # Si current_position_sec es 0 pero la forma de onda tiene una posiciÃ³n, mantenerla
                    elif hasattr(self.music_waveform, 'current_position') and self.music_waveform.current_position > 0:
                        # Ya tiene una posiciÃ³n, no hacer nada
                        pass
            
            if hasattr(self, 'music_play_crop_btn'):
                self.music_play_crop_btn.setEnabled(True)
        except Exception as e:
            print(f"âš ï¸ Error en stop_music_preview: {e}")
    
    def _cleanup_temp_audio_files(self):
        """Limpia archivos temporales de audio"""
        if hasattr(self, '_temp_audio_files'):
            import threading
            
            def delayed_cleanup(file_path):
                time.sleep(2)
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                        print(f"ðŸ—‘ï¸ Archivo temporal eliminado: {file_path}")
                except Exception as e:
                    print(f"âš ï¸ Error eliminando archivo temporal {file_path}: {e}")
            
            for temp_path in self._temp_audio_files[:]:
                threading.Thread(target=delayed_cleanup, args=(temp_path,), daemon=True).start()
                self._temp_audio_files.remove(temp_path)
    
    # ========== MÃ‰TODOS DE TIMELINE ==========
    
    def format_time(self, seconds):
        """Formatea segundos a formato mm:ss"""
        if seconds < 0:
            return "00:00"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"
    
    def update_timeline(self):
        """Actualiza el timeline mientras se reproduce la mÃºsica usando VLC o QtMultimedia"""
        if not hasattr(self, 'music_timeline_being_dragged') or self.music_timeline_being_dragged:
            return
        
        if not self._music_is_playing or self.music_is_paused:
            return
        
        try:
            position_ms = 0
            duration_ms = 0
            is_playing = False
            
            if self._using_qt_player and self._qt_player:
                is_playing = (self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
                if is_playing:
                    position_ms = self._qt_player.position()
                    duration_ms = self._qt_player.duration()
            
            elif self._using_ffplay:
                is_playing = (self._ffplay_process is not None and self._ffplay_process.poll() is None)
                if is_playing:
                    # Estimar posiciÃ³n
                    if hasattr(self, 'music_start_time'):
                        position_ms = (time.time() - self.music_start_time) * 1000
                    duration_ms = self.music_duration * 1000 if hasattr(self, 'music_duration') else 0
                else:
                    # Se detuvo solo (fin de archivo)
                    # Verificar si realmente estaba reproduciendo antes de llamar a stop
                    if self._music_is_playing and not self.music_is_paused:
                         self.stop_music_preview()
                         return

            elif VLC_AVAILABLE and self._vlc_player:
                is_playing = self._vlc_player.is_playing()
                if is_playing:
                    position_ms = self._vlc_player.get_time()
                    duration_ms = self._vlc_player.get_length()
            
            if not is_playing:
                return
            
            if duration_ms > 0:
                if position_ms >= duration_ms:
                    position_ms = duration_ms
                    self.stop_music_preview()
                    return
                
                # Actualizar slider de timeline
                try:
                    if hasattr(self, 'music_timeline'):
                        self.music_timeline.setMaximum(duration_ms)
                        self.music_timeline.setValue(position_ms)
                except Exception as e:
                    print(f"âš ï¸ Error actualizando slider: {e}")
                
                # Actualizar tiempo actual
                try:
                    if hasattr(self, 'music_time_current'):
                        self.music_time_current.setText(self.format_time(position_ms / 1000.0))
                except Exception as e:
                    print(f"âš ï¸ Error actualizando tiempo: {e}")
                
                # Actualizar timeline widget
                try:
                    if hasattr(self, 'music_timeline_widget') and self.music_timeline_widget:
                        self.music_timeline_widget.set_position(
                            position_ms / 1000.0, duration_ms / 1000.0)
                except Exception as e:
                    pass
                
                # Actualizar posiciÃ³n en la forma de onda
                try:
                    if hasattr(self, 'music_waveform') and self.music_waveform and hasattr(
                        self.music_waveform, 'duration') and self.music_waveform.duration > 0:
                        self.music_waveform.set_current_position(position_ms / 1000.0)
                except Exception as e:
                    print(f"âš ï¸ Error actualizando forma de onda: {e}")

        except Exception as e:
            print(f"âš ï¸ Error en update_timeline: {e}")
    
    def on_timeline_pressed(self):
        """Cuando el usuario presiona el slider"""
        self.music_timeline_being_dragged = True
    
    def on_timeline_released(self):
        """Cuando el usuario suelta el slider"""
        try:
            if self.music_timeline_being_dragged:
                position_ms = self.music_timeline.value()
                position_sec = position_ms / 1000.0
                
                if self._using_qt_player and self._qt_player and self.music_duration > 0:
                    was_playing = (self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
                    if was_playing and position_sec < self.music_duration:
                        self._qt_player.setPosition(position_ms)
                        self.music_start_time = time.time() - position_sec

                elif VLC_AVAILABLE and self._vlc_player and self.music_duration > 0:
                    was_playing = self._vlc_player.is_playing()
                    
                    if was_playing and position_sec < self.music_duration:
                        self._vlc_player.set_time(position_ms)
                        self.music_start_time = time.time() - position_sec
                
                if hasattr(self, 'music_time_current'):
                    self.music_time_current.setText(self.format_time(position_sec))
        except Exception as e:
            print(f"âš ï¸ Error en on_timeline_released: {e}")
        finally:
            self.music_timeline_being_dragged = False
    
    def on_timeline_changed(self, value):
        """Cuando el slider cambia de valor (solo si estÃ¡ siendo arrastrado)"""
        if self.music_timeline_being_dragged:
            self.music_time_current.setText(self.format_time(value / 1000.0))
    
    # ========== MÃ‰TODOS DE RECORTE ==========
    
    def on_crop_changed(self):
        """Callback cuando cambian los valores de recorte desde los spinboxes"""
        if hasattr(self, 'music_crop_start') and hasattr(self, 'music_crop_end'):
            start = self.music_crop_start.value()
            end = self.music_crop_end.value()
            
            if start >= end:
                if self.sender() == self.music_crop_start:
                    self.music_crop_end.setValue(start + 0.1)
                else:
                    self.music_crop_start.setValue(max(0.0, end - 0.1))
                return
            
            self.music_crop_start_value = start
            self.music_crop_end_value = end
            
            if hasattr(self, 'music_waveform') and self.music_waveform:
                self.music_waveform.crop_range_changed.disconnect()
                self.music_waveform.set_crop_range(start, end)
                self.music_waveform.crop_range_changed.connect(self.on_waveform_crop_changed)

            self._refresh_crop_summary()
    
    def _refresh_crop_summary(self):
        """Escribe inicio / fin / duracion del recorte en la etiqueta."""
        if not hasattr(self, 'crop_summary_label'):
            return
        try:
            from waveform_geometry import describe_selection
            inicio = self.music_crop_start.value()
            fin = self.music_crop_end.value()
            if fin <= inicio:
                self.crop_summary_label.setText(
                    "Rango invalido: el fin tiene que ser mayor que el inicio")
                self.crop_summary_label.setStyleSheet(
                    "color: #ff6b6b; font-size: 12px; padding: 4px 2px;")
                return
            self.crop_summary_label.setText(describe_selection(inicio, fin))
            self.crop_summary_label.setStyleSheet(
                "color: #ffd633; font-size: 12px; padding: 4px 2px;")
        except Exception:
            pass

    def on_waveform_crop_changed(self, start_time, end_time):
        """Callback cuando se arrastra una lÃ­nea en la forma de onda"""
        if hasattr(self, 'music_crop_start') and hasattr(self, 'music_crop_end'):
            self.music_crop_start.valueChanged.disconnect()
            self.music_crop_end.valueChanged.disconnect()
            
            self.music_crop_start.setValue(start_time)
            self.music_crop_end.setValue(end_time)
            self.music_crop_start_value = start_time
            self.music_crop_end_value = end_time
            
            self.music_crop_start.valueChanged.connect(self.on_crop_changed)
            self.music_crop_end.valueChanged.connect(self.on_crop_changed)

        self._refresh_crop_summary()
    
    def on_waveform_position_clicked(self, position_sec):
        """Callback cuando se hace clic en la forma de onda para cambiar posiciÃ³n de reproducciÃ³n"""
        if not hasattr(self, 'music_duration') or self.music_duration <= 0:
            return
        
        try:
            position_sec = max(0.0, min(position_sec, self.music_duration))
            position_ms = int(position_sec * 1000)
            
            if self._using_qt_player and self._qt_player:
                was_playing = (self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
                if was_playing and position_ms < int(self.music_duration * 1000):
                    self._qt_player.setPosition(position_ms)
                    self.music_start_time = time.time() - position_sec

            elif VLC_AVAILABLE and self._vlc_player:
                was_playing = self._vlc_player.is_playing()
                
                if was_playing and position_ms < int(self.music_duration * 1000):
                    self._vlc_player.set_time(position_ms)
                    self.music_start_time = time.time() - position_sec
            
            if hasattr(self, 'music_timeline'):
                self.music_timeline.blockSignals(True)
                self.music_timeline.setValue(position_ms)
                self.music_timeline.blockSignals(False)
            
            if hasattr(self, 'music_time_current'):
                self.music_time_current.setText(self.format_time(position_sec))
            
            if hasattr(self, 'music_timeline_widget'):
                self.music_timeline_widget.set_position(position_sec, self.music_duration)
            
            if hasattr(self, 'music_waveform') and self.music_waveform:
                self.music_waveform.set_current_position(position_sec)
        except Exception as e:
            print(f"âš ï¸ Error cambiando posiciÃ³n desde forma de onda: {e}")
    
    def reset_crop_range(self):
        """Resetea el rango de recorte a toda la pista"""
        if self.current_music_track:
            duration = self.current_music_track.get('duration', 0)
            if duration > 0:
                self.music_crop_start.setValue(0.0)
                self.music_crop_end.setValue(duration)
                self.music_crop_start_value = 0.0
                self.music_crop_end_value = duration

    def apply_crop_preview(self):
        """Aplica el recorte configurado y actualiza la vista de la forma de onda"""
        if not self.current_music_track:
            return

        crop_start = self.music_crop_start.value()
        crop_end = self.music_crop_end.value()

        if crop_start >= crop_end:
            QMessageBox.warning(self, "Rango invÃ¡lido",
                "El tiempo de inicio debe ser menor que el tiempo de fin")
            return

        # Actualizar valores internos
        self.music_crop_start_value = crop_start
        self.music_crop_end_value = crop_end

        # Actualizar forma de onda
        if hasattr(self, 'music_waveform') and self.music_waveform:
            self.music_waveform.set_crop_range(crop_start, crop_end)

        self.log(f"[INFO] Recorte aplicado: {self.format_time(crop_start)} - {self.format_time(crop_end)}")

    def save_cropped_audio(self):
        """Guarda la secciÃ³n recortada como un archivo MP3 separado"""
        if not self.current_music_track:
            return

        crop_start = self.music_crop_start.value()
        crop_end = self.music_crop_end.value()

        if crop_start >= crop_end:
            QMessageBox.warning(self, "Rango invÃ¡lido",
                "El tiempo de inicio debe ser menor que el tiempo de fin")
            return

        if not hasattr(self, '_current_preview_path') or not os.path.exists(
            getattr(self, '_current_preview_path', '')):
            QMessageBox.information(self, "Info",
                "Primero presiona Play para descargar la pista completa.")
            return

        if not PYDUB_AVAILABLE:
            QMessageBox.warning(self, "Error", "pydub no estÃ¡ disponible. No se puede guardar audio recortado.")
            return

        # Pedir ruta de guardado
        from PyQt6.QtWidgets import QFileDialog
        track_name = self.current_music_track.get('title', 'track').replace(' ', '_').replace('/', '_')
        default_name = f"{track_name}_cropped.mp3"

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar Audio Recortado",
            default_name,
            "MP3 Files (*.mp3)"
        )

        if not save_path:
            return

        try:
            file_path = self._current_preview_path
            crop_start_ms = int(crop_start * 1000)
            crop_end_ms = int(crop_end * 1000)

            # Recortar con pydub
            audio = AudioSegment.from_file(file_path)
            cropped_audio = audio[crop_start_ms:crop_end_ms]
            cropped_audio.export(save_path, format="mp3")

            QMessageBox.information(
                self,
                "Guardado Exitoso",
                f"âœ… Audio recortado guardado en:\n{save_path}\n\n"
                f"DuraciÃ³n: {self.format_time(crop_end - crop_start)}"
            )

            self.log(f"[OK] Audio recortado guardado: {save_path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error guardando audio recortado:\n{e}")
            self.log(f"[ERROR] Error guardando recorte: {e}")
    
    def play_music_crop(self):
        """Reproduce solo la secciÃ³n seleccionada entre las barras de inicio y fin"""
        if not self.current_music_track:
            return
        
        crop_start = self.music_crop_start.value()
        crop_end = self.music_crop_end.value()
        
        if crop_start >= crop_end:
            QMessageBox.warning(self, "Rango invÃ¡lido",
                "El tiempo de inicio debe ser menor que el tiempo de fin")
            return
        
        if not hasattr(self, '_current_preview_path') or not os.path.exists(
            getattr(self, '_current_preview_path', '')):
            QMessageBox.information(self, "Info",
                "Primero presiona Play para descargar la pista, luego podrÃ¡s reproducir el recorte.")
            return
        
        if not PYDUB_AVAILABLE:
            QMessageBox.warning(self, "Error", "pydub no estÃ¡ disponible. No se puede recortar audio.")
            return
        
        file_path = self._current_preview_path
        crop_start_ms = int(crop_start * 1000)
        crop_end_ms = int(crop_end * 1000)
        
        track_id = self.current_music_track.get('title', 'track').replace(' ', '_').replace('/', '_')
        crop_hash = hashlib.md5(f"{crop_start_ms}_{crop_end_ms}".encode()).hexdigest()[:8]
        cached_crop_path = os.path.join(tempfile.gettempdir(), f"jamendo_crop_{track_id}_{crop_hash}.mp3")
        
        if os.path.exists(cached_crop_path):
            self._play_cropped_audio(cached_crop_path, crop_start, crop_end)
            return
        
        if hasattr(self, 'music_play_crop_btn'):
            self.music_play_crop_btn.setText("â³ Procesando...")
            self.music_play_crop_btn.setEnabled(False)
        
        class CropWorker(QThread):
            crop_ready = pyqtSignal(str, float, float)
            error_occurred = pyqtSignal(str)
            
            def __init__(self, file_path, crop_start_ms, crop_end_ms, output_path):
                super().__init__()
                self.file_path = file_path
                self.crop_start_ms = crop_start_ms
                self.crop_end_ms = crop_end_ms
                self.output_path = output_path
            
            def run(self):
                try:
                    audio = AudioSegment.from_mp3(self.file_path)
                    cropped_audio = audio[self.crop_start_ms:self.crop_end_ms]
                    cropped_audio.export(self.output_path, format="mp3")
                    self.crop_ready.emit(self.output_path, self.crop_start_ms / 1000.0, self.crop_end_ms / 1000.0)
                except Exception as e:
                    self.error_occurred.emit(str(e))
        
        self.crop_worker = CropWorker(file_path, crop_start_ms, crop_end_ms, cached_crop_path)
        self.crop_worker.crop_ready.connect(lambda path, start, end: self._play_cropped_audio(path, start, end))
        self.crop_worker.error_occurred.connect(lambda e: (
            QMessageBox.critical(self, "Error", f"Error recortando audio:\n{e}"),
            setattr(self, 'music_play_crop_btn', None) if hasattr(self, 'music_play_crop_btn') else None,
            print(f"âŒ Error en crop worker: {e}")
        ))
        self.crop_worker.start()
    
    def _play_cropped_audio(self, cropped_path, crop_start, crop_end):
        """Reproduce el audio recortado usando VLC, QtMultimedia o FFplay"""
        try:
            if not VLC_AVAILABLE and not self._using_qt_player and not self._using_ffplay:
                QMessageBox.warning(self, "Error", "No hay reproductor disponible para reproducir audio recortado")
                return
            
            # === RUTA FFPLAY ===
            if self._using_ffplay and self._ffplay_path:
                if self._ffplay_process:
                    try:
                        self._ffplay_process.terminate()
                        self._ffplay_process = None
                    except:
                        pass
                
                self._play_with_ffplay(cropped_path)
                
                # Ajustar duraciÃ³n y tiempos
                self.music_duration = crop_end - crop_start
                # self.music_start_time se setea en _play_with_ffplay, pero asume start_pos=0 del archivo fÃ­sico
                
                print(f"â–¶ï¸ Reproduciendo recorte desde {crop_start:.1f}s hasta {crop_end:.1f}s (FFplay)")
                self._setup_crop_playback_ui(crop_end) # UI Consistency
                return

            # === RUTA QT MULTIMEDIA ===
            if self._using_qt_player and self._qt_player:
                # Detener reproducciÃ³n anterior
                self._qt_player.stop()
                
                # Cargar archivo recortado
                abs_path = os.path.abspath(cropped_path)
                url = QUrl.fromLocalFile(abs_path)
                self._qt_player.setSource(url)
                self._qt_player.play()
                
                # Configurar estado
                self.music_duration = crop_end - crop_start
                self.music_start_time = time.time()
                self.music_is_paused = False
                self._currently_playing_file = cropped_path
                self._music_is_playing = True
                self._update_playback_ui()
                if hasattr(self, 'music_timer'):
                    self.music_timer.start(100)
                
                print(f"â–¶ï¸ Reproduciendo recorte desde {crop_start:.1f}s hasta {crop_end:.1f}s (Qt)")
                self._setup_crop_playback_ui(crop_end)
                return

            # === RUTA VLC ===
            if self._vlc_player:
                # Detener reproducciÃ³n anterior
                self._vlc_player.stop()
                
                # Cargar archivo recortado
                abs_path = os.path.abspath(cropped_path)
                media = self._vlc_instance.media_new(abs_path)
                self._vlc_player.set_media(media)
                self._vlc_player.audio_set_volume(100)
                
                # Reproducir
                result = self._vlc_player.play()
                
                if result == 0:
                    time.sleep(0.3)
                    if self._vlc_player.is_playing():
                        self.music_duration = crop_end - crop_start
                        self.music_start_time = time.time()
                        self.music_is_paused = False
                        self._currently_playing_file = cropped_path
                        self._music_is_playing = True
                        self._update_playback_ui()
                        if hasattr(self, 'music_timer'):
                            self.music_timer.start(100)
                    else:
                        QMessageBox.warning(self, "Error", "No se pudo reproducir el audio recortado")
                else:
                    QMessageBox.warning(self, "Error", f"Error al reproducir audio recortado (cÃ³digo: {result})")
                
                print(f"â–¶ï¸ Reproduciendo recorte desde {crop_start:.1f}s hasta {crop_end:.1f}s (VLC)")
                self._setup_crop_playback_ui(crop_end)

        except Exception as e:
            print(f"âŒ Error reproduciendo recorte: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"No se pudo reproducir el recorte:\n{str(e)}")
            if hasattr(self, 'music_play_crop_btn'):
                self.music_play_crop_btn.setText("â–¶ï¸ Play Recorte")
                self.music_play_crop_btn.setEnabled(True)

    def toggle_crop_playback(self):
        """Pausa o reanuda la reproduccion del recorte."""
        try:
            if getattr(self, '_crop_is_playing', False):
                self.pause_music_preview()
                self._crop_is_playing = False
                if hasattr(self, 'music_play_crop_btn'):
                    self.music_play_crop_btn.setText("▶ Reanudar recorte")
            else:
                self.resume_music_preview()
                self._crop_is_playing = True
                if hasattr(self, 'music_play_crop_btn'):
                    self.music_play_crop_btn.setText("⏸ Pausar recorte")
        except Exception as exc:
            self.log(f"No se pudo alternar la reproduccion del recorte: {exc}")

    def _reset_crop_playback_button(self):
        """Devuelve el boton a 'Play Recorte' cuando el recorte termina."""
        self._crop_is_playing = False
        if not hasattr(self, 'music_play_crop_btn'):
            return
        self.music_play_crop_btn.setText("▶ Play Recorte")
        self.music_play_crop_btn.setEnabled(True)
        try:
            self.music_play_crop_btn.clicked.disconnect()
        except Exception:
            pass
        self.music_play_crop_btn.clicked.connect(self.play_music_crop)

    def _setup_crop_playback_ui(self, crop_end):
        """Configura la UI para reproducciÃ³n de recorte"""
        if hasattr(self, 'music_play_btn'):
            self.music_play_btn.setText("â¸ï¸ Pause")
            self.music_play_btn.setEnabled(True)
            try:
                self.music_play_btn.clicked.disconnect()
            except:
                pass
            self.music_play_btn.clicked.connect(self.pause_music_preview)
        
        if hasattr(self, 'music_play_crop_btn'):
            # Mientras suena el recorte, este boton pasa a ser Pausa/Reanudar
            # en vez de quedar deshabilitado: antes, para pausar habia que ir
            # al boton Play de al lado, que es poco intuitivo.
            self.music_play_crop_btn.setText("⏸ Pausar recorte")
            self.music_play_crop_btn.setEnabled(True)
            try:
                self.music_play_crop_btn.clicked.disconnect()
            except Exception:
                pass
            self.music_play_crop_btn.clicked.connect(self.toggle_crop_playback)
            self._crop_is_playing = True

        self.music_crop_end_time = crop_end
        try:
            self.music_timer.timeout.disconnect()
        except:
            pass
        
        def update_and_check_crop_end():
            self.update_timeline()
            if hasattr(self, 'music_crop_end_time'):
                current_pos = (time.time() - self.music_start_time) if hasattr(self, 'music_start_time') else 0
                if current_pos >= self.music_crop_end_time:
                    self.stop_music_preview()
                    self._reset_crop_playback_button()
        
        self.music_timer.timeout.connect(update_and_check_crop_end)
        self.music_timer.start(100)
    
    # ========== MÃ‰TODOS DE FORMA DE ONDA ==========
    
    def load_waveform_for_track(self, track):
        """Carga y genera la forma de onda para una pista (en background)"""
        if not PYDUB_AVAILABLE:
            return
        
        if hasattr(self, 'music_waveform') and self.music_waveform:
            self.music_waveform.set_waveform_data([], 0)
        
        # Verificar si la pista tiene URL de audio (solo Jamendo tiene descarga)
        audio_url = track.get('audio_url')
        if not audio_url:
            print("️ Sin URL de audio - Last.fm no proporciona descarga directa")
            if hasattr(self, 'music_waveform') and self.music_waveform:
                # Generar forma de onda vacía para Last.fm
                self.music_waveform.set_waveform_data([], 180)  # Duración estimada
            return
        
        class WaveformWorker(QThread):
            waveform_ready = pyqtSignal(list, float)
            error_occurred = pyqtSignal(str)
            progress_updated = pyqtSignal(int)  # Señal para actualizar progreso
            
            def __init__(self, track, cached_path=None):
                super().__init__()
                self.track = track
                self.cached_path = cached_path
                self.audio_url = track.get('audio_url')
            
            def run(self):
                try:
                    import requests
                    
                    temp_path = self.cached_path
                    should_delete = False
                    
                    if not temp_path or not os.path.exists(temp_path):
                        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                        temp_path = temp_file.name
                        temp_file.close()
                        should_delete = True
                        
                        try:
                            response = requests.get(self.audio_url, timeout=15, stream=True)
                            if response.status_code != 200:
                                self.error_occurred.emit(f"Error HTTP: {response.status_code}")
                                return
                            
                            with open(temp_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    f.write(chunk)
                        except Exception as e:
                            if should_delete and os.path.exists(temp_path):
                                try:
                                    os.unlink(temp_path)
                                except:
                                    pass
                            self.error_occurred.emit(f"Error descargando: {e}")
                            return
                    
                    try:
                        # Emitir progreso inicial
                        self.progress_updated.emit(10)
                        
                        audio = AudioSegment.from_file(temp_path)
                        duration = len(audio) / 1000.0
                        
                        # Emitir progreso despuÃ©s de cargar audio
                        self.progress_updated.emit(30)
                        
                        sample_rate = 2
                        waveform_data = []
                        chunk_size_ms = int(1000 / sample_rate)
                        total_chunks = len(audio) // chunk_size_ms
                        
                        for i, chunk_start in enumerate(range(0, len(audio), chunk_size_ms)):
                            chunk = audio[chunk_start:chunk_start + chunk_size_ms]
                            rms = chunk.rms
                            normalized = min(1.0, rms / 32768.0)
                            waveform_data.append(normalized)
                            
                            # Emitir progreso cada 10% o cada 100 chunks
                            if total_chunks > 0:
                                progress = 30 + int((i / total_chunks) * 60)  # 30-90%
                                if i % max(1, total_chunks // 10) == 0 or i % 100 == 0:
                                    self.progress_updated.emit(progress)
                        
                        # Asegurar que se emita 100% al finalizar
                        self.progress_updated.emit(100)
                        self.waveform_ready.emit(waveform_data, duration)
                    finally:
                        if should_delete and os.path.exists(temp_path):
                            try:
                                os.unlink(temp_path)
                            except:
                                pass
                except Exception as e:
                    self.error_occurred.emit(f"Error procesando: {e}")
        
        cached_path = None
        if hasattr(self, '_current_preview_path') and self._current_preview_path:
            track_id = track.get('title', 'track').replace(' ', '_').replace('/', '_')
            expected_path = os.path.join(tempfile.gettempdir(), f"jamendo_preview_{track_id}.mp3")
            if os.path.exists(expected_path):
                cached_path = expected_path
        
        self.waveform_worker = WaveformWorker(track, cached_path)
        self.waveform_worker.waveform_ready.connect(self.on_waveform_ready)
        self.waveform_worker.progress_updated.connect(self.on_waveform_progress)
        self.waveform_worker.error_occurred.connect(self.on_waveform_error)
        self.waveform_worker.start()
        
        # Mostrar barra de progreso
        if hasattr(self, 'waveform_progress'):
            self.waveform_progress.setVisible(True)
            self.waveform_progress.setValue(0)
    
    def on_waveform_progress(self, percentage):
        """Actualiza la barra de progreso de carga de forma de onda"""
        if hasattr(self, 'waveform_progress'):
            self.waveform_progress.setValue(percentage)
    
    def on_waveform_error(self, error_msg):
        """Maneja errores al cargar la forma de onda"""
        print(f"âš ï¸ Error forma de onda: {error_msg}")
        if hasattr(self, 'waveform_progress'):
            self.waveform_progress.setVisible(False)
    
    def on_waveform_ready(self, waveform_data, duration):
        """Callback cuando la forma de onda estÃ¡ lista"""
        # Ocultar barra de progreso
        if hasattr(self, 'waveform_progress'):
            self.waveform_progress.setVisible(False)
        
        if hasattr(self, 'music_waveform') and self.music_waveform:
            self.music_waveform.set_waveform_data(waveform_data, duration)
            self.music_waveform.set_crop_range(self.music_crop_start_value, self.music_crop_end_value)
            print("âœ… Forma de onda cargada correctamente")
    
    def select_local_music_file(self):
        """Selecciona uno o varios archivos de música local.

        Si se elige un solo archivo, lo muestra en la lista para previsualizar
        antes de confirmar. Si se eligen varios, cierra el diálogo inmediatamente
        devolviendo todos en ``selected_music_paths``.
        """
        try:
            file_dialog = QFileDialog(self)
            file_dialog.setWindowTitle("Seleccionar archivos de música")
            file_dialog.setNameFilter("Archivos de audio (*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma)")
            file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)

            if file_dialog.exec():
                selected_files = [p for p in file_dialog.selectedFiles() if os.path.exists(p)]
                if not selected_files:
                    return

                if len(selected_files) == 1:
                    # Flujo original: mostrar en lista para que el usuario pueda previsualizar
                    self.handle_local_music_file(selected_files[0])
                    return

                # Múltiples archivos: devolver todos inmediatamente sin pasar por la lista
                self.selected_music_paths = selected_files
                self.selected_music_path = selected_files[0]
                first_name = os.path.splitext(os.path.basename(selected_files[0]))[0]
                self.selected_music_metadata = {
                    'title': first_name,
                    'artist': 'Archivo Local',
                    'source': 'local',
                    'local_path': selected_files[0],
                    'license_code': 'LOCAL',
                    'attribution_required': False,
                }
                names = [os.path.basename(p) for p in selected_files]
                self.log(f"[OK] {len(selected_files)} archivos locales seleccionados: {', '.join(names)}")
                self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error seleccionando archivo:\n{e}")
    
    def handle_local_music_file(self, file_path):
        """Maneja el archivo de música local seleccionado"""
        try:
            if not os.path.exists(file_path):
                QMessageBox.warning(self, "Error", "El archivo seleccionado no existe")
                return
            
            # Obtener información básica del archivo
            file_name = os.path.basename(file_path)
            file_name_no_ext = os.path.splitext(file_name)[0]
            
            # Intentar obtener duración con pydub
            duration = 0
            if PYDUB_AVAILABLE:
                try:
                    audio = AudioSegment.from_file(file_path)
                    duration = len(audio) / 1000.0
                except Exception as e:
                    print(f"âš ï¸ No se pudo obtener duración: {e}")
            
            # Crear objeto de track local
            local_track = {
                'title': file_name_no_ext,
                'artist': 'Archivo Local',
                'duration': duration,
                'audio_url': None,  # No hay URL para archivos locales
                'source': 'local',
                'local_path': file_path,
                'file_size': os.path.getsize(file_path),
                'license_code': 'LOCAL',
                'youtube_safe': False,
                'attribution_required': False,
            }
            
            # Limpiar lista actual y agregar el archivo local
            self.music_results_list.clear()
            
            duration_str = f"{int(duration//60)}:{int(duration%60):02d}" if duration > 0 else "--:--"
            item_text = f"[LOCAL] {file_name_no_ext} - Archivo Local ({duration_str})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, local_track)
            self.music_results_list.addItem(item)
            
            self.log(f"[OK] Archivo local cargado: {file_name}")
            
            # Seleccionar automáticamente el item
            self.music_results_list.setCurrentItem(item)
            self.on_music_item_selected()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error procesando archivo:\n{e}")
            import traceback
            traceback.print_exc()
    
    # ========== MÃ‰TODOS DE SELECCIÃ“N ==========
    
    def select_music(self):
        """Selecciona la música y la descarga (con recorte si está configurado)"""
        if not self.current_music_track:
            return
        
        try:
            self.stop_music_preview()
            
            # Verificar si es un archivo local
            if self.current_music_track.get('source') == 'local':
                # Para archivos locales, solo copiar el archivo
                local_path = self.current_music_track.get('local_path')
                if not local_path or not os.path.exists(local_path):
                    QMessageBox.warning(self, "Error", "El archivo local no existe o no es accesible")
                    return
                
                temp_dir = tempfile.gettempdir()
                file_name = os.path.basename(local_path)
                temp_path = os.path.join(temp_dir, f"local_{file_name}")
                
                # Copiar archivo local
                import shutil
                shutil.copy2(local_path, temp_path)
                
                final_path = temp_path
                
                # Aplicar recorte si está configurado y pydub está disponible
                if PYDUB_AVAILABLE and (self.music_crop_start_value > 0 or 
                                       self.music_crop_end_value < self.current_music_track.get('duration', 0)):
                    try:
                        audio = AudioSegment.from_file(temp_path)
                        start_ms = int(self.music_crop_start_value * 1000)
                        end_ms = int(self.music_crop_end_value * 1000)
                        cropped_audio = audio[start_ms:end_ms]
                        
                        cropped_path = os.path.join(temp_dir, f"local_cropped_{file_name}")
                        cropped_audio.export(cropped_path, format="mp3")
                        final_path = cropped_path
                        
                        # Limpiar archivo original copiado
                        try:
                            os.unlink(temp_path)
                        except:
                            pass
                    except Exception as e:
                        print(f"️ Error aplicando recorte: {e}")
                
                self.selected_music_path = final_path
                self.selected_music_paths = [final_path]
                self.selected_music_metadata = {
                    'title': self.current_music_track.get('title', ''),
                    'artist': self.current_music_track.get('artist', ''),
                    'audio_url': self.current_music_track.get('audio_url', ''),
                    'duration': self.current_music_track.get('duration', 0),
                    'source': self.current_music_track.get('source', ''),
                    'local_path': self.current_music_track.get('local_path', ''),
                    'license_url': self.current_music_track.get('license_url', ''),
                    'license_code': self.current_music_track.get('license_code', 'LOCAL'),
                    'attribution_required': self.current_music_track.get('attribution_required', False),
                    'attribution_text_en': self.youtube_attribution_text.toPlainText().strip(),
                }

                self.log(f"[OK] Archivo local seleccionado: {final_path}")
                self.accept()
                return
            
            # Para archivos de Jamendo, continuar con la lógica original
            from music_recommender import download_track
            
            temp_dir = tempfile.gettempdir()
            track_name = self.current_music_track['title'].replace(' ', '_').replace('/', '_')
            save_path = os.path.join(temp_dir, f"{track_name}.mp3")
            
            audio_url = self.current_music_track.get('audio_url')
            if not audio_url:
                QMessageBox.warning(self, "Error", "La pista no tiene URL de audio")
                return
            
            downloaded_path = download_track(audio_url, save_path)
            
            if downloaded_path and os.path.exists(downloaded_path):
                final_path = downloaded_path
                if PYDUB_AVAILABLE and (self.music_crop_start_value > 0 or 
                                       self.music_crop_end_value < self.current_music_track.get('duration', 0)):
                    try:
                        audio = AudioSegment.from_file(downloaded_path)
                        start_ms = int(self.music_crop_start_value * 1000)
                        end_ms = int(self.music_crop_end_value * 1000)
                        cropped_audio = audio[start_ms:end_ms]
                        
                        cropped_path = os.path.join(temp_dir, f"{track_name}_cropped.mp3")
                        cropped_audio.export(cropped_path, format="mp3")
                        final_path = cropped_path
                        
                        if final_path != downloaded_path:
                            try:
                                os.unlink(downloaded_path)
                            except:
                                pass
                    except Exception as e:
                        print(f"️ Error aplicando recorte: {e}")
                
                self.selected_music_path = final_path
                self.selected_music_paths = [final_path]
                if hasattr(self, 'current_music_track') and self.current_music_track:
                    self.selected_music_metadata = {
                        'title': self.current_music_track.get('title', ''),
                        'artist': self.current_music_track.get('artist', ''),
                        'audio_url': self.current_music_track.get('audio_url', ''),
                        'duration': self.current_music_track.get('duration', 0),
                        'source': self.current_music_track.get('source', 'jamendo'),
                        'license_url': self.current_music_track.get('license_url', ''),
                        'license_code': self.current_music_track.get('license_code', ''),
                        'attribution_required': self.current_music_track.get('attribution_required', False),
                        'attribution_text_en': self.current_music_track.get(
                            'youtube_attribution_text',
                            self._build_youtube_attribution_text(self.current_music_track),
                        ),
                    }

                self.log(f"[OK] Musica seleccionada: {self.selected_music_path}")
                self.accept()
            else:
                QMessageBox.warning(self, "Error", "No se pudo descargar la música")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error seleccionando música:\n{e}")
    


class WaveformWorker(QThread):
    waveform_ready = pyqtSignal(list, float)
    error_occurred = pyqtSignal(str)
    progress_updated = pyqtSignal(int)  # Señal para actualizar progreso

    def __init__(self, track, cached_path=None):
        super().__init__()
        self.track = track
        self.cached_path = cached_path
        self.audio_url = track.get('audio_url')

    def run(self):
        try:
            import requests

            temp_path = self.cached_path
            should_delete = False

            if not temp_path or not os.path.exists(temp_path):
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                temp_path = temp_file.name
                temp_file.close()
                should_delete = True

            try:
                response = requests.get(self.audio_url, timeout=15, stream=True)
                if response.status_code != 200:
                    self.error_occurred.emit(f"Error HTTP: {response.status_code}")
                    return

                with open(temp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
            except Exception as e:
                if should_delete and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                self.error_occurred.emit(f"Error descargando: {e}")
                return

            try:
                # Emitir progreso inicial
                self.progress_updated.emit(10)

                audio = AudioSegment.from_file(temp_path)
                duration = len(audio) / 1000.0

                # Emitir progreso después de cargar audio
                self.progress_updated.emit(30)

                sample_rate = 2
                waveform_data = []
                chunk_size_ms = int(1000 / sample_rate)
                total_chunks = len(audio) // chunk_size_ms

                for i, chunk_start in enumerate(range(0, len(audio), chunk_size_ms)):
                    chunk = audio[chunk_start:chunk_start + chunk_size_ms]
                    rms = chunk.rms
                    normalized = min(1.0, rms / 32768.0)
                    waveform_data.append(normalized)

                    # Emitir progreso cada 10% o cada 100 chunks
                    if total_chunks > 0:
                        progress = 30 + int((i / total_chunks) * 60)  # 30-90%
                        if i % max(1, total_chunks // 10) == 0 or i % 100 == 0:
                            self.progress_updated.emit(progress)

                # Asegurar que se emita 100% al finalizar
                self.progress_updated.emit(100)
                self.waveform_ready.emit(waveform_data, duration)
            finally:
                if should_delete and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
        except Exception as e:
            self.error_occurred.emit(f"Error procesando: {e}")
