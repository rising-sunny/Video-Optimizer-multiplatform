# -*- coding: utf-8 -*-
"""Guardas del formato Catarsis (catharsis_editor).

2026-09-28: Short vertical sin voz, de impacto: tarjetas de texto, imagenes y musica con
cortes secos al ritmo. En el primer piloto el limitador de destellos fundio el quiebre
(1.7 s de papel en blanco) con la palabra del climax, porque al quiebre le tocaba el cuarto
destello del segundo: ahora un plano largo solo atrasa su corte. Ademas: la duracion total
es exacta, nunca hay mas de 3 destellos por segundo y el ajuste al ritmo no cambia el total.

    .venv\\Scripts\\python.exe test_catharsis_editor.py
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import catharsis_editor as ce

SCRIPT = {
    "images": [{"file": "a.png"}, {"file": "b.png", "focus": [0.3, 0.6], "zoom": 2.0}, {"file": "c.png"}],
    "opening": "Who am I?",
    "lines": ["July 16, 1945.", "A few people laughed.", "A few people cried.", "Most people were silent.",
              "What did I build?", "Who am I now?"],
    "climax": ["WHO", "AM", "I"],
    "final": ["Now I am become Death,", "the destroyer of worlds."],
    "end": "J. Robert Oppenheimer, recalling Trinity (1965)",
}


def _flash_frames(shots):
    """Cuadros donde hay un destello, con el mismo criterio que el limitador."""
    luma = lambda img: float(np.asarray(img.convert("L").resize((54, 96))).mean())  # noqa: E731
    frames, frame = [], 0
    for prev, shot in zip(shots, shots[1:]):
        frame += prev.frames
        if abs(luma(shot.image) - luma(prev.image)) >= ce.FLASH_DELTA or shot.red or prev.red:
            frames.append(frame)
    return frames


class CatharsisPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        rng = np.random.default_rng(1)
        for name, size in (("a.png", (500, 700)), ("b.png", (1600, 900)), ("c.png", (900, 650))):
            Image.fromarray(rng.integers(0, 255, (size[1], size[0]), dtype=np.uint8)).save(cls.tmp / name)
        cls.shots, cls.marks = ce.plan(SCRIPT, cls.tmp, 30)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_duracion_exacta(self):
        self.assertEqual(sum(s.frames for s in self.shots), 30 * ce.FPS)
        self.assertTrue(all(s.frames >= 1 for s in self.shots))

    def test_el_quiebre_sobrevive_al_limitador(self):
        start, end = self.marks["break"]
        self.assertAlmostEqual(end - start, (ce.BREAK_END - ce.CLIMAX_END) * 30, delta=0.5)
        breaks = [s for s in self.shots if s.tag == "break"]
        self.assertEqual(len(breaks), 1)

    def test_nunca_mas_de_tres_destellos_por_segundo(self):
        flashes = _flash_frames(self.shots)
        for i, f in enumerate(flashes):
            window = [x for x in flashes[i:] if x - f < ce.FPS]
            self.assertLessEqual(len(window), ce.MAX_FLASHES_PER_SECOND, f"cuadro {f}")

    def test_todas_las_tarjetas_son_verticales(self):
        for style in ("center", "left", "invert", "red", "word", "caption"):
            self.assertEqual(ce.text_card("Who am I?", style).size, (ce.W, ce.H), style)


class ProjectAndSequenceTest(unittest.TestCase):
    """La pestana Catarsis trabaja con un proyecto y una secuencia de planos editable."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for name in ("a.png", "b.png", "c.png"):
            Image.new("L", (600, 800), 90).save(cls.tmp / name)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_un_guion_viejo_se_convierte_en_proyecto(self):
        p = ce.normalize_project(SCRIPT, self.tmp, 30)
        self.assertEqual(p["seconds"], 30.0)
        self.assertTrue(all(Path(m["file"]).is_absolute() and m["type"] == "image" for m in p["media"]))
        self.assertEqual(p["cards"]["climax"], ["WHO", "AM", "I"])
        self.assertIn("variants", p["style"])

    def test_la_secuencia_automatica_es_editable(self):
        p = ce.normalize_project(SCRIPT, self.tmp, 30)
        seq = ce.auto_sequence(p)
        self.assertTrue(all({"kind", "seconds", "transition", "motion"} <= set(s) for s in seq))
        self.assertEqual(sum(1 for s in seq if s.get("tag") == "break"), 1)
        self.assertAlmostEqual(sum(s["seconds"] for s in seq), 30, delta=0.5)
        seq[2]["seconds"] = 3.0          # retoque: un plano mas largo
        shots, _ = ce.build_shots(p, seq)
        self.assertAlmostEqual(sum(s.frames for s in shots) / ce.FPS, sum(s["seconds"] for s in seq), delta=0.1)

    def test_un_video_con_su_audio_se_oye(self):
        try:
            ffmpeg = ce._ffmpeg()
            clip = self.tmp / "clip.mp4"
            subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=4",
                            "-f", "lavfi", "-i", "sine=frequency=330:duration=4", "-shortest", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
        except Exception as exc:
            self.skipTest(f"sin FFmpeg: {exc}")
        p = ce.normalize_project(SCRIPT, self.tmp, 20)
        p["media"].append({"file": str(clip), "type": "video", "in": 0.0, "out": 4.0, "audio": True})
        seq = ce.auto_sequence(p)
        loud = [s for s in seq if s["kind"] == "media" and s["media"] == 3 and s["seconds"] >= ce.AUDIO_HOLD]
        self.assertTrue(loud, "el video con audio necesita al menos un plano largo en la subida")
        shots, marks = ce.build_shots(p, seq)
        self.assertTrue(any(s.audio for s in shots))
        out = ce.render(shots, self.tmp / "out.mp4", break_span=marks["break"], preview=True)
        info = ce.media_info.__wrapped__(str(out))
        self.assertTrue(info["audio"])
        self.assertAlmostEqual(info["duration"], marks["end"], delta=0.2)


class CardsTest(unittest.TestCase):
    def test_lee_respuestas_desordenadas_del_modelo(self):
        raw = ('Here you go:\n```json\n{"opening": "Who am I?", "lines": ["July 16, 1945.", "What did I build?",],'
               ' "climax": ["who", "am", "i"], "final": ["Now I am become Death,"], "end": "Oppenheimer (1965)"}\n```')
        cards = ce.parse_cards(raw)
        self.assertEqual(cards["lines"], ["July 16, 1945.", "What did I build?"])
        self.assertEqual(cards["climax"], ["WHO", "AM", "I"])

    def test_el_pedido_lleva_tema_y_voz(self):
        seen = {}

        def fake(prompt):
            seen["prompt"] = prompt
            return '{"opening": "Who was he?", "lines": ["July 16, 1945."], "climax": ["WHO"], "final": [], "end": ""}'

        cards = ce.write_cards("Trinity test", "narrator", generate_fn=fake, check=False, log=lambda m: None)
        self.assertIn("Trinity test", seen["prompt"])
        self.assertIn("third person", seen["prompt"])
        self.assertEqual(cards["opening"], "Who was he?")


class LimitFlashesTest(unittest.TestCase):
    def test_un_plano_largo_atrasa_su_corte_en_vez_de_desaparecer(self):
        black = Image.new("RGB", (ce.W, ce.H), (0, 0, 0))
        red = Image.new("RGB", (ce.W, ce.H), ce.RED)
        white = Image.new("RGB", (ce.W, ce.H), ce.PAPER)
        # negro/rojo cada 3 cuadros: el quiebre llega como cuarto destello del mismo segundo
        strobe = [ce.Shot(3, red, red=True) if i % 2 else ce.Shot(3, black) for i in range(5)]
        out = ce.limit_flashes(strobe + [ce.Shot(50, white, tag="break")])
        self.assertEqual(sum(s.frames for s in out), 3 * 5 + 50)
        self.assertEqual(out[-1].tag, "break")
        self.assertEqual(out[-1].frames, 32)   # el corte se atraso 18 cuadros; no desaparecio

    def test_el_ajuste_al_ritmo_no_cambia_el_total(self):
        durations = [1.0, 1.0, 1.0]
        snapped = ce._snap_cuts(durations, 10.0, beats=[11.1, 11.9])
        self.assertAlmostEqual(sum(snapped), 3.0, places=6)
        self.assertAlmostEqual(10.0 + snapped[0], 11.1, places=6)


if __name__ == "__main__":
    unittest.main()
