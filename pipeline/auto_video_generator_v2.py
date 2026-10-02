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
from pipeline.auto_video_assembly_mixin import AutoVideoAssemblyMixin


class AutoVideoGenerator(AutoVideoAssemblyMixin):
    """
    Clase principal que coordina el NUEVO flujo de generaciÃ³n contextual.
    Flujo: Guion (Gemini) -> Audio (TTS) -> Tiempos (Whisper) -> 
           Prompts Visuales (Gemini) -> CreaciÃ³n Visual (Runway/Pexels) -> Ensamblaje
    """
    
    def __init__(self, parent_window=None):
        VideoConfig.setup_directories()
        
        # --- MÃ³dulos de IA ---
        self.ai_factory = AIFactory.get_instance()
        self.gemini_client = self.ai_factory.get_llm_client() if GEMINI_AVAILABLE else None
        
        self.runway_api_key = os.getenv("RUNWAYML_API_SECRET") 
        if RUNWAY_AVAILABLE and self.runway_api_key:
            self.runway_client = RunwayML(api_key=self.runway_api_key) 
        else:
            self.runway_client = None
        
        # --- Directorio de Recursos Generados ---
        self.generated_media_dir = VideoConfig.TEMP_DIR / "generated_media"
        self.generated_media_dir.mkdir(exist_ok=True, parents=True)
        
        # --- MÃ³dulos de Video/Audio ---
        self.tts = TextToSpeechGenerator()
        self.subtitle_gen = SubtitleGenerator() 
        self.contextual_assembler = ContextualVideoAssembler()
        
        self.jamendo_client_id = os.getenv("JAMENDO_CLIENT_ID")
        self.freesound_api_key = os.getenv("FREESOUND_API_KEY")

        # --- Downloader de Stock (Pexels) ---
        self.downloader = ResourceDownloader()
        self.downloader.download_dir = self.generated_media_dir
        self.pexels_api_key = os.getenv("PEXELS_API_KEY")

        if RECRAFT_AVAILABLE and os.getenv("RECRAFT_API_KEY"):
            try:
                recraft_client = RecraftClient(log_callback=self.log)
                self.recraft_client = (
                    recraft_client if getattr(recraft_client, "api_key", None) else None
                )
            except Exception as e:
                self.log(f"âš ï¸ Error inicializando Recraft: {e}")
                self.recraft_client = None
        else:
            self.recraft_client = None

        # Inicializar Google AI Image client (Gemini)
        if GOOGLE_AI_IMAGE_AVAILABLE:
            try:
                google_ai_client = GoogleAiImageClient(log_callback=self.log)
                self.google_ai_image_client = (
                    google_ai_client if getattr(google_ai_client, "client_available", False) else None
                )
            except Exception as e:
                self.log(f"âš ï¸ Error inicializando Google AI Image: {e}")
                self.google_ai_image_client = None
        else:
            self.google_ai_image_client = None

        # Inicializar Stability AI client
        if STABILITY_AVAILABLE and os.getenv("STABILITY_API_KEY"):
            try:
                self.stability_ultra_client = StabilityClient(log_callback=self.log, model="ultra")
                self.stability_core_client  = StabilityClient(log_callback=self.log, model="core")
            except Exception as e:
                self.log(f"Error inicializando Stability AI: {e}")
                self.stability_ultra_client = None
                self.stability_core_client  = None
        else:
            self.stability_ultra_client = None
            self.stability_core_client  = None

        # Inicializar ComfyUI/Vast.ai client (opcional). No hace health check
        # aqui: la instancia Vast puede estar apagada hasta que el usuario la use.
        if COMFYUI_AVAILABLE:
            try:
                self.comfyui_image_client = ComfyUiImageClient(log_callback=self.log)
            except Exception as e:
                self.log(f"Error inicializando ComfyUI: {e}")
                self.comfyui_image_client = None
        else:
            self.comfyui_image_client = None

        # Inicializar Google Images client
        if GOOGLE_IMAGES_AVAILABLE:
            try:
                self.google_images_client = GoogleImagesClient(gemini_client=self.gemini_client)
            except Exception as e:
                self.log(f"âš ï¸ Error inicializando Google Images: {e}")
                self.google_images_client = None
        else:
            self.google_images_client = None
        
        # Inicializar Wikimedia client
        if WIKIMEDIA_AVAILABLE:
            try:
                self.wikimedia_client = WikimediaClient(gemini_client=self.gemini_client)
            except Exception as e:
                self.log(f"âš ï¸ Error inicializando Wikimedia: {e}")
                self.wikimedia_client = None
        else:
            self.wikimedia_client = None
        
        # Inicializar FAL.AI (Flux + Kling/Luma) -- opcional, solo si hay FAL_KEY
        self.fal_image_client = None
        self.fal_video_client = None
        try:
            from ai.fal_ai_client import build_fal_clients, is_fal_configured
            if is_fal_configured():
                img_c, vid_c = build_fal_clients(log_callback=self.log)
                self.fal_image_client = img_c
                self.fal_video_client = vid_c
        except Exception as e:
            self.log(f"[FAL] Error inicializando FAL.AI: {e}")

        # Inicializar VideoGenerationManager
        if VideoGenerationManager:
            self.video_gen_manager = VideoGenerationManager(
                log_callback=self.log,
                runway_client=self.runway_client,
                google_images_client=self.google_images_client,
                wikimedia_client=self.wikimedia_client,
                generated_media_dir=self.generated_media_dir,
                fal_image_client=self.fal_image_client,
                fal_video_client=self.fal_video_client,
            )
        else:
            self.video_gen_manager = None
        
        # Inicializar PromptProcessor
        if PromptProcessor:
            self.prompt_processor = PromptProcessor(
                log_callback=self.log,
                gemini_client=self.gemini_client
            )
        else:
            self.prompt_processor = None
        
        # Inicializar VideoExportManager
        if VideoExportManager:
            self.export_manager = VideoExportManager(log_callback=self.log)
        else:
            self.export_manager = None
        
        # Inicializar StoryboardGenerator
        if StoryboardGenerator:
            self.storyboard_generator = StoryboardGenerator(
                log_callback=self.log,
                gemini_client=self.gemini_client,
                tts=self.tts,
                subtitle_gen=self.subtitle_gen,
                generated_media_dir=self.generated_media_dir,
                jamendo_client_id=self.jamendo_client_id,
                assemble_video_callback=self.assemble_video_from_storyboard
            )
        else:
            self.storyboard_generator = None
        
        # Inicializar ImageGenerationManager
        if ImageGenerationManager:
            self.image_gen_manager = ImageGenerationManager(
                log_callback=self.log,
                generated_media_dir=self.generated_media_dir,
                recraft_client=self.recraft_client,
                google_ai_image_client=self.google_ai_image_client,
                google_images_client=self.google_images_client,
                wikimedia_client=self.wikimedia_client,
                prompt_processor=self.prompt_processor,
                fal_image_client=self.fal_image_client,
                stability_ultra_client=self.stability_ultra_client,
                stability_core_client=self.stability_core_client,
                comfyui_image_client=self.comfyui_image_client,
            )
        else:
            self.image_gen_manager = None

        print("âœ… Auto Video Generator (Contextual v3.0 - Heavy) inicializado")

    def log(self, message):
        """Helper simple para logging en consola."""
        print(message, flush=True)

    # --- MÃ‰TODOS DE GENERACIÃ“N DE VIDEO CON FALLBACK ---
    # Delegados a VideoGenerationManager si estÃ¡ disponible


    def generate_video_with_fallback(self, prompt, output_path, is_vertical=False, duration=4,
                                    preferred_provider='fal', image_path=None,
                                    image_url=None, fal_model='kling'):
        """
        Genera video con sistema de fallback en cascada.

        Args:
            prompt: Prompt visual para el video
            output_path: Ruta donde guardar el video
            is_vertical: Si el video debe ser vertical (9:16)
            duration: DuraciÃ³n en segundos
            preferred_provider: 'fal' o 'runway'
            image_path: Ruta a imagen base (para FAL I2V con Kling/Luma)
            image_url: URL publica alternativa a image_path (FAL I2V)
            fal_model: 'kling' | 'kling-pro' | 'luma' (solo aplica a FAL)

        Returns:
            str: Ruta al video generado, o None si todos fallaron
        """
        if self.video_gen_manager:
            return self.video_gen_manager.generate_video_with_fallback(
                prompt=prompt,
                output_path=output_path,
                is_vertical=is_vertical,
                duration=duration,
                preferred_provider=preferred_provider,
                image_path=image_path,
                image_url=image_url,
                fal_model=fal_model,
            )
        return None

    # ------------------------------------------------------------------
    # Fase Image-to-Video por segmento (Kling/Luma/Runway)
    # ------------------------------------------------------------------
    def _generate_i2v_clips_for_segments(self, storyboard_data, platform,
                                         video_provider='fal',
                                         fal_video_model=None):
        if not self.video_gen_manager:
            self.log("[I2V] VideoGenerationManager no disponible; se omite fase I2V")
            return 0

        vp = str(video_provider or 'none').strip().lower()
        if vp in ('', 'none'):
            return 0

        segments = storyboard_data.get('segments', []) if isinstance(storyboard_data, dict) else []
        if not segments:
            return 0

        is_vertical = platform in ('tiktok', 'reels', 'youtube_short', 'youtube_vertical', '9:16')

        try:
            from infra.video_config import VideoConfig
            i2v_dir = VideoConfig.TEMP_DIR / "i2v_clips"
        except Exception:
            from pathlib import Path as _P
            i2v_dir = _P("auto_videos/temp/i2v_clips")
        i2v_dir.mkdir(parents=True, exist_ok=True)

        fal_model = (fal_video_model or 'kling').lower()
        total = len(segments)
        
        # MEJORA: Generación Concurrente de I2V
        import concurrent.futures
        
        self.log(f"\n[I2V] Generando clips concurrentemente -> provider={vp}, model={fal_model}, total={total}")
        
        # Agrupar peticiones únicas por imagen para no regenerar la misma imagen
        unique_tasks = {}
        
        for idx, seg in enumerate(segments):
            existing_video = (seg.get('video_path') or '').strip() if isinstance(seg, dict) else ''
            if existing_video and os.path.exists(existing_video):
                continue
                
            image_path = (seg.get('image_path') or '').strip() if isinstance(seg, dict) else ''
            visual_prompt = str(seg.get('visual_prompt') or seg.get('motion_prompt') or '').strip()
            
            if not image_path and not visual_prompt:
                continue
                
            duration_s = 5
            try:
                raw_dur = seg.get('duration') or seg.get('duration_seconds')
                if raw_dur:
                    d = float(raw_dur)
                    duration_s = 10 if d > 7 else 5
            except Exception:
                duration_s = 5
                
            assigned = seg.get('assigned_filename') or f"segment_{idx + 1:03d}"
            out_path = str(i2v_dir / f"{assigned}_i2v.mp4")
            
            # Usar image_path como llave si existe, sino el prompt visual
            task_key = image_path if image_path else visual_prompt
            
            if task_key not in unique_tasks:
                unique_tasks[task_key] = {
                    'prompt': visual_prompt or "slow dramatic camera zoom, cinematic lighting, dust particles",
                    'output_path': out_path,
                    'is_vertical': is_vertical,
                    'duration': duration_s,
                    'image_path': image_path if image_path and os.path.exists(image_path) else None,
                    'fal_model': fal_model,
                    'vp': vp,
                    'target_segments': [seg]
                }
            else:
                # Si es la misma imagen, agrupar
                unique_tasks[task_key]['target_segments'].append(seg)
                
        generated = 0
        failed = 0
        
        if not unique_tasks:
            self.log("[I2V] No hay nuevas tareas de generacion I2V pendientes.")
            return 0
            
        def process_task(task):
            clip = self.generate_video_with_fallback(
                prompt=task['prompt'],
                output_path=task['output_path'],
                is_vertical=task['is_vertical'],
                duration=task['duration'],
                preferred_provider=task['vp'],
                image_path=task['image_path'],
                fal_model=task['fal_model'],
            )
            return task, clip

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_task = {executor.submit(process_task, task): task for task in unique_tasks.values()}
            for future in concurrent.futures.as_completed(future_to_task):
                try:
                    task, clip = future.result()
                    if clip and os.path.exists(clip):
                        for seg in task['target_segments']:
                            seg['video_path'] = clip
                            seg['video_source'] = f"{task['vp']}_{task['fal_model']}" if task['vp'] == 'fal' else task['vp']
                            generated += 1
                        self.log(f"   [I2V] ✅ Clip generado: {task['output_path']}")
                    else:
                        failed += len(task['target_segments'])
                        self.log(f"   [I2V] ❌ Fallo generando clip para {task['output_path']}")
                except Exception as exc:
                    failed += len(future_to_task[future]['target_segments'])
                    self.log(f"   [I2V] ⚠️ Excepcion generando clip: {exc}")

        self.log(f"[I2V] Completado -> generados={generated}, fallidos={failed}")
        return generated

    # --- NUEVO: MÃ‰TODOS PARA MODO MANUAL IA (JSON) ---
    def generate_manual_prompt_text(self, topic, category, duration, language='es',
                                    research_context=None, video_format=None, platform=None):
        """Delega a StoryboardGenerator si estÃ¡ disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.generate_manual_prompt_text(
                topic, category, duration, language, research_context=research_context,
                video_format=video_format, platform=platform)
        # Fallback bÃ¡sico
        lang_str = "SPANISH" if language == 'es' else "ENGLISH"
        return f"""
ActÃºa como un productor de video experto. Necesito un guion tÃ©cnico en formato JSON para un video de {duration} segundos sobre "{topic}" (CategorÃ­a: {category}).

El JSON debe tener ESTRICTAMENTE esta estructura:
{{
  "title": "TÃ­tulo del Video",
  "scenes": [
    {{
      "narration": "Texto de narraciÃ³n en {lang_str}.",
      "visual_prompt": "Prompt visual detallado en INGLÃ‰S (estilo cinematogrÃ¡fico).",
      "sfx_tag": "Palabra clave de sonido (InglÃ©s) o 'none'.",
      "overlay_tag": "Palabra clave de GIF/Sticker (InglÃ©s) o 'none'."
    }}
  ]
}}

Reglas:
1. Calcula aproximadamente {max(3, int(duration/6))} escenas.
2. La narraciÃ³n debe ser en {lang_str}.
3. Responde SOLO con el cÃ³digo JSON.
"""
    def generate_scenes_json_batched(self, topic, category, duration, language='es',
                                     research_context=None, video_format=None, platform=None,
                                     progress_callback=None,
                                     opening_style="hook_overlay_v1"):
        """Delega a StoryboardGenerator si esta disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.generate_scenes_json_batched(
                topic, category, duration, language=language,
                research_context=research_context, video_format=video_format,
                platform=platform, progress_callback=progress_callback,
                opening_style=opening_style)
        self.log("StoryboardGenerator no disponible para generacion JSON en batches")
        return None

    def process_manual_json(self, json_data, voice_id=None, language='es', rate="+0%", max_duration: float = 0):
        """Delega a StoryboardGenerator si estÃ¡ disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.process_manual_json(json_data, voice_id, language, rate=rate, max_duration=max_duration)
        # Fallback: implementaciÃ³n bÃ¡sica (no recomendado)
        self.log("âš ï¸ StoryboardGenerator no disponible, usando fallback bÃ¡sico")
        return None

    def generate_storyboard_data(self, topic: str, category: str, platform: str = 'youtube',
                                 custom_duration: Optional[int] = None,
                                 voice_id: Optional[str] = None,
                                 find_auto_music: bool = True,
                                 style: str = "Estilo Realista / Cinematografico",
                                 language: str = 'es',
                                 rate: str = "+0%",
                                 pre_research_snippets: list = None,
                                 format_archetype: str = "",
                                 opening_style: str = "hook_overlay_v1"):
        """Delega a StoryboardGenerator si esta disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.generate_storyboard_data(
                topic, category, platform, custom_duration, voice_id, find_auto_music, style, language,
                rate=rate, pre_research_snippets=pre_research_snippets,
                format_archetype=format_archetype,
                opening_style=opening_style,
            )
        self.log("âš ï¸ StoryboardGenerator no disponible, usando fallback bÃ¡sico")
        return None

    def generate_short_teaser_from_long_video(self, long_video_storyboard, language='es', voice_id=None,
                                               disable_wikimedia=False, existing_teaser_storyboard=None,
                                               rate="+0%",
                                               mode='standalone'):
        """
        Genera un Short teaser (30-60 segundos) en formato vertical 9:16 a partir de un video largo.
        El teaser incluye un hook, resumen del contenido y CTA al final.

        Args:
            long_video_storyboard: Storyboard del video largo completo
            language: Idioma del teaser
            voice_id: ID de voz para TTS (opcional)
            disable_wikimedia: (OBSOLETO) ParÃ¡metro mantenido por compatibilidad - Google Images y Wikimedia eliminados
            existing_teaser_storyboard: Storyboard del teaser previo (para reutilizar audio/segmentos/imÃ¡genes)
            rate: Velocidad de habla Edge-TTS, ej: '+0%', '+30%'

        Returns:
            dict con 'video_path', 'script', 'topic', 'category' del short teaser, o None si falla
        """
        # Asegurar que los subtÃ­tulos dinÃ¡micos estÃ©n activos para el teaser
        # (estilo capcut para shorts)
        if not hasattr(self, '_dynamic_subtitle_wrapper'):
            try:
                from pipeline.dynamic_subtitle_wrapper import patch_subtitle_generation
                patch_subtitle_generation(self, 'capcut')
                self.log("   âœ… SubtÃ­tulos dinÃ¡micos activados para teaser (estilo: capcut)")
            except Exception as e:
                self.log(f"   âš ï¸ No se pudo activar subtÃ­tulos dinÃ¡micos: {e}")
        
        # Delegar a StoryboardGenerator si estÃ¡ disponible
        if self.storyboard_generator:
            return self.storyboard_generator.generate_short_teaser_from_long_video(
                long_video_storyboard, language, voice_id, disable_wikimedia, existing_teaser_storyboard,
                rate=rate, mode=mode
            )
        # Fallback: implementaciÃ³n bÃ¡sica (no recomendado)
        self.log("âš ï¸ StoryboardGenerator no disponible, usando fallback bÃ¡sico")
        return None

    def _assemble_existing_teaser(self, existing_teaser_storyboard, long_video_storyboard, disable_wikimedia=False):
        """Delega a StoryboardGenerator si estÃ¡ disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator._assemble_existing_teaser(
                existing_teaser_storyboard, long_video_storyboard, disable_wikimedia
            )
        # Fallback: implementaciÃ³n bÃ¡sica (no recomendado)
        self.log("âš ï¸ StoryboardGenerator no disponible, usando fallback bÃ¡sico")
        return None

    def _group_segments_for_images(self, segments, images_per_segment_ratio=1.0):
        """Delega a PromptProcessor si estÃ¡ disponible"""
        if self.prompt_processor:
            return self.prompt_processor.group_segments_for_images(segments, images_per_segment_ratio)
        # Fallback: implementaciÃ³n bÃ¡sica
        if images_per_segment_ratio <= 1.0:
            return [[seg] for seg in segments]
        groups = []
        current_group = []
        segments_per_image = int(images_per_segment_ratio)
        for i, seg in enumerate(segments):
            current_group.append(seg)
            if len(current_group) >= segments_per_image or i == len(segments) - 1:
                groups.append(current_group)
                current_group = []
        return groups
    
    def _apply_style_to_prompt(self, visual_prompt, style):
        """Delega a PromptProcessor si estÃ¡ disponible"""
        if self.prompt_processor:
            return self.prompt_processor.apply_style_to_prompt(visual_prompt, style)
        # Fallback: retornar prompt sin modificar
        return visual_prompt
    
    def regenerate_visual_prompts_with_style(self, storyboard_data, style):
        """Delega a PromptProcessor si estÃ¡ disponible"""
        if self.prompt_processor:
            return self.prompt_processor.regenerate_visual_prompts_with_style(storyboard_data, style)
        # Fallback: retornar storyboard sin modificar
        return storyboard_data
    
    def _combine_prompts(self, segment_group):
        """Delega a PromptProcessor si estÃ¡ disponible"""
        if self.prompt_processor:
            return self.prompt_processor.combine_prompts(segment_group)
        # Fallback: retornar prompt del primer segmento
        if segment_group:
            return segment_group[0].get('visual_prompt', '')
        return ''

    def generate_all_images_for_storyboard(self, storyboard_data, platform,
                                           use_wikimedia=False, disable_wikimedia=False,
                                           use_real_images=True, use_google_images=True,
                                           enable_real_images_mix=False, test_mode=False,
                                           image_provider='auto', images_per_segment_ratio=1.0,
                                           interleave_images=False, style='Cinematic',
                                           regenerate_prompts=False, project_path=None,
                                           **kwargs):
        """Delega a ImageGenerationManager si está disponible"""
        if self.image_gen_manager:
            # Cargar contexto del guión para que los neg prompts sean inteligentes
            self.image_gen_manager.set_storyboard_context(storyboard_data)
            return self.image_gen_manager.generate_all_images_for_storyboard(
                storyboard_data, platform,
                use_wikimedia, disable_wikimedia,
                use_real_images, use_google_images,
                enable_real_images_mix, test_mode,
                image_provider, images_per_segment_ratio,
                interleave_images, style,
                regenerate_prompts, project_path,
                **kwargs
            )
        # Fallback: implementaciÃ³n bÃ¡sica (no recomendado)
        self.log("âš ï¸ ImageGenerationManager no disponible, usando fallback bÃ¡sico")
        return storyboard_data

    def export_recraft_prompts_to_txt(self, storyboard_data, platform, output_path,
                                      images_per_segment_ratio=1.0,
                                      interleave_images=False, style='Photorealism',
                                      regenerate_prompts=False, project_path=None):
        """Delega a ImageGenerationManager la exportación del TXT para Recraft."""
        if self.image_gen_manager:
            return self.image_gen_manager.export_recraft_prompts_to_txt(
                storyboard_data=storyboard_data,
                platform=platform,
                output_path=output_path,
                images_per_segment_ratio=images_per_segment_ratio,
                interleave_images=interleave_images,
                style=style,
                regenerate_prompts=regenerate_prompts,
                project_path=project_path,
            )
        self.log("âš ï¸ ImageGenerationManager no disponible, no se pudo exportar TXT de prompts Recraft")
        return None

    def get_recraft_prompt_for_segment(self, storyboard_data, platform, segment_index,
                                       images_per_segment_ratio=1.0,
                                       interleave_images=False, style='Photorealism',
                                       regenerate_prompts=False):
        """Delega a ImageGenerationManager la resolución de prompts Recraft por segmento."""
        if self.image_gen_manager:
            self.image_gen_manager.set_storyboard_context(storyboard_data)
            return self.image_gen_manager.get_recraft_prompt_for_segment(
                storyboard_data=storyboard_data,
                platform=platform,
                segment_index=segment_index,
                images_per_segment_ratio=images_per_segment_ratio,
                interleave_images=interleave_images,
                style=style,
                regenerate_prompts=regenerate_prompts,
            )
        self.log("âš ï¸ ImageGenerationManager no disponible, no se pudo resolver prompt Recraft por segmento")
        return None
    
    
    
    

    

    # ------------------------------------------------------------------
    # QA de audio/sync del ensamblaje
    #
    # Los tres bugs del 2026-08-18 (auto-ducking invalido, swoosh saltado,
    # cover frame sin padding) llegaron a produccion porque cada uno degradaba
    # EN SILENCIO: un [WARN] perdido entre 400 lineas de log. Este bloque deja
    # el estado real de la cadena de audio a la vista en cada render.
    # ------------------------------------------------------------------






    # Zoom suave por defecto cuando los efectos cinematograficos estan apagados:
    # un still totalmente quieto mata la retencion en un Short.
    DEFAULT_MOTION_ZOOM = 1.08








        
if __name__ == "__main__":
    print("Ejecuta video-opt-app.py para usar la interfaz.")
