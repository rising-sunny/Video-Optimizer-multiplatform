"""Escenas: intro, ronda (mapa + pistas + reloj + sello) y cierre. Todo procedural, 1080x1920."""
import math
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw

from . import geo
from . import style as S
from .style import W, H, INK, RED, SERIF, SERIF_B, SERIF_I, MONO, MONO_B, ink, put_text

# ---- layout (zona segura de Shorts: nada importante bajo y=1540) -----------------------------
OY = 60                            # bajada global: deja respirar el borde superior de la UI de Shorts
PX0, PY0, PW, PH = 70, 540 + OY, 940, 570
DIAL_C, DIAL_R = (540, 372 + OY), 132
ROW_Y = (1245 + OY, 1348 + OY, 1451 + OY)
ROMAN = ("I.", "II.", "III.")
CLUE_SIZE = 38

# ---- tiempos de una ronda (segundos) ---------------------------------------------------------
CS, CD = 0.6, 5.0                  # inicio y duracion de la cuenta regresiva
REV = CS + CD                      # sello
ROUND_DUR = CS + 7.0               # 3,5 compases a 120 BPM: la frase musical cierra justo al final
TRANSITION = 0.45                  # la hoja anterior se desliza y deja ver la nueva
CLUE_T = (0.6, 2.1, 3.6)
CPS = 30                           # letras por segundo de la maquina de escribir


def _poly(img, ring, v=255):
    cv2.fillPoly(img, [np.round(ring).astype(np.int32)], v)


@lru_cache(maxsize=None)
def _hatch(variant):
    pat = np.zeros((PH, PW), np.uint8)
    for k in range(-PH, PW, 12):
        cv2.line(pat, (k, PH), (k + PH, 0), 255, 2, cv2.LINE_AA)
    pat = np.roll(pat, variant * 4, axis=1)
    rng = np.random.default_rng(40 + variant)
    gx, gy = np.meshgrid(np.arange(PW, dtype=np.float32), np.arange(PH, dtype=np.float32))
    dx = 0.9 * S.smooth_noise(rng, PH, PW, 40)
    dy = 0.9 * S.smooth_noise(rng, PH, PW, 40)
    return cv2.remap(pat, gx + dx, gy + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def make_stamp(top, name, max_w=760, size=112, angle=-4.5, seed=5):
    """Sello de goma: doble marco, texto, tinta gastada. Devuelve mascara uint8 ya rotada."""
    size = S.fit_size(name, SERIF_B, max_w, size)
    f, ft = S.font(SERIF_B, size), S.font(SERIF_B, max(22, size // 4))
    tw = f.getlength(name)
    w, h = int(tw + 90), int(size * 1.15 + ft.size * 1.6 + 50)
    m = 50
    img = Image.new("L", (w + 2 * m, h + 2 * m), 0)
    d = ImageDraw.Draw(img)
    d.rectangle((m, m, m + w, m + h), outline=255, width=9)
    d.rectangle((m + 16, m + 16, m + w - 16, m + h - 16), outline=255, width=3)
    d.text((m + w / 2, m + 30 + ft.size * 0.8), "  ".join(top), font=ft, fill=255, anchor="mm")
    d.text((m + w / 2, m + h * 0.62), name, font=f, fill=255, anchor="mm")
    a = np.asarray(img).astype(np.float32) / 255
    rng = np.random.default_rng(seed)
    n1 = S.smooth_noise(rng, a.shape[0], a.shape[1], 5)
    n2 = S.smooth_noise(rng, a.shape[0], a.shape[1], 2)
    a *= np.clip(0.88 + 0.12 * n1, 0.6, 1)
    a[(n2 > 1.15) | (n1 > 1.5)] *= 0.12            # tinta que no agarro
    a = np.maximum(a, cv2.GaussianBlur(a, (0, 0), 1.3) * 0.9)
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    return np.asarray(im.rotate(angle, resample=Image.BICUBIC, expand=True))


def _runs(px, vis):
    out, cur = [], []
    for p, v in zip(px, vis):
        if v:
            cur.append(p)
        else:
            if len(cur) > 1:
                out.append(np.array(cur))
            cur = []
    if len(cur) > 1:
        out.append(np.array(cur))
    return out


def make_globe(world110, world50, country, polys, lon0, lat0):
    """Globo ortografico con el pais marcado. Devuelve (tinta uint8, rojo uint8)."""
    r = 92
    size = 2 * r + 34
    c = size / 2
    ink_m = np.zeros((size, size), np.uint8)
    red_m = np.zeros((size, size), np.uint8)

    def to_px(lon, lat):
        x, y, vis = geo.ortho(lon, lat, lon0, lat0)
        return np.stack([c + r * x, c - r * y], 1), vis

    def draw_runs(mask, lon, lat, t, val=255):
        px, vis = to_px(lon, lat)
        for run in _runs(px, vis):
            cv2.polylines(mask, [np.round(run * 8).astype(np.int32).reshape(-1, 1, 2)], False, val, t, cv2.LINE_AA, 3)

    cv2.circle(ink_m, (int(c), int(c)), r, 255, 2, cv2.LINE_AA)
    ll = np.linspace(-180, 180, 181)
    for la in (-60, -30, 0, 30, 60):
        draw_runs(ink_m, ll, np.full_like(ll, la), 1, 90)
    la_ = np.linspace(-90, 90, 91)
    for lo in range(-180, 180, 30):
        draw_runs(ink_m, np.full_like(la_, lo), la_, 1, 90)
    for name, plist in world110.items():
        if name == country:
            continue
        for p in plist:
            draw_runs(ink_m, p[0][:, 0], p[0][:, 1], 1, 230)
    for p in polys:
        px, vis = to_px(p[0][:, 0], p[0][:, 1])
        if vis.all():
            _poly(red_m, px * 1.0)
        draw_runs(red_m, p[0][:, 0], p[0][:, 1], 2)
    px, _ = to_px(np.array([lon0]), np.array([lat0]))
    cv2.circle(red_m, (int(px[0, 0]), int(px[0, 1])), 15, 255, 2, cv2.LINE_AA)
    return ink_m, red_m


class RoundScene:
    dur = ROUND_DUR

    def __init__(self, q, idx, total, world50, world110):
        self.q, self.idx, self.total = q, idx, total
        country = q["country"]
        polys = geo.main_polys(world50[country])
        v = self.view = geo.View(polys, PW, PH, center=q.get("center"))
        tgt_rings = [v.px(r) for p in polys for r in p]
        tgt_outer = [v.px(p[0]) for p in polys]
        tgt_holes = [v.px(r) for p in polys for r in p[1:]]
        near_rings, near_outer = [], []
        for name, plist in world50.items():
            if name == country:
                continue
            for p in plist:
                if geo.ang_dist_deg(v.lon0, v.lat0, *geo.bbox_center(p[0])) < 42:
                    near_outer.append(v.px(p[0]))
                    near_rings.extend(v.px(r) for r in p)

        land = np.zeros((PH, PW), np.uint8)
        for r in near_outer + tgt_outer:
            _poly(land, r)
        fill = np.zeros_like(land)
        for r in tgt_outer:
            _poly(fill, r)
        for r in tgt_holes:
            _poly(fill, r, 0)
        self.fill = fill.astype(np.float32) / 255

        # --- contexto estatico: vecinos, lineas de agua, reticula, escala, rosa de los vientos
        nm = np.zeros((PH, PW), np.uint8)
        S.draw_chunks(nm, S.strokes(near_rings, 1, 900 + idx, amp=0.5, chunk=40))
        n_cc, cc, st, _ = cv2.connectedComponentsWithStats((land > 0).astype(np.uint8), connectivity=8)
        big = np.isin(cc, [k for k in range(1, n_cc) if st[k, cv2.CC_STAT_AREA] >= 1800])
        dist = cv2.distanceTransform((~big).astype(np.uint8), cv2.DIST_L2, 5)
        dist += 1.0 * S.smooth_noise(np.random.default_rng(idx + 11), PH, PW, 30)
        water = np.zeros((PH, PW), np.float32)
        for d, a in ((9, .8), (20, .55), (33, .32)):
            water = np.maximum(water, a * np.clip(1 - np.abs(dist - d) / 1.0, 0, 1))
        water *= (land == 0)

        grat = np.zeros((PH, PW), np.uint8)
        lab = np.zeros((PH, PW), np.float32)
        reserve = [(20, PH - 66, 280, PH - 12), (PW - 104, PH - 150, PW - 20, PH - 24)]   # escala y rosa de vientos
        lo0, lo1, la0, la1 = v.lonlat_bounds()
        span = max(lo1 - lo0, la1 - la0)
        step = next((s for s in (1, 2, 5, 10, 15, 20, 30) if span / s <= 6), 30)

        def label(txt, x, y):
            m = S.text_mask(txt, MONO, 20).astype(np.float32) / 255 * 0.75
            x, y = int(x), int(y)
            x0, y0 = max(x, 0), max(y, 0)
            x1, y1 = min(x + m.shape[1], PW), min(y + m.shape[0], PH)
            if any(x0 < rx1 and x1 > rx0 and y0 < ry1 and y1 > ry0 for rx0, ry0, rx1, ry1 in reserve):
                return
            if x1 > x0 and y1 > y0:
                lab[y0:y1, x0:x1] = np.maximum(lab[y0:y1, x0:x1], m[y0 - y:y1 - y, x0 - x:x1 - x])
                reserve.append((x0 - 4, y0 - 2, x1 + 4, y1 + 2))

        def dashed(px):
            for j in range(0, len(px) - 1, 10):
                if (j // 10) % 2 == 0:
                    cv2.polylines(grat, [np.round(px[j:j + 11] * 8).astype(np.int32).reshape(-1, 1, 2)], False, 255, 1, cv2.LINE_AA, 3)

        def inside(px):
            return (px[:, 0] > 16) & (px[:, 0] < PW - 16) & (px[:, 1] > 16) & (px[:, 1] < PH - 16)

        for lat in np.arange(math.ceil(la0 / step) * step, la1, step):
            lons = np.linspace(lo0 - 8, lo1 + 8, 240)
            px = v.px(np.stack([lons, np.full_like(lons, lat)], 1))
            dashed(px)
            ins = inside(px)
            if ins.any():
                k = np.where(ins)[0][np.argmin(px[ins, 0])]
                label(f"{abs(int(lat))}°{'N' if lat >= 0 else 'S'}", px[k, 0] + 6, px[k, 1] - 24)
        for lon in np.arange(math.ceil(lo0 / step) * step, lo1, step):
            lats = np.linspace(la0 - 8, la1 + 8, 240)
            px = v.px(np.stack([np.full_like(lats, lon), lats], 1))
            dashed(px)
            ins = inside(px)
            if ins.any():
                k = np.where(ins)[0][np.argmax(px[ins, 1])]
                label(f"{abs(int(lon))}°{'E' if lon >= 0 else 'W'}", px[k, 0] + 6, px[k, 1] - 26)

        # barra de escala
        km = next((k for k in (2500, 2000, 1000, 500, 250, 200, 100, 50, 25, 10) if k / v.km_per_px <= 230), 10)
        L = int(km / v.km_per_px)
        sb = np.zeros((PH, PW), np.uint8)
        bx, by = 34, PH - 54
        cv2.rectangle(sb, (bx, by), (bx + L, by + 9), 255, 2, cv2.LINE_AA)
        cv2.rectangle(sb, (bx, by), (bx + L // 2, by + 9), 255, -1)
        label(f"{km} km", bx, by + 12)
        reserve.append((bx - 8, by - 8, bx + L + 8, by + 34))
        # rosa de los vientos
        cx, cy = PW - 62, PH - 70
        cv2.line(sb, (cx, cy + 30), (cx, cy - 24), 255, 2, cv2.LINE_AA)
        cv2.fillPoly(sb, [np.array([[cx, cy - 34], [cx - 8, cy - 14], [cx + 8, cy - 14]], np.int32)], 255, cv2.LINE_AA)
        cv2.circle(sb, (cx, cy), 24, 255, 1, cv2.LINE_AA)
        label("N", cx - 6, cy - 66)
        reserve.append((cx - 36, cy - 70, cx + 36, cy + 36))
        for x0, y0, x1, y1 in reserve:
            water[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = 0

        self.ctx = np.maximum.reduce([water, nm.astype(np.float32) / 255 * 0.8, grat.astype(np.float32) / 255 * 0.42,
                                      lab, sb.astype(np.float32) / 255 * 0.9])

        # --- trazo del pais (3 variantes = animacion "hirviendo") y rayado
        self.chunks = [S.strokes(tgt_rings, 3, idx * 10 + k, amp=1.4) for k in range(3)]
        self.outline = [S.draw_chunks(np.zeros((PH, PW), np.uint8), c) for c in self.chunks]
        self.hatch = [(_hatch(k).astype(np.float32) / 255 * self.fill) for k in range(3)]
        self.red = [np.maximum(0.22 * self.fill, 0.92 * h) for h in self.hatch]

        # --- pistas (maquina de escribir: tinta irregular)
        self.caption = f"Fig. {idx + 1}.  Outline, Lambert equal-area projection"
        self.answer_label = country.upper()
        self._common_init()
        self.globe = make_globe(world110, world50, country, polys, v.lon0, v.lat0)

    def _common_init(self):
        self.clues = [self._clue_mask(t, 70 + 7 * k + self.idx) for k, t in enumerate(self.q["clues"])]
        self.bg = self._static()
        self.stamp = make_stamp(("IDENTIFIED",), self.answer_label, seed=self.idx)
        self._stamp_cache = {}
        self.dials = [self._dial_face(k) for k in range(3)]

    # ------------------------------------------------------------------ piezas estaticas
    @staticmethod
    def _clue_mask(text, seed):
        f = S.font(MONO, CLUE_SIZE)
        adv = f.getlength("M")
        asc, desc = f.getmetrics()
        w, h = int(adv * len(text)) + 44, asc + desc + 16
        img = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(img)
        rng = np.random.default_rng(seed)
        for i, ch in enumerate(text):
            if ch != " ":
                d.text((20 + i * adv, 6 + int(rng.integers(-1, 2))), ch, font=f, fill=int(rng.uniform(190, 255)))
        return np.asarray(img), adv

    def _static(self):
        img = S.paper().copy()
        put_text(img, "THE LOST ATLAS", SERIF_B, 30, PX0 - 8, 148 + OY, tracking=7, align="l")
        put_text(img, f"No. {self.idx + 1} of {self.total}", SERIF_I, 34, PX0 + PW + 8, 148 + OY, align="r")
        S.rule(img, PX0, 196 + OY, PX0 + PW, 196 + OY, 3, 1)
        S.rule(img, PX0, 205 + OY, PX0 + PW, 205 + OY, 1, 2)
        # marco del mapa: doble linea con banda graduada
        m = np.zeros((PH + 60, PW + 60), np.uint8)
        o = 30
        cv2.rectangle(m, (o - 12, o - 12), (o + PW + 12, o + PH + 12), 255, 3, cv2.LINE_AA)
        cv2.rectangle(m, (o, o), (o + PW, o + PH), 255, 1, cv2.LINE_AA)
        for x in range(o, o + PW, 40):
            if (x - o) // 40 % 2 == 0:
                m[o - 12:o, x:x + 40] = 255
                m[o + PH:o + PH + 12, x:x + 40] = 255
        for y in range(o, o + PH, 40):
            if (y - o) // 40 % 2 == 0:
                m[y:y + 40, o - 12:o] = 255
                m[y:y + 40, o + PW:o + PW + 12] = 255
        ink(img, m, PX0 - o, PY0 - o)
        put_text(img, self.caption, SERIF_I, 25, PX0, PY0 + PH + 44, opacity=0.75, align="l")
        for k, y in enumerate(ROW_Y):
            S.rule(img, PX0, y, PX0 + PW, y, 1, 10 + k, opacity=0.8)
            put_text(img, ROMAN[k], SERIF_I, 40, PX0 + 4, y - 26, opacity=0.5, align="l")
        return img

    def _dial_face(self, v):
        R = DIAL_R
        size = 2 * (R + 30)
        c = size / 2
        m = np.zeros((size, size), np.uint8)
        th = np.linspace(0, 2 * np.pi, 181)
        for r, t in ((R, 4), (R - 12, 1)):
            ring = np.stack([c + r * np.cos(th), c + r * np.sin(th)], 1)
            S.draw_chunks(m, S.strokes([ring], t, 200 + v * 7 + int(r), amp=1.1, chunk=12))
        for n in range(60):
            a = n * math.radians(6) - math.pi / 2
            big = n % 12 == 0
            p0 = (c + (R - 14) * math.cos(a), c + (R - 14) * math.sin(a))
            p1 = (c + (R - 14 - (15 if big else 6)) * math.cos(a), c + (R - 14 - (15 if big else 6)) * math.sin(a))
            cv2.line(m, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), 255, 3 if big else 1, cv2.LINE_AA)
        for k in range(5):
            a = k * math.radians(72) - math.pi / 2
            t = S.text_mask(str(5 - k), SERIF_I, 30)
            px, py = int(c + (R - 50) * math.cos(a) - t.shape[1] / 2), int(c + (R - 50) * math.sin(a) - t.shape[0] / 2)
            m[py:py + t.shape[0], px:px + t.shape[1]] = np.maximum(m[py:py + t.shape[0], px:px + t.shape[1]], t)
        return m

    # ------------------------------------------------------------------ cuadro
    def _panel(self, img, t, v):
        ctx_k = S.ease_out(t / 0.5)
        ink(img, self.ctx, PX0, PY0, INK, ctx_k)
        revealed = t >= REV
        draw_k = S.ease_out((t - 0.15) / 1.0)
        if draw_k < 1:
            n = int(len(self.chunks[0]) * draw_k)
            ink(img, S.draw_chunks(np.zeros((PH, PW), np.uint8), self.chunks[0], n), PX0, PY0)
        else:
            ink(img, self.outline[v], PX0, PY0)
        if not revealed:
            ink(img, self.hatch[v], PX0, PY0, INK, 0.30 * draw_k)
        else:
            ink(img, self.red[v], PX0, PY0, RED, S.ease_out((t - REV) / 0.25))
            ink(img, self.outline[v], PX0, PY0, RED, 0.55 * S.ease_out((t - REV) / 0.25))

    def _after_reveal(self, img, s):
        if s > 0.35:
            gi, gr = self.globe
            gx, gy = PX0 + PW - 120 - gi.shape[0] // 2, PY0 + 112 - gi.shape[0] // 2 + 8
            k = S.ease_out((s - 0.35) / 0.3)
            ink(img, gi, gx, gy, INK, k)
            ink(img, gr, gx, gy, RED, k)

    def frame(self, t):
        img = self.bg.copy()
        v = int(t * 7.5) % 3                      # el trazo "hierve" ~7 fps
        self._panel(img, t, v)

        # pistas
        for k, ((mask, adv), t0) in enumerate(zip(self.clues, CLUE_T)):
            n = min(len(self.q["clues"][k]), int((t - t0) * CPS))
            if n > 0:
                w = int(20 + n * adv + 8)
                ink(img, mask[:, :w], PX0 + 78, ROW_Y[k] - mask.shape[0] + 14, INK, 0.93)

        # reloj
        s = t - REV
        if s < 0.12:
            self._dial(img, t, 1.0 if s < 0 else 1 - s / 0.12, v)
        if s >= 0:
            self._stamp_on(img, s)
            self._after_reveal(img, s)
            if s < 0.32:                            # golpe: sacudida de camara
                a = 10 * math.exp(-s * 13)
                M = np.float32([[1, 0, a * math.sin(s * 95)], [0, 1, a * math.cos(s * 80)]])
                img = cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
        return img

    def _dial(self, img, t, opacity, v):
        R = DIAL_R
        size = 2 * (R + 30)
        c = size / 2
        e = min(max(t - CS, 0.0), CD + 0.3)
        cnt = int(e)
        frac = e - cnt
        pos = 0.0 if cnt == 0 else (cnt - 1 + (1 - math.exp(-frac * 28) * math.cos(frac * 46))) / 5
        th = 2 * math.pi * min(pos, 1.0)
        ox, oy = DIAL_C[0] - size // 2, DIAL_C[1] - size // 2
        ink(img, self.dials[v], ox, oy, INK, opacity)
        wedge = np.zeros((size, size), np.uint8)
        phis = np.linspace(th, 2 * math.pi, 40)
        pts = [(c, c)] + [(c + (R - 14) * math.sin(p), c - (R - 14) * math.cos(p)) for p in phis]
        cv2.fillPoly(wedge, [np.round(np.array(pts)).astype(np.int32)], 255, cv2.LINE_AA)
        ink(img, wedge, ox, oy, RED, 0.2 * opacity)
        hand = np.zeros((size, size), np.uint8)
        p0 = (c + 66 * math.sin(th), c - 66 * math.cos(th))
        p1 = (c + (R - 22) * math.sin(th), c - (R - 22) * math.cos(th))
        cv2.line(hand, (int(p0[0] * 8), int(p0[1] * 8)), (int(p1[0] * 8), int(p1[1] * 8)), 255, 3, cv2.LINE_AA, 3)
        cv2.circle(hand, (int(p1[0]), int(p1[1])), 7, 255, -1, cv2.LINE_AA)
        ink(img, hand, ox, oy, RED, opacity)
        digit = max(0, 5 - cnt)
        put_text(img, str(digit), SERIF_B, 118, DIAL_C[0], DIAL_C[1] + 6, INK, opacity)

    def _stamp_on(self, img, s):
        scale = 1 + 0.55 * max(0.0, 1 - s / 0.10)
        key = round(scale, 2)
        if key not in self._stamp_cache:
            h, w = self.stamp.shape
            self._stamp_cache[key] = cv2.resize(self.stamp, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if key != 1 else self.stamp
        m = self._stamp_cache[key]
        ink(img, m, DIAL_C[0] - m.shape[1] // 2, DIAL_C[1] - m.shape[0] // 2, RED, min(1.0, s / 0.04))


class IntroScene:
    dur = 2.4

    def __init__(self, episode=1, n_rounds=5, task="name the country"):
        self.n = n_rounds
        self.task = task
        th = np.linspace(0, 2 * np.pi, 160)
        c = (540, 710)
        rings = [np.stack([c[0] + 250 * np.cos(th), c[1] + 250 * np.sin(th)], 1),
                 np.stack([c[0] + 238 * np.cos(th), c[1] + 238 * np.sin(th)], 1)]
        for ang, ln, wd in [(0, 250, 22), (90, 250, 22), (180, 250, 22), (270, 250, 22),
                            (45, 165, 14), (135, 165, 14), (225, 165, 14), (315, 165, 14)]:
            a = math.radians(ang - 90)
            u, nrm = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
            ctr = np.array(c, float)
            rings.append(np.array([ctr + u * ln, ctr + nrm * wd, ctr - u * ln * 0.18, ctr - nrm * wd, ctr + u * ln]))
        self.chunks = S.strokes(rings, 3, 77, amp=1.2, chunk=8)
        self.stamp = make_stamp(("EXPEDITION",), f"No. {episode:03d}", max_w=520, size=84, angle=5, seed=3)

    def frame(self, t):
        img = S.paper().copy()
        k = S.ease_out(t / 1.3)
        ink(img, S.draw_chunks(np.zeros((H, W), np.uint8), self.chunks, int(len(self.chunks) * k)), 0, 0)
        o = S.ease_out((t - 0.8) / 0.5)
        put_text(img, "THE", SERIF_I, 56, 540, 1010, INK, o, tracking=18)
        size = S.fit_size("LOST ATLAS", SERIF_B, 900, 150, 4)
        put_text(img, "LOST ATLAS", SERIF_B, size, 540, 1130, INK, o, tracking=4)
        S.rule(img, 190, 1222, 890, 1222, 3, 4, o)
        S.rule(img, 190, 1232, 890, 1232, 1, 5, o)
        put_text(img, f"{self.task} - {self.n} rounds - 5 seconds each", MONO, 31, 540, 1300, INK, o * 0.9)
        if t > 1.15:
            m = self.stamp
            sc = 1 + 0.5 * max(0, 1 - (t - 1.15) / 0.1)
            if sc != 1:
                m = cv2.resize(m, (int(m.shape[1] * sc), int(m.shape[0] * sc)), interpolation=cv2.INTER_AREA)
            ink(img, m, 540 - m.shape[1] // 2, 290 - m.shape[0] // 2, RED, min(1, (t - 1.15) / 0.04))
        return img


class OutroScene:
    dur = 3.6

    def __init__(self):
        self.circles = []
        th = np.linspace(0, 2 * np.pi * 1.04, 70)
        for k in range(5):
            cx = 540 + (k - 2) * 150
            ring = np.stack([cx + 50 * np.cos(th), 960 + 50 * np.sin(th)], 1)
            self.circles.append(S.strokes([ring], 4, 300 + k, amp=1.6, chunk=6))

    def frame(self, t):
        img = S.paper().copy()
        o = S.ease_out(t / 0.5)
        put_text(img, "How many", SERIF_I, 104, 540, 640, INK, o)
        put_text(img, "did you get?", SERIF_I, 104, 540, 760, INK, o)
        mask = np.zeros((H, W), np.uint8)
        for k, ch in enumerate(self.circles):
            kk = S.ease_out((t - 0.5 - 0.22 * k) / 0.35)
            S.draw_chunks(mask, ch, int(len(ch) * kk))
        ink(img, mask, 0, 0)
        put_text(img, "Comment your score.", MONO, 42, 540, 1130, INK, S.ease_out((t - 1.6) / 0.4))
        o2 = S.ease_out((t - 2.1) / 0.5)
        put_text(img, "A new expedition every day", SERIF_I, 44, 540, 1290, INK, o2)
        put_text(img, "THE LOST ATLAS", SERIF_B, 32, 540, 1370, INK, o2, tracking=8)
        return img
