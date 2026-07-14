# video_preview_dialog.py
"""
Diálogo VideoPreviewDialog.
Extraído de timeline_editor_widget.py para mejorar la organización del código.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QMessageBox, QScrollArea, QWidget, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon
from pathlib import Path
import os
import requests
import warnings

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
        
        # Solo procesar archivos locales desde aquí
            # Ocultar controles de reproducción y mostrar mensaje
            if hasattr(self, 'play_btn'):
                self.play_btn.setVisible(False)
            if hasattr(self, 'stop_btn'):
                self.stop_btn.setVisible(False)
            
            # Mostrar mensaje informativo en lugar de intentar reproducir
            if hasattr(self, 'video_widget') and self.video_widget:
                info_label = QLabel(
                    "ℹ️ Preview de video remoto no disponible por seguridad.\n\n"
                    "Los videos de Internet Archive/Wikimedia no se pueden reproducir directamente\n"
                    "en el preview para evitar problemas de estabilidad.\n\n"
                    "Usa el botón ' Abrir en Navegador' para ver el video,\n"
                    "o ' Seleccionar Video' para descargarlo y usarlo en tu proyecto."
                )
                info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                info_label.setObjectName("subtitle")
                info_label.setWordWrap(True)
                
                # Reemplazar el video widget con el mensaje
                if hasattr(self, 'video_widget') and self.video_widget:
                    layout = self.video_widget.parent().layout()
                    if layout:
                        layout.removeWidget(self.video_widget)
                        self.video_widget.setParent(None)
                        layout.addWidget(info_label)
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


# ========== WIKIMEDIA VIDEO SEARCH CLASSES ==========

