import unittest

from subtitle_style_catalog import (
    DEFAULT_SUBTITLE_STYLE_LABEL,
    SUBTITLE_STYLE_LABELS,
    get_subtitle_style_label,
)


class SubtitleStyleCatalogTests(unittest.TestCase):
    def test_legacy_capcut_alias_maps_to_tiktok_label(self):
        self.assertEqual(
            get_subtitle_style_label("capcut"),
            get_subtitle_style_label("tiktok"),
        )

    def test_existing_ui_label_is_stable(self):
        label = get_subtitle_style_label("capcut_luxury")
        self.assertIn(label, SUBTITLE_STYLE_LABELS)
        self.assertEqual(get_subtitle_style_label(label), label)

    def test_unknown_style_falls_back_to_default(self):
        self.assertEqual(
            get_subtitle_style_label("totally-unknown-style"),
            DEFAULT_SUBTITLE_STYLE_LABEL,
        )


if __name__ == "__main__":
    unittest.main()
