"""Lineas y palabras del memo escaneado, para recortar y resaltar evidencia."""
import json
import numpy as np
from PIL import Image
LINES = json.load(open("lines.json"))

def words(page, li, gap=18):
    """Cajas de palabras de la linea li: columnas sin tinta mas anchas que `gap` separan palabras."""
    a = np.asarray(Image.open(f"{page}.png").convert("L")) < 128
    x0, y0, x1, y1 = LINES[page][li]
    cols = a[y0:y1, x0:x1 + 1].sum(0) > 0
    out, x, n = [], 0, len(cols)
    while x < n:
        if cols[x]:
            s = x
            while x < n:
                if cols[x]:
                    x += 1; continue
                g = x
                while g < n and not cols[g]: g += 1
                if g - x > gap or g >= n: break
                x = g
            out.append((x0 + s, y0, x0 + x, y1))
        x += 1
    return [b for b in out if b[2] - b[0] >= 20]       # fuera las manchas del escaneo

def spans(page, sel):
    """sel: lista de (linea, primera_palabra, ultima_palabra) -> cajas a resaltar."""
    boxes = []
    for li, a, b in sel:
        w = words(page, li)
        b = len(w) - 1 if b is None else b
        boxes.append((w[a][0], w[a][1], w[b][2], w[b][3]))
    return boxes
