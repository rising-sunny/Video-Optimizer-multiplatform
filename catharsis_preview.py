"""Small composition previews using the same cards, crops and effects as the renderer.

These are still references. Transitions, timing and audio are shown by the rendered preview.
No global render dimensions are changed; rendering and preview workers may run together.
"""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

import catharsis_editor as ce


def composition_preview(project, spec, size=(144, 256)):
    media = project.get("media", [])
    stamps = []
    for item in media:
        try:
            stat = Path(item["file"]).stat()
            stamps.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamps.append(None)
    payload = json.dumps({"media": media, "style": project["style"], "spec": spec,
                          "stamps": stamps}, sort_keys=True)
    return _cached_composition(payload, tuple(size)).copy()


@lru_cache(maxsize=128)
def _cached_composition(payload, size):
    data = json.loads(payload)
    spec = dict(data["spec"], transition="cut")
    spec["seconds"] = max(0.1, float(spec.get("seconds", 1)))
    shots, _ = ce.build_shots(data, [spec])
    shot = shots[-1]
    image = shot.image.convert("RGBA")
    if shot.text_layer is not None:
        image = Image.alpha_composite(image, shot.text_layer)
    image = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    if shot.grain:
        pixels = np.asarray(image, dtype=np.float32)
        if data["style"].get("vignette", True):
            w, h = size
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            shade = 1 - .42 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 2
            pixels *= shade[..., None]
        pixels += np.random.default_rng(11).normal(0, 2, (*pixels.shape[:2], 1))
        image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))
    return image
