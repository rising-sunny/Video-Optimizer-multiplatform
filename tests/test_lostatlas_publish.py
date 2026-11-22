# -*- coding: utf-8 -*-
"""The Lost Atlas: registro del canal y metadata de YouTube. No toca la red.

    .venv/bin/python -m unittest tests.test_lostatlas_publish
"""
import unittest

from channel.channel_profiles import CHANNELS, load_profile
from lostatlas import publish_pack
from lostatlas.questions import GEO_DEMO
from lostatlas.questions_empire import EMPIRE_DEMO
from lostatlas.questions_year import YEAR_DEMO
from publish.upload_metadata import channel_brand, metadata_for_channel


class LostAtlasTests(unittest.TestCase):
    def test_registered(self):
        c = CHANNELS["the-lost-atlas"]
        self.assertEqual(c["token"], "token_the-lost-atlas.json")
        self.assertTrue(c["channel_id"].startswith("UC") and len(c["channel_id"]) == 24)
        self.assertEqual(load_profile("the-lost-atlas")["channel_identity"]["channel_id"], c["channel_id"])
        self.assertEqual(channel_brand("the-lost-atlas"), "The Lost Atlas")

    def test_metadata_limits_and_guard(self):
        for tpl, qs in (("geo", GEO_DEMO), ("year", YEAR_DEMO), ("empire", EMPIRE_DEMO)):
            m = publish_pack.build_metadata(tpl, qs, "Music:\n\"X\" Kevin MacLeod", "Maps: y")
            self.assertLessEqual(len(m["title"]), 100)
            self.assertLessEqual(len(m["description"]), 5000)
            self.assertLessEqual(sum(len(t) + 1 for t in m["tags"]), 500)
            self.assertEqual(m["fact_check"], "pending")            # las preguntas demo NO estan verificadas
            self.assertEqual(m["upload_channel"], "the-lost-atlas")
            out = metadata_for_channel(m, "the-lost-atlas")
            self.assertEqual(out["upload_channel"], "the-lost-atlas")

    def test_verified_flag(self):
        qs = [dict(q, verified=True) for q in GEO_DEMO]
        self.assertEqual(publish_pack.build_metadata("geo", qs)["fact_check"], "verified")


if __name__ == "__main__":
    unittest.main()
