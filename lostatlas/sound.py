"""Audio procedural (sin samples, sin licencias): efectos + musica original, todo anclado a los tiempos del video."""
import subprocess
import wave

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

from . import music
from .scenes import CD, CLUE_T, CPS, CS, REV, TRANSITION, IntroScene, OutroScene, RoundScene

SR = 44100
_rng = np.random.default_rng(11)
_put = music._put


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


def typewriter_bell():
    t = _t(int(0.9 * SR))
    return (np.sin(2 * np.pi * 3136 * t) + 0.35 * np.sin(2 * np.pi * 6272 * t) * np.exp(-t / 0.15)) * np.exp(-t / 0.28) * np.minimum(1, t / 0.002)


def carriage():
    n = int(0.16 * SR)
    t = _t(n)
    return _bp(_rng.standard_normal(n), 700, 3200) * np.exp(-t / 0.07) * np.minimum(1, t / 0.01) * 0.6


def stamp_hit():
    n = int(1.4 * SR)
    t = _t(n)
    f = 40 + 55 * np.exp(-t / 0.05)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.13)
    slap = _lp(_rng.standard_normal(n), 1100) * np.exp(-t / 0.05) * 0.9
    paper = _bp(_rng.standard_normal(n), 900, 4200) * np.exp(-t / 0.022) * 0.45
    dry = body * 1.1 + slap + paper
    ir = _rng.standard_normal(int(0.7 * SR)) * np.exp(-_t(int(0.7 * SR)) / 0.16)         # habitacion pequena
    wet = fftconvolve(dry, ir)[:n] * 0.012
    return dry + wet


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


def whoosh(dur=0.6):
    """Hoja de papel que se desliza: tres bandas con picos escalonados (graves -> agudos)."""
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for lo, hi, peak, w, g in ((180, 900, 0.20, 0.13, 1.0), (900, 3200, 0.24, 0.11, 0.8), (3200, 9000, 0.27, 0.09, 0.45)):
        out += _bp(_rng.standard_normal(n), lo, hi) * np.exp(-((t - peak) / w) ** 2) * g
    return out


def paper_land():
    n = int(0.25 * SR)
    t = _t(n)
    return (_lp(_rng.standard_normal(n), 700) * np.exp(-t / 0.05) + np.sin(2 * np.pi * 85 * t) * np.exp(-t / 0.07) * 0.8) * 0.6


def pencil_tap(f=520):
    n = int(0.1 * SR)
    t = _t(n)
    fr = f * (1 - 0.4 * np.minimum(1, t / 0.08))
    return (np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-t / 0.03) + _bp(_rng.standard_normal(n), 2000, 6000) * np.exp(-t / 0.006) * 0.6) * 0.8


def _load_bgm(path, start, total):
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", str(start), "-i", str(path), "-t", str(total + 1), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]
    a = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32).reshape(-1, 2).T
    n = int(total * SR)
    while a.shape[1] < n:                                   # pista corta: se repite
        a = np.concatenate([a, a], axis=1)
    return np.ascontiguousarray(a[:, :n])


def build_audio(tl, path, bgm=None, bgm_start=0.0):
    total = tl.total
    n = int(total * SR)
    sfx = np.zeros((2, n), np.float32)
    mus = np.zeros((2, n), np.float32)
    t = _t(n)
    room = _lp(_rng.standard_normal(n), 260) * 0.020
    sfx += (room * np.ones((2, 1))).astype(np.float32)

    for k, sc in enumerate(tl.scenes):
        b = float(tl.starts[k])
        if k >= 1:                                              # transicion: hoja que se desliza
            _put(sfx, whoosh(), b - 0.02, 0.55)
            _put(sfx, paper_land(), b + TRANSITION - 0.06, 0.5)
        if isinstance(sc, IntroScene):
            _put(sfx, pen(1.3), b, 0.13)
            _put(sfx, stamp_hit(), b + 1.15, 0.8)
            if bgm is None:
                music.intro_music(mus, b)
        elif isinstance(sc, OutroScene):
            _put(sfx, pen(1.9), b + 0.45, 0.12)
            for i in range(5):
                _put(sfx, pencil_tap(480 + 60 * i), b + 0.5 + 0.22 * i + 0.30, 0.45)
            if bgm is None:
                music.outro_music(mus, b)
        elif isinstance(sc, RoundScene):
            r = k - 1
            _put(sfx, pen(1.0), b + 0.15 + TRANSITION * 0.4, 0.12)
            for j, text in enumerate(sc.q["clues"]):
                for i, ch in enumerate(text):
                    _put(sfx, key(ch == " "), b + CLUE_T[j] + i / CPS, 0.5, pan=_rng.uniform(0.42, 0.58))
                end = b + CLUE_T[j] + len(text) / CPS
                _put(sfx, carriage(), end + 0.05, 0.4)
                _put(sfx, typewriter_bell(), end + 0.12, 0.22)
            _put(sfx, tick(accent=True), b + CS, 0.55)
            for s in range(1, int(CD)):
                _put(sfx, tick(tock=s % 2 == 1, accent=s >= int(CD) - 2), b + CS + s, 0.62 if s < int(CD) - 2 else 0.85)
            _put(sfx, stamp_hit(), b + REV, 0.95)
            _put(sfx, pencil_tap(620), b + REV + 0.55, 0.35, 0.7)           # aparece el globo
            if bgm is None:
                music.round_music(mus, b, r, CS)

    if bgm is not None:
        mus = _load_bgm(bgm, bgm_start, total)
        mus = mus / (np.sqrt((mus ** 2).mean()) + 1e-9) * 0.085           # nivel por RMS: igual para cualquier pista
        env = np.minimum(1, np.minimum(t / 0.8, (total - t) / 1.6)).astype(np.float32)
        for k, sc in enumerate(tl.scenes):                                 # la musica se agacha un instante en cada sello
            if isinstance(sc, RoundScene):
                i0 = int((float(tl.starts[k]) + REV - 0.03) * SR)
                d = np.ones(n)
                d[i0:i0 + int(0.6 * SR)] = np.linspace(0.45, 1.0, int(0.6 * SR)) ** 0.7
                env = env * np.convolve(d, np.ones(401) / 401, "same").astype(np.float32)
        mus = mus * env
        mix = sfx + mus
    else:
        peak_m = np.abs(mus).max() + 1e-9
        mix = sfx * 1.0 + mus / peak_m * 0.30
    mix = mix / (np.abs(mix).max() + 1e-9)
    pcm = (mix * 0.85 * np.minimum(1, np.minimum(t / 0.3, (total - t) / 0.7))).T
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((pcm * 32767).astype(np.int16).tobytes())
    return path
