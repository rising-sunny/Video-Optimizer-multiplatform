# -*- coding: utf-8 -*-
"""Regresion: "Super prompt no valido (el positivo debe contener solo la escena, sin tipografia)".

Groq a veces mete una palabra tipografica ("serif", "lettering") en la escena. Antes eso
descartaba la respuesta entera; dos intentos asi y el usuario se quedaba SIN super prompt
(2026-09-24). Ahora se quita solo ese fragmento: la escena sigue sin tipografia y el texto
de la miniatura lo agrega la app una vez (compile_title), en el mismo super prompt.
"""

import unittest
from unittest import mock

from thumbnail_art_direction import compile_title, parse_art_response, strip_scene_typography
from thumbnail_formats import SHORT_9_16
from tests.test_thumbnail_superprompt import art_response

SCENE = ("muddy battlefield at Agincourt under an overcast November sky, rows of sharpened wooden stakes in the "
         "mud, English longbowmen in woolen tunics drawing their bows, a rain of arrows arcing toward French "
         "knights in plate armor, tiny silhouette of a knight for scale, cinematic low-angle view, 50mm lens")


class LaEscenaSeLimpia(unittest.TestCase):
    def test_one_typography_fragment_is_removed_not_the_whole_answer(self):
        scene = SCENE + ", bold serif lettering space at the top, vertical 9:16, photoreal"
        hook, design, clean, _ = parse_art_response(art_response(hook="MUDDY STAKES", scene=scene))
        self.assertNotIn("serif", clean)
        self.assertNotIn("lettering", clean)
        self.assertIn("longbowmen", clean)
        self.assertIn("photoreal", clean)
        self.assertEqual(design["scene_cleanup"], ["bold serif lettering space at the top"])

    def test_the_headline_repeated_in_the_scene_is_removed_too(self):
        scene = SCENE + ', the words "MUDDY STAKES" painted on a banner'
        _, design, clean, _ = parse_art_response(art_response(hook="MUDDY STAKES", scene=scene))
        self.assertNotIn("MUDDY STAKES", clean)
        self.assertEqual(len(design["scene_cleanup"]), 1)

    def test_the_final_super_prompt_still_carries_the_text(self):
        scene = SCENE + ", title in a condensed slab serif font"
        hook, design, clean, _ = parse_art_response(art_response(hook="MUDDY STAKES", scene=scene,
                                                                 font_family="humanist_serif"))
        positive = f"{clean}, {compile_title(hook, SHORT_9_16, design)}"
        self.assertIn('render exactly these words and nothing else: "MUDDY STAKES"', positive)
        self.assertNotIn("slab serif", positive)                             # la tipografia improvisada no queda
        self.assertEqual(positive.lower().count("humanist serif capitals"), 1)  # solo el bloque de la app

    def test_a_scene_that_is_mostly_typography_is_still_rejected_with_a_precise_reason(self):
        scene = "serif font title, lettering at the top, kerning optical, text block centered, a ship"
        with self.assertRaises(ValueError) as ctx:
            parse_art_response(art_response(scene=scene))
        msg = str(ctx.exception)
        self.assertIn("sin tipografia", msg)
        self.assertIn("remove", msg)
        self.assertIn("serif", msg)

    def test_unresolved_decisions_are_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "resolver todas"):
            parse_art_response(art_response(scene=SCENE + ", choose lens and depth of field"))

    def test_clean_scene_is_untouched(self):
        _, design, clean, _ = parse_art_response(art_response(scene=SCENE))
        self.assertEqual(clean, SCENE)
        self.assertNotIn("scene_cleanup", design)

    def test_strip_helper(self):
        clean, removed = strip_scene_typography("a ship, gold lettering on the stern, calm sea", "")
        self.assertEqual(clean, "a ship, calm sea")
        self.assertEqual(removed, ["gold lettering on the stern"])


AGINCOURT_REAL = (   # la escena que devolvio Groq y salio con el 9,000 dos veces (2026-09-24)
    "A muddy battlefield in northern France, 1415, rows of sharpened wooden stakes forming a defensive barrier "
    "across the field, a weathered wooden plank propped against a stake bearing the bold number 9,000 carved in "
    "medieval block letters, a tiny silhouette of an English longbowman in woolen surcoat and chainmail seen "
    "from behind for scale, overcast winter sky with low diffused light, key light from left creating deep "
    "shadows on the ground, cool teal highlights on wet mud and wood, cinematic depth of field with 35mm lens, "
    "foreground stakes and plank in sharp focus, background blurred, vertical 9:16 YouTube Shorts thumbnail, "
    "1080x1920, photoreal")


class ElTitularUnaSolaVez(unittest.TestCase):
    """La miniatura de Agincourt salio con el '9,000' en el titulo y tallado en una tabla."""

    def test_the_carved_number_on_the_plank_is_removed(self):
        _, design, clean, _ = parse_art_response(art_response(hook="9,000", scene=AGINCOURT_REAL))
        self.assertNotIn("9,000", clean)
        self.assertNotIn("block letters", clean)
        self.assertIn("longbowman", clean)
        self.assertIn("35mm lens", clean)
        self.assertTrue(any("carved in medieval block letters" in r for r in design["scene_cleanup"]))

    def test_other_writing_in_the_scene_is_removed(self):
        for extra in ("a stone tablet with a Latin inscription", "a banner with gold words",
                      'a signboard reading "AGINCOURT"', "Roman numerals chiselled into the lintel"):
            with self.subTest(extra=extra):
                _, design, clean, _ = parse_art_response(art_response(hook="MUDDY STAKES",
                                                                      scene=SCENE + ", " + extra))
                self.assertNotIn(extra, clean)

    def test_a_count_in_the_scene_keeps_the_description_without_the_number(self):
        scene = SCENE + ", a line of 9,000 archers behind the stakes"
        _, design, clean, _ = parse_art_response(art_response(hook="9,000 ARCHERS", scene=scene))
        self.assertIn("a line of archers behind the stakes", clean)
        self.assertNotIn("9,000", clean)

    def test_objects_and_scene_words_are_not_false_positives(self):
        scene = SCENE + ", a letter sealed with red wax on a crate, rows of muddy stakes"
        _, design, clean, _ = parse_art_response(art_response(hook="MUDDY STAKES", scene=scene))
        self.assertIn("a letter sealed with red wax on a crate", clean)
        self.assertIn("rows of muddy stakes", clean)
        self.assertNotIn("scene_cleanup", design)

    def test_title_directive_and_negative_say_the_headline_appears_once(self):
        hook, design, clean, _ = parse_art_response(art_response(hook="9,000", scene=AGINCOURT_REAL))
        self.assertIn("the headline appears ONLY ONCE", compile_title(hook, SHORT_9_16, design))
        from claude_client import ClaudeAiClient
        client = ClaudeAiClient.__new__(ClaudeAiClient)
        with mock.patch.object(ClaudeAiClient, "_generate",
                               return_value=art_response(hook="9,000", scene=AGINCOURT_REAL)) as gen:
            out = client.generate_thumbnail_super_prompt("Agincourt", "", "History", language="en",
                                                         thumbnail_format=SHORT_9_16, render_text=True)
        self.assertIn("Never put the headline, its number or any other writing ON an object", gen.call_args.args[0])
        self.assertIn("second copy of the headline", gen.call_args.args[0])
        scene_part = out["positive"].split("render exactly these words")[0]
        self.assertNotIn("9,000", scene_part)


class ElSuperPromptNoSeCae(unittest.TestCase):
    def test_a_stray_typography_word_no_longer_leaves_the_user_without_a_prompt(self):
        from claude_client import ClaudeAiClient
        client = ClaudeAiClient.__new__(ClaudeAiClient)
        reply = art_response(hook="MUDDY STAKES", scene=SCENE + ", bold serif lettering space at the top")
        with mock.patch.object(ClaudeAiClient, "_generate", return_value=reply) as gen:
            out = client.generate_thumbnail_super_prompt("Agincourt", "", "History", language="en",
                                                         thumbnail_format=SHORT_9_16, render_text=True)
        self.assertIsNotNone(out)
        self.assertEqual(gen.call_count, 1)                                  # sin reintento
        self.assertIn('render exactly these words and nothing else: "MUDDY STAKES"', out["positive"])
        self.assertNotIn("serif lettering space", out["positive"])


if __name__ == "__main__":
    unittest.main()
