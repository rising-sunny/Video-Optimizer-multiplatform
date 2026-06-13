# fal_ai_client.py
# Cliente real para Fal.ai (FLUX.1 schnell) manteniendo la interfaz
# historica usada por el proyecto.

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    import fal_client
except Exception:
    fal_client = None


class FalAiClient:
    """Cliente ligero para Fal.ai FLUX.1 schnell."""

    DEFAULT_MODEL_ID = "fal-ai/flux/schnell"

    def __init__(self, log_callback=None, model_id=None):
        self.log_callback = log_callback
        self.model_id = (model_id or os.getenv("FAL_IMAGE_MODEL") or self.DEFAULT_MODEL_ID).strip()
        self.api_key = (
            os.getenv("FAL_KEY")
            or os.getenv("FAL_API_KEY")
        )
        self.api_key_id = os.getenv("FAL_KEY_ID")
        self.api_key_secret = os.getenv("FAL_KEY_SECRET")
        self.last_error = None

        # El SDK oficial usa FAL_KEY. Mantener compatibilidad con proyectos
        # que solo tengan FAL_API_KEY en el .env.
        if self.api_key and not os.getenv("FAL_KEY"):
            os.environ["FAL_KEY"] = self.api_key

        self.client_available = bool(
            fal_client is not None and (
                self.api_key or (self.api_key_id and self.api_key_secret)
            )
        )

        if fal_client is None:
            self._log("WARNING fal_client no disponible en el entorno actual")
        elif self.client_available:
            self._log(f"OK FalAiClient inicializado ({self.model_id})")
        else:
            self._log("WARNING FAL_KEY/FAL_API_KEY no configurada")

    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def _resolve_image_size(self, width: int, height: int) -> str:
        if width <= 0 or height <= 0:
            return "landscape_16_9"
        if width == height:
            return "square_hd"
        return "portrait_9_16" if height > width else "landscape_16_9"

    def _build_prompt(self, prompt, negative_prompt=None, style=None):
        parts = [str(prompt or "").strip()]
        if style and str(style).strip().lower() not in {"photorealism", "realistic image", "realistic"}:
            parts.append(f"Visual style: {style}.")
        if negative_prompt:
            parts.append(f"Avoid: {negative_prompt}.")
        return "\n".join(part for part in parts if part)

    def _extract_image_url(self, payload):
        if not isinstance(payload, dict):
            return None

        images = payload.get("images") or []
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                return first.get("url") or first.get("href")
            if isinstance(first, str):
                return first

        image = payload.get("image")
        if isinstance(image, dict):
            return image.get("url") or image.get("href")
        if isinstance(image, str):
            return image

        data = payload.get("data")
        if isinstance(data, dict):
            return self._extract_image_url(data)

        return None

    def generate_image(self, prompt, width=1024, height=576, negative_prompt=None, style=None):
        """
        Mantiene la firma historica y retorna una URL publica de imagen.
        """
        self.last_error = None

        if not self.client_available:
            self.last_error = "fal_client no disponible o falta FAL_KEY/FAL_API_KEY"
            return None

        prompt_text = self._build_prompt(
            prompt=prompt,
            negative_prompt=negative_prompt,
            style=style,
        )
        if not prompt_text:
            self.last_error = "prompt vacio"
            return None

        try:
            result = fal_client.subscribe(
                self.model_id,
                arguments={
                    "prompt": prompt_text,
                    "image_size": self._resolve_image_size(width, height),
                    "num_inference_steps": 4,
                    "num_images": 1,
                },
            )
        except Exception as exc:
            self.last_error = str(exc)
            self._log(f"WARNING Fal.ai error: {exc}")
            return None

        image_url = self._extract_image_url(result)
        if image_url:
            self.last_error = None
            return image_url

        self.last_error = "Fal.ai no devolvio URL publica para la imagen"
        self._log(f"WARNING {self.last_error}")
        return None
