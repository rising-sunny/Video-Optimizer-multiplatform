# -*- coding: utf-8 -*-
"""Guardas del borrador de TikTok (tiktok_uploader).

Lo que se rompe en silencio:
  - el PKCE de escritorio de TikTok va en HEX: con base64url (como Google) el login falla;
  - la cuenta de trozos: video_size // chunk_size y el ultimo se lleva el resto (el
    ejemplo de la documentacion: 50.000.123 bytes en trozos de 10.000.000 son 5);
  - el borrador no lleva texto: si el titulo y la descripcion no salen por Telegram,
    el usuario se queda sin que pegar;
  - un token vencido se renueva solo, sin abrir el navegador;
  - un documental de 15 min no tiene que gastar uno de los 5 borradores del dia.

    .venv\\Scripts\\python.exe test_tiktok_uploader.py

No toca la red: API de TikTok falsa y Telegram falso.
"""

import hashlib
import io
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from unittest.mock import patch, Mock

from publish import tiktok_uploader as tu

MB = 1024 * 1024
ENV = {"TIKTOK_CLIENT_KEY": "ck_test", "TIKTOK_CLIENT_SECRET": "cs_test"}
SHORT = {"duration": 58.0, "width": 1080, "height": 1920, "fps": 30.0}


def _fake_env(name, default=""):
    return ENV.get(name, default)


class _R:
    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._p = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._p is None:
            raise ValueError("sin json")
        return self._p


class TikTokFalso:
    """Simula la API de TikTok y anota cada llamada."""

    def __init__(self, estados=("SEND_TO_USER_INBOX",), init_error=None, fail_reason=None):
        self.llamadas = []
        self.init_body = None
        self.rangos = []
        self.token_posts = []
        self.estados = list(estados)
        self.init_error = init_error
        self.fail_reason = fail_reason

    def post(self, url, data=None, headers=None, timeout=None):      # endpoint del token
        self.token_posts.append(dict(data or {}))
        return _R(200, {"access_token": "act.NUEVO", "refresh_token": "rft.NUEVO", "open_id": "o1",
                        "scope": "user.info.basic,video.upload", "expires_in": 86400,
                        "refresh_expires_in": 31536000, "token_type": "Bearer"})

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        ruta = url.replace(tu.API, "")
        self.llamadas.append(ruta)
        if ruta == "/user/info/":
            return _R(200, {"data": {"user": {"display_name": "Stunning Facts of History",
                                              "open_id": "o1"}}, "error": {"code": "ok"}})
        if ruta == "/post/publish/inbox/video/init/":
            self.init_body = json
            if self.init_error:
                status, code = self.init_error
                return _R(status, {"error": {"code": code, "message": "boom", "log_id": "L1"}})
            return _R(200, {"data": {"publish_id": "v_inbox_file~v2.123",
                                     "upload_url": "https://open-upload.tiktokapis.com/video/?t=x"},
                            "error": {"code": "ok"}})
        if ruta == "/video/list/":
            # Dos paginas: la primera pide seguir con el cursor, la segunda cierra.
            self.list_bodies = getattr(self, "list_bodies", []) + [json]
            if not (json or {}).get("cursor"):
                return _R(200, {"data": {"videos": [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}],
                                         "cursor": 1700000000000, "has_more": True}, "error": {"code": "ok"}})
            return _R(200, {"data": {"videos": [{"id": "3", "title": "C"}], "cursor": 1600000000000,
                                     "has_more": False}, "error": {"code": "ok"}})
        if ruta == "/post/publish/status/fetch/":
            if self.fail_reason:
                return _R(200, {"data": {"status": "FAILED", "fail_reason": self.fail_reason},
                                "error": {"code": "ok"}})
            estado = self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]
            return _R(200, {"data": {"status": estado, "uploaded_bytes": 1}, "error": {"code": "ok"}})
        return _R(404, {"error": {"code": "not_found"}})

    def put(self, url, data=None, headers=None, timeout=None):
        self.rangos.append(headers["Content-Range"])
        assert int(headers["Content-Length"]) == len(data)
        bytes_, total = headers["Content-Range"].split(" ")[1].split("/")
        ultimo = int(bytes_.split("-")[1])
        return _R(201 if ultimo == int(total) - 1 else 206, text="")


def _token(**cambios):
    ahora = time.time()
    base = {"access_token": "act.VIEJO", "refresh_token": "rft.VIEJO", "open_id": "o1",
            "scope": "user.info.basic,video.upload", "expires_at": ahora + 3600,
            "refresh_expires_at": ahora + 86400 * 300, "client_key": "ck_test"}
    base.update(cambios)
    return base


class ConTokenTemporal(unittest.TestCase):
    """Token y .env falsos: nunca se toca el token_tiktok.json real."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tiktok_")
        self.token_path = os.path.join(self.tmp, "token_tiktok.json")
        self._patches = [patch.object(tu, "TOKEN_PATH", tu.Path(self.token_path)),
                         patch.object(tu, "_env", side_effect=_fake_env),
                         patch.object(tu, "probe_video", return_value=dict(SHORT))]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def guardar_token(self, **cambios):
        tu.save_token(_token(**cambios))

    def video(self, nombre="short.mp4", size=1024):
        ruta = os.path.join(self.tmp, nombre)
        with open(ruta, "wb") as f:
            f.write(b"\0" * size)
        return ruta


class Pkce(unittest.TestCase):

    def test_el_challenge_es_sha256_en_hex(self):
        verifier = tu.make_code_verifier()
        self.assertEqual(tu.code_challenge(verifier), hashlib.sha256(verifier.encode()).hexdigest())
        self.assertRegex(tu.code_challenge(verifier), r"^[0-9a-f]{64}$", "TikTok escritorio pide HEX, no base64url")

    def test_el_verifier_cumple_largo_y_caracteres(self):
        v = tu.make_code_verifier()
        self.assertTrue(43 <= len(v) <= 128)
        self.assertRegex(v, r"^[A-Za-z0-9\-._~]+$")

    def test_url_de_autorizacion(self):
        url = tu.build_authorize_url("ck", "http://127.0.0.1:8723/callback/", "st", "ch")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertTrue(url.startswith("https://www.tiktok.com/v2/auth/authorize/"))
        self.assertEqual(q["scope"], ["user.info.basic,video.upload,video.list"])
        self.assertEqual(q["redirect_uri"], ["http://127.0.0.1:8723/callback/"])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["response_type"], ["code"])


class VueltaDelLogin(unittest.TestCase):

    def test_devuelve_el_code_ya_decodificado(self):
        self.assertEqual(tu.parse_callback("/callback/?code=abc%2A1&state=s1&scopes=video.upload", "s1"), "abc*1")

    def test_state_distinto_falla(self):
        with self.assertRaises(tu.TikTokAuthError):
            tu.parse_callback("/callback/?code=abc&state=otro", "s1")

    def test_el_error_de_tiktok_se_explica(self):
        with self.assertRaises(tu.TikTokAuthError) as ctx:
            tu.parse_callback("/callback/?error=access_denied&error_description=User+denied&state=s1", "s1")
        self.assertIn("cancelaste", str(ctx.exception))


class LoginCompleto(ConTokenTemporal):

    def test_el_servidor_local_recibe_el_code_y_el_challenge_cierra(self):
        # De punta a punta: el challenge de la URL tiene que ser el SHA256 (hex) del
        # verifier que despues se manda al canjear el code.
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
        s.close()
        avisos, salida, api = [], {}, TikTokFalso()
        with patch.object(tu, "_redirect_port", return_value=puerto):
            hilo = threading.Thread(target=lambda: salida.update(
                token=tu.authorize(open_browser=False, timeout_s=15, on_status=avisos.append, http=api)))
            hilo.start()
            url = None
            for _ in range(100):
                url = next((a.split(": ", 1)[1] for a in avisos if "tiktok.com/v2/auth" in a), None)
                if url:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(url, "no aviso la direccion de login")
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            sin_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with sin_proxy.open(
                    f"http://127.0.0.1:{puerto}/callback/?code=CODE123&state={q['state'][0]}", timeout=10) as r:
                self.assertEqual(r.status, 200)
                page = r.read().decode('utf-8')
                self.assertIn('Autorización recibida', page)
                self.assertNotIn('cuenta de TikTok quedó conectada', page)
            hilo.join(15)
        canje = api.token_posts[0]
        self.assertEqual(canje["code"], "CODE123")
        self.assertEqual(canje["grant_type"], "authorization_code")
        self.assertEqual(hashlib.sha256(canje["code_verifier"].encode()).hexdigest(), q["code_challenge"][0])
        self.assertEqual(salida["token"]["access_token"], "act.NUEVO")
        self.assertEqual(tu.load_token()["refresh_token"], "rft.NUEVO", "no guardo el token")

    def test_el_rechazo_del_token_conserva_detalle_y_no_guarda_permiso(self):
        server = Mock()
        server.wait.return_value = 'CODE_TEST_123'
        api = Mock()
        api.post.return_value = _R(200, {'error': 'invalid_client',
                                       'error_description': 'Client key or secret is incorrect.',
                                       'log_id': 'TT_LOG_123'})
        avisos = []
        with patch.object(tu, '_CallbackServer', return_value=server), patch.object(tu.webbrowser, 'open', return_value=True):
            with self.assertRaises(tu.TikTokAuthError) as ctx:
                tu.authorize(on_status=avisos.append, http=api)
        self.assertIn('Client key or secret is incorrect.', str(ctx.exception))
        self.assertIn('TT_LOG_123', str(ctx.exception))
        self.assertIn('--setup', str(ctx.exception))
        self.assertTrue(any('autorización recibida' in m for m in avisos))
        self.assertFalse(any('cuenta conectada' in m for m in avisos))
        self.assertIsNone(tu.load_token())
        server.close.assert_called_once()


class ConfigurarCredenciales(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = tu.Path(self.tmp.name) / '.env'
        self.original = '# otros ajustes\nOTHER_SECRET=preserve_this\nTIKTOK_CLIENT_KEY=old_key\nTIKTOK_CLIENT_SECRET=old_secret\n'
        self.path.write_text(self.original, encoding='utf-8')
        env = patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)
        self.messages = []

    def setup(self, key='new_key', secret='new_secret'):
        tu.setup_credentials(path=self.path, input_fn=lambda _: key, secret_fn=lambda _: secret,
                             on_status=self.messages.append)

    def test_guardado_del_par_preserva_otros_ajustes_y_actualiza_el_proceso(self):
        from dotenv import dotenv_values
        os.environ.update(TIKTOK_CLIENT_KEY='inherited_key', TIKTOK_CLIENT_SECRET='inherited_secret')
        self.setup()
        values = dotenv_values(self.path)
        self.assertEqual(values['OTHER_SECRET'], 'preserve_this')
        self.assertIn('# otros ajustes', self.path.read_text(encoding='utf-8'))
        self.assertEqual(values['TIKTOK_CLIENT_KEY'], 'new_key')
        self.assertEqual(values['TIKTOK_CLIENT_SECRET'], 'new_secret')
        self.assertEqual(tu._client_credentials(), ('new_key', 'new_secret'))
        self.assertNotIn('new_key', str(self.messages))
        self.assertNotIn('new_secret', str(self.messages))
        self.assertEqual(list(tu.Path(self.tmp.name).glob('.env.tiktok-*')), [])

    def test_informa_si_son_los_mismos_valores_sin_mostrarlos(self):
        self.setup(key='old_key', secret='old_secret')
        self.assertIn('coinciden', str(self.messages))
        self.assertNotIn('old_secret', str(self.messages))

    def test_entrada_vacia_mascara_y_espacios_no_sobrescriben_env(self):
        for key, secret in [('', 'secret'), ('key', ''), ('key', '********'), ('key', 'not a secret')]:
            with self.subTest(key=key, secret=secret), self.assertRaises(tu.TikTokAuthError):
                self.setup(key, secret)
            self.assertEqual(self.path.read_text(encoding='utf-8'), self.original)

    def test_cancelar_secreto_no_deja_la_clave_a_medio_guardar(self):
        with self.assertRaises(tu.TikTokAuthError):
            tu.setup_credentials(path=self.path, input_fn=lambda _: 'new_key',
                                 secret_fn=Mock(side_effect=KeyboardInterrupt), on_status=self.messages.append)
        self.assertEqual(self.path.read_text(encoding='utf-8'), self.original)

    def test_error_de_guardado_conserva_archivo_y_entorno(self):
        os.environ.update(TIKTOK_CLIENT_KEY='inherited_key', TIKTOK_CLIENT_SECRET='inherited_secret')
        with patch.object(tu.os, 'replace', side_effect=PermissionError), self.assertRaises(tu.TikTokAuthError):
            self.setup()
        self.assertEqual(self.path.read_text(encoding='utf-8'), self.original)
        self.assertEqual(tu._client_credentials(), ('inherited_key', 'inherited_secret'))
        self.assertEqual(list(tu.Path(self.tmp.name).glob('.env.tiktok-*')), [])

    def test_setup_cli_usa_los_valores_recien_guardados_en_la_autorizacion(self):
        calls = []
        def authorize(**kwargs):
            calls.append(tu._client_credentials())
            return _token()
        with patch.object(tu, 'ROOT', self.path.parent), patch('builtins.input', return_value='new_key'), \
                patch('getpass.getpass', return_value='new_secret'), patch.object(tu, 'authorize', side_effect=authorize), \
                patch.object(tu, 'get_user_info', return_value={'display_name': 'Test'}), \
                patch('sys.stdout', new=io.StringIO()) as output:
            self.assertEqual(tu.main(['--setup']), 0)
            self.assertNotIn('new_secret', output.getvalue())
        self.assertEqual(calls, [('new_key', 'new_secret')])


class DetalleOauth(unittest.TestCase):

    def test_el_error_no_revela_secretos_ni_sus_variantes_codificadas(self):
        data = {'client_key': 'client_test', 'client_secret': 'secret+example/test',
                'code': 'code_test_123', 'code_verifier': 'verifier_test_123', 'refresh_token': 'refresh_test_123'}
        secret_text = ' '.join(list(data.values()) + [urllib.parse.quote_plus(data['client_secret']), 'act.test_token'])
        api = Mock()
        api.post.return_value = _R(400, {'error': 'invalid_client', 'error_description': secret_text,
                                       'access_token': 'act.test_token', 'log_id': 'LOG_987'})
        with self.assertRaises(tu.TikTokAuthError) as ctx:
            tu._token_request(data, http=api)
        text = str(ctx.exception)
        self.assertIn('[oculto]', text)
        self.assertIn('LOG_987', text)
        for value in list(data.values()) + ['act.test_token', urllib.parse.quote_plus(data['client_secret'])]:
            self.assertNotIn(value, text)

    def test_error_de_red_no_expone_el_secreto(self):
        api = Mock()
        api.post.side_effect = tu.requests.ConnectionError('secret=secret_test_abc')
        with self.assertRaises(tu.TikTokAuthError) as ctx:
            tu._token_request({'client_secret': 'secret_test_abc'}, http=api)
        self.assertNotIn('secret_test_abc', str(ctx.exception))

    def test_respuesta_no_json_no_vuelca_el_cuerpo(self):
        api = Mock()
        api.post.return_value = _R(502, text='upstream error with private diagnostic')
        with self.assertRaises(tu.TikTokAuthError) as ctx:
            tu._token_request({}, http=api)
        self.assertIn('HTTP 502', str(ctx.exception))
        self.assertNotIn('private diagnostic', str(ctx.exception))


class Trozos(unittest.TestCase):

    def test_el_ejemplo_de_la_documentacion_de_tiktok(self):
        chunk, total = tu.plan_chunks(50_000_123, 10_000_000)
        self.assertEqual((chunk, total), (10_000_000, 5))
        rangos = tu.chunk_ranges(50_000_123, chunk, total)
        self.assertEqual(rangos[-1], (40_000_000, 50_000_122), "el ultimo trozo se lleva los 123 bytes")

    def test_menos_de_5_mb_va_entero(self):
        self.assertEqual(tu.plan_chunks(3 * MB), (3 * MB, 1))

    def test_hasta_un_trozo_va_entero(self):
        self.assertEqual(tu.plan_chunks(7 * MB), (7 * MB, 1))

    def test_el_short_de_petra_va_entero(self):
        # 2026-09-27: 20.885.618 bytes con trozos de 10 MiB daba (10 MiB, 1) y TikTok
        # contesto "The chunk size is invalid". Un solo trozo = el archivo entero.
        self.assertEqual(tu.plan_chunks(20_885_618), (20_885_618, 1))

    def test_entre_uno_y_dos_trozos_va_entero(self):
        for size in (10 * MB + 1, 15 * MB, 20 * MB - 1):
            self.assertEqual(tu.plan_chunks(size), (size, 1), size)

    def test_si_no_entra_entero_van_al_menos_dos_trozos(self):
        chunk, total = tu.plan_chunks(100 * MB, chunk_size=64 * MB)
        self.assertEqual(total, 2)
        self.assertLessEqual(chunk, tu.MAX_CHUNK)

    def test_nunca_pasa_los_limites_y_cubre_todos_los_bytes(self):
        for size in (5 * MB, 10 * MB + 1, 20_885_618, 25 * MB, 95 * MB + 7, 700 * MB, 4 * 1024 * MB):
            chunk, total = tu.plan_chunks(size)
            rangos = tu.chunk_ranges(size, chunk, total)
            self.assertEqual(rangos[0][0], 0)
            self.assertEqual(rangos[-1][1], size - 1)
            for (a, b), (c, _) in zip(rangos, rangos[1:]):
                self.assertEqual(c, b + 1, "hay un hueco o un solapamiento entre trozos")
            if total > 1:
                self.assertTrue(tu.MIN_CHUNK <= chunk <= tu.MAX_CHUNK)
                self.assertLessEqual(rangos[-1][1] - rangos[-1][0] + 1, 128 * MB)
            else:
                self.assertEqual(chunk, size, "un solo trozo tiene que ser el archivo entero")
                self.assertLessEqual(size, tu.MAX_CHUNK)
            self.assertLessEqual(total, 1000)


class Token(ConTokenTemporal):

    def test_vigente_se_usa_tal_cual(self):
        self.assertEqual(tu.token_state(_token(), "ck_test"), "valid")

    def test_vencido_con_refresh_se_renueva_sin_navegador(self):
        self.guardar_token(expires_at=time.time() - 10)
        api = TikTokFalso()
        with patch.object(tu, "authorize", side_effect=AssertionError("abrio el navegador")):
            token = tu.get_access_token(http=api)
        self.assertEqual(token["access_token"], "act.NUEVO")
        self.assertEqual(api.token_posts[0]["grant_type"], "refresh_token")
        guardado = tu.load_token()
        self.assertEqual(guardado["refresh_token"], "rft.NUEVO", "TikTok puede cambiar el refresh: vale el nuevo")
        self.assertEqual(guardado["client_key"], "ck_test")

    def test_sin_token_y_sin_interaccion_pide_auth(self):
        with self.assertRaises(tu.TikTokAuthError) as ctx:
            tu.get_access_token(interactive=False)
        self.assertIn("--auth", str(ctx.exception))

    def test_token_de_otra_app_pide_login(self):
        self.assertEqual(tu.token_state(_token(client_key="de_produccion"), "ck_test"), "login")

    def test_sin_video_upload_pide_login(self):
        self.assertEqual(tu.token_state(_token(scope="user.info.basic"), "ck_test"), "login")

    def test_todo_vencido_pide_login(self):
        viejo = _token(expires_at=time.time() - 10, refresh_expires_at=time.time() - 10)
        self.assertEqual(tu.token_state(viejo, "ck_test"), "login")

    def test_sin_claves_en_env_lo_dice(self):
        with patch.object(tu, "_env", return_value=""):
            with self.assertRaises(tu.TikTokAuthError) as ctx:
                tu.get_access_token(interactive=False)
        self.assertIn("TIKTOK_CLIENT_KEY", str(ctx.exception))


class Subida(ConTokenTemporal):

    def setUp(self):
        super().setUp()
        self.guardar_token()

    def test_el_init_manda_solo_el_archivo(self):
        api = TikTokFalso()
        ruta = self.video(size=25 * MB)
        res = tu.send_video_to_inbox(ruta, http=api, sleep=lambda s: None)
        self.assertEqual(res["publish_id"], "v_inbox_file~v2.123")
        self.assertEqual(api.init_body, {"source_info": {
            "source": "FILE_UPLOAD", "video_size": 25 * MB, "chunk_size": 10 * MB, "total_chunk_count": 2}},
            "la bandeja solo acepta source_info: un titulo aca da invalid_param")

    def test_los_trozos_van_en_orden_con_content_range(self):
        api = TikTokFalso()
        ruta = self.video(size=25 * MB)
        tu.send_video_to_inbox(ruta, http=api, sleep=lambda s: None)
        self.assertEqual(api.rangos, [f"bytes 0-{10 * MB - 1}/{25 * MB}",
                                      f"bytes {10 * MB}-{25 * MB - 1}/{25 * MB}"])

    def test_reporta_progreso_hasta_el_100(self):
        avances = []
        tu.send_video_to_inbox(self.video(size=12 * MB), http=TikTokFalso(), sleep=lambda s: None,
                               on_progress=lambda e, t: avances.append((e, t)))
        self.assertEqual(avances[0], (0, 12 * MB))
        self.assertEqual(avances[-1], (12 * MB, 12 * MB))

    def test_espera_a_que_llegue_a_la_bandeja(self):
        api = TikTokFalso(estados=("PROCESSING_UPLOAD", "PROCESSING_UPLOAD", "SEND_TO_USER_INBOX"))
        res = tu.send_video_to_inbox(self.video(), http=api, sleep=lambda s: None)
        self.assertEqual(res["tiktok_status"], "SEND_TO_USER_INBOX")
        self.assertEqual(api.llamadas.count("/post/publish/status/fetch/"), 3)

    def test_si_sigue_procesando_no_falla(self):
        # El borrador llega igual; solo tarda la notificacion.
        reloj = iter(range(0, 10_000, 100))
        api = TikTokFalso(estados=("PROCESSING_UPLOAD",))
        estado = tu.wait_for_inbox(_token(), "p1", http=api, sleep=lambda s: None, clock=lambda: next(reloj))
        self.assertEqual(estado["status"], "PROCESSING_UPLOAD")

    def test_fallo_de_procesado_se_explica(self):
        api = TikTokFalso(fail_reason="duration_check_failed")
        with self.assertRaises(tu.TikTokError) as ctx:
            tu.send_video_to_inbox(self.video(), http=api, sleep=lambda s: None)
        self.assertIn("10 min", str(ctx.exception))

    def test_cinco_borradores_pendientes_se_explica(self):
        api = TikTokFalso(init_error=(403, "spam_risk_too_many_pending_share"))
        with self.assertRaises(tu.TikTokError) as ctx:
            tu.send_video_to_inbox(self.video(), http=api, sleep=lambda s: None)
        self.assertIn("5 borradores", str(ctx.exception))
        self.assertEqual(api.rangos, [], "no tiene que subir nada si TikTok no abrio la subida")

    def test_token_invalido_pide_auth(self):
        api = TikTokFalso(init_error=(401, "access_token_invalid"))
        with self.assertRaises(tu.TikTokError) as ctx:
            tu.send_video_to_inbox(self.video(), http=api, sleep=lambda s: None)
        self.assertIn("--auth", str(ctx.exception))


class ListaDeVideos(unittest.TestCase):

    def test_recorre_todas_las_paginas(self):
        api = TikTokFalso()
        token = _token(scope="user.info.basic,video.upload,video.list")
        videos = tu.list_public_videos(token, http=api)
        self.assertEqual([v["id"] for v in videos], ["1", "2", "3"])
        self.assertEqual(api.list_bodies[1]["cursor"], 1700000000000, "no siguio con el cursor de TikTok")
        self.assertLessEqual(api.list_bodies[0]["max_count"], 20)

    def test_sin_video_list_pide_autorizar_de_nuevo(self):
        with self.assertRaises(tu.TikTokAuthError) as ctx:
            tu.list_public_videos(_token(), http=TikTokFalso())
        self.assertIn("Display API", str(ctx.exception))


class Limites(ConTokenTemporal):

    def test_short_normal_pasa(self):
        self.assertEqual(tu.check_video_limits(SHORT, 30 * MB), [])

    def test_documental_de_mas_de_10_min(self):
        problemas = tu.check_video_limits(dict(SHORT, duration=900.0), 300 * MB)
        self.assertTrue(any("10 min" in p for p in problemas))

    def test_fps_fuera_de_rango(self):
        self.assertTrue(tu.check_video_limits(dict(SHORT, fps=15.0), MB))

    def test_23_976_fps_entra(self):
        self.assertEqual(tu.check_video_limits(dict(SHORT, fps=24000 / 1001), MB), [])

    def test_sin_ffprobe_no_frena(self):
        self.assertEqual(tu.check_video_limits(None, 30 * MB), [])

    def test_un_documental_largo_no_llega_a_la_api(self):
        api = TikTokFalso()
        self.guardar_token()
        with patch.object(tu, "probe_video", return_value=dict(SHORT, duration=900.0)):
            with self.assertRaises(tu.TikTokError):
                tu.upload_from_metadata(self.tmp, video_path=self.video(), http=api, notify=False)
        self.assertEqual(api.llamadas, [], "gasto un borrador con un video que TikTok iba a rechazar")

    def test_formato_no_soportado(self):
        with self.assertRaises(tu.TikTokError):
            tu.send_video_to_inbox(self.video("clip.avi"), http=TikTokFalso())


class DesdeCarpeta(ConTokenTemporal):

    META = {"title": "Caral: The Oldest City in the Americas",
            "description": "Six pyramids, 5,000 years, zero weapons.\n\nWhat do you think really happened?\n\n#History",
            "topic": "Caral", "script_excerpt": "Caral was built 5,000 years ago in Peru.",
            "music_attribution": "Music: \"Epic Dawn\" by Some Artist (CC BY 3.0)",
            "upload_channel": "stunning-facts-of-history"}

    def setUp(self):
        super().setUp()
        self.guardar_token()
        self.video()
        with open(os.path.join(self.tmp, "tiktok_metadata.json"), "w", encoding="utf-8") as f:
            json.dump(self.META, f)
        self._env_os = patch.dict(os.environ, {"FACEBOOK_SEO_RESEARCH": "0"})
        self._env_os.start()

    def tearDown(self):
        self._env_os.stop()
        super().tearDown()

    def test_manda_el_borrador_y_el_texto_por_telegram(self):
        enviados = []
        with patch("publish.telegram_notify.send_message", side_effect=lambda texto, **kw: enviados.append(texto)):
            res = tu.upload_from_metadata(self.tmp, http=TikTokFalso())
        self.assertEqual(res["status"], "draft")
        self.assertTrue(res["telegram_sent"])
        self.assertEqual(len(enviados), 1)
        mensaje = enviados[0]
        self.assertIn("<code>Caral: The Oldest City in the Americas</code>", mensaje)
        self.assertIn("<pre>Six pyramids", mensaje)
        self.assertIn("Stunning Facts of History", mensaje)

    def test_la_descripcion_lleva_marca_de_la_cuenta_y_atribucion(self):
        with patch("publish.telegram_notify.send_message"):
            res = tu.upload_from_metadata(self.tmp, http=TikTokFalso())
        desc = res["description_sent"]
        self.assertIn("#StunningFactsofHistory", desc, "la marca sale de la cuenta real de TikTok")
        self.assertIn("Epic Dawn", desc, "CC BY exige la atribucion donde se publique")
        self.assertLess(desc.index("Epic Dawn"), desc.index("#History"), "la atribucion va antes de los hashtags")
        self.assertLessEqual(len(desc), tu.DESCRIPTION_LIMIT)

    def test_sin_telegram_el_borrador_igual_queda(self):
        from publish.telegram_notify import TelegramError
        avisos = []
        with patch("publish.telegram_notify.send_message", side_effect=TelegramError("Falta TELEGRAM_BOT_TOKEN")):
            res = tu.upload_from_metadata(self.tmp, http=TikTokFalso(), on_status=avisos.append)
        self.assertFalse(res["telegram_sent"])
        self.assertIn("TELEGRAM_BOT_TOKEN", res["telegram_error"])
        self.assertTrue(any("Caral" in a for a in avisos), "el texto tiene que quedar al menos en el log")

    def test_deja_el_resultado_en_disco(self):
        with patch("publish.telegram_notify.send_message"):
            tu.upload_from_metadata(self.tmp, http=TikTokFalso())
        with open(os.path.join(self.tmp, "tiktok_upload_result.json"), encoding="utf-8") as f:
            guardado = json.load(f)
        self.assertEqual(guardado["publish_id"], "v_inbox_file~v2.123")
        self.assertNotIn("act.VIEJO", json.dumps(guardado), "el token no se escribe en el resultado")

    def test_queda_registrado_en_el_proyecto(self):
        from publish.publish_record import summarize_result
        with patch("publish.telegram_notify.send_message"):
            res = tu.upload_from_metadata(self.tmp, http=TikTokFalso())
        entrada = summarize_result("tiktok", res)
        self.assertEqual(entrada["id"], "v_inbox_file~v2.123")
        self.assertEqual(entrada["status"], "draft")


class EnElStudio(unittest.TestCase):

    def setUp(self):
        with io.open("studio/auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace") as fh:
            self.fuente = fh.read()

    def test_casilla_y_subida(self):
        self.assertIn('self.chk_publish_tiktok = QCheckBox("TikTok")', self.fuente)
        self.assertIn('("tiktok_metadata.json", _tiktok_meta)', self.fuente)
        self.assertIn("from publish.tiktok_uploader import upload_from_metadata", self.fuente)
        self.assertIn("do_x or do_tiktok", self.fuente, "solo TikTok marcado dice 'sin plataforma'")

    def test_el_cierre_no_lo_llama_publicado(self):
        bloque = self.fuente[self.fuente.index("def _on_publish_done("):][:1800]
        self.assertIn("platform == 'tiktok'", bloque)
        self.assertIn("borrador", bloque)


if __name__ == "__main__":
    unittest.main(verbosity=2)
