"""Linea de tiempo del largo: plan de segmentos + escenas bajo demanda + transicion de hoja que se desliza."""
import cv2
import numpy as np

from . import long_states as LS
from .long_scenes import CS, FPS, HOLD, LH, LW, TIER_CD, Checkpoint, LongIntro, LongOutro, StateRound, TierCard

TRANSITION = 0.35


def slide(prev, new, k):
    e = k * k * (3 - 2 * k)
    x = int(round(LW * e))
    if x <= 0:
        return prev
    if x >= LW:
        return new
    edge = LW - x
    out = new.copy()
    out[:, :edge] = prev[:, x:]
    wsh = min(90, x)
    f = (1 - 0.36 * np.exp(-np.arange(wsh, dtype=np.float32) / 26))[None, :, None]
    out[:, edge:edge + wsh] = (out[:, edge:edge + wsh].astype(np.float32) * f).astype(np.uint8)
    out[:, max(edge - 3, 0):edge] = (out[:, max(edge - 3, 0):edge] * 0.8).astype(np.uint8)
    return out


def build_plan(data, limit=None, episode=2):
    """Segmentos en orden de juego. `limit` recorta a las primeras N rondas (pruebas)."""
    plan, t, n = [], 0.0, 0

    def add(kind, dur, **kw):
        nonlocal t
        plan.append(dict(kind=kind, start=t, dur=dur, **kw))
        t += dur

    add("intro", LongIntro.dur, episode=episode)
    order = LS.order()
    total = len(order)
    for ti, (num, label, states) in enumerate(LS.TIERS):
        rounds = [o for o in order if o[0] == ti]
        if limit is not None and n >= limit:
            break
        add("tier", TierCard.dur, num=num, label=label, n=len(rounds), cd=TIER_CD[ti], tier=ti)
        for (_i, _num, _label, st) in rounds:
            if limit is not None and n >= limit:
                break
            cd = TIER_CD[ti]
            add("round", CS + cd + HOLD, state=st, idx=n, tier=ti, num=num, label=label, cd=cd, rec=data[st])
            n += 1
        if ti == 2 and (limit is None or n < limit):
            add("checkpoint", Checkpoint.dur, done=n, total=total)
    add("outro", LongOutro.dur)
    return plan, t


class LongTimeline:
    def __init__(self, data, limit=None, episode=2):
        self.plan, self.total = build_plan(data, limit, episode)
        self.n_states = 50
        self.starts = np.array([p["start"] for p in self.plan] + [self.total])
        self._k, self._scene, self._cur_last, self._trans_from = None, None, None, None

    def locate(self, t):
        k = int(np.searchsorted(self.starts, t, side="right") - 1)
        k = min(max(k, 0), len(self.plan) - 1)
        return k, t - self.starts[k]

    def scene(self, k):
        if self._k != k:                                       # solo vive la escena actual (RAM)
            seg = self.plan[k]
            self._scene = None
            kind = seg["kind"]
            if kind == "intro":
                self._scene = LongIntro(seg["episode"], self.n_states)
            elif kind == "tier":
                self._scene = TierCard(seg["num"], seg["label"], seg["n"], seg["cd"])
            elif kind == "round":
                self._scene = StateRound(seg["rec"], seg["idx"], self.n_states, seg["tier"], seg["num"], seg["label"], seg["cd"])
            elif kind == "checkpoint":
                self._scene = Checkpoint(seg["done"], seg["total"])
            else:
                self._scene = LongOutro()
            self._trans_from, self._k = self._cur_last, k
        return self._scene

    def frame(self, t, transitions=True):
        k, tau = self.locate(t)
        img = self.scene(k).frame(tau)
        self._cur_last = img
        if transitions and k > 0 and tau < TRANSITION and self._trans_from is not None:
            img = slide(self._trans_from, img, tau / TRANSITION)
        return img
