import tempfile
import unittest
from pathlib import Path

from pipeline.image_generation_manager import ImageGenerationManager


class _FakeComfyClient:
    available = True
    last_error = None

    def __init__(self):
        self.calls = []

    def generate_image(
        self,
        prompt,
        width,
        height,
        output_path,
        negative_prompt=None,
        style=None,
        seed=None,
        preset=None,
    ):
        self.calls.append({
            "prompt": prompt,
            "width": width,
            "height": height,
            "output_path": output_path,
            "negative_prompt": negative_prompt,
            "style": style,
            "seed": seed,
            "preset": preset,
        })
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-comfy-image")
        return str(output)


class ImageGenerationManagerComfyTests(unittest.TestCase):
    def test_comfy_schnell_generates_local_path_and_marks_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_comfy = _FakeComfyClient()
            manager = ImageGenerationManager(
                log_callback=lambda _msg: None,
                generated_media_dir=Path(tmpdir),
                comfyui_image_client=fake_comfy,
            )
            storyboard = {
                "segments": [
                    {
                        "assigned_filename": "segment_001",
                        "visual_prompt": "ancient city at sunrise, cinematic documentary realism",
                    }
                ]
            }

            result = manager.generate_all_images_for_storyboard(
                storyboard,
                "youtube_short",
                use_real_images=False,
                use_google_images=False,
                image_provider="comfy_schnell",
                style="Realistic image",
            )

            segment = result["segments"][0]
            self.assertEqual(segment["image_source"], "comfy_flux_schnell")
            self.assertTrue(Path(segment["image_path"]).exists())
            self.assertEqual(len(fake_comfy.calls), 1)
            call = fake_comfy.calls[0]
            self.assertEqual(call["width"], 1080)
            self.assertEqual(call["height"], 1920)
            self.assertEqual(call["preset"], "historical_vertical_schnell")
            self.assertIn("ancient city", call["prompt"])

    def test_comfy_sdxl_uses_coloring_preset_and_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_comfy = _FakeComfyClient()
            manager = ImageGenerationManager(
                log_callback=lambda _msg: None,
                generated_media_dir=Path(tmpdir),
                comfyui_image_client=fake_comfy,
            )
            storyboard = {
                "segments": [
                    {
                        "assigned_filename": "segment_001",
                        "visual_prompt": "simple printable castle coloring page",
                    }
                ]
            }

            result = manager.generate_all_images_for_storyboard(
                storyboard,
                "youtube",
                use_real_images=False,
                use_google_images=False,
                image_provider="comfy_sdxl",
                style="coloring page lineart",
            )

            segment = result["segments"][0]
            self.assertEqual(segment["image_source"], "comfy_sdxl")
            self.assertTrue(Path(segment["image_path"]).exists())
            self.assertEqual(fake_comfy.calls[0]["width"], 1920)
            self.assertEqual(fake_comfy.calls[0]["height"], 1080)
            self.assertEqual(fake_comfy.calls[0]["preset"], "coloring_sdxl_lineart")


if __name__ == "__main__":
    unittest.main()
