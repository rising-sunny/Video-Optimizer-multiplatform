"""Analisis del canal The Lost Atlas con la YouTube Data + Analytics API (mismo motor que los otros canales).

    python -m lostatlas.analyze [--days 28] [--videos 15]

Imprime: estadisticas del canal, avance hacia el Programa de Socios (1.000 subs y 4.000 h, o 10 M de vistas de Shorts en 90 d),
y por video: vistas, retencion, enganche (proxy del swipe rate), suscriptores ganados y fuentes de trafico.
"""
import argparse

from googleapiclient.discovery import build

from channel.youtube_analytics_client import _tabla, consultar, evolucion_mensual, fuentes_de_trafico, retencion_por_video, tasa_de_enganche
from publish.youtube_uploader import _get_credentials

KEY = "the-lost-atlas"


def _bar(x, goal, width=24):
    k = max(0.0, min(1.0, x / goal))
    return "#" * int(k * width) + "." * (width - int(k * width)) + f" {100 * k:5.1f}%"


def _table(title, rows, cols):
    print(f"\n== {title}")
    if not rows:
        print("   (sin datos todavia)")
        return
    print("   " + " | ".join(f"{c:>14s}" for c in cols))
    for r in rows:
        print("   " + " | ".join(f"{str(round(r.get(c), 2) if isinstance(r.get(c), float) else r.get(c, ''))[:14]:>14s}" for c in cols))


def _safe(title, fn):
    """Una seccion que falla (p. ej. un 500 de Google en canales sin datos) no debe tumbar el informe entero."""
    try:
        return fn()
    except Exception as exc:                                  # noqa: BLE001
        print(f"\n== {title}\n   (no disponible: {str(exc).splitlines()[0][:110]})")
        return []


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--videos", type=int, default=15)
    a = ap.parse_args()
    creds = _get_credentials(interactive=False, channel_profile=KEY)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    ch = yt.channels().list(part="snippet,statistics", mine=True).execute()["items"][0]
    st = ch["statistics"]
    subs, views, nvid = int(st.get("subscriberCount", 0)), int(st.get("viewCount", 0)), int(st.get("videoCount", 0))
    print(f"{ch['snippet']['title']}  ({ch['id']})\n   suscriptores={subs}  vistas={views}  videos={nvid}")

    year = _tabla(consultar(ya, "views,estimatedMinutesWatched,subscribersGained", dias=365))
    hours = (year[0].get("estimatedMinutesWatched", 0) / 60) if year else 0
    s90 = _tabla(consultar(ya, "views", dias=90))
    sv90 = s90[0]["views"] if s90 else 0
    print("\n== Programa de Socios de YouTube")
    print(f"   suscriptores   {subs:>6d} / 1000   {_bar(subs, 1000)}")
    print(f"   horas (365 d)  {hours:>6.1f} / 4000   {_bar(hours, 4000)}")
    print(f"   vistas 90 d    {sv90:>6d} (la via alternativa pide 10 M de vistas de Shorts)")

    tot = _tabla(consultar(ya, "views,estimatedMinutesWatched,averageViewPercentage,subscribersGained,likes,comments", dias=a.days))
    print(f"\n== Ultimos {a.days} dias")
    print("   " + (", ".join(f"{k}={round(v, 1) if isinstance(v, float) else v}" for k, v in tot[0].items()) if tot else "(sin datos todavia)"))

    rows = _safe("Por video", lambda: retencion_por_video(ya, dias=a.days, limite=a.videos))
    ids = [r["video"] for r in rows]
    titles = {}
    for i in range(0, len(ids), 50):
        for it in yt.videos().list(part="snippet", id=",".join(ids[i:i + 50])).execute().get("items", []):
            titles[it["id"]] = it["snippet"]["title"]
    for r in rows:
        r["titulo"] = titles.get(r["video"], r["video"])
    _table("Por video (ordenado por vistas)", rows, ["titulo", "views", "engagedViews", "averageViewPercentage", "subscribersGained"])
    eng = _safe("Enganche", lambda: tasa_de_enganche(ya, dias=a.days, limite=a.videos, minimo_views=1))
    if eng or not eng:
        _table("Enganche (engagedViews/views: proxy del swipe rate)", eng, ["video", "views", "engagedViews", "enganche"])
    _table("Fuentes de trafico", _safe("Fuentes de trafico", lambda: fuentes_de_trafico(ya, dias=a.days)), ["insightTrafficSourceType", "views", "estimatedMinutesWatched"])
    _table("Evolucion mensual", _safe("Evolucion mensual", lambda: evolucion_mensual(ya, dias=365)), ["month", "views", "estimatedMinutesWatched", "subscribersGained"])


if __name__ == "__main__":
    main()
