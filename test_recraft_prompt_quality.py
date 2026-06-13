import unittest

from image_generation_manager import ImageGenerationManager
from recraft_client import RecraftClient


class RecraftPromptQualityTests(unittest.TestCase):
    def setUp(self):
        self.manager = ImageGenerationManager()

    def test_historical_year_enables_period_accuracy_boosters(self):
        prompt = self.manager._build_generation_visual_prompt(
            segment_group=[
                {
                    "visual_prompt": (
                        "Roswell UFO crash site in 1947 New Mexico desert at night, "
                        "military personnel examining a damaged flying saucer"
                    )
                }
            ],
            style="Photorealism",
            provider_key="recraft",
            is_vertical=True,
            is_square=False,
            segment_number_in_storyboard=1,
            used_prompts={},
            add_variation=False,
        )

        self.assertIn("period-accurate clothing and props", prompt)
        self.assertIn("documentary realism", prompt)
        self.assertIn("believable scale", prompt)

    def test_negative_prompt_prioritizes_text_and_contextual_artifacts(self):
        negative = self.manager._build_negative_prompt(
            "Roswell UFO recovery in 1947 military hangar with officers and wreckage"
        )

        self.assertTrue(negative.startswith("text, captions, subtitles"))
        self.assertIn("modern clothing", negative)
        self.assertIn("cartoon alien", negative)
        self.assertLessEqual(len(negative), 360)

    def test_recraft_prompt_is_trimmed_to_leave_room_for_negative_prompt(self):
        long_prompt = (
            "ancient underground temple chamber with carved stone walls, ritual basin, "
            "weathered reliefs, torchlight, ceremonial objects, drifting dust, "
            "mysterious shadows, archaeological detail, "
        ) * 18
        prompt = self.manager._build_generation_visual_prompt(
            segment_group=[{"visual_prompt": long_prompt}],
            style="Photorealism",
            provider_key="recraft",
            is_vertical=True,
            is_square=False,
            segment_number_in_storyboard=2,
            used_prompts={},
            add_variation=True,
        )

        self.assertLessEqual(len(prompt), 760)
        self.assertIn("single decisive still image", prompt)

    def test_recraft_client_preserves_avoid_block_with_long_prompt(self):
        prompt = ("documentary still image of a declassified bunker interior, " * 40).strip()
        negative_prompt = (
            "text, watermark, logo, ui, cropped face, bad anatomy, modern clothing, "
            "red arrow, clickbait thumbnail"
        )

        composed = RecraftClient._compose_prompt_with_negative(
            prompt,
            negative_prompt,
            max_chars=1000,
            preferred_negative_budget=180,
        )

        self.assertIn("\nAvoid: ", composed)
        self.assertIn("text, watermark, logo", composed)
        self.assertLessEqual(len(composed), 1000)


if __name__ == "__main__":
    unittest.main()
