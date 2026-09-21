# -*- coding: utf-8 -*-
"""Publicar un video en X (Twitter) con la API v2.

Por que un modulo aparte de `x_uploader.py`: ese sube IMAGENES con el endpoint
simple `upload.twitter.com/1.1/media/upload.json`, que X deprecio en marzo de
2025. Un video ademas nunca pudo subirse asi: necesita el flujo por trozos.

Flujo v2 (verificado contra docs.x.com el 2026-09-03):

    POST https://api.x.com/2/media/upload/initialize
         {media_type, total_bytes, media_category}          -> media_id
    POST https://api.x.com/2/media/upload/{id}/append
         multipart: segment_index + media                   (<= 5 MB por trozo)
    POST https://api.x.com/2/media/upload/{id}/finalize     -> processing_info
    GET  https://api.x.com/2/media/upload?command=STATUS&media_id={id}
         estados: pending -> in_progress -> succeeded | failed
    POST https://api.x.com/2/tweets  {text, media:{media_ids:[id]}}

Autenticacion: OAuth 1.0a de usuario, las mismas cuatro claves TWITTER_* del
`.env` que ya usa el bot de texto.

Limites del formato (tweet_video): 20 min y 8 GB en cuentas estandar. Un short
de 60s y 25 MB entra sobrado.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests

X_API = "https://api.x.com/2"

# 5 MB es el maximo recomendado por trozo (8 MB el del servidor). 4 MB deja
# margen y hace que un short de 25 MB entre en 7 pedazos.
CHUNK_SIZE = 4 * 1024 * 1024

# Limite de caracteres de un post para cuentas sin X Premium.
POST_CHAR_LIMIT = 280

PROCESSING_TIMEOUT_S = 300
X_METADATA_FILES = ("x_metadata.json", "twitter_metadata.json", "metadata.json")


class XUploadError(RuntimeError):
    pass


# ---------------------------------------------------------------- texto puro

def build_post_text(title: str = "", description: str = "", tags=None,
                    url: str = "", limit: int = POST_CHAR_LIMIT) -> str:
    """Arma el texto del post respetando el limite de caracteres.

    Pura y testeable: es la parte que se rompe en silencio si no se cuida. X
    rechaza el post entero con 403 si se pasa de largo, y perder el video por
    dos caracteres de mas seria absurdo.

    Prioridad al recortar: primero se caen los hashtags, despues la
    descripcion, y el titulo se conserva siempre. La URL, si viene, se
    respeta entera porque sin ella el post no sirve de nada.
    """
    titulo = " ".join(str(title or "").split())
    desc = " ".join(str(description or "").split())
    enlace = str(url or "").strip()

    etiquetas = []
    for t in (tags or []):
        limpio = "".join(ch for ch in str(t) if ch.isalnum())
        if limpio:
            etiquetas.append("#" + limpio)
    etiquetas = etiquetas[:3]

    def armar(partes):
        return "\n\n".join(p for p in partes if p).strip()

    # De mas completo a mas escueto.
    candidatos = [
        [titulo, desc, " ".join(etiquetas), enlace],
        [titulo, desc, enlace],
        [titulo, enlace],
    ]
    for partes in candidatos:
        texto = armar(partes)
        if len(texto) <= limit:
            return texto

    # Ni titulo + enlace entran: se recorta el titulo por palabra.
    reservado = len(enlace) + 2 if enlace else 0
    disponible = max(0, limit - reservado - 1)
    recortado = titulo[:disponible]
    if " " in recortado:
        recortado = recortado[:recortado.rfind(" ")]
    return armar([recortado.rstrip(" ,.;:-") + "…", enlace])[:limit]


def _load_metadata(output_dir: Path) -> Dict[str, Any]:
    for nombre in X_METADATA_FILES:
        ruta = output_dir / nombre
        if ruta.is_file():
            try:
                return json.loads(ruta.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


# --------------------------------------------------------------- API de X

def _oauth():
    from x_uploader import get_oauth_session

    sesion = get_oauth_session()
    if not sesion:
        raise XUploadError(
            "Faltan las credenciales de X en .env: TWITTER_CONSUMER_KEY, "
            "TWITTER_CONSUMER_SECRET, TWITTER_ACCESS_TOKEN, "
            "TWITTER_ACCESS_TOKEN_SECRET."
        )
    return sesion


def _check(resp, paso: str):
    if resp.status_code >= 400:
        detalle = (resp.text or "")[:400]
        if resp.status_code == 401:
            raise XUploadError(
                f"X rechazo las credenciales en {paso} (401). Los tokens del "
                f".env estan vencidos o son de otra app: regeneralos en el "
                f"portal de desarrolladores. Detalle: {detalle}"
            )
        if resp.status_code == 402:
            raise XUploadError(
                f"X corto por creditos agotados en {paso} (402). El plan "
                f"'Pay Per Use' consume credito por llamada y el de esta cuenta "
                f"se termino: hay que recargarlo en el portal de desarrolladores. "
                f"Las credenciales estan bien. Detalle: {detalle}"
            )
        if resp.status_code == 429:
            raise XUploadError(
                f"X limito la frecuencia en {paso} (429). Esperá unos minutos "
                f"y reintentá; no es un problema de credenciales. Detalle: {detalle}"
            )
        if resp.status_code == 403:
            raise XUploadError(
                f"X rechazo la operacion en {paso} (403). Suele ser el plan de "
                f"acceso (la subida de media no esta en todos los niveles) o el "
                f"texto pasado de largo. Detalle: {detalle}"
            )
        raise XUploadError(f"X fallo en {paso} ({resp.status_code}): {detalle}")
    return resp


def upload_video(video_path: str, on_progress: Optional[Callable[[int, int], None]] = None,
                 media_category: str = "tweet_video", oauth=None) -> str:
    """Sube el video por trozos y devuelve el media_id ya procesado."""
    ruta = Path(video_path)
    if not ruta.is_file():
        raise FileNotFoundError(f"No existe el video: {video_path}")

    total = ruta.stat().st_size
    sesion = oauth or _oauth()

    # 1) INIT
    init = _check(sesion.post(
        f"{X_API}/media/upload/initialize",
        json={
            "media_type": "video/mp4",
            "total_bytes": total,
            "media_category": media_category,
        },
        timeout=60,
    ), "initialize")
    media_id = str((init.json().get("data") or init.json()).get("id") or "").strip()
    if not media_id:
        raise XUploadError(f"initialize no devolvio media_id: {init.text[:300]}")

    # 2) APPEND
    enviado = 0
    with ruta.open("rb") as fh:
        indice = 0
        while True:
            trozo = fh.read(CHUNK_SIZE)
            if not trozo:
                break
            _check(sesion.post(
                f"{X_API}/media/upload/{media_id}/append",
                data={"segment_index": indice},
                files={"media": ("chunk", trozo, "application/octet-stream")},
                timeout=300,
            ), f"append #{indice}")
            enviado += len(trozo)
            indice += 1
            if on_progress:
                on_progress(enviado, total)

    # 3) FINALIZE
    fin = _check(sesion.post(
        f"{X_API}/media/upload/{media_id}/finalize", timeout=120
    ), "finalize")
    datos = fin.json().get("data") or fin.json()

    # 4) STATUS, solo si X avisa que procesa en diferido
    _esperar_procesado(sesion, media_id, datos.get("processing_info"))
    return media_id


def _esperar_procesado(sesion, media_id: str, processing_info) -> None:
    """Espera a que X termine de transcodificar, si corresponde.

    Publicar antes de que el estado sea `succeeded` da un post sin video: el
    tweet sale, el media_id todavia no sirve.
    """
    limite = time.time() + PROCESSING_TIMEOUT_S
    info = processing_info or {}

    while time.time() < limite:
        estado = str(info.get("state") or "").strip().lower()
        if not estado or estado == "succeeded":
            return
        if estado == "failed":
            raise XUploadError(f"X no pudo procesar el video: {info}")

        time.sleep(max(1, int(info.get("check_after_secs") or 3)))
        resp = _check(sesion.get(
            f"{X_API}/media/upload",
            params={"command": "STATUS", "media_id": media_id},
            timeout=60,
        ), "status")
        cuerpo = resp.json().get("data") or resp.json()
        info = cuerpo.get("processing_info") or {}

    raise XUploadError(
        f"X no termino de procesar el video en {PROCESSING_TIMEOUT_S}s "
        f"(media_id {media_id})."
    )


def post_video(video_path: str, text: str,
               on_progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Sube el video y publica el post. Devuelve {'id', 'url', 'media_id'}."""
    sesion = _oauth()
    media_id = upload_video(video_path, on_progress=on_progress, oauth=sesion)

    resp = _check(sesion.post(
        f"{X_API}/tweets",
        json={"text": text, "media": {"media_ids": [media_id]}},
        timeout=120,
    ), "tweets")
    datos = resp.json().get("data") or {}
    post_id = str(datos.get("id") or "")
    return {
        "id": post_id,
        "media_id": media_id,
        "url": f"https://x.com/i/status/{post_id}" if post_id else None,
        "text": text,
        "response": resp.json(),
    }


def upload_from_metadata(output_dir: str, on_progress=None,
                         video_url: str = "") -> Dict[str, Any]:
    """Misma forma que los uploaders de YouTube y Facebook: carpeta + metadata."""
    carpeta = Path(output_dir)
    from output_video_locator import find_output_video
    video = find_output_video(carpeta)
    if not video:
        raise FileNotFoundError(f"No se encontro video en {output_dir}")

    meta = _load_metadata(carpeta)
    texto = build_post_text(
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        tags=meta.get("tags"),
        url=video_url,
    )
    resultado = post_video(str(video), texto, on_progress=on_progress)

    try:
        (carpeta / "x_upload_result.json").write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return resultado


def check_auth() -> Dict[str, Any]:
    """Diagnostico rapido: .las credenciales sirven y de que cuenta son?"""
    try:
        sesion = _oauth()
        resp = sesion.get(f"{X_API}/users/me",
                          params={"user.fields": "username,public_metrics"}, timeout=30)
        if resp.status_code == 401:
            return {"ok": False, "error": "401: tokens vencidos o de otra app"}
        _check(resp, "users/me")
        datos = resp.json().get("data") or {}
        return {
            "ok": True,
            "user_id": datos.get("id"),
            "username": datos.get("username"),
            "followers": (datos.get("public_metrics") or {}).get("followers_count"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        print(json.dumps(check_auth(), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
