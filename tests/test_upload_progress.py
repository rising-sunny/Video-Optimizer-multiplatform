# -*- coding: utf-8 -*-
"""Guardas: el panel de la GUI ve el progreso de la publicacion local.

2026-09-15: con VPS_UPLOAD_ENABLED=0 el log se detenia en "Instagram se sube
desde esta PC" y no volvia a decir nada hasta el resultado final, minutos
despues (Cloudinary + Meta procesando el contenedor, ahora con reintentos).
Los uploaders solo reportaban bytes por callback y nadie los cableaba al panel.

    .venv\\Scripts\\python.exe test_upload_progress.py
"""

import io
import unittest
from unittest.mock import patch

from publish import instagram_uploader as ig
from publish.upload_progress import make_byte_progress_reporter


class BytesAPorcentaje(unittest.TestCase):

    def _run(self, total, pasos, step=25):
        lineas = []
        cb = make_byte_progress_reporter("Cloudinary", lineas.append, step_percent=step)
        for enviado in pasos:
            cb(enviado, total)
        return lineas

    def test_avisa_cada_25_por_ciento_y_una_sola_vez(self):
        lineas = self._run(1000, [0, 10, 120, 250, 260, 500, 740, 750, 990, 1000, 1000])
        self.assertEqual(lineas, ["Cloudinary: 0% (0.0 MB)", "Cloudinary: 25%", "Cloudinary: 50%",
                                  "Cloudinary: 75%", "Cloudinary: 100%"])

    def test_el_tamano_va_solo_en_el_arranque(self):
        lineas = self._run(16_580_337, [0, 16_580_337])
        self.assertEqual(lineas[0], "Cloudinary: 0% (16.6 MB)")
        self.assertEqual(lineas[-1], "Cloudinary: 100%")

    def test_saltos_grandes_no_pierden_el_final(self):
        # Cloudinary sin toolbelt: solo llama (0,total) y (total,total).
        self.assertEqual(self._run(500, [0, 500]), ["Cloudinary: 0% (0.0 MB)", "Cloudinary: 100%"])

    def test_total_desconocido_solo_avisa_el_arranque(self):
        self.assertEqual(self._run(0, [0, 100, 200]), ["Cloudinary: 0%"])

    def test_un_panel_que_revienta_no_frena_la_subida(self):
        def boom(_): raise RuntimeError("panel cerrado")
        cb = make_byte_progress_reporter("X", boom)
        cb(0, 10); cb(10, 10)   # no levanta

    def test_basura_en_los_numeros_no_rompe(self):
        lineas = []
        cb = make_byte_progress_reporter("X", lineas.append)
        cb(None, "abc"); cb("x", 10)
        self.assertEqual(lineas, [])


class ElUploaderCuentaLasEtapas(unittest.TestCase):

    def test_status_llama_al_panel_y_no_rompe_si_falla(self):
        vistos = []
        ig._status(vistos.append, "hola")
        self.assertEqual(vistos, ["hola"])
        ig._status(None, "sin panel")            # no levanta
        ig._status(lambda m: 1 / 0, "panel roto")  # tampoco

    def test_los_reintentos_avisan_en_el_panel(self):
        estados = ["Instagram container failed: Error: Media upload has failed with error code 2207076"]
        vistos = []
        with patch.object(ig, "_create_reel_container", side_effect=lambda **kw: {"id": "c"}), \
             patch.object(ig, "_wait_for_container_ready",
                          side_effect=lambda cid, tok, api_version=None, on_status=None:
                          (_ for _ in ()).throw(RuntimeError(estados.pop(0))) if estados else {"status_code": "FINISHED"}):
            ig._create_container_with_retries("ig1", "t", "https://x/v.mp4", "cap", True,
                                              attempts=2, sleep=lambda s: None, on_status=vistos.append)
        texto = "\n".join(vistos)
        self.assertIn("intento 1/2", texto)
        self.assertIn("reintento 2/2", texto)
        self.assertIn("misma URL", texto)

    def test_el_polling_avisa_que_meta_esta_procesando(self):
        vistos = []
        respuestas = [{"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}]
        with patch.object(ig, "get_container_status", side_effect=lambda *a, **k: respuestas.pop(0)), \
             patch.object(ig.time, "sleep", lambda s: None):
            ig._wait_for_container_ready("c1", "t", on_status=vistos.append)
        self.assertEqual(len(vistos), 1)
        self.assertIn("Meta procesando", vistos[0])


class LaGuiCableaElProgreso(unittest.TestCase):

    def test_los_fallbacks_locales_pasan_progreso_al_panel(self):
        fuente = io.open("auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace").read()
        self.assertIn("_publish_log_signal = pyqtSignal(str)", fuente)
        self.assertIn("self._publish_log_signal.connect(self.log)", fuente)
        ig_block = fuente[fuente.index("def _upload_instagram_via_vps("):fuente.index("def _on_publish_done(")]
        self.assertIn("on_status=", ig_block)
        self.assertIn("make_byte_progress_reporter", ig_block)
        fb_block = fuente[fuente.index("def _upload_facebook_via_vps("):fuente.index("def _upload_instagram_via_vps(")]
        self.assertIn("make_byte_progress_reporter", fb_block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
