"""Read saved reviews and final frames into a bounded ZIP; no AI or job writes."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from PIL import Image, ImageOps, ImageDraw

BATCH='fa402b8286c149e698875a48b471977c'
BASE=Path('/home/videoagent/video-automation/runtime')
STATE=Path('/var/lib/video-agent-prepare/catarsis')/BATCH
CHANNELS=('stunning-facts-of-history','stunning-revelations')

def safe(path):
    if any(p.is_symlink() for p in (path,*path.parents)):raise RuntimeError('export_symlink_rejected')
    return path

def sha(path):
    h=hashlib.sha256()
    with safe(path).open('rb') as stream:
        while data:=stream.read(1024*1024):h.update(data)
    return h.hexdigest()

def load(path):
    raw=safe(path).read_bytes()
    if len(raw)>2*1024*1024:raise RuntimeError('export_json_too_large')
    return json.loads(raw)

def redact(value):
    if isinstance(value,dict):return {k:redact(v) for k,v in value.items()}
    if isinstance(value,list):return [redact(v) for v in value]
    if isinstance(value,str):
        value=re.sub(r'\bsk-[A-Za-z0-9_-]+','[oculto]',value)
        value=re.sub(r'(?i)Bearer\s+[^\s"<>]+','Bearer [oculto]',value)
        return re.sub(r'(?i)([?&](?:token|api_key|secret|signature|x-amz-signature)=)[^\s&"<>]+',r'\1[oculto]',value)
    return value

status=load(STATE/'status.json')
if status.get('state') not in ('blocked','partial','ready','interrupted'):
    raise SystemExit('El lote sigue activo; no se exporta durante el procesamiento.')
report=dict(batch_id=BATCH,read_only=True,ai_requests=0,network_requests=0,files_modified=False,status=status,channels={})
entries={}
for c in CHANNELS:
    folder=BASE/'manual-catarsis'/BATCH/c;ledger=BASE/'deepseek-ledger/catarsis'/BATCH/c
    row=dict(files={},sha256={},provider_reviews={});report['channels'][c]=row
    for n in ('editorial-plan.json','project.json','metadata.json','qa.json','deepseek-text-review.json',
        'visual-review.json','blocked.json','framing-evidence.json','asset-credits.json','source-excerpt-proof-v45.json',
        'saved-text-binding-v45.json','saved-finish-receipt-v45.json'):
        p=folder/n
        if p.is_file():row['files'][n]=load(p);row['sha256'][n]=sha(p)
    if (ledger/'budget.json').is_file():
        value=load(ledger/'budget.json');row['budget']={k:value.get(k) for k in ('counts','pending','estimated_usd')}
    for p in sorted(ledger.glob('vision-*.json')):
        if re.fullmatch(r'vision-[a-f0-9]{64}\.json',p.name):row['provider_reviews'][p.name]=load(p)
    row['visual_claims']=sorted(p.name for p in ledger.glob('vision-*.claimed'))
    events=folder/'visual-review-events.jsonl'
    if events.is_file():
        row['visual_event_sha256']=sha(events);row['completed_visual_turns']=[]
        for line in safe(events).read_text(errors='replace').splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('type')=='turn.completed':row['completed_visual_turns'].append(event.get('usage',{}))
    for n in ('video.mp4','catarsis-music-free.mp4'):
        p=folder/n
        if p.is_file():row[n]=dict(bytes=p.stat().st_size,sha256=sha(p))
    if c==CHANNELS[1]:
        row['exported_images']={}
        for p in sorted(folder.glob('review-sheet-*.jpg')):
            with Image.open(safe(p)) as im:
                im.load();out=io.BytesIO();im.convert('RGB').save(out,format='JPEG',quality=80,optimize=True)
            entries[c+'/'+p.name]=out.getvalue()
            row['exported_images'][p.name]=dict(original_sha256=sha(p),export='jpeg_reencoded_for_read_only_inspection')
        p=folder/'thumbnail.jpg'
        with Image.open(safe(p)) as im:
            out=io.BytesIO();im.convert('RGB').save(out,format='JPEG',quality=80,optimize=True)
        entries[c+'/thumbnail.jpg']=out.getvalue()

# Contact sheet of the already-downloaded original newsreel, before grain.
source=BASE/'manual-catarsis'/BATCH/CHANNELS[0]/'media-2.webm'
credits=report['channels'][CHANNELS[0]]['files']['asset-credits.json']
if sha(source)!=credits[2]['sha256']:raise RuntimeError('original_newsreel_hash_changed')
p=subprocess.run(['ffmpeg','-v','error','-threads','1','-filter_threads','1','-i',str(safe(source)),
    '-t','60','-vf','fps=1/2.5,scale=320:240','-an','-f','rawvideo','-pix_fmt','rgb24','-'],
    check=True,capture_output=True,timeout=90)
frame_bytes=320*240*3
if len(p.stdout)%frame_bytes:raise RuntimeError('newsreel_sampling_incomplete')
count=len(p.stdout)//frame_bytes
if not 1<=count<=24:raise RuntimeError('newsreel_sample_count_invalid')
board=Image.new('RGB',(1280,270*((count+3)//4)),'#151515');draw=ImageDraw.Draw(board)
for i in range(count):
    frame=Image.frombytes('RGB',(320,240),p.stdout[i*frame_bytes:(i+1)*frame_bytes])
    x=(i%4)*320;y=(i//4)*270;board.paste(frame,(x,y))
    draw.text((x+8,y+244),f'Original newsreel ~ {i*2.5:.1f} s',fill='white')
out=io.BytesIO();board.save(out,format='JPEG',quality=82,optimize=True)
entries['balto-original-newsreel.jpg']=out.getvalue()
report['source_samples']=dict(source_sha256=sha(source),sample_interval_seconds=2.5,times_approximate=True,
    generated_in_memory=True,added_render_grain=False)
entries['diagnostico-v45.json']=json.dumps(redact(report),ensure_ascii=False,indent=2).encode()
def make_zip():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as archive:
        for name,data in entries.items():archive.writestr(name,data)
    return output.getvalue()
data=make_zip()
if len(data)>1500*1024:
    for name,raw in list(entries.items()):
        if name.endswith('.jpg'):
            with Image.open(io.BytesIO(raw)) as im:
                out=io.BytesIO();ImageOps.contain(im,(1024,1536)).save(out,format='JPEG',quality=72,optimize=True)
            entries[name]=out.getvalue()
    data=make_zip()
if len(data)>2*1024*1024:raise RuntimeError('export_archive_too_large')
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    if archive.testzip() is not None:raise RuntimeError('export_zip_crc_failed')
sys.stdout.buffer.write(data)
