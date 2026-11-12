"""Procedural sound, no samples and no licensing: an ambient pad, and a nature bed
(wind, rustling leaves, birdsong, passing bees) with the pad far underneath."""
import numpy as np, wave
from scipy.signal import butter, sosfilt

SR = 44100


def _pad(t, seconds):
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]
    seg = seconds / len(chords)
    out = np.zeros((2, len(t)), np.float32)
    for ci, ch in enumerate(chords):
        env = np.clip(np.minimum((t - ci * seg) / 1.6, (ci * seg + seg + 1.6 - t) / 1.6), 0, 1)
        for f in ch:
            for det, pan in ((0.997, 0.3), (1.003, 0.7)):
                s = np.sin(2 * np.pi * f * det * t) + 0.35 * np.sin(2 * np.pi * f * 2 * det * t)
                s *= env * (0.6 + 0.4 * np.sin(2 * np.pi * 0.11 * t + f))
                out[0] += s * (1 - pan); out[1] += s * pan
    return out / (np.abs(out).max() + 1e-9)


def _bells(t, events, gain=0.30):
    out = np.zeros((2, len(t)), np.float32)
    for at, freqs in events:
        mask = t >= at
        for j, f in enumerate(freqs):
            b = np.sin(2 * np.pi * f * (t - at)) * np.exp(-(t - at) * 1.5) * gain * mask
            out[0] += b * (0.6 - 0.1 * j); out[1] += b * (0.4 + 0.1 * j)
    return out


def _write(out, t, seconds, path, peak):
    out = out / (np.abs(out).max() + 1e-9)
    fade = np.minimum(1, np.minimum(t / 1.0, (seconds - t) / 1.0))
    pcm = (out * fade * peak).T
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((pcm * 32767).astype(np.int16).tobytes())


def make_pad(seconds, path, seed=0, events=()):
    t = np.arange(int(seconds * SR)) / SR
    _write(_pad(t, seconds) + _bells(t, events), t, seconds, path, 0.35)


def _birdsong(t, rng, seconds):
    out = np.zeros((2, len(t)), np.float32)
    at = rng.uniform(0.3, 1.2)
    while at < seconds - 1.0:
        pan = rng.uniform(0.15, 0.85)
        f0, gain = rng.uniform(2600, 4600), rng.uniform(0.25, 1.0)
        pos = at
        for _ in range(rng.integers(2, 7)):                # a call is a few quick rising/falling notes
            d = rng.uniform(0.05, 0.14)
            n = int(d * SR)
            i0 = int(pos * SR)
            if i0 + n >= len(t):
                break
            u = np.linspace(0, 1, n)
            f = f0 * (1 + rng.uniform(-0.3, 0.4) * u + 0.05 * np.sin(2 * np.pi * rng.uniform(6, 14) * u))
            s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * u) ** 2 * gain
            out[0, i0:i0 + n] += s * (1 - pan); out[1, i0:i0 + n] += s * pan
            pos += d + rng.uniform(0.02, 0.09)
        at = pos + rng.uniform(0.5, 2.3)
    # distance: a faint slapback off the field
    d = int(0.13 * SR)
    out[:, d:] += out[:, :-d] * 0.28
    return out


def make_nature(seconds, path, seed=0, events=()):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    gust = 0.55 + 0.30 * np.sin(2 * np.pi * t / 7.3 + 0.4) + 0.15 * np.sin(2 * np.pi * t / 2.9)
    low = butter(2, 420, "low", fs=SR, output="sos")
    high = butter(2, [2200, 7000], "band", fs=SR, output="sos")
    wind = np.stack([sosfilt(low, rng.standard_normal(len(t))) for _ in range(2)]) * gust
    leaves = np.stack([sosfilt(high, rng.standard_normal(len(t))) for _ in range(2)]) * np.clip(gust - 0.35, 0, 1) ** 2
    bee_env = np.exp(-((t - 4.0) / 1.5) ** 2) * 0.8 + np.exp(-((t - 12.4) / 1.2) ** 2)
    f = 196 + 9 * np.sin(2 * np.pi * 3.1 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    bee = (np.sin(ph) + 0.6 * np.sin(2 * ph) + 0.4 * np.sin(3 * ph)) * bee_env
    bee = np.stack([bee * 0.6, bee * 0.4])
    mix = (wind * 1.5 + leaves * 0.16 + bee * 0.022 + _birdsong(t, rng, seconds) * 0.42
           + _pad(t, seconds) * 0.13 + _bells(t, events, gain=0.16))
    _write(mix.astype(np.float32), t, seconds, path, 0.62)


def make_night(seconds, path, seed=0, events=()):
    """Crickets, a creek, a far owl, and one soft note per collective firefly flash."""
    rng = np.random.default_rng(seed + 5)
    t = np.arange(int(seconds * SR)) / SR
    # creek: band noise with a slow bubbling swell
    bands = butter(2, [350, 1900], "band", fs=SR, output="sos")
    swell = 0.75 + 0.25 * np.sin(2 * np.pi * t / 3.7)
    creek = np.stack([sosfilt(bands, rng.standard_normal(len(t))) for _ in range(2)]) * swell
    air = np.stack([sosfilt(butter(2, 300, "low", fs=SR, output="sos"), rng.standard_normal(len(t))) for _ in range(2)])
    # crickets: a chorus of pulsed tones around 4.5 kHz, each with its own chirp rate
    cr = np.zeros((2, len(t)), np.float32)
    for _ in range(9):
        f, rate, ph, pan, g = rng.uniform(3900, 5100), rng.uniform(1.4, 2.6), rng.uniform(0, 1), rng.uniform(0.1, 0.9), rng.uniform(0.3, 1.0)
        chirp = np.mod(t * rate + ph, 1.0)
        gate = np.where(chirp < 0.42, (np.sin(2 * np.pi * chirp * 3 / 0.42 * 2) > -0.2).astype(np.float32), 0.0)
        s = np.sin(2 * np.pi * f * t) * sosfilt(butter(1, 240, "low", fs=SR, output="sos"), gate) * g
        cr[0] += s * (1 - pan); cr[1] += s * pan
    # a distant owl, twice
    owl = np.zeros((2, len(t)), np.float32)
    for at in (3.6, 8.9):
        for k, (off, d) in enumerate(((0, 0.42), (0.55, 0.28), (0.92, 0.65))):
            i0, n = int((at + off) * SR), int(d * SR)
            if i0 + n >= len(t):
                continue
            u = np.linspace(0, 1, n)
            f = 335 * (1 - 0.08 * u) * (1.03 if k == 1 else 1)
            v = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * u) ** 1.5
            owl[0, i0:i0 + n] += v * 0.7; owl[1, i0:i0 + n] += v * 0.3
    d = int(0.21 * SR)
    owl[:, d:] += owl[:, :-d] * 0.3
    mix = (creek * 0.30 + air * 0.20 + cr * 0.075 + owl * 0.16 + _pad(t, seconds) * 0.07 + _bells(t, events, gain=0.34))
    _write(mix.astype(np.float32), t, seconds, path, 0.62)
