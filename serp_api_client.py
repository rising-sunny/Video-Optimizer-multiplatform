# serp_api_client.py
"""
Cliente para SERP API (Search Engine Results Page API)
Proporciona resultados estructurados de Google para refinar búsquedas de videos virales
"""

import os
import requests
import time
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv

load_dotenv()

SERP_API_KEY = os.getenv("SERP_API_KEY")
SERP_API_AVAILABLE = SERP_API_KEY is not None and SERP_API_KEY != "" and "TU_API_KEY" not in SERP_API_KEY.upper()

class SerpApiClient:
    """
    Cliente para interactuar con SerpApi (serpapi.com)
    Proporciona resultados estructurados de Google incluyendo:
    - People Also Ask
    - Related Searches
    - Top Stories
    - Video Results
    - Knowledge Graph
    """
    
    def __init__(self):
        self.api_key = SERP_API_KEY
        self.base_url = "https://serpapi.com/search"
        self.rate_limit_delay = 1.0  # Delay entre requests para evitar rate limiting
        self.last_request_time = 0
        self.max_retries = 3
        self.timeout = 30
        
        if not SERP_API_AVAILABLE:
            print("️ SERP_API_KEY no configurada o inválida en .env")
        else:
            print(" SERP API Client inicializado")
    
    def _rate_limit(self):
        """Implementa rate limiting básico"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - time_since_last)
        self.last_request_time = time.time()
    
    def _make_request(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Realiza una petición a SERP API con manejo robusto de errores
        
        Args:
            params: Parámetros para la petición
            
        Returns:
            Diccionario con resultados o None si hay error
        """
        if not SERP_API_AVAILABLE:
            return None
        
        params["api_key"] = self.api_key
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                response = requests.get(self.base_url, params=params, timeout=self.timeout)
                
                # Verificar código de estado
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    print(" SERP API: API Key inválida o expirada")
                    return None
                elif response.status_code == 429:
                    wait_time = (attempt + 1) * 2
                    print(f"️ SERP API: Rate limit alcanzado. Esperando {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                elif response.status_code == 400:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", "Bad Request")
                    print(f"️ SERP API: Error 400 - {error_msg}")
                    return None
                else:
                    print(f"️ SERP API: Error {response.status_code} - {response.text[:200]}")
                    if attempt < self.max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    return None
                    
            except requests.exceptions.Timeout:
                print(f"️ SERP API: Timeout en intento {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
                
            except requests.exceptions.ConnectionError as e:
                print(f"️ SERP API: Error de conexión - {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
                
            except requests.exceptions.RequestException as e:
                print(f"️ SERP API: Error en petición - {e}")
                return None
                
            except Exception as e:
                print(f"️ SERP API: Error inesperado - {e}")
                return None
        
        return None
    
    def search_google(self, query: str, location: str = "Spain", language: str = "es", 
                     num_results: int = 10) -> Optional[Dict[str, Any]]:
        """
        Realiza una búsqueda en Google usando SERP API
        
        Args:
            query: Término de búsqueda
            location: Ubicación para los resultados (default: Spain) - usar nombre de país o ciudad,país
            language: Idioma (default: es)
            num_results: Número de resultados a obtener
            
        Returns:
            Diccionario con resultados estructurados o None si hay error
        """
        if not SERP_API_AVAILABLE:
            return None
        
        # Mapeo de nombres de países a códigos ISO para el parámetro gl
        country_codes = {
            "spain": "es",
            "Spain": "es",
            "españa": "es",
            "España": "es",
            "united states": "us",
            "usa": "us",
            "US": "us",
            "mexico": "mx",
            "México": "mx",
            "argentina": "ar",
            "chile": "cl",
            "colombia": "co",
        }
        
        # Determinar código de país (gl parameter)
        # Si location es un código de 2 letras, usarlo directamente
        if len(location) == 2 and location.isalpha():
            gl_code = location.lower()
        else:
            # Buscar en el mapeo o extraer de formato "ciudad,país"
            location_lower = location.lower()
            if "," in location_lower:
                country_part = location_lower.split(",")[-1].strip()
                gl_code = country_codes.get(country_part, "es")
            else:
                gl_code = country_codes.get(location_lower, "es")  # Default a España
        
        params = {
            "q": query,
            "location": location,  # Nombre del país/ciudad
            "hl": language,
            "gl": gl_code,  # Código ISO de país (es, us, mx, etc.)
            "num": min(num_results, 20),  # Limitar a 20 máximo
            "engine": "google"
        }
        
        return self._make_request(params)
    
    def get_related_searches(self, query: str, location: str = "Spain", 
                            language: str = "es") -> List[str]:
        """
        Obtiene búsquedas relacionadas para un término
        
        Returns:
            Lista de términos de búsqueda relacionados
        """
        results = self.search_google(query, location, language, num_results=5)
        if not results:
            return []
            
        related_searches = []
        
        try:
            # Extraer "related_searches"
            if "related_searches" in results:
                for item in results["related_searches"]:
                    if isinstance(item, dict) and "query" in item:
                        query_text = item["query"].strip()
                        if query_text:
                            related_searches.append(query_text)
                    elif isinstance(item, str):
                        related_searches.append(item.strip())
        except (KeyError, TypeError, AttributeError) as e:
            print(f"️ Error extrayendo related_searches: {e}")
        
        return related_searches[:10]  # Limitar a 10
    
    def get_people_also_ask(self, query: str, location: str = "Spain", 
                           language: str = "es") -> List[Dict[str, str]]:
        """
        Obtiene preguntas "People Also Ask" relacionadas
        
        Returns:
            Lista de diccionarios con 'question' y 'snippet'
        """
        results = self.search_google(query, location, language, num_results=5)
        if not results:
            return []
            
        paa_results = []
        
        try:
            if "people_also_ask" in results:
                for item in results["people_also_ask"]:
                    if isinstance(item, dict):
                        paa_results.append({
                            "question": item.get("question", "").strip(),
                            "snippet": item.get("snippet", "").strip(),
                            "title": item.get("title", "").strip()
                        })
        except (KeyError, TypeError, AttributeError) as e:
            print(f"️ Error extrayendo People Also Ask: {e}")
        
        return paa_results[:10]  # Limitar a 10
    
    def get_video_results(self, query: str, location: str = "Spain", 
                         language: str = "es", max_videos: int = 10) -> List[Dict[str, Any]]:
        """
        Obtiene resultados de videos de Google
        
        Returns:
            Lista de videos con información estructurada
        """
        results = self.search_google(query, location, language, num_results=20)
        if not results:
            return []
            
        videos = []
        
        try:
            if "video_results" in results:
                for video in results["video_results"][:max_videos]:
                    if isinstance(video, dict):
                        videos.append({
                            "title": video.get("title", "").strip(),
                            "link": video.get("link", "").strip(),
                            "thumbnail": video.get("thumbnail", "").strip(),
                            "channel": video.get("channel", {}).get("name", "") if isinstance(video.get("channel"), dict) else "",
                            "duration": video.get("duration", "").strip(),
                            "views": video.get("views", "").strip(),
                            "date": video.get("date", "").strip()
                        })
        except (KeyError, TypeError, AttributeError) as e:
            print(f"️ Error extrayendo video results: {e}")
        
        return videos
    
    def get_trending_keywords(self, category: str, location: str = "Spain", 
                             language: str = "es") -> List[str]:
        """
        Obtiene keywords trending para una categoría usando búsquedas relacionadas
        
        Returns:
            Lista de keywords trending
        """
        keywords = []
        
        try:
            # Buscar la categoría principal
            main_results = self.search_google(f"{category} trending", location, language, num_results=5)
            
            # Extraer related searches
            if main_results and "related_searches" in main_results:
                for item in main_results["related_searches"]:
                    if isinstance(item, dict) and "query" in item:
                        query_text = item["query"].strip()
                        if query_text and query_text not in keywords:
                            keywords.append(query_text)
                    elif isinstance(item, str) and item.strip() not in keywords:
                        keywords.append(item.strip())
            
            # También buscar variaciones (limitado para no exceder quota)
            variations = [
                f"{category} viral",
                f"{category} popular"
            ]
            
            for variation in variations[:2]:  # Solo 2 variaciones
                try:
                    var_results = self.search_google(variation, location, language, num_results=3)
                    if var_results and "related_searches" in var_results:
                        for item in var_results["related_searches"][:2]:
                            if isinstance(item, dict) and "query" in item:
                                query_text = item["query"].strip()
                                if query_text and query_text not in keywords:
                                    keywords.append(query_text)
                            elif isinstance(item, str) and item.strip() not in keywords:
                                keywords.append(item.strip())
                except Exception as e:
                    print(f"️ Error en variación '{variation}': {e}")
                    continue
                    
        except Exception as e:
            print(f"️ Error obteniendo trending keywords: {e}")
        
        return keywords[:15]  # Limitar a 15 keywords
    
    def analyze_search_intent(self, query: str, location: str = "Spain", 
                            language: str = "es") -> Dict[str, Any]:
        """
        Analiza la intención de búsqueda y proporciona insights
        
        Returns:
            Diccionario con análisis de intención de búsqueda
        """
        results = self.search_google(query, location, language, num_results=10)
        if not results:
            return {
                "query": query,
                "total_results": 0,
                "related_searches": [],
                "people_also_ask": [],
                "top_stories": [],
                "knowledge_graph": None
            }
        
        analysis = {
            "query": query,
            "total_results": 0,
            "related_searches": [],
            "people_also_ask": [],
            "top_stories": [],
            "knowledge_graph": None
        }
        
        try:
            # Total results
            if "search_information" in results and isinstance(results["search_information"], dict):
                analysis["total_results"] = results["search_information"].get("total_results", 0)
            
            # Related searches
            if "related_searches" in results:
                for item in results["related_searches"][:5]:
                    if isinstance(item, dict) and "query" in item:
                        analysis["related_searches"].append(item["query"].strip())
                    elif isinstance(item, str):
                        analysis["related_searches"].append(item.strip())
            
            # People Also Ask
            if "people_also_ask" in results:
                for item in results["people_also_ask"][:5]:
                    if isinstance(item, dict) and "question" in item:
                        analysis["people_also_ask"].append(item["question"].strip())
            
            # Top Stories
            if "top_stories" in results:
                for item in results["top_stories"][:5]:
                    if isinstance(item, dict):
                        analysis["top_stories"].append({
                            "title": item.get("title", "").strip(),
                            "link": item.get("link", "").strip(),
                            "source": item.get("source", "").strip()
                        })
            
            # Knowledge Graph
            if "knowledge_graph" in results and isinstance(results["knowledge_graph"], dict):
                kg = results["knowledge_graph"]
                analysis["knowledge_graph"] = {
                    "title": kg.get("title", "").strip(),
                    "type": kg.get("type", "").strip(),
                    "description": kg.get("description", "").strip()
                }
                
        except (KeyError, TypeError, AttributeError) as e:
            print(f"️ Error analizando search intent: {e}")
        
        return analysis

