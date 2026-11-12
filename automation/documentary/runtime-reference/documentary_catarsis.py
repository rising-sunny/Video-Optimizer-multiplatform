"""One horizontal style pass after factual review, before one visual review."""
import re
import shutil
from pathlib import Path
from documentary_common import *
from documentary_catarsis_assets import STYLE,permitted,music_score

PROOF='catarsis-proof-v31.json'

def caption(plan,chapters,credits,tracks,original_metadata):
    from documentary_captions import synopsis
    lines=['CHAPTERS']
    for chapter in chapters:
        at=int(chapter['start']);lines.append(f"{at//60}:{at%60:02} {chapter['title']}")
    lines+=['','Sources:']+list(dict.fromkeys(r['url'] for r in plan['research']))
    lines+=['','Visual credits:'];licenses={}
    for index,row in enumerate(credits,1):
        lines.append(f"[{index}] {row['author']} — {row['license']} — {row['source_url']}")
        if row['license'].startswith('CC BY'):licenses[(row['license'],row['license_url'])]=True
    lines+=['Visual adaptations: excerpts, animated framing, resizing, context labels and transitions; original footage audio omitted.']
    for name,url in licenses:lines.append(name+' '+url)
    if any(r['license'].startswith('CC BY-SA') for r in credits):
        lines.append('Adapted film: CC BY-SA 4.0 https://creativecommons.org/licenses/by-sa/4.0/')
    lines+=['','Music:']
    for row in tracks:
        artists=', '.join(dict.fromkeys(c['artist'] for c in row['credits'] if c.get('artist')))
        lines.append(f'“{row["title"]}” — {artists}'+(' (Epidemic Sound).' if row['provider']=='epidemic' else '.'))
    if any(r['provider']=='epidemic' for r in tracks):
        lines.append('Music licensed through the account subscription for Stunning Revelations.')
    disclosure=next((s for s in original_metadata['description'].splitlines() if s.startswith('Synthetic narration:')),None)
    if disclosure:lines+=['',disclosure]
    suffix='\n\n'+'\n'.join(lines);budget=min(500,5000-len(suffix.encode()))
    if budget<80:raise Failure('documentary_catarsis_full_credits_too_long')
    text=synopsis(plan['description'],budget,plan['title'])+suffix
    if len(text.encode())>5000:raise Failure('documentary_catarsis_full_credits_too_long')
    return text

def prepare(folder,task,facts,guard,progress,cached=(),exclude_music=(),soundtrack=None):
    """Facts were actually approved before entry. No text requests inside this
    operation; newly added media/music rights are verified from provider receipts."""
    from documentary_catarsis_assets import music,acquire
    from documentary_catarsis_render import usable_shots,render
    from documentary_layout import part_paths
    from documentary_render import probe
    if (folder/PROOF).exists():raise Failure('documentary_catarsis_already_rendered')
    checks=('factual_support','rights','narrative_coherence')
    if facts.get('approved') is not True or any(facts.get('checks',{}).get(k) is not True for k in checks):
        raise Failure('documentary_catarsis_requires_actual_factual_review')
    guard();before=folder/'catarsis-before-v31';before.mkdir(mode=0o700)
    for name in ('video.mp4','qa.json','metadata.json','asset-credits.json'):
        shutil.copy2(folder/name,before/name)
    save(before/'factual-review.json',facts)
    original=read(before/'asset-credits.json');plan=read(folder/'editorial-plan.json')
    qa=read(before/'qa.json');metadata=read(before/'metadata.json')
    if qa.get('passed') is not True or qa['video_sha256']!=sha(before/'video.mp4'):
        raise Failure('documentary_catarsis_original_render_changed')
    # Contract data comes from the exact narration-aligned parts, not equal
    # time slices or the model's guessed timings.
    lengths=[]
    source_folder=Path(task.get('narration_parts_folder',str(folder)))
    for path in part_paths(source_folder,len(plan['segments'])):
        value=next(s for s in probe(path)['streams'] if s['codec_type']=='video')
        if value['avg_frame_rate']!='30/1':raise Failure('documentary_catarsis_original_fps')
        lengths.append(int(value['nb_frames'])/30)
    progress('finding_documentary_suspense_music')
    if soundtrack is None:
        soundtrack=music(folder,task['channel'],task['topic'],guard,exclude_music)
    else:
        from documentary_catarsis_assets import verified_music
        if soundtrack!=verified_music(folder,task['channel']):
            raise Failure('documentary_prepared_music_changed')
    progress('discovering_catarsis_media')
    pool=acquire(folder,plan,original,guard,progress,cached)
    # YouTube descriptions have a real limit. Keep complete attribution and
    # remove the least-prioritized optional additions locally if needed; never
    # truncate an author's name/license or invoke the model to shorten credits.
    while True:
        shots=usable_shots(folder,plan,lengths,pool)
        used={s['asset'] for s in shots}
        credits=[r for i,r in enumerate(pool) if i in used]
        try:text=caption(plan,read(folder/'chapters.json'),credits,soundtrack['tracks'],metadata);break
        except Failure as exc:
            optional=[i for i,r in enumerate(pool) if r.get('origin')=='new_context']
            if str(exc)!='documentary_catarsis_full_credits_too_long' or not optional:raise
            pool.pop(optional[-1])
    save(folder/'catarsis-pool-v31.json',pool)
    return finish_style(folder,task,guard,progress,pool,soundtrack,lengths)

def finish_style(folder,task,guard,progress,pool,soundtrack,lengths,resume=None):
    from documentary_catarsis_render import usable_shots,render
    before=folder/'catarsis-before-v31'
    plan=read(folder/'editorial-plan.json');metadata=read(before/'metadata.json')
    original=read(before/'asset-credits.json')
    shots=usable_shots(folder,plan,lengths,pool,resume)
    credits=[r for i,r in enumerate(pool) if i in {s['asset'] for s in shots}]
    text=caption(plan,read(folder/'chapters.json'),credits,soundtrack['tracks'],metadata)
    # All original factual source files and raw assets remain pinned. The
    # before directory carries the replaced render/QA/caption for audit.
    keep={'editorial-plan.json','subtitles.srt','chapters.json','sources.json',
          'documentary-text-review.json','autocorrection-resolution-v24.json','autocorrection-sources-v24.json'}
    keep.update(p.name for p in folder.glob('license-*.json'))
    keep.update(p.name for p in folder.glob('source-*.html'))
    keep.update(p.name for p in folder.glob('editorial-plan-autoverify-*.json'))
    source_pins={str(folder/n):sha(folder/n) for n in keep if (folder/n).is_file()}
    source_pins.update({str(p):sha(p) for p in before.iterdir() if p.is_file()})
    for row in original:source_pins[row['file']]=row['sha256']
    save(folder/'asset-credits.json',credits)
    save(folder/'metadata.json',dict(metadata,description=text))
    shots,sheets=render(folder,before/'video.mp4',plan,lengths,pool,soundtrack,guard,progress,resume=resume)
    guard()
    inputs={n:sha(folder/n) for n in ('editorial-plan.json','metadata.json','asset-credits.json','subtitles.srt',
        'chapters.json','catarsis-timeline-v31.json','catarsis-pool-v31.json','soundtrack-v31.json',
        'music-selection.json','music-license-evidence.json','epidemic-catalogue.json',
        'music-ranking-v31.json','qa.json','video.mp4','media-decode-resolution-v32.json')}
    inputs.update({p.name:sha(p) for p in sheets})
    save(folder/PROOF,dict(version=STYLE,job_id=folder.name,source_pins=source_pins,inputs=inputs,
        original_metadata_file=str(before/'metadata.json'),factual_review_file=str(before/'factual-review.json'),
        music_recordings=[dict(recording_id=r['recording_id'],title=r['title']) for r in soundtrack['tracks']],
        text_ai_requests=0,narration_regenerated=False,thumbnail_mode='manual',
        speech_timing='same_integer_frames_and_subtitles',completed_at=now(),publication_allowed=False))
    effective_text(folder)
    return sheets

def effective_text(folder):
    proof=read(folder/PROOF)
    if proof.get('music_revision'):
        from documentary_music_revision import validate_resolution
        return validate_resolution(folder)
    if proof.get('context_correction'):
        from documentary_context_fix import validate_resolution,REPAIR
        if proof['context_correction']!=REPAIR:raise Failure('documentary_context_resolution_scope')
        validate_resolution(folder)
    if proof.get('version')!=STYLE or proof.get('job_id')!=folder.name or proof.get('thumbnail_mode')!='manual':
        raise Failure('documentary_catarsis_proof_scope')
    for path,digest in proof['source_pins'].items():
        if sha(path)!=digest:raise Failure('documentary_catarsis_factual_inputs_changed')
    for name,digest in proof['inputs'].items():
        if Path(name).name!=name or sha(folder/name)!=digest:raise Failure('documentary_catarsis_render_inputs_changed')
    facts=read(proof['factual_review_file'])
    if facts.get('resolution',{}).get('version')=='chrome-dome-music-evidence-20261106':
        from chrome_dome_music_recovery_20261106 import validate_resolution
        validate_resolution(folder,facts)
    if facts.get('approved') is not True or any(facts.get('checks',{}).get(k) is not True for k in ('factual_support','rights','narrative_coherence')):
        raise Failure('documentary_catarsis_factual_approval_changed')
    pool=read(folder/'catarsis-pool-v31.json')
    for row in pool:
        if not permitted(row['license']) or sha(row['file'])!=row['sha256']:
            raise Failure('documentary_catarsis_asset_rights_changed')
        if row.get('origin')=='new_context':
            receipt=folder/row['evidence'];value=read(receipt);record=value['record']
            if (sha(receipt)!=row['evidence_sha256'] or value['file_sha256']!=row['sha256'] or
                any(record[k]!=row[k] for k in ('source_url','author','license','license_url','type'))):
                raise Failure('documentary_catarsis_asset_rights_changed')
        elif row.get('origin')=='previous_context_clip':
            # This is the actual old licensed clip, never a newly asserted
            # government/public-domain license for arbitrary footage.
            receipt=read(row['original_evidence_file'])
            if (sha(row['original_evidence_file'])!=row['evidence_sha256'] or receipt['file_sha256']!=row['sha256'] or
                any(receipt['record'][k]!=row[k] for k in ('source_url','author','license','type'))):
                raise Failure('documentary_catarsis_asset_rights_changed')
    from documentary_av_assets import native
    soundtrack=read(folder/'soundtrack-v31.json')
    if soundtrack['covered_channel']!=read(folder/'metadata.json')['channel']:
        raise Failure('documentary_catarsis_music_rights_changed')
    evidence=read(folder/'music-license-evidence.json')
    if soundtrack['provider']=='epidemic':
        policy=native().rights(read(folder/'metadata.json')['channel'])
        if policy!=soundtrack['policy'] or evidence['policy']!=policy:
            raise Failure('documentary_catarsis_music_rights_changed')
    elif (soundtrack['provider']!='original' or soundtrack['covered_channel']!=CHANNELS[0] or
        soundtrack['policy']!={'generator':'local_minor_drone_and_pulse_v31','external_recordings':False} or evidence['policy']!=soundtrack['policy']):
        raise Failure('documentary_catarsis_music_rights_changed')
    offered={r['recording_id']:r for r in read(folder/'epidemic-catalogue.json')['tracks']}
    for track in soundtrack['tracks']:
        if soundtrack['provider']=='original':
            if (track.get('provider')!='original' or track['recording_id']!='original-suspense-v31' or
                sha(track['file'])!=track['sha256'] or evidence.get('file_sha256')!=track['sha256']):
                raise Failure('documentary_catarsis_music_rights_changed')
            continue
        candidate=offered.get(track['recording_id'],{})
        if (track.get('provider')!='epidemic' or track.get('covered_channel')!=soundtrack['covered_channel'] or
            candidate.get('title')!=track['title'] or candidate.get('instrumental_search_filter') is not True or
            music_score(candidate,soundtrack.get('selection_profile'))<5 or sha(track['file'])!=track['sha256']):
            raise Failure('documentary_catarsis_music_rights_changed')
    plan=read(folder/'editorial-plan.json');metadata=read(proof['original_metadata_file'])
    expected=dict(metadata,description=caption(plan,read(folder/'chapters.json'),read(folder/'asset-credits.json'),soundtrack['tracks'],metadata))
    if read(folder/'metadata.json')!=expected:raise Failure('documentary_catarsis_caption_changed')
    result=dict(approved=True,checks=dict(factual_support=True,rights=True,narrative_coherence=True),findings=[],
        resolution=dict(version=STYLE,factual_review_sha256=sha(proof['factual_review_file']),
            facts_reused_from_unchanged_narration=True,new_media_and_music='actual_provider_receipts',text_ai_requests=0))
    if facts.get('resolution',{}).get('version')=='chrome-dome-music-evidence-20261106':
        result['resolution']['music_evidence_resolution']=facts['resolution']
    return result
