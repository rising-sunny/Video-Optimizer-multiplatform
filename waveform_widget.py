# waveform_widget.py
"""
Widget personalizado para mostrar la forma de onda del audio
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen


class WaveformWidget(QWidget):
    """Widget personalizado para mostrar la forma de onda del audio"""

    # Señal emitida cuando cambia el rango de recorte
    crop_range_changed = pyqtSignal(float, float)  # (start_time, end_time)
    # Señal emitida cuando se hace clic para cambiar la posición de reproducción
    position_clicked = pyqtSignal(float)  # (position_in_seconds)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Lista de valores de amplitud normalizados (0-1)
        self.waveform_data = []
        self.start_time = 0.0  # Tiempo de inicio seleccionado (segundos)
        self.end_time = 0.0  # Tiempo de fin seleccionado (segundos)
        self.duration = 0.0  # Duración total del audio (segundos)
        # Posición actual de reproducción (segundos)
        self.current_position = 0.0
        self.setMinimumHeight(100)
        self.setMaximumHeight(150)
        self.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #3d3d3d; border-radius: 4px;")

        # Variables para arrastre
        self.dragging = None  # 'start', 'end', o None
        self.drag_threshold = 5  # Píxeles de tolerancia para detectar click en línea
        self.start_x = 0
        self.end_x = 0
        self.line_width = 3
        self.setMouseTracking(True)  # Para detectar hover

    def set_current_position(self, position):
        """Establece la posición actual de reproducción"""
        self.current_position = max(0.0, min(position, self.duration))
        self.update()

    def set_waveform_data(self, waveform_data, duration):
        """Establece los datos de la forma de onda"""
        self.waveform_data = waveform_data
        self.duration = duration
        if self.end_time == 0.0 or self.end_time > duration:
            self.end_time = duration
        self.update()

    def set_crop_range(self, start_time, end_time):
        """Establece el rango de recorte"""
        self.start_time = max(0.0, min(start_time, self.duration))
        self.end_time = max(self.start_time, min(end_time, self.duration))
        self.update()

    def paintEvent(self, event):
        """Dibuja la forma de onda"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        if not self.waveform_data or self.duration == 0:
            # Dibujar mensaje de "sin datos"
            painter.setPen(QColor(100, 100, 100))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Cargando forma de onda...")
            return

        # Color de fondo
        painter.fillRect(self.rect(), QColor(26, 26, 26))

        # Dibujar área de recorte (sombreada)
        if self.start_time > 0 or self.end_time < self.duration:
            start_x = int((self.start_time / self.duration)
                          * width) if self.duration > 0 else 0
            end_x = int((self.end_time / self.duration) *
                        width) if self.duration > 0 else width

            # Área antes del inicio (sombreada)
            if start_x > 0:
                painter.fillRect(
                    0, 0, start_x, height, QColor(50, 50, 50, 150))

            # Área después del fin (sombreada)
            if end_x < width:
                painter.fillRect(
                    end_x, 0, width - end_x, height, QColor(50, 50, 50, 150))

            # Líneas de marcadores de inicio y fin (más gruesas para facilitar el arrastre)
            self.line_width = 3
            painter.setPen(QPen(QColor(255, 200, 0), self.line_width))
            painter.drawLine(start_x, 0, start_x, height)
            painter.drawLine(end_x, 0, end_x, height)

            # Guardar posiciones para detección de clicks
            self.start_x = start_x
            self.end_x = end_x

        # Dibujar forma de onda
        if len(self.waveform_data) > 0:
            center_y = height // 2
            samples = len(self.waveform_data)
            x_step = width / samples if samples > 0 else 0

            painter.setPen(QPen(QColor(76, 175, 80), 1))

            for i, amplitude in enumerate(self.waveform_data):
                x = int(i * x_step)
                # Normalizar amplitud a la altura disponible
                # Dejar margen arriba y abajo
                bar_height = int(amplitude * (height - 20) / 2)

                # Dibujar línea desde el centro hacia arriba y abajo
                painter.drawLine(x, center_y - bar_height,
                                 x, center_y + bar_height)

        # Dibujar línea de posición actual de reproducción
        if self.duration > 0 and self.current_position >= 0:
            position_x = int(
                (self.current_position / self.duration) * width) if self.duration > 0 else 0
            painter.setPen(QPen(QColor(33, 150, 243), 2))  # Azul brillante
            painter.drawLine(position_x, 0, position_x, height)

    def mousePressEvent(self, event):
        """Detecta cuando se hace click en una línea de recorte o en la forma de onda"""
        if not self.waveform_data or self.duration == 0:
            return

        if event.button() == Qt.MouseButton.LeftButton:
            x = event.position().x()
            width = self.width()

            # Calcular posiciones de las líneas
            start_x = int((self.start_time / self.duration)
                          * width) if self.duration > 0 else 0
            end_x = int((self.end_time / self.duration) *
                        width) if self.duration > 0 else width

            # Detectar si el click está cerca de alguna línea de recorte
            if abs(x - start_x) <= self.drag_threshold:
                self.dragging = 'start'
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif abs(x - end_x) <= self.drag_threshold:
                self.dragging = 'end'
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                # Click en la forma de onda (no cerca de las líneas de recorte)
                # Convertir posición X a tiempo y emitir señal para cambiar posición de reproducción
                new_time = (x / width) * self.duration if width > 0 else 0
                new_time = max(0.0, min(new_time, self.duration))
                self.position_clicked.emit(new_time)
                self.dragging = None

    def mouseMoveEvent(self, event):
        """Detecta el arrastre de las líneas"""
        if not self.waveform_data or self.duration == 0:
            return

        if self.dragging:
            x = event.position().x()
            width = self.width()

            # Convertir posición X a tiempo
            new_time = (x / width) * self.duration if width > 0 else 0
            new_time = max(0.0, min(new_time, self.duration))

            if self.dragging == 'start':
                # Asegurar que inicio < fin
                if new_time >= self.end_time:
                    new_time = max(0.0, self.end_time - 0.1)
                self.start_time = new_time
            elif self.dragging == 'end':
                # Asegurar que fin > inicio
                if new_time <= self.start_time:
                    new_time = min(self.duration, self.start_time + 0.1)
                self.end_time = new_time

            # Actualizar visualización
            self.update()

            # Emitir señal para actualizar los spinboxes
            self.crop_range_changed.emit(self.start_time, self.end_time)
        else:
            # Cambiar cursor cuando está cerca de una línea
            x = event.position().x()
            width = self.width()
            start_x = int((self.start_time / self.duration)
                          * width) if self.duration > 0 else 0
            end_x = int((self.end_time / self.duration) *
                        width) if self.duration > 0 else width

            if abs(x - start_x) <= self.drag_threshold or abs(x - end_x) <= self.drag_threshold:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """Detecta cuando se suelta el mouse"""
        if self.dragging:
            self.dragging = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

