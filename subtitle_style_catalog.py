"""
Shared subtitle style labels for GUI tabs.

This module keeps the visible style names aligned across Video Studio and
Daily Shorts while still allowing the pipeline to normalize them to engine
keys later.
"""

from typing import Dict, List, Optional, Tuple


SUBTITLE_STYLE_OPTIONS: List[Tuple[str, str]] = [
    ("hormozi", "\U0001F525 Hormozi (Amarillo + Karaoke + Emojis)"),
    ("mrbeast", "\U0001F4B0 MrBeast (Verde Pop + Emojis)"),
    ("tiktok", "\U0001F4F1 TikTok (Shake + Viral)"),
    ("capcut_creator", "PRO \u2022 CapCut Creator (Clean Pop)"),
    ("capcut_kinetic", "PRO \u2022 CapCut Kinetic (Bold Zoom)"),
    ("capcut_focus", "PRO \u2022 CapCut Focus (Center Highlight)"),
    ("capcut_podcast", "PRO \u2022 CapCut Podcast (Lower Third)"),
    ("capcut_luxury", "PRO \u2022 CapCut Luxury (Gold Editorial)"),
    ("minimalist", "\U0001F3A8 Minimalista (Limpio)"),
    ("documentary", "\U0001F4FA Documental (Cl\u00e1sico)"),
    ("gaming", "\U0001F3AE Gaming/Streaming (Verde + Pop)"),
    ("news", "\U0001F4F0 Noticiero (Profesional)"),
    ("cinematic", "\U0001F3AC Cinematogr\u00e1fico (Elegante)"),
    ("neon", "\U0001F495 Ne\u00f3n (Magenta + Shake)"),
    ("retro", "\U0001F579\ufe0f Retro 80s (Cyan + Pop)"),
    ("elegant", "\U0001F454 Elegante (Refinado)"),
    ("bold", "\U0001F4A5 Bold/Impact (Impactante)"),
    ("horror", "\U0001F480 Horror/Terror (Rojo + Shake)"),
    ("typewriter", "\u2328\ufe0f Typewriter (M\u00e1quina de escribir)"),
    ("fire", "\U0001F525 Fuego/Fire (Naranja + Bounce)"),
    ("ice", "\u2744\ufe0f Hielo/Ice (Azul helado)"),
    ("comic", "\U0001F4A2 Comic/Cartoon (Pop + Emojis)"),
    ("karaoke_party", "\U0001F3A4 Karaoke Party (Magenta + Bounce)"),
    ("whatsapp", "\U0001F4AC WhatsApp/Chat (Verde chat)"),
    ("glitch", "\U0001F916 Glitch/Cyberpunk (Verde terminal)"),
    ("handwritten", "\u270d\ufe0f Manuscrito/Handwritten (Papel)"),
    ("spotify", "\U0001F3B5 Spotify/Music (Verde Spotify)"),
    ("military", "\U0001F396\ufe0f Militar/Tactical (Naranja militar)"),
]

SUBTITLE_STYLE_LABELS: List[str] = [label for _key, label in SUBTITLE_STYLE_OPTIONS]
SUBTITLE_STYLE_LABEL_BY_KEY: Dict[str, str] = dict(SUBTITLE_STYLE_OPTIONS)
DEFAULT_SUBTITLE_STYLE_KEY = "hormozi"
DEFAULT_SUBTITLE_STYLE_LABEL = SUBTITLE_STYLE_LABEL_BY_KEY[DEFAULT_SUBTITLE_STYLE_KEY]


def _normalize_style(style: Optional[str]) -> str:
    try:
        from dynamic_subtitle_wrapper import normalize_subtitle_style

        return normalize_subtitle_style(style)
    except Exception:
        return str(style or "").strip().lower()


def get_subtitle_style_label(style: Optional[str]) -> str:
    """Return the UI label for an engine key, legacy value, or UI label."""
    normalized = _normalize_style(style)
    return SUBTITLE_STYLE_LABEL_BY_KEY.get(normalized, DEFAULT_SUBTITLE_STYLE_LABEL)
