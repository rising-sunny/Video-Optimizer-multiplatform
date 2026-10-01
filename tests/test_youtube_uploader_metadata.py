import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import youtube_uploader


class YouTubeUploaderMetadataTests(unittest.TestCase):
    def test_upload_from_metadata_prefers_youtube_metadata_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Fallback Title",
                        "description": "Fallback description",
                        "tags": ["fallback"],
                    }
                ),
                encoding="utf-8",
            )
            (root / "youtube_metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Roswell: 1947 Cover-Up",
                        "description": "Dedicated YouTube description",
                        "tags": ["history", "mystery", "roswell"],
                    }
                ),
                encoding="utf-8",
            )
            (root / "short.mp4").write_bytes(b"fake-video")

            fake_result = {
                "video_id": "abc123",
                "url": "https://youtube.com/watch?v=abc123",
                "status": "private",
                "thumbnail_set": False,
            }

            with patch.object(youtube_uploader, "upload_video", return_value=fake_result) as upload_mock:
                result = youtube_uploader.upload_from_metadata(str(root), privacy_status="private")

            self.assertEqual(result["video_id"], "abc123")
            upload_mock.assert_called_once()
            self.assertEqual(upload_mock.call_args.kwargs["title"], "Roswell: 1947 Cover-Up")
            self.assertEqual(upload_mock.call_args.kwargs["description"], "Dedicated YouTube description")
            self.assertEqual(upload_mock.call_args.kwargs["tags"], ["history", "mystery", "roswell"])

            upload_result_path = root / "upload_result.json"
            self.assertTrue(upload_result_path.exists())
            saved = json.loads(upload_result_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["video_id"], "abc123")
            self.assertEqual(saved["privacy"], "private")
            archive_files = list(root.glob("upload_result_*.json"))
            self.assertEqual(len(archive_files), 1)
            archived = json.loads(archive_files[0].read_text(encoding="utf-8"))
            self.assertEqual(archived["video_id"], "abc123")


if __name__ == "__main__":
    unittest.main()
