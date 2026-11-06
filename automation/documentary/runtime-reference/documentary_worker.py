"""Manual documentary pipeline; source-pinned, checkpointed, no upload imports."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from documentary_common import *

def dependencies():
    import PIL
    for binary in ('ffmpeg','ffprobe','/usr/bin/bwrap','/usr/bin/codex'):
        import shutil
        if not shutil.which(binary):raise Failure('documentary_render_dependency_missing')
    config=read(TTS/'voice.json')
    for key in ('model','config'):
        path=Path(config[key])
        if not path.is_relative_to(TTS) or sha(path)!=config[key+'_sha256']:
            raise Failure('documentary_voice_changed')
    if not (TTS/'venv/bin/python').is_file():raise Failure('documentary_voice_runtime_missing')
    return config

def history(folder):
    sys.path.insert(0,str(AUTOMATION))
    import daily_remote
    from history_worker import collect
    value=collect(daily_remote)
    if not value.get('complete') or any(x.get('status')!='available' for x in value['sources'].values()):
        raise Failure('documentary_history_incomplete')
    save(folder/'history-full.json',value)
    entries=[];seen=set()
    for channel,platforms in value['channels'].items():
        for platform,items in platforms.items():
            for i in items:
                title=i.get('title') or i.get('text','').split('\n')[0]
                intro=i.get('text','').split('\n\n')[0][:350]
                key=(channel,title,intro)
                if key in seen:continue
                seen.add(key);entries.append(dict(channel=channel,title=title,summary=intro))
    save(folder/'history-editorial.json',entries)

def calibrate(folder,config):
    from documentary_render import duration
    text=('A documentary begins with a question. We follow the evidence through photographs, '
          'written records and the memories people leave behind. Some details are well documented. '
          'Others remain uncertain. Careful narration gives the listener time to understand that difference. '
          'The story moves forward, but it never needs to outrun the evidence.')
    out=folder/'voice-calibration.wav'
    p=subprocess.run([str(TTS/'venv/bin/python'),'-m','piper','--model',config['model'],'--output_file',str(out)],
        input=text,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=180)
    if p.returncode or not out.is_file():raise Failure('documentary_narration_failed')
    seconds=duration(out)
    if not 5<seconds<90:raise Failure('documentary_voice_calibration_failed')
    wpm=len(text.split())*60/seconds;scale=wpm/140
    if not .7<=scale<=2:raise Failure('documentary_voice_calibration_failed')
    value=dict(config,length_scale=scale,effective_target_wpm=140)
    save(folder/'voice-calibration.json',dict(measured_wpm=wpm,length_scale=scale,target_wpm=140))
    return value

def narrate(folder,plan,config,guard,progress):
    voice=folder/'narration';voice.mkdir(exist_ok=True)
    result=[]
    for i,s in enumerate(plan['segments']):
        guard();progress('narrating',i,len(plan['segments']))
        path=voice/f'segment-{i:03}.wav'
        p=subprocess.run([str(TTS/'venv/bin/python'),'-m','piper','--model',config['model'],
                          '--length_scale',str(config['length_scale']),'--output_file',str(path)],input=s['narration'],text=True,
                         stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=180)
        if p.returncode or not path.is_file():raise Failure('documentary_narration_failed')
        result.append(path)
    return result

def description(plan,credits,voice,chapters):
    from documentary_captions import description as fit
    return fit(plan,credits,voice,chapters)

def perform(job):
    if not valid_id(job):raise Failure('invalid_documentary_job_id')
    folder=JOBS/job;state=STATE/job;task=read(state/'request.json')
    if task.get('job_id')!=job or task.get('publication_allowed') is not False:raise Failure('documentary_task_invalid')
    with (state/'claimed').open('x') as f:f.write(now());f.flush();os.fsync(f.fileno())
    from publication_service import controls
    controls_before=controls();source_pins={n:sha(ROOT/n) for n in MODULES};request_pin=sha(state/'request.json')
    def guard():
        if (state/'STOP').exists():raise Failure('documentary_cancelled')
        if controls()!=controls_before or sha(state/'request.json')!=request_pin or any(sha(ROOT/n)!=v for n,v in source_pins.items()):
            raise Failure('documentary_inputs_or_controls_changed')
    def progress(phase,done=None,total=None):
        guard();status=read(state/'status.json')
        status.update(state='running',phase=phase,updated_at=now(),progress=dict(completed=done,total=total))
        status['ai_usage']=usage(folder)
        if (folder/'deepseek-usage.json').is_file():status['deepseek_budget']=read(folder/'deepseek-usage.json')
        save(state/'status.json',status)
    from deepseek_runtime import key
    key()
    guard();folder.mkdir(mode=0o700,parents=True,exist_ok=False)
    config=dependencies();progress('calibrating_voice');config=calibrate(folder,config)
    save(folder/'request-editorial.json',dict({k:task[k] for k in ('channel','topic','minutes')},
         target_word_count=round(task['minutes']*config['effective_target_wpm'])))
    progress('checking_history');history(folder)
    progress('researching')
    from documentary_ai import plan as editorial_plan, review
    from documentary_media import acquire
    from documentary_render import render
    plan=validate_plan(editorial_plan(folder,task));save(folder/'editorial-plan.json',plan)
    finish(job,task,folder,state,config,plan,guard,progress,source_pins)

def finish(job,task,folder,state,config,plan,guard,progress,source_pins):
    from documentary_media import acquire
    from documentary_render import render
    from documentary_ai import review
    guard();media=acquire(folder,plan,guard,progress)
    # Check the full public credit budget before spending time on TTS or render.
    provisional=[dict(start=0,title=title) for title in dict.fromkeys(s['chapter'] for s in plan['segments'])]
    description(plan,media,config,provisional)
    from documentary_duration import prepare_narration
    audios,target=prepare_narration(folder,plan,task,config,guard,progress,narrate)
    if task.get('horizontal_style')=='documentary-catarsis-v31':
        from documentary_catarsis_render import narration_base
        sheets=narration_base(folder,plan,media,audios,target,guard,progress)
    else:sheets=render(folder,plan,media,audios,target,guard,progress)
    qa=read(folder/'qa.json')
    if not 480<=qa['duration_seconds']<=602:raise Failure('documentary_duration_outside_contract')
    metadata=dict(title=plan['title'],description=description(plan,media,config,qa['chapters']),
                  language='en',channel=task['channel'],synthetic_narration=True,is_short=False)
    save(folder/'metadata.json',metadata)
    sheets=quality(folder,task,config,guard,progress,sheets)
    approve(job,task,folder,state,source_pins)

def quality(folder,task,config,guard,progress,sheets):
    from documentary_ai import review
    def assess(images):
        if task.get('horizontal_style')=='documentary-catarsis-v31' and not (folder/'catarsis-proof-v31.json').exists():
            from deepseek_review import text_review
            from documentary_catarsis_assets import prepared_music
            from documentary_catarsis import caption
            progress('preparing_music_rights_before_text_review')
            soundtrack=prepared_music(folder,task['channel'],task['topic'],guard)
            metadata=read(folder/'metadata.json')
            metadata['description']=caption(read(folder/'editorial-plan.json'),read(folder/'chapters.json'),
                read(folder/'asset-credits.json'),soundtrack['tracks'],metadata)
            save(folder/'metadata.json',metadata)
            if (folder/'autocorrection-resolution-v24.json').is_file():
                from documentary_autocorrection import resolved_text
                facts=resolved_text(folder)
            else:facts=text_review(folder,documentary=True)
            from documentary_catarsis import prepare
            images=prepare(folder,task,facts,guard,progress,soundtrack=soundtrack)
        pinned={str(p.relative_to(folder)):sha(p) for p in folder.rglob('*') if p.is_file() and p.name not in ('deepseek-usage.json','review.json','review-events.jsonl','review-stderr.log')}
        try:return review(folder,images)
        finally:
            guard()
            if any(sha(folder/n)!=v for n,v in pinned.items()):
                raise Failure('documentary_review_inputs_changed')
    progress('reviewing')
    try:
        try:assess(sheets)
        except Exception as exc:
            if str(exc)!='deepseek_text_evidence_requires_correction':raise
            if (folder/'source-repair-binding-v41.json').is_file():raise
            from documentary_compact import run
            sheets=run(folder,task,config,guard,progress)
            progress('reviewing_corrected_video');assess(sheets)
    except Exception as exc:
        if task.get('horizontal_style')=='documentary-catarsis-v31':raise
        if str(exc)!='documentary_review_requires_correction':raise
        from documentary_layout import allowed,run
        if not allowed(folder):raise
        sheets=run(folder,task,config,guard,progress)
        progress('reviewing_visual_correction');assess(sheets)

    return sheets

def approve(job,task,folder,state,source_pins):
    metadata=read(folder/'metadata.json');qa=read(folder/'qa.json')
    if read(folder/'review.json').get('approved') is not True:
        raise Failure('documentary_review_requires_correction')
    manual=task.get('horizontal_style')=='documentary-catarsis-v31' and task.get('thumbnail_mode')=='manual'
    files={kind:file_info(folder/name) for kind,(name,_) in KINDS.items() if not manual or kind=='video'}
    if manual:files['subtitles']=file_info(folder/'subtitles.srt')
    approval=dict(quality_approved=True,job_id=job,channel=task['channel'],files=files,
        metadata_sha256=sha(folder/'metadata.json'),plan_sha256=sha(folder/'editorial-plan.json'),
        review_sha256=sha(folder/'review.json'),source_pins=source_pins,publication_allowed=False,approved_at=now())
    if manual:
        from documentary_catarsis import effective_text
        effective_text(folder)
        approval.update(quality_scope='video_only',thumbnail_mode='manual',catarsis_proof_sha256=sha(folder/'catarsis-proof-v31.json'))
    save(folder/'approval.json',approval)
    status=read(state/'status.json');status.update(state='ready',phase='ready',updated_at=now(),error_code=None,
        quality_approved=True,files=files,metadata=metadata,duration_seconds=qa['duration_seconds'],
        ai_budget=dict(text_provider='deepseek',visual_provider='codex',automatic_provider_fallback=False),approval_sha256=sha(folder/'approval.json'))
    if manual:status.update(quality_scope='video_only',thumbnail_mode='manual',subtitles=dict(filename='subtitles.srt',language='en',sha256=sha(folder/'subtitles.srt')))
    status['ai_usage']=usage(folder)
    if (folder/'deepseek-usage.json').is_file():status['deepseek_budget']=read(folder/'deepseek-usage.json')
    save(state/'status.json',status)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('job',nargs='?');parser.add_argument('--probe',action='store_true');parser.add_argument('--resume-history',action='store_true');parser.add_argument('--resume-sources',action='store_true');parser.add_argument('--resume-assets',action='store_true');parser.add_argument('--revise-score',action='store_true');parser.add_argument('--resume-length',action='store_true');parser.add_argument('--resume-metadata',action='store_true');parser.add_argument('--resume-media',action='store_true');parser.add_argument('--resume-downloads',action='store_true');parser.add_argument('--resume-autocorrection',action='store_true');parser.add_argument('--resume-compact',action='store_true');parser.add_argument('--resume-layout',action='store_true');parser.add_argument('--resume-visual-quota',action='store_true');parser.add_argument('--revise-audiovisual',action='store_true');parser.add_argument('--correct-labels',action='store_true');parser.add_argument('--revise-catarsis',action='store_true');parser.add_argument('--resume-shots',action='store_true');parser.add_argument('--correct-context',action='store_true');args=parser.parse_args()
    if sum((args.resume_length,args.resume_metadata,args.resume_media,args.resume_downloads,args.resume_autocorrection,args.resume_compact,args.resume_layout,args.resume_visual_quota,args.revise_audiovisual,args.correct_labels,args.revise_catarsis,args.resume_shots,args.correct_context,args.resume_history,args.resume_sources,args.resume_assets,args.revise_score))>1:parser.error('Choose only one continuation')
    os.umask(0o077)
    if args.probe:
        try:
            dependencies()
            import tempfile
            from deepseek_review import sandbox
            with tempfile.TemporaryDirectory(prefix='.dependency-',dir=JOBS) as temp:
                for binary in ('/usr/bin/codex',):
                    p=subprocess.run(sandbox(Path(temp))+[binary,'--version'],
                        capture_output=True,text=True,timeout=15)
                    if p.returncode:raise Failure('documentary_cli_sandbox_probe_failed')
            print(json.dumps(dict(state='passed',version=VERSION,ai_requests=0,generation='not_requested',publication='not_requested')))
            return
        except Exception:
            print(json.dumps(dict(state='blocked',error_code='documentary_dependency_probe_failed',ai_requests=0)))
            raise SystemExit(2)
    if not args.job:parser.error('job is required')
    try:
        if args.revise_score:
            from documentary_music_revision import perform as resume
            resume(args.job)
        elif args.resume_assets:
            from documentary_asset_repair import perform as resume
            resume(args.job)
        elif args.resume_sources:
            from documentary_source_repair import perform as resume
            resume(args.job)
        elif args.resume_history:
            from documentary_history_repair import perform as resume
            resume(args.job)
        elif args.correct_context:
            from documentary_context_fix import perform as resume
            resume(args.job)
        elif args.resume_shots:
            from documentary_catarsis_recovery import perform as resume
            resume(args.job)
        elif args.revise_catarsis:
            from documentary_catarsis_revision import perform as resume
            resume(args.job)
        elif args.correct_labels:
            from documentary_labels import perform as resume
            resume(args.job)
        elif args.revise_audiovisual:
            from documentary_av_revision import perform as resume
            resume(args.job)
        elif args.resume_visual_quota:
            from documentary_visual_recovery import perform as resume
            resume(args.job)
        elif args.resume_layout:
            from documentary_layout_repair import perform as resume
            resume(args.job)
        elif args.resume_compact:
            from documentary_compact_repair import perform as resume
            resume(args.job)
        elif args.resume_autocorrection:
            from documentary_autocorrection_repair import perform as resume
            resume(args.job)
        elif args.resume_downloads:
            from documentary_download_repair import perform as resume
            resume(args.job)
        elif args.resume_media:
            from documentary_media_repair import perform as resume
            resume(args.job)
        elif args.resume_metadata:
            from documentary_metadata_repair import perform as resume
            resume(args.job)
        elif args.resume_length:
            from documentary_length_repair import perform as resume
            resume(args.job)
        else:perform(args.job)
    except Exception as exc:
        if valid_id(args.job):
            path=STATE/args.job/'status.json'
            if path.exists():
                status=read(path);code=error(exc)
                import traceback
                save(JOBS/args.job/'failure-diagnostic-v32.json',dict(
                    exception=type(exc).__name__,phase=status.get('phase'),code=code,at=now(),
                    location=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name)
                        for f in traceback.extract_tb(exc.__traceback__)[-6:]]))
                status.update(state='cancelled' if code=='documentary_cancelled' else 'blocked',phase='stopped',
                              error_code=code,updated_at=now(),quality_approved=False)
                status['ai_usage']=usage(JOBS/args.job)
                budget=JOBS/args.job/'deepseek-usage.json'
                if budget.is_file():status['deepseek_budget']=read(budget)
                save(path,status)
        raise SystemExit(2)

if __name__=='__main__':main()
