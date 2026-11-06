import ast
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import catarsis_selection as selection
import patch_sources
import single_catarsis_request as client

BUNDLE = Path(__file__).resolve().parent
CHANNELS = selection.CHANNELS


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def read(path):
    return json.loads(Path(path).read_text())


def module(name, **values):
    value = types.ModuleType(name)
    value.__dict__.update(values)
    return value


class SelectionTests(unittest.TestCase):
    def task(self, selected=None, single=False):
        channels = selected or list(CHANNELS)
        return dict(operation='generate_single_only' if single else 'generate_only',
                    topics={c: 'A documented historical topic' for c in channels},
                    requested_channels=channels)

    def test_legacy_pairs_remain_pairs(self):
        value = self.task()
        value.pop('requested_channels')
        self.assertEqual(selection.task_channels(value), CHANNELS)

    def test_single_facts_selects_exactly_one(self):
        self.assertEqual(selection.task_channels(self.task([CHANNELS[0]], True)), (CHANNELS[0],))

    def test_single_revelations_selects_exactly_one(self):
        self.assertEqual(selection.task_channels(self.task([CHANNELS[1]], True)), (CHANNELS[1],))

    def test_pair_operation_cannot_be_used_to_select_one(self):
        with self.assertRaises(ValueError):
            selection.task_channels(self.task([CHANNELS[0]]))

    def test_single_operation_cannot_expand_into_two(self):
        with self.assertRaises(ValueError):
            selection.task_channels(self.task(single=True))

    def test_extra_unselected_topic_is_rejected(self):
        value = self.task([CHANNELS[0]], True)
        value['topics'][CHANNELS[1]] = 'Not authorized'
        with self.assertRaises(ValueError):
            selection.task_channels(value)

    def test_unknown_channel_is_rejected(self):
        with self.assertRaises(ValueError):
            selection.task_channels(self.task(['../other'], True))

    def test_single_request_does_not_require_an_unrequested_topic(self):
        request = dict(operation='generation_start_single', channel=CHANNELS[0], topic='Marie Curie')
        self.assertEqual(selection.request_topics(request), {CHANNELS[0]: 'Marie Curie'})


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history = module('history_data', CHANNELS=CHANNELS,
            PLATFORMS=('youtube', 'facebook', 'instagram'), atomic=atomic, read=read,
            timestamp=lambda: '2026-11-06T23:40:00+00:00')
        self.prepared_pair = Mock(return_value=({}, 'pair-hash'))
        self.modules = {
            'history_data': self.history,
            'catarsis_style': module('catarsis_style', VERSION='introspective-catarsis-v7'),
            'generation_diagnostics': module('generation_diagnostics', inspect_failure=lambda *a: {}, inspect_recovery=lambda *a: {}),
            'editor_efficiency': module('editor_efficiency', usage_summary=lambda *a: {}),
            'publication_service': module('publication_service', prepared_pair=self.prepared_pair,
                                          controls=lambda: {'paused': True}),
        }
        patcher = patch.dict(sys.modules, self.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        source = (BUNDLE / 'native/generation_service.py').read_text()
        self.service = module('generation_service', __file__=str(BUNDLE / 'native/generation_service.py'))
        exec(compile(source, self.service.__file__, 'exec'), self.service.__dict__)
        self.service.STATE, self.service.JOBS = self.root / 'state', self.root / 'jobs'
        patcher = patch.dict(sys.modules, {'generation_service': self.service})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.broker = self.service.GenerationBroker(self.service.STATE, self.service.JOBS, launch=lambda f: None)

    def request(self, ident='single-request-001', channel=CHANNELS[0]):
        return dict(operation='generation_start_single', request_id=ident, channel=channel,
                    topic='Marie Curie and mobile radiography during World War I')

    def test_single_broker_creates_one_topic_and_no_second_channel_job(self):
        result = self.broker.handle(self.request())
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(result['requested_channels'], [CHANNELS[0]])
        self.assertEqual(result['channels'][CHANNELS[1]]['state'], 'not_requested')
        task = read(self.broker.state / result['batch_id'] / 'request.json')
        self.assertEqual(set(task['topics']), {CHANNELS[0]})
        self.assertEqual(task['operation'], 'generate_single_only')
        self.assertFalse((self.broker.jobs / result['batch_id'] / CHANNELS[1]).exists())

    def test_same_request_reuses_batch_and_does_not_launch_twice(self):
        first = self.broker.handle(self.request())
        second = self.broker.handle(self.request())
        self.assertEqual(first['batch_id'], second['batch_id'])
        self.assertEqual(len(self.broker.index()['requests']), 1)

    def test_same_id_with_changed_topic_is_rejected(self):
        self.broker.handle(self.request())
        changed = self.request()
        changed['topic'] = 'A completely different historical topic'
        self.assertEqual(self.broker.handle(changed)['error_code'], 'request_id_topics_changed')

    def test_pair_request_keeps_both_channels(self):
        result = self.broker.handle(dict(operation='generation_start', request_id='pair-request-001',
            facts_topic='A documented history topic', revelations_topic='A documented science topic'))
        self.assertEqual(result['requested_channels'], list(CHANNELS))
        self.assertEqual(result['generation_mode'], 'pair')

    def test_single_ready_never_gets_a_pair_publication_hash(self):
        result = self.broker.handle(self.request())
        path = self.broker.state / result['batch_id'] / 'status.json'
        value = read(path)
        value['state'] = 'ready'
        value['channels'][CHANNELS[0]] = dict(state='ready', approval_sha256='approval', files={}, metadata={})
        atomic(path, value)
        result = self.broker.status(result['batch_id'])
        self.assertIsNone(result['pair_sha256'])
        self.assertEqual(result['channels'][CHANNELS[0]]['approval_sha256'], 'approval')
        self.prepared_pair.assert_not_called()

    def test_pair_ready_still_uses_existing_pair_validation(self):
        result = self.broker.handle(dict(operation='generation_start', request_id='pair-request-002',
            facts_topic='A documented history topic', revelations_topic='A documented science topic'))
        path = self.broker.state / result['batch_id'] / 'status.json'
        value = read(path)
        value.update(state='ready', channels={c: dict(state='ready', files={}, metadata={}) for c in CHANNELS})
        atomic(path, value)
        result = self.broker.status(result['batch_id'])
        self.assertEqual(result['pair_sha256'], 'pair-hash')
        self.prepared_pair.assert_called_once()

    def test_single_schema_rejects_extra_fields(self):
        request = dict(self.request(), revelations_topic='not authorized')
        self.assertEqual(self.broker.handle(request)['state'], 'blocked')

    def test_active_manual_generation_prevents_new_single(self):
        self.broker.active['other'] = True
        self.assertEqual(self.broker.handle(self.request())['state'], 'blocked')

    def worker(self):
        self.built = []
        self.music_configured, self.music_rights = Mock(return_value=True), Mock()
        @contextlib.contextmanager
        def locked():
            yield
        def build(editorial, folder, channel, day, topic, batch, guard):
            guard()
            self.built.append(channel)
            for name in ('video.mp4', 'thumbnail.jpg'):
                (folder / name).write_bytes(b'offline fake artifact')
            atomic(folder / 'metadata.json', dict(youtube=dict(title='test', description='credits', tags=[]),
                facebook=dict(title='test', description='credits'), instagram=dict(caption='credits')))
            atomic(folder / 'approval.json', dict(scope='production'))
        core = module('daily_core', atomic=atomic, load=read, approval=lambda *a: dict(scope='production'))
        helpers = module('helpers', daily=types.SimpleNamespace(locked=locked))
        extras = dict(daily_core=core, daily_remote=module('daily_remote'), editorial=module('editorial'),
            music_provider=module('music_provider', configured=self.music_configured, rights=self.music_rights),
            helpers=helpers, history_worker=module('history_worker', collect=lambda _: {}))
        patcher = patch.dict(sys.modules, extras)
        patcher.start()
        self.addCleanup(patcher.stop)
        worker = module('generation_worker', __file__=str(BUNDLE / 'native/generation_worker.py'))
        exec(compile((BUNDLE / 'native/generation_worker.py').read_text(), worker.__file__, 'exec'), worker.__dict__)
        worker.AUTOMATION = self.root / 'automation'
        worker.preflight = lambda: None
        worker.native_history = lambda _: {}
        worker.sha = lambda _: 'offline-pin'
        worker.build = build
        worker.diagnostic = lambda folder, code: code
        return worker

    def test_facts_worker_builds_once_and_never_uses_revelations_music(self):
        result = self.broker.handle(self.request())
        worker = self.worker()
        worker.perform(result['batch_id'])
        self.assertEqual(self.built, [CHANNELS[0]])
        self.music_configured.assert_not_called()
        self.music_rights.assert_not_called()
        saved = read(self.broker.state / result['batch_id'] / 'status.json')
        self.assertEqual(saved['state'], 'ready')
        self.assertEqual(set(saved['channels']), {CHANNELS[0]})
        self.assertFalse((self.broker.jobs / result['batch_id'] / CHANNELS[1]).exists())

    def test_pair_worker_still_builds_two_and_checks_revelations_rights(self):
        result = self.broker.handle(dict(operation='generation_start', request_id='pair-worker-001',
            facts_topic='A history topic', revelations_topic='A science topic'))
        worker = self.worker()
        worker.perform(result['batch_id'])
        self.assertEqual(self.built, list(CHANNELS))
        self.music_rights.assert_called_once_with(CHANNELS[1])
        self.assertEqual(read(self.broker.state / result['batch_id'] / 'status.json')['state'], 'ready')

    def test_worker_claim_blocks_a_second_execution(self):
        result = self.broker.handle(self.request())
        worker = self.worker()
        worker.perform(result['batch_id'])
        with self.assertRaises(FileExistsError):
            worker.perform(result['batch_id'])
        self.assertEqual(self.built, [CHANNELS[0]])

    def test_generated_job_retains_generation_only_and_production_scope(self):
        result = self.broker.handle(self.request())
        self.worker().perform(result['batch_id'])
        job = read(self.broker.jobs / result['batch_id'] / CHANNELS[0] / 'job.json')
        self.assertTrue(job['generation_only'])
        self.assertFalse(job['publication_allowed'])
        self.assertEqual(job['scope'], 'production')


class PatchAndClientTests(unittest.TestCase):
    def test_worker_patch_preserves_everything_outside_perform(self):
        before = (BUNDLE / 'baseline/generation_worker.py').read_text()
        after = ((BUNDLE / 'native/generation_worker.py').read_text()
                 if '    selected = task_channels(request, CHANNELS)' in before
                 else patch_sources.generation_worker(before))
        self.assertEqual(before.split('def perform(batch):')[0], after.split('def perform(batch):')[0])
        self.assertEqual(before.split('\n\ndef main():')[1], after.split('\n\ndef main():')[1])

    def test_unknown_source_shape_is_rejected(self):
        with self.assertRaises(RuntimeError):
            patch_sources.generation_service('class GenerationBroker: pass\n')

    def test_documentary_exclusion_also_covers_single_requests(self):
        source = (BUNDLE / 'native/documentary_service.py').read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'attach')
        space = dict(OPERATIONS=set(), DocumentaryBroker=lambda parent: types.SimpleNamespace(active={'busy': True}),
                     denied=lambda code: dict(state='blocked', error_code=code))
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<attach>', 'exec'), space)
        original = Mock(return_value={})
        parent = types.SimpleNamespace(handle=original)
        space['attach'](parent)
        result = parent.handle(dict(operation='generation_start_single'))
        self.assertEqual(result['state'], 'blocked')
        original.assert_not_called()

    def test_request_file_limits_scope_to_one_channel(self):
        request = client.load_request(BUNDLE / 'curie-request.json')
        self.assertEqual(request['channel'], CHANNELS[0])
        self.assertNotIn('revelations_topic', request)
        self.assertLessEqual(len(request['topic']), 900)

    def test_duplicate_json_request_keys_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'duplicate_json_key'):
            json.loads('{"channel":"one","channel":"two"}', object_pairs_hook=client.unique)

    def test_overlong_or_invalid_request_cannot_reach_broker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'request.json'
            request = client.load_request(BUNDLE / 'curie-request.json')
            request['topic'] = 'x' * 901
            path.write_text(json.dumps(request))
            with self.assertRaisesRegex(RuntimeError, 'topic_invalid'):
                client.load_request(path)


class InstallationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('single_install_under_test', BUNDLE / 'install.py')
        cls.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.installer)

    def test_known_installed_source_is_not_patched_a_second_time(self):
        name = 'generation_worker.py'
        content = (BUNDLE / 'native' / name).read_bytes()
        saved = dict(after={name: self.installer.digest(content)})
        with patch.object(patch_sources, 'generation_worker') as transform:
            result = self.installer.candidate_sources({name: content}, saved)
            self.assertEqual(result[name], content)
            transform.assert_not_called()

    def test_unknown_unpatchable_source_fails_before_installation(self):
        with self.assertRaises(RuntimeError):
            self.installer.candidate_sources({'generation_worker.py': b'print(1)\n'}, {})

    def test_readable_helper_directories_survive_private_umask(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.umask(0o077)
            try:
                path = Path(tmp) / 'code' / 'helpers' / 'one.py'
                self.installer.atomic(path, b'# helper')
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o755)
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            finally:
                os.umask(old)

    def test_unrelated_source_customizations_are_preserved_by_patch(self):
        before = '# existing customization\n' + (BUNDLE / 'baseline/generation_worker.py').read_text()
        if '    selected = task_channels(request, CHANNELS)' in before:
            return
        after = patch_sources.generation_worker(before)
        self.assertTrue(after.startswith('# existing customization\n'))
        self.assertIn("control_pins = controls()", after)
        self.assertIn("preflight()", after)

    def test_existing_task_budget_configuration_is_not_modified_by_patch(self):
        source = (BUNDLE / 'native/generation_worker.py').read_text()
        self.assertNotIn('RECOVERY_LIMITS', source)
        self.assertNotIn('LIMITS =', source)
        self.assertIn('Supervisor', source)


if __name__ == '__main__':
    unittest.main()
