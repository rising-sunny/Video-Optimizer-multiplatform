import subprocess
import os

with open('test_quotes.ass', 'w') as f:
    f.write('dummy')

cmd1 = ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=16x16:d=1', '-vf', 'subtitles=test.ass', 'out1.mp4']
res1 = subprocess.run(cmd1, capture_output=True, text=True)

cmd2 = ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=16x16:d=1', '-vf', 'subtitles=\'test.ass\'', 'out2.mp4']
res2 = subprocess.run(cmd2, capture_output=True, text=True)

print('test1 success:', res1.returncode == 0)
print('test2 success:', res2.returncode == 0)

ass_path = os.path.abspath('test.ass')
ass_escaped = ass_path.replace('\\\\', '/').replace(':', '\\\\:')
cmd3 = ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=16x16:d=1', '-vf', f"subtitles='{ass_escaped}'", 'out3.mp4']
res3 = subprocess.run(cmd3, capture_output=True, text=True)
print('test3 success:', res3.returncode == 0)
if res3.returncode != 0: print('test3 error:', res3.stderr[-200:])
