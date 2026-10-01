# video_edit_dialog.py
"""
Diálogo para editar/recortar el video asignado a un segmento.
Permite seleccionar qué parte del video usar (inicio y fin del clip).
Incluye timeline visual, controles de reproducción y preview del video.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QGroupBox, QMessageBox, QProgressBar, QCheckBox, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap
import os
from pathlib import Path

# Importar VideoTimelineWidget
try:
    from studio.timeline_video_widget import VideoTimelineWidget
except ImportError:
    VideoTimelineWidget = None
    print("️ timeline_video_widget.py no encontrado. VideoTimelineWidget no estará disponible.")


class CropWorker(QThread):
    """Worker para recortar video en segundo plano."""
    finished = pyqtSignal(str)   # Emite ruta del video recortado
    error = pyqtSignal(str)      # Emite mensaje de error
    progress = pyqtSignal(str)   # Emite mensajes de progreso

    def __init__(self, video_path, crop_start, crop_end):
        super().__init__()
        self.video_path = video_path
        self.crop_start = crop_start
        self.crop_end = crop_end

    def run(self):
        try:
            import tempfile
            import time
            from moviepy.editor import VideoFileClip

            self.progress.emit("Abriendo video...")
            clip = VideoFileClip(self.video_path)

            self.progress.emit(f"Recortando {self.crop_start:.1f}s - {self.crop_end:.1f}s...")
            cropped_clip = clip.subclip(self.crop_start, self.crop_end)

            # Escribir a directorio temporal local (no Google Drive)
            temp_dir = Path(tempfile.gettempdir()) / "video_optimizer" / "cropped_videos"
            temp_dir.mkdir(parents=True, exist_ok=True)

            video_name = Path(self.video_path).stem
            cropped_name = f"{video_name}_crop_{int(self.crop_start)}_{int(self.crop_end)}_{int(time.time())}.mp4"
            cropped_path = str(temp_dir / cropped_name)

            self.progress.emit("Escribiendo video recortado...")
            write_kwargs = {
                'codec': 'libx264',
                'audio_codec': 'aac',
                'verbose': False,
                'logger': None
            }
            source_fps = getattr(clip, 'fps', 0) or 0
            if source_fps > 0:
                write_kwargs['fps'] = float(source_fps)

            cropped_clip.write_videofile(cropped_path, **write_kwargs)
            cropped_clip.close()
            clip.close()

            if os.path.exists(cropped_path) and os.path.getsize(cropped_path) > 0:
                self.finished.emit(cropped_path)
            else:
                self.error.emit("El archivo recortado está vacío o no se creó.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class VideoEditDialog(QDialog):
    """Diálogo para editar/recortar el video de un segmento"""
    
    def __init__(self, parent=None, segment_data=None, video_path=None):
        super().__init__(parent)
        self.segment_data = segment_data or {}
        self.video_path = video_path
        self.cropped_video_path = None
        
        # Obtener información del video
        self.video_duration = 0
        self.video_info_loaded = False
        
        # Variables para reproducción con moviepy
        self.video_clip = None
        self.playback_timer = None
        self.playback_position = 0.0
        self.is_playing = False
        
        if self.video_path and os.path.exists(self.video_path):
            self.load_video_info()
        
        self.setWindowTitle("️ Editar Video del Segmento")
        self.setMinimumSize(900, 700)
        self.resize(1100, 800)
        
        self.setup_ui()
    
    def load_video_info(self):
        """Carga información del video usando ffprobe"""
        try:
            import subprocess
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                self.video_path
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                self.video_duration = float(result.stdout.strip())
                self.video_info_loaded = True
                print(f"[VideoEditDialog] Video cargado: {os.path.basename(self.video_path)}, duración: {self.video_duration:.2f}s")
            else:
                raise RuntimeError(result.stderr or "ffprobe no devolvio duracion")
        except Exception as e:
            print(f"️ Error cargando información del video: {e}")
            self.video_duration = 0
            self.video_info_loaded = False
    
    def setup_ui(self):
        """Configura la interfaz del diálogo"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Título
        title = QLabel("Editor de Segmento de Video")
        title.setObjectName("title")
        layout.addWidget(title)
        
        # Información del video
        info_group = QGroupBox(" Información del Video")
        info_layout = QVBoxLayout(info_group)
        
        if self.video_path:
            video_name = os.path.basename(self.video_path)
            info_label = QLabel(f" Archivo: {video_name}")
            info_layout.addWidget(info_label)
            
            if self.video_info_loaded:
                duration_label = QLabel(f"️ Duración total: {self.video_duration:.2f} segundos")
                info_layout.addWidget(duration_label)
            else:
                error_label = QLabel("️ No se pudo cargar información del video")
                error_label.setObjectName("errorText")
                info_layout.addWidget(error_label)
        else:
            error_label = QLabel(" No hay video asignado a este segmento")
            error_label.setObjectName("errorText")
            info_layout.addWidget(error_label)
        
        layout.addWidget(info_group)
        
        if not self.video_info_loaded or self.video_duration <= 0:
            # No se puede editar si no hay información del video
            close_btn = QPushButton(" Cerrar")
            close_btn.clicked.connect(self.reject)
            layout.addWidget(close_btn)
            return
        
        # Scroll area para el contenido principal
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        # Grupo de controles de recorte (similar a CapCut con timeline visual)
        crop_group = QGroupBox("️ Recortar Video")
        crop_layout = QVBoxLayout(crop_group)
        
        crop_info_label = QLabel("Selecciona el rango de tiempo del video que deseas usar en este segmento:")
        crop_info_label.setObjectName("subtitle")
        crop_info_label.setWordWrap(True)
        crop_layout.addWidget(crop_info_label)
        
        # Widget de video para reproducción (usando QLabel + moviepy)
        self.video_label = QLabel()
        self.video_label.setMinimumHeight(200)
        self.video_label.setMaximumHeight(250)
        self.video_label.setObjectName("videoPreview")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setText("Presiona Play para ver el video")
        self.video_label.setVisible(True)
        crop_layout.addWidget(self.video_label)
        
        # Barra de progreso para carga de video
        self.video_loading_progress = QProgressBar()
        self.video_loading_progress.setVisible(False)
        self.video_loading_progress.setTextVisible(True)
        self.video_loading_progress.setFormat("Cargando video... %p%")
        crop_layout.addWidget(self.video_loading_progress)
        
        # Widget de timeline de video (similar a CapCut)
        if VideoTimelineWidget:
            self.video_timeline = VideoTimelineWidget()
            self.video_timeline.set_video_duration(self.video_duration)
            self.video_timeline.set_crop_range(0.0, self.video_duration)
            self.video_timeline.crop_range_changed.connect(self.on_timeline_crop_changed)
            self.video_timeline.position_clicked.connect(self.on_timeline_position_clicked)
            self.video_timeline.position_dragged.connect(self.on_timeline_position_dragged)
            
            # Cargar frames del video en el timeline
            if self.video_path and os.path.exists(self.video_path):
                try:
                    self.video_timeline.load_video_frames(self.video_path, num_frames=20)
                except Exception as e:
                    print(f"️ Error cargando frames: {e}")
            
            crop_layout.addWidget(self.video_timeline)
        else:
            self.video_timeline = None
            print("️ VideoTimelineWidget no disponible")
        
        # Controles de reproducción
        playback_controls_layout = QHBoxLayout()
        playback_controls_layout.addStretch()
        
        self.play_btn = QPushButton("️ Play")
        self.play_btn.setMaximumWidth(80)
        self.play_btn.clicked.connect(self.toggle_playback)
        playback_controls_layout.addWidget(self.play_btn)
        
        self.stop_btn = QPushButton("️ Stop")
        self.stop_btn.setMaximumWidth(80)
        self.stop_btn.clicked.connect(self.stop_playback)
        playback_controls_layout.addWidget(self.stop_btn)
        
        # Botón para reproducir solo el tramo recortado
        self.play_crop_btn = QPushButton(" Play Recorte")
        self.play_crop_btn.setMaximumWidth(120)
        self.play_crop_btn.setToolTip("Reproducir solo el tramo seleccionado (entre las barras amarillas)")
        self.play_crop_btn.clicked.connect(self.play_crop_range)
        playback_controls_layout.addWidget(self.play_crop_btn)
        
        playback_controls_layout.addStretch()
        crop_layout.addLayout(playback_controls_layout)
        
        # Controles numéricos de recorte (como respaldo)
        numeric_crop_layout = QHBoxLayout()
        
        numeric_crop_layout.addWidget(QLabel("Inicio:"))
        self.crop_start_spin = QDoubleSpinBox()
        self.crop_start_spin.setRange(0, self.video_duration)
        self.crop_start_spin.setDecimals(2)
        self.crop_start_spin.setSuffix(" s")
        self.crop_start_spin.setValue(0.0)
        self.crop_start_spin.setSingleStep(0.5)
        self.crop_start_spin.valueChanged.connect(self.on_crop_spin_changed)
        numeric_crop_layout.addWidget(self.crop_start_spin)
        
        numeric_crop_layout.addWidget(QLabel("Fin:"))
        self.crop_end_spin = QDoubleSpinBox()
        self.crop_end_spin.setRange(0, self.video_duration)
        self.crop_end_spin.setDecimals(2)
        self.crop_end_spin.setSuffix(" s")
        self.crop_end_spin.setValue(self.video_duration)
        self.crop_end_spin.setSingleStep(0.5)
        self.crop_end_spin.valueChanged.connect(self.on_crop_spin_changed)
        numeric_crop_layout.addWidget(self.crop_end_spin)
        
        self.reset_crop_btn = QPushButton(" Resetear")
        self.reset_crop_btn.setToolTip("Restablecer recorte al video completo")
        self.reset_crop_btn.clicked.connect(self.reset_crop_range)
        
        numeric_crop_layout.addStretch()
        crop_layout.addLayout(numeric_crop_layout)
        
        # Checkbox para habilitar recorte
        self.enable_crop_checkbox = QCheckBox("Habilitar recorte de video")
        self.enable_crop_checkbox.stateChanged.connect(self.on_crop_checkbox_changed)
        crop_layout.addWidget(self.enable_crop_checkbox)

        # Botones de recorte
        crop_buttons_layout = QHBoxLayout()

        self.fit_segment_btn = QPushButton(" Ajustar a Segmento")
        self.fit_segment_btn.setEnabled(False)
        self.fit_segment_btn.setToolTip("Ajusta el recorte a la duración del segmento actual")
        self.fit_segment_btn.clicked.connect(self.fit_crop_to_segment)
        crop_buttons_layout.addWidget(self.fit_segment_btn)

        crop_buttons_layout.addWidget(self.reset_crop_btn)
        crop_buttons_layout.addStretch()
        crop_layout.addLayout(crop_buttons_layout)

        # Duración del clip seleccionado
        self.duration_label = QLabel()
        self.update_duration_label()
        crop_layout.addWidget(self.duration_label)

        # Iniciar con recorte deshabilitado
        self.crop_start_spin.setEnabled(False)
        self.crop_end_spin.setEnabled(False)
        self.reset_crop_btn.setEnabled(False)
        
        scroll_layout.addWidget(crop_group)
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)
        
        # Barra de progreso para recorte (oculta inicialmente)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Botones
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        cancel_btn = QPushButton(" Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        
        apply_btn = QPushButton(" Aplicar Recorte")
        apply_btn.setObjectName("accent")
        apply_btn.clicked.connect(self.apply_crop)
        buttons_layout.addWidget(apply_btn)
        
        layout.addLayout(buttons_layout)
    
    def on_timeline_crop_changed(self, start_time, end_time):
        """Callback cuando cambia el rango de recorte en el timeline"""
        # Actualizar controles numéricos
        self.crop_start_spin.blockSignals(True)
        self.crop_end_spin.blockSignals(True)
        self.crop_start_spin.setValue(start_time)
        self.crop_end_spin.setValue(end_time)
        self.crop_start_spin.blockSignals(False)
        self.crop_end_spin.blockSignals(False)
        self.update_duration_label()
    
    def on_timeline_position_clicked(self, position):
        """Callback cuando se hace clic en el timeline para cambiar posición"""
        self.playback_position = position
        if self.video_clip:
            self.update_video_frame()
    
    def on_timeline_position_dragged(self, position):
        """Callback cuando se arrastra la barra de posición"""
        self.playback_position = position
        if self.video_clip:
            self.update_video_frame()
    
    def on_crop_spin_changed(self):
        """Callback cuando cambian los controles numéricos de recorte"""
        start = self.crop_start_spin.value()
        end = self.crop_end_spin.value()
        
        # Actualizar timeline
        if self.video_timeline:
            self.video_timeline.set_crop_range(start, end)
        
        self.update_duration_label()
    
    def on_crop_checkbox_changed(self, state):
        """Habilita/deshabilita los controles de recorte según el checkbox"""
        enabled = (state == Qt.CheckState.Checked.value)
        self.crop_start_spin.setEnabled(enabled)
        self.crop_end_spin.setEnabled(enabled)
        self.fit_segment_btn.setEnabled(enabled)
        self.reset_crop_btn.setEnabled(enabled)

    def fit_crop_to_segment(self):
        """Ajusta el recorte para que coincida con la duración del segmento"""
        segment_duration = 0.0
        if self.segment_data:
            segment_duration = float(self.segment_data.get('duration', 0) or 0)
            if segment_duration <= 0:
                start = float(self.segment_data.get('start', 0) or 0)
                end = float(self.segment_data.get('end', 0) or 0)
                if end > start:
                    segment_duration = end - start

        if segment_duration <= 0:
            QMessageBox.warning(self, "Sin duración de segmento",
                                "No se pudo determinar la duración del segmento.")
            return

        if self.video_duration <= 0:
            return

        if segment_duration > self.video_duration:
            QMessageBox.warning(self, "Segmento muy largo",
                                f"La duración del segmento ({segment_duration:.1f}s) es mayor que la del video ({self.video_duration:.1f}s).\n"
                                "Se usará todo el video.")
            segment_duration = self.video_duration

        # Usar posición actual del timeline como punto de inicio
        current_position = self.playback_position if self.playback_position > 0 else 0.0
        new_start = current_position
        new_end = new_start + segment_duration

        if new_end > self.video_duration:
            new_end = self.video_duration
            new_start = max(0.0, self.video_duration - segment_duration)

        self.crop_start_spin.setValue(new_start)
        self.crop_end_spin.setValue(new_end)
        if self.video_timeline:
            self.video_timeline.set_crop_range(new_start, new_end)
        self.update_duration_label()
        print(f" Recorte ajustado a segmento: {new_start:.1f}s - {new_end:.1f}s ({segment_duration:.1f}s)")

    def reset_crop_range(self):
        """Resetea el rango de recorte al video completo"""
        if self.video_timeline:
            self.video_timeline.set_crop_range(0.0, self.video_duration)
        self.crop_start_spin.setValue(0.0)
        self.crop_end_spin.setValue(self.video_duration)
        self.update_duration_label()
    
    def update_duration_label(self):
        """Actualiza la etiqueta de duración del clip seleccionado"""
        start = self.crop_start_spin.value()
        end = self.crop_end_spin.value()
        duration = end - start
        
        if duration > 0:
            self.duration_label.setText(f" Duración del clip seleccionado: {duration:.2f} segundos ({start:.2f}s - {end:.2f}s)")
            self.duration_label.setObjectName("successText")
            # Force style refresh
            self.duration_label.style().unpolish(self.duration_label)
            self.duration_label.style().polish(self.duration_label)
        else:
            self.duration_label.setText("️ El tiempo de inicio debe ser menor que el tiempo de fin")
            self.duration_label.setObjectName("errorText")
            # Force style refresh
            self.duration_label.style().unpolish(self.duration_label)
            self.duration_label.style().polish(self.duration_label)
    
    def toggle_playback(self):
        """Inicia o pausa la reproducción del video"""
        if not self.video_path or not os.path.exists(self.video_path):
            return
        
        if not self.video_clip:
            # Cargar video por primera vez
            try:
                from moviepy.editor import VideoFileClip
                self.video_clip = VideoFileClip(self.video_path)
                self.playback_position = 0.0
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo cargar el video:\n{str(e)}")
                return
        
        if self.is_playing:
            # Pausar
            if self.playback_timer:
                self.playback_timer.stop()
            self.is_playing = False
            self.play_btn.setText("️ Play")
        else:
            # Reproducir
            self.is_playing = True
            self.play_btn.setText("️ Pause")
            
            if not self.playback_timer:
                self.playback_timer = QTimer()
                self.playback_timer.timeout.connect(self.update_playback)
            
            self.playback_timer.start(33)  # ~30 FPS
            self.update_playback()
    
    def stop_playback(self):
        """Detiene la reproducción del video"""
        if self.playback_timer:
            self.playback_timer.stop()
        self.is_playing = False
        self.playback_position = 0.0
        self.play_btn.setText("️ Play")
        
        if self.video_clip:
            self.update_video_frame()
        
        if self.video_timeline:
            self.video_timeline.set_current_position(0.0)
    
    def play_crop_range(self):
        """Reproduce solo el rango seleccionado entre las barras de recorte"""
        crop_start = self.crop_start_spin.value()
        crop_end = self.crop_end_spin.value()
        
        if crop_start >= crop_end:
            QMessageBox.warning(self, "Rango Inválido", "El tiempo de inicio debe ser menor que el tiempo de fin.")
            return
        
        if not self.video_path or not os.path.exists(self.video_path):
            return
        
        try:
            from moviepy.editor import VideoFileClip
            
            # Cargar video
            if not self.video_clip:
                self.video_clip = VideoFileClip(self.video_path)
            
            # Crear clip recortado
            cropped_clip = self.video_clip.subclip(crop_start, crop_end)
            
            # Reproducir el clip recortado (mostrar frames)
            self.playback_position = crop_start
            self.is_playing = True
            self.play_btn.setText("️ Pause")
            
            if not self.playback_timer:
                self.playback_timer = QTimer()
                self.playback_timer.timeout.connect(self.update_playback_crop)
            
            self.crop_start = crop_start
            self.crop_end = crop_end
            self.playback_timer.start(33)  # ~30 FPS
            self.update_playback_crop()
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo reproducir el recorte:\n{str(e)}")
    
    def update_playback(self):
        """Actualiza la reproducción del video completo"""
        if not self.video_clip or not self.is_playing:
            return
        
        if self.playback_position >= self.video_duration:
            self.stop_playback()
            return
        
        self.update_video_frame()
        
        # Actualizar timeline
        if self.video_timeline:
            self.video_timeline.set_current_position(self.playback_position)
        
        # Incrementar posición
        self.playback_position += 1.0 / 30.0  # ~30 FPS
    
    def update_playback_crop(self):
        """Actualiza la reproducción del rango recortado"""
        if not self.video_clip or not self.is_playing:
            return
        
        if self.playback_position >= self.crop_end:
            # Volver al inicio del recorte
            self.playback_position = self.crop_start
        
        self.update_video_frame()
        
        # Actualizar timeline
        if self.video_timeline:
            self.video_timeline.set_current_position(self.playback_position)
        
        # Incrementar posición
        self.playback_position += 1.0 / 30.0  # ~30 FPS
    
    def update_video_frame(self):
        """Actualiza el frame mostrado en el video_label"""
        if not self.video_clip:
            return
        
        try:
            import io
            from PIL import Image
            
            safe_time = max(0.0, min(self.playback_position, self.video_duration - 0.001))
            frame = self.video_clip.get_frame(safe_time)
            pil_image = Image.fromarray(frame.astype('uint8'), 'RGB')
            
            label_w = self.video_label.width()
            label_h = self.video_label.height()
            if label_w > 0 and label_h > 0:
                pil_image.thumbnail((label_w, label_h), Image.Resampling.LANCZOS)
            
            buffer = io.BytesIO()
            pil_image.save(buffer, format='PNG')
            buffer.seek(0)
            
            pixmap = QPixmap()
            if pixmap.loadFromData(buffer.getvalue()) and not pixmap.isNull():
                self.video_label.setText("")
                self.video_label.setPixmap(pixmap)
        except Exception as e:
            print(f"️ Error actualizando frame: {e}")
    
    def apply_crop(self):
        """Aplica el recorte al video"""
        # Si el recorte no está habilitado, usar video completo
        if not self.enable_crop_checkbox.isChecked():
            self.cropped_video_path = self.video_path
            self.accept()
            return

        crop_start = self.crop_start_spin.value()
        crop_end = self.crop_end_spin.value()
        
        # Validar rango
        if crop_start >= crop_end:
            QMessageBox.warning(self, "Rango Inválido",
                                "El tiempo de inicio debe ser menor que el tiempo de fin.")
            return
        
        if crop_start < 0 or crop_end > self.video_duration:
            QMessageBox.warning(self, "Rango Inválido",
                                f"Los tiempos deben estar entre 0 y {self.video_duration:.2f} segundos.")
            return
        
        # Si el recorte es el video completo, no hacer nada
        if crop_start == 0 and crop_end >= self.video_duration:
            self.cropped_video_path = self.video_path
            self.accept()
            return
        
        # Detener reproducción y liberar clip
        self.stop_playback()
        if self.video_clip:
            self.video_clip.close()
            self.video_clip = None
        
        # Mostrar progreso y deshabilitar botones
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Recortando video...")
        
        print(f"[VideoEditDialog] Recortando video en background: {crop_start:.2f}s - {crop_end:.2f}s")
        
        self.crop_worker = CropWorker(self.video_path, crop_start, crop_end)
        self.crop_worker.finished.connect(self._on_crop_finished)
        self.crop_worker.error.connect(self._on_crop_error)
        self.crop_worker.progress.connect(lambda msg: self.progress_bar.setFormat(msg))
        self.crop_worker.start()

    def _on_crop_finished(self, cropped_path):
        """Callback cuando el recorte termina exitosamente"""
        self.progress_bar.setVisible(False)
        self.cropped_video_path = cropped_path
        print(f" Video recortado guardado: {cropped_path}")
        QMessageBox.information(
            self,
            "Recorte Completado",
            f" Video recortado exitosamente.\n\n"
            f" {os.path.basename(cropped_path)}"
        )
        self.accept()

    def _on_crop_error(self, error_msg):
        """Callback cuando el recorte falla"""
        self.progress_bar.setVisible(False)
        print(f" Error recortando video: {error_msg}")
        QMessageBox.critical(self, "Error", f"Error recortando video:\n{error_msg}")
    
    def closeEvent(self, event):
        """Limpia recursos al cerrar el diálogo"""
        # Detener reproducción
        if self.playback_timer:
            self.playback_timer.stop()
        
        # Cerrar video_clip
        if self.video_clip:
            try:
                self.video_clip.close()
            except:
                pass
            self.video_clip = None
        
        super().closeEvent(event)
