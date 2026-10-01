# prompt_processor.py
"""
Procesador de prompts visuales
Maneja la aplicación de estilos, agrupación de segmentos y combinación de prompts
"""

import re
from typing import List, Dict

try:
    from ai.recraft_style_catalog import normalize_recraft_style
except Exception:
    def normalize_recraft_style(style: str) -> str:
        return str(style or "").strip()


class PromptProcessor:
    """
    Procesador de prompts visuales para storyboards.
    Maneja estilos, agrupación de segmentos y combinación de prompts.
    """
    
    def __init__(self, log_callback=None, gemini_client=None):
        """
        Inicializa el procesador de prompts.
        
        Args:
            log_callback: Función para logging (opcional)
            gemini_client: Cliente de Gemini AI para regeneración de prompts (opcional)
        """
        self.log = log_callback or (lambda msg: print(msg))
        self.gemini_client = gemini_client

    VERTEX_STYLE_MODIFIERS = {
        "No style": "",
        "Any style": "natural, visually coherent, clean composition",
        "Recraft V3 Raw": "natural lighting, raw photographic realism, grounded details",
        "Photorealism": "photorealistic, realistic lighting, detailed textures, believable materials",
        "Illustration": "polished digital illustration, editorial artwork, clean visual storytelling",
        "Vector art": "clean vector illustration, flat shapes, crisp contours, simplified geometry",
        "Icon": "minimal icon-style illustration, bold silhouette, clean graphic shape",
        "Logo": "clean symbolic mark, graphic minimalism, strong centered composition",
        "2D art poster": "bold poster illustration, graphic composition, high visual impact",
        "3D render": "high-quality 3D render, dimensional lighting, realistic depth",
        "Pixel art": "detailed pixel art, retro game aesthetic, readable shapes",
        "Kawaii": "cute stylized illustration, soft palette, charming character design",
        "Color engraving": "engraving-inspired illustration, etched texture, detailed linework",
        "Linocut": "linocut print aesthetic, bold carved shapes, high contrast",
        "Line art": "clean line art, precise outlines, minimal shading",
        "Hand-drawn": "hand-drawn illustration, organic linework, sketch-like detail",
        "Child book": "storybook illustration, warm playful mood, family-friendly artwork",
        "Noir": "moody noir atmosphere, dramatic shadows, cinematic contrast",
        "Watercolor": "watercolor painting, soft edges, layered pigments, painterly texture",
        "Retro Pop": "retro pop illustration, bright palette, nostalgic graphic energy",
        "Modern Folk": "modern folk illustration, decorative shapes, handcrafted feel",
        "Urban Glow": "cinematic urban night scene, neon accents, atmospheric glow",
        "Hard Comics": "bold comic-book illustration, graphic shadows, dynamic framing",
        "Pop art": "pop art aesthetic, vibrant color blocks, strong graphic contrast",
        "Pop Graphic": "graphic poster style, punchy color palette, bold forms",
        "Engraving": "engraving illustration, detailed etched lines, antique print texture",
        "Pictogram": "simple pictogram style, high readability, geometric minimalism",
        "Outline details": "outlined illustration, clean edge definition, simplified fills",
        "Sticker sheet": "sticker-style illustration, cutout look, clean contours",
        "Crosshatch": "crosshatched shading, detailed pen texture, illustrated depth",
        "Flat 2.0": "flat illustration, modern simplified shapes, clean visual hierarchy",
        "Isometric": "isometric illustration, structured geometry, clear spatial depth",
        "Isometric 3D": "isometric 3D illustration, dimensional forms, polished depth",
        "Minimalism": "minimalist composition, restrained detail, strong focal clarity",
        "Block print": "block print texture, bold shapes, tactile inked surface",
        "Glow": "soft luminous atmosphere, subtle bloom, cinematic glow",
        "Marker drawing": "marker-rendered illustration, bold strokes, vibrant fills",
        "Doodle line art": "playful doodle line art, sketchy details, casual illustration",
        "Pen drawing": "pen drawing, fine ink detail, crisp line structure",
        "Vintage botanical": "vintage botanical illustration, natural detail, antique scientific style",
        "Bold fantasy": "epic fantasy artwork, rich atmosphere, dramatic imaginative scene",
        "Psychedelic illustration": "psychedelic illustration, surreal palette, layered visual rhythm",
        "Decorative line art": "decorative line art, ornamental detail, elegant contours",
        "Art Nouveau": "art nouveau illustration, flowing ornamental lines, elegant period styling",
        "Faded nostalgia": "faded nostalgic mood, softened tones, memory-like atmosphere",
        "Microworlds": "tiny immersive worldbuilding, miniature environment detail, whimsical scale",
        "Antiquarian": "antiquarian illustration, aged historical texture, archival atmosphere",
    }

    def _dedupe_prompt_parts(self, parts: List[str]) -> str:
        result = []
        seen = set()
        for part in parts:
            clean = str(part or "").strip(" ,.")
            normalized = clean.casefold()
            if clean and normalized not in seen:
                result.append(clean)
                seen.add(normalized)
        return ", ".join(result)

    def _build_vertex_style_modifier(self, style: str) -> str:
        if not style:
            return ""

        normalized = normalize_recraft_style(style)
        modifier = self.VERTEX_STYLE_MODIFIERS.get(normalized)
        if modifier is not None:
            return modifier

        raw_style = str(style).strip()
        if not raw_style:
            return ""
        return f"{raw_style.lower()} style"

    def _looks_historical_prompt(self, prompt: str) -> bool:
        prompt_lower = str(prompt or "").lower()
        markers = (
            "ancient", "bronze age", "iron age", "pharaoh", "egypt", "egyptian",
            "sea peoples", "roman", "greek", "hittite", "mycenaean", "medieval",
            "historical", "battlefield", "warship", "temple", "inscription", "relief",
        )
        return any(marker in prompt_lower for marker in markers)

    def _contextualize_style_modifier(self, style: str, modifier: str, visual_prompt: str) -> str:
        normalized_style = normalize_recraft_style(style)
        prompt_lower = str(visual_prompt or "").lower()

        if normalized_style == "Urban Glow" and self._looks_historical_prompt(prompt_lower):
            return (
                "cinematic atmospheric glow, dramatic rim light, moody contrast, "
                "period-accurate historical setting, grounded ancient-world textures"
            )

        if normalized_style in {"Pop Graphic", "Retro Pop", "Hard Comics"} and self._looks_historical_prompt(prompt_lower):
            return (
                "cinematic historical illustration, dramatic contrast, bold readable composition, "
                "period-accurate details, no modern graphic design motifs"
            )

        return modifier

    def resolve_generation_style(self, style: str, visual_prompt: str, provider: str = "recraft") -> str:
        """
        Ajusta el estilo final que se enviará al proveedor cuando el estilo visual
        elegido es conceptualmente incompatible con el contenido del prompt.
        """
        normalized_style = normalize_recraft_style(style)
        provider_key = str(provider or "").strip().lower()

        if not self._looks_historical_prompt(visual_prompt):
            return normalized_style

        if normalized_style == "Urban Glow":
            return "Photorealism"

        if normalized_style in {"Pop Graphic", "Retro Pop", "Hard Comics", "Pop art"}:
            return "Illustration" if provider_key not in {"google_ai", "google", "gemini"} else style

        return normalized_style

    def adapt_prompt_for_provider(self, visual_prompt, style=None, provider="recraft"):
        provider_key = str(provider or "").strip().lower()
        if provider_key not in {"vertex_imagen", "vertex", "vertex_ai", "imagen_4_fast", "imagen4_fast", "imagen4"}:
            return self.apply_style_to_prompt(visual_prompt, style)

        prompt = str(visual_prompt or "").strip()
        if not prompt:
            return prompt

        style_modifier = self._contextualize_style_modifier(
            style,
            self._build_vertex_style_modifier(style),
            prompt,
        )
        prompt = re.sub(r"\brecraft v3 raw\b", "natural realism", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\bany style\b", "clean visual style", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\bno style\b", "", prompt, flags=re.IGNORECASE)

        extra_parts = [
            style_modifier,
            "single coherent scene",
            "clear focal subject",
            "high image fidelity",
        ]
        return self._dedupe_prompt_parts([prompt] + extra_parts)

    def _build_narrative_context(self, segments, index, window=2):
        """Construye una ventana narrativa simple para regeneración de prompts."""
        if not segments:
            return {}

        index = max(0, min(index, len(segments) - 1))

        def _seg_text(seg):
            return str(seg.get('narration_text') or seg.get('text') or seg.get('narration') or '').strip()

        def _join_text(items, max_chars):
            text = " ".join(_seg_text(seg) for seg in items if _seg_text(seg)).strip()
            if len(text) <= max_chars:
                return text
            return text[:max_chars].rstrip() + "..."

        prev_segments = segments[max(0, index - window):index]
        next_segments = segments[index + 1:index + 1 + window]
        total = len(segments)
        progress = (index + 1) / max(1, total)
        if progress <= 0.18:
            narrative_role = "opening setup or hook"
        elif progress <= 0.45:
            narrative_role = "early development"
        elif progress <= 0.72:
            narrative_role = "core explanation or escalation"
        elif progress <= 0.9:
            narrative_role = "late development or payoff"
        else:
            narrative_role = "closing beat or conclusion"

        return {
            "segment_range": f"segment {index + 1} of {total}",
            "narrative_role": narrative_role,
            "previous_context": _join_text(prev_segments, 280),
            "current_focus": _join_text([segments[index]], 360),
            "next_context": _join_text(next_segments, 280),
            "continuity_note": "Use previous and next beats only for continuity. Focus the image on the current narration.",
        }
    
    def group_segments_for_images(self, segments, images_per_segment_ratio=1.0):
        """
        Agrupa segmentos consecutivos para compartir una misma imagen.
        
        Args:
            segments: Lista de segmentos del storyboard
            images_per_segment_ratio: Ratio de imágenes por segmento
                - 1.0 = 1 imagen por segmento (comportamiento actual)
                - 2.0 = 1 imagen cada 2 segmentos (50% menos imágenes)
                - 3.0 = 1 imagen cada 3 segmentos (67% menos imágenes)
                - 4.0 = 1 imagen cada 4 segmentos (75% menos imágenes)
        
        Returns:
            Lista de grupos, donde cada grupo es una lista de segmentos que compartirán la misma imagen
        """
        if images_per_segment_ratio <= 1.0:
            # Sin agrupación: cada segmento tiene su propia imagen
            return [[seg] for seg in segments]
        
        groups = []
        current_group = []
        segments_per_image = int(images_per_segment_ratio)
        
        for i, seg in enumerate(segments):
            current_group.append(seg)
            
            # Si el grupo alcanza el tamaño deseado, o es el último segmento
            if len(current_group) >= segments_per_image or i == len(segments) - 1:
                groups.append(current_group)
                current_group = []
        
        return groups
    
    def apply_style_to_prompt(self, visual_prompt, style):
        """
        Aplica el estilo seleccionado al prompt visual.
        IMPORTANTE: Siempre aplica el estilo, reemplazando cualquier estilo previo.
        Esto permite cambiar el estilo al regenerar imágenes sin regenerar el storyboard.

        Args:
            visual_prompt: Prompt visual original
            style: Estilo seleccionado (ej: 'Documental Realista', 'Cinematográfico Oscuro', etc.)

        Returns:
            Prompt visual con el estilo aplicado, o sin tocar si el style es
            "No style" / vacío / valor desconocido (evita inyectar el literal
            "No style" o cualquier otra cadena cruda en el prompt final).
        """
        if not visual_prompt or not style:
            return visual_prompt

        # Sentinela del dropdown de la GUI cuando el usuario NO quiere un estilo.
        # Antes este literal se inyectaba como tag al prompt — confundía a FLUX
        # y a otros modelos al verse como un keyword "No style" sin significado.
        normalized_style = str(style).strip().lower()
        if normalized_style in {"no style", "none", "default", "n/a", "ninguno"}:
            return visual_prompt
        
        # Mapeo de estilos (nombres en español de la UI) a modificadores de prompt
        style_modifiers = {
            # Estilos de la UI (nombres exactos)
            'Cinematográfico Oscuro': 'cinematic, dramatic lighting, film grain, professional cinematography, 8K quality, dark mood, high contrast',
            'Documental Realista': 'documentary style, realistic, natural lighting, authentic, photojournalistic, candid, unposed',
            'Terror Atmosférico': 'horror atmosphere, dark, eerie, moody lighting, cinematic horror, suspenseful, ominous',
            'Épico Histórico': 'epic historical, grand scale, dramatic composition, cinematic, period accurate, detailed costumes',
            'Minimalista Moderno': 'minimalist, clean composition, simple, elegant, uncluttered, modern, geometric',
            'Ilustración Digital': 'digital illustration, stylized, vibrant colors, clean lines, modern art style',
            'Cartoon/Animación': 'animated style, vibrant colors, cartoon aesthetic, stylized illustration, playful',
            'Anime/Manga': 'anime style, manga aesthetic, vibrant colors, expressive, stylized, Japanese animation',
            'Estilo Artístico': 'artistic, painterly style, creative interpretation, stylized, unique composition',
            'Acuarela': 'watercolor style, soft edges, flowing colors, artistic, painterly, delicate',
            'Vectorial': 'vector art style, clean lines, flat colors, geometric, modern illustration',
            'Sketch/Dibujo': 'sketch style, pencil drawing, rough lines, artistic, hand-drawn aesthetic',
            # Compatibilidad con nombres en inglés (fallback)
            'Cinematic': 'cinematic, dramatic lighting, film grain, professional cinematography, 8K quality',
            'Documentary': 'documentary style, realistic, natural lighting, authentic, photojournalistic',
            'Animated': 'animated style, vibrant colors, cartoon aesthetic, stylized illustration',
            'Minimalist': 'minimalist, clean composition, simple, elegant, uncluttered',
            'Vintage': 'vintage style, retro aesthetic, film photography, aged look, nostalgic',
            'Futuristic': 'futuristic, sci-fi aesthetic, high-tech, cyberpunk, neon lighting',
            'Artistic': 'artistic, painterly style, creative interpretation, stylized, unique composition',
            'Realistic': 'photorealistic, highly detailed, natural lighting, accurate representation'
        }
        
        # Compatibilidad con etiquetas legacy de Recraft usadas en proyectos guardados.
        style_modifiers.update({
            'Digital illustration/Engraving color': 'digital illustration in engraving color style',
            'Digital illustration/Line art': 'digital illustration line art style',
            'Digital illustration/Comic book': 'comic book illustration style',
            'Digital illustration/Noir': 'noir illustration style',
            'Digital illustration/Watercolor': 'watercolor illustration style',
            'Illustration': 'illustration style',
            'Photorealism': 'photorealistic, natural lighting, realistic details',
            'Color engraving': 'color engraving illustration style',
            'Line art': 'line art style',
            'Vector art': 'vector art style, clean lines, geometric composition'
        })

        # Obtener modificador de estilo. Si el estilo NO está en el lookup, NO
        # inyectar el texto crudo (eso producía artefactos como ", No style," en
        # el prompt enviado al modelo). En ese caso devolvemos el prompt sin tocar.
        if style not in style_modifiers:
            return visual_prompt
        style_modifier = style_modifiers[style]
        style_modifier = self._contextualize_style_modifier(style, style_modifier, visual_prompt)

        cleaned_prompt = visual_prompt.strip()

        # Solo remover modificadores de estilo previamente agregados AL FINAL.
        # Evita borrar palabras descriptivas válidas dentro del prompt.
        known_modifiers = set(style_modifiers.values())
        for modifier in sorted(known_modifiers, key=len, reverse=True):
            suffix_pattern = r'(?:,\s*)?' + re.escape(modifier) + r'\s*$'
            new_prompt = re.sub(suffix_pattern, '', cleaned_prompt, flags=re.IGNORECASE).strip(' ,')
            if new_prompt != cleaned_prompt:
                cleaned_prompt = new_prompt
                break

        if cleaned_prompt and re.search(
            r'(?:,\s*)?' + re.escape(style_modifier) + r'\s*$',
            cleaned_prompt,
            flags=re.IGNORECASE
        ):
            return cleaned_prompt

        if cleaned_prompt and style_modifier.casefold() in cleaned_prompt.casefold():
            return cleaned_prompt

        if cleaned_prompt:
            return f"{cleaned_prompt}, {style_modifier}"
        return style_modifier
    
    def regenerate_visual_prompts_with_style(self, storyboard_data, style):
        """
        Regenera los visual_prompts de todos los segmentos con el nuevo estilo.
        Esto garantiza que el estilo se aplique desde el inicio, sin intentar
        remover estilos previos de prompts existentes.
        
        Args:
            storyboard_data: Diccionario con los datos del storyboard
            style: Nuevo estilo a aplicar (ej: 'Documental Realista', 'Cinematográfico Oscuro')
        
        Returns:
            storyboard_data con los visual_prompts actualizados
        """
        if not self.gemini_client:
            self.log("️ Gemini client no disponible, no se pueden regenerar los prompts")
            return storyboard_data
        
        segments = storyboard_data.get('segments', [])
        if not segments:
            return storyboard_data
        
        topic = storyboard_data.get('topic', '')
        category = storyboard_data.get('category', 'general')
        full_script = storyboard_data.get('script', '')
        # Heredar long-form horizontal desde el storyboard si existe
        is_long_horizontal = (
            str(storyboard_data.get('generation_profile') or '').lower() == 'long_horizontal'
            or str(storyboard_data.get('platform') or '').lower() == 'youtube'
        )

        self.log(f"\n Regenerando visual_prompts con estilo '{style}'...")
        self.log(f"    {len(segments)} segmentos a regenerar")
        if is_long_horizontal:
            self.log("    Modo: long horizontal 16:9 (composicion cinematografica activa)")

        for i, segment in enumerate(segments, 1):
            narration_text = segment.get('narration_text') or segment.get('text', '')
            if not narration_text:
                continue

            self.log(f"   ... Regenerando prompt {i}/{len(segments)}")
            narrative_context = self._build_narrative_context(segments, i - 1)

            # Regenerar prompt visual con el nuevo estilo
            prompt_data = self.gemini_client.generate_prompts_for_segment(
                narration_text, category, style,
                topic=topic,
                full_script=full_script,
                research_context=None,  # No hay investigación para regeneración
                narrative_context=narrative_context,
                is_long_horizontal=is_long_horizontal,
            )
            
            if prompt_data and 'visual_prompt' in prompt_data:
                segment['visual_prompt'] = prompt_data['visual_prompt']
                # También actualizar sfx_tag y overlay_tag si están disponibles
                if 'sfx_tag' in prompt_data:
                    segment['sfx_tag'] = prompt_data['sfx_tag']
                if 'overlay_tag' in prompt_data:
                    segment['overlay_tag'] = prompt_data['overlay_tag']
        
        self.log(f" Visual_prompts regenerados con estilo '{style}'")
        return storyboard_data
    
    def combine_prompts(self, segment_group):
        """
        Devuelve el prompt visual del segmento líder del grupo.

        Cuando varios segmentos comparten una imagen, usamos el visual_prompt del
        PRIMER segmento como prompt único. La estrategia anterior de extraer 5
        palabras random (>4 caracteres) del resto y pegarlas como "incorporating
        elements: ..." era una fuente importante de basura: producía tokens sin
        contexto como "roger" (de "Roger Deakins"), "signs" (de "no signs",
        invirtiendo el sentido de la negación), "faces" o "natural", que FLUX
        interpretaba como pesos extra → escenas degeneradas (p. ej. solo manos
        renderizadas, sujeto principal omitido).

        Args:
            segment_group: Lista de segmentos que comparten una imagen.

        Returns:
            str: visual_prompt del líder, o '' si ninguno tiene prompt.
        """
        if not segment_group:
            return ''
        for seg in segment_group:
            vp = seg.get('visual_prompt')
            if vp:
                return vp
        return ''


