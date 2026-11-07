"""Bounded read-only previews of existing local video frames, never generation."""
import base64
from pathlib import Path
import subprocess
import workflow_common as c

def frames(job):
    video=c.safe(Path(job)/'video.mp4')
    if not video.is_file():return []
    before=c.digest(video);result=[]
    for seconds in (4.0,7.0,20.0,24.5):
        response=subprocess.run(['ffmpeg','-v','error','-threads','1','-ss',str(seconds),
            '-i',str(video),'-frames:v','1','-vf','scale=360:640','-c:v','mjpeg','-q:v','4','-f','image2pipe','-'],
            capture_output=True,timeout=15)
        if response.returncode or not response.stdout.startswith(b'\xff\xd8') or len(response.stdout)>100000:
            continue
        result.append(dict(seconds=seconds,mime_type='image/jpeg',video_sha256=before,
            image_base64=base64.b64encode(response.stdout).decode(),quality_approval=False))
    if c.digest(video)!=before:return []
    return result
