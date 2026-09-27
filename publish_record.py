# -*- coding: utf-8 -*-
"""Dejar escrito en el project.json que se publico, donde y con que id.

Hasta 2026-09-21 el Studio publicaba desde un staging temporal que se borraba
al terminar: el id de YouTube, del reel de Facebook, etc. no quedaba en ningun
lado. Sin eso, performance_feedback.py solo puede cruzar metricas con
proyectos por parecido de titulo (9 de 25 el dia que se midio).

Puro: `merge_publish_results(project_data, results)` devuelve el dict con
`publish_results` actualizado; el project manager se ocupa del disco.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

# publish_id: TikTok (borrador en la bandeja; el id del post recien existe cuando se publica en la app).
_ID_KEYS = ("video_id", "media_id", "reel_id", "id", "post_id", "tweet_id", "publish_id")
_URL_KEYS = ("url", "permalink_url", "permalink", "video_url", "post_url")


def _pick(d: dict[str, Any], keys) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if v:
            return str(v)
    return None


def summarize_result(platform: str, result: Any) -> Optional[dict[str, Any]]:
    """Lo minimo que hace falta para cruzar metricas despues: id, url, cuando."""
    if not isinstance(result, dict):
        return None
    entry: dict[str, Any] = {}
    vid = _pick(result, _ID_KEYS)
    url = _pick(result, _URL_KEYS)
    if not vid and not url:
        return None
    if "thumbnail_set" in result:
        entry["thumbnail_set"] = bool(result.get("thumbnail_set"))
    if vid:
        entry["video_id" if platform == "youtube" else "id"] = vid
    if url:
        entry["url"] = url
    for extra in ("status", "privacy_status", "publish_at", "scheduled_publish_time", "transport",
                  "tags_sent", "tags_stored", "title_sent", "title_original",
                  "thumbnail_sent", "thumbnail_error", "hashtags_sent"):
        if result.get(extra):
            entry[extra] = result[extra]
    return entry


def merge_publish_results(project_data: dict[str, Any], results: dict[str, Any],
                          now: Optional[_dt.datetime] = None) -> dict[str, Any]:
    """Suma (no pisa) los resultados de esta publicacion al proyecto.

    Un fallo (None) no borra lo que ya estaba: si YouTube se publico ayer y hoy
    solo se reintento Instagram, el id de YouTube sigue ahi.
    """
    data = dict(project_data or {})
    stamp = (now or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    existing = dict(data.get("publish_results") or {})
    for platform, result in (results or {}).items():
        entry = summarize_result(str(platform).lower(), result)
        if entry is None:
            continue
        entry["published_at"] = stamp
        existing[str(platform).lower()] = entry
    data["publish_results"] = existing
    return data


__all__ = ["merge_publish_results", "summarize_result"]
