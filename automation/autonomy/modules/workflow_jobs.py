"""Checkpointed continuations of authorized jobs; no new batch or budget."""
import ast
import copy
from datetime import datetime,timezone
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time

import workflow_common as c

MAX_ATTEMPTS=3
PYTHON='/home/videoagent/Video-Optimizer-multiplatform/.venv/bin/python'

def retry_allowed(job,code):
    if code=='visual_or_editorial_review_failed' and job is not None and Path(job).parent.parent.name=='manual-catarsis':
        from workflow_presentation import available
        return available(Path(job).parent.name).get('state')=='eligible'
    # An already charged preparation correction must not spend another worker
    # continuation repeating its malformed result and hitting the same audit.
    if code in ('generation_dependency_deepseek_json_invalid','generation_dependency_deepseek_incomplete_handoff') and (job is not None and (Path(job)/'workflow-preparation-repair.json').is_file()):
        return False
    return code in c.RETRY_CODES

def selected(task):
    from catarsis_selection import task_channels
    return task_channels(task)

def enroll(kind,ident,state_root=None):
    state=(Path(state_root) if state_root is not None else c.STATE/kind)/ident
    task=c.read(state/'request.json')
    if task.get('publication_allowed') is not False:raise RuntimeError('workflow_generation_only_required')
    path=state/'workflow.json'
    if not path.exists():c.write(path,dict(version=c.VERSION,kind=kind,job_id=ident,enabled=True,
        request_sha256=c.digest(state/'request.json'),attempts=[],state='monitoring',next_at=0))
    return c.read(path)

def evidence(job):
    root=c.ledger(job);result={}
    if (root/'tools.json').is_file():
        for row in c.read(root/'tools.json').values():
            value=row.get('result',{});text=value.get('content')
            if row.get('kind')=='fetch' and value.get('state') not in ('unavailable','error') and isinstance(text,str) and len(text.strip())>=350:
                result[row['request']['url']]=dict(content=text,transport='saved_deepseek_fetch_response')
    from documentary_sources import available
    result.update({url:dict(content=row['content'],transport=row['transport']) for url,row in available(job).items()})
    return result

def saved_plan(job):
    target=job/'editorial-plan.json'
    if target.is_file():value=c.read(target)
    else:
        from shorts_handoff import parse
        candidates=[]
        for file in c.ledger(job).glob('invalid-handoff-*.json'):
            data=c.read(file)
            if str(data.get('output','')).startswith('editorial-plan'):
                try:value,repairs=parse(data.get('provider_content',''))
                except ValueError:continue
                candidates.append((file.stat().st_mtime_ns,value))
        if not candidates:raise RuntimeError('workflow_no_complete_saved_plan')
        value=max(candidates,key=lambda row:row[0])[1]
    if not isinstance(value,dict) or value.get('blocked'):raise RuntimeError('workflow_saved_plan_blocked')
    if value.get('action')=='rebuild':
        value=copy.deepcopy(value)
        native=value['plan']
        for name in ('metadata','thumbnail'):
            if name in value:
                if name in native and native[name]!=value[name]:raise RuntimeError('workflow_envelope_conflict')
                native[name]=value[name]
        value=native
    return copy.deepcopy(value)

def validate_saved_plan(job,value,kind,task,channel=None):
    value=copy.deepcopy(value)
    known=evidence(job);urls={row['url'] for row in value.get('research',[])}
    if len(urls)<2 or not urls<=set(known):raise RuntimeError('workflow_verified_factual_evidence_missing')
    for row in value['research']:
        row.update(evidence_transport=known[row['url']]['transport'],
            cached_content_sha256=hashlib.sha256(known[row['url']]['content'].encode()).hexdigest())
    if kind=='documentary':
        from documentary_common import validate_plan
        return validate_plan(value)
    identity=c.read(job/'job.json')
    if any(value.get(k)!=identity[k] for k in ('channel','date')):
        raise RuntimeError('workflow_saved_plan_identity_mismatch')
    if value.get('topic')!=identity['topic']:
        subject=identity['topic'].split(':',1)[0].strip().casefold()
        if not subject or not str(value.get('topic','')).casefold().startswith(subject):
            raise RuntimeError('workflow_saved_plan_identity_mismatch')
        value['topic']=identity['topic']
    from shorts_handoff import timing
    from shorts_media import normalize_plan
    from catarsis_style import validate
    from platform_rules import validate_base_plan
    from workflow_native import implementation
    from workflow_preparation import normalized_fields
    sys.path.insert(0,'/home/videoagent/video-automation');import editorial
    value,_=timing(value);value=normalize_plan(job,value);value=normalized_fields(job,value)
    implementation(editorial).validate_plan(value,channel,task['date'],c.read(job/'music-input.json'),c.read(job/'history-input.json'))
    validate(value);validate_base_plan(value)
    return value

def plan(job,kind,task,channel=None):
    return validate_saved_plan(job,saved_plan(job),kind,task,channel)

def frozen_sources():
    # Include the implementation modules read by the native source-pin check.
    import generation_worker
    sources={str(path):c.digest(path) for path in c.ROOT.glob('*.py')}
    for name in generation_worker.SOURCE_HASHES:
        path=generation_worker.AUTOMATION/name;sources[str(path)]=c.digest(path)
    sys.path.insert(0,str(generation_worker.AUTOMATION));import editorial
    from workflow_native import implementation
    native=Path(implementation(editorial).__file__);sources[str(native)]=c.digest(native)
    return sources

def inspect(kind,ident):
    if kind not in ('catarsis','documentary') or not c.valid_id(ident):raise RuntimeError('workflow_invalid_job')
    state=c.STATE/kind/ident;task=c.read(state/'request.json');status=c.read(state/'status.json')
    if task.get('publication_allowed') is not False or status.get('state') not in ('blocked','interrupted','partial'):
        raise RuntimeError('workflow_stopped_generation_required')
    if (state/'STOP').exists():raise RuntimeError('generation_cancelled')
    enrollment=enroll(kind,ident)
    if enrollment['request_sha256']!=c.digest(state/'request.json'):raise RuntimeError('workflow_request_changed')
    if len(enrollment['attempts'])>=MAX_ATTEMPTS:raise RuntimeError('workflow_recovery_attempt_limit')
    channels=selected(task) if kind=='catarsis' else (task['channel'],)
    jobs={}
    for channel in channels:
        job=c.RUNTIME/('manual-catarsis' if kind=='catarsis' else 'manual-documentary')/ident
        if kind=='catarsis':job/=channel
        if (job/'approval.json').exists():continue
        if any((job/n).exists() for n in ('publication.json','.transport.json')):raise RuntimeError('workflow_publication_exists')
        budget=c.read(c.ledger(job)/'budget.json')
        if budget.get('pending') is not None:raise RuntimeError('workflow_ambiguous_provider_request')
        # Reserve room for the mandatory independent text assessment.
        if budget['counts']['chat']>=10 or budget['counts']['invocations']>=4:raise RuntimeError('workflow_original_budget_exhausted')
        value=saved_plan(job)
        if (job/'video.mp4').exists():
            value=validate_saved_plan(job,value,kind,task,channel)
        else:
            # Inspect stays read-only. Missing public evidence/music is prepared
            # in the claimed worker, after the original inputs are archived.
            from workflow_preparation import identity
            identity(job,value,kind,task,channel)
        jobs[channel]=dict(job=str(job),files=c.tree(job),ledger=c.tree(c.ledger(job)),
            original_budget=budget,plan=value)
    if not jobs:raise RuntimeError('workflow_no_unapproved_channel')
    from generation_worker import preflight
    preflight()
    return task,status,enrollment,jobs

def start(broker,kind,ident,request_id=None):
    if kind=='catarsis' and request_id=='finalize-curie-style-review-scope-20261107-v1':
        from workflow_style_finalize import start as finish_scope
        return finish_scope(broker,ident,request_id)
    from generation_service import denied,safe_error
    from history_data import timestamp
    state=c.STATE/kind/ident
    if not c.valid_id(ident):return denied('workflow_invalid_job')
    status=c.read(state/'status.json')
    path=state/'workflow.json'
    previous=c.read(path) if path.is_file() else {}
    if request_id is None:request_id='auto-resume-'+str(len(previous.get('attempts',[]))+1)
    if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',request_id):return denied('workflow_invalid_resume_request_id')
    if request_id in previous.get('requests',{}):return broker.status(ident)
    if status.get('state') in ('ready','accepted','running'):
        observed=broker.status(ident)
        if observed.get('state')!='interrupted':return observed
        status.update(state='interrupted',error_code='workflow_worker_interrupted')
        c.write(state/'status.json',status)
    if broker.active or (getattr(broker,'publication',None) and broker.publication.active):return denied('another_manual_operation_is_running')
    if kind=='catarsis' and status.get('state')=='blocked':
        codes=[row.get('error_code') for row in status.get('channels',{}).values()]
        if 'visual_or_editorial_review_failed' in codes or previous.get('presentation',{}).get('state')=='blocked':
            from workflow_presentation import start as presentation_start
            return presentation_start(broker,ident,request_id)
    try:
        task,status,enrollment,jobs=inspect(kind,ident)
        from publication_service import controls
        attempt=len(enrollment['attempts'])+1
        token=f'{attempt:03d}'
        auth=dict(kind=kind,job_id=ident,attempt=attempt,request_sha256=enrollment['request_sha256'],
            sources=frozen_sources(),controls=controls(),jobs=jobs,publication_allowed=False)
        c.write(state/f'workflow-auth-{token}.json',auth)
        enrollment['attempts'].append(dict(number=attempt,created_at=timestamp(),state='queued'))
        enrollment.setdefault('requests',{})[request_id]=attempt
        enrollment.update(state='resuming',next_at=0);c.write(state/'workflow.json',enrollment)
        status.update(state='accepted',error_code=None,repair_id='autonomous-workflow-v49',updated_at=timestamp())
        c.write(state/'status.json',status)
        broker.active[ident]=True
        launch=getattr(broker,'launch',None) or broker.parent.launch
        try:launch(lambda:execute(broker,kind,ident,token))
        except Exception:
            broker.active.pop(ident,None)
            status.update(state='blocked',error_code='workflow_resume_launch_failed');c.write(state/'status.json',status)
            enrollment['state']='needs_attention';c.write(state/'workflow.json',enrollment)
            raise
        return broker.status(ident)
    except Exception as exc:return denied(safe_error(exc))

def execute(broker,kind,ident,token):
    from history_data import timestamp
    state=c.STATE/kind/ident
    try:
        command=[PYTHON,'-B',str(c.ROOT/'workflow_jobs.py'),'--kind',kind,'--job-id',ident,'--attempt',token]
        with subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True) as process:
            deadline=time.monotonic()+7200
            while process.poll() is None:
                if (state/'STOP').exists() or time.monotonic()>=deadline:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    raise RuntimeError('generation_cancelled' if (state/'STOP').exists() else 'workflow_recovery_time_limit')
                time.sleep(.25)
            if process.returncode:raise RuntimeError('workflow_recovery_worker_failed')
    except Exception as exc:
        from generation_service import safe_error
        value=c.read(state/'status.json');value.update(state='blocked',error_code=safe_error(exc),updated_at=timestamp());c.write(state/'status.json',value)
    finally:
        with broker.lock:broker.active.pop(ident,None)

def verify_ledger(job,old):
    new=c.read(c.ledger(job)/'budget.json')
    if (any(new['counts'][k]<v for k,v in old['counts'].items()) or
        new['usage'][:len(old['usage'])]!=old['usage'] or new.get('estimated_usd',1)>.2):
        raise RuntimeError('workflow_paid_ledger_regressed')

def semantic_history(job,guard):
    root=c.ledger(job)
    if (root/'history-check.json').is_file():
        value=c.read(root/'history-check.json')
        if value.get('history_review_complete') is True and value.get('duplicate') is False:return
        raise RuntimeError('workflow_history_check_not_approved')
    import deepseek_editor as editor
    from deepseek_runtime import Budget,Client
    dataset=editor.compact_history(c.read(job/'history-input.json'));request=c.read(job/'job.json')
    with Budget(job) as budget:
        if budget.data['counts']['chat']+len(editor.history_parts(dataset,request))+1>budget.limits['chat']:
            raise RuntimeError('workflow_history_and_review_budget_unavailable')
        budget.invoke_once();guard()
        with (job/'workflow-history-events.jsonl').open('a') as stream:
            os.chmod(stream.name,0o600)
            def event(value):stream.write(json.dumps(value)+'\n');stream.flush()
            editor.history_check(budget,Client(),event,dataset,request)

def source_delivery(job,original,guard):
    known=evidence(job);wanted={row['url'] for row in c.read(job/'editorial-plan.json')['research']}
    def fetch(url,*args,**kwargs):
        guard()
        if url in wanted:
            from curated_short_plans import SavedSource
            row=known[url];result=SavedSource(url,row['content']);result.evidence_transport=row['transport'];return result
        return original(url,*args,**kwargs)
    return fetch

def run_catarsis(job,task,channel,ident,guard):
    from workflow_native import implementation
    from generation_worker import manual_editorial,public_metadata
    from autonomous_generation import Supervisor
    sys.path.insert(0,'/home/videoagent/video-automation');import editorial as exported;import daily_core as core
    editorial=implementation(exported)
    semantic_history(job,guard)
    class SavedSupervisor(Supervisor):
        def decision(self,*args,**kwargs):raise RuntimeError('workflow_saved_plan_requires_attention')
    from workflow_native import enabled
    with enabled(editorial,job,channel),manual_editorial(editorial,job,ident,channel,task['date'],guard,recovery=SavedSupervisor(job,guard,attempt_namespace='workflow-v49')):
        old=editorial.external;editorial.external=source_delivery(job,old,guard)
        try:
            if (job/'video.mp4').exists():
                qa=c.read(job/'qa.json')
                if qa.get('technical_checks_passed') is not True or qa.get('sha256')!=c.digest(job/'video.mp4'):
                    raise RuntimeError('workflow_existing_video_qa_not_valid')
                from credit_repair import native_review_function
                project=c.read(job/'project.json')
                native_review_function(editorial)(job,project,c.read(job/'editorial-plan.json'),channel,task['date'],'production',project.get('music_provider')=='epidemic')
            else:editorial.build(job,channel,task['date'],task['topics'][channel],scope='production')
        finally:editorial.external=old
    guard();approval=core.approval(job,channel,task['date'])
    if approval.get('scope')!='production':raise RuntimeError('workflow_native_approval_required')
    files={}
    for kind,name in (('video','video.mp4'),('thumbnail','thumbnail.jpg')):
        info=(job/name).stat();files[kind]=dict(size=info.st_size,mtime_ns=info.st_mtime_ns,ctime_ns=info.st_ctime_ns,sha256=c.digest(job/name))
    return dict(state='ready',error_code=None,files=files,metadata=public_metadata(c.read(job/'metadata.json')),approval_sha256=c.digest(job/'approval.json'))

def run_documentary(job,task,ident,guard):
    import documentary_worker as worker
    from documentary_common import MODULES
    state=c.STATE/'documentary'/ident
    def progress(phase,done=None,total=None):
        guard();value=c.read(state/'status.json');value.update(state='running',phase=phase,progress=dict(completed=done,total=total));c.write(state/'status.json',value)
    config=worker.calibrate(job,worker.dependencies())
    sources={name:c.digest(c.ROOT/name) for name in MODULES}
    if (job/'video.mp4').exists():
        qa=c.read(job/'qa.json')
        if qa.get('passed') is not True or qa.get('video_sha256')!=c.digest(job/'video.mp4'):
            raise RuntimeError('workflow_existing_video_qa_not_valid')
        sheets=sorted(job.glob('review-sheet-*.jpg'))
        if not sheets:raise RuntimeError('workflow_saved_review_frames_missing')
        worker.quality(job,task,config,guard,progress,sheets);worker.approve(ident,task,job,state,sources)
    else:worker.finish(ident,task,job,state,config,c.read(job/'editorial-plan.json'),guard,progress,sources)

def perform(kind,ident,token):
    from history_data import timestamp
    from publication_service import controls
    from generation_service import safe_error
    from generation_worker import preflight
    state=c.STATE/kind/ident;auth=c.read(state/f'workflow-auth-{token}.json');auth_hash=c.digest(state/f'workflow-auth-{token}.json')
    if auth.get('kind')!=kind or auth.get('job_id')!=ident or auth.get('publication_allowed') is not False:
        raise RuntimeError('workflow_invalid_resume_authorization')
    task=c.read(state/'request.json');status=c.read(state/'status.json')
    def guard():
        if (state/'STOP').exists():raise RuntimeError('generation_cancelled')
        if (c.digest(state/f'workflow-auth-{token}.json')!=auth_hash or c.digest(state/'request.json')!=auth['request_sha256'] or
            controls()!=auth['controls'] or any(c.digest(Path(path))!=value for path,value in auth['sources'].items())):
            raise RuntimeError('workflow_frozen_inputs_changed')
        preflight()
    guard()
    with (state/f'workflow-claim-{token}').open('x') as stream:stream.write(timestamp());stream.flush();os.fsync(stream.fileno())
    archive=c.RUNTIME/'workflow-attempts'/kind/ident/token
    archive.mkdir(mode=0o700,parents=True,exist_ok=False)
    sys.path.insert(0,'/home/videoagent/video-automation');from helpers import daily
    with daily.locked():
        status.update(state='running',error_code=None,updated_at=timestamp());c.write(state/'status.json',status)
        for channel,item in auth['jobs'].items():
            job=Path(item['job']);guard()
            try:
                if c.tree(job)!=item['files'] or c.tree(c.ledger(job))!=item['ledger']:raise RuntimeError('workflow_original_evidence_changed')
                shutil.copytree(job,archive/channel);shutil.copytree(c.ledger(job),archive/(channel+'-ledger'))
                if c.tree(archive/channel)!=item['files'] or c.tree(archive/(channel+'-ledger'))!=item['ledger']:raise RuntimeError('workflow_archive_failed')
                for name in ('blocked.json','autonomy-feedback.json','editor-recovery-status.json'):(job/name).unlink(missing_ok=True)
                value=item['plan']
                if not (job/'video.mp4').exists():
                    if kind=='catarsis':
                        status['channels'][channel].update(state='preparing',phase='recovering_saved_inputs',error_code=None)
                        status['updated_at']=timestamp();c.write(state/'status.json',status)
                    from workflow_preparation import prepare
                    value=prepare(job,value,kind,task,channel,token,guard)
                c.write(job/'editorial-plan.json',value)
                if kind=='catarsis':status['channels'][channel]=run_catarsis(job,task,channel,ident,guard)
                else:run_documentary(job,task,ident,guard);status=c.read(state/'status.json')
                verify_ledger(job,item['original_budget'])
            except Exception as exc:
                code=safe_error(exc)
                c.write(job/'blocked.json',dict(reason=code,phase='workflow_resume',at=timestamp()))
                if kind=='catarsis':status['channels'][channel]=dict(state='blocked',error_code=code,diagnostic=code)
                else:status.update(state='blocked',phase='stopped',error_code=code)
            status['updated_at']=timestamp();c.write(state/'status.json',status)
        if kind=='catarsis':
            ready=sum(row.get('state')=='ready' for row in status['channels'].values())
            status['state']='ready' if ready==len(selected(task)) else 'partial' if ready else 'blocked'
        c.write(state/'status.json',status)
        enrollment=c.read(state/'workflow.json')
        codes=[status.get('error_code')]+[row.get('error_code') for row in status.get('channels',{}).values()]
        again=status['state']!='ready' and any(retry_allowed(Path(item['job']),status.get('channels',{}).get(channel,{}).get('error_code',status.get('error_code'))) for channel,item in auth['jobs'].items()) and len(enrollment['attempts'])<MAX_ATTEMPTS
        enrollment.update(state='complete' if status['state']=='ready' else 'monitoring' if again else 'needs_attention',next_at=time.time()+min(60,5*2**int(token)) if again else 0)
        enrollment['attempts'][int(token)-1]['state']=status['state'];c.write(state/'workflow.json',enrollment)

def poll(generation):
    if c.busy() or generation.active or (getattr(generation,'publication',None) and generation.publication.active):return dict(state='busy')
    doc=getattr(generation,'workflow_documentary',None)
    if doc is not None and doc.active:return dict(state='busy')
    for kind in ('catarsis','documentary'):
        for path in sorted((c.STATE/kind).glob('*/workflow.json')):
            enrollment=c.read(path)
            if not enrollment.get('enabled') or enrollment.get('state') in ('complete','needs_attention'):continue
            if enrollment.get('next_at',0)>time.time():continue
            ident=enrollment['job_id'];status=c.read(path.parent/'status.json')
            target=generation if kind=='catarsis' else doc
            if status.get('state') in ('accepted','running') and target is not None and target.status(ident).get('state')=='interrupted':
                status.update(state='interrupted',error_code='workflow_worker_interrupted')
                c.write(path.parent/'status.json',status)
            if status.get('state')=='ready':enrollment['state']='complete';c.write(path,enrollment);continue
            if status.get('state') not in ('blocked','interrupted','partial'):continue
            codes=[status.get('error_code')]+[r.get('error_code') for r in status.get('channels',{}).values()]
            active_jobs=[(c.RUNTIME/('manual-catarsis' if kind=='catarsis' else 'manual-documentary')/ident/channel,row.get('error_code')) for channel,row in status.get('channels',{}).items()] if kind=='catarsis' else [(c.RUNTIME/'manual-documentary'/ident,status.get('error_code'))]
            if not any(retry_allowed(job,code) for job,code in active_jobs):enrollment['state']='needs_attention';c.write(path,enrollment);continue
            if target is not None:
                value=start(target,kind,ident)
                if value.get('state')=='blocked':enrollment['state']='needs_attention';c.write(path,enrollment)
                return value
    return dict(state='idle')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--kind',choices=('catarsis','documentary'),required=True)
    parser.add_argument('--job-id',required=True);parser.add_argument('--attempt',required=True);args=parser.parse_args()
    if not c.valid_id(args.job_id) or not args.attempt.isdigit() or len(args.attempt)!=3:raise SystemExit(2)
    os.umask(0o077);perform(args.kind,args.job_id,args.attempt)

