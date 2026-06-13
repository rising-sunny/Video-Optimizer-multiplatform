"""
Recraft style catalog and normalization helpers.

This module keeps UI/backward-compatible style names and maps them to
style labels accepted by the current Recraft API.
"""

from typing import Dict, List


# Curated styles observed in current Recraft docs for raster/vector generation.
RECRAFT_STYLE_OPTIONS: List[str] = [
    "No style",
    "Any style",
    "Recraft V3 Raw",
    "Photorealism",
    "Illustration",
    "Vector art",
    "Icon",
    "Logo",
    "2D art poster",
    "3D render",
    "Pixel art",
    "Kawaii",
    "Color engraving",
    "Linocut",
    "Line art",
    "Hand-drawn",
    "Child book",
    "Noir",
    "Watercolor",
    "Retro Pop",
    "Modern Folk",
    "Urban Glow",
    "Hard Comics",
    "Pop art",
    "Pop Graphic",
    "Engraving",
    "Pictogram",
    "Outline details",
    "Sticker sheet",
    "Crosshatch",
    "Flat 2.0",
    "Isometric",
    "Isometric 3D",
    "Minimalism",
    "Block print",
    "Glow",
    "Marker drawing",
    "Doodle line art",
    "Pen drawing",
    "Vintage botanical",
    "Bold fantasy",
    "Psychedelic illustration",
    "Decorative line art",
    "Art Nouveau",
    "Faded nostalgia",
    "Microworlds",
    "Antiquarian",
]


LEGACY_STYLE_MAP: Dict[str, str] = {
    "realistic_image": "Photorealism",
    "realistic image": "Photorealism",
    "realistic": "Photorealism",
    "photorealism": "Photorealism",
    "recraft v3 raw": "Recraft V3 Raw",
    "digital_illustration": "Illustration",
    "digital illustration": "Illustration",
    "vector_illustration": "Vector art",
    "vector illustration": "Vector art",
    "illustration": "Illustration",
    "vector": "Vector art",
    "vector art": "Vector art",
    "logo_raster": "Logo",
    "logo": "Logo",
    "icon": "Icon",
    "3d": "3D render",
    "3d icon": "3D render",
    "isometric": "Isometric",
    "hand drawn": "Hand-drawn",
    "infantile sketch": "Child book",
    "sticker": "Sticker sheet",
    "line circuit": "Line art",
    # Legacy Recraft V2/V3 style groups
    "digital illustration/pixel art": "Pixel art",
    "digital illustration/hand drawn": "Hand-drawn",
    "digital illustration/grain": "Crosshatch",
    "digital illustration/infantile sketch": "Child book",
    "digital illustration/2d art poster": "2D art poster",
    "digital illustration/antiquarian": "Antiquarian",
    "digital illustration/handmade 3d": "3D render",
    "digital illustration/hand drawn outline": "Outline details",
    "digital illustration/engraving color": "Color engraving",
    "digital illustration/2d pixel art": "Pixel art",
    "digital illustration/cyberpunk": "Urban Glow",
    "digital illustration/comic book": "Hard Comics",
    "digital illustration/vintage propaganda": "Pop Graphic",
    "digital illustration/modern folk": "Modern Folk",
    "digital illustration/isometric": "Isometric",
    "digital illustration/japanese anime": "Kawaii",
    "digital illustration/kawaii style": "Kawaii",
    "digital illustration/logotype": "Logo",
    "digital illustration/marker outline": "Marker drawing",
    "digital illustration/medieval style": "Antiquarian",
    "digital illustration/neo baroque": "Art Nouveau",
    "digital illustration/noir": "Noir",
    "digital illustration/naturalistic": "Photorealism",
    "digital illustration/octane render": "3D render",
    "digital illustration/coloring book": "Outline details",
    "digital illustration/light retro": "Retro Pop",
    "digital illustration/line art": "Line art",
    "digital illustration/pictogram": "Pictogram",
    "digital illustration/pop art": "Pop art",
    "digital illustration/rubber hose": "Illustration",
    "digital illustration/sticker": "Sticker sheet",
    "digital illustration/storybook": "Child book",
    "digital illustration/tattoo design": "Illustration",
    "digital illustration/watercolor": "Watercolor",
    "digital illustration/flat 2.0": "Flat 2.0",
    "vector illustration/engraving": "Engraving",
    "vector illustration/line art": "Line art",
    "vector illustration/line circuit": "Line art",
    "vector illustration/linocut": "Linocut",
    # Spanish aliases used by UI/project
    "fotorrealista": "Photorealism",
    "cinematic": "Photorealism",
    "digital art": "Illustration",
    "anime": "Kawaii",
    "sketch": "Hand-drawn",
    "oil-painting": "Watercolor",
    "low-poly": "Isometric 3D",
    "ilustracion": "Illustration",
    "ilustracion digital": "Illustration",
    "vectorial": "Vector art",
    "acuarela": "Watercolor",
    "cartoon/animacion": "Hard Comics",
    "sketch/dibujo": "Hand-drawn",
    "minimalista": "Minimalism",
    "minimalista moderno": "Minimalism",
    "estilo artistico": "Illustration",
    "anime/manga": "Kawaii",
    "documental realista": "Photorealism",
    "cinematografico oscuro": "Noir",
    "terror atmosferico": "Noir",
    "epico historico": "2D art poster",
    "concept art": "Illustration",
}


VECTOR_STYLE_SET = {
    "Vector art",
    "Line art",
    "Linocut",
    "Engraving",
    "Pictogram",
    "Icon",
    "Logo",
    "Outline details",
    "Sticker sheet",
    "Decorative line art",
    "Doodle line art",
}


def _find_case_insensitive_style(value: str) -> str:
    key = value.casefold()
    for option in RECRAFT_STYLE_OPTIONS:
        if option.casefold() == key:
            return option
    return ""


def normalize_recraft_style(style: str) -> str:
    """Return a canonical style label accepted by Recraft API."""
    if not style:
        return "Photorealism"

    style_clean = str(style).strip()
    direct = _find_case_insensitive_style(style_clean)
    if direct:
        return direct

    mapped = LEGACY_STYLE_MAP.get(style_clean.casefold())
    if mapped:
        return mapped

    if "/" in style_clean:
        # Generic legacy group fallback: use right-hand side first, then left family.
        left, right = style_clean.split("/", 1)
        right_match = _find_case_insensitive_style(right.strip())
        if right_match:
            return right_match
        left_mapped = LEGACY_STYLE_MAP.get(left.strip().casefold())
        if left_mapped:
            return left_mapped

    return "Photorealism"


def is_vector_style(style: str) -> bool:
    """True when style belongs to vector/icon-style families."""
    return normalize_recraft_style(style) in VECTOR_STYLE_SET


def to_recraft_style_family(style: str) -> str:
    """
    Map style to a broader fallback style accepted by Recraft.
    """
    normalized = normalize_recraft_style(style)
    if normalized in ("No style", "Any style", "Recraft V3 Raw"):
        return "Photorealism"
    if normalized in ("Icon", "Logo", "Pictogram"):
        return "Icon"
    if normalized in VECTOR_STYLE_SET:
        return "Vector art"
    if normalized == "Photorealism":
        return "Photorealism"
    return "Illustration"

