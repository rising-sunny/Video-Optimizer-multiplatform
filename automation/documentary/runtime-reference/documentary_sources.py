"""Bounded public text snapshots, reused by planning, acquisition and review.

Native GETs are independent of DeepSeek and never represented as paid API fetches.
Failures and intents are durable: asking again does not retry a missing page.
"""
from html.parser import HTMLParser
import hashlib
import re
import urllib.error
import urllib.request
from pathlib import Path
from deepseek_runtime import safe,read,write,now,Failure

INDEX='factual-sources-v41.json'
MAX_NATIVE=6
MAX_BYTES=2*1024*1024

class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.stack=[];self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('head','script','style','nav','header','footer','aside','form','svg','iframe'):
            self.stack.append(tag)
        elif not self.stack and tag in ('p','br','div','h1','h2','h3','pre','li'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in self.stack:
            self.stack=self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]
    def handle_data(self,data):
        if not self.stack:self.parts.append(data)

def identifier(url):return hashlib.sha256(url.encode()).hexdigest()[:24]

def extracted(raw):
    if raw.startswith(b'%PDF'):
        raise Failure('documentary_factual_pdf_text_not_extracted')
    if b'\x00' in raw[:4096]:raise Failure('documentary_factual_text_unavailable')
    value=raw.decode('utf-8','replace')
    if value.count('\ufffd')>max(5,len(value)//100):raise Failure('documentary_factual_text_unavailable')
    parser=Text();parser.feed(value)
    text=re.sub(r'\s+',' ',' '.join(parser.parts)).strip()
    if (len(text)<350 or re.search(r'(?i)(access denied|verify you are human|enable javascript and cookies|captcha|just a moment)',text[:700])):
        raise Failure('documentary_factual_text_unavailable')
    return text

def excerpt(text,focus=()):
    if len(text)<=15000:return text
    spans=[(0,600)]
    for term in focus:
        where=text.casefold().find(term.casefold())
        if where>=0:spans.append((max(0,where-250),min(len(text),where+2600)))
    if len(spans)==1:
        for match in list(re.finditer(r'(?i)\bSL[- ]1\b',text))[:4]:
            spans.append((max(0,match.start()-200),min(len(text),match.start()+2400)))
    merged=[]
    for a,b in sorted(spans):
        if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:merged.append((a,b))
    return '\n[...selected source excerpt...]\n'.join(text[a:b] for a,b in merged)[:15000]

def index(folder):
    path=safe(Path(folder)/INDEX)
    return read(path) if path.is_file() else dict(version='verified-public-text-v41',sources={})

def cached(folder,url):
    folder=Path(folder);row=index(folder)['sources'].get(url)
    if not row or row.get('state')!='available':return None
    if row.get('url')!=url:raise Failure('documentary_factual_snapshot_url_changed')
    for key,digest in (('file','text_sha256'),('raw_file','raw_sha256')):
        name=row.get(key)
        if not isinstance(name,str) or Path(name).name!=name:raise Failure('documentary_factual_snapshot_path')
        if hashlib.sha256(safe(folder/name).read_bytes()).hexdigest()!=row[digest]:
            raise Failure('documentary_factual_snapshot_changed')
    text=(folder/row['file']).read_text()
    if excerpt(text,row.get('focus',()))!=row.get('content'):
        raise Failure('documentary_factual_excerpt_changed')
    return dict(row)

def store(folder,url,raw,text,*,transport,focus=(),http_status=None):
    folder=Path(folder);name='factual-v41-'+identifier(url)
    from documentary_common import safe_path
    for suffix,data in (('.raw',raw),('.txt',text.encode())):
        path=safe_path(folder/(name+suffix))
        with path.open('xb') as stream:
            __import__('os').fchmod(stream.fileno(),0o600);stream.write(data)
    row=dict(url=url,state='available',transport=transport,http_status=http_status,
        file=name+'.txt',raw_file=name+'.raw',text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        raw_sha256=hashlib.sha256(raw).hexdigest(),content=excerpt(text,focus),focus=list(focus),
        retrieved_at=now(),full_text_characters=len(text),full_raw_preserved=True,
        raw_scope='bounded_provider_text' if transport=='saved_deepseek_fetch_text' else 'retrieved_http_body',ai_requests=0)
    value=index(folder);value['sources'][url]=row;write(folder/INDEX,value)
    return cached(folder,url)

def native_get(url):
    from documentary_media import public_url,Redirect
    public_url(url)
    request=urllib.request.Request(url,headers={
        'User-Agent':'VideoOptimizerDocumentary/41 (+https://publisher.mathrelaxing.store)',
        'Accept':'text/html,text/plain;q=0.9,*/*;q=0.1','Accept-Encoding':'identity'})
    with urllib.request.build_opener(Redirect()).open(request,timeout=35) as response:
        raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise Failure('documentary_factual_response_too_large')
        return raw,response.status

def fetch_source(folder,url,guard=lambda:None,focus=()):
    folder=Path(folder);value=index(folder)
    if url in value['sources']:return cached(folder,url)
    if sum(s.get('transport')=='controller_native_http' for s in value['sources'].values())>=MAX_NATIVE:return None
    # Validate before the intent as well as every actual redirect, without credentials.
    from documentary_media import public_url
    guard()
    try:public_url(url)
    except OSError:
        value['sources'][url]=dict(url=url,state='unavailable',transport='controller_native_http',error_type='DNSUnavailable')
        write(folder/INDEX,value);return None
    value['sources'][url]=dict(url=url,state='intent',transport='controller_native_http',at=now())
    write(folder/INDEX,value)
    try:
        raw,status=native_get(url)
        if not 200<=status<300:raise Failure('documentary_factual_http_error')
        text=extracted(raw)
    except (OSError,ValueError,urllib.error.URLError,Failure) as exc:
        if isinstance(exc,Failure) and str(exc) in ('documentary_cancelled','documentary_sources_inputs_changed'):
            raise
        value=index(folder);value['sources'][url].update(state='unavailable',
            error_type=type(exc).__name__,http_status=getattr(exc,'code',None))
        write(folder/INDEX,value);return None
    guard()
    return store(folder,url,raw,text,transport='controller_native_http',focus=focus,http_status=status)

def import_cached_fetch(folder,url,tools):
    current=index(folder)['sources'].get(url)
    if current:return cached(folder,url)
    for record in tools.values():
        if record.get('kind')!='fetch' or record.get('request',{}).get('url')!=url:continue
        if record.get('result',{}).get('state') in ('unavailable','error'):continue
        text=record.get('result',{}).get('content')
        if not isinstance(text,str) or len(text.strip())<350:continue
        return store(folder,url,text.encode(),text,transport='saved_deepseek_fetch_text',http_status=None)
    return None

def available(folder):
    return {url:cached(folder,url) for url,row in index(folder)['sources'].items() if row.get('state')=='available'}

def diagnostics(folder):
    """Saved receipts only; no credentials, text bodies, signed queries or network."""
    from urllib.parse import urlsplit
    rows=[]
    for url,row in index(folder)['sources'].items():
        parsed=urlsplit(url)
        item=dict(source_url=f'{parsed.scheme}://{parsed.hostname}{parsed.path}',
            source_fingerprint=identifier(url),state=row.get('state'),transport=row.get('transport'),
            http_status=row.get('http_status'))
        if row.get('state')=='available':
            verified=cached(folder,url);item['text_characters']=verified['full_text_characters']
        rows.append(item)
    return dict(sources=rows,available=sum(r['state']=='available' for r in rows),
        native_gets=sum(r['transport']=='controller_native_http' for r in rows),
        note='Saved public-text receipts, not a live source check. No text bodies or query parameters returned.')

def prepare_sl1(folder,guard=lambda:None):
    """Only concrete archival alternatives; no guessed reports, paid search or API retries."""
    from deepseek_runtime import workspace
    root=workspace(folder);tools=read(root/'tools.json') if (root/'tools.json').is_file() else {}
    wiki='https://en.wikipedia.org/wiki/SL-1'
    import_cached_fetch(folder,wiki,tools)
    seeds=[('https://inl.gov/20-questions/',()),
        ('https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=10005472.TXT',
            ('On the evening of January 3','2.1 SL-1','In November 1962','three operators')),
        ('https://digital.library.unt.edu/ark:/67531/metadc1053436/',())]
    for url,focus in seeds:
        guard();fetch_source(folder,url,guard,focus)
        current=available(folder)
        if len(current)>=3:break
    result=available(folder)
    if len(result)<2 or not any(r['transport']=='controller_native_http' for r in result.values()):
        raise Failure('documentary_factual_primary_source_unavailable')
    return result
