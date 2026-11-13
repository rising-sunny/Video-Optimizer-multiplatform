"""Investigacion para documentales long-form (solo lectura, no sube ni modifica nada).

    .venv/bin/python long_form_research.py demand "Kursk submarine disaster" "Sea Peoples bronze age collapse"
    .venv/bin/python long_form_research.py retention 9Mre9fHxDaU sGDGHRRg_hU
    .venv/bin/python long_form_research.py summary
    .venv/bin/python long_form_research.py reach JQsan954wac bXZ-XCLw5_k

- demand: busca en YouTube (videos 4-20 min desde 2024) y mide la demanda del tema:
  mediana de vistas y cuantos canales chicos (<50k subs) superan 20k vistas.
  Cuesta ~102 unidades de cuota por tema (la cuota diaria es 10.000; una subida usa 1.600).
- retention: curva de retencion (en % del video) y fuentes de trafico de videos propios.
- summary: vistas y minutos por tipo de contenido (Shorts vs largos) en los ultimos 365 dias.
  Solo los largos (videoOnDemand) cuentan para las 4.000 horas del Programa de Socios.

- reach: impresiones y CTR de miniaturas por video (Reporting API, informe diario channel_reach_basic_a1).
  Los informes tardan 1-2 dias en aparecer tras crear la tarea; los CSV se guardan en generated_media/reach_reports/.

Usa el token de `--channel` (por defecto stunning-revelations), que necesita el scope
yt-analytics.readonly para `retention` y `summary`.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import statistics
from datetime import date, timedelta
from pathlib import Path

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


def _download_report(reporting, resource: str) -> bytes:
    """Baja un CSV del Reporting API (download_media devuelve el contenido en streaming; execute() puede devolver str)."""
    from googleapiclient.http import MediaIoBaseDownload

    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, reporting.media().download_media(resourceName=resource))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def reach_reports(reporting, video_ids=None, report_type="channel_reach_basic_a1") -> dict:
    """Baja los CSV nuevos del informe de alcance y suma impresiones/CTR por video."""
    jobs = reporting.jobs().list().execute().get("jobs", [])
    job = next((j for j in jobs if j["reportTypeId"] == report_type), None)
    if not job:
        return {"status": "sin_tarea", "videos": {}, "days": 0, "columns": []}
    cache = Path("generated_media/reach_reports")
    cache.mkdir(parents=True, exist_ok=True)
    reports, token = [], None
    while True:
        r = reporting.jobs().reports().list(jobId=job["id"], pageToken=token).execute()
        reports += r.get("reports", [])
        token = r.get("nextPageToken")
        if not token:
            break
    totals, columns = {}, []
    for rep in reports:
        f = cache / f"{report_type}_{rep['startTime'][:10]}_{rep['id']}.csv"
        if not f.exists():
            f.write_bytes(_download_report(reporting, rep["downloadUrl"].split("/media/")[1].split("?")[0]))
        rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8"))))
        for row in rows:
            columns = list(row)
            vid = row.get("video_id")
            if video_ids and vid not in video_ids:
                continue
            imp = float(row.get("video_thumbnail_impressions") or 0)
            ctr = float(row.get("video_thumbnail_impressions_ctr") or 0)
            t = totals.setdefault(vid, {"impressions": 0.0, "clicks": 0.0})
            t["impressions"] += imp
            t["clicks"] += imp * ctr
    return {"status": "ok" if reports else "pendiente", "videos": totals, "days": len(reports), "columns": columns}


def main() -> None:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--channel", default="stunning-revelations")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demand").add_argument("queries", nargs="+")
    sub.add_parser("retention").add_argument("video_ids", nargs="+")
    sub.add_parser("summary")
    sub.add_parser("reach").add_argument("video_ids", nargs="*")
    args = parser.parse_args()
    if args.cmd == "reach":
        from googleapiclient.discovery import build

        creds = _get_credentials(interactive=False, channel_profile=args.channel)
        r = reach_reports(build("youtubereporting", "v1", credentials=creds), set(args.video_ids) or None)
        print(f"estado: {r['status']} | informes diarios: {r['days']}")
        if r["status"] == "pendiente":
            print("YouTube aun no genero informes (suele tardar 1-2 dias desde que se creo la tarea).")
        for vid, t in sorted(r["videos"].items(), key=lambda kv: -kv[1]["impressions"]):
            ctr = t["clicks"] / t["impressions"] * 100 if t["impressions"] else 0
            print(f"{vid}  impresiones {t['impressions']:>9,.0f}  CTR {ctr:5.2f}%")
        return
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
