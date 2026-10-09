# -*- coding: utf-8 -*-
"""Guardas del Director IA (pipeline/ai_director): composicion por escena con LLM."""

import json
import os
import unittest
from unittest import mock

from pipeline import ai_director
from pipeline import segment_layouts as sl


def _storyboard(texts, dur=4.0, **extra):
    return {"segments": [
        dict({"start": i * dur, "end": (i + 1) * dur, "text": t, "narration_text": t}, **extra)
        for i, t in enumerate(texts)
    ]}


class FakeClient:
    def __init__(self, plan=None, raw=None):
        self._plan = plan or {}
        self._raw = raw
        self.prompt = None

    def _generate(self, prompt, **kwargs):
        self.prompt = prompt
        if self._raw is not None:
            return self._raw
        return json.dumps(self._plan)


TEXTS = [
    "Two shots changed history.",                 # 0 entrada
    "Archduke Franz Ferdinand arrived.",          # persona -> pip
    "The city cheered, while assassins waited.",  # comparacion -> split
    "Three conspirators stood by the river.",     # enumeracion -> triptych
    "A bomb exploded under the next car.",        # accion -> punch_in
    "A wrong turn brought the car to the killer.",  # climax -> punch_in
    "Within weeks, Europe was at war.",           # cierre
]


class TestAiDirector(unittest.TestCase):
    def test_ai_decides_layouts_with_boundaries_forced_full(self):
        client = FakeClient(plan={"scenes": [
            {"scene": 1, "layout": "split"},
            {"scene": 2, "layout": "reveal"},
            {"scene": 3, "layout": "split"},
            {"scene": 4, "layout": "triptych"},
            {"scene": 5, "layout": "punch_in"},
            {"scene": 6, "layout": "punch_in"},
            {"scene": 7, "layout": "split"},
        ]})
        sb = _storyboard(TEXTS)
        summary = ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        layouts = [s["layout_plan"]["layout"] for s in sb["segments"]]
        # Primera y ultima siempre a pantalla completa.
        self.assertEqual(layouts[0], "full")
        self.assertEqual(layouts[-1], "full")
        # El resto toma lo que dijo la IA (respetando el presupuesto).
        self.assertEqual(layouts[1], "reveal")
        self.assertEqual(layouts[2], "split")
        self.assertEqual(summary["level"], "ai")
        self.assertEqual(summary["director"], "ai")
        self.assertIn("escenas", client.prompt or "")
        self.assertIn("director cinematografico", client.prompt)

    def test_budget_caps_non_full_layouts(self):
        # La IA pide composicion para TODAS las escenas; el presupuesto la recorta.
        client = FakeClient(plan={"scenes": [
            {"scene": i, "layout": "split"} for i in range(1, len(TEXTS) + 1)
        ]})
        sb = _storyboard(TEXTS)
        ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        non_full = [s["layout_plan"]["layout"] for s in sb["segments"]
                    if s["layout_plan"]["layout"] != "full"]
        eligible = len(TEXTS) - 2
        allowed = int(round(eligible * sl.DYNAMISM_SPECS["ai"]["budget"]))
        self.assertLessEqual(len(non_full), allowed)

    def test_no_consecutive_repeat(self):
        client = FakeClient(plan={"scenes": [
            {"scene": 1, "layout": "split"},
            {"scene": 2, "layout": "split"},
            {"scene": 3, "layout": "split"},
        ]})
        sb = _storyboard(TEXTS[:4])
        ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        layouts = [s["layout_plan"]["layout"] for s in sb["segments"]]
        for a, b in zip(layouts, layouts[1:]):
            if a != "full":
                self.assertNotEqual(a, b)

    def test_locked_segments_are_kept(self):
        sb = _storyboard(TEXTS)
        sb["segments"][2]["layout_plan"] = {"layout": "pip", "locked": True, "version": sl.LAYOUT_VERSION}
        client = FakeClient(plan={"scenes": [
            {"scene": i, "layout": "split"} for i in range(1, len(TEXTS) + 1)
        ]})
        ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        self.assertEqual(sb["segments"][2]["layout_plan"]["layout"], "pip")
        self.assertTrue(sb["segments"][2]["layout_plan"]["locked"])

    def test_falls_back_to_rules_without_client_or_key(self):
        sb = _storyboard(TEXTS)
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            summary = ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None)
        # Sin IA: las reglas escriben igual los layout_plan y el resumen no dice 'director: ai'.
        self.assertNotIn("director", summary)
        for seg in sb["segments"]:
            self.assertIn("layout_plan", seg)

    def test_falls_back_on_bad_json(self):
        client = FakeClient(raw="esto no es json")
        sb = _storyboard(TEXTS)
        summary = ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        self.assertNotIn("director", summary)   # cayo a las reglas
        for seg in sb["segments"]:
            self.assertIn("layout_plan", seg)

    def test_plan_with_unknown_layouts_is_filtered(self):
        client = FakeClient(plan={"scenes": [
            {"scene": 2, "layout": "no_existe"},
            {"scene": 3, "layout": "reveal"},
        ]})
        sb = _storyboard(TEXTS)
        ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        # 'no_existe' se descarta: la escena 2 queda a full, la 3 toma reveal.
        self.assertEqual(sb["segments"][1]["layout_plan"]["layout"], "full")
        self.assertEqual(sb["segments"][2]["layout_plan"]["layout"], "reveal")

    def test_pip_is_not_offered_to_the_ai(self):
        # 2026-10: el retrato flotante (rostro en circulo) se retiro del Director IA.
        self.assertNotIn("pip", ai_director.AI_LAYOUTS)
        self.assertNotIn("retrato flotante", ai_director._PROMPT)

    def test_blender_shots_are_capped_and_get_an_environment(self):
        client = FakeClient(plan={"scenes": [
            {"scene": i, "layout": "blender_3d"} for i in range(1, len(TEXTS) + 1)
        ]})
        sb = _storyboard(TEXTS)
        ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client,
                                           blender_shots=1)
        layouts = [s["layout_plan"]["layout"] for s in sb["segments"]]
        self.assertEqual(layouts.count("blender_3d"), 1)
        for seg in sb["segments"]:
            if seg["layout_plan"]["layout"] == "blender_3d":
                self.assertIn("environment", seg["layout_plan"])

    def test_no_blender_when_blender_shots_is_zero(self):
        client = FakeClient(plan={"scenes": [
            {"scene": i, "layout": "blender_3d"} for i in range(1, len(TEXTS) + 1)
        ]})
        sb = _storyboard(TEXTS)
        ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client,
                                           blender_shots=0)
        layouts = [s["layout_plan"]["layout"] for s in sb["segments"]]
        self.assertNotIn("blender_3d", layouts)


class TestAiDirectorVision(unittest.TestCase):
    def _with_image(self, sb):
        import tempfile
        from PIL import Image
        td = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
        img = os.path.join(td, "scene.jpg")
        Image.new("RGB", (32, 32), (120, 30, 30)).save(img)
        for seg in sb["segments"]:
            seg["image_path"] = img
        return img

    def test_gemini_descriptions_feed_the_director_prompt(self):
        sb = _storyboard(TEXTS)
        self._with_image(sb)
        client = FakeClient(plan={"scenes": [{"scene": i, "layout": "full"} for i in range(1, 8)]})
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g"}), \
                mock.patch("ai.gemini_vision.ask_images",
                           return_value=json.dumps({"images": [{"description": "a dark red square"}
                                                               for _ in range(7)]})) as vision:
            ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        vision.assert_called_once()
        self.assertIn("visto: a dark red square", client.prompt)

    def test_vision_failure_falls_back_to_text_only(self):
        sb = _storyboard(TEXTS)
        self._with_image(sb)
        client = FakeClient(plan={"scenes": [{"scene": i, "layout": "full"} for i in range(1, 8)]})
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g"}), \
                mock.patch("ai.gemini_vision.ask_images", side_effect=RuntimeError("quota")):
            ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        self.assertIn("layout_plan", sb["segments"][0])
        self.assertNotIn("visto:", client.prompt)   # siguio solo con texto

    def test_vision_falls_back_to_second_model(self):
        sb = _storyboard(TEXTS)
        self._with_image(sb)
        client = FakeClient(plan={"scenes": [{"scene": i, "layout": "full"} for i in range(1, 8)]})
        calls = []

        def fake_ask(prompt, images, model=None, **kwargs):
            calls.append(model)
            if model == "gemini-2.5-flash":
                raise RuntimeError("Gemini HTTP 503: high demand")
            return json.dumps({"images": [{"description": "a red square"} for _ in images]})

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g"}), \
                mock.patch("ai.gemini_vision.ask_images", side_effect=fake_ask):
            ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        self.assertEqual(calls, ["gemini-2.5-flash", "gemini-3.5-flash"])
        self.assertIn("visto: a red square", client.prompt)

    def test_no_vision_without_gemini_key(self):
        sb = _storyboard(TEXTS)
        self._with_image(sb)
        client = FakeClient(plan={"scenes": [{"scene": i, "layout": "full"} for i in range(1, 8)]})
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), \
                mock.patch("ai.gemini_vision.ask_images") as vision:
            ai_director.direct_layouts_with_ai(sb, level="ai", log=lambda m: None, client=client)
        vision.assert_not_called()
        self.assertNotIn("visto:", client.prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
