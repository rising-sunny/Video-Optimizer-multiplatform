"""Identidad del canal: foto de perfil (800x800) y banner (2560x1440) con el mismo lenguaje del atlas.

    .venv/bin/python -m lostatlas.brand [--name "THE LOST ATLAS"]   ->  auto_videos/lostatlas/brand/

Banner de YouTube: la zona segura (visible en todos los dispositivos) es 1546x423 px centrada; en escritorio
se ve una franja de 2560x423 y solo en TV el lienzo completo. Todo lo importante va en la zona segura.
"""
import argparse
import math
from pathlib import Path

import cv2
import numpy as np

from . import geo
from . import style as S
from .scenes import make_stamp
from .style import INK, MONO, RED, SERIF_B, SERIF_I, ink, put_text

ROOT = Path(__file__).resolve().parent.parent


def rose(c, r, seed, scale=1.0):
    """Rosa de los vientos grabada: aros con graduacion, 4 puntas principales (media punta rellena) y 4 diagonales."""
    cx, cy = c
    th = np.linspace(0, 2 * np.pi, 220)
    rings = [np.stack([cx + r * np.cos(th), cy + r * np.sin(th)], 1), np.stack([cx + r * 0.94 * np.cos(th), cy + r * 0.94 * np.sin(th)], 1)]
    petals, fills = [], []
    ctr = np.array(c, float)
    for ang, ln, wd in [(0, 1.0, .10), (90, 1.0, .10), (180, 1.0, .10), (270, 1.0, .10), (45, .66, .065), (135, .66, .065), (225, .66, .065), (315, .66, .065)]:
        a = math.radians(ang - 90)
        u, n = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
        tip, side = ctr + u * r * ln * 0.92, n * r * wd
        petals.append(np.array([tip, ctr + side, ctr - u * r * ln * 0.16, ctr - side, tip]))
        fills.append(np.array([tip, ctr + side, ctr, tip]))
    return rings, petals, fills


def draw_rose(canvas, c, r, thick, seed, color=INK, ticks=True):
    h, w = canvas.shape[:2]
    rings, petals, fills = rose(c, r, seed)
    m = np.zeros((h, w), np.uint8)
    S.draw_chunks(m, S.strokes(rings[:1], thick, seed, amp=r * 0.004, chunk=10))
    S.draw_chunks(m, S.strokes(rings[1:], max(1, thick // 3), seed + 1, amp=r * 0.004, chunk=10))
    S.draw_chunks(m, S.strokes(petals, max(2, int(thick * 0.55)), seed + 2, amp=r * 0.003, chunk=6))
    for f in fills:
        cv2.fillPoly(m, [np.round(f).astype(np.int32)], 255, cv2.LINE_AA)
    if ticks:
        for k in range(72):
            a = math.radians(k * 5)
            r0, r1 = r * 0.94, r * (0.885 if k % 2 == 0 else 0.915)
            p0 = (int(c[0] + r0 * math.sin(a)), int(c[1] - r0 * math.cos(a)))
            p1 = (int(c[0] + r1 * math.sin(a)), int(c[1] - r1 * math.cos(a)))
            cv2.line(m, p0, p1, 255, 2 if k % 6 == 0 else 1, cv2.LINE_AA)
    cv2.circle(m, (int(c[0]), int(c[1])), int(r * 0.17), 0, -1, cv2.LINE_AA)           # hueco de papel para el centro rojo
    ink(canvas, m, 0, 0, color)
    dot = np.zeros((h, w), np.uint8)                       # centro rojo, como un sello
    cv2.circle(dot, (int(c[0]), int(c[1])), int(r * 0.085), 255, -1, cv2.LINE_AA)
    cv2.circle(dot, (int(c[0]), int(c[1])), int(r * 0.15), 255, max(2, thick // 3), cv2.LINE_AA)
    ink(canvas, dot, 0, 0, RED)


def profile(size=800):
    img = S.paper(size, size).copy()
    draw_rose(img, (size / 2, size / 2), size * 0.40, 9, 21)
    return img


def _frame(img, x0, y0, x1, y1, seed):
    """Marco de cartucho: doble linea con banda graduada, igual que el marco de los mapas."""
    h, w = img.shape[:2]
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (x0 - 14, y0 - 14), (x1 + 14, y1 + 14), 255, 4, cv2.LINE_AA)
    cv2.rectangle(m, (x0, y0), (x1, y1), 255, 2, cv2.LINE_AA)
    for x in range(x0, x1, 48):
        if (x - x0) // 48 % 2 == 0:
            m[y0 - 14:y0, x:min(x + 48, x1)] = 255
            m[y1:y1 + 14, x:min(x + 48, x1)] = 255
    for y in range(y0, y1, 48):
        if (y - y0) // 48 % 2 == 0:
            m[y:min(y + 48, y1), x0 - 14:x0] = 255
            m[y:min(y + 48, y1), x1:x1 + 14] = 255
    ink(img, m, 0, 0)


def banner(name="THE LOST ATLAS", tagline="name the country - the year - the empire", w=2560, h=1440):
    img = S.paper(w, h).copy()
    # ---------------- mapamundi de grabado, a ancho completo (solo se ve en escritorio y TV)
    world = geo.load("110m")
    k = w / 340.0
    lat_top = 84
    oy = (h - (lat_top + 58) * k) / 2

    def px(ring):
        return np.stack([(ring[:, 0] + 170) * k, oy + (lat_top - ring[:, 1]) * k], 1)

    land = np.zeros((h, w), np.uint8)
    rings = []
    for name_, plist in world.items():
        if name_ == "Antarctica":
            continue
        for p in plist:
            pr = px(p[0])
            cv2.fillPoly(land, [np.round(pr).astype(np.int32)], 255)
            rings.append(pr)
    outline = np.zeros((h, w), np.uint8)
    S.draw_chunks(outline, S.strokes(rings, 2, 5, amp=1.0, chunk=30))
    dist = cv2.distanceTransform((land == 0).astype(np.uint8), cv2.DIST_L2, 5)
    dist += 2.0 * S.smooth_noise(np.random.default_rng(3), h, w, 60)
    water = np.zeros((h, w), np.float32)
    for d, a in ((14, .8), (30, .55), (50, .35)):
        water = np.maximum(water, a * np.clip(1 - np.abs(dist - d) / 1.4, 0, 1))
    water *= (land == 0)
    pat = np.zeros((h, w), np.uint8)
    for kx in range(-h, w, 16):
        cv2.line(pat, (kx, h), (kx + h, 0), 255, 2, cv2.LINE_AA)
    hatch = pat.astype(np.float32) / 255 * (land > 0)
    grat = np.zeros((h, w), np.uint8)
    for lon in range(-150, 180, 30):
        for y in range(0, h, 26):
            cv2.line(grat, (int((lon + 170) * k), y), (int((lon + 170) * k), y + 12), 255, 1, cv2.LINE_AA)
    for lat in range(-60, 90, 30):
        y = int(oy + (lat_top - lat) * k)
        for x in range(0, w, 26):
            cv2.line(grat, (x, y), (x + 12, y), 255, 1, cv2.LINE_AA)
    mapa = np.maximum.reduce([water, outline.astype(np.float32) / 255 * 0.62, hatch * 0.20, grat.astype(np.float32) / 255 * 0.28])
    # el mapa se disuelve detras del cartucho para que el titulo respire
    cx0, cy0, cx1, cy1 = 520, 525, 2040, 915
    hole = np.zeros((h, w), np.float32)
    hole[cy0 - 70:cy1 + 70, cx0 - 70:cx1 + 70] = 1
    hole = cv2.GaussianBlur(hole, (0, 0), 28)
    ink(img, mapa * (1 - hole), 0, 0, INK, 0.55)
    # ---------------- cartucho central (zona segura 1546x423)
    _frame(img, cx0, cy0, cx1, cy1, 3)
    draw_rose(img, (745, 720), 150, 6, 40)
    cxm = 1470
    put_text(img, "THE", SERIF_I, 52, cxm, 618, INK, 0.95, tracking=20)
    parts = name.replace("THE ", "", 1) if name.startswith("THE ") else name
    size = S.fit_size(parts, SERIF_B, 940, 150, 5)
    put_text(img, parts, SERIF_B, size, cxm, 728, INK, 1.0, tracking=5)
    S.rule(img, cxm - 470, 812, cxm + 470, 812, 3, 7)
    S.rule(img, cxm - 470, 822, cxm + 470, 822, 1, 8)
    put_text(img, tagline, MONO, 33, cxm, 872, INK, 0.9)
    # ---------------- sellos a los costados (solo escritorio/TV)
    left = make_stamp(("EXPEDITION",), "No. 001", max_w=250, size=64, angle=-6, seed=11)
    right = make_stamp(("NEW",), "EVERY DAY", max_w=270, size=64, angle=5, seed=12)
    ink(img, left, 270 - left.shape[1] // 2, 720 - left.shape[0] // 2, RED)
    ink(img, right, 2290 - right.shape[1] // 2, 720 - right.shape[0] // 2, RED)
    return img


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="THE LOST ATLAS")
    ap.add_argument("--tagline", default="name the country - the year - the empire")
    ap.add_argument("--out", default=str(ROOT / "auto_videos" / "lostatlas" / "brand"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "profile_800.png"), profile())
    b = banner(a.name, a.tagline)
    cv2.imwrite(str(out / "banner_2560x1440.png"), b)
    cv2.imwrite(str(out / "banner_2560x1440.jpg"), b, [cv2.IMWRITE_JPEG_QUALITY, 93])
    prev = b.copy()                                          # vista previa con las zonas de YouTube
    cv2.rectangle(prev, (507, 508), (2053, 931), (0, 0, 255), 3)
    cv2.rectangle(prev, (0, 508), (2559, 931), (255, 120, 0), 3)
    cv2.imwrite(str(out / "banner_safe_zones_preview.png"), prev)
    for f in sorted(out.iterdir()):
        print(f, f"{f.stat().st_size / 1e6:.1f} MB")
