# video_config.py
"""
Configuracion centralizada del sistema de generacion de videos.
Adaptado para funcionar tanto en Windows (desktop) como Linux (Docker/web).
"""

import os
import sys
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

IS_LINUX = sys.platform.startswith("linux")
IS_WINDOWS = sys.platform == "win32"


def find_ffmpeg_paths():
    """Busca FFmpeg y ffprobe en rutas comunes (cross-platform)"""
    # 1. Check PATH first (works on both Linux and Windows)
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return os.path.dirname(ffmpeg_in_path)

    # 2. Check env var
    env_path = os.getenv("FFMPEG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # 3. Common Linux paths
    if IS_LINUX:
        for p in ["/usr/bin", "/usr/local/bin"]:
            if os.path.exists(os.path.join(p, "ffmpeg")):
                return p

    # 4. Common Windows paths
    if IS_WINDOWS:
        possible_paths = [
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
        ]
        for path in possible_paths:
            if path and os.path.exists(path):
                ffmpeg_exe = os.path.join(path, "ffmpeg.exe")
                ffprobe_exe = os.path.join(path, "ffprobe.exe")
                if os.path.exists(ffmpeg_exe) and os.path.exists(ffprobe_exe):
                    return path

    return None


def _get_binary_name(base_name):
    """Returns 'ffmpeg.exe' on Windows, 'ffmpeg' on Linux"""
    if IS_WINDOWS:
        return f"{base_name}.exe"
    return base_name


class VideoConfig:
    """Configuracion centralizada del sistema"""

    # FFmpeg Configuration
    _ffmpeg_path = find_ffmpeg_paths()
    FFMPEG_BINARY_PATH = _ffmpeg_path or os.getenv("FFMPEG_PATH")
    FFPROBE_BINARY_PATH = (
        os.path.join(_ffmpeg_path, _get_binary_name("ffprobe"))
        if _ffmpeg_path
        else None
    )

    @classmethod
    def ensure_ffmpeg_in_path(cls):
        """Asegura que FFmpeg este en el PATH"""
        if cls.FFMPEG_BINARY_PATH and os.path.exists(cls.FFMPEG_BINARY_PATH):
            if cls.FFMPEG_BINARY_PATH not in os.environ.get("PATH", ""):
                os.environ["PATH"] = (
                    cls.FFMPEG_BINARY_PATH
                    + os.pathsep
                    + os.environ.get("PATH", "")
                )
                print(f"[OK] FFmpeg anadido al PATH: {repr(cls.FFMPEG_BINARY_PATH)}")
        else:
            print(f"[WARN] FFmpeg no encontrado en: {repr(cls.FFMPEG_BINARY_PATH)}")

    @staticmethod
    def get_negative_prompt(base_negative=None):
        """Genera un negative prompt robusto para prevenir errores de generacion IA."""
        negative_base = [
            "distorted", "deformed", "malformed", "disfigured", "mutated",
            "ugly", "bad anatomy", "bad proportions", "extra limbs", "missing limbs",
            "extra fingers", "missing fingers", "fused fingers", "too many fingers",
            "extra arms", "extra legs", "extra heads", "duplicate", "cloned",
            "malformed hands", "malformed feet", "malformed face", "asymmetric",
            "text", "words", "letters", "numbers", "signs", "symbols", "logos",
            "watermark", "signature", "copyright", "trademark", "brand",
            "artifacts", "glitches", "noise", "grain", "pixelated", "blurry",
            "low quality", "low resolution", "jpeg artifacts", "compression artifacts",
            "double exposure", "ghosting", "halo", "lens flare", "chromatic aberration",
            "bad composition", "cropped", "cut off", "out of frame", "incomplete",
            "partial", "truncated", "amputated", "floating objects", "disconnected",
            "unrealistic", "impossible", "illogical", "nonsensical",
            "overexposed", "underexposed", "washed out", "oversaturated", "undersaturated",
            "color bleeding", "color shift", "unnatural colors", "wrong colors",
            "nude", "naked", "nsfw", "explicit", "inappropriate",
            "modern technology", "modern vehicles", "modern buildings", "anachronism",
            "contemporary", "modern clothing", "modern architecture",
            "amateur", "unprofessional", "draft", "sketch", "unfinished",
            "cartoon", "animation", "3d render", "cgi", "computer graphics",
            "stock photo", "generic", "boring", "uninteresting",
        ]
        negative_prompt = ", ".join(negative_base)
        if base_negative:
            try:
                base_negative_clean = base_negative.encode("ascii", "ignore").decode("ascii")
                if base_negative_clean.strip():
                    negative_prompt = f"{negative_prompt}, {base_negative_clean}"
            except Exception:
                base_negative_clean = "".join(
                    char for char in base_negative if ord(char) < 128
                )
                if base_negative_clean.strip():
                    negative_prompt = f"{negative_prompt}, {base_negative_clean}"
        try:
            negative_prompt = negative_prompt.encode("ascii", "ignore").decode("ascii")
        except Exception:
            negative_prompt = "".join(
                char for char in negative_prompt if ord(char) < 128
            )
        return negative_prompt

    # APIs
    PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
    PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    RECRAFT_API_KEY = os.getenv("RECRAFT_API_KEY")
    LEONARDO_API_KEY = os.getenv("LEONARDO_API_KEY") or RECRAFT_API_KEY
    FAL_API_KEY = os.getenv("FAL_API_KEY") or RECRAFT_API_KEY

    # Directories - configurable via env vars for Docker
    ROOT_DIR = Path(os.getenv("APP_ROOT_DIR", str(Path(__file__).resolve().parent)))
    BASE_DIR = Path(os.getenv("APP_MEDIA_DIR", str(ROOT_DIR / "auto_videos")))
    DOWNLOADS_DIR = BASE_DIR / "downloads"
    AUDIO_DIR = BASE_DIR / "audio"
    OUTPUT_DIR = BASE_DIR / "output"
    TEMP_DIR = BASE_DIR / "temp"
    BGM_DIR = BASE_DIR / "bgm_library"

    # Video config
    VIDEO_RESOLUTION = (1920, 1080)
    VIDEO_RESOLUTION_VERTICAL = (1080, 1920)
    VIDEO_RESOLUTION_SQUARE = (1080, 1080)
    DEFAULT_VIDEO_WIDTH = 1920
    DEFAULT_VIDEO_HEIGHT = 1080
    DEFAULT_VIDEO_FPS = 30

    # Platform durations (seconds)
    PLATFORM_DURATIONS = {
        "youtube": 1800,
        "youtube_short": 120,
        "tiktok": 60,
        "reels": 60,
        "square": 180,
    }

    # Subtitle styles
    SUBTITLE_STYLES = {
        "capcut": {
            "font_size": 70,
            "font_color": "white",
            "stroke_color": "black",
            "stroke_width": 3,
            "bg_color": None,
            "position": ("center", "bottom"),
            "animation": "pop",
        },
        "modern": {
            "font_size": 60,
            "font_color": "yellow",
            "stroke_color": "black",
            "stroke_width": 2,
            "bg_color": "rgba(0,0,0,0.7)",
            "position": ("center", "bottom"),
            "animation": "pop",
        },
        "minimal": {
            "font_size": 50,
            "font_color": "white",
            "stroke_color": None,
            "stroke_width": 0,
            "bg_color": None,
            "position": ("center", "bottom"),
            "animation": "pop",
        },
        "alex_hormozi": {
            "font_size": 80,
            "font_color": "yellow",
            "stroke_color": "black",
            "stroke_width": 4,
            "bg_color": "rgba(0,0,0,0.8)",
            "position": ("center", "center"),
            "animation": "zoom",
            "highlight_keywords": True,
        },
    }

    @classmethod
    def setup_directories(cls):
        """Crea todos los directorios necesarios"""
        for directory in [
            cls.BASE_DIR,
            cls.DOWNLOADS_DIR,
            cls.AUDIO_DIR,
            cls.OUTPUT_DIR,
            cls.TEMP_DIR,
            cls.BGM_DIR,
        ]:
            directory.mkdir(parents=True, exist_ok=True)
        print("[OK] Directorios configurados")

    @classmethod
    def configure_for_project(cls, user_id: str, project_id: str):
        """Configure paths for a specific user/project (web mode)"""
        media_root = Path(os.getenv("APP_MEDIA_DIR", "/app/media"))
        project_dir = media_root / user_id / project_id
        cls.BASE_DIR = project_dir
        cls.DOWNLOADS_DIR = project_dir / "downloads"
        cls.AUDIO_DIR = project_dir / "audio"
        cls.OUTPUT_DIR = project_dir / "output"
        cls.TEMP_DIR = project_dir / "temp"
        cls.BGM_DIR = project_dir / "bgm_library"
        cls.setup_directories()
