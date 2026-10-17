"""Pista ad hoc del Short de Hiroo Onoda (sintetizada, sin derechos). Mismo arco y grilla que el del Titanic:
koto suelto sobre un dron, pulso que se acelera, taikos, silencio en el quiebre y una melodia lenta en escala 'in' (miyako-bushi)."""
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt, fftconvolve
SR, T = 44100, 44.0
OPEN, RISE, CLIMAX, B0, B1 = 5.3, 25.5, 33.53, 33.53, 35.17
N = int(SR * T); rng = np.random.default_rng(1974)
L, R = np.zeros(N), np.zeros(N)
hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)

def put(sig, t, pan=0.0, g=1.0):
    i = int(t * SR); j = min(N, i + len(sig))
    if i >= N or j <= i: return
    L[i:j] += sig[:j - i] * g * (1 - pan) / 2 * 2 ** 0.5; R[i:j] += sig[:j - i] * g * (1 + pan) / 2 * 2 ** 0.5

def env(n, a, r):
    e = np.ones(n); a, r = int(a * SR), int(r * SR)
    if a: e[:a] = np.linspace(0, 1, a)
    if r: e[-r:] *= np.linspace(1, 0, r)
    return e

def piano(m, dur, vel=0.5):
    n = int((dur + 1.5) * SR); t = np.arange(n) / SR; f = hz(m)
    s = sum(a * np.sin(2 * np.pi * f * k * t * (1 + 0.0004 * k * k)) * np.exp(-t * (1.2 + 0.9 * k)) for k, a in enumerate((1, .45, .25, .12, .06), 1))
    return vel * s * env(n, 0.004, 0.3)

def pad(notes, dur, vel=0.08, cut=1400):
    n = int(dur * SR); t = np.arange(n) / SR; s = np.zeros(n)
    for m in notes:
        for d in (-0.07, 0.0, 0.07):
            ph = (hz(m) * (1 + d / 100 * 12 / 12 * 0.06)) * t
            s += 2 * (ph % 1) - 1
    s = sosfilt(butter(2, cut, "lp", fs=SR, output="sos"), s) / (3 * len(notes))
    return vel * s * env(n, min(1.0, dur / 3), min(1.2, dur / 3))

def koto(m, dur, vel=0.5):
    """Cuerda pulsada (Karplus-Strong), un periodo por bloque."""
    n = int((dur + 1.2) * SR); p = int(SR / hz(m)); y = np.zeros(n)
    y[:p] = rng.uniform(-1, 1, p)
    for i in range(p, n, p):
        prev = y[i - p:i]; k = min(p, n - i)
        y[i:i + k] = 0.497 * (prev[:k] + np.roll(prev, 1)[:k])
    return vel * y * env(n, 0.002, 0.4)

def flute(m, dur, vel=0.12):
    """Shakuhachi aproximado: seno con vibrato que crece y soplo filtrado."""
    n = int(dur * SR); t = np.arange(n) / SR
    vib = 1 + 0.006 * np.sin(2 * np.pi * 5.2 * t) * np.minimum(t / 0.6, 1)
    tone = np.sin(2 * np.pi * np.cumsum(hz(m) * vib) / SR) + 0.15 * np.sin(4 * np.pi * np.cumsum(hz(m) * vib) / SR)
    air = sosfilt(butter(2, [hz(m) * 0.8, hz(m) * 3], "band", fs=SR, output="sos"), rng.standard_normal(n))
    return vel * (tone + 0.35 * air / np.abs(air).max()) * env(n, 0.12, min(0.5, dur / 2))

def kick(vel=0.6):
    n = int(0.45 * SR); t = np.arange(n) / SR
    return vel * np.sin(2 * np.pi * (45 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 7)

def taiko(vel=0.8):
    n = int(1.0 * SR); t = np.arange(n) / SR
    body = np.sin(2 * np.pi * (60 + 50 * np.exp(-t * 18)) * t) * np.exp(-t * 4)
    hit = sosfilt(butter(2, [200, 1500], "band", fs=SR, output="sos"), rng.standard_normal(n)) * np.exp(-t * 25)
    return vel * (body + 0.5 * hit)

# 1. Dron grave en Re, viento y koto suelto (todo el tramo previo al quiebre)
t = np.arange(int(B0 * SR)) / SR
drone = (np.sin(2 * np.pi * hz(38) * t) + 0.5 * np.sin(2 * np.pi * hz(45) * t)) * (0.5 + 0.5 * np.minimum(t / 4, 1))
wind = sosfilt(butter(2, [300, 1800], "band", fs=SR, output="sos"), rng.standard_normal(len(t)))
wind *= 0.5 + 0.5 * np.sin(2 * np.pi * 0.13 * t) ** 2
put(0.10 * drone + 0.025 * wind / np.abs(wind).max(), 0)
for k, (tt, m) in enumerate(((0.6, 74), (1.4, 75), (2.6, 69), (3.3, 70), (4.4, 62))):
    put(koto(m, 1.2, 0.35), tt, pan=(-0.5, 0.5)[k % 2])
for k, tt in enumerate(np.arange(OPEN + 0.5, RISE, 2.4)):
    put(koto((62, 63, 67, 69, 70)[k % 5] + 12, 1.0, 0.16), tt, pan=(-0.4, 0.4)[k % 2])
# 2. Subida: acordes de cuerdas (Rem, Sib, Fa, Do) y un pulso que se acelera de 66 a 112 bpm
chords = ((50, 53, 57), (46, 50, 53), (48, 53, 57), (48, 52, 55))
seg = (RISE - OPEN) / 8
for i in range(8):
    put(pad([n + 12 * (i >= 4) for n in chords[i % 4]], seg + 0.4, vel=0.06 + 0.012 * i, cut=900 + 140 * i), OPEN + i * seg)
tt = OPEN
while tt < CLIMAX - 0.2:
    p = (tt - OPEN) / (CLIMAX - OPEN); bpm = 66 + 46 * p
    put(kick(0.35 + 0.35 * p), tt); put(kick(0.2 + 0.2 * p), tt + 60 / bpm * 0.35)
    tt += 60 / bpm
# 3. Climax: tambores y cuerdas en tremolo que suben hasta el corte
tt, k = RISE, 0
while tt < CLIMAX - 0.1:
    put(taiko(0.5 + 0.4 * (tt - RISE) / (CLIMAX - RISE)), tt, pan=(-0.3, 0.3)[k % 2]); tt += 0.43 - 0.2 * (tt - RISE) / (CLIMAX - RISE); k += 1
n = int((CLIMAX - RISE) * SR); t = np.arange(n) / SR
trem = pad((62, 65, 69, 74), CLIMAX - RISE, vel=0.12, cut=2600) * (0.6 + 0.4 * np.sin(2 * np.pi * 9 * t)) * np.linspace(0.6, 1.4, n)
put(trem, RISE)
# 4. Quiebre: silencio total
for ch in (L, R): ch[int(B0 * SR):int(B1 * SR)] = 0.0
# 5. Cierre: melodia lenta en escala in (Re, Mib, Sol, La, Sib) en flauta y koto, sobre cuerdas suaves
beat = 60 / 72; tt = B1 + 0.15
melody = ((74, 2), (75, 1), (74, 1), (70, 2), (69, 1.5), (67, 0.5), (69, 2.5))
t0 = tt
for m, d in melody:
    put(flute(m, d * beat + 0.15, 0.16), tt, pan=0.15); put(koto(m - 12, d * beat, 0.22), tt, pan=-0.2); tt += d * beat
tt = t0
for notes, d in (((50, 57, 62), 4), ((46, 53, 58), 3), ((43, 50, 55), 3.5)):
    put(pad(notes, d * beat + 0.6, vel=0.07, cut=1000), tt); tt += d * beat
# reverb corta, normalizado, fundido final
ir = np.exp(-np.arange(int(1.8 * SR)) / SR * 3.2) * rng.standard_normal(int(1.8 * SR)) * 0.03
mix = np.stack([L + fftconvolve(L, ir)[:N], R + fftconvolve(R, ir)[:N]], 1)
for ch in (0, 1): mix[int(B0 * SR):int(B1 * SR), ch] = 0.0
tt_ = np.arange(N) / SR   # apertura y subida al nivel del cierre (+8 dB), que el climax no las tape
mix *= np.interp(tt_, [0, RISE - 1.5, RISE + 0.5, T], [2.5, 2.5, 1.0, 1.0])[:, None]
mix *= np.concatenate([np.ones(N - int(1.2 * SR)), np.linspace(1, 0, int(1.2 * SR))])[:, None]
mix = 0.89 * mix / np.abs(mix).max()
wavfile.write("musica_onoda.wav", SR, mix.astype(np.float32)); print("ok", mix.shape)
