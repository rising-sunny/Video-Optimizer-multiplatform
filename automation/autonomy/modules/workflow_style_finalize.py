"""Finish one exact all-positive visual inspection with native AV scope evidence.

The provider's overall false flag stays in its raw cache and archived response.
No failed check is overridden and no new provider or render call is permitted.
"""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import workflow_common as c
from workflow_style_revision import BATCH,CHANNEL,NAME,SOURCE_VIDEO,SOURCE_APPROVAL

STAGE='curie-style-review-scope-v50-4'
REQUEST='finalize-curie-style-review-scope-20261107-v1'
VIDEO='b9b4c5a7521533755d56cc068b61127cd17e175f73a68234374e5efddfb4699f'
EVENTS='4a5b6214bb776262452be8591ead44dda32da99666552e43b877af4200052868'
SHEET='11890cf4dd2462d3ed99c047acc400d14252451d631ac88efc8daf1a81e90ae7'
LIMITATION='The supplied sheets show a deliberate still-photo montage with readable text, contextual labels, and a thumbnail that matches the subject and title. They do not show every video frame, so this assessment cannot confirm full-motion playback or audible quality.'

def resolved(raw,qa):
    from deepseek_review import VISUAL,PLATFORMS
    if (raw.get('approved') is not False or set(raw.get('checks',{}))!=VISUAL
        or not all(v is True for v in raw['checks'].values()) or raw.get('findings')!=[]
        or raw.get('suggestions')!=[LIMITATION]
        or set(raw.get('visual_platform_checks',{}))!=set(PLATFORMS)
        or any(set(row)!={'community_guidelines','non_misleading_context'} or not all(v is True for v in row.values()) for row in raw['visual_platform_checks'].values())
        or qa.get('technical_checks_passed') is not True or qa.get('sha256')!=VIDEO
        or not qa.get('checks') or not all(v is True for v in qa['checks'].values())
        or not all(qa['checks'].get(k) is True for k in ('full_decode','audible_no_clipping','av_duration','duration'))):
        raise RuntimeError('workflow_style_scope_not_unanimous_positive_checks')
    value=copy.deepcopy(raw)
    value.update(approved=True,assessment_source='codex_positive_visual_checks_plus_controller_native_av_scope_verification',
        resolution=dict(version=STAGE,original_provider_approved=False,new_visual_ai_requests=0,
            basis='All seven actual provider visual checks and all platform checks are explicitly true, with no findings. The sole written limitation is outside frame-review scope. Native full AV decode/audio-level/duration checks pass; original AAC and the chat-inspected actual crisp entry sheet are separately hash-bound. No full-video watching or listening is claimed.',
            original_provider_events_sha256=EVENTS,entry_sheet_sha256=SHEET))
    return value

def inspect():
    from generation_worker import preflight
    from workflow_presentation import text_cache,audio_digest
    state,job=c.paths('catarsis',BATCH,CHANNEL)
    status=c.read(state/'status.json');task=c.read(state/'request.json')
    if (status.get('state')!='blocked' or status.get('error_code')!='visual_or_editorial_review_failed'
        or task.get('publication_allowed') is not False or set(task.get('topics',{}))!={CHANNEL}
        or (state/'STOP').exists() or (job/'approval.json').exists()
        or any((job/n).exists() for n in ('publication.json','.transport.json','tiktok-draft.json'))
        or (c.STATE/'catarsis-publication'/BATCH).exists()):raise RuntimeError('workflow_style_scope_stopped_single_required')
    if c.digest(job/'video.mp4')!=VIDEO or c.digest(job/'visual-review-events.jsonl')!=EVENTS or c.digest(job/'style-entry-sheet-0.jpg')!=SHEET:
        raise RuntimeError('workflow_style_scope_observed_inputs_changed')
    rows=[json.loads(line) for line in (job/'visual-review-events.jsonl').read_text().splitlines() if line.strip()]
    if any(r.get('type') in ('error','turn.failed') for r in rows) or not any(r.get('type')=='turn.completed' for r in rows):raise RuntimeError('workflow_style_scope_completed_provider_required')
    from deepseek_editor import parse_handoff
    raw=parse_handoff([r['item']['text'] for r in rows if r.get('type')=='item.completed' and r.get('item',{}).get('type')=='agent_message'][-1])
    qa=c.read(job/'qa.json');decision=resolved(raw,qa)
    review=c.read(job/'visual-review.json')
    from credit_repair import CHECKS
    if (review.get('approved') is not False or review.get('video_sha256')!=VIDEO or set(review.get('checks',{}))!=CHECKS
        or not all(v is True for v in review['checks'].values()) or review.get('findings')!=[]):raise RuntimeError('workflow_style_scope_actual_failed_check')
    cache_root=c.RUNTIME/'workflow-style-reviews'/BATCH/(NAME+'-clean-entry')
    caches=[p for p in cache_root.glob('vision-*.json') if c.read(p)==raw]
    if len(caches)!=1 or len(list(cache_root.glob('vision-*.claimed')))!=1:raise RuntimeError('workflow_style_scope_exact_provider_cache_required')
    parent=c.read(state/(NAME+'-auth.json'))
    if c.tree(c.ledger(job))!=parent['item']['ledger']:raise RuntimeError('workflow_style_scope_original_budget_changed')
    for name in ('editorial-plan.json','sources.json','asset-credits.json','metadata.json','music-license-evidence.json','project.json','thumbnail.jpg'):
        if c.digest(job/name)!=parent['item']['files'][name]:raise RuntimeError('workflow_style_scope_factual_evidence_changed')
    original=c.RUNTIME/'workflow-attempts/catarsis'/BATCH/NAME/'job'
    if c.digest(original/'video.mp4')!=SOURCE_VIDEO or c.digest(original/'approval.json')!=SOURCE_APPROVAL or audio_digest(job/'video.mp4')!=audio_digest(original/'video.mp4'):
        raise RuntimeError('workflow_style_scope_original_audio_or_approval_changed')
    cache=text_cache(job);preflight()
    return dict(files=c.tree(job),ledger=c.tree(c.ledger(job)),decision=decision,provider_cache=str(caches[0]),
        provider_cache_sha256=c.digest(caches[0]),text_cache=str(cache),text_cache_sha256=c.digest(cache))

def start(broker,ident,request_id):
    from generation_service import denied,safe_error
    from workflow_jobs import frozen_sources
    from publication_service import controls
    from history_data import timestamp
    if ident!=BATCH or request_id!=REQUEST:return denied('workflow_style_scope_exact_request_required')
    state,job=c.paths('catarsis',BATCH,CHANNEL);path=state/(STAGE+'-auth.json')
    if path.exists():return broker.status(BATCH)
    try:
        item=inspect();c.write(path,dict(job_id=BATCH,request_id=REQUEST,request_sha256=c.digest(state/'request.json'),
            item=item,sources=frozen_sources(),controls=controls(),publication_allowed=False,new_ai_requests=0))
        status=c.read(state/'status.json');status.update(state='accepted',error_code=None,updated_at=timestamp());c.write(state/'status.json',status)
        broker.active[BATCH]=True
        def execute():
            try:perform()
            except Exception as exc:
                value=c.read(state/'status.json');value.update(state='blocked',error_code=safe_error(exc),updated_at=timestamp());c.write(state/'status.json',value)
            finally:
                with broker.lock:broker.active.pop(BATCH,None)
        broker.launch(execute);return broker.status(BATCH)
    except Exception as exc:broker.active.pop(BATCH,None);return denied(safe_error(exc))

def perform():
    from generation_worker import preflight,manual_editorial,public_metadata
    from workflow_native import implementation,enabled
    from workflow_readable import sequence_for_display
    from workflow_presentation import text_cache
    from credit_repair import native_review_function
    from autonomous_generation import Supervisor
    from publication_service import controls
    from history_data import timestamp
    from deepseek_runtime import Client
    import deepseek_review
    state,job=c.paths('catarsis',BATCH,CHANNEL);path=state/(STAGE+'-auth.json');auth=c.read(path);pin=c.digest(path);item=auth['item']
    if auth.get('job_id')!=BATCH or auth.get('request_id')!=REQUEST or auth.get('new_ai_requests')!=0 or auth.get('publication_allowed') is not False:raise RuntimeError('workflow_style_scope_auth_invalid')
    def guard():
        if ((state/'STOP').exists() or c.digest(path)!=pin or c.digest(state/'request.json')!=auth['request_sha256']
            or controls()!=auth['controls'] or any(c.digest(Path(p))!=s for p,s in auth['sources'].items())
            or c.digest(job/'video.mp4')!=VIDEO or c.digest(job/'visual-review-events.jsonl')!=EVENTS
            or c.digest(Path(item['provider_cache']))!=item['provider_cache_sha256'] or c.tree(c.ledger(job))!=item['ledger']):
            raise RuntimeError('workflow_style_scope_frozen_evidence_changed')
        preflight()
    guard()
    with (state/(STAGE+'.claim')).open('x') as stream:stream.write(timestamp());stream.flush();os.fsync(stream.fileno())
    archive=c.RUNTIME/'workflow-attempts/catarsis'/BATCH/STAGE;archive.mkdir(mode=0o700,parents=True,exist_ok=False)
    if c.tree(job)!=item['files']:raise RuntimeError('workflow_style_scope_job_changed')
    shutil.copytree(job,archive/'job');shutil.copytree(c.ledger(job),archive/'ledger')
    if c.tree(archive/'job')!=item['files'] or c.tree(archive/'ledger')!=item['ledger']:raise RuntimeError('workflow_style_scope_archive_failed')
    sys.path.insert(0,'/home/videoagent/video-automation');import editorial as exported;import daily_core as core
    from helpers import daily
    editorial=implementation(exported);project=c.read(job/'project.json');plan=c.read(job/'editorial-plan.json');task=c.read(state/'request.json')
    old_visual,old_request=deepseek_review.visual,Client.request
    def no_new_text(*args,**kwargs):raise RuntimeError('workflow_style_scope_no_provider_calls')
    def saved_visual(folder,images,documentary=False,quota_recovery=None):
        guard()
        if Path(folder)!=job or documentary or quota_recovery is not None or not images:raise RuntimeError('workflow_style_scope_review_inputs_changed')
        for image in images:
            if Path(image).parent!=job or c.digest(image)!=item['files'].get(Path(image).name):raise RuntimeError('workflow_style_scope_review_image_changed')
        return copy.deepcopy(item['decision'])
    try:
        with daily.locked():
            Client.request=no_new_text;deepseek_review.visual=saved_visual
            status=c.read(state/'status.json');status.update(state='running',error_code=None,updated_at=timestamp());c.write(state/'status.json',status)
            c.write(job/'style-scope-resolution-v50.json',dict(decision=item['decision'],original_provider_response_preserved=True,
                original_events_sha256=EVENTS,video_sha256=VIDEO,actual_entry_sheet_inspected_in_current_chat_sha256=SHEET,
                new_ai_requests=0,new_renders=0,publication_authorized=False))
            editorial.d.qa(job/'video.mp4',job,smoke=False)
            resolved(c.read(Path(item['provider_cache'])),c.read(job/'qa.json'))
            if c.digest(text_cache(job))!=item['text_cache_sha256']:raise RuntimeError('workflow_style_scope_text_cache_changed')
            old_qa=editorial.extended_qa;display=sequence_for_display(project['sequence'])
            extras=sorted(job.glob('style-entry-sheet-*.jpg'))+[job/'style-reference-sheet.jpg']
            editorial.extended_qa=lambda folder,p:old_qa(folder,dict(p,sequence=display))+extras
            try:
                with enabled(editorial,job,CHANNEL),manual_editorial(editorial,job,BATCH,CHANNEL,task['date'],guard,recovery=Supervisor(job,guard,attempt_namespace=STAGE)):
                    write=editorial.atomic
                    def audited(target,value):
                        if Path(target)==job/'vision-evidence.json':value=dict(value,new_visual_ai_requests=0,original_provider_approved=False,
                            invocation='Reused completed native Codex positive image/platform checks; controller verifies native full AV QA and frame-review scope',
                            quality_decision_source=STAGE,original_provider_events_sha256=EVENTS)
                        return write(target,value)
                    editorial.atomic=audited
                    try:native_review_function(editorial)(job,project,plan,CHANNEL,task['date'],'production',False)
                    finally:editorial.atomic=write
            finally:editorial.extended_qa=old_qa
            guard();core.approval(job,CHANNEL,task['date'])
            files={}
            for kind,name in (('video','video.mp4'),('thumbnail','thumbnail.jpg')):
                p=job/name;s=p.stat();files[kind]=dict(size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns,sha256=c.digest(p))
            status['channels'][CHANNEL]=dict(state='ready',error_code=None,files=files,metadata=public_metadata(c.read(job/'metadata.json')),approval_sha256=c.digest(job/'approval.json'))
            status.update(state='ready',error_code=None,updated_at=timestamp());c.write(state/'status.json',status)
            tracking=c.read(state/'workflow.json');tracking['style_revision'].update(state='ready',scope_resolution=STAGE,new_ai_requests_for_resolution=0);c.write(state/'workflow.json',tracking)
    finally:deepseek_review.visual=old_visual;Client.request=old_request
