"""Natural Earth (dominio publico) + proyecciones. Sin shapely: todo con numpy."""
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "data"
R_EARTH = 6371.0


@lru_cache(maxsize=2)
def load(res="50m"):
    """{ADMIN: [poligono, ...]}; poligono = [anillo_exterior, agujero, ...]; anillo = array Nx2 (lon, lat)."""
    d = json.loads((DATA / f"ne_{res}_countries.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in d["features"]:
        g = f["geometry"]
        if not g:
            continue
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out[f["properties"]["ADMIN"]] = [[np.asarray(r, float)[:, :2] for r in poly] for poly in polys]
    return out


def ring_area(r):
    x, y = r[:, 0], r[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def bbox_center(ring):
    return ((ring[:, 0].min() + ring[:, 0].max()) / 2, (ring[:, 1].min() + ring[:, 1].max()) / 2)


def ang_dist_deg(lon1, lat1, lon2, lat2):
    p1, p2, dl = map(math.radians, (lat1, lat2, lon2 - lon1))
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def main_polys(polys, max_km=3000):
    """Quita territorios lejanos (Guayana francesa, Hawai...) para que el mapa quede enfocado."""
    areas = [ring_area(p[0]) for p in polys]
    big = int(np.argmax(areas))
    c0 = bbox_center(polys[big][0])
    keep = []
    for p, a in zip(polys, areas):
        c = bbox_center(p[0])
        if ang_dist_deg(*c0, *c) * 111.19 <= max_km or a >= 0.2 * max(areas):
            keep.append(p)
    return keep


def laea(lon, lat, lon0, lat0):
    """Lambert azimutal de area igual sobre la esfera unidad; y hacia el norte."""
    l = np.radians(np.asarray(lon, float) - lon0)
    p = np.radians(np.asarray(lat, float))
    p0 = math.radians(lat0)
    den = 1 + math.sin(p0) * np.sin(p) + math.cos(p0) * np.cos(p) * np.cos(l)
    k = np.sqrt(2 / np.maximum(den, 1e-6))
    return k * np.cos(p) * np.sin(l), k * (math.cos(p0) * np.sin(p) - math.sin(p0) * np.cos(p) * np.cos(l))


def laea_inv(x, y, lon0, lat0):
    x, y = np.asarray(x, float), np.asarray(y, float)
    p0 = math.radians(lat0)
    rho = np.maximum(np.hypot(x, y), 1e-9)
    c = 2 * np.arcsin(np.clip(rho / 2, 0, 1))
    lat = np.arcsin(np.clip(np.cos(c) * math.sin(p0) + y * np.sin(c) * math.cos(p0) / rho, -1, 1))
    lon = lon0 + np.degrees(np.arctan2(x * np.sin(c), rho * math.cos(p0) * np.cos(c) - y * math.sin(p0) * np.sin(c)))
    return lon, np.degrees(lat)


def ortho(lon, lat, lon0, lat0):
    """Proyeccion ortografica (globo): x, y en [-1,1] y visibilidad."""
    l = np.radians(np.asarray(lon, float) - lon0)
    p = np.radians(np.asarray(lat, float))
    p0 = math.radians(lat0)
    z = math.sin(p0) * np.sin(p) + math.cos(p0) * np.cos(p) * np.cos(l)
    return np.cos(p) * np.sin(l), math.cos(p0) * np.sin(p) - math.sin(p0) * np.cos(p) * np.cos(l), z > 0


class View:
    """Ajusta un pais a una caja de pixeles. px() devuelve coordenadas locales del panel."""

    def __init__(self, polys, panel_w, panel_h, margin_x=50, margin_y=45, center=None):
        allpts = np.vstack([r for p in polys for r in p[:1]])
        self.lon0, self.lat0 = center or ((allpts[:, 0].min() + allpts[:, 0].max()) / 2, (allpts[:, 1].min() + allpts[:, 1].max()) / 2)
        x, y = laea(allpts[:, 0], allpts[:, 1], self.lon0, self.lat0)
        self.cx, self.cy = (x.min() + x.max()) / 2, (y.min() + y.max()) / 2
        bw, bh = x.max() - x.min(), y.max() - y.min()
        self.S = min((panel_w - 2 * margin_x) / bw, (panel_h - 2 * margin_y) / bh)
        self.pw, self.ph = panel_w, panel_h
        self.km_per_px = R_EARTH / self.S

    def px(self, ring):
        x, y = laea(ring[:, 0], ring[:, 1], self.lon0, self.lat0)
        out = np.stack([(x - self.cx) * self.S + self.pw / 2, (self.cy - y) * self.S + self.ph / 2], 1)
        return np.clip(out, -20000, 20000)

    def lonlat_bounds(self):
        gx, gy = np.meshgrid(np.linspace(0, self.pw, 7), np.linspace(0, self.ph, 7))
        x = (gx - self.pw / 2) / self.S + self.cx
        y = self.cy - (gy - self.ph / 2) / self.S
        lon, lat = laea_inv(x, y, self.lon0, self.lat0)
        return lon.min(), lon.max(), lat.min(), lat.max()
