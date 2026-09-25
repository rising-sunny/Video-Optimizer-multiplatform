"""Regresiones de direccion contextual, composicion unica y espacio seguro."""
import re
import unittest
from unittest.mock import Mock

from thumbnail_art_direction import compile_title, parse_art_response, readable_color, contextual_composition_rules
from thumbnail_typography import contrast_ratio
from thumbnail_formats import SHORT_9_16, LANDSCAPE_16_9
from test_thumbnail_superprompt import art_response, cliente_con


class ContextualTitle(unittest.TestCase):
    def test_las_reglas_heredadas_no_imponen_el_color_ni_ocultan_la_formacion(self):
        for fmt in (SHORT_9_16, LANDSCAPE_16_9):
            rules = " ".join(contextual_composition_rules(fmt))
            self.assertNotIn("warm dominant palette", rules)
            self.assertNotIn("red channel stronger", rules)
            self.assertNotIn("shallow depth of field", rules)
            self.assertIn("all elements needed to explain the headline", rules)

    def test_no_reenvia_decisiones_sin_resolver(self):
        with self.assertRaisesRegex(ValueError, "resolver todas"):
            parse_art_response(art_response(scene="A fleet at sea, choose lens and depth of field"))

    def test_dos_escenas_producen_formas_y_colores_distintos_sin_alternativas(self):
        settings = (
            dict(font_family="wedge_serif", base_color="#F1E6CC", accent_color="#EFC891"),
            dict(font_family="geometric_sans", base_color="#D6EDF3", accent_color="#AFDCE5"),
        )
        outputs = []
        for style in settings:
            hook, design, _, _ = parse_art_response(art_response(**style))
            out = compile_title(hook, SHORT_9_16, design)
            self.assertIn(style["base_color"], out)
            self.assertIn(style["accent_color"], out)
            self.assertNotIn("choose", out)
            self.assertNotIn("#FFFFFF", out)
            self.assertNotIn("#FFD23F", out)
            outputs.append(out)
        self.assertIn("wedge serifs", outputs[0])
        self.assertIn("circular counters", outputs[1])
        self.assertNotEqual(*outputs)

    def test_el_numero_puede_ser_parte_de_la_frase_o_protagonista(self):
        for layout, expected in (("inline", 'line 1 "2 COLUMNS"'), ("hero", 'line 1 "2"')):
            _, design, _, _ = parse_art_response(art_response(hook="2 COLUMNS", number_layout=layout))
            self.assertIn(expected, compile_title("2 COLUMNS", SHORT_9_16, design))

    def test_todas_las_letras_entran_en_zona_segura_en_ambos_formatos(self):
        for fmt in (SHORT_9_16, LANDSCAPE_16_9):
            for title in ("2 COLUMNS", "100 KILOMETERS", "LOST CITY FOUND"):
                _, design, _, _ = parse_art_response(art_response(hook=title))
                out = compile_title(title, fmt, design)
                lo, hi = (13, 34) if fmt.is_vertical else (20, 80)
                for cap, top in re.findall(r"cap height ([\d.]+)% of frame height, actual glyph top y ([\d.]+)%", out):
                    self.assertGreaterEqual(float(top), lo)
                    self.assertLessEqual(float(top) + float(cap), hi + 0.1)

    def test_no_esconde_texto_demasiado_largo_en_letras_minimas(self):
        _, design, _, _ = parse_art_response(art_response())
        with self.assertRaisesRegex(ValueError, "demasiado largo"):
            compile_title("EXTRAORDINARILY UNBELIEVABLE CIRCUMSTANCES", SHORT_9_16, design)

    def test_rechaza_colores_invalidos_y_decisiones_ambiguas(self):
        for bad in (dict(base_color="ivory or white"), dict(font_family="serif or sans")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_art_response(art_response(**bad))

    def test_ajusta_luminosidad_sin_imponer_blanco_o_amarillo(self):
        for color, bg in (("#334955", "#14222B"), ("#F1E6CC", "#EEEEDD")):
            corrected = readable_color(color, bg)
            self.assertGreaterEqual(contrast_ratio(corrected, bg), 4.5)
            self.assertNotIn(corrected, ("#FFFFFF", "#FFD23F"))
        self.assertEqual(readable_color("#F1E6CC", "#14222B"), "#F1E6CC")

    def test_exige_evidencia_del_guion_sin_confundirla_con_la_explicacion_visual(self):
        script = "The fleet advanced in two columns."
        scene = "An aerial view of two columns of ships crossing the sea"
        valid = art_response(hook="2 COLUMNS", scene=scene, evidence="two columns", visual_anchor="two columns of ships")
        parse_art_response(valid, script)
        with self.assertRaisesRegex(ValueError, "evidence_quote"):
            parse_art_response(valid, "A cannon fired on the deck.")

    def test_parafrasis_y_anclas_cortas_no_bloquean_el_superprompt(self):
        script = "The fleet advanced in two columns."
        scene = "An aerial view of two parallel formations of wooden warships crossing the sea"
        for anchor in ("Two columns", "Dos columnas navales", "Ships arranged in two lines", "formation"):
            with self.subTest(anchor=anchor):
                response = art_response(hook="2 COLUMNS", scene=scene, evidence="two columns", visual_anchor=anchor)
                cli = cliente_con(response)
                cli._generate = Mock(return_value=response)
                result = cli.generate_thumbnail_super_prompt("Battle of Trafalgar", script_excerpt=script,
                                                             thumbnail_format=SHORT_9_16)
                self.assertIsNotNone(result)
                self.assertEqual(cli._generate.call_count, 1, "una parafrasis no debe gastar un reintento")
                self.assertEqual(result["art_direction"]["visual_anchor"], anchor)
                self.assertTrue(result["positive"].startswith(scene))
                self.assertEqual(result["positive"].count("ONE coherent title"), 1)
                self.assertEqual(result["positive"].split(", render exactly")[0], scene,
                                 "la explicacion no se pega como una segunda escena")

    def test_ancla_ausente_o_malformada_sigue_siendo_un_error(self):
        for anchor in (None, "", "   ", [], {}, 42):
            with self.subTest(anchor=anchor), self.assertRaisesRegex(ValueError, "visual_anchor"):
                parse_art_response(art_response(visual_anchor=anchor))

    def test_el_reintento_no_vuelve_a_exigir_coincidencia_literal_del_ancla(self):
        cli = cliente_con("")
        cli._generate = Mock(side_effect=[art_response(visual_anchor=""), art_response(visual_anchor="Mound")])
        result = cli.generate_thumbnail_super_prompt("Cahokia", thumbnail_format=SHORT_9_16)
        self.assertIsNotNone(result)
        self.assertEqual(cli._generate.call_count, 2)
        repair = cli._generate.call_args.args[0]
        self.assertIn("paraphrases are valid", repair)
        self.assertNotIn("occurs VERBATIM", repair)
        self.assertNotIn("phrase directly from your POSITIVE PROMPT", repair)

    def test_no_anexa_otro_estilo_a_la_escena_con_comillas_curvas(self):
        cli = cliente_con("")
        cli._generate = Mock(side_effect=[
            art_response(hook="2 COLUMNS", scene='An aerial view, “2 COLUMNS”'),
            art_response(hook="2 COLUMNS", scene="An aerial view of two columns of ships"),
        ])
        result = cli.generate_thumbnail_super_prompt("Fleet tactics", thumbnail_format=SHORT_9_16)
        self.assertEqual(cli._generate.call_count, 2)
        self.assertEqual(result["positive"].count("ONE coherent title"), 1)
        self.assertNotIn("“2 COLUMNS”", result["positive"])
        self.assertIn("no repetido", cli._generate.call_args.args[0])

    def test_brief_antiguo_no_impone_el_primer_candidato_ni_su_estilo(self):
        cli = cliente_con(art_response(hook="BY HAND"))
        cli._generate = Mock(return_value=art_response(hook="BY HAND"))
        result = cli.generate_thumbnail_super_prompt("Naval cannon", research_brief={
            "text": "2 COLUMNS", "typography": {"font": "Impact"},
            "prompt_block": '- short_text: use EXACTLY "2 COLUMNS"\n- Typography plan: yellow, thick outline',
        })
        request = cli._generate.call_args.args[0]
        self.assertNotIn("use EXACTLY", request)
        self.assertNotIn("Typography plan", request)
        self.assertEqual(result["text"], "BY HAND")
        self.assertEqual(result["positive"].count("ONE coherent title"), 1)


if __name__ == "__main__":
    unittest.main()
