# deepseek_client.py
# Cliente para interactuar con la API de DeepSeek (OpenAI-compatible) via `requests`.
# Se usa, entre otras cosas, como "juez" del verificador de hechos del guion
# (ai/script_fact_check.py): revisa tramos del guion contra los parrafos de
# Wikipedia que ya trae el prompt y devuelve un JSON con el veredicto.
#
# Nota: se usa `requests` (y no la libreria `openai`) para evitar el conflicto
# openai<->httpx 0.28 (`Client.__init__() got an unexpected keyword 'proxies'`).

import os
import re
from typing import Optional

import requests

from infra.env_loader import load_project_env

# ========== Cargar variables de entorno ==========
load_project_env()

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL_DEFAULT = "deepseek-chat"

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
                  system: Optional[str] = None):
        """Genera texto con DeepSeek. Devuelve el contenido o None si falla."""
        if not self.api_key:
            print("[ERROR] DeepSeek no esta configurado.")
            return None
        try:
            safe_max_tokens = max(256, min(8192, int(max_tokens)))
        except Exception:
            safe_max_tokens = 4096

        if system is not None:
            system_content = system
        elif json_mode:
            system_content = JSON_SYSTEM
        else:
            system_content = GENERAL_SYSTEM

        temperature = 0.45 if str(task_type or "general").lower() == "script_quality" else 0.7

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt_text},
            ],
            "temperature": temperature,
            "max_tokens": safe_max_tokens,
        }
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
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
            if content:
                cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", content)
                cleaned = re.sub(r"[\u0000-\u001F\u007F-\u009F]", "", cleaned)
                return cleaned
        except Exception as e:
            print(f"[ERROR] Error en la API de DeepSeek ({self.model}): {str(e)[:180]}")
        return None
