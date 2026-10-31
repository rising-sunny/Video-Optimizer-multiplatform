"""Cuadros de 'evidencia' para el Short: paginas del memo con la linea resaltada, sobre fondo oscuro (1080x1920)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import carousel as cv
from PIL import Image
OUT = Path("ev"); OUT.mkdir(exist_ok=True)

def frame(name, cards, bg_page=None):
    img = cv.photo(bg_page, 0.5, 0.5, 1.1, dark=0.18, blur=3) if bg_page else cv.vignette(cv.grain(Image.new("RGB", (cv.W, cv.H), (14, 14, 14)), 14))
    total = sum(c.height for c in cards) + 30 * (len(cards) - 1)
    y = (cv.H - total) // 2 - 80
    for c in cards:
        img.paste(c, ((cv.W - c.width) // 2, y), c); y += c.height + 30
    img.save(OUT / f"{name}.png"); print(name)

pc, sp = cv.paper_crop, cv.sp
frame("e1_cover", [pc("p00", (150, 230, 1560, 640), sp("p00", [(2, 2, 4), (3, 0, None), (4, 1, None)]), width=1040, angle=-1.0),
                   pc("p00", (560, 1440, 1560, 1810), [(830, 1590, 1440, 1730)], width=760, angle=1.5)], "p00.png")
frame("e2_northwoods", [pc("p01", (520, 330, 1420, 640), sp("p01", [(7, 0, None)]), width=1000, angle=1.2)], "p01.png")
frame("e3_ship", [pc("p10", (240, 890, 1460, 1100), sp("p10", [(14, 1, None), (16, 1, None), (17, 0, None)]), width=1040, angle=-1.2)], "p10.png")
frame("e4_funerals", [pc("p10", (330, 570, 1460, 690), sp("p10", [(8, 2, 2), (9, 0, 0)]), width=1040, angle=1.0)], "p10.png")
frame("e5_terror", [pc("p10", (240, 1800, 1460, 1915), sp("p10", [(31, 1, 1), (32, 0, None)]), width=1040, angle=1.1)], "p10.png")
frame("e6_airliner", [pc("p12", (260, 370, 1600, 720), sp("p12", [(5, 1, None), (6, 0, None), (7, 0, None), (10, 0, None)]), width=1040, angle=-1.0)], "p12.png")
frame("e7_drone", [pc("p12", (260, 1110, 1600, 1260), sp("p12", [(19, 1, 1), (20, 0, None)]), width=1040, angle=1.0),
                   pc("p12", (260, 1820, 1600, 1920), sp("p12", [(32, 0, None), (33, 0, 0)]), width=1040, angle=-1.2)], "p12.png")
frame("e8_casualty", [pc("p10", (290, 1640, 1290, 1800), sp("p10", [(29, 1, 1), (30, 0, None)]), width=1040, angle=-1.3)], "p10.png")
frame("e9_topsecret", [pc("p00", (150, 20, 1580, 410), [], width=1040, angle=-2.0, marker=False)], "p00.png")
