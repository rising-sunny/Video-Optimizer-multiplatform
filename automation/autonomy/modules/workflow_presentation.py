"""One local display correction, preserving approved text and original review caps."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import workflow_common as c

NAME='workflow-presentation-v1'

def text_cache(job):
    from deepseek_review import evidence,text_prompt,POLICY_KEYS
    from deepseek_editor import input_fingerprint
    prompt=text_prompt(evidence(job),False,sorted(POLICY_KEYS),platform_policies=False)
    path=c.ledger(job)/('handoff-'+input_fingerprint(job,prompt,'deepseek-text-review.json')+'.json')
    value=c.read(path)
    if value.get('approved') is not True or set(value.get('checks',{}))!={'facts_supported','licenses_and_full_credits'} or not all(value['checks'].values()):
        raise RuntimeError('workflow_presentation_positive_text_cache_required')
    return path

def inspect(ident,technical=False):
    from generation_worker import preflight
    from catarsis_selection import task_channels
    if not c.valid_id(ident):raise RuntimeError('workflow_invalid_job')
    state=c.STATE/'catarsis'/ident;task=c.read(state/'request.json');status=c.read(state/'status.json')
    channels=task_channels(task)
    if len(channels)!=1 or task.get('publication_allowed') is not False or status.get('state')!='blocked' or (state/'STOP').exists():
        raise RuntimeError('workflow_presentation_single_stopped_generation_required')
    channel=channels[0];job=c.RUNTIME/'manual-catarsis'/ident/channel
    if any((job/name).exists() for name in ('approval.json','publication.json','.transport.json')):
        raise RuntimeError('workflow_presentation_unpublished_unapproved_required')
    if technical:
        if not (state/(NAME+'.claim')).is_file() or (state/(NAME+'-technical.claim')).exists():
            raise RuntimeError('workflow_presentation_technical_checkpoint_unavailable')
        parent=c.read(state/(NAME+'-auth.json'));old=parent['item']
        if parent.get('job_id')!=ident or parent.get('request_sha256')!=c.digest(state/'request.json'):
            raise RuntimeError('workflow_presentation_parent_request_changed')
        current=c.tree(job)
        if ({k:v for k,v in current.items() if k!='blocked.json'}!={k:v for k,v in old['files'].items() if k!='blocked.json'}
            or c.tree(c.ledger(job))!=old['ledger']):
            raise RuntimeError('workflow_presentation_changed_checkpoint_not_replayable')
    elif (state/(NAME+'.claim')).exists():raise RuntimeError('workflow_presentation_already_attempted')
    review=c.read(job/'visual-review.json');text=c.read(job/'deepseek-text-review.json');qa=c.read(job/'qa.json')
    failed={key for key,value in review.get('checks',{}).items() if value is not True}
    if (review.get('approved') is not False or not failed or not failed<={'text_readable','context_labels'}
        or review.get('checks',{}).get('images_inspected') is not True
        or text.get('approved') is not True or set(text.get('checks',{}))!={'facts_supported','licenses_and_full_credits'} or not all(text['checks'].values())):
        raise RuntimeError('workflow_presentation_display_only_failure_required')
    video=c.digest(job/'video.mp4')
    if qa.get('technical_checks_passed') is not True or qa.get('sha256')!=video or review.get('video_sha256')!=video:
        raise RuntimeError('workflow_presentation_exact_video_qa_required')
    root=c.ledger(job);budget=c.read(root/'budget.json')
    if budget.get('pending') is not None:raise RuntimeError('workflow_ambiguous_provider_request')
    # This is the existing native Short cap (two), not a new allowance.
    if len(list(root.glob('vision-*.claimed')))!=1:
        raise RuntimeError('generation_dependency_codex_visual_budget_exhausted')
    cache=text_cache(job)
    plan=c.read(job/'editorial-plan.json');project=c.read(job/'project.json')
    if plan.get('project',{}).get('sequence')!=project.get('sequence'):
        raise RuntimeError('workflow_presentation_sequence_binding_changed')
    from workflow_readable import layout
    for scene in project['sequence']:
        if scene.get('kind')=='card':layout(scene.get('text',''))
        if scene.get('kind') in ('media','overlay'):layout(plan['assets'][scene['media']]['label'],caption=True)
    preflight()
    return dict(channel=channel,job=str(job),files=c.tree(job),ledger=c.tree(root),
        text_cache=dict(file=cache.name,sha256=c.digest(cache)),budget=budget,
        video_sha256=video,failed_checks=sorted(failed))

def available(ident):
    try:
        item=inspect(ident)
        return dict(state='eligible',scope='existing_text_labels_and_pixel_layout_only',
            failed_checks=item['failed_checks'],text_ai_requests=0,native_visual_reviews_remaining=1)
    except Exception as exc:
        try:
            inspect(ident,technical=True)
            return dict(state='eligible_technical_checkpoint',scope='original_render_never_changed',text_ai_requests=0,native_visual_reviews_remaining=1)
        except Exception:return dict(state='blocked',error_code=c.clean(exc,300))

def start(broker,ident,request_id):
    from generation_service import denied,safe_error
    from publication_service import controls
    from workflow_jobs import frozen_sources,PYTHON
    from history_data import timestamp
    state=c.STATE/'catarsis'/ident
    try:
        technical=(state/(NAME+'.claim')).exists()
        item=inspect(ident,technical=technical)
        stage_name=NAME+('-technical' if technical else '')
        auth=dict(job_id=ident,request_sha256=c.digest(state/'request.json'),item=item,
            sources=frozen_sources(),controls=controls(),publication_allowed=False)
        if technical:auth['parent_auth_sha256']=c.digest(state/(NAME+'-auth.json'))
        c.write(state/(stage_name+'-auth.json'),auth)
        tracking=c.read(state/'workflow.json')
        tracking.setdefault('requests',{})[request_id]=stage_name
        tracking['presentation']=dict(state='queued',scope='display_only',original_attempts_preserved=True,technical_checkpoint=technical)
        tracking['state']='resuming';c.write(state/'workflow.json',tracking)
        status=c.read(state/'status.json');status.update(state='accepted',error_code=None,updated_at=timestamp())
        status['channels'][item['channel']].update(state='preparing',phase='local_presentation_revision',error_code=None)
        c.write(state/'status.json',status)
        broker.active[ident]=True
        launch=getattr(broker,'launch',None) or broker.parent.launch
        def execute():
            try:
                command=[PYTHON,'-B',str(c.ROOT/'workflow_presentation.py'),'--job-id',ident]
                if technical:command.append('--technical-checkpoint')
                with subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True) as process:
                    deadline=time.monotonic()+1800
                    while process.poll() is None:
                        if (state/'STOP').exists() or time.monotonic()>deadline:
                            os.killpg(process.pid,signal.SIGTERM)
                            try:process.wait(timeout=10)
                            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                            raise RuntimeError('workflow_presentation_cancelled_or_timed_out')
                        time.sleep(.5)
                    if process.returncode:raise RuntimeError('workflow_presentation_worker_failed')
            except Exception as exc:
                status=c.read(state/'status.json');status.update(state='blocked',error_code=safe_error(exc),updated_at=timestamp());c.write(state/'status.json',status)
            finally:
                with broker.lock:broker.active.pop(ident,None)
        try:launch(execute)
        except Exception:
            broker.active.pop(ident,None)
            status.update(state='blocked',error_code='workflow_presentation_launch_failed');c.write(state/'status.json',status)
            tracking['state']='needs_attention';tracking['presentation']['state']='launch_failed';c.write(state/'workflow.json',tracking)
            raise
        return broker.status(ident)
    except Exception as exc:return denied(safe_error(exc))

def audio_digest(path):
    import hashlib
    result=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','data','-'],capture_output=True,timeout=30)
    if result.returncode:raise RuntimeError('workflow_presentation_audio_probe_failed')
    return hashlib.sha256(result.stdout).hexdigest()

def perform(ident,technical=False):
    from generation_worker import preflight,manual_editorial
    from publication_service import controls
    from workflow_jobs import run_catarsis,verify_ledger
    from workflow_native import implementation,enabled
    from autonomous_generation import Supervisor
    from history_data import timestamp
    state=c.STATE/'catarsis'/ident;stage_name=NAME+('-technical' if technical else '')
    auth_path=state/(stage_name+'-auth.json');auth=c.read(auth_path);auth_sha=c.digest(auth_path)
    if auth.get('job_id')!=ident or auth.get('publication_allowed') is not False:raise RuntimeError('workflow_presentation_auth_invalid')
    item=auth['item'];job=Path(item['job']);channel=item['channel'];task=c.read(state/'request.json')
    def guard():
        if (state/'STOP').exists():raise RuntimeError('generation_cancelled')
        if (c.digest(auth_path)!=auth_sha or c.digest(state/'request.json')!=auth['request_sha256']
            or controls()!=auth['controls'] or any(c.digest(Path(path))!=sha for path,sha in auth['sources'].items())):
            raise RuntimeError('workflow_presentation_frozen_inputs_changed')
        preflight()
    guard()
    sys.path.insert(0,'/home/videoagent/video-automation');import editorial as exported
    editorial=implementation(exported)
    # Native build normally performs this import setup before render_project.
    # A display-only render enters later, so prepare the same package path here.
    sys.path.insert(0,str(editorial.REPO));from catharsis import catharsis_editor
    if not all(hasattr(catharsis_editor,name) for name in ('build_shots','text_card','overlay_layer','render')):
        raise RuntimeError('workflow_presentation_renderer_api_changed')
    if technical and c.digest(state/(NAME+'-auth.json'))!=auth.get('parent_auth_sha256'):
        raise RuntimeError('workflow_presentation_parent_auth_changed')
    with (state/(stage_name+'.claim')).open('x') as stream:stream.write(timestamp());stream.flush();os.fsync(stream.fileno())
    archive=c.RUNTIME/'workflow-attempts/catarsis'/ident/stage_name
    if c.tree(job)!=item['files'] or c.tree(c.ledger(job))!=item['ledger']:raise RuntimeError('workflow_presentation_original_inputs_changed')
    archive.mkdir(mode=0o700,parents=True,exist_ok=False)
    shutil.copytree(job,archive/'job');shutil.copytree(c.ledger(job),archive/'ledger')
    if c.tree(archive/'job')!=item['files'] or c.tree(archive/'ledger')!=item['ledger']:raise RuntimeError('workflow_presentation_backup_failed')
    old_video=archive/'job/video.mp4';old_audio=audio_digest(old_video)
    from helpers import daily
    from deepseek_runtime import Client
    request_method=Client.request
    def no_new_text(*args,**kwargs):raise RuntimeError('workflow_presentation_new_text_requests_forbidden')
    status=c.read(state/'status.json')
    try:
        with daily.locked():
            Client.request=no_new_text
            status.update(state='running',error_code=None,updated_at=timestamp());c.write(state/'status.json',status)
            plan=c.read(job/'editorial-plan.json');project=c.read(job/'project.json')
            with enabled(editorial,job,channel),manual_editorial(editorial,job,ident,channel,task['date'],guard,recovery=Supervisor(job,guard,attempt_namespace=NAME)):
                editorial.d.render_project(project,job)
            guard()
            remux=job/'workflow-presentation-remux.mp4'
            result=subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(job/'video.mp4'),'-i',str(old_video),
                '-map','0:v:0','-map','1:a:0','-c','copy','-map_metadata','-1','-map_chapters','-1','-movflags','+faststart',str(remux)],capture_output=True,timeout=60)
            if result.returncode or audio_digest(remux)!=old_audio:raise RuntimeError('workflow_presentation_original_audio_not_preserved')
            os.replace(remux,job/'video.mp4')
            from catarsis_style import EVIDENCE
            proof=c.read(job/EVIDENCE);proof['video_sha256']=c.digest(job/'video.mp4');c.write(job/EVIDENCE,proof)
            if c.digest(c.ledger(job)/item['text_cache']['file'])!=item['text_cache']['sha256'] or text_cache(job).name!=item['text_cache']['file']:
                raise RuntimeError('workflow_presentation_text_evidence_changed')
            for name in ('editorial-plan.json','sources.json','asset-credits.json','metadata.json','music-license-evidence.json','project.json','thumbnail.jpg'):
                if c.digest(job/name)!=item['files'][name]:raise RuntimeError('workflow_presentation_approved_text_or_media_changed')
            c.write(job/'workflow-presentation-proof.json',dict(scope='pixel_layout_and_existing_labels_only',
                original_video_sha256=item['video_sha256'],original_audio_payload_preserved=True,
                old_negative_review_preserved_in_archive=True,text_evidence_exactly_unchanged=True,
                source_audio_sha256=old_audio,display_labels=[row['label'] for row in plan['assets']],text_ai_requests=0))
            editorial.extended_qa(job,project)
            # Native review recalculates QA, reuses the exact cached factual
            # response and uses only the remaining original visual claim.
            status['channels'][channel]=run_catarsis(job,task,channel,ident,guard)
            verify_ledger(job,item['budget'])
            if c.read(c.ledger(job)/'budget.json')['counts']!=item['budget']['counts']:
                raise RuntimeError('workflow_presentation_text_budget_changed')
            status.update(state='ready',error_code=None)
    except Exception as exc:
        from generation_service import safe_error
        code=safe_error(exc);status.update(state='blocked',error_code=code)
        status['channels'][channel].update(state='blocked',error_code=code,diagnostic=code)
        import traceback
        detail=dict(type=type(exc).__name__,message=c.clean(exc,600),
            location=[dict(file=Path(row.filename).name,line=row.lineno) for row in traceback.extract_tb(exc.__traceback__)[-5:]])
        c.write(job/'blocked.json',dict(reason=code,phase=stage_name,at=timestamp(),detail=detail))
    finally:
        Client.request=request_method
        status['updated_at']=timestamp();c.write(state/'status.json',status)
        tracking=c.read(state/'workflow.json');tracking['state']='complete' if status['state']=='ready' else 'needs_attention'
        tracking['presentation']['state']=status['state'];c.write(state/'workflow.json',tracking)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--job-id',required=True);parser.add_argument('--technical-checkpoint',action='store_true');args=parser.parse_args()
    os.umask(0o077);perform(args.job_id,technical=args.technical_checkpoint)
