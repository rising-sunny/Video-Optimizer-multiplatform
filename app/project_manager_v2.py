# project_manager_v2.py
"""
Sistema de gestión de proyectos v2.0 - Aislamiento completo de proyectos
Cada proyecto tiene su propia carpeta aislada con todos sus archivos multimedia.
"""

import builtins
import json
import os
import shutil
import glob
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any, List


def _safe_print(*args, sep=' ', end='\n', file=None, flush=False):
    """Evita que logs Unicode interrumpan el guardado en consolas cp1252."""
    target = file if file is not None else sys.stdout
    text = sep.join(str(arg) for arg in args) + end

    try:
        target.write(text)
    except UnicodeEncodeError:
        encoding = getattr(target, 'encoding', None) or 'utf-8'
        sanitized = text.encode(encoding, errors='replace').decode(encoding, errors='replace')
        target.write(sanitized)
    except Exception:
        fallback = sys.__stdout__ or sys.stdout
        builtins.print(text, sep='', end='', file=fallback, flush=flush)
        return

    if flush:
        try:
            target.flush()
        except Exception:
            pass


print = _safe_print


class ProjectManagerV2:
    """Gestiona el guardado y carga de proyectos con aislamiento completo"""
    
    ROOT_DIR = Path(__file__).resolve().parent.parent
    PROJECTS_DIR = ROOT_DIR / "projects"
    _dir_ensured = False
    
    @classmethod
    def _ensure_projects_dir(cls):
        """Asegura que el directorio de proyectos existe"""
        if cls._dir_ensured:
            return
        
        try:
            os.makedirs(str(cls.PROJECTS_DIR), exist_ok=True)
            cls._dir_ensured = True
        except Exception as e:
            print(f"️ Error creando directorio projects: {e}")
            cls._dir_ensured = False
    
    @classmethod
    def create_project_folder(cls, project_name: str) -> Path:
        """
        Crea una carpeta única para el proyecto con subcarpetas para diferentes tipos de archivos.
        
        Args:
            project_name: Nombre base del proyecto
            
        Returns:
            Path: Ruta a la carpeta del proyecto
        """
        cls._ensure_projects_dir()
        
        # Limpiar nombre de archivo
        import re
        clean_name = re.sub(r'[<>:"/\\|?*]', '_', project_name)
        
        # Crear carpeta principal del proyecto
        project_folder = cls.PROJECTS_DIR / clean_name
        counter = 1
        original_name = clean_name
        
        # Si ya existe, agregar número
        while project_folder.exists():
            clean_name = f"{original_name}_{counter}"
            project_folder = cls.PROJECTS_DIR / clean_name
            counter += 1
        
        # Crear subcarpetas para organizar archivos
        subfolders = [
            "images",           # Imágenes generadas/manual
            "videos",           # Videos generados
            "audio",            # Archivos de audio
            "thumbnails",       # Thumbnails del proyecto
            "storyboard",       # Datos del storyboard
            "temp",             # Archivos temporales del proyecto
            "exports"           # Videos finales exportados
        ]
        
        try:
            project_folder.mkdir(exist_ok=True)
            for subfolder in subfolders:
                (project_folder / subfolder).mkdir(exist_ok=True)
            
            print(f" Carpeta de proyecto creada: {project_folder}")
            return project_folder
            
        except Exception as e:
            print(f" Error creando carpeta de proyecto: {e}")
            return None
    
    @classmethod
    def copy_media_to_project(cls, project_folder: Path, media_path: str, media_type: str = "images") -> Optional[str]:
        """
        Copia un archivo multimedia a la carpeta correspondiente del proyecto.
        
        Args:
            project_folder: Carpeta del proyecto
            media_path: Ruta original del archivo
            media_type: Tipo de medio (images, videos, audio, thumbnails)
            
        Returns:
            str: Nueva ruta relativa al proyecto, o None si hay error
        """
        if not project_folder or not media_path or not os.path.exists(media_path):
            return None
        
        try:
            source_path = Path(media_path)
            target_folder = project_folder / media_type

            try:
                relative_existing_path = source_path.resolve().relative_to(project_folder.resolve())
                print(f"Archivo ya pertenece al proyecto: {relative_existing_path}")
                return str(relative_existing_path)
            except ValueError:
                pass
            
            # Asegurar que la carpeta destino existe
            target_folder.mkdir(exist_ok=True)
            
            # Generar nombre único para evitar conflictos
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_name = source_path.name
            target_name = f"{timestamp}_{original_name}"
            target_path = target_folder / target_name
            
            # Copiar archivo
            shutil.copy2(source_path, target_path)
            
            # Devolver ruta relativa desde la carpeta del proyecto
            relative_path = Path(media_type) / target_name
            print(f" Archivo copiado: {media_path} -> {relative_path}")
            
            return str(relative_path)
            
        except Exception as e:
            print(f" Error copiando archivo {media_path}: {e}")
            return None
    
    @classmethod
    def update_storyboard_paths(cls, storyboard_data: Dict, project_folder: Path) -> Dict:
        """
        Actualiza las rutas del storyboard para que apunten a los archivos copiados al proyecto.
        PRESERVA todos los campos de los segmentos, incluyendo image_source y video_source.
        
        Args:
            storyboard_data: Datos originales del storyboard
            project_folder: Carpeta del proyecto
            
        Returns:
            Dict: Storyboard con rutas actualizadas
        """
        if not storyboard_data or not project_folder:
            return storyboard_data
        
        updated_storyboard = storyboard_data.copy()
        segments = updated_storyboard.get('segments', [])
        
        for i, segment in enumerate(segments):
            # IMPORTANTE: Preservar todos los campos del segmento (incluyendo image_source y video_source)
            # Solo actualizar image_path y video_path, no sobrescribir el segmento completo
            
            # Copiar imagen del segmento si existe
            if segment.get('image_path') and os.path.exists(segment['image_path']):
                new_path = cls.copy_media_to_project(project_folder, segment['image_path'], "images")
                if new_path:
                    segments[i]['image_path'] = new_path
                    # Preservar image_source si existe (no se pierde al copiar)
                    if 'image_source' not in segments[i] and 'image_source' in segment:
                        segments[i]['image_source'] = segment['image_source']
            
            # Copiar video del segmento si existe
            if segment.get('video_path') and os.path.exists(segment['video_path']):
                new_path = cls.copy_media_to_project(project_folder, segment['video_path'], "videos")
                if new_path:
                    segments[i]['video_path'] = new_path
                    # Preservar video_source si existe (no se pierde al copiar)
                    if 'video_source' not in segments[i] and 'video_source' in segment:
                        segments[i]['video_source'] = segment['video_source']
                    # Si video_path e image_path son el mismo archivo, también actualizar image_path
                    if segments[i].get('image_path') == segment.get('video_path'):
                        segments[i]['image_path'] = new_path
                        # Preservar image_source desde video_source si no hay image_source
                        if 'image_source' not in segments[i] and 'video_source' in segment:
                            segments[i]['image_source'] = segment['video_source']
        
        # Copiar audio principal si existe
        if updated_storyboard.get('audio_path') and os.path.exists(updated_storyboard['audio_path']):
            new_path = cls.copy_media_to_project(project_folder, updated_storyboard['audio_path'], "audio")
            if new_path:
                updated_storyboard['audio_path'] = new_path
        
        updated_storyboard['segments'] = segments
        return updated_storyboard
    
    @classmethod
    def save_project(cls, project_data: Dict[str, Any], project_name: Optional[str] = None) -> Optional[str]:
        """
        Guarda un proyecto con aislamiento completo de archivos.
        
        Args:
            project_data: Diccionario con todos los datos del proyecto
            project_name: Nombre del proyecto (si None, se genera automáticamente)
        
        Returns:
            str: Ruta al archivo JSON del proyecto, o None si hay error
        """
        try:
            cls._ensure_projects_dir()
            
            # Generar nombre de proyecto si no se proporciona
            if not project_name:
                topic = project_data.get('config', {}).get('topic', 'Video')
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                project_name = f"{topic}_{timestamp}".replace(' ', '_')[:50]
            
            # Limpiar caracteres inválidos
            import re
            project_name = re.sub(r'[<>:"/\\|?*]', '_', project_name)
            
            # Crear carpeta del proyecto
            project_folder = cls.create_project_folder(project_name)
            if not project_folder:
                return None
            
            # Procesar y copiar archivos multimedia
            updated_project_data = cls._process_project_media(project_data, project_folder)
            
            # Guardar archivo JSON del proyecto
            json_path = project_folder / "project.json"
            
            # Agregar metadatos del proyecto
            updated_project_data['project_metadata'] = {
                'version': '2.0',
                'created': datetime.now().isoformat(),
                'project_folder': str(project_folder),
                'isolation_mode': True
            }
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(updated_project_data, f, indent=2, ensure_ascii=False)
            
            print(f" Proyecto guardado con aislamiento: {json_path}")
            return str(json_path)
            
        except Exception as e:
            print(f" Error guardando proyecto: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @classmethod
    def _process_project_media(cls, project_data: Dict, project_folder: Path) -> Dict:
        """
        Procesa y copia todos los archivos multimedia del proyecto.
        
        Args:
            project_data: Datos originales del proyecto
            project_folder: Carpeta del proyecto
            
        Returns:
            Dict: Datos del proyecto con rutas actualizadas
        """
        updated_data = project_data.copy()

        def resolve_media_path(path_str: Optional[str]) -> Optional[str]:
            if not path_str:
                return None

            candidate_path = Path(path_str)
            if candidate_path.is_absolute() and candidate_path.exists():
                return str(candidate_path)

            project_candidate = project_folder / candidate_path
            if project_candidate.exists():
                return str(project_candidate.resolve())

            if candidate_path.exists():
                return str(candidate_path.resolve())

            return None

        def persist_thumbnail_path(path_value: Optional[str]) -> Optional[str]:
            resolved_path = resolve_media_path(path_value)
            if not resolved_path:
                return path_value
            new_path = cls.copy_media_to_project(project_folder, resolved_path, "thumbnails")
            return new_path or path_value
        
        # Procesar storyboard
        if updated_data.get('storyboard'):
            updated_data['storyboard'] = cls.update_storyboard_paths(
                updated_data['storyboard'], project_folder
            )
        
        # Procesar thumbnail si existe
        if updated_data.get('thumbnail_path'):
            updated_data['thumbnail_path'] = persist_thumbnail_path(updated_data.get('thumbnail_path'))

        # Procesar datos avanzados de thumbnails si existen
        thumbnail_data = updated_data.get('thumbnail_data')
        if isinstance(thumbnail_data, dict):
            thumbnail_variants = []
            for variant in thumbnail_data.get('thumbnail_variants', []) or []:
                if not isinstance(variant, dict):
                    continue

                updated_variant = variant.copy()
                for path_key in ('path', 'raw_path'):
                    if updated_variant.get(path_key):
                        updated_variant[path_key] = persist_thumbnail_path(updated_variant.get(path_key))
                thumbnail_variants.append(updated_variant)

            thumbnail_data['thumbnail_variants'] = thumbnail_variants

            if thumbnail_data.get('thumbnail_path'):
                thumbnail_data['thumbnail_path'] = persist_thumbnail_path(thumbnail_data.get('thumbnail_path'))
                if thumbnail_data.get('thumbnail_path'):
                    updated_data['thumbnail_path'] = thumbnail_data.get('thumbnail_path')
        
        # Procesar música si existe
        config = updated_data.get('config')
        music_source_path = resolve_media_path(updated_data.get('music_path'))
        if not music_source_path and isinstance(config, dict):
            music_source_path = resolve_media_path(config.get('selected_music_path'))

        if music_source_path:
            new_path = cls.copy_media_to_project(project_folder, music_source_path, "audio")
            if new_path:
                updated_data['music_path'] = new_path
                if isinstance(config, dict):
                    config['selected_music_path'] = new_path
        
        # Procesar video generado si existe
        if updated_data.get('generated_video_data'):
            video_data = updated_data['generated_video_data']
            if video_data.get('video_path') and os.path.exists(video_data['video_path']):
                new_path = cls.copy_media_to_project(project_folder, video_data['video_path'], "videos")
                if new_path:
                    video_data['video_path'] = new_path
            
            if video_data.get('teaser_video_path') and os.path.exists(video_data['teaser_video_path']):
                new_path = cls.copy_media_to_project(project_folder, video_data['teaser_video_path'], "videos")
                if new_path:
                    video_data['teaser_video_path'] = new_path
            
            if video_data.get('audio_path') and os.path.exists(video_data['audio_path']):
                new_path = cls.copy_media_to_project(project_folder, video_data['audio_path'], "audio")
                if new_path:
                    video_data['audio_path'] = new_path
        
        return updated_data
    
    @classmethod
    def load_project(cls, project_path: str) -> Optional[Dict[str, Any]]:
        """
        Carga un proyecto desde su carpeta aislada.
        
        Args:
            project_path: Ruta al archivo JSON del proyecto
        
        Returns:
            dict: Datos del proyecto con rutas absolutas, o None si hay error
        """
        try:
            if not os.path.exists(project_path):
                print(f" El archivo del proyecto no existe: {project_path}")
                return None
            
            project_path = Path(project_path)
            project_folder = project_path.parent
            
            with open(project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            # Convertir rutas relativas a absolutas
            updated_data = cls._convert_to_absolute_paths(project_data, project_folder)
            
            print(f" Proyecto cargado: {project_path}")
            return updated_data
            
        except Exception as e:
            print(f" Error cargando proyecto: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @classmethod
    def _convert_to_absolute_paths(cls, project_data: Dict, project_folder: Path) -> Dict:
        """
        Convierte rutas relativas del proyecto a rutas absolutas.
        
        Args:
            project_data: Datos del proyecto con rutas relativas
            project_folder: Carpeta base del proyecto
            
        Returns:
            Dict: Datos del proyecto con rutas absolutas
        """
        updated_data = project_data.copy()
        
        def convert_path(path_str):
            if not path_str:
                return path_str
            
            path = Path(path_str)
            if not path.is_absolute():
                # Es relativa, convertirla a absoluta
                absolute_path = project_folder / path
                if absolute_path.exists():
                    return str(absolute_path.resolve())
            return path_str
        
        # Convertir rutas del storyboard
        if updated_data.get('storyboard'):
            storyboard = updated_data['storyboard']
            if storyboard.get('audio_path'):
                storyboard['audio_path'] = convert_path(storyboard['audio_path'])
            
            segments = storyboard.get('segments', [])
            for i, segment in enumerate(segments):
                if segment.get('image_path'):
                    segments[i]['image_path'] = convert_path(segment['image_path'])
                if segment.get('video_path'):
                    segments[i]['video_path'] = convert_path(segment['video_path'])
            
            storyboard['segments'] = segments
        
        # Convertir otras rutas
        for path_key in ['thumbnail_path', 'music_path']:
            if updated_data.get(path_key):
                updated_data[path_key] = convert_path(updated_data[path_key])

        thumbnail_data = updated_data.get('thumbnail_data')
        if isinstance(thumbnail_data, dict):
            if thumbnail_data.get('thumbnail_path'):
                thumbnail_data['thumbnail_path'] = convert_path(thumbnail_data['thumbnail_path'])

            updated_variants = []
            for variant in thumbnail_data.get('thumbnail_variants', []) or []:
                if not isinstance(variant, dict):
                    continue
                updated_variant = variant.copy()
                for path_key in ('path', 'raw_path'):
                    if updated_variant.get(path_key):
                        updated_variant[path_key] = convert_path(updated_variant[path_key])
                updated_variants.append(updated_variant)
            thumbnail_data['thumbnail_variants'] = updated_variants

        config = updated_data.get('config')
        if isinstance(config, dict) and config.get('selected_music_path'):
            config['selected_music_path'] = convert_path(config['selected_music_path'])
        
        # Convertir rutas del video generado
        if updated_data.get('generated_video_data'):
            video_data = updated_data['generated_video_data']
            for path_key in ['video_path', 'teaser_video_path', 'audio_path']:
                if video_data.get(path_key):
                    video_data[path_key] = convert_path(video_data[path_key])
        
        return updated_data
    
    @classmethod
    def list_projects(cls) -> List[Dict]:
        """
        Lista todos los proyectos guardados.
        
        Returns:
            List[Dict]: Lista de diccionarios con información de cada proyecto
        """
        projects = []
        
        try:
            cls._ensure_projects_dir()
            
            # Buscar carpetas de proyectos (que contengan project.json)
            for item in cls.PROJECTS_DIR.iterdir():
                if item.is_dir():
                    project_json = item / "project.json"
                    if project_json.exists():
                        try:
                            with open(project_json, 'r', encoding='utf-8') as f:
                                project_data = json.load(f)
                            
                            config = project_data.get('config', {})
                            metadata = project_data.get('project_metadata', {})
                            
                            projects.append({
                                'path': str(project_json),
                                'folder': str(item),
                                'name': item.name,
                                'topic': config.get('topic', 'Sin título'),
                                'created': metadata.get('created', ''),
                                'version': metadata.get('version', '1.0'),
                                'isolation_mode': metadata.get('isolation_mode', False),
                                'progress': project_data.get('progress', {}),
                                'file_size': project_json.stat().st_size
                            })
                        except Exception as e:
                            print(f"️ Error leyendo proyecto {project_json}: {e}")
                            continue
            
            # Ordenar por fecha de creación (más recientes primero)
            projects.sort(key=lambda x: x.get('created', ''), reverse=True)
            
        except Exception as e:
            print(f" Error listando proyectos: {e}")
        
        return projects
    
    @classmethod
    def delete_project(cls, project_path: str) -> bool:
        """
        Elimina completamente un proyecto y todos sus archivos.
        
        Args:
            project_path: Ruta al archivo JSON del proyecto
            
        Returns:
            bool: True si se eliminó correctamente
        """
        try:
            project_path = Path(project_path)
            project_folder = project_path.parent
            
            # Verificar que es un proyecto válido
            project_json = project_folder / "project.json"
            if not project_json.exists():
                print(f" No se encontró project.json en: {project_folder}")
                return False
            
            # Eliminar toda la carpeta del proyecto
            shutil.rmtree(project_folder)
            print(f" Proyecto eliminado: {project_folder}")
            return True
            
        except Exception as e:
            print(f" Error eliminando proyecto: {e}")
            return False
    
    @classmethod
    def create_project_data(
        cls,
        storyboard_data: Optional[Dict] = None,
        config: Optional[Dict] = None,
        progress: Optional[Dict] = None,
        thumbnail_path: Optional[str] = None,
        thumbnail_data: Optional[Dict] = None,
        music_path: Optional[str] = None,
        music_metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Crea la estructura de datos del proyecto.
        
        Args:
            storyboard_data: Datos del storyboard
            config: Configuraciones
            progress: Estado del progreso
            thumbnail_path: Ruta al thumbnail
            thumbnail_data: Datos completos del pipeline de thumbnails
            music_path: Ruta a la música
            music_metadata: Metadatos de la música
        
        Returns:
            dict: Estructura completa del proyecto
        """
        project = {
            'version': '2.0',
            'created': datetime.now().isoformat(),
            'config': config or {},
            'storyboard': storyboard_data or {},
            'progress': progress or {
                'storyboard_done': False,
                'images_done': False,
                'video_assembled': False,
                'published': False
            },
            'thumbnail_path': thumbnail_path,
            'thumbnail_data': thumbnail_data,
            'music_path': music_path,
            'music_metadata': music_metadata,
            'isolation_mode': True
        }
        
        # Actualizar progreso basado en los datos disponibles
        if storyboard_data and storyboard_data.get('segments'):
            project['progress']['storyboard_done'] = True
        
        return project
