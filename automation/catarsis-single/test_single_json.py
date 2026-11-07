import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock,patch

import json_recovery_patch as changes
import shorts_single_json as recovery

BUNDLE=Path(__file__).resolve().parent


def parser(source):
    nodes=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in ('parse','_pairs')]
    space=dict(json=json,re=__import__('re'))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<parser>', 'exec'),space)
    return space['parse']


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original=(BUNDLE/'baseline/shorts_handoff.py').read_text()
        cls.before=staticmethod(parser(original))
        cls.after=staticmethod(parser(changes.shorts_handoff(original)))

    def test_observed_one_extra_brace_preserves_all_values(self):
        text='{"action":"rebuild","plan":{"caption":"a closing } inside text","nested":{"v":1}}}}'
        with self.assertRaises(ValueError):self.before(text)
        result,receipt=self.after(text)
        self.assertEqual(result,dict(action='rebuild',plan=dict(caption='a closing } inside text',nested=dict(v=1))))
        self.assertEqual(receipt,[dict(kind='removed_single_redundant_object_close',count=1)])

    def test_valid_json_keeps_empty_repair_receipt(self):
        source='{"nested":{"value":1},"text":"}"}'
        self.assertEqual(self.before(source),self.after(source))

    def test_truncated_plan_is_never_filled_in(self):
        with self.assertRaises(ValueError):self.after('{"plan":{"text":"unfinished')

    def test_two_extra_closes_are_not_accepted(self):
        with self.assertRaises(ValueError):self.after('{"ok":true}}}')

    def test_other_trailing_content_is_not_accepted(self):
        for suffix in ('[]','{"another":true}','} instructions','}}',';'):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError):self.after('{"ok":true}'+suffix)

    def test_duplicate_keys_still_fail(self):
        with self.assertRaisesRegex(ValueError,'duplicate_json_key'):
            self.after('{"v":1,"v":2}}')

    def test_array_with_object_close_is_rejected(self):
        with self.assertRaises(ValueError):self.after('[{"ok":true}]}')

    def test_existing_control_comma_and_dsml_repairs_still_work(self):
        sources=['{"text":"line\none",}','{"x":1,}',
            '{"x":1}\n</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>']
        for source in sources:
            self.assertEqual(self.before(source),self.after(source))


class RoutingAndPlanTests(unittest.TestCase):
    def test_old_batch_routes_are_preserved_after_exact_new_branch(self):
        before=(BUNDLE/'baseline/shorts_handoff_resume.py').read_text()
        after=changes.shorts_handoff_resume(before)
        helper=types.ModuleType('shorts_single_json')
        helper.start=Mock(return_value='single-start')
        helper.perform=Mock(return_value='single-perform')
        for name in ('start','perform'):
            node=next(n for n in ast.parse(after).body if isinstance(n,ast.FunctionDef) and n.name==name)
            # The original function follows the new dispatch branch byte-for-byte.
            original=next(n for n in ast.parse(before).body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(ast.dump(ast.Module(body=node.body[1:],type_ignores=[])),
                             ast.dump(ast.Module(body=original.body,type_ignores=[])))
            space={}
            # Execute only the dispatch; legacy route dependencies are unneeded.
            node.body=node.body[:1]
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<dispatch>','exec'),space)
            with patch.dict(sys.modules,{'shorts_single_json':helper}):
                args=(object(),recovery.BATCH) if name=='start' else (recovery.BATCH,)
                self.assertEqual(space[name](*args),'single-'+name)

    def test_changed_shape_is_rejected_before_any_write(self):
        with self.assertRaisesRegex(RuntimeError,'source_shape_changed'):
            changes.shorts_handoff('def parse(text): return {}\n')

    def test_documentary_excludes_saved_handoff_operation(self):
        source=(BUNDLE/'baseline/documentary_service.py').read_text()
        changed=changes.documentary_service(source)
        self.assertIn("'generation_start_single','generation_resume_saved_handoffs'",changed)
        self.assertEqual(changed.replace("'generation_resume_saved_handoffs',",''),source)

    def envelope(self):
        return dict(action='rebuild',plan=dict(channel=recovery.CHANNEL,date='2026-11-06',topic='Marie Curie mobile radiography'),
            metadata=dict(youtube=dict(title='Title')),thumbnail=dict(media=0,text='Curie'))

    def test_envelope_merge_and_authoritative_topic_do_not_change_scenes(self):
        source=self.envelope();source['plan']['project']=dict(sequence=[dict(text='Historical assertion',seconds=3)])
        before=copy.deepcopy(source)
        plan,receipt=recovery.unwrap(source,dict(topic='Marie Curie: exact original request',date='2026-11-06'))
        self.assertEqual(plan['project'],before['plan']['project'])
        self.assertEqual(plan['topic'],'Marie Curie: exact original request')
        self.assertEqual(source,before)
        self.assertEqual(receipt,[dict(kind='restore_original_full_topic_binding')])

    def test_conflicting_metadata_is_not_resolved_by_dropping_one_value(self):
        source=self.envelope();source['plan']['metadata']={'different':True}
        with self.assertRaisesRegex(RuntimeError,'conflicting_envelope'):
            recovery.unwrap(source,dict(topic='Marie Curie',date='2026-11-06'))

    def test_other_channel_or_subject_cannot_be_rebound(self):
        for field,value in (('channel','stunning-revelations'),('topic','The Berlin Wall')):
            source=self.envelope();source['plan'][field]=value
            with self.subTest(field=field):
                with self.assertRaises(RuntimeError):
                    recovery.unwrap(source,dict(topic='Marie Curie',date='2026-11-06'))

    def test_observed_response_hash_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/recovery.INVALID).write_text('{}')
            with patch.object(recovery,'ledger',return_value=folder):
                with self.assertRaisesRegex(RuntimeError,'observed_response_changed'):
                    recovery.prepared(folder)

    def test_start_is_idempotent_once_authorization_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/recovery.BATCH;folder.mkdir()
            (folder/recovery.AUTH).write_text('{}')
            broker=types.SimpleNamespace(state=Path(temp),status=Mock(return_value={'state':'running'}),launch=Mock())
            fake=types.ModuleType('generation_service');fake.denied=lambda c:{'state':'blocked','error_code':c};fake.safe_error=str
            history=types.ModuleType('history_data');history.atomic=Mock();history.timestamp=lambda:'now'
            with patch.dict(sys.modules,{'generation_service':fake,'history_data':history}),patch.object(recovery,'authorize') as authorize:
                self.assertEqual(recovery.start(broker,recovery.BATCH),{'state':'running'})
                authorize.assert_not_called();broker.launch.assert_not_called()

    def test_foreign_batch_is_denied_without_authorization(self):
        fake=types.ModuleType('generation_service');fake.denied=lambda c:{'state':'blocked','error_code':c};fake.safe_error=str
        history=types.ModuleType('history_data');history.atomic=Mock();history.timestamp=lambda:'now'
        with patch.dict(sys.modules,{'generation_service':fake,'history_data':history}),patch.object(recovery,'authorize') as authorize:
            self.assertEqual(recovery.start(object(),'f'*32)['state'],'blocked')
            authorize.assert_not_called()

    def test_reexport_implementation_is_resolved_to_its_actual_globals(self):
        impl=types.ModuleType('test_implementation')
        impl.__file__=__file__
        exec('def build(*args):return 1',impl.__dict__)
        shim=types.ModuleType('editorial');shim.build=impl.build
        with patch.dict(sys.modules,{'editorial':shim,'test_implementation':impl}):
            self.assertIs(recovery.native_editorial(),impl)

    def test_ledger_usage_cannot_be_reset_or_research_charged(self):
        old=dict(counts=dict(chat=5,search=3,fetch=3),usage=[{'old':True}])
        good=dict(counts=dict(chat=7,search=3,fetch=3),usage=[{'old':True},{'review':True}],estimated_usd=.04)
        with patch.object(recovery,'read',return_value=good):recovery.finish_budget(old)
        for change in ('reset','research','usage'):
            bad=copy.deepcopy(good)
            if change=='reset':bad['counts']['chat']=0
            if change=='research':bad['counts']['search']=4
            if change=='usage':bad['usage'][0]={'rewritten':True}
            with self.subTest(change=change),patch.object(recovery,'read',return_value=bad):
                with self.assertRaisesRegex(RuntimeError,'ledger_changed_out_of_scope'):recovery.finish_budget(old)


if __name__=='__main__':unittest.main()
