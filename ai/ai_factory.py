import sys
from pathlib import Path


class AIFactory:
    _instance = None
    _TEXT_LLM_ALIASES = {"groq", "gemini", "claude", "text_ai"}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._clients = {}
        self._default_llm = "groq"
        self._load_preferences()

    def _load_preferences(self):
        try:
            config_path = Path("video_config.py")
            if config_path.exists():
                pass
        except Exception:
            pass


    def get_llm_client(self):
        """Retorna el cliente principal de texto (Groq, via wrapper compatible)."""
        return self.get_client("groq")

    def get_client(self, name):
        """Patron Singleton por tipo de cliente para ahorrar recursos."""
        name = str(name or "").lower()
        if name in self._clients:
            return self._clients[name]

        client = None
        try:
            if name == "gemini":
                from ai.gemini_ai_client import GeminiAiClient
                client = GeminiAiClient()
            elif name in {"claude", "groq", "text_ai"}:
                from ai.claude_client import ClaudeAiClient
                client = ClaudeAiClient()
            elif name == "recraft":
                from ai.recraft_client import RecraftClient
                client = RecraftClient()
            elif name == "bing":
                from bing_images_client import BingImagesClient
                client = BingImagesClient()
            elif name == "wikimedia":
                from wikimedia_client import WikimediaClient
                client = WikimediaClient()
            elif name == "google_ai":
                from ai.google_ai_image_client import GoogleAiImageClient
                client = GoogleAiImageClient()
            elif name == "google_images":
                from ai.google_images_client import GoogleImagesClient
                client = GoogleImagesClient()
            elif name in {"comfyui", "comfy"}:
                from ai.comfyui_image_client import ComfyUiImageClient
                client = ComfyUiImageClient()
            elif name == "image_manager":
                from image_generation_manager import ImageGenerationManager
                client = ImageGenerationManager(comfyui_image_client=self.get_client("comfyui"))
            elif name == "video_manager":
                from video_generation_manager import VideoGenerationManager
                client = VideoGenerationManager()
            elif name == "export_manager":
                from video_export_manager import VideoExportManager
                client = VideoExportManager()
            else:
                raise ValueError(f"Cliente '{name}' desconocido.")

            self._clients[name] = client
            return client
        except ImportError as e:
            print(f"AIFactory: Modulo no encontrado ({e})", file=sys.stderr)
            return None
        except Exception as e:
            print(f"AIFactory: Error creando {name} ({e})", file=sys.stderr)
            return None
