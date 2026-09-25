# -*- coding: utf-8 -*-
"""Bucle de datos: que esta funcionando AHORA, medido, y en un JSON que lean los prompts.

Hasta 2026-09-21 la estrategia editorial (Channel Bible) se escribio una vez, a
mano, con los 223 videos del canal anterior, y el pipeline le pedia al modelo
exactamente lo que en el canal nuevo moria ("Vanished / Erased", "THE CURSE",
"The Tunguska Mystery"). Este modulo hace lo que ese dia se hizo a mano:

  YouTube Analytics (vistas, engagedViews, retencion, subs por video)
  + Facebook Graph (plays, tiempo medio, retencion 25/50/75, seguidores por reel)
  + cada project.json (tema, categoria, angulo, formato, duracion)
  -> daily_shorts/performance_snapshot.json

con winners/losers, agregados por ANGULO (format_archetype), categoria y
duracion, diferencias YouTube/Facebook, recomendaciones y pesos. Lo consumen
`channel_strategy.build_performance_prompt_block()` (entra al prompt del guion)
y `build_category_weight_map()` (mezcla de temas del pipeline diario).

    .venv\\Scripts\\python.exe performance_feedback.py              # 30 dias, YT + FB
    .venv\\Scripts\\python.exe performance_feedback.py --dias 60 --sin-facebook

Las funciones de clasificacion, cruce, agregacion y recomendacion son puras:
ver `test_performance_feedback.py`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT / "daily_shorts" / "performance_snapshot.json"

# Umbral empirico (2026-09): en YouTube un short o pasa de ~300 vistas en 24 h o
# se queda en <50. No hay termino medio: "despego" es binario.
TAKEOFF_VIEWS = 300
DEAD_VIEWS = 50

ARCHETYPES = ("mechanism", "discovery", "human_story", "scale_event")
ARCHETYPE_LABELS = {
    "mechanism": "Como lo hicieron (mecanismo)",
    "discovery": "Hallazgo arqueologico (noticia)",
    "human_story": "Historia humana (escape, supervivencia, engano)",
    "scale_event": "Evento con cifra",
    "unknown": "Sin clasificar",
}

# ----------------------------------------------------------------------------
# Clasificacion por titulo (para lo ya publicado; los proyectos nuevos traen
# `format_archetype` en config y ese manda).
# ----------------------------------------------------------------------------
_RE_DISCOVERY = re.compile(
    r"\b(discover|discovers|discovered|found|unearth|archaeolog|excavat|revealed|dig up|tomb|"
    r"lost city|hidden city|secret city|buried city|artifact|scrolls?)\b", re.I)
_RE_MECHANISM = re.compile(
    r"^(how|why)\b|\b(how did|how do|how does|why did|why do|why does|why were|why was|how were|how was|"
    r"worked|engineer|engineering|built like|the real reason|actually)\b", re.I)
_RE_HUMAN = re.compile(
    r"\b(survived|survivor|escaped|escape|the man who|the woman who|the only|alone|without a parachute|"
    r"surrender|surrendered|prisoner|spy|saboteur|ghost army|lived to|the boy who|the girl who|"
    r"he fell|she fell|his last|her last)\b", re.I)
_RE_SCALE = re.compile(
    r"\d[\d,\.]*\s*(kt|kiloton|megaton|tons?|people|inhabitants|troops|soldiers|flights|men|dead|"
    r"magnitude|meters?|metres?|km|miles|ft|feet|years?|days?|hours?|islets|pyramids|mongols|ships)\b", re.I)
_RE_EVENT = re.compile(
    r"\b(battle|siege|sack|explosion|blast|eruption|bomb|war|conquers?|attack|invasion|disaster|"
    r"earthquake|flood|fire|air ?bridge|airlift)\b", re.I)
_RE_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-2][0-9])\b|\b\d{3,4}\s*(bc|bce|ad|ce)\b", re.I)

# Etiquetas de riesgo: lo que en YouTube murio de forma consistente (sep-2026).
_RE_MODERN_DISASTER = re.compile(
    r"\b(explosion|blast|earthquake|eruption|flood|disaster|shockwave|flattened|shattered)\b", re.I)
_RE_MYSTERY = re.compile(
    r"\b(mystery|mysterious|mysteries|unexplained|curse|cursed|vanished|paranormal|ufo|invaders who)\b", re.I)


_RE_ANCIENT = re.compile(r"\b(bc|bce|ancient|antig\w*|medieval|roman|bronze age)\b", re.I)


def _looks_modern(title: str) -> bool:
    """Un desastre es moderno salvo que el titulo lo marque antiguo (a.C., 'ancient', ano < 1850)."""
    if _RE_ANCIENT.search(title or ""):
        return False
    for m in re.finditer(r"\b(\d{3,4})\b", title or ""):
        year = int(m.group(1))
        if 500 <= year < 1850:
            return False
    return True


def classify_archetype(title: str, description: str = "") -> str:
    """Angulo narrativo de un titulo ya publicado. Orden: hallazgo > mecanismo > humano > evento."""
    text = f"{title or ''} {description or ''}".strip()
    head = (title or "").strip()
    if not head:
        return "unknown"
    if _RE_DISCOVERY.search(head):
        return "discovery"
    if _RE_MECHANISM.search(head):
        return "mechanism"
    if _RE_HUMAN.search(head):
        return "human_story"
    if _RE_SCALE.search(head) or (_RE_YEAR.search(head) and _RE_EVENT.search(head)) or _RE_EVENT.search(head):
        return "scale_event"
    if _RE_YEAR.search(text):
        return "scale_event"
    return "unknown"


def tag_risks(title: str) -> list[str]:
    """Etiquetas de encuadre que en YouTube Shorts murieron: desastre moderno, misterio."""
    tags = []
    t = title or ""
    if _RE_MODERN_DISASTER.search(t) and _looks_modern(t):
        tags.append("modern_disaster")
    if _RE_MYSTERY.search(t):
        tags.append("mystery_framing")
    return tags


def duration_bucket(seconds: float) -> str:
    s = float(seconds or 0)
    if s <= 0:
        return "unknown"
    if s <= 45:
        return "<=45s"
    if s <= 70:
        return "46-70s"
    if s <= 95:
        return "71-95s"
    if s <= 180:
        return "96-180s"
    return ">180s"


# ----------------------------------------------------------------------------
# Proyectos: lo que la app sabe de cada video (tema, categoria, angulo...)
# ----------------------------------------------------------------------------
def _norm(text: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def load_projects(roots: Iterable[Path] = ()) -> list[dict[str, Any]]:
    """Lee projects/*/project.json y daily_shorts/*/{project,storyboard}.json."""
    roots = list(roots) or [ROOT / "projects", ROOT / "daily_shorts"]
    out = []
    for base in roots:
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir()):
            if not folder.is_dir():
                continue
            for name in ("project.json", "storyboard.json"):
                path = folder / name
                if not path.is_file():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                cfg = data.get("config") or {}
                sb = data.get("storyboard") if isinstance(data.get("storyboard"), dict) else data
                try:
                    from video_opening import opening_style
                    opening = opening_style(sb)
                except Exception:
                    opening = ""
                gv = data.get("generated_video_data") or {}
                pub = data.get("publish_results") or {}
                out.append({
                    "path": str(path),
                    "folder": folder.name,
                    "topic": cfg.get("topic") or sb.get("topic") or gv.get("topic") or "",
                    "category": cfg.get("category") or sb.get("category") or gv.get("category") or "",
                    "format_archetype": cfg.get("format_archetype") or sb.get("format_archetype") or "",
                    "format_strategy": cfg.get("format_strategy") or "",
                    "video_format": cfg.get("video_format") or sb.get("video_format") or "",
                    "platform_key": cfg.get("platform_key") or cfg.get("platform") or "",
                    "channel_profile": cfg.get("channel_profile") or "",
                    "opening": opening,
                    "youtube_video_id": (pub.get("youtube") or {}).get("video_id") or "",
                    "facebook_reel_id": (pub.get("facebook") or {}).get("id") or (pub.get("facebook") or {}).get("video_id") or "",
                })
                break
    return out


def match_project(title: str, projects: list[dict[str, Any]], video_id: str = "",
                  reel_id: str = "", min_ratio: float = 0.55) -> Optional[dict[str, Any]]:
    """Primero por id publicado; si no, por parecido entre titulo y tema."""
    if video_id:
        for p in projects:
            if p.get("youtube_video_id") == video_id:
                return p
    if reel_id:
        for p in projects:
            if p.get("facebook_reel_id") == reel_id:
                return p
    nt = _norm(title)
    if not nt:
        return None
    best, best_ratio = None, 0.0
    for p in projects:
        topic = _norm(p.get("topic", ""))
        if not topic:
            continue
        ratio = difflib.SequenceMatcher(None, nt, topic).ratio()
        # tokens del tema que aparecen en el titulo (Catalhoyuk, Halifax, Kaiten...)
        toks = [w for w in topic.split() if len(w) >= 5]
        if toks:
            hit = sum(1 for w in toks if w in nt) / len(toks)
            ratio = max(ratio, hit)
        if ratio > best_ratio:
            best, best_ratio = p, ratio
    return best if best_ratio >= min_ratio else None


# ----------------------------------------------------------------------------
# Enriquecer filas (angulo, etiquetas, proyecto) y agregar
# ----------------------------------------------------------------------------
def enrich_rows(rows: list[dict[str, Any]], projects: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        row = dict(r)
        p = match_project(row.get("title", ""), projects, video_id=row.get("video_id", "") if platform == "youtube" else "",
                          reel_id=row.get("reel_id", "") if platform == "facebook" else "")
        row["project"] = p["folder"] if p else None
        row["category"] = (p or {}).get("category") or row.get("category") or ""
        arche = (p or {}).get("format_archetype") or classify_archetype(row.get("title", ""), row.get("description", ""))
        row["archetype"] = arche if arche in ARCHETYPES else "unknown"
        row["risk_tags"] = tag_risks(row.get("title", ""))
        # Arranque del video (video_opening): placa vieja vs texto de gancho, para el A/B.
        row["opening"] = (p or {}).get("opening") or "unknown"
        row["duration_bucket"] = duration_bucket(row.get("duration", 0))
        row["is_vertical"] = bool(row.get("is_vertical", True))
        if platform == "youtube":
            v = float(row.get("views") or 0)
            row["took_off"] = v >= TAKEOFF_VIEWS
            row["dead"] = v < DEAD_VIEWS
            ev = float(row.get("engaged_views") or 0)
            row["engaged_pct"] = round(100 * ev / v, 1) if v > 0 and ev else None
            row["subs_per_1k"] = round(1000 * float(row.get("subs") or 0) / v, 2) if v > 0 else 0.0
        out.append(row)
    return out


def _median(values: list[float]) -> float:
    vals = [float(v) for v in values if v is not None]
    return round(statistics.median(vals), 1) if vals else 0.0


def summarize(rows: list[dict[str, Any]], key: str, platform: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        k = r.get(key) or "unknown"
        if isinstance(k, list):
            for kk in (k or ["none"]):
                groups.setdefault(kk, []).append(r)
        else:
            groups.setdefault(k, []).append(r)
    out = {}
    for k, rs in groups.items():
        n = len(rs)
        if platform == "youtube":
            out[k] = {
                "n": n,
                "median_views": _median([r.get("views") for r in rs]),
                "takeoff_rate": round(sum(1 for r in rs if r.get("took_off")) / n, 2),
                "dead_rate": round(sum(1 for r in rs if r.get("dead")) / n, 2),
                "median_engaged_pct": _median([r.get("engaged_pct") for r in rs if r.get("engaged_pct") is not None]),
                "median_avg_view_pct": _median([r.get("avg_view_pct") for r in rs if r.get("avg_view_pct") is not None]),
                "subs_per_1k": round(1000 * sum(float(r.get("subs") or 0) for r in rs) / max(1.0, sum(float(r.get("views") or 0) for r in rs)), 2),
                "views_total": int(sum(float(r.get("views") or 0) for r in rs)),
            }
        else:
            out[k] = {
                "n": n,
                "median_plays": _median([r.get("plays") for r in rs]),
                "median_avg_watch_s": _median([r.get("avg_watch_s") for r in rs]),
                "median_retention_25": _median([r.get("retention_25") for r in rs if r.get("retention_25") is not None]),
                "followers_total": int(sum(float(r.get("followers") or 0) for r in rs)),
                "plays_total": int(sum(float(r.get("plays") or 0) for r in rs)),
            }
    return out


def score_archetypes(by_archetype: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Puntaje 0..1 por angulo en YouTube: despegue, permanencia y conversion a subs."""
    scores = {}
    for k, s in by_archetype.items():
        if k == "unknown" or s.get("n", 0) < 2:
            continue
        takeoff = float(s.get("takeoff_rate") or 0)
        engaged = float(s.get("median_engaged_pct") or 0) / 100.0
        subs = min(1.0, float(s.get("subs_per_1k") or 0) / 10.0)
        scores[k] = round(0.5 * takeoff + 0.3 * engaged + 0.2 * subs, 3)
    return scores


def recommend(yt_rows: list[dict[str, Any]], fb_rows: list[dict[str, Any]], yt_summary: dict[str, Any],
              fb_summary: dict[str, Any]) -> dict[str, Any]:
    """Reglas explicitas, no magia: cada recomendacion cita el dato que la sostiene."""
    lean, avoid, notes = [], [], []
    by_arch = yt_summary.get("by_archetype", {})
    scores = score_archetypes(by_arch)
    for k, sc in sorted(scores.items(), key=lambda kv: -kv[1])[:2]:
        s = by_arch[k]
        lean.append({"archetype": k, "label": ARCHETYPE_LABELS.get(k, k), "score": sc,
                     "why": f"{s['n']} videos: despegan {int(s['takeoff_rate']*100)}%, permanencia {s['median_engaged_pct']}%, {s['subs_per_1k']} subs/1k"})
    for k, sc in sorted(scores.items(), key=lambda kv: kv[1]):
        s = by_arch[k]
        if s.get("n", 0) >= 3 and float(s.get("takeoff_rate") or 0) <= 0.2:
            avoid.append({"what": k, "label": ARCHETYPE_LABELS.get(k, k),
                          "why": f"{s['n']} videos, solo {int(s['takeoff_rate']*100)}% despego"})
    for tag, s in yt_summary.get("by_risk", {}).items():
        if tag == "none":
            continue
        if s.get("n", 0) >= 3 and float(s.get("takeoff_rate") or 0) <= 0.25:
            avoid.append({"what": tag, "label": {"modern_disaster": "desastre/explosion moderna como eje",
                                                  "mystery_framing": "encuadre de misterio"}.get(tag, tag),
                          "why": f"{s['n']} shorts, {int(s['takeoff_rate']*100)}% despego, mediana {int(s['median_views'])} vistas"})
    horiz = [r for r in yt_rows if not r.get("is_vertical")]
    if len(horiz) >= 2 and all(float(r.get("views") or 0) < TAKEOFF_VIEWS for r in horiz):
        avoid.append({"what": "youtube_16_9_only", "label": "subir el 16:9 sin version vertical",
                      "why": f"{len(horiz)} videos 16:9 en YouTube, ninguno paso de {TAKEOFF_VIEWS} vistas"})
    # Facebook: lo que alli explota
    if fb_rows:
        plays = [float(r.get("plays") or 0) for r in fb_rows]
        med = statistics.median(plays) if plays else 0
        for r in sorted(fb_rows, key=lambda r: -float(r.get("plays") or 0))[:3]:
            if med and float(r.get("plays") or 0) >= 5 * med:
                notes.append(f"Facebook: '{(r.get('title') or '')[:60]}' hizo {int(r['plays'])} plays "
                             f"({int(float(r['plays'])/med)}x la mediana){' siendo 16:9' if not r.get('is_vertical') else ''}"
                             f"; {int(r.get('followers') or 0)} seguidores.")
        fb_arch = fb_summary.get("by_archetype", {})
        best = max((k for k in fb_arch if k != "unknown"), key=lambda k: fb_arch[k].get("median_retention_25") or 0, default=None)
        if best:
            notes.append(f"Facebook: mejor retencion al primer cuarto en '{ARCHETYPE_LABELS.get(best, best)}' "
                         f"({fb_arch[best]['median_retention_25']}%).")
    dur = yt_summary.get("by_duration", {})
    good = [k for k, s in dur.items() if s.get("n", 0) >= 2 and float(s.get("takeoff_rate") or 0) >= 0.5]
    if good:
        notes.append("YouTube: duraciones que despegan al menos la mitad de las veces: " + ", ".join(sorted(good)) + ".")
    return {"lean_into": lean, "avoid": avoid, "notes": notes}


def derive_weights(yt_summary: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Pesos 0.4..2.0 para mezclar temas: angulos por puntaje, categorias por mediana de vistas."""
    scores = score_archetypes(yt_summary.get("by_archetype", {}))
    arch = {k: round(min(2.0, max(0.4, 0.5 + 1.5 * sc)), 2) for k, sc in scores.items()}
    cats = {}
    by_cat = {k: s for k, s in yt_summary.get("by_category", {}).items() if k and k != "unknown" and s.get("n", 0) >= 2}
    if by_cat:
        ref = statistics.median([s["median_views"] for s in by_cat.values()]) or 1.0
        for k, s in by_cat.items():
            cats[k] = round(min(2.0, max(0.4, s["median_views"] / ref)), 2)
    return {"archetypes": arch, "categories": cats}


def build_snapshot(yt_rows: list[dict[str, Any]], fb_rows: list[dict[str, Any]], projects: list[dict[str, Any]],
                   days: int, yt_channel: Optional[dict[str, Any]] = None,
                   fb_page: Optional[dict[str, Any]] = None, now: Optional[_dt.datetime] = None) -> dict[str, Any]:
    now = now or _dt.datetime.now()
    yt = enrich_rows(yt_rows, projects, "youtube")
    fb = enrich_rows(fb_rows, projects, "facebook")
    yt_summary = {
        "by_archetype": summarize(yt, "archetype", "youtube"),
        "by_category": summarize(yt, "category", "youtube"),
        "by_duration": summarize(yt, "duration_bucket", "youtube"),
        "by_risk": summarize([dict(r, risk_tags=r["risk_tags"] or ["none"]) for r in yt], "risk_tags", "youtube"),
        "by_opening": summarize(yt, "opening", "youtube"),
    }
    fb_summary = {
        "by_archetype": summarize(fb, "archetype", "facebook"),
        "by_duration": summarize(fb, "duration_bucket", "facebook"),
        "by_opening": summarize(fb, "opening", "facebook"),
    }
    winners = sorted(yt, key=lambda r: -float(r.get("views") or 0))[:8]
    losers = sorted([r for r in yt if r.get("dead")], key=lambda r: float(r.get("views") or 0))[:8]
    fb_winners = sorted(fb, key=lambda r: -float(r.get("plays") or 0))[:5]
    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "window_days": int(days),
        "takeoff_views": TAKEOFF_VIEWS,
        "youtube": {
            "channel": yt_channel or {},
            "videos": yt,
            **yt_summary,
            "winners": [{k: r.get(k) for k in ("video_id", "title", "views", "engaged_pct", "subs", "archetype")} for r in winners],
            "losers": [{k: r.get(k) for k in ("video_id", "title", "views", "archetype", "risk_tags")} for r in losers],
        },
        "facebook": {
            "page": fb_page or {},
            "reels": fb,
            **fb_summary,
            "winners": [{k: r.get(k) for k in ("reel_id", "title", "plays", "avg_watch_s", "followers", "archetype", "is_vertical")} for r in fb_winners],
        },
        "recommendations": recommend(yt, fb, yt_summary, fb_summary),
        "weights": derive_weights(yt_summary),
    }


def write_snapshot(snapshot: dict[str, Any], path: Path = SNAPSHOT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ----------------------------------------------------------------------------
# Colectores (red). Finos: devuelven filas planas que las funciones puras entienden.
# ----------------------------------------------------------------------------
def _iso_duration(iso: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)


def collect_youtube(days: int = 30) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Analytics API (por video) + Data API (titulo, duracion, orientacion)."""
    from googleapiclient.discovery import build
    import youtube_analytics_client as ya
    from youtube_uploader import _get_credentials

    creds = _get_credentials(interactive=False)
    data_api = build("youtube", "v3", credentials=creds)
    an = ya._build_service()
    resp = ya.consultar(an, "views,engagedViews,averageViewPercentage,averageViewDuration,subscribersGained",
                        dias=days, dimensions="video", sort="-views", max_results=50)
    stats = {row["video"]: row for row in ya._tabla(resp)}
    ids = list(stats)
    meta = {}
    for i in range(0, len(ids), 50):
        r = data_api.videos().list(id=",".join(ids[i:i + 50]), part="snippet,contentDetails,statistics").execute()
        for v in r.get("items", []):
            meta[v["id"]] = v
    rows = []
    for vid, s in stats.items():
        v = meta.get(vid, {})
        sn = v.get("snippet", {})
        dur = _iso_duration((v.get("contentDetails") or {}).get("duration", ""))
        thumbs = sn.get("thumbnails", {}) or {}
        hi = thumbs.get("high") or thumbs.get("default") or {}
        # Data API no expone orientacion; un short vertical de esta app dura <=180 s.
        # Los 16:9 del pipeline duran >120 s y se etiquetan por el proyecto si lo hay.
        is_vertical = dur <= 180 and not (hi.get("width", 0) > hi.get("height", 1) and dur > 120)
        rows.append({
            "video_id": vid,
            "title": sn.get("title", ""),
            "description": (sn.get("description") or "")[:200],
            "published": (sn.get("publishedAt") or "")[:10],
            "duration": dur,
            "views": int(float(s.get("views") or 0)),
            "engaged_views": int(float(s.get("engagedViews") or 0)),
            "avg_view_pct": float(s.get("averageViewPercentage") or 0),
            "avg_view_s": float(s.get("averageViewDuration") or 0),
            "subs": int(float(s.get("subscribersGained") or 0)),
            "likes": int(float((v.get("statistics") or {}).get("likeCount") or 0)),
            "is_vertical": is_vertical,
        })
    ch = data_api.channels().list(mine=True, part="snippet,statistics").execute()["items"][0]
    channel = {"title": ch["snippet"]["title"], **{k: int(v) for k, v in ch["statistics"].items() if str(v).isdigit()}}
    return rows, channel


def collect_facebook(limit: int = 30) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Graph API: reels de la pagina con las metricas que existen en v23 (validadas 2026-09-21)."""
    import requests
    from env_loader import load_project_env

    load_project_env(ROOT)
    tok = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN") or ""
    page = os.getenv("FACEBOOK_PAGE_ID") or ""
    ver = os.getenv("FACEBOOK_GRAPH_API_VERSION", "v23.0")
    if not tok or not page:
        raise RuntimeError("FACEBOOK_PAGE_ACCESS_TOKEN / FACEBOOK_PAGE_ID no configurados")
    base = f"https://graph.facebook.com/{ver}"

    def get(path, **params):
        params["access_token"] = tok
        j = requests.get(f"{base}/{path}", params=params, timeout=40).json()
        if "error" in j:
            raise RuntimeError(j["error"].get("message", "Graph API error"))
        return j

    me = get("me", fields="name,followers_count,fan_count")
    page_info = {"name": me.get("name"), "followers": me.get("followers_count"), "fans": me.get("fan_count")}
    for metric in ("page_video_views", "page_follows", "page_post_engagements"):
        try:
            r = get(f"{page}/insights", metric=metric, period="days_28")
            vals = (r.get("data") or [{}])[0].get("values") or []
            page_info[metric + "_28d"] = vals[-1]["value"] if vals else None
        except Exception:
            page_info[metric + "_28d"] = None
    reels = get(f"{page}/video_reels", fields="id,description,created_time,length", limit=limit).get("data", [])
    rows = []
    for v in reels:
        try:
            ins = get(f"{v['id']}/video_insights",
                      metric="fb_reels_total_plays,post_video_avg_time_watched,post_video_followers,post_video_retention_graph")
            d = {x["name"]: x["values"][0]["value"] for x in ins.get("data", []) if x.get("values")}
        except Exception:
            d = {}
        g = d.get("post_video_retention_graph") or {}
        n = len(g)

        def ret(p):
            if not n:
                return None
            val = g.get(str(int(round((n - 1) * p))))
            return round(100 * float(val), 1) if val is not None else None

        length = float(v.get("length") or 0)
        rows.append({
            "reel_id": v["id"],
            "title": ((v.get("description") or "").split("\n")[0])[:120],
            "description": (v.get("description") or "")[:200],
            "published": (v.get("created_time") or "")[:10],
            "duration": length,
            "plays": int(d.get("fb_reels_total_plays") or 0),
            "avg_watch_s": round(float(d.get("post_video_avg_time_watched") or 0) / 1000.0, 1),
            "followers": int(d.get("post_video_followers") or 0),
            "retention_25": ret(0.25), "retention_50": ret(0.5), "retention_75": ret(0.75),
            # el pipeline solo sube 16:9 cuando es microdocumental (>120 s)
            "is_vertical": length <= 120,
        })
    return rows, page_info


def run(days: int = 30, with_youtube: bool = True, with_facebook: bool = True,
        out_path: Path = SNAPSHOT_PATH, log=print) -> dict[str, Any]:
    projects = load_projects()
    yt_rows, yt_channel, fb_rows, fb_page = [], {}, [], {}
    if with_youtube:
        log(f"[Rendimiento] YouTube Analytics, ultimos {days} dias...")
        yt_rows, yt_channel = collect_youtube(days)
        log(f"[Rendimiento]   {len(yt_rows)} videos")
    if with_facebook:
        log("[Rendimiento] Facebook Graph, reels de la pagina...")
        try:
            fb_rows, fb_page = collect_facebook()
            log(f"[Rendimiento]   {len(fb_rows)} reels")
        except Exception as exc:
            log(f"[Rendimiento]   Facebook omitido: {exc}")
    snap = build_snapshot(yt_rows, fb_rows, projects, days, yt_channel, fb_page)
    write_snapshot(snap, out_path)
    log(f"[Rendimiento] Snapshot escrito: {out_path}")
    return snap


OPENING_LABELS = {"cover_card": "placa quieta de 0.7 s", "hook_overlay_v1": "texto de gancho sobre la escena 1",
                  "plain": "sin placa ni gancho"}
MIN_OPENING_N = 8


def compare_openings(by_opening: dict[str, dict[str, Any]]) -> Optional[str]:
    """El A/B del arranque (video_opening): retencion tras los primeros segundos (engagedViews/views)
    por estilo. None si todavia no hay de los dos."""
    old, new = by_opening.get("cover_card"), by_opening.get("hook_overlay_v1")
    if not old or not new:
        return None
    txt = (f"ARRANQUE: {OPENING_LABELS['cover_card']} (n={old['n']}, se quedan {old['median_engaged_pct']}%, "
           f"despegan {int(old['takeoff_rate'] * 100)}%) vs {OPENING_LABELS['hook_overlay_v1']} (n={new['n']}, "
           f"se quedan {new['median_engaged_pct']}%, despegan {int(new['takeoff_rate'] * 100)}%)")
    if min(old["n"], new["n"]) < MIN_OPENING_N:
        return txt + f" -- todavia pocos videos (hacen falta {MIN_OPENING_N} de cada uno para juzgar)"
    diff = round(float(new["median_engaged_pct"]) - float(old["median_engaged_pct"]), 1)
    verdict = ("el gancho retiene mas" if diff >= 3 else "la placa retenia mas" if diff <= -3 else "sin diferencia clara")
    return f"{txt} -> {verdict} ({diff:+} puntos)"


def format_summary(snap: dict[str, Any]) -> str:
    lines = [f"RENDIMIENTO (ventana {snap.get('window_days')} dias, {snap.get('generated_at')})"]
    ch = snap.get("youtube", {}).get("channel") or {}
    if ch:
        lines.append(f"  YouTube: {ch.get('title')} - {ch.get('viewCount', '?')} vistas, {ch.get('subscriberCount', '?')} subs, {ch.get('videoCount', '?')} videos")
    pg = snap.get("facebook", {}).get("page") or {}
    if pg:
        lines.append(f"  Facebook: {pg.get('name')} - {pg.get('followers')} seguidores, {pg.get('page_video_views_28d')} reproducciones/28d")
    rec = snap.get("recommendations", {})
    if rec.get("lean_into"):
        lines.append("  APOSTAR A:")
        for x in rec["lean_into"]:
            lines.append(f"    - {x['label']}: {x['why']}")
    if rec.get("avoid"):
        lines.append("  EVITAR:")
        for x in rec["avoid"]:
            lines.append(f"    - {x['label']}: {x['why']}")
    for n in rec.get("notes", []):
        lines.append(f"  NOTA: {n}")
    ab = compare_openings((snap.get("youtube") or {}).get("by_opening") or {})
    if ab:
        lines.append(f"  {ab}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dias", type=int, default=30)
    ap.add_argument("--sin-youtube", action="store_true")
    ap.add_argument("--sin-facebook", action="store_true")
    ap.add_argument("--salida", default=str(SNAPSHOT_PATH))
    args = ap.parse_args(argv)
    snap = run(days=args.dias, with_youtube=not args.sin_youtube, with_facebook=not args.sin_facebook,
               out_path=Path(args.salida))
    print()
    print(format_summary(snap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
