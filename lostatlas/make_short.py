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
from .questions_empire import EMPIRE_DEMO
from .questions_year import YEAR_DEMO
from .scenes import TRANSITION, IntroScene, OutroScene, RoundScene
from .style import FPS, H, W
from .year_scene import YearRoundScene

ROOT = Path(__file__).resolve().parent.parent


def slide(prev, new, k):
    """La hoja anterior se desliza hacia la izquierda y proyecta una sombra corta sobre la nueva."""
    e = k * k * (3 - 2 * k)
    x = int(round(W * e))
    if x <= 0:
        return prev
    if x >= W:
        return new
    edge = W - x
    out = new.copy()
    out[:, :edge] = prev[:, x:]
    wsh = min(90, x)
    f = (1 - 0.36 * np.exp(-np.arange(wsh, dtype=np.float32) / 26))[None, :, None]
    out[:, edge:edge + wsh] = (out[:, edge:edge + wsh].astype(np.float32) * f).astype(np.uint8)
    out[:, max(edge - 3, 0):edge] = (out[:, max(edge - 3, 0):edge] * 0.8).astype(np.uint8)
    return out


class Timeline:
    def __init__(self, questions, episode=1):
        w50, w110 = geo.load("50m"), geo.load("110m")
        task = "name the year" if "year" in questions[0] else "name the empire" if "map_year" in questions[0] else "name the country"
        self.scenes = [IntroScene(episode, len(questions), task)]
        self.scenes += [self._round(q, i, len(questions), w50, w110) for i, q in enumerate(questions)]
        self.scenes.append(OutroScene())
        self.starts = np.cumsum([0] + [s.dur for s in self.scenes])
        self.total = float(self.starts[-1])
        self._last = {}

    @staticmethod
    def _round(q, i, n, w50, w110):
        if "year" in q:
            return YearRoundScene(q, i, n, w50, w110)
        if "map_year" in q:
            from . import hist
            return RoundScene(q, i, n, hist.load_dict(q["map_year"], q["select"], q["country"]), w110)
        return RoundScene(q, i, n, w50, w110)

    def locate(self, t):
        k = int(np.searchsorted(self.starts, t, side="right") - 1)
        k = min(max(k, 0), len(self.scenes) - 1)
        return k, t - self.starts[k]

    def frame(self, t):
        k, tau = self.locate(t)
        img = self.scenes[k].frame(tau)
        if k > 0 and tau < TRANSITION:
            if k - 1 not in self._last:
                self._last = {k - 1: self.scenes[k - 1].frame(self.scenes[k - 1].dur - 1 / FPS)}
            img = slide(self._last[k - 1], img, tau / TRANSITION)
        return img


def render(questions, out_dir, episode=1, with_audio=True, bgm=None, bgm_start=0.0):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tl = Timeline(questions, episode)
    mp4 = out_dir / "short.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if with_audio:
        from .sound import build_audio
        wav = out_dir / "mix.wav"
        build_audio(tl, wav, bgm, bgm_start)
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
    ap.add_argument("--template", choices=["geo", "year", "empire"], default="geo")
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--bgm", help="titulo de Incompetech (p. ej. Zanzibar) o ruta a un MP3 propio (p. ej. de la Biblioteca de Audio de YouTube)")
    ap.add_argument("--bgm-start", type=float, default=0.0)
    ap.add_argument("--audio-only", action="store_true", help="solo mezcla de audio en MP3 (para comparar pistas)")
    a = ap.parse_args()
    qs = {"year": YEAR_DEMO, "empire": EMPIRE_DEMO}.get(a.template, GEO_DEMO)
    bgm, attribution = None, None
    if a.bgm:
        if Path(a.bgm).exists():
            bgm = Path(a.bgm)
        else:
            from .music_lib import fetch
            bgm, attribution, _ = fetch(a.bgm)
    if a.audio_only:
        from .sound import build_audio
        tl = Timeline(qs, a.episode)
        out = Path(a.out or ROOT / "auto_videos" / "lostatlas" / "music_preview")
        out.mkdir(parents=True, exist_ok=True)
        name = (a.bgm or "original").replace(" ", "_")
        wav = out / f"{name}.wav"
        build_audio(tl, wav, bgm, a.bgm_start)
        mp3 = out / f"{name}.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", "loudnorm=I=-14:TP=-1.5:LRA=7", "-b:a", "128k", str(mp3)], check=True)
        wav.unlink()
        print(mp3)
        sys.exit(0)
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
        mp4 = render(qs, out, a.episode, not a.no_audio, bgm, a.bgm_start)
        print(mp4)
        extra = None
        if a.template == "empire":
            from .hist import ATTRIBUTION
            extra = "Maps:\n" + ATTRIBUTION
        if attribution:
            (Path(out) / "attribution.txt").write_text("Music:\n" + attribution + "\n" + (("\n" + extra + "\n") if extra else ""), encoding="utf-8")
        from .publish_pack import write_package
        meta = write_package(out, mp4, a.template, qs, ("Music:\n" + attribution) if attribution else None, extra)
        print(f"metadata.json listo ({meta['title']}) - fact_check={meta['fact_check']}. Subir: python -m lostatlas.upload {out}")
