# auto_video_generator_v2.py
import builtins
import os
import time
import requests
from pathlib import Path
from datetime import datetime
import json
import sys


def _safe_print(*args, sep=' ', end='\n', file=None, flush=False):
    """Evita caídas por logs Unicode en consolas Windows cp1252."""
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

# --- FIX CRÍTICO PARA PILLOW 10.0+ Y MOVIEPY ---
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
    """Carpeta local segura para exportaciones pesadas cuando el proyecto está en WebDAV."""
    base_dir = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    output_dir = Path(base_dir) / 'VideoOptimizer' / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _resolve_safe_video_output_path(output_path: Path) -> Tuple[Path, bool]:
    """Redirige la exportación a disco local si la salida cae en una unidad remota."""
    output_path = Path(output_path)
    if _is_windows_remote_drive(str(output_path)):
        return _get_local_safe_output_dir() / output_path.name, True
    return output_path, False

# ========== VERIFICACIÓN DE DEPENDENCIAS Y CONFIGURACIÓN DE ENTORNO ==========
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
    print("⚠️ gTTS no disponible (Instala: pip install gTTS)")

# 1.5. Edge-TTS (Microsoft Edge voices - GRATIS)
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    print("⚠️ edge-tts no disponible (Instala: pip install edge-tts)")

# 2. MoviePy
try:
    from moviepy.editor import (
        VideoFileClip, AudioFileClip, ImageClip,
        CompositeVideoClip, concatenate_videoclips,
        TextClip, CompositeAudioClip, concatenate_audioclips
    )
    # vfx incluye tanto efectos de video como de audio (audio_fadeout, etc.)
    import moviepy.audio.fx.all as vfx
    # AudioClip está disponible desde moviepy.audio.AudioClip
    from moviepy.audio.AudioClip import AudioClip
    MOVIEPY_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ MoviePy no disponible (Instala: pip install moviepy<2.0.0)")
    print(f"   Error de importación: {e}")

# 3. Whisper
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    print("⚠️ Whisper no disponible - subtítulos deshabilitados (Instala: pip install openai-whisper)")

# 4. Pydub y FFmpeg
try:
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent
    
    # Configurar la ruta de FFmpeg para pydub (Específico para Windows)
    import platform
    if platform.system() == "Windows":
        # Rutas comunes donde podría estar FFmpeg
        possible_paths = [
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
                print(f"✅ pydub configurado con FFmpeg en: {base_path}")
                ffmpeg_configured = True
                break
        
        if not ffmpeg_configured:
            # Intentar usar el PATH del sistema
            print("⚠️ No se encontró FFmpeg en rutas estándar, confiando en el PATH del sistema.")
            
    PYDUB_AVAILABLE = True
except ImportError:
    print("⚠️ pydub no está instalado. El Audio Ducking fallará. (Instala: pip install pydub)")
except Exception as e:
    print(f"⚠️ Error al configurar pydub: {e}")

# --- MÓDULOS DEL PROYECTO (IA y Utilidades) ---
try:
    from gemini_ai_client import GeminiAiClient
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ gemini_ai_client.py no encontrado. La generación de guion contextual fallará.")

try:
    from runwayml import RunwayML, TaskFailedError
    RUNWAY_AVAILABLE = True
except ImportError:
    RUNWAY_AVAILABLE = False
    print("⚠️ SDK 'runwayml' no encontrado. La generación de video/imagen fallará.")

try:
    from music_recommender import (
        analyze_narration,
        map_ai_to_jamendo_tags,
        search_jamendo_api,
        download_track
    )
    JAMENDO_AVAILABLE = True
    print("✅ Music Recommender (Jamendo) cargado")
except ImportError as e:
    JAMENDO_AVAILABLE = False
    print(f"⚠️ music_recommender.py no disponible: {e}")

try:
    from google_search_api import search_google_trends
    GOOGLE_SEARCH_AVAILABLE = True
except ImportError:
    GOOGLE_SEARCH_AVAILABLE = False
    print("⚠️ google_search_api.py no encontrado. Los guiones no tendrán investigación.")

try:
    from sfx_client import find_and_download_sfx
    SFX_AVAILABLE = False  # Desactivado por defecto
except ImportError:
    SFX_AVAILABLE = False
    print("⚠️ sfx_client.py no encontrado. La búsqueda de SFX fallará.")

try:
    from giphy_client import find_and_download_gif
    GIPHY_AVAILABLE = True
except ImportError:
    GIPHY_AVAILABLE = False
    print("⚠️ giphy_client.py no encontrado. Los Overlays fallarán.")

try:
    from cinematic_effects import CinematicEffectsEngine, ContextDetector
    CINEMATIC_AVAILABLE = True
except ImportError:
    CINEMATIC_AVAILABLE = False
    print("⚠️ cinematic_effects.py no encontrado. Efectos cinematográficos desactivados.")

# Stability.ai eliminado
STABILITY_AVAILABLE = False

# Importar cliente Fal.ai (FLUX.1 schnell - prioritario)
try:
    from fal_ai_client import FalAiClient
    FAL_AI_AVAILABLE = True
    print("✅ Fal.ai client (FLUX.1 schnell) cargado")
except ImportError:
    FAL_AI_AVAILABLE = False
    print("⚠️ fal_ai_client.py no encontrado. Fal.ai no funcionará.")

try:
    from recraft_client import RecraftClient
    RECRAFT_AVAILABLE = True
    print("✅ Recraft client cargado")
except ImportError:
    RECRAFT_AVAILABLE = False
    print("⚠️ recraft_client.py no encontrado. Recraft no funcionará.")

# Importar clientes de Google Images y Wikimedia
try:
    from google_images_client import GoogleImagesClient
    GOOGLE_IMAGES_AVAILABLE = True
    print("✅ Google Images client cargado")
except ImportError:
    GOOGLE_IMAGES_AVAILABLE = False
    print("⚠️ google_images_client.py no encontrado. La búsqueda de imágenes en Google Images no funcionará.")

try:
    from wikimedia_client import WikimediaClient
    WIKIMEDIA_AVAILABLE = True
    print("✅ Wikimedia client cargado")
except ImportError:
    WIKIMEDIA_AVAILABLE = False
    print("⚠️ wikimedia_client.py no encontrado. La búsqueda de imágenes en Wikimedia no funcionará.")

try:
    from google_ai_image_client import GoogleAiImageClient
    GOOGLE_AI_IMAGE_AVAILABLE = True
    print("✅ Google AI Image client cargado")
except ImportError:
    GOOGLE_AI_IMAGE_AVAILABLE = False
    print("⚠️ google_ai_image_client.py no encontrado. Google AI Image no funcionará.")

try:
    from vertex_imagen_client import VertexImagenClient
    VERTEX_IMAGEN_AVAILABLE = True
    print("✅ Vertex Imagen client cargado")
except ImportError:
    VERTEX_IMAGEN_AVAILABLE = False
    print("⚠️ vertex_imagen_client.py no encontrado. Vertex Imagen no funcionará.")

# ========== IMPORTAR CONFIGURACIÓN DESDE MÓDULO SEPARADO ==========
# VideoConfig ha sido movido a video_config.py para mejor organización
try:
    from video_config import VideoConfig
except ImportError:
    # Fallback: definir VideoConfig aquí si el módulo no está disponible
    # (para compatibilidad hacia atrás)
    print("⚠️ video_config.py no encontrado, usando definición local de VideoConfig")
    
    # ========== CONFIGURACIÓN GLOBAL (FALLBACK) ==========
    class VideoConfig:
        """Configuración centralizada del sistema"""
        
        @staticmethod
        def get_negative_prompt(base_negative=None):
            """
            Genera un negative prompt robusto para prevenir errores de generación IA.
            Usa solo caracteres ASCII para evitar problemas de codificación.
            
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
            
            # Problemas de composición
            "bad composition", "cropped", "cut off", "out of frame", "incomplete",
            "partial", "truncated", "amputated", "floating objects", "disconnected",
            "unrealistic", "impossible", "illogical", "nonsensical",
            
            # Problemas de iluminación y color
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
            # Limpiar cualquier carácter no ASCII del base_negative
            if base_negative:
                # Normalizar a ASCII si es necesario
                try:
                    base_negative_clean = base_negative.encode('ascii', 'ignore').decode('ascii')
                    if base_negative_clean.strip():
                        negative_prompt = f"{negative_prompt}, {base_negative_clean}"
                except:
                    # Si falla, usar el original pero limpiar caracteres problemáticos
                    base_negative_clean = ''.join(char for char in base_negative if ord(char) < 128)
                    if base_negative_clean.strip():
                        negative_prompt = f"{negative_prompt}, {base_negative_clean}"
            
            # Asegurar que el resultado final sea solo ASCII
            try:
                negative_prompt = negative_prompt.encode('ascii', 'ignore').decode('ascii')
            except:
                # Fallback: remover cualquier carácter no ASCII manualmente
                negative_prompt = ''.join(char for char in negative_prompt if ord(char) < 128)
            
            return negative_prompt
        
        # APIs (leídas desde .env por el script principal)
        PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
        PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")
        ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        LEONARDO_API_KEY = os.getenv("LEONARDO_API_KEY")
        FAL_API_KEY = os.getenv("FAL_API_KEY")
        
        # Directorios
        BASE_DIR = Path("auto_videos")
        DOWNLOADS_DIR = BASE_DIR / "downloads"
        AUDIO_DIR = BASE_DIR / "audio"
        OUTPUT_DIR = BASE_DIR / "output"
        TEMP_DIR = BASE_DIR / "temp"
        BGM_DIR = BASE_DIR / "bgm_library"  # Para música manual
        
        # Configuración de video
        VIDEO_RESOLUTION = (1920, 1080)  # YouTube horizontal
        VIDEO_RESOLUTION_VERTICAL = (1080, 1920)  # Vertical (Shorts/TikTok)
        DEFAULT_VIDEO_WIDTH = 1920
        DEFAULT_VIDEO_HEIGHT = 1080
        DEFAULT_VIDEO_FPS = 30
        
        # Duraciones por plataforma (segundos)
        PLATFORM_DURATIONS = {
            'youtube': 300,      # 5 minutos
            'youtube_short': 120,  # 2 minutos
            'tiktok': 60,        # 1 minuto
            'reels': 60          # 1 minuto
        }
        
        # Configuración de estilos de subtítulos detallada
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
            print("✅ Directorios configurados")


# ========== IMPORTAR DESCARGADOR DE RECURSOS DESDE MÓDULO SEPARADO ==========
# ResourceDownloader ha sido movido a resource_downloader.py
try:
    from resource_downloader import ResourceDownloader
except ImportError:
    print("⚠️ resource_downloader.py no encontrado, ResourceDownloader no disponible")
    ResourceDownloader = None


# ========== IMPORTAR GENERADOR DE VOZ DESDE MÓDULO SEPARADO ==========
# TextToSpeechGenerator ha sido movido a tts_generator.py
try:
    from tts_generator import TextToSpeechGenerator
except ImportError:
    print("⚠️ tts_generator.py no encontrado, TextToSpeechGenerator no disponible")
    TextToSpeechGenerator = None

# Nota: TextToSpeechGenerator está en tts_generator.py
# Nota: SubtitleGenerator está en subtitle_generator.py

# ========== IMPORTAR GENERADOR DE SUBTÍTULOS DESDE MÓDULO SEPARADO ==========
try:
    from subtitle_generator import SubtitleGenerator
except ImportError:
    print("⚠️ subtitle_generator.py no encontrado, SubtitleGenerator no disponible")
    SubtitleGenerator = None

# ========== IMPORTAR ENSAMBLADOR DE VIDEO DESDE MÓDULO SEPARADO ==========
# ContextualVideoAssembler ha sido movido a video_assembler.py
try:
    from video_assembler import ContextualVideoAssembler
except ImportError:
    print("⚠️ video_assembler.py no encontrado, ContextualVideoAssembler no disponible")
    ContextualVideoAssembler = None
                                                        
# ========== CLIENTE LEONARDO AI (NUEVO) ==========
# En auto_video_generator_v2.py

# ========== IMPORTAR LEONARDO AI CLIENT DESDE MÓDULO SEPARADO ==========
# LeonardoAIClient ha sido movido a leonardo_ai_client.py
try:
    from leonardo_ai_client import LeonardoAIClient
except ImportError:
    print("⚠️ leonardo_ai_client.py no encontrado, LeonardoAIClient no disponible")
    LeonardoAIClient = None

# ========== IMPORTAR VIDEO GENERATION MANAGER DESDE MÓDULO SEPARADO ==========
# VideoGenerationManager ha sido movido a video_generation_manager.py
try:
    from video_generation_manager import VideoGenerationManager
except ImportError:
    print("⚠️ video_generation_manager.py no encontrado, VideoGenerationManager no disponible")
    VideoGenerationManager = None

# ========== IMPORTAR PROMPT PROCESSOR DESDE MÓDULO SEPARADO ==========
# PromptProcessor ha sido movido a prompt_processor.py
try:
    from prompt_processor import PromptProcessor
except ImportError:
    print("⚠️ prompt_processor.py no encontrado, PromptProcessor no disponible")
    PromptProcessor = None

# ========== IMPORTAR VIDEO EXPORT MANAGER DESDE MÓDULO SEPARADO ==========
# VideoExportManager ha sido movido a video_export_manager.py
try:
    from video_export_manager import VideoExportManager
except ImportError:
    print("⚠️ video_export_manager.py no encontrado, VideoExportManager no disponible")
    VideoExportManager = None

try:
    from storyboard_generator import StoryboardGenerator
except ImportError:
    print("⚠️ storyboard_generator.py no encontrado, StoryboardGenerator no disponible")
    StoryboardGenerator = None

try:
    from image_generation_manager import ImageGenerationManager
except ImportError:
    print("⚠️ image_generation_manager.py no encontrado, ImageGenerationManager no disponible")
    ImageGenerationManager = None

# ========== CLASE PRINCIPAL: AUTO VIDEO GENERATOR ==========
class AutoVideoGenerator:
    """
    Clase principal que coordina el NUEVO flujo de generación contextual.
    Flujo: Guion (Gemini) -> Audio (TTS) -> Tiempos (Whisper) -> 
           Prompts Visuales (Gemini) -> Creación Visual (Runway/Pexels) -> Ensamblaje
    """
    
    def __init__(self, parent_window=None):
        VideoConfig.setup_directories()
        
        # --- Módulos de IA ---
        self.gemini_client = GeminiAiClient() if GEMINI_AVAILABLE else None
        
        self.runway_api_key = os.getenv("RUNWAYML_API_SECRET") 
        if RUNWAY_AVAILABLE and self.runway_api_key:
            self.runway_client = RunwayML(api_key=self.runway_api_key) 
        else:
            self.runway_client = None
        
        # --- Directorio de Recursos Generados ---
        self.generated_media_dir = VideoConfig.TEMP_DIR / "generated_media"
        self.generated_media_dir.mkdir(exist_ok=True, parents=True)
        
        # --- Módulos de Video/Audio ---
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

        # Inicializar Fal.ai (FLUX.1 schnell)
        if FAL_AI_AVAILABLE and (
            os.getenv("FAL_KEY")
            or os.getenv("FAL_API_KEY")
            or (os.getenv("FAL_KEY_ID") and os.getenv("FAL_KEY_SECRET"))
        ):
            self.fal_client = FalAiClient(log_callback=self.log)
            self.fal_available = self.fal_client is not None and getattr(self.fal_client, 'client_available', False)
        else:
            self.fal_client = None
            self.fal_available = False
        
        # Inicializar Leonardo AI como FALLBACK
        if os.getenv("LEONARDO_API_KEY"):
            self.leonardo_client = LeonardoAIClient(log_callback=self.log)
        else:
            self.leonardo_client = None
        
        self.stability_client = None
        if RECRAFT_AVAILABLE and os.getenv("RECRAFT_API_KEY"):
            try:
                recraft_client = RecraftClient(log_callback=self.log)
                self.recraft_client = (
                    recraft_client if getattr(recraft_client, "api_key", None) else None
                )
            except Exception as e:
                self.log(f"⚠️ Error inicializando Recraft: {e}")
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
                self.log(f"⚠️ Error inicializando Google AI Image: {e}")
                self.google_ai_image_client = None
        else:
            self.google_ai_image_client = None

        if VERTEX_IMAGEN_AVAILABLE:
            try:
                vertex_client = VertexImagenClient(log_callback=self.log)
                self.vertex_imagen_client = (
                    vertex_client if getattr(vertex_client, "client_available", False) else None
                )
            except Exception as e:
                self.log(f"⚠️ Error inicializando Vertex Imagen: {e}")
                self.vertex_imagen_client = None
        else:
            self.vertex_imagen_client = None

        # Inicializar Google Images client
        if GOOGLE_IMAGES_AVAILABLE:
            try:
                self.google_images_client = GoogleImagesClient(gemini_client=self.gemini_client)
            except Exception as e:
                self.log(f"⚠️ Error inicializando Google Images: {e}")
                self.google_images_client = None
        else:
            self.google_images_client = None
        
        # Inicializar Wikimedia client
        if WIKIMEDIA_AVAILABLE:
            try:
                self.wikimedia_client = WikimediaClient(gemini_client=self.gemini_client)
            except Exception as e:
                self.log(f"⚠️ Error inicializando Wikimedia: {e}")
                self.wikimedia_client = None
        else:
            self.wikimedia_client = None
        
        # Inicializar VideoGenerationManager
        if VideoGenerationManager:
            self.video_gen_manager = VideoGenerationManager(
                log_callback=self.log,
                leonardo_client=self.leonardo_client,
                fal_client=self.fal_client,
                runway_client=self.runway_client,
                fal_available=self.fal_available,
                google_images_client=self.google_images_client,
                wikimedia_client=self.wikimedia_client,
                generated_media_dir=self.generated_media_dir
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
                fal_client=self.fal_client,
                recraft_client=self.recraft_client,
                leonardo_client=self.leonardo_client,
                google_ai_image_client=self.google_ai_image_client,
                vertex_imagen_client=self.vertex_imagen_client,
                google_images_client=self.google_images_client,
                wikimedia_client=self.wikimedia_client,
                prompt_processor=self.prompt_processor
            )
        else:
            self.image_gen_manager = None

        print("✅ Auto Video Generator (Contextual v3.0 - Heavy) inicializado")

    def log(self, message):
        """Helper simple para logging en consola."""
        print(message)

    # --- MÉTODOS DE GENERACIÓN DE VIDEO CON FALLBACK ---
    # Delegados a VideoGenerationManager si está disponible

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
                                    preferred_provider='leonardo', image_path=None):
        """
        Genera video con sistema de fallback en cascada.

        Args:
            prompt: Prompt visual para el video
            output_path: Ruta donde guardar el video
            is_vertical: Si el video debe ser vertical (9:16)
            duration: Duración en segundos
            preferred_provider: 'leonardo', 'runway' o 'fal'
            image_path: Ruta a imagen base (solo para Leonardo Motion)

        Returns:
            str: Ruta al video generado, o None si todos fallaron
        """
        if self.video_gen_manager:
            return self.video_gen_manager.generate_video_with_fallback(
                prompt, output_path, is_vertical, duration, preferred_provider, image_path
            )
        return None

    # --- NUEVO: MÉTODOS PARA MODO MANUAL IA (JSON) ---
    def generate_manual_prompt_text(self, topic, category, duration, language='es',
                                    research_context=None, video_format=None):
        """Delega a StoryboardGenerator si está disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.generate_manual_prompt_text(
                topic, category, duration, language, research_context=research_context,
                video_format=video_format)
        # Fallback básico
        lang_str = "SPANISH" if language == 'es' else "ENGLISH"
        return f"""
Actúa como un productor de video experto. Necesito un guion técnico en formato JSON para un video de {duration} segundos sobre "{topic}" (Categoría: {category}).

El JSON debe tener ESTRICTAMENTE esta estructura:
{{
  "title": "Título del Video",
  "scenes": [
    {{
      "narration": "Texto de narración en {lang_str}.",
      "visual_prompt": "Prompt visual detallado en INGLÉS (estilo cinematográfico).",
      "sfx_tag": "Palabra clave de sonido (Inglés) o 'none'.",
      "overlay_tag": "Palabra clave de GIF/Sticker (Inglés) o 'none'."
    }}
  ]
}}

Reglas:
1. Calcula aproximadamente {max(3, int(duration/6))} escenas.
2. La narración debe ser en {lang_str}.
3. Responde SOLO con el código JSON.
"""
    def process_manual_json(self, json_data, voice_id=None, language='es', rate="+0%", max_duration: float = 0):
        """Delega a StoryboardGenerator si está disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.process_manual_json(json_data, voice_id, language, rate=rate, max_duration=max_duration)
        # Fallback: implementación básica (no recomendado)
        self.log("⚠️ StoryboardGenerator no disponible, usando fallback básico")
        return None

    def generate_storyboard_data(self, topic: str, category: str, platform: str = 'youtube',
                                 custom_duration: Optional[int] = None,
                                 voice_id: Optional[str] = None,
                                 find_auto_music: bool = True,
                                 style: str = "Estilo Realista / Cinematográfico",
                                 language: str = 'es',
                                 rate: str = "+0%"):
        """Delega a StoryboardGenerator si está disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator.generate_storyboard_data(
                topic, category, platform, custom_duration, voice_id, find_auto_music, style, language,
                rate=rate
            )
        # Fallback: implementación básica (no recomendado)
        self.log("⚠️ StoryboardGenerator no disponible, usando fallback básico")
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
            disable_wikimedia: (OBSOLETO) Parámetro mantenido por compatibilidad - Google Images y Wikimedia eliminados
            existing_teaser_storyboard: Storyboard del teaser previo (para reutilizar audio/segmentos/imágenes)
            rate: Velocidad de habla Edge-TTS, ej: '+0%', '+30%'

        Returns:
            dict con 'video_path', 'script', 'topic', 'category' del short teaser, o None si falla
        """
        # Asegurar que los subtítulos dinámicos estén activos para el teaser
        # (estilo capcut para shorts)
        if not hasattr(self, '_dynamic_subtitle_wrapper'):
            try:
                from dynamic_subtitle_wrapper import patch_subtitle_generation
                patch_subtitle_generation(self, 'capcut')
                self.log("   ✅ Subtítulos dinámicos activados para teaser (estilo: capcut)")
            except Exception as e:
                self.log(f"   ⚠️ No se pudo activar subtítulos dinámicos: {e}")
        
        # Delegar a StoryboardGenerator si está disponible
        if self.storyboard_generator:
            return self.storyboard_generator.generate_short_teaser_from_long_video(
                long_video_storyboard, language, voice_id, disable_wikimedia, existing_teaser_storyboard,
                rate=rate
            )
        # Fallback: implementación básica (no recomendado)
        self.log("⚠️ StoryboardGenerator no disponible, usando fallback básico")
        return None

    def _assemble_existing_teaser(self, existing_teaser_storyboard, long_video_storyboard, disable_wikimedia=False):
        """Delega a StoryboardGenerator si está disponible"""
        if self.storyboard_generator:
            return self.storyboard_generator._assemble_existing_teaser(
                existing_teaser_storyboard, long_video_storyboard, disable_wikimedia
            )
        # Fallback: implementación básica (no recomendado)
        self.log("⚠️ StoryboardGenerator no disponible, usando fallback básico")
        return None

    def _group_segments_for_images(self, segments, images_per_segment_ratio=1.0):
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            return self.prompt_processor.group_segments_for_images(segments, images_per_segment_ratio)
        # Fallback: implementación básica
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
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            return self.prompt_processor.apply_style_to_prompt(visual_prompt, style)
        # Fallback: retornar prompt sin modificar
        return visual_prompt
    
    def regenerate_visual_prompts_with_style(self, storyboard_data, style):
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            return self.prompt_processor.regenerate_visual_prompts_with_style(storyboard_data, style)
        # Fallback: retornar storyboard sin modificar
        return storyboard_data
    
    def _combine_prompts(self, segment_group):
        """Delega a PromptProcessor si está disponible"""
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
                                           regenerate_prompts=False, project_path=None):
        """Delega a ImageGenerationManager si está disponible"""
        if self.image_gen_manager:
            return self.image_gen_manager.generate_all_images_for_storyboard(
                storyboard_data, platform,
                use_wikimedia, disable_wikimedia,
                use_real_images, use_google_images,
                enable_real_images_mix, test_mode,
                image_provider, images_per_segment_ratio,
                interleave_images, style,
                regenerate_prompts, project_path
            )
        # Fallback: implementación básica (no recomendado)
        self.log("⚠️ ImageGenerationManager no disponible, usando fallback básico")
        return storyboard_data
    
    def _export_video_with_ffmpeg(self, video_clip, output_path, video_bitrate='8000k', 
                                   preset='medium', fps=30, video_duration=0):
        """Delega a VideoExportManager si está disponible"""
        if self.export_manager:
            return self.export_manager.export_video_with_ffmpeg(
                video_clip, output_path, video_bitrate, preset, fps, video_duration
            )
        return False
    
    def _check_system_memory(self):
        """Delega a VideoExportManager si está disponible"""
        if self.export_manager:
            return self.export_manager.check_system_memory()
        return None, None
    
    def _estimate_memory_required(self, num_segments, video_duration, apply_cinematic=False):
        """Delega a VideoExportManager si está disponible"""
        if self.export_manager:
            return self.export_manager.estimate_memory_required(num_segments, video_duration, apply_cinematic)
        # Fallback: estimación básica
        base_memory_per_clip_mb = 50 * (2 if apply_cinematic else 1)
        clips_memory_gb = (num_segments * base_memory_per_clip_mb) / 1024
        processing_overhead_gb = 0.5 + ((video_duration / 300) * 0.5 if video_duration > 300 else 0)
        return (clips_memory_gb + processing_overhead_gb) * 1.3
    
    def _should_disable_cinematic_effects(self, storyboard_data, apply_cinematic,
                                          platform=None, visual_mode=None,
                                          transition_type=None, cinematic_preset=None):
        """Delega a VideoExportManager si está disponible"""
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
        Convierte el texto de transición de la UI a un nombre válido de xfade.
        Retorna None cuando la transición equivale a corte directo.
        """
        text = str(transition_type or "").strip().lower()
        if not text:
            return None

        no_transition_tokens = (
            "none",
            "ninguna",
            "direct cut",
            "corte directo",
            "sin transición",
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
            ("fade", "fade"),
            ("zoom", "smoothup"),
            ("slide", "slideleft"),
            ("blur", "fadeblack"),
            ("dissolve", "dissolve"),
            ("wipe", "wipeleft"),
        ]
        for key, value in mapping:
            if key in text:
                return value

        # Fallback: si no se reconoce, usar fade (evita perder transición).
        return "fade"
    
    def _assemble_direct_ffmpeg(self, clips_data, audio_file_path, output_path,
                                resolution, fps=30, transition_type='None (Direct Cut)',
                                transition_duration=0.5):
        """
        Ensambla video directamente con FFmpeg desde imágenes y/o videos.
        Mucho más rápido y robusto que MoviePy.
        Evita CompositeVideoClip, pipes, y problemas de seek.

        Args:
            clips_data: Lista de dicts con 'filename', 'timestamp_start', 'duration'
            audio_file_path: Ruta al archivo de audio final
            output_path: Ruta de salida del video
            resolution: Tupla (width, height)
            fps: Frames por segundo
            transition_type: Tipo de transición seleccionada en UI
            transition_duration: Duración en segundos para la transición

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
                self.log("   ❌ FFmpeg no encontrado")
                return False

        width, height = resolution
        try:
            interpolation_fps = max(1, int(round(float(fps))))
        except Exception:
            interpolation_fps = 30
        temp_dir = os.path.join("auto_videos", "temp", "ffmpeg_direct")
        os.makedirs(temp_dir, exist_ok=True)

        # Resolver ffprobe de forma robusta (sin depender de mayúsculas en ffmpeg.EXE)
        ffprobe_exe = shutil.which("ffprobe")
        if not ffprobe_exe and ffmpeg_exe:
            ffmpeg_dir = os.path.dirname(ffmpeg_exe)
            for candidate in ("ffprobe.exe", "ffprobe.EXE", "ffprobe"):
                probe_path = os.path.join(ffmpeg_dir, candidate)
                if os.path.exists(probe_path):
                    ffprobe_exe = probe_path
                    break

        def _probe_duration_seconds(path, stream_selector=None, timeout=15):
            """Obtiene duración en segundos vía ffprobe (stream o format)."""
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

        # Ajustar duraciones para que el video cubra todo el audio (evita corte en últimos segmentos)
        audio_duration_sec = 0.0
        if os.path.exists(audio_file_path):
            audio_duration_sec = _probe_duration_seconds(audio_file_path, timeout=15)
            # Fallback: duración con pydub si ffprobe falló
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
        xfade_transition = self._map_transition_to_ffmpeg_xfade(transition_type)
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
            clips_data[-1]['duration'] = clips_data[-1].get('duration', 0) + deficit
            if use_transitions:
                self.log(
                    f"   [INFO] Ajustando ultimo segmento +{deficit:.1f}s "
                    f"(compensando {transition_overlap_sec:.1f}s de solape por transiciones)"
                )
            else:
                self.log(
                    f"   [INFO] Ajustando ultimo segmento +{deficit:.1f}s "
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

        # FASE 1: Crear clips individuales desde imágenes
        total_clips = len(clips_data)
        self.log(f"\n   📹 Fase 1/3: Creando {total_clips} clips ({width}x{height})...")
        start_time = _time.time()
        clips = []
        clip_durations = []
        supports_minterpolate = _ffmpeg_supports_filter("minterpolate")
        minterpolate_warning_logged = False

        for i, item in enumerate(clips_data):
            img_path = item['filename']
            duration = item['duration']
            clip_out = os.path.join(temp_dir, f"c_{i+1:03d}.mp4")

            if not os.path.exists(img_path):
                self.log(f"      ⚠️ Archivo no existe: {os.path.basename(img_path)}")
                continue

            is_video = img_path.lower().endswith(('.mp4', '.mov', '.avi', '.webm', '.mkv'))

            # Construir filtro de video base - preservar aspect ratio sin crop agresivo
            vf = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                  f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}')

            # Agregar fade-out de video al último clip para un cierre suave
            if i == total_clips - 1 and duration > 2:
                fade_duration = min(4.0, duration - 0.5)  # Fade de hasta 4s, dejando al menos 0.5s
                fade_start = max(0, duration - fade_duration)
                vf += f',fade=t=out:st={fade_start:.2f}:d={fade_duration:.2f}'
                self.log(f"      🎬 Fade-out de video: {fade_duration:.1f}s al final del último clip")

            if is_video:
                # Si el video es más corto que el segmento, ralentizarlo para cubrirlo completo
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
                            f"      🐢 Video corto: {original_duration:.2f}s → {duration:.2f}s "
                            f"(ralentizado x{slow_factor:.2f} + interpolación de cuadros)"
                        )
                    else:
                        vf = f'setpts={slow_factor:.6f}*PTS,{vf}'
                        if slow_factor > 1.05 and not supports_minterpolate and not minterpolate_warning_logged:
                            self.log(
                                "      ℹ️ FFmpeg no trae 'minterpolate'; usando ralentizado básico "
                                "sin cuadros intermedios."
                            )
                            minterpolate_warning_logged = True
                        self.log(
                            f"      🐢 Video corto: {original_duration:.2f}s → {duration:.2f}s "
                            f"(ralentizado x{slow_factor:.2f})"
                        )

                # Construir comando para video (sin loop; recorta o estira según corresponda)
                cmd = [
                    ffmpeg_exe, '-y',
                    '-i', img_path,
                    '-t', str(duration),
                    '-vf', vf,
                    '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p',
                    '-g', '30',  # Keyframe cada 1s para seek limpio
                    '-r', str(fps),  # Forzar framerate consistente
                    '-an',
                    clip_out
                ]
            else:
                # Para imágenes: usar -loop 1 para generar video desde frame estático
                cmd = [
                    ffmpeg_exe, '-y',
                    '-loop', '1', '-i', img_path,
                    '-t', str(duration),
                    '-vf', vf,
                    '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p',
                    clip_out
                ]

            try:
                result = sp.run(cmd, capture_output=True, text=True, timeout=120,
                                creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if result.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 500:
                    clips.append(clip_out)
                    # Usar duración real para xfade (evita offsets fuera de rango)
                    actual_clip_duration = _probe_duration_seconds(clip_out, stream_selector='v:0', timeout=10)
                    clip_durations.append(actual_clip_duration if actual_clip_duration > 0 else float(duration))
                else:
                    stderr_short = (result.stderr or '')[-100:]
                    self.log(f"      ⚠️ Error en clip {i+1}: {stderr_short}")
            except sp.TimeoutExpired:
                self.log(f"      ⚠️ Timeout en clip {i+1}")
            except Exception as e:
                self.log(f"      ⚠️ Error en clip {i+1}: {e}")

            # Progreso cada 10 clips o al final
            if (i + 1) % 10 == 0 or (i + 1) == total_clips:
                elapsed = _time.time() - start_time
                pct = int((i + 1) / total_clips * 100)
                self.log(f"      [{pct}%] {i+1}/{total_clips} clips ({elapsed:.1f}s)")

        if not clips:
            self.log("   ❌ No se pudo crear ningún clip")
            return False

        self.log(f"   ✅ {len(clips)}/{total_clips} clips creados")

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
                f"   🔗 Fase 2/3: Concatenando con transiciones "
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
                '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p',
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
                            f"   ⚠️ xfade produjo video corto ({actual_xfade_duration:.1f}s "
                            f"vs esperado {expected_xfade_duration:.1f}s). Usando concatenacion simple estable."
                        )
                        concat_ok = False
                    else:
                        concat_ok = True
                        self.log("   ✅ Video base concatenado con transiciones")
                else:
                    err = (result.stderr or '')[:220]
                    self.log(f"   ⚠️ Fallo xfade, usando concatenacion simple: {err}")
            except Exception as e:
                self.log(f"   ⚠️ Error en xfade, usando concatenacion simple: {e}")

        if not concat_ok:
            self.log("   🔗 Fase 2/3: Concatenando clips...")
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
                result = sp.run(concat_cmd, capture_output=True, text=True, timeout=120,
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
            result = sp.run(audio_cmd, capture_output=True, text=True, timeout=300,
                            creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode != 0:
                self.log(f"   ❌ Error agregando audio: {(result.stderr or '')[:200]}")
                return False
        except Exception as e:
            self.log(f"   ❌ Error agregando audio: {e}")
            return False

        # Verificar resultado
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            self.log("   ❌ Video final no fue creado correctamente")
            return False

        final_size = os.path.getsize(output_path) / (1024 * 1024)
        total_time = _time.time() - start_time
        self.log(f"   ✅ Video final: {final_size:.1f} MB (ensamblado en {total_time:.1f}s)")

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

    def assemble_video_from_storyboard(self, storyboard_data, platform,
                                       add_subtitles=True, subtitle_style='capcut',
                                       add_overlays=True, manual_bgm_path=None,
                                       manual_bgm_metadata=None,
                                       assembly_mode='auto', visual_mode='mixed',
                                       apply_cinematic=False, cinematic_preset='auto',
                                       transition_type='🌅 Fade Suave', transition_duration=0.5,
                                       generate_short_teaser=False, use_wikimedia=False,
                                       disable_wikimedia=False, use_real_images=True, 
                                       use_google_images=True, enable_real_images_mix=False, test_mode=False,
                                       image_provider='auto',
                                       allow_visual_regeneration=True):
        """
        Ensambla el video desde el storyboard.
        
        Args:
            generate_short_teaser: Si es True y platform='youtube', genera un short teaser en paralelo
            use_wikimedia: (OBSOLETO) Parámetro mantenido por compatibilidad - Solo se usan APIs de generación (Fal.ai FLUX.1 schnell, Leonardo AI)
        """
        
        self.log(f"\n🚀 ENSAMBLANDO VIDEO (Modo: {assembly_mode} / {visual_mode})...")
        if not allow_visual_regeneration:
            self.log("🧱 Modo estricto de ensamblaje: NO se generarán nuevas imágenes/videos IA.")
        
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
        
        # Iniciar generación de short teaser en paralelo si está habilitado
        teaser_thread = None
        teaser_result = None
        
        if generate_short_teaser and platform == 'youtube':
            self.log("🎬 Iniciando generación de Short Teaser en paralelo...")
            import threading
            
            def generate_teaser():
                nonlocal teaser_result
                try:
                    # Extraer idioma del storyboard o usar el del video principal
                    language = storyboard_data.get('language', 'es')
                    # Si el script está en inglés, usar inglés
                    script_sample = storyboard_data.get('script', '')[:100].lower()
                    if any(word in script_sample for word in ['the', 'and', 'was', 'were', 'this', 'that', 'from']):
                        language = 'en'
                    
                    # Obtener voice_id del storyboard si está disponible
                    voice_id = storyboard_data.get('voice_id', None)
                    voice_rate = storyboard_data.get('voice_rate', '+0%')
                    
                    self.log(f"🎬 Generando teaser en idioma: {language}")
                    teaser_result = self.generate_short_teaser_from_long_video(
                        long_video_storyboard=storyboard_data,
                        language=language,
                        voice_id=voice_id,
                        disable_wikimedia=disable_wikimedia,  # Pasar la configuración de desactivación
                        rate=voice_rate
                    )
                except Exception as e:
                    self.log(f"❌ Error generando short teaser: {e}")
            
            teaser_thread = threading.Thread(target=generate_teaser, daemon=True)
            teaser_thread.start()
        segments = storyboard_data['segments']
        # Política YouTube Shorts: evitar pistas Jamendo en shorts >60s para reducir bloqueos/reclamaciones.
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
            # Si no hay metadata confiable, usar heurística conservadora.
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
        is_vertical = platform in ['tiktok', 'reels', 'youtube_short']

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
            visual_prompt = seg['visual_prompt']
            media_path = None

            # 0) Priorizar media ya existente (video o imagen), resolviendo rutas relativas del proyecto.
            for media_field in ('video_path', 'image_path'):
                resolved_media = _resolve_existing_media_path(seg.get(media_field))
                if resolved_media:
                    media_path = resolved_media
                    media_type = "video" if media_field == 'video_path' else "imagen"
                    self.log(f"      ✅ Usando {media_type} existente: {os.path.basename(media_path)}")
                    break

            # 0.5) Compatibilidad: buscar por assigned_filename en generated_media_dir.
            if not media_path:
                for ext in ['.mp4', '.jpg', '.png', '.jpeg', '.webp']:
                    test_p = os.path.join(str(self.generated_media_dir), f"{fname}{ext}")
                    if os.path.exists(test_p):
                        media_path = test_p
                        self.log(f"      ✅ Usando media local existente: {os.path.basename(media_path)}")
                        break

            # Imagen marcada como eliminada: usar negro sin intentar regenerar.
            if not media_path and seg.get('image_deleted', False):
                self.log(f"      ⚫ Imagen eliminada, usando imagen negra para: {fname}")
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
                    # En modo prueba, no usar videos (solo imágenes de Wikimedia)
                    use_video = (visual_mode != 'static') and ((random.random() < 0.3) or (i < 1)) and not test_mode

                    # A. Generación de video con sistema de fallback (Leonardo Motion) - NO en modo prueba
                    if use_video and not test_mode:
                        # Generar imagen para Leonardo Motion usando Fal.ai primero, luego Leonardo
                        image_path_for_motion = None
                        w, h = (1080, 1920) if is_vertical else (1920, 1080)
                        
                        # Intentar Fal.ai primero
                        if self.fal_client:
                            img_url = self.fal_client.generate_image(visual_prompt, w, h)
                            if img_url:
                                temp_img_path = os.path.join(str(media_dir), f"{fname}_temp.jpg")
                                with open(temp_img_path, 'wb') as f:
                                    f.write(requests.get(img_url).content)
                                image_path_for_motion = temp_img_path
                        
                        # Fallback a Leonardo si Fal.ai falló
                        if not image_path_for_motion and self.leonardo_client:
                            img_url = self.leonardo_client.generate_image(visual_prompt, w, h)
                            if img_url:
                                temp_img_path = os.path.join(str(media_dir), f"{fname}_temp.jpg")
                                with open(temp_img_path, 'wb') as f:
                                    f.write(requests.get(img_url).content)
                                image_path_for_motion = temp_img_path

                        # Intentar generar video con Leonardo Motion si tenemos imagen
                        if image_path_for_motion:
                            video_output_path = os.path.join(str(media_dir), f"{fname}.mp4")
                            media_path = self.generate_video_with_fallback(
                                prompt=visual_prompt,
                                output_path=video_output_path,
                                is_vertical=is_vertical,
                                duration=4,
                                preferred_provider='leonardo',
                                image_path=image_path_for_motion
                            )

                        # Limpiar imagen temporal
                        if image_path_for_motion and os.path.exists(image_path_for_motion):
                            try:
                                os.remove(image_path_for_motion)
                            except:
                                pass

                    # B. Pexels Video (fallback si la generación IA falló completamente, NO en modo prueba)
                    if use_video and not media_path and self.downloader.pexels_key and not test_mode:
                        v = self.downloader.search_pexels_videos(visual_prompt)
                        if v:
                            media_path = self.downloader.download_video(v[0], os.path.join(str(self.generated_media_dir), f"{fname}.mp4"))

                    # C. Imagen (PRIORIDAD: Fal.ai FLUX.1 schnell primero, Leonardo AI como fallback)
                    if not media_path:
                        w, h = (1080, 1920) if is_vertical else (1920, 1080)
                        
                        # PRIORIDAD 1: Fal.ai FLUX.1 schnell
                        if self.fal_client and not test_mode:
                            try:
                                self.log(f"      🎨 Fal.ai FLUX.1 schnell: {fname}")
                                img_url = self.fal_client.generate_image(visual_prompt, w, h)
                                if img_url:
                                    tp = os.path.join(str(self.generated_media_dir), f"{fname}.jpg")
                                    with open(tp, 'wb') as f:
                                        f.write(requests.get(img_url).content)
                                    media_path = tp
                                    self.log(f"         ✅ Imagen generada por Fal.ai FLUX.1 schnell")
                            except Exception as e:
                                self.log(f"         ⚠️ Fal.ai falló: {str(e)[:50]}")
                        
                        # FALLBACK: Leonardo AI si Fal.ai falló
                        if not media_path and self.leonardo_client and not test_mode:
                            try:
                                self.log(f"      🎨 Leonardo AI (fallback): {fname}")
                                img_url = self.leonardo_client.generate_image(visual_prompt, w, h)
                                if img_url:
                                    tp = os.path.join(str(self.generated_media_dir), f"{fname}.jpg")
                                    with open(tp, 'wb') as f:
                                        f.write(requests.get(img_url).content)
                                    media_path = tp
                                    self.log(f"         ✅ Imagen generada por Leonardo AI (fallback)")
                            except Exception as e:
                                self.log(f"         ⚠️ Leonardo AI falló: {str(e)[:50]}")

                        # PRIORIDAD 4: Fallbacks de IA (Fal.ai, Runway, Eden, Pexels) - solo si Leonardo falló
                        if not media_path and not test_mode:
                            # PRIORIDAD 4.1: Fal.ai (fallback)
                            if not media_path and self.fal_available:
                                try:
                                    import fal_client
                                    self.log(f"      ⚡ Fal.ai FLUX (fallback): {fname}")
                                    result = fal_client.subscribe(
                                        "fal-ai/flux/schnell",
                                        arguments={
                                            "prompt": visual_prompt,
                                            "image_size": "portrait_9_16" if is_vertical else "landscape_16_9",
                                            "num_inference_steps": 4,
                                            "num_images": 1
                                        }
                                    )
                                    if result and 'images' in result and len(result['images']) > 0:
                                        image_url = result['images'][0]['url']
                                        tp = os.path.join(str(self.generated_media_dir), f"{fname}.png")
                                        with open(tp, 'wb') as f:
                                            f.write(requests.get(image_url).content)
                                        media_path = tp
                                        self.log(f"         ✅ Imagen generada por Fal.ai FLUX")
                                except Exception as e:
                                    self.log(f"         ⚠️ Fal.ai falló: {str(e)[:50]}")
                            
                            # PRIORIDAD 4.2: Runway Gen4 (fallback)
                            if not media_path and self.runway_client:
                                try:
                                    self.log(f"      🚀 Runway Gen4 (fallback): {fname}")
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
                                        self.log(f"         ✅ Imagen generada por Runway Gen4")
                                except Exception as e:
                                    self.log(f"         ⚠️ Runway falló: {str(e)[:50]}")
                            
                            # PRIORIDAD 4.3: Eden AI (fallback)
                            if not media_path and hasattr(self, 'eden_ai_available') and self.eden_ai_available:
                                try:
                                    eden_api_key = os.getenv("EDEN_AI_API_KEY")
                                    if eden_api_key:
                                        self.log(f"      🌟 Eden AI (fallback): {fname}")
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
                                                                        self.log(f"         ✅ Imagen generada por Eden AI ({provider})")
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
                                    self.log(f"         ⚠️ Eden AI falló: {str(e)[:50]}")
                            
                            # PRIORIDAD 4.4: Pexels (último fallback)
                            if not media_path and self.downloader.pexels_key:
                                self.log(f"      🔍 Pexels (fallback): {fname}")
                                imgs = self.downloader.search_pexels_images(visual_prompt)
                                if imgs:
                                    media_path = self.downloader.download_image(imgs[0], os.path.join(str(self.generated_media_dir), f"{fname}.jpg"))
                                    if media_path:
                                        self.log(f"         ✅ Imagen descargada de Pexels")

            # Si falta media y NO se permite regenerar, crear placeholder negro.
            if not media_path and not allow_visual_regeneration:
                self.log(f"      ⚫ Sin media para {fname}; se usa placeholder (regeneración IA desactivada)")
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
            if add_overlays and GIPHY_AVAILABLE and seg.get('overlay_tag') != 'none':
                ov_path = find_and_download_gif(seg['overlay_tag'], self.generated_media_dir)

            if media_path:
                # Usar os.path.abspath para la ruta definitiva
                abs_p = os.path.abspath(media_path)
                # Mantener coherencia temporal con el timeline narrativo:
                # si hay hueco entre este segmento y el siguiente, extender
                # visualmente este clip para cubrir ese silencio.
                seg_start = float(seg.get('start', 0) or 0)
                seg_end = float(seg.get('end', seg_start) or seg_start)
                seg_duration = max(0.05, seg_end - seg_start)

                if (i + 1) < len(segments):
                    try:
                        next_start = float(segments[i + 1].get('start', seg_end) or seg_end)
                        if next_start > seg_end:
                            seg_duration += (next_start - seg_end)
                    except Exception:
                        pass

                generated_clips.append({
                    'filename': abs_p,
                    'timestamp_start': seg_start,
                    'duration': seg_duration,
                    'overlay_filename': os.path.basename(ov_path) if ov_path else None,
                    'sfx_path': sfx_path
                })
            else:
                self.log(f"      ⚠️ No se generó visual para: {fname}")

        # 2. Ensamblar
        res = VideoConfig.VIDEO_RESOLUTION_VERTICAL if is_vertical else VideoConfig.VIDEO_RESOLUTION

        # Verificar que el audio existe antes de ensamblar
        audio_path = storyboard_data.get('audio_path')
        if not audio_path or not os.path.exists(audio_path):
            self.log(f"❌ ERROR: Audio no encontrado en: {audio_path}")
            return None

        # === RUTA RÁPIDA: FFmpeg directo (sin MoviePy) ===
        # Ensamblar directamente con FFmpeg es ~2x más rápido y más robusto.
        # Soporta imágenes Y videos. Evita problemas de CompositeVideoClip y seek.
        # Solo se desactiva cuando hay efectos cinematográficos (que requieren MoviePy).
        all_supported_media = all(
            c.get('filename', '').lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.mp4', '.mov', '.avi', '.webm', '.mkv'))
            for c in generated_clips
        ) if generated_clips else False

        self.log(f"   🔍 DEBUG: {len(generated_clips)} clips, música: {'SÍ' if manual_bgm_path or effective_music_data else 'NO'}, PYDUB: {'SÍ' if PYDUB_AVAILABLE else 'NO'}")

        # Preparar música de fondo (si existe) antes de decidir la ruta
        bgm = manual_bgm_path
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
        # Agregar segundos extra después de la narración para un cierre gradual
        OUTRO_FADE_SECONDS = 4  # Segundos extra después de la narración
        final_audio_path = audio_path
        audio_has_outro = False  # Flag para indicar que el audio ya tiene el outro integrado
        self.log(f"   🔍 DEBUG: bgm={bgm}, exists={os.path.exists(bgm) if bgm else False}")
        if bgm and os.path.exists(bgm):
            try:
                if PYDUB_AVAILABLE:
                    outro_ms = OUTRO_FADE_SECONDS * 1000
                    self.log(f"   🎵 Preparando audio con música (fade out {OUTRO_FADE_SECONDS}s después de narración)...")
                    v = AudioSegment.from_file(audio_path)
                    m = AudioSegment.from_file(bgm)

                    # Extender narración con silencio para crear espacio para el fade-out de música
                    # Esto permite que la música siga sonando (con fade) después de que termine la narración
                    v_extended = v + AudioSegment.silent(duration=outro_ms)
                    total_duration = len(v_extended)  # narración + outro

                    # Asegurar que la música cubra toda la duración
                    if len(m) < total_duration:
                        m = m * (int(total_duration / len(m)) + 2)

                    # Recortar música y aplicar fade out durante los segundos extra
                    music_segment = m[:total_duration]
                    music_with_fadeout = music_segment.fade_out(outro_ms)

                    # Mezclar: narración (con silencio al final) + música (con fade-out al final)
                    # El resultado tendrá: narración+música durante la narración, luego solo música con fade-out
                    # VOLUMEN: -15dB hace que la música esté muy baja, permitiendo que la narración destaque
                    final_mix = v_extended.overlay(music_with_fadeout - 15)
                    mp = str(self.generated_media_dir / "mix.mp3")
                    final_mix.export(mp, format="mp3")
                    final_audio_path = mp
                    audio_has_outro = True
                    self.log(f"   ✅ Audio preparado: narración ({len(v)/1000:.1f}s) + outro con música fade-out ({OUTRO_FADE_SECONDS}s)")

                    # EXTENDER el último clip para cubrir los segundos extra del outro
                    if generated_clips:
                        last_clip = generated_clips[-1]
                        original_duration = last_clip.get('duration', 0)
                        last_clip['duration'] = original_duration + OUTRO_FADE_SECONDS
                        last_clip['timestamp_end'] = last_clip.get('timestamp_start', 0) + last_clip['duration']
                        self.log(f"   ⏱️ Último clip extendido: {original_duration:.1f}s → {last_clip['duration']:.1f}s (outro)")
                else:
                    self.log(f"   ⚠️ PYDUB no disponible, no se puede aplicar fade out a la música")
            except Exception as e:
                self.log(f"   ⚠️ Error preparando audio con música: {e}")
                import traceback
                traceback.print_exc()
                final_audio_path = audio_path  # Fallback a audio original
                audio_has_outro = False

        # Si no hay música pero sí pydub, agregar silencio al final para el fade-out de video
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
                self.log(f"   🎬 Audio extendido con {OUTRO_FADE_SECONDS}s de silencio para fade-out de video")

                # Extender último clip
                if generated_clips:
                    last_clip = generated_clips[-1]
                    original_duration = last_clip.get('duration', 0)
                    last_clip['duration'] = original_duration + OUTRO_FADE_SECONDS
                    last_clip['timestamp_end'] = last_clip.get('timestamp_start', 0) + last_clip['duration']
                    self.log(f"   ⏱️ Último clip extendido: {original_duration:.1f}s → {last_clip['duration']:.1f}s (outro)")
            except Exception as e:
                self.log(f"   ⚠️ Error extendiendo audio: {e}")

        if all_supported_media and not apply_cinematic and generated_clips:
            has_videos = any(c.get('filename', '').lower().endswith(('.mp4', '.mov', '.avi', '.webm', '.mkv')) for c in generated_clips)
            mode_desc = "imágenes + videos" if has_videos else "imágenes"
            self.log(f"\n🚀 Modo rápido: ensamblaje directo con FFmpeg ({mode_desc}, sin MoviePy)...")

            requested_out = VideoConfig.OUTPUT_DIR / f"{platform}_{int(time.time())}.mp4"
            out, using_local_safe_output = _resolve_safe_video_output_path(requested_out)
            if using_local_safe_output:
                self.log("⚠️ Unidad remota/WebDAV detectada para exportación de video.")
                self.log(f"   Guardando video base localmente para evitar ERROR_FILE_TOO_LARGE (0x800700DF): {out}")
            self.log(f"📹 Exportando video a: {out}")

            direct_ok = self._assemble_direct_ffmpeg(
                generated_clips, final_audio_path, str(out), res,
                transition_type=transition_type,
                transition_duration=transition_duration
            )

            if direct_ok:
                file_size_mb = os.path.getsize(str(out)) / 1024 / 1024
                self.log(f"✅ Video exportado: {file_size_mb:.1f} MB")

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

                # Aplicar subtítulos dinámicos si están activos
                if add_subtitles and hasattr(self, '_dynamic_subtitle_wrapper'):
                    self.log("🎬 Aplicando subtítulos dinámicos al video final...")
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

                            # Verificar que el ASS se generó con contenido
                            if not os.path.exists(ass_path) or os.path.getsize(ass_path) < 50:
                                self.log(f"⚠️ Archivo ASS no generado o vacío: {ass_path}")
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
                                        self.log(f"✅ Subtítulos dinámicos aplicados (estilo: {subtitle_style})")
                                        result['video_path'] = str(out)
                                        subs_applied = True
                                    except Exception as e:
                                        self.log(f"⚠️ No se pudo reemplazar el video: {e}")
                                        result['video_path'] = video_with_subs
                                        subs_applied = True
                                else:
                                    self.log(f"❌ burn_subtitles_with_ffmpeg falló - el video NO tiene subtítulos")
                        else:
                            self.log(f"⚠️ No hay segmentos para generar subtítulos")
                    except Exception as e:
                        self.log(f"❌ Error aplicando subtítulos dinámicos: {e}")
                        import traceback
                        self.log(f"   {traceback.format_exc().splitlines()[-1]}")

                    if not subs_applied:
                        self.log(f"🔴 ATENCIÓN: El video final NO contiene subtítulos. "
                                 f"Podés aplicarlos manualmente con: python simple_subs.py")

                # Esperar teaser si está en proceso
                if generate_short_teaser and platform == 'youtube' and teaser_thread:
                    self.log("⏳ Esperando a que termine la generación del Short Teaser...")
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
                        self.log("✅ Short Teaser generado exitosamente")

                return result
            else:
                self.log("⚠️ FFmpeg directo falló, intentando con MoviePy...")

        # === RUTA MOVIEPY (fallback o videos con efectos/clips de video) ===
        self.log(f"🎵 Cargando audio desde: {final_audio_path}")
        final, audio = self.contextual_assembler.assemble_video_from_prompts(
            generated_clips, final_audio_path, res, self.generated_media_dir,
            apply_cinematic=apply_cinematic, cinematic_preset=cinematic_preset,
            transition_type=transition_type, transition_duration=transition_duration,
            segments=storyboard_data['segments'],
            extra_duration_override=0 if audio_has_outro else None
        )
        
        if not final:
            self.log("❌ ERROR: No se pudo ensamblar el video")
            return None
        
        if not audio:
            self.log("❌ ERROR: No se pudo cargar el audio")
            return None
        
        self.log(f"✅ Audio cargado: {audio.duration:.2f}s")

        # 3. Subtítulos (solo si NO se están usando subtítulos dinámicos)
        # Los subtítulos dinámicos se aplican después en dynamic_subtitle_wrapper
        # Solo usar MoviePy TextClip si los subtítulos dinámicos no están activos
        if add_subtitles and not hasattr(self, '_dynamic_subtitle_wrapper'):
            try:
                s = self.subtitle_gen.create_subtitle_clips(segments, res, subtitle_style)
                if s: final = CompositeVideoClip([final] + s)
            except Exception as e:
                # Si falla (por ejemplo, ImageMagick no disponible), continuar sin subtítulos MoviePy
                # Los subtítulos dinámicos se aplicarán después si están configurados
                self.log(f"⚠️ No se pudieron crear subtítulos MoviePy (ImageMagick puede no estar disponible): {e}")
                self.log(f"   Continuando sin subtítulos MoviePy...")

        # 4. Audio Final
        self.log("🎵 Configurando audio final...")
        audio_layers = []
        
        # Asegurar que el audio principal esté en la lista
        if audio:
            audio_layers.append(audio)
            self.log(f"   ✅ Audio principal agregado ({audio.duration:.2f}s)")
        else:
            self.log("   ❌ ERROR: No hay audio principal disponible")
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
                    self.log(f"   ⚠️ Error cargando SFX {c['sfx_path']}: {e}")
        
        if sfx_count > 0:
            self.log(f"   ✅ {sfx_count} efectos de sonido agregados")
        
        # Agregar música de fondo
        # NOTA: Si hay música (bgm existe), el audio ya fue mezclado arriba con fade out
        # Solo necesitamos verificar que el audio_layers[0] sea el audio mezclado
        if bgm and os.path.exists(bgm) and final_audio_path != audio_path:
            # El audio fue mezclado arriba, asegurarnos de usar el archivo mix.mp3
            try:
                if os.path.exists(final_audio_path):
                    audio_layers[0] = AudioFileClip(final_audio_path)
                    self.log(f"   ✅ Usando audio pre-mezclado con música (fade out 3s)")
            except Exception as e:
                self.log(f"   ⚠️ Error cargando audio mezclado: {e}")

        # Crear audio compuesto
        if len(audio_layers) == 0:
            self.log("❌ ERROR: No hay capas de audio para el video")
            return None
        
        try:
            # Si solo hay una capa, usar directamente (evita problemas con CompositeAudioClip)
            if len(audio_layers) == 1:
                final_audio = audio_layers[0]
                self.log(f"✅ Audio final configurado (1 capa única - sin mezcla)")
            else:
                # Solo usar CompositeAudioClip si hay múltiples capas (SFX, música separada, etc.)
                final_audio = CompositeAudioClip(audio_layers)
                self.log(f"✅ Audio final configurado ({len(audio_layers)} capas mezcladas)")
            
            final = final.set_audio(final_audio)
        except Exception as e:
            self.log(f"❌ ERROR al crear audio compuesto: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        # 5. Exportar
        requested_out = VideoConfig.OUTPUT_DIR / f"{platform}_{int(time.time())}.mp4"
        out, using_local_safe_output = _resolve_safe_video_output_path(requested_out)
        if using_local_safe_output:
            self.log("⚠️ Unidad remota/WebDAV detectada para exportación de video.")
            self.log(f"   Guardando video base localmente para evitar ERROR_FILE_TOO_LARGE (0x800700DF): {out}")
        self.log(f"📹 Exportando video a: {out}")
        
        # Verificar que el audio esté configurado antes de exportar
        if final.audio is None:
            self.log("⚠️ ADVERTENCIA: El video no tiene audio configurado. Intentando agregar audio...")
            if audio:
                final = final.set_audio(audio)
                self.log("✅ Audio agregado al video")
            else:
                self.log("❌ ERROR: No hay audio disponible para el video")
        
        # Crear logger personalizado compatible con MoviePy
        # MoviePy necesita un objeto logger con métodos como iter_bar, no solo una función
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
                            bar = '█' * filled + '░' * (bar_length - filled)
                            self.log_func(f"   [{bar}] {percent}%")
                            self.last_percent = percent
            
            def iter_bar(self, chunk=None, t=None, **kwargs):
                """Método requerido por MoviePy para iterar sobre chunks de audio o frames de video"""
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
        
        # Usar FFmpeg directo para exportación más rápida y optimizada
        self.log("🚀 Exportando con FFmpeg directo (más rápido y optimizado)...")
        
        # Determinar bitrate y preset según plataforma
        if is_vertical:
            video_bitrate = '6000k'  # 6 Mbps para shorts (9:16)
            preset = 'fast'  # Más rápido para shorts
        else:
            video_bitrate = '12000k'  # 12 Mbps para videos largos (16:9)
            preset = 'medium'  # Balance para videos largos
        
        self.log(f"   📊 Bitrate: {video_bitrate}, Preset: {preset}")
        
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
            self.log("⚠️ FFmpeg falló, usando MoviePy como fallback...")
            try:
                if video_duration > 0:
                    custom_logger = MoviePyLogger(self.log, video_duration)
                else:
                    custom_logger = 'bar'

                final.write_videofile(
                    str(out),
                    fps=30,
                    codec='libx264',
                    audio_codec='aac',
                    audio_bitrate='192k',
                    bitrate=video_bitrate,
                    preset=preset,
                    threads=4,
                    logger=custom_logger,
                    verbose=False
                )
            except Exception as moviepy_err:
                self.log(f"⚠️ MoviePy fallback también falló: {moviepy_err}")

            # Verificar si MoviePy produjo un video válido
            try:
                from video_export_manager import _probe_has_video_and_audio as _probe_check
                mv_has_v, _ = _probe_check(str(out), log_callback=self.log)
                if not mv_has_v and self.export_manager:
                    self.log("⚠️ MoviePy no generó video válido, intentando exportación directa con FFmpeg pipe...")
                    pipe_ok = self.export_manager._export_with_ffmpeg_pipe(
                        final, str(out), fps=30,
                        video_bitrate=video_bitrate, preset=preset,
                        video_duration=video_duration
                    )
                    if pipe_ok:
                        self.log("✅ Video exportado correctamente con FFmpeg pipe directo")
            except Exception:
                pass

        # Verificar que el video se exportó correctamente y es reproducible
        if not os.path.exists(str(out)):
            self.log(f"❌ ERROR: El video no se exportó correctamente")
            return None
        try:
            from video_export_manager import _probe_has_video_and_audio, _probe_duration
            has_v, has_a = _probe_has_video_and_audio(str(out), log_callback=self.log)
            dur = _probe_duration(str(out))
            out_fsize = os.path.getsize(str(out))
            if not has_v:
                # Si ffprobe no detecta video pero el archivo es grande, aceptar
                if out_fsize > 5 * 1024 * 1024:
                    self.log(f"⚠️ ffprobe no detecta video pero el archivo es grande ({out_fsize / (1024*1024):.1f} MB), aceptando como válido")
                    has_v = True
                elif dur < 0.5:
                    self.log(f"❌ ERROR: El video exportado está corrupto o no es válido (sin video o duración inválida)")
                    return None
            if not has_a:
                self.log(f"⚠️ ADVERTENCIA: El video no tiene pista de audio; puede no reproducirse correctamente en algunos reproductores.")
        except Exception as probe_err:
            self.log(f"⚠️ No se pudo verificar el video con ffprobe: {probe_err}")
        file_size_mb = os.path.getsize(str(out)) / 1024 / 1024
        self.log(f"✅ Video exportado: {file_size_mb:.1f} MB")
        
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
        
        # 6. Aplicar subtítulos dinámicos si están activos y el patch está aplicado
        if add_subtitles and hasattr(self, '_dynamic_subtitle_wrapper'):
            self.log("🎬 Aplicando subtítulos dinámicos al video final...")
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
                        self.log(f"⚠️ Archivo ASS no generado o vacío: {ass_path}")
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
                                self.log("✅ Subtítulos dinámicos aplicados al video final")
                                result['video_path'] = str(out)
                                subs_applied = True
                            except Exception as e:
                                self.log(f"⚠️ No se pudo reemplazar el video: {e}")
                                result['video_path'] = video_with_subs
                                subs_applied = True
                        else:
                            self.log(f"❌ burn_subtitles_with_ffmpeg falló - el video NO tiene subtítulos")
                else:
                    self.log(f"⚠️ No hay segmentos para generar subtítulos")
            except Exception as e:
                self.log(f"❌ Error aplicando subtítulos dinámicos: {e}")
                import traceback
                self.log(f"   {traceback.format_exc().splitlines()[-1]}")

            if not subs_applied:
                self.log(f"🔴 ATENCIÓN: El video final NO contiene subtítulos. "
                         f"Podés aplicarlos manualmente con: python simple_subs.py")
        
        # Esperar a que termine la generación del teaser si está en proceso
        if generate_short_teaser and platform == 'youtube' and teaser_thread:
            self.log("⏳ Esperando a que termine la generación del Short Teaser...")
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
                self.log("✅ Short Teaser generado exitosamente en paralelo")
            else:
                self.log("⚠️ Short Teaser no se pudo generar (puede estar aún procesándose)")
        
        return result
        
if __name__ == "__main__":
    print("Ejecuta video-opt-app.py para usar la interfaz.")
