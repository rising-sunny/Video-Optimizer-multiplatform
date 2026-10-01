from PyQt6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QDialog
from PyQt6.QtCore import QTimer
import os
import json
import glob
import shutil
import traceback
import copy
from pathlib import Path
from datetime import datetime, timedelta
from studio.studio_channel_controls import project_channel_config, restore_channel_config
from media.gdrive_file_utils import safe_copy2


class ProjectMediaMixin:
    def validate_project_files(self, project_data):
        """Valida que los archivos referenciados en el proyecto existan"""

        warnings = []


        # Validar audio del storyboard

        storyboard = project_data.get('storyboard') or {}

        audio_path = storyboard.get('audio_path')

        if audio_path and not os.path.exists(audio_path):

            warnings.append(f" Audio no encontrado: {audio_path}")


        # Validar imágenes de segmentos

        segments = storyboard.get('segments', [])

        missing_images = 0

        for i, segment in enumerate(segments):

            image_path = segment.get('image_path')

            if image_path:

                # Si es ruta relativa, intentar resolverla desde projects/

                if not os.path.isabs(image_path) and not os.path.exists(image_path):

                    from pathlib import Path

                    # Intentar desde projects/

                    possible_path = Path("projects") / image_path

                    if possible_path.exists():

                        segment['image_path'] = str(possible_path.resolve())

                        continue

                    # Intentar desde el directorio actual

                    possible_path = Path(image_path)

                    if possible_path.exists():

                        segment['image_path'] = str(possible_path.resolve())

                        continue


                # Verificar si existe después de intentar resolver

                if not os.path.exists(image_path):

                    missing_images += 1


        if missing_images > 0:

            warnings.append(

                f"️ {missing_images} imagen(es) de segmentos no encontrada(s)")


        # Validar thumbnail

        thumbnail_path = project_data.get('thumbnail_path')

        if thumbnail_path and not os.path.exists(thumbnail_path):

            warnings.append(f"️ Thumbnail no encontrado: {thumbnail_path}")


        # Validar música

        music_path = project_data.get('music_path')

        if music_path and not os.path.exists(music_path):

            warnings.append(f"️ Música no encontrada: {music_path}")


        return warnings



    def _copy_manual_media_to_project(self, storyboard_data):
        """

        Copia imágenes/videos manuales y actualiza rutas en los segmentos.

        Retorna el storyboard_data con rutas actualizadas.

        """

        if not storyboard_data or not storyboard_data.get('segments'):

            return storyboard_data


        # Crear una copia para no modificar el original

        storyboard_copy = storyboard_data.copy()

        storyboard_copy['segments'] = [seg.copy() for seg in storyboard_data['segments']]


        # Preparar estructura para copiar archivos (se hará después cuando tengamos el path del proyecto)

        # Por ahora solo retornamos una copia (los archivos se copiarán en _copy_manual_media_files)

        return storyboard_copy



    def _copy_manual_media_files(self, project_path, storyboard_data):
        """

        Copia archivos de imágenes/videos (manuales e IA generadas) a la carpeta del proyecto.


        Args:

            project_path: Ruta al archivo JSON del proyecto

            storyboard_data: Datos del storyboard con segmentos


        Returns:

            storyboard_data con rutas actualizadas, o None si no hay cambios

        """

        if not storyboard_data or not storyboard_data.get('segments'):
            return storyboard_data
        
        print(f"[_copy_manual_media_files]  Iniciando copia de medios para {len(storyboard_data.get('segments', []))} segmentos...")

        try:

            from pathlib import Path

            import shutil


            project_path_obj = Path(project_path)

            project_dir = project_path_obj.parent

            project_name = project_path_obj.stem  # Nombre sin extensión


            # Crear carpeta de media para este proyecto
            # Usar formato nuevo: project_media dentro de la carpeta del proyecto
            media_dir = project_dir / "project_media"
            media_dir.mkdir(exist_ok=True)


            segments = storyboard_data.get('segments', [])

            copied_files = []
            
            manual_sources = ['wikimedia', 'google_images', 'pexels_video', 'wikimedia_video', 'internet_archive', 'youtube', 'local', 'file']

            for i, seg in enumerate(segments):

                image_source = seg.get('image_source', '')
                video_source = seg.get('video_source', '')

                image_path = seg.get('image_path')

                video_path = seg.get('video_path')
                
                # Debug: mostrar segmentos con medios manuales
                if (image_source in manual_sources or video_source in manual_sources) and (image_path or video_path):
                    print(f"    Segmento {i+1}: {image_source or video_source}, image_path={Path(image_path).name if image_path else None}, video_path={Path(video_path).name if video_path else None}")

                # Verificar si es contenido manual o IA generada
                # Considerar tanto image_source como video_source
                is_manual = (image_source in manual_sources) or (video_source in manual_sources)

                ai_sources = [
                    'fal_ai', 'fal',
                    'leonardo', 'leonardo_ai',
                    'recraft_ai', 'recraft_compat_leonardo',
                    'google_ai', 'vertex_imagen', 'existing'
                ]
                is_ai_generated = (image_source in ai_sources) or (video_source in ai_sources)


                # Copiar imagen/video si existe (manual o IA)
                # CRÍTICO: Si el archivo está en una carpeta temporal (como youtube_downloads), DEBE copiarse al proyecto
                # Esto asegura que los videos/imágenes agregados manualmente se conserven después de cerrar la app
                
                # FIX: Copiar también si es una ruta absoluta externa, aunque no tenga image_source marcado
                should_check_image = False
                if image_path and os.path.exists(image_path):
                    if is_manual or is_ai_generated:
                        should_check_image = True
                    elif os.path.isabs(image_path):
                         # Es ruta absoluta, verificar si es externa (se verifica abajo en is_outside_project)
                         should_check_image = True

                if should_check_image:
                    # Verificar si el archivo está en una carpeta temporal que debe copiarse al proyecto
                    image_path_str = str(image_path)
                    # Normalizar la ruta para comparaciones más robustas
                    try:
                        image_path_resolved = str(Path(image_path).resolve())
                    except:
                        image_path_resolved = image_path_str
                    
                    # Detectar ubicaciones temporales (con múltiples formatos de ruta)
                    is_temp_location = any(
                        temp_dir in image_path_resolved.replace('\\', '/').lower() or 
                        temp_dir in image_path_str.replace('\\', '/').lower()
                        for temp_dir in [
                            'youtube_downloads', 'wikimedia_downloads', 'internet_archive_downloads',
                            'video_optimizer', 'appdata/local/temp', 'temp/', '/tmp/',
                            'temp\\', '\\tmp\\'
                        ]
                    )
                    # Verificar si está fuera de la carpeta del proyecto
                    is_outside_project = False
                    try:
                        project_dir_resolved = str(project_dir.resolve())
                        is_outside_project = not image_path_resolved.startswith(project_dir_resolved)
                    except:
                        # Si hay error resolviendo rutas, asumir que está fuera
                        is_outside_project = True
                    
                    # IMPORTANTE: Si la imagen ya está en project_media con ruta relativa, no copiar de nuevo
                    # Verificar si image_path es relativa y apunta a project_media
                    is_already_in_project = False
                    if not os.path.isabs(image_path):
                        # Es una ruta relativa, verificar si apunta a project_media
                        if image_path.startswith('project_media/'):
                            # Ya está en project_media, verificar que el archivo existe
                            possible_path = project_dir / image_path
                            if possible_path.exists():
                                is_already_in_project = True
                                # Asegurar que la ruta esté correctamente guardada
                                seg['image_path'] = image_path  # Mantener ruta relativa
                                print(f"    Imagen IA ya está en project_media: {Path(image_path).name}")
                    
                    # También verificar rutas absolutas que ya están dentro de media_dir
                    if not is_already_in_project and os.path.isabs(image_path):
                        try:
                            media_dir_resolved = str(media_dir.resolve())
                            if image_path_resolved.startswith(media_dir_resolved):
                                # Ya está en project_media con ruta absoluta, convertir a relativa
                                rel_filename = Path(image_path).name
                                seg['image_path'] = f"project_media/{rel_filename}"
                                if video_path == image_path:
                                    seg['video_path'] = f"project_media/{rel_filename}"
                                is_already_in_project = True
                        except:
                            pass

                    # Si es una ubicación temporal O está fuera de la carpeta del proyecto, copiarlo
                    # PERO NO si ya está en project_media
                    should_copy = (is_temp_location or is_outside_project) and not is_already_in_project

                    # Si ya está en project_media, saltar todo el proceso de copia
                    if is_already_in_project:
                        continue  # Saltar al siguiente segmento
                    
                    if is_temp_location:
                        print(f"    Detectado archivo en ubicación temporal: {Path(image_path).name}")
                    
                    source_path = Path(image_path)

                    # Generar nombre único para el archivo en la carpeta del proyecto
                    # IMPORTANTE: Limitar longitud del nombre para evitar errores en Windows (máx 260 chars en ruta completa)

                    # Para imágenes IA, usar formato project_segment_XXX.jpg para facilitar restauración
                    if is_ai_generated:
                        # Obtener índice del segmento para usar formato project_segment_XXX.jpg
                        segment_index = segments.index(seg)
                        segment_number = segment_index + 1
                        # Usar formato: project_segment_XXX.jpg (más fácil de restaurar)
                        filename = f"project_segment_{segment_number:03d}.jpg"
                    else:
                        filename = source_path.name
                    
                    # Limitar longitud del nombre del archivo (máximo ~200 caracteres para dejar espacio a la ruta)
                    # Si el nombre es muy largo, truncarlo y usar hash como identificador único
                    MAX_FILENAME_LENGTH = 200
                    ext = Path(filename).suffix
                    name_part = Path(filename).stem
                    
                    if len(filename) > MAX_FILENAME_LENGTH:
                        # Si el nombre es demasiado largo, usar hash como identificador principal
                        import hashlib
                        # Crear hash del nombre original para mantener unicidad
                        name_hash = hashlib.md5(name_part.encode()).hexdigest()[:12]
                        # Truncar nombre original pero mantener algo legible
                        truncated_name = name_part[:50] if len(name_part) > 50 else name_part
                        filename = f"{truncated_name}_{name_hash}{ext}"
                        if hasattr(self, 'studio_tab') and hasattr(self.studio_tab, 'log'):
                            self.studio_tab.log(f"      ️ Nombre de archivo truncado (era muy largo): {source_path.name[:80]}... -> {filename}")
                        else:
                            print(f"      ️ Nombre de archivo truncado (era muy largo): {source_path.name[:80]}... -> {filename}")

                    # Si el archivo ya existe, agregar hash para evitar colisiones

                    if (media_dir / filename).exists():

                        import hashlib

                        hash_suffix = hashlib.md5(str(image_path).encode()).hexdigest()[:8]

                        name_part = Path(filename).stem

                        ext = Path(filename).suffix
                        
                        # Asegurar que el nombre final no exceda el límite
                        new_filename = f"{name_part}_{hash_suffix}{ext}"
                        if len(new_filename) > MAX_FILENAME_LENGTH:
                            # Si aún es muy largo, usar solo hash
                            filename = f"img_{hash_suffix}{ext}"
                        else:
                            filename = new_filename


                    dest_path = media_dir / filename


                    # Copiar archivo (solo si no es el mismo archivo)
                    # IMPORTANTE: Si está en ubicación temporal, SIEMPRE copiar
                    should_copy_file = should_copy or str(source_path.resolve()) != str(dest_path.resolve())

                    if should_copy_file:

                        try:
                            safe_copy2(source_path, dest_path)
                            if is_temp_location:
                                print(f"    Video copiado desde ubicación temporal: {source_path.name} -> {media_dir.name}")
                        except Exception as e:
                            print(f"   ️ Error copiando archivo desde ubicación temporal {source_path}: {e}")
                            # Continuar aunque falle, el archivo puede estar en la ubicación temporal original


                        # Actualizar ruta en el segmento (relativa al proyecto)
                        # Usar formato nuevo: project_media/filename
                        rel_path = f"project_media/{filename}"

                        seg['image_path'] = rel_path
                        # IMPORTANTE: Preservar image_source si existe
                        if 'image_source' not in seg:
                            # Si no hay image_source, intentar establecerlo basado en el tipo de contenido
                            # Si ya existe, se mantiene (no se sobrescribe)
                            pass
                        # Si video_path es el mismo que image_path, también actualizar video_path
                        if video_path == image_path:
                            seg['video_path'] = rel_path
                            # Preservar video_source si existe
                            if 'video_source' not in seg and 'image_source' in seg:
                                seg['video_source'] = seg['image_source']
                            # IMPORTANTE: Si el archivo original estaba en ubicación temporal, ya fue copiado
                            # Marcar que ya no necesita copia adicional
                            if is_temp_location:
                                print(f"    Video/imagen copiado desde ubicación temporal (video_path==image_path): {source_path.name}")


                        copied_files.append(filename)


                # IMPORTANTE: Copiar video si existe y es manual
                # Si video_path == image_path, ya debería haberse copiado en el bloque de imágenes arriba
                # Este bloque solo maneja el caso donde video_path es diferente de image_path
                
                # FIX: Copiar también si es una ruta absoluta externa, aunque no tenga video_source marcado
                should_check_video = False
                if video_path and os.path.exists(video_path) and video_path != image_path:
                    if is_manual:
                         should_check_video = True
                    elif os.path.isabs(video_path):
                         should_check_video = True

                if should_check_video:
                    # Video es diferente de image_path, copiarlo separadamente
                    # Verificar si el video está en una carpeta temporal que DEBE copiarse
                    video_path_str = str(video_path)
                    try:
                        video_path_resolved = str(Path(video_path).resolve())
                    except:
                        video_path_resolved = video_path_str
                    
                    # Detectar ubicaciones temporales (con múltiples formatos de ruta)
                    is_video_temp = any(
                        temp_dir in video_path_resolved.replace('\\', '/').lower() or 
                        temp_dir in video_path_str.replace('\\', '/').lower()
                        for temp_dir in [
                            'youtube_downloads', 'wikimedia_downloads', 'internet_archive_downloads',
                            'video_optimizer', 'appdata/local/temp', 'temp/', '/tmp/',
                            'temp\\', '\\tmp\\'
                        ]
                    )
                    
                    # Verificar si está fuera de la carpeta del proyecto
                    is_video_outside_project = False
                    try:
                        project_dir_resolved = str(project_dir.resolve())
                        is_video_outside_project = not video_path_resolved.startswith(project_dir_resolved)
                    except:
                        is_video_outside_project = True
                    
                    # Verificar si el video ya está dentro de media_dir (ruta absoluta)
                    is_video_already_in_project = False
                    if os.path.isabs(video_path):
                        try:
                            media_dir_resolved_v = str(media_dir.resolve())
                            if video_path_resolved.startswith(media_dir_resolved_v):
                                rel_filename = Path(video_path).name
                                seg['video_path'] = f"project_media/{rel_filename}"
                                is_video_already_in_project = True
                        except:
                            pass
                    elif video_path.startswith('project_media/'):
                        possible_vpath = project_dir / video_path
                        if possible_vpath.exists():
                            is_video_already_in_project = True

                    # Si el video está en ubicación temporal o fuera del proyecto, copiarlo
                    if not is_video_already_in_project and (is_video_temp or is_video_outside_project):
                        if is_video_temp:
                            print(f"    Detectado video en ubicación temporal: {Path(video_path).name}")
                        source_path = Path(video_path)
                        filename = source_path.name
                        
                        # Limitar longitud del nombre del archivo (máximo ~200 caracteres para dejar espacio a la ruta)
                        MAX_FILENAME_LENGTH = 200
                        ext = source_path.suffix
                        name_part = source_path.stem
                        
                        if len(filename) > MAX_FILENAME_LENGTH:
                            # Si el nombre es demasiado largo, usar hash como identificador principal
                            import hashlib
                            # Crear hash del nombre original para mantener unicidad
                            name_hash = hashlib.md5(name_part.encode()).hexdigest()[:12]
                            # Truncar nombre original pero mantener algo legible
                            truncated_name = name_part[:50] if len(name_part) > 50 else name_part
                            filename = f"{truncated_name}_{name_hash}{ext}"
                            if hasattr(self, 'studio_tab') and hasattr(self.studio_tab, 'log'):
                                self.studio_tab.log(f"      ️ Nombre de video truncado (era muy largo): {source_path.name[:80]}... -> {filename}")
                            else:
                                print(f"      ️ Nombre de video truncado (era muy largo): {source_path.name[:80]}... -> {filename}")

                        if (media_dir / filename).exists():
                            import hashlib
                            hash_suffix = hashlib.md5(str(video_path).encode()).hexdigest()[:8]
                            name_part = Path(filename).stem
                            ext = Path(filename).suffix
                            
                            # Asegurar que el nombre final no exceda el límite
                            new_filename = f"{name_part}_{hash_suffix}{ext}"
                            if len(new_filename) > MAX_FILENAME_LENGTH:
                                # Si aún es muy largo, usar solo hash
                                filename = f"video_{hash_suffix}{ext}"
                            else:
                                filename = new_filename

                        dest_path = media_dir / filename
                        should_copy_video = str(source_path.resolve()) != str(dest_path.resolve())

                        if should_copy_video:
                            try:
                                safe_copy2(source_path, dest_path)
                                if is_video_temp:
                                    print(f"    Video copiado desde ubicación temporal: {source_path.name} -> {media_dir.name}")
                            except Exception as e:
                                print(f"   ️ Error copiando video desde ubicación temporal {source_path}: {e}")
                                # Continuar aunque falle

                            rel_path = f"project_media/{filename}"
                            seg['video_path'] = rel_path
                            # IMPORTANTE: Preservar video_source si existe
                            if 'video_source' not in seg:
                                # Si no hay video_source, intentar establecerlo basado en el tipo de contenido
                                # Si ya existe, se mantiene (no se sobrescribe)
                                pass
                            # Si no hay image_path, usar el mismo archivo para image_path
                            if not seg.get('image_path'):
                                seg['image_path'] = rel_path  # rel_path ya es "project_media/{filename}"
                                # Si video_source existe, usarlo también como image_source
                                if 'video_source' in seg and 'image_source' not in seg:
                                    seg['image_source'] = seg['video_source']

                            copied_files.append(filename)


            if copied_files:

                self.studio_tab.log(f" {len(copied_files)} archivo(s) de medios copiados a: {media_dir}")

                # Retornar el storyboard con rutas actualizadas

                return storyboard_data

            else:

                # No se copiaron archivos, retornar sin cambios

                return storyboard_data


        except Exception as e:

            self.studio_tab.log(f"️ Error copiando archivos de medios: {e}")

            import traceback

            traceback.print_exc()

            # Retornar sin cambios en caso de error

            return storyboard_data





    def _find_media_without_hash(self, file_path):
        """Busca una versión del archivo sin sufijos hash.

        Si project_segment_001_6c413e3b.jpg no existe, intenta project_segment_001.jpg.
        Esto permite que tras regenerar imágenes IA (con nombres limpios),
        las referencias antiguas con hash se resuelvan al archivo nuevo.
        """
        import re
        name = file_path.name
        # Pattern: project_segment_XXX seguido de uno o más _HASH antes de la extensión
        match = re.match(r'^(project_segment_\d{3})(?:_[a-f0-9]+)+(\.\w+)$', name)
        if match:
            base_name = match.group(1) + match.group(2)
            fallback = file_path.parent / base_name
            if fallback.exists():
                return fallback
        return None

    def _restore_media_paths(self, project_path, storyboard_data):
        """
        Restaura las rutas absolutas de los archivos de medios desde el proyecto guardado.
        Convierte rutas relativas guardadas en el proyecto a rutas absolutas.
        PRESERVA todos los campos de los segmentos, incluyendo image_source y video_source.

        SIMPLIFICADO: Las rutas en el JSON del proyecto son SIEMPRE relativas a la carpeta del proyecto.
        Solo necesitamos convertirlas a absolutas sumando project_dir + ruta_relativa.
        
        IMPORTANTE: image_source y video_source deben estar en el JSON del proyecto.
        Esta función solo actualiza las rutas, no elimina ni modifica otros campos.
        """
        if not storyboard_data or not storyboard_data.get('segments'):
            return storyboard_data

        try:
            from pathlib import Path

            project_path_obj = Path(project_path)
            project_dir = project_path_obj.parent  # Carpeta que contiene el project.json

            segments = storyboard_data.get('segments', [])

            # Obtener nombre del proyecto para buscar en project_media
            project_name = project_path_obj.stem
            # Formato antiguo: {project_name}_media
            project_media_dir = project_dir / f"{project_name}_media"
            # Formato nuevo v2: project_media dentro de la carpeta del proyecto
            project_media_dir_v2 = project_dir / "project_media"
            # Formato ProjectManagerV2: subcarpetas images/, videos/, etc. dentro de la carpeta del proyecto
            project_v2_images_dir = project_dir / "images"
            project_v2_videos_dir = project_dir / "videos"
            
            # Debug: verificar qué carpetas existen
            print(f"[_restore_media_paths] Buscando imágenes en:")
            print(f"   - project_media_dir_v2: {project_media_dir_v2} (existe: {project_media_dir_v2.exists()})")
            if project_media_dir_v2.exists():
                # Buscar ambos formatos: project_segment_*.ext y segment_*.ext
                image_files = list(project_media_dir_v2.glob("project_segment_*.*"))
                image_files += list(project_media_dir_v2.glob("segment_*.*"))
                # Filtrar solo imágenes
                image_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
                image_files = [f for f in image_files if f.suffix.lower() in image_exts]
                print(f"   - Encontrados {len(image_files)} archivos de imagen (project_segment_* + segment_*)")
                if len(image_files) > 0:
                    print(f"   - Primeros 5: {[f.name for f in image_files[:5]]}")
            
            # Lista para rastrear qué imágenes ya fueron asignadas (evitar duplicados)
            assigned_images = set()

            # Pre-build lookup: segment number -> image file in project_media
            # SAFE: only searches the project's OWN project_media folder
            import re
            _seg_image_lookup = {}
            if project_media_dir_v2.exists():
                image_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
                for img_file in sorted(project_media_dir_v2.iterdir()):
                    if img_file.suffix.lower() not in image_exts:
                        continue
                    # Match both: project_segment_001.png and segment_001_TIMESTAMP.png
                    m = re.match(r'(?:project_)?segment_(\d{3})', img_file.name)
                    if m:
                        seg_num = int(m.group(1))
                        if seg_num not in _seg_image_lookup:
                            _seg_image_lookup[seg_num] = img_file

            for seg_idx, seg in enumerate(segments):
                restored = False
                image_path = seg.get('image_path')

                # If segment has no image_path, try to restore from project's own media folder
                if not image_path or (image_path and not os.path.isabs(image_path) and not (project_dir / image_path).exists()):
                    seg_num = seg_idx + 1
                    if seg_num in _seg_image_lookup:
                        matched_file = _seg_image_lookup[seg_num]
                        resolved_path = str(matched_file.resolve())
                        if resolved_path not in assigned_images:
                            seg['image_path'] = resolved_path
                            assigned_images.add(resolved_path)
                            restored = True
                
                # Solo procesar rutas que estén explícitamente en el JSON
                # NUNCA buscar automáticamente en el disco
                #
                # NOTA: la dedup `assigned_images` se RELAJÓ — antes borraba el image_path
                # cuando dos segmentos compartían la misma imagen, lo cual es legítimo
                # cuando el usuario elige "N segmentos por imagen" (agrupación). El
                # tracking se mantiene a nivel informativo, pero ya NO se borra el path.
                if image_path and not restored:
                    restored = False
                    if not os.path.isabs(image_path):
                        # Ruta relativa: convertir a absoluta desde project_dir
                        abs_path = project_dir / image_path
                        if abs_path.exists():
                            resolved_path = str(abs_path.resolve())
                            seg['image_path'] = resolved_path
                            assigned_images.add(resolved_path)
                            restored = True
                        else:
                            # Ruta relativa no existe: intentar versión sin hash
                            fallback = self._find_media_without_hash(abs_path)
                            if fallback:
                                resolved_path = str(fallback.resolve())
                                seg['image_path'] = resolved_path
                                assigned_images.add(resolved_path)
                                restored = True
                                print(f"    Imagen {abs_path.name}  {fallback.name} (fallback sin hash)")
                            else:
                                print(f"   ️ Imagen no encontrada {abs_path.name}, eliminando referencia")
                                if 'image_path' in seg:
                                    del seg['image_path']
                                if 'image_source' in seg:
                                    del seg['image_source']
                                image_path = None
                    else:
                        # Ruta absoluta: verificar que existe
                        if not os.path.exists(image_path):
                            # Intentar versión sin hash
                            fallback = self._find_media_without_hash(Path(image_path))
                            if fallback:
                                resolved_path = str(fallback.resolve())
                                seg['image_path'] = resolved_path
                                print(f"    Imagen {Path(image_path).name}  {fallback.name} (fallback sin hash)")
                            else:
                                print(f"   ️ Imagen absoluta no encontrada {image_path}, eliminando referencia")
                                if 'image_path' in seg:
                                    del seg['image_path']
                                if 'image_source' in seg:
                                    del seg['image_source']
                                image_path = None

                # Restaurar video_path - solo procesar rutas explícitas
                video_path = seg.get('video_path')
                if video_path:
                    if not os.path.isabs(video_path):
                        # Ruta relativa: convertir a absoluta desde project_dir
                        abs_path = project_dir / video_path
                        if abs_path.exists():
                            seg['video_path'] = str(abs_path.resolve())
                        else:
                            # Si no existe, eliminar referencia
                            print(f"   ️ Video no encontrado {abs_path.name}, eliminando referencia")
                            if 'video_path' in seg:
                                del seg['video_path']
                            if 'video_source' in seg:
                                del seg['video_source']
                    else:
                        # Ruta absoluta: verificar que existe
                        if not os.path.exists(video_path):
                            print(f"   ️ Video absoluto no encontrado {video_path}, eliminando referencia")
                            if 'video_path' in seg:
                                del seg['video_path']
                            if 'video_source' in seg:
                                del seg['video_source']
            
            # Debug final: contar cuántas imágenes se restauraron
            images_restored_count = sum(1 for seg in segments if seg.get('image_path'))
            print(f"[_restore_media_paths]  Total de imágenes restauradas: {images_restored_count} de {len(segments)} segmentos")
            
            return storyboard_data

        except Exception as e:
            self.studio_tab.log(f"Error restaurando rutas de medios: {e}")
            import traceback
            traceback.print_exc()
            return storyboard_data
