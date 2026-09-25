# -*- coding: utf-8 -*-
"""Guardas de la miniatura guiada por datos (thumbnail_research + super prompt).

2026-09-22: el super prompt tenia paleta ambar/roja fija, luminancia fija y texto
inventado por el LLM. En vivo, con la investigacion: Pompeii (competencia 5/8 calida)
-> acento teal y '1,000 CASTS'; Kaiten (competencia fria/neutra) -> acento calido y
'63 SAILORS' (el titulo ya dice 100). La primera version propuso 'HE LIVED' para los
pilotos kaiten, que morian: todo texto tiene que estar respaldado por el guion.

    .venv\\Scripts\\python.exe test_thumbnail_research.py
"""

import io
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import thumbnail_research as tr


def _solid(color, size=(320, 180), busy=False):
    im = Image.new("RGB", size, color)
    if busy:
        d = ImageDraw.Draw(im)
        for x in range(0, size[0], 6):
            d.line([(x, 0), (x, size[1])], fill=(255, 255, 255) if x % 12 else (0, 0, 0))
    return im


class AnalisisDeImagen(unittest.TestCase):

    def test_calida_fria_y_neutra(self):
        self.assertEqual(tr.color_family(tr.analyze_image(_solid((200, 90, 30)))), "warm")
        self.assertEqual(tr.color_family(tr.analyze_image(_solid((30, 140, 170)))), "cool")
        self.assertEqual(tr.color_family(tr.analyze_image(_solid((110, 110, 110)))), "neutral")

    def test_brillo_y_carga(self):
        oscura = tr.analyze_image(_solid((20, 20, 30)))
        clara = tr.analyze_image(_solid((230, 225, 215)))
        self.assertLess(oscura["brightness"], 40)
        self.assertGreater(clara["brightness"], 200)
        self.assertGreater(tr.analyze_image(_solid((90, 90, 90), busy=True))["edge_density"],
                           tr.analyze_image(_solid((90, 90, 90)))["edge_density"])


class Diferenciarse(unittest.TestCase):

    def _metrics(self, colors, busy=False):
        return [tr.analyze_image(_solid(c, busy=busy)) for c in colors]

    def test_si_todas_son_calidas_el_acento_es_frio(self):
        s = tr.summarize_competitors(self._metrics([(200, 90, 30)] * 5 + [(110, 110, 110)] * 3))
        d = tr.differentiate(s)
        self.assertEqual(d["family"], "cool")

    def test_si_todas_son_frias_el_acento_es_calido(self):
        s = tr.summarize_competitors(self._metrics([(30, 140, 170)] * 5 + [(100, 100, 100)] * 3))
        self.assertEqual(tr.differentiate(s)["family"], "warm")

    def test_competencia_oscura_pide_sujeto_iluminado(self):
        s = tr.summarize_competitors(self._metrics([(20, 25, 30)] * 6 + [(200, 200, 200)] * 2))
        self.assertEqual(tr.differentiate(s)["luminance"], (125, 165))

    def test_competencia_cargada_pide_minimalismo(self):
        s = tr.summarize_competitors(self._metrics([(90, 90, 90)] * 8, busy=True))
        self.assertTrue(tr.differentiate(s)["minimal"])

    def test_sin_datos_no_rompe(self):
        d = tr.differentiate(tr.summarize_competitors([]))
        self.assertEqual(d["family"], "warm")
        self.assertTrue(d["notes"])


RESEARCH = {"keyword": "plaster casts of pompeii", "suggestions": {"giuseppe fiorelli": 1.0, "pompeii": 0.9},
            "corpus": set()}
SCRIPT = ("The famous bodies of Pompeii are not bodies. In 1863 Giuseppe Fiorelli poured plaster into the voids "
          "left in the ash of Mount Vesuvius. More than 1,000 casts exist.")


class ElTexto(unittest.TestCase):

    def test_how_why_no_pasan_con_un_conjunto_de_palabras_vacio(self):
        with patch("channel_strategy.archetype_cover_words", return_value=["HOW?", "WHY?", "BY HAND"]):
            ops = tr.text_options("Naval cannon", "Sailors loaded the gun by hand.",
                                  {"keyword": "", "suggestions": {}, "corpus": set()}, "mechanism")
        self.assertEqual([o["text"] for o in ops], ["BY HAND"])

    def test_sin_detalle_respaldado_no_impone_una_palabra_generica(self):
        with patch("channel_strategy.archetype_cover_words", return_value=["HOW?", "WHY?", "BY HAND"]):
            ops = tr.text_options("Naval cannon", "The ship sailed.",
                                  {"keyword": "", "suggestions": {}, "corpus": set()}, "mechanism")
        self.assertEqual(ops, [])

    def test_prioriza_la_cifra_nueva_con_formato(self):
        ops = tr.text_options("Plaster casts of Pompeii: Fiorelli's 1863 breakthrough", SCRIPT, RESEARCH, "discovery")
        self.assertEqual(ops[0]["text"], "1,000 CASTS")

    def test_no_repite_una_cifra_que_ya_esta_en_el_titulo(self):
        ops = tr.text_options("Hannibal crossing the Alps with 30,000 oxen",
                              "He led 50,000 troops and 30,000 oxen carrying 250 kilograms.",
                              {"keyword": "hannibal crossing the alps", "suggestions": {}, "corpus": set()}, "mechanism")
        textos = [o["text"] for o in ops]
        self.assertNotIn("30,000 OXEN", textos)
        self.assertEqual(textos[0], "50,000 TROOPS")

    def test_los_anos_no_son_texto_de_miniatura(self):
        textos = [o["text"] for o in tr.text_options("x", SCRIPT, RESEARCH)]
        self.assertFalse(any(t.startswith("1863") for t in textos))

    def test_nunca_afirma_algo_que_el_guion_no_dice(self):
        # 'HE LIVED' / 'ALONE' (palabras del angulo historia humana) para pilotos que morian.
        ops = tr.text_options("Kaiten torpedo: 100 suicide subs in World War II",
                              "The Kaiten was a manned torpedo. About 100 were launched. The USS Mississinewa was sunk, killing 63 sailors.",
                              {"keyword": "kaiten torpedo", "suggestions": {}, "corpus": set()}, "human_story")
        textos = [o["text"] for o in ops]
        self.assertIn("63 SAILORS", textos)
        for falso in ("HE LIVED", "ALONE", "THE ONLY ONE"):
            self.assertNotIn(falso, textos)

    def test_no_repite_el_titulo(self):
        ops = tr.text_options("Giuseppe Fiorelli and the casts of Pompeii", SCRIPT, RESEARCH, "discovery")
        self.assertNotIn("GIUSEPPE FIORELLI", [o["text"] for o in ops])

    def test_ascii_y_largo(self):
        for o in tr.text_options("x", SCRIPT, RESEARCH, "discovery"):
            self.assertTrue(o["text"].isascii())
            self.assertLessEqual(len(o["text"]), 18)


class ElBriefYElPrompt(unittest.TestCase):

    def _brief(self):
        buf = io.BytesIO()
        _solid((200, 90, 30)).save(buf, "JPEG")
        comps = [{"video_id": f"v{i}", "title": f"T{i}", "views": 1000 - i, "thumbnail": f"u{i}"} for i in range(6)]
        research = dict(RESEARCH, competitors=comps)
        return tr.build_thumbnail_brief("The plaster casts of Pompeii", "Plaster casts of Pompeii: Fiorelli's 1863 breakthrough",
                                        SCRIPT, research=research, archetype="discovery",
                                        fetch=lambda url: buf.getvalue(), log=lambda m: None)

    def test_brief_completo(self):
        b = self._brief()
        self.assertEqual(b["competitors"]["n"], 6)
        self.assertEqual(b["family"], "cool", "competencia toda calida -> acento frio")
        self.assertEqual(b["text"], "1,000 CASTS")
        self.assertIn('1,000 CASTS', b["prompt_block"])
        self.assertNotIn('use EXACTLY', b["prompt_block"])
        self.assertIn("#3fb6c6", b["prompt_block"])

    def test_el_super_prompt_usa_la_paleta_y_la_luminancia_del_brief(self):
        from claude_client import ClaudeAiClient
        from thumbnail_formats import SHORT_9_16
        b = self._brief()
        cc = ClaudeAiClient.__new__(ClaudeAiClient)
        capturado = {}

        def fake_generate(prompt, *a, **k):
            capturado["p"] = prompt
            from test_thumbnail_superprompt import art_response
            return art_response(hook="1,000 CASTS", evidence="More than 1,000 casts exist.")
        cc._generate = fake_generate
        cc.generate_thumbnail_super_prompt(topic="Pompeii", script_excerpt=SCRIPT, category="", language="en",
                                           thumbnail_format=SHORT_9_16, research_brief=b)
        prompt = capturado["p"]
        self.assertIn("#3fb6c6", prompt)
        self.assertNotIn("#f3c267, #e07a2b, #b32a1c", prompt)
        self.assertIn('1,000 CASTS', prompt)
        self.assertNotIn('use EXACTLY', prompt)

    def test_la_fuente_del_super_prompt_tiene_los_defaults_solo_sin_brief(self):
        src = open("claude_client.py", encoding="utf-8", errors="replace").read()
        self.assertIn("research_brief=None", src)
        self.assertIn("{color_line}", src)
        self.assertIn("{lum_line}", src)
        self.assertIn("{research_block}", src)

    def test_la_gui_pasa_el_brief(self):
        src = open("auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace").read()
        self.assertIn("build_thumbnail_brief(topic, _title_for_brief", src)
        self.assertIn("research_brief=brief if brief and not brief.get(\"error\") else None", src)


class CifrasConGentilicio(unittest.TestCase):
    """Cannae (2026-09-25) quedo sin texto de gancho: 'Romans' con mayuscula se descartaba como nombre propio."""

    R = {"keyword": "", "suggestions": {}, "corpus": set()}

    def texts(self, title, script):
        return [o["text"] for o in tr.text_options(title, script, self.R, "", max_chars=18)]

    def test_demonyms_are_valid_hook_nouns(self):
        self.assertIn("300 SPARTANS", self.texts("Thermopylae", "Only 300 Spartans held the pass in 480 BC."))
        self.assertIn("86,000 ROMANS", self.texts("Cannae", "About 86,000 Romans and allies fought at Cannae."))

    def test_proper_names_and_title_numbers_are_still_excluded(self):
        self.assertEqual(self.texts("Nelson", "In 1805 Nelson won; by 1806 Villeneuve was dead."), [])
        self.assertNotIn("86,000 ROMANS", self.texts("86,000 Dead", "About 86,000 Romans fought."))

    def test_the_video_opening_hook_now_finds_it(self):
        from video_opening import pick_hook_text
        text, why = pick_hook_text("About 86,000 Romans and allies fought at Cannae. Hannibal waited.", "ANNIHILATED")
        self.assertEqual(text, "86,000 ROMANS")
        self.assertIn("cifra", why)


if __name__ == "__main__":
    unittest.main(verbosity=2)
