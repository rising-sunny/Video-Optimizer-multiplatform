"""Autumn sunset: a recursive branching rule + wind + falling leaves."""
import numpy as np, cv2
from .common import W, H, vgrad, Finisher, loop_sin


class TreeScene:
    name = "tree"
    title_stats = {}

    def __init__(self, seed=11542, depth=11):
        rng = np.random.default_rng(seed)
        self.rng = rng
        # ---- branch table, generated level by level (rule: split, turn, shorten, repeat)
        L = [dict(parent=np.array([-1]), turn=np.array([0.0]), length=np.array([175.0]),
                  width=np.array([13.0]), depth=0)]
        for d in range(1, depth):
            p = L[-1]
            n = len(p["length"])
            parent = np.repeat(np.arange(n), 2)
            side = np.tile([-1, 1], n)
            turn = side * rng.uniform(0.28, 0.50, 2 * n)
            length = p["length"][parent] * rng.uniform(0.72, 0.80, 2 * n)
            width = np.maximum(p["width"][parent] * 0.70, 1.0)
            L.append(dict(parent=parent, turn=turn, length=length, width=width, depth=d))
        self.L = L
        self.n_branches = sum(len(l["length"]) for l in L)
        self.phase = [rng.uniform(0, 6.28, len(l["length"])) for l in L]
        # ---- leaves
        self.n_leaves = 3500
        tips = L[-1]
        self.leaf_branch = rng.integers(0, len(tips["length"]), self.n_leaves)
        self.leaf_t0 = rng.uniform(0, 1, self.n_leaves)
        self.leaf_fall = rng.random(self.n_leaves) < 0.45     # these let go and fall
        self.leaf_col = rng.choice(4, self.n_leaves)
        self.leaf_sz = rng.uniform(2.2, 4.6, self.n_leaves)
        self.leaf_drift = rng.uniform(40, 150, self.n_leaves)
        self.leaf_cyc = rng.integers(1, 4, self.n_leaves)
        self.pal = np.array([(20, 70, 230), (25, 120, 245), (30, 170, 255), (35, 50, 170)])  # BGR
        self.title_stats = {"branches": self.n_branches, "leaves": self.n_leaves}
        # ---- static background
        sky = vgrad([(0, (60, 25, 45)), (0.35, (70, 60, 150)), (0.62, (60, 130, 245)), (0.78, (130, 200, 255)), (1, (30, 60, 110))])
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        sx, sy = W * 0.62, H * 0.58
        d = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2)
        glow = np.exp(-(d / 210) ** 2)[..., None] * np.array([190, 235, 255], np.float32)
        self.sun_core = (np.exp(-(d / 38) ** 4))[..., None] * 255
        ang = np.arctan2(yy - sy, xx - sx)
        rays = (0.5 + 0.5 * np.sin(ang * 11 + 1.3)) * (0.5 + 0.5 * np.sin(ang * 5 - 0.4))
        self.rays = (rays ** 3 * np.exp(-d / 650))[..., None].astype(np.float32)
        ground = np.clip((yy - H * 0.86) / (H * 0.14), 0, 1)[..., None]
        self.bg = sky * (1 - 0.0) + glow * 0.9 + self.sun_core
        self.bg = self.bg * (1 - ground) + np.array([12, 18, 30], np.float32) * ground
        self.bg = self.bg.astype(np.float32)
        self.ray_col = np.array([140, 205, 255], np.float32)
        self.fin = Finisher(seed=3, grain=4.5, vig=0.55)

    def _tips(self, i, n):
        base = np.array([W * 0.42, H * 0.92])
        pos = [base[None, :].copy()]
        ang = [np.array([-np.pi / 2])]
        out = []
        wind = loop_sin(i, n, 1) * 0.5 + loop_sin(i, n, 3, 1.1) * 0.2 + 0.25
        for d, l in enumerate(self.L):
            k = (d / (len(self.L) - 1)) ** 1.6                 # sway grows with distance from trunk
            gust = loop_sin(i, n, 2, 0) * 0.5 + loop_sin(i, n, 5, 0)
            a = ang[-1][l["parent"]] if d else ang[0]
            a = a + l["turn"] + (0.07 * wind + 0.02 * np.sin(self.phase[d] + 0 * gust)) * k * 0.9 \
                + 0.012 * k * np.sin(2 * np.pi * (i / n) * 3 + self.phase[d])
            p0 = pos[-1][l["parent"]] if d else pos[0]
            p1 = p0 + np.stack([np.cos(a), np.sin(a)], -1) * l["length"][:, None]
            out.append((p0, p1, l["width"], d))
            pos.append(p1); ang.append(a)
        return out

    def frame(self, i, n):
        t = i / n
        img = self.bg.copy()
        ray_k = 0.55 + 0.25 * loop_sin(i, n, 2)
        img += self.rays * self.ray_col * ray_k
        np.clip(img, 0, 255, out=img)
        im = img.astype(np.uint8)
        segs = self._tips(i, n)
        for p0, p1, w, d in segs:                               # branches
            col = (14 + 3 * d, 22 + 2 * d, 32 + 3 * d)
            for a, b, ww in zip(p0.astype(np.int32), p1.astype(np.int32), w):
                cv2.line(im, (a[0], a[1]), (b[0], b[1]), col, int(round(ww)), cv2.LINE_AA)
        tp = segs[-1][1]
        # leaves: attached to tips, or falling (periodic over the clip)
        for k in range(self.n_leaves):
            x, y = tp[self.leaf_branch[k]]
            c = tuple(int(v) for v in self.pal[self.leaf_col[k]])
            if self.leaf_fall[k]:
                u = (t + self.leaf_t0[k]) % 1.0
                y = y + u * (H * 0.93 - y)
                x = x + self.leaf_drift[k] * u + 24 * np.sin(2 * np.pi * (self.leaf_cyc[k] * t + self.leaf_t0[k]))
                if u > 0.97:
                    continue
            cv2.ellipse(im, (int(x), int(y)), (int(self.leaf_sz[k] * 1.3), int(self.leaf_sz[k])),
                        (t * 360 * self.leaf_cyc[k] + k * 7) % 360, 0, 360, c, -1, cv2.LINE_AA)
        out = im.astype(np.float32)
        return self.fin(out, i)
