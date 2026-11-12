import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import documentary_youtube_core as p


class Response(dict):
    def __init__(self, status, **headers):
        super().__init__(headers)
        self.status = status


class ApiError(Exception):
    def __init__(self, status, reason):
        self.resp = Response(status)
        self.content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(p, "BASE", self.folder).start()
        patch.object(p, "emit").start()
        (self.folder / "video.mp4").write_bytes(b"video-data")
        self.api = MagicMock()
        self.state = {}
        self.saved = []
        self.checkpoint = lambda: self.saved.append(copy.deepcopy(self.state))
        self.snippet = dict(title=p.TITLE, description="all credits")
        self.video_id = "Abc123XyZ09"

    def test_session_is_saved_before_any_video_bytes_and_upload_stays_private(self):
        def http(uri, **kwargs):
            if kwargs["method"] == "POST":
                self.assertTrue(self.saved[-1]["insert_intent"])
                self.assertEqual(json.loads(kwargs["body"])["status"]["privacyStatus"], "private")
                return Response(200, location="https://www.googleapis.com/upload/session"), b""
            self.assertEqual(self.saved[-1]["session_uri"], uri)
            if not kwargs["body"]:
                return Response(308), b""
            return Response(200), json.dumps(dict(id=self.video_id)).encode()
        self.api._http.request.side_effect = http
        p.transfer(self.api, self.snippet, self.state, self.checkpoint)
        self.assertEqual(self.state["video_id"], self.video_id)
        self.assertEqual(self.state["state"], "uploaded_private")
        self.api.videos().update.assert_not_called()

    def test_resume_after_lost_final_response_recovers_id_without_insert_or_resend(self):
        self.state.update(insert_intent=True, session_uri="https://www.googleapis.com/upload/session")
        self.api._http.request.return_value = Response(200), json.dumps(dict(id=self.video_id)).encode()
        p.transfer(self.api, self.snippet, self.state, self.checkpoint)
        self.assertEqual(self.state["video_id"], self.video_id)
        self.assertEqual(self.api._http.request.call_count, 1)
        self.assertEqual(self.api._http.request.call_args.kwargs["method"], "PUT")
        self.assertEqual(self.api._http.request.call_args.kwargs["body"], b"")

    def test_partial_upload_queries_server_then_sends_only_remaining_bytes(self):
        self.state.update(insert_intent=True, session_uri="https://www.googleapis.com/upload/session")
        self.api._http.request.side_effect = [
            (Response(308, range="bytes=0-4"), b""),
            (Response(200), json.dumps(dict(id=self.video_id)).encode())]
        p.transfer(self.api, self.snippet, self.state, self.checkpoint)
        self.assertEqual(self.api._http.request.call_args.kwargs["body"], b"-data")
        self.assertEqual(self.api._http.request.call_args.kwargs["headers"]["Content-Range"], "bytes 5-9/10")

    def test_ambiguous_initialization_never_creates_second_session(self):
        self.state["insert_intent"] = True
        with self.assertRaisesRegex(p.Blocked, "ambiguous_upload"):
            p.transfer(self.api, self.snippet, self.state, self.checkpoint)
        self.api._http.request.assert_not_called()

    def test_expired_session_is_preserved_and_never_replaced(self):
        self.state.update(insert_intent=True, session_uri="https://www.googleapis.com/upload/session")
        self.api._http.request.return_value = Response(410), b"expired"
        with self.assertRaisesRegex(p.Blocked, "http_410"):
            p.transfer(self.api, self.snippet, self.state, self.checkpoint)
        self.assertEqual(self.api._http.request.call_count, 1)
        self.assertTrue(self.state["session_uri"])

    def test_known_video_id_never_reuploads(self):
        self.state["video_id"] = self.video_id
        p.transfer(self.api, self.snippet, self.state, self.checkpoint)
        self.api._http.request.assert_not_called()

    def test_wrong_owner_blocks(self):
        self.api.channels().list().execute.return_value = dict(items=[dict(id="wrong")])
        with self.assertRaisesRegex(p.Blocked, "identity_mismatch"):
            p.owner(self.api)

    def test_duplicate_search_follows_pages_and_includes_private_uploads_playlist(self):
        self.api.playlistItems().list().execute.side_effect = [
            dict(items=[], nextPageToken="second"),
            dict(items=[dict(snippet=dict(title="Operation Chrome Dome: documentary"))])]
        with self.assertRaisesRegex(p.Blocked, "already_exists"):
            p.no_duplicate(self.api, "uploads")
        self.assertEqual(self.api.playlistItems().list.call_args.kwargs["pageToken"], "second")

    def caption_import(self):
        module = types.ModuleType("googleapiclient.http")
        module.MediaFileUpload = lambda *args, **kwargs: (args, kwargs)
        parent = types.ModuleType("googleapiclient")
        patch.dict(sys.modules, {"googleapiclient": parent, "googleapiclient.http": module}).start()

    def test_caption_transport_ambiguity_does_not_insert_a_duplicate(self):
        self.caption_import()
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_intent=True)
        self.api.captions().list().execute.return_value = dict(items=[])
        with self.assertRaisesRegex(p.Blocked, "ambiguous_caption_insert"):
            p.assets(self.api, self.state, self.checkpoint, {}, wait=lambda _: None)
        self.api.captions().insert.assert_not_called()

    def test_completed_caption_is_reconciled_without_reinserting(self):
        self.caption_import()
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_intent=True)
        self.api.captions().list().execute.return_value = dict(items=[dict(id="caption", snippet={
            "language": "en", "name": p.CAPTION_NAME})])
        p.assets(self.api, self.state, self.checkpoint, {})
        self.assertEqual(self.state["caption_id"], "caption")
        self.api.captions().insert.assert_not_called()

    def ready_video(self, privacy="private"):
        return dict(snippet=dict(self.snippet, channelId=p.CHANNEL_ID),
                    status=dict(privacyStatus=privacy, uploadStatus="processed"),
                    processingDetails=dict(processingStatus="succeeded"))

    def caption_row(self, status="serving"):
        return dict(id="caption", snippet=dict(language="en", name=p.CAPTION_NAME, status=status))

    def test_no_publication_until_thumbnail_and_caption_are_ready(self):
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_id="caption")
        self.api.videos().list().execute.return_value = dict(items=[self.ready_video()])
        self.api.captions().list().execute.return_value = dict(items=[self.caption_row("syncing")])
        with self.assertRaisesRegex(p.Blocked, "processing_pending"):
            p.finalize(self.api, self.snippet, self.state, self.checkpoint, wait=lambda _: None, polls=2)
        self.api.videos().update.assert_not_called()

    def test_publication_is_last_and_read_back(self):
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_id="caption")
        self.api.videos().list().execute.side_effect = [
            dict(items=[self.ready_video()]), dict(items=[self.ready_video("public")])]
        self.api.captions().list().execute.return_value = dict(items=[self.caption_row()])
        p.finalize(self.api, self.snippet, self.state, self.checkpoint, wait=lambda _: None)
        self.api.videos().update.assert_called_once()
        self.assertTrue(any(s.get("publish_intent") for s in self.saved))
        self.assertEqual(self.state["state"], "published")

    def test_caption_not_found_before_first_insert_is_empty_not_a_fatal_failure(self):
        self.caption_import()
        self.state.update(video_id=self.video_id, thumbnail_set=True)
        self.api.captions().list().execute.side_effect = ApiError(404, "captionNotFound")
        self.api.captions().insert.return_value.execute.return_value = dict(id="caption")
        p.assets(self.api, self.state, self.checkpoint, {}, wait=lambda _: None)
        self.assertEqual(self.state["caption_id"], "caption")
        self.assertTrue(self.state["caption_intent"])
        self.api.captions().insert.assert_called_once()

    def test_caption_permission_and_unrelated_404_errors_are_not_hidden(self):
        self.state["video_id"] = self.video_id
        for code, reason in ((403, "forbidden"), (404, "videoNotFound"), (500, "backendError")):
            with self.subTest(reason=reason):
                self.api.captions().list().execute.side_effect = ApiError(code, reason)
                with self.assertRaises(ApiError):
                    p.caption_tracks(self.api, self.state)

    def test_saved_caption_id_is_preserved_without_inserting_again(self):
        self.caption_import()
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_intent=True, caption_id="caption")
        p.assets(self.api, self.state, self.checkpoint, {}, wait=lambda _: None)
        self.api.captions().list.assert_not_called()
        self.api.captions().insert.assert_not_called()

    def test_temporarily_missing_inserted_caption_is_polled_by_video_not_reinserted(self):
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_intent=True, caption_id="caption")
        self.api.videos().list().execute.side_effect = [
            dict(items=[self.ready_video()]), dict(items=[self.ready_video()]),
            dict(items=[self.ready_video("public")])]
        self.api.captions().list().execute.side_effect = [ApiError(404, "captionNotFound"),
                                                        dict(items=[self.caption_row()])]
        waits = []
        p.finalize(self.api, self.snippet, self.state, self.checkpoint, wait=waits.append)
        self.assertEqual(waits, [20])
        self.assertEqual(self.state["state"], "published")
        self.api.captions().insert.assert_not_called()
        for call in self.api.captions().list.call_args_list:
            self.assertNotIn("id", call.kwargs)

    def test_missing_existing_caption_never_becomes_approval_or_new_track(self):
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_id="caption")
        self.api.videos().list().execute.return_value = dict(items=[self.ready_video()])
        self.api.captions().list().execute.side_effect = ApiError(404, "captionNotFound")
        with self.assertRaisesRegex(p.Blocked, "processing_pending"):
            p.finalize(self.api, self.snippet, self.state, self.checkpoint, wait=lambda _: None, polls=2)
        self.api.captions().insert.assert_not_called()
        self.api.videos().update.assert_not_called()

    def test_ambiguous_caption_creation_is_reconciled_after_delayed_visibility(self):
        self.caption_import()
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_intent=True)
        self.api.captions().list().execute.side_effect = [ApiError(404, "captionNotFound"),
                                                        dict(items=[self.caption_row()])]
        p.assets(self.api, self.state, self.checkpoint, {}, wait=lambda _: None)
        self.assertEqual(self.state["caption_id"], "caption")
        self.api.captions().insert.assert_not_called()

    def test_saved_caption_with_wrong_language_cannot_publish(self):
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_id="caption")
        self.api.videos().list().execute.return_value = dict(items=[self.ready_video()])
        row = self.caption_row()
        row["snippet"]["language"] = "es"
        self.api.captions().list().execute.return_value = dict(items=[row])
        with self.assertRaisesRegex(p.Blocked, "caption_identity_changed"):
            p.finalize(self.api, self.snippet, self.state, self.checkpoint, wait=lambda _: None)
        self.api.videos().update.assert_not_called()

    def test_video_must_finish_processing_before_caption_actions(self):
        self.state["video_id"] = self.video_id
        first = self.ready_video()
        first["status"]["uploadStatus"] = "uploaded"
        self.api.videos().list().execute.side_effect = [dict(items=[first]), dict(items=[self.ready_video()])]
        waits = []
        p.wait_for_video(self.api, self.snippet, self.state, self.checkpoint, wait=waits.append)
        self.assertEqual(waits, [20])
        self.api.captions.assert_not_called()

    def test_resume_without_saved_id_never_attempts_upload(self):
        self.assert_main_resume(dict(), missing_id=True)

    def test_resume_existing_id_cannot_call_transfer_or_duplicate_search(self):
        self.assert_main_resume(dict(video_id=self.video_id), missing_id=False)

    def test_resume_refuses_other_video_id_before_network_calls(self):
        self.assert_main_resume(dict(video_id="Wrong123456"), missing_id=True)

    def assert_main_resume(self, saved, missing_id):
        (self.folder / "metadata.json").write_text("{}")
        state = dict(job_id=p.JOB, channel_id=p.CHANNEL_ID, video_sha256=p.PINS["video.mp4"],
                     approval_sha256=p.PINS["approval.json"], metadata_sha256=p.sha(self.folder / "metadata.json"),
                     subtitles_sha256=p.PINS["subtitles.srt"], thumbnail_source=p.THUMBNAIL_URL, **saved)
        (self.folder / "youtube-receipt.json").write_text(json.dumps(state))
        with patch.object(p, "OUT", self.folder), patch.object(p.os, "geteuid", return_value=1001), \
             patch.object(p, "RESUME_VIDEO_ID", self.video_id), \
             patch.object(sys, "argv", ["publish", "--resume-existing"]), \
             patch.object(p, "preflight", return_value=self.snippet), \
             patch.object(p, "service", return_value=self.api), patch.object(p, "owner"), \
             patch.object(p, "thumbnail", return_value=dict(path=str(self.folder / "video.mp4"))), \
             patch.object(p, "transfer") as transfer, patch.object(p, "no_duplicate") as duplicate, \
             patch.object(p, "video"), patch.object(p, "wait_for_video"), \
             patch.object(p, "assets"), patch.object(p, "finalize"):
            if missing_id:
                with self.assertRaisesRegex(p.Blocked, "saved_video_id_required"):
                    p.main()
            else:
                p.main()
            transfer.assert_not_called()
            duplicate.assert_not_called()

    def test_changed_metadata_prevents_making_video_public(self):
        self.state.update(video_id=self.video_id, thumbnail_set=True, caption_id="caption")
        current = self.ready_video()
        current["snippet"]["description"] = "credits deleted"
        self.api.videos().list().execute.return_value = dict(items=[current])
        with self.assertRaisesRegex(p.Blocked, "metadata_readback_changed"):
            p.finalize(self.api, self.snippet, self.state, self.checkpoint, wait=lambda _: None)
        self.api.videos().update.assert_not_called()

    def test_preflight_requires_exact_original_approval_video_and_metadata(self):
        metadata = dict(self.snippet, channel=p.CHANNEL, language="en", is_short=False,
                        description="Visual credits: complete\nMusic: complete")
        (self.folder / "metadata.json").write_text(json.dumps(metadata))
        (self.folder / "review.json").write_text(json.dumps(dict(approved=True)))
        (self.folder / "subtitles.srt").write_text("real timed subtitles")
        approval = dict(quality_approved=True, job_id=p.JOB, channel=p.CHANNEL,
                        metadata_sha256=p.sha(self.folder / "metadata.json"),
                        review_sha256=p.sha(self.folder / "review.json"))
        (self.folder / "approval.json").write_text(json.dumps(approval))
        pins = {name: p.sha(self.folder / name) for name in p.PINS}
        with patch.object(p, "PINS", pins):
            self.assertEqual(p.preflight()["title"], p.TITLE)
            (self.folder / "video.mp4").write_bytes(b"different render")
            with self.assertRaisesRegex(p.Blocked, "file_changed"):
                p.preflight()


if __name__ == "__main__":
    unittest.main()
