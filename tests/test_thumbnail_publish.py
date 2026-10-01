# -*- coding: utf-8 -*-
"""Guardas de la miniatura de publicacion (thumbnail_publish).

2026-09-22, "a veces el thumbnail no aparece": un .webp se descartaba en silencio,
los errores de thumbnails.set no llegaban al panel y no habia reintento. Verificado
contra lo que YouTube sirve: Catalhoyuk y Halifax muestran la miniatura de la app
(d=0.0); Gunnerside y Hannibal muestran las que el usuario subio a mano despues.

    .venv\\Scripts\\python.exe test_thumbnail_publish.py
"""

import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from PIL import Image, ImageDraw

from publish import thumbnail_publish as tp


def _img(path, size=(1080, 1920), fmt="PNG", color=(20, 40, 90)):
    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    d.rectangle([size[0] // 4, size[1] // 5, size[0] // 2, size[1] // 2], fill=(240, 200, 30))
    d.ellipse([size[0] // 2, size[1] // 2, size[0] - 50, size[1] - 200], fill=(200, 30, 30))
    im.save(path, fmt)
    return path


class Preparar(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_webp_se_convierte_a_jpeg_real(self):
        src = _img(os.path.join(self.tmp.name, "thumbnail.webp"), fmt="WEBP")
        out = tp.prepare_for_youtube(src)
        self.assertTrue(out["converted"])
        self.assertEqual(out["mimetype"], "image/jpeg")
        with Image.open(out["path"]) as im:
            self.assertEqual(im.format, "JPEG")

    def test_png_liviano_pasa_tal_cual(self):
        src = _img(os.path.join(self.tmp.name, "t.png"))
        out = tp.prepare_for_youtube(src)
        self.assertFalse(out["converted"])
        self.assertEqual(out["mimetype"], "image/png")

    def test_la_extension_miente_y_manda_el_contenido(self):
        src = _img(os.path.join(self.tmp.name, "t.png"), fmt="WEBP")   # WebP con nombre .png
        out = tp.prepare_for_youtube(src)
        self.assertEqual(out["mimetype"], "image/jpeg")
        self.assertTrue(out["converted"])

    def test_mas_de_2mb_se_recomprime(self):
        import random
        src = os.path.join(self.tmp.name, "big.png")
        im = Image.new("RGB", (1600, 2800))
        im.putdata([(random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(1600 * 2800)])
        im.save(src, "PNG")
        self.assertGreater(os.path.getsize(src), 2 * 1024 * 1024)
        out = tp.prepare_for_youtube(src)
        self.assertLessEqual(out["bytes"], 2 * 1024 * 1024)

    def test_chica_avisa(self):
        src = _img(os.path.join(self.tmp.name, "tiny.png"), size=(300, 500))
        self.assertTrue(tp.prepare_for_youtube(src)["warnings"])

    def test_la_carpeta_de_publicacion_encuentra_webp(self):
        _img(os.path.join(self.tmp.name, "thumbnail.webp"), fmt="WEBP")
        self.assertEqual(tp.find_staged_thumbnail(self.tmp.name).name, "thumbnail.webp")


class Subir(unittest.TestCase):

    def _yt(self, errors):
        yt = MagicMock()
        calls = {"n": 0}

        def execute():
            calls["n"] += 1
            if errors:
                err = errors.pop(0)
                if err is not None:
                    raise err
            return {"items": [{"default": {"url": "u"}}]}
        yt.thumbnails.return_value.set.return_value.execute.side_effect = execute
        return yt, calls

    def _err(self, status, text=""):
        e = Exception(text or f"HttpError {status}")
        e.resp = MagicMock(status=status)
        return e

    def test_reintenta_un_error_transitorio(self):
        yt, calls = self._yt([self._err(500)])
        esperas = []
        out = tp.set_thumbnail_with_retry(yt, "V", {"path": "x", "mimetype": "image/jpeg"},
                                          media_factory=lambda p, m: object(), sleep=esperas.append)
        self.assertTrue(out["ok"])
        self.assertEqual(out["attempts"], 2)
        self.assertEqual(esperas, [8])

    def test_403_no_reintenta_y_explica(self):
        yt, calls = self._yt([self._err(403, "forbidden")])
        out = tp.set_thumbnail_with_retry(yt, "V", {"path": "x", "mimetype": "image/jpeg"},
                                          media_factory=lambda p, m: object(), sleep=lambda s: None)
        self.assertFalse(out["ok"])
        self.assertEqual(calls["n"], 1)
        self.assertIn("youtube.com/verify", out["error"])

    def test_se_rinde_tras_tres_intentos(self):
        yt, calls = self._yt([self._err(503), self._err(503), self._err(503)])
        out = tp.set_thumbnail_with_retry(yt, "V", {"path": "x", "mimetype": "image/jpeg"},
                                          media_factory=lambda p, m: object(), sleep=lambda s: None)
        self.assertFalse(out["ok"])
        self.assertEqual(calls["n"], 3)


class Verificar(unittest.TestCase):

    def test_un_short_servido_con_bordes_difuminados_coincide(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        local_p = _img(os.path.join(tmp.name, "l.png"))
        local = Image.open(local_p).convert("RGB")
        # Asi sirve YouTube un Short: 16:9, la miniatura al centro, bordes oscuros.
        served = Image.new("RGB", (1280, 720), (15, 15, 15))
        panel = local.resize((405, 720))
        served.paste(panel, ((1280 - 405) // 2, 0))
        buf = io.BytesIO()
        served.save(buf, "JPEG")
        rep = tp.verify_served_thumbnail("V", local_p, fetch=lambda url: buf.getvalue())
        self.assertTrue(rep["match"], rep)

    def test_otra_imagen_no_coincide(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        local_p = _img(os.path.join(tmp.name, "l.png"))
        other = Image.new("RGB", (1280, 720), (200, 200, 200))
        ImageDraw.Draw(other).rectangle([0, 0, 640, 360], fill=(0, 0, 0))
        buf = io.BytesIO()
        other.save(buf, "JPEG")
        rep = tp.verify_served_thumbnail("V", local_p, fetch=lambda url: buf.getvalue())
        self.assertFalse(rep["match"])

    def test_sin_respuesta_de_youtube(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rep = tp.verify_served_thumbnail("V", _img(os.path.join(tmp.name, "l.png")), fetch=lambda url: None)
        self.assertFalse(rep["checked"])


class LasFuentesUsanElModulo(unittest.TestCase):

    def test_uploader_y_studio(self):
        up = open("publish/youtube_uploader.py", encoding="utf-8").read()
        self.assertIn("find_staged_thumbnail(output_dir)", up)
        self.assertIn("set_thumbnail_with_retry(", up)
        self.assertIn("NO SE PUSO", up)
        st = open("studio/auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace").read()
        self.assertIn("Miniatura a publicar:", st)
        self.assertIn("la miniatura NO se puso", st)


if __name__ == "__main__":
    unittest.main(verbosity=2)
