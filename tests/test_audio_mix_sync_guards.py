# -*- coding: utf-8 -*-
"""Guardas de regresion de la cadena de audio/sincronia del ensamblaje.

Cada test corresponde a un bug real que llego a produccion el 2026-08-18 y que
NO fallaba ruidosamente: el video salia, solo que sonaba/sincronizaba mal.

    python .venv/Scripts/python.exe test_audio_mix_sync_guards.py

Los tests que necesitan FFmpeg o pydub se saltean solos si no estan.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from pipeline import audio_mix_utils as amu

try:
    from pydub import AudioSegment
    from pydub.generators import Sine, WhiteNoise
    PYDUB_OK = True
except Exception:
    PYDUB_OK = False

FFMPEG = shutil.which("ffmpeg") or r"C:\ffmpeg-7.1.1-full_build\bin\ffmpeg.exe"
FFMPEG_OK = bool(FFMPEG and os.path.exists(FFMPEG)) or bool(shutil.which("ffmpeg"))


class TestDuckFilterGraph(unittest.TestCase):
    """BUG: el filtergraph reusaba [v] en dos consumidores -> FFmpeg exit -22.

    Fallaba en TODOS los renders y caia al fallback, dejando la musica a la par
    de la voz. Este test corre FFmpeg de verdad: si el grafo vuelve a ser
    invalido, falla aca y no en un video ya publicado.
    """

    @staticmethod
    def _parse_labels(filtergraph):
        """Devuelve (productores, consumidores) por etiqueta del filtergraph."""
        import collections
        import re
        produced = collections.Counter()
        consumed = collections.Counter()
        for chain in filtergraph.split(";"):
            chain = chain.strip()
            if not chain:
                continue
            head = re.match(r"^((?:\[[^\]]+\])+)", chain)
            tail = re.search(r"((?:\[[^\]]+\])+)$", chain)
            body_start = head.end() if head else 0
            for label in re.findall(r"\[([^\]]+)\]", head.group(1) if head else ""):
                consumed[label] += 1
            # el tail solo cuenta como salida si no es tambien el head del chain
            if tail and tail.start() >= body_start:
                for label in re.findall(r"\[([^\]]+)\]", tail.group(1)):
                    produced[label] += 1
        return produced, consumed

    def test_no_label_is_consumed_twice(self):
        """El bug original: [v] alimentaba el sidechain Y el amix a la vez."""
        f = amu.build_duck_filter(4.0, -8.0)
        produced, consumed = self._parse_labels(f)
        for label, count in consumed.items():
            self.assertEqual(
                count, 1,
                f"la etiqueta [{label}] se consume {count} veces; FFmpeg rechaza el "
                f"filtergraph entero (exit -22). Para ramificar hace falta asplit.",
            )
        for label, count in produced.items():
            self.assertEqual(count, 1, f"la etiqueta [{label}] se produce {count} veces")
        # Toda etiqueta intermedia producida se consume (salvo la salida final).
        for label in produced:
            if label != "out":
                self.assertEqual(consumed.get(label, 0), 1, f"[{label}] queda sin conectar")

    def test_filter_keeps_the_pieces_that_matter(self):
        f = amu.build_duck_filter(4.0, -8.0)
        self.assertIn("asplit=2[v_mix][v_key]", f,
                      "la voz alimenta la mezcla Y la llave del sidechain: hace falta asplit")
        self.assertIn("normalize=0", f,
                      "sin normalize=0 amix divide el volumen por la cantidad de entradas")
        self.assertIn("alimiter", f, "hace falta limitador tras amplificar la voz")
        self.assertIn("volume=4.00dB", f)
        self.assertIn("volume=-8.00dB", f)

    @unittest.skipUnless(FFMPEG_OK, "FFmpeg no disponible")
    def test_ffmpeg_accepts_the_graph(self):
        with tempfile.TemporaryDirectory() as td:
            voice = os.path.join(td, "v.wav")
            music = os.path.join(td, "m.wav")
            out = os.path.join(td, "mix.mp3")
            # voz mono 24k y musica estereo 44.1k: los formatos reales no coinciden
            self._synth(voice, "sine=f=300:d=3:r=24000", channels=1)
            self._synth(music, "anoisesrc=d=3:c=pink:r=44100", channels=2)

            gains = amu.compute_mix_gains(-21.0, -18.0)
            proc = subprocess.run(
                [FFMPEG, "-y", "-i", music, "-i", voice,
                 "-filter_complex", amu.build_duck_filter(*gains),
                 "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "2", out],
                capture_output=True,
            )
            self.assertEqual(
                proc.returncode, 0,
                "el filtergraph de auto-ducking es invalido:\n"
                + (proc.stderr or b"").decode("utf-8", "replace")[-600:],
            )
            self.assertTrue(os.path.getsize(out) > 0)

    @staticmethod
    def _synth(path, lavfi, channels):
        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", lavfi, "-ac", str(channels), path],
                       capture_output=True, check=True)


class TestMixGains(unittest.TestCase):
    """BUG: no habia nivelado; la musica masterizada tapaba al TTS."""

    def test_music_lands_below_voice(self):
        voice_gain, music_gain = amu.compute_mix_gains(-21.0, -18.0)
        self.assertAlmostEqual(-21.0 + voice_gain, amu.TARGET_VOICE_DBFS, places=6)
        gap = (-21.0 + voice_gain) - (-18.0 + music_gain)
        self.assertAlmostEqual(gap, amu.MUSIC_UNDER_VOICE_DB, places=6)
        self.assertGreaterEqual(gap, 6.0, "la musica tiene que quedar claramente bajo la voz")

    def test_music_louder_than_voice_gets_pushed_down(self):
        # Caso real: musica -18.1 dBFS contra narracion -20.9 dBFS.
        _, music_gain = amu.compute_mix_gains(-20.9, -18.1)
        self.assertLess(music_gain, 0.0, "una musica mas fuerte que la voz debe bajarse")

    def test_silent_inputs_do_not_explode(self):
        self.assertEqual(amu.compute_mix_gains(float("-inf"), -18.0), (0.0, 0.0))
        self.assertEqual(amu.compute_mix_gains(-20.0, float("-inf"))[1], 0.0)

    @unittest.skipUnless(PYDUB_OK and FFMPEG_OK, "pydub/FFmpeg no disponibles")
    def test_end_to_end_mix_is_voice_forward(self):
        """La mezcla resultante tiene que estar dominada por la voz, no por la musica."""
        with tempfile.TemporaryDirectory() as td:
            # Niveles del caso real: narracion -21 dBFS contra musica -18 dBFS.
            voice_seg = Sine(220).to_audio_segment(duration=3000)
            voice_seg = voice_seg.apply_gain(-21.0 - voice_seg.dBFS)
            music_seg = WhiteNoise().to_audio_segment(duration=3000)
            music_seg = music_seg.apply_gain(-18.0 - music_seg.dBFS)
            voice = os.path.join(td, "v.wav")
            music = os.path.join(td, "m.wav")
            voice_seg.export(voice, format="wav").close()
            music_seg.export(music, format="wav").close()

            gains = amu.compute_mix_gains(voice_seg.dBFS, music_seg.dBFS)
            out = os.path.join(td, "mix.wav")
            proc = subprocess.run(
                [FFMPEG, "-y", "-i", music, "-i", voice,
                 "-filter_complex", amu.build_duck_filter(*gains), "-map", "[out]", out],
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, (proc.stderr or b"").decode("utf-8", "replace")[-400:])

            # Comparar contra una mezcla de solo-musica al mismo tratamiento:
            # el mix tiene que estar cerca del nivel objetivo de la voz.
            with open(out, "rb") as fh:
                mixed = AudioSegment.from_file(fh)
            self.assertGreater(
                mixed.dBFS, amu.TARGET_VOICE_DBFS - 4.0,
                "el mix quedo muy por debajo del nivel de voz objetivo",
            )
            music_only = music_seg.apply_gain(gains[1])
            self.assertGreater(
                mixed.dBFS - music_only.dBFS, 5.0,
                "la musica esta demasiado cerca del nivel del mix: la voz queda tapada",
            )


class TestTransitionSfxGating(unittest.TestCase):
    """BUG: con efectos cinematograficos + Film Burn el swoosh no se inyectaba
    en NINGUNA de las dos rutas de ensamblaje."""

    def test_cinematic_overlay_transition_still_gets_sfx(self):
        # Esta es la combinacion exacta del short que salio sin swoosh.
        self.assertTrue(amu.should_inject_transition_sfx(
            enable_transition_sfx=True, pydub_available=True,
            transition_type="Film Burn (Overlay)", clip_count=9,
            will_use_direct_ffmpeg=False,  # efectos cinematograficos -> ruta MoviePy
        ))

    def test_direct_ffmpeg_path_handles_it_itself(self):
        self.assertFalse(amu.should_inject_transition_sfx(
            True, True, "Film Burn (Overlay)", 9, will_use_direct_ffmpeg=True,
        ), "la ruta rapida ya lo inyecta; inyectarlo dos veces duplica el swoosh")

    def test_respects_user_toggle_and_direct_cut(self):
        self.assertFalse(amu.should_inject_transition_sfx(False, True, "Fade", 9, False))
        self.assertFalse(amu.should_inject_transition_sfx(True, True, "None (Direct Cut)", 9, False))
        self.assertFalse(amu.should_inject_transition_sfx(True, True, "Fade", 1, False))
        self.assertFalse(amu.should_inject_transition_sfx(True, False, "Fade", 9, False))

    def test_plain_transitions_on_moviepy_path(self):
        self.assertTrue(amu.should_inject_transition_sfx(True, True, "Fade", 5, False))


class TestCoverFrameOffset(unittest.TestCase):
    """BUG: el cover frame corria los timestamps de todos los segmentos pero la
    narracion seguia arrancando en 0.0s -> video entero desfasado."""

    def test_offset_from_cover_segment(self):
        segs = [
            {"cover_frame": True, "start": 0.0, "end": 0.7},
            {"start": 0.7, "end": 8.55},
        ]
        self.assertAlmostEqual(amu.compute_cover_offset_seconds(segs), 0.7, places=6)

    def test_no_cover_frame_means_no_offset(self):
        self.assertEqual(amu.compute_cover_offset_seconds([{"start": 0.0, "end": 8.5}]), 0.0)
        self.assertEqual(amu.compute_cover_offset_seconds([]), 0.0)
        self.assertEqual(amu.compute_cover_offset_seconds(None), 0.0)

    def test_malformed_segments_do_not_raise(self):
        self.assertEqual(amu.compute_cover_offset_seconds([{"cover_frame": True}]), 0.0)
        self.assertEqual(amu.compute_cover_offset_seconds([{"cover_frame": True, "end": "x"}]), 0.0)

    @unittest.skipUnless(PYDUB_OK, "pydub no disponible")
    def test_padding_puts_voice_on_the_segment_timeline(self):
        """Padear la voz con el offset alinea narracion, imagenes y subtitulos."""
        segs = [{"cover_frame": True, "start": 0.0, "end": 0.7}, {"start": 0.7, "end": 3.7}]
        offset = amu.compute_cover_offset_seconds(segs)
        narration = Sine(220).to_audio_segment(duration=3000)
        padded = AudioSegment.silent(duration=int(offset * 1000)) + narration
        self.assertAlmostEqual(len(padded) / 1000.0, segs[-1]["end"], places=2)
        self.assertLess(padded[:int(offset * 1000)].dBFS, -50.0, "el arranque debe ser silencio")


class TestWordNormalizationForSubtitles(unittest.TestCase):
    """BUG: los guiones tipograficos de los nombres propios del guion no existen
    en la transcripcion de Whisper, y cada nombre sin anclar obliga a interpolar
    el timing de las palabras que lo rodean."""

    def setUp(self):
        from pipeline.dynamic_subtitles_generator import EmojiMapper
        self.n = EmojiMapper.normalize_word

    def test_typographic_hyphen_matches_whisper(self):
        self.assertEqual(self.n("Shu\u2011Sin"), self.n("Shusin"))
        self.assertEqual(self.n("Muriq\u2011Tidnim"), self.n("MuriqTidnim"))
        self.assertEqual(self.n("Shu-Sin"), self.n("shusin"))

    def test_accents_and_punctuation_still_normalized(self):
        self.assertEqual(self.n("¿Qué?"), self.n("que"))
        self.assertEqual(self.n("wall's"), self.n("walls"))
        self.assertEqual(self.n("2032,"), "2032")

    def test_distinct_words_stay_distinct(self):
        self.assertNotEqual(self.n("wall"), self.n("walls"))
        self.assertNotEqual(self.n("2032"), self.n("2033"))

    def test_spoken_content_detection_survives(self):
        from pipeline.dynamic_subtitles_generator import EmojiMapper
        self.assertTrue(EmojiMapper.has_spoken_content("Shu\u2011Sin"))
        self.assertFalse(EmojiMapper.has_spoken_content("—"))
        self.assertFalse(EmojiMapper.has_spoken_content("..."))


class TestMusicAudibilityBudget(unittest.TestCase):
    """La musica se atenua dos veces: la cama fija y despues el ducking.

    Mirando solo `MUSIC_UNDER_VOICE_DB` la mezcla parece razonable; sumando la
    reduccion del sidechain la musica puede terminar inaudible (fue el caso con
    cama de 10 dB + ratio 8: -26 dB bajo la voz). Este test fija la banda que
    hay que respetar mirando la atenuacion TOTAL.
    """

    def test_bed_between_phrases_is_audible(self):
        # Entre frases no hay ducking: solo la cama.
        self.assertLessEqual(
            amu.MUSIC_UNDER_VOICE_DB, 8.0,
            "cama demasiado baja: entre frases la musica no se va a escuchar",
        )
        self.assertGreaterEqual(
            amu.MUSIC_UNDER_VOICE_DB, 3.0,
            "cama demasiado alta: la musica va a competir con la voz",
        )

    def test_total_attenuation_under_speech_stays_in_band(self):
        under = amu.estimate_ducked_music_under_voice_db()
        self.assertGreaterEqual(
            under, 10.0,
            "la musica tapa la narracion (%.1f dB bajo la voz)" % under,
        )
        self.assertLessEqual(
            under, 20.0,
            "la musica queda inaudible bajo la narracion (%.1f dB bajo la voz)" % under,
        )

    def test_ducking_actually_ducks(self):
        under = amu.estimate_ducked_music_under_voice_db()
        self.assertGreater(
            under, amu.MUSIC_UNDER_VOICE_DB + 3.0,
            "el sidechain no esta bajando la musica de forma apreciable",
        )


class TestCinematicEffectsAreReachable(unittest.TestCase):
    """Los efectos de movimiento (Ken Burns / cinematicos) vivian DENTRO del
    `except MemoryError` del bucle de clips, asi que solo se aplicaban cuando
    cargar la imagen fallaba por memoria: en la practica, nunca. El video salia
    con los stills congelados y el log igual anunciaba "Efectos activados".
    """

    @classmethod
    def setUpClass(cls):
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline/video_assembler.py")
        with open(path, encoding="utf-8") as fh:
            cls.tree = ast.parse(fh.read())
        cls.ast = ast

        cls.func = None
        for node in ast.walk(cls.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "assemble_video_from_prompts":
                cls.func = node
                break

    def _ancestors_of(self, predicate):
        """Devuelve la cadena de ancestros del primer nodo que cumple predicate."""
        ast = self.ast
        stack = [(self.func, [])]
        while stack:
            node, chain = stack.pop()
            if node is not self.func and predicate(node):
                return chain
            for child in ast.iter_child_nodes(node):
                stack.append((child, chain + [node]))
        return None

    def test_function_exists(self):
        self.assertIsNotNone(self.func, "no se encontro assemble_video_from_prompts")

    def test_cinematic_call_is_not_buried_in_an_except_handler(self):
        ast = self.ast

        def is_cinematic_call(node):
            return (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "apply_effects_to_segment"
            )

        chain = self._ancestors_of(is_cinematic_call)
        self.assertIsNotNone(chain, "no se encontro la llamada a apply_effects_to_segment")
        handlers = [n for n in chain if isinstance(n, ast.ExceptHandler)]
        self.assertEqual(
            handlers, [],
            "apply_effects_to_segment quedo dentro de un except: los efectos "
            "solo se aplicarian cuando la carga del clip falle",
        )

    def test_ken_burns_fallback_is_not_buried_either(self):
        ast = self.ast
        target = []

        def find(node, chain):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Name) and child.id == "zoom_intensity":
                    target.append(chain)
                find(child, chain + [child])

        find(self.func, [])
        self.assertTrue(target, "no se encontro el fallback de Ken Burns")
        buried = [c for c in target if any(isinstance(n, ast.ExceptHandler) for n in c)]
        self.assertEqual(
            len(buried), 0,
            "el Ken Burns quedo dentro de un except handler",
        )


class TestPillowMoviepyCompat(unittest.TestCase):
    """moviepy 1.0.3 usa Image.ANTIALIAS, que Pillow >= 10 elimino.

    Sin cv2 instalado el resizer de moviepy ES el de PIL, asi que cada
    clip.resize() levantaba AttributeError. La excepcion se la comia el
    `except Exception` del bucle de clips: sin error en el log, pero con los
    stills congelados.
    """

    def test_alias_exists_after_importing_the_effects_module(self):
        from pipeline import cinematic_effects  # noqa: F401
        from PIL import Image
        self.assertTrue(hasattr(Image, "ANTIALIAS"),
                        "falta el shim: moviepy va a romper en cada resize")

    def test_a_real_moviepy_resize_works(self):
        try:
            import numpy as np
            from pipeline import cinematic_effects  # noqa: F401  (aplica el shim)
            from moviepy.editor import ImageClip
        except Exception as exc:
            self.skipTest("moviepy/numpy no disponibles: %s" % exc)

        img = np.zeros((80, 60, 3), dtype=np.uint8)
        clip = ImageClip(img).set_duration(1.0)
        frame = clip.resize(1.5).get_frame(0.0)
        self.assertEqual(frame.shape[:2], (120, 90))


class TestCameraMovementActuallyMoves(unittest.TestCase):
    """Los paneos eran no-ops y los zooms desbordaban el lienzo.

    `generate_moviepy_resize_lambda` devolvia SOLO la escala y tiraba x/y, asi
    que PAN_* (scale 1.0 -> 1.0) no movia un pixel, y ZOOM_* entregaba un clip
    mas grande que el video, recortado desde la esquina.
    """

    SIZE = (270, 480)  # chico a proposito: el test tiene que ser rapido

    @classmethod
    def setUpClass(cls):
        try:
            import numpy as np
            from pipeline.cinematic_effects import CinematicEffectsEngine, MovementType
            from moviepy.editor import ImageClip
        except Exception as exc:
            raise unittest.SkipTest("moviepy/numpy no disponibles: %s" % exc)

        cls.np = np
        cls.MovementType = MovementType
        rng = np.random.RandomState(7)
        img = rng.randint(0, 255, (cls.SIZE[1], cls.SIZE[0], 3)).astype("uint8")
        cls.engine = CinematicEffectsEngine(video_size=cls.SIZE)
        cls.clip = ImageClip(img).set_duration(4.0)

    def _render(self, movement):
        out = self.engine.apply_effects_to_segment(
            self.clip, segment_text="x", duration=4.0,
            auto_detect=False, force_movement=movement,
        )
        return [out.get_frame(t).astype("float32") for t in (0.0, 2.0, 3.9)]

    def test_every_movement_produces_motion(self):
        np = self.np
        quietos = []
        for movement in self.MovementType:
            if movement == self.MovementType.STATIC:
                continue
            frames = self._render(movement)
            if np.abs(frames[-1] - frames[0]).mean() <= 1.0:
                quietos.append(movement.value)
        self.assertEqual(quietos, [],
                         "movimientos que no mueven nada: %s" % ", ".join(quietos))

    def test_canvas_size_is_preserved(self):
        w, h = self.SIZE
        for movement in self.MovementType:
            frames = self._render(movement)
            for frame in frames:
                self.assertEqual(
                    frame.shape[:2], (h, w),
                    "%s cambia el tamano del lienzo a %s" % (movement.value, frame.shape[:2]),
                )

    def test_no_black_borders(self):
        for movement in self.MovementType:
            for frame in self._render(movement):
                bordes = [frame[0], frame[-1], frame[:, 0], frame[:, -1]]
                self.assertFalse(
                    any(b.max() == 0 for b in bordes),
                    "%s deja una franja negra en el borde" % movement.value,
                )

    def test_static_stays_static(self):
        np = self.np
        frames = self._render(self.MovementType.STATIC)
        self.assertLess(np.abs(frames[-1] - frames[0]).mean(), 0.01)


class TestFfmpegMotionFilter(unittest.TestCase):
    """El Ken Burns ahora lo resuelve FFmpeg (zoompan), no MoviePy.

    Dos trampas que ya nos comimos:
      - la progresion escrita con `in` no avanza en una imagen fija (el efecto
        queda congelado y nada falla);
      - un filtergraph invalido haria caer el clip entero al fallback negro.
    """

    SIZE = (216, 384)   # chico: el test tiene que correr en segundos

    @classmethod
    def setUpClass(cls):
        if not FFMPEG_OK:
            raise unittest.SkipTest("ffmpeg no disponible")
        try:
            import numpy as np
            from PIL import Image
            from pipeline.cinematic_effects import CameraMovement, MovementType
        except Exception as exc:
            raise unittest.SkipTest("dependencias faltantes: %s" % exc)

        cls.np = np
        cls.CameraMovement = CameraMovement
        cls.MovementType = MovementType
        cls.tmp = tempfile.mkdtemp(prefix="motionfx_")
        w, h = cls.SIZE
        rng = np.random.RandomState(11)
        cls.src = os.path.join(cls.tmp, "src.png")
        Image.fromarray(rng.randint(0, 255, (h, w, 3)).astype("uint8")).save(cls.src)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _render(self, movement, frames=45, fps=15):
        w, h = self.SIZE
        pos = self.CameraMovement.calculate_positions(movement, (w, h), 1.2)
        vf = self.CameraMovement.build_ffmpeg_motion_filter(pos, frames, (w, h))
        out = os.path.join(self.tmp, "%s.mp4" % movement.value)
        proc = subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-i", self.src,
             "-t", str(frames / float(fps)), "-vf", "%s,fps=%d" % (vf, fps),
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-r", str(fps), out],
            capture_output=True, text=True,
        )
        return proc, out

    def _frames(self, video, count=6):
        np = self.np
        from PIL import Image
        d = os.path.join(self.tmp, "fr")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        subprocess.run(
            [FFMPEG, "-v", "error", "-i", video, "-vf", "scale=100:-1,format=gray",
             os.path.join(d, "f_%03d.png")],
            check=True, capture_output=True,
        )
        return [np.asarray(Image.open(os.path.join(d, n)), dtype="float32")
                for n in sorted(os.listdir(d))]

    def test_progression_uses_output_frame_counter(self):
        pos = self.CameraMovement.calculate_positions(
            self.MovementType.ZOOM_IN, self.SIZE, 1.2)
        vf = self.CameraMovement.build_ffmpeg_motion_filter(pos, 45, self.SIZE)
        self.assertIn("on/", vf)
        self.assertNotIn("(in/", vf,
                         "usar `in` deja el zoompan congelado en una imagen fija")

    def test_ffmpeg_accepts_every_movement(self):
        for movement in self.MovementType:
            proc, _ = self._render(movement)
            self.assertEqual(
                proc.returncode, 0,
                "filtergraph invalido para %s: %s" % (movement.value, proc.stderr[-300:]),
            )

    def test_movements_actually_move(self):
        np = self.np
        quietos = []
        for movement in self.MovementType:
            if movement == self.MovementType.STATIC:
                continue
            _, out = self._render(movement)
            fr = self._frames(out)
            if np.abs(fr[-1] - fr[0]).mean() <= 1.0:
                quietos.append(movement.value)
        self.assertEqual(quietos, [],
                         "no producen movimiento: %s" % ", ".join(quietos))

    def test_no_black_borders(self):
        np = self.np
        for movement in self.MovementType:
            _, out = self._render(movement)
            for f in self._frames(out):
                bordes = [f[0], f[-1], f[:, 0], f[:, -1]]
                self.assertFalse(
                    any(b.max() == 0 for b in bordes),
                    "%s deja franja negra" % movement.value,
                )

    def test_pan_displacement_matches_the_geometry(self):
        """El paneo tiene que correr los pixeles que dice el recorrido (con clamp)."""
        np = self.np
        w, h = self.SIZE
        movement = self.MovementType.PAN_RIGHT
        pos = self.CameraMovement.calculate_positions(movement, (w, h), 1.2)
        _, out = self._render(movement, frames=45, fps=15)

        fr = self._frames(out)
        escala = fr[0].shape[1] / float(w)
        fila_a = fr[0][fr[0].shape[0] // 2] - fr[0][fr[0].shape[0] // 2].mean()
        fila_b = fr[-1][fr[-1].shape[0] // 2] - fr[-1][fr[-1].shape[0] // 2].mean()
        corr = np.correlate(fila_b, fila_a, mode="full")
        medido = abs(int(np.argmax(corr)) - (len(fila_a) - 1)) / escala

        z = pos["start"]["scale"]
        recorrido = (pos["end"]["x"] - pos["start"]["x"]) * z
        tope = w * (z - 1.0)          # el clamp no deja pasar de aca
        esperado = min(recorrido, tope)
        self.assertAlmostEqual(
            medido, esperado, delta=max(4.0, esperado * 0.15),
            msg="el paneo corrio %.0f px y el recorrido pedia %.0f" % (medido, esperado),
        )


class TestCoverFrameStaysStill(unittest.TestCase):
    """El cover frame es una PLACA DE TEXTO de 0.7s.

    Al mover los efectos a FFmpeg, el zoompan empezo a aplicarse tambien al
    cover: el texto se desplazaba y escalaba en menos de un segundo y se veia
    como un salto. Medido en el MP4: 14.75 de deriva contra 0.03 estando quieto.
    """

    class _Gen:
        DEFAULT_MOTION_ZOOM = 1.08
        _record_audio_qa = staticmethod(lambda *a, **k: None)
        log = staticmethod(lambda *a, **k: None)

    @classmethod
    def setUpClass(cls):
        from pipeline import auto_video_generator_v2 as avg
        cls.avg = avg
        cls.gen = cls._Gen()

    def test_cover_clip_gets_no_camera_move(self):
        vf = self.avg.AutoVideoGenerator._build_motion_filter(
            self.gen, clip_data={"is_cover": True}, frames=21,
                        duration=0.7, size=(1080, 1920),
                        apply_cinematic=True, index=0)
        self.assertIn("z=1", vf)
        self.assertNotIn("on/", vf, "el cover no debe tener progresion de camara")

    def test_normal_clip_still_moves(self):
        vf = self.avg.AutoVideoGenerator._build_motion_filter(
            self.gen, clip_data={"segment_text": "a battle raged"},
                        frames=240, duration=8.0, size=(1080, 1920),
                        apply_cinematic=True, index=1)
        self.assertIn("on/", vf, "un clip normal si debe moverse")


class TestCoverFrameResolvesRelativePaths(unittest.TestCase):
    """Las rutas del storyboard son relativas al proyecto
    ("project_media/segment_001.png"). Sin resolverlas, el cover caia a un
    gradiente oscuro aunque hubiera imagenes perfectamente usables."""

    def setUp(self):
        try:
            from PIL import Image
        except Exception as exc:
            self.skipTest("PIL no disponible: %s" % exc)
        self.tmp = tempfile.mkdtemp(prefix="cover_")
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.proj, "project_media"))
        Image.new("RGB", (400, 700), (120, 40, 30)).save(
            os.path.join(self.proj, "project_media", "seg1.png"))
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.storyboard = {"segments": [{"image_path": "project_media/seg1.png"}]}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _usa_imagen(self, media_base_dir):
        from pipeline.cover_frame_generator import generate_cover_frame
        mensajes = []
        generate_cover_frame(
            topic="x", category="", storyboard=self.storyboard,
            output_dir=self.out, cover_text_override="TEST",
            log_callback=mensajes.append, media_base_dir=media_base_dir,
        )
        texto = " ".join(mensajes)
        return "como base" in texto, texto

    def test_resolves_against_the_project_dir(self):
        ok, texto = self._usa_imagen(self.proj)
        self.assertTrue(ok, "no resolvio la ruta relativa: %s" % texto[-200:])

    def test_without_the_base_dir_it_falls_back(self):
        """Documenta el comportamiento previo: sin base no encuentra nada."""
        ok, _ = self._usa_imagen(None)
        self.assertFalse(ok)


class TestMixSeparationIsMeasured(unittest.TestCase):
    """Guarda de extremo a extremo: MIDE la mezcla, no confia en la formula.

    Los tests de `TestMusicAudibilityBudget` comprueban la ESTIMACION, y por eso
    no detectaron nada cuando la estimacion misma estaba mal: informaba 15.6 dB
    mientras la musica quedaba 25.8 dB bajo la voz (inaudible) y el QA decia
    "banda sana". Este test renderiza con FFmpeg y mide el resultado.
    """

    @classmethod
    def setUpClass(cls):
        if not (FFMPEG_OK and PYDUB_OK):
            raise unittest.SkipTest("hacen falta ffmpeg y pydub")
        try:
            import numpy as np
        except Exception as exc:
            raise unittest.SkipTest("numpy no disponible: %s" % exc)
        cls.np = np
        cls.tmp = tempfile.mkdtemp(prefix="mixsep_")

        # Voz sintetica: rafagas con pausas, como una narracion real.
        voz = AudioSegment.silent(duration=0)
        for i in range(8):
            # Amplitud variable: la voz real no es plana, y con una senoide
            # constante el percentil iguala al maximo y no selecciona nada.
            tono = Sine(180).to_audio_segment(duration=900).apply_gain(-14 - (i % 4) * 2)
            voz += tono + AudioSegment.silent(duration=350)
        cls.voz_path = os.path.join(cls.tmp, "voz.wav")
        voz.export(cls.voz_path, format="wav")

        # Musica: continua, sin pausas.
        musica = WhiteNoise().to_audio_segment(duration=len(voz)).apply_gain(-18)
        cls.mus_path = os.path.join(cls.tmp, "mus.wav")
        musica.export(cls.mus_path, format="wav")

        cls.voz, cls.mus = voz, musica

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _envolvente(self, path, gain_db=0.0):
        import wave
        np = self.np
        with wave.open(path) as w:
            a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            if w.getnchannels() == 2:
                a = a.reshape(-1, 2).mean(axis=1)
            sr = w.getframerate()
        a = a.astype("float32") / 32768 * (10 ** (gain_db / 20))
        win = int(0.1 * sr)
        return np.array([np.sqrt((a[i:i + win] ** 2).mean() + 1e-12)
                         for i in range(0, len(a) - win, win)])

    def _render(self, filtro, etiqueta, nombre):
        out = os.path.join(self.tmp, nombre)
        proc = subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-i", self.mus_path, "-i", self.voz_path,
             "-filter_complex", filtro, "-map", etiqueta, out],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        return out

    def test_music_sits_in_the_audible_band_under_speech(self):
        np = self.np
        nv = amu.speech_level_dbfs(self.voz)
        nm = amu.music_level_dbfs(self.mus)
        vg, mg = amu.compute_mix_gains(nv, nm)

        cama = self._render(f"[0:a]volume={mg:.2f}dB[m]", "[m]", "cama.wav")
        duck = self._render(
            f"[1:a]volume={vg:.2f}dB[k];[0:a]volume={mg:.2f}dB[m];"
            f"[m][k]sidechaincompress=threshold={amu.DUCK_THRESHOLD}:"
            f"ratio={amu.DUCK_RATIO}:attack={amu.DUCK_ATTACK_MS}:"
            f"release={amu.DUCK_RELEASE_MS}[d]", "[d]", "duck.wav")

        e_voz = self._envolvente(self.voz_path, vg)
        e_cama = self._envolvente(cama)
        e_duck = self._envolvente(duck)
        n = min(len(e_voz), len(e_cama), len(e_duck))
        hablando = e_voz[:n] >= np.percentile(e_voz[:n], 65)

        db = lambda x: 20 * np.log10(max(float(x), 1e-9))
        separacion = db(np.median(e_voz[:n][hablando])) - db(np.median(e_duck[:n][hablando]))

        self.assertGreater(separacion, 8.0,
                           "la musica tapa la voz (%.1f dB de separacion)" % separacion)
        self.assertLess(separacion, 22.0,
                        "la musica queda inaudible (%.1f dB bajo la voz)" % separacion)

    def test_the_estimate_is_close_to_what_gets_rendered(self):
        """La estimacion que imprime el QA tiene que parecerse a la realidad.

        Antes erraba por 10 dB y el log daba por buena una mezcla inaudible.
        """
        np = self.np
        nv = amu.speech_level_dbfs(self.voz)
        nm = amu.music_level_dbfs(self.mus)
        vg, mg = amu.compute_mix_gains(nv, nm)
        cama = self._render(f"[0:a]volume={mg:.2f}dB[m]", "[m]", "cama2.wav")
        duck = self._render(
            f"[1:a]volume={vg:.2f}dB[k];[0:a]volume={mg:.2f}dB[m];"
            f"[m][k]sidechaincompress=threshold={amu.DUCK_THRESHOLD}:"
            f"ratio={amu.DUCK_RATIO}:attack={amu.DUCK_ATTACK_MS}:"
            f"release={amu.DUCK_RELEASE_MS}[d]", "[d]", "duck2.wav")

        e_voz = self._envolvente(self.voz_path, vg)
        e_cama = self._envolvente(cama)
        e_duck = self._envolvente(duck)
        n = min(len(e_voz), len(e_cama), len(e_duck))
        hablando = e_voz[:n] >= np.percentile(e_voz[:n], 65)
        db = lambda x: 20 * np.log10(max(float(x), 1e-9))

        medido = db(np.median(e_voz[:n][hablando])) - db(np.median(e_duck[:n][hablando]))
        estimado = amu.estimate_ducked_music_under_voice_db()
        self.assertLess(
            abs(medido - estimado), 7.0,
            "el QA informa %.1f dB pero se renderiza %.1f dB" % (estimado, medido),
        )


class TestTransitionSfxPositions(unittest.TestCase):
    """BUG (2026-09-01): el video salio sin un solo swoosh.

    Dos fallas encadenadas, las dos silenciosas:
      1. la mezcla se hacia con pydub y `export()` a un mp3 intermedio reventaba
         con [Errno 22]; el `except` lo degradaba a un [WARN];
      2. la ruta rapida de FFmpeg -- la que se usa por defecto -- nunca nivelaba
         el swoosh, asi que aun mezclandolo quedaba enterrado.
    """

    def test_film_burn_pone_el_swoosh_al_inicio_del_clip_entrante(self):
        # Film Burn se MEZCLA sobre el clip que arranca escena: el corte esta
        # en el inicio de ese clip, no en un clip de overlay intermedio.
        pos = amu.compute_transition_sfx_positions(
            [2.0, 3.0, 4.0, 5.0], escenas_nuevas=[1, 2, 3])
        self.assertEqual(pos, [2.0, 5.0, 9.0])

    def test_el_pico_del_swoosh_cae_en_el_corte_no_su_inicio(self):
        # El archivo dura 4s y arranca con build-up: si se alinea el INICIO, el
        # golpe suena ~0.66s despues del corte.
        pos = amu.compute_transition_sfx_positions(
            [2.0, 3.0], escenas_nuevas=[1], peak_offset_s=0.66)
        self.assertAlmostEqual(pos[0], 1.34, places=3)

    def test_no_se_agenda_un_swoosh_fuera_de_la_pista(self):
        pos = amu.compute_transition_sfx_positions(
            [2.0, 3.0, 4.0], escenas_nuevas=[1, 2], total_duration_s=4.0)
        self.assertEqual(pos, [2.0])

    def test_dos_cortes_en_el_mismo_instante_no_suman_dos_swooshes(self):
        pos = amu.compute_transition_sfx_positions(
            [2.0, 0.0, 3.0], escenas_nuevas=[1, 2])
        self.assertEqual(pos, [2.0])

    def test_crossfade_descuenta_lo_que_se_come_cada_transicion(self):
        pos = amu.compute_transition_sfx_positions(
            [4.0, 4.0, 4.0], transition_duration=1.0, created_count=3)
        # corte 1: 4 - 1 = 3, pico a 3.5 | corte 2: 8 - 2 = 6, pico a 6.5
        self.assertEqual(pos, [3.5, 6.5])

    def test_sin_cortes_no_se_arma_filtro(self):
        # Devolver un filtergraph vacio es lo que deja al llamador muxear sin
        # SFX en vez de pasarle a FFmpeg un grafo invalido.
        self.assertEqual(amu.build_transition_sfx_filter([]), "")


class TestTransitionSfxLevels(unittest.TestCase):
    """El nivelado del swoosh: el bug era que la ruta rapida no lo hacia."""

    def test_el_swoosh_se_nivela_por_pico_bajo_el_maestro(self):
        g = amu.compute_sfx_gain_db(master_peak_dbfs=-0.3, sfx_peak_dbfs=-2.0)
        # referencia = -0.3 - 3 (headroom) = -3.3 ; objetivo = -3.3 - 6 = -9.3
        self.assertAlmostEqual(g, -9.3 - (-2.0), places=2)

    def test_la_referencia_deja_aire_bajo_el_limitador(self):
        # Sin headroom el maestro entra pegado al techo y el alimiter se come el
        # swoosh: medido, la mezcla quedaba 1 dB MAS BAJA en el corte.
        con = amu.compute_sfx_gain_db(-0.3, -2.0)
        sin = amu.compute_sfx_gain_db(-0.3, -2.0, master_headroom_db=0.0)
        self.assertLess(con, sin)
        self.assertAlmostEqual(sin - con, abs(amu.SFX_MASTER_HEADROOM_DB), places=2)

    def test_silencio_no_dispara_ganancias_absurdas(self):
        self.assertEqual(amu.compute_sfx_gain_db(float("-inf"), -2.0), 0.0)
        self.assertEqual(amu.compute_sfx_gain_db(-0.3, float("-inf")), 0.0)


class TestTransitionSfxFilterGraph(unittest.TestCase):
    """El filtergraph del swoosh tiene que ser valido para FFmpeg de verdad.

    Mismo tipo de guarda que `TestDuckFilterGraph`: reusar una etiqueta en dos
    consumidores tira exit -22 y el swoosh desaparece sin que nadie se entere.
    """

    def test_cada_etiqueta_se_produce_y_consume_una_sola_vez(self):
        graph = amu.build_transition_sfx_filter([1.0, 2.0, 3.0], gain_db=-7.0)
        produced, consumed = TestDuckFilterGraph._parse_labels(graph)
        for label, veces in consumed.items():
            if label.endswith(":a"):  # entradas del comando, no del grafo
                continue
            self.assertEqual(produced[label], 1,
                             "la etiqueta [%s] no se produce exactamente 1 vez" % label)
        for label, veces in produced.items():
            if label == "aout":
                continue
            self.assertEqual(consumed[label], 1,
                             "la etiqueta [%s] se consume %d veces" % (label, veces))

    def test_el_maestro_manda_la_duracion(self):
        # duration=first: si manda el ultimo swoosh, la mezcla se alarga o se
        # corta respecto del video.
        graph = amu.build_transition_sfx_filter([1.0, 2.0])
        self.assertIn("duration=first", graph)
        self.assertIn("normalize=0", graph)

    def test_formato_explicito_en_las_dos_ramas(self):
        # Maestro mono 24 kHz vs swoosh estereo 48 kHz: depender de la
        # negociacion automatica de FFmpeg es justo lo que falla en silencio.
        graph = amu.build_transition_sfx_filter([1.0])
        self.assertEqual(graph.count("aformat="), 2)

    @unittest.skipUnless(FFMPEG_OK and PYDUB_OK, "requiere FFmpeg y pydub")
    def test_ffmpeg_acepta_el_grafo_y_el_swoosh_se_oye(self):
        """Render real: el swoosh tiene que SUMAR nivel en el corte.

        Se compara contra la MISMA cadena sin swoosh (mismo headroom, mismo
        limitador). Comparar contra el maestro crudo mezclaba el efecto del
        limitador con el del swoosh y daba negativo aun estando bien.
        """
        tmp = tempfile.mkdtemp(prefix="sfxmix_")
        try:
            maestro = os.path.join(tmp, "maestro.wav")
            swoosh = os.path.join(tmp, "swoosh.wav")
            # Maestro: tono continuo fuerte (peor caso, sin huecos donde colar
            # el swoosh). Swoosh: rafaga corta de ruido.
            Sine(220).to_audio_segment(duration=8000).apply_gain(-3).export(
                maestro, format="wav")
            (AudioSegment.silent(duration=100)
             + WhiteNoise().to_audio_segment(duration=200).apply_gain(-1)
             + AudioSegment.silent(duration=100)).export(swoosh, format="wav")

            m = AudioSegment.from_file(maestro)
            s = AudioSegment.from_file(swoosh)
            pos = [2.0, 5.0]
            gain = amu.compute_sfx_gain_db(m.max_dBFS, s.max_dBFS)
            graph = amu.build_transition_sfx_filter(pos, gain_db=gain)

            def render(nombre, filtro, entradas):
                out = os.path.join(tmp, nombre)
                cmd = [FFMPEG, "-y", "-i", maestro, "-i", maestro]
                if entradas > 2:
                    cmd += ["-i", swoosh]
                cmd += ["-filter_complex", filtro, "-map", "[aout]",
                        "-c:a", "pcm_s16le", out]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                self.assertEqual(r.returncode, 0,
                                 "FFmpeg rechazo el grafo:\n%s" % (r.stderr or "")[-1200:])
                return AudioSegment.from_file(out)

            sin_sfx = render(
                "sin.wav",
                "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:"
                "channel_layouts=stereo,"
                f"volume={amu.SFX_MASTER_HEADROOM_DB:.2f}dB[m];"
                "[m]alimiter=limit=0.95[aout]", 2)
            con_sfx = render("con.wav", graph, 3)

            self.assertAlmostEqual(len(con_sfx) / 1000.0, len(m) / 1000.0, delta=0.2,
                                   msg="la mezcla no dura lo mismo que el maestro")

            # El pico del ruido esta ~0.2s dentro del archivo de swoosh; se mide
            # una ventana generosa alrededor de cada corte.
            for p in pos:
                ini = max(0, int(p * 1000) - 50)
                fin = ini + 500
                a = sin_sfx[ini:fin].max_dBFS
                b = con_sfx[ini:fin].max_dBFS
                self.assertGreater(
                    b - a, 1.0,
                    "en el corte %.2fs el swoosh aporta solo %+.2f dB "
                    "(sin=%.2f con=%.2f): no se oye" % (p, b - a, a, b))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
