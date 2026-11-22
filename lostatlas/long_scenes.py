"""Escenas del largo horizontal 1920x1080 de The Lost Atlas ("Name All 50 US States by Outline").

Diseno: mapa grande a la izquierda (contorno del estado + vecinos), a la derecha reloj, pistas de maquina de escribir y sello;
al revelar aparece un minimapa de EE. UU. con el estado marcado; abajo, una ruta de 50 marcas muestra el progreso.
Las rondas se construyen bajo demanda (long_timeline.py): 50 escenas a la vez no caben en la RAM de la VPS.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from . import brand, geo
from . import style as S
from .scenes import _poly, make_stamp
from .style import INK, MONO, RED, SERIF, SERIF_B, SERIF_I, ink, put_text

LW, LH, FPS = 1920, 1080, 30
MX, MY, MW, MH = 60, 140, 1120, 800            # panel del mapa
CX0 = 1240                                    # columna derecha
DIAL_C, DIAL_R = (1550, 300), 150
ROWS = (585, 665, 745)
ROMAN = ("I.", "II.", "III.")
CLUE_SIZE = 25
CS, HOLD = 0.6, 2.8                           # inicio de la cuenta regresiva, pausa tras el sello
CLUE_T, CPS = (0.6, 2.4, 4.2), 30
MM = (CX0 + 60, 772, 500, 226)                # minimapa (x, y, w, h)
DATA = Path(__file__).parent / "data"
TIER_CD = (5, 5, 6, 7, 8)                     # segundos de cuenta regresiva por nivel: los dificiles dan mas tiempo


# ------------------------------------------------------------------ datos
@lru_cache(maxsize=1)
def admin1():
    """{(pais, nombre): [poligonos]} de Natural Earth admin-1 (dominio publico)."""
    d = json.loads((DATA / "ne_50m_admin1.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in d["features"]:
        g, p = f["geometry"], f["properties"]
        if not g:
            continue
        coords = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out[(p.get("admin"), p.get("name"))] = [[np.asarray(r, float)[:, :2] for r in poly] for poly in coords]
    return out


MAX_KM = {"Hawaii": 700, "Alaska": 2500}                 # sin atolones del noroeste de Hawai ni cola de las Aleutianas


def us_state(name):
    polys = admin1()[("United States of America", name)]
    if name == "Alaska":                                  # la cola de las Aleutianas cruza el antimeridiano
        polys = [p for p in polys if p[0][:, 0].mean() < 0]
    return geo.main_polys(polys, MAX_KM.get(name, 3000))


@lru_cache(maxsize=None)
def _hatch(variant):
    pat = np.zeros((MH, MW), np.uint8)
    for k in range(-MH, MW, 14):
        cv2.line(pat, (k, MH), (k + MH, 0), 255, 2, cv2.LINE_AA)
    pat = np.roll(pat, variant * 4, axis=1)
    rng = np.random.default_rng(40 + variant)
    gx, gy = np.meshgrid(np.arange(MW, dtype=np.float32), np.arange(MH, dtype=np.float32))
    return cv2.remap(pat, gx + 0.9 * S.smooth_noise(rng, MH, MW, 40), gy + 0.9 * S.smooth_noise(rng, MH, MW, 40), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def clue_mask(text, seed, size=CLUE_SIZE):
    f = S.font(MONO, size)
    adv = f.getlength("M")
    asc, desc = f.getmetrics()
    img = Image.new("L", (int(adv * len(text)) + 40, asc + desc + 14), 0)
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(seed)
    for i, ch in enumerate(text):
        if ch != " ":
            d.text((16 + i * adv, 5 + int(rng.integers(-1, 2))), ch, font=f, fill=int(rng.uniform(190, 255)))
    return np.asarray(img), adv


def dial_face(variant, cd, R=DIAL_R):
    size = 2 * (R + 30)
    c = size / 2
    m = np.zeros((size, size), np.uint8)
    th = np.linspace(0, 2 * np.pi, 181)
    for r, t in ((R, 5), (R - 14, 2)):
        ring = np.stack([c + r * np.cos(th), c + r * np.sin(th)], 1)
        S.draw_chunks(m, S.strokes([ring], t, 200 + variant * 7 + int(r), amp=1.2, chunk=12))
    for n in range(60):
        a = n * math.radians(6) - math.pi / 2
        r0, r1 = R - 16, R - 16 - 7
        cv2.line(m, (int(c + r0 * math.cos(a)), int(c + r0 * math.sin(a))), (int(c + r1 * math.cos(a)), int(c + r1 * math.sin(a))), 255, 1, cv2.LINE_AA)
    for k in range(cd):
        a = k * 2 * math.pi / cd - math.pi / 2
        r0, r1 = R - 16, R - 16 - 18
        cv2.line(m, (int(c + r0 * math.cos(a)), int(c + r0 * math.sin(a))), (int(c + r1 * math.cos(a)), int(c + r1 * math.sin(a))), 255, 3, cv2.LINE_AA)
        t = S.text_mask(str(cd - k), SERIF_I, 34)
        px, py = int(c + (R - 58) * math.cos(a) - t.shape[1] / 2), int(c + (R - 58) * math.sin(a) - t.shape[0] / 2)
        m[py:py + t.shape[0], px:px + t.shape[1]] = np.maximum(m[py:py + t.shape[0], px:px + t.shape[1]], t)
    return m


# ------------------------------------------------------------------ minimapa de EE. UU. (Alaska y Hawaii como recuadros)
class UsMini:
    _inst = None

    @classmethod
    def get(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self, w=MM[2], h=MM[3], hatch_step=5, line=1):
        self.w, self.h, self.hatch_step = w, h, hatch_step
        names = [k[1] for k in admin1() if k[0] == "United States of America" and k[1] != "District of Columbia"]
        proj = {}
        for n in names:
            rings = []
            for p in us_state(n):
                lon, lat = p[0][:, 0], p[0][:, 1]
                x, y = geo.laea(lon, lat, -96, 38)
                rings.append(np.stack([x, y], 1))
            proj[n] = rings
        contig = np.vstack([r for n, rs in proj.items() if n not in ("Alaska", "Hawaii") for r in rs])
        cxmin, cxmax, cymin, cymax = contig[:, 0].min(), contig[:, 0].max(), contig[:, 1].min(), contig[:, 1].max()
        cw, ch = cxmax - cxmin, cymax - cymin

        def inset(name, scale, cx, cy):
            allp = np.vstack(proj[name])
            c0 = np.array([(allp[:, 0].min() + allp[:, 0].max()) / 2, (allp[:, 1].min() + allp[:, 1].max()) / 2])
            proj[name] = [(r - c0) * scale + np.array([cx, cy]) for r in proj[name]]
        inset("Alaska", 0.30, cxmin + 0.11 * cw, cymin + 0.13 * ch)
        inset("Hawaii", 1.0, cxmin + 0.30 * cw, cymin + 0.05 * ch)
        every = np.vstack([r for rs in proj.values() for r in rs])
        xmin, xmax, ymin, ymax = every[:, 0].min(), every[:, 0].max(), every[:, 1].min(), every[:, 1].max()
        s = min((w - 20) / (xmax - xmin), (h - 16) / (ymax - ymin))
        ox, oy = (w - (xmax - xmin) * s) / 2, (h - (ymax - ymin) * s) / 2
        self.rings = {n: [np.stack([(r[:, 0] - xmin) * s + ox, (ymax - r[:, 1]) * s + oy], 1) for r in rs] for n, rs in proj.items()}
        self.outline = np.zeros((h, w), np.uint8)
        S.draw_chunks(self.outline, S.strokes([r for rs in self.rings.values() for r in rs], line, 61, amp=0.4, chunk=40))
        self._fill = {}

    def fill(self, name):
        if name not in self._fill:
            m = np.zeros((self.h, self.w), np.uint8)
            for r in self.rings[name]:
                _poly(m, r)
            hatch = np.zeros_like(m)
            for k in range(-self.h, self.w, self.hatch_step):
                cv2.line(hatch, (k, self.h), (k + self.h, 0), 255, 1 if self.hatch_step <= 6 else 3, cv2.LINE_AA)
            self._fill[name] = (np.maximum(m.astype(np.float32) / 255 * 0.55, hatch.astype(np.float32) / 255 * (m > 0)))
        return self._fill[name]


# ------------------------------------------------------------------ una ronda: un estado
class StateRound:
    def __init__(self, rec, idx, total, tier_idx, tier_num, tier_label, cd):
        self.rec, self.idx, self.total, self.cd = rec, idx, total, cd
        self.tier_num, self.tier_label = tier_num, tier_label
        self.rev = CS + cd
        self.dur = self.rev + HOLD
        name = rec["state"]
        polys = us_state(name)
        centre = geo.bbox_center(max(polys, key=lambda p: geo.ring_area(p[0]))[0])
        v = self.view = geo.View(polys, MW, MH, margin_x=90, margin_y=70, center=centre)
        tgt_rings = [v.px(r) for p in polys for r in p]
        tgt_outer = [v.px(p[0]) for p in polys]
        tgt_holes = [v.px(r) for p in polys for r in p[1:]]
        near_rings, near_outer = [], []
        for key, plist in admin1().items():
            if key == ("United States of America", name):
                continue
            for p in plist:
                if geo.ang_dist_deg(v.lon0, v.lat0, *geo.bbox_center(p[0])) < 30:
                    near_outer.append(v.px(p[0]))
                    near_rings.extend(v.px(r) for r in p)
        land = np.zeros((MH, MW), np.uint8)
        for r in near_outer + tgt_outer:
            _poly(land, r)
        fill = np.zeros_like(land)
        for r in tgt_outer:
            _poly(fill, r)
        for r in tgt_holes:
            _poly(fill, r, 0)
        self.fill = fill.astype(np.float32) / 255
        self.ctx = self._context(v, land, near_rings, idx)
        self.chunks = [S.strokes(tgt_rings, 4, idx * 10 + k, amp=1.6) for k in range(3)]
        self.outline = [S.draw_chunks(np.zeros((MH, MW), np.uint8), c) for c in self.chunks]
        self.hatch = [_hatch(k).astype(np.float32) / 255 * self.fill for k in range(3)]
        self.red = [np.maximum(0.22 * self.fill, 0.92 * h) for h in self.hatch]
        self.clues = [clue_mask(t, 70 + 7 * k + idx) for k, t in enumerate(rec["clues"])]
        self.stamp = make_stamp(("IDENTIFIED",), name.upper(), max_w=560, size=100, seed=idx)
        self._stamp_cache = {}
        self.dials = [dial_face(k, cd) for k in range(3)]
        self.bg = self._static()

    # contexto del mapa: vecinos, lineas de agua, reticula, escala, rosa de los vientos (misma receta que RoundScene, a 1120x800)
    def _context(self, v, land, near_rings, idx):
        nm = np.zeros((MH, MW), np.uint8)
        S.draw_chunks(nm, S.strokes(near_rings, 1, 900 + idx, amp=0.5, chunk=40))
        n_cc, cc, st, _ = cv2.connectedComponentsWithStats((land > 0).astype(np.uint8), connectivity=8)
        big = np.isin(cc, [k for k in range(1, n_cc) if st[k, cv2.CC_STAT_AREA] >= 2200])
        dist = cv2.distanceTransform((~big).astype(np.uint8), cv2.DIST_L2, 5)
        dist += 1.0 * S.smooth_noise(np.random.default_rng(idx + 11), MH, MW, 30)
        water = np.zeros((MH, MW), np.float32)
        for d, a in ((10, .8), (22, .55), (36, .32)):
            water = np.maximum(water, a * np.clip(1 - np.abs(dist - d) / 1.0, 0, 1))
        water *= (land == 0)
        grat = np.zeros((MH, MW), np.uint8)
        lab = np.zeros((MH, MW), np.float32)
        reserve = [(20, MH - 70, 300, MH - 14), (MW - 110, MH - 160, MW - 20, MH - 26)]
        lo0, lo1, la0, la1 = v.lonlat_bounds()
        step = next((s for s in (1, 2, 5, 10, 15, 20, 30) if max(lo1 - lo0, la1 - la0) / s <= 7), 30)

        def label(txt, x, y, size=22):
            m = S.text_mask(txt, MONO, size).astype(np.float32) / 255 * 0.75
            x, y = int(x), int(y)
            x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + m.shape[1], MW), min(y + m.shape[0], MH)
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
            return (px[:, 0] > 18) & (px[:, 0] < MW - 18) & (px[:, 1] > 18) & (px[:, 1] < MH - 18)

        for lat in np.arange(math.ceil(la0 / step) * step, la1, step):
            lons = np.linspace(lo0 - 8, lo1 + 8, 240)
            px = v.px(np.stack([lons, np.full_like(lons, lat)], 1))
            dashed(px)
            if inside(px).any():
                k = np.where(inside(px))[0][np.argmin(px[inside(px), 0])]
                label(f"{abs(int(lat))}°{'N' if lat >= 0 else 'S'}", px[k, 0] + 6, px[k, 1] - 26)
        for lon in np.arange(math.ceil(lo0 / step) * step, lo1, step):
            lats = np.linspace(la0 - 8, la1 + 8, 240)
            px = v.px(np.stack([np.full_like(lats, lon), lats], 1))
            dashed(px)
            if inside(px).any():
                k = np.where(inside(px))[0][np.argmax(px[inside(px), 1])]
                label(f"{abs(int(lon))}°{'E' if lon >= 0 else 'W'}", px[k, 0] + 6, px[k, 1] - 28)
        km = next((k for k in (2500, 2000, 1000, 500, 250, 200, 100, 50, 25, 10, 5) if k / v.km_per_px <= 260), 5)
        L = int(km / v.km_per_px)
        sb = np.zeros((MH, MW), np.uint8)
        bx, by = 40, MH - 58
        cv2.rectangle(sb, (bx, by), (bx + L, by + 10), 255, 2, cv2.LINE_AA)
        cv2.rectangle(sb, (bx, by), (bx + L // 2, by + 10), 255, -1)
        label(f"{km} km", bx, by + 14)
        reserve.append((bx - 8, by - 8, bx + L + 8, by + 40))
        cx, cy = MW - 70, MH - 80
        cv2.line(sb, (cx, cy + 34), (cx, cy - 28), 255, 2, cv2.LINE_AA)
        cv2.fillPoly(sb, [np.array([[cx, cy - 40], [cx - 9, cy - 16], [cx + 9, cy - 16]], np.int32)], 255, cv2.LINE_AA)
        cv2.circle(sb, (cx, cy), 28, 255, 1, cv2.LINE_AA)
        label("N", cx - 7, cy - 76)
        reserve.append((cx - 40, cy - 80, cx + 40, cy + 40))
        for x0, y0, x1, y1 in reserve:
            water[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = 0
        return np.maximum.reduce([water, nm.astype(np.float32) / 255 * 0.8, grat.astype(np.float32) / 255 * 0.42, lab, sb.astype(np.float32) / 255 * 0.9])

    def _static(self):
        img = S.paper(LW, LH).copy()
        put_text(img, "THE LOST ATLAS", SERIF_B, 26, MX, 60, tracking=7, align="l")
        put_text(img, f"LEVEL {self.tier_num}  -  {self.tier_label.upper()}", SERIF_B, 30, 960, 60, tracking=6)
        put_text(img, f"State {self.idx + 1} of {self.total}", SERIF_I, 32, LW - MX, 60, align="r")
        S.rule(img, MX, 100, LW - MX, 100, 3, 1)
        S.rule(img, MX, 109, LW - MX, 109, 1, 2)
        m = np.zeros((MH + 60, MW + 60), np.uint8)
        o = 30
        cv2.rectangle(m, (o - 13, o - 13), (o + MW + 13, o + MH + 13), 255, 3, cv2.LINE_AA)
        cv2.rectangle(m, (o, o), (o + MW, o + MH), 255, 1, cv2.LINE_AA)
        for x in range(o, o + MW, 40):
            if (x - o) // 40 % 2 == 0:
                m[o - 13:o, x:x + 40] = 255
                m[o + MH:o + MH + 13, x:x + 40] = 255
        for y in range(o, o + MH, 40):
            if (y - o) // 40 % 2 == 0:
                m[y:y + 40, o - 13:o] = 255
                m[y:y + 40, o + MW:o + MW + 13] = 255
        ink(img, m, MX - o, MY - o)
        put_text(img, f"Fig. {self.idx + 1}.  Outline, Lambert equal-area projection", SERIF_I, 24, MX, MY + MH + 42, opacity=0.75, align="l")
        for k, y in enumerate(ROWS):
            S.rule(img, CX0, y, LW - MX, y, 1, 10 + k, opacity=0.8)
            put_text(img, ROMAN[k], SERIF_I, 34, CX0 + 4, y - 24, opacity=0.5, align="l")
        # ruta de progreso: 50 marcas
        pm = np.zeros((LH, LW), np.uint8)
        for i in range(self.total):
            x = MX + 18 + int(i * (LW - 2 * MX - 36) / (self.total - 1))
            if i < self.idx:
                cv2.circle(pm, (x, 1038), 8, 255, -1, cv2.LINE_AA)
            else:
                cv2.circle(pm, (x, 1038), 8, 255 if i == self.idx else 150, 1, cv2.LINE_AA)
        ink(img, pm, 0, 0, INK, 0.85)
        self.mark = (MX + 18 + int(self.idx * (LW - 2 * MX - 36) / (self.total - 1)), 1038)
        ring = np.zeros((LH, LW), np.uint8)
        cv2.circle(ring, self.mark, 14, 255, 2, cv2.LINE_AA)
        ink(img, ring, 0, 0, RED, 0.9)
        return img

    # ------------------------------------------------------------------ cuadro
    def frame(self, t):
        img = self.bg.copy()
        ink(img, self.ctx, MX, MY, INK, S.ease_out(t / 0.5))
        v = int(t * 7.5) % 3
        draw_k = S.ease_out((t - 0.15) / 1.2)
        if draw_k < 1:
            ink(img, S.draw_chunks(np.zeros((MH, MW), np.uint8), self.chunks[0], int(len(self.chunks[0]) * draw_k)), MX, MY)
        else:
            ink(img, self.outline[v], MX, MY)
        s = t - self.rev
        if s < 0:
            ink(img, self.hatch[v], MX, MY, INK, 0.30 * draw_k)
        else:
            k = S.ease_out(s / 0.25)
            ink(img, self.red[v], MX, MY, RED, k)
            ink(img, self.outline[v], MX, MY, RED, 0.55 * k)
        for k, ((mask, adv), t0) in enumerate(zip(self.clues, CLUE_T)):
            n = min(len(self.rec["clues"][k]), int((t - t0) * CPS))
            if n > 0:
                ink(img, mask[:, :int(16 + n * adv + 8)], CX0 + 62, ROWS[k] - mask.shape[0] + 12, INK, 0.93)
        if s < 0.12:
            self._dial(img, t, 1.0 if s < 0 else 1 - s / 0.12, v)
        if s >= 0:
            sc = 1 + 0.55 * max(0.0, 1 - s / 0.10)
            key = round(sc, 2)
            if key not in self._stamp_cache:
                h, w = self.stamp.shape
                self._stamp_cache[key] = cv2.resize(self.stamp, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_AREA) if key != 1 else self.stamp
            m = self._stamp_cache[key]
            ink(img, m, DIAL_C[0] - m.shape[1] // 2, DIAL_C[1] - m.shape[0] // 2, RED, min(1.0, s / 0.04))
            mark = np.zeros((LH, LW), np.uint8)
            cv2.circle(mark, self.mark, 8, 255, -1, cv2.LINE_AA)
            ink(img, mark, 0, 0, RED, S.ease_out(s / 0.3))
            if s > 0.3:
                mini = UsMini.get()
                k = S.ease_out((s - 0.3) / 0.35)
                ink(img, mini.outline, MM[0], MM[1], INK, k)
                ink(img, mini.fill(self.rec["state"]), MM[0], MM[1], RED, k)
            if s < 0.32:
                a = 10 * math.exp(-s * 13)
                M = np.float32([[1, 0, a * math.sin(s * 95)], [0, 1, a * math.cos(s * 80)]])
                img = cv2.warpAffine(img, M, (LW, LH), borderMode=cv2.BORDER_REPLICATE)
        return img

    def _dial(self, img, t, opacity, v):
        R, cd = DIAL_R, self.cd
        size = 2 * (R + 30)
        c = size / 2
        e = min(max(t - CS, 0.0), cd + 0.3)
        cnt = int(e)
        frac = e - cnt
        pos = 0.0 if cnt == 0 else (cnt - 1 + (1 - math.exp(-frac * 28) * math.cos(frac * 46))) / cd
        th = 2 * math.pi * min(pos, 1.0)
        ox, oy = DIAL_C[0] - size // 2, DIAL_C[1] - size // 2
        ink(img, self.dials[v], ox, oy, INK, opacity)
        wedge = np.zeros((size, size), np.uint8)
        pts = [(c, c)] + [(c + (R - 16) * math.sin(p), c - (R - 16) * math.cos(p)) for p in np.linspace(th, 2 * math.pi, 40)]
        cv2.fillPoly(wedge, [np.round(np.array(pts)).astype(np.int32)], 255, cv2.LINE_AA)
        ink(img, wedge, ox, oy, RED, 0.2 * opacity)
        hand = np.zeros((size, size), np.uint8)
        p0 = (c + 74 * math.sin(th), c - 74 * math.cos(th))
        p1 = (c + (R - 26) * math.sin(th), c - (R - 26) * math.cos(th))
        cv2.line(hand, (int(p0[0] * 8), int(p0[1] * 8)), (int(p1[0] * 8), int(p1[1] * 8)), 255, 4, cv2.LINE_AA, 3)
        cv2.circle(hand, (int(p1[0]), int(p1[1])), 8, 255, -1, cv2.LINE_AA)
        ink(img, hand, ox, oy, RED, opacity)
        put_text(img, str(max(0, cd - cnt)), SERIF_B, 130, DIAL_C[0], DIAL_C[1] + 8, INK, opacity)

    def audio_events(self):
        """(tiempo local, tipo) para el sonido: lo comparte long_sound.py."""
        return dict(rev=self.rev, cd=self.cd, clue_t=CLUE_T, clues=self.rec["clues"])


# ------------------------------------------------------------------ tarjetas
class TierCard:
    dur = 4.0

    def __init__(self, tier_num, label, n_states, cd):
        self.num, self.label, self.n, self.cd = tier_num, label, n_states, cd
        self.stamp = make_stamp(("LEVEL",), tier_num, max_w=640, size=230, angle=-3.5, seed=ord(tier_num[0]))

    def frame(self, t):
        img = S.paper(LW, LH).copy()
        s = t - 0.45
        if s >= 0:
            sc = 1 + 0.5 * max(0.0, 1 - s / 0.10)
            m = self.stamp if sc == 1 else cv2.resize(self.stamp, (int(self.stamp.shape[1] * sc), int(self.stamp.shape[0] * sc)), interpolation=cv2.INTER_AREA)
            ink(img, m, LW // 2 - m.shape[1] // 2, 410 - m.shape[0] // 2, RED, min(1.0, s / 0.04))
        put_text(img, self.label, SERIF_I, 120, 960, 790, INK, S.ease_out((t - 0.9) / 0.5))
        S.rule(img, 560, 870, 1360, 870, 3, 5, S.ease_out((t - 1.2) / 0.4))
        put_text(img, f"{self.n} states  -  {self.cd} seconds each", MONO, 36, 960, 935, INK, 0.9 * S.ease_out((t - 1.4) / 0.4))
        if 0 <= s < 0.32:
            a = 12 * math.exp(-s * 13)
            img = cv2.warpAffine(img, np.float32([[1, 0, a * math.sin(s * 95)], [0, 1, a * math.cos(s * 80)]]), (LW, LH), borderMode=cv2.BORDER_REPLICATE)
        return img


class Checkpoint:
    dur = 6.0

    def __init__(self, done, total):
        self.done, self.total = done, total

    def frame(self, t):
        img = S.paper(LW, LH).copy()
        put_text(img, f"{self.done} states down.", SERIF_I, 120, 960, 400, INK, S.ease_out(t / 0.5))
        put_text(img, f"{self.total - self.done} to go.", SERIF_I, 120, 960, 540, INK, S.ease_out((t - 0.5) / 0.5))
        S.rule(img, 560, 640, 1360, 640, 3, 6, S.ease_out((t - 1.0) / 0.4))
        put_text(img, "Keep count - the hardest ones are still ahead.", MONO, 36, 960, 730, INK, 0.9 * S.ease_out((t - 1.6) / 0.5))
        put_text(img, "Level IV and V give you more time.", MONO, 36, 960, 800, INK, 0.9 * S.ease_out((t - 2.6) / 0.5))
        return img


class LongIntro:
    dur = 6.5

    def __init__(self, episode=2, total=50):
        rings, petals, fills = brand.rose((960, 400), 250, 77)
        self.chunks = S.strokes(rings + petals, 4, 77, amp=1.2, chunk=8)
        self.fills = fills
        self.stamp = make_stamp(("EXPEDITION",), f"No. {episode:03d}", max_w=520, size=84, angle=5, seed=3)
        self.total = total

    def frame(self, t):
        img = S.paper(LW, LH).copy()
        k = S.ease_out(t / 1.6)
        m = S.draw_chunks(np.zeros((LH, LW), np.uint8), self.chunks, int(len(self.chunks) * k))
        cv2.circle(m, (960, 400), 43, 0, -1, cv2.LINE_AA)                        # hueco de papel para el centro rojo
        ink(img, m, 0, 0)
        if t > 1.2:
            f = np.zeros((LH, LW), np.uint8)
            for poly in self.fills:
                cv2.fillPoly(f, [np.round(poly).astype(np.int32)], 255, cv2.LINE_AA)
            cv2.circle(f, (960, 400), 43, 0, -1, cv2.LINE_AA)
            ink(img, f, 0, 0, INK, S.ease_out((t - 1.2) / 0.6))
            dot = np.zeros((LH, LW), np.uint8)
            cv2.circle(dot, (960, 400), 21, 255, -1, cv2.LINE_AA)
            cv2.circle(dot, (960, 400), 37, 255, 3, cv2.LINE_AA)
            ink(img, dot, 0, 0, RED, S.ease_out((t - 1.4) / 0.5))
        o = S.ease_out((t - 1.6) / 0.6)
        size = S.fit_size(f"NAME ALL {self.total} US STATES", SERIF_B, 1500, 124, 4)
        put_text(img, f"NAME ALL {self.total} US STATES", SERIF_B, size, 960, 770, INK, o, tracking=4)
        S.rule(img, 440, 850, 1480, 850, 3, 4, o)
        S.rule(img, 440, 860, 1480, 860, 1, 5, o)
        put_text(img, "by outline  -  from easy to impossible", SERIF_I, 52, 960, 930, INK, o)
        put_text(img, "5 levels  -  3 clues each  -  beat the clock", MONO, 32, 960, 1000, INK, 0.9 * S.ease_out((t - 2.4) / 0.6))
        if t > 2.0:
            s = t - 2.0
            m = self.stamp if s > 0.1 else cv2.resize(self.stamp, (int(self.stamp.shape[1] * 1.4), int(self.stamp.shape[0] * 1.4)), interpolation=cv2.INTER_AREA)
            ink(img, m, 1560 - m.shape[1] // 2, 200 - m.shape[0] // 2, RED, min(1.0, s / 0.04))
        return img


RANKS = (("50", "Lost Atlas Master"), ("41-49", "Royal Explorer"), ("31-40", "Cartographer"), ("21-30", "Navigator"), ("11-20", "Deckhand"), ("0-10", "Stowaway"))


class LongOutro:
    dur = 14.0

    def frame(self, t):
        img = S.paper(LW, LH).copy()
        put_text(img, "How many did you get?", SERIF_I, 96, 960, 190, INK, S.ease_out(t / 0.6))
        S.rule(img, 560, 262, 1360, 262, 3, 7, S.ease_out((t - 0.4) / 0.4))
        for i, (rng_, title) in enumerate(RANKS):
            o = S.ease_out((t - 1.0 - 0.7 * i) / 0.45)
            y = 350 + i * 80
            put_text(img, rng_, S.MONO_B, 42, 760, y, INK, o, align="r")
            put_text(img, title, SERIF_I, 56, 810, y - 4, RED if i == 0 else INK, o, align="l")
        put_text(img, "Comment your rank below.", MONO, 40, 960, 880, INK, 0.95 * S.ease_out((t - 6.0) / 0.5))
        put_text(img, "A new expedition every day  -  THE LOST ATLAS", SERIF_I, 44, 960, 965, INK, S.ease_out((t - 7.5) / 0.6))
        return img

