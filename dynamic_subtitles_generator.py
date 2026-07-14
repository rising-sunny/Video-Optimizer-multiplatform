# dynamic_subtitles_generator.py
"""
Generador de SubtÃ­tulos DinÃ¡micos Profesionales
------------------------------------------------
Crea subtÃ­tulos estilo Hormozi/MrBeast con:
- Animaciones palabra por palabra
- Efecto karaoke (resaltado de palabra activa)
- Emojis contextuales automÃ¡ticos
- MÃºltiples estilos predefinidos

Usa formato ASS (Advanced SubStation Alpha) para mÃ¡xima flexibilidad.
"""

import builtins
import difflib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import random


def _safe_print(*args, sep=' ', end='\n', file=None, flush=False):
    """
    Evita que logs con emoji/Unicode rompan la sincronización Whisper en
    consolas Windows con codificaciones limitadas (ej. cp1252).
    """
    target = file if file is not None else sys.stdout
    text = sep.join(str(arg) for arg in args) + end

    try:
        target.write(text)
    except UnicodeEncodeError:
        encoding = getattr(target, 'encoding', None) or 'utf-8'
        sanitized = text.encode(encoding, errors='replace').decode(encoding, errors='replace')
        target.write(sanitized)
    except Exception:
        fallback = sys.__stdout__ or sys.stdout
        builtins.print(text, sep='', end='', file=fallback, flush=flush)
        return

    if flush:
        try:
            target.flush()
        except Exception:
            pass


print = _safe_print


class EmojiMapper:
    """
    Mapea palabras clave a emojis relevantes.
    Se usa para insertar emojis automÃ¡ticamente en los subtÃ­tulos.
    """
    
    EMOJI_MAP = {
        # Emociones
        'increÃ­ble': 'ðŸ¤©', 'amazing': 'ðŸ¤©', 'wow': 'ðŸ˜®',
        'importante': 'âš ï¸', 'important': 'âš ï¸', 'atenciÃ³n': 'ðŸ‘€',
        'cuidado': 'âš ï¸', 'warning': 'âš ï¸', 'peligro': 'âš ï¸',
        'secreto': 'ðŸ¤«', 'secret': 'ðŸ¤«', 'confidencial': 'ðŸ¤',
        'dinero': 'ðŸ’°', 'money': 'ðŸ’°', 'dÃ³lares': 'ðŸ’µ', 'dollars': 'ðŸ’µ',
        'Ã©xito': 'ðŸŽ¯', 'success': 'ðŸŽ¯', 'logro': 'ðŸ†', 'achievement': 'ðŸ†',
        'millÃ³n': 'ðŸ’Ž', 'million': 'ðŸ’Ž', 'billÃ³n': 'ðŸ’Ž', 'billion': 'ðŸ’Ž',
        'pregunta': 'â“', 'question': 'â“', 'cÃ³mo': 'ðŸ¤”', 'how': 'ðŸ¤”',
        'tiempo': 'â°', 'time': 'â°', 'rÃ¡pido': 'âš¡', 'fast': 'âš¡',
        'fuego': 'ðŸ”¥', 'fire': 'ðŸ”¥', 'caliente': 'ðŸ”¥', 'hot': 'ðŸ”¥',
        'nuevo': 'âœ¨', 'new': 'âœ¨', 'gratis': 'ðŸŽ', 'free': 'ðŸŽ',
        'amor': 'â¤ï¸', 'love': 'â¤ï¸', 'corazÃ³n': 'ðŸ’–', 'heart': 'ðŸ’–',
        'poder': 'ðŸ’ª', 'power': 'ðŸ’ª', 'fuerte': 'ðŸ’ª', 'strong': 'ðŸ’ª',
        'cerebro': 'ðŸ§ ', 'brain': 'ðŸ§ ', 'inteligente': 'ðŸ§ ', 'smart': 'ðŸ§ ',
        'ojo': 'ðŸ‘ï¸', 'eye': 'ðŸ‘ï¸', 'mirar': 'ðŸ‘€', 'look': 'ðŸ‘€',
        'guerra': 'âš”ï¸', 'war': 'âš”ï¸', 'batalla': 'âš”ï¸', 'battle': 'âš”ï¸',
        'misterio': 'ðŸ”®', 'mystery': 'ðŸ”®', 'extraÃ±o': 'ðŸ‘½', 'alien': 'ðŸ‘½',
        'muerte': 'ðŸ’€', 'death': 'ðŸ’€', 'muerto': 'â˜ ï¸', 'dead': 'â˜ ï¸',
        'rey': 'ðŸ‘‘', 'king': 'ðŸ‘‘', 'reina': 'ðŸ‘‘', 'queen': 'ðŸ‘‘',
        'victoria': 'ðŸ†', 'victory': 'ðŸ†', 'ganar': 'ðŸ†', 'win': 'ðŸ†',
    }

    _NORMALIZED_EMOJI_MAP: Optional[Dict[str, str]] = None

    @staticmethod
    def is_enabled() -> bool:
        """
        Emojis desactivados por defecto para evitar artefactos de codificación
        y problemas de fuentes en ASS/libass.
        """
        return os.environ.get("VIDEO_OPTIMIZER_SUBS_ENABLE_EMOJIS", "0") == "1"

    @staticmethod
    def _repair_mojibake(text: str) -> str:
        """
        Repara texto UTF-8 mal decodificado como Windows-1252 (ej: 'ðŸ”®').
        Si no aplica, devuelve el texto original.
        """
        if not text:
            return text

        if not any(marker in text for marker in ("Ã", "â", "ð", "ï")):
            return text

        try:
            repaired = text.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
            repaired = repaired.strip()
            return repaired or text
        except Exception:
            return text

    @classmethod
    def normalize_word(cls, word: str) -> str:
        """Normaliza palabras para matching robusto (lower + sin acentos + sin puntuación)."""
        cleaned = cls._repair_mojibake(str(word or ""))
        cleaned = cleaned.lower().strip('.,!?;:¡¿"\'()[]{}')
        normalized = unicodedata.normalize("NFKD", cleaned)
        return ''.join(ch for ch in normalized if not unicodedata.combining(ch))

    @classmethod
    def normalize_text_token(cls, token: str) -> str:
        """Limpia texto para ASS evitando tags accidentales y controles."""
        cleaned = cls._repair_mojibake(str(token or ""))
        cleaned = cleaned.replace("{", "(").replace("}", ")")
        cleaned = re.sub(r"[\x00-\x1F\x7F-\x9F]", "", cleaned)
        return cleaned.strip()

    @classmethod
    def has_spoken_content(cls, token: str) -> bool:
        """True cuando el token contiene contenido pronunciable (letras o números)."""
        normalized = cls.normalize_word(token)
        return any(ch.isalnum() for ch in normalized)

    @classmethod
    def tokenize_spoken_words(cls, text: str) -> List[str]:
        """
        Divide texto en tokens útiles para subtítulos y descarta puntuación aislada
        como guiones largos o comillas sueltas, que pueden romper el karaoke.
        """
        tokens: List[str] = []
        for raw_token in str(text or "").split():
            cleaned = cls.normalize_text_token(raw_token)
            if cleaned and cls.has_spoken_content(cleaned):
                tokens.append(cleaned)
        return tokens

    @classmethod
    def _get_normalized_emoji_map(cls) -> Dict[str, str]:
        if cls._NORMALIZED_EMOJI_MAP is not None:
            return cls._NORMALIZED_EMOJI_MAP

        normalized_map: Dict[str, str] = {}
        for raw_key, raw_value in cls.EMOJI_MAP.items():
            key = cls.normalize_word(raw_key)
            value = cls._repair_mojibake(raw_value)
            if key and value:
                normalized_map[key] = value

        cls._NORMALIZED_EMOJI_MAP = normalized_map
        return normalized_map
    
    @classmethod
    def get_emoji(cls, word: str) -> Optional[str]:
        """Obtiene emoji para una palabra si existe"""
        if not cls.is_enabled():
            return None
        normalized_word = cls.normalize_word(word)
        return cls._get_normalized_emoji_map().get(normalized_word)
    
    @classmethod
    def add_emojis_to_text(cls, text: str, max_emojis: int = 3) -> str:
        """AÃ±ade emojis automÃ¡ticamente a un texto"""
        words = text.split()
        emoji_count = 0
        result = []
        
        for word in words:
            clean_word = cls.normalize_text_token(word)
            emoji = cls.get_emoji(clean_word)
            if emoji and emoji_count < max_emojis:
                result.append(f"{clean_word} {emoji}")
                emoji_count += 1
            else:
                result.append(clean_word)
        
        return ' '.join(result)


class SubtitleStyle:
    """
    Define estilos de subtÃ­tulos predefinidos.
    Cada estilo tiene configuraciÃ³n de colores, fuentes, animaciones, etc.
    """
    
    STYLES = {
        'hormozi': {
            'name': 'Alex Hormozi',
            'font': 'Impact',
            'font_size': 80,
            'primary_color': '&H00FFFF',  # Amarillo brillante (BGR)
            'secondary_color': '&H0000FF',  # Rojo (palabra activa)
            'outline_color': '&H000000',  # Negro
            'back_color': '&H80000000',  # Negro semi-transparente
            'bold': -1,
            'outline': 4,
            'shadow': 2,
            'alignment': 2,  # Centro inferior
            'margin_v': 80,
            'animation': 'bounce',
            'karaoke': True,
            'emojis': True,
        },
        'mrbeast': {
            'name': 'MrBeast',
            'font': 'Bangers',
            'font_size': 70,
            'primary_color': '&H00FFFF',  # Amarillo
            'secondary_color': '&H00FF00',  # Verde (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H00000000',  # Transparente
            'bold': -1,
            'outline': 5,
            'shadow': 0,
            'alignment': 2,
            'margin_v': 100,
            'animation': 'pop',
            'karaoke': True,
            'emojis': True,
        },
        'tiktok': {
            'name': 'TikTok Viral',
            'font': 'Arial Black',
            'font_size': 65,
            'primary_color': '&HFFFFFF',  # Blanco
            'secondary_color': '&H00FFFF',  # Amarillo (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H80000000',
            'bold': -1,
            'outline': 3,
            'shadow': 1,
            'alignment': 2,
            'margin_v': 120,
            'animation': 'shake',
            'karaoke': True,
            'emojis': True,
        },
        'minimalist': {
            'name': 'Minimalista',
            'font': 'Helvetica Neue',
            'font_size': 50,
            'primary_color': '&HFFFFFF',  # Blanco
            'secondary_color': '&H00D4D4',  # Cyan claro (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&HC0000000',  # Negro muy transparente
            'bold': 0,
            'outline': 2,
            'shadow': 1,
            'alignment': 2,
            'margin_v': 60,
            'animation': 'fade',
            'karaoke': False,
            'emojis': False,
        },
        'documentary': {
            'name': 'Documental',
            'font': 'Arial',
            'font_size': 45,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&HFFFFFF',
            'outline_color': '&H000000',
            'back_color': '&HE0000000',  # Negro semi-opaco
            'bold': 0,
            'outline': 2,
            'shadow': 0,
            'alignment': 2,
            'margin_v': 40,
            'animation': 'none',
            'karaoke': False,
            'emojis': False,
        },
        'gaming': {
            'name': 'Gaming/Streaming',
            'font': 'Arial Black',
            'font_size': 75,
            'primary_color': '&H00FF00',  # Verde brillante
            'secondary_color': '&H00FFFF',  # Cyan (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H80000000',
            'bold': -1,
            'outline': 4,
            'shadow': 2,
            'alignment': 2,
            'margin_v': 90,
            'animation': 'pop',
            'karaoke': True,
            'emojis': True,
        },
        'news': {
            'name': 'Noticiero',
            'font': 'Arial',
            'font_size': 55,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&H00FFFF',  # Amarillo (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&HF0000000',  # Negro opaco
            'bold': -1,
            'outline': 3,
            'shadow': 1,
            'alignment': 8,  # Centro superior
            'margin_v': 50,
            'animation': 'fade',
            'karaoke': True,
            'emojis': False,
        },
        'cinematic': {
            'name': 'CinematogrÃ¡fico',
            'font': 'Times New Roman',
            'font_size': 60,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&H00D4D4',  # Cyan claro (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H00000000',  # Transparente
            'bold': 0,
            'outline': 2,
            'shadow': 3,
            'alignment': 2,
            'margin_v': 70,
            'animation': 'fade',
            'karaoke': False,
            'emojis': False,
        },
        'neon': {
            'name': 'NeÃ³n',
            'font': 'Arial Black',
            'font_size': 70,
            'primary_color': '&HFF00FF',  # Magenta neÃ³n
            'secondary_color': '&H00FFFF',  # Cyan neÃ³n (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H00000000',  # Transparente
            'bold': -1,
            'outline': 5,
            'shadow': 4,
            'alignment': 2,
            'margin_v': 100,
            'animation': 'shake',
            'karaoke': True,
            'emojis': True,
        },
        'retro': {
            'name': 'Retro 80s',
            'font': 'Courier New',
            'font_size': 65,
            'primary_color': '&H00FFFF',  # Cyan
            'secondary_color': '&HFF00FF',  # Magenta (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H80000000',
            'bold': -1,
            'outline': 3,
            'shadow': 2,
            'alignment': 2,
            'margin_v': 80,
            'animation': 'pop',
            'karaoke': True,
            'emojis': False,
        },
        'elegant': {
            'name': 'Elegante',
            'font': 'Georgia',
            'font_size': 55,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&H00D4D4',  # Cyan claro (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&HC0000000',  # Negro muy transparente
            'bold': 0,
            'outline': 1,
            'shadow': 2,
            'alignment': 2,
            'margin_v': 60,
            'animation': 'fade',
            'karaoke': False,
            'emojis': False,
        },
        'bold': {
            'name': 'Bold/Impact',
            'font': 'Impact',
            'font_size': 85,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&H0000FF',  # Rojo (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H00000000',
            'bold': -1,
            'outline': 6,
            'shadow': 3,
            'alignment': 2,
            'margin_v': 110,
            'animation': 'bounce',
            'karaoke': True,
            'emojis': True,
        },
        'capcut_creator': {
            'name': 'CapCut Creator Pro',
            'font': 'Segoe UI Semibold',
            'font_size': 72,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&H00FFFF',  # Amarillo (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H70000000',  # Negro transparente
            'bold': -1,
            'outline': 4,
            'shadow': 2,
            'alignment': 2,
            'margin_v': 90,
            'animation': 'pop',
            'karaoke': True,
            'emojis': False,
        },
        'capcut_kinetic': {
            'name': 'CapCut Kinetic Pro',
            'font': 'Arial Black',
            'font_size': 78,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&H0000FF',  # Rojo (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H00000000',
            'bold': -1,
            'outline': 5,
            'shadow': 2,
            'alignment': 2,
            'margin_v': 100,
            'animation': 'bounce',
            'karaoke': True,
            'emojis': False,
        },
        'capcut_focus': {
            'name': 'CapCut Focus Pro',
            'font': 'Trebuchet MS',
            'font_size': 66,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&H00FF00',  # Verde (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H60000000',
            'bold': -1,
            'outline': 3,
            'shadow': 2,
            'alignment': 5,  # Centro
            'margin_v': 55,
            'animation': 'fade',
            'karaoke': True,
            'emojis': False,
        },
        'capcut_podcast': {
            'name': 'CapCut Podcast Pro',
            'font': 'Segoe UI',
            'font_size': 56,
            'primary_color': '&HFFFFFF',
            'secondary_color': '&H00D4D4',  # Cyan claro (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H90000000',
            'bold': 0,
            'outline': 2,
            'shadow': 1,
            'alignment': 2,
            'margin_v': 36,
            'animation': 'fade',
            'karaoke': False,
            'emojis': False,
        },
        'capcut_luxury': {
            'name': 'CapCut Luxury Pro',
            'font': 'Georgia',
            'font_size': 62,
            'primary_color': '&H00C8FF',  # Dorado suave (BGR)
            'secondary_color': '&H00FFFF',  # Amarillo (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H50000000',
            'bold': -1,
            'outline': 2,
            'shadow': 3,
            'alignment': 2,
            'margin_v': 76,
            'animation': 'fade',
            'karaoke': True,
            'emojis': False,
        },
        # ── Nuevos estilos ────────────────────────────────────────────
        'horror': {
            'name': 'Horror/Terror',
            'font': 'Impact',
            'font_size': 75,
            'primary_color': '&H0000FF',  # Rojo sangre (BGR)
            'secondary_color': '&H0000AA',  # Rojo oscuro (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H80000000',
            'bold': -1,
            'outline': 4,
            'shadow': 5,
            'alignment': 2,
            'margin_v': 90,
            'animation': 'shake',
            'karaoke': True,
            'emojis': False,
        },
        'typewriter': {
            'name': 'Typewriter',
            'font': 'Courier New',
            'font_size': 52,
            'primary_color': '&H00FFFF',  # Amarillo envejecido
            'secondary_color': '&HFFFFFF',  # Blanco (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&HA0000000',
            'bold': 0,
            'outline': 1,
            'shadow': 0,
            'alignment': 2,
            'margin_v': 50,
            'animation': 'fade',
            'karaoke': False,
            'emojis': False,
        },
        'fire': {
            'name': 'Fuego/Fire',
            'font': 'Impact',
            'font_size': 80,
            'primary_color': '&H0080FF',  # Naranja fuego (BGR)
            'secondary_color': '&H0000FF',  # Rojo (palabra activa)
            'outline_color': '&H000040',  # Marrón oscuro
            'back_color': '&H00000000',
            'bold': -1,
            'outline': 5,
            'shadow': 3,
            'alignment': 2,
            'margin_v': 100,
            'animation': 'bounce',
            'karaoke': True,
            'emojis': True,
        },
        'ice': {
            'name': 'Hielo/Ice',
            'font': 'Arial',
            'font_size': 65,
            'primary_color': '&HFFCC66',  # Azul hielo claro (BGR)
            'secondary_color': '&HFFFFFF',  # Blanco (palabra activa)
            'outline_color': '&H804000',  # Azul profundo
            'back_color': '&H40000000',
            'bold': -1,
            'outline': 3,
            'shadow': 4,
            'alignment': 2,
            'margin_v': 80,
            'animation': 'fade',
            'karaoke': True,
            'emojis': False,
        },
        'comic': {
            'name': 'Comic/Cartoon',
            'font': 'Comic Sans MS',
            'font_size': 70,
            'primary_color': '&HFFFFFF',  # Blanco
            'secondary_color': '&H00FF00',  # Verde (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H00000000',
            'bold': -1,
            'outline': 5,
            'shadow': 3,
            'alignment': 2,
            'margin_v': 95,
            'animation': 'pop',
            'karaoke': True,
            'emojis': True,
        },
        'karaoke_party': {
            'name': 'Karaoke Party',
            'font': 'Arial Black',
            'font_size': 75,
            'primary_color': '&HFF00FF',  # Magenta (BGR)
            'secondary_color': '&H00FFFF',  # Amarillo (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H60000000',
            'bold': -1,
            'outline': 4,
            'shadow': 2,
            'alignment': 2,
            'margin_v': 100,
            'animation': 'bounce',
            'karaoke': True,
            'emojis': True,
        },
        'whatsapp': {
            'name': 'WhatsApp/Chat',
            'font': 'Segoe UI',
            'font_size': 50,
            'primary_color': '&HFFFFFF',  # Blanco
            'secondary_color': '&H00FF8B',  # Verde WhatsApp (BGR)
            'outline_color': '&H004400',
            'back_color': '&HE0254B25',  # Verde oscuro semi-opaco
            'bold': 0,
            'outline': 1,
            'shadow': 0,
            'alignment': 1,  # Inferior izquierda
            'margin_v': 60,
            'animation': 'fade',
            'karaoke': False,
            'emojis': True,
        },
        'glitch': {
            'name': 'Glitch/Cyberpunk',
            'font': 'Consolas',
            'font_size': 68,
            'primary_color': '&H00FF00',  # Verde terminal
            'secondary_color': '&HFF00FF',  # Magenta (palabra activa)
            'outline_color': '&H000000',
            'back_color': '&H00000000',
            'bold': -1,
            'outline': 3,
            'shadow': 4,
            'alignment': 2,
            'margin_v': 85,
            'animation': 'shake',
            'karaoke': True,
            'emojis': False,
        },
        'handwritten': {
            'name': 'Manuscrito/Handwritten',
            'font': 'Segoe Script',
            'font_size': 58,
            'primary_color': '&H303030',  # Gris oscuro (tinta)
            'secondary_color': '&H0000CC',  # Rojo oscuro
            'outline_color': '&HFFFFFF',
            'back_color': '&HD0E0E8F0',  # Beige papel
            'bold': 0,
            'outline': 1,
            'shadow': 1,
            'alignment': 2,
            'margin_v': 70,
            'animation': 'fade',
            'karaoke': False,
            'emojis': False,
        },
        'spotify': {
            'name': 'Spotify/Music',
            'font': 'Arial',
            'font_size': 54,
            'primary_color': '&HFFFFFF',  # Blanco
            'secondary_color': '&H00DB1E',  # Verde Spotify (BGR)
            'outline_color': '&H000000',
            'back_color': '&HE0121212',  # Negro Spotify
            'bold': -1,
            'outline': 0,
            'shadow': 0,
            'alignment': 2,
            'margin_v': 55,
            'animation': 'fade',
            'karaoke': True,
            'emojis': False,
        },
        'military': {
            'name': 'Militar/Tactical',
            'font': 'Impact',
            'font_size': 62,
            'primary_color': '&H00AAFF',  # Naranja militar (BGR)
            'secondary_color': '&HFFFFFF',  # Blanco (palabra activa)
            'outline_color': '&H003300',  # Verde militar oscuro
            'back_color': '&H80003300',
            'bold': -1,
            'outline': 3,
            'shadow': 2,
            'alignment': 2,  # Inferior
            'margin_v': 60,
            'animation': 'pop',
            'karaoke': True,
            'emojis': False,
        },
    }
    
    @classmethod
    def get_style(cls, style_name: str) -> Dict:
        """Obtiene un estilo por nombre"""
        return cls.STYLES.get(style_name.lower(), cls.STYLES['hormozi'])
    
    @classmethod
    def list_styles(cls) -> List[str]:
        """Lista todos los estilos disponibles"""
        return list(cls.STYLES.keys())


class ASSSubtitleGenerator:
    """
    Generador de archivos ASS (Advanced SubStation Alpha).
    Permite subtÃ­tulos con animaciones complejas, karaoke, y efectos avanzados.
    """
    
    def __init__(self, style_name: str = 'hormozi'):
        self.style_name = style_name
        self.base_style = dict(SubtitleStyle.get_style(style_name))
        self.style = dict(self.base_style)
        self.events = []
        self.video_width = 1920
        self.video_height = 1080

    def set_video_context(self, video_width: int = 1920, video_height: int = 1080):
        """Configura el contexto del video para adaptar estilo y layout."""
        try:
            self.video_width = max(1, int(video_width))
        except Exception:
            self.video_width = 1920
        try:
            self.video_height = max(1, int(video_height))
        except Exception:
            self.video_height = 1080
        self.style = self._resolve_style_for_video()

    def _is_vertical_layout(self) -> bool:
        return self.video_height > self.video_width

    def _resolve_style_for_video(self) -> Dict:
        """Ajusta tamaños y márgenes del estilo según la resolución objetivo."""
        style = dict(self.base_style)
        if not self._is_vertical_layout():
            return style

        width_ratio = self.video_width / 1920.0
        height_ratio = self.video_height / 1080.0
        font_scale = max(0.68, min(0.82, width_ratio * 1.35))
        outline_scale = max(0.70, min(1.0, width_ratio * 1.35))
        shadow_scale = max(0.70, min(1.0, width_ratio * 1.25))
        margin_scale = max(1.35, min(1.9, height_ratio * 0.9))

        style['font_size'] = max(40, int(style.get('font_size', 60) * font_scale))
        style['outline'] = max(1, int(round(style.get('outline', 2) * outline_scale)))
        style['shadow'] = max(0, int(round(style.get('shadow', 1) * shadow_scale)))
        # Evitar traslape con la UI de TikTok/Shorts (aproximadamente el 25% inferior)
        safe_margin = 0.25 if self._is_vertical_layout() else 0.14
        style['margin_v'] = max(
            int(self.video_height * safe_margin),
            int(style.get('margin_v', 60) * margin_scale)
        )
        return style

    def _get_layout_limits(self) -> Dict[str, int]:
        """Define densidad máxima del subtítulo según el formato final."""
        if self._is_vertical_layout():
            return {
                'max_words': 7,
                'max_chars': 36,
                'min_words_before_break': 3,
            }
        return {
            'max_words': 7,
            'max_chars': 42,
            'min_words_before_break': 3,
        }

    def _split_words_for_layout(self, words: List[Dict]) -> List[List[Dict]]:
        """Divide palabras en chunks más seguros para el formato del video."""
        if not words:
            return []

        limits = self._get_layout_limits()
        max_words = limits['max_words']
        max_chars = limits['max_chars']
        min_words_before_break = limits['min_words_before_break']
        chunks = []
        current_chunk = []
        current_chars = 0
        punctuation_breaks = ('.', '!', '?', ';', ':')

        for word_data in words:
            raw_word = str(word_data.get('word', '') or '').strip()
            if not raw_word:
                continue

            normalized_word = EmojiMapper.normalize_text_token(raw_word) or raw_word
            projected_chars = current_chars + (1 if current_chunk else 0) + len(normalized_word)
            should_break = False

            if current_chunk:
                if len(current_chunk) >= max_words:
                    should_break = True
                elif projected_chars > max_chars and len(current_chunk) >= min_words_before_break:
                    should_break = True

            if should_break:
                chunks.append(current_chunk)
                current_chunk = []
                current_chars = 0

            current_chunk.append(word_data)
            current_chars += (1 if len(current_chunk) > 1 else 0) + len(normalized_word)

            if normalized_word.endswith(punctuation_breaks) and len(current_chunk) >= min_words_before_break:
                chunks.append(current_chunk)
                current_chunk = []
                current_chars = 0

        if current_chunk:
            chunks.append(current_chunk)

        return chunks or [words]
    
    def generate_ass_header(self, video_width: int = 1920, video_height: int = 1080) -> str:
        """Genera el header del archivo ASS"""
        self.set_video_context(video_width, video_height)
        style = self.style
        
        def _pad_color(color_str: str) -> str:
            if color_str.startswith('&H') and len(color_str) == 8: # &H + 6 digits
                return '&H00' + color_str[2:]
            return color_str
            
        p_color = _pad_color(style['primary_color'])
        s_color = _pad_color(style['secondary_color'])
        o_color = _pad_color(style['outline_color'])
        b_color = _pad_color(style.get('back_color', '&H00000000'))
        
        header = f"""[Script Info]
Title: Dynamic Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['font']},{style['font_size']},{p_color},{s_color},{o_color},{b_color},{style['bold']},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},{style['alignment']},20,20,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        return header
    
    def time_to_ass_format(self, seconds: float) -> str:
        """Convierte segundos a formato ASS (H:MM:SS.CC)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"
    
    def create_animation_tags(self, animation_type: str, word_index: int, total_words: int) -> str:
        """Crea tags de animaciÃ³n ASS segÃºn el tipo"""
        
        if animation_type == 'bounce':
            # AnimaciÃ³n de rebote (sube y baja)
            offset = word_index * 50  # Delay escalonado
            return f"{{\\t({offset},{offset+150},\\fscx120\\fscy120)\\t({offset+150},{offset+300},\\fscx100\\fscy100)}}"
        
        elif animation_type == 'pop':
            # Pop explosivo
            offset = word_index * 40
            return f"{{\\t({offset},{offset+100},\\fscx150\\fscy150\\1a&HFF&)\\t({offset+100},{offset+200},\\fscx100\\fscy100\\1a&H00&)}}"
        
        elif animation_type == 'shake':
            # Shake horizontal usando \t (transiciones) - ASS solo permite UN \move por evento
            shake_amount = 5
            return f"{{\\t(0,50,\\frz{shake_amount})\\t(50,100,\\frz-{shake_amount})\\t(100,150,\\frz0)}}"
        
        elif animation_type == 'fade':
            # Fade in suave
            return f"{{\\fad(150,150)}}"
        
        else:
            return ""
    
    def create_karaoke_effect(self, words: List[Dict], line_start: float, line_end: float) -> str:
        """
        Crea efecto karaoke palabra por palabra.
        Cada palabra se resalta cuando es su turno de ser pronunciada.
        """
        
        use_emojis = self.style.get('emojis', False) and EmojiMapper.is_enabled()

        if not self.style.get('karaoke', False):
            # Sin karaoke, devolver texto simple
            text = ' '.join([EmojiMapper.normalize_text_token(w.get('word', '')) for w in words])
            if use_emojis:
                text = EmojiMapper.add_emojis_to_text(text)
            return text
        
        # Construir texto con karaoke
        karaoke_text = ""
        animation = self.style.get('animation', 'none')
        
        def _is_highlightable(w: str) -> bool:
            clean = EmojiMapper.normalize_text_token(w).strip(".,!?:;'\"()")
            if not clean: return False
            if any(c.isdigit() for c in clean): return True
            if len(clean) > 1 and clean[0].isupper() and clean.lower() not in {"el", "la", "los", "las", "un", "una", "y", "en", "de", "por", "para", "con"}:
                return True
            return False

        for i, word_data in enumerate(words):
            raw_word = word_data.get('word', '')
            word = EmojiMapper.normalize_text_token(raw_word)
            if not word or not EmojiMapper.has_spoken_content(word):
                continue
            word_start = word_data.get('start', line_start)
            word_end = word_data.get('end', line_end)
            
            duration_cs = int((word_end - word_start) * 100)
            karaoke_tag = f"{{\\k{duration_cs}}}"
            anim_tag = self.create_animation_tags(animation, i, len(words))
            
            emoji = EmojiMapper.get_emoji(word) if use_emojis else None
            word_with_emoji = f"{word} {emoji}" if emoji else word
            
            if _is_highlightable(raw_word):
                color_tag = "{\\c&H00FFFF&\\2c&H00FFFF&}"
                reset_tag = "{\\c\\2c}"
                word_with_emoji = f"{color_tag}{word_with_emoji}{reset_tag}"
            
            karaoke_text += f"{anim_tag}{karaoke_tag}{word_with_emoji} "
        
        return karaoke_text.strip()
    
    def add_subtitle_line(self, start: float, end: float, words: List[Dict]):
        """
        AÃ±ade una lÃ­nea de subtÃ­tulo con timing y palabras individuales.
        
        Args:
            start: Tiempo de inicio en segundos
            end: Tiempo de fin en segundos
            words: Lista de diccionarios con {'word': str, 'start': float, 'end': float}
        """
        
        filtered_words = [
            word_data for word_data in (words or [])
            if EmojiMapper.has_spoken_content(word_data.get('word', ''))
        ]
        if not filtered_words:
            return

        for chunk in self._split_words_for_layout(filtered_words):
            chunk_start = start
            chunk_end = end
            if chunk:
                try:
                    chunk_start = float(chunk[0].get('start', start))
                except Exception:
                    chunk_start = start
                try:
                    chunk_end = float(chunk[-1].get('end', end))
                except Exception:
                    chunk_end = end
                if chunk_end <= chunk_start:
                    chunk_end = chunk_start + 0.05

            start_time = self.time_to_ass_format(chunk_start)
            end_time = self.time_to_ass_format(chunk_end)

            # Crear texto con karaoke
            text = self.create_karaoke_effect(chunk, chunk_start, chunk_end)

            # Formato: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            event_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}"

            self.events.append(event_line)
    
    def generate_ass_file(self, output_path: str, video_width: int = 1920, video_height: int = 1080):
        """Genera el archivo ASS completo"""
        
        # Header
        ass_content = self.generate_ass_header(video_width, video_height)
        
        # Events
        def event_sort_key(event_line: str):
            try:
                parts = event_line.split(',', 9)
                return parts[1], parts[2]
            except Exception:
                return event_line, event_line

        ass_content += '\n'.join(sorted(self.events, key=event_sort_key))
        
        # Escribir archivo
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)
        
        print(f"âœ… Archivo ASS generado: {output_path}")
        return output_path


class WhisperTimestampParser:
    """
    Parser de timestamps de Whisper para extraer timing palabra por palabra.
    """
    
    @staticmethod
    def parse_whisper_json(json_path: str) -> List[Dict]:
        """
        Parsea el JSON de Whisper y extrae palabras con timestamps.
        
        Returns:
            Lista de segmentos con palabras y sus tiempos
        """
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        segments = []
        
        for segment in data.get('segments', []):
            segment_data = {
                'start': segment.get('start', 0),
                'end': segment.get('end', 0),
                'text': segment.get('text', ''),
                'words': []
            }
            
            # Extraer palabras individuales si estÃ¡n disponibles
            if 'words' in segment:
                for word_data in segment['words']:
                    segment_data['words'].append({
                        'word': word_data.get('word', '').strip(),
                        'start': word_data.get('start', segment['start']),
                        'end': word_data.get('end', segment['end'])
                    })
            else:
                # Si no hay word timestamps, dividir por palabras y estimar
                words = segment['text'].split()
                duration = segment['end'] - segment['start']
                time_per_word = duration / len(words) if words else 0
                
                for i, word in enumerate(words):
                    word_start = segment['start'] + (i * time_per_word)
                    word_end = word_start + time_per_word
                    segment_data['words'].append({
                        'word': word,
                        'start': word_start,
                        'end': word_end
                    })
            
            segments.append(segment_data)
        
        return segments
    
    @staticmethod
    def _estimate_word_weight(word: str) -> float:
        """
        Estima el peso relativo de duracion de una palabra basado en
        su longitud y caracteristicas foneticas.
        Palabras mas largas y con mas silabas tardan mas en pronunciarse.
        """
        import re
        # Limpiar puntuacion para contar caracteres reales
        clean = re.sub(r'[^\w]', '', word)
        char_count = max(len(clean), 1)

        # Base weight: raiz cuadrada de caracteres (no lineal, porque
        # palabras largas no tardan proporcionalmente mas)
        weight = char_count ** 0.65

        # Palabras cortas comunes (articulos, preposiciones) son mas rapidas
        short_words = {
            'a', 'an', 'the', 'of', 'to', 'in', 'on', 'at', 'is', 'it',
            'by', 'or', 'as', 'if', 'so', 'no', 'up', 'do', 'my', 'we',
            'he', 'be', 'me', 'us', 'am', 'el', 'la', 'de', 'en', 'un',
            'y', 'o', 'e', 'a', 'se', 'es', 'lo', 'le', 'al', 'su',
            'del', 'por', 'con', 'que', 'una', 'los', 'las', 'its', 'was',
            'and', 'but', 'for', 'not', 'are', 'had', 'has', 'his', 'her',
            'the', 'this', 'that', 'with', 'from', 'they', 'been', 'have',
            'were', 'said', 'each', 'than', 'them', 'into'
        }
        if clean.lower() in short_words:
            weight *= 0.75

        # Pausa extra despues de puntuacion final (. , ; : ! ?)
        if word and word[-1] in '.!?':
            weight += 0.6  # Pausa al final de oracion
        elif word and word[-1] in ',;:':
            weight += 0.3  # Pausa menor en comas

        return weight

    @staticmethod
    def parse_whisper_segments(segments: List[Dict]) -> List[Dict]:
        """
        Parsea segmentos ya extraidos de Whisper.

        Args:
            segments: Lista de segmentos con formato:
                [{'start': float, 'end': float, 'text': str, 'words': [...]}, ...]

        Returns:
            Lista normalizada de segmentos
        """
        normalized = []

        for segment in segments:
            seg_data = {
                'start': segment.get('start', 0),
                'end': segment.get('end', 0),
                'text': segment.get('text', ''),
                'words': []
            }

            # Si ya tiene palabras con timing
            if 'words' in segment and segment['words']:
                seg_data['words'] = segment['words']
            else:
                # Estimar timing por palabra con pesos proporcionales
                # a la longitud/complejidad de cada palabra
                words = segment['text'].split()
                if not words:
                    normalized.append(seg_data)
                    continue

                seg_start = float(segment.get('start', 0))
                seg_end = float(segment.get('end', 0))
                duration = seg_end - seg_start

                # Reservar un pequeno margen al inicio y final del segmento
                # (la voz no empieza exactamente en t=0 del segmento)
                margin = min(0.08, duration * 0.02)
                effective_start = seg_start + margin
                effective_duration = duration - (margin * 2)

                if effective_duration <= 0:
                    effective_start = seg_start
                    effective_duration = duration

                # Calcular peso de cada palabra
                weights = [WhisperTimestampParser._estimate_word_weight(w) for w in words]
                total_weight = sum(weights)

                if total_weight <= 0:
                    total_weight = len(words)
                    weights = [1.0] * len(words)

                # Distribuir tiempo proporcionalmente al peso
                current_time = effective_start
                for i, word in enumerate(words):
                    word_fraction = weights[i] / total_weight
                    word_duration = effective_duration * word_fraction
                    word_start = current_time
                    word_end = current_time + word_duration

                    seg_data['words'].append({
                        'word': word,
                        'start': round(word_start, 3),
                        'end': round(word_end, 3)
                    })
                    current_time = word_end

            normalized.append(seg_data)

        return normalized


class DynamicSubtitleEngine:
    """
    Motor principal para generar subtÃ­tulos dinÃ¡micos.
    Integra todos los componentes: parser, generador ASS, estilos, etc.
    """
    
    def __init__(self, style: str = 'hormozi'):
        self.style_name = style
        self.ass_generator = ASSSubtitleGenerator(style)
        self.last_sync_details = {
            'mode': 'uninitialized',
            'reason': None,
        }

    def _set_sync_details(self, mode: str, **extra):
        details = {'mode': mode}
        details.update(extra)
        self.last_sync_details = details

    @staticmethod
    def _get_min_hybrid_match_ratio() -> float:
        """Umbral mínimo para confiar en subtítulos híbridos con texto editado."""
        raw_value = os.environ.get("VIDEO_OPTIMIZER_SUBS_MIN_HYBRID_MATCH", "0.55")
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = 0.55
        return max(0.0, min(1.0, value))

    @staticmethod
    def _allow_proportional_fallback() -> bool:
        """
        El fallback proporcional puede conservar texto editado, pero es menos seguro
        que Whisper puro cuando el match es bajo. Por eso queda desactivado por defecto.
        """
        return str(os.environ.get("VIDEO_OPTIMIZER_SUBS_ALLOW_PROPORTIONAL", "0") or "0").strip().lower() in {
            "1", "true", "yes", "on"
        }

    @staticmethod
    def _segment_text(seg: Dict) -> str:
        """Obtiene el texto canónico de un segmento del timeline/storyboard."""
        if not isinstance(seg, dict):
            return ""
        for key in ("text", "narration_text", "narration"):
            value = seg.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _segment_time_bounds(seg: Dict, fallback_start: float = 0.0) -> Tuple[float, float]:
        """Obtiene los límites temporales más confiables disponibles para un segmento."""
        start = fallback_start
        end = fallback_start

        if isinstance(seg, dict):
            for key in ("start", "start_time", "timestamp_start"):
                value = seg.get(key)
                if value is not None:
                    try:
                        start = float(value)
                        break
                    except Exception:
                        pass

            end = start
            for key in ("end", "end_time", "timestamp_end"):
                value = seg.get(key)
                if value is not None:
                    try:
                        end = float(value)
                        break
                    except Exception:
                        pass

        if end < start:
            end = start
        return start, end

    @staticmethod
    def _extract_whisper_word_timeline(whisper_segments: List[Dict]) -> List[Dict]:
        """Aplana las palabras de Whisper en una sola línea de tiempo secuencial."""
        timeline = []

        for segment in whisper_segments or []:
            seg_start = float(segment.get('start', 0.0) or 0.0)
            seg_end = float(segment.get('end', seg_start) or seg_start)
            words = segment.get('words') or []

            for word_data in words:
                raw_word = str(word_data.get('word', '') or '').strip()
                if not raw_word:
                    continue
                if not EmojiMapper.has_spoken_content(raw_word):
                    continue

                start = float(word_data.get('start', seg_start) or seg_start)
                end = float(word_data.get('end', max(start, seg_end)) or start)
                if end <= start:
                    end = start + 0.05

                timeline.append({
                    'word': EmojiMapper.normalize_text_token(raw_word),
                    'normalized': EmojiMapper.normalize_word(raw_word),
                    'start': start,
                    'end': end,
                })

        return timeline

    @classmethod
    def _align_segments_with_whisper_words(cls, input_segments: List[Dict], whisper_segments: List[Dict]) -> Tuple[List[Dict], int, int]:
        """
        Alinea el texto editado del timeline con la línea de tiempo palabra-a-palabra
        de Whisper usando un matching global. Esto evita que un segmento "robe"
        anchors del siguiente cuando hay palabras repetidas o hints de tiempo
        ligeramente corridos respecto al audio real.
        """
        whisper_words = cls._extract_whisper_word_timeline(whisper_segments)
        if not input_segments or not whisper_words:
            return [], 0, 0

        script_entries: List[Dict] = []
        segment_ranges: List[Tuple[int, int, str, float, float]] = []
        fallback_start = 0.0

        for seg in input_segments:
            text = cls._segment_text(seg)
            raw_words = EmojiMapper.tokenize_spoken_words(text)
            if not raw_words:
                continue

            seg_start_hint, seg_end_hint = cls._segment_time_bounds(seg, fallback_start)
            first_idx = len(script_entries)

            for raw_word in raw_words:
                script_entries.append({
                    'word': EmojiMapper.normalize_text_token(raw_word),
                    'normalized': EmojiMapper.normalize_word(raw_word),
                    'segment_start_hint': seg_start_hint,
                    'segment_end_hint': seg_end_hint,
                })

            segment_ranges.append((first_idx, len(script_entries) - 1, text, seg_start_hint, seg_end_hint))
            fallback_start = max(fallback_start, seg_end_hint)

        total_words = len(script_entries)
        if total_words == 0:
            return [], 0, 0

        matcher = difflib.SequenceMatcher(
            a=[entry['normalized'] for entry in script_entries],
            b=[entry['normalized'] for entry in whisper_words],
            autojunk=False
        )
        matching_blocks = [block for block in matcher.get_matching_blocks() if block.size > 0]
        matched_words = sum(block.size for block in matching_blocks)

        assigned_times: List[Optional[Dict[str, float]]] = [None] * total_words
        for block in matching_blocks:
            for offset in range(block.size):
                script_idx = block.a + offset
                whisper_idx = block.b + offset
                timing = whisper_words[whisper_idx]
                start = float(timing.get('start', 0.0) or 0.0)
                end = float(timing.get('end', start) or start)
                if end <= start:
                    end = start + 0.05
                assigned_times[script_idx] = {'start': start, 'end': end}

        def _run_hint_bounds(run_start: int, run_end: int) -> Tuple[float, float]:
            start_hint = min(
                float(script_entries[idx]['segment_start_hint'])
                for idx in range(run_start, run_end + 1)
            )
            end_hint = max(
                float(script_entries[idx]['segment_end_hint'])
                for idx in range(run_start, run_end + 1)
            )
            if end_hint < start_hint:
                end_hint = start_hint
            return start_hint, end_hint

        idx = 0
        while idx < total_words:
            if assigned_times[idx] is not None:
                idx += 1
                continue

            run_start = idx
            while idx < total_words and assigned_times[idx] is None:
                idx += 1
            run_end = idx - 1
            run_len = run_end - run_start + 1

            left_idx = run_start - 1 if run_start > 0 and assigned_times[run_start - 1] is not None else None
            right_idx = idx if idx < total_words and assigned_times[idx] is not None else None
            hint_start, hint_end = _run_hint_bounds(run_start, run_end)

            if left_idx is not None:
                left_time = float(assigned_times[left_idx]['end'])
            else:
                left_time = max(0.0, hint_start)

            if right_idx is not None:
                right_time = float(assigned_times[right_idx]['start'])
            else:
                right_time = max(left_time, hint_end)

            min_gap = run_len * 0.08
            if right_time <= left_time:
                if left_idx is None and right_idx is not None:
                    left_time = max(0.0, right_time - max(min_gap, hint_end - hint_start))
                else:
                    right_time = left_time + max(min_gap, hint_end - hint_start)

            gap = right_time - left_time
            if gap < min_gap:
                if left_idx is None and right_idx is not None:
                    left_time = max(0.0, right_time - min_gap)
                    gap = right_time - left_time
                else:
                    right_time = left_time + min_gap
                    gap = min_gap

            step = gap / run_len
            for offset in range(run_len):
                start = left_time + offset * step
                end = left_time + (offset + 1) * step
                if end <= start:
                    end = start + 0.05
                assigned_times[run_start + offset] = {'start': start, 'end': end}

        aligned_segments: List[Dict] = []
        global_last_end = 0.0
        for first_idx, last_idx, text, seg_start_hint, seg_end_hint in segment_ranges:
            ass_words = []
            for script_idx in range(first_idx, last_idx + 1):
                timing = assigned_times[script_idx]
                if timing is None:
                    continue

                start = float(timing['start'])
                end = float(timing['end'])
                duration = max(end - start, 0.05)

                if start < global_last_end:
                    start = global_last_end
                    end = start + duration
                if end <= start:
                    end = start + 0.05

                ass_words.append({
                    'word': script_entries[script_idx]['word'],
                    'start': start,
                    'end': end,
                })
                global_last_end = max(global_last_end, end)

            if not ass_words:
                continue

            aligned_segments.append({
                'start': ass_words[0]['start'],
                'end': ass_words[-1]['end'],
                'text': text,
                'words': ass_words,
            })

        return aligned_segments, matched_words, total_words

    @staticmethod
    def _measure_segment_overlaps(segments: List[Dict]) -> Tuple[int, float]:
        """Cuenta cuántos segmentos retroceden en el tiempo y cuánto se pisan."""
        overlap_count = 0
        max_overlap = 0.0
        last_end = -1.0

        for seg in segments or []:
            try:
                start = float(seg.get('start', 0.0) or 0.0)
            except Exception:
                start = 0.0
            try:
                end = float(seg.get('end', start) or start)
            except Exception:
                end = start
            if end < start:
                end = start

            overlap = max(0.0, last_end - start)
            if overlap > 0.05:
                overlap_count += 1
                max_overlap = max(max_overlap, overlap)
            last_end = max(last_end, end)

        return overlap_count, max_overlap
    
    def generate_from_audio_and_segments(self,
                                       audio_path: str,
                                       segments: List[Dict],
                                       output_path: str,
                                       video_width: int = 1920,
                                       video_height: int = 1080,
                                       language: str = None) -> str:
        """
        Genera subtÃ­tulos sincronizados con el audio real.
        Usa Whisper para obtener timestamps precisos del audio final.
        """
        self.ass_generator.events = []
        self.ass_generator.set_video_context(video_width, video_height)
        self._set_sync_details('whisper_pending', audio_path=audio_path, segment_count=len(segments or []))
        try:
            # ──────────────────────────────────────────────────────────────
            # Whisper se invoca en un SUBPROCESS aislado.
            #
            # Razón: torch 2.4.1+CPU tiene crashes documentados en c10.dll
            # (access violation 0xC0000005) cuando se llama desde un Qt worker
            # thread tras un ensamblado FFmpeg. Esos crashes son a nivel C++ y
            # NO los puede atrapar `try/except` de Python — la app entera muere.
            #
            # Aislándolo: si el subprocess crashea, solo muere el subprocess,
            # subprocess.run() levanta CalledProcessError, esta función lanza
            # Exception, y el wrapper (generate_ass_from_segments) cae al
            # camino de timings de segmentos. La app principal sobrevive.
            # ──────────────────────────────────────────────────────────────
            import json as _json
            import os as _os
            import subprocess as _subprocess
            import sys as _sys

            lang_info = f", idioma: {language}" if language else ", idioma: auto-detect"
            print(f"ðŸŽµ Transcribiendo audio (subprocess aislado, modelo small): {Path(audio_path).name}{lang_info}")

            worker_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_whisper_subprocess_worker.py")
            if not _os.path.isfile(worker_path):
                raise RuntimeError(f"Whisper worker no encontrado: {worker_path}")

            cmd = [_sys.executable, worker_path, "--audio", str(_os.path.abspath(audio_path)), "--model", "small"]
            if language:
                cmd.extend(["--language", language])

            # Timeout generoso: 450s de audio ≈ 5-15 min con modelo small en CPU.
            # 30 min cubre con holgura. Override por env si hace falta.
            try:
                timeout_s = int(_os.environ.get("VIDEO_OPTIMIZER_WHISPER_TIMEOUT_S", "1800"))
            except Exception:
                timeout_s = 1800

            try:
                completed = _subprocess.run(
                    cmd,
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.PIPE,
                    timeout=timeout_s,
                    check=False,
                )
            except _subprocess.TimeoutExpired:
                raise RuntimeError(f"Whisper subprocess timeout tras {timeout_s}s")

            stdout_bytes = completed.stdout or b""
            stderr_text = (completed.stderr or b"").decode("utf-8", errors="replace")
            if stderr_text.strip():
                # Reemitir stderr del worker como diagnóstico (no error fatal).
                for ln in stderr_text.splitlines()[-15:]:
                    print(f"   [whisper-worker:stderr] {ln}")

            # Exit code != 0 → crash o error reportado. Distinguir segfault (Windows
            # devuelve códigos como 3221225477 = 0xC0000005) de error Python normal.
            if completed.returncode != 0:
                code = completed.returncode
                if code in (3221225477, 0xC0000005, -1073741819):  # access violation
                    raise RuntimeError(f"Whisper subprocess crasheó (access violation 0xC0000005)")
                raise RuntimeError(f"Whisper subprocess salió con código {code}")

            # Última línea NO vacía de stdout debe ser JSON con resultado.
            stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
            last_line = stdout_text.splitlines()[-1] if stdout_text else ""
            if not last_line:
                raise RuntimeError("Whisper subprocess no emitió resultado JSON en stdout")

            try:
                payload = _json.loads(last_line)
            except _json.JSONDecodeError as exc:
                raise RuntimeError(f"Whisper subprocess emitió stdout no-JSON: {exc}")

            if not payload.get("ok"):
                raise RuntimeError(f"Whisper subprocess falló: {payload.get('error', 'sin detalle')}")

            whisper_segments = payload.get("segments", []) or []
            detected_lang = payload.get("language", "??")
            print(f"   Whisper detectó idioma: {detected_lang}")

            # Diagnóstico: comparar primeras palabras del guión vs Whisper
            _diag_whisper_words = []
            for _ws in whisper_segments[:3]:
                for _ww in (_ws.get('words') or []):
                    _w = str(_ww.get('word', '')).strip()
                    if _w:
                        _diag_whisper_words.append(_w)
                    if len(_diag_whisper_words) >= 10:
                        break
                if len(_diag_whisper_words) >= 10:
                    break
            _diag_script_words = []
            for _seg in (segments or []):
                for _key in ('text', 'narration_text', 'narration'):
                    _txt = _seg.get(_key, '')
                    if isinstance(_txt, str) and _txt.strip():
                        _diag_script_words.extend(_txt.strip().split()[:10])
                        break
                if len(_diag_script_words) >= 10:
                    break
            print(f"   Whisper words (first 10): {_diag_whisper_words[:10]}")
            print(f"   Script words (first 10): {_diag_script_words[:10]}")
            print(f"   Whisper normalized: {[EmojiMapper.normalize_word(w) for w in _diag_whisper_words[:10]]}")
            print(f"   Script normalized:  {[EmojiMapper.normalize_word(w) for w in _diag_script_words[:10]]}")

            # Limpiar eventos anteriores.
            self.ass_generator.events = []

            input_segments = segments if isinstance(segments, list) else []
            use_hybrid = bool(input_segments and whisper_segments)
            hybrid_lines = 0

            if use_hybrid:
                print(" Modo subtítulos híbrido: timing Whisper + texto editado")
                aligned_segments, matched_words, total_words = self._align_segments_with_whisper_words(
                    input_segments,
                    whisper_segments
                )
                match_ratio = (matched_words / total_words) if total_words else 0.0
                overlap_count, max_overlap = self._measure_segment_overlaps(aligned_segments)
                min_hybrid_ratio = self._get_min_hybrid_match_ratio()
                allow_proportional_fallback = self._allow_proportional_fallback()

                if aligned_segments:
                    interpolated = total_words - matched_words
                    print(
                        f"   Alineacion de palabras Whisper: {matched_words}/{total_words} "
                        f"({match_ratio:.0%}) — {interpolated} interpoladas entre anchors"
                    )
                    if overlap_count:
                        print(
                            f"   Eventos híbridos superpuestos detectados: {overlap_count} "
                            f"(solape max {max_overlap:.2f}s)"
                        )
                    print(f"   Umbral mínimo para subtítulos híbridos: {min_hybrid_ratio:.0%}")

                if aligned_segments and match_ratio >= min_hybrid_ratio and overlap_count == 0:
                    for seg in aligned_segments:
                        self.ass_generator.add_subtitle_line(
                            seg['start'],
                            seg['end'],
                            seg['words']
                        )
                        hybrid_lines += 1
                    self._set_sync_details(
                        'whisper_hybrid',
                        matched_words=matched_words,
                        total_words=total_words,
                        match_ratio=match_ratio,
                        overlap_count=overlap_count,
                    )
                elif aligned_segments:
                    if allow_proportional_fallback:
                        print("   Coincidencia texto/audio insuficiente; usando mapeo proporcional por compatibilidad.")
                    else:
                        print("   Coincidencia texto/audio insuficiente; usando Whisper puro para priorizar sincronización.")

            # Fallback mejorado: mapear texto del guión a timestamps de Whisper
            # proporcionalmente. Whisper sabe CUÁNDO se habla; nosotros sabemos QUÉ se dice.
            if hybrid_lines == 0 and input_segments and self._allow_proportional_fallback():
                whisper_words = self._extract_whisper_word_timeline(whisper_segments)
                if whisper_words:
                    # Recopilar todas las palabras del guión con su segmento
                    script_word_segments = []  # [(word_str, seg_index), ...]
                    seg_boundaries = []  # [(first_word_idx, last_word_idx, seg_ref), ...]
                    for seg_i, seg in enumerate(input_segments):
                        text = seg.get('text', '').strip()
                        if not text:
                            continue
                        words = EmojiMapper.tokenize_spoken_words(text)
                        first_idx = len(script_word_segments)
                        for w in words:
                            script_word_segments.append((w, seg_i))
                        seg_boundaries.append((first_idx, len(script_word_segments) - 1, seg))

                    n_script = len(script_word_segments)
                    n_whisper = len(whisper_words)

                    if n_script > 0 and n_whisper > 0:
                        print(f"   Mapeo proporcional: {n_script} palabras guión  {n_whisper} timestamps Whisper")
                        # Mapear cada palabra del guión a un timestamp Whisper por posición proporcional
                        all_ass_words = []
                        for i, (w, _) in enumerate(script_word_segments):
                            if n_script == 1:
                                pos = 0.0
                            else:
                                pos = i * (n_whisper - 1) / (n_script - 1)
                            lo = int(pos)
                            hi = min(lo + 1, n_whisper - 1)
                            frac = pos - lo
                            w_start = whisper_words[lo]['start'] * (1 - frac) + whisper_words[hi]['start'] * frac
                            w_end = whisper_words[lo]['end'] * (1 - frac) + whisper_words[hi]['end'] * frac
                            if w_end <= w_start:
                                w_end = w_start + 0.05
                            all_ass_words.append({
                                'word': w,
                                'start': w_start,
                                'end': w_end,
                            })

                        # Agrupar por segmento y generar líneas
                        for first_idx, last_idx, seg in seg_boundaries:
                            seg_words = all_ass_words[first_idx:last_idx + 1]
                            if seg_words:
                                self.ass_generator.add_subtitle_line(
                                    seg_words[0]['start'],
                                    seg_words[-1]['end'],
                                    seg_words
                                )
                                hybrid_lines += 1
                        if hybrid_lines > 0:
                            self._set_sync_details(
                                'whisper_proportional',
                                script_word_count=n_script,
                                whisper_word_count=n_whisper,
                            )

            # Fallback final: distribución uniforme con tiempos del storyboard
            if hybrid_lines == 0 and input_segments:
                print("   Usando texto editado de segmentos con tiempos del storyboard (distribución uniforme).")
                for seg in input_segments:
                    text = seg.get('text', '').strip()
                    if not text:
                        continue
                    start = float(seg.get('start', 0))
                    end = float(seg.get('end', start + 1))
                    if end <= start:
                        end = start + 1
                    words_list = EmojiMapper.tokenize_spoken_words(text)
                    if not words_list:
                        continue
                    duration = end - start
                    word_dur = duration / len(words_list)
                    ass_words = []
                    for i, w in enumerate(words_list):
                        ass_words.append({
                            'word': w,
                            'start': start + i * word_dur,
                            'end': start + (i + 1) * word_dur,
                        })
                    self.ass_generator.add_subtitle_line(start, end, ass_words)
                    hybrid_lines += 1
                if hybrid_lines > 0:
                    self._set_sync_details(
                        'storyboard_estimate',
                        reason='uniform_segment_distribution',
                        segment_count=hybrid_lines,
                    )

            # Fallback clásico: usar texto y timings que devuelve Whisper.
            if hybrid_lines == 0:
                for segment in whisper_segments:
                    words = segment.get('words', [])
                    if not words:
                        continue

                    ass_words = []
                    for w in words:
                        ass_words.append({
                            'word': w['word'].strip(),
                            'start': w['start'],
                            'end': w['end']
                        })

                    if ass_words:
                        self.ass_generator.add_subtitle_line(
                            segment['start'],
                            segment['end'],
                            ass_words
                        )
                self._set_sync_details(
                    'whisper_raw',
                    segment_count=len(whisper_segments or []),
                )
            
            # Generar archivo
            return self.ass_generator.generate_ass_file(
                output_path,
                video_width,
                video_height
            )
            
        except ImportError:
            print("âš ï¸ OpenAI Whisper no instalado. Usando sincronizaciÃ³n por estimaciÃ³n (menos precisa).")
            print("   Instalar con: pip install openai-whisper")
            self._set_sync_details('storyboard_estimate', reason='whisper_import_error')
            return self.generate_from_segments(segments, output_path, video_width, video_height)
        except Exception as e:
            print(f"âš ï¸ Error en sincronizaciÃ³n Whisper: {e}. Usando estimaciÃ³n.")
            self._set_sync_details('storyboard_estimate', reason=f'whisper_exception:{type(e).__name__}')
            return self.generate_from_segments(segments, output_path, video_width, video_height)

    def generate_from_whisper_json(self, 
                                   whisper_json_path: str,
                                   output_ass_path: str,
                                   video_width: int = 1920,
                                   video_height: int = 1080) -> str:
        """
        Genera subtÃ­tulos ASS desde un archivo JSON de Whisper.
        
        Args:
            whisper_json_path: Path al JSON de Whisper
            output_ass_path: Path donde guardar el ASS
            video_width: Ancho del video
            video_height: Alto del video
        
        Returns:
            Path al archivo ASS generado
        """
        
        print(f"ðŸŽ¬ Generando subtÃ­tulos dinÃ¡micos estilo '{self.style_name}'...")
        self.ass_generator.events = []
        self.ass_generator.set_video_context(video_width, video_height)
        
        # Parsear Whisper JSON
        segments = WhisperTimestampParser.parse_whisper_json(whisper_json_path)
        
        # Generar lÃ­neas ASS
        for segment in segments:
            if segment['words']:
                self.ass_generator.add_subtitle_line(
                    segment['start'],
                    segment['end'],
                    segment['words']
                )
        
        self._set_sync_details(
            'whisper_json',
            segment_count=len(segments),
        )
        # Generar archivo
        return self.ass_generator.generate_ass_file(
            output_ass_path,
            video_width,
            video_height
        )
    
    def generate_from_segments(self,
                               segments: List[Dict],
                               output_ass_path: str,
                               video_width: int = 1920,
                               video_height: int = 1080) -> str:
        """
        Genera subtÃ­tulos ASS desde segmentos ya parseados.
        
        Args:
            segments: Lista de segmentos con palabras y timing
            output_ass_path: Path donde guardar el ASS
            video_width: Ancho del video
            video_height: Alto del video
        
        Returns:
            Path al archivo ASS generado
        """
        
        print(f"ðŸŽ¬ Generando subtÃ­tulos dinÃ¡micos estilo '{self.style_name}'...")
        self.ass_generator.events = []
        self.ass_generator.set_video_context(video_width, video_height)
        
        # Normalizar segmentos
        normalized = WhisperTimestampParser.parse_whisper_segments(segments)
        
        # Generar lÃ­neas ASS
        for segment in normalized:
            if segment['words']:
                self.ass_generator.add_subtitle_line(
                    segment['start'],
                    segment['end'],
                    segment['words']
                )
        
        self._set_sync_details(
            'segments_estimate',
            segment_count=len(normalized),
        )
        # Generar archivo
        return self.ass_generator.generate_ass_file(
            output_ass_path,
            video_width,
            video_height
        )
    @staticmethod
    def burn_subtitles_with_ffmpeg(video_path: str, ass_path: str, output_path: str, video_width: int = 1920, video_height: int = 1080) -> bool:
        """
        VERSIÓN CORREGIDA - Siempre funciona con subtítulos visibles
        """
        import subprocess
        import os
        import shutil
        
        # Buscar FFmpeg
        ffmpeg_path = shutil.which('ffmpeg')
        if not ffmpeg_path:
            ffmpeg_path = r"C:\ffmpeg-7.1.1-full_build\bin\ffmpeg.exe"
        
        if not os.path.exists(ffmpeg_path or ""):
            ffmpeg_path = r"C:\Users\esteban.navarro\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
        
        if not os.path.exists(ffmpeg_path or ""):
            print(" FFmpeg no encontrado")
            return False
        
        # Validar archivos
        if not os.path.exists(video_path):
            print(f" Video no encontrado: {video_path}")
            return False
        if not os.path.exists(ass_path):
            print(f" ASS no encontrado: {ass_path}")
            return False
        
        print(f" FFmpeg encontrado: {ffmpeg_path}")
        print(f" Video: {os.path.basename(video_path)}")
        print(f" Subtítulos: {os.path.basename(ass_path)}")
        
        # Copiar ASS a un nombre temporal simple en el directorio de salida temporalmente
        # Para evitar el infierno de parseo de rutas absolutas de FFmpeg en Windows
        base_dir = os.path.dirname(os.path.abspath(output_path))
        temp_ass_name = f"temp_subs_{os.getpid()}.ass"
        temp_ass_path = os.path.join(base_dir, temp_ass_name)
        
        try:
            shutil.copy2(ass_path, temp_ass_path)
            
            # Detectar el mejor codificador disponible para evitar cuello de botella de CPU
            try:
                from auto_video_generator_v2 import get_optimal_h264_encoder
                optimal_encoder = get_optimal_h264_encoder(ffmpeg_path)
            except Exception:
                optimal_encoder = 'libx264'
            
            # Comando FFmpeg - método directo con subtitles filter usando path relativo
            cmd = [
                ffmpeg_path,
                '-y',
                '-i', str(video_path),
                '-vf', f"subtitles={temp_ass_name}",
                '-c:v', optimal_encoder,
                '-preset', 'fast',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'copy',
                '-movflags', '+faststart',
                str(output_path)
            ]

            print(f" Aplicando subtítulos con FFmpeg...")
            print(f"   Comando: {' '.join(cmd)}")

            result = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True, timeout=600)
        finally:
            # Asegurar limpieza del ASS temporal
            if os.path.exists(temp_ass_path):
                try:
                    os.remove(temp_ass_path)
                except:
                    pass

        try:
            if result.returncode == 0:
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    # Verificar que el archivo de salida no sea idéntico al original
                    # (indicaría que los subtítulos no se aplicaron realmente)
                    orig_size = os.path.getsize(video_path)
                    out_size = os.path.getsize(output_path)
                    size_diff_pct = abs(out_size - orig_size) / max(orig_size, 1) * 100

                    print(f" Subtítulos aplicados: {os.path.basename(output_path)}")
                    print(f" Tamaño: {out_size / (1024*1024):.1f} MB (original: {orig_size / (1024*1024):.1f} MB, diff: {size_diff_pct:.1f}%)")

                    if size_diff_pct < 0.1 and orig_size > 1024*1024:
                        print(f"️ ADVERTENCIA: El tamaño del video con subs es casi idéntico al original - los subtítulos podrían no haberse renderizado")

                    return True
                else:
                    print(" Archivo de salida no creado o vacío")
                    return False
            else:
                print(f" Error en FFmpeg (returncode={result.returncode}):")
                if result.stderr:
                    # Mostrar últimas líneas del stderr para diagnóstico
                    stderr_lines = result.stderr.strip().split('\n')
                    for line in stderr_lines[-10:]:
                        print(f"   {line}")
                return False

        except subprocess.TimeoutExpired:
            print(" Timeout en FFmpeg (>600s)")
            return False
        except Exception as e:
            print(f" Error inesperado: {e}")
            return False
