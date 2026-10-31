"""Portable chat-generated video package. No AI, credentials, network or publishing."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, hmac, json, os, re, shutil, stat, uuid, zipfile
from pathlib import Path, PurePosixPath

CHANNELS=('stunning-facts-of-history','stunning-revelations')
MAX_TOTAL=512*1024*1024
MAX_FILE=256*1024*1024
MAX_MEMBERS=512
SCHEMA='video-agent.chat-package.v1'
ROOT_FILES={'video.mp4','thumbnail.jpg','metadata.json','chat-review.json','sources.json',
            'asset-credits.json','editorial-plan.json','music-selection.json',
            'music-license-evidence.json','music_credits.json','project.json','local-qa.json'}
FOLDERS={'review','evidence','media','music','licenses'}
EXTENSIONS={'.json','.txt','.jpg','.jpeg','.png','.mp4','.webm','.mp3','.wav','.m4a','.pdf'}
SECRET_KEYS={'access_token','refresh_token','client_secret','authorization','api_key','password',
             'upload_url','session_uri','download_url'}

class InvalidPackage(ValueError):pass

def require(condition,code):
    if not condition:raise InvalidPackage(code)

def strict_json(data):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'duplicate_json_key')
            result[key]=value
        return result
    def constant(_):raise InvalidPackage('invalid_json_number')
    return json.loads(data,object_pairs_hook=pairs,parse_constant=constant)

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def safe_path(name):
    require(isinstance(name,str) and 0<len(name)<=240,'invalid_package_path')
    parts=name.split('/')
    require(not PurePosixPath(name).is_absolute() and all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}',p) and p not in ('.','..') for p in parts),'unsafe_package_path')
    require(name in ROOT_FILES or (len(parts)>1 and parts[0] in FOLDERS and PurePosixPath(name).suffix.lower() in EXTENSIONS),'file_not_allowlisted')
    require(not any(re.search(r'(?:^|[_.-])(token|credential|secret|transport)(?:[_.-]|$)',p,re.I) for p in parts),'private_file_forbidden')
    return name

def no_secrets(value):
    if isinstance(value,dict):
        for key,item in value.items():
            require(str(key).lower() not in SECRET_KEYS,'credential_field_forbidden')
            no_secrets(item)
    elif isinstance(value,list):
        for item in value:no_secrets(item)
    elif isinstance(value,str):
        require(not re.search(r'(?i)(?:[?&](?:access_token|token|signature|x-amz-signature|sig)=|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)',value),'private_value_forbidden')

def validate_identity(value):
    require(isinstance(value,dict),'invalid_manifest')
    require(value.get('channel') in CHANNELS,'channel_not_allowed')
    date=value.get('date')
    try:valid_date=isinstance(date,str) and dt.date.fromisoformat(date).isoformat()==date
    except ValueError:valid_date=False
    require(valid_date,'invalid_date')
    identifier=value.get('request_id')
    try:valid_id=isinstance(identifier,str) and str(uuid.UUID(identifier))==identifier
    except ValueError:valid_id=False
    require(valid_id,'invalid_request_id')
    for key in ('topic','topic_key'):
        require(isinstance(value.get(key),str) and 0<len(value[key].strip())<=500,'missing_'+key)
    return f"VA-CHAT:{date}:{value['channel']}:{identifier}"

def validate_content(manifest,read):
    marker=validate_identity(manifest)
    entries=manifest['files']
    require({'video.mp4','thumbnail.jpg','metadata.json','chat-review.json','music_credits.json','sources.json','asset-credits.json'}<=entries.keys(),'required_files_missing')
    metadata=strict_json(read('metadata.json'))
    review=strict_json(read('chat-review.json'))
    require(isinstance(metadata,dict) and isinstance(review,dict),'metadata_and_review_objects_required')
    no_secrets(metadata);no_secrets(review)
    require(metadata.get('marker')==marker,'metadata_marker_mismatch')
    for network,field in (('youtube','description'),('facebook','description'),('instagram','caption')):
        content=metadata.get(network)
        require(isinstance(content,dict) and isinstance(content.get(field),str) and marker in content[field],'platform_metadata_missing_or_marker_mismatch')
    require(isinstance(metadata['youtube'].get('title'),str) and 0<len(metadata['youtube']['title'])<=100,'youtube_title_invalid')
    require(isinstance(metadata['youtube'].get('tags'),list) and all(isinstance(v,str) for v in metadata['youtube']['tags']),'youtube_tags_invalid')
    require(isinstance(metadata['facebook'].get('title'),str) and bool(metadata['facebook']['title'].strip()),'facebook_title_missing')
    require(len(metadata['instagram']['caption'])<=2200 and len(metadata['facebook']['description'])<=2200,'caption_too_long')
    require(len(metadata['youtube']['description'])<=5000,'youtube_description_too_long')
    require(isinstance(review,dict) and review.get('origin')=='codex_chat' and review.get('approved') is True,'chat_review_missing_or_not_approved')
    for key in ('channel','date','request_id'):
        require(review.get(key)==manifest[key],'review_identity_mismatch')
    require(review.get('video_sha256')==entries['video.mp4']['sha256'],'review_video_mismatch')
    require(isinstance(review.get('review_reference'),str) and bool(review['review_reference'].strip()),'review_reference_missing')
    checks=review.get('checks')
    require(isinstance(checks,dict) and checks and all(v is True for v in checks.values()),'chat_review_checks_missing_or_failed')
    require('successful_agent_exit' not in review and 'cli_version' not in review,'cli_evidence_not_allowed_for_chat_review')
    images=review.get('image_inputs')
    require(isinstance(images,list) and 0<len(images)<=100,'review_images_missing')
    for image in images:
        require(isinstance(image,dict),'invalid_review_image')
        name=image.get('path')
        require(isinstance(name,str) and name.startswith('review/') and Path(name).suffix.lower() in ('.jpg','.jpeg','.png') and name in entries,'review_image_not_packaged')
        require(image.get('sha256')==entries[name]['sha256'],'review_image_hash_mismatch')
    return metadata,review

def build(directory,output,identity):
    directory,output=Path(directory).resolve(),Path(output).absolute()
    validate_identity(identity)
    require(directory.is_dir(),'source_directory_missing')
    require(not output.is_relative_to(directory),'archive_must_be_outside_source')
    require(not output.exists(),'archive_already_exists')
    entries={};total=0
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(),'symlinks_forbidden')
        if path.is_dir():continue
        require(path.resolve()==path and stat.S_ISREG(path.stat().st_mode) and path.stat().st_nlink==1,'non_regular_or_linked_file')
        name=safe_path(path.relative_to(directory).as_posix())
        size=path.stat().st_size
        require(0<size<=MAX_FILE,'invalid_file_size')
        total+=size;require(total<=MAX_TOTAL,'package_too_large')
        if path.suffix=='.json':no_secrets(strict_json(path.read_bytes()))
        entries[name]={'size':size,'sha256':digest(path)}
    require(len(entries)<=MAX_MEMBERS,'too_many_files')
    manifest=dict(identity,schema=SCHEMA,producer='codex_chat',files=entries)
    no_secrets(manifest)
    validate_content(manifest,lambda name:(directory/name).read_bytes())
    raw=canonical(manifest)
    require(len(raw)<=128*1024,'manifest_too_large')
    temporary=output.with_name(output.name+'.partial')
    require(not temporary.exists(),'partial_archive_already_exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with temporary.open('xb') as stream,zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
            for name in ('manifest.json',*entries):
                info=zipfile.ZipInfo(name);info.external_attr=(stat.S_IFREG|0o600)<<16
                if name=='manifest.json':archive.writestr(info,raw);continue
                h=hashlib.sha256();count=0
                with (directory/name).open('rb') as source,archive.open(info,'w') as target:
                    for block in iter(lambda:source.read(1024*1024),b''):
                        target.write(block);h.update(block);count+=len(block)
                require(count==entries[name]['size'] and h.hexdigest()==entries[name]['sha256'],'source_changed_during_packaging')
        # Exclusive destination creation prevents replacing an existing archive.
        os.link(temporary,output);temporary.unlink()
    finally:temporary.unlink(missing_ok=True)
    return {'archive':str(output),'manifest_sha256':hashlib.sha256(raw).hexdigest(),'files':len(entries),'publication_invoked':False}

def inspect_archive(path,expected_sha256):
    require(isinstance(expected_sha256,str) and re.fullmatch(r'[0-9a-f]{64}',expected_sha256),'expected_manifest_hash_required')
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist();names=[i.filename for i in infos]
        require(len(infos)<=MAX_MEMBERS+1 and len(names)==len(set(names)),'duplicate_or_excessive_members')
        require('manifest.json' in names,'manifest_missing')
        require(archive.getinfo('manifest.json').file_size<=128*1024,'manifest_too_large')
        require(sum(i.file_size for i in infos)<=MAX_TOTAL+128*1024,'package_too_large')
        for info in infos:
            require(info.compress_type==zipfile.ZIP_STORED and not info.flag_bits&1,'compressed_or_encrypted_archive_forbidden')
            require(stat.S_IFMT(info.external_attr>>16)==stat.S_IFREG,'non_regular_archive_member')
            require(0<info.file_size<=MAX_FILE,'invalid_file_size')
            if info.filename!='manifest.json':safe_path(info.filename)
        raw=archive.read('manifest.json')
        require(hmac.compare_digest(hashlib.sha256(raw).hexdigest(),expected_sha256),'manifest_hash_mismatch')
        manifest=strict_json(raw)
        no_secrets(manifest)
        require(manifest.get('schema')==SCHEMA and manifest.get('producer')=='codex_chat','unsupported_package_schema')
        files=manifest.get('files');require(isinstance(files,dict),'files_manifest_missing')
        require(set(files)==set(names)-{'manifest.json'},'unlisted_or_missing_members')
        for name,entry in files.items():
            safe_path(name)
            require(isinstance(entry,dict) and type(entry.get('size')) is int and 0<entry['size']<=MAX_FILE,'invalid_manifest_entry')
            require(isinstance(entry.get('sha256'),str) and re.fullmatch(r'[0-9a-f]{64}',entry['sha256']),'invalid_file_hash')
            require(archive.getinfo(name).file_size==entry['size'],'file_size_mismatch')
            h=hashlib.sha256()
            with archive.open(name) as source:
                for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
            require(hmac.compare_digest(h.hexdigest(),entry['sha256']),'file_hash_mismatch')
            if name.endswith('.json'):no_secrets(strict_json(archive.read(name)))
        validate_content(manifest,archive.read)
        return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('build');create.add_argument('directory');create.add_argument('output')
    for name in ('channel','date','request-id','topic','topic-key'):create.add_argument('--'+name,required=True)
    check=sub.add_parser('check');check.add_argument('archive');check.add_argument('--manifest-sha256',required=True)
    args=parser.parse_args()
    if args.command=='build':
        identity={name:getattr(args,name) for name in ('channel','date','request_id','topic','topic_key')}
        print(json.dumps(build(args.directory,args.output,identity),ensure_ascii=False))
    else:
        manifest=inspect_archive(args.archive,args.manifest_sha256)
        print(json.dumps({'status':'valid_package','channel':manifest['channel'],'date':manifest['date'],'files':len(manifest['files']),'publication_invoked':False}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'blocked','reason':str(exc) if isinstance(exc,InvalidPackage) else type(exc).__name__}))
        raise SystemExit(2)
