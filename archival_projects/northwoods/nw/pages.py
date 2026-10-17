"""Paginas completas del memo con la frase clave resaltada (marcador rojo) y el foco en ella, para el Short."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from PIL import Image, ImageDraw
import carousel as cv
OUT = Path("pg"); OUT.mkdir(exist_ok=True)
focus = {}

def page(name, pg, sel=(), boxes=()):
    im = Image.open(f"{pg}.png").convert("RGB")
    ink = np.asarray(im)
    paper = Image.blend(im, Image.new("RGB", im.size, (236, 226, 200)), 0.2)
    im = Image.fromarray(np.minimum(np.asarray(paper), ink))
    bx = list(cv.sp(pg, list(sel))) + list(boxes)
    if bx:
        hl = Image.new("RGB", im.size, (255, 255, 255)); d = ImageDraw.Draw(hl)
        for x0, y0, x1, y1 in bx:
            d.rectangle((x0 - 8, y0 - 8, x1 + 8, y1 + 8), fill=(245, 110, 110))
        im = Image.fromarray((np.asarray(im).astype(np.uint16) * np.asarray(hl) // 255).astype(np.uint8))
        x0 = min(b[0] for b in bx); x1 = max(b[2] for b in bx); y0 = min(b[1] for b in bx); y1 = max(b[3] for b in bx)
        scale = max(1080 / im.width, 1920 / im.height)
        zoom = min(2.6, max(1.45, 1080 / (scale * (x1 - x0 + 60) * 1.05)))   # la frase entera, lo mas grande posible
        focus[name] = [round((x0 + x1) / 2 / im.width, 3), round((y0 + y1) / 2 / im.height, 3), round(zoom, 2)]
    else:
        focus[name] = [0.5, 0.5, 1.2]
    cv.grain(im, 7).save(OUT / f"{name}.png"); print(name, focus[name])

page("topsecret", "p00", boxes=[(175, 28, 1564, 113)])
page("northwoods", "p01", [(7, 0, None)])
page("subject", "p00", [(3, 0, None), (4, 1, None)])
page("ship", "p10", [(16, 1, None), (17, 0, None)])
page("funerals", "p10", [(8, 2, 2), (9, 0, 0)])
page("terror", "p10", [(31, 1, 1), (32, 0, None)])
page("airliner", "p12", [(5, 1, None), (6, 0, None), (7, 0, None)])
page("students", "p12", [(10, 0, None)])
page("drone", "p12", [(32, 0, None), (33, 0, 0)])
page("indignation", "p10", [(29, 1, 1), (30, 0, None)])
page("signature", "p00", boxes=[(830, 1590, 1440, 1730)])
json.dump(focus, open(OUT / "focus.json", "w"), indent=1)
