# -*- coding: utf-8 -*-
"""Guardas del ANGULO narrativo (format_archetype): de la GUI al prompt, al cover y al thumbnail.

2026-09-21: el muestreo de 106 shorts de historia del mes mostro que tres
formatos concentran los millones -- "como lo hicieron", "hallazgo", "historia
humana" -- y este canal no hacia ninguno. El angulo es la dimension que separa
10x; ahora se elige (o se infiere) y viaja por toda la cadena.

    .venv\\Scripts\\python.exe test_format_archetypes.py
"""

import io
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

import channel_strategy as cs
from channel_profiles import DEFAULT_CHANNEL, select_channel


class ElBibleTieneLosCuatroAngulos(unittest.TestCase):

    def setUp(self):
        select_channel(DEFAULT_CHANNEL)

    def test_ids_y_campos(self):
        ids = [a["id"] for a in cs.get_format_archetypes()]
        self.assertEqual(ids, ["mechanism", "discovery", "human_story", "scale_event"])
        for a in cs.get_format_archetypes():
            for campo in ("prompt", "hook_templates", "title_templates", "cover_words", "thumbnail", "evidence"):
                self.assertTrue(a.get(campo), f"{a['id']} sin {campo}")

    def test_cada_angulo_cita_su_evidencia(self):
        # Sin numero medido no hay angulo: es la regla de este proyecto.
        for a in cs.get_format_archetypes():
            self.assertRegex(a["evidence"], r"\d", a["id"])

    def test_lo_que_murio_salio_del_bible(self):
        words = cs.get_cover_frame_config().get("word_examples", [])
        for muerto in ("THE CURSE", "DEAD HAND", "NO SURVIVORS"):
            self.assertNotIn(muerto, words)
        self.assertIn("HOW?", words)
        titulos = cs.get_channel_strategy()["title_formula"]["winning_examples_live"]
        self.assertFalse(any("Mystery" in t for t in titulos))
        self.assertTrue(any("7,000 People" in t for t in titulos))
        reject = " ".join(cs.get_channel_strategy()["topic_scorecard"]["reject_if"])
        self.assertIn("Mystery framing", reject)


class ElAngulo(unittest.TestCase):

    def setUp(self):
        select_channel(DEFAULT_CHANNEL)
        cs.set_active_archetype("")

    def tearDown(self):
        cs.set_active_archetype("")

    def test_auto_por_palabras_del_tema(self):
        self.assertEqual(cs.pick_archetype_auto("Why Roman concrete gets stronger underwater"), "mechanism")
        self.assertEqual(cs.pick_archetype_auto("Archaeologists found a 5,000-year-old dress"), "discovery")
        self.assertEqual(cs.pick_archetype_auto("The U-boat that escaped to Argentina"), "human_story")

    def test_auto_sin_pistas_usa_lo_medido_y_si_no_el_fallback(self):
        with patch.object(cs, "performance_archetype_weights", return_value={"human_story": 1.4, "scale_event": 1.1}):
            self.assertEqual(cs.pick_archetype_auto("Kadesh 1274 BC"), "human_story")
        with patch.object(cs, "performance_archetype_weights", return_value={}):
            self.assertEqual(cs.pick_archetype_auto("Kadesh 1274 BC"), "scale_event")

    def test_un_id_desconocido_no_se_activa(self):
        self.assertEqual(cs.set_active_archetype("listicle"), "")
        self.assertEqual(cs.build_archetype_prompt_instructions(), "")

    def test_el_prompt_del_angulo_entra_en_las_instrucciones_de_gancho(self):
        cs.set_active_archetype("mechanism")
        instr = cs.build_hook_prompt_instructions()
        self.assertIn("NARRATIVE ANGLE", instr)
        self.assertIn("ANGLE = MECHANISM", instr)
        self.assertIn("Why this angle (measured)", instr)
        cs.set_active_archetype("")
        self.assertNotIn("NARRATIVE ANGLE", cs.build_hook_prompt_instructions())

    def test_cover_words_y_brief_de_thumbnail(self):
        self.assertIn("FOUND", cs.archetype_cover_words("discovery"))
        self.assertIn("no faces", cs.archetype_thumbnail_brief("mechanism"))
        self.assertEqual(cs.archetype_cover_words("nope"), [])


class ElCoverFrameSigueAlAngulo(unittest.TestCase):

    def setUp(self):
        select_channel(DEFAULT_CHANNEL)

    def tearDown(self):
        cs.set_active_archetype("")

    def test_con_angulo_no_sale_una_palabra_de_misterio(self):
        from cover_frame_generator import select_cover_text
        cs.set_active_archetype("")
        for _ in range(20):
            texto = select_cover_text("How did they cut the stones of Puma Punku", "Ancient Civilizations",
                                      storyboard={"format_archetype": "mechanism"})
            self.assertIn(texto, [w.upper() for w in cs.archetype_cover_words("mechanism")])

    def test_sin_angulo_sigue_el_mapa_generico(self):
        from cover_frame_generator import select_cover_text
        cs.set_active_archetype("")
        self.assertEqual(select_cover_text("The siege of Tyre", "War", storyboard={}), "TRAPPED")


class ElStudioLoEligeYLoGuarda(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        select_channel(DEFAULT_CHANNEL)
        cs.set_active_archetype("")

    def test_combo_config_y_restauracion(self):
        from test_studio_channel_controls import StudioStub
        from studio_channel_controls import project_channel_config, restore_channel_config, resolve_archetype_for_topic
        tab = StudioStub()
        datos = [tab.archetype_combo.itemData(i) for i in range(tab.archetype_combo.count())]
        self.assertEqual(datos, ["auto", "mechanism", "discovery", "human_story", "scale_event"])
        self.assertEqual(project_channel_config(tab)["format_archetype"], "auto")
        restore_channel_config(tab, {"channel_profile": DEFAULT_CHANNEL, "format_archetype": "discovery"})
        self.assertEqual(tab.archetype_combo.currentData(), "discovery")
        self.assertEqual(cs.get_active_archetype(), "discovery", "al reabrir, el angulo activo es el del proyecto")
        self.assertEqual(resolve_archetype_for_topic(tab, "cualquier tema"), "discovery")
        self.assertTrue(any("elegido" in e for e in tab.events))
        tab.close()

    def test_auto_resuelve_por_tema(self):
        from test_studio_channel_controls import StudioStub
        from studio_channel_controls import resolve_archetype_for_topic
        tab = StudioStub()
        tab.archetype_combo.setCurrentIndex(0)
        self.assertEqual(resolve_archetype_for_topic(tab, "How did the Romans build the Cloaca Maxima"), "mechanism")
        tab.close()

    def test_el_perfil_viejo_solo_ofrece_auto(self):
        from test_studio_channel_controls import StudioStub
        from studio_channel_controls import set_editorial_channel
        tab = StudioStub()
        set_editorial_channel(tab, "stunning-revelations")
        self.assertEqual(tab.archetype_combo.count(), 1)
        tab.close()


class LlegaAlGenerador(unittest.TestCase):

    def test_el_adaptador_deja_pasar_el_parametro(self):
        from auto_video_generator_pyqt6_adapter import AutoVideoGeneratorPyQt6

        class Fake:
            def generate_storyboard_data(self, **kw):
                return kw
        ad = AutoVideoGeneratorPyQt6.__new__(AutoVideoGeneratorPyQt6)
        ad._generator = Fake()
        out = ad.generate_storyboard(topic="t", category="c", format_archetype="discovery",
                                     opening_style="map_zoom_v1", duration_seconds=60)
        self.assertEqual(out["format_archetype"], "discovery")
        self.assertEqual(out["opening_style"], "map_zoom_v1")
        self.assertEqual(out["custom_duration"], 60)

    def test_el_wrapper_real_acepta_y_reenvia_el_parametro(self):
        """BUG 2026-09-22: el adaptador llama a AutoVideoGenerator.generate_storyboard_data (el
        wrapper), no a StoryboardGenerator; el parametro estaba solo en el segundo y la
        generacion reventaba con TypeError."""
        import inspect
        from auto_video_generator_v2 import AutoVideoGenerator
        self.assertIn("format_archetype", inspect.signature(AutoVideoGenerator.generate_storyboard_data).parameters)
        self.assertIn("opening_style", inspect.signature(AutoVideoGenerator.generate_storyboard_data).parameters)

        class FakeSB:
            def generate_storyboard_data(self, *a, **kw):
                return kw
        gen = AutoVideoGenerator.__new__(AutoVideoGenerator)
        gen.storyboard_generator = FakeSB()
        gen.log = lambda m: None
        out = gen.generate_storyboard_data(
            "t", "c", format_archetype="human_story", opening_style="artifact_reveal_v1"
        )
        self.assertEqual(out["format_archetype"], "human_story")
        self.assertEqual(out["opening_style"], "artifact_reveal_v1")

    def test_el_handler_lo_pasa_y_el_generador_lo_estampa(self):
        fuente = io.open("studio_storyboard_handlers.py", encoding="utf-8", errors="replace").read()
        self.assertIn("format_archetype=format_archetype", fuente)
        gen = io.open("storyboard_generator.py", encoding="utf-8", errors="replace").read()
        self.assertIn('format_archetype: str = ""', gen)
        self.assertEqual(gen.count('structured_result["format_archetype"] = _arche'), 2)

    def test_el_microdoc_y_el_super_prompt_lo_reciben(self):
        micro = io.open("micro_documentary.py", encoding="utf-8", errors="replace").read()
        self.assertIn("format_archetype=format_archetype", micro)
        self.assertIn("{angle_block}", micro)
        cc = io.open("claude_client.py", encoding="utf-8", errors="replace").read()
        self.assertIn("render_text=True, format_archetype=None", cc)
        self.assertIn("Narrative angle:", cc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
