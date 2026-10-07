# -*- coding: utf-8 -*-
"""Mandar avisos al celular por Telegram, con un bot propio del usuario.

Para que existe (2026-09-26): TikTok no deja mandar texto junto con un borrador de
video (la bandeja recibe solo el archivo, ver tiktok_uploader). El titulo y la
descripcion llegan por aca, listos para copiar con un toque: Telegram copia al
portapapeles el texto monoespaciado (`<code>`) y los bloques `<pre>` traen su
boton de copiar.

Configuracion (una sola vez):
  1. En Telegram, abrir @BotFather -> /newbot -> copiar el token que devuelve.
  2. En el `.env` (el local; NO en `.env.txt`, que viaja al VPS):
         TELEGRAM_BOT_TOKEN=<token>
  3. Abrir el chat con el bot nuevo y tocar Iniciar (o mandarle /start).
  4. .venv\\Scripts\\python.exe telegram_notify.py --setup
     (encuentra ese chat y agrega TELEGRAM_CHAT_ID al .env)
  5. .venv\\Scripts\\python.exe telegram_notify.py --test

`build_tiktok_draft_message`, `chats_from_updates` y `upsert_env_var` no tocan la
red. Ver `test_telegram_notify.py`.
"""

from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from infra.env_loader import load_project_env

ROOT = Path(__file__).resolve().parent.parent
load_project_env(ROOT)

API = "https://api.telegram.org"
MESSAGE_LIMIT = 4096          # caracteres de un mensaje, ya interpretado el HTML
TIMEOUT_S = 30


class TelegramError(RuntimeError):
    pass


def _env(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def _redact(text: str, token: str) -> str:
    """La URL de la API lleva el token: nunca tiene que aparecer en un log."""
    text = str(text or "")
    return text.replace(token, "<TOKEN>") if token else text


def is_configured() -> bool:
    return bool(_env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"))


# ------------------------------------------------------------------ mensaje

def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def _visible_len(html_text: str) -> int:
    """Largo que cuenta Telegram: sin etiquetas y con las entidades ya resueltas."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", html_text)))


def _trim_words(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max(0, max_chars - 1)]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip() + "…"


def build_tiktok_draft_message(title: str, description: str, *, account: str = "",
                               processing: bool = False, notes=()) -> str:
    """El aviso del borrador: pasos, titulo y descripcion, cada uno copiable con un toque.
    `notes`: avisos del filtro de normas de TikTok (tiktok_filter), para revisar antes de publicar."""
    titulo = " ".join(str(title or "").split())
    desc = str(description or "").strip()

    cabecera = "🎬 <b>TikTok: borrador en tu bandeja</b>"
    if account:
        cabecera += f" · {_esc(account)}"
    partes = [cabecera]
    if processing:
        partes.append("TikTok todavía lo está procesando: la notificación puede tardar unos minutos.")
    partes.append("Abrí la notificación de TikTok → Siguiente → pegá el título y la descripción → "
                  "Más opciones → activá «Contenido generado por IA» → Publicar.")
    if notes:
        partes += ["", "⚠️ <b>Filtro de normas de TikTok</b> (revisalo antes de publicar):"]
        partes += [f"• {_esc(str(n))[:300]}" for n in list(notes)[:4]]
    partes += ["", "<b>Título</b> (tocá para copiar)",
               f"<code>{_esc(titulo)}</code>" if titulo else "<i>(sin título)</i>"]
    if not desc:
        return "\n".join(partes)

    partes += ["", "<b>Descripción</b> (tocá para copiar)"]
    sin_desc = "\n".join(partes + ["<pre></pre>"])
    lugar = MESSAGE_LIMIT - _visible_len(sin_desc) - 8
    partes.append(f"<pre>{_esc(_trim_words(desc, lugar))}</pre>")
    return "\n".join(partes)


# ------------------------------------------------------------------ API

def _check(resp, token: str) -> Dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.status_code < 400 and payload.get("ok"):
        return payload
    code = payload.get("error_code") or resp.status_code
    desc = _redact(payload.get("description") or (resp.text or "")[:200], token)
    low = desc.lower()
    if code == 401:
        raise TelegramError("Telegram rechazó el token (401): revisá TELEGRAM_BOT_TOKEN en .env.")
    if "chat not found" in low:
        raise TelegramError("Telegram no encuentra el chat: mandale /start a tu bot y corré "
                            "telegram_notify.py --setup.")
    if code == 403:
        raise TelegramError("El bot no puede escribirte (403): abrí su chat y tocá Iniciar, o "
                            f"desbloquealo. Detalle: {desc}")
    if code == 429:
        espera = (payload.get("parameters") or {}).get("retry_after")
        raise TelegramError(f"Telegram limitó la frecuencia (429); reintentá en {espera or 'unos'} s.")
    if "can't parse entities" in low:
        raise TelegramError(f"Telegram no pudo leer el formato del mensaje: {desc}")
    raise TelegramError(f"Telegram falló ({code}): {desc}")


def _call(method: str, token: str, *, json_body: Optional[dict] = None, http=None) -> Dict[str, Any]:
    http = http or requests
    try:
        resp = http.post(f"{API}/bot{token}/{method}", json=json_body or {}, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        raise TelegramError(f"No se pudo conectar con Telegram: {_redact(str(exc), token)}") from None
    return _check(resp, token)


def send_message(text: str, *, token: Optional[str] = None, chat_id: Optional[str] = None,
                 parse_mode: str = "HTML", http=None) -> Dict[str, Any]:
    token = token or _env("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or _env("TELEGRAM_CHAT_ID")
    if not token:
        raise TelegramError("Falta TELEGRAM_BOT_TOKEN en .env (se crea con @BotFather en Telegram).")
    if not chat_id:
        raise TelegramError("Falta TELEGRAM_CHAT_ID en .env: mandale /start a tu bot y corré "
                            "telegram_notify.py --setup.")
    payload = _call("sendMessage", token, http=http, json_body={
        "chat_id": chat_id, "text": text, "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    })
    return payload.get("result") or {}


def chats_from_updates(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chats que le escribieron al bot (getUpdates), del mas reciente al mas viejo."""
    chats: List[Dict[str, Any]] = []
    vistos = set()
    for update in reversed((payload or {}).get("result") or []):
        for clave in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(clave) or {}).get("chat") or {}
            if "id" not in chat or chat["id"] in vistos:
                continue
            vistos.add(chat["id"])
            nombre = " ".join(p for p in (chat.get("first_name"), chat.get("last_name")) if p)
            chats.append({"id": chat["id"], "type": chat.get("type") or "",
                          "name": nombre or chat.get("title") or chat.get("username") or str(chat["id"])})
    return chats


def upsert_env_var(path: Path, name: str, value: str) -> bool:
    """Deja `NAME=value` en el archivo sin tocar las demas lineas. True si cambio algo."""
    path = Path(path)
    lineas = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    patron = re.compile(rf"^\s*{re.escape(name)}\s*=")
    nueva = f"{name}={value}"
    for i, linea in enumerate(lineas):
        if patron.match(linea):
            if linea.strip() == nueva:
                return False
            lineas[i] = nueva
            break
    else:
        lineas.append(nueva)
    path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return True


def check(http=None) -> Dict[str, Any]:
    """Estado sin mandar nada: el token sirve (getMe) y hay chat configurado."""
    token, chat_id = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    out: Dict[str, Any] = {"configured": bool(token and chat_id), "ok": False, "bot": None,
                           "chat_id": chat_id or None, "error": None}
    if not token:
        out["error"] = "falta TELEGRAM_BOT_TOKEN en .env"
        return out
    try:
        bot = _call("getMe", token, http=http).get("result") or {}
        out["bot"] = "@" + str(bot.get("username") or "")
        out["ok"] = bool(chat_id)
        if not chat_id:
            out["error"] = "falta TELEGRAM_CHAT_ID: corré telegram_notify.py --setup"
    except TelegramError as exc:
        out["error"] = str(exc)
    return out


# ------------------------------------------------------------------ CLI

def _setup() -> int:
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Falta TELEGRAM_BOT_TOKEN en .env. Crealo con @BotFather (/newbot) y pegalo así:\n"
              "    TELEGRAM_BOT_TOKEN=<token>")
        return 1
    bot = _call("getMe", token).get("result") or {}
    usuario = bot.get("username") or ""
    chats = chats_from_updates(_call("getUpdates", token))
    privados = [c for c in chats if c["type"] == "private"] or chats
    if not privados:
        print(f"Todavía nadie le escribió al bot. Abrí https://t.me/{usuario}, tocá Iniciar "
              "y volvé a correr esto.")
        return 1
    chat = privados[0]
    cambio = upsert_env_var(ROOT / ".env", "TELEGRAM_CHAT_ID", str(chat["id"]))
    print(f"Chat encontrado: {chat['name']} ({chat['id']}). TELEGRAM_CHAT_ID "
          f"{'guardado' if cambio else 'ya estaba'} en .env.")
    send_message("Listo: este chat va a recibir los títulos y descripciones de TikTok.",
                 token=token, chat_id=str(chat["id"]))
    print("Te mandé un mensaje de prueba.")
    return 0


def main(argv=None) -> int:
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Avisos por Telegram (textos de TikTok)")
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--setup", action="store_true",
                       help="encontrar tu chat (mandale /start al bot antes) y guardarlo en .env")
    grupo.add_argument("--test", action="store_true", help="mandar un mensaje de prueba")
    args = ap.parse_args(argv)
    try:
        if args.setup:
            return _setup()
        send_message(build_tiktok_draft_message(
            "72 Seconds: The Wow! Signal",
            "In 1977 a radio telescope caught a signal that never came back.\n\n#WowSignal #History",
            account="(prueba)"))
        print("Mensaje de prueba enviado.")
        return 0
    except TelegramError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
