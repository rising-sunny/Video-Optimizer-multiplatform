"""Apply covers only to new IDs recorded by the four automatic Short publishers."""
import argparse
import io
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image
from channels import ACCOUNTS, DAILY, LAB, MATH

STATE=Path('/var/lib/youtube-short-covers')
JOURNALS=Path('/var/lib/mathrelaxing-publisher-cli')

def read(path):
    try: return json.loads(path.read_text())
    except FileNotFoundError: return {}

def jobs(channel, since):
    first=since.astimezone(timezone.utc if channel=='mood' else ZoneInfo('America/Santiago')).date().isoformat()
    if channel in DAILY:
        for f in sorted(DAILY[channel].glob('????-??-??/receipt.json')):
            if f.parent.name<first: continue
            receipt=read(f)
            info=(receipt.get('platforms',{}) if channel=='history' else receipt).get('youtube',{})
            if info.get('video_id'):
                yield info['video_id'], f.parent/'youtube-short-cover.jpg'
    elif channel=='math':
        for e in read(Path('/opt/mathrelaxing-auto/calendar.json'))['items']:
            if e['publish_at'][:10]<first: continue
            draft=read(MATH/'states'/(e['id']+'.json')).get('draft_id')
            if draft:
                vid=read(JOURNALS/(draft+'-youtube.json')).get('video_id')
                if vid: yield vid,MATH/'covers'/(e['id']+'.jpg')
    else:
        for f in sorted((LAB/'receipts').glob('*.json')):
            rec=read(f)
            if rec.get('day','')>=first and rec.get('video_id'):
                yield rec['video_id'], LAB/'covers'/(f.stem+'.jpg')

def account(channel):
    _,expected,token=ACCOUNTS[channel]
    api=build('youtube','v3',credentials=Credentials.from_authorized_user_file(str(token)),cache_discovery=False)
    api._http.timeout=18
    items=api.channels().list(part='id',mine=True).execute(num_retries=1)['items']
    if [x['id'] for x in items]!=[expected]: raise ValueError('channel identity mismatch')
    return api

def attach(api, channel, vid, cover, since):
    res=api.videos().list(part='snippet,status,processingDetails',id=vid).execute(num_retries=1)
    if not res.get('items'): return 'waiting_video'
    video,=res['items']
    if video['snippet']['channelId']!=ACCOUNTS[channel][1]: raise ValueError('video owner mismatch')
    if datetime.fromisoformat(video['snippet']['publishedAt'])<since: return 'before_rollout'
    status=video['status']['uploadStatus']
    if status in ('deleted','rejected','failed'): return 'video_unavailable'
    if video['status']['privacyStatus']!='public': return 'waiting_public'
    if status!='processed' or video.get('processingDetails',{}).get('processingStatus')!='succeeded':
        return 'waiting_processing'
    if cover.resolve()!=cover or not cover.is_file() or not 0<cover.stat().st_size<2_000_000:
        raise ValueError('cover missing or invalid')
    payload=cover.read_bytes()
    with Image.open(io.BytesIO(payload)) as image:
        if image.format!='JPEG' or image.size!=(1080,1920): raise ValueError('invalid cover image')
        image.verify()
    result=api.thumbnails().set(videoId=vid,media_body=MediaIoBaseUpload(io.BytesIO(payload),mimetype='image/jpeg')).execute(num_retries=1)
    if not result.get('items'): raise RuntimeError('missing thumbnail confirmation')
    return 'accepted'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--status',action='store_true');args=parser.parse_args()
    since=datetime.fromisoformat((STATE/'enabled-at').read_text().strip())
    db=sqlite3.connect(STATE/'receipts.sqlite',timeout=15)
    db.execute('create table if not exists covers(channel text, video text, status text, attempts integer, next_try real, detail text, changed real, primary key(channel,video))')
    db.execute('create table if not exists pending(channel text, video text, cover text, primary key(channel,video))')
    if args.status:
        for row in db.execute('select channel,video,status,attempts,detail from covers order by changed desc limit 30'): print(*row)
        return
    errors=[]
    for channel in ACCOUNTS:
        api=None
        try:
            # Keep the original ID even if a later calendar revision removes its entry.
            for ident,cover_path in jobs(channel,since):
                db.execute('insert or ignore into pending values(?,?,?)',(channel,ident,str(cover_path)))
            db.commit()
            for vid,stored_path in db.execute('select video,cover from pending where channel=?',(channel,)).fetchall():
                cover=Path(stored_path)
                if not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid): raise ValueError('invalid video ID in publisher receipt')
                old=db.execute('select status,attempts,next_try from covers where channel=? and video=?',(channel,vid)).fetchone()
                now=time.time()
                if old and (old[0] in ('accepted','before_rollout','video_unavailable') or old[2]>now): continue
                attempt=1 if not old else old[1]+1
                detail=''
                try:
                    if api is None: api=account(channel)
                    status=attach(api,channel,vid,cover,since)
                except HttpError as err:
                    status='retry_api';detail=f'HTTP {err.resp.status} '+str(err.reason)[:180]
                except Exception as err:
                    status='retry_error';detail=f'{type(err).__name__}: {str(err)[:160]}'
                delay=min(21600,120*2**min(8,attempt-1)) if status.startswith('retry') else 120
                db.execute('insert or replace into covers values(?,?,?,?,?,?,?)',(channel,vid,status,attempt,now+delay,detail,now));db.commit()
                print(channel,vid,status,detail,flush=True)
                if status.startswith('retry'):errors.append((channel,vid,status))
        except Exception as err:
            print(channel, type(err).__name__,str(err)[:180],file=sys.stderr);errors.append((channel,'discovery'))
    if errors: sys.exit(1)

if __name__=='__main__': main()
