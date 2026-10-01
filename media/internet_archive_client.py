# internet_archive_client.py
"""
Cliente para buscar y descargar videos históricos de Internet Archive.
Excelente para documentales históricos, noticieros antiguos, y archivos históricos.
"""

import requests
import os
from pathlib import Path
from typing import List, Dict, Optional
import urllib.parse


class InternetArchiveClient:
    """
    Cliente para interactuar con Internet Archive API.
    
    Internet Archive tiene una enorme colección de videos históricos:
    - Documentales históricos
    - Noticieros antiguos (newsreels)
    - Archivos de guerra
    - Eventos históricos grabados
    
    API Docs: https://archive.org/help/wayback_api.php
    Search API: https://archive.org/advancedsearch.php
    """

    def __init__(self, user_agent="VideoOptimizerPro/1.0"):
        self.base_url = "https://archive.org/advancedsearch.php"
        self.download_base = "https://archive.org/download"
        self.headers = {
            'User-Agent': user_agent
        }

    def _safe_int(self, value) -> int:
        """Convierte tamaños/duraciones a entero de forma segura."""
        try:
            if value is None or value == "":
                return 0
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    def _select_video_file(self, video_files: List[Dict], prefer_preview: bool = False) -> Optional[Dict]:
        """Prioriza archivos reproducibles y de tamaño razonable para la app."""
        if not video_files:
            return None

        target_size = 75 * 1024 * 1024 if prefer_preview else 220 * 1024 * 1024

        def _score(video: Dict):
            filename = str(video.get('filename', '') or '').lower()
            format_type = str(video.get('format', '') or '').lower()
            ext = Path(filename).suffix.lower()
            size = self._safe_int(video.get('size', 0))

            stream_priority = {
                '.mp4': 6,
                '.m4v': 5,
                '.webm': 4,
                '.ogv': 3,
                '.mov': 2,
                '.avi': 1,
                '.mpeg': 1,
                '.mpg': 1,
            }.get(ext, 0)

            keyword_bonus = 0
            if any(token in filename or token in format_type for token in ('h264', 'h.264', 'mpeg4', '512kb', '256kb', '150kb')):
                keyword_bonus += 2
            if 'original' in format_type or 'master' in format_type:
                keyword_bonus -= 3

            if size > 0:
                size_score = -abs(size - target_size)
                if prefer_preview and size > 350 * 1024 * 1024:
                    size_score -= size
                if (not prefer_preview) and size > 1500 * 1024 * 1024:
                    size_score -= size
            else:
                size_score = -10**12

            return (stream_priority, keyword_bonus, size_score, -len(filename))

        return max(video_files, key=_score)

    def search_videos(self, query: str, limit: int = 20, media_type: str = "movies") -> List[Dict]:
        """
        Busca videos históricos en Internet Archive.
        
        Args:
            query: Término de búsqueda (Ej: "World War II", "Apollo 11", "Berlin Wall 1989")
            limit: Número máximo de resultados
            media_type: Tipo de media ("movies", "video", "newsreels")
        
        Returns:
            Lista de diccionarios con información de los videos
        """
        try:
            # Construir query para Internet Archive
            # Filtrar por mediatype y formato de video
            search_query = f"mediatype:{media_type} AND format:Video AND ({query})"
            
            params = {
                'q': search_query,
                'fl': 'identifier,title,description,date,creator,mediatype,downloads,item_size',
                'rows': limit,
                'page': 1,
                'output': 'json',
                'sort': 'downloads desc'  # Ordenar por popularidad
            }
            
            response = requests.get(self.base_url, params=params, headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            videos = []
            
            if 'response' in data and 'docs' in data['response']:
                # Limitar el número de items procesados para evitar demasiadas llamadas HTTP
                items_to_process = min(len(data['response']['docs']), limit)
                
                for idx, item in enumerate(data['response']['docs'][:items_to_process]):
                    identifier = item.get('identifier', '')
                    if not identifier:
                        continue
                    
                    try:
                        # Obtener información detallada del item con timeout corto
                        metadata = self._get_item_metadata(identifier)
                        if not metadata:
                            continue
                        
                        # Buscar archivos de video
                        video_files = self._find_video_files(metadata)
                        if not video_files:
                            continue
                        
                        preview_video = self._select_video_file(video_files, prefer_preview=True) or video_files[0]
                        best_video = self._select_video_file(video_files, prefer_preview=False) or preview_video
                        
                        # Generar URL del thumbnail
                        thumbnail_url = f"https://archive.org/services/img/{identifier}"

                        video_info = {
                            'url': best_video.get('url', ''),
                            'preview_url': preview_video.get('url', ''),
                            'title': item.get('title', identifier),
                            'description': item.get('description', ''),
                            'date': item.get('date', ''),
                            'creator': item.get('creator', ''),
                            'source': 'internet_archive',
                            'query': query,
                            'identifier': identifier,
                            'downloads': item.get('downloads', 0),
                            'duration': best_video.get('duration', 0) or preview_video.get('duration', 0),
                            'format': best_video.get('format', ''),
                            'size': best_video.get('size', 0),
                            'preview_format': preview_video.get('format', ''),
                            'preview_size': preview_video.get('size', 0),
                            'thumbnail': thumbnail_url,
                            'thumbnail_url': thumbnail_url
                        }
                        
                        videos.append(video_info)
                        
                        # Limitar a máximo 10 videos para evitar sobrecarga
                        if len(videos) >= 10:
                            break
                    
                    except Exception as e:
                        # Continuar con el siguiente item si hay error
                        print(f"️ Error procesando item {identifier}: {e}")
                        continue
            
            if videos:
                print(f" Internet Archive: {len(videos)} videos históricos encontrados para '{query}'")
            else:
                print(f"️ Internet Archive: Sin videos para '{query}'")
            
            return videos
            
        except Exception as e:
            print(f" Error buscando videos en Internet Archive: {e}")
            return []

    def _get_item_metadata(self, identifier: str) -> Optional[Dict]:
        """Obtiene metadata detallada de un item"""
        try:
            url = f"https://archive.org/metadata/{identifier}"
            # Timeout más corto para evitar bloqueos
            response = requests.get(url, headers=self.headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            # Validar que tenga la estructura esperada
            if 'files' not in data:
                return None
            return data
        except requests.Timeout:
            # Silenciar timeouts para no saturar la consola
            return None
        except Exception as e:
            # Solo mostrar errores críticos
            if '404' not in str(e) and 'timeout' not in str(e).lower():
                print(f"️ Error obteniendo metadata de {identifier}: {e}")
            return None

    def _find_video_files(self, metadata: Dict) -> List[Dict]:
        """Encuentra archivos de video en la metadata"""
        video_files = []
        
        if 'files' not in metadata:
            return video_files
        
        video_formats = ['.mp4', '.webm', '.ogv', '.avi', '.mov', '.mpeg', '.mpg']
        
        try:
            # Obtener identifier de metadata de forma segura
            identifier = None
            if 'metadata' in metadata and isinstance(metadata['metadata'], dict):
                identifier = metadata['metadata'].get('identifier', '')
            elif 'identifier' in metadata:
                identifier = metadata['identifier']
            
            if not identifier:
                return video_files
            
            # Limitar el número de archivos procesados para evitar sobrecarga
            files_to_check = metadata['files'][:50]  # Solo revisar los primeros 50 archivos
            
            for file_info in files_to_check:
                try:
                    filename = file_info.get('name', '')
                    format_type = file_info.get('format', '')
                    
                    # Verificar si es un archivo de video
                    is_video = (
                        any(filename.lower().endswith(ext) for ext in video_formats) or
                        'Video' in format_type or
                        'video' in format_type.lower()
                    )
                    
                    if is_video:
                        # Construir URL de descarga (usar quote para URLs seguras)
                        safe_filename = urllib.parse.quote(filename, safe='')
                        download_url = f"{self.download_base}/{identifier}/{safe_filename}"
                        
                        video_file = {
                            'url': download_url,
                            'filename': filename,
                            'format': format_type,
                            'size': file_info.get('size', 0),
                            'duration': file_info.get('length', 0)  # En segundos si está disponible
                        }
                        video_files.append(video_file)
                        
                        # Limitar a máximo 3 videos por item para evitar sobrecarga
                        if len(video_files) >= 3:
                            break
                except Exception:
                    # Continuar con el siguiente archivo si hay error
                    continue
        except Exception as e:
            print(f"️ Error procesando archivos de video: {e}")
        
        return video_files

    def download_video(self, video_info: Dict, output_path: str) -> Optional[str]:
        """
        Descarga un video de Internet Archive.
        
        Args:
            video_info: Diccionario con información del video (debe incluir 'url')
            output_path: Ruta donde guardar el video
        
        Returns:
            Ruta del archivo descargado o None si falla
        """
        try:
            video_url = video_info.get('url', '')
            if not video_url:
                print(" No hay URL de video para descargar")
                return None
            
            print(f"   ⬇️ Descargando video histórico de Internet Archive...")
            print(f"    {video_info.get('title', 'Video sin título')}")
            
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
                                print(f"    {percent:.1f}% descargado...", end='\r')
            
            print(f"\n    Video descargado: {Path(output_path).name}")
            return str(output_path)
            
        except Exception as e:
            print(f"    Error descargando video: {e}")
            return None

