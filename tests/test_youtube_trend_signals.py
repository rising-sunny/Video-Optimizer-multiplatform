"""Regression tests for actual demand, sampling/auth failures, cache and Studio selection."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from channel import youtube_trend_signals as ys

NOW = dt.datetime(2026, 9, 30, 20, tzinfo=dt.timezone.utc)


def row(vid, title, channel, views=60000, age=3, **extra):
    return dict(video_id=vid, title=title, channel=channel, channel_id=channel, views=views,
                age_days=age, views_per_day=views / max(1, age), duration=600,
                published=(NOW - dt.timedelta(days=age)).isoformat(), **extra)


def video(vid="v1", title="Roman concrete in seawater", duration="PT10M", age=3, views=60000, **snippet):
    return {"id": vid, "snippet": {"title": title, "channelTitle": "Channel", "channelId": "c1",
                                  "publishedAt": (NOW - dt.timedelta(days=age)).isoformat(), **snippet},
            "statistics": {"viewCount": str(views)}, "contentDetails": {"duration": duration}}


class Request:
    def __init__(self, action):
        self.action = action

    def execute(self, **kwargs):
        return self.action()


class FakeYouTube:
    def __init__(self, videos, error=None):
        self.data, self.error, self.calls, self.resource = videos, error, [], None

    def search(self):
        self.resource = "search"
        return self

    def videos(self):
        self.resource = "videos"
        return self

    def list(self, **kwargs):
        resource = self.resource
        self.calls.append((resource, kwargs))
        def respond():
            if self.error:
                raise self.error
            return {"items": [{"id": {"videoId": v["id"]}} for v in self.data] if resource == "search" else self.data}
        return Request(respond)


class HttpFailure(Exception):
    def __init__(self, reason, status=403):
        self.content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
        self.resp = type("Response", (), {"status": status})()

    def __str__(self):
        return "https://api.invalid/?key=DO_NOT_PRINT_THIS_KEY"


class DemandTests(unittest.TestCase):
    def sample(self):
        return [row("a", "Roman concrete lasts underwater", "A"),
                row("b", "How Roman concrete repairs itself", "B", views=75000),
                row("c", "Roman concrete seawater secrets", "C", views=90000)] + [
                    row(f"p{i}", f"Unique subject number {i}", f"P{i}", views=1000) for i in range(10)]

    def test_recent_multi_channel_subject_beats_one_old_viral_hit(self):
        rows = self.sample() + [row("old", "Titanic survivor", "BigChannel", views=10_000_000, age=29)]
        topics = ys.rank_opportunities(rows)
        self.assertEqual(topics[0]["topic"], "Roman Concrete")
        self.assertTrue(topics[0]["qualified"])
        self.assertEqual(topics[0]["signal"], "Demanda reciente")
        self.assertEqual(topics[0]["channel_count"], 3)
        self.assertIsNone(topics[0]["measured_views_per_day"])
        self.assertFalse(next(p for p in topics if p["topic"] == "Titanic survivor")["qualified"])

    def test_duplicate_results_and_one_channel_are_not_independent_demand(self):
        a = row("a", "Roman concrete", "A", views=1_000_000)
        topics = ys.rank_opportunities([a, a, row("b", "Roman concrete seawater", "A", views=800000)])
        self.assertTrue(all(not p["qualified"] and p["channel_count"] == 1 for p in topics))
        self.assertEqual(sum(p["video_count"] for p in topics), 2)

    def test_several_old_uploads_do_not_become_recent_trend(self):
        rows = self.sample()
        for r in rows[:3]:
            r["age_days"] = 24
        self.assertFalse(ys.rank_opportunities(rows)[0]["qualified"])

    def test_recent_demand_must_succeed_on_distinct_channels(self):
        rows = self.sample()
        rows[1]['channel_id'] = rows[1]['channel'] = 'A'
        rows[2]['age_days'] = 20
        self.assertTrue(all(not p['qualified'] for p in ys.rank_opportunities(rows)))

    def test_tiny_second_channel_cannot_validate_a_large_creator_hit(self):
        rows = self.sample()
        for r in rows[1:3]:
            r.update(views=3, views_per_day=1)
        self.assertTrue(all(not p['qualified'] for p in ys.rank_opportunities(rows)))

    def test_weekly_documentaries_can_show_demand_but_seven_day_filter_is_respected(self):
        rows = self.sample()
        for r in rows[:3]:
            r['age_days'] = 11
        topic = ys.rank_opportunities(rows, window_days=30)[0]
        self.assertTrue(topic['qualified'])
        self.assertEqual(topic['recent_count'], 0)
        self.assertEqual(topic['demand_window_days'], 14)
        self.assertFalse(ys.rank_opportunities(rows, window_days=7)[0]['qualified'])

    def test_only_real_counter_changes_can_label_growth(self):
        rows = self.sample()
        for r in rows[:3]:
            r.update(measured_views_per_day=60000, measurement_hours=12)
        topic = ys.rank_opportunities(rows)[0]
        self.assertEqual(topic["signal"], "Crecimiento medido")
        self.assertEqual(topic["measured_views_per_day"], 60000)

    def test_generic_headline_words_do_not_merge_different_subjects(self):
        topics = ys.group_topics([row("a", "The Greatest Naval Battle: Trafalgar", "A"),
                                  row("b", "The Greatest Naval Battle: Midway", "B")])
        self.assertEqual(len(topics), 2)

    def test_verified_subject_searches_group_names_but_not_unrelated_videos(self):
        a = row("a", "Inside the Sturmtiger", "A", subject_queries=["Sturmtiger"])
        b = row("b", "Sturmtiger ammunition", "B", subject_queries=["Sturmtiger"])
        unrelated = row("c", "Tank battle", "C", subject_queries=[])
        groups = ys.group_topics([a, b, unrelated])
        self.assertEqual(groups[0]["topic"], "Sturmtiger")
        self.assertEqual(len(groups[0]["videos"]), 2)

    def test_category_queries_use_mysteries_and_historical_science_context(self):
        self.assertIn("historical mysteries", ys.discovery_queries("Misterios y Conspiraciones"))
        self.assertIn("misterios historicos", ys.discovery_queries("Misterios y Conspiraciones", "es"))
        self.assertIn("history of science", ys.discovery_queries("Science & Technology in History"))
        self.assertIn("historical disasters", ys.discovery_queries("Historical Disasters"))

    def test_all_categories_discovery_and_applied_category_follow_actual_evidence(self):
        with patch.object(ys, 'configured_categories', return_value=['War & Military History', 'Misterios y Conspiraciones']):
            queries = ys.discovery_queries('')
            self.assertIn('military history', queries)
            self.assertIn('historical mysteries', queries)
            r = row('a', 'Wake Island', 'A', queries=['military history'])
            self.assertEqual(ys.rank_opportunities([r])[0]['category'], 'War & Military History')

    def test_without_ai_seeds_are_actual_subjects_not_headline_openings(self):
        subjects = ys.discover_subjects([video('a', title='Inside the Sturmtiger'),
                                        video('b', title='The Rise of Hitler')], use_ai=False)
        self.assertIn('Sturmtiger', subjects)
        self.assertIn('Hitler', subjects)
        self.assertNotIn('Inside', subjects)

    def test_history_guard_rejects_airport_and_industry_matches(self):
        self.assertFalse(ys.category_match(video(title='Engine failed on go around at Midway'), 'War & Military History'))
        self.assertFalse(ys.category_match(video(title='Inside the high end factory'), 'War & Military History'))
        self.assertTrue(ys.category_match(video(title='Wake Island 1941'), 'War & Military History'))

    def test_json_recovery_uses_room_for_reasoning_and_validates_object(self):
        class Client:
            def _generate(self, prompt, **kwargs):
                self.options = kwargs
                return '```json\n{"keep_ids":[0,2]}\n```'
        client = Client()
        self.assertEqual(ys.request_json(client, 'Filter'), {'keep_ids': [0, 2]})
        self.assertFalse(client.options['json_mode'])
        self.assertEqual(client.options['max_tokens'], 8192)


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cache.json"

    def collect(self, service, **kwargs):
        defaults = dict(queries=["Roman engineering"], cache_path=self.path, services=[service], now=NOW,
                        video_format="long", verify_subjects=False, use_ai=False, log=lambda _: None)
        defaults.update(kwargs)
        return ys.collect_sample(**defaults)

    def test_search_both_hits_and_new_uploads_details_batched_deduped(self):
        yt = FakeYouTube([video("a"), video("b")])
        result = self.collect(yt)
        self.assertEqual(len(result["rows"]), 2)
        searches = [p for resource, p in yt.calls if resource == "search"]
        self.assertEqual([p["order"] for p in searches], ["viewCount", "date"])
        self.assertTrue(all("videoDuration" not in p for p in searches))
        self.assertEqual(len([p for resource, p in yt.calls if resource == "videos"]), 1)

    def test_hour_duration_and_cortos_do_not_mix_and_gaming_is_excluded(self):
        yt = FakeYouTube([video("long", duration="PT1H2M3S"), video("short", duration="PT2M59S"),
                          video("4min", duration="PT3M30S"), video("game", title="Simulating a Medieval War in VR"),
                          video("movie", title="Kingdom Full English HD Movie"), video("old", age=50)])
        self.assertEqual({r["video_id"] for r in self.collect(yt)["rows"]}, {"long", "4min"})
        result = self.collect(yt, video_format="short")
        self.assertEqual([r["video_id"] for r in result["rows"]], ["short"])
        self.assertEqual(ys.duration_seconds("PT1H2M3S"), 3723)

    def test_new_uploads_cannot_inflate_vpd_by_extrapolating_minutes(self):
        result = self.collect(FakeYouTube([video(age=.1, views=100)]))
        self.assertEqual(result["rows"][0]["views_per_day"], 100)

    def test_cache_reuse_context_isolation_and_measured_growth(self):
        self.collect(FakeYouTube([video(views=60000)]))
        second = FakeYouTube([video(views=120000)])
        cached = self.collect(second, now=NOW + dt.timedelta(hours=1))
        self.assertTrue(cached["cached"])
        self.assertEqual(second.calls, [])
        refreshed = self.collect(second, now=NOW + dt.timedelta(hours=12))
        r = refreshed["rows"][0]
        self.assertFalse(refreshed["cached"])
        self.assertEqual(r["measured_views_per_day"], 120000)
        self.assertEqual(r["measurement_hours"], 12)
        other = self.collect(FakeYouTube([video()]), region="GB", now=NOW + dt.timedelta(hours=13))
        self.assertFalse(other["cached"])
        self.assertNotIn("measured_views_per_day", other["rows"][0])

    def test_refresh_within_six_hours_does_not_invent_growth(self):
        self.collect(FakeYouTube([video(views=60000)]))
        result = self.collect(FakeYouTube([video(views=80000)]), now=NOW + dt.timedelta(hours=1), force_refresh=True)
        self.assertNotIn("measured_views_per_day", result["rows"][0])
        after = self.collect(FakeYouTube([video(views=120000)]), now=NOW + dt.timedelta(hours=12), force_refresh=True)
        self.assertEqual(after["rows"][0]["measured_views_per_day"], 120000)

    def test_auth_failure_uses_other_existing_credential_without_leaking_key(self):
        bad, good = FakeYouTube([], HttpFailure("accessNotConfigured")), FakeYouTube([video()])
        result = self.collect(bad, services=[bad, good])
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["errors"], [])
        self.assertNotIn("DO_NOT_PRINT", ys.safe_error(HttpFailure("accessNotConfigured"))[0])

    @patch.object(ys.time, 'sleep')
    def test_temporary_network_error_retries_same_session(self, sleep):
        good, other = FakeYouTube([video()]), FakeYouTube([], HttpFailure('accessNotConfigured'))
        search_result = Request(lambda: {'items': [{'id': {'videoId': 'v1'}}]})
        good.list = Mock(side_effect=[OSError('DNS failure'), search_result, search_result,
                                      Request(lambda: {'items': good.data})])
        messages = []
        result = self.collect(good, services=[good, other], log=messages.append)
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['errors'], [])
        self.assertEqual(other.calls, [])
        self.assertTrue(any('misma sesión' in m for m in messages))
        sleep.assert_called_once_with(1)

    @patch.object(ys.time, 'sleep')
    def test_network_failure_has_bounded_retries_and_keeps_credentials(self, sleep):
        bad, other = FakeYouTube([], OSError('DNS failure')), FakeYouTube([video()])
        result = self.collect(bad, services=[bad, other])
        self.assertEqual(len(bad.calls), 3)
        self.assertEqual(other.calls, [])
        self.assertEqual(result['rows'], [])
        self.assertTrue(result['refresh_failed'])
        self.assertIn('conexión', result['errors'][0])
        self.assertNotIn('API_KEY', str(result))

    @patch.object(ys.time, 'sleep')
    def test_failed_forced_refresh_preserves_sample_time_and_history(self, sleep):
        first = self.collect(FakeYouTube([video()]))
        original_cache = self.path.read_bytes()
        bad = FakeYouTube([], OSError('DNS failure'))
        result = self.collect(bad, force_refresh=True, now=NOW + dt.timedelta(hours=12))
        self.assertTrue(result['cached'])
        self.assertTrue(result['refresh_failed'])
        self.assertEqual(result['sampled_at'], first['sampled_at'])
        self.assertEqual(result['rows'], first['rows'])
        self.assertEqual(result['cache_age_hours'], 12)
        self.assertEqual(self.path.read_bytes(), original_cache)
        self.assertEqual(len(bad.calls), 3)

    @patch.object(ys.time, 'sleep')
    def test_failed_refresh_never_reuses_old_or_different_context(self, sleep):
        self.collect(FakeYouTube([video()]))
        for changes in ({'region': 'CL'}, {'video_format': 'short'}, {'days': 7},
                        {'category': 'War & Military History'}, {'now': NOW + dt.timedelta(hours=25)}):
            with self.subTest(changes=changes):
                result = self.collect(FakeYouTube([], OSError('DNS failure')), force_refresh=True, **changes)
                self.assertEqual(result['rows'], [])
                self.assertFalse(result['cached'])

    @patch.object(ys.time, 'sleep')
    def test_recovered_sample_excludes_publications_outside_selected_window(self, sleep):
        self.collect(FakeYouTube([video('fresh', age=2), video('expired', age=6.8)]), days=7)
        result = self.collect(FakeYouTube([], OSError('DNS failure')), days=7, force_refresh=True,
                              now=NOW + dt.timedelta(hours=12))
        self.assertEqual([r['video_id'] for r in result['rows']], ['fresh'])

    def test_search_quota_after_discovery_still_fetches_available_statistics(self):
        yt = FakeYouTube([video()])
        yt.list = Mock(side_effect=[Request(lambda: {'items': [{'id': {'videoId': 'v1'}}]}),
                                    HttpFailure('quotaExceeded'), Request(lambda: {'items': yt.data})])
        result = self.collect(yt)
        self.assertEqual(len(result['rows']), 1)
        self.assertIn('Cuota', result['errors'][0])
        self.assertEqual(yt.list.call_count, 3)

    def test_quota_failure_stops_searches_and_never_fabricates_sample(self):
        yt = FakeYouTube([], HttpFailure("quotaExceeded"))
        result = self.collect(yt)
        self.assertEqual(result["rows"], [])
        self.assertEqual(len(yt.calls), 1)
        self.assertIsNone(result["sampled_at"])
        self.assertIn("Cuota", result["errors"][0])
        self.assertNotIn("DO_NOT_PRINT", str(result))

    def test_subject_verification_needs_subject_in_the_title(self):
        yt = FakeYouTube([video("a", title="Wake Island last stand", channelId="A"),
                          video("b", title="Wake Island battle", channelId="B"),
                          video("c", title="Other war subject", channelId="C")])
        with patch.object(ys, "discover_subjects", return_value=["Wake Island"]):
            result = self.collect(yt, verify_subjects=True)
        by_id = {r["video_id"]: r for r in result["rows"]}
        self.assertEqual(by_id["a"]["subject_queries"], ["Wake Island"])
        self.assertEqual(by_id["c"]["subject_queries"], [])
        self.assertIn("Wake Island", result["queries"])

    def test_non_contiguous_subject_words_are_not_a_match(self):
        yt = FakeYouTube([video('a', title='Wake Island last stand'),
                          video('b', title='Wake Up to Island Time')])
        with patch.object(ys, 'discover_subjects', return_value=['Wake Island']):
            result = self.collect(yt, verify_subjects=True)
        by_id = {r['video_id']: r for r in result['rows']}
        self.assertEqual(by_id['b']['subject_queries'], [])

    def test_no_credentials_is_actionable_error_not_calendar_as_youtube(self):
        with patch.object(ys, "service_candidates", side_effect=RuntimeError("Configura YOUTUBE_API_KEY")):
            result = self.collect(None, services=None)
        self.assertEqual(result["rows"], [])
        self.assertIn("YOUTUBE_API_KEY", result["errors"][0])

    def test_ai_source_ids_and_subjects_are_validated_before_search(self):
        class Client:
            client = object()
        edits = {'subjects': [{'source_id': 0, 'query': 'Wake Island'},
                              {'source_id': 0, 'query': 'Atlantis'},
                              {'source_id': 99, 'query': 'Roman concrete'},
                              {'source_id': True, 'query': 'Roman concrete'}]}
        with patch('ai.groq_client.GroqAiClient', return_value=Client()), patch.object(ys, 'request_json', return_value=edits):
            subjects = ys.discover_subjects([video(title='Wake Island 1941')], log=lambda _: None)
        self.assertEqual(subjects, ['Wake Island'])

    def test_reading_with_existing_oauth_does_not_require_analytics_permissions(self):
        from types import SimpleNamespace
        token = Path(self.tmp.name) / 'token.json'
        token.write_text('{}')
        service = SimpleNamespace()
        creds = SimpleNamespace(valid=True, scopes=['https://www.googleapis.com/auth/youtube.force-ssl'])
        with patch.dict(os.environ, {}, clear=True), patch('infra.env_loader.load_project_env'), \
                patch('channel.channel_profiles.token_path', return_value=token), \
                patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=creds), \
                patch('google_auth_httplib2.AuthorizedHttp', return_value=object()), \
                patch('googleapiclient.discovery.build', return_value=service):
            self.assertEqual(ys.service_candidates(log=lambda _: None), [service])

    def test_expired_session_refresh_is_deferred_until_retryable_api_request(self):
        token = Path(self.tmp.name) / 'token.json'
        token.write_text('{}')
        creds = SimpleNamespace(valid=False, refresh_token='test-only', token='old',
                                refresh=Mock(side_effect=OSError('DNS failure')))
        service = SimpleNamespace()
        with patch.dict(os.environ, {}, clear=True), patch('infra.env_loader.load_project_env'), \
                patch('channel.channel_profiles.token_path', return_value=token), \
                patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=creds), \
                patch('google_auth_httplib2.AuthorizedHttp', return_value=object()), \
                patch('googleapiclient.discovery.build', return_value=service):
            self.assertEqual(ys.service_candidates(log=lambda _: None), [service])
        creds.refresh.assert_not_called()

    def test_successful_refresh_saves_session_but_disk_failure_does_not_hide_results(self):
        token = Path(self.tmp.name) / 'token.json'
        creds = SimpleNamespace(valid=True, token='new-test-only', to_json=lambda: '{"token":"new-test-only"}')
        yt = FakeYouTube([video()])
        yt._trend_credential_state = (creds, token, 'old-test-only')
        self.collect(yt)
        self.assertEqual(json.loads(token.read_text())['token'], 'new-test-only')
        yt._trend_credential_state = (creds, token, 'old-test-only')
        with patch.object(Path, 'replace', side_effect=PermissionError()):
            result = self.collect(yt, force_refresh=True)
        self.assertEqual(len(result['rows']), 1)
        self.assertFalse(list(Path(self.tmp.name).glob('token_*.tmp')))

    def test_revoked_session_is_auth_error_but_refresh_transport_error_is_network(self):
        from google.auth.exceptions import RefreshError, TransportError
        self.assertEqual(ys.safe_error(RefreshError('failed', {'error': 'invalid_grant'}))[1], 'auth')
        self.assertEqual(ys.safe_error(TransportError('DNS failure'))[1], 'network')

    def test_ai_relevance_review_cannot_add_source_ids(self):
        class Client:
            client = object()
        vids = [video('a', title='Midway 1942'), video('b', title='Midway airport')]
        with patch('ai.groq_client.GroqAiClient', return_value=Client()), patch.object(ys, 'request_json', return_value={'keep_ids': [0, 99, True]}):
            accepted = ys.review_relevance(vids, log=lambda _: None)
        self.assertEqual([v['id'] for v in accepted], ['a'])


class ReportTests(unittest.TestCase):
    def test_recovered_report_preserves_original_timestamp_and_skips_ai_rewrite(self):
        from channel import trend_report as tr
        sample = dict(rows=DemandTests().sample(), errors=['Sin conexión'], sampled_at=NOW.isoformat(), cached=True,
                      refresh_failed=True, cache_age_hours=12, queries=[])
        messages = []
        with tempfile.TemporaryDirectory() as tmp, patch.object(tr, 'REPORT_PATH', Path(tmp) / 'report.json'), \
                patch.object(ys, 'collect_sample', return_value=sample), patch.object(tr, 'refine_measured_topics') as ai:
            report = tr.build_report(log=messages.append)
        self.assertTrue(report['youtube']['refresh_failed'])
        self.assertEqual(report['youtube']['sampled_at'], NOW.isoformat())
        self.assertEqual(report['youtube']['cache_age_hours'], 12)
        self.assertTrue(report['proposals'])
        self.assertTrue(any('anterior conservada' in m for m in messages))
        self.assertFalse(any('menos de 6 horas' in m for m in messages))
        ai.assert_not_called()

    def test_no_youtube_data_keeps_calendar_out_of_recommendations(self):
        from channel import trend_report as tr
        with tempfile.TemporaryDirectory() as tmp, patch.object(tr, "REPORT_PATH", Path(tmp) / "report.json"):
            report = tr.build_report(with_youtube=False, with_llm=False, today=NOW.date(), log=lambda _: None)
        self.assertEqual(report["proposals"], [])
        self.assertTrue(report["editorial_ideas"])
        self.assertEqual(report["youtube"]["sample_size"], 0)

    def test_ai_cannot_replace_subject_or_metrics(self):
        from channel import trend_report as tr
        proposals = ys.rank_opportunities(DemandTests().sample())
        original = json.loads(json.dumps(proposals))
        class Client:
            client = object()
        edits = {"proposals": [{"id": 0, "topic": "Trafalgar battle", "score": 100, "views": 999999},
                                {"id": 0, "topic": "Roman concrete: underwater repairs", "archetype": "mechanism", "hook": "How does it endure?", "score": 100}]}
        with patch.object(ys, "request_json", return_value=edits):
            tr.refine_measured_topics(proposals, client=Client(), log=lambda _: None)
        self.assertEqual(proposals[0]["topic"], "Roman concrete: underwater repairs")
        self.assertEqual(proposals[0]["score"], original[0]["score"])
        self.assertEqual(proposals[0]["evidence"], original[0]["evidence"])

    def test_ai_cannot_invent_a_more_specific_unmeasured_story(self):
        from channel import trend_report as tr
        proposals = ys.rank_opportunities(DemandTests().sample())
        class Client:
            client = object()
        for topic in ['Roman concrete: secret letters from Julius Caesar', 'Roman concrete lasts 9000 years']:
            with patch.object(ys, 'request_json', return_value={'proposals': [{'id': 0, 'topic': topic}]}):
                tr.refine_measured_topics(proposals, client=Client(), log=lambda _: None)
            self.assertEqual(proposals[0]['topic'], 'Roman Concrete')


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_refresh_button_shows_worker_progress_and_loads_result(self):
        import threading
        from PyQt6.QtTest import QTest
        from PyQt6.QtCore import Qt
        from studio.studio_channel_controls import TrendsDialog
        from tests.test_studio_channel_controls import StudioStub
        tab = StudioStub()
        context = dict(category='Ancient Civilizations & Empires', language='en', region='US', video_format='short')
        report = dict(context=context, window_days=7, youtube={'sample_size': 1},
                      proposals=[{'topic': 'Roman Concrete', 'score': 25}])
        dlg = TrendsDialog(tab, dict(context=context, window_days=7, proposals=[]))
        dlg.show()
        release = threading.Event()
        called = {}

        def build(**kwargs):
            called.update(kwargs)
            kwargs['log']('[Tendencias] Buscando: ancient civilization...')
            release.wait(5)
            return report

        try:
            with patch('channel.trend_report.build_report', side_effect=build):
                QTest.mouseClick(dlg.btn_refresh, Qt.MouseButton.LeftButton)
                self.assertFalse(dlg.btn_refresh.isEnabled())
                self.assertTrue(dlg.progress_bar.isVisible())
                for _ in range(200):
                    QTest.qWait(10)
                    if 'ancient civilization' in dlg.progress_label.text():
                        break
                self.assertIn('ancient civilization', dlg.progress_label.text())
                self.assertFalse(dlg.category_filter.isEnabled())
                self.assertEqual({k: called[k] for k in context}, context)
                self.assertEqual(called['days'], 7)
                self.assertTrue(called['force_refresh'])
                release.set()
                for _ in range(200):
                    QTest.qWait(10)
                    if dlg.btn_refresh.isEnabled():
                        break
                self.assertTrue(dlg.btn_refresh.isEnabled())
                self.assertFalse(dlg.progress_bar.isVisible())
                self.assertEqual(dlg.table.rowCount(), 1)
                self.assertEqual(dlg.selected_proposal()['topic'], 'Roman Concrete')
        finally:
            release.set()
            if getattr(tab, '_trends_worker', None):
                tab._trends_worker.wait(5000)
            self.app.processEvents()
            dlg.close()
            tab.close()

    def test_recovered_sample_is_visible_with_original_date_and_explicit_warning(self):
        from studio.studio_channel_controls import TrendsDialog
        from tests.test_studio_channel_controls import StudioStub
        tab = StudioStub()
        dlg = TrendsDialog(tab, {'proposals': [{'topic': 'Roman Concrete'}],
                                'youtube': {'sample_size': 1, 'cached': True, 'refresh_failed': True,
                                            'cache_age_hours': 12, 'sampled_at': NOW.isoformat(),
                                            'errors': ['Sin conexión']}})
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertIn('resultado anterior', dlg.status_label.text())
        self.assertIn('no se pudo actualizar', dlg.status_label.text())
        self.assertNotIn('menos de 6 horas', dlg.status_label.text())
        self.assertIn('Sin conexión', dlg.warning_label.text())
        dlg.close()
        tab.close()

    def test_sorting_still_selects_correct_subject_and_links_evidence(self):
        from PyQt6.QtCore import Qt
        from studio.studio_channel_controls import TrendsDialog
        from tests.test_studio_channel_controls import StudioStub
        tab = StudioStub()
        report = {"proposals": [{"topic": "A", "score": 9, "evidence": [row("abc", "Title <unsafe>", "Channel")]},
                                {"topic": "B", "score": 80}], "youtube": {"sample_size": 2}}
        dlg = TrendsDialog(tab, report)
        dlg.table.sortItems(1, Qt.SortOrder.DescendingOrder)
        dlg.table.selectRow(0)
        self.assertEqual(dlg.selected_proposal()["topic"], "B")
        dlg.table.sortItems(1, Qt.SortOrder.AscendingOrder)
        dlg.table.selectRow(0)
        self.assertEqual(dlg.selected_proposal()["topic"], "A")
        dlg.show_evidence()
        self.assertIn("https://www.youtube.com/watch?v=abc", dlg.evidence_view.toHtml())
        self.assertIn("Title &lt;unsafe&gt;", dlg.evidence_view.toHtml())
        dlg.close(); tab.close()

    def test_empty_primary_list_and_separate_calendar(self):
        from studio.studio_channel_controls import TrendsDialog
        from tests.test_studio_channel_controls import StudioStub
        tab = StudioStub()
        dlg = TrendsDialog(tab, {"proposals": [], "editorial_ideas": [{"topic": "Trafalgar", "source": "anniversary"}],
                                 "youtube": {"errors": ["Cuota agotada"]}})
        self.assertEqual(dlg.table.rowCount(), 0)
        self.assertFalse(dlg.btn_use.isEnabled())
        self.assertIn("Cuota agotada", dlg.warning_label.text())
        dlg.tabs.setCurrentIndex(1)
        dlg.calendar_table.selectRow(0)
        self.assertEqual(dlg.selected_proposal()["topic"], "Trafalgar")
        self.assertIn("no se ha comprobado", dlg.evidence_view.toPlainText())
        dlg.close(); tab.close()

    def test_studio_category_language_and_long_vertical_are_captured(self):
        from PyQt6.QtWidgets import QComboBox, QRadioButton
        from studio.studio_channel_controls import studio_trend_options
        from tests.test_studio_channel_controls import StudioStub
        tab = StudioStub()
        tab.category_combo = QComboBox(); tab.category_combo.addItem("Misterios y Conspiraciones")
        tab.lang_es = QRadioButton(); tab.lang_es.setChecked(True)
        tab.platform_combo.addItem("9:16 · Vertical Largo", {"platform": "youtube_vertical"})
        tab.platform_combo.setCurrentIndex(1)
        options = studio_trend_options(tab)
        self.assertEqual(options["video_format"], "long")
        self.assertEqual(options["language"], "es")
        self.assertEqual(options["category"], "Misterios y Conspiraciones")
        tab.platform_combo.addItem("Shorts", {"platform": "youtube_short"})
        tab.platform_combo.setCurrentIndex(2)
        self.assertEqual(studio_trend_options(tab)["video_format"], "short")
        tab.close()


if __name__ == "__main__":
    unittest.main()
