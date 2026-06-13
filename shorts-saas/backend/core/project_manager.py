# project_manager.py
"""
Sistema de gestión de proyectos para Video Optimizer Pro
Permite guardar y cargar el estado del proyecto para continuar más tarde
"""

import builtins
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any


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


class ProjectManager:
    """Gestiona el guardado y carga de proyectos"""
    
    ROOT_DIR = Path(__file__).resolve().parent
    PROJECTS_DIR = ROOT_DIR / "projects"
    _dir_ensured = False
    
    @classmethod
    def _ensure_projects_dir(cls):
        """Asegura que el directorio de proyectos existe (lazy initialization)"""
        if cls._dir_ensured:
            return
        
        import os
        projects_path = str(cls.PROJECTS_DIR)
        
        try:
            # Intentar crear el directorio directamente con os.makedirs
            # que es más robusto en Windows que Path.exists() + Path.mkdir()
            # NO usar Path.exists() aquí porque puede causar EINVAL en Windows
            os.makedirs(projects_path, exist_ok=True)
            cls._dir_ensured = True
        except (PermissionError, OSError, ValueError) as e:
            # Si falla, solo loguear pero no fallar - se intentará de nuevo cuando se necesite
            # No usar print aquí para evitar problemas de importación
            try:
                import sys
                sys.stderr.write(f"⚠️ Advertencia: No se pudo crear directorio projects: {e}\n")
            except:
                pass
            cls._dir_ensured = False
        except Exception as e:
            # Cualquier otro error
            try:
                import sys
                sys.stderr.write(f"⚠️ Advertencia: Error inesperado creando directorio projects: {e}\n")
            except:
                pass
            cls._dir_ensured = False
    
    @staticmethod
    def save_project(project_data: Dict[str, Any], project_name: Optional[str] = None) -> Optional[str]:
        """
        Guarda un proyecto en un archivo JSON.
        
        Args:
            project_data: Diccionario con todos los datos del proyecto
            project_name: Nombre del proyecto (si None, se genera automáticamente)
        
        Returns:
            str: Ruta al archivo guardado, o None si hay error
        """
        try:
            # Asegurar que el directorio existe (por si acaso)
            ProjectManager._ensure_projects_dir()
            
            # Generar nombre de proyecto si no se proporciona
            if not project_name:
                topic = project_data.get('config', {}).get('topic', 'Video')
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                project_name = f"{topic}_{timestamp}".replace(' ', '_')[:50]
            
            # Asegurar extensión .json
            if not project_name.endswith('.json'):
                project_name += '.json'
            
            # Limpiar caracteres inválidos del nombre de archivo
            import re
            project_name = re.sub(r'[<>:"/\\|?*]', '_', project_name)
            
            project_path = ProjectManager.PROJECTS_DIR / project_name
            
            # Guardar proyecto
            with open(project_path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Proyecto guardado: {project_path}")
            return str(project_path)
            
        except Exception as e:
            print(f"❌ Error guardando proyecto: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    def load_project(project_path: str) -> Optional[Dict[str, Any]]:
        """
        Carga un proyecto desde un archivo JSON.
        
        Args:
            project_path: Ruta al archivo del proyecto
        
        Returns:
            dict: Datos del proyecto, o None si hay error
        """
        try:
            if not os.path.exists(project_path):
                print(f"❌ El archivo del proyecto no existe: {project_path}")
                return None
            
            with open(project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            print(f"✅ Proyecto cargado: {project_path}")
            return project_data
            
        except Exception as e:
            print(f"❌ Error cargando proyecto: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    def list_projects() -> list:
        """
        Lista todos los proyectos guardados.
        
        Returns:
            list: Lista de diccionarios con información de cada proyecto
        """
        projects = []
        
        try:
            # Asegurar que el directorio existe
            ProjectManager._ensure_projects_dir()
            
            # Usar os.listdir en lugar de Path.glob para evitar problemas con stat()
            import os
            projects_dir_str = str(ProjectManager.PROJECTS_DIR)
            try:
                json_files = [f for f in os.listdir(projects_dir_str) if f.endswith('.json')]
            except (OSError, PermissionError):
                # Si no se puede listar, retornar lista vacía
                return []
            
            for json_file in json_files:
                project_file = ProjectManager.PROJECTS_DIR / json_file
                try:
                    with open(project_file, 'r', encoding='utf-8') as f:
                        project_data = json.load(f)
                    
                    # Obtener información básica
                    config = project_data.get('config', {})
                    topic = config.get('topic', 'Sin título')
                    created = project_data.get('created', '')
                    progress = project_data.get('progress', {})
                    
                    projects.append({
                        'path': str(project_file),
                        'name': project_file.stem,
                        'topic': topic,
                        'created': created,
                        'progress': progress,
                        'file_size': os.path.getsize(project_file)
                    })
                except Exception as e:
                    print(f"⚠️ Error leyendo proyecto {project_file}: {e}")
                    continue
            
            # Ordenar por fecha de creación (más recientes primero)
            projects.sort(key=lambda x: x.get('created', ''), reverse=True)
            
        except Exception as e:
            print(f"❌ Error listando proyectos: {e}")
        
        return projects
    
    @staticmethod
    def create_project_data(
        storyboard_data: Optional[Dict] = None,
        config: Optional[Dict] = None,
        progress: Optional[Dict] = None,
        thumbnail_path: Optional[str] = None,
        music_path: Optional[str] = None,
        music_metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Crea la estructura de datos del proyecto.
        
        Args:
            storyboard_data: Datos del storyboard (segments, script, audio_path, etc.)
            config: Configuraciones (plataforma, idioma, estilo, etc.)
            progress: Estado del progreso (storyboard_done, images_done, etc.)
            thumbnail_path: Ruta al thumbnail si existe
            music_path: Ruta a la música seleccionada si existe
        
        Returns:
            dict: Estructura completa del proyecto
        """
        project = {
            'version': '1.0',
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
            'music_path': music_path,
            'music_metadata': music_metadata
        }
        
        # Actualizar progreso basado en los datos disponibles
        if storyboard_data and storyboard_data.get('segments'):
            project['progress']['storyboard_done'] = True
        
        return project
