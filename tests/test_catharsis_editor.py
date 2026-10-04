# -*- coding: utf-8 -*-
"""Guardas del formato Catarsis (catharsis_editor).

2026-09-28: Short vertical sin voz, de impacto: tarjetas de texto, imagenes y musica con
cortes secos al ritmo. En el primer piloto el limitador de destellos fundio el quiebre
(1.7 s de papel en blanco) con la palabra del climax, porque al quiebre le tocaba el cuarto
destello del segundo: ahora un plano largo solo atrasa su corte. Ademas: la duracion total
es exacta, nunca hay mas de 3 destellos por segundo y el ajuste al ritmo no cambia el total.

Efectos: la caida de la musica mueve el quiebre sin cambiar el largo del climax; la secuencia
trae texto sobre imagen, doble exposicion, pantalla dividida e impact frames; con loop el primer
y el ultimo cuadro son iguales; la rampa de velocidad entrega todos sus cuadros.

    .venv\\Scripts\\python.exe test_catharsis_editor.py
"""

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from catharsis import catharsis_editor as ce

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
        cls.clip = cls.tmp / "clip.mp4"
        try:
            subprocess.run([ce._ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=size=320x240:rate=30:duration=4", "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
                            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.clip)], check=True)
        except Exception as exc:
            cls.clip_error = exc

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_un_noticiero_mpeg2_entrelazado_y_anamorfico(self):
        """Noticieros de archivo (Universal): 720x480 con pixeles 8:9 y entrelazados. Se leen a 640x480
        de pantalla (antes salian estirados un 12 %) y desentrelazados (antes, peine en el movimiento)."""
        clip = self.tmp / "newsreel.mpeg"
        try:
            subprocess.run([ce._ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=size=720x480:rate=30000/1001:duration=1", "-vf", "setsar=8/9,setfield=bff",
                            "-c:v", "mpeg2video", "-flags", "+ilme+ildct", "-top", "0", str(clip)], check=True)
        except Exception as exc:
            self.skipTest(f"sin FFmpeg: {exc}")
        info = ce.media_info.__wrapped__(str(clip))
        self.assertEqual((info["width"], info["height"]), (640, 480))
        self.assertTrue(info["interlaced"])
        frames = list(ce.iter_video_frames(clip, 0.2, 3, size=(270, 480)))
        self.assertEqual([f.size for f in frames], [(270, 480)] * 3)

    def test_un_guion_viejo_se_convierte_en_proyecto(self):
        p = ce.normalize_project(SCRIPT, self.tmp, 30)
        self.assertEqual(p["seconds"], 30.0)
        self.assertTrue(all(Path(m["file"]).is_absolute() and m["type"] == "image" for m in p["media"]))
        self.assertEqual(p["cards"]["climax"], ["WHO", "AM", "I"])
        self.assertIn("variants", p["style"])
        archive = ce.normalize_project({"media": [{"file": "newsreel.mpeg"}, {"file": "clip.ogv"}]})
        self.assertEqual([m["type"] for m in archive["media"]], ["video", "video"])   # material de archivo

    def test_la_secuencia_automatica_es_editable(self):
        p = ce.normalize_project(SCRIPT, self.tmp, 30)
        seq = ce.auto_sequence(p)
        self.assertTrue(all({"kind", "seconds", "transition", "motion"} <= set(s) for s in seq))
        self.assertEqual(sum(1 for s in seq if s.get("tag") == "break"), 1)
        self.assertAlmostEqual(sum(s["seconds"] for s in seq), 30, delta=0.5)
        seq[2]["seconds"] = 3.0          # retoque: un plano mas largo
        shots, _ = ce.build_shots(p, seq)
        self.assertAlmostEqual(sum(s.frames for s in shots) / ce.FPS, sum(s["seconds"] for s in seq), delta=0.1)

    def _clip(self) -> Path:
        if not self.clip.exists():
            self.skipTest(f"sin FFmpeg: {getattr(self, 'clip_error', '')}")
        return self.clip

    def test_un_video_con_su_audio_se_oye(self):
        clip = self._clip()
        p = ce.normalize_project(SCRIPT, self.tmp, 20)
        p["media"].append({"file": str(clip), "type": "video", "in": 0.0, "out": 4.0, "audio": True})
        seq = ce.auto_sequence(p)
        loud = [s for s in seq if s["kind"] == "media" and s["media"] == 3 and s["seconds"] >= ce.AUDIO_HOLD]
        self.assertTrue(loud, "el video con audio necesita al menos un plano largo en la subida")
        shots, marks = ce.build_shots(p, seq)
        self.assertTrue(any(s.audio for s in shots))
        from scipy.io import wavfile
        music = self.tmp / "music.wav"
        wavfile.write(music, 22050, (0.3 * np.sin(2 * np.pi * 220 * np.arange(25 * 22050) / 22050) * 32767).astype(np.int16))
        out = ce.render(shots, self.tmp / "out.mp4", music=music, break_span=marks["break"], preview=True)
        info = ce.media_info.__wrapped__(str(out))
        self.assertTrue(info["audio"])
        self.assertAlmostEqual(info["duration"], marks["end"], delta=0.2)
        # la musica sigue despues del ultimo video con audio (sidechaincompress la cortaba ahi)
        pcm = subprocess.run([ce._ffmpeg(), "-loglevel", "error", "-ss", f"{marks['break'][1] + 0.5:.2f}", "-t", "1",
                              "-i", str(out), "-f", "s16le", "-ac", "1", "-"], capture_output=True).stdout
        self.assertGreater(float(np.abs(np.frombuffer(pcm, np.int16)).mean()), 1000)

    def test_el_texto_sobre_un_video_no_lo_congela(self):
        p = ce.normalize_project(SCRIPT, self.tmp, 20)
        p["media"].append({"file": str(self._clip()), "type": "video", "in": 0.0, "out": 4.0})
        shots, _ = ce.build_shots(p, [{"kind": "overlay", "media": 3, "variant": "base", "text": "5:29 a.m.",
                                       "seconds": 1.0}])
        self.assertIsNotNone(shots[0].clip)
        self.assertEqual(shots[0].text_layer.mode, "RGBA")

    def test_la_rampa_entrega_todos_los_cuadros(self):
        frames = list(ce.iter_clip_frames(self._clip(), 0.0, 30, ramp=True))
        self.assertEqual(len(frames), 30)
        self.assertEqual(frames[-1].size, (ce.W, ce.H))

    def test_render_con_diseno_sonoro_y_loop(self):
        self._clip()
        p = ce.normalize_project(SCRIPT, self.tmp, 20)
        shots, marks = ce.build_shots(p, ce.auto_sequence(p))
        self.assertTrue(np.array_equal(np.asarray(shots[0].image), np.asarray(shots[-1].image)))   # loop
        track = ce.sfx_track(shots, marks["end"])
        i = int(marks["break"][1] * ce.SR)
        self.assertGreater(float(np.abs(track[i:i + ce.SR // 4]).max()), 0.3)   # boom al volver la musica
        out = ce.render(shots, self.tmp / "sfx.mp4", break_span=marks["break"], preview=True, sfx=True, loop=True)
        self.assertTrue(ce.media_info.__wrapped__(str(out))["audio"])   # sin musica ni videos: el diseno sonoro
        self.assertFalse(out.with_suffix(".sfx.wav").exists())


class EffectsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for name in ("a.png", "b.png", "c.png"):
            Image.new("RGB", (600, 800), (120, 90, 60)).save(cls.tmp / name)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_la_caida_mueve_el_quiebre_sin_cambiar_el_climax(self):
        _, rise_end, climax_end, break_end = ce._phase_bounds(40, drop=34.0)
        self.assertEqual(break_end, 34.0)
        self.assertAlmostEqual(climax_end - rise_end, (ce.CLIMAX_END - ce.RISE_END) * 40)
        self.assertEqual(ce._phase_bounds(20, drop=11.0), ce._phase_bounds(20))   # la subida quedaria muy corta

    def test_detecta_la_caida_de_la_musica(self):
        if importlib.util.find_spec("librosa") is None:
            self.skipTest("sin librosa")
        from scipy.io import wavfile
        sr = 22050
        t = np.arange(36 * sr) / sr
        wavfile.write(self.tmp / "drop.wav", sr,
                      (np.sin(2 * np.pi * 110 * t) * np.where(t < 26, 0.05, 0.8) * 32767).astype(np.int16))
        _, drop = ce.music_analysis(self.tmp / "drop.wav", 36)
        self.assertAlmostEqual(drop, 26, delta=0.5)

    def test_una_pista_larga_arranca_donde_su_caida_cae_en_el_quiebre(self):
        if importlib.util.find_spec("librosa") is None:
            self.skipTest("sin librosa")
        from scipy.io import wavfile
        sr = 22050
        t = np.arange(120 * sr) / sr
        amp = np.where(t < 5, 0.01, np.where(t < 70, 0.15, 0.8))   # intro casi muda, cuerpo y caida a los 70 s
        wavfile.write(self.tmp / "long.wav", sr, (np.sin(2 * np.pi * 110 * t) * amp * 32767).astype(np.int16))
        start, drop = ce.find_music_start(self.tmp / "long.wav", 30)
        self.assertAlmostEqual(drop, 70, delta=0.5)
        self.assertAlmostEqual(start, 70 - ce.DROP_AT * 30, delta=0.5)
        self.assertAlmostEqual(ce.music_analysis(self.tmp / "long.wav", 30, start)[1], ce.DROP_AT * 30, delta=0.5)
        inputs, _ = ce._audio_graph([], self.tmp / "long.wav", None, 30, 1, music_start=start)
        self.assertEqual(inputs[:2], ["-ss", f"{start:.3f}"])

    def test_la_secuencia_trae_los_efectos(self):
        p = ce.normalize_project(SCRIPT, self.tmp, 40)
        seq = ce.auto_sequence(p, drop=33.0)
        kinds = {s["kind"] for s in seq}
        self.assertTrue({"overlay", "double", "split", "impact"} <= kinds, kinds)
        self.assertEqual((seq[0]["kind"], seq[0]["text"]), ("card", SCRIPT["opening"]))    # loop: empieza y
        self.assertEqual((seq[-1]["kind"], seq[-1]["text"]), ("card", SCRIPT["opening"]))  # termina igual
        brk = next(i for i, s in enumerate(seq) if s.get("tag") == "break")
        self.assertAlmostEqual(sum(s["seconds"] for s in seq[:brk + 1]), 33.0, delta=0.05)
        self.assertAlmostEqual(sum(s["seconds"] for s in seq), 40, delta=0.5)
        shots, _ = ce.build_shots(p, seq)
        self.assertEqual(sum(s.frames for s in shots), 40 * ce.FPS)
        self.assertTrue(any(s.text_layer is not None for s in shots))

    def test_sin_frases_la_subida_es_de_imagenes(self):
        p = ce.normalize_project({"media": SCRIPT["images"], "cards": {"opening": "Who am I?"}}, self.tmp, 30)
        seq = ce.auto_sequence(p)
        climax = sum(s["seconds"] for s in seq if s["act"] == "climax")
        self.assertAlmostEqual(climax, (ce.CLIMAX_END - ce.RISE_END) * 30, delta=0.5)   # no se come la subida
        self.assertGreaterEqual(sum(1 for s in seq if s["act"] == "rise" and s["kind"] == "media"), 3)
        self.assertFalse([s for s in seq if s["kind"] == "card" and not s.get("text") and s["act"] == "rise"])

    def test_sin_efectos_vuelve_al_arco_simple(self):
        p = ce.normalize_project(SCRIPT, self.tmp, 30)
        p["style"].update({k: False for k in ("kinetic", "impact", "double", "split", "ramps", "drop", "loop")})
        seq = ce.auto_sequence(p, drop=25.0)
        self.assertFalse({"overlay", "double", "split", "impact"} & {s["kind"] for s in seq})
        self.assertEqual(seq[0]["kind"], "color")   # sin loop arranca en negro
        self.assertFalse(any(s.get("kinetic") for s in seq))

    def test_un_cuadro_parejo_no_se_estira_hasta_el_ruido(self):
        flat = Image.fromarray(np.random.default_rng(0).integers(225, 245, (96, 54), dtype=np.uint8))
        out = np.asarray(ce.variant(flat.convert("RGB"), "base"), dtype=np.float32)
        self.assertLess(out.std(), 3 * np.asarray(flat, dtype=np.float32).std())   # no aparecen los bloques
        self.assertGreater(out.mean(), 150)                                           # un destello sigue claro

    def test_los_efectos_son_verticales(self):
        img = Image.new("RGB", (ce.W, ce.H), (120, 90, 60))
        for out in (ce.impact_image(img), ce.double_image(img, img), ce.split_image([img, img, img]),
                    ce.bloom(img), ce.grade(img, "climax")):
            self.assertEqual(out.size, (ce.W, ce.H))
        self.assertEqual(ce.overlay_layer("Who am I?").mode, "RGBA")


class CardsTest(unittest.TestCase):
    COMPLETE = json.dumps({
        "direction": {"speaker": "Narrador externo", "moment": "Trinity, 1945",
                      "conflict": "Construccion y consecuencias", "turn": "La prueba",
                      "payoff": "La responsabilidad sigue"},
        "opening": "What follows the first flash?",
        "lines": ["July 16, 1945.", "A desert test.", "Scientists stand back.",
                  "The countdown ends.", "A flash appears.", "The test succeeds.", "The questions remain."],
        "climax": ["BEYOND", "THE", "FLASH"], "final": ["The test ends. Responsibility remains."],
        "end": "Trinity, 1945"})

    def test_reintenta_respuesta_truncada_con_mas_margen(self):
        client = Mock()
        client._generate.side_effect = [None, self.COMPLETE]
        log = Mock()
        with patch('ai.ai_factory.AIFactory.get_instance') as factory:
            factory.return_value.get_llm_client.return_value = client
            cards = ce.write_cards("Trinity", check=False, log=log)
        self.assertEqual(len(cards["lines"]), 7)
        self.assertEqual([c.kwargs for c in client._generate.call_args_list], [
            {"max_tokens": 4096, "task_type": "script_quality"},
            {"max_tokens": 8192, "task_type": "script_quality"},
        ])
        self.assertIn("ENTIRE JSON", client._generate.call_args.args[0])
        self.assertTrue(any("reintentando" in c.args[0] for c in log.call_args_list))

    def test_no_reintenta_una_respuesta_completa(self):
        generate = Mock(return_value=self.COMPLETE)
        ce.write_cards("Trinity", generate_fn=generate, check=False, log=lambda m: None)
        generate.assert_called_once()

    def test_etiqueta_dramatizacion_en_ambos_idiomas_sin_alterar_narrador(self):
        for language, label in (("en", "Dramatization"), ("es", "Dramatización")):
            with self.subTest(language=language):
                cards = ce.write_cards("Trinity", "character", language,
                                       generate_fn=lambda p: self.COMPLETE, check=False, log=lambda m: None)
                self.assertTrue(cards["end"].startswith(label))
                again = ce.write_cards("Trinity", "character", language,
                                       generate_fn=lambda p: json.dumps(cards), check=False, log=lambda m: None)
                self.assertEqual(again["end"], cards["end"])
        narrator = ce.write_cards("Trinity", "narrator", generate_fn=lambda p: self.COMPLETE,
                                  check=False, log=lambda m: None)
        self.assertEqual(narrator["end"], "Trinity, 1945")

    def test_no_acepta_tarjetas_truncadas_ni_campos_inventados_por_defecto(self):
        for raw in (None, "ERROR: token limit", '{"opening": "Who?", "lines": ["July',
                    '{"lines": ["July 16, 1945."]}', '[]',
                    self.COMPLETE.replace('"July 16, 1945."', '{"text": "July"}')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                ce.parse_cards(raw)

    def test_fallo_final_limitado_no_verifica_tarjetas_incompletas(self):
        generate = Mock(return_value=None)
        with patch('ai.script_fact_check.fact_check_scenes') as check:
            with self.assertRaisesRegex(RuntimeError, "tras dos intentos"):
                ce.write_cards("Trinity", generate_fn=generate, log=lambda m: None)
            check.assert_not_called()
        self.assertEqual(generate.call_count, 2)

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
            return self.COMPLETE

        cards = ce.write_cards("Trinity test", "narrator", generate_fn=fake, check=False, log=lambda m: None)
        self.assertIn("Trinity test", seen["prompt"])
        self.assertIn("third person", seen["prompt"])
        self.assertEqual(cards["opening"], "What follows the first flash?")

    def test_verifica_climax_y_firma_sin_reparador_de_narraciones(self):
        def fact_check(texts, topic, **kwargs):
            self.assertEqual(texts[-1], "Trinity, 1945")
            self.assertIn("BEYOND THE FLASH", texts)
            self.assertIs(kwargs["repair"], False)
            fixed = list(texts)
            fixed[1] = "The corrected date."
            return fixed, {"status": "verified", "remaining": []}
        generate = Mock(side_effect=[self.COMPLETE, '{"issues": []}'])
        with patch('ai.script_fact_check.fact_check_scenes', side_effect=fact_check):
            cards = ce.write_cards("Trinity", "narrator", generate_fn=generate, log=lambda m: None)
        self.assertNotIn("The corrected date.", generate.call_args.args[0])
        self.assertEqual(cards["lines"][0], "July 16, 1945.")
        self.assertEqual(cards["fact_check"]["status"], "verified")
        self.assertEqual(cards["narrative_review"]["status"], "reviewed")

    def test_rechazo_editorial_reescribe_y_vuelve_a_verificar(self):
        responses = [self.COMPLETE, '{"issues": ["Opening is disconnected from final"]}',
                     self.COMPLETE, '{"issues": []}']
        generate = Mock(side_effect=responses)
        with patch('ai.script_fact_check.fact_check_scenes', side_effect=lambda texts, *a, **k:
                   (texts, {"status": "verified"})) as check:
            ce.write_cards("Trinity", "narrator", generate_fn=generate, log=lambda m: None)
        self.assertEqual(check.call_count, 2)
        self.assertIn("Opening is disconnected", generate.call_args_list[2].args[0])

    def test_fallo_editorial_no_se_presenta_como_exito(self):
        review = '{"issues": ["Voice changes after death"]}'
        generate = Mock(side_effect=[self.COMPLETE, review, self.COMPLETE, review])
        with patch('ai.script_fact_check.fact_check_scenes', side_effect=lambda texts, *a, **k:
                   (texts, {"status": "verified"})):
            cards = ce.write_cards("Trinity", generate_fn=generate, log=lambda m: None)
        self.assertEqual(cards["narrative_review"]["status"], "needs_review")
        self.assertIn("Voice changes after death", cards["narrative_review"]["issues"])
        self.assertEqual(generate.call_count, 4)

    def test_revision_ilegible_no_aprueba_tarjetas(self):
        generate = Mock(side_effect=[self.COMPLETE, 'ERROR: truncated', 'ERROR: truncated'])
        with patch('ai.script_fact_check.fact_check_scenes', side_effect=lambda texts, *a, **k:
                   (texts, {"status": "verified"})):
            with self.assertRaisesRegex(RuntimeError, 'revision narrativa'):
                ce.write_cards("Trinity", generate_fn=generate, log=lambda m: None)

    def test_reparacion_factual_reescribe_el_arco_con_la_voz_elegida(self):
        reports = iter([{"status": "needs_review", "remaining": [
            {"quote": "July 16, 1945.", "verdict": "false", "correction": "Use the documented date"}]},
                        {"status": "verified"}])
        def fact_check(texts, topic, **kwargs):
            self.assertFalse(kwargs["repair"])
            return texts, next(reports)
        generate = Mock(side_effect=[self.COMPLETE, '{"issues": []}', self.COMPLETE, '{"issues": []}'])
        with patch('ai.script_fact_check.fact_check_scenes', side_effect=fact_check):
            ce.write_cards("Trinity", "character", "es", generate_fn=generate, log=lambda m: None)
        repair_prompt = generate.call_args_list[2].args[0]
        self.assertIn("No foreknowledge", repair_prompt)
        self.assertIn("Use the documented date", repair_prompt)
        self.assertIn("Visible language: Spanish", generate.call_args.args[0])

    def test_rechaza_arco_incompleto_sin_cambiar_tarjetas_manuales(self):
        for change in ({"direction": {}}, {"climax": ["WHO AM I"]}, {"final": []},
                       {"lines": ["Just one card"]}):
            data = json.loads(self.COMPLETE)
            data.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                ce._validate_generated_cards(data)
        legacy = ce.normalize_project(SCRIPT)
        self.assertEqual(legacy["cards"]["climax"], SCRIPT["climax"])


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
