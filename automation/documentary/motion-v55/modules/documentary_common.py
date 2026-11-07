"""Data contracts for manual narrated documentaries; no publishing capability."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from datetime import datetime, timezone

VERSION = 'curated-plans-v36'
ROOT = Path('/opt/video-agent-mcp')
STATE = Path('/var/lib/video-agent-prepare/documentary')
JOBS = Path('/home/videoagent/video-automation/runtime/manual-documentary')
AUTOMATION = Path('/home/videoagent/video-automation')
PYTHON = '/home/videoagent/Video-Optimizer-multiplatform/.venv/bin/python'
TTS = Path('/opt/video-documentary-tts')
CHANNELS = ('stunning-facts-of-history', 'stunning-revelations')
KINDS = {'video': ('video.mp4', 'video/mp4'), 'thumbnail': ('thumbnail.jpg', 'image/jpeg')}
MEDIA_KINDS = dict(KINDS, subtitles=('subtitles.srt','application/x-subrip'))
MODULES = ('workflow_motion_documentary.py','workflow_documentary_brief.py','shorts_handoff.py','shorts_handoff_resume.py','documentary_music_revision.py','documentary_asset_repair.py','documentary_sources.py','documentary_source_repair.py','documentary_history_repair.py','documentary_common.py','documentary_service.py','documentary_worker.py',
           'documentary_ai.py','documentary_media.py','documentary_render.py','documentary_tools.py','documentary_control.py',
           'deepseek_runtime.py','deepseek_editor.py','deepseek_review.py',
           'documentary_duration.py','documentary_length_repair.py',
           'documentary_captions.py','documentary_metadata_repair.py',
           'documentary_catalog.py','documentary_media_repair.py',
           'documentary_transport.py','documentary_download_repair.py',
           'documentary_autocorrection.py','documentary_partial.py','documentary_autocorrection_repair.py',
           'documentary_compact.py','documentary_compact_repair.py',
           'documentary_layout.py','documentary_layout_repair.py','documentary_visual_recovery.py','documentary_av_revision.py','documentary_av_assets.py','documentary_av_render.py','documentary_labels.py',
           'documentary_catarsis_assets.py','documentary_catarsis_render.py','documentary_catarsis.py','documentary_catarsis_revision.py','documentary_catarsis_recovery.py','documentary_context_fix.py','shorts_media.py','shorts_resume.py','shorts_context_resume.py','shorts_curated_resume.py','curated_short_plans.py','facts-plan-v36.json','revelations-plan-v36.json','observed-plans-v36.json')

class Failure(RuntimeError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def valid_id(value):
    return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{32}',value) is not None

def safe_path(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise Failure('documentary_symlink_rejected')
    return path

def save(path,value):
    path=safe_path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.documentary-')
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:Path(tmp).unlink(missing_ok=True)

def read(path):
    path=safe_path(path)
    if path.stat().st_size>8*1024*1024:raise Failure('documentary_json_too_large')
    return json.loads(path.read_text())

def sha(path):
    path=safe_path(path)
    h=hashlib.sha256()
    with path.open('rb') as f:
        while data:=f.read(1024*1024):h.update(data)
    return h.hexdigest()

def file_info(path):
    path=safe_path(path);info=path.stat()
    if not stat.S_ISREG(info.st_mode):raise Failure('documentary_regular_file_required')
    return dict(size=info.st_size,mtime_ns=info.st_mtime_ns,ctime_ns=info.st_ctime_ns,sha256=sha(path))

def request(values):
    if (set(values)!={'request_id','channel','topic','minutes'} or
        not isinstance(values['request_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',values['request_id']) or
        values['channel'] not in CHANNELS or not isinstance(values['topic'],str) or
        not 8<=len(values['topic'].strip())<=900 or
        type(values['minutes']) not in (int,float) or not math.isfinite(values['minutes']) or
        not 8<=values['minutes']<=10):
        raise Failure('invalid_documentary_request')
    return dict(values,topic=values['topic'].strip(),minutes=float(values['minutes']))

def error(exc):
    value=str(exc)
    return value if re.fullmatch(r'[a-z][a-z0-9_]{0,100}',value) else 'documentary_worker_failed'

def usage(folder):
    result={}
    for name,provider in (('editorial-plan-events.jsonl','claude'),('documentary-text-review-events.jsonl','deepseek'),('review-events.jsonl','codex')):
        path=safe_path(Path(folder)/name)
        if not path.exists():continue
        with path.open() as f:
            for line in f:
                try:e=json.loads(line)
                except ValueError:continue
                if e.get('type')!='turn.completed' or not isinstance(e.get('usage'),dict):continue
                row=result.setdefault(e.get('provider',provider),dict(measured_turns=0,input_tokens=0,cached_input_tokens=0,output_tokens=0))
                u=e['usage'];row['measured_turns']+=1
                for k in ('input_tokens','cached_input_tokens','output_tokens'):
                    v=u.get(k,0)
                    if type(v) is int and v>=0:row[k]+=v
    history=Path(folder)/'visual-usage-history-v26.json'
    if history.is_file():
        current=Path(folder)/'review-events.jsonl'
        active=sha(current) if current.is_file() else None
        for source,entries in read(history).items():
            if source==active:continue
            for u in entries:
                row=result.setdefault('codex',dict(measured_turns=0,input_tokens=0,cached_input_tokens=0,output_tokens=0))
                row['measured_turns']+=1
                for k in ('input_tokens','cached_input_tokens','output_tokens'):
                    v=u.get(k,0)
                    if type(v) is int and v>=0:row[k]+=v
    budget=Path(folder)/'deepseek-usage.json'
    if budget.is_file() and not budget.is_symlink():
        value=read(budget).get('usage_totals')
        if isinstance(value,dict):result['deepseek']=value
    return dict(by_provider=result,note='Recorded API/CLI usage, not account quota or money. Cached input is included in input tokens; failed calls may omit telemetry.')

def validate_plan(plan):
    if plan.get('blocked'):raise Failure('documentary_editorial_blocked')
    if plan.get('history_review_complete') is not True or plan.get('duplicate') is not False:
        raise Failure('documentary_topic_duplicate_or_unchecked')
    research=plan.get('research',[]);assets=plan.get('assets',[]);segments=plan.get('segments',[])
    if not 2<=len(research)<=12 or not 8<=len(assets)<=24 or not 24<=len(segments)<=48:
        raise Failure('documentary_plan_shape_invalid')
    urls={x['url'] for x in research}
    claims=plan.get('claims',[])
    if not claims or any(not x.get('source_urls') or not set(x['source_urls'])<=urls for x in claims):
        raise Failure('documentary_claim_sources_missing')
    for a in assets:
        verified=(isinstance(a.get('media_ids'),list) and 1<=len(a['media_ids'])<=3
                  and all(isinstance(i,str) and re.fullmatch(r'M[a-f0-9]{16}',i) for i in a['media_ids']))
        if (a.get('type') not in ('image','video') or a.get('role') not in ('event','context') or
            (not verified and (not isinstance(a.get('commons_titles'),list) or not 1<=len(a['commons_titles'])<=3 or
            any(not isinstance(t,str) or not t.startswith('File:') or len(t)>250 for t in a['commons_titles']))) or
            not isinstance(a.get('label'),str) or not 1<=len(a['label'])<=90):
            raise Failure('documentary_asset_invalid')
    for s in segments:
        if (not isinstance(s.get('narration'),str) or not 8<=len(s['narration'].split())<=80 or
            type(s.get('asset')) is not int or not 0<=s['asset']<len(assets) or
            not isinstance(s.get('chapter'),str) or not 1<=len(s['chapter'])<=80):
            raise Failure('documentary_segment_invalid')
    words=sum(len(s['narration'].split()) for s in segments)
    if not 850<=words<=1850:raise Failure('documentary_word_budget_invalid')
    th=plan.get('thumbnail',{})
    if (type(th.get('asset')) is not int or not 0<=th['asset']<len(assets) or
        assets[th['asset']]['type']!='image' or not isinstance(th.get('text'),str) or not 1<=len(th['text'])<=60 or
        not isinstance(plan.get('title'),str) or not 1<=len(plan['title'])<=100 or
        not isinstance(plan.get('description'),str) or not 1<=len(plan['description'])<=5000):
        raise Failure('documentary_metadata_invalid')
    return plan

