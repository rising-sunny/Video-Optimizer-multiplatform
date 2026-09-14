"""
cloudinary_uploader.py - Upload local assets to Cloudinary via the Upload API.

Used by Instagram publishing, which requires a public video URL.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

# requests-toolbelt da progreso real en multipart uploads (Cloudinary)
_HAS_TOOLBELT = False
try:
    from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
    _HAS_TOOLBELT = True
except ImportError:
    pass

from env_loader import load_project_env

PROJECT_DIR = Path(__file__).resolve().parent
load_project_env(PROJECT_DIR)

REQUEST_TIMEOUT = 120


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    if value is None:
        return None
    text = str(value).strip()
    return text or default


def _resolve_config() -> tuple[str, str, str, str]:
    cloud_name = _env("CLOUDINARY_CLOUD_NAME")
    api_key = _env("CLOUDINARY_API_KEY")
    api_secret = _env("CLOUDINARY_API_SECRET")
    upload_prefix = _env("CLOUDINARY_UPLOAD_PREFIX", "https://api.cloudinary.com")
    cloudinary_url = _env("CLOUDINARY_URL")

    if cloudinary_url and (not cloud_name or not api_key or not api_secret):
        parsed = urlparse(cloudinary_url)
        if parsed.scheme == "cloudinary":
            if not api_key:
                api_key = parsed.username
            if not api_secret:
                api_secret = parsed.password
            if not cloud_name:
                cloud_name = parsed.hostname

    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError(
            "Cloudinary auth not configured. Set CLOUDINARY_URL or "
            "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in .env."
        )
    return cloud_name, api_key, api_secret, upload_prefix.rstrip("/")


def _upload_url(resource_type: str = "video") -> str:
    cloud_name, _api_key, _api_secret, upload_prefix = _resolve_config()
    normalized_type = str(resource_type or "video").strip() or "video"
    return f"{upload_prefix}/v1_1/{cloud_name}/{normalized_type}/upload"


def check_auth(verify_remote: bool = True) -> dict:
    """Verifica las credenciales de Cloudinary CONTRA el servidor.

    Antes solo leia el .env y devolvia authenticated=True si las variables
    estaban: con una API key revocada respondia lo mismo que con una buena.
    Cloudinary es el puente obligatorio para publicar en Instagram (la API de
    Meta pide una URL publica del video), asi que un "todo bien" falso ahi se
    descubre recien cuando falla la publicacion.

    Devuelve ademas el plan y los creditos consumidos: en el plan Free son 25
    al mes y el almacenamiento acumulado tambien cuenta.
    """
    try:
        cloud_name, api_key, api_secret, upload_prefix = _resolve_config()
    except Exception as e:
        return {
            "authenticated": False,
            "cloud_name": None,
            "api_key_suffix": None,
            "upload_prefix": None,
            "error": str(e),
        }

    info = {
        "authenticated": True,
        "cloud_name": cloud_name,
        "api_key_suffix": api_key[-4:] if len(api_key) >= 4 else api_key,
        "upload_prefix": upload_prefix,
        "error": None,
    }
    if not verify_remote:
        info["verified_remotely"] = False
        return info

    try:
        resp = requests.get(
            f"{upload_prefix}/v1_1/{cloud_name}/usage",
            auth=(api_key, api_secret),
            timeout=30,
        )
        if resp.status_code == 401:
            info.update(authenticated=False, verified_remotely=True,
                        error="401: la API key o el secret de Cloudinary no son validos")
            return info
        if resp.status_code >= 400:
            info.update(verified_remotely=False,
                        error=f"{resp.status_code}: {(resp.text or '')[:160]}")
            return info

        datos = resp.json() or {}
        creditos = datos.get("credits") or {}
        info.update(
            verified_remotely=True,
            plan=datos.get("plan"),
            credits_used=creditos.get("usage"),
            credits_limit=creditos.get("limit"),
            credits_percent=creditos.get("used_percent"),
            resources=datos.get("resources"),
        )
        return info
    except Exception as e:
        # Sin red no se puede afirmar que las claves esten mal: se informa que
        # no se pudo verificar, sin declararlas invalidas.
        info.update(verified_remotely=False, error=f"no se pudo verificar: {e}")
        return info


def delete_video(public_id: str, resource_type: str = "video") -> dict:
    """Borra de Cloudinary un video ya publicado.

    Cloudinary aca es solo un PUENTE: la API de Instagram no acepta el archivo,
    pide una URL publica, asi que se sube, Meta lo descarga, y despues la copia
    queda ahi ocupando lugar para siempre. En el plan Free el almacenamiento
    cuenta contra los 25 creditos mensuales, y publicando a diario crece solo
    (al 2026-09-03 habia 145 recursos y 1.5 GB acumulados).

    Nunca lanza: limpiar es una tarea de mantenimiento y no puede afectar a una
    publicacion que ya salio bien. Devuelve {'deleted': bool, ...}.
    """
    pid = str(public_id or "").strip()
    if not pid:
        return {"deleted": False, "error": "public_id vacio"}

    try:
        cloud_name, api_key, api_secret, upload_prefix = _resolve_config()
        resp = requests.delete(
            f"{upload_prefix}/v1_1/{cloud_name}/resources/{resource_type}/upload",
            params={"public_ids[]": pid},
            auth=(api_key, api_secret),
            timeout=60,
        )
        if resp.status_code >= 400:
            return {"deleted": False, "public_id": pid,
                    "error": f"{resp.status_code}: {(resp.text or '')[:160]}"}

        datos = resp.json() or {}
        # Cloudinary responde {"deleted": {"<public_id>": "deleted"|"not_found"}}
        estado = str((datos.get("deleted") or {}).get(pid) or "").strip().lower()
        return {
            "deleted": estado == "deleted",
            "public_id": pid,
            "state": estado or "sin estado",
            "error": None,
        }
    except Exception as e:
        return {"deleted": False, "public_id": pid, "error": str(e)[:200]}


def upload_video(video_path: str, folder: Optional[str] = None, public_id: Optional[str] = None,
                 tags: Optional[list[str]] = None, on_progress=None) -> dict:
    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video not found: {video_file}")

    _cloud_name, api_key, api_secret, _upload_prefix = _resolve_config()
    file_size = video_file.stat().st_size
    upload_folder = folder or _env("CLOUDINARY_UPLOAD_FOLDER", "video_optimizer/instagram")

    data = {
        "folder": str(upload_folder or "").strip(),
        "use_filename": "true",
        "unique_filename": "true",
        "overwrite": "false",
    }
    if public_id:
        data["public_id"] = str(public_id).strip()
    if tags:
        normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        if normalized_tags:
            data["tags"] = ",".join(normalized_tags)

    if on_progress:
        on_progress(0, file_size)

    with open(video_file, "rb") as handle:
        if on_progress and _HAS_TOOLBELT:
            # requests-toolbelt da progreso real en multipart uploads
            fields = dict(data)
            fields["file"] = (video_file.name, handle, "video/mp4")
            encoder = MultipartEncoder(fields=fields)
            _last = [0]

            def _monitor_cb(monitor):
                sent = monitor.bytes_read
                if sent - _last[0] >= 512 * 1024 or sent >= encoder.len:
                    on_progress(sent, encoder.len)
                    _last[0] = sent

            monitor = MultipartEncoderMonitor(encoder, _monitor_cb)
            response = requests.post(
                _upload_url("video"),
                auth=(api_key, api_secret),
                data=monitor,
                headers={
                    "Content-Type": monitor.content_type,
                    "User-Agent": "VideoOptimizerPro/1.0",
                },
                timeout=max(REQUEST_TIMEOUT, 600),
            )
        else:
            response = requests.post(
                _upload_url("video"),
                auth=(api_key, api_secret),
                data=data,
                files={"file": handle},
                timeout=max(REQUEST_TIMEOUT, 600),
                headers={"User-Agent": "VideoOptimizerPro/1.0"},
            )
    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error") or {}
            message = str(error.get("message") or response.text or "Cloudinary upload failed").strip()
            raise RuntimeError(f"Cloudinary upload failed: {message}")
        response.raise_for_status()

    if on_progress:
        on_progress(file_size, file_size)

    payload = response.json() if response.text.strip() else {}
    secure_url = str(payload.get("secure_url") or "").strip()
    if not secure_url:
        raise RuntimeError(f"Cloudinary did not return a secure_url: {payload}")
    return payload
