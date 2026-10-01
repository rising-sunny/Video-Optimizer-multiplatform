# timeline_video_widget.py
"""
Widget personalizado para mostrar timeline de video con barras de recorte.
Extraído de timeline_editor_widget.py para mejorar la organización del código.
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap
from PyQt6.QtCore import QPoint
import os


class VideoTimelineWidget(QWidget):
    """Widget personalizado para mostrar timeline de video con barras de recorte"""

    # Señal emitida cuando cambia el rango de recorte
    crop_range_changed = pyqtSignal(float, float)  # (start_time, end_time)
    # Señal emitida cuando se hace clic para cambiar la posición de reproducción
    position_clicked = pyqtSignal(float)  # (position_in_seconds)
    # Señal emitida cuando el usuario arrastra la barra de posición
    position_dragged = pyqtSignal(float)  # (position_in_seconds)
    # Señal para solicitar reproducción del tramo recortado
    play_crop_range_requested = pyqtSignal(float, float)  # (start_time, end_time)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_time = 0.0  # Tiempo de inicio seleccionado (segundos)
        self.end_time = 0.0  # Tiempo de fin seleccionado (segundos)
        self.duration = 0.0  # Duración total del video (segundos)
        self.current_position = 0.0  # Posición actual de reproducción (segundos)

        self.setMinimumHeight(120)
        self.setMaximumHeight(150)
        self.setObjectName("videoPreview")

        # Variables para arrastre
        self.dragging = None  # 'start', 'end', 'position', o None
        self.drag_threshold = 8  # Píxeles de tolerancia para detectar click en línea
        self.position_drag_threshold = 10  # Umbral mayor para la barra de posición (más fácil de agarrar)
        self.start_x = 0
        self.end_x = 0
        self.position_x = 0  # Posición X de la barra azul
        self.line_width = 4
        self._range_drag_activation_px = 6  # Distancia minima para considerar arrastre del rango
        self.setMouseTracking(True)  # Para detectar hover

        # Frames del video para mostrar en el timeline (thumbnails)
        self.video_frames = []  # Lista de QPixmap con frames del video

        # Mensaje de carga
        self._loading_message = None
    
    def set_video_duration(self, duration):
        """Establece la duración del video"""
        self.duration = duration
        if self.end_time == 0.0 or self.end_time > duration:
            self.end_time = duration
        self.update()
    
    def set_current_position(self, position):
        """Establece la posición actual de reproducción"""
        self.current_position = max(0.0, min(position, self.duration))
        self.update()
    
    def set_crop_range(self, start_time, end_time):
        """Establece el rango de recorte"""
        self.start_time = max(0.0, min(start_time, self.duration))
        self.end_time = max(self.start_time, min(end_time, self.duration))
        self.update()

    def set_video_frames(self, frames):
        """Establece los frames del video directamente (lista de QPixmap)"""
        self.video_frames = frames if frames else []
        self.update()

    def set_loading_message(self, message):
        """Muestra un mensaje de carga en el timeline"""
        self._loading_message = message
        self.update()

    def clear_loading_message(self):
        """Limpia el mensaje de carga"""
        self._loading_message = None
        self.update()

    def load_video_frames(self, video_path, num_frames=20):
        """Carga frames del video para mostrar en el timeline"""
        try:
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(video_path)
            self.duration = clip.duration
            
            # Extraer frames distribuidos uniformemente
            self.video_frames = []
            if self.duration > 0:
                frame_times = [i * self.duration / num_frames for i in range(num_frames)]
                for t in frame_times:
                    frame = clip.get_frame(t)
                    from PIL import Image
                    import numpy as np
                    pil_image = Image.fromarray(frame.astype('uint8'), 'RGB')
                    # Convertir a QPixmap
                    import tempfile
                    temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
                    os.close(temp_fd)
                    pil_image.save(temp_path, 'JPEG')
                    pixmap = QPixmap(temp_path)
                    os.remove(temp_path)
                    self.video_frames.append(pixmap)
            
            clip.close()
            self.update()
        except Exception as e:
            print(f"️ Error cargando frames del video: {e}")
            self.video_frames = []
    
    def paintEvent(self, event):
        """Dibuja el timeline del video"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        if self.duration == 0:
            # Dibujar mensaje de "sin datos"
            painter.setPen(QColor(100, 100, 100))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Selecciona un video para ver el timeline")
            return

        # Color de fondo
        painter.fillRect(self.rect(), QColor(26, 26, 26))

        # Mostrar mensaje de carga si existe
        if self._loading_message:
            painter.setPen(QColor(255, 200, 0))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._loading_message)

        # Dibujar frames del video como thumbnails
        if self.video_frames:
            num_frames = len(self.video_frames)
            frame_width = width / num_frames if num_frames > 0 else 0
            thumbnail_height = height - 30  # Dejar espacio para las barras
            
            for i, pixmap in enumerate(self.video_frames):
                if not pixmap.isNull():
                    x = int(i * frame_width)
                    scaled_pixmap = pixmap.scaled(
                        int(frame_width), thumbnail_height,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    painter.drawPixmap(x, 0, scaled_pixmap)
        
        # Calcular posiciones de las barras de recorte
        start_x = int((self.start_time / self.duration) * width) if self.duration > 0 else 0
        end_x = int((self.end_time / self.duration) * width) if self.duration > 0 else width

        # Dibujar área de recorte (sombreada) si hay recorte activo
        if self.start_time > 0 or self.end_time < self.duration:
            # Área antes del inicio (sombreada)
            if start_x > 0:
                painter.fillRect(0, 0, start_x, height, QColor(50, 50, 50, 180))

            # Área después del fin (sombreada)
            if end_x < width:
                painter.fillRect(end_x, 0, width - end_x, height, QColor(50, 50, 50, 180))

            # Dibujar borde del área seleccionada (para indicar que es arrastrable)
            crop_rect_color = QColor(255, 200, 0, 60)  # Amarillo semi-transparente
            if getattr(self, 'dragging', None) == 'range':
                crop_rect_color = QColor(255, 200, 0, 100)  # Más visible al arrastrar
            painter.fillRect(start_x, height - 8, end_x - start_x, 8, crop_rect_color)

        # Siempre dibujar las barras de marcadores de inicio y fin
        painter.setPen(QPen(QColor(255, 200, 0), self.line_width))
        painter.drawLine(start_x, 0, start_x, height)
        painter.drawLine(end_x - 1, 0, end_x - 1, height)  # -1 para que se vea dentro del widget

        # Dibujar triángulos en la parte superior de las barras para indicar que son arrastrables
        triangle_size = 8
        # Triángulo inicio
        painter.setBrush(QColor(255, 200, 0))
        painter.setPen(QPen(QColor(255, 200, 0), 1))
        start_points = [
            QPoint(start_x, 0),
            QPoint(start_x - triangle_size, triangle_size),
            QPoint(start_x + triangle_size, triangle_size)
        ]
        painter.drawPolygon(start_points)
        # Triángulo fin
        end_points = [
            QPoint(end_x - 1, 0),
            QPoint(end_x - 1 - triangle_size, triangle_size),
            QPoint(end_x - 1 + triangle_size, triangle_size)
        ]
        painter.drawPolygon(end_points)

        # Guardar posiciones para detección de clicks
        self.start_x = start_x
        self.end_x = end_x

        # Dibujar línea de posición actual de reproducción (barra vertical azul)
        if self.duration > 0 and self.current_position >= 0:
            position_x = int((self.current_position / self.duration) * width) if self.duration > 0 else 0
            self.position_x = position_x  # Guardar para detección de arrastre
            painter.setPen(QPen(QColor(33, 150, 243), 3))  # Azul brillante
            painter.drawLine(position_x, 0, position_x, height)

            # Dibujar círculo/cabezal en la parte superior (más grande para facilitar arrastre)
            painter.setBrush(QColor(33, 150, 243))
            painter.setPen(QPen(QColor(255, 255, 255), 2))  # Borde blanco para destacar
            painter.drawEllipse(position_x - 8, 0, 16, 16)  # Círculo más grande
    
    def mousePressEvent(self, event):
        """Detecta cuando se hace click en una línea de recorte, barra de posición o timeline"""
        if self.duration == 0:
            return

        if event.button() == Qt.MouseButton.LeftButton:
            x = event.position().x()
            y = event.position().y()
            width = self.width()
            height = self.height()

            # Calcular posiciones de las líneas
            start_x = int((self.start_time / self.duration) * width) if self.duration > 0 else 0
            end_x = int((self.end_time / self.duration) * width) if self.duration > 0 else width
            position_x = int((self.current_position / self.duration) * width) if self.duration > 0 else 0

            # Prioridad: barra azul de posición (más fácil de agarrar)
            if abs(x - position_x) <= self.position_drag_threshold:
                self.dragging = 'position'
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            # Detectar si el click está dentro del área de recorte (para mover todo el rango)
            # Esto tiene prioridad sobre las barras individuales para facilitar el arrastre del rango completo
            elif start_x <= x <= end_x and (self.start_time > 0 or self.end_time < self.duration):
                # Click dentro del área de recorte - mover todo el rango
                # Incluir también un pequeño margen alrededor de las barras para facilitar el agarre
                margin = max(5, (end_x - start_x) * 0.1)  # 10% del ancho del recorte o mínimo 5px
                if start_x - margin <= x <= end_x + margin:
                    # Activar arrastre de rango solo si hay movimiento real.
                    # Un click simple dentro del rango debe mover la barra azul.
                    self.dragging = 'range_candidate'
                    self._drag_start_x = x  # Guardar posición inicial del mouse
                    self._range_duration = self.end_time - self.start_time  # Duración del rango
                    self._drag_start_time = self.start_time  # Guardar tiempo inicial para cálculo más preciso
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                    self.update()
                # Si está muy cerca de las barras (dentro del umbral pequeño), permitir ajuste individual
                elif abs(x - start_x) <= self.drag_threshold:
                    self.dragging = 'start'
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif abs(x - end_x) <= self.drag_threshold:
                    self.dragging = 'end'
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
            # Detectar si el click está cerca de alguna línea de recorte (fuera del área de recorte)
            elif abs(x - start_x) <= self.drag_threshold:
                self.dragging = 'start'
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif abs(x - end_x) <= self.drag_threshold:
                self.dragging = 'end'
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                # Click en el timeline (fuera del área de recorte)
                # Convertir posición X a tiempo y emitir señal para cambiar posición de reproducción
                new_time = (x / width) * self.duration if width > 0 else 0
                new_time = max(0.0, min(new_time, self.duration))
                self.current_position = new_time
                self.update()
                self.position_clicked.emit(new_time)
                self.dragging = None
    
    def mouseMoveEvent(self, event):
        """Detecta el arrastre de las líneas"""
        if self.duration == 0:
            return

        if self.dragging:
            x = event.position().x()
            width = self.width()

            # Convertir posición X a tiempo
            new_time = (x / width) * self.duration if width > 0 else 0
            new_time = max(0.0, min(new_time, self.duration))

            if self.dragging == 'range_candidate':
                # Solo activar arrastre de rango cuando hay desplazamiento real.
                delta_x = abs(x - getattr(self, '_drag_start_x', x))
                if delta_x >= self._range_drag_activation_px:
                    self.dragging = 'range'
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    return

            if self.dragging == 'position':
                # Arrastre de la barra azul de posición
                self.current_position = new_time
                self.update()
                # Emitir señal para actualizar la reproducción
                self.position_dragged.emit(new_time)
            elif self.dragging == 'start':
                # Asegurar que inicio < fin
                if new_time >= self.end_time:
                    new_time = max(0.0, self.end_time - 0.1)
                self.start_time = new_time
                self.update()
                # Emitir señal para actualizar los spinboxes
                self.crop_range_changed.emit(self.start_time, self.end_time)
            elif self.dragging == 'end':
                # Asegurar que fin > inicio
                if new_time <= self.start_time:
                    new_time = min(self.duration, self.start_time + 0.1)
                self.end_time = new_time
                self.update()
                # Emitir señal para actualizar los spinboxes
                self.crop_range_changed.emit(self.start_time, self.end_time)
            elif self.dragging == 'range':
                # Arrastre de todo el rango de recorte
                range_duration = getattr(self, '_range_duration', self.end_time - self.start_time)
                drag_start_x = getattr(self, '_drag_start_x', x)
                drag_start_time = getattr(self, '_drag_start_time', self.start_time)

                # Calcular el desplazamiento en píxeles y convertir a tiempo
                # Usar la posición inicial guardada para un cálculo más preciso
                delta_x = x - drag_start_x
                delta_time = (delta_x / width) * self.duration if width > 0 else 0

                # Calcular nueva posición de inicio basada en el tiempo inicial guardado
                new_start = drag_start_time + delta_time
                new_end = new_start + range_duration

                # Limitar a los bordes del video
                if new_start < 0:
                    new_start = 0
                    new_end = range_duration
                if new_end > self.duration:
                    new_end = self.duration
                    new_start = self.duration - range_duration

                # Aplicar cambios
                self.start_time = max(0.0, new_start)
                self.end_time = min(self.duration, new_end)

                self.update()
                # Emitir señal para actualizar los spinboxes
                self.crop_range_changed.emit(self.start_time, self.end_time)
        else:
            # Cambiar cursor cuando está cerca de una línea
            x = event.position().x()
            width = self.width()
            start_x = int((self.start_time / self.duration) * width) if self.duration > 0 else 0
            end_x = int((self.end_time / self.duration) * width) if self.duration > 0 else width
            position_x = int((self.current_position / self.duration) * width) if self.duration > 0 else 0

            # Cursor especial para barra de posición o líneas de recorte
            if abs(x - position_x) <= self.position_drag_threshold:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            # Cursor especial para área de recorte (mover todo el rango)
            # Incluir margen alrededor del área de recorte para facilitar el agarre
            elif start_x <= x <= end_x and (self.start_time > 0 or self.end_time < self.duration):
                margin = max(5, (end_x - start_x) * 0.1)  # 10% del ancho del recorte o mínimo 5px
                if start_x - margin <= x <= end_x + margin:
                    # Solo mostrar cursor de mover si no está muy cerca de las barras
                    if abs(x - start_x) > self.drag_threshold and abs(x - end_x) > self.drag_threshold:
                        self.setCursor(Qt.CursorShape.SizeAllCursor)
                    else:
                        self.setCursor(Qt.CursorShape.SizeHorCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
            elif abs(x - start_x) <= self.drag_threshold or abs(x - end_x) <= self.drag_threshold:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """Detecta cuando se suelta el mouse"""
        if self.dragging == 'range_candidate' and self.duration > 0:
            # Click simple dentro del rango recortado: mover barra azul.
            x = event.position().x()
            width = self.width()
            new_time = (x / width) * self.duration if width > 0 else 0
            new_time = max(0.0, min(new_time, self.duration))
            self.current_position = new_time
            self.update()
            self.position_clicked.emit(new_time)

        if self.dragging:
            self.dragging = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
