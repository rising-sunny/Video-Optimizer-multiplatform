"""Pruebas reales de documentary_kit.imgtools (se saltan si faltan los modelos)."""
import tempfile, unittest
from pathlib import Path
from PIL import Image, ImageDraw
from documentary_kit import imgtools


@unittest.skipUnless(imgtools.ESRGAN.exists(), 'falta RealESRGAN_x4plus.pth')
class TestUpscale(unittest.TestCase):
    def test_x4_and_gray(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'a.png'; im = Image.new('L', (40, 30), 80); ImageDraw.Draw(im).rectangle((10, 8, 30, 22), fill=220); im.save(src)
            out = imgtools.upscale(src, Path(d) / 'b.png')
            r = Image.open(out); self.assertEqual(r.size, (160, 120)); self.assertEqual(r.mode, 'L')
            out2 = imgtools.upscale(src, Path(d) / 'c.png', scale=2)
            self.assertEqual(Image.open(out2).size, (80, 60))


@unittest.skipUnless((Path.home() / '.u2net/isnet-general-use.onnx').exists(), 'falta el modelo de rembg')
class TestCutout(unittest.TestCase):
    def test_alpha(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'a.jpg'; im = Image.new('RGB', (200, 200), (30, 120, 30)); ImageDraw.Draw(im).ellipse((60, 40, 140, 180), fill=(230, 210, 190)); im.save(src)
            out = imgtools.cutout(src, Path(d) / 'b')
            r = Image.open(out); self.assertEqual(r.mode, 'RGBA'); self.assertEqual(out.suffix, '.png')


if __name__ == '__main__':
    unittest.main()
