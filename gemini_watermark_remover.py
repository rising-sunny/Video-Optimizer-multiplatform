"""
gemini_watermark_remover.py

Elimina la marca de agua (sparkle) que Gemini/Imagen agrega en la esquina
inferior derecha de las imágenes generadas.

Estrategia (en orden de preferencia):
    1. OpenCV inpainting (cv2.INPAINT_TELEA): reconstruye el área desde todos
       los bordes usando difusión PDE — resultado más natural, especialmente en
       fondos con gradientes, texturas o contenido complejo.
    2. Fallback PIL: blend ponderado de tres parches (izquierda, arriba,
       diagonal) con máscaras de gradiente, mejor que el espejo simple anterior.

API pública:
    remove_gemini_watermark(src_path, dst_path=None) -> str
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

try:
    from PIL import Image, ImageFilter, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


# Zona de búsqueda del watermark (fracción de la imagen desde el borde inf-der)
# Gemini siempre coloca el sparkle en la esquina inferior-derecha con margen pequeño;
# un área demasiado grande captura contenido brillante (cielo, sol) en lugar del sparkle
_SEARCH_X_RATIO = 0.18   # buscar en el 18% derecho
_SEARCH_Y_RATIO = 0.14   # buscar en el 14% inferior
# Tamaño del box de inpainting alrededor del centro detectado
_WM_WIDTH_RATIO  = 0.16
_WM_HEIGHT_RATIO = 0.13
_WM_MIN_PX  = 90
_WM_MAX_PX  = 300


def _detect_watermark_center(arr: "np.ndarray") -> Tuple[int, int]:
    """
    Detecta la posición del sparkle de Gemini buscando el cluster más brillante
    dentro de la zona inferior-derecha esperada.
    Devuelve (cx, cy) en coordenadas de la imagen completa.
    """
    h, w = arr.shape[:2]
    # Zona de búsqueda
    sy = int(h * (1 - _SEARCH_Y_RATIO))
    sx = int(w * (1 - _SEARCH_X_RATIO))
    region = arr[sy:h, sx:w]

    # Convertir a escala de grises y aplicar blur para encontrar el cluster
    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY).astype(np.float32)
    blurred = cv2.GaussianBlur(gray, (21, 21), 0)
    _, _, _, max_loc = cv2.minMaxLoc(blurred)

    # Coordenadas en la imagen completa
    cx = sx + max_loc[0]
    cy = sy + max_loc[1]
    return (cx, cy)


def _compute_watermark_box(width: int, height: int,
                            arr: "Optional[np.ndarray]" = None) -> Tuple[int, int, int, int]:
    """
    Si se pasa el array numpy de la imagen, detecta automáticamente el centro
    del watermark. Si no, usa la esquina inferior-derecha como fallback.
    """
    wm_w = max(_WM_MIN_PX, min(int(width  * _WM_WIDTH_RATIO),  _WM_MAX_PX))
    wm_h = max(_WM_MIN_PX, min(int(height * _WM_HEIGHT_RATIO), _WM_MAX_PX))

    if arr is not None and CV2_AVAILABLE:
        try:
            cx, cy = _detect_watermark_center(arr)
            left   = max(0,     cx - wm_w // 2)
            top    = max(0,     cy - wm_h // 2)
            right  = min(width,  left + wm_w)
            bottom = min(height, top  + wm_h)
            return (left, top, right, bottom)
        except Exception:
            pass

    # Fallback: esquina inferior-derecha fija
    return (max(0, width - wm_w), max(0, height - wm_h), width, height)


# ---------------------------------------------------------------------------
# Estrategia 1: OpenCV inpainting
# ---------------------------------------------------------------------------

def _soft_ellipse_mask(shape: Tuple[int, int], box: Tuple[int, int, int, int],
                       feather: int) -> "np.ndarray":
    """
    Máscara float32 [0..1]:
      - 1.0 en todo el interior del box (la zona eliminada queda completamente
        reemplazada por el inpainted, sin que el sparkle original se cuele).
      - Decae suavemente de 1.0 a 0.0 en los `feather` píxeles exteriores
        al borde del box (transición coseno para evitar costuras visibles).
    """
    h, w = shape
    left, top, right, bottom = box

    ys, xs = np.ogrid[:h, :w]

    # Distancia de cada píxel al borde más cercano del box (0 = dentro o en borde)
    dx = np.maximum(0.0, np.maximum(left - xs.astype(np.float32),
                                     xs.astype(np.float32) - (right  - 1)))
    dy = np.maximum(0.0, np.maximum(top  - ys.astype(np.float32),
                                     ys.astype(np.float32) - (bottom - 1)))
    dist_outside = np.sqrt(dx ** 2 + dy ** 2)  # 0 dentro del box, >0 fuera

    # t=0 en el borde del box (1.0), t=1 a `feather` px de distancia (0.0)
    t = np.clip(dist_outside / max(feather, 1), 0.0, 1.0)
    blend = (np.cos(t * np.pi) + 1.0) / 2.0
    return blend.astype(np.float32)


def _inpaint_opencv(img: "Image.Image", box: Tuple[int, int, int, int],
                    arr: "Optional[np.ndarray]" = None) -> "Image.Image":
    """
    Usa cv2.INPAINT_TELEA con una máscara binaria ampliada para la reconstrucción,
    luego compone el resultado sobre el original con una máscara de gradiente
    elíptico suave — sin bordes rectangulares visibles.
    """
    left, top, right, bottom = box
    bw, bh = right - left, bottom - top
    pad = max(12, int(min(bw, bh) * 0.20))

    if arr is None:
        arr = np.array(img.convert("RGB"), dtype=np.uint8)

    # Máscara binaria con margen para inpaint (el inpainting necesita un poco más
    # de área que la zona a ocultar para reconstruir bien)
    hard_mask = np.zeros(arr.shape[:2], dtype=np.uint8)
    hard_mask[max(0, top - pad): min(arr.shape[0], bottom + pad),
              max(0, left - pad): min(arr.shape[1], right + pad)] = 255

    radius = max(14, int((bw + bh) / 6))
    inpainted = cv2.inpaint(arr, hard_mask, inpaintRadius=radius, flags=cv2.INPAINT_TELEA)

    # Máscara suave elíptica: mezcla gradual entre inpainted y original
    feather = max(12, int(min(bw, bh) * 0.25))
    soft = _soft_ellipse_mask(arr.shape[:2], box, feather)

    # Composite: inpainted donde soft≈1, original donde soft≈0
    soft3 = soft[:, :, np.newaxis]
    blended = (inpainted.astype(np.float32) * soft3
               + arr.astype(np.float32) * (1.0 - soft3))
    blended = np.clip(blended, 0, 255).astype(np.uint8)

    result_pil = Image.fromarray(blended)
    if img.mode == "RGBA":
        result_pil = result_pil.convert("RGBA")
        result_pil.putalpha(img.split()[3])

    return result_pil


# ---------------------------------------------------------------------------
# Estrategia 2: PIL multi-source blend (fallback)
# ---------------------------------------------------------------------------

def _make_gradient_mask(size: Tuple[int, int], direction: str) -> "Image.Image":
    """Crea una máscara en gradiente en la dirección dada ('left'|'top'|'diag')."""
    w, h = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if direction == "left":
        for x in range(w):
            v = int(255 * (1 - x / max(w - 1, 1)))
            draw.line([(x, 0), (x, h - 1)], fill=v)
    elif direction == "top":
        for y in range(h):
            v = int(255 * (1 - y / max(h - 1, 1)))
            draw.line([(0, y), (w - 1, y)], fill=v)
    else:  # diag
        for x in range(w):
            for y in range(h):
                v = int(255 * (1 - (x + y) / max(w + h - 2, 1)))
                mask.putpixel((x, y), v)
    return mask


def _get_patch(img: "Image.Image", box: Tuple[int, int, int, int],
               source: str) -> Optional["Image.Image"]:
    """Devuelve un parche del mismo tamaño que `box` tomado desde `source`."""
    left, top, right, bottom = box
    bw, bh = right - left, bottom - top
    iw, ih = img.size

    if source == "left":
        src_l = max(0, left - bw)
        src_r = left
        if src_r <= src_l:
            return None
        crop = img.crop((src_l, top, src_r, bottom))
        if crop.size != (bw, bh):
            crop = crop.resize((bw, bh), Image.Resampling.LANCZOS)
        return crop.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    if source == "top":
        src_t = max(0, top - bh)
        src_b = top
        if src_b <= src_t:
            return None
        crop = img.crop((left, src_t, right, src_b))
        if crop.size != (bw, bh):
            crop = crop.resize((bw, bh), Image.Resampling.LANCZOS)
        return crop.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    if source == "diag":
        src_l = max(0, left - bw)
        src_t = max(0, top - bh)
        if src_l >= left or src_t >= top:
            return None
        crop = img.crop((src_l, src_t, left, top))
        if crop.size != (bw, bh):
            crop = crop.resize((bw, bh), Image.Resampling.LANCZOS)
        return crop.rotate(180)

    return None


def _inpaint_pil_blend(img: "Image.Image", box: Tuple[int, int, int, int]) -> "Image.Image":
    """
    Blend ponderado de parches (izquierda, arriba, diagonal) compuesto sobre el
    original con una máscara elíptica suave — sin bordes rectangulares visibles.
    Usa numpy si está disponible para la composición final.
    """
    import importlib
    np_mod = None
    try:
        np_mod = importlib.import_module("numpy")
    except ImportError:
        pass

    left, top, right, bottom = box
    bw, bh = right - left, bottom - top
    if bw <= 0 or bh <= 0:
        return img

    patches = {}
    for src in ("left", "top", "diag"):
        p = _get_patch(img, box, src)
        if p is not None:
            patches[src] = p.filter(ImageFilter.GaussianBlur(radius=1.5))

    if not patches:
        return img

    # ---- Blend de parches con pesos de gradiente (operado con numpy) ----
    rgb_img = img.convert("RGB")
    if np_mod is not None:
        arr_orig = np_mod.array(rgb_img, dtype=np_mod.float32)
        acc  = np_mod.zeros((bh, bw, 3), dtype=np_mod.float32)
        wsum = np_mod.zeros((bh, bw),    dtype=np_mod.float32)

        for src, patch in patches.items():
            patch_arr = np_mod.array(patch.convert("RGB").resize((bw, bh),
                                     Image.Resampling.LANCZOS), dtype=np_mod.float32)
            grad_pil = _make_gradient_mask((bw, bh), src)
            grad = np_mod.array(grad_pil, dtype=np_mod.float32) / 255.0
            acc  += patch_arr * grad[:, :, np_mod.newaxis]
            wsum += grad

        wsum = np_mod.maximum(wsum, 1e-6)
        blended_arr = np_mod.clip(acc / wsum[:, :, np_mod.newaxis], 0, 255).astype(np_mod.uint8)
        blended_full = arr_orig.copy()
        blended_full[top:bottom, left:right] = blended_arr
        blended_full = np_mod.clip(blended_full, 0, 255).astype(np_mod.uint8)

        # Máscara elíptica suave para la composición final
        feather = max(14, int(min(bw, bh) * 0.30))
        soft = _soft_ellipse_mask(arr_orig.shape[:2], box, feather)
        soft3 = soft[:, :, np_mod.newaxis]
        composite = (blended_full.astype(np_mod.float32) * soft3
                     + arr_orig * (1.0 - soft3))
        composite = np_mod.clip(composite, 0, 255).astype(np_mod.uint8)
        result = Image.fromarray(composite)
        if img.mode == "RGBA":
            result = result.convert("RGBA")
            result.putalpha(img.split()[3])
        return result

    # ---- Fallback puro PIL (sin numpy) ----
    # Tomar el parche de mayor disponibilidad y aplicar blur fuerte
    patch = next(iter(patches.values()))
    patch = patch.resize((bw, bh), Image.Resampling.LANCZOS)
    patch = patch.filter(ImageFilter.GaussianBlur(radius=3))

    out = img.copy()
    out.paste(patch.convert(img.mode), (left, top))

    # Suavizar bordes manualmente con blur progresivo
    feather_px = max(8, int(min(bw, bh) * 0.20))
    for seam_box in [
        (max(0, left - feather_px), top,    left + feather_px, bottom),
        (left, max(0, top - feather_px),     right, top + feather_px),
    ]:
        try:
            orig_c = img.crop(seam_box)
            new_c  = out.crop(seam_box)
            blurred = new_c.filter(ImageFilter.GaussianBlur(radius=feather_px * 0.8))
            mixed = Image.blend(orig_c, blurred, alpha=0.5)
            out.paste(mixed, (seam_box[0], seam_box[1]))
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Punto de entrada público
# ---------------------------------------------------------------------------

def remove_gemini_watermark(src_path: str, dst_path: Optional[str] = None) -> str:
    """Elimina el watermark de Gemini de una imagen.

    Usa OpenCV inpainting si está disponible; si no, blend multi-fuente con PIL.

    Args:
        src_path: ruta a la imagen de entrada.
        dst_path: ruta de salida. Si es None, sobrescribe src_path.

    Returns:
        La ruta de la imagen procesada.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow no está instalado: pip install Pillow")

    src = Path(src_path)
    if not src.is_file():
        raise FileNotFoundError(f"No existe la imagen: {src_path}")

    out_path = Path(dst_path) if dst_path else src

    with Image.open(src) as img:
        mode = img.mode
        if mode not in ("RGB", "RGBA"):
            work = img.convert("RGBA" if "A" in mode else "RGB")
        else:
            work = img.copy()

        width, height = work.size
        if width < 100 or height < 100:
            if str(out_path) != str(src):
                work.save(out_path)
            return str(out_path)

        if CV2_AVAILABLE:
            arr = np.array(work.convert("RGB"), dtype=np.uint8)
            box = _compute_watermark_box(width, height, arr=arr)
            cleaned = _inpaint_opencv(work, box, arr=arr)
            method = "OpenCV TELEA"
        else:
            box = _compute_watermark_box(width, height)
            cleaned = _inpaint_pil_blend(work, box)
            method = "PIL multi-source blend"

        fmt = (img.format or out_path.suffix.lstrip(".").upper() or "PNG").upper()
        if fmt == "JPG":
            fmt = "JPEG"
        save_kwargs = {}
        if fmt == "JPEG":
            if cleaned.mode == "RGBA":
                cleaned = cleaned.convert("RGB")
            save_kwargs["quality"] = 95
            save_kwargs["subsampling"] = 0

        cleaned.save(out_path, format=fmt, **save_kwargs)
        print(f"[WatermarkRemover] {method} aplicado: {out_path.name}")

    return str(out_path)


if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) < 2:
        print("Uso: python gemini_watermark_remover.py <imagen> [salida]")
        sys.exit(1)
    result = remove_gemini_watermark(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"[OK] {result}")
