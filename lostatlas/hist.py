"""Fronteras historicas: aourednik/historical-basemaps (GPL-3.0). Se descargan en ejecucion y NO se versionan.

Aviso del autor: es un trabajo en curso, las fronteras son aproximadas y discutidas; verificar antes de uso academico.
Por eso el pie de cada figura dice "Borders approximate" y la descripcion del video debe acreditar la fuente:
    Historical boundaries: aourednik/historical-basemaps (GPL-3.0) - github.com/aourednik/historical-basemaps
Los GeoJSON van a lostatlas/data/historical/ (en .gitignore); el video final solo contiene imagenes renderizadas.
"""
import json
import urllib.request
from pathlib import Path

import numpy as np

CACHE = Path(__file__).parent / "data" / "historical"
URL = "https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_{}.geojson"
ATTRIBUTION = ("Historical boundaries: aourednik/historical-basemaps (GPL-3.0)\n"
               "https://github.com/aourednik/historical-basemaps  (borders are approximate and disputed)")


def _features(map_year):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"world_{map_year}.geojson"
    if not f.exists():
        req = urllib.request.Request(URL.format(map_year), headers={"User-Agent": "Mozilla/5.0"})
        f.write_bytes(urllib.request.urlopen(req, timeout=90).read())
    return json.loads(f.read_text(encoding="utf-8"))["features"]


def _matches(props, select):
    return all(props.get(k) in (v if isinstance(v, (list, tuple)) else [v]) for k, v in select.items())


def load_dict(map_year, select, label):
    """{NOMBRE: [poligonos]} con los rasgos elegidos fusionados bajo `label` y quitados de los vecinos."""
    out, target = {}, []
    for f in _features(map_year):
        g, p = f["geometry"], f["properties"]
        if not g:
            continue
        coords = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        polys = [[np.asarray(r, float)[:, :2] for r in poly] for poly in coords]
        if _matches(p, select):
            target.extend(polys)
        else:
            out.setdefault(str(p.get("NAME")), []).extend(polys)
    if not target:
        raise SystemExit(f"world_{map_year}: nada coincide con {select}")
    out[label] = target
    return out
