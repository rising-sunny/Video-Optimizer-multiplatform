# gemini_ai_client.py
# CLIENTE PRINCIPAL DE IA - AHORA USA GROQ COMO PROVEEDOR PRINCIPAL

import os

# Importar Claude (que ahora usa Groq como principal y Claude Code CLI como fallback)
try:
    from claude_client import ClaudeAiClient
    CLAUDE_AVAILABLE = True
except ImportError:
    ClaudeAiClient = None
    CLAUDE_AVAILABLE = False
    print("⚠️ claude_client.py no encontrado. IA no funcionará.")

# Mantener compatibilidad: GeminiAiClient ahora usa Groq como principal (vía ClaudeAiClient)
class GeminiAiClient:
    """
    Cliente principal de IA. 
    AHORA USA GROQ COMO PROVEEDOR PRINCIPAL (con Claude Code CLI como fallback).
    Mantiene la misma interfaz para compatibilidad con código existente.
    """
    def __init__(self):
        # Inicializar ClaudeAiClient (que internamente usa Groq como principal)
        self.claude_client = ClaudeAiClient() if CLAUDE_AVAILABLE and ClaudeAiClient else None
        
        if self.claude_client:
            if self.claude_client.groq_client and self.claude_client.groq_client.client:
                print("✅ Groq inicializado como IA principal (vía GeminiAiClient)")
            elif self.claude_client.claude_cmd:
                print("✅ Claude Code CLI inicializado como fallback (vía GeminiAiClient)")
            else:
                print("⚠️ ADVERTENCIA: Ni Groq ni Claude Code CLI están disponibles.")
                print("   Configura GROQ_API_KEY en .env para usar Groq como IA principal")
                print("   O asegúrate de tener Claude Code instalado y accesible desde PATH")

    def _generate(self, prompt_text, max_tokens=4096):
        """Genera texto usando Claude"""
        if self.claude_client:
            return self.claude_client._generate(prompt_text, max_tokens=max_tokens)
        else:
            return "ERROR: Claude Code CLI no está disponible. Instala Claude Code o configura CLAUDE_CLI_PATH"

    # Delegar todos los métodos a Claude
    def generate_thumbnail_prompt(self, topic, category, style, provider='recraft'):
        if self.claude_client:
            return self.claude_client.generate_thumbnail_prompt(topic, category, style, provider)
        return "ERROR: Claude no disponible"

    def generate_video_script(self, topic, category, duration_seconds, language='es', narrative_profile=None):
        if self.claude_client:
            return self.claude_client.generate_video_script(
                topic, category, duration_seconds, language, narrative_profile=narrative_profile
            )
        return "ERROR: Claude no disponible"

    def generate_video_script_with_research(
        self,
        topic,
        category,
        duration_seconds,
        research_snippets,
        language='es',
        narrative_profile=None
    ):
        if self.claude_client:
            return self.claude_client.generate_video_script_with_research(
                topic,
                category,
                duration_seconds,
                research_snippets,
                language,
                narrative_profile=narrative_profile
            )
        return "ERROR: Claude no disponible"

    def generate_prompts_for_segment(self, segment_text, category, style, topic=None, full_script=None,
                                     research_context=None, narrative_context=None):
        if self.claude_client:
            return self.claude_client.generate_prompts_for_segment(
                segment_text, category, style, topic, full_script, research_context, narrative_context
            )
        return {
            "visual_prompt": "ERROR: Claude no disponible",
            "sfx_tag": "none",
            "overlay_tag": "none"
        }
