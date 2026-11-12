"""Diseno sonoro SINTETIZADO (sin derechos): ambiente, tension y golpes dramaticos que se mezclan bajo la voz.

Cada cue = (t_seg, tipo, duracion_seg, gain_db). Tipos:
  rumble   ruido marron filtrado grave (tension de fondo)       tick     reloj que marca segundos (con aceleracion opcional)
  wind     viento/ambiente de puerto (ruido rosa pasabanda)      riser    subida de tension (ruido filtrado ascendente)
  boom     golpe grave con cola (explosion lejana, 'caida')      hit      golpe seco corto (subraya una cifra)
  heart    latido lento                                          void     silencio forzado: baja TODO el soundscape a 0 durante la duracion
build(cues, total, out) escribe un WAV estereo 44,1 kHz. Mezclar bajo narracion con sidechain (ver compose.build)."""
from __future__ import annotations
import numpy as np, soundfile as sf
from scipy import signal

SR = 44100
rng = np.random.default_rng(7)


def _db(x): return 10 ** (x / 20.0)
def _env(n, a=0.02, r=0.3):
    e = np.ones(n); na, nr = int(a * SR), int(r * SR)
    if na: e[:na] = np.linspace(0, 1, na)
    if nr: e[-nr:] = np.linspace(1, 0, nr)
    return e
def _bp(x, lo, hi, order=4):
    sos = signal.butter(order, [lo, hi], btype='band', fs=SR, output='sos'); return signal.sosfilt(sos, x)
def _lp(x, f, order=4):
    sos = signal.butter(order, f, btype='low', fs=SR, output='sos'); return signal.sosfilt(sos, x)
def _norm(x, peak=0.9): m = np.max(np.abs(x)) or 1; return x / m * peak


def rumble(d):
    n = int(d * SR); b = np.cumsum(rng.standard_normal(n)); b -= np.linspace(b[0], b[-1], n)
    return _norm(_lp(b, 90) * (1 + 0.25 * np.sin(2 * np.pi * 0.17 * np.arange(n) / SR))) * _env(n, 1.5, 2.0)
def wind(d):
    n = int(d * SR); w = _bp(rng.standard_normal(n), 120, 1400); sw = 0.55 + 0.45 * np.sin(2 * np.pi * (0.07 * np.arange(n) / SR) + rng.uniform(0, 6))
    return _norm(w * sw) * _env(n, 2.0, 2.5)
def tick(d, accel=0.0):
    n = int(d * SR); out = np.zeros(n); t = 0.0; period = 1.0
    click = _bp(rng.standard_normal(int(0.03 * SR)), 1800, 5200) * np.exp(-np.linspace(0, 9, int(0.03 * SR)))
    k = 0
    while t < d - 0.05:
        i = int(t * SR); c = click * (1.0 if k % 2 == 0 else 0.7); out[i:i + len(c)] += c[:max(0, n - i)][:len(out[i:i + len(c)])]
        t += max(0.35, period - accel * (t / max(d, 1))); k += 1
    return _norm(out, 0.8)
def riser(d):
    n = int(d * SR); x = rng.standard_normal(n); out = np.zeros(n); seg = 24
    for s in range(seg):
        a, b = s * n // seg, (s + 1) * n // seg; fc = 200 * (40 ** (s / seg))
        out[a:b] = _bp(x[a:b], fc * 0.6, min(fc * 1.6, SR / 2 - 100), 2) * (0.15 + 0.85 * (s / seg) ** 2)
    return _norm(out) * _env(n, 0.3, 0.05)
def boom(d):
    n = int(d * SR); t = np.arange(n) / SR; f = 62 * np.exp(-t * 1.6) + 28
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.5); burst = _lp(rng.standard_normal(n), 400) * np.exp(-t * 3.5)
    tail = _lp(rng.standard_normal(n), 140) * np.exp(-t * 0.9) * 0.35
    return _norm(body + 0.6 * burst + tail)
def hit(d):
    n = int(min(d, 0.9) * SR); t = np.arange(n) / SR
    return _norm(np.sin(2 * np.pi * 78 * t) * np.exp(-t * 9) + 0.4 * _lp(rng.standard_normal(n), 700) * np.exp(-t * 14))
def heart(d):
    n = int(d * SR); out = np.zeros(n); t = 0.0
    thump = lambda f, L: np.sin(2 * np.pi * f * np.arange(int(L * SR)) / SR) * np.exp(-np.linspace(0, 7, int(L * SR)))
    while t < d - 0.4:
        i = int(t * SR); a = thump(52, 0.22); out[i:i + len(a)] += a[:n - i]
        j = i + int(0.28 * SR); b = thump(44, 0.18) * 0.7; out[j:j + len(b)] += b[:max(0, n - j)][:len(out[j:j + len(b)])]
        t += 1.15
    return _norm(out) * _env(n, 1.0, 1.0)

GEN = {'rumble': rumble, 'wind': wind, 'tick': tick, 'riser': riser, 'boom': boom, 'hit': hit, 'heart': heart}


def build(cues, total, out, master_db=-6.0):
    n = int((total + 2) * SR); mix = np.zeros(n); gate = np.ones(n)
    for t, kind, d, gdb in cues:
        i = int(t * SR)
        if kind == 'void':                                  # silencio forzado con rampas de 80 ms
            a, b = i, min(n, i + int(d * SR)); gate[a:b] = 0.0; r = int(0.08 * SR)
            gate[max(0, a - r):a] = np.linspace(1, 0, a - max(0, a - r)); gate[b:min(n, b + r)] = np.linspace(0, 1, min(n, b + r) - b); continue
        x = GEN[kind](d) * _db(gdb); j = min(n, i + len(x)); mix[i:j] += x[:j - i]
    mix = _norm(mix * gate, 1.0) * _db(master_db) if np.max(np.abs(mix)) > 0 else mix
    sf.write(out, np.stack([mix, mix], 1).astype('float32'), SR, subtype='PCM_16')
    return out
