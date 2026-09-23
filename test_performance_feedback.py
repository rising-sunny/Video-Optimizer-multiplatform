# -*- coding: utf-8 -*-
"""Guardas del bucle de datos: clasificar, cruzar, agregar y recomendar sin red.

Los casos son los videos reales del canal al 2026-09-21, con sus numeros, para
que el snapshot reproduzca las conclusiones de ese dia (y avise si dejan de
cumplirse cuando cambie la logica).

    .venv\\Scripts\\python.exe test_performance_feedback.py
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import performance_feedback as pf


def yt(video_id, title, views, engaged, subs, dur=70, vertical=True, avg_pct=70.0):
    return {"video_id": video_id, "title": title, "views": views, "engaged_views": engaged, "subs": subs,
            "duration": dur, "is_vertical": vertical, "avg_view_pct": avg_pct, "published": "2026-09-10"}


# Los shorts reales del canal (YouTube Analytics, 30 dias al 2026-09-21).
YT_REAL = [
    yt("-qgTZ_QJ2bk", "7,000 People in Çatalhöyük: Urban Giant", 1320, 912, 8),
    yt("V0eyf-tbdaE", "Japan's WWII Suicide Submarines: The Kaiten", 1249, 332, 0, dur=125),
    yt("9W9IlhKFQ1w", "Alexander Conquers Tyre in 7 Months", 1025, 663, 5, dur=139),
    yt("WxFfc6NV4jM", "They almost set the atmosphere on fire", 964, 591, 3, dur=80),
    yt("mYOI2VdfSBs", "92 Islets, 50-Ton Basalt: Nan Madol's Ocean City", 840, 511, 4),
    yt("-6sXfAO6f40", "Kushite King Piye: 20,000 Troops Storm Egypt!", 674, 403, 7, avg_pct=96.9),
    yt("t2RdyatshZM", "Halifax Explosion: 2.9 kt Blast Shattered a City", 227, 155, 1),
    yt("2Cqt_5YWtnM", "Beirut 2020 Explosion: 1.1 kt TNT Shockwave", 19, 10, 0),
    yt("jvrAuwCn8AE", "The Explosion That Flattened Siberia", 7, 3, 0),
    yt("nF3Vr7RUwfU", "The Strongest Earthquake Ever Recorded Hit Here", 46, 22, 0, dur=50),
    yt("f4qFcoNAkhI", "The mystery invaders who ended the Bronze Age", 9, 4, 0, dur=108),
    yt("0W3Y90wB1gQ", "The Eruption That Shook the Ancient World | Thera, 1600 BC", 49, 30, 0, dur=130, vertical=False),
    yt("RwQXlH3Cndo", "The Night the Nazis Lost Heavy Water", 17, 8, 0, dur=224, vertical=False),
    yt("LbsR1InHtNw", "The CIA's Secret Mission to Steal a Soviet Nuclear Submarine", 27, 12, 0, dur=260, vertical=False),
]

FB_REAL = [
    {"reel_id": "1", "title": "Around 1600 BC, one of the most powerful volcanic eruptions", "plays": 52265, "avg_watch_s": 33.3,
     "followers": 192, "duration": 130, "is_vertical": False, "retention_25": 37.0},
    {"reel_id": "2", "title": "They calculated six megatons. They got fifteen.", "plays": 462, "avg_watch_s": 11.8,
     "followers": 1, "duration": 52, "is_vertical": True, "retention_25": 50.0},
    {"reel_id": "3", "title": "In a frozen night, a handful of Norwegian saboteurs", "plays": 211, "avg_watch_s": 6.1,
     "followers": 0, "duration": 224, "is_vertical": False, "retention_25": 3.0},
    {"reel_id": "4", "title": "On December 6, 1917, a 2.9-kiloton blast shattered Halifax", "plays": 603, "avg_watch_s": 8.8,
     "followers": 3, "duration": 69, "is_vertical": True, "retention_25": 32.0},
]


class ClasificarPorTitulo(unittest.TestCase):

    def test_los_cuatro_angulos(self):
        self.assertEqual(pf.classify_archetype("How Did Romans Measure Distance?"), "mechanism")
        self.assertEqual(pf.classify_archetype("Why WW2 Grenades Had Grooves! The Real Reason"), "mechanism")
        self.assertEqual(pf.classify_archetype("Teenager Discovers Lost Ancient City?"), "discovery")
        self.assertEqual(pf.classify_archetype("Why Was an Iron Sickle Placed Around Her Neck?"), "mechanism")
        self.assertEqual(pf.classify_archetype("He Fell 18,000 Feet Without a Parachute - And Lived"), "human_story")
        self.assertEqual(pf.classify_archetype("The U-Boat That Escaped to Argentina"), "human_story")
        self.assertEqual(pf.classify_archetype("7,000 People in Çatalhöyük: Urban Giant"), "scale_event")
        self.assertEqual(pf.classify_archetype("Alexander Conquers Tyre in 7 Months"), "scale_event")

    def test_hallazgo_manda_sobre_cifra(self):
        self.assertEqual(pf.classify_archetype("This 5,000-Year-Old Dress Was Mistaken for Rags: archaeologists found it"), "discovery")

    def test_vacio_es_unknown(self):
        self.assertEqual(pf.classify_archetype(""), "unknown")
        self.assertEqual(pf.classify_archetype(None), "unknown")

    def test_etiquetas_de_riesgo(self):
        self.assertIn("modern_disaster", pf.tag_risks("Beirut 2020 Explosion: 1.1 kt TNT Shockwave"))
        self.assertIn("modern_disaster", pf.tag_risks("Halifax Explosion: 2.9 kt Blast Shattered a City"))
        self.assertIn("mystery_framing", pf.tag_risks("The mystery invaders who ended the Bronze Age"))
        # Una erupcion antigua no es "desastre moderno": sin ano >= 1850 no se etiqueta.
        self.assertEqual(pf.tag_risks("The Eruption That Shook the Ancient World | Thera, 1600 BC"), [])
        self.assertEqual(pf.tag_risks("7,000 People in Çatalhöyük"), [])

    def test_buckets_de_duracion(self):
        self.assertEqual(pf.duration_bucket(38), "<=45s")
        self.assertEqual(pf.duration_bucket(70), "46-70s")
        self.assertEqual(pf.duration_bucket(80), "71-95s")
        self.assertEqual(pf.duration_bucket(139), "96-180s")
        self.assertEqual(pf.duration_bucket(260), ">180s")
        self.assertEqual(pf.duration_bucket(0), "unknown")


class CruzarConProyectos(unittest.TestCase):

    def _projects(self):
        return [
            {"folder": "Catalhoyuk_2026", "topic": "Çatalhöyük", "category": "Ancient Civilizations & Empires",
             "format_archetype": "", "youtube_video_id": ""},
            {"folder": "Halifax_2026", "topic": "La explosión de Halifax, 1917", "category": "Historical Disasters",
             "format_archetype": "scale_event", "youtube_video_id": "t2RdyatshZM"},
            {"folder": "Nuevo", "topic": "Roman concrete", "category": "Science & Technology in History",
             "format_archetype": "mechanism", "youtube_video_id": ""},
        ]

    def test_por_id_publicado_primero(self):
        p = pf.match_project("cualquier titulo", self._projects(), video_id="t2RdyatshZM")
        self.assertEqual(p["folder"], "Halifax_2026")

    def test_por_parecido_de_tema_y_titulo(self):
        p = pf.match_project("7,000 People in Çatalhöyük: Urban Giant", self._projects())
        self.assertEqual(p["folder"], "Catalhoyuk_2026")
        p = pf.match_project("Why Roman concrete gets stronger underwater", self._projects())
        self.assertEqual(p["folder"], "Nuevo")

    def test_sin_parecido_no_inventa(self):
        self.assertIsNone(pf.match_project("The Week Jupiter Was Bombarded", self._projects()))

    def test_el_angulo_del_proyecto_manda_sobre_el_titulo(self):
        rows = pf.enrich_rows([yt("t2RdyatshZM", "Halifax Explosion: 2.9 kt Blast", 227, 155, 1)], self._projects(), "youtube")
        self.assertEqual(rows[0]["archetype"], "scale_event")
        self.assertEqual(rows[0]["category"], "Historical Disasters")
        self.assertEqual(rows[0]["project"], "Halifax_2026")

    def test_load_projects_lee_config_y_publish_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "P1.json").mkdir()
            (root / "P1.json" / "project.json").write_text(json.dumps({
                "config": {"topic": "Tema uno", "category": "Cat", "format_archetype": "discovery"},
                "publish_results": {"youtube": {"video_id": "abc"}, "facebook": {"id": "999"}}}), encoding="utf-8")
            (root / "sin_json").mkdir()
            ps = pf.load_projects([root])
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["youtube_video_id"], "abc")
        self.assertEqual(ps[0]["facebook_reel_id"], "999")
        self.assertEqual(ps[0]["format_archetype"], "discovery")


class ElSnapshotReproduceLasConclusionesDel21(unittest.TestCase):

    def setUp(self):
        self.snap = pf.build_snapshot(YT_REAL, FB_REAL, [], days=30,
                                      yt_channel={"title": "SFOH", "viewCount": 9095, "subscriberCount": 29})

    def test_despegue_es_binario(self):
        vids = {v["video_id"]: v for v in self.snap["youtube"]["videos"]}
        self.assertTrue(vids["-qgTZ_QJ2bk"]["took_off"])
        self.assertTrue(vids["jvrAuwCn8AE"]["dead"])
        self.assertFalse(vids["t2RdyatshZM"]["took_off"])
        self.assertAlmostEqual(vids["V0eyf-tbdaE"]["engaged_pct"], 26.6, places=0)

    def test_los_desastres_modernos_van_a_evitar(self):
        avoid = {a["what"] for a in self.snap["recommendations"]["avoid"]}
        self.assertIn("modern_disaster", avoid)
        self.assertIn("youtube_16_9_only", avoid)

    def test_facebook_thera_aparece_como_nota(self):
        notes = " ".join(self.snap["recommendations"]["notes"])
        self.assertIn("52265", notes)
        self.assertIn("16:9", notes)

    def test_pesos_en_rango(self):
        for w in self.snap["weights"]["archetypes"].values():
            self.assertGreaterEqual(w, 0.4)
            self.assertLessEqual(w, 2.0)

    def test_riesgo_none_no_aparece_como_recomendacion(self):
        self.assertNotIn("none", {a["what"] for a in self.snap["recommendations"]["avoid"]})

    def test_escribe_y_lee_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pf.write_snapshot(self.snap, Path(tmp) / "x" / "snap.json")
            self.assertEqual(pf.load_snapshot(p)["window_days"], 30)
        self.assertEqual(pf.load_snapshot(Path(tmp) / "no_existe.json"), {})

    def test_resumen_legible(self):
        texto = pf.format_summary(self.snap)
        self.assertIn("EVITAR", texto)
        self.assertIn("SFOH", texto)


class ScoresYPesos(unittest.TestCase):

    def test_score_ignora_grupos_de_un_solo_video(self):
        by = {"mechanism": {"n": 1, "takeoff_rate": 1.0, "median_engaged_pct": 90, "subs_per_1k": 20},
              "scale_event": {"n": 5, "takeoff_rate": 0.6, "median_engaged_pct": 60, "subs_per_1k": 5}}
        s = pf.score_archetypes(by)
        self.assertNotIn("mechanism", s)
        self.assertAlmostEqual(s["scale_event"], 0.5 * 0.6 + 0.3 * 0.6 + 0.2 * 0.5, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
