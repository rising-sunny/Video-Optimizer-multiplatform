# glitch_transitions.py
"""
Transiciones de Estilo CapCut - Efectos Glitch Profesionales
----------------------------------------------------------------
Implementa transiciones tipo glitch de alta calidad similares a CapCut:
- Digital Glitch: Distorsión digital con bloques de color
- RGB Split: Separación de canales RGB
- Data Mosh: Efecto de corrupción de datos
- Pixel Sort: Clasificación de píxeles
- Chromatic Aberration: Aberración cromática
- Freeze Frame + Glitch: Congelación + distorsión
- Wave Distortion: Distorsión de onda digital
"""

import numpy as np
import random
from typing import List, Dict, Tuple, Optional
from enum import Enum
import math


class GlitchTransitionType(Enum):
    """Tipos de transiciones glitch estilo CapCut"""
    DIGITAL_GLITCH = "digital_glitch"          # Distorsión digital con bloques
    RGB_SPLIT = "rgb_split"                    # Separación RGB
    DATA_MOSH = "data_mosh"                    # Corrupción de datos
    PIXEL_SORT = "pixel_sort"                  # Clasificación de píxeles
    CHROMATIC_ABERRATION = "chromatic_aberration"  # Aberración cromática
    FREEZE_GLITCH = "freeze_glitch"            # Congelación + glitch
    WAVE_DISTORTION = "wave_distortion"        # Distorsión de onda
    BLOCK_GLITCH = "block_glitch"              # Bloques desalineados
    NOISE_INTERFERENCE = "noise_interference"  # Interferencia de ruido
    SCAN_LINES = "scan_lines"                  # Líneas de escaneo


class GlitchIntensity(Enum):
    """Niveles de intensidad del glitch"""
    SUBTLE = "subtle"          # Sutil, barely noticeable
    MODERATE = "moderate"      # Moderado, noticeable but not overwhelming
    INTENSE = "intense"        # Intenso, strong effect
    EXTREME = "extreme"        # Extremo, very aggressive


class GlitchTransitionEngine:
    """
    Motor principal para generar transiciones glitch estilo CapCut.
    """
    
    def __init__(self, resolution: Tuple[int, int] = (1920, 1080)):
        """
        Inicializa el motor de transiciones glitch.
        
        Args:
            resolution: Resolución del video (ancho, alto)
        """
        self.resolution = resolution
        self.width, self.height = resolution
        
        # Parámetros preconfigurados para diferentes intensidades
        self.intensity_params = {
            GlitchIntensity.SUBTLE: {
                'block_size': (4, 8),
                'offset_range': 2,
                'noise_level': 0.02,
                'rgb_offset': 2,
                'pixel_sort_threshold': 0.1
            },
            GlitchIntensity.MODERATE: {
                'block_size': (8, 16),
                'offset_range': 5,
                'noise_level': 0.05,
                'rgb_offset': 4,
                'pixel_sort_threshold': 0.2
            },
            GlitchIntensity.INTENSE: {
                'block_size': (16, 32),
                'offset_range': 10,
                'noise_level': 0.1,
                'rgb_offset': 8,
                'pixel_sort_threshold': 0.3
            },
            GlitchIntensity.EXTREME: {
                'block_size': (32, 64),
                'offset_range': 20,
                'noise_level': 0.2,
                'rgb_offset': 16,
                'pixel_sort_threshold': 0.4
            }
        }
    
    def apply_glitch_transition(self, 
                               frame: np.ndarray, 
                               progress: float, 
                               transition_type: GlitchTransitionType,
                               intensity: GlitchIntensity = GlitchIntensity.MODERATE) -> np.ndarray:
        """
        Aplica una transición glitch a un frame.
        
        Args:
            frame: Frame del video (numpy array HxWx3)
            progress: Progreso de la transición (0.0 a 1.0)
            transition_type: Tipo de transición glitch
            intensity: Intensidad del efecto
            
        Returns:
            Frame con efecto aplicado
        """
        if frame is None or frame.size == 0:
            return frame
            
        frame = np.asarray(frame)
        if frame.ndim == 2:
            frame = np.stack([frame, frame, frame], axis=-1)
        elif frame.ndim == 3 and frame.shape[2] == 1:
            frame = np.repeat(frame, 3, axis=2)
        elif frame.ndim == 3 and frame.shape[2] > 3:
            frame = frame[:, :, :3]

        frame = np.ascontiguousarray(frame)
        # Obtener parámetros según intensidad
        params = self.intensity_params[intensity]
        
        # Aplicar efecto según tipo
        if transition_type == GlitchTransitionType.DIGITAL_GLITCH:
            return self._digital_glitch(frame, progress, params)
        elif transition_type == GlitchTransitionType.RGB_SPLIT:
            return self._rgb_split(frame, progress, params)
        elif transition_type == GlitchTransitionType.DATA_MOSH:
            return self._data_mosh(frame, progress, params)
        elif transition_type == GlitchTransitionType.PIXEL_SORT:
            return self._pixel_sort(frame, progress, params)
        elif transition_type == GlitchTransitionType.CHROMATIC_ABERRATION:
            return self._chromatic_aberration(frame, progress, params)
        elif transition_type == GlitchTransitionType.FREEZE_GLITCH:
            return self._freeze_glitch(frame, progress, params)
        elif transition_type == GlitchTransitionType.WAVE_DISTORTION:
            return self._wave_distortion(frame, progress, params)
        elif transition_type == GlitchTransitionType.BLOCK_GLITCH:
            return self._block_glitch(frame, progress, params)
        elif transition_type == GlitchTransitionType.NOISE_INTERFERENCE:
            return self._noise_interference(frame, progress, params)
        elif transition_type == GlitchTransitionType.SCAN_LINES:
            return self._scan_lines(frame, progress, params)
        else:
            return frame
    
    def _digital_glitch(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Efecto glitch digital con bloques desalineados"""
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Intensidad basada en progreso (máximo en 0.5)
        intensity = math.sin(progress * math.pi) * 0.8 + 0.2
        
        # Número de bloques glitch basado en intensidad
        num_blocks = int(intensity * 20)
        
        for _ in range(num_blocks):
            # Tamaño aleatorio del bloque
            block_h = random.randint(*params['block_size'])
            block_w = random.randint(*params['block_size'])
            
            # Posición aleatoria
            y = random.randint(0, h - block_h)
            x = random.randint(0, w - block_w)
            
            # Offset aleatorio
            offset_y = random.randint(-params['offset_range'], params['offset_range'])
            offset_x = random.randint(-params['offset_range'], params['offset_range'])
            
            # Extraer bloque
            block = result[y:y+block_h, x:x+block_w].copy()
            
            # Aplicar offset con wrap-around
            new_y = (y + offset_y) % h
            new_x = (x + offset_x) % w
            
            # Asegurar que el bloque quepa en la nueva posición
            if new_y + block_h <= h and new_x + block_w <= w:
                result[new_y:new_y+block_h, new_x:new_x+block_w] = block
                
                # Efecto de color aleatorio en el bloque
                if random.random() < 0.3:
                    color_shift = random.choice([
                        [1.2, 0.8, 0.8],  # Rojizo
                        [0.8, 1.2, 0.8],  # Verdoso
                        [0.8, 0.8, 1.2],  # Azulado
                    ])
                    result[new_y:new_y+block_h, new_x:new_x+block_w] = \
                        np.clip(result[new_y:new_y+block_h, new_x:new_x+block_w] * color_shift, 0, 255)
        
        return result.astype(np.uint8)
    
    def _rgb_split(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Separación de canales RGB"""
        h, w = frame.shape[:2]
        result = np.zeros_like(frame)
        
        # Offset máximo basado en progreso
        max_offset = int(params['rgb_offset'] * math.sin(progress * math.pi))
        
        # Separar canales
        r_channel = frame[:, :, 0]
        g_channel = frame[:, :, 1]
        b_channel = frame[:, :, 2]
        
        # Aplicar offsets diferentes a cada canal
        r_offset = random.randint(-max_offset, max_offset)
        g_offset = random.randint(-max_offset//2, max_offset//2)
        b_offset = random.randint(-max_offset, max_offset)
        
        # Desplazar canales
        result[:, :, 0] = np.roll(r_channel, r_offset, axis=1)
        result[:, :, 1] = np.roll(g_channel, g_offset, axis=0)
        result[:, :, 2] = np.roll(b_channel, b_offset, axis=1)
        
        # Añadir líneas horizontales aleatorias
        if random.random() < 0.3:
            num_lines = random.randint(1, 5)
            for _ in range(num_lines):
                y = random.randint(0, h-1)
                thickness = random.randint(1, 3)
                result[y:y+thickness, :] = np.roll(result[y:y+thickness, :], 
                                                  random.randint(-10, 10), axis=1)
        
        return result.astype(np.uint8)
    
    def _data_mosh(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Efecto de corrupción de datos (data moshing)"""
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Intensidad basada en progreso
        intensity = math.sin(progress * math.pi)
        
        # Crear bloques corruptos
        num_corrupt_blocks = int(intensity * 15)
        
        for _ in range(num_corrupt_blocks):
            # Tamaño del bloque corrupto
            block_h = random.randint(4, 20)
            block_w = random.randint(4, 20)
            
            # Posición
            y = random.randint(0, h - block_h)
            x = random.randint(0, w - block_w)
            
            # Tipo de corrupción
            corruption_type = random.choice(['pixelate', 'color_shift', 'duplicate'])
            
            if corruption_type == 'pixelate':
                # Pixelar el bloque
                pixel_size = random.randint(2, 8)
                for py in range(0, block_h, pixel_size):
                    for px in range(0, block_w, pixel_size):
                        # Calcular color promedio del bloque de píxeles
                        block_region = result[y+py:min(y+py+pixel_size, h), 
                                           x+px:min(x+px+pixel_size, w)]
                        if block_region.size > 0:
                            avg_color = np.mean(block_region, axis=(0, 1))
                            result[y+py:min(y+py+pixel_size, h), 
                                  x+px:min(x+px+pixel_size, w)] = avg_color
                                  
            elif corruption_type == 'color_shift':
                # Cambiar color del bloque
                shift_factor = random.uniform(0.5, 2.0)
                color_channel = random.randint(0, 2)
                result[y:y+block_h, x:x+block_w, color_channel] = \
                    np.clip(result[y:y+block_h, x:x+block_w, color_channel] * shift_factor, 0, 255)
                    
            elif corruption_type == 'duplicate':
                # Duplicar y desplazar bloque
                if y + block_h * 2 <= h:
                    duplicate_block = result[y:y+block_h, x:x+block_w].copy()
                    result[y+block_h:y+block_h*2, x:x+block_w] = duplicate_block
        
        return result.astype(np.uint8)
    
    def _pixel_sort(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Clasificación de píxeles (pixel sorting)"""
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Intensidad basada en progreso
        intensity = math.sin(progress * math.pi)
        
        # Número de líneas a procesar
        num_lines = int(intensity * 20)
        
        for _ in range(num_lines):
            # Elegir línea aleatoria (horizontal o vertical)
            if random.random() < 0.5:
                # Línea horizontal
                y = random.randint(0, h-1)
                line = result[y, :].copy()
                
                # Ordenar por brillo
                brightness = np.mean(line, axis=1)
                sorted_indices = np.argsort(brightness)
                result[y, :] = line[sorted_indices]
            else:
                # Línea vertical
                x = random.randint(0, w-1)
                line = result[:, x].copy()
                
                # Ordenar por brillo
                brightness = np.mean(line, axis=1)
                sorted_indices = np.argsort(brightness)
                result[:, x] = line[sorted_indices]
        
        return result.astype(np.uint8)
    
    def _chromatic_aberration(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Aberración cromática (separación de colores en los bordes)"""
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Intensidad basada en progreso
        intensity = math.sin(progress * math.pi) * params['rgb_offset']
        
        # Crear máscara de distancia desde el centro
        center_y, center_x = h // 2, w // 2
        Y, X = np.ogrid[:h, :w]
        distance = np.sqrt((X - center_x)**2 + (Y - center_y)**2)
        max_distance = np.sqrt(center_x**2 + center_y**2)
        
        # Normalizar distancia (0 en centro, 1 en bordes)
        distance_normalized = distance / max_distance
        
        # Aplicar separación RGB basada en distancia
        for channel in range(3):
            offset = int(intensity * distance_normalized * (channel + 1) / 3)
            if channel == 0:  # Rojo - desplazar a la derecha
                result[:, :, channel] = np.roll(result[:, :, channel], offset, axis=1)
            elif channel == 2:  # Azul - desplazar a la izquierda
                result[:, :, channel] = np.roll(result[:, :, channel], -offset, axis=1)
        
        return result.astype(np.uint8)
    
    def _freeze_glitch(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Congelación del frame con efectos glitch"""
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Para efecto de congelación, mantenemos partes del frame original
        # y aplicamos glitch en otras áreas
        
        # Intensidad basada en progreso
        intensity = math.sin(progress * math.pi)
        
        # Áreas a congelar (franjas horizontales)
        num_freeze_lines = int(intensity * 10)
        
        for _ in range(num_freeze_lines):
            y = random.randint(0, h-1)
            thickness = random.randint(1, 5)
            
            # Congelar esta línea (copiar de un frame anterior simulado)
            # En implementación real, necesitarías el frame anterior
            # Por ahora, aplicamos un efecto de "congelación" con reducción de color
            freeze_area = result[y:y+thickness, :]
            result[y:y+thickness, :] = np.mean(freeze_area, axis=(1, 2), keepdims=True) * 0.8
        
        # Añadir glitch digital en áreas no congeladas
        glitch_areas = int(intensity * 5)
        for _ in range(glitch_areas):
            y = random.randint(0, h-10)
            x = random.randint(0, w-10)
            block_h = random.randint(2, 8)
            block_w = random.randint(2, 8)
            
            # Desplazar bloque
            offset = random.randint(-params['offset_range'], params['offset_range'])
            if 0 <= y + block_h < h and 0 <= x + block_w < w:
                block = result[y:y+block_h, x:x+block_w].copy()
                new_x = (x + offset) % w
                if new_x + block_w <= w:
                    result[y:y+block_h, new_x:new_x+block_w] = block
        
        return result.astype(np.uint8)
    
    def _wave_distortion(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Distorsión de onda digital"""
        h, w = frame.shape[:2]
        result = np.zeros_like(frame)
        
        # Intensidad basada en progreso
        intensity = math.sin(progress * math.pi)
        amplitude = int(intensity * 20)
        frequency = random.uniform(0.01, 0.05)
        
        for y in range(h):
            # Calcular offset de onda para esta línea
            offset = int(amplitude * math.sin(frequency * y))
            
            # Aplicar offset horizontal
            for x in range(w):
                new_x = (x + offset) % w
                result[y, x] = frame[y, new_x]
        
        return result.astype(np.uint8)
    
    def _block_glitch(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Glitch con bloques desalineados"""
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Intensidad basada en progreso
        intensity = math.sin(progress * math.pi)
        
        # Dividir imagen en bloques
        block_size = random.randint(*params['block_size'])
        
        for y in range(0, h, block_size):
            for x in range(0, w, block_size):
                if random.random() < intensity * 0.3:  # Probabilidad de glitch
                    # Offset aleatorio para este bloque
                    offset_y = random.randint(-params['offset_range'], params['offset_range'])
                    offset_x = random.randint(-params['offset_range'], params['offset_range'])
                    
                    # Extraer bloque
                    block_h = min(block_size, h - y)
                    block_w = min(block_size, w - x)
                    block = result[y:y+block_h, x:x+block_w].copy()
                    
                    # Aplicar offset
                    new_y = max(0, min(h - block_h, y + offset_y))
                    new_x = max(0, min(w - block_w, x + offset_x))
                    
                    result[new_y:new_y+block_h, new_x:new_x+block_w] = block
        
        return result.astype(np.uint8)
    
    def _noise_interference(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Interferencia de ruido digital"""
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Intensidad basada en progreso
        intensity = math.sin(progress * math.pi)
        noise_level = params['noise_level'] * intensity
        
        # Añadir ruido aleatorio
        noise = np.random.random((h, w, 3)) * noise_level * 255
        result = result + noise
        
        # Añadir líneas de interferencia horizontales
        num_lines = int(intensity * 10)
        for _ in range(num_lines):
            y = random.randint(0, h-1)
            thickness = random.randint(1, 2)
            result[y:y+thickness, :] = np.random.random((thickness, w, 3)) * 255
        
        return np.clip(result, 0, 255).astype(np.uint8)
    
    def _scan_lines(self, frame: np.ndarray, progress: float, params: Dict) -> np.ndarray:
        """Líneas de escaneo estilo monitor antiguo"""
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Intensidad basada en progreso
        intensity = math.sin(progress * math.pi)
        
        # Crear líneas de escaneo
        line_spacing = max(2, int(5 - intensity * 3))  # Líneas más juntas con más intensidad
        line_brightness = 0.7 - intensity * 0.3  # Más oscuras con más intensidad
        
        for y in range(0, h, line_spacing):
            result[y:y+1, :] = result[y:y+1, :] * line_brightness
        
        # Añavegación horizontal ocasional
        if random.random() < intensity * 0.3:
            y = random.randint(0, h-1)
            result[y:y+1, :] = np.random.random((1, w, 3)) * 255
        
        return result.astype(np.uint8)
    
    


# Funciones de utilidad para integración con MoviePy


def demo_glitch_effects():
    """Demo de los efectos glitch disponibles"""
    print(" Demo: Transiciones Glitch Estilo CapCut\n")
    
    # Crear frame de prueba
    test_frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    
    engine = GlitchTransitionEngine()
    
    for transition_type in GlitchTransitionType:
        print(f"Probando: {transition_type.value}")
        
        # Aplicar efecto con diferentes progresos
        for progress in [0.25, 0.5, 0.75]:
            result = engine.apply_glitch_transition(
                test_frame, progress, transition_type, GlitchIntensity.MODERATE
            )
            print(f"  Progreso {progress:.2f}: OK")
        
        print()


if __name__ == "__main__":
    print(" Glitch Transitions Engine - CapCut Style")
    print("=" * 60)
    demo_glitch_effects()
