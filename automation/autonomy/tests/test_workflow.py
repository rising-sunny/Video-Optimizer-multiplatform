import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock,patch

HERE=Path(__file__).resolve().parent
PACKAGE=HERE.parent
sys.path.insert(0,str(HERE))
if (PACKAGE/'modules').is_dir():sys.path.insert(0,str(PACKAGE/'modules'))
sys.path.insert(0,str(PACKAGE))
import source_patch
import workflow_common as c
import workflow_jobs as jobs
import workflow_native as native
import workflow_recovery as recovery
import workflow_service as service
import maintenance_daemon as admin

def module(name,**values):
    result=types.ModuleType(name);result.__dict__.update(values);return result

class ParserAndPatchTests(unittest.TestCase):
    def baseline(self,name):
        path=HERE/'baseline'/name
        if not path.exists():path=PACKAGE/'baseline'/name
        return path.read_text()
    def parse(self,text):
        source=source_patch.shorts_handoff(self.baseline('shorts_handoff.py'))
        nodes=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in ('parse','_pairs')]
        space=dict(json=json,re=__import__('re'));exec(compile(ast.Module(body=nodes,type_ignores=[]),'<parser>','exec'),space)
        return space['parse'](text)
    def test_complete_object_with_one_redundant_close_is_recovered(self):
        value,receipt=self.parse('{"x":{"text":"a } inside text"}}}')
        self.assertEqual(value,{'x':{'text':'a } inside text'}})
        self.assertEqual(receipt,[dict(kind='removed_single_redundant_object_close',count=1)])
    def test_unfinished_duplicate_and_multiple_values_are_rejected(self):
        for text in ('{"x":','{"x":1,"x":2}}','{"x":1}}}','{"x":1}[]','[1]}'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.parse(text)
    def test_earlier_syntax_repairs_keep_working(self):
        value,receipt=self.parse('{"text":"one\ntwo",}')
        self.assertEqual(value,{'text':'one\ntwo'});self.assertEqual(len(receipt),2)
    def test_shared_normalizer_only_changes_parse(self):
        before=self.baseline('shorts_handoff.py');after=source_patch.shorts_handoff(before)
        functions=lambda s:{n.name:ast.dump(n) for n in ast.parse(s).body if isinstance(n,ast.FunctionDef)}
        a,b=functions(before),functions(after)
        self.assertEqual({k for k in a if a[k]!=b[k]},{'parse'})
    def test_every_patch_is_valid_and_repeatable(self):
        for name in ('generation_service.py','generation_worker.py','generation_tools.py','documentary_service.py','deepseek_editor.py','shorts_handoff.py'):
            source=self.baseline(name);transform=getattr(source_patch,Path(name).stem)
            first=transform(source);ast.parse(first)
            self.assertEqual(transform(first),first)
    def test_worker_claim_preflight_and_budget_configuration_are_preserved(self):
        before=self.baseline('generation_worker.py');after=source_patch.generation_worker(before)
        self.assertIn("with (folder / 'claimed').open('x')",after)
        self.assertIn('preflight()',after)
        original=next(n for n in ast.parse(before).body if isinstance(n,ast.FunctionDef) and n.name=='preflight')
        current=next(n for n in ast.parse(after).body if isinstance(n,ast.FunctionDef) and n.name=='preflight')
        self.assertEqual(ast.dump(original),ast.dump(current))
        self.assertNotIn('RECOVERY_LIMITS',after)
    def test_tools_are_appended_inside_register(self):
        source=source_patch.generation_tools(self.baseline('generation_tools.py'))
        tree=ast.parse(source);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='register')
        self.assertIn('_workflow_register(server, links)',ast.get_source_segment(source,node))
    def test_unknown_source_shape_does_not_get_overwritten(self):
        with self.assertRaisesRegex(RuntimeError,'source_shape_changed'):source_patch.deepseek_editor('def invoke():pass\n')

class DurableAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.job=self.root/'manual-catarsis'/('a'*32)/c.CHANNELS[0]
        self.job.mkdir(parents=True);self.ledger=self.root/'ledger';self.ledger.mkdir()
    def test_no_symlinked_job_data_is_followed(self):
        target=self.root/'private';target.write_text('private')
        link=self.root/'link';link.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError,'symlink'):c.digest(link)
    def test_private_atomic_records_survive_replacement(self):
        path=self.root/'new'/'record.json';c.write(path,{'attempt':1});c.write(path,{'attempt':2})
        self.assertEqual(c.read(path),{'attempt':2});self.assertEqual(path.stat().st_mode&0o777,0o600)
    def budget(self,chat=5,invocations=1,pending=None):
        c.write(self.ledger/'budget.json',dict(counts=dict(chat=chat,invocations=invocations),pending=pending))
    def invoke(self,chat=5,attempts=0,pending=None):
        self.budget(chat=chat,pending=pending)
        c.write(self.ledger/'invalid-handoff-abc.json',dict(output='editorial-plan.json',provider_content='{"a":1,} garbage'))
        if attempts:c.write(self.ledger/'workflow-format-repairs.json',dict(attempts=[{}]*attempts))
        calls=[]
        class Failure(RuntimeError):pass
        def original(folder,prompt,output,*args,**kwargs):
            calls.append((folder,prompt,output,kwargs))
            if len(calls)==1:raise Failure('generation_dependency_deepseek_json_invalid')
            return {'complete':True}
        space=dict(invoke=original,Failure=Failure)
        recovery.install(space)
        return calls,space,Failure
    def test_format_retry_uses_the_same_output_and_original_implementation(self):
        calls,space,_=self.invoke()
        with patch.object(c,'ledger',return_value=self.ledger),patch.object(recovery,'validate_result'):
            result=space['invoke'](self.job,'original schema','editorial-plan.json')
        self.assertEqual(result,{'complete':True});self.assertEqual(len(calls),2)
        self.assertEqual(calls[0][2],calls[1][2]);self.assertTrue(calls[1][3]['local_only']);self.assertFalse(calls[1][3]['search'])
        self.assertEqual(c.read(self.ledger/'budget.json')['counts']['chat'],5)
        self.assertEqual(len(c.read(self.ledger/'workflow-format-repairs.json')['attempts']),1)
    def test_retry_leaves_capacity_for_remaining_reviews(self):
        calls,space,Failure=self.invoke(chat=8)
        with patch.object(c,'ledger',return_value=self.ledger),self.assertRaises(Failure):space['invoke'](self.job,'schema','editorial-plan.json')
        self.assertEqual(len(calls),1)
    def test_ambiguous_pending_requests_are_not_repeated(self):
        calls,space,Failure=self.invoke(pending={'kind':'chat'})
        with patch.object(c,'ledger',return_value=self.ledger),self.assertRaises(Failure):space['invoke'](self.job,'schema','editorial-plan.json')
        self.assertEqual(len(calls),1)
    def test_retry_cap_survives_new_invocation(self):
        calls,space,Failure=self.invoke(attempts=2)
        with patch.object(c,'ledger',return_value=self.ledger),self.assertRaises(Failure):space['invoke'](self.job,'schema','editorial-plan.json')
        self.assertEqual(len(calls),1)
    def test_failed_second_reply_is_not_retried_recursively(self):
        calls,space,Failure=self.invoke()
        original=space['invoke'].__wrapped__
        def always_fail(*args,**kwargs):
            calls.append(args);raise Failure('generation_dependency_deepseek_json_invalid')
        space=dict(invoke=always_fail,Failure=Failure);recovery.install(space)
        with patch.object(c,'ledger',return_value=self.ledger),self.assertRaises(Failure):space['invoke'](self.job,'schema','editorial-plan.json')
        self.assertEqual(len(calls),2)
    def test_native_reexport_hooks_use_the_real_module(self):
        impl=module('workflow_test_impl',__file__=__file__);exec('def build():pass',impl.__dict__)
        shim=module('workflow_test_shim',build=impl.build)
        with patch.dict(sys.modules,{'workflow_test_impl':impl}):self.assertIs(native.implementation(shim),impl)
    def test_paid_ledger_prefix_is_append_only(self):
        old=dict(counts=dict(chat=5),usage=[{'before':True}])
        good=dict(counts=dict(chat=6),usage=[{'before':True},{'after':True}],estimated_usd=.03)
        with patch.object(c,'ledger',return_value=self.ledger):
            c.write(self.ledger/'budget.json',good);jobs.verify_ledger(self.job,old)
            bad=copy.deepcopy(good);bad['usage'][0]={'reset':True};c.write(self.ledger/'budget.json',bad)
            with self.assertRaisesRegex(RuntimeError,'regressed'):jobs.verify_ledger(self.job,old)
    def test_enrollment_never_resets_attempts(self):
        state=self.root/'catarsis'/('a'*32);state.mkdir(parents=True)
        c.write(state/'request.json',dict(publication_allowed=False))
        with patch.object(c,'STATE',self.root):
            first=jobs.enroll('catarsis','a'*32);first['attempts']=[{'number':1}];c.write(state/'workflow.json',first)
            second=jobs.enroll('catarsis','a'*32)
        self.assertEqual(second['attempts'],[{'number':1}])
    def test_resume_cannot_authorize_publication(self):
        state=self.root/'catarsis'/('a'*32);state.mkdir(parents=True)
        c.write(state/'request.json',dict(publication_allowed=True))
        with patch.object(c,'STATE',self.root),self.assertRaisesRegex(RuntimeError,'generation_only'):jobs.enroll('catarsis','a'*32)
    def test_ready_and_unenrolled_jobs_are_not_automatically_replayed(self):
        state=self.root/'catarsis'/('a'*32);state.mkdir(parents=True)
        c.write(state/'workflow.json',dict(enabled=True,state='monitoring',job_id='a'*32))
        c.write(state/'status.json',dict(state='ready'))
        generation=types.SimpleNamespace(active={},publication=None,workflow_documentary=None)
        with patch.object(c,'STATE',self.root),patch.object(c,'busy',return_value=False),patch.object(jobs,'start') as start:
            self.assertEqual(jobs.poll(generation)['state'],'idle');start.assert_not_called()
        self.assertEqual(c.read(state/'workflow.json')['state'],'complete')

class ServiceTests(unittest.TestCase):
    def test_deployment_gate_blocks_mutations_and_allows_cancellation_and_reads(self):
        with patch.object(c,'busy',return_value=True):
            for op in ('generation_start_single','documentary_start','documentary_resume_assets','publication_start','generation_workflow_resume'):
                self.assertTrue(service.guard_operation(op))
            for op in ('generation_status','documentary_status','generation_cancel','documentary_cancel','generation_workflow_admin','manual_activity'):
                self.assertFalse(service.guard_operation(op))
    def test_strict_broker_schema_and_existing_routes(self):
        class Broker:
            def __init__(self):self.lock=threading.RLock();self.active={};self.publication=None
            def handle(self,request):return {'old':request.get('operation')}
            def start(self,request):return {'state':'blocked'}
            def status(self,ident):return {'state':'not_requested'}
        operations=set();service.install(Broker,operations);service.install(Broker,operations)
        fake=module('generation_service',denied=lambda code:dict(state='blocked',error_code=code),safe_error=str)
        with patch.dict(sys.modules,{'generation_service':fake}),patch.object(c,'busy',return_value=False):
            broker=Broker();self.assertEqual(broker.handle({'operation':'legacy'})['old'],'legacy')
            self.assertEqual(broker.handle({'operation':'generation_workflow_capabilities','extra':1})['state'],'blocked')
            self.assertTrue(broker.handle({'operation':'generation_workflow_capabilities'})['automatic_recovery'])
        self.assertIn('generation_workflow_resume',operations)
    def test_same_tools_cover_short_and_long_formats(self):
        calls=[]
        fake=module('generation_control',call=lambda operation,**kw:(calls.append((operation,kw)) or {'state':'accepted'}))
        sys.modules.pop('workflow_tools',None)
        with patch.dict(sys.modules,{'generation_control':fake}):
            import workflow_tools
            class Server:
                def __init__(self):self.tools={}
                def tool(self,**kwargs):
                    def decorator(fn):self.tools[fn.__name__]=fn;return fn
                    return decorator
            server=Server();workflow_tools.register(server,lambda v:v)
            server.tools['resume_video_generation']('short-resume-v1','catarsis','a'*32)
            server.tools['resume_video_generation']('long-resume-v1','documentary','b'*32)
        self.assertEqual([row[1]['kind'] for row in calls],['catarsis','documentary'])
        self.assertEqual(len(server.tools),7)

class CheckpointBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.job=Path(self.temp.name)
        self.task=dict(date='2026-11-06',topics={c.CHANNELS[1]:'Historical subject'})
        self.video=b'unchanged existing video bytes'
        (self.job/'video.mp4').write_bytes(self.video)
        (self.job/'thumbnail.jpg').write_bytes(b'thumbnail')
        for name,value in (('metadata.json',{}),('project.json',dict(music_provider='epidemic')),('editorial-plan.json',{})):
            c.write(self.job/name,value)
    def short_modules(self,scope='production'):
        from contextlib import nullcontext
        editorial=module('test_checkpoint_editorial',external=lambda *a:None,__file__=__file__)
        exec('def build(*args,**kwargs):raise AssertionError("must reuse existing video")',editorial.__dict__)
        def approve(*args):
            c.write(self.job/'approval.json',dict(scope=scope))
            return dict(scope=scope)
        core=module('daily_core',approval=Mock(side_effect=approve))
        review=Mock()
        modules={'test_checkpoint_editorial':editorial,'editorial':editorial,'daily_core':core,
            'generation_worker':module('generation_worker',manual_editorial=lambda *a,**kw:nullcontext(),public_metadata=lambda v:v),
            'autonomous_generation':module('autonomous_generation',Supervisor=type('Supervisor',(),{'__init__':lambda *a,**k:None})),
            'credit_repair':module('credit_repair',native_review_function=lambda editor:review)}
        return modules,core,review
    def test_short_reuses_mp4_but_keeps_native_review_and_native_approval(self):
        c.write(self.job/'qa.json',dict(technical_checks_passed=True,sha256=c.digest(self.job/'video.mp4')))
        modules,core,review=self.short_modules()
        with patch.dict(sys.modules,modules),patch.object(jobs,'semantic_history'),patch.object(jobs,'source_delivery',side_effect=lambda j,old,g:old):
            value=jobs.run_catarsis(self.job,self.task,c.CHANNELS[1],'a'*32,lambda:None)
        self.assertEqual(value['state'],'ready');review.assert_called_once();core.approval.assert_called_once()
        self.assertTrue(review.call_args.args[-1]);self.assertEqual((self.job/'video.mp4').read_bytes(),self.video)
    def test_short_cannot_mark_nonproduction_approval_ready(self):
        c.write(self.job/'qa.json',dict(technical_checks_passed=True,sha256=c.digest(self.job/'video.mp4')))
        modules,_,_=self.short_modules(scope='rehearsal')
        with patch.dict(sys.modules,modules),patch.object(jobs,'semantic_history'),patch.object(jobs,'source_delivery',side_effect=lambda j,old,g:old),self.assertRaisesRegex(RuntimeError,'approval_required'):
            jobs.run_catarsis(self.job,self.task,c.CHANNELS[1],'a'*32,lambda:None)
    def test_short_bad_qa_never_reaches_a_review_or_approval(self):
        c.write(self.job/'qa.json',dict(technical_checks_passed=False,sha256=c.digest(self.job/'video.mp4')))
        modules,core,review=self.short_modules()
        with patch.dict(sys.modules,modules),patch.object(jobs,'semantic_history'),patch.object(jobs,'source_delivery',side_effect=lambda j,old,g:old),self.assertRaisesRegex(RuntimeError,'qa_not_valid'):
            jobs.run_catarsis(self.job,self.task,c.CHANNELS[1],'a'*32,lambda:None)
        review.assert_not_called();core.approval.assert_not_called()
    def doc_modules(self):
        worker=module('documentary_worker',calibrate=Mock(return_value={}),dependencies=Mock(return_value={}),quality=Mock(),approve=Mock(),finish=Mock())
        return worker,{'documentary_worker':worker,'documentary_common':module('documentary_common',MODULES=())}
    def test_documentary_reuses_mp4_and_preserves_quality_and_approval(self):
        c.write(self.job/'qa.json',dict(passed=True,video_sha256=c.digest(self.job/'video.mp4')))
        (self.job/'review-sheet-0.jpg').write_bytes(b'frame sample')
        worker,modules=self.doc_modules()
        with patch.dict(sys.modules,modules):jobs.run_documentary(self.job,{},'a'*32,lambda:None)
        worker.quality.assert_called_once();worker.approve.assert_called_once();worker.finish.assert_not_called()
        self.assertEqual((self.job/'video.mp4').read_bytes(),self.video)
    def test_documentary_bad_hash_does_not_spend_on_a_review(self):
        c.write(self.job/'qa.json',dict(passed=True,video_sha256='bad'))
        worker,modules=self.doc_modules()
        with patch.dict(sys.modules,modules),self.assertRaisesRegex(RuntimeError,'qa_not_valid'):
            jobs.run_documentary(self.job,{},'a'*32,lambda:None)
        worker.quality.assert_not_called();worker.approve.assert_not_called()

class ResumeIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ident='a'*32;self.state=self.root/'catarsis'/self.ident
        self.state.mkdir(parents=True)
        c.write(self.state/'status.json',dict(state='blocked'))
        c.write(self.state/'workflow.json',dict(attempts=[],requests={},enabled=True))
        self.broker=types.SimpleNamespace(active={},publication=None,launch=Mock(),
            status=lambda ident:c.read(self.state/'status.json'))
        self.fake_modules={'generation_service':module('generation_service',denied=lambda code:dict(state='blocked',error_code=code),safe_error=str),
            'history_data':module('history_data',timestamp=lambda:'2026-11-07T00:00:00Z'),
            'publication_service':module('publication_service',controls=lambda:())}
        self.inspect=Mock(return_value=({},dict(state='blocked'),dict(request_sha256='hash',attempts=[],requests={}),{}))
    def invoke(self):return jobs.start(self.broker,'catarsis',self.ident,request_id='transport-resume-v1')
    def test_transport_repetition_never_launches_a_second_worker(self):
        with patch.dict(sys.modules,self.fake_modules),patch.object(c,'STATE',self.root),patch.object(jobs,'inspect',self.inspect),patch.object(jobs,'frozen_sources',return_value={}):
            first=self.invoke();second=self.invoke()
        self.assertEqual(first,second);self.broker.launch.assert_called_once();self.inspect.assert_called_once()
        self.assertEqual(len(c.read(self.state/'workflow.json')['attempts']),1)
    def test_launch_failure_preserves_idempotency_and_releases_the_active_slot(self):
        self.broker.launch.side_effect=RuntimeError('worker_launch_failed')
        with patch.dict(sys.modules,self.fake_modules),patch.object(c,'STATE',self.root),patch.object(jobs,'inspect',self.inspect),patch.object(jobs,'frozen_sources',return_value={}):
            self.assertEqual(self.invoke()['state'],'blocked');self.assertEqual(self.invoke()['state'],'blocked')
        self.assertEqual(self.broker.active,{});self.broker.launch.assert_called_once()
        self.assertEqual(len(c.read(self.state/'workflow.json')['attempts']),1)

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.policy=dict(modules=['generation_worker.py'],native_modules=[],client_uid=os_uid(),client_gid=os_gid(),python='/usr/bin/python3',paid_limits={})
    def manifest(self):
        return dict(version=1,release_id='test',files=[dict(target='generation_worker.py',source='automation/autonomy/test.py',sha256='a'*64,expected_sha256='b'*64)],
            tests=[dict(source='automation/autonomy/tests/test_x.py',path='test_x.py',sha256='c'*64)])
    def test_manifest_cannot_write_credentials_units_or_other_paths(self):
        for name in ('../secrets.py','/etc/config.json','config.py','server.py','a/b.py'):
            value=self.manifest();value['files'][0]['target']=name
            with self.subTest(name=name),self.assertRaises(RuntimeError):admin.validate_manifest(value,self.policy)
    def test_candidate_directories_remain_readable_under_private_root_umask(self):
        import os
        previous=os.umask(0o077)
        try:
            directory=admin.public_directory(self.root/'candidate')
            admin.atomic(directory/'test.py',b'# public test code',0o644)
        finally:os.umask(previous)
        self.assertEqual(directory.stat().st_mode&0o777,0o755)
        self.assertEqual((directory/'test.py').stat().st_mode&0o777,0o644)
    def test_release_requires_tests_and_unique_targets(self):
        value=self.manifest();admin.validate_manifest(value,self.policy)
        value['tests']=[]
        with self.assertRaisesRegex(RuntimeError,'tests_required'):admin.validate_manifest(value,self.policy)
        value=self.manifest();value['files'].append(copy.deepcopy(value['files'][0]))
        with self.assertRaises(RuntimeError):admin.validate_manifest(value,self.policy)
    def test_release_does_not_allow_test_fixture_escape(self):
        value=self.manifest();value['tests'][0]['path']='../../host.py'
        with self.assertRaisesRegex(RuntimeError,'path_rejected'):admin.validate_manifest(value,self.policy)
    def test_secrets_are_withheld_but_paths_and_source_hashes_are_not_secrets(self):
        self.assertTrue(admin.sensitive('API_KEY = "this-is-a-secret-value"'))
        self.assertTrue(admin.sensitive('value = "https://host/x?access_token=private"'))
        self.assertFalse(admin.sensitive('KEY = Path("/home/user/api-key")\nSOURCE_HASH = "'+'a'*64+'"'))
    def test_root_controller_never_executes_a_release_provided_shell_command(self):
        command=admin.tests_command(Path('/var/tmp/fixture-abc'),self.policy)
        self.assertIn('--property=PrivateNetwork=yes',command)
        self.assertIn('--property=ProtectHome=tmpfs',command)
        self.assertIn('--property=User=videoagent',command)
        self.assertIn('--property=InaccessiblePaths=/run/credentials /run/video-agent-prepare /run/video-workflow-maintenance',command)
        self.assertNotIn('bash',command)
    def test_ordinary_releases_preserve_the_remote_maintenance_contract(self):
        for name in ('generation_service.py','generation_tools.py','workflow_tools.py'):
            with self.subTest(name=name),self.assertRaises(RuntimeError):admin.invariants({name:b'# removed bridge\n'})
    def test_two_runtime_test_units_have_distinct_names(self):
        first=admin.tests_command(Path('/var/tmp/test'),dict(self.policy,python='/usr/bin/python3'))
        second=admin.tests_command(Path('/var/tmp/test'),dict(self.policy,python='/opt/mcp/bin/python3'))
        self.assertNotEqual(next(x for x in first if x.startswith('--unit=')),next(x for x in second if x.startswith('--unit=')))
    def test_same_deployment_is_idempotent(self):
        controller=admin.Controller(self.policy)
        request=dict(operation='deploy',release_id='test',commit_sha='a'*40,manifest_sha256='b'*64)
        with patch.object(admin,'STORE',self.root):
            first=controller.handle(request);second=controller.handle(request)
        self.assertEqual(first,second);self.assertEqual(len(list(self.root.glob('deployment-*.json'))),1)
    def test_inventory_rejects_arbitrary_source_names(self):
        with self.assertRaisesRegex(RuntimeError,'not_allowed'):admin.source('../../root.key',self.policy)
    def test_interrupted_install_rolls_back_only_verified_files(self):
        code=self.root/'code';code.mkdir();backup=self.root/'backup';backup.mkdir()
        old=b'# previous\n';new=b'# candidate\n'
        (code/'generation_worker.py').write_bytes(new);(backup/'generation_worker.py').write_bytes(old)
        value=dict(backup=str(backup),transaction=[dict(name='generation_worker.py',existed=True,before_sha256=admin.sha(old),after_sha256=admin.sha(new))])
        with patch.object(admin,'ROOT',code),patch.object(admin,'call') as call:
            admin.restore_interrupted(value)
        self.assertEqual((code/'generation_worker.py').read_bytes(),old);call.assert_called_once()
    def test_unknown_changes_are_not_overwritten_by_rollback(self):
        code=self.root/'code';code.mkdir();backup=self.root/'backup';backup.mkdir()
        (code/'generation_worker.py').write_bytes(b'# manual change\n')
        value=dict(backup=str(backup),transaction=[dict(name='generation_worker.py',existed=True,before_sha256='a'*64,after_sha256='b'*64)])
        with patch.object(admin,'ROOT',code),self.assertRaisesRegex(RuntimeError,'source_changed'):admin.restore_interrupted(value)

class DeploymentTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.code=self.root/'code';self.code.mkdir()
        self.store=self.root/'store';self.store.mkdir();self.run=self.root/'run';self.run.mkdir()
        self.old=b'# previous verified generation module\n';self.new=b'# corrected generation module\n'
        (self.code/'generation_worker.py').write_bytes(self.old)
        self.test=b'import unittest\nclass Example(unittest.TestCase):\n def test_ok(self):self.assertTrue(True)\n'
        self.manifest=dict(version=1,release_id='example',files=[dict(target='generation_worker.py',
            source='automation/example/worker.py',sha256=admin.sha(self.new),expected_sha256=admin.sha(self.old))],
            tests=[dict(source='automation/example/test_worker.py',path='test_worker.py',sha256=admin.sha(self.test))])
        raw=json.dumps(self.manifest).encode()
        self.deployment=dict(deployment_id='a'*32,release_id='example',commit_sha='b'*40,manifest_sha256=admin.sha(raw))
        self.policy=dict(modules=['generation_worker.py'],native_modules=[],client_uid=os_uid(),client_gid=os_gid(),python='/usr/bin/python3',paid_limits={})
        self.files={'automation/releases/example/manifest.json':raw,'automation/example/worker.py':self.new,'automation/example/test_worker.py':self.test}
        for target,name,value in ((admin,'ROOT',self.code),(admin,'STORE',self.store),(admin,'RUN',self.run),(admin,'LOCK',self.root/'install.lock')):
            mocked=patch.object(target,name,value);mocked.start();self.addCleanup(mocked.stop)
        self.git=patch.object(admin,'git_file',side_effect=lambda commit,path:self.files[path]).start()
        self.broker=patch.object(admin,'broker',return_value={'state':'idle'}).start()
        self.controls=patch.object(admin,'controls',return_value=('paused',1,b'disabled')).start()
        self.call=patch.object(admin,'call',return_value=b'').start()
        self.health=patch.object(admin,'health').start()
        self.tests=patch.object(admin.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='',stderr='Ran 1 test in 0.001s\nOK')).start()
        self.addCleanup(patch.stopall)
    def test_install_requires_test_completion_and_persists_exact_backup(self):
        admin.apply(self.deployment,self.policy)
        self.assertEqual((self.code/'generation_worker.py').read_bytes(),self.new)
        backup=self.store/'backups'/('a'*32)/'generation_worker.py'
        self.assertEqual(backup.read_bytes(),self.old)
        self.assertEqual(admin.read(self.store/('deployment-'+'a'*32+'.json'))['state'],'installed')
        self.assertFalse((self.run/'deploying.json').exists());self.health.assert_called_once()
    def test_health_failure_restores_all_original_bytes(self):
        self.health.side_effect=RuntimeError('health_failed')
        with self.assertRaisesRegex(RuntimeError,'health_failed'):admin.apply(self.deployment,self.policy)
        self.assertEqual((self.code/'generation_worker.py').read_bytes(),self.old)
        self.assertEqual(admin.read(self.store/('deployment-'+'a'*32+'.json'))['state'],'rolled_back')
        self.assertFalse((self.run/'deploying.json').exists())
    def test_zero_discovered_tests_block_the_install(self):
        self.tests.return_value=types.SimpleNamespace(returncode=0,stdout='',stderr='Ran 0 tests in 0s\nOK')
        with self.assertRaisesRegex(RuntimeError,'offline_tests_failed'):admin.apply(self.deployment,self.policy)
        self.assertEqual((self.code/'generation_worker.py').read_bytes(),self.old);self.health.assert_not_called()
    def test_source_hash_drift_blocks_before_testing_or_writing(self):
        (self.code/'generation_worker.py').write_bytes(b'# different live edit\n')
        with self.assertRaisesRegex(RuntimeError,'installed_source_changed'):admin.apply(self.deployment,self.policy)
        self.tests.assert_not_called()
        self.assertEqual((self.code/'generation_worker.py').read_bytes(),b'# different live edit\n')

def os_uid():return __import__('os').geteuid()
def os_gid():return __import__('os').getegid()

if __name__=='__main__':unittest.main()
