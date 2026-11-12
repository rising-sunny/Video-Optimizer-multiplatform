"""A real sunflower in its field at golden hour. Its seeds follow r = c*sqrt(k), theta = k*angle
(Vogel's model); the angle sweeps from 120 deg to the golden angle while the flower is still closed,
and it opens when the seeds finally pack. Everything on screen is drawn by code."""
import numpy as np, cv2
from .common import W, H, FPS, vgrad, Finisher, text_layer, blit_text

GOLDEN = 180.0 * (3.0 - np.sqrt(5.0))      # 137.50776...
SHIFT = 4
ONE = 1 << SHIFT
HORIZON = int(H * 0.69)


def _smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def _fbm(h, w, rng, octaves=5, base=4):
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        c = base * 2 ** o
        n = rng.random((max(2, int(c * h / w)) + 1, c + 1)).astype(np.float32)
        out += cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC) * amp
        tot += amp
        amp *= 0.5
    return out / tot


def _petal_template(n=9):
    """Unit petal: base at x=0, pointed tip at x=1, widest around 40%."""
    s = np.linspace(0, 1, n)
    half = np.sin(np.pi * s ** 0.72) ** 0.8
    return np.concatenate([np.stack([s, half], 1), np.stack([s[::-1], -half[::-1]], 1)[1:-1]])


def _poly(pts):
    return (pts * ONE).astype(np.int32)


def _small_flower(rng, r):
    """Blurred foreground sunflower sprite: (bgr, alpha)."""
    s = int(r * 3.2)
    img, a = np.zeros((s, s, 3), np.float32), np.zeros((s, s), np.float32)
    tpl = _petal_template(6)
    c = s / 2
    for k in range(24):
        an = k * np.deg2rad(GOLDEN)
        L, w = r * rng.uniform(0.75, 1.0), r * 0.2
        rot = np.array([[np.cos(an), -np.sin(an)], [np.sin(an), np.cos(an)]])
        p = (tpl * [L, w]) @ rot.T + np.array([np.cos(an), np.sin(an)]) * r * 0.45 + c
        col = np.array([20, 165, 235], np.float32) * rng.uniform(0.75, 1.05)
        cv2.fillPoly(img, [_poly(p)], col.tolist(), cv2.LINE_AA, SHIFT)
        cv2.fillPoly(a, [_poly(p)], 1.0, cv2.LINE_AA, SHIFT)
    cv2.circle(img, (int(c), int(c)), int(r * 0.5), (22, 42, 62), -1, cv2.LINE_AA)
    cv2.circle(a, (int(c), int(c)), int(r * 0.5), 1.0, -1, cv2.LINE_AA)
    sig = max(1.5, r * 0.06)
    return cv2.GaussianBlur(img * a[..., None], (0, 0), sig), cv2.GaussianBlur(a, (0, 0), sig)[..., None]


def _blit(dst, sprite, x, y):
    premult, a = sprite
    h, w = a.shape[:2]
    x, y = int(x - w / 2), int(y - h / 2)
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    al = a[y0 - y:y1 - y, x0 - x:x1 - x]
    dst[y0:y1, x0:x1] = dst[y0:y1, x0:x1] * (1 - al) + premult[y0 - y:y1 - y, x0 - x:x1 - x]


class SunflowerScene:
    name = "sunflower"
    audio_kind = "nature"

    def __init__(self, seed=137, seeds=1000):
        rng = np.random.default_rng(seed)
        self.rng = rng
        self.t_pop, self.t_hold, self.t_lock = 0.9, 1.3, 10.5
        self.audio_events = [(self.t_lock, (523.25, 783.99, 1046.5))]
        self.n = seeds
        self.title_stats = {"seeds": seeds}
        self.cx, self.cy = W * 0.5, H * 0.50
        self.Rmax = 205.0
        self._init_landscape(rng)
        self._init_flower(rng)
        self._init_life(rng)
        self.fin = Finisher(seed=2, grain=2.6, vig=0.40)
        self.cap_a = text_layer("Same 1,000 seeds.", 42, bold=True)
        self.cap_b = text_layer("Only this angle changes.", 32)
        self.cap_c = text_layer("The golden angle.", 42, bold=True)
        self.cap_d = text_layer("Real sunflowers pack their seeds this way.", 28)

    # ------------------------------------------------------------------ landscape
    def _init_landscape(self, rng):
        sky = vgrad([(0, (120, 72, 62)), (0.28, (150, 110, 120)), (0.50, (130, 150, 225)),
                     (0.64, (120, 190, 255)), (0.72, (150, 220, 255)), (1, (150, 220, 255))])
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.sun = (W * 0.80, HORIZON - 58.0)
        d = np.sqrt((xx - self.sun[0]) ** 2 + (yy - self.sun[1]) ** 2)
        sky += np.exp(-(d / 330) ** 2)[..., None] * np.array([70, 130, 175], np.float32)
        sky += np.exp(-(d / 46) ** 4)[..., None] * np.array([190, 235, 255], np.float32)
        self.sky = np.clip(sky, 0, 255).astype(np.float32)
        # clouds: fractal noise, lit from below, drifting slowly
        cw = W + 260
        n = _fbm(H, cw, rng)
        band = np.clip(1 - np.abs(np.linspace(0, 1, H)[:, None] - 0.30) / 0.30, 0, 1).astype(np.float32)
        m = np.clip((n - 0.50) * 5.5, 0, 1) * band
        self.cloud_a = cv2.GaussianBlur(m, (0, 0), 2.0)[..., None]
        shade = np.clip((np.roll(n, -14, axis=0) - n) * 7 + 0.5, 0, 1)[..., None]
        self.cloud_c = (np.array([165, 165, 240], np.float32) * shade
                        + np.array([135, 95, 125], np.float32) * (1 - shade))
        # hills + far field: precomposed premultiplied layer
        lay, a = np.zeros((H, W, 3), np.float32), np.zeros((H, W), np.float32)
        xs = np.arange(W, dtype=np.float32)
        for h0, amp, col, ph in ((HORIZON - 92, 30, (118, 118, 170), 0.4), (HORIZON - 52, 24, (88, 104, 128), 2.1),
                                 (HORIZON - 20, 12, (54, 86, 84), 4.0)):
            top = h0 + amp * np.sin(xs / 143 + ph) + amp * 0.5 * np.sin(xs / 61 + ph * 2)
            mask = (np.arange(H, dtype=np.float32)[:, None] > top[None, :]).astype(np.float32)
            lay = lay * (1 - mask[..., None]) + np.array(col, np.float32) * mask[..., None]
            a = np.maximum(a, mask)
        g = np.linspace(0, 1, H - HORIZON, dtype=np.float32)[:, None, None]
        lay[HORIZON:] = np.array([44, 112, 122], np.float32) * (1 - g) + np.array([16, 50, 28], np.float32) * g
        a[HORIZON:] = 1
        # rows of sunflowers: tiny and far near the horizon, bigger towards the viewer
        for _ in range(1500):
            v = rng.random() ** 1.5
            y = HORIZON + 6 + v * (H - HORIZON - 150)
            x = rng.uniform(-10, W + 10)
            r = 1.6 + v * 15
            cv2.line(lay, (int(x), int(y)), (int(x), int(y + r * 3.2)), (22, 72, 40), max(1, int(r * 0.2)), cv2.LINE_AA)
            cv2.circle(lay, (int(x), int(y)), int(max(r, 1)), (22, int(rng.uniform(150, 190)), int(rng.uniform(215, 248))), -1, cv2.LINE_AA)
            if r > 4:
                cv2.circle(lay, (int(x), int(y)), int(r * 0.46), (24, 44, 62), -1, cv2.LINE_AA)
        far = cv2.GaussianBlur(lay, (0, 0), 1.2)
        ga = cv2.GaussianBlur(a, (0, 0), 1.0)[..., None]
        self.land = far.astype(np.float32)
        self.land_a = ga.astype(np.float32)
        # warm light wrapping everything near the sun
        self.flare = (np.exp(-(d / 520) ** 2))[..., None] * np.array([28, 62, 96], np.float32)
        ang = np.arctan2(yy - self.sun[1], xx - self.sun[0])
        rays = (0.5 + 0.5 * np.sin(ang * 13 + 0.7)) * (0.5 + 0.5 * np.sin(ang * 6 - 1.0))
        sky_only = np.clip((HORIZON - 70 - yy) / 90, 0, 1)
        self.rays = (rays ** 3 * np.exp(-d / 520) * sky_only)[..., None].astype(np.float32) * np.array([34, 70, 100], np.float32)
        # foreground: out-of-focus sunflowers + wind-driven grass
        self.near = []
        for x, y, r in ((62, 1085, 56), (668, 1040, 62), (22, 1215, 80), (702, 1205, 88), (190, 1250, 62), (560, 1262, 58)):
            self.near.append(dict(x=x, y=y, s=_small_flower(rng, r), ph=rng.uniform(0, 6.28), k=rng.uniform(4, 8)))
        g = 240
        self.gx = rng.uniform(-20, W + 20, g)
        self.gh = rng.uniform(70, 215, g)
        self.gb = rng.uniform(0.2, 1.0, g)
        self.gph = rng.uniform(0, 6.28, g)
        self.gc = np.stack([rng.uniform(22, 58, g), rng.uniform(88, 150, g), rng.uniform(52, 100, g)], 1)

    # ------------------------------------------------------------------ the flower
    def _init_flower(self, rng):
        self.k = np.arange(1, self.n + 1, dtype=np.float64)
        self.r = self.Rmax * np.sqrt(self.k / self.n)
        u = np.sqrt(self.k / self.n)
        self.sr = 2.1 + 3.5 * u
        c0, c1, c2 = (np.array(c, np.float32) for c in ((34, 76, 58), (26, 62, 108), (44, 148, 226)))
        v = u[:, None]
        cols = np.where(v < 0.55, c0 + (c1 - c0) * (v / 0.55), c1 + (c2 - c1) * ((v - 0.55) / 0.45))
        self.col = cols * rng.uniform(0.84, 1.12, (self.n, 1))
        self.tpl = _petal_template()
        self.pk = []
        for ring, count, (l0, l1), (w0, w1), base, off in (
                (0, 34, (82, 108), (17, 22), (10, 112, 190), 0.3), (1, 55, (66, 92), (15, 20), (16, 172, 244), 0.0)):
            for k in range(count):
                self.pk.append(dict(a=np.deg2rad((k * GOLDEN) % 360) + off, L=rng.uniform(l0, l1), w=rng.uniform(w0, w1),
                                    ph=rng.uniform(0, 6.28), c=np.array(base, np.float32) * rng.uniform(0.86, 1.08)))
        self.sep = [dict(a=np.deg2rad(k * GOLDEN), L=rng.uniform(34, 46), w=rng.uniform(13, 17)) for k in range(34)]
        # stem and two leaves (local to the stem curve)
        self.leaves = [dict(s=0.52, side=-1, L=215, w=62, tilt=0.42, droop=95), dict(s=0.60, side=1, L=225, w=60, tilt=0.40, droop=90)]

    def _stem(self, hx, hy, t):
        base = np.array([W * 0.47, H + 30.0])
        ctrl = np.array([W * 0.53 + 6 * np.sin(0.5 * t), (hy + H) * 0.56])
        head = np.array([hx, hy])
        s = np.linspace(0, 1, 26)[:, None]
        return (1 - s) ** 2 * head + 2 * s * (1 - s) * ctrl + s ** 2 * base

    def _draw_leaf(self, im, pts, leaf, t):
        p, side = pts[int(leaf["s"] * (len(pts) - 1))], leaf["side"]
        a = leaf["tilt"] + 0.035 * np.sin(1.1 * t + leaf["s"] * 9)
        d = np.array([side * np.cos(a), -np.sin(a)])       # out and slightly up...
        n = np.array([-d[1], d[0]])
        u = np.linspace(0, 1, 16)[:, None]
        half = (np.sin(np.pi * u ** 0.62) * leaf["w"])
        mid = p + d * u * leaf["L"] + np.array([0.0, 1.0]) * u ** 2 * leaf["droop"]   # ...then it droops
        a_edge, b_edge = mid + n * half, mid - n * half
        cv2.fillPoly(im, [_poly(np.concatenate([a_edge, b_edge[::-1]]))], (34, 100, 58), cv2.LINE_AA, SHIFT)
        upper = a_edge if a_edge[8, 1] < b_edge[8, 1] else b_edge
        cv2.fillPoly(im, [_poly(np.concatenate([upper, mid[::-1]]))], (46, 132, 80), cv2.LINE_AA, SHIFT)
        for j in (3, 5, 7, 9, 11):                           # side veins
            for edge in (a_edge, b_edge):
                v = mid[j] + (edge[min(j + 2, 15)] - mid[j]) * 0.82
                cv2.line(im, tuple(int(q * ONE) for q in mid[j]), tuple(int(q * ONE) for q in v),
                         (58, 142, 96), 1, cv2.LINE_AA, SHIFT)
        cv2.polylines(im, [_poly(mid)], False, (74, 168, 120), 2, cv2.LINE_AA, SHIFT)

    def _draw_petal(self, im, hx, hy, a, L, w, c, rim):
        ca, sa = np.cos(a), np.sin(a)
        rot = np.array([[ca, -sa], [sa, ca]])
        o = np.array([hx + rim * ca, hy + rim * sa])
        p = (self.tpl * [L, w]) @ rot.T + o
        cv2.fillPoly(im, [_poly(p)], tuple(float(x) for x in c), cv2.LINE_AA, SHIFT)
        tip, q = o + rot @ np.array([L * 0.88, 0]), o + rot @ np.array([L * 0.10, 0])
        cv2.line(im, tuple(int(v * ONE) for v in q), tuple(int(v * ONE) for v in tip),
                 tuple(float(x) * 0.82 for x in c), 1, cv2.LINE_AA, SHIFT)

    # ------------------------------------------------------------------ living things
    def _init_life(self, rng):
        n = 170
        self.mx, self.my = rng.uniform(0, W, n), rng.uniform(H * 0.5, H, n)
        self.mv, self.mp = rng.uniform(6, 22, n), rng.uniform(0, 6.28, n)
        self.mr = rng.uniform(0.9, 2.2, n)
        self.birds = rng.uniform(-1, 1, (6, 2)) * [42, 22]
        self.flock_ph = rng.uniform(0, 6.28, 6)

    def _bee(self, im, x, y, a, t, s=1.0):
        ca, sa = np.cos(a), np.sin(a)
        L, Wd = 11 * s, 6.5 * s
        flick = 0.65 + 0.35 * np.sin(t * 190)
        for side in (-1, 1):                       # wings first, pale
            wx, wy = x - sa * side * 7 * s, y + ca * side * 7 * s
            cv2.ellipse(im, (int(wx * ONE), int(wy * ONE)), (int(8.5 * s * ONE), int(4.2 * flick * s * ONE)),
                        np.rad2deg(a) + side * 72, 0, 360, (236, 232, 226), -1, cv2.LINE_AA, SHIFT)
        cv2.ellipse(im, (int(x * ONE), int(y * ONE)), (int(L * ONE), int(Wd * ONE)), np.rad2deg(a), 0, 360,
                    (24, 170, 232), -1, cv2.LINE_AA, SHIFT)
        for off in (-3.5, 1.0, 5.5):               # stripes
            cx, cy = x + ca * off * s, y + sa * off * s
            dx, dy = -sa * Wd * 0.92, ca * Wd * 0.92
            cv2.line(im, (int((cx - dx) * ONE), int((cy - dy) * ONE)), (int((cx + dx) * ONE), int((cy + dy) * ONE)),
                     (20, 22, 26), max(2, int(2.4 * s)), cv2.LINE_AA, SHIFT)
        cv2.circle(im, (int((x - ca * L) * ONE), int((y - sa * L) * ONE)), int(4.2 * s * ONE), (22, 24, 28), -1, cv2.LINE_AA, SHIFT)

    def _butterfly(self, im, x, y, t, ph, c):
        flap = abs(np.sin(t * 8.5 + ph)) * 0.85 + 0.15
        for side in (-1, 1):
            for dy, r, k in ((-6, 15, 1.0), (7, 10, 0.9)):
                cx = x + side * r * flap * 0.78
                axes = (int(max(r * flap, 1.5) * ONE), int(r * k * ONE))
                cv2.ellipse(im, (int(cx * ONE), int((y + dy) * ONE)), axes, side * 18, 0, 360, c, -1, cv2.LINE_AA, SHIFT)
                cv2.ellipse(im, (int(cx * ONE), int((y + dy) * ONE)), axes, side * 18, 0, 360, (24, 22, 26), 1, cv2.LINE_AA, SHIFT)
        cv2.line(im, (int(x * ONE), int((y - 11) * ONE)), (int(x * ONE), int((y + 12) * ONE)), (20, 20, 24), 2, cv2.LINE_AA, SHIFT)

    # ------------------------------------------------------------------ frame
    def angle(self, t):
        u = np.clip((t - self.t_hold) / (self.t_lock - self.t_hold), 0, 1)
        return GOLDEN - (GOLDEN - 120.0) * (1 - u) ** 3

    def frame(self, i, n):
        t = i / FPS
        after = max(0.0, t - self.t_lock)
        # sky, drifting clouds, land
        dx = 2 + 7.0 * t
        M = np.float32([[1, 0, -dx], [0, 1, 0]])
        ca = cv2.warpAffine(self.cloud_a, M, (W, H), flags=cv2.INTER_LINEAR)[..., None]
        cc = cv2.warpAffine(self.cloud_c, M, (W, H), flags=cv2.INTER_LINEAR)
        img = self.sky * (1 - ca) + cc * ca
        img = img * (1 - self.land_a) + self.land * self.land_a
        img = img + self.flare + self.rays * (0.75 + 0.25 * np.sin(0.8 * t))
        np.clip(img, 0, 255, out=img)
        for f in self.near[:2]:                    # far pair sits behind the main stem
            _blit(img, f["s"], f["x"] + f["k"] * np.sin(1.1 * t + f["ph"]), f["y"])
        im = img.astype(np.uint8)
        # birds crossing high in the sky
        fx = -80 + (W + 160) * ((t - 2.0) / 11.0)
        for k, (ox, oy) in enumerate(self.birds):
            x, y = fx + ox, 332 + oy + 4 * np.sin(t * 0.9 + k)
            w = 6.5 * (0.3 + 0.7 * abs(np.sin(t * 7 + self.flock_ph[k])))
            cv2.polylines(im, [_poly(np.array([[x - 8, y - w], [x, y], [x + 8, y - w]]))], False, (56, 44, 50), 2, cv2.LINE_AA, SHIFT)
        # the plant sways as one
        sway = 7 * np.sin(0.75 * t) + 2.5 * np.sin(1.9 * t + 1)
        hx, hy = self.cx + sway, self.cy + 1.4 * np.sin(1.2 * t)
        pts = self._stem(hx, hy, t)
        tan = np.gradient(pts, axis=0)
        nor = np.stack([-tan[:, 1], tan[:, 0]], 1) / (np.linalg.norm(tan, axis=1, keepdims=True) + 1e-6)
        wd = np.linspace(8.5, 15.0, len(pts))[:, None]
        cv2.fillPoly(im, [_poly(np.concatenate([pts + nor * wd, (pts - nor * wd)[::-1]]))], (30, 88, 50), cv2.LINE_AA, SHIFT)
        lit = pts + np.array([wd[:, 0] * 0.34, np.zeros(len(pts))]).T
        cv2.fillPoly(im, [_poly(np.concatenate([lit + nor * wd * 0.3, (lit - nor * wd * 0.3)[::-1]]))], (60, 142, 92), cv2.LINE_AA, SHIFT)
        for leaf in self.leaves:
            self._draw_leaf(im, pts, leaf, t)
        spin = 0.03 * np.sin(0.4 * t)
        # green sepals are always there; petals open once the angle locks
        for s in self.sep:
            self._draw_petal(im, hx, hy, s["a"] + spin, s["L"], s["w"], (44, 118, 74), self.Rmax - 4)
        bloom = _smooth(after / 2.2)
        if bloom > 0:
            for p in self.pk:
                a = p["a"] + spin + 0.016 * np.sin(1.4 * t + p["ph"])
                self._draw_petal(im, hx, hy, a, p["L"] * bloom, p["w"] * (0.35 + 0.65 * bloom), p["c"], self.Rmax - 7)
        cv2.circle(im, (int(hx * ONE), int(hy * ONE)), int((self.Rmax + 7) * ONE), (16, 28, 38), -1, cv2.LINE_AA, SHIFT)
        th = self.k * np.deg2rad(self.angle(t)) + spin
        xs = ((hx + self.r * np.cos(th)) * ONE).astype(np.int64)
        ys = ((hy + self.r * np.sin(th)) * ONE).astype(np.int64)
        rad = (self.sr * ONE).astype(np.int64)
        visible = int(self.n * _smooth(t / self.t_pop) ** 0.7)
        for k in range(visible):
            cv2.circle(im, (int(xs[k]), int(ys[k])), int(rad[k]), tuple(float(v) for v in self.col[k]), -1, cv2.LINE_AA, SHIFT)
        # bees: two wander; one lands on the open flower
        land = _smooth((t - 11.6) / 1.5)
        for b, (rx, ry, wx, wy, ph, s) in enumerate(((300, 250, 0.55, 0.83, 0.3, 1.25), (245, 330, 0.71, 0.47, 2.4, 1.0), (330, 200, 0.38, 0.91, 4.5, 0.85))):
            x0 = hx + rx * np.cos(wx * t + ph) + 16 * np.sin(5.3 * t + ph)
            y0 = hy + ry * np.sin(wy * t + ph) + 12 * np.sin(7.1 * t + ph)
            if b == 0:
                tx, ty = hx + 64 + 5 * np.sin(0.9 * t), hy - 46 + 3 * np.sin(1.3 * t)
                x0, y0 = x0 * (1 - land) + tx * land, y0 * (1 - land) + ty * land
            ax = -rx * wx * np.sin(wx * t + ph)
            ay = ry * wy * np.cos(wy * t + ph)
            self._bee(im, x0, y0, np.arctan2(ay, ax), t, s)
        # butterflies low over the field
        for bx, by, ph, c in ((W * 0.18, H * 0.76, 0.7, (30, 120, 240)), (W * 0.83, H * 0.71, 3.1, (60, 180, 250))):
            self._butterfly(im, bx + 62 * np.sin(0.42 * t + ph), by + 44 * np.sin(0.67 * t + ph * 2) + 9 * np.sin(4.2 * t), t, ph, c)
        # grass blown by a travelling gust
        for k in range(len(self.gx)):
            x, h = self.gx[k], self.gh[k]
            gust = np.sin(0.9 * t - x / 180 + self.gph[k] * 0.2) * 0.75 + 0.35 * np.sin(2.3 * t + self.gph[k])
            s = np.linspace(0, 1, 5)
            px = x + (28 * self.gb[k] + 26 * gust) * s ** 2
            py = H - s * h
            cv2.polylines(im, [_poly(np.stack([px, py], 1))], False, tuple(float(v) for v in self.gc[k]), 2 + (k % 3 == 0), cv2.LINE_AA, SHIFT)
        out = im.astype(np.float32)
        for f in self.near[2:]:
            _blit(out, f["s"], f["x"] + f["k"] * np.sin(1.1 * t + f["ph"]), f["y"])
        # pollen and dust catching the sun
        my = (self.my - self.mv * t) % (H * 0.5) + H * 0.5
        mx = self.mx + 14 * np.sin(0.6 * t + self.mp)
        motes = np.zeros((H, W, 3), np.float32)
        for k in range(len(mx)):
            v = 150 + 90 * np.sin(1.4 * t + self.mp[k])
            cv2.circle(motes, (int(mx[k] * ONE), int(my[k] * ONE)), int(self.mr[k] * ONE), (v * 0.62, v * 0.9, v), -1, cv2.LINE_AA, SHIFT)
        out += motes * 0.55
        # light swell when the flower opens
        if t >= self.t_lock:
            out += self.flare * (0.35 * _smooth(after / 2.0) + 1.1 * np.exp(-after * 1.5))
        # the angle stays a small hook; the last seconds are only the field
        vis = 1 - _smooth((t - 14.0) / 0.8)
        label = f"{GOLDEN:.3f}°" if t >= self.t_lock else f"{self.angle(t):.1f}°"
        if vis > 0:
            blit_text(out, text_layer(label, 66, bold=True), W // 2, 236, vis)
        pre = 1 - _smooth((t - self.t_lock + 0.6) / 0.6)
        post = _smooth((t - self.t_lock - 0.6) / 0.7) * vis
        if pre > 0:
            blit_text(out, self.cap_a, W // 2, 118, pre * _smooth(t / 0.35))
            blit_text(out, self.cap_b, W // 2, 170, pre * _smooth((t - 0.5) / 0.35))
        if post > 0:
            blit_text(out, self.cap_c, W // 2, 118, post)
            blit_text(out, self.cap_d, W // 2, 170, post)
        return self.fin(out, i)
