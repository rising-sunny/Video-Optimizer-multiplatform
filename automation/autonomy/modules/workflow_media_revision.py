"""Explicit Curie WWI media revision, using native acquisition/render/reviews.

The approved parent and its exhausted generation ledger are immutable. This is
a separately requested edit with one new evidence assessment, no new planning,
and a ceiling equal to the parent's unspent monetary allowance. Never publishes.
"""
import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
from urllib.parse import urlencode, urlsplit

import workflow_common as c

VERSION='curie-wwi-media-v51'
PARENT='cf2a22d4f40f453fba2b3af137b716d1'
CHANNEL='stunning-facts-of-history'
VIDEO='b9b4c5a7521533755d56cc068b61127cd17e175f73a68234374e5efddfb4699f'
APPROVAL='7d57ffba1792fe5f0979b060210846ab337a9e659601f727b39d58cf0c762c5d'
REQUEST_ID='revise-curie-wwi-media-20261107-v1'
TOPIC='Revise the approved Marie Curie Short cf2a22d4f40f453fba2b3af137b716d1 with more varied genuine WWI photographs and two moving archival excerpts. Prioritize Curie in a mobile X-ray unit, field radiography, radiology trainees, ambulances and nurses. Label contextual wartime footage honestly. Preserve all factual cards, crisp Catarsis serif typography, 55-second duration, quiet break, no narration and Measured Paces music. Keep the approved parent and its counters unchanged. One fresh factual/rights assessment and one actual visual assessment of the changed media, within the original remaining dollar ceiling. Generation only; no publication.'
FILES=('editorial-plan.json','history-input.json','music-input.json','music-license-evidence.json',
       'publisher-catalog.json','publisher-track-template.html','publisher-music-faq.html')

# Existing file titles observed on Commons, never invented by the text model.
# Each is re-read through the official API before selection and native download.
SLOTS=(
 ('mobile','File:Marie Curie - Mobile X-Ray-Unit.jpg','Curie, mobile X-ray unit, c.1915','event','image'),
 ('portrait','File:Marie Curie 1903.jpg','Marie Curie, 1903','event','image'),
 ('hospital','File:American Ambulance field hosp. at Verdun LOC 15241858629.jpg','Field hospital, Verdun, WWI context','context','image'),
 ('xray','File:"French Field Hospital - Locating Bullet with X-Ray Machine".jpg','French field-hospital X-ray, c.1914–18','context','image'),
 ('trainees','File:Irène Curie and Suzanne Veil (left) among the 7th group of radiology nurses trained at the Radium Institute, November 1917.webp','Radiology trainees with Irène Curie, 1917','event','image'),
 ('ambulances',"File:20-7-1915 (90) autos-ambulances offertes par l'Angleterre (exposées dans la cour d'honneur de l'Hôtel des Invalides) - btv1b69084793.jpg",'Ambulances, Paris, 1915 (context)','context','image'),
 ('nurses','File:Medical Department - Nurses - In Theater of Operations - American nurses in Nice. Three American nurses of the Franco-American Hospital at Nice going to their work in the morning on the sunny promenade Dos Anglais - NARA - 45496582.jpg','Hospital nurses, Nice, 1918 (context)','context','image'),
 ('front','File:9.2inchhowitzerfiringWWI.ogv','Western Front artillery, 1914–18 (context)','context','video'),
)

def matches(request):
    return request==dict(operation='generation_start_single',request_id=REQUEST_ID,channel=CHANNEL,topic=TOPIC)

def inspect_parent():
    from generation_worker import preflight
    state,job=c.paths('catarsis',PARENT,CHANNEL)
    task,status=c.read(state/'request.json'),c.read(state/'status.json')
    if (status.get('state')!='ready' or task.get('publication_allowed') is not False
        or set(task.get('topics',{}))!={CHANNEL} or (state/'STOP').exists()
        or c.digest(job/'video.mp4')!=VIDEO or c.digest(job/'approval.json')!=APPROVAL
        or any((job/n).exists() for n in ('publication.json','.transport.json','tiktok-draft.json'))
        or (c.STATE/'catarsis-publication'/PARENT).exists()):
        raise RuntimeError('workflow_media_revision_approved_unpublished_parent_required')
    import sys
    sys.path.insert(0,'/home/videoagent/video-automation');import daily_core
    daily_core.approval(job,CHANNEL,task['date']);preflight()
    budget=c.read(c.ledger(job)/'budget.json')
    if budget.get('pending') is not None or budget.get('estimated_usd',1)>=.20:
        raise RuntimeError('workflow_media_revision_parent_budget_unavailable')
    return dict(version=VERSION,batch_id=PARENT,video_sha256=VIDEO,approval_sha256=APPROVAL,
        files={n:c.digest(job/n) for n in FILES},ledger=c.tree(c.ledger(job)),
        estimated_usd=budget['estimated_usd'],counts=budget['counts'],
        residual_ceiling_usd=round(.20-budget['estimated_usd'],6),publication_allowed=False)

def verify_parent(binding):
    _,job=c.paths('catarsis',PARENT,CHANNEL)
    if (binding.get('version')!=VERSION or binding.get('batch_id')!=PARENT
        or binding.get('video_sha256')!=VIDEO or binding.get('approval_sha256')!=APPROVAL
        or c.digest(job/'video.mp4')!=VIDEO or c.digest(job/'approval.json')!=APPROVAL
        or any(c.digest(job/n)!=v for n,v in binding['files'].items())
        or c.tree(c.ledger(job))!=binding['ledger']):
        raise RuntimeError('workflow_media_revision_parent_changed')
    return job

def start(broker,request,original):
    from generation_service import denied,safe_error
    if not matches(request):return denied('workflow_media_revision_exact_request_required')
    # The native idempotency index is authoritative, including after disconnects.
    if REQUEST_ID in broker.index()['requests']:return original(broker,request)
    try:
        binding=inspect_parent();queued=[];launch=broker.launch
        broker.launch=queued.append
        try:value=original(broker,request)
        finally:broker.launch=launch
        if value.get('state')!='accepted' or len(queued)!=1:
            return value
        ident=value['batch_id'];path=broker.state/ident/'request.json';task=c.read(path)
        task.update(revision_of=PARENT,media_revision=binding);c.write(path,task)
        from workflow_jobs import enroll
        enroll('catarsis',ident,state_root=broker.state)
        launch(queued[0]);return broker.status(ident)
    except Exception as exc:return denied(safe_error(exc))

def official_rows(payload):
    """Reject missing, incorrectly typed, unlicensed or oversized API records."""
    from documentary_media import clean
    rows={}
    for page in payload.get('query',{}).get('pages',{}).values():
        if int(page.get('pageid',-1))<=0 or not page.get('imageinfo'):continue
        info=page['imageinfo'][0];meta=info.get('extmetadata',{})
        field=lambda k:clean(meta.get(k,{}).get('value',''))
        url,source=info.get('url',''),info.get('descriptionurl','')
        p,sp=urlsplit(url),urlsplit(source)
        ext=Path(p.path).suffix.lower()
        kind='image' if ext in {'.jpg','.jpeg','.png','.webp','.tif','.tiff'} else 'video' if ext in {'.ogv','.webm','.mp4'} else None
        if (field('LicenseShortName')!='Public domain' or not kind
            or p.scheme!='https' or p.hostname!='upload.wikimedia.org' or p.username or p.password
            or sp.scheme!='https' or sp.hostname!='commons.wikimedia.org' or sp.username or sp.password
            or not 0<info.get('size',0)<=(24 if kind=='image' else 120)*1024*1024):continue
        row=dict(commons_title=page['title'],type=kind,url=url,source_url=source,
            pageid=page['pageid'],author=field('Artist') or 'Unidentified author',collection=field('Credit'),
            license='Public domain',license_url=field('LicenseUrl') or source,
            date=field('DateTimeOriginal') or field('DateTime'),description=field('ImageDescription'),metadata=info)
        # Short institution names come from that very provider record. Full
        # metadata and the canonical file URL remain in the preserved receipt.
        raw=json.dumps(info,ensure_ascii=False).lower();author=row['author']
        author=author.replace('Unknown author Unknown author','Unknown author')
        if 'international film service' in raw:author='International Film Service'
        institutions=[label for token,label in (('nobel','Nobel Foundation'),('missouri history','Missouri History Museum'),
            ('nara','NARA'),('loc.gov','Library of Congress'),('bnf.fr','BnF'),('radium institute','Radium Institute'),
            ('us army signal corps','US Army Signal Corps')) if token in raw]
        row['credit']='; '.join(dict.fromkeys([author]+institutions+['Wikimedia Commons']))
        rows[page['title'].replace('_',' ')]=row
    return rows

def revised_plan(parent,rows,day,topic):
    plan=copy.deepcopy(parent);assets=[]
    for key,title,label,role,kind in SLOTS:
        row=rows.get(title.replace('_',' '))
        if row is None or row['type']!=kind:raise RuntimeError('workflow_media_revision_verified_'+key+'_missing')
        assets.append(dict(commons_title=row['commons_title'],type=kind,role=role,label=label,
            reason='Period subject photograph' if role=='event' else 'Dated WWI context; not identified as Curie\'s own team or unit',
            credit=row['credit'],**({'in':2.0} if kind=='video' else {'in':0})))
    old=parent['project']['sequence'];seq=[]
    def media(index,seconds,act,transition='cut',offset=0):
        scene=dict(kind='overlay',media=index,seconds=seconds,text=assets[index]['label'],
            act=act,motion='hold' if index==7 else 'push',transition=transition)
        if offset:scene['offset']=offset
        return scene
    seq=[copy.deepcopy(old[0]),media(0,old[1]['seconds'],'hook'),
        media(1,2.0,'rise'),media(2,old[2]['seconds']-2.0,'rise'),
        media(3,old[3]['seconds'],'rise'),copy.deepcopy(old[4]),
        media(7,old[5]['seconds'],'rise','burn'),copy.deepcopy(old[6]),
        media(4,old[7]['seconds'],'rise'),copy.deepcopy(old[8]),
        media(5,old[9]['seconds'],'turn'),media(7,old[10]['seconds'],'turn','burn',offset=7.0),
        copy.deepcopy(old[11]),copy.deepcopy(old[12]),media(6,old[13]['seconds'],'release','burn'),
        copy.deepcopy(old[14]),media(0,old[15]['seconds'],'end')]
    if (round(sum(s['seconds'] for s in seq)*30)!=1650
        or [s['text'] for s in seq if s['kind']=='card']!=[s['text'] for s in old if s['kind']=='card']
        or {s.get('media') for s in seq if 'media' in s}!=set(range(8))):
        raise RuntimeError('workflow_media_revision_timing_or_words_changed')
    plan.update(date=day,topic=topic,assets=assets)
    plan['project'].update(sequence=seq,total_seconds=55.0,media_scenes=10,text_cards=6,transition_count=3,burn_count=3)
    plan['thumbnail']=dict(media=0,text='Her wartime lab had wheels')
    for network,field in (('youtube','description'),('facebook','description'),('instagram','caption')):
        plan['metadata'][network][field]=parent['metadata'][network][field].split('\n\n')[0].replace(' A short, quiet portrait, no narration.','')
    return plan

def prepare(job,task,guard):
    from documentary_media import fetch
    from shorts_media import VERSION as CATALOG,FILE
    binding=task['media_revision'];parent=verify_parent(binding);job=Path(job)
    for name in FILES:
        if name!='editorial-plan.json':shutil.copyfile(parent/name,job/name);(job/name).chmod(0o600)
    from documentary_sources import INDEX,index
    evidence=index(parent)
    for row in evidence['sources'].values():
        if row.get('state')=='available':
            for key in ('file','raw_file'):
                name=row[key]
                if Path(name).name!=name:raise RuntimeError('workflow_media_revision_source_path')
                shutil.copyfile(c.safe(parent/name),job/name);(job/name).chmod(0o600)
    c.write(job/INDEX,evidence)
    root=c.ledger(job);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    tools=c.read(c.ledger(parent)/'tools.json')
    c.write(root/'tools.json',{key:row for key,row in tools.items() if row.get('kind')=='fetch'})
    params=dict(action='query',format='json',prop='imageinfo',iiprop='url|size|mime|extmetadata',
        titles='|'.join(s[1] for s in SLOTS),redirects=1)
    raw=fetch('https://commons.wikimedia.org/w/api.php?'+urlencode(params),4*1024*1024,guard,job)
    (job/'wwi-official-file-metadata.json').write_bytes(raw)
    rows=official_rows(json.loads(raw))
    plan=revised_plan(c.read(parent/'editorial-plan.json'),rows,task['date'],task['topics'][CHANNEL])
    c.write(job/FILE,dict(version=CATALOG,channel=CHANNEL,
        topic_sha256=hashlib.sha256(task['topics'][CHANNEL].encode()).hexdigest(),
        checked_at=__import__('deepseek_runtime').now(),metadata_requests=1,
        items=list(rows.values()),source_errors=[],ai_requests=0))
    c.write(job/'editorial-plan.json',plan)
    c.write(job/'media-revision-provenance.json',dict(binding,request_id=task['request_id'],
        new_planning_calls=0,new_evidence_reviews_max=1,new_visual_reviews_max=1,
        old_approval_reused_for_new_media=False,parent_preserved=True))
    guard();verify_parent(binding)

@contextmanager
def context(editorial,job,task,guard):
    """Only the new revision's one evidence call can consume residual budget."""
    import deepseek_runtime as rt
    from workflow_jobs import source_delivery
    binding=task['media_revision'];verify_parent(binding)
    old_limits,old_estimate=rt.LIMITS,rt.MAX_ESTIMATE
    old_external,old_music,old_prepare=editorial.external,editorial.music_evidence,editorial.prepare_media
    def music(directory,catalog):
        if Path(directory)!=Path(job):raise RuntimeError('workflow_media_revision_music_scope')
        proof=c.read(job/'music-license-evidence.json')
        for name,digest in proof['evidence_files'].items():
            if c.digest(job/name)!=digest:raise RuntimeError('workflow_media_revision_music_evidence_changed')
    def acquired(*args,**kwargs):
        plan,media,credits=old_prepare(*args,**kwargs)
        rows={r['commons_title']:r for r in c.read(job/'shorts-media-v34.json')['items']}
        for asset,credit in zip(plan['assets'],credits):
            row=rows[asset['commons_title']]
            if credit['license']!=row['license']:raise RuntimeError('workflow_media_revision_rights_changed')
            alias='https://commons.wikimedia.org/?curid='+str(row['pageid'])
            credit['canonical_source_url']=credit['source_url'];credit['source_url']=alias
            if credit['license']=='Public domain':credit['license_url']=alias
        return plan,media,credits
    try:
        rt.LIMITS=dict(chat=1,search=0,fetch=0,invocations=1,input_tokens=100000,output_tokens=2200)
        rt.MAX_ESTIMATE=binding['residual_ceiling_usd']
        editorial.external=source_delivery(job,old_external,guard)
        editorial.music_evidence=music;editorial.prepare_media=acquired
        yield
    finally:
        rt.LIMITS,rt.MAX_ESTIMATE=old_limits,old_estimate
        editorial.external,editorial.music_evidence,editorial.prepare_media=old_external,old_music,old_prepare
        verify_parent(binding)
        path=c.ledger(job)/'budget.json'
        if path.is_file():
            current=c.read(path)
            c.write(job/'media-revision-usage.json',dict(parent_batch_id=PARENT,
                parent_counts=binding['counts'],revision_counts=current['counts'],
                parent_estimated_usd=binding['estimated_usd'],revision_estimated_usd=current['estimated_usd'],
                cumulative_estimated_usd=round(binding['estimated_usd']+current['estimated_usd'],6),
                cumulative_ceiling_usd=.20,parent_ledger_unchanged=True))
