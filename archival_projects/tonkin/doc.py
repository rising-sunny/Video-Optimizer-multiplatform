"""Documental 16:9 'The Gulf of Tonkin' (Stunning Revelations): narracion + archivo real + memo, efectos tipo Catarsis.
Uso: python doc.py sheet | audio | video | all      (siempre escribe timeline.json, tonkin.srt y chapters.txt)"""
import json, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
from script import SCRIPT, NW, WV, PC20, PC06, MAD, SH, MA, VA
import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()
Image.MAX_IMAGE_PIXELS = None
W, H, FPS, SR = 1920, 1080, 30, 48000
CARD, END, LEAD, TAIL = 3.0, 10.0, 0.25, 0.45
SERIF = "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"
MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"
F = lambda p, s: ImageFont.truetype(p, s)
RED, HOT = (186, 14, 22), (240, 60, 60)
rng = np.random.default_rng(1962)

MEMO = "NSA, Cryptologic Quarterly (2001) · declassified 2005"
CREDIT = {WV: "\"Why Vietnam?\" · U.S. Department of Defense, 1965", PC20: "Pentagon press conference, August 1964 · U.S. Army (NARA)",
          PC06: "Pentagon press conference, August 1964 · U.S. Army (NARA)", MAD: "USS Maddox, 1954 · U.S. Navy (NARA)",
          SH: "Universal Newsreel, February 1965", MA: "Universal Newsreel, April 1965", VA: "Universal Newsreel, December 1965"}
PHOTO = {}
ILLUSTRATIVE = {2, 4}      # capitulos donde el archivo de 1965 ilustra hechos de 1964


# ---------------------------------------------------------------- linea de tiempo
def load_audio(path):
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)

def timeline():
    tl, f, chap = [], 0, 0
    for i, item in enumerate(SCRIPT):
        if item[0] == "card":
            n = round(CARD * FPS)
            if item[1][0].isdigit():
                chap = int(item[1].split()[0])
            tl.append(dict(kind="card", title=item[1], f0=f, nf=n, chap=chap)); f += n
            continue
        v = load_audio(f"tts/b{i:02d}.mp3")
        lead = 0.8 if i == 0 else LEAD
        n = round((lead + len(v) / SR + TAIL) * FPS)
        shots, neg = [], False
        for vis in item[1]:
            if vis[0] == "neg":
                neg = True; continue
            shots.append(dict(vis=list(vis), neg=neg)); neg = False
        while len(shots) > 1 and n / len(shots) < 2.2 * FPS:
            shots.pop()
        cuts = [round(n * k / len(shots)) for k in range(len(shots) + 1)]
        for k, s in enumerate(shots):
            s.update(f0=f + cuts[k], nf=cuts[k + 1] - cuts[k], chap=chap)
        tl.append(dict(kind="beat", i=i, f0=f, nf=n, voice_at=f / FPS + lead, voice=v, chap=chap, shots=shots,
                       subs=json.load(open(f"tts/b{i:02d}.mp3.json")))); f += n
    tl.append(dict(kind="card", title="END", f0=f, nf=round(END * FPS), chap=8))
    return tl


# ---------------------------------------------------------------- textos: SRT y capitulos
def ts(t, srt=True):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}" if srt else (f"{m}:{int(s):02d}" if not h else f"{h}:{m:02d}:{int(s):02d}")

def chunks(text, maxc=84):
    out, cur = [], ""
    for w in text.split():
        if cur and len(cur) + len(w) + 1 > maxc:
            out.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    return out + [cur]

def write_texts(tl):
    srt, k = [], 1
    for b in (x for x in tl if x["kind"] == "beat"):
        for s in b["subs"]:
            parts, t = chunks(s["text"]), b["voice_at"] + s["start"]
            tot = sum(len(p) for p in parts)
            for p in parts:
                d = s["dur"] * len(p) / tot
                srt.append(f"{k}\n{ts(t)} --> {ts(t + d - 0.04)}\n{p}\n"); k += 1; t += d
    open("tonkin.srt", "w").write("\n".join(srt))
    ch = ["0:00 August 4, 1964"]
    for c in tl:
        if c["kind"] == "card" and c["title"][0].isdigit():
            n, title = c["title"].split(" · ")
            ch.append(f"{ts(c['f0'] / FPS, False)} {n}. {title.title().replace('Ninety', 'Ninety')}")
    ch.append(f"{ts(tl[-1]['f0'] / FPS - 0.5, False)} Sources")
    open("chapters.txt", "w").write("\n".join(ch) + "\n")
    print("\n".join(ch))


# ---------------------------------------------------------------- imagenes base
VIG = None; VIGP = None; NOISE = None

def init_fx():
    global VIG, VIGP, NOISE
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    VIG = np.clip(1 - 0.32 * np.clip(r - 0.55, 0, None), 0, 1)[..., None].astype(np.float32)
    VIGP = np.clip(1 - 0.12 * np.clip(r - 0.7, 0, None), 0, 1)[..., None].astype(np.float32)   # papel: casi plano, sin ovalo
    NOISE = rng.normal(0, 7, (12, H, W)).astype(np.float32)

TINT = np.array([0.93, 0.97, 1.0], np.float32)

def post(a, k, flick=0.0):
    f = (a[..., None] * TINT if a.ndim == 2 else a.astype(np.float32)) * (VIG if flick else VIGP)
    if flick:
        f *= 1 + flick * (np.sin(k * 1.7) * 0.5 + np.sin(k * 0.61) * 0.5)
    f += NOISE[k % len(NOISE)][..., None]
    return np.clip(f, 0, 255).astype(np.uint8)

def box16(size, cx, cy, cw):
    w, h = size
    cw = min(cw, w, h * 16 / 9); ch = cw * 9 / 16
    left = min(max(cx - cw / 2, 0), w - cw); top = min(max(cy - ch / 2, 0), h - ch)
    return (left, top, left + cw, top + ch)

def lerp_box(a, b, p):
    return tuple(x + (y - x) * p for x, y in zip(a, b))

def ease(p):
    return p * p * (3 - 2 * p)

def paper(pg):
    im = Image.open(f"{NW}/{pg}.png").convert("RGB")
    ink = np.asarray(im)
    pap = Image.blend(im, Image.new("RGB", im.size, (236, 226, 200)), 0.2)
    return Image.fromarray(np.minimum(np.asarray(pap), ink))

def line_boxes(pg, ranges):
    """Lineas de texto cuyo centro cae en los rangos (fraccion del alto de la pagina) -> cajas a resaltar."""
    a = np.asarray(Image.open(f"{NW}/{pg}.png").convert("L")) < 128
    a = a & (a.mean(0) < 0.08)[None, :]                # fuera las franjas de ruido del margen del escaneo
    h, w = a.shape; xs0, xs1 = int(0.06 * w), int(0.96 * w)
    rows = a[:, xs0:xs1].sum(1) > (8 if pg == "p13" else 3)   # p13 tiene mas manchas
    runs, y = [], 0
    while y < h:
        if rows[y]:
            s = y
            while y < h and (rows[y] or rows[y:y + 3].any()):
                y += 1
            if y - s >= 14:
                runs.append((s, y))
        y += 1
    out = []
    for y0f, y1f in ranges:
        for s, e in runs:
            if y0f * h <= (s + e) / 2 <= y1f * h:
                cols = np.nonzero(a[s:e, xs0:xs1].sum(0) >= 2)[0]
                if len(cols):
                    out.append((xs0 + cols[0], s, xs0 + cols[-1], e))
    return out

def highlight(im, boxes):
    hl = Image.new("RGB", im.size, (255, 255, 255)); d = ImageDraw.Draw(hl)
    for x0, y0, x1, y1 in boxes:
        d.rectangle((x0 - 8, y0 - 8, x1 + 8, y1 + 8), fill=(245, 110, 110))
    return Image.fromarray((np.asarray(im).astype(np.uint16) * np.asarray(hl) // 255).astype(np.uint8))

def stamp(img, s, cx, cy, size=150, angle=-10, alpha=215):
    f = F(MONO, size); tw = int(f.getlength(s)) + 70; th = size + 70
    st = Image.new("RGBA", (tw, th), (0, 0, 0, 0)); d = ImageDraw.Draw(st)
    d.rectangle((7, 7, tw - 7, th - 7), outline=RED + (alpha,), width=12)
    d.text((35, 26), s, font=f, fill=RED + (alpha,))
    a = np.asarray(st).copy()
    holes = np.random.default_rng(7).random(a.shape[:2]) < 0.22
    a[..., 3] = np.where(holes, (a[..., 3] * 0.35).astype(np.uint8), a[..., 3])
    st = Image.fromarray(a).rotate(angle, expand=True, resample=Image.BICUBIC)
    img = img.copy(); img.paste(st, (int(cx - st.width / 2), int(cy - st.height / 2)), st)
    return img

def credit_layer(text):
    if not text:
        return None
    f = F(MONO, 26); tw = int(f.getlength(text)) + 40
    im = Image.new("RGBA", (tw, 50), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.text((22, 12), text, font=f, fill=(0, 0, 0, 200)); d.text((20, 10), text, font=f, fill=(235, 232, 225, 205))
    a = np.asarray(im).astype(np.float32) / 255
    return a[..., :3] * 255, a[..., 3:]

def put_credit(frame, cl):
    if cl is None:
        return frame
    rgb, al = cl; h, w = al.shape[:2]; y, x = H - 40 - h, 50
    reg = frame[y:y + h, x:x + w].astype(np.float32)
    frame[y:y + h, x:x + w] = (reg * (1 - al) + rgb * al).astype(np.uint8)
    return frame


# ---------------------------------------------------------------- planos
_cache = {}

def cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]

def read_video(path, a, secs):
    pre = "crop=1440:1080:240:0," if path == PC06 else ""          # esa copia viene en 1080p con bandas negras
    vf = pre + "yadif=deint=1,scale=960:720,setsar=1,crop=960:540:0:63,fps=30,format=gray"
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{a:.3f}", "-i", path, "-t", f"{secs:.3f}", "-vf", vf,
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 540, 960)
    lo, hi = np.percentile(fr[::max(1, len(fr) // 8)], (1, 99.5))
    lut = np.clip((np.arange(256) - lo) * 255 / max(hi - lo, 40), 0, 255).astype(np.uint8)
    return lut[fr]

def shot_frames(s, idx, only=None):
    """Genera (frame_sin_post, es_archivo) para el plano s. only: lista de indices locales a generar (hoja de contacto)."""
    v, nf = s["vis"], s["nf"]
    want = range(nf) if only is None else only
    kind = v[0]
    if kind == "v":
        _, path, a, z = v
        secs = min(z - a, nf / FPS + 0.2) if only is None else z - a
        fr = read_video(path, a, secs)
        k = len(fr)
        for j in want:
            g = fr[min(j, k - 1)] if k >= nf else fr[min(int(j * k / nf), k - 1)]
            zm = 1 + 0.05 * (j / nf)
            cw, ch = 960 / zm, 540 / zm
            yield np.asarray(Image.fromarray(g).resize((W, H), Image.BILINEAR, box=((960 - cw) / 2, (540 - ch) / 2, (960 + cw) / 2, (540 + ch) / 2))), True
        return
    if kind == "ph":
        name = os.path.basename(v[1]).split(".")[0]
        def load():
            im = ImageOps.autocontrast(Image.open(f"{NW}/loc/{name}_hi.png").convert("L"), cutoff=1)
            b = box16(im.size, im.width / 2, im.height * 0.45, im.width)
            return im.resize((2880, 1620), Image.LANCZOS, box=b)
        im = cached(name, load)
        full, tight = (0, 0, 2880, 1620), box16((2880, 1620), 1440 * (1 + 0.04 * (-1) ** idx), 790, 2880 / 1.1)
        a, b = (full, tight) if idx % 2 == 0 else (tight, full)
        for j in want:
            yield np.asarray(im.resize((W, H), Image.BILINEAR, box=lerp_box(a, b, ease(j / nf)))), True
        return
    if kind == "txt":
        im = cached("txt" + v[1] + v[2], lambda: txt_image(v[1], v[2]))
        a, b = (0, 0, im.width, im.height), box16(im.size, im.width / 2, im.height / 2, im.width / 1.08)
        for j in want:
            yield np.asarray(im.resize((W, H), Image.BICUBIC, box=lerp_box(a, b, ease(j / nf)))), False
        return
    if kind == "pgk":
        im = cached("pgk" + v[2], lambda: Image.open(f"{v[1]}/{v[2]}.png").convert("RGB"))
        fx, fy, z = json.load(open(f"{v[1]}/focus.json"))[v[2]]
        cw = im.width * min(0.88, 1.25 / z)
        a, b = box16(im.size, fx * im.width, fy * im.height, cw * 1.12), box16(im.size, fx * im.width, fy * im.height, cw * 0.94)
        for j in want:
            yield np.asarray(im.resize((W, H), Image.BICUBIC, box=lerp_box(a, b, ease(j / nf)))), False
        return
    if kind in ("pg", "doc"):
        pg, ranges = (v[1], v[2]) if kind == "pg" else (f"pg/{v[1]}", v[2])
        key = f"pg{pg}{ranges}"
        def load():
            base = paper(pg); bx = line_boxes(pg, ranges) if kind == "pg" else phrase_boxes(v[1], v[2])
            return base, highlight(base, bx), bx
        base, hl, bx = cached(key, load)
        x0 = min(b[0] for b in bx); x1 = max(b[2] for b in bx); y0 = min(b[1] for b in bx); y1 = max(b[3] for b in bx)
        cw = max(x1 - x0 + 160, (y1 - y0 + 220) * 16 / 9, 0.45 * base.width)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        a, b = box16(base.size, cx, cy, cw * 1.15), box16(base.size, cx, cy, cw)
        wipe = int(0.7 * FPS)
        for j in want:
            bb = lerp_box(a, b, ease(j / nf))
            fh = np.asarray(hl.resize((W, H), Image.BICUBIC, box=bb))
            if j >= wipe + 6:
                yield fh, False; continue
            fb = np.asarray(base.resize((W, H), Image.BICUBIC, box=bb))
            if j < 6:
                yield fb, False; continue
            xc = x0 - 10 + (x1 - x0 + 20) * (j - 6) / wipe
            xo = int((xc - bb[0]) * W / (bb[2] - bb[0]))
            out = fb.copy(); out[:, :max(0, xo)] = fh[:, :max(0, xo)]
            yield out, False
        return
    if kind == "stamp":
        pg, text = v[1], v[2]
        def load():
            base = paper(pg)
            return base, stamp(base, text, base.width * 0.5, base.height * 0.3)
        base, st = cached(f"st{pg}{text}", load)
        a, b = box16(base.size, base.width / 2, base.height * 0.3, base.width), box16(base.size, base.width / 2, base.height * 0.3, base.width * 0.86)
        slam = 12
        for j in want:
            bb = lerp_box(a, b, ease(j / nf))
            if slam <= j < slam + 3:
                dx = (8, -6, 3)[j - slam]; sx = 1 + 2 * 12 / (bb[2] - bb[0])     # sacudida: zoom leve + corrimiento dentro de la pagina
                cx, cy, hw, hh = (bb[0] + bb[2]) / 2 + dx, (bb[1] + bb[3]) / 2 - dx, (bb[2] - bb[0]) / 2 / sx, (bb[3] - bb[1]) / 2 / sx
                bb = box16(base.size, cx, cy, 2 * hw)
            yield np.asarray((st if j >= slam else base).resize((W, H), Image.BICUBIC, box=bb)), False
        return
    raise ValueError(kind)

def norm(w):
    return "".join(c for c in w.lower() if c.isalnum())

def phrase_boxes(page, phrase):
    """Cajas por linea de la frase en la pagina OCR (tesseract TSV); une las palabras cortadas con guion."""
    rows = [r.split("\t") for r in open(f"pg/{page}.tsv").read().splitlines()[1:]]
    words = [(r[11], (int(r[2]), int(r[3]), int(r[4])), (int(r[6]), int(r[7]), int(r[6]) + int(r[8]), int(r[7]) + int(r[9])))
             for r in rows if len(r) == 12 and r[0] == "5" and r[11].strip()]
    toks, i = [], 0
    while i < len(words):
        t, key, bx = words[i]
        if t.endswith("-") and i + 1 < len(words) and words[i + 1][1] != key:
            toks.append((norm(t) + norm(words[i + 1][0]), [(key, bx), (words[i + 1][1], words[i + 1][2])])); i += 2
        else:
            toks.append((norm(t), [(key, bx)])); i += 1
    P = [norm(w) for w in phrase.split() if norm(w)]
    P = [p for p in P]
    best, bi = -1, 0
    for i in range(len(toks)):
        sc = sum(1 for k, p in enumerate(P) if i + k < len(toks) and (toks[i + k][0] == p or (len(p) > 3 and p in toks[i + k][0])))
        if sc > best:
            best, bi = sc, i
    assert best >= 0.6 * len(P), (page, phrase, best, len(P))
    lines = {}
    for t, parts in toks[bi:bi + len(P)]:
        for key, (x0, y0, x1, y1) in parts:
            l = lines.setdefault(key, [x0, y0, x1, y1])
            l[0], l[1], l[2], l[3] = min(l[0], x0), min(l[1], y0), max(l[2], x1), max(l[3], y1)
    return [tuple(b) for b in sorted(lines.values(), key=lambda b: b[1])]

def txt_image(title, line):
    """Tarjeta tipo documento: papel envejecido y maquina de escribir (texto real de la resolucion o de la votacion)."""
    im = Image.new("RGB", (2880, 1620), (232, 222, 196)); d = ImageDraw.Draw(im)
    a = np.asarray(im).astype(np.int16) + rng.normal(0, 6, (1620, 2880, 1)).astype(np.int16)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
    def center(t, y, font, fill):
        d.text(((2880 - d.textlength(t, font=font)) / 2, y), t, font=font, fill=fill)
    center(title, 560, F(MONO, 150), (28, 26, 24))
    f = F(MONO, 96 if len(line) < 20 else 74)
    y = 820
    for ln in wrap(d, ("“" + line + "”") if len(line) > 20 else line, f, 2400):
        center(ln, y, f, RED); y += 120
    return im

def credit_for(s):
    v = s["vis"]
    if v[0] == "txt":
        return "Southeast Asia (Gulf of Tonkin) Resolution, H.J. Res. 1145, August 1964"
    if v[0] == "pgk":
        return "Joint Chiefs of Staff memo, 13 March 1962 · declassified 1997"
    if v[0] == "v":
        c = CREDIT[v[1]]
        ill = v[1] in (SH, VA, MA, MAD) or (v[1] == WV and s["chap"] == 1)   # archivo de otra fecha que ilustra 1964
        return c + (" · illustrative" if ill else "")
    if v[0] == "ph":
        return PHOTO[os.path.basename(v[1]).split(".")[0]] + " · Library of Congress"
    return MEMO


# ---------------------------------------------------------------- tarjetas
def wrap(d, text, font, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if cur and d.textlength(t, font=font) > maxw:
            lines.append(cur); cur = w
        else:
            cur = t
    return lines + [cur]

def card_image(title):
    im = Image.new("RGB", (W, H), (10, 10, 10)); d = ImageDraw.Draw(im)
    def center(t, y, font, fill):
        d.text(((W - d.textlength(t, font=font)) / 2, y), t, font=font, fill=fill)
    if title == "THE GULF OF TONKIN":
        center("THE GULF", 330, F(MONO, 150), (238, 236, 230))
        center("OF TONKIN", 500, F(MONO, 150), HOT)
        d.rectangle((560, 700, 1360, 706), fill=RED)
        center("4 AUGUST 1964  ·  THE ATTACK THAT NEVER HAPPENED", 740, F(MONO, 34), (190, 186, 178))
    elif title == "END":
        center("STUNNING REVELATIONS", 280, F(MONO, 84), (238, 236, 230))
        d.rectangle((660, 400, 1260, 405), fill=RED)
        y = 450
        for t in ["Sources", "R. J. Hanyok, \"Skunks, Bogies, Silent Hounds, and the Flying Fish\", NSA Cryptologic Quarterly (2001)",
                  "declassified by the NSA, 30 November 2005 · National Security Archive",
                  "Southeast Asia Resolution, H.J. Res. 1145 (1964) · Congressional Record",
                  "\"Why Vietnam?\" (DoD, 1965) · U.S. Army and U.S. Navy films (NARA) · Universal Newsreel",
                  "J. Stockdale, In Love and War (1984) · The Fog of War (2003)"]:
            center(t, y, F(MONO, 40 if t == "Sources" else 28), HOT if t == "Sources" else (200, 196, 188)); y += 60
    else:
        n, t = title.split(" · ")
        center(f"CHAPTER {n}", 380, F(MONO, 46), HOT)
        f = F(SERIF, 110); y = 460
        for line in wrap(d, t, f, 1600):
            center(line, y, f, (240, 238, 232)); y += 128
        d.rectangle((860, y + 30, 1060, y + 35), fill=RED)
    return np.asarray(im)

def glitch(a, amt, r):
    out = a.copy(); s = int(amt)
    out[..., 0] = np.roll(a[..., 0], s, 1); out[..., 2] = np.roll(a[..., 2], -s, 1)
    for _ in range(5):
        y = int(r.integers(0, H - 60)); h = int(r.integers(8, 60))
        out[y:y + h] = np.roll(out[y:y + h], int(r.integers(-90, 90)), 1)
    return out

def card_frames(c, only=None):
    img = card_image(c["title"]); nf = c["nf"]; r = np.random.default_rng(c["f0"])
    end = c["title"] == "END"
    for j in (range(nf) if only is None else only):
        if not end and j < 2:
            yield np.full((H, W, 3), 245, np.uint8); continue          # destello blanco (1 por tarjeta)
        g = j - 2
        yield (glitch(img, 26 * (1 - g / 7), r) if (g < 7 and not end) else img)


# ---------------------------------------------------------------- render
def frames(tl, only_mid=False):
    """Recorre la linea de tiempo; devuelve (frame_final, frame_global)."""
    sidx = 0
    for item in tl:
        if item["kind"] == "card":
            only = [item["nf"] // 2] if only_mid else None
            for j, fr in zip(only or range(item["nf"]), card_frames(item, only)):
                yield post(fr, item["f0"] + j), item["f0"] + j
            continue
        for s in item["shots"]:
            cl = credit_layer(credit_for(s)); only = [int(s["nf"] * 0.7)] if only_mid else None
            for j, (fr, arch) in zip(only or range(s["nf"]), shot_frames(s, sidx, only)):
                if s["neg"] and j < 3:
                    fr = glitch(255 - (fr if fr.ndim == 3 else np.repeat(fr[..., None], 3, 2)), 20, rng)
                yield put_credit(post(fr, s["f0"] + j, 0.035 if arch else 0.0), cl), s["f0"] + j
            sidx += 1

def sheet(tl):
    th = []
    for fr, f in frames(tl, only_mid=True):
        im = Image.fromarray(fr).resize((480, 270)); ImageDraw.Draw(im).text((8, 6), f"{f / FPS:.0f}s", fill=(255, 255, 0))
        th.append(im)
    cols = 6
    for p in range(0, len(th), 60):
        part = th[p:p + 60]; rows = (len(part) + cols - 1) // cols
        sh = Image.new("RGB", (cols * 480, rows * 270))
        for k, im in enumerate(part):
            sh.paste(im, (k % cols * 480, k // cols * 270))
        sh.save(f"sheet_doc_{p // 60}.png"); print("sheet", p // 60, len(part))

def video(tl):
    total = tl[-1]["f0"] + tl[-1]["nf"]
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "video_only.mp4"],
                           stdin=subprocess.PIPE)
    for fr, f in frames(tl):
        fade = min(1.0, f / 15, (total - 1 - f) / 30)
        if fade < 1:
            fr = (fr * max(fade, 0)).astype(np.uint8)
        enc.stdin.write(fr.tobytes())
        if f % 900 == 0:
            print(f"video {f / FPS:.0f}/{total / FPS:.0f}s", flush=True)
    enc.stdin.close(); enc.wait()


# ---------------------------------------------------------------- audio: voz + musica ad hoc
def audio(tl):
    from scipy.signal import butter, sosfilt
    total = tl[-1]["f0"] + tl[-1]["nf"]; N = int(total / FPS * SR) + SR
    t = np.arange(N, dtype=np.float32) / SR
    voice = np.zeros(N, np.float32)
    for b in (x for x in tl if x["kind"] == "beat"):
        s = int(b["voice_at"] * SR); voice[s:s + len(b["voice"])] += b["voice"]
    voice *= 0.89 / np.abs(voice).max()
    # intensidad por capitulo (0 = apertura) y eventos
    inten = np.zeros(N, np.float32)
    lvl = {0: 0.8, 1: 0.5, 2: 0.6, 3: 0.65, 4: 1.0, 5: 0.75, 6: 0.55, 7: 0.6, 8: 0.7}
    for x in tl:
        s = int(x["f0"] / FPS * SR); inten[s:] = lvl[x["chap"]]
    inten = np.convolve(inten, np.ones(SR * 2, np.float32) / (SR * 2), "same")
    hits = [x["f0"] / FPS for x in tl if x["kind"] == "card"]
    hits += [s["f0"] / FPS + 0.1 for b in tl if b["kind"] == "beat" for s in b["shots"] if s["neg"]]
    hits += [s["f0"] / FPS + 12 / FPS for b in tl if b["kind"] == "beat" for s in b["shots"] if s["vis"][0] == "stamp"]
    risers = [x["f0"] / FPS for x in tl if x["kind"] == "card" and x["title"] != "END"]
    r = np.random.default_rng(5)
    lp = lambda x, fc, o=2: sosfilt(butter(o, fc, "low", fs=SR, output="sos"), x).astype(np.float32)
    hp = lambda x, fc: sosfilt(butter(2, fc, "high", fs=SR, output="sos"), x).astype(np.float32)
    # dron grave (La) + viento
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * t / 13)
    drone = (0.5 * np.sin(2 * np.pi * 55 * t) + 0.3 * np.sin(2 * np.pi * 82.41 * t + 1) + 0.18 * np.sin(2 * np.pi * 110.4 * t)) * lfo
    wind = lp(r.normal(0, 1, N).astype(np.float32), 380) * (0.6 + 0.4 * np.sin(2 * np.pi * t / 9 + 2))
    drone = drone + 0.9 * wind / np.abs(wind).max()
    # pad en La menor: Am F Dm E, 8 s por acorde, con detune L/R
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (146.83, 174.61, 220.0), (164.81, 207.65, 246.94)]
    padL, padR = np.zeros(N, np.float32), np.zeros(N, np.float32)
    seg = 8 * SR
    for k, s in enumerate(range(0, N, seg)):
        e = min(N, s + seg + 2 * SR); tt = t[s:e] - t[s]
        env = np.sin(np.pi * np.clip(tt / ((e - s) / SR), 0, 1)) ** 2
        for fq in chords[k % 4]:
            for h, amp in ((1, 1.0), (2, 0.35), (3, 0.12)):
                padL[s:e] += amp * env * np.sin(2 * np.pi * fq * h * 0.997 * tt)
                padR[s:e] += amp * env * np.sin(2 * np.pi * fq * h * 1.003 * tt + 0.5)
    padL, padR = lp(padL, 1600) / 6, lp(padR, 1600) / 6
    # latido (capitulos 4-5) y tic de reloj (2-3)
    beat = np.zeros(N, np.float32); tick = np.zeros(N, np.float32)
    th = np.arange(int(0.25 * SR)) / SR; thump = np.sin(2 * np.pi * 48 * th) * np.exp(-th / 0.07)
    tk = hp(r.normal(0, 1, int(0.008 * SR)).astype(np.float32), 2500) * np.exp(-np.arange(int(0.008 * SR)) / (0.002 * SR))
    for x in tl:
        s0, s1 = x["f0"] / FPS, (x["f0"] + x["nf"]) / FPS
        if x["chap"] in (4, 5):
            for q in np.arange(s0, s1, 60 / 66):
                for off, a in ((0, 1.0), (0.22, 0.6)):
                    i = int((q + off) * SR); beat[i:i + len(thump)] += a * thump[:max(0, N - i)]
        if x["chap"] in (2, 3):
            for q in np.arange(s0, s1, 1.0):
                i = int(q * SR); tick[i:i + len(tk)] += tk[:max(0, N - i)]
    # golpes (tarjetas, negativos, sellos) y subidas antes de cada tarjeta
    fx = np.zeros(N, np.float32)
    hd = np.arange(int(2.2 * SR)) / SR
    boom = np.sin(2 * np.pi * np.cumsum(90 * np.exp(-hd / 0.5) + 33) / SR) * np.exp(-hd / 0.6)
    nb = lp(r.normal(0, 1, len(hd)).astype(np.float32), 900) * np.exp(-hd / 0.12)
    boom = boom + 0.8 * nb / np.abs(nb).max()
    for h in hits:
        i = int(h * SR); fx[i:i + len(boom)] += boom[:max(0, N - i)]
    rl = int(1.6 * SR); rise = hp(r.normal(0, 1, rl).astype(np.float32), 900) * np.linspace(0, 1, rl) ** 3
    for h in risers:
        i = int(h * SR) - rl
        if i > 0:
            fx[i:i + rl] += 0.5 * rise / np.abs(rise).max()
    mono = 0.55 * drone / np.abs(drone).max() * (0.6 + 0.4 * inten) + 0.35 * beat * inten + 0.05 * tick
    L = mono + padL * inten * 0.8 + 0.6 * fx; R = mono + padR * inten * 0.8 + 0.6 * fx
    m = np.stack([L, R], 1); m /= np.abs(m).max()
    # ducking bajo la voz
    win = int(0.05 * SR); env = np.sqrt(np.convolve(voice ** 2, np.ones(win) / win, "same"))
    pres = np.convolve((env > 0.01).astype(np.float32), np.ones(int(0.6 * SR)) / int(0.6 * SR), "same") > 0
    pres = np.convolve(pres.astype(np.float32), np.ones(int(0.3 * SR)) / int(0.3 * SR), "same")
    gain = 0.36 - 0.24 * pres
    mix = m * gain[:, None] + voice[:, None]
    mix /= max(1.0, np.abs(mix).max() / 0.97)
    import soundfile as sf
    sf.write("mix.wav", mix[:int(total / FPS * SR)], SR, subtype="FLOAT")
    print("audio ok", total / FPS)

def mux():
    subprocess.run([FF, "-v", "error", "-y", "-i", "video_only.mp4", "-i", "mix.wav", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
                    "tonkin_documental.mp4"], check=True)
    print("mux ok")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sheet"
    tl = timeline(); write_texts(tl)
    print("duracion", (tl[-1]["f0"] + tl[-1]["nf"]) / FPS)
    init_fx()
    if mode == "sheet":
        sheet(tl)
    if mode in ("audio", "all"):
        audio(tl)
    if mode in ("video", "all", "videomux"):
        video(tl)
    if mode in ("all", "videomux"):
        mux()
