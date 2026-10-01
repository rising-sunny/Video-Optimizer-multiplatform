# dynamic_subtitle_wrapper.py
"""
Wrapper para reemplazar el sistema de subtÃ­tulos MoviePy
con el sistema de subtÃ­tulos dinÃ¡micos (ASS + FFmpeg).

Este mÃ³dulo intercepta la generaciÃ³n de subtÃ­tulos y usa
el sistema profesional en lugar de MoviePy TextClip.
"""

import builtins
import ctypes
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
from dynamic_subtitles_generator import DynamicSubtitleEngine


def _safe_print(*args, sep=' ', end='\n', file=None, flush=False):
    """Evita errores de codificación en consolas Windows cp1252."""
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


SHORT_FORM_SUBTITLE_PLATFORMS = {"youtube_short", "tiktok", "reels"}
PRECISE_SUBTITLE_SYNC_MODES = {
    "whisper_hybrid",
    "whisper_raw",
    "whisper_json",
}


def platform_requires_precise_subtitles(platform: Optional[str]) -> bool:
    """Los shorts con subtitulos solo deben exportarse con sync preciso."""
    return str(platform or "").strip().lower() in SHORT_FORM_SUBTITLE_PLATFORMS


def is_precise_subtitle_sync_mode(mode: Optional[str]) -> bool:
    """True solo para modos basados en timestamps reales de Whisper."""
    return str(mode or "").strip().lower() in PRECISE_SUBTITLE_SYNC_MODES


def _resolve_ffmpeg_binary_paths():
    """Ubica ffmpeg/ffprobe usando la misma logica general del proyecto."""
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    try:
        from infra.video_config import VideoConfig

        configured_dir = getattr(VideoConfig, "FFMPEG_BINARY_PATH", None)
        configured_probe = getattr(VideoConfig, "FFPROBE_BINARY_PATH", None)

        if configured_dir:
            ffmpeg_candidate = configured_dir
            if os.path.isdir(configured_dir):
                ffmpeg_candidate = os.path.join(
                    configured_dir,
                    "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
                )
            if ffmpeg_candidate and os.path.exists(ffmpeg_candidate):
                ffmpeg_path = ffmpeg_candidate

            if os.path.isdir(configured_dir):
                probe_candidate = os.path.join(
                    configured_dir,
                    "ffprobe.exe" if os.name == "nt" else "ffprobe"
                )
                if os.path.exists(probe_candidate):
                    ffprobe_path = probe_candidate

        if configured_probe and os.path.exists(configured_probe):
            ffprobe_path = configured_probe
    except Exception:
        pass

    if os.name == "nt":
        common_dirs = [
            os.getenv("FFMPEG_PATH"),
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
            r"C:\Program Files\ffmpeg-2025-11-06-git-222127418b-full_build\bin",
        ]
        for directory in common_dirs:
            if not directory:
                continue
            ffmpeg_candidate = os.path.join(directory, "ffmpeg.exe")
            ffprobe_candidate = os.path.join(directory, "ffprobe.exe")
            if not ffmpeg_path and os.path.exists(ffmpeg_candidate):
                ffmpeg_path = ffmpeg_candidate
            if not ffprobe_path and os.path.exists(ffprobe_candidate):
                ffprobe_path = ffprobe_candidate

    return ffmpeg_path, ffprobe_path


def probe_precise_subtitle_dependencies() -> Dict[str, object]:
    """Resume si el entorno puede generar subtitulos precisos para shorts."""
    status: Dict[str, object] = {
        "whisper_module": False,
        "torch_module": False,
        "ffmpeg_path": None,
        "ffprobe_path": None,
        "missing": [],
        "ready": False,
    }

    try:
        import whisper  # noqa: F401
        status["whisper_module"] = True
    except Exception:
        status["whisper_module"] = False

    try:
        import torch  # noqa: F401
        status["torch_module"] = True
    except Exception:
        status["torch_module"] = False

    ffmpeg_path, ffprobe_path = _resolve_ffmpeg_binary_paths()
    status["ffmpeg_path"] = ffmpeg_path
    status["ffprobe_path"] = ffprobe_path

    missing = []
    # Las dependencias de whisper y torch se omiten de la validacion estricta 
    # porque el sistema utiliza un tunnel VPS/fallback automatico si fallan localmente.
    if not ffmpeg_path:
        missing.append("ffmpeg")
    if not ffprobe_path:
        missing.append("ffprobe")

    status["missing"] = missing
    status["ready"] = not missing
    return status


def normalize_subtitle_style(style: Optional[str]) -> str:
    """Normalize UI labels and legacy style names to engine keys."""
    if not style:
        return "hormozi"

    normalized = str(style).strip().lower()

    valid_styles = {
        "hormozi",
        "mrbeast",
        "tiktok",
        "minimalist",
        "documentary",
        "gaming",
        "news",
        "cinematic",
        "neon",
        "retro",
        "elegant",
        "bold",
        "capcut_creator",
        "capcut_kinetic",
        "capcut_focus",
        "capcut_podcast",
        "capcut_luxury",
        "horror",
        "typewriter",
        "fire",
        "ice",
        "comic",
        "karaoke_party",
        "whatsapp",
        "glitch",
        "handwritten",
        "spotify",
        "military",
        "none",
    }
    if normalized in valid_styles:
        return normalized

    legacy_aliases = {
        "capcut": "tiktok",
        "modern": "mrbeast",
        "minimal": "minimalist",
        "alex_hormozi": "hormozi",
    }
    if normalized in legacy_aliases:
        return legacy_aliases[normalized]

    if "sin subt" in normalized or normalized == "none":
        return "none"
    if "reel" in normalized:
        return "tiktok"
    if "hormozi" in normalized:
        return "hormozi"
    if "mrbeast" in normalized:
        return "mrbeast"
    if "tiktok" in normalized:
        return "tiktok"
    if "capcut" in normalized and "creator" in normalized:
        return "capcut_creator"
    if "capcut" in normalized and "kinetic" in normalized:
        return "capcut_kinetic"
    if "capcut" in normalized and "focus" in normalized:
        return "capcut_focus"
    if "capcut" in normalized and "podcast" in normalized:
        return "capcut_podcast"
    if "capcut" in normalized and ("luxury" in normalized or "gold" in normalized):
        return "capcut_luxury"
    if "capcut" in normalized and "pro" in normalized:
        return "capcut_creator"
    if "minimal" in normalized:
        return "minimalist"
    if "document" in normalized:
        return "documentary"
    if "gaming" in normalized or "stream" in normalized:
        return "gaming"
    if "notic" in normalized or "news" in normalized:
        return "news"
    if "cinemat" in normalized:
        return "cinematic"
    if "neon" in normalized:
        return "neon"
    if "retro" in normalized:
        return "retro"
    if "eleg" in normalized:
        return "elegant"
    if "bold" in normalized or "impact" in normalized:
        return "bold"
    if "horror" in normalized or "terror" in normalized:
        return "horror"
    if "typewriter" in normalized or "maquina" in normalized:
        return "typewriter"
    if "fire" in normalized or "fuego" in normalized:
        return "fire"
    if "ice" in normalized or "hielo" in normalized:
        return "ice"
    if "comic" in normalized or "cartoon" in normalized:
        return "comic"
    if "karaoke" in normalized and "party" in normalized:
        return "karaoke_party"
    if "whatsapp" in normalized or "chat" in normalized:
        return "whatsapp"
    if "glitch" in normalized or "cyber" in normalized:
        return "glitch"
    if "handwrit" in normalized or "manuscri" in normalized:
        return "handwritten"
    if "spotify" in normalized or "music" in normalized:
        return "spotify"
    if "militar" in normalized or "military" in normalized or "tactical" in normalized:
        return "military"

    return "hormozi"


def _is_windows_remote_drive(path: str) -> bool:
    """Return True when path points to a remote Windows drive (includes WebDAV)."""
    if os.name != 'nt' or not path:
        return False

    try:
        abs_path = os.path.abspath(path)
        drive, _ = os.path.splitdrive(abs_path)
        if not drive:
            return False
        drive_root = f"{drive}\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_root)
        return drive_type == 4  # DRIVE_REMOTE
    except Exception:
        return False


def _get_local_safe_output_dir() -> str:
    """Return a local folder to avoid WebDAV file-size limits."""
    base_dir = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    output_dir = os.path.join(base_dir, 'VideoOptimizer', 'output')
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


class DynamicSubtitleWrapper:
    """
    Wrapper que reemplaza los subtÃ­tulos MoviePy con subtÃ­tulos dinÃ¡micos.
    """
    
    def __init__(self, style: str = 'hormozi'):
        """
        Args:
            style: Estilo de subtÃ­tulos ('hormozi', 'mrbeast', 'tiktok', etc.)
        """
        self.style = normalize_subtitle_style(style)
        self.engine = DynamicSubtitleEngine(self.style)
        self.temp_ass_file = None
    
    def generate_ass_from_segments(self,
                                   segments: List[Dict],
                                   output_ass_path: str,
                                   video_width: int = 1920,
                                   video_height: int = 1080,
                                   audio_path: Optional[str] = None,
                                   force_whisper: bool = False,
                                   language: Optional[str] = None) -> str:
        """
        Genera archivo ASS desde segmentos de Whisper.

        Args:
            segments: Lista de segmentos con formato:
                [{'start': float, 'end': float, 'text': str}, ...]
            output_ass_path: Donde guardar el archivo ASS
            video_width: Ancho del video
            video_height: Alto del video
            audio_path: Path al audio narrado (si se proporciona, usa Whisper
                        para timestamps precisos palabra por palabra)
            language: Idioma del audio ('es', 'en', etc.) para mejorar Whisper

        Returns:
            Path al archivo ASS generado
        """
        # Si existe audio real de narracion, usarlo por defecto para alinear
        # subtitulos con la locucion final. Se puede desactivar con:
        #   VIDEO_OPTIMIZER_SUBS_USE_WHISPER=0
        # o forzar explicitamente con:
        #   VIDEO_OPTIMIZER_SUBS_USE_WHISPER=1
        audio_available = bool(audio_path and os.path.exists(str(audio_path)))
        whisper_pref = str(os.environ.get("VIDEO_OPTIMIZER_SUBS_USE_WHISPER", "auto") or "auto").strip().lower()
        if whisper_pref in {"0", "false", "no", "off"}:
            whisper_enabled = False
        elif whisper_pref in {"1", "true", "yes", "on"}:
            whisper_enabled = True
        else:
            whisper_enabled = True

        use_whisper = audio_available and (force_whisper or whisper_enabled)

        if use_whisper:
            if force_whisper:
                print("Usando Whisper forzado para sincronizacion precisa de subtitulos...")
            else:
                print("Usando Whisper para sincronizacion precisa de subtitulos...")
            try:
                ass_path = self.engine.generate_from_audio_and_segments(
                    str(audio_path),
                    segments,
                    output_ass_path,
                    video_width,
                    video_height,
                    language=language
                )
                sync_mode = (self.engine.last_sync_details or {}).get('mode')
                if sync_mode and sync_mode != 'uninitialized' and not str(sync_mode).startswith('whisper'):
                    print(f"️ Subtítulos generados sin Whisper real (modo: {sync_mode}).")
                self.temp_ass_file = ass_path
                return ass_path
            except Exception as e:
                print(f"Whisper fallo ({e}), usando texto/timing de segmentos...")
        elif force_whisper and not audio_available:
            print("Whisper forzado pero no hay audio válido; usando texto/timing de segmentos...")
        else:
            print("Generando subtitulos desde texto/timing de segmentos editados...")

        # Generacion por segmentos: garantiza coincidencia con texto editado.
        normalized_segments = []

        for seg in segments:
            start = seg.get('timestamp_start', seg.get('start', 0))
            end = seg.get('timestamp_end', seg.get('end', 0))
            try:
                start = float(start)
            except (TypeError, ValueError):
                start = 0.0
            try:
                end = float(end)
            except (TypeError, ValueError):
                end = start
            if end < start:
                end = start

            # `text` es el campo canónico del editor de timeline.
            text = str(seg.get('text', seg.get('narration_text', '')) or '').strip()

            seg_data = {
                'start': start,
                'end': end,
                'text': text,
                'words': []
            }

            words = text.split()
            if words:
                duration = max(seg_data['end'] - seg_data['start'], 0.001)
                time_per_word = duration / len(words)

                for i, word in enumerate(words):
                    word_start = seg_data['start'] + (i * time_per_word)
                    word_end = word_start + time_per_word
                    seg_data['words'].append({
                        'word': word,
                        'start': word_start,
                        'end': word_end
                    })
            elif 'words' in seg and seg['words']:
                # Fallback: si no hay texto pero existe word-timing previo.
                seg_data['words'] = seg['words']

            normalized_segments.append(seg_data)

        # Generar archivo ASS
        ass_path = self.engine.generate_from_segments(
            normalized_segments,
            output_ass_path,
            video_width,
            video_height
        )

        self.temp_ass_file = ass_path
        return ass_path
    
    
    def cleanup(self):
        """Limpia archivos temporales"""
        if self.temp_ass_file and os.path.exists(self.temp_ass_file):
            try:
                os.remove(self.temp_ass_file)
                print(f"ðŸ§¹ Archivo ASS temporal eliminado")
            except:
                pass


import types  # FIX: Para MethodType bind de 'self'

def patch_subtitle_generation(generator, subtitle_style='hormozi'):
    """
    Parchea el generador para usar subtÃ­tulos dinÃ¡micos en lugar de MoviePy.
    
    Args:
        generator: Instancia del AutoVideoGenerator
        subtitle_style: Estilo de subtÃ­tulos ('hormozi', 'mrbeast', etc.)
    
    Returns:
        None (modifica el generator in-place)
    """
    from dynamic_subtitles_generator import DynamicSubtitleEngine
    import os
    subtitle_style = normalize_subtitle_style(subtitle_style)
    
    # Guardar referencia al mÃ©todo original antes de reemplazarlo
    original_assemble_method = generator.assemble_video_from_storyboard
    
    # Crear wrapper y guardarlo en el generator
    wrapper = DynamicSubtitleWrapper(style=subtitle_style)
    generator._dynamic_subtitle_wrapper = wrapper
    
    # Definir la funciÃ³n de ensamblaje con subtÃ­tulos (nested para closure)
    def assemble_with_dynamic_subtitles(self, storyboard_data, subtitle_style=subtitle_style, 
                                       add_subtitles=True, video_width=1920, video_height=1080, platform='youtube', **kwargs):
        """
        Ensambla video con subtÃ­tulos dinÃ¡micos (wrapper principal).
        Primero genera el video base, luego aplica subtÃ­tulos dinÃ¡micos.
        
        Args:
            self: Instancia del generator
            storyboard_data: Datos del storyboard
            subtitle_style: Estilo de subtÃ­tulos
            add_subtitles: Si agregar subtÃ­tulos
            video_width: Ancho del video
            video_height: Alto del video
            platform: Plataforma (afecta resoluciÃ³n)
            **kwargs: Absorbe extras (ej: add_overlays)
        
        Returns:
            dict: Resultado con video_path y metadata
        """
        import json
        import subprocess
        from pathlib import Path
        import shutil
        
        result = {
            'video_path': None,
            'script': storyboard_data.get('script', ''),
            'topic': storyboard_data.get('topic', ''),
            'category': storyboard_data.get('category', ''),
            'music_attribution': storyboard_data.get('music_attribution', ''),
            'ass_path': None  # Para fallback manual
        }
        
        # Si no se deben agregar subtÃ­tulos, usar el mÃ©todo original directamente
        subtitle_style = normalize_subtitle_style(subtitle_style)
        if subtitle_style == 'none':
            add_subtitles = False

        if not add_subtitles:
            return original_assemble_method(storyboard_data, platform=platform, add_subtitles=False, **kwargs)
        
        # PASO 1: Generar video base SIN subtÃ­tulos usando el mÃ©todo original
        print("ðŸŽ¬ Generando video base (sin subtÃ­tulos)...")
        base_result = original_assemble_method(
            storyboard_data, 
            platform=platform, 
            add_subtitles=False,  # NO agregar subtÃ­tulos aquÃ­
            subtitle_style=subtitle_style,
            **{k: v for k, v in kwargs.items() if k != 'add_subtitles'}  # Pasar otros kwargs
        )
        
        if not base_result or not base_result.get('video_path'):
            print("âŒ Error generando video base. Abortando.")
            return result
        
        video_path = base_result['video_path']
        
        # Verificar que el video existe
        if not os.path.exists(video_path):
            print(f"âŒ Video base no encontrado en: {video_path}")
            return result
        
        segments = storyboard_data.get('segments', [])
        if not segments:
            print("âš ï¸ Sin segmentos. Video base sin subs.")
            result['video_path'] = video_path
            result.update(base_result)  # Copiar otros datos del resultado base
            return result

        require_precise_sync = bool(
            storyboard_data.get('_require_precise_subtitle_sync')
            or platform_requires_precise_subtitles(platform)
        )

        # Si el ensamblador devuelve timeline real de render, usarlo para evitar desfase.
        segments_for_subtitles = segments
        render_timeline = base_result.get('render_timeline') if isinstance(base_result, dict) else None
        if render_timeline:
            timeline_by_index = {}
            for item in render_timeline:
                seg_idx = item.get('segment_index')
                if isinstance(seg_idx, int):
                    timeline_by_index[seg_idx] = item

            adjusted_segments = []
            for idx, seg in enumerate(segments):
                t = timeline_by_index.get(idx)
                if not t:
                    continue
                seg_copy = dict(seg)
                seg_copy['start'] = float(t.get('start', seg_copy.get('start', 0.0)))
                seg_copy['end'] = float(t.get('end', seg_copy.get('end', seg_copy['start'])))
                seg_copy['timestamp_start'] = seg_copy['start']
                seg_copy['timestamp_end'] = seg_copy['end']
                adjusted_segments.append(seg_copy)

            if adjusted_segments:
                segments_for_subtitles = adjusted_segments
                print(f"âœ… SubtÃ­tulos alineados con timeline de render ({len(segments_for_subtitles)} segmentos)")

        force_whisper_subtitles = bool(
            (base_result.get('force_whisper_subtitles') if isinstance(base_result, dict) else False) or
            storyboard_data.get('_force_whisper_subtitles')
        )

        # Priorizar el audio final del render cuando exista; si no, usar la
        # narración del storyboard. Así evitamos desfases si el export añadió
        # silêncio/outro o algún ajuste temporal.
        subtitle_audio_path = None
        if isinstance(base_result, dict):
            candidate_paths = [
                # Voz sola alineada al render: Whisper acierta muchas mas
                # palabras que sobre la mezcla con musica (mismo timeline).
                base_result.get('subtitle_audio_path'),
                base_result.get('final_audio_path'),
                base_result.get('audio_path'),
                storyboard_data.get('audio_path'),
            ]
            for candidate in candidate_paths:
                if candidate and os.path.exists(str(candidate)):
                    subtitle_audio_path = str(candidate)
                    break
        elif storyboard_data.get('audio_path') and os.path.exists(str(storyboard_data.get('audio_path'))):
            subtitle_audio_path = str(storyboard_data.get('audio_path'))

        if require_precise_sync and not subtitle_audio_path:
            raise RuntimeError(
                "Exportacion bloqueada: el short requiere un audio final valido "
                "para sincronizar subtitulos con Whisper."
            )
        
        # Inicializar wrapper
        wrapper = DynamicSubtitleWrapper(style=subtitle_style)
        
        try:
            # Obtener dimensiones reales del video (fallback a params)
            def get_video_dimensions(vp):
                cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', vp]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    for stream in data['streams']:
                        if stream['codec_type'] == 'video':
                            return int(stream.get('width', video_width)), int(stream.get('height', video_height))
                return video_width, video_height
            
            actual_width, actual_height = get_video_dimensions(video_path)
            
            # Generar ASS con paths absolutos y dims correctas
            base_path = os.path.abspath(video_path)
            ass_path = base_path.replace('.mp4', '.ass')
            ass_path = os.path.abspath(ass_path)  # Asegurar absolute
            
            subtitle_language = storyboard_data.get('language') or None
            wrapper.generate_ass_from_segments(
                segments_for_subtitles,
                ass_path,
                video_width=actual_width,
                video_height=actual_height,
                audio_path=subtitle_audio_path,
                force_whisper=force_whisper_subtitles,
                language=subtitle_language
            )
            sync_details = dict(wrapper.engine.last_sync_details or {})
            sync_mode = sync_details.get('mode')
            result['subtitle_sync_mode'] = sync_mode
            result['subtitle_sync_details'] = sync_details

            if require_precise_sync and not is_precise_subtitle_sync_mode(sync_mode):
                raise RuntimeError(
                    "Exportacion bloqueada: los shorts con subtitulos requieren "
                    f"sincronizacion precisa de Whisper. Modo obtenido: {sync_mode or 'desconocido'}."
                )
            
            # Verificar que el video base tiene audio antes de aplicar subtÃ­tulos
            import subprocess
            check_audio_cmd = ['ffprobe', '-v', 'quiet', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', base_path]
            audio_check = subprocess.run(check_audio_cmd, capture_output=True, text=True)
            has_audio = audio_check.returncode == 0 and audio_check.stdout.strip() == 'audio'
            
            if not has_audio:
                print(f"âš ï¸ ADVERTENCIA: El video base no tiene pista de audio. El video final puede no tener audio.")
                print(f"   Verificando si el audio se perdiÃ³ durante la exportaciÃ³n...")
            
            # Aplicar subtÃ­tulos quemados
            base_root, base_ext = os.path.splitext(base_path)
            if not base_ext:
                base_ext = '.mp4'

            use_local_subtitle_output = _is_windows_remote_drive(base_path)
            if use_local_subtitle_output:
                local_output_dir = _get_local_safe_output_dir()
                video_with_subs = os.path.join(
                    local_output_dir,
                    f"{os.path.basename(base_root)}_with_subs{base_ext}"
                )
                print("âš ï¸ Unidad remota/WebDAV detectada para salida de video.")
                print("   Para evitar ERROR_FILE_TOO_LARGE (0x800700DF),")
                print(f"   el video final con subtÃ­tulos se guardarÃ¡ localmente: {video_with_subs}")
            else:
                video_with_subs = f"{base_root}_with_subs{base_ext}"

            video_with_subs = os.path.abspath(video_with_subs)
            
            success = wrapper.engine.burn_subtitles_with_ffmpeg(
                base_path,
                ass_path,
                video_with_subs,
                video_width=actual_width,
                video_height=actual_height
            )
            
            if success:
                if use_local_subtitle_output:
                    print(f"âœ… Video con subtÃ­tulos guardado en ruta local segura: {video_with_subs}")
                    result['video_path'] = video_with_subs
                    result['remote_base_video_path'] = base_path
                else:
                    # Reemplazar original
                    try:
                        os.remove(base_path)
                        shutil.move(video_with_subs, base_path)
                        print(f"âœ… Video actualizado con subtÃ­tulos dinÃ¡micos: {base_path}")
                        result['video_path'] = base_path
                    except Exception as e:
                        print(f"âš ï¸ No se pudo reemplazar el video original: {e}")
                        result['video_path'] = video_with_subs
            else:
                print("âš ï¸ Fallback: Sin subtÃ­tulos quemados. Usa comando manual para post-producciÃ³n:")
                # Comando manual corregido y copiable para CMD
                escaped_ass = (
                    ass_path
                    .replace('\\', '/')
                    .replace(':', '\\:')
                    .replace(',', '\\,')
                    .replace("'", "\\'")
                )
                manual_output = base_path.replace('.mp4', '_manual_subs.mp4')
                manual_cmd = (
                    f"ffmpeg -i \"{base_path}\" "
                    f"-vf \"subtitles=filename='{escaped_ass}':original_size={actual_width}x{actual_height}\" "
                    f"-c:v libx264 -preset medium -crf 23 -c:a copy "
                    f"\"{manual_output}\""
                )
                print(f"   {manual_cmd}")
                print("   (Ejecuta en CMD desde el directorio del video)")
                result['video_path'] = base_path  # Video sin subs
                result['ass_path'] = ass_path  # Para manual
                result['manual_ffmpeg_cmd'] = manual_cmd  # Para GUI si aplica
            
            # Copiar otros datos del resultado base
            result['script'] = base_result.get('script', storyboard_data.get('script', ''))
            result['topic'] = base_result.get('topic', storyboard_data.get('topic', ''))
            result['category'] = base_result.get('category', storyboard_data.get('category', ''))
            result['music_attribution'] = base_result.get('music_attribution', '')
            result['music_used'] = base_result.get('music_used')   # atribucion al publicar (music_license)

            # Cleanup condicional
            if success and os.path.exists(ass_path):
                try:
                    os.remove(ass_path)
                    print("ðŸ§¹ Archivo ASS temporal eliminado")
                except:
                    pass
                    
        except Exception as e:
            if isinstance(e, RuntimeError) and str(e).startswith("Exportacion bloqueada:"):
                raise
            print(f"âš ï¸ Error aplicando subtÃ­tulos dinÃ¡micos: {e}")
            print(f"   El video se generÃ³ sin subtÃ­tulos: {video_path}")
            import traceback
            traceback.print_exc()
            # Devolver el resultado base (video sin subtÃ­tulos)
            result = base_result.copy()
        
        return result
    
    # FIX: Bind con MethodType para 'self' correcto (resuelve TypeError)
    bound_method = types.MethodType(assemble_with_dynamic_subtitles, generator)
    generator.assemble_video_from_storyboard = bound_method
    
    # Guardar wrapper para uso posterior
    generator._dynamic_subtitle_wrapper = wrapper
    
    print(f"âœ… SubtÃ­tulos dinÃ¡micos activados (estilo: {subtitle_style})")        


if __name__ == "__main__":
    print("ðŸŽ¬ Dynamic Subtitle Wrapper")
    print("Este mÃ³dulo se usa como wrapper para reemplazar subtÃ­tulos MoviePy.")
    print("\nUso:")
    print("  from dynamic_subtitle_wrapper import patch_subtitle_generation")
    print("  patch_subtitle_generation(generator, 'hormozi')")


