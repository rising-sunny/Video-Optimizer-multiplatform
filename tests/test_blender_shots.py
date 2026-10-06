# -*- coding: utf-8 -*-
"""Guardas de las tomas 3D con Blender (pipeline/blender_shots).

Lo importante: si Blender no esta, falla o tarda de mas, el video igual sale
(la escena cae a punch-in) y el QA lo dice. El render real es lento (~25 s
aun minimo, por la compilacion de shaders): corre solo con RUN_BLENDER_TESTS=1.

    set RUN_BLENDER_TESTS=1 && .venv\\Scripts\\python.exe -m unittest tests.test_blender_shots
"""

import os
import py_compile
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from pipeline import blender_shots as bs


class TestFindBlender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="find_blender_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _fake(self, *parts):
        path = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def test_explicit_path_wins(self):
        exe = self._fake("custom", "blender.exe")
        self.assertEqual(bs.find_blender({"BLENDER_PATH": exe}), exe)

    def test_newest_installed_version(self):
        self._fake("Blender Foundation", "Blender 4.4", "blender.exe")
        newest = self._fake("Blender Foundation", "Blender 5.1", "blender.exe")
        self._fake("Blender Foundation", "Blender 4.10", "blender.exe")
        with mock.patch.object(bs.shutil, "which", return_value=None):
            found = bs.find_blender({"BLENDER_PATH": os.path.join(self.tmp, "no_existe.exe"),
                                     "ProgramFiles": self.tmp, "ProgramFiles(x86)": self.tmp})
        self.assertEqual(found, newest)

    def test_none_when_missing(self):
        with mock.patch.object(bs.shutil, "which", return_value=None):
            self.assertIsNone(bs.find_blender({"ProgramFiles": self.tmp, "ProgramFiles(x86)": self.tmp}))


class TestParamsAndCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="blender_cache_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.img = os.path.join(self.tmp, "a.png")
        with open(self.img, "wb") as fh:
            fh.write(b"1234")

    def test_quality_names(self):
        self.assertEqual(bs.normalize_quality("Borrador"), "draft")
        self.assertEqual(bs.normalize_quality("high"), "high")
        self.assertEqual(bs.normalize_quality("???"), bs.DEFAULT_QUALITY)

    def test_shot_has_a_tail_so_the_assembler_never_stretches_it(self):
        self.assertEqual(bs.shot_frames(4.0, 30), int(round((4.0 + bs.TAIL_SECONDS) * 30)))

    def test_cache_key(self):
        p1 = bs.build_params([self.img], 3.0, (1080, 1920), 30, "normal", os.path.join(self.tmp, "x"))
        p2 = bs.build_params([self.img], 3.0, (1080, 1920), 30, "normal", os.path.join(self.tmp, "y"))
        self.assertEqual(bs.cache_key(p1), bs.cache_key(p2), "la carpeta temporal no cuenta")
        p3 = bs.build_params([self.img], 3.0, (1080, 1920), 30, "high", os.path.join(self.tmp, "x"))
        self.assertNotEqual(bs.cache_key(p1), bs.cache_key(p3), "otra calidad = otra toma")
        before = bs.cache_key(p1)
        time.sleep(1.1)
        with open(self.img, "wb") as fh:
            fh.write(b"otra imagen distinta")
        self.assertNotEqual(bs.cache_key(p1), before, "imagen cambiada = otra toma")

    def test_errors_come_back_instead_of_raising(self):
        missing = bs.render_desk_shot([os.path.join(self.tmp, "no.png")], duration=1, size=(108, 192),
                                      fps=30, cache_dir=self.tmp)
        self.assertFalse(missing["ok"])
        self.assertIn("sin imagenes", missing["error"])
        with mock.patch.object(bs, "find_blender", return_value=None):
            no_blender = bs.render_desk_shot([self.img], duration=1, size=(108, 192), fps=30,
                                             cache_dir=self.tmp)
        self.assertFalse(no_blender["ok"])
        self.assertIn("BLENDER_PATH", no_blender["error"])

    def test_template_is_valid_python(self):
        py_compile.compile(bs.DESK_TEMPLATE, doraise=True)


class TestAssemblerFallsBackWithoutBlender(unittest.TestCase):
    def test_scene_becomes_punch_in_and_qa_says_so(self):
        from pipeline.auto_video_generator_v2 import AutoVideoGenerator
        tmp = tempfile.mkdtemp(prefix="blender_fallback_")
        self.addCleanup(shutil.rmtree, tmp, True)
        img = os.path.join(tmp, "a.png")
        open(img, "wb").close()
        gen = AutoVideoGenerator.__new__(AutoVideoGenerator)
        gen.log = lambda *_: None
        gen._audio_qa = {}
        gen.generated_media_dir = tmp
        clips = [{"filename": img, "duration": 3.0, "layout_plan": {"layout": "blender_desk"}}]
        gen._render_blender_shots(clips, (1080, 1920), blender_exe=None)
        self.assertEqual(clips[0]["layout_plan"]["layout"], "punch_in")
        self.assertEqual(clips[0]["filename"], img)
        self.assertEqual(len(gen._audio_qa["blender_shots_failed"]), 1)

        lineas = []
        gen.log = lineas.append
        gen._probe_media_duration = lambda *_: 0.0
        gen._audio_qa["sfx_enabled"] = False
        problemas = AutoVideoGenerator.log_audio_qa(gen)
        self.assertTrue(any("toma 3D" in p for p in problemas))
        self.assertTrue(any("Toma 3D -> punch-in" in ln for ln in lineas))


@unittest.skipUnless(os.environ.get("RUN_BLENDER_TESTS") == "1" and bs.find_blender(),
                     "render real de Blender: RUN_BLENDER_TESTS=1 (tarda ~25 s)")
class TestRealRender(unittest.TestCase):
    def test_tiny_shot_renders_and_is_cached(self):
        from PIL import Image
        tmp = tempfile.mkdtemp(prefix="blender_real_")
        self.addCleanup(shutil.rmtree, tmp, True)
        imgs = []
        for i, color in enumerate(((180, 120, 60), (60, 120, 180))):
            path = os.path.join(tmp, f"p{i}.png")
            Image.new("RGB", (120, 160), color).save(path)
            imgs.append(path)
        cache = os.path.join(tmp, "cache")
        first = bs.render_desk_shot(imgs, duration=0.0, size=(108, 192), fps=5, cache_dir=cache,
                                    quality="draft", log=lambda *_: None)
        self.assertTrue(first["ok"], first["error"])
        probe = subprocess.run(
            [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-count_frames", "-show_entries",
             "stream=width,height,nb_read_frames", "-of", "csv=p=0", first["path"]],
            capture_output=True, text=True, check=True)
        self.assertEqual(probe.stdout.strip(), f"108,192,{bs.shot_frames(0.0, 5)}")
        second = bs.render_desk_shot(imgs, duration=0.0, size=(108, 192), fps=5, cache_dir=cache,
                                     quality="draft", log=lambda *_: None)
        self.assertTrue(second["cached"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
