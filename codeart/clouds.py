"""Sunset clouds from noise: layers of 1/f random fields (periodic by construction), thresholded and lit from below; scrolling is an exact number of tiles, so it loops."""
import numpy as np, cv2
from .common import W, H, Finisher, vgrad, text_layer, blit_text

N = 512


def _ease(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)


def _noise(rng, beta=2.0):
    f = np.fft.fftfreq(N)[:, None] ** 2 + np.fft.fftfreq(N)[None, :] ** 2
    f[0, 0] = 1
    spec = (rng.standard_normal((N, N)) + 1j * rng.standard_normal((N, N))) / f ** (beta / 2)
    spec[0, 0] = 0
    z = np.fft.ifft2(spec).real
    return ((z - z.min()) / (z.max() - z.min())).astype(np.float32)


class CloudsScene:
    name = "clouds"
    title_stats = {}

    def __init__(self, seed=12, layers=5, seconds=16):
        rng = np.random.default_rng(seed)
        self.layers, self.seconds = layers, seconds
        self.fields = [(lambda a, b: np.clip(0.66 * a + 0.34 * b, 0, 1))(_noise(rng, 2.6), _noise(rng, 1.7)) for _ in range(layers)]
        self.hz = int(H * 0.78)
        self.sky = vgrad([(0, (96, 52, 40)), (0.35, (150, 92, 120)), (0.62, (150, 130, 230)), (0.78, (130, 190, 255)), (1, (60, 120, 200))], h=H)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.sun = np.exp(-(((xx - W * 0.62) / (W * 0.55)) ** 2 + ((yy - self.hz) / (H * 0.18)) ** 2)) * 1.0
        hill = self.hz + 40 * np.sin(2 * np.pi * np.linspace(0, 1.6, W)) + 28 * np.sin(2 * np.pi * np.linspace(0, 4.3, W) + 1)
        self.hill = np.array([hill[x] for x in range(W)], np.float32)
        self.ymask = yy > self.hill[None, :]
        self.fin = Finisher(seed=seed + 41, grain=3.0, vig=0.5)
        self.title_stats = {"layers": layers}
        self.cap_a = text_layer("These clouds are just noise.", 42, bold=True)
        self.cap_b = text_layer(f"{layers} layers of random numbers.", 27)
        self.cap_c = text_layer("Blurred, stacked, and lit from below.", 27)

    def frame(self, i, n):
        t = i / n; ts = t * self.seconds
        img = self.sky + self.sun[..., None] * np.array([40, 150, 255], np.float32) * 0.8
        for k, fld in enumerate(self.fields):
            depth = k / max(1, self.layers - 1)                          # 0 far .. 1 near
            scale = 1.0 + 1.6 * depth
            dx = (k + 1) * N * t                                          # integer tiles per loop
            Mx = np.float32([[1 / scale * (N / W) * 1.0, 0, dx], [0, 1 / scale * (N / H) * 1.25, (k * 97) % N]])
            tile = cv2.warpAffine(fld, Mx, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
            dens = np.clip((tile - (0.52 - 0.04 * depth)) / 0.16, 0, 1)
            band = np.exp(-(((np.arange(H, dtype=np.float32) - H * (0.42 + 0.30 * depth)) / (H * (0.20 + 0.06 * depth))) ** 2))[:, None]
            dens = dens * band
            gy = np.gradient(cv2.GaussianBlur(tile, (0, 0), 3), axis=0)
            light = np.clip(0.5 - gy * 60, 0, 1)[..., None]               # brighter where the underside faces the sun
            warm = np.array([90, 150, 255], np.float32) * light + np.array([120, 70, 120], np.float32) * (1 - light)
            cloud = warm * (0.55 + 0.45 * (self.sun[..., None] + 0.4))
            img = img * (1 - dens[..., None] * 0.85) + cloud * dens[..., None] * 0.85
        img[self.ymask] = np.array([22, 14, 28], np.float32)
        out = self.fin(np.clip(img, 0, 255), i)
        o = out.astype(np.float32)
        for layer, a, b, y in ((self.cap_a, 0.4, 4.4, 0.92), (self.cap_b, 4.4, 8.6, 0.92), (self.cap_c, 9.0, 14.5, 0.92)):
            op = _ease((ts - a) / 0.8) * (1 - _ease((ts - (b - 0.8)) / 0.8))
            if op > 0: blit_text(o, layer, W / 2, H * y, float(op))
        return np.clip(o, 0, 255).astype(np.uint8)
