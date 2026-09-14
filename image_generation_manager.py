# image_generation_manager.py
"""
Gestor de generación de imágenes para storyboards
Maneja la generación de imágenes usando Recraft AI / Google AI
y fuentes manuales (Openverse (Gratis), Wikimedia).
"""

import copy
import hashlib
import json
import os
import random
import re
import requests
import socket
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable


VALID_IMAGE_ASPECT_RATIOS = ("16:9", "9:16", "1:1")

_VERTICAL_PLATFORMS = {
    "youtube_short", "youtube_vertical", "tiktok", "reels", "instagram", "9:16",
}
_SQUARE_PLATFORMS = {"square", "x", "x_square", "1:1"}

_CONFLICTING_ASPECT_PATTERNS = {
    "16:9": (
        r",?\s*vertical\s+9:16\s+portrait\s+composition\s+(?:for\s+youtube\s+shorts\s+)?",
        r",?\s*vertical\s+9:16\b",
        r",?\s*vertical\s+portrait\s+composition(?:\s+optimized\s+for\s+mobile[^,]*)?",
        r",?\s*portrait\s+orientation",
        r",?\s*mobile[- ]safe\s+viewing",
        r",?\s*lower[- ]third\s+negative\s+space(?:\s+for\s+subtitles)?",
        r",?\s*subject\s+centered\s+in\s+the\s+middle\s+safe\s+area",
        r",?\s*no\s+important\s+details\s+at\s+the\s+edges",
        r"\bvertical\s+portrait\b",
        r"\b9:16\b",
        r",?\s*square\s+1:1\s+composition",
        r",?\s*square\s+composition",
        r"\b1:1\b",
    ),
    "9:16": (
        r",?\s*cinematic\s+16:9\s+horizontal\s+(?:framing|composition)"
        r"(?:\s*,\s*wide\s+establishing\s+(?:composition|framing))?",
        r",?\s*cinematic\s+16:9\b",
        r",?\s*horizontal\s+composition",
        r",?\s*landscape\s+framing",
        r"\b16:9\b",
        r",?\s*square\s+1:1\s+composition",
        r",?\s*square\s+composition",
        r"\b1:1\b",
    ),
    "1:1": (
        r",?\s*vertical\s+9:16\s+portrait\s+composition\s+(?:for\s+youtube\s+shorts\s+)?",
        r",?\s*vertical\s+9:16\b",
        r",?\s*vertical\s+portrait\s+composition(?:\s+optimized\s+for\s+mobile[^,]*)?",
        r"\bvertical\s+portrait\b",
        r"\b9:16\b",
        r",?\s*cinematic\s+16:9\s+horizontal\s+(?:framing|composition)"
        r"(?:\s*,\s*wide\s+establishing\s+(?:composition|framing))?",
        r",?\s*cinematic\s+16:9\b",
        r",?\s*horizontal\s+composition",
        r",?\s*landscape\s+framing",
        r"\b16:9\b",
    ),
}

_ASPECT_LEAD = {
    "16:9": "cinematic 16:9",
    "9:16": "vertical 9:16",
    "1:1": "square 1:1",
}

_ASPECT_EXTRA = {
    "16:9": (
        "horizontal composition",
        ("horizontal composition", "horizontal framing", "landscape framing"),
    ),
    "9:16": (
        "portrait composition optimized for mobile-safe viewing, "
        "subject centered in the middle safe area, "
        "leave clean lower-third negative space for subtitles, "
        "strong focal subject, no important details at the edges",
        (
            "vertical portrait composition",
            "portrait composition",
            "mobile-safe viewing",
            "lower-third negative space",
            "middle safe area",
        ),
    ),
    "1:1": (
        "centered framing, balanced negative space",
        ("square composition", "centered framing"),
    ),
}


def primary_aspect_ratio_from_format(video_format=None, platform=None) -> str:
    """Aspect ratio primario de imagen: '16:9', '9:16' o '1:1'.

    Valores duales/triples de la GUI (`16:9+1:1+9:16`) usan el primer
    componente, que coincide con el perfil de generación de assets.
    """
    fmt = str(video_format or "").strip()
    if fmt:
        first = fmt.split("+")[0].strip().lower()
        if "9:16" in first:
            return "9:16"
        if first.startswith("1:1") or first in {"square", "1:1"}:
            return "1:1"
        if "16:9" in first:
            return "16:9"
    plat = str(platform or "").strip().lower()
    if plat in _VERTICAL_PLATFORMS:
        return "9:16"
    if plat in _SQUARE_PLATFORMS:
        return "1:1"
    return "16:9"


def aspect_ratio_from_flags(is_vertical: bool = False, is_square: bool = False) -> str:
    if is_square:
        return "1:1"
    if is_vertical:
        return "9:16"
    return "16:9"


def apply_aspect_ratio_to_visual_prompt(visual_prompt, aspect_ratio="16:9") -> str:
    """Deja el ratio de imagen explícito en el visual prompt y quita el contrario.

    El token (`16:9` / `9:16` / `1:1`) va al inicio para que el modelo de imagen
    (y el texto copiado al portapapeles) no lo pierda al recortar el prompt.
    """
    prompt = str(visual_prompt or "").strip()
    if not prompt:
        return prompt

    ratio = str(aspect_ratio or "16:9").strip()
    if ratio not in VALID_IMAGE_ASPECT_RATIOS:
        ratio = primary_aspect_ratio_from_format(ratio)

    for pat in _CONFLICTING_ASPECT_PATTERNS.get(ratio, ()):
        prompt = re.sub(pat, "", prompt, flags=re.IGNORECASE)

    prompt = re.sub(r",\s*,+", ", ", prompt)
    prompt = re.sub(r"^\s*,\s*", "", prompt)
    prompt = re.sub(r"\s+,", ",", prompt)
    prompt = re.sub(r"\s{2,}", " ", prompt).strip(" ,")

    if ratio not in prompt:
        lead = _ASPECT_LEAD[ratio]
        prompt = f"{lead}, {prompt}" if prompt else lead

    extra, markers = _ASPECT_EXTRA[ratio]
    prompt_lower = prompt.lower()
    if extra and not any(marker in prompt_lower for marker in markers):
        prompt = f"{prompt}, {extra}" if prompt else extra

    prompt = re.sub(r",\s*,+", ", ", prompt)
    prompt = re.sub(r"\s{2,}", " ", prompt).strip(" ,")
    return prompt


class ImageGenerationManager:
    """
    Gestor de generación de imágenes para storyboards.
    Maneja la generación de imágenes usando Recraft o Google AI.
    """
    
    def __init__(self, log_callback=None, generated_media_dir=None,
                 recraft_client=None,
                 google_ai_image_client=None,
                 google_images_client=None, wikimedia_client=None,
                 prompt_processor=None,
                 fal_image_client=None,
                 stability_ultra_client=None,
                 stability_core_client=None,
                 comfyui_image_client=None):
        """
        Inicializa el gestor de generación de imágenes.

        Args:
            log_callback: Función para logging (opcional)
            generated_media_dir: Directorio para medios generados (opcional)
            recraft_client: Cliente real de Recraft (opcional)
            google_ai_image_client: Cliente Google AI (Gemini) para imagen generativa
            google_images_client: Cliente de Openverse (Gratis) (compat legacy)
            wikimedia_client: Cliente de Wikimedia (opcional)
            prompt_processor: Procesador de prompts (opcional)
            fal_image_client: Cliente FAL.AI (Flux dev/schnell) para imagen generativa
            stability_ultra_client: Cliente Stability AI Ultra (~$0.008/img)
            stability_core_client:  Cliente Stability AI Core  (~$0.003/img)
            comfyui_image_client: Cliente ComfyUI/Vast.ai opcional
        """
        self.log = log_callback or (lambda msg: print(msg))
        self.generated_media_dir = generated_media_dir
        self.recraft_client = recraft_client
        self.google_ai_image_client = google_ai_image_client
        self.google_images_client = google_images_client
        self.wikimedia_client = wikimedia_client
        self.prompt_processor = prompt_processor
        self.fal_image_client = fal_image_client
        self.stability_ultra_client = stability_ultra_client
        self.stability_core_client  = stability_core_client
        self.comfyui_image_client = comfyui_image_client
        # Contexto del guión actual — cargado una vez por storyboard
        self._storyboard_context: dict = {}
        # Cache de términos negativos específicos de la época, generados por IA
        self._era_negative_terms: list = []
        # Visual Bible (contexto global positivo)
        self._era_positive_context: str = ""


    def set_storyboard_context(self, storyboard_data: dict) -> None:
        """
        Carga el contexto del guión actual y genera (una vez) los términos negativos
        específicos de la época usando IA. Llamar antes de generar imágenes.
        """
        if not isinstance(storyboard_data, dict):
            return
        sb = storyboard_data.get('storyboard', {}) if isinstance(storyboard_data.get('storyboard'), dict) else {}
        title    = str(storyboard_data.get('title') or sb.get('title') or sb.get('topic') or '').strip()
        category = str(storyboard_data.get('category') or sb.get('category') or '').strip()
        script   = str(storyboard_data.get('script') or sb.get('script') or '').strip()

        new_ctx = {'title': title, 'category': category, 'script': script}
        if new_ctx == self._storyboard_context:
            return  # mismo contexto, no recalcular

        self._storyboard_context = new_ctx
        self._era_negative_terms = self._generate_era_negative_terms(title, category, script)
        self._era_positive_context = self._generate_era_positive_context(title, category, script)

    def _generate_era_negative_terms(self, title: str, category: str, script: str) -> list:
        """
        Usa Groq/Gemini para generar una lista de términos a excluir en los prompts
        de imágenes, específicos para el período histórico/temático del guión.
        Retorna una lista de strings vacía si no hay IA disponible.
        """
        ai_client = None
        if self.prompt_processor and getattr(self.prompt_processor, 'gemini_client', None):
            ai_client = self.prompt_processor.gemini_client
        if not ai_client or not getattr(ai_client, 'client_available', False):
            return []

        script_preview = script[:800] if script else ''
        prompt_text = (
            "You are a visual consistency expert for AI-generated images.\n"
            "Given the following documentary/history video script context, generate a compact list "
            "of visual elements that MUST be excluded from image prompts to avoid historical anachronisms "
            "or thematic inconsistencies.\n\n"
            f"Title: {title}\n"
            f"Category: {category}\n"
            f"Script excerpt: {script_preview}\n\n"
            "Rules:\n"
            "- Focus on anachronistic objects, architecture, clothing, technology, or cultural elements "
            "that don't belong to this specific historical period and region.\n"
            "- Be specific to THIS era and topic (not generic).\n"
            "- Output ONLY a comma-separated list of short negative prompt terms (no explanations, no bullets, no numbering).\n"
            "- Maximum 20 terms, each 1-4 words.\n"
            "- Example output: modern buildings, electric lights, cars, medieval armor, roman columns, "
            "gunpowder weapons, printed books\n\n"
            "Output:"
        )

        try:
            result = ai_client._generate(prompt_text, max_tokens=256)
            if not result or result.startswith("ERROR"):
                return []
            # Parsear la lista de términos
            terms = [t.strip().lower() for t in result.split(',') if t.strip()]
            terms = [t for t in terms if 2 <= len(t) <= 60]  # filtrar términos inválidos
            self.log(f"[ImageGen] Era negative terms generados ({len(terms)}): {', '.join(terms[:8])}...")
            return terms[:20]
        except Exception as e:
            self.log(f"[ImageGen] No se pudo generar era negative terms: {e}")
            return []

    def _generate_era_positive_context(self, title: str, category: str, script: str) -> str:
        """
        Usa Groq/Gemini para generar un contexto histórico y visual global ("Visual Bible")
        que se inyectará al inicio de todos los prompts visuales.
        """
        ai_client = None
        if self.prompt_processor and getattr(self.prompt_processor, 'gemini_client', None):
            ai_client = self.prompt_processor.gemini_client
        if not ai_client or not getattr(ai_client, 'client_available', False):
            return ""

        script_preview = script[:1000] if script else ''
        prompt_text = (
            "You are a visual consistency expert for AI-generated images.\n"
            "Given the following documentary/history video script context, generate a dense, strict "
            "global context prefix (max 250 characters) that establishes the historical era, location, "
            "and primary visual constraints (clothing, architecture, technology).\n\n"
            f"Title: {title}\n"
            f"Category: {category}\n"
            f"Script excerpt: {script_preview}\n\n"
            "Rules:\n"
            "- It MUST be a single, dense string that will be prepended to all image prompts.\n"
            "- Specify the EXACT era/year, geographical location, and visual style.\n"
            "- Include strict constraints (e.g. 'NO modern clothing', 'Paleolithic tribes in animal hides', 'Victorian London, 1888').\n"
            "- Do not explain or include bullet points. Return ONLY the prefix string.\n"
            "Output:"
        )

        try:
            result = ai_client._generate(prompt_text, max_tokens=150)
            if not result or result.startswith("ERROR"):
                return ""
            context = result.strip().replace('[', '').replace(']', '')
            if len(context) > 300:
                context = context[:300]
            self.log(f"[ImageGen] Visual Bible generado: [{context[:50]}...]")
            return context
        except Exception as e:
            self.log(f"[ImageGen] No se pudo generar Visual Bible: {e}")
            return ""

    @staticmethod
    def _normalize_provider_key(provider_key):
        provider = str(provider_key or "").strip().lower()
        return provider

    @staticmethod
    def _comfy_image_source(provider_key: str) -> str:
        provider = str(provider_key or "").strip().lower()
        if provider == "comfy_sdxl":
            return "comfy_sdxl"
        if provider in ("comfy_dev", "comfy_flux_dev"):
            return "comfy_flux_dev"
        return "comfy_flux_schnell"

    @staticmethod
    def _resolve_comfy_preset(provider_key: str, is_vertical: bool,
                              is_square: bool, style: Optional[str] = None) -> str:
        provider = str(provider_key or "").strip().lower()
        style_text = str(style or "").strip().lower()
        if provider == "comfy_sdxl" or "coloring" in style_text or "lineart" in style_text:
            return "coloring_sdxl_lineart"
        is_dev = provider in ("comfy_dev", "comfy_flux_dev")
        if is_vertical or is_square:
            return "historical_vertical_dev" if is_dev else "historical_vertical_schnell"
        return "thumbnail_16x9_dev" if is_dev else "thumbnail_16x9_schnell"

    def _iter_project_json_candidates(self):
        """Itera proyectos guardados en formatos legacy y v2."""
        projects_dir = Path("projects")
        if not projects_dir.exists():
            return

        seen = set()
        for pattern in ("*/project.json", "*.json"):
            for candidate in projects_dir.glob(pattern):
                if not candidate.is_file():
                    continue
                resolved = str(candidate.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield candidate

    def _project_media_dir_from_project_file(self, project_file: Path) -> Path:
        """Obtiene la carpeta de medios asociada al proyecto detectado."""
        if project_file.name.lower() == "project.json":
            return project_file.parent / "project_media"
        return project_file.parent / f"{project_file.stem}_media"

    def _resolve_project_media_dir(self, segments, project_path=None):
        """Resuelve la carpeta de medios del proyecto actual."""
        if project_path:
            try:
                project_candidate = Path(project_path)
                if not project_candidate.is_absolute():
                    project_candidate = (Path.cwd() / project_candidate).resolve()
                else:
                    project_candidate = project_candidate.resolve()

                if project_candidate.is_dir():
                    nested_project_json = project_candidate / "project.json"
                    if nested_project_json.exists():
                        project_candidate = nested_project_json
                    else:
                        media_dir = project_candidate / "project_media"
                        media_dir.mkdir(exist_ok=True, parents=True)
                        return media_dir

                if project_candidate.is_file():
                    media_dir = self._project_media_dir_from_project_file(project_candidate)
                    media_dir.mkdir(exist_ok=True, parents=True)
                    return media_dir
            except Exception:
                pass

        if segments:
            assigned_filename = str(segments[0].get("assigned_filename") or "").strip()
            if assigned_filename:
                for project_file in self._iter_project_json_candidates():
                    try:
                        with open(project_file, "r", encoding="utf-8") as f:
                            project_data = json.load(f)
                    except Exception:
                        continue

                    project_segments = project_data.get("storyboard", {}).get("segments", [])
                    if any(seg.get("assigned_filename", "") == assigned_filename for seg in project_segments):
                        media_dir = self._project_media_dir_from_project_file(project_file)
                        media_dir.mkdir(exist_ok=True, parents=True)
                        return media_dir

        return None

    def _resolve_storyboard_media_path(self, media_path, project_base_dir=None):
        """Resuelve rutas relativas guardadas dentro del storyboard."""
        if not media_path:
            return None

        try:
            candidate = Path(media_path)
        except Exception:
            return media_path

        if candidate.is_absolute():
            return str(candidate)

        if project_base_dir:
            candidate_paths = [project_base_dir / candidate]
            if len(candidate.parts) == 1:
                candidate_paths.extend([
                    project_base_dir / "project_media" / candidate.name,
                    project_base_dir / "images" / candidate.name,
                    project_base_dir / "videos" / candidate.name,
                ])

            for resolved_candidate in candidate_paths:
                if resolved_candidate.exists():
                    return str(resolved_candidate.resolve())

            return str(candidate_paths[0].resolve())

        return str(candidate.resolve())

    def _is_transient_network_error(self, message: str) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False
        markers = (
            "connection reset",
            "connection aborted",
            "connection refused",
            "connection timed out",
            "network is unreachable",
            "temporary failure in name resolution",
            "name or service not known",
            "max retries exceeded",
            "remote end closed connection",
            "no route to host",
            "dns",
            "socket",
            "timeout",
            "timed out",
            "connection error",
        )
        return any(marker in text for marker in markers)

    def _looks_like_quota_error(self, message: Optional[str]) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False
        markers = (
            "http 429",
            "quota",
            "resource exhausted",
            "too many requests",
            "rate limit",
            "exceeded",
        )
        return any(marker in text for marker in markers)

    def _has_internet_connection(self, timeout_seconds: float = 2.0) -> bool:
        probes = (("1.1.1.1", 53), ("8.8.8.8", 53))
        for host, port in probes:
            try:
                conn = socket.create_connection((host, port), timeout=timeout_seconds)
                conn.close()
                return True
            except OSError:
                continue
        return False

    def _wait_for_internet_recovery(self, timeout_seconds: int = 90, interval_seconds: int = 3) -> bool:
        deadline = time.time() + max(1, int(timeout_seconds))
        while time.time() < deadline:
            if self._has_internet_connection():
                return True
            time.sleep(max(1, int(interval_seconds)))
        return False

    def _run_network_resilient(self, action_name: str, callback, max_attempts: int = 4,
                               retry_on_empty: bool = False):
        attempts = max(1, int(max_attempts))
        for attempt in range(1, attempts + 1):
            try:
                value = callback()
            except Exception as e:
                transient = self._is_transient_network_error(str(e)) or not self._has_internet_connection()
                if transient and attempt < attempts:
                    self.log(
                        f"          Conexión inestable durante {action_name} "
                        f"(intento {attempt}/{attempts}). Esperando reconexión..."
                    )
                    if self._wait_for_internet_recovery():
                        self.log(f"          Internet restablecida. Reanudando {action_name}...")
                        continue
                raise

            if value:
                return value

            if retry_on_empty and attempt < attempts and not self._has_internet_connection():
                self.log(
                    f"          Sin internet durante {action_name} "
                    f"(intento {attempt}/{attempts}). Esperando reconexión..."
                )
                if self._wait_for_internet_recovery():
                    self.log(f"          Internet restablecida. Reanudando {action_name}...")
                    continue

            return value

        return None

    def _download_binary_with_resume(self, url: str, timeout: int = 30, headers: Optional[Dict[str, str]] = None):
        if not url:
            return None

        def _request():
            response = requests.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response.content

        try:
            return self._run_network_resilient(
                f"descarga de {os.path.basename(url) or 'imagen'}",
                _request,
                max_attempts=4,
                retry_on_empty=True
            )
        except Exception as e:
            self.log(f"         ️ Error descargando recurso: {e}")
            return None
    
    def _group_segments_for_images(self, segments, images_per_segment_ratio=1.0):
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            return self.prompt_processor.group_segments_for_images(segments, images_per_segment_ratio)
        # Fallback: implementación básica
        if images_per_segment_ratio <= 1.0:
            return [[seg] for seg in segments]
        groups = []
        current_group = []
        segments_per_image = int(images_per_segment_ratio)
        for i, seg in enumerate(segments):
            current_group.append(seg)
            if len(current_group) >= segments_per_image or i == len(segments) - 1:
                groups.append(current_group)
                current_group = []
        return groups

    def _segment_has_assigned_media(self, seg):
        """
        Retorna True si el segmento ya tiene contenido asignado (imagen o video)
        y no está marcado para regeneración.
        """
        if seg.get('image_deleted', False):
            return False
        return bool(seg.get('image_path') or seg.get('video_path'))

    def _chunk_segments(self, segments, chunk_size):
        """Divide una lista de segmentos en bloques consecutivos de tamaño fijo."""
        if chunk_size <= 1:
            return [[seg] for seg in segments]
        chunks = []
        for i in range(0, len(segments), chunk_size):
            chunks.append(segments[i:i + chunk_size])
        return chunks

    def _group_segments_respecting_content_boundaries(self, segments, images_per_segment_ratio=1.0):
        """
        Agrupa SOLO segmentos vacíos consecutivos.
        Los segmentos con contenido existente actúan como separadores y no se mezclan
        con vacíos para evitar desalinear los pares.
        """
        if images_per_segment_ratio <= 1.0:
            return [[seg] for seg in segments]

        segments_per_image = max(1, int(images_per_segment_ratio))
        groups = []
        pending_empty_run = []

        for seg in segments:
            if self._segment_has_assigned_media(seg):
                if pending_empty_run:
                    groups.extend(self._chunk_segments(pending_empty_run, segments_per_image))
                    pending_empty_run = []
                groups.append([seg])  # Mantener segmento ocupado intacto como separador
            else:
                pending_empty_run.append(seg)

        if pending_empty_run:
            groups.extend(self._chunk_segments(pending_empty_run, segments_per_image))

        return groups
    
    def _combine_prompts(self, segment_group):
        """Delega a PromptProcessor si está disponible e inyecta el Visual Bible (era_positive_context) si existe."""
        if self.prompt_processor:
            base_prompt = self.prompt_processor.combine_prompts(segment_group)
        else:
            # Fallback: combinar textos
            prompts = [seg.get('visual_prompt', '') for seg in segment_group]
            base_prompt = ', '.join(filter(None, prompts))
            
        if getattr(self, '_era_positive_context', None):
            if not base_prompt.startswith(f"[{self._era_positive_context}]"):
                base_prompt = f"[{self._era_positive_context}] " + base_prompt
                
        return base_prompt
    
    def _apply_style_to_prompt(self, visual_prompt, style, provider_key=None):
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            if hasattr(self.prompt_processor, 'adapt_prompt_for_provider'):
                return self.prompt_processor.adapt_prompt_for_provider(
                    visual_prompt,
                    style=style,
                    provider=self._normalize_provider_key(provider_key),
                )
            return self.prompt_processor.apply_style_to_prompt(visual_prompt, style)
        # Fallback: retornar prompt sin modificar
        if style and self._normalize_provider_key(provider_key) == 'google_ai':
            return f"{visual_prompt}, {style}, single coherent scene, clear focal subject"
        return visual_prompt

    def _resolve_generation_style(self, style, visual_prompt, provider_key=None):
        if self.prompt_processor and hasattr(self.prompt_processor, 'resolve_generation_style'):
            try:
                return self.prompt_processor.resolve_generation_style(
                    style,
                    visual_prompt,
                    provider=provider_key or "recraft",
                )
            except Exception:
                pass
        return style

    def _apply_aspect_guidance_to_prompt(self, visual_prompt, is_vertical: bool = False,
                                         is_square: bool = False) -> str:
        """Añade el ratio de imagen (16:9 / 9:16 / 1:1) y guía de composición."""
        return apply_aspect_ratio_to_visual_prompt(
            visual_prompt,
            aspect_ratio_from_flags(is_vertical=is_vertical, is_square=is_square),
        )

    def _build_prompt_variation_suffix(self, segment_number: int, duplicated: bool = False) -> str:
        base_modifiers = [
            "single coherent scene",
            "clear focal hierarchy",
            "distinct subject placement",
            "layered depth",
            "balanced spatial hierarchy",
            "clean negative space",
            "uncluttered background",
            "foreground emphasis",
            "wider environmental context",
            "crisp subject separation",
        ]
        duplicate_modifiers = [
            "alternative staging",
            "fresh spatial balance",
            "new visual arrangement",
            "different subject blocking",
            "reframed environment details",
            "alternate foreground emphasis",
        ]

        index = max(0, int(segment_number) - 1)
        active_modifiers = duplicate_modifiers if duplicated else base_modifiers
        parts = [
            base_modifiers[index % len(base_modifiers)],
            base_modifiers[(index * 3 + 2) % len(base_modifiers)],
            active_modifiers[(index * 5 + 1) % len(active_modifiers)],
        ]

        unique_parts = []
        for part in parts:
            if part not in unique_parts:
                unique_parts.append(part)
        return ", " + ", ".join(unique_parts)

    def _looks_historical_prompt(self, visual_prompt: str) -> bool:
        prompt_lower = str(visual_prompt or "").lower()
        historical_markers = (
            "ancient", "historical", "medieval", "roman", "greek", "egypt",
            "mesopotam", "sumer", "uruk", "pharaoh", "wwi", "wwii", "world war",
            "victorian", "byzant", "renaissance", "ottoman", "imperial",
            "antiquity", "bronze age", "iron age", "antique", "cold war",
            "declassified", "archive", "archival",
            # Civilizaciones y pueblos
            "hittite", "babylonian", "assyrian", "persian", "carthag", "viking",
            "celtic", "aztec", "mayan", "inca", "mongol", "spartan", "trojan",
            "phoenician", "sumerian", "minoan", "saxon", "crusade", "feudal",
            # Escenas de batalla/invasión antigua
            "chariot", "siege", "invader", "warship", "galley", "catapult",
            "horned helmet", "bronze sword", "iron sword", "shield wall",
            "sea peoples", "burning city", "city burning", "city on fire",
            "city siege", "ancient battle", "ancient war", "ancient soldier",
            # Arquitectura y artefactos
            "stone temple", "stone ruins", "clay tablet", "cuneiform",
            "citadel", "fortress", "acropolis", "ziggurat", "pyramid",
            "stone gate", "lion gate", "ancient palace", "ancient ruins",
            # Dioses y mitología antigua
            "storm god", "thunder god", "ancient god", "ancient deity",
            "mythology", "mythological", "ancient myth",
        )
        if any(marker in prompt_lower for marker in historical_markers):
            return True
        return bool(re.search(r"\b(?:1[0-9]{3}|20[01][0-9])\b", prompt_lower))

    @staticmethod
    def _prompt_contains_any(visual_prompt: str, markers) -> bool:
        prompt_lower = str(visual_prompt or "").lower()
        return any(marker in prompt_lower for marker in markers)

    def _looks_mystery_prompt(self, visual_prompt: str) -> bool:
        return self._prompt_contains_any(
            visual_prompt,
            (
                "mystery", "mysterious", "unsolved", "unexplained", "enigmatic",
                "disappearance", "vanished", "artifact", "legend", "secret",
                "anomaly", "forbidden", "hidden", "cryptid",
            ),
        )

    def _looks_ufo_prompt(self, visual_prompt: str) -> bool:
        return self._prompt_contains_any(
            visual_prompt,
            (
                "ufo", "ufos", "flying saucer", "orb", "extraterrestrial",
                "alien craft", "alien ship", "unidentified aerial", "roswell",
                "abduction", "close encounter",
            ),
        )

    def _looks_paranormal_prompt(self, visual_prompt: str) -> bool:
        return self._prompt_contains_any(
            visual_prompt,
            (
                "paranormal", "ghost", "haunted", "apparition", "specter",
                "demon", "occult", "ritual", "possession", "poltergeist",
                "shadow figure", "supernatural", "curse",
            ),
        )

    def _looks_conspiracy_prompt(self, visual_prompt: str) -> bool:
        return self._prompt_contains_any(
            visual_prompt,
            (
                "conspiracy", "cover-up", "cover up", "declassified", "classified",
                "secret file", "secret files", "government secret", "hidden agenda",
                "suppressed", "redacted", "intel file",
            ),
        )

    @staticmethod
    def _looks_illustrative_style(style: Optional[str]) -> bool:
        style_lower = str(style or "").strip().lower()
        markers = (
            "illustration", "vector", "icon", "logo", "comic", "watercolor",
            "line art", "engraving", "linocut", "kawaii", "anime", "sticker",
            "marker", "doodle", "drawing", "poster", "art nouveau",
        )
        return any(marker in style_lower for marker in markers)

    @staticmethod
    def _dedupe_comma_parts(parts) -> List[str]:
        unique_parts = []
        seen = set()
        for part in parts:
            clean = str(part or "").strip(" ,.")
            normalized = clean.lower()
            if clean and normalized not in seen:
                unique_parts.append(clean)
                seen.add(normalized)
        return unique_parts

    def _merge_prompt_fragments(self, prompt: str, extra_parts) -> str:
        prompt_parts = [chunk.strip() for chunk in str(prompt or "").split(",")]
        merged_parts = self._dedupe_comma_parts(list(prompt_parts) + list(extra_parts or []))
        return ", ".join(merged_parts)

    def _trim_prompt_for_provider(self, prompt: str, provider_key=None, max_chars: Optional[int] = None) -> str:
        normalized_provider = self._normalize_provider_key(provider_key)
        limit = max_chars or (760 if normalized_provider == "recraft" else 950)
        clean_prompt = str(prompt or "").strip()
        if len(clean_prompt) <= limit:
            return clean_prompt

        trimmed_parts = []
        current_length = 0
        for part in self._dedupe_comma_parts(clean_prompt.split(",")):
            addition = len(part) + (2 if trimmed_parts else 0)
            if current_length + addition > limit:
                break
            trimmed_parts.append(part)
            current_length += addition

        if trimmed_parts:
            return ", ".join(trimmed_parts).strip(" ,")

        fallback = clean_prompt[:limit].rsplit(" ", 1)[0].strip(" ,")
        return fallback or clean_prompt[:limit].strip(" ,")

    def _build_recraft_prompt_boosters(self, visual_prompt: str, style: Optional[str],
                                       is_vertical: bool, is_square: bool) -> List[str]:
        illustrative = self._looks_illustrative_style(style)
        boosters = [
            "single decisive still image",
            "clear focal subject",
            "foreground midground background depth",
            "believable material textures",
        ]

        if illustrative:
            boosters.extend([
                "editorial illustration quality",
                "grounded believable details",
                "readable silhouette",
            ])
        else:
            boosters.extend([
                "documentary realism",
                "cinematic but believable lighting",
            ])

        if self._looks_ufo_prompt(visual_prompt):
            boosters.extend([
                "believable scale",
                "subtle atmospheric haze",
                "uncanny but realistic aerial phenomenon",
            ])
        elif self._looks_paranormal_prompt(visual_prompt):
            boosters.extend([
                "grounded eerie atmosphere",
                "practical moody lighting",
                "real-world environmental detail",
                "subtle supernatural tension",
            ])
        elif self._looks_conspiracy_prompt(visual_prompt) or self._looks_mystery_prompt(visual_prompt):
            boosters.extend([
                "investigative documentary tone",
                "specific environment detail",
                "credible suspense",
                "grounded realism",
            ])

        if self._looks_historical_prompt(visual_prompt):
            boosters.extend([
                "period-accurate clothing and props",
                "authentic architecture",
                "archival credibility",
            ])

        if is_vertical:
            boosters.extend([
                "center-weighted composition",
                "keep lower-third area visually clean",
            ])
        elif is_square:
            boosters.append("balanced centered framing")

        return self._dedupe_comma_parts(boosters)

    # Directiva anti-texto canonica. Es la UNICA palanca efectiva contra texto en
    # FLUX, cuyo workflow usa CFG=1.0 y por tanto IGNORA el negative prompt por
    # completo. Va siempre al final del prompt POSITIVO.
    _NO_TEXT_DIRECTIVE = (
        "no text, no words, no letters, no writing, no captions, no watermark, no signage"
    )

    # Acciones/objetos que piden escritura legible -> se neutralizan para que el
    # modelo no dibuje glifos. Ej: "scribe inscribing a clay tablet" generaba texto.
    _TEXT_CREATION_REPLACEMENTS = [
        (r"(?i)\binscribing\b", "working over"),
        (r"(?i)\binscribes\b", "works over"),
        (r"(?i)\binscribed with [^,.;]+", "with weathered abstract carved markings"),
        (r"(?i)\bengraving (?:text|letters|words|runes)[^,.;]*", "engraving abstract patterns"),
        (r"(?i)\bwriting on\b", "marking"),
        (r"(?i)\bwritten (?:text|words|message|inscription)[^,.;]*", "faint indecipherable marks"),
        (r"(?i)\bcovered in (?:text|writing|inscriptions?)\b", "covered in weathered abstract markings"),
        (r"(?i)\b(?:readable|legible|visible) (?:text|inscriptions?|writing|words?)\b", "illegible weathered markings"),
        (r"(?i)\bfilled with (?:text|writing|inscriptions?)\b", "filled with abstract markings"),
    ]

    # Palabras-clave de TEXTO para detectar/eliminar clausulas anti-texto duplicadas.
    # Solo terminos de texto/marca: frases legitimas como 'no windows', 'no cropped
    # face' o 'no important details at the edges' NO matchean y se preservan.
    _ANTI_TEXT_KEYWORD = (
        r"(?:embedded\s+)?(?:text|words?|letters?|lettering|writing|writings?|"
        r"signs?|signage|signatures?|captions?|subtitles?|watermarks?|logos?|"
        r"numbers?|inscriptions?|typography)"
    )

    def _enforce_no_text_directive(self, prompt: str) -> str:
        """Garantiza UNA sola directiva anti-texto al final del prompt positivo.

        Elimina TODAS las clausulas anti-texto preexistentes EN CUALQUIER posicion
        (las anexa el LLM, y la guia de formato a veces inserta mas), y agrega una
        unica directiva canonica al final. Evita que el prompt lleve el anti-texto
        duplicado (la frase vieja del LLM + la canonica).

        Solo matchea palabras de texto/marca, asi que 'no windows' / 'no cropped
        face' se preservan. Idempotente.
        """
        if not prompt:
            return prompt
        kw = self._ANTI_TEXT_KEYWORD
        # Clausulas ', no <keyword>' (o ';') en cualquier parte del prompt.
        prompt = re.sub(rf"(?i)\s*[,;]\s*no\s+{kw}\b", "", prompt)
        # Clausula anti-texto al INICIO (sin coma previa).
        prompt = re.sub(rf"(?i)^\s*no\s+{kw}\b\s*,?", "", prompt)
        # Limpiar comas/espacios sobrantes que deja la eliminacion.
        prompt = re.sub(r"\s*,\s*,+", ", ", prompt)
        prompt = re.sub(r"\s{2,}", " ", prompt).strip().strip(",;").strip()
        if not prompt:
            return self._NO_TEXT_DIRECTIVE
        return f"{prompt}, {self._NO_TEXT_DIRECTIVE}"

    def _sanitize_visual_prompt(self, visual_prompt: str) -> str:
        """Elimina o reemplaza frases que inducen elementos anacrónicos, de rodaje
        o TEXTO LEGIBLE en la imagen generada.

        Nota FLUX: el workflow usa CFG=1.0, asi que el negative prompt se ignora.
        La supresion de texto DEBE hacerse en el prompt positivo (aqui).
        """
        prompt = str(visual_prompt or "")

        # Frases POV/cámara → reemplazar por equivalente cinematográfico sin implicar dispositivo
        pov_replacements = [
            (r"(?i)\bfirst[- ]person view of\b", "wide cinematic shot of"),
            (r"(?i)\bfirst[- ]person perspective\b", "cinematic perspective"),
            (r"(?i)\bpov shot of\b", "cinematic shot of"),
            (r"(?i)\bpoint of view of\b", "cinematic view of"),
            (r"(?i)\bthrough the lens of\b", "cinematic depiction of"),
            (r"(?i)\btime[- ]lapse of\b", "dramatic scene of"),  # time-lapse implica cámara
        ]
        for pattern, replacement in pov_replacements:
            prompt = re.sub(pattern, replacement, prompt)

        # Eliminar referencias explícitas a elementos modernos en contextos históricos/fantasy
        if self._looks_historical_prompt(prompt) or self._looks_mystery_prompt(prompt):
            modern_phrase_patterns = [
                r"(?i),?\s*modern city lights? appearing in the distance",
                r"(?i),?\s*modern city lights? visible",
                r"(?i),?\s*city lights? appearing",
                r"(?i),?\s*skyscrapers? in the background",
                r"(?i),?\s*contemporary (?:city|buildings?|architecture)",
            ]
            for pattern in modern_phrase_patterns:
                prompt = re.sub(pattern, "", prompt)

        # Neutralizar acciones/objetos que piden texto legible (critico en FLUX).
        for pattern, replacement in self._TEXT_CREATION_REPLACEMENTS:
            prompt = re.sub(pattern, replacement, prompt)

        prompt = prompt.strip().strip(",").strip()

        # Garantizar la directiva anti-texto canonica al final (determinista, no
        # depende de que el LLM la haya incluido).
        prompt = self._enforce_no_text_directive(prompt)
        return prompt

    def _enhance_generation_prompt(self, visual_prompt: str, style: Optional[str], provider_key=None,
                                   is_vertical: bool = False, is_square: bool = False) -> str:
        prompt = str(visual_prompt or "").strip()
        if not prompt:
            return prompt

        normalized_provider = self._normalize_provider_key(provider_key)
        if normalized_provider != "recraft":
            return prompt

        prompt = self._sanitize_visual_prompt(prompt)

        enhanced = self._merge_prompt_fragments(
            prompt,
            self._build_recraft_prompt_boosters(
                prompt,
                style=style,
                is_vertical=is_vertical,
                is_square=is_square,
            ),
        )
        return self._trim_prompt_for_provider(enhanced, provider_key=normalized_provider, max_chars=720)

    @staticmethod
    def _trim_negative_terms(negative: str, max_chars: int) -> str:
        """Recorta la lista de negativos por termino completo.

        El recorte por caracteres dejaba fragmentos como "modern" (de "modern
        clothing"), que ademas de no servir pueden confundir al modelo.
        """
        terminos = [t.strip() for t in (negative or "").split(",") if t.strip()]
        salida: list[str] = []
        largo = 0
        for t in terminos:
            extra = len(t) + (2 if salida else 0)
            if largo + extra > max_chars:
                break
            salida.append(t)
            largo += extra
        return ", ".join(salida)

    def _build_negative_prompt(self, visual_prompt: str) -> str:
        """Build the negative prompt with prioritized buckets.

        Order matters: trimmer cuts from the END, so the most critical / topic-specific
        exclusions go first. AI-artifact terms are critical but UNIVERSAL — keeping them
        in the middle ensures topic-specific exclusions survive the trim.

        Buckets (in priority order):
          1. Text/branding/UI — small, absolute (text never allowed)
          2. Tone-contextual — topic-specific, HIGHEST signal (anti-anachronism, anti-supernatural for documentary, anti-camp for mystery)
          3. AI-artifact universals — face/hand/anatomy issues common to all generators
          4. POV/camera-crew — only when relevant
          5. Era-specific terms (from LLM analysis)
          6. General quality / composition — lowest priority, trimmed first
        """
        # 1. Text / UI / branding — absolutamente critico, y AHORA SI pequeno.
        # Tenia 25 terminos y se comia el presupuesto entero: medido, sobrevivian
        # 25 de 63 negativos y los 19 primeros eran sinonimos de "sin texto",
        # mientras se perdian los anti-anacronismo y los anti-deformidad. Un
        # modelo de imagen no necesita 19 sinonimos para entender "sin texto".
        # Los anacronismos que estaban aca (skyscrapers, modern city, cars...)
        # se sacaron por duplicados: ya viven en el bucket historico.
        text_branding_terms = [
            "text", "captions", "watermark", "logo", "signature", "ui",
        ]

        # 1b. Anatomia esencial. Va ARRIBA a proposito: con el presupuesto real
        # (~290 chars) los buckets de mas abajo no llegaban nunca, y en escenas
        # con personas las manos deformes son el fallo mas visible de la IA.
        anatomy_essentials = ["extra fingers", "deformed hands", "bad anatomy"]

        # 3. Tone-contextual exclusions
        contextual_terms: list[str] = []
        is_ufo = self._looks_ufo_prompt(visual_prompt)
        is_paranormal = self._looks_paranormal_prompt(visual_prompt)
        is_conspiracy = self._looks_conspiracy_prompt(visual_prompt)
        is_mystery = self._looks_mystery_prompt(visual_prompt)
        is_historical = self._looks_historical_prompt(visual_prompt)

        if is_ufo:
            contextual_terms.extend([
                "cartoon alien", "toy spaceship", "space opera", "laser battle",
                "kawaii alien", "rubber alien suit",
            ])
        elif is_paranormal:
            contextual_terms.extend([
                "campy horror", "cheap halloween makeup", "theme park monster",
                "rubber mask", "video game monster",
            ])
        elif is_conspiracy or is_mystery:
            contextual_terms.extend([
                "clickbait thumbnail", "red arrow", "circle highlight",
                "tabloid montage", "youtube thumbnail style",
            ])

        if is_historical:
            # Anti-anachronism (always for historical content)
            # Compactado: "modern clothing/vehicles/buildings/weapons/street" +
            # "contemporary architecture" eran seis maneras de decir lo mismo y
            # consumian el presupuesto que necesitaban anatomia y anti-fantasia.
            contextual_terms.extend([
                "modern clothing", "modern vehicles", "anachronism",
                "contemporary architecture", "power lines", "asphalt",
            ])
            # Anti-supernatural ONLY when historical AND not explicitly a mystery/paranormal prompt.
            # This is the key fix for documentary content (e.g. Punic Wars) that should NOT
            # render glowing artifacts, ghostly figures, or magical auras.
            if not (is_ufo or is_paranormal or is_conspiracy or is_mystery):
                contextual_terms.extend([
                    # No supernatural elements
                    # Compactado de 20 a 6: la lista larga no llegaba a la API.
                    "supernatural glow", "ghostly figure", "glowing eyes",
                    "fantasy creature", "anime style", "video game art",
                ])

        # 4. POV / camera-crew exclusions (when prompt mentions cameras/POV)
        pov_markers = (
            "first-person", "first person", "pov", "point of view", "photographer",
            "camera", "filming", "recording", "screenshot", "video game",
        )
        if self._prompt_contains_any(visual_prompt, pov_markers):
            contextual_terms.extend([
                "camera lens", "photographer in frame", "film crew", "dslr visible",
                "viewfinder", "selfie stick", "tripod visible", "camera strap",
            ])

        # 5. AI-artifact universals (slim set — most impactful only).
        ai_artifact_terms = [
            # Hands (worst offenders)
            "extra fingers", "fused fingers", "deformed hands", "extra arms",
            # Face / eyes (uncanny valley)
            "asymmetric face", "crossed eyes", "doll face", "wax figure",
            "uncanny valley", "plastic skin", "melted face",
            # Composition errors
            "duplicate face", "two heads", "bad anatomy",
            "twisted neck", "incorrect proportions",
        ]

        # 6. Era-specific terms generated by LLM for the current script
        era_terms = list(self._era_negative_terms) if self._era_negative_terms else []

        # 7. General quality / composition (lowest priority — trimmed first if budget tight)
        quality_terms = [
            "cropped face", "out of frame", "blurry", "low resolution",
            "jpeg artifacts", "pixelated", "oversaturated", "washed out",
            "camera crew", "tripod", "microphone", "behind the scenes",
        ]

        compact_negative = ", ".join(
            self._dedupe_comma_parts(
                text_branding_terms       # 1. critical, small
                + anatomy_essentials      # 1b. siempre presente
                + contextual_terms        # 2. topic-specific, highest signal
                + ai_artifact_terms       # 3. universal anatomy/face fixes
                + era_terms               # 4. LLM-derived per-script
                + quality_terms           # 5. general quality (first to be trimmed)
            )
        )
        # OJO CON ESTE NUMERO. El negative prompt NO tiene 1000 caracteres propios:
        # Recraft no expone un parametro negativo, asi que el cliente lo PEGA al
        # final del prompt ("Avoid: ...") dentro del mismo techo de ~1000. El
        # prompt visual se lleva ~700, asi que aca entran ~290. El tope anterior
        # de 900 partia de suponer un presupuesto propio que no existe, y el
        # resultado era que el 60% de los negativos se descartaba en silencio.
        return self._trim_negative_terms(compact_negative, max_chars=300)
    
    def regenerate_visual_prompts_with_style(self, storyboard_data, style):
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            return self.prompt_processor.regenerate_visual_prompts_with_style(storyboard_data, style)
        # Fallback: retornar storyboard sin modificar
        return storyboard_data

    def _build_generation_visual_prompt(self, segment_group, style, provider_key,
                                        is_vertical, is_square,
                                        segment_number_in_storyboard,
                                        used_prompts, add_variation=True):
        """Replica la preparación del prompt final usada por la generación real."""
        visual_prompt = self._combine_prompts(segment_group)

        if style and visual_prompt:
            visual_prompt = self._apply_style_to_prompt(
                visual_prompt,
                style,
                provider_key=provider_key,
            )

        visual_prompt = self._apply_aspect_guidance_to_prompt(
            visual_prompt,
            is_vertical=is_vertical,
            is_square=is_square,
        )
        visual_prompt = self._enhance_generation_prompt(
            visual_prompt,
            style=style,
            provider_key=provider_key,
            is_vertical=is_vertical,
            is_square=is_square,
        )
        visual_prompt = self._sanitize_visual_prompt(visual_prompt)
        visual_prompt = self._trim_prompt_for_provider(visual_prompt, provider_key=provider_key)

        if not visual_prompt or not add_variation:
            return visual_prompt

        prompt_hash = hashlib.md5(visual_prompt.encode('utf-8')).hexdigest()[:8]
        if prompt_hash in used_prompts:
            variation_suffix = self._build_prompt_variation_suffix(
                segment_number_in_storyboard,
                duplicated=True,
            )
        else:
            variation_suffix = self._build_prompt_variation_suffix(
                segment_number_in_storyboard,
                duplicated=False,
            )

        if variation_suffix not in visual_prompt:
            visual_prompt = f"{visual_prompt}{variation_suffix}"

        visual_prompt = self._trim_prompt_for_provider(visual_prompt, provider_key=provider_key)

        final_prompt_hash = hashlib.md5(visual_prompt.encode('utf-8')).hexdigest()[:8]
        used_prompts[final_prompt_hash] = (segment_number_in_storyboard, visual_prompt)
        return visual_prompt

    def _resolve_existing_segment_content(self, seg, project_base_dir=None):
        """Resuelve si el segmento ya tiene imagen o video utilizable."""
        image_source = seg.get('image_source', 'unknown')

        existing_image_path = seg.get('image_path')
        if existing_image_path and not seg.get('image_deleted', False):
            resolved_image_path = existing_image_path
            if not os.path.isabs(existing_image_path):
                if project_base_dir:
                    resolved_image_path = self._resolve_storyboard_media_path(
                        existing_image_path,
                        project_base_dir=project_base_dir,
                    )
                else:
                    resolved_image_path = str(Path(existing_image_path).resolve())

            if os.path.exists(resolved_image_path):
                return {
                    'has_content': True,
                    'content_type': 'image',
                    'content_path': resolved_image_path,
                    'image_source': image_source,
                }

        existing_video_path = seg.get('video_path')
        if existing_video_path:
            resolved_video_path = existing_video_path
            if not os.path.isabs(existing_video_path):
                if project_base_dir:
                    resolved_video_path = self._resolve_storyboard_media_path(
                        existing_video_path,
                        project_base_dir=project_base_dir,
                    )
                else:
                    resolved_video_path = str(Path(existing_video_path).resolve())

            if os.path.exists(resolved_video_path):
                return {
                    'has_content': True,
                    'content_type': 'video',
                    'content_path': resolved_video_path,
                    'image_source': image_source,
                }

        return {
            'has_content': False,
            'content_type': None,
            'content_path': None,
            'image_source': image_source,
        }

    def _build_recraft_prompt_jobs(self, storyboard_data, platform,
                                   images_per_segment_ratio=1.0,
                                   interleave_images=False, style='Photorealism',
                                   regenerate_prompts=False, project_path=None):
        """Construye el lote de prompts que realmente terminaría usando Recraft."""
        storyboard_copy = copy.deepcopy(storyboard_data or {})
        if regenerate_prompts and style:
            storyboard_copy = self.regenerate_visual_prompts_with_style(storyboard_copy, style)

        segments = storyboard_copy.get('segments', [])
        is_vertical = platform in ['tiktok', 'reels', 'youtube_short', 'youtube_vertical']
        is_square = platform in ['square', 'x_square', 'x']
        total_segments = len(segments)
        selected_provider_key = 'recraft'
        segment_number_map = {id(seg): idx + 1 for idx, seg in enumerate(segments)}
        used_prompts = {}
        jobs = []
        skipped_segments = []

        project_media_dir = self._resolve_project_media_dir(segments, project_path=project_path)
        if not project_media_dir:
            current_dir = Path.cwd()
            possible_project_media = current_dir / "project_media"
            project_media_dir = possible_project_media if possible_project_media.exists() else self.generated_media_dir
        project_base_dir = Path(project_media_dir).parent if project_media_dir else None

        if interleave_images:
            for idx in range(len(segments)):
                if idx % 2 == 1:
                    segments[idx]['image_path'] = None
                    if 'image_source' in segments[idx]:
                        del segments[idx]['image_source']
            segments_to_process = [seg for idx, seg in enumerate(segments) if idx % 2 == 0]
        else:
            segments_to_process = segments
            if is_vertical and images_per_segment_ratio <= 1.0:
                skipped_segments.extend(
                    segment_number_map.get(id(seg), 0)
                    for seg in segments_to_process
                    if self._segment_has_assigned_media(seg) and segment_number_map.get(id(seg), 0)
                )
                segments_to_process = [
                    seg for seg in segments_to_process if not self._segment_has_assigned_media(seg)
                ]

        if images_per_segment_ratio > 1.0:
            segment_groups = self._group_segments_respecting_content_boundaries(
                segments_to_process,
                images_per_segment_ratio,
            )
        else:
            segment_groups = self._group_segments_for_images(
                segments_to_process,
                images_per_segment_ratio,
            )

        manual_sources = {
            'wikimedia', 'bing_images', 'google_images', 'pexels_video',
            'wikimedia_video', 'internet_archive', 'youtube'
        }
        ai_sources = {
            'recraft_ai', 'google_ai', 'fal_flux',
            'stability_core', 'stability_ultra',
            'comfy_flux_schnell', 'comfy_flux_dev', 'comfy_sdxl',
            'existing'
        }

        for group_idx, original_group in enumerate(segment_groups, start=1):
            if not original_group:
                continue

            first_seg = original_group[0]

            if first_seg.get('cover_frame', False):
                self.log(f"   [{group_idx}/{total_groups}] Skipping cover_frame segment (handled by cover_frame_generator)")
                continue

            fname = first_seg.get('assigned_filename', f'segment_{group_idx:03d}')
            segment_number_in_storyboard = segment_number_map.get(id(first_seg), group_idx)

            visual_prompt = self._build_generation_visual_prompt(
                original_group,
                style,
                selected_provider_key,
                is_vertical,
                is_square,
                segment_number_in_storyboard,
                used_prompts,
                add_variation=True,
            )

            segments_with_content = []
            segments_to_generate = []
            for seg in original_group:
                content_state = self._resolve_existing_segment_content(
                    seg,
                    project_base_dir=project_base_dir,
                )
                has_content = content_state.get('has_content', False)
                content_type = content_state.get('content_type')
                image_source = content_state.get('image_source', 'unknown')

                if has_content and content_type == 'image' and image_source in (manual_sources | ai_sources):
                    segments_with_content.append((seg, content_state))
                    continue
                if has_content and content_type == 'video':
                    segments_with_content.append((seg, content_state))
                    continue

                segments_to_generate.append(seg)

            if len(segments_with_content) == len(original_group):
                skipped_segments.extend(
                    segment_number_map.get(id(seg), 0)
                    for seg, _ in segments_with_content
                    if segment_number_map.get(id(seg), 0)
                )
                continue

            segment_group = list(original_group)
            if segments_with_content and segments_to_generate:
                segment_group = segments_to_generate
                first_seg = segment_group[0]
                fname = first_seg.get('assigned_filename', f'segment_{group_idx:03d}')
                visual_prompt = self._build_generation_visual_prompt(
                    segment_group,
                    style,
                    selected_provider_key,
                    is_vertical,
                    is_square,
                    segment_number_in_storyboard,
                    used_prompts,
                    add_variation=False,
                )

            group_image_path = None
            all_have_same_image = True
            needs_regeneration = False

            for seg in segment_group:
                if seg.get('image_deleted', False):
                    needs_regeneration = True
                    break

                existing_image_path = seg.get('image_path')
                image_source = seg.get('image_source', 'unknown')
                if existing_image_path:
                    resolved_image_path = existing_image_path
                    if not os.path.isabs(existing_image_path):
                        if project_base_dir:
                            resolved_image_path = self._resolve_storyboard_media_path(
                                existing_image_path,
                                project_base_dir=project_base_dir,
                            )
                        else:
                            resolved_image_path = str(Path(existing_image_path).resolve())

                    if os.path.exists(resolved_image_path):
                        if image_source not in manual_sources:
                            if group_image_path is None:
                                group_image_path = resolved_image_path
                            elif group_image_path != resolved_image_path:
                                all_have_same_image = False
                                break
                        else:
                            needs_regeneration = True
                            break
                    else:
                        needs_regeneration = True
                        break
                else:
                    needs_regeneration = True
                    break

            should_reuse_existing = (
                not needs_regeneration and
                all_have_same_image and
                group_image_path and
                images_per_segment_ratio > 1.0
            )
            if should_reuse_existing:
                skipped_segments.extend(
                    segment_number_map.get(id(seg), 0)
                    for seg in segment_group
                    if segment_number_map.get(id(seg), 0)
                )
                continue

            if is_square:
                width, height = (1080, 1080)
            elif is_vertical:
                width, height = (1080, 1920)
            else:
                width, height = (1920, 1080)

            segment_numbers = [
                segment_number_map.get(id(seg), idx + 1)
                for idx, seg in enumerate(segment_group)
            ]
            negative_prompt = self._build_negative_prompt(visual_prompt)
            recraft_style = self._resolve_generation_style(style, visual_prompt, 'recraft')

            jobs.append({
                'job_number': len(jobs) + 1,
                'group_index': group_idx,
                'filename_base': fname,
                'segment_numbers': segment_numbers,
                'assigned_filenames': [
                    seg.get('assigned_filename', f'segment_{num:03d}')
                    for seg, num in zip(segment_group, segment_numbers)
                ],
                'prompt': visual_prompt,
                'negative_prompt': negative_prompt,
                'recraft_style': recraft_style or (style or 'Photorealism'),
                'width': width,
                'height': height,
            })

        return {
            'storyboard': storyboard_copy,
            'platform': platform,
            'style': style or 'Photorealism',
            'total_segments': total_segments,
            'jobs': jobs,
            'interleave_images': bool(interleave_images),
            'images_per_segment_ratio': images_per_segment_ratio,
            'project_path': project_path,
            'skipped_segments': sorted(set(skipped_segments)),
        }

    def build_recraft_prompt_export(self, storyboard_data, platform,
                                    images_per_segment_ratio=1.0,
                                    interleave_images=False, style='Photorealism',
                                    regenerate_prompts=False, project_path=None):
        """Genera el contenido TXT con prompts manuales equivalentes a Recraft."""
        export_data = self._build_recraft_prompt_jobs(
            storyboard_data=storyboard_data,
            platform=platform,
            images_per_segment_ratio=images_per_segment_ratio,
            interleave_images=interleave_images,
            style=style,
            regenerate_prompts=regenerate_prompts,
            project_path=project_path,
        )

        storyboard = export_data.get('storyboard', {}) or {}
        topic = storyboard.get('topic', 'Sin tema')
        category = storyboard.get('category', 'general')
        project_label = project_path or 'Sin proyecto activo'
        jobs = export_data.get('jobs', [])
        skipped_segments = export_data.get('skipped_segments', [])

        lines = [
            "=" * 80,
            "  Video Optimizer Pro - Prompts manuales para Recraft",
            "=" * 80,
            "",
            f"Fecha de exportación: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Proyecto: {project_label}",
            f"Tema: {topic}",
            f"Categoría: {category}",
            f"Plataforma objetivo: {platform}",
            f"Estilo visual Recraft: {export_data.get('style')}",
            f"Regenerar prompts con estilo: {'Sí' if regenerate_prompts else 'No'}",
            f"Ratio imágenes/segmento: {export_data.get('images_per_segment_ratio')}",
            f"Intercalado: {'Sí' if export_data.get('interleave_images') else 'No'}",
            f"Segmentos totales del storyboard: {export_data.get('total_segments')}",
            f"Imágenes a solicitar manualmente: {len(jobs)}",
            f"Segmentos omitidos por media ya existente: {len(skipped_segments)}",
        ]

        if skipped_segments:
            lines.append(
                "Segmentos omitidos: " + ", ".join(str(num) for num in skipped_segments)
            )

        if not jobs:
            lines.extend([
                "",
                "No hay prompts nuevos para exportar.",
                "Todos los segmentos ya tienen media asignada o reutilizable según la lógica actual del pipeline.",
            ])
        else:
            for job in jobs:
                segment_text = ", ".join(str(num) for num in job.get('segment_numbers', []))
                filename_text = ", ".join(job.get('assigned_filenames', []))
                prompt_text = job.get('prompt') or "[PROMPT VACÍO]"
                negative_prompt = job.get('negative_prompt') or "[Sin negative prompt]"

                lines.extend([
                    "",
                    "-" * 80,
                    f"IMAGEN {job.get('job_number'):02d}",
                    f"Segmentos: {segment_text}",
                    f"Assigned filename(s): {filename_text}",
                    f"Archivo sugerido base: {job.get('filename_base')}",
                    f"Resolución sugerida: {job.get('width')}x{job.get('height')}",
                    f"Estilo Recraft API: {job.get('recraft_style')}",
                    "",
                    "PROMPT:",
                    prompt_text,
                    "",
                    "NEGATIVE PROMPT (opcional):",
                    negative_prompt,
                ])

        export_data['text'] = "\n".join(lines).strip() + "\n"
        return export_data

    def export_recraft_prompts_to_txt(self, storyboard_data, platform, output_path,
                                      images_per_segment_ratio=1.0,
                                      interleave_images=False, style='Photorealism',
                                      regenerate_prompts=False, project_path=None):
        """Exporta a TXT los prompts que usaría la generación de Recraft."""
        export_data = self.build_recraft_prompt_export(
            storyboard_data=storyboard_data,
            platform=platform,
            images_per_segment_ratio=images_per_segment_ratio,
            interleave_images=interleave_images,
            style=style,
            regenerate_prompts=regenerate_prompts,
            project_path=project_path,
        )

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(export_data['text'], encoding='utf-8')

        export_data['output_path'] = str(output_file.resolve())
        return export_data

    def build_recraft_prompt_plan(self, storyboard_data, platform,
                                  images_per_segment_ratio=1.0,
                                  interleave_images=False, style='Photorealism',
                                  regenerate_prompts=False, provider_key='recraft'):
        """Construye el plan de prompts para todos los segmentos elegibles.

        `provider_key` controla qué provider se asume al armar el prompt:
        - 'recraft' (default): inyecta boosters específicos de Recraft.
        - 'comfy_schnell' / 'comfy_dev' / 'flux_*' / 'google_ai' / etc.: NO inyecta
          los boosters de Recraft. El prompt resultante refleja lo que realmente
          se envía al modelo (los boosters se gatean en _enhance_generation_prompt).
        El nombre `build_recraft_prompt_plan` se conserva por compatibilidad con
        call sites externos (ej. el export TXT manual sigue usando 'recraft').
        """
        storyboard_copy = copy.deepcopy(storyboard_data or {})
        if regenerate_prompts and style:
            storyboard_copy = self.regenerate_visual_prompts_with_style(storyboard_copy, style)

        segments = storyboard_copy.get('segments', [])
        is_vertical = platform in ['tiktok', 'reels', 'youtube_short', 'youtube_vertical']
        is_square = platform in ['square', 'x_square', 'x']
        segment_number_map = {id(seg): idx + 1 for idx, seg in enumerate(segments)}
        used_prompts = {}

        if interleave_images:
            segments_to_process = [seg for idx, seg in enumerate(segments) if idx % 2 == 0]
        else:
            segments_to_process = list(segments)

        if images_per_segment_ratio > 1.0:
            segment_groups = self._group_segments_for_images(
                segments_to_process,
                images_per_segment_ratio,
            )
        else:
            segment_groups = [[seg] for seg in segments_to_process]

        jobs = []
        segment_lookup = {}
        for group_idx, segment_group in enumerate(segment_groups, start=1):
            if not segment_group:
                continue

            first_seg = segment_group[0]

            fname = first_seg.get('assigned_filename', f'segment_{group_idx:03d}')
            segment_number_in_storyboard = segment_number_map.get(id(first_seg), group_idx)

            # Cover frames usan un prompt base ("Cinematic dark vertical cover frame
            # for: <topic>") que cover_frame_generator enriquece en tiempo de
            # generación con la guía de composición (vertical portrait, mobile-safe,
            # lower-third clean, etc.). Para que el prompt COPIADO coincida con lo
            # que se manda al modelo, replicamos aquí ese enriquecimiento aplicando
            # _apply_aspect_guidance_to_prompt.
            #
            # Antes salteábamos cover_frames entero con `continue`, lo que hacía
            # que el botón "Copiar Prompts" mostrara "Sin prompts Recraft disponible".
            if first_seg.get('cover_frame', False):
                visual_prompt = str(first_seg.get('visual_prompt') or '').strip()
                if not visual_prompt:
                    continue
                # Enriquecer con la guía de composición para que el prompt copiado
                # sea fiel al enviado a FLUX/Recraft/etc.
                visual_prompt = self._apply_aspect_guidance_to_prompt(
                    visual_prompt,
                    is_vertical=is_vertical,
                    is_square=is_square,
                )
            else:
                visual_prompt = self._build_generation_visual_prompt(
                    segment_group,
                    style,
                    provider_key,
                    is_vertical,
                    is_square,
                    segment_number_in_storyboard,
                    used_prompts,
                    add_variation=True,
                )

            if is_square:
                width, height = (1080, 1080)
            elif is_vertical:
                width, height = (1080, 1920)
            else:
                width, height = (1920, 1080)

            segment_numbers = [
                segment_number_map.get(id(seg), idx + 1)
                for idx, seg in enumerate(segment_group)
            ]
            job = {
                'job_number': len(jobs) + 1,
                'group_index': group_idx,
                'filename_base': fname,
                'segment_numbers': segment_numbers,
                'assigned_filenames': [
                    seg.get('assigned_filename', f'segment_{num:03d}')
                    for seg, num in zip(segment_group, segment_numbers)
                ],
                'prompt': visual_prompt,
                'negative_prompt': self._build_negative_prompt(visual_prompt),
                # Resolución de estilo usa el provider real (antes hardcodeaba 'recraft',
                # lo que aplicaba normalización de estilos Recraft a prompts FLUX/ComfyUI).
                'recraft_style': self._resolve_generation_style(style, visual_prompt, provider_key) or (style or 'Photorealism'),
                'provider_key': provider_key,
                'width': width,
                'height': height,
            }
            jobs.append(job)
            for segment_number in segment_numbers:
                segment_lookup[segment_number] = job

        return {
            'storyboard': storyboard_copy,
            'platform': platform,
            'style': style or 'Photorealism',
            'jobs': jobs,
            'segment_lookup': segment_lookup,
            'interleave_images': bool(interleave_images),
            'images_per_segment_ratio': images_per_segment_ratio,
            'disabled_segment_numbers': [
                idx + 1 for idx in range(len(segments))
                if idx + 1 not in segment_lookup
            ],
        }

    def get_recraft_prompt_for_segment(self, storyboard_data, platform, segment_index,
                                       images_per_segment_ratio=1.0,
                                       interleave_images=False, style='Photorealism',
                                       regenerate_prompts=False, provider_key='recraft'):
        """Retorna el prompt/negative prompt correspondiente a un segmento.

        El argumento `provider_key` permite construir el prompt para el provider
        REAL que se usa al generar (p.ej. 'comfy_schnell', 'comfy_dev', 'flux_dev',
        'google_ai', etc.). El default 'recraft' se mantiene por compatibilidad
        con call sites antiguos. Cuando el provider no es 'recraft', los boosters
        específicos de Recraft (documentary realism, believable material textures,
        single decisive still image, etc.) no se inyectan, y el prompt copiado
        refleja lo que realmente se manda al modelo.
        """
        try:
            normalized_index = int(segment_index)
        except Exception:
            normalized_index = -1

        segment_number = normalized_index + 1
        if segment_number <= 0:
            return None

        plan = self.build_recraft_prompt_plan(
            storyboard_data=storyboard_data,
            platform=platform,
            images_per_segment_ratio=images_per_segment_ratio,
            interleave_images=interleave_images,
            style=style,
            regenerate_prompts=regenerate_prompts,
            provider_key=provider_key,
        )
        return plan.get('segment_lookup', {}).get(segment_number)

    def generate_all_images_for_storyboard(self, storyboard_data, platform,
                                           use_wikimedia=False, disable_wikimedia=False,
                                           use_real_images=True, use_google_images=True,
                                           enable_real_images_mix=False, test_mode=False,
                                           image_provider='auto', images_per_segment_ratio=1.0,
                                           interleave_images=False, style='Realistic image',
                                           regenerate_prompts=False, project_path=None,
                                           video_provider='none', fal_video_model=None,
                                           **_unused):
        """
        Genera todas las imágenes para cada segmento del storyboard ANTES de ensamblar.
        Retorna el storyboard actualizado con las rutas de imágenes en cada segmento.
        
        Args:
            storyboard_data: Datos del storyboard con segmentos
            platform: Plataforma de destino (youtube, tiktok, etc.)
            images_per_segment_ratio: Ratio de imágenes por segmento
                - 1.0 = 1 imagen por segmento (comportamiento actual)
                - 2.0 = 1 imagen cada 2 segmentos (50% menos imágenes)
                - 3.0 = 1 imagen cada 3 segmentos (67% menos imágenes)
                - 4.0 = 1 imagen cada 4 segmentos (75% menos imágenes)
            style: Estilo visual a aplicar
            regenerate_prompts: Si True, regenera los visual_prompts con el nuevo estilo antes de generar imágenes
        """
        # Regenerar prompts visuales con el nuevo estilo si se solicita
        if regenerate_prompts and style:
            storyboard_data = self.regenerate_visual_prompts_with_style(storyboard_data, style)

        # Guardar config de video para el pipeline I2V posterior.
        # Los consumidores posteriores (ensamblado/video_generation_manager) pueden
        # leer estos atributos o el bloque 'video_pipeline' del storyboard.
        try:
            self.last_video_provider = (video_provider or 'none')
            self.last_fal_video_model = fal_video_model
        except Exception:
            pass
        if isinstance(storyboard_data, dict):
            storyboard_data.setdefault('video_pipeline', {})
            storyboard_data['video_pipeline'].update({
                'video_provider': (video_provider or 'none'),
                'fal_video_model': fal_video_model,
            })

        self.log(f"\n️ GENERANDO TODAS LAS IMÁGENES...")
        self.log(f"    Parámetros: use_google_images={use_google_images}, use_real_images={use_real_images}, enable_real_images_mix={enable_real_images_mix}")
        if (video_provider or 'none') != 'none':
            model_str = f" ({fal_video_model})" if fal_video_model else ""
            self.log(f"    Video pipeline (posterior): {video_provider}{model_str}")
        
        segments = storyboard_data.get('segments', [])
        is_vertical = platform in ['tiktok', 'reels', 'youtube_short', 'youtube_vertical']
        is_square = platform in ['square', 'x_square', 'x']
        total_segments = len(segments)
        selected_provider_key = self._normalize_provider_key(image_provider or 'auto')
        project_media_dir = self._resolve_project_media_dir(segments, project_path=project_path)
        
        # DETERMINAR DIRECTORIO DE DESTINO POR PROYECTO
        # Buscar el primer segmento para determinar el proyecto
        if not project_media_dir and segments and len(segments) > 0:
            first_seg = segments[0]
            assigned_filename = first_seg.get('assigned_filename', '')
            if assigned_filename:
                # Extraer nombre del proyecto del assigned_filename
                # Formato: segment_001 -> proyecto = nombre_base
                # Buscar si hay un archivo .json del proyecto en projects/
                import json
                from pathlib import Path
                
                # Intentar determinar el proyecto desde el assigned_filename
                project_json_files = list(self._iter_project_json_candidates())
                
                for json_file in project_json_files:
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            project_data = json.load(f)
                            project_segments = project_data.get('storyboard', {}).get('segments', [])
                            
                            # Buscar segmento con el mismo assigned_filename
                            for seg in project_segments:
                                if seg.get('assigned_filename', '') == assigned_filename:
                                    # Encontramos el proyecto, usar su carpeta de medios correcta
                                    project_media_dir = self._project_media_dir_from_project_file(json_file)
                                    project_media_dir.mkdir(exist_ok=True, parents=True)
                                    break
                    except:
                        continue
        if project_media_dir:
            self.log(f"    Usando directorio del proyecto: {project_media_dir}")
        # Si no se encuentra proyecto específico, intentar usar project_media del directorio actual
        if not project_media_dir:
            # Intentar encontrar project_media en el directorio actual o en projects/
            from pathlib import Path
            current_dir = Path.cwd()
            possible_project_media = current_dir / "project_media"
            if possible_project_media.exists():
                project_media_dir = possible_project_media
                self.log(f"    Usando project_media del directorio actual: {project_media_dir}")
            else:
                # Fallback: usar directorio global
                project_media_dir = self.generated_media_dir
                self.log(f"   ️ No se encontró directorio del proyecto, usando global: {project_media_dir}")
        
        # Usar el directorio determinado
        media_dir = project_media_dir
        project_base_dir = media_dir.parent if media_dir else None
        
        # Si está activado el modo intercalado, solo generar imágenes para índices pares (0, 2, 4...)
        if interleave_images:
            self.log(f"    Modo intercalado: Generando imágenes solo para segmentos impares (1, 3, 5...)")
            self.log(f"    Segmentos pares (2, 4, 6...) quedarán vacíos para agregar manualmente")
            # Limpiar imágenes de segmentos pares (índices impares en 0-based: 1, 3, 5...)
            for idx in range(len(segments)):
                if idx % 2 == 1:  # Índices impares (segmentos pares: 2, 4, 6...)
                    segments[idx]['image_path'] = None
                    if 'image_source' in segments[idx]:
                        del segments[idx]['image_source']
            # Filtrar segmentos para solo procesar los impares (índice par en 0-based: 0, 2, 4...)
            segments_to_process = [seg for idx, seg in enumerate(segments) if idx % 2 == 0]
            skipped_count = total_segments - len(segments_to_process)
            self.log(f"    {skipped_count} segmentos quedaron vacíos para edición manual")
        else:
            segments_to_process = segments
            skipped_count = 0

            # En formato vertical 9:16, generar IA solo para segmentos vacios.
            if is_vertical and images_per_segment_ratio <= 1.0:
                occupied_segments = [seg for seg in segments_to_process if self._segment_has_assigned_media(seg)]
                if occupied_segments:
                    segments_to_process = [seg for seg in segments_to_process if not self._segment_has_assigned_media(seg)]
                    skipped_count = len(occupied_segments)
                    self.log(f"   Formato vertical 9:16: generando IA solo para {len(segments_to_process)} segmento(s) vacios")
                    self.log(f"   Saltando {skipped_count} segmento(s) con imagen/video existente")
        
        # Agrupar segmentos según el ratio (solo los que se van a procesar)
        # IMPORTANTE: con ratio > 1, agrupar únicamente vacíos consecutivos.
        # Los segmentos con contenido existente (manual/IA/video) no se tocan y actúan como separadores.
        if images_per_segment_ratio > 1.0:
            segment_groups = self._group_segments_respecting_content_boundaries(
                segments_to_process, images_per_segment_ratio
            )
        else:
            segment_groups = self._group_segments_for_images(segments_to_process, images_per_segment_ratio)
        total_groups = len(segment_groups)
        
        if images_per_segment_ratio > 1.0:
            empty_segments = sum(
                1 for seg in segments_to_process if not self._segment_has_assigned_media(seg)
            )
            target_groups = sum(
                1 for group in segment_groups
                if any(not self._segment_has_assigned_media(seg) for seg in group)
            )
            self.log(
                f"   Agrupacion activada: {empty_segments} segmentos vacios consecutivos -> ~{target_groups} imagenes IA")
            if empty_segments > 0:
                savings = int((1 - target_groups / empty_segments) * 100)
                self.log(f"   Ahorro estimado en vacios: ~{savings}% menos imagenes")
        elif not interleave_images:
            if is_vertical and images_per_segment_ratio <= 1.0:
                self.log(f"   Generando {len(segments_to_process)} imagenes IA para segmentos vacios")
                if not segments_to_process:
                    self.log("   No hay segmentos vacios: se conservaran las imagenes/videos ya asignados")
            else:
                self.log(f"   Generando {total_segments} imagenes (1 por segmento)")
        
        # Calcular cuántos grupos usarán imágenes reales (50%)
        num_real_images = total_groups // 2
        real_group_indices = set()
        
        # Seleccionar índices aleatorios para imágenes reales
        if enable_real_images_mix and total_groups > 1:
            real_group_indices = set(random.sample(range(total_groups), num_real_images))
            self.log(f"    Distribución: {num_real_images} imágenes reales, {total_groups - num_real_images} imágenes IA")
        
        # Contadores para estadísticas
        generated_count = 0
        failed_count = 0
        success_count = 0
        reused_count = 0
        google_quota_exhausted = False
        
        # Track de prompts usados para detectar duplicados
        used_prompts = {}  # {prompt_hash: (segment_index, prompt_text)}
        
        # Iterar sobre grupos de segmentos concurrentemente
        import concurrent.futures
        
        def _process_group(args):
            nonlocal generated_count, failed_count, success_count, reused_count, google_quota_exhausted
            group_idx, segment_group = args
            # Obtener el primer segmento del grupo para el nombre de archivo
            first_seg = segment_group[0]
            # Si images_per_segment_ratio es 1.0, usar el nombre único de cada segmento
            # Si es > 1.0, usar el nombre del primer segmento del grupo
            if images_per_segment_ratio <= 1.0 and len(segment_group) == 1:
                fname = first_seg.get('assigned_filename', f'segment_{group_idx+1:03d}')
            else:
                fname = first_seg.get('assigned_filename', f'segment_{group_idx+1:03d}')
            
            # Obtener el índice real del segmento en el storyboard completo (no en el grupo)
            # Esto es importante para agregar variación única a cada prompt
            segment_index_in_storyboard = None
            for idx, seg in enumerate(segments):
                if seg == first_seg:
                    segment_index_in_storyboard = idx
                    break
            if segment_index_in_storyboard is None:
                segment_index_in_storyboard = group_idx
            
            # Combinar prompts del grupo
            visual_prompt = self._combine_prompts(segment_group)
            
            # Aplicar estilo al prompt visual si está disponible
            if style and visual_prompt:
                original_prompt = visual_prompt
                visual_prompt = self._apply_style_to_prompt(
                    visual_prompt,
                    style,
                    provider_key=selected_provider_key,
                )
                # Log detallado para depuración
                if original_prompt != visual_prompt:
                    self.log(f"       Estilo '{style}' aplicado al prompt")
                    # Log del prompt original (primeros 150 caracteres)
                    self.log(f"       Prompt original: {original_prompt[:150]}...")
                    # Log del prompt final (primeros 150 caracteres)
                    self.log(f"       Prompt con estilo: {visual_prompt[:150]}...")

            aspect_adjusted_prompt = self._apply_aspect_guidance_to_prompt(
                visual_prompt,
                is_vertical=is_vertical,
                is_square=is_square,
            )
            if aspect_adjusted_prompt != visual_prompt:
                self.log("       Prompt ajustado al encuadre del formato final")
                visual_prompt = aspect_adjusted_prompt
            visual_prompt = self._sanitize_visual_prompt(visual_prompt)
            
            # IMPORTANTE: Agregar variación única al prompt para evitar duplicados
            # Esto asegura que cada segmento tenga un prompt ligeramente diferente
            # incluso si el contenido es similar, evitando que la IA genere imágenes idénticas
            segment_number = segment_index_in_storyboard + 1
            
            # Crear hash del prompt original para detectar duplicados
            import hashlib
            prompt_hash = hashlib.md5(visual_prompt.encode()).hexdigest()[:8]
            
            # Verificar si este prompt ya fue usado (especialmente en segmentos consecutivos)
            if prompt_hash in used_prompts:
                prev_segment, prev_prompt = used_prompts[prompt_hash]
                self.log(f"      ️ ADVERTENCIA: Prompt duplicado detectado!")
                self.log(f"         Segmento {prev_segment} y segmento {segment_number} tienen prompts muy similares")
                self.log(f"         Prompt anterior: {prev_prompt[:150]}...")
                self.log(f"         Prompt actual: {visual_prompt[:150]}...")
                self.log(f"         Agregando variación adicional para evitar imagen duplicada...")
                
                # Agregar variación más fuerte si el prompt es muy similar
                # Usar variaciones más específicas para segmentos consecutivos
                variation_suffix = self._build_prompt_variation_suffix(segment_number, duplicated=True)
            else:
                # Siempre agregar variación única incluso para prompts nuevos
                # Esto garantiza que cada segmento tenga una imagen única
                variation_suffix = self._build_prompt_variation_suffix(segment_number, duplicated=False)
            
            # Asegurarse de que la variación se agregue siempre
            if variation_suffix not in visual_prompt:
                visual_prompt = f"{visual_prompt}{variation_suffix}"
            
            # Guardar prompt usado con el hash actualizado después de agregar variación
            final_prompt_hash = hashlib.md5(visual_prompt.encode()).hexdigest()[:8]
            used_prompts[final_prompt_hash] = (segment_number, visual_prompt)
            
            # Log del prompt final con variación
            self.log(f"       Prompt final para segmento {segment_number}: {visual_prompt[:200]}...")
            
            media_path = None
            
            # IMPORTANTE: Verificar si algún segmento del grupo ya tiene imagen o video asignado
            # Solo generar imágenes para segmentos SIN imagen (vacíos)
            segments_with_content = []
            segments_to_generate = []
            
            for seg in segment_group:
                existing_image_path = seg.get('image_path')
                existing_video_path = seg.get('video_path')
                image_source = seg.get('image_source', 'unknown')
                
                # Verificar si el segmento tiene contenido asignado (manual o IA)
                has_content = False
                content_path = None
                content_type = None
                
                # Verificar si tiene imagen válida (manual o IA)
                if existing_image_path and not seg.get('image_deleted', False):
                    # Resolver ruta si es relativa
                    resolved_path = existing_image_path
                    if not os.path.isabs(existing_image_path) and project_base_dir:
                        resolved_path = self._resolve_storyboard_media_path(
                            existing_image_path,
                            project_base_dir=project_base_dir,
                        )
                    elif not os.path.isabs(existing_image_path):
                        from pathlib import Path
                        # Intentar resolver desde el directorio del proyecto
                        if 'project_media' in existing_image_path or existing_image_path.startswith('project_media'):
                            # Es una ruta relativa del proyecto
                            try:
                                # Buscar en projects/ para encontrar el proyecto
                                projects_dir = Path("projects")
                                for json_file in projects_dir.glob("*.json"):
                                    project_dir = json_file.parent
                                    possible_path = project_dir / existing_image_path
                                    if possible_path.exists():
                                        resolved_path = str(possible_path.resolve())
                                        break
                            except:
                                pass
                        else:
                            # Intentar resolver como ruta relativa desde el directorio actual
                            resolved_path = str(Path(existing_image_path).resolve())
                    
                    if os.path.exists(resolved_path):
                        has_content = True
                        content_path = resolved_path
                        content_type = 'image'
                        # Verificar si es de fuente manual (debe conservarse)
                        if image_source in ['wikimedia', 'bing_images', 'google_images', 'pexels_video', 'wikimedia_video', 'internet_archive', 'youtube']:
                            segments_with_content.append((seg, content_path, content_type, image_source))
                            self.log(f"      ️ Segmento {segments.index(seg) + 1} tiene imagen manual ({image_source}) - Saltando")
                            continue  # Saltar este segmento, tiene contenido manual
                        # Si es IA generada y existe, también conservarla (no regenerar)
                        elif image_source in ['recraft_ai', 'google_ai', 'fal_flux', 'stability_core', 'stability_ultra', 'comfy_flux_schnell', 'comfy_flux_dev', 'comfy_sdxl']:
                            segments_with_content.append((seg, content_path, content_type, image_source))
                            self.log(f"      ️ Segmento {segments.index(seg) + 1} ya tiene imagen IA ({image_source}) - Saltando")
                            continue  # Saltar este segmento, ya tiene imagen IA
                
                # Verificar si tiene video válido
                if existing_video_path:
                    resolved_video_path = existing_video_path
                    if not os.path.isabs(existing_video_path) and project_base_dir:
                        resolved_video_path = self._resolve_storyboard_media_path(
                            existing_video_path,
                            project_base_dir=project_base_dir,
                        )
                    elif not os.path.isabs(existing_video_path):
                        from pathlib import Path
                        resolved_video_path = str(Path(existing_video_path).resolve())
                    
                    if os.path.exists(resolved_video_path):
                        has_content = True
                        content_path = resolved_video_path
                        content_type = 'video'
                        # Si tiene video_path, probablemente es manual
                        if image_source in ['pexels_video', 'wikimedia_video', 'internet_archive', 'youtube'] or existing_video_path:
                            segments_with_content.append((seg, content_path, content_type, image_source))
                            self.log(f"      ️ Segmento {segments.index(seg) + 1} tiene video ({image_source}) - Saltando")
                            continue  # Saltar este segmento, tiene video manual
                
                # Si no tiene contenido, agregarlo a la lista para generar
                segments_to_generate.append(seg)
            
            # Si todos los segmentos del grupo tienen contenido manual, saltar todo el grupo
            if len(segments_with_content) == len(segment_group):
                group_size = len(segment_group)
                start_seg = sum(len(segment_groups[i]) for i in range(group_idx)) + 1
                end_seg = start_seg + group_size - 1
                seg_numbers = f"{start_seg}-{end_seg}" if group_size > 1 else str(start_seg)
                self.log(f"\n    Grupo {group_idx+1}/{total_groups} (Segmentos {seg_numbers}): {fname}")
                
                content_sources = [src for _, _, _, src in segments_with_content]
                unique_sources = list(set(content_sources))
                source_names = {
                    'wikimedia': 'Wikimedia',
                    'bing_images': 'Openverse (Gratis)',
                    'google_images': 'Openverse (Gratis) (legacy)',
                    'pexels_video': 'Pexels Video',
                    'recraft_ai': 'Recraft AI',
                    'google_ai': 'Google AI (Gemini)',
                    'comfy_flux_schnell': 'ComfyUI FLUX Schnell',
                    'comfy_flux_dev': 'ComfyUI FLUX Dev',
                    'comfy_sdxl': 'ComfyUI SDXL',
                }
                sources_str = ', '.join([source_names.get(s, s) for s in unique_sources])
                self.log(f"       Todos los segmentos tienen contenido existente ({sources_str}) - Saltando generación")
                reused_count += group_size
                return
            
            # Si algunos segmentos tienen contenido y otros no, generar solo para los que faltan
            if segments_with_content and segments_to_generate:
                group_size = len(segment_group)
                start_seg = sum(len(segment_groups[i]) for i in range(group_idx)) + 1
                end_seg = start_seg + group_size - 1
                seg_numbers = f"{start_seg}-{end_seg}" if group_size > 1 else str(start_seg)
                self.log(f"\n    Grupo {group_idx+1}/{total_groups} (Segmentos {seg_numbers}): {fname}")
                self.log(f"      ️ {len(segments_with_content)} segmento(s) tienen contenido existente - Generando para {len(segments_to_generate)} restante(s)")
                # Actualizar el grupo para procesar solo los que faltan
                segment_group = segments_to_generate
                # Actualizar first_seg y fname para el grupo reducido
                if segment_group:
                    first_seg = segment_group[0]
                    fname = first_seg.get('assigned_filename', f'segment_{group_idx+1:03d}')
                    visual_prompt = self._combine_prompts(segment_group)
                    # IMPORTANTE: Aplicar estilo después de recombinar prompts
                    if style and visual_prompt:
                        original_prompt = visual_prompt
                        visual_prompt = self._apply_style_to_prompt(
                            visual_prompt,
                            style,
                            provider_key=selected_provider_key,
                        )
                        # Log detallado para depuración
                        if original_prompt != visual_prompt:
                            self.log(f"       Estilo '{style}' aplicado al prompt (grupo actualizado)")
                            # Log del prompt original (primeros 150 caracteres)
                            self.log(f"       Prompt original (grupo): {original_prompt[:150]}...")
                            # Log del prompt final (primeros 150 caracteres)
                            self.log(f"       Prompt con estilo (grupo): {visual_prompt[:150]}...")

                    aspect_adjusted_prompt = self._apply_aspect_guidance_to_prompt(
                        visual_prompt,
                        is_vertical=is_vertical,
                        is_square=is_square,
                    )
                    if aspect_adjusted_prompt != visual_prompt:
                        self.log("       Prompt ajustado al encuadre del formato final")
                        visual_prompt = aspect_adjusted_prompt
                    visual_prompt = self._sanitize_visual_prompt(visual_prompt)
            
            # Si no hay segmentos para generar (todos tienen contenido manual), ya se saltó arriba
            # Continuar con la verificación de reutilización para los segmentos restantes
            
            group_image_path = None
            group_image_source = None
            all_have_same_image = True
            needs_regeneration = False
            
            for seg in segment_group:
                existing_image_path = seg.get('image_path')
                image_source = seg.get('image_source', 'unknown')
                
                # Si algún segmento está eliminado, necesitamos regenerar
                if seg.get('image_deleted', False):
                    needs_regeneration = True
                    break
                
                # Verificar si tiene imagen válida (pero no manual)
                # IMPORTANTE: Si image_path fue eliminado del segmento (None), NO reutilizar archivos existentes
                # Esto permite regenerar imágenes con diferentes estilos
                if existing_image_path:
                    if os.path.isabs(existing_image_path) or os.path.dirname(existing_image_path):
                        if os.path.exists(existing_image_path):
                            # Solo reutilizar si no es de fuente manual
                            if image_source not in ['wikimedia', 'bing_images', 'google_images', 'pexels_video', 'wikimedia_video', 'internet_archive', 'youtube']:
                                if group_image_path is None:
                                    group_image_path = existing_image_path
                                    group_image_source = image_source
                                elif group_image_path != existing_image_path:
                                    all_have_same_image = False
                                    break
                            else:
                                # Es manual, ya debería estar en segments_with_content
                                needs_regeneration = True
                                break
                        else:
                            # El archivo no existe físicamente, necesitamos regenerar
                            needs_regeneration = True
                            break
                    else:
                        needs_regeneration = True
                        break
                else:
                    # No hay image_path en el segmento, necesitamos generar nueva imagen
                    needs_regeneration = True
                    break
            
            # Si todos tienen la misma imagen válida (no manual), reutilizarla para todo el grupo
            # IMPORTANTE: Solo reutilizar si images_per_segment_ratio > 1.0 (agrupación activa)
            # Si es 1.0, cada segmento debe tener su propia imagen única, incluso si son similares
            should_reuse_existing = (not needs_regeneration and all_have_same_image and group_image_path and 
                                     images_per_segment_ratio > 1.0)
            
            if should_reuse_existing:
                media_path = group_image_path
                group_size = len(segment_group)
                start_seg = sum(len(segment_groups[i]) for i in range(group_idx)) + 1
                end_seg = start_seg + group_size - 1
                seg_numbers = f"{start_seg}-{end_seg}" if group_size > 1 else str(start_seg)
                self.log(f"\n    Grupo {group_idx+1}/{total_groups} (Segmentos {seg_numbers}): {fname}")
                
                if group_image_source in ['recraft_ai', 'recraft_compat_leonardo']:
                    source_name = "Recraft AI (reutilizada)"
                elif group_image_source == 'google_ai':
                    source_name = "Google AI (reutilizada)"
                elif group_image_source == 'comfy_flux_schnell':
                    source_name = "ComfyUI FLUX Schnell (reutilizada)"
                elif group_image_source == 'comfy_flux_dev':
                    source_name = "ComfyUI FLUX Dev (reutilizada)"
                elif group_image_source == 'comfy_sdxl':
                    source_name = "ComfyUI SDXL (reutilizada)"
                else:
                    source_name = "imagen existente (reutilizada)"
                
                self.log(f"       {source_name} - Compartida por {group_size} segmento(s)")
                
                for seg in segment_group:
                    seg['image_path'] = media_path
                    seg['image_source'] = 'existing'
                
                reused_count += group_size
                return
            elif not needs_regeneration and all_have_same_image and group_image_path and images_per_segment_ratio <= 1.0:
                # Cuando ratio es 1.0, forzar regeneración para evitar duplicados
                self.log(f"       Ratio 1.0 detectado: Forzando generación de imagen única para cada segmento")
                needs_regeneration = True
                for seg in segment_group:
                    seg['image_path'] = None
                    if 'image_source' in seg:
                        del seg['image_source']
            
            # Si necesitamos regenerar, limpiar las imágenes de todos los segmentos del grupo
            if needs_regeneration:
                for seg in segment_group:
                    seg['image_path'] = None
                    if 'image_source' in seg:
                        del seg['image_source']
            
            # Decidir si usar imagen real o IA (50/50)
            should_use_real = (group_idx in real_group_indices) if enable_real_images_mix else False
            
            group_size = len(segment_group)
            # Calcular números de segmentos correctamente
            start_seg = sum(len(segment_groups[i]) for i in range(group_idx)) + 1
            end_seg = start_seg + group_size - 1
            seg_numbers = f"{start_seg}-{end_seg}" if group_size > 1 else str(start_seg)
            self.log(f"\n    Grupo {group_idx+1}/{total_groups} (Segmentos {seg_numbers}): {fname}")
            
            # Generar sufijo único para evitar colisiones entre proyectos
            unique_suffix = f"_{int(time.time())}"
            
            # Flujo: fuentes manuales (si están activadas) + IA generativa seleccionada
            image_source = 'unknown'  # Inicializar image_source
            # Si el usuario eligió un proveedor IA específico, saltar búsquedas de imágenes reales
            _ia_providers = {
                'recraft', 'fal', 'fal_ai', 'google_ai', 'google', 'gemini',
                'flux', 'flux_dev', 'flux_schnell',
                'stability', 'stability_core', 'stability_ultra',
                'comfy', 'comfyui', 'comfy_schnell', 'comfy_sdxl', 'comfy_dev',
            }
            skip_real_images = selected_provider_key in _ia_providers
            if not media_path:
                # PRIORIDAD 1: Openverse (Gratis) (compatibilidad usa variable legacy)
                if use_google_images and self.google_images_client and not test_mode and not skip_real_images:
                    try:
                        self.log(f"       Buscando en Openverse (Gratis): {fname}")
                        # Usar el texto narrativo del segmento para búsqueda
                        narration_text = first_seg.get('text', '')
                        images = self._run_network_resilient(
                            "búsqueda en Openverse (Gratis)",
                            lambda: self.google_images_client.search_images(
                                visual_prompt, limit=3, narration_text=narration_text
                            ),
                            max_attempts=4,
                            retry_on_empty=True
                        )
                        if images:
                            # Descargar la primera imagen
                            img_data = images[0]
                            img_url = img_data.get('url') or img_data.get('link')
                            if img_url:
                                image_content = self._download_binary_with_resume(
                                    img_url,
                                    timeout=20,
                                    headers={'User-Agent': 'Mozilla/5.0'}
                                )
                                if image_content:
                                    tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.jpg")
                                    with open(tp, 'wb') as f:
                                        f.write(image_content)
                                    media_path = tp
                                    image_source = 'bing_images'
                                    self.log(f"          Imagen descargada de Openverse (Gratis)")
                                    generated_count += 1
                    except Exception as e:
                        self.log(f"         ️ Error buscando en Openverse (Gratis): {e}")
                
                # PRIORIDAD 2: Wikimedia (si está habilitado y Openverse (Gratis) falló)
                if not media_path and use_wikimedia and self.wikimedia_client and not test_mode and not skip_real_images:
                    try:
                        self.log(f"       Buscando en Wikimedia: {fname}")
                        narration_text = first_seg.get('text', '')
                        images = self._run_network_resilient(
                            "búsqueda en Wikimedia",
                            lambda: self.wikimedia_client.search_images(
                                visual_prompt, limit=3, narration_text=narration_text
                            ),
                            max_attempts=4,
                            retry_on_empty=True
                        )
                        if images:
                            # Descargar la primera imagen
                            img_data = images[0]
                            img_url = img_data.get('url') or img_data.get('file_url')
                            if img_url:
                                image_content = self._download_binary_with_resume(
                                    img_url,
                                    timeout=20,
                                    headers={'User-Agent': 'VideoOptimizerPro/1.0'}
                                )
                                if image_content:
                                    tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.jpg")
                                    with open(tp, 'wb') as f:
                                        f.write(image_content)
                                    media_path = tp
                                    image_source = 'wikimedia'
                                    self.log(f"          Imagen descargada de Wikimedia")
                                    generated_count += 1
                    except Exception as e:
                        self.log(f"         ️ Error buscando en Wikimedia: {e}")
                
                # PRIORIDAD 3: Generación IA (Google AI o Recraft)
                if not media_path:
                    if should_use_real:
                        self.log(f"      ️ Búsqueda de imágenes reales falló, usando IA generativa")

                    # Determinar dimensiones
                    if is_square:
                        w, h = (1080, 1080)
                    elif is_vertical:
                        w, h = (1080, 1920)
                    else:
                        w, h = (1920, 1080)

                    provider_key = self._normalize_provider_key(image_provider or 'auto')
                    negative_prompt = self._build_negative_prompt(visual_prompt)
                    recraft_style = self._resolve_generation_style(style, visual_prompt, 'recraft')
                    google_style = self._resolve_generation_style(style, visual_prompt, 'google_ai')
                    use_google_ai = provider_key in {'google_ai', 'google', 'gemini'}
                    use_fal_ai = provider_key in {'fal', 'fal_ai', 'flux', 'flux_dev', 'flux_schnell'}
                    use_stability = provider_key in {'stability_ultra', 'stability_core', 'stability'}
                    use_comfyui = provider_key in {'comfy', 'comfyui', 'comfy_schnell', 'comfy_sdxl', 'comfy_dev', 'comfy_flux_dev'}

                    use_recraft_primary = provider_key in {'auto', 'recraft', ''}

                    if provider_key == 'manual':
                        self.log("      ℹ️ Proveedor manual seleccionado; no se genera IA automática.")


                    elif use_comfyui:
                        comfy_client = self.comfyui_image_client
                        if comfy_client and not test_mode and getattr(comfy_client, 'available', False):
                            comfy_preset = self._resolve_comfy_preset(
                                provider_key,
                                is_vertical=is_vertical,
                                is_square=is_square,
                                style=style,
                            )
                            self.log(f"      [ComfyUI] Generando con preset {comfy_preset}: {fname}")
                            if style:
                                self.log(f"       Prompt (estilo '{style}'): {visual_prompt[:200]}...")
                            tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.png")
                            downloaded = self._run_network_resilient(
                                "generacion IA (ComfyUI)",
                                lambda: comfy_client.generate_image(
                                    prompt=visual_prompt,
                                    width=w,
                                    height=h,
                                    output_path=tp,
                                    negative_prompt=negative_prompt,
                                    style=style or recraft_style,
                                    preset=comfy_preset,
                                ),
                                max_attempts=2,
                                retry_on_empty=True,
                            )
                            if downloaded and os.path.exists(downloaded):
                                media_path = downloaded
                                image_source = self._comfy_image_source(provider_key)
                                self.log("          Imagen generada por ComfyUI")
                                generated_count += 1
                            else:
                                last_err = getattr(comfy_client, 'last_error', None)
                                if last_err:
                                    self.log(f"      ComfyUI: {last_err}")
                        else:
                            self.log("      ComfyUI seleccionado pero cliente no disponible. Revisa COMFYUI_BASE_URL y workflows.")


                    elif use_fal_ai:
                        if self.fal_image_client and not test_mode and getattr(self.fal_image_client, 'available', False):
                            # Determinar modelo Flux: schnell si el usuario lo pide explicito
                            if provider_key == 'flux_schnell':
                                try:
                                    self.fal_image_client.model_id = 'fal-ai/flux/schnell'
                                except Exception:
                                    pass
                            elif provider_key == 'flux_dev':
                                try:
                                    self.fal_image_client.model_id = 'fal-ai/flux/dev'
                                except Exception:
                                    pass

                            self.log(f"      [FAL] Generando con Flux ({self.fal_image_client.model_id}): {fname}")
                            if style:
                                self.log(f"       Prompt (estilo '{style}'): {visual_prompt[:200]}...")
                            # Guardar directamente a la ruta destino (el cliente descarga)
                            tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.png")
                            downloaded = self._run_network_resilient(
                                "generacion IA (FAL Flux)",
                                lambda: self.fal_image_client.generate_image(
                                    prompt=visual_prompt,
                                    width=w,
                                    height=h,
                                    output_path=tp,
                                    negative_prompt=negative_prompt,
                                    style=recraft_style,
                                ),
                                max_attempts=3,
                                retry_on_empty=True,
                            )
                            if downloaded and os.path.exists(downloaded):
                                media_path = downloaded
                                image_source = 'fal_flux'
                                self.log("          Imagen generada por FAL Flux")
                                generated_count += 1
                            else:
                                last_err = getattr(self.fal_image_client, 'last_error', None)
                                if last_err:
                                    self.log(f"      ️ FAL Flux: {last_err}")
                        else:
                            self.log("      ️ FAL seleccionado pero cliente no está disponible (FAL_KEY o SDK).")


                    elif use_stability:
                        stab_client = (
                            self.stability_core_client
                            if provider_key == 'stability_core'
                            else self.stability_ultra_client
                        )
                        model_label = "Core" if provider_key == 'stability_core' else "Ultra"
                        if stab_client and getattr(stab_client, 'available', False) and not test_mode:
                            self.log(f"      [Stability {model_label}] Generando: {fname}")
                            tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.png")
                            stab_result = self._run_network_resilient(
                                f"generacion IA (Stability {model_label})",
                                lambda: stab_client.generate_image(
                                    prompt=visual_prompt,
                                    width=w,
                                    height=h,
                                    negative_prompt=negative_prompt or "",
                                    output_path=tp,
                                ),
                                max_attempts=3,
                                retry_on_empty=True,
                            )
                            if stab_result and os.path.exists(tp):
                                media_path = tp
                                image_source = f'stability_{model_label.lower()}'
                                self.log(f"         Imagen generada por Stability {model_label}")
                                generated_count += 1
                            else:
                                last_err = getattr(stab_client, 'last_error', None)
                                if last_err:
                                    self.log(f"      Stability {model_label}: {last_err}")
                        else:
                            self.log(f"      Stability {model_label} seleccionado pero no disponible (STABILITY_API_KEY).")

                    elif use_google_ai:
                        if self.google_ai_image_client and not test_mode and not google_quota_exhausted:
                            self.log(f"       Generando con Google AI (Gemini API): {fname}")
                            if style:
                                self.log(f"       Prompt (estilo '{style}'): {visual_prompt[:200]}...")
                            image_content = self._run_network_resilient(
                                "generación IA (Google AI)",
                                lambda: self.google_ai_image_client.generate_image(
                                    visual_prompt, w, h, negative_prompt=negative_prompt, style=google_style
                                ),
                                max_attempts=4,
                                retry_on_empty=True
                            )
                            if image_content:
                                tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.png")
                                with open(tp, 'wb') as f:
                                    f.write(image_content)
                                media_path = tp
                                image_source = 'google_ai'
                                self.log("          Imagen generada por Google AI")
                                generated_count += 1
                            elif self._looks_like_quota_error(getattr(self.google_ai_image_client, 'last_error', None)):
                                google_quota_exhausted = True
                                self.log("      ️ Google AI sin cuota en esta sesión.")
                        elif google_quota_exhausted:
                            self.log("      ️ Google AI ya quedó sin cuota en esta sesión.")
                        else:
                            self.log("      ️ Google AI seleccionado pero no está disponible (API key o cliente).")


                    else:
                        # Si llega un valor desconocido, mantener fallback a Recraft.


                        # Proveedor primario (Recraft real).
                        if use_recraft_primary and self.recraft_client and not test_mode:
                            self.log(f"      [Recraft] Generando con Recraft AI: {fname}")
                            if style:
                                self.log(f"      Prompt (estilo '{style}'): {visual_prompt[:200]}...")
                            recraft_result = self._run_network_resilient(
                                "generacion IA (Recraft)",
                                lambda: self.recraft_client.generate_image(
                                    prompt=visual_prompt,
                                    style=recraft_style or "Photorealism",
                                    width=w,
                                    height=h,
                                    negative_prompt=negative_prompt or "",
                                ),
                                max_attempts=4,
                                retry_on_empty=True
                            )
                            if recraft_result:
                                u = recraft_result.get('url')
                                image_content = self._download_binary_with_resume(u, timeout=30)
                                if image_content:
                                    tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.jpg")
                                    with open(tp, 'wb') as f:
                                        f.write(image_content)
                                    media_path = tp
                                    image_source = 'recraft_ai'
                                    self.log("         OK Imagen generada por Recraft AI")
                                    generated_count += 1

                    # Si el proveedor seleccionado falló.
                    if not media_path:
                        if use_comfyui or provider_key == 'comfy_dev':
                            self.log("       ComfyUI fallÃ³")
                            self.log("       Posibles causas:")
                            self.log("         - COMFYUI_BASE_URL no apunta a una instancia activa")
                            self.log("         - Falta el workflow JSON exportado desde ComfyUI")
                            self.log("         - El preset no coincide con los nodos del workflow")
                            self.log("         - Vast.ai/ComfyUI todavia esta cargando el modelo")
                        elif use_fal_ai:
                            self.log("       FAL Flux falló")
                            self.log("       Posibles causas:")
                            self.log("         - FAL_KEY inválida o sin saldo")
                            self.log("         - Contenido bloqueado por filtros de seguridad")
                            self.log("         - Endpoint del modelo cambió")
                            self.log("         - Error de conexión o timeout")
                        elif use_google_ai:
                            self.log("       Google AI falló")
                            self.log("       Posibles causas:")
                            self.log("         - API key inválida o sin cuota")
                            self.log("         - Modelo sin soporte de imagen")
                            self.log("         - Contenido bloqueado por filtros")
                            self.log("         - Error de conexión o timeout")
                        elif provider_key != 'manual':
                            self.log("       Recraft AI falló")
                            self.log("       Posibles causas:")
                            self.log("         - API keys inválidas o sin créditos")
                            self.log("         - Contenido bloqueado por filtros")
                            self.log("         - Error de conexión o timeout")

                        if provider_key != 'manual':
                            self.log("       SOLUCIÓN: Usa el modo 'Manual (Gratuito)' para generar prompts")
                            self.log("         o habilita Openverse (Gratis)/Wikimedia en las opciones")

                        # Detectar temas controvertidos en el prompt
                        controversial_keywords = ['war', 'guerra', 'battle', 'batalla', 'violence', 'violencia',
                                                 'weapon', 'arma', 'conflict', 'conflicto', 'death', 'muerte',
                                                 'crime', 'crimen', 'attack', 'ataque', 'kill', 'matar']
                        prompt_lower = visual_prompt.lower()
                        if any(keyword in prompt_lower for keyword in controversial_keywords):
                            self.log("      ️ Tema sensible detectado - puede ser bloqueado por filtros")
                            self.log("       Usa imágenes reales (Wikimedia/Openverse (Gratis)) o modo Manual")
            
            # Guardar ruta de imagen en todos los segmentos del grupo
            if media_path:
                abs_path = os.path.abspath(media_path)
                group_size = len(segment_group)
                
                # Asignar la misma imagen a todos los segmentos del grupo
                # (Cuando ratio es 1.0, cada segmento está en su propio grupo, así que esto está bien)
                for seg in segment_group:
                    seg['image_path'] = abs_path
                    seg['image_source'] = image_source
                
                if group_size > 1:
                    self.log(f"       Imagen guardada: {os.path.basename(media_path)} (compartida por {group_size} segmentos)")
                else:
                    self.log(f"       Imagen guardada: {os.path.basename(media_path)}")
                
                success_count += group_size
            else:
                self.log(f"      ️ No se generó imagen para el grupo: {fname}")
                # Marcar todos los segmentos del grupo como sin imagen
                for seg in segment_group:
                    seg['image_path'] = None
                failed_count += group_size
                
        # Ejecutar en paralelo (max 5 hilos)
        max_workers = min(5, max(1, len(segment_groups)))
        self.log(f"\n⚡ Iniciando generacion concurrente de imagenes con {max_workers} hilos...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(_process_group, enumerate(segment_groups)))
        
        # Resumen final
        self.log(f"\n Generación de imágenes completada")
        self.log(f"    Resumen:")
        self.log(f"       Generadas: {success_count} segmentos")
        self.log(f"      ️  Reutilizadas: {reused_count} segmentos")
        self.log(f"       Fallidas: {failed_count} segmentos")
        if interleave_images:
            self.log(f"       Modo intercalado: {skipped_count} segmentos quedaron vacíos para edición manual")
        if images_per_segment_ratio > 1.0:
            self.log(f"       Imágenes IA nuevas: {generated_count} (agrupación de vacíos activa)")
        
        # Si hay muchas fallas, sugerir modo manual
        if failed_count > total_segments * 0.5:  # Más del 50% fallaron
            self.log(f"\n️ ADVERTENCIA: {failed_count} de {total_segments} segmentos no tienen imagen")
            self.log(f"    RECOMENDACIÓN: Usa el modo 'Manual (Gratuito)' para generar prompts")
            self.log(f"      y copiarlos en servicios gratuitos como:")
            self.log(f"      • Gemini Veo (https://gemini.google.com/)")
            self.log(f"      • Bing Image Creator (https://www.bing.com/images/create)")
            self.log(f"      • Recraft AI (https://www.recraft.ai)")
            self.log(f"    Selecciona 'Manual (Gratuito)' en el combo de proveedores")

        # ──────────────────────────────────────────────────────────────
        # Auto-stop de la instancia Vast.ai al terminar la generacion masiva.
        # Politica "just-in-time": la instancia se enciende cuando se necesita
        # (en ensure_ready) y se apaga cuando ya no. Esto es mas fiable que
        # depender de QApplication.aboutToQuit, que no dispara si la app se
        # cierra de forma irregular (consola cerrada, hard kill, crash).
        # Solo apaga si la instancia fue usada en esta corrida (`_used_remote`).
        # ──────────────────────────────────────────────────────────────
        try:
            from vast_ai_instance_manager import get_default_vast_manager
            _vm = get_default_vast_manager()
            if _vm.enabled and getattr(_vm, "_used_remote", False):
                self.log("\n[Vast.ai] Generacion terminada — apagando instancia para ahorrar creditos")
                _vm.stop_instance()
                # Reset para que una segunda generacion en la misma sesion vuelva
                # a hacer el ciclo start->stop limpiamente.
                _vm._used_remote = False
                _vm._shutdown_called = False
        except Exception as _vast_stop_exc:
            self.log(f"[Vast.ai] Aviso: no se pudo detener la instancia tras la generacion: {_vast_stop_exc}")

        return storyboard_data






