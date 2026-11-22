"""Miniatura 1280x720 del largo (los Shorts no la usan): mapa de EE. UU. con los 10 estados "Impossible" rayados en rojo."""
import cv2
import numpy as np

from . import long_states as LS
from . import style as S
from .long_scenes import UsMini
from .scenes import make_stamp
from .style import INK, RED, SERIF_B, SERIF_I, ink, put_text

TW, TH = 1280, 720


def make(out_path, title_number="50"):
    img = S.paper(TW, TH).copy()
    mini = UsMini(w=780, h=470, hatch_step=9, line=3)
    ox, oy = 20, 170
    ink(img, mini.outline, ox, oy)
    for st in LS.TIERS[-1][2]:                                  # nivel V (Impossible) en rojo
        ink(img, mini.fill(st), ox, oy, RED, 0.95)
    put_text(img, "THE LOST ATLAS", SERIF_B, 30, 40, 52, tracking=8, align="l")
    S.rule(img, 40, 86, TW - 40, 86, 3, 1)
    cx = 1030
    size = S.fit_size(title_number, SERIF_B, 400, 380)
    put_text(img, title_number, SERIF_B, size, cx, 265, INK)
    put_text(img, "US STATES", SERIF_B, S.fit_size("US STATES", SERIF_B, 430, 96, 2), cx, 440, INK, tracking=2)
    put_text(img, "by outline", SERIF_I, 64, cx, 515, INK)
    stamp = make_stamp(("EASY",), "IMPOSSIBLE", max_w=400, size=58, angle=-4, seed=9)
    ink(img, stamp, cx - stamp.shape[1] // 2, 625 - stamp.shape[0] // 2, RED)
    cv2.imwrite(str(out_path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out_path
