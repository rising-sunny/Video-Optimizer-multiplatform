"""Lenguaje visual: papel, tinta que se multiplica sobre el papel, trazos con pulso de mano.

Reglas para no parecer plantilla de IA: sin degradados ni brillos, un solo rojo de sello,
tipografia de libro (P052) y maquina de escribir (Nimbus Mono), lineas que "hierven" como
animacion dibujada a mano, y texturas procedurales (fibra de papel, sello gastado).
"""
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
PAPER = (236, 226, 206)       # RGB
INK = (30, 34, 44)
RED = (176, 42, 34)

FD = "/usr/share/fonts/opentype/urw-base35/"
SERIF, SERIF_B, SERIF_I = "P052-Roman.otf", "P052-Bold.otf", "P052-Italic.otf"
MONO, MONO_B = "NimbusMonoPS-Regular.otf", "NimbusMonoPS-Bold.otf"


@lru_cache(maxsize=None)
def font(name, size):
    return ImageFont.truetype(FD + name, size)


def smooth_noise(rng, h, w, scale):
    small = rng.standard_normal((h // scale + 3, w // scale + 3)).astype(np.float32)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


@lru_cache(maxsize=None)
def tooth(w=W, h=H):
    """Grano fino 0..1: rompe la tinta como el papel con textura."""
    rng = np.random.default_rng(3)
    t = 0.5 * smooth_noise(rng, h, w, 2) + 0.5 * rng.standard_normal((h, w)).astype(np.float32)
    return np.clip(0.5 + 0.32 * t, 0, 1).astype(np.float32)


@lru_cache(maxsize=None)
def paper(w=W, h=H):
    rng = np.random.default_rng(7)
    lum = sum(smooth_noise(rng, h, w, s) * a for s, a in ((2, 1.5), (5, 1.8), (24, 2.4), (140, 3.6)))
    fib = np.zeros((h, w), np.float32)
    for _ in range(2600):
        x, y, a, l = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0, np.pi), rng.uniform(6, 24)
        cv2.line(fib, (int(x), int(y)), (int(x + l * np.cos(a)), int(y + l * np.sin(a))),
                 float(rng.choice([-1, 1]) * rng.uniform(2, 6)), 1, cv2.LINE_AA)
    lum += cv2.GaussianBlur(fib, (0, 0), 0.7)
    img = np.empty((h, w, 3), np.float32)
    for c, v in enumerate(PAPER[::-1]):
        img[..., c] = v
    img += lum[..., None] * np.array([1.2, 1.0, 0.85], np.float32)
    fox = np.zeros((h, w), np.float32)
    for _ in range(16):
        fox[int(rng.uniform(0, h)), int(rng.uniform(0, w))] = rng.uniform(0.5, 1.0)
    fox = cv2.GaussianBlur(fox, (0, 0), 70)
    img -= (fox / fox.max())[..., None] * np.array([14, 8, 3], np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.maximum(np.abs(xx / w - 0.5), np.abs(yy / h - 0.5)) * 2
    img -= ((np.clip(r - 0.5, 0, 1) / 0.5) ** 2 * 26)[..., None] * np.array([1.0, 0.7, 0.45], np.float32)
    return np.clip(img, 0, 255).astype(np.uint8)


def ink(img, mask, x, y, color=INK, opacity=1.0):
    """Multiplica `color` sobre el papel donde `mask` (uint8 0-255 o float 0-1) tiene valor."""
    h, w = mask.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, img.shape[1]), min(y + h, img.shape[0])
    if x1 <= x0 or y1 <= y0 or opacity <= 0:
        return
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    if mask.dtype == np.uint8:
        m /= 255
    a = np.clip(m * opacity * (0.78 + 0.44 * tooth(img.shape[1], img.shape[0])[y0:y1, x0:x1]), 0, 1)
    col = np.array(color[::-1], np.float32) / 255
    roi = img[y0:y1, x0:x1].astype(np.float32)
    roi *= 1 - a[..., None] * (1 - col)
    img[y0:y1, x0:x1] = roi


@lru_cache(maxsize=4096)
def text_mask(text, fname, size, tracking=0.0):
    f = font(fname, size)
    asc, desc = f.getmetrics()
    pad = size // 3
    if tracking:
        adv = [f.getlength(c) + tracking for c in text]
        w = int(sum(adv)) + 2 * pad
        img = Image.new("L", (w, asc + desc + pad), 0)
        d, x = ImageDraw.Draw(img), pad
        for c, a in zip(text, adv):
            d.text((x, pad // 2), c, font=f, fill=255)
            x += a
    else:
        img = Image.new("L", (int(f.getlength(text)) + 2 * pad, asc + desc + pad), 0)
        ImageDraw.Draw(img).text((pad, pad // 2), text, font=f, fill=255)
    return np.asarray(img)


def fit_size(text, fname, max_w, start, tracking=0.0):
    s = start
    while s > 12 and text_mask(text, fname, s, tracking).shape[1] - 2 * (s // 3) > max_w:
        s -= 2
    return s


def put_text(img, text, fname, size, cx, cy, color=INK, opacity=1.0, tracking=0.0, align="c"):
    m = text_mask(text, fname, size, tracking)
    h, w = m.shape
    x = int(cx - w / 2) if align == "c" else int(cx) if align == "l" else int(cx - w)
    ink(img, m, x, int(cy - h / 2), color, opacity)


def wobble(pts, seed, amp=1.5, scale=55.0):
    r = np.random.default_rng(seed)
    p = r.uniform(0, 6.28, 4)
    x, y = pts[:, 0], pts[:, 1]
    dx = amp * (0.65 * np.sin(x / scale + p[0] + y / (scale * 1.7)) + 0.35 * np.sin(y / (scale * 0.6) + p[1]))
    dy = amp * (0.65 * np.sin(y / scale + p[2] + x / (scale * 1.3)) + 0.35 * np.sin(x / (scale * 0.55) + p[3]))
    return pts + np.stack([dx, dy], 1) + r.normal(0, amp * 0.12, pts.shape)


def strokes(rings, thickness, seed, amp=1.5, chunk=10):
    """Anillos -> tramos con grosor de pluma variable (en orden, para animar el trazado)."""
    r = np.random.default_rng(seed)
    out = []
    for k, ring in enumerate(rings):
        pts = np.clip(wobble(np.asarray(ring, float), seed + 31 * k, amp), -20000, 20000)
        for j in range(0, len(pts) - 1, chunk):
            t = max(1, int(round(thickness * r.uniform(0.75, 1.35))))
            out.append((np.round(pts[j:j + chunk + 1] * 8).astype(np.int32).reshape(-1, 1, 2), t))
    return out


def draw_chunks(mask, chunks, n=None, value=255):
    for seg, t in chunks[:n]:
        cv2.polylines(mask, [seg], False, value, t, cv2.LINE_AA, 3)
    return mask


def rule(img, x0, y0, x1, y1, t=2, seed=0, opacity=1.0, color=INK, amp=0.7):
    n = max(2, int(np.hypot(x1 - x0, y1 - y0) / 18))
    pts = np.stack([np.linspace(x0, x1, n), np.linspace(y0, y1, n)], 1)
    bx, by = int(min(x0, x1)) - 6, int(min(y0, y1)) - 6
    m = np.zeros((int(abs(y1 - y0)) + 14, int(abs(x1 - x0)) + 14), np.uint8)
    draw_chunks(m, strokes([pts - [bx, by]], t, seed, amp=amp, chunk=6))
    ink(img, m, bx, by, color, opacity)


def ease_out(k):
    k = min(max(k, 0.0), 1.0)
    return 1 - (1 - k) ** 3
