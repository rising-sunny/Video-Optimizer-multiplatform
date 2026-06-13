# video_assembler.py
"""
Ensamblador de video contextual
Ensambla video colocando imágenes/videos en timestamps exactos con transiciones profesionales
"""

import os
import numpy as np
from PIL import Image
from typing import List, Dict, Optional, Tuple

# Verificar dependencias
MOVIEPY_AVAILABLE = False
CINEMATIC_AVAILABLE = False

try:
    from moviepy.editor import (
        VideoFileClip, AudioFileClip, ImageClip,
        CompositeVideoClip, concatenate_videoclips,
        TextClip, CompositeAudioClip, concatenate_audioclips
    )
    import moviepy.audio.fx.all as vfx
    import moviepy.video.fx.all as vfx_video
    from moviepy.audio.AudioClip import AudioClip
    MOVIEPY_AVAILABLE = True
except ImportError as e:
    print(f"️ MoviePy no disponible: {e}")

try:
    from cinematic_effects import CinematicEffectsEngine
    CINEMATIC_AVAILABLE = True
except ImportError:
    CINEMATIC_AVAILABLE = False


class ContextualVideoAssembler:
    """
    Ensambla video colocando imágenes/videos en timestamps exactos.
    """

    def __init__(self):
        if not MOVIEPY_AVAILABLE:
            print(" Error Crítico: MoviePy no está disponible")

    def _normalize_transition_name(self, transition_type) -> str:
        """
        Devuelve el nombre real de la transicion seleccionado en la UI.
        Mantiene nombres como "Fade Smooth" o "Zoom Transition" intactos,
        pero tolera prefijos visuales/emoji usados por versiones antiguas.
        """
        name = str(transition_type or "").strip()
        while name and not name[0].isalnum():
            name = name[1:].strip()
        return name

    def _is_no_transition(self, transition_type) -> bool:
        name = self._normalize_transition_name(transition_type).lower()
        if not name:
            return True
        no_transition_tokens = (
            "none",
            "ninguna",
            "direct cut",
            "corte directo",
            "sin transicion",
            "sin transici",
        )
        return any(token in name for token in no_transition_tokens)

    def _ensure_frame_rgb(self, frame):
        """Normaliza frames a RGB HxWx3 para evitar errores de broadcasting."""
        if frame is None:
            return frame

        arr = np.asarray(frame)
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        elif arr.ndim == 3 and arr.shape[2] == 1:
            arr = np.repeat(arr, 3, axis=2)
        elif arr.ndim == 3 and arr.shape[2] > 3:
            arr = arr[:, :, :3]

        return np.ascontiguousarray(arr)

    def _create_image_clip_from_frame(self, frame, duration):
        """Crea un ImageClip garantizando un frame RGB valido para MoviePy."""
        return ImageClip(self._ensure_frame_rgb(frame)).set_duration(duration)

    def _create_image_clip_from_path(self, image_path, duration, apply_saturation=False):
        """Carga una imagen como RGB para evitar clips 2D o grayscale en composiciones."""
        try:
            with Image.open(image_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                if apply_saturation:
                    from PIL import ImageEnhance
                    enhancer = ImageEnhance.Color(img)
                    img = enhancer.enhance(1.15)
                frame = np.array(img)
            return self._create_image_clip_from_frame(frame, duration)
        except Exception as e:
            print(f"      Warning: no se pudo normalizar {os.path.basename(image_path)} a RGB: {e}")
            return ImageClip(image_path).set_duration(duration).fl_image(self._ensure_frame_rgb)

    def _preprocess_video_clip(self, video_path, target_duration, apply_saturation=False):
        """
        Pre-procesa un video clip con FFmpeg para garantizar:
        - Keyframes regulares (sin problemas de seek)
        - Duración exacta (loop si es corto, truncar si es largo)
        - Codec estándar compatible con MoviePy

        Returns:
            str: Ruta al archivo procesado, o None si falla
        """
        import subprocess
        import tempfile
        import shutil

        ffmpeg_exe = shutil.which("ffmpeg")
        if not ffmpeg_exe:
            return None

        try:
            temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4')
            os.close(temp_fd)

            # Obtener duración original del video con ffprobe
            original_duration = None
            ffprobe_exe = shutil.which("ffprobe")
            if not ffprobe_exe:
                # Intentar encontrar ffprobe junto a ffmpeg
                ffmpeg_dir = os.path.dirname(ffmpeg_exe)
                probe_candidate = os.path.join(ffmpeg_dir, "ffprobe.exe" if os.name == 'nt' else "ffprobe")
                if os.path.exists(probe_candidate):
                    ffprobe_exe = probe_candidate

            if ffprobe_exe:
                try:
                    probe_result = subprocess.run(
                        [ffprobe_exe, '-v', 'error', '-show_entries', 'format=duration',
                         '-of', 'csv=p=0', video_path],
                        capture_output=True, text=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    if probe_result.returncode == 0 and probe_result.stdout.strip():
                        original_duration = float(probe_result.stdout.strip())
                except Exception:
                    pass

            # Construir comando FFmpeg
            cmd = [ffmpeg_exe, '-y']

            needs_loop = original_duration is not None and original_duration < target_duration
            if needs_loop:
                loops_needed = int(target_duration / original_duration) + 1
                cmd.extend(['-stream_loop', str(loops_needed)])
                print(f"       Looping video: {original_duration:.1f}s × {loops_needed + 1}  {target_duration:.1f}s")

            vf_filters = []
            if apply_saturation:
                vf_filters.append('eq=saturation=1.15')
            
            cmd.extend([
                '-i', video_path,
                '-t', str(target_duration),
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-pix_fmt', 'yuv420p',
                '-g', '30',  # Keyframe cada 1s a 30fps (seek limpio)
                '-an'        # Sin audio
            ])
            if vf_filters:
                cmd.extend(['-vf', ','.join(vf_filters)])
            cmd.append(temp_path)

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 500:
                return temp_path
            else:
                # Limpiar temp fallido
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                if result.stderr:
                    print(f"      ️ FFmpeg pre-proceso falló: {result.stderr[-150:]}")
                return None

        except Exception as e:
            print(f"      ️ Error pre-procesando video: {e}")
            return None

    def _resize_clip_to_fill(self, clip, target_resolution, source_path=None):
        """
        Redimensiona un clip para llenar completamente el frame objetivo.
        Mantiene aspect ratio y recorta si es necesario (sin bandas negras).

        Args:
            clip: MoviePy clip (ImageClip o VideoFileClip)
            target_resolution: Tupla (width, height)
            source_path: Ruta al archivo original (para obtener dimensiones)

        Returns:
            Clip redimensionado y recortado al tamaño objetivo
        """
        try:
            target_width, target_height = target_resolution

            # Obtener dimensiones originales
            if source_path and os.path.exists(source_path):
                if source_path.lower().endswith(('.mp4', '.mov', '.avi', '.webm')):
                    # Para videos, usar el tamaño del clip
                    orig_width, orig_height = clip.size
                else:
                    # Para imágenes, usar PIL para obtener tamaño
                    with Image.open(source_path) as img:
                        orig_width, orig_height = img.size
            else:
                orig_width, orig_height = clip.size

            # Calcular proporciones
            aspect_ratio = orig_width / orig_height
            target_aspect = target_width / target_height

            # Calcular nuevo tamaño manteniendo aspect ratio
            # fill_completely = False muestra toda la imagen (puede tener bandas negras)
            # fill_completely = True llena el frame recortando (zoom)
            fill_completely = False  # Mostrar imagen completa sin recortar
            
            if fill_completely:
                # Llenar completamente el frame (crop si es necesario - zoom)
                if aspect_ratio > target_aspect:
                    # Imagen más ancha que el target: usar todo el alto, recortar lados
                    new_height = target_height
                    new_width = int(target_height * aspect_ratio)
                else:
                    # Imagen más alta que el target: usar todo el ancho, recortar arriba/abajo
                    new_width = target_width
                    new_height = int(target_width / aspect_ratio)
            else:
                # Mantener todo visible (puede tener bandas negras - letterbox)
                if aspect_ratio > target_aspect:
                    # Imagen más ancha, ajustar por ancho
                    new_width = target_width
                    new_height = int(target_width / aspect_ratio)
                else:
                    # Imagen más alta, ajustar por alto
                    new_height = target_height
                    new_width = int(target_height * aspect_ratio)

            # Asegurar dimensiones mínimas
            new_width = max(1, new_width)
            new_height = max(1, new_height)

            # Redimensionar
            clip = clip.resize(newsize=(new_width, new_height))

            # Si la imagen es más pequeña que el target, centrarla usando CompositeVideoClip
            if new_width < target_width or new_height < target_height:
                try:
                    from moviepy.video.VideoClip import ColorClip
                    import moviepy.editor as mpy
                    # Crear fondo negro del tamaño del target
                    bg = ColorClip(size=(target_width, target_height), color=(0, 0, 0), duration=clip.duration)
                    # Centrar la imagen
                    clip = mpy.CompositeVideoClip([bg, clip.set_position(('center', 'center'))])
                except Exception as center_error:
                    print(f"      ️ Error al centrar imagen: {center_error}, usando posición por defecto")
            elif new_width > target_width or new_height > target_height:
                # Si la imagen es más grande, recortar al centro
                x_center = (new_width - target_width) // 2 if new_width > target_width else 0
                y_center = (new_height - target_height) // 2 if new_height > target_height else 0
                clip = clip.crop(
                    x1=x_center,
                    y1=y_center,
                    x2=x_center + target_width,
                    y2=y_center + target_height
                )

            return clip

        except Exception as e:
            print(f"      ️ Error en resize inteligente: {e}, usando resize directo")
            # Fallback: resize directo (puede distorsionar ligeramente)
            return clip.resize(newsize=target_resolution)

    def assemble_video_from_prompts(self, prompts_data, audio_path, target_resolution, images_dir, apply_ken_burns=True, zoom_intensity=0.02, apply_cinematic=False, cinematic_preset='auto', transition_type=' Fade Suave', transition_duration=0.5, segments=None, extra_duration_override=None):
        if not MOVIEPY_AVAILABLE: 
            return None, None
            
        is_short = target_resolution[0] < target_resolution[1]
        apply_saturation = is_short

        # Verificar RAM disponible antes de aplicar efectos cinematográficos
        if apply_cinematic and segments and len(segments) > 0:
            num_segments = len(prompts_data)
            # Obtener duración del audio si es posible
            video_duration = 300  # Duración por defecto
            try:
                audio_temp = AudioFileClip(audio_path)
                video_duration = audio_temp.duration
                audio_temp.close()
            except:
                pass
            
            # Verificar para videos con segmentos o duración significativa
            # (Umbrales reducidos: antes era 30/300, pero videos de 46 seg / 230s
            # ya causan renderizado extremadamente lento con efectos)
            if num_segments >= 20 or video_duration >= 180:
                # Detectar RAM disponible
                try:
                    import psutil
                    mem = psutil.virtual_memory()
                    ram_available_gb = mem.available / (1024**3)
                    ram_total_gb = mem.total / (1024**3)
                    
                    # Estimar memoria necesaria
                    base_memory_per_clip_mb = 50 * 2  # Con efectos cinematográficos
                    clips_memory_gb = (num_segments * base_memory_per_clip_mb) / 1024
                    processing_overhead_gb = 0.5 + ((video_duration / 300) * 0.5 if video_duration > 300 else 0)
                    memory_required_gb = (clips_memory_gb + processing_overhead_gb) * 1.3
                    required_available_gb = memory_required_gb * 2
                    
                    print(f"\n    RAM disponible: {ram_available_gb:.1f} GB / {ram_total_gb:.1f} GB")
                    print(f"    RAM estimada necesaria (con efectos): {memory_required_gb:.1f} GB")
                    print(f"    RAM requerida disponible (mínimo): {required_available_gb:.1f} GB")
                    
                    if ram_available_gb < required_available_gb:
                        print(f"   ️ RAM insuficiente para efectos cinematográficos")
                        print(f"    Desactivando efectos cinematográficos automáticamente")
                        apply_cinematic = False
                except ImportError:
                    # Si psutil no está disponible, ser conservador
                    if num_segments >= 30 or video_duration >= 200:
                        print(f"\n   ️ No se pudo detectar RAM disponible. Para seguridad, desactivando efectos cinematográficos ({num_segments} segmentos, {video_duration:.0f}s)")
                        apply_cinematic = False

        # Inicializar motor de efectos cinematográficos
        cinematic_engine = None
        if apply_cinematic and CINEMATIC_AVAILABLE and segments:
            cinematic_engine = CinematicEffectsEngine(video_size=target_resolution)
            print(f"\n Efectos cinematográficos activados: {cinematic_preset}")
        
        print("\n" + "=" * 70)
        print(" ENSAMBLANDO CLIPS VISUALES (Modo Rastreador)")
        print("=" * 70)

        try:
            audio = AudioFileClip(audio_path)
            visual_clips = []
            clip_media_sources = []
            transitionable_mask = []
            
            for i, item in enumerate(prompts_data):
                # --- BUSCADOR INFALIBLE DE ARCHIVOS ---
                original_path = item.get('filename', '')
                target_name = os.path.basename(original_path)  # Ej: segment_001.jpg
                
                found_path = None
                
                # 1. Intento Directo (Ruta Absoluta)
                if os.path.exists(original_path):
                    found_path = original_path
                
                # 2. Intento Directo en Carpeta de Medios
                if not found_path:
                    p = os.path.join(str(images_dir), target_name)
                    if os.path.exists(p): 
                        found_path = p
                
                # 3. RASTREO PROFUNDO: Buscar en toda la carpeta 'auto_videos'
                if not found_path:
                    print(f"   ️ Rastreando '{target_name}' en el sistema...")
                    # Subimos hasta la raíz del proyecto para buscar
                    root_search = images_dir.parent.parent  # auto_videos
                    for root, dirs, files in os.walk(str(root_search)):
                        if target_name in files:
                            found_path = os.path.join(root, target_name)
                            print(f"       Encontrado en: {found_path}")
                            break
                
                if not found_path:
                    print(f"   ️ SALTO CRÍTICO: Imposible encontrar {target_name}")
                    continue
                # ---------------------------------------------

                # Crear Clip
                try:
                    clip = None
                    # Intentar cargar clip con manejo de errores de memoria
                    try:
                        if found_path.lower().endswith(('.mp4', '.mov', '.avi', '.webm', '.mkv')):
                            try:
                                dur = item.get('duration', 4)

                                # Pre-procesar video con FFmpeg para garantizar keyframes limpios
                                # y duración correcta (evita congelamiento por seek corrupto)
                                processed_path = self._preprocess_video_clip(found_path, dur, apply_saturation=apply_saturation)

                                if processed_path:
                                    clip = VideoFileClip(processed_path, audio=False)
                                    clip._temp_processed_path = processed_path
                                    print(f"       Video: {os.path.basename(found_path)} - Procesado a {clip.duration:.2f}s (requerido: {dur:.2f}s)")
                                else:
                                    # Fallback: cargar directamente con MoviePy
                                    clip = VideoFileClip(found_path, audio=False)
                                    print(f"       Video: {os.path.basename(found_path)} - Duración original: {clip.duration:.2f}s, Requerida: {dur:.2f}s")

                                    if clip.duration < dur:
                                        # Extender con freeze del último frame
                                        print(f"       Extendiendo video con freeze-frame ({clip.duration:.1f}s  {dur:.1f}s)")
                                        last_frame = clip.get_frame(clip.duration - 0.01)
                                        freeze_clip = self._create_image_clip_from_frame(last_frame, dur - clip.duration)
                                        clip = concatenate_videoclips([clip, freeze_clip])
                                    elif clip.duration > dur:
                                        clip = clip.subclip(0, dur)

                                # Redimensionar video para llenar pantalla completa
                                clip = self._resize_clip_to_fill(clip, target_resolution, found_path)
                            except Exception as video_error:
                                print(f"      ️ Error cargando video {os.path.basename(found_path)}: {video_error}")
                                # Fallback: crear clip negro con duración requerida
                                from moviepy.video.VideoClip import ColorClip
                                clip = ColorClip(size=target_resolution, color=(0, 0, 0), duration=item.get('duration', 4))
                                print(f"      ️ Usando placeholder negro para video fallido")
                        else:
                            clip = self._create_image_clip_from_path(found_path, item.get('duration', 4), apply_saturation=apply_saturation)
                            # Redimensionar imagen para llenar pantalla completa
                            clip = self._resize_clip_to_fill(clip, target_resolution, found_path)
                    except MemoryError as mem_error:
                        # Si hay error de memoria, intentar con resolución reducida
                        print(f"      ️ Error de memoria al cargar {os.path.basename(found_path)}, intentando con resolución reducida...")
                        import gc
                        gc.collect()
                        # Intentar reducir resolución antes de cargar
                        if found_path.lower().endswith(('.mp4', '.mov')):
                            # Para videos, cargar y luego reducir resolución
                            try:
                                clip = VideoFileClip(found_path)
                                # Reducir resolución a la mitad
                                clip = clip.resize(0.5)
                                dur = item.get('duration', 4)
                                if clip.duration < dur:
                                    # Usar FFmpeg para loop en caso de error de memoria
                                    print(f"       MemoryError: usando FFmpeg loop para video corto")
                                    try:
                                        import tempfile
                                        import subprocess
                                        temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4')
                                        os.close(temp_fd)
                                        loops_needed = int(dur / clip.duration) + 1
                                        cmd = [
                                            'ffmpeg', '-y',
                                            '-stream_loop', str(loops_needed),
                                            '-i', found_path,
                                            '-vf', 'scale=iw/2:ih/2',  # Reducir resolución
                                            '-c:v', 'libx264',
                                            '-preset', 'fast',
                                            '-t', str(dur),
                                            temp_path
                                        ]
                                        result = subprocess.run(cmd, capture_output=True, text=True)
                                        if result.returncode == 0:
                                            clip.close()
                                            clip = VideoFileClip(temp_path, audio=False)
                                            clip.temp_file_path = temp_path
                                        else:
                                            clip = clip.subclip(0, min(dur, clip.duration))
                                    except Exception:
                                        clip = clip.subclip(0, min(dur, clip.duration))
                                else: 
                                    clip = clip.subclip(0, dur)
                                # Volver a escalar a la resolución objetivo
                                clip = clip.resize(target_resolution)
                            except Exception as e2:
                                print(f"       Error crítico de memoria, saltando clip: {e2}")
                                continue
                        else:
                            # Para imágenes, cargar con PIL primero y reducir
                            try:
                                with Image.open(found_path) as img:
                                    # Reducir resolución a la mitad
                                    half_size = (img.width // 2, img.height // 2)
                                    img = img.resize(half_size, Image.LANCZOS)
                                    # Guardar temporalmente
                                    import tempfile
                                    temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
                                    os.close(temp_fd)
                                    img.convert('RGB').save(temp_path, 'JPEG', quality=85)
                                    clip = self._create_image_clip_from_path(temp_path, item.get('duration', 4), apply_saturation=apply_saturation)
                                    # Limpiar archivo temporal después
                                    import atexit
                                    atexit.register(lambda: os.remove(temp_path) if os.path.exists(temp_path) else None)
                                    clip = clip.resize(target_resolution)
                            except Exception as e2:
                                print(f"       Error crítico de memoria, saltando clip: {e2}")
                                continue
                        print(f"       Clip cargado con resolución reducida")
                        
                        # Resize al tamaño correcto con manejo robusto de proporciones y centrado
                        try:
                            # Obtener dimensiones originales usando PIL
                            with Image.open(found_path) as img:
                                # Convertir a RGB si es necesario (evita problemas de broadcasting)
                                if img.mode != 'RGB':
                                    img = img.convert('RGB')
                                orig_width, orig_height = img.size
                            
                            # Calcular proporción y redimensionar manteniendo aspect ratio
                            target_width, target_height = target_resolution[0], target_resolution[1]
                            aspect_ratio = orig_width / orig_height
                            target_aspect = target_width / target_height
                            
                            # MANTENER CALIDAD: Usar algoritmo LANCZOS para mejor escalado
                            # Calcular nuevo tamaño manteniendo aspect ratio
                            fill_completely = False  # Mostrar imagen completa sin recortar
                            
                            if fill_completely:
                                # Llenar completamente el frame (crop si es necesario)
                                if aspect_ratio > target_aspect:
                                    # Imagen más ancha, usar todo el alto y recortar lados
                                    new_height = target_height
                                    new_width = int(target_height * aspect_ratio)
                                else:
                                    # Imagen más alta, usar todo el ancho y recortar arriba/abajo
                                    new_width = target_width
                                    new_height = int(target_width / aspect_ratio)
                            else:
                                # Mantener todo visible (puede tener bandas negras)
                                if aspect_ratio > target_aspect:
                                    # Imagen más ancha, ajustar por ancho (crop vertical después)
                                    new_width = target_width
                                    new_height = int(target_width / aspect_ratio)
                                else:
                                    # Imagen más alta, ajustar por alto (crop horizontal después)
                                    new_height = target_height
                                    new_width = int(target_height * aspect_ratio)
                            
                            # Asegurar que las dimensiones no sean cero
                            new_width = max(1, new_width)
                            new_height = max(1, new_height)
                            
                            # Redimensionar con LANCZOS para máxima calidad
                            clip = clip.resize(newsize=(new_width, new_height))
                            
                            # Centrar la imagen si no llena completamente el frame
                            if new_width < target_width or new_height < target_height:
                                # Usar CompositeVideoClip para centrar
                                if MOVIEPY_AVAILABLE:
                                    try:
                                        # Importar ColorClip
                                        from moviepy.video.VideoClip import ColorClip
                                        bg = ColorClip(size=(target_width, target_height), color=(0, 0, 0), duration=clip.duration)
                                        # Usar CompositeVideoClip del módulo moviepy.editor
                                        import moviepy.editor as mpy
                                        clip = mpy.CompositeVideoClip([bg, clip.set_position(('center', 'center'))])
                                    except (ImportError, NameError, AttributeError) as comp_error:
                                        # Si CompositeVideoClip no está disponible, simplemente redimensionar
                                        print(f"      ️ CompositeVideoClip no disponible: {comp_error}, redimensionando directamente")
                                        clip = clip.resize(width=target_width, height=target_height)
                                else:
                                    # Si MoviePy no está disponible, simplemente redimensionar
                                    clip = clip.resize(width=target_width, height=target_height)
                            else:
                                # Si la imagen es más grande, recortar al centro
                                if new_width > target_width or new_height > target_height:
                                    x_center = (new_width - target_width) // 2 if new_width > target_width else 0
                                    y_center = (new_height - target_height) // 2 if new_height > target_height else 0
                                    clip = clip.crop(x_center=x_center, y_center=y_center, width=target_width, height=target_height)
                            
                        except Exception as resize_error:
                            # Fallback: redimensionar directamente (puede distorsionar pero funciona)
                            print(f"      ️ Error en resize inteligente: {resize_error}, usando resize directo")
                            try:
                                # Intentar convertir la imagen a RGB primero si es necesario
                                try:
                                    with Image.open(found_path) as img:
                                        if img.mode != 'RGB':
                                            # Guardar como RGB temporalmente
                                            import tempfile
                                            rgb_fd, rgb_path = tempfile.mkstemp(suffix='.jpg')
                                            os.close(rgb_fd)
                                            img.convert('RGB').save(rgb_path)
                                            found_path = rgb_path
                                    
                                    # Recrear el clip con la imagen RGB
                                    clip = self._create_image_clip_from_path(found_path, item.get('duration', 4), apply_saturation=apply_saturation)
                                except Exception as img_error:
                                    print(f"      ️ Error convirtiendo imagen: {img_error}")
                                
                                # Redimensionar directamente
                                clip = clip.resize(width=target_resolution[0], height=target_resolution[1])
                            except Exception as e2:
                                print(f"       Error crítico en resize: {e2}, saltando imagen")
                                continue
                        
                        # DESPUÉS aplicar efectos cinematográficos o Ken Burns
                        if cinematic_engine and segments and i < len(segments):
                            # Detectar contexto del segmento
                            segment_text = segments[i].get('narration_text', '')
                            duration = item.get('duration', 4)
                            
                            print(f"    Segmento {i+1}: Aplicando efectos cinematográficos...")
                            
                            # Aplicar efectos según preset
                            clip = cinematic_engine.apply_effects_to_segment(
                                clip, 
                                segment_text=segment_text,
                                duration=duration,
                                auto_detect=True
                            )
                        elif apply_ken_burns:
                            clip = clip.resize(lambda t: 1 + zoom_intensity * t)
                    
                    # Ya no necesitamos resize aquí porque se hizo arriba
                    clip = clip.set_start(item['timestamp_start'])
                    
                    if clip.end > audio.duration: 
                        clip = clip.set_duration(audio.duration - clip.start)
                    
                    visual_clips.append(clip)
                    clip_media_sources.append(self._normalize_media_source_key(found_path))
                    transitionable_mask.append(True)
                    
                    # Overlay
                    if item.get('overlay_filename'):
                        ov_name = os.path.basename(item['overlay_filename'])
                        ov_path = os.path.join(str(images_dir), ov_name)
                        if os.path.exists(ov_path):
                            ov_clip = VideoFileClip(ov_path, has_mask=True).resize(height=200).set_position(('right','top'))
                            ov_clip = ov_clip.set_start(item['timestamp_start']).set_duration(item['duration'])
                            visual_clips.append(ov_clip)
                            clip_media_sources.append(None)
                            transitionable_mask.append(False)
                    
                    # Liberar memoria periódicamente para videos largos
                    if (i + 1) % 10 == 0:  # Cada 10 clips
                        import gc
                        gc.collect()

                except Exception as e:
                    print(f"       Error cargando clip {found_path}: {e}")
                    # Intentar liberar memoria si es posible
                    import gc
                    gc.collect()

            if not visual_clips:
                print(" No se generaron clips válidos.")
                return None, None
            
            # Asegurar que CompositeVideoClip esté disponible
            if not MOVIEPY_AVAILABLE:
                print(" MoviePy no está disponible")
                return None, None
            
            # Aplicar transiciones profesionales entre clips (tipo CapCut)
            # Decidir si omitir fades en transiciones para ahorrar memoria
            skip_transition_fades = False
            if len(visual_clips) >= 50 or audio.duration > 300:
                skip_transition_fades = True
                if len(visual_clips) >= 50:
                    print(f"   ℹ️ Muchos clips ({len(visual_clips)}), omitiendo fades en transiciones para ahorrar memoria")
                if audio.duration > 300:
                    print(f"   ℹ️ Video largo ({audio.duration:.1f}s), omitiendo fades en transiciones para ahorrar memoria")
            
            if not self._is_no_transition(transition_type) and len(visual_clips) > 1:
                print(f"\n Aplicando transiciones: {transition_type} ({transition_duration}s)")
                visual_clips = self._apply_transitions(
                    visual_clips,
                    transition_type,
                    transition_duration,
                    target_resolution,
                    skip_fades=skip_transition_fades,
                    media_sources=clip_media_sources,
                    transitionable_mask=transitionable_mask,
                )
            
            try:
                # Configuración de fade in/out
                fade_in_duration = 1.0  # Duración del fade in en segundos
                fade_out_duration = 3.0  # Duración del fade out en segundos
                # Si extra_duration_override es proporcionado, usar ese valor
                # (0 cuando el audio ya viene con el outro integrado desde el generador)
                extra_duration = extra_duration_override if extra_duration_override is not None else 3.0
                total_duration = audio.duration + extra_duration
                narration_end = audio.duration  # Momento donde termina la narración
                
                # Extender el último clip visual para cubrir el tiempo adicional
                if visual_clips:
                    last_clip = visual_clips[-1]
                    # Extender el último clip para cubrir todo el tiempo adicional
                    extended_last_clip = last_clip.set_duration(total_duration - last_clip.start)
                    visual_clips[-1] = extended_last_clip
                
                # Decidir si aplicar fades en video basado en la duración y número de clips
                # Los fades en video pueden causar problemas de memoria con videos largos o muchos clips
                apply_video_fades = False
                if total_duration <= 300 and len(visual_clips) < 50:
                    # Solo aplicar fades en video si el video no es muy largo y no hay demasiados clips
                    apply_video_fades = True
                else:
                    if total_duration > 300:
                        print(f"   ℹ️ Video largo ({total_duration:.1f}s), omitiendo fades en video para ahorrar memoria")
                    if len(visual_clips) >= 50:
                        print(f"   ℹ️ Muchos clips ({len(visual_clips)}), omitiendo fades en video para ahorrar memoria")
                    print("   ℹ️ Los fades se mantienen en el audio")
                
                # Aplicar fade in al primer clip y fade out al último clip ANTES de crear el CompositeVideoClip
                # Esto es más eficiente en memoria que aplicar fades al CompositeVideoClip completo
                if apply_video_fades and visual_clips and len(visual_clips) > 0:
                    try:
                        # Aplicar fade in solo al primer clip
                        if visual_clips[0].duration > fade_in_duration:
                            visual_clips[0] = visual_clips[0].fadein(fade_in_duration)
                        
                        # Aplicar fade out solo al último clip
                        if visual_clips[-1].duration > fade_out_duration:
                            visual_clips[-1] = visual_clips[-1].fadeout(fade_out_duration)
                    except Exception as fade_error:
                        # Si hay error aplicando fades a clips individuales, continuar sin fades
                        print(f"   ️ Error aplicando fades a clips individuales: {fade_error}")
                        print("   ℹ️ Continuando sin fade in/out en video (se mantienen en audio)")
                
                # Crear video final con duración extendida
                # Intentar liberar memoria antes de crear el CompositeVideoClip
                import gc
                gc.collect()
                
                try:
                    final_video = CompositeVideoClip(visual_clips, size=target_resolution).set_duration(total_duration)
                except MemoryError as mem_err:
                    print(f"    Error de memoria al crear CompositeVideoClip: {mem_err}")
                    print(f"   ️ Intentando liberar memoria y reducir resolución temporalmente...")
                    gc.collect()
                    # Intentar con resolución reducida como último recurso
                    try:
                        # Reducir resolución a la mitad temporalmente
                        reduced_resolution = (target_resolution[0] // 2, target_resolution[1] // 2)
                        print(f"   ️ Intentando con resolución reducida: {reduced_resolution}")
                        final_video = CompositeVideoClip(visual_clips, size=reduced_resolution).set_duration(total_duration)
                        # Escalar de vuelta a la resolución objetivo
                        final_video = final_video.resize(target_resolution)
                        print(f"    Video creado con resolución reducida y escalado")
                    except Exception as e2:
                        print(f"    Error crítico: No se pudo crear el video incluso con resolución reducida: {e2}")
                        raise
                
                # Procesar audio: aplicar fade in y fade out
                # 1. Aplicar fade in al inicio del audio
                try:
                    audio_with_fadein = audio.fx(vfx.audio_fadein, fade_in_duration)
                except (AttributeError, NameError):
                    # Si audio_fadein no está disponible, usar solo el audio original
                    print("   ℹ️ audio_fadein no disponible, usando audio sin fade in")
                    audio_with_fadein = audio
                
                # 2. Aplicar fade out al audio (comienza fade_out_duration segundos antes del final de la narración)
                # El fade out debe comenzar cuando la narración está por terminar
                audio_with_fade = audio_with_fadein.fx(vfx.audio_fadeout, fade_out_duration)
                
                # 3. Repetir el audio si el video es más largo, con fade in/out entre repeticiones
                if total_duration > audio.duration:
                    # Calcular cuántas repeticiones completas necesitamos
                    # Cada repetición tendrá fade in (1s) + contenido + fade out (2s)
                    audio_base_duration = audio.duration
                    repetitions_needed = int(total_duration / audio_base_duration) + 1
                    
                    # Crear lista de clips de audio con fade in/out entre repeticiones
                    audio_clips = []
                    current_time = 0.0
                    
                    for i in range(repetitions_needed):
                        # Calcular cuánto tiempo queda
                        remaining_time = total_duration - current_time
                        
                        if remaining_time <= 0:
                            break
                        
                        # Para cada repetición, aplicar fade in y fade out
                        # Primera repetición ya tiene los fades aplicados
                        if i == 0:
                            audio_clips.append(audio_with_fade)
                            current_time += audio_base_duration
                        else:
                            # Repeticiones siguientes: crear nueva copia del audio original y aplicar fades
                            # Aplicar fade in al inicio
                            try:
                                audio_copy_with_fadein = audio.fx(vfx.audio_fadein, fade_in_duration)
                            except (AttributeError, NameError):
                                audio_copy_with_fadein = audio
                            
                            # Si esta es la última repetición y no necesitamos todo el audio, recortar
                            if remaining_time < audio_base_duration:
                                # Recortar el audio a lo que necesitamos
                                audio_copy_with_fadein = audio_copy_with_fadein.subclip(0, remaining_time)
                                # Aplicar fade out al final si hay suficiente tiempo
                                if remaining_time > fade_out_duration:
                                    audio_copy_with_fadein = audio_copy_with_fadein.fx(vfx.audio_fadeout, fade_out_duration)
                            else:
                                # Aplicar fade out al final
                                audio_copy_with_fadein = audio_copy_with_fadein.fx(vfx.audio_fadeout, fade_out_duration)
                            
                            audio_clips.append(audio_copy_with_fadein)
                            current_time += audio_copy_with_fadein.duration
                    
                    # Concatenar todas las repeticiones
                    if len(audio_clips) > 1:
                        extended_audio = concatenate_audioclips(audio_clips)
                    else:
                        extended_audio = audio_clips[0] if audio_clips else audio_with_fade
                    
                    # Asegurar que la duración sea exactamente total_duration
                    if extended_audio.duration > total_duration:
                        extended_audio = extended_audio.subclip(0, total_duration)
                    elif extended_audio.duration < total_duration:
                        # Si aún falta tiempo (poco probable), agregar silencio al final
                        remaining_time = total_duration - extended_audio.duration
                        if remaining_time > 0.1:  # Solo si falta más de 0.1 segundos
                            silence = AudioClip(lambda t: np.zeros((1,)), duration=remaining_time, fps=audio.fps)
                            extended_audio = concatenate_audioclips([extended_audio, silence])
                else:
                    # Si el video no es más largo, usar el audio con fade in/out y extender con silencio si es necesario
                    silence_duration = extra_duration
                    if silence_duration > 0:
                        # Crear clip de silencio
                        silence = AudioClip(lambda t: np.zeros((1,)), duration=silence_duration, fps=audio.fps)
                        # Concatenar audio original con fade in/out + silencio
                        extended_audio = concatenate_audioclips([audio_with_fade, silence])
                    else:
                        extended_audio = audio_with_fade.set_duration(total_duration)
                
                return final_video, extended_audio
            except NameError:
                # Si CompositeVideoClip no está disponible, intentar importarlo
                try:
                    from moviepy.editor import CompositeVideoClip
                    # Configuración de fade in/out
                    fade_in_duration = 1.0  # Duración del fade in en segundos
                    fade_out_duration = 2.0  # Duración del fade out en segundos
                    extra_duration = extra_duration_override if extra_duration_override is not None else 3.0
                    total_duration = audio.duration + extra_duration
                    
                    # Extender el último clip visual para cubrir el tiempo adicional
                    if visual_clips:
                        last_clip = visual_clips[-1]
                        # Extender el último clip para cubrir todo el tiempo adicional
                        extended_last_clip = last_clip.set_duration(total_duration - last_clip.start)
                        visual_clips[-1] = extended_last_clip
                    
                    # Decidir si aplicar fades en video basado en la duración y número de clips
                    # Los fades en video pueden causar problemas de memoria con videos largos o muchos clips
                    apply_video_fades = False
                    if total_duration <= 300 and len(visual_clips) < 50:
                        # Solo aplicar fades en video si el video no es muy largo y no hay demasiados clips
                        apply_video_fades = True
                    else:
                        if total_duration > 300:
                            print(f"   ℹ️ Video largo ({total_duration:.1f}s), omitiendo fades en video para ahorrar memoria")
                        if len(visual_clips) >= 50:
                            print(f"   ℹ️ Muchos clips ({len(visual_clips)}), omitiendo fades en video para ahorrar memoria")
                        print("   ℹ️ Los fades se mantienen en el audio")
                    
                    # Aplicar fade in al primer clip y fade out al último clip ANTES de crear el CompositeVideoClip
                    # Esto es más eficiente en memoria que aplicar fades al CompositeVideoClip completo
                    if apply_video_fades and visual_clips and len(visual_clips) > 0:
                        try:
                            # Aplicar fade in solo al primer clip
                            if visual_clips[0].duration > fade_in_duration:
                                visual_clips[0] = visual_clips[0].fadein(fade_in_duration)
                            
                            # Aplicar fade out solo al último clip
                            if visual_clips[-1].duration > fade_out_duration:
                                visual_clips[-1] = visual_clips[-1].fadeout(fade_out_duration)
                        except Exception as fade_error:
                            # Si hay error aplicando fades a clips individuales, continuar sin fades
                            print(f"   ️ Error aplicando fades a clips individuales: {fade_error}")
                            print("   ℹ️ Continuando sin fade in/out en video (se mantienen en audio)")
                    
                    # Crear video final con duración extendida
                    # Intentar liberar memoria antes de crear el CompositeVideoClip
                    import gc
                    gc.collect()
                    
                    try:
                        final_video = CompositeVideoClip(visual_clips, size=target_resolution).set_duration(total_duration)
                    except (MemoryError, Exception) as mem_err:
                        # Capturar cualquier error relacionado con memoria
                        error_str = str(mem_err).lower()
                        if "unable to allocate" in error_str or "memory" in error_str:
                            print(f"    Error de memoria al crear CompositeVideoClip: {mem_err}")
                            print(f"   ️ El sistema no tiene suficiente memoria para procesar {len(visual_clips)} clips")
                            print(f"    Intenta reducir el número de segmentos o desactivar efectos cinematográficos")
                            raise
                        else:
                            raise
                    
                    # Procesar audio: aplicar fade in y fade out
                    try:
                        audio_with_fadein = audio.fx(vfx.audio_fadein, fade_in_duration)
                    except (AttributeError, NameError):
                        # Si audio_fadein no está disponible, usar solo el audio original
                        print("   ℹ️ audio_fadein no disponible, usando audio sin fade in")
                        audio_with_fadein = audio
                    
                    audio_with_fade = audio_with_fadein.fx(vfx.audio_fadeout, fade_out_duration)
                    
                    # Repetir el audio si el video es más largo, con fade in/out entre repeticiones
                    if total_duration > audio.duration:
                        # Calcular cuántas repeticiones completas necesitamos
                        audio_base_duration = audio.duration
                        repetitions_needed = int(total_duration / audio_base_duration) + 1
                        
                        # Crear lista de clips de audio con fade in/out entre repeticiones
                        audio_clips = []
                        current_time = 0.0
                        
                        for i in range(repetitions_needed):
                            # Calcular cuánto tiempo queda
                            remaining_time = total_duration - current_time
                            
                            if remaining_time <= 0:
                                break
                            
                            # Para cada repetición, aplicar fade in y fade out
                            if i == 0:
                                audio_clips.append(audio_with_fade)
                                current_time += audio_base_duration
                            else:
                                # Repeticiones siguientes: crear nueva copia del audio original y aplicar fades
                                try:
                                    audio_copy_with_fadein = audio.fx(vfx.audio_fadein, fade_in_duration)
                                except (AttributeError, NameError):
                                    audio_copy_with_fadein = audio
                                
                                # Si esta es la última repetición y no necesitamos todo el audio, recortar
                                if remaining_time < audio_base_duration:
                                    audio_copy_with_fadein = audio_copy_with_fadein.subclip(0, remaining_time)
                                    if remaining_time > fade_out_duration:
                                        audio_copy_with_fadein = audio_copy_with_fadein.fx(vfx.audio_fadeout, fade_out_duration)
                                else:
                                    audio_copy_with_fadein = audio_copy_with_fadein.fx(vfx.audio_fadeout, fade_out_duration)
                                
                                audio_clips.append(audio_copy_with_fadein)
                                current_time += audio_copy_with_fadein.duration
                        
                        # Concatenar todas las repeticiones
                        if len(audio_clips) > 1:
                            extended_audio = concatenate_audioclips(audio_clips)
                        else:
                            extended_audio = audio_clips[0] if audio_clips else audio_with_fade
                        
                        # Asegurar que la duración sea exactamente total_duration
                        if extended_audio.duration > total_duration:
                            extended_audio = extended_audio.subclip(0, total_duration)
                        elif extended_audio.duration < total_duration:
                            remaining_time = total_duration - extended_audio.duration
                            if remaining_time > 0.1:
                                silence = AudioClip(lambda t: np.zeros((1,)), duration=remaining_time, fps=audio.fps)
                                extended_audio = concatenate_audioclips([extended_audio, silence])
                    else:
                        # Si el video no es más largo, usar el audio con fade in/out y extender con silencio si es necesario
                        silence_duration = extra_duration
                        if silence_duration > 0:
                            silence = AudioClip(lambda t: np.zeros((1,)), duration=silence_duration, fps=audio.fps)
                            extended_audio = concatenate_audioclips([audio_with_fade, silence])
                        else:
                            extended_audio = audio_with_fade.set_duration(total_duration)
                    
                    return final_video, extended_audio
                except Exception as e:
                    print(f" Error creando CompositeVideoClip: {e}")
                    return None, None
            
        except Exception as e:
            print(f" Error crítico ensamblaje: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def _normalize_media_source_key(self, media_path: Optional[str]) -> Optional[str]:
        """Normaliza una ruta para comparar si dos escenas usan el mismo recurso visual."""
        if not media_path:
            return None
        try:
            return os.path.normcase(os.path.abspath(str(media_path)))
        except Exception:
            value = str(media_path).strip()
            return value.lower() if value else None

    def _should_transition_between_sources(
        self,
        media_sources: List[Optional[str]],
        left_idx: int,
        right_idx: int,
    ) -> bool:
        """True solo cuando las dos escenas tienen fuente distinta y válida."""
        if not isinstance(media_sources, list):
            return False
        if left_idx < 0 or right_idx < 0:
            return False
        if left_idx >= len(media_sources) or right_idx >= len(media_sources):
            return False

        left_source = media_sources[left_idx]
        right_source = media_sources[right_idx]
        if not left_source or not right_source:
            return False
        return left_source != right_source

    def _resolve_transition_permissions(
        self,
        clips,
        media_sources: Optional[List[Optional[str]]] = None,
        transitionable_mask: Optional[List[bool]] = None,
    ) -> List[Tuple[bool, bool]]:
        """
        Para cada clip retorna (apply_in, apply_out), aplicando transición
        solo entre escenas visuales diferentes.
        """
        total = len(clips)
        if total == 0:
            return []

        if not isinstance(media_sources, list) or len(media_sources) != total:
            # Compatibilidad: sin metadata de fuentes, asumir que cada clip es distinto.
            media_sources = [f"__clip_{idx}__" for idx in range(total)]
        if not isinstance(transitionable_mask, list) or len(transitionable_mask) != total:
            transitionable_mask = [True] * total

        permissions: List[Tuple[bool, bool]] = [(False, False) for _ in range(total)]
        scene_indices = [idx for idx, enabled in enumerate(transitionable_mask) if enabled]
        if len(scene_indices) <= 1:
            return permissions

        for pos, idx in enumerate(scene_indices):
            apply_in = False
            apply_out = False

            if pos > 0:
                prev_idx = scene_indices[pos - 1]
                apply_in = self._should_transition_between_sources(media_sources, prev_idx, idx)
            if pos < len(scene_indices) - 1:
                next_idx = scene_indices[pos + 1]
                apply_out = self._should_transition_between_sources(media_sources, idx, next_idx)

            permissions[idx] = (apply_in, apply_out)

        return permissions

    def _apply_transitions(
        self,
        clips,
        transition_type,
        duration,
        target_resolution,
        skip_fades=False,
        media_sources: Optional[List[Optional[str]]] = None,
        transitionable_mask: Optional[List[bool]] = None,
    ):
        """
        Aplica transiciones profesionales entre clips.
        Solo aplica transición cuando cambia la fuente visual entre escenas.
        """
        if len(clips) <= 1:
            return clips

        transition_name = self._normalize_transition_name(transition_type)
        print(f"    Aplicando {transition_name} entre {len(clips)} clips...")

        permissions = self._resolve_transition_permissions(clips, media_sources, transitionable_mask)
        transition_count = sum(1 for can_in, can_out in permissions if can_in)  # una entrada por cambio de escena
        if transition_count == 0:
            print("   ℹ️ No se aplican transiciones: escenas consecutivas usan el mismo recurso visual.")
        else:
            try:
                print(f"   ℹ️ Transiciones efectivas por cambio de escena: {transition_count}")
            except UnicodeEncodeError:
                print(f"   [INFO] Transiciones efectivas por cambio de escena: {transition_count}")

        if self._is_overlay_transition(transition_name):
            return self._apply_overlay_transitions(
                clips,
                duration,
                target_resolution,
                media_sources=media_sources,
                transitionable_mask=transitionable_mask,
            )

        if self._is_glitch_transition(transition_name):
            return self._apply_glitch_transitions(
                clips,
                transition_name,
                duration,
                target_resolution,
                skip_fades,
                media_sources=media_sources,
                transitionable_mask=transitionable_mask,
            )

        return self._apply_standard_transitions(
            clips,
            transition_name,
            duration,
            target_resolution,
            skip_fades,
            media_sources=media_sources,
            transitionable_mask=transitionable_mask,
        )
    
    def _apply_transition_in(self, clip, transition_type, duration, target_resolution, skip_fades=False):
        """Aplica transición de entrada a un clip"""
        try:
            if skip_fades:
                # Si se omiten fades, usar transición simple sin fadein
                return clip
            
            if "Fade" in transition_type or "fade" in transition_type.lower():
                return clip.fadein(duration)
            
            elif "Crossfade" in transition_type or "crossfade" in transition_type.lower():
                return clip.fadein(duration)
            
            elif "Zoom" in transition_type or "zoom" in transition_type.lower():
                # Zoom in: empezar pequeño y crecer
                def zoom_effect(get_frame, t):
                    if t < duration:
                        scale = 0.85 + (0.15 * (t / duration))  # De 0.85 a 1.0
                        frame = get_frame(t)
                        h, w = frame.shape[:2]
                        new_h, new_w = int(h * scale), int(w * scale)
                        # Convertir frame float64 a uint8 si es necesario
                        if frame.dtype != np.uint8:
                            if frame.max() <= 1.0:
                                frame = (frame * 255).astype(np.uint8)
                            else:
                                frame = frame.astype(np.uint8)
                        img = Image.fromarray(frame)
                        img = img.resize((new_w, new_h), Image.LANCZOS)
                        new_frame = np.array(img)
                        # Centrar
                        y_offset = (h - new_h) // 2
                        x_offset = (w - new_w) // 2
                        result = np.zeros((h, w, 3), dtype=np.uint8)
                        result[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = new_frame
                        # Fade in simultáneo
                        alpha = t / duration
                        result = (result * alpha).astype(np.uint8)
                        return result
                    return get_frame(t)
                return clip.fl(zoom_effect, apply_to=['video'])
            
            elif "Slide" in transition_type or "slide" in transition_type.lower():
                # Slide desde la derecha
                def slide_effect(get_frame, t):
                    if t < duration:
                        progress = t / duration
                        x_offset = int(target_resolution[0] * (1 - progress))
                        frame = get_frame(t)
                        # Normalizar frame float64 a uint8
                        if frame.dtype != np.uint8:
                            if frame.max() <= 1.0:
                                frame = (frame * 255).astype(np.uint8)
                            else:
                                frame = np.clip(frame, 0, 255).astype(np.uint8)
                        h, w = frame.shape[:2]
                        result = np.zeros((h, w, 3), dtype=np.uint8)
                        if x_offset < w:
                            result[:, x_offset:] = frame[:, :w-x_offset]
                        # Fade in simultáneo
                        alpha = progress
                        result = (result * alpha).astype(np.uint8)
                        return result
                    return get_frame(t)
                return clip.fl(slide_effect, apply_to=['video'])

            elif "Blur" in transition_type or "blur" in transition_type.lower():
                # Blur que se desvanece
                def blur_fade(get_frame, t):
                    if t < duration:
                        alpha = t / duration
                        frame = get_frame(t)
                        # Normalizar frame float64 a uint8
                        if frame.dtype != np.uint8:
                            if frame.max() <= 1.0:
                                frame = (frame * 255).astype(np.uint8)
                            else:
                                frame = np.clip(frame, 0, 255).astype(np.uint8)
                        return (frame * alpha).astype(np.uint8)
                    return get_frame(t)
                if skip_fades:
                    return clip.fl(blur_fade, apply_to=['video'])
                return clip.fl(blur_fade, apply_to=['video']).fadein(duration)
            
            elif "Dissolve" in transition_type or "dissolve" in transition_type.lower():
                if skip_fades:
                    return clip
                return clip.fadein(duration)
            
            elif "Wipe" in transition_type or "wipe" in transition_type.lower():
                # Wipe desde la izquierda
                def wipe_effect(get_frame, t):
                    if t < duration:
                        progress = t / duration
                        wipe_x = int(target_resolution[0] * progress)
                        frame = get_frame(t)
                        # Normalizar frame float64 a uint8
                        if frame.dtype != np.uint8:
                            if frame.max() <= 1.0:
                                frame = (frame * 255).astype(np.uint8)
                            else:
                                frame = np.clip(frame, 0, 255).astype(np.uint8)
                        h, w = frame.shape[:2]
                        result = np.zeros((h, w, 3), dtype=np.uint8)
                        result[:, :wipe_x] = frame[:, :wipe_x]
                        return result
                    return get_frame(t)
                return clip.fl(wipe_effect, apply_to=['video'])

            # Por defecto: fade suave
            if skip_fades:
                return clip
            return clip.fadein(duration)
            
        except Exception as e:
            print(f"   ️ Error en transición de entrada: {e}. Usando clip sin transición.")
            return clip
    
    def _apply_transition_out(self, clip, transition_type, duration, target_resolution, skip_fades=False):
        """Aplica transición de salida a un clip"""
        try:
            if skip_fades:
                # Si se omiten fades, usar transición simple sin fadeout
                return clip
            
            if "Fade" in transition_type or "fade" in transition_type.lower():
                return clip.fadeout(duration)
            
            elif "Crossfade" in transition_type or "crossfade" in transition_type.lower():
                return clip.fadeout(duration)
            
            elif "Zoom" in transition_type or "zoom" in transition_type.lower():
                # Zoom out: empezar normal y alejarse
                def zoom_effect(get_frame, t):
                    clip_duration = clip.duration
                    if t > clip_duration - duration:
                        elapsed = t - (clip_duration - duration)
                        scale = 1.0 - (0.15 * (elapsed / duration))  # De 1.0 a 0.85
                        frame = get_frame(t)
                        h, w = frame.shape[:2]
                        new_h, new_w = int(h * scale), int(w * scale)
                        # Convertir frame float64 a uint8 si es necesario
                        if frame.dtype != np.uint8:
                            if frame.max() <= 1.0:
                                frame = (frame * 255).astype(np.uint8)
                            else:
                                frame = frame.astype(np.uint8)
                        img = Image.fromarray(frame)
                        img = img.resize((new_w, new_h), Image.LANCZOS)
                        new_frame = np.array(img)
                        # Centrar
                        y_offset = (h - new_h) // 2
                        x_offset = (w - new_w) // 2
                        result = np.zeros((h, w, 3), dtype=np.uint8)
                        result[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = new_frame
                        # Fade out simultáneo
                        alpha = 1.0 - (elapsed / duration)
                        result = (result * alpha).astype(np.uint8)
                        return result
                    return get_frame(t)
                return clip.fl(zoom_effect, apply_to=['video'])
            
            elif "Slide" in transition_type or "slide" in transition_type.lower():
                # Slide hacia la izquierda
                def slide_effect(get_frame, t):
                    clip_duration = clip.duration
                    if t > clip_duration - duration:
                        elapsed = t - (clip_duration - duration)
                        progress = elapsed / duration
                        x_offset = int(target_resolution[0] * progress)
                        frame = get_frame(t)
                        # Normalizar frame float64 a uint8
                        if frame.dtype != np.uint8:
                            if frame.max() <= 1.0:
                                frame = (frame * 255).astype(np.uint8)
                            else:
                                frame = np.clip(frame, 0, 255).astype(np.uint8)
                        h, w = frame.shape[:2]
                        result = np.zeros((h, w, 3), dtype=np.uint8)
                        if x_offset < w:
                            result[:, :w-x_offset] = frame[:, x_offset:]
                        # Fade out simultáneo
                        alpha = 1.0 - progress
                        result = (result * alpha).astype(np.uint8)
                        return result
                    return get_frame(t)
                return clip.fl(slide_effect, apply_to=['video'])

            elif "Blur" in transition_type or "blur" in transition_type.lower():
                # Blur que aumenta
                def blur_fade(get_frame, t):
                    clip_duration = clip.duration
                    if t > clip_duration - duration:
                        elapsed = t - (clip_duration - duration)
                        alpha = 1.0 - (elapsed / duration)
                        frame = get_frame(t)
                        # Normalizar frame float64 a uint8
                        if frame.dtype != np.uint8:
                            if frame.max() <= 1.0:
                                frame = (frame * 255).astype(np.uint8)
                            else:
                                frame = np.clip(frame, 0, 255).astype(np.uint8)
                        return (frame * alpha).astype(np.uint8)
                    return get_frame(t)
                return clip.fl(blur_fade, apply_to=['video'])

            elif "Dissolve" in transition_type or "dissolve" in transition_type.lower():
                if skip_fades:
                    return clip
                return clip.fadeout(duration)
            
            elif "Wipe" in transition_type or "wipe" in transition_type.lower():
                # Wipe hacia la derecha
                def wipe_effect(get_frame, t):
                    clip_duration = clip.duration
                    if t > clip_duration - duration:
                        elapsed = t - (clip_duration - duration)
                        progress = elapsed / duration
                        wipe_x = int(target_resolution[0] * (1 - progress))
                        frame = get_frame(t)
                        # Normalizar frame float64 a uint8
                        if frame.dtype != np.uint8:
                            if frame.max() <= 1.0:
                                frame = (frame * 255).astype(np.uint8)
                            else:
                                frame = np.clip(frame, 0, 255).astype(np.uint8)
                        h, w = frame.shape[:2]
                        result = np.zeros((h, w, 3), dtype=np.uint8)
                        result[:, :wipe_x] = frame[:, :wipe_x]
                        return result
                    return get_frame(t)
                return clip.fl(wipe_effect, apply_to=['video'])
            
            # Por defecto: fade suave
            if skip_fades:
                return clip
            return clip.fadeout(duration)
            
        except Exception as e:
            print(f"   ️ Error en transición de salida: {e}. Usando clip sin transición.")
            return clip
    
    # ------------------------------------------------------------------ #
    #  Transiciones de overlay con clip de video (film burn / light leak) #
    # ------------------------------------------------------------------ #

    _OVERLAY_TRANSITION_KEYWORDS = ("film burn", "light leak", "overlay")

    def _is_overlay_transition(self, transition_name: str) -> bool:
        """True si la transicion es de tipo overlay con clip de video."""
        name_lower = transition_name.lower()
        return any(kw in name_lower for kw in self._OVERLAY_TRANSITION_KEYWORDS)

    def _get_overlay_clip_path(self) -> Optional[str]:
        """Busca el primer clip de transicion overlay disponible en transition_overlays/."""
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transition_overlays")
        if not os.path.isdir(base):
            return None
        for fname in sorted(os.listdir(base)):
            if fname.lower().endswith((".mp4", ".mov", ".webm")):
                return os.path.join(base, fname)
        return None

    def _apply_overlay_transitions(
        self,
        clips,
        duration: float,
        target_resolution: Tuple[int, int],
        media_sources: Optional[List[Optional[str]]] = None,
        transitionable_mask: Optional[List[bool]] = None,
    ):
        """
        Superpone un clip de video (film burn) en cada cambio de escena.
        El clip se escala a target_resolution y se mezcla con modo 'screen'
        (negro = transparente, colores = visibles).
        Funciona con cualquier aspect ratio (16:9, 9:16, 1:1).
        """
        overlay_path = self._get_overlay_clip_path()
        if not overlay_path:
            print("   [WARN] No se encontro clip en transition_overlays/. Usando fade como fallback.")
            return self._apply_standard_transitions(
                clips, "Fade", duration, target_resolution,
                media_sources=media_sources, transitionable_mask=transitionable_mask,
            )

        permissions = self._resolve_transition_permissions(
            clips, media_sources=media_sources, transitionable_mask=transitionable_mask,
        )

        # Buscar los indices donde se necesita transicion (cambio de escena)
        transition_boundaries = []
        for i, (apply_in, apply_out) in enumerate(permissions):
            if apply_in and i > 0:
                transition_boundaries.append(i)

        if not transition_boundaries:
            print("   [INFO] Sin cambios de escena para overlay transition.")
            return clips

        # Cargar el clip overlay y acelerarlo para que dure ~duration
        try:
            overlay_raw = VideoFileClip(overlay_path)
            w_target, h_target = target_resolution
            overlay_resized = overlay_raw.resize((w_target, h_target))
            orig_duration = overlay_resized.duration
            # Acelerar el clip para que dure exactamente 'duration' (el spinner de la UI)
            target_ovr_dur = max(0.15, min(duration, 1.0))
            if orig_duration > target_ovr_dur:
                speed_factor = orig_duration / target_ovr_dur
                overlay_fast = overlay_resized.fl_time(
                    lambda t: t * speed_factor, apply_to=['video']
                ).set_duration(target_ovr_dur)
            else:
                overlay_fast = overlay_resized
                target_ovr_dur = orig_duration
            print(
                f"   Film Burn overlay: {os.path.basename(overlay_path)} "
                f"{orig_duration:.2f}s -> {target_ovr_dur:.2f}s "
                f"(x{orig_duration/target_ovr_dur:.1f}) a {w_target}x{h_target}"
            )
        except Exception as exc:
            print(f"   [WARN] Error cargando overlay clip: {exc}. Fallback a fade.")
            return self._apply_standard_transitions(
                clips, "Fade", duration, target_resolution,
                media_sources=media_sources, transitionable_mask=transitionable_mask,
            )

        # Crear funcion de blending screen: result = 1 - (1 - base) * (1 - overlay)
        def make_screen_blend(base_clip, ovr_clip, ovr_dur, t_start):
            """Retorna un clip que aplica screen blend del overlay sobre el base."""

            def blend_frame(get_frame, t):
                frame = get_frame(t)
                ovr_t = t - t_start
                if ovr_t < 0 or ovr_t >= ovr_dur:
                    return frame
                try:
                    ovr_frame = ovr_clip.get_frame(ovr_t)
                    # Asegurar mismas dimensiones
                    if ovr_frame.shape[:2] != frame.shape[:2]:
                        from PIL import Image as _PILImage
                        ovr_pil = _PILImage.fromarray(ovr_frame)
                        ovr_pil = ovr_pil.resize((frame.shape[1], frame.shape[0]), _PILImage.LANCZOS)
                        ovr_frame = np.array(ovr_pil)
                    # Screen blend: 1 - (1-a)*(1-b) en rango 0-255
                    a = frame.astype(np.float32) / 255.0
                    b = ovr_frame.astype(np.float32) / 255.0
                    result = 1.0 - (1.0 - a) * (1.0 - b)
                    return (result * 255.0).clip(0, 255).astype(np.uint8)
                except Exception:
                    return frame

            return base_clip.fl(blend_frame)

        # Aplicar: para cada boundary, overlay rapido al inicio/final del clip
        transitioned_clips = []
        boundaries_set = set(transition_boundaries)

        for i, clip in enumerate(clips):
            apply_in, apply_out = permissions[i] if i < len(permissions) else (False, False)

            if i in boundaries_set:
                # Overlay al inicio del clip entrante
                effective_dur = min(target_ovr_dur, clip.duration * 0.5)
                blended = make_screen_blend(clip, overlay_fast, effective_dur, 0)
                transitioned_clips.append(blended)
            elif apply_out:
                # Overlay al final del clip saliente
                effective_dur = min(target_ovr_dur, clip.duration * 0.5)
                t_start = max(0, clip.duration - effective_dur)
                blended = make_screen_blend(clip, overlay_fast, effective_dur, t_start)
                transitioned_clips.append(blended)
            else:
                transitioned_clips.append(clip)

        # IMPORTANTE: NO cerrar overlay_raw aqui. Los clips devueltos leen los
        # frames del overlay de forma DIFERIDA (lazy) durante el EXPORT, no ahora.
        # Si cerramos el reader FFMPEG en este punto, cada overlay.get_frame() en
        # render-time lanza excepcion, blend_frame la traga (except: return frame)
        # y devuelve el frame base SIN overlay -> las transiciones no aparecen en
        # el video final. Mantenemos vivas las referencias hasta que el assembler
        # sea recolectado (o se llame a cleanup_transition_resources tras exportar).
        # Asignacion (no extend): cada ensamblaje reemplaza la lista. Los refs del
        # video anterior (ya exportado) se liberan por GC, evitando acumular handles
        # si el assembler se reutiliza para varios videos.
        self._transition_keepalive = [overlay_raw, overlay_resized, overlay_fast]

        applied = len(boundaries_set)
        print(f"   Film Burn overlay aplicado en {applied} cambio(s) de escena ({target_ovr_dur:.2f}s c/u)")
        return transitioned_clips

    def cleanup_transition_resources(self) -> None:
        """Cierra los readers de overlay de transicion. Llamar SOLO tras exportar.

        Los clips de overlay se mantienen abiertos durante todo el render porque
        sus frames se leen de forma diferida. Una vez exportado el video ya no se
        necesitan y se pueden cerrar para liberar los handles de FFMPEG.
        """
        for clip in getattr(self, "_transition_keepalive", []) or []:
            try:
                clip.close()
            except Exception:
                pass
        self._transition_keepalive = []

    def _is_glitch_transition(self, transition_name: str) -> bool:
        """
        Verifica si el tipo de transición es una transición glitch.
        
        Args:
            transition_name: Nombre de la transición
            
        Returns:
            True si es una transición glitch
        """
        glitch_keywords = [
            'glitch', 'digital', 'rgb split', 'data mosh', 'pixel sort',
            'chromatic', 'freeze glitch', 'wave distortion', 'block glitch',
            'noise interference', 'scan lines', 'distorsión', 'distorsion'
        ]
        
        transition_lower = transition_name.lower()
        return any(keyword in transition_lower for keyword in glitch_keywords)
    
    def _apply_glitch_transitions(
        self,
        clips,
        transition_name: str,
        duration: float,
        target_resolution: Tuple[int, int],
        skip_fades: bool = False,
        media_sources: Optional[List[Optional[str]]] = None,
        transitionable_mask: Optional[List[bool]] = None,
    ):
        """
        Aplica transiciones glitch estilo CapCut entre clips.
        
        Args:
            clips: Lista de clips de video
            transition_name: Nombre de la transición glitch
            duration: Duración de la transición
            target_resolution: Resolución del video
            skip_fades: Si se omiten fades para ahorrar memoria
            
        Returns:
            Lista de clips con transiciones glitch aplicadas
        """
        try:
            # Importar el motor de transiciones glitch
            from glitch_transitions import GlitchTransitionEngine, GlitchTransitionType, GlitchIntensity
            
            # Crear motor de transiciones
            engine = GlitchTransitionEngine(target_resolution)
            
            # Determinar tipo de transición glitch
            glitch_type = self._map_glitch_type(transition_name)
            
            # Determinar intensidad basada en el nombre
            intensity = self._determine_glitch_intensity(transition_name)
            
            print(f"    Aplicando transición Glitch: {glitch_type.value} (Intensidad: {intensity.value})")
            
            transitioned_clips = []
            permissions = self._resolve_transition_permissions(
                clips,
                media_sources=media_sources,
                transitionable_mask=transitionable_mask,
            )
            
            for i in range(len(clips)):
                current_clip = clips[i]
                
                # Crear función de transición para este clip
                def create_glitch_effect(clip, is_exit: bool = False):
                    def glitch_effect(get_frame, t):
                        # Calcular progreso de la transición
                        if is_exit:
                            # Transición de salida: empezar en 1 y terminar en 0
                            clip_duration = clip.duration
                            transition_start = clip_duration - duration
                            if t < transition_start:
                                return get_frame(t)
                            progress = 1.0 - ((t - transition_start) / duration)
                        else:
                            # Transición de entrada: empezar en 0 y terminar en 1
                            if t > duration:
                                return get_frame(t)
                            progress = t / duration
                        
                        # Aplicar efecto glitch
                        frame = self._ensure_frame_rgb(get_frame(t))
                        if frame is not None:
                            return self._ensure_frame_rgb(
                                engine.apply_glitch_transition(frame, progress, glitch_type, intensity)
                            )
                        return frame
                    
                    return clip.fl(glitch_effect, apply_to=['video'])
                
                apply_in, apply_out = permissions[i] if i < len(permissions) else (False, False)

                if apply_in and apply_out:
                    clip_with_in = create_glitch_effect(current_clip, is_exit=False)
                    clip_with_both = create_glitch_effect(clip_with_in, is_exit=True)
                    transitioned_clips.append(clip_with_both)
                elif apply_out:
                    transitioned_clips.append(create_glitch_effect(current_clip, is_exit=True))
                elif apply_in:
                    transitioned_clips.append(create_glitch_effect(current_clip, is_exit=False))
                else:
                    transitioned_clips.append(current_clip)
            
            return transitioned_clips
            
        except ImportError:
            print(f"   ️ Módulo glitch_transitions no disponible. Usando transiciones estándar.")
            # Fallback a transiciones estándar
            return self._apply_standard_transitions(
                clips,
                transition_name,
                duration,
                target_resolution,
                skip_fades,
                media_sources=media_sources,
                transitionable_mask=transitionable_mask,
            )
        except Exception as e:
            print(f"   ️ Error aplicando transiciones glitch: {e}. Usando clips sin transiciones.")
            import traceback
            traceback.print_exc()
            return clips
    
    def _map_glitch_type(self, transition_name: str) -> 'GlitchTransitionType':
        """
        Mapea el nombre de la transición a un tipo de glitch específico.
        
        Args:
            transition_name: Nombre de la transición
            
        Returns:
            Tipo de transición glitch
        """
        from glitch_transitions import GlitchTransitionType
        
        name_lower = transition_name.lower()
        
        if 'digital' in name_lower or 'glitch' in name_lower:
            return GlitchTransitionType.DIGITAL_GLITCH
        elif 'rgb' in name_lower or 'split' in name_lower:
            return GlitchTransitionType.RGB_SPLIT
        elif 'data' in name_lower or 'mosh' in name_lower:
            return GlitchTransitionType.DATA_MOSH
        elif 'pixel' in name_lower or 'sort' in name_lower:
            return GlitchTransitionType.PIXEL_SORT
        elif 'chromatic' in name_lower or 'aberration' in name_lower:
            return GlitchTransitionType.CHROMATIC_ABERRATION
        elif 'freeze' in name_lower:
            return GlitchTransitionType.FREEZE_GLITCH
        elif 'wave' in name_lower or 'distortion' in name_lower or 'distorsión' in name_lower:
            return GlitchTransitionType.WAVE_DISTORTION
        elif 'block' in name_lower:
            return GlitchTransitionType.BLOCK_GLITCH
        elif 'noise' in name_lower or 'interference' in name_lower:
            return GlitchTransitionType.NOISE_INTERFERENCE
        elif 'scan' in name_lower or 'lines' in name_lower:
            return GlitchTransitionType.SCAN_LINES
        else:
            # Por defecto: glitch digital
            return GlitchTransitionType.DIGITAL_GLITCH
    
    def _determine_glitch_intensity(self, transition_name: str) -> 'GlitchIntensity':
        """
        Determina la intensidad del glitch basada en el nombre de la transición.
        
        Args:
            transition_name: Nombre de la transición
            
        Returns:
            Intensidad del glitch
        """
        from glitch_transitions import GlitchIntensity
        
        name_lower = transition_name.lower()
        
        if 'subtle' in name_lower or 'suave' in name_lower:
            return GlitchIntensity.SUBTLE
        elif 'intense' in name_lower or 'intenso' in name_lower:
            return GlitchIntensity.INTENSE
        elif 'extreme' in name_lower or 'extremo' in name_lower:
            return GlitchIntensity.EXTREME
        else:
            # Por defecto: moderado
            return GlitchIntensity.MODERATE
    
    def _apply_standard_transitions(
        self,
        clips,
        transition_name: str,
        duration: float,
        target_resolution: Tuple[int, int],
        skip_fades: bool = False,
        media_sources: Optional[List[Optional[str]]] = None,
        transitionable_mask: Optional[List[bool]] = None,
    ):
        """
        Aplica transiciones estándar como fallback.
        
        Args:
            clips: Lista de clips
            transition_name: Nombre de la transición
            duration: Duración
            target_resolution: Resolución
            skip_fades: Si se omiten fades
            
        Returns:
            Lista de clips con transiciones estándar
        """
        try:
            transitioned_clips = []
            permissions = self._resolve_transition_permissions(
                clips,
                media_sources=media_sources,
                transitionable_mask=transitionable_mask,
            )
            
            for i in range(len(clips)):
                current_clip = clips[i]

                apply_in, apply_out = permissions[i] if i < len(permissions) else (False, False)
                if apply_in and apply_out:
                    clip_with_in = self._apply_transition_in(
                        current_clip, transition_name, duration, target_resolution, skip_fades
                    )
                    clip_with_transitions = self._apply_transition_out(
                        clip_with_in, transition_name, duration, target_resolution, skip_fades
                    )
                    transitioned_clips.append(clip_with_transitions)
                elif apply_out:
                    transitioned_clips.append(self._apply_transition_out(
                        current_clip, transition_name, duration, target_resolution, skip_fades
                    ))
                elif apply_in:
                    transitioned_clips.append(self._apply_transition_in(
                        current_clip, transition_name, duration, target_resolution, skip_fades
                    ))
                else:
                    transitioned_clips.append(current_clip)
            
            return transitioned_clips
            
        except Exception as e:
            print(f"   ️ Error en transiciones estándar: {e}. Usando clips sin transiciones.")
            return clips

