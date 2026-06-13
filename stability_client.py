# stability_client.py
"""
Cliente para la API de Stability AI (Stable Image Ultra / Core).
Documentación: https://platform.stability.ai/docs/api-reference

Modelos disponibles:
  - ultra : $0.008/imagen — mayor calidad, ideal para producción
  - core  : $0.003/imagen — calidad similar a Flux dev, más económico

Requiere STABILITY_API_KEY en .env.txt
"""

import os
import time
import requests
from pathlib import Path
from typing import Optional, Dict
from collections import deque

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")

# Aspect ratios válidos para Stable Image Ultra y Core
_VALID_RATIOS = {"16:9", "9:16", "1:1", "21:9", "9:21", "2:3", "3:2", "4:5", "5:4"}


def _best_aspect_ratio(width: int, height: int) -> str:
    """Devuelve el aspect ratio admitido más cercano a las dimensiones solicitadas."""
    if width <= 0 or height <= 0:
        return "1:1"
    target = width / height
    candidates = {
        "16:9": 16 / 9,
        "9:16": 9 / 16,
        "1:1":  1.0,
        "21:9": 21 / 9,
        "9:21": 9 / 21,
        "2:3":  2 / 3,
        "3:2":  3 / 2,
        "4:5":  4 / 5,
        "5:4":  5 / 4,
    }
    return min(candidates, key=lambda k: abs(candidates[k] - target))


class StabilityClient:
    """
    Cliente REST para Stability AI Stable Image (Ultra / Core).

    Uso:
        client = StabilityClient(model="ultra")
        result = client.generate_image(
            prompt="...", width=1920, height=1080, output_path="out.png"
        )
        if result:
            print(result["path"])
    """

    BASE_URL = "https://api.stability.ai/v2beta/stable-image/generate"

    def __init__(self, log_callback=None, model: str = "ultra"):
        self._log = log_callback or print
        self.api_key = os.getenv("STABILITY_API_KEY") or STABILITY_API_KEY
        self.model = model.strip().lower() if model else "ultra"
        if self.model not in {"ultra", "core"}:
            self.model = "ultra"
        self.last_error: Optional[str] = None
        # Rate limiting conservador: 10 req/10 s
        self._request_times: deque = deque()
        self._min_delay = 1.0  # segundos entre peticiones

        if not self.api_key:
            self._log("  Stability AI: STABILITY_API_KEY no encontrada en .env.txt")
        else:
            self._log(f"  Cliente Stability AI ({self.model}) inicializado")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------
    def _rate_limit(self):
        now = time.time()
        # Limpiar ventana de 10 s
        while self._request_times and now - self._request_times[0] > 10:
            self._request_times.popleft()
        # Max 10 req / 10 s
        if len(self._request_times) >= 10:
            wait = 10 - (now - self._request_times[0]) + 0.1
            if wait > 0:
                self._log(f"   Stability AI rate limit — esperando {wait:.1f}s...")
                time.sleep(wait)
                now = time.time()
                while self._request_times and now - self._request_times[0] > 10:
                    self._request_times.popleft()
        # Delay mínimo entre peticiones
        if self._request_times:
            elapsed = now - self._request_times[-1]
            if elapsed < self._min_delay:
                time.sleep(self._min_delay - elapsed)
        self._request_times.append(time.time())

    # ------------------------------------------------------------------
    def generate_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        negative_prompt: str = "",
        output_path: Optional[str] = None,
        style: Optional[str] = None,      # ignorado — siempre fotorrealista
        num_images: int = 1,
    ) -> Optional[Dict]:
        """
        Genera una imagen con Stability AI.

        Returns:
            dict con claves: path, data, width, height, prompt
            o None si falla.
        """
        self.last_error = None

        if not self.api_key:
            self.last_error = "STABILITY_API_KEY no configurada"
            self._log(f"   Stability AI: {self.last_error}")
            return None

        prompt = (prompt or "").strip()
        if not prompt:
            self.last_error = "Prompt vacío"
            return None
        if len(prompt) > 10000:
            prompt = prompt[:10000]

        aspect_ratio = _best_aspect_ratio(width, height)
        endpoint = f"{self.BASE_URL}/{self.model}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "image/*",
        }

        files: dict = {"none": ""}   # multipart dummy necesario
        data: dict = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "png",
        }
        if negative_prompt:
            data["negative_prompt"] = negative_prompt[:10000]

        self._rate_limit()
        self._log(f"   [Stability {self.model.upper()}] {aspect_ratio} — {prompt[:80]}...")

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                files=files,
                data=data,
                timeout=90,
            )
        except requests.exceptions.RequestException as exc:
            self.last_error = str(exc)
            self._log(f"   Stability AI error de red: {exc}")
            return None

        if response.status_code == 200:
            image_data = response.content
        elif response.status_code == 402:
            self.last_error = "Sin créditos en la cuenta de Stability AI"
            self._log(f"   Stability AI: {self.last_error}")
            return None
        elif response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            self._log(f"   Stability AI rate limit (429) — esperando {retry_after}s...")
            time.sleep(retry_after)
            # Reintentar una vez
            try:
                response = requests.post(endpoint, headers=headers, files=files,
                                         data=data, timeout=90)
                if response.status_code == 200:
                    image_data = response.content
                else:
                    self.last_error = f"HTTP {response.status_code} tras reintento"
                    self._log(f"   Stability AI: {self.last_error}")
                    return None
            except requests.exceptions.RequestException as exc:
                self.last_error = str(exc)
                return None
        else:
            try:
                msg = response.json().get("message") or response.text[:300]
            except Exception:
                msg = response.text[:300]
            self.last_error = f"HTTP {response.status_code}: {msg}"
            self._log(f"   Stability AI error: {self.last_error}")
            return None

        if not image_data:
            self.last_error = "Respuesta vacía"
            return None

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "wb") as f:
                f.write(image_data)
            self._log(f"     Imagen guardada: {output_path}")

        return {
            "path": output_path,
            "data": image_data,
            "url": None,
            "width": width,
            "height": height,
            "prompt": prompt,
        }
