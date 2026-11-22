"""Musica de Incompetech (Kevin MacLeod, CC BY 4.0) con su atribucion lista para la descripcion.

Politica del repo (publish/music_license.py): CC0 / CC BY / CC BY-SA sirven; la atribucion va en la descripcion.
Riesgo honesto: un tercero (p. ej. un distribuidor) puede registrar el tema en Content ID. Si llega un reclamo,
poner el credito en la descripcion y disputar (ver incompetech.com/music/royalty-free/youtube-contentid.html).
Cero riesgo solo da la Biblioteca de Audio de YouTube: bajar el MP3 desde Studio y pasarlo con --bgm <ruta>.
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(__file__).parent / "data" / "music"
BASE = "https://incompetech.com/music/royalty-free/"
UA = {"User-Agent": "Mozilla/5.0"}


def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()


def catalog():
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / "pieces.json"
    if not f.exists():
        f.write_bytes(_get(BASE + "pieces.json"))
    return json.loads(f.read_text(encoding="utf-8"))


def fetch(title):
    """Descarga (con cache) una pieza por titulo exacto. Devuelve (ruta_mp3, atribucion)."""
    piece = next((p for p in catalog() if p["title"].lower() == title.lower()), None)
    if not piece:
        raise SystemExit(f"Incompetech no tiene '{title}'")
    mp3 = CACHE / piece["filename"]
    if not mp3.exists():
        mp3.write_bytes(_get(BASE + "mp3-royaltyfree/" + urllib.parse.quote(piece["filename"])))
    attribution = (f'"{piece["title"]}" Kevin MacLeod (incompetech.com)\n'
                   "Licensed under Creative Commons: By Attribution 4.0 License\n"
                   "http://creativecommons.org/licenses/by/4.0/")
    return mp3, attribution, piece
