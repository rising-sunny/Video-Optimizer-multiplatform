# -*- coding: utf-8 -*-
"""Guardas del borrado automatico de la copia intermedia de Cloudinary.

Cloudinary es un PUENTE: la API de Instagram no acepta el archivo, pide una URL
publica. Se sube, Meta lo descarga y despues la copia queda ahi para siempre.
Al 2026-09-03 habia 145 recursos y 1.5 GB acumulados, y en el plan Free el
almacenamiento cuenta contra los 25 creditos mensuales.

Dos reglas que no se pueden romper:
  1. Borrar SOLO despues de que el reel este publicado. Antes, Instagram se
     queda sin de donde bajar el video.
  2. Un fallo al borrar NO puede afectar a la publicacion, que ya salio bien.

    .venv\\Scripts\\python.exe test_cloudinary_cleanup.py
"""

import unittest
from unittest.mock import patch

from publish import cloudinary_uploader as cu
from publish import instagram_uploader as ig


class RespuestaFalsa:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._p = payload or {}
        self.text = text

    def json(self):
        return self._p


CONFIG = ("micloud", "123456789", "secreto", "https://api.cloudinary.com")


class BorradoEnCloudinary(unittest.TestCase):

    def test_borra_por_public_id(self):
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "delete",
                          return_value=RespuestaFalsa(200, {"deleted": {"vo/reel_1": "deleted"}})) as d:
            res = cu.delete_video("vo/reel_1")
        self.assertTrue(res["deleted"])
        url = d.call_args[0][0]
        self.assertIn("/resources/video/upload", url)
        self.assertEqual(d.call_args[1]["params"], {"public_ids[]": "vo/reel_1"})

    def test_un_id_inexistente_no_se_reporta_como_borrado(self):
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "delete",
                          return_value=RespuestaFalsa(200, {"deleted": {"x": "not_found"}})):
            res = cu.delete_video("x")
        self.assertFalse(res["deleted"])
        self.assertEqual(res["state"], "not_found")

    def test_nunca_lanza(self):
        # Limpiar es mantenimiento: no puede tumbar nada.
        with patch.object(cu, "_resolve_config", side_effect=RuntimeError("sin claves")):
            res = cu.delete_video("vo/reel_1")
        self.assertFalse(res["deleted"])
        self.assertIn("sin claves", res["error"])

        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "delete", side_effect=OSError("sin red")):
            res = cu.delete_video("vo/reel_1")
        self.assertFalse(res["deleted"])

    def test_un_public_id_vacio_no_llama_a_la_api(self):
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "delete") as d:
            res = cu.delete_video("")
        d.assert_not_called()
        self.assertFalse(res["deleted"])

    def test_un_error_http_se_informa_sin_romper(self):
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "delete",
                          return_value=RespuestaFalsa(401, {}, "Invalid credentials")):
            res = cu.delete_video("vo/reel_1")
        self.assertFalse(res["deleted"])
        self.assertIn("401", res["error"])


class LimpiezaDesdeInstagram(unittest.TestCase):

    def test_borra_cuando_hay_public_id(self):
        with patch.object(ig, "_env", lambda n, d=None: d), \
             patch("publish.cloudinary_uploader.delete_video",
                   return_value={"deleted": True, "public_id": "vo/reel_1"}) as borrar:
            res = ig._cleanup_cloudinary("vo/reel_1")
        borrar.assert_called_once_with("vo/reel_1")
        self.assertTrue(res["deleted"])

    def test_se_puede_desactivar_por_configuracion(self):
        env = {"CLOUDINARY_DELETE_AFTER_PUBLISH": "0"}
        with patch.object(ig, "_env", lambda n, d=None: env.get(n, d)), \
             patch("publish.cloudinary_uploader.delete_video") as borrar:
            res = ig._cleanup_cloudinary("vo/reel_1")
        borrar.assert_not_called()
        self.assertIn("desactivado", res["skipped"])

    def test_sin_public_id_no_intenta_nada(self):
        with patch.object(ig, "_env", lambda n, d=None: d), \
             patch("publish.cloudinary_uploader.delete_video") as borrar:
            res = ig._cleanup_cloudinary(None)
        borrar.assert_not_called()
        self.assertFalse(res["deleted"])

    def test_un_fallo_al_borrar_no_se_propaga(self):
        # El reel ya esta publicado: perder la limpieza cuesta almacenamiento,
        # no la publicacion.
        with patch.object(ig, "_env", lambda n, d=None: d), \
             patch("publish.cloudinary_uploader.delete_video", side_effect=RuntimeError("boom")):
            res = ig._cleanup_cloudinary("vo/reel_1")
        self.assertFalse(res["deleted"])
        self.assertIn("boom", res["error"])


class OrdenDeLosPasos(unittest.TestCase):
    """El borrado va DESPUES de publicar, nunca antes."""

    def test_el_codigo_borra_despues_de_obtener_el_permalink(self):
        import inspect

        # Desde 2026-09-22 el cuerpo vive en _upload_video_once (upload_video lo envuelve
        # para la portada, que tambien pasa por Cloudinary).
        fuente = inspect.getsource(ig._upload_video_once)
        pos_publicar = fuente.index("_publish_reel(")
        pos_media_info = fuente.index("_get_media_info(")
        # Desde 2026-09-15 hay DOS limpiezas: la del `except` (no se publico,
        # la copia no sirve) y la del camino feliz. Esta guarda es sobre la
        # segunda: en el camino feliz se borra recien despues del permalink.
        pos_limpieza = fuente.rindex("_cleanup_cloudinary(")
        self.assertLess(pos_publicar, pos_limpieza,
                        "se borra Cloudinary ANTES de publicar el reel")
        self.assertLess(pos_media_info, pos_limpieza,
                        "se borra antes de confirmar el permalink")

    def test_la_portada_se_borra_despues_de_publicar(self):
        # Meta descarga la portada (cover_url) al procesar el contenedor.
        import inspect

        fuente = inspect.getsource(ig.upload_video)
        self.assertLess(fuente.index("_upload_video_once("), fuente.index("_cleanup_cover("))
        self.assertIn("finally:", fuente, "la copia de la portada se borra tambien si falla")


if __name__ == "__main__":
    unittest.main(verbosity=2)
