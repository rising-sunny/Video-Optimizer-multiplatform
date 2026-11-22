"""Audio del largo: efectos sincronizados con la linea de tiempo + una pista de Incompetech distinta por nivel (CC BY)."""
import wave

import numpy as np

from . import music, music_lib, sound as snd
from .long_scenes import CLUE_T, CPS, CS
from .long_timeline import TRANSITION

SR = snd.SR
TIER_TRACKS = ["Allada", "Zanzibar", "Spy Glass", "Hard Boiled", "Deadly Roulette"]       # de lo alegre a lo tenso
_put = music._put


def tier_ranges(tl):
    """[(inicio, fin)] de cada nivel (la intro cuenta para el I y el cierre para el V)."""
    starts = [p["start"] for p in tl.plan if p["kind"] == "tier"]
    ends = starts[1:] + [tl.total]
    starts[0] = 0.0
    return list(zip(starts, ends))


def build_audio(tl, path, tracks=TIER_TRACKS):
    total = tl.total
    n = int(total * SR)
    sfx = np.zeros((2, n), np.float32)
    t = np.arange(n) / SR
    sfx += (snd._lp(snd._rng.standard_normal(n), 260) * 0.020 * np.ones((2, 1))).astype(np.float32)
    for k, seg in enumerate(tl.plan):
        b, kind = seg["start"], seg["kind"]
        if k > 0:
            _put(sfx, snd.whoosh(), b - 0.02, 0.5)
            _put(sfx, snd.paper_land(), b + TRANSITION - 0.06, 0.45)
        if kind == "intro":
            _put(sfx, snd.pen(1.6), b, 0.12)
            _put(sfx, snd.stamp_hit(), b + 2.0, 0.8)
        elif kind == "tier":
            _put(sfx, snd.stamp_hit(), b + 0.45, 0.9)
        elif kind == "checkpoint":
            for i in range(3):
                _put(sfx, snd.pencil_tap(500 + 60 * i), b + 0.5 + 0.5 * i, 0.4)
        elif kind == "outro":
            _put(sfx, snd.pen(1.0), b + 0.2, 0.1)
            for i in range(6):
                _put(sfx, snd.pencil_tap(480 + 45 * i), b + 1.0 + 0.7 * i + 0.2, 0.4)
        elif kind == "round":
            cd, rec = seg["cd"], seg["rec"]
            _put(sfx, snd.pen(1.0), b + 0.15 + TRANSITION * 0.4, 0.12)
            for j, text in enumerate(rec["clues"]):
                for i, ch in enumerate(text):
                    _put(sfx, snd.key(ch == " "), b + CLUE_T[j] + i / CPS, 0.5, pan=snd._rng.uniform(0.42, 0.58))
                end = b + CLUE_T[j] + len(text) / CPS
                _put(sfx, snd.carriage(), end + 0.05, 0.4)
                _put(sfx, snd.typewriter_bell(), end + 0.12, 0.22)
            _put(sfx, snd.tick(accent=True), b + CS, 0.55)
            for s in range(1, cd):
                _put(sfx, snd.tick(tock=s % 2 == 1, accent=s >= cd - 2), b + CS + s, 0.62 if s < cd - 2 else 0.85)
            _put(sfx, snd.stamp_hit(), b + CS + cd, 0.95)
            _put(sfx, snd.pencil_tap(620), b + CS + cd + 0.55, 0.35, 0.7)
    # musica: una pista por nivel, con fundidos; se agacha un instante en cada sello
    mus = np.zeros((2, n), np.float32)
    duck = np.ones(n, np.float32)
    for seg in tl.plan:
        if seg["kind"] == "round":
            i0 = int((seg["start"] + CS + seg["cd"] - 0.03) * SR)
            ramp = np.linspace(0.45, 1.0, int(0.6 * SR)) ** 0.7
            duck[i0:i0 + len(ramp)] = np.minimum(duck[i0:i0 + len(ramp)], ramp[: max(0, n - i0)] if i0 < n else ramp[:0])
    duck = np.convolve(duck, np.ones(401) / 401, "same").astype(np.float32)
    attribution = []
    for (s0, s1), track in zip(tier_ranges(tl), tracks):
        mp3, attr, _ = music_lib.fetch(track)
        attribution.append((s0, track, attr))
        dur = s1 - s0 + 1.6                                            # solape para el fundido cruzado
        bed = snd._load_bgm(mp3, 0.0, dur)
        bed = bed / (np.sqrt((bed ** 2).mean()) + 1e-9) * 0.085
        m = bed.shape[1]
        tt = np.arange(m) / SR
        env = np.minimum(np.minimum(tt / 1.2, (dur - tt) / 1.6), 1.0).astype(np.float32)
        i0 = int(s0 * SR)
        seg_ = bed * env
        mus[:, i0:i0 + m] += seg_[:, : max(0, min(m, n - i0))] if i0 < n else 0
    mix = sfx + mus * duck
    mix = mix / (np.abs(mix).max() + 1e-9)
    pcm = (mix * 0.85 * np.minimum(1, np.minimum(t / 0.3, (total - t) / 1.2))).T
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((pcm * 32767).astype(np.int16).tobytes())
    return attribution
