import numpy as np, cv2
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 720, 1280, 60


def vgrad(stops, h=H, w=W):
    """Vertical gradient from [(pos0-1, (b,g,r)), ...] -> float32 HxWx3 (0-255)."""
    ys = np.linspace(0, 1, h)
    pos = [p for p, _ in stops]
    out = np.stack([np.interp(ys, pos, [c[k] for _, c in stops]) for k in range(3)], -1)
    return np.repeat(out[:, None, :], w, 1).astype(np.float32)


def vignette(strength=0.55):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((x - W / 2) / (W * 0.75)) ** 2 + ((y - H / 2) / (H * 0.75)) ** 2)
    return (1 - strength * np.clip(r, 0, 1) ** 2)[..., None].astype(np.float32)


class Finisher:
    """Vignette + film grain, shared by all scenes."""
    def __init__(self, seed=0, grain=5.0, vig=0.5):
        self.rng = np.random.default_rng(seed)
        self.vig = vignette(vig)
        self.grain = grain
        self.pool = [self.rng.normal(0, grain, (H, W, 1)).astype(np.float32) for _ in range(6)]

    def __call__(self, img, i):
        img = img * self.vig + self.pool[i % 6] * (1 if i % 2 else -1)
        return np.clip(img, 0, 255).astype(np.uint8)


def loop_sin(i, n, cycles=1, phase=0.0):
    """Sine that is perfectly periodic over n frames (seamless loop)."""
    return np.sin(2 * np.pi * (cycles * i / n) + phase)


_FONTS = {False: "/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf",
          True: "/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf"}


@lru_cache(maxsize=4096)
def text_layer(text, size, bold=False, color=(255, 255, 255)):
    """(bgr float32 HxWx3, alpha float32 HxWx1) with a soft shadow, no outline."""
    font = ImageFont.truetype(_FONTS[bold], size)
    x0, y0, x1, y1 = font.getbbox(text)
    pad = 24
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((pad - x0, pad - y0), text, fill=255, font=font)
    a = np.asarray(mask, np.float32) / 255
    shadow = cv2.GaussianBlur(a, (0, 0), 7) * 0.55
    alpha = 1 - (1 - a) * (1 - shadow)
    rgb = a[..., None] / np.maximum(alpha[..., None], 1e-3) * np.array(color[::-1], np.float32)
    return rgb, alpha[..., None]


def blit_text(img, layer, cx, cy, opacity=1.0):
    rgb, alpha = layer
    h, w = alpha.shape[:2]
    x, y = int(cx - w / 2), int(cy - h / 2)
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, img.shape[1]), min(y + h, img.shape[0])
    if x1 <= x0 or y1 <= y0 or opacity <= 0:
        return
    a = alpha[y0 - y:y1 - y, x0 - x:x1 - x] * opacity
    img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - a) + rgb[y0 - y:y1 - y, x0 - x:x1 - x] * a
