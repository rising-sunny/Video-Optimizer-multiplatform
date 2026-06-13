# timeline_workers.py
"""
Workers (QThread) para Timeline Editor.
ExtraÃ­do de timeline_editor_widget.py para mejorar la organizaciÃ³n del cÃ³digo.

Contiene workers para:
- ExtracciÃ³n de frames de video
- RegeneraciÃ³n de imÃ¡genes con IA
- BÃºsqueda de imÃ¡genes en Wikimedia
- BÃºsqueda de imÃ¡genes en Openverse
- BÃºsqueda de videos en Pexels
- BÃºsqueda de videos en Wikimedia Commons
- BÃºsqueda de videos en Internet Archive
- BÃºsqueda de videos en YouTube
"""

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
import os
import time
import threading
import requests

# Importaciones condicionales
try:
    from wikimedia_client import WikimediaClient
    WIKIMEDIA_AVAILABLE = True
except ImportError:
    WIKIMEDIA_AVAILABLE = False
    WikimediaClient = None

try:
    from bing_images_client import BingImagesClient
    BING_IMAGES_AVAILABLE = True
except ImportError:
    BING_IMAGES_AVAILABLE = False
    BingImagesClient = None

# Compatibilidad legacy con código que aún usa el nombre antiguo
GOOGLE_IMAGES_AVAILABLE = BING_IMAGES_AVAILABLE
GoogleImagesClient = BingImagesClient

try:
    from auto_video_generator_v2 import ResourceDownloader
    PEXELS_AVAILABLE = True
except ImportError:
    PEXELS_AVAILABLE = False
    ResourceDownloader = None

try:
    from internet_archive_client import InternetArchiveClient
    INTERNET_ARCHIVE_AVAILABLE = True
except ImportError:
    INTERNET_ARCHIVE_AVAILABLE = False
    InternetArchiveClient = None

# Rate limiter global para evitar errores 429
class RateLimiter:
    def __init__(self, max_requests_per_minute=300):
        self.max_requests = max_requests_per_minute
        self.requests = []
        self.lock = threading.Lock()
        self.max_wait_time = 30  # MÃ¡ximo 30 segundos de espera
    
    def wait_if_needed(self):
        """Esperar si se alcanzÃ³ el lÃ­mite de solicitudes"""
        start_time = time.time()
        
        while True:
            with self.lock:
                now = time.time()
                
                # Si hemos esperado demasiado, salir para evitar bloqueo
                if now - start_time > self.max_wait_time:
                    print(f"âš ï¸ Rate limit timeout despuÃ©s de {self.max_wait_time}s, continuando...")
                    self.requests = []  # Resetear para evitar bloqueo infinito
                    self.requests.append(now)
                    return
                
                # Eliminar solicitudes antiguas (mÃ¡s de 1 minuto)
                self.requests = [req_time for req_time in self.requests if now - req_time < 60]
                
                if len(self.requests) < self.max_requests:
                    self.requests.append(now)
                    return
                
                # Calcular tiempo de espera
                oldest_request = min(self.requests)
                wait_time = min(60 - (now - oldest_request) + 0.5, 5.0) # MÃ¡ximo 5s de espera
            
            # Esperar fuera del lock
            if wait_time > 0:
                print(f"DEBUG: Rate limit alcanzado, esperando {wait_time:.1f} segundos...")
                time.sleep(wait_time)

# Rate limiter global
rate_limiter = RateLimiter(max_requests_per_minute=300)

try:
    from youtube_video_client import YouTubeVideoClient, YT_DLP_AVAILABLE
    YOUTUBE_VIDEO_AVAILABLE = True
except ImportError:
    YOUTUBE_VIDEO_AVAILABLE = False
    YouTubeVideoClient = None
    YT_DLP_AVAILABLE = False

class VideoFrameExtractorWorker(QThread):
    """Worker thread para descargar un video y extraer frames para el timeline"""
    finished = pyqtSignal(str, list)  # Emite (video_path, list of QPixmap frames)
    error = pyqtSignal(str)  # Emite mensaje de error
    progress = pyqtSignal(str)  # Emite mensajes de progreso

    def __init__(self, video_url, video_source='youtube', num_frames=15):
        super().__init__()
        self.video_url = video_url
        self.video_source = video_source  # 'youtube', 'wikimedia', 'internet_archive'
        self.num_frames = num_frames
        self.temp_video_path = None
        self.preview_timeout_primary = 35
        self.preview_timeout_fallback = 90

    def run(self):
        """Descarga el video y extrae frames"""
        try:
            import tempfile
            import sys
            import subprocess
            from pathlib import Path

            # Crear archivo temporal para el video
            temp_dir = Path(tempfile.gettempdir()) / "video_optimizer_frames"
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Nombre Ãºnico basado en hash de URL
            video_hash = hash(self.video_url) % 1000000
            video_prefix = f"temp_video_{video_hash}"
            self.temp_video_path = str(temp_dir / f"{video_prefix}.mp4")

            def _pick_downloaded_video() -> str:
                candidates = []
                for p in temp_dir.glob(f"{video_prefix}.*"):
                    if not p.is_file():
                        continue
                    if p.suffix.lower() in ['.part', '.ytdl', '.tmp']:
                        continue
                    try:
                        size = p.stat().st_size
                    except Exception:
                        size = 0
                    if size > 0:
                        candidates.append((size, p))
                if not candidates:
                    return ""
                candidates.sort(key=lambda x: x[0], reverse=True)
                return str(candidates[0][1])

            # Verificar cache en cualquier extension
            cached_video = _pick_downloaded_video()
            if cached_video:
                self.temp_video_path = cached_video
                self.progress.emit("Video en cache, extrayendo frames...")
            else:
                self.progress.emit("Descargando video para preview...")

                if self.video_source == 'youtube':
                    # Verificar si yt-dlp estÃ¡ disponible
                    try:
                        from youtube_video_client import YT_DLP_AVAILABLE
                    except ImportError:
                        YT_DLP_AVAILABLE = False
                    
                    if not YT_DLP_AVAILABLE:
                        # Verificar directamente si yt-dlp estÃ¡ instalado
                        try:
                            check_result = subprocess.run(
                                [sys.executable, "-m", "yt_dlp", "--version"],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            yt_dlp_available = check_result.returncode == 0
                        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                            yt_dlp_available = False
                    else:
                        yt_dlp_available = YT_DLP_AVAILABLE
                    
                    if not yt_dlp_available:
                        self.error.emit(
                            "yt-dlp no estÃ¡ instalado.\n\n"
                            "Para descargar videos de YouTube, necesitas instalar yt-dlp:\n"
                            "pip install yt-dlp"
                        )
                        return
                    
                    # Limpiar posibles residuos temporales
                    for stale in temp_dir.glob(f"{video_prefix}.*"):
                        try:
                            if stale.is_file() and stale.suffix.lower() in ['.part', '.ytdl', '.tmp']:
                                stale.unlink(missing_ok=True)
                            elif stale.is_file() and stale.stat().st_size == 0:
                                stale.unlink(missing_ok=True)
                        except Exception:
                            pass

                    # Usar plantilla por extension para no asumir .mp4 fijo
                    output_template = str(temp_dir / f"{video_prefix}.%(ext)s")

                    # Usar yt-dlp para YouTube (calidad baja, video completo para permitir navegación)
                    cmd = [
                        sys.executable, "-m", "yt_dlp",
                        "-f", "worst[height<=240][ext=mp4]/worst[height<=240]/worst[ext=mp4]/worst",
                        "-o", output_template,
                        "--no-playlist",
                        "--no-warnings",
                        "--socket-timeout", "20",
                        "--retries", "0",
                        "--fragment-retries", "0",
                        "--no-part",
                        "--extractor-args", "youtube:player_client=android,web",
                        self.video_url
                    ]
                    result = self._run_preview_subprocess(cmd, self.preview_timeout_primary)
                    if result is None:
                        self.progress.emit("Timeout en intento 1 de preview, probando alternativo...")
                        result = subprocess.CompletedProcess(cmd, 124, "", "Timeout en intento primario de preview")

                    downloaded_video = _pick_downloaded_video()
                    file_exists = bool(downloaded_video)
                    file_size = os.path.getsize(downloaded_video) if file_exists else 0
                    if file_exists:
                        self.temp_video_path = downloaded_video
                    
                    if result.returncode != 0 or not file_exists or file_size == 0:
                        combined_output = f"{result.stderr or ''}\n{result.stdout or ''}".lower()
                        if ("javascript runtime" in combined_output
                                or "no supported javascript runtime" in combined_output
                                or "--js-runtimes" in combined_output):
                            self.error.emit(
                                "Preview no disponible para este video (YouTube requiere runtime JS).\n"
                                "Puedes seleccionar el video igualmente para descargarlo."
                            )
                            return
                        # Mostrar error detallado de yt-dlp
                        if result.stderr:
                            error_detail = result.stderr[:800]  # Aumentar lÃ­mite
                            self.progress.emit(f"yt-dlp stderr: {error_detail}")
                        if result.stdout:
                            stdout_detail = result.stdout[:800]  # Mostrar tambiÃ©n stdout
                            self.progress.emit(f"yt-dlp stdout: {stdout_detail}")
                        
                        # Segundo intento con formato mÃ¡s simple
                        self.progress.emit("Reintentando preview con formato alternativo...")
                        cmd_alt = [
                            sys.executable, "-m", "yt_dlp",
                            "-f", "best[height<=360]/worst",
                            "-o", output_template,
                            "--no-playlist",
                            "--no-warnings",
                            "--socket-timeout", "20",
                            "--retries", "1",
                            "--fragment-retries", "1",
                            "--no-part",
                            "--extractor-args", "youtube:player_client=android,web",
                            self.video_url
                        ]
                        result = self._run_preview_subprocess(cmd_alt, self.preview_timeout_fallback)
                        if result is None:
                            self.progress.emit("Timeout en intento 2 de preview, usando fallback...")
                            result = subprocess.CompletedProcess(cmd_alt, 124, "", "Timeout en intento alternativo de preview")

                        # Verificar resultado del intento simple
                        downloaded_video_simple = _pick_downloaded_video()
                        file_exists_simple = bool(downloaded_video_simple)
                        file_size_simple = os.path.getsize(downloaded_video_simple) if file_exists_simple else 0
                        if file_exists_simple:
                            self.temp_video_path = downloaded_video_simple
                        
                        if result.returncode != 0 or not file_exists_simple or file_size_simple == 0:
                            # Tercer intento: usar descargador mejorado del proyecto
                            self.progress.emit("Intentando fallback de preview...")
                            fallback_output = str(temp_dir / f"{video_prefix}_fallback.mp4")
                            fallback_video = self._try_preview_with_fixed_downloader(fallback_output)
                            if fallback_video:
                                self.temp_video_path = fallback_video
                                file_exists_simple = True
                                file_size_simple = os.path.getsize(fallback_video)

                        if result.returncode != 0 or not file_exists_simple or file_size_simple == 0:
                            # Mostrar error completo del segundo intento
                            if result.stderr:
                                error_detail = result.stderr[:800]
                                self.progress.emit(f"yt-dlp stderr (2do intento): {error_detail}")
                            if result.stdout:
                                stdout_detail = result.stdout[:800]
                                self.progress.emit(f"yt-dlp stdout (2do intento): {stdout_detail}")
                            
                            error_msg = result.stderr.strip() if result.stderr else result.stdout.strip() if result.stdout else "Error desconocido"
                            
                            # Verificar si el error es porque yt-dlp no estÃ¡ instalado
                            if "No module named yt_dlp" in error_msg or "No module named 'yt_dlp'" in error_msg:
                                error_msg = (
                                    "yt-dlp no estÃ¡ instalado.\n\n"
                                    "Para descargar videos de YouTube, necesitas instalar yt-dlp:\n"
                                    "pip install yt-dlp"
                                )
                            else:
                                # Agregar informaciÃ³n sobre archivo vacÃ­o
                                if file_exists_simple and file_size_simple == 0:
                                    error_msg += "\n\nArchivo vacÃ­o - posibles causas: video bloqueado, requiere autenticaciÃ³n, o cambios en YouTube"
                            
                            self.error.emit(f"No se pudo descargar el video: {error_msg}")
                            return

                elif self.video_source == 'internet_archive':
                    # Para Internet Archive usar preview remoto directamente.
                    # Evita descargar archivos enormes solo para ver el timeline.
                    self.progress.emit("Cargando preview remoto...")
                    self.temp_video_path = self.video_url

                elif self.video_source == 'wikimedia':
                    # Descargar directamente con requests
                    import requests
                    self.progress.emit("Descargando video...")
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    response = requests.get(self.video_url, headers=headers, stream=True, timeout=120)
                    if response.status_code == 200:
                        with open(self.temp_video_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        # Verificar que se descargÃ³ correctamente
                        if os.path.getsize(self.temp_video_path) == 0:
                            os.remove(self.temp_video_path)
                            self.error.emit("El video descargado estÃ¡ vacÃ­o")
                            return
                    else:
                        self.error.emit(f"Error descargando video: HTTP {response.status_code}")
                        return

            is_remote_source = str(self.temp_video_path or '').startswith('http://') or str(self.temp_video_path or '').startswith('https://')
            if not self.temp_video_path or ((not is_remote_source) and (not os.path.exists(self.temp_video_path) or os.path.getsize(self.temp_video_path) == 0)):
                self.error.emit("No se pudo preparar el video para preview")
                return

            # Extraer frames del video
            self.progress.emit("Extrayendo frames...")
            frames = self._extract_frames()

            if frames:
                self.finished.emit(self.temp_video_path, frames)
            else:
                self.error.emit("No se pudieron extraer frames del video")

        except subprocess.TimeoutExpired:
            self.error.emit("Timeout descargando preview de video.")
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")

    def _run_preview_subprocess(self, cmd, timeout_seconds):
        """Ejecuta subprocess para preview sin abortar el worker en timeout."""
        import subprocess
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
        except subprocess.TimeoutExpired:
            return None

    def _try_preview_with_fixed_downloader(self, output_path: str) -> str:
        """Fallback de preview usando el downloader mejorado del proyecto."""
        try:
            from youtube_downloader_fixed import FixedYouTubeDownloader
        except Exception as e:
            self.progress.emit(f"Fallback no disponible: {e}")
            return ""

        try:
            downloader = FixedYouTubeDownloader()
            video_info = {
                "url": self.video_url,
                "title": "YouTube Preview"
            }
            result = downloader.download_video(video_info, output_path, max_attempts=1)
            if result and os.path.exists(result) and os.path.getsize(result) > 0:
                return result
        except Exception as e:
            self.progress.emit(f"Fallback preview fallÃ³: {e}")

        return ""

    def _extract_frames(self):
        """Extrae frames del video descargado (moviepy o ffmpeg fallback)"""
        frames = self._extract_frames_moviepy()
        if not frames:
            frames = self._extract_frames_ffmpeg()
        return frames

    def _extract_frames_moviepy(self):
        """Extrae frames usando moviepy"""
        frames = []
        try:
            from moviepy.editor import VideoFileClip
            from PIL import Image
            import io

            clip = VideoFileClip(self.temp_video_path)
            duration = clip.duration

            if duration <= 0:
                clip.close()
                return frames

            frame_times = [i * duration / self.num_frames for i in range(self.num_frames)]

            for i, t in enumerate(frame_times):
                try:
                    self.progress.emit(f"Extrayendo frame {i+1}/{self.num_frames}...")
                    frame = clip.get_frame(t)

                    pil_image = Image.fromarray(frame.astype('uint8'), 'RGB')

                    aspect_ratio = pil_image.width / pil_image.height
                    new_height = 90
                    new_width = int(new_height * aspect_ratio)
                    pil_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

                    buffer = io.BytesIO()
                    pil_image.save(buffer, format='PNG')
                    buffer.seek(0)

                    pixmap = QPixmap()
                    pixmap.loadFromData(buffer.getvalue())
                    frames.append(pixmap)

                except Exception as e:
                    print(f"️ Error extrayendo frame en t={t}: {e}")
                    continue

            clip.close()

        except ImportError:
            print("ℹ️ moviepy no disponible, usando ffmpeg para extraer frames")
        except Exception as e:
            print(f" Error extrayendo frames con moviepy: {e}")

        return frames

    def _extract_frames_ffmpeg(self):
        """Extrae frames usando ffmpeg (fallback cuando moviepy no esta)"""
        import subprocess
        import tempfile
        import shutil
        frames = []

        video_path = self.temp_video_path
        is_remote = str(video_path or '').startswith(('http://', 'https://'))

        # Obtener duracion con ffprobe
        try:
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            duration = float(result.stdout.strip())
        except Exception as e:
            print(f"️ ffprobe no pudo obtener duracion: {e}")
            duration = 10.0

        if duration <= 0:
            return frames

        frame_times = [i * duration / self.num_frames for i in range(self.num_frames)]

        # Crear directorio temporal para frames
        temp_frames_dir = tempfile.mkdtemp(prefix="vo_frames_")

        try:
            for i, t in enumerate(frame_times):
                try:
                    self.progress.emit(f"Extrayendo frame {i+1}/{self.num_frames} (ffmpeg)...")
                    frame_path = os.path.join(temp_frames_dir, f"frame_{i:03d}.png")

                    cmd = [
                        "ffmpeg", "-y",
                        "-ss", f"{t:.3f}",
                        "-i", video_path,
                        "-vframes", "1",
                        "-vf", "scale=-1:90",
                        "-q:v", "2",
                        frame_path
                    ]
                    subprocess.run(cmd, capture_output=True, timeout=15)

                    if os.path.exists(frame_path) and os.path.getsize(frame_path) > 0:
                        pixmap = QPixmap(frame_path)
                        if not pixmap.isNull():
                            frames.append(pixmap)

                except Exception as e:
                    print(f"️ Error extrayendo frame {i} con ffmpeg: {e}")
                    continue

        finally:
            try:
                shutil.rmtree(temp_frames_dir, ignore_errors=True)
            except Exception:
                pass

        if frames:
            print(f" {len(frames)} frames extraidos con ffmpeg")
        else:
            print(" No se pudieron extraer frames con ffmpeg")

        return frames



class AIImageRegenerationWorker(QThread):
    """Worker batch para regenerar imagenes con el proveedor activo."""
    finished = pyqtSignal(int, str)  # Emite (segment_index, image_path) cuando termina
    error = pyqtSignal(str)  # Emite mensaje de error
    progress = pyqtSignal(str)  # Emite mensajes de progreso

    def __init__(self, segment_index, visual_prompt, filename, generation_config=None):
        super().__init__()
        self.segment_index = segment_index
        self.visual_prompt = visual_prompt
        self.filename = filename
        self.generation_config = generation_config.copy() if isinstance(generation_config, dict) else {}
        self.generated_image_source = ""

    def _resolve_dimensions(self):
        platform = str(self.generation_config.get("platform") or "youtube").strip().lower()
        if any(token in platform for token in ("9:16", "vertical", "short", "reel", "tiktok")):
            return 1024, 1820
        if "1:1" in platform or "square" in platform:
            return 1024, 1024
        return 1820, 1024

    def _fix_prompt_orientation(self, prompt: str) -> str:
        """Strip vertical/portrait keywords and inject 16:9 guidance for horizontal platforms."""
        import re
        width, height = self._resolve_dimensions()
        if width <= height:
            return prompt  # vertical or square: keep as-is

        portrait_patterns = [
            r",?\s*vertical\s+9:16\s+portrait\s+composition\s+(?:for\s+youtube\s+shorts\s+)?",
            r",?\s*vertical\s+portrait\s+composition(?:\s+optimized\s+for\s+mobile[^,]*)?",
            r",?\s*portrait\s+orientation",
            r",?\s*mobile[- ]safe\s+viewing",
            r",?\s*lower[- ]third\s+negative\s+space(?:\s+for\s+subtitles)?",
            r",?\s*subject\s+centered\s+in\s+the\s+middle\s+safe\s+area",
            r",?\s*no\s+important\s+details\s+at\s+the\s+edges",
            r"\bvertical\s+portrait\b",
            r"\b9:16\b",
        ]
        for pat in portrait_patterns:
            prompt = re.sub(pat, "", prompt, flags=re.IGNORECASE)

        prompt = re.sub(r",\s*,+", ", ", prompt)
        prompt = re.sub(r"^\s*,\s*", "", prompt)
        prompt = re.sub(r"\s+", " ", prompt).strip()

        horizontal_markers = ("16:9", "wide shot", "horizontal composition",
                              "landscape framing", "wide angle", "rule of thirds")
        if not any(m in prompt.lower() for m in horizontal_markers):
            prompt = f"{prompt}, cinematic 16:9 horizontal framing, wide establishing composition"

        return prompt

    def _build_output_path(self, images_dir: str, extension: str):
        import hashlib
        timestamp = int(time.time())
        hash_suffix = hashlib.md5(
            f"{self.segment_index}_{self.visual_prompt}_{timestamp}".encode()
        ).hexdigest()[:8]
        safe_filename = self.filename.replace(' ', '_').replace('/', '_').replace('\\', '_')
        return images_dir / f"{safe_filename}_regenerated_{timestamp}_{hash_suffix}{extension}"

    def _download_image(self, image_url):
        response = requests.get(image_url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code != 200:
            self.error.emit(f"Error descargando imagen: Status {response.status_code}")
            return None
        return response.content

    def run(self):
        """Ejecuta la generacion de imagen segun el proveedor configurado."""
        try:
            from video_config import VideoConfig
            from recraft_client import RecraftClient
            from google_ai_image_client import GoogleAiImageClient

            provider = str(self.generation_config.get("image_provider") or "recraft").strip().lower()
            style = str(self.generation_config.get("style") or "").strip() or None
            width, height = self._resolve_dimensions()

            visual_prompt = self._fix_prompt_orientation(self.visual_prompt)

            VideoConfig.setup_directories()
            images_dir = VideoConfig.TEMP_DIR / "generated_media"
            images_dir.mkdir(exist_ok=True, parents=True)

            self.progress.emit(f"Generando imagen con proveedor '{provider}'...")
            self.progress.emit(f"   Prompt: {visual_prompt[:80]}...")

            if provider == "manual":
                self.error.emit("El proveedor actual esta en modo manual.")
                return

                image_path = self._build_output_path(images_dir, ".jpg")
                self.generated_image_source = "fal_ai"

            elif provider == "google_ai":
                client = GoogleAiImageClient(log_callback=self.progress.emit)
                if not getattr(client, "client_available", False):
                    self.error.emit("Google AI no esta disponible. Configura GEMINI_API_KEY o GOOGLE_API_KEY.")
                    return
                image_bytes = client.generate_image(
                    prompt=visual_prompt,
                    width=width,
                    height=height,
                    style=style,
                )
                if not image_bytes:
                    self.error.emit(client.last_error or "Google AI no pudo generar la imagen.")
                    return
                image_path = self._build_output_path(images_dir, ".png")
                self.generated_image_source = "google_ai"

            else:
                client = RecraftClient(log_callback=self.progress.emit)
                if not getattr(client, "api_key", None):
                    self.error.emit("Recraft AI no esta disponible. Configura RECRAFT_API_KEY.")
                    return
                result = client.generate_image(
                    prompt=visual_prompt,
                    style=style or "Photorealism",
                    width=width,
                    height=height,
                )
                if not result or not result.get("url"):
                    self.error.emit("Recraft AI no pudo generar la imagen.")
                    return
                image_bytes = self._download_image(result["url"])
                if not image_bytes:
                    return
                image_path = self._build_output_path(images_dir, ".jpg")
                self.generated_image_source = "recraft_ai"

            with open(image_path, 'wb') as f:
                f.write(image_bytes)

            self.progress.emit(f"Imagen guardada: {image_path.name}")
            self.finished.emit(self.segment_index, str(image_path))

        except Exception as e:
            import traceback
            error_msg = f"Error generando imagen: {str(e)}\n\n{traceback.format_exc()}"
            self.error.emit(error_msg)


class ContextualAIImageRegenerationWorker(QThread):
    """Regenera una imagen IA usando la pipeline central y contexto narrativo local."""
    finished = pyqtSignal(int, dict)  # Emite (segment_index, segment_data_actualizado)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, segment_index, segment_data, generation_config):
        super().__init__()
        self.segment_index = segment_index
        self.segment_data = segment_data.copy() if isinstance(segment_data, dict) else {}
        self.generation_config = generation_config.copy() if isinstance(generation_config, dict) else {}

    def _log(self, message):
        self.progress.emit(str(message))

    def run(self):
        try:
            from pathlib import Path

            from video_config import VideoConfig
            from gemini_ai_client import GeminiAiClient
            from prompt_processor import PromptProcessor
            from image_generation_manager import ImageGenerationManager
            from recraft_client import RecraftClient
            from google_ai_image_client import GoogleAiImageClient

            platform = str(self.generation_config.get("platform") or "youtube").strip().lower()
            style = str(self.generation_config.get("style") or "Realistic Image").strip()
            image_provider = str(self.generation_config.get("image_provider") or "auto").strip().lower()
            refresh_prompt = bool(self.generation_config.get("refresh_prompt", True))
            topic = self.generation_config.get("topic")
            category = self.generation_config.get("category") or "General"
            full_script = self.generation_config.get("full_script")
            research_context = self.generation_config.get("research_context")
            narrative_context = self.generation_config.get("narrative_context")

            if image_provider == "manual":
                self.error.emit("El proveedor actual esta en modo manual y no permite regeneracion IA automatica.")
                return

            VideoConfig.setup_directories()
            generated_media_dir = VideoConfig.TEMP_DIR / "generated_media"
            generated_media_dir.mkdir(exist_ok=True, parents=True)

            self._log("Preparando pipeline central de regeneracion IA...")

            gemini_client = GeminiAiClient()
            prompt_processor = PromptProcessor(
                log_callback=self._log,
                gemini_client=gemini_client
            )
            # FAL.AI (opcional, se salta si falta FAL_KEY o SDK)
            fal_image_client = None
            try:
                from fal_ai_client import FalAiImageClient, is_fal_configured
                if is_fal_configured():
                    fal_image_client = FalAiImageClient(log_callback=self._log)
            except Exception as exc:
                self._log(f"[FAL] No disponible para regeneración individual: {exc}")

            image_manager = ImageGenerationManager(
                log_callback=self._log,
                generated_media_dir=generated_media_dir,
                recraft_client=RecraftClient(log_callback=self._log),
                google_ai_image_client=GoogleAiImageClient(log_callback=self._log),
                prompt_processor=prompt_processor,
                fal_image_client=fal_image_client,
            )

            segment = self.segment_data.copy()
            segment_text = str(
                segment.get("text") or segment.get("narration_text") or segment.get("narration") or ""
            ).strip()

            if refresh_prompt and segment_text and gemini_client and getattr(gemini_client, "claude_client", None):
                self._log("Regenerando prompt visual con contexto narrativo actual...")
                prompt_data = gemini_client.generate_prompts_for_segment(
                    segment_text,
                    category,
                    style,
                    topic=topic,
                    full_script=full_script,
                    research_context=research_context,
                    narrative_context=narrative_context
                )
                if isinstance(prompt_data, dict):
                    for key in ("visual_prompt", "sfx_tag", "overlay_tag"):
                        value = prompt_data.get(key)
                        if value:
                            segment[key] = value

            visual_prompt = str(segment.get("visual_prompt") or "").strip()
            if not visual_prompt:
                self.error.emit("El segmento no tiene prompt visual util para regenerar la imagen.")
                return

            # Forzar regeneracion para este segmento sin tocar archivos/estado previo.
            segment.pop("image_path", None)
            segment.pop("image_source", None)
            segment.pop("video_path", None)
            segment.pop("video_source", None)
            segment.pop("image_deleted", None)

            assigned_filename = str(
                segment.get("assigned_filename") or f"segment_{self.segment_index + 1:03d}"
            ).strip()
            if not assigned_filename:
                assigned_filename = f"segment_{self.segment_index + 1:03d}"
            segment["assigned_filename"] = assigned_filename

            storyboard_data = {
                "topic": topic or "",
                "category": category,
                "script": full_script or "",
                "segments": [segment],
            }

            self._log("Generando imagen IA con la pipeline central...")
            result = image_manager.generate_all_images_for_storyboard(
                storyboard_data=storyboard_data,
                platform=platform,
                use_wikimedia=False,
                disable_wikimedia=True,
                use_real_images=False,
                use_google_images=False,
                enable_real_images_mix=False,
                test_mode=False,
                image_provider=image_provider,
                images_per_segment_ratio=1.0,
                interleave_images=False,
                style=style,
                regenerate_prompts=False
            )

            segments = result.get("segments", []) if isinstance(result, dict) else []
            if not segments:
                self.error.emit("La pipeline no devolvio segmentos tras regenerar la imagen.")
                return

            updated_segment = segments[0].copy()
            image_path = str(updated_segment.get("image_path") or "").strip()
            if not image_path:
                self.error.emit("No se pudo generar una imagen nueva para el segmento.")
                return

            image_source = str(updated_segment.get("image_source") or "").strip()
            if not image_source:
                provider_to_source = {
                    "fal": "fal_ai",
                    "fal_ai": "fal_ai",
                    "google_ai": "google_ai",
                    "recraft": "recraft_ai",
                    "auto": "recraft_ai",
                }
                updated_segment["image_source"] = provider_to_source.get(image_provider, "recraft_ai")

            self.finished.emit(self.segment_index, updated_segment)

        except Exception as e:
            import traceback
            error_msg = f"Error regenerando imagen con pipeline central: {str(e)}\n\n{traceback.format_exc()}"
            self.error.emit(error_msg)


class WikimediaSearchWorker(QThread):
    """Worker thread para buscar imÃ¡genes en Wikimedia de forma asÃ­ncrona"""
    finished = pyqtSignal(list)  # Emite lista de imÃ¡genes encontradas
    error = pyqtSignal(str)  # Emite mensaje de error
    progress = pyqtSignal(str)  # Emite mensajes de progreso
    
    def __init__(self, query, narration_text="", require_attribution=False):
        super().__init__()
        self.query = query
        self.narration_text = narration_text
        self.require_attribution = require_attribution
    
    def run(self):
        """Ejecuta la bÃºsqueda"""
        try:
            if not WIKIMEDIA_AVAILABLE:
                self.error.emit("Wikimedia client no disponible")
                return
            
            self.progress.emit(f"Buscando imÃ¡genes para: {self.query}...")
            
            # Aplicar rate limiting antes de la bÃºsqueda
            rate_limiter.wait_if_needed()
            
            # Crear cliente de Wikimedia
            wikimedia_client = WikimediaClient()
            
            # Buscar imÃ¡genes (Wikimedia ya es libre de derechos por defecto)
            images = wikimedia_client.search_images(
                query=self.query,  # BÃºsqueda natural sin filtros adicionales
                limit=24,  # Buscar suficiente sin saturar previews
                narration_text=self.narration_text
            )
            
            # Filtrar y priorizar imÃ¡genes sin atribuciÃ³n
            filtered_images = []
            no_attribution_images = []
            attribution_images = []
            seen_title_signatures = set()
            
            for img in images:
                title_value = str(img.get('title', '')).strip().lower()
                title_signature = ''.join(
                    ch for ch in title_value if ch.isalnum() or ch.isspace()
                ).strip()[:80]

                # Firma reducida para deduplicar variantes casi idénticas
                title_compact = ' '.join(title_signature.split())
                title_core = ' '.join(title_compact.split()[:6]).strip()
                dedup_key = title_core or title_compact or title_signature

                if dedup_key and dedup_key in seen_title_signatures:
                    continue
                if dedup_key:
                    seen_title_signatures.add(dedup_key)

                # Analizar licencia para determinar si requiere atribuciÃ³n
                license_info = img.get('license', '').lower()
                title = img.get('title', '').lower()
                
                # Licencias que NO requieren atribuciÃ³n
                no_attribution_licenses = [
                    'public domain', 'pd', 'cc0', 'cc-zero', 'creative commons zero',
                    'public domain mark', 'pdmark', 'no rights reserved',
                    'free use', 'unrestricted', 'copyright free'
                ]
                
                # Licencias que SÃ requieren atribuciÃ³n
                attribution_licenses = [
                    'cc by', 'cc by-sa', 'cc by-nc', 'cc by-nd', 'cc by-nc-sa', 'cc by-nc-nd',
                    'creative commons attribution', 'creative commons share alike',
                    'creative commons non-commercial', 'attribution required'
                ]
                
                requires_attribution = False
                
                # Verificar si requiere atribuciÃ³n
                for attr_license in attribution_licenses:
                    if attr_license in license_info or attr_license in title:
                        requires_attribution = True
                        break
                
                # Verificar si es libre de atribuciÃ³n
                is_free = False
                for free_license in no_attribution_licenses:
                    if free_license in license_info or free_license in title:
                        is_free = True
                        break
                
                # Si no hay informaciÃ³n clara, asumir que requiere atribuciÃ³n (mÃ¡s seguro)
                if not requires_attribution and not is_free and not license_info:
                    requires_attribution = True
                
                # Clasificar la imagen
                if self.require_attribution:
                    # Si el usuario pidiÃ³ con atribuciÃ³n, incluir todo
                    if requires_attribution or is_free or not license_info:
                        img['license_note'] = 'Creative Commons con atribuciÃ³n (Wikimedia)'
                        img['requires_attribution'] = True
                        attribution_images.append(img)
                else:
                    # Si el usuario pidiÃ³ sin atribuciÃ³n, priorizar las libres
                    if is_free or not requires_attribution:
                        img['license_note'] = 'Dominio PÃºblico / Creative Commons (Wikimedia)'
                        img['requires_attribution'] = False
                        no_attribution_images.append(img)
                    elif requires_attribution and len(no_attribution_images) < 15:
                        # Incluir algunas con atribuciÃ³n si hay pocas libres
                        img['license_note'] = 'Creative Commons con atribuciÃ³n (Wikimedia)'
                        img['requires_attribution'] = True
                        attribution_images.append(img)
                
                img['source'] = 'Wikimedia Commons'
            
            # Combinar resultados: primero las sin atribuciÃ³n, luego con atribuciÃ³n
            if not self.require_attribution:
                filtered_images = no_attribution_images + attribution_images[:5]  # MÃ¡ximo 5 con atribuciÃ³n
            else:
                filtered_images = attribution_images
            
            # Limitar resultados finales para evitar ráfagas de previews/HTTP 429
            images = filtered_images[:12]
            
            if images:
                attribution_text = "con atribuciÃ³n" if self.require_attribution else "libres de derechos"
                self.progress.emit(f"âœ… Encontradas {len(images)} imÃ¡genes {attribution_text}")
                self.finished.emit(images)
            else:
                self.error.emit(f"No se encontraron imÃ¡genes para: {self.query}")
        
        except Exception as e:
            self.error.emit(f"Error buscando imÃ¡genes: {str(e)}")


class BingImagesSearchWorker(QThread):
    """Worker thread para buscar imagenes (Openverse gratis, compat legacy)."""
    finished = pyqtSignal(list)  # Emite lista de imÃ¡genes encontradas
    error = pyqtSignal(str)  # Emite mensaje de error
    progress = pyqtSignal(str)  # Emite mensajes de progreso
    
    def __init__(self, query, narration_text="", require_attribution=False):
        super().__init__()
        self.query = query
        self.narration_text = narration_text
        self.require_attribution = require_attribution
    
    def run(self):
        """Ejecuta la bÃºsqueda"""
        try:
            if not BING_IMAGES_AVAILABLE:
                self.error.emit("Cliente de imagenes no disponible")
                return
            
            # Validar query
            if not self.query or not self.query.strip():
                self.error.emit("La bÃºsqueda estÃ¡ vacÃ­a")
                return
            
            self.progress.emit(f"Buscando imagenes reales para: {self.query}...")
            
            # Crear cliente de busqueda de imagenes
            try:
                bing_images_client = BingImagesClient()
            except Exception as e:
                self.error.emit(f"Error creando cliente de imagenes: {str(e)}")
                return
            
            # Buscar imÃ¡genes con filtros de copyright
            try:
                if self.require_attribution:
                    # BÃºsqueda con atribuciÃ³n - mÃ¡s opciones disponibles
                    copyright_query = f"{self.query}"
                    license_type = "Con atribuciÃ³n (Creative Commons)"
                else:
                    # BÃºsqueda libre de derechos - mÃ¡s natural, menos restrictivo
                    copyright_query = f"{self.query}"
                    license_type = "Libre de derechos (verificar en fuente)"
                
                images = bing_images_client.search_images(
                    query=copyright_query,
                    limit=24,  # Limitar para reducir rafagas de previews y errores 429
                    narration_text=self.narration_text if self.narration_text else ""
                )
                if not images:
                    detailed_error = getattr(bing_images_client, 'last_error', '')
                    if detailed_error:
                        self.error.emit(f"Busqueda de imagenes: {detailed_error}")
                    else:
                        self.error.emit(f"No se encontraron imagenes para: {self.query}")
                    return
                
                # Filtrar y priorizar resultados segÃºn tipo de licencia
                no_attribution_images = []
                attribution_images = []
                filtered_images = []
                
                for img in images:
                    # Verificar si la imagen tiene informaciÃ³n de licencia
                    license_info = img.get('license', '').lower()
                    rights_info = img.get('rights', '').lower()
                    title = img.get('title', '').lower()
                    
                    # Licencias que NO requieren atribuciÃ³n
                    no_attribution_licenses = [
                        'public domain', 'pd', 'cc0', 'cc-zero', 'creative commons zero',
                        'public domain mark', 'pdmark', 'no rights reserved',
                        'free use', 'unrestricted', 'copyright free', 'no attribution'
                    ]
                    
                    # Licencias que SÃ requieren atribuciÃ³n
                    attribution_licenses = [
                        'cc by', 'cc by-sa', 'cc by-nc', 'cc by-nd', 'cc by-nc-sa', 'cc by-nc-nd',
                        'creative commons attribution', 'creative commons share alike',
                        'creative commons non-commercial', 'attribution required', 'credit required'
                    ]
                    
                    requires_attribution = False
                    is_free = False
                    
                    # Verificar si requiere atribuciÃ³n
                    for attr_license in attribution_licenses:
                        if (attr_license in license_info or 
                            attr_license in rights_info or 
                            attr_license in title):
                            requires_attribution = True
                            break
                    
                    # Verificar si es libre de atribuciÃ³n
                    for free_license in no_attribution_licenses:
                        if (free_license in license_info or 
                            free_license in rights_info or 
                            free_license in title):
                            is_free = True
                            break
                    
                    # Si no hay informaciÃ³n clara, asumir que requiere atribuciÃ³n (mÃ¡s seguro)
                    if not requires_attribution and not is_free and not license_info:
                        requires_attribution = True
                    
                    # Clasificar la imagen
                    if self.require_attribution:
                        # Si el usuario pidiÃ³ con atribuciÃ³n, incluir contenido que requiere atribuciÃ³n
                        if requires_attribution or is_free or not license_info:
                            img['license_note'] = license_type
                            img['requires_attribution'] = True
                            attribution_images.append(img)
                    else:
                        # Si el usuario pidiÃ³ sin atribuciÃ³n, priorizar las libres
                        if is_free or not requires_attribution:
                            img['license_note'] = license_type
                            img['requires_attribution'] = False
                            no_attribution_images.append(img)
                        elif requires_attribution and len(no_attribution_images) < 15:
                            # Incluir algunas con atribuciÃ³n si hay pocas libres
                            img['license_note'] = 'Con atribuciÃ³n (verificar en fuente)'
                            img['requires_attribution'] = True
                            attribution_images.append(img)
                
                # Combinar resultados: primero las sin atribuciÃ³n, luego con atribuciÃ³n
                if not self.require_attribution:
                    filtered_images = no_attribution_images + attribution_images[:5]  # MÃ¡ximo 5 con atribuciÃ³n
                else:
                    filtered_images = attribution_images
                
                images = filtered_images[:12]  # Limitar para evitar sobrecarga de previews
                
            except Exception as e:
                self.error.emit(f"Error en la busqueda de imagenes: {str(e)}")
                return
            
            # Validar resultados
            if images and isinstance(images, list) and len(images) > 0:
                self.progress.emit(f"âœ… Encontradas {len(images)} imÃ¡genes")
                self.finished.emit(images)
            else:
                self.error.emit(f"No se encontraron imÃ¡genes para: {self.query}")
        
        except Exception as e:
            import traceback
            error_msg = f"Error buscando imÃ¡genes: {str(e)}"
            print(f"âŒ Error en ImageSearchWorker: {error_msg}")
            print(traceback.format_exc())
            self.error.emit(error_msg)


# Compatibilidad con imports antiguos
class GoogleImagesSearchWorker(BingImagesSearchWorker):
    """Alias legacy: Google Images fue retirado y ahora usa Openverse."""
    pass


class PexelsVideoSearchWorker(QThread):
    """Worker thread para buscar videos en Pexels de forma asÃ­ncrona"""
    finished = pyqtSignal(list)  # Emite lista de videos encontrados
    error = pyqtSignal(str)  # Emite mensaje de error
    progress = pyqtSignal(str)  # Emite mensajes de progreso
    
    def __init__(self, query, narration_text="", require_attribution=False):
        super().__init__()
        self.query = query
        self.narration_text = narration_text
        self.require_attribution = require_attribution
    
    def run(self):
        """Ejecuta la bÃºsqueda"""
        try:
            from auto_video_generator_v2 import ResourceDownloader
            # Alias para compatibilidad
            StockMediaDownloader = ResourceDownloader
            downloader = StockMediaDownloader()
            
            if not downloader.pexels_key or downloader.pexels_key == "TU_API_KEY_DE_PEXELS":
                self.error.emit("Pexels API Key no configurada. Configura PEXELS_API_KEY en .env")
                return
            
            self.progress.emit(f"Buscando videos para: {self.query}...")
            
            # Buscar videos (Pexels ya es libre de derechos por defecto)
            videos = downloader.search_pexels_videos(self.query, count=50)  # Buscar mÃ¡s para filtrar
            
            # Filtrar y priorizar videos sin atribuciÃ³n
            no_attribution_videos = []
            attribution_videos = []
            filtered_videos = []
            
            for video in videos:
                # Analizar licencia para determinar si requiere atribuciÃ³n
                license_info = video.get('license', '').lower()
                title = video.get('title', '').lower()
                
                # Licencias que NO requieren atribuciÃ³n
                no_attribution_licenses = [
                    'public domain', 'pd', 'cc0', 'cc-zero', 'creative commons zero',
                    'public domain mark', 'pdmark', 'no rights reserved',
                    'free use', 'unrestricted', 'copyright free', 'no attribution',
                    'pexels license', 'free to use', 'no credit required'
                ]
                
                # Licencias que SÃ requieren atribuciÃ³n
                attribution_licenses = [
                    'cc by', 'cc by-sa', 'cc by-nc', 'cc by-nd', 'cc by-nc-sa', 'cc by-nc-nd',
                    'creative commons attribution', 'creative commons share alike',
                    'creative commons non-commercial', 'attribution required', 'credit required'
                ]
                
                requires_attribution = False
                is_free = False
                
                # Verificar si requiere atribuciÃ³n
                for attr_license in attribution_licenses:
                    if (attr_license in license_info or 
                        attr_license in title):
                        requires_attribution = True
                        break
                
                # Verificar si es libre de atribuciÃ³n
                for free_license in no_attribution_licenses:
                    if (free_license in license_info or 
                        free_license in title):
                        is_free = True
                        break
                
                # Pexels generalmente es libre de derechos, pero verificamos por si acaso
                if 'pexels' in license_info.lower() or 'pexels' in title.lower():
                    is_free = True
                    requires_attribution = False
                
                # Clasificar el video
                if self.require_attribution:
                    # Si el usuario pidiÃ³ con atribuciÃ³n, incluir todo
                    if requires_attribution or is_free or not license_info:
                        video['license_note'] = 'Gratis con atribuciÃ³n (Pexels License)'
                        video['requires_attribution'] = True
                        attribution_videos.append(video)
                else:
                    # Si el usuario pidiÃ³ sin atribuciÃ³n, priorizar los libres
                    if is_free or not requires_attribution:
                        video['license_note'] = 'Gratis para uso comercial (Pexels License)'
                        video['requires_attribution'] = False
                        no_attribution_videos.append(video)
                    elif requires_attribution and len(no_attribution_videos) < 15:
                        # Incluir algunos con atribuciÃ³n si hay pocos libres
                        video['license_note'] = 'Gratis con atribuciÃ³n (Pexels License)'
                        video['requires_attribution'] = True
                        attribution_videos.append(video)
                
                video['source'] = 'Pexels'
            
            # Combinar resultados: primero los sin atribuciÃ³n, luego con atribuciÃ³n
            if not self.require_attribution:
                filtered_videos = no_attribution_videos + attribution_videos[:5]  # MÃ¡ximo 5 con atribuciÃ³n
            else:
                filtered_videos = attribution_videos
            
            # Limitar a 20 resultados finales
            videos = filtered_videos[:20]
            
            if videos:
                attribution_text = "con atribuciÃ³n" if self.require_attribution else "libres de derechos"
                self.progress.emit(f"âœ… Encontrados {len(videos)} videos {attribution_text}")
                self.finished.emit(videos)
            else:
                self.error.emit(f"No se encontraron videos para: {self.query}")
        
        except Exception as e:
            self.error.emit(f"Error buscando videos: {str(e)}")


class WikimediaVideoSearchWorker(QThread):
    """Worker thread para buscar videos histÃ³ricos en Wikimedia de forma asÃ­ncrona"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, query, narration_text="", require_attribution=False):
        super().__init__()
        self.query = query
        self.narration_text = narration_text
        self.require_attribution = require_attribution

    @staticmethod
    def _normalize_duration(duration_value):
        """Convierte duraciÃ³n a segundos numÃ©ricos para evitar errores de tipo en UI."""
        if duration_value is None or isinstance(duration_value, bool):
            return 0.0

        if isinstance(duration_value, (int, float)):
            return float(duration_value) if duration_value > 0 else 0.0

        if isinstance(duration_value, str):
            raw_value = duration_value.strip()
            if not raw_value:
                return 0.0

            normalized = raw_value.replace(",", ".")

            if ":" in normalized:
                parts = [p.strip() for p in normalized.split(":")]
                values = []
                for part in parts:
                    if not part:
                        return 0.0
                    try:
                        values.append(float(part))
                    except ValueError:
                        values = []
                        break
                if values:
                    total_seconds = 0.0
                    for value in values:
                        total_seconds = total_seconds * 60 + value
                    return total_seconds if total_seconds > 0 else 0.0

            numeric_text = "".join(ch for ch in normalized if ch.isdigit() or ch == ".")
            if numeric_text:
                try:
                    numeric_value = float(numeric_text)
                    return numeric_value if numeric_value > 0 else 0.0
                except ValueError:
                    return 0.0

        return 0.0
    
    def run(self):
        """Ejecuta la bÃºsqueda"""
        try:
            from wikimedia_client import WikimediaClient
            client = WikimediaClient()
            
            self.progress.emit(f"Buscando videos histÃ³ricos para: {self.query}...")
            
            # Buscar videos reales de Wikimedia (no imÃ¡genes)
            media_items = client.search_videos(
                query=f"{self.query}",
                limit=50,
                narration_text=self.narration_text
            )
            
            # Filtrar y priorizar videos sin atribuciÃ³n
            no_attribution_videos = []
            attribution_videos = []
            filtered_videos = []
            seen_urls = set()
            
            for item in media_items:
                if not isinstance(item, dict):
                    continue

                video_url = item.get('url', '')
                if not video_url or video_url in seen_urls:
                    continue
                seen_urls.add(video_url)

                # Analizar licencia para determinar si requiere atribuciÃ³n
                license_info = item.get('license', '').lower()
                title = item.get('title', '').lower()
                
                # Licencias que NO requieren atribuciÃ³n
                no_attribution_licenses = [
                    'public domain', 'pd', 'cc0', 'cc-zero', 'creative commons zero',
                    'public domain mark', 'pdmark', 'no rights reserved',
                    'free use', 'unrestricted', 'copyright free', 'no attribution'
                ]
                
                # Licencias que SÃ requieren atribuciÃ³n
                attribution_licenses = [
                    'cc by', 'cc by-sa', 'cc by-nc', 'cc by-nd', 'cc by-nc-sa', 'cc by-nc-nd',
                    'creative commons attribution', 'creative commons share alike',
                    'creative commons non-commercial', 'attribution required', 'credit required'
                ]
                
                requires_attribution = False
                is_free = False
                
                # Verificar si requiere atribuciÃ³n
                for attr_license in attribution_licenses:
                    if (attr_license in license_info or 
                        attr_license in title):
                        requires_attribution = True
                        break
                
                # Verificar si es libre de atribuciÃ³n
                for free_license in no_attribution_licenses:
                    if (free_license in license_info or 
                        free_license in title):
                        is_free = True
                        break
                
                # Si no hay informaciÃ³n clara, asumir que requiere atribuciÃ³n (mÃ¡s seguro)
                if not requires_attribution and not is_free and not license_info:
                    requires_attribution = True
                
                # Clasificar el video
                if self.require_attribution:
                    # Si el usuario pidiÃ³ con atribuciÃ³n, incluir todo
                    if requires_attribution or is_free or not license_info:
                        item['license_note'] = 'Creative Commons con atribuciÃ³n (Wikimedia)'
                        item['requires_attribution'] = True
                        attribution_videos.append(item)
                else:
                    # Si el usuario pidiÃ³ sin atribuciÃ³n, priorizar los libres
                    if is_free or not requires_attribution:
                        item['license_note'] = 'Dominio PÃºblico / Creative Commons (Wikimedia)'
                        item['requires_attribution'] = False
                        no_attribution_videos.append(item)
                    elif requires_attribution and len(no_attribution_videos) < 15:
                        # Incluir algunos con atribuciÃ³n si hay pocos libres
                        item['license_note'] = 'Creative Commons con atribuciÃ³n (Wikimedia)'
                        item['requires_attribution'] = True
                        attribution_videos.append(item)
                
                # Marcar como video histÃ³rico
                item['media_type'] = 'video'
                item['source'] = 'Wikimedia Commons'
                item['duration'] = self._normalize_duration(item.get('duration', 0))
                if item['duration'] <= 0:
                    item['duration_text'] = 'Desconocida'
            
            # Combinar resultados: primero los sin atribuciÃ³n, luego con atribuciÃ³n
            if not self.require_attribution:
                filtered_videos = no_attribution_videos + attribution_videos[:5]  # MÃ¡ximo 5 con atribuciÃ³n
            else:
                filtered_videos = attribution_videos
            
            # Limitar resultados finales (configurable) para mantener UI fluida
            try:
                max_results = int(os.getenv('WIKIMEDIA_VIDEO_MAX_RESULTS', '50'))
            except Exception:
                max_results = 50
            max_results = max(1, min(max_results, 200))
            videos = filtered_videos[:max_results]
            
            if videos:
                print(
                    f"Wikimedia worker: {len(videos)} videos listos para mostrar "
                    f"(de {len(media_items)} candidatos) para '{self.query}'"
                )
                self.progress.emit(
                    f"âœ… Encontrados {len(videos)} videos histÃ³ricos "
                    f"(de {len(media_items)} candidatos)"
                )
                self.finished.emit(videos)
            else:
                self.error.emit(f"No se encontraron videos histÃ³ricos para: {self.query}")
        
        except Exception as e:
            self.error.emit(f"Error buscando videos: {str(e)}")


class InternetArchiveVideoSearchWorker(QThread):
    """Worker thread para buscar videos histÃ³ricos en Internet Archive de forma asÃ­ncrona"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, query, narration_text=""):
        super().__init__()
        self.query = query
        self.narration_text = narration_text
    
    def run(self):
        """Ejecuta la bÃºsqueda"""
        try:
            from internet_archive_client import InternetArchiveClient
            client = InternetArchiveClient()
            
            try:
                self.progress.emit(f"Buscando videos histÃ³ricos para: {self.query}...")
            except Exception:
                pass  # Ignorar errores al emitir progreso
            
            try:
                videos = client.search_videos(self.query, limit=10)  # Reducir a 10 para evitar sobrecarga
            except Exception as e:
                self.error.emit(f"Error en la bÃºsqueda: {str(e)}")
                return
            
            # Validar que videos sea una lista
            if not isinstance(videos, list):
                self.error.emit("Error: Los resultados no son vÃ¡lidos")
                return
            
            if videos:
                try:
                    self.progress.emit(f"âœ… Encontrados {len(videos)} videos histÃ³ricos")
                except Exception:
                    pass
                
                # Validar y limpiar videos antes de emitir
                valid_videos = []
                for video in videos:
                    if isinstance(video, dict) and video.get('url'):
                        valid_videos.append(video)
                
                if valid_videos:
                    try:
                        self.finished.emit(valid_videos)
                    except Exception as e:
                        self.error.emit(f"Error emitiendo resultados: {str(e)}")
                else:
                    self.error.emit(f"No se encontraron videos vÃ¡lidos para: {self.query}")
            else:
                self.error.emit(f"No se encontraron videos histÃ³ricos para: {self.query}")
        
        except Exception as e:
            try:
                self.error.emit(f"Error buscando videos: {str(e)}")
            except Exception:
                # Si incluso emitir el error falla, al menos imprimir
                print(f"âŒ Error crÃ­tico en InternetArchiveVideoSearchWorker: {e}")
                import traceback
                traceback.print_exc()


class YouTubeVideoSearchWorker(QThread):
    """Worker thread para buscar videos en YouTube de forma asÃ­ncrona"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, query, narration_text=""):
        super().__init__()
        self.query = query
        self.narration_text = narration_text
    def run(self):
        """Ejecuta la b????squeda"""
        try:
            if not YOUTUBE_VIDEO_AVAILABLE:
                self.error.emit("YouTube client no disponible")
                return
            
            from youtube_video_client import YouTubeVideoClient
            youtube_client = YouTubeVideoClient()
            
            if youtube_client.is_youtube_url(self.query):
                if not YT_DLP_AVAILABLE:
                    self.error.emit(
                        "yt-dlp no esta instalado.\n\n"
                        "Para usar una URL directa de YouTube necesitas instalar yt-dlp:\n"
                        "pip install yt-dlp"
                    )
                    return
            
                self.progress.emit("Analizando URL directa de YouTube...")
                video_info = youtube_client.get_video_info_from_url(self.query)
                if not video_info:
                    self.error.emit(
                        "No se pudo analizar la URL de YouTube.\n\n"
                        "Verifica que el enlace sea valido y que yt-dlp pueda acceder al video."
                    )
                    return
            
                self.finished.emit([video_info])
                return
            
            self.progress.emit("Buscando videos en YouTube...")
            
            if not youtube_client.api_key:
                self.error.emit("GOOGLE_API_KEY no configurada. Config????rala en tu archivo .env")
                return
            
            videos = youtube_client.search_videos(self.query, limit=20, order='relevance')

            self.finished.emit(videos)
        except Exception as e:
            self.error.emit(f"Error buscando videos: {str(e)}")


class FalI2VWorker(QThread):
    """
    Worker que anima una imagen local a video usando FAL.AI Image-to-Video (Kling/Luma).

    Flujo:
    1. Sube la imagen local a la CDN de FAL via fal_client.upload_file().
    2. Llama a FalAiVideoClient.image_to_video() con la URL resultante.
    3. Emite finished(segment_index, video_path) o error(segment_index, msg).
    """

    finished = pyqtSignal(int, str)   # segment_index, video_path
    error = pyqtSignal(int, str)      # segment_index, error_message
    progress = pyqtSignal(str)        # log message

    def __init__(self, segment_index: int, image_path: str, motion_prompt: str,
                 output_path: str, aspect_ratio: str = "16:9",
                 duration: int = 5, video_model: str = "kling-standard"):
        super().__init__()
        self.segment_index = segment_index
        self.image_path = image_path
        self.motion_prompt = motion_prompt
        self.output_path = output_path
        self.aspect_ratio = aspect_ratio
        self.duration = duration
        self.video_model = video_model

    def run(self):
        import os
        try:
            from fal_ai_client import build_fal_clients, is_fal_configured
            if not is_fal_configured():
                self.error.emit(self.segment_index, "FAL.AI no configurado (falta FAL_KEY en .env.txt)")
                return

            _, vid_client = build_fal_clients()
            if not vid_client or not getattr(vid_client, 'available', False):
                self.error.emit(self.segment_index, "FAL.AI VideoClient no disponible")
                return

            self.progress.emit("Subiendo imagen a CDN de FAL...")
            try:
                import fal_client as _fal_sdk
                image_url = _fal_sdk.upload_file(self.image_path)
            except Exception as exc:
                self.error.emit(self.segment_index, f"Error subiendo imagen a FAL CDN: {exc}")
                return

            if not image_url:
                self.error.emit(self.segment_index, "No se obtuvo URL de la imagen subida")
                return

            self.progress.emit(f"Generando video I2V {self.duration}s ({self.aspect_ratio})...")
            video_path = vid_client.image_to_video(
                image_url=image_url,
                prompt=self.motion_prompt or "Slow dramatic camera motion, cinematic lighting",
                output_path=self.output_path,
                model=self.video_model,
                duration=self.duration,
                aspect_ratio=self.aspect_ratio,
            )

            if video_path and os.path.exists(video_path):
                self.finished.emit(self.segment_index, video_path)
            else:
                err = getattr(vid_client, 'last_error', None) or "Sin video generado"
                self.error.emit(self.segment_index, str(err))

        except Exception as exc:
            self.error.emit(self.segment_index, str(exc))

