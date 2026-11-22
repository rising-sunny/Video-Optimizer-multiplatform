"""CLI del largo horizontal.

    python -m lostatlas.make_long --stills 8 --state Texas --allow-missing     # cuadros de prueba (segundos desde el inicio de la ronda)
    python -m lostatlas.make_long --render auto_videos/lostatlas/long --limit 3  # prueba corta
    python -m lostatlas.make_long --render auto_videos/lostatlas/long            # el largo completo
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import cv2

from . import long_states as LS
from .long_timeline import LongTimeline
from .long_scenes import FPS, LH, LW

ROOT = Path(__file__).resolve().parent.parent
# Cadena de masterizacion medida el 2026-11-22: la mezcla tiene transitorios fuertes (golpes del sello) y poco volumen medio, asi que un
# loudnorm de una pasada deja picos reales de +1,8 dBFS. Compresor suave + -15 LUFS + limitador rapido dio -15,4 LUFS y pico -1,3 dBFS tras el AAC.
MASTER = ("acompressor=threshold=0.1:ratio=5:attack=3:release=100:makeup=2,loudnorm=I=-15:TP=-2:LRA=7,"
          "alimiter=limit=0.7:attack=2:release=40:level=disabled,aresample=44100")


def data_for(allow_missing):
    data = LS.load()
    for _i, _n, _l, st in LS.order():
        if st not in data:
            if not allow_missing:
                sys.exit(f"Falta el estado {st} (corre: python -m lostatlas.long_states --gen)")
            data[st] = dict(state=st, clues=["Placeholder clue one", "Placeholder clue two", "Capital: Placeholder"])
    return data


def render(tl, out_dir, audio=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / "long.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{LW}x{LH}", "-r", str(FPS), "-i", "-"]
    if audio:
        cmd += ["-i", str(audio), "-af", MASTER, "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(tl.total * FPS)
    t0 = time.time()
    for i in range(n):
        p.stdin.write(tl.frame(i / FPS).tobytes())
        if i % 300 == 0:
            print(f"{i}/{n}  {time.time() - t0:.0f}s", flush=True)
    p.stdin.close()
    p.wait()
    return mp4


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", help="segundos separados por coma (relativos a --state, o absolutos)")
    ap.add_argument("--state")
    ap.add_argument("--render")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    a = ap.parse_args()
    tl = LongTimeline(data_for(a.allow_missing or bool(a.stills)), limit=a.limit)
    if a.stills:
        base = 0.0
        if a.state:
            seg = next(p for p in tl.plan if p["kind"] == "round" and p["state"] == a.state)
            base = seg["start"]
        out = ROOT / "auto_videos" / "lostatlas" / "stills_long"
        out.mkdir(parents=True, exist_ok=True)
        for s in a.stills.split(","):
            t = base + float(s)
            f = out / f"{(a.state or 'abs').replace(' ', '_')}_{float(s):05.2f}.png"
            cv2.imwrite(str(f), tl.frame(t, transitions=False))
            print(f)
    elif a.render:
        audio, attribution = None, []
        if not a.no_audio:
            from .long_sound import build_audio
            audio = Path(a.render) / "mix.wav"
            Path(a.render).mkdir(parents=True, exist_ok=True)
            attribution = build_audio(tl, audio)
        mp4 = render(tl, a.render, audio)
        print(mp4)
        if a.limit is None and attribution:
            from .long_pack import build
            meta = build(tl, attribution, a.render)
            print(f"metadata.json y miniatura listos: {meta['title']} | fact_check={meta['fact_check']}")
