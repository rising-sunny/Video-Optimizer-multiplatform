# video_registry.py
"""
Sistema de registro de videos generados.
Permite trackear videos, relacionar shorts con videos largos,
y gestionar la generación de shorts trailers para monetización.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os


class VideoRegistry:
    """Sistema de registro de videos generados"""
    
    def __init__(self, db_path: str = "auto_videos/video_registry.db"):
        """
        Inicializa el registro de videos.
        
        Args:
            db_path: Ruta al archivo de base de datos SQLite
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """Inicializa la base de datos con las tablas necesarias"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Tabla principal de videos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE NOT NULL,
                video_path TEXT NOT NULL,
                video_type TEXT NOT NULL,  -- 'long', 'short', 'teaser'
                title TEXT,
                topic TEXT,
                category TEXT,
                platform TEXT,
                duration REAL,
                resolution TEXT,
                language TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                parent_video_id TEXT,  -- ID del video largo si es un short/teaser
                metadata TEXT,  -- JSON con metadatos adicionales
                youtube_url TEXT,  -- URL si fue subido a YouTube
                views INTEGER DEFAULT 0,
                watch_hours REAL DEFAULT 0.0,
                status TEXT DEFAULT 'generated'  -- 'generated', 'uploaded', 'published'
            )
        """)
        
        # Tabla de relaciones (shorts relacionados con videos largos)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS video_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                long_video_id TEXT NOT NULL,
                short_video_id TEXT NOT NULL,
                relation_type TEXT DEFAULT 'teaser',  -- 'teaser', 'trailer', 'promo'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (long_video_id) REFERENCES videos(video_id),
                FOREIGN KEY (short_video_id) REFERENCES videos(video_id)
            )
        """)
        
        # Índices para búsquedas rápidas
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_video_type ON videos(video_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_parent_video ON videos(parent_video_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at ON videos(created_at)
        """)
        
        conn.commit()
        conn.close()
    
    def register_video(self, video_path: str, video_type: str = 'long', 
                      title: str = None, topic: str = None, category: str = None,
                      platform: str = 'youtube', duration: float = None,
                      resolution: str = None, language: str = 'es',
                      parent_video_id: str = None, metadata: Dict = None,
                      relation_type: str = 'teaser') -> str:
        """
        Registra un video generado en la base de datos.
        
        Args:
            video_path: Ruta al archivo de video
            video_type: Tipo de video ('long', 'short', 'teaser')
            title: Título del video
            topic: Tema del video
            category: Categoría del video
            platform: Plataforma objetivo ('youtube', 'youtube_short', 'tiktok', etc.)
            duration: Duración en segundos
            resolution: Resolución (ej: '1920x1080', '1080x1920')
            language: Idioma del video
            parent_video_id: ID del video largo si es un short/teaser
            metadata: Diccionario con metadatos adicionales
            relation_type: Tipo de relación si es un teaser ('teaser', 'trailer', 'promo')
        
        Returns:
            video_id: ID único del video registrado
        """
        video_path_obj = Path(video_path)
        if not video_path_obj.exists():
            raise FileNotFoundError(f"El video no existe: {video_path}")
        
        # Generar ID único basado en timestamp y nombre del archivo
        video_id = f"{platform}_{int(datetime.now().timestamp())}"
        
        # Obtener información del archivo
        file_size = video_path_obj.stat().st_size
        
        metadata_dict = metadata or {}
        metadata_dict['file_size'] = file_size
        metadata_dict['file_name'] = video_path_obj.name
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO videos (
                    video_id, video_path, video_type, title, topic, category,
                    platform, duration, resolution, language, parent_video_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                video_id, str(video_path), video_type, title, topic, category,
                platform, duration, resolution, language, parent_video_id,
                json.dumps(metadata_dict)
            ))
            
            # Si tiene parent_video_id, crear relación
            if parent_video_id:
                cursor.execute("""
                    INSERT INTO video_relations (long_video_id, short_video_id, relation_type)
                    VALUES (?, ?, ?)
                """, (parent_video_id, video_id, relation_type))
            
            conn.commit()
            return video_id
        except sqlite3.IntegrityError:
            # Si el video_id ya existe, actualizar
            cursor.execute("""
                UPDATE videos SET
                    video_path = ?, video_type = ?, title = ?, topic = ?, category = ?,
                    platform = ?, duration = ?, resolution = ?, language = ?,
                    parent_video_id = ?, metadata = ?
                WHERE video_id = ?
            """, (
                str(video_path), video_type, title, topic, category,
                platform, duration, resolution, language, parent_video_id,
                json.dumps(metadata_dict), video_id
            ))
            conn.commit()
            return video_id
        finally:
            conn.close()
    
    def get_video(self, video_id: str) -> Optional[Dict]:
        """Obtiene información de un video por su ID"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_all_videos(self, video_type: str = None, platform: str = None,
                      category: str = None, limit: int = None) -> List[Dict]:
        """
        Obtiene todos los videos con filtros opcionales.
        
        Args:
            video_type: Filtrar por tipo ('long', 'short', 'teaser')
            platform: Filtrar por plataforma
            category: Filtrar por categoría
            limit: Límite de resultados
        
        Returns:
            Lista de diccionarios con información de videos
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM videos WHERE 1=1"
        params = []
        
        if video_type:
            query += " AND video_type = ?"
            params.append(video_type)
        
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_long_videos_without_teasers(self) -> List[Dict]:
        """Obtiene videos largos que no tienen shorts teasers asociados"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT v.* FROM videos v
            WHERE v.video_type = 'long'
            AND v.platform = 'youtube'
            AND NOT EXISTS (
                SELECT 1 FROM video_relations vr
                WHERE vr.long_video_id = v.video_id
                AND vr.relation_type = 'teaser'
            )
            ORDER BY v.created_at DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_teasers_for_long_video(self, long_video_id: str) -> List[Dict]:
        """Obtiene todos los shorts teasers asociados a un video largo"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT v.* FROM videos v
            INNER JOIN video_relations vr ON v.video_id = vr.short_video_id
            WHERE vr.long_video_id = ?
            ORDER BY v.created_at DESC
        """, (long_video_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    
    def get_total_watch_hours(self) -> float:
        """Obtiene el total de horas de visualización acumuladas"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT SUM(watch_hours) FROM videos")
        result = cursor.fetchone()
        conn.close()
        
        return result[0] or 0.0
    
    def get_statistics(self) -> Dict:
        """Obtiene estadísticas generales del registro"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        stats = {}
        
        # Total de videos
        cursor.execute("SELECT COUNT(*) FROM videos")
        stats['total_videos'] = cursor.fetchone()[0]
        
        # Videos largos
        cursor.execute("SELECT COUNT(*) FROM videos WHERE video_type = 'long'")
        stats['long_videos'] = cursor.fetchone()[0]
        
        # Shorts/Teasers
        cursor.execute("SELECT COUNT(*) FROM videos WHERE video_type IN ('short', 'teaser')")
        stats['shorts'] = cursor.fetchone()[0]
        
        # Videos con teasers
        cursor.execute("""
            SELECT COUNT(DISTINCT long_video_id) FROM video_relations
        """)
        stats['videos_with_teasers'] = cursor.fetchone()[0]
        
        # Total watch hours
        stats['total_watch_hours'] = self.get_total_watch_hours()
        
        # Horas necesarias para monetización (4000 horas según YouTube)
        stats['hours_needed_for_monetization'] = 4000.0
        stats['hours_remaining'] = max(0, stats['hours_needed_for_monetization'] - stats['total_watch_hours'])
        stats['monetization_progress'] = (stats['total_watch_hours'] / stats['hours_needed_for_monetization']) * 100
        
        conn.close()
        
        return stats
    
    def delete_video(self, video_id: str):
        """Elimina un video del registro (no elimina el archivo)"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Eliminar relaciones primero
        cursor.execute("DELETE FROM video_relations WHERE short_video_id = ? OR long_video_id = ?", 
                      (video_id, video_id))
        
        # Eliminar video
        cursor.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
        
        conn.commit()
        conn.close()


