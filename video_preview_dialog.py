# video_preview_dialog.py
"""
Diálogo VideoPreviewDialog.
Extraído de timeline_editor_widget.py para mejorar la organización del código.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QMessageBox, QScrollArea, QWidget, QCheckBox, QSlider
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QTimer
from PyQt6.QtGui import QPixmap, QIcon
from pathlib import Path
import os
import requests
import warnings

MEDIA_PLAYER_AVAILABLE = False
QMediaPlayer = None
QVideoWidget = None
QAudioOutput = None
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    if QMediaPlayer and QVideoWidget and QAudioOutput:
        MEDIA_PLAYER_AVAILABLE = True
except Exception:
    MEDIA_PLAYER_AVAILABLE = False

class VideoPreviewDialog(QDialog):
    """Diálogo para previsualizar videos antes de seleccionarlos"""
    
    def __init__(self, parent=None, video_data=None):
        super().__init__(parent)
        
        # PRIMERO: Obtener datos del video
        self.video_data = video_data or {}
        self.video_url = video_data.get('url', '') if video_data else ''
        
        # SEGUNDO: Verificar si es URL remota ANTES de CUALQUIER otra cosa
        # Esto es crítico para evitar crashes con QMediaPlayer
        self.is_remote_url = (
            self.video_url.startswith('http://') or 
            self.video_url.startswith('https://')
        ) if self.video_url else False
        
        # Inicializar variables de media player como None por defecto
        self.media_player = None
        self.audio_output = None
        self.video_widget = None
        
        self.setWindowTitle("️ Preview de Video")
        self.setMinimumSize(800, 600)
        
        # Setup UI (que ahora verifica is_remote_url antes de crear QMediaPlayer)
        self.setup_ui()
        
        # NO llamar load_video() para URLs remotas - ya se mostró mensaje en setup_ui
        if self.video_url and not self.is_remote_url and self.media_player is not None:
            # Solo intentar cargar si es archivo local Y media_player está disponible
            try:
                self.load_video()
            except Exception as e:
                print(f"️ Error cargando video local: {e}")
    
    def setup_ui(self):
        """Configura la interfaz del diálogo"""
        layout = QVBoxLayout(self)
        
        # Información del video
        info_label = QLabel()
        title = self.video_data.get('title', 'Video sin título')
        source = self.video_data.get('source', 'unknown')
        info_text = f" {title}\n"
        info_text += f"Fuente: {source}"
        if self.video_data.get('duration'):
            info_text += f" | Duración: {self.video_data.get('duration', 0):.1f}s"
        info_label.setText(info_text)
        info_label.setObjectName("subtitle")
        layout.addWidget(info_label)
        
        # Widget de video
        # NO inicializar QMediaPlayer si es URL remota (causa crashes)
        if MEDIA_PLAYER_AVAILABLE and not self.is_remote_url:
            try:
                self.video_widget = QVideoWidget()
                self.video_widget.setMinimumSize(640, 360)
                layout.addWidget(self.video_widget)
                
                # Inicializar QMediaPlayer con manejo de errores robusto
                try:
                    self.media_player = QMediaPlayer()
                    self.audio_output = QAudioOutput()
                    self.media_player.setAudioOutput(self.audio_output)
                    self.media_player.setVideoOutput(self.video_widget)
                except Exception as e:
                    print(f"️ Error inicializando QMediaPlayer: {e}")
                    # Fallback: mostrar mensaje
                    self.media_player = None
                    self.audio_output = None
                    fallback_label = QLabel(
                        f"️ Error inicializando reproductor de video:\n{str(e)}\n\n"
                        "Puedes usar 'Abrir en Navegador' para ver el video."
                    )
                    fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    fallback_label.setObjectName("errorText")
                    layout.addWidget(fallback_label)
                    self.video_widget = None
            except Exception as e:
                print(f"️ Error creando video widget: {e}")
                self.video_widget = None
                self.media_player = None
                self.audio_output = None
                fallback_label = QLabel(
                    f"️ Error inicializando componentes de video:\n{str(e)}\n\n"
                    "Puedes usar 'Abrir en Navegador' para ver el video."
                )
                fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                fallback_label.setObjectName("errorText")
                layout.addWidget(fallback_label)
        else:
            # Para URLs remotas o si MEDIA_PLAYER no está disponible, mostrar mensaje
            self.video_widget = None
            self.media_player = None
            self.audio_output = None
            
            if self.is_remote_url:
                info_label = QLabel(
                    "ℹ️ Preview de video remoto no disponible por seguridad.\n\n"
                    "Los videos de Internet Archive/Wikimedia no se pueden reproducir directamente\n"
                    "en el preview para evitar problemas de estabilidad.\n\n"
                    "Usa el botón ' Abrir en Navegador' para ver el video,\n"
                    "o ' Seleccionar Video' para descargarlo y usarlo en tu proyecto."
                )
            else:
                info_label = QLabel(
                    "️ QMediaPlayer no está disponible.\n"
                    "Para previsualizar videos, instala PyQt6 con soporte multimedia:\n"
                    "pip install PyQt6[multimedia]"
                )
            
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info_label.setObjectName("subtitle")
            info_label.setWordWrap(True)
            layout.addWidget(info_label)
        
        # Controles de reproducción (solo si NO es URL remota y media_player está disponible)
        if not self.is_remote_url and MEDIA_PLAYER_AVAILABLE and self.media_player is not None:
            controls_layout = QHBoxLayout()
            
            self.play_btn = QPushButton("️ Reproducir")
            self.play_btn.clicked.connect(self.toggle_playback)
            controls_layout.addWidget(self.play_btn)
            
            self.stop_btn = QPushButton("️ Detener")
            self.stop_btn.clicked.connect(self.stop_playback)
            controls_layout.addWidget(self.stop_btn)
            
            controls_layout.addStretch()
            
            # Botón para abrir en navegador como alternativa
            open_browser_btn = QPushButton(" Abrir en Navegador")
            open_browser_btn.clicked.connect(self.open_in_browser)
            controls_layout.addWidget(open_browser_btn)
            
            layout.addLayout(controls_layout)
        else:
            # Para URLs remotas, solo mostrar botón de abrir en navegador
            controls_layout = QHBoxLayout()
            controls_layout.addStretch()
            
            open_browser_btn = QPushButton(" Abrir en Navegador")
            open_browser_btn.clicked.connect(self.open_in_browser)
            controls_layout.addWidget(open_browser_btn)
            
            layout.addLayout(controls_layout)
        
        # Botones de acción
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(close_btn)
        
        layout.addLayout(buttons_layout)
    
    def load_video(self):
        """Carga el video en el reproductor"""
        # Si es URL remota, NO hacer nada (ya se mostró mensaje en setup_ui)
        if self.is_remote_url:
            return
        
        if not MEDIA_PLAYER_AVAILABLE or not hasattr(self, 'media_player') or self.media_player is None:
            return
        
        if not self.video_url:
            return
        
        # Solo intentar cargar si es un archivo local
        try:
            # Limpiar cualquier fuente anterior antes de cargar nueva
            try:
                self.media_player.stop()
            except:
                pass
            
            # Desconectar señales anteriores si existen
            try:
                self.media_player.playbackStateChanged.disconnect()
            except:
                pass
            try:
                if hasattr(self.media_player, 'errorOccurred'):
                    self.media_player.errorOccurred.disconnect()
            except:
                pass
            
            # Para archivos locales, intentar cargar
            video_url = QUrl.fromLocalFile(self.video_url) if os.path.exists(self.video_url) else QUrl(self.video_url)
            
            # Verificar si es una URL válida
            if not video_url.isValid():
                QMessageBox.warning(
                    self,
                    "URL Inválida",
                    f"La URL del video no es válida:\n{self.video_url}\n\n"
                    "Puedes usar 'Abrir en Navegador' para verlo."
                )
                return
            
            # Cargar fuente con manejo de errores robusto
            try:
                self.media_player.setSource(video_url)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Error",
                    f"No se pudo cargar el video:\n{str(e)}\n\n"
                    "Puedes usar 'Abrir en Navegador' para verlo."
                )
                return
            
            # Conectar señales después de cargar
            try:
                self.media_player.playbackStateChanged.connect(self.on_playback_state_changed)
            except Exception as e:
                print(f"️ Error conectando señal playbackStateChanged: {e}")
            
            # Conectar señal de error si está disponible
            try:
                if hasattr(self.media_player, 'errorOccurred'):
                    self.media_player.errorOccurred.connect(self.on_media_error)
            except Exception as e:
                print(f"️ Error conectando señal errorOccurred: {e}")
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(
                self,
                "Error",
                f"No se pudo cargar el video para preview:\n{str(e)}\n\n"
                "Algunos videos remotos no se pueden reproducir directamente.\n"
                "Puedes usar 'Abrir en Navegador' para verlo."
            )
    
    def on_media_error(self, error, error_string=""):
        """Maneja errores del reproductor de medios"""
        error_msg = error_string if error_string else "Error desconocido"
        QMessageBox.warning(
            self,
            "Error de Reproducción",
            f"No se pudo reproducir el video:\n{error_msg}\n\n"
            "Puedes usar 'Abrir en Navegador' para verlo."
        )
    
    def toggle_playback(self):
        """Alterna entre reproducir y pausar"""
        if not MEDIA_PLAYER_AVAILABLE or not hasattr(self, 'media_player') or self.media_player is None:
            return
        
        try:
            # Verificar que el media player sigue siendo válido
            current_state = self.media_player.playbackState()
            if current_state == QMediaPlayer.PlaybackState.PlayingState:
                self.media_player.pause()
            else:
                self.media_player.play()
        except (AttributeError, RuntimeError, SystemError) as e:
            print(f"️ Error en toggle_playback: {e}")
            # Si hay un error crítico, limpiar referencia
            try:
                self.media_player = None
            except:
                pass
        except Exception as e:
            print(f"️ Error inesperado en toggle_playback: {e}")
    
    def stop_playback(self):
        """Detiene la reproducción"""
        if MEDIA_PLAYER_AVAILABLE and hasattr(self, 'media_player') and self.media_player is not None:
            try:
                self.media_player.stop()
            except (AttributeError, RuntimeError, SystemError) as e:
                print(f"️ Error deteniendo reproducción: {e}")
                # Si hay un error crítico, limpiar referencia
                try:
                    self.media_player = None
                except:
                    pass
            except Exception as e:
                print(f"️ Error inesperado deteniendo: {e}")
    
    def on_playback_state_changed(self, state):
        """Actualiza el botón de play/pause según el estado"""
        if not hasattr(self, 'play_btn') or not MEDIA_PLAYER_AVAILABLE:
            return
        
        try:
            # Verificar que el botón y el media player siguen siendo válidos
            if not hasattr(self, 'play_btn') or self.play_btn is None:
                return
            
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self.play_btn.setText("️ Pausar")
            else:
                self.play_btn.setText("️ Reproducir")
        except (AttributeError, RuntimeError) as e:
            print(f"️ Error actualizando estado de reproducción: {e}")
        except Exception as e:
            print(f"️ Error inesperado en on_playback_state_changed: {e}")
    
    def open_in_browser(self):
        """Abre el video en el navegador web"""
        if self.video_url:
            import webbrowser
            webbrowser.open(self.video_url)
        else:
            QMessageBox.warning(self, "Error", "No hay URL de video disponible.")
    
    def closeEvent(self, event):
        """Limpia recursos al cerrar"""
        if MEDIA_PLAYER_AVAILABLE and hasattr(self, 'media_player') and self.media_player is not None:
            try:
                # Desconectar todas las señales primero
                try:
                    self.media_player.playbackStateChanged.disconnect()
                except:
                    pass
                try:
                    if hasattr(self.media_player, 'errorOccurred'):
                        self.media_player.errorOccurred.disconnect()
                except:
                    pass
                
                # Detener reproducción
                try:
                    self.media_player.stop()
                except Exception:
                    pass
                
                # Limpiar fuente
                try:
                    self.media_player.setSource(QUrl())
                except Exception:
                    pass
                
                # Limpiar referencias
                self.media_player = None
            except Exception as e:
                print(f"️ Error limpiando media player: {e}")
        
        # Limpiar audio output si existe
        if hasattr(self, 'audio_output') and self.audio_output is not None:
            try:
                self.audio_output = None
            except:
                pass
        
        event.accept()


def _format_player_time(ms: int) -> str:
    total_seconds = max(0, int(ms) // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


class LocalVideoPreviewDialog(QDialog):
    """Reproduce un video local insertado o recortado.

    QtMultimedia no tiene backend de video en este entorno (QVideoSink
    "Not available"). Se usa VLC si está instalado, y si no moviepy/ffmpeg
    para mostrar frames en un QLabel — el mismo enfoque del editor de recorte.
    """

    def __init__(self, parent=None, video_path="", title=None):
        super().__init__(parent)
        self.video_path = os.path.normpath(os.path.abspath(str(video_path or "")))
        self._slider_pressed = False
        self._backend = None
        self._vlc_instance = None
        self._vlc_player = None
        self._vlc_hwnd_ready = False
        self.video_clip = None
        self.playback_timer = None
        self.playback_position = 0.0
        self.video_duration = 0.0
        self.is_playing = False

        display_name = os.path.basename(self.video_path) if self.video_path else "Video"
        self.setWindowTitle(title or f"Video — {display_name}")
        self.setMinimumSize(720, 480)
        self.resize(900, 620)
        self._probe_duration()
        self._backend = self._choose_backend()
        self.setup_ui()

    def _probe_duration(self):
        self.video_duration = 0.0
        if not self.video_path or not os.path.exists(self.video_path):
            return
        try:
            import shutil
            import subprocess
            ffprobe = shutil.which("ffprobe")
            if not ffprobe:
                return
            result = subprocess.run(
                [
                    ffprobe, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    self.video_path,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                self.video_duration = max(0.0, float(result.stdout.strip()))
        except Exception as exc:
            print(f"[LocalVideoPreview] ffprobe: {exc}")

    def _choose_backend(self):
        try:
            import vlc
            instance = vlc.Instance("--quiet", "--no-video-title-show")
            player = instance.media_player_new() if instance else None
            if player:
                self._vlc_instance = instance
                self._vlc_player = player
                print("[LocalVideoPreview] Backend: VLC")
                return "vlc"
        except Exception as exc:
            print(f"[LocalVideoPreview] VLC no disponible ({exc})")
        print("[LocalVideoPreview] Backend: moviepy/ffmpeg")
        return "moviepy"

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        info = QLabel(os.path.basename(self.video_path) if self.video_path else "Sin video")
        info.setWordWrap(True)
        info.setObjectName("subtitle")
        layout.addWidget(info)

        if self._backend == "vlc":
            self.video_surface = QWidget()
            self.video_surface.setMinimumSize(640, 360)
            self.video_surface.setStyleSheet("background-color: #111;")
            layout.addWidget(self.video_surface, 1)
            self.video_label = None
        else:
            self.video_label = QLabel("Cargando video...")
            self.video_label.setMinimumSize(640, 360)
            self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_label.setStyleSheet("background-color: #111; color: #ddd;")
            self.video_label.setScaledContents(False)
            layout.addWidget(self.video_label, 1)
            self.video_surface = self.video_label

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        duration_ms = int(self.video_duration * 1000)
        self.position_slider.setRange(0, max(0, duration_ms))
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        layout.addWidget(self.position_slider)

        time_row = QHBoxLayout()
        self.time_label = QLabel("00:00")
        self.duration_label = QLabel(_format_player_time(duration_ms))
        time_row.addWidget(self.time_label)
        time_row.addStretch()
        time_row.addWidget(self.duration_label)
        layout.addLayout(time_row)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("Pausar")
        self.play_btn.clicked.connect(self.toggle_playback)
        controls.addWidget(self.play_btn)

        self.stop_btn = QPushButton("Detener")
        self.stop_btn.clicked.connect(self.stop_playback)
        controls.addWidget(self.stop_btn)

        controls.addStretch()
        open_btn = QPushButton("Abrir en reproductor del sistema")
        open_btn.clicked.connect(self.open_in_system_player)
        controls.addWidget(open_btn)
        layout.addLayout(controls)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(50 if self._backend == "moviepy" else 200)
        self.playback_timer.timeout.connect(self._on_tick)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_started", False):
            return
        self._started = True
        QTimer.singleShot(0, self._start_playback)

    def _start_playback(self):
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.warning(
                self,
                "Video no encontrado",
                f"No se encontró el archivo:\n{self.video_path}",
            )
            return
        if self._backend == "vlc":
            self._start_vlc()
        else:
            self._start_moviepy()

    def _start_vlc(self):
        try:
            media = self._vlc_instance.media_new(self.video_path)
            self._vlc_player.set_media(media)
            hwnd = int(self.video_surface.winId())
            if hasattr(self._vlc_player, "set_hwnd"):
                self._vlc_player.set_hwnd(hwnd)
            elif hasattr(self._vlc_player, "set_xwindow"):
                self._vlc_player.set_xwindow(hwnd)
            self._vlc_hwnd_ready = True
            self._vlc_player.play()
            self.is_playing = True
            self.play_btn.setText("Pausar")
            self.playback_timer.start()
        except Exception as exc:
            print(f"[LocalVideoPreview] VLC falló ({exc}), usando moviepy")
            self._fallback_to_moviepy()

    def _fallback_to_moviepy(self):
        self._backend = "moviepy"
        if self.video_label is None:
            self.video_label = QLabel("Cargando video...")
            self.video_label.setMinimumSize(640, 360)
            self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_label.setStyleSheet("background-color: #111; color: #ddd;")
            layout = self.layout()
            if self.video_surface is not None:
                layout.replaceWidget(self.video_surface, self.video_label)
                self.video_surface.hide()
                self.video_surface.deleteLater()
            self.video_surface = self.video_label
        self.playback_timer.setInterval(50)
        self._start_moviepy()

    def _start_moviepy(self):
        try:
            from moviepy.editor import VideoFileClip
            if self.video_label:
                self.video_label.setText("Cargando video...")
            self.video_clip = VideoFileClip(self.video_path)
            if self.video_duration <= 0:
                self.video_duration = float(self.video_clip.duration or 0)
                duration_ms = int(self.video_duration * 1000)
                self.position_slider.setRange(0, max(0, duration_ms))
                self.duration_label.setText(_format_player_time(duration_ms))
            self.playback_position = 0.0
            self.is_playing = True
            self.play_btn.setText("Pausar")
            self._render_moviepy_frame()
            self.playback_timer.start()
        except Exception as exc:
            if self.video_label:
                self.video_label.setText(
                    "No se pudo decodificar el video aquí.\n"
                    "Usá 'Abrir en reproductor del sistema'."
                )
            QMessageBox.warning(
                self,
                "No se pudo reproducir",
                f"{exc}\n\nPodés abrirlo con el reproductor del sistema.",
            )

    def toggle_playback(self):
        if self._backend == "vlc" and self._vlc_player:
            try:
                if self._vlc_player.is_playing():
                    self._vlc_player.pause()
                    self.is_playing = False
                    self.play_btn.setText("Reproducir")
                else:
                    self._vlc_player.play()
                    self.is_playing = True
                    self.play_btn.setText("Pausar")
                    if not self.playback_timer.isActive():
                        self.playback_timer.start()
            except Exception as exc:
                print(f"[LocalVideoPreview] VLC toggle: {exc}")
            return

        if not self.video_clip:
            self._start_moviepy()
            return
        if self.is_playing:
            self.is_playing = False
            self.playback_timer.stop()
            self.play_btn.setText("Reproducir")
        else:
            self.is_playing = True
            self.play_btn.setText("Pausar")
            self.playback_timer.start()

    def stop_playback(self):
        self.is_playing = False
        self.playback_position = 0.0
        self.play_btn.setText("Reproducir")
        if self.playback_timer:
            self.playback_timer.stop()
        if self._backend == "vlc" and self._vlc_player:
            try:
                self._vlc_player.stop()
            except Exception:
                pass
        if self.position_slider:
            self.position_slider.setValue(0)
        if self.time_label:
            self.time_label.setText("00:00")
        if self.video_clip:
            self._render_moviepy_frame()

    def _on_tick(self):
        if self._backend == "vlc" and self._vlc_player:
            self._sync_vlc_position()
            return
        if not self.video_clip or not self.is_playing:
            return
        self.playback_position += 0.05
        if self.video_duration and self.playback_position >= self.video_duration:
            self.stop_playback()
            return
        self._render_moviepy_frame()
        self._update_time_ui(self.playback_position)

    def _sync_vlc_position(self):
        try:
            length = int(self._vlc_player.get_length() or 0)
            if length > 0:
                if self.video_duration <= 0:
                    self.video_duration = length / 1000.0
                    self.position_slider.setRange(0, length)
                    self.duration_label.setText(_format_player_time(length))
                pos = int(self._vlc_player.get_time() or 0)
                if not self._slider_pressed:
                    self.position_slider.setValue(pos)
                self.time_label.setText(_format_player_time(pos))
            playing = bool(self._vlc_player.is_playing())
            self.is_playing = playing
            self.play_btn.setText("Pausar" if playing else "Reproducir")
        except Exception:
            pass

    def _render_moviepy_frame(self):
        if not self.video_clip or not self.video_label:
            return
        try:
            import io
            from PIL import Image
            safe_time = max(0.0, min(self.playback_position, max(0.0, self.video_duration - 0.04)))
            frame = self.video_clip.get_frame(safe_time)
            pil_image = Image.fromarray(frame.astype("uint8"), "RGB")
            label_w = max(2, self.video_label.width())
            label_h = max(2, self.video_label.height())
            pil_image.thumbnail((label_w, label_h), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            pil_image.save(buffer, format="JPEG", quality=80)
            buffer.seek(0)
            pixmap = QPixmap()
            if pixmap.loadFromData(buffer.getvalue()) and not pixmap.isNull():
                self.video_label.setText("")
                self.video_label.setPixmap(pixmap)
        except Exception as exc:
            print(f"[LocalVideoPreview] frame: {exc}")

    def _update_time_ui(self, seconds):
        ms = int(max(0.0, seconds) * 1000)
        if self.position_slider and not self._slider_pressed:
            self.position_slider.setValue(ms)
        if self.time_label:
            self.time_label.setText(_format_player_time(ms))

    def _seek(self, ms):
        seconds = max(0.0, ms / 1000.0)
        self.playback_position = seconds
        if self._backend == "vlc" and self._vlc_player:
            try:
                self._vlc_player.set_time(int(ms))
            except Exception:
                pass
            return
        if self.video_clip:
            self._render_moviepy_frame()

    def _on_slider_pressed(self):
        self._slider_pressed = True

    def _on_slider_released(self):
        self._slider_pressed = False
        self._seek(int(self.position_slider.value()))

    def _on_slider_moved(self, value):
        if self.time_label:
            self.time_label.setText(_format_player_time(value))

    def open_in_system_player(self):
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.warning(self, "Error", "No hay un archivo de video disponible.")
            return
        try:
            os.startfile(self.video_path)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo abrir el video:\n{exc}")

    def closeEvent(self, event):
        self.is_playing = False
        if self.playback_timer:
            self.playback_timer.stop()
        if self._vlc_player is not None:
            try:
                self._vlc_player.stop()
            except Exception:
                pass
            self._vlc_player = None
            self._vlc_instance = None
        if self.video_clip is not None:
            try:
                self.video_clip.close()
            except Exception:
                pass
            self.video_clip = None
        event.accept()


# ========== WIKIMEDIA VIDEO SEARCH CLASSES ==========

