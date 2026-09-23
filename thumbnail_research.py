# -*- coding: utf-8 -*-
"""Miniaturas guiadas por datos: que hacen las miniaturas que compiten y como diferenciarse.

Hasta 2026-09-22 el super prompt de miniatura tenia todo fijo: la paleta era siempre
ambar/rojo (#f3c267 #e07a2b #b32a1c), la luminancia objetivo fija, y el texto lo
inventaba el LLM (a veces repitiendo el titulo). Lo que hace vidIQ, aca:

  1. Competencia: las miniaturas de los videos que rankean para la palabra clave
     (la MISMA busqueda que tags y titulo, youtube_tags.gather_research) se bajan
     y se miden con numpy: brillo, contraste, saturacion, familia de color
     dominante (calida / fria / neutra) y cuan "cargadas" estan (densidad de bordes).
  2. Diferenciarse: el acento de color que MENOS usa la competencia, el brillo
     contrario al promedio, y si todas estan cargadas, una sola cosa y 2 palabras.
  3. Texto que COMPLEMENTA al titulo (no lo repite): una busqueda real corta del
     autocompletado, una cifra del guion con su sustantivo, o la palabra del angulo.

Salida: `build_thumbnail_brief(...)` -> {text, text_options, palette, luminance,
competitors, differentiation, prompt_block}; el super prompt la consume.

Ver `test_thumbnail_research.py`.
"""

from __future__ import annotations

import io
import re
from typing import Any, Callable, Iterable, Optional

from youtube_tags import content_tokens, normalize_tag

# Paletas por familia de acento (hex para el generador de imagenes).
PALETTES = {
    "warm": {"label": "calida (ambar/rojo)", "highlights": ["#f3c267", "#e07a2b", "#b32a1c"],
             "mids": ["#6a3a1e", "#2f3a44"], "shadows": ["#0e1318", "#1a2330"]},
    "cool": {"label": "fria (teal/acero)", "highlights": ["#9fe3e0", "#3fb6c6", "#1f6f8b"],
             "mids": ["#2b4a5e", "#5a6b73"], "shadows": ["#0b1419", "#14222b"]},
    "neutral": {"label": "neutra con un solo acento", "highlights": ["#f2efe8", "#d9d2c3", "#e24a2b"],
                "mids": ["#6d6a63", "#3b3a37"], "shadows": ["#111111", "#1d1c1a"]},
}


# ----------------------------------------------------------------------------
# Analisis de imagen (puro, numpy)
# ----------------------------------------------------------------------------
def analyze_image(img) -> dict[str, float]:
    """Metricas de una miniatura: brillo, contraste, saturacion, calido/frio, carga visual."""
    import numpy as np

    im = img.convert("RGB")
    im.thumbnail((320, 320))
    arr = np.asarray(im).astype("float32") / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    # tono en grados, solo donde hay color de verdad
    delta = np.maximum(mx - mn, 1e-6)
    hue = np.zeros_like(mx)
    rm, gm, bm = (mx == r), (mx == g), (mx == b)
    hue = np.where(rm, ((g - b) / delta) % 6, hue)
    hue = np.where(gm & ~rm, (b - r) / delta + 2, hue)
    hue = np.where(bm & ~rm & ~gm, (r - g) / delta + 4, hue)
    hue = hue * 60.0
    colored = (sat > 0.25) & (mx > 0.2)
    n_col = max(1, int(colored.sum()))
    warm = float((colored & ((hue < 55) | (hue >= 330))).sum()) / n_col
    cool = float((colored & (hue >= 160) & (hue < 260)).sum()) / n_col
    gy, gx = np.gradient(lum)
    edges = float((np.hypot(gx, gy) > 0.08).mean())
    return {
        "brightness": round(float(lum.mean()) * 255, 1),
        "contrast": round(float(lum.std()) * 255, 1),
        "saturation": round(float(sat.mean()), 3),
        "colored_share": round(float(colored.mean()), 3),
        "warm": round(warm, 3),
        "cool": round(cool, 3),
        "edge_density": round(edges, 3),
    }


def color_family(m: dict[str, float]) -> str:
    if m.get("colored_share", 0) < 0.12:
        return "neutral"
    if m.get("warm", 0) >= m.get("cool", 0) + 0.15:
        return "warm"
    if m.get("cool", 0) >= m.get("warm", 0) + 0.15:
        return "cool"
    return "neutral"


def summarize_competitors(metrics: list[dict[str, float]]) -> dict[str, Any]:
    if not metrics:
        return {"n": 0}
    n = len(metrics)
    fams = {"warm": 0, "cool": 0, "neutral": 0}
    for m in metrics:
        fams[color_family(m)] += 1
    med = lambda key: sorted(m[key] for m in metrics)[n // 2]
    return {
        "n": n,
        "families": fams,
        "median_brightness": med("brightness"),
        "median_saturation": med("saturation"),
        "dark_share": round(sum(1 for m in metrics if m["brightness"] < 90) / n, 2),
        "bright_share": round(sum(1 for m in metrics if m["brightness"] > 150) / n, 2),
        "busy_share": round(sum(1 for m in metrics if m["edge_density"] > 0.18) / n, 2),
    }


def differentiate(summary: dict[str, Any]) -> dict[str, Any]:
    """Acento, brillo y carga que mas se despegan de lo que ya hay en la pagina de resultados."""
    notes: list[str] = []
    if not summary or not summary.get("n"):
        return {"family": "warm", "luminance": (100, 150), "minimal": True,
                "notes": ["sin datos de competencia: paleta calida por defecto, 2 palabras"]}
    fams = summary["families"]
    family = min(("cool", "warm", "neutral"), key=lambda f: (fams.get(f, 0), {"cool": 0, "warm": 1, "neutral": 2}[f]))
    notes.append(f"de {summary['n']} miniaturas que compiten: {fams['warm']} calidas, {fams['cool']} frias, "
                 f"{fams['neutral']} neutras -> acento {PALETTES[family]['label']}, el menos usado")
    if summary["dark_share"] >= 0.5:
        lum = (125, 165)
        notes.append(f"{int(summary['dark_share'] * 100)}% son oscuras -> sujeto bien iluminado, luminancia 125-165")
    elif summary["bright_share"] >= 0.5:
        lum = (70, 110)
        notes.append(f"{int(summary['bright_share'] * 100)}% son claras -> clima oscuro con un solo punto de luz, 70-110")
    else:
        lum = (100, 150)
        notes.append(f"brillo mediano de la competencia {summary['median_brightness']:.0f}/255 -> contraste fuerte, 100-150")
    minimal = summary["busy_share"] >= 0.4
    notes.append(f"{int(summary['busy_share'] * 100)}% estan cargadas -> "
                 + ("UNA sola cosa, mucho espacio vacio, 2 palabras" if minimal else "una sola cosa clara, hasta 3 palabras"))
    return {"family": family, "luminance": lum, "minimal": minimal, "notes": notes}


# ----------------------------------------------------------------------------
# Texto de la miniatura: complementa al titulo
# ----------------------------------------------------------------------------
_NUM_NOUN_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|kg|km|kt|tons?|meters?|metres?|feet|ft|"
                          r"[a-z]{3,})\b", re.I)
_SKIP_NOUNS = {"years", "year", "and", "the", "with", "was", "were", "each", "per", "of", "to", "in", "on", "at"}


def _ascii_upper(text: str) -> str:
    """ASCII en mayusculas conservando el formato de las cifras ('50,000 TROOPS')."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^0-9A-Za-z,.'& -]+", " ", t)
    return re.sub(r"\s+", " ", t).strip(" ,.-").upper()


def _is_year(num: str) -> bool:
    return bool(re.fullmatch(r"1\d{3}|20\d{2}", num))


def text_options(title: str, script: str, research: dict[str, Any], archetype: str = "",
                 max_chars: int = 18, limit: int = 5) -> list[dict[str, str]]:
    """Textos de 1-3 palabras que agregan algo que el titulo no dice, con su por que.

    Orden (de mas a menos concreto):
      1. cifra del guion + su sustantivo comun ('1,000 CASTS', '63 SAILORS'), sin anos;
      2. busqueda real de 2+ palabras que no repite el titulo ('HUMAN TORPEDO');
      3. palabra del angulo, SOLO si el guion la respalda.
    Todo texto de miniatura es una afirmacion: cada palabra tiene que estar en el guion
    (el 2026-09-22 salio 'HE LIVED' para los pilotos kaiten, que morian).
    """
    title_toks = set(content_tokens(title))
    corpus = set(research.get("corpus") or ()) | set(content_tokens(script))
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(text: str, why: str) -> None:
        t = _ascii_upper(text)
        words = t.split()
        if not t or len(t) > max_chars or not 1 <= len(words) <= 3 or t in seen:
            return
        toks = set(content_tokens(t))
        nums = {n.replace(",", "") for n in re.findall(r"\d[\d,]*", t)}
        title_nums = {n.replace(",", "") for n in re.findall(r"\d[\d,]*", title or "")}
        new_number = bool(nums - title_nums)
        if toks and toks <= title_toks and not new_number:
            return                                  # repite el titulo: no suma nada
        if toks and not toks <= corpus:
            return                                  # afirma algo que el guion no dice
        seen.add(t)
        out.append({"text": t, "why": why})

    # 1) cifras con sustantivo comun (en minuscula en el guion), sin anos
    for m in _NUM_NOUN_RE.finditer(script or ""):
        num, noun = m.group(1), m.group(2)
        if _is_year(num) or noun.lower() in _SKIP_NOUNS or noun[:1].isupper():
            continue
        if num.replace(",", "") in {n.replace(",", "") for n in re.findall(r"\d[\d,]*", title or "")}:
            continue                                # la cifra ya esta en el titulo
        add(f"{num} {noun}", "cifra del guion que el titulo no dice")

    # 2) busquedas reales de 2+ palabras (sin la palabra clave, que ya va en el titulo)
    kw_toks = set(content_tokens(research.get("keyword") or ""))
    for sug, _score in sorted((research.get("suggestions") or {}).items(), key=lambda kv: -kv[1]):
        toks = content_tokens(sug)
        if not toks or any(t not in corpus for t in toks):
            continue
        extra = [w for w in normalize_tag(sug).split()
                 if _depossess_safe(w) not in kw_toks and w not in ("the", "of", "a", "an")]
        if len(extra) >= 2 and len(" ".join(extra)) <= max_chars:
            add(" ".join(extra), f"busqueda real: '{sug}'")

    # 3) palabras del angulo respaldadas por el guion
    try:
        from channel_strategy import archetype_cover_words
        for w in archetype_cover_words(archetype):
            add(w, f"palabra del angulo '{archetype}'")
    except Exception:
        pass
    return out[:limit]


def _depossess_safe(word: str) -> str:
    toks = content_tokens(word)
    return toks[0] if toks else word


# ----------------------------------------------------------------------------
# Brief completo
# ----------------------------------------------------------------------------
def fetch_competitor_metrics(competitors: Iterable[dict[str, Any]], limit: int = 8,
                             fetch: Optional[Callable[[str], Optional[bytes]]] = None,
                             log: Callable[[str], None] = lambda m: None) -> list[dict[str, Any]]:
    from PIL import Image

    if fetch is None:
        import requests

        def fetch(url):
            r = requests.get(url, timeout=15)
            return r.content if r.status_code == 200 else None
    out = []
    for v in sorted(competitors, key=lambda v: -int(v.get("views") or 0)):
        url = v.get("thumbnail") or (f"https://i.ytimg.com/vi/{v['video_id']}/mqdefault.jpg" if v.get("video_id") else "")
        if not url:
            continue
        try:
            raw = fetch(url)
            if not raw:
                continue
            m = analyze_image(Image.open(io.BytesIO(raw)))
            m.update({"title": v.get("title", ""), "views": int(v.get("views") or 0)})
            out.append(m)
        except Exception as exc:
            log(f"   [Miniatura] no se pudo analizar {url}: {exc}")
        if len(out) >= limit:
            break
    return out


def build_thumbnail_brief(topic: str, title: str, script: str, *, research: Optional[dict[str, Any]] = None,
                          archetype: str = "", fetch=None, log: Callable[[str], None] = print) -> dict[str, Any]:
    if research is None:
        from youtube_tags import gather_research
        research = gather_research(topic, title, script, log=log)
    metrics = fetch_competitor_metrics(research.get("competitors") or [], fetch=fetch, log=log)
    summary = summarize_competitors(metrics)
    diff = differentiate(summary)
    options = text_options(title, script, research, archetype, max_chars=14 if diff["minimal"] else 18)
    text = options[0]["text"] if options else ""
    palette = PALETTES[diff["family"]]
    lo, hi = diff["luminance"]
    lines = [
        "SEARCH & COMPETITION RESEARCH (use it; it overrides generic defaults):",
        f"- Main search keyword: \"{research.get('keyword', '')}\". The TITLE already carries it; the thumbnail"
        " text must ADD information, not repeat the title.",
    ]
    for n in diff["notes"]:
        lines.append(f"- {n}")
    if text:
        lines.append(f"- short_text: use EXACTLY \"{text}\" ({options[0]['why']}).")
    lines.append(f"- COLOR SYSTEM ({palette['label']}): highlights {', '.join(palette['highlights'])}; "
                 f"mids {', '.join(palette['mids'])}; shadows {', '.join(palette['shadows'])}.")
    lines.append(f"- Average luminance target: {lo}-{hi} (out of 255).")
    if diff["minimal"]:
        lines.append("- ONE subject, large calm negative space, 2 words max: the result page is cluttered.")
    return {
        "keyword": research.get("keyword"), "text": text, "text_options": options,
        "palette": palette, "family": diff["family"], "luminance": (lo, hi), "minimal": diff["minimal"],
        "competitors": summary, "competitor_samples": metrics, "differentiation": diff["notes"],
        "prompt_block": "\n".join(lines),
    }


__all__ = ["analyze_image", "summarize_competitors", "differentiate", "text_options", "build_thumbnail_brief"]
