# -*- coding: utf-8 -*-
"""Guardas de la composicion por escena (pipeline/segment_layouts).

Cubre las reglas del planificador, de donde salen los paneles extra, el encaje
sin barras negras y que cada composicion produzca un clip valido y de la
duracion exacta (un cuadro de menos por escena desincroniza todo el video).
"""

import os
import shutil
import subprocess
import tempfile
import unittest
import wave

from pipeline import segment_layouts as sl
from pipeline.cinematic_director import count_judder_frames

FFMPEG = shutil.which("ffmpeg")


def _storyboard(texts, dur=4.0, **extra):
    return {"segments": [
        dict({"start": i * dur, "end": (i + 1) * dur, "text": t, "narration_text": t}, **extra)
        for i, t in enumerate(texts)
    ]}


def _layouts(storyboard):
    return [s["layout_plan"]["layout"] for s in storyboard["segments"]]


class TestNameTag(unittest.TestCase):
    def test_finds_people(self):
        self.assertEqual(sl.extract_name_tag("Gavrilo Princip fired two shots."), "GAVRILO PRINCIP")
        self.assertEqual(sl.extract_name_tag("In June 1914, Archduke Franz Ferdinand visited Sarajevo."),
                         "ARCHDUKE FRANZ FERDINAND")
        self.assertEqual(sl.extract_name_tag("Leonardo da Vinci painted it."), "LEONARDO DA VINCI")

    def test_rejects_what_is_not_a_name(self):
        for text in ("The Romans built it.", "World War began in Europe.",
                     "In June the city burned.", "nothing capitalized here", ""):
            self.assertEqual(sl.extract_name_tag(text), "", text)


class TestPlanLayouts(unittest.TestCase):
    TEXTS = [
        "On that morning two shots changed history.",                 # 0 entrada
        "Archduke Franz Ferdinand arrived in Sarajevo.",              # persona
        "The city cheered, while assassins waited in the crowd.",     # comparacion
        "Three conspirators stood along the river.",                  # enumeracion
        "A bomb exploded under the next car.",
        "A wrong turn brought the car to the killer.",                # climax
        "Within weeks, Europe was at war.",                           # cierre
    ]

    def test_off_keeps_everything_full(self):
        sb = _storyboard(self.TEXTS)
        sl.plan_layouts(sb, level="off")
        self.assertEqual(set(_layouts(sb)), {"full"})

    def test_content_rules(self):
        sb = _storyboard(self.TEXTS)
        sl.plan_layouts(sb, level="high")
        got = _layouts(sb)
        self.assertEqual(got[0], "full", "la entrada lleva su propio movimiento y el gancho")
        self.assertEqual(got[-1], "full", "el cierre va limpio")
        self.assertEqual(got[1], "pip")
        self.assertEqual(sb["segments"][1]["layout_plan"]["tag"], "ARCHDUKE FRANZ FERDINAND")
        self.assertEqual(got[2], "split")
        self.assertEqual(got[3], "triptych")
        self.assertEqual(got[5], "punch_in")

    def test_never_the_same_layout_twice_in_a_row(self):
        sb = _storyboard(["x"] + ["Three things, while a long shot holds."] * 8 + ["y"], dur=6.0)
        sl.plan_layouts(sb, level="high")
        got = _layouts(sb)
        for a, b in zip(got, got[1:]):
            if a != "full":
                self.assertNotEqual(a, b, got)

    def test_budget(self):
        texts = ["x"] + ["Three rivers, while the long shot holds steady."] * 10 + ["y"]
        for level, budget in (("moderate", 0.40), ("high", 0.70)):
            sb = _storyboard(texts, dur=6.0)
            sl.plan_layouts(sb, level=level)
            used = sum(1 for name in _layouts(sb) if name != "full")
            self.assertLessEqual(used, round(10 * budget), level)
            self.assertGreater(used, 0, level)

    def test_respects_locked_and_keeps_extra_media(self):
        sb = _storyboard(self.TEXTS)
        sb["segments"][4]["layout_plan"] = {"layout": "triptych", "locked": True}
        sb["segments"][5]["layout_plan"] = {"layout": "full", "locked": False, "extra_media": ["a.png"]}
        sl.plan_layouts(sb, level="high")
        self.assertEqual(sb["segments"][4]["layout_plan"]["layout"], "triptych")
        self.assertEqual(sb["segments"][5]["layout_plan"]["extra_media"], ["a.png"])

    def test_video_and_short_scenes_stay_full(self):
        sb = _storyboard(self.TEXTS)
        sb["segments"][2]["video_path"] = "clip.mp4"
        sb["segments"][3]["end"] = sb["segments"][3]["start"] + 1.0
        sl.plan_layouts(sb, level="high")
        self.assertEqual(_layouts(sb)[2], "full")
        self.assertEqual(_layouts(sb)[3], "full")

    def test_blender_goes_to_the_strong_moment(self):
        sb = _storyboard(self.TEXTS)
        sl.plan_layouts(sb, level="moderate", blender_shots=1)
        got = _layouts(sb)
        self.assertEqual(got.count("blender_desk"), 1)
        self.assertEqual(got[5], "blender_desk", "el climax se lleva la toma 3D")
        sb = _storyboard(self.TEXTS)
        sl.plan_layouts(sb, level="off", blender_shots=1)
        self.assertNotIn("blender_desk", _layouts(sb))


class TestResolveSources(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.mkdtemp(prefix="layout_src_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.imgs = []
        for i in range(5):
            path = os.path.join(self.tmp, f"img{i}.png")
            Image.new("RGB", (40, 70), (i * 40, 20, 20)).save(path)
            self.imgs.append(path)

    def _clips(self, layout, at=2, extra=None):
        clips = [{"filename": p} for p in self.imgs]
        clips[at]["layout_plan"] = {"layout": layout, "extra_media": extra or []}
        sl.resolve_layout_sources(clips)
        return clips[at].get("layout_sources")

    def test_split_looks_back_and_reveal_looks_ahead(self):
        self.assertEqual(self._clips("split")[0]["path"], self.imgs[1])
        self.assertEqual(self._clips("reveal")[0]["path"], self.imgs[3])

    def test_extra_media_wins(self):
        self.assertEqual(self._clips("split", extra=[self.imgs[4]])[0]["path"], self.imgs[4])

    def test_pip_magnifies_its_own_image(self):
        src = self._clips("pip")[0]
        self.assertEqual(src["path"], self.imgs[2])
        self.assertTrue(src.get("detail"))

    def test_triptych_and_lonely_scene(self):
        self.assertEqual(len(self._clips("triptych")), 2)
        clips = [{"filename": self.imgs[0], "layout_plan": {"layout": "triptych"}}]
        sl.resolve_layout_sources(clips)
        self.assertTrue(all(s.get("detail") for s in clips[0]["layout_sources"]),
                        "sin vecinas, los paneles salen de detalles de la misma imagen")

    def test_video_scene_gets_nothing(self):
        clips = [{"filename": "a.mp4", "layout_plan": {"layout": "split"}}, {"filename": self.imgs[0]}]
        sl.resolve_layout_sources(clips)
        self.assertNotIn("layout_sources", clips[0])


class TestFrameFit(unittest.TestCase):
    """Antes: `scale=decrease,pad` -> una foto horizontal en un short quedaba
    con dos franjas negras enormes arriba y abajo."""

    def test_decision(self):
        self.assertFalse(sl.needs_blur_fill((1080, 1920), (1080, 1920)))
        self.assertFalse(sl.needs_blur_fill((1024, 1792), (1080, 1920)), "casi igual: se recorta")
        self.assertTrue(sl.needs_blur_fill((1500, 1000), (1080, 1920)))
        self.assertTrue(sl.needs_blur_fill((1080, 1920), (1920, 1080)))
        self.assertIn("pad=", sl.frame_fit_filter(None, (1080, 1920)), "sin medir, no recorta a ciegas")

    def test_landscape_photo_in_a_short_has_no_black_bars(self):
        if not FFMPEG:
            self.skipTest("ffmpeg no disponible")
        import numpy as np
        from PIL import Image
        tmp = tempfile.mkdtemp(prefix="fit_")
        self.addCleanup(shutil.rmtree, tmp, True)
        src = os.path.join(tmp, "land.png")
        Image.fromarray(np.full((200, 300, 3), (180, 120, 60), "uint8")).save(src)
        out = os.path.join(tmp, "f.png")
        for chain, expect_black in ((sl.frame_fit_filter((300, 200), (216, 384)), False),
                                    ("scale=216:384:force_original_aspect_ratio=decrease,"
                                     "pad=216:384:(ow-iw)/2:(oh-ih)/2", True)):
            subprocess.run([FFMPEG, "-v", "error", "-y", "-i", src, "-vf", chain, "-frames:v", "1", out],
                           check=True, capture_output=True)
            top = np.asarray(Image.open(out).convert("RGB"), dtype="float32")[:30]
            self.assertEqual(top.max() < 10, expect_black, chain[:40])


@unittest.skipUnless(FFMPEG, "ffmpeg no disponible")
class TestLayoutGraphs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        from PIL import Image
        cls.np = np
        cls.tmp = tempfile.mkdtemp(prefix="layout_graph_")
        rng = np.random.RandomState(3)
        cls.imgs = []
        for i, size in enumerate(((300, 200), (200, 300), (240, 240))):
            path = os.path.join(cls.tmp, f"src{i}.png")
            Image.fromarray(rng.randint(30, 220, (size[1], size[0], 3)).astype("uint8")).save(path)
            cls.imgs.append(path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _render(self, layout, size, duration=2.0, fps=15, tag=""):
        srcs = [{"path": self.imgs[1]}, {"path": self.imgs[2]}]
        if layout == "pip":
            srcs = [{"path": self.imgs[0], "detail": sl.DETAIL_CROPS[0]}]
        spec = sl.build_layout_graph(layout, main=self.imgs[0], sources=srcs, duration=duration,
                                     size=size, fps=fps, temp_dir=self.tmp, index=1, tag=tag,
                                     main_size=(300, 200))
        cmd = [FFMPEG, "-v", "error"]
        for path in spec["inputs"]:
            cmd += ["-i", path]
        cmd += ["-t", str(duration), "-filter_complex", spec["graph"], "-map", "[lay]",
                "-f", "framemd5", "-"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, f"{layout} {size}: {proc.stderr[-400:]}")
        return proc.stdout

    def test_every_layout_renders_exact_duration_in_both_orientations(self):
        for size in ((216, 384), (384, 216)):
            for layout in sorted(sl.FFMPEG_LAYOUTS):
                out = self._render(layout, size, tag="ADA LOVELACE" if layout == "pip" else "")
                self.assertEqual(count_judder_frames(out)[1], 30, f"{layout} {size}")

    def test_punch_in_actually_cuts(self):
        """Cada plano empieza con un flash: el cuadro del corte salta en brillo."""
        spec = sl.build_layout_graph("punch_in", main=self.imgs[0], sources=[], duration=4.0,
                                     size=(216, 384), fps=15, temp_dir=self.tmp, main_size=(300, 200))
        out = os.path.join(self.tmp, "pk_%03d.png")
        cmd = [FFMPEG, "-v", "error", "-y", "-i", spec["inputs"][0], "-t", "4",
               "-filter_complex", spec["graph"], "-map", "[lay]", out]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        from PIL import Image
        means = [self.np.asarray(Image.open(out % (k + 1)).convert("L"), dtype="float32").mean()
                 for k in range(60)]
        flashes = [k for k in range(1, 60) if means[k] - means[k - 1] > 25]
        self.assertGreaterEqual(len(flashes), 1, "sin cortes visibles: %s" % flashes)


@unittest.skipUnless(FFMPEG, "ffmpeg no disponible")
class TestAssemblerWithLayouts(unittest.TestCase):
    """Ensamblaje real: las composiciones salen y, si una falla, la escena va a
    pantalla completa (antes un clip fallido salia en NEGRO)."""

    def test_layouts_render_and_a_broken_one_falls_back(self):
        from PIL import Image
        from pipeline.auto_video_generator_v2 import AutoVideoGenerator
        tmp = tempfile.mkdtemp(prefix="assembler_layouts_")
        self.addCleanup(shutil.rmtree, tmp, True)
        imgs = []
        for i, color in enumerate(((150, 60, 40), (40, 120, 150), (90, 150, 60))):
            path = os.path.join(tmp, f"s{i}.png")
            Image.new("RGB", (300, 200), color).save(path)
            imgs.append(path)
        audio = os.path.join(tmp, "voice.wav")
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000 * 6)
        clips = [
            {"filename": imgs[0], "duration": 2.0, "segment_text": "a"},
            {"filename": imgs[1], "duration": 2.0, "segment_text": "b",
             "layout_plan": {"layout": "split"}, "layout_sources": [{"path": imgs[0]}]},
            {"filename": imgs[2], "duration": 2.0, "segment_text": "c",
             "layout_plan": {"layout": "split"},
             "layout_sources": [{"path": os.path.join(tmp, "no_existe.png")}]},
        ]
        gen = AutoVideoGenerator.__new__(AutoVideoGenerator)
        gen.log = lambda *_: None
        gen._audio_qa = {}
        out = os.path.join(tmp, "out.mp4")
        ok = gen._assemble_direct_ffmpeg(clips, audio, out, (216, 384), fps=15,
                                         transition_type="None (Direct Cut)",
                                         enable_transition_sfx=False)
        self.assertTrue(ok)
        self.assertEqual(gen._audio_qa.get("layouts_rendered"), {"split": 1})
        self.assertEqual(gen._audio_qa.get("layouts_failed"), ["3:split"])
        self.assertEqual(gen._audio_qa.get("blur_fill_count"), 3)
        frame = os.path.join(tmp, "last.png")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "5.0", "-i", out, "-frames:v", "1", frame],
                       check=True, capture_output=True)
        import numpy as np
        pixels = np.asarray(Image.open(frame).convert("RGB"), dtype="float32")
        self.assertGreater(pixels.mean(), 30, "la escena con composicion rota salio en negro")


if __name__ == "__main__":
    unittest.main(verbosity=2)
