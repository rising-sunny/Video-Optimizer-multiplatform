# -*- coding: utf-8 -*-
"""Guardas: lo publicado queda registrado en el project.json (ids por red).

2026-09-21: el Studio publicaba desde un staging temporal que se borraba; el id
de YouTube/Facebook no quedaba en ningun lado y performance_feedback.py solo
podia cruzar metricas con proyectos por parecido de titulo (9 de 25).

    .venv\\Scripts\\python.exe test_publish_record.py
"""

import datetime
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from publish.publish_record import merge_publish_results, summarize_result


class ResumenPorRed(unittest.TestCase):

    def test_youtube_guarda_video_id_y_url(self):
        e = summarize_result("youtube", {"video_id": "t2RdyatshZM", "url": "https://youtube.com/shorts/t2RdyatshZM", "privacy_status": "public"})
        self.assertEqual(e["video_id"], "t2RdyatshZM")
        self.assertEqual(e["privacy_status"], "public")

    def test_facebook_e_instagram_guardan_id(self):
        self.assertEqual(summarize_result("facebook", {"id": "924234763701033", "url": "https://www.facebook.com/reel/924234763701033"})["id"], "924234763701033")
        self.assertEqual(summarize_result("instagram", {"media_id": "m1", "permalink_url": "https://www.instagram.com/reel/x/", "transport": "resumable"})["transport"], "resumable")

    def test_un_fallo_no_es_un_resultado(self):
        self.assertIsNone(summarize_result("instagram", None))
        self.assertIsNone(summarize_result("x", {"error": "402"}))


class MezclaEnElProyecto(unittest.TestCase):

    def test_suma_sin_pisar_lo_anterior(self):
        ayer = {"publish_results": {"youtube": {"video_id": "abc", "published_at": "2026-09-20 10:00"}}}
        hoy = merge_publish_results(ayer, {"youtube": None, "instagram": {"media_id": "m9", "url": "u"}},
                                    now=datetime.datetime(2026, 9, 21, 12, 0))
        self.assertEqual(hoy["publish_results"]["youtube"]["video_id"], "abc", "un reintento fallido no borra lo publicado")
        self.assertEqual(hoy["publish_results"]["instagram"]["id"], "m9")
        self.assertEqual(hoy["publish_results"]["instagram"]["published_at"], "2026-09-21 12:00")

    def test_no_muta_la_entrada(self):
        original = {"config": {"topic": "x"}}
        merge_publish_results(original, {"youtube": {"video_id": "v"}})
        self.assertNotIn("publish_results", original)

    def test_resultados_vacios_dejan_el_dict_valido(self):
        self.assertEqual(merge_publish_results({}, {})["publish_results"], {})


class ElProjectManagerLoEscribe(unittest.TestCase):

    def test_registra_en_memoria_y_en_disco(self):
        from studio.studio_project_manager import StudioProjectManager

        with tempfile.TemporaryDirectory(suffix=".json") as tmp:
            path = os.path.join(tmp, "project.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"config": {"topic": "Halifax"}, "storyboard": {"segments": []}}, fh)
            tab = SimpleNamespace(current_project_path=path, log=lambda m: None)
            pm = StudioProjectManager.__new__(StudioProjectManager)
            pm.studio_tab = tab
            ok = pm.record_publish_results({"youtube": {"video_id": "t2R", "url": "https://youtube.com/shorts/t2R"}, "facebook": None})
            self.assertTrue(ok)
            self.assertEqual(tab.publish_results["youtube"]["video_id"], "t2R")
            saved = json.load(open(path, encoding="utf-8"))
            self.assertEqual(saved["publish_results"]["youtube"]["video_id"], "t2R")
            self.assertEqual(saved["config"]["topic"], "Halifax", "no pisa el resto del proyecto")

    def test_sin_proyecto_en_disco_queda_solo_en_memoria(self):
        from studio.studio_project_manager import StudioProjectManager

        tab = SimpleNamespace(current_project_path=None)
        pm = StudioProjectManager.__new__(StudioProjectManager)
        pm.studio_tab = tab
        self.assertFalse(pm.record_publish_results({"x": {"tweet_id": "1"}}))
        self.assertEqual(tab.publish_results["x"]["id"], "1")

    def test_la_gui_llama_al_registro_al_terminar(self):
        import io
        fuente = io.open("studio/auto_video_integration_pyqt6.py", encoding="utf-8", errors="replace").read()
        bloque = fuente[fuente.index("def _on_publish_done("):][:900]
        self.assertIn("record_publish_results(results)", bloque)

    def test_el_guardado_normal_conserva_publish_results(self):
        import io
        fuente = "\n".join(io.open(r, encoding="utf-8", errors="replace").read() for r in (
            "studio/studio_project_manager.py",
            "studio/project_save_mixin.py",
            "studio/project_load_mixin.py",
        ))
        self.assertGreaterEqual(fuente.count("project_data['publish_results'] = dict(self.studio_tab.publish_results)"), 2)
        self.assertIn("self.studio_tab.publish_results = dict(project_data.get('publish_results') or {})", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
