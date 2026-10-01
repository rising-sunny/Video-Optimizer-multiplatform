# -*- coding: utf-8 -*-
"""Tests de visual_art_direction: prompts de imagen con direccion de arte por segmento.

El usuario pega el prompt de "Copiar Prompts" en una IA externa. Antes salia
del armado para FLUX (refuerzos, sufijo de variacion, negative en etiquetas) y
cada escena elegia luz y paleta por su cuenta. Sin red: el modelo es falso.
"""

import json
import os
import unittest
from pathlib import Path
from unittest import mock

import visual_art_direction as vad

ROOT = Path(__file__).resolve().parent.parent

NARR = [
    "How did Admiral Nelson break a numerically superior fleet on October 21 1805?",
    "At 12:45 PM, HMS Victory broke the enemy line with a daring double-column attack.",
    "After hours of fighting, the British captured Admiral Villeneuve aboard his flagship Bucentaure.",
    "Nelson was struck by a French marksman and died knowing the battle was won.",
]

BIBLE = {
    "era": "21 October 1805", "place": "off Cape Trafalgar", "conditions": "light winds, heavy swell",
    "characters": [{"name": "Horatio Nelson", "appearance": "47, right arm amputated, right eye blind but normal",
                    "costume": "Vice-Admiral's undress coat with four stars", "avoid": "eyepatch"}],
    "objects": [{"name": "HMS Victory", "look": "black hull with yellow ochre gunport bands"}],
    "palette_arc": [
        {"act": "setup", "scenes": "1-2", "colors": ["Pewter #6B7078", "Canvas #E8E0CC"], "light": "cold dawn, 5600K"},
        {"act": "confrontation", "scenes": "3", "colors": ["Gunsmoke #2F3542", "Flash amber #E8A13A"],
         "light": "smoke-filtered noon sun"},
        {"act": "resolution", "scenes": "4", "colors": ["Ember #C4622D"], "light": "low lantern light, 2700K"},
    ],
    "look": {"camera": "ARRI Alexa 35", "lens": "anamorphic primes", "film": "Kodak Vision3 500T grain",
             "grade": "lifted shadows"},
    "avoid": ["eyepatch on Nelson", "Hollywood explosions (use black powder smoke)", "pirate costume"],
}


def shots_reply(indices, extra=None):
    shots = []
    for i in indices:
        shots.append({
            "scene": i + 1, "moment": f"moment of scene {i + 1}.", "subject": "Horatio Nelson, one-armed.",
            "action": "raising his telescope.", "setting": "quarterdeck of HMS Victory, dawn.",
            "shot": "medium-wide, low angle.", "lens": "40mm anamorphic, T2.8",
            "depth": "foreground rigging; midground Nelson; background enemy line",
            "lighting": "low sun from camera left, 3800K, cool sky fill.",
            "palette": ["Pewter #6B7078", "Canvas #E8E0CC"], "atmosphere": "sea spray, thin gunsmoke.",
            "mood": "resolve", "details": "four embroidered stars, empty right sleeve pinned",
            "avoid": ["two arms"],
        })
    obj = {"shots": shots}
    if extra:
        obj["shots"].extend(extra)
    return json.dumps(obj)


class FakeLLM:
    """Responde biblia o planos segun el pedido; cuenta las llamadas."""

    def __init__(self, bible=BIBLE, fail_shots=0):
        self.calls = []
        self.bible = bible
        self.fail_shots = fail_shots

    def __call__(self, prompt):
        self.calls.append(prompt)
        if "VISUAL BIBLE every image" in prompt:
            return json.dumps(self.bible)
        if self.fail_shots > 0:
            self.fail_shots -= 1
            return "lo siento"
        wanted = prompt.split("for each of these scenes: ", 1)[1].split(" (of", 1)[0]
        return shots_reply([int(n) - 1 for n in wanted.split(", ")])


def storyboard(narr=NARR):
    return {"topic": "How Nelson Won Trafalgar",
            "segments": [{"narration_text": t, "text": t, "visual_prompt": f"old prompt {i}"}
                         for i, t in enumerate(narr)]}


class LaBiblia(unittest.TestCase):
    def test_prompt_asks_for_documented_people_palette_arc_and_myths(self):
        p = vad.build_bible_prompt("Trafalgar", "Scene 1: ...", aspect="9:16", scene_count=7)
        for must in ("AT THAT DATE", "never an eyepatch", "palette arc in three acts", "hex codes",
                     "color temperature", "anachronisms", "omit a detail rather than guess"):
            self.assertIn(must, p)

    def test_parse_bible(self):
        self.assertIsNone(vad.parse_bible("no"))
        b = vad.parse_bible("```json\n" + json.dumps({"era": "1805", "avoid": "a; b"}) + "\n```")
        self.assertEqual(b["avoid"], ["a", "b"])
        self.assertEqual(b["characters"], [])

    def test_each_scene_gets_its_act(self):
        self.assertEqual(vad.act_for_scene(BIBLE, 1, 4)["act"], "setup")
        self.assertEqual(vad.act_for_scene(BIBLE, 3, 4)["act"], "confrontation")
        self.assertEqual(vad.act_for_scene(BIBLE, 4, 4)["act"], "resolution")
        no_ranges = {"palette_arc": [{"act": "a"}, {"act": "b"}, {"act": "c"}]}
        self.assertEqual(vad.act_for_scene(no_ranges, 9, 9)["act"], "c")


class LosPlanos(unittest.TestCase):
    def test_shots_prompt_carries_bible_story_and_rules(self):
        p = vad.build_shots_prompt(BIBLE, NARR, [0, 2], "Trafalgar", existing={0: "old idea"})
        self.assertIn("for each of these scenes: 1, 3 (of 4)", p)
        self.assertIn("Horatio Nelson", p)                 # la biblia viaja
        self.assertIn("Scene 3: After hours of fighting", p)
        self.assertIn("never a claim it does not make", p)
        self.assertIn("Vary shot sizes", p)
        self.assertIn("never an extreme close-up", p)       # la escena 1 lleva el titular arriba
        self.assertIn("old idea", p)

    def test_parse_shots_keeps_valid_scenes_only(self):
        raw = shots_reply([0, 1], extra=[{"scene": 9, "moment": "x"}, {"scene": 2}, "bad"])
        shots = vad.parse_shots(raw, 4)
        self.assertEqual(sorted(shots), [0, 1])
        self.assertEqual(shots[0]["avoid"], ["two arms"])


class ElPromptFinal(unittest.TestCase):
    def shot(self):
        return vad.parse_shots(shots_reply([0]), 4)[0]

    def test_sections_in_clean_prose(self):
        p = vad.compose_prompt(self.shot(), BIBLE, scene_no=1, total=4, aspect="9:16", is_opening=True)
        lines = p.split("\n")
        self.assertEqual(lines[0], "Vertical 9:16 photorealistic cinematic film still, documentary reenactment.")
        for head in ("Scene:", "Subject:", "Action:", "Setting:", "Composition:", "Lighting:",
                     "Color palette:", "Atmosphere:", "Period details:", "Camera and look:", "Avoid:"):
            self.assertTrue(any(l.startswith(head) for l in lines), head)
        for bad in (".,", ".;", ",.", ";.", "..", " ,"):
            self.assertNotIn(bad, p)
        self.assertIn("Pewter #6B7078", p)
        self.assertIn("3800K", p)
        self.assertIn("ARRI Alexa 35", p)

    def test_opening_keeps_headline_band_and_all_keep_subtitle_zone(self):
        first = vad.compose_prompt(self.shot(), BIBLE, scene_no=1, total=4, is_opening=True)
        later = vad.compose_prompt(self.shot(), BIBLE, scene_no=3, total=4, is_opening=False)
        self.assertIn("12-36% from the top", first)
        self.assertNotIn("12-36% from the top", later)
        self.assertIn("subtitles go there", later)
        wide = vad.compose_prompt(self.shot(), BIBLE, scene_no=3, total=4, aspect="16:9")
        self.assertTrue(wide.startswith("Horizontal 16:9"))
        self.assertNotIn("subtitles go there", wide)

    def test_avoid_merges_scene_video_and_base_without_repeats(self):
        p = vad.compose_prompt(dict(self.shot(), avoid=["Eyepatch on Nelson", "two arms"]), BIBLE,
                               scene_no=2, total=4)
        avoid = p.split("Avoid: ", 1)[1]
        self.assertEqual(avoid.lower().count("eyepatch"), 1)
        self.assertIn("any text, letters, captions, logos or watermarks", avoid)

    def test_negative_prompt_is_short_phrases(self):
        neg = vad.negative_prompt(self.shot(), BIBLE)
        self.assertIn("Hollywood explosions", neg)
        self.assertNotIn("(use black powder smoke)", neg)
        self.assertIn("deformed hands", neg)

    def test_palette_falls_back_to_the_act(self):
        shot = dict(self.shot(), palette=[])
        p = vad.compose_prompt(shot, BIBLE, scene_no=4, total=4)
        self.assertIn("Ember #C4622D", p)


class LaOrquestacion(unittest.TestCase):
    def test_one_bible_and_batched_shots_then_cached(self):
        sb = storyboard()
        llm = FakeLLM()
        ready = vad.ensure_art_direction(sb, [0, 1, 2, 3], llm=llm, log=lambda m: None)
        self.assertEqual(ready, [0, 1, 2, 3])
        self.assertEqual(len(llm.calls), 2)                  # biblia + una tanda
        self.assertFalse(vad.needs_work(sb, [0, 1, 2, 3]))
        vad.ensure_art_direction(sb, [0, 1, 2, 3], llm=llm, log=lambda m: None)
        self.assertEqual(len(llm.calls), 2)                  # ya estaba al dia
        p = vad.prompt_for_segment(sb, 2)
        self.assertIn("Scene: Moment of scene 3.", p["prompt"])

    def test_editing_one_narration_redoes_the_bible_and_that_shot(self):
        sb = storyboard()
        llm = FakeLLM()
        vad.ensure_art_direction(sb, [0, 1, 2, 3], llm=llm, log=lambda m: None)
        sb["segments"][2]["narration_text"] = "Villeneuve surrendered Bucentaure after hours of fighting."
        self.assertTrue(vad.needs_work(sb, [2]))
        self.assertIsNone(vad.prompt_for_segment(sb, 2))      # un plano viejo no se copia
        vad.ensure_art_direction(sb, [2], llm=llm, log=lambda m: None)
        self.assertIsNotNone(vad.prompt_for_segment(sb, 2))

    def test_editing_the_visual_prompt_redoes_that_shot(self):
        sb = storyboard()
        vad.ensure_art_direction(sb, [0, 1], llm=FakeLLM(), log=lambda m: None)
        sb["segments"][1]["visual_prompt"] = "the user's own idea"
        self.assertTrue(vad.needs_work(sb, [1]))
        self.assertFalse(vad.needs_work(sb, [0]))

    def test_long_scripts_go_in_batches(self):
        sb = storyboard([f"Scene text number {i}." for i in range(23)])
        llm = FakeLLM()
        ready = vad.ensure_art_direction(sb, list(range(23)), llm=llm, log=lambda m: None)
        self.assertEqual(len(ready), 23)
        self.assertEqual(len(llm.calls), 1 + 3)

    def test_unreadable_shots_are_retried_once(self):
        sb = storyboard()
        llm = FakeLLM(fail_shots=1)
        self.assertEqual(vad.ensure_art_direction(sb, [0], llm=llm, log=lambda m: None), [0])

    def test_model_down_returns_nothing_so_the_old_prompt_is_used(self):
        sb = storyboard()
        self.assertEqual(vad.ensure_art_direction(sb, [0], llm=lambda p: None, log=lambda m: None), [])
        self.assertIsNone(vad.prompt_for_segment(sb, 0))

    def test_switch(self):
        with mock.patch.dict(os.environ, {"VISUAL_ART_DIRECTION": "0"}):
            self.assertFalse(vad.enabled())


class ElPromptDeVideo(unittest.TestCase):
    """Segundo boton: prompt para una IA de video externa, desde el mismo plano que la imagen."""

    def shot(self, **extra):
        shot = vad.parse_shots(shots_reply([0]), 4)[0]
        shot.update({"camera_move": "slow push-in from medium-wide to medium",
                     "subject_motion": "Nelson lowers the telescope and narrows his eyes",
                     "environment_motion": "gunsmoke drifts left, sails snap in the wind",
                     "pace": "measured", "sound": "creaking timbers, distant cannon"})
        shot.update(extra)
        return shot

    def test_shots_prompt_asks_for_motion_ai_video_can_render(self):
        p = vad.build_shots_prompt(BIBLE, NARR, [0], "Trafalgar", motions={0: "slow zoom"})
        for must in ("FIRST FRAME of a 5-10 s AI video clip", "ONE slow, smooth", "no fighting",
                     "walking toward the camera", "no music, no voices", '"camera_move"', '"environment_motion"',
                     "slow zoom"):
            self.assertIn(must, p)

    def test_sections_duration_and_sound(self):
        p = vad.compose_video_prompt(self.shot(), BIBLE, scene_no=1, total=4, aspect="9:16",
                                     is_opening=True, duration=6.6)
        lines = p.split("\n")
        self.assertTrue(lines[0].startswith("Vertical 9:16 cinematic video clip, about 7 seconds, one continuous shot"))
        for head in ("Opening frame:", "Camera:", "Subject motion:", "Environment motion:", "Lighting and color:",
                     "Pace:", "Frame zones:", "Sound (only if the tool generates audio):", "Look:", "Avoid:"):
            self.assertTrue(any(l.startswith(head) for l in lines), head)
        self.assertIn("Slow push-in from medium-wide to medium.", p)
        self.assertIn("calm for the first 2 seconds", p)
        self.assertIn("no dialogue, no narration, no music", p)
        self.assertIn("morphing or melting faces", p)
        self.assertIn("eyepatch on Nelson", p)                 # la biblia tambien vale para el video
        for bad in (".,", ".;", ",.", ";.", ".."):
            self.assertNotIn(bad, p)

    def test_missing_camera_move_gets_a_safe_default(self):
        p = vad.compose_video_prompt(self.shot(camera_move=""), BIBLE, scene_no=3, total=4, duration=0)
        self.assertIn("Camera: Slow, smooth push-in over the whole clip.", p)
        self.assertIn("5-10 seconds", p)
        self.assertNotIn("calm for the first 2 seconds", p)

    def test_motion_only_is_for_animating_the_still(self):
        m = vad.motion_only(self.shot())
        self.assertTrue(m.startswith("Slow push-in"))
        self.assertIn("Keep the look, lighting and composition of the image", m)
        self.assertNotIn("Nelson, one-armed", m)               # no redescribe la imagen

    def test_avoid_items_have_no_double_negatives(self):
        bible = dict(BIBLE, avoid=["No bright, saturated 'Hollywood' colors; keep tones organic",
                                   "No inaccurate uniforms (e.g., modern rank insignia)", "Avoid pirate aesthetics"])
        for text in (vad.compose_video_prompt(self.shot(), bible, scene_no=2, total=4).split("Avoid: ", 1)[1],
                     vad.video_negative_prompt(self.shot(), bible), vad.negative_prompt(self.shot(), bible)):
            items = [i.strip() for i in text.replace(";", ",").split(",")]
            self.assertFalse([i for i in items if i.lower().startswith(("no ", "avoid "))], text)
            self.assertIn("inaccurate uniforms", text)
            self.assertNotIn("keep tones organic", text)

    def test_video_negative_has_motion_artifacts(self):
        neg = vad.video_negative_prompt(self.shot(), BIBLE)
        for must in ("morphing", "melting faces", "flicker", "sudden cuts", "eyepatch on Nelson"):
            self.assertIn(must, neg)

    def test_segment_prompt_uses_duration_and_goes_stale_with_motion_edits(self):
        sb = storyboard()
        for i, seg in enumerate(sb["segments"]):
            seg.update({"start": i * 7.0, "end": i * 7.0 + 6.6})
        vad.ensure_art_direction(sb, [0, 1], llm=FakeLLM(), log=lambda m: None)
        data = vad.video_prompt_for_segment(sb, 1)
        self.assertAlmostEqual(data["duration"], 6.6)
        self.assertIn("about 7 seconds", data["prompt"])
        sb["segments"][1]["motion_prompt"] = "the user's own camera move"
        self.assertIsNone(vad.video_prompt_for_segment(sb, 1))
        self.assertTrue(vad.needs_work(sb, [1]))

    def test_version_bump_redoes_old_cached_shots(self):
        sb = storyboard()
        vad.ensure_art_direction(sb, [0], llm=FakeLLM(), log=lambda m: None)
        old = dict(sb["segments"][0]["art_direction"])
        with mock.patch.object(vad, "VERSION", vad.VERSION + 1):
            self.assertTrue(vad.needs_work(sb, [0]))
        self.assertEqual(old["_signature"], sb["segments"][0]["art_direction"]["_signature"])

    def test_fallback_when_art_direction_is_down(self):
        seg = {"visual_prompt": "vertical 9:16, Nelson on the quarterdeck, overcast dawn",
               "motion_prompt": "slow dolly left", "duration": 5.2}
        data = vad.fallback_video_prompt(seg, is_opening=True)
        self.assertIn("Opening frame: Nelson on the quarterdeck, overcast dawn.", data["prompt"])
        self.assertIn("Motion: Slow dolly left.", data["prompt"])
        self.assertIn("about 5 seconds", data["prompt"])
        self.assertTrue(data["motion_only"].startswith("Slow dolly left."))

    def test_clipboard_text_has_three_blocks(self):
        text = vad.video_clipboard_text({"prompt": "P", "motion_only": "M", "negative_prompt": "N",
                                         "duration": 6.6}, "9:16  (1080×1920px)")
        self.assertTrue(text.startswith("Formato: 9:16  (1080×1920px) · Duracion del segmento: 6.6 s"))
        for block in ("Prompt de video (texto a video):\nP", "Solo movimiento (imagen a video", "Negative Prompt:\nN"):
            self.assertIn(block, text)

    def test_segment_duration(self):
        self.assertEqual(vad.segment_duration({"duration": 7.8}), 7.8)
        self.assertAlmostEqual(vad.segment_duration({"start_time": 2.0, "end_time": 8.6}), 6.6)
        self.assertEqual(vad.segment_duration({}), 0.0)


class LosBotones(unittest.TestCase):
    """Dos botones por segmento: imagen y video."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_segment_has_both_buttons_and_the_video_one_emits_its_index(self):
        from timeline_segment_widget import TimelineSegment
        w = TimelineSegment(3, {"narration_text": "x", "text": "x", "visual_prompt": "v", "duration": 5.0},
                            defer_media_load=True)
        self.assertEqual(w.btn_copy_recraft_prompts.text(), "Copiar prompt imagen")
        self.assertEqual(w.btn_copy_video_prompt.text(), "Copiar prompt video")
        got = []
        w.video_prompt_copy_requested.connect(got.append)
        w.btn_copy_video_prompt.click()
        self.assertEqual(got, [3])


class ElCableado(unittest.TestCase):
    def _src(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_video_button_is_wired_for_single_and_grouped_segments(self):
        src = self._src("timeline_editor_widget.py")
        self.assertIn("widget.video_prompt_copy_requested.connect(self.copy_video_prompt_for_segment)", src)
        self.assertIn("wrapper.grouped_copy_video_prompt_requested.connect(self.copy_video_prompt_for_segment)", src)
        body = src[src.index("    def copy_video_prompt_for_segment("):]
        self.assertLess(body.index("self._ensure_art_view([segment_index])"), body.index("fallback_video_prompt("))

    def test_copy_buttons_use_art_direction_first(self):
        src = self._src("timeline_editor_widget.py")
        one = src[src.index("    def copy_recraft_prompts_for_segment("):]
        self.assertLess(one.index("self._art_directed_prompts([segment_index])"),
                        one.index("self._resolve_recraft_prompt_for_segment(segment_index)"))
        allp = src[src.index("    def copy_all_prompts_to_clipboard("):]
        self.assertLess(allp.index("self._art_directed_prompts("), allp.index("self._resolve_recraft_prompt_for_segment(i)"))


class LaReparacionDelPromptVisual(unittest.TestCase):
    """Si el verificador corrige una escena, su prompt de imagen tambien se corrige."""

    def test_corrected_scene_gets_a_corrected_image_prompt(self):
        import script_fact_check as sfc
        sfc._UNAVAILABLE.clear()
        texts = ["Nelson led the attack at Trafalgar in 1805 with great daring and skill.",
                 "Within forty minutes, the British flagship Victory fired the fatal shot that killed Admiral Villeneuve, sealing the British triumph."]
        scenes = [{"narration": t, "visual_prompt": f"vp{i}"} for i, t in enumerate(texts)]
        scenes[1]["visual_prompt"] = "HMS Victory firing the broadside that kills Admiral Villeneuve"

        def judge(prompt):
            problems = []
            if "killed Admiral Villeneuve" in prompt:
                problems.append({"scene": 2, "quote": "killed Admiral Villeneuve", "verdict": "false",
                                 "correction": "Villeneuve was captured."})
            return json.dumps({"claims": problems}), []

        seen = []

        def rewriter(prompt):
            seen.append(prompt)
            return json.dumps({"scenes": [{
                "scene": 2,
                "narration": "Within hours the enemy line was shattered, and Admiral Villeneuve was captured aboard his flagship, sealing the British triumph.",
                "visual_prompt": "Admiral Villeneuve surrendering his sword on the shattered deck of Bucentaure"}]})

        with mock.patch.dict(os.environ, {"SCRIPT_FACT_CHECK": "1"}):
            out, report = sfc.fact_check_scenes(scenes, "Trafalgar", generate_fn=rewriter,
                                                judges=[("j", judge, False)],
                                                http_get=lambda u, p: {"query": {}}, log=lambda m: None)
        self.assertEqual(report["status"], "corrected")
        self.assertIn('Image prompt: "HMS Victory firing the broadside', seen[0])
        self.assertIn('"visual_prompt"', seen[0])
        self.assertEqual(out[1]["visual_prompt"], "Admiral Villeneuve surrendering his sword on the shattered deck of Bucentaure")
        self.assertEqual(out[0]["visual_prompt"], "vp0")


if __name__ == "__main__":
    unittest.main()
