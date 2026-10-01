"""A scrollable overview of the editable Catarsis plan."""
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from catharsis.catharsis_timeline import timecode


class TimelineStrip(QWidget):
    scene_selected = pyqtSignal(int)
    pixels_per_second = 75

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timings, self.pending, self.kinds = [], set(), []
        self.selected = -1
        self.setFixedHeight(66)
        self.setMouseTracking(True)

    def set_plan(self, timings, pending, kinds):
        self.timings, self.pending, self.kinds = timings, set(pending), kinds
        end = timings[-1][1] if timings else 0
        self.setMinimumWidth(max(400, int(end * self.pixels_per_second) + 20))
        self.update()

    def select(self, row):
        self.selected = row
        self.update()

    def scene_at(self, x):
        seconds = (x - 8) / self.pixels_per_second
        return next((i for i, (a, b) in enumerate(self.timings) if a <= seconds < b), -1)

    def mousePressEvent(self, event):
        row = self.scene_at(event.position().x())
        if event.button() == Qt.MouseButton.LeftButton and row >= 0:
            self.scene_selected.emit(row)

    def mouseMoveEvent(self, event):
        row = self.scene_at(event.position().x())
        if row >= 0:
            start, end = self.timings[row]
            status = " · Falta material" if row in self.pending else ""
            self.setToolTip(f"Escena {row + 1} · {timecode(start)}–{timecode(end)}"
                            f" · {end - start:.3f} s{status}")
        else:
            self.setToolTip("")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151c27"))
        painter.setPen(QColor("#b9c6d8"))
        if not self.timings:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Planifica las escenas para ver el montaje")
            return
        clip = event.rect()
        first = max(0, int((clip.left() - 8) / self.pixels_per_second // 5) * 5)
        last = min(int(self.timings[-1][1]) + 1, int(clip.right() / self.pixels_per_second) + 1)
        for sec in range(first, last + 1, 5):
            x = 8 + sec * self.pixels_per_second
            painter.drawText(x, 15, f"{sec // 60:02d}:{sec % 60:02d}")
        for row, (start, end) in enumerate(self.timings):
            rect = QRectF(8 + start * self.pixels_per_second, 24,
                          max(1, (end - start) * self.pixels_per_second - 1), 32)
            if not rect.intersects(QRectF(clip)):
                continue
            color = "#9b6026" if row in self.pending else ("#466688" if self.kinds[row] == "card" else "#267e75")
            painter.fillRect(rect, QColor(color))
            if row == self.selected:
                painter.setPen(QPen(QColor("#ffffff"), 2))
                painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.setPen(QColor("#ffffff"))
            if rect.width() >= 26:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(row + 1))
