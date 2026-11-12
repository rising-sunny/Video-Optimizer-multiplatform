"""
instagram_uploader.py - Publish Instagram Reels using the Meta Graph API.

This implementation uses Cloudinary to host the local MP4 temporarily, because
Instagram publishing requires a publicly accessible video URL.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from publish.cloudinary_uploader import check_auth as check_cloudinary_auth
from publish.cloudinary_uploader import upload_video as upload_video_to_cloudinary
from infra.env_loader import load_project_env

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_project_env(PROJECT_DIR)

INSTAGRAM_METADATA_FILES = ("instagram_metadata.json", "facebook_metadata.json", "metadata.json")
REQUEST_TIMEOUT = 60
POLL_INTERVAL_SECONDS = 15
POLL_TIMEOUT_SECONDS = 300

# Codigos con los que Meta marca el contenedor como ERROR por fallas de SU lado.
# 2207076 (2026-09-15, "Halifax Explosion"): "Media upload has failed" con el
# mismo mp4 que Facebook acepto un minuto antes, specs impecables; la comunidad
# lo trata como intermitente y lo resuelve reintentando. 2207001 media no
# lista, 2207005/2207053 error desconocido de subida, 2207052 fetch fallido.
TRANSIENT_CONTAINER_CODES = ("2207076", "2207001", "2207005", "2207052", "2207053")
# 2 y no 3: cuando Meta esta caido (2026-09-15/16: rechazaba TODO, incluso videos
# que ya habia publicado) reintentar mas seguido solo alarga la espera.
CONTAINER_ATTEMPTS = max(1, int(str(os.getenv("INSTAGRAM_CONTAINER_ATTEMPTS", "2") or "2")))
CONTAINER_RETRY_WAITS = (30, 90)   # segundos entre intentos (el ultimo se repite)

# Como llega el binario a Meta.
#   resumable (default): el archivo se POSTea directo a rupload.facebook.com, el
#       mismo mecanismo con el que Facebook Reels SI publica estos videos. No hay
#       Cloudinary ni URL publica ni "fetch" del lado de Meta.
#   url: el flujo viejo (Cloudinary -> video_url). Queda como respaldo: el
#       2207076 (2026-09-15/16, dos shorts 9:16 impecables, tres intentos cada
#       uno) es Meta fallando al traer el archivo por URL, y no depende del video.
UPLOAD_MODE = str(os.getenv("INSTAGRAM_UPLOAD_MODE", "resumable") or "resumable").strip().lower()
RESUMABLE_UPLOAD_TIMEOUT = 300   # s por trozo
# MEDIDO 2026-09-16: un POST unico de 103 MB a rupload se cae ("Remote end closed
# connection", SSL EOF); en trozos de 4 MB con `offset` incremental Meta acepta
# los 24 trozos. Y solo con Content-Type video/mp4 llega a la etapa de procesado;
# con application/octet-stream devuelve un 400 generico.
RESUMABLE_CHUNK_BYTES = 4 * 1024 * 1024
RESUMABLE_CHUNK_RETRIES = 3


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    if value is None:
        return None
    text = str(value).strip()
    return text or default


def _channel_suffix(channel: Optional[str]) -> str:
    """'stunning-revelations' -> 'STUNNING_REVELATIONS' (sufijo de las claves del canal)."""
    return re.sub(r"[^A-Z0-9]+", "_", str(channel or "").upper()).strip("_")


def _default_api_version() -> str:
    return str(
        _env("INSTAGRAM_GRAPH_API_VERSION")
        or _env("FACEBOOK_GRAPH_API_VERSION")
        or "v23.0"
    ).strip()


def _graph_api_url(path: str, api_version: Optional[str] = None) -> str:
    version = str(api_version or _default_api_version()).strip()
    normalized_path = str(path or "").lstrip("/")
    return f"https://graph.facebook.com/{version}/{normalized_path}"


def _write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _archive_upload_result(result_file: Path, payload: dict) -> Path:
    result_file = Path(result_file)
    uploaded_at = str(payload.get("uploaded_at") or time.strftime("%Y-%m-%dT%H:%M:%S"))
    stamp = uploaded_at.replace("-", "").replace(":", "")
    archive_path = result_file.with_name(f"{result_file.stem}_{stamp}{result_file.suffix}")
    counter = 2
    while archive_path.exists():
        archive_path = result_file.with_name(f"{result_file.stem}_{stamp}_{counter}{result_file.suffix}")
        counter += 1
    _write_json(archive_path, payload)
    return archive_path


def _safe_read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_upload_metadata(output_dir: Path) -> dict:
    for filename in INSTAGRAM_METADATA_FILES:
        meta_path = output_dir / filename
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as handle:
                datos = json.load(handle)
            # Un archivo con `null` o con una lista no es metadata utilizable:
            # devolver eso tal cual hacia reventar al llamador con
            # "'NoneType' object has no attribute 'get'".
            return datos if isinstance(datos, dict) else {}
    raise FileNotFoundError(
        f"No Instagram metadata found in {output_dir}. "
        f"Expected one of: {', '.join(INSTAGRAM_METADATA_FILES)}"
    )


def _clean_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,")
    return trimmed or text[:max_chars].rstrip(" ,")


def _compose_caption(title: str, description: str, max_chars: int = 2200) -> str:
    title = str(title or "").strip()
    description = str(description or "").strip()
    parts = []
    if title:
        parts.append(title)
    if description:
        if parts and description != title:
            parts.append("")
        parts.append(description)
    caption = "\n".join(parts).strip()
    return _clean_text(caption, max_chars)


def _normalize_permalink(url: Optional[str]) -> Optional[str]:
    text = str(url or "").strip()
    return text or None


def _request_json(method: str, url: str, **kwargs) -> dict:
    response = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error") or {}
            message = str(error.get("message") or response.text or "Instagram API request failed").strip()
            code = error.get("code")
            if code is not None:
                raise RuntimeError(f"Instagram API error {code}: {message}")
            raise RuntimeError(f"Instagram API error: {message}")
        response.raise_for_status()
    if not response.text.strip():
        return {}
    return response.json()


def _resolve_instagram_identity(api_version: Optional[str] = None, channel: Optional[str] = None) -> dict:
    # Las claves del canal (sufijo, p. ej. INSTAGRAM_PAGE_ID_STUNNING_REVELATIONS) van ANTES que
    # cualquier global: si no, un canal con FACEBOOK_PAGE_ID propio caia en el INSTAGRAM_PAGE_ID
    # global y publicaba en la cuenta del otro canal (facebook_uploader._channel_env).
    sufijo = _channel_suffix(channel)

    def pick(*names: str, global_fallback: bool = True) -> tuple[Optional[str], bool]:
        """(valor, vino_del_canal)."""
        if sufijo:
            for name in names:
                value = _env(f"{name}_{sufijo}")
                if value:
                    return value, True
        if global_fallback:
            for name in names:
                value = _env(name)
                if value:
                    return value, False
        return None, False

    user_access_token, _ = pick("INSTAGRAM_USER_ACCESS_TOKEN", "FACEBOOK_USER_ACCESS_TOKEN")
    if not user_access_token:
        raise RuntimeError(
            "Instagram auth not configured. Set INSTAGRAM_USER_ACCESS_TOKEN or "
            "FACEBOOK_USER_ACCESS_TOKEN in .env."
        )

    page_id, page_del_canal = pick("INSTAGRAM_PAGE_ID", "FACEBOOK_PAGE_ID")
    # Con pagina propia del canal, la cuenta de Instagram global (la del otro canal) no sirve de respaldo.
    ig_user_id, _ = pick("INSTAGRAM_BUSINESS_ACCOUNT_ID", global_fallback=not page_del_canal)

    if page_id:
        page_info = _request_json(
            "GET",
            _graph_api_url(page_id, api_version=api_version),
            params={
                "fields": "id,name,instagram_business_account{id,username,name}",
                "access_token": user_access_token,
            },
            headers={"User-Agent": "VideoOptimizerPro/1.0"},
        )
        ig_account = page_info.get("instagram_business_account") or {}
        resolved_ig_user_id = str(ig_account.get("id") or ig_user_id or "").strip()
        if not resolved_ig_user_id:
            raise RuntimeError("The configured Facebook Page is not linked to an Instagram professional account.")
        return {
            "access_token": user_access_token,
            "page_id": str(page_info.get("id") or page_id).strip() or None,
            "page_name": str(page_info.get("name") or "").strip() or None,
            "ig_user_id": resolved_ig_user_id,
            "instagram_username": str(ig_account.get("username") or "").strip() or None,
            "instagram_name": str(ig_account.get("name") or "").strip() or None,
        }

    if ig_user_id:
        ig_info = _request_json(
            "GET",
            _graph_api_url(ig_user_id, api_version=api_version),
            params={
                "fields": "id,username,name",
                "access_token": user_access_token,
            },
            headers={"User-Agent": "VideoOptimizerPro/1.0"},
        )
        return {
            "access_token": user_access_token,
            "page_id": None,
            "page_name": None,
            "ig_user_id": str(ig_info.get("id") or ig_user_id).strip(),
            "instagram_username": str(ig_info.get("username") or "").strip() or None,
            "instagram_name": str(ig_info.get("name") or "").strip() or None,
        }

    pages = _request_json(
        "GET",
        _graph_api_url("me/accounts", api_version=api_version),
        params={
            "fields": "id,name,instagram_business_account{id,username,name}",
            "access_token": user_access_token,
        },
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    ).get("data") or []
    linked_pages = [page for page in pages if (page or {}).get("instagram_business_account")]
    if not linked_pages:
        raise RuntimeError("The configured token does not expose any Page linked to an Instagram professional account.")
    if len(linked_pages) > 1:
        raise RuntimeError(
            "Multiple Instagram-linked Facebook Pages found. Set INSTAGRAM_PAGE_ID or FACEBOOK_PAGE_ID in .env."
        )
    page_info = linked_pages[0] or {}
    ig_account = page_info.get("instagram_business_account") or {}
    return {
        "access_token": user_access_token,
        "page_id": str(page_info.get("id") or "").strip() or None,
        "page_name": str(page_info.get("name") or "").strip() or None,
        "ig_user_id": str(ig_account.get("id") or "").strip() or None,
        "instagram_username": str(ig_account.get("username") or "").strip() or None,
        "instagram_name": str(ig_account.get("name") or "").strip() or None,
    }


def _content_publishing_limit(ig_user_id: str, access_token: str, api_version: Optional[str] = None) -> dict:
    return _request_json(
        "GET",
        _graph_api_url(f"{ig_user_id}/content_publishing_limit", api_version=api_version),
        params={
            "fields": "config,quota_usage",
            "access_token": access_token,
        },
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def _create_reel_container(ig_user_id: str, access_token: str, video_url: str, caption: str,
                           share_to_feed: bool = True, api_version: Optional[str] = None,
                           cover_url: Optional[str] = None) -> dict:
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": str(bool(share_to_feed)).lower(),
        "access_token": access_token,
    }
    if cover_url:
        params["cover_url"] = cover_url
    return _request_json(
        "POST",
        _graph_api_url(f"{ig_user_id}/media", api_version=api_version),
        params=params,
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def get_container_status(container_id: str, access_token: str, api_version: Optional[str] = None) -> dict:
    return _request_json(
        "GET",
        _graph_api_url(container_id, api_version=api_version),
        params={
            "fields": "status_code,status",
            "access_token": access_token,
        },
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def _wait_for_container_ready(container_id: str, access_token: str, api_version: Optional[str] = None,
                              timeout_seconds: int = POLL_TIMEOUT_SECONDS, on_status=None) -> dict:
    started = time.time()
    deadline = started + max(30, int(timeout_seconds))
    last_state = {}
    while time.time() < deadline:
        last_state = get_container_status(container_id, access_token, api_version=api_version)
        status_code = str(last_state.get("status_code") or "").strip().upper()
        if status_code in {"FINISHED", "PUBLISHED"}:
            return last_state
        if status_code in {"ERROR", "EXPIRED"}:
            status_text = str(last_state.get("status") or status_code).strip()
            raise RuntimeError(f"Instagram container failed: {status_text}")
        _status(on_status, f"Meta procesando el reel ({status_code or 'IN_PROGRESS'}, {int(time.time() - started)} s)...")
        time.sleep(POLL_INTERVAL_SECONDS)
    return last_state


def _status(on_status, message: str) -> None:
    """Etapa legible para el panel de la GUI (y la consola). Nunca rompe la subida."""
    print(f"   [Instagram] {message}")
    if on_status:
        try:
            on_status(message)
        except Exception:
            pass


def is_transient_container_error(message) -> bool:
    """True si el fallo del contenedor es de los que Meta resuelve al reintentar."""
    text = str(message or "")
    return any(code in text for code in TRANSIENT_CONTAINER_CODES)


def _create_container_with_retries(ig_user_id: str, access_token: str, video_url: str, caption: str,
                                   share_to_feed: bool, api_version: Optional[str] = None,
                                   attempts: Optional[int] = None, sleep=time.sleep, on_status=None,
                                   cover_url: Optional[str] = None) -> tuple:
    """Crea el contenedor y espera a que este listo; reintenta si Meta falla de su lado.

    Reusa la MISMA URL de Cloudinary: el video ya esta publico, no hace falta
    volver a subirlo. Devuelve (container_id, estado_final).
    """
    total = max(1, int(attempts or CONTAINER_ATTEMPTS))
    for attempt in range(1, total + 1):
        container = _create_reel_container(
            ig_user_id=ig_user_id, access_token=access_token, video_url=video_url,
            caption=caption, share_to_feed=share_to_feed, api_version=api_version,
            **({"cover_url": cover_url} if cover_url else {}),
        )
        container_id = str(container.get("id") or "").strip()
        if not container_id:
            raise RuntimeError(f"Instagram did not return a media container id: {container}")
        _status(on_status, f"Contenedor {container_id} creado (intento {attempt}/{total}); esperando a Meta...")
        try:
            status = _wait_for_container_ready(container_id, access_token, api_version=api_version,
                                               on_status=on_status)
            return container_id, status
        except RuntimeError as exc:
            if attempt >= total or not is_transient_container_error(exc):
                raise
            wait = CONTAINER_RETRY_WAITS[min(attempt - 1, len(CONTAINER_RETRY_WAITS) - 1)]
            _status(on_status, f"Meta fallo de su lado ({exc}); reintento {attempt + 1}/{total} "
                               f"en {wait} s con la misma URL de Cloudinary")
            sleep(wait)
    raise RuntimeError("Instagram container retries exhausted")  # inalcanzable


def _create_resumable_container(ig_user_id: str, access_token: str, caption: str,
                                share_to_feed: bool = True, api_version: Optional[str] = None,
                                cover_url: Optional[str] = None) -> dict:
    """Contenedor de reel que espera el binario por POST (no una URL)."""
    params = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "share_to_feed": str(bool(share_to_feed)).lower(),
        "access_token": access_token,
    }
    if cover_url:
        params["cover_url"] = cover_url
    return _request_json(
        "POST",
        _graph_api_url(f"{ig_user_id}/media", api_version=api_version),
        params=params,
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def _resumable_upload_uri(container: dict, api_version: Optional[str] = None) -> str:
    """El `uri` que devuelve Meta; si no viene, se construye segun la doc."""
    uri = str(container.get("uri") or "").strip()
    if uri:
        return uri
    container_id = str(container.get("id") or "").strip()
    if not container_id:
        raise RuntimeError(f"Instagram did not return a resumable container: {container}")
    return f"https://rupload.facebook.com/ig-api-upload/{api_version or _default_api_version()}/{container_id}"


def _describe_rupload_error(payload) -> str:
    """El detalle util de rupload viene anidado (message dentro de message)."""
    if not isinstance(payload, dict):
        return str(payload)[:300]
    info = payload.get("debug_info") or payload.get("error") or payload
    message = info.get("message") if isinstance(info, dict) else None
    return str(message or info)[:300]


def _upload_binary_resumable(upload_uri: str, access_token: str, video_path: str,
                             on_progress=None, chunk_bytes: Optional[int] = None,
                             sleep=time.sleep) -> dict:
    """Manda el archivo a rupload en trozos con `offset` incremental.

    Devuelve el JSON del ultimo trozo (el que completa el archivo). Un error de
    red en un trozo se reintenta; un 4xx/5xx de Meta se propaga con su detalle:
    en el ULTIMO trozo es Meta procesando el video, no la subida.
    """
    path = Path(video_path)
    file_size = path.stat().st_size
    chunk = max(1, int(chunk_bytes or RESUMABLE_CHUNK_BYTES))
    if on_progress:
        on_progress(0, file_size)
    payload = {}
    with open(path, "rb") as handle:
        offset = 0
        while offset < file_size:
            data = handle.read(chunk)
            if not data:
                break
            headers = {
                "Authorization": f"OAuth {access_token}",
                "offset": str(offset),
                "file_size": str(file_size),
                "Content-Type": "video/mp4",
                "User-Agent": "VideoOptimizerPro/1.0",
            }
            response = None
            for attempt in range(1, RESUMABLE_CHUNK_RETRIES + 1):
                try:
                    response = requests.post(upload_uri, headers=headers, data=data,
                                             timeout=RESUMABLE_UPLOAD_TIMEOUT)
                    break
                except requests.RequestException as exc:
                    if attempt >= RESUMABLE_CHUNK_RETRIES:
                        raise RuntimeError(f"Instagram resumable upload: red caida en el trozo "
                                           f"@{offset} ({type(exc).__name__}: {exc})") from exc
                    sleep(2 * attempt)
            try:
                payload = response.json()
            except Exception:
                payload = {"raw": response.text[:300]}
            if response.status_code >= 400:
                last = offset + len(data) >= file_size
                stage = "Meta no pudo procesar el video" if last else f"trozo @{offset} rechazado"
                raise RuntimeError(f"Instagram resumable upload failed (HTTP {response.status_code}, {stage}): "
                                   f"{_describe_rupload_error(payload)}")
            offset += len(data)
            if on_progress:
                on_progress(offset, file_size)
    if not (isinstance(payload, dict) and payload.get("success")):
        raise RuntimeError(f"Instagram resumable upload did not confirm success: {_describe_rupload_error(payload)}")
    return payload


def _publish_via_resumable(ig_user_id: str, access_token: str, video_path: str, caption: str,
                           share_to_feed: bool, api_version: Optional[str] = None,
                           on_progress=None, on_status=None, cover_url: Optional[str] = None) -> tuple:
    """Contenedor resumable + binario + espera. Devuelve (container_id, estado)."""
    container = _create_resumable_container(ig_user_id, access_token, caption,
                                            share_to_feed=share_to_feed, api_version=api_version,
                                            **({"cover_url": cover_url} if cover_url else {}))
    container_id = str(container.get("id") or "").strip()
    if not container_id:
        raise RuntimeError(f"Instagram did not return a media container id: {container}")
    upload_uri = _resumable_upload_uri(container, api_version=api_version)
    size_mb = Path(video_path).stat().st_size / 1_000_000
    _status(on_status, f"Contenedor {container_id} creado; enviando el video directo a Meta ({size_mb:.1f} MB)...")
    _upload_binary_resumable(upload_uri, access_token, video_path, on_progress=on_progress)
    _status(on_status, "Video recibido por Meta; esperando el procesado...")
    status = _wait_for_container_ready(container_id, access_token, api_version=api_version, on_status=on_status)
    return container_id, status


def _publish_reel(ig_user_id: str, container_id: str, access_token: str,
                  api_version: Optional[str] = None) -> dict:
    return _request_json(
        "POST",
        _graph_api_url(f"{ig_user_id}/media_publish", api_version=api_version),
        params={
            "creation_id": container_id,
            "access_token": access_token,
        },
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def _get_media_info(media_id: str, access_token: str, api_version: Optional[str] = None) -> dict:
    return _request_json(
        "GET",
        _graph_api_url(media_id, api_version=api_version),
        params={
            "fields": "id,permalink,media_product_type",
            "access_token": access_token,
        },
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def save_upload_result(result_path: str, upload_result: dict, title: str = "",
                       description: str = "", caption: str = "", extra: Optional[dict] = None) -> dict:
    result_file = Path(result_path)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    save_data = {
        "media_id": upload_result.get("media_id"),
        "container_id": upload_result.get("container_id"),
        "url": upload_result.get("url"),
        "permalink_url": upload_result.get("permalink_url"),
        "status": upload_result.get("status"),
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ig_user_id": upload_result.get("ig_user_id"),
        "instagram_username": upload_result.get("instagram_username"),
        "instagram_name": upload_result.get("instagram_name"),
        "page_id": upload_result.get("page_id"),
        "page_name": upload_result.get("page_name"),
        "title": _clean_text(title, 120),
        "description": _clean_text(description, 2200),
        "caption": _clean_text(caption, 2200),
        "cloudinary_url": upload_result.get("cloudinary_url"),
        "cloudinary_public_id": upload_result.get("cloudinary_public_id"),
    }
    for key, value in (extra or {}).items():
        if value is not None:
            save_data[key] = value
    _write_json(result_file, save_data)
    _archive_upload_result(result_file, save_data)
    return save_data


def _cleanup_cloudinary(public_id: Optional[str]) -> dict:
    """Borra la copia intermedia de Cloudinary una vez publicado el reel.

    Se puede desactivar con CLOUDINARY_DELETE_AFTER_PUBLISH=0 en el .env, por
    si alguna vez conviene conservar el archivo (depurar, republicar sin
    volver a subir).

    Nunca propaga un error: el reel YA esta publicado y perder la limpieza es
    un costo de almacenamiento, no un fallo de la publicacion.
    """
    if str(_env("CLOUDINARY_DELETE_AFTER_PUBLISH", "1") or "1").strip().lower() in (
            "0", "false", "no", "off"):
        return {"deleted": False, "skipped": "desactivado por configuracion"}
    if not public_id:
        return {"deleted": False, "skipped": "Cloudinary no devolvio public_id"}

    try:
        from publish.cloudinary_uploader import delete_video

        resultado = delete_video(str(public_id))
        if resultado.get("deleted"):
            print(f"   [Cloudinary] Copia intermedia borrada: {public_id}")
        else:
            print(f"   [Cloudinary] No se pudo borrar {public_id}: "
                  f"{resultado.get('error') or resultado.get('state')}")
        return resultado
    except Exception as e:
        print(f"   [Cloudinary] Limpieza omitida: {e}")
        return {"deleted": False, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Portada (2026-09-22): la misma miniatura que YouTube y Facebook. La API solo la
# acepta al crear el contenedor, como cover_url (URL publica, JPEG): se sube la
# imagen a Cloudinary, Meta la descarga al procesar y despues se borra. Despues de
# publicado ya no se puede cambiar por API (si, a mano en la app de Instagram).
# ---------------------------------------------------------------------------

COVER_MAX_BYTES = 8 * 1024 * 1024


def _prepare_cover(cover_path: str, on_status=None) -> dict:
    """JPEG <= 8 MB subido a Cloudinary. Devuelve {url, public_id, local}. Lanza si falla."""
    from publish.cloudinary_uploader import upload_image
    try:
        from publish.thumbnail_publish import prepare_for_youtube
        prepared = prepare_for_youtube(cover_path, max_bytes=COVER_MAX_BYTES, jpeg_only=True,
                                       log=lambda m: _status(on_status, m.strip()))
        local = prepared["path"]
    except ImportError:                                   # VPS sin Pillow: solo JPEG tal cual
        if Path(cover_path).suffix.lower() not in (".jpg", ".jpeg"):
            raise ValueError("la portada tiene que ser JPEG y no hay Pillow para convertirla")
        local = str(cover_path)
    _status(on_status, f"Portada: subiendo {Path(cover_path).name} a Cloudinary (Instagram pide una URL)...")
    payload = upload_image(local, folder=_env("CLOUDINARY_UPLOAD_FOLDER", "video_optimizer/instagram"),
                           tags=["video-optimizer", "instagram", "cover"])
    return {"url": str(payload.get("secure_url") or "").strip(), "public_id": payload.get("public_id"),
            "local": local}


def _cleanup_cover(public_id: Optional[str]) -> None:
    if not public_id:
        return
    try:
        from publish.cloudinary_uploader import delete_video
        delete_video(str(public_id), resource_type="image")
    except Exception as exc:
        print(f"   [Cloudinary] No se pudo borrar la portada {public_id}: {exc}")


def cover_rejected(exc: BaseException) -> bool:
    """El error habla de la portada (no del video): se reintenta sin ella."""
    low = str(exc).lower()
    return any(w in low for w in ("cover", "thumbnail", "thumb_offset", "image"))


def verify_cover(media_id: str, access_token: str, local_path: str, api_version: Optional[str] = None,
                 fetch=None) -> dict:
    """Compara la portada que muestra Instagram (thumbnail_url) con la local."""
    try:
        import io as _io
        from PIL import Image
        from publish.thumbnail_publish import served_matches_local
    except ImportError:
        return {"checked": False, "match": None, "reason": "sin Pillow para comparar"}
    info = _request_json("GET", _graph_api_url(media_id, api_version=api_version),
                         params={"fields": "thumbnail_url", "access_token": access_token},
                         headers={"User-Agent": "VideoOptimizerPro/1.0"})
    url = str(info.get("thumbnail_url") or "").strip()
    if not url:
        return {"checked": False, "match": None, "reason": "Instagram no devolvio thumbnail_url"}
    if fetch is None:
        def fetch(u):
            r = requests.get(u, timeout=REQUEST_TIMEOUT)
            return r.content if r.status_code == 200 else None
    raw = fetch(url)
    if not raw:
        return {"checked": False, "match": None, "reason": "no se pudo bajar la portada"}
    served = Image.open(_io.BytesIO(raw)).convert("RGB")
    with Image.open(local_path) as im:
        ok, d = served_matches_local(served, im.convert("RGB"))
    return {"checked": True, "match": ok, "distance": d,
            "reason": "coincide con la local" if ok else "Instagram muestra otra imagen"}


def upload_video(video_path: str, title: str, description: str = "", share_to_feed: Optional[bool] = None,
                 on_progress=None, api_version: Optional[str] = None, on_status=None,
                 cover_path: Optional[str] = None, identity: Optional[dict] = None) -> dict:
    """Publica el reel. cover_path: None = sin portada (como antes); '' = no habia miniatura."""
    thumb = {"thumbnail_sent": str(cover_path) if cover_path else None, "thumbnail_set": False,
             "thumbnail_error": None}
    cover = {}
    if cover_path:
        try:
            cover = _prepare_cover(str(cover_path), on_status=on_status)
        except Exception as exc:
            thumb["thumbnail_error"] = f"la portada no se pudo preparar ({exc})"
            _status(on_status, f"ATENCION: {thumb['thumbnail_error']}; Instagram elige la portada")
    elif cover_path is not None:
        _status(on_status, "sin miniatura seleccionada: Instagram elige la portada")
    try:
        try:
            result = _upload_video_once(video_path, title, description, share_to_feed, on_progress,
                                        api_version, on_status, cover.get("url"), identity)
        except Exception as exc:
            if not (cover.get("url") and cover_rejected(exc)):
                raise
            thumb["thumbnail_error"] = f"Meta rechazo la portada ({str(exc)[:160]})"
            _status(on_status, f"ATENCION: {thumb['thumbnail_error']}; se publica sin ella")
            cover = dict(cover, url=None)
            result = _upload_video_once(video_path, title, description, share_to_feed, on_progress,
                                        api_version, on_status, None, identity)
    finally:
        _cleanup_cover(cover.get("public_id"))
    if cover.get("url"):
        thumb["thumbnail_set"] = True
        try:
            thumb["thumbnail_verify"] = verify_cover(result["media_id"], result.get("_access_token") or "",
                                                     cover["local"], api_version=api_version)
        except Exception as exc:
            thumb["thumbnail_verify"] = {"checked": False, "match": None, "reason": f"{type(exc).__name__}: {exc}"}
        v = thumb["thumbnail_verify"]
        if v.get("match") is False:
            _status(on_status, f"ATENCION: la portada se envio pero {v['reason']}.")
        else:
            _status(on_status, "Portada puesta" + (" y verificada." if v.get("match") else "."))
    result.pop("_access_token", None)
    if cover_path is not None:
        result.update(thumb)
    return result


INSTAGRAM_MAX_UPLOAD_MB = float(os.getenv("INSTAGRAM_MAX_UPLOAD_MB", "90") or 90)   # Cloudinary (plan gratis) rechaza >100 MB con 413
INSTAGRAM_REENCODE_MAXRATE = os.getenv("INSTAGRAM_REENCODE_MAXRATE", "8M") or "8M"


def ensure_instagram_size(video_path: str, on_status=None) -> str:
    """Devuelve una ruta apta para subir: si el mp4 pesa mas que INSTAGRAM_MAX_UPLOAD_MB lo recodifica con tope de
    bitrate (H.264/AAC, faststart) en un archivo hermano `<nombre>_ig.mp4` (se reutiliza si ya existe y es mas nuevo).
    Caso real (2026-11-10): un Short de 50 s a crf 21 pesaba 115 MB; Cloudinary respondio 413 y la subida directa a Meta
    fallo; recodificado a 42 MB (maxrate 8M) se publico bien."""
    import shutil
    import subprocess
    src = Path(video_path)
    if src.stat().st_size <= INSTAGRAM_MAX_UPLOAD_MB * 1_000_000:
        return str(src)
    out = src.with_name(src.stem + "_ig.mp4")
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime and out.stat().st_size <= INSTAGRAM_MAX_UPLOAD_MB * 1_000_000:
        return str(out)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    _status(on_status, f"El video pesa {src.stat().st_size / 1_000_000:.0f} MB (> {INSTAGRAM_MAX_UPLOAD_MB:.0f}); recodificando para Instagram...")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-preset", "medium", "-crf", "23",
           "-maxrate", INSTAGRAM_REENCODE_MAXRATE, "-bufsize", "2x".replace("2x", str(int(float(INSTAGRAM_REENCODE_MAXRATE.rstrip("MmKk")) * 2)) + INSTAGRAM_REENCODE_MAXRATE[-1]),
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"No se pudo recodificar para Instagram: {(r.stderr or '')[-300:]}")
    if out.stat().st_size > INSTAGRAM_MAX_UPLOAD_MB * 1_000_000:
        raise RuntimeError(f"El video recodificado sigue pesando {out.stat().st_size / 1_000_000:.0f} MB")
    return str(out)


def _upload_video_once(video_path: str, title: str, description: str, share_to_feed: Optional[bool],
                       on_progress, api_version: Optional[str], on_status, cover_url: Optional[str],
                       identity: Optional[dict]) -> dict:
    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video not found: {video_file}")
    video_file = Path(ensure_instagram_size(str(video_file), on_status))

    identity = identity or _resolve_instagram_identity(api_version=api_version)
    access_token = str(identity.get("access_token") or "").strip()
    ig_user_id = str(identity.get("ig_user_id") or "").strip()
    if not ig_user_id:
        raise RuntimeError("Could not resolve INSTAGRAM_BUSINESS_ACCOUNT_ID.")

    publish_to_feed = bool(True if share_to_feed is None else share_to_feed)
    caption = _compose_caption(title, description)
    cuenta = identity.get('instagram_username') or ig_user_id

    container_id = container_status = None
    transport = "resumable"
    if UPLOAD_MODE != "url":
        _status(on_status, f"Cuenta @{cuenta}; subida directa (resumable), sin Cloudinary...")
        try:
            container_id, container_status = _publish_via_resumable(
                ig_user_id, access_token, str(video_file), caption, publish_to_feed,
                api_version=api_version, on_progress=on_progress, on_status=on_status,
                **({"cover_url": cover_url} if cover_url else {}),
            )
        except Exception as exc:
            if cover_url and cover_rejected(exc):
                raise                                   # upload_video reintenta sin portada
            _status(on_status, f"Subida directa fallo ({exc}); probando el camino por URL (Cloudinary)...")
            container_id = None

    cloudinary_result = {}
    public_video_url = ""
    if container_id is None:
        transport = "url"
        _status(on_status, f"Cuenta @{cuenta}; subiendo a Cloudinary ({video_file.stat().st_size / 1_000_000:.1f} MB)...")
        cloudinary_result = upload_video_to_cloudinary(
            str(video_file),
            folder=_env("CLOUDINARY_UPLOAD_FOLDER", "video_optimizer/instagram"),
            tags=["video-optimizer", "instagram", "reels"],
            on_progress=on_progress,
        )
        public_video_url = str(cloudinary_result.get("secure_url") or "").strip()
        if not public_video_url:
            raise RuntimeError(f"Cloudinary did not return a secure_url: {cloudinary_result}")
        _status(on_status, "Cloudinary listo; creando el contenedor del reel en Meta...")

    try:
        if container_id is None:
            container_id, container_status = _create_container_with_retries(
                ig_user_id=ig_user_id,
                access_token=access_token,
                video_url=public_video_url,
                caption=caption,
                share_to_feed=publish_to_feed,
                api_version=api_version,
                on_status=on_status,
                **({"cover_url": cover_url} if cover_url else {}),
            )
        _status(on_status, "Reel procesado; publicando...")
        publish_response = _publish_reel(
            ig_user_id=ig_user_id,
            container_id=container_id,
            access_token=access_token,
            api_version=api_version,
        )
        media_id = str(publish_response.get("id") or "").strip()
        if not media_id:
            raise RuntimeError(f"Instagram did not return a published media id: {publish_response}")
    except Exception:
        # No se publico: la copia de Cloudinary no sirve para nada y antes se
        # quedaba huerfana (asi se juntaron 145 en la cuenta). Un reintento
        # manual vuelve a subir de todos modos.
        _cleanup_cloudinary(cloudinary_result.get("public_id"))
        raise

    media_info = _get_media_info(media_id, access_token=access_token, api_version=api_version)
    permalink = _normalize_permalink(media_info.get("permalink"))
    _status(on_status, f"Publicado: {permalink or media_id}")

    # Recien ACA se borra la copia de Cloudinary: Meta ya descargo el video
    # durante la creacion del contenedor y el reel esta publicado con su
    # media_id. Borrar antes dejaria a Instagram sin de donde bajarlo.
    cleanup = _cleanup_cloudinary(cloudinary_result.get("public_id"))

    return {
        "media_id": media_id,
        "container_id": container_id,
        "url": permalink,
        "permalink_url": permalink,
        "status": "published",
        "ig_user_id": ig_user_id,
        "instagram_username": identity.get("instagram_username"),
        "instagram_name": identity.get("instagram_name"),
        "page_id": identity.get("page_id"),
        "page_name": identity.get("page_name"),
        "transport": transport,
        "cloudinary_url": public_video_url or None,
        "cloudinary_public_id": cloudinary_result.get("public_id"),
        "cloudinary_cleanup": cleanup,
        "container_status": container_status,
        "publish_response": publish_response,
        "media_info": media_info,
        "share_to_feed": publish_to_feed,
        "_access_token": access_token,            # solo para verificar la portada; se quita antes de devolver
    }


def _find_cover(output_dir: Path) -> Optional[Path]:
    try:
        from publish.thumbnail_publish import find_staged_thumbnail
        return find_staged_thumbnail(output_dir)
    except ImportError:
        for name in ("thumbnail.jpg", "thumbnail.jpeg"):
            if (output_dir / name).is_file():
                return output_dir / name
        return None


def _seo_enabled() -> bool:
    return str(os.getenv("INSTAGRAM_SEO", "1")).strip().lower() not in ("0", "false", "no", "off")


def upload_from_metadata(output_dir: str, share_to_feed: Optional[bool] = None, on_progress=None,
                         on_status=None, optimize: bool = True, thumbnail: bool = True) -> dict:
    """Publica el reel de una carpeta con video + metadata.

    optimize: primera linea (= titulo), cuerpo y hashtags con la investigacion de YouTube
              (facebook_metadata.prepare_instagram_metadata); INSTAGRAM_SEO=0 lo apaga.
    thumbnail: la miniatura de la carpeta (thumbnail.*) como portada del reel.
    """
    output_dir = Path(output_dir)
    metadata = _load_upload_metadata(output_dir)

    from publish.output_video_locator import find_output_video
    video_path = find_output_video(output_dir)
    if not video_path:
        raise FileNotFoundError(f"No video file found in {output_dir}")
    video_path = Path(video_path)

    title = metadata.get("title") or output_dir.name
    description = metadata.get("description") or ""
    # La cuenta del canal elegido en el Studio (sus claves con sufijo) o la global.
    identity = _resolve_instagram_identity(channel=str(metadata.get("upload_channel") or "").strip() or None)
    brand = identity.get("instagram_name") or identity.get("page_name") or ""

    seo = None
    if optimize and _seo_enabled():
        try:
            from publish.facebook_metadata import prepare_instagram_metadata
            seo = prepare_instagram_metadata(metadata, brand=brand, log=lambda m: _status(on_status, str(m).strip()))
            title = seo["title"] or title
            description = seo["description"] or description
            _status(on_status, seo["summary"])
        except ImportError:
            pass
        except Exception as exc:
            _status(on_status, f"optimizacion no disponible ({type(exc).__name__}: {exc}); se usa la metadata tal cual")

    # Atribucion de la musica (CC BY la exige): al final, despues de optimizar. El caption
    # es titulo + descripcion con tope 2200, asi que la descripcion deja lugar al titulo.
    if metadata.get("music_attribution"):
        try:
            from publish.music_license import with_attribution, DESCRIPTION_LIMITS
            room = DESCRIPTION_LIMITS["instagram"] - len(str(title or "")) - 2
            description = with_attribution(description, metadata["music_attribution"], room)
        except ImportError:
            description = f"{description}\n\n{metadata['music_attribution']}".strip()

    cover = _find_cover(output_dir) if thumbnail else None
    result = upload_video(
        video_path=str(video_path),
        title=title,
        description=description,
        share_to_feed=share_to_feed,
        on_progress=on_progress,
        on_status=on_status,
        cover_path=str(cover) if cover else ("" if thumbnail else None),
        identity=identity,
    )
    result["title_sent"] = title
    result["title_original"] = metadata.get("title") or None
    if seo:
        result["hashtags_sent"] = seo["hashtags"]
        result["instagram_seo"] = {k: seo.get(k) for k in ("summary", "keyword", "lead_repaired",
                                                          "hashtags_dropped", "source")}
    save_upload_result(
        result_path=output_dir / "instagram_upload_result.json",
        upload_result=result,
        title=title,
        description=description,
        caption=_compose_caption(title, description),
        extra={k: result.get(k) for k in ("title_original", "hashtags_sent", "instagram_seo", "thumbnail_sent",
                                          "thumbnail_set", "thumbnail_error", "thumbnail_verify")},
    )
    return result


def check_auth(channel: Optional[str] = None) -> dict:
    try:
        identity = _resolve_instagram_identity(channel=channel)
        limit_data = _content_publishing_limit(
            str(identity.get("ig_user_id") or ""),
            str(identity.get("access_token") or ""),
        )
        limit_entry = ((limit_data or {}).get("data") or [{}])[0] or {}
        config = limit_entry.get("config") or {}
        cloudinary_auth = check_cloudinary_auth()
        return {
            "authenticated": True,
            "ig_user_id": identity.get("ig_user_id"),
            "instagram_username": identity.get("instagram_username"),
            "instagram_name": identity.get("instagram_name"),
            "page_id": identity.get("page_id"),
            "page_name": identity.get("page_name"),
            "quota_total": config.get("quota_total"),
            "quota_usage": limit_entry.get("quota_usage"),
            "cloudinary_authenticated": bool(cloudinary_auth.get("authenticated")),
            "cloudinary_error": cloudinary_auth.get("error"),
            "upload_ready": bool(cloudinary_auth.get("authenticated")),
            "error": None,
        }
    except Exception as e:
        return {
            "authenticated": False,
            "ig_user_id": None,
            "instagram_username": None,
            "instagram_name": None,
            "page_id": None,
            "page_name": None,
            "quota_total": None,
            "quota_usage": None,
            "cloudinary_authenticated": None,
            "cloudinary_error": None,
            "upload_ready": False,
            "error": str(e),
        }
