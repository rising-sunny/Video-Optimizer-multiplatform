import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publish import instagram_uploader

# upload_from_metadata resuelve la cuenta (marca de los hashtags): sin esto el test
# consultaba la Graph API real y corria la investigacion de titulos.
FAKE_IDENTITY = {"access_token": "token-falso", "ig_user_id": "1784", "instagram_username": "stunning.foh",
                 "instagram_name": "Stunning Facts of History", "page_id": "1291", "page_name": "Stunning Facts of History"}


class InstagramUploaderTests(unittest.TestCase):
    def test_upload_from_metadata_prefers_instagram_metadata_file(self):
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
                        "title": "Facebook Title",
                        "description": "Facebook description",
                    }
                ),
                encoding="utf-8",
            )
            (root / "instagram_metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Roswell on Instagram",
                        "description": "The caption optimized for Instagram Reels.",
                    }
                ),
                encoding="utf-8",
            )
            (root / "short.mp4").write_bytes(b"fake-video")

            fake_result = {
                "media_id": "178900000001",
                "container_id": "179800000001",
                "url": "https://www.instagram.com/reel/CODEX123/",
                "permalink_url": "https://www.instagram.com/reel/CODEX123/",
                "status": "published",
                "ig_user_id": "17841472326324371",
                "instagram_username": "stunning.revelations",
            }

            with patch.object(instagram_uploader, "upload_video", return_value=fake_result) as upload_mock,                  patch.object(instagram_uploader, "_resolve_instagram_identity", return_value=FAKE_IDENTITY):
                result = instagram_uploader.upload_from_metadata(str(root), share_to_feed=True, optimize=False)

            self.assertEqual(result["media_id"], "178900000001")
            upload_mock.assert_called_once()
            self.assertEqual(upload_mock.call_args.kwargs["title"], "Roswell on Instagram")
            self.assertEqual(
                upload_mock.call_args.kwargs["description"],
                "The caption optimized for Instagram Reels.",
            )
            self.assertTrue(upload_mock.call_args.kwargs["share_to_feed"])

    def test_upload_from_metadata_persists_instagram_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "instagram_metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Instagram Title",
                        "description": "Instagram description",
                    }
                ),
                encoding="utf-8",
            )
            (root / "short.mp4").write_bytes(b"fake-video")

            fake_result = {
                "media_id": "178900000002",
                "container_id": "179800000002",
                "url": "https://www.instagram.com/reel/CODEX456/",
                "permalink_url": "https://www.instagram.com/reel/CODEX456/",
                "status": "published",
                "ig_user_id": "17841472326324371",
                "instagram_username": "stunning.revelations",
                "cloudinary_url": "https://res.cloudinary.com/demo/video/upload/v1/example.mp4",
                "cloudinary_public_id": "video_optimizer/instagram/example",
            }

            with patch.object(instagram_uploader, "upload_video", return_value=fake_result),                  patch.object(instagram_uploader, "_resolve_instagram_identity", return_value=FAKE_IDENTITY):
                instagram_uploader.upload_from_metadata(str(root), optimize=False)

            result_path = root / "instagram_upload_result.json"
            self.assertTrue(result_path.exists())
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["media_id"], "178900000002")
            self.assertEqual(saved["url"], "https://www.instagram.com/reel/CODEX456/")
            self.assertEqual(saved["instagram_username"], "stunning.revelations")
            self.assertEqual(saved["title"], "Instagram Title")
            self.assertEqual(saved["description"], "Instagram description")
            archive_files = list(root.glob("instagram_upload_result_*.json"))
            self.assertEqual(len(archive_files), 1)
            archived = json.loads(archive_files[0].read_text(encoding="utf-8"))
            self.assertEqual(archived["media_id"], "178900000002")


if __name__ == "__main__":
    unittest.main()
