import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import facebook_uploader


class FacebookUploaderTests(unittest.TestCase):
    def test_upload_from_metadata_prefers_facebook_metadata_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "metadata.json").write_text(
                json.dumps(
                    {
                        "title": "YouTube Title",
                        "description": "YouTube description",
                    }
                ),
                encoding="utf-8",
            )
            (root / "facebook_metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Roswell 1947",
                        "description": "Recovered wreckage in the New Mexico desert.",
                    }
                ),
                encoding="utf-8",
            )
            (root / "short.mp4").write_bytes(b"fake-video")

            fake_result = {
                "video_id": "123456789",
                "url": "https://www.facebook.com/reel/123456789",
                "status": "published",
                "page_id": "987654321",
                "page_name": "Stunning Revelations",
            }

            with patch.object(facebook_uploader, "upload_video", return_value=fake_result) as upload_mock:
                result = facebook_uploader.upload_from_metadata(str(root), video_state="PUBLISHED")

            self.assertEqual(result["video_id"], "123456789")
            upload_mock.assert_called_once()
            self.assertEqual(upload_mock.call_args.kwargs["title"], "Roswell 1947")
            self.assertEqual(upload_mock.call_args.kwargs["description"], "Recovered wreckage in the New Mexico desert.")
            self.assertEqual(upload_mock.call_args.kwargs["video_state"], "PUBLISHED")

            result_path = root / "facebook_upload_result.json"
            self.assertTrue(result_path.exists())
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["video_id"], "123456789")
            self.assertEqual(saved["url"], "https://www.facebook.com/reel/123456789")
            self.assertEqual(saved["video_state"], "PUBLISHED")
            archive_files = list(root.glob("facebook_upload_result_*.json"))
            self.assertEqual(len(archive_files), 1)
            archived = json.loads(archive_files[0].read_text(encoding="utf-8"))
            self.assertEqual(archived["video_id"], "123456789")

    def test_upload_from_metadata_persists_scheduled_facebook_reel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "facebook_metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Roswell: Scheduled",
                        "description": "A scheduled Facebook Reel.",
                    }
                ),
                encoding="utf-8",
            )
            (root / "short.mp4").write_bytes(b"fake-video")

            fake_result = {
                "video_id": "555666777",
                "url": None,
                "permalink_url": "https://www.facebook.com/reel/555666777",
                "status": "scheduled",
                "page_id": "987654321",
                "page_name": "Stunning Revelations",
            }

            with patch.object(facebook_uploader, "upload_video", return_value=fake_result) as upload_mock:
                result = facebook_uploader.upload_from_metadata(
                    str(root),
                    video_state="PUBLISHED",
                    scheduled_publish_time="2099-01-01T12:00:00Z",
                )

            self.assertEqual(result["video_id"], "555666777")
            upload_mock.assert_called_once()
            self.assertEqual(upload_mock.call_args.kwargs["scheduled_publish_time"], "2099-01-01T12:00:00Z")

            result_path = root / "facebook_upload_result.json"
            self.assertTrue(result_path.exists())
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["video_id"], "555666777")
            self.assertEqual(saved["permalink_url"], "https://www.facebook.com/reel/555666777")
            self.assertEqual(saved["video_state"], "SCHEDULED")
            self.assertTrue(saved["scheduled"])
            self.assertEqual(saved["publish_at"], "2099-01-01T12:00:00Z")
            archive_files = list(root.glob("facebook_upload_result_*.json"))
            self.assertEqual(len(archive_files), 1)


class PageTokenResolutionTests(unittest.TestCase):
    """Un FACEBOOK_PAGE_ACCESS_TOKEN vencido tumbaba la subida entera.

    Facebook contesta error 190 con un texto sobre permisos faltantes
    ("pages_read_engagement, pages_manage_metadata, ...") aunque el user token
    tenga TODOS esos scopes: el problema es que el page token murio. El mensaje
    manda a buscar permisos y hace perder el tiempo.
    """

    ENV = {
        "FACEBOOK_PAGE_ACCESS_TOKEN": "page-token",
        "FACEBOOK_USER_ACCESS_TOKEN": "user-token",
        "FACEBOOK_PAGE_ID": "999",
    }

    def _env(self, name, default=None):
        return self.ENV.get(name, default)

    def test_valid_page_token_is_used_as_is(self):
        with patch.object(facebook_uploader, "_env", self._env),              patch.object(facebook_uploader, "_request_json",
                          return_value={"id": "999"}) as req:
            token, page_id = facebook_uploader._resolve_page_access_token()
        self.assertEqual(token, "page-token")
        self.assertEqual(page_id, "999")
        self.assertEqual(req.call_count, 1)  # solo el chequeo de validez

    def test_dead_page_token_falls_back_to_deriving_from_user_token(self):
        calls = []

        def fake(method, url, **kwargs):
            calls.append(url)
            if len(calls) == 1:                      # validacion del page token
                raise RuntimeError("Facebook API error 190: token vencido")
            return {"id": "999", "name": "Pagina", "access_token": "fresco"}

        with patch.object(facebook_uploader, "_env", self._env),              patch.object(facebook_uploader, "_request_json", side_effect=fake):
            token, page_id = facebook_uploader._resolve_page_access_token()

        self.assertEqual(token, "fresco",
                         "no se derivo un token nuevo teniendo un user token sano")
        self.assertEqual(page_id, "999")

    def test_network_error_does_not_discard_a_good_page_token(self):
        import requests

        def fake(method, url, **kwargs):
            raise requests.exceptions.ConnectionError("DNS caido")

        with patch.object(facebook_uploader, "_env", self._env),              patch.object(facebook_uploader, "_request_json", side_effect=fake):
            token, _ = facebook_uploader._resolve_page_access_token()
        self.assertEqual(token, "page-token",
                         "un corte de red no puede invalidar el token configurado")

    def test_error_names_the_page_and_lists_the_manageable_ones(self):
        def fake(method, url, **kwargs):
            if url.endswith("/me"):
                raise RuntimeError("Facebook API error 190: token vencido")
            if url.endswith("/me/accounts"):
                return {"data": [{"id": "111", "name": "Otra Pagina"}]}
            return {"id": "999", "name": "Pagina"}   # 200 pero SIN access_token

        with patch.object(facebook_uploader, "_env", self._env),              patch.object(facebook_uploader, "_request_json", side_effect=fake):
            with self.assertRaises(RuntimeError) as ctx:
                facebook_uploader._resolve_page_access_token()

        mensaje = str(ctx.exception)
        self.assertIn("999", mensaje, "el error no dice de que pagina habla")
        self.assertIn("Otra Pagina", mensaje, "el error no lista las paginas disponibles")
        self.assertIn("vencido", mensaje.lower())

    def test_error_explains_granular_scopes_when_the_page_is_not_granted(self):
        """El caso real: rol de admin en el Business, pero el permiso del token
        solo alcanza a OTRA pagina. Aconsejar 'darse rol de admin' hace perder
        el tiempo porque el rol ya esta; hay que reautorizar la app."""

        def fake(method, url, **kwargs):
            if url.endswith("/me"):
                raise RuntimeError("Facebook API error 190: token vencido")
            if url.endswith("/me/accounts"):
                return {"data": [{"id": "111", "name": "Otra Pagina"}]}
            if url.endswith("/debug_token"):
                return {"data": {"granular_scopes": [
                    {"scope": "pages_manage_posts", "target_ids": ["111"]},
                    {"scope": "pages_show_list", "target_ids": ["111"]},
                ]}}
            return {"id": "999", "name": "Pagina"}

        with patch.object(facebook_uploader, "_env", self._env),              patch.object(facebook_uploader, "_request_json", side_effect=fake):
            with self.assertRaises(RuntimeError) as ctx:
                facebook_uploader._resolve_page_access_token()

        mensaje = str(ctx.exception)
        self.assertIn("pages_manage_posts", mensaje)
        self.assertIn("reautorizar", mensaje.lower())
        self.assertNotIn("rol de administrador en la pagina", mensaje.lower())

    def test_no_granular_noise_when_the_page_is_covered(self):
        """Si el permiso SI cubre la pagina, el problema es otro: no confundir."""

        def fake(method, url, **kwargs):
            if url.endswith("/me"):
                raise RuntimeError("Facebook API error 190: token vencido")
            if url.endswith("/me/accounts"):
                return {"data": [{"id": "999", "name": "La Pagina"}]}
            if url.endswith("/debug_token"):
                return {"data": {"granular_scopes": [
                    {"scope": "pages_manage_posts", "target_ids": ["999"]},
                ]}}
            return {"id": "999", "name": "Pagina"}

        with patch.object(facebook_uploader, "_env", self._env),              patch.object(facebook_uploader, "_request_json", side_effect=fake):
            with self.assertRaises(RuntimeError) as ctx:
                facebook_uploader._resolve_page_access_token()

        self.assertNotIn("reautorizar", str(ctx.exception).lower())


    def test_no_user_token_usa_el_page_token_pero_verifica_la_pagina(self):
        """Sin user token no hay plan B, pero SI se confirma la pagina.

        Antes este test exigia CERO llamadas ("sin plan B no tiene sentido
        gastar una"). Ese contrato cambio a proposito el 2026-09-02: una llamada
        es mas barata que publicar en la pagina equivocada, que es lo que pasaba
        al cambiar FACEBOOK_PAGE_ID dejando el token viejo.
        """
        env = {"FACEBOOK_PAGE_ACCESS_TOKEN": "page-token", "FACEBOOK_PAGE_ID": "999"}
        with patch.object(facebook_uploader, "_env", lambda n, d=None: env.get(n, d)), \
             patch.object(facebook_uploader, "_request_json",
                          return_value={"id": "999"}) as req:
            token, _ = facebook_uploader._resolve_page_access_token()
        self.assertEqual(token, "page-token")
        self.assertEqual(req.call_count, 1, "una sola llamada: vitalidad e identidad juntas")


class PaginaCorrectaTests(unittest.TestCase):
    """El token puede ser valido y aun asi apuntar a OTRA pagina.

    BUG (2026-09-02): al abrir la pagina del canal nuevo (Stunning Facts of
    History, 1291553907375982) alcanzaba con cambiar FACEBOOK_PAGE_ID y dejar el
    token viejo para que el resolver devolviera el token de Stunning Revelations
    junto al ID de la pagina nueva. Solo se validaba que el token FUNCIONARA,
    nunca a que pagina pertenece. Publicar en la pagina equivocada es peor que
    no publicar.
    """

    ENV = {
        "FACEBOOK_PAGE_ACCESS_TOKEN": "token-de-la-pagina-vieja",
        "FACEBOOK_USER_ACCESS_TOKEN": "user-token",
        "FACEBOOK_PAGE_ID": "1291553907375982",     # la pagina NUEVA
    }
    PAGINA_VIEJA = "533073909895353"

    def _env(self, name, default=None):
        return self.ENV.get(name, default)

    def test_un_token_de_otra_pagina_no_se_usa(self):
        llamadas = []

        def fake(method, url, **kwargs):
            llamadas.append(url)
            if len(llamadas) == 1:          # a quien pertenece el page token
                return {"id": self.PAGINA_VIEJA}
            # derivacion desde el user token para la pagina pedida
            return {"id": self.ENV["FACEBOOK_PAGE_ID"], "name": "Stunning Facts of History",
                    "access_token": "token-de-la-pagina-nueva"}

        with patch.object(facebook_uploader, "_env", self._env), \
             patch.object(facebook_uploader, "_request_json", side_effect=fake):
            token, page_id = facebook_uploader._resolve_page_access_token()

        self.assertEqual(token, "token-de-la-pagina-nueva",
                         "siguio usando el token de la pagina vieja")
        self.assertEqual(page_id, self.ENV["FACEBOOK_PAGE_ID"])

    def test_sin_user_token_falla_en_vez_de_publicar_en_la_pagina_equivocada(self):
        env = dict(self.ENV)
        env.pop("FACEBOOK_USER_ACCESS_TOKEN")

        with patch.object(facebook_uploader, "_env", lambda n, d=None: env.get(n, d)), \
             patch.object(facebook_uploader, "_request_json",
                          return_value={"id": self.PAGINA_VIEJA}):
            with self.assertRaises(RuntimeError) as ctx:
                facebook_uploader._resolve_page_access_token()

        mensaje = str(ctx.exception)
        self.assertIn(self.PAGINA_VIEJA, mensaje, "no dice de que pagina es el token")
        self.assertIn(self.ENV["FACEBOOK_PAGE_ID"], mensaje, "no dice cual se pidio")
        self.assertIn(".env.txt", mensaje, "no recuerda el archivo que viaja al VPS")

    def test_el_token_de_la_pagina_correcta_se_usa_tal_cual(self):
        with patch.object(facebook_uploader, "_env", self._env), \
             patch.object(facebook_uploader, "_request_json",
                          return_value={"id": self.ENV["FACEBOOK_PAGE_ID"]}):
            token, page_id = facebook_uploader._resolve_page_access_token()
        self.assertEqual(token, "token-de-la-pagina-vieja")   # el valor de ENV
        self.assertEqual(page_id, self.ENV["FACEBOOK_PAGE_ID"])

    def test_si_no_se_puede_averiguar_la_pagina_no_se_bloquea(self):
        # Sin red no se sabe de quien es el token: se sigue con la logica de
        # siempre en vez de frenar una publicacion que quizas estaba bien.
        import requests

        with patch.object(facebook_uploader, "_env", self._env), \
             patch.object(facebook_uploader, "_request_json",
                          side_effect=requests.exceptions.ConnectionError("sin red")):
            token, _ = facebook_uploader._resolve_page_access_token()
        self.assertEqual(token, "token-de-la-pagina-vieja")


class VerificarNoPuedeTumbarUnaPublicacion(unittest.TestCase):
    """BUG (2026-09-03): el reel de Caral se publico y el pipeline dijo error.

    `_wait_for_reel_ready` corre DESPUES de publicar. Justo despues, Facebook
    devuelve a veces error 100 ("Object with ID '2305003476920318' does not
    exist") sobre el id que el mismo acaba de emitir -- consistencia eventual.
    Comprobado a posteriori: el reel estaba publicado y visible en la pagina.
    Que esa consulta reventara convertia un exito en un fallo.
    """

    ERROR_100 = RuntimeError(
        "Facebook API error 100: Unsupported get request. Object with ID "
        "'2305003476920318' does not exist, cannot be loaded due to missing permissions"
    )

    def test_el_error_100_no_se_propaga(self):
        with patch.object(facebook_uploader, "get_reel_status", side_effect=self.ERROR_100), \
             patch.object(facebook_uploader, "POLL_INTERVAL_SECONDS", 0):
            estado = facebook_uploader._wait_for_reel_ready(
                video_id="2305003476920318", page_access_token="t", timeout_seconds=5)
        self.assertIsInstance(estado, dict)
        self.assertIn("status_check_failed", estado)

    def test_si_se_recupera_devuelve_el_estado_real(self):
        llamadas = []
        bueno = {"status": {"video_status": "ready"}}

        def flaky(**kw):
            llamadas.append(1)
            if len(llamadas) < 3:
                raise self.ERROR_100
            return bueno

        with patch.object(facebook_uploader, "get_reel_status", side_effect=flaky), \
             patch.object(facebook_uploader, "POLL_INTERVAL_SECONDS", 0):
            estado = facebook_uploader._wait_for_reel_ready(
                video_id="1", page_access_token="t", timeout_seconds=5)
        self.assertEqual(estado, bueno, "no reintento tras el error transitorio")

    def test_si_nunca_contesta_abandona_rapido(self):
        """BUG (2026-09-09): el trabajo del VPS supero el tope de 600s de SSH.

        Al hacer que el poll reintentara ante el error 100, un fallo permanente
        pasaba a consumir los 300s completos de POLL_TIMEOUT_SECONDS. Sumado a
        la subida, el `ssh` se cortaba por timeout y Facebook quedaba sin
        publicar. El reel ya esta publicado cuando corre este poll: confirmarlo
        no vale cinco minutos.
        """
        import time as _t

        reloj = {"t": 1000.0}
        with patch.object(facebook_uploader, "get_reel_status", side_effect=self.ERROR_100), \
             patch.object(facebook_uploader, "POLL_INTERVAL_SECONDS", 0), \
             patch.object(facebook_uploader, "STATUS_ERROR_GRACE_SECONDS", 45), \
             patch.object(_t, "sleep", lambda s: reloj.__setitem__("t", reloj["t"] + 5)), \
             patch.object(_t, "time", lambda: reloj["t"]):
            estado = facebook_uploader._wait_for_reel_ready(
                video_id="1", page_access_token="t", timeout_seconds=300)

        transcurrido = reloj["t"] - 1000.0
        self.assertIn("status_check_failed", estado)
        self.assertLessEqual(transcurrido, 60,
                             "gasto %.0fs esperando algo que nunca iba a contestar"
                             % transcurrido)

    def test_un_video_que_tarda_en_procesarse_conserva_el_plazo_largo(self):
        # Si la API SI contesta, el video puede estar transcodificando de
        # verdad y ahi los 300s tienen sentido.
        respuestas = [{"status": {"video_status": "processing"}}] * 20 + \
                     [{"status": {"video_status": "ready"}}]
        with patch.object(facebook_uploader, "get_reel_status", side_effect=respuestas), \
             patch.object(facebook_uploader, "POLL_INTERVAL_SECONDS", 0), \
             patch.object(facebook_uploader, "STATUS_ERROR_GRACE_SECONDS", 45):
            estado = facebook_uploader._wait_for_reel_ready(
                video_id="1", page_access_token="t", timeout_seconds=300)
        self.assertEqual(estado["status"]["video_status"], "ready")

    def test_el_camino_feliz_no_cambia(self):
        bueno = {"status": {"video_status": "published"}}
        with patch.object(facebook_uploader, "get_reel_status", return_value=bueno), \
             patch.object(facebook_uploader, "POLL_INTERVAL_SECONDS", 0):
            estado = facebook_uploader._wait_for_reel_ready(
                video_id="1", page_access_token="t", timeout_seconds=5)
        self.assertEqual(estado, bueno)


class TokenRedactionTests(unittest.TestCase):
    """El token viaja en la query string y urllib3 mete la URL entera en el
    texto de la excepcion. Asi es como un token termino pegado en un log."""

    def test_network_error_does_not_leak_the_token(self):
        import requests

        url = "https://graph.facebook.com/v23.0/me?access_token=SECRETO123&fields=id"
        boom = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='graph.facebook.com', port=443): "
            "Max retries exceeded with url: %s" % url
        )

        with patch.object(facebook_uploader.requests, "request", side_effect=boom):
            with self.assertRaises(Exception) as ctx:
                facebook_uploader._request_json("GET", url)

        import traceback
        texto = "".join(traceback.format_exception(
            type(ctx.exception), ctx.exception, ctx.exception.__traceback__))
        self.assertNotIn("SECRETO123", texto, "el token se filtro en el traceback")
        self.assertIn("REDACTED", str(ctx.exception))

    def test_redaction_leaves_the_rest_readable(self):
        limpio = facebook_uploader._redact_tokens(
            "GET /me?access_token=abc123&fields=id,name failed")
        self.assertIn("fields=id,name", limpio)
        self.assertNotIn("abc123", limpio)

    def test_still_a_requests_exception(self):
        import requests
        self.assertTrue(issubclass(facebook_uploader.FacebookRequestError,
                                   requests.exceptions.RequestException),
                        "romperia la deteccion de 'sin red' al validar el token")


if __name__ == "__main__":
    unittest.main()
