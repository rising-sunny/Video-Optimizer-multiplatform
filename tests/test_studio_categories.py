"""The manual mystery category survives profile synchronization and reaches script prompts."""
import copy
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QComboBox, QWidget

from channel.channel_profiles import DEFAULT_CHANNEL, select_channel
from channel.channel_strategy import get_channel_strategy, get_all_category_names
from ai.claude_client import ClaudeAiClient
from pipeline.storyboard_generator import StoryboardGenerator
from studio_categories import MYSTERY_CATEGORY, get_studio_category_names, mystery_editorial_instructions
from studio_channel_controls import set_editorial_channel, sync_editorial_before_writing
from ai.tone_profile import get_tone_profile_for_category


class MysteryEditorialTests(unittest.TestCase):
    def setUp(self):
        select_channel(DEFAULT_CHANNEL)

    def tearDown(self):
        select_channel(DEFAULT_CHANNEL)

    def test_option_is_available_without_modifying_automated_channel_strategy(self):
        before = copy.deepcopy(get_channel_strategy())
        names = get_studio_category_names()
        self.assertIn(MYSTERY_CATEGORY, names)
        self.assertEqual(names.count(MYSTERY_CATEGORY), 1)
        self.assertIn("War & Military History", names)
        self.assertNotIn(MYSTERY_CATEGORY, get_all_category_names())
        self.assertEqual(get_channel_strategy(), before)
        self.assertEqual(get_tone_profile_for_category(MYSTERY_CATEGORY), "mystery")

    def test_option_remains_available_when_channel_loading_fails(self):
        with patch("channel.channel_strategy.get_all_category_names", side_effect=OSError("missing profile")):
            self.assertIn(MYSTERY_CATEGORY, get_studio_category_names())

    def test_manual_json_prompts_allow_investigation_only_when_selected(self):
        gen = StoryboardGenerator()
        for seconds, platform, ratio in ((60, "youtube_short", "9:16"), (600, "youtube", "16:9")):
            with self.subTest(platform=platform):
                prompt = gen.generate_manual_prompt_text(
                    "El misterio del ángel de Senaquerib", MYSTERY_CATEGORY, seconds,
                    language="es", platform=platform, video_format=ratio,
                )
                self.assertIn("HECHO DOCUMENTADO", prompt)
                self.assertIn("RELATO/CREENCIA DE UNA FUENTE", prompt)
                self.assertIn("Se permite un cierre abierto", prompt)
                self.assertIn("no refutado NO significa demostrado", prompt)
                self.assertNotIn("FUERA DE ALCANCE", prompt)
                self.assertNotIn("NO cierres\n  insinuando un misterio abierto", prompt)
        ordinary = gen.generate_manual_prompt_text(
            "Trafalgar", "War & Military History", 60,
            language="en", platform="youtube_short", video_format="9:16",
        )
        self.assertIn("FUERA DE ALCANCE", ordinary)
        self.assertNotIn("MODO EDITORIAL — MISTERIOS Y CONSPIRACIONES", ordinary)

    def test_script_prompts_and_rewrite_context_keep_evidence_and_uncertainty(self):
        client = ClaudeAiClient.__new__(ClaudeAiClient)
        client._generate = Mock(return_value="Narration")
        client._postprocess_generated_script = Mock(return_value="Narration")
        for researched in (False, True):
            with self.subTest(researched=researched):
                if researched:
                    client.generate_video_script_with_research(
                        "Sennacherib", MYSTERY_CATEGORY, 60, ["A source account"], language="en")
                else:
                    client.generate_video_script("Sennacherib", MYSTERY_CATEGORY, 60, language="en")
                prompt = client._generate.call_args.args[0]
                self.assertIn("not refuted does NOT mean demonstrated", prompt)
                self.assertIn("SOURCE ACCOUNT/BELIEF", prompt)
                self.assertIn("Close with what is known and the question that remains open", prompt)
                self.assertNotIn("Do NOT debunk or dismiss", prompt)
                self.assertNotIn("Do NOT be overly skeptical", prompt)
                self.assertNotIn("No cerrar insinuando un misterio", prompt)
                rewrite = client._postprocess_generated_script.call_args.kwargs["quality_block"]
                self.assertIn("not refuted does NOT mean demonstrated", rewrite)

    def test_retry_does_not_force_a_factual_only_documentary(self):
        client = ClaudeAiClient.__new__(ClaudeAiClient)
        client._generate = Mock(return_value="Narration")
        client._retry_script_after_refusal(
            "Sennacherib", MYSTERY_CATEGORY, 60, "en", 150, 1000,
            "Investigative narrator", mystery_editorial_instructions(MYSTERY_CATEGORY, "en"))
        prompt = client._generate.call_args.args[0]
        self.assertIn("open hypotheses", prompt)
        self.assertNotIn("This is a standard historical documentary", prompt)


class MysteryCategoryGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        select_channel(DEFAULT_CHANNEL)

    def test_editorial_sync_keeps_explicit_selection_and_allows_restore(self):
        parent = QWidget()
        parent.category_combo = QComboBox(parent)
        tab = SimpleNamespace(parent_gui=parent, current_project_path=None, last_storyboard_data=None,
                              _upload_channel=DEFAULT_CHANNEL)
        set_editorial_channel(tab, DEFAULT_CHANNEL)
        parent.category_combo.setCurrentText(MYSTERY_CATEGORY)
        self.assertFalse(sync_editorial_before_writing(tab, isolated=True))
        self.assertEqual(parent.category_combo.currentText(), MYSTERY_CATEGORY)
        set_editorial_channel(tab, "stunning-revelations")
        self.assertEqual(parent.category_combo.currentText(), MYSTERY_CATEGORY)
        set_editorial_channel(tab, DEFAULT_CHANNEL)
        self.assertEqual(parent.category_combo.currentText(), MYSTERY_CATEGORY)
        self.assertEqual(sum(parent.category_combo.itemText(i) == MYSTERY_CATEGORY
                             for i in range(parent.category_combo.count())), 1)
        parent.close()


if __name__ == "__main__":
    unittest.main()
