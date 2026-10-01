# -*- coding: utf-8 -*-
"""Mandar un video a la bandeja de TikTok como borrador (Content Posting API, modo Upload).

Por que borrador y no publicacion directa (2026-09-26): publicar en publico por API
exige que TikTok audite la app, y sus reglas rechazan las herramientas para subir a
las cuentas propias. Sin auditoria, la publicacion directa sale "Solo yo" y encima
pide la cuenta en privado. El modo Upload no tiene esa traba: el video llega como
borrador a la bandeja (notificacion en el celular) y el usuario lo termina en la app.
Funciona con la app en sandbox y la cuenta del canal agregada como usuario de prueba.

El borrador NO lleva texto: el endpoint acepta solo el archivo (titulo y descripcion
en borradores existen solo para fotos). Por eso el titulo y la descripcion van por
Telegram (telegram_notify), listos para copiar y pegar.

Flujo (verificado contra developers.tiktok.com el 2026-09-26):

    Login Kit de escritorio: https://www.tiktok.com/v2/auth/authorize/ con PKCE S256.
        OJO: el code_challenge es el SHA256 del verifier en HEX, no en base64url como
        en Google. Vuelve a http://127.0.0.1:<puerto>/callback/ (en el portal se
        registra http://127.0.0.1:*/callback/).
    POST https://open.tiktokapis.com/v2/oauth/token/    -> access (24 h) + refresh (365 dias)
    POST /v2/post/publish/inbox/video/init/   {source_info: FILE_UPLOAD, video_size,
                                               chunk_size, total_chunk_count} -> publish_id, upload_url
    PUT  upload_url por trozos (Content-Range)          -> 206 ... 201
    POST /v2/post/publish/status/fetch/ {publish_id}    -> SEND_TO_USER_INBOX

Limites: 5 borradores sin publicar por 24 h, 6 inicios por minuto por token, video
de 3 s a 10 min, 23 a 60 fps, 360 a 4096 px por lado, hasta 4 GB, MP4/H.264 recomendado.

Configuracion en `.env` (el local): TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET (las del
sandbox) y, opcional, TIKTOK_REDIRECT_PORT (8723). El token queda en
token_tiktok.json (gitignored por `token_*.json`).

    .venv\\Scripts\\python.exe tiktok_uploader.py --setup     # ingresar credenciales y conectar
    .venv\\Scripts\\python.exe tiktok_uploader.py --auth      # conectar con las credenciales guardadas
    .venv\\Scripts\\python.exe tiktok_uploader.py --check     # cuenta, token y Telegram
    .venv\\Scripts\\python.exe tiktok_uploader.py --upload CARPETA_O_MP4

Ver `test_tiktok_uploader.py`.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import shutil
import string
import subprocess
import tempfile
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from infra.env_loader import load_project_env

ROOT = Path(__file__).resolve().parent
load_project_env(ROOT)

TOKEN_PATH = ROOT / "token_tiktok.json"

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API = "https://open.tiktokapis.com/v2"
# video.list (producto Display API): los videos publicos de la cuenta, para saber que
# shorts ya estan en TikTok. Los borradores dependen solo de video.upload.
SCOPES = ("user.info.basic", "video.upload", "video.list")
DEFAULT_REDIRECT_PORT = 8723
REDIRECT_PATH = "/callback/"
AUTH_TIMEOUT_S = 300
TOKEN_MARGIN_S = 300            # se renueva 5 min antes de que venza

MB = 1024 * 1024
MIN_CHUNK = 5 * MB
MAX_CHUNK = 64 * MB
# Un short de 30 MB va en 3 trozos: el panel ve el avance en vez de un salto de 0 a 100.
CHUNK_SIZE = 10 * MB
CHUNK_RETRIES = 3
MAX_VIDEO_BYTES = 4 * 1024 * MB

MIN_DURATION_S, MAX_DURATION_S = 3, 600
MIN_FPS, MAX_FPS = 23, 60
MIN_SIDE, MAX_SIDE = 360, 4096

STATUS_TIMEOUT_S = 180
STATUS_POLL_S = 5               # la consulta de estado admite 30 por minuto

DESCRIPTION_LIMIT = 2200
TIKTOK_METADATA_FILES = ("tiktok_metadata.json", "instagram_metadata.json", "metadata.json")
_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
INBOX_STATES = ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE")


class TikTokError(RuntimeError):
    pass


class TikTokAuthError(TikTokError):
    pass


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name) or default).strip()


def _status(on_status: Optional[Callable[[str], None]], message: str) -> None:
    if not message:
        return
    if on_status:
        try:
            on_status(message)
        except Exception:
            pass
    else:
        print(f"[TikTok] {message}")


# ================================================================ login (PKCE)

_VERIFIER_CHARS = string.ascii_letters + string.digits + "-._~"


def make_code_verifier(length: int = 64) -> str:
    if not 43 <= length <= 128:
        raise ValueError("el code_verifier va de 43 a 128 caracteres")
    return "".join(secrets.choice(_VERIFIER_CHARS) for _ in range(length))


def code_challenge(verifier: str) -> str:
    """SHA256 en HEX: lo que pide TikTok en escritorio. Con base64url (lo de Google) el
    login vuelve con error de code_verifier; es la trampa tipica del primer intento."""
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


def _redirect_port() -> int:
    try:
        return int(_env("TIKTOK_REDIRECT_PORT") or DEFAULT_REDIRECT_PORT)
    except ValueError:
        return DEFAULT_REDIRECT_PORT


def redirect_uri(port: Optional[int] = None) -> str:
    return f"http://127.0.0.1:{int(port or _redirect_port())}{REDIRECT_PATH}"


def build_authorize_url(client_key: str, redirect: str, state: str, challenge: str,
                        scopes=SCOPES) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_key": client_key,
        "scope": ",".join(scopes),
        "response_type": "code",
        "redirect_uri": redirect,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def parse_callback(path: str, expected_state: str) -> str:
    """El `code` de la vuelta del login; TikTokAuthError si vino un error o el state no coincide."""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)

    def get(key: str) -> str:
        return (query.get(key) or [""])[0]

    if get("error"):
        detalle = get("error_description") or "sin detalle"
        extra = " (cancelaste la autorización)" if get("error") == "access_denied" else ""
        raise TikTokAuthError(f"TikTok no autorizó la app: {get('error')}{extra}. {detalle}")
    if get("state") != expected_state:
        raise TikTokAuthError("La vuelta del login no corresponde a este pedido (state distinto): "
                              "reintentá tiktok_uploader.py --auth.")
    code = get("code")
    if not code:
        raise TikTokAuthError("TikTok volvió sin código de autorización.")
    return code


class _CallbackServer:
    """Servidor de un solo uso en 127.0.0.1 que espera la vuelta del login."""

    def __init__(self, port: int, expected_state: str):
        box: Dict[str, Any] = {}
        self.box = box

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (nombre que exige http.server)
                if not self.path.startswith(REDIRECT_PATH):
                    self.send_response(404)
                    self.end_headers()
                    return
                try:
                    box["code"] = parse_callback(self.path, expected_state)
                    titulo, texto, codigo = ("Autorización recibida", "Vuelve a la app para comprobar "
                                             "si la conexión se completó. Ya puedes cerrar esta pestaña.", 200)
                except TikTokAuthError as exc:
                    box["error"] = exc
                    titulo, texto, codigo = "No se pudo conectar", str(exc), 400
                cuerpo = ("<!doctype html><meta charset='utf-8'><title>TikTok</title>"
                          "<body style='font-family:sans-serif;padding:2em'>"
                          f"<h2>{html.escape(titulo)}</h2><p>{html.escape(texto)}</p></body>").encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *args):  # sin ruido en la consola
                pass

        try:
            self.server = HTTPServer(("127.0.0.1", port), Handler)
        except OSError as exc:
            raise TikTokAuthError(f"El puerto {port} está ocupado ({exc}): cambialo con "
                                  "TIKTOK_REDIRECT_PORT en .env.") from None
        self.server.timeout = 1

    def wait(self, timeout_s: int) -> str:
        limite = time.monotonic() + timeout_s
        while time.monotonic() < limite and not self.box:
            self.server.handle_request()
        if "error" in self.box:
            raise self.box["error"]
        if "code" not in self.box:
            raise TikTokAuthError(
                f"No llegó la autorización en {max(1, timeout_s // 60)} min. Revisá: (1) que entraste con "
                "la cuenta agregada como usuario de prueba del sandbox; (2) que en Login Kit (Desktop) "
                "está registrada http://127.0.0.1:*/callback/ ; (3) que TIKTOK_CLIENT_KEY es la del sandbox.")
        return self.box["code"]

    def close(self) -> None:
        self.server.server_close()


def _client_credentials() -> Tuple[str, str]:
    key, secret = _env("TIKTOK_CLIENT_KEY"), _env("TIKTOK_CLIENT_SECRET")
    if not key or not secret:
        raise TikTokAuthError("Faltan TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET en .env "
                              "(developers.tiktok.com > tu app > Sandbox > credenciales).")
    return key, secret


def setup_credentials(*, path: Optional[Path] = None, input_fn=None, secret_fn=None,
                      on_status=None) -> None:
    """Console setup: collect both values before saving; never print credentials."""
    from getpass import getpass
    from dotenv import dotenv_values, set_key

    path = Path(path or ROOT / ".env")
    input_fn, secret_fn = input_fn or input, secret_fn or getpass
    _status(on_status, "Copia Client key y Client secret del mismo Sandbox de TikTok for Developers.")
    try:
        key = input_fn("TIKTOK_CLIENT_KEY: ").strip()
        secret = secret_fn("TIKTOK_CLIENT_SECRET (oculto): ").strip()
    except (EOFError, KeyboardInterrupt):
        raise TikTokAuthError("Configuración cancelada. No se guardaron cambios.") from None
    if not key or not secret:
        raise TikTokAuthError("Falta una credencial. No se guardaron cambios.")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key + secret):
        raise TikTokAuthError("Las credenciales contienen espacios o caracteres de control. Copia los valores otra vez.")
    if set(secret) <= set("*•●"):
        raise TikTokAuthError("Se copió la máscara del secreto. Usa el botón de copiar de Client secret.")

    values = {"TIKTOK_CLIENT_KEY": key, "TIKTOK_CLIENT_SECRET": secret}
    tmp = None
    try:
        before = dotenv_values(path, encoding="utf-8-sig", interpolate=False) if path.exists() else {}
        changes = [name for name, value in values.items() if value != before.get(name)]
        # Stage both changes together. The temporary filename is also gitignored.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".env.tiktok-",
                                         suffix=".tmp", dir=path.parent, delete=False) as handle:
            tmp = Path(handle.name)
            if path.exists():
                handle.write(path.read_text(encoding="utf-8-sig"))
        for name, value in values.items():
            set_key(str(tmp), name, value, encoding="utf-8")
        parsed = dotenv_values(tmp, encoding="utf-8")
        if any(parsed.get(name) != value for name, value in values.items()):
            raise TikTokAuthError("No se pudieron guardar las credenciales sin alterarlas. No se guardaron cambios.")
        os.replace(tmp, path)
    except (OSError, UnicodeError):
        raise TikTokAuthError("No se pudo actualizar .env. Revisa los permisos del archivo.") from None
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    # The just-entered pair must also replace stale inherited environment values.
    os.environ.update(values)
    if changes:
        _status(on_status, "Credenciales guardadas en .env. Actualizadas: " + ", ".join(changes) + ".")
    else:
        _status(on_status, "Los dos valores coinciden con los que ya estaban guardados en .env.")


# ================================================================ token

def _safe_oauth_detail(value: Any, request_data: Dict[str, str], payload=None) -> str:
    """OAuth diagnostics must not echo keys, codes, verifiers or tokens."""
    text = str(value or "")
    sensitive = {"client_key", "client_secret", "code", "code_verifier", "refresh_token", "access_token", "open_id"}
    secrets_to_hide = set()
    for source in (request_data, payload or {}):
        for name in sensitive:
            secret = source.get(name)
            if isinstance(secret, str) and secret:
                secrets_to_hide.update((secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)))
    for secret in sorted(secrets_to_hide, key=len, reverse=True):
        text = text.replace(secret, "[oculto]")
    return " ".join(text.split())[:500]


def _token_error_help(error: str, description: str, log_id: str = "") -> str:
    if error == "invalid_client":
        message = ("TikTok rechazó las credenciales de la app (invalid_client) al solicitar el token. "
                   "Para ingresar de nuevo Client key y Client secret: "
                   ".venv\\Scripts\\python.exe tiktok_uploader.py --setup. "
                   "Si usas Sandbox, ambos valores deben ser los vigentes de ese mismo Sandbox.")
    elif error == "invalid_grant":
        message = ("TikTok rechazó el código o permiso (invalid_grant): puede haber vencido, sido revocado "
                   "o no coincidir con la app o su redirect_uri. Corré "
                   ".venv\\Scripts\\python.exe tiktok_uploader.py --auth.")
    else:
        message = f"TikTok no dio el token ({error})."
    if description:
        message += f" Detalle de TikTok: {description}"
    if log_id:
        message += f" [log_id {log_id}]"
    return message


def _token_from_payload(payload: Dict[str, Any], *, client_key: str = "", now: Optional[float] = None,
                        previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    now = int(time.time() if now is None else now)
    previous = previous or {}
    return {
        "access_token": payload["access_token"],
        # Al renovar, TikTok puede devolver otro refresh_token: vale el nuevo.
        "refresh_token": payload.get("refresh_token") or previous.get("refresh_token"),
        "open_id": payload.get("open_id") or previous.get("open_id"),
        "scope": payload.get("scope") or previous.get("scope") or "",
        "token_type": payload.get("token_type") or "Bearer",
        "expires_at": now + int(payload.get("expires_in") or 86400),
        "refresh_expires_at": now + int(payload.get("refresh_expires_in") or 31536000),
        "obtained_at": now,
        "client_key": client_key or previous.get("client_key") or "",
    }


def _token_request(data: Dict[str, str], *, http=None, client_key: str = "",
                   previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    http = http or requests
    try:
        resp = http.post(TOKEN_URL, data=data, timeout=60, headers={
            "Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"})
    except requests.RequestException as exc:
        raise TikTokAuthError("No se pudo conectar con TikTok para el token: " +
                              _safe_oauth_detail(exc, data)) from None
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if resp.status_code >= 400 or payload.get("error") or not payload.get("access_token"):
        raise TikTokAuthError(_token_error_help(
            _safe_oauth_detail(payload.get("error") or f"HTTP {resp.status_code}", data, payload),
            _safe_oauth_detail(payload.get("error_description") or "Respuesta sin token de acceso.", data, payload),
            _safe_oauth_detail(payload.get("log_id"), data, payload)))
    return _token_from_payload(payload, client_key=client_key, previous=previous)


def exchange_code(code: str, verifier: str, redirect: str, client_key: str, client_secret: str,
                  http=None) -> Dict[str, Any]:
    return _token_request({
        "client_key": client_key, "client_secret": client_secret, "code": code,
        "grant_type": "authorization_code", "redirect_uri": redirect, "code_verifier": verifier,
    }, http=http, client_key=client_key)


def refresh_access_token(token: Dict[str, Any], client_key: str, client_secret: str,
                         http=None) -> Dict[str, Any]:
    return _token_request({
        "client_key": client_key, "client_secret": client_secret,
        "grant_type": "refresh_token", "refresh_token": str(token.get("refresh_token") or ""),
    }, http=http, client_key=client_key, previous=token)


def load_token(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = Path(path or TOKEN_PATH)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_token(token: Dict[str, Any], path: Optional[Path] = None) -> None:
    path = Path(path or TOKEN_PATH)
    # El temporal tambien cae en `token_*.json` del .gitignore: si algo corta entre
    # escribir y renombrar, el secreto no queda a tiro de un `git add`.
    tmp = path.with_name(f"{path.stem}_tmp{path.suffix}")
    tmp.write_text(json.dumps(token, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def token_state(token: Optional[Dict[str, Any]], client_key: str = "", now: Optional[float] = None,
                margin: int = TOKEN_MARGIN_S) -> str:
    """'valid' (sirve tal cual), 'refresh' (se renueva solo) o 'login' (hay que volver a conectar)."""
    if not token or not token.get("access_token"):
        return "login"
    if client_key and token.get("client_key") and token["client_key"] != client_key:
        return "login"          # token de otra app (p. ej. sandbox vs produccion)
    scopes = {s.strip() for s in str(token.get("scope") or "").split(",") if s.strip()}
    if scopes and "video.upload" not in scopes:
        return "login"
    now = time.time() if now is None else now
    if float(token.get("expires_at") or 0) - margin > now:
        return "valid"
    if token.get("refresh_token") and float(token.get("refresh_expires_at") or 0) - margin > now:
        return "refresh"
    return "login"


def authorize(*, open_browser: bool = True, timeout_s: int = AUTH_TIMEOUT_S, on_status=None,
              http=None) -> Dict[str, Any]:
    """Login de escritorio: abre el navegador, espera la vuelta en 127.0.0.1 y guarda el token."""
    client_key, client_secret = _client_credentials()
    port = _redirect_port()
    redirect = redirect_uri(port)
    verifier = make_code_verifier()
    state = secrets.token_urlsafe(24)
    url = build_authorize_url(client_key, redirect, state, code_challenge(verifier))
    server = _CallbackServer(port, state)          # escuchando ANTES de abrir el navegador
    try:
        _status(on_status, "se abre el navegador para conectar TikTok: entrá con la cuenta del canal "
                           "y autorizá la app")
        if not open_browser or not webbrowser.open(url):
            _status(on_status, f"abrí esta dirección en el navegador: {url}")
        code = server.wait(timeout_s)
    finally:
        server.close()
    _status(on_status, "autorización recibida del navegador; solicitando el token a TikTok...")
    token = exchange_code(code, verifier, redirect, client_key, client_secret, http=http)
    save_token(token)
    _status(on_status, f"cuenta conectada; permiso guardado en {TOKEN_PATH.name}")
    return token


def get_access_token(*, interactive: bool = True, on_status=None, http=None) -> Dict[str, Any]:
    """El token listo para usar: tal cual, renovado solo o, si hace falta, con login."""
    client_key, client_secret = _client_credentials()
    token = load_token()
    estado = token_state(token, client_key)
    if estado == "valid":
        return token
    if estado == "refresh":
        try:
            token = refresh_access_token(token, client_key, client_secret, http=http)
            save_token(token)
            return token
        except TikTokAuthError as exc:
            _status(on_status, f"no se pudo renovar el permiso ({exc}); hay que volver a conectar la cuenta")
    if not interactive:
        raise TikTokAuthError("La cuenta de TikTok no está conectada o el permiso venció. Corré: "
                              ".venv\\Scripts\\python.exe tiktok_uploader.py --auth")
    return authorize(on_status=on_status, http=http)


# ================================================================ API

_API_ERROR_HELP = {
    "access_token_invalid": "el permiso de la cuenta venció o fue revocado: corré "
                            ".venv\\Scripts\\python.exe tiktok_uploader.py --auth",
    "scope_not_authorized": "la cuenta no autorizó video.upload: revisá que el sandbox tenga el producto "
                            "Content Posting API y corré tiktok_uploader.py --auth de nuevo",
    "scope_permission_missed": "la cuenta no autorizó video.upload: revisá que el sandbox tenga el producto "
                               "Content Posting API y corré tiktok_uploader.py --auth de nuevo",
    "spam_risk_too_many_pending_share": "ya hay 5 borradores sin publicar en las últimas 24 h (el tope de "
                                        "TikTok): publicá o borrá alguno de la bandeja y reintentá",
    "spam_risk_user_banned_from_posting": "TikTok tiene a la cuenta bloqueada para publicar",
    "rate_limit_exceeded": "demasiados pedidos seguidos (TikTok permite 6 por minuto): esperá un minuto "
                           "y reintentá",
    "invalid_param": "TikTok rechazó un dato del pedido",
}


def explain_api_error(code: str, message: str = "", paso: str = "", log_id: Optional[str] = None) -> str:
    ayuda = _API_ERROR_HELP.get(code)
    base = f"TikTok falló en {paso or 'la API'} ({code})"
    texto = f"{base}: {ayuda}." if ayuda else f"{base}."
    if message:
        texto += f" Detalle: {message}"
    if log_id:
        texto += f" [log_id {log_id}]"
    return texto


def _api(method: str, path: str, token: Dict[str, Any], *, json_body: Optional[dict] = None,
         params: Optional[dict] = None, http=None, paso: str = "") -> Dict[str, Any]:
    http = http or requests
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
    try:
        resp = http.request(method, f"{API}{path}", headers=headers, json=json_body,
                            params=params, timeout=60)
    except requests.RequestException as exc:
        raise TikTokError(f"No se pudo conectar con TikTok en {paso}: {exc}") from None
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    error = payload.get("error") or {}
    code = str(error.get("code") or "").strip()
    if resp.status_code < 400 and code in ("", "ok"):
        return payload.get("data") or {}
    raise TikTokError(explain_api_error(code or f"http_{resp.status_code}",
                                        str(error.get("message") or (resp.text or "")[:300]),
                                        paso, error.get("log_id")))


def get_user_info(token: Dict[str, Any], http=None) -> Dict[str, Any]:
    data = _api("GET", "/user/info/", token, params={"fields": "open_id,union_id,avatar_url,display_name"},
                http=http, paso="los datos de la cuenta")
    return data.get("user") or {}


VIDEO_LIST_FIELDS = "id,create_time,title,video_description,duration,share_url,view_count"


def list_public_videos(token: Dict[str, Any], http=None, max_pages: int = 100) -> List[Dict[str, Any]]:
    """Los videos PUBLICOS de la cuenta, del mas nuevo al mas viejo (20 por pagina).
    Los privados y los borradores no aparecen: TikTok no los expone en esta API."""
    scopes = {s.strip() for s in str(token.get("scope") or "").split(",")}
    if "video.list" not in scopes:
        raise TikTokAuthError("El permiso guardado no incluye video.list: agregá el producto Display API al "
                              "sandbox y corré tiktok_uploader.py --auth de nuevo.")
    videos: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(max_pages):
        cuerpo: Dict[str, Any] = {"max_count": 20}
        if cursor:
            cuerpo["cursor"] = cursor
        data = _api("POST", "/video/list/", token, params={"fields": VIDEO_LIST_FIELDS}, json_body=cuerpo,
                    http=http, paso="la lista de videos")
        videos += data.get("videos") or []
        if not data.get("has_more") or not data.get("cursor"):
            break
        cursor = data["cursor"]
    return videos


# ================================================================ video

def plan_chunks(video_size: int, chunk_size: int = CHUNK_SIZE) -> Tuple[int, int]:
    """(chunk_size, total_chunk_count) con las reglas de TikTok.

    - Si no llega a DOS trozos, va entero: un solo trozo con chunk_size = video_size.
      Petra (2026-09-27, 20.885.618 bytes): 20,9 // 10,5 MiB = 1 y se declaro
      chunk_size 10 MiB con un unico trozo de 20,9 MB; TikTok contesto invalid_params
      "The chunk size is invalid". Con un trozo, TikTok exige que sea el archivo entero.
    - Si no, trozos de 5 a 64 MB; la cantidad es video_size // chunk_size (redondeo para
      abajo) y el ultimo trozo se lleva el resto (puede pasar de chunk_size, hasta 128 MB).
    """
    if video_size <= 0:
        raise ValueError("el video esta vacio")
    chunk = max(MIN_CHUNK, min(MAX_CHUNK, int(chunk_size)))
    if video_size // chunk < 2:
        if video_size <= MAX_CHUNK:
            return video_size, 1
        chunk = min(MAX_CHUNK, video_size // 2)     # no entra entero: dos trozos
    return chunk, video_size // chunk


def chunk_ranges(video_size: int, chunk_size: int, total_chunks: int) -> List[Tuple[int, int]]:
    """[(primer_byte, ultimo_byte)] de cada trozo, inclusivos, como en Content-Range."""
    rangos = []
    for i in range(total_chunks):
        primero = i * chunk_size
        ultimo = video_size - 1 if i == total_chunks - 1 else primero + chunk_size - 1
        rangos.append((primero, ultimo))
    return rangos


def _ffprobe_bin() -> Optional[str]:
    encontrado = shutil.which("ffprobe")
    if encontrado:
        return encontrado
    base = _env("FFMPEG_PATH")
    if base:
        carpeta = Path(base).parent if Path(base).is_file() else Path(base)
        candidato = carpeta / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if candidato.is_file():
            return str(candidato)
    try:
        from infra.video_config import VideoConfig
        candidato = getattr(VideoConfig, "FFPROBE_BINARY_PATH", None)
        if candidato and os.path.isfile(candidato):
            return candidato
    except Exception:
        pass
    return None


def _ratio(text: Any) -> Optional[float]:
    try:
        num, _, den = str(text or "").partition("/")
        valor = float(num) / float(den or 1)
        return valor if valor > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe_video(path) -> Optional[Dict[str, Any]]:
    """Duracion, fps y tamano con ffprobe; None si no hay ffprobe (no frena la subida)."""
    ffprobe = _ffprobe_bin()
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        datos = json.loads(proc.stdout or "{}") if proc.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not datos:
        return None
    stream = (datos.get("streams") or [{}])[0]
    try:
        duracion = float((datos.get("format") or {}).get("duration") or 0) or None
    except ValueError:
        duracion = None
    return {"duration": duracion, "width": stream.get("width"), "height": stream.get("height"),
            "fps": _ratio(stream.get("avg_frame_rate")) or _ratio(stream.get("r_frame_rate"))}


def check_video_limits(info: Optional[Dict[str, Any]], size: int) -> List[str]:
    """Lo que TikTok rechazaria, dicho antes de gastar un borrador (hay 5 por dia)."""
    problemas = []
    if size > MAX_VIDEO_BYTES:
        problemas.append(f"pesa {size / 1024 / MB:.1f} GB y TikTok acepta hasta 4 GB")
    if not info:
        return problemas
    duracion = info.get("duration")
    if duracion and duracion > MAX_DURATION_S + 0.5:
        problemas.append(f"dura {duracion / 60:.1f} min y por API TikTok acepta hasta 10 min")
    elif duracion and duracion < MIN_DURATION_S:
        problemas.append(f"dura {duracion:.1f} s y TikTok pide al menos 3 s")
    fps = info.get("fps")
    if fps and not MIN_FPS - 0.1 <= fps <= MAX_FPS + 0.1:
        problemas.append(f"tiene {fps:.2f} fps y TikTok pide entre 23 y 60")
    ancho, alto = info.get("width"), info.get("height")
    if ancho and alto and not all(MIN_SIDE <= int(lado) <= MAX_SIDE for lado in (ancho, alto)):
        problemas.append(f"mide {ancho}x{alto} y TikTok pide entre 360 y 4096 px por lado")
    return problemas


def _validate_video(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"No existe el video: {path}")
    mime = _MIME.get(path.suffix.lower())
    if not mime:
        raise TikTokError(f"TikTok acepta MP4, MOV o WebM; este archivo es {path.suffix or 'sin extension'}.")
    problemas = check_video_limits(probe_video(path), path.stat().st_size)
    if problemas:
        raise TikTokError("El video no entra en TikTok: " + "; ".join(problemas) + ".")
    return mime


def _put_chunks(upload_url: str, path: Path, size: int, chunk: int, total: int, mime: str,
                on_progress=None, http=None, sleep=None) -> None:
    http = http or requests
    sleep = sleep or time.sleep
    enviado = 0
    if on_progress:
        on_progress(0, size)
    with path.open("rb") as fh:
        for n, (primero, ultimo) in enumerate(chunk_ranges(size, chunk, total), start=1):
            fh.seek(primero)
            datos = fh.read(ultimo - primero + 1)
            headers = {"Content-Type": mime, "Content-Length": str(len(datos)),
                       "Content-Range": f"bytes {primero}-{ultimo}/{size}"}
            for intento in range(1, CHUNK_RETRIES + 1):
                try:
                    resp = http.put(upload_url, data=datos, headers=headers, timeout=(30, 600))
                except requests.RequestException as exc:
                    if intento == CHUNK_RETRIES:
                        raise TikTokError(f"Se cortó la subida del trozo {n}/{total}: {exc}") from None
                    sleep(2 * intento)
                    continue
                if resp.status_code in (200, 201, 206):
                    break
                if resp.status_code >= 500 and intento < CHUNK_RETRIES:
                    sleep(2 * intento)
                    continue
                raise TikTokError(f"TikTok rechazó el trozo {n}/{total} (HTTP {resp.status_code}): "
                                  f"{(resp.text or '')[:300]}")
            enviado += len(datos)
            if on_progress:
                on_progress(enviado, size)


_FAIL_REASONS = {
    "file_format_check_failed": "TikTok no acepta el formato del archivo (usá MP4 con H.264)",
    "duration_check_failed": "la duración no entra en lo que acepta la cuenta (de 3 s a 10 min)",
    "frame_rate_check_failed": "los cuadros por segundo tienen que estar entre 23 y 60",
    "picture_size_check_failed": "la resolución tiene que estar entre 360 y 4096 px por lado",
    "auth_removed": "la cuenta le quitó el permiso a la app: corré tiktok_uploader.py --auth",
    "spam_risk_too_many_posts": "la cuenta llegó al tope diario de publicaciones",
    "spam_risk_too_many_pending_share": "ya hay 5 borradores sin publicar en las últimas 24 h",
    "spam_risk_user_banned_from_posting": "TikTok tiene a la cuenta bloqueada para publicar",
    "internal": "error interno de TikTok: reintentá en unos minutos",
}


def explain_fail_reason(reason: Any) -> str:
    codigo = str(reason or "").strip() or "sin motivo"
    ayuda = _FAIL_REASONS.get(codigo)
    return f"TikTok no pudo procesar el video ({codigo})" + (f": {ayuda}." if ayuda else ".")


def fetch_status(token: Dict[str, Any], publish_id: str, http=None) -> Dict[str, Any]:
    return _api("POST", "/post/publish/status/fetch/", token, json_body={"publish_id": publish_id},
                http=http, paso="la consulta del estado")


def wait_for_inbox(token: Dict[str, Any], publish_id: str, *, http=None,
                   timeout_s: int = STATUS_TIMEOUT_S, poll_s: int = STATUS_POLL_S,
                   sleep=None, clock=None) -> Dict[str, Any]:
    """Espera SEND_TO_USER_INBOX. Si sigue procesando al vencer el plazo, devuelve el ultimo
    estado sin fallar: el borrador llega igual, solo que la notificacion tarda."""
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    limite = clock() + timeout_s
    while True:
        estado = fetch_status(token, publish_id, http=http)
        valor = str(estado.get("status") or "").upper()
        if valor in INBOX_STATES:
            return estado
        if valor == "FAILED":
            raise TikTokError(explain_fail_reason(estado.get("fail_reason")))
        if clock() >= limite:
            return estado
        sleep(poll_s)


def send_video_to_inbox(video_path, *, token: Optional[Dict[str, Any]] = None, on_progress=None,
                        on_status=None, http=None, sleep=None, validate: bool = True) -> Dict[str, Any]:
    """Sube el archivo como borrador. Devuelve {publish_id, tiktok_status, uploaded_bytes}."""
    path = Path(video_path)
    mime = _validate_video(path) if validate else _MIME.get(path.suffix.lower(), "video/mp4")
    token = token or get_access_token(on_status=on_status, http=http)
    size = path.stat().st_size
    chunk, total = plan_chunks(size)
    # Solo el archivo: el endpoint de la bandeja no acepta titulo ni descripcion.
    init = _api("POST", "/post/publish/inbox/video/init/", token, http=http, paso="el inicio de la subida",
                json_body={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                           "chunk_size": chunk, "total_chunk_count": total}})
    publish_id, upload_url = init.get("publish_id"), init.get("upload_url")
    if not publish_id or not upload_url:
        raise TikTokError(f"TikTok no devolvió publish_id/upload_url: {init}")
    _status(on_status, f"subiendo {size / 1_000_000:.1f} MB en {total} trozo(s)...")
    _put_chunks(upload_url, path, size, chunk, total, mime, on_progress=on_progress, http=http, sleep=sleep)
    _status(on_status, "archivo subido; esperando que TikTok lo mande a la bandeja...")
    estado = wait_for_inbox(token, publish_id, http=http, sleep=sleep)
    return {"publish_id": publish_id, "tiktok_status": estado.get("status"),
            "uploaded_bytes": estado.get("uploaded_bytes")}


# ================================================================ texto

def _seo_enabled() -> bool:
    return _env("TIKTOK_SEO", "1").lower() not in ("0", "false", "no", "off")


def _load_metadata(folder: Path) -> Dict[str, Any]:
    for nombre in TIKTOK_METADATA_FILES:
        ruta = folder / nombre
        if ruta.is_file():
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if isinstance(datos, dict):
                return datos
    return {}


def _fallback_brand(meta: Dict[str, Any]) -> str:
    canal = meta.get("upload_channel")
    if not canal:
        return ""
    try:
        from upload_metadata import channel_brand
        return channel_brand(canal)
    except Exception:
        return ""


def _trim_words(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    corte = text[:max_chars - 1]
    if " " in corte:
        corte = corte[:corte.rfind(" ")]
    return corte.rstrip() + "…"


def prepare_text(meta: Dict[str, Any], *, brand: str = "", optimize: bool = True,
                 on_status=None) -> Dict[str, Any]:
    """Titulo y descripcion para pegar en TikTok: {title, description, hashtags, summary}."""
    title = " ".join(str(meta.get("title") or "").split())
    description = str(meta.get("description") or "").strip()
    reporte: Dict[str, Any] = {}
    if optimize and _seo_enabled():
        try:
            # Mismo motor que Instagram (video vertical, texto con hashtags). Como ahi, la
            # descripcion no repite el titulo al principio: en TikTok el titulo va en su campo.
            from facebook_metadata import prepare_instagram_metadata
            reporte = prepare_instagram_metadata(meta, brand=brand,
                                                 log=lambda m: _status(on_status, str(m).strip()))
            title = reporte.get("title") or title
            description = reporte.get("description") or description
            _status(on_status, reporte.get("summary") or "")
        except ImportError:
            pass
        except Exception as exc:
            _status(on_status, f"optimizacion no disponible ({type(exc).__name__}: {exc}); "
                               "se usa la metadata tal cual")
    # Atribucion de la musica (CC BY la exige donde se publique el video), despues de optimizar.
    if meta.get("music_attribution"):
        try:
            from music_license import DESCRIPTION_LIMITS, with_attribution
            description = with_attribution(description, meta["music_attribution"], DESCRIPTION_LIMITS["tiktok"])
        except ImportError:
            description = f"{description}\n\n{meta['music_attribution']}".strip()
    return {"title": title, "description": _trim_words(description, DESCRIPTION_LIMIT),
            "hashtags": list(reporte.get("hashtags") or []), "summary": reporte.get("summary")}


# ================================================================ entrada principal

def _save_result(path: Path, result: Dict[str, Any]) -> None:
    try:
        datos = dict(result, uploaded_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        path.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def upload_from_metadata(output_dir: str, *, on_progress=None, on_status=None, optimize: bool = True,
                         notify: bool = True, video_path: Optional[str] = None, interactive: bool = True,
                         http=None) -> Dict[str, Any]:
    """Misma forma que los otros uploaders (carpeta + metadata), pero deja un BORRADOR.

    Nada queda publicado: el video llega a la bandeja de TikTok y el titulo y la
    descripcion, por Telegram. Si Telegram falla, el borrador igual queda y el texto va
    al log (`telegram_error` en el resultado).
    """
    carpeta = Path(output_dir)
    if video_path:
        video = Path(video_path)
    else:
        from output_video_locator import find_output_video
        encontrado = find_output_video(carpeta)
        if not encontrado:
            raise FileNotFoundError(f"No se encontró video en {output_dir}")
        video = Path(encontrado)
    # Antes del login: un documental de 15 min no tiene que abrir el navegador para nada.
    mime = _validate_video(video)
    meta = _load_metadata(carpeta)

    token = get_access_token(interactive=interactive, on_status=on_status, http=http)
    cuenta: Dict[str, Any] = {}
    try:
        cuenta = get_user_info(token, http=http)
    except TikTokError as exc:
        _status(on_status, f"no se pudo leer el nombre de la cuenta ({exc}); sigo igual")
    nombre = str(cuenta.get("display_name") or "").strip()
    _status(on_status, f"cuenta {nombre or token.get('open_id') or '(sin nombre)'}")

    texto = prepare_text(meta, brand=nombre or _fallback_brand(meta), optimize=optimize, on_status=on_status)
    enviado = send_video_to_inbox(video, token=token, on_progress=on_progress, on_status=on_status,
                                  http=http, validate=False)
    procesando = str(enviado.get("tiktok_status") or "").upper() not in INBOX_STATES
    _status(on_status, "borrador en la bandeja de TikTok" if not procesando else
                       "TikTok sigue procesando el video; la notificación llega en unos minutos")

    result: Dict[str, Any] = {
        "publish_id": enviado["publish_id"],
        "status": "draft",                      # falta publicarlo desde la app
        "tiktok_status": enviado.get("tiktok_status"),
        "account": nombre or None,
        "open_id": token.get("open_id"),
        "mime": mime,
        "title_sent": texto["title"],
        "title_original": meta.get("title") or None,
        "description_sent": texto["description"],
        "hashtags_sent": texto["hashtags"],
        "tiktok_seo": texto.get("summary"),
        "telegram_sent": False,
        "telegram_error": None,
    }
    if notify:
        try:
            from telegram_notify import build_tiktok_draft_message, send_message
            send_message(build_tiktok_draft_message(texto["title"], texto["description"],
                                                    account=nombre, processing=procesando))
            result["telegram_sent"] = True
            _status(on_status, "título y descripción enviados por Telegram")
        except Exception as exc:
            result["telegram_error"] = str(exc)[:300]
            _status(on_status, f"ATENCION: no llegó por Telegram ({exc}). Título: {texto['title']} | "
                               f"Descripción: {texto['description']}")
    _save_result(carpeta / "tiktok_upload_result.json", result)
    return result


def check_auth(http=None) -> Dict[str, Any]:
    """Diagnostico sin abrir el navegador: cuenta conectada, vencimientos y Telegram."""
    out: Dict[str, Any] = {"ok": False, "account": None, "open_id": None, "scope": None,
                           "access_expires": None, "refresh_expires": None, "telegram": None,
                           "error": None}

    def iso(ts) -> Optional[str]:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts))) if ts else None

    try:
        token = get_access_token(interactive=False, http=http)
        usuario = get_user_info(token, http=http)
        out.update(ok=True, account=usuario.get("display_name"), open_id=token.get("open_id"),
                   scope=token.get("scope"), access_expires=iso(token.get("expires_at")),
                   refresh_expires=iso(token.get("refresh_expires_at")))
    except Exception as exc:
        out["error"] = str(exc)[:300]
    try:
        from telegram_notify import check as telegram_check
        out["telegram"] = telegram_check()
    except Exception as exc:
        out["telegram"] = {"ok": False, "error": str(exc)[:200]}
    return out


def main(argv=None) -> int:
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Borradores de TikTok (bandeja) con el texto por Telegram")
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--setup", action="store_true", help="ingresar Client key y Client secret, guardarlos en .env y conectar la cuenta")
    grupo.add_argument("--auth", action="store_true", help="conectar la cuenta (abre el navegador)")
    grupo.add_argument("--check", action="store_true", help="estado de la cuenta, el permiso y Telegram")
    grupo.add_argument("--list", action="store_true", help="videos publicos de la cuenta (JSON)")
    grupo.add_argument("--upload", metavar="CARPETA_O_VIDEO",
                       help="mandar un borrador a la bandeja (carpeta con video+metadata o un .mp4)")
    args = ap.parse_args(argv)
    try:
        if args.setup:
            setup_credentials(on_status=print)
        if args.auth or args.setup:
            token = authorize(on_status=lambda m: print(m))
            try:
                nombre = get_user_info(token).get("display_name")
            except TikTokError:
                nombre = None
            print(f"Cuenta conectada: {nombre or token.get('open_id')}.")
        elif args.check:
            print(json.dumps(check_auth(), ensure_ascii=False, indent=2))
        elif args.list:
            videos = list_public_videos(get_access_token(interactive=False))
            for v in videos:
                v["created"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(v.get("create_time") or 0)))
            print(json.dumps(videos, ensure_ascii=False, indent=2))
        else:
            from upload_progress import make_byte_progress_reporter
            ruta = Path(args.upload)
            carpeta, video = (ruta.parent, ruta) if ruta.is_file() else (ruta, None)
            res = upload_from_metadata(str(carpeta), video_path=str(video) if video else None,
                                       on_status=lambda m: print(m),
                                       on_progress=make_byte_progress_reporter("subiendo", print))
            print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    except (TikTokError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
