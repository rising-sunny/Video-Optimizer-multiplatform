# youtube_video_client.py
"""
Cliente para buscar y descargar videos de YouTube.
Usa la API de YouTube para buscar y yt-dlp para descargar.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Optional
import json
from urllib.parse import parse_qs, urlparse

# Intentar importar la API de YouTube
try:
        YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False
    print("️ google_search_api.py no encontrado. La búsqueda de YouTube no funcionará.")

# Verificar si yt-dlp está disponible
try:
    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--version"],
        capture_output=True,
        text=True,
        timeout=5
    )
    YT_DLP_AVAILABLE = result.returncode == 0
except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
    YT_DLP_AVAILABLE = False


class YouTubeVideoClient:
    """
    Cliente para buscar y descargar videos de YouTube.
    
    Requiere:
    - GOOGLE_API_KEY: API key de Google Cloud Console (para búsqueda)
    - yt-dlp instalado: pip install yt-dlp (para descarga)
    """
    
    # Token OAuth del canal propio. Su proyecto de Google Cloud SI tiene la
    # YouTube Data API habilitada (es el que se usa para subir), asi que sirve
    # de respaldo cuando la API key pertenece a otro proyecto donde no lo esta.
    OAUTH_TOKEN_FILE = "token.json"

    def __init__(self):
        # YOUTUBE_API_KEY tiene prioridad: permite usar una key del MISMO
        # proyecto que el OAuth, sin depender de para que se creo GOOGLE_API_KEY
        # (que suele ser la de Gemini/CSE, de otro proyecto).
        self.api_key = os.getenv("YOUTUBE_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            print("️ YouTube Video Client: sin API key (YOUTUBE_API_KEY / GOOGLE_API_KEY)")
            print("   Se intentara con las credenciales OAuth del canal (token.json).")


        if not YT_DLP_AVAILABLE:
            print("️ YouTube Video Client: yt-dlp no está instalado")
            print("   Instala con: pip install yt-dlp")
    
    @staticmethod
    def _is_api_not_enabled(error) -> bool:
        """403 accessNotConfigured: la Data API no esta habilitada en ESE proyecto."""
        texto = str(error)
        return "accessNotConfigured" in texto or "has not been used in project" in texto

    def _oauth_youtube(self):
        """Cliente de YouTube con el OAuth del canal, o None si no se puede."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            ruta = self.OAUTH_TOKEN_FILE
            if not os.path.exists(ruta):
                base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                ruta = os.path.join(base, self.OAUTH_TOKEN_FILE)
            if not os.path.exists(ruta):
                return None

            creds = Credentials.from_authorized_user_file(ruta)
            if not creds.valid:
                creds.refresh(Request())
                with open(ruta, "w", encoding="utf-8") as fh:
                    fh.write(creds.to_json())
            return build("youtube", "v3", credentials=creds, cache_discovery=False)
        except Exception as exc:
            print(f"   [WARN] No se pudo usar el OAuth del canal como respaldo: {exc}")
            return None

    @staticmethod
    def is_youtube_url(value: str) -> bool:
        """Detecta si un texto parece una URL de YouTube."""
        if not value:
            return False

        text = str(value).strip()
        if not text.startswith(("http://", "https://")):
            return False

        try:
            parsed = urlparse(text)
        except Exception:
            return False

        host = (parsed.netloc or "").lower()
        return host in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtu.be",
        }

    @staticmethod
    def extract_video_id(video_url: str) -> str:
        """Extrae el ID del video desde una URL de YouTube."""
        if not video_url:
            return ""

        try:
            parsed = urlparse(str(video_url).strip())
        except Exception:
            return ""

        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").strip("/")

        if host in {"youtu.be", "www.youtu.be"}:
            return path.split("/")[0] if path else ""

        if path == "watch":
            return parse_qs(parsed.query).get("v", [""])[0]

        parts = path.split("/")
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
            return parts[1]

        return ""

    def get_video_info_from_url(self, video_url: str) -> Optional[Dict]:
        """Obtiene metadata básica desde una URL directa usando yt-dlp."""
        normalized_url = str(video_url or "").strip()
        if not self.is_youtube_url(normalized_url):
            print("ERROR: URL de YouTube invalida o no soportada")
            return None

        if not YT_DLP_AVAILABLE:
            print("ERROR: yt-dlp no esta instalado. Instala con: pip install yt-dlp")
            return None

        try:
            cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--dump-single-json",
                "--skip-download",
                "--no-playlist",
                "--no-warnings",
                "--extractor-args",
                "youtube:player_client=android,web",
                normalized_url,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )

            if result.returncode != 0:
                error_msg = (result.stderr or result.stdout or "Error desconocido").strip()
                print(f"ERROR resolviendo URL de YouTube: {error_msg[:500]}")
                return None

            output_lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            json_text = ""
            for line in reversed(output_lines):
                if line.startswith("{") and line.endswith("}"):
                    json_text = line
                    break
            if not json_text:
                json_text = (result.stdout or "").strip()
            if not json_text:
                print("ERROR: yt-dlp no devolvio metadata para la URL")
                return None

            info = json.loads(json_text)
            webpage_url = info.get("webpage_url") or info.get("original_url") or normalized_url
            video_id = info.get("id") or self.extract_video_id(webpage_url)
            duration = info.get("duration") or 0

            return {
                "url": webpage_url,
                "video_id": video_id,
                "title": info.get("title") or f"Video de YouTube ({video_id or 'sin_titulo'})",
                "description": info.get("description") or "",
                "channel": info.get("channel") or info.get("uploader") or "",
                "published_at": info.get("upload_date") or "",
                "thumbnail": info.get("thumbnail") or "",
                "duration": int(duration) if duration else 0,
                "view_count": int(info.get("view_count") or 0),
                "like_count": int(info.get("like_count") or 0),
                "source": "youtube",
                "query": normalized_url,
                "license": info.get("license") or "Licencia no verificada (URL directa)",
                "direct_url": True,
            }
        except Exception as e:
            print(f"ERROR obteniendo metadata desde URL de YouTube: {e}")
            return None

    def search_videos(self, query: str, limit: int = 20, order: str = 'relevance',
                      creative_commons_only: bool = True) -> List[Dict]:
        """
        Busca videos en YouTube usando la API de YouTube.

        Args:
            query: Término de búsqueda
            limit: Número máximo de resultados
            order: Orden de resultados ('relevance', 'viewCount', 'rating', 'date')
            creative_commons_only: Si True, solo busca videos con licencia Creative Commons

        Returns:
            Lista de diccionarios con información de los videos
        """
        if not YOUTUBE_API_AVAILABLE:
            print(" YouTube API no disponible")
            return []

        try:
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError

            if self.api_key:
                youtube = build('youtube', 'v3', developerKey=self.api_key)
            else:
                youtube = self._oauth_youtube()
                if youtube is None:
                    print(" Sin API key ni OAuth utilizable para buscar en YouTube")
                    return []

            # Parámetros de búsqueda
            search_params = {
                'part': 'snippet',
                'q': query,
                'type': 'video',
                'order': order,
                'maxResults': min(limit, 50),  # Máximo 50 por request
            }

            # Filtrar por licencia Creative Commons si se solicita
            if creative_commons_only:
                search_params['videoLicense'] = 'creativeCommon'
                print(f" Buscando videos con licencia Creative Commons...")

            try:
                response = youtube.search().list(**search_params).execute()
            except HttpError as exc:
                # La API key puede ser de otro proyecto de Google Cloud (p.ej. la
                # de Gemini/CSE), donde la YouTube Data API no esta habilitada.
                # El OAuth del canal si la tiene: se reintenta con eso antes de
                # devolver una lista vacia, que en la GUI parece "no hay videos".
                if not self._is_api_not_enabled(exc):
                    raise
                print("   [WARN] La API key no tiene habilitada la YouTube Data API "
                      "en su proyecto; reintentando con el OAuth del canal...")
                youtube_oauth = self._oauth_youtube()
                if youtube_oauth is None:
                    print("   Habilitala en: https://console.cloud.google.com/apis/library/"
                          "youtube.googleapis.com  (o defini YOUTUBE_API_KEY de otro proyecto)")
                    raise
                youtube = youtube_oauth
                response = youtube.search().list(**search_params).execute()
                print("   [OK] Busqueda resuelta con las credenciales OAuth del canal.")


            videos = []
            for item in response.get('items', []):
                video_id = item['id']['videoId']
                snippet = item['snippet']
                
                # Obtener información adicional del video (duración, estadísticas)
                try:
                    video_details = youtube.videos().list(
                        part='contentDetails,statistics',
                        id=video_id
                    ).execute()
                    
                    content_details = video_details.get('items', [{}])[0].get('contentDetails', {})
                    statistics = video_details.get('items', [{}])[0].get('statistics', {})
                    status = video_details.get('items', [{}])[0].get('status', {})

                    # Convertir duración ISO 8601 a segundos
                    duration_str = content_details.get('duration', 'PT0S')
                    duration_seconds = self._parse_duration(duration_str)

                    # Obtener licencia del video
                    license_type = content_details.get('licensedContent', False)
                    license_name = 'Creative Commons' if creative_commons_only else 'YouTube estándar'

                    video_info = {
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'video_id': video_id,
                        'title': snippet.get('title', ''),
                        'description': snippet.get('description', ''),
                        'channel': snippet.get('channelTitle', ''),
                        'published_at': snippet.get('publishedAt', ''),
                        'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                        'duration': duration_seconds,
                        'view_count': int(statistics.get('viewCount', 0)),
                        'like_count': int(statistics.get('likeCount', 0)),
                        'source': 'youtube',
                        'query': query,
                        'license': license_name
                    }

                    videos.append(video_info)
                except Exception as e:
                    print(f"️ Error obteniendo detalles del video {video_id}: {e}")
                    # Continuar con información básica
                    video_info = {
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'video_id': video_id,
                        'title': snippet.get('title', ''),
                        'description': snippet.get('description', ''),
                        'channel': snippet.get('channelTitle', ''),
                        'published_at': snippet.get('publishedAt', ''),
                        'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                        'duration': 0,
                        'view_count': 0,
                        'like_count': 0,
                        'source': 'youtube',
                        'query': query,
                        'license': 'Creative Commons' if creative_commons_only else 'YouTube estándar'
                    }
                    videos.append(video_info)

            if videos:
                license_msg = " (Creative Commons)" if creative_commons_only else ""
                print(f" YouTube: {len(videos)} videos{license_msg} encontrados para '{query}'")
            else:
                cc_msg = " con licencia Creative Commons" if creative_commons_only else ""
                print(f"️ YouTube: Sin videos{cc_msg} para '{query}'")
            
            return videos
            
        except HttpError as e:
            print(f" Error en API de YouTube: {e}")
            return []
        except Exception as e:
            print(f" Error buscando videos en YouTube: {e}")
            return []
    
    def _parse_duration(self, duration_str: str) -> int:
        """Convierte duración ISO 8601 (PT1H2M10S) a segundos"""
        import re
        pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
        match = re.match(pattern, duration_str)
        if not match:
            return 0
        
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        
        return hours * 3600 + minutes * 60 + seconds
    
    def download_video(self, video_info: Dict, output_path: str) -> Optional[str]:
        """
        Descarga un video de YouTube usando el método mejorado.
        
        Args:
            video_info: Diccionario con información del video (debe incluir 'url')
            output_path: Ruta donde guardar el video
        
        Returns:
            Ruta del archivo descargado o None si falla
        """
        if not YT_DLP_AVAILABLE:
            print(" yt-dlp no está instalado. Instala con: pip install yt-dlp")
            return None
        
        # Importar y usar el descargador mejorado
        try:
            from media.youtube_downloader_fixed import FixedYouTubeDownloader
            downloader = FixedYouTubeDownloader()
            return downloader.download_video(video_info, output_path)
        except ImportError:
            print(" No se pudo importar el descargador mejorado, usando método estándar...")
            return self._download_video_legacy(video_info, output_path)
    
    def _download_video_legacy(self, video_info: Dict, output_path: str) -> Optional[str]:
        """Método legacy de descarga como fallback"""
        video_url = video_info.get('url', '')
        if not video_url:
            print(" No hay URL de video para descargar")
            return None
        
        try:
            print(f"   ⬇️ Descargando video de YouTube (método legacy)...")
            print(f"    {video_info.get('title', 'Video sin título')}")
            
            # Crear directorio si no existe
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Usar yt-dlp con opciones básicas
            cmd = [
                sys.executable, "-m", "yt_dlp",
                "-f", "best[ext=mp4]/best",
                "-o", str(output_path),
                "--no-playlist",
                "--ignore-errors",
                video_url
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # Verificar resultado
            file_exists = os.path.exists(output_path)
            file_size = os.path.getsize(output_path) if file_exists else 0
            
            if result.returncode == 0 and file_exists and file_size > 0:
                print(f"    Video descargado (legacy): {Path(output_path).name} ({file_size:,} bytes)")
                return output_path
            else:
                error_msg = result.stderr or result.stdout or "Error desconocido"
                print(f"    Error descargando video: {error_msg[:300]}")
                return None
                
        except Exception as e:
            print(f"    Error descargando video: {e}")
            return None


