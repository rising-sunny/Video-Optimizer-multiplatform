# deepseek_client.py
# Cliente para interactuar con la API de DeepSeek (OpenAI-compatible) via `requests`.
# Se usa, entre otras cosas, como "juez" del verificador de hechos del guion
# (ai/script_fact_check.py): revisa tramos del guion contra los parrafos de
# Wikipedia que ya trae el prompt y devuelve un JSON con el veredicto.
#
# Nota: se usa `requests` (y no la libreria `openai`) para evitar el conflicto
# openai<->httpx 0.28 (`Client.__init__() got an unexpected keyword 'proxies'`).

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from infra.env_loader import load_project_env

# ========== Cargar variables de entorno ==========
load_project_env()

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL_DEFAULT = "deepseek-chat"

# ========== Presupuesto diario ==========
# Tope de gasto ESTIMADO por dia (UTC) en USD, para que un bucle o un video largo no vacie el saldo.
#   DEEPSEEK_DAILY_BUDGET_USD  tope (defecto 1.00; 0 o negativo lo desactiva)
#   DEEPSEEK_PRICE_IN_PER_M / DEEPSEEK_PRICE_OUT_PER_M  USD por millon de tokens (defecto conservador,
#                              por encima de la tarifa publica; ajustalos si cambia el precio)
#   DEEPSEEK_BUDGET_FILE       donde se guarda el acumulado (defecto generated_media/deepseek_budget.json)
# Al llegar al tope DeepSeek devuelve None (log claro) y GroqAiClient pasa a Groq si hay clave.
DEFAULT_DAILY_BUDGET_USD = 1.0
DEFAULT_PRICE_IN_PER_M = 0.60
DEFAULT_PRICE_OUT_PER_M = 2.20
_BUDGET_LOCK = threading.Lock()


def _float_env(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, "")).strip() or default)
    except ValueError:
        return default


def daily_budget_usd() -> float:
    return _float_env("DEEPSEEK_DAILY_BUDGET_USD", DEFAULT_DAILY_BUDGET_USD)


def _budget_path() -> Path:
    custom = str(os.getenv("DEEPSEEK_BUDGET_FILE") or "").strip()
    return Path(custom) if custom else Path(__file__).resolve().parent.parent / "generated_media" / "deepseek_budget.json"


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def budget_state() -> dict:
    """Gasto estimado de HOY: {date, usd, requests, input_tokens, output_tokens}. Un dia nuevo parte de cero."""
    empty = {"date": _today(), "usd": 0.0, "requests": 0, "input_tokens": 0, "output_tokens": 0}
    try:
        data = json.loads(_budget_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("date") == empty["date"]:
            return {**empty, **{k: data[k] for k in empty if k in data}}
    except (OSError, ValueError):
        pass
    return empty


def budget_exceeded() -> bool:
    limit = daily_budget_usd()
    return limit > 0 and float(budget_state().get("usd") or 0.0) >= limit


def record_usage(usage: Optional[dict]) -> float:
    """Suma al acumulado del dia lo que costo esta llamada (segun `usage` de la API). Devuelve el USD estimado."""
    usage = usage if isinstance(usage, dict) else {}
    tin = int(usage.get("prompt_tokens") or 0)
    tout = int(usage.get("completion_tokens") or 0)
    cost = (tin * _float_env("DEEPSEEK_PRICE_IN_PER_M", DEFAULT_PRICE_IN_PER_M)
            + tout * _float_env("DEEPSEEK_PRICE_OUT_PER_M", DEFAULT_PRICE_OUT_PER_M)) / 1_000_000
    path = _budget_path()
    with _BUDGET_LOCK:
        state = budget_state()
        state.update(usd=round(float(state["usd"]) + cost, 6), requests=int(state["requests"]) + 1,
                     input_tokens=int(state["input_tokens"]) + tin, output_tokens=int(state["output_tokens"]) + tout)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".deepseek_budget_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
            os.replace(tmp, path)
        except OSError as exc:
            print(f"[WARN] No se pudo guardar el presupuesto de DeepSeek: {exc}")
    return cost


# System prompt neutro para el modo JSON (el "juez" devuelve hallazgos en JSON).
JSON_SYSTEM = (
    "Return exactly one complete, valid JSON object matching the requested structure. "
    "No markdown or narration outside the JSON. Follow the requested historical accuracy "
    "and uncertainty rules; do not invent sources, events or quotes."
)
GENERAL_SYSTEM = (
    "You are a helpful assistant for video production. "
    "Output only the requested content without conversational filler. Be concise and accurate."
)


class DeepSeekClient:
    """Cliente minimo de DeepSeek (chat completions via REST)."""

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.model = os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL_DEFAULT).strip() or DEEPSEEK_MODEL_DEFAULT
        if not self.api_key:
            print("[WARN] DEEPSEEK_API_KEY no encontrada en .env o .env.txt")
            return
        print(f"[OK] Cliente DeepSeek inicializado. Modelo: {self.model}")

    def _generate(self, prompt_text, max_tokens=4096, task_type="general", json_mode=False,
                  system: Optional[str] = None, model: Optional[str] = None):
        """Genera texto con DeepSeek. Devuelve el contenido o None si falla.

        `model` permite elegir otro modelo para una tarea concreta sin tocar el
        `DEEPSEEK_MODEL` global (p. ej. `deepseek-chat` para JSON estricto).
        """
        if not self.api_key:
            print("[ERROR] DeepSeek no esta configurado.")
            return None
        if budget_exceeded():
            st = budget_state()
            print(f"[ERROR] DeepSeek: presupuesto diario agotado (~{st['usd']:.2f} de {daily_budget_usd():.2f} USD, "
                  f"{st['requests']} llamadas hoy). Subi DEEPSEEK_DAILY_BUDGET_USD o espera a manana (UTC).")
            return None
        try:
            safe_max_tokens = max(256, min(8192, int(max_tokens)))
        except Exception:
            safe_max_tokens = 4096

        use_model = (model or self.model or "deepseek-chat").strip()

        if system is not None:
            system_content = system
        elif json_mode:
            system_content = JSON_SYSTEM
        else:
            system_content = GENERAL_SYSTEM

        payload = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt_text},
            ],
            "max_tokens": safe_max_tokens,
        }
        # deepseek-reasoner (R1) no acepta temperature ni otros parametros de muestreo.
        if "reasoner" not in use_model.lower():
            payload["temperature"] = 0.45 if str(task_type or "general").lower() == "script_quality" else 0.7
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=180,
            )
            if resp.status_code != 200:
                print(f"[ERROR] DeepSeek HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            record_usage(data.get("usage"))
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
            if content:
                cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", content)
                cleaned = re.sub(r"[\u0000-\u001F\u007F-\u009F]", "", cleaned)
                return cleaned
        except Exception as e:
            print(f"[ERROR] Error en la API de DeepSeek ({use_model}): {str(e)[:180]}")
        return None
