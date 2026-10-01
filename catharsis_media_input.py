"""Local-file drops and clipboard images for the Catarsis media list."""
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QListWidget, QWidget

from catharsis_editor import VIDEO_EXT

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
IMAGE_MIME_TYPES = ("image/png", "image/jpeg", "image/webp", "image/bmp")


def supported_file(path):
    try:
        p = Path(path)
        return p.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXT and p.is_file()
    except (OSError, ValueError):
        return False


def local_paths(mime):
    if mime is None:
        return []
    if mime.hasUrls():
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
    paths = []
    for line in str(mime.text() or "").splitlines():
        value = line.strip().strip('"')
        url = QUrl(value)
        path = url.toLocalFile() if url.isLocalFile() else value
        if supported_file(path):
            paths.append(path)
    return paths


def can_import(mime):
    if mime is None:
        return False
    paths = local_paths(mime)
    if paths:
        return any(supported_file(path) for path in paths)
    return mime.hasImage() or any(mime.hasFormat(fmt) for fmt in IMAGE_MIME_TYPES)


def image_from_mime(mime):
    if mime.hasImage():
        data = mime.imageData()
        if isinstance(data, QPixmap):
            data = data.toImage()
        if isinstance(data, QImage) and not data.isNull():
            return data.copy()
    for fmt in IMAGE_MIME_TYPES:
        if mime.hasFormat(fmt):
            image = QImage.fromData(mime.data(fmt))
            if not image.isNull():
                return image
    return QImage()


class MediaDropList(QListWidget):
    media_dropped = pyqtSignal(object)
    paste_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.possibleActions() & Qt.DropAction.CopyAction and can_import(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if not event.possibleActions() & Qt.DropAction.CopyAction or not can_import(event.mimeData()):
            event.ignore()
            return
        self.media_dropped.emit(event.mimeData())
        # Never ask the source application to move/delete its original files.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MediaDropArea(QWidget):
    """A scene assignment target; child buttons/combos keep their usual behavior."""
    media_dropped = pyqtSignal(object)
    paste_requested = pyqtSignal()
    dragEnterEvent = MediaDropList.dragEnterEvent
    dragMoveEvent = MediaDropList.dragMoveEvent
    dropEvent = MediaDropList.dropEvent

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)
