"""CLI: render un Short de The Lost Atlas.

    python -m lostatlas.make_short                          # 5 rondas geo demo -> auto_videos/lostatlas/<fecha>/
    python -m lostatlas.make_short --stills 1.0,3.0,6.5     # PNG de prueba del primer round (sin codificar)
    python -m lostatlas.make_short --stills 10 --round 2    # cuadro a los 10 s absolutos
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from . import geo
from .questions import GEO_DEMO
from .scenes import IntroScene, OutroScene, RoundScene
from .style import FPS, H, W

ROOT = Path(__file__).resolve().parent.parent


class Timeline:
    def __init__(self, questions, episode=1):
        w50, w110 = geo.load("50m"), geo.load("110m")
        self.scenes = [IntroScene(episode, len(questions))]
        self.scenes += [RoundScene(q, i, len(questions), w50, w110) for i, q in enumerate(questions)]
        self.scenes.append(OutroScene())
        self.starts = np.cumsum([0] + [s.dur for s in self.scenes])
        self.total = float(self.starts[-1])

    def locate(self, t):
        k = int(np.searchsorted(self.starts, t, side="right") - 1)
        k = min(max(k, 0), len(self.scenes) - 1)
        return k, t - self.starts[k]

    def frame(self, t):
        k, tau = self.locate(t)
        img = self.scenes[k].frame(tau)
        if k > 0 and tau < 0.2:                       # fundido corto entre escenas
            prev = self.scenes[k - 1].frame(self.scenes[k - 1].dur - 1 / FPS)
            a = tau / 0.2
            img = cv2.addWeighted(prev, 1 - a, img, a, 0)
        return img


def render(questions, out_dir, episode=1, with_audio=True):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tl = Timeline(questions, episode)
    mp4 = out_dir / "short.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if with_audio:
        from .sound import build_audio
        wav = out_dir / "mix.wav"
        build_audio(tl, wav)
        cmd += ["-i", str(wav), "-af", "loudnorm=I=-14:TP=-1.5:LRA=7,aresample=44100", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(tl.total * FPS)
    t0 = time.time()
    for i in range(n):
        p.stdin.write(tl.frame(i / FPS).tobytes())
        if i % 150 == 0:
            print(f"{i}/{n}  {time.time() - t0:.0f}s", flush=True)
    p.stdin.close()
    p.wait()
    (out_dir / "questions.json").write_text(json.dumps(questions, indent=1, ensure_ascii=False), encoding="utf-8")
    return mp4


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", help="tiempos en segundos separados por coma (relativos a --round, o absolutos si no hay)")
    ap.add_argument("--round", type=int, help="indice de ronda 0-based para --stills")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--episode", type=int, default=1)
    a = ap.parse_args()
    qs = GEO_DEMO
    if a.stills:
        tl = Timeline(qs, a.episode)
        base = float(tl.starts[1 + a.round]) if a.round is not None else 0.0
        out = Path(a.out or ROOT / "auto_videos" / "lostatlas" / "stills")
        out.mkdir(parents=True, exist_ok=True)
        for s in a.stills.split(","):
            t = base + float(s)
            f = out / f"t{t:06.2f}.png"
            cv2.imwrite(str(f), tl.frame(t))
            print(f)
    else:
        out = a.out or ROOT / "auto_videos" / "lostatlas" / time.strftime("%Y%m%d_%H%M%S")
        print(render(qs, out, a.episode, not a.no_audio))
