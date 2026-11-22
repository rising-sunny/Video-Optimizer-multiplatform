"""Audio procedural (sin samples, sin licencias): tic-tac de reloj, maquina de escribir, pluma, sello.

Todo se ubica a partir de los mismos tiempos que usa el video (scenes.py), asi que no se desfasa.
"""
import wave

import numpy as np
from scipy.signal import butter, sosfilt

from .scenes import CD, CLUE_T, CPS, CS, REV, IntroScene, OutroScene, RoundScene

SR = 44100
_rng = np.random.default_rng(11)


def _bp(x, lo, hi):
    return sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), x)


def _lp(x, hi):
    return sosfilt(butter(2, hi, "low", fs=SR, output="sos"), x)


def _t(n):
    return np.arange(n) / SR


def tick(tock=False, accent=False):
    n = int(0.10 * SR)
    t = _t(n)
    click = _bp(_rng.standard_normal(n), 2400, 6800) * np.exp(-t / 0.0035)
    thock = np.sin(2 * np.pi * (1050 if tock else 1450) * t) * np.exp(-t / 0.016) * 0.55
    return (click * 1.3 + thock) * (1.0 if accent else 0.62)


def key(space=False):
    n = int(0.06 * SR)
    t = _t(n)
    click = _bp(_rng.standard_normal(n), 1500, 7000) * np.exp(-t / 0.003)
    thump = np.sin(2 * np.pi * (115 if space else 170) * t) * np.exp(-t / 0.014) * (0.9 if space else 0.55)
    return (click * 0.9 + thump) * _rng.uniform(0.55, 1.0)


def stamp_hit():
    n = int(1.4 * SR)
    t = _t(n)
    f = 40 + 55 * np.exp(-t / 0.05)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.13)
    slap = _lp(_rng.standard_normal(n), 1100) * np.exp(-t / 0.05) * 0.9
    paper = _bp(_rng.standard_normal(n), 900, 4200) * np.exp(-t / 0.022) * 0.45
    # una nota calida y corta: confirma el acierto sin sonar a videojuego
    note = (np.sin(2 * np.pi * 523.25 * t) + 0.45 * np.sin(2 * np.pi * 784 * t)) * np.exp(-t / 0.45) * np.minimum(1, t / 0.004) * 0.10
    return body * 1.1 + slap + paper + note


def pen(seconds):
    n = int(seconds * SR)
    t = _t(n)
    env = np.zeros(n)
    pos = 0
    while pos < n:
        d = int(_rng.uniform(0.04, 0.13) * SR)
        env[pos:pos + d] = _rng.uniform(0.4, 1.0) * np.sin(np.linspace(0, np.pi, min(d, n - pos)))
        pos += d + int(_rng.uniform(0.01, 0.07) * SR)
    return _bp(_rng.standard_normal(n), 1800, 7500) * env * (0.5 + 0.5 * np.sin(2 * np.pi * 9 * t) ** 2)


def _put(buf, sig, at, gain=1.0, pan=0.5):
    i = int(at * SR)
    if i < 0 or i >= buf.shape[1]:
        return
    sig = sig[:buf.shape[1] - i] * gain
    buf[0, i:i + len(sig)] += sig * (1 - pan) * 1.4
    buf[1, i:i + len(sig)] += sig * pan * 1.4


def build_audio(tl, path):
    total = tl.total
    n = int(total * SR)
    buf = np.zeros((2, n), np.float32)
    t = _t(n)
    # cuarto: aire grave + un zumbido casi imperceptible
    room = _lp(_rng.standard_normal(n), 260) * 0.020
    drone = (np.sin(2 * np.pi * 110 * t) + 0.6 * np.sin(2 * np.pi * 164.81 * t)) * 0.010 * (0.7 + 0.3 * np.sin(2 * np.pi * t / 9))
    buf += (room + drone).astype(np.float32)

    for k, sc in enumerate(tl.scenes):
        b = float(tl.starts[k])
        if isinstance(sc, IntroScene):
            _put(buf, pen(1.3), b, 0.13)
            _put(buf, stamp_hit(), b + 1.15, 0.8)
        elif isinstance(sc, OutroScene):
            _put(buf, pen(1.9), b + 0.45, 0.12)
            _put(buf, stamp_hit()[: int(1.0 * SR)] * 0.35, b + 0.2, 0.5)
        elif isinstance(sc, RoundScene):
            _put(buf, pen(1.0), b + 0.15, 0.12)
            for j, text in enumerate(sc.q["clues"]):
                for i, ch in enumerate(text):
                    _put(buf, key(ch == " "), b + CLUE_T[j] + i / CPS, 0.55, pan=_rng.uniform(0.42, 0.58))
            _put(buf, tick(accent=True), b + CS, 0.55)
            for s in range(1, int(CD)):
                _put(buf, tick(tock=s % 2 == 1, accent=s >= int(CD) - 2), b + CS + s, 0.62 if s < int(CD) - 2 else 0.85)
            _put(buf, stamp_hit(), b + REV, 0.95)

    peak = np.abs(buf).max() + 1e-9
    pcm = (buf / peak * 0.85 * np.minimum(1, np.minimum(t / 0.3, (total - t) / 0.6))).T
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((pcm * 32767).astype(np.int16).tobytes())
    return path
