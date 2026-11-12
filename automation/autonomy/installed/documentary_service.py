"""Durable manual documentary requests and read-only approved media."""
import base64
import os
from pathlib import Path
import signal
import stat
import subprocess
import threading
import time
import uuid
from documentary_common import *

OPERATIONS={'documentary_revise_score','documentary_resume_assets','documentary_resume_sources','documentary_resume_history','documentary_correct_context','documentary_resume_shots','documentary_start','documentary_status','documentary_cancel','documentary_media_meta','documentary_media_read','documentary_probe','documentary_resume_length','documentary_resume_metadata','documentary_resume_media','documentary_resume_downloads','documentary_resume_autocorrection','documentary_resume_compact','documentary_resume_layout','documentary_resume_visual_quota','documentary_revise_audiovisual','documentary_correct_labels','documentary_revise_catarsis'}
TERMINAL={'ready','blocked','cancelled','interrupted'}

def denied(code):return dict(state='blocked',error_code=code,publication_allowed=False)

class DocumentaryBroker:
    def __init__(self,parent,state=STATE,jobs=JOBS,launch=None,executor=None):
        self.parent=parent;self.state=Path(state);self.jobs=Path(jobs)
        self.active={};self.lock=threading.RLock()
        self.launch=launch or (lambda f:threading.Thread(target=f,daemon=True).start())
        self.executor=executor or self.execute

    def handle(self,r):
        if not isinstance(r,dict):return denied('invalid_documentary_request')
        try:
            op=r['operation']
            schemas={'documentary_revise_score':{'operation','job_id'},'documentary_resume_assets':{'operation','job_id'},'documentary_resume_sources':{'operation','job_id'},'documentary_resume_history':{'operation','job_id'},'documentary_correct_context':{'operation','job_id'},'documentary_resume_shots':{'operation','job_id'},'documentary_revise_catarsis':{'operation','job_id'},'documentary_correct_labels':{'operation','job_id'},'documentary_revise_audiovisual':{'operation','job_id'},'documentary_resume_visual_quota':{'operation','job_id'},'documentary_resume_layout':{'operation','job_id'},'documentary_resume_compact':{'operation','job_id'},'documentary_resume_autocorrection':{'operation','job_id'},'documentary_resume_downloads':{'operation','job_id'},'documentary_resume_media':{'operation','job_id'},'documentary_resume_metadata':{'operation','job_id'},'documentary_resume_length':{'operation','job_id'},'documentary_probe':{'operation'},'documentary_start':{'operation','request_id','channel','topic','minutes'},
                'documentary_status':{'operation','job_id'},'documentary_cancel':{'operation','job_id'},
                'documentary_media_meta':{'operation','job_id','kind'},
                'documentary_media_read':{'operation','job_id','kind','offset','length'}}
            if op not in schemas or set(r)!=schemas[op]:raise Failure('invalid_documentary_request')
            with self.lock:
                if op=='documentary_probe':
                    if self.active or self.parent.generation.active or self.parent.publication.active:
                        return denied('another_manual_operation_is_running')
                    p=subprocess.run([PYTHON,'-B',str(ROOT/'documentary_worker.py'),'--probe'],
                        capture_output=True,text=True,timeout=45)
                    if p.returncode:raise Failure('documentary_dependency_probe_failed')
                    return json.loads(p.stdout)
                if op=='documentary_start':return self.start({k:v for k,v in r.items() if k!='operation'})
                job=r['job_id']
                if not valid_id(job):raise Failure('invalid_documentary_job_id')
                if op=='documentary_status':return self.status(job)
                if op=='documentary_revise_score':
                    from documentary_music_revision import start
                    return start(self,job)
                if op=='documentary_resume_assets':
                    from documentary_asset_repair import start
                    return start(self,job)
                if op=='documentary_resume_sources':
                    from documentary_source_repair import start
                    return start(self,job)
                if op=='documentary_resume_history':
                    from documentary_history_repair import start
                    return start(self,job)
                if op=='documentary_correct_context':
                    from documentary_context_fix import start
                    return start(self,job)
                if op=='documentary_resume_shots':
                    from documentary_catarsis_recovery import start
                    return start(self,job)
                if op=='documentary_revise_catarsis':
                    from documentary_catarsis_revision import start
                    return start(self,job)
                if op=='documentary_correct_labels':
                    from documentary_labels import start
                    return start(self,job)
                if op=='documentary_revise_audiovisual':
                    from documentary_av_revision import start
                    return start(self,job)
                if op=='documentary_resume_visual_quota':
                    from documentary_visual_recovery import start
                    return start(self,job)
                if op=='documentary_resume_layout':
                    from documentary_layout_repair import start
                    return start(self,job)
                if op=='documentary_resume_compact':
                    from documentary_compact_repair import start
                    return start(self,job)
                if op=='documentary_resume_autocorrection':
                    from documentary_autocorrection_repair import start
                    return start(self,job)
                if op=='documentary_resume_downloads':
                    from documentary_download_repair import start
                    return start(self,job)
                if op=='documentary_resume_media':
                    from documentary_media_repair import start
                    return start(self,job)
                if op=='documentary_resume_metadata':
                    from documentary_metadata_repair import start
                    return start(self,job)
                if op=='documentary_resume_length':
                    from documentary_length_repair import start
                    return start(self,job)
                if op=='documentary_cancel':
                    value=self.status(job)
                    if job in self.active:
                        save(self.state/job/'STOP',dict(at=now()));value['cancellation_requested']=True
                    return value
                return self.media(job,r['kind'],r.get('offset'),r.get('length'))
        except Exception as exc:return denied(error(exc))

    def start(self,r):
        r=request(r);self.state.mkdir(mode=0o700,parents=True,exist_ok=True)
        index_path=self.state/'index.json';index=read(index_path) if index_path.exists() else {}
        key=r['request_id']
        if key in index:
            old=read(self.state/index[key]/'request.json')
            if any(old.get(k)!=v for k,v in r.items()):return denied('documentary_request_id_conflict')
            return self.status(index[key])
        if self.active or self.parent.generation.active or self.parent.publication.active or self.parent.active:
            return denied('another_manual_operation_is_running')
        job=uuid.uuid4().hex;folder=self.state/job;folder.mkdir(mode=0o700)
        save(folder/'request.json',dict(r,job_id=job,publication_allowed=False,created_at=now(),horizontal_style='documentary-catarsis-v31',thumbnail_mode='manual'))
        value=dict(state='accepted',job_id=job,version=VERSION,channel=r['channel'],topic=r['topic'],
             minutes=r['minutes'],language='en',format='16:9',narration=True,phase='queued',
             quality_approved=False,publication_allowed=False,error_code=None,created_at=now(),updated_at=now(),files={})
        save(folder/'status.json',value);index[key]=job;save(index_path,index)
        self.active[job]=True
        try:self.launch(lambda:self.work(job))
        except Exception:
            self.active.pop(job,None);value.update(state='blocked',error_code='documentary_worker_launch_failed');save(folder/'status.json',value)
        return self.status(job)

    def status(self,job):
        path=self.state/job/'status.json'
        if not path.exists():return dict(state='not_requested',job_id=job,publication_allowed=False)
        value=read(path)
        from documentary_transport import summary
        value['download_diagnostics']=summary(self.jobs/job)
        score=self.jobs/job/'music-revision-v43.json'
        if score.is_file():
            record=read(score)
            value['music_only_revision']={k:record[k] for k in ('version','revision_of','new_ai_requests','music_profile','music_recordings','audio','music_bed_audio') if k in record}
            value['music_only_revision']['unchanged_encoded_picture']=record['video_packet_sha256']==record['parent_video_packet_sha256']
        correction=self.jobs/job/'asset-normalization-v42.json'
        if correction.is_file():
            record=read(correction)
            value['asset_format_correction']=dict(version='local-asset-format-v42',
                corrected_fields=[dict(asset=c['asset'],field=c['field']) for c in record.get('changes',[])],
                narration_and_research_unchanged=True,ai_requests=0)
        if (self.jobs/job/'factual-sources-v41.json').is_file():
            from documentary_sources import diagnostics
            value['factual_sources']=diagnostics(self.jobs/job)
        failure=self.jobs/job/'failure-diagnostic-v32.json'
        if value.get('state')=='blocked' and failure.is_file():
            detail=read(failure)
            value['worker_diagnostic']={k:detail.get(k) for k in ('exception','phase','code','at','location')}
        resolution=self.jobs/job/'media-decode-resolution-v32.json'
        if resolution.is_file():
            detail=read(resolution)
            value['media_decode_recovery']=dict(unreadable_assets=len(detail['invalid_assets']),
                replaced_shots=len(detail['replacements']),preserved_shots=detail['completed_shots_preserved'],
                ai_requests=0,downloads=0)
        handoffs=[]
        for path in sorted((self.jobs/job).glob('editorial-plan-auto*-v25-*-events.jsonl')):
            if path.stat().st_size>1024*1024:continue
            for line in path.read_text().splitlines():
                try:event=json.loads(line)
                except ValueError:continue
                if event.get('type')=='provider.handoff':
                    handoffs.append({k:event[k] for k in ('output','finish_reason','content_type','content_bytes','requested_max_output_tokens') if k in event})
        if handoffs:value['correction_handoffs']=handoffs
        quality_path=self.jobs/job/'review.json'
        if quality_path.is_file():
            recorded=read(quality_path)
            value['quality_review']={k:recorded[k] for k in ('approved','checks','findings','suggestions','assessment_sources','resolution') if k in recorded}
            if value.get('repair_id')=='short-context-captions-v33' and value.get('state') in ('accepted','running'):
                value['quality_review']['historical']=True
        layout_path=self.jobs/job/'visual-layout-proof-v26.json'
        if layout_path.is_file():
            layout_value=read(layout_path)
            value['visual_layout_repair']={k:layout_value[k] for k in ('version','changed_segments','deepseek_requests','completed_at') if k in layout_value}
        av=self.jobs/job/'audiovisual-revision-v28.json'
        if av.is_file():
            v=read(av)
            value['audiovisual_revision']={k:v[k] for k in ('version','revision_of','clip_shots','music','deepseek_requests','completed_at') if k in v}
        style=self.jobs/job/'catarsis-proof-v31.json'
        if style.is_file():
            proof=read(style);qa=read(self.jobs/job/'qa.json')
            value['horizontal_style']={k:qa.get(k) for k in ('style','shot_count','clip_shots','unique_visual_assets','mean_shot_seconds','longest_shot_seconds','music_arc')}
            value['horizontal_style'].update(music_recordings=proof['music_recordings'],text_ai_requests=0,thumbnail_mode='manual')
            value['thumbnail_mode']='manual'
        correction=self.jobs/job/'context-correction-proof-v33.json'
        if correction.is_file():
            record=read(correction)
            value['context_caption_correction']=dict(changed_source_shots=len(record['changed_source_shots']),
                checked_caption_frames=len(record['pixel_checks']),new_ai_requests=0,
                audio_payload_preserved=record['before_audio_sha256']==record['after_audio_sha256'])
        review_path=self.jobs/job/'documentary-text-review.json'
        if review_path.is_file():
            recorded=read(review_path)
            value['text_review_recorded']={k:recorded[k] for k in ('approved','checks','findings') if k in recorded}
        resolution=self.jobs/job/'autocorrection-resolution-v24.json'
        if resolution.is_file():
            fixed=read(resolution)
            value['correction_resolution']={k:fixed[k] for k in ('version','changed_segments','completed_at') if k in fixed}
            if 'text_review_recorded' in value:
                value['text_review_recorded']['historical']=True
                value['text_review_recorded']['notice']='Original review retained; see correction_resolution and current job state for the effective outcome.'
        if value['state'] in ('accepted','running') and job not in self.active:
            value.update(state='interrupted',error_code='documentary_execution_interrupted_no_retry')
        if value.get('state')=='ready':
            approval=self.jobs/job/'approval.json'
            if sha(approval)!=value.get('approval_sha256'):raise Failure('documentary_approval_changed')
            if sha(self.jobs/job/'metadata.json')!=read(approval)['metadata_sha256']:
                raise Failure('documentary_metadata_changed')
            for kind,expected in value.get('files',{}).items():
                if kind not in MEDIA_KINDS:raise Failure('invalid_documentary_media_kind')
                info=safe_path(self.jobs/job/MEDIA_KINDS[kind][0]).stat()
                if (not stat.S_ISREG(info.st_mode) or info.st_size!=expected['size'] or
                    info.st_mtime_ns!=expected['mtime_ns'] or info.st_ctime_ns!=expected['ctime_ns']):
                    raise Failure('documentary_media_changed_after_review')
        return value

    def execute(self,job,length_repair=False,metadata_repair=False,media_repair=False,download_repair=False,autocorrection=False,compact=False,layout=False,visual_quota=False,audiovisual=False,labels=False,catarsis=False,shot_recovery=False,context_fix=False,history_repair=False,source_repair=False,asset_repair=False,score_revision=False):
        command=[PYTHON,'-B',str(ROOT/'documentary_worker.py'),job]
        if sum((length_repair,metadata_repair,media_repair,download_repair,autocorrection,compact,layout,visual_quota,audiovisual,labels,catarsis,shot_recovery,context_fix,history_repair,source_repair,asset_repair,score_revision))>1:raise Failure('invalid_documentary_continuation')
        if length_repair:command+=['--resume-length']
        if metadata_repair:command+=['--resume-metadata']
        if media_repair:command+=['--resume-media']
        if download_repair:command+=['--resume-downloads']
        if autocorrection:command+=['--resume-autocorrection']
        if compact:command+=['--resume-compact']
        if layout:command+=['--resume-layout']
        if visual_quota:command+=['--resume-visual-quota']
        if audiovisual:command+=['--revise-audiovisual']
        if labels:command+=['--correct-labels']
        if catarsis:command+=['--revise-catarsis']
        if shot_recovery:command+=['--resume-shots']
        if context_fix:command+=['--correct-context']
        if history_repair:command+=['--resume-history']
        if source_repair:command+=['--resume-sources']
        if asset_repair:command+=['--resume-assets']
        if score_revision:command+=['--revise-score']
        with subprocess.Popen(command,stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True) as process:
            deadline=time.monotonic()+10800
            while process.poll() is None:
                stopped=(self.state/job/'STOP').exists()
                if stopped or time.monotonic()>deadline:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    raise Failure('documentary_cancelled' if stopped else 'documentary_timeout')
                time.sleep(.5)
            if process.returncode:
                value=read(self.state/job/'status.json')
                raise Failure(value.get('error_code') or 'documentary_worker_failed')

    def work(self,job,length_repair=False,metadata_repair=False,media_repair=False,download_repair=False,autocorrection=False,compact=False,layout=False,visual_quota=False,audiovisual=False,labels=False,catarsis=False,shot_recovery=False,context_fix=False,history_repair=False,source_repair=False,asset_repair=False,score_revision=False):
        try:
            if score_revision:self.execute(job,score_revision=True)
            elif asset_repair:self.execute(job,asset_repair=True)
            elif source_repair:self.execute(job,source_repair=True)
            elif history_repair:self.execute(job,history_repair=True)
            elif context_fix:self.execute(job,context_fix=True)
            elif shot_recovery:self.execute(job,shot_recovery=True)
            elif catarsis:self.execute(job,catarsis=True)
            elif labels:self.execute(job,labels=True)
            elif audiovisual:self.execute(job,audiovisual=True)
            elif visual_quota:self.execute(job,visual_quota=True)
            elif layout:self.execute(job,layout=True)
            elif compact:self.execute(job,compact=True)
            elif autocorrection:self.execute(job,autocorrection=True)
            elif download_repair:self.execute(job,download_repair=True)
            elif media_repair:self.execute(job,media_repair=True)
            elif metadata_repair:self.execute(job,metadata_repair=True)
            elif length_repair:self.execute(job,length_repair=True)
            else:self.executor(job)
        except Exception as exc:
            value=read(self.state/job/'status.json');code=error(exc)
            value.update(state='cancelled' if code=='documentary_cancelled' else 'blocked',error_code=code,updated_at=now())
            save(self.state/job/'status.json',value)
        finally:
            with self.lock:self.active.pop(job,None)

    def media(self,job,kind,offset,length):
        if kind not in MEDIA_KINDS:raise Failure('invalid_documentary_media_kind')
        value=self.status(job)
        if value['state']!='ready' or not value.get('quality_approved'):raise Failure('documentary_media_not_ready')
        if kind not in value['files']:raise Failure('documentary_media_not_ready')
        expected=value['files'][kind];path=safe_path(self.jobs/job/MEDIA_KINDS[kind][0])
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            info=os.fstat(f.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size!=expected['size'] or
                info.st_mtime_ns!=expected['mtime_ns'] or info.st_ctime_ns!=expected['ctime_ns']):
                raise Failure('documentary_media_changed_after_review')
            result=dict(state='ready',size=info.st_size,sha256=expected['sha256'],content_type=MEDIA_KINDS[kind][1],filename=MEDIA_KINDS[kind][0])
            if offset is None and length is None:return result
            if type(offset) is not int or type(length) is not int or not 0<=offset<info.st_size or not 1<=length<=262144:
                raise Failure('invalid_documentary_media_range')
            f.seek(offset);result['data']=base64.b64encode(f.read(length)).decode();return result

def attach(parent):
    parent.documentary=DocumentaryBroker(parent)
    import workflow_service
    workflow_service.bind_documentary(parent)
    original=parent.handle
    def handle(r):
        op=r.get('operation') if isinstance(r,dict) else None
        if workflow_service.guard_operation(op):return denied('workflow_deployment_in_progress')
        if op in OPERATIONS:return parent.documentary.handle(r)
        if op=='manual_activity':
            value=original(r)
            value['documentary_active']=bool(parent.documentary.active)
            if parent.documentary.active:value.update(state='running',generation_active=True)
            return value
        if parent.documentary.active and op in {'generation_start','generation_start_single','generation_revise_style','publication_start','request_today'}:
            return denied('another_manual_operation_is_running')
        return original(r)
    parent.handle=handle
