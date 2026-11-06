import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import documentary_youtube_core as core
import publish_documentary as app


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = "a" * 32
        self.addCleanup(patch.stopall)
        patch.dict(core.__dict__, core.__dict__.copy()).start()
        patch.object(app, "JOBS", self.root / "jobs").start()
        patch.object(app, "PUBLICATIONS", self.root / "publications").start()
        self.url = "https://ai-thumbnails.s3.amazonaws.com/example.png"

    def fixture(self, job=None, channel="stunning-revelations"):
        job = job or self.job
        folder = app.JOBS / job
        folder.mkdir(parents=True)
        for name, data in (("video.mp4", b"approved video"), ("subtitles.srt", b"approved subtitles")):
            (folder / name).write_bytes(data)
        (folder / "review.json").write_text(json.dumps(dict(approved=True)))
        (folder / "metadata.json").write_text(json.dumps(dict(title="A different documentary",
            description="Visual credits: complete\nMusic: verified", channel=channel, language="en", is_short=False)))
        approval = dict(quality_approved=True, job_id=job, channel=channel,
            metadata_sha256=core.sha(folder / "metadata.json"), review_sha256=core.sha(folder / "review.json"),
            files={"video": {"sha256": core.sha(folder / "video.mp4")},
                   "subtitles": {"sha256": core.sha(folder / "subtitles.srt")}})
        (folder / "approval.json").write_text(json.dumps(approval))
        return ["--job-id", job, "--approval-sha256", core.sha(folder / "approval.json"),
                "--thumbnail-url", self.url]

    def test_inspect_verifies_saved_files_without_auth_network_or_runtime_writes(self):
        argv = self.fixture() + ["--inspect"]
        with patch.object(core, "service") as service, patch.object(core, "main") as main, \
             patch.object(core, "emit"):
            app.main(argv)
            service.assert_not_called()
            main.assert_not_called()
        self.assertFalse(app.PUBLICATIONS.exists())

    def test_other_job_and_title_replace_chrome_dome_constants(self):
        args = app.arguments(self.fixture() + ["--publish"])
        app.configure(args)
        self.assertEqual(core.JOB, self.job)
        self.assertEqual(core.TITLE, "A different documentary")
        self.assertEqual(core.CAPTION_NAME, "English")
        self.assertEqual(core.TAGS, [])

    def test_other_channel_uses_its_exact_authorized_identity(self):
        args = app.arguments(self.fixture(channel="stunning-facts-of-history") + ["--inspect"])
        app.configure(args)
        self.assertEqual(core.CHANNEL_ID, app.CHANNELS["stunning-facts-of-history"])

    def test_modified_approved_video_is_rejected(self):
        args = app.arguments(self.fixture() + ["--inspect"])
        (app.JOBS / self.job / "video.mp4").write_bytes(b"different")
        with self.assertRaisesRegex(core.Blocked, "file_changed"):
            app.configure(args)

    def test_fabricated_approval_fingerprint_is_rejected(self):
        args = app.arguments(self.fixture() + ["--inspect"])
        args.approval_sha256 = "0" * 64
        with self.assertRaisesRegex(core.Blocked, "file_changed"):
            app.configure(args)

    def test_resume_requires_the_exact_saved_video_id(self):
        argv = self.fixture()
        output = app.PUBLICATIONS / self.job
        output.mkdir(parents=True)
        (output / "youtube-receipt.json").write_text(json.dumps(dict(video_id="Saved123456")))
        args = app.arguments(argv + ["--resume-existing", "--video-id", "Wrong123456"])
        with self.assertRaisesRegex(core.Blocked, "saved_video_id_required"):
            app.configure(args)
        args.video_id = "Saved123456"
        app.configure(args)
        self.assertEqual(core.RESUME_VIDEO_ID, "Saved123456")

    def test_existing_chrome_dome_caption_name_is_preserved(self):
        args = app.arguments(self.fixture(job=app.LEGACY_CHROME_DOME) + ["--inspect"])
        app.configure(args)
        self.assertEqual(core.CAPTION_NAME, "English - Chrome Dome")

    def test_missing_action_cannot_publish_by_default(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            app.arguments(self.fixture())

    def test_invalid_thumbnail_protocol_is_rejected(self):
        args = app.arguments(self.fixture() + ["--inspect"])
        args.thumbnail_url = "file:///etc/passwd"
        with self.assertRaisesRegex(core.Blocked, "thumbnail_https"):
            app.configure(args)

    def test_duplicate_check_matches_actual_future_title_and_follows_pages(self):
        args = app.arguments(self.fixture() + ["--inspect"])
        app.configure(args)
        api = MagicMock()
        api.playlistItems().list().execute.side_effect = [dict(items=[], nextPageToken="next"),
            dict(items=[dict(snippet=dict(title="A DIFFERENT   DOCUMENTARY"))])]
        with self.assertRaisesRegex(core.Blocked, "already_exists"):
            app.duplicate_check(api, "uploads")

    def test_future_title_does_not_reuse_chrome_dome_tags_or_duplicate_keyword(self):
        args = app.arguments(self.fixture() + ["--inspect"])
        app.configure(args)
        api = MagicMock()
        api.playlistItems().list().execute.return_value = dict(items=[dict(snippet=dict(title="Chrome Dome"))])
        app.duplicate_check(api, "uploads")
        self.assertEqual(core.TAGS, [])


if __name__ == "__main__":
    unittest.main()
