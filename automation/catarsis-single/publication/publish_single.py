#!/usr/bin/env python3
"""Publish one exact approved Facts Short on YT/FB/IG; never generates media.

The pair-only broker is not used or weakened. An explicit, immutable single
authorization replaces the daily/pair entry gate only. Native identity, music,
approval, upload-once, transport recovery and publication-readback checks remain.
"""
import argparse
import contextlib
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

CHANNEL='stunning-facts-of-history'
PLATFORMS=('youtube','facebook','instagram')
BATCH='414d2230218342febf4d42846e71c3e6'
VIDEO='4ead29ff752aa469f28af6d5c172798fe2e7dcaf9376c2d8740a26f7faa02914'
APPROVAL='d11cebb555eb09a9890c6a688c6c90c49550f8526ff529242956279a467d76d3'
REQUEST='publish-curie-wwi-facts-yt-fb-ig-20261107-v1'
ROOT=Path('/opt/video-agent-mcp')
AUTOMATION=Path('/home/videoagent/video-automation')
GENERATION=Path('/var/lib/video-agent-prepare/catarsis')
STATE=Path('/var/lib/video-agent-prepare/catarsis-single-publication')
JOBS=AUTOMATION/'runtime/manual-catarsis'
PINNED=('job.json','metadata.json','approval.json','video.mp4','thumbnail.jpg')
WORKER_SHA='500fbeb3ce2bbb40c9c184e6e26782f905b8f765dce9003cc6490b1eddfdf5d6'

def require(value,code):
    if not value:raise RuntimeError(code)

def safe(path):
    path=Path(path)
    require(not any(p.is_symlink() for p in (path,*path.parents)),'single_publication_symlink_rejected')
    return path

def sha(path):
    h=hashlib.sha256()
    with safe(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def read(path):
    path=safe(path);require(path.stat().st_size<=2*1024*1024,'single_publication_record_too_large')
    return json.loads(path.read_text())

def write(path,data):
    path=safe(path);path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.single-publication-')
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600);json.dump(data,stream,ensure_ascii=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def now():return datetime.now(timezone.utc)

def prepared(core,generation=GENERATION,jobs=JOBS):
    task,status=(read(generation/BATCH/name) for name in ('request.json','status.json'))
    require(task.get('batch_id')==BATCH and task.get('operation')=='generate_single_only'
        and task.get('requested_channels')==[CHANNEL] and set(task.get('topics',{}))=={CHANNEL}
        and task.get('publication_allowed') is False and status.get('state')=='ready',
        'single_publication_exact_ready_channel_required')
    require(not (generation/BATCH/'superseded.json').exists(),'single_publication_superseded')
    folder=safe(jobs/BATCH/CHANNEL);row=status.get('channels',{}).get(CHANNEL,{})
    pins={name:sha(folder/name) for name in PINNED}
    require(row.get('state')=='ready' and pins['approval.json']==APPROVAL==row.get('approval_sha256')
        and pins['video.mp4']==VIDEO==row.get('files',{}).get('video',{}).get('sha256')
        and pins['thumbnail.jpg']==row.get('files',{}).get('thumbnail',{}).get('sha256'),
        'single_publication_approved_artifact_changed')
    expected=dict(date=task['date'],channel=CHANNEL,topic=task['topics'][CHANNEL],scope='production',
                  manual_batch=BATCH,generation_only=True,publication_allowed=False)
    require(read(folder/'job.json')==expected,'single_publication_job_binding_changed')
    meta=read(folder/'metadata.json')
    require(meta.get('marker')=='VO:manual:'+BATCH+':'+CHANNEL,'single_publication_metadata_binding_changed')
    core.approval(folder,CHANNEL,task['date'])
    return dict(batch_id=BATCH,date=task['date'],channels=[CHANNEL],platforms=list(PLATFORMS),
        generation_request_sha256=sha(generation/BATCH/'request.json'),pins=pins)

def scoped_receipts(native,jobs=JOBS):
    # Read the original receipts, including previously created IDs/intents. The
    # unselected channel never becomes part of this publication authorization.
    result=native.public_receipts(jobs,BATCH)
    rows=result['channels'][CHANNEL]
    require(set(rows)==set(PLATFORMS),'single_publication_receipt_scope_changed')
    return dict(complete=all(v.get('state')=='published' for v in rows.values()),channels={CHANNEL:rows})

def selected_run(publisher,controller):
    """Native Publisher.run, with explicit single auth instead of its pair gate."""
    remote,core=controller.remote,controller.core
    require(publisher.job.get('channel')==CHANNEL and publisher.directory==controller.jobs/BATCH/CHANNEL,
            'single_publication_channel_changed')
    controller.guard()
    core.approval(publisher.directory,CHANNEL,publisher.job['date'])
    music=remote.publish_preflight(publisher.directory,CHANNEL,dry=publisher.dry)
    service,token,identity=remote.identities(CHANNEL)
    if publisher.dry:
        return dict(dry_run=True,profile=CHANNEL,identity_reads=True,platforms=list(PLATFORMS),
            remote_mutations=0,metadata_checked=True,music_check=music)
    for network in PLATFORMS:
        record=core.receipt(publisher.directory)['platforms'].get(network,{})
        if record.get('state')=='published':continue
        try:
            getattr(publisher,network)(service if network=='youtube' else token if network=='facebook' else identity)
        except Exception as exc:
            code=str(exc) if isinstance(exc,core.Blocked) else 'api_error_reconciliation_required'
            publisher.mark(network,last_error=type(exc).__name__,reason_code=code)
    return core.receipt(publisher.directory)

class Controller:
    def __init__(self,core,remote,native,auth,auth_path,*,jobs=JOBS,generation=GENERATION,state=STATE,clock=now):
        self.core,self.remote,self.native=core,remote,native
        self.jobs,self.generation,self.state=map(Path,(jobs,generation,state))
        self.auth,self.auth_path,self.clock=auth,Path(auth_path),clock
        self.auth_sha=sha(auth_path)

    def guard(self):
        auth=self.auth
        require(sha(self.auth_path)==self.auth_sha,'single_publication_authorization_changed')
        require(auth.get('operation')=='publish_prepared_single' and auth.get('request_id')==REQUEST
            and auth.get('channels')==[CHANNEL] and auth.get('platforms')==list(PLATFORMS)
            and auth.get('include_tiktok_drafts') is False,'single_publication_scope_changed')
        created,expires=(datetime.fromisoformat(auth[k]) for k in ('created_at','expires_at'))
        require(created.tzinfo is not None and expires.tzinfo is not None
            and created<=self.clock()<expires and timedelta(0)<expires-created<=timedelta(hours=2),
            'single_publication_authorization_expired')
        require(not (self.state/BATCH/'STOP').exists(),'publication_cancelled')
        require(self.native.controls()==auth['controls'],'automation_controls_changed')
        require(sha(__file__)==auth['publisher_sha256'],'single_publication_publisher_changed')
        expected=set(self.native.CONNECTOR_SOURCES)|{'instagram_recovery.py','publication_transport.py'}
        require(set(auth['connector_sha256'])==expected,'single_publication_source_binding_missing')
        for name,digest in auth['connector_sha256'].items():
            require(sha(ROOT/name)==digest,'single_publication_connector_changed')
        from generation_worker import preflight
        preflight()
        require(prepared(self.core,self.generation,self.jobs)==auth['manifest'],
                'single_publication_approved_inputs_changed')

    def job(self):
        folder=self.jobs/BATCH/CHANNEL
        self.core.approval(folder,CHANNEL,self.auth['manifest']['date'])
        return folder,read(folder/'job.json')

    def receipts(self):return scoped_receipts(self.native,self.jobs)

    def publisher(self):
        controller=self;remote=self.remote
        class SinglePublisher(remote.Publisher):
            def run(publisher):return selected_run(publisher,controller)
            def youtube(publisher,service):
                if publisher.meta.get('public_marker') is False:
                    record=controller.core.receipt(publisher.directory).get('platforms',{}).get('youtube',{})
                    transport=publisher.directory/'.transport.json'
                    saved=read(transport).get('youtube',{}) if transport.exists() else {}
                    if record.get('intent') and not record.get('video_id') and not saved.get('session_uri'):
                        raise controller.core.Blocked('youtube_create_ambiguous_reconcile_before_retry')
                return super().youtube(service)
            def offset_upload(publisher,network,url,token,record,status_reader):
                if network=='facebook':
                    from publication_transport import facebook_offsets
                    return facebook_offsets(publisher,url,token,record,status_reader,controller)
                return super().offset_upload(network,url,token,record,status_reader)
            def instagram(publisher,identity):
                from instagram_recovery import publish_or_recover
                return publish_or_recover(publisher,identity,controller,lambda:super(SinglePublisher,publisher).instagram(identity))
            def mutate(publisher,callback,*args,**kwargs):
                require(not publisher.dry,'dry_run_mutation_rejected')
                controller.guard();folder,job=controller.job()
                require(publisher.directory==folder and publisher.job==job,'single_publication_job_changed')
                return callback(*args,**kwargs)
        return SinglePublisher

    def run(self):
        if self.receipts()['complete']:return self.receipts()
        self.guard();folder,job=self.job()
        from platform_rules import preflight
        preflight(folder)
        policy=read(AUTOMATION/'activation-package-20261019/activation-policy.json')
        publisher=self.publisher()
        dry=publisher(policy,folder,job,dry=True).run()
        require(dry.get('dry_run') is True and dry.get('profile')==CHANNEL and dry.get('identity_reads') is True
            and dry.get('remote_mutations')==0 and set(dry.get('platforms',[]))==set(PLATFORMS),
            'single_publication_identity_preflight_incomplete')
        self.remote.publish_preflight(folder,CHANNEL,dry=False)
        publisher(policy,folder,job).run()
        waiting={'youtube_public_propagation_pending','facebook_transfer_reconciliation_pending','youtube_indexing_pending',
            'youtube_processing_pending_or_failed','instagram_upload_pending_reconciliation','instagram_processing_pending',
            'instagram_verification_pending','instagram_publish_pending_reconcile_before_retry','facebook_publication_pending',
            'facebook_finish_pending_reconcile_before_retry','instagram_url_processing_pending','instagram_url_verification_pending',
            'instagram_url_publish_pending_reconciliation'}
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            result=self.receipts()
            if result['complete']:return result
            pending=any(row.get('state')!='published' and row.get('error_code') in waiting
                        for row in result['channels'][CHANNEL].values())
            # A previously observed Facebook 400 may follow an accepted finish.
            # The native method reads this exact ID first and refuses a second
            # finish when finish_intent is set; reconciling cannot create a Reel.
            fb=self.core.receipt(folder)['platforms'].get('facebook',{})
            pending=pending or (fb.get('state')!='published' and fb.get('finish_intent') is True
                and isinstance(fb.get('video_id'),str) and re.fullmatch(r'\d{1,30}',fb['video_id']) is not None
                and fb.get('reason_code')=='graph_http_400_code_100')
            if not pending:return result
            self.guard();time.sleep(5);publisher(policy,folder,job).run()
        return self.receipts()

def initialize():
    require(sha(ROOT/'publication_worker.py')==WORKER_SHA,'single_publication_native_worker_changed')
    sys.path.insert(0,str(ROOT))
    from generation_worker import preflight
    preflight();sys.path.insert(0,str(AUTOMATION))
    import daily_core as core,daily_remote as remote,publication_service as native
    require(Path(core.__file__).resolve()==AUTOMATION/'daily_core.py'
        and Path(remote.__file__).resolve()==AUTOMATION/'daily_remote.py','unexpected_publication_runtime_import')
    return core,remote,native

def execute(publish=False):
    core,remote,native=initialize();manifest=prepared(core)
    if not publish:return dict(state='checked',batch_id=BATCH,channel=CHANNEL,platforms=list(PLATFORMS),
        video_sha256=VIDEO,approval_sha256=APPROVAL,publication='not_requested',ai_requests=0)
    current=scoped_receipts(native)
    if current['complete']:return dict(state='completed',batch_id=BATCH,**current)
    folder=STATE/BATCH;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    auth_path=folder/(REQUEST+'.json');claim=folder/(REQUEST+'.claimed')
    # Repeating the same command is a transport retry, never a new upload grant.
    if claim.exists():return dict(state=read(folder/'status.json')['state'],batch_id=BATCH,**current,
        note='Existing attempt retained. Read publication status; do not start another upload.')
    if auth_path.exists():auth=read(auth_path)
    else:
        started=now();auth=dict(operation='publish_prepared_single',request_id=REQUEST,
            channels=[CHANNEL],platforms=list(PLATFORMS),include_tiktok_drafts=False,
            created_at=started.isoformat(),expires_at=(started+timedelta(hours=2)).isoformat(),
            controls=native.controls(),manifest=manifest,publisher_sha256=sha(__file__),
            connector_sha256={name:sha(ROOT/name) for name in set(native.CONNECTOR_SOURCES)|{'instagram_recovery.py','publication_transport.py'}})
        write(auth_path,auth)
    controller=Controller(core,remote,native,auth,auth_path)
    from helpers import daily
    with daily.locked():
        controller.guard()
        with claim.open('x') as stream:
            os.fchmod(stream.fileno(),0o600);stream.write(now().isoformat());stream.flush();os.fsync(stream.fileno())
        state=dict(state='publishing',request_id=REQUEST,channels=[CHANNEL],platforms=list(PLATFORMS),
            authorization_expires_at=auth['expires_at'],updated_at=now().isoformat(),include_tiktok_drafts=False)
        write(folder/'status.json',state)
        try:
            result=controller.run();state.update(state='completed' if result['complete'] else 'pending',updated_at=now().isoformat())
        except Exception as exc:
            from generation_service import safe_error
            state.update(state='blocked',error_code=safe_error(exc),updated_at=now().isoformat())
            write(folder/'status.json',state);raise
        write(folder/'status.json',state)
    return dict(state=state['state'],batch_id=BATCH,ai_requests=0,**result)

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--inspect',action='store_true');action.add_argument('--publish',action='store_true')
    args=parser.parse_args()
    with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):
        try:result=execute(args.publish)
        except Exception as exc:
            code=str(exc).split(':',1)[0]
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,120}',code):code='single_publication_'+type(exc).__name__
            result=dict(state='blocked',error_code=code,batch_id=BATCH,ai_requests=0)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result.get('state') in ('completed','checked') else 2

if __name__=='__main__':raise SystemExit(main())
