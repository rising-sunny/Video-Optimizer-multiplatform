# waveform_widget.py
"""Forma de onda con recorte por barras arrastrables.

Que cambio respecto de la version anterior (2026-09-03):

- Las barras se dibujan SIEMPRE. Antes solo aparecian `if start_time > 0 or
  end_time < duration`, asi que en una pista recien cargada no habia ninguna
  visible y no se podia empezar a recortar con el mouse.
- El margen de agarre paso de 5 px a 12 y cada barra tiene asas visibles
  arriba y abajo, para que se note que se pueden mover.
- Se puede arrastrar el recorte ENTERO desde el interior, conservando su
  largo.
- Sobre la onda se muestran inicio, fin y duracion del recorte.
- El rango nunca queda invertido ni de largo cero.

La matematica vive en `waveform_geometry.py` para poder testearla sin Qt.
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont

from studio.waveform_geometry import (
    GRAB_TOLERANCE_PX,
    MIN_SELECTION_S,
    clamp_range,
    format_timecode,
    hit_test,
    move_region,
    time_to_x,
    x_to_time,
)

# Paleta
_FONDO = QColor(26, 26, 26)
_ONDA = QColor(76, 175, 80)
_ONDA_FUERA = QColor(70, 78, 70)
_VELO = QColor(12, 12, 12, 170)
_BARRA = QColor(255, 200, 0)
_ASA = QColor(255, 214, 51)
_POSICION = QColor(33, 150, 243)
_TEXTO = QColor(235, 235, 235)

_ANCHO_BARRA = 3
_ASA_W, _ASA_H = 9, 20


class WaveformWidget(QWidget):
    """Forma de onda con seleccion de recorte arrastrable."""

    crop_range_changed = pyqtSignal(float, float)   # durante el arrastre
    crop_range_committed = pyqtSignal(float, float)  # al soltar
    position_clicked = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.waveform_data = []
        self.start_time = 0.0
        self.end_time = 0.0
        self.duration = 0.0
        self.current_position = 0.0

        self.setMinimumHeight(120)
        self.setMaximumHeight(170)
        self.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #3d3d3d; border-radius: 4px;")

        self.dragging = None        # 'start' | 'end' | 'region' | None
        self._drag_anchor_s = 0.0   # para mover la region sin saltos
        self.drag_threshold = GRAB_TOLERANCE_PX
        self.setMouseTracking(True)

    # ------------------------------------------------------------- estado

    def set_current_position(self, position):
        self.current_position = max(0.0, min(float(position or 0.0), self.duration))
        self.update()

    def set_waveform_data(self, waveform_data, duration):
        self.waveform_data = waveform_data or []
        self.duration = float(duration or 0.0)
        if self.end_time <= 0.0 or self.end_time > self.duration:
            self.end_time = self.duration
        self.start_time, self.end_time = clamp_range(
            self.start_time, self.end_time, self.duration)
        self.update()

    def set_crop_range(self, start_time, end_time):
        self.start_time, self.end_time = clamp_range(
            start_time, end_time, self.duration)
        self.update()

    def selection_length(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    # ------------------------------------------------------------- dibujo

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if not self.waveform_data or self.duration <= 0:
            painter.setPen(QColor(100, 100, 100))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Cargando forma de onda...")
            return

        painter.fillRect(self.rect(), _FONDO)

        sx = time_to_x(self.start_time, self.duration, w)
        ex = time_to_x(self.end_time, self.duration, w)

        self._dibujar_onda(painter, w, h, sx, ex)

        # Velo sobre lo que queda FUERA del recorte: lo elegido se ve nitido.
        if sx > 0:
            painter.fillRect(0, 0, sx, h, _VELO)
        if ex < w:
            painter.fillRect(ex, 0, w - ex, h, _VELO)

        self._dibujar_posicion(painter, w, h)
        # Las barras van al final para que queden por encima de todo.
        self._dibujar_barra(painter, sx, h)
        self._dibujar_barra(painter, ex, h)
        self._dibujar_etiquetas(painter, w, h, sx, ex)

    def _dibujar_onda(self, painter, w, h, sx, ex):
        centro = h // 2
        muestras = len(self.waveform_data)
        if muestras <= 0:
            return
        paso = w / muestras
        for i, amplitud in enumerate(self.waveform_data):
            x = int(i * paso)
            alto = int(abs(float(amplitud)) * (h - 46) / 2)
            painter.setPen(QPen(_ONDA if sx <= x <= ex else _ONDA_FUERA, 1))
            painter.drawLine(x, centro - alto, x, centro + alto)

    def _dibujar_posicion(self, painter, w, h):
        if self.current_position <= 0:
            return
        px = time_to_x(self.current_position, self.duration, w)
        painter.setPen(QPen(_POSICION, 2))
        painter.drawLine(px, 0, px, h)

    def _dibujar_barra(self, painter, x, h):
        """Una barra con asas arriba y abajo: se nota que se puede arrastrar."""
        painter.setPen(QPen(_BARRA, _ANCHO_BARRA))
        painter.drawLine(x, 0, x, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_ASA))
        for y in (0, h - _ASA_H):
            painter.drawRoundedRect(
                QRectF(x - _ASA_W / 2.0, y, _ASA_W, _ASA_H), 3, 3)
        # Dos ranuras en el asa superior, como los tiradores de siempre.
        painter.setPen(QPen(QColor(60, 45, 0), 1))
        for dx in (-2, 1):
            painter.drawLine(int(x + dx), 5, int(x + dx), 14)

    def _dibujar_etiquetas(self, painter, w, h, sx, ex):
        fuente = QFont()
        fuente.setPointSize(8)
        painter.setFont(fuente)
        painter.setPen(QPen(_TEXTO, 1))

        # Inicio y fin, pegados a su barra y siempre dentro del widget.
        painter.drawText(max(2, min(sx + 5, w - 46)), h - 6,
                         format_timecode(self.start_time))
        painter.drawText(max(2, min(ex - 44, w - 46)), h - 6,
                         format_timecode(self.end_time))

        # Duracion del recorte, centrada arriba.
        largo = self.selection_length()
        if largo > 0:
            texto = "recorte  %s" % format_timecode(largo)
            centro = (sx + ex) // 2
            painter.setPen(QPen(_ASA, 1))
            painter.drawText(max(2, min(centro - 34, w - 74)), 14, texto)

    # ------------------------------------------------------------- mouse

    def mousePressEvent(self, event):
        if not self.waveform_data or self.duration <= 0:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        x = event.position().x()
        objetivo = hit_test(x, self.start_time, self.end_time,
                            self.duration, self.width(), self.drag_threshold)
        if objetivo in ("start", "end"):
            self.dragging = objetivo
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif objetivo == "region":
            self.dragging = "region"
            self._drag_anchor_s = x_to_time(x, self.duration, self.width())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self.dragging = None
            self.position_clicked.emit(
                x_to_time(x, self.duration, self.width()))

    def mouseMoveEvent(self, event):
        if not self.waveform_data or self.duration <= 0:
            return
        x = event.position().x()

        if not self.dragging:
            objetivo = hit_test(x, self.start_time, self.end_time,
                                self.duration, self.width(), self.drag_threshold)
            if objetivo in ("start", "end"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif objetivo == "region":
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        t = x_to_time(x, self.duration, self.width())
        if self.dragging == "start":
            self.start_time, self.end_time = clamp_range(
                min(t, self.end_time - MIN_SELECTION_S), self.end_time, self.duration)
        elif self.dragging == "end":
            self.start_time, self.end_time = clamp_range(
                self.start_time, max(t, self.start_time + MIN_SELECTION_S), self.duration)
        elif self.dragging == "region":
            self.start_time, self.end_time = move_region(
                self.start_time, self.end_time, t - self._drag_anchor_s, self.duration)
            self._drag_anchor_s = t

        self.update()
        self.crop_range_changed.emit(self.start_time, self.end_time)

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.dragging = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            # Una sola senal al soltar: lo caro (recortar y re-codificar) no
            # tiene que correr en cada pixel del arrastre.
            self.crop_range_committed.emit(self.start_time, self.end_time)
