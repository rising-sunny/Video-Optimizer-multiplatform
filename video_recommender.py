# video_recommender.py
"""
Sistema inteligente de recomendación de videos para maximizar visitas y suscriptores.
Combina múltiples fuentes de datos para generar recomendaciones personalizadas.
"""

import os
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv
import requests
import json

load_dotenv()

try:
    from google_search_api import GOOGLE_API_KEY
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False
    GOOGLE_API_KEY = None

try:
    from pytrends.request import TrendReq
    TRENDS_AVAILABLE = True
except ImportError:
    TRENDS_AVAILABLE = False

try:
    from gemini_ai_client import GeminiAiClient
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from serp_api_client import SerpApiClient, SERP_API_AVAILABLE
except ImportError:
    SERP_API_AVAILABLE = False
    SerpApiClient = None
    print("️ serp_api_client.py no encontrado. SERP API no estará disponible.")


class VideoRecommender:
    """
    Sistema de recomendación de videos que analiza:
    - Tendencias de YouTube
    - Búsquedas en Google Trends
    - Competencia y engagement
    - Potencial de crecimiento
    - Métricas y historial del canal del usuario (si está configurado)
    """
    
    def __init__(self, channel_id: Optional[str] = None, channel_handle: Optional[str] = None):
        """
        Inicializa el recomendador.
        
        Args:
            channel_id: ID del canal de YouTube del usuario (opcional)
            channel_handle: Handle del canal del usuario (opcional, ej: "StunningRevelations")
        """
        self.gemini_client = GeminiAiClient() if GEMINI_AVAILABLE else None
        self.youtube_api_key = GOOGLE_API_KEY
        self._youtube_api_disabled = False
        self._youtube_api_warning_logged = False
        
        # Inicializar SERP API Client para refinar búsquedas
        self.serp_client = SerpApiClient() if SERP_API_AVAILABLE else None
        if self.serp_client and SERP_API_AVAILABLE:
            print(" SERP API Client inicializado - Búsquedas refinadas activadas")
        
        # Inicializar analizador de canal si se proporciona información
        self.channel_analyzer = None
        if channel_id or channel_handle:
            try:
                from youtube_channel_analyzer import YouTubeChannelAnalyzer
                self.channel_analyzer = YouTubeChannelAnalyzer(channel_id, channel_handle)
            except ImportError:
                print("️ youtube_channel_analyzer no disponible")
    
    def _is_youtube_access_not_configured(self, error: Exception) -> bool:
        """Detecta si YouTube Data API v3 no está habilitada en el proyecto."""
        error_text = str(error).lower()
        return (
            'accessnotconfigured' in error_text
            or 'has not been used in project' in error_text
            or 'youtube data api v3 has not been used' in error_text
        )

    def _disable_youtube_api_for_session(self, error: Exception) -> None:
        """Desactiva consultas a YouTube API en esta sesión para evitar spam."""
        self._youtube_api_disabled = True
        if not self._youtube_api_warning_logged:
            print(
                "️ YouTube Data API deshabilitada/no habilitada en GCP. "
                "Se omiten búsquedas de YouTube en esta sesión."
            )
            self._youtube_api_warning_logged = True

    def get_recommendations(self, category: str, language: str = 'es', max_recommendations: int = 10) -> List[Dict[str, Any]]:
        """
        Genera recomendaciones de videos basadas en la temática del canal.
        Si hay un canal configurado, también analiza métricas e historial.
        
        Args:
            category: Temática del canal (historia, ciencia, tecnología, etc.)
            language: Idioma para las recomendaciones
            max_recommendations: Número máximo de recomendaciones
        
        Returns:
            Lista de recomendaciones con análisis detallado
        """
        recommendations = []
        
        # 1. Obtener tendencias de Google Trends (global, filtradas por categoría)
        trends = self._get_google_trends(category=category)
        
        # 2. NUEVO: Refinar búsquedas con SERP API
        serp_data = self._refine_search_with_serp(category, language)
        
        # 3. Buscar videos populares en YouTube relacionados con la categoría
        # Usar keywords refinados de SERP si están disponibles
        search_queries = [category]
        if serp_data.get('trending_keywords'):
            search_queries.extend(serp_data['trending_keywords'][:3])
        if serp_data.get('related_searches'):
            search_queries.extend(serp_data['related_searches'][:2])
        
        # Limitar queries para no exceder quota
        youtube_trends = self._get_youtube_trends(category, refined_queries=search_queries[:5])
        
        # 4. Analizar competencia y engagement
        competition_analysis = self._analyze_competition(category, youtube_trends)
        
        # 5. Analizar canal del usuario (si está configurado)
        channel_context = None
        if self.channel_analyzer:
            try:
                channel_context = self.channel_analyzer.get_personalized_recommendations_context()
                metrics = (channel_context or {}).get('channel_metrics') or {}
                performance = (channel_context or {}).get('performance_analysis') or {}
                print(f" Canal analizado: {metrics.get('channel_name', 'Unknown')}")
                print(f"   Suscriptores: {metrics.get('subscribers', 0):,}")
                videos_count = performance.get('total_videos_analyzed', 0)
                print(f"   Videos analizados: {videos_count}")
            except Exception as e:
                print(f"️ Error analizando canal: {e}")
                channel_context = None
        
        # 6. Usar IA para generar recomendaciones inteligentes (con contexto del canal y SERP)
        ai_recommendations = self._generate_ai_recommendations(
            category, trends, youtube_trends, competition_analysis, language, 
            channel_context, serp_data  # Agregar serp_data
        )
        
        # 6. Combinar y rankear recomendaciones (personalizadas si hay canal)
        recommendations = self._rank_recommendations(ai_recommendations, competition_analysis, channel_context)
        
        return recommendations[:max_recommendations]
    
    def _get_google_trends(self, category: str = None) -> List[str]:
        """Obtiene tendencias actuales de Google Trends (búsqueda global)"""
        if not TRENDS_AVAILABLE:
            return []
        
        trends_list = []
        
        # Buscar tendencias globales (múltiples países para audiencia global)
        # Lista ampliada y aleatorizada para variedad
        import random
        countries_to_check = [
            'united_states', 'spain', 'mexico', 'argentina', 
            'colombia', 'chile', 'peru', 'united_kingdom', 'canada'
        ]
        random.shuffle(countries_to_check)
        
        try:
            pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25))  # Inglés para búsqueda global
            
            for country in countries_to_check[:3]:  # Probar 3 países aleatorios
                try:
                    trending_data = pytrends.trending_searches(pn=country)
                    if trending_data is not None and not trending_data.empty:
                        country_trends = trending_data.head(10)[0].tolist()
                        # Agregar solo tendencias nuevas (evitar duplicados)
                        for trend in country_trends:
                            if trend not in trends_list:
                                trends_list.append(trend)
                except Exception as e:
                    continue  # Continuar con siguiente país si falla
            
            # Si hay categoría, buscar tendencias específicas de esa categoría
            if category:
                try:
                    # Buscar tendencias relacionadas con la categoría
                    pytrends.build_payload([category], cat=0, timeframe='today 3-m', geo='', gprop='')
                    related_topics = pytrends.related_topics()
                    if related_topics and category in related_topics:
                        topics_data = related_topics[category].get('rising', [])
                        if topics_data is not None and not topics_data.empty:
                            category_trends = topics_data.head(5)['topic_title'].tolist()
                            for trend in category_trends:
                                if trend not in trends_list:
                                    trends_list.append(trend)
                except Exception as e:
                    pass  # Si falla, continuar sin estas tendencias
            
            if trends_list:
                print(f" {len(trends_list)} tendencias globales obtenidas de Google Trends")
                return trends_list[:20]  # Limitar a 20
        except Exception as e:
            print(f"️ Error obteniendo Google Trends: {e}")
        
        return []
    
    def _get_youtube_trends(self, category: str, refined_queries: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Obtiene videos populares de YouTube relacionados con la categoría"""
        if self._youtube_api_disabled or not YOUTUBE_API_AVAILABLE or not self.youtube_api_key:
            return []
        
        try:
            from googleapiclient.discovery import build
            youtube = build('youtube', 'v3', developerKey=self.youtube_api_key)
            
            # Usar queries refinados si están disponibles, sino usar los predeterminados
            if refined_queries:
                search_queries = refined_queries[:3]  # Limitar a 3 para no exceder quota
            else:
                # Buscar videos populares en la categoría (queries optimizados para audiencia global)
                # Aleatorizar modificadores para variedad
                import random
                modifiers = [
                    "documentary", "explained", "mystery", "viral", "analysis", 
                    "history", "future", "top 10", "review", "tutorial", 
                    "secret", "truth", "guide", "2024", "2025", "vs", "deep dive"
                ]
                random.shuffle(modifiers)
                
                search_queries = [
                    f"{category} {modifiers[0]}",
                    f"{category} {modifiers[1]}",
                    f"{category} {modifiers[2]}",
                    f"{category} {modifiers[3]}"
                ]
            
            all_videos = []
            for query in search_queries[:2]:  # Limitar a 2 búsquedas para no exceder quota
                try:
                    request = youtube.search().list(
                        part='snippet',
                        q=query,
                        type='video',
                        order='viewCount',  # Ordenar por más vistas (global)
                        maxResults=10,
                        videoDefinition='high',
                        videoDuration='medium',  # Videos de 4-20 minutos
                        relevanceLanguage=None,  # Sin limitación de idioma (global)
                        regionCode=None  # Sin limitación de región (global)
                    )
                    response = request.execute()
                    
                    # Obtener IDs de todos los videos para obtener estadísticas en batch
                    video_ids = [item['id']['videoId'] for item in response.get('items', [])]
                    
                    if not video_ids:
                        continue
                    
                    # Obtener estadísticas detalladas en batch
                    stats_request = youtube.videos().list(
                        part='statistics,contentDetails',
                        id=','.join(video_ids)
                    )
                    stats_response = stats_request.execute()
                    
                    # Crear diccionario de estadísticas por video_id
                    stats_dict = {item['id']: item for item in stats_response.get('items', [])}
                    
                    for item in response.get('items', []):
                        video_id = item['id']['videoId']
                        stats = stats_dict.get(video_id)
                        
                        if not stats:
                            continue
                        
                        snippet = item['snippet']
                        statistics = stats['statistics']
                        
                        view_count = int(statistics.get('viewCount', 0))
                        like_count = int(statistics.get('likeCount', 0))
                        comment_count = int(statistics.get('commentCount', 0))
                        
                        # Calcular engagement rate
                        engagement_rate = 0
                        if view_count > 0:
                            engagement_rate = ((like_count + comment_count) / view_count) * 100
                        
                        all_videos.append({
                            'title': snippet['title'],
                            'channel': snippet['channelTitle'],
                            'views': view_count,
                            'likes': like_count,
                            'comments': comment_count,
                            'engagement_rate': engagement_rate,
                            'published': snippet['publishedAt'],
                            'video_id': video_id,
                            'url': f"https://www.youtube.com/watch?v={video_id}"
                        })
                except Exception as e:
                    if self._is_youtube_access_not_configured(e):
                        self._disable_youtube_api_for_session(e)
                        break
                    print(f"️ Error en búsqueda YouTube '{query}': {e}")
                    continue
            
            return all_videos
        except Exception as e:
            if self._is_youtube_access_not_configured(e):
                self._disable_youtube_api_for_session(e)
                return []
            print(f"️ Error obteniendo tendencias de YouTube: {e}")
            return []
    
    def _refine_search_with_serp(self, category: str, language: str = 'es') -> Dict[str, Any]:
        """
        Refina las búsquedas usando SERP API para obtener:
        - Keywords trending relacionados
        - Preguntas frecuentes (People Also Ask)
        - Búsquedas relacionadas
        - Análisis de intención de búsqueda
        
        Búsqueda global para audiencia internacional.
        
        Returns:
            Diccionario con datos refinados de búsqueda
        """
        if not self.serp_client or not SERP_API_AVAILABLE:
            return {
                'trending_keywords': [],
                'related_searches': [],
                'people_also_ask': [],
                'search_intent': {}
            }
        
        try:
            print(f" Refinando búsquedas globales con SERP API para categoría: {category}...")
            
            # Para audiencia global, usar ubicaciones principales y combinar resultados
            # Priorizar US (mayor volumen) pero también incluir otros países
            locations_to_try = ["United States", "Spain", "Mexico"]  # Mix global
            all_trending_keywords = []
            all_related_searches = []
            all_people_also_ask = []
            search_intent = {}
            
            # 1. Obtener keywords trending (de múltiples ubicaciones)
            for location in locations_to_try[:2]:  # Limitar a 2 para no exceder quota
                try:
                    keywords = self.serp_client.get_trending_keywords(
                        category, location=location, language=language
                    )
                    # Combinar sin duplicados
                    for kw in keywords:
                        if kw not in all_trending_keywords:
                            all_trending_keywords.append(kw)
                except Exception as e:
                    continue
            
            if all_trending_keywords:
                print(f"    {len(all_trending_keywords)} keywords trending globales encontrados")
            
            # 2. Obtener búsquedas relacionadas (usar US como base global)
            try:
                related_searches = self.serp_client.get_related_searches(
                    f"{category} viral", location="United States", language=language
                )
                all_related_searches = related_searches
                print(f"    {len(all_related_searches)} búsquedas relacionadas encontradas")
            except Exception as e:
                print(f"   ️ Error obteniendo related searches: {e}")
            
            # 3. Obtener People Also Ask (usar US como base global)
            try:
                people_also_ask = self.serp_client.get_people_also_ask(
                    f"{category} trending", location="United States", language=language
                )
                all_people_also_ask = people_also_ask
                print(f"    {len(all_people_also_ask)} preguntas frecuentes encontradas")
            except Exception as e:
                print(f"   ️ Error obteniendo People Also Ask: {e}")
            
            # 4. Analizar intención de búsqueda (usar US como base global)
            try:
                search_intent = self.serp_client.analyze_search_intent(
                    f"{category} viral videos", location="United States", language=language
                )
            except Exception as e:
                print(f"   ️ Error analizando search intent: {e}")
            
            return {
                'trending_keywords': all_trending_keywords[:15],  # Limitar a 15
                'related_searches': all_related_searches,
                'people_also_ask': all_people_also_ask,
                'search_intent': search_intent
            }
        except Exception as e:
            print(f"️ Error refinando búsquedas con SERP API: {e}")
            return {
                'trending_keywords': [],
                'related_searches': [],
                'people_also_ask': [],
                'search_intent': {}
            }
    
    def _analyze_competition(self, category: str, youtube_videos: List[Dict]) -> Dict[str, Any]:
        """Analiza la competencia y calcula métricas de oportunidad"""
        if not youtube_videos:
            return {
                'avg_views': 0,
                'avg_engagement': 0,
                'competition_level': 'unknown',
                'opportunity_score': 0
            }
        
        # Calcular promedios
        total_views = sum(v.get('views', 0) for v in youtube_videos)
        total_engagement = sum(v.get('engagement_rate', 0) for v in youtube_videos)
        avg_views = total_views / len(youtube_videos) if youtube_videos else 0
        avg_engagement = total_engagement / len(youtube_videos) if youtube_videos else 0
        
        # Determinar nivel de competencia
        if avg_views > 1000000:
            competition_level = 'high'
        elif avg_views > 100000:
            competition_level = 'medium'
        else:
            competition_level = 'low'
        
        # Calcular oportunidad (inversamente proporcional a competencia, proporcional a engagement)
        opportunity_score = (avg_engagement / 10) * (1 / (competition_level == 'high' and 3 or competition_level == 'medium' and 2 or 1))
        
        return {
            'avg_views': avg_views,
            'avg_engagement': avg_engagement,
            'competition_level': competition_level,
            'opportunity_score': opportunity_score,
            'sample_size': len(youtube_videos)
        }
    
    def _generate_ai_recommendations(self, category: str, trends: List[str], 
                                    youtube_trends: List[Dict], competition: Dict[str, Any],
                                    language: str, channel_context: Optional[Dict[str, Any]] = None,
                                    serp_data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Usa IA para generar recomendaciones inteligentes de videos"""
        if not self.gemini_client:
            return []
        
        # Preparar contexto para la IA
        trends_str = "\n".join(f"- {t}" for t in trends[:10]) if trends else "No hay tendencias disponibles"
        
        youtube_summary = ""
        if youtube_trends:
            top_videos = sorted(youtube_trends, key=lambda x: x.get('views', 0), reverse=True)[:5]
            youtube_summary = "\n".join([
                f"- '{v['title']}' ({v['views']:,} vistas, {v['engagement_rate']:.2f}% engagement)"
                for v in top_videos
            ])
        else:
            youtube_summary = "No hay datos de YouTube disponibles"
        
        competition_info = f"""
        Nivel de competencia: {competition.get('competition_level', 'unknown')}
        Promedio de vistas: {competition.get('avg_views', 0):,.0f}
        Engagement promedio: {competition.get('avg_engagement', 0):.2f}%
        Oportunidad: {competition.get('opportunity_score', 0):.2f}/10
        """
        
        # Agregar datos de SERP API
        serp_info = ""
        if serp_data:
            trending_kw = serp_data.get('trending_keywords', [])
            related_searches = serp_data.get('related_searches', [])
            paa = serp_data.get('people_also_ask', [])
            search_intent = serp_data.get('search_intent', {})
            
            serp_info = f"""
        DATOS REFINADOS DE SERP API (Búsquedas Optimizadas):
        - Keywords trending: {', '.join(trending_kw[:10]) if trending_kw else 'N/A'}
        - Búsquedas relacionadas: {', '.join(related_searches[:5]) if related_searches else 'N/A'}
        - Preguntas frecuentes (People Also Ask): {len(paa)} preguntas encontradas
        - Total de resultados en Google: {search_intent.get('total_results', 0):,} resultados
        - Preguntas clave para contenido: {', '.join([q.get('question', '') for q in paa[:3]]) if paa else 'N/A'}
        """
        
        # Agregar contexto del canal si está disponible
        channel_info = ""
        if channel_context:
            metrics = channel_context.get('channel_metrics') or {}
            performance = channel_context.get('performance_analysis') or {}
            monetization = channel_context.get('monetization_gap') or {}
            
            # Determinar estrategia según brecha de monetización
            priority = monetization.get('priority', 'both')
            strategy_focus = ""
            
            if priority == 'subscribers':
                strategy_focus = """
        ESTRATEGIA PRIORITARIA: ENFOQUE EN SUSCRIPTORES
        - Necesitas {subscribers_gap:.0f} suscriptores más para monetizar
        - Prioriza videos con alto potencial de conversión a suscriptores
        - Recomienda temas que generen engagement y llamen a la acción
        - Incluye CTAs fuertes para suscripción en las recomendaciones
                """.format(**monetization)
            elif priority == 'watch_hours':
                strategy_focus = """
        ESTRATEGIA PRIORITARIA: ENFOQUE EN HORAS DE VISUALIZACIÓN
        - Necesitas {watch_hours_gap:.1f} horas más de visualización para monetizar
        - Prioriza videos LARGOS (15-30 minutos) que maximicen tiempo de visualización
        - Recomienda temas que mantengan a la audiencia enganchada
        - Considera series o contenido serializado que genere retención
                """.format(**monetization)
            elif priority == 'both':
                strategy_focus = """
        ESTRATEGIA PRIORITARIA: ENFOQUE BALANCEADO
        - Necesitas {subscribers_gap:.0f} suscriptores más Y {watch_hours_gap:.1f} horas más
        - Balancea entre videos que atraigan suscriptores y maximicen horas
        - Recomienda mix: algunos videos cortos virales (suscriptores) + videos largos (horas)
        - Prioriza temas que ya funcionan bien en tu canal para maximizar ambos
                """.format(**monetization)
            else:
                strategy_focus = """
        ESTRATEGIA: MANTENER Y CRECER
        - Ya cumples requisitos básicos de monetización
        - Enfócate en crecimiento sostenible y optimización
        - Recomienda contenido que mejore métricas existentes
                """
            
            channel_info = f"""
        
        ANÁLISIS DE TU CANAL (PERSONALIZACIÓN PARA MONETIZACIÓN):
        - Nombre del canal: {metrics.get('channel_name', 'N/A')}
        - Suscriptores actuales: {metrics.get('subscribers', 0):,} / 1,000 necesarios ({monetization.get('subscribers_progress', 0):.1f}%)
        - Horas de visualización estimadas: {monetization.get('watch_hours', 0):.1f} / 4,000 necesarias ({monetization.get('watch_hours_progress', 0):.1f}%)
        - Videos publicados: {metrics.get('video_count', 0)}
        - Promedio de vistas por video: {performance.get('avg_views', 0):,.0f}
        - Engagement promedio: {performance.get('avg_engagement', 0):.2f}%
        - Tendencias de crecimiento: {performance.get('growth_trend', 'unknown')}
        - Temas más exitosos en tu canal: {', '.join([t['topic'] for t in performance.get('best_performing_topics', [])[:5]])}
        - Tamaño del canal: {channel_context.get('channel_size', 'unknown')}
        - Estado de monetización: {' CUMPLE REQUISITOS' if monetization.get('can_monetize', False) else ' PENDIENTE'}
        
        {strategy_focus}
        
        CRITERIOS ESPECÍFICOS PARA RECOMENDACIONES:
        1. PRIORIDAD: {priority.upper()} - Enfócate en cerrar esta brecha primero
        2. Alinea con temas exitosos: {', '.join([t['topic'] for t in performance.get('best_performing_topics', [])[:3]])}
        3. Supera promedio actual: Videos que puedan obtener >{performance.get('avg_views', 0):,.0f} vistas
        4. Considera duración: {'Videos largos (15-30 min)' if priority in ['watch_hours', 'both'] else 'Videos optimizados para engagement'}
        5. Potencial de conversión: {'Alto potencial de suscripción' if priority in ['subscribers', 'both'] else 'Retención y horas de visualización'}
        """
        
        lang_instr = "WRITE IN ENGLISH." if language == 'en' else "ESCRIBE EN ESPAÑOL."
        
        # Seleccionar un ángulo creativo aleatorio para variar los resultados
        import random
        creative_angles = [
            "Controversial & Debated Topics",
            "Educational & Deep Dives",
            "Emotional & Storytelling",
            "Future Predictions & Trends",
            "Historical Comparisons",
            "Problem Solving & Tutorials",
            "Top Lists & Rankings",
            "Myths vs Reality",
            "Behind the Scenes / Secrets",
            "Beginner Mistakes vs Pro Tips",
            "Case Studies & Analysis",
            "Unexpected Experiments"
        ]
        selected_angle = random.choice(creative_angles)
        
        prompt = f"""
        Eres un experto en estrategia de contenido para YouTube especializado en {category}.
        
        Tu tarea es generar recomendaciones de videos que maximicen visitas y suscriptores para una AUDIENCIA GLOBAL.
        
        ENFOQUE CREATIVO OBLIGATORIO PARA ESTA SESIÓN: {selected_angle}
        (Todas las ideas deben estar influenciadas por este ángulo para asegurar variedad)
        
        CONTEXTO GENERAL:
        - Temática del canal: {category}
        - Audiencia objetivo: GLOBAL (no limitada a un país específico)
        - Tendencias actuales de Google (globales): {trends_str}
        - Videos populares en YouTube (globales): {youtube_summary}
        - Análisis de competencia: {competition_info}{serp_info}{channel_info}
        
        GENERA 8-10 RECOMENDACIONES DE VIDEOS (no más de 10) con este formato JSON:
        {{
            "recommendations": [
                {{
                    "title": "Título del video sugerido",
                    "description": "Breve descripción del contenido (máx 150 caracteres)",
                    "why_viral": "Razón por la que podría ser viral (máx 100 caracteres)",
                    "potential_views": "Estimación: Alto/Medio/Bajo",
                    "keywords": ["keyword1", "keyword2", "keyword3"],
                    "angle": "Ángulo único o enfoque diferenciador",
                    "trend_score": 8.5,
                    "competition_score": 6.0,
                    "overall_score": 7.5
                }}
            ]
        }}
        
        CRITERIOS GENERALES:
        1. Combina tendencias actuales GLOBALES con la temática {category}
        2. Busca ángulos únicos que diferencien del contenido existente y atraigan audiencia internacional
        3. EVITA REPETIR temas genéricos o ideas obvias. SE CREATIVO y NOVEDOSO.
        4. Prioriza temas con alto potencial de engagement a nivel global
        5. Incluye keywords relevantes para SEO GLOBAL (usa los keywords trending de SERP API si están disponibles)
        6. Considera las preguntas frecuentes (People Also Ask) para generar ideas de contenido que respondan a la audiencia global
        7. Los títulos y temas deben ser atractivos para audiencia internacional, no solo local
        
        CRITERIOS ESPECÍFICOS PARA MONETIZACIÓN:
        - Si el canal necesita suscriptores: Prioriza videos con alto potencial viral y CTAs fuertes
        - Si el canal necesita horas: Prioriza videos largos (15-30 min) con alta retención
        - Si necesita ambos: Balancea entre contenido viral corto y contenido largo de valor
        - Siempre considera los temas que ya funcionan bien en el canal del usuario
        
        IMPORTANTE - AUDIENCIA GLOBAL:
        - Las recomendaciones deben ser atractivas para audiencia de múltiples países
        - Usa temas universales que trasciendan barreras culturales
        - Considera que el contenido será visto por personas de diferentes idiomas y culturas
        - Prioriza temas con interés global sobre temas muy locales
        
        Language: {lang_instr}
        
        CRÍTICO - FORMATO DE RESPUESTA:
        - Responde SOLO con JSON válido, sin markdown code blocks (sin ```json)
        - El JSON debe estar completo y bien formateado
        - Asegúrate de que todas las llaves, corchetes y comillas estén correctamente cerradas
        - Las descripciones deben ser breves (máximo 150 caracteres)
        - Los títulos deben ser concisos
        - Incluye exactamente 8-10 recomendaciones, no más
        """
        
        try:
            # Aumentar max_tokens para poder generar 10-15 recomendaciones completas
            # gemini-2.5-flash soporta hasta 8192 tokens de salida
            response = self.gemini_client._generate(prompt, max_tokens=8192)
            
            # Verificar si la generación fue exitosa
            if not response:
                print("️ Error generando recomendaciones: Claude CLI no devolvió contenido")
                print("    Posibles soluciones:")
                print("      1. Configura GEMINI_API_KEY en .env como respaldo")
                print("      2. Verifica que Claude CLI esté correctamente autenticado")
                print("      3. Intenta con un prompt más corto")
                return []
            
            # Detectar error de cuotas agotadas
            if response == "ERROR_QUOTA_EXCEEDED":
                print("️ Error generando recomendaciones: Cuotas de Claude API agotadas")
                print("    Las cuotas se repondrán automáticamente. Intenta más tarde.")
                return []
            
            # Intentar parsear JSON de la respuesta
            # La IA puede devolver JSON envuelto en markdown o texto
            json_text = response.strip()
            
            # Asegurar que el texto esté en UTF-8
            if isinstance(json_text, bytes):
                json_text = json_text.decode('utf-8', errors='replace')
            elif not isinstance(json_text, str):
                json_text = str(json_text)
            
            # Limpiar markdown code blocks si existe (más robusto)
            json_text = json_text.replace("```json", "").replace("```", "").strip()
            
            # Remover caracteres de control inválidos para JSON (pero mantener UTF-8 válido)
            import re
            # Solo remover caracteres de control, no caracteres UTF-8 válidos
            json_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', json_text)
            
            # Si el JSON está dentro de texto, extraer solo la parte JSON
            if '{' in json_text and '}' in json_text:
                # Buscar el primer { y último }
                start = json_text.find('{')
                end = json_text.rfind('}') + 1
                if start >= 0 and end > start:
                    json_text = json_text[start:end]
            
            json_text = json_text.strip()
            
            # Parsear JSON asegurando codificación UTF-8
            data = json.loads(json_text, strict=False)
            recommendations = data.get('recommendations', [])
            
            # Normalizar strings UTF-8 en las recomendaciones
            for rec in recommendations:
                for key, value in rec.items():
                    if isinstance(value, str):
                        # Asegurar que el string esté correctamente codificado en UTF-8
                        try:
                            # Si el string tiene caracteres mal codificados, intentar corregirlos
                            if 'Ã' in value or 'â' in value or 'Ã©' in value:
                                # Intentar decodificar como si fuera latin-1 y luego codificar en UTF-8
                                try:
                                    value = value.encode('latin-1').decode('utf-8')
                                except:
                                    pass
                            rec[key] = value
                        except:
                            pass
                    elif isinstance(value, list):
                        # Normalizar strings en listas (como keywords)
                        rec[key] = [
                            item.encode('latin-1').decode('utf-8') if isinstance(item, str) and ('Ã' in item or 'â' in item) else item
                            for item in value
                        ]
            
            # Enriquecer con datos de competencia
            for rec in recommendations:
                rec['category'] = category
                rec['competition_data'] = competition
            
            return recommendations
        except json.JSONDecodeError as e:
            print(f"️ Error parseando JSON de IA: {e}")
            print(f"Respuesta recibida: {response[:500]}")
            return []
        except Exception as e:
            print(f"️ Error generando recomendaciones con IA: {e}")
            return []
    
    def _rank_recommendations(self, recommendations: List[Dict], competition: Dict, 
                              channel_context: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """Rankea las recomendaciones por potencial de éxito, personalizado si hay canal"""
        # Calcular score final combinando múltiples factores
        for rec in recommendations:
            trend_score = rec.get('trend_score', 5.0)
            competition_score = rec.get('competition_score', 5.0)
            overall_score = rec.get('overall_score', 5.0)
            
            # Ajustar score basado en competencia real
            competition_multiplier = {
                'low': 1.2,
                'medium': 1.0,
                'high': 0.8
            }.get(competition.get('competition_level', 'medium'), 1.0)
            
            # Score base ponderado
            base_score = (
                overall_score * 0.5 +
                trend_score * 0.3 +
                competition_score * 0.2
            ) * competition_multiplier
            
            # Ajuste personalizado basado en el canal del usuario
            personalization_multiplier = 1.0
            if channel_context:
                performance = channel_context.get('performance_analysis') or {}
                best_topics = [
                    t.get('topic', '')
                    for t in performance.get('best_performing_topics', [])
                    if isinstance(t, dict)
                ]
                rec_title_lower = rec.get('title', '').lower()
                
                # Bonus si el tema coincide con temas exitosos del canal
                for topic in best_topics[:3]:
                    if topic in rec_title_lower:
                        personalization_multiplier += 0.15
                        break
                
                # Bonus si el canal está creciendo
                if performance.get('growth_trend') == 'positive':
                    personalization_multiplier += 0.1
                
                # Ajuste según tamaño del canal
                channel_size = channel_context.get('channel_size', 'medium')
                if channel_size in ['micro', 'small']:
                    # Para canales pequeños, priorizar temas con menos competencia
                    if competition.get('competition_level') == 'low':
                        personalization_multiplier += 0.2
                elif channel_size in ['large', 'mega']:
                    # Para canales grandes, priorizar temas trending
                    personalization_multiplier += 0.1
            
            final_score = base_score * personalization_multiplier
            rec['final_score'] = final_score
            rec['personalized'] = channel_context is not None
        
        # Ordenar por score final
        recommendations.sort(key=lambda x: x.get('final_score', 0), reverse=True)
        
        return recommendations
