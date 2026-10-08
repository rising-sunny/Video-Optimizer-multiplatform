"""Portada de periodico de epoca para la toma 3D "periodico que gira" (PIL).

La cabecera lleva el nombre del CANAL (nunca el de un diario real). El titular sale
del rotulo que se escriba en el timeline, si no del titulo o tema del video; la bajada,
de la narracion de la escena; la fecha, de la que mencione el guion; y las columnas
se llenan con la narracion real del video (en una pausa no se lee relleno sin sentido).
"""

from __future__ import annotations

import hashlib
import os
import re
import textwrap
from typing import Any, Dict, Optional

FONTS_DIR = r"C:\Windows\Fonts"
W, H, M = 1400, 1960, 70
INK = (28, 24, 20)

MASTHEADS = {
    "stunning-facts-of-history": "Stunning Facts of History",
    "stunning-revelations": "Stunning Revelations",
}
_MONTHS_EN = ("january february march april may june july august september october november "
              "december").split()
_MONTHS_ES = ("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre "
              "diciembre").split()
_DATE_EN = re.compile(r"\b(" + "|".join(_MONTHS_EN) + r")\s+(\d{1,2}),?\s+(\d{3,4})\b", re.IGNORECASE)
_DATE_ES = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MONTHS_ES) + r")\s+de\s+(\d{3,4})\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-4][0-9])\b")


def channel_masthead(channel_key: Optional[str] = None) -> str:
    try:
        from channel.channel_profiles import CHANNELS, active_channel
        key = channel_key or active_channel()
    except Exception:
        return MASTHEADS["stunning-revelations"]
    if key in MASTHEADS:
        return MASTHEADS[key]
    handle = str((CHANNELS.get(key) or {}).get("name") or key).lstrip("@")
    return re.sub(r"[-_]+", " ", handle).strip().title() or MASTHEADS["stunning-revelations"]


def find_dateline(*texts: Any) -> str:
    """'JUNE 28, 1914' / '28 DE JUNIO DE 1914' / '1914' / '' segun lo que mencione el texto."""
    for text in texts:
        text = str(text or "")
        match = _DATE_EN.search(text)
        if match:
            return f"{match.group(1).upper()} {int(match.group(2))}, {match.group(3)}"
        match = _DATE_ES.search(text)
        if match:
            return f"{int(match.group(1))} DE {match.group(2).upper()} DE {match.group(3)}"
    for text in texts:
        match = _YEAR.search(str(text or ""))
        if match:
            return match.group(1)
    return ""


def clean_headline(text: Any, max_chars: int = 38) -> str:
    """Titular corto en mayusculas: sin emojis ni hashtags.

    Un titulo con ':' o '|' se parte y se queda con la primera parte de 3+
    palabras (o la mas larga): 'Sarajevo: the day everything changed' da
    'THE DAY EVERYTHING CHANGED', no un 'SARAJEVO' suelto.
    """
    text = re.sub(r"#\w+", "", str(text or ""))
    parts = [p for p in re.split(r"\s[|–—-]\s|[:|]", text) if p.strip()] or [""]
    text = next((p for p in parts if len(p.split()) >= 3), max(parts, key=len))
    text = re.sub(r"[^\w\s,'’.\-!?¿¡áéíóúñüÁÉÍÓÚÑÜ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,-")
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0]
    return text.upper()


def split_headline(headline: str) -> str:
    """Dos renglones parejos ('A|B') si el titular es largo; uno si es corto."""
    words = headline.split()
    if len(headline) <= 14 or len(words) < 2:
        return headline
    best = min(range(1, len(words)),
               key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
    return " ".join(words[:best]) + "|" + " ".join(words[best:])


def front_page_texts(storyboard: Dict[str, Any], segment_text: Any, tag: Any = "") -> Dict[str, str]:
    """Titular, bajada, fecha, epigrafe y cuerpo para la portada de una escena."""
    segments = storyboard.get("segments") or []
    script = storyboard.get("script") or " ".join(
        str(s.get("narration_text") or s.get("text") or "") for s in segments if isinstance(s, dict))
    headline = clean_headline(tag) or clean_headline(storyboard.get("title")) \
        or clean_headline(storyboard.get("topic")) or "EXTRA"
    sentence = re.split(r"(?<=[.!?])\s", str(segment_text or "").strip())[0]
    spanish = str(storyboard.get("language") or "").lower().startswith("es")
    date = find_dateline(segment_text, script)
    edition = "EDICION EXTRA" if spanish else "EXTRA EDITION"
    return {
        "headline": split_headline(headline),
        "deck": sentence[:110],
        "dateline": f"{date}  —  {edition}" if date else edition,
        "caption": "",
        "body": script,
        "masthead": channel_masthead(),
    }


def _font(name: str, size: int):
    from PIL import ImageFont
    for candidate in (name, "timesbd.ttf", "georgiab.ttf"):
        try:
            return ImageFont.truetype(os.path.join(FONTS_DIR, candidate), size)
        except OSError:
            continue
    for linux in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",):
        try:
            return ImageFont.truetype(linux, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit(draw, text, name, max_w, max_size):
    size = max_size
    while size > 20:
        font = _font(name, size)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_w:
            return font
        size -= 4
    return _font(name, size)


def _centered(draw, y, text, font):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((W - (right - left)) / 2 - left, y - top), text, font=font, fill=INK)
    return y + (bottom - top)


def _column(draw, x, y, width, bottom, words, cursor, size=21):
    """Llena una columna con `words` desde `cursor` (y vuelve a empezar si se acaban)."""
    font = _font("BOD_R.TTF", size)
    line_h = int(size * 1.28)
    while y + line_h < bottom and words:
        line = ""
        while True:
            word = words[cursor % len(words)]
            candidate = (line + " " + word).strip()
            if draw.textbbox((0, 0), candidate, font=font)[2] > width and line:
                break
            line = candidate
            cursor += 1
        draw.text((x, y), line, font=font, fill=(55, 50, 44))
        y += line_h
        if line.endswith("."):
            y += line_h // 3      # punto y aparte
    return cursor


def build_front_page(out_path: str, photo: str, texts: Dict[str, str]) -> str:
    """Dibuja la portada (1400x1960) y la guarda en `out_path`."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    rng = np.random.RandomState(3)
    base = np.full((H, W, 3), (232, 222, 198), dtype="float32")
    base += rng.normal(0, 6, (H, W, 1))
    yy, xx = np.mgrid[0:H, 0:W]
    edge = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    base *= (1 - 0.18 * np.clip(edge - 0.55, 0, 1))[..., None]
    page = Image.fromarray(np.clip(base, 0, 255).astype("uint8"))
    draw = ImageDraw.Draw(page)

    small = _font("BASKVILL.TTF", 26)
    draw.text((M, M), "VOL. LXII ..... No. 18,427", font=small, fill=INK)
    price = "PRICE ONE PENNY"
    draw.text((W - M - draw.textbbox((0, 0), price, font=small)[2], M), price, font=small, fill=INK)
    masthead = texts.get("masthead") or MASTHEADS["stunning-revelations"]
    y = _centered(draw, M + 40, masthead, _fit(draw, masthead, "OLDENGL.TTF", W - 2 * M, 170)) + 26
    draw.line((M, y, W - M, y), fill=INK, width=5)
    draw.line((M, y + 9, W - M, y + 9), fill=INK, width=2)
    y = _centered(draw, y + 24, texts.get("dateline", ""), _font("BASKVILL.TTF", 32)) + 22
    draw.line((M, y, W - M, y), fill=INK, width=3)
    y += 28
    for line in str(texts.get("headline") or "EXTRA").split("|"):
        y = _centered(draw, y, line, _fit(draw, line, "BOD_CB.TTF", W - 2 * M, 230)) + 18
    y += 6
    for line in textwrap.wrap(str(texts.get("deck") or ""), 52)[:2]:
        y = _centered(draw, y, line, _font("BOD_I.TTF", 42)) + 10
    y += 18
    draw.line((M, y, W - M, y), fill=INK, width=2)
    y += 26

    pw = 830
    img = ImageOps.autocontrast(ImageOps.grayscale(Image.open(photo)), cutoff=1)
    ph = min(int(pw * img.height / img.width), H - y - 260)
    img = ImageOps.fit(img, (pw, ph))
    sepia = Image.merge("RGB", [img.point(lambda v: min(255, v * 1.02 + 6)),
                                img.point(lambda v: v * 0.95 + 4), img.point(lambda v: v * 0.82)])
    page.paste(sepia, (M, y))
    draw.rectangle((M - 1, y - 1, M + pw, y + ph), outline=INK, width=2)
    cap_y = y + ph + 12
    for line in textwrap.wrap(str(texts.get("caption") or ""), 62)[:2]:
        draw.text((M, cap_y), line, font=_font("BOD_I.TTF", 24), fill=INK)
        cap_y += 30

    words = re.sub(r"\s+", " ", str(texts.get("body") or "")).split() or ["..."]
    right_x = M + pw + 30
    draw.line((right_x - 15, y, right_x - 15, H - M), fill=(90, 84, 76), width=1)
    cursor = _column(draw, right_x, y, W - M - right_x, H - M, words, 0)
    top = cap_y + 20
    col_w = (pw - 30) // 2
    cursor = _column(draw, M, top, col_w, H - M, words, cursor)
    draw.line((M + col_w + 15, top, M + col_w + 15, H - M), fill=(90, 84, 76), width=1)
    _column(draw, M + col_w + 30, top, col_w, H - M, words, cursor)

    page.filter(ImageFilter.GaussianBlur(0.6)).save(out_path)
    return out_path


def cached_front_page(cache_dir: str, photo: str, texts: Dict[str, str]) -> str:
    """La misma portada siempre en la misma ruta (para que el cache de la toma 3D sirva)."""
    st = os.stat(photo)
    key = hashlib.sha1(repr((sorted(texts.items()), photo, st.st_size, int(st.st_mtime))).encode("utf-8"))
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, f"front_{key.hexdigest()[:14]}.png")
    if not os.path.exists(out):
        build_front_page(out, photo, texts)
    return out
