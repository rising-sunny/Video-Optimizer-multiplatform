import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_short_pipeline


class TestTitleSimilarity(unittest.TestCase):
    def test_submarine_family_titles_are_flagged(self):
        self.assertTrue(
            daily_short_pipeline._titles_are_similar(
                "Submarine Disasters: 4 Worst Recoveries",
                "7 Deadliest Submarine Disasters: Revealed",
            )
        )

    def test_tunguska_rewording_is_flagged(self):
        self.assertTrue(
            daily_short_pipeline._titles_are_similar(
                "The Tunguska Event: A Blast 1000x Stronger Than Hiroshima",
                "Tunguska Mystery: 3 Secrets Behind the Blast",
            )
        )

    def test_single_broad_overlap_is_not_enough(self):
        self.assertFalse(
            daily_short_pipeline._titles_are_similar(
                "Roman Empire: 5 Hidden Secrets",
                "Aztec Empire: 7 Hidden Secrets",
            )
        )

    def test_distinct_topics_stay_distinct(self):
        self.assertFalse(
            daily_short_pipeline._titles_are_similar(
                "Augusta National: 3 Hidden Secrets",
                "Mount Mayon: 10 Eruptions",
            )
        )


class TestUsedTitleCollection(unittest.TestCase):
    def test_pending_daily_short_drafts_are_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = root / "daily_shorts" / "2026-04-11"
            draft_dir.mkdir(parents=True)
            (draft_dir / "idea.json").write_text(
                json.dumps({"title": "Submarine Disasters: 4 Worst Recoveries"}),
                encoding="utf-8",
            )

            with patch.object(daily_short_pipeline, "PROJECT_DIR", root):
                with patch("youtube_channel_analyzer.YouTubeChannelAnalyzer") as analyzer_cls:
                    analyzer_cls.return_value.get_channel_videos.return_value = []
                    used_titles = daily_short_pipeline.get_used_titles()

            self.assertIn("Submarine Disasters: 4 Worst Recoveries", used_titles)


if __name__ == "__main__":
    unittest.main()
