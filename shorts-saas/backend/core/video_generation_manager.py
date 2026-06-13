# video_generation_manager.py
"""
Gestor de generación de video e imágenes
Maneja la generación de contenido visual usando Recraft (vía wrappers) y Runway.
"""

import os
import time
import requests
from typing import Optional, Dict, List
from pathlib import Path

# Verificar dependencias
RUNWAY_AVAILABLE = False

try:
    from runwayml import RunwayML
    RUNWAY_AVAILABLE = True
except ImportError:
    RUNWAY_AVAILABLE = False


class VideoGenerationManager:
    """
    Gestor de generación de video e imágenes con sistema de fallback.
    Maneja múltiples proveedores: Recraft (wrappers compat) y Runway.
    """
    
    def __init__(self, log_callback=None, leonardo_client=None, fal_client=None, 
                 runway_client=None, fal_available=False, google_images_client=None,
                 wikimedia_client=None, generated_media_dir=None):
        """
        Inicializa el gestor de generación.
        
        Args:
            log_callback: Función para logging (opcional)
            leonardo_client: Wrapper compat Leonardo (backend Recraft) (opcional)
            fal_client: Wrapper compat Fal (backend Recraft) (opcional)
            runway_client: Cliente de Runway (opcional)
            fal_available: Si el wrapper compat Fal/Recraft está disponible
            google_images_client: Cliente de Openverse (Gratis) (opcional)
            wikimedia_client: Cliente de Wikimedia (opcional)
            generated_media_dir: Directorio para guardar medios generados
        """
        self.log = log_callback or (lambda msg: print(msg))
        self.leonardo_client = leonardo_client
        self.fal_client = fal_client
        self.runway_client = runway_client
        self.fal_available = fal_available
        self.google_images_client = google_images_client
        self.wikimedia_client = wikimedia_client
        self.generated_media_dir = generated_media_dir or Path("auto_videos/temp/generated_media")
    
    def generate_video_with_leonardo_motion(self, image_path, output_path, duration=4):
        """Recraft no soporta generacion de video; mantener para compatibilidad."""
        self.log("      Video con Leonardo Motion desactivado: backend actual es Recraft (solo imagenes)")
        return None

    def generate_video_with_fal(self, prompt, output_path, is_vertical=False, duration=4):
        """Recraft no soporta generacion de video; mantener para compatibilidad."""
        self.log("      Video con Fal.ai desactivado: backend actual es Recraft (solo imagenes)")
        return None

    def generate_video_with_runway(self, prompt, output_path, is_vertical=False, duration=4):
        """Genera video desde prompt usando Runway Gen-3"""
        try:
            if not self.runway_client:
                return None

            ratio = '720:1280' if is_vertical else '1280:720'

            # Runway tiene un límite de 1000 caracteres para promptText
            # Truncar el prompt si es necesario
            max_prompt_length = 1000
            if len(prompt) > max_prompt_length:
                # Truncar de forma inteligente: mantener palabras completas
                truncated_prompt = prompt[:max_prompt_length]
                last_space = truncated_prompt.rfind(' ')
                if last_space > max_prompt_length * 0.8:  # Si hay un espacio razonable
                    truncated_prompt = truncated_prompt[:last_space]
                prompt = truncated_prompt

            # Intentar con diferentes modelos disponibles (en orden de preferencia)
            # Modelos válidos según la API: gen3a_turbo, gen4.5, veo3, veo3.1, veo3.1_fast
            models_to_try = ['gen3a_turbo', 'veo3.1', 'veo3.1_fast', 'veo3', 'gen4.5']

            for model_name in models_to_try:
                try:
                    self.log(f"      🚀 Runway Gen-3 ({model_name}): generando video...")

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

                    self.log(f"      ✅ Runway Gen-3 ({model_name}) exitoso")
                    return output_path
                    
                except Exception as model_error:
                    error_str = str(model_error)
                    # Si el error indica que el modelo no está disponible, intentar siguiente
                    if 'not available' in error_str.lower() or '403' in error_str:
                        self.log(f"      ⚠️ Modelo {model_name} no disponible, intentando siguiente...")
                        continue
                    else:
                        # Si es otro tipo de error, lanzarlo
                        raise model_error
            
            # Si todos los modelos fallaron
            self.log(f"      ❌ Todos los modelos de Runway fallaron")
            return None

        except Exception as e:
            self.log(f"      ❌ Runway Gen-3 error: {e}")
            return None

    def generate_video_with_fallback(self, prompt, output_path, is_vertical=False, duration=4,
                                    preferred_provider='leonardo', image_path=None):
        """
        Genera video con sistema de fallback en cascada.

        Args:
            prompt: Prompt visual para el video
            output_path: Ruta donde guardar el video
            is_vertical: Si el video debe ser vertical (9:16)
            duration: Duración en segundos
            preferred_provider: 'leonardo', 'runway' o 'fal'
            image_path: Ruta a imagen base (solo para Leonardo Motion)

        Returns:
            str: Ruta al video generado, o None si todos fallaron
        """
        # Definir orden de fallback basado en proveedor preferido
        if preferred_provider == 'leonardo':
            providers = ['leonardo', 'runway', 'fal']
        elif preferred_provider == 'runway':
            providers = ['runway', 'fal', 'leonardo']
        else:  # fal
            providers = ['fal', 'runway', 'leonardo']

        # Intentar con cada proveedor en orden
        for provider in providers:
            if provider == 'leonardo' and self.leonardo_client and image_path:
                result = self.generate_video_with_leonardo_motion(image_path, output_path, duration)
                if result:
                    return result
                self.log(f"      ⚠️ Leonardo falló, intentando siguiente proveedor...")

            elif provider == 'runway' and self.runway_client:
                result = self.generate_video_with_runway(prompt, output_path, is_vertical, duration)
                if result:
                    return result
                self.log(f"      ⚠️ Runway falló, intentando siguiente proveedor...")

            elif provider == 'fal' and self.fal_available:
                result = self.generate_video_with_fal(prompt, output_path, is_vertical, duration)
                if result:
                    return result
                self.log(f"      ⚠️ Fal.ai falló, intentando siguiente proveedor...")

        self.log(f"      ❌ TODOS los proveedores de video fallaron")
        return None





