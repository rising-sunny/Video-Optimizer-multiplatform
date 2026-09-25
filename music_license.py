# -*- coding: utf-8 -*-
"""Musica de Jamendo que se puede usar en YouTube, y su atribucion.

Por que existe (2026-09-24). Videos bloqueados en todo el mundo por reclamos
de derechos de autor (WAMI_CS, MINT, BMI) sobre "The Prophecy" de Paul Werner,
elegido desde el buscador de Jamendo de la app. La API de Jamendo dice de ese
tema: licencia CC BY-NC-ND y `content_id_free: false`. La app aceptaba
CUALQUIER licencia Creative Commons, y dos de ellas no sirven para un video:

  - NC (no comercial): un canal monetizado es uso comercial;
  - ND (sin obras derivadas): Creative Commons considera que sincronizar una
    cancion con imagen en movimiento ES una obra derivada, asi que un tema ND
    no se puede poner en un video, ni siquiera sin monetizar.

Quedan CC BY y CC BY-SA (y CC0): uso comercial y en video permitidos, con la
atribucion en la descripcion. La API filtra con `ccnc=false&ccnd=false`.

Limite honesto: Jamendo marca `content_id_free` solo en temas NC-ND (inutiles
aca). En los CC BY / BY-SA el campo viene en false porque el artista no lo
declaro, no porque este registrado. La mayoria no esta en Content ID, pero si un
artista registro su musica, el reclamo llega igual. Para eso esta la lista de
artistas reclamados (`daily_shorts/music_claims.json`): quien reclamo una vez
no vuelve a aparecer. Cero riesgo solo da la Biblioteca de Audio de YouTube
(se carga como "Musica Local").

Funciones puras con la red inyectable. Ver `test_music_license.py`.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Parametros de la API de Jamendo que dejan solo CC BY y CC BY-SA.
JAMENDO_SAFE_PARAMS = {"ccnc": "false", "ccnd": "false"}

USABLE_LICENSES = ("CC0", "CC BY", "CC BY-SA")

CLAIMS_PATH = Path(__file__).resolve().parent / "daily_shorts" / "music_claims.json"

# Limites de descripcion por plataforma (la atribucion nunca se recorta).
DESCRIPTION_LIMITS = {"youtube": 5000, "facebook": 2200, "instagram": 2200}

_TRACK_URL_RE = re.compile(r"(?:trackid=|/track/|jamen\.do/t/)(\d+)")


# ------------------------------------------------------------------ licencia

def license_code(url: Any) -> str:
    """'http://creativecommons.org/licenses/by-nc-nd/3.0/' -> 'CC BY-NC-ND'."""
    text = str(url or "").lower().strip()
    if not text:
        return "UNKNOWN"
    if "publicdomain/zero" in text or "/zero/" in text:
        return "CC0"
    for code in ("by-nc-nd", "by-nc-sa", "by-nc", "by-nd", "by-sa", "by"):
        if f"/licenses/{code}/" in text:
            return "CC " + code.upper()
    return "UNKNOWN"


def license_version(url: Any) -> str:
    m = re.search(r"/(\d+\.\d+)(?:/|$)", str(url or ""))
    return m.group(1) if m else ""


def track_license_code(track: Dict) -> str:
    """Licencia de un tema: manda la URL de la licencia; si no hay, el codigo guardado."""
    t = track or {}
    code = str(t.get("license_code") or "").strip().upper()
    if code == "LOCAL":
        return "LOCAL"
    from_url = license_code(t.get("license_url") or t.get("license_ccurl"))
    if from_url != "UNKNOWN":
        return from_url
    return code if code.startswith("CC") else "UNKNOWN"


def license_problem(code: str) -> Optional[str]:
    """Por que un tema NO sirve para un video de YouTube (None si sirve)."""
    code = str(code or "").upper()
    if code in USABLE_LICENSES:
        return None
    if code in ("", "UNKNOWN"):
        return "licencia desconocida"
    problems = []
    if "-NC" in code:
        problems.append("no comercial (NC): no se puede usar en un canal monetizado")
    if "-ND" in code:
        problems.append("sin obras derivadas (ND): ponerla en un video ya es una obra derivada")
    return "; ".join(problems) or f"licencia {code} no apta para video"


def usable_in_video(track: Dict) -> bool:
    return license_problem(track_license_code(track)) is None


# ------------------------------------------------------------------ identidad

def track_id(track: Dict) -> str:
    t = track or {}
    for key in ("track_id", "id"):
        val = str(t.get(key) or "").strip()
        if val.isdigit():
            return val
    for key in ("share_url", "shareurl", "short_url", "shorturl", "audio_url", "audio", "prourl"):
        m = _TRACK_URL_RE.search(str(t.get(key) or ""))
        if m:
            return m.group(1)
    return ""


def track_url(track: Dict) -> str:
    t = track or {}
    for key in ("share_url", "shareurl"):
        if t.get(key):
            return str(t[key])
    tid = track_id(t)
    return f"https://www.jamendo.com/track/{tid}" if tid else ""


def _norm_name(text: Any) -> str:
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


# ------------------------------------------------------------------ atribucion

def attribution_text(track: Dict) -> str:
    """Credito en ingles para la descripcion (titulo, autor, fuente, licencia)."""
    t = track or {}
    title = str(t.get("title") or t.get("name") or "").strip() or "Untitled"
    artist = str(t.get("artist") or t.get("artist_name") or "").strip() or "Unknown artist"
    code = track_license_code(t)
    url = str(t.get("license_url") or t.get("license_ccurl") or "").strip()
    lines = [f'Music: "{title}" by {artist}']
    link = track_url(t)
    if link:
        lines.append(f"Source: {link} (Jamendo)")
    if code.startswith("CC") and code != "CC0":
        version = license_version(url)
        canonical = url.replace("http://", "https://") if url else ""
        lines.append(f"License: {code}{(' ' + version) if version else ''}" + (f" ({canonical})" if canonical else ""))
    elif code == "CC0":
        lines.append("License: CC0 (public domain)")
    return "\n".join(lines)


def _split_trailing_hashtags(text: str) -> Tuple[str, str]:
    lines = str(text or "").rstrip().split("\n")
    tail: List[str] = []
    while lines and lines[-1].strip() and all(w.startswith("#") for w in lines[-1].split()):
        tail.insert(0, lines.pop())
    return "\n".join(lines).rstrip(), "\n".join(tail)


def with_attribution(description: Any, attribution: Any, limit: int = 5000) -> str:
    """Agrega la atribucion antes de los hashtags finales, sin recortarla nunca.

    Si no entra, se recorta el cuerpo de la descripcion. Idempotente: si la
    primera linea de la atribucion ya esta, no la repite.
    """
    desc = str(description or "").strip()
    attr = str(attribution or "").strip()
    if not attr:
        return desc
    first = attr.split("\n", 1)[0].strip()
    if first and first in desc:
        return desc
    body, hashtags = _split_trailing_hashtags(desc)
    tail = "\n\n".join(p for p in (attr, hashtags) if p)
    room = limit - len(tail) - 2
    if room <= 0:
        return tail[:limit]
    if len(body) > room:
        cut = body[:room]
        stop = max(cut.rfind(". "), cut.rfind("\n"))
        body = (cut[:stop + 1] if stop > room * 0.5 else cut.rsplit(" ", 1)[0]).rstrip()
    return "\n\n".join(p for p in (body, tail) if p)


# ------------------------------------------------------------------ reclamos

def load_claims(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path or CLAIMS_PATH)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("artists", [])
    data.setdefault("tracks", [])
    return data


def is_blocked(track: Dict, claims: Optional[Dict] = None) -> Tuple[bool, str]:
    """El tema o su artista ya genero un reclamo de Content ID?"""
    claims = claims if claims is not None else load_claims()
    t = track or {}
    tid = track_id(t)
    for entry in claims.get("tracks") or []:
        if tid and str(entry.get("track_id")) == tid:
            return True, f"el tema ya genero un reclamo ({entry.get('claimants') or 'Content ID'})"
    artist_id = str(t.get("artist_id") or "").strip()
    artist = _norm_name(t.get("artist") or t.get("artist_name"))
    for entry in claims.get("artists") or []:
        if artist_id and str(entry.get("artist_id") or "") == artist_id:
            return True, f"el artista registro su musica en Content ID ({entry.get('claimants') or 'reclamo previo'})"
        if artist and _norm_name(entry.get("name")) == artist:
            return True, f"el artista registro su musica en Content ID ({entry.get('claimants') or 'reclamo previo'})"
    return False, ""


def record_claim(track: Dict, claimants: str = "", note: str = "", path: Optional[Path] = None) -> Dict:
    """Anota que un tema recibio un reclamo: se bloquea el tema y su artista."""
    p = Path(path or CLAIMS_PATH)
    data = load_claims(p)
    t = track or {}
    today = time.strftime("%Y-%m-%d")
    tid = track_id(t)
    if tid and not any(str(e.get("track_id")) == tid for e in data["tracks"]):
        data["tracks"].append({"track_id": tid, "title": t.get("title") or t.get("name") or "",
                               "artist": t.get("artist") or t.get("artist_name") or "",
                               "claimants": claimants, "date": today, "note": note})
    name = t.get("artist") or t.get("artist_name") or ""
    artist_id = str(t.get("artist_id") or "")
    known = any((artist_id and str(e.get("artist_id") or "") == artist_id) or
                (name and _norm_name(e.get("name")) == _norm_name(name)) for e in data["artists"])
    if (name or artist_id) and not known:
        data["artists"].append({"artist_id": artist_id, "name": name, "claimants": claimants,
                                "date": today, "note": note})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


# ------------------------------------------------------------------ busqueda

def filter_tracks(tracks: List[Dict], claims: Optional[Dict] = None) -> Tuple[List[Dict], List[Tuple[Dict, str]]]:
    """(aptos, [(descartado, motivo)]). Aptos llevan license_code y attribution_text."""
    claims = claims if claims is not None else load_claims()
    kept, dropped = [], []
    for track in tracks or []:
        code = track_license_code(track)
        problem = license_problem(code)
        if problem:
            dropped.append((track, problem))
            continue
        blocked, why = is_blocked(track, claims)
        if blocked:
            dropped.append((track, why))
            continue
        t = dict(track)
        t["license_code"] = code
        t["youtube_safe"] = True
        t["attribution_required"] = code != "CC0"
        t["attribution_text"] = attribution_text(t)
        kept.append(t)
    return kept, dropped


def lookup_jamendo_track(tid: str, client_id: str, http_get: Optional[Callable] = None) -> Dict:
    """Datos de licencia de un tema por su id (para proyectos viejos sin licencia guardada)."""
    if not tid or not client_id:
        return {}
    if http_get is None:
        import requests

        def http_get(url, params):
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
    data = http_get("https://api.jamendo.com/v3.0/tracks/",
                    {"client_id": client_id, "format": "json", "id": tid, "include": "licenses"})
    results = (data or {}).get("results") or []
    return results[0] if results else {}


# ------------------------------------------------------------------ subida

def check_music_for_upload(music: Optional[Dict], *, client_id: str = "",
                           http_get: Optional[Callable] = None,
                           claims: Optional[Dict] = None) -> Dict[str, Any]:
    """Veredicto sobre la musica de un video antes de subirlo.

    status: "none" (sin musica), "local" (archivo propio: responsabilidad del
    usuario), "ok" (apto; trae la atribucion), "risky" (NC/ND, artista reclamado
    o licencia que no se pudo confirmar).
    """
    if not music:
        return {"status": "none", "reason": "", "attribution": ""}
    track = dict(music)
    source = str(track.get("source") or "").lower()
    code = track_license_code(track)
    if source == "local" or code == "LOCAL":
        return {"status": "local", "reason": "archivo local: asegurate de tener los derechos",
                "attribution": ""}
    if code == "UNKNOWN":
        tid = track_id(track)
        try:
            info = lookup_jamendo_track(tid, client_id, http_get=http_get) if tid else {}
        except Exception:
            info = {}
        if info:
            track["license_url"] = info.get("license_ccurl", "")
            track["artist_id"] = track.get("artist_id") or info.get("artist_id", "")
            track["share_url"] = track.get("share_url") or info.get("shareurl", "")
            code = license_code(track["license_url"])
            track["license_code"] = code
    blocked, why = is_blocked(track, claims)
    problem = license_problem(code)
    attribution = attribution_text(track) if code != "UNKNOWN" else ""
    if blocked or problem:
        reason = "; ".join(r for r in (why, problem) if r)
        return {"status": "risky", "reason": reason, "attribution": attribution, "track": track,
                "license_code": code}
    return {"status": "ok", "reason": "", "attribution": attribution, "track": track, "license_code": code}


__all__ = [
    "JAMENDO_SAFE_PARAMS", "USABLE_LICENSES", "license_code", "license_version", "track_license_code",
    "license_problem", "usable_in_video", "track_id", "track_url", "attribution_text", "with_attribution",
    "load_claims", "is_blocked", "record_claim", "filter_tracks", "lookup_jamendo_track",
    "check_music_for_upload", "DESCRIPTION_LIMITS",
]


if __name__ == "__main__":
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Licencias de musica de Jamendo para YouTube")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="licencia y atribucion de un tema (id o URL de Jamendo)")
    c.add_argument("track")
    r = sub.add_parser("claim", help="anotar un reclamo de Content ID (bloquea tema y artista)")
    r.add_argument("track")
    r.add_argument("--claimants", default="")
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except Exception:
        pass
    m = _TRACK_URL_RE.search(args.track)
    tid = m.group(1) if m else args.track.strip()
    info = lookup_jamendo_track(tid, os.getenv("JAMENDO_CLIENT_ID", ""))
    track = {"track_id": tid, "title": info.get("name", ""), "artist": info.get("artist_name", ""),
             "artist_id": info.get("artist_id", ""), "license_url": info.get("license_ccurl", ""),
             "share_url": info.get("shareurl", "")}
    if args.cmd == "check":
        verdict = check_music_for_upload(track)
        print(f"{track['title']} - {track['artist']}: {track_license_code(track)} -> {verdict['status']}"
              + (f" ({verdict['reason']})" if verdict["reason"] else ""))
        if verdict["attribution"]:
            print(verdict["attribution"])
    else:
        record_claim(track, claimants=args.claimants)
        print(f"Bloqueados el tema {tid} y el artista {track['artist'] or '?'}")
