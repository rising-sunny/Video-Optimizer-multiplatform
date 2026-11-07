"""Source-bound curation before narration, after the workflow archives its inputs.

No approval, publication, budget changes, or new planning. Public media records
are fetched from the official Commons API; binary size caps remain unchanged.
"""
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit

JOB = '51c0cfdb56e743d88c68859e5b6df165'
FILM = 'File:Skylab - The First 40 Days.webm'
PHOTO = 'File:Skylab Station Viewed by Skylab 2 Command Module - GPN-2000-001709.jpg'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def official_record(title, fetcher):
    from documentary_catalog import item, host
    from documentary_media import clean
    movie = title == FILM
    prop = 'videoinfo' if movie else 'imageinfo'
    prefix = 'vi' if movie else 'ii'
    params = dict(action='query', format='json', prop=prop, titles=title, redirects=1)
    params[prefix+'prop'] = 'url|size|extmetadata'+('|derivatives' if movie else '')
    payload = json.loads(fetcher('https://commons.wikimedia.org/w/api.php?'+urlencode(params), 4*1024*1024))
    for page in payload.get('query', {}).get('pages', {}).values():
        if page.get('title') != title or type(page.get('pageid')) is not int or page['pageid'] <= 0:
            continue
        for info in page.get(prop, [])[:1]:
            meta = info.get('extmetadata', {})
            field = lambda k: clean(meta.get(k, {}).get('value', ''))
            candidates = [dict(src=info.get('url'), size=info.get('size'))]
            if movie:
                # Select an actual provider rendition; never compute a media URL.
                candidates = [d for d in info.get('derivatives', [])
                              if d.get('height') == 360 and str(d.get('type', '')).startswith('video/webm')]
            for variant in candidates:
                url = variant.get('src', '')
                if not host(url, {'upload.wikimedia.org'}):
                    continue
                source = 'https://commons.wikimedia.org/?curid='+str(page['pageid'])
                license_url = field('LicenseUrl') or source
                row = item('commons', source, url, title, field('ImageDescription'),
                    field('Artist'), field('LicenseShortName'), license_url,
                    field('DateTimeOriginal'), variant.get('size'),
                    dict(file_title=title, official_pageid=page['pageid'], metadata=info,
                         canonical_source_url=info.get('descriptionurl'), chosen_derivative=variant))
                if row:
                    return row
    raise RuntimeError('workflow_skylab_official_media_unavailable')


def curated(value, catalogue, film, photo):
    """Correct chronology, misleading pairings and the native 24-asset cap."""
    result = copy.deepcopy(value)
    old = result['assets']
    # Conservative context labels describe the file rather than a guessed event.
    labels = {
        0:'Skylab and crew launch vehicles, Kennedy Space Center, 4 May 1973',
        1:'Skylab launch, 14 May 1973',
        2:'Solar-array deployment test on Earth, 1970',
        3:'Kerwin, Conrad and Weitz: first Skylab crew, May 1973',
        5:'First Skylab crew at preflight breakfast, 25 May 1973',
        6:'Crew boards the astrovan before launch, 25 May 1973',
        7:'Parasol fabrication on Earth, Johnson Space Center, 23 May 1973',
        8:'Parasol deployment test on Earth, 23 May 1973',
        9:'NASA Skylab 2 mission footage, 1973',
        11:'Engineers test matching repair tools on Earth, June 1973',
        12:'Ground replica of the jammed-array problem, 5 June 1973',
        13:'Underwater repair rehearsal on Earth, May 1973',
        14:'Parasol partially extended: NASA illustration, circa 1973',
        15:'Parasol fully extended: NASA illustration, circa 1973',
        16:'Kerwin at the airlock: onboard TV image, 7 June 1973',
        18:'Station with parasol, photographed by departing first crew, June 1973',
        22:'Kerwin and Conrad demonstrate weightlessness, 1 June 1973',
        23:'Kerwin examines Weitz aboard Skylab, June 1973',
        24:'Repaired station photographed by departing first crew, 22 June 1973',
        25:'Skylab 2 splashdown and recovery, 22 June 1973',
    }
    for i, label in labels.items():
        old[i]['label'] = label
        old[i]['role'] = 'context'
    extra = [
        dict(type='video', role='context', label='Skylab: The First 40 Days, NASA mission film, 1973', media_ids=[film['id']]),
        dict(type='image', role='context', label='Damaged Skylab before parasol deployment, 25 May 1973', media_ids=[photo['id']]),
        dict(type='image', role='context', label='Crew moves ultraviolet experiment equipment in orbit, June 1973', media_ids=['M08d74666082cd288']),
        dict(type='image', role='context', label='Conrad and Kerwin conduct a medical experiment, 9 June 1973', media_ids=['Me8997c2018ed4901']),
    ]
    old.extend(extra)
    edits = {
        0: "May 1973. NASA's first space station reaches orbit damaged, overheated and short of electricity. Its first crew has not even left Earth. A shield has torn away, one solar wing is gone, and the other is trapped. Saving Skylab will take two different repairs: a sunshade built on the ground, and a difficult spacewalk to restore its power.",
        4: "Before launch, technicians had tested the solar wings on Earth. Their job was to unfold and turn sunlight into electricity for the workshop. Now one wing could not unfold at all. That changed the mission from a planned research visit into an engineering problem: how could the crew reach and release hardware never designed for this kind of repair?",
        8: "Technicians in Building 10 assembled the parasol and tested its deployment on the ground. Riggers and technicians turned the design into equipment the crew could carry. Controllers meanwhile worked out how to orient the damaged station. They had to balance collecting power from the telescope mount's solar panels against heating the exposed workshop. There was no single adjustment that solved both problems.",
        9: "Commander Pete Conrad, Pilot Paul Weitz and Science Pilot Joe Kerwin, a physician, prepared for a changed mission. Their spacecraft would carry repair equipment along with the crew. On May 25, 1973, the three men boarded the astrovan and headed for Pad 39B. The launch delay had given ground teams ten days to prepare their response.",
        11: "The first attempt to release the wing came before docking. Weitz stood in the Apollo spacecraft's open hatch while Kerwin held his legs and Conrad flew alongside the station. Weitz worked with a long tool, trying to release the obstruction. The attempt failed. The crew still had two jobs ahead of them: make the station habitable and recover its electrical power.",
        12: "After docking, the crew entered the overheated station. The first repair tackled cooling. On May 26, they extended the folded parasol through a scientific airlock. Its rods opened and the fabric spread over the workshop. These NASA drawings illustrate that deployment; they are not photographs of the repair. The design allowed the shade to be installed without another spacewalk.",
        13: "The sunshade lowered the workshop's temperatures, making the station habitable. It was a major change, but the electrical problem remained. The parasol could block sunlight from the workshop's skin; it could not unfold the trapped solar wing. The first repair had protected the laboratory from heat. A second operation was still needed to give its experiments the power they required.",
        16: "At Marshall, engineers tested tools matching those already carried into orbit. A cable-operated cutter severed a similar strip of metal on Earth. Extension rods let an astronaut use it from a distance. The white packing on the ground-test tools helped make them buoyant underwater. This photograph records the engineering work on Earth, not the spacewalk itself.",
        17: "On June 7, Conrad and Kerwin prepared to go outside, while Weitz remained inside. Conrad deliberately left cameras behind so he could concentrate on the repair. There is no exterior movie of this operation. The surviving pictures include images recorded from inside the station. That matters when reading the archive: a rehearsal or a drawing cannot stand in for a camera that was never there.",
        20: "When the hinge released, both astronauts tumbled, stopped by their tethers. The wing extended and its panels could unfold. Restored electrical power changed the station's prospects. Conrad and Kerwin also completed work at the telescope mount before returning inside. Their full spacewalk lasted three hours and twenty-five minutes; that duration includes those additional tasks, not just cutting the strap.",
        21: "With power restored, the crew could carry on with the laboratory's experiments. Kerwin, a physician as well as an astronaut, examined his crewmates. The medical work tracked how bodies adapted to an extended stay in weightlessness. The repaired station was becoming the research workplace it had been intended to be, rather than a vehicle devoted almost entirely to solving its own failures.",
        22: "Astronomy and Earth observation continued alongside the medical studies. On June 15, Weitz recorded a solar flare using the Apollo Telescope Mount. The crew also photographed Earth. Inside the workshop, they moved experiment equipment through weightlessness. Those ordinary working scenes are part of the rescue's result: the station could support the research that had justified launching it.",
        23: "Medical experiments made the astronauts both investigators and subjects. In one study, Kerwin helped Conrad into a device that applied reduced pressure around the lower body. Researchers were studying cardiovascular adaptation to spaceflight and the difficulties astronauts might face after returning to gravity. Restoring the laboratory's power had made room for this detailed work on living and working in orbit.",
        26: "Before departing, the crew photographed the repaired laboratory. The gold sunshade covered the workshop, and the freed wing extended beside it. Two separate repairs had made continued operations possible. The next crews would stay for fifty-nine and eighty-four days. What began with launch damage had become a station able to support months of research across its three crewed visits.",
        27: "The archive also shows Conrad running and jumping around the workshop's circular wall. It is a demonstration of movement in weightlessness, not a recording of the repair. The contrast is useful: the same crew that had struggled with a trapped solar wing could now work and move inside a functioning laboratory. These quieter scenes show what the repair had preserved.",
        28: "Skylab's recovery depended on work in many places: technicians built the parasol, engineers tested cutting tools, controllers managed the station, divers rehearsed procedures, and the astronauts carried out the repairs. The sunshade solved the heat problem. The June 7 spacewalk restored power. Keeping those two achievements separate shows how the rescue actually worked, and why it took a team on Earth as well as a crew in orbit.",
        29: "The first crew returned after twenty-eight days, having completed virtually all of its planned science. Skylab's story is therefore more than a narrow escape. A damaged station was turned into a working research laboratory. The photographs of its sunshade and extended wing record the practical outcome: repairs that let the mission continue, and let the crews who followed do their work.",
    }
    # Original segment indexes -> curated visual index. Every chosen file is used.
    mapping = {0:26,1:0,2:27,3:12,4:2,5:7,6:8,7:7,8:5,9:6,10:27,11:3,
               12:14,13:15,14:12,15:13,16:11,17:16,18:16,19:27,20:9,
               21:23,22:28,23:29,25:25,26:24,27:9,28:22,29:18}
    segments=[]
    for i,s in enumerate(result['segments']):
        if i not in mapping: continue
        if i in edits:s['narration']=edits[i]
        s['asset']=mapping[i]
        segments.append(s)
    used=sorted({s['asset'] for s in segments})
    translate={old_index:new_index for new_index,old_index in enumerate(used)}
    result['assets']=[old[i] for i in used]
    for s in segments:s['asset']=translate[s['asset']]
    result['segments']=segments
    result['claims']=result['claims'][:7]
    result['thumbnail']=dict(asset=translate[27],text='BROKEN IN ORBIT')
    result['description']=("In May 1973, Skylab reached orbit damaged and overheating before its first crew arrived. "
        "Follow the ground teams and Conrad, Weitz and Kerwin through two repairs: a parasol to cool the workshop "
        "and a spacewalk to release its solar wing. NASA photographs, ground tests, illustrations and mission film "
        "are identified by context. No exterior film of the June 7 repair is claimed.")
    offered={r['id']:r for r in catalogue['items']}
    if any(a['media_ids'][0] not in offered for a in result['assets']):
        raise RuntimeError('workflow_skylab_curated_media_not_offered')
    from documentary_common import validate_plan
    validate_plan(result)
    from workflow_documentary_brief import validate
    return validate(result,catalogue,dict(channel='stunning-revelations',topic='Skylab: 1973'))


def prepare(job, value, task, guard):
    if Path(job).name != JOB:return value
    from documentary_common import read,save,sha
    if task.get('channel') != 'stunning-revelations' or not task.get('topic','').startswith('Skylab:'):
        raise RuntimeError('workflow_skylab_request_changed')
    if (job/'video.mp4').exists() or any(job.glob('speech-*.wav')):
        raise RuntimeError('workflow_skylab_existing_artifact')
    receipt=job/'curated-plan-v53.json'
    if receipt.exists():
        previous=read(receipt)
        if previous.get('curated_fingerprint')==fingerprint(value):return value
        raise RuntimeError('workflow_skylab_curated_plan_changed')
    if fingerprint(value) != ORIGINAL_FINGERPRINT:
        raise RuntimeError('workflow_skylab_original_plan_changed')
    catalog=read(job/'media-catalog.json')
    from documentary_media import fetch
    def getter(url,limit):
        guard();return fetch(url,limit,guard,job)
    film=official_record(FILM,getter)
    photo=official_record(PHOTO,getter)
    updated=copy.deepcopy(catalog)
    for row in (film,photo):
        if not any(r['id']==row['id'] for r in updated['items']):updated['items'].append(row)
    if len(updated['items'])>72:raise RuntimeError('workflow_skylab_catalogue_limit')
    result=curated(value,updated,film,photo)
    guard()
    # Original job and ledger have already been archived by workflow_jobs.
    save(job/'editorial-plan-original-v53.json',value)
    save(job/'media-catalog-before-curation-v53.json',catalog)
    save(job/'media-catalog.json',updated)
    save(receipt,dict(original_fingerprint=fingerprint(value),curated_fingerprint=fingerprint(result),
        source='three saved NASA historical accounts plus exact official media records',
        selected_assets=len(result['assets']),segments=len(result['segments']),
        corrected_visual_pairings=True,removed_unflown_rescue_subplot=True,
        original_model_response_and_ledger_preserved=True,ai_requests=0,publication_allowed=False))
    return result


ORIGINAL_FINGERPRINT = '5446d2241405b300360100ee32057d1a7ee10507a433b2e95292da5e5f4b5cbf'
