"""
thumbnail_quality_validator.py

Valida cuantitativamente si un thumbnail 16:9 cumple los targets de
alto CTR para YouTube long-form. Basado en analisis empirico de canales
con CTR >5% vs canales estancados:

Umbrales objetivo (derivados de mediciones reales, no intuicion):
    1. Brillo medio (luminancia) entre 95 y 160 (/255). Debajo de 95 el
       thumb desaparece en el feed; arriba de 160 se ve desteñido.
    2. El tercio izquierdo debe ser al menos 20 puntos mas brillante que
       el tercio derecho (foco + key light calido a la izquierda, fondo
       oscuro/frio a la derecha).
    3. Al menos 55% de los bordes de alta frecuencia deben caer en el
       tercio izquierdo (el sujeto vive ahi; el tercio derecho queda libre
       para que el ojo lea el titulo del video).
    4. Temperatura calida dominante: canal R > canal B + 15.
    5. Histograma de luminancia disperso: ningun bin (10 slices) con mas
       del 30% de los pixels. Fuerza rango tonal real (no imagen plana).

API publica:
    validate_thumbnail(image_path) -> dict con metricas + score 0-100 + passes.
    score_thumbnail(image_path) -> float 0-100 (shortcut).

El validador NO rechaza imagenes; solo las puntua. El pipeline decide
que hacer con el score (ordenar variantes, loggear warnings, etc.).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# Umbrales de referencia (no modificar a la ligera; afinados sobre
# mediciones de canales historicos con CTR >5%).
TARGET_BRIGHTNESS_MIN = 95
TARGET_BRIGHTNESS_MAX = 160
TARGET_LEFT_RIGHT_LUM_DELTA = 20      # L debe ser >= R + 20
TARGET_LEFT_EDGE_RATIO = 0.55         # >= 55% de los bordes en tercio izq
TARGET_WARM_DELTA = 15                # R debe ser >= B + 15
TARGET_MAX_HIST_BIN_SHARE = 0.30      # ningun bin con mas del 30%

# Peso de cada metrica en el score final (suma = 100).
_SCORE_WEIGHTS = {
    "brightness": 25,
    "left_right_delta": 25,
    "left_edges": 20,
    "warmth": 15,
    "histogram_spread": 15,
}


def _downscale_for_analysis(img: "Image.Image", target_w: int = 320) -> "Image.Image":
    """Downscale para velocidad; mantener 16:9."""
    w, h = img.size
    if w <= target_w:
        return img
    ratio = target_w / w
    new_h = max(1, int(h * ratio))
    return img.resize((target_w, new_h), Image.Resampling.BILINEAR)


def _analyze_pixels(img: "Image.Image") -> Dict:
    """Analiza pixels (downsampled) y devuelve metricas crudas."""
    work = _downscale_for_analysis(img.convert("RGB"))
    W, H = work.size
    pixels = work.load()

    total = 0
    rs = gs = bs = ls = 0.0
    thirds = {
        "L": {"lum": 0.0, "n": 0, "edges": 0},
        "M": {"lum": 0.0, "n": 0, "edges": 0},
        "R": {"lum": 0.0, "n": 0, "edges": 0},
    }
    hist = [0] * 10  # 10 bins de luminancia
    third_w = W / 3

    for y in range(H):
        for x in range(W):
            r, g, b = pixels[x, y]
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            rs += r; gs += g; bs += b; ls += lum
            total += 1
            bin_idx = min(9, int(lum / 25.6))
            hist[bin_idx] += 1
            region = "L" if x < third_w else ("M" if x < 2 * third_w else "R")
            thirds[region]["lum"] += lum
            thirds[region]["n"] += 1
            if x < W - 1:
                r2, g2, b2 = pixels[x + 1, y]
                lum2 = 0.299 * r2 + 0.587 * g2 + 0.114 * b2
                if abs(lum - lum2) > 30:
                    thirds[region]["edges"] += 1

    if total == 0:
        raise ValueError("imagen vacia")

    avg_r = rs / total
    avg_g = gs / total
    avg_b = bs / total
    avg_lum = ls / total

    lum_L = thirds["L"]["lum"] / max(1, thirds["L"]["n"])
    lum_M = thirds["M"]["lum"] / max(1, thirds["M"]["n"])
    lum_R = thirds["R"]["lum"] / max(1, thirds["R"]["n"])
    total_edges = thirds["L"]["edges"] + thirds["M"]["edges"] + thirds["R"]["edges"]
    left_edge_ratio = thirds["L"]["edges"] / max(1, total_edges)

    max_hist_share = max(hist) / total if total else 0.0

    return {
        "avg_rgb": (round(avg_r), round(avg_g), round(avg_b)),
        "avg_hex": "#{:02x}{:02x}{:02x}".format(round(avg_r), round(avg_g), round(avg_b)),
        "brightness": round(avg_lum, 1),
        "lum_by_third": {
            "left": round(lum_L, 1),
            "mid": round(lum_M, 1),
            "right": round(lum_R, 1),
        },
        "left_right_delta": round(lum_L - lum_R, 1),
        "left_edge_ratio": round(left_edge_ratio, 3),
        "warmth_delta": round(avg_r - avg_b, 1),
        "max_hist_bin_share": round(max_hist_share, 3),
        "histogram": hist,
        "edges_by_third": {
            "L": thirds["L"]["edges"],
            "M": thirds["M"]["edges"],
            "R": thirds["R"]["edges"],
        },
    }


def _score_from_metrics(m: Dict) -> Dict:
    """Convierte metricas crudas en sub-scores 0-100 y score total ponderado."""
    brightness = m["brightness"]
    if TARGET_BRIGHTNESS_MIN <= brightness <= TARGET_BRIGHTNESS_MAX:
        s_bright = 100.0
    else:
        if brightness < TARGET_BRIGHTNESS_MIN:
            diff = TARGET_BRIGHTNESS_MIN - brightness
        else:
            diff = brightness - TARGET_BRIGHTNESS_MAX
        s_bright = max(0.0, 100.0 - diff * 2.0)

    delta = m["left_right_delta"]
    if delta >= TARGET_LEFT_RIGHT_LUM_DELTA:
        s_delta = 100.0
    elif delta >= 0:
        s_delta = (delta / TARGET_LEFT_RIGHT_LUM_DELTA) * 100.0
    else:
        s_delta = max(0.0, 50.0 + delta * 2.0)  # penaliza fuerte si R > L

    edge_ratio = m["left_edge_ratio"]
    if edge_ratio >= TARGET_LEFT_EDGE_RATIO:
        s_edges = 100.0
    else:
        s_edges = max(0.0, (edge_ratio / TARGET_LEFT_EDGE_RATIO) * 100.0)

    warmth = m["warmth_delta"]
    if warmth >= TARGET_WARM_DELTA:
        s_warmth = 100.0
    elif warmth >= 0:
        s_warmth = (warmth / TARGET_WARM_DELTA) * 100.0
    else:
        s_warmth = max(0.0, 50.0 + warmth * 1.5)

    hist_share = m["max_hist_bin_share"]
    if hist_share <= TARGET_MAX_HIST_BIN_SHARE:
        s_hist = 100.0
    else:
        overflow = hist_share - TARGET_MAX_HIST_BIN_SHARE
        s_hist = max(0.0, 100.0 - overflow * 200.0)

    sub_scores = {
        "brightness": round(s_bright, 1),
        "left_right_delta": round(s_delta, 1),
        "left_edges": round(s_edges, 1),
        "warmth": round(s_warmth, 1),
        "histogram_spread": round(s_hist, 1),
    }

    total = sum(sub_scores[k] * _SCORE_WEIGHTS[k] for k in sub_scores) / 100.0

    passes = {
        "brightness_in_range": TARGET_BRIGHTNESS_MIN <= brightness <= TARGET_BRIGHTNESS_MAX,
        "left_brighter_than_right": delta >= TARGET_LEFT_RIGHT_LUM_DELTA,
        "left_third_has_focus": edge_ratio >= TARGET_LEFT_EDGE_RATIO,
        "warm_palette": warmth >= TARGET_WARM_DELTA,
        "histogram_has_range": hist_share <= TARGET_MAX_HIST_BIN_SHARE,
    }

    return {
        "sub_scores": sub_scores,
        "total_score": round(total, 1),
        "passes": passes,
        "passed_count": sum(1 for v in passes.values() if v),
        "total_checks": len(passes),
    }


def validate_thumbnail(image_path: str) -> Dict:
    """Valida un thumbnail y devuelve metricas + score + pass/fail.

    Args:
        image_path: ruta a la imagen (PNG/JPG).

    Returns:
        dict con 'metrics', 'sub_scores', 'total_score', 'passes' (por metrica),
        'passed_count', 'verdict' ('excellent'|'good'|'weak'|'poor') y 'suggestions'.

    Raises:
        RuntimeError si PIL no esta disponible.
        FileNotFoundError si no existe la imagen.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow no instalado. pip install Pillow")

    p = Path(image_path)
    if not p.is_file():
        raise FileNotFoundError(f"No existe: {image_path}")

    with Image.open(p) as img:
        img.load()
        metrics = _analyze_pixels(img)

    scoring = _score_from_metrics(metrics)
    total = scoring["total_score"]

    if total >= 85:
        verdict = "excellent"
    elif total >= 70:
        verdict = "good"
    elif total >= 50:
        verdict = "weak"
    else:
        verdict = "poor"

    suggestions = []
    if not scoring["passes"]["brightness_in_range"]:
        if metrics["brightness"] < TARGET_BRIGHTNESS_MIN:
            suggestions.append(
                f"Brillo {metrics['brightness']} < {TARGET_BRIGHTNESS_MIN}: agrega luz calida (sol, fuego, lampara) al tercio izquierdo"
            )
        else:
            suggestions.append(
                f"Brillo {metrics['brightness']} > {TARGET_BRIGHTNESS_MAX}: baja exposicion global o agrega sombra al fondo"
            )
    if not scoring["passes"]["left_brighter_than_right"]:
        suggestions.append(
            f"Delta L-R = {metrics['left_right_delta']} (objetivo >= {TARGET_LEFT_RIGHT_LUM_DELTA}): mueve el sujeto/foco al tercio izquierdo con key light calido"
        )
    if not scoring["passes"]["left_third_has_focus"]:
        suggestions.append(
            f"Solo {int(metrics['left_edge_ratio']*100)}% de detalle en tercio izq (objetivo {int(TARGET_LEFT_EDGE_RATIO*100)}%): encuadra la cara/accion en la izquierda"
        )
    if not scoring["passes"]["warm_palette"]:
        suggestions.append(
            f"Paleta no calida (R-B = {metrics['warmth_delta']}): agrega firelight/sunset/amber; evita grises neutros"
        )
    if not scoring["passes"]["histogram_has_range"]:
        suggestions.append(
            f"Imagen tonalmente plana ({int(metrics['max_hist_bin_share']*100)}% en un solo bin): aumenta contraste, agrega luces/sombras duras"
        )

    return {
        "image": str(p),
        "metrics": metrics,
        "sub_scores": scoring["sub_scores"],
        "total_score": total,
        "passes": scoring["passes"],
        "passed_count": scoring["passed_count"],
        "total_checks": scoring["total_checks"],
        "verdict": verdict,
        "suggestions": suggestions,
    }


def score_thumbnail(image_path: str) -> float:
    """Shortcut: devuelve solo el score total 0-100."""
    try:
        return float(validate_thumbnail(image_path)["total_score"])
    except Exception:
        return 0.0


if __name__ == "__main__":  # pragma: no cover
    import sys
    import json
    if len(sys.argv) < 2:
        print("Uso: python thumbnail_quality_validator.py <imagen>")
        sys.exit(1)
    result = validate_thumbnail(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
