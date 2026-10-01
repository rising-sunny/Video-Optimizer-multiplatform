import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from pipeline import cinematic_director as director


def _storyboard():
    return {
        "opening": {"style": "artifact_reveal_v1"},
        "segments": [
            {"text": "A carved artifact emerged from the ancient tomb.", "sfx_tag": "stone scrape"},
            {"text": "The city expanded quietly along the coast.", "sfx_tag": "none"},
            {"text": "A hidden document changed the investigation.", "sfx_tag": "none"},
            {"text": "The battle and fire destroyed the northern gate.", "sfx_tag": "battle"},
            {"text": "The ruins remained in silence.", "sfx_tag": "none"},
        ],
    }


class CinematicDirectionPlans(unittest.TestCase):
    def test_level_names_are_normalized(self):
        self.assertEqual(director.normalize_cinematic_level("Epico"), "epic")
        self.assertEqual(director.normalize_cinematic_level("Cinematografico"), "cinematic")
        self.assertEqual(director.normalize_cinematic_level("desconocido"), "auto")

    def test_direction_is_stable_and_serializable(self):
        first = _storyboard()
        second = _storyboard()
        summary_a = director.direct_storyboard(first, level="epic", preset="action")
        summary_b = director.direct_storyboard(second, level="epic", preset="action")
        self.assertEqual(first["segments"], second["segments"])
        self.assertEqual(summary_a, summary_b)
        self.assertEqual(first["segments"][0]["cinematic_plan"]["camera"], "macro_reveal")
        self.assertEqual(first["segments"][3]["cinematic_plan"]["atmosphere"], "embers")
        for segment in first["segments"]:
            plan = segment["cinematic_plan"]
            self.assertEqual(plan["version"], director.DIRECTOR_VERSION)
            self.assertTrue(0 <= plan["intensity"] <= 1)
            self.assertTrue({"camera", "atmosphere", "lighting", "lens", "sound"} <= set(plan))

    def test_locked_manual_plan_survives_redirection(self):
        storyboard = _storyboard()
        manual = {
            "version": director.DIRECTOR_VERSION,
            "camera": "pull_back",
            "atmosphere": "mist",
            "lighting": "none",
            "lens": "clean",
            "sound": "none",
            "intensity": 0.2,
            "locked": True,
        }
        storyboard["segments"][1]["cinematic_plan"] = manual.copy()
        director.direct_storyboard(storyboard, level="epic")
        self.assertEqual(storyboard["segments"][1]["cinematic_plan"], manual)

    def test_subtle_mode_avoids_heavy_atmosphere_on_bridges(self):
        storyboard = _storyboard()
        director.direct_storyboard(storyboard, level="subtle")
        bridge = storyboard["segments"][1]["cinematic_plan"]
        self.assertEqual(bridge["role"], "bridge")
        self.assertEqual(bridge["atmosphere"], "none")
        self.assertEqual(bridge["lens"], "clean")


class FFmpegDirectionFilters(unittest.TestCase):
    def test_camera_uses_the_output_frame_counter(self):
        plan = {"camera": "map_dive", "intensity": 0.9, "lens": "lens_breathing"}
        vf = director.build_ffmpeg_motion_filter(plan, 30, (320, 180))
        self.assertIn("on/29", vf)
        self.assertNotIn("(in/", vf)
        self.assertIn("zoompan", vf)

    def test_installed_ffmpeg_accepts_all_directed_looks(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg no disponible")
        storyboard = _storyboard()
        director.direct_storyboard(storyboard, level="epic", preset="action")
        for segment in storyboard["segments"]:
            plan = segment["cinematic_plan"]
            motion = director.build_ffmpeg_motion_filter(plan, 6, (160, 90))
            look = director.build_ffmpeg_look_filter(plan, 0.4, "action")
            vf = f"fps=15,{motion},fps=15"
            if look:
                vf += f",{look}"
            result = subprocess.run(
                [
                    ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                    "color=c=#4b5864:s=160x90:r=15:d=0.4",
                    "-vf", vf, "-frames:v", "6", "-f", "null", "-",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class TimelineDirectionEditor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_manual_direction_is_saved_and_locked(self):
        from timeline_segment_editor import SegmentEditor
        editor = SegmentEditor()
        saved = []
        editor.saved.connect(saved.append)
        segment = _storyboard()["segments"][0]
        segment["start"] = 0.0
        segment["end"] = 4.0
        segment["visual_prompt"] = "artifact on a stone table"
        segment["assigned_filename"] = "segment_001"
        segment["cinematic_plan"] = director.build_cinematic_plan(
            segment, index=0, count=5, level="cinematic",
            opening_style="artifact_reveal_v1",
        )
        editor.load_segment(segment)
        index = editor.cinematic_camera_combo.findData("crash_zoom")
        editor.cinematic_camera_combo.setCurrentIndex(index)
        editor.cinematic_intensity_spin.setValue(0.85)
        editor.save_changes()
        plan = saved[-1]["cinematic_plan"]
        self.assertEqual(plan["camera"], "crash_zoom")
        self.assertEqual(plan["intensity"], 0.85)
        self.assertTrue(plan["locked"])


class DirectRenderIntegration(unittest.TestCase):
    def test_direct_ffmpeg_exports_directed_video_with_audio(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe no disponible")
        from PIL import Image
        from pipeline.auto_video_generator_v2 import AutoVideoGenerator

        with tempfile.TemporaryDirectory(prefix="cinematic_render_") as temp:
            root = Path(temp)
            image_a = root / "a.png"
            image_b = root / "b.png"
            Image.new("RGB", (320, 180), (72, 88, 108)).save(image_a)
            Image.new("RGB", (320, 180), (112, 62, 42)).save(image_b)
            audio = root / "voice.wav"
            with wave.open(str(audio), "wb") as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b"\x00\x00\x00\x00" * 44100 * 2)

            clips = []
            for index, (path, text) in enumerate(((image_a, "ancient artifact"), (image_b, "battle fire"))):
                segment = {"text": text, "sfx_tag": "none"}
                plan = director.build_cinematic_plan(
                    segment, index=index, count=2, level="epic",
                    opening_style="artifact_reveal_v1",
                )
                clips.append({
                    "filename": str(path),
                    "timestamp_start": float(index),
                    "duration": 1.0,
                    "segment_text": text,
                    "cinematic_plan": plan,
                })

            generator = AutoVideoGenerator.__new__(AutoVideoGenerator)
            generator.log = lambda _message: None
            generator._audio_qa = {}
            output = root / "directed.mp4"
            ok = generator._assemble_direct_ffmpeg(
                clips,
                str(audio),
                str(output),
                (320, 180),
                fps=15,
                transition_type="None (Direct Cut)",
                enable_transition_sfx=False,
                apply_cinematic=True,
                cinematic_preset="action",
            )
            self.assertTrue(ok)
            self.assertGreater(output.stat().st_size, 1000)
            probe = subprocess.run(
                [
                    shutil.which("ffprobe"), "-v", "error", "-show_entries",
                    "stream=codec_type", "-of", "csv=p=0", str(output),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            streams = set(probe.stdout.split())
            self.assertEqual(streams, {"video", "audio"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
