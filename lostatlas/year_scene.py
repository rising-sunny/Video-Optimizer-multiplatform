"""Plantilla "Adivina el ano": odometro mecanico de cuatro tambores sobre un fondo guilloche de billete antiguo.

Mecanica: los tambores giran con desenfoque; cada pista tipeada "traba" un digito (milenio, siglo, decada)
y el ultimo (unidades) cae exactamente con el sello. B.C. / A.D. se marca en rojo al revelar.
"""
import math

import cv2
import numpy as np

from . import style as S
from .scenes import CLUE_T, CPS, PH, PW, PX0, PY0, REV, RoundScene
from .style import FPS, INK, RED, SERIF_B, SERIF_I, ink, put_text

N = 11                                   # celdas por tambor: 0-9 + en blanco
DW, DH, GAP = 150, 230, 20
DX0 = (PW - (4 * DW + 3 * GAP)) // 2     # x local de la ventana 0
DY0 = 170                                # y local (arriba) de las ventanas
SPEEDS = (9.0, 11.0, 13.0, 15.0)         # celdas por segundo mientras giran
APPROACH = 0.45                          # frenada antes de trabarse
PLATES = {"BC": (22, 118), "AD": (822, 918)}
BLANK = 10


def _strip():
    """Cinta vertical de digitos (celdas de DH px); sobran filas para envolver."""
    strip = np.zeros(((N + 2) * DH, DW), np.uint8)
    for i in range(N + 2):
        c = i % N
        if c == BLANK:
            continue
        m = S.text_mask(str(c), SERIF_B, 196)
        ys, xs = np.where(m > 8)
        m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]            # caja real del glifo
        h, w = m.shape
        y0 = i * DH + (DH - h) // 2
        x0 = (DW - w) // 2
        strip[y0:y0 + h, x0:x0 + w] = np.maximum(strip[y0:y0 + h, x0:x0 + w], m)
    return strip


def _window_frame(seed):
    """Marco de la ventana + sombreado de cilindro por rayado (mas denso hacia los bordes)."""
    pad = 10
    m = np.zeros((DH + 2 * pad, DW + 2 * pad), np.uint8)
    for inset, t in ((pad, 3), (pad + 8, 1)):
        rect = np.array([[inset, inset], [inset + DW - 2 * (inset - pad), inset], [inset + DW - 2 * (inset - pad), inset + DH - 2 * (inset - pad)],
                         [inset, inset + DH - 2 * (inset - pad)], [inset, inset]], float)
        S.draw_chunks(m, S.strokes([rect], t, seed + inset, amp=0.8, chunk=8))
    for k in range(15):
        d = int(64 * (k / 15) ** 1.7)
        v = int(255 * (0.95 - 0.5 * k / 15))
        for y in (pad + 10 + d, pad + DH - 10 - d):
            cv2.line(m, (pad + 10, y), (pad + DW - 10, y), v, 1, cv2.LINE_AA)
    return m


def _guilloche(cx, cy):
    m = np.zeros((PH, PW), np.uint8)
    th = np.linspace(0, 2 * np.pi, 900)
    for j in range(30):
        phi = 2 * np.pi * j / 30
        r = 262 + 74 * np.sin(8 * th + phi)
        pts = np.stack([cx + r * np.cos(th), cy + r * np.sin(th)], 1)
        cv2.polylines(m, [np.round(pts * 8).astype(np.int32).reshape(-1, 1, 2)], True, 255, 1, cv2.LINE_AA, 3)
    for rr in (330, 322):
        cv2.circle(m, (int(cx), int(cy)), rr, 255, 1, cv2.LINE_AA)
    return m


def _plate(label, x0, x1, cy=DY0 + DH // 2, seed=0):
    m = np.zeros((PH, PW), np.uint8)
    rect = np.array([[x0, cy - 42], [x1, cy - 42], [x1, cy + 42], [x0, cy + 42], [x0, cy - 42]], float)
    S.draw_chunks(m, S.strokes([rect], 2, seed, amp=0.8, chunk=8))
    return m


class YearRoundScene(RoundScene):
    def __init__(self, q, idx, total, world50=None, world110=None):
        self.q, self.idx, self.total = q, idx, total
        y = q["year"]
        self.bc = y < 0
        yy = abs(y)
        self.digits = [BLANK if (i == 0 and yy < 1000) or (i == 1 and yy < 100) or (i == 2 and yy < 10) else int(f"{yy:04d}"[i]) for i in range(4)]
        self.caption = f"Fig. {idx + 1}.  Dated by its contemporaries"
        self.answer_label = f"{yy} B.C." if self.bc else str(yy)
        # --- tiempos en que se traba cada tambor
        end = lambda k: CLUE_T[k] + len(q["clues"][k]) / CPS                       # noqa: E731
        t0 = end(1) + 0.30
        t1 = max(end(2) + 0.30, t0 + 0.55)
        t2 = min(max(REV - 0.5, t1 + 0.35), REV - 0.15)
        self.locks = [t0, t1, t2, REV]
        rng = np.random.default_rng(idx + 5)
        self.phase = rng.uniform(0, N, 4)
        # --- capas estaticas
        strip = self.strip = _strip()
        self.frame_mask = _window_frame(idx)
        ctx = np.zeros((PH, PW), np.float32)
        g = _guilloche(PW / 2, PH / 2).astype(np.float32) / 255 * 0.34
        for d in range(4):                                             # las ventanas son opacas
            xw = DX0 + d * (DW + GAP)
            g[DY0:DY0 + DH, xw:xw + DW] = 0
        for x0p, x1p in PLATES.values():
            g[DY0 + DH // 2 - 42:DY0 + DH // 2 + 42, x0p:x1p] = 0
        ctx = np.maximum(ctx, g)
        for d in range(4):
            x = DX0 + d * (DW + GAP) - 10
            fm = self.frame_mask.astype(np.float32) / 255
            ctx[DY0 - 10:DY0 - 10 + fm.shape[0], x:x + fm.shape[1]] = np.maximum(ctx[DY0 - 10:DY0 - 10 + fm.shape[0], x:x + fm.shape[1]], fm)
        title = S.text_mask("In which year?", SERIF_I, 50).astype(np.float32) / 255 * 0.92
        y0 = 78 - title.shape[0] // 2
        x0 = (PW - title.shape[1]) // 2
        ctx[y0:y0 + title.shape[0], x0:x0 + title.shape[1]] = np.maximum(ctx[y0:y0 + title.shape[0], x0:x0 + title.shape[1]], title)
        rule = np.zeros((PH, PW), np.uint8)
        cv2.line(rule, (250, 128), (PW // 2 - 14, 128), 255, 1, cv2.LINE_AA)
        cv2.line(rule, (PW // 2 + 14, 128), (PW - 250, 128), 255, 1, cv2.LINE_AA)
        cv2.fillPoly(rule, [np.array([[PW // 2, 121], [PW // 2 + 8, 128], [PW // 2, 135], [PW // 2 - 8, 128]], np.int32)], 255, cv2.LINE_AA)
        ctx = np.maximum(ctx, rule.astype(np.float32) / 255 * 0.8)
        self.plate_masks = {}
        for key, (x0p, x1p) in PLATES.items():
            pm = _plate(key, x0p, x1p, seed=77 + (key == "AD"))
            ctx = np.maximum(ctx, pm.astype(np.float32) / 255 * 0.85)
            lab = S.text_mask("B.C." if key == "BC" else "A.D.", SERIF_B, 34)
            full = np.zeros((PH, PW), np.uint8)
            cy = DY0 + DH // 2
            lx, ly = (x0p + x1p) // 2 - lab.shape[1] // 2, cy - lab.shape[0] // 2
            full[ly:ly + lab.shape[0], lx:lx + lab.shape[1]] = lab
            self.plate_masks[key] = full
            ctx = np.maximum(ctx, full.astype(np.float32) / 255 * 0.42)
        self.ctx = ctx
        self._common_init()

    # ------------------------------------------------------------------ cinematica de los tambores
    def pos(self, d, t):
        sp, tl, target, ph = SPEEDS[d], self.locks[d], self.digits[d], self.phase[d]
        ta = tl - APPROACH
        if t < ta:
            return ph + sp * t
        p0 = ph + sp * ta
        P = p0 + 2.0
        P += (target - P) % N
        if t >= tl:
            return P + 0.045 * math.sin(28 * (t - tl)) * math.exp(-10 * (t - tl))
        return p0 + (P - p0) * S.ease_out((t - ta) / APPROACH)

    def cell_crossings(self, d, t_from=0.3):
        """Instantes en que el tambor cruza una celda (para sincronizar el 'ratchet' del audio)."""
        ts = np.arange(t_from, self.locks[d], 1 / 400)
        p = np.array([self.pos(d, t) for t in ts])
        k = np.floor(p)
        idx = np.where(np.diff(k) > 0)[0]
        return [float(ts[i + 1]) for i in idx]

    # ------------------------------------------------------------------ cuadro
    def _panel(self, img, t, v):
        ink(img, self.ctx, PX0, PY0, INK, S.ease_out(t / 0.5))
        for d in range(4):
            p = self.pos(d, t)
            speed = abs(self.pos(d, t + 0.01) - self.pos(d, t - 0.01)) / 0.02
            y0 = int((p % N) * DH)
            win = self.strip[y0:y0 + DH]
            blur = int(min(150, speed * DH / FPS * 0.9))
            if blur > 2:
                win = cv2.blur(win, (1, blur))
            locked = t >= self.locks[d]
            ink(img, win, PX0 + DX0 + d * (DW + GAP), PY0 + DY0, INK, 1.0 if locked else 0.62)
        if t >= REV:
            k = S.ease_out((t - REV) / 0.25)
            ink(img, self.plate_masks["BC" if self.bc else "AD"], PX0, PY0, RED, k)
            kt = S.ease_out((t - REV - 0.35) / 0.35)
            if kt > 0:
                size = S.fit_size(self.q["title"], SERIF_I, 840, 54)
                S.rule(img, PX0 + 230, PY0 + 458, PX0 + PW - 230, PY0 + 458, 1, 31, kt * 0.8)
                put_text(img, self.q["title"], SERIF_I, size, PX0 + PW / 2, PY0 + 505, INK, kt)

    def _after_reveal(self, img, s):
        pass
