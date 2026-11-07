"""Evidence-first archive preparation for the requested Skylab rescue film.

Real provider records are acquired before the text plan. No models, budget
changes, invented media, publication or replacement of existing jobs.
"""
import re
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

VERSION='skylab-evidence-and-variety-v53'
TITLE="Skylab: NASA's Space Station Broke Before Its Crew Arrived"
SOURCES=(
 'https://www.nasa.gov/history/50-years-ago-skylab-2-the-we-fix-anything-crew/',
 'https://www.nasa.gov/history/50-years-ago-skylab-2-astronauts-deploy-jammed-solar-array-during-spacewalk/',
 'https://www.nasa.gov/history/50-years-ago-skylab-2-astronauts-splash-down-after-record-breaking-28-day-mission-2/',
)
QUERIES=('Skylab filetype:video','Skylab 2','Skylab parasol','Skylab solar array',
         'Skylab launch 1973','Skylab training','Skylab Conrad Kerwin','Skylab mission control')
FILMS=('Skylab_TheFirst40Days','B-Roll_Skylab','Skylab-SpaceStationI')

def matches(task):
    return (task.get('channel')=='stunning-revelations' and
            re.match(r'^Skylab\s*:',task.get('topic',''),re.I) is not None and '1973' in task['topic'])

def compact_sources(catalog,pageids):
    """Verified page-ID aliases keep all creators/links inside credit limits."""
    for row in catalog['items']:
        if row.get('provider')!='commons':continue
        title=row.get('evidence',{}).get('file_title','').replace('_',' ')
        pageid=pageids.get(title)
        if type(pageid) is not int or pageid<=0:continue
        canonical=row['source_url'];alias='https://commons.wikimedia.org/?curid='+str(pageid)
        row['evidence']['canonical_source_url']=canonical;row['evidence']['official_pageid']=pageid
        row['source_url']=alias
        if row['license_url']==canonical:row['license_url']=alias
        row['id']='M'+hashlib.sha256((row['provider']+'\n'+alias+'\n'+row['url']).encode()).hexdigest()[:16]

def prepare(folder,task):
    if not matches(task):return None
    from documentary_sources import fetch_source
    from documentary_catalog import Catalog,VERSION as CATALOG_VERSION
    from documentary_common import read,save,Failure
    from documentary_media import fetch
    folder=Path(folder)
    factual={}
    for url in SOURCES:
        row=fetch_source(folder,url,focus=('Skylab','parasol','solar array','spacewalk','Conrad','June 7','May 25'))
        if row and row.get('state')=='available':factual[url]=row
    if len(factual)<2:raise Failure('documentary_skylab_primary_evidence_missing')
    path=folder/'media-catalog.json'
    if path.exists():
        catalog=read(path)
        if catalog.get('version')!=CATALOG_VERSION or catalog.get('topic')!=task['topic']:
            raise Failure('documentary_catalog_input_changed')
    else:
        pageids={}
        def getter(url,limit):
            raw=fetch(url,limit,folder=folder)
            parsed=urlsplit(url)
            if parsed.hostname=='commons.wikimedia.org' and parsed.path=='/w/api.php':
                for page in json.loads(raw).get('query',{}).get('pages',{}).values():
                    if page.get('imageinfo') and type(page.get('pageid')) is int:
                        pageids[page.get('title','').replace('_',' ')]=page['pageid']
            return raw
        box=Catalog(getter)
        # Moving archive is discovered before stills fill the bounded catalogue.
        for ident in FILMS:
            box.attempt('internet_archive','identifier:'+ident,lambda i=ident:box.archive('identifier:'+i))
        for query in QUERIES:
            box.attempt('commons',query,lambda q=query:box.commons(q))
        catalog=box.result();compact_sources(catalog,pageids)
        catalog['topic']=task['topic'];save(path,catalog)
    images=sum(r['type']=='image' for r in catalog['items']);clips=sum(r['type']=='video' for r in catalog['items'])
    if images<14 or clips<2 or len(catalog['items'])<18:raise Failure('documentary_skylab_archive_variety_missing')
    save(folder/'production-brief-v53.json',dict(version=VERSION,title=TITLE,
        factual_urls=list(factual),offered_photographs=images,offered_video_sources=clips,
        selected_unique_assets_min=18,original_model_limits_preserved=True,
        narration_regenerated=False,publication_allowed=False))
    return factual

def brief(task):
    if not matches(task):return ''
    return '''
USER-REQUESTED SKYLAB PRODUCTION BRIEF:
Use the working title "Skylab: NASA's Space Station Broke Before Its Crew Arrived".
Open in the first 15 seconds on a damaged, overheating, underpowered station in orbit
while its first crew remains on Earth. Promise the two-part repair, not a generic
history of NASA. Chronology: May 14 launch damage; ground engineering and training;
May 25 first crew and failed initial repair; May 26 parasol; June 7 Conrad/Kerwin
solar-array spacewalk; June 22 return and what the rescued laboratory achieved.
Cooling the station and restoring its electrical power are separate challenges.
Credit engineers, technicians, controllers and the three astronauts. No invented
dialogue or thoughts; quotations need exact primary support. Do not confuse the
first crew's repair with the later unflown August 1973 rescue-vehicle contingency.
Choose 18-24 DISTINCT offered resources, including at least TWO verified moving
video sources. All assets must actually be used by the narration's segment asset
references. Create 28-36 complete segments of 30-65 words, around 1400 words total,
with an integer asset index on EVERY segment. Maintain native word limits.
Give launch, damage, shield design, rehearsals, inspection, sunshade, array repair,
science and recovery their OWN relevant imagery. No generic aircraft, Apollo 13,
Shuttle or ISS material. Label ground demonstrations and 1972 preflight context
accurately; they are not recordings of the orbital repair. No modern recreation
of a historical event presented as real. Avoid cycling one wide view in every
chapter. Match each label to the chosen file's actual date and configuration.
Epidemic documentary tension should rise at the failed repair and June 7 attempt,
ease briefly after the parasol, and resolve with the operational station.
The final thumbnail is separate. Supply no model-generated historical footage.
'''

def validate(plan,catalog,task):
    if not matches(task):return plan
    from documentary_common import Failure
    rows={r['id']:r for r in catalog['items']}
    assets=plan['assets'];used={s['asset'] for s in plan['segments']}
    primary=[a['media_ids'][0] for a in assets]
    if (len(set(primary))<18 or used!=set(range(len(assets)))
        or sum(rows[i]['type']=='video' for i in set(primary))<2):
        raise Failure('documentary_skylab_selected_variety_insufficient')
    if plan['title']!=TITLE:raise Failure('documentary_skylab_title_binding_changed')
    return plan
