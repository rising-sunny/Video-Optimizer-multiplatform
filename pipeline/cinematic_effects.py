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
from typing import List, Dict, Tuple, Optional
from enum import Enum
import re

# Todo lo de este modulo es resize sobre clips de moviepy, y moviepy 1.0.3 usa
# Image.ANTIALIAS, que Pillow >= 10 elimino. Sin este shim cada efecto levanta
# AttributeError y los stills quedan congelados. Se importa aca ademas de en
# video_assembler para que el modulo funcione sea cual sea el orden de imports.
from infra import moviepy_pillow_compat  # noqa: F401


# Colchon de zoom minimo para cualquier movimiento. Un paneo sobre una imagen
# a escala 1.0 no tiene pixeles de sobra: o no se mueve, o muestra negro.
PAN_HEADROOM_SCALE = 1.15

# Cuanto se agranda el input antes del zoompan de FFmpeg. x/y se cuantizan a
# pixeles enteros del input: sin supersampling un paneo lento avanza a saltos
# visibles. 2 alcanza para que el salto quede en ~medio pixel de salida.
FFMPEG_MOTION_SUPERSAMPLE = 2


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


def filter_for_preset(preset):
    """Translate Studio labels into an explicit filter; auto retains detection."""
    key = str(preset or 'auto').strip().lower().split(' ', 1)[0]
    return {'noir': FilterType.NOIR, 'vintage': FilterType.SEPIA,
            'minimal': FilterType.NONE, 'documentary': FilterType.CINEMATIC,
            'action': FilterType.DRAMATIC}.get(key)


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

        positions = movements.get(movement_type, movements[MovementType.STATIC])

        # Colchon de zoom para los paneos. Un paneo con scale=1.0 no tiene de
        # donde sacar pixeles: o no se mueve (era el caso) o deja bordes negros.
        # Se le suma a AMBOS extremos para no alterar el recorrido del zoom.
        if movement_type != MovementType.STATIC:
            min_scale = min(positions['start']['scale'], positions['end']['scale'])
            deficit = PAN_HEADROOM_SCALE - min_scale
            if deficit > 0:
                positions = {
                    'start': dict(positions['start']),
                    'end': dict(positions['end']),
                }
                positions['start']['scale'] += deficit
                positions['end']['scale'] += deficit

        return positions

    @staticmethod
    def build_ffmpeg_motion_filter(positions: Dict, frames: int,
                                   video_size: Tuple[int, int],
                                   supersample: int = FFMPEG_MOTION_SUPERSAMPLE,
                                   fps: float = 30) -> str:
        """Traduce un recorrido de camara a un filtro `zoompan` de FFmpeg.

        Misma matematica que `apply_movement` (el punto (x, y) del recorrido
        termina en el centro del cuadro, con clamp para no mostrar negro), pero
        resuelta en C dentro de FFmpeg en vez de cuadro a cuadro en Python.

        Semantica de zoompan (verificada empiricamente, es facil de confundir):
        `zoom` multiplica el input igual que nuestra `scale`, y `x`/`y` son la
        esquina superior izquierda de la ventana visible EN COORDENADAS DEL
        INPUT (no del input ya zoomeado); esa ventana mide iw/zoom x ih/zoom y
        despues se escala a `s`.

        `supersample` agranda el input antes del zoompan: x/y se cuantizan a
        pixeles enteros del input, asi que sin esto un paneo lento avanza a
        saltos de un pixel de salida. Con SS el salto pasa a ser zoom/SS.

        IMPORTANTE: la progresion usa `on` (cuadro de SALIDA). Con `in` -- que
        es lo que habia -- una imagen fija nunca avanza y el efecto no se ve.

        `fps` tiene que ser el del video: zoompan sale a 25 por defecto y al
        pasarlo a 30 repite un cuadro de cada seis y corta el recorrido.
        """
        w, h = int(video_size[0]), int(video_size[1])
        ss = max(1, int(supersample))
        n = max(1, int(frames))

        s0 = float(positions['start']['scale'])
        s1 = float(positions['end']['scale'])
        x0, x1 = float(positions['start']['x']), float(positions['end']['x'])
        y0, y1 = float(positions['start']['y']), float(positions['end']['y'])

        # Progreso 0..1 a lo largo del clip.
        p = "0" if n <= 1 else f"(on/{n - 1})"

        z_expr = f"{s0:.5f}+({s1 - s0:.5f})*{p}"
        # Centro del recorrido en coordenadas del input supersampleado.
        cx = f"{x0 * ss:.3f}+({(x1 - x0) * ss:.3f})*{p}"
        cy = f"{y0 * ss:.3f}+({(y1 - y0) * ss:.3f})*{p}"
        # Esquina de la ventana, recortada al area valida (sin franjas negras).
        x_expr = f"clip({cx}-iw/(2*zoom),0,iw-iw/zoom)"
        y_expr = f"clip({cy}-ih/(2*zoom),0,ih-ih/zoom)"

        chain = ""
        if ss > 1:
            chain += f"scale={w * ss}:{h * ss}:flags=bicubic,"
        chain += (
            f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
            f":d={n}:s={w}x{h}:fps={float(fps):g}"
        )
        return chain

    @staticmethod
    def apply_movement(clip, positions: Dict, duration: float,
                       video_size: Tuple[int, int]):
        """Ken Burns real: zoom Y paneo, con el lienzo fijo en video_size.

        El camino viejo hacia `clip.resize(func)` con una lambda que devolvia
        SOLO la escala: los paneos (scale 1.0 -> 1.0) no hacian nada, y los
        zooms devolvian un clip cada vez mas grande que el lienzo, que la
        composicion recortaba desde la esquina en vez del centro.

        Aca el clip ampliado se reposiciona cuadro a cuadro para que el punto
        (x, y) del recorrido caiga en el centro del frame, y el resultado se
        compone sobre un lienzo del tamano exacto del video.
        """
        from moviepy.editor import CompositeVideoClip

        w, h = video_size
        s0, s1 = positions['start']['scale'], positions['end']['scale']
        x0, x1 = float(positions['start']['x']), float(positions['end']['x'])
        y0, y1 = float(positions['start']['y']), float(positions['end']['y'])

        def _progress(t):
            if not duration or duration <= 0:
                return 0.0
            return min(1.0, max(0.0, float(t) / duration))

        def scale_at(t):
            return s0 + (s1 - s0) * _progress(t)

        def position_at(t):
            p = _progress(t)
            s = scale_at(t)
            cx = x0 + (x1 - x0) * p
            cy = y0 + (y1 - y0) * p
            # Llevar el punto (cx, cy) del original al centro del lienzo.
            px = w / 2.0 - cx * s
            py = h / 2.0 - cy * s
            # Clamp: la imagen ampliada nunca puede despegarse de los bordes,
            # asi no aparecen franjas negras aunque el recorrido sea agresivo.
            px = min(0.0, max(w - w * s, px))
            py = min(0.0, max(h - h * s, py))
            return (px, py)

        moving = clip.resize(scale_at).set_position(position_at)
        composed = CompositeVideoClip([moving], size=(w, h))
        if clip.duration:
            composed = composed.set_duration(clip.duration)
        return composed

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
    
    def __init__(self, video_size: Tuple[int, int] = (1920, 1080), level: str = "auto"):
        self.video_size = video_size
        self.level = level
        self.context_detector = ContextDetector()

    @staticmethod
    def movement_for_plan(plan: Optional[Dict]) -> Optional[MovementType]:
        """Map the shared direction plan to the closest MoviePy movement."""
        if not plan:
            return None
        return {
            "slow_drift": MovementType.PAN_RIGHT,
            "drift_left": MovementType.PAN_LEFT,
            "drift_right": MovementType.PAN_RIGHT,
            "depth_push": MovementType.PAN_ZOOM_IN,
            "macro_reveal": MovementType.ZOOM_OUT,
            "lateral_reveal": MovementType.PAN_RIGHT,
            "crash_zoom": MovementType.ZOOM_IN,
            "map_dive": MovementType.ZOOM_IN,
            "pull_back": MovementType.ZOOM_OUT,
        }.get(str(plan.get("camera") or ""))
    
    def apply_effects_to_segment(self,
                                 clip,
                                 segment_text: str,
                                 duration: float,
                                 auto_detect: bool = True,
                                 force_movement: Optional[MovementType] = None,
                                 force_filter: Optional[FilterType] = None,
                                 cinematic_plan: Optional[Dict] = None) -> object:
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
        planned_movement = self.movement_for_plan(cinematic_plan)
        if force_movement:
            movement = force_movement
        elif planned_movement:
            movement = planned_movement
        elif auto_detect:
            movement = self.context_detector.suggest_movement(segment_text, duration)
        else:
            movement = MovementType.ZOOM_IN
        
        # 2. Aplicar movimiento (Pan & Zoom)
        if movement != MovementType.STATIC:
            raw_strength = (cinematic_plan or {}).get("intensity", 0.65)
            plan_strength = float(0.65 if raw_strength is None else raw_strength)
            positions = CameraMovement.calculate_positions(
                movement,
                self.video_size,
                zoom_factor=1.15 + (0.17 * max(0.0, min(1.0, plan_strength)))
            )
            
            clip = CameraMovement.apply_movement(
                clip,
                positions,
                duration,
                self.video_size
            )
        
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
