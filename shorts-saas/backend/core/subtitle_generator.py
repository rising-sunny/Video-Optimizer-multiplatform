# subtitle_generator.py
"""
Generador de subtítulos automáticos usando Whisper
"""

from typing import List, Dict, Optional, Tuple

from video_config import VideoConfig

# Verificar dependencias
WHISPER_AVAILABLE = False
MOVIEPY_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    pass

try:
    from moviepy.editor import TextClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    pass


class SubtitleGenerator:
    """Genera subtítulos automáticos usando Whisper"""
    
    def __init__(self):
        self.model = None
        if WHISPER_AVAILABLE:
            try:
                # print("🎤 Cargando modelo Whisper...")
                self.model = whisper.load_model("base")
                # print("✅ Modelo Whisper cargado")
            except Exception as e:
                print(f"❌ Error cargando Whisper: {e}")
    
    def transcribe_audio(self, audio_path: str, language: str = 'es') -> Optional[List[Dict]]:
        if not self.model:
            return None
        try:
            # print("🎤 Transcribiendo audio...")
            # Pasamos el idioma seleccionado a Whisper
            result = self.model.transcribe(
                audio_path,
                language=language,
                word_timestamps=True,
                verbose=False
            )
            segments = []
            for segment in result.get('segments', []):
                segments.append({
                    'start': segment['start'],
                    'end': segment['end'],
                    'text': segment['text'].strip()
                })
            
            # print(f"✅ {len(segments)} segmentos transcritos")
            return segments
        except Exception as e:
            print(f"❌ Error en transcripción: {e}")
            return None
    
    def create_subtitle_clips(self, segments: List[Dict], video_size: Tuple[int, int],
                             style: str = 'capcut') -> List:
        """Crea clips de subtítulos con estilo específico"""
        if not MOVIEPY_AVAILABLE:
            return []
        
        # Verificar si ImageMagick está disponible antes de intentar crear TextClips
        # TextClip requiere ImageMagick en Windows
        try:
            # Intentar crear un TextClip de prueba para verificar ImageMagick
            test_clip = TextClip("test", fontsize=20, color='white', method='caption')
            test_clip.close()  # Cerrar inmediatamente
            imagemagick_available = True
        except Exception as e:
            # ImageMagick no está disponible o no está configurado
            print(f"⚠️ ImageMagick no disponible para TextClip. Los subtítulos MoviePy no se crearán.")
            print(f"   (Esto es normal si estás usando subtítulos dinámicos)")
            return []  # Retornar lista vacía en lugar de fallar
        
        style_config = VideoConfig.SUBTITLE_STYLES.get(style, VideoConfig.SUBTITLE_STYLES['capcut'])
        subtitle_clips = []
        
        for segment in segments:
            try:
                # Crear TextClip
                txt_clip = TextClip(
                    segment['text'].upper(),  # Convertir a mayúsculas
                    fontsize=style_config['font_size'],
                    color=style_config['font_color'],
                    font='Arial-Bold',  # Fuente estándar
                    stroke_color=style_config['stroke_color'],
                    stroke_width=style_config['stroke_width'],
                    method='caption',
                    size=(video_size[0] * 0.9, None),  # 90% del ancho
                    align='center'
                )
                
                # Posicionar
                if style_config['position'][1] == 'bottom':
                    txt_clip = txt_clip.set_position(('center', video_size[1] * 0.8))  # 80% hacia abajo
                elif style_config['position'][1] == 'center':
                    txt_clip = txt_clip.set_position('center')
                else:
                    txt_clip = txt_clip.set_position(('center', video_size[1] * 0.2))  # 20% hacia abajo
                
                txt_clip = txt_clip.set_start(segment['start']).set_duration(
                    segment['end'] - segment['start']
                )
                
                # Animaciones
                fade_duration = 0.1
                if style_config.get('animation') == 'zoom':
                    # Efecto Zoom simple
                    txt_clip = txt_clip.resize(lambda t: 1 + 0.1 * t)
                else:
                    # Fade in/out
                    txt_clip = txt_clip.crossfadein(fade_duration).crossfadeout(fade_duration)
                
                subtitle_clips.append(txt_clip)
            
            except Exception as e:
                # Si falla, continuar sin ese clip (no bloquear todo el proceso)
                print(f"⚠️ Error creando clip de subtítulo (puede ser ImageMagick): {e}")
                continue
        
        return subtitle_clips

