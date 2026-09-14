# -*- coding: utf-8 -*-
"""Compatibilidad moviepy 1.0.3 <-> Pillow >= 10.

Pillow 10 elimino las constantes `Image.ANTIALIAS` / `BICUBIC` / `LINEAR`, pero
moviepy 1.0.3 todavia las usa en `video/fx/resize.py`. Sin cv2 instalado el
resizer de moviepy ES el de PIL, asi que CUALQUIER `clip.resize(...)` levanta
`AttributeError: module 'PIL.Image' has no attribute 'ANTIALIAS'`.

Por que importa: los efectos cinematograficos y el Ken Burns son puro resize.
La excepcion la terminaba tragando un `except Exception` del bucle de clips, asi
que el sintoma no era un crash sino stills congelados (o clips faltantes) sin
un solo error en el log.

Importar este modulo antes de usar moviepy. Es idempotente.
"""

from __future__ import annotations


def ensure_pillow_compat() -> dict:
    """Restaura los alias que moviepy espera. Devuelve los que hizo falta poner."""
    restored = {}
    try:
        from PIL import Image
    except ImportError:
        return restored

    # Pillow >= 9.1 los movio a Image.Resampling; >= 10 borro los viejos.
    resampling = getattr(Image, "Resampling", Image)
    for old, new in (
        ("ANTIALIAS", "LANCZOS"),
        ("LINEAR", "BILINEAR"),
        ("CUBIC", "BICUBIC"),
        ("NEAREST", "NEAREST"),
        ("BILINEAR", "BILINEAR"),
        ("BICUBIC", "BICUBIC"),
        ("LANCZOS", "LANCZOS"),
    ):
        if hasattr(Image, old):
            continue
        value = getattr(resampling, new, None)
        if value is not None:
            setattr(Image, old, value)
            restored[old] = new

    return restored


_RESTORED = ensure_pillow_compat()

__all__ = ["ensure_pillow_compat"]
