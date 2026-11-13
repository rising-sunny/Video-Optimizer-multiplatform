"""Panel semanal de captacion para Stunning Revelations (solo lectura: API oficial de YouTube, no sube ni cambia nada).

Responde cada semana: ¿de donde vienen las vistas?, ¿cuantas impresiones y que CTR tuvo cada largo?, ¿funciono la renovacion de
titulos/miniaturas?, ¿cuanto aportan los Shorts?, ¿cuantas horas largas llevamos hacia las 4.000?

Uso:  .venv/bin/python -m documentary_kit.growth_report [--days 28] [--out ~/growth-reports]
Datos: Data API (uploads), Analytics API (vistas, minutos, retencion media, suscriptores, fuentes de trafico) y los informes diarios
de alcance del Reporting API que ya baja `long_form_research.reach_reports` (impresiones y CTR por video y dia; tardan 1-2 dias).
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

import long_form_research as lfr

# Cambios de titulo/miniatura ya aplicados (video -> fecha ISO). Fuente: ~/video-projects/renovacion-2026-11/
RENOVATIONS = {
    "mpknQRr5DKs": ("Damascus", "2026-11-10"), "3d5MUi75ay4": ("SL-1", "2026-11-10"),
    "w4EoiM792u0": ("Skylab", "2026-11-10"), "fUXqm3Bwsm4": ("Starfish Prime", "2026-11-10"),
}
LONG_MIN_SECONDS = 181          # Shorts: hasta 3 minutos


def _uploads(yt, since: date) -> list[dict]:
    up = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=token).execute()
        for it in r["items"]:
            if it["contentDetails"].get("videoPublishedAt", "")[:10] >= since.isoformat():
                ids.append(it["contentDetails"]["videoId"])
        token = r.get("nextPageToken")
        if not token or len(ids) >= 300:
            break
    out = []
    for i in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,contentDetails,status", id=",".join(ids[i:i + 50])).execute()["items"]:
            out.append(dict(id=v["id"], title=v["snippet"]["title"], published=v["snippet"]["publishedAt"][:10],
                            seconds=lfr._iso_seconds(v["contentDetails"]["duration"]), privacy=v["status"]["privacyStatus"]))
    return out


def _reach_by_day(reporting) -> dict[str, dict[str, tuple[float, float]]]:
    """video -> {YYYY-MM-DD: (impresiones, clics)} a partir de los CSV en cache (se actualizan antes con reach_reports)."""
    lfr.reach_reports(reporting)
    days: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    for f in Path("generated_media/reach_reports").glob("channel_reach_basic_a1_*.csv"):
        for row in csv.DictReader(io.StringIO(f.read_text(encoding="utf-8"))):
            d = row["date"]
            iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            imp = float(row.get("video_thumbnail_impressions") or 0)
            ctr = float(row.get("video_thumbnail_impressions_ctr") or 0)
            old = days[row["video_id"]].get(iso, (0.0, 0.0))
            days[row["video_id"]][iso] = (old[0] + imp, old[1] + imp * ctr)
    return days


def _sum(days_for_video: dict, a: str, b: str) -> tuple[float, float]:
    imp = clk = 0.0
    for d, (i, c) in days_for_video.items():
        if a <= d < b:
            imp += i
            clk += c
    return imp, clk


def _ya(ya, **kw):
    return ya.reports().query(ids="channel==MINE", **kw).execute().get("rows", [])


def build(days: int = 28) -> str:
    load_dotenv(".env")
    yt, ya = lfr._services("stunning-revelations")
    from googleapiclient.discovery import build as gbuild
    from publish.youtube_uploader import _get_credentials
    reporting = gbuild("youtubereporting", "v1", credentials=_get_credentials(interactive=False, channel_profile="stunning-revelations"))
    today = date.today(); start = (today - timedelta(days=days)).isoformat(); end = today.isoformat()
    L: list[str] = [f"# Captacion de Stunning Revelations — {today.isoformat()} (ultimos {days} dias)\n"]

    # 1. canal: totales y fuentes
    tot = _ya(ya, startDate=start, endDate=end, metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost")
    t = tot[0] if tot else [0, 0, 0, 0]
    L.append(f"**Canal:** {int(t[0]):,} vistas · {t[1] / 60:,.1f} h · +{int(t[2])} / -{int(t[3])} suscriptores\n")
    src = sorted(_ya(ya, startDate=start, endDate=end, metrics="views,estimatedMinutesWatched", dimensions="insightTrafficSourceType"), key=lambda r: -r[1])
    sv = sum(r[1] for r in src) or 1
    L.append("**De donde vienen las vistas:** " + " · ".join(f"{r[0]} {int(r[1]):,} ({r[1] / sv * 100:.0f} %)" for r in src[:6]) + "\n")
    summary = lfr.content_type_summary(ya)
    long_h = sum(m for k, v, m in summary if k == "videoOnDemand") / 60
    L.append(f"**Horas de largos (365 d):** {long_h:,.1f} h de 4.000 ({long_h / 40:.1f} %)\n")

    # 2. alcance por largo
    ups = [u for u in _uploads(yt, today - timedelta(days=max(days, 45))) if u["seconds"] >= LONG_MIN_SECONDS and u["privacy"] == "public"]
    reach = _reach_by_day(reporting)
    stats = {}
    if ups:
        ids = ",".join(u["id"] for u in ups)
        for r in _ya(ya, startDate=(today - timedelta(days=60)).isoformat(), endDate=end, dimensions="video", filters=f"video=={ids}",
                     metrics="views,estimatedMinutesWatched,averageViewPercentage,subscribersGained"):
            stats[r[0]] = r[1:]
    L.append("\n## Largos publicados (alcance y retencion)\n")
    L.append("| Largo | Publicado | Impresiones | CTR | Vistas | % visto | Min | Subs |\n|---|---|---:|---:|---:|---:|---:|---:|")
    for u in sorted(ups, key=lambda u: u["published"], reverse=True):
        imp, clk = _sum(reach.get(u["id"], {}), u["published"], "9999")
        st = stats.get(u["id"], [0, 0, 0, 0])
        L.append(f"| {u['title'][:46]} | {u['published']} | {imp:,.0f} | {clk / imp * 100 if imp else 0:.2f} % | {int(st[0]):,} | {st[2]:.0f} % | {int(st[1]):,} | {int(st[3])} |")
    imps = [_sum(reach.get(u["id"], {}), u["published"], "9999")[0] for u in ups]
    if imps:
        L.append(f"\nImpresiones por largo: mediana {statistics.median(imps):,.0f}. Referencia 2026-11: ~385 impresiones y 1,5 % de CTR por largo.\n")

    # 3. renovacion: 7 dias antes vs 7 dias despues del cambio
    L.append("\n## Renovacion de titulo y miniatura (7 dias antes / 7 despues)\n")
    L.append("| Video | Cambio | Impresiones antes → despues | CTR antes → despues |\n|---|---|---|---|")
    for vid, (name, when) in RENOVATIONS.items():
        d0 = date.fromisoformat(when)
        b0, b1, a0, a1 = (d0 - timedelta(days=7)).isoformat(), d0.isoformat(), d0.isoformat(), (d0 + timedelta(days=7)).isoformat()
        ib, cb = _sum(reach.get(vid, {}), b0, b1)
        ia, ca = _sum(reach.get(vid, {}), a0, a1)
        pending = "(faltan datos: 7 dias no cumplidos)" if d0 + timedelta(days=7) > today else ""
        L.append(f"| {name} | {when} | {ib:,.0f} → {ia:,.0f} | {cb / ib * 100 if ib else 0:.2f} % → {ca / ia * 100 if ia else 0:.2f} % {pending} |")

    # 4. Shorts: aporte
    shorts = [u for u in _uploads(yt, today - timedelta(days=days)) if u["seconds"] < LONG_MIN_SECONDS]
    L.append(f"\n## Shorts ({len(shorts)} en {days} dias)\n")
    if shorts:
        sids = ",".join(u["id"] for u in shorts)
        rows = sorted(_ya(ya, startDate=start, endDate=end, dimensions="video", filters=f"video=={sids}", metrics="views,estimatedMinutesWatched,averageViewPercentage"), key=lambda r: -r[1])[:6]
        names = {u["id"]: u["title"] for u in shorts}
        for r in rows:
            L.append(f"- {names.get(r[0], r[0])[:60]}: {int(r[1]):,} vistas · {r[3]:.0f} % visto")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--out", default=str(Path.home() / "growth-reports"))
    a = ap.parse_args()
    text = build(a.days)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    f = out / f"{date.today().isoformat()}.md"
    f.write_text(text, encoding="utf-8")
    print(text)
    print(f"guardado en {f}")


if __name__ == "__main__":
    main()
