# -*- coding: utf-8 -*-
"""Guardas del tramo con movimiento de los videos (pipeline/video_motion).

BUG (2026-10-06): un clip real del proyecto "El triangulo de las Bermudas" se
movia 2.44 s y repetia el mismo cuadro hasta los 10.64 s. En el video final se
veia un segundo de accion y despues una foto quieta, sin ningun aviso. Otro clip
(un short de junio) tambien se congelaba casi un segundo al final.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
import wave

from pipeline import video_motion as vm

FFMPEG = shutil.which("ffmpeg")

TAIL_LOG = "[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 2.44\n"
MIDDLE_LOG = ("lavfi.freezedetect.freeze_start: 3.0\nlavfi.freezedetect.freeze_duration: 1.0\n"
              "lavfi.freezedetect.freeze_end: 4.0\n")


class TestParsing(unittest.TestCase):
    def test_frozen_until_the_end(self):
        self.assertEqual(vm.parse_freezes(TAIL_LOG), [(2.44, None)])
        self.assertEqual(vm.moving_span(vm.parse_freezes(TAIL_LOG), 10.64), (0.0, 2.44))

    def test_freeze_in_the_middle_keeps_the_longest_part(self):
        self.assertEqual(vm.moving_span(vm.parse_freezes(MIDDLE_LOG), 8.5), (4.0, 8.5))
        self.assertEqual(vm.moving_span([(0.0, 1.5)], 6.0), (1.5, 6.0), "congelado al arrancar")

    def test_input_window(self):
        info = {"duration": 10.64, "start": 0.0, "end": 2.44, "frozen": True, "usable": True}
        start, length, stretch = vm.input_window(info, 4.0)
        self.assertEqual((start, length), (0.0, 2.44))
        self.assertAlmostEqual(stretch, 4.0 / 2.44, places=3)
        healthy = {"duration": 8.0, "start": 0.0, "end": 8.0, "frozen": False, "usable": False}
        self.assertEqual(vm.input_window(healthy, 4.0), (0.0, 4.0, 1.0))
        short = dict(healthy, duration=3.0, end=3.0)
        self.assertAlmostEqual(vm.input_window(short, 4.0)[2], 4.0 / 3.0, places=3)


@unittest.skipUnless(FFMPEG, "ffmpeg no disponible")
class TestFrozenClipEndToEnd(unittest.TestCase):
    """Clip sintetico: 1.5 s de movimiento y 3 s congelado, como el del avion."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="frozen_")
        cls.clip = os.path.join(cls.tmp, "frozen.mp4")
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=1.5",
             "-vf", "tpad=stop_mode=clone:stop_duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             cls.clip], check=True, capture_output=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def _freezes(path, seconds=None):
        limit = ["-t", str(seconds)] if seconds else []
        log = subprocess.run([FFMPEG, "-hide_banner"] + limit + ["-i", path, "-vf",
                              f"freezedetect=n={vm.FREEZE_NOISE}:d={vm.FREEZE_MIN_SECONDS}", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=120).stderr
        return vm.parse_freezes(log)

    def test_analyze_finds_the_moving_part(self):
        info = vm.analyze(self.clip)
        self.assertTrue(info["frozen"])
        self.assertTrue(info["usable"])
        self.assertAlmostEqual(info["end"], 1.5, delta=0.2)

    def test_assembled_scene_never_freezes(self):
        from pipeline.auto_video_generator_v2 import AutoVideoGenerator
        from PIL import Image
        audio = os.path.join(self.tmp, "a.wav")
        with wave.open(audio, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000 * 5)
        still = os.path.join(self.tmp, "still.png")
        Image.new("RGB", (216, 384), (120, 80, 50)).save(still)
        gen = AutoVideoGenerator.__new__(AutoVideoGenerator)
        gen.log = lambda *_: None
        gen._audio_qa = {}
        out = os.path.join(self.tmp, "out.mp4")
        # El video va PRIMERO: al ultimo clip se le aplica un fundido de salida, y
        # un fundido cambia todos los cuadros (taparia el congelamiento).
        ok = gen._assemble_direct_ffmpeg([{"filename": self.clip, "duration": 3.0, "segment_text": "x"},
                                          {"filename": still, "duration": 2.0, "segment_text": "y"}],
                                         audio, out, (216, 384), fps=15,
                                         transition_type="None (Direct Cut)", enable_transition_sfx=False)
        self.assertTrue(ok)
        self.assertEqual(self._freezes(out, seconds=3.0), [], "la escena de video se congela")
        self.assertEqual(len(gen._audio_qa.get("videos_unfrozen") or []), 1, "el QA no lo reporto")


if __name__ == "__main__":
    unittest.main(verbosity=2)
