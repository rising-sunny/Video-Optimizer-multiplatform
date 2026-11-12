"""Aurora over a still lake: summed sine curtains + ray streaks, mirrored with ripples."""
import numpy as np, cv2
from .common import W, H, Finisher, loop_sin


class AuroraScene:
    name = "aurora"
    title_stats = {}

    def __init__(self, seed=4):
        rng = np.random.default_rng(seed)
        self.hz = int(H * 0.62)
        sky = np.zeros((self.hz, W, 3), np.float32)
        top, bot = np.array([40, 14, 8], np.float32), np.array([60, 36, 24], np.float32)
        g = np.linspace(0, 1, self.hz)[:, None, None] ** 1.5
        sky[:] = top * (1 - g) + bot * g
        self.sky = sky
        n_stars = 420
        self.sx, self.sy = rng.uniform(0, W, n_stars), rng.uniform(0, self.hz * 0.8, n_stars)
        self.sb, self.sp = rng.uniform(80, 255, n_stars), rng.uniform(0, 6.28, n_stars)
        self.rayph = rng.uniform(0, 6.28, 6)
        self.xs = np.linspace(0, 1, W, dtype=np.float32)
        self.ys = np.linspace(0, 1, self.hz, dtype=np.float32)[:, None]
        self.fin = Finisher(seed=9, grain=3.5, vig=0.5)
        self.title_stats = {"stars": n_stars}

    def frame(self, i, n):
        t = i / n
        xs, ys = self.xs, self.ys
        c = 0.52 + 0.07 * np.sin(2 * np.pi * (2 * xs + t)) + 0.05 * np.sin(2 * np.pi * (3 * xs - 2 * t) + 1.0) \
            + 0.03 * np.sin(2 * np.pi * (7 * xs + 3 * t))                       # curtain height per column
        width = 0.17 + 0.04 * np.sin(2 * np.pi * (1.5 * xs + t) + 2)
        prof = np.exp(-((ys - c[None, :]) / width[None, :]) ** 2)                # HxW
        streak = 0.65 + 0.35 * np.sin(2 * np.pi * (26 * xs + 2 * t * 1) + 5 * np.sin(2 * np.pi * (4 * xs + t)))
        bright = prof * streak[None, :] * (0.8 + 0.2 * np.sin(2 * np.pi * (2 * t) + 3 * xs))
        mix = np.clip((ys - 0.25) / 0.45, 0, 1)                                  # green low -> purple high is (1-mix)
        col = (np.array([90, 255, 90], np.float32) * mix[..., None] + np.array([230, 80, 180], np.float32) * (1 - mix[..., None]))
        sky = self.sky + bright[..., None] * col * 1.5
        sky = np.clip(sky, 0, 255)
        sky_u = sky.astype(np.uint8)
        for x, y, b, p in zip(self.sx, self.sy, self.sb, self.sp):
            v = b * (0.65 + 0.35 * np.sin(2 * np.pi * (3 * t) + p))
            cv2.circle(sky_u, (int(x), int(y)), 1, (v, v, v), -1, cv2.LINE_AA)
        sky = sky_u.astype(np.float32)
        # lake: mirror + horizontal ripple displacement
        lake_h = H - self.hz
        refl = cv2.resize(sky[::-1].copy(), (W, lake_h), interpolation=cv2.INTER_AREA)
        yy = np.arange(lake_h, dtype=np.float32)[:, None]
        shift = (3 * np.sin(2 * np.pi * (yy / 90 + 2 * t)) * (1 + yy / lake_h * 2)).astype(np.float32)
        mapx = (np.arange(W, dtype=np.float32)[None, :] + shift).astype(np.float32)
        mapy = np.repeat(np.arange(lake_h, dtype=np.float32)[:, None], W, 1)
        refl = cv2.remap(refl.astype(np.float32), mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        refl = refl * 0.6 + np.array([14, 8, 4], np.float32)
        img = np.concatenate([sky, refl], 0)
        # dark treeline silhouette on the horizon
        return self.fin(img, i)
