"""Select a video region and preview an effect before applying it to a copy."""
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QProcess, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QPen
from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                            QPushButton, QComboBox, QMessageBox, QProgressDialog)
from video_region_effects import preview_frame, export_command


class RegionCanvas(QWidget):
    changed = pyqtSignal()

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.selection = None
        self.origin = None
        self.editable = True
        self.setMinimumSize(480, 300)

    def image_rect(self):
        size = self.pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                      size.width(), size.height())

    def normalized_point(self, point):
        bounds = self.image_rect()
        return (max(0, min(1, (point.x() - bounds.x()) / bounds.width())),
                max(0, min(1, (point.y() - bounds.y()) / bounds.height())))

    def mousePressEvent(self, event):
        if self.editable and event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(event.position()):
            self.origin = self.normalized_point(event.position())

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            x, y = self.origin
            end_x, end_y = self.normalized_point(event.position())
            self.selection = [min(x, end_x), min(y, end_y), abs(end_x - x), abs(end_y - y)]
            self.update()

    def mouseReleaseEvent(self, event):
        if self.origin is not None:
            self.mouseMoveEvent(event)
            self.origin = None
            self.changed.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        bounds = self.image_rect()
        painter.drawPixmap(bounds, self.pixmap, QRectF(self.pixmap.rect()))
        if self.selection and self.editable:
            x, y, w, h = self.selection
            painter.setPen(QPen(Qt.GlobalColor.yellow, 2))
            painter.drawRect(QRectF(bounds.x() + x * bounds.width(), bounds.y() + y * bounds.height(),
                                   w * bounds.width(), h * bounds.height()))

class VideoRegionEditor(QDialog):
    def __init__(self, source, seconds=0, edit=None, parent=None):
        super().__init__(parent)
        self.source, self.seconds = source, seconds
        self.edit = None
        self.setWindowTitle('Cubrir o quitar marca de agua')
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        instructions = QLabel('Arrastra un rectángulo sobre la marca. La zona se aplicará durante todo el extracto.\n'
                              'Quitar intenta rellenar con píxeles vecinos; revisa el resultado antes de usarlo.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.original = QPixmap()
        if not self.original.loadFromData(preview_frame(source, seconds)):
            raise RuntimeError('No se pudo mostrar el fotograma.')
        self.canvas = RegionCanvas(self.original)
        self.canvas.selection = list(edit['rect']) if edit else None
        layout.addWidget(self.canvas, 1)
        self.mode = QComboBox()
        for label, key in [('Cubrir con negro', 'cover'), ('Difuminar', 'blur'), ('Quitar (relleno aproximado)', 'remove')]:
            self.mode.addItem(label, key)
        if edit:
            self.mode.setCurrentIndex(max(0, self.mode.findData(edit['mode'])))
        self.mode.currentIndexChanged.connect(self.show_original)
        layout.addWidget(self.mode)
        row = QHBoxLayout()
        for label, action in [('Ver original / seleccionar zona', self.show_original),
                              ('Vista previa del efecto', self.preview), ('Usar esta zona', self.use_region),
                              ('Cancelar', self.reject)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            row.addWidget(button)
        layout.addLayout(row)

    def config(self):
        if not self.canvas.selection:
            raise ValueError('Dibuja primero un rectángulo sobre la marca.')
        return {'mode': self.mode.currentData(), 'rect': list(self.canvas.selection)}

    def show_original(self, *_):
        self.canvas.pixmap = self.original
        self.canvas.editable = True
        self.canvas.update()

    def preview(self):
        try:
            pixmap = QPixmap()
            pixmap.loadFromData(preview_frame(self.source, self.seconds, self.config()))
            self.canvas.pixmap = pixmap
            self.canvas.editable = False
            self.canvas.update()
            return True
        except Exception as exc:
            QMessageBox.warning(self, 'Revisar zona', str(exc))
            return False

    def use_region(self):
        if self.preview():
            self.edit = self.config()
            self.accept()


def export_region_copy(source, edit, parent=None):
    """Run FFmpeg while keeping Qt responsive; cancellation never selects the source."""
    args, output = export_command(source, edit)
    progress = QProgressDialog('Aplicando efecto al extracto…', 'Cancelar', 0, 0, parent)
    progress.setWindowTitle('Editar video')
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)
    process = QProcess(progress)
    errors = bytearray()
    process.readyReadStandardError.connect(lambda: errors.extend(bytes(process.readAllStandardError())))
    process.finished.connect(lambda *_: progress.accept())
    process.errorOccurred.connect(lambda *_: progress.reject())
    progress.canceled.connect(process.kill)
    QTimer.singleShot(0, lambda: process.start('ffmpeg', args))
    progress.exec()
    cancelled = progress.wasCanceled()
    if process.state() != QProcess.ProcessState.NotRunning:
        process.kill()
        process.waitForFinished(3000)
    if cancelled or process.exitStatus() != QProcess.ExitStatus.NormalExit or process.exitCode() != 0 or not output.exists():
        output.unlink(missing_ok=True)
        raise RuntimeError('Edición cancelada.' if cancelled else
                           errors.decode('utf-8', 'replace')[-1500:] or process.errorString())
    return str(output)
