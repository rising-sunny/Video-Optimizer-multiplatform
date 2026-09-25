# groq_client.py
# Cliente para interactuar con la API de Groq Cloud Console como respaldo de IA de texto

import os
import requests
from typing import List, Set
from env_loader import load_project_env

# ========== Cargar variables de entorno ==========
load_project_env()

try:
    from groq import Groq
    GROQ_LIB_OK = True
except ImportError:
    GROQ_LIB_OK = False
    print("[WARN] Libreria 'groq' no encontrada. Groq no funcionara. (pip install groq)")

# Cargar API Key (DESPUÉS de load_dotenv)
GROQ_API_KEY = None

class GroqAiClient:
    """
    Cliente para interactuar con la API de Groq Cloud Console como respaldo.
    Groq ofrece modelos de IA muy rápidos como llama-3.3-70b-versatile, mixtral-8x7b-32768, etc.
    """
    def __init__(self):
        self.client = None
        self.api_key = os.getenv("GROQ_API_KEY")
        # Cadenas de modelos por tipo de tarea.
        # script_quality prioriza calidad factual y consistencia para guiones largos.
        self.script_models = [
            "openai/gpt-oss-120b",
            "groq/compound",
            "moonshotai/kimi-k2-instruct-0905",
            "moonshotai/kimi-k2-instruct",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "qwen/qwen3-32b",
            "llama-3.3-70b-versatile",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant"
        ]
        self.general_models = [
            "llama-3.3-70b-versatile",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant"
        ]
        self.available_models: Set[str] = set()
        self.model_cursors = {"general": 0, "script_quality": 0}
        self.models = self.general_models[:]  # compatibilidad con código legacy
        self.model_index = 0
        
        if not GROQ_LIB_OK:
            return

        if not self.api_key:
            print("[WARN] GROQ_API_KEY no encontrada en .env o .env.txt")
            return
        
        # Limpiar env vars de proxies si interfieren
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('HTTPS_PROXY', None)
        os.environ.pop('PROXY', None)

        try:
            self.client = Groq(
                api_key=self.api_key,
            )
            self._refresh_available_models()
            print(f"[OK] Cliente Groq inicializado. Modelo: {self.model}")
        except Exception as e:
            print(f"[ERROR] Error al inicializar Groq: {e}")

    @property
    def model(self):
        """Retorna el modelo actual"""
        candidates = self._get_models_for_task("general")
        if candidates:
            return candidates[0]
        return "llama-3.1-8b-instant"

    def _refresh_available_models(self):
        """Consulta modelos disponibles en la cuenta y filtra catálogos locales."""
        if not self.api_key:
            return
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers=headers,
                timeout=15
            )
            if response.status_code != 200:
                print(f"[WARN] No se pudo consultar catalogo de Groq ({response.status_code}).")
                return
            payload = response.json() or {}
            data = payload.get("data", [])
            discovered = {
                str(item.get("id", "")).strip()
                for item in data
                if isinstance(item, dict) and item.get("id")
            }
            if discovered:
                self.available_models = discovered
                self.script_models = [
                    m for m in self.script_models if m in self.available_models
                ] or self.script_models
                self.general_models = [
                    m for m in self.general_models if m in self.available_models
                ] or self.general_models
                self.models = self.general_models[:]
                if self.models:
                    print(
                        f"[INFO] Groq catalog active: {len(self.available_models)} models. "
                        f"Script preferred: {self.script_models[0] if self.script_models else 'N/A'}"
                    )
        except Exception as e:
            print(f"[WARN] Error querying Groq catalog: {str(e)[:120]}")

    def _get_models_for_task(self, task_type: str = "general") -> List[str]:
        if str(task_type or "").lower() == "script_quality":
            ordered = self.script_models + self.general_models
        else:
            ordered = self.general_models + self.script_models

        deduped = []
        seen = set()
        for model_id in ordered:
            if model_id and model_id not in seen:
                seen.add(model_id)
                deduped.append(model_id)

        if self.available_models:
            filtered = [m for m in deduped if m in self.available_models]
            if filtered:
                return filtered
        return deduped

    def _generate(self, prompt_text, max_tokens=4096, task_type="general", json_mode=False):
        """Genera texto usando Groq, seleccionando modelo según tipo de tarea."""
        if not self.client:
            print("[ERROR] Groq no esta configurado.")
            return None

        try:
            safe_max_tokens = int(max_tokens)
        except Exception:
            safe_max_tokens = 4096
        safe_max_tokens = max(256, min(8192, safe_max_tokens))

        task_key = str(task_type or "general").lower()
        candidate_models = self._get_models_for_task(task_key)
        if not candidate_models:
            print("[ERROR] No hay modelos Groq candidatos para esta tarea.")
            return None

        start_idx = int(self.model_cursors.get(task_key, 0)) % len(candidate_models)
        order = [candidate_models[(start_idx + i) % len(candidate_models)] for i in range(len(candidate_models))]
        temperature = 0.45 if task_key == "script_quality" else 0.7
        last_error = None

        for idx, current_model in enumerate(order):
            try:
                print(f"   [INFO] Consultando a Groq ({current_model}) [{task_key}]...")

                system_content = (
                    # Neutral system prompt: tone/persona is fully controlled by the user prompt,
                    # which now carries a category-derived tone profile (documentary / dramatic_factual / mystery).
                    # Previously this system prompt hardcoded a mystery-channel persona, which overrode
                    # historical/scientific topics and caused fabricated content (curses, pseudohistory, fake conspiracies).
                    "You are an expert scriptwriter for video documentaries. "
                    "Follow the tone, persona and content rules given in the user prompt EXACTLY — "
                    "if the user prompt forbids paranormal/conspiracy framing, do NOT add it. "
                    "If the user prompt requests strict factual/historical content, do NOT invent events, names, dates, organizations or quotes. "
                    "When documented material does not fill the requested duration, produce a SHORTER script rather than fabricating filler. "
                    "Never refuse a historical documentary narration. If a proper name is unfamiliar, use the aliases and outline in the user prompt. "
                    "Do not reply with apologies or 'I can't fulfill that request' — output narration only. "
                    "Output only the requested content without conversational filler or meta-commentary."
                ) if task_key == "script_quality" else (
                    "You are a helpful assistant for video production. "
                    "Output only the requested content without conversational filler. Be concise and accurate."
                )

                if json_mode:
                    system_content = (
                        "Return exactly one complete, valid JSON object matching the requested structure. "
                        "No markdown or narration outside the JSON. Follow the requested historical accuracy "
                        "and uncertainty rules; do not invent sources, events or quotes."
                    )
                chat_completion = self.client.chat.completions.create(
                    messages=[
                        {
                            "role": "system",
                            "content": system_content
                        },
                        {
                            "role": "user",
                            "content": prompt_text
                        }
                    ],
                    model=current_model,
                    temperature=temperature,
                    max_tokens=safe_max_tokens,
                    **({'response_format': {'type': 'json_object'}} if json_mode else {})
                )

                if chat_completion.choices[0].finish_reason == 'length':
                    last_error = 'Respuesta truncada por límite de tokens'
                    print(f'[WARN] {last_error}; probando siguiente modelo.')
                    continue
                response = chat_completion.choices[0].message.content
                if response:
                    import re
                    cleaned_response = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', response)
                    cleaned_response = re.sub(r'[\u0000-\u001F\u007F-\u009F]', '', cleaned_response)
                    if json_mode:
                        import json
                        payload = json.loads(cleaned_response)
                        if not isinstance(payload, dict):
                            raise ValueError('La respuesta JSON debe ser un objeto')
                    self.model_cursors[task_key] = (start_idx + idx) % len(candidate_models)
                    if task_key == "general":
                        self.model_index = self.model_cursors[task_key]
                    print(f"[OK] Respuesta generada por Groq ({current_model})")
                    return cleaned_response
                last_error = "Respuesta vacía"
            except Exception as e:
                last_error = str(e)
                error_msg = last_error.lower()
                print(f"[ERROR] Error en la API de Groq ({current_model}): {last_error}")

                if (
                    "decommissioned" in error_msg
                    or "no longer supported" in error_msg
                    or "not found" in error_msg
                    or ("model" in error_msg and "invalid" in error_msg)
                ):
                    if current_model in self.available_models:
                        self.available_models.discard(current_model)
                    self.script_models = [m for m in self.script_models if m != current_model]
                    self.general_models = [m for m in self.general_models if m != current_model]
                    self.models = self.general_models[:]

                # En rate limits o timeouts, continuar al siguiente modelo.
                continue

        if last_error:
            print(f"[ERROR] Todos los modelos de Groq fallaron. Ultimo error: {last_error[:180]}")
        else:
            print("[ERROR] Todos los modelos de Groq fallaron.")
        return None
