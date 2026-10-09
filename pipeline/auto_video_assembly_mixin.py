# auto_video_generator_v2.py
import builtins
import importlib.util
import os
import time
import requests
from pathlib import Path
from datetime import datetime
import json
from ai.ai_factory import AIFactory
import sys


def _safe_print(*args, sep=' ', end='\n', file=None, flush=False):
    """Evita caÃ­das por logs Unicode en consolas Windows cp1252."""
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

from typing import List, Dict, Optional, Tuple
from pipeline import audio_mix_utils
from pipeline import segment_layouts
from pipeline import video_motion
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import base64
import random
import shutil
import tempfile
import ctypes

# --- FIX CRÃTICO PARA PILLOW 10.0+ Y MOVIEPY ---
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS


def _is_windows_remote_drive(path: str) -> bool:
    """Detecta unidades remotas/WebDAV para evitar errores 0x800700DF."""
    if os.name != 'nt' or not path:
        return False

    try:
        abs_path = os.path.abspath(str(path))
        drive, _ = os.path.splitdrive(abs_path)
        if not drive:
            return False
        drive_root = f"{drive}\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_root)
        return drive_type == 4  # DRIVE_REMOTE
    except Exception:
        return False


def _get_local_safe_output_dir() -> Path:
    """Carpeta local segura para exportaciones pesadas cuando el proyecto estÃ¡ en WebDAV."""
    base_dir = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    output_dir = Path(base_dir) / 'VideoOptimizer' / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _resolve_safe_video_output_path(output_path: Path) -> Tuple[Path, bool]:
    """Redirige la exportaciÃ³n a disco local si la salida cae en una unidad remota."""
    output_path = Path(output_path)
    if _is_windows_remote_drive(str(output_path)):
        return _get_local_safe_output_dir() / output_path.name, True
    return output_path, False

# ========== VERIFICACIÃ“N DE DEPENDENCIAS Y CONFIGURACIÃ“N DE ENTORNO ==========
GTTS_AVAILABLE = False
EDGE_TTS_AVAILABLE = False
MOVIEPY_AVAILABLE = False
WHISPER_AVAILABLE = False
PYDUB_AVAILABLE = False

# 1. gTTS
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    print("âš ï¸ gTTS no disponible (Instala: pip install gTTS)")

# 1.5. Edge-TTS (Microsoft Edge voices - GRATIS)
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    print("âš ï¸ edge-tts no disponible (Instala: pip install edge-tts)")

# 2. MoviePy
try:
    from moviepy.editor import (
        VideoFileClip, AudioFileClip, ImageClip,
        CompositeVideoClip, concatenate_videoclips,
        TextClip, CompositeAudioClip, concatenate_audioclips
    )
    # vfx incluye tanto efectos de video como de audio (audio_fadeout, etc.)
    import moviepy.audio.fx.all as vfx
    # AudioClip estÃ¡ disponible desde moviepy.audio.AudioClip
    from moviepy.audio.AudioClip import AudioClip
    MOVIEPY_AVAILABLE = True
except ImportError as e:
    print(f"âš ï¸ MoviePy no disponible (Instala: pip install moviepy<2.0.0)")
    print(f"   Error de importaciÃ³n: {e}")

# 3. Whisper
try:
    WHISPER_AVAILABLE = importlib.util.find_spec("whisper") is not None
except Exception:
    WHISPER_AVAILABLE = False

if not WHISPER_AVAILABLE:
    print("âš ï¸ Whisper no disponible - subtÃ­tulos deshabilitados (Instala: pip install openai-whisper)")

# 4. Pydub y FFmpeg
try:
    from pydub import AudioSegment
    
    # Configurar la ruta de FFmpeg para pydub (EspecÃ­fico para Windows)
    import platform
    if platform.system() == "Windows":
        # Usar primero la deteccion central, que ya valida ffmpeg + ffprobe.
        configured_dir = None
        try:
            from infra.video_config import VideoConfig as _VideoConfig
            configured_dir = getattr(_VideoConfig, "FFMPEG_BINARY_PATH", None)
        except ImportError:
            pass

        ffmpeg_from_path = shutil.which("ffmpeg")
        possible_paths = [
            configured_dir,
            os.path.dirname(ffmpeg_from_path) if ffmpeg_from_path else None,
            r"C:\Program Files\ffmpeg-2025-11-06-git-222127418b-full_build\bin",
            r"C:\ffmpeg\bin",
            os.getenv("FFMPEG_PATH", "")
        ]
        
        ffmpeg_configured = False
        for base_path in possible_paths:
            if not base_path: continue
            ffmpeg_exe = os.path.join(base_path, "ffmpeg.exe")
            ffprobe_exe = os.path.join(base_path, "ffprobe.exe")
            
            if os.path.exists(ffmpeg_exe) and os.path.exists(ffprobe_exe):
                AudioSegment.converter = ffmpeg_exe
                AudioSegment.ffmpeg = ffmpeg_exe
                AudioSegment.ffprobe = ffprobe_exe
                print(f"[OK] pydub configurado con FFmpeg en: {base_path}")
                ffmpeg_configured = True
                break
        
        if not ffmpeg_configured:
            # Intentar usar el PATH del sistema
            print("[!] No se encontro FFmpeg/ffprobe para pydub; confiando en el PATH del sistema.")
            
    PYDUB_AVAILABLE = True
except ImportError:
    print("[!] pydub no esta instalado. El Audio Ducking fallara. (Instala: pip install pydub)")
except Exception as e:
    print(f"[!] Error al configurar pydub: {e}")

# --- MÃ“DULOS DEL PROYECTO (IA y Utilidades) ---
try:
    from ai.gemini_ai_client import GeminiAiClient
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("[!] gemini_ai_client.py no encontrado. La generacion de guion contextual fallara.")

try:
    from runwayml import RunwayML
    RUNWAY_AVAILABLE = True
except ImportError:
    RUNWAY_AVAILABLE = False
    print("[!] SDK runwayml no encontrado (opcional, se usan otros proveedores).")

try:
    from media.music_recommender import (
        analyze_narration,
        map_ai_to_jamendo_tags,
        search_jamendo_api,
        download_track
    )
    JAMENDO_AVAILABLE = True
    print("[OK] Music Recommender (Jamendo) cargado")
except ImportError as e:
    JAMENDO_AVAILABLE = False
    print(f"[!] music_recommender.py no disponible: {e}")

try:
    from ai.google_search_api import search_google_trends
    GOOGLE_SEARCH_AVAILABLE = True
except ImportError:
    GOOGLE_SEARCH_AVAILABLE = False
    print("[!] google_search_api.py no encontrado. Los guiones no tendran investigacion.")

try:
    from pipeline.sfx_client import find_and_download_sfx
    SFX_AVAILABLE = False  # Desactivado por defecto
except ImportError:
    SFX_AVAILABLE = False
    print("[!] sfx_client.py no encontrado. La busqueda de SFX fallara.")

try:
    from pipeline.cinematic_effects import CinematicEffectsEngine, ContextDetector
    CINEMATIC_AVAILABLE = True
except ImportError:
    CINEMATIC_AVAILABLE = False
    print("[!] cinematic_effects.py no encontrado. Efectos cinematograficos desactivados.")


try:
    from ai.recraft_client import RecraftClient
    RECRAFT_AVAILABLE = True
    print("[OK] Recraft client cargado")
except ImportError:
    RECRAFT_AVAILABLE = False
    print("[!] recraft_client.py no encontrado. Recraft no funcionara.")

# Importar clientes de Google Images y Wikimedia
try:
    from ai.google_images_client import GoogleImagesClient
    GOOGLE_IMAGES_AVAILABLE = True
    print("[OK] Google Images client cargado")
except ImportError:
    GOOGLE_IMAGES_AVAILABLE = False
    print("[!] google_images_client.py no encontrado. La busqueda de imagenes en Google Images no funcionara.")

try:
    from media.wikimedia_client import WikimediaClient
    WIKIMEDIA_AVAILABLE = True
    print("[OK] Wikimedia client cargado")
except ImportError:
    WIKIMEDIA_AVAILABLE = False
    print("[!] wikimedia_client.py no encontrado. La busqueda de imagenes en Wikimedia no funcionara.")

try:
    from ai.google_ai_image_client import GoogleAiImageClient
    GOOGLE_AI_IMAGE_AVAILABLE = True
    print("[OK] Google AI Image client cargado")
except ImportError:
    GOOGLE_AI_IMAGE_AVAILABLE = False
    print("[!] google_ai_image_client.py no encontrado. Google AI Image no funcionara.")

try:
    from ai.stability_client import StabilityClient
    STABILITY_AVAILABLE = True
    print("[OK] Stability AI client cargado")
except ImportError:
    STABILITY_AVAILABLE = False
    print("[!] stability_client.py no encontrado. Stability AI no funcionara.")

try:
    from ai.comfyui_image_client import ComfyUiImageClient
    COMFYUI_AVAILABLE = True
    print("[OK] ComfyUI image client cargado")
except ImportError:
    COMFYUI_AVAILABLE = False
    print("[!] comfyui_image_client.py no encontrado. ComfyUI no funcionara.")

# ========== IMPORTAR CONFIGURACION DESDE MODULO SEPARADO ==========
# VideoConfig ha sido movido a video_config.py para mejor organizacion
try:
    from infra.video_config import VideoConfig
except ImportError:
    # Fallback: definir VideoConfig aqui si el modulo no esta disponible
    # (para compatibilidad hacia atras)
    print("[!] video_config.py no encontrado, usando definicion local de VideoConfig")
    
    # ========== CONFIGURACION GLOBAL (FALLBACK) ==========
    class VideoConfig:
        """ConfiguraciÃ³n centralizada del sistema"""
        
        @staticmethod
        def get_negative_prompt(base_negative=None):
            """
            Genera un negative prompt robusto para prevenir errores de generaciÃ³n IA.
            Usa solo caracteres ASCII para evitar problemas de codificaciÃ³n.
            
            Args:
                base_negative: Negative prompt base adicional (opcional)
                
            Returns:
                String con negative prompt completo (solo ASCII)
            """
            # Negative prompts base para prevenir errores comunes (solo ASCII)
            negative_base = [
            # Distorsiones y deformidades
            "distorted", "deformed", "malformed", "disfigured", "mutated",
            "ugly", "bad anatomy", "bad proportions", "extra limbs", "missing limbs",
            "extra fingers", "missing fingers", "fused fingers", "too many fingers",
            "extra arms", "extra legs", "extra heads", "duplicate", "cloned",
            "malformed hands", "malformed feet", "malformed face", "asymmetric",
            
            # Alucinaciones y artefactos
            "text", "words", "letters", "numbers", "signs", "symbols", "logos",
            "watermark", "signature", "copyright", "trademark", "brand",
            "artifacts", "glitches", "noise", "grain", "pixelated", "blurry",
            "low quality", "low resolution", "jpeg artifacts", "compression artifacts",
            "double exposure", "ghosting", "halo", "lens flare", "chromatic aberration",
            
            # Problemas de composiciÃ³n
            "bad composition", "cropped", "cut off", "out of frame", "incomplete",
            "partial", "truncated", "amputated", "floating objects", "disconnected",
            "unrealistic", "impossible", "illogical", "nonsensical",
            
            # Problemas de iluminaciÃ³n y color
            "overexposed", "underexposed", "washed out", "oversaturated", "undersaturated",
            "color bleeding", "color shift", "unnatural colors", "wrong colors",
            
            # Elementos no deseados
            "nude", "naked", "nsfw", "explicit", "inappropriate",
            "modern technology", "modern vehicles", "modern buildings", "anachronism",
            "contemporary", "modern clothing", "modern architecture",
            
                # Calidad y estilo
                "amateur", "unprofessional", "draft", "sketch", "unfinished",
                "cartoon", "animation", "3d render", "cgi", "computer graphics",
                "stock photo", "generic", "boring", "uninteresting"
            ]
            
            # Combinar negative prompts
            negative_prompt = ", ".join(negative_base)
            
            # Agregar negative prompt base adicional si se proporciona
            # Limpiar cualquier carÃ¡cter no ASCII del base_negative
            if base_negative:
                # Normalizar a ASCII si es necesario
                try:
                    base_negative_clean = base_negative.encode('ascii', 'ignore').decode('ascii')
                    if base_negative_clean.strip():
                        negative_prompt = f"{negative_prompt}, {base_negative_clean}"
                except:
                    # Si falla, usar el original pero limpiar caracteres problemÃ¡ticos
                    base_negative_clean = ''.join(char for char in base_negative if ord(char) < 128)
                    if base_negative_clean.strip():
                        negative_prompt = f"{negative_prompt}, {base_negative_clean}"
            
            # Asegurar que el resultado final sea solo ASCII
            try:
                negative_prompt = negative_prompt.encode('ascii', 'ignore').decode('ascii')
            except:
                # Fallback: remover cualquier carÃ¡cter no ASCII manualmente
                negative_prompt = ''.join(char for char in negative_prompt if ord(char) < 128)
            
            return negative_prompt
        
        # APIs (leÃ­das desde .env por el script principal)
        PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
        PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")
        ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        
        # Directorios
        BASE_DIR = Path("auto_videos")
        DOWNLOADS_DIR = BASE_DIR / "downloads"
        AUDIO_DIR = BASE_DIR / "audio"
        OUTPUT_DIR = BASE_DIR / "output"
        TEMP_DIR = BASE_DIR / "temp"
        BGM_DIR = BASE_DIR / "bgm_library"  # Para mÃºsica manual
        
        # ConfiguraciÃ³n de video
        VIDEO_RESOLUTION = (1920, 1080)  # YouTube horizontal
        VIDEO_RESOLUTION_VERTICAL = (1080, 1920)  # Vertical (Shorts/TikTok)
        DEFAULT_VIDEO_WIDTH = 1920
        DEFAULT_VIDEO_HEIGHT = 1080
        DEFAULT_VIDEO_FPS = 30
        
        # Duraciones por plataforma (segundos)
        PLATFORM_DURATIONS = {
            'youtube': 300,      # 5 minutos
            'youtube_short': 120,  # 2 minutos
            'youtube_vertical': 600,  # 10 minutos vertical largo
            'tiktok': 60,        # 1 minuto
            'reels': 60          # 1 minuto
        }
        
        # ConfiguraciÃ³n de estilos de subtÃ­tulos detallada
        SUBTITLE_STYLES = {
            'capcut': {
                'font_size': 70,
                'font_color': 'white',
                'stroke_color': 'black',
                'stroke_width': 3,
                'bg_color': None,
                'position': ('center', 'bottom'),
                'animation': 'pop'
            },
            'modern': {
                'font_size': 60,
                'font_color': 'yellow',
                'stroke_color': 'black',
                'stroke_width': 2,
                'bg_color': 'rgba(0,0,0,0.7)',
                'position': ('center', 'bottom'),
                'animation': 'pop'
            },
            'minimal': {
                'font_size': 50,
                'font_color': 'white',
                'stroke_color': None,
                'stroke_width': 0,
                'bg_color': None,
                'position': ('center', 'bottom'),
                'animation': 'pop'
            },
            'alex_hormozi': {
                'font_size': 80,
                'font_color': 'yellow',
                'stroke_color': 'black',
                'stroke_width': 4,
                'bg_color': 'rgba(0,0,0,0.8)',
                'position': ('center', 'center'),
                'animation': 'zoom',
                'highlight_keywords': True
            }
        }
        
        @classmethod
        def setup_directories(cls):
            """Crea todos los directorios necesarios"""
            for directory in [cls.BASE_DIR, cls.DOWNLOADS_DIR, cls.AUDIO_DIR, 
                             cls.OUTPUT_DIR, cls.TEMP_DIR, cls.BGM_DIR]:
                directory.mkdir(parents=True, exist_ok=True)
            print("âœ… Directorios configurados")


# ========== IMPORTAR DESCARGADOR DE RECURSOS DESDE MÃ“DULO SEPARADO ==========
# ResourceDownloader ha sido movido a resource_downloader.py
try:
    from media.resource_downloader import ResourceDownloader
except ImportError:
    print("âš ï¸ resource_downloader.py no encontrado, ResourceDownloader no disponible")
    ResourceDownloader = None


# ========== IMPORTAR GENERADOR DE VOZ DESDE MÃ“DULO SEPARADO ==========
# TextToSpeechGenerator ha sido movido a tts_generator.py
try:
    from pipeline.tts_generator import TextToSpeechGenerator
except ImportError:
    print("âš ï¸ tts_generator.py no encontrado, TextToSpeechGenerator no disponible")
    TextToSpeechGenerator = None

# Nota: TextToSpeechGenerator estÃ¡ en tts_generator.py
# Nota: SubtitleGenerator estÃ¡ en subtitle_generator.py

# ========== IMPORTAR GENERADOR DE SUBTÃTULOS DESDE MÃ“DULO SEPARADO ==========
try:
    from pipeline.subtitle_generator import SubtitleGenerator
except ImportError:
    print("âš ï¸ subtitle_generator.py no encontrado, SubtitleGenerator no disponible")
    SubtitleGenerator = None

# ========== IMPORTAR ENSAMBLADOR DE VIDEO DESDE MÃ“DULO SEPARADO ==========
# ContextualVideoAssembler ha sido movido a video_assembler.py
try:
    from pipeline.video_assembler import ContextualVideoAssembler
except ImportError:
    print("âš ï¸ video_assembler.py no encontrado, ContextualVideoAssembler no disponible")
    ContextualVideoAssembler = None
                                                        
# ========== IMPORTAR VIDEO GENERATION MANAGER DESDE MÃ“DULO SEPARADO ==========
# VideoGenerationManager ha sido movido a video_generation_manager.py
try:
    from pipeline.video_generation_manager import VideoGenerationManager
except ImportError:
    print("âš ï¸ video_generation_manager.py no encontrado, VideoGenerationManager no disponible")
    VideoGenerationManager = None

# ========== IMPORTAR PROMPT PROCESSOR DESDE MÃ“DULO SEPARADO ==========
# PromptProcessor ha sido movido a prompt_processor.py
try:
    from ai.prompt_processor import PromptProcessor
except ImportError:
    print("âš ï¸ prompt_processor.py no encontrado, PromptProcessor no disponible")
    PromptProcessor = None

# ========== IMPORTAR VIDEO EXPORT MANAGER DESDE MÃ“DULO SEPARADO ==========
# VideoExportManager ha sido movido a video_export_manager.py
try:
    from pipeline.video_export_manager import VideoExportManager
except ImportError:
    print("âš ï¸ video_export_manager.py no encontrado, VideoExportManager no disponible")
    VideoExportManager = None

try:
    from pipeline.storyboard_generator import StoryboardGenerator
except ImportError:
    print("âš ï¸ storyboard_generator.py no encontrado, StoryboardGenerator no disponible")
    StoryboardGenerator = None

try:
    from pipeline.image_generation_manager import ImageGenerationManager
except ImportError:
    print("âš ï¸ image_generation_manager.py no encontrado, ImageGenerationManager no disponible")
    ImageGenerationManager = None

from functools import lru_cache

@lru_cache(maxsize=1)
def get_optimal_h264_encoder(ffmpeg_exe="ffmpeg"):
    """Detecta el mejor codificador H264 disponible en el sistema.
    Por seguridad en equipos sin GPU dedicada, se fuerza libx264."""
    return "libx264"

# ========== CLASE PRINCIPAL: AUTO VIDEO GENERATOR ==========


class AutoVideoAssemblyMixin:
    def _export_video_with_ffmpeg(self, video_clip, output_path, video_bitrate='8000k', 
                                   preset='medium', fps=30, video_duration=0):
        """Delega a VideoExportManager si estÃ¡ disponible"""
        if self.export_manager:
            return self.export_manager.export_video_with_ffmpeg(
                video_clip, output_path, video_bitrate, preset, fps, video_duration
            )
        return False


    def _should_disable_cinematic_effects(self, storyboard_data, apply_cinematic,
                                          platform=None, visual_mode=None,
                                          transition_type=None, cinematic_preset=None):
        """Delega a VideoExportManager si estÃ¡ disponible"""
        if self.export_manager:
            return self.export_manager.should_disable_cinematic_effects(
                storyboard_data,
                apply_cinematic,
                self.log,
                platform=platform,
                visual_mode=visual_mode,
                transition_type=transition_type,
                cinematic_preset=cinematic_preset,
            )
        # Fallback: no desactivar si no se puede verificar
        return False


    def _map_transition_to_ffmpeg_xfade(self, transition_type):
        """
        Convierte el texto de transiciÃ³n de la UI a un nombre vÃ¡lido de xfade.
        Retorna None cuando la transiciÃ³n equivale a corte directo.
        """
        text = str(transition_type or "").strip().lower()
        if not text:
            return None

        no_transition_tokens = (
            "none",
            "ninguna",
            "direct cut",
            "corte directo",
            "sin transiciÃ³n",
            "sin transicion",
        )
        if any(token in text for token in no_transition_tokens):
            return None

        mapping = [
            ("data mosh", "pixelize"),
            ("rgb split", "distance"),
            ("digital glitch", "pixelize"),
            ("crossfade", "fade"),
            ("fade smooth", "fade"),
            ("fade suave", "fade"),
            ("fade to white", "fadewhite"),
            ("fade to black", "fadeblack"),
            ("fade", "fade"),
            ("zoom", "smoothup"),
            ("slide right", "slideright"),
            ("slide up", "slideup"),
            ("slide down", "slidedown"),
            ("slide", "slideleft"),
            ("blur", "fadeblack"),
            ("dissolve", "dissolve"),
            ("wipe right", "wiperight"),
            ("wipe up", "wipeup"),
            ("wipe down", "wipedown"),
            ("wipe", "wipeleft"),
            ("circle open", "circleopen"),
            ("circle close", "circleclose"),
            ("horizontal open", "horzopen"),
            ("horizontal close", "horzclose"),
            ("diagonal", "diagtl"),
            ("squeeze h", "squeezeh"),
            ("squeeze v", "squeezev"),
        ]
        for key, value in mapping:
            if key in text:
                return value

        # Fallback: si no se reconoce, usar fade (evita perder transiciÃ³n).
        return "fade"


    def _composite_on_screen_text(self, image_path: str, text: str, seg_index: int) -> str:
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.open(image_path).convert("RGBA")
            w, h = img.size
            draw = ImageDraw.Draw(img)

            label = text.upper().strip()
            max_w = int(w * 0.85)

            font_candidates = [
                "C:/Windows/Fonts/bahnschrift.ttf",
                "C:/Windows/Fonts/impact.ttf",
                "C:/Windows/Fonts/ariblk.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
            def _get_font(size):
                for p in font_candidates:
                    try:
                        return ImageFont.truetype(p, size)
                    except (OSError, IOError):
                        continue
                return ImageFont.load_default()

            chosen = None
            for sz in range(72, 28, -4):
                f = _get_font(sz)
                bbox = draw.textbbox((0, 0), label, font=f, stroke_width=max(2, sz // 24))
                if (bbox[2] - bbox[0]) <= max_w:
                    chosen = f
                    break
            if chosen is None:
                chosen = _get_font(32)

            cx = w // 2
            cy = int(h * 0.12)

            pill_bbox = draw.textbbox((cx, cy), label, font=chosen, anchor="mm",
                                     stroke_width=max(2, chosen.size // 24) if hasattr(chosen, 'size') else 2)
            pad = 16
            draw.rounded_rectangle(
                [pill_bbox[0] - pad, pill_bbox[1] - pad // 2,
                 pill_bbox[2] + pad, pill_bbox[3] + pad // 2],
                radius=12, fill=(0, 0, 0, 160),
            )

            stroke_w = max(2, 32 // 24)
            draw.text((cx, cy), label, font=chosen, fill="#FFFFFF", anchor="mm",
                      stroke_width=stroke_w, stroke_fill=(0, 0, 0, 200))

            out_path = os.path.join(os.path.dirname(image_path),
                                    f"segment_{seg_index + 1:03d}_ost.png")
            img.convert("RGB").save(out_path, "PNG")
            self.log(f"      [On-Screen] '{label}' composited on segment {seg_index + 1}")
            return out_path
        except Exception as exc:
            self.log(f"      [On-Screen] Failed for segment {seg_index + 1}: {exc}")
            return image_path


    def _reset_audio_qa(self):
        self._audio_qa = {}


    def _record_audio_qa(self, key, value):
        if getattr(self, '_audio_qa', None) is None:
            self._audio_qa = {}
        self._audio_qa[key] = value


    @staticmethod
    def _probe_media_duration(path):
        """Duracion en segundos via ffprobe (0.0 si no se puede medir)."""
        if not path or not os.path.exists(str(path)):
            return 0.0
        ffprobe_exe = shutil.which("ffprobe") or "ffprobe"
        try:
            import subprocess as _sp
            out = _sp.run(
                [ffprobe_exe, '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=nw=1:nk=1', str(path)],
                capture_output=True, timeout=20,
                creationflags=_sp.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            return float((out.stdout or b'').decode('utf-8', 'replace').strip() or 0.0)
        except Exception:
            return 0.0


    def log_hook_qa(self, storyboard_data=None):
        """QA DEL GANCHO: la primera frase hablada contra la regla medida (cifra o pregunta, la fecha despues)."""
        sb = storyboard_data if isinstance(storyboard_data, dict) else (getattr(self, '_current_storyboard_data', None) or {})
        segments = (sb.get('storyboard') or {}).get('segments') if isinstance(sb.get('storyboard'), dict) else sb.get('segments')
        segments = segments or []
        if not segments:
            return []
        seg0 = segments[0] if isinstance(segments[0], dict) else {}
        text = ''
        for key in ('narration', 'narration_text', 'text', 'voiceover', 'script'):
            if seg0.get(key):
                text = str(seg0[key]); break
        if not text.strip():
            return []
        try:
            from channel.channel_strategy import hook_report, first_sentence
            ok, verdicts = hook_report(text)
            sentence = first_sentence(text)
        except Exception as exc:
            self.log(f"  [--] QA del gancho no disponible: {exc}")
            return []
        self.log("")
        self.log("=" * 60)
        self.log("QA DEL GANCHO (primeros segundos)")
        self.log("=" * 60)
        self.log(f"  Primera frase: \"{sentence[:120]}\"")
        for v in verdicts:
            self.log(f"  {v}")
        return [v for v in verdicts if v.startswith('[FAIL]') or v.startswith('[WARN]')]


    def log_audio_qa(self, video_path=None, audio_path=None, subtitle_sync=None):
        """Imprime el resumen de QA de audio/sync y devuelve los problemas."""
        qa = dict(getattr(self, '_audio_qa', None) or {})
        problems = []
        try:
            hook_problems = self.log_hook_qa()
            problems.extend(f"gancho: {h}" for h in hook_problems if h.startswith('[FAIL]'))
        except Exception:
            pass
        lines = ["", "=" * 60, "QA DE AUDIO / SINCRONIA", "=" * 60]

        # 1. Auto-ducking: si falla, la musica se come la voz.
        if 'ducking_ok' not in qa:
            lines.append("  [--] Ducking: sin musica de fondo en este render")
        elif qa.get('ducking_ok'):
            lines.append(
                f"  [OK] Ducking aplicado | voz {qa.get('voice_dbfs', 0):.1f} dBFS "
                f"({qa.get('voice_gain_db', 0):+.1f} dB), musica {qa.get('music_gain_db', 0):+.1f} dB"
            )
            # La atenuacion TOTAL (cama + ducking) es la que decide si la musica
            # se escucha. Mirando solo la cama la mezcla parece bien y la musica
            # igual termina inaudible.
            _under = qa.get('music_under_voice_speech_db')
            if _under is not None:
                _verdict = "OK"
                if _under > 20:
                    _verdict = "FAIL"
                    problems.append(f"musica inaudible: {_under:.0f} dB bajo la voz")
                elif _under < 10:
                    _verdict = "FAIL"
                    problems.append(f"musica muy alta: solo {_under:.0f} dB bajo la voz")
                lines.append(
                    f"  [{_verdict}] Musica: cama a -{audio_mix_utils.MUSIC_UNDER_VOICE_DB:.0f} dB, "
                    f"~-{_under:.0f} dB bajo la voz con narracion (banda sana: 10-20)"
                )
        else:
            problems.append("auto-ducking fallo: la musica puede tapar la voz")
            lines.append(f"  [FAIL] Ducking FALLO -> {qa.get('ducking_error', 'sin detalle')}")

        # 2. SFX de transicion.
        if not qa.get('sfx_enabled', True):
            lines.append("  [--] SFX de transicion: desactivado por el usuario")
        elif qa.get('sfx_injected'):
            lines.append(f"  [OK] SFX de transicion: {qa['sfx_injected']} swoosh en la mezcla final")
        else:
            problems.append("el swoosh de transicion no se mezclo en ningun lado")
            lines.append(f"  [FAIL] SFX de transicion NO inyectado -> {qa.get('sfx_error', 'ninguna ruta lo mezclo')}")

        # 3. Cover frame: el padding de la voz mantiene todo en la misma linea de tiempo.
        expected = float(qa.get('cover_offset_expected_s', 0.0) or 0.0)
        applied = float(qa.get('cover_offset_applied_s', 0.0) or 0.0)
        if expected <= 0.01:
            lines.append("  [--] Cover frame: no hay, no hace falta desplazar la voz")
        elif abs(expected - applied) < 0.01:
            lines.append(f"  [OK] Cover frame: voz desplazada {applied:.2f}s")
        else:
            problems.append(f"el cover frame corre {expected:.2f}s pero la voz no se desplazo")
            lines.append(f"  [FAIL] Cover frame {expected:.2f}s SIN aplicar a la voz -> video corrido")

        # 4. Duracion video vs audio.
        v_dur = self._probe_media_duration(video_path)
        a_dur = self._probe_media_duration(audio_path)
        if v_dur > 0 and a_dur > 0:
            delta = abs(v_dur - a_dur)
            if delta <= 0.35:
                lines.append(f"  [OK] Duracion: video {v_dur:.2f}s vs audio {a_dur:.2f}s (dif {delta:.2f}s)")
            else:
                problems.append(f"video y audio difieren {delta:.2f}s")
                lines.append(f"  [FAIL] Duracion: video {v_dur:.2f}s vs audio {a_dur:.2f}s (dif {delta:.2f}s)")

        # 5. Subtitulos: modo de sync y cuantas palabras quedaron interpoladas.
        if subtitle_sync:
            mode = subtitle_sync.get('mode', 'desconocido')
            ratio = subtitle_sync.get('match_ratio')
            if ratio is None:
                lines.append(f"  [OK] Subtitulos: modo {mode}")
            elif ratio >= 0.85:
                lines.append(f"  [OK] Subtitulos: modo {mode}, {ratio:.0%} de palabras ancladas a Whisper")
            else:
                problems.append(f"solo {ratio:.0%} de las palabras quedaron ancladas a Whisper")
                lines.append(f"  [WARN] Subtitulos: modo {mode}, solo {ratio:.0%} ancladas -> riesgo de desfase")

        # 6. Camara: un zoompan a otro fps que el video repite cuadros (tiron).
        checked = int(qa.get('motion_frames_checked') or 0)
        if checked:
            from pipeline.cinematic_director import MAX_JUDDER_RATIO
            judder = int(qa.get('motion_judder_frames') or 0)
            if judder / float(checked) <= MAX_JUDDER_RATIO:
                lines.append(f"  [OK] Camara fluida: {judder}/{checked} cuadros repetidos sueltos en el primer movimiento")
            else:
                problems.append(f"la camara da tirones: {judder}/{checked} cuadros repetidos sueltos")
                lines.append(f"  [FAIL] Camara con tirones: {judder}/{checked} cuadros repetidos sueltos "
                             f"(zoompan a otro fps que el video?)")
        elif qa.get('motion_judder_error'):
            lines.append(f"  [WARN] Camara: no se pudo medir -> {qa['motion_judder_error']}")

        # 7. Composicion por escena. Una composicion que falla sale a pantalla
        # completa (el video no se rompe), pero es un error nuestro: se avisa.
        rendered = dict(qa.get('layouts_rendered') or {})
        if rendered:
            detalle = ", ".join(f"{segment_layouts.LAYOUT_LABELS.get(k, k).lower()} {v}"
                                for k, v in sorted(rendered.items()))
            lines.append(f"  [OK] Composicion: {sum(rendered.values())} escena(s) ({detalle})")
        failed_layouts = list(qa.get('layouts_failed') or [])
        if failed_layouts:
            problems.append(f"{len(failed_layouts)} composicion(es) fallaron y salieron a pantalla completa")
            lines.append(f"  [FAIL] Composicion: fallaron {', '.join(failed_layouts)} (escena:tipo) "
                         f"-> salieron a pantalla completa")
        if qa.get('pip_without_face'):
            lines.append(f"  [OK] Retrato flotante: {qa['pip_without_face']} escena(s) sin una cara clara "
                         f"fueron como punch-in")
        if qa.get('blur_fill_count'):
            lines.append(f"  [OK] Sin barras negras: {qa['blur_fill_count']} escena(s) con fondo desenfocado")

        # 9. Videos con cuadros congelados: se uso solo el tramo con movimiento.
        for item in qa.get('videos_unfrozen') or []:
            lines.append(f"  [OK] Video congelado corregido (se usa el tramo con movimiento): {item}")
        for name in qa.get('videos_still') or []:
            lines.append(f"  [WARN] Video casi quieto (menos de {video_motion.MIN_MOVING_SECONDS:.1f}s "
                         f"de movimiento), va como esta: {name}")

        # 8. Tomas 3D (Blender).
        if 'blender_shots_ok' in qa:
            hechas = int(qa.get('blender_shots_ok') or 0)
            if hechas:
                extra = []
                if qa.get('blender_shots_cached'):
                    extra.append(f"{qa['blender_shots_cached']} del cache")
                if qa.get('blender_seconds'):
                    extra.append(f"{float(qa['blender_seconds']) / 60:.1f} min de render")
                if qa.get('blender_environments'):
                    extra.insert(0, ", ".join(qa['blender_environments']))
                lines.append(f"  [OK] Tomas 3D (Blender): {hechas}" + (f" ({'; '.join(extra)})" if extra else ""))
            for err in qa.get('blender_shots_failed') or []:
                problems.append(f"una toma 3D salio como punch-in: {err}")
                lines.append(f"  [WARN] Toma 3D -> punch-in: {err}")

        lines.append("-" * 60)
        if problems:
            lines.append(f"  => {len(problems)} PROBLEMA(S): " + "; ".join(problems))
        else:
            lines.append("  => Audio y sincronia OK")
        lines.append("=" * 60)
        for ln in lines:
            self.log(ln)
        return problems


    def _resolve_transition_sfx_path(self, preferred=None):
        if preferred and os.path.exists(str(preferred)):
            return str(preferred)
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for candidate in (
            os.path.join(base, "transition_overlays", "swoosh.wav"),
            os.path.join(base, "swoosh.wav"),
        ):
            if os.path.exists(candidate):
                return candidate
        return None


    def _prepare_transition_overlay(self, ffmpeg_exe, temp_dir, width, height, fps,
                                    transition_duration, encoder, probe_duration, sp):
        """Deja el Film Burn escalado y acelerado a la duracion de transicion.

        Devuelve (ruta, duracion_real) o (None, 0.0) si no hay overlay usable.
        """
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "transition_overlays")
        if not os.path.isdir(base_dir):
            return None, 0.0

        origen = None
        for fname in sorted(os.listdir(base_dir)):
            if fname.lower().endswith((".mp4", ".mov", ".webm")):
                origen = os.path.join(base_dir, fname)
                break
        if not origen:
            return None, 0.0

        objetivo = max(0.15, min(float(transition_duration or 0.5), 1.5))
        dur_orig = probe_duration(origen, stream_selector='v:0', timeout=10) or 2.0
        speed = dur_orig / objetivo
        destino = os.path.join(temp_dir, "overlay_blend.mp4")
        cmd = [
            ffmpeg_exe, '-y', '-i', origen,
            '-vf', (f'setpts={1.0 / speed:.6f}*PTS,'
                    f'scale={width}:{height}:force_original_aspect_ratio=increase,'
                    f'crop={width}:{height},fps={fps}'),
            '-t', f'{objetivo:.3f}',
            '-c:v', encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
            '-r', str(fps), '-an', destino,
        ]
        try:
            res = sp.run(cmd, capture_output=True, text=True, timeout=120,
                         creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if res.returncode != 0 or not os.path.exists(destino):
                self.log(f"   [WARN] No se pudo preparar el overlay de transicion: "
                         f"{(res.stderr or '')[-160:]}")
                return None, 0.0
        except Exception as exc:
            self.log(f"   [WARN] No se pudo preparar el overlay de transicion: {exc}")
            return None, 0.0

        real = probe_duration(destino, stream_selector='v:0', timeout=10) or objetivo
        self.log(f"   [FX] Film Burn listo: {dur_orig:.2f}s -> {real:.2f}s "
                 f"(se mezcla sobre el clip, sin sumar duracion)")
        return destino, real


    def _add_hook_to_ass(self, ass_path, storyboard_data, res):
        """Texto de gancho (video_opening) como evento del mismo .ass de los subtitulos."""
        try:
            from pipeline.video_opening import append_hook_to_ass, get_hook_overlay
            hook = get_hook_overlay(storyboard_data)
            if not hook or not ass_path or not os.path.exists(ass_path):
                return False
            with open(ass_path, encoding='utf-8') as fh:
                text = fh.read()
            nuevo = append_hook_to_ass(text, hook, int(res[0]), int(res[1]))
            if nuevo != text:
                with open(ass_path, 'w', encoding='utf-8') as fh:
                    fh.write(nuevo)
                self._record_audio_qa('hook_overlay', hook['text'])
                self.log(f"   Texto de gancho: '{hook['text']}' ({hook['duration']:.1f}s, arriba, sobre la escena 1)")
            return True
        except Exception as exc:
            self.log(f"   [WARN] No se pudo agregar el texto de gancho: {exc}")
            return False


    def _burn_hook_only(self, video_path, storyboard_data, res):
        """Si el video sale sin subtitulos, el texto de gancho se quema solo."""
        try:
            from pipeline.video_opening import get_hook_overlay, standalone_hook_ass
            hook = get_hook_overlay(storyboard_data)
            if not hook or not video_path or not os.path.exists(str(video_path)):
                return False
            ass_path = str(video_path).replace('.mp4', '_hook.ass')
            with open(ass_path, 'w', encoding='utf-8') as fh:
                fh.write(standalone_hook_ass(hook, int(res[0]), int(res[1])))
            from pipeline.dynamic_subtitles_generator import DynamicSubtitleEngine
            out_hook = str(video_path).replace('.mp4', '_hook.mp4')
            if DynamicSubtitleEngine.burn_subtitles_with_ffmpeg(str(video_path), ass_path, out_hook,
                                                                video_width=int(res[0]), video_height=int(res[1])):
                os.replace(out_hook, str(video_path))
                self._record_audio_qa('hook_overlay', hook['text'])
                self.log(f"   Texto de gancho quemado sin subtitulos: '{hook['text']}'")
                return True
        except Exception as exc:
            self.log(f"   [WARN] No se pudo quemar el texto de gancho: {exc}")
        return False


    def _build_motion_filter(self, clip_data, frames, duration, size,
                             apply_cinematic, index, fps=30):
        """Filtro de movimiento (Ken Burns) para un clip de imagen.

        Con efectos cinematograficos activados usa los MISMOS presets que la
        ruta MoviePy (`CameraMovement`), elegidos por el texto del segmento, de
        modo que las dos rutas se vean igual. Sin ellos, un zoom-in suave.

        Antes esto era un zoompan fijo con la progresion escrita en funcion de
        `in`, que en una imagen fija no avanza nunca: el movimiento no existia.

        Todos los zoompan salen a `fps` (el del video). Sin eso salen a 25, el
        `fps=30` posterior repite un cuadro de cada seis y `-t` corta la camara
        al ~82% del recorrido.
        """
        width, height = int(size[0]), int(size[1])
        n = max(1, int(frames))
        rate = f"{float(fps):g}"

        # El cover frame es una PLACA DE TEXTO de 0.7s. Con zoompan el texto se
        # desplaza y escala en menos de un segundo: se ve como un salto, no como
        # un movimiento. Va quieto.
        if clip_data.get('is_cover'):
            return f"zoompan=z=1:x=0:y=0:d={n}:s={width}x{height}:fps={rate}"

        # Arranque nuevo (video_opening): cada estilo tiene un movimiento propio
        # y todos empiezan a moverse desde el cuadro 0.
        if clip_data.get('opening_style'):
            from pipeline.video_opening import opening_motion_filter
            return opening_motion_filter(
                n, width, height, str(clip_data['opening_style']),
                float(clip_data.get('opening_motion_amount') or 0) or None,
                fps=fps,
            )

        # Compatibilidad con storyboards hook_overlay_v1 anteriores.
        if clip_data.get('opening_push_in'):
            from pipeline.video_opening import push_in_filter
            return push_in_filter(n, width, height, float(clip_data['opening_push_in']), fps=fps)

        if apply_cinematic and CINEMATIC_AVAILABLE:
            try:
                cinematic_plan = clip_data.get('cinematic_plan')
                if cinematic_plan:
                    from pipeline.cinematic_director import build_ffmpeg_motion_filter, plan_summary
                    self._record_audio_qa(
                        'cinematic_plan_%d' % index, plan_summary(cinematic_plan)
                    )
                    return build_ffmpeg_motion_filter(
                        cinematic_plan, n, (width, height), fps=fps
                    )
                from pipeline.cinematic_effects import CameraMovement, ContextDetector
                texto = str(clip_data.get('segment_text') or '')
                movimiento = ContextDetector.suggest_movement(texto, float(duration))
                posiciones = CameraMovement.calculate_positions(
                    movimiento, (width, height), zoom_factor=1.2
                )
                self._record_audio_qa(
                    'motion_%d' % index, getattr(movimiento, 'value', str(movimiento))
                )
                return CameraMovement.build_ffmpeg_motion_filter(
                    posiciones, n, (width, height), fps=fps
                )
            except Exception as exc:
                self.log(f"      [WARN] No se pudo armar el movimiento cinematografico: {exc}")

        # Fallback: zoom-in lento y centrado, con la progresion en `on`.
        z0, z1 = 1.0, self.DEFAULT_MOTION_ZOOM
        p = "0" if n <= 1 else f"(on/{n - 1})"
        return (
            f"zoompan=z='{z0:.4f}+({z1 - z0:.4f})*{p}'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={n}:s={width}x{height}:fps={rate}"
        )


    @staticmethod
    def _layout_plan_for_clip(seg, resolve_media):
        """Copia del `layout_plan` de la escena con la media extra resuelta a rutas que existen."""
        plan = seg.get('layout_plan')
        if not isinstance(plan, dict):
            return None
        plan = dict(plan)
        extra = [resolve_media(p) for p in (plan.get('extra_media') or [])]
        plan['extra_media'] = [p for p in extra if p]
        return plan


    def _render_blender_shots(self, clips, size, blender_exe=None, quality='normal', fps=30,
                              storyboard_data=None, environment='auto'):
        """Renderiza las escenas marcadas como toma 3D y las cambia por su mp4.

        El ambiente sale del timeline (si se eligio a mano), del Studio, o de la
        escena (`choose_environment`): TV de tubo para videos, tablero para
        misterios, periodico para anuncios, mesa con fotos para el resto. Si
        Blender no esta o falla, la escena cae a punch-in (FFmpeg, misma imagen o
        video): una toma 3D perdida no puede costar el video ni dejarla en negro.
        """
        pending = [c for c in clips
                   if segment_layouts.normalize_layout((c.get('layout_plan') or {}).get('layout')) == 'blender_3d']
        if not pending:
            return
        from pipeline import blender_shots, front_page
        cache_dir = os.path.join(str(self.generated_media_dir), 'blender_shots')
        done, cached, failed, seconds, envs = 0, 0, [], 0.0, []
        for clip in pending:
            plan = dict(clip['layout_plan'])
            main = str(clip.get('filename') or '')
            is_video = segment_layouts.is_video_path(main)
            chosen = plan.get('environment') if plan.get('environment') not in (None, '', 'auto') else environment
            env = segment_layouts.choose_environment(clip.get('segment_text'), is_video, chosen)
            label = segment_layouts.BLENDER_ENVIRONMENTS.get(env, env).lower()
            if not blender_exe:
                outcome = {'ok': False, 'error': 'tomas 3D desactivadas o Blender no instalado'}
            else:
                try:
                    duration = float(clip['duration'])
                    if env == 'crt_tv':
                        images = [blender_shots.prepare_screen_video(main, duration, fps, cache_dir)
                                  if is_video else main]
                    else:
                        hero = main
                        if is_video:
                            # Nombre estable y sin re-extraer: si no, el cache de la toma
                            # 3D fallaria en cada re-ensamblaje.
                            import hashlib
                            os.makedirs(cache_dir, exist_ok=True)
                            hero = os.path.join(
                                cache_dir, f"grab_{hashlib.sha1(main.encode('utf-8')).hexdigest()[:12]}.png")
                            if not os.path.exists(hero):
                                segment_layouts.frame_grab(main, hero,
                                                           video_motion.analyze(main).get('start', 0.0) + 0.5)
                        others = [s['path'] for s in (clip.get('layout_sources') or [])
                                  if not s.get('detail') and segment_layouts.is_image_path(s.get('path'))]
                        if env == 'newspaper':
                            texts = front_page.front_page_texts(storyboard_data or {}, clip.get('segment_text'),
                                                                plan.get('tag'))
                            images = [front_page.cached_front_page(cache_dir, hero, texts)]
                        else:
                            images = [hero] + others
                    self.log(f"   [3D] Toma Blender ({label}) para {os.path.basename(main)} "
                             f"({duration:.1f}s)")
                    outcome = blender_shots.render_shot(
                        env, images, duration=duration, size=size, fps=fps, cache_dir=cache_dir,
                        quality=quality, blender_exe=blender_exe, log=self.log,
                    )
                except Exception as exc:
                    outcome = {'ok': False, 'error': str(exc)}
            if outcome.get('ok'):
                clip['filename'] = outcome['path']
                plan.update(rendered='blender', environment=env)
                done += 1
                envs.append(label)
                cached += 1 if outcome.get('cached') else 0
                seconds += float(outcome.get('seconds') or 0)
                self.log(f"   [OK] Toma 3D lista ({label}){' (reusada del cache)' if outcome.get('cached') else ''}: "
                         f"{os.path.basename(outcome['path'])}")
            else:
                plan.update(layout=segment_layouts.BLENDER_FALLBACK_LAYOUT, fallback_from='blender_3d')
                failed.append(str(outcome.get('error') or 'error desconocido'))
                self.log(f"   [WARN] Toma 3D no disponible ({failed[-1]}): va como punch-in")
            clip['layout_plan'] = plan
        self._record_audio_qa('blender_shots_ok', done)
        self._record_audio_qa('blender_shots_cached', cached)
        self._record_audio_qa('blender_shots_failed', failed)
        self._record_audio_qa('blender_seconds', round(seconds, 1))
        self._record_audio_qa('blender_environments', envs)


    @staticmethod
    def _probe_media_size(path, ffprobe_exe=None, is_video=False):
        """(ancho, alto) del medio, o None si no se puede medir."""
        try:
            if not is_video:
                with Image.open(path) as im:
                    return im.size
            import subprocess as _sp
            out = _sp.run(
                [ffprobe_exe or shutil.which("ffprobe") or "ffprobe", '-v', 'error',
                 '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                 '-of', 'csv=p=0:s=x', str(path)],
                capture_output=True, text=True, timeout=20,
                creationflags=_sp.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            w, h = (int(v) for v in (out.stdout or '').strip().splitlines()[0].split('x')[:2])
            return (w, h) if w > 0 and h > 0 else None
        except Exception:
            return None


    def _layout_clip_command(self, ffmpeg_exe, item, img_path, duration, size, fps,
                             temp_dir, index, post_filters, overlay_path, encoder, clip_out,
                             interpolate=False):
        """Comando de FFmpeg de un clip con composicion (ver `segment_layouts`).

        `post_filters` (look, fundido) van detras de la composicion, igual que en
        un clip normal; `overlay_path` es el Film Burn si el clip abre escena.
        Los videos (escena o paneles) usan solo su tramo con movimiento.
        """
        plan = item.get('layout_plan') or {}
        sources = item.get('layout_sources') or []
        windows = {}
        for path in [img_path] + [s.get('path') for s in sources]:
            if segment_layouts.is_video_path(path) and path not in windows:
                windows[path] = video_motion.input_window(
                    video_motion.analyze(path, ffmpeg_exe), float(duration))
        layout = segment_layouts.normalize_layout(plan.get('layout'))
        tag = str(plan.get('tag') or '').strip().upper()
        common = dict(
            main=img_path, sources=sources, duration=float(duration), size=size, fps=fps,
            temp_dir=temp_dir, index=index,
            main_size=self._probe_media_size(img_path, None, segment_layouts.is_video_path(img_path)),
            video_windows=windows, interpolate=interpolate,
        )
        try:
            spec = segment_layouts.build_layout_graph(
                layout, tag=tag, require_face=(plan.get('reason') == 'person' or bool(tag)), **common)
        except segment_layouts.NoFaceFound as no_face:
            # Retrato de una persona sin una cara clara: punch-in con la misma escena,
            # mejor que un circulo mostrando un hombro o una pared.
            self.log(f"      [OK] Retrato flotante sin cara clara ({no_face}): va como punch-in")
            self._record_audio_qa('pip_without_face', int((getattr(self, '_audio_qa', None) or {})
                                                          .get('pip_without_face', 0)) + 1)
            layout = 'punch_in'
            spec = segment_layouts.build_layout_graph(layout, **common)
        item['_layout_used'] = layout
        width, height = int(size[0]), int(size[1])
        post = ','.join(f for f in post_filters if f) or 'null'
        graph = spec['graph']
        cmd = [ffmpeg_exe, '-y'] + segment_layouts.input_args(spec)
        if overlay_path:
            cmd += ['-i', overlay_path]
            graph += (
                f";[lay]{post}[pre];"
                f"[{len(spec['inputs'])}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps={fps},setpts=PTS-STARTPTS[ovr];"
                f"[pre][ovr]blend=all_mode=screen:shortest=0:repeatlast=0[v]"
            )
        else:
            graph += f";[lay]{post}[v]"
        return cmd + [
            '-t', str(duration), '-filter_complex', graph, '-map', '[v]',
            '-c:v', encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
            '-r', str(fps), '-g', '30', clip_out,
        ]


    def _measure_motion_judder(self, ffmpeg_exe, img_path, duration, vf, sp):
        """Cuenta cuadros repetidos de un clip con camara para el QA.

        Corre la MISMA cadena de filtros del clip pero sin codificar: un
        encoder por hardware podria disimular los duplicados y dar un OK falso.
        """
        try:
            from pipeline.cinematic_director import count_judder_frames
            proc = sp.run(
                [ffmpeg_exe, '-v', 'error', '-i', img_path, '-t', str(duration),
                 '-vf', vf, '-f', 'framemd5', '-'],
                capture_output=True, text=True, timeout=180,
                creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            if proc.returncode != 0:
                self._record_audio_qa('motion_judder_error', (proc.stderr or '')[-160:])
                return
            aislados, total = count_judder_frames(proc.stdout)
            self._record_audio_qa('motion_judder_frames', aislados)
            self._record_audio_qa('motion_frames_checked', total)
        except Exception as exc:
            self._record_audio_qa('motion_judder_error', str(exc))


    def _assemble_direct_ffmpeg(self, clips_data, audio_file_path, output_path,
                                resolution, fps=30, transition_type='None (Direct Cut)',
                                transition_duration=0.5,
                                enable_transition_sfx=True,
                                transition_sfx_path=None,
                                apply_cinematic=False,
                                cinematic_preset='auto'):
        """
        Ensambla video directamente con FFmpeg desde imÃ¡genes y/o videos.
        Mucho mÃ¡s rÃ¡pido y robusto que MoviePy.
        Evita CompositeVideoClip, pipes, y problemas de seek.

        Args:
            clips_data: Lista de dicts con 'filename', 'timestamp_start', 'duration'
            audio_file_path: Ruta al archivo de audio final
            output_path: Ruta de salida del video
            resolution: Tupla (width, height)
            fps: Frames por segundo
            transition_type: Tipo de transiciÃ³n seleccionada en UI
            transition_duration: DuraciÃ³n en segundos para la transiciÃ³n

        Returns:
            bool: True si el ensamblaje fue exitoso
        """
        import subprocess as sp
        import time as _time

        ffmpeg_exe = shutil.which("ffmpeg")
        if not ffmpeg_exe:
            # Fallback a ruta conocida en Windows
            if os.name == "nt":
                for p in [
                    r"C:\Users\esteban.navarro\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe",
                ]:
                    if os.path.exists(p):
                        ffmpeg_exe = p
                        break
            if not ffmpeg_exe:
                self.log("   â Œ FFmpeg no encontrado")
                return False

        # Detectar el mejor codificador disponible (GPU/CPU)
        optimal_encoder = get_optimal_h264_encoder(ffmpeg_exe)
        self.log(f"   [INFO] Usando codificador de video: {optimal_encoder}")

        width, height = resolution
        try:
            interpolation_fps = max(1, int(round(float(fps))))
        except Exception:
            interpolation_fps = 30
        temp_dir = os.path.join("auto_videos", "temp", "ffmpeg_direct")
        os.makedirs(temp_dir, exist_ok=True)

        # Resolver ffprobe de forma robusta (sin depender de mayÃºsculas en ffmpeg.EXE)
        ffprobe_exe = shutil.which("ffprobe")
        if not ffprobe_exe and ffmpeg_exe:
            ffmpeg_dir = os.path.dirname(ffmpeg_exe)
            for candidate in ("ffprobe.exe", "ffprobe.EXE", "ffprobe"):
                probe_path = os.path.join(ffmpeg_dir, candidate)
                if os.path.exists(probe_path):
                    ffprobe_exe = probe_path
                    break

        def _probe_duration_seconds(path, stream_selector=None, timeout=15):
            """Obtiene duraciÃ³n en segundos vÃ­a ffprobe (stream o format)."""
            if not ffprobe_exe or not path or not os.path.exists(path):
                return 0.0
            try:
                base_cmd = [ffprobe_exe, "-v", "error"]
                if stream_selector:
                    out = sp.run(
                        base_cmd + [
                            "-select_streams", stream_selector,
                            "-show_entries", "stream=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1",
                            path,
                        ],
                        capture_output=True, text=True, timeout=timeout,
                        creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    if out.returncode == 0 and (out.stdout or "").strip():
                        val = float((out.stdout or "").strip().splitlines()[0].strip())
                        if val > 0:
                            return val

                out_fmt = sp.run(
                    base_cmd + [
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        path,
                    ],
                    capture_output=True, text=True, timeout=timeout,
                    creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if out_fmt.returncode == 0 and (out_fmt.stdout or "").strip():
                    return max(0.0, float((out_fmt.stdout or "").strip().splitlines()[0].strip()))
            except Exception:
                pass
            return 0.0

        @lru_cache(maxsize=32)
        def _ffmpeg_supports_filter(filter_name, timeout=10):
            """Verifica si el binario actual de FFmpeg soporta un filtro dado."""
            key = str(filter_name or "").strip().lower()
            if not key or not ffmpeg_exe:
                return False

            try:
                result = sp.run(
                    [ffmpeg_exe, "-hide_banner", "-filters"],
                    capture_output=True, text=True, timeout=timeout,
                    creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode != 0:
                    return False

                filters_output = f"{result.stdout or ''}\n{result.stderr or ''}"
                for line in filters_output.splitlines():
                    tokens = line.strip().split()
                    if len(tokens) >= 2 and tokens[1].lower() == key:
                        return True
            except Exception:
                pass

            return False

        # Ajustar duraciones para que el video cubra todo el audio (evita corte en Ãºltimos segmentos)
        audio_duration_sec = 0.0
        if os.path.exists(audio_file_path):
            audio_duration_sec = _probe_duration_seconds(audio_file_path, timeout=15)
            # Fallback: duraciÃ³n con pydub si ffprobe fallÃ³
            if audio_duration_sec <= 0 and PYDUB_AVAILABLE:
                try:
                    seg = AudioSegment.from_file(audio_file_path)
                    audio_duration_sec = len(seg) / 1000.0
                except Exception:
                    pass
        # Trabajar sobre una copia para no mutar el original
        clips_data = [dict(x) for x in clips_data]
        total_video_duration = sum(max(0, item.get('duration', 0)) for item in clips_data)
        min_clip_duration = 0.25  # minimo por clip para no generar clips de 0s
        for item in clips_data:
            d = item.get('duration', 0)
            if d is None or d < min_clip_duration:
                item['duration'] = min_clip_duration
        # Resolver transicion para FFmpeg directo
        is_overlay_transition = any(
            kw in (transition_type or '').lower()
            for kw in ("film burn", "light leak", "overlay")
        )
        xfade_transition = None if is_overlay_transition else self._map_transition_to_ffmpeg_xfade(transition_type)
        use_transitions = bool(xfade_transition and len(clips_data) > 1)
        try:
            transition_duration = float(transition_duration)
        except Exception:
            transition_duration = 0.5
        transition_duration = max(0.05, min(2.0, transition_duration))
        transition_overlap_sec = (len(clips_data) - 1) * transition_duration if use_transitions else 0.0
        total_video_duration = sum(item['duration'] for item in clips_data)
        effective_video_duration = total_video_duration - transition_overlap_sec
        if audio_duration_sec > 0 and effective_video_duration < audio_duration_sec and clips_data:
            deficit = audio_duration_sec - effective_video_duration
            
            # Distribute deficit proportionally
            for item in clips_data:
                orig_dur = item.get('duration', 0)
                if total_video_duration > 0:
                    proportion = orig_dur / total_video_duration
                    item['duration'] = orig_dur + (deficit * proportion)
                else:
                    item['duration'] = orig_dur + (deficit / len(clips_data))
                    
            if use_transitions:
                self.log(
                    f"   [INFO] Distribuido deficit de +{deficit:.1f}s proporcionalmente "
                    f"(compensando {transition_overlap_sec:.1f}s de solape por transiciones)"
                )
            else:
                self.log(
                    f"   [INFO] Distribuido deficit de +{deficit:.1f}s proporcionalmente "
                    f"para igualar duracion del audio ({audio_duration_sec:.1f}s)"
                )
        elif audio_duration_sec > 0 and effective_video_duration >= audio_duration_sec:
            if use_transitions:
                self.log(
                    f"   [INFO] Duracion efectiva con transiciones ({effective_video_duration:.1f}s) "
                    f">= audio ({audio_duration_sec:.1f}s), sin ajuste"
                )
            else:
                self.log(
                    f"   [INFO] Duracion video ({total_video_duration:.1f}s) "
                    f">= audio ({audio_duration_sec:.1f}s), sin ajuste"
                )

        # Limpiar clips temporales previos
        for f in os.listdir(temp_dir):
            if f.startswith("c_") and f.endswith(".mp4"):
                try:
                    os.remove(os.path.join(temp_dir, f))
                except Exception:
                    pass

        # FASE 1: Crear clips individuales desde imÃ¡genes
        total_clips = len(clips_data)
        # --- Overlay de transicion (Film Burn) preparado ANTES de los clips ---
        # Se mezcla DENTRO del clip entrante (screen blend sobre sus primeros
        # cuadros) en vez de insertarse como clip aparte. Insertarlo sumaba su
        # duracion al video: con 8 cortes de 0.70s el video terminaba 5.6s mas
        # largo que el audio y todo el visual quedaba corrido.
        overlay_blend_path = None
        overlay_blend_dur = 0.0
        if is_overlay_transition and len(clips_data) > 1:
            overlay_blend_path, overlay_blend_dur = self._prepare_transition_overlay(
                ffmpeg_exe, temp_dir, width, height, fps,
                transition_duration, optimal_encoder, _probe_duration_seconds, sp,
            )

        # Fuentes visuales por clip, para detectar cambios de escena.
        _clip_sources = [
            os.path.normcase(os.path.abspath(str(it.get('filename') or '')))
            for it in clips_data
        ]

        self.log(f"\n   ðŸ“¹ Fase 1/3: Creando {total_clips} clips ({width}x{height})...")
        start_time = _time.time()
        clips = []
        clip_durations = []
        overlays_blended = 0
        # Indices de clip donde arranca una escena nueva. Los usa el SFX de
        # transicion: antes se deducian de los clips 'overlay_transition'
        # insertados, que ya no existen desde que el Film Burn se mezcla.
        escenas_nuevas = []
        layouts_rendered = {}
        layouts_failed = []
        blur_fill_count = 0
        videos_unfrozen = []
        videos_still = []
        supports_minterpolate = _ffmpeg_supports_filter("minterpolate")
        minterpolate_warning_logged = False

        for i, item in enumerate(clips_data):
            try:
                img_path = item['filename']
                duration = item['duration']
                clip_out = os.path.join(temp_dir, f"c_{i+1:03d}.mp4")

                # Pre-concatenar cadenas vsplit antes de cualquier procesamiento
                vsplit_chain = item.get('_vsplit_chain')
                if vsplit_chain:
                    chain_list = os.path.join(temp_dir, f"vchain_{i+1:03d}.txt")
                    chain_out  = os.path.join(temp_dir, f"vcat_{i+1:03d}.mp4")
                    with open(chain_list, 'w', encoding='utf-8') as _cf:
                        for _cp in vsplit_chain:
                            _cf.write("file " + chr(39) + _cp.replace(chr(92), chr(47)) + chr(39) + chr(10))
                    _cat = sp.run(
                        [ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0',
                         '-i', chain_list, '-c', 'copy', chain_out],
                        capture_output=True, text=True, timeout=180,
                        creationflags=sp.CREATE_NO_WINDOW if os.name == "nt" else 0
                    )
                    if _cat.returncode == 0 and os.path.exists(chain_out) and os.path.getsize(chain_out) > 0:
                        img_path = chain_out
                        self.log(f"      Vsplit chain {len(vsplit_chain)} clips -> {os.path.basename(chain_out)}")
                    else:
                        self.log(f"      Vsplit chain concat fallo: {(_cat.stderr or '')[-80:]}")

                if not os.path.exists(img_path):
                    self.log(f"      âš ï¸  Archivo no existe: {os.path.basename(img_path)}")
                    continue

                is_video = img_path.lower().endswith(('.gif', '.mp4', '.mov', '.avi', '.webm', '.mkv'))

                # Filtro base: el medio al cuadro completo. Si su aspecto es muy
                # distinto (foto horizontal en un short) va sobre un fondo de si
                # mismo desenfocado, en vez de las barras negras de antes.
                src_size = self._probe_media_size(img_path, ffprobe_exe, is_video)
                if segment_layouts.needs_blur_fill(src_size, (width, height)):
                    blur_fill_count += 1
                vf = f"{segment_layouts.frame_fit_filter(src_size, (width, height))},fps={fps}"
                cinematic_look = ''
                if apply_cinematic and item.get('cinematic_plan'):
                    try:
                        from pipeline.cinematic_director import build_ffmpeg_look_filter
                        cinematic_look = build_ffmpeg_look_filter(
                            item.get('cinematic_plan'), float(duration), cinematic_preset
                        )
                    except Exception as look_exc:
                        self.log(f"      [WARN] Look cinematografico omitido: {look_exc}")

                # Fade-out del ultimo clip. Se calcula aca pero se agrega DESPUES
                # del zoompan: en una imagen fija el input tiene un solo cuadro en
                # t=0, asi que un fade con `st` de varios segundos nunca dispara si
                # va antes del zoompan (que es quien genera la linea de tiempo).
                fade_suffix = ''
                if i == total_clips - 1 and duration > 2:
                    fade_duration = min(4.0, duration - 0.5)  # Fade de hasta 4s, dejando al menos 0.5s
                    fade_start = max(0, duration - fade_duration)
                    fade_suffix = f',fade=t=out:st={fade_start:.2f}:d={fade_duration:.2f}'
                    self.log(f"      ðŸŽ¬ Fade-out de video: {fade_duration:.1f}s al final del Ãºltimo clip")

                # Cadena de movimiento de un clip con camara, para medir el tiron
                # en el QA (sin look ni Film Burn, que taparian los repetidos).
                medir_movimiento = None
                layout_fallback_cmd = None
                layout = None
                # El Film Burn va MEZCLADO sobre el arranque del clip cuando
                # este inicia una escena nueva (ver mas abajo).
                inicia_escena = (
                    not is_video and overlay_blend_path is not None and i > 0
                    and _clip_sources[min(i, len(_clip_sources) - 1)]
                    != _clip_sources[min(i - 1, len(_clip_sources) - 1)]
                )
                if is_video:
                    if cinematic_look:
                        vf += f',{cinematic_look}'
                    vf += fade_suffix
                    # Solo el tramo que se mueve: un video con cuadros congelados
                    # (pasa en material real) salia como un segundo de accion y
                    # despues una foto quieta. Si el tramo es mas corto que la
                    # escena, se ralentiza para cubrirla (sin loops visibles).
                    motion = video_motion.analyze(img_path, ffmpeg_exe)
                    if not motion.get('duration'):
                        motion['duration'] = _probe_duration_seconds(img_path, stream_selector='v:0', timeout=10)
                    v_start, v_len, slow_factor = video_motion.input_window(motion, duration)
                    if motion.get('usable'):
                        videos_unfrozen.append(
                            f"{os.path.basename(img_path)[:40]}: {motion['start']:.1f}-{motion['end']:.1f}s "
                            f"de {motion['duration']:.1f}s")
                        self.log(f"      [OK] Video con cuadros congelados: se usa {motion['start']:.2f}-"
                                 f"{motion['end']:.2f}s de {motion['duration']:.2f}s")
                    elif motion.get('frozen'):
                        videos_still.append(os.path.basename(img_path)[:40])
                    original_duration = v_len
                    if slow_factor > 1.0:
                        if supports_minterpolate and slow_factor > 1.05:
                            vf = (
                                f'setpts={slow_factor:.6f}*PTS,'
                                f'minterpolate=fps={interpolation_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,'
                                f'{vf}'
                            )
                            self.log(
                                f"      ðŸ ¢ Video corto: {original_duration:.2f}s â†’ {duration:.2f}s "
                                f"(ralentizado x{slow_factor:.2f} + interpolaciÃ³n de cuadros)"
                            )
                        else:
                            vf = f'setpts={slow_factor:.6f}*PTS,{vf}'
                            if slow_factor > 1.05 and not supports_minterpolate and not minterpolate_warning_logged:
                                self.log(
                                    "      â„¹ï¸  FFmpeg no trae 'minterpolate'; usando ralentizado bÃ¡sico "
                                    "sin cuadros intermedios."
                                )
                                minterpolate_warning_logged = True
                            self.log(
                                f"      ðŸ ¢ Video corto: {original_duration:.2f}s â†’ {duration:.2f}s "
                                f"(ralentizado x{slow_factor:.2f})"
                            )

                    # Construir comando para video (sin loop; recorta o estira segÃºn corresponda)
                    cmd = [
                        ffmpeg_exe, '-y',
                        '-ss', f"{v_start:.3f}", '-t', f"{v_len:.3f}",
                        '-i', img_path,
                        '-t', str(duration),
                        '-vf', vf,
                        '-c:v', optimal_encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
                        '-g', '30',  # Keyframe cada 1s para seek limpio
                        '-r', str(fps),  # Forzar framerate consistente
                        '-an',
                        clip_out
                    ]
                else:
                    # Ken Burns / efectos cinematograficos resueltos DENTRO de
                    # FFmpeg (C, multihilo) en vez de cuadro a cuadro en Python.
                    from pipeline.cinematic_director import clip_motion_frames
                    frames = clip_motion_frames(duration, fps)
                    motion_vf = self._build_motion_filter(
                        clip_data=item,
                        frames=frames,
                        duration=float(duration),
                        size=(width, height),
                        apply_cinematic=apply_cinematic,
                        index=i,
                        fps=fps,
                    )
                    kb_vf = f"{vf},{motion_vf},fps={fps}"
                    if 'on/' in motion_vf:
                        # Se mide ANTES del look: su grano (`noise allf=t`)
                        # cambia todos los cuadros y esconderia los repetidos.
                        medir_movimiento = kb_vf
                    if cinematic_look:
                        kb_vf += f',{cinematic_look}'
                    kb_vf += fade_suffix

                    # Film Burn: `repeatlast=0` corta el blend al terminar el
                    # overlay y deja pasar el clip sin tocar; asi el efecto no
                    # alarga el video ni se queda congelado encima.
                    if inicia_escena:
                        filtro = (
                            f"[0:v]{kb_vf}[base];"
                            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                            f"crop={width}:{height},fps={fps},setpts=PTS-STARTPTS[ovr];"
                            f"[base][ovr]blend=all_mode=screen:shortest=0:repeatlast=0[v]"
                        )
                        cmd = [
                            ffmpeg_exe, '-y',
                            '-i', img_path,
                            '-i', overlay_blend_path,
                            '-t', str(duration),
                            '-filter_complex', filtro,
                            '-map', '[v]',
                            '-c:v', optimal_encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
                            '-r', str(fps), '-g', '30',
                            clip_out
                        ]
                        overlays_blended += 1
                        escenas_nuevas.append(i)
                    else:
                        cmd = [
                            ffmpeg_exe, '-y',
                            '-i', img_path,
                            '-t', str(duration),
                            '-vf', kb_vf,
                            '-c:v', optimal_encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
                            '-r', str(fps), '-g', '30',
                            clip_out
                        ]

                # Composicion (pantalla dividida, retrato, punch-in...), tambien
                # sobre escenas de video. El clip de arriba (Ken Burns o video a
                # pantalla completa) queda de respaldo: si la composicion falla,
                # la escena sale a pantalla completa y no en negro.
                layout = segment_layouts.normalize_layout((item.get('layout_plan') or {}).get('layout'))
                if layout in segment_layouts.FFMPEG_LAYOUTS and not item.get('is_cover'):
                    try:
                        layout_cmd = self._layout_clip_command(
                            ffmpeg_exe, item, img_path, duration, (width, height), fps,
                            temp_dir, i, [cinematic_look, fade_suffix.lstrip(',')],
                            overlay_blend_path if inicia_escena else None,
                            optimal_encoder, clip_out, interpolate=supports_minterpolate,
                        )
                        layout_fallback_cmd, cmd = cmd, layout_cmd
                        layout = item.get('_layout_used', layout)
                        medir_movimiento = None
                    except Exception as layout_exc:
                        self.log(f"      [WARN] Composicion '{layout}' omitida: {layout_exc}")
                        layouts_failed.append(f"{i + 1}:{layout}")

                tipo = "video" if is_video else "img"
                if layout_fallback_cmd:
                    tipo = segment_layouts.LAYOUT_LABELS.get(layout, layout).lower()
                self.log(f"      [{i+1}/{total_clips}] Codificando seg {i+1} ({tipo}, {duration:.1f}s)...")
                clip_start = _time.time()
                try:
                    result = sp.run(cmd, capture_output=True, text=True, timeout=1200,
                                    creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    if layout_fallback_cmd and result.returncode != 0:
                        self.log(f"      [WARN] Composicion '{layout}' fallo, va a pantalla completa: "
                                 f"{(result.stderr or '')[-200:]}")
                        layouts_failed.append(f"{i + 1}:{layout}")
                        result = sp.run(layout_fallback_cmd, capture_output=True, text=True, timeout=1200,
                                        creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    elif layout_fallback_cmd:
                        layouts_rendered[layout] = layouts_rendered.get(layout, 0) + 1
                    clip_elapsed = _time.time() - clip_start

                    if result.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 500:
                        clips.append(clip_out)
                        actual_clip_duration = _probe_duration_seconds(clip_out, stream_selector='v:0', timeout=10)
                        clip_durations.append(actual_clip_duration if actual_clip_duration > 0 else float(duration))
                        self.log(f"      [{i+1}/{total_clips}] OK ({clip_elapsed:.1f}s)")
                        if medir_movimiento and 'motion_frames_checked' not in (getattr(self, '_audio_qa', None) or {}):
                            self._measure_motion_judder(ffmpeg_exe, img_path, duration, medir_movimiento, sp)
                    else:
                        stderr_short = (result.stderr or '')
                        self.log(f"      [{i+1}/{total_clips}] ERROR ({clip_elapsed:.1f}s): {stderr_short}")
                        raise RuntimeError("FFmpeg returncode no es 0 o archivo corrupto")
                        
                except Exception as e:
                    clip_elapsed = _time.time() - clip_start
                    self.log(f"      [{i+1}/{total_clips}] FALLO en seg {i+1} ({clip_elapsed:.1f}s): {e}")
                    # MEJORA: Fallback de video negro para evitar desincronizacion
                    try:
                        self.log(f"      [{i+1}/{total_clips}] Generando clip de fallback negro para mantener sincronia...")
                        fallback_cmd = [
                            ffmpeg_exe, '-y',
                            '-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}:r={fps}:d={duration}',
                            '-c:v', optimal_encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
                            clip_out
                        ]
                        sp.run(fallback_cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=60, creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                        if os.path.exists(clip_out):
                            clips.append(clip_out)
                            clip_durations.append(float(duration))
                            self.log(f"      [{i+1}/{total_clips}] Fallback generado exitosamente.")
                    except Exception as fallback_e:
                        self.log(f"      [{i+1}/{total_clips}] Error crítico en fallback: {fallback_e}")
            except Exception as item_e:
                self.log(f"      [{i+1}/{total_clips}] Error crítico procesando segmento entero: {item_e}")

            # Resumen cada 25 clips o al final
            if (i + 1) % 25 == 0 or (i + 1) == total_clips:
                elapsed = _time.time() - start_time
                pct = int((i + 1) / total_clips * 100)
                avg = elapsed / (i + 1)
                remaining = avg * (total_clips - (i + 1))
                self.log(
                    f"      --- [{pct}%] {i+1}/{total_clips} | "
                    f"Transcurrido: {elapsed:.0f}s | Restante estimado: {remaining:.0f}s ---"
                )

        self._record_audio_qa('layouts_rendered', dict(layouts_rendered))
        self._record_audio_qa('layouts_failed', list(layouts_failed))
        self._record_audio_qa('blur_fill_count', blur_fill_count)
        self._record_audio_qa('videos_unfrozen', list(videos_unfrozen))
        self._record_audio_qa('videos_still', list(videos_still))

        if not clips:
            self.log("   âŒ No se pudo crear ningÃºn clip")
            return False

        self.log(f"   âœ… {len(clips)}/{total_clips} clips creados")

        if overlays_blended:
            self.log(f"   [OK] Film Burn mezclado en {overlays_blended} cambio(s) de escena "
                     f"(sin alterar la duracion)")

        # FASE 1.5: Insertar clips de overlay transition (film burn) entre escenas.
        # Solo como respaldo: si el blend por clip funciono, insertar ademas
        # duplicaria el efecto y volveria a desincronizar audio y video.
        if is_overlay_transition and len(clips) > 1 and not overlays_blended:
            overlay_base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "transition_overlays")
            overlay_src = None
            if os.path.isdir(overlay_base_dir):
                for fname in sorted(os.listdir(overlay_base_dir)):
                    if fname.lower().endswith((".mp4", ".mov", ".webm")):
                        overlay_src = os.path.join(overlay_base_dir, fname)
                        break

            if overlay_src:
                target_ovr_dur = max(0.7, min(float(transition_duration or 1.0), 1.5))
                self.log(f"   [FX] Insertando Film Burn overlay ({target_ovr_dur:.2f}s) entre escenas...")
                # Crear clip de overlay escalado y acelerado a target_ovr_dur
                overlay_clip_path = os.path.join(temp_dir, "overlay_transition.mp4")
                # Primero obtener duracion original para calcular factor de velocidad
                orig_ovr_dur = _probe_duration_seconds(overlay_src, stream_selector='v:0', timeout=10)
                if orig_ovr_dur <= 0:
                    orig_ovr_dur = 2.0
                speed_factor = orig_ovr_dur / target_ovr_dur
                ovr_vf = (
                    f'setpts={1.0/speed_factor:.6f}*PTS,'
                    f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                    f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}'
                )
                ovr_cmd = [
                    ffmpeg_exe, '-y', '-i', overlay_src,
                    '-vf', ovr_vf,
                    '-c:v', optimal_encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
                    '-r', str(fps), '-g', '30',
                    '-an', overlay_clip_path
                ]
                try:
                    ovr_result = sp.run(
                        ovr_cmd, capture_output=True, text=True, timeout=60,
                        creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    if ovr_result.returncode == 0 and os.path.exists(overlay_clip_path):
                        actual_ovr_dur = _probe_duration_seconds(overlay_clip_path, stream_selector='v:0', timeout=10)
                        if actual_ovr_dur <= 0:
                            actual_ovr_dur = target_ovr_dur
                        self.log(
                            f"   [FX] Film Burn: {orig_ovr_dur:.2f}s -> {actual_ovr_dur:.2f}s "
                            f"(x{speed_factor:.1f} velocidad)"
                        )

                        # Detectar cambios de escena (fuentes visuales diferentes)
                        sources = []
                        for item in clips_data:
                            src = os.path.normcase(os.path.abspath(item.get('filename', '')))
                            sources.append(src)

                        # Insertar overlay entre clips con fuente visual diferente.
                        # Copiar un archivo ÚNICO por corte: concat demuxer + -c copy
                        # ignora repeticiones del mismo path y el burn desaparece.
                        merged_clips = [clips[0]]
                        merged_durations = [clip_durations[0]]
                        overlays_inserted = 0
                        for idx in range(1, len(clips)):
                            src_idx = min(idx, len(sources) - 1)
                            prev_src_idx = min(idx - 1, len(sources) - 1)
                            if sources[prev_src_idx] != sources[src_idx]:
                                unique_ovr = os.path.join(
                                    temp_dir, f"overlay_transition_{overlays_inserted:03d}.mp4"
                                )
                                try:
                                    shutil.copy2(overlay_clip_path, unique_ovr)
                                    ovr_to_use = unique_ovr
                                except Exception:
                                    ovr_to_use = overlay_clip_path
                                merged_clips.append(ovr_to_use)
                                merged_durations.append(actual_ovr_dur)
                                overlays_inserted += 1
                            merged_clips.append(clips[idx])
                            merged_durations.append(clip_durations[idx])

                        if overlays_inserted > 0:
                            clips = merged_clips
                            clip_durations = merged_durations
                            self.log(f"   [OK] {overlays_inserted} transiciones Film Burn insertadas")
                        else:
                            self.log("   [INFO] Sin cambios de escena detectados para overlay")
                    else:
                        self.log(f"   [WARN] No se pudo crear overlay clip: {(ovr_result.stderr or '')[:150]}")
                except Exception as exc:
                    self.log(f"   [WARN] Error preparando overlay: {exc}")
            else:
                self.log("   [WARN] No se encontro clip en transition_overlays/. Sin transicion overlay.")

        # FASE 2: Concatenar clips (con transiciones cuando aplica)
        list_file = os.path.join(temp_dir, "list.txt")
        video_no_audio = os.path.join(temp_dir, "video_base.mp4")
        concat_ok = False
        created_count = len(clips)

        if use_transitions and created_count > 1:
            min_clip = min(clip_durations) if clip_durations else 0.25
            safe_transition_duration = min(transition_duration, max(0.05, min_clip * 0.8))
            if safe_transition_duration < transition_duration:
                self.log(
                    f"   [INFO] Ajustando duracion de transicion {transition_duration:.2f}s -> "
                    f"{safe_transition_duration:.2f}s (clips cortos)"
                )
            self.log(
                f"   ðŸ”— Fase 2/3: Concatenando con transiciones "
                f"({transition_type} -> {xfade_transition}, {safe_transition_duration:.2f}s)..."
            )

            xfade_cmd = [ffmpeg_exe, '-y']
            clip_inputs = [os.path.basename(c) for c in clips]
            for c in clip_inputs:
                xfade_cmd.extend(['-i', c])

            filter_parts = []
            accumulated = 0.0
            prev_label = '[0:v]'
            for i in range(1, created_count):
                accumulated += max(0.01, clip_durations[i - 1])
                offset = max(0.0, accumulated - (i * safe_transition_duration))
                out_label = '[vout]' if i == created_count - 1 else f'[v{i}]'
                filter_parts.append(
                    f'{prev_label}[{i}:v]xfade=transition={xfade_transition}:duration={safe_transition_duration:.3f}:offset={offset:.3f}{out_label}'
                )
                prev_label = out_label

            xfade_cmd.extend([
                '-filter_complex', ';'.join(filter_parts),
                '-map', '[vout]',
                '-c:v', optimal_encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
                '-r', str(fps),
                '-movflags', '+faststart',
                os.path.basename(video_no_audio),
            ])

            try:
                result = sp.run(
                    xfade_cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    cwd=temp_dir,
                    creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode == 0 and os.path.exists(video_no_audio):
                    expected_xfade_duration = sum(clip_durations) - ((created_count - 1) * safe_transition_duration)
                    actual_xfade_duration = _probe_duration_seconds(video_no_audio, stream_selector='v:0', timeout=20)
                    if (
                        actual_xfade_duration > 0
                        and expected_xfade_duration > 0
                        and actual_xfade_duration < (expected_xfade_duration * 0.85)
                    ):
                        self.log(
                            f"   âš ï¸ xfade produjo video corto ({actual_xfade_duration:.1f}s "
                            f"vs esperado {expected_xfade_duration:.1f}s). Usando concatenacion simple estable."
                        )
                        concat_ok = False
                    else:
                        concat_ok = True
                        self.log("   âœ… Video base concatenado con transiciones")
                else:
                    err = (result.stderr or '')[:220]
                    self.log(f"   âš ï¸ Fallo xfade, usando concatenacion simple: {err}")
            except Exception as e:
                self.log(f"   âš ï¸ Error en xfade, usando concatenacion simple: {e}")

        if not concat_ok:
            self.log("   ðŸ”— Fase 2/3: Concatenando clips...")
            with open(list_file, 'w', encoding='utf-8') as f:
                for c in clips:
                    abs_path = os.path.abspath(c).replace('\\', '/')
                    f.write(f"file '{abs_path}'\n")

            concat_cmd = [
                ffmpeg_exe, '-y',
                '-f', 'concat', '-safe', '0', '-i', list_file,
                '-c', 'copy', '-movflags', '+faststart',
                video_no_audio
            ]

            try:
                result = sp.run(concat_cmd, capture_output=True, text=True, timeout=1800,
                                creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if result.returncode != 0:
                    self.log(f"   ❌ Error concatenando: {(result.stderr or '')[:200]}")
                    return False
            except Exception as e:
                self.log(f"   ❌ Error en concatenacion: {e}")
                return False

        if not os.path.exists(video_no_audio):
            self.log("   ❌ Archivo concatenado no fue creado")
            return False

        if not concat_ok:
            self.log("   ✅ Video base concatenado")

        # FASE 3: Agregar audio (duración = audio para que no se corte el final)
        self.log("   🎵 Fase 3/3: Agregando audio...")
        
        # --- MEJORA SFX: Inyectar Swoosh en transiciones ---
        # Se mezcla DENTRO del ffmpeg que muxea el audio (abajo), no con pydub:
        # el `export()` a un mp3 intermedio fallaba con [Errno 22] y el except se
        # comia el error -> video sin un solo swoosh. Aca solo se calculan las
        # posiciones y el filtro; si algo falla, el mux sigue sin SFX pero el QA
        # lo grita.
        sfx_filter = ""
        sfx_path_for_mix = None
        sfx_count = 0
        try:
            if enable_transition_sfx and (use_transitions or is_overlay_transition) and audio_file_path and len(clips) > 1:
                self.log("   🔊 Mezclando SFX de transicion en la pista maestra...")
                from pydub import AudioSegment
                sfx_path = self._resolve_transition_sfx_path(transition_sfx_path)

                if sfx_path and os.path.exists(sfx_path):
                    master = AudioSegment.from_file(audio_file_path)
                    sfx_swoosh = AudioSegment.from_file(sfx_path)

                    # Pico del swoosh: se alinea el PICO con el corte, no el
                    # inicio (el archivo dura ~4s y arranca con build-up).
                    max_rms, peak_idx = 0, 0
                    chunk_size = 10
                    for i in range(0, max(1, len(sfx_swoosh) - chunk_size), chunk_size):
                        rms = sfx_swoosh[i:i + chunk_size].rms
                        if rms > max_rms:
                            max_rms = rms
                            peak_idx = i

                    posiciones = audio_mix_utils.compute_transition_sfx_positions(
                        clip_durations,
                        escenas_nuevas=escenas_nuevas,
                        transition_duration=safe_transition_duration if use_transitions else 0.0,
                        created_count=created_count if use_transitions else None,
                        peak_offset_s=peak_idx / 1000.0,
                        total_duration_s=len(master) / 1000.0,
                    )

                    if not posiciones:
                        # Si no se inyecto ninguno, NO decir que salio bien: ese
                        # mensaje enganoso es lo que oculto que el swoosh no sonaba.
                        self.log("   [FAIL] SFX de transicion: 0 inyectados "
                                 "(no se detectaron cambios de escena)")
                        self._record_audio_qa('sfx_error', 'cero puntos de insercion')
                    else:
                        ganancia = audio_mix_utils.compute_sfx_gain_db(
                            master.max_dBFS, sfx_swoosh.max_dBFS
                        )
                        sfx_filter = audio_mix_utils.build_transition_sfx_filter(
                            posiciones, gain_db=ganancia
                        )
                        sfx_path_for_mix = sfx_path
                        sfx_count = len(posiciones)
                        self.log(
                            f"   [FX] Swoosh en {sfx_count} corte(s), "
                            f"{ganancia:+.1f} dB (pico a "
                            f"{audio_mix_utils.SFX_PEAK_UNDER_VOICE_DB:.0f} dB bajo la voz)"
                        )
                else:
                    self.log(f"   [WARN] No se encontro {sfx_path}, saltando SFX.")
        except Exception as e:
            self.log(f"   [WARN] Error preparando SFX de transicion: {e}")
            self._record_audio_qa('sfx_error', str(e))
            sfx_filter = ""
        # ---------------------------------------------------

        video_base_duration = _probe_duration_seconds(video_no_audio, stream_selector='v:0', timeout=20)
        force_shortest = False
        if audio_duration_sec > 0 and video_base_duration > 0 and video_base_duration + 0.25 < audio_duration_sec:
            self.log(
                f"   ⚠️ Duración de video base menor que audio ({video_base_duration:.1f}s < {audio_duration_sec:.1f}s). "
                f"Aplicando -shortest para evitar congelamiento de imagen."
            )
            force_shortest = True
        elif (
            audio_duration_sec > 0
            and video_base_duration > audio_duration_sec + 0.4
            and PYDUB_AVAILABLE
        ):
            # Film Burn inserts extra seconds; pad audio so -t audio does not crop the burns.
            try:
                pad_ms = int((video_base_duration - audio_duration_sec) * 1000)
                self.log(
                    f"   [FX] Video ({video_base_duration:.1f}s) > audio ({audio_duration_sec:.1f}s); "
                    f"rellenando audio +{pad_ms/1000:.1f}s para conservar Film Burn"
                )
                _aud = AudioSegment.from_file(audio_file_path)
                _aud = _aud + AudioSegment.silent(duration=pad_ms)
                padded = os.path.join(temp_dir, "audio_padded_for_overlays.mp3")
                _aud.export(padded, format="mp3")
                audio_file_path = padded
                audio_duration_sec = video_base_duration
            except Exception as pad_exc:
                self.log(f"   [WARN] No se pudo rellenar audio: {pad_exc}")
        def _build_audio_cmd(con_sfx):
            cmd = [ffmpeg_exe, '-y', '-i', video_no_audio, '-i', audio_file_path]
            if con_sfx:
                cmd += ['-i', sfx_path_for_mix,
                        '-filter_complex', sfx_filter,
                        '-map', '0:v', '-map', '[aout]']
            cmd += [
                '-c:v', 'copy',
                '-c:a', 'aac', '-b:a', '192k',
                '-ar', '44100', '-ac', '2',
                '-movflags', '+faststart',
            ]
            if audio_duration_sec > 0 and not force_shortest:
                cmd.extend(['-t', str(max(audio_duration_sec, video_base_duration or 0))])
            else:
                cmd.append('-shortest')
            cmd.append(output_path)
            return cmd

        def _run_audio_cmd(cmd):
            return sp.run(cmd, capture_output=True, text=True, timeout=1800,
                          creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)

        con_sfx = bool(sfx_filter and sfx_path_for_mix)
        try:
            result = _run_audio_cmd(_build_audio_cmd(con_sfx))
            if result.returncode != 0 and con_sfx:
                # Un swoosh no vale perder el render: se reintenta sin SFX y el
                # QA reporta que el video salio sin transiciones sonoras.
                self.log("   [WARN] Mux con SFX fallo, reintentando sin SFX: "
                         f"{(result.stderr or '')[:200]}")
                self._record_audio_qa('sfx_error', 'filtergraph de SFX rechazado por FFmpeg')
                con_sfx = False
                result = _run_audio_cmd(_build_audio_cmd(False))
            if con_sfx and result.returncode == 0:
                self._record_audio_qa('sfx_injected', sfx_count)
                self.log(f"   [OK] SFX de transicion mezclados en {sfx_count} cortes.")
            if result.returncode != 0:
                self.log(f"   âŒ Error agregando audio: {(result.stderr or '')[:200]}")
                return False
        except Exception as e:
            self.log(f"   âŒ Error agregando audio: {e}")
            return False

        # Verificar resultado
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            self.log("   âŒ Video final no fue creado correctamente")
            return False

        final_size = os.path.getsize(output_path) / (1024 * 1024)
        total_time = _time.time() - start_time
        self.log(f"   âœ… Video final: {final_size:.1f} MB (ensamblado en {total_time:.1f}s)")

        # Limpiar temporales
        try:
            for c in clips:
                if os.path.exists(c):
                    os.remove(c)
            if os.path.exists(video_no_audio):
                os.remove(video_no_audio)
            if os.path.exists(list_file):
                os.remove(list_file)
        except Exception:
            pass

        return True


    def _generate_youtube_chapters(self, storyboard_data, output_video_path):
        """Genera un archivo txt con capitulos de YouTube."""
        try:
            segments = storyboard_data.get('storyboard', {}).get('segments', []) if 'storyboard' in storyboard_data else storyboard_data.get('segments', [])
            if not segments:
                return
                
            out_dir = os.path.dirname(output_video_path)
            base_name = os.path.splitext(os.path.basename(output_video_path))[0]
            txt_path = os.path.join(out_dir, f"{base_name}_chapters.txt")
            
            chapters = ["00:00 Introduccion"]
            
            accumulated_sec = 0.0
            for i, seg in enumerate(segments):
                start_sec = seg.get('timestamp_start', accumulated_sec)
                
                if i == 0 and start_sec < 1.0:
                    accumulated_sec += seg.get('duration', 4.0)
                    continue
                    
                text_preview = seg.get('text', '')[:35].replace('\n', ' ').strip()
                title = seg.get('title', f"Escena {i+1}: {text_preview}...")
                
                mins = int(start_sec // 60)
                secs = int(start_sec % 60)
                ts_str = f"{mins:02d}:{secs:02d}"
                
                if not any(c.startswith(ts_str) for c in chapters):
                    chapters.append(f"{ts_str} {title}")
                
                accumulated_sec += seg.get('duration', 4.0)
                
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write("Capitulos / Marcas de Tiempo:\n")
                f.write("Copia y pega esto en la descripcion de YouTube:\n\n")
                f.write("\n".join(chapters))
        except Exception as e:
            self.log(f"   [WARN] Error generando capitulos: {e}")


    def assemble_video_from_storyboard(self, storyboard_data, platform,
                                       add_subtitles=True, subtitle_style='capcut',
                                       add_overlays=True, manual_bgm_path=None,
                                       manual_bgm_paths=None,
                                       manual_bgm_metadata=None,
                                       assembly_mode='auto', visual_mode='mixed',
                                       apply_cinematic=False, cinematic_preset='auto',
                                       cinematic_intensity='auto',
                                       transition_type='ðŸŒ… Fade Suave', transition_duration=0.5,
                                       generate_short_teaser=False, use_wikimedia=False,
                                       disable_wikimedia=False, use_real_images=True,
                                       use_google_images=True, enable_real_images_mix=False, test_mode=False,
                                       image_provider='auto',
                                       video_provider='none', fal_video_model=None,
                                       allow_visual_regeneration=True,
                                       enable_transition_sfx=None,
                                       transition_sfx_path=None,
                                       dynamism='off',
                                       blender_shots=False,
                                       blender_quality='normal',
                                       blender_environment='auto',
                                       **_extra_kwargs):
        """
        Ensambla el video desde el storyboard.
        
        Args:
            generate_short_teaser: Si es True y platform='youtube', genera un short teaser en paralelo
            use_wikimedia: (OBSOLETO) ParÃ¡metro mantenido por compatibilidad - Solo se usan APIs de generaciÃ³n (Fal.ai FLUX.1 schnell, Leonardo AI)
        """
        
        self.log(f"\nðŸš€ ENSAMBLANDO VIDEO (Modo: {assembly_mode} / {visual_mode})...")
        self.log(f"   Transicion seleccionada: {transition_type} ({transition_duration}s)")
        self._current_storyboard_data = storyboard_data
        if enable_transition_sfx is None:
            enable_transition_sfx = storyboard_data.get('_enable_transition_sfx')
        if enable_transition_sfx is None:
            enable_transition_sfx = True
        enable_transition_sfx = bool(enable_transition_sfx)
        transition_sfx_path = (
            transition_sfx_path
            or storyboard_data.get('_transition_sfx_path')
            or _extra_kwargs.get('transition_sfx_path')
        )
        if enable_transition_sfx:
            self.log(f"   SFX transicion: {os.path.basename(str(transition_sfx_path or 'swoosh.wav'))}")
        else:
            self.log("   SFX transicion: OFF")
        if not allow_visual_regeneration:
            self.log("ðŸ§± Modo estricto de ensamblaje: NO se generarÃ¡n nuevas imÃ¡genes/videos IA.")

        # --- Fase I2V previa al ensamblaje (opcional) ---------------------
        # Si video_provider es 'fal' o 'runway', genera un clip por segmento
        # usando la imagen ya existente como fotograma base (Kling/Luma) o un
        # prompt T2V (Runway). Debe ejecutarse ANTES de MoviePy/FFmpeg para
        # que el ensamblado use video_path en lugar de image_path + KenBurns.
        try:
            vp_effective = str(video_provider or 'none').strip().lower()
            # Si no llego por argumento, buscar en el bloque del storyboard
            if vp_effective in ('', 'none', 'auto') and isinstance(storyboard_data, dict):
                vp_block = storyboard_data.get('video_pipeline') or {}
                vp_effective = str(vp_block.get('video_provider') or 'none').lower()
                if fal_video_model is None:
                    fal_video_model = vp_block.get('fal_video_model')

            if vp_effective in ('fal', 'runway') and allow_visual_regeneration and not test_mode:
                self._generate_i2v_clips_for_segments(
                    storyboard_data=storyboard_data,
                    platform=platform,
                    video_provider=vp_effective,
                    fal_video_model=fal_video_model,
                )
        except Exception as exc:
            self.log(f"[I2V] Error en fase previa de video (se ignora y sigue ensamblando): {exc}")

        # Desactivar efectos cinematográficos si la ruta resulta riesgosa por RAM o estabilidad
        if apply_cinematic:
            if self._should_disable_cinematic_effects(
                storyboard_data,
                apply_cinematic,
                platform=platform,
                visual_mode=visual_mode,
                transition_type=transition_type,
                cinematic_preset=cinematic_preset,
            ):
                apply_cinematic = False
                self.log("   [OK] Efectos cinematicos desactivados automaticamente para usar una ruta de ensamblaje mas estable")
                
        # Comprobar espacio en disco físico antes de iniciar procesos pesados
        if self.export_manager:
            free_disk_gb = self.export_manager.check_system_disk_space()
            if free_disk_gb is not None and free_disk_gb < 2.5:
                err_msg = f"Espacio en disco critico: Solo quedan {free_disk_gb:.1f} GB libres. Se aborta para prevenir corrupcion."
                self.log(f"   [ERROR FATAL] {err_msg}")
                raise RuntimeError(err_msg)
        
        # Iniciar generaciÃ³n de short teaser en paralelo si estÃ¡ habilitado
        teaser_thread = None
        teaser_result = None
        
        if generate_short_teaser and platform == 'youtube':
            self.log("ðŸŽ¬ Iniciando generaciÃ³n de Short Teaser en paralelo...")
            import threading
            
            def generate_teaser():
                nonlocal teaser_result
                try:
                    # Extraer idioma del storyboard o usar el del video principal
                    language = storyboard_data.get('language', 'es')
                    # Si el script estÃ¡ en inglÃ©s, usar inglÃ©s
                    script_sample = storyboard_data.get('script', '')[:100].lower()
                    if any(word in script_sample for word in ['the', 'and', 'was', 'were', 'this', 'that', 'from']):
                        language = 'en'
                    
                    # Obtener voice_id del storyboard si estÃ¡ disponible
                    voice_id = storyboard_data.get('voice_id', None)
                    voice_rate = storyboard_data.get('voice_rate', '+0%')
                    
                    self.log(f"ðŸŽ¬ Generando teaser en idioma: {language}")
                    teaser_result = self.generate_short_teaser_from_long_video(
                        long_video_storyboard=storyboard_data,
                        language=language,
                        voice_id=voice_id,
                        disable_wikimedia=disable_wikimedia,  # Pasar la configuraciÃ³n de desactivaciÃ³n
                        rate=voice_rate
                    )
                except Exception as e:
                    self.log(f"âŒ Error generando short teaser: {e}")
            
            teaser_thread = threading.Thread(target=generate_teaser, daemon=True)
            teaser_thread.start()
        segments = storyboard_data['segments']
        if apply_cinematic:
            try:
                from pipeline.cinematic_director import direct_storyboard
                direction = direct_storyboard(
                    storyboard_data,
                    level=cinematic_intensity,
                    preset=cinematic_preset,
                )
                camera_counts = ", ".join(
                    f"{name}:{count}" for name, count in direction['camera_counts'].items()
                )
                self.log(
                    f"   Director cinematografico: {direction['label']} "
                    f"({direction['segments']} escenas; {camera_counts})"
                )
            except Exception as director_exc:
                self.log(f"   [WARN] Director cinematografico omitido: {director_exc}")
        # Composicion por escena (pantalla dividida, retrato, punch-in, toma 3D...).
        # Va despues del director: usa su papel narrativo (gancho, giro, climax).
        _blender_exe = None
        _blender_max = 0
        if blender_shots:
            from pipeline import blender_shots as _bs
            _blender_exe = _bs.find_blender()
            _orient = 'vertical' if platform in ['tiktok', 'reels', 'youtube_short', 'youtube_vertical'] else 'horizontal'
            _blender_max = _bs.MAX_SHOTS[_orient] if _blender_exe else 0
            if not _blender_exe:
                self.log("   [WARN] Tomas 3D pedidas pero Blender no esta instalado: se usan composiciones de FFmpeg")
        try:
            if segment_layouts.normalize_dynamism(dynamism) == "ai":
                from pipeline import ai_director
                layout_summary = ai_director.direct_layouts_with_ai(
                    storyboard_data, level=dynamism, log=self.log,
                    blender_shots=_blender_max, environment=blender_environment)
            else:
                layout_summary = segment_layouts.plan_layouts(
                    storyboard_data, level=dynamism, blender_shots=_blender_max,
                    environment=blender_environment,
                )
            self.log(f"   Composicion ({layout_summary['label']}): "
                     f"{segment_layouts.plan_summary_text(layout_summary)}")
        except Exception as layout_exc:
            self.log(f"   [WARN] Composicion por escena omitida: {layout_exc}")
        # PolÃ­tica YouTube Shorts: evitar pistas Jamendo en shorts >60s para reducir bloqueos/reclamaciones.
        short_duration_hint_sec = 0.0
        try:
            short_duration_hint_sec = max(float(seg.get('end', 0) or 0) for seg in segments) if segments else 0.0
        except Exception:
            short_duration_hint_sec = 0.0
        is_long_youtube_short = (platform == 'youtube_short' and short_duration_hint_sec > 60.0)

        manual_music_source = ""
        if isinstance(manual_bgm_metadata, dict):
            manual_music_source = str(manual_bgm_metadata.get('source', '') or '').strip().lower()

        manual_music_is_likely_jamendo = False
        if manual_bgm_path:
            if manual_music_source == "jamendo":
                manual_music_is_likely_jamendo = True
            # Si no hay metadata confiable, usar heurÃ­stica conservadora.
            elif manual_music_source in ("", "auto"):
                bgm_name = os.path.basename(str(manual_bgm_path)).lower()
                manual_music_is_likely_jamendo = not bgm_name.startswith("local_")

        if is_long_youtube_short and manual_bgm_path and manual_music_is_likely_jamendo:
            self.log(
                "   [WARN] YouTube Shorts >60s: desactivando pista de Jamendo para evitar "
                "reclamaciones/bloqueos por copyright."
            )
            manual_bgm_path = None

        effective_music_data = storyboard_data.get('music_data')
        if is_long_youtube_short and effective_music_data:
            self.log(
                "   [WARN] YouTube Shorts >60s: desactivando musica automatica de Jamendo "
                "para evitar reclamaciones/bloqueos por copyright."
            )
            effective_music_data = None
        audio_path = storyboard_data['audio_path']
        generated_clips = []
        is_vertical = platform in ['tiktok', 'reels', 'youtube_short', 'youtube_vertical']

        project_hint = storyboard_data.get('_project_path')
        project_base_dir = None
        if project_hint:
            try:
                project_hint_path = Path(str(project_hint))
                from infra.project_media_paths import project_directory
                project_base_dir = project_directory(project_hint_path)
            except Exception:
                project_base_dir = None

        def _resolve_existing_media_path(raw_path):
            if not raw_path:
                return None
            try:
                path_str = str(raw_path).strip()
            except Exception:
                return None
            if not path_str:
                return None

            candidate = Path(path_str)
            if candidate.exists():
                return str(candidate.resolve())
            if candidate.is_absolute():
                return None

            candidate_bases = []
            if project_base_dir is not None:
                candidate_bases.append(project_base_dir)
            candidate_bases.append(Path.cwd())
            candidate_bases.append(Path(self.generated_media_dir))

            for base in candidate_bases:
                try_path = base / candidate
                if try_path.exists():
                    return str(try_path.resolve())
            return None
        
        for i, seg in enumerate(segments):
            fname = seg['assigned_filename']
            visual_prompt = seg.get('visual_prompt', '')
            media_path = None

            # --- Cover frame handling ---
            if seg.get('cover_frame', False):
                cover_text = seg.get('cover_text', 'VANISHED')
                cf_duration = float(seg.get('end', 0.7)) - float(seg.get('start', 0))
                self.log(f"      [Cover Frame] Generating cover image: '{cover_text}'")
                try:
                    from pipeline.cover_frame_generator import generate_cover_frame
                    cf_result = generate_cover_frame(
                        topic=storyboard_data.get('topic', ''),
                        category=storyboard_data.get('category', ''),
                        storyboard=storyboard_data,
                        output_dir=str(self.generated_media_dir),
                        image_gen_manager=getattr(self, 'image_generation_manager', None),
                        image_provider=image_provider,
                        cover_text_override=cover_text,
                        log_callback=self.log,
                        # Sin esto, las rutas relativas del storyboard
                        # ("project_media/segment_001.png") no resuelven y el
                        # cover cae a un gradiente oscuro aunque haya imagenes.
                        media_base_dir=str(project_base_dir) if project_base_dir else None,
                    )
                    if cf_result and cf_result.get('image_path') and os.path.exists(cf_result['image_path']):
                        media_path = cf_result['image_path']
                        seg['image_path'] = media_path
                except Exception as exc:
                    self.log(f"      [Cover Frame] Error: {exc}")

                if not media_path:
                    self.log("      [Cover Frame] Fallback: dark gradient with text")
                    try:
                        from pipeline.cover_frame_generator import composite_cover_text
                        w, h = (1080, 1920) if is_vertical else (1920, 1080)
                        dark_img = Image.new('RGBA', (w, h), (10, 10, 15, 255))
                        final_img = composite_cover_text(dark_img, cover_text)
                        cf_path = os.path.join(str(self.generated_media_dir), 'cover_frame.png')
                        final_img.save(cf_path, 'PNG')
                        media_path = cf_path
                        seg['image_path'] = media_path
                    except Exception as exc2:
                        self.log(f"      [Cover Frame] Fallback also failed: {exc2}")

                if media_path:
                    seg_start = float(seg.get('start', 0) or 0)
                    generated_clips.append({
                        'filename': os.path.abspath(media_path),
                        'timestamp_start': seg_start,
                        'duration': max(0.3, cf_duration),
                        'overlay_filename': None,
                        'sfx_path': None,
                        'segment_text': '',
                        'is_cover': True,
                    })
                continue

            # 0) Priorizar media ya existente (video o imagen), resolviendo rutas relativas del proyecto.
            for media_field in ('video_path', 'image_path'):
                resolved_media = _resolve_existing_media_path(seg.get(media_field))
                if resolved_media:
                    media_path = resolved_media
                    media_type = "video" if media_field == 'video_path' else "imagen"
                    self.log(f"      âœ… Usando {media_type} existente: {os.path.basename(media_path)}")
                    break

            # 0.5) Compatibilidad: buscar por assigned_filename en generated_media_dir.
            if not media_path:
                for ext in ['.mp4', '.gif', '.jpg', '.png', '.jpeg', '.webp']:
                    test_p = os.path.join(str(self.generated_media_dir), f"{fname}{ext}")
                    if os.path.exists(test_p):
                        media_path = test_p
                        self.log(f"      âœ… Usando media local existente: {os.path.basename(media_path)}")
                        break

            # Imagen marcada como eliminada: usar negro sin intentar regenerar.
            if not media_path and seg.get('image_deleted', False):
                self.log(f"      âš« Imagen eliminada, usando imagen negra para: {fname}")
                w, h = (1080, 1920) if is_vertical else (1920, 1080)
                black_img = Image.new('RGB', (w, h), (0, 0, 0))
                black_path = os.path.join(str(self.generated_media_dir), f"{fname}_black.jpg")
                black_img.save(black_path)
                media_path = black_path

            # Si no hay media preexistente y se permite, generar (flujo antiguo).
            if not media_path and allow_visual_regeneration:
                # MODO MANUAL
                if assembly_mode == 'manual':
                    for ext in ['.mp4', '.jpg', '.png']:
                        # Buscamos directamente con os.path para evitar problemas de Pathlib en G:
                        test_p = os.path.join(str(self.generated_media_dir), f"{fname}{ext}")
                        if os.path.exists(test_p):
                            media_path = test_p
                            break
                
                # MODO AUTO
                elif assembly_mode == 'auto':
                    # En modo prueba, no usar videos (solo imÃ¡genes de Wikimedia)
                    use_video = (visual_mode != 'static') and ((random.random() < 0.3) or (i < 1)) and not test_mode

                    # A. GeneraciÃ³n de video con sistema de fallback (Leonardo Motion) - NO en modo prueba
                    # B. Pexels Video (fallback si la generaciÃ³n IA fallÃ³ completamente, NO en modo prueba)
                    if use_video and not media_path and self.downloader.pexels_key and not test_mode:
                        v = self.downloader.search_pexels_videos(visual_prompt)
                        if v:
                            media_path = self.downloader.download_video(v[0], os.path.join(str(self.generated_media_dir), f"{fname}.mp4"))

                    # C. Imagen
                    if not media_path:
                        w, h = (1080, 1920) if is_vertical else (1920, 1080)
                        # PRIORIDAD 4: Fallbacks de IA (Fal.ai, Runway, Eden, Pexels) - solo si Leonardo fallÃ³
                        if not media_path and not test_mode:
                            # PRIORIDAD 4.2: Runway Gen4 (fallback)
                            if not media_path and self.runway_client:
                                try:
                                    self.log(f"      ðŸš€ Runway Gen4 (fallback): {fname}")
                                    task = self.runway_client.text_to_image.create(
                                        model='gen4_image_turbo',
                                        prompt_text=visual_prompt,
                                        ratio='9:16' if is_vertical else '16:9'
                                    ).wait_for_task_output()
                                    if task.output and task.output.url:
                                        tp = os.path.join(str(self.generated_media_dir), f"{fname}.png")
                                        with open(tp, 'wb') as f:
                                            f.write(requests.get(task.output.url).content)
                                        media_path = tp
                                        self.log(f"         âœ… Imagen generada por Runway Gen4")
                                except Exception as e:
                                    self.log(f"         âš ï¸ Runway fallÃ³: {str(e)[:50]}")
                            
                            # PRIORIDAD 4.3: Eden AI (fallback)
                            if not media_path and hasattr(self, 'eden_ai_available') and self.eden_ai_available:
                                try:
                                    eden_api_key = os.getenv("EDEN_AI_API_KEY")
                                    if eden_api_key:
                                        self.log(f"      ðŸŒŸ Eden AI (fallback): {fname}")
                                        providers = ['fal-ai', 'leonardo']
                                        for provider in providers:
                                            try:
                                                urls_to_try = [
                                                    "https://api.edenai.run/v2/image/generation",
                                                    "https://api.edenai.co/v2/image/generation"
                                                ]
                                                for url in urls_to_try:
                                                    try:
                                                        headers = {'Authorization': f'Bearer {eden_api_key}', 'Content-Type': 'application/json'}
                                                        data = {'text': visual_prompt, 'providers': provider, 'resolution': f'{w}x{h}', 'num_images': 1}
                                                        response = requests.post(url, headers=headers, json=data, timeout=60)
                                                        if response.status_code == 200:
                                                            result = response.json()
                                                            if provider in result and result[provider].get('status') == 'success':
                                                                items = result[provider].get('items', [])
                                                                if items:
                                                                    image_url = items[0].get('image_resource_url') or items[0].get('image_url') or items[0].get('url')
                                                                    if image_url:
                                                                        tp = os.path.join(str(self.generated_media_dir), f"{fname}.png")
                                                                        with open(tp, 'wb') as f:
                                                                            f.write(requests.get(image_url).content)
                                                                        media_path = tp
                                                                        self.log(f"         âœ… Imagen generada por Eden AI ({provider})")
                                                                        break
                                                    except requests.exceptions.ConnectionError:
                                                        continue
                                                    except:
                                                        continue
                                                if media_path:
                                                    break
                                            except:
                                                continue
                                except Exception as e:
                                    self.log(f"         âš ï¸ Eden AI fallÃ³: {str(e)[:50]}")
                            
                            # PRIORIDAD 4.4: Pexels (Ãºltimo fallback)
                            if not media_path and self.downloader.pexels_key:
                                self.log(f"      ðŸ” Pexels (fallback): {fname}")
                                imgs = self.downloader.search_pexels_images(visual_prompt)
                                if imgs:
                                    media_path = self.downloader.download_image(imgs[0], os.path.join(str(self.generated_media_dir), f"{fname}.jpg"))
                                    if media_path:
                                        self.log(f"         âœ… Imagen descargada de Pexels")

            # Si falta media y NO se permite regenerar, crear placeholder negro.
            if not media_path and not allow_visual_regeneration:
                self.log(f"      âš« Sin media para {fname}; se usa placeholder (regeneraciÃ³n IA desactivada)")
                w, h = (1080, 1920) if is_vertical else (1920, 1080)
                black_img = Image.new('RGB', (w, h), (0, 0, 0))
                black_path = os.path.join(str(self.generated_media_dir), f"{fname}_missing_black.jpg")
                black_img.save(black_path)
                media_path = black_path

            # SFX / Overlays
            sfx_path = None
            if SFX_AVAILABLE and seg.get('sfx_tag') != 'none':
                sfx_path = find_and_download_sfx(seg['sfx_tag'], self.generated_media_dir)
            # Overlays GIF retirados (nunca hubo API key). 'overlay_tag' sigue en
            # el esquema del storyboard pero no se descarga nada.
            ov_path = None

            if media_path:
                # Usar os.path.abspath para la ruta definitiva
                abs_p = os.path.abspath(media_path)

                ost = (seg.get('on_screen_text') or '').strip()
                if ost and abs_p.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                    abs_p = self._composite_on_screen_text(abs_p, ost, i)

                # Mantener coherencia temporal con el timeline narrativo:
                # si hay hueco entre este segmento y el siguiente, extender
                # visualmente este clip para cubrir ese silencio.
                seg_start = float(seg.get('start', 0) or 0)
                seg_end = float(seg.get('end', seg_start) or seg_start)
                seg_duration = max(0.05, seg_end - seg_start)
                if seg_duration <= 0.05:
                    seg_duration = float(seg.get('duration', 4.0))

                if (i + 1) < len(segments):
                    pass # Evitar extender la duracion. El gap es rellenado intencionalmente por las transiciones.

                generated_clips.append({
                    'filename': abs_p,
                    'timestamp_start': seg_start,
                    'duration': seg_duration,
                    'overlay_filename': os.path.basename(ov_path) if ov_path else None,
                    'sfx_path': sfx_path,
                    # Lo usa la ruta FFmpeg para elegir el movimiento de camara
                    # segun el contexto, igual que hace la ruta MoviePy.
                    'segment_text': (seg.get('narration_text') or seg.get('text') or ''),
                    'cinematic_plan': seg.get('cinematic_plan'),
                    'layout_plan': self._layout_plan_for_clip(seg, _resolve_existing_media_path),
                })
            else:
                self.log(f"      âš ï¸ No se generÃ³ visual para: {fname}")

        # Fusionar clips consecutivos:
        # - Misma imagen/video → un solo clip con duración acumulada
        # - Vsplit consecutivos (vsplit_01 → vsplit_02 → …) → encadenados en _vsplit_chain
        #   para ser pre-concatenados en Phase 1 sin transición ni slowdown incorrecto.
        import re as _vre
        _VSPLIT_PAT = _vre.compile(r'_vsplit_0*(\d+)\.\w+$', _vre.IGNORECASE)
        def _vsplit_n(p):
            m = _VSPLIT_PAT.search(os.path.basename(str(p)))
            return int(m.group(1)) if m else None

        _merged = []
        for _clip in generated_clips:
            fn = _clip["filename"]
            vn = _vsplit_n(fn)
            if _merged:
                last = _merged[-1]
                last_tail = last.get('_vsplit_tail', last["filename"])
                last_vn   = _vsplit_n(last_tail)
                if (last["filename"] == fn
                        and last.get('cinematic_plan') == _clip.get('cinematic_plan')
                        and last.get('layout_plan') == _clip.get('layout_plan')
                        and last.get('sfx_path') == _clip.get('sfx_path')):
                    # Misma fuente: acumular duración (p.ej. misma imagen en varios segmentos)
                    last["duration"] += _clip["duration"]
                    continue
                if vn is not None and last_vn is not None and vn == last_vn + 1:
                    # Vsplit consecutivo: encadenar para concat sin transición
                    last.setdefault('_vsplit_chain', [last["filename"]]).append(fn)
                    last['_vsplit_tail'] = fn
                    last["duration"] += _clip["duration"]
                    continue
            _merged.append(dict(_clip))

        vsplit_chains = sum(1 for c in _merged if c.get('_vsplit_chain'))
        if len(_merged) < len(generated_clips):
            self.log(
                f"   Fusionados {len(generated_clips)} clips en {len(_merged)} "
                f"({vsplit_chains} cadenas vsplit + misma fuente consecutiva)"
            )
        generated_clips = _merged
        # De donde salen los paneles extra (vecinas, detalle, media extra).
        segment_layouts.resolve_layout_sources(generated_clips)

        # Arranque (video_opening): el primer plano dura ~1.8 s (mediana de los shorts que ganan)
        # y arranca con acercamiento. Solo en storyboards nuevos: los viejos renderizan igual.
        try:
            from pipeline import video_opening as _vo
            _opening_style = _vo.opening_style(storyboard_data)
            if generated_clips and _vo.is_modern_opening(_opening_style):
                _op = storyboard_data.get('opening') or {}
                _moved = _vo.enforce_min_first_shot(
                    generated_clips,
                    float(_op.get('min_first_shot_seconds') or _vo.DEFAULTS['min_first_shot_seconds']))
                generated_clips[0]['opening_style'] = _opening_style
                generated_clips[0]['opening_motion_amount'] = float(
                    _op.get('motion_amount') or _op.get('push_in_zoom') or _vo.DEFAULTS['push_in_zoom'])
                self._record_audio_qa('opening_style', _opening_style)
                _opening_label = _vo.opening_style_spec(_opening_style)['short_label']
                self.log(f"   Arranque: primer plano {generated_clips[0]['duration']:.2f}s"
                         + (f" (+{_moved:.2f}s tomados del segundo)" if _moved else "")
                         + f", {_opening_label}, voz en 0.0s")
        except Exception as exc:
            self.log(f"   [WARN] No se pudo preparar el arranque: {exc}")

        # 2. Ensamblar
        res = VideoConfig.VIDEO_RESOLUTION_VERTICAL if is_vertical else VideoConfig.VIDEO_RESOLUTION

        # Verificar que el audio existe antes de ensamblar
        audio_path = storyboard_data.get('audio_path')
        if not audio_path or not os.path.exists(audio_path):
            self.log(f"âŒ ERROR: Audio no encontrado en: {audio_path}")
            return None

        # === RUTA RÃPIDA: FFmpeg directo (sin MoviePy) ===
        # Ensamblar directamente con FFmpeg es ~2x mÃ¡s rÃ¡pido y mÃ¡s robusto.
        # Soporta imÃ¡genes Y videos. Evita problemas de CompositeVideoClip y seek.
        # Solo se desactiva cuando hay efectos cinematogrÃ¡ficos (que requieren MoviePy).
        all_supported_media = all(
            c.get('filename', '').lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif', '.mp4', '.mov', '.avi', '.webm', '.mkv'))
            for c in generated_clips
        ) if generated_clips else False

        self.log(f"   ðŸ” DEBUG: {len(generated_clips)} clips, mÃºsica: {'SÃ' if manual_bgm_path or effective_music_data else 'NO'}, PYDUB: {'SÃ' if PYDUB_AVAILABLE else 'NO'}")
        self.log(f"   🔎 DEBUG: {len(generated_clips)} clips, música: {'Sí ' if manual_bgm_path or effective_music_data else 'NO'}, PYDUB: {'Sí ' if PYDUB_AVAILABLE else 'NO'}")

        # Normalizar lista de pistas: manual_bgm_paths tiene prioridad sobre manual_bgm_path
        _bgm_paths = []
        if manual_bgm_paths and isinstance(manual_bgm_paths, list):
            _bgm_paths = [p for p in manual_bgm_paths if p and os.path.exists(str(p))]
        if not _bgm_paths and manual_bgm_path and os.path.exists(str(manual_bgm_path)):
            _bgm_paths = [manual_bgm_path]
            
        # Preparar audio con fade-out suave al final
        # Agregar segundos extra despuÃ©s de la narraciÃ³n para un cierre gradual
        OUTRO_FADE_SECONDS = 4  # Segundos extra despuÃ©s de la narraciÃ³n
        final_audio_path = audio_path
        
        # --- Alineacion del cover frame -----------------------------------
        # El storyboard desplaza los timestamps de TODOS los segmentos cuando
        # inserta el cover frame, pero la narracion sigue empezando en 0.0s.
        # Sin este padding la voz (y los subtitulos que salen de ella) van
        # adelantados respecto de las imagenes durante todo el video.
        cover_offset_s = audio_mix_utils.compute_cover_offset_seconds(
            storyboard_data.get('segments')
        )
        self._reset_audio_qa()
        self._record_audio_qa('cover_offset_expected_s', cover_offset_s)

        # Tomas 3D: se renderizan ANTES del ensamblaje y entran como un video mas.
        # Va despues de reiniciar el QA para que su resultado llegue al resumen.
        self._render_blender_shots(generated_clips, res, blender_exe=_blender_exe,
                                   quality=blender_quality, storyboard_data=storyboard_data,
                                   environment=blender_environment)

        # Pista de voz que alimenta la mezcla y (limpia) los subtitulos.
        voice_path = audio_path
        if PYDUB_AVAILABLE and cover_offset_s > 0.01:
            try:
                _v_aligned = (
                    AudioSegment.silent(duration=int(round(cover_offset_s * 1000)))
                    + AudioSegment.from_file(audio_path)
                )
                voice_path = str(self.generated_media_dir / "voice_aligned.wav")
                _v_aligned.export(voice_path, format="wav")
                self._record_audio_qa('cover_offset_applied_s', cover_offset_s)
                self.log(f"   Cover frame: narracion desplazada {cover_offset_s:.2f}s para alinear con los visuales")
            except Exception as e:
                self.log(f"   [WARN] No se pudo alinear la narracion con el cover frame: {e}")
                voice_path = audio_path

        # Referencia limpia (voz sola, misma linea de tiempo) para Whisper.
        subtitle_reference_audio = voice_path

        _is_overlay_trans = audio_mix_utils.is_overlay_transition(transition_type)
        _use_trans = audio_mix_utils.uses_transition(transition_type)
        # --- Swoosh solo en CAMBIO de still (no en cada parrafo del mismo visual_key) ---
        # La ruta FFmpeg ahora resuelve los efectos cinematograficos con zoompan,
        # asi que `apply_cinematic` ya no obliga a pasar por MoviePy (que iba a
        # ~1.6 fps contra ~120 fps de FFmpeg).
        _will_use_direct_ffmpeg = bool(all_supported_media and generated_clips)
        self._record_audio_qa('sfx_enabled', bool(enable_transition_sfx))
        self._record_audio_qa('sfx_handled_by_direct_ffmpeg', _will_use_direct_ffmpeg)
        if audio_mix_utils.should_inject_transition_sfx(
            enable_transition_sfx, PYDUB_AVAILABLE, transition_type,
            len(generated_clips), _will_use_direct_ffmpeg,
        ):
            try:
                self.log("   🔊 Inyectando SFX de transicion en la pista de voz...")
                # 32 bits: el swoosh se suma a la voz y a 16 bits los picos
                # coincidentes clipearian. El limiter final ajusta el nivel.
                v_sfx = AudioSegment.from_file(voice_path).set_sample_width(4)
                sfx_path = self._resolve_transition_sfx_path(transition_sfx_path)

                if sfx_path and os.path.exists(sfx_path):
                    sfx_swoosh = AudioSegment.from_file(sfx_path)
                    # Nivelar el swoosh por PICO contra la voz: el archivo tiene
                    # media muy baja (-27 dBFS) y quedaba inaudible bajo la
                    # musica. Por pico se lo escucha sin clipear la mezcla.
                    try:
                        if sfx_swoosh.max_dBFS > -90 and v_sfx.max_dBFS > -90:
                            sfx_swoosh = sfx_swoosh.apply_gain(
                                (v_sfx.max_dBFS - audio_mix_utils.SFX_PEAK_UNDER_VOICE_DB)
                                - sfx_swoosh.max_dBFS
                            )
                    except Exception:
                        pass
                    # Alinear el PICO del swoosh con el corte (no su inicio):
                    # el archivo dura varios segundos y arranca con un build-up.
                    peak_idx, max_rms, chunk_size = 0, 0, 10
                    for _i in range(0, max(1, len(sfx_swoosh) - chunk_size), chunk_size):
                        _rms = sfx_swoosh[_i:_i + chunk_size].rms
                        if _rms > max_rms:
                            max_rms, peak_idx = _rms, _i
                    sfx_added = 0
                    prev_src = os.path.normcase(os.path.abspath(str(generated_clips[0].get('filename') or '')))
                    for i in range(1, len(generated_clips)):
                        cur_src = os.path.normcase(os.path.abspath(str(generated_clips[i].get('filename') or '')))
                        if cur_src == prev_src:
                            continue
                        prev_src = cur_src
                        t_start_ms = int(generated_clips[i].get('timestamp_start', 0) * 1000)
                        if t_start_ms > 0:
                            v_sfx = v_sfx.overlay(sfx_swoosh, position=max(0, t_start_ms - peak_idx))
                            sfx_added += 1

                    if sfx_added:
                        # OJO: no pisar audio_path (es la narracion del proyecto);
                        # se escribe una pista aparte para la mezcla.
                        voice_path = str(self.generated_media_dir / "voice_sfx.wav")
                        v_sfx.export(voice_path, format="wav")
                        self._record_audio_qa('sfx_injected', sfx_added)
                        self.log(f"   ✅ SFX de transicion mezclados en {sfx_added} cambios de escena.")
                else:
                    self._record_audio_qa('sfx_error', f"SFX no encontrado: {sfx_path}")
                    self.log(f"   [WARN] No se encontro el archivo de SFX de transicion ({sfx_path}).")
            except Exception as e:
                self._record_audio_qa('sfx_error', str(e))
                self.log(f"   ⚠️ Error inyectando SFX de transicion: {e}")

        # Los SFX contextuales ya se descargaban por segmento, pero la ruta
        # rapida de FFmpeg nunca los mezclaba. Se integran en la misma linea de
        # tiempo de la voz para que lleguen tanto al render directo como al mix
        # posterior con musica y ducking.
        if PYDUB_AVAILABLE and _will_use_direct_ffmpeg:
            contextual_sfx = [
                clip for clip in generated_clips
                if clip.get('sfx_path') and os.path.exists(str(clip.get('sfx_path')))
            ]
            if contextual_sfx:
                try:
                    voice_with_sfx = AudioSegment.from_file(voice_path).set_sample_width(4)
                    mixed_count = 0
                    for clip in contextual_sfx:
                        effect = AudioSegment.from_file(str(clip['sfx_path'])).set_sample_width(4)
                        try:
                            if effect.max_dBFS > -90 and voice_with_sfx.max_dBFS > -90:
                                target_peak = voice_with_sfx.max_dBFS - 16.0
                                effect = effect.apply_gain(target_peak - effect.max_dBFS)
                        except Exception:
                            effect = effect - 16
                        position_ms = max(0, int(float(clip.get('timestamp_start', 0) or 0) * 1000))
                        voice_with_sfx = voice_with_sfx.overlay(effect, position=position_ms)
                        mixed_count += 1
                    contextual_path = str(self.generated_media_dir / "voice_contextual_sfx.wav")
                    voice_with_sfx.export(contextual_path, format="wav")
                    voice_path = contextual_path
                    self._record_audio_qa('contextual_sfx_injected', mixed_count)
                    self.log(f"   [OK] {mixed_count} SFX contextuales sincronizados con el timeline.")
                except Exception as contextual_exc:
                    self._record_audio_qa('contextual_sfx_error', str(contextual_exc))
                    self.log(f"   [WARN] No se pudieron mezclar los SFX contextuales: {contextual_exc}")

        audio_has_outro = False  # Flag para indicar que el audio ya tiene el outro integrado

        # Preparar música de fondo (si existe) antes de decidir la ruta
        bgm = _bgm_paths[0] if _bgm_paths else None
        if not bgm and effective_music_data and JAMENDO_AVAILABLE:
            try:
                bgm = str(self.generated_media_dir / "temp_bgm.mp3")
                self.log(f"   🎵 Descargando música de fondo...")
                download_track(effective_music_data['audio_url'], bgm)
                if not os.path.exists(bgm):
                    bgm = None
            except Exception as e:
                self.log(f"   ⚠️ Error descargando música: {e}")
                bgm = None

        # Que musica quedo en la mezcla: se atribuye en la descripcion al publicar
        # (music_license). Antes 'music_attribution' era siempre None y la atribucion
        # que exige CC BY nunca llegaba a YouTube.
        _music_used = None
        if bgm and _bgm_paths:
            _music_used = dict(manual_bgm_metadata) if isinstance(manual_bgm_metadata, dict) else {
                'source': 'local', 'license_code': 'LOCAL',
                'title': os.path.splitext(os.path.basename(str(bgm)))[0]}
        elif bgm and effective_music_data:
            _music_used = dict(effective_music_data)
        _music_attribution = None
        if _music_used and str(_music_used.get('source') or '').lower() != 'local':
            try:
                from publish.music_license import attribution_text as _music_attr_text
                _music_attribution = _music_attr_text(_music_used)
            except Exception:
                _music_attribution = None

        # Preparar audio con fade-out suave al final
        # Agregar segundos extra despuÃ©s de la narraciÃ³n para un cierre gradual
        OUTRO_FADE_SECONDS = 4  # Segundos extra despuÃ©s de la narraciÃ³n
        final_audio_path = audio_path
        audio_has_outro = False  # Flag para indicar que el audio ya tiene el outro integrado
        self.log(f"   ðŸ” DEBUG: bgm={bgm}, exists={os.path.exists(bgm) if bgm else False}")
        if bgm and os.path.exists(bgm):
            try:
                if PYDUB_AVAILABLE:
                    outro_ms = OUTRO_FADE_SECONDS * 1000
                    self.log(f"   ðŸŽµ Preparando audio con mÃºsica (fade out {OUTRO_FADE_SECONDS}s despuÃ©s de narraciÃ³n)...")
                    v = AudioSegment.from_file(voice_path)

                    # Cargar y encadenar pistas de música con crossfade entre ellas
                    bgm_playlist = _bgm_paths if _bgm_paths else [bgm]
                    TRACK_CROSSFADE_MS = 2000  # 2s de fade-out/fade-in entre pistas
                    if len(bgm_playlist) > 1:
                        self.log(f"   🎵 Encadenando {len(bgm_playlist)} pistas con crossfade {TRACK_CROSSFADE_MS//1000}s...")
                        m = AudioSegment.from_file(bgm_playlist[0])
                        for _track_path in bgm_playlist[1:]:
                            try:
                                _next = AudioSegment.from_file(_track_path)
                                m = m.append(_next, crossfade=TRACK_CROSSFADE_MS)
                                self.log(f"   ✅ Pista encadenada: {os.path.basename(_track_path)}")
                            except Exception as _e:
                                self.log(f"   ⚠️ Error encadenando {os.path.basename(_track_path)}: {_e}")
                    else:
                        m = AudioSegment.from_file(bgm)

                    # Extender narraciÃ³n con silencio para crear espacio para el fade-out de mÃºsica
                    # Esto permite que la mÃºsica siga sonando (con fade) despuÃ©s de que termine la narraciÃ³n
                    v_extended = v + AudioSegment.silent(duration=outro_ms)
                    total_duration = len(v_extended)  # narraciÃ³n + outro

                    # Asegurar que la cadena de pistas cubra toda la duraciÃ³n (repitiendo la cadena completa)
                    if len(m) < total_duration:
                        CROSSFADE_MS = min(3000, len(m) // 4)  # MÃ¡ximo 3 segs de crossfade
                        base_m = m
                        loops_needed = int(total_duration / max(1, (len(m) - CROSSFADE_MS))) + 1
                        for _ in range(loops_needed):
                            m = m.append(base_m, crossfade=CROSSFADE_MS)
                    # Recortar mÃºsica y aplicar fade out durante los segundos extra
                    music_segment = m[:total_duration]
                    music_with_fadeout = music_segment.fade_out(outro_ms)

                    # Calcular niveles ANTES de mezclar: la voz manda y la musica
                    # queda por debajo. Sin esto la musica (masterizada, ~-18 dBFS)
                    # tapa al TTS (~-21 dBFS). Las ganancias se APLICAN en FFmpeg
                    # (float + limiter) para no clipear los picos de la voz.
                    # Niveles medidos como se PERCIBEN: la voz en sus tramos
                    # hablados y la musica en su nivel tipico. Usar dBFS global
                    # para ambos metia 5.6 dB de error y la musica terminaba
                    # 25.8 dB bajo la voz en vez de los ~14 buscados.
                    _voz_nivel = audio_mix_utils.speech_level_dbfs(v)
                    _mus_nivel = audio_mix_utils.music_level_dbfs(music_with_fadeout)
                    _voice_gain_db, _music_gain_db = audio_mix_utils.compute_mix_gains(
                        _voz_nivel, _mus_nivel
                    )
                    self._record_audio_qa('voice_dbfs', _voz_nivel)
                    self._record_audio_qa('music_dbfs', _mus_nivel)
                    self._record_audio_qa('voice_gain_db', _voice_gain_db)
                    self._record_audio_qa('music_gain_db', _music_gain_db)
                    _under_speech = audio_mix_utils.estimate_ducked_music_under_voice_db()
                    self._record_audio_qa('music_under_voice_speech_db', _under_speech)
                    self.log(
                        f"   Niveles (hablando/tipico): voz {_voz_nivel:.1f} dBFS "
                        f"({_voice_gain_db:+.1f} dB) / musica {_mus_nivel:.1f} dBFS "
                        f"({_music_gain_db:+.1f} dB)"
                    )
                    self.log(
                        f"   Musica: cama a -{audio_mix_utils.MUSIC_UNDER_VOICE_DB:.0f} dB de la voz, "
                        f"~-{_under_speech:.0f} dB mientras hay narracion (ducking incluido)"
                    )

                    # Mezclar: narraciÃ³n (con silencio al final) + mÃºsica (con fade-out al final)
                    # El resultado tendrÃ¡: narraciÃ³n+mÃºsica durante la narraciÃ³n, luego solo mÃºsica con fade-out
                    # MEJORA: Auto-Ducking Inteligente con FFmpeg sidechaincompress
                    self.log("   🎚️ Aplicando Auto-Ducking (Sidechain) a la musica...")
                    import shutil, subprocess as sp
                    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
                    temp_voice = str(self.generated_media_dir / "temp_voice.wav")
                    temp_music = str(self.generated_media_dir / "temp_music.wav")
                    v_extended.export(temp_voice, format="wav")
                    music_with_fadeout.export(temp_music, format="wav")
                    
                    mp = str(self.generated_media_dir / "mix.mp3")
                    # sidechaincompress: musica (entrada 0) comprimida por la voz
                    # (entrada 1). El detalle del filtergraph vive en
                    # audio_mix_utils.build_duck_filter (tiene test de regresion).
                    duck_filter = audio_mix_utils.build_duck_filter(
                        _voice_gain_db, _music_gain_db
                    )
                    duck_cmd = [
                        ffmpeg_exe, '-y',
                        '-i', temp_music,
                        '-i', temp_voice,
                        '-filter_complex', duck_filter,
                        '-map', '[out]',
                        '-c:a', 'libmp3lame', '-q:a', '2',
                        mp
                    ]
                    try:
                        _duck = sp.run(
                            duck_cmd, stdout=sp.DEVNULL, stderr=sp.PIPE,
                            creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                            check=True,
                        )
                        self._record_audio_qa('ducking_ok', True)
                        self.log("   Auto-ducking aplicado (sidechain OK)")
                    except Exception as e:
                        _err = getattr(e, 'stderr', b'') or b''
                        if isinstance(_err, bytes):
                            _err = _err.decode('utf-8', errors='replace')
                        _err_tail = ' | '.join([ln for ln in _err.strip().splitlines() if ln.strip()][-3:])
                        self._record_audio_qa('ducking_ok', False)
                        self._record_audio_qa('ducking_error', _err_tail or str(e))
                        self.log(f"   [WARN] Error en FFmpeg Sidechain, usando mezcla normal: {e}")
                        if _err_tail:
                            self.log(f"   [WARN] ffmpeg: {_err_tail}")
                        # Fallback en pydub: aplicar aca las ganancias calculadas.
                        # 32 bits antes de subir la voz para no clipear los picos.
                        try:
                            _vf = v_extended.set_sample_width(4).apply_gain(_voice_gain_db)
                            _mf = music_with_fadeout.set_sample_width(4).apply_gain(_music_gain_db)
                            final_mix = _vf.overlay(_mf).set_sample_width(2)
                        except Exception:
                            final_mix = v_extended.overlay(music_with_fadeout - 10)
                        final_mix.export(mp, format="mp3")
                        
                    if os.path.exists(temp_voice): os.remove(temp_voice)
                    if os.path.exists(temp_music): os.remove(temp_music)
                    final_audio_path = mp
                    audio_has_outro = True
                    self.log(f"   âœ… Audio preparado: narraciÃ³n ({len(v)/1000:.1f}s) + outro con mÃºsica fade-out ({OUTRO_FADE_SECONDS}s)")

                    # EXTENDER el Ãºltimo clip para cubrir los segundos extra del outro
                    if generated_clips:
                        last_clip = generated_clips[-1]
                        original_duration = last_clip.get('duration', 0)
                        last_clip['duration'] = original_duration + OUTRO_FADE_SECONDS
                        last_clip['timestamp_end'] = last_clip.get('timestamp_start', 0) + last_clip['duration']
                        self.log(f"   â±ï¸ Ãšltimo clip extendido: {original_duration:.1f}s â†’ {last_clip['duration']:.1f}s (outro)")
                else:
                    self.log(f"   âš ï¸ PYDUB no disponible, no se puede aplicar fade out a la mÃºsica")
            except Exception as e:
                self.log(f"   âš ï¸ Error preparando audio con mÃºsica: {e}")
                import traceback
                traceback.print_exc()
                final_audio_path = audio_path  # Fallback a audio original
                audio_has_outro = False

        # Si no hay mÃºsica pero sÃ­ pydub, agregar silencio al final para el fade-out de video
        if not audio_has_outro and PYDUB_AVAILABLE:
            try:
                outro_ms = OUTRO_FADE_SECONDS * 1000
                v = AudioSegment.from_file(voice_path)
                # Agregar silencio para que el video tenga tiempo de hacer fade to black
                v_extended = v + AudioSegment.silent(duration=outro_ms)
                mp = str(self.generated_media_dir / "mix.mp3")
                v_extended.export(mp, format="mp3")
                final_audio_path = mp
                audio_has_outro = True
                self.log(f"   ðŸŽ¬ Audio extendido con {OUTRO_FADE_SECONDS}s de silencio para fade-out de video")

                # Extender Ãºltimo clip
                if generated_clips:
                    last_clip = generated_clips[-1]
                    original_duration = last_clip.get('duration', 0)
                    last_clip['duration'] = original_duration + OUTRO_FADE_SECONDS
                    last_clip['timestamp_end'] = last_clip.get('timestamp_start', 0) + last_clip['duration']
                    self.log(f"   â±ï¸ Ãšltimo clip extendido: {original_duration:.1f}s â†’ {last_clip['duration']:.1f}s (outro)")
            except Exception as e:
                self.log(f"   âš ï¸ Error extendiendo audio: {e}")

        if all_supported_media and generated_clips:
            has_videos = any(c.get('filename', '').lower().endswith(('.gif', '.mp4', '.mov', '.avi', '.webm', '.mkv')) for c in generated_clips)
            mode_desc = "imÃ¡genes + videos" if has_videos else "imÃ¡genes"
            self.log(f"\nðŸš€ Modo rÃ¡pido: ensamblaje directo con FFmpeg ({mode_desc}, sin MoviePy)...")

            # El nombre lleva el tema: un timestamp Unix suelto no permite
            # reconocer un video sin abrirlo.
            from infra.output_naming import build_video_filename
            requested_out = VideoConfig.OUTPUT_DIR / build_video_filename(
                platform, storyboard_data.get("topic", ""))
            out, using_local_safe_output = _resolve_safe_video_output_path(requested_out)
            if using_local_safe_output:
                self.log("âš ï¸ Unidad remota/WebDAV detectada para exportaciÃ³n de video.")
                self.log(f"   Guardando video base localmente para evitar ERROR_FILE_TOO_LARGE (0x800700DF): {out}")
            self.log(f"ðŸ“¹ Exportando video a: {out}")

            direct_ok = self._assemble_direct_ffmpeg(
                generated_clips, final_audio_path, str(out), res,
                transition_type=transition_type,
                transition_duration=transition_duration,
                enable_transition_sfx=enable_transition_sfx,
                transition_sfx_path=transition_sfx_path,
                apply_cinematic=apply_cinematic,
                cinematic_preset=cinematic_preset,
            )

            if direct_ok:
                file_size_mb = os.path.getsize(str(out)) / 1024 / 1024
                self.log(f"âœ… Video exportado: {file_size_mb:.1f} MB")

                result = {
                    'video_path': str(out),
                    'script': storyboard_data['script'],
                    'topic': storyboard_data['topic'],
                    'category': storyboard_data['category'],
                    'music_attribution': _music_attribution,
                    'music_used': _music_used,
                    'segments': storyboard_data.get('segments', []),
                    'audio_path': storyboard_data.get('audio_path'),
                    'final_audio_path': final_audio_path,
                    'subtitle_audio_path': subtitle_reference_audio
                }

                # Aplicar subtÃ­tulos dinÃ¡micos si estÃ¡n activos
                if add_subtitles and hasattr(self, '_dynamic_subtitle_wrapper'):
                    self.log("ðŸŽ¬ Aplicando subtÃ­tulos dinÃ¡micos al video final...")
                    subs_applied = False
                    _subtitle_sync = None
                    try:
                        segs = storyboard_data.get('segments', [])
                        if segs:
                            from pipeline.dynamic_subtitle_wrapper import DynamicSubtitleWrapper
                            wrapper = DynamicSubtitleWrapper(style=subtitle_style)
                            # Whisper alinea mucho mejor sobre la voz sola que
                            # sobre la mezcla con musica (misma linea de tiempo).
                            subtitle_audio_path = (
                                subtitle_reference_audio or final_audio_path
                                or storyboard_data.get('audio_path')
                            )
                            if subtitle_audio_path and not os.path.exists(str(subtitle_audio_path)):
                                subtitle_audio_path = None

                            ass_path = str(out).replace('.mp4', '.ass')
                            subtitle_language = storyboard_data.get('language') or None
                            wrapper.generate_ass_from_segments(
                                segs, ass_path,
                                video_width=res[0],
                                video_height=res[1],
                                audio_path=subtitle_audio_path,
                                language=subtitle_language
                            )
                            _subtitle_sync = dict(getattr(wrapper.engine, 'last_sync_details', None) or {})
                            self._add_hook_to_ass(ass_path, storyboard_data, res)

                            # Verificar que el ASS se generÃ³ con contenido
                            if not os.path.exists(ass_path) or os.path.getsize(ass_path) < 50:
                                self.log(f"âš ï¸ Archivo ASS no generado o vacÃ­o: {ass_path}")
                            else:
                                self.log(f"   ASS generado: {os.path.basename(ass_path)} ({os.path.getsize(ass_path)} bytes)")
                                video_with_subs = str(out).replace('.mp4', '_with_subs.mp4')
                                success = wrapper.engine.burn_subtitles_with_ffmpeg(
                                    str(out), ass_path, video_with_subs,
                                    video_width=res[0], video_height=res[1]
                                )
                                if success and os.path.exists(video_with_subs):
                                    try:
                                        os.remove(str(out))
                                        os.rename(video_with_subs, str(out))
                                        self.log(f"âœ… SubtÃ­tulos dinÃ¡micos aplicados (estilo: {subtitle_style})")
                                        result['video_path'] = str(out)
                                        subs_applied = True
                                    except Exception as e:
                                        self.log(f"âš ï¸ No se pudo reemplazar el video: {e}")
                                        result['video_path'] = video_with_subs
                                        subs_applied = True
                                else:
                                    self.log(f"âŒ burn_subtitles_with_ffmpeg fallÃ³ - el video NO tiene subtÃ­tulos")
                        else:
                            self.log(f"âš ï¸ No hay segmentos para generar subtÃ­tulos")
                    except Exception as e:
                        self.log(f"âŒ Error aplicando subtÃ­tulos dinÃ¡micos: {e}")
                        import traceback
                        self.log(f"   {traceback.format_exc().splitlines()[-1]}")

                    if not subs_applied:
                        self._burn_hook_only(result.get('video_path') or str(out), storyboard_data, res)
                        self.log(f"ðŸ”´ ATENCIÃ“N: El video final NO contiene subtÃ­tulos. "
                                 f"PodÃ©s aplicarlos manualmente con: python simple_subs.py")

                    result['audio_qa_problems'] = self.log_audio_qa(
                        video_path=result.get('video_path') or str(out),
                        audio_path=final_audio_path,
                        subtitle_sync=_subtitle_sync,
                    )
                else:
                    self._burn_hook_only(str(out), storyboard_data, res)
                    result['audio_qa_problems'] = self.log_audio_qa(
                        video_path=str(out), audio_path=final_audio_path
                    )

                # Esperar teaser si estÃ¡ en proceso
                if generate_short_teaser and platform == 'youtube' and teaser_thread:
                    self.log("â³ Esperando a que termine la generaciÃ³n del Short Teaser...")
                    teaser_thread.join(timeout=600)
                    if teaser_result:
                        result['teaser_video_path'] = teaser_result.get('video_path')
                        result['teaser_script'] = teaser_result.get('script')
                        result['teaser_duration'] = teaser_result.get('duration')
                        result['teaser_metadata'] = {
                            'segments': teaser_result.get('segments', []),
                            'audio_path': teaser_result.get('audio_path'),
                            'script': teaser_result.get('script', '')
                        }
                        self.log("âœ… Short Teaser generado exitosamente")

                return result
            else:
                self.log("âš ï¸ FFmpeg directo fallÃ³, intentando con MoviePy...")

        # === RUTA MOVIEPY (fallback o videos con efectos/clips de video) ===
        self.log(f"ðŸŽµ Cargando audio desde: {final_audio_path}")
        final, audio = self.contextual_assembler.assemble_video_from_prompts(
            generated_clips, final_audio_path, res, self.generated_media_dir,
            apply_cinematic=apply_cinematic, cinematic_preset=cinematic_preset,
            cinematic_intensity=cinematic_intensity,
            transition_type=transition_type, transition_duration=transition_duration,
            segments=storyboard_data['segments'],
            extra_duration_override=0 if audio_has_outro else None
        )
        
        if not final:
            self.log("âŒ ERROR: No se pudo ensamblar el video")
            return None
        
        if not audio:
            self.log("âŒ ERROR: No se pudo cargar el audio")
            return None
        
        self.log(f"âœ… Audio cargado: {audio.duration:.2f}s")

        # 3. SubtÃ­tulos (solo si NO se estÃ¡n usando subtÃ­tulos dinÃ¡micos)
        # Los subtÃ­tulos dinÃ¡micos se aplican despuÃ©s en dynamic_subtitle_wrapper
        # Solo usar MoviePy TextClip si los subtÃ­tulos dinÃ¡micos no estÃ¡n activos
        if add_subtitles and not hasattr(self, '_dynamic_subtitle_wrapper'):
            try:
                s = self.subtitle_gen.create_subtitle_clips(segments, res, subtitle_style)
                if s: final = CompositeVideoClip([final] + s)
            except Exception as e:
                # Si falla (por ejemplo, ImageMagick no disponible), continuar sin subtÃ­tulos MoviePy
                # Los subtÃ­tulos dinÃ¡micos se aplicarÃ¡n despuÃ©s si estÃ¡n configurados
                self.log(f"âš ï¸  No se pudieron crear subtÃ­tulos MoviePy (ImageMagick puede no estar disponible): {e}")
                self.log(f"   Continuando sin subtÃ­tulos MoviePy...")

        # 4. Audio Final
        self.log("ðŸŽµ Configurando audio final...")
        audio_layers = []
        
        # Asegurar que el audio principal estÃ© en la lista
        if audio:
            audio_layers.append(audio)
            self.log(f"   âœ… Audio principal agregado ({audio.duration:.2f}s)")
        else:
            self.log("   âŒ ERROR: No hay audio principal disponible")
            return None
        
        # Agregar SFX
        sfx_count = 0
        for c in generated_clips:
            if c.get('sfx_path') and os.path.exists(c['sfx_path']):
                try:
                    sfx_clip = AudioFileClip(c['sfx_path']).set_start(c['timestamp_start'])
                    audio_layers.append(sfx_clip)
                    sfx_count += 1
                except Exception as e:
                    self.log(f"   âš ï¸ Error cargando SFX {c['sfx_path']}: {e}")
        
        if sfx_count > 0:
            self.log(f"   âœ… {sfx_count} efectos de sonido agregados")
        
        # Agregar mÃºsica de fondo
        # NOTA: Si hay mÃºsica (bgm existe), el audio ya fue mezclado arriba con fade out
        # Solo necesitamos verificar que el audio_layers[0] sea el audio mezclado
        if bgm and os.path.exists(bgm) and final_audio_path != audio_path:
            # El audio fue mezclado arriba, asegurarnos de usar el archivo mix.mp3
            try:
                if os.path.exists(final_audio_path):
                    audio_layers[0] = AudioFileClip(final_audio_path)
                    self.log(f"   âœ… Usando audio pre-mezclado con mÃºsica (fade out 3s)")
            except Exception as e:
                self.log(f"   âš ï¸ Error cargando audio mezclado: {e}")

        # Crear audio compuesto
        if len(audio_layers) == 0:
            self.log("âŒ ERROR: No hay capas de audio para el video")
            return None
        
        try:
            # Si solo hay una capa, usar directamente (evita problemas con CompositeAudioClip)
            if len(audio_layers) == 1:
                final_audio = audio_layers[0]
                self.log(f"âœ… Audio final configurado (1 capa Ãºnica - sin mezcla)")
            else:
                # Solo usar CompositeAudioClip si hay mÃºltiples capas (SFX, mÃºsica separada, etc.)
                final_audio = CompositeAudioClip(audio_layers)
                self.log(f"âœ… Audio final configurado ({len(audio_layers)} capas mezcladas)")
            
            final = final.set_audio(final_audio)
        except Exception as e:
            self.log(f"âŒ ERROR al crear audio compuesto: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        # 5. Exportar
        from infra.output_naming import build_video_filename
        requested_out = VideoConfig.OUTPUT_DIR / build_video_filename(
            platform, storyboard_data.get("topic", ""))
        out, using_local_safe_output = _resolve_safe_video_output_path(requested_out)
        if using_local_safe_output:
            self.log("âš ï¸ Unidad remota/WebDAV detectada para exportaciÃ³n de video.")
            self.log(f"   Guardando video base localmente para evitar ERROR_FILE_TOO_LARGE (0x800700DF): {out}")
        self.log(f"ðŸ“¹ Exportando video a: {out}")
        
        # Verificar que el audio estÃ© configurado antes de exportar
        if final.audio is None:
            self.log("âš ï¸ ADVERTENCIA: El video no tiene audio configurado. Intentando agregar audio...")
            if audio:
                final = final.set_audio(audio)
                self.log("âœ… Audio agregado al video")
            else:
                self.log("âŒ ERROR: No hay audio disponible para el video")
        
        # Crear logger personalizado compatible con MoviePy
        # MoviePy necesita un objeto logger con mÃ©todos como iter_bar, no solo una funciÃ³n
        video_duration = final.duration if hasattr(final, 'duration') and final.duration else 0
        last_percent = [0]  # Usar lista para poder modificar desde el closure
        
        class MoviePyLogger:
            """Logger compatible con MoviePy que muestra progreso en terminal"""
            def __init__(self, log_func, total_duration):
                self.log_func = log_func
                self.total_duration = total_duration
                self.last_percent = 0
            
            def __call__(self, *args, **kwargs):
                """Maneja llamadas logger(message="...") y logger(t)"""
                if 'message' in kwargs:
                    return  # Ignorar mensajes de MoviePy
                if args and len(args) > 0:
                    t = args[0]
                    if t is not None and self.total_duration > 0:
                        percent = int((t / self.total_duration) * 100)
                        if percent != self.last_percent and percent % 5 == 0:
                            bar_length = 40
                            filled = int(bar_length * percent / 100)
                            bar = 'â–ˆ' * filled + 'â–‘' * (bar_length - filled)
                            self.log_func(f"   [{bar}] {percent}%")
                            self.last_percent = percent
            
            def iter_bar(self, chunk=None, t=None, **kwargs):
                """MÃ©todo requerido por MoviePy para iterar sobre chunks de audio o frames de video"""
                # MoviePy puede llamar con chunk (audio) o t (video frames)
                if t is not None:
                    # Es para video frames - retornar el array de tiempos
                    return t
                elif chunk is not None:
                    # Es para audio chunks - retornar el chunk
                    return chunk
                else:
                    # Fallback - retornar lo que sea que se pase
                    return chunk if chunk is not None else t
        
        # Usar FFmpeg directo para exportaciÃ³n mÃ¡s rÃ¡pida y optimizada
        self.log("ðŸš€ Exportando con FFmpeg directo (mÃ¡s rÃ¡pido y optimizado)...")
        
        # Determinar bitrate y preset segÃºn plataforma
        if is_vertical:
            video_bitrate = '6000k'  # 6 Mbps para shorts (9:16)
            preset = 'fast'  # MÃ¡s rÃ¡pido para shorts
        else:
            video_bitrate = '12000k'  # 12 Mbps para videos largos (16:9)
            preset = 'medium'  # Balance para videos largos
        
        self.log(f"   ðŸ“Š Bitrate: {video_bitrate}, Preset: {preset}")
        
        # Exportar con FFmpeg directo
        export_success = self._export_video_with_ffmpeg(
            final, 
            str(out),
            video_bitrate=video_bitrate,
            preset=preset,
            fps=30,
            video_duration=video_duration
        )
        
        if not export_success:
            # Fallback a MoviePy si FFmpeg falla
            self.log("âš ï¸ FFmpeg fallÃ³, usando MoviePy como fallback...")
            try:
                if video_duration > 0:
                    custom_logger = MoviePyLogger(self.log, video_duration)
                else:
                    custom_logger = 'bar'

                final.write_videofile(
                    str(out),
                    fps=30,
                    codec=get_optimal_h264_encoder(),
                    audio_codec='aac',
                    audio_bitrate='192k',
                    bitrate=video_bitrate,
                    preset=preset,
                    threads=4,
                    logger=custom_logger,
                    verbose=False
                )
            except Exception as moviepy_err:
                self.log(f"âš ï¸ MoviePy fallback tambiÃ©n fallÃ³: {moviepy_err}")

            # Verificar si MoviePy produjo un video vÃ¡lido
            try:
                from pipeline.video_export_manager import _probe_has_video_and_audio as _probe_check
                mv_has_v, _ = _probe_check(str(out), log_callback=self.log)
                if not mv_has_v and self.export_manager:
                    self.log("âš ï¸ MoviePy no generÃ³ video vÃ¡lido, intentando exportaciÃ³n directa con FFmpeg pipe...")
                    pipe_ok = self.export_manager._export_with_ffmpeg_pipe(
                        final, str(out), fps=30,
                        video_bitrate=video_bitrate, preset=preset,
                        video_duration=video_duration
                    )
                    if pipe_ok:
                        self.log("âœ… Video exportado correctamente con FFmpeg pipe directo")
            except Exception:
                pass

        # Verificar que el video se exportÃ³ correctamente y es reproducible
        if not os.path.exists(str(out)):
            self.log(f"âŒ ERROR: El video no se exportÃ³ correctamente")
            return None
        try:
            from pipeline.video_export_manager import _probe_has_video_and_audio, _probe_duration
            has_v, has_a = _probe_has_video_and_audio(str(out), log_callback=self.log)
            dur = _probe_duration(str(out))
            out_fsize = os.path.getsize(str(out))
            if not has_v:
                # Si ffprobe no detecta video pero el archivo es grande, aceptar
                if out_fsize > 5 * 1024 * 1024:
                    self.log(f"âš ï¸ ffprobe no detecta video pero el archivo es grande ({out_fsize / (1024*1024):.1f} MB), aceptando como vÃ¡lido")
                    has_v = True
                elif dur < 0.5:
                    self.log(f"âŒ ERROR: El video exportado estÃ¡ corrupto o no es vÃ¡lido (sin video o duraciÃ³n invÃ¡lida)")
                    return None
            if not has_a:
                self.log(f"âš ï¸ ADVERTENCIA: El video no tiene pista de audio; puede no reproducirse correctamente en algunos reproductores.")
        except Exception as probe_err:
            self.log(f"âš ï¸ No se pudo verificar el video con ffprobe: {probe_err}")
        file_size_mb = os.path.getsize(str(out)) / 1024 / 1024
        self.log(f"   âœ… Video exportado: {file_size_mb:.1f} MB")
        
        # MEJORA: Auto-Capítulos
        try:
            self._generate_youtube_chapters(storyboard_data, str(out))
            self.log("   ✅ Capítulos de YouTube generados exitosamente.")
        except Exception as e:
            self.log(f"   [WARN] Error generando capítulos: {e}")
        
        result = {
            'video_path': str(out), 
            'script': storyboard_data['script'], 
            'topic': storyboard_data['topic'], 
            'category': storyboard_data['category'], 
            'music_attribution': _music_attribution,
            'music_used': _music_used,
            'segments': storyboard_data.get('segments', []),  # Incluir segmentos para el preview
            'audio_path': storyboard_data.get('audio_path'),  # Incluir audio_path para el preview
            'final_audio_path': final_audio_path,
            'subtitle_audio_path': subtitle_reference_audio
        }
        
        # 6. Aplicar subtÃ­tulos dinÃ¡micos si estÃ¡n activos y el patch estÃ¡ aplicado
        if add_subtitles and hasattr(self, '_dynamic_subtitle_wrapper'):
            self.log("ðŸŽ¬ Aplicando subtÃ­tulos dinÃ¡micos al video final...")
            subs_applied = False
            _subtitle_sync = None
            try:
                segments = storyboard_data.get('segments', [])
                if segments:
                    wrapper = self._dynamic_subtitle_wrapper
                    # Whisper alinea mucho mejor sobre la voz sola que sobre la
                    # mezcla con musica (misma linea de tiempo).
                    subtitle_audio_path = (
                        subtitle_reference_audio or final_audio_path
                        or storyboard_data.get('audio_path')
                    )
                    if subtitle_audio_path and not os.path.exists(str(subtitle_audio_path)):
                        subtitle_audio_path = None

                    ass_path = str(out).replace('.mp4', '.ass')
                    subtitle_language = storyboard_data.get('language') or None
                    wrapper.generate_ass_from_segments(
                        segments, ass_path,
                        video_width=res[0], video_height=res[1],
                        audio_path=subtitle_audio_path,
                        language=subtitle_language
                    )
                    _subtitle_sync = dict(getattr(wrapper.engine, 'last_sync_details', None) or {})
                    self._add_hook_to_ass(ass_path, storyboard_data, res)

                    if not os.path.exists(ass_path) or os.path.getsize(ass_path) < 50:
                        self.log(f"âš ï¸ Archivo ASS no generado o vacÃ­o: {ass_path}")
                    else:
                        self.log(f"   ASS generado: {os.path.basename(ass_path)} ({os.path.getsize(ass_path)} bytes)")
                        video_with_subs = str(out).replace('.mp4', '_with_subs.mp4')
                        success = wrapper.engine.burn_subtitles_with_ffmpeg(
                            str(out), ass_path, video_with_subs,
                            video_width=res[0], video_height=res[1]
                        )

                        if success and os.path.exists(video_with_subs):
                            try:
                                os.remove(str(out))
                                os.rename(video_with_subs, str(out))
                                self.log("âœ… SubtÃ­tulos dinÃ¡micos aplicados al video final")
                                result['video_path'] = str(out)
                                subs_applied = True
                            except Exception as e:
                                self.log(f"âš ï¸ No se pudo reemplazar el video: {e}")
                                result['video_path'] = video_with_subs
                                subs_applied = True
                        else:
                            self.log(f"âŒ burn_subtitles_with_ffmpeg fallÃ³ - el video NO tiene subtÃ­tulos")
                else:
                    self.log(f"âš ï¸ No hay segmentos para generar subtÃ­tulos")
            except Exception as e:
                self.log(f"âŒ Error aplicando subtÃ­tulos dinÃ¡micos: {e}")
                import traceback
                self.log(f"   {traceback.format_exc().splitlines()[-1]}")

            if not subs_applied:
                self._burn_hook_only(result.get('video_path') or str(out), storyboard_data, res)
                self.log(f"ðŸ”´ ATENCIÃ“N: El video final NO contiene subtÃ­tulos. "
                         f"PodÃ©s aplicarlos manualmente con: python simple_subs.py")

            result['audio_qa_problems'] = self.log_audio_qa(
                video_path=result.get('video_path') or str(out),
                audio_path=final_audio_path,
                subtitle_sync=_subtitle_sync,
            )
        else:
            self._burn_hook_only(result.get('video_path') or str(out), storyboard_data, res)
            result['audio_qa_problems'] = self.log_audio_qa(
                video_path=result.get('video_path') or str(out),
                audio_path=final_audio_path,
            )

        # Esperar a que termine la generaciÃ³n del teaser si estÃ¡ en proceso
        if generate_short_teaser and platform == 'youtube' and teaser_thread:
            self.log("â³ Esperando a que termine la generaciÃ³n del Short Teaser...")
            teaser_thread.join(timeout=600)  # Timeout de 10 minutos
            
            if teaser_result:
                result['teaser_video_path'] = teaser_result.get('video_path')
                result['teaser_script'] = teaser_result.get('script')
                result['teaser_duration'] = teaser_result.get('duration')
                # Incluir metadata del teaser con segmentos para el preview
                result['teaser_metadata'] = {
                    'segments': teaser_result.get('segments', []),
                    'audio_path': teaser_result.get('audio_path'),
                    'script': teaser_result.get('script', '')
                }
                self.log("âœ… Short Teaser generado exitosamente en paralelo")
            else:
                self.log("âš ï¸ Short Teaser no se pudo generar (puede estar aÃºn procesÃ¡ndose)")
        
        return result
