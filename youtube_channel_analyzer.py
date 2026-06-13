# youtube_channel_analyzer.py
"""
Analizador de canal de YouTube para obtener métricas y historial.
Permite personalizar recomendaciones basadas en el rendimiento del canal.
"""

import os
from typing import Dict, List, Optional, Any
from env_loader import load_project_env
from datetime import datetime, timedelta
import json

load_project_env()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


class YouTubeChannelAnalyzer:
    """
    Analiza un canal de YouTube para obtener:
    - Métricas del canal (suscriptores, vistas totales, etc.)
    - Historial de videos (títulos, vistas, engagement)
    - Tendencias de rendimiento
    - Temas más exitosos
    """
    
    def __init__(self, channel_id: Optional[str] = None, channel_handle: Optional[str] = None):
        """
        Inicializa el analizador de canal.
        
        Args:
            channel_id: ID del canal de YouTube (ej: UCxxxxx)
            channel_handle: Handle del canal (ej: @StunningRevelations) - sin @
        """
        self.api_key = GOOGLE_API_KEY
        self.channel_id = channel_id
        self.channel_handle = channel_handle
        self.youtube_service = None
        self._youtube_api_disabled = False
        self._youtube_api_warning_logged = False
        self._youtube_api_disable_reason = ""
        
        if True:
            try:
                from googleapiclient.discovery import build
                try:
                    from youtube_uploader import _get_credentials
                    creds = _get_credentials(interactive=False)
                    if creds:
                        self.youtube_service = build('youtube', 'v3', credentials=creds)
                except Exception as oe:
                    pass
                if not self.youtube_service and self.api_key:
                    self.youtube_service = build('youtube', 'v3', developerKey=self.api_key)
            except Exception as e:
                print(f"️ Error inicializando YouTube API: {e}")

    def _is_access_not_configured_error(self, error: Exception) -> bool:
        """Detecta si la API de YouTube está deshabilitada en el proyecto de Google."""
        error_text = str(error).lower()
        return (
            'accessnotconfigured' in error_text
            or 'has not been used in project' in error_text
            or 'youtube data api v3 has not been used' in error_text
        )

    def _disable_youtube_api_for_session(self, error: Exception) -> None:
        """Desactiva YouTube API para esta sesión y evita spam de errores repetidos."""
        self._youtube_api_disabled = True
        self.youtube_service = None
        self._youtube_api_disable_reason = str(error)
        if not self._youtube_api_warning_logged:
            print(
                "️ YouTube Data API deshabilitada/no habilitada en GCP. "
                "Se omite análisis de canal hasta que la habilites."
            )
            self._youtube_api_warning_logged = True
    
    def resolve_channel_id(self) -> Optional[str]:
        """Resuelve el channel_id desde el handle si es necesario"""
        if self._youtube_api_disabled or not self.youtube_service:
            return None
        
        if self.channel_id:
            return self.channel_id
        
        if not self.channel_handle:
            return None
        
        try:
            # Buscar canal por handle
            request = self.youtube_service.search().list(
                part='snippet',
                q=self.channel_handle,
                type='channel',
                maxResults=1
            )
            response = request.execute()
            
            if response.get('items'):
                self.channel_id = response['items'][0]['snippet']['channelId']
                return self.channel_id
        except Exception as e:
            if self._is_access_not_configured_error(e):
                self._disable_youtube_api_for_session(e)
            else:
                print(f"️ Error resolviendo channel ID: {e}")
        
        return None
    
    def get_channel_metrics(self) -> Optional[Dict[str, Any]]:
        """
        Obtiene métricas principales del canal.
        
        Returns:
            Dict con: subscribers, total_views, video_count, created_date, etc.
        """
        if self._youtube_api_disabled or not self.youtube_service:
            return None
        
        channel_id = self.resolve_channel_id()
        if not channel_id:
            return None
        
        try:
            # Obtener estadísticas del canal
            request = self.youtube_service.channels().list(
                part='statistics,snippet,contentDetails',
                id=channel_id
            )
            response = request.execute()
            
            if not response.get('items'):
                return None
            
            channel = response['items'][0]
            stats = channel.get('statistics', {})
            snippet = channel.get('snippet', {})
            
            return {
                'channel_id': channel_id,
                'channel_name': snippet.get('title', 'Unknown'),
                'subscribers': int(stats.get('subscriberCount', 0)),
                'total_views': int(stats.get('viewCount', 0)),
                'video_count': int(stats.get('videoCount', 0)),
                'created_date': snippet.get('publishedAt', ''),
                'description': snippet.get('description', ''),
                'country': snippet.get('country', ''),
                'custom_url': snippet.get('customUrl', '')
            }
        except Exception as e:
            if self._is_access_not_configured_error(e):
                self._disable_youtube_api_for_session(e)
            else:
                print(f"️ Error obteniendo métricas del canal: {e}")
            return None
    
    def get_channel_videos(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Obtiene el historial de videos del canal.
        
        Args:
            max_results: Número máximo de videos a obtener
        
        Returns:
            Lista de videos con sus métricas
        """
        if self._youtube_api_disabled or not self.youtube_service:
            return []
        
        channel_id = self.resolve_channel_id()
        if not channel_id:
            return []
        
        try:
            # Obtener uploads playlist ID
            request = self.youtube_service.channels().list(
                part='contentDetails',
                id=channel_id
            )
            response = request.execute()
            
            if not response.get('items'):
                return []
            
            uploads_playlist_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            
            # Obtener videos de la playlist de uploads
            videos = []
            next_page_token = None
            
            while len(videos) < max_results:
                request = self.youtube_service.playlistItems().list(
                    part='snippet,contentDetails',
                    playlistId=uploads_playlist_id,
                    maxResults=min(50, max_results - len(videos)),
                    pageToken=next_page_token
                )
                response = request.execute()
                
                video_ids = [item['contentDetails']['videoId'] for item in response.get('items', [])]
                
                if not video_ids:
                    break
                
                # Obtener estadísticas de los videos
                stats_request = self.youtube_service.videos().list(
                    part='statistics,snippet,contentDetails',
                    id=','.join(video_ids)
                )
                stats_response = stats_request.execute()
                
                # Crear diccionario de estadísticas
                stats_dict = {item['id']: item for item in stats_response.get('items', [])}
                
                for item in response.get('items', []):
                    video_id = item['contentDetails']['videoId']
                    stats = stats_dict.get(video_id)
                    
                    if not stats:
                        continue
                    
                    snippet = stats.get('snippet', {})
                    statistics = stats.get('statistics', {})
                    content_details = stats.get('contentDetails', {})
                    
                    view_count = int(statistics.get('viewCount', 0))
                    like_count = int(statistics.get('likeCount', 0))
                    comment_count = int(statistics.get('commentCount', 0))
                    
                    # Calcular engagement rate
                    engagement_rate = 0
                    if view_count > 0:
                        engagement_rate = ((like_count + comment_count) / view_count) * 100
                    
                    videos.append({
                        'video_id': video_id,
                        'title': snippet.get('title', ''),
                        'description': snippet.get('description', ''),
                        'published_at': snippet.get('publishedAt', ''),
                        'views': view_count,
                        'likes': like_count,
                        'comments': comment_count,
                        'engagement_rate': engagement_rate,
                        'duration': content_details.get('duration', ''),
                        'tags': snippet.get('tags', []),
                        'category_id': snippet.get('categoryId', ''),
                        'url': f"https://www.youtube.com/watch?v={video_id}"
                    })
                
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break
            
            return videos
        except Exception as e:
            if self._is_access_not_configured_error(e):
                self._disable_youtube_api_for_session(e)
            else:
                print(f"️ Error obteniendo videos del canal: {e}")
            return []
    
    def analyze_channel_performance(self) -> Dict[str, Any]:
        """
        Analiza el rendimiento del canal y extrae insights.
        
        Returns:
            Dict con análisis: best_performing_topics, avg_views, trends, etc.
        """
        videos = self.get_channel_videos(max_results=50)
        
        if not videos:
            return {
                'total_videos_analyzed': 0,
                'avg_views': 0,
                'avg_engagement': 0,
                'best_performing_topics': [],
                'trending_topics': [],
                'recommendations': []
            }
        
        # Calcular promedios
        total_views = sum(v.get('views', 0) for v in videos)
        total_engagement = sum(v.get('engagement_rate', 0) for v in videos)
        avg_views = total_views / len(videos) if videos else 0
        avg_engagement = total_engagement / len(videos) if videos else 0
        
        # Analizar temas más exitosos (usando títulos y tags)
        topic_performance = {}
        for video in videos:
            title = video.get('title', '').lower()
            tags = [tag.lower() for tag in video.get('tags', [])]
            views = video.get('views', 0)
            engagement = video.get('engagement_rate', 0)
            
            # Extraer palabras clave del título
            keywords = title.split()
            for keyword in keywords:
                if len(keyword) > 4:  # Solo palabras significativas
                    if keyword not in topic_performance:
                        topic_performance[keyword] = {'total_views': 0, 'count': 0, 'avg_engagement': 0}
                    topic_performance[keyword]['total_views'] += views
                    topic_performance[keyword]['count'] += 1
                    topic_performance[keyword]['avg_engagement'] += engagement
        
        # Calcular promedios por tema
        for topic, data in topic_performance.items():
            if data['count'] > 0:
                data['avg_views'] = data['total_views'] / data['count']
                data['avg_engagement'] = data['avg_engagement'] / data['count']
        
        # Ordenar por rendimiento
        best_topics = sorted(
            topic_performance.items(),
            key=lambda x: x[1]['avg_views'] * x[1]['avg_engagement'],
            reverse=True
        )[:10]
        
        # Videos más exitosos
        top_videos = sorted(videos, key=lambda x: x.get('views', 0), reverse=True)[:5]
        
        # Tendencias (videos recientes vs antiguos)
        recent_videos = [v for v in videos if self._is_recent(v.get('published_at', ''))]
        recent_avg_views = sum(v.get('views', 0) for v in recent_videos) / len(recent_videos) if recent_videos else 0
        
        return {
            'total_videos_analyzed': len(videos),
            'avg_views': avg_views,
            'avg_engagement': avg_engagement,
            'recent_avg_views': recent_avg_views,
            'best_performing_topics': [
                {'topic': topic, 'avg_views': data['avg_views'], 'avg_engagement': data['avg_engagement']}
                for topic, data in best_topics
            ],
            'top_videos': [
                {'title': v['title'], 'views': v['views'], 'engagement': v['engagement_rate']}
                for v in top_videos
            ],
            'growth_trend': 'positive' if recent_avg_views > avg_views * 0.8 else 'stable' if recent_avg_views > avg_views * 0.5 else 'declining'
        }
    
    def _is_recent(self, published_at: str, days: int = 30) -> bool:
        """Verifica si un video fue publicado recientemente"""
        try:
            pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            cutoff = datetime.now(pub_date.tzinfo) - timedelta(days=days)
            return pub_date > cutoff
        except:
            return False
    
    def get_monetization_gap_analysis(self) -> Dict[str, Any]:
        """
        Analiza qué le falta al canal para alcanzar la monetización.
        
        Returns:
            Dict con análisis de brechas para monetización
        """
        metrics = self.get_channel_metrics()
        performance = self.analyze_channel_performance()
        
        if not metrics:
            return {
                'subscribers': 0,
                'subscribers_needed': 1000,
                'subscribers_gap': 1000,
                'subscribers_progress': 0.0,
                'watch_hours': 0.0,
                'watch_hours_needed': 4000.0,
                'watch_hours_gap': 4000.0,
                'watch_hours_progress': 0.0,
                'can_monetize': False,
                'priority': 'both'  # Necesita ambos
            }
        
        subscribers = metrics.get('subscribers', 0)
        subscribers_needed = 1000
        subscribers_gap = max(0, subscribers_needed - subscribers)
        subscribers_progress = (subscribers / subscribers_needed) * 100 if subscribers_needed > 0 else 0
        
        # Calcular horas de visualización estimadas
        # Usar promedio de vistas * duración promedio de videos
        avg_views = performance.get('avg_views', 0)
        # Estimación: asumir duración promedio de 10 minutos (0.167 horas) por video
        # Esto es una estimación, el valor real debería venir de YouTube Analytics
        estimated_watch_hours = (avg_views * metrics.get('video_count', 0) * 0.167) / 1000  # Convertir a miles
        watch_hours_needed = 4000.0
        watch_hours_gap = max(0, watch_hours_needed - estimated_watch_hours)
        watch_hours_progress = (estimated_watch_hours / watch_hours_needed) * 100 if watch_hours_needed > 0 else 0
        
        can_monetize = subscribers >= subscribers_needed and estimated_watch_hours >= watch_hours_needed
        
        # Determinar prioridad
        if subscribers < subscribers_needed and estimated_watch_hours < watch_hours_needed:
            priority = 'both'
        elif subscribers < subscribers_needed:
            priority = 'subscribers'
        elif estimated_watch_hours < watch_hours_needed:
            priority = 'watch_hours'
        else:
            priority = 'maintain'
        
        return {
            'subscribers': subscribers,
            'subscribers_needed': subscribers_needed,
            'subscribers_gap': subscribers_gap,
            'subscribers_progress': subscribers_progress,
            'watch_hours': estimated_watch_hours,
            'watch_hours_needed': watch_hours_needed,
            'watch_hours_gap': watch_hours_gap,
            'watch_hours_progress': watch_hours_progress,
            'can_monetize': can_monetize,
            'priority': priority,
            'avg_views': avg_views,
            'video_count': metrics.get('video_count', 0)
        }
    
    def get_personalized_recommendations_context(self) -> Dict[str, Any]:
        """
        Obtiene contexto personalizado del canal para usar en recomendaciones.
        Incluye análisis de monetización.
        
        Returns:
            Dict con contexto: metrics, performance, best_topics, monetization_gap, etc.
        """
        metrics = self.get_channel_metrics() or {}
        performance = self.analyze_channel_performance() or {}
        monetization_gap = self.get_monetization_gap_analysis() or {}

        return {
            'channel_metrics': metrics,
            'performance_analysis': performance,
            'monetization_gap': monetization_gap,
            'channel_size': self._categorize_channel_size(metrics.get('subscribers', 0)),
            'content_focus': self._extract_content_focus(performance.get('best_performing_topics', []))
        }
    
    def _categorize_channel_size(self, subscribers: int) -> str:
        """Categoriza el tamaño del canal"""
        if subscribers < 1000:
            return 'micro'
        elif subscribers < 10000:
            return 'small'
        elif subscribers < 100000:
            return 'medium'
        elif subscribers < 1000000:
            return 'large'
        else:
            return 'mega'
    
    def _extract_content_focus(self, best_topics: List[Dict]) -> List[str]:
        """Extrae los temas principales del canal"""
        return [topic['topic'] for topic in best_topics[:5]]
