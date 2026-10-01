# -*- coding: utf-8 -*-
"""Guardas de Facebook: titulo/hashtags investigados y la misma miniatura que YouTube.

2026-09-22: el reel de Hannibal salio con '#History #Mystery #StunningRevelations'
(marca del otro canal; la pagina es Stunning Facts of History) y la descripcion
cortada en '...every s'. Facebook nunca recibia la miniatura elegida.

    .venv\\Scripts\\python.exe test_facebook_metadata.py
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import facebook_metadata as fm
import facebook_uploader as fu

BRAND = "Stunning Facts of History"
FAKE_PAGE = ("token-falso", "987654321", {"id": "987654321", "name": BRAND})

HANNIBAL_DESC = ("How did Hannibal sustain 50,000 troops and war elephants across the frozen Alps without "
                 "modern supply lines? He relied on 30,000 oxen, each carrying up to 250 kilograms of grain, "
                 "meat, and water. At the Little St. Bernard pass, they distributed rations every s\n\n"
                 "What do you think really happened?\n\n#History #Mystery #StunningRevelations")
HANNIBAL_RESEARCH = {"title": "Hannibal crossing the Alps: how 30,000 oxen fed his army",
                     "keyword": "hannibal crossing the alps", "subject": "hannibal",
                     "tags": ["hannibal crossing the alps", "hannibal barca", "second punic war", "hannibal",
                              "history", "stunning facts of history"], "from": "youtube"}


def _image(path, color=(200, 90, 30), size=(720, 1280), fmt=None):
    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    d.rectangle([60, 400, 660, 800], fill=(20, 20, 20))
    d.ellipse([200, 100, 520, 380], fill=(240, 240, 240))
    im.save(path, fmt)
    return path


class Hashtags(unittest.TestCase):

    def test_hannibal_sin_misterio_ni_marca_ajena(self):
        r = fm.optimize_facebook_metadata({"title": "How Hannibal Fed an Army Across the Alps",
                                           "description": HANNIBAL_DESC},
                                          research_title=HANNIBAL_RESEARCH["title"],
                                          keyword=HANNIBAL_RESEARCH["keyword"], subject="hannibal",
                                          research_tags=HANNIBAL_RESEARCH["tags"], brand=BRAND)
        low = [t.lower() for t in r["hashtags"]]
        self.assertNotIn("mystery", low)
        self.assertNotIn("stunningrevelations", low)
        self.assertEqual(r["hashtags"][-1], "StunningFactsofHistory", "la marca de la pagina, al final")
        self.assertIn("HannibalCrossingTheAlps", r["hashtags"])
        self.assertIn("History", r["hashtags"])
        self.assertLessEqual(len(r["hashtags"]), fm.MAX_HASHTAGS)
        self.assertEqual(low.count("history"), 1)
        self.assertIn("Mystery", r["hashtags_dropped"])
        self.assertTrue(r["description"].endswith(" ".join("#" + t for t in r["hashtags"])))
        self.assertEqual(r["description"].count("#Mystery"), 0)

    def test_frase_a_hashtag(self):
        self.assertEqual(fm.hashtag_from_phrase("kaiten torpedo"), "KaitenTorpedo")
        self.assertEqual(fm.hashtag_from_phrase("plaster casts of pompeii"), "PlasterCastsOfPompeii")
        self.assertEqual(fm.hashtag_from_phrase("world war ii"), "WorldWarII")
        self.assertEqual(fm.hashtag_from_phrase("USS Mississinewa"), "USSMississinewa")
        self.assertIsNone(fm.hashtag_from_phrase("imperial japanese navy suicide weapons"))
        self.assertIsNone(fm.hashtag_from_phrase("1863"))
        self.assertIsNone(fm.hashtag_from_phrase("extraordinarily long phrase indeed"))

    def test_palabra_de_inicio_de_frase_no_es_hashtag(self):
        # primera prueba en vivo: '#Recovered' salio de "Recovered wreckage in the New Mexico desert."
        tags = fm.build_hashtags(keyword="new mexico", research_tags=["recovered", "roswell"],
                                 brand=BRAND, subject="roswell",
                                 source_text="Recovered wreckage in the New Mexico desert near Roswell.")
        self.assertNotIn("Recovered", tags)
        self.assertIn("Roswell", tags)
        self.assertIn("NewMexico", tags)

    def test_nombre_propio_del_guion_si_entra(self):
        tags = fm.build_hashtags(keyword="plaster casts of pompeii", research_tags=["fiorelli"], brand=BRAND,
                                 subject="pompeii", source_text="In 1863 Giuseppe Fiorelli poured plaster.")
        self.assertIn("Fiorelli", tags)

    def test_cebo_generico_fuera_y_tope(self):
        tags = fm.build_hashtags(keyword="kaiten torpedo", research_tags=["kaiten", "human torpedo", "kamikaze subs",
                                                                         "japanese navy"],
                                 draft_hashtags=["fyp", "viral", "Shorts", "WW2"], brand=BRAND, subject="kaiten")
        self.assertEqual(len(tags), 5)
        self.assertEqual(tags[-1], "StunningFactsofHistory")
        for bad in ("fyp", "viral", "Shorts"):
            self.assertNotIn(bad, tags)
        self.assertEqual(tags[:3], ["Kaiten", "KaitenTorpedo", "HumanTorpedo"],
                         "sujeto amplio, palabra clave y variedad; investigacion primero, hasta 3")

    def test_un_tag_de_la_competencia_que_el_guion_no_respalda_no_entra(self):
        # prueba en vivo: '#RomanArmy' para Hannibal (cartagines); el guion no habla del ejercito romano.
        r = fm.optimize_facebook_metadata({"title": "How Hannibal Fed an Army Across the Alps",
                                           "description": HANNIBAL_DESC},
                                          keyword="hannibal army", subject="hannibal", brand=BRAND,
                                          research_tags=["roman army", "war elephants"])
        self.assertNotIn("RomanArmy", r["hashtags"])
        self.assertIn("WarElephants", r["hashtags"], "'war elephants' si esta en el guion")

    def test_no_repite_el_sujeto_tres_veces(self):
        # primera prueba en vivo: #HannibalArmy #Hannibal #HannibalBarca
        tags = fm.build_hashtags(keyword="hannibal army", subject="hannibal", brand=BRAND,
                                 research_tags=["hannibal", "hannibal barca", "second punic war"])
        self.assertEqual(tags[:3], ["Hannibal", "HannibalArmy", "SecondPunicWar"])


class Descripcion(unittest.TestCase):

    def test_no_corta_a_mitad_de_palabra(self):
        texto = HANNIBAL_DESC.split("\n")[0][:-8] + " every soldier received rations. And more text follows here."
        out = fm.trim_at_boundary(texto, 260)
        self.assertLessEqual(len(out), 261)
        self.assertTrue(out.endswith((".", "?", "!", "…")), out[-20:])
        self.assertFalse(out.endswith("every s"))

    def test_repara_el_primer_parrafo_cortado_sin_caer_en_st_bernard(self):
        body, _ = fm.split_trailing_hashtags(HANNIBAL_DESC)
        fixed, ok = fm.repair_truncated_lead(body)
        self.assertTrue(ok)
        lead = fixed.split("\n\n")[0]
        self.assertTrue(lead.endswith("grain, meat, and water."), lead[-40:])
        self.assertIn("What do you think really happened?", fixed)

    def test_no_toca_un_primer_parrafo_completo(self):
        body = "The famous bodies of Pompeii are not bodies. " * 6 + "\n\nWhat do you think?"
        self.assertEqual(fm.repair_truncated_lead(body), (body, False))

    def test_antepone_el_titulo_si_el_tema_no_se_ve(self):
        r = fm.optimize_facebook_metadata({"title": "Kaiten torpedo: Japan's human torpedoes",
                                           "description": "They volunteered knowing there was no way back. "
                                                          "Inside a steel tube, a young pilot waited.\n\n#History"},
                                          keyword="kaiten torpedo", subject="kaiten", brand=BRAND)
        self.assertTrue(r["hook_added"])
        self.assertTrue(r["description"].startswith("Kaiten torpedo: Japan's human torpedoes\n\n"))

    def test_no_antepone_si_el_tema_ya_esta_arriba(self):
        r = fm.optimize_facebook_metadata({"title": "x", "description": "The famous bodies of Pompeii are not bodies."},
                                          keyword="plaster casts of pompeii", subject="pompeii", brand=BRAND)
        self.assertFalse(r["hook_added"])
        self.assertTrue(r["description"].startswith("The famous bodies of Pompeii"))

    def test_tope_de_2200_conserva_los_hashtags(self):
        r = fm.optimize_facebook_metadata({"title": "Pompeii", "description": ("Pompeii was buried. " * 200)},
                                          keyword="pompeii", subject="pompeii", brand=BRAND)
        self.assertLessEqual(len(r["description"]), fm.MAX_DESCRIPTION_CHARS)
        self.assertTrue(r["description"].endswith("#StunningFactsofHistory"))

    def test_hashtags_dentro_de_una_frase_se_quedan(self):
        body, tags = fm.split_trailing_hashtags("Why #Rome fell.\n\n#History #Rome\n")
        self.assertEqual(body, "Why #Rome fell.")
        self.assertEqual(tags, ["History", "Rome"])


class Titulo(unittest.TestCase):

    def test_optimize_usa_el_titulo_investigado(self):
        r = fm.optimize_facebook_metadata({"title": "Roswell 1947", "description": "x"},
                                          research_title="Roswell 1947: what the Army recovered", brand=BRAND)
        self.assertEqual(r["title"], "Roswell 1947: what the Army recovered")
        self.assertTrue(r["title_changed"])

    def test_suggest_respeta_el_titulo_del_usuario(self):
        r = fm.optimize_facebook_metadata({"title": "How Hannibal Fed an Army Across the Alps", "description": "x"},
                                          research_title=HANNIBAL_RESEARCH["title"], brand=BRAND, title_mode="suggest")
        self.assertEqual(r["title"], "How Hannibal Fed an Army Across the Alps")
        self.assertFalse(r["title_changed"])
        self.assertIn("alternativa investigada", r["summary"])

    def test_sin_titulo_usa_el_investigado_aunque_sea_suggest(self):
        r = fm.optimize_facebook_metadata({"title": "", "description": "x"}, research_title="Kaiten torpedo",
                                          title_mode="suggest", brand=BRAND)
        self.assertEqual(r["title"], "Kaiten torpedo")


class Investigacion(unittest.TestCase):

    def test_reusa_lo_que_investigo_youtube(self):
        yt = {"video_id": "abc", "title_sent": "Kaiten torpedo: 100 suicide subs in World War II",
              "tags_sent": ["kaiten torpedo", "kaiten"], "title_research": {"keyword": "kaiten torpedo"},
              "research_subject": "kaiten"}
        r = fm.research_from_youtube(yt)
        self.assertEqual(r["title"], yt["title_sent"])
        self.assertEqual(r["keyword"], "kaiten torpedo")
        self.assertEqual(r["subject"], "kaiten")
        self.assertIsNone(fm.research_from_youtube(None))
        self.assertIsNone(fm.research_from_youtube({"video_id": "x"}))

    def test_con_investigacion_de_youtube_no_vuelve_a_la_red(self):
        meta = {"title": "Hannibal", "description": HANNIBAL_DESC, "research": HANNIBAL_RESEARCH}
        with patch("youtube_tags.gather_research", side_effect=AssertionError("no deberia investigar")):
            r = fm.prepare_facebook_metadata(meta, brand=BRAND, log=lambda m: None)
        self.assertEqual(r["title"], HANNIBAL_RESEARCH["title"])
        self.assertIn("YouTube", r["source"])

    def test_si_la_investigacion_falla_igual_limpia_los_hashtags(self):
        meta = {"title": "Hannibal", "description": HANNIBAL_DESC, "topic": "Hannibal"}
        with patch.object(fm, "research_inputs", side_effect=RuntimeError("sin red")):
            r = fm.prepare_facebook_metadata(meta, brand=BRAND, log=lambda m: None)
        self.assertNotIn("Mystery", r["hashtags"])
        self.assertEqual(r["hashtags"][-1], "StunningFactsofHistory")
        self.assertIn("no disponible", r["source"])


class _FakeGraph:
    """_request_json falso: registra llamadas y contesta como la Graph API."""

    def __init__(self, fail_first=0, error="Facebook API error 1: An unknown error occurred", thumb_uri="u"):
        self.calls = []
        self.fail_first = fail_first
        self.error = error
        self.thumb_uri = thumb_uri

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if method == "POST" and url.endswith("/thumbnails"):
            if self.fail_first:
                self.fail_first -= 1
                raise RuntimeError(self.error)
            self.sent_file = kw["files"]["source"]
            return {"success": True}
        if method == "GET" and url.endswith("/thumbnails"):
            return {"data": [{"uri": "otra", "is_preferred": False}, {"uri": self.thumb_uri, "is_preferred": True}]}
        return {}


class TituloMalRedactadoNoPisa(unittest.TestCase):
    """Trafalgar (24-09): Facebook e Instagram tenian "How Nelson Won Trafalgar Against a Bigger
    Fleet" y lo cambiaron por el de YouTube, "Nelson Trafalgar how the victory secured British seas"."""

    def test_se_queda_el_titulo_que_se_lee_bien(self):
        r = fm.optimize_facebook_metadata({"title": "How Nelson Won Trafalgar Against a Bigger Fleet",
                                           "description": "How did Admiral Nelson break a bigger fleet?"},
                                          research_title="Nelson Trafalgar how the victory secured British seas",
                                          keyword="nelson trafalgar", subject="nelson", brand=BRAND)
        self.assertEqual(r["title"], "How Nelson Won Trafalgar Against a Bigger Fleet")
        self.assertFalse(r["title_changed"])
        self.assertIn("mal redactado", r["summary"])

    def test_un_titulo_investigado_bien_redactado_si_reemplaza(self):
        r = fm.optimize_facebook_metadata({"title": "Trafalgar", "description": "x"},
                                          research_title="Nelson at Trafalgar: the double-column that broke the line",
                                          keyword="nelson trafalgar", brand=BRAND)
        self.assertEqual(r["title"], "Nelson at Trafalgar: the double-column that broke the line")


class Miniatura(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sube_como_preferida(self):
        thumb = _image(self.root / "thumbnail.jpg")
        g = _FakeGraph()
        with patch.object(fu, "_request_json", side_effect=g):
            out = fu.set_video_thumbnail("111", "tok", {"path": str(thumb), "mimetype": "image/jpeg"},
                                         sleep=lambda s: None)
        self.assertTrue(out["ok"])
        method, url, kw = g.calls[0]
        self.assertTrue(url.endswith("/111/thumbnails"))
        self.assertEqual(kw["data"]["is_preferred"], "true")
        self.assertIn("source", kw["files"])
        self.assertNotIn("access_token", url, "el token va en el cuerpo, no en la URL")

    def test_reintenta_errores_transitorios(self):
        thumb = _image(self.root / "thumbnail.jpg")
        g = _FakeGraph(fail_first=2)
        waits = []
        with patch.object(fu, "_request_json", side_effect=g):
            out = fu.set_video_thumbnail("111", "tok", {"path": str(thumb), "mimetype": "image/jpeg"},
                                         sleep=waits.append)
        self.assertTrue(out["ok"])
        self.assertEqual(out["attempts"], 3)
        self.assertEqual(waits, list(fu.THUMBNAIL_RETRY_WAITS[:2]))

    def test_no_reintenta_un_token_vencido(self):
        thumb = _image(self.root / "thumbnail.jpg")
        g = _FakeGraph(fail_first=5, error="Facebook API error 190: Error validating access token")
        with patch.object(fu, "_request_json", side_effect=g):
            out = fu.set_video_thumbnail("111", "tok", {"path": str(thumb), "mimetype": "image/jpeg"},
                                         sleep=lambda s: None)
        self.assertFalse(out["ok"])
        self.assertEqual(out["attempts"], 1)
        self.assertIn("190", out["error"])

    def test_webp_se_convierte_y_se_verifica(self):
        thumb = _image(self.root / "thumbnail.webp", fmt="WEBP")
        served = self.root / "served.jpg"
        _image(served)
        g = _FakeGraph()
        msgs = []
        with patch.object(fu, "_request_json", side_effect=g), \
             patch("requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.content = served.read_bytes()
            out = fu.apply_thumbnail("111", "tok", str(thumb), on_status=msgs.append, sleep=lambda s: None)
        self.assertTrue(out["thumbnail_set"])
        self.assertEqual(g.sent_file[2], "image/jpeg", "WebP -> JPEG")
        self.assertTrue(out["thumbnail_verify"]["match"])
        self.assertTrue(any("verificada" in m for m in msgs))

    def test_si_facebook_guarda_otra_imagen_avisa(self):
        thumb = _image(self.root / "thumbnail.jpg")
        otra = self.root / "otra.jpg"
        im = Image.new("RGB", (720, 1280), (10, 10, 10))
        ImageDraw.Draw(im).rectangle([0, 0, 360, 640], fill=(255, 255, 255))
        im.save(otra)
        g = _FakeGraph()
        msgs = []
        with patch.object(fu, "_request_json", side_effect=g), patch("requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.content = otra.read_bytes()
            out = fu.apply_thumbnail("111", "tok", str(thumb), on_status=msgs.append, sleep=lambda s: None)
        self.assertFalse(out["thumbnail_verify"]["match"])
        self.assertTrue(any("ATENCION" in m for m in msgs))

    def test_un_fallo_de_miniatura_no_tumba_la_publicacion(self):
        with patch.object(fu, "_request_json", side_effect=RuntimeError("Facebook API error 200: Permissions error")):
            out = fu.apply_thumbnail("111", "tok", str(_image(self.root / "thumbnail.jpg")), sleep=lambda s: None)
        self.assertFalse(out["thumbnail_set"])
        self.assertIn("permiso", out["thumbnail_error"])

    def _fake_reel_flow(self):
        return [patch.object(fu, "_start_reel_upload", return_value={"video_id": "222", "upload_url": "https://x"}),
                patch.object(fu, "_upload_local_reel", return_value={"success": True}),
                patch.object(fu, "_finish_reel_upload", return_value={"success": True}),
                patch.object(fu, "_wait_for_reel_ready", return_value={"status": {"video_status": "ready"}})]

    def test_el_reel_recibe_la_miniatura(self):
        video = self.root / "short.mp4"
        video.write_bytes(b"v")
        thumb = _image(self.root / "thumbnail.jpg")
        patches = self._fake_reel_flow()
        for p in patches:
            p.start()
        try:
            with patch.object(fu, "apply_thumbnail", return_value={"thumbnail_set": True}) as ap:
                res = fu.upload_video(str(video), "t", "d", thumbnail_path=str(thumb), page_context=FAKE_PAGE)
        finally:
            for p in patches:
                p.stop()
        ap.assert_called_once()
        self.assertEqual(ap.call_args.args[:3], ("222", "token-falso", str(thumb)))
        self.assertTrue(res["thumbnail_set"])

    def test_el_video_de_pagina_recibe_la_miniatura(self):
        video = self.root / "long.mp4"
        video.write_bytes(b"v" * 10)
        thumb = _image(self.root / "thumbnail.jpg")
        with patch.object(fu, "_start_video_post_upload", return_value={"video_id": "333", "start_offset": 0,
                                                                        "end_offset": 10}), \
             patch.object(fu, "_transfer_video_post_chunk", return_value={"start_offset": 10, "end_offset": 10}), \
             patch.object(fu, "_finish_video_post_upload", return_value={"success": True}), \
             patch.object(fu, "apply_thumbnail", return_value={"thumbnail_set": True}) as ap:
            res = fu.upload_video_post(str(video), "t", "d", thumbnail_path=str(thumb), page_context=FAKE_PAGE)
        self.assertEqual(ap.call_args.args[:3], ("333", "token-falso", str(thumb)))
        self.assertTrue(res["thumbnail_set"])


class DesdeLaCarpeta(unittest.TestCase):

    def test_upload_from_metadata_optimiza_y_pone_la_miniatura_de_la_carpeta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "short.mp4").write_bytes(b"v")
            _image(root / "thumbnail.webp", fmt="WEBP")
            (root / "facebook_metadata.json").write_text(json.dumps(
                {"title": "How Hannibal Fed an Army Across the Alps", "description": HANNIBAL_DESC,
                 "title_mode": "optimize", "research": HANNIBAL_RESEARCH}), encoding="utf-8")
            fake = {"video_id": "444", "url": "https://www.facebook.com/reel/444", "status": "published",
                    "thumbnail_set": True, "thumbnail_sent": str(root / "thumbnail.webp")}
            msgs = []
            with patch.object(fu, "_page_context", return_value=FAKE_PAGE), \
                 patch.object(fu, "upload_video", return_value=dict(fake)) as up:
                res = fu.upload_from_metadata(str(root), on_status=msgs.append)
            kw = up.call_args.kwargs
            self.assertEqual(kw["title"], HANNIBAL_RESEARCH["title"])
            self.assertTrue(kw["description"].endswith("#StunningFactsofHistory"))
            self.assertNotIn("#Mystery", kw["description"])
            self.assertEqual(Path(kw["thumbnail_path"]).name, "thumbnail.webp")
            self.assertIs(kw["page_context"], FAKE_PAGE)
            self.assertEqual(res["hashtags_sent"][-1], "StunningFactsofHistory")
            self.assertEqual(res["title_original"], "How Hannibal Fed an Army Across the Alps")
            saved = json.loads((root / "facebook_upload_result.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["thumbnail_set"])
            self.assertIn("hashtags_sent", saved)
            self.assertTrue(any("hashtags" in m for m in msgs))

    def test_facebook_seo_0_lo_apaga(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "short.mp4").write_bytes(b"v")
            (root / "facebook_metadata.json").write_text(json.dumps({"title": "T", "description": "D #Mystery"}),
                                                         encoding="utf-8")
            with patch.dict(os.environ, {"FACEBOOK_SEO": "0"}), \
                 patch.object(fu, "_page_context", return_value=FAKE_PAGE), \
                 patch.object(fu, "upload_video", return_value={"video_id": "1"}) as up:
                fu.upload_from_metadata(str(root))
            self.assertEqual(up.call_args.kwargs["description"], "D #Mystery")


class Cableado(unittest.TestCase):
    """El Studio y los respaldos (lectura de fuente)."""

    def _src(self, name):
        with open(name, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def test_el_studio_reusa_la_investigacion_de_youtube_y_reporta_al_panel(self):
        s = self._src("auto_video_integration_pyqt6.py")
        self.assertIn("research_from_youtube(results.get('youtube'))", s)
        self.assertIn("_facebook_meta['research'] = _fb_research", s)
        self.assertIn("on_status=lambda msg: notify(f\"   Facebook: {msg}\")", s)
        self.assertIn("_facebook_meta['title_mode'] = fb_title_mode", s)

    def test_el_vps_recibe_los_modulos_que_importa_el_uploader(self):
        s = self._src("auto_video_integration_pyqt6.py")
        for mod in ("facebook_metadata.py", "thumbnail_publish.py", "output_video_locator.py"):
            self.assertIn(f"os.path.join(os.getcwd(), '{mod}')", s)

    def test_los_respaldos_de_facebook_no_usan_mystery_ni_marca_fija(self):
        for name in ("auto_video_integration_pyqt6.py", "platform_metadata_tab.py", "daily_short_pipeline.py"):
            s = self._src(name)
            self.assertNotIn("#History #Mystery #StunningRevelations", s, name)
        self.assertNotIn("preview[:260]", self._src("auto_video_integration_pyqt6.py"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
