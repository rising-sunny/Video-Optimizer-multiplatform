"""Musica original generada por codigo (sin samples): no puede dar reclamos de Content ID.

Reloj: 120 BPM, el tic de la cuenta regresiva cae cada 1 s = tiempos 1 y 3 del compas.
Cada ronda es una frase i - V - i que sube un tono por ronda (Re, Mi, Fa, Sol, La menor);
el sello cae sobre el acorde de resolucion. Timbres: marimba, bajo pizzicato, campana, shaker.
"""
import numpy as np
from scipy.signal import butter, sosfilt

SR = 44100
BEAT = 0.5                                  # 120 BPM
KEYS = (0, 2, 3, 5, 7, 9, 10)               # semitonos sobre Re menor, por ronda
_rng = np.random.default_rng(23)
ARP8 = (0, 1, 2, 3, 2, 1, 2, 1)
ARP16 = (0, 1, 2, 3, 2, 1, 2, 3, 0, 1, 2, 3, 2, 1, 3, 2)


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _t(n):
    return np.arange(n) / SR


def _bp(x, lo, hi):
    return sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), x)


def marimba(m, dur=0.6):
    f, t = mtof(m), _t(int(dur * SR))
    s = (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.20) + 0.33 * np.sin(2 * np.pi * f * 3.98 * t) * np.exp(-t / 0.045)
         + 0.10 * np.sin(2 * np.pi * f * 9.2 * t) * np.exp(-t / 0.02))
    return s * np.minimum(1, t / 0.002)


def bass(m, dur=0.7):
    f, t = mtof(m), _t(int(dur * SR))
    s = (np.sin(2 * np.pi * f * t) + 0.45 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t / 0.10)) * np.exp(-t / 0.30)
    return s * np.minimum(1, t / 0.003)


def bell(m, dur=2.0):
    f, t = mtof(m), _t(int(dur * SR))
    s = (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.9) + 0.4 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t / 0.5)
         + 0.2 * np.sin(2 * np.pi * f * 5.4 * t) * np.exp(-t / 0.25))
    return s * np.minimum(1, t / 0.004)


def shaker(accent=1.0):
    n = int(0.05 * SR)
    t = _t(n)
    return _bp(_rng.standard_normal(n), 5500, 11000) * np.exp(-t / 0.014) * accent


def kick(depth=1.0):
    n = int(0.28 * SR)
    t = _t(n)
    f = 48 + 90 * np.exp(-t / 0.03)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.11) * depth


def rim():
    n = int(0.05 * SR)
    t = _t(n)
    return (_bp(_rng.standard_normal(n), 1500, 3200) * 0.7 + np.sin(2 * np.pi * 820 * t) * 0.5) * np.exp(-t / 0.012)


def snare(g=1.0):
    n = int(0.16 * SR)
    t = _t(n)
    return (_bp(_rng.standard_normal(n), 1800, 6500) * np.exp(-t / 0.045) + np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.03) * 0.4) * g


def cymbal(dur=1.1):
    n = int(dur * SR)
    t = _t(n)
    return sosfilt(butter(2, 4500, "high", fs=SR, output="sos"), _rng.standard_normal(n)) * np.exp(-t / 0.35)


def riser(dur):
    n = int(dur * SR)
    t = _t(n)
    u = t / dur
    noise = _bp(_rng.standard_normal(n), 900, 7000) * u ** 2.2
    f = 300 + 1500 * u ** 2
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * u ** 2.5 * 0.35
    return noise + tone


def _put(buf, sig, at, gain=1.0, pan=0.5):
    i = int(round(at * SR))
    if i < 0 or i >= buf.shape[1]:
        return
    sig = sig[:buf.shape[1] - i] * gain
    buf[0, i:i + len(sig)] += sig * (1 - pan) * 1.4
    buf[1, i:i + len(sig)] += sig * pan * 1.4


CHORDS = {"i": (0, 3, 7), "V": (7, 11, 14)}
BARS = {1: "i", 2: "V", 3: "i"}


def round_music(buf, b, round_idx, cs=0.6):
    """Escribe en `buf` la frase de la ronda. b = inicio de la ronda; el primer tic cae en b+cs."""
    k = KEYS[round_idx % len(KEYS)]
    t0 = b + cs - 1.0                                   # compas 0 empieza 1 s antes del primer tic
    tb = lambda beats: t0 + beats * BEAT                # noqa: E731
    root = 38 + k                                       # Re2 + tonalidad
    # anacrusa (tic + medio compas): solo bajo y un par de notas
    _put(buf, bass(root), tb(2), 0.9)
    _put(buf, bass(root + 7), tb(3), 0.6)
    for i, m in enumerate((62 + k + 7, 62 + k + 12)):
        _put(buf, marimba(m), tb(2) + i * 0.5 * BEAT * 2, 0.35, 0.4 + 0.2 * i)
    for j in (1, 2, 3):
        n0 = 4 * j
        ch = CHORDS[BARS[j]]
        r, third, fifth = ch
        tones = [62 + k + r, 62 + k + third, 62 + k + fifth, 62 + k + r + 12]
        broot = root + (r - 12 if r > 5 else r)
        # bajo
        _put(buf, bass(broot), tb(n0), 1.0)
        _put(buf, bass(broot + (7 if j != 2 else 5)), tb(n0 + 2), 0.7)
        if j != 3:
            _put(buf, bass(broot + 12), tb(n0 + 3.5), 0.45)
        # arpegio de marimba
        if j == 2:                                        # tension: semicorcheas
            for i, idx in enumerate(ARP16):
                _put(buf, marimba(tones[idx], 0.35), tb(n0 + i * 0.25), (0.34 + 0.12 * (i / 16)) * (1 if i % 2 == 0 else 0.7), 0.35 + 0.3 * (i % 2))
        else:
            steps = 8 if j == 1 else 4
            for i in range(steps):
                _put(buf, marimba(tones[ARP8[i]]), tb(n0 + i * 0.5), 0.36 * (1 if i % 2 == 0 else 0.65), 0.38 + 0.24 * (i % 2))
        # campana melodica en el primer tiempo
        mel = {1: tones[2] + 12, 2: tones[1] + 12, 3: tones[0] + 12}[j]
        _put(buf, bell(mel, 2.0 if j == 3 else 1.2), tb(n0), 0.22 if j != 3 else 0.34, 0.6)
        # percusion
        for i in range(8 if j != 2 else 16):
            step = 0.5 if j != 2 else 0.25
            acc = (1.0 if i % 2 == 0 else 0.5) * (0.7 if j == 1 else 1.0) * (0.6 + 0.6 * i / 16 if j == 2 else 1.0)
            _put(buf, shaker(acc), tb(n0 + i * step), 0.16, 0.6)
        for beat in (1, 3):
            _put(buf, rim(), tb(n0 + beat), 0.20)
        if j >= 2:
            for beat in (0, 2):
                _put(buf, kick(), tb(n0 + beat), 0.42)
        else:
            _put(buf, kick(), tb(n0), 0.28)
    # subida hacia el sello (compas 2) y redoble en el ultimo tiempo
    _put(buf, riser(2.0), tb(8), 0.34)
    for i in range(4):
        _put(buf, snare(0.5 + 0.25 * i), tb(11 + i * 0.25), 0.34)
    # sello: acorde de resolucion lleno
    n0 = 12
    for m, g in ((62 + k, 0.5), (62 + k + 3, 0.42), (62 + k + 7, 0.42), (62 + k + 12, 0.46), (62 + k + 19, 0.34)):
        _put(buf, marimba(m, 0.9), tb(n0), g, 0.5)
    _put(buf, bell(74 + k, 2.4), tb(n0), 0.3, 0.5)
    _put(buf, bass(root - 12, 1.0), tb(n0), 0.9)
    _put(buf, cymbal(), tb(n0), 0.22)


def intro_music(buf, b):
    k = 0
    for i, m in enumerate((62, 65, 69, 74)):
        _put(buf, bell(m, 1.6), b + 0.15 + 0.22 * i, 0.30, 0.35 + 0.1 * i)
    _put(buf, bass(38, 1.4), b + 1.15, 0.9)
    for m in (50, 57, 62, 65, 69):
        _put(buf, marimba(m, 1.0), b + 1.15, 0.3, 0.5)
    _put(buf, cymbal(), b + 1.15, 0.2)
    _put(buf, kick(), b + 1.15, 0.5)


def outro_music(buf, b):
    for i, m in enumerate((74, 77, 79, 81, 84)):                  # pentatonica menor ascendente, una nota por circulo
        _put(buf, bell(m, 1.4), b + 0.5 + 0.22 * i + 0.30, 0.34, 0.3 + 0.1 * i)
        _put(buf, marimba(m - 12, 0.7), b + 0.5 + 0.22 * i + 0.30, 0.30, 0.5)
    for m in (50, 57, 62, 65, 69, 74):
        _put(buf, marimba(m, 1.6), b + 1.9, 0.22, 0.5)
    _put(buf, bell(86, 2.4), b + 1.9, 0.26, 0.55)
    _put(buf, bass(38, 1.6), b + 1.9, 0.6)
