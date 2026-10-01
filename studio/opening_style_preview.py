# -*- coding: utf-8 -*-
"""Vista previa animada y liviana para los estilos de entrada del video."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from pipeline.video_opening import (
    ARTIFACT_REVEAL_STYLE,
    BEFORE_AFTER_STYLE,
    MAP_ZOOM_STYLE,
    OPENING_STYLE,
    OUTCOME_TEASER_STYLE,
    normalize_opening_style,
)


@lru_cache(maxsize=1)
def _preview_font_family():
    candidates = (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/georgia.ttf",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf",
        Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    )
    for path in candidates:
        if path.is_file():
            font_id = QFontDatabase.addApplicationFont(str(path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                return families[0]
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family() or "serif"


class OpeningStylePreview(QWidget):
    """Miniatura vertical en bucle; equivale a un GIF pero se dibuja en vivo."""

    LOOP_SECONDS = 3.2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._style = OPENING_STYLE
        self._elapsed = 0.0
        self.setMinimumSize(190, 292)
        self.setMaximumWidth(230)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setToolTip("Vista previa en bucle de los primeros segundos del video")
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def sizeHint(self):
        return QSize(210, 310)

    @property
    def style_id(self):
        return self._style

    def set_style(self, style):
        selected = normalize_opening_style(style)
        if selected != self._style:
            self._style = selected
            self._elapsed = 0.0
        self.update()

    def set_phase(self, phase):
        """Fija la fase 0..1; util para pruebas y capturas estaticas."""
        self._elapsed = (float(phase) % 1.0) * self.LOOP_SECONDS
        self.update()

    def _tick(self):
        self._elapsed = (self._elapsed + self._timer.interval() / 1000.0) % self.LOOP_SECONDS
        self.update()

    def _phase(self):
        return self._elapsed / self.LOOP_SECONDS

    @staticmethod
    def _ease_out(value):
        value = max(0.0, min(1.0, value))
        return 1.0 - (1.0 - value) ** 3

    def _video_rect(self):
        outer = self.rect().adjusted(8, 8, -8, -8)
        height = float(outer.height())
        width = min(float(outer.width()), height * 9.0 / 16.0)
        left = outer.center().x() - width / 2.0
        return QRectF(left, float(outer.top()), width, height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#eef1f4"))

        frame = self._video_rect()
        painter.setPen(QPen(QColor("#c8ced5"), 1))
        painter.setBrush(QColor("#10151b"))
        painter.drawRoundedRect(frame, 5, 5)
        painter.save()
        painter.setClipRect(frame.adjusted(1, 1, -1, -1))

        phase = self._phase()
        if self._style == MAP_ZOOM_STYLE:
            self._paint_map(painter, frame, phase)
        elif self._style == ARTIFACT_REVEAL_STYLE:
            self._paint_artifact(painter, frame, phase)
        elif self._style == BEFORE_AFTER_STYLE:
            self._paint_before_after(painter, frame, phase)
        elif self._style == OUTCOME_TEASER_STYLE:
            self._paint_outcome(painter, frame, phase)
        else:
            self._paint_cold_open(painter, frame, phase)

        self._paint_hook(painter, frame, phase)
        self._paint_progress(painter, frame, phase)
        painter.restore()

    def _paint_cold_open(self, painter, r, phase):
        t = self._ease_out(min(1.0, phase * 2.0))
        painter.fillRect(r, QColor("#17222a"))
        horizon = r.top() + r.height() * 0.66
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#243843"))
        painter.drawRect(QRectF(r.left(), horizon, r.width(), r.bottom() - horizon))
        for idx, height in enumerate((0.18, 0.29, 0.23, 0.34, 0.20)):
            width = r.width() * 0.18
            left = r.left() + idx * r.width() * 0.19
            painter.setBrush(QColor("#0a0f13"))
            painter.drawRect(QRectF(left, horizon - r.height() * height, width, r.height() * height))

        cx = r.center().x()
        cy = r.top() + r.height() * (0.59 - 0.04 * t)
        scale = 1.0 + 0.22 * t
        painter.setBrush(QColor("#c7a96d"))
        painter.drawEllipse(QPointF(cx, cy - 18 * scale), 8 * scale, 8 * scale)
        painter.setBrush(QColor("#090d10"))
        painter.drawRoundedRect(QRectF(cx - 11 * scale, cy - 11 * scale, 22 * scale, 48 * scale), 5, 5)
        painter.setPen(QPen(QColor("#d6b979"), 2))
        painter.drawLine(QPointF(r.left() + 12, r.top() + r.height() * 0.47),
                         QPointF(r.right() - 12, r.top() + r.height() * 0.47))

    def _paint_map(self, painter, r, phase):
        t = self._ease_out(min(1.0, phase * 1.8))
        painter.fillRect(r, QColor("#182129"))
        painter.save()
        center = r.center()
        scale = 1.0 + 1.15 * t
        painter.translate(center)
        painter.scale(scale, scale)
        painter.translate(-center)
        painter.setPen(QPen(QColor("#77958c"), 1.2))
        for offset in (0.18, 0.29, 0.42, 0.56, 0.70):
            path = QPainterPath()
            x0 = r.left() + r.width() * 0.06
            y0 = r.top() + r.height() * offset
            path.moveTo(x0, y0)
            path.cubicTo(r.left() + r.width() * 0.28, y0 - 22,
                         r.left() + r.width() * 0.55, y0 + 28,
                         r.right() - r.width() * 0.05, y0 - 5)
            painter.drawPath(path)
        painter.setPen(QPen(QColor("#9c8157"), 2))
        route = QPainterPath(QPointF(r.left() + r.width() * 0.22, r.bottom() - r.height() * 0.18))
        route.cubicTo(r.left() + r.width() * 0.40, r.top() + r.height() * 0.62,
                      r.left() + r.width() * 0.46, r.top() + r.height() * 0.42,
                      r.left() + r.width() * 0.69, r.top() + r.height() * 0.38)
        painter.drawPath(route)
        target = QPointF(r.left() + r.width() * 0.69, r.top() + r.height() * 0.38)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(target, 8, 8)
        painter.drawEllipse(target, 3, 3)
        painter.restore()

    def _paint_artifact(self, painter, r, phase):
        t = self._ease_out(min(1.0, phase * 1.8))
        painter.fillRect(r, QColor("#090c0e"))
        beam = QPainterPath()
        beam.moveTo(r.center().x(), r.top() + r.height() * 0.08)
        beam.lineTo(r.left() + r.width() * 0.18, r.bottom())
        beam.lineTo(r.right() - r.width() * 0.18, r.bottom())
        beam.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(70, 62, 46, int(80 + 80 * t)))
        painter.drawPath(beam)

        scale = 1.42 - 0.38 * t
        cx, base = r.center().x(), r.top() + r.height() * 0.78
        painter.setBrush(QColor("#9b7a48"))
        painter.setPen(QPen(QColor("#d2b47d"), 1.3))
        painter.drawRoundedRect(QRectF(cx - 27 * scale, base - 92 * scale,
                                      54 * scale, 92 * scale), 9, 9)
        painter.setPen(QPen(QColor("#4e3b25"), 1))
        for y in (0.22, 0.40, 0.58):
            painter.drawLine(QPointF(cx - 17 * scale, base - 92 * scale + 92 * scale * y),
                             QPointF(cx + 17 * scale, base - 92 * scale + 92 * scale * y))
        painter.setPen(Qt.PenStyle.NoPen)
        for idx in range(13):
            x = r.left() + (idx * 37 % max(1, int(r.width())))
            y = r.top() + ((idx * 61 + phase * 70) % max(1, int(r.height())))
            painter.setBrush(QColor(226, 204, 157, 80 + (idx % 3) * 35))
            painter.drawEllipse(QPointF(x, y), 1.2, 1.2)

    def _paint_before_after(self, painter, r, phase):
        t = self._ease_out(min(1.0, phase * 1.7))
        painter.fillRect(r, QColor("#2a3338"))
        split = r.left() + r.width() * (0.18 + 0.64 * t)
        old = QRectF(r.left(), r.top(), split - r.left(), r.height())
        new = QRectF(split, r.top(), r.right() - split, r.height())
        painter.fillRect(old, QColor("#596268"))
        painter.fillRect(new, QColor("#193344"))
        ground = r.top() + r.height() * 0.76
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#24292c"))
        painter.drawRect(QRectF(r.left(), ground, r.width(), r.bottom() - ground))

        # Misma arquitectura, ruina a la izquierda y reconstruccion a la derecha.
        for x_ratio in (0.16, 0.40, 0.64, 0.84):
            x = r.left() + r.width() * x_ratio
            col_top = r.top() + r.height() * (0.48 if x < split else 0.34)
            painter.setBrush(QColor("#9b927e") if x < split else QColor("#d0c49e"))
            painter.drawRect(QRectF(x - 5, col_top, 10, ground - col_top))
        painter.setPen(QPen(QColor("#efe2b5"), 2))
        painter.drawLine(QPointF(split, r.top()), QPointF(split, r.bottom()))
        painter.setBrush(QColor("#efe2b5"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(split, r.top() + 18), 3, 3)

    def _paint_outcome(self, painter, r, phase):
        flash = phase < 0.10 or 0.47 < phase < 0.54
        painter.fillRect(r, QColor("#e7dfcf") if flash else QColor("#111820"))
        if flash:
            return
        t = self._ease_out(min(1.0, max(0.0, phase - 0.10) * 2.4))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5d2521"))
        painter.drawRect(QRectF(r.left(), r.top() + r.height() * 0.70, r.width(), r.height() * 0.30))
        cx = r.center().x()
        painter.setBrush(QColor("#090c10"))
        painter.drawEllipse(QPointF(cx, r.top() + r.height() * (0.50 - 0.03 * t)), 25 + 9 * t, 25 + 9 * t)
        painter.drawRect(QRectF(cx - 18 - 7 * t, r.top() + r.height() * 0.51,
                                36 + 14 * t, r.height() * 0.28))
        painter.setPen(QPen(QColor("#b96a4f"), 2))
        for idx in range(5):
            y = r.top() + r.height() * (0.24 + idx * 0.07)
            painter.drawLine(QPointF(r.left() + 10 + idx * 3, y),
                             QPointF(r.right() - 14, y - 18))

    def _paint_hook(self, painter, r, phase):
        if self._style == MAP_ZOOM_STYLE:
            text = "AQUÍ COMENZÓ"
        elif self._style == ARTIFACT_REVEAL_STYLE:
            text = "EL OBJETO PERDIDO"
        elif self._style == BEFORE_AFTER_STYLE:
            text = "2.000 AÑOS DESPUÉS"
        elif self._style == OUTCOME_TEASER_STYLE:
            text = "ASÍ TERMINÓ"
        else:
            text = "50.000 SOLDADOS"

        alpha = 255 if phase < 0.72 else max(0, int(255 * (1.0 - phase) / 0.28))
        if self._style == OUTCOME_TEASER_STYLE and phase < 0.10:
            alpha = 0
        painter.setPen(QColor(242, 235, 221, alpha))
        font = QFont(_preview_font_family())
        font.setPixelSize(max(10, int(r.width() * 0.082)))
        font.setBold(True)
        painter.setFont(font)
        title = QRectF(r.left() + 9, r.top() + r.height() * 0.10, r.width() - 18, r.height() * 0.18)
        painter.drawText(title, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)
        painter.setPen(QPen(QColor(205, 181, 138, alpha), 2))
        y = r.top() + r.height() * 0.25
        half = r.width() * 0.10
        painter.drawLine(QPointF(r.center().x() - half, y), QPointF(r.center().x() + half, y))

    def _paint_progress(self, painter, r, phase):
        bar = QRectF(r.left() + 8, r.bottom() - 8, r.width() - 16, 2)
        painter.fillRect(bar, QColor(255, 255, 255, 55))
        painter.fillRect(QRectF(bar.left(), bar.top(), bar.width() * phase, bar.height()), QColor("#cdb58a"))

