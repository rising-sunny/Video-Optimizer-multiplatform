# fal_ai_client.py
"""
Cliente unificado para FAL.AI (hub de modelos).

Provee dos clases principales:

* FalAiImageClient  -> genera imagenes con Flux.1 dev/schnell y devuelve el
                       archivo local (descargado) o, si el caller lo pide,
                       la URL publica.
* FalAiVideoClient  -> genera clips de video a partir de una imagen (Image-to-
                       Video) con Kling v1.5 o Luma Dream Machine, y los
                       descarga como MP4 local.

Ambas clases esperan la FAL_KEY como variable de entorno (FAL_KEY o
FAL_API_KEY) y se apoyan en el SDK oficial `fal_client`.

Uso tipico (Image-to-Video automatico):

    from fal_ai_client import FalAiImageClient, FalAiVideoClient

    img = FalAiImageClient()
    vid = FalAiVideoClient()

    image_url = img.generate_image(
        "Historical mystery, cinematic lighting, pyramids of Giza at dusk",
        width=1920, height=1080, return_url=True,
    )
    video_path = vid.image_to_video(
        image_url=image_url,
        prompt="Slow dramatic zoom, dust particles in the air",
        output_path="clip_01.mp4",
        model="kling",
        duration=5,
    )
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional, Tuple

try:
    import requests
except Exception:
    requests = None  # pragma: no cover

try:
    import fal_client
except Exception:
    fal_client = None


# --- Tarifas estimadas (USD) -------------------------------------------------
# Valores aproximados publicados por FAL.AI (diciembre 2025). Mantener
# sincronizado con cost_calculator.py.
FAL_PRICES = {
    "fal-ai/flux/dev":     {"per_image": 0.025},
    "fal-ai/flux/schnell": {"per_image": 0.003},
    "kling-standard":      {"per_second": 0.095},  # ~$0.48 por clip de 5s
    "kling-pro":           {"per_second": 0.190},
    "luma":                {"per_second": 0.100},  # ~$0.50 por clip de 5s
}


# =============================================================================
#  Helpers
# =============================================================================

def _ensure_fal_key() -> bool:
    """Copia FAL_API_KEY -> FAL_KEY si hace falta. Devuelve si hay clave."""
    if os.getenv("FAL_KEY"):
        return True
    alt = os.getenv("FAL_API_KEY")
    if alt:
        os.environ["FAL_KEY"] = alt
        return True
    return False


def _download_url_to_file(url: str, out_path: str, timeout: int = 120) -> Optional[str]:
    """Descarga una URL a archivo local. Devuelve la ruta o None si falla."""
    if not url or not requests:
        return None
    try:
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        handle.write(chunk)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
    except Exception:
        return None
    return None


def _resolve_image_size(width: int, height: int):
    """Devuelve el valor correcto para el campo image_size de Flux.

    Flux acepta los presets ('square_hd', 'landscape_16_9', etc.) O un dict
    {"width": w, "height": h}. Usamos el dict siempre que las dimensiones no
    encajen exactamente en un preset, garantizando que se respeten exactamente.
    """
    if width <= 0 or height <= 0:
        return "landscape_16_9"
    # Presets exactos reconocidos por Flux
    presets = {
        (1920, 1080): "landscape_16_9",
        (1280, 720):  "landscape_16_9",
        (1080, 1920): "portrait_16_9",   # 9:16 en nomenclatura de Flux
        (720,  1280): "portrait_16_9",
        (1080, 1080): "square_hd",
        (512,  512):  "square",
    }
    preset = presets.get((width, height))
    if preset:
        return preset
    # Para cualquier otra dimensión, usar dict exacto
    return {"width": width, "height": height}


def _extract_first_url(payload: dict, keys=("images", "image", "video", "data")) -> Optional[str]:
    """Extrae la primera URL publica de una respuesta tipica de FAL."""
    if not isinstance(payload, dict):
        return None

    # Caso tipico: {"images": [{"url": "..."}]}
    images = payload.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            return first.get("url") or first.get("href")
        if isinstance(first, str):
            return first

    # Caso tipico: {"video": {"url": "..."}}
    video = payload.get("video")
    if isinstance(video, dict):
        return video.get("url") or video.get("href")
    if isinstance(video, str):
        return video

    # Caso: {"image": {...}}
    image = payload.get("image")
    if isinstance(image, dict):
        return image.get("url") or image.get("href")
    if isinstance(image, str):
        return image

    # Caso: {"data": {...}} (recursivo)
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_first_url(data, keys=keys)

    return None


# =============================================================================
#  Cliente de imagen (Flux)
# =============================================================================

class FalAiImageClient:
    """Genera imagenes con Flux.1 en FAL.AI.

    Parameters
    ----------
    log_callback : callable, optional
        Funcion para logging (recibe un str).
    model_id : str, optional
        Id del modelo en FAL. Por defecto FAL_IMAGE_MODEL env o
        fal-ai/flux/dev.
    """

    DEFAULT_MODEL_ID = "fal-ai/flux/dev"
    FALLBACK_MODEL_ID = "fal-ai/flux/schnell"

    def __init__(self, log_callback=None, model_id: Optional[str] = None):
        self.log_callback = log_callback
        self.model_id = (
            model_id
            or os.getenv("FAL_IMAGE_MODEL")
            or self.DEFAULT_MODEL_ID
        ).strip()
        self.last_error: Optional[str] = None
        self.available = bool(fal_client is not None and _ensure_fal_key())

        if fal_client is None:
            self._log("[FAL] SDK fal_client no instalado (pip install fal-client)")
        elif not self.available:
            self._log("[FAL] FAL_KEY no configurada (revisa .env / .env.txt)")
        else:
            self._log(f"[FAL] ImageClient listo ({self.model_id})")

    # ------------------------------------------------------------------ log

    def _log(self, message: str) -> None:
        if self.log_callback:
            try:
                self.log_callback(message)
                return
            except Exception:
                pass
        print(message)

    # ------------------------------------------------------------------ api

    def generate_image(
        self,
        prompt: str,
        width: int = 1920,
        height: int = 1080,
        output_path: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        style: Optional[str] = None,
        num_inference_steps: Optional[int] = None,
        return_url: bool = False,
    ) -> Optional[str]:
        """Genera una imagen con Flux y la descarga localmente.

        Returns
        -------
        str | None
            Si return_url=False: ruta local del archivo descargado.
            Si return_url=True: URL publica (util para encadenar con I2V).
            None si hubo error.
        """
        self.last_error = None
        if not self.available:
            self.last_error = "FAL no disponible (SDK o key faltante)"
            return None

        prompt_text = self._compose_prompt(prompt, style)
        if not prompt_text:
            self.last_error = "prompt vacio"
            return None

        # Flux schnell trabaja mejor con menos steps; dev tolera mas
        if num_inference_steps is None:
            num_inference_steps = 4 if "schnell" in self.model_id else 28

        args = {
            "prompt": prompt_text,
            "image_size": _resolve_image_size(width, height),
            "num_inference_steps": int(num_inference_steps),
            "guidance_scale": 3.5,
            "num_images": 1,
            "enable_safety_checker": False,
        }
        if negative_prompt and str(negative_prompt).strip():
            args["negative_prompt"] = str(negative_prompt).strip()

        try:
            result = fal_client.subscribe(self.model_id, arguments=args)
        except Exception as exc:
            self.last_error = str(exc)
            self._log(f"[FAL] Error generando imagen ({self.model_id}): {exc}")
            return None

        image_url = _extract_first_url(result)
        if not image_url:
            self.last_error = "FAL no devolvio URL de imagen"
            self._log(f"[FAL] {self.last_error}")
            return None

        if return_url:
            return image_url

        # Descargar a disco
        if not output_path:
            output_path = str(Path("auto_videos/temp/fal_images") / f"fal_{int(time.time())}.png")
        downloaded = _download_url_to_file(image_url, output_path)
        if not downloaded:
            # Si la descarga fallo pero tenemos URL, devolvemos la URL
            self.last_error = "No se pudo descargar la imagen; devuelvo URL"
            self._log(f"[FAL] {self.last_error}")
            return image_url
        return downloaded

    # ---------------------------------------------------------------- utils

    @staticmethod
    def _compose_prompt(prompt: str, style: Optional[str]) -> str:
        parts = [str(prompt or "").strip()]
        if style and str(style).strip().lower() not in {"photorealism", "realistic image", "realistic"}:
            parts.append(f"Visual style: {style}.")
        return "\n".join(part for part in parts if part)


# =============================================================================
#  Cliente de video (Image-to-Video: Kling / Luma)
# =============================================================================

class FalAiVideoClient:
    """Genera clips de video con Kling v1.5 o Luma Dream Machine en FAL.AI.

    El flujo recomendado es Image-to-Video (se pasa una URL de imagen generada
    por Flux previamente). Tambien se expone `text_to_video()` para casos
    especiales.
    """

    # Endpoints oficiales de FAL para Image-to-Video
    KLING_I2V_STANDARD = "fal-ai/kling-video/v2.1/standard/image-to-video"
    KLING_I2V_PRO      = "fal-ai/kling-video/v2.1/pro/image-to-video"
    KLING_T2V_STANDARD = "fal-ai/kling-video/v2.1/standard/text-to-video"
    LUMA_I2V           = "fal-ai/luma-dream-machine/image-to-video"
    LUMA_T2V           = "fal-ai/luma-dream-machine"

    def __init__(self, log_callback=None, default_model: Optional[str] = None):
        self.log_callback = log_callback
        raw = (default_model or os.getenv("FAL_VIDEO_MODEL") or "kling-standard").strip().lower()
        self.default_model = raw
        self.last_error: Optional[str] = None
        self.available = bool(fal_client is not None and _ensure_fal_key())

        if fal_client is None:
            self._log("[FAL] SDK fal_client no instalado")
        elif not self.available:
            self._log("[FAL] FAL_KEY no configurada (revisa .env / .env.txt)")
        else:
            self._log(f"[FAL] VideoClient listo (modelo por defecto: {self.default_model})")

    # ------------------------------------------------------------------ log

    def _log(self, message: str) -> None:
        if self.log_callback:
            try:
                self.log_callback(message)
                return
            except Exception:
                pass
        print(message)

    # --------------------------------------------------------------- helpers

    def _resolve_endpoint_i2v(self, model: str) -> Tuple[str, str]:
        """Devuelve (endpoint, nombre_humano) para el modelo solicitado."""
        key = (model or "").strip().lower()
        if key in {"kling", "kling-standard", "kling-std", "kling_v1"}:
            return self.KLING_I2V_STANDARD, "Kling v1.5 Standard"
        if key in {"kling-pro", "kling_pro"}:
            return self.KLING_I2V_PRO, "Kling v1.5 Pro"
        if key in {"luma", "luma-dream", "dream-machine"}:
            return self.LUMA_I2V, "Luma Dream Machine"
        # Si el usuario pasa un endpoint completo, respetarlo
        if key.startswith("fal-ai/"):
            return model, model
        # Default
        return self.KLING_I2V_STANDARD, "Kling v1.5 Standard"

    def _resolve_endpoint_t2v(self, model: str) -> Tuple[str, str]:
        key = (model or "").strip().lower()
        if key in {"luma", "luma-dream", "dream-machine"}:
            return self.LUMA_T2V, "Luma Dream Machine"
        if key.startswith("fal-ai/"):
            return model, model
        return self.KLING_T2V_STANDARD, "Kling v1.5 Standard"

    # ---------------------------------------------------------------- I2V

    def image_to_video(
        self,
        image_url: str,
        prompt: str,
        output_path: str,
        model: Optional[str] = None,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        extra_args: Optional[dict] = None,
    ) -> Optional[str]:
        """Genera un clip I2V a partir de una imagen (url) y lo descarga.

        Parameters
        ----------
        image_url : str
            URL publica (idealmente una de Flux via FAL, pero acepta cualquiera).
        prompt : str
            Prompt de movimiento ("slow zoom", "dust particles", etc.).
        output_path : str
            Ruta donde guardar el MP4 resultante.
        model : str
            'kling' | 'kling-pro' | 'luma' (o endpoint fal-ai/... completo).
        duration : int
            Segundos (5 o 10 tipicamente para Kling).
        aspect_ratio : str
            '16:9', '9:16' o '1:1'.

        Returns
        -------
        str | None
            Ruta local del MP4 o None si fallo.
        """
        self.last_error = None
        if not self.available:
            self.last_error = "FAL no disponible"
            return None
        if not image_url:
            self.last_error = "image_url vacio"
            return None

        endpoint, human_name = self._resolve_endpoint_i2v(model or self.default_model)

        args = {
            "image_url": image_url,
            "prompt": str(prompt or "").strip() or "Maintain visual style, subtle motion",
            "duration": str(int(duration)),
            "aspect_ratio": aspect_ratio,
        }
        if extra_args:
            args.update(extra_args)

        self._log(f"[FAL] {human_name} I2V: enviando ({duration}s, {aspect_ratio})...")
        try:
            result = fal_client.subscribe(endpoint, arguments=args)
        except Exception as exc:
            self.last_error = str(exc)
            self._log(f"[FAL] Error en I2V ({human_name}): {exc}")
            return None

        video_url = _extract_first_url(result)
        if not video_url:
            self.last_error = f"{human_name} no devolvio URL de video"
            self._log(f"[FAL] {self.last_error}")
            return None

        downloaded = _download_url_to_file(video_url, output_path, timeout=300)
        if not downloaded:
            self.last_error = f"No se pudo descargar el video de {human_name}"
            self._log(f"[FAL] {self.last_error}")
            return None

        self._log(f"[FAL] {human_name} OK: {output_path}")
        return downloaded

    # ---------------------------------------------------------------- T2V

    def text_to_video(
        self,
        prompt: str,
        output_path: str,
        model: Optional[str] = None,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        extra_args: Optional[dict] = None,
    ) -> Optional[str]:
        """Genera un clip a partir solo de texto (sin imagen de base)."""
        self.last_error = None
        if not self.available:
            self.last_error = "FAL no disponible"
            return None

        endpoint, human_name = self._resolve_endpoint_t2v(model or self.default_model)

        args = {
            "prompt": str(prompt or "").strip(),
            "duration": str(int(duration)),
            "aspect_ratio": aspect_ratio,
        }
        if extra_args:
            args.update(extra_args)

        self._log(f"[FAL] {human_name} T2V: enviando ({duration}s, {aspect_ratio})...")
        try:
            result = fal_client.subscribe(endpoint, arguments=args)
        except Exception as exc:
            self.last_error = str(exc)
            self._log(f"[FAL] Error en T2V ({human_name}): {exc}")
            return None

        video_url = _extract_first_url(result)
        if not video_url:
            self.last_error = f"{human_name} no devolvio URL de video"
            return None

        downloaded = _download_url_to_file(video_url, output_path, timeout=300)
        if not downloaded:
            self.last_error = f"No se pudo descargar el video de {human_name}"
            return None

        self._log(f"[FAL] {human_name} OK: {output_path}")
        return downloaded


# =============================================================================
#  Factory helpers
# =============================================================================

def build_fal_clients(log_callback=None):
    """Construye (image_client, video_client) y los devuelve como tupla.
    Cualquier cliente cuyo modulo no este disponible se devuelve como None.
    """
    if fal_client is None:
        return None, None
    if not _ensure_fal_key():
        return None, None
    try:
        image_client = FalAiImageClient(log_callback=log_callback)
    except Exception:
        image_client = None
    try:
        video_client = FalAiVideoClient(log_callback=log_callback)
    except Exception:
        video_client = None
    return image_client, video_client


def is_fal_configured() -> bool:
    """True si hay SDK y FAL_KEY disponible."""
    return fal_client is not None and _ensure_fal_key()


__all__ = [
    "FalAiImageClient",
    "FalAiVideoClient",
    "build_fal_clients",
    "is_fal_configured",
    "FAL_PRICES",
]
