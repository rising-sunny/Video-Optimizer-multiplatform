#!/usr/bin/env python3
"""One-time installation of general autonomous generation and owner maintenance."""
import ast
from datetime import datetime,timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import tempfile
import time

import install_helpers as base
import source_patch

BUNDLE=Path(__file__).resolve().parent
ROOT=Path('/opt/video-agent-mcp')
LIB=Path('/usr/local/lib/video-workflow-maintenance')
RECEIPT=ROOT/'workflow-v49-installed.json'
TARGETS=('generation_service.py','generation_worker.py','generation_tools.py','documentary_service.py','deepseek_editor.py','shorts_handoff.py')
CURIE='cf2a22d4f40f453fba2b3af137b716d1'

def rpc(operation,**values):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(60);connection.connect('/run/video-agent-prepare/control.sock')
        connection.sendall(json.dumps(dict(operation=operation,**values)).encode()+b'\n')
        with connection.makefile('rb') as stream:raw=stream.readline(1048577)
    if len(raw)>1048576 or not raw.endswith(b'\n'):raise RuntimeError('workflow_invalid_broker_response')
    return json.loads(raw)

MAINTENANCE_UNIT='''[Unit]
Description=Verified video-generation maintenance controller
After=network-online.target video-agent-prepare.service
Wants=network-online.target
[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/bin/python3 -B -u /usr/local/lib/video-workflow-maintenance/maintenance_daemon.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
UMask=0077
[Install]
WantedBy=multi-user.target
'''

WATCH_UNIT='''[Unit]
Description=Persistent recovery of requested video generations
After=video-agent-prepare.service
Requires=video-agent-prepare.service
PartOf=video-agent-prepare.service
[Service]
Type=simple
User=videoagent
Group=videoagent
ExecStart=/home/videoagent/Video-Optimizer-multiplatform/.venv/bin/python -B -u /opt/video-agent-mcp/workflow_daemon.py
Restart=always
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
RestrictAddressFamilies=AF_UNIX
UMask=0077
[Install]
WantedBy=multi-user.target
'''

def mcp_python():
    value=base.command(['systemctl','show','video-agent-mcp.service','-p','ExecStart','-p','ActiveState'])
    props=dict(line.split('=',1) for line in value.splitlines() if '=' in line)
    match=re.search(r'\bpath=([^ ;}]+)',props.get('ExecStart',''))
    if props.get('ActiveState')!='active' or not match:raise RuntimeError('workflow_mcp_service_not_ready')
    path=Path(match[1])
    if not path.is_file() or not path.name.startswith('python'):raise RuntimeError('workflow_mcp_python_not_found')
    return str(path)

def stage_test(candidates,policy):
    spec=importlib.util.spec_from_file_location('workflow_admin_test_helper',BUNDLE/'maintenance_daemon.py')
    admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)
    stage=Path(tempfile.mkdtemp(prefix='video-workflow-bootstrap-',dir='/var/tmp'));stage.chmod(0o755)
    for name in ('candidate','tests','work'):admin.public_directory(stage/name)
    os.chown(stage/'work',policy['client_uid'],policy['client_gid'])
    for name,data in candidates.items():base.atomic(stage/'candidate'/name,data)
    for file in (BUNDLE/'tests').rglob('*'):
        if not file.is_file() or '__pycache__' in file.parts:continue
        relative=file.relative_to(BUNDLE/'tests');base.atomic(stage/'tests'/relative,file.read_bytes())
    for name in TARGETS:base.atomic(stage/'tests'/'baseline'/name,(BUNDLE/'baseline'/name).read_bytes())
    base.atomic(stage/'tests'/'source_patch.py',(BUNDLE/'source_patch.py').read_bytes())
    base.atomic(stage/'candidate'/'maintenance_daemon.py',(BUNDLE/'maintenance_daemon.py').read_bytes())
    for interpreter in dict.fromkeys((base.PYTHON,mcp_python())):
        config=dict(policy,python=interpreter)
        result=subprocess.run(admin.tests_command(stage,config),capture_output=True,text=True,timeout=600)
        summary=result.stdout+'\n'+result.stderr
        if result.returncode or not re.search(r'Ran [1-9][0-9]* tests?\b',summary):
            print(admin.clean(summary),flush=True);raise RuntimeError('workflow_offline_tests_failed')
        print(json.dumps(dict(test_environment='render' if interpreter==base.PYTHON else 'mcp',
            summary=admin.clean(summary),ai_requests=0)),flush=True)

def build_policy():
    who=pwd.getpwnam('videoagent')
    source=(ROOT/'generation_worker.py').read_text()
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.Assign) and any(
        isinstance(t,ast.Name) and t.id=='SOURCE_HASHES' for t in n.targets))
    native=list(ast.literal_eval(node.value))
    excluded={'server.py','app.py','main.py','prepare.py','prepare_service.py','auth.py','config.py'}
    modules=[p.name for p in ROOT.glob('*.py') if p.name not in excluded and not p.name.startswith(('auth_','oauth_','setup_'))]
    return dict(version=1,client_uid=who.pw_uid,client_gid=who.pw_gid,python=base.PYTHON,
        modules=sorted(modules),native_modules=native,
        paid_limits=dict(chat=10,search=4,fetch=14,invocations=4,input_tokens=350000,output_tokens=24000))

def main():
    if os.geteuid()!=0:raise RuntimeError('workflow_bootstrap_root_required')
    os.umask(0o077)
    manifest=json.loads((BUNDLE/'payload-sha256.json').read_text())
    for name,expected in manifest.items():
        if base.digest(base.safe(BUNDLE/name).read_bytes())!=expected:raise RuntimeError('workflow_bootstrap_hash_changed')
    with base.safe(Path('/run/lock/video-generation-install.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=base.controls();base.idle()
        if "generation_start_single" not in (ROOT/'generation_service.py').read_text():raise RuntimeError('workflow_v48_single_prerequisite_missing')
        print(base.command(['runuser','-u','videoagent','--',base.PYTHON,'-B','-c',
            "import sys;sys.path.insert(0,'/opt/video-agent-mcp');from generation_worker import preflight;preflight();print('Native source and readiness checks passed')"]),flush=True)
        originals={name:base.safe(ROOT/name).read_bytes() for name in TARGETS}
        candidates={name:getattr(source_patch,Path(name).stem)(data.decode()).encode() for name,data in originals.items()}
        for file in (BUNDLE/'modules').glob('*.py'):
            name=file.name;path=base.safe(ROOT/name)
            if path.exists():
                old=json.loads(RECEIPT.read_text()) if RECEIPT.exists() else {}
                if base.digest(path.read_bytes())!=old.get('after',{}).get(name):raise RuntimeError('workflow_existing_module_changed')
            originals[name]=path.read_bytes() if path.exists() else None;candidates[name]=file.read_bytes()
        for data in candidates.values():ast.parse(data)
        policy=build_policy();stage_test(candidates,policy);base.idle()
        backup=Path('/var/backups/video-agent-mcp')/('workflow-v49-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        backup.mkdir(mode=0o700)
        locations={ROOT/name:data for name,data in originals.items()}
        locations.update({
            LIB/'maintenance_daemon.py':(LIB/'maintenance_daemon.py').read_bytes() if (LIB/'maintenance_daemon.py').exists() else None,
            Path('/etc/video-workflow-maintenance/policy.json'):Path('/etc/video-workflow-maintenance/policy.json').read_bytes() if Path('/etc/video-workflow-maintenance/policy.json').exists() else None,
            Path('/etc/systemd/system/video-workflow-maintenance.service'):Path('/etc/systemd/system/video-workflow-maintenance.service').read_bytes() if Path('/etc/systemd/system/video-workflow-maintenance.service').exists() else None,
            Path('/etc/systemd/system/video-workflow-recovery.service'):Path('/etc/systemd/system/video-workflow-recovery.service').read_bytes() if Path('/etc/systemd/system/video-workflow-recovery.service').exists() else None,
        })
        for path,data in locations.items():
            if data is not None:base.atomic(backup/str(path).lstrip('/'),data,0o600)
        try:
            for name,data in candidates.items():base.atomic(ROOT/name,data)
            base.atomic(LIB/'maintenance_daemon.py',(BUNDLE/'maintenance_daemon.py').read_bytes())
            base.atomic(Path('/etc/video-workflow-maintenance/policy.json'),json.dumps(policy,indent=2).encode(),0o600)
            base.atomic(Path('/etc/systemd/system/video-workflow-maintenance.service'),MAINTENANCE_UNIT.encode())
            base.atomic(Path('/etc/systemd/system/video-workflow-recovery.service'),WATCH_UNIT.encode())
            base.command(['systemctl','daemon-reload'])
            base.command(['systemctl','restart','video-agent-prepare.service','video-agent-mcp.service'])
            for _ in range(120):
                try:
                    result=rpc('generation_workflow_capabilities')
                    if result.get('version')=='autonomous-workflow-v49':break
                except (OSError,ValueError):pass
                time.sleep(.25)
            else:raise RuntimeError('workflow_capabilities_probe_failed')
            spec=importlib.util.spec_from_file_location('workflow_live_health',BUNDLE/'maintenance_daemon.py')
            admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)
            admin.health()
            base.command(['systemctl','enable','--now','video-workflow-maintenance.service'])
            for _ in range(80):
                try:
                    result=rpc('generation_workflow_admin',action='inventory',values={})
                    if result.get('maintenance_version')==1:break
                except (OSError,ValueError):pass
                time.sleep(.25)
            else:raise RuntimeError('workflow_maintenance_probe_failed')
            if base.controls()!=before:raise RuntimeError('workflow_daily_controls_changed')
        except Exception:
            subprocess.run(['systemctl','disable','--now','video-workflow-recovery.service','video-workflow-maintenance.service'],capture_output=True)
            for path,data in locations.items():
                if data is None:base.safe(path).unlink(missing_ok=True)
                else:base.atomic(path,data,0o600 if path.name=='policy.json' else 0o644)
            base.command(['systemctl','daemon-reload']);base.command(['systemctl','restart','video-agent-prepare.service','video-agent-mcp.service'])
            raise
        receipt=dict(release='autonomous-workflow-v49',state='installed',backup=str(backup),
            after={name:base.digest(data) for name,data in candidates.items()},maintenance=True,
            short_and_long=True,installation_ai_requests=0,paid_limits_increased=False,publication='not_requested')
        base.atomic(RECEIPT,json.dumps(receipt,indent=2).encode())
        who=pwd.getpwnam('videoagent');owner=(who.pw_uid,who.pw_gid)
        folder=base.REPO/'automation/autonomy'
        for source in BUNDLE.rglob('*'):
            if source.is_file() and '__pycache__' not in source.parts:
                base.atomic(folder/source.relative_to(BUNDLE),source.read_bytes(),owner=owner)
        for name,data in candidates.items():base.atomic(folder/'installed'/name,data,owner=owner)
        base.atomic(folder/'installation-receipt.json',json.dumps(receipt,indent=2).encode(),owner=owner)
        agents=base.REPO/'AGENTS.md';content=agents.read_text() if agents.exists() else '# Video Automation\n'
        if '## Autonomous generation (v49)' not in content:
            content=content.rstrip()+'\n\n## Autonomous generation (v49)\n\nRead `automation/autonomy/README.md` for short and long generation, diagnostics, same-job recovery and verified maintenance releases. Use the connected tools rather than asking the user to relay shell commands. Never reset budgets/claims or infer publication from ready generation.\n'
            base.atomic(agents,content.encode(),owner=owner)
        print(json.dumps(receipt),flush=True)
    # The independent service outlives this installer and the chat. Only explicitly
    # enrolled requests are observed; existing unrelated old jobs stay untouched.
    base.command(['systemctl','enable','--now','video-workflow-recovery.service'])
    current=rpc('generation_status',batch_id=CURIE)
    if current.get('request_id')=='manual-facts-curie-ww1-20261106-v1' and current.get('state')=='blocked':
        result=rpc('generation_workflow_resume',kind='catarsis',job_id=CURIE)
        print(json.dumps(dict(curie_resume=result)),flush=True)
    print(json.dumps(dict(state='ready',maintenance='enabled',automatic_recovery='short_and_long',
        connector_refresh='refresh_tools_if_not_yet_visible',publication='not_requested')),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        value=str(exc);code=value if value.replace('_','').isalnum() else type(exc).__name__
        print(json.dumps(dict(state='blocked',error_code=code,publication_allowed=False)),flush=True)
        raise SystemExit(2)
