# -*- coding: utf-8 -*-
"""Autoriza (o verifica) el token de YouTube de un canal registrado en channel/channel_profiles.py.

En la VPS no hay navegador: el servidor de OAuth escucha en 127.0.0.1 y se llega con un tunel SSH.

  1) En la VPS:    python authorize_channel.py the-lost-atlas
  2) En tu PC:     ssh -L 8767:127.0.0.1:8767 root@5.78.125.169      (dejar abierta la terminal)
  3) En tu PC, abri en el navegador la URL que imprime el paso 1, elegi la cuenta Y EL CANAL
     "The Lost Atlas" y acepta. Google vuelve a http://localhost:8767 (llega por el tunel) y
     el token queda guardado solo. No hay que pegar ningun codigo en ningun lado.

Guarda: antes de grabar el token confirma que el canal autorizado es el del registro
(channel_id). Si elegiste otro canal, NO se guarda nada.

  python authorize_channel.py the-lost-atlas --check     # solo verifica el token existente
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from channel.channel_profiles import CHANNELS, token_path  # noqa: E402
from publish.youtube_uploader import CLIENT_SECRETS_FILE, SCOPES  # noqa: E402


def client_config():
    """client_secrets.json si existe; si no, el client_id/secret de cualquier token ya emitido (misma app de Google)."""
    if CLIENT_SECRETS_FILE.exists():
        return json.loads(CLIENT_SECRETS_FILE.read_text(encoding="utf-8"))
    for tok in sorted(ROOT.glob("token*.json")):
        try:
            d = json.loads(tok.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("client_id") and d.get("client_secret"):
            return {"installed": {"client_id": d["client_id"], "client_secret": d["client_secret"],
                                  "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": d.get("token_uri", "https://oauth2.googleapis.com/token"),
                                  "redirect_uris": ["http://localhost"]}}
    raise SystemExit("No hay client_secrets.json ni un token existente con client_id/client_secret.")


def whoami(creds):
    from googleapiclient.discovery import build
    items = build("youtube", "v3", credentials=creds, cache_discovery=False).channels().list(part="id,snippet,statistics", mine=True).execute().get("items", [])
    return items


def check(key):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    path = token_path(key)
    if not path.exists():
        print(f"[{key}] no hay token en {path.name}")
        return 1
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    missing = [s for s in SCOPES if s not in set(creds.scopes or [])]
    if missing:
        print(f"[{key}] faltan permisos: {missing}")
        return 1
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
    items = whoami(creds)
    ok = bool(items) and items[0]["id"] == CHANNELS[key]["channel_id"]
    for it in items:
        st = it.get("statistics", {})
        print(f"[{key}] canal: {it['snippet']['title']} ({it['id']})  subs={st.get('subscriberCount')} videos={st.get('videoCount')} vistas={st.get('viewCount')}")
    print(f"[{key}] {'OK: coincide con el registro' if ok else 'ERROR: el token no es del canal registrado'}")
    return 0 if ok else 1


def authorize(key, port, timeout):
    from google_auth_oauthlib.flow import InstalledAppFlow
    expected = CHANNELS[key]["channel_id"]
    flow = InstalledAppFlow.from_client_config(client_config(), SCOPES)
    print(f"\nEsperando autorizacion de {CHANNELS[key]['name']} (hasta {timeout // 60} min).")
    print("Con el tunel SSH abierto (ssh -L %d:127.0.0.1:%d root@5.78.125.169), abri la URL de abajo en tu PC.\n" % (port, port), flush=True)
    creds = flow.run_local_server(host="localhost", bind_addr="127.0.0.1", port=port, open_browser=False, timeout_seconds=timeout,
                                  authorization_prompt_message="URL:  {url}\n", success_message="Listo: ya podes cerrar esta pestana.",
                                  access_type="offline", prompt="consent")
    items = whoami(creds)
    got = items[0]["id"] if items else None
    if got != expected:
        print(f"\nERROR: autorizaste el canal {got} ({items[0]['snippet']['title'] if items else '?'}), pero {key} es {expected}. NO se guardo nada.")
        print("Repetilo y en la pantalla de Google elegi el canal 'The Lost Atlas'.")
        return 1
    path = token_path(key)
    path.write_text(creds.to_json(), encoding="utf-8")
    path.chmod(0o600)
    print(f"\nToken guardado en {path.name}  ->  canal: {items[0]['snippet']['title']} ({got})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("channel", choices=sorted(CHANNELS))
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    sys.exit(check(a.channel) if a.check else authorize(a.channel, a.port, a.timeout))
