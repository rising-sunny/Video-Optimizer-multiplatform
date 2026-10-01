# -*- coding: utf-8 -*-
"""Guardas: Facebook e Instagram publican en las cuentas del canal elegido en el Studio.

2026-09-27: en una PC nueva, el .env.txt copiado de Drive era viejo y los reels de
Stunning Facts of History salian en Stunning Revelations. Ahora las claves globales
son las del canal por defecto y cada otro canal puede tener las suyas con sufijo
(FACEBOOK_PAGE_ID_STUNNING_REVELATIONS, INSTAGRAM_BUSINESS_ACCOUNT_ID_..., etc.).
Publicar en la cuenta del otro canal es peor que no publicar.

    .venv\\Scripts\\python.exe test_channel_accounts.py

No toca la red.
"""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import facebook_uploader as fb
import instagram_uploader as ig

FOH, REV = "111", "222"
ENV = {
    "FACEBOOK_USER_ACCESS_TOKEN": "user",
    "FACEBOOK_PAGE_ID": FOH,
    "FACEBOOK_PAGE_ACCESS_TOKEN": "tok-foh",
    "INSTAGRAM_PAGE_ID": FOH,
    "INSTAGRAM_BUSINESS_ACCOUNT_ID": "ig-foh",
    "FACEBOOK_PAGE_ID_STUNNING_REVELATIONS": REV,
    "FACEBOOK_PAGE_ACCESS_TOKEN_STUNNING_REVELATIONS": "tok-rev",
    "INSTAGRAM_PAGE_ID_STUNNING_REVELATIONS": REV,
    "INSTAGRAM_BUSINESS_ACCOUNT_ID_STUNNING_REVELATIONS": "ig-rev",
}


def fake_env(env):
    return lambda name, default=None: env.get(name, default)


def probe_fb(method, url, **kw):
    """Graph falso: GET /me con un page token dice de que pagina es."""
    token = (kw.get("params") or {}).get("access_token")
    return {"id": {"tok-foh": FOH, "tok-rev": REV}.get(token, "?")}


class Facebook(unittest.TestCase):

    def test_canal_con_claves_propias_usa_su_pagina(self):
        with patch.object(fb, "_env", fake_env(ENV)), patch.object(fb, "_request_json", side_effect=probe_fb):
            self.assertEqual(fb._resolve_page_access_token(channel="stunning-revelations"), ("tok-rev", REV))

    def test_canal_por_defecto_y_sin_canal_usan_las_globales(self):
        with patch.object(fb, "_env", fake_env(ENV)), patch.object(fb, "_request_json", side_effect=probe_fb):
            self.assertEqual(fb._resolve_page_access_token(channel="stunning-facts-of-history"), ("tok-foh", FOH))
            self.assertEqual(fb._resolve_page_access_token(), ("tok-foh", FOH))

    def test_pagina_propia_sin_token_propio_deriva_uno_y_no_usa_el_de_la_otra_pagina(self):
        env = {k: v for k, v in ENV.items() if k != "FACEBOOK_PAGE_ACCESS_TOKEN_STUNNING_REVELATIONS"}

        def graph(method, url, **kw):
            if url.endswith("/me"):
                return probe_fb(method, url, **kw)          # el token global es de FOH
            return {"id": REV, "name": "Stunning Revelations", "access_token": "tok-derivado"}

        with patch.object(fb, "_env", fake_env(env)), patch.object(fb, "_request_json", side_effect=graph):
            token, page = fb._resolve_page_access_token(channel="stunning-revelations")
        self.assertEqual((token, page), ("tok-derivado", REV))

    def test_upload_from_metadata_pasa_el_canal(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "short.mp4").write_bytes(b"\0" * 64)
            Path(tmp, "facebook_metadata.json").write_text(json.dumps(
                {"title": "T", "description": "D", "upload_channel": "stunning-revelations"}), encoding="utf-8")
            ctx = ("tok-rev", REV, {"id": REV, "name": "Stunning Revelations"})
            with patch.object(fb, "_page_context", return_value=ctx) as page_ctx, \
                    patch.object(fb, "upload_video", return_value={"video_id": "v"}) as up, \
                    patch.object(fb, "save_upload_result"):
                fb.upload_from_metadata(tmp, optimize=False, thumbnail=False, on_status=lambda m: None)
        page_ctx.assert_called_once_with(channel="stunning-revelations")
        self.assertEqual(up.call_args.kwargs["page_context"], ctx)


class Instagram(unittest.TestCase):

    def _identity(self, env, channel):
        pedidas = []

        def graph(method, url, **kw):
            pedidas.append(url.rsplit("/", 1)[-1])
            page = url.rsplit("/", 1)[-1]
            return {"id": page, "name": page, "instagram_business_account": {"id": f"ig-{page}", "username": page}}

        with patch.object(ig, "_env", fake_env(env)), patch.object(ig, "_request_json", side_effect=graph):
            identidad = ig._resolve_instagram_identity(channel=channel)
        return identidad, pedidas

    def test_canal_con_claves_propias_consulta_su_pagina(self):
        identidad, pedidas = self._identity(ENV, "stunning-revelations")
        self.assertEqual(pedidas, [REV])
        self.assertEqual(identidad["ig_user_id"], f"ig-{REV}")

    def test_sin_canal_usa_la_pagina_global(self):
        _, pedidas = self._identity(ENV, None)
        self.assertEqual(pedidas, [FOH])

    def test_facebook_page_id_del_canal_gana_al_instagram_page_id_global(self):
        # Solo FACEBOOK_PAGE_ID_<CANAL>: antes caia en INSTAGRAM_PAGE_ID global (la otra cuenta).
        env = {k: v for k, v in ENV.items() if k != "INSTAGRAM_PAGE_ID_STUNNING_REVELATIONS"}
        _, pedidas = self._identity(env, "stunning-revelations")
        self.assertEqual(pedidas, [REV])

    def test_pagina_del_canal_sin_instagram_no_cae_en_la_cuenta_global(self):
        env = {k: v for k, v in ENV.items() if k != "INSTAGRAM_BUSINESS_ACCOUNT_ID_STUNNING_REVELATIONS"}
        with patch.object(ig, "_env", fake_env(env)), \
                patch.object(ig, "_request_json", return_value={"id": REV, "name": "Stunning Revelations"}):
            with self.assertRaises(RuntimeError):
                ig._resolve_instagram_identity(channel="stunning-revelations")

    def test_upload_from_metadata_pasa_el_canal(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "short.mp4").write_bytes(b"\0" * 64)
            Path(tmp, "instagram_metadata.json").write_text(json.dumps(
                {"title": "T", "description": "D", "upload_channel": "stunning-revelations"}), encoding="utf-8")
            with patch.object(ig, "_resolve_instagram_identity",
                              return_value={"ig_user_id": "ig-rev", "instagram_name": "Stunning Revelations"}) as ident, \
                    patch.object(ig, "upload_video", return_value={"media_id": "m"}), \
                    patch.object(ig, "save_upload_result"):
                ig.upload_from_metadata(tmp, optimize=False, thumbnail=False, on_status=lambda m: None)
        ident.assert_called_once_with(channel="stunning-revelations")


class EnElStudio(unittest.TestCase):

    def test_el_studio_manda_el_canal_a_facebook_e_instagram(self):
        with io.open("auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace") as fh:
            fuente = fh.read()
        self.assertIn("_facebook_meta['upload_channel'] = upload_channel", fuente)
        self.assertIn("_instagram_meta['upload_channel'] = upload_channel", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
