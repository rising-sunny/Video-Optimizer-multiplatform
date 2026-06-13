# resource_downloader.py
"""
Descargador de recursos de stock (Pexels, Pixabay)
Usado como fallback cuando la IA falla
"""

import os
import requests
from pathlib import Path
from typing import List, Dict, Optional

from video_config import VideoConfig


class ResourceDownloader:
    """Descarga imágenes y videos de stock (Usado como Fallback cuando la IA falla)"""
    
    def __init__(self):
        self.pexels_key = VideoConfig.PEXELS_API_KEY
        self.pixabay_key = VideoConfig.PIXABAY_API_KEY
        self.download_dir = VideoConfig.DOWNLOADS_DIR
    
    def search_pexels_videos(self, query: str, count: int = 1) -> List[Dict]:
        """Busca videos en Pexels"""
        if not self.pexels_key or self.pexels_key == "TU_API_KEY_DE_PEXELS":
            print("   ️ Pexels API Key no configurada.")
            return []
        
        try:
            url = "https://api.pexels.com/videos/search"
            headers = {"Authorization": self.pexels_key}
            params = {"query": query, "per_page": count, "orientation": "landscape"}
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                videos = []
                for video in data.get('videos', [])[:count]:
                    video_files = video.get('video_files', [])
                    # Buscar calidad HD
                    hd_file = next((f for f in video_files if f.get('quality') == 'hd'), None)
                    if hd_file:
                        # Incluir información completa del video, incluyendo miniatura
                        video_info = {
                            'url': hd_file['link'],
                            'source': 'pexels',
                            'query': query,
                            'image': video.get('image', ''),  # Miniatura del video
                            'duration': video.get('duration', 0),
                            'id': video.get('id', 0)
                        }
                        videos.append(video_info)
                return videos
            else:
                print(f"   ️ Error Pexels (Video): {response.status_code}")
                return []
        except Exception as e:
            print(f"    Error buscando videos Pexels: {e}")
            return []
    
    def search_pexels_images(self, query: str, count: int = 1) -> List[Dict]:
        """Busca imágenes en Pexels"""
        if not self.pexels_key or self.pexels_key == "TU_API_KEY_DE_PEXELS":
            print("   ️ Pexels API Key no configurada.")
            return []
        
        try:
            url = "https://api.pexels.com/v1/search"
            headers = {"Authorization": self.pexels_key}
            params = {"query": query, "per_page": count, "orientation": "landscape"}
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                images = []
                for photo in data.get('photos', [])[:count]:
                    images.append({'url': photo['src']['large2x'], 'source': 'pexels', 'query': query})
                return images
            else:
                print(f"   ️ Error Pexels (Imagen): {response.status_code}")
                return []
        except Exception as e:
            print(f"    Error buscando imágenes Pexels: {e}")
            return []
    
    def download_video(self, video_info: Dict, target_path: str) -> Optional[str]:
        """Descarga un video a una ruta específica"""
        try:
            print(f"   ⬇️ Descargando video de Pexels...")
            response = requests.get(video_info['url'], stream=True, timeout=30)
            if response.status_code == 200:
                with open(target_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"    Video descargado: {Path(target_path).name}")
                return str(target_path)
        except Exception as e:
            print(f"    Error en descarga Pexels: {e}")
            return None
    
    def download_image(self, image_info: Dict, target_path: str) -> Optional[str]:
        """Descarga una imagen a una ruta específica"""
        try:
            print(f"   ⬇️ Descargando imagen de Pexels...")
            response = requests.get(image_info['url'], timeout=10)
            if response.status_code == 200:
                with open(target_path, 'wb') as f:
                    f.write(response.content)
                print(f"    Imagen descargada: {Path(target_path).name}")
                return str(target_path)
        except Exception as e:
            print(f"    Error en descarga Pexels: {e}")
            return None

