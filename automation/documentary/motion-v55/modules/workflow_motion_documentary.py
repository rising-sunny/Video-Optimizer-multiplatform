"""Evidence-first X-15 production with more actual moving archive. No publishing."""
import copy
import json
from pathlib import Path
import re
from urllib.parse import urlencode,urlsplit

PROFILE='motion-led-v55'
TITLE='X-15: The Rocket Plane That Had to Glide Home'
SOURCES=(
 'https://www.nasa.gov/reference/x-15/',
 'https://www.nasa.gov/history/x15/',
 'https://www.nasa.gov/history/65-years-ago-first-powered-flight-of-the-x-15-hypersonic-rocket-plane/',
)
FILMS=(
 'File:Research Project X-15 - development of the X-15 rocket plane - 1962 NASA documentary.webm',
 'File:X-15 Man Into Space.webm',
 'File:X-15 Pathway To The Skies.webm',
 'File:X-15 ROCKET RESEARCH AIRCRAFT PROGRAM OVERVIEW.webm',
)
QUERIES=('X-15 1959','X-15 B-52 1960','X-15 cockpit','X-15 XLR99',
         'X-15 1967 Knight','X-15 Walker 1963','X-15 landing 1960')

def matches(task):
    return task.get('channel')=='stunning-revelations' and bool(re.match(r'^X[ -]?15:',task.get('topic',''),re.I))

def active(plan):return plan.get('motion_profile')==PROFILE

def film_rows(payload):
    from documentary_catalog import item,host
    from documentary_media import clean
    result=[]
    for page in payload.get('query',{}).get('pages',{}).values():
        if page.get('title') not in FILMS or type(page.get('pageid')) is not int or page['pageid']<=0:continue
        for info in page.get('videoinfo',[])[:1]:
            meta=info.get('extmetadata',{});field=lambda k:clean(meta.get(k,{}).get('value',''))
            limit=120*1024*1024;variants=[]
            if type(info.get('size')) is int and 0<info['size']<=limit:
                variants=[dict(src=info.get('url'),size=info['size'],width=info.get('width'),height=info.get('height'))]
            else:
                duration=info.get('duration',0)
                variants=[d for d in info.get('derivatives',[]) if
                    str(d.get('type','')).startswith('video/webm') and
                    int(d.get('height',0))>=240 and int(d.get('width',0))>=320 and
                    isinstance(duration,(int,float)) and duration>0 and
                    isinstance(d.get('bandwidth'),(int,float)) and d['bandwidth']*duration/8*1.10<=limit]
                variants.sort(key=lambda d:int(d.get('height',0)),reverse=True)
            for variant in variants:
                url=variant.get('src','')
                if url.startswith('//upload.wikimedia.org/'):url='https:'+url
                if not host(url,{'upload.wikimedia.org'}):continue
                source='https://commons.wikimedia.org/?curid='+str(page['pageid'])
                restored=page['title']!=FILMS[0]
                note=('NASA X-15 program film, digitally restored copy (2025); not a recording of one named record flight.'
                    if restored else 'NASA documentary (1962); not the 1967 speed-record flight.')
                row=item('commons',source,url,page['title'],field('ImageDescription')+' '+note,
                    field('Artist'),field('LicenseShortName'),field('LicenseUrl') or source,
                    field('DateTimeOriginal'),variant.get('size'),dict(file_title=page['title'],metadata=info,
                    canonical_source_url=info.get('descriptionurl'),official_pageid=page['pageid'],
                    chosen_derivative=variant,restored_copy=restored,context_note=note))
                if row:result.append(row);break
    return result

def prepare(folder,task):
    if not matches(task):return None
    from documentary_sources import fetch_source
    from documentary_catalog import Catalog,VERSION
    from documentary_common import read,save,Failure
    from documentary_media import fetch
    folder=Path(folder);factual={}
    for url in SOURCES:
        row=fetch_source(folder,url,focus=('X-15','rocket','landing','Knight','Walker','1959','1967'))
        if row and row.get('state')=='available':factual[url]=row
    if len(factual)<2:raise Failure('documentary_motion_primary_sources_missing')
    path=folder/'media-catalog.json'
    if path.exists():
        catalog=read(path)
        if catalog.get('version')!=VERSION or catalog.get('topic')!=task['topic']:raise Failure('documentary_catalog_input_changed')
    else:
        pageids={}
        def getter(url,limit):
            raw=fetch(url,limit,folder=folder)
            if urlsplit(url).hostname=='commons.wikimedia.org':
                for p in json.loads(raw).get('query',{}).get('pages',{}).values():
                    if type(p.get('pageid')) is int:pageids[p.get('title','').replace('_',' ')]=p['pageid']
            return raw
        box=Catalog(getter)
        data=box.get('https://commons.wikimedia.org/w/api.php?'+urlencode(dict(
            action='query',format='json',prop='videoinfo',titles='|'.join(FILMS),
            viprop='url|size|extmetadata|derivatives',redirects=1)))
        save(folder/'motion-film-provider-response-v55.json',data)
        films=film_rows(data)
        for row in films:box.add(row)
        for query in QUERIES:box.attempt('commons',query,lambda q=query:box.commons(q))
        film_ids={f['id'] for f in films}
        box.rows={k:r for k,r in box.rows.items() if
            (r['title'] not in FILMS or r['id'] in film_ids) and
            (r['type']=='video' or not re.search(
            r'museum|replica|airshow|air show|war thunder|flight simulator',r['title'],re.I))}
        catalog=box.result()
        from workflow_documentary_brief import compact_sources
        originals=[r for r in catalog['items'] if r['id'] not in {f['id'] for f in films}]
        compact_sources(dict(items=originals),pageids)
        catalog['topic']=task['topic'];save(path,catalog)
    movies=[r for r in catalog['items'] if r['type']=='video' and r['title'] in FILMS]
    images=[r for r in catalog['items'] if r['type']=='image']
    if len(movies)<3 or len(images)<8:raise Failure('documentary_motion_archive_support_missing')
    save(folder/'motion-production-v55.json',dict(profile=PROFILE,title=TITLE,
        factual_urls=list(factual),available_film_works=len(movies),available_images=len(images),
        motion_target_fraction=.5,required_motion_fraction=.35,source_audio_removed=True,
        restored_copies_labeled=True,ai_requests=0,publication_allowed=False))
    return factual

def brief(task):
    if not matches(task):return ''
    return '''
USER MOTION-LED BRIEF (takes precedence over general asset-count suggestions):
Title: "X-15: The Rocket Plane That Had to Glide Home". Open with the engine
stopping and the unpowered return. Explain a TYPICAL compiled research-flight
profile; never invent one composite flight, pilot dialogue or private thoughts.
Then show B-52 release, rocket burn, heating, thin-air controls and lakebed landing.
Distinguish Walker's 1963 altitude record from Knight's October 1967 speed record;
they are different flights. US 50-mile and international 100-km thresholds differ.
Use 28-32 segments, 1200-1400 words, 6-8 chapters. Every segment has integer asset.
Choose 12-16 distinct offered assets (maximum 24), including THREE DIFFERENT
offered NASA film works and a real still for thumbnail. Use every chosen slot.
Assign VIDEO assets to at least HALF the segments, including segment zero.
Include Research Project X-15 (1962) as the main source, plus at least two other films.
The 1962 film is program context, not footage of the 1967 record flight. The other
named program films are digitally restored copies uploaded in 2025. Label them
"NASA X-15 film, restored copy (2025)"; do not infer historical filming dates from
upload dates. No Hollywood scenes or fictional crashes. If mentioning Adams's
1967 accident, use respectful factual context and no invented accident footage.
Labels <=90 characters. No new web tools. Narration stays continuous while the
controller uses more moving footage, purposeful cuts and chapter transitions.
'''

def normalize(value,catalog,task):
    if not matches(task) or value.get('blocked'):return value
    result=copy.deepcopy(value);assets=result.get('assets',[]);segments=result.get('segments',[])
    if not isinstance(assets,list) or not isinstance(segments,list):return result
    used={s.get('asset') for s in segments if isinstance(s,dict) and type(s.get('asset')) is int}
    thumb=result.get('thumbnail',{}).get('asset')
    if type(thumb) is int:used.add(thumb)
    if used and all(0<=i<len(assets) for i in used):
        indexes=sorted(used);remap={v:i for i,v in enumerate(indexes)}
        result['assets']=[assets[i] for i in indexes]
        for s in segments:
            if type(s.get('asset')) is int:s['asset']=remap[s['asset']]
        if type(thumb) is int:result['thumbnail']['asset']=remap[thumb]
    offered={r['id']:r for r in catalog['items']}
    # Observed transcription errors in the saved X-15 plan. Bind each repair to
    # the actual offered work; never guess a new identity from a similar label.
    corrections={
        'M18e691f016cf7de2':('M18e691f016cf7de1','File:X-15 launch from B-52 mothership (E-4942).jpg'),
        'M160020e83df7a42f':('M160020e83df7a42c','File:Joseph A Walker after X-15 flight -2-14-28 (EC68-1937).jpg'),
    }
    for a in result['assets']:
        ids=a.get('media_ids',[])
        if len(ids)==1 and ids[0] not in offered and ids[0] in corrections:
            target,title=corrections[ids[0]]
            if target in offered and offered[target]['title']==title:
                ids=[target];a['media_ids']=ids
        if len(ids)==1 and ids[0] in offered:
            row=offered[ids[0]];a['type']=row['type']
            if row.get('evidence',{}).get('restored_copy'):
                a['label']='NASA X-15 program film, digitally restored copy (2025)';a['role']='context'
            elif row['title']==FILMS[0]:
                a['label']='Research Project X-15, NASA film (1962; program context)';a['role']='context'
    result['motion_profile']=PROFILE
    return result

def validate(plan,catalog,task):
    if not matches(task):return plan
    from documentary_common import Failure
    rows={r['id']:r for r in catalog['items']}
    videos={rows[i]['title'] for a in plan['assets'] for i in a.get('media_ids',[]) if i in rows and rows[i]['type']=='video'}
    if len(videos)<3 or FILMS[0] not in videos:raise Failure('documentary_motion_three_film_works_required')
    return plan
