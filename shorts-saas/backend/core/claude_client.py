# claude_client.py
# Cliente para interactuar con Claude Code CLI (ejecuciÃ³n local sin API key)
# Usa Groq como IA principal y Claude Code CLI como fallback automÃ¡tico

import os
import subprocess
import shutil
import platform

# Importar Groq como fallback
try:
    from groq_client import GroqAiClient
    GROQ_AVAILABLE = True
except ImportError:
    GroqAiClient = None
    GROQ_AVAILABLE = False
    print("âš ï¸ groq_client.py no encontrado. Groq fallback no estarÃ¡ disponible.")

def load_env_file():
    """Cargar manualmente variables desde .env"""
    env_file = os.path.join(os.path.dirname(__file__), '.env')
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

class ClaudeAiClient:
    """
    Cliente para interactuar con Claude Code CLI (ejecuciÃ³n local).
    NO requiere API key, ejecuta Claude Code CLI como proceso local.
    Usa Groq como IA principal y Claude Code CLI como fallback automÃ¡tico.
    """
    def __init__(self):
        self.claude_cmd = self._find_claude_command()
        # Cache para anÃ¡lisis histÃ³rico (evita repetir anÃ¡lisis para el mismo tema/script)
        self._historical_context_cache = {}
        self.client_available = False # Propiedad necesaria para chequeos externos
        
        # Inicializar Groq como IA principal
        self.groq_client = None
        if GROQ_AVAILABLE and GroqAiClient:
            try:
                self.groq_client = GroqAiClient()
                if self.groq_client and self.groq_client.client:
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
        else:
            print("âš ï¸ ADVERTENCIA: Claude Code CLI no encontrado en el sistema (fallback no disponible)")
            # Si Groq estÃ¡ disponible, marcar como disponible aunque no haya Claude
            if self.groq_client and self.groq_client.client:
                self.client_available = True
            print("   AsegÃºrate de tener Claude Code instalado y accesible desde PATH")
            print("   O configurar la ruta en CLAUDE_CLI_PATH si estÃ¡ en ubicaciÃ³n personalizada")

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
    
    def _find_claude_command(self):
        """Busca el comando de Claude Code CLI en el sistema"""
        # Primero verificar si hay una ruta personalizada en env
        custom_path = os.getenv("CLAUDE_CLI_PATH")
        if custom_path and os.path.exists(custom_path):
            return custom_path
        
        # Intentar encontrar en PATH
        possible_commands = ["claude", "claude-code", "claude-cli"]
        
        for cmd in possible_commands:
            cmd_path = shutil.which(cmd)
            if cmd_path:
                return cmd_path
        
        # En Windows, buscar en ubicaciones comunes
        if platform.system() == "Windows":
            common_paths = [
                os.path.expanduser("~\\AppData\\Local\\Programs\\claude\\claude.exe"),
                os.path.expanduser("~\\AppData\\Roaming\\claude\\claude.exe"),
                "C:\\Program Files\\Claude\\claude.exe",
                "C:\\Program Files (x86)\\Claude\\claude.exe",
            ]
            
            for path in common_paths:
                if os.path.exists(path):
                    return path
        
        return None
    
    def _generate_with_claude_cli(self, prompt_text, max_tokens=4096):
        """Genera texto usando Claude Code CLI con verificaciÃ³n de cuotas"""
        if not self.claude_cmd:
            print("âš ï¸ Claude Code CLI no disponible: comando no encontrado")
            return None
        
        try:
            print(f"[DEBUG] Ejecutando Claude CLI...")
            
            # Primero verificar cuotas disponibles con un comando simple
            try:
                print("[DEBUG] Verificando cuotas de Claude CLI...")
                quota_check = subprocess.run(
                    [self.claude_cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=True if platform.system() == "Windows" else False
                )
                
                if quota_check.returncode != 0:
                    print("   âš ï¸ Claude CLI no responde (posible problema de cuotas o conexiÃ³n)")
                    if quota_check.stderr:
                        error_msg = quota_check.stderr.lower()
                        if any(keyword in error_msg for keyword in ["quota", "limit", "rate", "429", "usage"]):
                            print("   âŒ Error de cuotas detectado en Claude CLI")
                            return "ERROR_QUOTA_EXCEEDED"
                        elif any(keyword in error_msg for keyword in ["auth", "permission", "403", "unauthorized"]):
                            print("   âŒ Error de autenticaciÃ³n en Claude CLI")
                            return "ERROR_AUTH"
                    return None
                else:
                    print(f"   âœ… Claude CLI operativo: {quota_check.stdout.strip()}")
            except Exception as e:
                print(f"   âš ï¸ No se pudo verificar cuotas de Claude CLI: {str(e)[:50]}")
            
            # CRÃTICO: En Windows, usar subprocess.run con mejor manejo de recursos
            # evita el crash STATUS_STACK_BUFFER_OVERRUN (0xC0000409)
            
            # Crear flags de creaciÃ³n especÃ­ficos para Windows
            creation_flags = 0
            if platform.system() == "Windows":
                # CREATE_NO_WINDOW evita crear ventana de consola adicional
                creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0x08000000

            # Intentar diferentes formas de llamar a Claude CLI
            # Algunas versiones pueden requerir flags especÃ­ficos
            claude_args = [self.claude_cmd]
            
            # Verificar si el comando es un .CMD o .BAT (Windows)
            if self.claude_cmd.lower().endswith('.cmd') or self.claude_cmd.lower().endswith('.bat'):
                # En Windows, los .CMD/.BAT pueden necesitar ser llamados con cmd.exe
                claude_args = ['cmd.exe', '/c', self.claude_cmd]
            
            # Usar subprocess.run (mÃ¡s simple y robusto que Popen)
            result = subprocess.run(
                claude_args,
                input=prompt_text,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',  # Asegurar codificaciÃ³n UTF-8
                errors='replace',  # Reemplazar caracteres invÃ¡lidos
                timeout=120,  # 2 minutos timeout
                creationflags=creation_flags,
                # CRÃTICO: Cerrar handles automÃ¡ticamente en Windows
                close_fds=True if platform.system() != "Windows" else False
            )

            # Verificar resultado
            stdout_text = result.stdout.strip() if result.stdout else ""
            stderr_text = result.stderr.strip() if result.stderr else ""
            
            # Caso 1: Ã‰xito con contenido
            if result.returncode == 0 and stdout_text:
                response = stdout_text
                print("[DEBUG] Claude CLI completado exitosamente")
                return response
            
            # Caso 2: CÃ³digo 0 pero sin contenido (puede ser que Claude CLI no respondiÃ³ correctamente)
            if result.returncode == 0 and not stdout_text:
                print(f"âš ï¸ Claude Code CLI completÃ³ sin errores pero no devolviÃ³ contenido")
                if stderr_text:
                    print(f"   Stderr: {stderr_text[:300]}")
                print("   ðŸ’¡ Posibles causas:")
                print("      - Claude CLI puede requerir autenticaciÃ³n interactiva")
                print("      - El prompt puede ser demasiado largo")
                print("      - Claude CLI puede estar esperando entrada adicional")
                return None
            
            # Caso 3: Error con cÃ³digo distinto de 0
            print(f"âš ï¸ Claude Code CLI retornÃ³ cÃ³digo de error: {result.returncode}")
            error_msg = stderr_text
            if error_msg:
                print(f"   Error: {error_msg[:300]}")
            elif stdout_text:
                # A veces el error estÃ¡ en stdout
                print(f"   Output: {stdout_text[:300]}")
            
            # Detectar errores de cuotas/rate limits
            error_lower = error_msg.lower() if error_msg else ""
            stdout_lower = stdout_text.lower() if stdout_text else ""
            combined_error = f"{error_lower} {stdout_lower}"
            
            # Palabras clave que indican cuotas agotadas
            quota_keywords = [
                "quota", "rate limit", "429", "insufficient", 
                "exceeded", "limit reached", "too many requests",
                "cuota", "lÃ­mite", "agotado", "excedido", "usage"
            ]
            
            # Palabras clave que indican errores de autenticaciÃ³n
            auth_keywords = [
                "auth", "permission", "403", "unauthorized", "forbidden",
                "authentication", "login", "credential"
            ]
            
            if any(keyword in combined_error for keyword in quota_keywords):
                print("   ðŸ’¡ Detectado: Error de cuotas agotadas en Claude CLI")
                return "ERROR_QUOTA_EXCEEDED"
            elif any(keyword in combined_error for keyword in auth_keywords):
                print("   ðŸ’¡ Detectado: Error de autenticaciÃ³n en Claude CLI")
                return "ERROR_AUTH"
                
            return None

        except subprocess.TimeoutExpired:
            print("   âš ï¸ Claude CLI timeout (mÃ¡s de 2 minutos)")
            return None
        except Exception as e:
            print(f"   âš ï¸ Error ejecutando Claude CLI: {str(e)[:100]}")
            return None
    
    def _generate(self, prompt_text, max_tokens=4096, task_type="general"):
        """Genera texto usando Groq como IA principal, con Claude Code CLI como fallback"""
        # Intentar primero con Groq (IA principal)
        if self.groq_client and self.groq_client.client:
            print("   âš¡ Consultando a Groq (IA principal)...")
            groq_result = self.groq_client._generate(
                prompt_text,
                max_tokens=max_tokens,
                task_type=task_type
            )
            if groq_result and not (isinstance(groq_result, str) and groq_result.startswith("ERROR")):
                print("   âœ… Groq generÃ³ respuesta exitosamente")
                return groq_result
            print("   âš ï¸ Groq fallÃ³, intentando con Claude Code CLI como fallback...")
        else:
            print("   âš ï¸ Groq no estÃ¡ disponible, intentando con Claude Code CLI...")
        
        # Si Groq no estÃ¡ disponible o fallÃ³, intentar con Claude Code CLI como fallback
        if not self.claude_cmd:
            print("   âŒ Claude Code CLI no estÃ¡ disponible")
            if not (self.groq_client and self.groq_client.client):
                print("   âŒ Funciones de IA deshabilitadas (Groq no configurado y Claude no disponible)")
            return None
        
        # Intentar con Claude Code CLI como fallback
        result = self._generate_with_claude_cli(prompt_text, max_tokens)
        
        # Si Claude tambiÃ©n falla, retornar el resultado (puede ser None o error)
        if not result or result == "ERROR_QUOTA_EXCEEDED" or result == "ERROR_AUTH" or (isinstance(result, str) and result.startswith("ERROR")):
            print("   âš ï¸ Claude Code CLI tambiÃ©n fallÃ³")
            return result
        
        print("   âœ… Claude Code CLI generÃ³ respuesta exitosamente (fallback)")
        return result

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

        result = self._generate(prompt, max_tokens=600, task_type="script_quality")
        if not result or (isinstance(result, str) and result.startswith("ERROR")):
            return []

        import re, json
        match = re.search(r'\[.*\]', result, re.DOTALL)
        if not match:
            return []
        try:
            suggestions = json.loads(match.group(0))
            return [s for s in suggestions if isinstance(s, dict) and s.get('text')]
        except Exception:
            return []

    def generate_thumbnail_super_prompt(self, topic, script_excerpt="", category="", language="es"):
        """Genera [POSITIVE PROMPT] y [NEGATIVE PROMPT] para thumbnail en IA externa.

        Devuelve un dict {'positive': str, 'negative': str} o None si falla.
        """
        print("Generando super prompt de thumbnail para IA externa...")
        lang_note = "The video is in Spanish." if language == "es" else "The video is in English."
        script_block = f"\nScript excerpt (first 1200 chars):\n{script_excerpt[:1200]}" if script_excerpt else ""

        prompt = f"""You are a senior YouTube thumbnail art director specialized in cinematic historical, war, and mystery content.

VIDEO DATA:
- Title / Topic: {topic}
- Category: {category or "mystery / history"}
- {lang_note}{script_block}

TASK: Analyze the video data above and generate a cinematic thumbnail prompt for an external AI image generator (Midjourney, DALL-E, Stable Diffusion, etc.).

From the video data, infer and fill these variables:
- event_name: full title or event
- year_era: period (e.g. "1908", "ancient Rome", "medieval", etc.)
- location: geographic / historical setting
- central_figure: the single most impactful visual subject (person, creature, object, landscape)
- emotional_hook: one of — fear / betrayal / shock / loss / glory
- short_text: 2-3 ALL CAPS words for text overlay (max 3 words, punchy, in the video's language)
- era_anchor: one sentence describing the exact period-accurate scene (clothing, weapons, architecture, light, season)

MANDATORY COMPOSITION RULES (all must be respected):
1. 16:9, 1920x1080, photoreal cinematic still.
2. Rule of thirds: main subject face/eyes on the LEFT third intersection.
3. Subject occupies 55-70% of frame height. Eyes visible, expression matches emotional_hook.
4. Strong left-to-right luminance gradient: left side brighter than right by >= 20 luminance points.
5. RIGHT third kept as calm negative space (sky, smoke, darkness) — reserved for the short_text overlay. Do NOT place the subject there.
6. Cinematic rim light + warm key light from upper-left, cool fill from right.
7. 50mm full-frame lens look, shallow depth of field, subject tack sharp, background softly defocused.
8. Background clearly suggests location + era (architecture, terrain, banners, smoke, weather).
9. Color palette: warm dominants (amber, ember, blood-red, bronze) against cool shadows (steel blue, slate). No pastels, no neon.
10. High micro-contrast on the face. Skin texture visible. Sweat / dust acceptable if plausible.
11. NO modern objects, NO wristwatches, NO zippers, NO synthetic fabrics, NO contemporary haircuts.
12. NO garbled letters, NO fake glyphs, NO watermark, NO logo, NO frame, NO border, NO text in the image.
13. Reads clearly at 320x180 px (mobile feed test).
14. ONE single focal subject. Secondary figures only as silhouettes or out of focus.
15. Mood: cinematic poster, History Channel x A24, photographic realism — NOT illustration, NOT anime.

QUANTITATIVE TARGETS:
- Average luminance: 100-150 (out of 255).
- Left-half mean luminance minus right-half mean luminance: >= 20.
- Edge density on the left third: >= 55% of total edge mass.
- Warm channel (R+G) minus cool channel (B): >= 15 on average.
- No single histogram bin > 30% of pixels.

COLOR SYSTEM — Highlights: #f3c267, #e07a2b, #b32a1c — Mids: #6a3a1e, #2f3a44 — Shadows: #0e1318, #1a2330

EMOTIONAL HOOK:
- shock → widened eyes, open mouth, tense shoulders
- fear → half-lit profile, darting eyes
- betrayal → clenched jaw, narrowed eyes
- loss → downward gaze, slack expression
- glory → raised chin, side light, confident expression

PROHIBITED ELEMENTS (for negative prompt):
garbled text, fake letters, text artifacts, deformed hands, extra fingers, extra limbs, modern clothing, wristwatch, sunglasses, smartphone, plastic, neon, pastel colors, cartoon, anime, 3d render, cgi look, low contrast, washed out, flat lighting, centered subject, symmetrical composition, watermark, logo, signature, frame, border, blurry subject, motion blur on face, multiple faces competing, crowd as main subject

Return EXACTLY two blocks with no extra text before, between, or after them:

[POSITIVE PROMPT]
<one dense paragraph in English, comma-separated, all rules applied, ending with: cinematic 16:9, 1920x1080, photoreal, 50mm, shallow depth of field, dramatic lighting>

[NEGATIVE PROMPT]
<prohibited elements list, comma-separated>
"""
        result = self._generate(prompt, max_tokens=1200, task_type="script_quality")
        if not result or (isinstance(result, str) and result.startswith("ERROR")):
            return None

        import re
        pos_match = re.search(r'\[POSITIVE PROMPT\]\s*\n(.*?)(?=\[NEGATIVE PROMPT\]|\Z)', result, re.DOTALL)
        neg_match = re.search(r'\[NEGATIVE PROMPT\]\s*\n(.*?)$', result, re.DOTALL)

        positive = pos_match.group(1).strip() if pos_match else result.strip()
        negative = neg_match.group(1).strip() if neg_match else (
            "garbled text, fake letters, text artifacts, deformed hands, extra fingers, extra limbs, "
            "modern clothing, wristwatch, sunglasses, smartphone, plastic, neon, pastel colors, cartoon, "
            "anime, 3d render, cgi look, low contrast, washed out, flat lighting, centered subject, "
            "symmetrical composition, watermark, logo, signature, frame, border, blurry subject, "
            "motion blur on face, multiple faces competing, crowd as main subject"
        )
        return {"positive": positive, "negative": negative}

    def _estimate_script_max_tokens(self, duration_seconds: int) -> int:
        """Calcula un presupuesto de tokens de salida para guiones largos."""
        try:
            words_target = int((max(1, int(duration_seconds)) / 60) * 150)
        except Exception:
            words_target = 600
        estimated_tokens = int(words_target * 1.8)
        return max(4096, min(12000, estimated_tokens))

    def _build_script_quality_block(self) -> str:
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
        - Avoid empty phrases: "como todos sabemos", "a lo largo de la historia", "sin lugar a dudas".
        - Use rhetorical questions strategically to hook the viewer (e.g., "But what really happened that night?").
        - End with an open question or thought-provoking reflection that leaves the viewer wanting more.
        """

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

    def generate_video_script(self, topic, category, duration_seconds, language='es', narrative_profile=None):
        """Genera guion de video"""
        print(f"ðŸ¤– Claude: Generando guion ({language})...")
        words = int((duration_seconds / 60) * 150)
        script_max_tokens = self._estimate_script_max_tokens(duration_seconds)
        lang_instr = "WRITE IN ENGLISH." if language == 'en' else "ESCRIBE EN ESPAÃ‘OL."
        is_long_horizontal = str(narrative_profile or "").lower() in {"long_horizontal", "long_horizontal_strict"}
        is_strict = str(narrative_profile or "").lower() == "long_horizontal_strict"
        quality_block = self._build_script_quality_block()
        long_block = ""
        if is_long_horizontal:
            runtime_minutes = round(duration_seconds / 60)
            runtime_display = f"{runtime_minutes} minutes (~{duration_seconds} seconds)"
            long_block = f"""
        RETENTION BLUEPRINT FOR LONG HORIZONTAL VIDEO (MANDATORY):
        - Runtime target: {runtime_display}. Write EXACTLY enough content to fill this duration — no more, no less.
        - First 30 seconds: hook + stakes + open loop (must create curiosity).
        - First 2 minutes: deliver first concrete payoff and set the core conflict.
        - Structure the narrative in 6-10 chapters with clear transitions and escalating reveals.
        - Add a curiosity reset every 90-150 seconds (new question, reveal, contrast, or unexpected fact).
        - Keep first minute sentences concise and punchy.
        - Avoid long preambles and generic context in the opening.

        CONTENT DEPTH MANDATE (CRITICAL — read carefully):
        - The script MUST discuss the topic substantively from start to finish.
        - If you feel you have covered the main story but have not yet reached the word target, DO NOT add filler or repeat the subscribe call. Instead, go DEEPER: explore counter-theories, lesser-known details, eyewitness accounts, what happened afterward, modern implications, related mysteries, or historical context.
        - The subscribe/CTA call appears ONCE, at the very end. Never repeat it. Never use it to fill space.
        - A script that says "subscribe" more than once will be considered a failure.

        {"- STRICT MODE: If the opening is weak, rewrite aggressively for retention, even if style changes." if is_strict else ""}
        """

        prompt = f"""
        Role: Expert Scriptwriter for a YouTube channel about mysteries, conspiracies, and unexplained phenomena.
        Task: Write a captivating narration script about "{topic}".

        CRITICAL LANGUAGE REQUIREMENT:
        - Language: {lang_instr}
        - ALL narration text MUST be in {'English' if language == 'en' else 'Spanish'}
        - Do NOT mix languages. Use ONLY {'English' if language == 'en' else 'Spanish'} throughout the entire script.
        - This applies to ALL parts of the script: introduction, main content, and conclusion.

        NARRATIVE APPROACH:
        - Write for an audience that loves mysteries, conspiracies, and unexplained phenomena.
        - Use real locations, organizations, and known facts as the foundation, then explore the mystery around them.
        - Present alternative theories and witness accounts as intriguing possibilities worth exploring.
        - Do NOT debunk or dismiss — instead, invite the viewer to think and question.
        - Build suspense, use dramatic pacing, and create curiosity hooks throughout.
        - Frame uncertain claims with phrases like "some believe", "witnesses report", "according to certain investigators".
        - Maintain internal consistency (don't contradict your own dates or facts within the script).
        {quality_block}
        {long_block}

        Length: ~{words} words.
        Format: Just the narration text. No intro/outro notes.
        IMPORTANT: At the very end of the script (and ONLY at the very end, never before), add ONE single call to subscribe to the channel "Stunning Revelations" in a natural and engaging way, in {'English' if language == 'en' else 'Spanish'}. Do NOT repeat this call anywhere else in the script.
        """
        
        script = self._generate(
            prompt,
            max_tokens=script_max_tokens,
            task_type="script_quality"
        )
        # El mÃ©todo _generate ya intenta Groq primero y Claude como fallback
        # Si ambos fallan, retornar error
        if script == "ERROR_QUOTA_EXCEEDED" or script == "ERROR_AUTH" or (script and script.startswith("ERROR")):
            return script

        if self._script_needs_refinement(script, words):
            print("   âš ï¸ Guion con baja densidad detectado. Aplicando refinamiento anti-relleno...")
            refine_prompt = f"""
            Role: Senior Script Editor for a mystery/conspiracy YouTube channel.
            Task: Rewrite this narration script to be more engaging, suspenseful, and captivating.

            Language: {'English' if language == 'en' else 'Spanish'} only.
            Keep same topic: "{topic}".
            Target length: ~{words} words.
            {quality_block}

            Additional rewrite constraints:
            - Remove repetitive phrases and generic filler.
            - Add more suspense, mystery, and intrigue to the narrative.
            - Use dramatic transitions between sections.
            - Keep a captivating narration voice for a mystery/conspiracy YouTube channel.
            - Return ONLY the final narration text.

            Script to rewrite:
            {script}
            """
            refined = self._generate(
                refine_prompt,
                max_tokens=script_max_tokens,
                task_type="script_quality"
            )
            if refined and not str(refined).startswith("ERROR") and len(refined.split()) >= int(words * 0.65):
                script = refined

        if script:
            script = self._deduplicate_cta(script)

        if script and "stunning revelations" not in script.lower() and "suscrÃ­bete" not in script.lower() and "subscribe" not in script.lower():
            if language == 'es':
                script += "\n\nNo olvides suscribirte a Stunning Revelations para mÃ¡s contenido fascinante."
            else:
                script += "\n\nDon't forget to subscribe to Stunning Revelations for more fascinating content."
        return script

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
        
        # Prompt para extraer contexto histÃ³rico
        analysis_prompt = f"""
Role: Expert Historical Analyst.
Task: Analyze the following text and extract ALL historical context information.

Text to analyze:
{combined_text[:3000]}

Extract and provide:
1. Time Period: Specific historical period (e.g., "Ancient Greece (1200-800 BCE)", "World War II (1939-1945)", "Medieval Europe (5th-15th century)")
2. Location: Geographic location or region (e.g., "Ancient Greece", "Mediterranean", "Europe", "Egypt")
3. Cultural Context: Cultural or civilization context (e.g., "Ancient Greek civilization", "Medieval European", "Ancient Egyptian")
4. Key Historical Elements: List of 3-5 key historical elements mentioned (e.g., ["Trojan War", "Greek triremes", "Ancient Greek warriors"])
5. Technology Level: Technology level of the period (e.g., "Bronze Age technology", "Medieval technology", "Ancient naval technology")
6. Clothing Style: Typical clothing/style of the period (e.g., "Ancient Greek tunics and armor", "Medieval European clothing")
7. Architecture Style: Architecture style of the period (e.g., "Ancient Greek architecture", "Medieval castles")
8. Is Historical: true/false - whether this is clearly historical content

Output ONLY valid JSON (no explanations, no markdown):
{{
    "time_period": "specific time period or 'Not specified'",
    "location": "geographic location or 'Not specified'",
    "cultural_context": "cultural context or 'Not specified'",
    "key_historical_elements": ["element1", "element2", "element3"],
    "technology_level": "technology level or 'Not specified'",
    "clothing_style": "clothing style or 'Not specified'",
    "architecture_style": "architecture style or 'Not specified'",
    "is_historical": true or false
}}
"""
        
        try:
            result = self._generate(analysis_prompt)
            if not result or result.startswith("ERROR"):
                return None
            
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
            
            analysis = json.loads(clean)
            
            # Validar que tenga informaciÃ³n Ãºtil
            if analysis.get('is_historical') or any(
                analysis.get(key) and analysis.get(key) != 'Not specified' 
                for key in ['time_period', 'location', 'cultural_context']
            ):
                # Guardar en cachÃ©
                self._historical_context_cache[cache_key] = analysis
                return analysis
            else:
                # Guardar None en cachÃ© para evitar repetir anÃ¡lisis
                self._historical_context_cache[cache_key] = None
                return None
        except Exception as e:
            print(f"âš ï¸ Error extrayendo contexto histÃ³rico: {e}")
            # Guardar None en cachÃ© para evitar repetir anÃ¡lisis
            self._historical_context_cache[cache_key] = None
            return None

    def generate_video_script_with_research(
        self,
        topic,
        category,
        duration_seconds,
        research_snippets,
        language='es',
        narrative_profile=None
    ):
        """Genera guion con investigaciÃ³n"""
        print(f"ðŸ¤– Claude: Guion investigado ({language})...")
        words = int((duration_seconds / 60) * 150)
        script_max_tokens = self._estimate_script_max_tokens(duration_seconds)
        context = "\n".join(research_snippets)
        lang_instr = "WRITE IN ENGLISH." if language == 'en' else "ESCRIBE EN ESPAÃ‘OL."
        is_long_horizontal = str(narrative_profile or "").lower() in {"long_horizontal", "long_horizontal_strict"}
        is_strict = str(narrative_profile or "").lower() == "long_horizontal_strict"
        quality_block = self._build_script_quality_block()
        long_block = ""
        if is_long_horizontal:
            runtime_minutes = round(duration_seconds / 60)
            runtime_display = f"{runtime_minutes} minutes (~{duration_seconds} seconds)"
            long_block = f"""
        RETENTION BLUEPRINT FOR LONG HORIZONTAL VIDEO (MANDATORY):
        - Runtime target: {runtime_display}. Write EXACTLY enough content to fill this duration — no more, no less.
        - First 30 seconds: hook + stakes + open loop (must create curiosity).
        - First 2 minutes: deliver first concrete payoff and set the core conflict.
        - Structure the narrative in 6-10 chapters with clear transitions and escalating reveals.
        - Add a curiosity reset every 90-150 seconds (new question, reveal, contrast, or unexpected fact).
        - Keep first minute sentences concise and punchy.
        - Avoid long preambles and generic context in the opening.

        CONTENT DEPTH MANDATE (CRITICAL — read carefully):
        - The script MUST discuss the topic substantively from start to finish.
        - If you feel you have covered the main story but have not yet reached the word target, DO NOT add filler or repeat the subscribe call. Instead, go DEEPER: explore counter-theories, lesser-known details, eyewitness accounts, what happened afterward, modern implications, related mysteries, or historical context.
        - The subscribe/CTA call appears ONCE, at the very end. Never repeat it. Never use it to fill space.
        - A script that says "subscribe" more than once will be considered a failure.

        {"- STRICT MODE: If the opening is weak, rewrite aggressively for retention, even if style changes." if is_strict else ""}
        """

        prompt = f"""
        Role: Expert Scriptwriter for a YouTube channel about mysteries, conspiracies, and unexplained phenomena.
        Task: Write a captivating script about "{topic}" using this research as inspiration:
        {context}

        CRITICAL LANGUAGE REQUIREMENT:
        - Language: {lang_instr}
        - ALL narration text MUST be in {'English' if language == 'en' else 'Spanish'}
        - Do NOT mix languages. Use ONLY {'English' if language == 'en' else 'Spanish'} throughout the entire script.
        - The research context above may be in different languages, but YOUR SCRIPT must be entirely in {'English' if language == 'en' else 'Spanish'}.
        - This applies to ALL parts of the script: introduction, main content, and conclusion.

        NARRATIVE APPROACH:
        - Use the research above as a starting point, but tell the story in an engaging, mysterious tone.
        - Weave real facts with intriguing theories and unanswered questions.
        - Present witness accounts, leaked reports, and alternative theories as fascinating possibilities.
        - Do NOT debunk or be overly skeptical — explore the mystery with the audience.
        - Frame uncertain claims with phrases like "some believe", "witnesses report", "according to certain investigators".
        - Build suspense and curiosity throughout the narrative.
        - Maintain internal consistency (don't contradict dates or facts within the script).
        {quality_block}
        {long_block}

        Length: ~{words} words.
        Format: Just the narration text.
        IMPORTANT: At the very end of the script (and ONLY at the very end, never before), add ONE single call to subscribe to the channel "Stunning Revelations" in a natural and engaging way, in {'English' if language == 'en' else 'Spanish'}. Do NOT repeat this call anywhere else in the script.
        """

        script = self._generate(
            prompt,
            max_tokens=script_max_tokens,
            task_type="script_quality"
        )
        # El mÃ©todo _generate ya intenta Groq primero y Claude como fallback
        # Si ambos fallan, retornar error
        if script == "ERROR_QUOTA_EXCEEDED" or script == "ERROR_AUTH" or (script and script.startswith("ERROR")):
            return script

        if self._script_needs_refinement(script, words):
            print("   âš ï¸ Guion investigado con baja densidad detectado. Aplicando refinamiento...")
            refine_prompt = f"""
            Role: Senior Script Editor for a mystery/conspiracy YouTube channel.
            Task: Rewrite this script to be more engaging and suspenseful, using the research as inspiration.

            Language: {'English' if language == 'en' else 'Spanish'} only.
            Topic: "{topic}".
            Target length: ~{words} words.
            Research context:
            {context}

            {quality_block}

            Additional rewrite constraints:
            - Remove filler and generic repetition.
            - Weave research facts into an intriguing, mystery-driven narrative.
            - Present alternative theories as fascinating possibilities to explore.
            - Build suspense with dramatic transitions and curiosity hooks.
            - Return ONLY the final narration text.

            Script to rewrite:
            {script}
            """
            refined = self._generate(
                refine_prompt,
                max_tokens=script_max_tokens,
                task_type="script_quality"
            )
            if refined and not str(refined).startswith("ERROR") and len(refined.split()) >= int(words * 0.65):
                script = refined

        if script:
            script = self._deduplicate_cta(script)

        if script and "stunning revelations" not in script.lower() and "suscrÃ­bete" not in script.lower() and "subscribe" not in script.lower():
            if language == 'es':
                script += "\n\nNo olvides suscribirte a Stunning Revelations para mÃ¡s contenido fascinante."
            else:
                script += "\n\nDon't forget to subscribe to Stunning Revelations for more fascinating content."
        return script

    def generate_prompts_for_segment(self, segment_text, category, style, topic=None,
                                     full_script=None, research_context=None, narrative_context=None):
        """Genera prompts visuales para un segmento"""
        
        # Extraer contexto histÃ³rico completo del script y tema
        historical_analysis = self._extract_historical_context(topic, full_script, research_context)
        
        # Construir contexto global del video con anÃ¡lisis histÃ³rico
        global_context = ""
        if topic:
            global_context += f"\nGLOBAL VIDEO CONTEXT:\n"
            global_context += f"- Main Topic: {topic}\n"
            global_context += f"- Category: {category}\n"
            
            # Incluir anÃ¡lisis histÃ³rico completo
            if historical_analysis:
                global_context += f"\nHISTORICAL CONTEXT ANALYSIS:\n"
                if historical_analysis.get('time_period'):
                    global_context += f"- Time Period: {historical_analysis['time_period']}\n"
                if historical_analysis.get('location'):
                    global_context += f"- Location/Region: {historical_analysis['location']}\n"
                if historical_analysis.get('cultural_context'):
                    global_context += f"- Cultural Context: {historical_analysis['cultural_context']}\n"
                if historical_analysis.get('key_historical_elements'):
                    global_context += f"- Key Historical Elements: {', '.join(historical_analysis['key_historical_elements'][:5])}\n"
                if historical_analysis.get('technology_level'):
                    global_context += f"- Technology Level: {historical_analysis['technology_level']}\n"
                if historical_analysis.get('clothing_style'):
                    global_context += f"- Clothing/Style: {historical_analysis['clothing_style']}\n"
                if historical_analysis.get('architecture_style'):
                    global_context += f"- Architecture: {historical_analysis['architecture_style']}\n"
            
            # Incluir resumen del script completo (mÃ¡s largo para mejor contexto)
            if full_script:
                # Usar mÃ¡s del script para mejor contexto
                script_summary = full_script[:1500] if len(full_script) > 1500 else full_script
                global_context += f"\n- Full Script Context (first 1500 chars): {script_summary}...\n"
            
            if research_context:
                research_text = " ".join(research_context[:5]) if isinstance(research_context, list) else str(research_context)[:500]
                global_context += f"\n- Research Context: {research_text}...\n"
            
            global_context += "\nCRITICAL CONTEXTUAL REQUIREMENTS:\n"
            global_context += "- The visual prompt MUST maintain ABSOLUTE consistency with the global video topic, theme, and historical context\n"
            global_context += "- EVERY image must reflect the historical period, location, and cultural context identified above\n"
            global_context += "- If the video is about a historical period, ALL elements in EVERY image must reflect that period (clothing, architecture, technology, weapons, vehicles, atmosphere)\n"
            global_context += "- If a segment mentions 'people', 'individuals', 'soldiers', 'sailors', etc., they MUST be in the correct historical/cultural context from the main topic\n"
            global_context += "- If a segment is about subscription invitation or call-to-action, use imagery related to the video's main theme and historical period, NOT modern generic scenes\n"
            global_context += "- NEVER use modern elements (2020s technology, modern clothing, contemporary settings, modern ships, modern aircraft) unless the video topic is explicitly about modern times\n"
            global_context += "- Apply the historical period, location, and cultural context to EVERY segment, even if the segment text doesn't explicitly mention historical details\n"
            global_context += "- If the topic mentions a specific war, battle, or historical event, ALL images must reflect that specific period (e.g., WWII ships, not 18th century ships)\n"

        narrative_context_block = self._format_narrative_context(narrative_context)
        
        # Determinar si es contenido histÃ³rico (ahora mÃ¡s robusto)
        is_historical = historical_analysis is not None and historical_analysis.get('is_historical', False)
        
        historical_context = ""
        if is_historical:
            historical_context = f"""
CRITICAL HISTORICAL ACCURACY RULES (MUST BE APPLIED TO EVERY IMAGE):
- Time Period: {historical_analysis.get('time_period', 'Extract from topic/script')}
- Location: {historical_analysis.get('location', 'Extract from topic/script')}
- Technology Level: {historical_analysis.get('technology_level', 'Period-appropriate')}
- Clothing Style: {historical_analysis.get('clothing_style', 'Period-appropriate')}
- Architecture: {historical_analysis.get('architecture_style', 'Period-appropriate')}

MANDATORY RULES:
1. Verify dates, locations, and historical figures mentioned in the topic/script
2. Use correct historical terminology and period-appropriate descriptions
3. STRICTLY avoid anachronisms (modern elements in historical scenes)
4. Reference specific archaeological sites, monuments, or artifacts when mentioned
5. Use accurate historical context (e.g., "Bronze Age" not "Stone Age" if mentioned)
6. Include specific place names, time periods, and cultural details from the topic/script
7. Apply the historical period from the main topic to EVERY segment, even if the segment doesn't mention it
8. If topic mentions a specific war/event (e.g., "Trojan War", "WWII", "Ancient Egypt"), ALL images must reflect that specific period
9. Ships, vehicles, weapons, and technology must match the historical period (e.g., ancient Greek triremes for Trojan War, not 18th century ships)
10. People, clothing, and architecture must match the historical period and location
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
        
        prompt = f"""
Role: Expert AI Art Director and Historical Consultant.
Task: Create accurate visual/audio prompts from this narration text: "{segment_text}".
Context: Category: {category}, Style: {style}.
{global_context}
{historical_context}
{narrative_context_block}
{illustrative_context}

INSTRUCTIONS:
1. FIRST: Carefully read and understand the GLOBAL VIDEO CONTEXT and HISTORICAL CONTEXT ANALYSIS above
2. Identify the historical period, location, and cultural context from the analysis
3. THEN: Analyze the specific narration text for this segment: "{segment_text}"
4. Use the NARRATIVE CONTEXT WINDOW to understand what this segment is explaining, what came immediately before, and what comes immediately after
5. Choose the single most important visible moment implied by the CURRENT segment, not a generic summary of the whole video
6. Use previous/next context only to disambiguate characters, setting, chronology, and continuity; do NOT merge multiple separate events into one image unless the narration clearly describes them together
7. CRITICAL: The visual prompt MUST maintain ABSOLUTE consistency with the historical context identified above
8. If historical context is identified: ALL elements in the image MUST reflect that specific period:
   - Ships/vehicles must match the period (e.g., ancient Greek triremes for Trojan War, NOT 18th century ships)
   - Clothing must match the period (e.g., ancient Greek tunics, NOT modern clothing)
   - Architecture must match the period (e.g., ancient Greek temples, NOT modern buildings)
   - Technology must match the period (e.g., bronze weapons, NOT modern weapons)
   - Atmosphere and setting must match the period
9. If the segment mentions "people", "individuals", "soldiers", "sailors", "warriors", etc., they MUST be in the correct historical/cultural context from the main topic
10. If the segment is about subscription invitation or call-to-action, use imagery related to the video's main theme and historical period (e.g., if topic is Trojan War, show ancient Greek imagery, NOT modern tablets/TVs)
11. Create a detailed visual prompt in English that:
   - Matches the selected style ({style})
   - Maintains the global video context and historical period
   - Includes specific historical details from the context analysis (time period, location, cultural elements)
   - Accurately represents what is described in the CURRENT narration text
   - Describes only visible elements inside a single coherent still image
   - Prioritizes the main subject, action, place, and objects explicitly implied by the narration
   - If the narration is abstract or explanatory, convert it into a concrete, historically coherent visual moment
   - Does NOT mention sounds, smell, narration, aspect ratios, platform names, or video metadata
   - Does NOT mention cameras, camera crews, photographers, microphones, tripods, studio lights, or behind-the-scenes elements
   - Does NOT request subtitles, timestamps, UI, labels, logos, watermarks, or any written text inside the image
12. If historical content: Include specific time periods, locations, cultural elements, technology level, clothing style, and architecture style from the context analysis
13. If illustrative style: Apply the artistic style consistently throughout the visual description while maintaining historical accuracy
14. Avoid generic descriptions - be SPECIFIC about historical period, location, clothing, architecture, technology, and cultural elements
15. Ensure visual prompt matches the narration text exactly while respecting the chosen style AND the global video theme AND historical context
16. NEVER use anachronisms - if the topic is about ancient times, do NOT include modern elements or modern production equipment
17. For SFX: Identify appropriate sound effects matching the historical period (e.g., "ocean waves", "ancient battle sounds", "ancient music", "none")
18. For Overlays: Identify appropriate animated overlays matching the theme (e.g., "fire", "smoke", "sparks", "none")

QUALITY AND ERROR PREVENTION REQUIREMENTS:
- The visual prompt should explicitly avoid common AI generation errors
- Avoid descriptions that could lead to distortions, deformities, or anatomical errors
- Avoid descriptions that could generate text, watermarks, or unwanted artifacts
- Ensure descriptions are clear and specific to prevent hallucinations
- Focus on realistic, well-composed scenes with proper proportions
- Avoid ambiguous descriptions that could lead to multiple interpretations

Output ONLY valid JSON (no explanations, no markdown):
{{
    "visual_prompt": "detailed english visual prompt for one still image, matching the narration text '{segment_text}' exactly, respecting the selected style ({style}), and CRITICALLY maintaining consistency with the global video context and historical period identified above. Include specific historical details (time period, location, clothing, architecture, technology) even if the segment text doesn't explicitly mention them. Describe only visible elements in the scene. Do not mention audio, camera language, production equipment, aspect ratios, platform names, subtitles, timestamps, UI, labels, logos, watermarks, or any written text inside the image. Use clear, specific descriptions to avoid AI generation errors like distortions, deformities, text artifacts, or anatomical mistakes. Focus on well-composed, realistic scenes with proper proportions and accurate details.",
    "sfx_tag": "sound keyword in english matching the historical period or 'none'",
    "overlay_tag": "gif keyword in english matching the theme or 'none'"
}}

REMEMBER: 
1. Even if the segment text "{segment_text}" doesn't explicitly mention historical details, the visual prompt MUST still include the historical context from the main topic. For example, if the topic is "Trojan War" and the segment says "ships sailing", the prompt should specify "ancient Greek triremes" not just "ships".
2. Use specific, clear descriptions to prevent AI generation errors. Avoid vague terms that could lead to distortions or hallucinations.
3. The visual prompt must read like an art-direction brief for a single still image, never like behind-the-scenes footage or a video production setup.
4. The image must represent the CURRENT narration beat. Previous and next beats are only for continuity and disambiguation.
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
                result['visual_prompt'] = f"{visual_prompt}, {category} style, detailed, accurate"
            
            return result
        except Exception as e:
            print(f"âš ï¸ Error parseando JSON de Claude: {e}")
            print(f"   Respuesta recibida: {res[:200] if res else 'None'}...")
            return {
                "visual_prompt": f"detailed still image of {segment_text[:20]}, {category} style, accurate historical context",
                "sfx_tag": "none",
                "overlay_tag": "none"
            }

