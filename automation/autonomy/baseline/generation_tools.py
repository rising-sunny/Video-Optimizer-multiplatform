"""Owner-authenticated MCP actions and short-lived, file-scoped preview URLs."""
import asyncio
import base64
import hashlib
import hmac
import re
import time
from typing import Literal
from urllib.parse import urlencode

from starlette.responses import Response, StreamingResponse
from generation_control import call
from generation_service import valid_batch, MAX_CHUNK
from history_data import CHANNELS

TTL = 7200


def signature(key, batch, channel, kind, expires):
    value = '\n'.join((batch, channel, kind, str(expires))).encode()
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def bounds(value, size):
    if value is None:
        return 0, size - 1, 200
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value) if len(value) < 128 else None
    if not match or not any(match.groups()):
        raise ValueError('invalid_range')
    first, last = match.groups()
    if first:
        start, end = int(first), min(int(last), size - 1) if last else size - 1
    else:
        length = int(last)
        if length <= 0:
            raise ValueError('invalid_range')
        start, end = max(0, size - length), size - 1
    if not 0 <= start <= end < size:
        raise ValueError('invalid_range')
    return start, end, 206


def register(server, signing_key, base_url):
    key = hmac.new(signing_key.encode(), b'catarsis-preview-v1', hashlib.sha256).digest()
    def links(value):
        batch = value.get('batch_id')
        if not valid_batch(batch):
            return value
        expires = int(time.time()) + TTL
        for channel, row in value.get('channels', {}).items():
            if row.get('state') != 'ready' or channel not in CHANNELS:
                continue
            for kind, item in row.get('files', {}).items():
                if kind not in ('video', 'thumbnail'):
                    continue
                query = urlencode(dict(catarsis_preview='1', batch=batch, channel=channel, kind=kind,
                    expires=expires, token=signature(key, batch, channel, kind, expires)))
                item.pop('mtime_ns', None)
                item.pop('ctime_ns', None)
                item['url'] = base_url + '/mcp?' + query
                item['expires_at_unix'] = expires
                # Private metadata cache only; no upload or publication. The URL
                # still needs the existing file-scoped HMAC at the media handler.
                call('generation_media_link_cache',batch_id=batch,channel=channel,kind=kind,url=item['url'])
        return value

    @server.tool(annotations=dict(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True))
    def generate_catarsis_pair(request_id: str, facts_topic: str, revelations_topic: str) -> dict:
        """Generate ONE Catarsis video for EACH channel using the two explicitly chosen
        topics. DeepSeek API handles text; Codex subscription handles visual review.
        This consumes API/music/render services with a per-video DeepSeek budget. GENERATION ONLY: never uploads,
        schedules or publishes. English, portrait 50-59 seconds, no narration, expressive
        text, varied licensed imagery, purposeful light transitions and original SFX.
        Current style: introspective-catarsis-v7. Optional clips fall back to stills.
        Facts uses its existing licensed free-music catalogue; Revelations uses its
        configured Epidemic Sound coverage. Daily automation stays paused.
        request_id must be 8-80 ASCII letters/digits/_/-, stable for this user request.
        Retry transport failures with the SAME ID and topics: never silently create a
        new batch or retry interrupted/blocked renders. Topics must be 8-900 characters.
        Rechecks history, sources, licenses and native technical/visual QA. Poll status.
        """
        return links(call('generation_start', request_id=request_id,
                          facts_topic=facts_topic, revelations_topic=revelations_topic))

    @server.tool(annotations=dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def catarsis_generation_status(batch_id: str | None = None) -> dict:
        """Progress and results of a manual Catarsis generation. Omit batch_id for the
        latest pair. A ready channel includes short-lived preview/download URLs for
        its approved MP4 and thumbnail. Technical/editorial QA is not user approval
        to publish. Ready files are NOT published. If links expire, call again.
        Results also include approved platform titles/captions with required full
        source/music credits; preserve those credits when uploading the video.
        Interrupted or blocked generations are never retried by this read operation.
        """
        return links(call('generation_status', batch_id=batch_id))

    @server.tool(annotations=dict(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def cancel_catarsis_generation(batch_id: str) -> dict:
        """Cancel the specified manual generation when the user asks to stop it.
        Stops only its bounded worker process group, preserves existing results and
        evidence, and never changes daily timers, accounts or published videos.
        """
        return links(call('generation_cancel', batch_id=batch_id))

    @server.custom_route('/catarsis-media/{batch}/{channel}/{kind}', methods=['GET', 'HEAD'])
    async def preview(request):
        batch, channel, kind = (request.path_params[x] for x in ('batch', 'channel', 'kind'))
        query = request.query_params
        try:
            expires = int(query.get('expires', ''))
            token = query.get('token', '')
            now = int(time.time())
            valid = (valid_batch(batch) and channel in CHANNELS and kind in ('video', 'thumbnail')
                     and set(query.keys()) == {'expires', 'token'}
                     and now < expires <= now + TTL + 60 and re.fullmatch(r'[0-9a-f]{64}', token)
                     and hmac.compare_digest(token, signature(key, batch, channel, kind, expires)))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            return Response(status_code=403, headers={'Cache-Control': 'no-store', 'X-Catarsis-Preview': 'restricted'})
        meta = await asyncio.to_thread(call, 'generation_media_meta', batch_id=batch, channel=channel, kind=kind)
        if meta.get('state') != 'ready':
            return Response(status_code=404, headers={'Cache-Control': 'no-store'})
        size = meta['size']
        headers = {'Accept-Ranges': 'bytes', 'Content-Type': meta['content_type'],
                   'Content-Disposition': 'inline; filename="' + meta['filename'] + '"',
                   'ETag': '"' + meta['sha256'] + '"', 'Cache-Control': 'private, no-store',
                   'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'}
        try:
            start, end, status = bounds(request.headers.get('range'), size)
        except ValueError:
            return Response(status_code=416, headers=dict(headers, **{'Content-Range': f'bytes */{size}'}))
        headers['Content-Length'] = str(end - start + 1)
        if status == 206:
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
        if request.method == 'HEAD':
            return Response(status_code=status, headers=headers)
        async def content():
            offset = start
            while offset <= end:
                result = await asyncio.to_thread(call, 'generation_media_read', batch_id=batch,
                    channel=channel, kind=kind, offset=offset, length=min(MAX_CHUNK, end - offset + 1))
                if result.get('state') != 'ready' or result.get('sha256') != meta['sha256']:
                    raise RuntimeError('preview_media_changed')
                chunk = base64.b64decode(result['data'], validate=True)
                if not chunk or len(chunk) > end - offset + 1:
                    raise RuntimeError('invalid_preview_chunk')
                yield chunk
                offset += len(chunk)
        return StreamingResponse(content(), status_code=status, headers=headers)
