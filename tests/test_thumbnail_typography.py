# -*- coding: utf-8 -*-
"""Guardas del texto de miniatura con impacto (thumbnail_typography).

2026-09-23: el super prompt pedia "small and restrained" (6% de alto de letra, peso medio,
espaciado amplio, blanco con sombra suave). En la miniatura del caballo mongol el generador
dejo "100 KILOMETERS" en 2.6-3.3% de alto, peso regular, sin contorno, sobre un cielo naranja:
mas chico que las 31 miniaturas con texto de los shorts de historia mas vistos del mes
(rotulos de 1-3 palabras: mediana 6%, cuarto superior ~8%, 12/13 en negrita, 10/13 con
contorno o caja).

    .venv\\Scripts\\python.exe test_thumbnail_typography.py
"""

import io
import json
import re
import unittest
from unittest.mock import patch

from PIL import Image

import thumbnail_typography as tt
from thumbnail_formats import LANDSCAPE_16_9, SHORT_9_16
from thumbnail_research import PALETTES


class ElPlan(unittest.TestCase):

    def test_caballo_mongol_la_cifra_sola_y_grande(self):
        plan = tt.plan_typography("100 KILOMETERS", SHORT_9_16)
        self.assertEqual([(ln["text"], ln["role"]) for ln in plan["lines"]], [("100", "hero"), ("KILOMETERS", "label")])
        self.assertEqual(plan["lines"][0]["cap_pct"], 11.0)
        self.assertEqual(plan["lines"][1]["cap_pct"], 8.0, "4 veces el 2.6% que salio")
        self.assertNotEqual(plan["lines"][0]["color"], tt.WHITE, "la cifra en el color de acento")
        self.assertEqual(plan["lines"][1]["color"], tt.WHITE)
        self.assertLessEqual(plan["widest_pct"], 86)

    def test_explica_por_que_el_blanco_se_perdia_en_el_cielo_naranja(self):
        plan = tt.plan_typography("100 KILOMETERS", SHORT_9_16)
        self.assertTrue(any("1.65:1" in r and "fondo oscuro necesario" in r for r in plan["reasons"]))

    def test_sin_cifra_dos_renglones_parejos(self):
        plan = tt.plan_typography("LOST CITY FOUND", SHORT_9_16, PALETTES["cool"])
        self.assertEqual([ln["text"] for ln in plan["lines"]], ["LOST CITY", "FOUND"])
        self.assertTrue(all(ln["cap_pct"] == 8.0 and ln["color"] == tt.WHITE for ln in plan["lines"]))

    def test_una_palabra_un_renglon(self):
        plan = tt.plan_typography("FOUND", SHORT_9_16)
        self.assertEqual(len(plan["lines"]), 1)
        self.assertEqual(plan["lines"][0]["cap_pct"], 8.0)

    def test_texto_largo_se_achica_y_avisa(self):
        plan = tt.plan_typography("EXTRAORDINARILY UNBELIEVABLE CIRCUMSTANCES", SHORT_9_16)
        self.assertLessEqual(plan["widest_pct"], 86)
        self.assertTrue(any("texto largo" in r for r in plan["reasons"]))

    def test_el_bloque_entra_en_la_zona(self):
        plan = tt.plan_typography("20,000 TROOPS CROSSED DESERTS", SHORT_9_16)
        top, bottom = plan["zone"]
        alto = sum(ln["cap_pct"] * tt.LINE_GAP for ln in plan["lines"])
        self.assertLessEqual(alto, (bottom - top) * 100 + 0.1)

    def test_apaisado_tercio_derecho_y_mas_grande(self):
        plan = tt.plan_typography("100 KILOMETERS", LANDSCAPE_16_9)
        self.assertEqual(plan["lines"][0]["cap_pct"], 16.0)
        d = " ".join(tt.typography_directives(plan))
        self.assertIn("RIGHT third", d)
        self.assertIsNone(plan["subject_band"])


class ElColor(unittest.TestCase):

    def test_contraste_wcag(self):
        self.assertEqual(tt.contrast_ratio("#FFFFFF", "#000000"), 21.0)
        self.assertAlmostEqual(tt.contrast_ratio("#FFFFFF", "#f3c267"), 1.65, places=2)

    def test_escena_calida_cifra_fria_y_al_reves(self):
        warm = tt.choose_accent(PALETTES["warm"], "#1a2330")[0]
        cool = tt.choose_accent(PALETTES["cool"], "#14222b")[0]
        self.assertEqual(warm, "cyan", "tono opuesto al ambar/rojo")
        self.assertEqual(cool, "yellow", "tono opuesto al teal")

    def test_evita_el_color_que_usa_toda_la_competencia(self):
        name = tt.choose_accent(PALETTES["cool"], "#14222b", avoid="yellow")[0]
        self.assertNotEqual(name, "yellow")
        plan = tt.plan_typography("63 SAILORS", SHORT_9_16, PALETTES["cool"],
                                  competitor_text={"fill": {"white": 9, "yellow": 5}})
        self.assertNotEqual(plan["accent_name"], "yellow")


class LasDirectivas(unittest.TestCase):

    def test_numeros_concretos_para_el_generador(self):
        d = " ".join(tt.typography_directives(tt.plan_typography("100 KILOMETERS", SHORT_9_16)))
        self.assertIn('render exactly these words and nothing else: "100 KILOMETERS"', d)
        self.assertIn('line 1 "100" -- cap height 11.0% of the frame height', d)
        self.assertIn("custom bold condensed display lettering", d)
        self.assertIn("NOT Impact", d)
        self.assertIn("no thick outline", d)
        self.assertIn("between y 11% and y 34%", d)
        self.assertIn("no text below 71%", d)

    def test_how_no_hereda_el_acabado_wordart_de_un_plan_guardado(self):
        plan = tt.plan_typography("HOW", SHORT_9_16, PALETTES["cool"])
        plan.update(font="Oswald / Bebas Neue, weight 800-900", outline_fraction=0.10)
        d = " ".join(tt.typography_directives(plan))
        self.assertIn('ONE line "HOW", cap height 8.0%', d)
        self.assertIn("optical kerning", d)
        self.assertIn("matte ink finish", d)
        self.assertIn("no hard offset drop shadow", d)
        self.assertNotIn("Oswald", d)
        self.assertNotIn("one tenth", d)

    def test_la_composicion_deja_lugar_al_texto(self):
        plan = tt.plan_typography("100 KILOMETERS", SHORT_9_16)
        reglas = tt.adapt_composition_rules(SHORT_9_16.composition_rules, plan)
        joined = " ".join(reglas)
        self.assertIn("between y 34% and y 71%", joined)
        self.assertNotIn("between y 12% and y 62%", joined)
        self.assertNotIn("UPPER third", joined)
        self.assertEqual(len(reglas), len(SHORT_9_16.composition_rules))

    def test_en_apaisado_la_composicion_no_cambia(self):
        plan = tt.plan_typography("100 KILOMETERS", LANDSCAPE_16_9)
        self.assertEqual(tt.adapt_composition_rules(LANDSCAPE_16_9.composition_rules, plan),
                         list(LANDSCAPE_16_9.composition_rules))


class ElSuperPrompt(unittest.TestCase):

    def _prompt(self, brief=None):
        from ai.claude_client import ClaudeAiClient
        cc = ClaudeAiClient.__new__(ClaudeAiClient)
        caja = {}

        def fake(prompt, *a, **k):
            caja["p"] = prompt
            from tests.test_thumbnail_superprompt import art_response
            return art_response(hook="100 KILOMETERS")
        cc._generate = fake
        res = cc.generate_thumbnail_super_prompt("Mongol horses", thumbnail_format=SHORT_9_16, research_brief=brief)
        return caja["p"], res

    def test_la_investigacion_aporta_un_candidato_no_un_plan_obligatorio(self):
        brief = {"text": "100 KILOMETERS", "palette": PALETTES["warm"], "family": "warm"}
        p, res = self._prompt(brief)
        self.assertIn('"100 KILOMETERS"', p)
        self.assertIn('not fixed choices', p)
        self.assertIn("between y 34% and y 71%", p)
        self.assertIn("thin or light font weight", p)
        self.assertNotIn("small and restrained", p)

    def test_sin_investigacion_el_modelo_decide_y_la_app_compone_una_vez(self):
        p, res = self._prompt()
        self.assertIn("Choose number_layout=inline or hero", p)
        self.assertIn("between y 34% and y 71%", p)
        # el LLM no metio el texto en el prompt positivo: se agrega con el plan concreto
        self.assertIn('line 1 "100" in #EFC891', res["positive"])
        self.assertEqual(res["positive"].count('render exactly these words'), 1)


class ElTextoDeLaMiniatura(unittest.TestCase):

    def test_una_cifra_con_ritmo_pega_mas(self):
        import thumbnail_research as tr
        guion = "Mongol riders covered 100 kilometers a day with five horses each."
        ops = [o["text"] for o in tr.text_options("How the Mongol army moved so fast", guion,
                                                  {"keyword": "mongol army", "suggestions": {}, "corpus": set()})]
        self.assertEqual(ops[0], "100 KM A DAY", "el ritmo es la noticia; KM para que entre grande")
        self.assertIn("100 KILOMETERS", ops)

    def test_no_inventa_un_ritmo(self):
        import thumbnail_research as tr
        ops = [o["text"] for o in tr.text_options("x", "They rode 100 kilometers to the river.",
                                                  {"keyword": "", "suggestions": {}, "corpus": set()})]
        self.assertFalse(any("A DAY" in o for o in ops))


def _jpeg(size=(1080, 1920), color=(200, 120, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


class LaRevision(unittest.TestCase):

    def _vision(self, full, grid="100 KILOMETERS"):
        def fn(prompt, images):
            return json.dumps(full) if prompt == tt.CHECK_PROMPT else grid
        return fn

    def test_la_miniatura_del_caballo_sale_debil(self):
        full = {"has_text": True, "text": "100 KILOMETERS", "lines": 1, "box_2d": [95, 170, 128, 830],
                "weight": "regular", "outline": "none", "box_behind": False}
        res = tt.check_thumbnail_text(_jpeg(), self._vision(full), expected="100 KILOMETERS")
        self.assertEqual(res["cap_pct"], 3.3)
        self.assertEqual(res["verdict"], "debil")
        joined = " ".join(res["warnings"])
        self.assertIn("letra chica", joined)
        self.assertIn("trazo regular", joined)
        self.assertIn("sin contorno ni caja", joined)

    def test_una_con_impacto_no_avisa(self):
        full = {"has_text": True, "text": "100 KILOMETERS", "lines": 2, "box_2d": [110, 300, 220, 700],
                "weight": "black", "outline": "thick", "box_behind": False}
        res = tt.check_thumbnail_text(_jpeg(), self._vision(full), expected="100 KILOMETERS")
        self.assertEqual(res["verdict"], "con impacto")
        self.assertEqual(res["warnings"], [])

    def test_detecta_el_texto_mal_escrito_y_el_ilegible(self):
        full = {"has_text": True, "text": "100 KILOMETRES", "lines": 1, "box_2d": [110, 200, 200, 800],
                "weight": "black", "outline": "thick"}
        res = tt.check_thumbnail_text(_jpeg(), self._vision(full, grid="UNREADABLE"), expected="100 KILOMETERS")
        joined = " ".join(res["warnings"])
        self.assertIn("se pidio '100 KILOMETERS'", joined)
        self.assertIn("no se lee a 190 px", joined)

    def test_la_vista_de_grilla_recorta_2_3_y_190_px(self):
        im = Image.open(io.BytesIO(tt.grid_view(_jpeg())))
        self.assertEqual(im.size, (380, 570))


class LaMedicion(unittest.TestCase):

    def test_analiza_y_resume(self):
        def fake(prompt, images):
            return json.dumps([
                {"i": 1, "has_text": True, "text": "JODHA BAI", "words": 2, "box_2d": [100, 100, 180, 900],
                 "weight": "black", "fill": "white", "outline": "thick"},
                {"i": 2, "has_text": False},
                {"i": 3, "has_text": True, "text": "FRIENDS BEFORE WW2", "words": 3, "box_2d": [500, 100, 570, 900],
                 "weight": "black", "fill": "yellow", "outline": "thick", "highlight": True},
            ][:len(images)])
        rows = tt.analyze_text_styles([b"a", b"b", b"c"], fake, batch=3)
        self.assertEqual(rows[0]["cap_pct"], 8.0)
        s = tt.summarize_text_styles(rows)
        self.assertEqual((s["n"], s["with_text"]), (3, 2))
        self.assertEqual(s["labels"]["n"], 2)
        self.assertEqual(s["labels"]["heavy_share"], 1.0)

    def test_un_lote_que_falla_no_frena(self):
        rows = tt.analyze_text_styles([b"a", b"b"], lambda p, i: "no json", batch=2, log=lambda m: None)
        self.assertTrue(all(r.get("error") for r in rows))
        self.assertEqual(tt.summarize_text_styles(rows)["n"], 0)

    def test_el_brief_mide_la_competencia_y_arma_el_plan(self):
        import thumbnail_research as tr
        buf = io.BytesIO()
        Image.new("RGB", (320, 180), (200, 90, 30)).save(buf, "JPEG")
        comps = [{"video_id": f"v{i}", "title": f"T{i}", "views": 100 - i, "thumbnail": f"u{i}"} for i in range(3)]
        research = {"keyword": "mongol army", "suggestions": {}, "corpus": set(), "competitors": comps}
        vision = lambda p, ims: json.dumps([{"i": k + 1, "has_text": True, "words": 2, "weight": "black",
                                             "fill": "yellow", "outline": "thick", "box_2d": [100, 0, 180, 1000]}
                                            for k in range(len(ims))])
        b = tr.build_thumbnail_brief("Mongol army", "How the Mongol army moved so fast",
                                     "Mongol riders covered 100 kilometers a day.", research=research,
                                     fetch=lambda u: buf.getvalue(), log=lambda m: None,
                                     thumbnail_format=SHORT_9_16, text_vision_fn=vision)
        self.assertEqual(b["competitor_text"]["with_text"], 3)
        self.assertEqual(b["typography"]["lines"][0]["text"], "100")
        self.assertNotEqual(b["typography"]["accent_name"], "yellow", "toda la competencia usa amarillo")
        self.assertIn("Headline candidates", b["prompt_block"])
        self.assertNotIn("Typography plan", b["prompt_block"])

    def test_el_brief_de_los_tests_no_llama_a_gemini(self):
        import thumbnail_research as tr
        buf = io.BytesIO()
        Image.new("RGB", (320, 180), (200, 90, 30)).save(buf, "JPEG")
        research = {"keyword": "x", "suggestions": {}, "corpus": set(),
                    "competitors": [{"video_id": "v", "title": "T", "views": 1, "thumbnail": "u"}]}
        with patch("ai.gemini_vision.ask_images", side_effect=AssertionError("no deberia llamar")):
            b = tr.build_thumbnail_brief("x", "x", "They rode 100 kilometers.", research=research,
                                         fetch=lambda u: buf.getvalue(), log=lambda m: None)
        self.assertIsNone(b["competitor_text"])


class Cableado(unittest.TestCase):

    def test_el_studio_revisa_al_elegir_y_pasa_el_formato(self):
        with open("auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace") as fh:
            s = fh.read()
        self.assertIn("self._check_thumbnail_text_async(thumbnail_path)", s)
        self.assertIn("thumbnail_format=fmt)", s)
        self.assertIn("self._last_thumbnail_text = result.get('text')", s)

    def test_la_clave_de_gemini_va_en_el_header(self):
        with open("ai/gemini_vision.py", encoding="utf-8") as fh:
            s = fh.read()
        self.assertIn('"x-goog-api-key": key', s)
        self.assertNotIn("?key=", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
