# -*- coding: utf-8 -*-
"""Ventana de vistas previas de estilos de subtitulos, al estilo CapCut.

Muestra la frase de ejemplo animandose de verdad -- con el karaoke, el rebote o
el shake que tenga cada estilo -- y deja recorrer la lista completa antes de
decidir. La animacion sale del motor real de subtitulos, no de un dibujo: ver
`subtitle_style_preview`.

La generacion corre en un hilo: la primera previa de cada estilo cuesta medio
segundo de FFmpeg y bloquear la interfaz por eso se nota.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QVBoxLayout, QWidget,
)

from subtitle_style_preview import (
    GIF_W, SAMPLE_TEXT, build_preview, describe_style, style_key_from_label,
)


class _PreviewWorker(QThread):
    """Genera un GIF sin congelar la ventana."""

    listo = pyqtSignal(str, str)     # (style_key, ruta_gif)
    fallo = pyqtSignal(str, str)     # (style_key, motivo)

    def __init__(self, style_key: str):
        super().__init__()
        self.style_key = style_key

    def run(self):
        try:
            ruta = build_preview(self.style_key)
            if ruta:
                self.listo.emit(self.style_key, ruta)
            else:
                self.fallo.emit(self.style_key,
                                "No se pudo generar la vista previa (¿FFmpeg disponible?)")
        except Exception as exc:
            self.fallo.emit(self.style_key, str(exc)[:200])


class SubtitleStylePreviewDialog(QDialog):
    """Elegir estilo de subtitulos viendo como se anima cada uno."""

    def __init__(self, parent=None, labels: Optional[List[str]] = None,
                 current_label: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Estilos de subtitulos - vista previa")
        self.setMinimumSize(720, 640)

        self._labels: List[str] = list(labels or [])
        self._selected_label: str = current_label or (
            self._labels[0] if self._labels else "")
        self._movie: Optional[QMovie] = None
        self._worker: Optional[_PreviewWorker] = None
        self._cache: Dict[str, str] = {}

        raiz = QVBoxLayout(self)
        raiz.addWidget(QLabel(
            "<b>Elegi un estilo y mira como queda.</b> "
            "La animacion se genera con el mismo motor que usa el video final."))

        cuerpo = QHBoxLayout()

        self.lista = QListWidget()
        self.lista.setMinimumWidth(290)
        for etiqueta in self._labels:
            item = QListWidgetItem(etiqueta)
            item.setData(Qt.ItemDataRole.UserRole, etiqueta)
            self.lista.addItem(item)
        self.lista.currentRowChanged.connect(self._on_row_changed)
        cuerpo.addWidget(self.lista)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 0, 0, 0)

        self.anim = QLabel("Generando vista previa...")
        self.anim.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.anim.setMinimumSize(GIF_W, 520)
        self.anim.setStyleSheet(
            "background-color: #14181d; border: 1px solid #333; border-radius: 6px;"
            "color: #888;")
        panel_layout.addWidget(self.anim, 1)

        self.detalle = QLabel("")
        self.detalle.setWordWrap(True)
        self.detalle.setStyleSheet("color: #9ecbff; font-size: 11px; padding: 6px 2px;")
        panel_layout.addWidget(self.detalle)

        pie = QLabel('Frase de ejemplo: "%s"' % SAMPLE_TEXT)
        pie.setStyleSheet("color: #777; font-size: 10px;")
        panel_layout.addWidget(pie)

        cuerpo.addWidget(panel, 1)
        raiz.addLayout(cuerpo)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Usar este estilo")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        raiz.addWidget(botones)

        if self._labels:
            fila = self._labels.index(self._selected_label) \
                if self._selected_label in self._labels else 0
            self.lista.setCurrentRow(fila)

    # ------------------------------------------------------------------

    @property
    def selected_label(self) -> str:
        return self._selected_label

    def _on_row_changed(self, fila: int):
        if fila < 0 or fila >= len(self._labels):
            return
        self._selected_label = self._labels[fila]
        clave = style_key_from_label(self._selected_label)
        self.detalle.setText(describe_style(clave) or "")

        if clave in self._cache:
            self._mostrar_gif(self._cache[clave])
            return

        self._detener_animacion()
        self.anim.setText("Generando vista previa...")
        self._lanzar_worker(clave)

    def _lanzar_worker(self, clave: str):
        # Un solo worker vivo: al recorrer la lista con las flechas se pedirian
        # muchas previas a la vez y FFmpeg se apilaria.
        if self._worker and self._worker.isRunning():
            try:
                self._worker.listo.disconnect()
                self._worker.fallo.disconnect()
            except Exception:
                pass
        self._worker = _PreviewWorker(clave)
        self._worker.listo.connect(self._on_listo)
        self._worker.fallo.connect(self._on_fallo)
        self._worker.start()

    def _on_listo(self, clave: str, ruta: str):
        self._cache[clave] = ruta
        # Puede haber cambiado la seleccion mientras se generaba.
        if style_key_from_label(self._selected_label) == clave:
            self._mostrar_gif(ruta)

    def _on_fallo(self, clave: str, motivo: str):
        if style_key_from_label(self._selected_label) == clave:
            self.anim.setText("Sin vista previa\n\n%s" % motivo)

    def _mostrar_gif(self, ruta: str):
        self._detener_animacion()
        pelicula = QMovie(ruta)
        if not pelicula.isValid():
            self.anim.setText("No se pudo abrir la vista previa")
            return
        self.anim.setText("")
        self.anim.setMovie(pelicula)
        self._movie = pelicula
        pelicula.start()

    def _detener_animacion(self):
        if self._movie is not None:
            self._movie.stop()
            self.anim.setMovie(None)
            self._movie = None

    def closeEvent(self, event):
        self._detener_animacion()
        if self._worker and self._worker.isRunning():
            self._worker.wait(1500)
        super().closeEvent(event)
