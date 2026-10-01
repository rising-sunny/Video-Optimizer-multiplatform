import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtWidgets import QApplication

from opening_style_preview import OpeningStylePreview
from pipeline.video_opening import OPENING_STYLE_CHOICES


class VistaPreviaDeEntradas(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _png(widget):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        widget.grab().save(buffer, "PNG")
        return bytes(data)

    def test_acepta_las_cinco_entradas(self):
        preview = OpeningStylePreview()
        preview.resize(preview.sizeHint())
        for style in OPENING_STYLE_CHOICES:
            preview.set_style(style)
            self.assertEqual(preview.style_id, style)

    def test_la_animacion_cambia_de_cuadro(self):
        preview = OpeningStylePreview()
        preview.resize(preview.sizeHint())
        preview.set_style(OPENING_STYLE_CHOICES[0])
        preview.set_phase(0.0)
        first = self._png(preview)
        preview.set_phase(0.55)
        second = self._png(preview)
        self.assertNotEqual(first, second)

    def test_cada_estilo_tiene_una_imagen_propia(self):
        preview = OpeningStylePreview()
        preview.resize(preview.sizeHint())
        frames = set()
        for style in OPENING_STYLE_CHOICES:
            preview.set_style(style)
            preview.set_phase(0.35)
            frames.add(self._png(preview))
        self.assertEqual(len(frames), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
