# claude_client.py
# Cliente para interactuar con Claude Code CLI (ejecuciÃ³n local sin API key)
# Usa Groq como IA principal y Claude Code CLI como fallback automÃ¡tico

import os
import subprocess
import shutil
import platform
import json
import re
from studio_categories import is_mystery_inquiry, mystery_editorial_instructions


def get_channel_name(default: str = "this channel") -> str:
    """Nombre visible del canal, leido del Channel Bible.

    Import perezoso: este modulo se carga antes que el perfil en algunos flujos.
    """
    try:
        from channel.channel_strategy import get_channel_name as _real
        return _real(default)
    except Exception:
        return default


# Importar Groq como backend unico
try:
    from ai.groq_client import GroqAiClient
    GROQ_AVAILABLE = True
except ImportError:
    GroqAiClient = None
    GROQ_AVAILABLE = False

# Shared tone-profile mapping (single source of truth; also used by storyboard_generator)
try:
    from ai.tone_profile import get_tone_profile_for_category
except ImportError:
    # Defensive fallback so this file still loads if tone_profile.py is missing.
    def get_tone_profile_for_category(category):  # noqa: D401
        return "documentary"
    print("âš ï¸ groq_client.py no encontrado. Groq fallback no estarÃ¡ disponible.")

def load_env_file():
    """Cargar manualmente variables desde .env"""
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Remover comillas si existen
                    value = value.strip('"\'')
                    os.environ[key] = value

# Cargar variables de entorno desde .env
load_env_file()


_LLM_REFUSAL_RE = re.compile(
    r"(i['’]?m sorry[\s,]+but i can['’]?t fulfill|"
    r"i can(?:not|['’]?t)\s+fulfill that request|"
    r"i can(?:not|['’]?t)\s+assist with|"
    r"i can(?:not|['’]?t)\s+help with that|"
    r"i must decline|"
    r"as an ai (?:language )?model|"
    r"i(?: am|'m) not able to (?:fulfill|comply|write|create)|"
    r"lo siento[, ]+no puedo (?:cumplir|ayudar)|"
    r"no puedo (?:cumplir|acceder a) (?:esa|esta) (?:solicitud|petici[oó]n))",
    re.IGNORECASE,
)


def is_llm_refusal(text) -> bool:
    """True when the model returned a refusal instead of a narration script."""
    if not text or not isinstance(text, str):
        return False
    sample = text.strip()
    if not sample:
        return False
    if _LLM_REFUSAL_RE.search(sample[:500]):
        return True
    return len(sample.split()) <= 40 and bool(_LLM_REFUSAL_RE.search(sample))


def target_word_budget(duration_seconds) -> int:
    try:
        return int((max(1, int(duration_seconds)) / 60.0) * 150)
    except Exception:
        return 150


def minimum_script_words(duration_seconds, target_words=None) -> int:
    """Minimum usable narration length for this runtime."""
    target = int(target_words if target_words is not None else target_word_budget(duration_seconds))
    try:
        duration = int(duration_seconds)
    except Exception:
        duration = 60
    if duration <= 90:
        return max(25, int(target * 0.30))
    if duration < 600:
        return max(80, int(target * 0.30))
    return max(200, int(target * 0.28))


def script_is_too_short(script, duration_seconds, target_words=None) -> bool:
    if not script or not isinstance(script, str) or is_llm_refusal(script):
        return True
    return len(script.split()) < minimum_script_words(duration_seconds, target_words)


def _ascii_hook(texto: str) -> str:
    """Titular de miniatura en MAYUSCULAS y ASCII puro.

    Red de seguridad por si el LLM ignora la instruccion de escribirlo en
    ingles sin tildes: las IA de imagen se equivocan con los acentos. Caso
    real (2026-09-03): se pidio "6 PIRAMIDES" y la imagen volvio diciendo
    "6 PIRAMIDAS".
    """
    import unicodedata

    limpio = str(texto or "").strip().strip('"').strip("'").strip()
    # NFKD separa la tilde de la letra; al descartar los combinantes queda ASCII.
    plano = "".join(
        c for c in unicodedata.normalize("NFKD", limpio)
        if not unicodedata.combining(c)
    )
    return " ".join(plano.split()).upper()


def build_copyable_prompt(positive: str, negative: str = "") -> str:
    """Positivo + negativo en UN solo texto para copiar de una.

    La mayoria de las IA de imagen que se usan a mano (gpt-image, Gemini,
    Midjourney en chat) toman un unico bloque: copiar y pegar dos veces es un
    paso de mas y se presta a pegar solo la mitad.

    El negativo va como una linea en ingles y en imperativo porque asi lo
    entienden los modelos conversacionales; los que tienen campo negativo
    aparte lo ignoran sin romperse.
    """
    positivo = " ".join(str(positive or "").split())
    negativo = " ".join(str(negative or "").split())
    if not negativo:
        return positivo
    return f"{positivo}\n\nDo NOT include: {negativo}"


class ClaudeAiClient:
    """
    Cliente para interactuar con Claude Code CLI (ejecuciÃ³n local).
    NO requiere API key, ejecuta Claude Code CLI como proceso local.
    Usa Groq como IA principal y Claude Code CLI como fallback automÃ¡tico.
    """
    def __init__(self):
        self.claude_cmd = None
        # Cache para anÃ¡lisis histÃ³rico (evita repetir anÃ¡lisis para el mismo tema/script)
        self._historical_context_cache = {}
        self.client_available = False
        
        # Inicializar Groq como IA principal
        self.groq_client = None
        if GROQ_AVAILABLE and GroqAiClient:
            try:
                self.groq_client = GroqAiClient()
                if self.groq_client and self.groq_client.client:
                    self.client_available = True
                    print("âœ… Groq inicializado como IA principal")
                else:
                    print("âš ï¸ Groq no estÃ¡ configurado (falta GROQ_API_KEY en .env)")
            except Exception as e:
                print(f"âš ï¸ Error inicializando Groq: {e}")
        
        # Inicializar Claude Code CLI como fallback
        if self.claude_cmd:
            print(f"âœ… Claude Code CLI encontrado como fallback: {self.claude_cmd}")
            # Si hay al menos un cliente disponible (Groq o Claude), marcar como disponible
            if (self.groq_client and self.groq_client.client) or self.claude_cmd:
                self.client_available = True

    @property
    def client(self):
        return self.groq_client.client if self.groq_client else None

    def _truncate_context_text(self, value, max_chars=320):
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    def _format_narrative_context(self, narrative_context):
        if not narrative_context:
            return ""

        if isinstance(narrative_context, str):
            clean_text = self._truncate_context_text(narrative_context, max_chars=900)
            if clean_text:
                return f"\nNARRATIVE CONTEXT WINDOW:\n{clean_text}\n"
            return ""

        if not isinstance(narrative_context, dict):
            return ""

        lines = ["\nNARRATIVE CONTEXT WINDOW:"]

        segment_range = narrative_context.get("segment_range")
        if segment_range:
            lines.append(f"- Segment Position: {segment_range}")

        narrative_role = narrative_context.get("narrative_role")
        if narrative_role:
            lines.append(f"- Narrative Role: {narrative_role}")

        previous_context = self._truncate_context_text(
            narrative_context.get("previous_context", ""),
            max_chars=280
        )
        if previous_context:
            lines.append(f"- What Just Happened Before: {previous_context}")

        current_focus = self._truncate_context_text(
            narrative_context.get("current_focus", ""),
            max_chars=420
        )
        if current_focus:
            lines.append(f"- Current Narration Focus: {current_focus}")

        next_context = self._truncate_context_text(
            narrative_context.get("next_context", ""),
            max_chars=280
        )
        if next_context:
            lines.append(f"- What Happens Next: {next_context}")

        continuity_note = self._truncate_context_text(
            narrative_context.get("continuity_note", ""),
            max_chars=220
        )
        if continuity_note:
            lines.append(f"- Continuity Note: {continuity_note}")

        if len(lines) == 1:
            return ""
        return "\n".join(lines) + "\n"

    def _is_unspecified_context_value(self, value):
        text = str(value or "").strip().lower()
        return not text or text in {"not specified", "unknown", "none", "n/a", "unspecified"}

    def _normalize_historical_analysis(self, analysis):
        if not isinstance(analysis, dict):
            return None

        list_fields = ("key_historical_elements", "forbidden_elements")
        for field in list_fields:
            value = analysis.get(field)
            if isinstance(value, str):
                analysis[field] = [item.strip() for item in value.split(",") if item.strip()]
            elif not isinstance(value, list):
                analysis[field] = []

        has_specific_context = any(
            not self._is_unspecified_context_value(analysis.get(key))
            for key in (
                "time_period",
                "latest_allowed_year",
                "location",
                "cultural_context",
                "technology_level",
                "clothing_style",
                "architecture_style",
            )
        )
        has_specific_context = has_specific_context or bool(analysis.get("key_historical_elements"))

        analysis["is_historical"] = bool(analysis.get("is_historical"))
        analysis["has_temporal_constraints"] = bool(
            analysis.get("has_temporal_constraints") or has_specific_context
        )

        if not analysis["has_temporal_constraints"]:
            return None
        return analysis

    def _build_historical_analysis_fallback(self, topic, full_script, research_context):
        """Construye una guia temporal conservadora si el LLM no devuelve JSON util."""
        text_parts = [str(topic or ""), str(full_script or "")]
        if research_context:
            if isinstance(research_context, list):
                text_parts.append(" ".join(str(item) for item in research_context[:5]))
            else:
                pass
                text_parts.append(str(research_context))
        combined = " ".join(text_parts)
        combined_lower = combined.lower()

        if not combined.strip():
            return None

        year_match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", combined)
        bce_match = re.search(
            r"\b(c\.?\s*)?([1-9][0-9]{1,3})\s*(bce|bc|a\.c\.|a\. de c\.)\b",
            combined_lower,
        )

        context = {
            "time_period": "Not specified",
            "latest_allowed_year": "Not specified",
            "location": "Not specified",
            "cultural_context": "Not specified",
            "key_historical_elements": [],
            "technology_level": "Period-appropriate technology only",
            "clothing_style": "Period-accurate clothing only",
            "architecture_style": "Period-accurate architecture only",
            "forbidden_elements": [
                "smartphones", "modern cars", "plastic objects", "modern signage",
                "wristwatches", "contemporary clothing", "LED screens", "modern weapons",
            ],
            "is_historical": False,
            "has_temporal_constraints": False,
        }

        if bce_match:
            year = bce_match.group(2)
            context.update({
                "time_period": f"Ancient world, c. {year} BCE",
                "latest_allowed_year": f"c. {year} BCE",
                "is_historical": True,
                "has_temporal_constraints": True,
            })
        elif year_match:
            year = int(year_match.group(1))
            context.update({
                "time_period": f"{year}",
                "latest_allowed_year": str(year),
                "has_temporal_constraints": True,
                "is_historical": year < 2000,
            })

        era_rules = [
            (
                ("bronze age", "1200 bc", "1200 bce", "edad del bronce", "trojan", "mycenaean", "micen"),
                {
                    "time_period": "Bronze Age eastern Mediterranean (c. 1600-1100 BCE)",
                    "latest_allowed_year": "c. 1100 BCE",
                    "cultural_context": "Bronze Age Aegean / Near Eastern cultures",
                    "key_historical_elements": [
                        "bronze weapons", "linen tunics", "leather sandals",
                        "oxhide shields", "stone palaces", "oared ships",
                    ],
                    "technology_level": "Bronze Age technology: bronze, wood, linen, leather, stone; no iron, steel, gunpowder, glass eyewear, or machinery",
                    "clothing_style": "linen tunics, cloaks, leather sandals, bronze helmets or simple head coverings",
                    "architecture_style": "stone walls, mudbrick structures, timber beams, palatial courtyards",
                    "forbidden_elements": [
                        "iron weapons", "steel armor", "plate armor", "stirrups",
                        "gunpowder", "medieval castles", "classical marble columns",
                        "wristwatches", "eyeglasses", "modern fabric dyes",
                    ],
                    "is_historical": True,
                    "has_temporal_constraints": True,
                },
            ),
            (
                ("roman", "roma", "legion", "republica romana", "república romana", "imperio romano"),
                {
                    "time_period": "Ancient Rome",
                    "cultural_context": "Roman Republic / Roman Empire",
                    "key_historical_elements": [
                        "Roman tunics", "lorica armor", "scutum shields",
                        "stone roads", "Latin inscriptions", "tile roofs",
                    ],
                    "technology_level": "Ancient Roman technology only; no gunpowder, engines, electricity, or modern materials",
                    "clothing_style": "tunics, togas, leather sandals, Roman military armor where appropriate",
                    "architecture_style": "Roman masonry, arches, roads, villas, temples, amphitheaters",
                    "forbidden_elements": [
                        "medieval plate armor", "modern uniforms", "firearms",
                        "cars", "electric lights", "plastic", "smartphones",
                    ],
                    "is_historical": True,
                    "has_temporal_constraints": True,
                },
            ),
            (
                ("medieval", "middle ages", "edad media", "templar", "templario", "crusade", "cruzada"),
                {
                    "time_period": "Medieval period",
                    "cultural_context": "Medieval Europe / Near East as specified by topic",
                    "key_historical_elements": [
                        "chainmail", "wool cloaks", "leather belts",
                        "stone fortifications", "manuscripts", "torches",
                    ],
                    "technology_level": "Medieval technology only; no industrial, electric, or modern materials",
                    "clothing_style": "wool tunics, linen undergarments, cloaks, chainmail or period armor where appropriate",
                    "architecture_style": "stone castles, timber halls, monasteries, narrow streets",
                    "forbidden_elements": [
                        "modern military gear", "smartphones", "cars", "electric lights",
                        "plastic", "zippers", "concrete skyscrapers",
                    ],
                    "is_historical": True,
                    "has_temporal_constraints": True,
                },
            ),
            (
                ("world war ii", "wwii", "segunda guerra", "1940", "1941", "1942", "1943", "1944", "1945"),
                {
                    "time_period": "World War II era (1939-1945)",
                    "latest_allowed_year": "1945",
                    "cultural_context": "World War II military and civilian context",
                    "key_historical_elements": [
                        "period military uniforms", "steel helmets", "canvas packs",
                        "propeller aircraft", "radio sets", "wartime posters",
                    ],
                    "technology_level": "1940s wartime technology; no smartphones, GPS, modern tactical gear, or digital displays",
                    "clothing_style": "1940s uniforms or civilian clothing, wool, cotton, leather, steel helmets",
                    "architecture_style": "1930s-1940s buildings, trenches, bunkers, airfields, period streets",
                    "forbidden_elements": [
                        "smartphones", "GPS", "digital displays", "modern camouflage",
                        "modern assault rifles", "plastic helmets", "jet engines on WWII propeller aircraft",
                    ],
                    "is_historical": True,
                    "has_temporal_constraints": True,
                },
            ),
            (
                ("cold war", "guerra fria", "guerra fría", "1960", "1961", "1962", "1970", "1976"),
                {
                    "time_period": "Cold War era (c. 1947-1991)",
                    "latest_allowed_year": "1991",
                    "cultural_context": "Cold War military, political, and civilian context",
                    "key_historical_elements": [
                        "analog instruments", "period uniforms", "paper maps",
                        "radio equipment", "concrete command rooms", "1960s-1970s vehicles",
                    ],
                    "technology_level": "Analog Cold War technology; no smartphones, modern laptops, GPS dashboards, or LED screens",
                    "clothing_style": "mid-20th-century uniforms, suits, flight gear, civilian clothing matching the exact decade",
                    "architecture_style": "mid-century offices, bases, radar stations, concrete bunkers, period streets",
                    "forbidden_elements": [
                        "smartphones", "modern laptops", "LED screens", "GPS",
                        "modern cars", "contemporary tactical gear", "social media logos",
                    ],
                    "is_historical": True,
                    "has_temporal_constraints": True,
                },
            ),
        ]

        for markers, patch in era_rules:
            if any(marker in combined_lower for marker in markers):
                context.update(patch)
                break

        if not context["has_temporal_constraints"]:
            return None
        return self._normalize_historical_analysis(context)

    def _analysis_era_anchor(self, analysis):
        if not isinstance(analysis, dict):
            return ""
        period = analysis.get("time_period")
        loc = analysis.get("location")
        if self._is_unspecified_context_value(period):
            return ""
        if not self._is_unspecified_context_value(loc):
            return f"{period}, {loc}"
        return str(period).strip()
    
    
    
    def _generate(self, prompt_text, max_tokens=4096, task_type="general"):
        if not (self.groq_client and self.groq_client.client):
            print("   WARNING Groq no esta disponible para generar texto")
            return None

        groq_result = self.groq_client._generate(
            prompt_text,
            max_tokens=max_tokens,
            task_type=task_type
        )
        if groq_result and not (isinstance(groq_result, str) and groq_result.startswith("ERROR")):
            return groq_result

        print("   WARNING Groq no pudo generar una respuesta valida")
        return groq_result

    def generate_thumbnail_prompt(self, topic, category, style, provider='recraft'):
        """Genera prompt para thumbnail"""
        print(f"ðŸ¤– Claude: Generando prompt Thumbnail ({style})...")
        
        illustrative_styles = ["IlustraciÃ³n Digital", "Cartoon/AnimaciÃ³n", "Anime/Manga", 
                              "Estilo ArtÃ­stico", "Acuarela", "Vectorial", "Sketch/Dibujo",
                              "IlustraciÃ³n", "Cartoon", "Anime", "ArtÃ­stico", "Acuarela", "Vectorial", "Sketch"]
        is_illustrative = any(illus_style in style for illus_style in illustrative_styles)
        
        style_descriptions = {
            "IlustraciÃ³n Digital": "digital illustration style, vibrant colors, clean lines, modern digital art",
            "Cartoon/AnimaciÃ³n": "cartoon style, animated look, bold outlines, bright colors, playful",
            "Anime/Manga": "anime style, manga art, Japanese animation aesthetic, expressive eyes, dynamic poses",
            "Estilo ArtÃ­stico": "artistic style, creative interpretation, stylized rendering",
            "Acuarela": "watercolor painting style, soft brushstrokes, flowing colors, translucent layers",
            "Vectorial": "vector art style, clean geometric shapes, flat design, bold colors",
            "Sketch/Dibujo": "sketch style, hand-drawn look, pencil or ink drawing, line art"
        }
        
        style_description = ""
        for illus_style, desc in style_descriptions.items():
            if illus_style in style:
                style_description = desc
                break
        
        if is_illustrative:
            if style_description:
                engine_rules = f"Apply {style_description}. The image should be clearly illustrative, not photorealistic. Emphasize the artistic style throughout."
            else:
                engine_rules = "Focus on artistic illustration style, creative interpretation, stylized rendering."
        elif provider == 'recraft':
            engine_rules = (
                "Use Recraft-compatible wording, keep the selected style name explicit, "
                "focus on strong composition, lighting, and clean subject separation."
            )
        elif provider == 'leonardo':
            engine_rules = "Focus on artistic style, lighting, 8k resolution, detailed textures."
        else:
            engine_rules = "Focus on photorealism, cinematic lighting, physical accuracy."

        prompt = f"""
        Role: Prompt Engineer.
        Task: Create a visual prompt in English for an AI image generator ({provider}).
        Topic: "{topic}" ({category}).
        Style: {style}.
        Rules: {engine_rules}
        {"IMPORTANT: The output must be in the specified illustrative style, not photorealistic." if is_illustrative else ""}
        Output: ONLY the prompt text in English. Max 800 chars.
        """
        
        res = self._generate(prompt)
        # El mÃ©todo _generate ya intenta Groq primero y Claude como fallback
        # Si ambos fallan, retornar error
        if not res or res == "ERROR_QUOTA_EXCEEDED" or res == "ERROR_AUTH" or (isinstance(res, str) and res.startswith("ERROR")):
            return res if res else "ERROR: Groq y Claude Code CLI fallaron"
        
        visual_prompt = res.strip().replace("```", "").replace("\n", " ")
        if len(visual_prompt) > 1000:
            visual_prompt = visual_prompt[:1000]
        return visual_prompt

    def generate_thumbnail_text_suggestions(self, topic, script_excerpt="", category="",
                                             language="es", emotional_hook="shock",
                                             image_description=""):
        """Genera sugerencias de texto optimizadas para CTR para superponer en un thumbnail.

        Aplica técnicas psicológicas y de marketing (curiosity gap, power words, urgency, etc.).
        Devuelve una lista de dicts: [{'text': str, 'technique': str, 'why': str}, ...]
        """
        lang = "Spanish" if language == "es" else "English"
        script_block = f"\nScript excerpt:\n{script_excerpt[:800]}" if script_excerpt else ""
        image_block = f"\nImage description: {image_description}" if image_description else ""

        prompt = f"""You are a YouTube thumbnail text specialist with deep expertise in CTR optimization, consumer psychology, and viral content.

VIDEO DATA:
- Topic: {topic}
- Category: {category or "mystery / history"}
- Language: {lang}
- Emotional hook of the image: {emotional_hook}{script_block}{image_block}

TASK: Generate exactly 5 short text options to overlay on this YouTube thumbnail.

CONSTRAINTS (non-negotiable):
- Maximum 4 words per option (shorter = better, 2-3 words is ideal)
- ALL CAPS
- Must be in {lang}
- Must be readable at thumbnail size (320×180 px)
- Must complement the emotional hook ({emotional_hook}), not just repeat the title
- The text sits in the RIGHT THIRD of the image as overlay — it must create tension with the visual

PSYCHOLOGICAL TECHNIQUES TO USE (assign one per option):
1. CURIOSITY GAP — withhold a key piece of info, make them need to click to find out
   Examples: "LO QUE OCULTAN", "NADIE LO SABE", "LA VERDAD OCULTA"
2. POWER WORD + AUTHORITY — words that signal forbidden/exclusive/shocking knowledge
   Examples: "CLASIFICADO", "PROHIBIDO", "REVELADO", "CENSURADO"
3. URGENCY / SCARCITY — time pressure or rarity
   Examples: "ANTES QUE LO BORREN", "SOLO HOY", "ÚLTIMA EVIDENCIA"
4. SPECIFIC NUMBER — numbers create credibility and specificity
   Examples tied to the topic (year, count, duration, etc.)
5. DIRECT EMOTIONAL TRIGGER — one word that names the core fear/shock/awe
   Examples: "IMPACTANTE", "ATERRADOR", "INCREÍBLE", "JAMÁS VISTO"

For each option, explain WHY it would increase CTR for this specific thumbnail.

Return ONLY a JSON array, no markdown, no extra text:
[
  {{"text": "TEXT HERE", "technique": "technique name", "why": "one sentence explanation"}},
  ...
]"""

        result = self._generate(prompt, max_tokens=600, task_type="general")
        if not result or (isinstance(result, str) and result.startswith("ERROR")):
            print(f"[WARN] generate_thumbnail_text_suggestions: LLM returned: {str(result)[:120]}")
            return []

        import re, json
        # Buscar el primer '[' que arranque un JSON array válido
        for m in re.finditer(r'\[', result):
            try:
                parsed = json.loads(result[m.start():])
                if isinstance(parsed, list):
                    valid = [s for s in parsed if isinstance(s, dict) and s.get('text')]
                    if valid:
                        return valid
            except json.JSONDecodeError:
                continue
        print(f"[WARN] generate_thumbnail_text_suggestions: no valid JSON array found. Raw: {result[:300]}")
        return []

    def generate_thumbnail_super_prompt(self, topic, script_excerpt="", category="",
                                        language="es", thumbnail_format=None,
                                        render_text=True, format_archetype=None, research_brief=None):
        """Genera los prompts de miniatura listos para pegar en una IA externa.

        Devuelve {'positive', 'negative', 'text'} o None si falla.

        Dos cosas que antes no hacia:

        - `render_text`: el prompt pedia un `short_text` de 2-3 palabras,
          reservaba espacio para el... y en la regla 12 prohibia "NO text in the
          image". La palabra se calculaba y se tiraba, y la miniatura volvia con
          un hueco vacio. Ahora, con render_text=True, se le pide a la IA que la
          ESCRIBA, con tipografia, tamano y ubicacion concretos. Con False vuelve
          al comportamiento viejo (hueco reservado) para superponerla despues con
          `thumbnail_compositor`.
        - `thumbnail_format`: estaba clavado en 16:9. Un Short necesita 9:16 y
          reglas de encuadre distintas (ver `thumbnail_formats`).
        """
        from publish.thumbnail_formats import LANDSCAPE_16_9
        from publish.thumbnail_art_direction import (
            art_direction_brief, compile_title, contextual_composition_rules, parse_art_response,
        )

        fmt = thumbnail_format or LANDSCAPE_16_9
        print(f"Generando super prompt de thumbnail para IA externa ({fmt.aspect_label})...")

        # Composicion por angulo narrativo (mecanismo -> el objeto en proceso;
        # hallazgo -> la pieza in situ; historia humana -> el objeto de la persona).
        angle_line = ""
        try:
            from channel.channel_strategy import archetype_thumbnail_brief, archetype_label, get_active_archetype
            _arche = format_archetype or get_active_archetype()
            brief = archetype_thumbnail_brief(_arche) if _arche else ""
            if brief:
                angle_line = f"\n- Narrative angle: {archetype_label(_arche)} -> composition: {brief}"
        except Exception:
            angle_line = ""

        lang_note = "The video is in Spanish." if language == "es" else "The video is in English."

        # Investigacion (thumbnail_research.build_thumbnail_brief): si esta, la paleta, la
        # luminancia y el texto salen de la competencia real en vez de los valores fijos.
        brief = research_brief if isinstance(research_brief, dict) else {}
        # Un brief viejo puede imponer un titular o el estilo anterior. Sus
        # candidatos y mediciones informan la decision, no la sustituyen.
        research_lines = [line for line in str(brief.get("prompt_block") or "").splitlines()
                          if not line.lstrip().startswith(("- short_text:", "- Typography plan"))]
        candidates = brief.get("text_options") or ([{"text": brief["text"]}] if brief.get("text") else [])
        research_block = "\n".join(research_lines)
        if candidates:
            research_block += "\nHeadline candidates (evaluate visual relevance, not fixed choices): " + json.dumps(
                candidates, ensure_ascii=False)
        if brief.get("luminance"):
            _lo, _hi = brief["luminance"]
            lum_line = f"- Average luminance: {_lo}-{_hi} (out of 255), from the competition research."
        else:
            lum_line = "- Average luminance: 100-150 (out of 255)."
        warm_line = "- Keep the resolved scene and title palettes coherent; never impose amber/yellow on every topic."
        pal = brief.get("palette")
        color_line = ("COLOR SYSTEM - Infer one scene palette from the subject, era, materials, mood and lighting. "
                      "Choose explicit colors; no universal warm or teal palette."
                      if not pal else
                      f"COLOR SYSTEM ({pal['label']}, chosen to stand out from the competing thumbnails) - "
                      f"Highlights: {', '.join(pal['highlights'])} - Mids: {', '.join(pal['mids'])} - "
                      f"Shadows: {', '.join(pal['shadows'])}")
        script_block = (
            f"\nScript excerpt (first 12000 chars):\n{script_excerpt[:12000]}"
            if script_excerpt else ""
        )

        reglas = contextual_composition_rules(fmt, render_text)
        reglas_encuadre = "\n".join(
            f"{i}. {regla}" for i, regla in enumerate(reglas, start=1)
        )

        if render_text:
            bloque_texto = (
                "TEXT RENDERING (the image generator MUST draw this text into the image):\n"
                "The application composes the title from ART DIRECTION exactly once. "
                "Keep all typography out of POSITIVE PROMPT; reserve calm space for the title.\n"
            )
            prohibido_texto = (
                "misspelled words, duplicated letters, garbled glyphs, extra text, "
                "subtitles, captions, watermark, logo, signature, thin or light font weight, "
                "small text, low-contrast text, excessive letter spacing, thick black text outline, "
                "hard offset text shadow, sticker lettering, WordArt, beveled or extruded lettering, "
                "second copy of the headline, numbers or words carved or painted on objects, "
                "signs, plaques or inscriptions with writing"
            )
            nota_salida = (
                "The [POSITIVE PROMPT] describes only the scene, with NO typography or headline. "
                "Place the headline in TEXT and its resolved design in ART DIRECTION."
            )
        else:
            bloque_texto = (
                "TEXT RENDERING: none. Leave the reserved area as calm empty space; "
                "the text is composited afterwards in post-production.\n"
            )
            prohibido_texto = (
                "any text, letters, garbled glyphs, subtitles, captions, watermark, "
                "logo, signature"
            )
            nota_salida = (
                "The [POSITIVE PROMPT] must NOT ask for any text inside the image."
            )

        prompt = f"""You are a senior YouTube thumbnail art director for documented-history content.

VIDEO DATA:
- Title / Topic: {topic}
- Category: {category or "documented history"}{angle_line}
- {lang_note}{script_block}
{research_block}
TASK: Analyze the video data and produce a thumbnail prompt for an external AI
image generator (Recraft, gpt-image, Midjourney, Ideogram, Flux, etc.).

From the video data, infer and fill these variables:
- event_name: full title or event
- year_era: period (e.g. "1100 AD", "ancient Nubia", "medieval")
- location: geographic / historical setting
- hero_subject: the single most impactful visual element. PREFER the historical
  thing itself -- the structure, the artifact, the terrain, the wreck, the
  moment -- over a person's face. A human is only worth including when it gives
  SCALE to something enormous.
- shot_type: choose the one that fits the topic best, and say it explicitly:
    * scale        -> wide shot, the structure dwarfs a small figure seen from behind
    * detail       -> tight macro on texture, tooling marks, an object in a hand
    * aerial       -> impossible high viewpoint revealing the whole layout
    * aftermath    -> the place empty, abandoned, weathered, nobody in frame
    * moment       -> the action mid-event, figures small and in motion
- emotional_hook: one of - fear / betrayal / shock / loss / glory
- short_text: 1-3 ALL CAPS words, punchy, ALWAYS IN ENGLISH regardless of the
  narration language, and plain ASCII only (no accents, no diacritics, no
  special characters). Image generators misspell accented words -- a Spanish
  hook came back rendered as "6 PIRAMIDAS" instead of "6 PIRAMIDES". Prefer a
  concrete number or a hard noun over an abstraction. A number may stay inline
  with its noun or become a hero line when its magnitude IS the visual story.
  It must add a specific, script-supported detail beyond the title. Never use
  standalone HOW, WHY or WHAT: those describe a question, not this video's hook.
- era_anchor: one sentence with the period-accurate scene (clothing, weapons,
  architecture, light, season)

FORMAT: {fmt.prompt_constraint}
{fmt.llm_brief}

MANDATORY COMPOSITION RULES (all must be respected):
{reglas_encuadre}

{bloque_texto}
{art_direction_brief(fmt)}
QUANTITATIVE TARGETS:
{lum_line}
- Subject zone brighter than the calm zone by >= 20 luminance points.
- Edge density in the subject third: >= 55% of total edge mass.
{warm_line}
- No single histogram bin > 30% of pixels.

{color_line}

EMOTIONAL HOOK -- express it through the SCENE, not through a face:
- shock -> impossible scale, a tiny human against something enormous
- fear -> deep shadow swallowing most of the frame, one lit edge
- betrayal -> something broken, toppled or defaced in the foreground
- loss -> emptiness, dust, weeds reclaiming worked stone, nobody there
- glory -> low sun raking across the structure, long shadows, haze and depth

PROHIBITED ELEMENTS (for the negative prompt):
{prohibido_texto}, centered person facing camera, posed portrait, studio model
pose, smiling subject, symmetrical bust shot, person standing with arms at their
sides, stock-photo actor, deformed hands, extra fingers, extra limbs, modern clothing,
wristwatch, sunglasses, smartphone, plastic, neon, pastel colors, cartoon, anime,
3d render, cgi look, low contrast, washed out, flat lighting, symmetrical
composition, frame, border, blurry subject, motion blur on face, multiple faces
competing, crowd as main subject

{nota_salida}

Return EXACTLY four blocks, with no extra text before, between or after them:

[TEXT]
<the short_text, ALL CAPS, nothing else>

[ART DIRECTION]
<the resolved JSON object specified above; decisions and evidence, not a list of alternatives>

[POSITIVE PROMPT]
<one dense scene-only paragraph in English, comma-separated, all scene rules applied.
State the resolved lens and depth of field. End with: {fmt.prompt_constraint}, photoreal>

[NEGATIVE PROMPT]
<prohibited elements list, comma-separated>
"""
        # Las directivas artisticas ya no caben holgadamente en 1400 tokens.
        # Exigir los cuatro bloques: inventar un negativo por defecto ocultaba
        # respuestas cortadas a mitad del positivo (caso real: 'wedge-').
        # \s* tambien admite etiquetas pegadas, como las devuelve Groq.
        validation_error = ""
        for attempt, budget in enumerate((4096, 8192)):
            request = prompt
            if attempt:
                request += (
                    f"\nValidation of the previous response failed: {validation_error}. "
                    "Regenerate all FOUR blocks in full with valid art direction and a scene-only positive. "
                    "Use a concrete, script-supported headline. Do not continue a fragment. "
                    "For evidence_quote copy words directly from the script. In visual_anchor explain "
                    "the scene's connection to the headline; paraphrases are valid. "
                    "Preserve the other valid decisions.\n"
                    f"Previous response to repair:\n{str(result or '')[:16000]}"
                )
            result = self._generate(request, max_tokens=budget, task_type="script_quality")
            try:
                raw_hook, direction, positive, negative = parse_art_response(result, script_excerpt[:12000])
                if direction.get("scene_cleanup"):
                    print(f"   [Miniatura] se quitaron {len(direction['scene_cleanup'])} fragmento(s) con tipografia "
                          f"de la escena (el texto lo agrega la app): {'; '.join(direction['scene_cleanup'])[:160]}")
                hook = _ascii_hook(raw_hook).strip('\u201c\u201d')
                generic_hook = hook.rstrip("?!.") in ("HOW", "WHY", "WHAT")
                if not hook or generic_hook or not hook.isascii():
                    raise ValueError("se requiere un titular concreto en ASCII, no HOW/WHY/WHAT")
                if render_text:
                    positive = f"{positive}, {compile_title(hook, fmt, direction)}"
                break
            except (ValueError, TypeError) as exc:
                validation_error = str(exc)
            print(f"   WARNING Super prompt no valido ({validation_error}); "
                  + ("reintentando con mas margen" if not attempt else "no se mostrara como completo"))
        else:
            return None

        return {
            "positive": positive,
            "negative": negative,
            "text": hook,
            "art_direction": direction,
            "combined": build_copyable_prompt(positive, negative),
        }

    def _estimate_script_max_tokens(self, duration_seconds: int) -> int:
        """Calcula un presupuesto de tokens de salida para guiones largos."""
        try:
            words_target = int((max(1, int(duration_seconds)) / 60) * 150)
        except Exception:
            words_target = 600
        estimated_tokens = int(words_target * 1.8)
        return max(4096, min(12000, estimated_tokens))

    # ------------------------------------------------------------------
    # Tone-profile-aware prompt builders (used by generate_video_script and
    # generate_video_script_with_research). Profile is derived from the GUI
    # `category` dropdown via tone_profile.get_tone_profile_for_category.
    # ------------------------------------------------------------------

    @staticmethod
    def _build_script_role_for_profile(tone_profile: str) -> str:
        """First line of the script prompt — sets the LLM's persona by profile."""
        if tone_profile == "mystery":
            return (
                'Role: Expert Scriptwriter for a YouTube channel about mysteries, '
                f'conspiracies, and unexplained phenomena ({get_channel_name()}).'
            )
        if tone_profile == "dramatic_factual":
            return (
                'Role: Expert Scriptwriter for cinematic documentaries about extreme '
                f'natural events and disasters ({get_channel_name()} channel). Your style '
                'is dramatic and tense, but STRICTLY FACTUAL — no paranormal, no curses, '
                'no unproven theories.'
            )
        # documentary (default)
        return (
            f'Role: Expert historian and documentary scriptwriter for the {get_channel_name()} '
            'channel. Your style is a serious, cinematically dark documentary (think BBC dark '
            'history, Apple TV+ documentaries, Ken Burns). Your content is STRICTLY HISTORICAL '
            'AND VERIFIABLE — no invented curses, no impossible civilizations, no UFOs, no '
            'undocumented conspiracies.'
        )

    @staticmethod
    def _build_narrative_approach_for_profile(tone_profile: str) -> str:
        """The NARRATIVE APPROACH block — replaces the previously hardcoded mystery-only version."""
        if tone_profile == "mystery":
            return """
        NARRATIVE APPROACH:
        - Write for an audience that loves mysteries, conspiracies, and unexplained phenomena.
        - Use real locations, organizations, and known facts as the foundation, then explore the mystery around them.
        - Present alternative theories and witness accounts as intriguing possibilities worth exploring.
        - Do NOT debunk or dismiss — instead, invite the viewer to think and question.
        - Build suspense, use dramatic pacing, and create curiosity hooks throughout.
        - Frame uncertain claims with phrases like "some believe", "witnesses report", "according to certain investigators".
        - Cases, sightings, or testimonies you mention MUST have actually been reported (in books, press, archives, folklore). Do NOT invent entire cases.
        - Maintain internal consistency (don't contradict your own dates or facts within the script)."""
        if tone_profile == "dramatic_factual":
            return """
        NARRATIVE APPROACH:
        - Write a cinematic disaster-documentary narrative (think "Seconds From Disaster", "Apocalypse: WWII colorized", National Geographic disaster docs).
        - Build tension through real causes, early signs, tipping points, and consequences — NOT through supernatural framing.
        - FORBIDDEN: curses, omens, hidden forces, paranormal explanations, conspiracies about the event. Only physical/geological/meteorological/biological causes that are documented.
        - Use real figures: magnitudes, victim counts, distances, durations, names of places and people.
        - Suspense IS allowed when anchored to the documented timeline ("Nobody knew what the next 12 hours would bring"), but the facts MUST be real.
        - Maintain internal consistency: numbers, dates, names do not contradict between sections."""
        # documentary (default)
        return """
        NARRATIVE APPROACH:
        - Write as a serious historian / science communicator producing a cinematically dark documentary (BBC, Apple TV+, Ken Burns style), NOT as a mystery/conspiracy narrator.
        - EVERYTHING in the script must be historically verifiable: people, dates, battles, places, decisions, consequences.
        - FORBIDDEN: invented curses, UFOs, civilizations crossing oceans without evidence, lost technologies, prophecies, modern conspiracies connected to the historical topic, "echoes that still resonate in today's politics/EU/etc.", cursed artifacts, supernatural causes.
        - FORBIDDEN: mystery-channel content disguised as history. If the topic is historical, the script is 100% historical.
        - Permitted and desirable: real human drama (Hannibal's oath, generals' decisions, strategic blunders), documented historical ironies, real scale (troop numbers, siege duration), verifiable consequences (border changes, institutions).
        - Cinematic dark tone and narrative tension ARE allowed, anchored to reality: "On the night of August 2nd, 216 BCE, 50,000 Romans would die before dawn" YES; "On the night of August 2nd, 216 BCE, an inexplicable force changed Europe's destiny" NO.
        - If you run out of NEW facts, do NOT cut the script short. FIRST go deeper with documented material: prior historical context, biographical details of the real protagonists, documented critical decisions and their justification, verifiable consequences (short-term and over years/decades), real parallels with similar documented events, primary-source testimonies, verifiable scale/casualty/impact figures. Only if you genuinely exhausted documented material may you produce a shorter script. NEVER invent.
        - Maintain consistency: names, dates, places, and sides do not contradict between sections."""

    @staticmethod
    def _build_script_quality_block_for_profile(tone_profile: str) -> str:
        """The NARRATIVE STYLE block — was hardcoded as mystery-only, now profile-aware."""
        if tone_profile == "mystery":
            return """
        NARRATIVE STYLE AND QUALITY RULES (MANDATORY):
        - Write in an engaging, mysterious, and intriguing tone — like a narrator on a conspiracy/mystery YouTube channel.
        - Present theories, unexplained events, and alternative explanations as fascinating possibilities, NOT as debunked nonsense.
        - Use phrases like "some researchers believe", "according to certain sources", "what if", "could it be that",
          "the official explanation says... but others suggest", "witnesses claim", "there are those who argue".
        - Do NOT be overly skeptical or dismissive. The audience WANTS to explore mysteries and alternative theories.
        - Do NOT write like a fact-checker debunking claims. Write like a storyteller exploring the unknown.
        - However, do NOT present unverified claims as confirmed facts either. Frame them as intriguing possibilities.
        - Keep internal consistency: if you mention a date or name, don't contradict it later.
        - Use real names, places, and organizations when they exist (e.g., real government agencies, real locations).
        - Build suspense and curiosity throughout the narrative — use cliffhangers between sections.
        - Every paragraph must advance the story; no generic filler or repetition.
        - Avoid empty phrases: "as we all know", "throughout history", "without a doubt".
        - Use rhetorical questions strategically to hook the viewer (e.g., "But what really happened that night?").
        - End with an open question or thought-provoking reflection that leaves the viewer wanting more.
        """
        if tone_profile == "dramatic_factual":
            return """
        NARRATIVE STYLE AND QUALITY RULES (MANDATORY):
        - Write as a documentary narrator covering a real disaster, with tension built from documented facts.
        - Each chapter: cause → early warnings → tipping point → consequence. Build tension via physical scale, not invented mystery.
        - Use dates, magnitudes (Richter, km², casualties, speed, temperature), names of real places and people.
        - FORBIDDEN: attributing the event to curses, omens, occult forces, UFOs, or conspiracies. Only documented physical/geological/meteorological/biological causes.
        - Maintain internal consistency: figures, dates, names do not contradict between sections.
        - Avoid empty phrases: "as we all know", "throughout history".
        - End with reflection on lessons, current risks, or analogous ongoing events — never with invented mystery.
        """
        # documentary (default)
        return """
        NARRATIVE STYLE AND QUALITY RULES (MANDATORY):
        - Write as a rigorous historian / documentary narrator covering a dark cinematic documentary (BBC, Netflix dark history, Ken Burns), NOT as a mystery/conspiracy narrator.
        - EVERYTHING that appears must be historically verifiable: characters, dates, battles, places, decisions, consequences.
        - FORBIDDEN to invent: curses, UFOs, civilizations crossing oceans without evidence, lost technologies, prophecies, modern conspiracies linked to the historical topic, "echoes still resonating in today's politics/EU/etc.", cursed artifacts.
        - FORBIDDEN: mystery-channel content disguised as history. If the topic is historical, the script is 100% historical.
        - Permitted and desirable: real human drama, documented historical ironies, real scale, verifiable long-term consequences.
        - Cinematic dark tone and tension ARE allowed, anchored to reality.
        - Keep internal consistency: do not contradict your own dates or names later.
        - Avoid empty phrases: "as we all know", "throughout history", "what few people know".
        - End with a real historical reflection (consequences, documented parallels, what is still visible on the modern map), NOT with "what if the ancients knew something we don't?".
        - IF YOU RUN OUT OF NEW FACTS, DO NOT CUT THE SCRIPT SHORT. First go deeper with documented material: prior historical context, biographies of real protagonists, documented critical decisions, verifiable consequences (short-term and across years/decades), parallels with similar documented events, primary-source testimonies. Only if you genuinely exhausted documented material may you shorten. NEVER fabricate filler.
        """


    def _build_short_block(self, category="") -> str:
        try:
            from channel.channel_strategy import build_hook_prompt_instructions, get_shorts_rules as _get_sr
            _sr = _get_sr()
            if is_mystery_inquiry(category):
                return """
        PACING FOR A MYSTERY SHORT:
        - Open with the specific puzzle and attribute any source account from the hook itself.
        - Every 5-8 seconds add a source, evidence, an explanation or its limits.
        - Use short cinematic scenes. Close with what is known and the question that remains open.
        - Preserve uncertainty in metadata, titles and cover text; never present a reported number as proven.
        """
            _hook_instr = build_hook_prompt_instructions()
            return f"""
        STRICT RULES FOR SHORTS — {get_channel_name()} Channel Bible:

        DURATION: {_sr.get('min_duration', 45)} to {_sr.get('max_duration', 58)} seconds. NEVER exceed {_sr.get('hard_limit', 60)} seconds.

        {_hook_instr}

        PACING & STRUCTURE:
        - The script should be fast-paced, designed for scene cuts every 5-8 seconds.
        - Write shorter, punchier sentences. No long explanations.
        - Every 5-8 seconds must introduce a new piece of information or visual twist.
        - End with a sense of mystery or continuity — leave the viewer wanting more.

        CREDIBILITY:
        - Do NOT present speculation as fact.
        - Maintain historical rigor. Use real dates, places, and documented events.
        - The channel must feel like a dark historical documentary series, NOT a list channel.

        EDITORIAL FILTER — Every Short must answer one of:
        What vanished? What was erased? What went wrong? What remains unexplained?
        What changed history forever? What did they try to hide? Why does this still matter?
        """
        except ImportError:
            return """
        STRICT RULES FOR SHORTS:
        - Duration: 45 to 58 seconds. NEVER exceed 60 seconds.
        - The first 1-2 seconds are CRITICAL. Open with a brutal hook or impossible premise.
          Example: "A massive city vanished without a trace."
          Example: "In 536 AD, the sky went dark."
        - Pacing: Fast-paced, scene cuts every 5-8 seconds.
        - Write shorter, punchier sentences.
        - End with mystery or continuity, not a summary.
        """

    @staticmethod
    def _build_metadata_request_block() -> str:
        return """
        METADATA BLOCK (append after the script, each on its own line):
        COVER_TEXT: 1-3 powerful words for the video cover frame (e.g. COVER_TEXT: VANISHED)
        HOOK_PATTERN: Which hook pattern you used — A, B, C, or D
        CATEGORY: The single best-fitting category for this Short
        LONG_FORM_POTENTIAL: YES or NO — could this topic sustain an 8-12 minute video?
        LONG_FORM_ANGLE: If YES, a brief angle for the long-form expansion (1 sentence)
        SERIES_FIT: Which series this fits (e.g. "Lost Civilizations", "Vanished Empires") or NONE
        """

    _METADATA_KEYS = [
        "COVER_TEXT", "HOOK_PATTERN", "CATEGORY", "LONG_FORM_POTENTIAL",
        "LONG_FORM_ANGLE", "SERIES_FIT",
    ]


    @classmethod
    def _extract_script_metadata(cls, script: str) -> dict:
        import re
        metadata = {}
        for key in cls._METADATA_KEYS:
            match = re.search(rf'{key}:\s*(.+)', script, re.IGNORECASE)
            if match:
                val = match.group(1).strip().strip('"').strip("'")
                if key == "COVER_TEXT":
                    words = val.upper().split()
                    val = " ".join(words[:3]) if 1 <= len(words) <= 3 else ""
                elif key == "HOOK_PATTERN":
                    val = val.upper()[:1] if val and val[0].upper() in "ABCD" else ""
                elif key == "LONG_FORM_POTENTIAL":
                    val = "YES" if val.upper().startswith("Y") else "NO"
                if val:
                    metadata[key.lower()] = val
        return metadata

    @classmethod
    def _strip_metadata_lines(cls, script: str) -> str:
        import re
        for key in cls._METADATA_KEYS:
            script = re.sub(rf'\n*{key}:\s*.+', '', script, flags=re.IGNORECASE)
        return script.rstrip()


    def _script_needs_refinement(self, script: str, target_words: int) -> bool:
        if not script:
            return True
        words = script.split()
        if not words:
            return True

        word_count = len(words)
        if word_count < max(120, int(target_words * 0.7)):
            return True

        lower_script = script.lower()
        filler_markers = [
            "a lo largo de la historia",
            "como todos sabemos",
            "sin lugar a dudas",
            "en resumen",
            "in conclusion",
            "throughout history",
            "as we all know",
            "without a doubt"
        ]
        filler_hits = sum(lower_script.count(marker) for marker in filler_markers)
        if filler_hits >= max(3, target_words // 900):
            return True

        import re
        sentences = [
            re.sub(r'\s+', ' ', s.strip().lower())
            for s in re.split(r'[.!?]+', script)
            if s and s.strip()
        ]
        if len(sentences) >= 8:
            unique_ratio = len(set(sentences)) / max(1, len(sentences))
            if unique_ratio < 0.75:
                return True

        unique_word_ratio = len(set(w.lower() for w in words)) / max(1, word_count)
        if word_count > 1200 and unique_word_ratio < 0.28:
            return True

        return False

    def _deduplicate_cta(self, script):
        """Remove duplicate subscribe CTAs from a script, keeping only the last one."""
        import re
        cta_re = re.compile(
            r'suscr[íi]be|subscribe|stunning revelations|no olvides|don\'t forget',
            re.IGNORECASE
        )
        paragraphs = re.split(r'\n{2,}', script.strip())
        cta_indices = [i for i, p in enumerate(paragraphs) if cta_re.search(p)]
        if len(cta_indices) > 1:
            to_remove = set(cta_indices[:-1])
            print(f"   ⚠️ {len(to_remove)} CTA(s) de suscripción duplicado(s) eliminado(s) del guion.")
            paragraphs = [p for i, p in enumerate(paragraphs) if i not in to_remove]
        return "\n\n".join(paragraphs)

    _TOPIC_FACT_SEEDS = (
        (
            ("muriq", "amorrita", "amorite wall", "muro amorrita", "tidnim", "tidnum"),
            (
                "the Amorite Wall (Sumerian: Muriq-Tidnim, 'which keeps the Tidnum/Amorites at bay'). "
                "Ur III fortification project, mainly under king Shu-Sin (c. 2038-2030 BC); "
                "some year-names also connect earlier work to Shulgi. "
                "Goal: hold back Amorite (Martu/Tidnum) tribal pressure on Sumer and Akkad. "
                "Evidence is royal inscriptions and year-names, not a fully excavated 1,500 km wall. "
                "The viral claim of a 1,500 km wall in 2200 BC is a modern exaggeration; 2200 BC is closer "
                "to the 4.2-kiloyear drought and the lead-up to Ur III, not a surveyed wall length. "
                "Aftermath: Ibbi-Sin, fall of Ur c. 2004 BC, Amorite kingdoms (Isin, Larsa, Babylon). "
                "Contrast the inscriptional wall with the viral 1500 km legend."
            ),
        ),
    )

    @staticmethod
    def _build_topic_disambiguation_block(topic: str) -> str:
        raw = (topic or "").strip()
        aliases = []
        try:
            from ai.research_search import topic_search_queries
            aliases = topic_search_queries(raw)
        except Exception:
            aliases = [raw] if raw else []
        alias_txt = ", ".join(aliases[:8]) if aliases else raw
        seed = ""
        low = raw.lower()
        for keys, text in ClaudeAiClient._TOPIC_FACT_SEEDS:
            if any(key in low for key in keys):
                seed = text
                break
        seed_line = f"- Historical outline: {seed}\n" if seed else ""
        return f"""
        TOPIC DISAMBIGUATION (mandatory — do not refuse this request):
        - This is a legitimate historical documentary about a real subject.
        - User title: "{raw}"
        - Treat obscure Sumerian, Akkadian, Egyptian or indigenous names as history, not as disallowed content.
        - Alternate names to use: {alias_txt}
        - Never reply with an apology or "I can't fulfill that request". Write the narration.
        {seed_line}"""

    def _maybe_append_cta(self, script, language='es'):
        """Append the channel CTA only to a real narration, never to a refusal."""
        if not script or is_llm_refusal(script) or len(script.split()) < 40:
            return script
        lower = script.lower()
        if (
            "stunning revelations" in lower
            or "subscribe" in lower
            or "suscríbete" in lower
            or "suscribete" in lower
            or "suscrÃ­bete" in lower
        ):
            return script
        if language == 'es':
            return script + "\n\nNo olvides suscribirte a {get_channel_name()} para más contenido fascinante."
        return script + "\n\nDon't forget to subscribe to {get_channel_name()} for more fascinating content."

    def _retry_script_after_refusal(
        self,
        topic,
        category,
        duration_seconds,
        language,
        target_words,
        script_max_tokens,
        role_header,
        quality_block,
        research_snippets=None,
        opening_block="",
    ):
        disambig = self._build_topic_disambiguation_block(topic)
        context = ""
        if research_snippets:
            snippets = research_snippets if isinstance(research_snippets, (list, tuple)) else [str(research_snippets)]
            context = "Research notes:\n" + "\n".join(str(s) for s in snippets[:8])
        lang = "English" if language == "en" else "Spanish"
        prompt = f"""
        {role_header}
        {disambig}
        Task: Write a complete narration script about "{topic}".
        Category: {category}
        Language: {lang} only. Do not mix languages.
        Target length: ~{target_words} words.

        {context}

        {quality_block}
        {opening_block}

        CRITICAL:
        - Output ONLY the narration. No apology, no meta-commentary, no "I can't".
        - {"This is an evidence-led investigation of documented accounts and open hypotheses." if is_mystery_inquiry(category) else "This is a standard historical documentary, not disallowed content."}
        - Use the aliases and documented outline above if the user title looks obscure.

        Format: narration text only.
        """
        return self._generate(
            prompt,
            max_tokens=script_max_tokens,
            task_type="script_quality",
        )

    def _postprocess_generated_script(
        self,
        script,
        topic,
        category,
        duration_seconds,
        language,
        target_words,
        script_max_tokens,
        role_header,
        quality_block,
        is_short,
        research_snippets=None,
        opening_block="",
    ):
        if script == "ERROR_QUOTA_EXCEEDED" or script == "ERROR_AUTH" or (script and str(script).startswith("ERROR")):
            return script
        if not script:
            return script

        if is_short:
            meta = self._extract_script_metadata(script)
            self._last_cover_text = meta.get("cover_text", "")
            self._last_script_metadata = meta
            script = self._strip_metadata_lines(script)

        if is_llm_refusal(script) or script_is_too_short(script, duration_seconds, target_words):
            print("   ⚠️ Guion rechazado o demasiado corto. Reintentando con brief histórico...")
            retry = self._retry_script_after_refusal(
                topic=topic,
                category=category,
                duration_seconds=duration_seconds,
                language=language,
                target_words=target_words,
                script_max_tokens=script_max_tokens,
                role_header=role_header,
                quality_block=quality_block,
                research_snippets=research_snippets,
                opening_block=opening_block,
            )
            if retry and not str(retry).startswith("ERROR") and not is_llm_refusal(retry):
                if is_short:
                    meta = self._extract_script_metadata(retry)
                    self._last_cover_text = meta.get("cover_text", "")
                    self._last_script_metadata = meta
                    retry = self._strip_metadata_lines(retry)
                script = retry

        if is_llm_refusal(script):
            print("   ❌ El LLM rechazó el tema. No se usará el texto de rechazo como guion.")
            return "ERROR_SCRIPT_REFUSAL"

        if self._script_needs_refinement(script, target_words):
            print("   ⚠️ Guion con baja densidad detectado. Aplicando refinamiento anti-relleno...")
            context = ""
            if research_snippets:
                snippets = research_snippets if isinstance(research_snippets, (list, tuple)) else [str(research_snippets)]
                context = "Research context:\n" + "\n".join(str(s) for s in snippets[:8])
            refine_prompt = f"""
            {role_header.replace('Role: Expert Scriptwriter', 'Role: Senior Script Editor')}
            Task: Rewrite this narration script to be more engaging and substantive.

            Language: {'English' if language == 'en' else 'Spanish'} only.
            Keep same topic: "{topic}".
            Category: {category}
            Target length: ~{target_words} words.
            {self._build_topic_disambiguation_block(topic)}
            {quality_block}
            {opening_block}
            {context}

            Additional rewrite constraints:
            - Remove repetitive phrases and generic filler.
            - Do NOT output a refusal or apology.
            - Return ONLY the final narration text.

            Script to rewrite:
            {script}
            """
            refined = self._generate(
                refine_prompt,
                max_tokens=script_max_tokens,
                task_type="script_quality"
            )
            if (
                refined
                and not str(refined).startswith("ERROR")
                and not is_llm_refusal(refined)
                and (
                    len(refined.split()) >= int(target_words * 0.65)
                    or len(refined.split()) > max(len(script.split()) * 2, 80)
                )
            ):
                script = refined

        if script_is_too_short(script, duration_seconds, target_words):
            word_count = len(script.split()) if script else 0
            needed = minimum_script_words(duration_seconds, target_words)
            print(
                f"   ❌ Guion demasiado corto ({word_count} palabras; mínimo {needed} "
                f"para {duration_seconds}s). Abortando en vez de crear escenas basura."
            )
            return "ERROR_SCRIPT_TOO_SHORT"

        if script:
            script = self._deduplicate_cta(script)
            script = self._maybe_append_cta(script, language)
        return script

    def generate_video_script(self, topic, category, duration_seconds, language='es', narrative_profile=None,
                              opening_style="hook_overlay_v1"):
        """Genera guion de video"""
        print(f"ðŸ¤– Claude: Generando guion ({language})...")
        words = int((duration_seconds / 60) * 150)
        script_max_tokens = self._estimate_script_max_tokens(duration_seconds)
        lang_instr = "WRITE IN ENGLISH." if language == 'en' else "ESCRIBE EN ESPAÃ‘OL."
        is_long_horizontal = str(narrative_profile or "").lower() in {"long_horizontal", "long_horizontal_strict"}
        is_short = duration_seconds <= 60 or str(narrative_profile or "").lower() in {"short", "tiktok", "reels", "youtube_short"}
        is_strict = str(narrative_profile or "").lower() == "long_horizontal_strict"
        tone_profile = get_tone_profile_for_category(category)
        role_header = self._build_script_role_for_profile(tone_profile)
        narrative_approach = self._build_narrative_approach_for_profile(tone_profile)
        quality_block = self._build_script_quality_block_for_profile(tone_profile)
        if is_mystery_inquiry(category):
            narrative_approach = "Investigative cinematic narrative: source account, context, evidence, competing explanations and unresolved questions."
            quality_block = mystery_editorial_instructions(category, "en")
        long_block = ""
        short_block = ""
        runtime_minutes = round(duration_seconds / 60)
        runtime_display = f"{runtime_minutes} minutes (~{duration_seconds} seconds)"
        if is_long_horizontal:
            long_block = f"""
        RETENTION BLUEPRINT FOR LONG HORIZONTAL VIDEO (MANDATORY):
        - Runtime target: {runtime_display}. Write EXACTLY enough content to fill this duration — no more, no less.
        - Structure: "Retención por Capas".
        - First 0-90 seconds (Intro): MUST pose an "Unsolvable Mystery" or a "Life-or-Death Question". Do NOT use generic introductions. Drop the viewer mid-action.
        - First 2 minutes: deliver a first concrete payoff and set the core conflict. State who, where, when, and what is at stake.
        - Structure the narrative in chapters with clear transitions and escalating reveals. Each chapter ends on a mini-cliffhanger.
        - Add a curiosity reset every 90-150 seconds.
        - Outro (Cliffhanger): End with a question that invites watching another related video to increase "User Session" time.
        - High CTR Topics Priority: Mix [Ancient History] + [Mystery/Disappearance] + [Archaeological Evidence] (e.g., lost legions, sunken cities, impossible technologies).
        - Avoid long preambles, generic context, and filler "as we know" lines.
        - Maintain a serious documentary tone. Historical rigor is non-negotiable.

        CONTENT DEPTH MANDATE (CRITICAL — read carefully):
        - The script MUST discuss the topic substantively from start to finish.
        - If you feel you have covered the main story but have not yet reached the word target, DO NOT add filler or repeat the subscribe call. Instead, go DEEPER: explore counter-theories, lesser-known details, eyewitness accounts, what happened afterward, modern implications, related mysteries, or historical context.
        - The subscribe/CTA call appears ONCE, at the very end. Never repeat it. Never use it to fill space.
        - A script that says "subscribe" more than once will be considered a failure.

        TITLE GUIDANCE (for this long horizontal video):
        - Do NOT use emojis in the title.
        - Preferred pattern: "[PLACE or YEAR]: [Shocking event in 5-8 words]"
          examples: "Gallipoli 1915: The Week Britain Lost Its Empire"
                    "1200 BC: The 50 Years When Civilization Collapsed"
        - Keep title under 70 characters.
        {"- STRICT MODE: If the opening is weak, rewrite aggressively for retention, even if style changes." if is_strict else ""}
        """
        elif is_short:
            short_block = self._build_short_block(category)
        from pipeline.video_opening import opening_script_instructions
        opening_block = opening_script_instructions(opening_style, language=language)

        prompt = f"""
        {role_header}
        {self._build_topic_disambiguation_block(topic)}
        Task: Write a captivating narration script about "{topic}".
        Category: {category} (tone profile: {tone_profile})

        CRITICAL LANGUAGE REQUIREMENT:
        - Language: {lang_instr}
        - ALL narration text MUST be in {'English' if language == 'en' else 'Spanish'}
        - Do NOT mix languages. Use ONLY {'English' if language == 'en' else 'Spanish'} throughout the entire script.
        - This applies to ALL parts of the script: introduction, main content, and conclusion.

        DOCUMENTED FACTS ONLY (NON-NEGOTIABLE):
        - The script MUST be based EXCLUSIVELY on documented facts, events, people, places, and dates that exist in reality.
        - Do NOT invent cases, names, dates, places, events, quotes, institutions, programs, laws, or initiatives. Everything must be verifiable.
        - For tone profile "documentary" and "dramatic_factual": ZERO paranormal/conspiracy content, even disguised. If you are unsure whether something is documented, OMIT it.
        - For tone profile "mystery": reports/testimonies/folklore may be treated as possibilities, but the case or report mentioned MUST have actually existed (do NOT invent entire cases).
        - If you mention a specific date, name, or event, it must be real. If unsure, use phrases like "according to reports from that era" or "witnesses claimed that...", or simply OMIT it.
        - Open questions ("What if this were true?") are allowed ONLY in "mystery" profile. In "documentary", questions must be about real facts debated by historians.
        - IF YOU RUN OUT OF NEW FACTS, DO NOT CUT THE SCRIPT SHORT. First go deeper with documented material: prior historical context, biographies of real protagonists, documented critical decisions, verifiable consequences (short-term and across years/decades), parallels with similar documented events, primary-source testimonies. Only if you genuinely exhausted documented material may you shorten. NEVER invent filler.
        {narrative_approach}
        {quality_block}
        {opening_block}
        {long_block}
        {short_block}

        Length: ~{words} words.
        Format: Just the narration text. No intro/outro notes.
        IMPORTANT: At the very end of the script (and ONLY at the very end, never before), add ONE single call to subscribe to the channel {get_channel_name()} in a natural and engaging way, in {'English' if language == 'en' else 'Spanish'}. Do NOT repeat this call anywhere else in the script.
        {self._build_metadata_request_block() if is_short else ""}
        """

        script = self._generate(
            prompt,
            max_tokens=script_max_tokens,
            task_type="script_quality"
        )
        return self._postprocess_generated_script(
            script=script,
            topic=topic,
            category=category,
            duration_seconds=duration_seconds,
            language=language,
            target_words=words,
            script_max_tokens=script_max_tokens,
            role_header=role_header,
            quality_block=quality_block,
            is_short=is_short,
            opening_block=opening_block,
        )

    def _extract_historical_context(self, topic, full_script, research_context):
        """Extrae contexto histÃ³rico del tema y script completo (con cachÃ©)"""
        if not topic and not full_script:
            return None
        
        # Crear clave de cachÃ© basada en tema y primeros caracteres del script
        cache_key = f"{topic}_{hash(str(full_script)[:500]) if full_script else ''}"
        
        # Verificar cachÃ©
        if cache_key in self._historical_context_cache:
            return self._historical_context_cache[cache_key]
        
        # Combinar todo el texto para anÃ¡lisis
        combined_text = ""
        if topic:
            combined_text += f"Topic: {topic}\n"
        if full_script:
            combined_text += f"Full Script: {full_script}\n"
        if research_context:
            if isinstance(research_context, list):
                combined_text += f"Research: {' '.join(research_context[:5])}\n"
            else:
                combined_text += f"Research: {str(research_context)[:1000]}\n"
        
        if not combined_text:
            return None
        
        # Prompt para extraer contexto historico / temporal
        analysis_prompt = f"""
Role: Expert Historical Analyst and Period Consultant.
Task: Analyze the following text and extract RIGOROUS temporal and cultural context information
so that AI-generated images cannot contain anachronisms.

Text to analyze:
{combined_text[:3000]}

Extract the following with maximum precision. If the content is set in any specific era
(ancient, medieval, industrial, 20th century, contemporary, near-future, etc.), extract it
even if the word "historical" never appears. Modern content also has a period
(e.g., "2020s smartphones exist, 1980s computers do not").

Provide:
1. Time Period: Specific period with year range when possible (e.g., "Ancient Greece (1200-800 BCE)", "Cold War (1947-1991)", "Contemporary (2020s)")
2. Latest Allowed Year: The latest year/decade that can appear in images (e.g., "1200 BCE", "1945", "1969", "present day")
3. Location/Region: Geographic location (e.g., "Aegean Sea", "Western Europe", "North America")
4. Cultural Context: Civilization/culture (e.g., "Mycenaean Greek", "Roman Republic", "Edo-period Japan", "Post-war USA")
5. Key Historical Elements: 3-6 concrete visual anchors specific to this era (e.g., ["bronze spears", "hoplite shields", "triremes with painted eyes", "linen tunics"])
6. Technology Level: Specific technologies that existed (e.g., "Bronze Age: bronze weapons, no iron, no gunpowder, no steel")
7. Clothing Style: Exact period-accurate clothing (e.g., "Linen chitons, bronze cuirasses, Corinthian helmets, leather sandals")
8. Architecture Style: Period-accurate buildings (e.g., "Cyclopean stone walls, megaron halls, NO classical columns yet")
9. Forbidden Elements: CRITICAL list of 6-10 specific things that MUST NEVER appear in images for this era. Be concrete. For Bronze Age Greece: ["iron weapons", "steel armor", "stirrups", "gunpowder", "plate armor", "gothic arches", "wristwatches", "eyeglasses", "modern fabric dyes", "zippers/buttons"]. For WWII: ["smartphones", "digital displays", "modern military camo patterns", "jet engines on allied bombers", "assault rifles", "GPS", "plastic helmets"]. For Ancient Egypt: ["camels in Old Kingdom scenes", "horses before 1600 BCE", "iron tools", "wheel-spoke chariots before New Kingdom"].
10. Is Historical: true if set in a pre-2000 period, false if strictly contemporary
11. Has Temporal Constraints: true if ANY era is identifiable (even modern), false only for timeless/abstract content

Output ONLY valid JSON (no explanations, no markdown):
{{
    "time_period": "specific time period or 'Not specified'",
    "latest_allowed_year": "latest year/era that can appear or 'Not specified'",
    "location": "geographic location or 'Not specified'",
    "cultural_context": "cultural context or 'Not specified'",
    "key_historical_elements": ["element1", "element2", "element3"],
    "technology_level": "technology level with specific inclusions/exclusions or 'Not specified'",
    "clothing_style": "period-accurate clothing details or 'Not specified'",
    "architecture_style": "period-accurate architecture details or 'Not specified'",
    "forbidden_elements": ["forbidden1", "forbidden2", "forbidden3", "forbidden4", "forbidden5", "forbidden6"],
    "is_historical": true or false,
    "has_temporal_constraints": true or false
}}
"""
        
        try:
            result = self._generate(analysis_prompt)
            if not result or result.startswith("ERROR"):
                fallback = self._build_historical_analysis_fallback(topic, full_script, research_context)
                self._historical_context_cache[cache_key] = fallback
                return fallback
            
            # Parsear JSON
            import json
            import re
            
            clean = result.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0]
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0]
            
            clean = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', clean)
            
            if '{' in clean and '}' in clean:
                start = clean.find('{')
                end = clean.rfind('}') + 1
                if start >= 0 and end > start:
                    clean = clean[start:end]
            
            analysis = self._normalize_historical_analysis(json.loads(clean))
            if not analysis:
                raise ValueError("Historical analysis did not contain usable temporal constraints")
            
            # Validar que tenga informacion util (historica O con constraints temporales)
            if analysis.get('is_historical') or analysis.get('has_temporal_constraints') or any(
                analysis.get(key) and analysis.get(key) != 'Not specified'
                for key in ['time_period', 'location', 'cultural_context']
            ):
                # Guardar en cache
                self._historical_context_cache[cache_key] = analysis
                return analysis
            else:
                # Guardar None en cachÃ© para evitar repetir anÃ¡lisis
                pass
            fallback = self._build_historical_analysis_fallback(topic, full_script, research_context)
            self._historical_context_cache[cache_key] = fallback
            return fallback
        except Exception as e:
            print(f"[!] Error extrayendo contexto historico: {e}")
            # Guardar None en cachÃ© para evitar repetir anÃ¡lisis
            fallback = self._build_historical_analysis_fallback(topic, full_script, research_context)
            self._historical_context_cache[cache_key] = fallback
            return fallback

    def generate_video_script_with_research(
        self,
        topic,
        category,
        duration_seconds,
        research_snippets,
        language='es',
        narrative_profile=None,
        opening_style="hook_overlay_v1",
    ):
        """Genera guion con investigaciÃ³n"""
        print(f"ðŸ¤– Claude: Guion investigado ({language})...")
        words = int((duration_seconds / 60) * 150)
        script_max_tokens = self._estimate_script_max_tokens(duration_seconds)
        context = "\n".join(research_snippets)
        lang_instr = "WRITE IN ENGLISH." if language == 'en' else "ESCRIBE EN ESPAÃ‘OL."
        is_long_horizontal = str(narrative_profile or "").lower() in {"long_horizontal", "long_horizontal_strict"}
        is_short = duration_seconds <= 60 or str(narrative_profile or "").lower() in {"short", "tiktok", "reels", "youtube_short"}
        is_strict = str(narrative_profile or "").lower() == "long_horizontal_strict"
        tone_profile = get_tone_profile_for_category(category)
        role_header = self._build_script_role_for_profile(tone_profile)
        narrative_approach = self._build_narrative_approach_for_profile(tone_profile)
        quality_block = self._build_script_quality_block_for_profile(tone_profile)
        if is_mystery_inquiry(category):
            narrative_approach = "Investigative cinematic narrative: source account, context, evidence, competing explanations and unresolved questions."
            quality_block = mystery_editorial_instructions(category, "en")
        long_block = ""
        short_block = ""
        runtime_minutes = round(duration_seconds / 60)
        runtime_display = f"{runtime_minutes} minutes (~{duration_seconds} seconds)"
        if is_long_horizontal:
            long_block = f"""
        RETENTION BLUEPRINT FOR LONG HORIZONTAL VIDEO (MANDATORY):
        - Runtime target: {runtime_display}. Write EXACTLY enough content to fill this duration — no more, no less.
        - Structure: "Retención por Capas".
        - First 0-90 seconds (Intro): MUST pose an "Unsolvable Mystery" or a "Life-or-Death Question". Do NOT use generic introductions. Drop the viewer mid-action.
        - First 2 minutes: deliver a first concrete payoff and set the core conflict. State who, where, when, and what is at stake.
        - Structure the narrative in chapters with clear transitions and escalating reveals. Each chapter ends on a mini-cliffhanger.
        - Add a curiosity reset every 90-150 seconds.
        - Outro (Cliffhanger): End with a question that invites watching another related video to increase "User Session" time.
        - High CTR Topics Priority: Mix [Ancient History] + [Mystery/Disappearance] + [Archaeological Evidence] (e.g., lost legions, sunken cities, impossible technologies).
        - Avoid long preambles, generic context, and filler "as we know" lines.
        - Maintain a serious documentary tone. Historical rigor is non-negotiable.

        CONTENT DEPTH MANDATE (CRITICAL — read carefully):
        - The script MUST discuss the topic substantively from start to finish.
        - If you feel you have covered the main story but have not yet reached the word target, DO NOT add filler or repeat the subscribe call. Instead, go DEEPER: explore counter-theories, lesser-known details, eyewitness accounts, what happened afterward, modern implications, related mysteries, or historical context.
        - The subscribe/CTA call appears ONCE, at the very end. Never repeat it. Never use it to fill space.
        - A script that says "subscribe" more than once will be considered a failure.

        TITLE GUIDANCE (for this long horizontal video):
        - Do NOT use emojis in the title.
        - Preferred pattern: "[PLACE or YEAR]: [Shocking event in 5-8 words]"
          examples: "Gallipoli 1915: The Week Britain Lost Its Empire"
                    "1200 BC: The 50 Years When Civilization Collapsed"
        - Keep title under 70 characters.
        {"- STRICT MODE: If the opening is weak, rewrite aggressively for retention, even if style changes." if is_strict else ""}
        """
        elif is_short:
            short_block = self._build_short_block(category)
        from pipeline.video_opening import opening_script_instructions
        opening_block = opening_script_instructions(opening_style, language=language)

        prompt = f"""
        {role_header}
        {self._build_topic_disambiguation_block(topic)}
        Task: Write a captivating script about "{topic}" using this research as inspiration:
        {context}
        Category: {category} (tone profile: {tone_profile})

        CRITICAL LANGUAGE REQUIREMENT:
        - Language: {lang_instr}
        - ALL narration text MUST be in {'English' if language == 'en' else 'Spanish'}
        - Do NOT mix languages. Use ONLY {'English' if language == 'en' else 'Spanish'} throughout the entire script.
        - The research context above may be in different languages, but YOUR SCRIPT must be entirely in {'English' if language == 'en' else 'Spanish'}.
        - This applies to ALL parts of the script: introduction, main content, and conclusion.

        DOCUMENTED FACTS ONLY (NON-NEGOTIABLE):
        - The script MUST be based EXCLUSIVELY on documented facts, events, people, places, and dates from the research above OR other verifiable sources.
        - Do NOT invent cases, names, dates, places, events, quotes, institutions, programs, laws, or initiatives. Everything must be verifiable.
        - For tone profile "documentary" and "dramatic_factual": ZERO paranormal/conspiracy content, even disguised. If the research doesn't support a claim, OMIT it.
        - For tone profile "mystery": reports/testimonies/folklore may be treated as possibilities, but the case or report mentioned MUST have actually existed.
        - If you mention a specific date, name, or event, it must be real. If unsure, use phrases like "according to reports from that era" or "witnesses claimed that...", or simply OMIT it.
        - Open questions ("What if this were true?") are allowed ONLY in "mystery" profile.
        - IF YOU RUN OUT OF NEW FACTS, DO NOT CUT THE SCRIPT SHORT. First go deeper with documented material: prior historical context, biographies of real protagonists, documented critical decisions, verifiable consequences (short-term and across years/decades), parallels with similar documented events, primary-source testimonies. Only if you genuinely exhausted documented material may you shorten. NEVER invent filler.
        {narrative_approach}
        {quality_block}
        {opening_block}
        {long_block}
        {short_block}

        Length: ~{words} words.
        Format: Just the narration text.
        IMPORTANT: At the very end of the script (and ONLY at the very end, never before), add ONE single call to subscribe to the channel {get_channel_name()} in a natural and engaging way, in {'English' if language == 'en' else 'Spanish'}. Do NOT repeat this call anywhere else in the script.
        {self._build_metadata_request_block() if is_short else ""}
        """
        
        script = self._generate(
            prompt,
            max_tokens=script_max_tokens,
            task_type="script_quality"
        )
        return self._postprocess_generated_script(
            script=script,
            topic=topic,
            category=category,
            duration_seconds=duration_seconds,
            language=language,
            target_words=words,
            script_max_tokens=script_max_tokens,
            role_header=role_header,
            quality_block=quality_block,
            is_short=is_short,
            research_snippets=research_snippets,
            opening_block=opening_block,
        )

    def generate_prompts_for_segment(self, segment_text, category, style, topic=None,
                                     full_script=None, research_context=None, narrative_context=None,
                                     is_long_horizontal=False):
        """Genera prompts visuales para un segmento.

        Args:
            is_long_horizontal: cuando es True, inyecta el bloque de composicion
                16:9 cinematografica (regla de tercios con foco izquierdo,
                paleta calida, contraste L>R, iluminacion cinematica) que
                tambien usa el pipeline de thumbnails. De esta forma las
                imagenes de segmento y las miniaturas comparten lenguaje
                visual y construyen sello de canal.
        """

        # Extraer contexto histÃ³rico completo del script y tema
        historical_analysis = self._extract_historical_context(topic, full_script, research_context)
        
        # Construir contexto global del video con analisis historico
        global_context = ""
        era_anchor = ""  # Ancla temporal corta para inyectar en el visual_prompt
        forbidden_block = ""
        if topic:
            global_context += f"\nGLOBAL VIDEO CONTEXT:\n"
            global_context += f"- Main Topic: {topic}\n"
            global_context += f"- Category: {category}\n"

            # Incluir analisis historico completo
            if historical_analysis:
                global_context += f"\nHISTORICAL / TEMPORAL CONTEXT ANALYSIS:\n"
                if historical_analysis.get('time_period'):
                    global_context += f"- Time Period: {historical_analysis['time_period']}\n"
                if historical_analysis.get('latest_allowed_year'):
                    global_context += f"- Latest Allowed Year/Era in images: {historical_analysis['latest_allowed_year']}\n"
                if historical_analysis.get('location'):
                    global_context += f"- Location/Region: {historical_analysis['location']}\n"
                if historical_analysis.get('cultural_context'):
                    global_context += f"- Cultural Context: {historical_analysis['cultural_context']}\n"
                if historical_analysis.get('key_historical_elements'):
                    global_context += f"- Key Period Anchors (MUST appear or be implied): {', '.join(historical_analysis['key_historical_elements'][:6])}\n"
                if historical_analysis.get('technology_level'):
                    global_context += f"- Technology Level: {historical_analysis['technology_level']}\n"
                if historical_analysis.get('clothing_style'):
                    global_context += f"- Clothing/Style: {historical_analysis['clothing_style']}\n"
                if historical_analysis.get('architecture_style'):
                    global_context += f"- Architecture: {historical_analysis['architecture_style']}\n"

                # Construir ancla temporal corta para el visual_prompt final
                era_anchor = self._analysis_era_anchor(historical_analysis)

                # Construir bloque de elementos prohibidos
                forbidden = historical_analysis.get('forbidden_elements') or []
                if forbidden:
                    forbidden_list = ", ".join(str(f) for f in forbidden[:10])
                    forbidden_block = f"\nFORBIDDEN ELEMENTS (must NEVER appear in the image, not even in the background): {forbidden_list}\n"

            # Incluir resumen del script completo
            if full_script:
                script_summary = full_script[:1500] if len(full_script) > 1500 else full_script
                global_context += f"\n- Full Script Context (first 1500 chars): {script_summary}...\n"

            if research_context:
                research_text = " ".join(research_context[:5]) if isinstance(research_context, list) else str(research_context)[:500]
                global_context += f"\n- Research Context: {research_text}...\n"

            global_context += "\nCRITICAL CONTEXTUAL REQUIREMENTS:\n"
            global_context += "- The visual prompt MUST maintain ABSOLUTE consistency with the global video topic, theme, and temporal context\n"
            global_context += "- EVERY image must reflect the time period, location, and cultural context identified above\n"
            global_context += "- ALL elements in EVERY image must match the period: clothing, armor, weapons, tools, vehicles, ships, buildings, signage, writing systems, hairstyles, facial hair, makeup, and jewelry\n"
            global_context += "- If a segment mentions 'people', 'individuals', 'soldiers', 'sailors', 'warriors', etc., they MUST wear period-accurate clothing/armor from the context above\n"
            global_context += "- Call-to-action / subscription segments must still use imagery rooted in the video's period and culture, never generic modern stock imagery\n"
            global_context += "- NEVER use elements from eras later than the Latest Allowed Year. No smartphones, no cars, no plastic, no modern fabrics, no modern hairstyles, no modern signage, no glasses/watches unless the era allows them\n"
            global_context += "- Apply the period to EVERY segment even if the segment text does not explicitly mention historical details\n"
            global_context += "- If the topic mentions a specific war/battle/event, ALL images must reflect that specific period (e.g., Bronze Age Greek warriors for the Trojan War, not Roman legionaries, not medieval knights, not 18th century ships)\n"

        narrative_context_block = self._format_narrative_context(narrative_context)

        # Determinar si hay constraints temporales activas (histórico O periodo moderno especifico)
        has_temporal = bool(historical_analysis) and (
            historical_analysis.get('is_historical') or historical_analysis.get('has_temporal_constraints')
        )

        historical_context = ""
        if has_temporal and historical_analysis:
            historical_context = f"""
CRITICAL PERIOD-ACCURACY RULES (MUST BE APPLIED TO EVERY IMAGE):
- Time Period: {historical_analysis.get('time_period', 'Extract from topic/script')}
- Latest Allowed Year: {historical_analysis.get('latest_allowed_year', 'Period-appropriate')}
- Location: {historical_analysis.get('location', 'Extract from topic/script')}
- Technology Level: {historical_analysis.get('technology_level', 'Period-appropriate')}
- Clothing Style: {historical_analysis.get('clothing_style', 'Period-appropriate')}
- Architecture: {historical_analysis.get('architecture_style', 'Period-appropriate')}
{forbidden_block}
MANDATORY RULES:
1. Verify dates, locations, and historical figures mentioned in the topic/script
2. Use correct period terminology and period-appropriate descriptions
3. STRICTLY avoid anachronisms — any element from a later era invalidates the image
4. Reference specific archaeological sites, monuments, or artifacts when mentioned in the script
5. Use accurate period labels (e.g., "Bronze Age" not "Medieval" for 1200 BCE)
6. Include specific place names, time periods, and cultural details from the topic/script
7. Apply the period from the main topic to EVERY segment even if the segment does not mention it
8. If topic mentions a specific war/event, ALL images must reflect that exact period
9. Ships, vehicles, weapons, armor, and tools MUST match the period (e.g., bronze spears and oxhide shields for Bronze Age, NOT iron swords or plate armor)
10. People, clothing, hairstyles, jewelry, architecture, and writing systems MUST match the period and location
11. Do NOT mix periods. If uncertain about whether an object existed in this period, do NOT include it
12. Cross-check every noun in your visual_prompt against the Forbidden Elements list before finalizing
"""
        
        # Mapeo de estilos
        style_instructions = {
            "IlustraciÃ³n Digital": "digital illustration style, vibrant colors, clean lines, modern digital art, professional illustration",
            "Cartoon/AnimaciÃ³n": "cartoon style, animated look, bold outlines, bright colors, playful and expressive, Disney/Pixar style",
            "Anime/Manga": "anime style, manga art, Japanese animation aesthetic, expressive eyes, dynamic poses, vibrant colors, detailed backgrounds",
            "Estilo ArtÃ­stico": "artistic style, creative interpretation, unique visual approach, stylized rendering, artistic flair",
            "Acuarela": "watercolor painting style, soft brushstrokes, flowing colors, translucent layers, artistic watercolor technique",
            "Vectorial": "vector art style, clean geometric shapes, flat design, bold colors, minimalist vector illustration",
            "Sketch/Dibujo": "sketch style, hand-drawn look, pencil or ink drawing, artistic sketch, line art, rough sketch aesthetic"
        }
        
        is_illustrative = any(illustrative_style in style for illustrative_style in style_instructions.keys())
        illustrative_context = ""
        if is_illustrative:
            for illus_style, instructions in style_instructions.items():
                if illus_style in style:
                    illustrative_context = f"""
IMPORTANT ILLUSTRATIVE STYLE RULES:
- Apply {illus_style} style: {instructions}
- The visual should be clearly illustrative, not photorealistic
- Use artistic interpretation while maintaining accuracy of the subject matter
- Emphasize the artistic style in the visual prompt
- Include style-specific keywords in the prompt (e.g., "digital illustration", "anime style", "watercolor painting")
"""
                    break
        
        era_anchor_instruction = ""
        if era_anchor:
            era_anchor_instruction = (
                f"\nERA ANCHOR (MANDATORY): The visual_prompt MUST begin or end with an explicit period "
                f"tag like \"set in {era_anchor}\". This anchor is non-negotiable.\n"
            )

        # Bloque de composicion 16:9 cinematografica para videos horizontales
        # largos. Estas reglas son las mismas que usa thumbnail_pipeline.py
        # (SUPER_PROMPT_COMPOSITION_RULES), asi que segmentos y miniaturas
        # comparten lenguaje visual y construyen identidad de canal.
        long_horizontal_composition = ""
        if is_long_horizontal:
            long_horizontal_composition = """
LONG-FORM HORIZONTAL 16:9 COMPOSITION RULES (MANDATORY for this video):
- Cinematic 16:9 framing, 1920x1080 aspect, photoreal documentary style.
- Rule of thirds: the dominant subject (face, action, key prop) anchored in
  the LEFT third of the frame. Right two thirds reserved for environment and
  atmospheric depth.
- Three-point cinematic lighting: warm rim/key light on the subject (firelight,
  sunset, oil lamp, torch, explosion glow), cool desaturated background, smoke
  or dust haze for depth. The LEFT third of the frame should read clearly
  brighter than the RIGHT third.
- Warm dominant palette: burnt orange, amber, sepia, bronze tones. Cool teal
  or charcoal only as counter-background. Avoid neutral grays and pastels.
- Mean scene brightness in the mid-range: not underexposed, not washed out.
  Aim for deep shadows AND real highlights in the same frame.
- Shallow depth of field: foreground subject sharp, midground softly blurred,
  atmospheric haze in the far background.
- Readable emotion on any visible face: tense jaw, dilated pupils, sweat,
  dust, 1000-yard stare. No neutral expressions.
- 50mm lens look, subtle film grain, NOT AI-smooth, NOT plastic CGI,
  NOT digital painting.
- Include at least one material texture detail (bronze patina, wet stone,
  blood-stained leather, cracked plaster, dust particles in a light shaft).
- Absolutely zero modern elements (watches, plastic, modern fabrics, signage,
  vehicles) unless the era explicitly allows them.
"""

        prompt = f"""
Role: Expert AI Art Director and Historical Consultant.
Task: Create a historically rigorous visual prompt from this narration text: "{segment_text}".
Context: Category: {category}, Style: {style}.
{global_context}
{historical_context}
{narrative_context_block}
{illustrative_context}
{era_anchor_instruction}
{long_horizontal_composition}

INSTRUCTIONS:
1. READ the GLOBAL VIDEO CONTEXT and PERIOD-ACCURACY RULES above. Identify the exact period, location, and culture.
2. READ the NARRATIVE CONTEXT WINDOW to understand what just happened, what is happening now, and what happens next.
3. Analyze the CURRENT narration: "{segment_text}". Choose the single most important visible moment it implies.
4. Use previous/next context only to disambiguate characters, setting, chronology, and continuity. Do NOT merge multiple separate events into one image.
5. Ground the image in the period: every visible element (people, clothing, armor, weapons, tools, ships, vehicles, buildings, signage, jewelry, hairstyles, facial hair, cosmetics, fabrics, dyes, musical instruments, animals, crops, vegetation when region-specific) must belong to the identified period and location.
6. If the segment mentions generic nouns ("people", "soldiers", "ships", "a meeting", "a city"), translate them into period-specific equivalents using the Key Period Anchors and Clothing/Architecture fields from the context above.
7. Call-to-action / subscribe / outro segments still belong to the same period — use period imagery (e.g., scrolls, torches, banners, oars) rather than modern icons.
8. BEFORE finalizing the visual_prompt, mentally cross-check every concrete noun in it against the FORBIDDEN ELEMENTS list. If any forbidden element appears, rewrite that part.
9. The visual_prompt must:
   - Match the selected style ({style})
   - Start with the main subject and visible action, then specify environment, period + location, lighting, mood, and material details
   - Include at least 2-3 period anchors (specific clothing, weapon, material, architecture, or tool from the context) even if the narration does not mention them
   - Include the explicit period tag (e.g., "set in Bronze Age Mycenae, c. 1200 BCE")
   - Describe ONLY visible elements in a single coherent still image
   - NOT mention sounds, smells, narration, aspect ratios, platforms, subtitles, timestamps, UI, labels, logos, watermarks, or any written text inside the image
   - NOT mention cameras, camera crews, photographers, microphones, tripods, studio lights, or behind-the-scenes elements
   - Use compact art-direction language; prefer concrete nouns and visible details over vague hype words
   - For Cosmic Catastrophes/Space: Use hyper-realistic massive scales, blinding highlights against deep black voids, cinematic destruction.
   - For Ancient Warfare/History: Use cinematic dirt/grit, dynamic battle tension, dramatic side-lighting, macro-shots of period armor/weapons.
   - For Natural Disasters: Emphasize terrifying scale, violent atmospheric effects, and documentary-style ground-level realism.
   - Specify approximate count and natural posture when people appear, to reduce anatomy errors
   - ALWAYS end with the literal phrase: "no text, no writing, no signs, no captions, no watermarks"

ABSOLUTE PROHIBITION — ZERO TEXT IN THE IMAGE:
- The generated image must contain ZERO visible text of any kind: no signs, no posters, no inscriptions, no scrolls with readable text, no subtitles, no titles, no watermarks, no logos, no UI elements, no numbers, no letters of any script or alphabet.
- This includes: cuneiform tablets with readable symbols, open books with visible text, chalkboards, screens with text, flags with letters, coins with readable inscriptions, papyrus with writing, newspapers, documents.
- The ONLY exception: decorative worn carvings whose symbols are indistinct and unreadable (e.g., "ancient carved stone with worn indistinct symbols") — ONLY if symbols cannot be read.
- This rule is NON-NEGOTIABLE and overrides any other instruction. Even if the narration mentions a letter, document, or inscription, do NOT render readable text in the image. Instead show the object closed, from a distance, or from an angle where text is not legible.
10. If illustrative style: apply the artistic style consistently while keeping period accuracy intact.
11. Avoid generic descriptions — be SPECIFIC about period, location, clothing, architecture, technology, and cultural elements.
12. NEVER use anachronisms. When in doubt about whether an element existed in the period, leave it out.
13. For SFX: sound keyword matching the period (e.g., "bronze weapons clashing", "trireme oars", "WWII artillery", or "none").
14. For Overlays: animated overlay matching the theme (e.g., "fire", "smoke", "dust", or "none").

QUALITY AND ERROR PREVENTION:
- Avoid distortions, deformities, anatomical errors, text/watermark artifacts
- Prefer one compact paragraph, not a list of disconnected buzzwords
- Avoid filler adjectives ("epic", "stunning", "masterpiece", "trending", "award-winning") unless they describe a visible property
- Favor believable physical details and period-accurate materials over spectacle wording

SELF-VERIFICATION (do this before outputting):
- Does every noun in visual_prompt exist in the identified period? If not, replace it.
- Does the visual_prompt contain the explicit period tag? If not, add it.
- Does it include at least 2 period anchors from the context? If not, add them.
- Does it contain any forbidden element from the list above? If so, rewrite.

Output ONLY valid JSON (no explanations, no markdown):
{{
    "visual_prompt": "compact period-accurate english prompt for one still image matching the narration '{segment_text}', in style '{style}'. Must start with the main subject and visible action, then specify environment, explicit period tag (e.g. 'set in <period>, <location>'), lighting, mood, and period-accurate material details. Must include at least 2-3 concrete period anchors from the context (specific clothing, weapon, architecture, tool). Must not contain any element from the Forbidden Elements list. Describe only visible elements. No audio, no camera language, no production equipment, no aspect ratios, no platforms, no subtitles, no UI. MUST end with: no text, no writing, no signs, no captions, no watermarks",
    "period_tag": "short era tag included inside visual_prompt, e.g. 'Bronze Age Mycenae, c.1200 BCE' or 'none' if the topic is timeless",
    "sfx_tag": "sound keyword in english matching the period or 'none'",
    "overlay_tag": "gif keyword in english matching the theme or 'none'",
    "on_screen_text": "short text to overlay on screen for this segment — a date ('536 AD'), a place ('POMPEII'), a dramatic phrase ('NO SURVIVORS'), or empty string if none fits. Max 4 words, uppercase. Only include when it adds real informational value."
}}

REMEMBER:
1. Even if the segment text does not explicitly mention historical details, the visual prompt MUST include the period context from the main topic.
2. The visual_prompt must read like an art-direction brief for a single still image, never like behind-the-scenes footage.
3. The image must represent the CURRENT narration beat. Previous and next beats are only for continuity and disambiguation.
4. When uncertain whether an element belongs to the period, OMIT it rather than risk an anachronism.
"""
        
        res = self._generate(prompt)
        
        # El mÃ©todo _generate ya intenta Groq primero y Claude como fallback
        # Si ambos fallan, retornar error
        if res == "ERROR_QUOTA_EXCEEDED" or res == "ERROR_AUTH" or (isinstance(res, str) and res.startswith("ERROR")):
            return {
                "visual_prompt": res if res else "ERROR: Groq y Claude Code CLI fallaron",
                "sfx_tag": "none",
                "overlay_tag": "none"
            }
        
        # Parsear respuesta JSON
        import json
        import re
        try:
            clean = res.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0]
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0]
            
            clean = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', clean)
            
            if '{' in clean and '}' in clean:
                start = clean.find('{')
                end = clean.rfind('}') + 1
                if start >= 0 and end > start:
                    clean = clean[start:end]
            
            result = json.loads(clean)

            visual_prompt = result.get('visual_prompt', '')
            if len(visual_prompt.split()) < 5:
                visual_prompt = f"{visual_prompt}, {category} style, detailed, accurate"

            # Post-process: enforce period anchor and scan forbidden elements
            if has_temporal and historical_analysis:
                visual_prompt = self._enforce_period_accuracy(
                    visual_prompt,
                    era_anchor=era_anchor,
                    forbidden_elements=historical_analysis.get('forbidden_elements') or [],
                    segment_text=segment_text,
                )

            result['visual_prompt'] = visual_prompt
            return result
        except Exception as e:
            print(f"[!] Error parseando JSON de image prompt: {e}")
            print(f"   Respuesta recibida: {res[:200] if res else 'None'}...")
            fallback = f"detailed still image of {segment_text[:40]}, {category} style"
            if era_anchor:
                fallback += f", set in {era_anchor}, period-accurate details"
            return {
                "visual_prompt": fallback,
                "sfx_tag": "none",
                "overlay_tag": "none"
            }

    def _enforce_period_accuracy(self, visual_prompt: str, era_anchor: str,
                                  forbidden_elements: list, segment_text: str = "") -> str:
        """Post-process a generated visual prompt to enforce period anchor and flag anachronisms.

        - Appends the era anchor if the LLM forgot it.
        - Scans the prompt for any forbidden element keyword; if found, logs a warning and
          appends an explicit negative clarifier so downstream generators are less likely to
          include it anyway.
        """
        if not visual_prompt:
            return visual_prompt

        lowered = visual_prompt.lower()

        # 1. Asegurar que aparezca el ancla temporal
        if era_anchor:
            anchor_lower = era_anchor.lower()
            anchor_tokens = [tok.strip() for tok in anchor_lower.replace(',', ' ').split() if len(tok.strip()) > 3]
            has_anchor = any(tok in lowered for tok in anchor_tokens) if anchor_tokens else False
            if not has_anchor:
                visual_prompt = f"{visual_prompt.rstrip('. ')}. Set in {era_anchor}, period-accurate details throughout."
                lowered = visual_prompt.lower()

        # 2. Escanear elementos prohibidos
        if forbidden_elements:
            hits = []
            for element in forbidden_elements:
                token = str(element).strip().lower()
                if not token or len(token) < 3:
                    continue
                token_pattern = r"(?<![a-z0-9])" + re.escape(token).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
                core = token.split()[0] if token.split() else token
                core_pattern = r"(?<![a-z0-9])" + re.escape(core) + r"(?![a-z0-9])"
                if re.search(token_pattern, lowered) or (len(core) >= 5 and re.search(core_pattern, lowered)):
                    hits.append(element)

            if hits:
                try:
                    preview = segment_text[:60].replace('\n', ' ') if segment_text else ""
                    print(f"[!] Anacronismo potencial en prompt ({preview}...): {hits[:3]}")
                except Exception:
                    pass
                neg = ", ".join(str(h) for h in hits[:5])
                visual_prompt = f"{visual_prompt.rstrip('. ')}. Absolutely no {neg}; strictly period-accurate."

        return visual_prompt
