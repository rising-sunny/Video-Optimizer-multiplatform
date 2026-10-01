# -*- coding: utf-8 -*-
"""Guardas de los tags de YouTube: bien insertados e investigados.

Casos reales del canal al 2026-09-22 (tags GUARDADOS segun la Data API):
6/33 videos sin tags; 'Shorts Great Zimbabwe Great Zimbabwe history Shona...' como
UN tag; '#shorts', 'AncientHistory', 'Baghdad1258' como tags; ['documentary',
'history'] de relleno; el uploader cortaba `tags[:500]` (500 tags, no caracteres).

    .venv\\Scripts\\python.exe test_youtube_tags.py
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from publish import youtube_tags as yt


class LaPuertaFinal(unittest.TestCase):

    def test_separa_texto_por_comas_saltos_y_hashtags(self):
        self.assertEqual(yt.finalize_youtube_tags("roman army, carthage\nsecond punic war"),
                         ["roman army", "carthage", "second punic war"])
        self.assertEqual(yt.finalize_youtube_tags("#AncientHistory #Baghdad1258 #MongolConquest"),
                         ["ancient history", "baghdad1258", "mongol conquest"])

    def test_el_bloque_pegado_de_great_zimbabwe_no_entra(self):
        bloque = "Shorts Great Zimbabwe Great Zimbabwe history Shona Dry stone masonry African ancient city 20"
        self.assertEqual(yt.finalize_youtube_tags([bloque, "great zimbabwe"]), ["great zimbabwe"])

    def test_saca_hash_basura_y_duplicados_conservando_el_orden(self):
        out = yt.finalize_youtube_tags(["#shorts", "Shorts", "Hannibal", "hannibal", "Carthage", "viral", "CARTHAGE"])
        self.assertEqual(out, ["hannibal", "carthage"], "orden de relevancia, no alfabetico")

    def test_tildes_y_simbolos(self):
        self.assertEqual(yt.finalize_youtube_tags(["Çatalhöyük", "<script>", "Hannibal's army"]),
                         ["catalhoyuk", "script", "hannibal's army"])

    def test_largo_contado_como_youtube(self):
        # 'a b' cuenta 5 (3 + comillas), 'cd' 2, una coma entre medio: 8.
        self.assertEqual(yt.counted_length(["a b", "cd"]), 8)
        self.assertEqual(yt.counted_length([]), 0)

    def test_respeta_500_contados_y_prueba_los_siguientes_mas_cortos(self):
        largos = [f"long tag number {i} about the war" for i in range(30)]   # ~34 contados cada uno
        out = yt.finalize_youtube_tags(largos + ["rome"])
        self.assertLessEqual(yt.counted_length(out), 500)
        self.assertIn("rome", out, "si el siguiente largo no entra, uno corto todavia puede")

    def test_los_27_tags_de_hannibal_se_recortan_a_500(self):
        tags = ['Hannibal', 'Hannibal Barca', 'Hannibal Alps', 'Hannibal crossing the Alps', 'Carthaginian Empire',
                'Carthage', 'Punic Wars', 'Second Punic War', 'Ancient Rome', 'Rome vs Carthage', 'ancient warfare',
                'ancient military logistics'] + [f"extra tag {i} history" for i in range(15)]
        out = yt.finalize_youtube_tags(tags)
        self.assertLessEqual(yt.counted_length(out), 500)
        self.assertEqual(out[0], "hannibal")

    def test_nada_devuelve_lista_vacia(self):
        self.assertEqual(yt.finalize_youtube_tags(None), [])
        self.assertEqual(yt.finalize_youtube_tags(""), [])


SCRIPT = ("How did Hannibal sustain 50,000 troops and war elephants across the frozen Alps? He relied on 30,000 "
          "oxen. At the Little St. Bernard pass, rations were distributed every six hours. General Hasdrubal "
          "ordered a stockpile at Aosta. Hannibal Barca led the Carthaginian army of the Second Punic War "
          "against Rome. Crossing the Alps cost him half his army.")

SUGGEST = {
    "hannibal crossing of the alps": ["hannibal crossing the alps", "hannibal crossing the alps with elephants",
                                      "hannibal crossing the alps total war"],
    "hannibal": ["hannibal", "hannibal cooking", "hannibal lecter", "hannibal barca", "hannibal trailer"],
}

COMPETITORS = [
    {"title": "The Real Story of Hannibal", "channel": "History Hit", "views": 145_875,
     "tags": ["history hit", "history hit youtube", "hannibal barca", "second punic war", "carthage"]},
    {"title": "Second Punic War", "channel": "OverSimplified", "views": 20_205_646,
     "tags": ["the second punic war", "second punic war", "hannibal", "hannibal barca", "carthage", "oversimplified"]},
    {"title": "Total War ROME 2 Hannibal Trailer", "channel": "ONE Media", "views": 2_782_048,
     "tags": ["Total War ROME 2", "Trailer", "Gameplay", "hannibal"]},
    {"title": "Across the Alps", "channel": "HistoryMarche", "views": 479_921,
     "tags": ["rome", "roman republic", "hannibal", "second punic war", "war elephants"]},
]


def _research(**kw):
    return yt.research_tags(
        "Hannibal's crossing of the Alps: logistics of feeding an army",
        "Hannibal's 30,000 Oxen: 250kg Rations Across the Alps", SCRIPT,
        suggest_fn=lambda q: SUGGEST.get(q, []), competitor_fn=lambda q: COMPETITORS,
        brand_tag="stunning facts of history", own_channel_names=["Stunning Facts of History"],
        log=lambda m: None, **kw)


class LaInvestigacion(unittest.TestCase):

    def test_la_palabra_clave_es_una_busqueda_real_y_relevante(self):
        rep = _research()
        self.assertEqual(rep["main_keyword"], "hannibal crossing the alps")
        self.assertEqual(rep["tags"][0], "hannibal crossing the alps")

    def test_filtra_homonimos_juegos_y_marcas_ajenas(self):
        tags = _research()["tags"]
        for malo in ("hannibal lecter", "hannibal cooking", "total war rome 2", "history hit", "history hit youtube",
                     "oversimplified", "trailer", "gameplay", "hannibal crossing the alps total war"):
            self.assertNotIn(malo, tags)

    def test_el_consenso_de_la_competencia_entra(self):
        rep = _research()
        self.assertIn("second punic war", rep["tags"])
        self.assertIn("hannibal barca", rep["tags"])
        self.assertGreaterEqual(rep["evidence"]["second punic war"]["competitor_channels"], 3)

    def test_la_marca_propia_va_al_final_y_el_presupuesto_se_respeta(self):
        rep = _research()
        self.assertEqual(rep["tags"][-1], "stunning facts of history")
        self.assertLessEqual(yt.counted_length(rep["tags"]), 500)

    def test_el_borrador_del_llm_solo_entra_si_es_relevante(self):
        rep = _research(draft_tags=["ancient military logistics", "ufo history", "#shorts"])
        self.assertNotIn("ufo history", rep["tags"])
        self.assertNotIn("shorts", rep["tags"])

    def test_sin_red_devuelve_palabra_clave_y_borrador_relevante(self):
        def boom(q):
            raise OSError("sin red")
        rep = yt.research_tags("Siege of Tyre", "Alexander Conquers Tyre in 7 Months",
                               "Alexander the Great besieged Tyre for seven months in 332 BC.",
                               draft_tags=["siege of tyre", "alexander the great", "mystery"],
                               suggest_fn=boom, competitor_fn=boom, log=lambda m: None)
        self.assertFalse(rep["sources_ok"]["autocomplete"])
        self.assertIn("siege of tyre", rep["tags"])
        self.assertIn("alexander the great", rep["tags"])
        self.assertNotIn("mystery", rep["tags"])

    def test_entidades_del_guion_no_del_title_case(self):
        ents = yt.extract_entities("Hannibal's 30,000 Oxen: 250kg Rations Across the Alps", SCRIPT)
        self.assertIn("hannibal", ents)
        self.assertNotIn("rations across the alps", ents)
        self.assertTrue(any("bernard" in e for e in ents), "St. no corta el nombre")


class CasosQueFallaronEnVivo(unittest.TestCase):
    """Los que salieron mal en las pruebas en vivo del 2026-09-22, fijados con fuentes falsas."""

    def test_el_sujeto_desambigua_un_autocompletado_tomado_por_un_juego(self):
        # 'kaiten' a secas devuelve un videojuego (Blue Archive); 'kaiten torpedo' es la busqueda real.
        sug = {"kaiten": ["kaiten grand assault", "kaiten torment", "kaiten trailer"],
               "kaiten torpedo": ["kaiten torpedo", "kaiten human torpedo"],
               "imperial japanese navy": ["imperial japanese navy", "imperial japanese navy ships"]}
        rep = yt.research_tags("Kaiten suicide submarines of the Imperial Japanese Navy",
                               "Japan's WWII Suicide Submarines: The Kaiten",
                               "The Kaiten was a manned torpedo used by the Imperial Japanese Navy in World War II.",
                               suggest_fn=lambda q: sug.get(q, []), competitor_fn=lambda q: [], log=lambda m: None)
        self.assertEqual(rep["main_keyword"], "kaiten torpedo")
        self.assertNotIn("kaiten grand assault", rep["tags"])

    def test_sueltas_genericas_y_juegos_no_entran(self):
        comp = [{"channel": f"C{i}", "views": 10_000, "tags": ["world of warships", "blast", "bikini", "the test",
                                                              "castle bravo", "bikini atoll"]} for i in range(4)]
        rep = yt.research_tags("Castle Bravo nuclear test", "1954: America's Biggest Blast Was an Accident",
                               "Castle Bravo, detonated at Bikini Atoll in 1954, was a nuclear test. The blast was huge.",
                               suggest_fn=lambda q: [], competitor_fn=lambda q: comp, log=lambda m: None)
        for malo in ("world of warships", "blast", "bikini", "the test"):
            self.assertNotIn(malo, rep["tags"])
        self.assertIn("castle bravo", rep["tags"])
        self.assertIn("bikini atoll", rep["tags"])

    def test_casi_duplicados_se_colapsan(self):
        comp = [{"channel": f"C{i}", "views": 5000, "tags": ["roman empire", "the roman empire", "roman empires"]}
                for i in range(3)]
        rep = yt.research_tags("Roman concrete", "Why Roman concrete lasts",
                               "The Roman Empire built with concrete that hardens in seawater.",
                               suggest_fn=lambda q: [], competitor_fn=lambda q: comp, log=lambda m: None)
        romanos = [t for t in rep["tags"] if "roman empire" in t]
        self.assertEqual(len(romanos), 1, romanos)

    def test_la_marca_tiene_lugar_aunque_sobren_candidatos(self):
        sug = {q: [f"hannibal alps tag {i}" for i in range(10)] for q in ("hannibal crossing of the alps", "hannibal")}
        comp = [{"channel": f"C{i}", "views": 1000, "tags": [f"hannibal crossing alps variant {i} {j}" for j in range(10)]}
                for i in range(3)]
        rep = yt.research_tags("Hannibal crossing of the Alps", "Hannibal crossing the Alps",
                               "Hannibal crossing the Alps tag variant " * 20,
                               suggest_fn=lambda q: sug.get(q, []), competitor_fn=lambda q: comp,
                               brand_tag="stunning facts of history", log=lambda m: None)
        self.assertEqual(rep["tags"][-1], "stunning facts of history")
        self.assertLessEqual(yt.counted_length(rep["tags"]), 500)


FAKE_RESEARCH = {"keyword": "hannibal crossing the alps", "subject": "hannibal", "entities": ["hannibal"],
                 "corpus": {"hannibal", "crossing", "alp", "oxen"}, "suggestions": {}, "suggest_ranks": {},
                 "competitors": [], "sources_ok": {"autocomplete": True, "competitors": False}}


class ElUploader(unittest.TestCase):
    """upload_video con el servicio de YouTube simulado: que se manda y que se verifica."""

    def _run(self, stored_tags=None, env=None, research_side_effect=None):
        from channel.channel_profiles import CHANNELS, DEFAULT_CHANNEL
        from publish import youtube_uploader as yu
        insert_bodies = []
        service = MagicMock()
        service.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": CHANNELS[DEFAULT_CHANNEL]["channel_id"]}]}

        def insert(part, body, media_body):
            insert_bodies.append(body)
            return MagicMock()
        service.videos.return_value.insert.side_effect = insert
        service.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"snippet": {"tags": stored_tags if stored_tags is not None else ["a", "b", "c"]}}]}
        fake_report = {"tags": ["hannibal crossing the alps", "second punic war", "stunning facts of history"],
                       "main_keyword": "hannibal crossing the alps", "summary": "3 tags", "evidence": {},
                       "sources_ok": {"autocomplete": True, "competitors": True}}
        research = MagicMock(return_value=fake_report, side_effect=research_side_effect)
        estados = []
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            with open(video, "wb") as fh:
                fh.write(b"x")
            with patch.object(yu, "get_youtube_service", return_value=service), \
                 patch.object(yu, "MediaFileUpload"), \
                 patch.object(yu, "_resumable_upload", return_value={"id": "VID", "status": {"uploadStatus": "uploaded"}}), \
                 patch("publish.youtube_tags.research_tags", research), \
                 patch("publish.youtube_tags.gather_research", return_value=FAKE_RESEARCH), \
                 patch("publish.youtube_titles._default_generate", return_value=[]), \
                 patch("publish.youtube_titles._default_verify", return_value=""), \
                 patch.dict(os.environ, env or {}):
                res = yu.upload_video(video, "Hannibal's 30,000 Oxen", "desc", tags=["#shorts", "Hannibal"],
                                      is_short=True, channel_profile=DEFAULT_CHANNEL, research_topic="Hannibal crossing",
                                      research_script="How did Hannibal...", on_status=estados.append)
        return res, insert_bodies[0], research, estados

    def test_manda_los_tags_investigados_sin_shorts(self):
        res, body, research, estados = self._run()
        self.assertEqual(body["snippet"]["tags"], ["hannibal crossing the alps", "second punic war", "stunning facts of history"])
        self.assertNotIn("Shorts", body["snippet"]["tags"])
        research.assert_called_once()
        self.assertEqual(research.call_args.args[0], "Hannibal crossing", "investiga con el tema, no solo el titulo")
        self.assertEqual(res["tags_sent"], body["snippet"]["tags"])
        self.assertTrue(any("verificado" in e for e in estados))

    def test_avisa_si_youtube_guarda_menos_de_lo_mandado(self):
        res, body, research, estados = self._run(stored_tags=[])
        self.assertTrue(any("YouTube guardo 0" in e for e in estados))
        self.assertEqual(res["tags_stored"], [])

    def test_con_la_investigacion_apagada_limpia_el_borrador(self):
        res, body, research, estados = self._run(env={"YOUTUBE_TAG_RESEARCH": "0"})
        research.assert_not_called()
        self.assertEqual(body["snippet"]["tags"], ["hannibal"])

    def test_si_la_investigacion_falla_la_subida_sigue_con_el_borrador_limpio(self):
        res, body, research, estados = self._run(research_side_effect=RuntimeError("quotaExceeded"))
        self.assertEqual(body["snippet"]["tags"], ["hannibal"])
        self.assertTrue(any("investigacion no disponible" in e for e in estados))
        self.assertEqual(res["video_id"], "VID")

    def test_la_fuente_ya_no_mete_shorts_ni_corta_500_tags(self):
        src = open("publish/youtube_uploader.py", encoding="utf-8").read()
        self.assertNotIn('tags.insert(0, "Shorts")', src)
        self.assertNotIn("tags[:500]", src)


class ElStudioYElMicrodoc(unittest.TestCase):

    def test_el_studio_manda_tema_y_guion_y_separa_bien_el_campo(self):
        src = open("auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace").read()
        self.assertIn("youtube_meta.setdefault('script_excerpt'", src)
        self.assertIn("split_tag_field(yt_tags_raw)", src)
        self.assertIn("on_status=self._publish_log_signal.emit", src)
        self.assertNotIn('"StunningRevelations"] if is_long', src)

    def test_el_microdoc_no_escribe_tags_de_relleno(self):
        src = open("micro_documentary.py", encoding="utf-8", errors="replace").read()
        self.assertNotIn('"tags": ["history", "documentary"]', src)
        self.assertIn('"script_excerpt": sb[\'script\'][:4000]', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
