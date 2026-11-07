"""Bounded public evidence downloads and Commons licensing receipts."""
import html
import ipaddress
import json
from pathlib import Path
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from documentary_common import Failure, save, sha, now

AGENT='VideoOptimizerDocumentary/18 (historical documentary research)'

def public_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise Failure('documentary_public_https_required')
    addresses=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise Failure('documentary_private_source_rejected')
    return url

class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url,limit=4*1024*1024,guard=lambda:None,folder=None):
    from documentary_transport import transfer
    return transfer(url,limit,validate=public_url,guard=guard,folder=folder)

def clean(value):
    return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]*>',' ',str(value)))).strip()

def commons(folder,index,asset,fetcher=fetch):
    for title in asset['commons_titles']:
        try:
            query=urllib.parse.urlencode(dict(action='query',format='json',prop='imageinfo',
                 iiprop='url|size|extmetadata',titles=title))
            payload=json.loads(fetcher('https://commons.wikimedia.org/w/api.php?'+query))
            page=next(iter(payload['query']['pages'].values()));info=page['imageinfo'][0]
            meta=info.get('extmetadata',{});license=clean(meta.get('LicenseShortName',{}).get('value',''))
            author=clean(meta.get('Artist',{}).get('value',''))
            # Commercial use and adaptations are required; public domain is not.
            if license not in ('Public domain','CC0') and not re.fullmatch(r'CC BY(?:-SA)? (?:2\.0|2\.5|3\.0|4\.0)(?: [A-Z]{2})?',license):continue
            if license.startswith('CC BY') and not author:continue
            url=info['url'];p=urllib.parse.urlsplit(url)
            if p.hostname!='upload.wikimedia.org':continue
            ext=Path(p.path).suffix.lower()
            if ext not in ('.jpg','.jpeg','.png','.webp','.tif','.tiff','.mp4','.webm','.ogv'):continue
            kind='video' if ext in ('.mp4','.webm','.ogv') else 'image'
            if kind!=asset['type']:continue
            limit=120*1024*1024 if kind=='video' else 24*1024*1024
            if info.get('size',limit+1)>limit:continue
            data=fetcher(url,limit);path=folder/f'media-{index}{ext}';path.write_bytes(data)
            if kind=='image':
                from PIL import Image
                with Image.open(path) as im:
                    if im.width*im.height>90_000_000:continue
                    im.verify()
            evidence=folder/f'license-{index}.json';save(evidence,dict(retrieved_at=now(),file_title=title,metadata=info))
            return dict(file=str(path),type=kind,label=asset['label'],role=asset['role'],
                        source_url=info['descriptionurl'],author=author or 'Unidentified author',
                        license=license,license_url=clean(meta.get('LicenseUrl',{}).get('value','')) or info['descriptionurl'],
                        sha256=sha(path),evidence_sha256=sha(evidence),
                        changes='Resized proportionally; excerpted; text and context labels overlaid; soft fades and brief color washes; original clip audio removed.'+(' Foreground enlarged without cropping; blurred, dimmed background derived from the same photograph.' if kind=='image' else ''))
        except (Failure,KeyError,ValueError,StopIteration,OSError):continue
    raise Failure('documentary_asset_alternatives_exhausted')

def acquire(folder,plan,guard,progress):
    sources=[]
    for i,s in enumerate(plan['research']):
        guard()
        path=folder/f'source-{i}.html'
        from documentary_sources import cached
        snapshot=cached(folder,s['url'])
        if snapshot:
            data=(folder/snapshot['file']).read_bytes();path.write_bytes(data)
            sources.append(dict(url=s['url'],summary=s['summary'],file=path.name,sha256=sha(path),
                transport=snapshot['transport'],snapshot_sha256=snapshot['text_sha256'],
                retrieved_at=snapshot['retrieved_at']))
            continue
        previous=folder/'sources.json'
        if previous.is_file():
            from documentary_common import read
            saved=next((r for r in read(previous) if r.get('url')==s['url'] and r.get('file')==path.name),None)
            if saved and path.is_file() and sha(path)==saved.get('sha256'):
                sources.append(saved);continue
        try:
            data=fetch(s['url']);path=folder/f'source-{i}.html';path.write_bytes(data)
            sources.append(dict(url=s['url'],summary=s['summary'],file=path.name,sha256=sha(path)))
        except Failure:
            sources.append(dict(url=s['url'],state='unavailable'))
    if sum('file' in s for s in sources)<2:raise Failure('documentary_two_sources_required')
    save(folder/'sources.json',sources)
    media=[None]*len(plan['assets']);total=0;done=0
    # Validate and reuse checkpoints before contacting any source.
    for i,a in enumerate(plan['assets']):
        if a.get('media_ids'):
            guard();cached=reuse(folder,i,a)
            if cached:
                media[i]=cached;done+=1;total+=Path(cached['file']).stat().st_size
    thumb=plan['thumbnail']['asset']
    order=[thumb]+[i for i in range(len(media)) if i!=thumb]
    for i in order:
        if media[i] is not None:continue
        a=plan['assets'][i];guard();progress('acquiring_media',done,len(media))
        if a.get('media_ids'):
            try:row=verified(folder,i,a,guard)
            except Failure as exc:
                if str(exc)!='documentary_verified_media_download_failed' or i==thumb:raise
                row=fallback(folder,i,a,plan,guard)
        else:row=commons(folder,i,a)
        total+=Path(row['file']).stat().st_size
        if total>600*1024*1024:raise Failure('documentary_media_budget_exceeded')
        media[i]=row;done+=1
    save(folder/'asset-credits.json',media)
    if any(a.get('media_ids') for a in plan['assets']):save(folder/'editorial-plan.json',plan)
    progress('acquiring_media',done,len(media))
    return media

def fallback(folder,index,asset,plan,guard):
    from documentary_common import read
    catalog=read(folder/'media-catalog.json');rows={r['id']:r for r in catalog['items']}
    selected={i for a in plan['assets'] for i in a.get('media_ids',[])}
    words=lambda v:set(re.findall(r'[a-z0-9]{3,}',clean(v).lower()))-{'file','jpg','jpeg','png','photo','image','context','the','and'}
    theme=words(asset['label'])
    candidates=[r for r in rows.values() if r['id'] in selected and r['id'] not in asset['media_ids'] and r['type']=='image']
    candidates.sort(key=lambda r:len(theme & words(r['title']+' '+r['description'])),reverse=True)
    for r in candidates[:3]:
        title=re.sub(r'^File:','',r['title']);title=re.sub(r'\.(?:jpe?g|png|webp|tiff?)$','',title,flags=re.I)
        replacement=dict(type='image',role='context',label=('Context: '+title)[:90],media_ids=[r['id']])
        try:result=verified(folder,index,replacement,guard)
        except Failure as exc:
            if str(exc)!='documentary_verified_media_download_failed':raise
            continue
        previous=dict(asset);asset.clear();asset.update(replacement)
        save(folder/f'media-fallback-{index}.json',dict(reason='selected_media_unavailable',
            previous=previous,replacement=replacement,ai_requests=0,script_unchanged=True))
        return result
    raise Failure('documentary_verified_media_download_failed')

def credit(path,evidence,row,asset):
    return dict(file=str(path),type=row['type'],label=asset['label'],role=asset['role'],
        source_url=row['source_url'],author=row['author'],license=row['license'],license_url=row['license_url'],
        sha256=sha(path),evidence_sha256=sha(evidence),
        changes='Resized proportionally; excerpted; text and context labels overlaid; soft fades and brief color washes; original clip audio removed.'+(' Foreground enlarged without cropping; blurred, dimmed background derived from the same photograph.' if row['type']=='image' else ''))

def checkpoint(folder,index,ident,result,evidence,row):
    from documentary_common import read
    provenance=folder/'media-provenance.json';values=read(provenance) if provenance.exists() else {}
    values[str(index)]={k:row[k] for k in ('id','provider','source_url','title','description','date','license')}
    save(provenance,values)
    cache=folder/'media-checkpoints-v23.json';saved=read(cache) if cache.exists() else {}
    saved[str(index)]=dict(id=ident,file=Path(result['file']).name,sha256=result['sha256'],
        evidence=evidence.name,evidence_sha256=result['evidence_sha256'],type=result['type'])
    save(cache,saved)

def reuse(folder,index,asset):
    """Reuse a pinned receipt/checkpoint. Never replace changed cached media."""
    from documentary_common import read, safe_path
    from documentary_catalog import VERSION
    catalog=read(folder/'media-catalog.json')
    if catalog.get('version')!=VERSION:raise Failure('documentary_catalog_version_invalid')
    offered={r['id']:r for r in catalog['items']}
    cache=folder/'media-checkpoints-v23.json';values=read(cache) if cache.exists() else {}
    for value in values.values():
        if value['id'] not in asset['media_ids'] or value['type']!=asset['type']:continue
        if (Path(value['file']).name!=value['file'] or Path(value['evidence']).name!=value['evidence']):
            raise Failure('documentary_cached_media_path_invalid')
        path=safe_path(folder/value['file']);evidence=safe_path(folder/value['evidence'])
        if sha(path)!=value['sha256'] or sha(evidence)!=value['evidence_sha256']:
            raise Failure('documentary_cached_media_changed')
        row=offered[value['id']];result=credit(path,evidence,row,asset)
        checkpoint(folder,index,value['id'],result,evidence,row)
        return result
    # Import the exact successful v22 downloads, whose bytes and receipts are
    # pinned by the explicit continuation authorization before this function runs.
    provenance=folder/'media-provenance.json'
    original=read(provenance) if provenance.exists() else {}
    for position,value in original.items():
        ident=value.get('id')
        if ident not in asset['media_ids'] or not str(position).isdigit():continue
        row=offered.get(ident)
        if not row or row['type']!=asset['type']:continue
        ext=Path(urllib.parse.urlsplit(row['url']).path).suffix.lower()
        path=safe_path(folder/f'media-v22-{position}{ext}');evidence=safe_path(folder/f'license-{position}.json')
        if not path.is_file() or not evidence.is_file():continue
        receipt=read(evidence)
        if receipt.get('record')!=row or (row.get('size') and path.stat().st_size!=row['size']):
            raise Failure('documentary_cached_media_changed')
        if row['type']=='image':
            from PIL import Image
            with Image.open(path) as im:im.verify()
        result=credit(path,evidence,row,asset)
        checkpoint(folder,index,ident,result,evidence,row)
        return result
    return None

def rendition(folder,row,guard):
    """Ask the official API for a rendition of the exact same licensed work."""
    from documentary_common import read
    from documentary_catalog import host, IMAGE_EXT
    if row['provider']!='commons' or row['type']!='image':return None
    cached=folder/'media-renditions-v23.json';values=read(cached) if cached.exists() else {}
    if row['id'] in values:return values[row['id']]
    title=row.get('evidence',{}).get('file_title')
    if not isinstance(title,str) or not title.startswith('File:'):return None
    original_width=row.get('evidence',{}).get('metadata',{}).get('width',0)
    width=1280 if not isinstance(original_width,int) or original_width>1280 else 800
    query=urllib.parse.urlencode(dict(action='query',format='json',prop='imageinfo',
        iiprop='url|size',titles=title,iiurlwidth=width,redirects=1))
    payload=json.loads(fetch('https://commons.wikimedia.org/w/api.php?'+query,4*1024*1024,guard,folder))
    result=None
    for page in payload.get('query',{}).get('pages',{}).values():
        for info in page.get('imageinfo',[])[:1]:
            url=info.get('thumburl','')
            # No computed or invented URLs; accept only the API's actual link.
            if (page.get('title')!=title or not host(url,{'upload.wikimedia.org'}) or url==row['url']
                or Path(urllib.parse.urlsplit(url).path).suffix.lower() not in IMAGE_EXT):continue
            result=dict(kind='commons_thumbnail',url=url,expected_bytes=None,
                        width=info.get('thumbwidth'),height=info.get('thumbheight'),source_title=title)
    values[row['id']]=result;save(cached,values)
    return result

def binary_limit(row):
    # One observed 22-minute NASA film has no 360p WebM. Its actual 480p
    # provider rendition is ~135 MiB. Keep the total-job budget and all
    # licensing/host checks; allow this exact rendition up to 160 MiB.
    evidence=row.get('evidence',{});chosen=evidence.get('chosen_derivative',{})
    if (row.get('provider')=='commons' and row.get('license')=='Public domain'
        and evidence.get('file_title')=='File:Skylab - The First 40 Days.webm'
        and chosen.get('height')==480 and chosen.get('src')==row.get('url')
        and str(chosen.get('type','')).startswith('video/webm')):
        return 160*1024*1024
    return (120 if row['type']=='video' else 24)*1024*1024

def verified(folder,index,asset,guard=lambda:None,fetcher=None):
    from documentary_common import read, safe_path
    from documentary_catalog import VERSION, permitted, IMAGE_EXT, VIDEO_EXT, host
    from documentary_transport import record
    catalog=read(folder/'media-catalog.json')
    if catalog.get('version')!=VERSION:raise Failure('documentary_catalog_version_invalid')
    rows={r['id']:r for r in catalog['items']};failures=[]
    for ident in asset['media_ids']:
        guard()
        if ident not in rows:raise Failure('documentary_media_id_not_offered')
        row=rows[ident];url=row['url'];ext=Path(urllib.parse.urlsplit(url).path).suffix.lower()
        hosts={'commons':{'upload.wikimedia.org'},'loc':{'tile.loc.gov','cdn.loc.gov','www.loc.gov'},
               'internet_archive':{'archive.org'},'us_air_force':{'media.defense.gov'}}
        if (not host(url,hosts.get(row['provider'],set())) or not permitted(row['license']) or
            row['type']!=asset['type'] or ext not in IMAGE_EXT|VIDEO_EXT):
            raise Failure('documentary_catalog_record_invalid')
        cached=reuse(folder,index,dict(asset,media_ids=[ident]))
        if cached:return cached
        limit=binary_limit(row)
        variants=[dict(kind='original',url=url,expected_bytes=row.get('size'))]
        for attempt in range(2 if fetcher is None else 1):
            if attempt:
                try:alternative=rendition(folder,row,guard)
                except (Failure,ValueError,KeyError,OSError) as exc:
                    if isinstance(exc,Failure) and not str(exc).startswith('documentary_source_'):raise
                    failures.append(dict(id=ident,error=str(exc) if isinstance(exc,Failure) else 'rendition_metadata_invalid',details=getattr(exc,'details',{})))
                    record(folder,dict(state='rendition_failed',asset=index,**failures[-1]));break
                if not alternative:break
                variants.append(alternative)
            variant=variants[-1];expected=variant.get('expected_bytes')
            if expected is not None and not 0<expected<=limit:break
            try:
                data=fetcher(variant['url'],limit) if fetcher else fetch(variant['url'],limit,guard,folder)
                if not data or len(data)>limit:raise Failure('documentary_source_too_large')
                if expected is not None and len(data)!=expected:raise Failure('documentary_media_size_changed')
                if row['type']=='image':
                    from PIL import Image
                    import io
                    with Image.open(io.BytesIO(data)) as im:
                        if im.width*im.height>90_000_000:raise Failure('documentary_image_too_large')
                        im.verify()
                elif data.lstrip().lower().startswith((b'<html',b'<!doctype')):
                    raise Failure('documentary_video_response_invalid')
                ext=Path(urllib.parse.urlsplit(variant['url']).path).suffix.lower()
                path=safe_path(folder/f'media-v23-{index}{ext}');path.write_bytes(data)
                evidence=folder/f'license-{index}.json'
                save(evidence,dict(retrieved_at=now(),provider=row['provider'],record=row,representation=variant))
                result=credit(path,evidence,row,asset);checkpoint(folder,index,ident,result,evidence,row)
                return result
            except (Failure,OSError,ValueError) as exc:
                # Cancellation, pins and cache corruption are never media errors.
                if isinstance(exc,Failure) and not str(exc).startswith(('documentary_source_','documentary_media_size_','documentary_image_','documentary_video_response_')):
                    raise
                failures.append(dict(id=ident,representation=variant['kind'],
                    error=str(exc) if isinstance(exc,Failure) else 'invalid_media_bytes',details=getattr(exc,'details',{})))
                record(folder,dict(state='candidate_failed',asset=index,**failures[-1]))
                # Do not evade a provider cooldown by rapidly trying other URLs.
                if str(exc) in ('documentary_source_rate_limited','documentary_source_cooldown_required'):
                    save(folder/f'media-failure-v23-{index}.json',dict(asset=index,candidates=failures))
                    raise
    save(folder/f'media-failure-v23-{index}.json',dict(asset=index,candidates=failures))
    raise Failure('documentary_verified_media_download_failed')

