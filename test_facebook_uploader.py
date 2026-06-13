import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import facebook_uploader


class FacebookUploaderTests(unittest.TestCase):
    def test_upload_from_metadata_prefers_facebook_metadata_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "metadata.json").write_text(
                json.dumps(
                    {
                        "title": "YouTube Title",
                        "description": "YouTube description",
                    }
                ),
                encoding="utf-8",
            )
            (root / "facebook_metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Roswell 1947",
                        "description": "Recovered wreckage in the New Mexico desert.",
                    }
                ),
                encoding="utf-8",
            )
            (root / "short.mp4").write_bytes(b"fake-video")

            fake_result = {
                "video_id": "123456789",
                "url": "https://www.facebook.com/reel/123456789",
                "status": "published",
                "page_id": "987654321",
                "page_name": "Stunning Revelations",
            }

            with patch.object(facebook_uploader, "upload_video", return_value=fake_result) as upload_mock:
                result = facebook_uploader.upload_from_metadata(str(root), video_state="PUBLISHED")

            self.assertEqual(result["video_id"], "123456789")
            upload_mock.assert_called_once()
            self.assertEqual(upload_mock.call_args.kwargs["title"], "Roswell 1947")
            self.assertEqual(upload_mock.call_args.kwargs["description"], "Recovered wreckage in the New Mexico desert.")
            self.assertEqual(upload_mock.call_args.kwargs["video_state"], "PUBLISHED")

            result_path = root / "facebook_upload_result.json"
            self.assertTrue(result_path.exists())
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["video_id"], "123456789")
            self.assertEqual(saved["url"], "https://www.facebook.com/reel/123456789")
            self.assertEqual(saved["video_state"], "PUBLISHED")
            archive_files = list(root.glob("facebook_upload_result_*.json"))
            self.assertEqual(len(archive_files), 1)
            archived = json.loads(archive_files[0].read_text(encoding="utf-8"))
            self.assertEqual(archived["video_id"], "123456789")

    def test_upload_from_metadata_persists_scheduled_facebook_reel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "facebook_metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Roswell: Scheduled",
                        "description": "A scheduled Facebook Reel.",
                    }
                ),
                encoding="utf-8",
            )
            (root / "short.mp4").write_bytes(b"fake-video")

            fake_result = {
                "video_id": "555666777",
                "url": None,
                "permalink_url": "https://www.facebook.com/reel/555666777",
                "status": "scheduled",
                "page_id": "987654321",
                "page_name": "Stunning Revelations",
            }

            with patch.object(facebook_uploader, "upload_video", return_value=fake_result) as upload_mock:
                result = facebook_uploader.upload_from_metadata(
                    str(root),
                    video_state="PUBLISHED",
                    scheduled_publish_time="2099-01-01T12:00:00Z",
                )

            self.assertEqual(result["video_id"], "555666777")
            upload_mock.assert_called_once()
            self.assertEqual(upload_mock.call_args.kwargs["scheduled_publish_time"], "2099-01-01T12:00:00Z")

            result_path = root / "facebook_upload_result.json"
            self.assertTrue(result_path.exists())
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["video_id"], "555666777")
            self.assertEqual(saved["permalink_url"], "https://www.facebook.com/reel/555666777")
            self.assertEqual(saved["video_state"], "SCHEDULED")
            self.assertTrue(saved["scheduled"])
            self.assertEqual(saved["publish_at"], "2099-01-01T12:00:00Z")
            archive_files = list(root.glob("facebook_upload_result_*.json"))
            self.assertEqual(len(archive_files), 1)


if __name__ == "__main__":
    unittest.main()
