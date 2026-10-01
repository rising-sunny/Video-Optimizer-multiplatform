import unittest

from pipeline.daily_short_pipeline import (
    _filter_ideas_by_editorial_focus,
    _idea_matches_editorial_focus,
    _pick_editorial_fallback,
)


class DailyShortEditorialFocusTests(unittest.TestCase):
    def test_allows_history_mystery_ufo_topics(self):
        idea = {
            "title": "The Roswell Files: 7 Details Still Hidden",
            "category": "UFOs & Paranormal",
            "justification": "Strong mystery angle tied to declassified material.",
        }
        allowed, reason = _idea_matches_editorial_focus(idea)
        self.assertTrue(allowed, reason)

    def test_blocks_science_and_health_topics(self):
        idea = {
            "title": "AI Breakthrough: 5 Medical Uses This Year",
            "category": "Science & Technology",
            "justification": "Health and science trend with strong viral potential.",
        }
        allowed, reason = _idea_matches_editorial_focus(idea)
        self.assertFalse(allowed)
        self.assertIn("bloqueado", reason)

    def test_filters_out_celebrity_and_sports_ideas(self):
        ideas = [
            {
                "title": "Ancient Rome: 6 Secrets Buried Underground",
                "category": "Ancient History & Civilizations",
                "justification": "Historical mystery with evergreen appeal.",
            },
            {
                "title": "Celebrity Scandal: 4 Twists Fans Missed",
                "category": "Entertainment",
                "justification": "Showbiz topic.",
            },
            {
                "title": "Football Final: 3 Stats That Shocked Fans",
                "category": "Sports",
                "justification": "Sports topic.",
            },
        ]
        filtered = _filter_ideas_by_editorial_focus(ideas)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["category"], "Ancient History & Civilizations")

    def test_editorial_fallback_skips_duplicates(self):
        fallback = _pick_editorial_fallback(["The Roswell Incident: 7 Facts Still Unexplained"])
        self.assertNotEqual(fallback["title"], "The Roswell Incident: 7 Facts Still Unexplained")


if __name__ == "__main__":
    unittest.main()
