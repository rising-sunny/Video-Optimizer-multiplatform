"""python -m codeart.render --scene tree|rain|aurora|sunflower|fireflies --seconds 16 --out out/dir [--fps 60]"""
import argparse, json, subprocess, sys, time
import numpy as np
from pathlib import Path
from .common import W, H, FPS, text_layer, blit_text
from .tree import TreeScene
from .rain import RainScene
from .aurora import AuroraScene
from .sunflower import SunflowerScene
from .audio import make_pad, make_nature, make_night
from .fireflies import FirefliesScene
from .pendulum import PendulumScene
from .lava import LavaScene
from .clouds import CloudsScene
from .stars import StarsScene

SCENES = {"tree": TreeScene, "rain": RainScene, "aurora": AuroraScene, "sunflower": SunflowerScene, "fireflies": FirefliesScene, "pendulum": PendulumScene, "lava": LavaScene, "clouds": CloudsScene, "stars": StarsScene}


SERIES = "CODE ATMOSPHERES"
CTA_SECONDS = 2.2


def _cta(img, i, n, fps, layers):
    """Ultimos CTA_SECONDS: nombre de la serie y 'Subscribe' en el tercio inferior (fuera de la zona de la interfaz)."""
    k = (i - (n - CTA_SECONDS * fps)) / (0.6 * fps)
    if k <= 0:
        return img
    o = min(1.0, k)
    out = img.astype(np.float32)
    band = np.zeros((H, W, 1), np.float32); y0, y1 = int(H * 0.70), int(H * 0.80); band[y0:y1] = 0.38 * o
    out = out * (1 - band)
    blit_text(out, layers[0], W / 2, H * 0.735, o); blit_text(out, layers[1], W / 2, H * 0.772, o)
    return np.clip(out, 0, 255).astype(np.uint8)


def render(scene, seconds, out_dir, fps=FPS, params=None, cta=True):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    sc = SCENES[scene](**(params or {}))
    layers = (text_layer(SERIES, 40, True, (255, 244, 220)), text_layer('Subscribe for a new one every few days', 26, False, (235, 235, 235)))
    n = int(seconds * fps)
    wav, mp4 = out_dir / "pad.wav", out_dir / f"{scene}.mp4"
    {"nature": make_nature, "night": make_night}.get(getattr(sc, "audio_kind", ""), make_pad)(seconds, wav, events=getattr(sc, "audio_events", ()))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-af", "loudnorm=I=-15:TP=-1.5:LRA=7,aresample=44100", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest", "-movflags", "+faststart", str(mp4)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    for i in range(n):
        fr = sc.frame(i, n)
        if cta and i >= n - CTA_SECONDS * fps:
            fr = _cta(fr, i, n, fps, layers)
        p.stdin.write(fr.tobytes())
        if i % 120 == 0:
            print(f"{i}/{n} {time.time() - t0:.0f}s", flush=True)
    p.stdin.close(); p.wait()
    meta = {"scene": scene, "seconds": seconds, "fps": fps, "stats": sc.title_stats, "file": mp4.name}
    (out_dir / "render_info.json").write_text(json.dumps(meta, indent=1))
    return mp4


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True, choices=SCENES)
    ap.add_argument("--seconds", type=float, default=16)
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--out", default="auto_videos/codeart")
    a = ap.parse_args()
    print(render(a.scene, a.seconds, Path(a.out) / a.scene, a.fps))
