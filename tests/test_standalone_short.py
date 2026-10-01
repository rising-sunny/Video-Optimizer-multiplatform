# -*- coding: utf-8 -*-
"""Guardas: del 16:9 sale un Short vertical AUTONOMO, no un trailer.

2026-09-21: el microdocumental de Thera hizo 52.265 reproducciones en Facebook
y 49 vistas en YouTube (sin feed de Shorts para un 16:9). El "teaser" existente
era un trailer con CTA "mira el video completo" y encuadre de misterio: apunta
al video que nadie ve y usa el gancho que en este canal murio.

    .venv\\Scripts\\python.exe test_standalone_short.py
"""

import io
import unittest
from unittest.mock import patch

from channel.channel_profiles import DEFAULT_CHANNEL, select_channel


class _FakeLLM:
    def __init__(self):
        self.prompts = []

    def _generate(self, prompt, **kw):
        self.prompts.append(prompt)
        return "7,000 people lived here. No streets, no doors. They walked on the roofs."


class _FakeTTS:
    def generate_narration(self, script, out, voice_id, language="en", rate="+0%"):
        return None   # corta el flujo despues del guion: es lo unico que probamos aca


def _generator():
    from storyboard_generator import StoryboardGenerator
    gen = StoryboardGenerator.__new__(StoryboardGenerator)
    gen.log = lambda m: None
    gen.gemini_client = _FakeLLM()
    gen.tts = _FakeTTS()
    gen.assemble_video_callback = None
    return gen


LONG = {"topic": "Çatalhöyük", "category": "Ancient Civilizations & Empires",
        "script": "Around 7000 BC, Çatalhöyük housed up to 7,000 people. There were no streets: houses were entered from the roof. " * 5,
        "format_archetype": "mechanism"}


class ElModoStandalone(unittest.TestCase):

    def setUp(self):
        select_channel(DEFAULT_CHANNEL)

    def test_el_prompt_es_un_short_completo_sin_cta(self):
        gen = _generator()
        gen.generate_short_teaser_from_long_video(LONG, language="en", mode="standalone")
        prompt = gen.gemini_client.prompts[0]
        self.assertIn("SELF-CONTAINED", prompt)
        self.assertIn("NOT a trailer", prompt)
        self.assertIn("FIRST SECONDS", prompt, "las reglas medidas del canal entran al Short derivado")
        self.assertIn("NARRATIVE ANGLE", prompt, "hereda el angulo del 16:9")
        self.assertNotIn("Mira el video completo", prompt)
        self.assertNotIn("secreto oculto", prompt)
        self.assertNotIn("MYSTERIOUS", prompt)

    def test_por_defecto_es_standalone(self):
        gen = _generator()
        gen.generate_short_teaser_from_long_video(LONG, language="en")
        self.assertIn("SELF-CONTAINED", gen.gemini_client.prompts[0])

    def test_el_teaser_legado_sigue_existiendo(self):
        gen = _generator()
        gen.generate_short_teaser_from_long_video(LONG, language="es", mode="teaser")
        prompt = gen.gemini_client.prompts[0]
        self.assertIn("CALL-TO-ACTION", prompt)
        self.assertNotIn("SELF-CONTAINED", prompt)

    def test_las_fuentes_estampan_angulo_y_tema(self):
        fuente = io.open("storyboard_generator.py", encoding="utf-8", errors="replace").read()
        self.assertIn('"topic": topic if mode == "standalone" else f"{topic} - Teaser"', fuente)
        self.assertIn('"format_archetype": long_video_storyboard.get(\'format_archetype\')', fuente)
        self.assertIn('"derivation_mode": mode', fuente)

    def test_el_wrapper_y_la_gui_piden_standalone(self):
        wrapper = io.open("auto_video_generator_v2.py", encoding="utf-8", errors="replace").read()
        self.assertIn("mode='standalone'", wrapper)
        self.assertIn("rate=rate, mode=mode", wrapper)
        gui = io.open("auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace").read()
        self.assertIn("Short vertical (autónomo, 60–90 s)", gui)
        self.assertIn("mode='standalone',", gui)
        handlers = io.open("studio_video_assembly_handlers.py", encoding="utf-8", errors="replace").read()
        self.assertIn("YouTube no lo distribuye en Shorts", handlers)


if __name__ == "__main__":
    unittest.main(verbosity=2)
