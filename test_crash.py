import traceback
import sys
import os
from auto_video_generator_v2 import AutoVideoGenerator
from PIL import Image

dummy_img = "test_img.jpg"
Image.new('RGB', (1080, 1920), color = 'red').save(dummy_img)

dummy_audio = "test_audio.mp3"
os.system(f'ffmpeg -y -nostdin -f lavfi -i anullsrc=r=44100:cl=mono -t 10 -q:a 9 -acodec libmp3lame {dummy_audio}')

clips_data = [
    {'filename': dummy_img, 'duration': 4.3},
    {'filename': dummy_img, 'duration': 5.0}
]

class MyGenerator(AutoVideoGenerator):
    def log(self, message):
        print("[LOG]", message)
        sys.stdout.flush()

try:
    gen = MyGenerator()
    gen.generated_media_dir = "projects"
    gen._assemble_direct_ffmpeg(
        clips_data=clips_data, 
        audio_file_path=dummy_audio, 
        output_path="test_out.mp4", 
        resolution=(1080, 1920), 
        fps=30, 
        transition_type='none', 
        transition_duration=0.5
    )
    print("ASSEMBLY COMPLETED SUCCESSFULLY")
except Exception as e:
    print(f"FAILED WITH EXCEPTION: {e}")
    traceback.print_exc()
