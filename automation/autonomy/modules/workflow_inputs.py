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
    return dict(read_only=True, ai_requests=0, network_requests=0,
        fetched_sources=fetches[:14], factual_snapshots=snapshots,
        saved_snapshot_text=saved[:6], music=dict(fields=list(music), tracks=tracks),
        evidence_notice='Public saved input data only; a saved source or catalogue is not a quality approval.')
