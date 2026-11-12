"""Herramientas de imagen para documentales: ampliar fotos de archivo (Real-ESRGAN) y recortar sujetos (rembg).

- upscale(src, dst, scale=4, max_side=None): Real-ESRGAN x4plus (BSD-3, pesos en ~/apps/models) cargado con spandrel
  y torch en CPU, por bloques para no pasar de ~1 GB de RAM. Pensado para fotos chicas o escaneos de pocas lineas;
  NO inventa detalle historico confiable: usarlo para nitidez, nunca para "restaurar" lo que no se ve en el original.
- cutout(src, dst, model='isnet-general-use'): recorta el sujeto principal con fondo transparente (PNG), para miniaturas.

CLI:
  python -m documentary_kit.imgtools upscale foto.jpg foto_x4.png [--max-side 3840]
  python -m documentary_kit.imgtools cutout foto.jpg sujeto.png
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
from PIL import Image

MODELS = Path(os.getenv('IMGTOOLS_MODELS', str(Path.home() / 'apps/models')))
ESRGAN = MODELS / 'RealESRGAN_x4plus.pth'
TILE = int(os.getenv('IMGTOOLS_TILE', '256'))
_model = None


def _load():
    global _model
    if _model is None:
        import torch
        from spandrel import ModelLoader
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
        _model = ModelLoader(device='cpu').load_from_file(str(ESRGAN)).eval()   # torch.load con weights_only
    return _model


def _run_tiles(arr: np.ndarray, model, scale: int, tile: int, pad: int = 12) -> np.ndarray:
    import torch
    h, w, _ = arr.shape
    out = np.zeros((h * scale, w * scale, 3), dtype=np.float32)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            y0, x0 = max(0, y - pad), max(0, x - pad)
            y1, x1 = min(h, y + tile + pad), min(w, x + tile + pad)
            t = torch.from_numpy(arr[y0:y1, x0:x1].transpose(2, 0, 1)).unsqueeze(0)
            with torch.inference_mode():
                r = model(t)[0].clamp(0, 1).numpy().transpose(1, 2, 0)
            oy, ox = (y - y0) * scale, (x - x0) * scale
            th, tw = min(tile, h - y) * scale, min(tile, w - x) * scale
            out[y * scale:y * scale + th, x * scale:x * scale + tw] = r[oy:oy + th, ox:ox + tw]
    return out


def upscale(src, dst, scale: int = 4, max_side: int | None = None) -> Path:
    """Amplia x4 con Real-ESRGAN; si scale < 4 o max_side, reduce despues con LANCZOS."""
    model = _load()
    im = Image.open(src)
    gray = im.mode in ('L', 'LA', 'I;16', '1')
    rgb = np.asarray(im.convert('RGB'), dtype=np.float32) / 255.0
    out = _run_tiles(rgb, model, 4, TILE)
    res = Image.fromarray((out * 255.0 + 0.5).clip(0, 255).astype(np.uint8))
    target = (im.width * scale, im.height * scale)
    if max_side and max(target) > max_side:
        k = max_side / max(target)
        target = (int(target[0] * k), int(target[1] * k))
    if res.size != target:
        res = res.resize(target, Image.LANCZOS)
    if gray:
        res = res.convert('L')
    dst = Path(dst)
    res.save(dst)
    return dst


def cutout(src, dst, model: str = 'isnet-general-use') -> Path:
    """PNG con el sujeto principal y fondo transparente."""
    from rembg import new_session, remove
    with Image.open(src) as im:
        res = remove(im.convert('RGB'), session=new_session(model))
    dst = Path(dst)
    res.save(dst.with_suffix('.png'))
    return dst.with_suffix('.png')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Ampliar (Real-ESRGAN) o recortar (rembg) imagenes')
    sub = ap.add_subparsers(dest='cmd', required=True)
    u = sub.add_parser('upscale'); u.add_argument('src'); u.add_argument('dst'); u.add_argument('--scale', type=int, default=4); u.add_argument('--max-side', type=int)
    c = sub.add_parser('cutout'); c.add_argument('src'); c.add_argument('dst'); c.add_argument('--model', default='isnet-general-use')
    a = ap.parse_args(argv)
    print(upscale(a.src, a.dst, a.scale, a.max_side) if a.cmd == 'upscale' else cutout(a.src, a.dst, a.model))


if __name__ == '__main__':
    main()
