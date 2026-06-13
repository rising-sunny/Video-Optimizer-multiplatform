# video_generation_manager.py
"""
Gestor de generación de video e imágenes
Maneja la generación de contenido visual usando FAL.AI (Flux+Kling/Luma),
Runway (Gen-3/Veo) y fuentes manuales.
"""

import os
import time
import requests
from typing import Optional, Dict, List
from pathlib import Path

# Verificar dependencias opcionales
RUNWAY_AVAILABLE = False
try:
    from runwayml import RunwayML  # type: ignore
    RUNWAY_AVAILABLE = True
except ImportError:
    RUNWAY_AVAILABLE = False

FAL_SDK_AVAILABLE = False
try:
    import fal_client  # type: ignore
    FAL_SDK_AVAILABLE = True
except ImportError:
    FAL_SDK_AVAILABLE = False


class VideoGenerationManager:
    """
    Gestor de generación de video con sistema de fallback.
    Proveedores: FAL.AI (Kling/Luma image-to-video o text-to-video) y Runway Gen-3/Veo.
    """

    def __init__(self, log_callback=None, runway_client=None,
                 google_images_client=None,
                 wikimedia_client=None, generated_media_dir=None,
                 fal_image_client=None, fal_video_client=None):
        """
        Inicializa el gestor de generación.

        Args:
            log_callback: Función para logging (opcional)
            runway_client: Cliente de Runway (opcional)
            google_images_client: Cliente de Openverse (Gratis) (opcional)
            wikimedia_client: Cliente de Wikimedia (opcional)
            generated_media_dir: Directorio para guardar medios generados
            fal_image_client: Cliente FalAiImageClient (Flux) para fase 1 I2V
            fal_video_client: Cliente FalAiVideoClient (Kling/Luma) para fase 2 I2V
        """
        self.log = log_callback or (lambda msg: print(msg))
        self.runway_client = runway_client
        self.google_images_client = google_images_client
        self.wikimedia_client = wikimedia_client
        self.generated_media_dir = generated_media_dir or Path("auto_videos/temp/generated_media")
        self.fal_image_client = fal_image_client
        self.fal_video_client = fal_video_client

    # ------------------------------------------------------------------ log
    # (usa self.log inyectado)

    # ================================================================
    #  Legacy helpers
    # ================================================================

    def generate_video_with_leonardo_motion(self, image_path, output_path, duration=4):
        """Recraft no soporta generación de video; mantener para compatibilidad."""
        self.log("      Video con Leonardo Motion desactivado: backend actual es Recraft (solo imagenes)")
        return None

    # ================================================================
    #  FAL.AI (Flux + Kling/Luma)
    # ================================================================

    def _upload_image_to_fal(self, image_path: str) -> Optional[str]:
        """
        Sube una imagen local a la CDN de FAL para obtener URL pública.
        Necesario porque Kling/Luma requieren URL, no bytes.
        """
        if not FAL_SDK_AVAILABLE or not image_path or not os.path.exists(image_path):
            return None
        try:
            url = fal_client.upload_file(image_path)
            if url:
                return url
        except Exception as exc:
            self.log(f"      [FAL] upload_file falló: {exc}")
        return None

    def generate_video_with_fal(self, prompt: str, output_path: str,
                                is_vertical: bool = False,
                                duration: int = 5,
                                image_path: Optional[str] = None,
                                image_url: Optional[str] = None,
                                model: str = "kling",
                                generate_image_if_missing: bool = True) -> Optional[str]:
        """
        Genera un clip MP4 con el flujo Image-to-Video de FAL.AI.

        Prioriza I2V (Kling o Luma) porque da mejor consistencia visual.
        Si no se pasa imagen y `generate_image_if_missing=True`, crea una
        con Flux y la encadena al motor de video.

        Args:
            prompt: prompt de movimiento (ej. "slow dramatic zoom, dust particles")
            output_path: ruta MP4 destino
            is_vertical: True → 9:16, False → 16:9
            duration: 5 ó 10 típicamente
            image_path: ruta local de imagen base (se sube a FAL si hace falta)
            image_url: alternativa — URL pública ya existente
            model: 'kling' | 'kling-pro' | 'luma'
            generate_image_if_missing: usar Flux para crear la imagen si falta

        Returns:
            Ruta al MP4 local o None si falló.
        """
        if not self.fal_video_client or not getattr(self.fal_video_client, 'available', False):
            self.log("      [FAL] VideoClient no disponible (revisa FAL_KEY y SDK)")
            return None

        aspect_ratio = "9:16" if is_vertical else "16:9"

        # --- Resolver URL de imagen de base ---
        if not image_url and image_path and os.path.exists(image_path):
            self.log(f"      [FAL] Subiendo imagen local a CDN de FAL...")
            image_url = self._upload_image_to_fal(image_path)
            if not image_url:
                self.log(f"      [FAL] No se pudo subir {image_path}; intentando T2V...")

        # Si aún no hay imagen y está permitido, generarla con Flux
        if not image_url and generate_image_if_missing:
            if self.fal_image_client and getattr(self.fal_image_client, 'available', False):
                self.log("      [FAL] Generando imagen base con Flux...")
                w, h = (1080, 1920) if is_vertical else (1920, 1080)
                image_url = self.fal_image_client.generate_image(
                    prompt=prompt,
                    width=w,
                    height=h,
                    return_url=True,  # recibimos URL directamente
                )
                if not image_url:
                    last_err = getattr(self.fal_image_client, 'last_error', None)
                    if last_err:
                        self.log(f"      [FAL] Flux falló: {last_err}")

        # --- Image-to-Video ---
        if image_url:
            result = self.fal_video_client.image_to_video(
                image_url=image_url,
                prompt=prompt,
                output_path=output_path,
                model=model,
                duration=duration,
                aspect_ratio=aspect_ratio,
            )
            if result:
                return result
            # Cae al T2V solo si falló
            self.log("      [FAL] I2V falló, probando T2V como último recurso...")

        # --- Text-to-Video (último recurso sin imagen) ---
        return self.fal_video_client.text_to_video(
            prompt=prompt,
            output_path=output_path,
            model=model,
            duration=duration,
            aspect_ratio=aspect_ratio,
        )

    # ================================================================
    #  Runway Gen-3 / Veo
    # ================================================================

    def generate_video_with_runway(self, prompt, output_path, is_vertical=False, duration=4):
        """Genera video desde prompt usando Runway Gen-3"""
        try:
            if not self.runway_client:
                return None

            ratio = '720:1280' if is_vertical else '1280:720'

            # Runway tiene un límite de 1000 caracteres para promptText
            max_prompt_length = 1000
            if len(prompt) > max_prompt_length:
                truncated_prompt = prompt[:max_prompt_length]
                last_space = truncated_prompt.rfind(' ')
                if last_space > max_prompt_length * 0.8:
                    truncated_prompt = truncated_prompt[:last_space]
                prompt = truncated_prompt

            # Modelos válidos según la API
            models_to_try = ['veo3.1_fast', 'veo3.1', 'gen3a_turbo', 'veo3', 'gen4.5']

            for model_name in models_to_try:
                try:
                    self.log(f"       Runway Gen-3 ({model_name}): generando video...")

                    task = self.runway_client.text_to_video.create(
                        model=model_name,
                        prompt_text=prompt,
                        duration=duration,
                        ratio=ratio
                    ).wait_for_task_output()

                    # Descargar video
                    video_data = requests.get(task.output.url).content
                    with open(output_path, 'wb') as f:
                        f.write(video_data)

                    self.log(f"       Runway Gen-3 ({model_name}) exitoso")
                    return output_path

                except Exception as model_error:
                    error_str = str(model_error)
                    if 'not available' in error_str.lower() or '403' in error_str:
                        self.log(f"      ️ Modelo {model_name} no disponible, intentando siguiente...")
                        continue
                    else:
                        raise model_error

            self.log(f"       Todos los modelos de Runway fallaron")
            return None

        except Exception as e:
            self.log(f"       Runway Gen-3 error: {e}")
            return None

    # ================================================================
    #  Fallback orquestado
    # ================================================================

    def generate_video_with_fallback(self, prompt, output_path, is_vertical=False, duration=4,
                                     preferred_provider='fal', image_path=None,
                                     image_url=None, fal_model='kling'):
        """
        Genera video con sistema de fallback en cascada.

        Args:
            prompt: Prompt visual para el video
            output_path: Ruta donde guardar el video
            is_vertical: Si el video debe ser vertical (9:16)
            duration: Duración en segundos
            preferred_provider: 'fal' | 'runway' | 'auto'
            image_path: Ruta local a imagen base (FAL I2V la sube)
            image_url: URL pública alternativa a image_path (para FAL I2V)
            fal_model: 'kling' | 'kling-pro' | 'luma' (solo aplica a FAL)

        Returns:
            str: Ruta al video generado, o None si todos fallaron.
        """
        pref = str(preferred_provider or 'fal').strip().lower()
        if pref in {'fal', 'fal_ai', 'flux', 'kling', 'luma', 'auto', ''}:
            providers = ['fal', 'runway']
        elif pref == 'runway':
            providers = ['runway', 'fal']
        else:
            providers = ['fal', 'runway']

        for provider in providers:
            if provider == 'fal' and self.fal_video_client and getattr(self.fal_video_client, 'available', False):
                result = self.generate_video_with_fal(
                    prompt=prompt,
                    output_path=output_path,
                    is_vertical=is_vertical,
                    duration=duration,
                    image_path=image_path,
                    image_url=image_url,
                    model=fal_model,
                )
                if result:
                    return result
                self.log("      ️ FAL falló, intentando siguiente proveedor...")
            elif provider == 'runway' and self.runway_client:
                result = self.generate_video_with_runway(prompt, output_path, is_vertical, duration)
                if result:
                    return result
                self.log("      ️ Runway falló, intentando siguiente proveedor...")

        self.log("       TODOS los proveedores de video fallaron")
        return None
