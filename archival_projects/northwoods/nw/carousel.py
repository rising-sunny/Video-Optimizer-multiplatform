"""Carrusel de TikTok (1080x1920): Operation Northwoods. Memo JCS 13-3-1962 (desclasificado 1997) y fotos de la Biblioteca del Congreso."""
import random, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
sys.path.insert(0, str(Path(__file__).resolve().parent))
import memo
Image.MAX_IMAGE_PIXELS = None
W, H = 1080, 1920
RED, PAPER, INK = (186, 14, 22), (242, 240, 234), (8, 8, 8)
SERIF = "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"
MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"
F = lambda path, size: ImageFont.truetype(path, size)
X0, X1, TOP, BOTTOM = 64, 930, 170, 1480          # zona segura (arriba la barra, abajo el texto del post, a la derecha los botones)
N = 11
OUT = Path("slides"); OUT.mkdir(exist_ok=True)
rng = random.Random(1962)

def grain(img, amount=10):
    a = np.asarray(img).astype(np.int16)
    n = np.random.default_rng(rng.randint(0, 9999)).normal(0, amount, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a + n, 0, 255).astype(np.uint8))

def vignette(img, strength=0.55):
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    m = np.clip(1 - strength * np.clip(r - 0.35, 0, None), 0, 1)[..., None]
    return Image.fromarray((np.asarray(img).astype(np.float32) * m).astype(np.uint8))

def panel(img, y0, y1, alpha=150):
    """Franja oscura con bordes suaves detras del texto."""
    m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m); d.rectangle((0, y0, W, y1), fill=alpha)
    m = m.filter(ImageFilter.GaussianBlur(40))
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), m)

def photo(path, fx=0.5, fy=0.5, zoom=1.0, dark=0.6, blur=0):
    im = ImageOps.autocontrast(Image.open(path).convert("L"), cutoff=1)
    s = max(W / im.width, H / im.height) * zoom
    im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    left = int(min(max(fx * im.width - W / 2, 0), im.width - W)); top = int(min(max(fy * im.height - H / 2, 0), im.height - H))
    im = im.crop((left, top, left + W, top + H)).point(lambda v: int(v * dark))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    return vignette(grain(im.convert("RGB")))

def paper_crop(page, box, boxes=(), width=960, angle=0.0, marker=True):
    """Recorte del memo: papel envejecido, resaltado rojo (multiplicar) en las cajas, sombra y leve giro."""
    pg = Image.open(f"{page}.png").convert("L")
    x0, y0, x1, y1 = box
    im = pg.crop(box).convert("RGB")
    im = Image.blend(im, Image.new("RGB", im.size, (236, 226, 200)), 0.18)            # papel amarillento
    im = Image.fromarray(np.minimum(np.asarray(im), np.asarray(pg.crop(box).convert("RGB"))))  # la tinta queda negra
    if boxes and marker:
        hl = Image.new("RGB", im.size, (255, 255, 255)); d = ImageDraw.Draw(hl)
        for bx0, by0, bx1, by1 in boxes:
            pad = 6
            d.rectangle((bx0 - x0 - pad, by0 - y0 - pad, bx1 - x0 + pad, by1 - y0 + pad), fill=(245, 120, 120))
        im = Image.fromarray((np.asarray(im).astype(np.uint16) * np.asarray(hl) // 255).astype(np.uint8))
    s = width / im.width
    im = im.resize((width, int(im.height * s)), Image.LANCZOS)
    im = grain(im, 6).convert("RGBA")
    if angle:
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True)
    sh = Image.new("RGBA", (im.width + 40, im.height + 40), (0, 0, 0, 0))
    a = im.split()[3].point(lambda v: 170 if v else 0)
    sh.paste(Image.new("RGBA", im.size, (0, 0, 0, 255)), (26, 30), a)
    sh = sh.filter(ImageFilter.GaussianBlur(14)); sh.alpha_composite(im, (0, 0))
    return sh

def wrap(text, font, maxw):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split():
            t = (cur + " " + w).strip()
            if font.getlength(t) <= maxw: cur = t
            else: lines.append(cur); cur = w
        lines.append(cur)
    return lines

def text(img, s, y, size=78, font=SERIF, fill=PAPER, maxw=None, gap=0.18, stroke=None, align="left"):
    f = F(font, size); d = ImageDraw.Draw(img)
    maxw = maxw or (X1 - X0)
    for line in wrap(s, f, maxw):
        x = X0 if align == "left" else (W - f.getlength(line)) / 2
        d.text((x, y), line, font=f, fill=fill, stroke_width=stroke if stroke is not None else max(3, size // 14), stroke_fill=(0, 0, 0))
        y += int(size * (1 + gap))
    return y

def label(img, i, extra="OPERATION NORTHWOODS"):
    d = ImageDraw.Draw(img); f = F(MONO, 30)
    d.text((X0, TOP - 40), f"{extra} · {i}/{N}", font=f, fill=RED, stroke_width=2, stroke_fill=(0, 0, 0))

def source(img, s):
    d = ImageDraw.Draw(img); f = F(MONO, 22)
    y = BOTTOM - 26
    for line in reversed(wrap(s, f, X1 - X0)):
        d.text((X0, y), line, font=f, fill=(170, 170, 170), stroke_width=2, stroke_fill=(0, 0, 0)); y -= 28

def stamp(img, s, cx, cy, size=120, angle=-12, color=RED, alpha=210):
    f = F(MONO, size); tw = int(f.getlength(s)) + 60; th = size + 60
    st = Image.new("RGBA", (tw, th), (0, 0, 0, 0)); d = ImageDraw.Draw(st)
    d.rectangle((6, 6, tw - 6, th - 6), outline=color + (alpha,), width=10)
    d.text((30, 22), s, font=f, fill=color + (alpha,))
    a = np.asarray(st).copy()                                                      # tinta despareja de sello de goma
    holes = np.random.default_rng(7).random(a.shape[:2]) < 0.22
    a[..., 3] = np.where(holes, (a[..., 3] * 0.35).astype(np.uint8), a[..., 3])
    st = Image.fromarray(a).rotate(angle, expand=True, resample=Image.BICUBIC)
    img.paste(st, (int(cx - st.width / 2), int(cy - st.height / 2)), st)

def sp(page, sel):
    return memo.spans(page, sel)

def save(img, i):
    img.convert("RGB").save(OUT / f"slide_{i:02d}.png"); print("slide", i)

if __name__ == "__main__":
    SRC_MEMO = "Source: Joint Chiefs of Staff memo, March 13, 1962. Declassified November 18, 1997."
    LOC = "Photo: Library of Congress"
    HOT = (240, 60, 60)

    def quote(img, q, y, size=66):
        """Cita textual grande, entre comillas rojas."""
        f = F(SERIF, size); d = ImageDraw.Draw(img)
        d.text((X0 - 8, y - 18), "“", font=F(SERIF, size * 2), fill=HOT)
        return text(img, q, y + int(size * 0.9), size)

    def dark_bg():
        return vignette(grain(Image.new("RGB", (W, H), (14, 14, 14)), 14))

    # 1. Gancho (tambien es la portada en el feed)
    img = photo("p00.png", 0.5, 0.33, 1.05, dark=0.2, blur=4); label(img, 1)
    stamp(img, "TOP SECRET", 520, 360, size=116, angle=-9)
    panel(img, 520, 1260, 170)
    y = text(img, "In 1962, America's military chiefs proposed staging attacks on Americans", 560, 86)
    y = text(img, "…and blaming Cuba.", y + 24, 86, fill=HOT)
    text(img, "Swipe →", y + 70, 44, font=MONO, fill=PAPER)
    source(img, SRC_MEMO); save(img, 1)

    # 2. Nombre clave
    img = dark_bg(); label(img, 2)
    card = paper_crop("p01", (520, 330, 1420, 640), sp("p01", [(7, 0, None)]), width=900, angle=1.2)
    img.paste(card, (60, 260), card)
    y = text(img, "The plan's code name:", 760, 70)
    text(img, "NORTHWOODS", y + 20, 150, font=MONO, fill=HOT, stroke=6)
    source(img, SRC_MEMO); save(img, 2)

    # 3. Quien lo firmo y a quien
    img = dark_bg(); label(img, 3)
    card = paper_crop("p00", (150, 230, 1560, 640), sp("p00", [(2, 2, 4), (3, 0, None), (4, 1, None)]), width=960, angle=-1.0)
    img.paste(card, (30, 210), card)
    card2 = paper_crop("p00", (560, 1440, 1560, 1810), [(830, 1590, 1440, 1730)], width=700, angle=1.5)
    img.paste(card2, (330, 760), card2)
    y = text(img, "March 13, 1962.", 1150, 70, fill=HOT)
    text(img, "Signed by Gen. Lyman Lemnitzer, chairman of the Joint Chiefs, and sent to the Secretary of Defense.", y + 6, 52)
    source(img, SRC_MEMO); save(img, 3)

    def pretext(i, n, bg, q, crops, src, extra=None):
        """Etiqueta, cita textual grande y el memo como prueba, centrados en la zona que no tapa la interfaz."""
        img = bg; label(img, i)
        cards = [paper_crop(page, box, sp(page, sel), width=980, angle=ang) for page, box, sel, ang in crops]
        tag = f"Pretext #{n}" if n else extra
        h_tag = len(wrap(tag, F(MONO, 54), X1 - X0)) * int(54 * 1.18)
        h_q = int(66 * 0.9) + len(wrap(q, F(SERIF, 66), X1 - X0)) * int(66 * 1.18)
        total = h_tag + 10 + h_q + 30 + sum(c.height + 10 for c in cards)
        y0 = max(TOP + 30, int(TOP + (BOTTOM - 60 - TOP - total) / 2))
        panel(img, y0 - 40, y0 + h_tag + h_q + 60, 165)
        y = text(img, tag, y0, 54, font=MONO, fill=HOT)
        y = quote(img, q, y + 10) + 30
        for card in cards:
            img.paste(card, (20, y), card); y += card.height + 10
        source(img, src); save(img, i)

    # 4. Pretexto 1
    pretext(4, 1, photo("loc/gitmo_aerial.tif", 0.2, 0.62, 1.0, dark=0.6),
            "We could blow up a US ship in Guantanamo Bay and blame Cuba.",
            [("p10", (240, 890, 1460, 1100), [(14, 1, None), (16, 1, None), (17, 0, None)], -1.2)],
            SRC_MEMO + " " + LOC + " (Guantanamo Bay, 1963).")

    # 5. La referencia: el Maine
    img = photo("loc/maine1.tif", 0.62, 0.5, 1.0, dark=0.6); label(img, 5)
    panel(img, 150, 760, 160)
    y = text(img, "Why \"Remember the Maine\"?", 210, 70, fill=HOT)
    text(img, "In 1898, the USS Maine exploded in Havana harbor. \"Remember the Maine!\" became the battle cry for war with Spain.", y + 10, 58)
    source(img, LOC + " (wreck of the Maine, Havana, 1898)."); save(img, 5)

    # 6. Funerales y titulares
    pretext(6, 0, dark_bg(), "Conduct funerals for mock-victims… Casualty lists in US newspapers would cause a helpful wave of national indignation.",
            [("p10", (330, 570, 1460, 690), [(8, 2, 2), (9, 0, 0)], 1.0), ("p10", (290, 1640, 1290, 1800), [(29, 1, 1), (30, 0, None)], -1.3)],
            SRC_MEMO, extra="They planned the funerals")

    # 7. Pretexto 2: terror en casa
    pretext(7, 2, photo("loc/gitmo_guards.tif", 0.5, 0.5, 1.0, dark=0.45),
            "We could develop a Communist Cuban terror campaign in the Miami area, in other Florida cities and even in Washington.",
            [("p10", (240, 1800, 1460, 1915), [(31, 1, 1), (32, 0, None)], 1.1)],
            SRC_MEMO + " " + LOC + " (Guantanamo, 1962).")

    # 8. Pretexto 3: el avion de pasajeros
    pretext(8, 3, dark_bg(),
            "…a Cuban aircraft has attacked and shot down a chartered civil airliner… The passengers could be a group of college students.",
            [("p12", (260, 370, 1600, 720), [(5, 1, None), (6, 0, None), (7, 0, None), (10, 0, None)], -1.0)],
            SRC_MEMO)

    # 9. El dron
    pretext(9, 0, dark_bg(),
            "The actual registered aircraft would be converted to a drone… triggered by radio signal.",
            [("p12", (260, 1110, 1600, 1260), [(19, 1, 1), (20, 0, None)], 1.0), ("p12", (260, 1820, 1600, 1920), [(32, 0, None), (33, 0, 0)], -1.2)],
            SRC_MEMO, extra="The real passengers would land in secret")

    # 10. Kennedy dice que no
    img = photo("loc/jfk_lemnitzer.tif", 0.6, 0.45, 1.0, dark=0.6); label(img, 10)
    panel(img, 150, 700, 160)
    y = text(img, "Kennedy rejected the plan.", 210, 84, fill=HOT)
    text(img, "That same year, Lemnitzer was replaced as chairman of the Joint Chiefs.", y + 10, 58)
    source(img, LOC + " (Kennedy with Gen. Lemnitzer, right, 1961)."); save(img, 10)

    # 11. 35 anos en secreto + invitacion
    img = photo("p13.png", 0.5, 0.4, 1.05, dark=0.22, blur=3); label(img, 11)
    stamp(img, "DECLASSIFIED", 540, 420, size=104, angle=-8)
    panel(img, 600, 1300, 150)
    y = text(img, "It stayed secret for 35 years.", 640, 84)
    y = text(img, "Released on November 18, 1997.", y + 10, 58, fill=HOT)
    text(img, "What else is still classified?\nFollow for more declassified files.", y + 70, 54)
    source(img, SRC_MEMO); save(img, 11)
