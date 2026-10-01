# -*- coding: utf-8 -*-
"""Guardas de Instagram: caption/hashtags investigados y la misma miniatura como portada.

2026-09-22: el respaldo del caption de Instagram usaba '#stunningrevelations #history
#mystery #reels #facts' (marca del otro canal; la cuenta es @stunning.foh, "Stunning
Facts of History") y cortaba el guion a 320 caracteres a mitad de palabra. La portada
del reel la elegia Instagram: nunca se mandaba la miniatura elegida.

    .venv\\Scripts\\python.exe test_instagram_metadata.py
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from publish import facebook_metadata as fm
from publish import instagram_uploader as ig

BRAND = "Stunning Facts of History"
IDENTITY = {"access_token": "token-falso", "ig_user_id": "1784", "instagram_username": "stunning.foh",
            "instagram_name": BRAND, "page_id": "1291", "page_name": BRAND}
KAITEN_DESC = ("They volunteered knowing there was no way back. Inside a steel tube packed with explosives, a young "
               "pilot of the Imperial Japanese Navy steered the Kaiten torpedo toward American ships in the Pacific "
               "and waited for the impact that would kill him and every s\n\nWhat do you think really happened?\n\n"
               "#stunningrevelations #history #mystery #reels #facts")
KAITEN_RESEARCH = {"title": "Kaiten torpedo: 100 suicide subs in World War II", "keyword": "kaiten torpedo",
                   "subject": "kaiten", "tags": ["kaiten torpedo", "kaiten", "japanese navy", "human torpedo"],
                   "from": "youtube"}


def _image(path, fmt=None, color=(30, 140, 170)):
    im = Image.new("RGB", (720, 1280), color)
    d = ImageDraw.Draw(im)
    d.rectangle([60, 400, 660, 800], fill=(20, 20, 20))
    d.ellipse([200, 100, 520, 380], fill=(240, 240, 240))
    im.save(path, fmt)
    return path


class Caption(unittest.TestCase):

    def _prep(self, **meta):
        base = {"title": "Kaiten", "description": KAITEN_DESC, "research": KAITEN_RESEARCH}
        base.update(meta)
        return fm.prepare_instagram_metadata(base, brand=BRAND, log=lambda m: None)

    def test_la_primera_linea_es_el_titulo_investigado(self):
        r = self._prep()
        self.assertEqual(r["title"], KAITEN_RESEARCH["title"])
        caption = ig._compose_caption(r["title"], r["description"])
        self.assertTrue(caption.startswith("Kaiten torpedo: 100 suicide subs in World War II\n\n"))

    def test_suggest_respeta_el_titulo_del_usuario(self):
        r = self._prep(title="Japan's human torpedoes", title_mode="suggest")
        self.assertEqual(r["title"], "Japan's human torpedoes")
        self.assertIn("alternativa investigada", r["summary"])

    def test_hashtags_sin_marca_ajena_ni_cebo(self):
        r = self._prep()
        low = [t.lower() for t in r["hashtags"]]
        for bad in ("stunningrevelations", "mystery", "reels"):
            self.assertNotIn(bad, low)
        self.assertEqual(r["hashtags"][-1], "StunningFactsofHistory")
        self.assertIn("KaitenTorpedo", r["hashtags"])
        self.assertLessEqual(len(r["hashtags"]), 5)

    def test_no_antepone_el_titulo_al_cuerpo(self):
        # En Instagram el titulo YA es la primera linea del caption: no se duplica.
        r = self._prep()
        self.assertFalse(r["hook_added"])
        self.assertFalse(r["description"].startswith(KAITEN_RESEARCH["title"]))

    def test_repara_el_cuerpo_cortado(self):
        r = self._prep()
        self.assertTrue(r["lead_repaired"])
        self.assertNotIn("every s\n", r["description"])

    def test_el_caption_entero_entra_en_2200(self):
        r = self._prep(description="The Kaiten was a manned torpedo. " * 120)
        caption = ig._compose_caption(r["title"], r["description"])
        self.assertLessEqual(len(caption), 2200)
        self.assertTrue(caption.endswith("#StunningFactsofHistory"), "el tope no se come los hashtags")


class InvestigacionEncadenada(unittest.TestCase):

    def test_usa_la_de_youtube_si_hubo(self):
        yt = {"title_sent": "Kaiten torpedo", "tags_sent": ["kaiten"], "title_research": {"keyword": "kaiten torpedo"}}
        fb = {"research_used": {"title": "otro", "tags": ["x"]}}
        self.assertEqual(fm.research_for_next_platform(yt, fb)["title"], "Kaiten torpedo")

    def test_si_no_hubo_youtube_usa_la_de_facebook(self):
        fb = {"video_id": "1", "research_used": {"title": "Kaiten torpedo", "keyword": "kaiten torpedo",
                                                 "subject": "kaiten", "tags": ["kaiten"]}}
        self.assertEqual(fm.research_for_next_platform(None, fb)["keyword"], "kaiten torpedo")
        self.assertIsNone(fm.research_for_next_platform(None, None))

    def test_facebook_deja_su_investigacion_en_el_resultado(self):
        from publish import facebook_uploader as fu
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "short.mp4").write_bytes(b"v")
            (root / "facebook_metadata.json").write_text(json.dumps(
                {"title": "Kaiten", "description": "The kaiten torpedo.", "research": KAITEN_RESEARCH}),
                encoding="utf-8")
            with patch.object(fu, "_page_context", return_value=("t", "1", {"id": "1", "name": BRAND})), \
                 patch.object(fu, "upload_video", return_value={"video_id": "9"}):
                res = fu.upload_from_metadata(str(root))
        self.assertEqual(res["research_used"]["keyword"], "kaiten torpedo")


class Contenedor(unittest.TestCase):

    def test_cover_url_va_en_el_contenedor_por_url(self):
        with patch.object(ig, "_request_json", return_value={"id": "c1"}) as rq:
            ig._create_reel_container("1784", "tok", "https://v", "cap", cover_url="https://img/cover.jpg")
            self.assertEqual(rq.call_args.kwargs["params"]["cover_url"], "https://img/cover.jpg")
            ig._create_reel_container("1784", "tok", "https://v", "cap")
            self.assertNotIn("cover_url", rq.call_args.kwargs["params"])

    def test_cover_url_va_en_el_contenedor_resumable(self):
        with patch.object(ig, "_request_json", return_value={"id": "c2", "uri": "https://rupload/x"}) as rq, \
             patch.object(ig, "_upload_binary_resumable", return_value={"success": True}), \
             patch.object(ig, "_wait_for_container_ready", return_value={"status_code": "FINISHED"}), \
             tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "v.mp4"
            video.write_bytes(b"v")
            ig._publish_via_resumable("1784", "tok", str(video), "cap", True, cover_url="https://img/c.jpg")
        params = rq.call_args_list[0].kwargs["params"]
        self.assertEqual(params["upload_type"], "resumable")
        self.assertEqual(params["cover_url"], "https://img/c.jpg")


class Portada(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.video = self.root / "short.mp4"
        self.video.write_bytes(b"v")

    def tearDown(self):
        self.tmp.cleanup()

    def _once(self, calls, fail_with_cover=None):
        def fake(video_path, title, description, share_to_feed, on_progress, api_version, on_status,
                 cover_url, identity):
            calls.append(cover_url)
            if cover_url and fail_with_cover:
                raise RuntimeError(fail_with_cover)
            return {"media_id": "m1", "url": "https://instagram.com/reel/x", "_access_token": "tok"}
        return fake

    def test_publica_con_portada_la_verifica_y_borra_la_copia(self):
        calls, msgs = [], []
        cover = {"url": "https://res.cloudinary.com/c.jpg", "public_id": "vo/cover1", "local": "x.jpg"}
        with patch.object(ig, "_prepare_cover", return_value=cover), \
             patch.object(ig, "_upload_video_once", side_effect=self._once(calls)), \
             patch.object(ig, "verify_cover", return_value={"checked": True, "match": True}) as ver, \
             patch.object(ig, "_cleanup_cover") as clean:
            res = ig.upload_video(str(self.video), "t", "d", cover_path="thumbnail.webp", on_status=msgs.append)
        self.assertEqual(calls, ["https://res.cloudinary.com/c.jpg"])
        self.assertTrue(res["thumbnail_set"])
        self.assertTrue(res["thumbnail_verify"]["match"])
        self.assertEqual(ver.call_args.args[:3], ("m1", "tok", "x.jpg"))
        clean.assert_called_once_with("vo/cover1")
        self.assertNotIn("_access_token", res, "el token no queda en el resultado (se guarda en disco)")
        self.assertTrue(any("verificada" in m for m in msgs))

    def test_si_meta_rechaza_la_portada_publica_sin_ella(self):
        calls = []
        cover = {"url": "https://res.cloudinary.com/c.jpg", "public_id": "vo/cover1", "local": "x.jpg"}
        with patch.object(ig, "_prepare_cover", return_value=cover), \
             patch.object(ig, "_upload_video_once",
                          side_effect=self._once(calls, "Instagram container failed: invalid cover image")), \
             patch.object(ig, "_cleanup_cover") as clean:
            res = ig.upload_video(str(self.video), "t", "d", cover_path="thumbnail.jpg")
        self.assertEqual(calls, ["https://res.cloudinary.com/c.jpg", None])
        self.assertFalse(res["thumbnail_set"])
        self.assertIn("portada", res["thumbnail_error"])
        clean.assert_called_once_with("vo/cover1")

    def test_un_error_del_video_no_se_confunde_con_la_portada(self):
        # La caida de ingesta de Meta (09-2026) no es culpa de la portada: se propaga igual que antes.
        calls = []
        cover = {"url": "https://res.cloudinary.com/c.jpg", "public_id": "vo/cover1", "local": "x.jpg"}
        with patch.object(ig, "_prepare_cover", return_value=cover), \
             patch.object(ig, "_upload_video_once", side_effect=self._once(
                 calls, "Video Transcoding Error: both HD and SD progressive failed to transcode")), \
             patch.object(ig, "_cleanup_cover") as clean:
            with self.assertRaises(RuntimeError):
                ig.upload_video(str(self.video), "t", "d", cover_path="thumbnail.jpg")
        self.assertEqual(calls, ["https://res.cloudinary.com/c.jpg"])
        clean.assert_called_once_with("vo/cover1")

    def test_si_la_portada_no_se_puede_preparar_sale_sin_ella(self):
        calls = []
        with patch.object(ig, "_prepare_cover", side_effect=RuntimeError("Cloudinary caido")), \
             patch.object(ig, "_upload_video_once", side_effect=self._once(calls)):
            res = ig.upload_video(str(self.video), "t", "d", cover_path="thumbnail.jpg")
        self.assertEqual(calls, [None])
        self.assertIn("Cloudinary caido", res["thumbnail_error"])

    def test_sin_cover_path_se_comporta_como_antes(self):
        calls = []
        with patch.object(ig, "_upload_video_once", side_effect=self._once(calls)):
            res = ig.upload_video(str(self.video), "t", "d")
        self.assertEqual(calls, [None])
        self.assertNotIn("thumbnail_set", res)

    def test_la_portada_se_convierte_a_jpeg_antes_de_subirla(self):
        png = _image(self.root / "thumbnail.png")
        subidas = []

        def fake_upload(path, folder=None, tags=None):
            subidas.append(path)
            return {"secure_url": "https://res.cloudinary.com/c.jpg", "public_id": "vo/c"}
        with patch("publish.cloudinary_uploader.upload_image", side_effect=fake_upload):
            cover = ig._prepare_cover(str(png))
        self.assertTrue(subidas[0].endswith(".jpg"))
        with Image.open(subidas[0]) as im:
            self.assertEqual(im.format, "JPEG")
        self.assertEqual(cover["url"], "https://res.cloudinary.com/c.jpg")

    def test_verifica_contra_lo_que_muestra_instagram(self):
        local = _image(self.root / "local.jpg")
        with patch.object(ig, "_request_json", return_value={"thumbnail_url": "https://cdn/x.jpg"}):
            v = ig.verify_cover("m1", "tok", str(local), fetch=lambda u: Path(local).read_bytes())
        self.assertTrue(v["match"])


class DesdeLaCarpeta(unittest.TestCase):

    def test_optimiza_y_manda_la_miniatura_de_la_carpeta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "short.mp4").write_bytes(b"v")
            _image(root / "thumbnail.webp", fmt="WEBP")
            (root / "instagram_metadata.json").write_text(json.dumps(
                {"title": "Kaiten", "description": KAITEN_DESC, "research": KAITEN_RESEARCH}), encoding="utf-8")
            fake = {"media_id": "m1", "url": "https://instagram.com/reel/x", "thumbnail_set": True,
                    "thumbnail_sent": str(root / "thumbnail.webp")}
            with patch.object(ig, "_resolve_instagram_identity", return_value=IDENTITY), \
                 patch.object(ig, "upload_video", return_value=dict(fake)) as up:
                res = ig.upload_from_metadata(str(root))
            kw = up.call_args.kwargs
            self.assertEqual(kw["title"], KAITEN_RESEARCH["title"])
            self.assertTrue(kw["description"].endswith("#StunningFactsofHistory"))
            self.assertNotIn("#mystery", kw["description"].lower())
            self.assertEqual(Path(kw["cover_path"]).name, "thumbnail.webp")
            self.assertIs(kw["identity"], IDENTITY)
            self.assertEqual(res["hashtags_sent"][-1], "StunningFactsofHistory")
            saved = json.loads((root / "instagram_upload_result.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["thumbnail_set"])
            self.assertTrue(saved["caption"].startswith(KAITEN_RESEARCH["title"]))

    def test_instagram_seo_0_lo_apaga(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "short.mp4").write_bytes(b"v")
            (root / "instagram_metadata.json").write_text(json.dumps({"title": "T", "description": "D #mystery"}),
                                                          encoding="utf-8")
            with patch.dict(os.environ, {"INSTAGRAM_SEO": "0"}), \
                 patch.object(ig, "_resolve_instagram_identity", return_value=IDENTITY), \
                 patch.object(ig, "upload_video", return_value={"media_id": "1"}) as up:
                ig.upload_from_metadata(str(root))
            self.assertEqual(up.call_args.kwargs["description"], "D #mystery")


class Cableado(unittest.TestCase):

    def _src(self, name):
        with open(name, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def test_el_studio_encadena_la_investigacion_hacia_instagram(self):
        s = self._src("auto_video_integration_pyqt6.py")
        self.assertIn("research_for_next_platform(results.get('youtube'), results.get('facebook'))", s)
        self.assertIn("_instagram_meta['research'] = _ig_research", s)
        self.assertIn('ig_title_mode = "suggest"', s)

    def test_los_respaldos_de_instagram_no_usan_marca_ajena_ni_cebo(self):
        for name in ("auto_video_integration_pyqt6.py", "platform_metadata_tab.py", "pipeline/daily_short_pipeline.py"):
            s = self._src(name)
            self.assertNotIn("#stunningrevelations #history #mystery #reels #facts", s, name)
            self.assertNotIn("#history #reels #facts", s, name)
        self.assertNotIn("preview[:320]", self._src("auto_video_integration_pyqt6.py"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
