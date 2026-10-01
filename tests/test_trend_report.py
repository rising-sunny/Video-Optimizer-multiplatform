# -*- coding: utf-8 -*-
"""Guardas del boton Tendencias: efemerides, filtros, patrones, propuestas y el dialogo.

    .venv\\Scripts\\python.exe test_trend_report.py
"""

import datetime
import io
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from channel import trend_report as tr


class Efemerides(unittest.TestCase):

    EVENTS = [
        {"date": "09-25", "year": 1066, "title": "Stamford Bridge", "angle": "scale_event"},
        {"date": "10-30", "year": 1961, "title": "Tsar Bomba", "angle": "mechanism"},
        {"date": "01-10", "year": -49, "title": "Rubicon", "angle": "scale_event"},
        {"date": "02-30", "year": 1, "title": "fecha imposible"},
        {"date": "mal", "title": "roto"},
    ]

    def test_ventana_y_dias_que_faltan(self):
        hoy = datetime.date(2026, 9, 21)
        out = tr.upcoming_anniversaries(self.EVENTS, today=hoy, days_ahead=45)
        self.assertEqual([e["title"] for e in out], ["Stamford Bridge", "Tsar Bomba"])
        self.assertEqual(out[0]["days_left"], 4)
        self.assertEqual(out[0]["anniversary"], 960)
        self.assertEqual(out[0]["when"], "2026-09-25")

    def test_cruza_el_ano(self):
        hoy = datetime.date(2026, 12, 20)
        out = tr.upcoming_anniversaries(self.EVENTS, today=hoy, days_ahead=45)
        self.assertEqual([e["title"] for e in out], ["Rubicon"])
        self.assertEqual(out[0]["when"], "2027-01-10")
        self.assertNotIn("anniversary", out[0], "un ano negativo (a.C.) no se cuenta como aniversario")

    def test_hoy_mismo_cuenta(self):
        out = tr.upcoming_anniversaries(self.EVENTS, today=datetime.date(2026, 10, 30), days_ahead=0)
        self.assertEqual(out[0]["title"], "Tsar Bomba")
        self.assertEqual(out[0]["days_left"], 0)

    def test_el_archivo_real_carga_y_tiene_angulos_validos(self):
        events = tr.load_anniversaries()
        self.assertGreaterEqual(len(events), 25)
        from channel.channel_strategy import get_format_archetypes
        ids = {a["id"] for a in get_format_archetypes()}
        for e in events:
            self.assertIn(e.get("angle"), ids, e["title"])
            self.assertTrue(e.get("hook"), e["title"])


class Filtros(unittest.TestCase):

    def test_ingles_y_ruido(self):
        self.assertTrue(tr.is_niche("How Did Romans Measure Distance?"))
        self.assertFalse(tr.is_niche("फौजी ने खोला पहाड़ का बंद रास्ता"))
        self.assertFalse(tr.is_niche("RUSSIA VS USA countryballs"))
        self.assertFalse(tr.is_niche("The spiciest Mexican-style potato chips in history"))

    def test_historico(self):
        self.assertTrue(tr.looks_historical("The Odyssey (2026 film)"))
        self.assertTrue(tr.looks_historical("Why Did the Roman Empire divide in two?"))
        self.assertFalse(tr.looks_historical("Ed Sheeran"))

    def test_bandas(self):
        self.assertEqual(tr.duration_band(8), "<=15s")
        self.assertEqual(tr.duration_band(180), ">120s")


class PatronesYPropuestas(unittest.TestCase):

    ROWS = [
        {"title": "How Did Romans Measure Distance?", "views": 1_500_000, "duration": 68, "channel": "LHS"},
        {"title": "Teenager Discovers Lost Ancient City?", "views": 4_850_000, "duration": 62, "channel": "TM"},
        {"title": "The U-Boat That Escaped to Argentina", "views": 5_200_000, "duration": 180, "channel": "J"},
        {"title": "Cloaca Maxima: Roman Sewer Engineering", "views": 330_000, "duration": 66, "channel": "LHS"},
    ]

    def test_patrones(self):
        pat = tr.summarize_patterns(self.ROWS)
        self.assertEqual(pat["sample_size"], 4)
        self.assertIn("mechanism", pat["by_archetype"])
        self.assertEqual(pat["by_archetype"]["mechanism"]["n"], 2)
        self.assertEqual(pat["repeat_channels"], ["LHS"])
        self.assertEqual(list(pat["by_archetype"])[0], "human_story", "ordenado por vistas")

    def test_heuristicas_traen_efemerides_con_gancho_y_wikipedia(self):
        ann = [{"title": "Hastings", "angle": "mechanism", "when": "2026-10-14", "days_left": 23, "hook": "Why did the shield wall break?", "anniversary": 960, "category": "War & Military History"}]
        out = tr.heuristic_proposals(ann, ["The Odyssey (2026 film)"], {})
        self.assertEqual(out[0]["topic"], "Hastings")
        self.assertEqual(out[0]["archetype"], "mechanism")
        self.assertIn("960", out[0]["why"])
        self.assertEqual(out[1]["source"], "wikipedia")

    def test_merge_sin_duplicados_y_con_orden(self):
        a = [{"topic": "Roman concrete"}, {"topic": "Hastings"}]
        b = [{"topic": "roman CONCRETE!"}, {"topic": "Sputnik"}]
        out = tr.merge_proposals(a, b)
        self.assertEqual([p["topic"] for p in out], ["Roman concrete", "Hastings", "Sputnik"])

    def test_llm_sin_cliente_devuelve_vacio(self):
        class Sin:
            client = None
        self.assertEqual(tr.llm_proposals(self.ROWS, {}, [], client=Sin()), [])

    def test_llm_limpia_prefijos_de_angulo_y_valida_ids(self):
        class Fake:
            client = object()

            def _generate(self, prompt, **kw):
                return ('{"proposals": [{"topic": "Mechanism of the Roman concrete", "archetype": "mechanism", "category": "x", "hook": "h", "why": "w"},'
                        ' {"topic": "Human story of the U-boat crew", "archetype": "invented", "category": "", "hook": "", "why": ""}, {"topic": ""}]}')
        out = tr.llm_proposals(self.ROWS, {}, [], client=Fake())
        self.assertEqual([p["topic"] for p in out], ["the Roman concrete", "the U-boat crew"])
        self.assertEqual(out[1]["archetype"], "scale_event")

    def test_formato_legible(self):
        rep = {"generated_at": "x", "window_days": 30, "patterns": tr.summarize_patterns(self.ROWS),
               "wikipedia": ["The Odyssey (2026 film)"], "anniversaries": [], "proposals": [{"topic": "T", "archetype": "mechanism", "why": "w"}]}
        texto = tr.format_report(rep)
        self.assertIn("TEMAS PROPUESTOS", texto)
        self.assertIn("[mechanism] T", texto)


class ElDialogoCargaElTema(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_usar_tema_llena_tema_categoria_y_angulo(self):
        from PyQt6.QtWidgets import QWidget, QComboBox, QLineEdit
        from tests.test_studio_channel_controls import StudioStub
        from studio_channel_controls import TrendsDialog
        tab = StudioStub()
        parent = QWidget(); parent.category_combo = QComboBox(); parent.category_combo.addItems(["Ancient Civilizations & Empires", "War & Military History"])
        tab.parent_gui = parent
        tab.topic_input = QLineEdit()
        report = {"generated_at": "hoy", "patterns": {}, "proposals": [
            {"topic": "Battle of Hastings", "archetype": "mechanism", "category": "War & Military History", "date": "2026-10-14", "why": "efemeride", "hook": "Why did the shield wall break?"}]}
        dlg = TrendsDialog(tab, report, parent=tab)
        dlg.table.selectRow(0)
        dlg.use_selected()
        self.assertEqual(tab.topic_input.text(), "Battle of Hastings")
        self.assertEqual(parent.category_combo.currentText(), "War & Military History")
        self.assertEqual(tab.archetype_combo.currentData(), "mechanism")
        self.assertTrue(any("Why did the shield wall" in e for e in tab.events))
        dlg.close(); parent.close(); tab.close()

    def test_el_boton_existe(self):
        fuente = io.open("studio_channel_controls.py", encoding="utf-8", errors="replace").read()
        self.assertIn("tab.btn_trends = QPushButton('Tendencias')", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
