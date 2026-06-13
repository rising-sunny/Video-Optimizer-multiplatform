# cinematic_effects.py
"""
Sistema de Efectos Cinematográficos Profesionales
--------------------------------------------------
Implementa:
- Pan & Zoom dinámico (Efecto Ken Burns)
- Filtros contextuales automáticos (B&W, Sepia, Vignette, etc.)
- Transiciones inteligentes (basadas en ritmo y contexto)
- Detección de contexto del texto para aplicar efectos apropiados
"""

import random
from typing import List, Dict, Tuple, Optional, Literal
from enum import Enum
import re


class MovementType(Enum):
    """Tipos de movimiento de cámara"""
    ZOOM_IN = "zoom_in"           # Acercar desde lejos
    ZOOM_OUT = "zoom_out"         # Alejar desde cerca
    PAN_LEFT = "pan_left"         # Paneo izquierda
    PAN_RIGHT = "pan_right"       # Paneo derecha
    PAN_UP = "pan_up"             # Paneo arriba
    PAN_DOWN = "pan_down"         # Paneo abajo
    PAN_ZOOM_IN = "pan_zoom_in"   # Paneo + zoom combinado
    DIAGONAL_LT = "diagonal_lt"   # Diagonal izq-arriba
    DIAGONAL_RT = "diagonal_rt"   # Diagonal der-arriba
    DIAGONAL_LB = "diagonal_lb"   # Diagonal izq-abajo
    DIAGONAL_RB = "diagonal_rb"   # Diagonal der-abajo
    STATIC = "static"             # Sin movimiento


class FilterType(Enum):
    """Tipos de filtros cinematográficos"""
    NONE = "none"                 # Sin filtro
    BLACK_WHITE = "bw"            # Blanco y negro
    SEPIA = "sepia"               # Sepia (tono antiguo)
    COOL = "cool"                 # Tonos fríos (azul)
    WARM = "warm"                 # Tonos cálidos (naranja)
    DRAMATIC = "dramatic"         # Alto contraste
    VINTAGE = "vintage"           # Vintage (desaturado)
    NOIR = "noir"                 # Film noir (B&W + contraste)
    CINEMATIC = "cinematic"       # Look cinematográfico
    VIGNETTE = "vignette"         # Viñeta (bordes oscuros)


class TransitionType(Enum):
    """Tipos de transiciones"""
    CUT = "cut"                   # Corte directo
    FADE = "fade"                 # Fundido
    CROSSFADE = "crossfade"       # Fundido cruzado
    DISSOLVE = "dissolve"         # Disolución
    WIPE_LEFT = "wipe_left"       # Barrido izquierda
    WIPE_RIGHT = "wipe_right"     # Barrido derecha
    SLIDE = "slide"               # Deslizamiento
    ZOOM = "zoom"                 # Zoom transición


class ContextDetector:
    """
    Detecta el contexto del texto para aplicar efectos apropiados.
    """
    
    # Palabras clave para diferentes contextos
    HISTORICAL_KEYWORDS = [
        'historia', 'pasado', 'antiguo', 'época', 'año', 'siglo',
        'histórico', 'antes', 'viejo', 'origin', 'historia',
        'history', 'past', 'ancient', 'old', 'vintage', 'era',
        'century', 'ago', 'historical', 'traditional', 'classic'
    ]
    
    ACTION_KEYWORDS = [
        'rápido', 'velocidad', 'acción', 'movimiento', 'carrera',
        'batalla', 'lucha', 'explosión', 'persecución', 'escape',
        'fast', 'speed', 'action', 'movement', 'race', 'battle',
        'fight', 'explosion', 'chase', 'run', 'pursue'
    ]
    
    DRAMATIC_KEYWORDS = [
        'dramático', 'tensión', 'suspense', 'misterio', 'oscuro',
        'peligro', 'miedo', 'terror', 'conflicto', 'crisis',
        'dramatic', 'tension', 'suspense', 'mystery', 'dark',
        'danger', 'fear', 'terror', 'conflict', 'crisis'
    ]
    
    CALM_KEYWORDS = [
        'tranquilo', 'paz', 'calma', 'sereno', 'relajado',
        'suave', 'pacífico', 'natural', 'belleza', 'armonia',
        'calm', 'peace', 'peaceful', 'serene', 'relaxed',
        'smooth', 'gentle', 'natural', 'beauty', 'harmony'
    ]
    
    EMOTIONAL_KEYWORDS = [
        'amor', 'corazón', 'emoción', 'sentimiento', 'romántico',
        'tristeza', 'alegría', 'pasión', 'nostalgia', 'recuerdo',
        'love', 'heart', 'emotion', 'feeling', 'romantic',
        'sadness', 'joy', 'passion', 'nostalgia', 'memory'
    ]
    
    @classmethod
    def detect_context(cls, text: str) -> Dict[str, float]:
        """
        Analiza el texto y devuelve scores para cada contexto.
        
        Returns:
            Dict con scores 0-1 para: historical, action, dramatic, calm, emotional
        """
        text_lower = text.lower()
        
        scores = {
            'historical': cls._count_keywords(text_lower, cls.HISTORICAL_KEYWORDS),
            'action': cls._count_keywords(text_lower, cls.ACTION_KEYWORDS),
            'dramatic': cls._count_keywords(text_lower, cls.DRAMATIC_KEYWORDS),
            'calm': cls._count_keywords(text_lower, cls.CALM_KEYWORDS),
            'emotional': cls._count_keywords(text_lower, cls.EMOTIONAL_KEYWORDS)
        }
        
        # Normalizar scores
        total = sum(scores.values())
        if total > 0:
            scores = {k: v / total for k, v in scores.items()}
        
        return scores
    
    @staticmethod
    def _count_keywords(text: str, keywords: List[str]) -> float:
        """Cuenta apariciones de palabras clave"""
        count = 0
        for keyword in keywords:
            count += text.count(keyword)
        return float(count)
    
    @classmethod
    def suggest_filter(cls, text: str) -> FilterType:
        """Sugiere un filtro basado en el contexto del texto"""
        scores = cls.detect_context(text)
        
        # Obtener contexto dominante
        dominant = max(scores, key=scores.get)
        score = scores[dominant]
        
        # Si no hay contexto claro, sin filtro
        if score < 0.3:
            return FilterType.NONE
        
        # Mapeo contexto  filtro
        filter_map = {
            'historical': FilterType.SEPIA,
            'action': FilterType.DRAMATIC,
            'dramatic': FilterType.NOIR,
            'calm': FilterType.CINEMATIC,
            'emotional': FilterType.WARM
        }
        
        return filter_map.get(dominant, FilterType.NONE)
    
    @classmethod
    def suggest_movement(cls, text: str, duration: float) -> MovementType:
        """Sugiere un movimiento basado en el contexto y duración"""
        scores = cls.detect_context(text)
        dominant = max(scores, key=scores.get)
        
        # Movimientos según contexto
        if dominant == 'action' or duration < 3:
            # Acción: movimientos rápidos
            return random.choice([
                MovementType.ZOOM_IN,
                MovementType.PAN_RIGHT,
                MovementType.DIAGONAL_RT
            ])
        elif dominant == 'dramatic':
            # Dramático: zoom lento
            return random.choice([
                MovementType.ZOOM_IN,
                MovementType.PAN_ZOOM_IN
            ])
        elif dominant == 'calm':
            # Calma: movimientos suaves
            return random.choice([
                MovementType.PAN_LEFT,
                MovementType.PAN_RIGHT,
                MovementType.STATIC
            ])
        else:
            # Por defecto: variedad
            return random.choice([
                MovementType.ZOOM_IN,
                MovementType.PAN_RIGHT,
                MovementType.PAN_LEFT,
                MovementType.PAN_ZOOM_IN
            ])
    
    @classmethod
    def suggest_transition(cls, from_text: str, to_text: str, 
                          from_duration: float, to_duration: float) -> Tuple[TransitionType, float]:
        """
        Sugiere una transición entre dos clips basada en su contexto.
        
        Returns:
            (tipo_transicion, duracion_en_segundos)
        """
        from_scores = cls.detect_context(from_text)
        to_scores = cls.detect_context(to_text)
        
        # Calcular cambio de contexto
        context_change = sum(abs(from_scores.get(k, 0) - to_scores.get(k, 0)) 
                            for k in from_scores.keys())
        
        # Duración promedio de clips
        avg_duration = (from_duration + to_duration) / 2
        
        # Clips muy cortos  corte directo
        if avg_duration < 3:
            return TransitionType.CUT, 0.0
        
        # Cambio drástico de contexto  transición más marcada
        if context_change > 0.6:
            return random.choice([
                (TransitionType.FADE, 0.5),
                (TransitionType.DISSOLVE, 0.4),
                (TransitionType.WIPE_RIGHT, 0.3)
            ])
        
        # Cambio moderado  fundido suave
        elif context_change > 0.3:
            return TransitionType.CROSSFADE, 0.3
        
        # Sin cambio  corte o fundido rápido
        else:
            return random.choice([
                (TransitionType.CUT, 0.0),
                (TransitionType.FADE, 0.2)
            ])


class CameraMovement:
    """
    Genera movimientos de cámara (Pan & Zoom) para el efecto Ken Burns.
    """
    
    @staticmethod
    def calculate_positions(movement_type: MovementType,
                           video_size: Tuple[int, int],
                           zoom_factor: float = 1.2) -> Dict:
        """
        Calcula posiciones de inicio y fin para el movimiento.
        
        Args:
            movement_type: Tipo de movimiento
            video_size: (ancho, alto) del video
            zoom_factor: Factor de zoom (1.0 = sin zoom, 1.3 = 30% más grande)
        
        Returns:
            Dict con 'start' y 'end', cada uno con 'scale', 'x', 'y'
        """
        w, h = video_size
        
        # Posiciones por defecto (centro, sin zoom)
        default_pos = {'scale': 1.0, 'x': w//2, 'y': h//2}
        
        movements = {
            MovementType.STATIC: {
                'start': default_pos.copy(),
                'end': default_pos.copy()
            },
            
            MovementType.ZOOM_IN: {
                'start': {'scale': 1.0, 'x': w//2, 'y': h//2},
                'end': {'scale': zoom_factor, 'x': w//2, 'y': h//2}
            },
            
            MovementType.ZOOM_OUT: {
                'start': {'scale': zoom_factor, 'x': w//2, 'y': h//2},
                'end': {'scale': 1.0, 'x': w//2, 'y': h//2}
            },
            
            MovementType.PAN_LEFT: {
                'start': {'scale': 1.0, 'x': int(w * 0.6), 'y': h//2},
                'end': {'scale': 1.0, 'x': int(w * 0.4), 'y': h//2}
            },
            
            MovementType.PAN_RIGHT: {
                'start': {'scale': 1.0, 'x': int(w * 0.4), 'y': h//2},
                'end': {'scale': 1.0, 'x': int(w * 0.6), 'y': h//2}
            },
            
            MovementType.PAN_UP: {
                'start': {'scale': 1.0, 'x': w//2, 'y': int(h * 0.6)},
                'end': {'scale': 1.0, 'x': w//2, 'y': int(h * 0.4)}
            },
            
            MovementType.PAN_DOWN: {
                'start': {'scale': 1.0, 'x': w//2, 'y': int(h * 0.4)},
                'end': {'scale': 1.0, 'x': w//2, 'y': int(h * 0.6)}
            },
            
            MovementType.PAN_ZOOM_IN: {
                'start': {'scale': 1.0, 'x': int(w * 0.4), 'y': h//2},
                'end': {'scale': zoom_factor, 'x': int(w * 0.6), 'y': h//2}
            },
            
            MovementType.DIAGONAL_LT: {
                'start': {'scale': 1.0, 'x': int(w * 0.6), 'y': int(h * 0.6)},
                'end': {'scale': zoom_factor, 'x': int(w * 0.4), 'y': int(h * 0.4)}
            },
            
            MovementType.DIAGONAL_RT: {
                'start': {'scale': 1.0, 'x': int(w * 0.4), 'y': int(h * 0.6)},
                'end': {'scale': zoom_factor, 'x': int(w * 0.6), 'y': int(h * 0.4)}
            },
            
            MovementType.DIAGONAL_LB: {
                'start': {'scale': 1.0, 'x': int(w * 0.6), 'y': int(h * 0.4)},
                'end': {'scale': zoom_factor, 'x': int(w * 0.4), 'y': int(h * 0.6)}
            },
            
            MovementType.DIAGONAL_RB: {
                'start': {'scale': 1.0, 'x': int(w * 0.4), 'y': int(h * 0.4)},
                'end': {'scale': zoom_factor, 'x': int(w * 0.6), 'y': int(h * 0.6)}
            }
        }
        
        return movements.get(movement_type, movements[MovementType.STATIC])
    
    @staticmethod
    def generate_moviepy_resize_lambda(positions: Dict, duration: float):
        """
        Genera función lambda para MoviePy que implementa el movimiento.
        
        Args:
            positions: Dict con 'start' y 'end' del movimiento
            duration: Duración del clip en segundos
        
        Returns:
            Lambda function para usar con clip.resize()
        """
        start_scale = positions['start']['scale']
        end_scale = positions['end']['scale']
        start_x = positions['start']['x']
        end_x = positions['end']['x']
        start_y = positions['start']['y']
        end_y = positions['end']['y']
        
        def resize_func(t):
            # Progreso lineal 0 a 1
            progress = t / duration if duration > 0 else 0
            
            # Interpolación de valores
            scale = start_scale + (end_scale - start_scale) * progress
            x = int(start_x + (end_x - start_x) * progress)
            y = int(start_y + (end_y - start_y) * progress)
            
            return scale
        
        return resize_func


class FilterEngine:
    """
    Aplica filtros cinematográficos a clips de MoviePy.
    """
    
    @staticmethod
    def apply_filter(clip, filter_type: FilterType):
        """
        Aplica un filtro al clip.
        
        Args:
            clip: Clip de MoviePy
            filter_type: Tipo de filtro a aplicar
        
        Returns:
            Clip con filtro aplicado
        """
        from moviepy.editor import VideoFileClip
        from moviepy.video.fx import all as vfx
        
        if filter_type == FilterType.NONE:
            return clip
        
        elif filter_type == FilterType.BLACK_WHITE:
            return clip.fx(vfx.blackwhite)
        
        elif filter_type == FilterType.SEPIA:
            # Sepia = B&W + tinte marrón
            bw = clip.fx(vfx.blackwhite)
            # Multiplicar por color sepia (rgb)
            return bw.fx(vfx.colorx, 1.1).fx(vfx.lum_contrast, lum=0, contrast=0.2)
        
        elif filter_type == FilterType.COOL:
            # Tonos fríos (más azul)
            return clip.fx(vfx.colorx, 0.9).fl_image(
                lambda img: FilterEngine._apply_color_tint(img, (0.9, 1.0, 1.1))
            )
        
        elif filter_type == FilterType.WARM:
            # Tonos cálidos (más naranja/rojo)
            return clip.fl_image(
                lambda img: FilterEngine._apply_color_tint(img, (1.1, 1.0, 0.9))
            )
        
        elif filter_type == FilterType.DRAMATIC:
            # Alto contraste
            return clip.fx(vfx.lum_contrast, lum=0, contrast=0.5)
        
        elif filter_type == FilterType.VINTAGE:
            # Desaturado + leve vignette
            return clip.fx(vfx.colorx, 0.8).fx(vfx.lum_contrast, lum=-10, contrast=0.2)
        
        elif filter_type == FilterType.NOIR:
            # B&W + alto contraste
            return clip.fx(vfx.blackwhite).fx(vfx.lum_contrast, lum=0, contrast=0.6)
        
        elif filter_type == FilterType.CINEMATIC:
            # Look cinematográfico (leve desaturación + contraste)
            return clip.fx(vfx.colorx, 0.9).fx(vfx.lum_contrast, lum=-5, contrast=0.3)
        
        elif filter_type == FilterType.VIGNETTE:
            # Viñeta (bordes oscuros)
            return clip.fl_image(FilterEngine._apply_vignette)
        
        return clip
    
    @staticmethod
    def _apply_color_tint(image, rgb_factors):
        """Aplica tinte de color multiplicando canales RGB"""
        import numpy as np
        result = image.copy().astype(float)
        result[:, :, 0] *= rgb_factors[0]  # R
        result[:, :, 1] *= rgb_factors[1]  # G
        result[:, :, 2] *= rgb_factors[2]  # B
        return np.clip(result, 0, 255).astype('uint8')
    
    @staticmethod
    def _apply_vignette(image):
        """Aplica efecto viñeta (oscurece bordes)"""
        import numpy as np
        from scipy.ndimage import gaussian_filter
        
        h, w = image.shape[:2]
        
        # Crear máscara radial
        Y, X = np.ogrid[:h, :w]
        center_y, center_x = h // 2, w // 2
        
        # Distancia desde el centro
        dist = np.sqrt((X - center_x)**2 + (Y - center_y)**2)
        max_dist = np.sqrt(center_x**2 + center_y**2)
        
        # Máscara (1 en el centro, 0 en los bordes)
        mask = 1 - (dist / max_dist) ** 2
        mask = gaussian_filter(mask, sigma=max(h, w) * 0.1)
        mask = np.clip(mask, 0.3, 1.0)  # No oscurecer totalmente
        
        # Aplicar máscara a cada canal
        result = image.copy().astype(float)
        for i in range(3):
            result[:, :, i] *= mask
        
        return np.clip(result, 0, 255).astype('uint8')


class CinematicEffectsEngine:
    """
    Motor principal que orquesta todos los efectos cinematográficos.
    """
    
    def __init__(self, video_size: Tuple[int, int] = (1920, 1080)):
        self.video_size = video_size
        self.context_detector = ContextDetector()
    
    def apply_effects_to_segment(self,
                                 clip,
                                 segment_text: str,
                                 duration: float,
                                 auto_detect: bool = True,
                                 force_movement: Optional[MovementType] = None,
                                 force_filter: Optional[FilterType] = None) -> object:
        """
        Aplica efectos cinematográficos a un clip basándose en su contexto.
        
        Args:
            clip: Clip de MoviePy
            segment_text: Texto del segmento (para detección de contexto)
            duration: Duración del clip
            auto_detect: Si True, detecta contexto automáticamente
            force_movement: Forzar un movimiento específico
            force_filter: Forzar un filtro específico
        
        Returns:
            Clip con efectos aplicados
        """
        
        # 1. Determinar movimiento
        if force_movement:
            movement = force_movement
        elif auto_detect:
            movement = self.context_detector.suggest_movement(segment_text, duration)
        else:
            movement = MovementType.ZOOM_IN
        
        # 2. Aplicar movimiento (Pan & Zoom)
        if movement != MovementType.STATIC:
            positions = CameraMovement.calculate_positions(
                movement,
                self.video_size,
                zoom_factor=1.2
            )
            
            # Aplicar resize animado
            resize_func = CameraMovement.generate_moviepy_resize_lambda(
                positions,
                duration
            )
            
            clip = clip.resize(resize_func)
        
        # 3. Determinar filtro
        if force_filter:
            filter_type = force_filter
        elif auto_detect:
            filter_type = self.context_detector.suggest_filter(segment_text)
        else:
            filter_type = FilterType.NONE
        
        # 4. Aplicar filtro
        if filter_type != FilterType.NONE:
            clip = FilterEngine.apply_filter(clip, filter_type)
        
        return clip
    
    def get_transition_between_clips(self,
                                     from_clip,
                                     to_clip,
                                     from_text: str,
                                     to_text: str,
                                     from_duration: float,
                                     to_duration: float,
                                     auto_detect: bool = True) -> Tuple[object, object, Optional[object]]:
        """
        Genera transición inteligente entre dos clips.
        
        Args:
            from_clip: Clip saliente
            to_clip: Clip entrante
            from_text: Texto del clip saliente
            to_text: Texto del clip entrante
            from_duration: Duración del clip saliente
            to_duration: Duración del clip entrante
            auto_detect: Si True, detecta transición automáticamente
        
        Returns:
            (clip1_modified, clip2_modified, transition_clip)
        """
        
        if auto_detect:
            transition_type, transition_duration = self.context_detector.suggest_transition(
                from_text, to_text, from_duration, to_duration
            )
        else:
            transition_type = TransitionType.FADE
            transition_duration = 0.3
        
        # Aplicar transición según tipo
        if transition_type == TransitionType.CUT:
            # Sin transición
            return from_clip, to_clip, None
        
        elif transition_type == TransitionType.FADE:
            # Fadeout en from_clip, fadein en to_clip
            from moviepy.editor import concatenate_videoclips
            from_clip = from_clip.fadeout(transition_duration)
            to_clip = to_clip.fadein(transition_duration)
            return from_clip, to_clip, None
        
        elif transition_type == TransitionType.CROSSFADE:
            # Fundido cruzado
            from moviepy.editor import CompositeVideoClip
            # Overlap de transition_duration segundos
            to_clip = to_clip.set_start(from_duration - transition_duration)
            to_clip = to_clip.fadein(transition_duration)
            from_clip = from_clip.fadeout(transition_duration)
            return from_clip, to_clip, None
        
        # Por defecto, fade simple
        from_clip = from_clip.fadeout(transition_duration)
        to_clip = to_clip.fadein(transition_duration)
        return from_clip, to_clip, None


# ========== FUNCIONES DE UTILIDAD ==========

def demo_context_detection():
    """Demo de detección de contexto"""
    print(" Demo: Detección de Contexto\n")
    
    test_texts = [
        "En el año 1920, la historia cambió para siempre",
        "La batalla fue rápida y violenta, llena de acción",
        "El misterio oscuro envolvía la noche dramática",
        "La tranquila playa ofrecía paz y serenidad",
        "El amor verdadero conquista todos los corazones"
    ]
    
    detector = ContextDetector()
    
    for text in test_texts:
        print(f"Texto: {text}")
        scores = detector.detect_context(text)
        dominant = max(scores, key=scores.get)
        print(f"  Contexto: {dominant} ({scores[dominant]:.2f})")
        
        filter_suggested = detector.suggest_filter(text)
        movement_suggested = detector.suggest_movement(text, 5.0)
        
        print(f"  Filtro sugerido: {filter_suggested.value}")
        print(f"  Movimiento sugerido: {movement_suggested.value}")
        print()


if __name__ == "__main__":
    print(" Cinematic Effects Engine")
    print("=" * 60)
    demo_context_detection()