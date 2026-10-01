# video_config.py
"""
ConfiguraciÃ³n centralizada del sistema de generaciÃ³n de videos
"""

import os
import shutil
from pathlib import Path
from infra.env_loader import load_project_env

load_project_env()


def _find_winget_ffmpeg_dirs():
    """Busca instalaciones de FFmpeg hechas por winget para el usuario actual."""
    if os.name != "nt":
        return []

    winget_packages_dir = (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        / "Microsoft"
        / "WinGet"
        / "Packages"
    )
    if not winget_packages_dir.exists():
        return []

    discovered = []
    seen = set()
    for package_dir in winget_packages_dir.glob("*FFmpeg*"):
        if not package_dir.is_dir():
            continue

        for ffmpeg_exe in package_dir.rglob("ffmpeg.exe"):
            bin_dir = ffmpeg_exe.parent
            ffprobe_exe = bin_dir / "ffprobe.exe"
            if not ffprobe_exe.exists():
                continue

            bin_dir_str = str(bin_dir)
            if bin_dir_str.lower() in seen:
                continue

            seen.add(bin_dir_str.lower())
            discovered.append(bin_dir_str)

    return discovered


def find_ffmpeg_paths():
    """Busca FFmpeg y ffprobe en rutas comunes"""
    possible_paths = [
        # Ruta desde .env
        os.getenv("FFMPEG_PATH"),
        # Rutas Windows comunes
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files (x86)\ffmpeg\bin",
        # Rutas con versiones especÃ­ficas
        r"C:\Program Files\ffmpeg-2025-11-06-git-222127418b-full_build\bin",
    ]

    possible_paths.extend(_find_winget_ffmpeg_dirs())
    
    # Buscar en PATH
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        possible_paths.insert(0, os.path.dirname(ffmpeg_in_path))
    
    # Verificar cuÃ¡l existe
    for path in possible_paths:
        if path and os.path.exists(path):
            ffmpeg_exe = os.path.join(path, "ffmpeg.exe")
            ffprobe_exe = os.path.join(path, "ffprobe.exe")
            if os.path.exists(ffmpeg_exe) and os.path.exists(ffprobe_exe):
                return path
    
    return None


class VideoConfig:
    """ConfiguraciÃ³n centralizada del sistema"""
    
    # FFmpeg Configuration - detectar automÃ¡ticamente
    _ffmpeg_path = find_ffmpeg_paths()
    FFMPEG_BINARY_PATH = _ffmpeg_path or os.getenv("FFMPEG_PATH")
    FFPROBE_BINARY_PATH = os.path.join(_ffmpeg_path, "ffprobe.exe") if _ffmpeg_path else None
    
    @classmethod
    def ensure_ffmpeg_in_path(cls):
        """Asegura que FFmpeg estÃ© en el PATH"""
        if cls.FFMPEG_BINARY_PATH and os.path.exists(cls.FFMPEG_BINARY_PATH):
            if cls.FFMPEG_BINARY_PATH not in os.environ.get("PATH", ""):
                os.environ["PATH"] = cls.FFMPEG_BINARY_PATH + os.pathsep + os.environ.get("PATH", "")
                # Usar repr() para evitar problemas con caracteres especiales en rutas
                print(f"[OK] FFmpeg anadido al PATH: {repr(cls.FFMPEG_BINARY_PATH)}")
        else:
            print(f"âš ï¸ FFmpeg no encontrado en: {repr(cls.FFMPEG_BINARY_PATH)}")
    
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
    RECRAFT_API_KEY = os.getenv("RECRAFT_API_KEY")
    LEONARDO_API_KEY = os.getenv("LEONARDO_API_KEY") or RECRAFT_API_KEY
    FAL_API_KEY = os.getenv("FAL_API_KEY") or RECRAFT_API_KEY
    
    # Directorios
    ROOT_DIR = Path(__file__).resolve().parent.parent
    BASE_DIR = ROOT_DIR / "auto_videos"
    DOWNLOADS_DIR = BASE_DIR / "downloads"
    AUDIO_DIR = BASE_DIR / "audio"
    OUTPUT_DIR = BASE_DIR / "output"
    TEMP_DIR = BASE_DIR / "temp"
    BGM_DIR = BASE_DIR / "bgm_library"  # Para mÃºsica manual
    
    # ConfiguraciÃ³n de video
    VIDEO_RESOLUTION = (1920, 1080)  # YouTube horizontal
    VIDEO_RESOLUTION_VERTICAL = (1080, 1920)  # Vertical (Shorts/TikTok)
    VIDEO_RESOLUTION_SQUARE = (1080, 1080)  # Cuadrado (X)
    DEFAULT_VIDEO_WIDTH = 1920
    DEFAULT_VIDEO_HEIGHT = 1080
    DEFAULT_VIDEO_FPS = 30
    
    # Duraciones por plataforma (segundos)
    PLATFORM_DURATIONS = {
        'youtube': 1800,      # 30 minutos (largo horizontal)
        'youtube_short': 120,  # 2 minutos
        'youtube_vertical': 600,  # 10 minutos vertical largo
        'tiktok': 60,        # 1 minuto
        'reels': 60,         # 1 minuto
        'square': 180        # 3 minutos (editable por slider)
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



