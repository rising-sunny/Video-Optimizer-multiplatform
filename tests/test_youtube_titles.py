# -*- coding: utf-8 -*-
"""Guardas de los titulos investigados (youtube_titles): puntaje, hechos y quien decide.

2026-09-22: los titulos salian de pedirle a Groq "un titulo con gancho". Ejemplo real:
"Hannibal's 30,000 Oxen: 250kg Rations Across the Alps" -- sin la busqueda que la gente
hace ("hannibal crossing the alps"). En la prueba en vivo el optimizado fue "Hannibal
crossing the Alps: 50,000 troops and elephants" (95/100 contra 65/100).

    .venv\\Scripts\\python.exe test_youtube_titles.py
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from publish import youtube_titles as yt

SCRIPT = ("How did Hannibal sustain 50,000 troops and war elephants across the frozen Alps? He relied on 30,000 "
          "oxen, each carrying 250 kilograms. General Hasdrubal ordered a stockpile at Aosta.")
TOPIC = "Hannibal's crossing of the Alps: logistics of feeding an army"
RESEARCH = {
    "keyword": "hannibal crossing the alps", "subject": "hannibal", "entities": ["hannibal", "alps", "hasdrubal"],
    "corpus": set(yt.content_tokens(TOPIC + " " + SCRIPT)),
    "suggestions": {"hannibal crossing the alps": 1.0, "hannibal crossing the alps with elephants": 0.9,
                    "hannibal elephants": 0.7, "hannibal lecter": 0.6},
    "suggest_ranks": {}, "sources_ok": {"autocomplete": True, "competitors": True},
    "competitors": [{"title": "How Hannibal Crossed the Alps", "channel": "Our Ancient World", "views": 2104, "tags": []},
                    {"title": "The Second Punic War - OverSimplified (Part 1)", "channel": "OverSimplified",
                     "views": 20_205_646, "tags": []},
                    {"title": "Total War ROME 2 Hannibal Trailer", "channel": "ONE Media", "views": 2_782_048, "tags": []}],
}
BIBLE = {"title_formula": {"ideal_char_range": "40-55", "avoid_words_measured": ["mystery", "curse"],
                           "avoid_openers": ["Uncovering the", "Discover the truth"],
                           "winning_examples_live": ["7,000 People in Catalhoyuk: Urban Giant"], "templates": []}}


def score(title, **kw):
    return yt.score_title(title, RESEARCH, TOPIC + " " + SCRIPT, is_short=True, bible=BIBLE,
                          competitors=yt.competitor_titles(RESEARCH), **kw)


class ElPuntaje(unittest.TestCase):

    def test_el_titulo_viejo_pierde_contra_el_investigado(self):
        viejo = score("Hannibal's 30,000 Oxen: 250kg Rations Across the Alps")
        nuevo = score("Hannibal crossing the Alps: 50,000 troops and elephants")
        self.assertGreater(nuevo["score"], viejo["score"] + 15)
        self.assertTrue(any("no la busqueda" in r for r in viejo["reasons"]))
        self.assertEqual(nuevo["parts"]["palabra_clave"], 30)
        self.assertEqual(nuevo["parts"]["al_principio"], 15)

    def test_la_palabra_clave_al_final_puntua_menos(self):
        al_frente = score("Hannibal crossing the Alps with 30,000 oxen")
        al_final = score("With 30,000 oxen: the story of Hannibal crossing the Alps")
        self.assertGreater(al_frente["parts"]["al_principio"], al_final["parts"]["al_principio"])

    def test_una_cifra_inventada_invalida(self):
        r = score("Hannibal crossing the Alps with 80,000 oxen")
        self.assertFalse(r["valid"])
        self.assertTrue(any("80000" in x for x in r["reasons"]))

    def test_cifras_con_formato_distinto_valen(self):
        self.assertTrue(score("Hannibal crossing the Alps: 50000 troops")["valid"])
        self.assertEqual(yt.unsupported_numbers("250kg rations", SCRIPT), [])

    def test_una_medida_no_respalda_un_conteo(self):
        # 2026-09-22, Pompeii: "Vesuvius' 30 eruptions" con el 30 del guion = "30 km" de ceniza.
        guion = "A column of ash climbed roughly 30 km into the sky and pumice rained for eighteen hours."
        self.assertEqual(yt.unsupported_numbers("Plaster casts of Pompeii show Vesuvius' 30 eruptions", guion),
                         ["30 eruptions"])
        self.assertEqual(yt.unsupported_numbers("A 30-kilometre ash column over Pompeii", guion), [])
        self.assertEqual(yt.unsupported_numbers("Fiorelli spent 30 years on it", "He poured 30 casts."),
                         ["30 years"])

    def test_entre_sustantivos_no_se_juzga(self):
        self.assertEqual(yt.unsupported_numbers("Kaiten torpedo: 100 suicide subs in World War II",
                                                "About 100 were launched."), [])
        self.assertEqual(yt.unsupported_numbers("Pompeii 79 AD", "When Vesuvius erupted in 79 AD"), [])

    def test_un_nombre_que_el_guion_no_menciona_invalida(self):
        r = score("Hannibal crossing the Alps shaped Napoleonic logistics")
        self.assertFalse(r["valid"])
        self.assertEqual(yt.unsupported_names("Kaiten torpedo: Inside the cockpit", "The kaiten torpedo cockpit"), [])

    def test_en_title_case_no_se_invalida_por_mayusculas(self):
        # Caso en vivo: 'Plaster casts of Pompeii Reveal 1,000 Lost Faces' se invalidaba
        # por 'Reveal', 'Lost', 'Faces'. En Title Case la mayuscula no marca nombres.
        self.assertTrue(yt.is_title_case("Hannibal Crossing The Alps Reveals Hidden Supply Lines"))
        self.assertFalse(yt.is_title_case("Hannibal crossing the Alps with 30,000 oxen"))
        r = score("Hannibal Crossing The Alps Reveals Hidden Supply Lines")
        self.assertTrue(r["valid"])
        self.assertEqual(r["parts"]["verificable"], -4)

    def test_las_palabras_del_borrador_cuentan_como_respaldadas(self):
        r = yt.score_title("Kaiten torpedo: Japan's last weapon", RESEARCH, "The kaiten torpedo was a weapon",
                           draft_title="Japan's WWII Suicide Submarines: The Kaiten", bible=BIBLE)
        self.assertFalse(any("Japan" in x for x in r["reasons"]))

    def test_penaliza_lo_que_murio_y_el_ruido(self):
        self.assertLess(score("The Mystery of Hannibal crossing the Alps")["score"],
                        score("The Hannibal crossing the Alps story")["score"])
        r = score("HANNIBAL crossing the Alps 🐘 #shorts")
        self.assertTrue(any("MAYUSCULAS" in x for x in r["reasons"]))
        self.assertTrue(any("emoji" in x for x in r["reasons"]))
        self.assertTrue(any("hashtag" in x for x in r["reasons"]))

    def test_copiar_a_la_competencia_penaliza(self):
        r = score("How Hannibal Crossed the Alps!")
        self.assertTrue(any("casi igual" in x for x in r["reasons"]))

    def test_repetir_palabras_penaliza(self):
        r = score("Hannibal Crossing the Alps: Rations Across the Alps")
        self.assertTrue(any("repetida" in x for x in r["reasons"]))

    def test_largo(self):
        self.assertEqual(yt.length_band(True, BIBLE), (40, 55))
        self.assertEqual(yt.length_band(False, BIBLE), (50, 70))
        self.assertFalse(score("x" * 101)["valid"])


class LaEleccion(unittest.TestCase):

    def _opt(self, mode="optimize", titles=None, draft="Hannibal's 30,000 Oxen: 250kg Rations Across the Alps"):
        return yt.optimize_title(TOPIC, SCRIPT, draft, research=RESEARCH, is_short=True, archetype="mechanism",
                                 mode=mode, generate_fn=lambda p: list(titles or []), bible=BIBLE, own_winners=[],
                                 log=lambda m: None)

    def test_optimize_cambia_si_gana_por_5_o_mas(self):
        rep = self._opt(titles=["Hannibal crossing the Alps: 50,000 troops and elephants"])
        self.assertTrue(rep["changed"])
        self.assertEqual(rep["title"], "Hannibal crossing the Alps: 50,000 troops and elephants")
        self.assertIn("antes", rep["summary"])

    def test_optimize_no_cambia_por_diferencias_minimas(self):
        draft = "Hannibal crossing the Alps with 30,000 oxen"
        rep = self._opt(draft=draft, titles=["Hannibal crossing the Alps: 30,000 oxen"])
        self.assertFalse(rep["changed"])
        self.assertEqual(rep["title"], draft)

    def test_suggest_deja_el_del_usuario_y_reporta_la_alternativa(self):
        rep = self._opt(mode="suggest", titles=["Hannibal crossing the Alps: 50,000 troops and elephants"])
        self.assertFalse(rep["changed"])
        self.assertEqual(rep["title"], "Hannibal's 30,000 Oxen: 250kg Rations Across the Alps")
        self.assertIn("mejor alternativa", rep["summary"])

    def test_nunca_elige_un_candidato_invalido(self):
        rep = self._opt(titles=["Hannibal crossing the Alps with 99,999 oxen", "Hannibal crossing the Alps: Napoleonic lessons"])
        self.assertNotIn("99,999", rep["title"])
        self.assertNotIn("Napoleonic", rep["title"])

    def test_sin_llm_propone_la_clave_al_frente_sin_repetir(self):
        rep = self._opt(titles=[])
        titulos = [c["title"] for c in rep["candidates"]]
        for t in titulos:
            toks = yt.content_tokens(t)
            self.assertEqual(len(toks), len(set(toks)), f"candidato con palabras repetidas: {t}")
        self.assertFalse(any("Alps: 250kg Rations Across the Alps" in t for t in titulos))

    def test_el_llm_que_revienta_no_frena(self):
        def boom(p):
            raise RuntimeError("groq caido")
        rep = yt.optimize_title(TOPIC, SCRIPT, "Hannibal crossing the Alps with 30,000 oxen", research=RESEARCH,
                                generate_fn=boom, bible=BIBLE, own_winners=[], log=lambda m: None)
        self.assertEqual(rep["title"], "Hannibal crossing the Alps with 30,000 oxen")

    def _verificado(self, rechazar, mode="optimize", draft="Hannibal's 30,000 Oxen: 250kg Rations Across the Alps",
                    titles=None, respuesta=None):
        vistos = []

        def verify(prompt):
            import re as _re
            listado = _re.findall(r"^(\d+)\. (.+)$", prompt, _re.M)
            vistos.append([t for _, t in listado])
            if respuesta is not None:
                return respuesta
            return json.dumps({"results": [{"n": int(n), "supported": t not in rechazar, "reason": "contradice el guion"}
                                           for n, t in listado]})
        titles = titles or ["Hannibal crossing the Alps: 50,000 troops and elephants",
                            "Hannibal crossing the Alps: 30,000 oxen carried the food"]
        rep = yt.optimize_title(TOPIC, SCRIPT, draft, research=RESEARCH, is_short=True, archetype="mechanism",
                                mode=mode, generate_fn=lambda p: list(titles), verify_fn=verify, bible=BIBLE,
                                own_winners=[], log=lambda m: None)
        return rep, vistos

    def test_la_verificacion_descarta_al_que_contradice_el_guion(self):
        # Pompeii 22-09: gano "casts ... hold bodies" y el video dice que NO son cuerpos.
        malo = "Hannibal crossing the Alps: 50,000 troops and elephants"
        rep, vistos = self._verificado({malo})
        self.assertNotEqual(rep["title"], malo)
        self.assertIn(malo, vistos[0])
        fila = next(c for c in rep["candidates"] if c["title"] == malo)
        self.assertFalse(fila["valid"])
        self.assertTrue(any("verificacion" in r for r in fila["reasons"]))
        self.assertIn("verificacion descarto", rep["summary"])

    def test_el_borrador_siempre_se_verifica_y_se_avisa_en_suggest(self):
        draft = "Hannibal's 30,000 Oxen: 250kg Rations Across the Alps"
        rep, vistos = self._verificado({draft}, mode="suggest")
        self.assertIn(draft, vistos[0])
        self.assertEqual(rep["title"], draft, "suggest respeta al usuario")
        self.assertIn("no paso la verificacion", rep["summary"])

    def test_si_la_verificacion_no_responde_se_sigue_sin_ella(self):
        rep, _ = self._verificado(set(), respuesta="ERROR: groq caido")
        self.assertEqual(rep["title"], "Hannibal crossing the Alps: 50,000 troops and elephants")

    def test_parseo_de_la_verificacion(self):
        v = yt.parse_factcheck('ok {"results": [{"n": 1, "supported": "false", "reason": "x"}, {"n": 2, "supported": true}]}')
        self.assertEqual(v, {0: (False, "x"), 1: (True, "")})
        self.assertEqual(yt.parse_factcheck("nada"), {})

    def test_con_generador_inyectado_y_sin_verificador_no_llama_al_llm(self):
        with patch("publish.youtube_titles._default_verify", side_effect=AssertionError("no deberia verificar")):
            self._opt(titles=["Hannibal crossing the Alps: 50,000 troops and elephants"])

    def test_el_prompt_lleva_la_investigacion(self):
        p = yt.build_title_prompt(TOPIC, SCRIPT, "draft", RESEARCH, is_short=True, bible=BIBLE)
        self.assertIn('"hannibal crossing the alps"', p)
        self.assertIn("hannibal crossing the alps with elephants", p)
        self.assertIn("How Hannibal Crossed the Alps", p)
        self.assertNotIn("Total War", p, "los titulos de juegos no son competencia")
        self.assertNotIn("hannibal lecter", p, "las busquedas homonimas no entran")


class ParseoDelLLM(unittest.TestCase):

    def test_json_lista_y_lineas(self):
        self.assertEqual(yt.parse_titles('{"titles": ["Hannibal crossing the Alps: A", "Second title here"]}'),
                         ["Hannibal crossing the Alps: A", "Second title here"])
        self.assertEqual(yt.parse_titles('```json\n["Hannibal crossing the Alps: B"]\n```'),
                         ["Hannibal crossing the Alps: B"])
        self.assertEqual(yt.parse_titles("1. Hannibal crossing the Alps: C\n- Another good title"),
                         ["Hannibal crossing the Alps: C", "Another good title"])
        self.assertEqual(yt.parse_titles(""), [])


class ElUploaderYElStudio(unittest.TestCase):

    def _upload(self, title_mode, titles):
        from channel.channel_profiles import CHANNELS, DEFAULT_CHANNEL
        from publish import youtube_uploader as yu
        bodies = []
        service = MagicMock()
        service.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": CHANNELS[DEFAULT_CHANNEL]["channel_id"]}]}
        service.videos.return_value.insert.side_effect = lambda part, body, media_body: bodies.append(body) or MagicMock()
        service.videos.return_value.list.return_value.execute.return_value = {"items": [{"snippet": {"tags": []}}]}
        estados = []
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            with open(video, "wb") as fh:
                fh.write(b"x")
            with patch.object(yu, "get_youtube_service", return_value=service), \
                 patch.object(yu, "MediaFileUpload"), \
                 patch.object(yu, "_resumable_upload", return_value={"id": "VID", "status": {"uploadStatus": "uploaded"}}), \
                 patch("publish.youtube_tags.gather_research", return_value=RESEARCH), \
                 patch("publish.youtube_titles._default_generate", return_value=titles), \
                 patch("publish.youtube_titles._default_verify", return_value=""), \
                 patch.dict(os.environ, {"YOUTUBE_TAG_RESEARCH": "0"}):
                res = yu.upload_video(video, "Hannibal's 30,000 Oxen: 250kg Rations Across the Alps", "desc",
                                      tags=["hannibal"], is_short=True, channel_profile=DEFAULT_CHANNEL,
                                      research_topic=TOPIC, research_script=SCRIPT, on_status=estados.append,
                                      title_mode=title_mode, archetype="mechanism")
        return res, bodies[0], estados

    def test_optimize_sube_el_titulo_investigado(self):
        res, body, estados = self._upload("optimize", ["Hannibal crossing the Alps: 50,000 troops and elephants"])
        self.assertEqual(body["snippet"]["title"], "Hannibal crossing the Alps: 50,000 troops and elephants")
        self.assertEqual(res["title_original"], "Hannibal's 30,000 Oxen: 250kg Rations Across the Alps")
        self.assertTrue(any("Titulo:" in e for e in estados))

    def test_suggest_sube_el_del_usuario(self):
        res, body, estados = self._upload("suggest", ["Hannibal crossing the Alps: 50,000 troops and elephants"])
        self.assertEqual(body["snippet"]["title"], "Hannibal's 30,000 Oxen: 250kg Rations Across the Alps")
        self.assertIn("mejor alternativa", res["title_research"]["summary"])

    def test_el_studio_marca_quien_invento_el_titulo(self):
        src = open("studio/auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace").read()
        self.assertIn('title_mode = "optimize"', src)
        # (?<!\w): 'fb_title_mode = "suggest"' es el de Facebook (test_facebook_metadata), no cuenta aca.
        import re
        self.assertEqual(len(re.findall(r'(?<!\w)title_mode = "suggest"', src)), 2,
                         "Metadata Studio y piloto aprobado = del usuario")
        self.assertIn("youtube_meta.setdefault('title_mode', title_mode)", src)


class LaRedaccion(unittest.TestCase):
    """Dos videos distintos, la misma causa: la busqueda del autocompletado pegada tal cual.
    - Trafalgar (24-09): "Nelson Trafalgar how the victory secured British seas" en YouTube, y
      Facebook/Instagram pisaron "How Nelson Won Trafalgar Against a Bigger Fleet" con ese.
    - U-boat (23-09, otro video): "U boat 48 crew survived..." (el guion dice "U-boat")."""

    TRAFALGAR_SCRIPT = ("How did Admiral Nelson break a numerically superior fleet using unconventional tactics on "
                        "October 21 1805? At 12:45 PM, Nelson ordered his ships to sail perpendicular, forming a "
                        "daring double‑column that smashed the Franco‑Spanish line.")
    TRAFALGAR_TOPIC = "How Nelson Won Trafalgar Against a Bigger Fleet"
    UBOAT_SCRIPT = "The U‑boat U-977 fled to Argentina. Its 48 crew survived a 70‑day Atlantic crossing."

    def _research(self, keyword, subject, text):
        return {"keyword": keyword, "subject": subject, "entities": [], "corpus": set(yt.content_tokens(text)),
                "suggestions": {keyword: 1.0}, "suggest_ranks": {}, "competitors": [], "sources_ok": {}}

    def test_trafalgar_la_busqueda_pegada_no_es_un_titulo(self):
        self.assertTrue(yt.readability_issues("Nelson Trafalgar how the victory secured British seas",
                                              "nelson trafalgar"))
        for bien in ("Nelson at Trafalgar: how the victory secured British seas", self.TRAFALGAR_TOPIC,
                     "Hannibal crossing the Alps with 30,000 oxen", "Kaiten torpedo: 100 suicide subs in World War II"):
            self.assertEqual(yt.readability_issues(bien, "nelson trafalgar"), [], bien)

    def test_trafalgar_gana_un_titulo_bien_redactado(self):
        pegado = "Nelson Trafalgar how the victory secured British seas"
        rep = yt.optimize_title(self.TRAFALGAR_TOPIC, self.TRAFALGAR_SCRIPT, "Nelson's 1805 Miracle: 3 Ships Beat 30!",
                                research=self._research("nelson trafalgar", "nelson",
                                                        self.TRAFALGAR_TOPIC + " " + self.TRAFALGAR_SCRIPT),
                                generate_fn=lambda p: [pegado], bible=BIBLE, own_winners=[], log=lambda m: None)
        self.assertNotEqual(rep["title"], pegado)
        fila = next(c for c in rep["candidates"] if c["title"] == pegado)
        self.assertFalse(fila["valid"])
        self.assertTrue(any(r.startswith("redaccion:") for r in fila["reasons"]))
        self.assertIn(self.TRAFALGAR_TOPIC, [c["title"] for c in rep["candidates"]],
                      "el titulo con el que se escribio el guion compite")

    def test_uboat_se_escribe_como_en_el_guion(self):
        formas = yt.canonical_forms(self.UBOAT_SCRIPT)
        self.assertEqual(formas.get("u boat"), "U-boat")
        self.assertEqual(yt.apply_canonical_forms("U boat 48 crew survived a 70-day Atlantic odyssey", formas),
                         "U-boat 48 crew survived a 70-day Atlantic odyssey")

    def test_el_guion_no_separable_del_guion_pasa_a_guion_comun(self):
        # prueba en vivo de Trafalgar: el elegido traia "double‑column" copiado del guion
        self.assertEqual(yt.apply_canonical_forms("Nelson at Trafalgar: 1805 double‑column wins", {}),
                         "Nelson at Trafalgar: 1805 double-column wins")

    def test_la_verificacion_del_llm_tambien_juzga_la_redaccion(self):
        v = yt.parse_factcheck('{"results": [{"n": 1, "supported": true, "natural": false, "reason": "missing words"}]}')
        self.assertEqual(v, {0: (False, "redaccion: missing words")})
        self.assertIn('"natural"', yt.build_factcheck_prompt(["x"], "script"))

    def test_el_pedido_al_llm_no_manda_pegar_la_clave(self):
        p = yt.build_title_prompt(self.TRAFALGAR_TOPIC, self.TRAFALGAR_SCRIPT, "draft",
                                  self._research("nelson trafalgar", "nelson", self.TRAFALGAR_SCRIPT), is_short=True, bible=BIBLE)
        self.assertIn("NEVER write the bare keyword followed directly by a lowercase clause", p)
        self.assertIn("Franco-Spanish", p)
        self.assertNotIn("in the FIRST 3-4 words", p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
