# -*- coding: utf-8 -*-
"""Guardas: un fallo transitorio de Meta al crear el contenedor no tira la publicacion.

BUG (2026-09-15, "Halifax Explosion"): YouTube y Facebook publicaron; Instagram
fallo con "Media upload has failed with error code 2207076" sobre el MISMO mp4
(1080x1920 H.264, AAC, 68 s -- specs impecables). Es un error intermitente del
lado de Meta; la comunidad lo resuelve reintentando. Nuestro uploader creaba el
contenedor una sola vez y ademas dejaba la copia de Cloudinary huerfana.

    .venv\\Scripts\\python.exe test_instagram_container_retry.py
"""

import io
import unittest
from unittest.mock import patch

from publish import instagram_uploader as ig


TRANSITORIO = "Instagram container failed: Error: Media upload has failed with error code 2207076"
PERMANENTE = "Instagram container failed: Error: Media upload has failed with error code 2207026"


class QueEsTransitorio(unittest.TestCase):

    def test_el_codigo_del_bug_es_transitorio(self):
        self.assertTrue(ig.is_transient_container_error(TRANSITORIO))

    def test_formato_no_soportado_no_se_reintenta(self):
        # 2207026 = formato de video no soportado: reintentar es perder tiempo.
        self.assertFalse(ig.is_transient_container_error(PERMANENTE))

    def test_vacio_no_rompe(self):
        self.assertFalse(ig.is_transient_container_error(None))
        self.assertFalse(ig.is_transient_container_error(""))


class ElContenedorSeReintenta(unittest.TestCase):

    def _run(self, fallos, attempts=3):
        """`fallos`: lista de mensajes de error, uno por intento fallido; luego FINISHED."""
        estados = list(fallos)
        creados = []
        esperas = []

        def crear(**kw):
            creados.append(kw)
            return {"id": "c%d" % len(creados)}

        def esperar(container_id, token, api_version=None, on_status=None):
            if estados:
                raise RuntimeError(estados.pop(0))
            return {"status_code": "FINISHED"}

        with patch.object(ig, "_create_reel_container", side_effect=crear), \
             patch.object(ig, "_wait_for_container_ready", side_effect=esperar):
            resultado = ig._create_container_with_retries(
                "ig1", "tok", "https://res.cloudinary.com/x/v.mp4", "caption", True,
                attempts=attempts, sleep=esperas.append)
        return resultado, creados, esperas

    def test_el_caso_del_bug_publica_al_segundo_intento(self):
        (cid, estado), creados, esperas = self._run([TRANSITORIO])
        self.assertEqual(cid, "c2")
        self.assertEqual(estado["status_code"], "FINISHED")
        self.assertEqual(len(creados), 2)
        self.assertEqual(esperas, [30], "espera antes del reintento")

    def test_reintenta_con_la_misma_url_sin_volver_a_subir(self):
        _, creados, _ = self._run([TRANSITORIO, TRANSITORIO])
        urls = {c["video_url"] for c in creados}
        self.assertEqual(urls, {"https://res.cloudinary.com/x/v.mp4"})
        self.assertEqual(len(creados), 3)

    def test_un_error_permanente_no_se_reintenta(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._run([PERMANENTE])
        self.assertIn("2207026", str(ctx.exception))

    def test_se_agotan_los_intentos_y_propaga_el_ultimo_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._run([TRANSITORIO, TRANSITORIO, TRANSITORIO], attempts=3)
        self.assertIn("2207076", str(ctx.exception))

    def test_las_esperas_crecen_y_se_repite_la_ultima(self):
        _, _, esperas = self._run([TRANSITORIO] * 3, attempts=4)
        self.assertEqual(esperas, [30, 90, 90])


class SinPublicarNoQuedaBasuraEnCloudinary(unittest.TestCase):

    def _video(self):
        import os
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ruta = os.path.join(tmp.name, "video.mp4")
        with open(ruta, "wb") as fh:
            fh.write(b"\x00" * 1024)
        return ruta

    def test_si_el_contenedor_falla_se_borra_la_copia(self):
        borrados = []
        with patch.object(ig, "_resolve_instagram_identity", return_value={"access_token": "t", "ig_user_id": "ig1"}), \
             patch.object(ig, "upload_video_to_cloudinary", return_value={"secure_url": "https://x/v.mp4", "public_id": "vo/reel_1"}), \
             patch.object(ig, "_create_container_with_retries", side_effect=RuntimeError(PERMANENTE)), \
             patch.object(ig, "_cleanup_cloudinary", side_effect=lambda pid: borrados.append(pid) or {"deleted": True}):
            with self.assertRaises(RuntimeError):
                ig.upload_video(self._video(), "titulo")
        self.assertEqual(borrados, ["vo/reel_1"])

    def test_si_publica_se_borra_una_sola_vez(self):
        borrados = []
        with patch.object(ig, "_resolve_instagram_identity", return_value={"access_token": "t", "ig_user_id": "ig1"}), \
             patch.object(ig, "upload_video_to_cloudinary", return_value={"secure_url": "https://x/v.mp4", "public_id": "vo/reel_2"}), \
             patch.object(ig, "_create_container_with_retries", return_value=("c1", {"status_code": "FINISHED"})), \
             patch.object(ig, "_publish_reel", return_value={"id": "m1"}), \
             patch.object(ig, "_get_media_info", return_value={"permalink": "https://www.instagram.com/reel/abc/"}), \
             patch.object(ig, "_cleanup_cloudinary", side_effect=lambda pid: borrados.append(pid) or {"deleted": True}):
            resultado = ig.upload_video(self._video(), "titulo")
        self.assertEqual(resultado["media_id"], "m1")
        self.assertEqual(borrados, ["vo/reel_2"])


class ElVpsSePuedeApagar(unittest.TestCase):
    """Con el VPS sin usar, cada plataforma esperaba 40 s a un ssh mudo."""

    def test_la_gui_respeta_vps_upload_enabled(self):
        fuente = "\n".join(io.open(r, encoding="utf-8", errors="replace").read() for r in ("studio/auto_video_integration_pyqt6.py", "studio/studio_publishing_mixin.py", "studio/studio_thumbnail_intelligence_mixin.py", "studio/studio_voice_mixin.py", "studio/studio_ui_setup_mixin.py"))
        inicio = fuente.index("def _upload_via_vps(")
        cuerpo = fuente[inicio:fuente.index("proc_mkdir = subprocess.run", inicio)]
        self.assertIn("VPS_UPLOAD_ENABLED", cuerpo)
        self.assertIn("return fallback_fn() if fallback_fn else None", cuerpo)
        # El interruptor va ANTES del primer ssh, que es donde se colgaba.
        self.assertLess(cuerpo.index("VPS_UPLOAD_ENABLED"), len(cuerpo))


if __name__ == "__main__":
    unittest.main(verbosity=2)
