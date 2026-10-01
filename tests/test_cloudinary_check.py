# -*- coding: utf-8 -*-
"""Guardas del chequeo de Cloudinary.

BUG (2026-09-03): `check_auth()` devolvia authenticated=True sin llamar NUNCA
a la API -- solo miraba que las variables del .env existieran. Con una API key
revocada respondia exactamente lo mismo que con una buena.

Importa porque Cloudinary es el puente OBLIGATORIO para publicar en Instagram:
la API de Meta no acepta el archivo, pide una URL publica del video. Un "todo
bien" falso ahi se descubre recien cuando falla la publicacion.

    .venv\\Scripts\\python.exe test_cloudinary_check.py
"""

import unittest
from unittest.mock import patch

from publish import cloudinary_uploader as cu


class RespuestaFalsa:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._p = payload or {}
        self.text = text or ""

    def json(self):
        return self._p


CONFIG = ("micloud", "123456789", "secreto", "https://api.cloudinary.com")

USO_OK = {
    "plan": "Free",
    "credits": {"usage": 1.57, "limit": 25.0, "used_percent": 6.28},
    "resources": 145,
}


class ElChequeoLlamaDeVerdad(unittest.TestCase):

    def test_consulta_el_servidor(self):
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "get",
                          return_value=RespuestaFalsa(200, USO_OK)) as get:
            info = cu.check_auth()
        get.assert_called_once()
        self.assertIn("/v1_1/micloud/usage", get.call_args[0][0])
        self.assertTrue(info["authenticated"])
        self.assertTrue(info["verified_remotely"])

    def test_una_key_revocada_ya_no_pasa_por_valida(self):
        # Este es el caso que el chequeo viejo no distinguia.
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "get",
                          return_value=RespuestaFalsa(401, {}, "Invalid credentials")):
            info = cu.check_auth()
        self.assertFalse(info["authenticated"])
        self.assertIn("401", info["error"])

    def test_informa_el_cupo(self):
        # En el plan Free son 25 creditos al mes y el almacenamiento acumulado
        # tambien cuenta: conviene verlo antes de quedarse sin.
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "get", return_value=RespuestaFalsa(200, USO_OK)):
            info = cu.check_auth()
        self.assertEqual(info["plan"], "Free")
        self.assertEqual(info["credits_used"], 1.57)
        self.assertEqual(info["credits_limit"], 25.0)

    def test_sin_red_no_declara_las_claves_invalidas(self):
        # Un corte de red no prueba que las credenciales esten mal.
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "get", side_effect=OSError("sin red")):
            info = cu.check_auth()
        self.assertTrue(info["authenticated"], "un corte de red invalido las claves")
        self.assertFalse(info["verified_remotely"])
        self.assertIn("no se pudo verificar", info["error"])

    def test_sin_configuracion_falla_antes_de_la_red(self):
        with patch.object(cu, "_resolve_config", side_effect=RuntimeError("faltan claves")), \
             patch.object(cu.requests, "get") as get:
            info = cu.check_auth()
        self.assertFalse(info["authenticated"])
        get.assert_not_called()

    def test_se_puede_saltear_la_verificacion_remota(self):
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "get") as get:
            info = cu.check_auth(verify_remote=False)
        get.assert_not_called()
        self.assertTrue(info["authenticated"])
        self.assertFalse(info["verified_remotely"])

    def test_no_filtra_el_secret(self):
        with patch.object(cu, "_resolve_config", return_value=CONFIG), \
             patch.object(cu.requests, "get", return_value=RespuestaFalsa(200, USO_OK)):
            info = cu.check_auth()
        texto = str(info)
        self.assertNotIn("secreto", texto)
        self.assertNotIn("123456789", texto, "se filtro la api key entera")
        self.assertEqual(info["api_key_suffix"], "6789")


if __name__ == "__main__":
    unittest.main(verbosity=2)
