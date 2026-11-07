#!/usr/bin/env python3
"""Install narrow saved-JSON support and request the same single-batch continuation."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import time

import install as base
import json_recovery_patch as patch

ROOT=base.ROOT
BUNDLE=Path(__file__).resolve().parent
TARGETS=('shorts_handoff.py','shorts_handoff_resume.py','documentary_service.py')
HELPER='shorts_single_json.py'
RECEIPT=ROOT/'single-json-v48-2-installed.json'


def stage(candidates):
    folder=Path(tempfile.mkdtemp(prefix='curie-json-check-'))
    folder.chmod(0o755)
    for source in BUNDLE.rglob('*'):
        rel=source.relative_to(BUNDLE)
        if '__pycache__' in rel.parts:continue
        if source.is_dir():
            (folder/rel).mkdir(parents=True,exist_ok=True)
            (folder/rel).chmod(0o755)
        elif source.is_file():base.atomic(folder/rel,source.read_bytes())
    for name,data in candidates.items():base.atomic(folder/name,data)
    env='PYTHONPATH='+str(folder)+':'+str(ROOT)
    # Plan inspection uses the actual saved response and actual native validator;
    # the staged parser is loaded first. It is verified read-only by the helper.
    output=base.command(['runuser','-u','videoagent','--','env',env,'PYTHONDONTWRITEBYTECODE=1',
        base.PYTHON,'-B',str(folder/HELPER),'--batch-id',patch.BATCH,'--inspect'],cwd=folder)
    print(output,flush=True)
    base.command(['runuser','-u','videoagent','--','env',env,'PYTHONDONTWRITEBYTECODE=1',
        base.PYTHON,'-B','-m','unittest','discover','-s',str(folder),'-p','test_single_json.py','-q'],cwd=folder)
    print(json.dumps(dict(saved_json_tests='passed',ai_requests=0)),flush=True)


def main():
    if os.geteuid()!=0:raise RuntimeError('single_json_root_required')
    os.umask(0o077)
    for name,expected in json.loads((BUNDLE/'payload-sha256.json').read_text()).items():
        if base.digest(base.safe(BUNDLE/name).read_bytes())!=expected:
            raise RuntimeError('single_json_delivery_changed')
    with base.safe(Path('/run/lock/video-generation-install.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=base.controls();base.idle()
        originals={name:base.safe(ROOT/name).read_bytes() for name in TARGETS}
        installed=json.loads(base.safe(RECEIPT).read_text()) if RECEIPT.exists() else {}
        candidates={name:(data if base.digest(data)==installed.get('after',{}).get(name) else
            getattr(patch,Path(name).stem)(data.decode()).encode()) for name,data in originals.items()}
        extra=(BUNDLE/HELPER).read_bytes()
        if (ROOT/HELPER).exists() and base.safe(ROOT/HELPER).read_bytes()!=extra:
            raise RuntimeError('single_json_existing_helper_changed')
        stage(candidates)
        base.idle()
        if any((ROOT/n).read_bytes()!=data for n,data in originals.items()):
            raise RuntimeError('single_json_sources_changed_during_tests')
        changed=any(candidates[n]!=originals[n] for n in TARGETS) or not (ROOT/HELPER).exists()
        backup=None
        if changed:
            backup=Path('/var/backups/video-agent-mcp')/('single-json-v48-2-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
            backup.mkdir(mode=0o700)
            for name,data in originals.items():base.atomic(backup/name,data,0o600)
            existed=(ROOT/HELPER).exists()
            try:
                base.atomic(ROOT/HELPER,extra)
                for name,data in candidates.items():base.atomic(ROOT/name,data)
                base.command(['systemctl','restart','video-agent-prepare.service'])
                for _ in range(80):
                    try:
                        if base.rpc('manual_activity').get('state')=='idle':break
                    except (OSError,ValueError):pass
                    time.sleep(.25)
                else:raise RuntimeError('single_json_broker_not_ready')
                if base.controls()!=before:raise RuntimeError('single_json_daily_controls_changed')
            except Exception:
                for name,data in originals.items():base.atomic(ROOT/name,data)
                if not existed:(ROOT/HELPER).unlink(missing_ok=True)
                base.command(['systemctl','restart','video-agent-prepare.service'])
                raise
        receipt=dict(release='single-saved-json-v48.2',state='installed' if changed else 'already_installed',
            after={n:base.digest(data) for n,data in candidates.items()},helper_sha256=base.digest(extra),
            backup=str(backup) if backup else installed.get('backup'),install_ai_requests=0,
            planning_ai_requests=0,paid_limits_increased=False,publication='not_requested')
        base.atomic(RECEIPT,json.dumps(receipt,indent=2).encode())
        who=pwd.getpwnam('videoagent');owner=(who.pw_uid,who.pw_gid)
        folder=base.REPO/'automation/catarsis-single'
        for name in (HELPER,'json_recovery_patch.py','test_single_json.py','SAVED-JSON-v48.2.md',
                     'install_recovery.py','install.py','patch_sources.py'):
            base.atomic(folder/name,(BUNDLE/name).read_bytes(),owner=owner)
        for name in TARGETS:
            base.atomic(folder/'baseline'/name,(BUNDLE/'baseline'/name).read_bytes(),owner=owner)
        readme=base.safe(folder/'README.md')
        content=readme.read_text() if readme.is_file() else '# Single-channel Catarsis\n'
        if 'SAVED-JSON-v48.2.md' not in content:
            content=content.rstrip()+'\n\nFor the observed Curie JSON failure, see [saved JSON recovery](SAVED-JSON-v48.2.md). Reuse the exact batch and response; never reset its paid ledger or claims.\n'
            base.atomic(readme,content.encode(),owner=owner)
        for name,data in candidates.items():base.atomic(folder/'native'/name,data,owner=owner)
        base.atomic(folder/'single-json-v48-2-installed.json',json.dumps(receipt,indent=2).encode(),owner=owner)
        print(json.dumps(receipt),flush=True)
        print(base.command(['runuser','-u','videoagent','--',base.PYTHON,'-B','-c',
            "import sys;sys.path.insert(0,'/opt/video-agent-mcp');from single_catarsis_request import check_account;check_account();print('Codex account available')"]),flush=True)
        result=base.rpc('manual_activity')
        if result.get('state')!='idle':raise RuntimeError('single_json_another_manual_operation_started')
        import socket
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(60);connection.connect('/run/video-agent-prepare/control.sock')
            connection.sendall(json.dumps(dict(operation='generation_resume_saved_handoffs',batch_id=patch.BATCH)).encode()+b'\n')
            with connection.makefile('rb') as stream:result=json.loads(stream.readline(1048577))
        print(json.dumps(result),flush=True)
        if result.get('state') not in ('accepted','running','ready'):raise RuntimeError('single_json_resume_not_accepted')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        value=str(exc)
        code=value if value.replace('_','').isalnum() else type(exc).__name__
        print(json.dumps(dict(state='blocked',error_code=code,publication_allowed=False)),flush=True)
        raise SystemExit(2)
