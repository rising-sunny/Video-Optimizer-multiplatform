# tts_generator.py
"""
Generador de Text-to-Speech usando ElevenLabs, Edge-TTS o gTTS
"""

import asyncio
import os
import time
import requests
import importlib.util
from pathlib import Path
from typing import Dict, Optional, List

from infra.video_config import VideoConfig

# Verificar dependencias
GTTS_AVAILABLE = False
EDGE_TTS_AVAILABLE = False
edge_tts = None
EDGE_TTS_IMPORT_ERROR = None

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    pass

PYDUB_AVAILABLE = False
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    AudioSegment = None

# Detectar disponibilidad del paquete sin importarlo aÃºn (lazy import).
# Esto permite Edge-TTS tambiÃ©n en Windows, evitando cargarlo en arranque.
if importlib.util.find_spec("edge_tts") is not None:
    EDGE_TTS_AVAILABLE = True


def _ensure_edge_tts_loaded():
    """Importa edge_tts bajo demanda y devuelve el mÃ³dulo o None."""
    global edge_tts, EDGE_TTS_AVAILABLE, EDGE_TTS_IMPORT_ERROR
    if not EDGE_TTS_AVAILABLE:
        return None
    if edge_tts is not None:
        return edge_tts
    try:
        import edge_tts as edge_tts_module  # type: ignore
        edge_tts = edge_tts_module
        return edge_tts
    except Exception as e:
        EDGE_TTS_IMPORT_ERROR = str(e)
        EDGE_TTS_AVAILABLE = False
        print(f"âš ï¸ Edge-TTS detectado pero no pudo importarse: {e}")
        return None


class TextToSpeechGenerator:
    """Genera narraciÃ³n de audio usando ElevenLabs, Edge-TTS o gTTS"""
    
    def __init__(self):
        self.audio_dir = VideoConfig.AUDIO_DIR
        self.elevenlabs_key = VideoConfig.ELEVENLABS_API_KEY
        self.edge_tts_voices_cache = None
    
    async def _get_edge_tts_voices(self) -> Dict[str, Dict]:
        """Obtiene voces disponibles de Edge-TTS (async)"""
        edge_module = _ensure_edge_tts_loaded()
        if edge_module is None:
            return {}
        
        try:
            voices = await edge_module.list_voices()
            edge_voices = {}
            
            # Filtrar voces en espaÃ±ol e inglÃ©s principalmente
            for voice in voices:
                lang = voice.get('Locale', '').lower()
                name = voice.get('ShortName', '')
                friendly_name = voice.get('FriendlyName', name)
                
                # Incluir espaÃ±ol, inglÃ©s y algunos otros idiomas comunes
                if lang.startswith('es') or lang.startswith('en') or lang.startswith('fr') or lang.startswith('de'):
                    # Crear nombre amigable
                    gender = voice.get('Gender', '')
                    display_name = f"Edge-TTS: {friendly_name} ({lang.upper()})"
                    if gender:
                        display_name += f" [{gender}]"
                    
                    edge_voices[display_name] = {
                        'id': name,  # ShortName es el ID que se usa
                        'name': friendly_name,
                        'language': lang,
                        'gender': gender,
                        'provider': 'edge-tts'
                    }
            
            return edge_voices
        except Exception as e:
            print(f"âš ï¸ Error obteniendo voces de Edge-TTS: {e}")
            return {}
    
    def _get_edge_tts_disk_cache_path(self) -> Path:
        """Ruta del cache en disco para voces Edge-TTS"""
        return Path.home() / '.video_optimizer' / 'edge_tts_voices_cache.json'

    def _load_edge_tts_disk_cache(self) -> Dict[str, Dict]:
        """Carga voces Edge-TTS desde cache en disco (fallback cuando no hay internet)"""
        cache_path = self._get_edge_tts_disk_cache_path()
        if cache_path.exists():
            try:
                import json
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                if cached:
                    print(f" Usando {len(cached)} voces Edge-TTS desde cache local (sin conexion)")
                    return cached
            except Exception:
                pass
        return {}

    def _save_edge_tts_disk_cache(self, voices: Dict[str, Dict]):
        """Guarda voces Edge-TTS en cache en disco"""
        cache_path = self._get_edge_tts_disk_cache_path()
        try:
            import json
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(voices, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"️ No se pudo guardar cache de voces Edge-TTS: {e}")

    def get_cached_or_fallback_voices(self) -> Dict[str, Dict]:
        """Devuelve voces recuperadas desde cache local o un fallback minimo."""
        voices = {}

        if EDGE_TTS_AVAILABLE:
            voices.update(self._load_edge_tts_disk_cache())

        if GTTS_AVAILABLE and "gTTS (Español)" not in voices:
            voices["gTTS (Español)"] = {
                "id": "gtts_fallback",
                "name": "gTTS Español",
                "language": "es",
                "provider": "gtts",
            }

        return voices

    def get_edge_tts_voices_sync(self) -> Dict[str, Dict]:
        """Obtiene voces de Edge-TTS de forma sÃ­ncrona"""
        if _ensure_edge_tts_loaded() is None:
            return {}
        
        # Usar cache si estÃ¡ disponible
        if self.edge_tts_voices_cache is not None:
            return self.edge_tts_voices_cache
        
        try:
            import asyncio
            try:
                self.edge_tts_voices_cache = asyncio.run(self._get_edge_tts_voices())
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self.edge_tts_voices_cache = loop.run_until_complete(self._get_edge_tts_voices())
                loop.close()
            # Si obtuvimos voces, guardar en cache de disco para offline
            if self.edge_tts_voices_cache:
                self._save_edge_tts_disk_cache(self.edge_tts_voices_cache)

            return self.edge_tts_voices_cache
        except Exception as e:
            print(f"âš ï¸ Error obteniendo voces de Edge-TTS: {e}")
            # Intentar cargar desde cache en disco como fallback
            fallback = self._load_edge_tts_disk_cache()
            if fallback:
                self.edge_tts_voices_cache = fallback
                return fallback
            return {}
    
    def get_available_voices(self) -> Dict[str, Dict]:
        """Obtiene voces disponibles de ElevenLabs, Edge-TTS y gTTS"""
        voices = {}
        
        # 1. Agregar voces de Edge-TTS (GRATIS)
        if EDGE_TTS_AVAILABLE:
            edge_voices = self.get_edge_tts_voices_sync()
            voices.update(edge_voices)
            if edge_voices:
                print(f"âœ… {len(edge_voices)} voces de Edge-TTS (gratis) cargadas")
            elif EDGE_TTS_IMPORT_ERROR:
                print(f"️ Edge-TTS no se pudo cargar: {EDGE_TTS_IMPORT_ERROR}")
        
        # 2. Agregar gTTS (GRATIS)
        if GTTS_AVAILABLE:
            voices["gTTS (EspaÃ±ol)"] = {
                "id": "gtts_fallback", "name": "gTTS EspaÃ±ol", "language": "es", "provider": "gtts"
            }
        
        # 3. Agregar voces de ElevenLabs (si estÃ¡ configurado)
        if (not self.elevenlabs_key or self.elevenlabs_key == "TU_API_KEY_DE_ELEVENLABS"):
            if not voices:
                print("âš ï¸ ELEVENLABS_API_KEY no configurada. Usando solo voces gratuitas (Edge-TTS/gTTS).")
            return voices
        
        try:
            # URL LIMPIA
            url = "https://api.elevenlabs.io/v1/voices"
            headers = {"xi-api-key": self.elevenlabs_key}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                elevenlabs_voices = {}
                for voice in data.get('voices', []):
                    voice_name = voice.get('name', 'Unknown')
                    elevenlabs_voices[voice_name] = {
                        'id': voice.get('voice_id'),
                        'name': voice_name,
                        'language': voice.get('labels', {}).get('language', 'unknown'),
                        'provider': 'elevenlabs'
                    }
                voices.update(elevenlabs_voices)
                print(f"âœ… {len(elevenlabs_voices)} voces de ElevenLabs cargadas exitosamente")
                return voices
            elif response.status_code == 401:
                print(f"âŒ Error de autenticaciÃ³n con ElevenLabs (401). Verifica que tu API key sea vÃ¡lida.")
                return voices
            else:
                print(f"âš ï¸ Error al obtener voces de ElevenLabs (Status: {response.status_code})")
                print(f"   Respuesta: {response.text[:200]}")
                return voices
        except requests.exceptions.Timeout:
            print(f"âŒ Timeout al conectar con ElevenLabs. Verifica tu conexiÃ³n a internet.")
            return voices
        except requests.exceptions.RequestException as e:
            print(f"âŒ Error de conexiÃ³n con ElevenLabs: {e}")
            return voices
        except Exception as e:
            print(f"âŒ Error inesperado conectando con ElevenLabs: {e}")
            import traceback
            traceback.print_exc()
            return voices
    
    async def _play_edge_tts_sample(self, voice_id: str, language: str = 'es') -> bool:
        """Reproduce una muestra de voz de Edge-TTS (async)"""
        edge_module = _ensure_edge_tts_loaded()
        if edge_module is None:
            return False
        
        try:
            sample_text = "Hola, esta es una muestra de mi voz." if language == 'es' else "Hello, this is a sample of my voice."
            communicate = edge_module.Communicate(sample_text, voice_id)
            
            temp_audio = self.audio_dir / "temp_sample_edge.mp3"
            await communicate.save(str(temp_audio))
            
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(str(temp_audio))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy(): 
                    time.sleep(0.1)
                pygame.mixer.music.unload()
                try: temp_audio.unlink() 
                except: pass
                return True
            except Exception as e:
                print(f"âš ï¸ Error reproduciendo audio: {e}")
                return True
        except Exception as e:
            print(f"âŒ Error en play_edge_tts_sample: {e}")
            return False
    
    def play_voice_sample(self, voice_id: str, language: str = 'es') -> bool:
        """Reproduce una muestra de voz"""
        # Verificar si es una voz de Edge-TTS
        if EDGE_TTS_AVAILABLE and voice_id and not voice_id.startswith("gtts") and not voice_id.startswith("eleven"):
            try:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                return loop.run_until_complete(self._play_edge_tts_sample(voice_id, language))
            except Exception as e:
                print(f"âš ï¸ Error reproduciendo muestra de Edge-TTS: {e}")
                return False
        
        if voice_id == "gtts_fallback":
            print("â„¹ï¸ gTTS no tiene muestras de audio")
            return False
        
        # Texto de muestra segÃºn idioma
        sample_text = "Hola, esta es una muestra de mi voz." if language == 'es' else "Hello, this is a sample of my voice."
        
        try:
            # URL LIMPIA Y CORREGIDA
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            
            headers = {
                "Accept": "audio/mpeg", 
                "Content-Type": "application/json", 
                "xi-api-key": self.elevenlabs_key
            }
            data = {
                "text": sample_text, 
                "model_id": "eleven_multilingual_v2", 
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            }
            response = requests.post(url, json=data, headers=headers, timeout=30)
            
            if response.status_code == 200:
                temp_audio = self.audio_dir / "temp_sample.mp3"
                with open(temp_audio, 'wb') as f:
                    f.write(response.content)
                
                try:
                    import pygame
                    pygame.mixer.init()
                    pygame.mixer.music.load(str(temp_audio))
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy(): 
                        time.sleep(0.1)
                    pygame.mixer.music.unload()
                    try: temp_audio.unlink() 
                    except: pass
                    return True
                except Exception as e:
                    print(f"âš ï¸ Error reproduciendo audio: {e}")
                    return True
            else:
                print(f"âŒ Error ElevenLabs: {response.status_code}")
                return False
        except Exception as e:
            print(f"âŒ Error en play_voice_sample: {e}")
            return False

    def _split_script_for_tts(self, script: str, max_chars: int = 3200) -> List[str]:
        """Divide guiones largos en bloques para evitar límites de APIs TTS."""
        clean_script = " ".join((script or "").split())
        if not clean_script:
            return []
        if len(clean_script) <= max_chars:
            return [clean_script]

        import re
        sentences = re.split(r'(?<=[.!?])\s+', clean_script)
        chunks = []
        current = ""

        def _push_current():
            nonlocal current
            if current:
                chunks.append(current.strip())
                current = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(sentence) > max_chars:
                words = sentence.split()
                for word in words:
                    candidate = f"{current} {word}".strip() if current else word
                    if len(candidate) <= max_chars:
                        current = candidate
                    else:
                        _push_current()
                        current = word
                continue

            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                _push_current()
                current = sentence

        _push_current()
        return chunks if chunks else [clean_script]

    def _merge_audio_chunks(self, chunk_files: List[str], output_file: str) -> Optional[str]:
        """Une audios parciales en un único MP3."""
        if not chunk_files:
            return None
        if not PYDUB_AVAILABLE or AudioSegment is None:
            print("âš ï¸ pydub no disponible, no se pueden unir bloques de audio.")
            return None

        try:
            merged = AudioSegment.silent(duration=0)
            pause = AudioSegment.silent(duration=120)
            for idx, chunk_file in enumerate(chunk_files):
                merged += AudioSegment.from_file(chunk_file)
                if idx < len(chunk_files) - 1:
                    merged += pause
            merged.export(output_file, format="mp3")
            return output_file
        except Exception as e:
            print(f"âŒ Error uniendo audio por bloques: {e}")
            return None
        finally:
            for chunk_file in chunk_files:
                try:
                    if os.path.exists(chunk_file):
                        os.remove(chunk_file)
                except Exception:
                    pass

    @staticmethod
    def _is_transient_edge_tts_error(error: Exception) -> bool:
        """Detecta errores recuperables de Edge-TTS para aplicar reintentos."""
        # Por TIPO antes que por texto: `str(asyncio.TimeoutError())` es la
        # cadena VACIA, asi que buscar "timeout" en el mensaje no lo detecta y
        # el corte por timeout se trataba como error definitivo.
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return True
        message = str(error).lower()
        if "verify that your parameters are correct" in message:
            return False
        transient_markers = (
            "503",
            "429",
            "500",
            "502",
            "504",
            "timeout",
            "temporarily unavailable",
            "server disconnected",
            "connection reset",
            "cannot write to closing transport",
            "no audio received",
            "invalid response status",
        )
        return any(marker in message for marker in transient_markers)
    
    # Piso y ritmo del timeout de Edge-TTS. El servicio sintetiza bastante mas
    # rapido que tiempo real; 1s por cada 40 caracteres deja margen de sobra
    # sin dejar que un cuelgue se eternice. Un bloque de 3500 chars (el maximo
    # por request) da ~88s.
    EDGE_TTS_MIN_TIMEOUT_S = 45.0
    EDGE_TTS_SECONDS_PER_CHAR = 1 / 40.0

    def _edge_tts_timeout_for(self, script: str) -> float:
        """Timeout en segundos para UN request de Edge-TTS, segun el largo."""
        largo = len(script or "")
        return max(self.EDGE_TTS_MIN_TIMEOUT_S, largo * self.EDGE_TTS_SECONDS_PER_CHAR)

    async def _generate_edge_tts_narration(
        self,
        script: str,
        filename: str,
        voice_id: str,
        rate: str = "+0%",
        max_retries: int = 2
    ) -> Optional[str]:
        """Genera audio usando Edge-TTS (async)
        
        Args:
            rate: Velocidad de habla, ej: '+0%' (normal), '+20%', '+40%', '-10%'
        """
        edge_module = _ensure_edge_tts_loaded()
        if edge_module is None:
            return None

        attempts = max(1, int(max_retries) + 1)
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except Exception:
                        pass

                communicate = edge_module.Communicate(script, voice_id, rate=rate)
                # `save()` abre un WebSocket contra Microsoft y NO tiene
                # timeout: si la conexion queda a medias (TCP abierto pero sin
                # datos, o el servicio no responde) espera para siempre. El
                # 2026-09-02 eso colgo el ensamblaje en "Generando narracion",
                # con un dialogo modal SIN boton de cancelar: no habia salida
                # mas que matar la app. Los reintentos de abajo tampoco servian
                # porque un cuelgue nunca lanza excepcion.
                await asyncio.wait_for(
                    communicate.save(filename),
                    timeout=self._edge_tts_timeout_for(script),
                )

                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    return filename
                raise RuntimeError("Edge-TTS devolvió un archivo vacío")
            except Exception as e:
                last_error = e
                is_retryable = self._is_transient_edge_tts_error(e)
                # Un TimeoutError no trae mensaje: sin esto el log decia
                # "fallo temporalmente: ." y no se entendia nada.
                detalle = str(e) or (
                    f"sin respuesta en {self._edge_tts_timeout_for(script):.0f}s"
                    if isinstance(e, (asyncio.TimeoutError, TimeoutError))
                    else type(e).__name__
                )
                if attempt < attempts and is_retryable:
                    backoff_seconds = min(3.0, 0.8 * attempt)
                    print(
                        f"️ Edge-TTS falló temporalmente (intento {attempt}/{attempts}): {detalle}. "
                        f"Reintentando en {backoff_seconds:.1f}s..."
                    )
                    await asyncio.sleep(backoff_seconds)
                    continue
                break

        if last_error is not None:
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except Exception:
                    pass
            _detalle_final = str(last_error) or type(last_error).__name__
            print(f"\u274c Error Edge-TTS: {_detalle_final}")
        return None
    
    def generate_narration(
        self,
        script: str,
        filename: str,
        voice_id: Optional[str] = None,
        language: str = 'es',
        allow_chunking: bool = True,
        rate: str = "+0%",
        allow_provider_fallback: bool = True
    ) -> Optional[str]:
        """Genera audio de narración usando ElevenLabs, Edge-TTS o gTTS

        Args:
            rate: Velocidad de habla para Edge-TTS, ej: '+0%', '+20%', '+40%'
            allow_provider_fallback: Si es False, no cambia a otro proveedor cuando falla el elegido
        """
        output_path = Path(filename).expanduser()
        if not output_path.is_absolute():
            output_path = (Path(__file__).resolve().parent.parent / output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        filename = str(output_path)
        
        # Determinar el proveedor basado en voice_id
        provider = None
        if voice_id:
            # Verificar si es Edge-TTS (contiene guiones y generalmente cÃ³digo de paÃ­s, ej: es-ES-AlvaroNeural)
            # O si empieza explÃ­citamente con "edge-tts" (aunque no es el ID estÃ¡ndar)
            if EDGE_TTS_AVAILABLE and (("-" in voice_id and "Neural" in voice_id) or (len(voice_id) < 20 and not voice_id.startswith("gtts"))):
                provider = "edge-tts"
            # Verificar si es ElevenLabs (UUID largo ~20 chars o empieza con "eleven")
            # Los IDs de ElevenLabs suelen ser de 20 caracteres (ej: 21m00Tcm4TlvDq8ikWAM)
            elif (self.elevenlabs_key and self.elevenlabs_key != "TU_API_KEY_DE_ELEVENLABS" and
                  voice_id != "gtts_fallback" and len(voice_id) >= 20):
                provider = "elevenlabs"
            else:
                provider = "gtts"
        if provider is None:
            provider = "gtts"

        # Chunking automático para guiones largos (evita límites por request de TTS).
        if allow_chunking and script:
            chunk_limits = {
                "edge-tts": 3500,
                "elevenlabs": 2400,
                "gtts": 2500,
            }
            max_chunk_chars = chunk_limits.get(provider, 3000)
            script_chunks = self._split_script_for_tts(script, max_chars=max_chunk_chars)
            if len(script_chunks) > 1:
                if not PYDUB_AVAILABLE:
                    print("âš ï¸ Guion largo detectado, pero pydub no está disponible para unir bloques. Intentando en una sola pasada.")
                else:
                    print(f" Guion largo detectado: {len(script_chunks)} bloques TTS")
                    output_path = Path(filename)
                    suffix = output_path.suffix if output_path.suffix else ".mp3"
                    chunk_files = []
                    for idx, chunk_text in enumerate(script_chunks, start=1):
                        chunk_path = output_path.with_name(f"{output_path.stem}_chunk_{idx:03d}{suffix}")
                        chunk_result = self.generate_narration(
                            chunk_text,
                            str(chunk_path),
                            voice_id=voice_id,
                            language=language,
                            allow_chunking=False,
                            rate=rate,
                            allow_provider_fallback=allow_provider_fallback
                        )
                        if not chunk_result:
                            for temp_path in chunk_files:
                                try:
                                    if os.path.exists(temp_path):
                                        os.remove(temp_path)
                                except Exception:
                                    pass
                            return None
                        chunk_files.append(str(chunk_path))
                    merged_file = self._merge_audio_chunks(chunk_files, filename)
                    if merged_file:
                        return merged_file
                    return None

        # 1. Intentar Edge-TTS (GRATIS)
        if provider == "edge-tts" and EDGE_TTS_AVAILABLE:
            try:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self._generate_edge_tts_narration(script, filename, voice_id, rate=rate))
                if result:
                    return result
            except Exception as e:
                print(f"âŒ Error con Edge-TTS: {e}. Intentando fallback...")
            if not allow_provider_fallback:
                return None
        
        # 2. Intentar ElevenLabs
        if provider == "elevenlabs" and (self.elevenlabs_key and self.elevenlabs_key != "TU_API_KEY_DE_ELEVENLABS"):
            try:
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                headers = {
                    "Accept": "audio/mpeg", 
                    "Content-Type": "application/json", 
                    "xi-api-key": self.elevenlabs_key
                }
                data = {
                    "text": script, 
                    "model_id": "eleven_multilingual_v2", 
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
                }
                response = requests.post(url, json=data, headers=headers, timeout=60)
                
                if response.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    return filename
                else:
                    print(f"âš ï¸ Error ElevenLabs ({response.status_code}): {response.text}. Usando fallback...")
            except Exception as e:
                print(f"âŒ Error conectando con ElevenLabs: {e}. Usando fallback...")
            if not allow_provider_fallback:
                return None
        
        # 3. Fallback a gTTS (GRATIS)
        if GTTS_AVAILABLE:
            try:
                lang_code = 'es' if language == 'es' else 'en'
                tts = gTTS(text=script, lang=lang_code, slow=False)
                tts.save(filename)
                return filename
            except Exception as e:
                print(f"âŒ Error gTTS: {e}")
                return None
        return None

