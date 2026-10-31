"""Receive reviewed chat video packages. Receiving never publishes or invokes AI."""
from __future__ import annotations
import argparse,contextlib,ctypes,datetime as dt,errno,hashlib,hmac,json,math,os,secrets,shutil,stat,subprocess,tempfile,zipfile
from fractions import Fraction
from pathlib import Path
import chat_package as package

ROOT=Path('/home/videoagent/video-automation')
KEY_NAME='.chat-acceptance-key'
RECEIPT_NAME='.chat-import.json'
ACCEPTANCE_SCHEMA='video-agent.chat-acceptance.v1'
AUTH_NAME='.chat-publication-authorization.json'

def signed(payload):
    return {'payload':payload,'signature':hmac.new(key(),package.canonical(payload),hashlib.sha256).hexdigest()}

def verified(record):
    payload=record.get('payload');signature=record.get('signature')
    package.require(isinstance(payload,dict) and isinstance(signature,str),'signed_record_missing')
    package.require(hmac.compare_digest(hmac.new(key(),package.canonical(payload),hashlib.sha256).hexdigest(),signature),'signed_record_signature_mismatch')
    return payload

def require_publication_authorization(directory,job):
    import daily_core as c
    directory=Path(directory)
    trace=c.load(directory/'vision-evidence.json')
    if trace.get('review_origin')!='codex_chat':return
    try:
        package.require((directory/AUTH_NAME).is_file(),'chat_publication_not_authorized')
        payload=verified(c.load(directory/AUTH_NAME))
        package.require(payload.get('schema')=='video-agent.chat-publication.v1','chat_publication_schema_invalid')
        for field in ('channel','date','request_id'):
            package.require(payload.get(field)==job.get(field),'chat_publication_job_mismatch')
        package.require(payload.get('approval_sha256')==c.sha(directory/'approval.json'),'chat_publication_approval_mismatch')
        expires=dt.datetime.fromisoformat(payload['expires_at'])
        package.require(expires.tzinfo is not None and c.now()<=expires,'chat_publication_authorization_expired')
    except package.InvalidPackage as exc:raise c.Blocked(str(exc)) from None

def runtime():
    import daily_core as c
    package.require(Path(c.__file__).resolve()==ROOT/'daily_core.py' and c.ROOT.resolve()==ROOT,'unexpected_runtime_root')
    package.require(tuple(c.CHANNELS)==package.CHANNELS,'unexpected_channel_scope')
    return c

def gate(c):
    production=ROOT/'runtime/production'
    mode=c.load(production/'generation-mode.json')
    package.require(mode.get('generation')=='on_demand_codex_chat' and mode.get('vps_generation')=='disabled','chat_generation_mode_required')
    ready=c.load(production/'readiness.json')
    package.require(isinstance(ready.get('checks'),dict) and ready['checks'] and all(v is True for v in ready['checks'].values()),'readiness_not_passed')
    hashes=ready.get('code_sha256')
    package.require(isinstance(hashes,dict) and {'daily_core.py','chat_receiver.py','chat_package.py'}<=hashes.keys(),'chat_receiver_not_validated')
    for name,value in hashes.items():
        path=(ROOT/name).resolve()
        package.require(path.is_relative_to(ROOT) and c.sha(path)==value,'protected_source_changed')
    return ready

def key():
    path=ROOT/'runtime/production'/KEY_NAME
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(descriptor)
        package.require(stat.S_ISREG(info.st_mode) and not info.st_mode&0o077 and info.st_uid==os.geteuid() and info.st_size==32,'acceptance_key_permissions_invalid')
        value=os.read(descriptor,33)
        package.require(len(value)==32,'acceptance_key_invalid')
        return value
    finally:os.close(descriptor)

def destination(c,channel,date):
    package.require(channel in package.CHANNELS,'channel_not_allowed')
    package.require(isinstance(date,str) and dt.date.fromisoformat(date).isoformat()==date,'invalid_job_date')
    target=ROOT/'runtime/production/jobs'/date/channel
    package.require(target.resolve()==target,'job_path_symlink_forbidden')
    return target

def verify_chat_approval(directory,channel,date,trace,approval):
    import daily_core as c
    try:
        directory=Path(directory)
        package.require(directory.resolve()==destination(c,channel,date),'chat_approval_directory_mismatch')
        payload=verified(package.strict_json((directory/RECEIPT_NAME).read_bytes()))
        package.require(payload.get('schema')==ACCEPTANCE_SCHEMA and payload.get('acceptance')=='operator_cli_manifest_sha256','chat_acceptance_schema_invalid')
        package.require(payload.get('channel')==channel and payload.get('date')==date,'chat_acceptance_identity_mismatch')
        package.require(payload.get('approval_sha256')==c.sha(directory/'approval.json'),'chat_approval_hash_mismatch')
        package.require(payload.get('manifest_sha256')==c.sha(directory/'chat-manifest.json'),'chat_manifest_hash_mismatch')
        review=package.strict_json((directory/'chat-review.json').read_bytes())
        package.require(payload.get('review_sha256')==c.sha(directory/'chat-review.json'),'chat_review_hash_mismatch')
        package.require(review.get('origin')=='codex_chat' and review.get('approved') is True,'chat_review_not_approved')
        package.require(review.get('channel')==channel and review.get('date')==date and review.get('request_id')==payload.get('request_id'),'chat_review_identity_mismatch')
        checks=review.get('checks')
        package.require(isinstance(checks,dict) and checks and all(v is True for v in checks.values()),'chat_review_checks_failed')
        package.require(trace.get('review_origin')=='codex_chat' and trace.get('image_inputs') and trace.get('image_inputs')==review.get('image_inputs'),'chat_review_images_missing_or_mismatched')
        package.require(trace.get('video_sha256')==approval['video_sha256']==review.get('video_sha256')==payload.get('video_sha256'),'chat_review_video_mismatch')
        package.require('successful_agent_exit' not in trace and 'cli_version' not in trace,'chat_trace_cannot_assert_cli_execution')
    except package.InvalidPackage as exc:raise c.Blocked(str(exc)) from None

def technical_qa(directory):
    video=directory/'video.mp4'
    probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,size:stream=codec_type,codec_name,width,height,pix_fmt,avg_frame_rate,sample_rate,channels','-of','json',str(video)],capture_output=True,text=True,timeout=30)
    package.require(probe.returncode==0,'video_probe_failed')
    data=package.strict_json(probe.stdout)
    streams=data.get('streams',[])
    videos=[s for s in streams if s.get('codec_type')=='video']
    audios=[s for s in streams if s.get('codec_type')=='audio']
    package.require(len(streams)==2 and len(videos)==1 and len(audios)==1,'one_video_and_audio_stream_required')
    v,a=videos[0],audios[0]
    package.require(v.get('codec_name')=='h264' and v.get('pix_fmt')=='yuv420p' and (v.get('width'),v.get('height'))==(1080,1920),'video_format_invalid')
    package.require(Fraction(v.get('avg_frame_rate','0'))==30,'video_frame_rate_invalid')
    package.require(a.get('codec_name')=='aac' and a.get('sample_rate') in ('44100','48000') and a.get('channels')==2,'audio_format_invalid')
    duration=float(data['format']['duration'])
    package.require(math.isfinite(duration) and 50<=duration<=59,'video_duration_invalid')
    decoded=subprocess.run(['ffmpeg','-v','error','-xerror','-nostdin','-i',str(video),'-f','null','-'],capture_output=True,timeout=180)
    package.require(decoded.returncode==0,'video_decode_failed')
    from PIL import Image
    with Image.open(directory/'thumbnail.jpg') as image:
        package.require(image.format=='JPEG' and image.size==(1080,1920),'thumbnail_format_invalid');image.verify()
    return {'technical_checks_passed':True,'sha256':package.digest(video),'duration_seconds':duration,
            'checks':{'format':True,'full_decode':True,'thumbnail':True},'validator':'vps_chat_receiver_ffmpeg'}

def rename_new(source,target):
    # Ubuntu/Linux: atomically refuse even an existing empty destination directory.
    libc=ctypes.CDLL(None,use_errno=True)
    function=getattr(libc,'renameat2',None)
    package.require(function is not None,'atomic_directory_import_unavailable')
    if function(-100,os.fsencode(source),-100,os.fsencode(target),1)!=0:
        error=ctypes.get_errno()
        if error==errno.EEXIST:raise package.InvalidPackage('job_already_exists')
        raise OSError(error,'atomic_import_failed')

def music_cache(c,directory,manifest):
    track=c.load(directory/'music_credits.json')
    if track.get('provider')!='epidemic':return None
    package.require(track.get('covered_channel')==manifest['channel'],'epidemic_job_channel_mismatch')
    name=track.get('filename')
    package.require(isinstance(name,str) and Path(name).name==name and name.startswith('epidemic-'),'epidemic_cache_path_invalid')
    digest=track.get('sha256');package.require(isinstance(digest,str) and len(digest)==64,'epidemic_hash_missing')
    cache=ROOT/'runtime/music'/name
    package.require(cache.resolve()==cache,'epidemic_cache_symlink_forbidden')
    if cache.exists():
        package.require(c.sha(cache)==digest,'epidemic_existing_cache_hash_mismatch');return None
    source=directory/'music'/name
    package.require('music/'+name in manifest['files'] and source.is_file() and c.sha(source)==digest,'epidemic_verified_audio_missing')
    cache.parent.mkdir(parents=True,exist_ok=True)
    # Linking the verified private staging file is atomic and never overwrites.
    os.link(source,cache)
    return cache

def receive(archive,expected_hash,accept_review=False):
    package.require(accept_review is True,'explicit_chat_review_acceptance_required')
    c=runtime();gate(c)
    inbox=ROOT/'runtime/chat-inbox';inbox.mkdir(parents=True,exist_ok=True)
    package.require(inbox.resolve()==inbox,'inbox_symlink_forbidden')
    with tempfile.TemporaryDirectory(prefix='.receive-',dir=inbox) as temporary:
        temporary=Path(temporary);snapshot=temporary/'package.zip';copied=0
        descriptor=os.open(Path(archive),os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(descriptor,'rb') as source,snapshot.open('xb') as target:
            package.require(stat.S_ISREG(os.fstat(source.fileno()).st_mode),'archive_regular_file_required')
            for block in iter(lambda:source.read(1024*1024),b''):
                copied+=len(block);package.require(copied<=package.MAX_TOTAL+2*1024*1024,'archive_too_large');target.write(block)
        manifest=package.inspect_archive(snapshot,expected_hash)
        directory=temporary/'job';directory.mkdir()
        with zipfile.ZipFile(snapshot) as packed:
            for name in manifest['files']:
                target=directory/name;target.parent.mkdir(parents=True,exist_ok=True)
                with packed.open(name) as source,target.open('xb') as output:shutil.copyfileobj(source,output)
            (directory/'chat-manifest.json').write_bytes(packed.read('manifest.json'))
        qa=technical_qa(directory)
        from helpers import daily
        with daily.locked():
            gate(c)
            policy=c.load(ROOT/'activation-package-20261019/activation-policy.json')
            package.require(manifest['date']==c.day() and c.in_period(policy,manifest['date']),'import_requires_current_authorized_date')
            target=destination(c,manifest['channel'],manifest['date'])
            package.require(not target.exists(),'job_already_exists')
            created_cache=None
            committed=False
            try:
                created_cache=music_cache(c,directory,manifest)
                from music_provider import publish_preflight
                publish_preflight(directory,manifest['channel'],dry=True)
                review=c.load(directory/'chat-review.json')
                c.atomic(directory/'job.json',{'date':manifest['date'],'channel':manifest['channel'],'scope':'production',
                    'topic':manifest['topic'],'topic_key':manifest['topic_key'],'request_id':manifest['request_id']})
                c.atomic(directory/'qa.json',qa)
                c.atomic(directory/'visual-review.json',{'approved':True,'video_sha256':qa['sha256'],
                    'checks':review['checks'],'review_origin':'codex_chat','review_reference':review['review_reference']})
                c.atomic(directory/'vision-evidence.json',{'review_origin':'codex_chat','video_sha256':qa['sha256'],
                    'request_id':manifest['request_id'],'review_reference':review['review_reference'],'image_inputs':review['image_inputs']})
                artifacts={p.relative_to(directory).as_posix():c.sha(p) for p in directory.rglob('*') if p.is_file()}
                approval={'scope':'production','date':manifest['date'],'channel':manifest['channel'],'topic':manifest['topic'],
                    'topic_key':manifest['topic_key'],'request_id':manifest['request_id'],'video_sha256':qa['sha256'],
                    'review_origin':'codex_chat','approved_at':c.now().isoformat(),'artifacts':artifacts}
                c.atomic(directory/'approval.json',approval)
                payload={'schema':ACCEPTANCE_SCHEMA,'acceptance':'operator_cli_manifest_sha256','accepted_at':c.now().isoformat(),
                    'channel':manifest['channel'],'date':manifest['date'],'request_id':manifest['request_id'],
                    'manifest_sha256':expected_hash,'approval_sha256':c.sha(directory/'approval.json'),
                    'review_sha256':c.sha(directory/'chat-review.json'),'video_sha256':qa['sha256']}
                c.atomic(directory/RECEIPT_NAME,signed(payload))
                c.atomic(directory/'blocked.json',{'reason':'chat_import_awaiting_publication_authorization',
                    'phase':'receive','request_id':manifest['request_id'],'manifest_sha256':expected_hash})
                target.parent.mkdir(parents=True,exist_ok=True)
                rename_new(directory,target);committed=True
                try:c.approval(target,manifest['channel'],manifest['date'])
                except Exception:
                    c.atomic(target/'blocked.json',{'reason':'chat_import_post_commit_validation_failed','phase':'receive'});raise
            finally:
                if not committed and created_cache is not None:created_cache.unlink(missing_ok=True)
    return {'status':'received_awaiting_publication_authorization','channel':manifest['channel'],'date':manifest['date'],
            'request_id':manifest['request_id'],'publication_invoked':False}

def publish(channel,date,request_id,execute=False):
    package.require(execute is True,'explicit_publication_execution_required')
    c=runtime();gate(c)
    from helpers import daily
    with daily.locked():
        gate(c);directory=destination(c,channel,date)
        job=c.load(directory/'job.json')
        package.require(job.get('request_id')==request_id,'publication_request_id_mismatch')
        c.approval(directory,channel,date)
        package.require(c.load(directory/'vision-evidence.json').get('review_origin')=='codex_chat','chat_job_required')
        policy=c.load(ROOT/'activation-package-20261019/activation-policy.json')
        import daily_remote as remote
        remote.guard_window(policy,job)
        package.require(c.load(ROOT/'runtime/production/activation.json').get('status')=='enabled','activation_gate_closed')
        marker=directory/'blocked.json'
        if marker.exists():
            block=c.load(marker)
            package.require(block.get('reason')=='chat_import_awaiting_publication_authorization' and block.get('request_id')==request_id,'existing_job_block_requires_review')
        expires=dt.datetime.fromisoformat(date+'T'+policy['publication_window_end']).replace(tzinfo=c.ZONE)
        c.atomic(directory/AUTH_NAME,signed({'schema':'video-agent.chat-publication.v1','channel':channel,'date':date,
            'request_id':request_id,'approval_sha256':c.sha(directory/'approval.json'),
            'authorized_at':c.now().isoformat(),'expires_at':expires.isoformat()}))
        marker.unlink(missing_ok=True)
        result=remote.Publisher(policy,directory,job).run()
        return {'status':'publication_attempt_recorded','channel':channel,'date':date,
            'platforms':{name:{k:v for k,v in record.items() if k in ('state','video_id','media_id','url','reason_code')}
            for name,record in result.get('platforms',{}).items()}}

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    check=sub.add_parser('check-system')
    accept=sub.add_parser('receive');accept.add_argument('archive');accept.add_argument('--manifest-sha256',required=True)
    accept.add_argument('--accept-chat-review',action='store_true')
    post=sub.add_parser('publish');post.add_argument('--channel',required=True,choices=package.CHANNELS)
    post.add_argument('--date',required=True);post.add_argument('--request-id',required=True);post.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.command=='check-system':
        c=runtime();gate(c);key();result={'status':'chat_receiver_ready','publication_invoked':False}
    elif args.command=='receive':result=receive(args.archive,args.manifest_sha256,args.accept_chat_review)
    else:result=publish(args.channel,args.date,args.request_id,args.execute)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'blocked','reason':str(exc) if isinstance(exc,package.InvalidPackage) else type(exc).__name__}))
        raise SystemExit(2)
