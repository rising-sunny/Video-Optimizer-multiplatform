import json
from pathlib import Path
import tempfile
import unittest

import diagnose_native_sources as d


class SourceDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.code, self.auto = self.root / 'code', self.root / 'automation'
        self.code.mkdir()
        (self.auto / 'runtime/production').mkdir(parents=True)

    def fixture(self, pins, readiness, content=b'new source\n'):
        (self.code / 'generation_worker.py').write_text('SOURCE_HASHES = ' + repr(pins) + '\n')
        (self.auto / 'runner.py').write_bytes(content)
        (self.auto / 'runtime/production/readiness.json').write_text(json.dumps(dict(
            checks={'source_validation': True}, code_sha256=readiness, token='PRIVATE_VALUE')))

    def test_current_readiness_match_does_not_hide_stale_pin(self):
        digest = d.sha(b'new source\n')
        self.fixture({'runner.py': '0' * 64}, {'runner.py': digest})
        result = d.diagnose(self.code, self.auto)
        self.assertTrue(result['all_source_files_match_readiness'])
        self.assertEqual(result['mismatches'][0]['file'], 'runner.py')
        self.assertFalse(result['mismatches'][0]['matches_pin'])

    def test_secret_values_and_unapproved_paths_are_not_returned(self):
        self.fixture({'runner.py': '0' * 64, 'secrets.json': '1' * 64}, {})
        (self.auto / 'secrets.json').write_text('NEVER_READ_THIS')
        result = d.diagnose(self.code, self.auto)
        encoded = json.dumps(result)
        self.assertNotIn('PRIVATE_VALUE', encoded)
        self.assertNotIn('NEVER_READ_THIS', encoded)
        self.assertEqual(result['unsupported_source_entries'], 1)
        self.assertFalse(result['all_source_files_match_readiness'])

    def test_symlinked_source_is_not_followed(self):
        self.fixture({'runner.py': '0' * 64}, {})
        (self.auto / 'runner.py').unlink()
        (self.root / 'private').write_text('PRIVATE_FILE')
        (self.auto / 'runner.py').symlink_to(self.root / 'private')
        result = d.diagnose(self.code, self.auto)
        self.assertIsNone(result['source_files'][0]['actual_sha256'])
        self.assertEqual(result['source_files'][0]['state'], 'symlink_not_read')

    def test_diagnostic_preserves_all_fixture_bytes(self):
        self.fixture({'runner.py': '0' * 64}, {})
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        d.diagnose(self.code, self.auto)
        after = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
