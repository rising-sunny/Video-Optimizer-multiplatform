# recraft_client.py
# Cliente para interactuar con la API de Recraft para generación de imágenes

import os
import requests
from pathlib import Path
from typing import Optional, Dict
import time
from collections import deque

try:
    from recraft_style_catalog import normalize_recraft_style, to_recraft_style_family
except Exception as _catalog_import_error:
    print(
        f"️ No se pudo importar recraft_style_catalog ({_catalog_import_error}). "
        "Aplicando normalización de estilos mínima."
    )

    def normalize_recraft_style(style: str) -> str:
        value = (style or "").strip().casefold()
        if value in {"", "photorealism", "realistic", "realistic_image", "fotorrealista"}:
            return "Photorealism"
        if "vector" in value:
            return "Vector art"
        if value in {"icon", "logo", "pictogram"}:
            return "Icon" if value == "icon" else value.capitalize()
        if "kawaii" in value or "anime" in value:
            return "Kawaii"
        return "Illustration"

    def to_recraft_style_family(style: str) -> str:
        normalized = normalize_recraft_style(style)
        if normalized in {"Icon", "Logo", "Pictogram"}:
            return "Icon"
        if normalized == "Vector art":
            return "Vector art"
        if normalized == "Photorealism":
            return "Photorealism"
        return "Illustration"

# ========== Cargar variables de entorno ==========
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv es opcional

# Cargar API Key (DESPUÉS de load_dotenv)
RECRAFT_API_KEY = os.getenv("RECRAFT_API_KEY")

# Tamaños válidos para Recraft V3 según documentación oficial
# https://www.recraft.ai/docs/api-reference/appendix
RECRAFT_V3_VALID_SIZES = [
    (1024, 1024),  # 1:1 cuadrado
    (1365, 1024),  # ~4:3 landscape
    (1024, 1365),  # ~3:4 portrait
    (1536, 1024),  # 3:2 landscape
    (1024, 1536),  # 2:3 portrait
    (1820, 1024),  # ~16:9 landscape (ideal para video horizontal)
    (1024, 1820),  # ~9:16 portrait (ideal para video vertical)
    (2048, 1024),  # 2:1 landscape
    (1024, 2048),  # 1:2 portrait
    (1434, 1024),  # ~1.4:1 landscape
    (1024, 1434),  # ~1:1.4 portrait
    (1280, 1024),  # 5:4 landscape
    (1024, 1280),  # 4:5 portrait
    (1707, 1024),  # ~5:3 landscape
    (1024, 1707),  # ~3:5 portrait
]

class RecraftClient:
    """
    Cliente para interactuar con la API de Recraft para generación de imágenes.
    Recraft ofrece generación de imágenes de alta calidad con varios estilos.
    """
    
    def __init__(self, log_callback=None):
        # Leer desde entorno en tiempo de ejecución para soportar cambios dinámicos.
        self.api_key = os.getenv("RECRAFT_API_KEY") or RECRAFT_API_KEY
        self._log = log_callback if log_callback else print  # Usar callback o print por defecto
        # URL oficial según documentación: https://www.recraft.ai/docs/api-reference/getting-started
        # La documentación oficial especifica: https://external.api.recraft.ai/v1
        self.base_url = "https://external.api.recraft.ai/v1"
        self.current_base_url = self.base_url
        
        # Rate limiting: Recraft permite 100 peticiones por minuto según documentación
        self.max_requests_per_minute = 100
        self.request_times = deque()  # Cola para rastrear tiempos de peticiones
        self.min_delay_between_requests = 0.6  # Delay mínimo entre peticiones (600ms = ~100/min)
        
        if not self.api_key:
            self._log("️ ADVERTENCIA: RECRAFT_API_KEY no encontrada en .env")
            self._log("   Configura RECRAFT_API_KEY en tu archivo .env")
        else:
            self._log(" Cliente Recraft inicializado")

    def _get_closest_valid_size(self, width: int, height: int) -> tuple:
        """
        Encuentra el tamaño válido más cercano para Recraft V3 manteniendo la orientación.

        Args:
            width: Ancho solicitado
            height: Alto solicitado

        Returns:
            Tupla (width, height) con el tamaño válido más cercano
        """
        # Verificar si ya es un tamaño válido
        if (width, height) in RECRAFT_V3_VALID_SIZES:
            return (width, height)

        # Determinar orientación
        is_landscape = width > height
        is_portrait = height > width
        is_square = width == height

        # Calcular aspect ratio solicitado
        requested_ratio = width / height if height > 0 else 1

        best_size = None
        best_score = float('inf')

        for valid_w, valid_h in RECRAFT_V3_VALID_SIZES:
            valid_is_landscape = valid_w > valid_h
            valid_is_portrait = valid_h > valid_w
            valid_is_square = valid_w == valid_h

            # Priorizar mantener la orientación
            orientation_match = (
                (is_landscape and valid_is_landscape) or
                (is_portrait and valid_is_portrait) or
                (is_square and valid_is_square)
            )

            # Calcular diferencia de aspect ratio
            valid_ratio = valid_w / valid_h
            ratio_diff = abs(requested_ratio - valid_ratio)

            # Calcular diferencia de área (preferir tamaños similares)
            area_diff = abs((width * height) - (valid_w * valid_h)) / 1000000

            # Score: priorizar orientación, luego ratio, luego área
            orientation_penalty = 0 if orientation_match else 10
            score = orientation_penalty + ratio_diff + (area_diff * 0.1)

            if score < best_score:
                best_score = score
                best_size = (valid_w, valid_h)

        return best_size if best_size else (1024, 1024)

    @staticmethod
    def _trim_text(text: str, max_chars: int) -> str:
        clean = str(text or "").strip()
        if len(clean) <= max_chars:
            return clean
        trimmed = clean[:max_chars].rsplit(" ", 1)[0].rstrip(", ")
        return trimmed or clean[:max_chars].rstrip(", ")

    @classmethod
    def _compose_prompt_with_negative(cls, prompt: str, negative_prompt: str = "",
                                      max_chars: int = 1000,
                                      preferred_negative_budget: int = 220) -> str:
        prompt_text = str(prompt or "").strip()
        negative_text = str(negative_prompt or "").strip()
        if not negative_text:
            return cls._trim_text(prompt_text, max_chars)

        avoid_prefix = "\nAvoid: "
        reserved_negative = min(max(80, preferred_negative_budget), len(negative_text))
        prompt_budget = max(260, max_chars - len(avoid_prefix) - reserved_negative)
        prompt_text = cls._trim_text(prompt_text, prompt_budget)

        available_chars = max(0, max_chars - len(prompt_text) - len(avoid_prefix))
        if available_chars <= 20:
            return cls._trim_text(prompt_text, max_chars)

        negative_text = cls._trim_text(negative_text, available_chars)
        return f"{prompt_text}{avoid_prefix}{negative_text}".rstrip()

    def generate_image(
        self,
        prompt: str,
        style: str = "realistic",
        width: int = 1024,
        height: int = 1024,
        negative_prompt: str = "",
        num_images: int = 1,
        output_path: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Genera una imagen usando la API de Recraft.
        
        Args:
            prompt: Descripción de la imagen a generar
            style: Estilo de la imagen (realistic, vector, illustration, 3d, etc.)
            width: Ancho de la imagen
            height: Alto de la imagen
            negative_prompt: Qué evitar en la imagen
            num_images: Número de imágenes a generar (1-4)
            output_path: Ruta donde guardar la imagen (opcional)
            
        Returns:
            Diccionario con información de la imagen generada, o None si falla
        """
        if not self.api_key:
            self._log(" Recraft: API key no configurada")
            return None
        
        try:
            # Recraft valida longitud de prompt entre 1 y 1000 caracteres.
            prompt = self._compose_prompt_with_negative(prompt, negative_prompt)
            if len(prompt) > 1000:
                self._log(f"   ️ Prompt demasiado largo ({len(prompt)}), truncando a 1000 caracteres")
                prompt = prompt[:1000].rstrip()
            if not prompt:
                self._log("    Prompt vacío para Recraft")
                return None

            # Rate limiting: Asegurar que no excedamos 100 peticiones por minuto
            current_time = time.time()
            
            # Limpiar peticiones antiguas (más de 1 minuto)
            while self.request_times and current_time - self.request_times[0] > 60:
                self.request_times.popleft()
            
            # Si estamos cerca del límite, esperar
            if len(self.request_times) >= self.max_requests_per_minute:
                wait_time = 60 - (current_time - self.request_times[0]) + 1  # Esperar hasta que expire la ventana
                if wait_time > 0:
                    self._log(f"    Rate limit alcanzado ({len(self.request_times)}/100 por minuto). Esperando {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    # Limpiar después de esperar
                    current_time = time.time()
                    while self.request_times and current_time - self.request_times[0] > 60:
                        self.request_times.popleft()
            
            # Asegurar delay mínimo entre peticiones
            if self.request_times:
                time_since_last = current_time - self.request_times[-1]
                if time_since_last < self.min_delay_between_requests:
                    sleep_time = self.min_delay_between_requests - time_since_last
                    time.sleep(sleep_time)
                    current_time = time.time()
            
            # Registrar esta petición
            self.request_times.append(current_time)
            
            self._log(f"    Generando imagen con Recraft: '{prompt[:50]}...'")
            
            # Headers según documentación oficial
            # https://www.recraft.ai/docs/api-reference/getting-started
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            # Siempre usar realistic_image (máxima fidelidad al prompt, sin dirección artística forzada)
            style_used = "realistic_image"

            # Ajustar dimensiones a tamaños válidos para Recraft V3
            original_size = (width, height)
            adjusted_width, adjusted_height = self._get_closest_valid_size(width, height)

            if (adjusted_width, adjusted_height) != original_size:
                self._log(f"    Ajustando tamaño: {width}x{height} -> {adjusted_width}x{adjusted_height} (Recraft V3)")

            # Construir tamaño según documentación (formato "WIDTHxHEIGHT")
            size_str = f"{adjusted_width}x{adjusted_height}"
            
            # Payload según documentación oficial
            # Ejemplo oficial: {"prompt": "...", "style": "realistic_image", "size": "1280x1024", "model": "recraftv3"}
            data = {
                "prompt": prompt,
                "style": style_used,
                "size": size_str,
            }
            
            # Endpoint oficial según documentación
            # https://www.recraft.ai/docs/api-reference/guides
            endpoint = "/images/generations"  # La base URL ya incluye /v1
            
            # Construir URL completa según documentación oficial
            url = f"{self.base_url}{endpoint}"
            
            # Hacer la petición POST según documentación oficial
            # https://www.recraft.ai/docs/api-reference/guides
            self._log(f"    URL: {url}")
            self._log(f"    Payload: prompt='{prompt[:50]}...', style={style_used}, size={size_str}, model=auto")
            response = requests.post(url, headers=headers, json=data, timeout=60)
            
            if response.status_code == 200:
                self._log(f"    Petición exitosa a Recraft API")
            elif response.status_code == 401:
                # API key inválida
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", "") if isinstance(error_data.get("error"), dict) else error_data.get("error", "")
                    if error_msg:
                        raise requests.exceptions.RequestException(f"Recraft API: API Key inválida o expirada. {error_msg}")
                except requests.exceptions.RequestException:
                    raise
                except:
                    pass
                raise requests.exceptions.RequestException(f"Recraft API: API Key inválida o expirada (401)")
            elif response.status_code == 400:
                # Bad Request - formato incorrecto.
                # Compatibilidad: si falla un estilo curado, reintentar con su estilo base.
                fallback_family = to_recraft_style_family(style_used)
                if fallback_family and fallback_family != style_used:
                    self._log(f"   ️ Reintentando con estilo base: {fallback_family}")
                    data["style"] = fallback_family
                    response = requests.post(url, headers=headers, json=data, timeout=60)
                    if response.status_code == 200:
                        style_used = fallback_family
                    else:
                        data["style"] = style_used

                if response.status_code == 200:
                    self._log(f"    Petición exitosa a Recraft API (fallback de estilo)")
                else:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", "") if isinstance(error_data.get("error"), dict) else error_data.get("error", "")
                        raise requests.exceptions.RequestException(f"Recraft API: Solicitud inválida (400). {error_msg or response.text[:200]}")
                    except requests.exceptions.RequestException:
                        raise
                    except:
                        raise requests.exceptions.RequestException(f"Recraft API: Solicitud inválida (400). {response.text[:200]}")
            elif response.status_code == 429:
                # Rate limit excedido
                error_data = response.json() if response.text else {}
                error_code = error_data.get("code", "")
                error_msg = error_data.get("message", "")
                
                # Calcular tiempo de espera (generalmente 60 segundos para resetear el contador)
                wait_time = 60
                
                # Si hay un header Retry-After, usarlo
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_time = int(retry_after)
                    except:
                        pass
                
                self._log(f"   ️ Rate limit excedido (429). Esperando {wait_time}s antes de reintentar...")
                time.sleep(wait_time)
                
                # Limpiar el registro de peticiones después de esperar
                current_time = time.time()
                while self.request_times and current_time - self.request_times[0] > 60:
                    self.request_times.popleft()
                
                # Reintentar la petición una vez
                self._log(f"    Reintentando petición después de esperar...")
                response = requests.post(url, headers=headers, json=data, timeout=60)
                self.request_times.append(time.time())
                
                if response.status_code != 200:
                    raise requests.exceptions.RequestException(f"Recraft API: Rate limit excedido (429). {error_code or error_msg or 'Demasiadas peticiones'}")
            else:
                response.raise_for_status()
            
            # La respuesta es exitosa, procesar
            result = response.json()
            
            # Recraft puede devolver la imagen en diferentes formatos
            # Intentar obtener la URL de la imagen o los datos base64
            image_url = None
            image_data = None
            
            if "data" in result:
                # Si hay múltiples imágenes, tomar la primera
                if isinstance(result["data"], list) and len(result["data"]) > 0:
                    first_image = result["data"][0]
                    image_url = first_image.get("url") or first_image.get("image_url")
                elif isinstance(result["data"], dict):
                    image_url = result["data"].get("url") or result["data"].get("image_url")
            elif "url" in result:
                image_url = result["url"]
            elif "image_url" in result:
                image_url = result["image_url"]
            
            # Si tenemos una URL, descargar la imagen
            if image_url:
                img_response = requests.get(image_url, timeout=30)
                img_response.raise_for_status()
                image_data = img_response.content
            elif "base64" in result or "image" in result:
                # Si viene en base64
                import base64
                if "base64" in result:
                    image_data = base64.b64decode(result["base64"])
                elif "image" in result:
                    image_data = result["image"]
            
            if not image_data:
                self._log("   ️ Recraft: No se pudo obtener la imagen generada")
                return None
            
            # Guardar imagen si se especifica output_path
            if output_path:
                output_file = Path(output_path)
                output_file.parent.mkdir(parents=True, exist_ok=True)
                with open(output_file, 'wb') as f:
                    f.write(image_data)
                self._log(f"    Imagen generada y guardada: {output_path}")
            
            return {
                "path": output_path if output_path else None,
                "data": image_data,
                "url": image_url,
                "width": adjusted_width,
                "height": adjusted_height,
                "original_width": width,
                "original_height": height,
                "style": style_used,
                "prompt": prompt
            }
            
        except requests.exceptions.RequestException as e:
            self._log(f"    Error en Recraft API: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = error_detail.get("error", {}).get("message", "") if isinstance(error_detail.get("error"), dict) else error_detail.get("error", "")
                    if error_msg:
                        self._log(f"    Detalles: {error_msg}")
                    else:
                        self._log(f"    Detalles: {error_detail}")
                except:
                    self._log(f"    Status: {e.response.status_code}")
                    self._log(f"    Response: {e.response.text[:200]}")
            return None
        except Exception as e:
            self._log(f"    Error inesperado en Recraft: {e}")
            return None
    
    def generate_and_save_image(
        self,
        prompt: str,
        output_dir: str,
        filename: str = None,
        **kwargs
    ) -> Optional[str]:
        """
        Genera una imagen y la guarda en el directorio especificado.
        
        Args:
            prompt: Descripción de la imagen
            output_dir: Directorio donde guardar la imagen
            filename: Nombre del archivo (sin extensión). Si es None, se genera automáticamente
            **kwargs: Parámetros adicionales para generate_image
            
        Returns:
            Ruta completa del archivo guardado, o None si falla
        """
        if filename is None:
            timestamp = int(time.time())
            filename = f"recraft_{timestamp}.png"
        elif not filename.endswith('.png'):
            filename = f"{filename}.png"
        
        output_path = Path(output_dir) / filename
        
        result = self.generate_image(prompt, output_path=str(output_path), **kwargs)
        
        if result and result.get("path"):
            return result["path"]
        return None

