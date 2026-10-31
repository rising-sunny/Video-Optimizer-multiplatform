"""Hoja de contacto: un cuadro cada `step` s, con el segundo anotado."""
import subprocess, sys
import numpy as np
from PIL import Image, ImageDraw
import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()
path, step, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
raw = subprocess.run([FF, "-v", "error", "-i", path, "-vf", f"fps=1/{step},scale=192:144,setsar=1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
fr = np.frombuffer(raw, np.uint8).reshape(-1, 144, 192, 3)
cols = 12; rows = (len(fr) + cols - 1) // cols
sh = Image.new("RGB", (cols * 192, rows * 144))
for i, f in enumerate(fr):
    im = Image.fromarray(f); ImageDraw.Draw(im).text((3, 3), f"{i * step + step / 2:.0f}", fill=(255, 255, 0))
    sh.paste(im, (i % cols * 192, i // cols * 144))
sh.save(out); print(out, len(fr))
