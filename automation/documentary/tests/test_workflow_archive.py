import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install_workflow as archive


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_runtime_snapshot_uses_declared_python_sources_without_executing_them(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        (runtime / "documentary_common.py").write_text(
            "raise AssertionError('must not import')\nMODULES=('worker.py','secrets.json','auth.json')\n")
        (runtime / "worker.py").write_text("print('source only')\n")
        (runtime / "chrome_dome_example.py").write_text("# archived source\n")
        (runtime / "secrets.json").write_text("credential-value-must-not-copy")
        (runtime / "auth.json").write_text("credential-value-must-not-copy")
        expected = {"worker.py": archive.digest((runtime / "worker.py").read_bytes())}
        result = archive.snapshot_runtime(runtime, self.root / "snapshot", expected)
        self.assertEqual(result["matched_reference_modules"], 1)
        self.assertEqual(set(result["files"]), {"worker.py", "documentary_common.py", "chrome_dome_example.py"})
        self.assertFalse((self.root / "snapshot/secrets.json").exists())
        self.assertFalse((self.root / "snapshot/auth.json").exists())

    def test_symlinked_runtime_source_is_rejected(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        (runtime / "documentary_common.py").write_text("MODULES=('worker.py',)\n")
        (self.root / "secret").write_text("must not copy")
        (runtime / "worker.py").symlink_to(self.root / "secret")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            archive.snapshot_runtime(runtime, self.root / "snapshot", {})

    def test_agent_instructions_preserve_existing_content_and_are_idempotent(self):
        original = "# Existing rules\nKeep this custom instruction.\n"
        merged = archive.agent_instructions(original)
        self.assertIn(original.strip(), merged)
        self.assertEqual(archive.agent_instructions(merged), merged)
        self.assertEqual(merged.count(archive.MARKER), 1)

    def test_repository_targets_are_limited_to_workflow_paths(self):
        for name in ("/etc/passwd", "../auth.json", "automation/documentary/../../token.json", "token.json"):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "path_invalid"):
                archive.repository_path(name)

    def test_runtime_drift_is_reported_without_changing_the_running_source(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        (runtime / "documentary_common.py").write_text("MODULES=('worker.py',)\n")
        path = runtime / "worker.py"
        path.write_text("# newer live source\n")
        result = archive.snapshot_runtime(runtime, self.root / "snapshot", {"worker.py": "0" * 64})
        self.assertEqual(result["reference_differences"], ["worker.py"])
        self.assertEqual(path.read_text(), "# newer live source\n")

    def test_partial_persistence_failure_restores_original_file(self):
        first, second = self.root / "first", self.root / "second"
        first.write_bytes(b"original")
        changes = {first: (b"new", 0o644, "videoagent"), second: (b"other", 0o644, "videoagent")}
        real = archive.atomic
        def atomic(path, content, mode=0o644, owner=None):
            if path == second:
                raise OSError("simulated write failure")
            return real(path, content, mode=mode, owner=None)
        with patch.object(archive, "atomic", side_effect=atomic), self.assertRaises(OSError):
            archive.persist(changes, self.root / "backup", (os.getuid(), os.getgid()))
        self.assertEqual(first.read_bytes(), b"original")
        self.assertFalse(second.exists())

    def test_installed_code_parent_directories_are_readable_under_private_umask(self):
        old = os.umask(0o077)
        try:
            path = self.root / "new-tools" / "publication" / "publisher.py"
            archive.atomic(path, b"# source", mode=0o644)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o755)
            self.assertEqual(path.parent.parent.stat().st_mode & 0o777, 0o755)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        finally:
            os.umask(old)

    def test_private_backups_keep_private_directories(self):
        path = self.root / "backup" / "snapshot" / "runtime.py"
        archive.atomic(path, b"# archived source", mode=0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
