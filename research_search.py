# research_search.py
"""
Módulo de búsqueda de investigación para guiones de video.
Usa Wikipedia + DuckDuckGo como alternativas gratuitas a Google Custom Search.
No requiere API keys ni facturación.
"""

import os
import re
from typing import List, Optional

# === Wikipedia API ===
WIKIPEDIA_AVAILABLE = False
try:
    import wikipediaapi
    WIKIPEDIA_AVAILABLE = True
except ImportError:
    print("️ wikipedia-api no instalado. pip install wikipedia-api")

# === DuckDuckGo Search ===
DUCKDUCKGO_AVAILABLE = False
try:
    from duckduckgo_search import DDGS
    DUCKDUCKGO_AVAILABLE = True
except ImportError:
    print("️ duckduckgo-search no instalado. pip install duckduckgo-search")

RESEARCH_AVAILABLE = WIKIPEDIA_AVAILABLE or DUCKDUCKGO_AVAILABLE


def _search_wikipedia_title(query: str, language: str) -> Optional[str]:
    """Busca el titulo mas cercano cuando la consulta no es un titulo exacto."""
    try:
        import requests

        response = requests.get(
            f"https://{language}.wikipedia.org/w/api.php",
            params={
                'action': 'query',
                'list': 'search',
                'srsearch': query,
                'format': 'json',
                'utf8': 1,
                'srlimit': 1,
            },
            headers={'User-Agent': 'VideoOptimizer/1.0 (research)'},
            timeout=10,
        )
        response.raise_for_status()
        matches = response.json().get('query', {}).get('search', [])
        return matches[0].get('title') if matches else None
    except Exception:
        return None


def search_wikipedia(query: str, language: str = 'es', max_sections: int = 5) -> List[str]:
    """
    Busca en Wikipedia y extrae información factual estructurada.
    
    Args:
        query: Término de búsqueda
        language: Idioma ('es' o 'en')
        max_sections: Máximo de secciones a extraer
    
    Returns:
        Lista de snippets con información factual
    """
    if not WIKIPEDIA_AVAILABLE:
        return []
    
    results = []
    
    try:
        wiki = wikipediaapi.Wikipedia(
            user_agent='VideoOptimizer/1.0 (research)',
            language=language
        )
        
        page = wiki.page(query)
        
        if not page.exists():
            # Intentar con búsqueda más simple
            simplified = _simplify_query(query)
            if simplified != query:
                page = wiki.page(simplified)
            
            # El idioma del guion no siempre coincide con el idioma del tema.
            if not page.exists():
                fallback_language = 'en' if language != 'en' else 'es'
                wiki_fallback = wikipediaapi.Wikipedia(
                    user_agent='VideoOptimizer/1.0 (research)',
                    language=fallback_language
                )
                page = wiki_fallback.page(query)
                if not page.exists():
                    page = wiki_fallback.page(simplified)

        if not page.exists():
            for search_language in dict.fromkeys((language, 'es', 'en')):
                matched_title = _search_wikipedia_title(simplified, search_language)
                if not matched_title:
                    continue
                matched_wiki = wikipediaapi.Wikipedia(
                    user_agent='VideoOptimizer/1.0 (research)',
                    language=search_language
                )
                matched_page = matched_wiki.page(matched_title)
                if matched_page.exists():
                    page = matched_page
                    break
        
        if not page.exists():
            print(f"   ️ Wikipedia: No se encontró artículo para '{query}'")
            return []
        
        # Extraer resumen (summary)
        summary = page.summary
        if summary:
            # Limpiar y truncar
            clean_summary = _clean_wiki_text(summary)
            if len(clean_summary) > 100:
                results.append(
                    f"Título: {page.title}\n"
                    f"Snippet: {clean_summary[:800]}\n"
                    f"URL: {page.fullurl}"
                )
        
        # Extraer secciones principales (para datos más detallados)
        section_count = 0
        for section in page.sections:
            if section_count >= max_sections:
                break
            
            # Saltar secciones no informativas
            skip_titles = [
                'referencias', 'bibliografía', 'véase también', 'enlaces externos',
                'notas', 'fuentes', 'references', 'bibliography', 'see also',
                'external links', 'notes', 'further reading', 'sources'
            ]
            if section.title.lower() in skip_titles:
                continue
            
            section_text = section.text
            if section_text and len(section_text) > 50:
                clean_text = _clean_wiki_text(section_text)
                if len(clean_text) > 50:
                    results.append(
                        f"Título: {page.title} - {section.title}\n"
                        f"Snippet: {clean_text[:600]}\n"
                        f"URL: {page.fullurl}"
                    )
                    section_count += 1
        
        if results:
            print(f"    Wikipedia: {len(results)} fragmentos de '{page.title}'")
        
    except Exception as e:
        print(f"   ️ Error en Wikipedia: {e}")
    
    return results


def search_duckduckgo(query: str, max_results: int = 5) -> List[str]:
    """
    Busca en DuckDuckGo y extrae snippets relevantes.
    
    Args:
        query: Término de búsqueda
        max_results: Máximo de resultados
    
    Returns:
        Lista de snippets con información
    """
    if not DUCKDUCKGO_AVAILABLE:
        return []
    
    results = []
    
    try:
        with DDGS() as ddgs:
            search_results = list(ddgs.text(query, max_results=max_results))
            
            for item in search_results:
                title = item.get('title', '')
                body = item.get('body', '')
                href = item.get('href', '')
                
                # Filtrar resultados en scripts no-latinos (chino, japonés, etc.)
                if body and len(body) > 30:
                    latin_chars = len(re.findall(r'[a-záéíóúñüàèìòùâêîôûäëïöüçß]', body, re.IGNORECASE))
                    if latin_chars < len(body) * 0.3:
                        continue
                    
                    results.append(
                        f"Título: {title}\n"
                        f"Snippet: {body}\n"
                        f"URL: {href}"
                    )
        
        if results:
            print(f"    DuckDuckGo: {len(results)} resultados")
    
    except Exception as e:
        print(f"   ️ Error en DuckDuckGo: {e}")
    
    return results


def search_research_context(topic: str, category: str = '', 
                            language: str = 'es', max_results: int = 8) -> List[str]:
    """
    Función principal de búsqueda de investigación.
    Combina Wikipedia + DuckDuckGo para obtener contexto factual.
    
    Reemplaza a search_google_trends() para el pipeline de guiones.
    
    Args:
        topic: Tema del video
        category: Categoría (opcional)
        language: Idioma
        max_results: Máximo de resultados totales
    
    Returns:
        Lista de snippets para usar como contexto de investigación
    """
    if not RESEARCH_AVAILABLE:
        print("   ️ No hay servicios de búsqueda disponibles")
        return []
    
    all_results = []
    search_query = f"{topic} {category}".strip()
    
    # 1. Wikipedia primero (fuente más confiable para hechos)
    if WIKIPEDIA_AVAILABLE:
        print("    Buscando en Wikipedia...")
        wiki_results = search_wikipedia(topic, language=language, max_sections=4)
        all_results.extend(wiki_results)
        
        # Si no encontró en el idioma original, intentar en inglés
        if not wiki_results and language != 'en':
            print("    Reintentando Wikipedia en inglés...")
            wiki_results_en = search_wikipedia(topic, language='en', max_sections=4)
            all_results.extend(wiki_results_en)
    
    # 2. DuckDuckGo para complementar (más variedad de fuentes)
    remaining = max_results - len(all_results)
    if DUCKDUCKGO_AVAILABLE and remaining > 0:
        print("    Buscando en DuckDuckGo...")
        ddg_results = search_duckduckgo(search_query, max_results=min(remaining, 5))
        all_results.extend(ddg_results)
    
    # Filtrar resultados vacíos o de error
    valid_results = [
        r for r in all_results 
        if r and not r.startswith("Error") and "Snippet:" in r
    ]
    
    if valid_results:
        print(f"    Total: {len(valid_results)} fragmentos de investigación obtenidos")
    else:
        print("   ️ No se obtuvo contexto de investigación")
    
    return valid_results[:max_results]


def _simplify_query(query: str) -> str:
    """Simplifica una consulta para mejorar búsqueda en Wikipedia."""
    # Remover palabras comunes que no ayudan en Wikipedia
    stop_words = [
        'historia de', 'historia del', 'la historia de', 'el', 'la', 'los', 'las',
        'del', 'de', 'en', 'un', 'una', 'sobre', 'acerca de',
        'fallida', 'fallido', 'fallidas', 'fallidos', 'a',
        'history of', 'the', 'a', 'an', 'about', 'of'
    ]
    
    simplified = query
    for word in stop_words:
        simplified = re.sub(rf'\b{re.escape(word)}\b', '', simplified, flags=re.IGNORECASE)
    
    simplified = re.sub(r'\s+', ' ', simplified).strip()
    return simplified if simplified else query


def _clean_wiki_text(text: str) -> str:
    """Limpia texto de Wikipedia para uso como contexto."""
    if not text:
        return ""
    
    # Remover referencias [1], [2], etc.
    cleaned = re.sub(r'\[\d+\]', '', text)
    # Remover caracteres de control
    cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', cleaned)
    # Normalizar espacios
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned


def _search_google_custom(topic: str, max_results: int = 8) -> list:
    """Busca usando Google Custom Search API (resultados de alta calidad)."""
    results = []
    try:
        google_api_key = os.getenv("GOOGLE_API_KEY")
        google_cx = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
        if not google_api_key or not google_cx:
            return []
        
        from googleapiclient.discovery import build
        service = build('customsearch', 'v1', developerKey=google_api_key)
        res = service.cse().list(q=topic, cx=google_cx, num=min(max_results, 10)).execute()
        
        for item in res.get('items', []):
            title = item.get('title', '')
            snippet = item.get('snippet', '').replace('\n', ' ')
            url = item.get('link', '')
            
            if snippet and len(snippet) > 20:
                results.append({
                    'title': title,
                    'snippet': snippet[:300] + ('...' if len(snippet) > 300 else ''),
                    'url': url,
                    'source': 'Google',
                    'full_text': snippet
                })
        
        if results:
            print(f"    Google Search: {len(results)} resultados")
    except Exception as e:
        print(f"   ️ Error Google Search: {e}")
    
    return results


def _search_serp_api(topic: str, max_results: int = 8) -> list:
    """Busca usando SERP API (resultados estructurados de Google)."""
    results = []
    try:
        serp_key = os.getenv("SERP_API_KEY")
        if not serp_key or "TU_API_KEY" in serp_key.upper():
            return []
        
        import requests
        params = {
            "q": topic,
            "api_key": serp_key,
            "engine": "google",
            "hl": "es",
            "gl": "es",
            "num": min(max_results, 10)
        }
        response = requests.get("https://serpapi.com/search", params=params, timeout=15)
        if response.status_code != 200:
            return []
        
        data = response.json()
        
        # Resultados orgánicos
        for item in data.get('organic_results', [])[:max_results]:
            title = item.get('title', '')
            snippet = item.get('snippet', '')
            url = item.get('link', '')
            
            if snippet and len(snippet) > 20:
                results.append({
                    'title': title,
                    'snippet': snippet[:300] + ('...' if len(snippet) > 300 else ''),
                    'url': url,
                    'source': 'Google',
                    'full_text': snippet
                })
        
        # Knowledge Graph si existe
        kg = data.get('knowledge_graph', {})
        if kg and isinstance(kg, dict):
            kg_desc = kg.get('description', '')
            kg_title = kg.get('title', '')
            if kg_desc and len(kg_desc) > 30:
                results.insert(0, {
                    'title': f" {kg_title}" if kg_title else "Knowledge Graph",
                    'snippet': kg_desc[:300] + ('...' if len(kg_desc) > 300 else ''),
                    'url': kg.get('source', {}).get('link', '') if isinstance(kg.get('source'), dict) else '',
                    'source': 'Google KG',
                    'full_text': kg_desc
                })
        
        if results:
            print(f"    SERP API: {len(results)} resultados")
    except Exception as e:
        print(f"   ️ Error SERP API: {e}")
    
    return results


def search_topic_results(topic: str, language: str = 'es', max_results: int = 10) -> list:
    """
    Busca resultados estructurados sobre un tema para mostrar en la UI.
    Prioridad: Google Search > SERP API > Wikipedia > DuckDuckGo (fallback).
    
    Args:
        topic: Tema a buscar
        language: Idioma ('es' o 'en')
        max_results: Máximo de resultados totales
    
    Returns:
        Lista de dicts: [{'title': str, 'snippet': str, 'url': str, 'source': str, 'full_text': str}]
    """
    all_results = []
    
    # 1. Google Custom Search (mejor calidad de resultados)
    print("    Buscando en Google...")
    google_results = _search_google_custom(topic, max_results=max_results)
    all_results.extend(google_results)
    
    # 2. Si Google no dio resultados, intentar SERP API
    if not all_results:
        print("    Intentando SERP API...")
        serp_results = _search_serp_api(topic, max_results=max_results)
        all_results.extend(serp_results)
    
    # 3. Wikipedia para complementar (buena para contexto factual)
    remaining = max_results - len(all_results)
    if WIKIPEDIA_AVAILABLE and remaining > 0:
        try:
            wiki = wikipediaapi.Wikipedia(
                user_agent='VideoOptimizer/1.0 (research)',
                language=language
            )
            
            page = wiki.page(topic)
            
            if not page.exists():
                simplified = _simplify_query(topic)
                if simplified != topic:
                    page = wiki.page(simplified)
            
            if not page.exists() and language != 'en':
                wiki_en = wikipediaapi.Wikipedia(
                    user_agent='VideoOptimizer/1.0 (research)',
                    language='en'
                )
                page = wiki_en.page(topic)
                if not page.exists():
                    page = wiki_en.page(_simplify_query(topic))
            
            if page.exists():
                summary = _clean_wiki_text(page.summary)
                if summary and len(summary) > 50:
                    all_results.append({
                        'title': f" {page.title}",
                        'snippet': summary[:300] + ('...' if len(summary) > 300 else ''),
                        'url': page.fullurl,
                        'source': 'Wikipedia',
                        'full_text': summary[:1500]
                    })
                
                skip_titles = [
                    'referencias', 'bibliografía', 'véase también', 'enlaces externos',
                    'notas', 'fuentes', 'references', 'bibliography', 'see also',
                    'external links', 'notes', 'further reading', 'sources'
                ]
                for section in page.sections:
                    if len(all_results) >= max_results:
                        break
                    if section.title.lower() in skip_titles:
                        continue
                    section_text = _clean_wiki_text(section.text)
                    if section_text and len(section_text) > 50:
                        all_results.append({
                            'title': f" {page.title} — {section.title}",
                            'snippet': section_text[:300] + ('...' if len(section_text) > 300 else ''),
                            'url': page.fullurl,
                            'source': 'Wikipedia',
                            'full_text': section_text[:1500]
                        })
        except Exception as e:
            print(f"   ️ Error Wikipedia: {e}")
    
    # 4. DuckDuckGo solo como último recurso si no hay nada
    remaining = max_results - len(all_results)
    if DUCKDUCKGO_AVAILABLE and remaining > 0 and len(all_results) < 3:
        try:
            print("    Complementando con DuckDuckGo...")
            with DDGS() as ddgs:
                search_results = list(ddgs.text(topic, max_results=min(remaining + 2, 8)))
                
                for item in search_results:
                    if len(all_results) >= max_results:
                        break
                    
                    title = item.get('title', '')
                    body = item.get('body', '')
                    href = item.get('href', '')
                    
                    if not body or len(body) < 30:
                        continue
                    
                    # Filtrar resultados no-latinos
                    latin_chars = len(re.findall(r'[a-záéíóúñüàèìòùâêîôûäëïöüçß]', body, re.IGNORECASE))
                    if latin_chars < len(body) * 0.3:
                        continue
                    
                    all_results.append({
                        'title': title,
                        'snippet': body[:300] + ('...' if len(body) > 300 else ''),
                        'url': href,
                        'source': 'DuckDuckGo',
                        'full_text': body
                    })
        except Exception as e:
            print(f"   ️ Error DuckDuckGo: {e}")
    
    print(f"    search_topic_results: {len(all_results)} resultados para '{topic}'")
    return all_results[:max_results]


# === Test rápido ===
if __name__ == "__main__":
    print("=" * 60)
    print(" TEST DE BÚSQUEDA DE INVESTIGACIÓN")
    print("=" * 60)
    
    print(f"\nWikipedia disponible: {WIKIPEDIA_AVAILABLE}")
    print(f"DuckDuckGo disponible: {DUCKDUCKGO_AVAILABLE}")
    
    # Test con un tema histórico
    topic = "Batalla de las Termópilas"
    print(f"\n Buscando: '{topic}'")
    print("-" * 40)
    
    results = search_research_context(topic, category="Historia", language='es')
    
    print(f"\n Resultados: {len(results)}")
    for i, r in enumerate(results, 1):
        print(f"\n--- Resultado {i} ---")
        # Mostrar solo las primeras líneas
        lines = r.split('\n')
        for line in lines[:2]:
            print(f"  {line[:120]}")
    
    print("\n" + "=" * 60)
    print(" Test completado")
