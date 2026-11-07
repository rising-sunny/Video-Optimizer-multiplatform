import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules'))
import workflow_common as c
import workflow_inputs as inputs


class SavedInputs(unittest.TestCase):
    def test_diagnostic_reads_saved_public_content_without_network_or_writes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); job = root / 'job'; ledger = root / 'ledger'
            job.mkdir(); ledger.mkdir()
            c.write(ledger / 'tools.json', {'a': dict(kind='fetch', request=dict(url='https://example.org/page?token=private'),
                result=dict(content='saved public evidence')),
                'b': dict(kind='chat', result=dict(content='do not expose unrelated responses'))})
            c.write(job / 'music-input.json', dict(tracks=[dict(title='Documentary track', isrc='EXAMPLE',
                api_key='never-return-this', download_url='https://example.org/private?token=x')], api_key='private'))
            before = {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            facts = types.SimpleNamespace(diagnostics=lambda _:dict(available=0), available=lambda _: {})
            with patch.object(c, 'ledger', return_value=ledger), patch.dict(sys.modules, {'documentary_sources':facts}):
                result = inputs.resume_inputs(job)
            self.assertEqual(result['fetched_sources'][0]['url'], 'https://example.org/page')
            self.assertEqual(result['music']['tracks'], [dict(title='Documentary track', isrc='EXAMPLE')])
            self.assertEqual(result['network_requests'], 0)
            self.assertNotIn('never-return-this', json.dumps(result))
            self.assertEqual(before, {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_token_values_are_redacted_from_public_source_text(self):
        self.assertEqual(inputs.public_text('https://example.org/?token=abc&x=1'),
            'https://example.org/?token=[hidden]&x=1')
        self.assertNotIn('sk-privatevalue', inputs.public_text('sk-privatevalue'))

    def test_diagnostic_bounds_source_text(self):
        self.assertEqual(len(inputs.public_text('a'*20000)), 12000)


if __name__ == '__main__':
    unittest.main()
