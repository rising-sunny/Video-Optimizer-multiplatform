import unittest

from image_generation_manager import (
    ImageGenerationManager,
    apply_aspect_ratio_to_visual_prompt,
    primary_aspect_ratio_from_format,
)


class PrimaryAspectRatioTests(unittest.TestCase):
    def test_gui_format_strings(self):
        self.assertEqual(primary_aspect_ratio_from_format("16:9"), "16:9")
        self.assertEqual(primary_aspect_ratio_from_format("9:16"), "9:16")
        self.assertEqual(primary_aspect_ratio_from_format("1:1"), "1:1")

    def test_dual_and_triple_use_first_component(self):
        self.assertEqual(primary_aspect_ratio_from_format("16:9+1:1"), "16:9")
        self.assertEqual(primary_aspect_ratio_from_format("16:9+1:1+9:16"), "16:9")

    def test_platform_fallback(self):
        self.assertEqual(primary_aspect_ratio_from_format(None, "youtube_short"), "9:16")
        self.assertEqual(primary_aspect_ratio_from_format(None, "youtube_vertical"), "9:16")
        self.assertEqual(primary_aspect_ratio_from_format(None, "square"), "1:1")
        self.assertEqual(primary_aspect_ratio_from_format(None, "youtube"), "16:9")


class ApplyAspectRatioToVisualPromptTests(unittest.TestCase):
    def test_injects_16_9_at_start_when_missing(self):
        prompt = apply_aspect_ratio_to_visual_prompt(
            "Roman legionaries in a foggy forest, dramatic torchlight",
            "16:9",
        )
        self.assertTrue(prompt.startswith("cinematic 16:9"))
        self.assertIn("16:9", prompt)
        self.assertNotIn("9:16", prompt)

    def test_injects_9_16_at_start_when_missing(self):
        prompt = apply_aspect_ratio_to_visual_prompt(
            "close-up of a bronze mask in torchlight",
            "9:16",
        )
        self.assertTrue(prompt.startswith("vertical 9:16"))
        self.assertIn("9:16", prompt)
        self.assertNotIn("16:9", prompt)

    def test_injects_1_1_when_missing(self):
        prompt = apply_aspect_ratio_to_visual_prompt(
            "centered artifact on a stone plinth",
            "1:1",
        )
        self.assertTrue(prompt.startswith("square 1:1"))
        self.assertIn("1:1", prompt)

    def test_replaces_wrong_ratio(self):
        original = (
            "cinematic 16:9, wide establishing shot of Derinkuyu, "
            "horizontal composition, documentary still"
        )
        prompt = apply_aspect_ratio_to_visual_prompt(original, "9:16")
        self.assertIn("9:16", prompt)
        self.assertNotIn("16:9", prompt)
        self.assertTrue(prompt.startswith("vertical 9:16"))

    def test_does_not_duplicate_existing_ratio(self):
        original = "Cinematic photorealistic 16:9 documentary still, starfield wide"
        prompt = apply_aspect_ratio_to_visual_prompt(original, "16:9")
        self.assertEqual(prompt.count("16:9"), 1)
        self.assertIn("16:9", prompt)

    def test_idempotent(self):
        first = apply_aspect_ratio_to_visual_prompt("a torchlit tunnel", "9:16")
        second = apply_aspect_ratio_to_visual_prompt(first, "9:16")
        self.assertEqual(first, second)


class RecraftCopiedPromptIncludesAspectTests(unittest.TestCase):
    def setUp(self):
        self.manager = ImageGenerationManager()

    def test_vertical_generation_prompt_names_9_16(self):
        prompt = self.manager._build_generation_visual_prompt(
            segment_group=[{"visual_prompt": "Cucuteni settlement at dawn, golden light"}],
            style="Photorealism",
            provider_key="comfy_dev",
            is_vertical=True,
            is_square=False,
            segment_number_in_storyboard=1,
            used_prompts={},
            add_variation=False,
        )
        self.assertIn("9:16", prompt)
        self.assertNotIn("16:9", prompt)

    def test_horizontal_generation_prompt_names_16_9(self):
        prompt = self.manager._build_generation_visual_prompt(
            segment_group=[{"visual_prompt": "Cucuteni settlement at dawn, golden light"}],
            style="Photorealism",
            provider_key="comfy_dev",
            is_vertical=False,
            is_square=False,
            segment_number_in_storyboard=1,
            used_prompts={},
            add_variation=False,
        )
        self.assertIn("16:9", prompt)
        self.assertNotIn("9:16", prompt)

    def test_segment_lookup_prompt_includes_aspect(self):
        storyboard = {
            "segments": [
                {"visual_prompt": "Vanished title card over black, cinematic"},
                {"visual_prompt": "The Cucuteni-Trypillia culture built settlements"},
            ]
        }
        vertical = self.manager.get_recraft_prompt_for_segment(
            storyboard, "youtube_short", 1, provider_key="comfy_dev"
        )
        horizontal = self.manager.get_recraft_prompt_for_segment(
            storyboard, "youtube", 1, provider_key="comfy_dev"
        )
        self.assertIn("9:16", vertical["prompt"])
        self.assertIn("16:9", horizontal["prompt"])


if __name__ == "__main__":
    unittest.main()
