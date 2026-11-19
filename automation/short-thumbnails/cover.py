#!/opt/mathrelaxing-publisher/venv/bin/python -B
"""Render a branded, episode-specific portrait cover from the finished Short."""
import argparse
import hashlib
import io
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from channels import ACCOUNTS

ROOT = Path(__file__).resolve().parent
FONTS = Path('/usr/share/fonts/truetype/dejavu')
STYLE = {
    'lab': ('#f2efe2', '#163c3e', '#ad542e', 'DejaVuSansCondensed-Bold.ttf'),
    'math': ('#080b17', '#eeefff', '#95cfee', 'DejaVuSansCondensed-Bold.ttf'),
    'history': ('#1a2224', '#fff3d9', '#e6b768', 'DejaVuSerifCondensed-Bold.ttf'),
    'mood': ('#282237', '#fdf0da', '#f2c7bd', 'DejaVuSerifCondensed.ttf'),
}

def cover_title(title):
    title = re.sub(r'\s+#\w+|\s*\|\s*Math Art\s*$', '', title, flags=re.I)
    # A trailing emoji often separates the hook from a search label in Mood titles.
    for i, c in enumerate(title):
        if unicodedata.category(c)=='So' and len(title[:i].split())>=3:
            title=title[:i];break
    title = ''.join(c if unicodedata.category(c) not in ('So','Cf') and c != '\ufe0f' else ' ' for c in title)
    return ' '.join(title.split()) or 'Watch closely'

def title_lines(draw, title, face):
    words=title.split()
    for size in range(81, 28, -2):
        font=ImageFont.truetype(str(FONTS/face),size)
        lines=[]
        for word in words:
            if lines and draw.textlength(lines[-1]+' '+word,font=font)<=914:
                lines[-1]+=' '+word
            else:
                lines.append(word)
        if len(lines)*(size+10)<=292 and all(draw.textlength(line,font=font)<=914 for line in lines):
            return font,lines
    raise ValueError('Title could not be fitted')

def frame(media, channel):
    # Sample before the reveal in the lab and after the opening in atmospheric pieces.
    sec={'lab':4.4,'math':5.0,'history':4.0,'mood':6.0}[channel]
    for offset in (sec,0):
        p=subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(offset),'-i',str(media),
             '-map','0:v:0','-frames:v','1','-vf','scale=720:1280','-threads','1',
             '-f','image2pipe','-vcodec','png','pipe:1'],check=True,capture_output=True,timeout=45)
        if p.stdout: return Image.open(io.BytesIO(p.stdout)).convert('RGB')
    raise ValueError('No video frame available')

def prepare(channel, media, title, target):
    media,target=Path(media),Path(target)
    stat=media.stat()
    signature=hashlib.sha256(f'v2|{channel}|{title}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()
    if target.exists():
        try:
            with Image.open(target) as last:
                if last.size==(1080,1920) and last.getexif().get(270)==signature:
                    last.verify()
                    return target
        except (OSError, ValueError): pass
    pic=frame(media,channel)
    bg,fg,accent,face=STYLE[channel]
    canvas=Image.new('RGB',(1080,1920),bg)
    d=ImageDraw.Draw(canvas)
    if channel=='mood':
        canvas.paste(ImageOps.fit(pic.crop((0,12,720,1160)),(1080,1110)),(0,700))
    elif channel=='history':
        canvas.paste(ImageOps.fit(pic.crop((0,170,720,1100)),(1080,1110)),(0,710))
    elif channel=='math':
        canvas.paste(ImageOps.contain(pic.crop((0,223,720,887)),(1048,1090)),(16,735))
    else:
        panel=ImageOps.contain(pic.crop((40,330,665,887)),(996,990))
        canvas.paste(panel,((1080-panel.width)//2,750))
    with Image.open(ROOT/'brand'/(channel+'.png')) as logo:
        canvas.paste(logo.convert('RGB').resize((132,132),Image.Resampling.LANCZOS),(75,98))
    d.text((237,161),ACCOUNTS[channel][0],font=ImageFont.truetype(str(FONTS/'DejaVuSansCondensed-Bold.ttf'),42),fill=fg,anchor='lm')
    d.line((75,265,1005,265),fill=accent,width=3)
    font,lines=title_lines(d,cover_title(title),face)
    top=325+(291-len(lines)*(font.size+10))//2
    for i,line in enumerate(lines):
        d.text((75,top+i*(font.size+10)),line,font=font,fill=fg,anchor='lt')
    d.rectangle((75,667,181,675),fill=accent)
    target.parent.mkdir(parents=True,exist_ok=True)
    exif=Image.Exif();exif[270]=signature
    # Match the stream's umask-independent reading requirements in either publisher context.
    with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f: temp=Path(f.name)
    try:
        canvas.save(temp,format='JPEG',quality=91,subsampling=0,optimize=True,exif=exif)
        with Image.open(temp) as check: check.verify()
        temp.chmod(0o644)
        os.replace(temp,target)
    finally: temp.unlink(missing_ok=True)
    return target

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('channel',choices=STYLE);p.add_argument('video',type=Path)
    p.add_argument('title');p.add_argument('destination',type=Path);args=p.parse_args()
    prepare(args.channel,args.video,args.title,args.destination)
