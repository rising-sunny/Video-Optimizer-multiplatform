# -*- coding: utf-8 -*-
"""Guardas: un hipo del LLM no puede dejar el video sin miniatura.

BUG (2026-09-02): con el proyecto Nan Madol la GUI corto con
"Groq no devolvio un enrichment utilizable para miniaturas hook.". El enricher
funciona nueve de cada diez veces -- Groq (openai/gpt-oss-20b) es no
determinista -- pero CUALQUIER hipo era fatal:

  - JSON ilegible                       -> return None, sin reintento ni log
  - `suggested_niche_profile` fuera de
    la lista blanca                     -> se tiraba el brief ENTERO por un enum
  - estrategia sin alguno de 5 campos   -> RuntimeError

y `_fallback_synthesis`, que estaba escrito para exactamente esto, no se
llamaba desde ningun lado.

    .venv\\Scripts\\python.exe test_thumbnail_resilience.py
"""

import unittest

from thumbnail_context_enricher import ThumbnailContextEnricher
from thumbnail_intelligence import ThumbnailIntelligence
from thumbnail_formats import SHORT_9_16

PROYECTO = {
    "config": {"platform_key": "youtube_short", "video_format": "9:16",
               "topic": "Nan Madol", "category": "Ancient Civilizations",
               "language": "en", "duration": 68},
    "storyboard": {"segments": [
        {"text": "In 1180 AD the Saudeleur dynasty began building Nan Madol.",
         "visual_prompt": "basalt canal at dawn"},
        {"text": "Workers hauled basalt blocks up to 50 tons.",
         "visual_prompt": "laborers dragging stone"},
    ]},
}


class LlmFalso:
    """Cliente de LLM que responde lo que le digan (o falla)."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = 0

    def _generate(self, prompt, **kw):
        self.llamadas += 1
        r = self.respuestas[min(self.llamadas - 1, len(self.respuestas) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


BRIEF_OK = """{
 "suggested_niche_profile": "historical_revelation",
 "web_summary": "Nan Madol, 92 islets of stacked basalt.",
 "hero_subject": "massive basalt block being lifted",
 "hero_frame": "tight close-up",
 "selected_scene_prompt": "basalt canal at dawn",
 "visual_motifs": ["wet basalt", "torchlight"],
 "reference_queries": ["Nan Madol ruins"],
 "trend_hooks": ["50 TONS", "92 ISLETS", "NO CRANES"],
 "wow_directives": ["scale against a human figure"],
 "negative_constraints": ["modern clothing"],
 "quality_tier": "epic_cinematic"
}"""


class EnricherAguanta(unittest.TestCase):

    def _enriquecer(self, respuestas):
        cli = LlmFalso(respuestas)
        enr = ThumbnailContextEnricher(llm_client=cli, log_callback=lambda m: None)
        return enr.enrich_context(PROYECTO, thumbnail_format=SHORT_9_16), cli

    def test_camino_feliz(self):
        res, cli = self._enriquecer([BRIEF_OK])
        self.assertEqual(res["suggested_niche_profile"], "historical_revelation")
        self.assertEqual(cli.llamadas, 1)

    def test_json_ilegible_reintenta_una_vez(self):
        # Primer intento basura, segundo bueno: tiene que salir adelante.
        res, cli = self._enriquecer(["lo siento, no puedo", BRIEF_OK])
        self.assertEqual(cli.llamadas, 2, "no reintento")
        self.assertEqual(res["suggested_niche_profile"], "historical_revelation")

    def test_json_ilegible_dos_veces_no_revienta(self):
        # Este es el caso que corto la generacion en la GUI.
        res, _ = self._enriquecer(["basura", "mas basura"])
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("hero_subject"), "el brief de respaldo vino vacio")

    def test_un_enum_raro_no_tira_el_brief_entero(self):
        raro = BRIEF_OK.replace("historical_revelation", "ancient_engineering")
        res, _ = self._enriquecer([raro])
        # El perfil se reemplaza, pero lo demas del brief SOBREVIVE.
        self.assertEqual(res["hero_subject"], "massive basalt block being lifted")
        self.assertIn("wet basalt", res["visual_motifs"])
        self.assertTrue(res["suggested_niche_profile"])

    def test_el_llm_explotando_tampoco_revienta(self):
        res, _ = self._enriquecer([RuntimeError("429 rate limit")])
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("hero_subject"))


class EstrategiaAguanta(unittest.TestCase):

    ESTRATEGIA_OK = """{
     "selected_hook": "50 TONS",
     "hook_candidates": ["50 TONS", "92 ISLETS", "NO CRANES"],
     "palette": "orange_cyan",
     "render_mode": "realistic_image",
     "quality_tier": "epic_cinematic",
     "hero_subject": "basalt block",
     "selected_scene_prompt": "basalt canal at dawn",
     "base_prompt": "Nan Madol basalt canal at dawn",
     "impact_subject": "basalt block",
     "variant_recipes": [
      {"id": "a", "label": "A", "composition": "subject_left_text_right", "prompt_suffix": "x"},
      {"id": "b", "label": "B", "composition": "subject_right_text_left", "prompt_suffix": "y"},
      {"id": "c", "label": "C", "composition": "text_top_center", "prompt_suffix": "z"}
     ]
    }"""

    def _estrategia(self, respuestas):
        cli = LlmFalso(respuestas)
        intel = ThumbnailIntelligence(llm_client=cli, log_callback=lambda m: None)
        return intel.generate_strategy(PROYECTO, thumbnail_format=SHORT_9_16)

    def test_camino_feliz(self):
        est = self._estrategia([self.ESTRATEGIA_OK])
        self.assertTrue(est.get("base_prompt"))
        self.assertGreaterEqual(len(est.get("variant_recipes") or []), 1)

    def test_estrategia_incompleta_cae_al_respaldo(self):
        # Faltan hero_subject/base_prompt: antes era RuntimeError y adios miniatura.
        est = self._estrategia(['{"selected_hook": "50 TONS"}'])
        self.assertIsInstance(est, dict)
        self.assertTrue(est.get("base_prompt"), "el respaldo no trajo base_prompt")
        self.assertTrue(est.get("variant_recipes"), "el respaldo no trajo recetas")

    def test_sin_respuesta_del_llm_cae_al_respaldo(self):
        est = self._estrategia(["no soy un json"])
        self.assertIsInstance(est, dict)
        self.assertTrue(est.get("base_prompt"))

    def test_el_respaldo_sigue_dando_recetas_usables(self):
        est = self._estrategia([RuntimeError("500 server error")])
        for receta in est.get("variant_recipes") or []:
            self.assertIn("composition", receta)
            self.assertIn(SHORT_9_16.resolve_composition(receta["composition"]),
                          SHORT_9_16.text_boxes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
