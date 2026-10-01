# -*- coding: utf-8 -*-
"""Formato de la miniatura: 16:9 (long-form) o 9:16 (Shorts).

Todo el subsistema de thumbnails nacio clavado en 16:9 -- 1280x720 en el
compositor, `width=1280, height=720` en los cuatro proveedores de imagen,
"horizontal 16:9" en los prompts que van al LLM, y un validador que mide el
TERCIO IZQUIERDO. Generar una miniatura para un Short daba una imagen
apaisada que YouTube recorta al centro: se perdia la mitad del encuadre.

Este modulo es el unico lugar que sabe de geometria. Es puro (no importa PIL
ni clientes de imagen) para poder testearlo: ver `test_thumbnail_formats.py`.

Por que las reglas de 9:16 NO son las de 16:9 giradas:

- La grilla de Shorts NO muestra la miniatura en 9:16. MEDIDO sobre la
  grilla real (2026-09-02, canal publico, desktop y movil): la tarjeta es
  186x278 / 214x321, o sea 2:3 exacto, con `object-fit: cover` y
  `object-position: 50% 50%`. Sobre un 1080x1920 eso recorta 150 px
  ARRIBA y 150 px ABAJO (7.8% de cada lado).
- Encima de ese recorte, en MOVIL el titulo y las vistas se superponen
  desde el 75.2% de la tarjeta hacia abajo (en desktop el titulo va
  debajo de la imagen y no tapa nada). Llevado al asset original, la
  banda utilizable va de y=7.8% a y=71.3%.
- Y la miniatura NO aparece en el feed vertical deslizable, que arranca
  el video al instante: se ve en la pagina del canal, en busqueda, en
  las paginas de hashtag/audio y en la estanteria de Shorts del inicio.
- La convencion de 16:9 (sujeto en el tercio izquierdo, aire a la derecha
  para que el ojo lea el titulo) no existe en vertical: el ojo recorre la
  imagen de arriba hacia abajo, no de izquierda a derecha.
- Un encuadre vertical se ve a ~200 px de ancho en la grilla del telefono.
  La cara tiene que ocupar mas fraccion del ancho que en apaisado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

# Reglas comunes a los dos formatos: iluminacion, paleta, realismo y epoca.
# Nada de esto depende del encuadre, asi que no se duplica.
_SHARED_RULES: Tuple[str, ...] = (
    "overall mean luminance in the 100-150 range (never dark underexposed, never washed out)",
    "warm dominant palette: burnt orange, amber, sepia, firelight tones (#6b4a2e to #c0562a range), cool desaturated teal or charcoal only as background counter",
    "average red channel stronger than average blue channel by 15+ points (warm temperature signature)",
    "high tonal range: no single luminance bin over 25% of pixels, real deep shadows and real highlights",
    "cinematic three-point lighting: warm rim light on subject (sunset, firelight, oil lamp, explosion glow), cool ambient background, atmospheric haze or smoke for depth",
    "shallow depth of field, foreground subject sharp, midground softly blurred, background with volumetric haze",
    # La regla vieja pedia "readable emotion on the central figure: dilated
    # pupils, tense jaw, 1000-yard stare". Eso obliga a poner una cara
    # grande al centro, y todas las miniaturas terminaban siendo el mismo
    # retrato generico de IA. El drama sale de otro lado.
    "the drama comes from light, weather, scale and decay -- not from an actor's expression: raking low sun, dust in the air, smoke, rain, erosion, torchlight, wet stone",
    "avoid the generic AI-thumbnail look: no person centred and staring at the camera, no symmetrical bust framing, no studio-lit model pose, no smiling subject, no hero standing with arms at their sides",
    "photoreal cinematic style, 50mm lens look, subtle film grain, not AI-smooth, not plastic, not digital painting",
    "every visible element (weapons, uniforms, props, architecture) strictly period-accurate to the story era; zero anachronisms",
)


@dataclass(frozen=True)
class ThumbnailFormat:
    """Geometria + reglas de encuadre de un formato de miniatura."""

    key: str
    label: str
    width: int
    height: int
    aspect_label: str
    prompt_constraint: str
    llm_brief: str
    framing_rules: Tuple[str, ...]
    default_composition: str
    text_boxes: Mapping[str, Tuple[float, float, float, float]]
    # Eje y zona donde debe vivir el sujeto, para el validador. "y" mide
    # tercios de arriba a abajo; "x", de izquierda a derecha. En los dos
    # formatos el sujeto va en el PRIMER tercio y el aire en el ULTIMO.
    subject_axis: str = "x"
    subject_zone_label: str = "izquierdo"
    calm_zone_label: str = "derecho"
    # Fracciones del alto que se pierden por recorte de la grilla o por la
    # UI de la plataforma. Arriba solo se pierde por recorte; abajo, por
    # recorte MAS el titulo y las vistas superpuestos en movil.
    ui_reserved_top: float = 0.0
    ui_reserved_bottom: float = 0.0
    comfy_preset: str = "thumbnail_16x9_schnell"
    composition_aliases: Mapping[str, str] = field(default_factory=dict)
    # Coletillas propias del formato; vacio = se usa la de la receta.
    variant_suffixes: Mapping[str, str] = field(default_factory=dict)

    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @property
    def aspect_ratio(self) -> float:
        return self.width / float(self.height)

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width

    @property
    def composition_rules(self) -> Tuple[str, ...]:
        """Reglas para el prompt: encuadre propio del formato + comunes."""
        return tuple(self.framing_rules) + _SHARED_RULES

    def resolve_composition(self, composition: Optional[str]) -> str:
        """Traduce el nombre de composicion que eligio el LLM a uno valido.

        El LLM sigue pudiendo devolver nombres pensados para 16:9
        ('subject_left_text_right'); en vertical no significan nada, pero
        tampoco tienen que romper: se mapean al equivalente vertical.
        """
        nombre = str(composition or "").strip().lower()
        if nombre in self.text_boxes:
            return nombre
        alias = self.composition_aliases.get(nombre)
        if alias and alias in self.text_boxes:
            return alias
        return self.default_composition

    def text_box_pixels(self, composition: Optional[str]) -> Tuple[int, int, int, int]:
        """Caja de texto en pixeles para este formato.

        Se guarda en fracciones y no en pixeles justamente para que cambiar de
        formato no exija reescribir cada coordenada.
        """
        left, top, right, bottom = self.text_boxes[self.resolve_composition(composition)]
        return (
            int(round(left * self.width)),
            int(round(top * self.height)),
            int(round(right * self.width)),
            int(round(bottom * self.height)),
        )

    def variant_suffix(self, composition: Optional[str], fallback: Optional[str] = None) -> str:
        """Coletilla de la variante, reescrita para este formato.

        `DEFAULT_VARIANT_RECIPES` describe las variantes en terminos apaisados
        ("hero subject on the left third, open dark space on the right"). En un
        9:16 eso CONTRADICE las reglas de encuadre del propio formato, y el
        generador recibe dos ordenes opuestas en el mismo prompt.
        """
        propia = self.variant_suffixes.get(self.resolve_composition(composition))
        return propia or str(fallback or "").strip()

    def text_render_directives(self, hook: str = "{short_text}") -> tuple:
        """Instrucciones para que la IA de imagen DIBUJE el texto en la miniatura.

        Los generadores modernos (Recraft V3, gpt-image, Ideogram, Flux) escriben
        texto legible si se les da la palabra exacta entre comillas, una familia
        tipografica y un tamano relativo. Lo que los hace fallar es pedir texto
        "generico" o dejarlo librado.

        2026-09-23: el tamano, el peso, el color y el contorno ya no son fijos
        ("small and restrained" daba 2.6% de alto de letra): salen del plan de
        `thumbnail_typography`, calibrado con los shorts de historia mas vistos.
        """
        from publish.thumbnail_typography import generic_directives, plan_typography, typography_directives
        if not hook or hook == "{short_text}":
            return generic_directives(self, hook=hook or "{short_text}")
        return typography_directives(plan_typography(hook, self))

    def text_alignment(self, composition: Optional[str]) -> str:
        """Centrado cuando la caja ocupa casi todo el ancho; si no, izquierda."""
        left, _, right, _ = self.text_boxes[self.resolve_composition(composition)]
        return "center" if (right - left) >= 0.80 else "left"


LANDSCAPE_16_9 = ThumbnailFormat(
    key="landscape",
    label="16:9 (video largo)",
    width=1280,
    height=720,
    aspect_label="16:9",
    prompt_constraint="horizontal 16:9 YouTube thumbnail, 1920x1080",
    llm_brief="The thumbnail is horizontal 16:9 for the YouTube browse/search feed.",
    framing_rules=(
        "the subject is the HISTORICAL THING ITSELF -- the structure, the artifact, the terrain, the moment -- not a portrait; a human face is NOT the default subject",
        "rule of thirds composition, dominant subject anchored in the LEFT third of the frame (x 0-33%), occupying ~35-45% of image height",
        "if a human figure appears it is small and gives scale: from behind or in silhouette, never centred, never facing the camera, never posed",
        "upper-right third kept visually calm (sky, smoke, dust, darkness) as negative space for a later text overlay",
        "LEFT third clearly brighter than the RIGHT third by ~20+ luminance points: warm key light on the subject, cooler and darker background on the right",
        "at least 55% of visible fine detail and high-contrast edges concentrated in the LEFT third (the subject lives there)",
    ),
    default_composition="subject_left_text_right",
    text_boxes={
        # Fracciones equivalentes a las cajas en pixeles que ya usaba el
        # compositor sobre 1280x720: el rendering apaisado no cambia.
        "subject_left_text_right": (0.5625, 0.16667, 0.96094, 0.86111),
        "subject_right_text_left": (0.03906, 0.16667, 0.43750, 0.86111),
        "text_top_center": (0.09375, 0.05556, 0.90625, 0.36111),
    },
    subject_axis="x",
    subject_zone_label="izquierdo",
    calm_zone_label="derecho",
    ui_reserved_bottom=0.0,
    comfy_preset="thumbnail_16x9_schnell",
)


SHORT_9_16 = ThumbnailFormat(
    key="short",
    label="9:16 (Short)",
    width=1080,
    height=1920,
    aspect_label="9:16",
    prompt_constraint="vertical 9:16 YouTube Shorts thumbnail, 1080x1920",
    llm_brief=(
        "The thumbnail is vertical 9:16 for the YouTube Shorts grid. The grid "
        "center-crops it to 2:3 and then overlays the title and view count on "
        "mobile, so only the band between 8% and 71% of the height is safe: "
        "nothing important above or below that."
    ),
    framing_rules=(
        # El sujeto arriba, no a la izquierda: en vertical el ojo baja.
        "the subject is the HISTORICAL THING ITSELF -- the structure, the artifact, the terrain, the moment -- framed so it reads instantly at 190px wide in the Shorts grid; a human face is NOT the default subject",
        "if a human figure appears at all it is SMALL and exists only to give scale: seen from behind or as a silhouette, off-centre, under 25% of the frame height, never facing the camera, never making eye contact, never posed",
        "the dominant subject occupies the band between y 12% and y 62%, filling the width",
        "top 8% of the frame carries nothing important: the Shorts grid crops the 9:16 image to 2:3 and cuts it away",
        "bottom 29% of the frame (y 71-100%) kept dark, calm and empty: part is cropped by the same 2:3 crop and the rest is covered by the title and view count on mobile",
        "the visible band clearly brighter than the bottom by ~20+ luminance points: warm key light high on the subject, deep shadow falling off toward the bottom edge",
        "at least 55% of visible fine detail and high-contrast edges concentrated in the UPPER third (the subject lives there, the bottom is negative space)",
        "single subject filling the vertical frame; no wide horizontal panorama, no letterboxing, no split screen",
    ),
    default_composition="text_top",
    text_boxes={
        # Todo dentro de la banda MEDIDA [0.078, 0.713]. La caja de arriba
        # empezaba en 0.05 y le comian el borde superior: el 7.8% de arriba
        # no sobrevive al recorte 2:3 de la grilla.
        "text_top": (0.06, 0.11, 0.94, 0.30),
        "text_upper_mid": (0.06, 0.21, 0.94, 0.41),
        "text_lower_safe": (0.06, 0.50, 0.94, 0.70),
    },
    variant_suffixes={
        "text_top": "close-up hero subject filling the middle band of the vertical frame, "
                    "open dark space along the bottom third for the YouTube title overlay",
        "text_upper_mid": "hero subject high in the vertical frame with the dramatic action "
                          "reading downward, dark calm base at the bottom",
        "text_lower_safe": "hero subject at the top of the vertical frame, mid-frame kept "
                           "readable for hook text, bottom fifth dark and empty",
    },
    subject_axis="y",
    subject_zone_label="superior",
    calm_zone_label="inferior",
    ui_reserved_top=0.078,
    ui_reserved_bottom=0.287,
    comfy_preset="thumbnail_9x16_schnell",
    composition_aliases={
        # Los nombres apaisados que puede devolver el LLM siguen funcionando.
        "subject_left_text_right": "text_top",
        "subject_right_text_left": "text_upper_mid",
        "text_top_center": "text_top",
    },
)


FORMATS: Dict[str, ThumbnailFormat] = {
    LANDSCAPE_16_9.key: LANDSCAPE_16_9,
    SHORT_9_16.key: SHORT_9_16,
}

# La PLATAFORMA manda sobre el aspect ratio del video, y no es lo mismo.
# Caso real de esta app: '9:16 - Vertical Largo (>3 min, YouTube)' produce un
# VIDEO vertical, pero como dura mas de 3 minutos NO es un Short: aparece en el
# feed normal de YouTube, donde la miniatura sigue siendo 16:9. Resolver por
# aspect ratio le habria dado una miniatura vertical que nadie ve asi.
_PLATFORM_VERTICAL = ("short", "reel", "tiktok")
_PLATFORM_HORIZONTAL = ("youtube_vertical", "youtube_long", "square", "youtube")

_VERTICAL_TOKENS = ("9:16", "9x16", "vertical", "short", "reel", "tiktok", "portrait")
_HORIZONTAL_TOKENS = ("16:9", "16x9", "horizontal", "landscape", "long_form", "longform")

# Un Short dura como mucho 3 minutos; por encima de eso es long-form.
SHORT_MAX_DURATION_S = 180


def resolve_format(
    video_format: Any = None,
    platform: Any = None,
    duration: Any = None,
    project_data: Optional[Mapping[str, Any]] = None,
) -> ThumbnailFormat:
    """Elige el formato de miniatura a partir de lo que sepa el proyecto.

    Orden de confianza: lo que diga explicitamente el formato/plataforma
    primero, y la duracion solo como ultimo recurso. Un proyecto de 80s
    marcado como long-form es raro pero posible (un teaser); la etiqueta
    explicita gana.

    Ante la duda devuelve 16:9, que es el comportamiento historico: un
    default nuevo no deberia cambiar en silencio las miniaturas de los
    videos largos que ya funcionaban.
    """
    datos: Mapping[str, Any] = project_data or {}
    # La GUI guarda el formato en project_data['config'], no en la raiz: mirar
    # solo la raiz devolvia 16:9 para un proyecto de Short perfectamente
    # etiquetado.
    config: Mapping[str, Any] = datos.get("config") or {}

    def _buscar(*claves):
        for fuente in (datos, config):
            for clave in claves:
                valor = fuente.get(clave)
                if valor not in (None, ""):
                    return valor
        return None

    if video_format is None:
        video_format = _buscar("video_format", "aspect_ratio", "format")
    if platform is None:
        platform = _buscar("platform", "target_platform", "platform_key")
    if duration is None:
        duration = _buscar("duration", "duration_seconds")

    # 1) La plataforma primero: es la unica senal que distingue un Short de un
    #    video vertical largo, que comparten el mismo 9:16.
    plataforma = str(platform or "").strip().lower()
    if plataforma:
        if any(token in plataforma for token in _PLATFORM_VERTICAL):
            return SHORT_9_16
        if any(token in plataforma for token in _PLATFORM_HORIZONTAL):
            return LANDSCAPE_16_9

    # 2) Recien despues el aspect ratio del video.
    senales = str(video_format or "").strip().lower()
    if any(token in senales for token in _VERTICAL_TOKENS):
        return SHORT_9_16
    if any(token in senales for token in _HORIZONTAL_TOKENS):
        return LANDSCAPE_16_9

    try:
        segundos = float(duration or 0)
    except (TypeError, ValueError):
        segundos = 0.0
    if 0 < segundos <= SHORT_MAX_DURATION_S:
        return SHORT_9_16

    return LANDSCAPE_16_9


def get_format(key: Any) -> ThumbnailFormat:
    """Formato por clave ('landscape' / 'short'); 16:9 si no se reconoce."""
    return FORMATS.get(str(key or "").strip().lower(), LANDSCAPE_16_9)


__all__ = [
    "ThumbnailFormat",
    "LANDSCAPE_16_9",
    "SHORT_9_16",
    "FORMATS",
    "SHORT_MAX_DURATION_S",
    "resolve_format",
    "get_format",
]
