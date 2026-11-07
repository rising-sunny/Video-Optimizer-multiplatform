"""One explicitly requested, source-bound Curie style revision. Never publishes.

Original approval, video, ledger and claims are archived byte-for-byte. This new
user-requested assessment has one separate visual claim; the original generation
limits and all its claims remain untouched. No text/provider research is allowed.
"""
from contextlib import contextmanager
import copy
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import types

import workflow_common as c

NAME='curie-catarsis-style-v50'
BATCH='cf2a22d4f40f453fba2b3af137b716d1'
CHANNEL='stunning-facts-of-history'
REQUEST_ID='revise-curie-catarsis-style-20261107-v1'
TOPIC='Revise only the visual Catarsis presentation of the approved Marie Curie Short cf2a22d4f40f453fba2b3af137b716d1: restore condensed bold serif cards, semantic phrase deployment and brief kinetic entries; retain verified text, source images, context labels, 55-second timing, music, credits and original generation budget. Generation only.'
SOURCE_VIDEO='1a3a1cf8bc27b4a1910d8bb273a21549a2fc419e887527b332c8ffbcd4742992'
SOURCE_APPROVAL='aafb4abeef41ada2bb5e7d4ff5fb8009a7964ad37d9cb7e0f3ccb9622cd8d365'

def matches(request):
    return request==dict(operation='generation_start_single',request_id=REQUEST_ID,channel=CHANNEL,topic=TOPIC)

def inspect():
    from generation_worker import preflight
    from workflow_presentation import text_cache
    state,job=c.paths('catarsis',BATCH,CHANNEL)
    task,status=c.read(state/'request.json'),c.read(state/'status.json')
    if task.get('publication_allowed') is not False or set(task.get('topics',{}))!={CHANNEL} or status.get('state')!='ready' or (state/'STOP').exists():
        raise RuntimeError('workflow_style_revision_ready_single_required')
    if any((job/n).exists() for n in ('publication.json','.transport.json','tiktok-draft.json')) or (c.STATE/'catarsis-publication'/BATCH).exists():
        raise RuntimeError('workflow_style_revision_unpublished_required')
    if c.digest(job/'video.mp4')!=SOURCE_VIDEO or c.digest(job/'approval.json')!=SOURCE_APPROVAL:
        raise RuntimeError('workflow_style_revision_source_changed')
    sys.path.insert(0,'/home/videoagent/video-automation');import daily_core
    daily_core.approval(job,CHANNEL,task['date'])
    budget=c.read(c.ledger(job)/'budget.json')
    if budget.get('pending') is not None:raise RuntimeError('workflow_ambiguous_provider_request')
    cache=text_cache(job)
    project,plan=c.read(job/'project.json'),c.read(job/'editorial-plan.json')
    if project['sequence']!=plan['project']['sequence']:raise RuntimeError('workflow_style_revision_sequence_changed')
    from workflow_readable import sequence_for_display,layout
    display=sequence_for_display(project['sequence'])
    for s in display:
        if s.get('kind')=='card':layout(s['text'],style=s.get('style','center'))
    preflight()
    return dict(files=c.tree(job),ledger=c.tree(c.ledger(job)),budget=budget,
        text_cache=dict(file=cache.name,sha256=c.digest(cache)),display_sequence=display)

def start(broker,request):
    from generation_service import denied,safe_error
    from publication_service import controls
    from workflow_jobs import frozen_sources,PYTHON
    from history_data import timestamp
    if not matches(request):return denied('workflow_style_revision_exact_request_required')
    state,job=c.paths('catarsis',BATCH,CHANNEL)
    auth_path=state/(NAME+'-auth.json')
    if auth_path.exists():return broker.status(BATCH)
    doc=getattr(broker,'workflow_documentary',None)
    if broker.active or (getattr(broker,'publication',None) and broker.publication.active) or (doc is not None and doc.active):return denied('another_manual_operation_is_running')
    try:
        item=inspect()
        auth=dict(job_id=BATCH,request_id=REQUEST_ID,request_sha256=c.digest(state/'request.json'),
            item=item,sources=frozen_sources(),controls=controls(),visual_reviews_max=1,
            new_text_calls=0,publication_allowed=False,created_at=timestamp())
        c.write(auth_path,auth)
        tracking=c.read(state/'workflow.json')
        tracking['style_revision']=dict(version=NAME,state='queued',request_id=REQUEST_ID,
            original_video_sha256=SOURCE_VIDEO,original_approval_sha256=SOURCE_APPROVAL,
            original_claims_preserved=True,new_text_calls=0,visual_reviews_max=1)
        c.write(state/'workflow.json',tracking)
        status=c.read(state/'status.json');status.update(state='accepted',error_code=None,updated_at=timestamp())
        status['channels'][CHANNEL]=dict(state='preparing',phase='style_revision',error_code=None)
        c.write(state/'status.json',status);broker.active[BATCH]=True
        def execute():
            try:
                with subprocess.Popen([PYTHON,'-B',str(c.ROOT/'workflow_style_revision.py'),'--perform'],
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True) as process:
                    deadline=time.monotonic()+1800
                    while process.poll() is None:
                        if (state/'STOP').exists() or time.monotonic()>deadline:
                            os.killpg(process.pid,signal.SIGTERM)
                            try:process.wait(timeout=10)
                            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                            raise RuntimeError('workflow_style_revision_cancelled_or_timed_out')
                        time.sleep(.5)
                    if process.returncode:raise RuntimeError('workflow_style_revision_worker_failed')
            except Exception as exc:
                value=c.read(state/'status.json');value.update(state='blocked',error_code=safe_error(exc),updated_at=timestamp());c.write(state/'status.json',value)
            finally:
                with broker.lock:broker.active.pop(BATCH,None)
        broker.launch(execute)
        return broker.status(BATCH)
    except Exception as exc:
        broker.active.pop(BATCH,None)
        return denied(safe_error(exc))

@contextmanager
def revision_vision(job,review_root):
    """Use the unchanged real visual reviewer with a separately bound claim root."""
    import deepseek_review
    original=deepseek_review.visual
    calls=0
    def actual(folder,images,documentary=False,quota_recovery=None):
        nonlocal calls
        if calls or Path(folder)!=job or documentary or quota_recovery is not None:
            raise RuntimeError('workflow_style_revision_one_visual_only')
        calls+=1
        def workspace(selected):
            if Path(selected)!=job:raise RuntimeError('workflow_style_revision_review_scope_changed')
            return review_root
        # Neither original generation claims nor budgets are changed or hidden.
        # This is a fresh, explicitly authorized presentation assessment only.
        space=dict(original.__globals__,workspace=workspace)
        fn=types.FunctionType(original.__code__,space,original.__name__,original.__defaults__,original.__closure__)
        fn.__kwdefaults__=original.__kwdefaults__
        return fn(folder,images,documentary=False)
    deepseek_review.visual=actual
    try:yield
    finally:deepseek_review.visual=original

def sample_sheets(job,display):
    """Actual entry frames plus actual published style references; no mock frames."""
    from PIL import Image,ImageDraw
    from workflow_presentation import visible_labels
    at=0.;samples=[]
    for scene in display:
        length=float(scene['seconds'])
        if scene.get('kind')=='card':
            for offset in (.033,.100,.267):samples.append(at+min(offset,length/2))
        at+=length
    paths=[]
    for page in range(0,len(samples),9):
        image=Image.new('RGB',(1080,1980),'#555555');draw=ImageDraw.Draw(image)
        draw.text((15,8),'CURRENT CURIE - actual text entry frames at +1, +3, +8 frames',fill='white')
        for j,seconds in enumerate(samples[page:page+9]):
            file=job/f'style-entry-{page+j:03d}.jpg'
            subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(seconds),'-i',str(job/'video.mp4'),'-vf','scale=360:640','-frames:v','1','-y',str(file)],check=True,capture_output=True,timeout=20)
            with Image.open(file) as frame:image.paste(frame,((j%3)*360,40+(j//3)*640))
        path=job/f'style-entry-sheet-{page//9}.jpg';image.save(path,quality=94);paths.append(path)
    board=Image.new('RGB',(1080,1040),'#555555');draw=ImageDraw.Draw(board)
    draw.text((15,8),'PUBLISHED CATARSIS STYLE REFERENCES - not frames of Curie',fill='white')
    refs=(('8291e6f392b94253a60b7a48d0a1b0e0',7.,'Robert Smalls'),('fa402b8286c149e698875a48b471977c',7.,'Balto'))
    for i,(batch,seconds,title) in enumerate(refs):
        source=c.RUNTIME/'manual-catarsis'/batch/CHANNEL/'video.mp4'
        target=job/f'style-reference-{i}.jpg'
        subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(seconds),'-i',str(source),'-vf','scale=540:960','-frames:v','1','-y',str(target)],check=True,capture_output=True,timeout=20)
        draw.text((i*540+15,35),title,fill='white')
        with Image.open(target) as frame:board.paste(frame,(i*540,65))
    path=job/'style-reference-sheet.jpg';board.save(path,quality=94);paths.append(path)
    return paths

def perform():
    from generation_worker import preflight,manual_editorial,public_metadata
    from publication_service import controls
    from workflow_presentation import fresh_render,audio_digest,text_cache,visible_labels
    from workflow_native import implementation,enabled
    from workflow_readable import VERSION,sequence_for_display
    from autonomous_generation import Supervisor
    from history_data import timestamp
    from deepseek_runtime import Client
    from credit_repair import native_review_function
    state,job=c.paths('catarsis',BATCH,CHANNEL)
    auth_path=state/(NAME+'-auth.json');auth=c.read(auth_path);auth_sha=c.digest(auth_path)
    if auth.get('request_id')!=REQUEST_ID or auth.get('job_id')!=BATCH or auth.get('publication_allowed') is not False or auth.get('visual_reviews_max')!=1:
        raise RuntimeError('workflow_style_revision_auth_invalid')
    def guard():
        if (state/'STOP').exists():raise RuntimeError('generation_cancelled')
        if c.digest(auth_path)!=auth_sha or c.digest(state/'request.json')!=auth['request_sha256'] or controls()!=auth['controls'] or any(c.digest(Path(path))!=sha for path,sha in auth['sources'].items()):
            raise RuntimeError('workflow_style_revision_frozen_sources_changed')
        preflight()
    guard();item=auth['item']
    with (state/(NAME+'.claim')).open('x') as stream:stream.write(timestamp());stream.flush();os.fsync(stream.fileno())
    if c.tree(job)!=item['files'] or c.tree(c.ledger(job))!=item['ledger']:raise RuntimeError('workflow_style_revision_inputs_changed')
    archive=c.RUNTIME/'workflow-attempts/catarsis'/BATCH/NAME
    archive.mkdir(mode=0o700,parents=True,exist_ok=False)
    shutil.copytree(job,archive/'job');shutil.copytree(c.ledger(job),archive/'ledger')
    if c.tree(archive/'job')!=item['files'] or c.tree(archive/'ledger')!=item['ledger']:raise RuntimeError('workflow_style_revision_backup_failed')
    old_video=archive/'job/video.mp4';old_audio=audio_digest(old_video)
    review_root=c.RUNTIME/'workflow-style-reviews'/BATCH/NAME
    review_root.mkdir(mode=0o700,parents=True,exist_ok=False)
    c.write(review_root/'authorization.json',dict(original_job_id=BATCH,original_video_sha256=SOURCE_VIDEO,
        original_approval_sha256=SOURCE_APPROVAL,request_id=REQUEST_ID,maximum_visual_assessments=1,
        original_vision_claims_preserved=True,new_text_calls=0))
    task=c.read(state/'request.json');status=c.read(state/'status.json')
    sys.path.insert(0,'/home/videoagent/video-automation');import editorial as exported;import daily_core as core
    from helpers import daily
    editorial=implementation(exported);sys.path.insert(0,str(editorial.REPO))
    request_method=Client.request
    def no_new_text(*args,**kwargs):raise RuntimeError('workflow_style_revision_text_requests_forbidden')
    try:
        with daily.locked():
            Client.request=no_new_text
            status.update(state='running',error_code=None,updated_at=timestamp());c.write(state/'status.json',status)
            (job/'approval.json').unlink();(job/'quality-review-cache.json').unlink(missing_ok=True)
            project,plan=c.read(job/'project.json'),c.read(job/'editorial-plan.json')
            display=sequence_for_display(project['sequence'])
            if display!=item['display_sequence']:raise RuntimeError('workflow_style_revision_display_changed')
            with enabled(editorial,job,CHANNEL),manual_editorial(editorial,job,BATCH,CHANNEL,task['date'],guard,recovery=Supervisor(job,guard,attempt_namespace=NAME)):
                held=fresh_render(job,lambda:editorial.d.render_project(project,job))
            guard()
            remux=job/'style-revision-remux.mp4'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(job/'video.mp4'),'-i',str(old_video),'-map','0:v:0','-map','1:a:0','-c','copy','-map_metadata','-1','-map_chapters','-1','-movflags','+faststart',str(remux)],check=True,capture_output=True,timeout=60)
            if audio_digest(remux)!=old_audio:raise RuntimeError('workflow_style_revision_audio_changed')
            os.replace(remux,job/'video.mp4');held.unlink();(job/'workflow-prior-receipt.json').unlink(missing_ok=True)
            from catarsis_style import EVIDENCE
            proof=c.read(job/EVIDENCE);proof['video_sha256']=c.digest(job/'video.mp4');c.write(job/EVIDENCE,proof)
            for name in ('editorial-plan.json','sources.json','asset-credits.json','metadata.json','music-license-evidence.json','project.json','thumbnail.jpg'):
                if c.digest(job/name)!=item['files'][name]:raise RuntimeError('workflow_style_revision_factual_evidence_changed')
            if c.digest(text_cache(job))!=item['text_cache']['sha256']:raise RuntimeError('workflow_style_revision_text_cache_changed')
            c.write(job/'catarsis-typography-proof-v50.json',dict(version=VERSION,original_video_sha256=SOURCE_VIDEO,
                original_approval_preserved_in_archive=True,original_audio_payload_preserved=True,
                approved_text_and_media_unchanged=True,display_sequence=display,visual_reviews_max=1,
                visible_labels=visible_labels(job,project),text_ai_requests=0,
                reference_videos=['p3lxkEhl4LA','3B2FCQvm9bQ']))
            editorial.d.qa(job/'video.mp4',job,smoke=False)
            qa=c.read(job/'qa.json')
            if qa.get('technical_checks_passed') is not True or qa.get('sha256')!=c.digest(job/'video.mp4'):raise RuntimeError('workflow_style_revision_native_qa_failed')
            receipt=c.read(job/'receipt.json');receipt['video_sha256']=qa['sha256'];c.write(job/'receipt.json',receipt)
            extras=sample_sheets(job,display)
            old_qa=editorial.extended_qa
            def extended(folder,p):
                return old_qa(folder,dict(p,sequence=display))+extras
            editorial.extended_qa=extended
            try:
                with enabled(editorial,job,CHANNEL),revision_vision(job,review_root),manual_editorial(editorial,job,BATCH,CHANNEL,task['date'],guard,recovery=Supervisor(job,guard,attempt_namespace=NAME)):
                    native_review_function(editorial)(job,project,plan,CHANNEL,task['date'],'production',False)
            finally:editorial.extended_qa=old_qa
            if c.tree(c.ledger(job))!=item['ledger']:raise RuntimeError('workflow_style_revision_original_ledger_changed')
            if len(list(review_root.glob('vision-*.claimed')))!=1:raise RuntimeError('workflow_style_revision_actual_assessment_missing')
            core.approval(job,CHANNEL,task['date'])
            files={}
            for kind,name in (('video','video.mp4'),('thumbnail','thumbnail.jpg')):
                p=job/name;info=p.stat();files[kind]=dict(size=info.st_size,mtime_ns=info.st_mtime_ns,ctime_ns=info.st_ctime_ns,sha256=c.digest(p))
            status['channels'][CHANNEL]=dict(state='ready',error_code=None,files=files,
                metadata=public_metadata(c.read(job/'metadata.json')),approval_sha256=c.digest(job/'approval.json'))
            status.update(state='ready',error_code=None)
    except Exception as exc:
        from generation_service import safe_error
        import traceback
        code=safe_error(exc);status.update(state='blocked',error_code=code)
        status['channels'][CHANNEL]=dict(state='blocked',error_code=code,diagnostic=code)
        c.write(job/'blocked.json',dict(reason=code,phase=NAME,detail=dict(type=type(exc).__name__,message=c.clean(exc,500),
            location=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-5:]])))
    finally:
        Client.request=request_method
        status['updated_at']=timestamp();c.write(state/'status.json',status)
        tracking=c.read(state/'workflow.json');tracking['style_revision']['state']=status['state'];c.write(state/'workflow.json',tracking)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--perform',action='store_true',required=True);parser.parse_args()
    os.umask(0o077);perform()
