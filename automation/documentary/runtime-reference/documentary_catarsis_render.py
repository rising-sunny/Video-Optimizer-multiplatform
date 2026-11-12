"""Shot-based horizontal Catarsis. Speech is continuous and never regenerated.

Picture edits have their own 3-7 second rhythm, independently of the narrated
paragraphs. Integer-frame contracts keep subtitles and chapter times intact.
"""
import math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from documentary_common import *
from documentary_render import run,probe,duration,image,BOLD
from documentary_catarsis_assets import STYLE,relevance

def archival_badge(row):
    if not row.get('archival_low_resolution'):return None
    prefix='SIMULATED SCENARIO' if 'simulat' in row['label'].lower() else 'CONTEXT FOOTAGE'
    return f"{prefix} - LOW-RES SOURCE {row['source_width']} x {row['source_height']}"

def usable_shots(folder,plan,lengths,pool,resume=None,record=True):
    """Replace only unreadable sources, with existing relevant licensed media.
    The original pool/receipts remain intact. No downloads or AI retries."""
    from documentary_catarsis_assets import verify_image
    shots=timeline(plan,lengths,pool) if resume is None else [dict(s) for s in resume['shots']]
    completed=0 if resume is None else resume['completed']
    invalid={}
    for index,row in enumerate(pool):
        if sha(row['file'])!=row['sha256']:raise Failure('documentary_catarsis_source_media_changed')
        if row['type']!='image':continue
        try:verify_image(row['file'])
        except Failure as exc:
            if str(exc) not in ('documentary_catarsis_image_decode_failed','documentary_catarsis_image_size'):raise
            invalid[index]=str(exc)
    replacements=[]
    for i,shot in enumerate(shots):
        if shot['asset'] not in invalid:continue
        if i<completed:raise Failure('documentary_catarsis_completed_source_unreadable')
        theme=plan['assets'][plan['segments'][shot['segment']]['asset']]['label']
        ranked=[]
        for index,row in enumerate(pool):
            if index in invalid:continue
            match=relevance(theme,row)
            if match<2:continue
            if row['type']=='video' and row.get('duration_seconds',0)<shot['duration_seconds']+.15:continue
            recent={s['identity'] for s in shots[max(0,i-2):i]}
            ranked.append((match-20*(row['sha256'] in recent),-index,index))
        if not ranked:raise Failure('documentary_catarsis_no_readable_relevant_asset')
        index=max(ranked)[-1];row=pool[index];old=shot['asset']
        shot.update(asset=index,type=row['type'],label=row['label'],identity=row['sha256'],source_start=0,
            motion=('push_in' if i%2==0 else 'pull_out') if row['type']=='image' else 'source_motion')
        if archival_badge(row):shot['label_badge']=archival_badge(row)
        replacements.append(dict(shot=i,rejected_asset=old,replacement_asset=index,reason=invalid[old]))
    if record:
        save(folder/'media-decode-resolution-v32.json',dict(invalid_assets=invalid,replacements=replacements,
            completed_shots_preserved=completed,ai_requests=0,downloads=0,at=now()))
    return shots

def narration_base(folder,plan,media,audios,target_seconds,guard,progress,fps=30):
    """Cheap speech/timing assembly before factual approval. Do not render 600s
    of still pictures only to throw them away during the final Catarsis edit."""
    import textwrap
    from documentary_render import timestamp
    work=folder/'render';work.mkdir(mode=0o700)
    lengths=[duration(p) for p in audios];speed=sum(lengths)/target_seconds
    if not .85<=speed<=1.15:raise Failure('documentary_narration_runtime_needs_adjustment')
    parts=[];subtitles=[];chapters=[];elapsed=0
    for i,(scene,audio,length) in enumerate(zip(plan['segments'],audios,lengths)):
        guard();progress('assembling_continuous_narration',i,len(audios))
        n=math.ceil(length/speed*fps);seconds=n/fps;normalized=work/f'voice-{i:03}.wav'
        run(['ffmpeg','-v','error','-i',str(audio),'-af',
            f'atempo={speed:.8f},apad,atrim=duration={seconds:.8f},loudnorm=I=-16:TP=-1.5:LRA=9',
            '-c:a','pcm_s16le','-ar','48000','-ac','2','-y',str(normalized)])
        out=work/f'part-{i:03}.mp4'
        run(['ffmpeg','-v','error','-f','lavfi','-i',f'color=c=0x10151e:s=1920x1080:r={fps}',
            '-i',str(normalized),'-frames:v',str(n),'-t',str(seconds),'-threads','2','-c:v','libx264',
            '-preset','ultrafast','-crf','28','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-y',str(out)])
        parts.append(out)
        if not chapters or chapters[-1]['title']!=scene['chapter']:chapters.append(dict(start=round(elapsed,3),title=scene['chapter']))
        phrases=textwrap.wrap(scene['narration'],84)
        for j,phrase in enumerate(phrases):
            subtitles.append(f'{len(subtitles)+1}\n{timestamp(elapsed+seconds*j/len(phrases))} --> {timestamp(elapsed+seconds*(j+1)/len(phrases))}\n{phrase}\n')
        elapsed+=seconds
    listing=work/'parts.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in parts))
    run(['ffmpeg','-v','error','-f','concat','-safe','1','-i',str(listing),'-c','copy','-movflags','+faststart','-y',str(folder/'video.mp4')])
    (folder/'subtitles.srt').write_text('\n'.join(subtitles));save(folder/'chapters.json',chapters)
    # Internal placeholder only. It is never attached to the reviewer or
    # returned as an approved thumbnail in the video-only result.
    Image.new('RGB',(1280,720),'#10151e').save(folder/'thumbnail.jpg')
    result=probe(folder/'video.mp4');v=next(s for s in result['streams'] if s['codec_type']=='video')
    if (v['width'],v['height'])!=(1920,1080) or abs(float(result['format']['duration'])-elapsed)>.2 or not any(s['codec_type']=='audio' for s in result['streams']):
        raise Failure('documentary_catarsis_base_qa_failed')
    save(folder/'qa.json',dict(passed=True,width=1920,height=1080,duration_seconds=float(result['format']['duration']),
        video_sha256=sha(folder/'video.mp4'),narration_segments=len(audios),narration_speed=speed,
        subtitle_timing='proportional_within_each_spoken_segment',chapters=chapters))
    return []

def timeline(plan,lengths,pool,fps=30):
    if len(lengths)!=len(plan['segments']) or not pool:raise Failure('documentary_catarsis_timeline_inputs')
    result=[];elapsed=0;last=[];uses={};total=round(sum(lengths)*fps)
    for segment,(scene,seconds) in enumerate(zip(plan['segments'],lengths)):
        frames=round(seconds*fps)
        if frames<=0:raise Failure('documentary_catarsis_timeline_length')
        theme=plan['assets'][scene['asset']]['label']
        phase=elapsed/max(1,total)
        base=3.3 if phase<.10 else (6.5 if phase>.91 else 4.8)
        count=max(1,round(frames/(base*fps)));small,extra=divmod(frames,count)
        for local in range(count):
            n=small+(local<extra)
            ranked=[]
            for index,row in enumerate(pool):
                match=relevance(theme,row)
                if row.get('original_asset')==scene['asset']:match=max(match,6)
                if match<2:continue
                if row['type']=='video' and row.get('duration_seconds',0)<n/fps+.15:continue
                identity=row['sha256'];used=uses.get(identity,0)
                # Every few shots prefer moving footage when it matches this
                # scene. A nuclear-test clip never substitutes for a bomb crash.
                prefer_video=(len(result)%5 in (0,2))
                score=match+3*(prefer_video and row['type']=='video')-min(used,12)
                score-=20 if identity in last[-2:] else 0
                ranked.append((score,-used,-index,index))
            if not ranked:raise Failure('documentary_catarsis_no_relevant_scene_asset')
            index=max(ranked)[-1];row=pool[index];identity=row['sha256'];used=uses.get(identity,0)
            available=max(0,row.get('duration_seconds',0)-n/fps-.1)
            source_start=round((used*(n/fps+.7))%available,5) if row['type']=='video' and available>.1 else 0
            chapter_start=local==0 and (not result or scene['chapter']!=result[-1]['chapter'])
            transition='dissolve' if len(result)%3==0 else ('amber_leak' if chapter_start else 'cut')
            result.append(dict(segment=segment,chapter=scene['chapter'],chapter_start=chapter_start,
                asset=index,type=row['type'],label=row['label'],start_frame=elapsed,frames=n,
                start_seconds=elapsed/fps,duration_seconds=n/fps,source_start=source_start,
                motion=('push_in' if len(result)%2==0 else 'pull_out') if row['type']=='image' else 'source_motion',
                transition=transition,identity=identity))
            if row.get('archival_low_resolution'):
                result[-1]['label_badge']=archival_badge(row)
            elapsed+=n;last.append(identity);uses[identity]=used+1
    if elapsed!=sum(round(s*fps) for s in lengths):raise Failure('documentary_catarsis_frame_sum_changed')
    return result

def overlay(path,shot,size):
    from documentary_context_fix import caption_overlay
    return caption_overlay(path,shot,size)


def dissolve(previous,fps=30,input_index=2,base='picture'):
    # A single PNG frame cannot animate its alpha. Loop it at the actual
    # timeline rate so the fade supplies six progressively transparent frames.
    return ['-loop','1','-framerate',str(fps),'-i',str(previous)],[
        f'[{input_index}:v]format=rgba,fade=t=out:st=0:d=0.20:alpha=1[previous]',
        f"[{base}][previous]overlay=0:0:enable='lt(t,0.20)':eof_action=pass[transition]"]

def video_picture(row,size,fps=30):
    w,h=size
    if not row.get('archival_low_resolution'):
        return (f'[0:v]setpts=PTS-STARTPTS,scale={w}:{h}:force_original_aspect_ratio=decrease,'
            f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[picture]')
    # Preserve every source edge above the opaque footer. The dim background
    # comes from the same clip; it adds no invented historical detail.
    box_w=2*round(w*.8/2);box_h=2*round(h*.76/2);top=round(h*.10)
    return (f'[0:v]setpts=PTS-STARTPTS,split=2[archive_bg][archive_fg];'
        f'[archive_bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},'
        f'gblur=sigma=18,eq=brightness=-0.20:saturation=0.65,setsar=1,fps={fps}[archive_back];'
        f'[archive_fg]scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:flags=lanczos,'
        f'setsar=1,fps={fps}[archive_front];'
        f'[archive_back][archive_front]overlay=(W-w)/2:{top}:shortest=1,format=yuv420p[picture]')

def soundtrack_bed(soundtrack,output,seconds,work,guard):
    from documentary_av_render import music_bed
    from documentary_catarsis_assets import MUSIC_PROFILE
    tracks=soundtrack['tracks'];cross=min(3.,seconds/12)
    cuts=[0,seconds*.35,seconds*.83,seconds]
    files=[]
    for i in range(3):
        guard();length=cuts[i+1]-cuts[i]+(cross if i<2 else 0)
        path=work/f'cue-{i}.wav';music_bed(Path(tracks[0 if i!=1 else min(1,len(tracks)-1)]['file']),path,length)
        if soundtrack.get('selection_profile')==MUSIC_PROFILE:
            stronger=work/f'cue-epic-{i}.wav'
            target=(-24,-22,-25)[i]
            run(['ffmpeg','-v','error','-threads','2','-i',str(path),'-af',
                f'loudnorm=I={target}:TP=-5:LRA=10','-ar','48000','-ac','2','-c:a','pcm_s16le','-y',str(stronger)])
            path=stronger
        files.append(path)
    ins=[]
    for path in files:ins+=['-i',str(path)]
    levels=(1,1,1) if soundtrack.get('selection_profile')==MUSIC_PROFILE else (1.10,1.50,.75)
    graph=(f'[0:a]volume={levels[0]}[a];[1:a]volume={levels[1]}[b];[2:a]volume={levels[2]}[c];'
        f'[a][b]acrossfade=d={cross}:c1=tri:c2=tri[ab];'
        f'[ab][c]acrossfade=d={cross}:c1=tri:c2=tri,'
        f'atrim=duration={seconds:.8f},asetpts=PTS-STARTPTS[out]')
    run(['ffmpeg','-v','error','-threads','2',*ins,'-filter_complex_threads','1','-filter_complex',graph,
        '-map','[out]','-ar','48000','-ac','2','-c:a','pcm_s16le','-y',str(output)])
    if abs(duration(output)-seconds)>.05:raise Failure('documentary_catarsis_music_arc_length')
    return dict(phases=['investigation','rising_tension','reflective_close'],crossfade_seconds=cross,selection_profile=soundtrack.get('selection_profile'),
        cue_recordings=[tracks[0 if i!=1 else min(1,len(tracks)-1)]['recording_id'] for i in range(3)])

def render(folder,voice_video,plan,lengths,pool,soundtrack,guard,progress,size=(1920,1080),fps=30,resume=None):
    from documentary_av_render import effects,measure
    from documentary_labels import boards
    work=folder/'catarsis-render-v31';work.mkdir(mode=0o700,exist_ok=resume is not None)
    shots=usable_shots(folder,plan,lengths,pool,resume);save(folder/'catarsis-timeline-v31.json',shots)
    source=probe(voice_video);sv=next(s for s in source['streams'] if s['codec_type']=='video')
    wanted=sum(s['frames'] for s in shots);seconds=wanted/fps
    if abs(float(source['format']['duration'])-seconds)>.2:raise Failure('documentary_catarsis_speech_timing_changed')
    if int(sv['nb_frames'])!=wanted:raise Failure('documentary_catarsis_source_frames_changed')
    stills={};parts=[];geometry=[];w,h=size;previous=None
    for i,shot in enumerate(shots):
        guard()
        if resume is not None and i<resume['completed']:
            progress('checking_saved_shots',i+1,resume['completed'])
        else:progress('rendering_catarsis_shots',i,len(shots))
        row=pool[shot['asset']];n=shot['frames'];d=n/fps
        if resume is not None and i<resume['completed']:
            out=work/f'shot-{i:03}.mp4'
            if sha(out)!=resume['prefix_sha256'].get(out.name):raise Failure('documentary_catarsis_completed_shot_changed')
            v=next(s for s in probe(out)['streams'] if s['codec_type']=='video')
            if int(v['nb_frames'])!=n or (v['width'],v['height'])!=size:
                raise Failure('documentary_catarsis_completed_shot_invalid')
            geometry.append(overlay(work/f'context-{i:03}.png',shot,size))
            parts.append(out)
            if i==resume['completed']-1:
                previous=work/'previous.jpg'
                run(['ffmpeg','-v','error','-threads','2','-ss',f'{(n-1)/fps:.8f}','-i',str(out),'-frames:v','1','-y',str(previous)])
                if not previous.is_file():raise Failure('documentary_catarsis_previous_frame_missing')
            continue
        if sha(row['file'])!=row['sha256']:raise Failure('documentary_catarsis_source_media_changed')
        if row['type']=='image':
            key=row['sha256']
            if key not in stills:
                still=work/f'still-{len(stills):02}.png';image(row['file'],still,size);stills[key]=still
            ins=['-i',str(stills[key])]
            zoom=f'1.015+0.055*on/{max(1,n-1)}' if shot['motion']=='push_in' else f'1.070-0.055*on/{max(1,n-1)}'
            picture=(f"[0:v]zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
                f'd={n}:s={w}x{h}:fps={fps},setsar=1,format=yuv420p[picture]')
        else:
            ins=['-ss',str(shot['source_start']),'-i',row['file']]
            picture=video_picture(row,size,fps)
        context=work/f'context-{i:03}.png';geometry.append(overlay(context,shot,size))
        ins+=['-i',str(context)];graph=[picture];last='picture'
        if previous is not None and shot['transition']=='dissolve':
            incoming,filters=dissolve(previous,fps)
            ins+=incoming;graph+=filters
            last='transition'
        if shot['transition']=='amber_leak':
            # A subdued amber wash signals a chapter, without inventing fire,
            # nuclear detonations or aggressive flashing imagery.
            graph.append(f"[{last}]drawbox=x=0:y=0:w=iw:h=ih:color=0xff9d52@0.14:t=fill:enable='lt(t,0.18)'[leak]")
            last='leak'
        graph.append(f'[{last}][1:v]overlay=0:0:format=auto:eof_action=repeat,settb=expr=1/{fps},setpts=N,setsar=1,format=yuv420p[out]')
        out=work/f'shot-{i:03}.mp4'
        run(['ffmpeg','-v','error','-threads','2',*ins,'-filter_complex_threads','1','-filter_complex',';'.join(graph),
            '-map','[out]','-an','-frames:v',str(n),'-threads','2','-c:v','libx264','-preset','veryfast','-crf','20',
            '-pix_fmt','yuv420p','-fps_mode','passthrough','-y',str(out)])
        v=next(s for s in probe(out)['streams'] if s['codec_type']=='video')
        if int(v['nb_frames'])!=n:raise Failure('documentary_catarsis_shot_frame_count')
        previous=work/'previous.jpg'
        run(['ffmpeg','-v','error','-threads','2','-ss',f'{(n-1)/fps:.8f}','-i',str(out),'-frames:v','1','-y',str(previous)])
        parts.append(out)
    guard();progress('rendering_catarsis_shots',len(shots),len(shots))
    listing=work/'parts.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in parts))
    silent=work/'picture.mp4'
    run(['ffmpeg','-v','error','-f','concat','-safe','1','-i',str(listing),'-an','-c:v','copy','-y',str(silent)])
    progress('mixing_catarsis_suspense_music')
    bed=work/'music-bed.wav';arc=soundtrack_bed(soundtrack,bed,seconds,work,guard)
    transitions=[s['start_seconds'] for i,s in enumerate(shots) if i and (s['chapter_start'] or i%3==0)]
    sfx=work/'transitions.pcm';sfx_proof=effects(sfx,seconds,transitions)
    from documentary_music_revision import mix_graph
    graph=mix_graph(soundtrack.get('selection_profile'))
    run(['ffmpeg','-v','error','-threads','2','-i',str(silent),'-i',str(voice_video),'-i',str(bed),
        '-f','s16le','-ar','48000','-ac','1','-i',str(sfx),'-filter_complex_threads','1','-filter_complex',graph,
        '-map','0:v:0','-map','[mix]','-t',f'{seconds:.8f}','-c:v','copy','-c:a','aac','-b:a','192k',
        '-ar','48000','-ac','2','-movflags','+faststart','-y',str(folder/'video.mp4')])
    info=probe(folder/'video.mp4');v=next(s for s in info['streams'] if s['codec_type']=='video')
    metrics=measure(folder/'video.mp4');bed_metrics=measure(bed)
    if (int(v['nb_frames'])!=wanted or (v['width'],v['height'])!=size or
        abs(float(info['format']['duration'])-float(source['format']['duration']))>.2 or
        not -24<metrics['integrated_lufs']<-10 or metrics['true_peak_db']>-.4 or
        not -35<bed_metrics['integrated_lufs']<-19):raise Failure('documentary_catarsis_technical_qa_failed')
    samples=[s['start_seconds']+s['duration_seconds']/2 for i,s in enumerate(shots)
        if s['chapter_start'] or i%max(1,math.ceil(len(shots)/18))==0]
    sheets=boards(folder,folder/'video.mp4',[],guard,work,sample_times=samples[:40])
    sheets=[p for p in sheets if p.name!='thumbnail.jpg']
    qa=dict(passed=True,width=w,height=h,duration_seconds=float(info['format']['duration']),
        video_sha256=sha(folder/'video.mp4'),chapters=read(folder/'chapters.json'),style=STYLE,
        frame_count=wanted,narration_regenerated=False,narration_source_sha256=sha(voice_video),
        shot_count=len(shots),clip_shots=sum(s['type']=='video' for s in shots),
        unique_visual_assets=len({s['identity'] for s in shots}),
        mean_shot_seconds=seconds/len(shots),longest_shot_seconds=max(s['duration_seconds'] for s in shots),
        audio=metrics,music_bed_audio=bed_metrics,music_arc=arc,procedural_sfx=sfx_proof,
        transition_events=len(transitions),thumbnail_mode='manual',context_geometry=geometry)
    qa['archival_low_resolution_sources']=[dict(source_sha256=r['sha256'],width=r['source_width'],
        height=r['source_height'],framing='uncropped_foreground_over_same_clip_blurred_background',
        generated_detail=False,source_resolution_disclosed=True) for r in pool
        if r.get('archival_low_resolution') and r['sha256'] in {s['identity'] for s in shots}]
    save(folder/'qa.json',qa);return shots,sheets
