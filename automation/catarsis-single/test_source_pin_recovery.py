import ast
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import source_pin_recovery as r


class SourcePinMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.root = self.folder / 'code'
        self.root.mkdir()
        self.auto = self.folder / 'automation'
        self.ready = self.auto / 'runtime/production/readiness.json'
        self.ready.parent.mkdir(parents=True)
        self.files = {}
        for name in r.EXPECTED_FILES:
            content = ('# fixture: ' + name + '\n').encode()
            (self.auto / name).write_bytes(content)
            self.files[name] = r.digest(content)
        self.ready.write_text(json.dumps(dict(checks={str(i): True for i in range(36)}, code_sha256=self.files)))
        self.original, self.corrected, self.final = r.known_sources()
        self.worker = self.root / 'generation_worker.py'
        self.worker.write_bytes(self.original)
        self.worker.chmod(0o644)
        self.backups = self.folder / 'backups'
        self.backups.mkdir()
        self.paused = self.auto / 'runtime/production/PAUSED'
        self.paused.write_bytes(b'paused before repair')
        for obj, name, value in (
            (r.single, 'ROOT', self.root), (r, 'READINESS', self.ready),
            (r, 'OBSERVED_READINESS', r.digest(self.ready.read_bytes())),
            (r, 'EXPECTED_FILES', self.files), (r, 'BACKUPS', self.backups),
            (r, 'LOCK', self.folder / 'install.lock'),
        ):
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.idle = patch.object(r.single, 'idle').start()
        self.controls = patch.object(r.single, 'controls', return_value=('unchanged', 1, 'disabled')).start()
        self.native = patch.object(r, 'native_check').start()
        self.root_uid = patch.object(r.os, 'geteuid', return_value=0).start()
        self.addCleanup(patch.stopall)

    def test_only_four_dictionary_values_change_and_preflight_is_identical(self):
        # Source migration itself uses the real, observed baseline and constants.
        actual = r.repin(self.original)
        self.assertEqual(actual, self.corrected)
        before, after = ast.parse(self.original), ast.parse(actual)
        def pins(tree):
            return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SOURCE_HASHES' for t in n.targets))
        self.assertEqual({k for k in pins(before) if pins(before)[k] != pins(after)[k]}, set(r.UPDATES))
        def preflight(tree):
            return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'preflight'))
        self.assertEqual(preflight(before), preflight(after))

    def test_worker_unknown_to_observed_snapshot_is_rejected_without_changes(self):
        self.worker.write_bytes(self.original + b'\n# unrelated live change\n')
        before = self.worker.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'worker_not_observed'):
            r.repair()
        self.assertEqual(before, self.worker.read_bytes())
        self.native.assert_not_called()

    def test_changed_readiness_is_not_regenerated_or_approved(self):
        self.ready.write_bytes(self.ready.read_bytes() + b'\n')
        with self.assertRaisesRegex(RuntimeError, 'readiness_not_observed'):
            r.repair()
        self.assertEqual(self.worker.read_bytes(), self.original)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_source_change_even_with_previously_positive_checks_is_rejected(self):
        (self.auto / 'runner.py').write_text('# modified after readiness')
        with self.assertRaisesRegex(RuntimeError, 'approved_source_changed'):
            r.repair()
        self.assertEqual(self.worker.read_bytes(), self.original)

    def test_busy_broker_prevents_worker_write(self):
        self.idle.side_effect = RuntimeError('single_install_manual_work_in_progress')
        with self.assertRaisesRegex(RuntimeError, 'manual_work_in_progress'):
            r.repair()
        self.assertEqual(self.worker.read_bytes(), self.original)
        self.native.assert_not_called()

    def test_native_preflight_failure_restores_worker_and_has_no_success_receipt(self):
        self.native.side_effect = RuntimeError('source_pin_native_preflight_failed')
        with self.assertRaisesRegex(RuntimeError, 'native_preflight_failed'):
            r.repair()
        self.assertEqual(self.worker.read_bytes(), self.original)
        self.assertFalse((self.root / 'source-pins-v48-1-installed.json').exists())
        saved = list(self.backups.glob('*/generation_worker.py'))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), self.original)

    def test_repair_preserves_sources_readiness_pause_and_worker_mode(self):
        paths = [*self.auto.glob('*.py'), self.ready, self.paused]
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
        result = r.repair()
        self.assertEqual(result['state'], 'installed')
        self.assertEqual(self.worker.read_bytes(), self.corrected)
        self.assertEqual(self.worker.stat().st_mode & 0o777, 0o644)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths})
        self.native.assert_called_once()

    def test_repeat_reuses_corrected_worker_and_preserves_backup(self):
        first = r.repair()
        second = r.repair()
        self.assertEqual(second['state'], 'already_installed')
        self.assertEqual(second['backup'], first['backup'])
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_repeat_after_single_install_never_reverts_single_channel_worker(self):
        self.worker.write_bytes(self.final)
        result = r.repair()
        self.assertEqual(result['state'], 'already_installed')
        self.assertEqual(self.worker.read_bytes(), self.final)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_symlinked_automation_file_is_rejected(self):
        source = self.auto / 'runner.py'
        content = source.read_bytes()
        source.unlink()
        other = self.folder / 'other.py'
        other.write_bytes(content)
        source.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, 'symlink_rejected'):
            r.repair()
        self.assertEqual(self.worker.read_bytes(), self.original)

    def test_native_guard_still_rejects_changed_sources_and_false_readiness(self):
        # Execute the unchanged native guard over isolated fixture files.
        node = next(n for n in ast.parse(self.corrected).body if isinstance(n, ast.FunctionDef) and n.name == 'preflight')
        space = dict(AUTOMATION=self.auto, SOURCE_HASHES=self.files,
            sha=lambda p: r.digest(p.read_bytes()),
            read=lambda p: json.loads(p.read_text()),
            shutil=types.SimpleNamespace(which=lambda binary: '/bin/' + binary))
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<native-preflight>', 'exec'), space)
        space['preflight']()
        (self.auto / 'runner.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'generation_source_changed'):
            space['preflight']()
        (self.auto / 'runner.py').write_bytes(b'# fixture: runner.py\n')
        value = json.loads(self.ready.read_text())
        value['checks']['0'] = False
        self.ready.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'generation_readiness_failed'):
            space['preflight']()


if __name__ == '__main__':
    unittest.main()
