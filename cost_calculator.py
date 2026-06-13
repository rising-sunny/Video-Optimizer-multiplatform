# cost_calculator.py
import math

# =============================================================================
# PRECIOS DE API (Estimaciones - Dic 2025)
# =============================================================================
PRICES = {
    # --- IA DE TEXTO & ANÁLISIS ---
    "GEMINI_FLASH_OUTPUT": 0.00018, # Por 1k caracteres
    "GOOGLE_SEARCH": 0.005,         # Por consulta
    
    # --- VOZ ---
    "ELEVENLABS_V2": 0.18,          # Por 1k caracteres (aprox)
    
    # --- TRANSCRIPCIÓN ---
    "WHISPER_API": 0.006,           # Por minuto
    
    # --- VISUALES (EL CAMBIO CLAVE) ---
    # Runway Veo 3.1 Fast: ~$0.05 por segundo de video generado
    "RUNWAY_VIDEO_SEC": 0.05,

    # Fal.ai MiniMax Hailuo Live: ~$0.017 por segundo (text-to-video ~$0.035)
    "FAL_VIDEO_SEC": 0.035,

    # Recraft AI: estimacion media por imagen generada
    "RECRAFT_IMAGE": 0.003
}

# HEURÍSTICA
AVG_SEGMENT_DURATION = 6 # Segundos promedio por escena
VIDEO_CLIP_LEN = 4       # Segundos que genera cada clip de video

class CostCalculator:
    def __init__(self):
        pass

    def calculate_video_cost(self, duration_seconds, use_elevenlabs, use_whisper,
                             visual_mode='mixed', video_provider='fal'):
        """
        Calcula costos basándose en el modo visual elegido:
        - 'static': 100% Imágenes (Recraft)
        - 'mixed': 30% Video + 70% Imágenes (Recraft)

        video_provider: 'fal' (default, mas barato) o 'runway'
        """
        # 1. Cantidad de Recursos
        num_segments = math.ceil(duration_seconds / AVG_SEGMENT_DURATION)
        num_words = (duration_seconds / 60.0) * 150 # 150 words/min
        num_chars = num_words * 6

        # 2. Costos Base (Script, Voz, Subs)
        cost_ia_text = (PRICES["GOOGLE_SEARCH"] * 1) + (num_chars/1000 * PRICES["GEMINI_FLASH_OUTPUT"] * 2)

        cost_voice = (num_chars/1000 * PRICES["ELEVENLABS_V2"]) if use_elevenlabs else 0.0
        cost_subs = (duration_seconds/60.0 * PRICES["WHISPER_API"]) if use_whisper else 0.0

        # Precio por segundo segun proveedor de video
        video_price_key = "FAL_VIDEO_SEC" if video_provider == 'fal' else "RUNWAY_VIDEO_SEC"
        video_price_per_sec = PRICES[video_price_key]
        video_label = "Fal.ai" if video_provider == 'fal' else "Runway"

        # 3. Costos Visuales
        cost_visuals = 0.0
        details_visuals = ""

        if visual_mode == 'static':
            cost_visuals = num_segments * PRICES["RECRAFT_IMAGE"]
            details_visuals = f"{num_segments} Imgs (Recraft)"

        elif visual_mode == 'mixed':
            num_videos = math.ceil(num_segments * 0.3)
            num_images = num_segments - num_videos

            cost_video = num_videos * VIDEO_CLIP_LEN * video_price_per_sec
            cost_recraft = num_images * PRICES["RECRAFT_IMAGE"]

            cost_visuals = cost_video + cost_recraft
            details_visuals = f"{num_videos} Vids ({video_label}) + {num_images} Imgs (Recraft)"

        # 4. Totales
        cost_processing = cost_ia_text + cost_visuals
        total_cost = cost_voice + cost_subs + cost_processing

        return {
            'total_cost_formatted': f"${total_cost:.4f}",
            'note': f"Modo Visual: {visual_mode.upper()} ({video_label})",
            'costs': {
                'voice': {'service': 'ElevenLabs' if use_elevenlabs else 'gTTS', 'cost': cost_voice},
                'subtitles': {'cost': cost_subs},
                'processing': {'cost': cost_processing, 'time_minutes': math.ceil(num_segments * 0.5)}
            },
            'resources_used': {
                'words': int(num_words),
                'videos': details_visuals,
                'seconds_video': 0
            }
        }

    def compare_configurations(self, duration):
        static = self.calculate_video_cost(duration, True, True, 'static')
        mixed_fal = self.calculate_video_cost(duration, True, True, 'mixed', 'fal')
        mixed_runway = self.calculate_video_cost(duration, True, True, 'mixed', 'runway')

        return {
            'comparison_text': f"""
COMPARACIÓN DE MODOS VISUALES ({duration}s)

1. MODO ESTÁTICO (Solo Imágenes Recraft)
   - Costo Total: {static['total_cost_formatted']}
   - Visuales: {static['resources_used']['videos']}
   - Ideal para: Documentales, Historias Narradas, Presupuesto Bajo.

2. MODO MIXTO - Fal.ai (Más Barato)
   - Costo Total: {mixed_fal['total_cost_formatted']}
   - Visuales: {mixed_fal['resources_used']['videos']}
   - Ideal para: Produccion frecuente, Presupuesto Medio.

3. MODO MIXTO - Runway (Premium)
   - Costo Total: {mixed_runway['total_cost_formatted']}
   - Visuales: {mixed_runway['resources_used']['videos']}
   - Ideal para: Trailers, Intros impactantes, Contenido Viral.
"""
        }
