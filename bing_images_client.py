# bing_images_client.py
"""
Cliente de busqueda de imagenes sin costo.

Comportamiento actual:
- Usa Openverse (gratis, sin API key) por defecto.
- Puede usar Bing opcionalmente solo si se fuerza con:
  BING_PREFERRED_PROVIDER=bing y BING_IMAGE_SEARCH_KEY configurada.
"""

import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests


class BingImagesClient:
    """
    Cliente de busqueda de imagenes compatible con el codigo legacy.

    Nota:
    - El nombre de clase se mantiene por compatibilidad.
    - El backend recomendado y gratuito es Openverse.
    """

    def __init__(self, gemini_client=None):
        self.api_key = os.getenv("BING_IMAGE_SEARCH_KEY", "").strip()
        self.bing_endpoint = os.getenv("BING_IMAGE_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/images/search").rstrip("/")
        self.openverse_endpoint = os.getenv("OPENVERSE_API_ENDPOINT", "https://api.openverse.org/v1/images/").rstrip("/") + "/"
        self.preferred_provider = os.getenv("BING_PREFERRED_PROVIDER", "openverse").strip().lower()
        self.gemini_client = gemini_client
        self.last_error = ""
        self._request_delay_seconds = 0.35

        self.use_bing_api = bool(self.api_key and self.preferred_provider == "bing")
        self.provider_label = "bing" if self.use_bing_api else "openverse"

        if self.use_bing_api:
            print(" Imagenes: usando Bing API (modo forzado)")
        else:
            print(" Imagenes: usando Openverse (gratis, sin API key)")

    @staticmethod
    def _parse_retry_after_seconds(retry_after_value: str) -> Optional[float]:
        if not retry_after_value:
            return None
        try:
            seconds = float(retry_after_value)
            return seconds if seconds >= 0 else None
        except ValueError:
            return None

    def _request_with_retry(
        self,
        url: str,
        params: Dict,
        headers: Optional[Dict] = None,
        max_attempts: int = 3,
        timeout: int = 15
    ) -> requests.Response:
        backoff_seconds = 1.0
        response = None
        for attempt in range(1, max_attempts + 1):
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                retry_after = self._parse_retry_after_seconds(response.headers.get("Retry-After", ""))
                wait_time = retry_after if retry_after is not None else backoff_seconds
                print(f"   ️ API {response.status_code}, reintentando en {wait_time:.1f}s...")
                time.sleep(wait_time)
                backoff_seconds = min(backoff_seconds * 2, 8.0)
                continue
            return response
        return response

    def _extract_api_error(self, response: requests.Response) -> str:
        fallback = f"HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            return fallback

        error_obj = payload.get("error", {})
        if isinstance(error_obj, dict):
            code = str(error_obj.get("code", "")).strip()
            message = str(error_obj.get("message", "")).strip()
            if message:
                return f"{message}" + (f" (code: {code})" if code else "")

        message = str(payload.get("message", "")).strip()
        return message or fallback

    def suggest_search_terms_with_ai(self, visual_prompt: str, narration_text: str = "") -> str:
        if not self.gemini_client:
            return visual_prompt

        try:
            prompt = f"""Convierte este prompt en terminos de busqueda para imagenes reales.

REGLAS:
1. Prioriza hechos concretos de la narracion.
2. Maximo 8 palabras.
3. Quita palabras artisticas.
4. Incluye fechas si existen.
5. Solo salida final, sin explicaciones.

Visual: "{visual_prompt}"
Narracion: "{narration_text}"
"""
            response = self.gemini_client._generate(prompt)
            if not response or response == "ERROR_QUOTA_EXCEEDED":
                return visual_prompt
            text = response.strip().replace('"', "").replace("'", "").replace("`", "")
            text = text.split("\n")[0].strip()
            words = text.split()
            if len(words) > 8:
                text = " ".join(words[:8])
            return text or visual_prompt
        except Exception:
            return visual_prompt

    def _search_bing(self, query: str, limit: int) -> List[Dict]:
        if not self.api_key:
            self.last_error = "BING_IMAGE_SEARCH_KEY no configurada"
            return []

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "User-Agent": "VideoOptimizerPro/1.0",
        }

        all_images: List[Dict] = []
        seen_urls = set()
        offset = 0

        while len(all_images) < limit and offset < 150:
            remaining = max(1, min(35, limit - len(all_images)))
            params = {
                "q": query,
                "count": remaining,
                "offset": offset,
                "safeSearch": "Moderate",
                "mkt": "en-US",
                "imageType": "Photo",
            }
            response = self._request_with_retry(self.bing_endpoint, params=params, headers=headers, max_attempts=3, timeout=15)
            if response.status_code != 200:
                self.last_error = self._extract_api_error(response)
                if response.status_code in (401, 403):
                    return []
                response.raise_for_status()

            data = response.json()
            items = data.get("value", [])
            if not items:
                break

            for item in items:
                image_url = item.get("contentUrl", "")
                if not image_url or image_url in seen_urls:
                    continue
                seen_urls.add(image_url)
                all_images.append({
                    "title": item.get("name", ""),
                    "url": image_url,
                    "thumbnail": item.get("thumbnailUrl", image_url),
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                    "source": item.get("hostPageDisplayUrl", "bing.com"),
                    "context": item.get("hostPageUrl", ""),
                    "rights": item.get("license", ""),
                    "license": item.get("license", ""),
                    "relevance_score": 10.0,
                })

            if len(items) < remaining:
                break
            offset += len(items)
            time.sleep(self._request_delay_seconds)

        return all_images[:limit]

    def _search_openverse(self, query: str, limit: int) -> List[Dict]:
        headers = {"User-Agent": "VideoOptimizerPro/1.0"}
        all_images: List[Dict] = []
        seen_urls = set()
        page = 1

        while len(all_images) < limit and page <= 8:
            remaining = max(1, min(20, limit - len(all_images)))
            params = {
                "q": query,
                "page": page,
                "page_size": remaining,
                "mature": "false",
            }

            response = self._request_with_retry(self.openverse_endpoint, params=params, headers=headers, max_attempts=3, timeout=18)
            if response.status_code != 200:
                self.last_error = self._extract_api_error(response)
                response.raise_for_status()

            payload = response.json() if response.content else {}
            results = payload.get("results", [])
            if not results:
                break

            for item in results:
                image_url = str(item.get("url", "")).strip()
                if not image_url or image_url in seen_urls:
                    continue
                seen_urls.add(image_url)

                license_name = str(item.get("license", "")).strip()
                license_version = str(item.get("license_version", "")).strip()
                rights = f"{license_name} {license_version}".strip()

                all_images.append({
                    "title": item.get("title") or item.get("id") or "Openverse image",
                    "url": image_url,
                    "thumbnail": item.get("thumbnail") or image_url,
                    "width": int(item.get("width") or 0),
                    "height": int(item.get("height") or 0),
                    "source": item.get("source") or "openverse",
                    "context": item.get("foreign_landing_url") or item.get("detail_url") or "",
                    "rights": rights,
                    "license": license_name,
                    "license_url": item.get("license_url", ""),
                    "creator": item.get("creator", ""),
                    "relevance_score": 10.0,
                })

            page += 1
            time.sleep(self._request_delay_seconds)

        return all_images[:limit]

    def search_images(self, query: str, limit: int = 10, narration_text: str = "") -> List[Dict]:
        self.last_error = ""
        try:
            if self.gemini_client:
                query = self.suggest_search_terms_with_ai(query, narration_text)
                print(f"    IA mejoro terminos: '{query}'")

            # 1) Provider principal
            if self.use_bing_api:
                images = self._search_bing(query=query, limit=limit)
                if images:
                    print(f"    Bing: {len(images)} imagenes encontradas para '{query}'")
                    return images
                # 2) Fallback gratis si Bing falla
                print("   ️ Bing sin resultados, usando Openverse (gratis)...")

            images = self._search_openverse(query=query, limit=limit)
            print(f"    Openverse: {len(images)} imagenes encontradas para '{query}'")
            return images
        except requests.exceptions.RequestException as e:
            if not self.last_error:
                self.last_error = str(e)
            print(f"    Error en busqueda de imagenes: {self.last_error}")
            return []
        except Exception as e:
            self.last_error = str(e)
            print(f"    Error inesperado en busqueda: {self.last_error}")
            return []

    def search_and_download_image(
        self,
        visual_prompt: str,
        narration_text: str = "",
        output_dir: Optional[str] = None,
        filename: Optional[str] = None
    ) -> Optional[Dict]:
        images = self.search_images(visual_prompt, limit=5, narration_text=narration_text)
        if not images:
            return None

        selected_image = images[0]
        if output_dir and filename:
            try:
                output_path = Path(output_dir) / f"{filename}.jpg"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                response = requests.get(selected_image["url"], timeout=20, stream=True, headers={"User-Agent": "VideoOptimizerPro/1.0"})
                response.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                selected_image["path"] = str(output_path)
                print(f"          Imagen descargada: {selected_image.get('title', '')[:50]}")
            except Exception as e:
                print(f"         ️ Error descargando imagen: {e}")
        return selected_image
