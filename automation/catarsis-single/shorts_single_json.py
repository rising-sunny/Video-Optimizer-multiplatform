"""One exact saved Curie plan; original ledger, native checks and one durable claim."""
import argparse
import ast
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path('/opt/video-agent-mcp')
STATE = Path('/var/lib/video-agent-prepare/catarsis')
JOBS = Path('/home/videoagent/video-automation/runtime/manual-catarsis')
RUNTIME = JOBS.parent
AUTOMATION = Path('/home/videoagent/video-automation')
BATCH = 'cf2a22d4f40f453fba2b3af137b716d1'
CHANNEL = 'stunning-facts-of-history'
REQUEST = 'manual-facts-curie-ww1-20261106-v1'
REPAIR = 'single-saved-json-v48.2'
AUTH = 'single-saved-json-v48-2.json'
CLAIM = 'single-saved-json-v48-2.claimed'
INVALID = 'invalid-handoff-8e8fc00e5c994356ffc39d250dc3c805b76c09bb217ce80b2db21f59c9fa5277.json'
INVALID_SHA = 'bb7f971db3c5cdfed7cc740e6e443c219d2685cffc3e9e91e4f06efa0268ed6e'
EXPECTED = dict(chat=5,search=3,fetch=3,invocations=1,input_tokens=56192,output_tokens=3211)
ERROR = 'generation_dependency_deepseek_json_invalid'


def safe(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError('single_json_symlink_rejected')
    return path


def sha(path):
    return hashlib.sha256(safe(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(safe(path).read_text())


def tree(folder):
    return {str(p.relative_to(folder)):sha(p) for p in sorted(safe(folder).rglob('*')) if safe(p).is_file()}


def ledger():
    return RUNTIME / 'deepseek-ledger/catarsis' / BATCH / CHANNEL


def unwrap(value, job):
    if not isinstance(value,dict) or value.get('action') != 'rebuild' or not isinstance(value.get('plan'),dict):
        raise RuntimeError('single_json_saved_rebuild_required')
    plan = copy.deepcopy(value['plan'])
    for name in ('metadata','thumbnail'):
        if name in value:
            if name in plan and plan[name] != value[name]:
                raise RuntimeError('single_json_conflicting_envelope_fields')
            plan[name] = copy.deepcopy(value[name])
    # These fields identify the existing request, not historical assertions.
    if plan.get('channel') != CHANNEL:
        raise RuntimeError('single_json_channel_changed')
    changes = []
    if plan.get('topic') != job['topic']:
        if 'curie' not in str(plan.get('topic','')).casefold():
            raise RuntimeError('single_json_topic_changed')
        changes.append(dict(kind='restore_original_full_topic_binding'))
        plan['topic'] = job['topic']
    if plan.get('date') != job['date']:
        raise RuntimeError('single_json_date_changed')
    return plan, changes


def native_editorial():
    """Hook the implementation module even when editorial is a re-export shim."""
    sys.path.insert(0,str(AUTOMATION))
    import editorial
    implementation=sys.modules.get(editorial.build.__module__)
    if implementation is None or implementation.__dict__ is not editorial.build.__globals__:
        raise RuntimeError('single_json_native_module_binding_failed')
    path=safe(Path(implementation.__file__))
    if path.suffix!='.py' or not path.is_file():
        raise RuntimeError('single_json_native_module_source_missing')
    return implementation


def validate_saved(job,plan):
    from shorts_handoff import timing
    from shorts_media import normalize_plan
    from shorts_handoff_resume import factual_sources
    plan,times=timing(plan)
    task=read(job/'job.json')
    if any(plan.get(k)!=task[k] for k in ('channel','date','topic')):
        raise RuntimeError('single_json_plan_identity_changed')
    plan=normalize_plan(job,plan)
    evidence=factual_sources(job)
    urls={row['url'] for row in plan.get('research',[])}
    if len(urls)<2 or not urls<=set(evidence):
        raise RuntimeError('single_json_saved_factual_support_missing')
    for row in plan['research']:
        actual=evidence[row['url']]
        row.update(evidence_transport=actual['transport'],
            cached_content_sha256=hashlib.sha256(actual['content'].encode()).hexdigest(),
            cache_original_retrieved_at=actual.get('retrieved_at','not_recorded'),
            evidence_scope=actual.get('scope','saved_provider_text'))
    native_editorial().validate_plan(plan,CHANNEL,task['date'],read(job/'music-input.json'),read(job/'history-input.json'))
    from catarsis_style import validate
    from platform_rules import validate_base_plan
    validate(plan);validate_base_plan(plan)
    return plan,times


def prepared(job):
    source = ledger() / INVALID
    if sha(source) != INVALID_SHA:
        raise RuntimeError('single_json_observed_response_changed')
    data = read(source)
    if data.get('output') != 'editorial-plan-autonomy-1.json':
        raise RuntimeError('single_json_observed_output_changed')
    from shorts_handoff import parse
    envelope, changes = parse(data['provider_content'])
    if changes != [dict(kind='removed_single_redundant_object_close',count=1)]:
        raise RuntimeError('single_json_requires_exact_observed_syntax_repair')
    plan, bindings = unwrap(envelope, read(job/'job.json'))
    plan, timing = validate_saved(job,plan)
    return plan,dict(source_sha256=INVALID_SHA,syntax_repairs=changes,binding_repairs=bindings,
        timing_repair=timing,planning_ai_requests=0,research_ai_requests=0)


def inspect(batch):
    if batch != BATCH:
        raise RuntimeError('single_json_batch_not_authorized')
    from generation_worker import preflight
    preflight()
    root,job = STATE/BATCH,JOBS/BATCH/CHANNEL
    task,status = read(root/'request.json'),read(root/'status.json')
    if (task.get('request_id')!=REQUEST or task.get('batch_id')!=BATCH or
        task.get('operation')!='generate_single_only' or task.get('requested_channels')!=[CHANNEL] or
        set(task.get('topics',{}))!={CHANNEL} or task.get('date')!='2026-11-06' or
        task.get('publication_allowed') is not False):
        raise RuntimeError('single_json_request_changed')
    row = status.get('channels',{}).get(CHANNEL,{})
    if status.get('state')!='blocked' or row.get('state')!='blocked' or row.get('error_code')!=ERROR:
        raise RuntimeError('single_json_observed_block_changed')
    if (root/'STOP').exists():
        raise RuntimeError('generation_cancelled')
    if (root/CLAIM).exists():
        raise RuntimeError('single_json_recovery_already_claimed')
    if (JOBS/BATCH/'stunning-revelations').exists():
        raise RuntimeError('single_json_unselected_job_exists')
    if (STATE.parent/'catarsis-publication'/BATCH).exists() or any((job/n).exists() for n in
        ('video.mp4','rendering.json','approval.json','publication.json','.transport.json')):
        raise RuntimeError('single_json_existing_artifact_requires_reconciliation')
    native_job=read(job/'job.json')
    if native_job!=dict(date=task['date'],channel=CHANNEL,topic=task['topics'][CHANNEL],scope='production',
        manual_batch=BATCH,generation_only=True,publication_allowed=False):
        raise RuntimeError('single_json_job_changed')
    if read(job/'style-profile.json').get('version')!='introspective-catarsis-v7':
        raise RuntimeError('single_json_style_changed')
    budget=read(ledger()/'budget.json')
    if budget.get('counts')!=EXPECTED or budget.get('pending') is not None or budget.get('estimated_usd',1)>=.2:
        raise RuntimeError('single_json_observed_budget_changed')
    snapshots=(tree(job),tree(ledger()))
    plan,receipt=prepared(job)
    if snapshots!=(tree(job),tree(ledger())):
        raise RuntimeError('single_json_preflight_modified_saved_evidence')
    return task,status,plan,receipt


def modules():
    # Freeze every module frozen by the normal worker, plus this recovery.
    source = safe(ROOT/'generation_worker.py').read_text()
    worker = next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='perform')
    assignment = next(n for n in worker.body if isinstance(n,ast.Assign) and any(
        isinstance(t,ast.Name) and t.id=='module_names' for t in n.targets))
    names=set(ast.literal_eval(assignment.value))|{'shorts_single_json.py','documentary_service.py'}
    return {name:sha(ROOT/name) for name in names}


def authorize(batch):
    task,status,plan,receipt=inspect(batch)
    from history_data import atomic
    from publication_service import controls
    from generation_worker import AUTOMATION,SOURCE_HASHES
    now=datetime.now(timezone.utc)
    job=JOBS/BATCH/CHANNEL
    auth=dict(batch_id=BATCH,request_id=REQUEST,repair_id=REPAIR,operation='resume_single_saved_plan',
        request_sha256=sha(STATE/BATCH/'request.json'),controls=controls(),
        code_sha256=modules(),native_pins={n:sha(AUTOMATION/n) for n in SOURCE_HASHES},
        editorial_source=str(native_editorial().__file__),editorial_sha256=sha(Path(native_editorial().__file__)),
        created_at=now.isoformat(),expires_at=(now+timedelta(hours=12)).isoformat(),
        original_files=tree(job),original_ledger=tree(ledger()),original_counts=EXPECTED,
        planning_ai_requests=0,research_ai_requests=0,paid_limits_increased=False,publication_allowed=False)
    atomic(STATE/BATCH/AUTH,auth)
    return auth


def start(broker,batch):
    from generation_service import denied,safe_error
    from history_data import atomic,timestamp
    if batch!=BATCH:
        return denied('single_json_batch_not_authorized')
    if (broker.state/BATCH/AUTH).exists():
        return broker.status(BATCH)
    if broker.active or (getattr(broker,'publication',None) and broker.publication.active):
        return denied('another_manual_operation_is_running')
    try:
        authorize(batch)
    except Exception as exc:
        return denied(safe_error(exc))
    value=read(broker.state/BATCH/'status.json')
    value.update(state='accepted',error_code=None,repair_id=REPAIR,updated_at=timestamp())
    value['channels'][CHANNEL]=dict(state='preparing',error_code=None)
    atomic(broker.state/BATCH/'status.json',value)
    broker.active[BATCH]=True
    try:
        broker.launch(lambda:broker.work(BATCH,handoff=True))
    except Exception:
        broker.active.pop(BATCH,None)
        value.update(state='blocked',error_code='single_json_launch_failed')
        atomic(broker.state/BATCH/'status.json',value)
    return broker.status(BATCH)


def history_review(job,guard):
    import deepseek_editor as editor
    import deepseek_runtime as rt
    path=ledger()/'history-check.json'
    if path.is_file():
        receipt=read(path)
        if receipt.get('history_review_complete') is not True or receipt.get('duplicate') is not False:
            raise RuntimeError('single_json_history_not_approved')
        return
    guard()
    data=editor.compact_history(read(job/'history-input.json'))
    request=read(job/'job.json')
    parts=editor.history_parts(data,request)
    with rt.Budget(job) as budget:
        # Leave a chat request for the mandatory factual/rights review.
        if budget.data['counts']['chat']+len(parts)+1>budget.limits['chat']:
            raise RuntimeError('single_json_history_and_review_budget_unavailable')
        budget.invoke_once()
        events=job/'saved-history-v48-2-events.jsonl'
        with events.open('x') as stream:
            os.chmod(events,0o600)
            def event(value):
                stream.write(json.dumps(value)+'\n');stream.flush()
            editor.history_check(budget,rt.Client(),event,data,request)
    guard()


def finish_budget(old):
    current=read(ledger()/'budget.json')
    if (any(current['counts'][key]<value for key,value in old['counts'].items()) or
        current['usage'][:len(old['usage'])]!=old['usage'] or
        any(current['counts'][key]!=old['counts'][key] for key in ('search','fetch')) or
        current.get('estimated_usd',1)>.2):
        raise RuntimeError('single_json_paid_ledger_changed_out_of_scope')


def perform(batch):
    if batch!=BATCH:
        raise RuntimeError('single_json_batch_not_authorized')
    from history_data import atomic,timestamp
    from publication_service import controls
    from generation_service import safe_error
    from generation_worker import preflight,manual_editorial,public_metadata,diagnostic,AUTOMATION
    root,job=STATE/BATCH,JOBS/BATCH/CHANNEL
    auth=read(root/AUTH);auth_hash=sha(root/AUTH)
    if auth.get('repair_id')!=REPAIR or auth.get('paid_limits_increased') is not False:
        raise RuntimeError('single_json_authorization_changed')
    def guard():
        if (root/'STOP').exists():raise RuntimeError('generation_cancelled')
        if (sha(root/AUTH)!=auth_hash or sha(root/'request.json')!=auth['request_sha256'] or
            controls()!=auth['controls'] or any(sha(ROOT/n)!=v for n,v in auth['code_sha256'].items()) or
            any(sha(AUTOMATION/n)!=v for n,v in auth['native_pins'].items()) or
            sha(Path(auth['editorial_source']))!=auth['editorial_sha256']):
            raise RuntimeError('single_json_inputs_changed')
        if datetime.now(timezone.utc)>=datetime.fromisoformat(auth['expires_at']):
            raise RuntimeError('single_json_authorization_expired')
        if (STATE.parent/'catarsis-publication'/BATCH).exists():raise RuntimeError('single_json_publication_exists')
        for name in ('job.json','style-profile.json','history-input.json','music-input.json','music-license-evidence.json','shorts-media-v34.json'):
            if sha(job/name)!=auth['original_files'][name]:raise RuntimeError('single_json_evidence_changed')
        if sha(ledger()/INVALID)!=INVALID_SHA:raise RuntimeError('single_json_response_changed')
        preflight()
    guard()
    with (root/CLAIM).open('x') as stream:
        stream.write(timestamp());stream.flush();os.fsync(stream.fileno())
    if tree(job)!=auth['original_files'] or tree(ledger())!=auth['original_ledger']:
        raise RuntimeError('single_json_original_evidence_changed')
    plan,receipt=prepared(job)
    archive=RUNTIME/'manual-catarsis-archive'/BATCH/REPAIR
    archive.mkdir(mode=0o700,parents=True,exist_ok=False)
    shutil.copytree(job,archive/CHANNEL);shutil.copytree(ledger(),archive/'ledger')
    if tree(archive/CHANNEL)!=auth['original_files'] or tree(archive/'ledger')!=auth['original_ledger']:
        raise RuntimeError('single_json_archive_verification_failed')
    sys.path.insert(0,str(AUTOMATION))
    import daily_core as core
    editorial=native_editorial()
    import music_provider
    from helpers import daily
    from autonomous_generation import Supervisor
    from shorts_handoff_resume import source_delivery
    old_budget=read(ledger()/'budget.json')
    task=read(root/'request.json');status=read(root/'status.json')
    status.update(state='running',updated_at=timestamp());atomic(root/'status.json',status)
    with daily.locked():
        try:
            for name in ('blocked.json','autonomy-feedback.json','editor-recovery-status.json'):
                safe(job/name).unlink(missing_ok=True)
            history_review(job,guard)
            atomic(job/'editorial-plan.json',plan)
            atomic(job/'saved-json-recovery-v48-2.json',dict(receipt,repair_id=REPAIR,archive=str(archive/CHANNEL)))
            saved_music=read(job/'music-input.json')
            old_catalogue=music_provider.catalogue
            def catalogue(directory,channel,topic):
                if Path(directory)!=job or channel!=CHANNEL:raise RuntimeError('single_json_music_scope_changed')
                return saved_music
            music_provider.catalogue=catalogue
            class LocalSupervisor(Supervisor):
                def decision(self,*args,**kwargs):
                    raise RuntimeError('single_json_local_correction_requires_attention')
            supervisor=LocalSupervisor(job,guard,attempt_namespace=REPAIR)
            try:
                with manual_editorial(editorial,job,BATCH,CHANNEL,task['date'],guard,recovery=supervisor):
                    original_external,original_invoke=editorial.external,editorial.invoke
                    def review_only(directory,prompt,output,*args,**kwargs):
                        if str(output)!='visual-review.json' and not prompt.startswith('Perform ONE local copy edit for the SAME video.'):
                            raise editorial.Blocked('single_json_planning_disabled')
                        return original_invoke(directory,prompt,output,*args,**kwargs)
                    editorial.external=source_delivery(job,original_external,guard)
                    editorial.invoke=review_only
                    try:editorial.build(job,CHANNEL,task['date'],task['topics'][CHANNEL],scope='production')
                    finally:editorial.external,editorial.invoke=original_external,original_invoke
            finally:
                music_provider.catalogue=old_catalogue
            guard();approval=core.approval(job,CHANNEL,task['date'])
            if approval.get('scope')!='production':raise RuntimeError('manual_quality_scope_mismatch')
            files={}
            for kind,name in (('video','video.mp4'),('thumbnail','thumbnail.jpg')):
                info=(job/name).stat()
                files[kind]=dict(size=info.st_size,mtime_ns=info.st_mtime_ns,ctime_ns=info.st_ctime_ns,sha256=sha(job/name))
            finish_budget(old_budget)
            status['channels'][CHANNEL]=dict(state='ready',error_code=None,files=files,
                metadata=public_metadata(read(job/'metadata.json')),approval_sha256=sha(job/'approval.json'))
            status.update(state='ready',error_code=None,updated_at=timestamp())
        except Exception as exc:
            code=safe_error(exc)
            atomic(job/'blocked.json',dict(at=timestamp(),phase=REPAIR,reason=code))
            status['channels'][CHANNEL]=dict(state='blocked',error_code=code,diagnostic=diagnostic(job,code))
            status.update(state='blocked',error_code=code,updated_at=timestamp())
        atomic(root/'status.json',status)


if __name__=='__main__':
    sys.path.insert(1,str(ROOT))
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch-id',required=True)
    parser.add_argument('--inspect',action='store_true')
    args=parser.parse_args()
    try:
        task,status,plan,receipt=inspect(args.batch_id)
        print(json.dumps(dict(state='checked',batch_id=BATCH,read_only=True,ai_requests=0,
            syntax_repairs=receipt['syntax_repairs'],scenes=len(plan['project']['sequence']),
            seconds=sum(float(s['seconds']) for s in plan['project']['sequence']),
            native_plan_valid=True,planning='reuse_saved',paid_limits_increased=False,
            publication_allowed=False)))
    except Exception as exc:
        from generation_service import safe_error
        print(json.dumps(dict(state='blocked',error_code=safe_error(exc),batch_id=BATCH,ai_requests=0,publication_allowed=False)))
        raise SystemExit(2)
