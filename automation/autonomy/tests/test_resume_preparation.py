import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'modules'))
import workflow_common as c
import workflow_jobs as jobs
import workflow_native as native
import workflow_preparation as prep


class Preparation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.job=self.root/'job';self.job.mkdir()
        self.ledger=self.root/'ledger';self.ledger.mkdir()
        self.channel=c.CHANNELS[0]
        self.identity=dict(channel=self.channel,date='2026-11-06',topic='Marie Curie: exact original request')
        c.write(self.job/'job.json',self.identity)
        self.value=dict(self.identity,research=[dict(url='https://source-a.example/page'),dict(url='https://source-b.example/page')])
        self.task=dict(date='2026-11-06')

    def test_missing_snapshots_are_fetched_once_and_failed_sources_never_become_evidence(self):
        known={'https://source-a.example/page':dict(content='saved'*100)}
        def fetched(job,url,guard):
            guard();known[url]=dict(content='actually retrieved'*100)
        fetch=Mock(side_effect=fetched)
        facts=types.SimpleNamespace(fetch_source=fetch,available=lambda _:known)
        with patch.dict(sys.modules,{'documentary_sources':facts}),patch.object(jobs,'evidence',side_effect=lambda _:copy.deepcopy(known)):
            self.assertEqual(len(prep.sources(self.job,self.value,lambda:None)),2)
            prep.sources(self.job,self.value,lambda:None)
        fetch.assert_called_once();self.assertEqual(fetch.call_args.args[1],'https://source-b.example/page')
        with patch.dict(sys.modules,{'documentary_sources':facts}),patch.object(jobs,'evidence',return_value={}):
            with self.assertRaisesRegex(RuntimeError,'factual_evidence_missing'):
                prep.sources(self.job,self.value,lambda:None)

    def test_missing_music_inputs_are_prepared_from_native_channel_catalogue(self):
        music=dict(tracks=[dict(title='Verified native track')])
        history=dict(channels={self.channel:dict(youtube=[dict(id='v1',title='Earlier video',description='public history')])})
        def load(path):return music if Path(path).name=='music.json' else history
        editorial=types.SimpleNamespace(ROOT=self.root,load=load,d=types.SimpleNamespace(PACKAGE=self.root),
            mp=types.SimpleNamespace(configured=lambda _:False,catalogue=Mock()),music_evidence=Mock())
        prep.ensure_inputs(editorial,self.job,self.channel,lambda:None)
        self.assertEqual(c.read(self.job/'music-input.json'),music)
        self.assertEqual(c.read(self.job/'history-input.json')[self.channel]['youtube'][0]['text'],'public history')
        editorial.mp.catalogue.assert_not_called();editorial.music_evidence.assert_called_once()

    def test_existing_catalogue_and_history_are_not_replaced(self):
        for name,value in [('history-input.json',{'original':'history'}),('music-input.json',dict(tracks=[dict(title='Original track')])),('music-license-evidence.json',{'original':'receipt'})]:
            c.write(self.job/name,value)
        before=c.tree(self.job)
        editorial=types.SimpleNamespace(load=Mock(side_effect=AssertionError('must reuse')),
            mp=types.SimpleNamespace(configured=lambda _:False,catalogue=Mock()),music_evidence=Mock())
        prep.ensure_inputs(editorial,self.job,self.channel,lambda:None)
        self.assertEqual(before,c.tree(self.job));editorial.music_evidence.assert_not_called()

    def test_cancellation_before_preparation_does_not_write_inputs(self):
        before=c.tree(self.job)
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            prep.ensure_inputs(None,self.job,self.channel,lambda:(_ for _ in ()).throw(RuntimeError('cancelled')))
        self.assertEqual(before,c.tree(self.job))

    def test_ready_plan_needs_no_new_model_call(self):
        known={'https://source-a.example/page':dict(content='actual source')}
        with patch.object(prep,'identity'),patch.object(prep,'sources',return_value=known),patch.object(jobs,'validate_saved_plan',return_value=self.value),patch.object(prep,'repair') as repair:
            result=prep.prepare(self.job,self.value,'documentary',self.task,self.channel,'001',lambda:None)
        self.assertEqual(result,self.value);repair.assert_not_called()
        self.assertEqual(c.read(self.job/'workflow-preparation.json')['state'],'validated')

    def test_identity_mismatch_is_rejected_before_any_preparation(self):
        other=dict(self.value,channel=c.CHANNELS[1])
        with patch.object(prep,'ensure_inputs') as ensure,self.assertRaisesRegex(RuntimeError,'identity_mismatch'):
            prep.prepare(self.job,other,'catarsis',self.task,self.channel,'001',lambda:None)
        ensure.assert_not_called()

    def test_repair_reserves_independent_review_and_keeps_existing_ledger(self):
        c.write(self.ledger/'budget.json',dict(counts=dict(chat=9,invocations=3),pending=None))
        invoke=Mock()
        with patch.object(c,'ledger',return_value=self.ledger),patch.dict(sys.modules,{'deepseek_editor':types.SimpleNamespace(invoke=invoke)}),self.assertRaisesRegex(RuntimeError,'review_reserve'):
            prep.repair(self.job,self.value,'catarsis',self.task,self.channel,{},'001','unknown_music',lambda:None)
        invoke.assert_not_called();self.assertFalse((self.ledger/'workflow-preparation-repair.json').exists())
        self.assertEqual(c.read(self.ledger/'budget.json')['counts']['chat'],9)


class NativeEntry(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'native.py'

    def test_only_exact_migration_sentinel_is_removed_and_native_qa_remains(self):
        text="""def build(directory,channel,date,topic,scope='production'):
    raise Blocked('generation_moved_to_codex_chat')
    validate()
    render()
    return approve()
"""
        self.path.write_text(text)
        space=types.ModuleType('native_test');space.__file__=str(self.path)
        calls=[]
        space.Blocked=RuntimeError;space.validate=lambda:calls.append('validate');space.render=lambda:calls.append('render');space.approve=lambda:(calls.append('approve') or 'approved')
        exec(text,space.__dict__)
        function=native.native_function(space,'build')
        self.assertIs(function.__globals__,space.__dict__)
        self.assertEqual(function('job','channel','date','topic'),'approved')
        self.assertEqual(calls,['validate','render','approve']);self.assertEqual(self.path.read_text(),text)
        space.validate=lambda:(_ for _ in ()).throw(RuntimeError('quality-failed'))
        with self.assertRaisesRegex(RuntimeError,'quality-failed'):function('job','channel','date','topic')

    def test_unrelated_native_guard_is_never_removed(self):
        text="def build():\n raise RuntimeError('readiness_failed')\n"
        self.path.write_text(text);space=types.ModuleType('native_test');space.__file__=str(self.path);exec(text,space.__dict__)
        self.assertIs(native.native_function(space,'build'),space.build)
        with self.assertRaisesRegex(RuntimeError,'readiness_failed'):native.native_function(space,'build')()

    def test_native_entry_and_implementation_hooks_are_restored_after_error(self):
        text="def build():\n return 1\ndef invoke():\n return 2\n"
        self.path.write_text(text);space=types.ModuleType('native_test');space.__file__=str(self.path);exec(text,space.__dict__)
        previous=(space.build,space.invoke)
        with self.assertRaisesRegex(RuntimeError,'stop'):
            with native.enabled(space,Path(self.temp.name),'channel'):raise RuntimeError('stop')
        self.assertEqual(previous,(space.build,space.invoke))


if __name__=='__main__':unittest.main()
