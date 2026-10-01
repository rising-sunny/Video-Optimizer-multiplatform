# local_video_picker_dialog.py
"""
Diálogo para seleccionar y recortar un video local desde el sistema de archivos.
Similar a WikimediaVideoSearchDialog pero para archivos locales.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QMessageBox, QScrollArea, QWidget,
    QCheckBox, QGroupBox, QDoubleSpinBox, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap
from pathlib import Path
import os
import time

# Importar VideoTimelineWidget
try:
    from studio.timeline_video_widget import VideoTimelineWidget
except ImportError:
    VideoTimelineWidget = None
    print("️ timeline_video_widget.py no encontrado. VideoTimelineWidget no estará disponible.")


class LocalFrameExtractorWorker(QThread):
    """Worker para extraer frames de un video local sin descargar."""
    finished = pyqtSignal(str, list)  # (video_path, list of QPixmap frames)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, video_path, num_frames=15):
        super().__init__()
        self.video_path = video_path
        self.num_frames = num_frames

    def run(self):
        try:
            from moviepy.editor import VideoFileClip
            from PIL import Image
            import io

            if not os.path.exists(self.video_path):
                self.error.emit(f"Archivo no encontrado: {self.video_path}")
                return

            self.progress.emit("Extrayendo frames del video local...")
            clip = VideoFileClip(self.video_path)
            duration = clip.duration

            if duration <= 0:
                clip.close()
                self.error.emit("El video tiene duración 0")
                return

            frames = []
            frame_times = [i * duration / self.num_frames for i in range(self.num_frames)]

            for i, t in enumerate(frame_times):
                try:
                    self.progress.emit(f"Extrayendo frame {i+1}/{self.num_frames}...")
                    frame = clip.get_frame(t)
                    pil_image = Image.fromarray(frame.astype('uint8'), 'RGB')
                    aspect_ratio = pil_image.width / pil_image.height
                    new_height = 90
                    new_width = int(new_height * aspect_ratio)
                    pil_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    buffer = io.BytesIO()
                    pil_image.save(buffer, format='PNG')
                    buffer.seek(0)
                    pixmap = QPixmap()
                    pixmap.loadFromData(buffer.getvalue())
                    frames.append(pixmap)
                except Exception as e:
                    print(f"️ Error extrayendo frame en t={t}: {e}")
                    continue

            clip.close()

            if frames:
                self.finished.emit(self.video_path, frames)
            else:
                self.error.emit("No se pudieron extraer frames del video")

        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class LocalVideoPickerDialog(QDialog):
    """Diálogo para seleccionar y recortar un video local del sistema de archivos."""

    def __init__(self, parent=None, segment_data=None):
        super().__init__(parent)
        self.segment_data = segment_data or {}
        self.selected_video_path = None
        self._loaded_video_path = None
        self._video_duration = 0.0

        # Preview / playback state
        self.frame_extractor_worker = None
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
        self._closing = False

        self.setWindowTitle(" Seleccionar Video Local")
        self.setMinimumSize(900, 650)
        self.resize(1000, 750)

        self.setup_ui()

    @staticmethod
    def _normalize_duration(duration_value):
        """Convierte duración a segundos (float)."""
        if duration_value is None or isinstance(duration_value, bool):
            return 0.0
        if isinstance(duration_value, (int, float)):
            return float(duration_value) if duration_value > 0 else 0.0
        return 0.0

    def setup_ui(self):
        """Configura la interfaz del diálogo"""
        layout = QVBoxLayout(self)

        # --- Sección: Seleccionar archivo ---
        file_layout = QHBoxLayout()
        file_label = QLabel(" Archivo:")
        file_layout.addWidget(file_label)

        self.file_path_label = QLabel("Ningún archivo seleccionado")
        self.file_path_label.setStyleSheet(
            "color: #a0a0a0; padding: 6px; border: 1px solid #555; "
            "border-radius: 4px; background-color: #1a1a2e;"
        )
        self.file_path_label.setWordWrap(True)
        self.file_path_label.setMinimumHeight(30)
        file_layout.addWidget(self.file_path_label, 1)

        self.browse_btn = QPushButton(" Examinar...")
        self.browse_btn.setMinimumWidth(120)
        self.browse_btn.clicked.connect(self._browse_file)
        file_layout.addWidget(self.browse_btn)

        layout.addLayout(file_layout)

        # Info del video
        self.video_info_label = QLabel("")
        self.video_info_label.setStyleSheet("color: #80d0ff; font-size: 9pt;")
        layout.addWidget(self.video_info_label)

        # Área de scroll para el contenido principal
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        # --- Sección: Recortar Video ---
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

        crop_info_label = QLabel("Especifica el rango de tiempo del video que deseas usar:")
        crop_info_label.setStyleSheet("color: #a0a0a0; font-size: 9pt;")
        crop_info_label.setWordWrap(True)
        crop_layout.addWidget(crop_info_label)

        # Vista previa del video
        self.video_preview_label = QLabel()
        self.video_preview_label.setMinimumHeight(200)
        self.video_preview_label.setMaximumHeight(250)
        self.video_preview_label.setStyleSheet("background-color: #0a0a0a; border-radius: 4px;")
        self.video_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_preview_label.setText("Selecciona un video para cargar preview")
        crop_layout.addWidget(self.video_preview_label)

        # Widget de timeline de video
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

        # Controles de inicio/fin
        crop_controls_layout = QHBoxLayout()

        start_label = QLabel("Inicio:")
        crop_controls_layout.addWidget(start_label)
        self.video_crop_start = QDoubleSpinBox()
        self.video_crop_start.setMinimum(0.0)
        self.video_crop_start.setMaximum(86400.0)
        self.video_crop_start.setDecimals(2)
        self.video_crop_start.setSuffix(" s")
        self.video_crop_start.setValue(0.0)
        self.video_crop_start.setEnabled(False)
        self.video_crop_start.valueChanged.connect(self.on_crop_start_changed)
        crop_controls_layout.addWidget(self.video_crop_start)

        crop_controls_layout.addStretch()

        end_label = QLabel("Fin:")
        crop_controls_layout.addWidget(end_label)
        self.video_crop_end = QDoubleSpinBox()
        self.video_crop_end.setMinimum(0.0)
        self.video_crop_end.setMaximum(86400.0)
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

        # Botones de recorte
        crop_buttons_layout = QHBoxLayout()

        self.fit_segment_btn = QPushButton(" Ajustar a Segmento")
        self.fit_segment_btn.setEnabled(False)
        self.fit_segment_btn.setToolTip("Ajusta el recorte a la duración del segmento actual")
        self.fit_segment_btn.clicked.connect(self.fit_crop_to_segment)
        crop_buttons_layout.addWidget(self.fit_segment_btn)

        self.reset_crop_btn = QPushButton("️ Resetear Recorte")
        self.reset_crop_btn.setEnabled(False)
        self.reset_crop_btn.clicked.connect(self.reset_crop_range)
        crop_buttons_layout.addWidget(self.reset_crop_btn)

        crop_layout.addLayout(crop_buttons_layout)

        scroll_layout.addWidget(crop_group)

        # --- Botones finales ---
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.preview_btn = QPushButton("️ Preview")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self.preview_selected_video)
        self.preview_btn.setToolTip("Abrir el video en el reproductor del sistema")
        buttons_layout.addWidget(self.preview_btn)

        self.select_btn = QPushButton(" Seleccionar Video")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.accept_video)
        buttons_layout.addWidget(self.select_btn)

        cancel_btn = QPushButton(" Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)

        scroll_layout.addLayout(buttons_layout)

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)

    # ── File browsing ──────────────────────────────────────────────

    def _browse_file(self):
        """Abre diálogo para seleccionar un video local"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Video Local",
            "",
            "Videos (*.mp4 *.webm *.avi *.mov *.mkv *.ogv *.mpeg *.mpg);;Todos los archivos (*.*)"
        )
        if not file_path:
            return

        self._load_video(file_path)

    def _load_video(self, file_path):
        """Carga un video local y extrae frames para preview"""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Archivo no encontrado", f"No se encontró: {file_path}")
            return

        self.stop_playback()
        self._close_preview_video_clip()
        self._cancel_frame_extraction()
        self.preview_frames = []
        self.preview_video_path = None

        self._loaded_video_path = os.path.abspath(file_path)
        self.file_path_label.setText(self._loaded_video_path)

        # Obtener duración con moviepy
        try:
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(self._loaded_video_path)
            self._video_duration = self._normalize_duration(clip.duration)
            fps = getattr(clip, 'fps', 0) or 0
            w, h = clip.size if hasattr(clip, 'size') else (0, 0)
            clip.close()
        except Exception as e:
            self._video_duration = 0.0
            fps = 0
            w, h = 0, 0
            print(f"️ Error obteniendo info del video: {e}")

        if self._video_duration <= 0:
            QMessageBox.warning(self, "Video inválido", "No se pudo determinar la duración del video.")
            return

        # Info
        minutes = int(self._video_duration) // 60
        seconds = int(self._video_duration) % 60
        size_mb = os.path.getsize(self._loaded_video_path) / (1024 * 1024)
        info_parts = [f"️ {minutes}:{seconds:02d}"]
        if w and h:
            info_parts.append(f" {w}x{h}")
        if fps:
            info_parts.append(f" {fps:.0f} fps")
        info_parts.append(f" {size_mb:.1f} MB")
        self.video_info_label.setText("   ".join(info_parts))

        # Habilitar controles
        self.select_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        self.enable_crop_checkbox.setEnabled(True)

        # Configurar spinboxes
        self.video_crop_start.setMaximum(self._video_duration)
        self.video_crop_start.setValue(0.0)
        self.video_crop_end.setMaximum(self._video_duration)
        self.video_crop_end.setValue(self._video_duration)

        # Configurar timeline
        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_video_duration(self._video_duration)
            self.video_timeline.set_current_position(0.0)
            self.video_timeline.set_crop_range(0.0, self._video_duration)
            self.video_timeline.setEnabled(True)

        # Resetear botones de playback
        self.play_btn.setEnabled(False)
        self.play_btn.setText("️ Play")
        self.stop_btn.setEnabled(False)
        self.play_segment_btn.setEnabled(False)
        self.playback_position = 0.0

        self.video_preview_label.setText("Cargando preview del video...")
        self.video_preview_label.setPixmap(QPixmap())

        # Iniciar extracción de frames
        self._start_frame_extraction(self._loaded_video_path)

    # ── Frame extraction ───────────────────────────────────────────

    def _start_frame_extraction(self, video_path):
        """Inicia la extracción de frames en segundo plano"""
        self._cancel_frame_extraction()

        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_video_frames([])
            self.video_timeline.set_loading_message("Extrayendo frames del video...")

        self.frame_extractor_worker = LocalFrameExtractorWorker(video_path, num_frames=15)
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

    def _on_frames_extracted(self, video_path, frames):
        """Callback cuando se extraen los frames"""
        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()
            self.video_timeline.set_video_frames(frames)

        self.preview_video_path = video_path if isinstance(video_path, str) and video_path else None
        self._close_preview_video_clip()
        self.preview_frames = frames or []
        self.play_btn.setEnabled(bool(self.preview_frames))
        self.stop_btn.setEnabled(False)
        self._update_play_segment_button_state()
        self.playback_position = 0.0
        if not self._render_preview_frame_from_video(0.0):
            self._render_preview_frame(0.0)

    def _on_frame_extraction_error(self, error_msg):
        """Callback cuando falla la extracción de frames"""
        print(f"️ Error extrayendo frames: {error_msg}")
        if hasattr(self, 'video_timeline'):
            self.video_timeline.clear_loading_message()
        self._close_preview_video_clip()
        self.preview_video_path = None
        self.preview_frames = []
        self.play_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.play_segment_btn.setEnabled(False)
        self.video_preview_label.setPixmap(QPixmap())
        self.video_preview_label.setText("Preview no disponible para este video")

    def _on_frame_extraction_progress(self, message):
        """Callback para progreso de extracción"""
        if hasattr(self, 'video_timeline'):
            self.video_timeline.set_loading_message(message)

    # ── Preview rendering ──────────────────────────────────────────

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
        except Exception as e:
            print(f"️ No se pudo abrir clip de preview: {e}")
            self.preview_video_clip = None
            return None

    def _render_preview_frame_from_video(self, position_seconds):
        """Renderiza frame real del video según la posición actual."""
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
        if not self.preview_frames:
            self.video_preview_label.setPixmap(QPixmap())
            self.video_preview_label.setText("Preview no disponible")
            return

        duration = self._video_duration
        if duration <= 0:
            return

        safe_position = self._normalize_duration(position_seconds)
        ratio = min(1.0, max(0.0, safe_position / duration)) if duration > 0 else 0.0
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

    # ── Playback ───────────────────────────────────────────────────

    def toggle_playback(self):
        """Alterna reproducción/pausa."""
        if self.is_playing:
            self.stop_playback()
            return

        if not self.preview_frames and not self.preview_video_path:
            QMessageBox.warning(self, "Sin preview", "Espera a que se carguen los frames del video.")
            return

        if self._video_duration <= 0:
            return

        self._playing_crop_range = False
        if self.playback_position >= self._video_duration:
            self.playback_position = 0.0
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

        if self.playback_timer is None:
            self.playback_timer = QTimer(self)
            self.playback_timer.timeout.connect(self._advance_timeline_playback)

        self.is_playing = True
        interval_ms = max(16, int(round(1000.0 / max(1.0, self.preview_playback_fps))))
        self.playback_timer.start(interval_ms)
        self.play_btn.setText("️ Pause")
        self.stop_btn.setEnabled(True)

    def stop_playback(self):
        """Detiene la reproducción."""
        if self.playback_timer:
            self.playback_timer.stop()
        self.is_playing = False
        self._playing_crop_range = False
        self._crop_play_start = 0.0
        self._crop_play_end = 0.0
        self.play_btn.setText("️ Play")
        self.stop_btn.setEnabled(False)
        self._update_play_segment_button_state()

    def play_crop_range(self):
        """Reproduce solo el tramo de recorte Inicio-Fin."""
        if not self._is_crop_playback_available():
            QMessageBox.warning(self, "Segmento no disponible",
                                "Activa el recorte y define un rango válido.")
            return

        if self.is_playing:
            self.stop_playback()

        start, end = self._get_crop_bounds()
        start = max(0.0, min(start, self._video_duration))
        end = max(start + 0.05, min(end, self._video_duration))

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
        self.play_btn.setText("️ Pause")
        self.stop_btn.setEnabled(True)

    def _advance_timeline_playback(self):
        """Avanza la línea de reproducción."""
        if not self.is_playing:
            return

        if self._video_duration <= 0:
            self.stop_playback()
            return

        step = 1.0 / max(1.0, self.preview_playback_fps)
        next_position = self.playback_position + step

        if self._playing_crop_range:
            if next_position >= self._crop_play_end:
                self.playback_position = self._crop_play_end
                self.video_timeline.set_current_position(self.playback_position)
                if not self._render_preview_frame_from_video(self.playback_position):
                    self._render_preview_frame(self.playback_position)
                self.stop_playback()
                return
        else:
            if next_position >= self._video_duration:
                self.playback_position = self._video_duration
                self.video_timeline.set_current_position(self.playback_position)
                if not self._render_preview_frame_from_video(self.playback_position):
                    self._render_preview_frame(self.playback_position)
                self.stop_playback()
                return

        self.playback_position = next_position
        self.video_timeline.set_current_position(self.playback_position)
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

    # ── Timeline / crop callbacks ──────────────────────────────────

    def on_timeline_position_clicked(self, position):
        self.playback_position = self._normalize_duration(position)
        self.video_timeline.set_current_position(self.playback_position)
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

    def on_timeline_position_dragged(self, position):
        self.playback_position = self._normalize_duration(position)
        if not self._render_preview_frame_from_video(self.playback_position):
            self._render_preview_frame(self.playback_position)

    def on_timeline_crop_changed(self, start_time, end_time):
        self.video_crop_start.blockSignals(True)
        self.video_crop_start.setValue(start_time)
        self.video_crop_start.blockSignals(False)
        self.video_crop_end.blockSignals(True)
        self.video_crop_end.setValue(end_time)
        self.video_crop_end.blockSignals(False)
        self._update_play_segment_button_state()

    def on_crop_start_changed(self, value):
        end_time = self.video_crop_end.value()
        self.video_timeline.set_crop_range(value, end_time)
        self._update_play_segment_button_state()

    def on_crop_end_changed(self, value):
        start_time = self.video_crop_start.value()
        self.video_timeline.set_crop_range(start_time, value)
        self._update_play_segment_button_state()

    def on_crop_checkbox_changed(self, state):
        enabled = (state == Qt.CheckState.Checked.value)
        has_video = self._loaded_video_path is not None
        self.video_crop_start.setEnabled(enabled)
        self.video_crop_end.setEnabled(enabled)
        self.fit_segment_btn.setEnabled(enabled and has_video)
        self.reset_crop_btn.setEnabled(enabled)
        self._update_play_segment_button_state()

    def _get_crop_bounds(self):
        start = self._normalize_duration(self.video_crop_start.value())
        end = self._normalize_duration(self.video_crop_end.value())
        if end < start:
            start, end = end, start
        return start, end

    def _is_crop_playback_available(self):
        has_preview = bool(self.preview_frames or self.preview_video_path)
        if not has_preview:
            return False
        if not self.enable_crop_checkbox.isChecked():
            return False
        if self._video_duration <= 0:
            return False
        start, end = self._get_crop_bounds()
        if end - start <= 0.05:
            return False
        if start >= self._video_duration:
            return False
        return True

    def _update_play_segment_button_state(self):
        self.play_segment_btn.setEnabled(self._is_crop_playback_available())

    def reset_crop_range(self):
        if self._video_duration > 0:
            self.video_crop_start.setValue(0.0)
            self.video_crop_end.setValue(self._video_duration)
            self.video_timeline.set_crop_range(0.0, self._video_duration)

    def fit_crop_to_segment(self):
        """Ajusta el recorte para que coincida con la duración del segmento"""
        segment_duration = 0.0
        if self.segment_data:
            segment_duration = self._normalize_duration(self.segment_data.get('duration', 0))
            if segment_duration <= 0:
                start = self._normalize_duration(self.segment_data.get('start', 0))
                end = self._normalize_duration(self.segment_data.get('end', 0))
                if end > start:
                    segment_duration = end - start

        if segment_duration <= 0:
            QMessageBox.warning(self, "Sin duración de segmento",
                                "No se pudo determinar la duración del segmento.")
            return

        if self._video_duration <= 0:
            QMessageBox.warning(self, "Sin video", "Primero selecciona un video.")
            return

        if segment_duration > self._video_duration:
            QMessageBox.warning(self, "Segmento muy largo",
                                f"La duración del segmento ({segment_duration:.1f}s) es mayor que la del video ({self._video_duration:.1f}s).\n"
                                "Se usará todo el video.")
            segment_duration = self._video_duration

        current_position = self._normalize_duration(
            getattr(self.video_timeline, 'current_position', 0)
        )
        new_start = current_position
        new_end = new_start + segment_duration

        if new_end > self._video_duration:
            new_end = self._video_duration
            new_start = max(0.0, self._video_duration - segment_duration)

        self.video_crop_start.setValue(new_start)
        self.video_crop_end.setValue(new_end)
        self.video_timeline.set_crop_range(new_start, new_end)
        print(f" Recorte ajustado a duración del segmento: {new_start:.1f}s - {new_end:.1f}s ({segment_duration:.1f}s)")

    # ── Preview / Select ───────────────────────────────────────────

    def preview_selected_video(self):
        """Abre el video en el reproductor del sistema"""
        if self._loaded_video_path and os.path.exists(self._loaded_video_path):
            import subprocess
            try:
                os.startfile(self._loaded_video_path)
            except AttributeError:
                subprocess.Popen(['xdg-open', self._loaded_video_path])
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo abrir el video:\n{e}")

    def accept_video(self):
        """Selecciona el video y aplica recorte si está habilitado"""
        if not self._loaded_video_path or not os.path.exists(self._loaded_video_path):
            QMessageBox.warning(self, "Sin video", "Primero selecciona un archivo de video.")
            return

        video_path = self._loaded_video_path
        video_duration = self._video_duration

        # Verificar si el recorte está habilitado
        crop_enabled = False
        crop_start = 0.0
        crop_end = video_duration

        if self.enable_crop_checkbox.isChecked():
            crop_start = self.video_crop_start.value()
            crop_end = self.video_crop_end.value()

            if crop_start < 0:
                crop_start = 0.0
            if crop_end > video_duration:
                crop_end = video_duration
            if crop_start >= crop_end:
                QMessageBox.warning(self, "Rango Inválido",
                                    f"El tiempo de inicio ({crop_start:.2f}s) debe ser menor que el fin ({crop_end:.2f}s).\n"
                                    "Se usará el video completo.")
            else:
                crop_enabled = True
                print(f"️ Recorte habilitado: {crop_start:.2f}s - {crop_end:.2f}s")

        # Si hay recorte, crear una copia recortada (no modificar el original)
        if crop_enabled:
            try:
                import tempfile
                from moviepy.editor import VideoFileClip

                temp_dir = Path(tempfile.gettempdir()) / "video_optimizer" / "local_video_crops"
                temp_dir.mkdir(parents=True, exist_ok=True)

                stem = Path(video_path).stem
                cropped_filename = f"{stem}_crop_{int(crop_start)}_{int(crop_end)}_{int(time.time())}.mp4"
                cropped_path = str(temp_dir / cropped_filename)

                clip = VideoFileClip(video_path)
                cropped_clip = clip.subclip(crop_start, crop_end)

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
                    video_path = cropped_path
                    print(f"️ Video recortado guardado en: {cropped_path}")
                else:
                    QMessageBox.warning(self, "Advertencia",
                                        "No se pudo recortar el video.\nSe usará el video completo.")
            except Exception as e:
                print(f"️ Error recortando video: {e}")
                QMessageBox.warning(self, "Advertencia",
                                    f"No se pudo recortar el video:\n{e}\n\nSe usará el video completo.")

        # Ajuste de duración vs segmento (si no se recortó)
        if not crop_enabled and self.segment_data:
            segment_duration = self._normalize_duration(self.segment_data.get('duration', 0))
            if segment_duration <= 0:
                s = self._normalize_duration(self.segment_data.get('start', 0))
                e = self._normalize_duration(self.segment_data.get('end', 0))
                if e > s:
                    segment_duration = e - s

            if segment_duration > 0 and video_duration > segment_duration:
                reply = QMessageBox.question(
                    self,
                    "Ajustar Duración",
                    f"El video tiene {video_duration:.1f}s de duración.\n"
                    f"El segmento requiere {segment_duration:.1f}s.\n\n"
                    f"¿Deseas cortar el video a la duración del segmento?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    try:
                        import tempfile
                        from moviepy.editor import VideoFileClip

                        temp_dir = Path(tempfile.gettempdir()) / "video_optimizer" / "local_video_crops"
                        temp_dir.mkdir(parents=True, exist_ok=True)

                        stem = Path(video_path).stem
                        trimmed_path = str(temp_dir / f"{stem}_trim_{int(time.time())}.mp4")

                        clip = VideoFileClip(video_path)
                        trimmed = clip.subclip(0, min(segment_duration, clip.duration))
                        write_kwargs = {'codec': 'libx264', 'audio_codec': 'aac', 'verbose': False, 'logger': None}
                        fps = getattr(clip, 'fps', 0) or 0
                        if fps > 0:
                            write_kwargs['fps'] = float(fps)
                        trimmed.write_videofile(trimmed_path, **write_kwargs)
                        trimmed.close()
                        clip.close()

                        if os.path.exists(trimmed_path) and os.path.getsize(trimmed_path) > 0:
                            video_path = trimmed_path
                            print(f"️ Video cortado a {segment_duration:.1f}s")
                    except Exception as e:
                        print(f"️ Error cortando video: {e}")
                        QMessageBox.warning(self, "Advertencia",
                                            f"No se pudo cortar el video:\n{e}")

        self.selected_video_path = os.path.abspath(video_path)
        print(f" Video local seleccionado: {self.selected_video_path}")
        self.accept()

    # ── Cleanup ────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Limpia recursos al cerrar"""
        self._closing = True
        self.stop_playback()
        self._close_preview_video_clip()
        self._cancel_frame_extraction()
        event.accept()
