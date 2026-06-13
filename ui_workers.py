import json
from PyQt6.QtCore import QThread, pyqtSignal

try:
    from trend_spotter import get_trending_topics, analyze_trends_for_video_ideas
except ImportError:
    pass

try:
    from google_search_api import search_youtube_trends, search_google_trends
except ImportError:
    pass

try:
    from research_search import search_topic_results, RESEARCH_AVAILABLE
except ImportError:
    RESEARCH_AVAILABLE = False

class AnalysisWorker(QThread):
    """Worker thread para análisis de temas"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, topic, category, gemini_client):
        super().__init__()
        self.topic = topic
        self.category = category
        self.gemini_client = gemini_client
    
    def run(self):
        try:
            if not self.gemini_client:
                self.error.emit("Gemini AI no está disponible")
                return
            
            self.progress.emit("Analizando tema con Gemini AI...")
            
            prompt = f"""
            Eres un experto en SEO de YouTube para canales sobre {self.category}.
            Analiza el siguiente tema y genera:
            1. Un TÍTULO optimizado (clickbait profesional, <70 caracteres)
            2. Una DESCRIPCIÓN detallada (2-3 párrafos, SEO optimizado)
            3. 10-15 TAGS relevantes
            
            Tema: {self.topic}
            
            Responde ÚNICAMENTE con JSON:
            {{
                "title": "El título optimizado",
                "description": "La descripción completa...",
                "tags": ["tag1", "tag2", ...]
            }}
            """
            
            response = self.gemini_client._generate(prompt)
            
            # Verificar si la respuesta es un error
            if not response or response.startswith("ERROR"):
                self.error.emit(f"Error de IA: {response if response else 'Sin respuesta'}")
                return
            
            # Intentar parsear JSON con json_repair (más robusto)
            try:
                try:
                    import json_repair
                    data = json_repair.repair_json(response, return_objects=True)
                except ImportError:
                    # Fallback simple si no está instalado
                    print("️ json_repair no instalado, usando limpieza manual simple")
                    clean_json = response.strip().replace("```json", "").replace("```", "")
                    start = clean_json.find('{')
                    end = clean_json.rfind('}') + 1
                    if start >= 0 and end > start:
                        clean_json = clean_json[start:end]
                    data = json.loads(clean_json)
                
                # Validar estructura básica
                if not isinstance(data, dict):
                    # Si devolvió una lista u otra cosa, intentar envolver o fallar
                    self.error.emit("La respuesta de IA no es un objeto JSON válido")
                    return

                self.finished.emit(data)

            except Exception as json_err:
                error_msg = f"Error procesando JSON: {str(json_err)}\n"
                error_msg += f"Respuesta original: {response[:100]}..."
                self.error.emit(error_msg)
                return
            
        except Exception as e:
            self.error.emit(f"Error en análisis: {str(e)}")


class ResearchWorker(QThread):
    """Worker thread para buscar información sobre un tema en fuentes externas"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, topic, language='es'):
        super().__init__()
        self.topic = topic
        self.language = language
    
    def run(self):
        try:
            self.progress.emit(f" Buscando información sobre: {self.topic}...")
            
            from research_search import search_topic_results, RESEARCH_AVAILABLE
            if not RESEARCH_AVAILABLE:
                self.error.emit(
                    "No hay servicios de búsqueda disponibles.\n"
                    "Instala: pip install wikipedia-api duckduckgo-search"
                )
                return
            
            results = search_topic_results(self.topic, language=self.language, max_results=10)
            
            if not results:
                self.error.emit(f"No se encontraron resultados para: {self.topic}")
                return
            
            self.progress.emit(f" Se encontraron {len(results)} resultados")
            self.finished.emit(results)
            
        except Exception as e:
            self.error.emit(f"Error en búsqueda: {str(e)}")


class TrendsWorker(QThread):
    """Worker thread para obtener tendencias"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, gemini_client, categories=None):
        super().__init__()
        self.gemini_client = gemini_client
        self.categories = categories or [
            'Eventos naturales extremos', 'Ciencia/Tecnología actual',
            'Historia antigua/civilizaciones', 'Historia militar/guerras',
            'Misterios con datos', 'Conspiraciones verificables',
            'Actualidad científica', 'Documentales'
        ]
    
    def run(self):
        try:
            # Aleatorizar región para variedad en el dashboard
            import random
            regions = ['US', 'ES', 'MX', 'AR', 'GB', 'CA']
            selected_region = random.choice(regions)
            
            self.progress.emit(f"Obteniendo tendencias de Google ({selected_region})...")
            # Pasar gemini_client para fallback de IA si es necesario
            trends_list = get_trending_topics(selected_region, self.gemini_client)
            
            if not trends_list:
                self.error.emit("No se pudieron obtener tendencias (APIs y Fallback fallaron)")
                return
            
            self.progress.emit("Analizando tendencias con Gemini...")
            
            # Si se proporcionaron categorías específicas, usarlas. Si no, usar una selección aleatoria de las por defecto para variedad.
            selected_categories = self.categories
            if len(selected_categories) > 3:
                # Mezclar y tomar 3-4 para enfocar el análisis
                random.shuffle(selected_categories)
                selected_categories = selected_categories[:4]

            ideas_data = analyze_trends_for_video_ideas(trends_list, selected_categories, self.gemini_client)
            
            self.finished.emit(ideas_data)
            
        except Exception as e:
            self.error.emit(str(e))


class SearchWorker(QThread):
    """Worker thread para búsquedas de Google/YouTube"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, query, search_type):
        super().__init__()
        self.query = query
        self.search_type = search_type
    
    def run(self):
        try:
            self.progress.emit(f"Buscando en {self.search_type}...")
            
            if self.search_type == "YouTube":
                results = search_youtube_trends(self.query, max_results=10)
            else:
                results = search_google_trends(self.query, max_results=10)
            
            self.finished.emit(results)
            
        except Exception as e:
            self.error.emit(str(e))


