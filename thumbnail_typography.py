# -*- coding: utf-8 -*-
"""Texto de miniatura con impacto, decidido con datos (no a ojo).

Por que (2026-09-23): la regla fija pedia texto "small and restrained" (alto de letra 6%,
peso medio, espaciado amplio, blanco con sombra suave). Medido con vision sobre la
miniatura del caballo mongol: el generador lo achico a 2.6% de alto de letra, peso
regular, sobre un cielo naranja. Se leia, pero no pegaba.

Lo que hacen los que ganan (medido el mismo dia con Gemini sobre las miniaturas de los
60 shorts de historia mas vistos del mes, `trend_report.json`; 47 respondieron):
  - 31/47 llevan texto. Rotulos de 1-3 palabras (13): alto de letra mediano 6%, el
    cuarto superior ~8%; 12/13 en bold/black; 10/13 con contorno grueso o caja detras;
    4/13 con relleno de color (amarillo, naranja, cian).
  - El 2.6% del caballo mongol queda por DEBAJO de las 31 (la mas chica mide 3%).
Historia: la primera version (hasta 2026-09) salio con Impact, contorno grueso y 80% del
ancho, y se paso al extremo minimo. Esto queda en el medio que marcan los datos: negrita
condensada, 7-8% para rotulos, la cifra protagonista mas grande.
Revision visual: el ejemplo HOW resulto tosco por el contorno del 10% y la sombra
dura. Conservamos la escala, pero pedimos lettering de cartel cinematografico,
kerning optico, acabado mate y contraste por el fondo, sin borde de pegatina.

Tres partes:
  1. analyze_text_styles / summarize_text_styles: mide con vision el texto de miniaturas
     reales (palabras, alto de letra por la caja del renglon mas alto, peso, color, contorno).
  2. plan_typography: tamano por cantidad de caracteres (llenar el ancho util sin pasarse),
     jerarquia (la cifra grande, el resto chico), color por contraste WCAG contra el fondo
     que se le pide a la imagen y por tono complementario a la paleta, contorno, y la zona
     coordinada con la composicion. typography_directives(plan) -> texto para el prompt.
  3. check_thumbnail_text: al elegir la miniatura, la lee a tamano completo y a tamano de
     grilla (190 px, recorte 2:3) y mide el alto real de la letra.

    .venv\\Scripts\\python.exe thumbnail_typography.py plan "100 KILOMETERS"
    .venv\\Scripts\\python.exe thumbnail_typography.py check ruta\\miniatura.jpg "100 KILOMETERS"

Ver `test_thumbnail_typography.py`.
"""

from __future__ import annotations

import colorsys
import io
import math
import re
import statistics
import sys
from typing import Any, Callable, Iterable, Optional

# ----------------------------------------------------------------------------
# Metas (ver el docstring: de donde sale cada numero)
# ----------------------------------------------------------------------------
LABEL_CAP_PCT = {"vertical": 8.0, "landscape": 11.0}    # rotulo: el cuarto superior de los ganadores
HERO_CAP_PCT = {"vertical": 11.0, "landscape": 16.0}    # la cifra protagonista, mas grande que el rotulo
MIN_CAP_PCT = {"vertical": 5.0, "landscape": 7.0}       # por debajo, mas chico que la mediana ganadora
USABLE_WIDTH = {"vertical": 0.86, "landscape": 0.38}    # 16:9: el texto vive en el tercio derecho
TEXT_ZONE = {"vertical": (0.11, 0.34), "landscape": (0.20, 0.80)}   # fraccion del alto
SUBJECT_BAND_VERTICAL = (0.34, 0.71)                     # el sujeto debajo del texto, dentro de la banda util
GLYPH_WIDTH = 0.56          # ancho medio de una mayuscula negrita condensada / alto de letra
SPACE_WIDTH = 0.25
LINE_GAP = 1.18             # alto de renglon / alto de letra
OUTLINE_FRACTION = 0.0      # miniatura externa: separar con el fondo, no con un borde grueso
TITLE_FONT = "custom bold condensed display lettering for a cinematic documentary poster"
GRID_WIDTH_PX = 190         # ancho de una miniatura en la grilla de Shorts en un telefono

WHITE = "#FFFFFF"
ACCENTS = {"yellow": "#FFD23F", "cyan": "#5CE1E6", "orange": "#FF8A1E"}
DEFAULT_PALETTE = {"label": "calida (ambar/rojo)", "highlights": ["#f3c267", "#e07a2b", "#b32a1c"],
                   "mids": ["#6a3a1e", "#2f3a44"], "shadows": ["#0e1318", "#1a2330"]}
_NUMBER_RE = re.compile(r"^\d[\d,.]*[KkMm%]?$")


# ----------------------------------------------------------------------------
# 1. Medir miniaturas reales
# ----------------------------------------------------------------------------
ANALYZE_PROMPT = """You are measuring YouTube thumbnails. For EACH image, in order, describe ONLY the
graphic headline text overlaid on the image (ignore watermarks, channel logos, subtitles/captions
burned in from the video, and text that is part of the scene).
Return ONLY a JSON array, one object per image:
{"i": <1-based index>, "has_text": true|false, "text": "<exact headline text>", "words": <int>,
 "lines": <int>, "box_2d": [ymin, xmin, ymax, xmax] of the TALLEST single line of that text,
 normalized 0-1000, "weight": "thin|regular|medium|bold|black", "condensed": true|false,
 "fill": "<main text color name>", "highlight": true|false (one word/number in a different color
 or much bigger), "outline": "none|thin|thick", "shadow": "none|soft|hard",
 "box_behind": true|false (text on a solid band or box), "position": "top|middle|bottom"}
If an image has no headline text: {"i": n, "has_text": false}."""


def _box_metrics(d: dict[str, Any]) -> None:
    box = d.get("box_2d")
    if isinstance(box, list) and len(box) == 4:
        try:
            d["cap_pct"] = round(max(0.0, (float(box[2]) - float(box[0])) / 10.0), 1)
            d["width_pct"] = round(max(0.0, (float(box[3]) - float(box[1])) / 10.0), 1)
        except (TypeError, ValueError):
            pass


def analyze_text_styles(images: list, vision_fn: Callable[[str, list], str], batch: int = 6,
                        log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Mide el texto de cada miniatura (bytes). Una fila por imagen, en orden."""
    from ai.gemini_vision import parse_json
    rows: list[dict[str, Any]] = []
    for start in range(0, len(images), batch):
        chunk = images[start:start + batch]
        try:
            data = parse_json(vision_fn(ANALYZE_PROMPT, chunk))
        except Exception as exc:
            log(f"   [Tipografia] lote {start // batch + 1}: sin respuesta ({exc})")
            rows.extend({"i": start + k + 1, "error": True} for k in range(len(chunk)))
            continue
        by_i = {int(d.get("i", 0)): d for d in data if isinstance(d, dict)}
        for k in range(len(chunk)):
            d = dict(by_i.get(k + 1) or {"has_text": None})
            d["i"] = start + k + 1
            _box_metrics(d)
            rows.append(d)
    return rows


def summarize_text_styles(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Resumen de estilos; `labels` = solo rotulos de 1-3 palabras (el caso de una miniatura)."""
    rows = [r for r in rows if not r.get("error") and r.get("has_text") is not None]
    with_text = [r for r in rows if r.get("has_text")]

    def stats(group: list[dict[str, Any]]) -> dict[str, Any]:
        caps = sorted(r["cap_pct"] for r in group if r.get("cap_pct"))

        def share(pred) -> float:
            return round(sum(1 for r in group if pred(r)) / len(group), 2) if group else 0.0

        fills: dict[str, int] = {}
        for r in group:
            v = str(r.get("fill") or "?").lower()
            fills[v] = fills.get(v, 0) + 1
        return {
            "n": len(group),
            "median_words": statistics.median([int(r.get("words") or 0) for r in group]) if group else 0,
            "median_cap_pct": statistics.median(caps) if caps else None,
            "p75_cap_pct": caps[min(len(caps) - 1, int(len(caps) * 0.75))] if caps else None,
            "heavy_share": share(lambda r: str(r.get("weight")).lower() in ("bold", "black")),
            "outline_or_box_share": share(lambda r: str(r.get("outline")).lower() in ("thin", "thick")
                                          or bool(r.get("box_behind"))),
            "highlight_share": share(lambda r: bool(r.get("highlight"))),
            "fill": dict(sorted(fills.items(), key=lambda kv: -kv[1])),
        }

    out = {"n": len(rows), "with_text": len(with_text),
           "with_text_share": round(len(with_text) / len(rows), 2) if rows else 0.0}
    out.update({k: v for k, v in stats(with_text).items() if k != "n"})   # n = todas, no solo con texto
    out["labels"] = stats([r for r in with_text if 0 < int(r.get("words") or 0) <= 3])
    return out


# ----------------------------------------------------------------------------
# 2. Plan tipografico
# ----------------------------------------------------------------------------
def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def relative_luminance(hex_color: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hex_color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def _hue_saturation(hex_color: str) -> tuple[float, float]:
    h, s, _v = colorsys.rgb_to_hsv(*_rgb(hex_color))
    return h * 360.0, s


def _hue_distance(a: str, b: str) -> float:
    d = abs(_hue_saturation(a)[0] - _hue_saturation(b)[0]) % 360
    return min(d, 360 - d)


def _kind(fmt: Any) -> str:
    return "vertical" if getattr(fmt, "is_vertical", False) else "landscape"


def _chars(line: str) -> float:
    return sum(SPACE_WIDTH if ch == " " else 1.0 for ch in line)


def _fit_cap_pct(line: str, fmt: Any, usable_width: Optional[float] = None,
                 glyph_width: float = GLYPH_WIDTH) -> float:
    """El alto de letra (en % del alto del cuadro) con el que el renglon llena el ancho util."""
    kind = _kind(fmt)
    usable_px = (usable_width or USABLE_WIDTH[kind]) * float(getattr(fmt, "width", 1080))
    height = float(getattr(fmt, "height", 1920))
    # hacia abajo: redondear para arriba lo pasaba del ancho util (87% con tope 86%)
    return math.floor(usable_px / max(1.0, _chars(line) * glyph_width) / height * 1000.0) / 10.0


def _balanced_split(words: list[str]) -> list[str]:
    best, best_len = [" ".join(words)], None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        longest = max(len(a), len(b))
        if best_len is None or longest < best_len:
            best, best_len = [a, b], longest
    return best


def layout_lines(text: str, fmt: Any, usable_width: Optional[float] = None,
                 glyph_width: float = GLYPH_WIDTH, number_hero: bool = True) -> list[dict[str, Any]]:
    """Renglones con su rol: una cifra al frente va sola y grande ('hero'); el resto es rotulo."""
    kind = _kind(fmt)
    words = str(text or "").split()
    if not words:
        return []

    def fit(line: str) -> float:
        return _fit_cap_pct(line, fmt, usable_width, glyph_width)
    if number_hero and _NUMBER_RE.match(words[0]) and len(words) > 1:
        rest = words[1:]
        rest_lines = [" ".join(rest)] if fit(" ".join(rest)) >= LABEL_CAP_PCT[kind] * 0.9 \
            or len(rest) == 1 else _balanced_split(rest)
        return [{"text": words[0], "role": "hero"}] + [{"text": t, "role": "label"} for t in rest_lines]
    if len(words) == 1 or fit(" ".join(words)) >= LABEL_CAP_PCT[kind]:
        return [{"text": " ".join(words), "role": "label"}]
    return [{"text": t, "role": "label"} for t in _balanced_split(words)]


def _most_saturated(colors: Iterable[str]) -> str:
    return max(colors, key=lambda c: _hue_saturation(c)[1])


def choose_accent(palette: dict[str, Any], zone_bg: str, avoid: str = "") -> tuple[str, str, list[str]]:
    """El color de la cifra: tono opuesto al de la imagen y alto contraste con el fondo del texto.
    `avoid`: el color de texto que mas usa la competencia (si hay otro igual de bueno)."""
    ref = _most_saturated(palette.get("highlights") or DEFAULT_PALETTE["highlights"])
    scored = []
    for name, hx in ACCENTS.items():
        score = _hue_distance(hx, ref) + 8.0 * contrast_ratio(hx, zone_bg) - (40.0 if name == avoid else 0.0)
        scored.append((score, name, hx))
    scored.sort(reverse=True)
    _, name, hx = scored[0]
    why = [f"cifra en {name} {hx}: tono opuesto al acento de la imagen ({ref}, a "
           f"{_hue_distance(hx, ref):.0f} grados) y contraste {contrast_ratio(hx, zone_bg)}:1 con el fondo del texto"]
    if avoid and avoid in ACCENTS and name != avoid:
        why.append(f"se evita el {avoid}, el color de texto mas usado por la competencia")
    return name, hx, why


def plan_typography(text: str, fmt: Any, palette: Optional[dict[str, Any]] = None,
                    competitor_text: Optional[dict[str, Any]] = None, *, usable_width: Optional[float] = None,
                    zone: Optional[tuple] = None, glyph_width: float = GLYPH_WIDTH,
                    number_hero: bool = True) -> dict[str, Any]:
    """Renglones con tamano y color, fuente, contorno, zona y los motivos de cada decision.

    usable_width / zone / glyph_width: para otros usos que la miniatura (el texto de gancho del
    video, video_opening, usa todo el ancho arriba y la metrica real de la fuente de libass)."""
    kind = _kind(fmt)
    palette = palette or DEFAULT_PALETTE
    shadows = palette.get("shadows") or DEFAULT_PALETTE["shadows"]
    highlights = palette.get("highlights") or DEFAULT_PALETTE["highlights"]
    zone_bg, outline = shadows[-1], shadows[0]
    reasons: list[str] = []

    lines = layout_lines(text, fmt, usable_width, glyph_width, number_hero)
    for ln in lines:
        target = HERO_CAP_PCT[kind] if ln["role"] == "hero" else LABEL_CAP_PCT[kind]
        ln["cap_pct"] = round(min(target, _fit_cap_pct(ln["text"], fmt, usable_width, glyph_width)), 1)

    # Todo el bloque tiene que entrar en la zona del texto.
    zone_top, zone_bottom = zone or TEXT_ZONE[kind]
    zone_h = (zone_bottom - zone_top) * 100.0
    block = sum(ln["cap_pct"] * LINE_GAP for ln in lines)
    if lines and block > zone_h:
        k = zone_h / block
        for ln in lines:
            ln["cap_pct"] = math.floor(ln["cap_pct"] * k * 10.0) / 10.0
    too_long = [ln["text"] for ln in lines if ln["cap_pct"] < MIN_CAP_PCT[kind]]
    if too_long:
        reasons.append(f"texto largo: '{' / '.join(too_long)}' queda por debajo de {MIN_CAP_PCT[kind]}% "
                       "de alto de letra; conviene una opcion mas corta")

    # Color: blanco para el rotulo; la cifra en el acento.
    avoid = ""
    fills = (competitor_text or {}).get("fill") or {}
    colored = [f for f in fills if f in ACCENTS]
    if colored:
        avoid = colored[0]
    accent_name, accent, why = choose_accent(palette, zone_bg, avoid=avoid)
    for ln in lines:
        ln["color"] = accent if ln["role"] == "hero" else WHITE
    if any(ln["role"] == "hero" for ln in lines):
        reasons.extend(why)
    worst = contrast_ratio(WHITE, highlights[0])
    reasons.append(f"blanco sobre el fondo oscurecido del texto ({zone_bg}): {contrast_ratio(WHITE, zone_bg)}:1; "
                   f"sobre la zona clara de la imagen ({highlights[0]}) seria {worst}:1"
                   + (" -> fondo oscuro necesario detras del texto" if worst < 3.0 else ""))
    reasons.append("conservar el tamano y peso legibles a 190 px; lettering cinematografico con "
                   "kerning optico y sin contorno grueso ni sombra dura")
    if lines:
        reasons.append("tamanos: " + ", ".join(f"'{ln['text']}' {ln['cap_pct']}%" for ln in lines)
                       + f" del alto (rotulos ganadores: mediana 6%, cuarto superior ~8%)")
    widest = max((_chars(ln["text"]) * glyph_width * ln["cap_pct"] / 100.0 * float(getattr(fmt, "height", 1920))
                  / float(getattr(fmt, "width", 1080)) * 100.0 for ln in lines), default=0.0)
    return {"text": " ".join(ln["text"] for ln in lines), "kind": kind, "lines": lines,
            "font": TITLE_FONT,
            "outline": outline, "outline_fraction": OUTLINE_FRACTION, "zone": (zone_top, zone_bottom),
            "zone_bg": zone_bg, "accent": accent, "accent_name": accent_name,
            "widest_pct": round(widest, 0), "subject_band": SUBJECT_BAND_VERTICAL if kind == "vertical" else None,
            "reasons": reasons}


def typography_directives(plan: dict[str, Any]) -> tuple[str, ...]:
    """Las instrucciones de texto para el generador de imagenes, con los numeros del plan."""
    lines = plan["lines"]
    words = plan["text"]
    kind = plan["kind"]
    top, bottom = plan["zone"]
    if len(lines) == 1:
        layout = (f'layout: ONE line "{lines[0]["text"]}", cap height {lines[0]["cap_pct"]}% of the frame '
                  f'height, color {lines[0]["color"]}')
    else:
        parts = [f'line {i + 1} "{ln["text"]}" -- cap height {ln["cap_pct"]}% of the frame height, color {ln["color"]}'
                 for i, ln in enumerate(lines)]
        layout = f"layout: {len(lines)} stacked lines, centered: " + "; ".join(parts)
    layout += f"; the widest line spans about {int(plan['widest_pct'])}% of the frame width"
    if kind == "vertical":
        zone = (f"the text block sits between y {int(top * 100)}% and y {int(bottom * 100)}% of the frame height, "
                f"horizontally centered; nothing above {int(top * 100)}% (the Shorts grid crops it away) and "
                f"no text below 71%; the image behind the text is calm and dark (background darkening to "
                f"{plan['zone_bg']}) so the letters pop")
    else:
        zone = (f"place the text block in the RIGHT third of the frame, vertically centered between y "
                f"{int(top * 100)}% and y {int(bottom * 100)}%, over calm dark negative space "
                f"(darkening to {plan['zone_bg']})")
    return (
        f'render exactly these words and nothing else: "{words}"',
        "the text must be in ENGLISH and plain ASCII: no accents, no diacritics, "
        "no special characters -- image generators misspell accented words",
        "ALL CAPS, spelled exactly as written; no other words, captions, "
        "subtitles, watermarks or invented glyphs anywhere in the image",
        layout,
        # La direccion artistica actual prevalece sobre fuentes de planes guardados antiguos.
        f"typeface: {TITLE_FONT}; choose ONE coherent letterform family suited to the story: "
        "sculpted wedge-serif capitals for historical grandeur, or an editorial condensed sans-serif "
        "for mechanical tension; describe the chosen letterforms concretely in the final prompt; "
        "optical kerning, balanced counters, carefully shaped terminals, compact but not touching letters; "
        "substantial strokes readable at 190 px wide -- NOT a thin or light weight, NOT Impact; "
        "use the cap heights as legibility targets and adjust width to the chosen letterforms within safe margins",
        "art-directed title treatment: matte ink finish with very subtle fine grain inside the letters, "
        "clean silhouettes and open counters; preserve the specified base colors, with a restrained tint "
        "from the scene lighting; no bevel, no extruded 3D, no chrome, no glow, no glossy gradient; "
        "no thick outline, no hard offset drop shadow, no sticker edge, no WordArt; "
        "separate the title through calm darker background values; only an almost imperceptible soft "
        "shadow if needed, never a visible black border",
        zone,
        "compose the title and scene as one designed film poster, connected through color, light and "
        "negative space; keep every letter fully visible in a straight, front-facing title plane: "
        "never behind the subject, never warped by perspective, never on a curved path, "
        "never cropped by the frame edge; no decorative flourishes or extra symbols",
    )


def generic_directives(fmt: Any, palette: Optional[dict[str, Any]] = None,
                       hook: str = "{short_text}") -> tuple[str, ...]:
    """Cuando todavia no hay texto concreto (lo elige el LLM): las mismas reglas, como formula."""
    kind = _kind(fmt)
    plan = plan_typography("100 X", fmt, palette)          # para el color de acento y la zona
    base = list(typography_directives(dict(plan, text=hook, lines=[{"text": hook, "cap_pct": LABEL_CAP_PCT[kind],
                                                                     "color": WHITE, "role": "label"}])))
    base[3] = (f"layout: if the text starts with a number, put the number ALONE on the first line, cap height "
               f"{HERO_CAP_PCT[kind]}% of the frame height, color {plan['accent']}, and the rest on a second line "
               f"at {LABEL_CAP_PCT[kind]}% in white {WHITE}; otherwise one or two stacked lines at "
               f"{LABEL_CAP_PCT[kind]}% in white; the widest line spans no more than {int(USABLE_WIDTH[kind] * 100)}% "
               "of the frame width")
    return tuple(base)


def adapt_composition_rules(rules: Iterable[str], plan: Optional[dict[str, Any]]) -> list[str]:
    """En vertical, con el texto arriba y grande, el sujeto baja a la banda de abajo del texto.

    Las reglas del formato ponen el sujeto en y 12-62% (pensadas para un rotulo chico);
    con un bloque de texto de y 11-34% eso hace que el texto tape al sujeto o que el
    generador lo achique para que entre. Solo se reescribe el prompt externo: el
    validador del generador interno sigue midiendo con las reglas del formato."""
    rules = list(rules)
    band = (plan or {}).get("subject_band")
    if not band:
        return rules
    lo, hi = int(band[0] * 100), int(band[1] * 100)
    top, bottom = (plan or {}).get("zone", (0.11, 0.34))
    out = []
    for r in rules:
        if "occupies the band between y" in r:
            r = re.sub(r"between y \d+% and y \d+%", f"between y {lo}% and y {hi}%", r)
            r += f" (the headline text owns y {int(top * 100)}-{int(bottom * 100)}% above it)"
        elif "UPPER third" in r:
            r = (f"at least 55% of visible fine detail and high-contrast edges concentrated in the band "
                 f"y {lo}-{hi}% (the subject lives there); the text zone above it and the bottom stay calm")
        out.append(r)
    return out


# ----------------------------------------------------------------------------
# 3. Revisar la miniatura elegida
# ----------------------------------------------------------------------------
CHECK_PROMPT = """Measure the graphic headline text overlaid on this thumbnail (ignore logos/watermarks).
Return ONLY JSON: {"has_text": true|false, "text": "<exact text>", "lines": <int>,
"box_2d": [ymin, xmin, ymax, xmax] of the TALLEST single line of text, normalized 0-1000,
"weight": "thin|regular|medium|bold|black", "outline": "none|thin|thick", "box_behind": true|false}"""
GRID_PROMPT = ("This is a phone-size YouTube thumbnail as it appears in the grid. Read ONLY the overlaid "
               "headline text, exactly. If you cannot read it with confidence, answer UNREADABLE. "
               "Answer with the text only.")


def _norm(text: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(text or "").upper())


def grid_view(image_bytes: bytes, vertical: bool = True) -> bytes:
    """Como se ve en la grilla del telefono: recorte 2:3 (Shorts) y 190 px de ancho, sin inventar detalle."""
    from PIL import Image
    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = im.size
    if vertical and h > w:
        crop_h = min(h, int(w * 3 / 2))
        top = (h - crop_h) // 2
        im = im.crop((0, top, w, top + crop_h))
    small = im.resize((GRID_WIDTH_PX, max(1, int(im.height * GRID_WIDTH_PX / im.width))), Image.LANCZOS)
    big = small.resize((small.width * 2, small.height * 2), Image.NEAREST)
    buf = io.BytesIO()
    big.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def check_thumbnail_text(image_bytes: bytes, vision_fn: Callable[[str, list], str], expected: str = "",
                         vertical: bool = True) -> dict[str, Any]:
    """Lee y mide el texto de la miniatura. {text, grid_text, cap_pct, weight, outline, verdict, warnings}."""
    from ai.gemini_vision import parse_json
    kind = "vertical" if vertical else "landscape"
    d = parse_json(vision_fn(CHECK_PROMPT, [image_bytes]))
    if isinstance(d, list):
        d = d[0] if d else {}
    _box_metrics(d)
    grid_text = str(vision_fn(GRID_PROMPT, [grid_view(image_bytes, vertical)]) or "").strip()
    warnings: list[str] = []
    if not d.get("has_text"):
        return {"text": "", "grid_text": grid_text, "cap_pct": None, "verdict": "sin texto",
                "warnings": ["la miniatura no tiene texto (66% de los shorts de historia mas vistos lo llevan)"]}
    cap = d.get("cap_pct")
    if cap is not None:
        if cap < MIN_CAP_PCT[kind]:
            warnings.append(f"letra chica: {cap}% de alto (los rotulos ganadores: mediana 6%, cuarto superior ~8%)")
        elif cap < LABEL_CAP_PCT[kind] - 1:
            warnings.append(f"letra mediana: {cap}% de alto; con {LABEL_CAP_PCT[kind]:.0f}% pegaria mas")
    if str(d.get("weight")).lower() in ("thin", "regular", "medium"):
        warnings.append(f"trazo {d.get('weight')}: 12 de 13 rotulos ganadores usan bold/black")
    if str(d.get("outline")).lower() == "none" and not d.get("box_behind"):
        warnings.append("sin contorno ni caja: 10 de 13 rotulos ganadores usan uno de los dos")
    if grid_text.upper().startswith("UNREADABLE"):
        warnings.append(f"no se lee a {GRID_WIDTH_PX} px (tamano de la grilla en el telefono)")
    if expected and _norm(d.get("text")) != _norm(expected):
        warnings.append(f"el texto dice '{d.get('text')}' y se pidio '{expected}' (el generador pudo escribirlo mal)")
    verdict = "con impacto" if not warnings else ("mejorable" if len(warnings) <= 1 else "debil")
    return {"text": d.get("text", ""), "grid_text": grid_text, "cap_pct": cap, "weight": d.get("weight"),
            "outline": d.get("outline"), "box_behind": d.get("box_behind"), "verdict": verdict,
            "warnings": warnings}


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "plan":
        from thumbnail_formats import SHORT_9_16
        plan = plan_typography(argv[1], SHORT_9_16)
        for ln in plan["lines"]:
            print(f"  {ln['role']:5} '{ln['text']}' -> {ln['cap_pct']}% de alto, {ln['color']}")
        for r in plan["reasons"]:
            print("  -", r)
        print()
        print("\n".join(typography_directives(plan)))
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        from pathlib import Path

        from infra.env_loader import load_project_env
        from ai import gemini_vision
        load_project_env(Path(__file__).resolve().parent)
        data = Path(argv[1]).read_bytes()
        res = check_thumbnail_text(data, lambda p, ims: gemini_vision.ask_images(p, ims),
                                   expected=argv[2] if len(argv) > 2 else "")
        print(res)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
