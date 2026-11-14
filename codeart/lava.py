"""Metaballs / lava lamp: every blob adds r^2/d^2 to a field; where the sum passes 1 the pixel is inside, so near blobs merge."""
import numpy as np, cv2
from .common import W, H, Finisher, vgrad, text_layer, blit_text


def _ease(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)


class LavaScene:
    name = "lava"
    title_stats = {}

    def __init__(self, seed=8, blobs=9, seconds=16):
        rng = np.random.default_rng(seed)
        self.n, self.seconds = blobs, seconds
        self.gw, self.gh = W // 4, H // 4
        yy, xx = np.mgrid[0:self.gh, 0:self.gw].astype(np.float32)
        self.xx, self.yy = xx / self.gw, yy / self.gh * (H / W)
        self.bg = vgrad([(0, (60, 18, 34)), (0.5, (74, 26, 66)), (1, (30, 12, 40))])
        self.r = rng.uniform(0.07, 0.13, blobs)
        self.cx = rng.uniform(0.25, 0.75, blobs); self.ax = rng.uniform(0.05, 0.22, blobs)
        self.cy = rng.uniform(0.55, 0.85, blobs); self.ay = rng.uniform(0.35, 0.60, blobs)   # tall travel: they rise and sink
        self.px, self.py = rng.uniform(0, 6.28, blobs), rng.uniform(0, 6.28, blobs)
        self.kx, self.ky = rng.integers(1, 3, blobs), rng.integers(1, 3, blobs)                # integer cycles: seamless loop
        self.fin = Finisher(seed=seed + 31, grain=3.2, vig=0.5)
        self.title_stats = {"blobs": blobs}
        self.cap_a = text_layer(f"{blobs} circles. One equation.", 42, bold=True)
        self.cap_b = text_layer("Each one adds a field that fades with distance.", 27)
        self.cap_c = text_layer("Where the fields add up past 1, they merge.", 27)

    def frame(self, i, n):
        t = i / n
        field = np.zeros_like(self.xx)
        for k in range(self.n):
            x = self.cx[k] + self.ax[k] * np.sin(2 * np.pi * self.kx[k] * t + self.px[k])
            y = (self.cy[k] + self.ay[k] * np.sin(2 * np.pi * self.ky[k] * t + self.py[k])) * (H / W) * 0.78 - 0.1
            d2 = (self.xx - x) ** 2 + (self.yy - y) ** 2 + 1e-4
            field += self.r[k] ** 2 / d2
        f = cv2.resize(field, (W, H), interpolation=cv2.INTER_CUBIC)
        inside = np.clip((f - 0.85) / 0.30, 0, 1)
        inside = inside * inside * (3 - 2 * inside)
        halo = np.clip(f / 0.85, 0, 1) ** 2.2 * (1 - inside)
        depth = np.clip((f - 1.0) / 2.5, 0, 1)[..., None]                     # hotter toward blob centres
        hot = np.array([70, 150, 255], np.float32) * (1 - depth) + np.array([150, 235, 255], np.float32) * depth    # BGR: orange -> pale yellow
        rim = np.array([140, 60, 230], np.float32)                              # magenta rim
        col = hot * np.clip((f - 0.85) / 0.9, 0, 1)[..., None] + rim * (1 - np.clip((f - 0.85) / 0.9, 0, 1)[..., None])
        img = self.bg * (1 - inside[..., None]) + col * inside[..., None] + halo[..., None] * np.array([110, 50, 210], np.float32) * 0.55
        out = self.fin(np.clip(img, 0, 255), i)
        o = out.astype(np.float32); ts = t * self.seconds
        for layer, a, b, y in ((self.cap_a, 0.4, 4.0, 0.89), (self.cap_b, 4.0, 8.4, 0.89), (self.cap_c, 8.8, 14.5, 0.89)):
            op = _ease((ts - a) / 0.8) * (1 - _ease((ts - (b - 0.8)) / 0.8))
            if op > 0: blit_text(o, layer, W / 2, H * y, float(op))
        return np.clip(o, 0, 255).astype(np.uint8)
