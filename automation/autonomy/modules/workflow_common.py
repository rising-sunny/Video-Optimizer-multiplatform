"""Shared paths, durable records and bounded owner-facing diagnostics."""
import hashlib
import json
import os
from datetime import datetime,timezone
from pathlib import Path
import re
import socket
import tempfile

ROOT=Path('/opt/video-agent-mcp')
RUNTIME=Path('/home/videoagent/video-automation/runtime')
STATE=Path('/var/lib/video-agent-prepare')
ADMIN=Path('/run/video-workflow-maintenance')
VERSION='autonomous-workflow-v49'
CHANNELS=('stunning-facts-of-history','stunning-revelations')
RETRY_CODES={'generation_dependency_deepseek_json_invalid','generation_dependency_deepseek_incomplete_handoff',
    'source_transport_error','source_http_500','source_http_502','source_http_503','source_http_504','workflow_worker_interrupted'}

def safe(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise RuntimeError('workflow_symlink_rejected')
    return path

def digest(path):
    value=hashlib.sha256()
    with safe(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()
def read(path):return json.loads(safe(path).read_text())

def write(path,value):
    path=safe(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.workflow-')
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600);json.dump(value,stream,ensure_ascii=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:Path(temp).unlink(missing_ok=True)

def valid_id(value):return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{32}',value) is not None

def paths(kind,ident,channel=None):
    if kind not in ('catarsis','documentary') or not valid_id(ident):raise RuntimeError('workflow_invalid_job')
    state=STATE/kind/ident
    job=RUNTIME/('manual-catarsis' if kind=='catarsis' else 'manual-documentary')/ident
    if kind=='catarsis':
        if channel not in CHANNELS:raise RuntimeError('workflow_invalid_channel')
        job/=channel
    return safe(state),safe(job)

def tree(folder):return {str(p.relative_to(folder)):digest(p) for p in sorted(safe(folder).rglob('*')) if safe(p).is_file()}

def clean(value,limit=1000):
    text=str(value)
    text=re.sub(r'\bsk-[A-Za-z0-9_-]+','[hidden]',text)
    text=re.sub(r'(?i)Bearer\s+\S+','Bearer [hidden]',text)
    text=re.sub(r'https?://[^\s"<>]+','[URL]',text)
    return text[:limit]

def busy():return (ADMIN/'deploying.json').exists()

def rpc(operation,**values):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(30);connection.connect('/run/video-agent-prepare/control.sock')
        connection.sendall(json.dumps(dict(operation=operation,**values)).encode()+b'\n')
        with connection.makefile('rb') as stream:raw=stream.readline(1048577)
    if len(raw)>1048576 or not raw.endswith(b'\n'):raise RuntimeError('workflow_invalid_broker_response')
    return json.loads(raw)

def admin_call(operation,**values):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(10);connection.connect(str(ADMIN/'control.sock'))
        connection.sendall(json.dumps(dict(operation=operation,**values)).encode()+b'\n')
        with connection.makefile('rb') as stream:raw=stream.readline(1048577)
    if len(raw)>1048576 or not raw.endswith(b'\n'):raise RuntimeError('workflow_invalid_maintenance_response')
    return json.loads(raw)

def ledger(job):
    job=Path(job)
    if job.parent.parent.name=='manual-catarsis':
        return safe(RUNTIME/'deepseek-ledger/catarsis'/job.parent.name/job.name)
    if job.parent.name=='manual-documentary':return safe(RUNTIME/'deepseek-ledger/documentary'/job.name)
    raise RuntimeError('workflow_invalid_ledger_scope')

def diagnostics(kind,ident,channel=None,include_saved=False):
    state,job=paths(kind,ident,channel)
    task,status=read(state/'request.json'),read(state/'status.json')
    if kind=='catarsis' and channel not in task.get('topics',{}):raise RuntimeError('workflow_channel_not_requested')
    root=ledger(job);budget=read(root/'budget.json') if (root/'budget.json').is_file() else {}
    outputs=[]
    for file in sorted(root.glob('invalid-handoff-*.json'))[-4:]:
        data=read(file);text=data.get('provider_content','')
        entry=dict(file=file.name,sha256=digest(file),output=data.get('output'),characters=len(text))
        try:
            from shorts_handoff import parse
            value,repairs=parse(text)
            entry.update(parse='valid',repairs=repairs,fields=list(value) if isinstance(value,dict) else type(value).__name__)
        except (ValueError,TypeError) as exc:entry.update(parse='invalid',error=clean(exc,200),ending=clean(text[-400:]))
        if include_saved:
            # Provider content is model-visible public planning data, never credentials.
            value=re.sub(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+','[hidden]',text)
            value=re.sub(r'(?i)Bearer\s+\S+','Bearer [hidden]',value)
            value=re.sub(r'(?i)([?&](?:access_token|token|secret|signature|x-amz-signature)=)[^\s"&]+',r'\1[hidden]',value)
            entry['provider_content']=value[:18000]
        outputs.append(entry)
    row=status.get('channels',{}).get(channel,status)
    workflow=read(state/'workflow.json') if (state/'workflow.json').is_file() else {}
    reviews={}
    for name in ('deepseek-text-review.json','documentary-text-review.json','visual-review.json','review.json'):
        if (job/name).is_file():
            value=read(job/name)
            reviews[name]=dict(approved=value.get('approved'),checks=value.get('checks'),
                findings=clean(json.dumps(value.get('findings',[]),ensure_ascii=False),12000))
    return dict(kind=kind,job_id=ident,channel=channel,state=status.get('state'),phase=row.get('state',status.get('phase')),
        error_code=row.get('error_code',status.get('error_code')),workflow=workflow,read_only=True,
        checked_at=datetime.now(timezone.utc).isoformat(),status_updated_at=status.get('updated_at'),reviews=reviews,
        ai_requests=0,counts=budget.get('counts'),limits=budget.get('limits'),estimated_usd=budget.get('estimated_usd'),
        request_pending=budget.get('pending') is not None,invalid_outputs=outputs,
        files={n:dict(sha256=digest(job/n),bytes=(job/n).stat().st_size) for n in
            ('editorial-plan.json','metadata.json','project.json','qa.json','approval.json','video.mp4','thumbnail.jpg') if (job/n).is_file()})
