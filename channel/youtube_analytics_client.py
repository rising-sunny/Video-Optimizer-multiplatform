# -*- coding: utf-8 -*-
"""Estadisticas avanzadas del canal via YouTube Analytics API.

Lo que la Data API NO da y esto si:
  - `averageViewPercentage`  : retencion. La metrica que decide si el feed de
    Shorts sigue sirviendo el video.
  - `insightTrafficSourceType`: de donde vienen las vistas. Distingue "menos
    impresiones" de "misma exposicion, peor retencion" -- imposible de separar
    mirando solo el conteo de vistas.
  - `subscribersGained` por video: el objetivo real del canal.
  - `engagedViews`: vistas en las que el espectador se quedo. Contra `views` da
    la mejor proxy del swipe rate, que la API no expone directamente.

Requiere el scope `yt-analytics.readonly` (ver `youtube_uploader.SCOPES`). Si el
token guardado no lo tiene, `youtube_uploader._get_credentials` fuerza una nueva
autorizacion en el navegador.

Uso:
    .venv\\Scripts\\python.exe youtube_analytics_client.py            # resumen
    .venv\\Scripts\\python.exe youtube_analytics_client.py --dias 90
"""

from __future__ import annotations

import argparse
import datetime
import sys
from typing import Any, Optional

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def _build_service():
    """Cliente de la Analytics API usando las credenciales del uploader."""
    from googleapiclient.discovery import build
    from publish.youtube_uploader import _get_credentials

    creds = _get_credentials(interactive=True)
    otorgados = set(getattr(creds, "scopes", None) or [])
    if ANALYTICS_SCOPE not in otorgados:
        raise RuntimeError(
            "Las credenciales no incluyen yt-analytics.readonly. "
            "Borra token.json y volve a autorizar."
        )
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def _rango(dias: int, alinear_mes: bool = False) -> tuple[str, str]:
    """Rango de fechas. La Analytics API va con 2-3 dias de retraso.

    Con `dimensions=month` la API exige que AMBAS fechas sean el dia 1 de un
    mes. Ojo: NO es el ultimo dia del mes (probado: 2026-07-31 tambien lo
    rechaza). El error 400 dice "does not align to chosen date dimension" sin
    aclarar cual de las dos alineaciones espera.
    """
    fin = datetime.date.today() - datetime.timedelta(days=3)
    inicio = fin - datetime.timedelta(days=dias)
    if alinear_mes:
        inicio = inicio.replace(day=1)
        fin = fin.replace(day=1)
    return inicio.isoformat(), fin.isoformat()


def consultar(service, metrics: str, dias: int = 365, dimensions: Optional[str] = None,
              sort: Optional[str] = None, filters: Optional[str] = None,
              max_results: Optional[int] = None) -> dict[str, Any]:
    """Consulta cruda. Devuelve el dict de la API (columnHeaders + rows)."""
    inicio, fin = _rango(dias, alinear_mes=(dimensions == "month"))
    params: dict[str, Any] = {
        "ids": "channel==MINE",
        "startDate": inicio,
        "endDate": fin,
        "metrics": metrics,
    }
    if dimensions:
        params["dimensions"] = dimensions
    if sort:
        params["sort"] = sort
    if filters:
        params["filters"] = filters
    if max_results:
        params["maxResults"] = max_results
    try:
        return service.reports().query(**params).execute()
    except Exception as exc:
        # Dos fallos distintos con el mismo 403 y arreglos opuestos: uno se
        # resuelve reautorizando, el otro habilitando la API en la consola.
        detalle = str(exc)
        if "accessNotConfigured" in detalle or "has not been used in project" in detalle:
            raise RuntimeError(
                "La YouTube Analytics API no esta habilitada en el proyecto de Google "
                "Cloud.\n"
                "   Habilitala aca (un clic, y esperar 1-2 minutos):\n"
                "   https://console.cloud.google.com/apis/library/"
                "youtubeanalytics.googleapis.com\n"
                "   Elegi el proyecto de client_secrets.json (videooptimizer-476510)."
            ) from exc
        if "insufficient authentication scopes" in detalle.lower():
            raise RuntimeError(
                "El token no tiene yt-analytics.readonly. Borra token.json y volve "
                "a autorizar."
            ) from exc
        raise


def _tabla(resp: dict[str, Any]) -> list[dict[str, Any]]:
    cols = [c["name"] for c in resp.get("columnHeaders", [])]
    return [dict(zip(cols, fila)) for fila in resp.get("rows", []) or []]


def retencion_por_video(service, dias: int = 365, limite: int = 15) -> list[dict]:
    """Los videos ordenados por vistas, con retencion, enganche y suscriptores."""
    resp = consultar(
        service,
        metrics="views,engagedViews,averageViewPercentage,averageViewDuration,"
                "subscribersGained",
        dimensions="video", sort="-views", dias=dias, max_results=limite,
    )
    return _tabla(resp)


def tasa_de_enganche(service, dias: int = 365, limite: int = 30,
                     minimo_views: int = 40) -> list[dict]:
    """engagedViews / views por video: la mejor proxy del "swipe rate".

    La API NO expone una metrica de deslizamiento (`swipeAwayRate`,
    `shortsViewCorrectionVolume` e `impressions` son todas rechazadas: probado).
    `engagedViews` cuenta las vistas en que el espectador realmente se quedo, asi
    que la diferencia contra `views` es la gente que se fue enseguida.

    POR QUE NO USAR `averageViewPercentage` PARA ESTO: en Shorts el loop la
    infla. Caso real del canal anterior: "Roman Extinction: 1 Lost Plant" salia
    PRIMERO con 545% de retencion y es el ULTIMO por enganche, con 12%.
    """
    filas = _tabla(consultar(
        service, metrics="views,engagedViews", dimensions="video",
        sort="-views", dias=dias, max_results=limite,
    ))
    salida = []
    for f in filas:
        vistas = f.get("views") or 0
        if vistas < minimo_views:
            continue
        f["engagementRate"] = round(100.0 * (f.get("engagedViews") or 0) / vistas, 1)
        salida.append(f)
    salida.sort(key=lambda x: -x["engagementRate"])
    return salida


def fuentes_de_trafico(service, dias: int = 365) -> list[dict]:
    """De donde llegan las vistas. Para el canal, el feed de Shorts es ~84%."""
    resp = consultar(
        service,
        metrics="views,estimatedMinutesWatched,averageViewPercentage",
        dimensions="insightTrafficSourceType", sort="-views", dias=dias,
    )
    return _tabla(resp)


def evolucion_mensual(service, dias: int = 365) -> list[dict]:
    """Vistas, retencion y suscriptores mes a mes: separa caida de distribucion
    (vistas abajo, retencion igual) de caida de contenido (ambas abajo)."""
    resp = consultar(
        service,
        metrics="views,averageViewPercentage,subscribersGained,subscribersLost",
        dimensions="month", sort="month", dias=dias,
    )
    return _tabla(resp)


def curva_de_retencion(service, video_id: str, dias: int = 365) -> list[dict]:
    """Retencion a lo largo del video: donde exactamente se van.

    Sirve para responder si el cover frame de 0.7s cuesta espectadores en el
    primer segundo.
    """
    resp = consultar(
        service, metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio",
        filters=f"video=={video_id}", sort="elapsedVideoTimeRatio", dias=dias,
    )
    return _tabla(resp)


def _imprimir(titulo: str, filas: list[dict], columnas: list[str]) -> None:
    print("\n" + titulo)
    print("-" * 78)
    if not filas:
        print("  (sin datos)")
        return
    print("  " + "".join(c[:22].rjust(24) if i else c[:26].ljust(28)
                          for i, c in enumerate(columnas)))
    for fila in filas:
        celdas = []
        for i, c in enumerate(columnas):
            v = fila.get(c, "")
            if isinstance(v, float):
                v = f"{v:.1f}"
            celdas.append(str(v)[:22].rjust(24) if i else str(v)[:26].ljust(28))
        print("  " + "".join(celdas))


def main() -> int:
    ap = argparse.ArgumentParser(description="Estadisticas avanzadas del canal")
    ap.add_argument("--dias", type=int, default=365)
    ap.add_argument("--video", help="ID de video para ver su curva de retencion")
    args = ap.parse_args()

    try:
        service = _build_service()
    except Exception as exc:
        print("No se pudo abrir la Analytics API:")
        print("   %s" % exc)
        return 1

    if args.video:
        filas = curva_de_retencion(service, args.video, dias=args.dias)
        _imprimir("CURVA DE RETENCION de %s" % args.video, filas,
                  ["elapsedVideoTimeRatio", "audienceWatchRatio"])
        return 0

    bloques = [
        ("FUENTES DE TRAFICO (ultimos %d dias)" % args.dias, fuentes_de_trafico,
         ["insightTrafficSourceType", "views", "estimatedMinutesWatched",
          "averageViewPercentage"]),
        ("EVOLUCION MENSUAL", evolucion_mensual,
         ["month", "views", "averageViewPercentage", "subscribersGained",
          "subscribersLost"]),
        ("VIDEOS (por vistas)", retencion_por_video,
         ["video", "views", "engagedViews", "averageViewPercentage",
          "averageViewDuration", "subscribersGained"]),
        ("TASA DE ENGANCHE (proxy del swipe rate)", tasa_de_enganche,
         ["video", "engagementRate", "views", "engagedViews"]),
    ]
    fallos = 0
    for titulo, fn, columnas in bloques:
        try:
            _imprimir(titulo, fn(service, args.dias), columnas)
        except Exception as exc:
            fallos += 1
            print("\n%s" % titulo)
            print("-" * 78)
            print("  %s" % exc)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
