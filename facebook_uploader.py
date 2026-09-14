"""
facebook_uploader.py - Upload Facebook Page Reels via the Graph API.

Auth options:
1. Preferred: FACEBOOK_PAGE_ACCESS_TOKEN
2. Fallback: FACEBOOK_USER_ACCESS_TOKEN + FACEBOOK_PAGE_ID

Optional env vars:
- FACEBOOK_GRAPH_API_VERSION (default: v23.0)
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Wrapper para reportar progreso de subida byte-a-byte
# ---------------------------------------------------------------------------

class _ProgressReader:
    """File-like wrapper that calls *callback(sent, total)* as data is read."""

    def __init__(self, fh, total_size: int, callback, report_every: int = 512 * 1024):
        self._fh = fh
        self._total = total_size
        self._sent = 0
        self._callback = callback
        self._report_every = report_every
        self._last_report = 0

    # requests llama .read(size) para consumir el body
    def read(self, size: int = -1) -> bytes:
        data = self._fh.read(size)
        if data:
            self._sent += len(data)
            if self._callback and (self._sent - self._last_report >= self._report_every or self._sent >= self._total):
                self._callback(self._sent, self._total)
                self._last_report = self._sent
        return data

    # Proxy de atributos que requests puede necesitar (seek, tell, len, etc.)
    def __getattr__(self, name):
        return getattr(self._fh, name)

    def __len__(self):
        return self._total

from env_loader import load_project_env

PROJECT_DIR = Path(__file__).resolve().parent
load_project_env(PROJECT_DIR)
FACEBOOK_METADATA_FILES = ("facebook_metadata.json", "metadata.json")

REQUEST_TIMEOUT = 120
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 300
# Si TODAS las consultas de estado fallan, se abandona a los 45s en vez
# de agotar POLL_TIMEOUT_SECONDS: el reel ya esta publicado y esos 5
# minutos extra empujaban el trabajo del VPS mas alla del tope de SSH.
STATUS_ERROR_GRACE_SECONDS = 45


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


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    if value is None:
        return None
    text = str(value).strip()
    return text or default


def _default_api_version() -> str:
    return str(_env("FACEBOOK_GRAPH_API_VERSION", "v23.0") or "v23.0")


def _graph_api_url(path: str, api_version: Optional[str] = None) -> str:
    version = str(api_version or _default_api_version()).strip()
    normalized_path = str(path or "").lstrip("/")
    return f"https://graph.facebook.com/{version}/{normalized_path}"


def _rupload_url(video_id: str, api_version: Optional[str] = None) -> str:
    version = str(api_version or _default_api_version()).strip()
    return f"https://rupload.facebook.com/video-upload/{version}/{video_id}"


def _clean_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,")
    return trimmed or text[:max_chars].rstrip(" ,")


def _load_upload_metadata(output_dir: Path) -> dict:
    for filename in FACEBOOK_METADATA_FILES:
        meta_path = output_dir / filename
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as handle:
                datos = json.load(handle)
            # Un archivo con `null` o con una lista no es metadata utilizable:
            # devolver eso tal cual hacia reventar al llamador con
            # "'NoneType' object has no attribute 'get'".
            return datos if isinstance(datos, dict) else {}
    raise FileNotFoundError(
        f"No Facebook metadata found in {output_dir}. "
        f"Expected one of: {', '.join(FACEBOOK_METADATA_FILES)}"
    )


def _normalize_video_state(video_state: str = "PUBLISHED",
                           scheduled_publish_time: Optional[str | int | float] = None) -> str:
    if scheduled_publish_time is not None:
        return "SCHEDULED"
    return str(video_state or "PUBLISHED").upper()


def _normalize_scheduled_publish_time(value: Optional[str | int | float]) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        timestamp = int(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            timestamp = int(text)
        else:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamp = int(dt.timestamp())
    if timestamp <= int(time.time()):
        raise RuntimeError("Facebook scheduled publish time must be in the future.")
    return timestamp


def _timestamp_to_iso_utc(value: Optional[str | int | float]) -> Optional[str]:
    timestamp = _normalize_scheduled_publish_time(value) if value is not None else None
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_permalink(url: Optional[str], video_id: Optional[str] = None) -> Optional[str]:
    text = str(url or "").strip()
    if not text and video_id:
        return f"https://www.facebook.com/reel/{video_id}"
    if text.startswith("/"):
        return f"https://www.facebook.com{text}"
    return text or None


class FacebookRequestError(requests.exceptions.RequestException):
    """Error de red hacia Graph API, ya sin el token en el mensaje."""


_TOKEN_RE = re.compile(r"(access_token=)[^&\s\"']+", re.IGNORECASE)


def _redact_tokens(text: str) -> str:
    """Saca los access_token de cualquier texto antes de loguearlo."""
    return _TOKEN_RE.sub(r"\1<REDACTED>", str(text))


def _request_json(method: str, url: str, timeout: Optional[float] = None, **kwargs) -> dict:
    try:
        response = requests.request(method, url, timeout=timeout or REQUEST_TIMEOUT, **kwargs)
    except requests.exceptions.RequestException as exc:
        # El token viaja en la query string: urllib3 mete la URL entera en el
        # texto de la excepcion, y de ahi al traceback, al log y a cualquier
        # lado donde se pegue ese log. `from None` corta la cadena de causas
        # para que la version sin censurar no reaparezca mas abajo.
        raise FacebookRequestError(
            f"{type(exc).__name__}: {_redact_tokens(exc)}"
        ) from None
    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error") or {}
            message = str(error.get("message") or response.text or "Facebook API request failed").strip()
            code = error.get("code")
            if code is not None:
                raise RuntimeError(f"Facebook API error {code}: {message}")
            raise RuntimeError(f"Facebook API error: {message}")
        response.raise_for_status()
    if not response.text.strip():
        return {}
    return response.json()


def _probe_page_token(token: str, api_version: Optional[str] = None) -> tuple:
    """Una sola consulta que responde las DOS preguntas del page token.

    `/me` sobre un page token devuelve la identidad de SU pagina, asi que el
    mismo request dice si el token vive y a donde publica. Van juntas a
    proposito: preguntarlas por separado duplicaba la llamada a la API.

    Devuelve (estado, page_id):
      "ok"      -> token vivo; page_id es la pagina a la que pertenece
      "dead"    -> Facebook lo rechazo (tipico 190 por vencimiento)
      "unknown" -> no se pudo averiguar (sin red); no se concluye nada
    """
    if not token:
        return "dead", None
    try:
        data = _request_json(
            "GET",
            _graph_api_url("me", api_version=api_version),
            params={"fields": "id", "access_token": token},
        )
        return "ok", (str(data.get("id") or "").strip() or None)
    except requests.exceptions.RequestException:
        # Sin red no se puede afirmar que el token este mal: se lo da por bueno
        # y que falle mas adelante con el error real.
        return "unknown", None
    except Exception:
        return "dead", None


def _manageable_pages(user_access_token: str, api_version: Optional[str] = None) -> list:
    """Paginas que el user token puede administrar (mejor mensaje de error)."""
    try:
        data = _request_json(
            "GET",
            _graph_api_url("me/accounts", api_version=api_version),
            params={"fields": "id,name", "access_token": user_access_token},
        )
        return list(data.get("data") or [])
    except Exception:
        return []


def _granular_page_scopes(user_access_token: str, page_id: Optional[str],
                          api_version: Optional[str] = None) -> Optional[list]:
    """A que paginas alcanza cada permiso `pages_*` DE ESTE token.

    Meta congela en el token que paginas cubre cada scope, segun lo que se eligio
    en el dialogo "que paginas queres usar con esta app" al autorizarla. Un rol
    de administrador en el Business NO lo cambia, y el token viejo tampoco se
    actualiza: hay que reautorizar la app y emitir un token nuevo.
    """
    try:
        data = _request_json(
            "GET",
            _graph_api_url("debug_token", api_version=api_version),
            params={"input_token": user_access_token, "access_token": user_access_token},
        )
    except Exception:
        return None

    detalle = []
    for grant in ((data.get("data") or {}).get("granular_scopes") or []):
        scope = str(grant.get("scope") or "")
        if not scope.startswith("pages_"):
            continue
        targets = grant.get("target_ids")
        if targets is None:
            detalle.append((scope, None, True))
        else:
            ids = [str(t) for t in targets]
            detalle.append((scope, ids, page_id is not None and str(page_id) in ids))
    return detalle


def _page_token_help(page_id: Optional[str], user_access_token: str,
                     api_version: Optional[str] = None) -> str:
    """Error accionable en vez del 190 generico de Facebook."""
    lines = [
        "No hay un Facebook Page access token utilizable.",
        "  - FACEBOOK_PAGE_ACCESS_TOKEN esta vencido o fue rechazado.",
        "  - Tampoco se pudo derivar uno desde FACEBOOK_USER_ACCESS_TOKEN"
        f" para la pagina {page_id or '(sin FACEBOOK_PAGE_ID)'}.",
    ]

    pages = _manageable_pages(user_access_token, api_version=api_version)
    if pages:
        lines.append("  - Paginas que ESE user token si administra:")
        for page in pages:
            lines.append(f"      {page.get('name')} (id={page.get('id')})")
    else:
        lines.append("  - Ese user token no administra ninguna pagina.")

    scopes = _granular_page_scopes(user_access_token, page_id, api_version=api_version)
    if scopes and page_id and not any(cubre for _, _, cubre in scopes):
        lines.append(f"  - Permisos pages_* de este token (NO cubren {page_id}):")
        for scope, ids, _ in scopes:
            lines.append(f"      {scope} -> {'todas' if ids is None else ', '.join(ids)}")
        lines.append(
            "  - Causa: Meta limita cada permiso pages_* a las paginas que se"
            " tildaron al autorizar la app. Tener rol de administrador en el"
            " Business NO alcanza, y el token ya emitido NO se actualiza solo."
        )
        lines.append(
            "  - Solucion: reautorizar la app incluyendo esa pagina (Facebook >"
            " Configuracion > Aplicaciones y sitios web > la app > Editar) y"
            " emitir un token NUEVO; o generar un token de usuario del sistema"
            " en el Business que posee la pagina."
        )

    return "\n".join(lines)


def _resolve_page_access_token(api_version: Optional[str] = None) -> tuple[str, Optional[str]]:
    page_access_token = _env("FACEBOOK_PAGE_ACCESS_TOKEN")
    user_access_token = _env("FACEBOOK_USER_ACCESS_TOKEN")
    page_id = _env("FACEBOOK_PAGE_ID")

    if page_access_token:
        # El token puede ser PERFECTAMENTE VALIDO y aun asi ser de OTRA pagina.
        # Paso al abrir la pagina del canal nuevo (2026-09-02): alcanzaba con
        # cambiar FACEBOOK_PAGE_ID y dejar el token viejo para que el pipeline
        # devolviera (token de Stunning Revelations, id de Stunning Facts of
        # History). Publicar en la pagina equivocada es peor que no publicar.
        estado, pagina_del_token = _probe_page_token(page_access_token, api_version=api_version)
        if page_id and pagina_del_token and str(pagina_del_token) != str(page_id):
            aviso = (
                f"[FB] El FACEBOOK_PAGE_ACCESS_TOKEN es de la pagina {pagina_del_token} "
                f"pero FACEBOOK_PAGE_ID dice {page_id}."
            )
            if not user_access_token:
                raise RuntimeError(
                    aviso + "\n     No hay FACEBOOK_USER_ACCESS_TOKEN para derivar uno "
                    "correcto. Emiti un page token de la pagina destino y actualiza "
                    ".env (y .env.txt, que es el que viaja al VPS)."
                )
            print(aviso + " Se ignora y se intenta derivar uno desde el user token...")
            page_access_token = ""
        # Sin user token no hay plan B: se usa tal cual, como siempre.
        elif not user_access_token:
            return page_access_token, page_id
        elif estado != "dead":
            return page_access_token, page_id
        print(
            "[FB] FACEBOOK_PAGE_ACCESS_TOKEN rechazado por Facebook (vencido); "
            "intentando derivar uno nuevo desde FACEBOOK_USER_ACCESS_TOKEN..."
        )
        page_access_token = ""

    if not user_access_token:
        raise RuntimeError(
            "Facebook auth not configured. Set FACEBOOK_PAGE_ACCESS_TOKEN or "
            "FACEBOOK_USER_ACCESS_TOKEN + FACEBOOK_PAGE_ID in .env."
        )

    if page_id:
        data = _request_json(
            "GET",
            _graph_api_url(page_id, api_version=api_version),
            params={
                "fields": "id,name,access_token",
                "access_token": user_access_token,
            },
        )
        token = str(data.get("access_token") or "").strip()
        if not token:
            # Facebook responde 200 pero SIN access_token cuando la pagina no
            # cuelga de un rol personal del usuario (tipico de Business Manager).
            raise RuntimeError(_page_token_help(page_id, user_access_token, api_version))
        return token, str(data.get("id") or page_id)

    data = _request_json(
        "GET",
        _graph_api_url("me/accounts", api_version=api_version),
        params={
            "fields": "id,name,access_token",
            "access_token": user_access_token,
        },
    )
    pages = data.get("data") or []
    if not pages:
        raise RuntimeError("The configured Facebook user token does not expose any manageable Pages.")
    if len(pages) > 1:
        raise RuntimeError(
            "Multiple Facebook Pages found. Set FACEBOOK_PAGE_ID in .env to choose which Page to use."
        )

    page = pages[0] or {}
    token = str(page.get("access_token") or "").strip()
    page_id = str(page.get("id") or "").strip() or None
    if not token:
        raise RuntimeError("Could not resolve a Facebook Page access token.")
    return token, page_id


def _get_page_identity(page_access_token: str, api_version: Optional[str] = None) -> dict:
    try:
        return _request_json(
            "GET",
            _graph_api_url("me", api_version=api_version),
            params={
                "fields": "id,name",
                "access_token": page_access_token,
            },
        )
    except Exception:
        page_id = _env("FACEBOOK_PAGE_ID")
        if not page_id:
            raise
        return _request_json(
            "GET",
            _graph_api_url(page_id, api_version=api_version),
            params={
                "fields": "id,name",
                "access_token": page_access_token,
            },
        )


def _start_reel_upload(page_id: str, page_access_token: str, api_version: Optional[str] = None) -> dict:
    return _request_json(
        "POST",
        _graph_api_url(f"{page_id}/video_reels", api_version=api_version),
        params={
            "access_token": page_access_token,
            "upload_phase": "start",
        },
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def _upload_local_reel(upload_url: str, page_access_token: str, video_path: str, on_progress=None) -> dict:
    file_size = os.path.getsize(video_path)
    if on_progress:
        on_progress(0, file_size)

    with open(video_path, "rb") as handle:
        body = _ProgressReader(handle, file_size, on_progress) if on_progress else handle
        response = requests.post(
            upload_url,
            timeout=max(REQUEST_TIMEOUT, 300),
            headers={
                "Authorization": f"OAuth {page_access_token}",
                "offset": "0",
                "file_size": str(file_size),
                "Content-Type": "application/octet-stream",
                "User-Agent": "VideoOptimizerPro/1.0",
            },
            data=body,
        )
    response.raise_for_status()
    if on_progress:
        on_progress(file_size, file_size)
    return response.json() if response.text.strip() else {"success": True}


def get_reel_status(video_id: str, api_version: Optional[str] = None,
                    page_access_token: Optional[str] = None) -> dict:
    token = page_access_token or _resolve_page_access_token(api_version)[0]
    return _request_json(
        "GET",
        _graph_api_url(str(video_id), api_version=api_version),
        params={
            "fields": "status",
            "access_token": token,
        },
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def _wait_for_reel_ready(video_id: str, page_access_token: str, api_version: Optional[str] = None,
                         timeout_seconds: int = POLL_TIMEOUT_SECONDS) -> dict:
    inicio = time.time()
    deadline = inicio + max(5, int(timeout_seconds))
    last_state = {}
    ultimo_error = None
    hubo_respuesta = False

    while time.time() < deadline:
        try:
            last_state = get_reel_status(
                video_id=video_id,
                api_version=api_version,
                page_access_token=page_access_token,
            )
        except Exception as exc:
            # Este poll corre DESPUES de que el reel ya se publico. Justo despues
            # de publicar, Facebook devuelve a veces error 100 ("Object with ID
            # ... does not exist") sobre el id que el mismo acaba de dar: es
            # consistencia eventual. Que eso reviente hacia que un video ya
            # publicado se reportara como fallo (2026-09-03, Caral).
            ultimo_error = exc
            if not hubo_respuesta and (time.time() - inicio) >= STATUS_ERROR_GRACE_SECONDS:
                # Nunca contesto: no tiene sentido seguir esperando.
                break
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        hubo_respuesta = True
        ultimo_error = None
        status = last_state.get("status", {}) or {}
        video_status = str(status.get("video_status") or "").strip().lower()
        processing_phase = status.get("processing_phase", {}) or {}
        publishing_phase = status.get("publishing_phase", {}) or {}
        publish_status = str(publishing_phase.get("publish_status") or "").strip().lower()

        if video_status in {"published", "ready", "complete", "completed", "finished"}:
            return last_state
        if str(publishing_phase.get("status") or "").strip().lower() == "complete":
            return last_state
        if publish_status in {"published", "scheduled"}:
            return last_state
        if (
            str(processing_phase.get("status") or "").strip().lower() == "complete"
            and not publishing_phase
        ):
            return last_state

        time.sleep(POLL_INTERVAL_SECONDS)

    if ultimo_error is not None and not last_state:
        # No se pudo confirmar, pero el reel YA esta publicado: se avisa y se
        # sigue, en vez de convertir una publicacion exitosa en un error.
        print(
            f"   [WARN] No se pudo verificar el estado del reel {video_id} "
            f"({type(ultimo_error).__name__}: {str(ultimo_error)[:160]}).\n"
            f"          El video ya fue publicado; revisalo en Meta Business Suite."
        )
        return {"status_check_failed": str(ultimo_error)[:300]}

    return last_state


def _finish_reel_upload(page_id: str, video_id: str, page_access_token: str, title: str = "",
                        description: str = "", video_state: str = "PUBLISHED",
                        scheduled_publish_time: Optional[str | int | float] = None,
                        api_version: Optional[str] = None) -> dict:
    normalized_state = _normalize_video_state(video_state, scheduled_publish_time=scheduled_publish_time)
    params = {
        "access_token": page_access_token,
        "video_id": video_id,
        "upload_phase": "finish",
        "video_state": normalized_state,
    }
    normalized_schedule = _normalize_scheduled_publish_time(scheduled_publish_time)
    if normalized_schedule is not None:
        params["scheduled_publish_time"] = normalized_schedule
    clean_title = _clean_text(title, 255)
    clean_description = _clean_text(description, 2200)
    if clean_title:
        params["title"] = clean_title
    if clean_description:
        params["description"] = clean_description

    return _request_json(
        "POST",
        _graph_api_url(f"{page_id}/video_reels", api_version=api_version),
        params=params,
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def save_upload_result(result_path: str, upload_result: dict, title: str = "",
                       description: str = "", video_state: str = "PUBLISHED",
                       scheduled_publish_time: Optional[str | int | float] = None) -> dict:
    result_file = Path(result_path)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    normalized_state = _normalize_video_state(video_state, scheduled_publish_time=scheduled_publish_time)
    publish_at = _timestamp_to_iso_utc(scheduled_publish_time)

    save_data = {
        "video_id": upload_result.get("video_id"),
        "url": upload_result.get("url"),
        "permalink_url": upload_result.get("permalink_url"),
        "status": upload_result.get("status"),
        "video_state": normalized_state,
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "page_id": upload_result.get("page_id"),
        "page_name": upload_result.get("page_name"),
        "title": _clean_text(title, 255),
        "description": _clean_text(description, 2200),
        "scheduled": normalized_state == "SCHEDULED",
        "publish_at": publish_at,
    }
    _write_json(result_file, save_data)
    _archive_upload_result(result_file, save_data)
    return save_data


def upload_video(video_path: str, title: str, description: str = "",
                 video_state: str = "PUBLISHED", on_progress=None,
                 scheduled_publish_time: Optional[str | int | float] = None,
                 api_version: Optional[str] = None) -> dict:
    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video not found: {video_file}")

    page_access_token, page_id = _resolve_page_access_token(api_version=api_version)
    page_info = _get_page_identity(page_access_token, api_version=api_version)
    final_page_id = str(page_info.get("id") or page_id).strip()

    start_data = _start_reel_upload(final_page_id, page_access_token, api_version=api_version)
    video_id = str(start_data.get("video_id") or "").strip()
    upload_url = str(start_data.get("upload_url") or "").strip() or _rupload_url(video_id, api_version=api_version)
    if not video_id:
        raise RuntimeError(f"Facebook did not return a reel video_id: {start_data}")

    upload_response = _upload_local_reel(
        upload_url=upload_url,
        page_access_token=page_access_token,
        video_path=str(video_file),
        on_progress=on_progress,
    )
    if not upload_response.get("success", True):
        raise RuntimeError(f"Facebook upload failed: {upload_response}")

    publish_response = _finish_reel_upload(
        page_id=final_page_id,
        video_id=video_id,
        page_access_token=page_access_token,
        title=title,
        description=description,
        video_state=video_state,
        scheduled_publish_time=scheduled_publish_time,
        api_version=api_version,
    )
    if not publish_response.get("success", True):
        raise RuntimeError(f"Facebook publish failed: {publish_response}")

    latest_state = _wait_for_reel_ready(
        video_id=video_id,
        page_access_token=page_access_token,
        api_version=api_version,
    )
    status_payload = latest_state.get("status", {}) or {}
    publishing_phase = status_payload.get("publishing_phase", {}) or {}
    status = (
        str(publishing_phase.get("publish_status") or "").strip().lower()
        or str(status_payload.get("video_status") or "").strip().lower()
        or _normalize_video_state(video_state, scheduled_publish_time=scheduled_publish_time).lower()
    )
    final_state = _normalize_video_state(video_state, scheduled_publish_time=scheduled_publish_time)
    permalink_url = _normalize_permalink(latest_state.get("permalink_url"), video_id=video_id)

    result = {
        "video_id": video_id,
        "url": permalink_url if final_state == "PUBLISHED" else None,
        "permalink_url": permalink_url,
        "status": status,
        "video_state": final_state,
        "page_id": final_page_id or None,
        "page_name": str(page_info.get("name") or "").strip() or None,
        "response": publish_response,
        "status_response": latest_state,
    }
    return result


# ---------------------------------------------------------------------------
# Long-form video post upload (/{page-id}/videos — NOT Reels)
# Uses the Facebook 3-phase chunked upload protocol:
#   Phase 1 (start)    → graph.facebook.com
#   Phase 2 (transfer) → graph-video.facebook.com  (binary chunks)
#   Phase 3 (finish)   → graph.facebook.com
# ---------------------------------------------------------------------------

GRAPH_VIDEO_API_BASE = "https://graph-video.facebook.com"
GRAPH_VIDEO_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB per chunk


def _graph_video_api_url(path: str, api_version: Optional[str] = None) -> str:
    version = str(api_version or _default_api_version()).strip()
    return f"{GRAPH_VIDEO_API_BASE}/{version}/{str(path or '').lstrip('/')}"


def _start_video_post_upload(page_id: str, page_access_token: str, file_size: int,
                              api_version: Optional[str] = None) -> dict:
    return _request_json(
        "POST",
        _graph_api_url(f"{page_id}/videos", api_version=api_version),
        data={
            "upload_phase": "start",
            "file_size": str(file_size),
            "access_token": page_access_token,
        },
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def _transfer_video_post_chunk(page_id: str, upload_session_id: str, page_access_token: str,
                                chunk_data: bytes, start_offset: int,
                                api_version: Optional[str] = None) -> dict:
    return _request_json(
        "POST",
        _graph_video_api_url(f"{page_id}/videos", api_version=api_version),
        data={
            "upload_phase": "transfer",
            "start_offset": str(start_offset),
            "upload_session_id": upload_session_id,
            "access_token": page_access_token,
        },
        files={"video_file_chunk": ("chunk", chunk_data, "application/octet-stream")},
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
        timeout=max(REQUEST_TIMEOUT, 600),
    )


def _finish_video_post_upload(page_id: str, video_id: str, upload_session_id: str, page_access_token: str,
                                title: str = "", description: str = "", published: bool = True,
                                scheduled_publish_time: Optional[str | int | float] = None,
                                api_version: Optional[str] = None) -> dict:
    normalized_schedule = _normalize_scheduled_publish_time(scheduled_publish_time)
    params = {
        "upload_phase": "finish",
        "video_id": video_id,
        "upload_session_id": upload_session_id,
        "access_token": page_access_token,
    }
    clean_title = _clean_text(title, 255)
    clean_desc = _clean_text(description, 2200)
    if clean_title:
        params["title"] = clean_title
    if clean_desc:
        params["description"] = clean_desc
    if normalized_schedule:
        params["published"] = "false"
        params["scheduled_publish_time"] = str(normalized_schedule)
    else:
        params["published"] = "true" if published else "false"
    return _request_json(
        "POST",
        _graph_api_url(f"{page_id}/videos", api_version=api_version),
        data=params,
        headers={"User-Agent": "VideoOptimizerPro/1.0"},
    )


def upload_video_post(video_path: str, title: str, description: str = "",
                      video_state: str = "PUBLISHED", on_progress=None,
                      scheduled_publish_time: Optional[str | int | float] = None,
                      api_version: Optional[str] = None) -> dict:
    """Upload a long-form video as a regular Facebook Page video post (not a Reel)."""
    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video not found: {video_file}")

    file_size = os.path.getsize(video_path)
    page_access_token, page_id = _resolve_page_access_token(api_version=api_version)
    page_info = _get_page_identity(page_access_token, api_version=api_version)
    final_page_id = str(page_info.get("id") or page_id).strip()

    if on_progress:
        on_progress(0, file_size)

    # Phase 1: start
    start_data = _start_video_post_upload(final_page_id, page_access_token, file_size, api_version=api_version)
    video_id = str(start_data.get("video_id") or "").strip()
    upload_session_id = str(start_data.get("upload_session_id") or video_id).strip()
    if not video_id:
        raise RuntimeError(f"Facebook did not return a video_id: {start_data}")
    start_offset = int(start_data.get("start_offset", 0))
    end_offset = int(start_data.get("end_offset", min(GRAPH_VIDEO_CHUNK_SIZE, file_size)))

    # Phase 2: transfer in chunks
    with open(video_path, "rb") as fh:
        while start_offset < file_size:
            chunk_size = max(1, end_offset - start_offset)
            fh.seek(start_offset)
            chunk_data = fh.read(chunk_size)
            if not chunk_data:
                break
            transfer_data = _transfer_video_post_chunk(
                final_page_id, upload_session_id, page_access_token,
                chunk_data, start_offset, api_version=api_version,
            )
            new_start = int(transfer_data.get("start_offset", end_offset))
            new_end = int(transfer_data.get("end_offset", min(new_start + GRAPH_VIDEO_CHUNK_SIZE, file_size)))
            start_offset = new_start
            end_offset = new_end
            if on_progress:
                on_progress(min(start_offset, file_size), file_size)

    if on_progress:
        on_progress(file_size, file_size)

    # Phase 3: finish
    published = (video_state.upper() == "PUBLISHED")
    finish_data = _finish_video_post_upload(
        final_page_id, video_id, upload_session_id, page_access_token,
        title=title, description=description, published=published,
        scheduled_publish_time=scheduled_publish_time,
        api_version=api_version,
    )

    final_state = _normalize_video_state(video_state, scheduled_publish_time=scheduled_publish_time)
    permalink_url = f"https://www.facebook.com/video/{video_id}"

    return {
        "video_id": video_id,
        "url": permalink_url if final_state == "PUBLISHED" else None,
        "permalink_url": permalink_url,
        "status": final_state.lower(),
        "video_state": final_state,
        "page_id": final_page_id or None,
        "page_name": str(page_info.get("name") or "").strip() or None,
        "response": finish_data,
    }


def upload_from_metadata(output_dir: str, video_state: str = "PUBLISHED", on_progress=None,
                         scheduled_publish_time: Optional[str | int | float] = None,
                         upload_type: str = "reel") -> dict:
    """Upload a video to Facebook from a directory containing a video file and metadata JSON.

    upload_type: 'reel' (default, short vertical video) or 'video' (long-form page video post).
    """
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

    uploader = upload_video_post if upload_type == "video" else upload_video
    result = uploader(
        video_path=str(video_path),
        title=title,
        description=description,
        video_state=video_state,
        on_progress=on_progress,
        scheduled_publish_time=scheduled_publish_time,
    )
    save_upload_result(
        result_path=output_dir / "facebook_upload_result.json",
        upload_result=result,
        title=title,
        description=description,
        video_state=video_state,
        scheduled_publish_time=scheduled_publish_time,
    )
    return result


def check_auth() -> dict:
    try:
        page_access_token, page_id = _resolve_page_access_token()
        page_info = _get_page_identity(page_access_token)
        return {
            "authenticated": True,
            "page_id": str(page_info.get("id") or page_id or "").strip() or None,
            "page_name": str(page_info.get("name") or "").strip() or None,
            "error": None,
        }
    except Exception as e:
        return {
            "authenticated": False,
            "page_id": None,
            "page_name": None,
            "error": str(e),
        }
