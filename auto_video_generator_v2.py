# auto_video_generator_v2.py
import builtins
import importlib.util
import os
import time
import requests
from pathlib import Path
from datetime import datetime
import json
from ai_factory import AIFactory
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
    from pydub.silence import detect_nonsilent
    
    # Configurar la ruta de FFmpeg para pydub (EspecÃ­fico para Windows)
    import platform
    if platform.system() == "Windows":
        # Usar primero la deteccion central, que ya valida ffmpeg + ffprobe.
        configured_dir = None
        try:
            from video_config import VideoConfig as _VideoConfig
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
    from gemini_ai_client import GeminiAiClient
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("[!] gemini_ai_client.py no encontrado. La generacion de guion contextual fallara.")

try:
    from runwayml import RunwayML, TaskFailedError
    RUNWAY_AVAILABLE = True
except ImportError:
    RUNWAY_AVAILABLE = False
    print("[!] SDK runwayml no encontrado (opcional, se usan otros proveedores).")

try:
    from music_recommender import (
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
    from google_search_api import search_google_trends
    GOOGLE_SEARCH_AVAILABLE = True
except ImportError:
    GOOGLE_SEARCH_AVAILABLE = False
    print("[!] google_search_api.py no encontrado. Los guiones no tendran investigacion.")

try:
    from sfx_client import find_and_download_sfx
    SFX_AVAILABLE = False  # Desactivado por defecto
except ImportError:
    SFX_AVAILABLE = False
    print("[!] sfx_client.py no encontrado. La busqueda de SFX fallara.")

try:
    from giphy_client import find_and_download_gif
    GIPHY_AVAILABLE = True
except ImportError:
    GIPHY_AVAILABLE = False
    print("[!] giphy_client.py no encontrado. Los Overlays fallaran.")

try:
    from cinematic_effects import CinematicEffectsEngine, ContextDetector
    CINEMATIC_AVAILABLE = True
except ImportError:
    CINEMATIC_AVAILABLE = False
    print("[!] cinematic_effects.py no encontrado. Efectos cinematograficos desactivados.")


try:
    from recraft_client import RecraftClient
    RECRAFT_AVAILABLE = True
    print("[OK] Recraft client cargado")
except ImportError:
    RECRAFT_AVAILABLE = False
    print("[!] recraft_client.py no encontrado. Recraft no funcionara.")

# Importar clientes de Google Images y Wikimedia
try:
    from google_images_client import GoogleImagesClient
    GOOGLE_IMAGES_AVAILABLE = True
    print("[OK] Google Images client cargado")
except ImportError:
    GOOGLE_IMAGES_AVAILABLE = False
    print("[!] google_images_client.py no encontrado. La busqueda de imagenes en Google Images no funcionara.")

try:
    from wikimedia_client import WikimediaClient
    WIKIMEDIA_AVAILABLE = True
    print("[OK] Wikimedia client cargado")
except ImportError:
    WIKIMEDIA_AVAILABLE = False
    print("[!] wikimedia_client.py no encontrado. La busqueda de imagenes en Wikimedia no funcionara.")

try:
    from google_ai_image_client import GoogleAiImageClient
    GOOGLE_AI_IMAGE_AVAILABLE = True
    print("[OK] Google AI Image client cargado")
except ImportError:
    GOOGLE_AI_IMAGE_AVAILABLE = False
    print("[!] google_ai_image_client.py no encontrado. Google AI Image no funcionara.")

try:
    from stability_client import StabilityClient
    STABILITY_AVAILABLE = True
    print("[OK] Stability AI client cargado")
except ImportError:
    STABILITY_AVAILABLE = False
    print("[!] stability_client.py no encontrado. Stability AI no funcionara.")

try:
    from comfyui_image_client import ComfyUiImageClient
    COMFYUI_AVAILABLE = True
    print("[OK] ComfyUI image client cargado")
except ImportError:
    COMFYUI_AVAILABLE = False
    print("[!] comfyui_image_client.py no encontrado. ComfyUI no funcionara.")

# ========== IMPORTAR CONFIGURACION DESDE MODULO SEPARADO ==========
# VideoConfig ha sido movido a video_config.py para mejor organizacion
try:
    from video_config import VideoConfig
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
    from resource_downloader import ResourceDownloader
except ImportError:
    print("âš ï¸ resource_downloader.py no encontrado, ResourceDownloader no disponible")
    ResourceDownloader = None


# ========== IMPORTAR GENERADOR DE VOZ DESDE MÃ“DULO SEPARADO ==========
# TextToSpeechGenerator ha sido movido a tts_generator.py
try:
    from tts_generator import TextToSpeechGenerator
except ImportError:
    print("âš ï¸ tts_generator.py no encontrado, TextToSpeechGenerator no disponible")
    TextToSpeechGenerator = None

# Nota: TextToSpeechGenerator estÃ¡ en tts_generator.py
# Nota: SubtitleGenerator estÃ¡ en subtitle_generator.py

# ========== IMPORTAR GENERADOR DE SUBTÃTULOS DESDE MÃ“DULO SEPARADO ==========
try:
    from subtitle_generator import SubtitleGenerator
except ImportError:
    print("âš ï¸ subtitle_generator.py no encontrado, SubtitleGenerator no disponible")
    SubtitleGenerator = None

# ========== IMPORTAR ENSAMBLADOR DE VIDEO DESDE MÃ“DULO SEPARADO ==========
# ContextualVideoAssembler ha sido movido a video_assembler.py
try:
    from video_assembler import ContextualVideoAssembler
except ImportError:
    print("âš ï¸ video_assembler.py no encontrado, ContextualVideoAssembler no disponible")
    ContextualVideoAssembler = None
                                                        
# ========== IMPORTAR VIDEO GENERATION MANAGER DESDE MÃ“DULO SEPARADO ==========
# VideoGenerationManager ha sido movido a video_generation_manager.py
try:
    from video_generation_manager import VideoGenerationManager
except ImportError:
    print("âš ï¸ video_generation_manager.py no encontrado, VideoGenerationManager no disponible")
    VideoGenerationManager = None

# ========== IMPORTAR PROMPT PROCESSOR DESDE MÃ“DULO SEPARADO ==========
# PromptProcessor ha sido movido a prompt_processor.py
try:
    from prompt_processor import PromptProcessor
except ImportError:
    print("âš ï¸ prompt_processor.py no encontrado, PromptProcessor no disponible")
    PromptProcessor = None

# ========== IMPORTAR VIDEO EXPORT MANAGER DESDE MÃ“DULO SEPARADO ==========
# VideoExportManager ha sido movido a video_export_manager.py
try:
    from video_export_manager import VideoExportManager
except ImportError:
    print("âš ï¸ video_export_manager.py no encontrado, VideoExportManager no disponible")
    VideoExportManager = None

try:
    from storyboard_generator import StoryboardGenerator
except ImportError:
    print("âš ï¸ storyboard_generator.py no encontrado, StoryboardGenerator no disponible")
    StoryboardGenerator = None

try:
    from image_generation_manager import ImageGenerationManager
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
class AutoVideoGenerator:
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
        self.giphy_api_key = os.getenv("GIPHY_API_KEY")

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
            from fal_ai_client import build_fal_clients, is_fal_configured
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

    def _generate_video_with_leonardo_motion(self, image_path, output_path, duration=4):
        """Genera video desde imagen usando Leonardo Motion API"""
        if self.video_gen_manager:
            return self.video_gen_manager.generate_video_with_leonardo_motion(image_path, output_path, duration)
        return None

    def _generate_video_with_fal(self, prompt, output_path, is_vertical=False, duration=4):
        """Genera video desde prompt usando Fal.ai"""
        if self.video_gen_manager:
            return self.video_gen_manager.generate_video_with_fal(prompt, output_path, is_vertical, duration)
        return None

    def _generate_video_with_runway(self, prompt, output_path, is_vertical=False, duration=4):
        """Genera video desde prompt usando Runway Gen-3"""
        if self.video_gen_manager:
            return self.video_gen_manager.generate_video_with_runway(prompt, output_path, is_vertical, duration)
        return None

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
            from video_config import VideoConfig
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
                                     progress_callback=None):
        """Delega a StoryboardGenerator si esta disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.generate_scenes_json_batched(
                topic, category, duration, language=language,
                research_context=research_context, video_format=video_format,
                platform=platform, progress_callback=progress_callback)
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
                                 pre_research_snippets: list = None):
        """Delega a StoryboardGenerator si esta disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.generate_storyboard_data(
                topic, category, platform, custom_duration, voice_id, find_auto_music, style, language,
                rate=rate, pre_research_snippets=pre_research_snippets
            )
        self.log("âš ï¸ StoryboardGenerator no disponible, usando fallback bÃ¡sico")
        return None

    def generate_short_teaser_from_long_video(self, long_video_storyboard, language='es', voice_id=None,
                                               disable_wikimedia=False, existing_teaser_storyboard=None,
                                               rate="+0%"):
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
                from dynamic_subtitle_wrapper import patch_subtitle_generation
                patch_subtitle_generation(self, 'capcut')
                self.log("   âœ… SubtÃ­tulos dinÃ¡micos activados para teaser (estilo: capcut)")
            except Exception as e:
                self.log(f"   âš ï¸ No se pudo activar subtÃ­tulos dinÃ¡micos: {e}")
        
        # Delegar a StoryboardGenerator si estÃ¡ disponible
        if self.storyboard_generator:
            return self.storyboard_generator.generate_short_teaser_from_long_video(
                long_video_storyboard, language, voice_id, disable_wikimedia, existing_teaser_storyboard,
                rate=rate
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
    
    def _export_video_with_ffmpeg(self, video_clip, output_path, video_bitrate='8000k', 
                                   preset='medium', fps=30, video_duration=0):
        """Delega a VideoExportManager si estÃ¡ disponible"""
        if self.export_manager:
            return self.export_manager.export_video_with_ffmpeg(
                video_clip, output_path, video_bitrate, preset, fps, video_duration
            )
        return False
    
    def _check_system_memory(self):
        """Delega a VideoExportManager si estÃ¡ disponible"""
        if self.export_manager:
            return self.export_manager.check_system_memory()
        return None, None
    
    def _estimate_memory_required(self, num_segments, video_duration, apply_cinematic=False):
        """Delega a VideoExportManager si estÃ¡ disponible"""
        if self.export_manager:
            return self.export_manager.estimate_memory_required(num_segments, video_duration, apply_cinematic)
        # Fallback: estimaciÃ³n bÃ¡sica
        base_memory_per_clip_mb = 50 * (2 if apply_cinematic else 1)
        clips_memory_gb = (num_segments * base_memory_per_clip_mb) / 1024
        processing_overhead_gb = 0.5 + ((video_duration / 300) * 0.5 if video_duration > 300 else 0)
        return (clips_memory_gb + processing_overhead_gb) * 1.3
    
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

    def _assemble_direct_ffmpeg(self, clips_data, audio_file_path, output_path,
                                resolution, fps=30, transition_type='None (Direct Cut)',
                                transition_duration=0.5):
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
        self.log(f"\n   ðŸ“¹ Fase 1/3: Creando {total_clips} clips ({width}x{height})...")
        start_time = _time.time()
        clips = []
        clip_durations = []
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

                # Construir filtro de video base - preservar aspect ratio sin crop agresivo
                vf = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                      f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}')

                # Agregar fade-out de video al Ãºltimo clip para un cierre suave
                if i == total_clips - 1 and duration > 2:
                    fade_duration = min(4.0, duration - 0.5)  # Fade de hasta 4s, dejando al menos 0.5s
                    fade_start = max(0, duration - fade_duration)
                    vf += f',fade=t=out:st={fade_start:.2f}:d={fade_duration:.2f}'
                    self.log(f"      ðŸŽ¬ Fade-out de video: {fade_duration:.1f}s al final del Ãºltimo clip")

                if is_video:
                    # Si el video es mÃ¡s corto que el segmento, ralentizarlo para cubrirlo completo
                    # (evita repeticiones visibles por loop).
                    original_duration = _probe_duration_seconds(img_path, stream_selector='v:0', timeout=10)
                    if original_duration > 0 and original_duration < duration:
                        slow_factor = duration / original_duration
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
                    # MEJORA: Efecto Ken Burns Orgánico (Easing)
                    # En lugar de una imagen estática con -loop 1, generamos un paneo suave con ease-out.
                    frames = int(float(duration) * fps)
                    # sin((in/frames)*(PI/2)) genera una curva suave de desaceleración (Ease-out)
                    kb_vf = f"{vf},zoompan=z='1.0+0.05*sin((in/{frames})*(PI/2))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}"
                    
                    cmd = [
                        ffmpeg_exe, '-y',
                        '-i', img_path,
                        '-t', str(duration),
                        '-vf', kb_vf,
                        '-c:v', optimal_encoder, '-preset', 'fast', '-pix_fmt', 'yuv420p',
                        '-r', str(fps), '-g', '30',
                        clip_out
                    ]

                tipo = "video" if is_video else "img"
                self.log(f"      [{i+1}/{total_clips}] Codificando seg {i+1} ({tipo}, {duration:.1f}s)...")
                clip_start = _time.time()
                try:
                    result = sp.run(cmd, capture_output=True, text=True, timeout=1200,
                                    creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    clip_elapsed = _time.time() - clip_start

                    if result.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 500:
                        clips.append(clip_out)
                        actual_clip_duration = _probe_duration_seconds(clip_out, stream_selector='v:0', timeout=10)
                        clip_durations.append(actual_clip_duration if actual_clip_duration > 0 else float(duration))
                        self.log(f"      [{i+1}/{total_clips}] OK ({clip_elapsed:.1f}s)")
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

        if not clips:
            self.log("   âŒ No se pudo crear ningÃºn clip")
            return False

        self.log(f"   âœ… {len(clips)}/{total_clips} clips creados")

        # FASE 1.5: Insertar clips de overlay transition (film burn) entre escenas
        if is_overlay_transition and len(clips) > 1:
            overlay_base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transition_overlays")
            overlay_src = None
            if os.path.isdir(overlay_base_dir):
                for fname in sorted(os.listdir(overlay_base_dir)):
                    if fname.lower().endswith((".mp4", ".mov", ".webm")):
                        overlay_src = os.path.join(overlay_base_dir, fname)
                        break

            if overlay_src:
                target_ovr_dur = max(0.15, min(transition_duration, 1.0))
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

                        # Insertar overlay entre clips con fuente visual diferente
                        merged_clips = [clips[0]]
                        merged_durations = [clip_durations[0]]
                        overlays_inserted = 0
                        for idx in range(1, len(clips)):
                            src_idx = min(idx, len(sources) - 1)
                            prev_src_idx = min(idx - 1, len(sources) - 1)
                            if sources[prev_src_idx] != sources[src_idx]:
                                merged_clips.append(overlay_clip_path)
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
        try:
            if (use_transitions or is_overlay_transition) and audio_file_path and len(clips) > 1:
                self.log("   🔊 Mezclando SFX de transicion en la pista maestra...")
                from pydub import AudioSegment
                master = AudioSegment.from_file(audio_file_path)
                sfx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transition_overlays", "swoosh.wav")
                
                # Fallback to general swoosh if overlay specific one doesn't exist
                if not os.path.exists(sfx_path):
                    sfx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swoosh.wav")
                    
                if os.path.exists(sfx_path):
                    sfx_swoosh = AudioSegment.from_file(sfx_path)
                    
                    # Calcular pico del swoosh
                    max_rms, peak_idx = 0, 0
                    chunk_size = 10
                    for i in range(0, len(sfx_swoosh) - chunk_size, chunk_size):
                        rms = sfx_swoosh[i:i+chunk_size].rms
                        if rms > max_rms:
                            max_rms = rms
                            peak_idx = i
                    
                    # Calcular puntos de inyeccion
                    accumulated = 0.0
                    if use_transitions:
                        for i in range(1, created_count):
                            accumulated += clip_durations[i-1]
                            offset = max(0.0, accumulated - (i * safe_transition_duration))
                            transition_peak_ms = int((offset + safe_transition_duration / 2) * 1000)
                            position_ms = max(0, transition_peak_ms - peak_idx)
                            master = master.overlay(sfx_swoosh, position=position_ms)
                    elif is_overlay_transition:
                        for i in range(len(clips)):
                            if "overlay_transition" in clips[i]:
                                transition_peak_ms = int((accumulated + clip_durations[i] / 2) * 1000)
                                position_ms = max(0, transition_peak_ms - peak_idx)
                                master = master.overlay(sfx_swoosh, position=position_ms)
                            accumulated += clip_durations[i]
                            
                    mixed_audio_path = os.path.join(temp_dir, "master_mixed_sfx.mp3")
                    master.export(mixed_audio_path, format="mp3")
                    audio_file_path = mixed_audio_path
                    self.log("   ✅ SFX de transicion mezclados exitosamente.")
                else:
                    self.log(f"   [WARN] No se encontro {sfx_path}, saltando SFX.")
        except Exception as e:
            self.log(f"   [WARN] Error mezclando SFX de transicion: {e}")
        # ---------------------------------------------------

        video_base_duration = _probe_duration_seconds(video_no_audio, stream_selector='v:0', timeout=20)
        force_shortest = False
        if audio_duration_sec > 0 and video_base_duration > 0 and video_base_duration + 0.25 < audio_duration_sec:
            self.log(
                f"   ⚠️ Duración de video base menor que audio ({video_base_duration:.1f}s < {audio_duration_sec:.1f}s). "
                f"Aplicando -shortest para evitar congelamiento de imagen."
            )
            force_shortest = True
        audio_cmd = [
            ffmpeg_exe, '-y',
            '-i', video_no_audio,
            '-i', audio_file_path,
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            '-ar', '44100', '-ac', '2',
            '-movflags', '+faststart',
        ]
        if audio_duration_sec > 0 and not force_shortest:
            audio_cmd.extend(['-t', str(audio_duration_sec)])
        else:
            audio_cmd.append('-shortest')
        audio_cmd.append(output_path)

        try:
            result = sp.run(audio_cmd, capture_output=True, text=True, timeout=1800,
                            creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
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
                                       transition_type='ðŸŒ… Fade Suave', transition_duration=0.5,
                                       generate_short_teaser=False, use_wikimedia=False,
                                       disable_wikimedia=False, use_real_images=True,
                                       use_google_images=True, enable_real_images_mix=False, test_mode=False,
                                       image_provider='auto',
                                       video_provider='none', fal_video_model=None,
                                       allow_visual_regeneration=True, **_extra_kwargs):
        """
        Ensambla el video desde el storyboard.
        
        Args:
            generate_short_teaser: Si es True y platform='youtube', genera un short teaser en paralelo
            use_wikimedia: (OBSOLETO) ParÃ¡metro mantenido por compatibilidad - Solo se usan APIs de generaciÃ³n (Fal.ai FLUX.1 schnell, Leonardo AI)
        """
        
        self.log(f"\nðŸš€ ENSAMBLANDO VIDEO (Modo: {assembly_mode} / {visual_mode})...")
        self.log(f"   Transicion seleccionada: {transition_type} ({transition_duration}s)")
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
                project_base_dir = project_hint_path.parent if project_hint_path.suffix.lower() == '.json' else project_hint_path
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
                    from cover_frame_generator import generate_cover_frame
                    cf_result = generate_cover_frame(
                        topic=storyboard_data.get('topic', ''),
                        category=storyboard_data.get('category', ''),
                        storyboard=storyboard_data,
                        output_dir=str(self.generated_media_dir),
                        image_gen_manager=getattr(self, 'image_generation_manager', None),
                        image_provider=image_provider,
                        cover_text_override=cover_text,
                        log_callback=self.log,
                    )
                    if cf_result and cf_result.get('image_path') and os.path.exists(cf_result['image_path']):
                        media_path = cf_result['image_path']
                        seg['image_path'] = media_path
                except Exception as exc:
                    self.log(f"      [Cover Frame] Error: {exc}")

                if not media_path:
                    self.log("      [Cover Frame] Fallback: dark gradient with text")
                    try:
                        from cover_frame_generator import composite_cover_text
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
            ov_path = None
            if add_overlays and GIPHY_AVAILABLE and seg.get('overlay_tag') and seg.get('overlay_tag') != 'none':
                ov_path = find_and_download_gif(seg.get('overlay_tag'), self.generated_media_dir)

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
                    'sfx_path': sfx_path
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
                if last["filename"] == fn:
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
        
        # --- MEJORA SFX: Inyectar Swoosh en transiciones directamente en la pista de voz ---
        _no_trans = ("none", "corte directo", "direct cut")
        _use_trans = transition_type and not any(t in str(transition_type).lower() for t in _no_trans)
        if PYDUB_AVAILABLE and _use_trans and len(generated_clips) > 1:
            try:
                self.log("   🔊 Inyectando SFX de transicion en la pista de voz...")
                from pydub import AudioSegment
                v_sfx = AudioSegment.from_file(audio_path)
                sfx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transition_overlays", "swoosh.wav")
                if not os.path.exists(sfx_path):
                    sfx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swoosh.wav")
                
                if os.path.exists(sfx_path):
                    sfx_swoosh = AudioSegment.from_file(sfx_path) - 2 # Bajar 2 dB para no saturar
                    sfx_added = False
                    for i in range(1, len(generated_clips)):
                        t_start_ms = int(generated_clips[i].get('timestamp_start', 0) * 1000)
                        if t_start_ms > 0:
                            v_sfx = v_sfx.overlay(sfx_swoosh, position=max(0, t_start_ms - 500))
                            sfx_added = True
                    
                    if sfx_added:
                        v_sfx.export(audio_path, format="wav")
                        self.log("   ✅ SFX de transicion mezclados exitosamente.")
            except Exception as e:
                self.log(f"   ⚠️ Error inyectando SFX de transicion: {e}")

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
                    v = AudioSegment.from_file(audio_path)

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
                    # Usamos sidechaincompress: music (0) comprimido por voice (1)
                    duck_cmd = [
                        ffmpeg_exe, '-y',
                        '-i', temp_music,
                        '-i', temp_voice,
                        '-filter_complex', '[0:a]volume=0.8[m];[1:a]volume=1.0[v];[m][v]sidechaincompress=threshold=0.03:ratio=5:attack=20:release=1000[ducked];[ducked][v]amix=inputs=2:duration=first:dropout_transition=2',
                        '-c:a', 'libmp3lame', '-q:a', '2',
                        mp
                    ]
                    try:
                        sp.run(duck_cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL, creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0, check=True)
                    except Exception as e:
                        self.log(f"   [WARN] Error en FFmpeg Sidechain, usando mezcla normal: {e}")
                        # Subir un poco el volumen de la musica en el fallback (antes era -7)
                        final_mix = v_extended.overlay(music_with_fadeout - 3)
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
                v = AudioSegment.from_file(audio_path)
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

        if all_supported_media and not apply_cinematic and generated_clips:
            has_videos = any(c.get('filename', '').lower().endswith(('.gif', '.mp4', '.mov', '.avi', '.webm', '.mkv')) for c in generated_clips)
            mode_desc = "imÃ¡genes + videos" if has_videos else "imÃ¡genes"
            self.log(f"\nðŸš€ Modo rÃ¡pido: ensamblaje directo con FFmpeg ({mode_desc}, sin MoviePy)...")

            requested_out = VideoConfig.OUTPUT_DIR / f"{platform}_{int(time.time())}.mp4"
            out, using_local_safe_output = _resolve_safe_video_output_path(requested_out)
            if using_local_safe_output:
                self.log("âš ï¸ Unidad remota/WebDAV detectada para exportaciÃ³n de video.")
                self.log(f"   Guardando video base localmente para evitar ERROR_FILE_TOO_LARGE (0x800700DF): {out}")
            self.log(f"ðŸ“¹ Exportando video a: {out}")

            direct_ok = self._assemble_direct_ffmpeg(
                generated_clips, final_audio_path, str(out), res,
                transition_type=transition_type,
                transition_duration=transition_duration
            )

            if direct_ok:
                file_size_mb = os.path.getsize(str(out)) / 1024 / 1024
                self.log(f"âœ… Video exportado: {file_size_mb:.1f} MB")

                result = {
                    'video_path': str(out),
                    'script': storyboard_data['script'],
                    'topic': storyboard_data['topic'],
                    'category': storyboard_data['category'],
                    'music_attribution': None,
                    'segments': storyboard_data.get('segments', []),
                    'audio_path': storyboard_data.get('audio_path'),
                    'final_audio_path': final_audio_path
                }

                # Aplicar subtÃ­tulos dinÃ¡micos si estÃ¡n activos
                if add_subtitles and hasattr(self, '_dynamic_subtitle_wrapper'):
                    self.log("ðŸŽ¬ Aplicando subtÃ­tulos dinÃ¡micos al video final...")
                    subs_applied = False
                    try:
                        segs = storyboard_data.get('segments', [])
                        if segs:
                            from dynamic_subtitle_wrapper import DynamicSubtitleWrapper
                            wrapper = DynamicSubtitleWrapper(style=subtitle_style)
                            subtitle_audio_path = final_audio_path or storyboard_data.get('audio_path')
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
                        self.log(f"ðŸ”´ ATENCIÃ“N: El video final NO contiene subtÃ­tulos. "
                                 f"PodÃ©s aplicarlos manualmente con: python simple_subs.py")

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
        requested_out = VideoConfig.OUTPUT_DIR / f"{platform}_{int(time.time())}.mp4"
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
                from video_export_manager import _probe_has_video_and_audio as _probe_check
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
            from video_export_manager import _probe_has_video_and_audio, _probe_duration
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
            'music_attribution': None,
            'segments': storyboard_data.get('segments', []),  # Incluir segmentos para el preview
            'audio_path': storyboard_data.get('audio_path'),  # Incluir audio_path para el preview
            'final_audio_path': final_audio_path
        }
        
        # 6. Aplicar subtÃ­tulos dinÃ¡micos si estÃ¡n activos y el patch estÃ¡ aplicado
        if add_subtitles and hasattr(self, '_dynamic_subtitle_wrapper'):
            self.log("ðŸŽ¬ Aplicando subtÃ­tulos dinÃ¡micos al video final...")
            subs_applied = False
            try:
                segments = storyboard_data.get('segments', [])
                if segments:
                    wrapper = self._dynamic_subtitle_wrapper
                    subtitle_audio_path = final_audio_path or storyboard_data.get('audio_path')
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
                self.log(f"ðŸ”´ ATENCIÃ“N: El video final NO contiene subtÃ­tulos. "
                         f"PodÃ©s aplicarlos manualmente con: python simple_subs.py")
        
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
        
if __name__ == "__main__":
    print("Ejecuta video-opt-app.py para usar la interfaz.")
