"""Investigacion para documentales long-form (solo lectura, no sube ni modifica nada).

    .venv/bin/python long_form_research.py demand "Kursk submarine disaster" "Sea Peoples bronze age collapse"
    .venv/bin/python long_form_research.py retention 9Mre9fHxDaU sGDGHRRg_hU
    .venv/bin/python long_form_research.py summary

- demand: busca en YouTube (videos 4-20 min desde 2024) y mide la demanda del tema:
  mediana de vistas y cuantos canales chicos (<50k subs) superan 20k vistas.
  Cuesta ~102 unidades de cuota por tema (la cuota diaria es 10.000; una subida usa 1.600).
- retention: curva de retencion (en % del video) y fuentes de trafico de videos propios.
- summary: vistas y minutos por tipo de contenido (Shorts vs largos) en los ultimos 365 dias.
  Solo los largos (videoOnDemand) cuentan para las 4.000 horas del Programa de Socios.

Usa el token de `--channel` (por defecto stunning-revelations), que necesita el scope
yt-analytics.readonly para `retention` y `summary`.
"""
from __future__ import annotations

import argparse
import re
import statistics
from datetime import date, timedelta

from dotenv import load_dotenv

from publish.youtube_uploader import _get_credentials

DEMAND_MIN_MEDIAN = 10_000
SMALL_CHANNEL_SUBS = 50_000
SMALL_CHANNEL_HIT_VIEWS = 20_000
RETENTION_POINTS = (0, 2, 5, 10, 20, 30, 50, 70, 90, 99)


def _iso_seconds(value: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def _services(channel: str):
    from googleapiclient.discovery import build

    creds = _get_credentials(interactive=False, channel_profile=channel)
    return (
        build("youtube", "v3", credentials=creds),
        build("youtubeAnalytics", "v2", credentials=creds),
    )


def _window() -> tuple[str, str]:
    end = date.today()
    return (end - timedelta(days=365)).isoformat(), end.isoformat()


def topic_demand(yt, query: str) -> dict:
    found = yt.search().list(
        part="snippet", q=query, type="video", maxResults=15, videoDuration="medium",
        relevanceLanguage="en", order="relevance", publishedAfter="2024-01-01T00:00:00Z",
    ).execute()
    ids = [i["id"]["videoId"] for i in found.get("items", [])]
    if not ids:
        return {"query": query, "median": 0, "small_hits": 0, "top": [], "verdict": "sin resultados"}
    videos = yt.videos().list(part="statistics,contentDetails,snippet", id=",".join(ids)).execute()["items"]
    channel_ids = ",".join({v["snippet"]["channelId"] for v in videos})
    subs = {
        c["id"]: int(c["statistics"].get("subscriberCount", 0) or 0)
        for c in yt.channels().list(part="statistics", id=channel_ids).execute()["items"]
    }
    rows = [
        {
            "views": int(v["statistics"].get("viewCount", 0)),
            "subs": subs.get(v["snippet"]["channelId"], 0),
            "minutes": _iso_seconds(v["contentDetails"]["duration"]) // 60,
            "title": v["snippet"]["title"],
        }
        for v in videos
    ]
    median = int(statistics.median(r["views"] for r in rows))
    small_hits = sum(1 for r in rows if r["subs"] < SMALL_CHANNEL_SUBS and r["views"] > SMALL_CHANNEL_HIT_VIEWS)
    ok = median > DEMAND_MIN_MEDIAN or small_hits > 0
    return {
        "query": query,
        "median": median,
        "small_hits": small_hits,
        "top": sorted(rows, key=lambda r: -r["views"])[:3],
        "verdict": "pasa" if ok else "no pasa",
    }


def video_retention(ya, video_id: str) -> dict:
    start, end = _window()
    curve = ya.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="audienceWatchRatio,relativeRetentionPerformance",
        dimensions="elapsedVideoTimeRatio", filters=f"video=={video_id}",
    ).execute().get("rows", [])
    traffic = ya.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="views,estimatedMinutesWatched", dimensions="insightTrafficSourceType",
        filters=f"video=={video_id}", sort="-views",
    ).execute().get("rows", [])
    return {"video_id": video_id, "curve": curve, "traffic": traffic}


def content_type_summary(ya) -> list:
    start, end = _window()
    return ya.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="views,estimatedMinutesWatched", dimensions="creatorContentType",
    ).execute().get("rows", [])


def main() -> None:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--channel", default="stunning-revelations")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demand").add_argument("queries", nargs="+")
    sub.add_parser("retention").add_argument("video_ids", nargs="+")
    sub.add_parser("summary")
    args = parser.parse_args()
    yt, ya = _services(args.channel)

    if args.cmd == "demand":
        for q in args.queries:
            r = topic_demand(yt, q)
            print(f"{q:42s} mediana {r['median']:>10,}  canales chicos con >20k: {r['small_hits']}  -> {r['verdict']}")
            for t in r["top"]:
                print(f"    {t['views']:>10,} vistas | {t['subs']:>10,} subs | {t['minutes']:>2} min | {t['title'][:70]}")
    elif args.cmd == "retention":
        for vid in args.video_ids:
            r = video_retention(ya, vid)
            print(f"=== {vid}")
            if r["curve"]:
                pts = [r["curve"][i] for i in RETENTION_POINTS if i < len(r["curve"])]
                print("  t% -> % que sigue (relativo vs similares; 0,5 = mediana):")
                print("  " + "  ".join(f"{int(p[0] * 100)}%:{p[1] * 100:.0f}({p[2]:.2f})" for p in pts))
            else:
                print("  sin datos de retencion todavia")
            print("  trafico:", ", ".join(f"{t[0]} {t[1]}v/{t[2]}min" for t in r["traffic"][:6]) or "sin datos")
    else:
        for kind, views, minutes in content_type_summary(ya):
            print(f"{kind:15s} {views:>8,} vistas  {minutes:>8,} min  ({minutes / 60:,.1f} h)")


if __name__ == "__main__":
    main()
