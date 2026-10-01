# -*- coding: utf-8 -*-
"""Guardas del aviso por Telegram (telegram_notify).

Es la unica via por la que el titulo y la descripcion del borrador de TikTok llegan
al celular: si el HTML se rompe, Telegram rechaza el mensaje entero; si el token
aparece en un error, queda en el log del Studio.

    .venv\\Scripts\\python.exe test_telegram_notify.py

No toca la red.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import telegram_notify as tn

TOKEN = "123456:ABCdefSECRETO"


class _R:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._p = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p


class TelegramFalso:
    def __init__(self, status=200, payload=None, error=None):
        self.enviados = []
        self.status = status
        self.payload = payload or {"ok": True, "result": {"message_id": 7}}
        self.error = error

    def post(self, url, json=None, timeout=None):
        self.enviados.append((url, json))
        if self.error:
            raise self.error
        return _R(self.status, self.payload)


class Mensaje(unittest.TestCase):

    def test_titulo_y_descripcion_copiables(self):
        m = tn.build_tiktok_draft_message("72 Seconds: The Wow! Signal",
                                          "In 1977 a telescope heard it.\n\n#WowSignal #History",
                                          account="Stunning Facts of History")
        self.assertIn("<code>72 Seconds: The Wow! Signal</code>", m)
        self.assertIn("<pre>In 1977 a telescope heard it.\n\n#WowSignal #History</pre>", m)
        self.assertIn("Stunning Facts of History", m)
        self.assertIn("Contenido generado por IA", m)

    def test_escapa_el_html(self):
        # Un '&' o un '<' sin escapar hace que Telegram rechace el mensaje entero.
        m = tn.build_tiktok_draft_message("Rock & Roll <1950>", "A > B & C", account="A&B")
        self.assertIn("<code>Rock &amp; Roll &lt;1950&gt;</code>", m)
        self.assertIn("<pre>A &gt; B &amp; C</pre>", m)
        self.assertIn("A&amp;B", m)

    def test_no_pasa_el_limite_de_telegram(self):
        m = tn.build_tiktok_draft_message("Titulo", "palabra " * 1500)
        self.assertLessEqual(tn._visible_len(m), tn.MESSAGE_LIMIT)
        self.assertTrue(m.rstrip().endswith("…</pre>"))

    def test_avisa_si_tiktok_sigue_procesando(self):
        self.assertIn("procesando", tn.build_tiktok_draft_message("T", "D", processing=True))
        self.assertNotIn("procesando", tn.build_tiktok_draft_message("T", "D"))

    def test_sin_descripcion_no_deja_bloque_vacio(self):
        self.assertNotIn("<pre>", tn.build_tiktok_draft_message("T", ""))


class Envio(unittest.TestCase):

    def test_manda_html_sin_vista_previa(self):
        fake = TelegramFalso()
        tn.send_message("<b>hola</b>", token=TOKEN, chat_id="42", http=fake)
        url, cuerpo = fake.enviados[0]
        self.assertTrue(url.endswith("/sendMessage"))
        self.assertEqual(cuerpo["chat_id"], "42")
        self.assertEqual(cuerpo["parse_mode"], "HTML")
        self.assertTrue(cuerpo["disable_web_page_preview"])

    def test_token_rechazado(self):
        fake = TelegramFalso(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
        with self.assertRaises(tn.TelegramError) as ctx:
            tn.send_message("x", token=TOKEN, chat_id="42", http=fake)
        self.assertIn("TELEGRAM_BOT_TOKEN", str(ctx.exception))

    def test_chat_inexistente_pide_start(self):
        fake = TelegramFalso(400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
        with self.assertRaises(tn.TelegramError) as ctx:
            tn.send_message("x", token=TOKEN, chat_id="42", http=fake)
        self.assertIn("/start", str(ctx.exception))

    def test_bot_bloqueado(self):
        fake = TelegramFalso(403, {"ok": False, "error_code": 403,
                                   "description": "Forbidden: bot was blocked by the user"})
        with self.assertRaises(tn.TelegramError) as ctx:
            tn.send_message("x", token=TOKEN, chat_id="42", http=fake)
        self.assertIn("Iniciar", str(ctx.exception))

    def test_el_token_no_aparece_en_los_errores(self):
        # La URL de la API lleva el token y requests la repite en sus excepciones.
        fake = TelegramFalso(error=requests.ConnectionError(
            f"Max retries exceeded with url: /bot{TOKEN}/sendMessage"))
        with self.assertRaises(tn.TelegramError) as ctx:
            tn.send_message("x", token=TOKEN, chat_id="42", http=fake)
        self.assertNotIn("SECRETO", str(ctx.exception))

    def test_sin_configuracion_lo_dice(self):
        with patch.object(tn, "_env", return_value=""):
            with self.assertRaises(tn.TelegramError) as ctx:
                tn.send_message("x", http=TelegramFalso())
        self.assertIn("TELEGRAM_BOT_TOKEN", str(ctx.exception))


class Configuracion(unittest.TestCase):

    def test_encuentra_el_chat_privado_mas_reciente(self):
        payload = {"ok": True, "result": [
            {"update_id": 1, "message": {"chat": {"id": 111, "type": "private", "first_name": "Viejo"}}},
            {"update_id": 2, "message": {"chat": {"id": -5, "type": "group", "title": "Grupo"}}},
            {"update_id": 3, "message": {"chat": {"id": 222, "type": "private", "first_name": "Esteban"}}},
        ]}
        chats = tn.chats_from_updates(payload)
        self.assertEqual(chats[0]["id"], 222)
        self.assertEqual(chats[0]["name"], "Esteban")
        self.assertEqual(len(chats), 3)

    def test_sin_mensajes_no_hay_chats(self):
        self.assertEqual(tn.chats_from_updates({"ok": True, "result": []}), [])

    def test_upsert_env_agrega_reemplaza_y_no_toca_lo_demas(self):
        tmp = tempfile.mkdtemp(prefix="envtg_")
        try:
            env = Path(tmp) / ".env"
            env.write_text("GROQ_API_KEY=abc\n# comentario\n", encoding="utf-8")
            self.assertTrue(tn.upsert_env_var(env, "TELEGRAM_CHAT_ID", "222"))
            self.assertFalse(tn.upsert_env_var(env, "TELEGRAM_CHAT_ID", "222"), "reescribio sin cambios")
            self.assertTrue(tn.upsert_env_var(env, "TELEGRAM_CHAT_ID", "333"))
            texto = env.read_text(encoding="utf-8")
            self.assertEqual(texto.count("TELEGRAM_CHAT_ID="), 1)
            self.assertIn("TELEGRAM_CHAT_ID=333", texto)
            self.assertIn("GROQ_API_KEY=abc", texto)
            self.assertIn("# comentario", texto)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
