# wikimedia_client.py
"""
Cliente para buscar y descargar imÃ¡genes/videos de Wikimedia Commons.
Perfecto para contenido histÃ³rico, cientÃ­fico, geogrÃ¡fico y de actualidad.
"""

import requests
import os
from pathlib import Path
from typing import List, Dict, Optional
import urllib.parse
import time


class WikimediaClient:
    """
    Cliente para interactuar con Wikimedia Commons API.

    Fuentes:
    - https://api.wikimedia.org/wiki/Reusing_free_images_and_media_files_with_Python
    - https://www.mediawiki.org/wiki/API:Images
    - https://commons.wikimedia.org/wiki/Commons:API
    """

    def __init__(self, user_agent="VideoOptimizerPro/1.0", gemini_client=None):
        self.base_url = "https://commons.wikimedia.org/w/api.php"
        self.file_url_base = "https://api.wikimedia.org/core/v1/commons/file/"
        self.headers = {
            'User-Agent': user_agent
        }
        self.gemini_client = gemini_client  # Cliente de Gemini para mejorar bÃºsquedas
        self.thumb_width = self._safe_int(os.getenv("WIKIMEDIA_THUMB_WIDTH"), 320, min_value=240, max_value=1600)
        self.search_delay_seconds = self._safe_float(os.getenv("WIKIMEDIA_SEARCH_DELAY_SECONDS"), 0.45, min_value=0.0, max_value=5.0)

    @staticmethod
    def _safe_int(value: Optional[str], default: int, min_value: int, max_value: int) -> int:
        """Convierte string a int con lÃ­mites seguros."""
        try:
            parsed = int(value) if value is not None else default
        except (TypeError, ValueError):
            parsed = default
        return max(min_value, min(parsed, max_value))

    @staticmethod
    def _safe_float(value: Optional[str], default: float, min_value: float, max_value: float) -> float:
        """Convierte string a float con lÃ­mites seguros."""
        try:
            parsed = float(value) if value is not None else default
        except (TypeError, ValueError):
            parsed = default
        return max(min_value, min(parsed, max_value))

    @staticmethod
    def _parse_retry_after_seconds(retry_after_value: str) -> Optional[float]:
        """Convierte Retry-After a segundos si estÃ¡ disponible."""
        if not retry_after_value:
            return None
        try:
            seconds = float(retry_after_value)
            if seconds >= 0:
                return seconds
        except ValueError:
            return None
        return None

    def _request_with_retry(
        self,
        url: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        stream: bool = False,
        timeout: int = 10,
        max_attempts: int = 3,
        retry_statuses: Optional[tuple] = None,
        max_retry_after_seconds: float = 10.0
    ) -> requests.Response:
        """Realiza requests con reintentos ante errores temporales."""
        backoff_seconds = 1.0
        last_exception = None
        response = None
        if retry_statuses is None:
            retry_statuses = (429, 500, 502, 503, 504)

        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=headers or self.headers,
                    stream=stream,
                    timeout=timeout
                )

                if response.status_code in retry_statuses and attempt < max_attempts:
                    retry_after = self._parse_retry_after_seconds(response.headers.get('Retry-After', ''))
                    if retry_after is not None:
                        wait_time = min(retry_after, max_retry_after_seconds)
                    else:
                        wait_time = backoff_seconds
                    print(
                        f"️ Wikimedia: HTTP {response.status_code}, "
                        f"reintentando en {wait_time:.1f}s (intento {attempt + 1}/{max_attempts})"
                    )
                    time.sleep(wait_time)
                    backoff_seconds = min(backoff_seconds * 2, 8.0)
                    continue

                return response

            except requests.exceptions.Timeout as exc:
                last_exception = exc
                if attempt < max_attempts:
                    print(
                        f"️ Wikimedia: Timeout, reintentando en {backoff_seconds:.1f}s "
                        f"(intento {attempt + 1}/{max_attempts})"
                    )
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 8.0)
                    continue
                raise

            except requests.exceptions.ConnectionError as exc:
                last_exception = exc
                if attempt < max_attempts:
                    print(
                        f"️ Wikimedia: Error de conexión, reintentando en {backoff_seconds:.1f}s "
                        f"(intento {attempt + 1}/{max_attempts})"
                    )
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 8.0)
                    continue
                raise

        if response is not None:
            return response
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("Wikimedia request fallo sin respuesta ni excepcion")

    @staticmethod
    def _build_special_filepath_url(title: str, width: int) -> str:
        """Genera URL estable de preview/descarga por titulo de archivo."""
        if not title:
            return ""
        normalized_title = str(title).replace("File:", "").strip()
        if not normalized_title:
            return ""
        encoded_title = urllib.parse.quote(normalized_title, safe="")
        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded_title}?width={int(width)}"

    @staticmethod
    def _retarget_thumb_width(thumb_url: str, width: int) -> str:
        """Intenta ajustar el ancho de una URL /thumb/.../{N}px-archivo."""
        if not thumb_url or "/thumb/" not in thumb_url:
            return ""
        try:
            marker = "px-"
            idx = thumb_url.rfind(marker)
            if idx <= 0:
                return ""
            start = idx - 1
            while start >= 0 and thumb_url[start].isdigit():
                start -= 1
            start += 1
            if start >= idx:
                return ""
            return f"{thumb_url[:start]}{int(width)}{thumb_url[idx:]}"
        except Exception:
            return ""

    def search_images(self, query: str, limit: int = 10, image_type: str = 'all', narration_text: str = "") -> List[Dict]:
        """
        Busca imÃ¡genes en Wikimedia Commons con scoring de relevancia mejorado.

        Args:
            query: TÃ©rmino de bÃºsqueda (Ej: "Pearl Harbor 1941", "Einstein", "Mars rover")
            limit: NÃºmero mÃ¡ximo de resultados
            image_type: 'all', 'photo', 'drawing', 'historical'
            narration_text: Texto de narraciÃ³n para scoring de relevancia (opcional)

        Returns:
            Lista de diccionarios con informaciÃ³n de las imÃ¡genes, ordenadas por relevancia
        """
        # Estrategias de bÃºsqueda mejoradas
        search_strategies = [
            # Estrategia 1: BÃºsqueda exacta (mÃ¡s precisa)
            query,
            # Estrategia 2: Con comillas para frase exacta (si tiene mÃºltiples palabras)
            f'"{query}"' if len(query.split()) > 1 else query,
            # Estrategia 3: BÃºsqueda con intitle para priorizar tÃ­tulos relevantes
            f'intitle:{query}',
            # Estrategia 4: BÃºsqueda amplia sin restricciones
            query.split()[0] if len(query.split()) > 1 else query,  # Solo primera palabra si hay mÃºltiples
        ]
        
        all_images = []
        seen_urls = set()
        seen_title_signatures = set()
        
        for strategy_idx, search_query in enumerate(search_strategies):
            try:
                # BÃºsqueda usando MediaWiki API con parÃ¡metros mejorados
                params = {
                    'action': 'query',
                    'format': 'json',
                    'generator': 'search',
                    'gsrsearch': search_query,
                    'gsrlimit': limit * 2,  # Obtener mÃ¡s para filtrar despuÃ©s
                    'gsrnamespace': 6,  # Namespace 6 = File: namespace (solo archivos)
                        'prop': 'imageinfo|info',
                        'iiprop': 'url|size|mime|extmetadata|timestamp',
                        'iiurlwidth': self.thumb_width,  # Miniaturas mÃ¡s ligeras para evitar 429 en previews
                        'iiextmetadatafilter': 'ImageDescription|Artist|LicenseShortName|DateTimeOriginal|Categories',
                    }

                response = self._request_with_retry(
                    self.base_url,
                    params=params,
                    headers=self.headers,
                    timeout=12,
                    max_attempts=3
                )
                response.raise_for_status()
                data = response.json()

                if 'query' in data and 'pages' in data['query']:
                    for page_id, page_data in data['query']['pages'].items():
                        # Filtrar solo archivos de imagen
                        if not page_data.get('title', '').startswith('File:'):
                            continue
                        if 'imageinfo' not in page_data:
                            continue
                        
                        img_info = page_data['imageinfo'][0]
                        
                        # Filtrar solo imÃ¡genes (no videos)
                        mime_type = img_info.get('mime', '')
                        if not mime_type.startswith('image/'):
                            continue
                        
                        # Filtrar imÃ¡genes muy pequeÃ±as (probablemente iconos)
                        width = img_info.get('width', 0)
                        height = img_info.get('height', 0)
                        if width < 200 or height < 200:
                            continue

                        # Extraer metadata completa
                        title = page_data.get('title', '').replace('File:', '')
                        description = ''
                        artist = ''
                        license = ''
                        categories = []

                        if 'extmetadata' in img_info:
                            metadata = img_info['extmetadata']
                            if 'ImageDescription' in metadata:
                                description = metadata['ImageDescription'].get('value', '')
                            if 'Artist' in metadata:
                                artist = metadata['Artist'].get('value', '')
                            if 'LicenseShortName' in metadata:
                                license = metadata['LicenseShortName'].get('value', '')

                        # Calcular score de relevancia
                        relevance_score = self._calculate_relevance_score(
                            query, narration_text, title, description
                        )

                        image_data = {
                            'title': title,
                            'description': description,
                            'artist': artist,
                            'license': license,
                            'url': img_info.get('url', ''),
                            'thumburl': img_info.get('thumburl', img_info.get('url', '')),
                            'width': width,
                            'height': height,
                            'size': img_info.get('size', 0),
                            'mime': mime_type,
                            'page_id': page_id,
                            'relevance_score': relevance_score,
                            'search_strategy': strategy_idx + 1
                        }

                        # Evitar duplicados por URL y por tÃ­tulo base
                        image_url = image_data.get('url', '')
                        title_signature = ''.join(ch for ch in title.lower() if ch.isalnum() or ch.isspace()).strip()
                        title_compact = ' '.join(title_signature.split())
                        title_core = ' '.join(title_compact.split()[:6]).strip()
                        dedup_key = title_core or title_compact

                        if image_url and image_url in seen_urls:
                            continue
                        if dedup_key and dedup_key in seen_title_signatures:
                            continue

                        if image_url:
                            seen_urls.add(image_url)
                        if dedup_key:
                            seen_title_signatures.add(dedup_key)
                        all_images.append(image_data)

            except requests.exceptions.Timeout:
                print(f"âš ï¸ Wikimedia: Timeout en bÃºsqueda '{query}' (estrategia {strategy_idx + 1})")
                continue
            except Exception as e:
                print(f"âš ï¸ Wikimedia: Error en estrategia {strategy_idx + 1} para '{query}': {e}")
                continue
            finally:
                # Espaciado leve entre estrategias para no saturar la API
                if self.search_delay_seconds > 0:
                    time.sleep(self.search_delay_seconds)
        
        # Ordenar por relevancia y limitar resultados
        all_images.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        top_images = all_images[:limit]
        
        if top_images:
            print(f"âœ… Wikimedia: {len(top_images)} imÃ¡genes relevantes encontradas para '{query}' (score top: {top_images[0].get('relevance_score', 0):.2f})")
            return top_images
        else:
            print(f"âš ï¸ Wikimedia: Sin resultados relevantes para '{query}' despuÃ©s de {len(search_strategies)} estrategias")
            return []
    
    def _calculate_relevance_score(self, query: str, narration_text: str, title: str, description: str) -> float:
        """
        Calcula un score de relevancia para una imagen basado en la query y narraciÃ³n.
        Mejorado para penalizar imÃ¡genes de perÃ­odos histÃ³ricos incorrectos.
        
        Returns:
            Score de 0.0 a 10.0 (mayor = mÃ¡s relevante)
        """
        score = 0.0
        query_lower = query.lower()
        narration_lower = narration_text.lower() if narration_text else ""
        title_lower = title.lower()
        desc_lower = description.lower()
        combined_text = f"{title_lower} {desc_lower}"
        
        # Extraer palabras clave de la query
        query_words = set(query_lower.split())
        narration_words = set(narration_lower.split()) if narration_text else set()
        
        # Extraer fechas/perÃ­odos de la query y narraciÃ³n
        import re
        query_dates = re.findall(r'\b(19|20)\d{2}\b|\b\d+\s*(bc|ad|ce|bce)\b|\b\d+\s*century\b', query_lower)
        narration_dates = re.findall(r'\b(19|20)\d{2}\b|\b\d+\s*(bc|ad|ce|bce)\b|\b\d+\s*century\b', narration_lower) if narration_text else []
        
        # Score por coincidencias en el tÃ­tulo (mÃ¡s importante)
        title_words = set(title_lower.split())
        title_matches = len(query_words.intersection(title_words))
        score += title_matches * 3.0  # TÃ­tulo es muy importante
        
        # Score por coincidencias en la descripciÃ³n
        desc_words = set(desc_lower.split())
        desc_matches = len(query_words.intersection(desc_words))
        score += desc_matches * 1.5
        
        # Score por coincidencias con la narraciÃ³n (si estÃ¡ disponible)
        if narration_text:
            narration_title_matches = len(narration_words.intersection(title_words))
            narration_desc_matches = len(narration_words.intersection(desc_words))
            score += narration_title_matches * 2.0  # Coincidencias con narraciÃ³n en tÃ­tulo
            score += narration_desc_matches * 1.0  # Coincidencias con narraciÃ³n en descripciÃ³n
        
        # Bonus por frases completas que coinciden
        if query_lower in title_lower:
            score += 5.0  # Frase exacta en tÃ­tulo
        if query_lower in desc_lower:
            score += 3.0  # Frase exacta en descripciÃ³n
        
        # PENALIZACIÃ“N CRÃTICA: ImÃ¡genes de perÃ­odos histÃ³ricos incorrectos
        # Si la query/narraciÃ³n menciona un perÃ­odo antiguo (BC, siglo V a.C., etc.), penalizar imÃ¡genes modernas
        is_ancient_period = any('bc' in q or 'bce' in q or 'century bc' in q or 'ancient' in q for q in [query_lower, narration_lower])
        if is_ancient_period:
            # Penalizar imÃ¡genes del siglo XIX-XXI
            modern_periods = ['19', '20', '21', 'nineteenth', 'twentieth', 'twenty-first', '1800', '1900', '2000']
            if any(period in combined_text for period in modern_periods):
                # Verificar si es una imagen histÃ³rica/documental sobre el tema antiguo (OK) vs imagen moderna (MALO)
                historical_doc_indicators = ['history', 'ancient', 'reconstruction', 'depiction', 'illustration', 'painting of']
                if not any(indicator in combined_text for indicator in historical_doc_indicators):
                    score -= 5.0  # PenalizaciÃ³n fuerte por imagen moderna cuando se busca algo antiguo
        
        # PENALIZACIÃ“N: ImÃ¡genes genÃ©ricas comunes
        generic_terms = ['icon', 'logo', 'symbol', 'map', 'diagram', 'chart', 'graph']
        if any(term in title_lower for term in generic_terms):
            score -= 1.0
        
        # PENALIZACIÃ“N: ImÃ¡genes de lugares modernos cuando se busca algo histÃ³rico
        # Ej: "Marathon" puede traer maratones modernos, no la batalla histÃ³rica
        if 'marathon' in query_lower and 'battle' not in combined_text and '490' not in combined_text:
            if any(term in combined_text for term in ['race', 'running', 'sport', 'athlete', 'modern']):
                score -= 3.0  # Probablemente es una maratÃ³n moderna, no la batalla
        
        # PENALIZACIÃ“N: ImÃ¡genes de lugares modernos cuando se busca algo histÃ³rico
        # Ej: "Thermopylae" puede traer imÃ¡genes modernas del lugar, no de la batalla
        if 'thermopylae' in query_lower and 'battle' not in combined_text and '480' not in combined_text:
            if any(term in combined_text for term in ['modern', 'highway', 'road', 'monument']):
                score -= 2.0  # Probablemente es el lugar moderno, no la batalla histÃ³rica
        
        # PENALIZACIÃ“N AGRESIVA: ImÃ¡genes completamente irrelevantes
        # Detectar cuando el tÃ­tulo/descripciÃ³n no tiene NADA que ver con la query
        query_keywords = set(query_lower.split())
        narration_keywords = set(narration_lower.split()) if narration_text else set()
        all_keywords = query_keywords.union(narration_keywords)
        
        # Remover palabras comunes que no aportan
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them'}
        all_keywords = {k for k in all_keywords if k not in stop_words and len(k) > 2}
        
        # Contar cuÃ¡ntas palabras clave relevantes aparecen en el tÃ­tulo/descripciÃ³n
        title_words = set(title_lower.split())
        desc_words = set(desc_lower.split())
        combined_words = title_words.union(desc_words)
        
        relevant_matches = len(all_keywords.intersection(combined_words))
        total_keywords = len(all_keywords)
        
        # Si hay muy pocas coincidencias (menos del 20% de las palabras clave), penalizar fuertemente
        if total_keywords > 0:
            match_ratio = relevant_matches / total_keywords
            if match_ratio < 0.2:  # Menos del 20% de coincidencias
                score -= 8.0  # PenalizaciÃ³n muy fuerte por irrelevancia
        
        # PENALIZACIÃ“N ESPECÃFICA: Detectar imÃ¡genes de arte/pinturas cuando se busca algo histÃ³rico especÃ­fico
        # Ej: "Girl with a Pearl Earring" (pintura de Vermeer) para "Pearl Harbor attack"
        art_indicators = ['painting', 'portrait', 'art', 'artist', 'museum', 'gallery', 'canvas', 'oil', 'watercolor']
        if any(indicator in combined_text for indicator in art_indicators):
            # Si la query es sobre un evento histÃ³rico especÃ­fico (no sobre arte), penalizar
            historical_event_indicators = ['attack', 'battle', 'war', 'invasion', 'bombing', 'raid', 'conflict', 'campaign']
            if any(indicator in query_lower or indicator in narration_lower for indicator in historical_event_indicators):
                # Verificar si el tÃ­tulo de la imagen menciona el evento histÃ³rico
                if not any(keyword in combined_text for keyword in all_keywords if len(keyword) > 4):
                    score -= 10.0  # PenalizaciÃ³n mÃ¡xima: imagen de arte completamente irrelevante
        
        # PENALIZACIÃ“N: ImÃ¡genes modernas cuando se busca algo histÃ³rico especÃ­fico
        # Detectar aÃ±os modernos (2000+) en tÃ­tulos cuando se busca algo de 1941, etc.
        import re
        query_years = set(re.findall(r'\b(19\d{2}|20\d{2})\b', query_lower + ' ' + narration_lower))
        title_years = set(re.findall(r'\b(19\d{2}|20\d{2})\b', combined_text))
        
        if query_years:
            # Si hay aÃ±os en la query pero no coinciden con los del tÃ­tulo
            if not query_years.intersection(title_years):
                # Y el tÃ­tulo tiene aÃ±os mucho mÃ¡s modernos (2000+)
                modern_years_in_title = {y for y in title_years if int(y) >= 2000}
                query_years_nums = {int(y) for y in query_years}
                if modern_years_in_title and all(yr < 2000 for yr in query_years_nums):
                    score -= 7.0  # PenalizaciÃ³n fuerte: imagen moderna para evento histÃ³rico antiguo
        
        # PENALIZACIÃ“N: Objetos/entidades completamente diferentes
        # Ej: "train" para "Roosevelt infamy speech" - no tiene nada que ver
        if 'pearl harbor' in query_lower or 'pearl harbor' in narration_lower:
            # Si la imagen es sobre algo completamente diferente (arte, transporte moderno, etc.)
            irrelevant_terms = ['train', 'subway', 'metro', 'earring', 'jewelry', 'painting', 'portrait', 'art', 'city lights', 'night lights', 'skyline']
            if any(term in combined_text for term in irrelevant_terms):
                # Verificar que al menos menciona "Pearl Harbor" o algo relacionado
                if 'pearl' not in combined_text and 'harbor' not in combined_text and 'hawaii' not in combined_text and '1941' not in combined_text:
                    score -= 10.0  # Completamente irrelevante
        
        # PENALIZACIÃ“N ESPECÃFICA: Lugares geogrÃ¡ficos incorrectos
        # Ej: "Granada" (ciudad espaÃ±ola) para "NicolÃ¡s I" (zar ruso) - completamente diferente
        if 'nicolÃ¡s' in query_lower or 'nicholas' in query_lower or 'nicolas' in query_lower:
            # Si la query es sobre un zar/persona histÃ³rica, penalizar lugares geogrÃ¡ficos no relacionados
            if 'granada' in combined_text.lower() and ('zar' not in combined_text.lower() and 'russia' not in combined_text.lower() and 'russian' not in combined_text.lower() and 'imperio ruso' not in combined_text.lower()):
                score -= 10.0  # "Granada" (ciudad espaÃ±ola) no tiene nada que ver con NicolÃ¡s I (zar ruso)
        
        # PENALIZACIÃ“N: Documentos/actas de nacimiento cuando se busca un evento histÃ³rico
        # Ej: "Acte de naissance de NapolÃ©on Bonaparte" para "Napoleon III Crimean War"
        if 'napoleon' in query_lower and ('war' in query_lower or 'crimean' in query_lower or 'battle' in query_lower):
            if 'naissance' in combined_text.lower() or 'birth' in combined_text.lower() or 'acte' in combined_text.lower():
                # Verificar que no menciona el evento histÃ³rico buscado
                if 'crimean' not in combined_text.lower() and 'war' not in combined_text.lower() and 'battle' not in combined_text.lower():
                    score -= 10.0  # Es un documento de nacimiento, no sobre la guerra
        
        # PENALIZACIÃ“N: Lugares modernos cuando se busca algo histÃ³rico especÃ­fico
        # Ej: "A view from Great Sevastopol Trail - August 2021" para "Sevastopol 1855"
        if 'sevastopol' in query_lower or 'sevastopol' in narration_lower:
            # Si la imagen es de un lugar moderno (2021, trail, view) pero no menciona el evento histÃ³rico
            if ('2021' in combined_text or '2020' in combined_text or 'trail' in combined_text.lower() or 'view from' in combined_text.lower()):
                if '1854' not in combined_text and '1855' not in combined_text and 'siege' not in combined_text.lower() and 'war' not in combined_text.lower():
                    score -= 8.0  # Es una vista moderna del lugar, no del evento histÃ³rico
        
        # PENALIZACIÃ“N: Documentos histÃ³ricos de otros perÃ­odos
        # Ej: "Pedro de Quintanilla (1671) Especial tratado" para "Tratado de ParÃ­s 1856"
        if 'tratado' in query_lower or 'treaty' in query_lower:
            # Extraer aÃ±o del tratado si estÃ¡ en la query
            import re
            treaty_years = re.findall(r'\b(18\d{2}|19\d{2})\b', query_lower + ' ' + narration_lower)
            if treaty_years:
                # Si el tÃ­tulo menciona un aÃ±o muy diferente (ej: 1671 vs 1856)
                title_years = re.findall(r'\b(16\d{2}|17\d{2}|18\d{2}|19\d{2})\b', combined_text)
                if title_years:
                    query_year = int(treaty_years[0])
                    title_year = int(title_years[0])
                    if abs(query_year - title_year) > 50:  # MÃ¡s de 50 aÃ±os de diferencia
                        # Verificar que no menciona el tratado especÃ­fico
                        if 'paris' not in combined_text.lower() and 'parÃ­s' not in combined_text.lower():
                            score -= 9.0  # Es un documento de otro perÃ­odo completamente diferente
        
        # PENALIZACIÃ“N: Lugares con nombres similares pero diferentes
        # Ej: "Balaclava" (ciudad) puede traer imÃ¡genes modernas del lugar, no de la batalla de 1854
        if 'balaclava' in query_lower and ('battle' in query_lower or 'charge' in query_lower or '1854' in query_lower):
            # Si la imagen es del lugar moderno pero no menciona la batalla
            if ('2007' in combined_text or '2010' in combined_text or 'modern' in combined_text.lower()):
                if 'battle' not in combined_text.lower() and 'charge' not in combined_text.lower() and '1854' not in combined_text:
                    score -= 8.0  # Es una imagen moderna del lugar, no de la batalla histÃ³rica
        
        # PENALIZACIÃ“N CRÃTICA: Programas de TV/entretenimiento vs operaciones militares
        # Ej: "OperaciÃ³n Triunfo" (programa de TV) para "OperaciÃ³n Overlord" (operaciÃ³n militar)
        if 'operaciÃ³n' in query_lower or 'operation' in query_lower:
            # Si la query es sobre una operaciÃ³n militar (overlord, normandy, d-day, etc.)
            military_indicators = ['overlord', 'normandy', 'd-day', 'invasiÃ³n', 'invasion', 'anfibia', 'amphibious', 'aliados', 'allies', '1944', 'war', 'guerra']
            if any(indicator in query_lower or indicator in narration_lower for indicator in military_indicators):
                # Penalizar programas de TV/entretenimiento
                tv_entertainment_indicators = ['triunfo', 'triumph', 'concierto', 'concert', 'gira', 'tour', '2023', '2022', '2021', '2020', 'tv', 'television', 'show', 'programa']
                if any(indicator in combined_text.lower() for indicator in tv_entertainment_indicators):
                    # Verificar que no menciona la operaciÃ³n militar
                    if not any(military_ind in combined_text.lower() for military_ind in military_indicators):
                        score -= 10.0  # PenalizaciÃ³n mÃ¡xima: programa de TV completamente irrelevante
        
        # PENALIZACIÃ“N: Mapas de lugares incorrectos
        # Ej: "Butler County Nebraska" para "Dwight D Eisenhower" (el mapa es de Nebraska, no de Eisenhower en la guerra)
        if 'eisenhower' in query_lower or 'dwight' in query_lower:
            # Si la query es sobre Eisenhower en contexto militar/histÃ³rico
            if 'war' in query_lower or 'guerra' in query_lower or '1944' in query_lower or 'normandy' in query_lower or 'd-day' in query_lower:
                # Penalizar mapas de lugares geogrÃ¡ficos no relacionados
                geographic_indicators = ['county', 'nebraska', 'incorporated', 'unincorporated', 'areas', 'highlighted', 'svg', 'map']
                if any(indicator in combined_text.lower() for indicator in geographic_indicators):
                    # Verificar que no menciona el contexto militar/histÃ³rico
                    if 'war' not in combined_text.lower() and 'guerra' not in combined_text.lower() and '1944' not in combined_text and 'normandy' not in combined_text.lower() and 'd-day' not in combined_text.lower():
                        score -= 10.0  # PenalizaciÃ³n mÃ¡xima: mapa geogrÃ¡fico completamente irrelevante
        
        # PENALIZACIÃ“N: Museos modernos cuando se busca el evento histÃ³rico
        # Ej: "Museo del Desembarco galÃ©s" para "Desembarco de NormandÃ­a" - puede ser relevante pero con score bajo
        if 'museo' in combined_text.lower() or 'museum' in combined_text.lower():
            # Si la query es sobre un evento histÃ³rico especÃ­fico
            if any(year in query_lower or year in narration_lower for year in ['1944', '1941', '1854', '1855']):
                # Verificar que el museo menciona el evento histÃ³rico
                if not any(keyword in combined_text.lower() for keyword in all_keywords if len(keyword) > 4):
                    score -= 3.0  # PenalizaciÃ³n moderada: museo puede ser relevante pero menos que imÃ¡genes del evento
        
        # Asegurar que el score estÃ© en rango razonable
        return max(0.0, min(score, 10.0))

    def search_videos(self, query: str, limit: int = 10, narration_text: str = "") -> List[Dict]:
        """
        Busca videos en Wikimedia Commons.
        Perfecto para contenido historico, documentales y archivos historicos.

        Args:
            query: Termino de busqueda (Ej: "World War II", "Apollo 11", "Berlin Wall")
            limit: Numero maximo de resultados
            narration_text: Texto de narracion para scoring de relevancia (opcional)

        Returns:
            Lista de diccionarios con informacion de los videos
        """
        raw_query = str(query or "").strip()
        if not raw_query:
            print("Wikimedia: Query vacia para busqueda de videos")
            return []

        query_has_video_filter = "filetype:video" in raw_query.lower()
        words = raw_query.split()
        first_word = words[0] if len(words) > 1 else raw_query

        def as_video_query(base_text: str) -> str:
            text = str(base_text or "").strip()
            if not text:
                return ""
            if query_has_video_filter or "filetype:video" in text.lower():
                return text
            return f"{text} filetype:video"

        # Priorizar consultas que fuerzan archivos de video.
        search_candidates = [
            as_video_query(raw_query),
            as_video_query(f'"{raw_query}"') if len(words) > 1 else "",
            as_video_query(first_word) if first_word and first_word != raw_query else "",
            raw_query if not query_has_video_filter else "",
        ]

        search_strategies = []
        seen_queries = set()
        for candidate in search_candidates:
            normalized = str(candidate or "").strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            search_strategies.append(normalized)

        all_videos = []
        seen_urls = set()

        for strategy_idx, search_query in enumerate(search_strategies):
            try:
                params = {
                    'action': 'query',
                    'format': 'json',
                    'generator': 'search',
                    'gsrsearch': search_query,
                    'gsrlimit': max(20, min(limit * 2, 120)),
                    'gsrnamespace': 6,  # File: namespace
                    'prop': 'imageinfo|info',
                    'iiprop': 'url|size|mime|extmetadata|timestamp|duration',
                    'iiurlwidth': self.thumb_width,
                    'iiurlheight': int(self.thumb_width * 9 / 16),
                    'iiextmetadatafilter': 'ImageDescription|Artist|LicenseShortName|DateTimeOriginal|Categories',
                }

                response = self._request_with_retry(
                    self.base_url,
                    params=params,
                    headers=self.headers,
                    timeout=12,
                    max_attempts=3
                )
                response.raise_for_status()
                data = response.json()

                if 'query' in data and 'pages' in data['query']:
                    for page_id, page_data in data['query']['pages'].items():
                        if not page_data.get('title', '').startswith('File:'):
                            continue
                        if 'imageinfo' not in page_data:
                            continue

                        file_info = page_data['imageinfo'][0]
                        mime_type = file_info.get('mime', '')

                        # Filtrar solo videos.
                        if not mime_type.startswith('video/'):
                            continue

                        title = page_data.get('title', '').replace('File:', '')
                        description = ''
                        license = ''
                        duration = file_info.get('duration', 0)

                        if 'extmetadata' in file_info:
                            metadata = file_info['extmetadata']
                            if 'ImageDescription' in metadata:
                                desc_value = metadata['ImageDescription'].get('value', '')
                                if isinstance(desc_value, str):
                                    description = desc_value
                            if 'LicenseShortName' in metadata:
                                license = metadata['LicenseShortName'].get('value', 'Public domain')

                        video_url = file_info.get('url', '')
                        if not video_url or video_url in seen_urls:
                            continue

                        seen_urls.add(video_url)

                        # Calcular score de relevancia.
                        relevance_score = self._calculate_relevance_score(raw_query, narration_text, title, description)

                        video_info = {
                            'url': video_url,
                            'title': title,
                            'description': description,
                            'license': license,
                            'source': 'wikimedia',
                            'query': raw_query,
                            'relevance_score': relevance_score,
                            'duration': duration,
                            'mime_type': mime_type,
                            'thumburl': file_info.get('thumburl', '')
                        }

                        all_videos.append(video_info)

            except requests.exceptions.Timeout:
                print(f"Wikimedia: Timeout en busqueda de videos '{raw_query}' (estrategia {strategy_idx + 1})")
            except Exception as e:
                print(f"Wikimedia: Error en estrategia {strategy_idx + 1} para '{raw_query}': {e}")
            finally:
                if self.search_delay_seconds > 0:
                    time.sleep(self.search_delay_seconds)

        # Ordenar por relevancia y limitar.
        all_videos.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        top_videos = all_videos[:limit]

        if top_videos:
            print(f"Wikimedia: {len(top_videos)} candidatos de video encontrados para '{raw_query}'")
            return top_videos

        print(f"Wikimedia: Sin videos para '{raw_query}'")
        return []

    def search_historical_images(self, query: str, year: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        BÃºsqueda especializada para imÃ¡genes histÃ³ricas.

        Args:
            query: Evento o tema histÃ³rico
            year: AÃ±o opcional para filtrar (Ej: "1941", "1969")
            limit: NÃºmero de resultados

        Returns:
            Lista de imÃ¡genes histÃ³ricas
        """
        # Construir bÃºsqueda mejorada para contenido histÃ³rico
        search_query = query
        if year:
            search_query = f"{query} {year}"

        # Agregar categorÃ­as histÃ³ricas comunes
        search_query += " incategory:History OR incategory:Historical OR incategory:Archive"

        return self.search_images(search_query, limit)

    def search_by_category(self, category: str, limit: int = 10) -> List[Dict]:
        """
        Busca imÃ¡genes dentro de una categorÃ­a especÃ­fica.

        Args:
            category: Nombre de categorÃ­a (Ej: "World_War_II", "Ancient_Egypt", "Space_exploration")
            limit: NÃºmero de resultados

        Returns:
            Lista de imÃ¡genes de la categorÃ­a
        """
        try:
            params = {
                'action': 'query',
                'format': 'json',
                'generator': 'categorymembers',
                'gcmtitle': f'Category:{category}',
                'gcmtype': 'file',
                'gcmlimit': limit,
                'prop': 'imageinfo',
                'iiprop': 'url|size|mime|extmetadata',
                'iiurlwidth': self.thumb_width
            }

            response = self._request_with_retry(
                self.base_url,
                params=params,
                headers=self.headers,
                timeout=12,
                max_attempts=3
            )
            response.raise_for_status()
            data = response.json()

            images = []
            if 'query' in data and 'pages' in data['query']:
                for page_id, page_data in data['query']['pages'].items():
                    if 'imageinfo' not in page_data:
                        continue

                    img_info = page_data['imageinfo'][0]
                    images.append({
                        'title': page_data.get('title', '').replace('File:', ''),
                        'url': img_info.get('url', ''),
                        'thumburl': img_info.get('thumburl', img_info.get('url', '')),
                        'width': img_info.get('width', 0),
                        'height': img_info.get('height', 0)
                    })

            print(f"âœ… Wikimedia: {len(images)} imÃ¡genes de categorÃ­a '{category}'")
            return images

        except Exception as e:
            print(f"âŒ Error obteniendo categorÃ­a: {e}")
            return []

    def download_video(self, video_info: Dict, output_path: str) -> Optional[str]:
        """
        Descarga un video de Wikimedia Commons.
        
        Args:
            video_info: Diccionario con informaciÃ³n del video (debe incluir 'url')
            output_path: Ruta donde guardar el video
        
        Returns:
            Ruta del archivo descargado o None si falla
        """
        try:
            video_url = video_info.get('url', '')
            if not video_url:
                print("âŒ No hay URL de video para descargar")
                return None
            
            print(f"   â¬‡ï¸ Descargando video histÃ³rico de Wikimedia Commons...")
            print(f"   ðŸ“¹ {video_info.get('title', 'Video sin tÃ­tulo')}")
            
            # Crear directorio si no existe
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Descargar con stream para archivos grandes
            response = requests.get(video_url, headers=self.headers, stream=True, timeout=60)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            if downloaded % (1024 * 1024) == 0:  # Mostrar cada MB
                                print(f"   â³ {percent:.1f}% descargado...", end='\r')
            
            print(f"\n   âœ… Video descargado: {Path(output_path).name}")
            return str(output_path)
            
        except Exception as e:
            print(f"   âŒ Error descargando video: {e}")
            return None

    def download_image(self, image_info: Dict, output_path: str) -> Optional[str]:
        """
        Descarga una imagen de Wikimedia Commons.

        Args:
            image_info: Diccionario con informaciÃ³n de la imagen (de search_images)
            output_path: Ruta donde guardar la imagen

        Returns:
            Ruta al archivo descargado, o None si falla
        """
        try:
            # Descarga interactiva: priorizar variantes de thumbnail grande para
            # evitar bloqueos largos por 429 en originales.
            candidate_urls = []
            raw_url = image_info.get('url') or ''
            thumb_url = image_info.get('thumburl') or ''
            file_url = image_info.get('file_url') or ''
            image_title = image_info.get('title', '')

            def add_candidate(url: str):
                if not url:
                    return
                if url not in candidate_urls:
                    candidate_urls.append(url)

            # 1) Derivadas estables por título.
            add_candidate(self._build_special_filepath_url(image_title, 1600))
            add_candidate(self._build_special_filepath_url(image_title, 1280))
            add_candidate(self._build_special_filepath_url(image_title, 960))

            # 2) Reescalar thumb si existe.
            add_candidate(self._retarget_thumb_width(thumb_url, 1280))
            add_candidate(self._retarget_thumb_width(thumb_url, 960))
            add_candidate(thumb_url)

            # 3) Original/fallback.
            add_candidate(raw_url)
            add_candidate(file_url)

            if not candidate_urls:
                print("âŒ No hay URL de descarga disponible")
                return None

            for download_url in candidate_urls:
                try:
                    response = self._request_with_retry(
                        download_url,
                        headers=self.headers,
                        stream=True,
                        timeout=20,
                        max_attempts=1,
                        retry_statuses=(500, 502, 503, 504),
                        max_retry_after_seconds=4.0
                    )
                    if response.status_code == 429:
                        print("âš ï¸ Wikimedia: HTTP 429 en URL candidata, probando siguiente...")
                        continue
                    response.raise_for_status()

                    content_type = response.headers.get('content-type', '').lower()
                    if content_type and not content_type.startswith('image/'):
                        print(f"âš ï¸ Wikimedia: Respuesta no es imagen ({content_type}), intentando URL alternativa...")
                        continue

                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)

                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        print(f"âœ… Descargado: {image_info.get('title', 'imagen')}")
                        return output_path

                    print("âš ï¸ Wikimedia: Archivo descargado vacÃ­o, intentando URL alternativa...")

                except Exception as download_error:
                    print(f"âš ï¸ Wikimedia: FallÃ³ descarga desde URL candidata: {download_error}")
                    continue

            print("âŒ Error descargando imagen: no se pudo descargar desde ninguna URL candidata")
            return None

        except Exception as e:
            print(f"âŒ Error descargando imagen: {e}")
            return None

    def is_historical_content(self, query: str) -> bool:
        """
        Detecta si el contenido es de naturaleza histÃ³rica/real.

        Args:
            query: Texto del segmento o prompt

        Returns:
            True si es contenido histÃ³rico/real que deberÃ­a usar Wikimedia
        """
        # Palabras clave que indican contenido histÃ³rico o real
        historical_keywords = [
            # Eventos histÃ³ricos
            'guerra', 'war', 'batalla', 'battle', 'revoluciÃ³n', 'revolution',
            'independencia', 'independence', 'conquista', 'conquest',

            # PerÃ­odos histÃ³ricos
            'antiguo', 'ancient', 'medieval', 'renacimiento', 'renaissance',
            'siglo', 'century', 'era', 'Ã©poca', 'period',

            # Personajes histÃ³ricos (general)
            'presidente', 'president', 'rey', 'king', 'reina', 'queen',
            'emperador', 'emperor', 'faraÃ³n', 'pharaoh', 'lÃ­der', 'leader',

            # Ciencia real
            'cientÃ­fico', 'scientist', 'descubrimiento', 'discovery',
            'invento', 'invention', 'experimento', 'experiment',

            # GeografÃ­a/lugares reales
            'paÃ­s', 'country', 'ciudad', 'city', 'monumento', 'monument',
            'pirÃ¡mide', 'pyramid', 'templo', 'temple', 'catedral', 'cathedral',

            # Eventos actuales/reales
            'acontecimiento', 'event', 'noticia', 'news', 'actual', 'current',
            'fotografÃ­a', 'photograph', 'imagen real', 'real image',

            # Fechas (indica eventos histÃ³ricos especÃ­ficos)
            '19', '20', '18', '17',  # Siglos en aÃ±os
        ]

        query_lower = query.lower()
        return any(keyword in query_lower for keyword in historical_keywords)

    def search_by_historical_category(self, topic_keywords: List[str], limit: int = 10) -> List[Dict]:
        """
        Busca imÃ¡genes usando categorÃ­as histÃ³ricas especÃ­ficas de Wikimedia.
        Filtra resultados por relevancia basada en palabras clave.
        
        Args:
            topic_keywords: Lista de palabras clave del tema
            limit: NÃºmero mÃ¡ximo de resultados
            
        Returns:
            Lista de imÃ¡genes encontradas y filtradas por relevancia
        """
        # Mapeo de palabras clave a categorÃ­as de Wikimedia
        category_map = {
            'mongol': ['Mongol_Empire', 'Genghis_Khan', 'Mongolia', 'Central_Asia'],
            'minoan': ['Minoan_civilization', 'Crete', 'Knossos', 'Bronze_Age'],
            'ancient': ['Ancient_history', 'Archaeology', 'Historical_photographs'],
            'egypt': ['Ancient_Egypt', 'Egyptology', 'Pharaohs'],
            'greece': ['Ancient_Greece', 'Greek_history', 'Hellenistic_period'],
            'rome': ['Ancient_Rome', 'Roman_Empire', 'Roman_history'],
            'bronze': ['Bronze_Age', 'Archaeology', 'Ancient_history'],
            'medieval': ['Middle_Ages', 'Medieval_history', 'Medieval_architecture'],
            'war': ['Military_history', 'Battles', 'War_photography'],
            'civilization': ['Ancient_civilizations', 'Archaeology', 'Historical_photographs'],
        }
        
        # Identificar categorÃ­as relevantes
        relevant_categories = []
        topic_lower = ' '.join(topic_keywords).lower()
        
        for keyword, categories in category_map.items():
            if keyword in topic_lower:
                relevant_categories.extend(categories)
        
        # Si no encontramos categorÃ­as especÃ­ficas, usar categorÃ­as generales
        if not relevant_categories:
            relevant_categories = ['Ancient_history', 'Archaeology', 'Historical_photographs']
        
        # Buscar en cada categorÃ­a y filtrar por relevancia
        all_images = []
        for category in relevant_categories[:3]:  # MÃ¡ximo 3 categorÃ­as
            try:
                images = self.search_by_category(category, limit=limit*2)  # Obtener mÃ¡s para filtrar
                all_images.extend(images)
            except:
                continue
        
        # Filtrar imÃ¡genes por relevancia basada en palabras clave
        if topic_keywords:
            filtered_images = []
            topic_lower_str = ' '.join(topic_keywords).lower()
            
            for img in all_images:
                title_lower = img.get('title', '').lower()
                desc_lower = img.get('description', '').lower()
                combined_text = f"{title_lower} {desc_lower}"
                
                # Contar coincidencias de palabras clave
                matches = sum(1 for keyword in topic_keywords if keyword.lower() in combined_text)
                
                # Solo incluir si hay al menos una coincidencia relevante
                if matches > 0:
                    img['relevance_score'] = matches
                    filtered_images.append(img)
            
            # Ordenar por relevancia y limitar
            filtered_images.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
            return filtered_images[:limit]
        
        return all_images[:limit]
    
    def suggest_search_terms_with_ai(self, visual_prompt: str, narration_text: str = "") -> str:
        """
        Usa Gemini AI para generar tÃ©rminos de bÃºsqueda optimizados para Wikimedia.
        Mejorado para mayor precisiÃ³n y relevancia.
        
        Args:
            visual_prompt: Prompt visual generado por IA
            narration_text: Texto de narraciÃ³n del segmento (opcional, ayuda al contexto)
            
        Returns:
            TÃ©rminos de bÃºsqueda optimizados por IA
        """
        if not self.gemini_client:
            # Fallback al mÃ©todo tradicional si no hay Gemini
            return self.suggest_search_terms(visual_prompt)
        
        try:
            # Construir prompt mejorado para Gemini
            context = f"\n\nNARRACIÃ“N REAL DEL VIDEO: {narration_text}" if narration_text else ""
            
            prompt = f"""Eres un experto en bÃºsqueda de imÃ¡genes histÃ³ricas y reales en Wikimedia Commons.

TAREA CRÃTICA: Extrae SOLO los tÃ©rminos de bÃºsqueda mÃ¡s relevantes y especÃ­ficos que encontrarÃ¡n imÃ¡genes REALES en Wikimedia Commons que coincidan EXACTAMENTE con la narraciÃ³n histÃ³rica.

PROMPT VISUAL (puede ser artÃ­stico): "{visual_prompt}"
{context}

ANÃLISIS REQUERIDO:
1. PRIORIDAD ABSOLUTA: La narraciÃ³n es la fuente de verdad. Si la narraciÃ³n menciona algo especÃ­fico, usa ESO, no el prompt visual artÃ­stico.
2. IDENTIFICA EL PERÃODO HISTÃ“RICO ESPECÃFICO:
   - Si la narraciÃ³n menciona "Guerras MÃ©dicas", "Persian Wars", "Greco-Persian Wars" â†’ busca "Greco-Persian Wars" o "Persian Wars" con fechas (490 BC, 480 BC, etc.)
   - Si menciona un siglo especÃ­fico (ej: "siglo V a.C.", "5th century BC") â†’ INCLÃšYELO en la bÃºsqueda
   - Si menciona un evento especÃ­fico (ej: "Batalla de MaratÃ³n", "Battle of Marathon") â†’ busca ese evento especÃ­fico con fecha
   - EVITA tÃ©rminos genÃ©ricos como "Greece", "Ancient Greece" sin contexto temporal â†’ estos traen imÃ¡genes de cualquier perÃ­odo
3. Identifica ENTIDADES CONCRETAS en este orden de importancia:
   a) Eventos histÃ³ricos especÃ­ficos CON FECHAS (ej: "Battle of Marathon 490 BC", "Greco-Persian Wars 5th century BC")
   b) Nombres de personas histÃ³ricas especÃ­ficas (ej: "Darius I", "Xerxes I", "Leonidas")
   c) Nombres propios de lugares geogrÃ¡ficos histÃ³ricos (ej: "Thermopylae", "Salamis", "Marathon")
   d) Nombres de civilizaciones, culturas, imperios histÃ³ricos (ej: "Achaemenid Empire", "Persian Empire")
   e) Objetos, estructuras, artefactos especÃ­ficos (ej: "Behistun Inscription", "Hellespont bridge")
4. ELIMINA COMPLETAMENTE:
   - Palabras artÃ­sticas: "cinematic", "stunning", "atmospheric", "documentary-style", "epic", "dramatic", "beautiful", "realistic"
   - Palabras descriptivas genÃ©ricas: "view", "scene", "showing", "depicting", "featuring", "image of"
   - Adjetivos subjetivos: "amazing", "incredible", "spectacular"
   - TÃ©rminos tÃ©cnicos de video: "8k", "4k", "high-resolution", "photorealistic"
   - TÃ©rminos genÃ©ricos sin contexto temporal: "Greece" solo, "ancient" solo, "battle" solo â†’ estos traen imÃ¡genes de cualquier perÃ­odo
5. REGLAS CRÃTICAS PARA EVITAR IMÃGENES INCORRECTAS:
   - Si la narraciÃ³n habla de "Guerras MÃ©dicas" (490-449 BC), NO uses solo "Greece" o "Ancient Greece" â†’ usa "Greco-Persian Wars" o "Persian Wars 5th century BC"
   - Si menciona un evento del siglo V a.C., INCLUYE "5th century BC" o "490 BC" o "480 BC" en la bÃºsqueda
   - Si menciona "Marathon", especifica "Battle of Marathon 490 BC" no solo "Marathon"
   - Si menciona "Thermopylae", especifica "Battle of Thermopylae 480 BC" no solo "Thermopylae"
6. Si la narraciÃ³n menciona una fecha, INCLÃšYELA SIEMPRE (ej: "490 BC", "480 BC", "5th century BC")
7. Si la narraciÃ³n menciona un evento especÃ­fico, USA ESE EVENTO CON FECHA (ej: "Battle of Marathon 490 BC", "Battle of Thermopylae 480 BC")
8. MÃXIMO 5-7 palabras clave (incluyendo fechas cuando sea posible)
9. Idioma: inglÃ©s (para mejor compatibilidad con Wikimedia)
10. Usa nombres exactos como aparecen en Wikipedia/Wikimedia (ej: "Greco-Persian Wars" no "Greek-Persian Wars")

FORMATO DE RESPUESTA: SOLO los tÃ©rminos de bÃºsqueda, separados por espacios, sin explicaciones, sin artÃ­culos, sin puntuaciÃ³n.

Ejemplos CORRECTOS (especÃ­ficos con fechas y eventos):
Input visual: "A cinematic view of Pearl Harbor during the attack in 1941, showing dramatic explosions"
NarraciÃ³n: "On December 7, 1941, Japanese forces attacked Pearl Harbor"
Output: "Pearl Harbor attack 1941"

Input visual: "Realistic historical documentary style depicting ancient Egyptian pharaoh"
NarraciÃ³n: "Ramesses III was one of the last great pharaohs of ancient Egypt"
Output: "Ramesses III Egypt pharaoh"

Input visual: "Eastern Mediterranean Anatolia Levant Egypt ancient trade routes map"
NarraciÃ³n: "The Minoan civilization flourished on the island of Crete"
Output: "Minoan Crete civilization"

Input visual: "ancient civilization 2000 BC agriculture river valley settlements"
NarraciÃ³n: "The Mongol Empire was the largest contiguous land empire in history"
Output: "Mongol Empire"

Input visual: "stunning cinematic view of ancient ruins"
NarraciÃ³n: "The ancient city of Knossos was the center of Minoan civilization"
Output: "Knossos Minoan"

Input visual: "Battle of Marathon Greek phalanx"
NarraciÃ³n: "In 490 BC, the Battle of Marathon was fought between the Greeks and Persians"
Output: "Battle of Marathon 490 BC Greco-Persian"

Input visual: "Guerras MÃ©dicas Persian army"
NarraciÃ³n: "Las Guerras MÃ©dicas fueron una serie de conflictos entre el Imperio Persa y las ciudades-estado griegas en el siglo V a.C."
Output: "Greco-Persian Wars 5th century BC Persian Wars"

Input visual: "Thermopylae Leonidas Spartans"
NarraciÃ³n: "In 480 BC, King Leonidas and 300 Spartans fought at Thermopylae"
Output: "Battle of Thermopylae 480 BC Leonidas Spartans"

Ahora procesa (SOLO tÃ©rminos clave, sin palabras artÃ­sticas, priorizando la narraciÃ³n):
Visual: "{visual_prompt}"
{context if narration_text else ""}
"""
            
            # Generar con Gemini
            ai_terms = self.gemini_client._generate(prompt)
            
            # Verificar si la generaciÃ³n fue exitosa
            if not ai_terms:
                print("   âš ï¸ Error: Claude CLI retornÃ³ None, usando mÃ©todo tradicional")
                return self.suggest_search_terms(visual_prompt)
            
            # Detectar error de cuotas agotadas
            if ai_terms == "ERROR_QUOTA_EXCEEDED":
                print("   âš ï¸ Error: Cuotas de Claude API agotadas, usando mÃ©todo tradicional")
                return self.suggest_search_terms(visual_prompt)
            
            # Limpiar respuesta mÃ¡s agresivamente
            ai_terms = ai_terms.strip()
            # Remover markdown, asteriscos, comillas
            ai_terms = ai_terms.replace("```", "").replace("**", "").replace("*", "").replace('"', '').replace("'", "").strip()
            # Remover prefijos comunes de respuestas de IA
            prefixes_to_remove = ["Output:", "TÃ©rminos:", "BÃºsqueda:", "Search terms:", "Keywords:"]
            for prefix in prefixes_to_remove:
                if ai_terms.lower().startswith(prefix.lower()):
                    ai_terms = ai_terms[len(prefix):].strip()
            # Tomar solo la primera lÃ­nea
            ai_terms = ai_terms.split('\n')[0].strip()
            # Remover puntuaciÃ³n final
            ai_terms = ai_terms.rstrip('.,;:!?')
            
            # Validar que tenga contenido
            if len(ai_terms) > 3 and len(ai_terms.split()) >= 2:
                print(f"   ðŸ¤– IA mejorÃ³ tÃ©rminos: '{ai_terms}' (de '{visual_prompt[:50]}...')")
                return ai_terms
            else:
                # Si la respuesta de IA es muy corta, usar mÃ©todo tradicional
                print(f"   âš ï¸ Respuesta de IA muy corta ('{ai_terms}'), usando mÃ©todo tradicional")
                return self.suggest_search_terms(visual_prompt)
                
        except Exception as e:
            print(f"   âš ï¸ Error usando IA para tÃ©rminos de bÃºsqueda: {e}")
            # Fallback al mÃ©todo tradicional
            return self.suggest_search_terms(visual_prompt)
    
    def suggest_search_terms(self, visual_prompt: str) -> str:
        """
        Convierte un visual_prompt de IA en tÃ©rminos de bÃºsqueda para Wikimedia.

        Args:
            visual_prompt: Prompt generado por Gemini para IA
            (Ej: "A cinematic view of Pearl Harbor during the attack in 1941")

        Returns:
            TÃ©rminos de bÃºsqueda optimizados para Wikimedia
            (Ej: "Pearl Harbor attack 1941")
        """
        import re
        
        # Extraer tÃ©rminos clave: nombres propios, fechas, lugares, eventos
        # Primero, intentar extraer informaciÃ³n estructurada
        
        # Extraer aÃ±os (4 dÃ­gitos)
        years = re.findall(r'\b(19|20)\d{2}\b', visual_prompt)
        
        # Extraer nombres propios (palabras capitalizadas consecutivas)
        proper_nouns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', visual_prompt)
        
        # Remover palabras de estilo cinematogrÃ¡fico
        style_words = [
            'cinematic', 'cinematographic', 'view', 'scene', 'dramatic', 'epic', 
            'stunning', 'beautiful', 'amazing', 'professional', 'high quality', 
            '8k', '4k', 'photorealistic', 'detailed', 'atmospheric', 'lighting',
            'high-resolution', 'high resolution', 'high-definition', 'high definition',
            'style', 'realistic', 'documentary-style', 'documentary style',
            'd ting', 'd t', 'showing', 'depicting', 'featuring'
        ]
        
        # Remover artÃ­culos y preposiciones comunes
        stop_words = ['a ', 'an ', 'the ', 'of ', 'in ', 'at ', 'on ', 'with ', 
                     'from ', 'to ', 'for ', 'by ', 'and ', 'or ', 'but ',
                     'around', 'during', 'under', 'over', 'through']

        clean_query = visual_prompt.lower()
        
        # Remover palabras de estilo
        for word in style_words:
            pattern = r'\b' + re.escape(word) + r'\b'
            clean_query = re.sub(pattern, ' ', clean_query, flags=re.IGNORECASE)
        
        # Remover stop words
        for word in stop_words:
            pattern = r'\b' + re.escape(word) + r'\b'
            clean_query = re.sub(pattern, ' ', clean_query, flags=re.IGNORECASE)

        # Limpiar espacios mÃºltiples
        clean_query = ' '.join(clean_query.split())
        
        # Si encontramos nombres propios, priorizarlos
        if proper_nouns:
            # Combinar nombres propios con tÃ©rminos limpios
            proper_nouns_str = ' '.join([pn.lower() for pn in proper_nouns[:3]])  # MÃ¡ximo 3 nombres propios
            # Combinar con tÃ©rminos clave del prompt limpio
            key_terms = [w for w in clean_query.split() if len(w) > 3][:5]  # Palabras de mÃ¡s de 3 letras
            result_parts = [proper_nouns_str] + key_terms
            result = ' '.join(result_parts)
        else:
            # Sin nombres propios, usar tÃ©rminos clave del prompt limpio
            key_terms = [w for w in clean_query.split() if len(w) > 2][:8]  # Palabras de mÃ¡s de 2 letras
            result = ' '.join(key_terms)
        
        # Agregar aÃ±os si se encontraron
        if years:
            result = f"{result} {' '.join(years[:2])}"  # MÃ¡ximo 2 aÃ±os
        
        # Limpiar caracteres especiales innecesarios
        result = re.sub(r'[^\w\s\-]', ' ', result)
        result = ' '.join(result.split())
        
        # Si el resultado es muy corto, usar limpieza mÃ­nima del prompt original
        if len(result.split()) < 2:
            minimal_clean = visual_prompt.lower()
            # Solo remover palabras de estilo mÃ¡s obvias
            for word in ['cinematic', 'stunning', 'beautiful', 'amazing', 'professional', '8k', '4k', 'd ting', 'd t']:
                minimal_clean = minimal_clean.replace(word, ' ')
            minimal_clean = ' '.join(minimal_clean.split())
            # Tomar las primeras 6 palabras mÃ¡s relevantes
            words = [w for w in minimal_clean.split() if len(w) > 2][:6]
            if words:
                result = ' '.join(words)
        
        result = result.strip()
        
        # Log para debug
        if len(result) < 3:
            print(f"   âš ï¸ TÃ©rminos de bÃºsqueda muy cortos: '{result}' (original: '{visual_prompt[:60]}...')")
        else:
            print(f"   ðŸ” TÃ©rminos extraÃ­dos: '{result}'")
        
        return result


# CategorÃ­as Ãºtiles de Wikimedia Commons para diferentes temas
WIKIMEDIA_CATEGORIES = {
    'world_war_ii': 'World_War_II',
    'world_war_i': 'World_War_I',
    'ancient_egypt': 'Ancient_Egypt',
    'ancient_rome': 'Ancient_Rome',
    'space_exploration': 'Space_exploration',
    'scientists': 'Scientists',
    'presidents': 'Presidents_of_the_United_States',
    'historical_photographs': 'Historical_photographs',
    'aviation_history': 'Aviation_history',
    'naval_history': 'Naval_history',
    'architecture': 'Architecture',
    'natural_disasters': 'Natural_disasters',
    'geography': 'Geography',
    'astronomy': 'Astronomy',
}


if __name__ == "__main__":
    # Prueba del cliente
    client = WikimediaClient()

    # Ejemplo 1: BÃºsqueda histÃ³rica
    print("\n" + "="*70)
    print("EJEMPLO 1: Pearl Harbor")
    print("="*70)
    images = client.search_historical_images("Pearl Harbor attack", year="1941", limit=3)
    for img in images:
        print(f"\nðŸ“¸ {img['title']}")
        print(f"   URL: {img['url'][:80]}...")
        print(f"   Licencia: {img.get('license', 'N/A')}")

    # Ejemplo 2: DetecciÃ³n automÃ¡tica
    print("\n" + "="*70)
    print("EJEMPLO 2: DetecciÃ³n de contenido histÃ³rico")
    print("="*70)

    test_prompts = [
        "Un dragÃ³n volando sobre un castillo mÃ¡gico",  # FantasÃ­a â†’ IA
        "El bombardeo de Pearl Harbor en 1941",        # HistÃ³rico â†’ Wikimedia
        "Albert Einstein explicando la relatividad",   # Real â†’ Wikimedia
        "Una nave espacial futurista en Marte",        # FicciÃ³n â†’ IA
    ]

    for prompt in test_prompts:
        is_historical = client.is_historical_content(prompt)
        source = "ðŸ“š Wikimedia (Real)" if is_historical else "ðŸŽ¨ IA (Generada)"
        print(f"{source}: {prompt}")

