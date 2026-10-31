"""Install the chat receiver under the existing controller lock; never publish."""
import contextlib,copy,hashlib,io,json,os,secrets,shutil,subprocess,sys
from pathlib import Path
from chat_bridge_patch import core_candidate,remote_candidate

ROOT=Path('/home/videoagent/video-automation')
RUNTIME_FILES=('chat_package.py','chat_receiver.py')
TEST_FILES=('test_chat_smoke.py',)

def main():
    os.umask(0o077)
    kit=Path(__file__).resolve().parent
    expected=json.loads((kit/'KIT-SHA256.json').read_text())
    def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for name,digest in expected.items():
        if Path(name).name!=name or sha(kit/name)!=digest:raise RuntimeError('kit_hash_mismatch')
    sys.path.insert(0,str(ROOT))
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        import daily_core as c
        from helpers import daily as d
    if Path(c.__file__).resolve()!=ROOT/'daily_core.py' or c.ROOT.resolve()!=ROOT or tuple(c.CHANNELS)!=('stunning-facts-of-history','stunning-revelations'):
        raise RuntimeError('unexpected_runtime_or_channels')
    production=ROOT/'runtime/production';readiness=production/'readiness.json'
    stage=ROOT/'runtime/chat-receiver-install-v1';backup=stage/'backup'
    key_path=production/'.chat-acceptance-key'
    controls=[production/'generation-mode.json',production/'activation.json',production/'PAUSED']
    def baseline(expected_state=None):
        ready=c.load(readiness)
        if not ready.get('checks') or not all(v is True for v in ready['checks'].values()):raise RuntimeError('readiness_not_passed')
        if not {'daily_core.py','daily_remote.py'}<=ready.get('code_sha256',{}).keys():raise RuntimeError('source_hashes_missing')
        for name,value in ready['code_sha256'].items():
            path=(ROOT/name).resolve()
            if not path.is_relative_to(ROOT) or c.sha(path)!=value:raise RuntimeError('protected_source_changed')
        mode=c.load(controls[0])
        if mode.get('generation')!='on_demand_codex_chat' or mode.get('vps_generation')!='disabled':raise RuntimeError('generation_migration_required')
        state={'readiness':sha(readiness),'controls':{str(p):sha(p) if p.exists() else None for p in controls},
               'activation_tests':sha(ROOT/'test_activation.py'),
               'instagram_tests':sha(ROOT/'test_instagram_upload_once.py') if (ROOT/'test_instagram_upload_once.py').exists() else None}
        if expected_state is not None and state!=expected_state:raise RuntimeError('baseline_changed_during_tests')
        return ready,state
    with d.locked():
        ready,original=baseline()
        if any((ROOT/name).exists() for name in RUNTIME_FILES):raise RuntimeError('receiver_module_already_exists')
        stage.mkdir(exist_ok=False);backup.mkdir()
        for name in ('daily_core.py','daily_remote.py'):shutil.copy2(ROOT/name,backup/name)
        shutil.copy2(readiness,backup/'readiness.json')
        for name in (*RUNTIME_FILES,*TEST_FILES,'chat_bridge_patch.py'):shutil.copy2(kit/name,stage/name)
    (stage/'daily_core.py').write_text(core_candidate((backup/'daily_core.py').read_text()))
    (stage/'daily_remote.py').write_text(remote_candidate((backup/'daily_remote.py').read_text()))
    names=('daily_core.py','daily_remote.py',*RUNTIME_FILES)
    staged={name:sha(stage/name) for name in (*names,*TEST_FILES,'chat_bridge_patch.py')}
    runner='''import contextlib,importlib.util,io,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
root,stage=map(Path,sys.argv[1:]);sys.path[:0]=[str(stage),str(root)]
with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
 for name in ('chat_package','chat_receiver','daily_core','daily_remote'):
  spec=importlib.util.spec_from_file_location(name,stage/(name+'.py'))
  module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
suite=unittest.TestSuite()
sources=[(root,'test_activation')]
if (root/'test_instagram_upload_once.py').exists():sources.append((root,'test_instagram_upload_once'))
sources += [(stage,name) for name in ('test_chat_smoke',)]
for folder,name in sources:
 spec=importlib.util.spec_from_file_location(name,folder/(name+'.py'))
 module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
 suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
with patch('requests.sessions.Session.request',side_effect=AssertionError('test_network_forbidden')):
 result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'passed':result.wasSuccessful(),'tests_run':result.testsRun}))
sys.exit(0 if result.wasSuccessful() else 2)
'''
    (stage/'run_tests.py').write_text(runner)
    staged['run_tests.py']=sha(stage/'run_tests.py')
    tests=subprocess.run([sys.executable,'-B',str(stage/'run_tests.py'),str(ROOT),str(stage)],cwd=ROOT,text=True,capture_output=True)
    (stage/'tests.log').write_text(tests.stdout+tests.stderr)
    if tests.returncode:raise RuntimeError('candidate_tests_failed_see_private_tests_log')
    summary=json.loads(tests.stdout.strip().splitlines()[-1])
    if not summary.get('passed') or summary.get('tests_run',0)<34:raise RuntimeError('incomplete_test_suite')
    def install(source,target,mode):
        temporary=target.with_name(target.name+'.chat-receiver-tmp')
        with temporary.open('x') as stream:stream.write(source.read_text())
        temporary.chmod(mode);os.replace(temporary,target)
    with d.locked():
        baseline(original)
        if any((ROOT/name).exists() for name in RUNTIME_FILES):raise RuntimeError('receiver_file_appeared')
        if {name:sha(stage/name) for name in staged}!=staged:raise RuntimeError('candidate_changed_during_tests')
        updated=copy.deepcopy(ready)
        updated['code_sha256'].update({name:staged[name] for name in names})
        updated['checks']['chat_receiver_and_approval_regressions']=True
        updated['checks']['chat_publication_requires_separate_authorization']=True
        updated['chat_receiver_validation']={
            'validated_at':c.now().isoformat(),'previous_readiness_sha256':original['readiness'],
            'candidate_sha256':staged,'tests_log_sha256':sha(stage/'tests.log'),'tests_run':summary['tests_run'],
            'scope':'Offline candidate smoke and legacy regressions. Extended receiver tests were run locally against the same receiver sources. No media received, no identities queried, no publication invoked. Legacy approvals and native music preflight retained.'}
        installed=[];created_key=False
        try:
            if not key_path.exists():
                descriptor=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(descriptor,'wb') as stream:
                    stream.write(secrets.token_bytes(32));stream.flush();os.fsync(stream.fileno())
                created_key=True
            for name in names:
                mode=(ROOT/name).stat().st_mode&0o777 if (ROOT/name).exists() else 0o600
                install(stage/name,ROOT/name,mode);installed.append(name)
            c.atomic(readiness,updated)
            if c.load(readiness)!=updated or any(sha(ROOT/name)!=staged[name] for name in names):raise RuntimeError('post_install_verification_failed')
            check=subprocess.run([sys.executable,'-B',str(ROOT/'chat_receiver.py'),'check-system'],cwd=ROOT,text=True,capture_output=True)
            if check.returncode or json.loads(check.stdout.strip().splitlines()[-1]).get('status')!='chat_receiver_ready':raise RuntimeError('receiver_self_check_failed')
        except Exception:
            for name in reversed(installed):
                if (backup/name).exists():install(backup/name,ROOT/name,(backup/name).stat().st_mode&0o777)
                else:(ROOT/name).unlink()
            c.atomic(readiness,ready)
            if created_key:key_path.unlink(missing_ok=True)
            raise
    print(json.dumps({'status':'installed','receiver':'ready','tests_run':summary['tests_run'],
        'received_packages':0,'publication_invoked':False,'cron_changed':False,'backup':str(backup)},ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'not_confirmed','reason':str(exc) if type(exc) is RuntimeError else type(exc).__name__}))
        raise SystemExit(2)
