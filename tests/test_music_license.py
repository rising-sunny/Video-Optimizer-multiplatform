# -*- coding: utf-8 -*-
"""Tests de music_license: solo musica de Jamendo apta para video, con su atribucion.

Regresion (2026-09-24): Shorts bloqueados en todo el mundo por "The Prophecy"
(Paul Werner, Jamendo 1506663): CC BY-NC-ND y registrado en Content ID
(WAMI_CS, MINT, BMI). La app aceptaba cualquier licencia CC y la atribucion
que exige CC BY nunca llegaba a la descripcion. Sin red.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from publish import music_license as ml

ROOT = Path(__file__).resolve().parent.parent

PROPHECY_OLD_PROJECT = {   # como quedo guardado en los proyectos de enero-febrero
    "title": "The Prophecy", "artist": "Paul Werner",
    "audio_url": "https://prod-1.storage.jamendo.com/?trackid=1506663&format=mp31&from=abc",
    "duration": 243, "crop_start": 0.0, "crop_end": 243,
}
PROPHECY_API = {
    "id": "1506663", "name": "The Prophecy", "artist_id": "461414", "artist_name": "Paul Werner",
    "license_ccurl": "http://creativecommons.org/licenses/by-nc-nd/3.0/",
    "shareurl": "https://www.jamendo.com/track/1506663", "content_id_free": False,
}
CC_BY_TRACK = {
    "title": "Shore", "artist": "Some Artist", "artist_id": "999", "track_id": "123456",
    "license_url": "http://creativecommons.org/licenses/by/3.0/",
    "share_url": "https://www.jamendo.com/track/123456", "source": "jamendo",
}
NO_CLAIMS = {"artists": [], "tracks": []}


def claims_with_prophecy():
    return {"artists": [{"artist_id": "461414", "name": "Paul Werner", "claimants": "WAMI_CS, MINT, BMI"}],
            "tracks": [{"track_id": "1506663", "claimants": "WAMI_CS, MINT, BMI"}]}


class LaLicencia(unittest.TestCase):
    def test_codes_and_versions(self):
        self.assertEqual(ml.license_code("http://creativecommons.org/licenses/by-nc-nd/3.0/"), "CC BY-NC-ND")
        self.assertEqual(ml.license_code("https://creativecommons.org/licenses/by-sa/4.0/"), "CC BY-SA")
        self.assertEqual(ml.license_code("https://creativecommons.org/publicdomain/zero/1.0/"), "CC0")
        self.assertEqual(ml.license_code(""), "UNKNOWN")
        self.assertEqual(ml.license_version("http://creativecommons.org/licenses/by/3.0/"), "3.0")

    def test_only_by_by_sa_and_cc0_work_in_a_video(self):
        for ok in ("CC BY", "CC BY-SA", "CC0"):
            self.assertIsNone(ml.license_problem(ok), ok)
        self.assertIn("no comercial", ml.license_problem("CC BY-NC"))
        self.assertIn("obras derivadas", ml.license_problem("CC BY-ND"))
        both = ml.license_problem("CC BY-NC-ND")
        self.assertIn("no comercial", both)
        self.assertIn("obras derivadas", both)
        self.assertIn("desconocida", ml.license_problem("UNKNOWN"))

    def test_url_wins_over_a_stale_code(self):
        t = {"license_code": "CC BY", "license_url": "http://creativecommons.org/licenses/by-nc/3.0/"}
        self.assertEqual(ml.track_license_code(t), "CC BY-NC")
        self.assertEqual(ml.track_license_code({"license_code": "LOCAL"}), "LOCAL")
        self.assertEqual(ml.track_license_code({}), "UNKNOWN")

    def test_track_id_from_old_project_audio_url(self):
        self.assertEqual(ml.track_id(PROPHECY_OLD_PROJECT), "1506663")
        self.assertEqual(ml.track_id({"share_url": "https://jamen.do/t/42"}), "42")
        self.assertEqual(ml.track_url(PROPHECY_OLD_PROJECT), "https://www.jamendo.com/track/1506663")


class LaAtribucion(unittest.TestCase):
    def test_english_credit_with_title_author_source_license(self):
        text = ml.attribution_text(CC_BY_TRACK)
        self.assertEqual(text.split("\n"), [
            'Music: "Shore" by Some Artist',
            "Source: https://www.jamendo.com/track/123456 (Jamendo)",
            "License: CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/)",
        ])

    def test_goes_before_trailing_hashtags(self):
        desc = "The real story of the Bismarck.\n\nWhat do you think?\n\n#History #WW2"
        out = ml.with_attribution(desc, ml.attribution_text(CC_BY_TRACK))
        self.assertTrue(out.endswith("#History #WW2"))
        self.assertIn('Music: "Shore" by Some Artist', out)
        self.assertLess(out.index("What do you think?"), out.index("Music:"))

    def test_is_idempotent(self):
        once = ml.with_attribution("Body text.", ml.attribution_text(CC_BY_TRACK))
        self.assertEqual(ml.with_attribution(once, ml.attribution_text(CC_BY_TRACK)), once)

    def test_never_cut_the_credit_cut_the_body(self):
        attr = ml.attribution_text(CC_BY_TRACK)
        desc = ("Sentence number one is here. " * 120).strip() + "\n\n#History"
        out = ml.with_attribution(desc, attr, limit=600)
        self.assertLessEqual(len(out), 600)
        self.assertIn(attr, out)
        self.assertTrue(out.endswith("#History"))

    def test_no_attribution_leaves_description_alone(self):
        self.assertEqual(ml.with_attribution(" Body. ", ""), "Body.")


class LosReclamos(unittest.TestCase):
    def test_prophecy_is_blocked_by_track_artist_id_or_name(self):
        claims = claims_with_prophecy()
        self.assertTrue(ml.is_blocked(PROPHECY_OLD_PROJECT, claims)[0])
        other_track_same_artist = {"title": "Another", "artist": "Paul  Werner", "track_id": "1"}
        self.assertTrue(ml.is_blocked(other_track_same_artist, claims)[0])
        self.assertTrue(ml.is_blocked({"artist_id": "461414", "track_id": "2"}, claims)[0])
        self.assertFalse(ml.is_blocked(CC_BY_TRACK, claims)[0])

    def test_record_claim_blocks_track_and_artist_once(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "claims.json"
            ml.record_claim(CC_BY_TRACK, claimants="SomeCMS", path=p)
            data = ml.record_claim(CC_BY_TRACK, claimants="SomeCMS", path=p)
            self.assertEqual(len(data["tracks"]), 1)
            self.assertEqual(len(data["artists"]), 1)
            self.assertTrue(ml.is_blocked({"artist": "Some Artist"}, ml.load_claims(p))[0])

    def test_repo_claims_file_has_the_prophecy(self):
        self.assertTrue(ml.is_blocked(PROPHECY_OLD_PROJECT, ml.load_claims())[0])


class LaBusqueda(unittest.TestCase):
    def test_filter_drops_nc_nd_and_claimed_and_adds_credit(self):
        nc_nd = dict(CC_BY_TRACK, track_id="7", artist="X",
                     license_url="http://creativecommons.org/licenses/by-nc-nd/3.0/")
        claimed = dict(CC_BY_TRACK, track_id="8", artist="Paul Werner", artist_id="461414")
        kept, dropped = ml.filter_tracks([CC_BY_TRACK, nc_nd, claimed], claims_with_prophecy())
        self.assertEqual([t["track_id"] for t in kept], ["123456"])
        self.assertTrue(kept[0]["attribution_text"].startswith('Music: "Shore"'))
        self.assertTrue(kept[0]["attribution_required"])
        self.assertEqual(len(dropped), 2)

    def _api_track(self, tid, artist, lic="by", artist_id="1"):
        return {"id": tid, "name": f"T{tid}", "artist_name": artist, "artist_id": artist_id,
                "audio": f"https://x/?trackid={tid}", "duration": 120,
                "license_ccurl": f"http://creativecommons.org/licenses/{lic}/3.0/",
                "shareurl": f"https://www.jamendo.com/track/{tid}"}

    def test_search_asks_jamendo_for_commercial_derivable_licenses_only(self):
        from media import music_recommender as mr
        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append(dict(params))
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {"results": [
                self._api_track("1", "Paul Werner", "by-nc-nd", artist_id="461414"),
                self._api_track("2", "Good Artist", "by"),
                self._api_track("3", "Other Good", "by-sa"),
                self._api_track("4", "Paul Werner", "by", artist_id="461414"),
            ]}
            return resp

        with mock.patch.object(mr.requests, "get", side_effect=fake_get):
            tracks = mr.search_jamendo_api(["cinematic"], "client123", limit=5)
        self.assertEqual(calls[0]["ccnc"], "false")
        self.assertEqual(calls[0]["ccnd"], "false")
        self.assertIn("licenses", calls[0]["include"])
        self.assertEqual([t["track_id"] for t in tracks], ["2", "3"])
        self.assertTrue(all(t["attribution_text"] for t in tracks))
        self.assertTrue(all(t["source"] == "jamendo" for t in tracks))

    def test_auto_music_limit_one_still_finds_after_dropping_claimed(self):
        from media import music_recommender as mr

        def fake_get(url, params=None, timeout=None):
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {"results": [self._api_track("4", "Paul Werner", "by", artist_id="461414"),
                                                  self._api_track("5", "Good", "by")]}
            return resp

        with mock.patch.object(mr.requests, "get", side_effect=fake_get) as g:
            tracks = mr.search_jamendo_api(["cinematic"], "client123", limit=1)
        self.assertGreaterEqual(int(g.call_args_list[0].kwargs["params"]["limit"]), 20)
        self.assertEqual([t["track_id"] for t in tracks], ["5"])

    def test_transient_empty_answer_is_retried(self):
        from media import music_recommender as mr
        answers = [[], [self._api_track("2", "Good", "by")]]

        def fake_get(url, params=None, timeout=None):
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {"results": answers.pop(0) if answers else []}
            return resp

        with mock.patch.object(mr.requests, "get", side_effect=fake_get), \
                mock.patch.object(mr.time, "sleep"):
            tracks = mr.search_jamendo_api(["cinematic"], "client123", limit=3)
        self.assertEqual([t["track_id"] for t in tracks], ["2"])

    def test_youtube_safe_helper_rejects_nc_nd(self):
        from media import music_recommender as mr
        self.assertFalse(mr.is_youtube_safe_cc_license("http://creativecommons.org/licenses/by-nc-nd/3.0/"))
        self.assertTrue(mr.is_youtube_safe_cc_license("http://creativecommons.org/licenses/by/3.0/"))


class LaSubida(unittest.TestCase):
    def test_no_music_local_and_ok(self):
        self.assertEqual(ml.check_music_for_upload(None)["status"], "none")
        self.assertEqual(ml.check_music_for_upload({"source": "local", "title": "x"})["status"], "local")
        v = ml.check_music_for_upload(CC_BY_TRACK, claims=NO_CLAIMS)
        self.assertEqual(v["status"], "ok")
        self.assertIn('Music: "Shore"', v["attribution"])

    def test_old_prophecy_project_is_resolved_via_api_and_flagged(self):
        seen = []

        def http_get(url, params):
            seen.append(params["id"])
            return {"results": [PROPHECY_API]}
        v = ml.check_music_for_upload(PROPHECY_OLD_PROJECT, client_id="c", http_get=http_get, claims=NO_CLAIMS)
        self.assertEqual(seen, ["1506663"])
        self.assertEqual(v["status"], "risky")
        self.assertIn("no comercial", v["reason"])
        self.assertIn("obras derivadas", v["reason"])

    def test_claimed_artist_is_risky_even_with_a_good_license(self):
        t = dict(CC_BY_TRACK, artist="Paul Werner", artist_id="461414")
        v = ml.check_music_for_upload(t, claims=claims_with_prophecy())
        self.assertEqual(v["status"], "risky")
        self.assertIn("Content ID", v["reason"])

    def test_unknown_license_and_api_down_is_risky(self):
        def down(url, params):
            raise RuntimeError("timeout")
        v = ml.check_music_for_upload({"title": "?", "audio_url": "https://x/?trackid=5"}, client_id="c",
                                      http_get=down, claims=NO_CLAIMS)
        self.assertEqual(v["status"], "risky")


class ElCableado(unittest.TestCase):
    def _src(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_each_uploader_appends_the_credit_after_optimizing(self):
        for name, seo in (("publish/facebook_uploader.py", "prepare_facebook_metadata"),
                          ("publish/instagram_uploader.py", "prepare_instagram_metadata")):
            src = self._src(name)
            body = src[src.index("def upload_from_metadata("):]
            self.assertLess(body.index(seo), body.index("with_attribution(description"), name)
        yt = self._src("publish/youtube_uploader.py")
        body = yt[yt.index("def upload_from_metadata("):]
        self.assertLess(body.index("with_attribution(description"), body.index("result = upload_video("))
        self.assertIn("description=description,", body)

    def test_studio_checks_music_and_passes_the_credit(self):
        src = self._src("auto_video_integration_pyqt6.py")
        body = src[src.index("    def publish_video_to_platforms("):]
        self.assertIn("self._music_license_gate(storyboard)", body)
        self.assertIn("_meta['music_attribution'] = _music_attribution", body)
        self.assertIn("for pkg_name in ('infra', 'ai', 'media', 'channel', 'publish'):", src)  # music_license viaja en publish/

    def test_assembler_records_the_music_it_mixed(self):
        src = self._src("pipeline/auto_video_generator_v2.py")
        self.assertNotIn("'music_attribution': None,", src)
        self.assertEqual(src.count("'music_used': _music_used,"), 2)

    def test_daily_pipeline_passes_the_credit(self):
        src = self._src("pipeline/daily_short_pipeline.py")
        self.assertIn('youtube_metadata["music_attribution"] = music_attribution', src)
        self.assertIn('instagram_metadata["music_attribution"] = music_attribution', src)

    def test_dialog_no_longer_offers_nc_nd(self):
        src = self._src("music_browser_dialog.py")
        self.assertNotIn("Check NC/ND restrictions before publishing", src)
        self.assertIn("record_claim(track", src)


if __name__ == "__main__":
    unittest.main()
