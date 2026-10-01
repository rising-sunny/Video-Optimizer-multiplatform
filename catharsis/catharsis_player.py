"""Embedded VLC fallback for installations whose Qt multimedia backend is unavailable."""
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication


class VlcPreviewPlayer(QObject):
    durationChanged = pyqtSignal(int)
    positionChanged = pyqtSignal(int)
    errorOccurred = pyqtSignal()

    def __init__(self, widget, parent=None):
        super().__init__(parent)
        import vlc
        self.vlc = vlc
        options = ["--intf=dummy", "--quiet", "--no-video-title-show",
                   "--no-metadata-network-access", "--no-sub-autodetect-file"]
        # Headless GUI tests must not open a native VLC video window.
        if QGuiApplication.platformName() == "offscreen":
            options += ["--vout=dummy", "--aout=dummy"]
        self.instance = vlc.Instance(*options)
        if not self.instance:
            raise RuntimeError("VLC no pudo inicializar el reproductor")
        self.player = self.instance.media_player_new()
        handle = int(widget.winId())
        if sys.platform == "win32":
            self.player.set_hwnd(handle)
        elif sys.platform == "darwin":
            self.player.set_nsobject(handle)
        else:
            self.player.set_xwindow(handle)
        self._duration = 0
        self._error = ""
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def setSource(self, url):
        self.stop()
        self._error = ""
        self._duration = 0
        self.durationChanged.emit(0)
        self.positionChanged.emit(0)
        path = url.toLocalFile()
        if path:
            media = self.instance.media_new_path(str(Path(path)))
            if media is None:
                raise RuntimeError("VLC no pudo abrir el archivo de vista previa")
            self.player.set_media(media)
            media.release()
        else:
            self.player.set_media(None)

    def play(self):
        if self.player.get_state() == self.vlc.State.Ended:
            self.player.stop()
        if self.player.play() == -1:
            self._error = "VLC no pudo abrir esta vista previa. Usa Abrir video."
            self.errorOccurred.emit()
            return
        self.timer.start()

    def pause(self):
        self.player.set_pause(1)

    def stop(self):
        self.timer.stop()
        self.player.stop()

    def duration(self):
        return max(0, self.player.get_length())

    def position(self):
        return max(0, self.player.get_time())

    def setPosition(self, position):
        self.player.set_time(position)

    def is_playing(self):
        return bool(self.player.is_playing())

    def errorString(self):
        return self._error

    def _poll(self):
        duration = self.duration()
        if duration != self._duration:
            self._duration = duration
            self.durationChanged.emit(duration)
        self.positionChanged.emit(self.position())
        if self.player.get_state() == self.vlc.State.Error:
            self._error = "No se pudo reproducir la vista previa. Usa Abrir video."
            self.timer.stop()
            self.errorOccurred.emit()

    def close(self):
        self.stop()
        self.player.release()
        self.instance.release()
