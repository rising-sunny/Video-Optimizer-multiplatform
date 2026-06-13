import unittest
from pathlib import Path

from storyboard_generator import StoryboardGenerator


class FakeEdgeTTS:
    def __init__(self, failed_scenes=None):
        self.failed_scenes = set(failed_scenes or [])

    async def _generate_edge_tts_narration(self, text, temp_audio_path, voice_id, rate="+0%"):
        scene_idx = int(Path(temp_audio_path).stem.split("_")[1])
        if scene_idx in self.failed_scenes:
            return None
        Path(temp_audio_path).write_text(text, encoding="utf-8")
        return temp_audio_path


class StoryboardTimingFallbackTests(unittest.TestCase):
    def test_keeps_measured_edge_scenes_and_fills_only_failed_one(self):
        logs = []
        generator = StoryboardGenerator(log_callback=logs.append, tts=FakeEdgeTTS(failed_scenes={2}))

        measured_durations = {
            "scene_001.mp3": 2.0,
            "scene_003.mp3": 4.0,
        }
        generator._measure_audio_duration_seconds = lambda path: measured_durations.get(Path(path).name, 0.0)

        scene_metadata = [
            {"text": "uno dos tres cuatro", "word_count": 4},
            {"text": "cinco seis", "word_count": 2},
            {"text": "siete ocho nueve diez", "word_count": 4},
        ]

        durations = generator._estimate_scene_durations_with_selected_tts(
            scene_metadata,
            voice_id="es-CL-CatalinaNeural",
            language="es",
            rate="+0%",
        )

        self.assertIsNotNone(durations)
        self.assertEqual(len(durations), 3)
        self.assertAlmostEqual(durations[0], 2.0)
        self.assertAlmostEqual(durations[1], 1.5)
        self.assertAlmostEqual(durations[2], 4.0)
        self.assertTrue(any("Timing mixto" in line for line in logs))

    def test_returns_none_when_no_scene_has_valid_audio(self):
        generator = StoryboardGenerator(log_callback=lambda _: None, tts=FakeEdgeTTS(failed_scenes={1, 2}))
        generator._measure_audio_duration_seconds = lambda path: 0.0

        scene_metadata = [
            {"text": "primera escena", "word_count": 2},
            {"text": "segunda escena", "word_count": 2},
        ]

        durations = generator._estimate_scene_durations_with_selected_tts(
            scene_metadata,
            voice_id="es-CL-CatalinaNeural",
            language="es",
            rate="+0%",
        )

        self.assertIsNone(durations)


if __name__ == "__main__":
    unittest.main()
