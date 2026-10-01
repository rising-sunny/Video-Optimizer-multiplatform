# -*- coding: utf-8 -*-
"""Guardas: Instagram recibe el binario directo (resumable), sin Cloudinary ni URL.

DIAGNOSTICO (2026-09-15/16): dos shorts 9:16 estructuralmente identicos al
documental que Instagram SI acepto el 10-09 (mismo encoder, faststart, H.264
High yuv420p 30 fps, AAC) fallaron tres veces cada uno con "Media upload has
failed with error code 2207076" -- un codigo que NO figura en la documentacion
de Meta -- a los 15 s de crear el contenedor. Cloudinary servia el archivo bien
(200, video/mp4, rangos). O sea: Meta fallando al TRAER el archivo por URL.
Facebook Reels publica el mismo mp4 porque recibe el binario por POST. Ahora
Instagram tambien: `upload_type=resumable` + POST a rupload.facebook.com.

    .venv\\Scripts\\python.exe test_instagram_resumable.py
"""

import io
import os
import tempfile
import unittest
from unittest.mock import patch

from publish import instagram_uploader as ig


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _video(case, size=4096):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    ruta = os.path.join(tmp.name, "reel.mp4")
    with open(ruta, "wb") as fh:
        fh.write(b"\x01" * size)
    return ruta


class LaUriDeSubida(unittest.TestCase):

    def test_usa_la_uri_que_devuelve_meta(self):
        self.assertEqual(ig._resumable_upload_uri({"id": "c1", "uri": "https://rupload.facebook.com/ig-api-upload/v23.0/c1"}),
                         "https://rupload.facebook.com/ig-api-upload/v23.0/c1")

    def test_si_no_viene_la_construye_segun_la_doc(self):
        self.assertEqual(ig._resumable_upload_uri({"id": "c9"}, api_version="v23.0"),
                         "https://rupload.facebook.com/ig-api-upload/v23.0/c9")

    def test_sin_id_ni_uri_es_error(self):
        with self.assertRaises(RuntimeError):
            ig._resumable_upload_uri({})


class ElBinarioVaDirectoAMeta(unittest.TestCase):
    """MEDIDO 2026-09-16: un POST unico de 103 MB se cae; en trozos de 4 MB Meta
    acepta todos. Y solo con Content-Type video/mp4 llega al procesado."""

    def _capturar(self, llamadas, fallar_en=None, red_caida_veces=0):
        estado = {"red": red_caida_veces}

        def fake_post(uri, headers=None, data=None, timeout=None):
            if estado["red"] > 0:
                estado["red"] -= 1
                raise ig.requests.ConnectionError("Remote end closed connection")
            llamadas.append((uri, dict(headers), bytes(data), timeout))
            if fallar_en is not None and int(headers["offset"]) == fallar_en:
                return _Resp(400, {"debug_info": {"type": "ProcessingFailedError",
                                                  "message": "Video Transcoding Error: both HD and SD failed"}})
            return _Resp(200, {"success": True, "message": "Upload successful."})
        return fake_post

    def test_va_en_trozos_con_offset_incremental_y_video_mp4(self):
        ruta = _video(self, size=10_000)
        llamadas, progreso = [], []
        with patch.object(ig.requests, "post", side_effect=self._capturar(llamadas)):
            out = ig._upload_binary_resumable("https://rupload.facebook.com/x", "TOK", ruta,
                                              on_progress=lambda s, t: progreso.append((s, t)), chunk_bytes=4000)
        self.assertTrue(out["success"])
        self.assertEqual([h["offset"] for _, h, _, _ in llamadas], ["0", "4000", "8000"])
        self.assertEqual([len(b) for _, _, b, _ in llamadas], [4000, 4000, 2000])
        self.assertEqual(b"".join(b for _, _, b, _ in llamadas), b"\x01" * 10_000, "se manda el archivo completo y en orden")
        for _, h, _, _ in llamadas:
            self.assertEqual(h["Authorization"], "OAuth TOK")
            self.assertEqual(h["file_size"], "10000")
            self.assertEqual(h["Content-Type"], "video/mp4")
        self.assertEqual(progreso[0], (0, 10_000))
        self.assertEqual(progreso[-1], (10_000, 10_000))

    def test_un_archivo_chico_va_en_un_solo_trozo(self):
        ruta = _video(self, size=5000)
        llamadas = []
        with patch.object(ig.requests, "post", side_effect=self._capturar(llamadas)):
            ig._upload_binary_resumable("https://rupload/x", "T", ruta)
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(llamadas[0][1]["offset"], "0")

    def test_la_red_caida_en_un_trozo_se_reintenta(self):
        ruta = _video(self, size=5000)
        llamadas, esperas = [], []
        with patch.object(ig.requests, "post", side_effect=self._capturar(llamadas, red_caida_veces=2)):
            out = ig._upload_binary_resumable("https://rupload/x", "T", ruta, sleep=esperas.append)
        self.assertTrue(out["success"])
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(len(esperas), 2)

    def test_el_error_del_ultimo_trozo_es_meta_procesando_con_su_detalle(self):
        # El caso real: 24 trozos aceptados y el ultimo (el que completa el
        # archivo) devuelve ProcessingFailedError. Eso es el transcodificador.
        ruta = _video(self, size=10_000)
        llamadas = []
        with patch.object(ig.requests, "post", side_effect=self._capturar(llamadas, fallar_en=8000)):
            with self.assertRaises(RuntimeError) as ctx:
                ig._upload_binary_resumable("https://rupload/x", "T", ruta, chunk_bytes=4000)
        self.assertIn("Meta no pudo procesar el video", str(ctx.exception))
        self.assertIn("Video Transcoding Error", str(ctx.exception))

    def test_un_trozo_intermedio_rechazado_se_distingue(self):
        ruta = _video(self, size=10_000)
        with patch.object(ig.requests, "post", side_effect=self._capturar([], fallar_en=4000)):
            with self.assertRaises(RuntimeError) as ctx:
                ig._upload_binary_resumable("https://rupload/x", "T", ruta, chunk_bytes=4000)
        self.assertIn("trozo @4000 rechazado", str(ctx.exception))

    def test_200_sin_success_tambien_es_error(self):
        ruta = _video(self)
        with patch.object(ig.requests, "post", return_value=_Resp(200, {"success": False, "debug_info": "x"})):
            with self.assertRaises(RuntimeError):
                ig._upload_binary_resumable("https://rupload/x", "T", ruta)


class ElFlujoCompleto(unittest.TestCase):

    def _identity(self):
        return patch.object(ig, "_resolve_instagram_identity",
                            return_value={"access_token": "t", "ig_user_id": "ig1", "instagram_username": "stunning.foh"})

    def test_por_defecto_no_toca_cloudinary(self):
        ruta = _video(self)
        cloud = []
        estados = []
        with self._identity(), \
             patch.object(ig, "UPLOAD_MODE", "resumable"), \
             patch.object(ig, "upload_video_to_cloudinary", side_effect=lambda *a, **k: cloud.append(1)), \
             patch.object(ig, "_create_resumable_container", return_value={"id": "c1", "uri": "https://rupload/c1"}), \
             patch.object(ig, "_upload_binary_resumable", return_value={"success": True}), \
             patch.object(ig, "_wait_for_container_ready", return_value={"status_code": "FINISHED"}), \
             patch.object(ig, "_publish_reel", return_value={"id": "m1"}), \
             patch.object(ig, "_get_media_info", return_value={"permalink": "https://www.instagram.com/reel/zzz/"}):
            out = ig.upload_video(ruta, "titulo", on_status=estados.append)
        self.assertEqual(cloud, [], "el camino resumable no debe subir a Cloudinary")
        self.assertEqual(out["transport"], "resumable")
        self.assertEqual(out["media_id"], "m1")
        self.assertIsNone(out["cloudinary_url"])
        self.assertTrue(any("sin Cloudinary" in e for e in estados))

    def test_el_contenedor_resumable_pide_upload_type_resumable(self):
        capturado = {}

        def fake_request(method, url, **kw):
            capturado.update(method=method, url=url, params=kw.get("params"))
            return {"id": "c1", "uri": "https://rupload/c1"}

        with patch.object(ig, "_request_json", side_effect=fake_request):
            ig._create_resumable_container("ig1", "tok", "hola", share_to_feed=True, api_version="v23.0")
        self.assertEqual(capturado["method"], "POST")
        self.assertTrue(capturado["url"].endswith("/ig1/media"))
        self.assertEqual(capturado["params"]["media_type"], "REELS")
        self.assertEqual(capturado["params"]["upload_type"], "resumable")
        self.assertNotIn("video_url", capturado["params"])

    def test_si_la_directa_falla_cae_al_camino_por_url(self):
        ruta = _video(self)
        estados = []
        with self._identity(), \
             patch.object(ig, "UPLOAD_MODE", "resumable"), \
             patch.object(ig, "_publish_via_resumable", side_effect=RuntimeError("rupload 500")), \
             patch.object(ig, "upload_video_to_cloudinary", return_value={"secure_url": "https://cld/v.mp4", "public_id": "vo/r"}), \
             patch.object(ig, "_create_container_with_retries", return_value=("c2", {"status_code": "FINISHED"})), \
             patch.object(ig, "_publish_reel", return_value={"id": "m2"}), \
             patch.object(ig, "_get_media_info", return_value={"permalink": "https://www.instagram.com/reel/yyy/"}), \
             patch.object(ig, "_cleanup_cloudinary", return_value={"deleted": True}):
            out = ig.upload_video(ruta, "titulo", on_status=estados.append)
        self.assertEqual(out["transport"], "url")
        self.assertEqual(out["cloudinary_url"], "https://cld/v.mp4")
        self.assertTrue(any("probando el camino por URL" in e for e in estados))

    def test_instagram_upload_mode_url_salta_la_directa(self):
        ruta = _video(self)
        directa = []
        with self._identity(), \
             patch.object(ig, "UPLOAD_MODE", "url"), \
             patch.object(ig, "_publish_via_resumable", side_effect=lambda *a, **k: directa.append(1)), \
             patch.object(ig, "upload_video_to_cloudinary", return_value={"secure_url": "https://cld/v.mp4", "public_id": "vo/r"}), \
             patch.object(ig, "_create_container_with_retries", return_value=("c2", {"status_code": "FINISHED"})), \
             patch.object(ig, "_publish_reel", return_value={"id": "m2"}), \
             patch.object(ig, "_get_media_info", return_value={"permalink": "x"}), \
             patch.object(ig, "_cleanup_cloudinary", return_value={"deleted": True}):
            out = ig.upload_video(ruta, "titulo")
        self.assertEqual(directa, [])
        self.assertEqual(out["transport"], "url")


class LaFuenteNoVuelveAtras(unittest.TestCase):

    def test_resumable_es_el_camino_por_defecto(self):
        fuente = io.open("publish/instagram_uploader.py", encoding="utf-8", errors="replace").read()
        self.assertIn('os.getenv("INSTAGRAM_UPLOAD_MODE", "resumable")', fuente)
        self.assertIn("rupload.facebook.com/ig-api-upload", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
