"""Rain on glass at night: each droplet is a tiny lens showing the flipped city bokeh behind it."""
import numpy as np, cv2
from .common import W, H, vgrad, Finisher, loop_sin


class RainScene:
    name = "rain"
    title_stats = {}

    def __init__(self, seed=7, drops=46):
        rng = np.random.default_rng(seed)
        self.rng = rng
        base = vgrad([(0, (40, 18, 15)), (0.5, (60, 30, 30)), (1, (25, 12, 12))]).astype(np.float32)
        lights = np.zeros_like(base)
        pal = [(60, 120, 255), (255, 170, 80), (180, 90, 255), (90, 220, 255), (255, 120, 190)]
        for _ in range(260):
            x, y = int(rng.uniform(0, W)), int(rng.uniform(H * 0.3, H))
            r = int(rng.uniform(6, 30))
            c = np.array(pal[rng.integers(len(pal))], np.float32) * rng.uniform(0.8, 1.4)
            tmp = np.zeros((H, W, 3), np.float32)
            cv2.circle(tmp, (x, y), r, c.tolist(), -1, cv2.LINE_AA)
            lights += tmp
        self.sharp = np.clip(base + lights, 0, 255).astype(np.float32)
        self.blur = cv2.GaussianBlur(self.sharp, (0, 0), 16) * 0.95
        self.n = drops
        self.x0 = rng.uniform(40, W - 40, drops)
        self.y0 = rng.uniform(0, H, drops)
        self.r = rng.uniform(11, 30, drops)
        self.cyc = rng.integers(1, 3, drops)          # full-screen passes per clip (loop-safe)
        self.fin = Finisher(seed=5, grain=4.0, vig=0.5)
        self.title_stats = {"drops": drops}

    def frame(self, i, n):
        t = i / n
        img = self.blur.copy()
        # tiny fog droplets (static texture, slight twinkle)
        for k in range(self.n):
            y = (self.y0[k] + self.cyc[k] * t * H * 0.55 + 0) % (H + 80) - 40
            x = self.x0[k] + 9 * np.sin(2 * np.pi * (2 * t + k * 0.37))
            r = int(self.r[k])
            x0, y0 = int(x) - r, int(y) - r
            if x0 < 0 or y0 < 0 or x0 + 2 * r >= W or y0 + 2 * r >= H:
                continue
            patch = self.sharp[y0:y0 + 2 * r, x0:x0 + 2 * r][::-1, ::-1]   # lens inversion
            yy, xx = np.mgrid[-r:r, -r:r].astype(np.float32)
            d = np.sqrt(xx ** 2 + yy ** 2) / r
            m = np.clip((1 - d) * 5, 0, 1)[..., None]
            rim = (np.clip(1 - np.abs(d - 0.88) * 14, 0, 1) * 55)[..., None]
            hl = (np.exp(-(((xx + r * 0.35) ** 2 + (yy + r * 0.4) ** 2) / (r * 0.18) ** 2)) * 160)[..., None]
            roi = img[y0:y0 + 2 * r, x0:x0 + 2 * r]
            roi[:] = roi * (1 - m) + np.clip(patch * 1.9 + 20, 0, 255) * m + rim + hl
            cv2.line(img, (int(x), int(y) - r), (int(x), int(y) - r - 36), (48, 40, 38), 1, cv2.LINE_AA)   # thin trail
        return self.fin(img, i)
