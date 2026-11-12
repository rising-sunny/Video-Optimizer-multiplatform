"""python -m codeart.render --scene tree|rain|aurora|sunflower|fireflies --seconds 16 --out out/dir [--fps 60]"""
import argparse, json, subprocess, sys, time
from pathlib import Path
from .common import W, H, FPS
from .tree import TreeScene
from .rain import RainScene
from .aurora import AuroraScene
from .sunflower import SunflowerScene
from .audio import make_pad, make_nature, make_night
from .fireflies import FirefliesScene

SCENES = {"tree": TreeScene, "rain": RainScene, "aurora": AuroraScene, "sunflower": SunflowerScene, "fireflies": FirefliesScene}


def render(scene, seconds, out_dir, fps=FPS):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    sc = SCENES[scene]()
    n = int(seconds * fps)
    wav, mp4 = out_dir / "pad.wav", out_dir / f"{scene}.mp4"
    {"nature": make_nature, "night": make_night}.get(getattr(sc, "audio_kind", ""), make_pad)(seconds, wav, events=getattr(sc, "audio_events", ()))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(mp4)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    for i in range(n):
        p.stdin.write(sc.frame(i, n).tobytes())
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
