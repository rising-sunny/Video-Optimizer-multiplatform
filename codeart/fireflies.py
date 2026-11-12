"""Fireflies in a night forest. Each one is an oscillator that only sees its nearest neighbours
(Kuramoto-style coupling); nobody leads, and yet the whole forest ends up flashing together."""
import numpy as np, cv2
from scipy.spatial import cKDTree
from .common import W, H, FPS, vgrad, Finisher, text_layer, blit_text
from .sunflower import _fbm, _poly, _smooth, ONE, SHIFT

GROUND = int(H * 0.70)
GLOW = np.array([70, 240, 190], np.float32)     # BGR yellow-green
SIM_SECONDS = 20


def _pine(lay, x, base, h, w, col):
    tiers = 9
    cv2.rectangle(lay, (int(x - w * .05), int(base - h * .2)), (int(x + w * .05), int(base)), col, -1)
    for k in range(tiers):
        f = k / tiers
        top = base - h * (1 - f * 0.86)
        bot = top + h * 0.30
        hw = w * (0.12 + 0.88 * f ** 0.9) / 2 * (0.92 + 0.16 * (k % 2))
        cv2.fillPoly(lay, [np.int32([[x, top], [x - hw, bot], [x + hw, bot]])], col, cv2.LINE_AA)


class FirefliesScene:
    name = "fireflies"
    audio_kind = "night"

    def __init__(self, seed=10, count=1400):
        self.rng = rng = np.random.default_rng(seed)
        self.n = count
        self.title_stats = {"fireflies": count}
        self._simulate(rng)
        self._init_forest(rng)
        self.fin = Finisher(seed=4, grain=3.0, vig=0.45)
        self.cap_a = text_layer("1,400 fireflies. No leader.", 40, bold=True)
        self.cap_b = text_layer("Each one only watches its neighbors.", 29)
        self.cap_c = text_layer("Nobody told them to.", 42, bold=True)
        self.cap_d = text_layer("Real fireflies do this in the wild.", 29)

    # ------------------------------------------------------------------ the actual model
    def _simulate(self, rng):
        n = self.n
        self.z = rng.random(n) ** 1.3                      # 0 far .. 1 near
        self.x = rng.uniform(-20, W + 20, n)
        lo, hi = H * 0.40, H * 0.70 + (H * 0.22) * self.z
        self.y = lo + rng.random(n) * (hi - lo)
        tree = cKDTree(np.stack([self.x, self.y], 1))
        _, nb = tree.query(np.stack([self.x, self.y], 1), k=201)
        nb = nb[:, 1:]                                     # 200 nearest, never itself
        frames = SIM_SECONDS * FPS
        omega = 2 * np.pi * rng.normal(0.80, 0.025, n)     # ~0.8 flashes per second
        th = rng.uniform(0, 2 * np.pi, n)
        self.phase = np.zeros((frames, n), np.float32)
        self.r = np.zeros(frames, np.float32)
        dt = 1 / FPS
        for f in range(frames):
            K = 3.6 * _smooth((f / FPS - 2.5) / 6.0)
            th = th + dt * (omega + K * np.sin(th[nb] - th[:, None]).mean(1))
            self.phase[f] = np.mod(th, 2 * np.pi)
            self.r[f] = np.abs(np.exp(1j * th).mean())
        self.flash = self._pulse(self.phase)
        self.level = self.flash.mean(1)
        self.calm = float(self.level[:60].mean())
        hit = np.where(self.r > 0.92)[0]
        self.t_lock = float(hit[0] / FPS) if len(hit) else 11.0
        # one soft note per collective flash after the lock: a small melody the forest plays
        peaks = [f for f in range(1, frames - 1) if self.level[f] > 0.45 and self.level[f] >= self.level[f - 1]
                 and self.level[f] > self.level[f + 1] and f / FPS >= self.t_lock - 0.3]
        scale = (440.0, 523.25, 659.25, 587.33, 523.25, 659.25, 783.99)
        self.audio_events = [(f / FPS, (scale[k % len(scale)], scale[k % len(scale)] * 2)) for k, f in enumerate(peaks)]

    @staticmethod
    def _pulse(ph):
        return np.exp(-ph / 1.15) * _smooth(ph / 0.16)

    # ------------------------------------------------------------------ forest
    def _init_forest(self, rng):
        sky = vgrad([(0, (40, 18, 10)), (0.42, (70, 36, 22)), (0.70, (88, 54, 36)), (1, (40, 26, 18))])
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.moon = (W * 0.66, H * 0.285)
        d = np.sqrt((xx - self.moon[0]) ** 2 + (yy - self.moon[1]) ** 2)
        sky += np.exp(-(d / 300) ** 2)[..., None] * np.array([72, 54, 40], np.float32)
        sky += np.exp(-(d / 40) ** 6)[..., None] * np.array([214, 232, 240], np.float32)
        for _ in range(260):
            x, y, v = int(rng.uniform(0, W)), int(rng.uniform(0, H * 0.45)), float(rng.uniform(70, 200))
            if (x - self.moon[0]) ** 2 + (y - self.moon[1]) ** 2 > 60 ** 2:
                cv2.circle(sky, (x, y), 1, (v, v, v * 0.95), -1, cv2.LINE_AA)
        img = sky.copy()
        lit = np.zeros((H, W), np.float32)                 # how much each pixel catches the firefly light
        # pine ridges, far and foggy -> near and dark
        for depth, (n_tr, hmin, hmax, wmin, wmax, base, col, fog) in enumerate((
                (44, 150, 250, 105, 165, GROUND - 40, (96, 70, 52), 0.55), (24, 240, 370, 170, 250, GROUND - 6, (66, 48, 36), 0.40),
                (12, 360, 500, 250, 340, GROUND + 26, (36, 28, 22), 0.22))):
            mask = np.zeros((H, W), np.float32)
            lay = np.zeros((H, W, 3), np.float32)
            for _ in range(n_tr):
                x = rng.uniform(-40, W + 40)
                h, w = rng.uniform(hmin, hmax), rng.uniform(wmin, wmax)
                _pine(lay, x, base, h, w, tuple(float(c) * rng.uniform(0.88, 1.08) for c in col))
                _pine(mask, x, base, h, w, 1.0)
            # solid, uneven understory: no sky through the trees and no straight edge
            cols = np.arange(W, dtype=np.float32)
            fill = base - 90 - depth * 50 + 24 * np.sin(cols / 37 + depth * 2) + 13 * np.sin(cols / 13 + depth)
            under = yy > fill[None, :]
            lay[under & (mask == 0)] = np.array(col, np.float32) * 0.8
            mask[under] = 1
            m = cv2.GaussianBlur(mask, (0, 0), 0.9)[..., None]
            img = img * (1 - m) + cv2.GaussianBlur(lay, (0, 0), 1.2 - depth * 0.3) * m
            lit = np.maximum(lit, mask * (0.34 + depth * 0.25))
            fogband = np.exp(-(((yy - (base - 60)) / 210) ** 2))[..., None]
            img = img + fogband * np.array([78, 62, 52], np.float32) * fog * (0.55 + 0.45 * _fbm(H, W, rng, 4, 3)[..., None])
        # forest floor
        g = np.clip((yy - GROUND) / 60, 0, 1)[..., None]
        noise = _fbm(H, W, rng, 5, 12)[..., None]
        floor = (np.array([24, 40, 24], np.float32) * (0.45 + noise * 1.1))
        img = img * (1 - g) + floor * g
        lit = np.maximum(lit, g[..., 0] * 0.75)
        # a creek winding towards the viewer
        ys = np.arange(H, dtype=np.float32)
        p = np.clip((ys - (GROUND + 10)) / (H - GROUND - 10), 0, 1)
        centre = W * 0.46 + 92 * np.sin(p * 5.2 + 0.5) * p ** 0.7 + 40 * p
        half = 7 + 150 * p ** 1.6
        creek = np.clip((half[:, None] - np.abs(xx - centre[:, None])) / 6, 0, 1) * (p > 0)[:, None]
        self.creek = creek[..., None].astype(np.float32)
        moon_col = np.array([120, 92, 70], np.float32)
        streak = np.exp(-(((xx - centre[:, None] - 26 * np.sin(p * 9)[:, None]) / (half[:, None] * 0.5 + 6)) ** 2))[..., None]
        img = img * (1 - self.creek) + (np.array([44, 28, 18], np.float32) + moon_col * streak * 0.62) * self.creek
        self.base = np.clip(img, 0, 255).astype(np.float32)
        self.yy = yy
        reach = np.clip((yy - H * 0.26) / (H * 0.24), 0, 1) ** 1.5
        self.lit = (lit * reach * (0.75 + 0.5 * _fbm(H, W, rng, 5, 7)))[..., None].astype(np.float32)
        # creek ripples: flat stretched noise that slides towards the viewer
        rip = cv2.resize(rng.random((H // 7, W // 60)).astype(np.float32), (W, H * 2), interpolation=cv2.INTER_CUBIC)
        self.ripple = cv2.GaussianBlur(rip, (0, 0), 1.2)
        # drifting mist
        cw = W + 300
        fg = np.clip((_fbm(H, cw, rng, 5, 4) - 0.44) * 3.2, 0, 1)
        band = np.exp(-((np.arange(H, dtype=np.float32)[:, None] - GROUND * 0.92) / 240) ** 2)
        self.mist = (fg * band).astype(np.float32)
        # two near trunks frame the shot
        tr, ta = np.zeros((H, W, 3), np.float32), np.zeros((H, W), np.float32)
        grain = cv2.resize(rng.random((24, W // 3)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
        for x0, w0 in ((-30, 62), (W - 34, 70)):
            poly = np.array([[x0, 0], [x0 + w0 * 0.85, 0], [x0 + w0 * 1.25, H], [x0 - 22, H]], np.int32)
            m = np.zeros((H, W), np.float32)
            cv2.fillPoly(m, [poly], 1.0, cv2.LINE_AA)
            tr += m[..., None] * (np.array([12, 15, 18], np.float32) + grain[..., None] * np.array([14, 17, 22], np.float32))
            ta = np.maximum(ta, m)
        self.trunk = cv2.GaussianBlur(tr, (0, 0), 1.3)
        self.trunk_a = cv2.GaussianBlur(ta, (0, 0), 1.3)[..., None]
        # foreground grass and fern fronds
        g = 190
        self.gx = rng.uniform(-20, W + 20, g)
        self.gh = rng.uniform(55, 175, g)
        self.gb = rng.uniform(-0.6, 1.0, g)
        self.gph = rng.uniform(0, 6.28, g)
        self.gv = rng.uniform(0.55, 1.15, g)
        self.ferns = [(x, float(rng.uniform(95, 195)), float(side * rng.uniform(0.25, 0.72)), rng.uniform(0, 6.28))
                      for x, side in ((26, 1), (92, 1), (150, -1), (598, 1), (648, -1), (704, -1), (40, -1), (680, 1))]
        # firefly drift and depth
        self.dph = rng.uniform(0, 6.28, (self.n, 2))
        self.dfq = rng.uniform(0.18, 0.5, (self.n, 2))
        self.damp = 10 + self.z * 30
        self.bright = 0.34 + 0.9 * self.z ** 1.4
        self.big = self.z > 0.93

    def _splat(self, buf, x, y, w):
        x0, y0 = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
        fx, fy = x - x0, y - y0
        h_, w_ = buf.shape
        for dx, dy, wt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            xi, yi = x0 + dx, y0 + dy
            ok = (xi >= 0) & (xi < w_) & (yi >= 0) & (yi < h_)
            np.add.at(buf, (yi[ok], xi[ok]), (w * wt)[ok])

    def frame(self, i, n):
        t = i / FPS
        f = min(i, len(self.level) - 1)
        level = float(self.level[f])
        lift = max(0.0, level - self.calm) / (1 - self.calm)   # how far above the random "shimmer" this frame is
        img = self.base.copy()
        dx = 2 + 9.0 * t
        mist = cv2.warpAffine(self.mist, np.float32([[1, 0, -dx], [0, 1, 0]]), (W, H), flags=cv2.INTER_LINEAR)[..., None]
        img += mist * np.array([76, 62, 54], np.float32) * (0.62 + lift * 0.9)
        img += self.lit * GLOW * (0.04 + lift * 0.28)          # the forest appears when they all flash
        rp = cv2.warpAffine(self.ripple, np.float32([[1, 0, 0], [0, 1, -H + 26 * t]]), (W, H), flags=cv2.INTER_LINEAR)[..., None]
        img += self.creek * (0.05 + lift * 0.24) * GLOW * rp
        # fireflies
        x = self.x + self.damp * np.sin(self.dfq[:, 0] * t * 6.28 + self.dph[:, 0])
        y = self.y + self.damp * 0.7 * np.sin(self.dfq[:, 1] * t * 6.28 + self.dph[:, 1])
        w = self.flash[f] * self.bright
        small = ~self.big
        half = np.zeros((H // 2, W // 2), np.float32)
        self._splat(half, x[small] / 2, y[small] / 2, w[small])
        core = cv2.GaussianBlur(half, (0, 0), 1.0) * 26
        wide = cv2.GaussianBlur(half, (0, 0), 7.5) * 30
        glow = cv2.resize(core + wide, (W, H), interpolation=cv2.INTER_LINEAR)
        glow = 1 - np.exp(-glow * 0.8)                          # soft shoulder so a mass flash never clips flat
        img += glow[..., None] * np.array([120, 255, 215], np.float32)
        img += (cv2.flip(glow, 0)[..., None] * self.creek) * GLOW * 0.5   # creek reflection
        img = img * (1 - self.trunk_a) + (self.trunk * (1 + lift * 1.2) + self.lit * GLOW * lift * 0.12) * self.trunk_a
        np.clip(img, 0, 255, out=img)
        im = img.astype(np.uint8)
        gain = 0.42 + lift * 1.15
        for k in range(len(self.gx)):
            xx0, h = self.gx[k], self.gh[k]
            sw = 11 * np.sin(0.7 * t - xx0 / 170 + self.gph[k] * 0.2) + 5 * np.sin(1.9 * t + self.gph[k])
            s = np.linspace(0, 1, 5)
            px = xx0 + (24 * self.gb[k] + sw) * s ** 2
            c = (34 * self.gv[k] * gain, 74 * self.gv[k] * gain, 42 * self.gv[k] * gain)
            cv2.polylines(im, [_poly(np.stack([px, H - s * h], 1))], False, c, 2, cv2.LINE_AA, SHIFT)
        for x0, L, bend, ph in self.ferns:
            b = bend + 0.035 * np.sin(0.8 * t + ph)
            s = np.linspace(0, 1, 15)
            ang = -np.pi / 2 + b * (0.35 + 1.5 * s)
            sx, sy = x0 + np.cumsum(np.cos(ang)) * L / 15, H - 8 + np.cumsum(np.sin(ang)) * L / 15
            c = (38 * gain, 88 * gain, 50 * gain)
            cv2.polylines(im, [_poly(np.stack([sx, sy], 1))], False, c, 2, cv2.LINE_AA, SHIFT)
            for j in range(1, 14):
                ln = L * 0.27 * (1 - j / 14) ** 0.7
                for side in (-1, 1):
                    a2 = ang[j] + side * 1.05
                    p0 = (int(sx[j] * ONE), int(sy[j] * ONE))
                    p1 = (int((sx[j] + np.cos(a2) * ln) * ONE), int((sy[j] + np.sin(a2) * ln) * ONE))
                    cv2.line(im, p0, p1, c, 2, cv2.LINE_AA, SHIFT)
        out = im.astype(np.float32)
        # a few fireflies right in front of the lens: big soft bokeh
        if self.big.any():
            b = np.zeros((H // 2, W // 2), np.float32)
            self._splat(b, x[self.big] / 2, y[self.big] / 2, w[self.big])
            out += cv2.resize(cv2.GaussianBlur(b, (0, 0), 7.0) * 62, (W, H))[..., None] * np.array([60, 200, 165], np.float32)
        # the number is the hook; the end belongs to the forest
        vis = 1 - _smooth((t - 14.0) / 0.8)
        pre = 1 - _smooth((t - self.t_lock + 0.5) / 0.5)
        post = _smooth((t - self.t_lock - 0.5) / 0.7) * vis
        if vis > 0:
            blit_text(out, text_layer(f"In sync: {int(round(float(self.r[f]) * 100))}%", 58, bold=True), W // 2, 236, vis)
        if pre > 0:
            blit_text(out, self.cap_a, W // 2, 116, pre * _smooth(t / 0.3))
            blit_text(out, self.cap_b, W // 2, 168, pre * _smooth((t - 0.4) / 0.3))
        if post > 0:
            blit_text(out, self.cap_c, W // 2, 116, post)
            blit_text(out, self.cap_d, W // 2, 168, post)
        return self.fin(out, i)
