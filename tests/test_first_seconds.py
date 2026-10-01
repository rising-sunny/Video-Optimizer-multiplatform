# -*- coding: utf-8 -*-
"""Guardas de los primeros segundos: cifra o pregunta primero, la fecha despues.

MEDIDO 2026-09-21 en Facebook (curvas de retencion por segundo): los reels que
abren con fecha ("In 1540, ...", "On May 29, 1453, ...") retienen ~30% al primer
cuarto; el mejor de la pagina ("They calculated six megatons. They got fifteen.")
50/37/33% y no lleva fecha. El Bible pedia "cifra O FECHA" y el pipeline abria
casi siempre con la fecha.

    .venv\\Scripts\\python.exe test_first_seconds.py
"""

import io
import unittest

import channel_strategy as cs
from channel_profiles import DEFAULT_CHANNEL, select_channel


class PrimeraFrase(unittest.TestCase):

    def test_corta_en_punto_signo_o_interrogacion(self):
        self.assertEqual(cs.first_sentence("How did they breathe? Nobody knows."), "How did they breathe?")
        self.assertEqual(cs.first_sentence("They got fifteen! Then the island vanished."), "They got fifteen!")
        self.assertEqual(cs.first_sentence("sin puntuacion final"), "sin puntuacion final")
        self.assertEqual(cs.first_sentence(""), "")

    def test_un_decimal_no_corta_la_frase(self):
        self.assertEqual(cs.first_sentence("A 2.9 kiloton blast shattered Halifax. Then came the wave."),
                         "A 2.9 kiloton blast shattered Halifax.")


class ElVeredicto(unittest.TestCase):

    def setUp(self):
        select_channel(DEFAULT_CHANNEL)

    def _lines(self, text):
        return cs.hook_report(text)[1]

    def test_la_mejor_curva_de_facebook_pasa_limpia(self):
        self.assertEqual(self._lines("They calculated six megatons. They got fifteen."), ["[OK] abre con cifra"])

    def test_pregunta_de_mecanismo_pasa(self):
        self.assertEqual(self._lines("How did 7,000 people live without streets? Catalhoyuk had no doors."), ["[OK] abre con cifra"])
        self.assertEqual(self._lines("Why did Roman concrete get stronger underwater? Seawater."), ["[OK] abre con pregunta"])

    def test_abrir_con_fecha_avisa(self):
        lines = self._lines("In 1540, Portuguese cannon fire toppled a 24-meter obelisk.")
        self.assertTrue(any("abre con fecha" in l for l in lines))
        self.assertIn("[OK] abre con cifra", lines, "la cifra fuera de la fecha sigue contando")

    def test_fecha_sin_cifra_avisa_dos_veces(self):
        lines = self._lines("On May 29, 1453, the Orban cannon thundered.")
        self.assertTrue(any("abre con fecha" in l for l in lines))
        self.assertTrue(any("no trae cifra ni pregunta" in l for l in lines))

    def test_carraspeo_avisa(self):
        self.assertTrue(any("carraspeando" in l for l in self._lines("Did you know 20,000 people lived in a stone city?")))

    def test_largo_avisa(self):
        largo = "The volcano erupted and the island vanished under the sea forever and nobody ever came back."
        self.assertTrue(any("palabras" in l for l in self._lines(largo)))

    def test_prohibido_es_fail(self):
        ok, lines = cs.hook_report("Top 5 facts about Rome.")
        self.assertFalse(ok)
        self.assertTrue(any(l.startswith("[FAIL]") for l in lines))

    def test_validate_hook_sigue_compatible(self):
        ok, msg = cs.validate_hook("They calculated six megatons. They got fifteen.")
        self.assertTrue(ok); self.assertEqual(msg, "Hook passes validation")
        ok, msg = cs.validate_hook("In 1540, the obelisk fell.")
        self.assertTrue(ok); self.assertTrue(msg.startswith("WARNING"))
        ok, msg = cs.validate_hook("Top 10 things you didn't know")
        self.assertFalse(ok)


class ElPromptYElRender(unittest.TestCase):

    def setUp(self):
        select_channel(DEFAULT_CHANNEL)

    def test_el_prompt_pide_cifra_o_pregunta_y_prohibe_la_fecha_al_abrir(self):
        instr = cs.build_hook_prompt_instructions()
        self.assertIn("FIRST SECONDS", instr)
        self.assertIn("The date goes in the SECOND sentence", instr)
        self.assertIn("They calculated six megatons", instr)
        self.assertNotIn('"In 536 AD"', instr, "el ejemplo viejo de abrir con fecha no puede seguir en el prompt")

    def test_el_bible_trae_la_regla_con_evidencia(self):
        fs = cs.get_first_seconds_rules()
        self.assertGreaterEqual(len(fs.get("rules", [])), 3)
        self.assertRegex(fs.get("evidence", ""), r"\d")

    def test_el_render_imprime_el_qa_del_gancho(self):
        from auto_video_generator_v2 import AutoVideoGenerator
        logs = []
        gen = AutoVideoGenerator.__new__(AutoVideoGenerator)
        gen.log = logs.append
        gen._current_storyboard_data = {"segments": [{"narration": "In 1540, the obelisk fell. It weighed 500 tons."}]}
        problems = gen.log_hook_qa()
        texto = "\n".join(logs)
        self.assertIn("QA DEL GANCHO", texto)
        self.assertIn("abre con fecha", texto)
        self.assertTrue(all(p.startswith("[WARN]") for p in problems))

    def test_sin_segmentos_no_imprime_nada(self):
        from auto_video_generator_v2 import AutoVideoGenerator
        logs = []
        gen = AutoVideoGenerator.__new__(AutoVideoGenerator)
        gen.log = logs.append
        gen._current_storyboard_data = {"segments": []}
        self.assertEqual(gen.log_hook_qa(), [])
        self.assertEqual(logs, [])

    def test_el_qa_de_audio_incluye_el_del_gancho(self):
        fuente = io.open("auto_video_generator_v2.py", encoding="utf-8", errors="replace").read()
        self.assertIn("hook_problems = self.log_hook_qa()", fuente)
        self.assertIn("self._current_storyboard_data = storyboard_data", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
