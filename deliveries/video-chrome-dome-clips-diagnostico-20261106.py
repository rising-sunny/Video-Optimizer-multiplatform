#!/usr/bin/env python3
"""Read-only check of saved source clips and shot selection. No AI/network/retry."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,'/opt/video-agent-mcp')
import documentary_common as c
from documentary_catarsis_render import timeline
from documentary_layout import part_paths
from documentary_render import probe

job='d1da2fe6dfb746e09694bb2129ff6f80'
folder=c.JOBS/job
ledger=Path('/home/videoagent/video-automation/runtime/deepseek-ledger/documentary')/job
paths=[folder/'editorial-plan.json',folder/'catarsis-media-v31.json',ledger/'budget.json',c.STATE/job/'status.json']

def pin(path):
    if path.is_symlink() or not path.is_file():raise RuntimeError('saved_file_missing_or_symlink')
    return hashlib.sha256(path.read_bytes()).hexdigest()

before={str(p):pin(p) for p in paths}
plan=c.read(paths[0]);pool=c.read(paths[1])['assets'];enriched=copy.deepcopy(pool)
result=dict(job_id=job,read_only=True,ai_requests=0,network_requests=0,
    saved_pool_assets=len(pool),counts=c.read(ledger/'budget.json').get('counts'),clips=[],
    status={k:c.read(paths[-1]).get(k) for k in ('state','phase','error_code','repair_id')})
for index,row in enumerate(pool):
    if row.get('type')!='video':continue
    path=c.safe_path(Path(row['file']))
    item=dict(pool_index=index,original_asset=row.get('original_asset'),origin=row.get('origin'),
        filename=path.name,label=row.get('label'),saved_duration_seconds=row.get('duration_seconds'))
    try:
        info=probe(path);stream=next(s for s in info['streams'] if s.get('codec_type')=='video')
        seconds=float(info['format']['duration'])
        item.update(actual_duration_seconds=seconds,width=stream.get('width'),height=stream.get('height'),
                    codec=stream.get('codec_name'),fps=stream.get('avg_frame_rate'),
                    file_hash_matches=c.sha(path)==row.get('sha256'))
        enriched[index]['duration_seconds']=seconds
        run=subprocess.run(['ffmpeg','-v','error','-protocol_whitelist','file,pipe','-threads','2',
            '-i',str(path),'-t',str(min(6,seconds)),'-vf','fps=2,scale=64:36','-an','-f','framemd5','-'],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30)
        hashes={s.rsplit(',',1)[-1].strip() for s in run.stdout.splitlines() if s and not s.startswith('#')}
        item.update(motion_probe_exit=run.returncode,first_six_seconds_distinct_frames=len(hashes),
                    native_clip_motion_would_pass=(run.returncode==0 and len(hashes)>=3
                        and 2<=seconds<=3600 and stream.get('width',0)>=480 and stream.get('height',0)>=270))
    except Exception as exc:
        item['probe_error']=str(exc) if isinstance(exc,c.Failure) else type(exc).__name__
    result['clips'].append(item)
lengths=[]
try:
    for path in part_paths(folder,len(plan['segments'])):
        stream=next(s for s in probe(path)['streams'] if s.get('codec_type')=='video')
        if stream.get('avg_frame_rate')!='30/1':raise RuntimeError('saved_part_fps_invalid')
        lengths.append(int(stream['nb_frames'])/30)
    result['speech_parts']=len(lengths)
    result['speech_duration_seconds']=sum(lengths)
    for name,rows in (('saved_metadata',pool),('actual_durations_in_memory_only',enriched)):
        try:
            shots=timeline(plan,lengths,rows)
            result[name]=dict(state='passed',shots=len(shots),frames=sum(s['frames'] for s in shots),
                video_shots=sum(s['type']=='video' for s in shots),
                video_source_indexes=sorted({s['asset'] for s in shots if s['type']=='video'}))
        except Exception as exc:
            result[name]=dict(state='blocked',error_code=str(exc) if isinstance(exc,c.Failure) else type(exc).__name__)
except Exception as exc:
    result['speech_probe_error']=str(exc) if isinstance(exc,c.Failure) else type(exc).__name__
result['observed_files_unchanged']=all(pin(p)==before[str(p)] for p in paths)
print(json.dumps(result,ensure_ascii=False,indent=2))
