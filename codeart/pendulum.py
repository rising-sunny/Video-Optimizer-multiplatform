"""Pendulum wave: N pendulums whose swing counts differ by one, so they drift out of step and realign exactly at the loop point."""
import numpy as np, cv2
from .common import W, H, Finisher, vgrad, text_layer, blit_text

SCALE = [0, 2, 4, 7, 9]          # pentatonic, in semitones


def _ease(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)


class PendulumScene:
    name = "pendulum"
    title_stats = {}

    def __init__(self, seed=3, count=15, base=8, seconds=16):
        rng = np.random.default_rng(seed)
        self.count, self.base, self.seconds = count, base, seconds
        self.bg = vgrad([(0, (46, 22, 14)), (0.55, (70, 36, 28)), (1, (22, 12, 8))])
        self.top_y = int(H * 0.14); self.length = H * 0.60
        self.xs = np.linspace(W * 0.10, W * 0.90, count)
        pal = np.array([(70, 130, 255), (80, 190, 255), (110, 235, 255), (150, 255, 220), (200, 255, 170), (255, 235, 150)], np.float32)
        u = np.linspace(0, len(pal) - 1.001, count)
        self.cols = [tuple(float(v) for v in (pal[int(k)] * (1 - (k % 1)) + pal[int(k) + 1] * (k % 1))) for k in u]
        self.amp = 0.115                                          # radians (small angles keep the wave readable)
        self.fin = Finisher(seed=seed + 20, grain=3.2, vig=0.5)
        self.title_stats = {"count": count, "first": base, "last": base + count - 1}
        self.cap_a = text_layer(f"{count} pendulums.", 44, bold=True)
        self.cap_b = text_layer("Each one a little shorter than the last.", 28)
        self.cap_c = text_layer("They drift apart, then line up again.", 28)
        notes = []
        for i in range(count):
            semi = SCALE[i % 5] + 12 * (i // 5)
            f = 196.0 * 2 ** (semi / 12)
            notes.append(f)
        self.notes = notes
        # one soft note each time a bob passes the lowest point (moving left to right)
        ev = []
        for i in range(count):
            k = base + i                                           # swings in the loop
            for m in range(k):
                t = (m + 0.75) / k * seconds                       # cos(2*pi*k*t/T) crosses zero going down at phase 0.75
                ev.append((t, (notes[i],)))
        self.audio_events = ev

    def frame(self, i, n):
        t = i / n
        img = self.bg.copy()
        # support bar
        cv2.line(img, (int(W * 0.06), self.top_y), (int(W * 0.94), self.top_y), (170, 190, 215), 6, cv2.LINE_AA)
        trail = np.zeros((H, W, 3), np.float32)
        for k in range(self.count):
            freq = self.base + k
            th = self.amp * np.cos(2 * np.pi * freq * t)
            x0, y0 = self.xs[k], self.top_y
            bx, by = x0 + self.length * np.sin(th), y0 + self.length * np.cos(th)
            sh = 4
            cv2.line(img, (int(x0 * 16), int(y0 * 16)), (int(bx * 16), int(by * 16)), (210, 218, 230), 1, cv2.LINE_AA, shift=4)
            # glow: bob + halo, brightest when it passes the lowest point
            speed = abs(np.sin(2 * np.pi * freq * t))
            cv2.circle(trail, (int(bx), int(by)), 30, tuple(c * (0.35 + 0.45 * (1 - speed)) for c in self.cols[k]), -1, cv2.LINE_AA)
            cv2.circle(img, (int(bx * 16), int(by * 16)), 16 * 17, self.cols[k], -1, cv2.LINE_AA, shift=4)
            cv2.circle(img, (int(bx * 16 - 5 * 16), int(by * 16 - 5 * 16)), 16 * 5, (255, 255, 255), -1, cv2.LINE_AA, shift=4)
        glow = cv2.GaussianBlur(trail, (0, 0), 16)
        img = np.clip(img + glow * 0.9, 0, 255)
        out = self.fin(img, i)
        o = out.astype(np.float32)
        for layer, a, b, y in ((self.cap_a, 0.4, 3.6, 0.88), (self.cap_b, 3.2, 7.2, 0.88), (self.cap_c, 8.0, 14.5, 0.88)):
            ts = t * self.seconds
            op = _ease((ts - a) / 0.8) * (1 - _ease((ts - (b - 0.8)) / 0.8))
            if op > 0: blit_text(o, layer, W / 2, H * y, float(op))
        return np.clip(o, 0, 255).astype(np.uint8)
