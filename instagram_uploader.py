"""
instagram_uploader.py - Publish Instagram Reels using the Meta Graph API.

This implementation uses Cloudinary to host the local MP4 temporarily, because
Instagram publishing requires a publicly accessible video URL.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from cloudinary_uploader import check_auth as check_cloudinary_auth
from cloudinary_uploader import upload_video as upload_video_to_cloudinary
from env_loader import load_project_env

PROJECT_DIR = Path(__file__).resolve().parent
load_project_env(PROJECT_DIR)

INSTAGRAM_METADATA_FILES = ("instagram_metadata.json", "facebook_metadata.json", "metadata.json")
REQUEST_TIMEOUT = 60
POLL_INTERVAL_SECONDS = 15
POLL_TIMEOUT_SECONDS = 300


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    if value is None:
        return None
    text = str(value).strip()
    return text or default


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


def _resolve_instagram_identity(api_version: Optional[str] = None) -> dict:
    user_access_token = _env("INSTAGRAM_USER_ACCESS_TOKEN") or _env("FACEBOOK_USER_ACCESS_TOKEN")
    if not user_access_token:
        raise RuntimeError(
            "Instagram auth not configured. Set INSTAGRAM_USER_ACCESS_TOKEN or "
            "FACEBOOK_USER_ACCESS_TOKEN in .env."
        )

    page_id = _env("INSTAGRAM_PAGE_ID") or _env("FACEBOOK_PAGE_ID")
    ig_user_id = _env("INSTAGRAM_BUSINESS_ACCOUNT_ID")

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
                           share_to_feed: bool = True, api_version: Optional[str] = None) -> dict:
    return _request_json(
        "POST",
        _graph_api_url(f"{ig_user_id}/media", api_version=api_version),
        params={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": str(bool(share_to_feed)).lower(),
            "access_token": access_token,
        },
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
                              timeout_seconds: int = POLL_TIMEOUT_SECONDS) -> dict:
    deadline = time.time() + max(30, int(timeout_seconds))
    last_state = {}
    while time.time() < deadline:
        last_state = get_container_status(container_id, access_token, api_version=api_version)
        status_code = str(last_state.get("status_code") or "").strip().upper()
        if status_code in {"FINISHED", "PUBLISHED"}:
            return last_state
        if status_code in {"ERROR", "EXPIRED"}:
            status_text = str(last_state.get("status") or status_code).strip()
            raise RuntimeError(f"Instagram container failed: {status_text}")
        time.sleep(POLL_INTERVAL_SECONDS)
    return last_state


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
                       description: str = "", caption: str = "") -> dict:
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
        from cloudinary_uploader import delete_video

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


def upload_video(video_path: str, title: str, description: str = "", share_to_feed: Optional[bool] = None,
                 on_progress=None, api_version: Optional[str] = None) -> dict:
    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video not found: {video_file}")

    identity = _resolve_instagram_identity(api_version=api_version)
    access_token = str(identity.get("access_token") or "").strip()
    ig_user_id = str(identity.get("ig_user_id") or "").strip()
    if not ig_user_id:
        raise RuntimeError("Could not resolve INSTAGRAM_BUSINESS_ACCOUNT_ID.")

    publish_to_feed = bool(True if share_to_feed is None else share_to_feed)
    cloudinary_result = upload_video_to_cloudinary(
        str(video_file),
        folder=_env("CLOUDINARY_UPLOAD_FOLDER", "video_optimizer/instagram"),
        tags=["video-optimizer", "instagram", "reels"],
        on_progress=on_progress,
    )
    public_video_url = str(cloudinary_result.get("secure_url") or "").strip()
    if not public_video_url:
        raise RuntimeError(f"Cloudinary did not return a secure_url: {cloudinary_result}")

    caption = _compose_caption(title, description)
    container = _create_reel_container(
        ig_user_id=ig_user_id,
        access_token=access_token,
        video_url=public_video_url,
        caption=caption,
        share_to_feed=publish_to_feed,
        api_version=api_version,
    )
    container_id = str(container.get("id") or "").strip()
    if not container_id:
        raise RuntimeError(f"Instagram did not return a media container id: {container}")

    container_status = _wait_for_container_ready(
        container_id=container_id,
        access_token=access_token,
        api_version=api_version,
    )
    publish_response = _publish_reel(
        ig_user_id=ig_user_id,
        container_id=container_id,
        access_token=access_token,
        api_version=api_version,
    )
    media_id = str(publish_response.get("id") or "").strip()
    if not media_id:
        raise RuntimeError(f"Instagram did not return a published media id: {publish_response}")

    media_info = _get_media_info(media_id, access_token=access_token, api_version=api_version)
    permalink = _normalize_permalink(media_info.get("permalink"))

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
        "cloudinary_url": public_video_url,
        "cloudinary_public_id": cloudinary_result.get("public_id"),
        "cloudinary_cleanup": cleanup,
        "container_status": container_status,
        "publish_response": publish_response,
        "media_info": media_info,
        "share_to_feed": publish_to_feed,
    }


def upload_from_metadata(output_dir: str, share_to_feed: Optional[bool] = None, on_progress=None) -> dict:
    output_dir = Path(output_dir)
    metadata = _load_upload_metadata(output_dir)

    video_path = None
    for pattern in ("*.mp4", "*.mov", "*.mkv", "*.webm"):
        videos = list(output_dir.glob(pattern))
        if videos:
            video_path = videos[0]
            break
    if not video_path:
        raise FileNotFoundError(f"No video file found in {output_dir}")

    title = metadata.get("title") or output_dir.name
    description = metadata.get("description") or ""
    result = upload_video(
        video_path=str(video_path),
        title=title,
        description=description,
        share_to_feed=share_to_feed,
        on_progress=on_progress,
    )
    save_upload_result(
        result_path=output_dir / "instagram_upload_result.json",
        upload_result=result,
        title=title,
        description=description,
        caption=_compose_caption(title, description),
    )
    return result


def check_auth() -> dict:
    try:
        identity = _resolve_instagram_identity()
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
