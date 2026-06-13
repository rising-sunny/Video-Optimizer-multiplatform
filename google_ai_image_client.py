# google_ai_image_client.py
"""
Cliente para generar imagenes con Google AI (Gemini) via API.
"""

import base64
import os
from typing import Callable, Dict, List, Optional, Tuple

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


class GoogleAiImageClient:
    """Wrapper ligero para generacion de imagenes con Gemini."""

    def __init__(self, log_callback: Optional[Callable[[str], None]] = None, model_name: Optional[str] = None):
        self._log = log_callback or print
        self.api_key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GOOGLE_AI_API_KEY")
        )
        self.client_available = bool(self.api_key)
        self.model_candidates = self._build_model_candidates(model_name)
        self.last_error = None
        self.last_status_code = None

        if self.client_available:
            self._log("OK GoogleAiImageClient inicializado")
        else:
            self._log("WARNING GEMINI_API_KEY/GOOGLE_API_KEY no configurada")

    def _build_model_candidates(self, model_name: Optional[str]) -> List[str]:
        env_model = os.getenv("GOOGLE_IMAGE_MODEL", "").strip()
        candidates = [
            (model_name or "").strip(),
            env_model,
            "gemini-2.5-flash-image",
            "gemini-3.1-flash-image-preview",
            "gemini-3-pro-image-preview",
            "gemini-2.0-flash-exp-image-generation",
            # Fallback textual legacy (normalmente no soporta salida de imagen).
            "gemini-2.0-flash",
        ]
        result: List[str] = []
        for model in candidates:
            if model and model not in result:
                result.append(model)
        return result

    def _build_prompt(self, prompt: str, width: int, height: int,
                      style: Optional[str] = None, negative_prompt: Optional[str] = None) -> str:
        lines = [
            (prompt or "").strip(),
            f"Target resolution/aspect ratio: {width}x{height}.",
            "Generate exactly one high-quality image.",
            "Do not include text, letters, logos or watermarks.",
        ]
        if style:
            lines.append(f"Visual style: {style}.")
        if negative_prompt:
            lines.append(f"Avoid: {negative_prompt}.")
        return "\n".join(line for line in lines if line)

    def _extract_inline_image_bytes(self, payload: Dict) -> Optional[bytes]:
        candidates = payload.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                inline = part.get("inlineData") or part.get("inline_data") or {}
                data_b64 = inline.get("data")
                if not data_b64:
                    continue
                try:
                    return base64.b64decode(data_b64)
                except Exception:
                    continue
        return None

    def _request_generate_content(self, model: str, prompt_text: str) -> Tuple[Optional[bytes], Optional[str], Optional[int]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        params = {"key": self.api_key}
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE", "TEXT"],
            },
        }

        response = requests.post(url, params=params, json=payload, timeout=90)
        if response.status_code != 200:
            try:
                error_data = response.json()
                error_text = (
                    error_data.get("error", {}).get("message")
                    or error_data.get("error", {}).get("status")
                    or response.text[:240]
                )
            except Exception:
                error_text = response.text[:240]
            return None, f"HTTP {response.status_code}: {error_text}", response.status_code

        try:
            data = response.json()
        except Exception as exc:
            return None, f"Respuesta JSON invalida: {exc}", response.status_code

        image_bytes = self._extract_inline_image_bytes(data)
        if image_bytes:
            return image_bytes, None, response.status_code

        prompt_feedback = data.get("promptFeedback") or {}
        block_reason = prompt_feedback.get("blockReason")
        if block_reason:
            return None, f"Bloqueado por seguridad: {block_reason}", response.status_code

        return None, "La API respondio sin inlineData de imagen", response.status_code

    def generate_image(self, prompt: str, width: int = 1024, height: int = 1024,
                       negative_prompt: Optional[str] = None, style: Optional[str] = None) -> Optional[bytes]:
        """
        Genera una imagen y retorna bytes binarios (PNG/JPEG segun modelo).
        """
        self.last_error = None
        self.last_status_code = None

        if not self.client_available:
            self.last_error = "falta API key"
            self._log("WARNING Google AI no disponible: falta API key")
            return None

        prompt_text = self._build_prompt(
            prompt=prompt,
            width=width,
            height=height,
            style=style,
            negative_prompt=negative_prompt,
        )

        last_error = None
        import time
        last_error = None
        for model in self.model_candidates:
            retries = 4
            for attempt in range(retries):
                try:
                    if attempt > 0:
                        self._log(f"   [GoogleAI] ({model}) reintentando imagen ({attempt}/{retries - 1})...")
                    else:
                        self._log(f"   [GoogleAI] ({model}) generando imagen...")
                        
                    image_bytes, error_message, status_code = self._request_generate_content(model, prompt_text)
                    self.last_status_code = status_code
                    if image_bytes:
                        self.last_error = None
                        return image_bytes
                        
                    last_error = error_message or "Error desconocido"
                    self.last_error = last_error
                    
                    if status_code == 429:
                        self._log(f"   [GoogleAI] Límite de cuota (HTTP 429). Pausando 60 segundos antes de reintentar...")
                        time.sleep(60)
                        continue
                    else:
                        self._log(f"   [GoogleAI] ({model}) sin imagen: {last_error}")
                        break
                except Exception as exc:
                    last_error = str(exc)
                    self.last_error = last_error
                    self._log(f"   [GoogleAI] ({model}) error: {last_error}")
                    break

        self.last_error = last_error
        self._log(f"   [GoogleAI] fallo en todos los modelos. Ultimo error: {last_error}")
        return None
