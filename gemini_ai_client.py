# gemini_ai_client.py
# Wrapper de compatibilidad historica. La generacion de texto ahora usa solo Groq.

try:
    from claude_client import ClaudeAiClient
    CLAUDE_AVAILABLE = True
except ImportError:
    ClaudeAiClient = None
    CLAUDE_AVAILABLE = False
    print("WARNING claude_client.py no encontrado. La generacion de texto no funcionara.")


class GeminiAiClient:
    """
    Mantiene la interfaz usada por el proyecto, pero toda la generacion de texto
    se enruta unicamente a Groq.
    """

    def __init__(self):
        self.backend = ClaudeAiClient() if CLAUDE_AVAILABLE and ClaudeAiClient else None
        self.client_available = bool(self.backend and getattr(self.backend, "client_available", False))

        if self.backend and getattr(self.backend, "client", None):
            print("Groq inicializado como motor de texto (via GeminiAiClient)")
        else:
            print("WARNING Groq no esta disponible para el cliente de texto compatible")

    @property
    def client(self):
        return getattr(self.backend, "client", None)

    @property
    def groq_client(self):
        return getattr(self.backend, "groq_client", None)

    def _generate(self, prompt_text, max_tokens=4096, task_type="general"):
        """Forwardea a backend (Groq). El task_type controla qué cascada de modelos
        se usa: 'script_quality' prefiere gpt-oss-120b sobre llama-3.3-70b; 'general'
        usa la cascada por defecto. Backward-compat: si el caller no pasa task_type,
        sigue cayendo en 'general' como antes."""
        if self.backend:
            return self.backend._generate(
                prompt_text, max_tokens=max_tokens, task_type=task_type
            )
        return "ERROR: Groq no disponible"

    def generate_thumbnail_prompt(self, topic, category, style, provider='recraft'):
        if self.backend:
            return self.backend.generate_thumbnail_prompt(topic, category, style, provider)
        return "ERROR: Groq no disponible"

    def generate_video_script(self, topic, category, duration_seconds, language='es', narrative_profile=None,
                              opening_style="hook_overlay_v1"):
        if self.backend:
            return self.backend.generate_video_script(
                topic, category, duration_seconds, language, narrative_profile=narrative_profile,
                opening_style=opening_style,
            )
        return "ERROR: Groq no disponible"

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
        if self.backend:
            return self.backend.generate_video_script_with_research(
                topic,
                category,
                duration_seconds,
                research_snippets,
                language,
                narrative_profile=narrative_profile,
                opening_style=opening_style,
            )
        return "ERROR: Groq no disponible"

    def generate_prompts_for_segment(
        self,
        segment_text,
        category,
        style,
        topic=None,
        full_script=None,
        research_context=None,
        narrative_context=None,
        is_long_horizontal=False
    ):
        if self.backend:
            return self.backend.generate_prompts_for_segment(
                segment_text,
                category,
                style,
                topic,
                full_script,
                research_context,
                narrative_context,
                is_long_horizontal=is_long_horizontal,
            )
        return {
            "visual_prompt": "ERROR: Groq no disponible",
            "sfx_tag": "none",
            "overlay_tag": "none"
        }
