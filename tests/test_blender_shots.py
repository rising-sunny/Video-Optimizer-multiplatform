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

    def test_templates_are_valid_python(self):
        for env in bs.ENVIRONMENTS:
            py_compile.compile(bs.template_path(env), doraise=True)
        py_compile.compile(bs.COMMON_MODULE, doraise=True)

    def test_corkboard_never_renders_in_draft(self):
        """En Borrador el hilo fino del tablero sale serruchado: sube a Normal."""
        self.assertEqual(bs.effective_quality("corkboard", "draft"), "normal")
        self.assertEqual(bs.effective_quality("corkboard", "high"), "high")
        self.assertEqual(bs.effective_quality("desk", "draft"), "draft")
        params = bs.build_params([self.img], 3.0, (1080, 1920), 30, "draft", self.tmp, environment="corkboard")
        self.assertGreaterEqual(params["samples"], 8)
        self.assertEqual(params["shadow_scale"], 1.0)

    def test_cache_key_depends_on_environment(self):
        keys = {bs.cache_key(bs.build_params([self.img], 3.0, (1080, 1920), 30, "normal", self.tmp,
                                             environment=env)) for env in bs.ENVIRONMENTS}
        self.assertEqual(len(keys), len(bs.ENVIRONMENTS))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg no disponible")
class TestScreenVideo(unittest.TestCase):
    """La TV reproduce el video cuadro a cuadro: tiene que llegar sin el tramo congelado,
    del largo de la toma, y quedar en cache (si se re-codifica, la toma se re-renderiza)."""

    def test_moving_part_stretched_and_cached(self):
        tmp = tempfile.mkdtemp(prefix="screen_")
        self.addCleanup(shutil.rmtree, tmp, True)
        clip = os.path.join(tmp, "frozen.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=1.5",
                        "-vf", "tpad=stop_mode=clone:stop_duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        clip], check=True, capture_output=True, timeout=60)
        out = bs.prepare_screen_video(clip, 3.0, 30, tmp)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "csv=p=0", out], capture_output=True, text=True).stdout)
        self.assertAlmostEqual(dur, bs.shot_frames(3.0, 30) / 30.0, delta=0.15)
        log = subprocess.run(["ffmpeg", "-hide_banner", "-i", out, "-vf", "freezedetect=n=0.003:d=0.5",
                              "-f", "null", "-"], capture_output=True, text=True).stderr
        self.assertNotIn("freeze_start", log, "la pantalla de la TV se congelaria")
        mtime = os.path.getmtime(out)
        time.sleep(1.1)
        self.assertEqual(bs.prepare_screen_video(clip, 3.0, 30, tmp), out)
        self.assertEqual(os.path.getmtime(out), mtime)


@unittest.skipUnless(os.name == "nt" and shutil.which("ffmpeg"), "usa un .bat como Blender falso")
class TestBlenderCrashOnExit(unittest.TestCase):
    """Visto el 2026-10-06: EEVEE en segundo plano se cayo con EXCEPTION_ACCESS_VIOLATION
    AL CERRAR, con todos los cuadros ya guardados. Tirar esa toma costaba minutos."""

    FAKE = r'''
import json, os, sys
params = json.load(open(sys.argv[-1], encoding="utf-8"))
from PIL import Image
# FAKE_BLACK_ONCE=<archivo>: el primer intento sale negro (la GPU que falla a mitad).
once = os.environ.get("FAKE_BLACK_ONCE")
black = os.environ.get("FAKE_BLACK") == "1" or bool(once and not os.path.exists(once))
if once and not os.path.exists(once):
    open(once, "w").close()
for k in range(1, int(params["frames"]) + 1 - int(os.environ.get("FAKE_MISSING", "0"))):
    path = os.path.join(params["out_dir"], "f_%04d.png" % k)
    Image.new("RGB", (64, 112), (0, 0, 0) if black else (20 * k, 40, 60)).save(path)
    print("Saved: '%s'" % path, flush=True)
if os.environ.get("FAKE_FINISH") == "1":
    print("RENDER_TIME 1.0", flush=True)
'''

    def setUp(self):
        import sys
        self.tmp = tempfile.mkdtemp(prefix="fake_blender_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        script = os.path.join(self.tmp, "fake_blender.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(self.FAKE)
        self.exe = os.path.join(self.tmp, "blender.bat")
        with open(self.exe, "w", encoding="utf-8") as fh:
            fh.write(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\nexit /b 3\r\n')
        self.img = os.path.join(self.tmp, "a.png")
        from PIL import Image
        Image.new("RGB", (40, 60), (100, 100, 100)).save(self.img)

    def _render(self, **env):
        with mock.patch.dict(os.environ, env):
            return bs.render_shot("desk", [self.img], duration=0.0, size=(64, 112), fps=5,
                                  cache_dir=os.path.join(self.tmp, "cache"), quality="draft",
                                  blender_exe=self.exe, log=lambda *_: None)

    def test_crash_after_finishing_keeps_the_shot(self):
        result = self._render(FAKE_FINISH="1", FAKE_MISSING="0")
        self.assertTrue(result["ok"], result["error"])

    def test_crash_before_finishing_is_an_error(self):
        self.assertFalse(self._render(FAKE_FINISH="0", FAKE_MISSING="0")["ok"])
        self.assertFalse(self._render(FAKE_FINISH="1", FAKE_MISSING="1")["ok"], "falta un cuadro")

    def test_black_frames_are_retried(self):
        """Visto el 2026-10-06: la TV salio negra desde 0.5 s (la GPU fallo a mitad del
        render) y llego al video; repetirlo salio bien."""
        flag = os.path.join(self.tmp, "first_attempt_done")
        result = self._render(FAKE_FINISH="1", FAKE_MISSING="0", FAKE_BLACK_ONCE=flag, FAKE_BLACK="0")
        self.assertTrue(result["ok"], result["error"])
        self.assertTrue(os.path.exists(flag), "no hubo primer intento negro")
        self.assertEqual(bs.black_segments(result["path"]), [])

    def test_always_black_fails_and_never_reaches_the_cache(self):
        result = self._render(FAKE_FINISH="1", FAKE_MISSING="0", FAKE_BLACK="1")
        self.assertFalse(result["ok"])
        self.assertIn("negros", result["error"])
        self.assertEqual([f for f in os.listdir(os.path.join(self.tmp, "cache")) if f.endswith(".mp4")], [])

    def test_black_shot_in_the_cache_is_rendered_again(self):
        good = self._render(FAKE_FINISH="1", FAKE_MISSING="0", FAKE_BLACK="0")
        self.assertTrue(good["ok"])
        # Simula una toma negra cacheada antes de que existiera la validacion.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x112:r=5:d=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", good["path"]], check=True, capture_output=True)
        again = self._render(FAKE_FINISH="1", FAKE_MISSING="0", FAKE_BLACK="0")
        self.assertTrue(again["ok"])
        self.assertFalse(again["cached"], "reuso una toma negra del cache")
        self.assertEqual(bs.black_segments(again["path"]), [])

    def test_parse_black_segments(self):
        log = "[blackdetect @ 0x1] black_start:0.466667 black_end:4.366667 black_duration:3.9"
        self.assertEqual(bs.parse_black_segments(log), [(0.466667, 4.366667)])


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
                     "render real de Blender: RUN_BLENDER_TESTS=1 (tarda ~2 min)")
class TestEveryEnvironmentRenders(unittest.TestCase):
    def test_each_template_produces_its_frames(self):
        from PIL import Image
        tmp = tempfile.mkdtemp(prefix="blender_envs_")
        self.addCleanup(shutil.rmtree, tmp, True)
        imgs = []
        for i, color in enumerate(((180, 120, 60), (60, 120, 180), (90, 160, 90))):
            path = os.path.join(tmp, f"p{i}.png")
            Image.new("RGB", (120, 160), color).save(path)
            imgs.append(path)
        for env in bs.ENVIRONMENTS:
            result = bs.render_shot(env, imgs, duration=0.0, size=(108, 192), fps=5,
                                    cache_dir=tmp, quality="draft", log=lambda *_: None)
            self.assertTrue(result["ok"], f"{env}: {result['error']}")


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
