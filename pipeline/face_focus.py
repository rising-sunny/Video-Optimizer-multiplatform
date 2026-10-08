"""Donde esta la cara en una imagen, para centrar el retrato flotante en ella.

El circulo del retrato recortaba a ciegas (arriba al centro): con el oficial de un
clip real la cara estaba a la izquierda y el circulo mostraba el hombro. Aca se
busca la cara con los clasificadores Haar de OpenCV (de frente y de perfil, local,
sin cuota). Sin OpenCV o sin una cara clara devuelve None y el que llama decide
(el retrato de una persona pasa a punch-in: mejor que un circulo con un hombro).
"""

from __future__ import annotations

import os
from typing import Optional, Sequence, Tuple

# La cara ocupa esta fraccion del lado del circulo (deja frente, pelo y menton).
FACE_FILL = 0.55
# Una "cara" mas chica que esto respecto del lado menor es ruido (texturas, multitudes).
MIN_FACE_RATIO = 0.06


def _detector_files() -> Sequence[str]:
    import cv2
    base = cv2.data.haarcascades
    return [os.path.join(base, name) for name in (
        "haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml",
        "haarcascade_profileface.xml")]


def find_face(image_path: str) -> Optional[Tuple[float, float, float, float]]:
    """(x, y, w, h) en pixeles de la cara mas grande, o None."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    try:
        # cv2.imread no abre rutas con tildes en Windows ("el_triángulo_de_las_bermudas").
        img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        return None
    if img is None:
        return None
    gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    height, width = gray.shape[:2]
    min_side = max(24, int(min(width, height) * MIN_FACE_RATIO))
    found = []
    for path in _detector_files():
        cascade = cv2.CascadeClassifier(path)
        if cascade.empty():
            continue
        for flipped in ((False, True) if "profile" in path else (False,)):
            src = cv2.flip(gray, 1) if flipped else gray
            for (x, y, w, h) in cascade.detectMultiScale(src, scaleFactor=1.1, minNeighbors=6,
                                                         minSize=(min_side, min_side)):
                found.append((width - x - w if flipped else x, y, w, h))
    if not found:
        return None
    return tuple(float(v) for v in max(found, key=lambda f: f[2] * f[3]))


def face_box(image_size: Sequence[int], face: Sequence[float],
             fill: float = FACE_FILL) -> Tuple[float, float, float, float]:
    """Cuadrado (x0, y0, x1, y1) normalizado centrado en la cara, dentro de la imagen."""
    iw, ih = float(image_size[0]), float(image_size[1])
    x, y, w, h = (float(v) for v in face)
    side = min(max(w, h) / max(0.1, fill), iw, ih)
    cx, cy = x + w / 2, y + h / 2
    x0 = min(max(0.0, cx - side / 2), iw - side)
    y0 = min(max(0.0, cy - side / 2), ih - side)
    return (x0 / iw, y0 / ih, (x0 + side) / iw, (y0 + side) / ih)


def portrait_box(image_path: str) -> Optional[Tuple[float, float, float, float]]:
    """Recorte cuadrado normalizado para el retrato, centrado en la cara, o None."""
    face = find_face(image_path)
    if face is None:
        return None
    from PIL import Image
    with Image.open(image_path) as img:
        return face_box(img.size, face)
