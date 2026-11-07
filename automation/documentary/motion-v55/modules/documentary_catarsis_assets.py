"""Broader contextual footage and mood-ranked Epidemic music, without text AI.

Resource bounds protect a small VPS; they are not creative caps or requirements
to use a single archive. Every imported work keeps its actual reuse statement.
"""
import io
import re
from pathlib import Path
from urllib.parse import urlsplit
from documentary_common import *
from documentary_media import clean, fetch
from documentary_catalog import Catalog, permitted, host, IMAGE_EXT, VIDEO_EXT

STYLE='documentary-catarsis-v31'

def verify_image(path):
    """Header verification alone accepts truncated JPEGs. Decode every pixel."""
    from PIL import Image, ImageFile
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise Failure('documentary_catarsis_strict_image_decoder_required')
    try:
        with Image.open(path) as im:
            if im.width*im.height>90_000_000:
                raise Failure('documentary_catarsis_image_size')
            im.load()
    except Image.DecompressionBombError:
        raise Failure('documentary_catarsis_image_size') from None
    except (OSError, ValueError, SyntaxError):
        raise Failure('documentary_catarsis_image_decode_failed') from None
GROUPS={
 'aircraft':r'b[ -]?52|stratofortress|refuel|kc[ -]?135|bomber|strategic air command|b[ -]?47',
 'weapon':r'mark[ -]?39|mk[ -]?39|bomb casing|recovered.*(?:bomb|weapon)|nuclear weapon',
 'farmland':r'farmland|countryside|rural|tobacco field|farm in',
 'base':r'seymour johnson|air force base|airfield',
 'laboratory':r'sandia|laborator',
 'test':r'castle bravo|nuclear test|hydrogen bomb test|ivy mike',
 'city':r'goldsboro.*(?:downtown|street|city)|downtown goldsboro',
}
STOP={'the','and','for','with','from','this','that','file','photo','image','video','footage','context','historical','archive','modern','jpg','jpeg','webm','mp4'}

def tokens(value):
    return {s for s in re.findall(r'[a-z0-9]+',clean(value).lower()) if len(s)>2 and s not in STOP}

def group(value):
    return {k for k,pattern in GROUPS.items() if re.search(pattern,value,re.I)}

def relevance(theme,row):
    text=' '.join(str(row.get(k,'')) for k in ('label','title','description'))
    # A shared base/laboratory name does not make an unrelated community
    # event, chapel or display-team visit relevant to the narrated subject.
    title=str(row.get('title') or row.get('label',''))
    for subject in ('blue angels','child abuse','turkey drive','giving campaign','chapel','p-51','community'):
        if subject in title.lower() and subject not in theme.lower():return 0
    if 'north carolina' in theme.lower() and 'south carolina' in title.lower():return 0
    a,b=group(theme),group(text)
    # Different named scene families are not interchangeable merely because
    # their descriptions also say "North Carolina", "Cold War" or "USAF".
    if a and b and not a&b:return 0
    overlap=tokens(theme)&tokens(text)
    return len(overlap)+(5 if a&b else 0)

def label(row):
    title=clean(row.get('title','')).removeprefix('File:')
    title=re.sub(r'\.(?:jpe?g|png|webp|tiff?|mp4|webm|ogv)$','',title,flags=re.I)
    # A label describes the item, never the historical event inferred by a model.
    date=clean(row.get('date',''))
    year=re.search(r'\b(?:18|19|20)\d{2}\b',date)
    suffix=year[0] if year else 'date not specified'
    if len(title)>115:title=title[:112].rsplit(' ',1)[0]+'…'
    return f"Context {'footage' if row['type']=='video' else 'image'}: {title} | {suffix}"

def inspect_clip(path,minimum=(480,270)):
    from documentary_render import probe,run
    value=probe(path);v=next(s for s in value['streams'] if s['codec_type']=='video')
    seconds=float(value['format']['duration'])
    if not 2<=seconds<=3600 or v['width']<minimum[0] or v['height']<minimum[1]:
        raise Failure('documentary_catarsis_clip_dimensions')
    frames=run(['ffmpeg','-v','error','-threads','2','-i',str(path),'-t',str(min(6,seconds)),
        '-vf','fps=2,scale=64:36','-an','-f','framemd5','-']).decode()
    hashes={s.rsplit(',',1)[-1].strip() for s in frames.splitlines() if s and not s.startswith('#')}
    if len(hashes)<3:raise Failure('documentary_catarsis_clip_static')
    return dict(duration_seconds=seconds,observed_distinct_frames=len(hashes),
        source_width=v['width'],source_height=v['height'],source_codec=v.get('codec_name'),
        reported_frame_rate=v.get('avg_frame_rate'),motion_sample_seconds=min(6,seconds),
        motion_assessment='decoded_source_frames_before_render_effects')

def verify_clip(path):
    value=inspect_clip(path)
    return value['duration_seconds'],value['observed_distinct_frames']

def measured_original_pool(folder,original,guard=lambda:None):
    """Measure already licensed original videos before the timeline uses duration.

    Existing SD archival sources can be used at 320x240 with explicit source
    disclosure and uncropped framing. New optional acquisitions keep their
    existing minimum. Source bytes and rights receipts are never rewritten.
    """
    pool=[]
    for index,row in enumerate(original):
        guard()
        if sha(row['file'])!=row['sha256']:raise Failure('documentary_catarsis_source_media_changed')
        value=dict(row,origin='approved_scene',original_asset=index)
        if row['type']=='video':
            receipt=folder/f'license-{index}.json'
            if not permitted(row['license']) or not receipt.is_file() or sha(receipt)!=row.get('evidence_sha256'):
                raise Failure('documentary_catarsis_original_clip_receipt_changed')
            record=read(receipt).get('record')
            if isinstance(record,dict) and any(record.get(k)!=row.get(k) for k in
                    ('type','source_url','author','license','license_url')):
                raise Failure('documentary_catarsis_original_clip_receipt_changed')
            measured=inspect_clip(row['file'],minimum=(320,240))
            value.update(measured)
            value['archival_low_resolution']=measured['source_width']<480 or measured['source_height']<270
            value['source_measurement']=dict(measured,source_sha256=row['sha256'],
                rights_receipt_sha256=row['evidence_sha256'],inferred_from_filename_or_fps=False)
        pool.append(value)
    return pool

def acquire(folder,plan,original,guard,progress,cached=(),fetcher=None):
    """Existing assets + diverse, relevant verified additions. Missing archives
    are recorded; they do not discard the successfully acquired material."""
    pool=measured_original_pool(folder,original,guard)
    from workflow_motion_documentary import active
    if active(plan):
        # The user's selected motion-led programme already has a verified mix.
        # Do not dilute it with duplicate aliases or modern museum stills.
        save(folder/'catarsis-catalog-v31.json',dict(version='motion-led-v55',
            items=[],source='verified_selected_originals',additional_requests=0))
        return pool
    for row in cached:
        if sha(row['file'])!=row['sha256']:raise Failure('documentary_catarsis_cached_clip_changed')
        pool.append(dict(row,origin='previous_context_clip'))
    box=Catalog(fetcher or (lambda u,n:fetch(u,n,guard,folder)),guard)
    themes=list(dict.fromkeys(a['label'] for a in plan['assets']))
    request=folder/'request-editorial.json'
    topic=read(request).get('topic','') if request.is_file() else ''
    if 'https://archive.org/details/gov.ntis.A13886VNB1' in topic:
        # This exact film was supplied with the request. Verify its actual records
        # before broad scene-label searches; no license or download URL is assumed.
        box.attempt('internet_archive','identifier:gov.ntis.A13886VNB1',
                    lambda:box.archive('identifier:gov.ntis.A13886VNB1'))
        query='"SL-1" "Briefing Film Report" filetype:video'
        box.attempt('commons_video',query,lambda:box.commons(query))
    # Reserve discovery for moving images across providers, before stills can
    # fill a catalogue. These are real searches, never guessed File titles.
    for theme in themes[:4]:
        query=' '.join(clean(theme).split()[:8])
        box.attempt('internet_archive',query,lambda q=query:box.archive(q))
        box.attempt('commons_video',query,lambda q=query:box.commons(q+' filetype:video'))
    for theme in themes[:4]:
        query=' '.join(clean(theme).split()[:8])
        box.attempt('loc',query,lambda q=query:box.loc(q))
    for theme in themes[:8]:
        box.attempt('commons',theme,lambda q=theme:box.commons(q))
    save(folder/'catarsis-catalog-v31.json',box.result())
    candidates=list(box.rows.values());used={r['source_url'] for r in pool}
    candidates=[r for r in candidates if r['source_url'] not in used and max((relevance(t,r) for t in themes),default=0)>=2]
    # Interleave subjects and providers, prioritizing video without requiring an
    # arbitrary number of clips to continue. Runtime counts report reality.
    candidates.sort(key=lambda r:(r['type']!='video',-max(relevance(t,r) for t in themes)))
    total=0;added=[];failures=[];per_theme={t:0 for t in themes}
    hosts={'commons':{'upload.wikimedia.org'},'loc':{'tile.loc.gov','cdn.loc.gov','www.loc.gov'},
           'internet_archive':{'archive.org'},'us_air_force':{'media.defense.gov'}}
    for row in candidates:
        guard()
        if len(added)>=24 or total>=1024*1024*1024:break
        theme=max(themes,key=lambda t:relevance(t,row))
        if per_theme[theme]>=4:continue
        if not permitted(row['license']) or not host(row['url'],hosts.get(row['provider'],set())):continue
        limit=(120 if row['type']=='video' else 24)*1024*1024
        progress('acquiring_catarsis_media',len(added),None)
        try:
            data=(fetcher or (lambda u,n:fetch(u,n,guard,folder)))(row['url'],limit)
            if not data or len(data)>limit or (row.get('size') and len(data)!=row['size']):
                raise Failure('documentary_catarsis_media_size')
            path=folder/f'catarsis-media-{len(added):02}{Path(urlsplit(row["url"]).path).suffix.lower()}'
            if row['type']=='image':
                verify_image(io.BytesIO(data))
            path.write_bytes(data);path.chmod(0o600)
            extra={}
            if row['type']=='video':
                seconds,motion=verify_clip(path)
                extra=dict(duration_seconds=seconds,observed_distinct_frames=motion)
            receipt=folder/f'catarsis-license-{len(added):02}.json'
            save(receipt,dict(record=row,file_sha256=sha(path),checked_at=now()))
            result=dict(file=str(path),sha256=sha(path),type=row['type'],role='context',label=label(row),
                source_url=row['source_url'],author=row['author'],license=row['license'],license_url=row['license_url'],
                evidence=receipt.name,evidence_sha256=sha(receipt),origin='new_context',
                title=row['title'],description=row['description'],date=row['date'],
                changes='Excerpted; animated framing; resized; transitions and context labels added; original clip audio removed.',**extra)
            pool.append(result);added.append(result);per_theme[theme]+=1;total+=len(data)
        except (Failure,OSError,ValueError,StopIteration) as exc:
            if isinstance(exc,Failure) and not str(exc).startswith(('documentary_source_','documentary_catarsis_media_',
                'documentary_catarsis_clip_','documentary_catarsis_image_','documentary_media_command_')):raise
            failures.append(dict(source_url=row['source_url'],error_code=error(exc)))
            if str(exc) in ('documentary_source_rate_limited','documentary_source_cooldown_required'):break
    save(folder/'catarsis-media-v31.json',dict(version=STYLE,assets=pool,additional=len(added),
        source_errors=box.errors,download_errors=failures,ai_requests=0))
    return pool

POSITIVE={'suspense':8,'suspenseful':8,'tension':8,'tense':8,'ominous':7,'investigative':7,
 'dark':5,'mysterious':5,'mystery':5,'documentary':5,'uneasy':5,'eerie':4,'ambient':3,
 'atmospheric':3,'cinematic':2,'minimal':2,'minimalist':2,'dramatic':2,'pulse':2,'pulsing':2}
NEGATIVE={'happy','cheerful','uplifting','upbeat','playful','comedy','comedic','festive','celebration',
 'romantic','romance','triumphant','heroic','funky','party','jingle','lullaby'}

MUSIC_PROFILE='investigative-epic-v43'

def music_score(track,profile=None):
    if profile==MUSIC_PROFILE:
        # Provider metadata, never a title or BPM alone, must support drive.
        tags=tokens(' '.join(str(t.get('name','')) for t in track.get('tags',[])))
        if tags&{'happy','cheerful','playful','romantic','carefree','relaxing','peaceful','meditative','sleep','calm'}:return -100
        tension=tags&{'suspense','suspenseful','tension','tense','ominous','dark','dramatic','drama','mysterious','epic'}
        drive=tags&{'epic','powerful','energetic','intense','action','driving','percussion','percussive','pulsing','pulse','rhythmic','trailer','dramatic'}
        if not tension or not drive:return -1
        score=10+5*len(tension)+7*len(drive)
        score+=4*len(tags&{'orchestral','strings','brass','cinematic','documentary','investigative','building','build'})
        score-=8*len(tags&{'ambient','minimal','minimalist','soft','gentle','slow','sparse'})
        energy=[tokens(str(t.get('name',''))) for t in track.get('tags',[]) if 'energy' in str(t.get('dimension','')).lower()]
        if any(v&{'low','verylow'} for v in energy):return -1
        if any(v&{'high','veryhigh'} for v in energy):score+=12
        bpm=track.get('bpm')
        if type(bpm) in (int,float):score+=5 if 75<=bpm<=145 else -2
        return score
    if profile is not None:raise Failure('documentary_music_profile_unknown')
    # Titles are not evidence of mood. Rank actual provider tags and tempo,
    # never infer audible suitability from a dramatic-sounding title alone.
    tags=tokens(' '.join(str(t.get('name','')) for t in track.get('tags',[])))
    if tags&NEGATIVE:return -100
    score=sum(weight for word,weight in POSITIVE.items() if word in tags)
    mood=tags&{'suspense','suspenseful','tension','tense','ominous','investigative','dark','mysterious','mystery','uneasy','eerie'}
    if not mood:return -1
    bpm=track.get('bpm')
    if type(bpm) in (int,float):score+=2 if 45<=bpm<=115 else -3
    return score

def music(folder,channel,topic,guard,exclude=(),profile=MUSIC_PROFILE):
    if channel!=CHANNELS[1]:
        # The installed Creator entitlement covers Revelations, not the other
        # channel. Use an explicitly attributed original local score there;
        # never extend the Epidemic account license by inference.
        return original_music(folder,channel,guard)
    from documentary_av_assets import native,bounded_read
    provider=native();policy=provider.rights(channel);guard()
    if profile not in (None,MUSIC_PROFILE):raise Failure('documentary_music_profile_unknown')
    queries=[
      'Investigative documentary thriller score, driving rhythmic pulse and percussion, dramatic orchestral strings, ominous tension with a strong build, medium to high energy, instrumental no vocals, serious historical stakes. Avoid calm ambient or relaxing beds. Subject: ',
      'Epic cinematic documentary suspense climax, intense percussion, powerful orchestral tension, urgent rhythmic ostinato, rising dramatic stakes and a solemn resolution, instrumental no vocals, not cheerful or celebratory. Subject: ']
    tracks={};searches=[];evidence_saved=False
    for index,query in enumerate(queries):
        directory=folder/f'music-search-v31-{index}';directory.mkdir(mode=0o700)
        try:catalog=bounded_read(lambda d=directory,q=query:provider.catalogue(d,channel,q+topic[:180]),guard)
        except Exception as exc:
            if str(exc)!='epidemic_no_eligible_instrumental_candidates':raise
            searches.append(dict(query=query,tracks=0,state='no_eligible_results'));continue
        searches.append(dict(query=query,tracks=len(catalog.get('tracks',[]))))
        for row in catalog.get('tracks',[]):
            if row.get('provider')=='epidemic' and row.get('instrumental_search_filter') is True and row.get('recording_id') not in exclude:
                tracks[row['recording_id']]=row
        if not evidence_saved:
            # Actual account scope/search receipt, never a fictional entitlement.
            import shutil
            shutil.copy2(directory/'music-license-evidence.json',folder/'music-license-evidence.json')
            evidence_saved=True
    score=lambda t:music_score(t,profile)
    candidates=sorted(tracks.values(),key=score,reverse=True)
    save(folder/'epidemic-catalogue.json',dict(provider='epidemic',channel=channel,tracks=list(tracks.values()),searches=searches))
    ranked=[dict(recording_id=t['recording_id'],title=t['title'],score=score(t),tags=t.get('tags',[]),bpm=t.get('bpm')) for t in candidates]
    save(folder/'music-ranking-v31.json',dict(method='provider_mood_tags_and_tempo_not_title',candidates=ranked,
        selection_profile=profile,prior_recordings_excluded=list(exclude),listening_claim=False,ai_requests=0))
    chosen=[]
    for row in candidates:
        if score(row)<5:continue
        selected=provider.selected(dict(music_recording_id=row['recording_id'],music_title=row['title'],
            music_selection_reason='Verified documentary tension and rhythmic/epic drive tags; score '+str(score(row))),
            dict(tracks=list(tracks.values())),channel)
        guard();audio=bounded_read(lambda:provider.audio(selected,channel,folder),guard)
        path=AUTOMATION/'runtime/music'/audio['filename']
        if audio.get('covered_channel')!=channel or sha(path)!=audio['sha256']:
            raise Failure('documentary_catarsis_music_binding_changed')
        chosen.append(dict(audio,file=str(path)))
        if len(chosen)==2:break
    if not chosen:raise Failure('documentary_catarsis_matching_suspense_music_unavailable')
    result=dict(version=STYLE,provider='epidemic',covered_channel=channel,policy=policy,tracks=chosen,
        selection_profile=profile,arc=['investigation','rising_tension','reflective_close'],ai_requests=0)
    save(folder/'music-selection.json',result);save(folder/'soundtrack-v31.json',result)
    return result

def verified_music(folder,channel):
    """Bind selected recordings to actual account scope, provider records and downloaded bytes."""
    folder=Path(folder)
    value=read(folder/'soundtrack-v31.json')
    evidence=read(folder/'music-license-evidence.json')
    if value!=read(folder/'music-selection.json') or value.get('covered_channel')!=channel:
        raise Failure('documentary_music_receipt_binding_changed')
    tracks=value.get('tracks',[])
    if not isinstance(tracks,list) or not 1<=len(tracks)<=2:
        raise Failure('documentary_music_receipt_tracks_invalid')
    if channel==CHANNELS[0]:
        policy={'generator':'local_minor_drone_and_pulse_v31','external_recordings':False}
        if (value.get('provider')!='original' or value.get('policy')!=policy or evidence.get('policy')!=policy
            or len(tracks)!=1 or tracks[0].get('recording_id')!='original-suspense-v31'
            or sha(tracks[0]['file'])!=tracks[0].get('sha256') or evidence.get('file_sha256')!=tracks[0]['sha256']):
            raise Failure('documentary_music_receipt_rights_invalid')
        return value
    from documentary_av_assets import native
    policy=native().rights(channel)
    if (channel!=CHANNELS[1] or value.get('provider')!='epidemic' or value.get('policy')!=policy
        or evidence.get('policy')!=policy or value.get('selection_profile')!=MUSIC_PROFILE):
        raise Failure('documentary_music_receipt_rights_invalid')
    catalog=read(folder/'epidemic-catalogue.json')
    if catalog.get('provider')!='epidemic' or catalog.get('channel')!=channel:
        raise Failure('documentary_music_receipt_catalog_invalid')
    offered={r['recording_id']:r for r in catalog['tracks']}
    if len({t.get('recording_id') for t in tracks})!=len(tracks):
        raise Failure('documentary_music_receipt_tracks_invalid')
    for track in tracks:
        row=offered.get(track.get('recording_id'),{})
        credits=track.get('credits',[])
        if (track.get('provider')!='epidemic' or track.get('covered_channel')!=channel
            or row.get('title')!=track.get('title') or row.get('instrumental_search_filter') is not True
            or music_score(row,MUSIC_PROFILE)<5 or not credits
            or not any(isinstance(c,dict) and isinstance(c.get('artist'),str) and c['artist'] for c in credits)
            or not Path(track['file']).is_file() or Path(track['file']).stat().st_size==0
            or sha(track['file'])!=track.get('sha256')):
            raise Failure('documentary_music_receipt_rights_invalid')
    return value

def prepared_music(folder,channel,topic,guard):
    """Select once before text review; reuse only complete, still-valid receipts."""
    guard()
    if not (folder/'soundtrack-v31.json').exists():
        music(folder,channel,topic,guard)
    guard()
    return verified_music(folder,channel)

def original_music(folder,channel,guard):
    import array,math,sys,wave
    if channel not in CHANNELS:raise Failure('documentary_catarsis_unknown_music_channel')
    path=folder/'original-suspense-v31.wav';rate=48000;seconds=64
    with wave.open(str(path),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(rate)
        for second in range(seconds):
            guard();values=array.array('h')
            for sample in range(rate):
                t=second+sample/rate
                # Slow minor-key drone/pulse; entirely local original PCM.
                fade=min(1,t/2,(seconds-t)/3)
                bass=.06*math.sin(2*math.pi*55*t)
                pad=.025*math.sin(2*math.pi*130.8128*t)+.017*math.sin(2*math.pi*164.8138*t)
                phase=(t*62/60)%1;pulse=.028*math.exp(-phase*12)*math.sin(2*math.pi*110*t)
                left=round(32767*fade*(bass+pad+pulse));right=round(32767*fade*(bass+.94*pad+pulse))
                values.extend((left,right))
            if sys.byteorder!='little':values.byteswap()
            out.writeframesraw(values.tobytes())
    path.chmod(0o600)
    track=dict(provider='original',recording_id='original-suspense-v31',title='Quiet Stakes',
        credits=[dict(artist='Original score')],covered_channel=channel,file=str(path),sha256=sha(path),
        tags=[dict(name='Suspense'),dict(name='Dark')],bpm=62)
    value=dict(version=STYLE,provider='original',covered_channel=channel,tracks=[track],
        policy={'generator':'local_minor_drone_and_pulse_v31','external_recordings':False},ai_requests=0)
    save(folder/'soundtrack-v31.json',value);save(folder/'music-selection.json',value)
    save(folder/'music-license-evidence.json',dict(provider='original',policy=value['policy'],file_sha256=track['sha256']))
    save(folder/'epidemic-catalogue.json',dict(provider='not_used',tracks=[]))
    save(folder/'music-ranking-v31.json',dict(provider='original',reason='Epidemic account scope does not cover this channel',ai_requests=0))
    return value

