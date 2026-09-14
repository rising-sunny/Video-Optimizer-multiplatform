# -*- coding: utf-8 -*-
"""Guardas de la subida de video a X (Twitter).

El texto del post es la parte que se rompe en silencio: X rechaza el post
ENTERO con 403 si pasa de 280 caracteres, o sea que un titulo largo te hace
perder el video ya subido. Y el flujo por trozos tiene un orden que no se puede
alterar: initialize -> append(0..n) -> finalize -> STATUS hasta `succeeded`.
Publicar antes de `succeeded` da un post sin video.

    .venv\\Scripts\\python.exe test_x_video_uploader.py

No toca la red: se le enchufa una sesion OAuth falsa.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import x_video_uploader as xv


class TextoDelPost(unittest.TestCase):

    def test_lo_normal_entra_entero(self):
        t = xv.build_post_text(
            title="Caral: the oldest city in the Americas",
            description="Six pyramids, 5,000 years, zero weapons.",
            tags=["history", "caral"],
            url="https://youtube.com/shorts/abc",
        )
        self.assertIn("Caral", t)
        self.assertIn("#history", t)
        self.assertIn("https://youtube.com/shorts/abc", t)
        self.assertLessEqual(len(t), xv.POST_CHAR_LIMIT)

    def test_nunca_pasa_el_limite(self):
        t = xv.build_post_text(
            title="T" * 200, description="D" * 400,
            tags=["uno", "dos", "tres", "cuatro"],
            url="https://youtube.com/shorts/abcdefghijk",
        )
        self.assertLessEqual(len(t), xv.POST_CHAR_LIMIT)

    def test_al_recortar_se_caen_primero_los_hashtags(self):
        # Largo elegido a proposito: con hashtag son 286 caracteres (no entra),
        # sin hashtag 276 (entra). Asi se prueba el ESCALON, no el limite.
        largo = ("Caral " * 43).strip()               # 257 chars
        t = xv.build_post_text(title=largo, description="", tags=["history"],
                               url="https://x.com/abc")
        self.assertLessEqual(len(t), xv.POST_CHAR_LIMIT)
        self.assertNotIn("#history", t, "se conservo el hashtag y se perdio texto util")
        self.assertIn("https://x.com/abc", t)
        self.assertTrue(t.startswith("Caral"), "se recorto el titulo pudiendo entrar entero")

    def test_el_enlace_sobrevive_al_recorte(self):
        # Sin el enlace el post no cumple su funcion, asi que se respeta entero.
        url = "https://youtube.com/shorts/w31LtHdB14I"
        t = xv.build_post_text(title="T" * 500, description="D" * 500, url=url)
        self.assertIn(url, t)
        self.assertLessEqual(len(t), xv.POST_CHAR_LIMIT)

    def test_el_titulo_se_corta_por_palabra(self):
        t = xv.build_post_text(title="palabra " * 60, url="https://x.com/a")
        self.assertNotIn("palabr\n", t)
        self.assertTrue(t.startswith("palabra"))

    def test_sin_nada_no_revienta(self):
        self.assertEqual(xv.build_post_text(), "")

    def test_los_hashtags_se_limpian(self):
        t = xv.build_post_text(title="X", tags=["#ancient history!", "caral"])
        self.assertIn("#ancienthistory", t)
        self.assertNotIn("!", t)


class SesionFalsa:
    """Simula la API de X y anota el orden de las llamadas."""

    def __init__(self, processing=None, fallar_en=None, status=200):
        self.llamadas = []
        self.processing = processing
        self.fallar_en = fallar_en
        self.status_code_forzado = status
        self.polls = 0

    class _R:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._p = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._p

    def post(self, url, **kw):
        self.llamadas.append(url)
        if self.fallar_en and self.fallar_en in url:
            return self._R(self.status_code_forzado, {"detail": "boom"})
        if url.endswith("/initialize"):
            return self._R(200, {"data": {"id": "MEDIA123"}})
        if url.endswith("/append"):
            self.llamadas[-1] = f"append:{kw.get('data', {}).get('segment_index')}"
            return self._R(200, {})
        if url.endswith("/finalize"):
            return self._R(200, {"data": {"processing_info": self.processing}})
        if url.endswith("/tweets"):
            return self._R(201, {"data": {"id": "POST999"}})
        return self._R(404, {})

    def get(self, url, **kw):
        self.polls += 1
        self.llamadas.append("status")
        estado = "succeeded" if self.polls >= 2 else "in_progress"
        return self._R(200, {"data": {"processing_info":
                                      {"state": estado, "check_after_secs": 0}}})


class FlujoPorTrozos(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xvid_")
        self.video = os.path.join(self.tmp, "short.mp4")
        with open(self.video, "wb") as f:
            f.write(b"\0" * (10 * 1024 * 1024))   # 10 MB -> 3 trozos de 4 MB

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_el_orden_de_los_pasos_es_el_correcto(self):
        ses = SesionFalsa()
        with patch.object(xv, "_oauth", return_value=ses):
            media_id = xv.upload_video(self.video)
        self.assertEqual(media_id, "MEDIA123")
        self.assertTrue(ses.llamadas[0].endswith("/initialize"))
        self.assertTrue(ses.llamadas[-1].endswith("/finalize"))

    def test_los_trozos_van_numerados_desde_cero_y_en_orden(self):
        ses = SesionFalsa()
        with patch.object(xv, "_oauth", return_value=ses):
            xv.upload_video(self.video)
        indices = [c.split(":")[1] for c in ses.llamadas if str(c).startswith("append:")]
        self.assertEqual(indices, ["0", "1", "2"], "10 MB con trozos de 4 MB son 3 partes")

    def test_los_trozos_no_pasan_el_maximo_de_x(self):
        # X acepta hasta 8 MB y recomienda 5: pasarse da 400 en cada append.
        self.assertLessEqual(xv.CHUNK_SIZE, 5 * 1024 * 1024)

    def test_reporta_progreso(self):
        avances = []
        ses = SesionFalsa()
        with patch.object(xv, "_oauth", return_value=ses):
            xv.upload_video(self.video, on_progress=lambda e, t: avances.append((e, t)))
        self.assertEqual(avances[-1][0], avances[-1][1], "el ultimo avance no llega al 100%")

    def test_espera_a_que_termine_el_procesado(self):
        # Publicar con el media_id antes de `succeeded` da un post SIN video.
        ses = SesionFalsa(processing={"state": "in_progress", "check_after_secs": 0})
        with patch.object(xv, "_oauth", return_value=ses):
            xv.upload_video(self.video)
        self.assertGreaterEqual(ses.polls, 1, "no consulto el estado del procesado")

    def test_si_x_no_puede_procesarlo_falla_claro(self):
        ses = SesionFalsa(processing={"state": "failed"})
        with patch.object(xv, "_oauth", return_value=ses):
            with self.assertRaises(xv.XUploadError):
                xv.upload_video(self.video)

    def test_el_401_explica_que_son_los_tokens(self):
        ses = SesionFalsa(fallar_en="initialize", status=401)
        with patch.object(xv, "_oauth", return_value=ses):
            with self.assertRaises(xv.XUploadError) as ctx:
                xv.upload_video(self.video)
        self.assertIn("vencidos", str(ctx.exception))

    def test_el_402_dice_que_son_los_creditos_y_no_las_claves(self):
        # Caso real (2026-09-03): la cuenta quedo sin creditos del plan
        # 'Pay Per Use' y la API devolvia 402 'credits depleted'. Sin este
        # mensaje, el sintoma se confunde con credenciales rotas.
        ses = SesionFalsa(fallar_en="initialize", status=402)
        with patch.object(xv, "_oauth", return_value=ses):
            with self.assertRaises(xv.XUploadError) as ctx:
                xv.upload_video(self.video)
        mensaje = str(ctx.exception)
        self.assertIn("creditos agotados", mensaje)
        self.assertIn("credenciales estan bien", mensaje)

    def test_el_429_dice_que_es_frecuencia(self):
        ses = SesionFalsa(fallar_en="initialize", status=429)
        with patch.object(xv, "_oauth", return_value=ses):
            with self.assertRaises(xv.XUploadError) as ctx:
                xv.upload_video(self.video)
        self.assertIn("frecuencia", str(ctx.exception))

    def test_el_403_menciona_el_plan_de_acceso(self):
        ses = SesionFalsa(fallar_en="initialize", status=403)
        with patch.object(xv, "_oauth", return_value=ses):
            with self.assertRaises(xv.XUploadError) as ctx:
                xv.upload_video(self.video)
        self.assertIn("plan de acceso", str(ctx.exception))

    def test_un_video_inexistente_no_llega_a_la_api(self):
        ses = SesionFalsa()
        with patch.object(xv, "_oauth", return_value=ses):
            with self.assertRaises(FileNotFoundError):
                xv.upload_video(os.path.join(self.tmp, "no_existe.mp4"))
        self.assertEqual(ses.llamadas, [])


class DesdeCarpetaConMetadata(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xmeta_")
        with open(os.path.join(self.tmp, "short.mp4"), "wb") as f:
            f.write(b"\0" * 1024)
        with open(os.path.join(self.tmp, "x_metadata.json"), "w", encoding="utf-8") as f:
            json.dump({"title": "Caral", "description": "Six pyramids.",
                       "tags": ["history"]}, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_publica_con_el_texto_armado(self):
        ses = SesionFalsa()
        with patch.object(xv, "_oauth", return_value=ses):
            res = xv.upload_from_metadata(self.tmp, video_url="https://youtu.be/abc")
        self.assertEqual(res["id"], "POST999")
        self.assertIn("Caral", res["text"])
        self.assertIn("https://youtu.be/abc", res["text"])
        self.assertTrue(res["url"].endswith("POST999"))

    def test_deja_el_resultado_en_disco(self):
        ses = SesionFalsa()
        with patch.object(xv, "_oauth", return_value=ses):
            xv.upload_from_metadata(self.tmp)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "x_upload_result.json")))

    def test_sin_video_falla_antes_de_tocar_la_api(self):
        vacio = tempfile.mkdtemp(prefix="xvacio_")
        try:
            with self.assertRaises(FileNotFoundError):
                xv.upload_from_metadata(vacio)
        finally:
            import shutil
            shutil.rmtree(vacio, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
