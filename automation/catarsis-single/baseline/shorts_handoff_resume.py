"""Recover only the two observed saved JSON handoffs; no replanning or budget reset."""
import ast
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sys
from history_data import CHANNELS,atomic,read,timestamp
from generation_service import STATE,JOBS,denied,safe_error
from generation_worker import AUTOMATION,SOURCE_HASHES
from repair_controller import pins,sha

BATCH='fa402b8286c149e698875a48b471977c'
REQUEST='manual-balto-indianapolis-catarsis-20261029-v1'
REPAIR='saved-json-and-timing-v44'
AUTH='shorts-handoff-v44.json'
CLAIM='shorts-handoff-v44.claimed'
BINDING='saved-handoff-binding-v44.json'
CODE=Path(__file__).resolve().parent
MODULES=('curated-plans-v44.json','handoff-evidence-v44.json','shorts_handoff.py','shorts_handoff_resume.py','balto-indianapolis-topics-v44.json',
    'deepseek_editor.py','deepseek_runtime.py','deepseek_review.py','documentary_sources.py',
    'generation_worker.py','generation_service.py','autonomous_generation.py','editorial_recovery.py',
    'catarsis_style.py','catarsis_fixes.py','platform_rules.py','editor_efficiency.py','caption_policy.py',
    'review_consistency.py','review_cache.py','shorts_media.py','music_credit_changes.py','credit_repair.py')
EXPECTED={CHANNELS[0]:dict(chat=7,search=0,fetch=3,invocations=3,input_tokens=154836,output_tokens=10129),
          CHANNELS[1]:dict(chat=6,search=2,fetch=3,invocations=1,input_tokens=102735,output_tokens=2562)}
ERRORS={CHANNELS[0]:'generation_dependency_deepseek_json_invalid',CHANNELS[1]:'autonomy_agent_modified_protected_files'}
OUTPUTS={CHANNELS[0]:'editorial-plan-autonomy-2.json',CHANNELS[1]:'editorial-plan.json'}

class SavedPlanError(RuntimeError):
    def __init__(self,details):
        super().__init__('handoff_saved_candidates_invalid');self.details=details

def ledger(jobs,channel):return Path(jobs).parent/'deepseek-ledger/catarsis'/BATCH/channel

def native_validator():
    source=AUTOMATION/'editorial.py'
    if sha(source)!=SOURCE_HASHES['editorial.py']:raise RuntimeError('handoff_native_source_changed')
    node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='validate_plan')
    space={'Blocked':RuntimeError};exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),space)
    return space['validate_plan']

def factual_sources(job):
    from documentary_sources import available
    result={}
    tools=read(__import__('deepseek_runtime').workspace(job)/'tools.json')
    for row in tools.values():
        response=row.get('result',{});content=response.get('content')
        if row.get('kind')=='fetch' and response.get('state') not in ('unavailable','error') and isinstance(content,str) and len(content.strip())>=350:
            result[row['request']['url']]=dict(content=content,transport='saved_deepseek_fetch_response',retrieved_at=row.get('retrieved_at','not_recorded'))
    result.update({url:dict(content=row['content'],transport=row['transport'],retrieved_at=row.get('retrieved_at','not_recorded')) for url,row in available(job).items()})
    if job.name==CHANNELS[1]:
        supplied=read(CODE/'handoff-evidence-v44.json')
        if supplied.get('version')!='retrieved-public-evidence-v44':raise RuntimeError('handoff_supplied_evidence_version')
        for url,row in supplied['items'].items():
            if (url!='https://www.govinfo.gov/content/pkg/BILLS-115s2101enr/html/BILLS-115s2101enr.htm' or row.get('url')!=url or
                row.get('transport')!='assistant_web_tool_retrieved_excerpt' or
                __import__('hashlib').sha256(row['content'].encode()).hexdigest()!=row['content_sha256']):
                raise RuntimeError('handoff_supplied_evidence_changed')
            result[url]=dict(content=row['content'],transport=row['transport'],retrieved_at=row['retrieved_at'],scope=row['raw_scope'])
    return result

def validate_saved(job,value):
    from shorts_handoff import timing
    channel=job.name
    value,times=timing(value)
    task=read(job/'job.json')
    if any(value.get(k)!=task[k] for k in ('channel','date','topic')):raise RuntimeError('handoff_original_binding_changed')
    from shorts_media import normalize_plan
    value=normalize_plan(job,value)
    evidence=factual_sources(job);urls={r['url'] for r in value.get('research',[])}
    if len(urls)<2 or not urls<=set(evidence):raise RuntimeError('handoff_saved_factual_support_missing')
    for source_row in value['research']:
        actual=evidence[source_row['url']]
        source_row.update(evidence_transport=actual['transport'],cached_content_sha256=__import__('hashlib').sha256(actual['content'].encode()).hexdigest(),cache_original_retrieved_at=actual.get('retrieved_at','not_recorded'),evidence_scope=actual.get('scope','saved_provider_text'))
    music=read(job/'music-input.json')
    native_validator()(value,channel,task['date'],music,{})
    from catarsis_style import validate
    from platform_rules import validate_base_plan
    validate(value);validate_base_plan(value)
    if channel==CHANNELS[1] and not any(t.get('recording_id')==value.get('music_recording_id') and t.get('title')==value.get('music_title') for t in music['tracks']):
        raise RuntimeError('handoff_music_not_in_saved_catalog')
    return value,times

def prepared(job,jobs):
    channel=job.name;binding=read(CODE/'curated-plans-v44.json').get(channel)
    if not isinstance(binding,dict) or read(job/'job.json')!=binding['job']:
        raise RuntimeError('handoff_curated_job_binding_changed')
    source=(job if binding['source_scope']=='job' else ledger(jobs,channel))/binding['source_file']
    if source.is_symlink() or sha(source)!=binding['source_sha256']:
        raise RuntimeError('handoff_observed_source_changed')
    value,times=validate_saved(job,binding['plan'])
    return value,dict(source_file=str(source),source_sha256=sha(source),source_kind='curated_from_complete_user_report',
        report_binding=binding['source_plan_sha256'],changes=binding['changes'],duration_repair=times,
        planning_ai_requests=0,research_ai_requests=0)

def inspect(state,jobs,batch):
    if batch!=BATCH:raise RuntimeError('handoff_batch_not_authorized')
    state,jobs=Path(state),Path(jobs);task=read(state/batch/'request.json');status=read(state/batch/'status.json')
    topics=read(CODE/'balto-indianapolis-topics-v44.json')
    if (task.get('batch_id')!=batch or task.get('request_id')!=REQUEST or task.get('topics')!=topics or
        task.get('operation')!='generate_only' or task.get('publication_allowed') is not False or task.get('date')!='2026-10-29'):
        raise RuntimeError('handoff_original_request_changed')
    if status.get('state')!='blocked':raise RuntimeError('handoff_requires_observed_block')
    if (state/batch/'STOP').exists():raise RuntimeError('generation_cancelled')
    if (state.parent/'catarsis-publication'/batch).exists():raise RuntimeError('handoff_publication_state_exists')
    result={};failures=[]
    for channel in CHANNELS:
        job=jobs/batch/channel;row=status.get('channels',{}).get(channel,{})
        if row.get('state')!='blocked' or row.get('error_code')!=ERRORS[channel]:raise RuntimeError('handoff_observed_error_changed')
        if any((job/n).exists() for n in ('video.mp4','rendering.json','approval.json','publication.json','.transport.json')):
            raise RuntimeError('handoff_existing_render_requires_reconciliation')
        expected=dict(date=task['date'],channel=channel,topic=topics[channel],scope='production',manual_batch=batch,generation_only=True,publication_allowed=False)
        if read(job/'job.json')!=expected or read(job/'style-profile.json').get('version')!='introspective-catarsis-v7':
            raise RuntimeError('handoff_job_binding_changed')
        budget=read(ledger(jobs,channel)/'budget.json')
        if budget.get('counts')!=EXPECTED[channel] or budget.get('pending') is not None or budget.get('estimated_usd',1)>=.2:
            raise RuntimeError('handoff_requires_observed_settled_budget')
        receipt=read(ledger(jobs,channel)/'history-check.json')
        if receipt.get('history_review_complete') is not True or receipt.get('duplicate') is not False:
            raise RuntimeError('handoff_semantic_history_receipt_missing')
        try:result[channel]=prepared(job,jobs)
        except SavedPlanError as exc:failures.extend(exc.details)
        except Exception as exc:failures.append(dict(channel=channel,candidate=OUTPUTS[channel],error_code=safe_error(exc)))
    if failures:raise SavedPlanError(failures)
    return task,status,result

def authorize(state,jobs,batch):
    task,status,prepared_plans=inspect(state,jobs,batch)
    from publication_service import controls
    now=dt.datetime.now(dt.timezone.utc)
    native={str(AUTOMATION/n):sha(AUTOMATION/n) for n in ('editorial.py','music_provider.py','epidemic_mcp.py','daily_core.py','music-policy.json')}
    auth=dict(batch_id=batch,repair_id=REPAIR,operation='recover_saved_generation_only',
        request_sha256=sha(Path(state)/batch/'request.json'),controls=controls(),native_pins=native,
        code_sha256={n:sha(CODE/n) for n in MODULES},created_at=now.isoformat(),expires_at=(now+dt.timedelta(hours=12)).isoformat(),
        original_files={c:pins(Path(jobs)/batch/c) for c in CHANNELS},ledger_files={c:pins(ledger(jobs,c)) for c in CHANNELS},
        original_counts=EXPECTED,text_reviews_max_per_video=1,planning_ai_requests=0,limits_increased=False,publication_allowed=False)
    atomic(Path(state)/batch/AUTH,auth);return auth

def start(broker,batch):
    if batch!=BATCH:return denied('handoff_batch_not_authorized')
    if (broker.state/batch/AUTH).exists():return broker.status(batch)
    if broker.active or (getattr(broker,'publication',None) and broker.publication.active):return denied('another_manual_operation_is_running')
    try:authorize(broker.state,broker.jobs,batch)
    except Exception as exc:return denied(safe_error(exc))
    value=read(broker.state/batch/'status.json');value.update(state='accepted',error_code=None,repair_id=REPAIR,updated_at=timestamp())
    atomic(broker.state/batch/'status.json',value);broker.active[batch]=True
    try:broker.launch(lambda:broker.work(batch,handoff=True))
    except Exception:
        broker.active.pop(batch,None);value.update(state='blocked',error_code='handoff_worker_start_failed');atomic(broker.state/batch/'status.json',value)
    return broker.status(batch)

def review_allowance(folder,output,budget):
    folder=Path(folder)
    if not (folder/BINDING).exists():return
    state=STATE/BATCH;auth=read(state/AUTH)
    if (folder.parent!=JOBS/BATCH or folder.name not in CHANNELS or auth.get('repair_id')!=REPAIR or
        read(folder/BINDING)!=dict(repair_id=REPAIR,auth_sha256=sha(state/AUTH)) or not (state/CLAIM).is_file()):
        raise RuntimeError('handoff_review_binding_changed')
    old=auth['original_counts'][folder.name];counts=budget['counts']
    if output!='deepseek-text-review.json' or counts['chat']>=old['chat']+1 or counts['invocations']>=old['invocations']+1:
        raise RuntimeError('generation_dependency_handoff_saved_plan_only')

def source_delivery(job,original,guard):
    from curated_short_plans import SavedSource
    known=factual_sources(job);wanted={r['url']:r for r in read(job/'editorial-plan.json')['research']}
    def fetch(url,*args,**kwargs):
        guard()
        if url in wanted:
            row=known[url]
            if __import__('hashlib').sha256(row['content'].encode()).hexdigest()!=wanted[url]['cached_content_sha256']:
                raise RuntimeError('handoff_cached_source_changed')
            result=SavedSource(url,row['content']);result.evidence_transport=row['transport'];return result
        return original(url,*args,**kwargs)
    return fetch

def perform(batch):
    if batch!=BATCH:raise RuntimeError('handoff_batch_not_authorized')
    from publication_service import controls
    from generation_worker import preflight,manual_editorial,public_metadata,diagnostic
    root=STATE/batch;auth=read(root/AUTH);auth_pin=sha(root/AUTH)
    if auth.get('repair_id')!=REPAIR or auth.get('request_sha256')!=sha(root/'request.json') or auth.get('limits_increased') is not False:
        raise RuntimeError('handoff_authorization_changed')
    def guard():
        if (root/'STOP').exists():raise RuntimeError('generation_cancelled')
        if (sha(root/AUTH)!=auth_pin or sha(root/'request.json')!=auth['request_sha256'] or controls()!=auth['controls'] or
            any(sha(CODE/n)!=v for n,v in auth['code_sha256'].items()) or any(sha(p)!=v for p,v in auth['native_pins'].items())):
            raise RuntimeError('handoff_inputs_changed')
        if dt.datetime.now(dt.timezone.utc)>=dt.datetime.fromisoformat(auth['expires_at']):raise RuntimeError('handoff_authorization_expired')
        if (STATE.parent/'catarsis-publication'/batch).exists():raise RuntimeError('handoff_publication_state_exists')
        for c in CHANNELS:
            for n in ('job.json','style-profile.json','history-input.json','music-input.json','shorts-media-v34.json'):
                if sha(JOBS/batch/c/n)!=auth['original_files'][c][n]:raise RuntimeError('handoff_evidence_changed')
            if any((JOBS/batch/c/n).exists() for n in ('publication.json','.transport.json')):raise RuntimeError('handoff_publication_state_exists')
        preflight()
    guard()
    with (root/CLAIM).open('x') as f:f.write(timestamp());f.flush();os.fsync(f.fileno())
    archive=JOBS.parent/'manual-catarsis-archive'/batch/REPAIR;archive.mkdir(mode=0o700,parents=True,exist_ok=False)
    prepared_plans={}
    for c in CHANNELS:
        if pins(JOBS/batch/c)!=auth['original_files'][c] or pins(ledger(JOBS,c))!=auth['ledger_files'][c]:raise RuntimeError('handoff_original_files_changed')
        shutil.copytree(JOBS/batch/c,archive/c);shutil.copytree(ledger(JOBS,c),archive/'ledger'/c)
        if pins(archive/c)!=auth['original_files'][c] or pins(archive/'ledger'/c)!=auth['ledger_files'][c]:raise RuntimeError('handoff_archive_verification_failed')
        prepared_plans[c]=prepared(JOBS/batch/c,JOBS)
    sys.path.insert(0,str(AUTOMATION));import daily_core as core;import editorial;import music_provider
    from helpers import daily
    from autonomous_generation import Supervisor
    class LocalSupervisor(Supervisor):
        def decision(self,*args,**kwargs):raise RuntimeError('autonomy_handoff_local_repair_requires_attention')
    task=read(root/'request.json');status=read(root/'status.json');status.update(state='running',updated_at=timestamp());atomic(root/'status.json',status)
    with daily.locked():
        for c in CHANNELS:
            job=JOBS/batch/c;guard();plan,receipt=prepared_plans[c]
            for n in ('blocked.json','autonomy-feedback.json','editor-recovery-status.json'):(job/n).unlink(missing_ok=True)
            atomic(job/BINDING,dict(repair_id=REPAIR,auth_sha256=sha(root/AUTH)))
            atomic(job/'editorial-plan.json',plan);atomic(job/'handoff-recovery-v44.json',dict(receipt,repair_id=REPAIR,archive=str(archive/c)))
            saved_music=read(job/'music-input.json');old_catalogue=music_provider.catalogue
            def catalogue(directory,channel,topic):
                if Path(directory)!=job or channel!=c:raise RuntimeError('handoff_music_scope_changed')
                return saved_music
            music_provider.catalogue=catalogue
            status['channels'][c]=dict(state='preparing',error_code=None);status['updated_at']=timestamp();atomic(root/'status.json',status)
            try:
                supervisor=LocalSupervisor(job,guard,attempt_namespace=REPAIR)
                with manual_editorial(editorial,job,batch,c,task['date'],guard,recovery=supervisor):
                    original=editorial.external;editorial.external=source_delivery(job,original,guard)
                    try:editorial.build(job,c,task['date'],task['topics'][c],scope='production')
                    finally:editorial.external=original
                guard();approval=core.approval(job,c,task['date'])
                if approval.get('scope')!='production':raise RuntimeError('manual_quality_scope_mismatch')
                files={}
                for kind,name in (('video','video.mp4'),('thumbnail','thumbnail.jpg')):
                    info=(job/name).stat();files[kind]=dict(size=info.st_size,mtime_ns=info.st_mtime_ns,ctime_ns=info.st_ctime_ns,sha256=sha(job/name))
                status['channels'][c]=dict(state='ready',error_code=None,files=files,metadata=public_metadata(read(job/'metadata.json')),approval_sha256=sha(job/'approval.json'))
            except Exception as exc:
                code=safe_error(exc);atomic(job/'blocked.json',dict(at=timestamp(),phase=REPAIR,reason=code))
                status['channels'][c]=dict(state='blocked',error_code=code,diagnostic=diagnostic(job,code))
            finally:music_provider.catalogue=old_catalogue
            current=read(ledger(JOBS,c)/'budget.json');old=read(archive/'ledger'/c/'budget.json')
            if (any(current['counts'][k]<v for k,v in old['counts'].items()) or current['usage'][:len(old['usage'])]!=old['usage'] or
                current['counts']['chat']>old['counts']['chat']+1 or current['counts']['invocations']>old['counts']['invocations']+1):
                raise RuntimeError('handoff_paid_ledger_changed_out_of_scope')
            if sha(ledger(JOBS,c)/'tools.json')!=auth['ledger_files'][c]['tools.json']:raise RuntimeError('handoff_research_cache_changed')
            status['updated_at']=timestamp();atomic(root/'status.json',status)
    ready=sum(row.get('state')=='ready' for row in status['channels'].values())
    status.update(state='ready' if ready==2 else 'partial' if ready else 'blocked',updated_at=timestamp());atomic(root/'status.json',status)
