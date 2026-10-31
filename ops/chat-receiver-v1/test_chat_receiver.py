import contextlib,datetime as dt,importlib.util,json,os,sys,tempfile,types,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
import chat_package as p
import chat_receiver as r
import chat_bridge_patch as bridge
import test_chat_package as package_fixtures

CORE='''import datetime as dt,hashlib,json,os
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).parent
ZONE=ZoneInfo('America/Santiago')
CHANNELS=('stunning-facts-of-history','stunning-revelations')
class Blocked(RuntimeError):pass
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def atomic(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
def now():return dt.datetime(2026,10,31,19,0,tzinfo=ZONE)
def day():return '2026-10-31'
def in_period(p,date):return p['start_date']<=date<=p['end_date']
def path_inside(p,root):
 p=Path(p).resolve();root=Path(root).resolve()
 if not p.is_relative_to(root) or not p.is_file():raise Blocked('artifact_outside_job_or_missing')
 return p
def approval(directory,channel,date,allow_rehearsal=False):
 directory=Path(directory);a=load(directory/'approval.json')
 if a.get('scope')!=('rehearsal' if allow_rehearsal else 'production'):raise Blocked('non_publishable_scope')
 if a.get('date')!=date or a.get('channel')!=channel:raise Blocked('approval_identity_mismatch')
 for name,expected in a['artifacts'].items():
  if sha(path_inside(directory/name,directory))!=expected:raise Blocked('approved_artifact_changed')
 video=path_inside(directory/'video.mp4',directory)
 if sha(video)!=a['video_sha256']:raise Blocked('approved_video_changed')
 qa=load(directory/'qa.json');review=load(directory/'visual-review.json')
 if not qa.get('technical_checks_passed') or qa.get('sha256')!=a['video_sha256']:raise Blocked('qa_missing_failed_or_hash_mismatch')
 if not review.get('approved') or review.get('video_sha256')!=a['video_sha256']:raise Blocked('visual_review_missing_failed_or_hash_mismatch')
 trace=load(directory/'vision-evidence.json')
 if not trace.get('image_inputs') or not trace.get('successful_agent_exit') or trace.get('video_sha256')!=a['video_sha256']:raise Blocked('vision_tool_evidence_missing')
 for image in trace['image_inputs']:
  if sha(path_inside(directory/image['path'],directory))!=image['sha256']:raise Blocked('vision_input_changed')
 return a
'''

REMOTE='''calls=[]
class Publisher:
 def __init__(self,policy,directory,job):
  self.directory,self.job,self.dry=directory,job,False
 def run(self):
  approval(self.directory,self.job['channel'],self.job['date'],allow_rehearsal=False)
  calls.append('network')
  return {'platforms':{'youtube':{'state':'published','video_id':'fixture'}}}
'''

class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.old_root=r.ROOT;r.ROOT=self.root;self.addCleanup(setattr,r,'ROOT',self.old_root)
        for name,source in (('chat_receiver.py',Path(r.__file__).read_text()),('chat_package.py',Path(p.__file__).read_text()),('daily_core.py',bridge.core_candidate(CORE))):
            (self.root/name).write_text(source)
        self.modules={}
        def install_module(name,module):
            self.modules[name]=sys.modules.get(name);sys.modules[name]=module
        spec=importlib.util.spec_from_file_location('daily_core',self.root/'daily_core.py')
        self.c=importlib.util.module_from_spec(spec);install_module('daily_core',self.c);spec.loader.exec_module(self.c)
        helpers=types.ModuleType('helpers');helpers.daily=types.SimpleNamespace(locked=contextlib.nullcontext)
        install_module('helpers',helpers)
        music=types.ModuleType('music_provider');music.publish_preflight=Mock(return_value={'provider':'manifest','remote_mutations':0})
        self.music=music;install_module('music_provider',music)
        remote=types.ModuleType('daily_remote');remote.approval=self.c.approval
        exec(bridge.remote_candidate(REMOTE),remote.__dict__)
        remote.guard_window=Mock();install_module('daily_remote',remote);self.remote=remote
        def restore():
            for name,old in self.modules.items():
                if old is None:sys.modules.pop(name,None)
                else:sys.modules[name]=old
        self.addCleanup(restore)
        production=self.root/'runtime/production';production.mkdir(parents=True)
        self.c.atomic(production/'generation-mode.json',{'generation':'on_demand_codex_chat','vps_generation':'disabled'})
        self.c.atomic(production/'activation.json',{'status':'enabled'})
        self.c.atomic(production/'readiness.json',{'checks':{'fixture':True},'code_sha256':{n:p.digest(self.root/n) for n in ('daily_core.py','chat_receiver.py','chat_package.py')}})
        self.c.atomic(self.root/'activation-package-20261019/activation-policy.json',{'start_date':'2026-10-20','end_date':'2026-11-14','publication_window_end':'21:30'})
        keyfile=production/r.KEY_NAME;keyfile.write_bytes(b'k'*32);keyfile.chmod(0o600)
        self.package=package_fixtures.PackageTests();self.package.setUp();self.addCleanup(self.package.doCleanups)
        self.expected=self.package.build()['manifest_sha256']
        self.destination=r.destination(self.c,p.CHANNELS[0],'2026-10-31')
        qa=patch.object(r,'technical_qa',side_effect=lambda directory:{'technical_checks_passed':True,'sha256':p.digest(directory/'video.mp4'),'checks':{'fixture_only':True}})
        qa.start();self.addCleanup(qa.stop)
    def receive(self):return r.receive(self.package.archive,self.expected,True)
    def test_receive_approves_without_cli_evidence_and_blocks_publication(self):
        result=self.receive()
        self.assertFalse(result['publication_invoked'])
        self.assertTrue((self.destination/'blocked.json').exists())
        trace=self.c.load(self.destination/'vision-evidence.json')
        self.assertEqual(trace['review_origin'],'codex_chat')
        self.assertNotIn('successful_agent_exit',trace)
        self.c.approval(self.destination,p.CHANNELS[0],'2026-10-31')
        self.assertFalse(self.remote.calls)
    def test_explicit_acceptance_required(self):
        with self.assertRaisesRegex(p.InvalidPackage,'explicit_chat_review_acceptance_required'):
            r.receive(self.package.archive,self.expected,False)
        self.assertFalse(self.destination.exists())
    def test_existing_empty_job_not_overwritten(self):
        self.destination.mkdir(parents=True)
        with self.assertRaisesRegex(p.InvalidPackage,'job_already_exists'):self.receive()
        self.assertEqual(list(self.destination.iterdir()),[])
    def test_atomic_directory_move_refuses_existing_empty_directory(self):
        source=self.root/'source';target=self.root/'target';source.mkdir();target.mkdir()
        with self.assertRaisesRegex(p.InvalidPackage,'job_already_exists'):r.rename_new(source,target)
        self.assertTrue(source.exists());self.assertTrue(target.exists())
    def test_changed_native_approval_invalidates_signature(self):
        self.receive();approval=self.c.load(self.destination/'approval.json');approval['topic']='tampered'
        self.c.atomic(self.destination/'approval.json',approval)
        with self.assertRaisesRegex(self.c.Blocked,'chat_approval_hash_mismatch'):
            self.c.approval(self.destination,p.CHANNELS[0],'2026-10-31')
    def test_tampered_video_fails_native_gate(self):
        self.receive();(self.destination/'video.mp4').write_bytes(b'tampered')
        with self.assertRaises(self.c.Blocked):self.c.approval(self.destination,p.CHANNELS[0],'2026-10-31')
    def test_unsigned_external_record_cannot_approve(self):
        self.receive();record=self.c.load(self.destination/r.RECEIPT_NAME);record['signature']='0'*64
        self.c.atomic(self.destination/r.RECEIPT_NAME,record)
        with self.assertRaisesRegex(self.c.Blocked,'signature_mismatch'):self.c.approval(self.destination,p.CHANNELS[0],'2026-10-31')
    def test_native_timer_cannot_publish_imported_job_without_authorization(self):
        self.receive();job=self.c.load(self.destination/'job.json')
        with self.assertRaisesRegex(self.c.Blocked,'chat_publication_not_authorized'):
            self.remote.Publisher({},self.destination,job).run()
        self.assertFalse(self.remote.calls)
    def test_explicit_publication_can_release_only_matching_request(self):
        self.receive()
        result=r.publish(p.CHANNELS[0],'2026-10-31',self.package.identity['request_id'],True)
        self.assertEqual(result['status'],'publication_attempt_recorded')
        self.assertFalse((self.destination/'blocked.json').exists())
        self.assertEqual(self.remote.calls,['network'])
    def test_wrong_request_cannot_authorize_publication(self):
        self.receive()
        with self.assertRaisesRegex(p.InvalidPackage,'publication_request_id_mismatch'):
            r.publish(p.CHANNELS[0],'2026-10-31','wrong-request',True)
        self.assertFalse(self.remote.calls)
    def test_publication_requires_execute_flag(self):
        with self.assertRaisesRegex(p.InvalidPackage,'explicit_publication_execution_required'):
            r.publish(p.CHANNELS[0],'2026-10-31','fixture',False)
        self.assertFalse(self.remote.calls)
    def test_date_gate_prevents_backfill_or_future_import(self):
        with patch.object(self.c,'day',return_value='2026-11-01'),self.assertRaisesRegex(p.InvalidPackage,'current_authorized_date'):self.receive()
        self.assertFalse(self.destination.exists())
    def test_qa_failure_prevents_destination_creation(self):
        with patch.object(r,'technical_qa',side_effect=p.InvalidPackage('video_decode_failed')):
            with self.assertRaisesRegex(p.InvalidPackage,'video_decode_failed'):self.receive()
        self.assertFalse(self.destination.exists())
    def test_music_preflight_failure_prevents_approval_and_job_creation(self):
        self.music.publish_preflight.side_effect=self.c.Blocked('music_credits_missing')
        with self.assertRaises(self.c.Blocked):self.receive()
        self.assertFalse(self.destination.exists())
    def test_changed_receiver_hash_blocks_import(self):
        (self.root/'chat_receiver.py').write_text('tampered')
        with self.assertRaisesRegex(p.InvalidPackage,'protected_source_changed'):self.receive()
        self.assertFalse(self.destination.exists())
    def test_private_signing_key_required(self):
        (self.root/'runtime/production'/r.KEY_NAME).chmod(0o644)
        with self.assertRaisesRegex(p.InvalidPackage,'key_permissions_invalid'):self.receive()
        self.assertFalse(self.destination.exists())
    def test_existing_music_cache_never_overwritten(self):
        self.receive()
        cache=self.root/'runtime/music/epidemic-fixture.mp3';cache.parent.mkdir();cache.write_bytes(b'original')
        self.c.atomic(self.destination/'music_credits.json',{'provider':'epidemic','covered_channel':p.CHANNELS[0],'filename':cache.name,'sha256':'0'*64})
        with self.assertRaisesRegex(p.InvalidPackage,'existing_cache_hash_mismatch'):
            r.music_cache(self.c,self.destination,dict(self.package.identity,files={}))
        self.assertEqual(cache.read_bytes(),b'original')
    def test_legacy_approval_and_publishing_do_not_require_chat_key(self):
        self.receive()
        trace=self.c.load(self.destination/'vision-evidence.json');trace.pop('review_origin');trace['successful_agent_exit']=True
        self.c.atomic(self.destination/'vision-evidence.json',trace)
        approval=self.c.load(self.destination/'approval.json');approval['artifacts']['vision-evidence.json']=p.digest(self.destination/'vision-evidence.json')
        self.c.atomic(self.destination/'approval.json',approval)
        (self.root/'runtime/production'/r.KEY_NAME).unlink()
        self.c.approval(self.destination,p.CHANNELS[0],'2026-10-31')
        self.remote.Publisher({},self.destination,self.c.load(self.destination/'job.json')).run()
        self.assertEqual(self.remote.calls,['network'])

if __name__=='__main__':unittest.main(verbosity=2)
