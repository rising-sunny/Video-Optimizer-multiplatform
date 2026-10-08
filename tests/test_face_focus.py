# -*- coding: utf-8 -*-
"""Guardas del retrato flotante centrado en la cara (pipeline/face_focus).

BUG (2026-10-06): el circulo recortaba a ciegas (arriba al centro). Con un clip real
de un oficial, la cara estaba a la izquierda y el circulo mostraba su hombro.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
import wave

from pipeline import face_focus as ff
from pipeline import segment_layouts as sl

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "face_princip_1914.png")
try:
    import cv2  # noqa: F401
    CV2 = True
except ImportError:
    CV2 = False


class TestFaceBox(unittest.TestCase):
    def test_box_stays_inside_and_contains_the_face(self):
        x0, y0, x1, y1 = ff.face_box((1600, 900), (50, 300, 200, 200))
        self.assertEqual(x0, 0.0, "cara pegada al borde: el cuadrado se corre adentro")
        self.assertLessEqual(x1, 1.0)
        self.assertLessEqual(x0 * 1600, 50)
        self.assertGreaterEqual(x1 * 1600, 250)
        self.assertAlmostEqual((x1 - x0) * 1600, (y1 - y0) * 900, places=3, msg="tiene que ser cuadrado")

    def test_huge_face_uses_the_whole_short_side(self):
        x0, y0, x1, y1 = ff.face_box((400, 500), (0, 0, 400, 400))
        self.assertAlmostEqual((x1 - x0) * 400, 400)


@unittest.skipUnless(CV2 and os.path.exists(FIXTURE), "hace falta opencv y el fixture")
class TestOffCenterFace(unittest.TestCase):
    """La escena del bug: la persona esta a un costado del cuadro."""

    @classmethod
    def setUpClass(cls):
        from PIL import Image
        cls.tmp = tempfile.mkdtemp(prefix="face_focus_")
        canvas = Image.new("RGB", (900, 1600), (128, 128, 128))
        face = Image.open(FIXTURE).convert("RGB").resize((220, 275))
        canvas.paste(face, (10, 200))             # pegada a la izquierda, arriba
        cls.scene = os.path.join(cls.tmp, "scene.png")
        canvas.save(cls.scene)
        cls.empty = os.path.join(cls.tmp, "empty.png")
        Image.new("RGB", (900, 1600), (128, 128, 128)).save(cls.empty)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _inset_spread(self, require_face):
        """Variacion de grises adentro del circulo: ~0 si muestra la pared gris."""
        import numpy as np
        from PIL import Image
        sl.build_layout_graph("pip", main=self.scene, sources=[{"path": self.scene, "detail": sl.DETAIL_CROPS[0]}],
                              duration=1.0, size=(216, 384), fps=10, temp_dir=self.tmp, index=7,
                              require_face=require_face)
        inset = np.asarray(Image.open(os.path.join(self.tmp, "inset_007.png")).convert("L"), dtype="float32")
        c = inset.shape[0] // 2
        r = inset.shape[0] // 5
        return float(inset[c - r:c + r, c - r:c + r].std())

    def test_circle_shows_the_face(self):
        box = ff.portrait_box(self.scene)
        self.assertIsNotNone(box)
        cx, cy = (box[0] + box[2]) / 2 * 900, (box[1] + box[3]) / 2 * 1600
        self.assertTrue(10 <= cx <= 230 and 200 <= cy <= 475, "el centro del circulo no cae en la cara")
        self.assertGreater(self._inset_spread(require_face=True), 20, "el circulo no muestra la cara")

    def test_blind_crop_misses_it(self):
        """Lo que pasaba antes: el recorte fijo cae en la pared gris."""
        self.assertLess(self._inset_spread(require_face=False), 5)

    def test_no_face_raises(self):
        with self.assertRaises(sl.NoFaceFound):
            sl.build_layout_graph("pip", main=self.empty, sources=[{"path": self.empty}], duration=1.0,
                                  size=(216, 384), fps=10, temp_dir=self.tmp, index=8, require_face=True)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg no disponible")
class TestAssemblerFallsBackToPunchIn(unittest.TestCase):
    def test_portrait_without_a_face_goes_as_punch_in(self):
        from PIL import Image
        from pipeline.auto_video_generator_v2 import AutoVideoGenerator
        tmp = tempfile.mkdtemp(prefix="pip_noface_")
        self.addCleanup(shutil.rmtree, tmp, True)
        img = os.path.join(tmp, "wall.png")
        Image.new("RGB", (300, 400), (90, 110, 130)).save(img)
        last = os.path.join(tmp, "last.png")
        Image.new("RGB", (300, 400), (40, 40, 40)).save(last)
        audio = os.path.join(tmp, "a.wav")
        with wave.open(audio, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000 * 4)
        gen = AutoVideoGenerator.__new__(AutoVideoGenerator)
        gen.log = lambda *_: None
        gen._audio_qa = {}
        clips = [{"filename": img, "duration": 2.0, "segment_text": "x",
                  "layout_plan": {"layout": "pip", "reason": "person", "tag": "ADA LOVELACE"},
                  "layout_sources": [{"path": img, "detail": sl.DETAIL_CROPS[0]}]},
                 {"filename": last, "duration": 2.0, "segment_text": "y"}]
        ok = gen._assemble_direct_ffmpeg(clips, audio, os.path.join(tmp, "out.mp4"), (216, 384), fps=15,
                                         transition_type="None (Direct Cut)", enable_transition_sfx=False)
        self.assertTrue(ok)
        if CV2:
            self.assertEqual(gen._audio_qa.get("layouts_rendered"), {"punch_in": 1})
            self.assertEqual(gen._audio_qa.get("pip_without_face"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
