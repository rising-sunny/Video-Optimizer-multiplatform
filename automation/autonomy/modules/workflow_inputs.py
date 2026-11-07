"""Read only the public evidence and catalogue inputs of an existing video job."""
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

import workflow_common as c


def public_text(value, limit=12000):
    text = re.sub(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+', '[hidden]', str(value))
    text = re.sub(r'(?i)Bearer\s+\S+', 'Bearer [hidden]', text)
    return re.sub(r'(?i)([?&](?:access_token|token|secret|signature|x-amz-signature)=)[^\s"&]+', r'\1[hidden]', text)[:limit]


def public_url(value):
    parsed = urlsplit(str(value))
    return urlunsplit((parsed.scheme, parsed.hostname or '', parsed.path, '', ''))

def documentary_plan_data(job):
    """Bounded public saved plan, including invalid shapes, for local recovery."""
    import json
    job=c.safe(Path(job));path=c.safe(job/'editorial-plan.json')
    if job.parent.name!='manual-documentary' or not path.is_file() or path.stat().st_size>60000:return {}
    raw=path.read_text();value=json.loads(raw)
    if not isinstance(value,dict):return {}
    selected={key:value[key] for key in ('history_review_complete','duplicate','title','description',
        'research','claims','assets','segments','thumbnail') if key in value}
    return json.loads(public_text(json.dumps(selected,ensure_ascii=False),120000))

def documentary_catalog_data(job):
    job=c.safe(Path(job));path=c.safe(job/'media-catalog.json')
    if job.parent.name!='manual-documentary' or not path.is_file() or path.stat().st_size>4*1024*1024:return []
    return [{k:public_text(row[k],2200) for k in ('id','type','title','description','date','author','license','source_url') if k in row}
            for row in c.read(path).get('items',[])[:72]]


def resume_inputs(job):
    job = c.safe(Path(job))
    root = c.ledger(job)
    tools = c.read(root / 'tools.json') if (root / 'tools.json').is_file() else {}
    fetches = []
    for record in tools.values():
        if record.get('kind') != 'fetch':
            continue
        result = record.get('result', {})
        content = result.get('content', '')
        content = content if isinstance(content, str) else ''
        fetches.append(dict(url=public_url(record.get('request', {}).get('url', '')),
            state=result.get('state', 'saved'), characters=len(content),
            content=public_text(content)))
    from documentary_sources import diagnostics, available
    snapshots = diagnostics(job)
    saved = [dict(url=public_url(url), transport=row.get('transport'),
        content=public_text(row['content'])) for url, row in available(job).items()]
    music = c.read(job / 'music-input.json') if (job / 'music-input.json').is_file() else {}
    fields = ('title', 'artist', 'recording_id', 'isrc', 'url', 'license', 'license_url',
        'attribution', 'credit', 'moods', 'genres', 'tags', 'duration', 'bpm')
    tracks = [{key: public_text(row[key], 1600) for key in fields if key in row}
        for row in music.get('tracks', []) if isinstance(row, dict)][:30]
    plan_check={}
    try:
        from workflow_jobs import plan
        kind='catarsis' if job.parent.parent.name=='manual-catarsis' else 'documentary'
        ident=job.parent.name if kind=='catarsis' else job.name
        task=c.read(c.STATE/kind/ident/'request.json')
        selected=plan(job,kind,task,job.name if kind=='catarsis' else None)
        plan_check=dict(state='passed',native_schema_only=True,quality_approval=False,
            music_title=selected.get('music_title'),music_license_url=selected.get('music_license_url'),
            project=selected.get('project'),metadata=selected.get('metadata'),assets=selected.get('assets'))
    except Exception as exc:
        plan_check=dict(state='blocked',error_code=c.clean(exc,500),saved_documentary_plan=documentary_plan_data(job))
    presentation={}
    if job.parent.parent.name=='manual-catarsis' and (job/'visual-review.json').is_file():
        from workflow_presentation import available as presentation_available
        presentation=presentation_available(job.parent.name)
    from workflow_preview import frames
    previews=frames(job)
    qa=c.read(job/'qa.json') if (job/'qa.json').is_file() else {}
    api={}
    if (job/'video.mp4').is_file():
        try:
            import inspect,sys
            sys.path.insert(0,'/home/videoagent/video-automation');import editorial
            from workflow_native import implementation
            helper=implementation(editorial).d
            api={name:str(inspect.signature(getattr(helper,name))) for name in dir(helper)
                if (name in ('render_project','probe','check_video','validate_video') or 'qa' in name.lower())
                and callable(getattr(helper,name))}
            # Only these two non-credential generation functions are exposed;
            # no arbitrary helper/module path or configuration read is accepted.
            for name in ('render_project','qa'):
                api[name+'_source']=public_text(inspect.getsource(getattr(helper,name)),16000)
        except Exception as exc:api=dict(error=c.clean(exc,200))
    return dict(assessment_details=assessment_details(job),read_only=True, ai_requests=0, network_requests=0,
        fetched_sources=fetches[:14], factual_snapshots=snapshots,
        saved_snapshot_text=saved[:6], music=dict(fields=list(music), tracks=tracks),
        preview_frames=previews,qa=dict(technical_checks_passed=qa.get('technical_checks_passed'),
            sha256=qa.get('sha256'),fields=list(qa)),render_api=api,
        plan_check=plan_check,verified_catalogue=documentary_catalog_data(job),presentation=presentation,
        last_failure=c.clean(c.read(job/'blocked.json'),2000) if (job/'blocked.json').is_file() else None,
        preparation=c.read(job/'workflow-preparation.json') if (job/'workflow-preparation.json').is_file() else None,
        evidence_notice='Public saved input data only; a saved source or catalogue is not a quality approval.')


def assessment_details(job):
    """Bounded public review fields and original provider response, never credentials."""
    import json
    job=Path(job);result={}
    for name in ('visual-review.json','deepseek-text-review.json'):
        if (job/name).is_file():
            value=c.read(job/name)
            result[name]={k:value[k] for k in ('approved','video_sha256','checks','findings','recommendation','platform_policy_checks','assessment_sources','resolution') if k in value}
    events=job/'visual-review-events.jsonl'
    if events.is_file() and not events.is_symlink() and events.stat().st_size<=50*1024*1024:
        messages=[];complete=False;failed=False
        for line in events.read_text().splitlines():
            try:row=json.loads(line)
            except ValueError:continue
            if row.get('type')=='turn.completed':complete=True
            if row.get('type') in ('error','turn.failed'):failed=True
            if row.get('type')=='item.completed' and row.get('item',{}).get('type')=='agent_message':
                messages.append(row['item'].get('text',''))
        result['provider_visual']=dict(completed=complete,failed=failed,events_sha256=c.digest(events),
            original_response=public_text(messages[-1],18000) if messages else None)
    sheet=job/'style-entry-sheet-0.jpg'
    if sheet.is_file() and not sheet.is_symlink() and sheet.stat().st_size<=400000:
        import base64
        result['actual_text_entry_sheet']=dict(mime_type='image/jpeg',image_base64=base64.b64encode(sheet.read_bytes()).decode(),
            source='actual_final_mp4_entry_frames',video_sha256=c.digest(job/'video.mp4'),sha256=c.digest(sheet))
    return result


