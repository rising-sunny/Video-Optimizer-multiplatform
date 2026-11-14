"""Star trails: the stars are fixed points; the whole sky turns around one pole, as it appears to from the ground (about 15 degrees per hour)."""
import numpy as np, cv2
from .common import W, H, Finisher, vgrad, text_layer, blit_text


def _ease(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)


class StarsScene:
    name = "stars"
    title_stats = {}

    def __init__(self, seed=5, stars=1800, seconds=16):
        rng = np.random.default_rng(seed)
        self.seconds, self.n = seconds, stars
        self.pole = np.array([W * 0.40, H * 0.30], np.float32)
        r = np.sqrt(rng.uniform(0, 1, stars)) * H * 1.05
        a = rng.uniform(0, 2 * np.pi, stars)
        self.r, self.a0 = r, a
        self.b = rng.uniform(0.30, 1.0, stars) ** 1.1
        self.hue = rng.uniform(0, 1, stars)
        self.bg = vgrad([(0, (36, 16, 10)), (0.6, (58, 30, 22)), (0.82, (80, 52, 40)), (1, (24, 18, 18))])
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        ridge = H * 0.84 + 34 * np.sin(2 * np.pi * np.linspace(0, 1.3, W) + 1) + 18 * np.sin(2 * np.pi * np.linspace(0, 5, W))
        for px in (0.12, 0.2, 0.31, 0.78, 0.9):                                  # pine silhouettes
            x0 = int(px * W); base = int(ridge[x0]); h = int(H * (0.07 + 0.05 * ((px * 37) % 1)))
            self_pts = np.array([[x0, base - h], [x0 - h // 3, base], [x0 + h // 3, base]], np.int32)
        self.ground = yy > ridge[None, :]
        self.trees = [(int(px * W), int(ridge[int(px * W)]), int(H * (0.07 + 0.06 * ((px * 37) % 1)))) for px in (0.12, 0.2, 0.31, 0.78, 0.9)]
        self.fin = Finisher(seed=seed + 51, grain=3.2, vig=0.5)
        self.title_stats = {"stars": stars}
        self.cap_a = text_layer(f"{stars:,} stars. None of them move.", 40, bold=True)
        self.cap_b = text_layer("The Earth turns, so the sky seems to.", 27)
        self.cap_c = text_layer("About 15 degrees every hour. Sped up here.", 27)
        self.sweep = np.radians(52)                                               # total rotation over the clip

    def _pos(self, ang):
        x = self.pole[0] + self.r * np.cos(self.a0 + ang); y = self.pole[1] + self.r * np.sin(self.a0 + ang)
        return x, y

    def frame(self, i, n):
        t = i / n; ts = t * self.seconds
        acc = np.zeros((H, W), np.float32)
        steps = 20; trail = np.radians(4.5)
        for s in range(steps):
            ang = self.sweep * t - trail * s / steps
            x, y = self._pos(ang)
            ok = (x >= 0) & (x < W - 1) & (y >= 0) & (y < H - 1)
            np.add.at(acc, (y[ok].astype(int), x[ok].astype(int)), (self.b[ok] * 255 * (1 - s / steps)))
        acc = np.clip(acc, 0, 255)
        glow = acc * 0.9 + cv2.GaussianBlur(acc, (0, 0), 1.2) * 2.2 + cv2.GaussianBlur(acc, (0, 0), 5) * 1.6
        col = np.stack([glow * 1.0, glow * 0.95, glow * 0.85], -1)
        img = self.bg + col
        img[self.ground] = np.array([16, 12, 14], np.float32)
        for (x0, base, h) in self.trees:
            pts = np.array([[x0, base - h], [x0 - h // 3, base + 2], [x0 + h // 3, base + 2]], np.int32)
            cv2.fillConvexPoly(img, pts, (16, 12, 14), cv2.LINE_AA)
        out = self.fin(np.clip(img, 0, 255), i)
        o = out.astype(np.float32)
        for layer, a, b, y in ((self.cap_a, 0.4, 4.6, 0.93), (self.cap_b, 4.6, 9.0, 0.93), (self.cap_c, 9.4, 14.5, 0.93)):
            op = _ease((ts - a) / 0.8) * (1 - _ease((ts - (b - 0.8)) / 0.8))
            if op > 0: blit_text(o, layer, W / 2, H * y, float(op))
        return np.clip(o, 0, 255).astype(np.uint8)
