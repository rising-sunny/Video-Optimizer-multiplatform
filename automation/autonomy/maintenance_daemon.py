#!/usr/bin/env python3
"""Root controller: data-only module releases, isolated tests, backup and rollback.

Installed outside the generation-module tree. The release protocol cannot alter
this controller, its root-owned policy, credentials, job data or systemd units.
"""
import ast
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

POLICY=Path('/etc/video-workflow-maintenance/policy.json')
STORE=Path('/var/lib/video-workflow-maintenance')
RUN=Path('/run/video-workflow-maintenance')
ROOT=Path('/opt/video-agent-mcp')
REPO=Path('/home/videoagent/Video-Optimizer-multiplatform')
AUTOMATION=Path('/home/videoagent/video-automation')
LOCK=Path('/run/lock/video-generation-install.lock')
SCHEMAS={'inventory':{'operation'},'source':{'operation','module'},
    'deploy':{'operation','release_id','commit_sha','manifest_sha256'},'status':{'operation','deployment_id'}}

def safe(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise RuntimeError('maintenance_symlink_rejected')
    return path
def sha(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(safe(path).read_text())
def public_directory(path):
    path=safe(path);path.mkdir(mode=0o755,parents=True,exist_ok=True);path.chmod(0o755);return path
def atomic(path,data,mode=0o600):
    path=safe(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.maintenance-')
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode);stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:Path(temp).unlink(missing_ok=True)
def record(path,value):atomic(path,json.dumps(value,indent=2).encode())
def now():return datetime.now(timezone.utc).isoformat()
def clean(value):
    text=re.sub(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+','[hidden]',str(value))
    text=re.sub(r'(?i)Bearer\s+\S+','Bearer [hidden]',text)
    return re.sub(r'https?://[^\s"<>]+','[URL]',text)[-3000:]
def call(args,timeout=60):
    result=subprocess.run(args,capture_output=True,timeout=timeout)
    if result.returncode:raise RuntimeError('maintenance_command_failed:'+clean(result.stderr.decode(errors='replace')))
    return result.stdout
def broker(operation):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(10);connection.connect('/run/video-agent-prepare/control.sock')
        connection.sendall(json.dumps(dict(operation=operation)).encode()+b'\n')
        with connection.makefile('rb') as stream:raw=stream.readline(1048577)
    if len(raw)>1048576 or not raw.endswith(b'\n'):raise RuntimeError('maintenance_bad_broker_response')
    return json.loads(raw)

def allowed(name,policy):
    return isinstance(name,str) and re.fullmatch(r'[a-z][a-z0-9_]*\.py',name) is not None and (
        name in policy['modules'] or name.startswith('workflow_'))

def sensitive(source):
    tree=ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            names=[n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)]
            if any(re.search(r'(?i)(password|access_token|api_key|signing_key|secret|credential)',name) for name in names):
                try:value=ast.literal_eval(node.value)
                except (ValueError,TypeError):continue
                if isinstance(value,str) and len(value)>8:return True
        if isinstance(node,ast.Constant) and isinstance(node.value,str):
            value=node.value
            if re.search(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,}|(?i:Bearer)\s+[A-Za-z0-9._-]{16,}',value):return True
            if value.startswith('https://'):
                for key,item in urllib.parse.parse_qsl(urllib.parse.urlsplit(value).query):
                    if item and re.search(r'(?i)(token|secret|signature|authorization)',key):return True
    return False

def source(name,policy):
    if name.startswith('native:'):
        bare=name.removeprefix('native:')
        if bare not in policy['native_modules']:raise RuntimeError('maintenance_source_not_allowed')
        path=AUTOMATION/bare
    else:
        if not allowed(name,policy):raise RuntimeError('maintenance_source_not_allowed')
        path=ROOT/name
    raw=safe(path).read_bytes()
    if len(raw)>250000:raise RuntimeError('maintenance_source_too_large')
    withheld=sensitive(raw.decode())
    return dict(module=name,sha256=sha(raw),source=None if withheld else raw.decode(),
        source_withheld=withheld,read_only=True)

def inventory(policy):
    files={p.name:sha(safe(p).read_bytes()) for p in ROOT.glob('*.py') if allowed(p.name,policy)}
    native={name:sha(safe(AUTOMATION/name).read_bytes()) for name in policy['native_modules']}
    readiness_path=safe(AUTOMATION/'runtime/production/readiness.json')
    readiness={}
    if readiness_path.is_file():
        raw=readiness_path.read_bytes();data=json.loads(raw);checks=data.get('checks',{})
        approved={name:data.get('code_sha256',{}).get(name) for name in policy['native_modules']}
        readiness=dict(sha256=sha(raw),checks_passed=sum(v is True for v in checks.values()),checks_total=len(checks),
            all_checks_pass=bool(checks) and all(v is True for v in checks.values()),approved_native_sha256=approved,
            native_files_match=all(approved[name]==value for name,value in native.items()))
    return dict(state='available',modules=files,native_modules=native,readiness=readiness,maintenance_version=1,
        deployments=[read(p) for p in sorted(STORE.glob('deployment-*.json'))[-10:]],read_only=True)

def validate_manifest(manifest,policy):
    if set(manifest)!={'version','release_id','files','tests'} or manifest['version']!=1:
        raise RuntimeError('maintenance_manifest_schema')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',manifest['release_id']):raise RuntimeError('maintenance_release_id')
    if not isinstance(manifest['files'],list) or not 1<=len(manifest['files'])<=100:raise RuntimeError('maintenance_file_count')
    seen=set()
    for row in manifest['files']:
        if set(row)!={'target','source','sha256','expected_sha256'}:raise RuntimeError('maintenance_file_schema')
        if not allowed(row['target'],policy) or row['target'] in seen:raise RuntimeError('maintenance_target_not_allowed')
        seen.add(row['target'])
        for key in ('sha256','expected_sha256'):
            if row[key]!='absent' and not re.fullmatch(r'[a-f0-9]{64}',row[key]):raise RuntimeError('maintenance_hash_invalid')
        if row['sha256']=='absent':raise RuntimeError('maintenance_delete_not_allowed')
        validate_repo_path(row['source'])
    if not isinstance(manifest['tests'],list) or not 1<=len(manifest['tests'])<=100:raise RuntimeError('maintenance_tests_required')
    test_paths=set()
    for row in manifest['tests']:
        if set(row)!={'source','sha256','path'} or not re.fullmatch(r'[a-f0-9]{64}',row['sha256']):raise RuntimeError('maintenance_test_schema')
        validate_repo_path(row['source'])
        relative=Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.suffix not in ('.py','.json','.txt') or row['path'] in test_paths:
            raise RuntimeError('maintenance_test_path_rejected')
        test_paths.add(row['path'])
    if not any(Path(p).name.startswith('test_') and Path(p).suffix=='.py' for p in test_paths):raise RuntimeError('maintenance_no_tests')

def validate_repo_path(value):
    path=Path(value)
    if (not isinstance(value,str) or path.is_absolute() or '..' in path.parts or
        not value.startswith('automation/') or path.suffix not in ('.py','.json','.txt')):
        raise RuntimeError('maintenance_repository_path_rejected')

def git_file(commit,path):
    validate_repo_path(path)
    prefix=['runuser','-u','videoagent','--','git','-C',str(REPO)]
    size=int(call(prefix+['cat-file','-s',commit+':'+path]))
    if size>1024*1024:raise RuntimeError('maintenance_blob_too_large')
    return call(prefix+['show',commit+':'+path])

def tests_command(stage,policy):
    # Test code runs as videoagent, offline, with home/credentials/control sockets
    # hidden. No release-provided command is executed by the root controller.
    return ['systemd-run','--quiet','--wait','--pipe','--collect','--unit=video-workflow-tests-'+stage.name[-16:]+'-'+sha(policy['python'].encode())[:8],
        '--property=User=videoagent','--property=Group=videoagent','--property=PrivateNetwork=yes',
        '--property=PrivateTmp=yes','--property=ProtectHome=tmpfs','--property=ProtectSystem=strict',
        '--property=NoNewPrivileges=yes','--property=PrivateDevices=yes',
        '--property=InaccessiblePaths=/run/credentials /run/video-agent-prepare /run/video-workflow-maintenance',
        '--property=BindReadOnlyPaths='+str(Path(policy['python']).parent.parent),
        '--property=ReadWritePaths='+str(stage/'work'),
        '--property=WorkingDirectory='+str(stage/'work'),
        '--setenv=PYTHONPATH='+str(stage/'candidate')+':'+str(ROOT),
        '--setenv=PYTHONDONTWRITEBYTECODE=1',
        policy['python'],'-B','-m','unittest','discover','-s',str(stage/'tests'),'-p','test_*.py','-q']

def controls():
    path=Path('/home/videoagent/video-automation/runtime/production/PAUSED')
    if not path.is_file():raise RuntimeError('maintenance_daily_pause_required')
    return sha(path.read_bytes()),path.stat().st_mtime_ns,call(['systemctl','show',
        'video-shorts-prepare.timer','video-shorts-publish.timer','-p','ActiveState','-p','UnitFileState'])

def invariants(candidates):
    if 'generation_tools.py' in candidates:
        tree=ast.parse(candidates['generation_tools.py'])
        if not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_workflow_register' for n in ast.walk(tree)):
            raise RuntimeError('maintenance_connector_tools_removed')
    if 'generation_service.py' in candidates:
        tree=ast.parse(candidates['generation_service.py'])
        if not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name)
            and n.func.value.id=='workflow_service' and n.func.attr=='install' for n in ast.walk(tree)):
            raise RuntimeError('maintenance_broker_extension_removed')
    if 'workflow_tools.py' in candidates:
        names={n.name for n in ast.walk(ast.parse(candidates['workflow_tools.py'])) if isinstance(n,ast.FunctionDef)}
        required={'generate_catarsis_single','video_generation_diagnostics','resume_video_generation','video_workflow_inventory',
            'read_video_workflow_source','deploy_video_workflow_release','video_workflow_deployment_status'}
        if not required<=names:raise RuntimeError('maintenance_public_tool_contract_removed')

def health():
    for _ in range(60):
        try:
            capabilities=broker('generation_workflow_capabilities')
            if capabilities.get('maintenance') is True and capabilities.get('native_ready') is True:
                body=json.dumps(dict(jsonrpc='2.0',id=1,method='initialize',params={})).encode()
                request=urllib.request.Request('http://127.0.0.1:8880/mcp',data=body,headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
                try:urllib.request.urlopen(request,timeout=3).close();raise RuntimeError('maintenance_auth_boundary_changed')
                except urllib.error.HTTPError as exc:
                    if exc.code in (401,403):return
                    raise RuntimeError('maintenance_auth_probe_failed') from None
        except (OSError,ValueError,urllib.error.URLError):pass
        time.sleep(.25)
    raise RuntimeError('maintenance_service_health_failed')

def restore_interrupted(value):
    transaction=value.get('transaction',[])
    if not transaction:return
    backup=safe(Path(value['backup']))
    for row in transaction:
        path=safe(ROOT/row['name'])
        actual=sha(path.read_bytes()) if path.exists() else None
        if actual not in (row['before_sha256'],row['after_sha256']):raise RuntimeError('maintenance_interrupted_source_changed')
        if row['existed']:
            raw=safe(backup/row['name']).read_bytes()
            if sha(raw)!=row['before_sha256']:raise RuntimeError('maintenance_backup_changed')
            atomic(path,raw,0o644)
        elif path.exists():path.unlink()
    call(['systemctl','restart','video-agent-prepare.service','video-agent-mcp.service'])

def apply(deployment,policy):
    ident=deployment['deployment_id'];receipt=STORE/('deployment-'+ident+'.json')
    def progress(state,**extra):deployment.update(state=state,updated_at=now(),**extra);record(receipt,deployment)
    flag=RUN/'deploying.json'
    with safe(LOCK).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        atomic(flag,json.dumps(dict(deployment_id=ident)).encode(),0o644)
        try:
            before_controls=controls();progress('waiting_for_idle')
            deadline=time.monotonic()+7200
            while broker('manual_activity').get('state')!='idle':
                if time.monotonic()>deadline:raise RuntimeError('maintenance_idle_wait_timeout')
                time.sleep(2)
            progress('fetching')
            call(['runuser','-u','videoagent','--','env','GIT_TERMINAL_PROMPT=0','GCM_INTERACTIVE=never',
                'git','-C',str(REPO),'fetch','--no-tags','origin',deployment['commit_sha']],timeout=60)
            raw=git_file(deployment['commit_sha'],'automation/releases/'+deployment['release_id']+'/manifest.json')
            if sha(raw)!=deployment['manifest_sha256']:raise RuntimeError('maintenance_manifest_hash_changed')
            manifest=json.loads(raw);validate_manifest(manifest,policy)
            if manifest['release_id']!=deployment['release_id']:raise RuntimeError('maintenance_release_mismatch')
            stage=Path(tempfile.mkdtemp(prefix='video-workflow-tests-',dir='/var/tmp'));stage.chmod(0o755)
            for name in ('candidate','tests','work'):public_directory(stage/name)
            os.chown(stage/'work',policy['client_uid'],policy['client_gid'])
            originals={};candidates={};total=0
            for file in manifest['files']:
                target=safe(ROOT/file['target']);original=target.read_bytes() if target.exists() else None
                if (sha(original) if original is not None else 'absent')!=file['expected_sha256']:
                    raise RuntimeError('maintenance_installed_source_changed')
                value=git_file(deployment['commit_sha'],file['source']);total+=len(value)
                if sha(value)!=file['sha256'] or sensitive(value.decode()):raise RuntimeError('maintenance_candidate_rejected')
                ast.parse(value);originals[file['target']]=original;candidates[file['target']]=value
                atomic(stage/'candidate'/file['target'],value,0o644)
            for file in manifest['tests']:
                value=git_file(deployment['commit_sha'],file['source']);total+=len(value)
                if sha(value)!=file['sha256']:raise RuntimeError('maintenance_test_hash_changed')
                dest=stage/'tests'/file['path']
                atomic(dest,value,0o644)
                for parent in dest.parents:
                    if parent==stage:break
                    parent.chmod(0o755)
            if total>8*1024*1024:raise RuntimeError('maintenance_payload_too_large')
            invariants(candidates)
            # Prevent ordinary releases from changing the agreed paid ceilings.
            if 'deepseek_runtime.py' in candidates:
                tree=ast.parse(candidates['deepseek_runtime.py']);values={}
                for node in tree.body:
                    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                        if node.targets[0].id=='MAX_ESTIMATE':values['ceiling']=ast.literal_eval(node.value)
                        if node.targets[0].id=='LIMITS' and isinstance(node.value,ast.Call):values['limits']={k.arg:ast.literal_eval(k.value) for k in node.value.keywords}
                if values!=dict(ceiling=.2,limits=policy['paid_limits']):raise RuntimeError('maintenance_paid_limits_changed')
            progress('testing')
            test=subprocess.run(tests_command(stage,policy),capture_output=True,text=True,timeout=600)
            output=test.stdout+'\n'+test.stderr
            if test.returncode or not re.search(r'Ran [1-9][0-9]* tests?\b',output):
                raise RuntimeError('maintenance_offline_tests_failed:'+clean(output))
            progress('tested',test_summary=clean(output))
            if controls()!=before_controls:raise RuntimeError('maintenance_daily_controls_changed')
            if broker('manual_activity').get('state')!='idle':raise RuntimeError('maintenance_manual_work_started')
            backup=STORE/'backups'/ident;backup.mkdir(mode=0o700,parents=True,exist_ok=False)
            for name,value in originals.items():
                if value is not None:atomic(backup/name,value)
            progress('installing',backup=str(backup),transaction=[dict(name=name,existed=value is not None,
                before_sha256=sha(value) if value is not None else None,after_sha256=sha(candidates[name])) for name,value in originals.items()])
            try:
                for name,value in candidates.items():
                    current=(ROOT/name).read_bytes() if (ROOT/name).exists() else None
                    if current!=originals[name]:raise RuntimeError('maintenance_source_raced')
                    atomic(ROOT/name,value,0o644)
                call(['systemctl','restart','video-agent-prepare.service','video-agent-mcp.service'])
                health()
                if controls()!=before_controls:raise RuntimeError('maintenance_daily_controls_changed')
            except Exception:
                for name,value in originals.items():
                    if value is None:(ROOT/name).unlink(missing_ok=True)
                    else:atomic(ROOT/name,value,0o644)
                call(['systemctl','restart','video-agent-prepare.service','video-agent-mcp.service'])
                progress('rolled_back');raise
            progress('installed',installed_sha256={name:sha(value) for name,value in candidates.items()})
        finally:flag.unlink(missing_ok=True)

class Controller:
    def __init__(self,policy):self.policy=policy;self.lock=threading.Lock()
    def handle(self,request):
        op=request.get('operation')
        if op not in SCHEMAS or set(request)!=SCHEMAS[op]:raise RuntimeError('maintenance_request_schema')
        if op=='inventory':return inventory(self.policy)
        if op=='source':return source(request['module'],self.policy)
        if op=='status':
            if not re.fullmatch(r'[a-f0-9]{32}',request['deployment_id']):raise RuntimeError('maintenance_invalid_deployment_id')
            return read(STORE/('deployment-'+request['deployment_id']+'.json'))
        if (not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',request['release_id']) or
            not re.fullmatch(r'[a-f0-9]{40}',request['commit_sha']) or
            not re.fullmatch(r'[a-f0-9]{64}',request['manifest_sha256'])):raise RuntimeError('maintenance_invalid_release')
        ident=sha(json.dumps(request,sort_keys=True).encode())[:32]
        path=STORE/('deployment-'+ident+'.json')
        with self.lock:
            if path.exists():return read(path)
            value=dict(request,deployment_id=ident,state='queued',created_at=now())
            value.pop('operation');record(path,value)
        return value
    def worker(self):
        while True:
            for path in sorted(STORE.glob('deployment-*.json')):
                value=read(path)
                if value.get('state')!='queued':continue
                try:apply(value,self.policy)
                except Exception as exc:
                    current=read(path)
                    current.update(state='blocked' if current.get('state')!='rolled_back' else 'rolled_back',error=clean(exc),updated_at=now());record(path,current)
            time.sleep(2)

def main():
    if os.geteuid()!=0:raise SystemExit('Root maintenance service required')
    os.umask(0o077);policy=read(POLICY);STORE.mkdir(mode=0o700,parents=True,exist_ok=True)
    RUN.mkdir(mode=0o750,parents=True,exist_ok=True);os.chown(RUN,0,policy['client_gid'])
    RUN.chmod(0o750)
    # Never resume an ambiguous code transaction silently after a daemon crash.
    for path in STORE.glob('deployment-*.json'):
        value=read(path)
        if value.get('state') not in ('queued','installed','blocked','rolled_back'):
            try:
                restore_interrupted(value)
                value.update(state='rolled_back' if value.get('transaction') else 'blocked',error='maintenance_interrupted_transaction')
            except Exception as exc:value.update(state='blocked',error=clean(exc))
            record(path,value)
    (RUN/'deploying.json').unlink(missing_ok=True)
    controller=Controller(policy);threading.Thread(target=controller.worker,daemon=True).start()
    path=RUN/'control.sock';path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path));os.chmod(path,0o660);os.chown(path,0,policy['client_gid']);server.listen(8)
        while True:
            connection,_=server.accept()
            with connection:
                connection.settimeout(5)
                try:
                    _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                    if uid not in (0,policy['client_uid']):raise RuntimeError('maintenance_peer_not_allowed')
                    with connection.makefile('rb') as stream:raw=stream.readline(32769)
                    if len(raw)>32768 or not raw.endswith(b'\n'):raise RuntimeError('maintenance_request_too_large')
                    value=controller.handle(json.loads(raw))
                except Exception as exc:value=dict(state='blocked',error=clean(exc))
                connection.sendall(json.dumps(value).encode()+b'\n')

if __name__=='__main__':main()
