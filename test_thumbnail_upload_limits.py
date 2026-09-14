# -*- coding: utf-8 -*-
"""Guardas del limite de 2 MB de la API de miniaturas de YouTube.

BUG (2026-09-02): al publicar el short de Cahokia, la GUI reporto
"YouTube error: Media larger than: 2097152" y "Youtube fallo" -- pero el video
SI se habia subido (mxLaFvLwJ_A). Dos defectos encadenados:

  1. El compositor guarda PNG. Un 1080x1920 con foto pesa ~2.6 MB y la API de
     datos corta en 2 MB EXACTOS. (Los 50 MB que documenta YouTube son del
     uploader WEB de Studio, no de la API.)
  2. googleapiclient valida el tamano ANTES de enviar y lanza
     `MediaUploadSizeError`, que NO hereda de `HttpError`. El `except HttpError`
     del uploader no lo atrapaba, asi que un fallo de miniatura tumbaba la
     publicacion entera de un video ya subido.

    .venv\\Scripts\\python.exe test_thumbnail_upload_limits.py
"""

import os
import shutil
import tempfile
import unittest

from PIL import Image

from thumbnail_compositor import (
    YOUTUBE_API_THUMBNAIL_MAX_BYTES,
    fit_for_youtube_api,
)


class LimiteRealDeLaApi(unittest.TestCase):

    def test_el_limite_es_2_mb_exactos(self):
        # El numero del mensaje de error de la API.
        self.assertEqual(YOUTUBE_API_THUMBNAIL_MAX_BYTES, 2097152)

    def test_el_error_de_tamano_no_es_un_httperror(self):
        """Por esto el `except HttpError` no lo atrapaba."""
        from googleapiclient.errors import HttpError, MediaUploadSizeError
        self.assertFalse(issubclass(MediaUploadSizeError, HttpError))
        # Y por esto hay que atrapar Exception en el uploader.
        self.assertTrue(issubclass(MediaUploadSizeError, Exception))


class RecompresionParaLaApi(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="thumblim_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _png_pesado(self, nombre="thumb.png", size=(1080, 1920)):
        """PNG con ruido: incompresible, como una miniatura fotografica real."""
        import random
        random.seed(7)
        img = Image.new("RGB", size)
        px = img.load()
        for y in range(size[1]):
            for x in range(size[0]):
                px[x, y] = (random.randrange(256), random.randrange(256),
                            random.randrange(256))
        ruta = os.path.join(self.tmp, nombre)
        img.save(ruta, "PNG")
        return ruta

    def test_un_png_vertical_pesado_termina_bajo_el_limite(self):
        origen = self._png_pesado()
        self.assertGreater(os.path.getsize(origen), YOUTUBE_API_THUMBNAIL_MAX_BYTES,
                           "el fixture tiene que exceder el limite para probar algo")
        ruta, mime = fit_for_youtube_api(origen)
        self.assertLessEqual(os.path.getsize(ruta), YOUTUBE_API_THUMBNAIL_MAX_BYTES)
        self.assertEqual(mime, "image/jpeg")

    def test_conserva_la_resolucion_si_alcanza_con_calidad(self):
        # Bajar resolucion es el ultimo recurso: 1080x1920 esta muy por debajo
        # del maximo de YouTube, lo que sobra son bytes de PNG.
        origen = self._png_pesado()
        ruta, _ = fit_for_youtube_api(origen)
        with Image.open(ruta) as img:
            self.assertEqual(img.size, (1080, 1920))

    def test_un_archivo_que_ya_entra_no_se_toca(self):
        ruta_ok = os.path.join(self.tmp, "chico.png")
        Image.new("RGB", (1080, 1920), (30, 40, 50)).save(ruta_ok, "PNG")
        self.assertLess(os.path.getsize(ruta_ok), YOUTUBE_API_THUMBNAIL_MAX_BYTES)
        ruta, mime = fit_for_youtube_api(ruta_ok)
        self.assertEqual(ruta, ruta_ok, "recomprimio algo que ya entraba")
        self.assertEqual(mime, "image/png")

    def test_un_jpg_que_ya_entra_declara_su_mimetype(self):
        ruta_ok = os.path.join(self.tmp, "chico.jpg")
        Image.new("RGB", (1080, 1920), (30, 40, 50)).save(ruta_ok, "JPEG")
        _, mime = fit_for_youtube_api(ruta_ok)
        self.assertEqual(mime, "image/jpeg")

    def test_un_archivo_inexistente_no_revienta(self):
        ruta, mime = fit_for_youtube_api(os.path.join(self.tmp, "no_existe.png"))
        self.assertTrue(ruta)
        self.assertTrue(mime)

    def test_respeta_un_limite_mas_chico(self):
        # Fuerza el camino de bajar resolucion.
        origen = self._png_pesado()
        ruta, _ = fit_for_youtube_api(origen, max_bytes=60_000)
        self.assertLessEqual(os.path.getsize(ruta), 60_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
