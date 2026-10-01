import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import instagram_uploader
import vps_publish_scheduler


class VpsPublishSchedulerTests(unittest.TestCase):
    def test_remote_shell_uses_keepalive_and_retries(self):
        with patch.object(vps_publish_scheduler, "_ssh_host", return_value="root@example.com"):
            with patch.object(vps_publish_scheduler, "_run_local_command", return_value="ok") as run_mock:
                result = vps_publish_scheduler._remote_shell("echo ok")

        self.assertEqual(result, "ok")
        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][0], "ssh")
        self.assertIn("BatchMode=yes", args[0])
        self.assertIn("ServerAliveInterval=15", args[0])
        self.assertIn("PreferredAuthentications=publickey", args[0])
        self.assertEqual(args[0][-2:], ["root@example.com", "echo ok"])
        self.assertEqual(kwargs["retries"], vps_publish_scheduler.SSH_RETRY_COUNT)
        self.assertEqual(kwargs["retry_delay_seconds"], vps_publish_scheduler.SSH_RETRY_BACKOFF_SECONDS)
        self.assertIs(kwargs["retryable"], vps_publish_scheduler._is_retryable_ssh_error)

    def test_run_local_command_retries_retryable_ssh_errors(self):
        failures = [
            subprocess.CompletedProcess(
                args=["scp"],
                returncode=1,
                stdout="",
                stderr="client_loop: send disconnect: Connection reset",
            ),
            subprocess.CompletedProcess(
                args=["scp"],
                returncode=0,
                stdout="done",
                stderr="",
            ),
        ]

        with patch.object(vps_publish_scheduler.subprocess, "run", side_effect=failures) as run_mock:
            with patch.object(vps_publish_scheduler.time, "sleep") as sleep_mock:
                output = vps_publish_scheduler._run_local_command(
                    ["scp", "source", "dest"],
                    retries=1,
                    retry_delay_seconds=2,
                    retryable=vps_publish_scheduler._is_retryable_ssh_error,
                )

        self.assertEqual(output, "done")
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2.0)

    def test_sync_folder_to_vps_uses_scp_keepalive_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            folder = root / "daily_shorts" / "2099-01-01_3"
            folder.mkdir(parents=True, exist_ok=True)
            expected_remote_parent = f"root@example.com:{vps_publish_scheduler._vps_deploy_dir().as_posix()}/daily_shorts/"

            with patch.object(vps_publish_scheduler, "_ssh_host", return_value="root@example.com"):
                with patch.object(vps_publish_scheduler, "_remote_shell") as remote_mock:
                    with patch.object(vps_publish_scheduler, "_run_local_command", return_value="") as run_mock:
                        remote_path = vps_publish_scheduler._sync_folder_to_vps(
                            folder,
                            "daily_shorts/2099-01-01_3",
                        )

        remote_mock.assert_called_once()
        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][0], "scp")
        self.assertIn("ServerAliveInterval=15", args[0])
        self.assertIn("Compression=yes", args[0])
        self.assertEqual(args[0][-2:], ["2099-01-01_3", expected_remote_parent])
        self.assertEqual(kwargs["cwd"], str(folder.parent))
        self.assertEqual(
            remote_path.as_posix(),
            f"{vps_publish_scheduler._vps_deploy_dir().as_posix()}/daily_shorts/2099-01-01_3",
        )

    def test_enqueue_instagram_job_writes_queue_and_placeholder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            folder = root / "daily_shorts" / "2099-01-01_1"
            folder.mkdir(parents=True, exist_ok=True)

            original_project_dir = vps_publish_scheduler.PROJECT_DIR
            try:
                vps_publish_scheduler.PROJECT_DIR = root
                with patch.object(vps_publish_scheduler, "_ssh_host", return_value=None):
                    job = vps_publish_scheduler.enqueue_job(
                        folder=folder,
                        title="Roswell Reel",
                        publish_at="2099-01-01T12:00:00Z",
                        instagram=True,
                    )

                queue_path = root / "scheduler_queue" / "scheduled_publish_jobs.json"
                self.assertTrue(queue_path.exists())
                queue_payload = json.loads(queue_path.read_text(encoding="utf-8"))
                self.assertEqual(len(queue_payload), 1)
                self.assertEqual(queue_payload[0]["id"], job["id"])
                self.assertTrue(queue_payload[0]["instagram"])
                self.assertEqual(queue_payload[0]["relative_folder"], str(folder.relative_to(root)))

                placeholder_records = list(folder.glob("instagram_upload_result*.json"))
                self.assertGreaterEqual(len(placeholder_records), 1)
                payloads = [json.loads(path.read_text(encoding="utf-8")) for path in placeholder_records]
                self.assertTrue(any(item.get("scheduled") for item in payloads))
                self.assertTrue(any(item.get("status") == "queued_on_vps" for item in payloads))
            finally:
                vps_publish_scheduler.PROJECT_DIR = original_project_dir

    def test_process_due_jobs_marks_instagram_job_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            folder = root / "daily_shorts" / "2099-01-01_2"
            folder.mkdir(parents=True, exist_ok=True)

            original_project_dir = vps_publish_scheduler.PROJECT_DIR
            try:
                vps_publish_scheduler.PROJECT_DIR = root
                queue_path = root / "scheduler_queue" / "scheduled_publish_jobs.json"
                queue_path.parent.mkdir(parents=True, exist_ok=True)
                queue_payload = [
                    {
                        "id": "job123",
                        "created_at": "2099-01-01T00:00:00Z",
                        "origin": "test",
                        "folder": str(folder),
                        "relative_folder": str(folder.relative_to(root)),
                        "title": "Instagram Test",
                        "youtube": False,
                        "facebook": False,
                        "instagram": True,
                        "privacy": "private",
                        "publish_at": "2000-01-01T00:00:00Z",
                        "status": "queued",
                        "attempt_count": 0,
                        "next_attempt_at": "2000-01-01T00:00:00Z",
                        "last_error": None,
                        "platform_results": {},
                    }
                ]
                queue_path.write_text(json.dumps(queue_payload, ensure_ascii=False, indent=2), encoding="utf-8")

                fake_result = {
                    "media_id": "178900000009",
                    "container_id": "179800000009",
                    "url": "https://www.instagram.com/reel/CODEX999/",
                    "permalink_url": "https://www.instagram.com/reel/CODEX999/",
                    "status": "published",
                }
                with patch.object(instagram_uploader, "upload_from_metadata", return_value=fake_result) as upload_mock:
                    result = vps_publish_scheduler.process_due_jobs(limit=1)

                self.assertEqual(result["processed"], 1)
                self.assertEqual(result["succeeded"], 1)
                upload_mock.assert_called_once_with(str(folder), share_to_feed=True)

                saved_queue = json.loads(queue_path.read_text(encoding="utf-8"))
                self.assertEqual(saved_queue[0]["status"], "completed")
                self.assertEqual(saved_queue[0]["platform_results"]["instagram"]["media_id"], "178900000009")
            finally:
                vps_publish_scheduler.PROJECT_DIR = original_project_dir


if __name__ == "__main__":
    unittest.main()
