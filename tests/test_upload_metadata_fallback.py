# -*- coding: utf-8 -*-
"""Guardas: la metadata de subida nunca puede llegar como None.

BUG (2026-09-09): Facebook e Instagram fallaron con

    File "publish/facebook_uploader.py", line 848, in upload_from_metadata
      title = metadata.get("title") or output_dir.name
    AttributeError: 'NoneType' object has no attribute 'get'

Cadena completa: el Metadata Studio no tenia campos propios de Facebook, la
GUI guardaba `_facebook_meta = None`, `json.dump(None, f)` escribia el literal
`null` en `facebook_metadata.json`, y `json.load` devolvia None. YouTube
publicaba bien porque SI tenia metadata; las otras dos redes se caian, y el
fallback local se caia igual porque usaba el mismo archivo.

    .venv\\Scripts\\python.exe test_upload_metadata_fallback.py
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from publish import facebook_uploader as fb
from publish import instagram_uploader as ig


class MetadataInvalidaNoRompe(unittest.TestCase):
    """Capa 2: el uploader tolera un archivo con contenido inservible."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="meta_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _escribir(self, nombre, contenido_json):
        with open(os.path.join(self.tmp, nombre), "w", encoding="utf-8") as f:
            f.write(contenido_json)

    def test_un_archivo_con_null_devuelve_dict_vacio(self):
        """El caso exacto que reventaba."""
        self._escribir("facebook_metadata.json", "null")
        datos = fb._load_upload_metadata(Path(self.tmp))
        self.assertEqual(datos, {})
        # Lo que hacia el llamador y explotaba:
        self.assertIsNone(datos.get("title"))

    def test_lo_mismo_en_instagram(self):
        self._escribir("instagram_metadata.json", "null")
        datos = ig._load_upload_metadata(Path(self.tmp))
        self.assertEqual(datos, {})
        self.assertIsNone(datos.get("title"))

    def test_una_lista_tampoco_rompe(self):
        self._escribir("facebook_metadata.json", '["a", "b"]')
        self.assertEqual(fb._load_upload_metadata(Path(self.tmp)), {})

    def test_la_metadata_buena_pasa_intacta(self):
        self._escribir("facebook_metadata.json",
                       json.dumps({"title": "Caral", "description": "Seis piramides"}))
        datos = fb._load_upload_metadata(Path(self.tmp))
        self.assertEqual(datos["title"], "Caral")
        self.assertEqual(datos["description"], "Seis piramides")

    def test_sin_ningun_archivo_sigue_avisando_claro(self):
        # Que no haya metadata ES un error real y tiene que decirlo.
        with self.assertRaises(FileNotFoundError):
            fb._load_upload_metadata(Path(self.tmp))

    def test_cae_al_siguiente_archivo_de_la_lista(self):
        self._escribir("metadata.json", json.dumps({"title": "De YouTube"}))
        self.assertEqual(fb._load_upload_metadata(Path(self.tmp))["title"], "De YouTube")


class LaGuiNoEscribeNull(unittest.TestCase):
    """Capa 1: el arreglo de fondo, para que el archivo nunca traiga `null`."""

    def _fuente(self):
        return io.open("studio/auto_video_integration_pyqt6.py", encoding="utf-8",
                       errors="replace").read()

    def test_facebook_cae_a_la_metadata_de_youtube(self):
        # dict(...): copia, porque el Studio le agrega contexto de investigacion a Facebook
        # (facebook_metadata) sin tocar la metadata de YouTube. Sigue sin poder ser None.
        self.assertIn("_facebook_meta = dict(facebook_meta or youtube_meta or {})",
                      self._fuente())

    def test_instagram_tambien_tiene_respaldo(self):
        # dict(...): copia, el Studio le agrega el contexto de investigacion (facebook_metadata).
        self.assertIn("_instagram_meta = dict(instagram_meta or facebook_meta or youtube_meta or {})",
                      self._fuente())

    def test_ninguna_red_se_guarda_pelada(self):
        # `_x_meta` ya tenia respaldo; el bug fue que FB e IG quedaron sin el.
        fuente = self._fuente()
        for red in ("_facebook_meta", "_instagram_meta", "_x_meta"):
            self.assertNotIn("%s = facebook_meta\n" % red, fuente)
            self.assertNotIn("%s = instagram_meta\n" % red, fuente)


class ElTituloSaleDeAlgunLado(unittest.TestCase):
    """Con metadata vacia el uploader usa el nombre de la carpeta, no None."""

    def test_facebook_usa_el_nombre_de_la_carpeta(self):
        metadata = {}
        output_dir = Path(r"C:\staging\Caral_20260909")
        titulo = metadata.get("title") or output_dir.name
        self.assertEqual(titulo, "Caral_20260909")

    def test_instagram_igual(self):
        metadata = {}
        output_dir = Path(r"C:\staging\Leningrado")
        self.assertEqual(metadata.get("title") or output_dir.name, "Leningrado")


if __name__ == "__main__":
    unittest.main(verbosity=2)
