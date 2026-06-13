# image_generation_manager.py
"""
Gestor de generación de imágenes para storyboards
Maneja la generación de imágenes usando Recraft AI / Google AI
y fuentes manuales (Openverse (Gratis), Wikimedia).
"""

import json
import os
import random
import re
import requests
import socket
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable


class ImageGenerationManager:
    """
    Gestor de generación de imágenes para storyboards.
    Maneja la generación de imágenes usando Recraft o Google AI.
    """
    
    def __init__(self, log_callback=None, generated_media_dir=None,
                 fal_client=None, recraft_client=None, leonardo_client=None,
                 google_ai_image_client=None, vertex_imagen_client=None,
                 google_images_client=None, wikimedia_client=None,
                 prompt_processor=None):
        """
        Inicializa el gestor de generación de imágenes.
        
        Args:
            log_callback: Función para logging (opcional)
            generated_media_dir: Directorio para medios generados (opcional)
            fal_client: Cliente real de Fal.ai (opcional)
            recraft_client: Cliente real de Recraft (opcional)
            leonardo_client: Wrapper compat Leonardo (backend Recraft) (opcional)
            google_ai_image_client: Cliente Google AI (Gemini) para imagen generativa
            vertex_imagen_client: Cliente Vertex AI (Imagen 4 Fast) para imagen generativa
            google_images_client: Cliente de Openverse (Gratis) (compat legacy)
            wikimedia_client: Cliente de Wikimedia (opcional)
            prompt_processor: Procesador de prompts (opcional)
        """
        self.log = log_callback or (lambda msg: print(msg))
        self.generated_media_dir = generated_media_dir
        self.fal_client = fal_client
        self.recraft_client = recraft_client
        self.leonardo_client = leonardo_client
        self.google_ai_image_client = google_ai_image_client
        self.vertex_imagen_client = vertex_imagen_client
        self.google_images_client = google_images_client
        self.wikimedia_client = wikimedia_client
        self.prompt_processor = prompt_processor

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
                        f"         🌐 Conexión inestable durante {action_name} "
                        f"(intento {attempt}/{attempts}). Esperando reconexión..."
                    )
                    if self._wait_for_internet_recovery():
                        self.log(f"         🔄 Internet restablecida. Reanudando {action_name}...")
                        continue
                raise

            if value:
                return value

            if retry_on_empty and attempt < attempts and not self._has_internet_connection():
                self.log(
                    f"         🌐 Sin internet durante {action_name} "
                    f"(intento {attempt}/{attempts}). Esperando reconexión..."
                )
                if self._wait_for_internet_recovery():
                    self.log(f"         🔄 Internet restablecida. Reanudando {action_name}...")
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
            self.log(f"         ⚠️ Error descargando recurso: {e}")
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
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            return self.prompt_processor.combine_prompts(segment_group)
        # Fallback: combinar textos
        prompts = [seg.get('visual_prompt', '') for seg in segment_group]
        return ', '.join(filter(None, prompts))
    
    def _apply_style_to_prompt(self, visual_prompt, style, provider_key=None):
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            if hasattr(self.prompt_processor, 'adapt_prompt_for_provider'):
                return self.prompt_processor.adapt_prompt_for_provider(
                    visual_prompt,
                    style=style,
                    provider=provider_key,
                )
            return self.prompt_processor.apply_style_to_prompt(visual_prompt, style)
        # Fallback: retornar prompt sin modificar
        if style and str(provider_key or '').strip().lower() in {
            'vertex_imagen', 'vertex', 'vertex_ai', 'imagen_4_fast', 'imagen4_fast', 'imagen4'
        }:
            return f"{visual_prompt}, {style}, single coherent scene, clear focal subject"
        return visual_prompt

    def _apply_aspect_guidance_to_prompt(self, visual_prompt, is_vertical: bool = False,
                                         is_square: bool = False) -> str:
        """Añade guía de composición según el formato final del video."""
        prompt = str(visual_prompt or '').strip()
        if not prompt:
            return prompt

        if is_vertical:
            guidance = (
                "vertical portrait composition optimized for smartphone framing, "
                "subject centered in the middle safe area, leave clean lower-third negative space for subtitles, "
                "strong focal subject, no embedded text, no captions, no UI, no cropped face, no important details at the edges"
            )
            prompt_lower = prompt.lower()
            guidance_markers = (
                'vertical portrait composition',
                'smartphone framing',
                'lower-third negative space',
                'no embedded text',
                'middle safe area',
            )
            if not any(marker in prompt_lower for marker in guidance_markers):
                return f"{prompt}, {guidance}"
            return prompt

        if is_square:
            guidance = (
                "square composition, centered framing, balanced negative space, "
                "no embedded text, no captions"
            )
            prompt_lower = prompt.lower()
            if 'square composition' not in prompt_lower and 'centered framing' not in prompt_lower:
                return f"{prompt}, {guidance}"

        return prompt

    def _sanitize_visual_prompt(self, visual_prompt: str) -> str:
        prompt = str(visual_prompt or '').strip()
        if not prompt:
            return prompt

        substitutions = (
            (r"\bvertical\s+9:16\s+portrait\s+composition\s+for\s+youtube\s+shorts\b", "vertical portrait composition"),
            (r"\b9:16\b", "vertical portrait"),
            (r"\b1:1\b", "square composition"),
            (r"\byoutube shorts\b", "vertical short-form video"),
            (r"\bdifferent camera angle\b", "alternate viewpoint"),
            (r"\bcamera angle\b", "viewpoint"),
            (r"\bframe\s+\d+\b", "still image composition"),
            (r"\bvariation\s+\d+\b", "distinct arrangement"),
            (r"\bperspective\s+\d+\b", "alternate viewpoint"),
            (r"\bunique scene\s+\d+\b", "distinct scene arrangement"),
            (r"\bscene\s+\d+\b", "alternate composition"),
        )
        for pattern, replacement in substitutions:
            prompt = re.sub(pattern, replacement, prompt, flags=re.IGNORECASE)

        prompt = re.sub(r",?\s*the sound of [^,.]+(?:fills the air)?", "", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r",?\s*and the sound of [^,.]+(?:fills the air)?", "", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r",?\s*audio cue:[^,.]+", "", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\bvertical\s+vertical\b", "vertical", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\bportrait\s+portrait\b", "portrait", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\band\s*\.", ".", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r",\s*\.", ".", prompt)
        prompt = re.sub(r"\s+,", ",", prompt)
        prompt = re.sub(r",\s*,+", ", ", prompt)
        prompt = re.sub(r"\s{2,}", " ", prompt)

        prompt_parts = []
        seen_parts = set()
        for part in prompt.split(','):
            clean_part = part.strip()
            normalized_part = clean_part.lower()
            if clean_part and normalized_part not in seen_parts:
                prompt_parts.append(clean_part)
                seen_parts.add(normalized_part)

        prompt = ', '.join(prompt_parts)
        return prompt.strip(" ,")

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
            "antiquity", "bronze age", "iron age", "antique",
        )
        return any(marker in prompt_lower for marker in historical_markers)

    def _build_negative_prompt(self, visual_prompt: str) -> str:
        base_negative_terms = [
            "captions", "subtitle text", "title text", "letters", "numbers", "timestamp",
            "ui", "hud", "watermark", "logo", "label", "signage", "poster layout",
            "camera", "camera crew", "film crew", "videographer", "photographer",
            "tripod", "microphone", "boom mic", "studio light", "behind the scenes",
            "making of", "documentary set",
        ]

        if self._looks_historical_prompt(visual_prompt):
            base_negative_terms.extend([
                "modern props", "modern tools", "modern objects", "contemporary clothing",
                "paper notebook", "spiral notebook", "ballpoint pen", "smartphone",
                "tablet", "computer", "modern recording equipment",
            ])

        base_negative = ", ".join(base_negative_terms)
        try:
            from video_config import VideoConfig
            return VideoConfig.get_negative_prompt(base_negative)
        except Exception:
            return base_negative
    
    def regenerate_visual_prompts_with_style(self, storyboard_data, style):
        """Delega a PromptProcessor si está disponible"""
        if self.prompt_processor:
            return self.prompt_processor.regenerate_visual_prompts_with_style(storyboard_data, style)
        # Fallback: retornar storyboard sin modificar
        return storyboard_data
    
    def generate_all_images_for_storyboard(self, storyboard_data, platform,
                                           use_wikimedia=False, disable_wikimedia=False,
                                           use_real_images=True, use_google_images=True,
                                           enable_real_images_mix=False, test_mode=False,
                                           image_provider='auto', images_per_segment_ratio=1.0,
                                           interleave_images=False, style='Realistic image',
                                           regenerate_prompts=False, project_path=None):
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
        
        self.log(f"\n🖼️ GENERANDO TODAS LAS IMÁGENES...")
        self.log(f"   🔧 Parámetros: use_google_images={use_google_images}, use_real_images={use_real_images}, enable_real_images_mix={enable_real_images_mix}")
        
        segments = storyboard_data.get('segments', [])
        is_vertical = platform in ['tiktok', 'reels', 'youtube_short']
        is_square = platform in ['square', 'x_square', 'x']
        total_segments = len(segments)
        selected_provider_key = str(image_provider or 'auto').strip().lower()
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
            self.log(f"   📁 Usando directorio del proyecto: {project_media_dir}")
        # Si no se encuentra proyecto específico, intentar usar project_media del directorio actual
        if not project_media_dir:
            # Intentar encontrar project_media en el directorio actual o en projects/
            from pathlib import Path
            current_dir = Path.cwd()
            possible_project_media = current_dir / "project_media"
            if possible_project_media.exists():
                project_media_dir = possible_project_media
                self.log(f"   📁 Usando project_media del directorio actual: {project_media_dir}")
            else:
                # Fallback: usar directorio global
                project_media_dir = self.generated_media_dir
                self.log(f"   ⚠️ No se encontró directorio del proyecto, usando global: {project_media_dir}")
        
        # Usar el directorio determinado
        media_dir = project_media_dir
        project_base_dir = media_dir.parent if media_dir else None
        
        # Si está activado el modo intercalado, solo generar imágenes para índices pares (0, 2, 4...)
        if interleave_images:
            self.log(f"   🔄 Modo intercalado: Generando imágenes solo para segmentos impares (1, 3, 5...)")
            self.log(f"   📊 Segmentos pares (2, 4, 6...) quedarán vacíos para agregar manualmente")
            # Limpiar imágenes de segmentos pares (índices impares en 0-based: 1, 3, 5...)
            for idx in range(len(segments)):
                if idx % 2 == 1:  # Índices impares (segmentos pares: 2, 4, 6...)
                    segments[idx]['image_path'] = None
                    if 'image_source' in segments[idx]:
                        del segments[idx]['image_source']
            # Filtrar segmentos para solo procesar los impares (índice par en 0-based: 0, 2, 4...)
            segments_to_process = [seg for idx, seg in enumerate(segments) if idx % 2 == 0]
            skipped_count = total_segments - len(segments_to_process)
            self.log(f"   📝 {skipped_count} segmentos quedaron vacíos para edición manual")
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
            self.log(f"   📊 Distribución: {num_real_images} imágenes reales, {total_groups - num_real_images} imágenes IA")
        
        # Contadores para estadísticas
        generated_count = 0
        failed_count = 0
        success_count = 0
        reused_count = 0
        vertex_quota_exhausted = False
        google_quota_exhausted = False
        
        # Track de prompts usados para detectar duplicados
        used_prompts = {}  # {prompt_hash: (segment_index, prompt_text)}
        
        # Iterar sobre grupos de segmentos
        for group_idx, segment_group in enumerate(segment_groups):
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
                    self.log(f"      🎨 Estilo '{style}' aplicado al prompt")
                    # Log del prompt original (primeros 150 caracteres)
                    self.log(f"      📝 Prompt original: {original_prompt[:150]}...")
                    # Log del prompt final (primeros 150 caracteres)
                    self.log(f"      📝 Prompt con estilo: {visual_prompt[:150]}...")

            aspect_adjusted_prompt = self._apply_aspect_guidance_to_prompt(
                visual_prompt,
                is_vertical=is_vertical,
                is_square=is_square,
            )
            if aspect_adjusted_prompt != visual_prompt and (is_vertical or is_square):
                self.log("      📐 Prompt ajustado al encuadre del formato final")
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
                self.log(f"      ⚠️ ADVERTENCIA: Prompt duplicado detectado!")
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
            self.log(f"      🔍 Prompt final para segmento {segment_number}: {visual_prompt[:200]}...")
            
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
                            self.log(f"      ⏭️ Segmento {segments.index(seg) + 1} tiene imagen manual ({image_source}) - Saltando")
                            continue  # Saltar este segmento, tiene contenido manual
                        # Si es IA generada y existe, también conservarla (no regenerar)
                        elif image_source in ['fal_ai', 'leonardo', 'leonardo_ai', 'fal', 'recraft_ai', 'recraft_compat_leonardo', 'google_ai', 'vertex_imagen']:
                            segments_with_content.append((seg, content_path, content_type, image_source))
                            self.log(f"      ⏭️ Segmento {segments.index(seg) + 1} ya tiene imagen IA ({image_source}) - Saltando")
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
                            self.log(f"      ⏭️ Segmento {segments.index(seg) + 1} tiene video ({image_source}) - Saltando")
                            continue  # Saltar este segmento, tiene video manual
                
                # Si no tiene contenido, agregarlo a la lista para generar
                segments_to_generate.append(seg)
            
            # Si todos los segmentos del grupo tienen contenido manual, saltar todo el grupo
            if len(segments_with_content) == len(segment_group):
                group_size = len(segment_group)
                start_seg = sum(len(segment_groups[i]) for i in range(group_idx)) + 1
                end_seg = start_seg + group_size - 1
                seg_numbers = f"{start_seg}-{end_seg}" if group_size > 1 else str(start_seg)
                self.log(f"\n   📸 Grupo {group_idx+1}/{total_groups} (Segmentos {seg_numbers}): {fname}")
                
                content_sources = [src for _, _, _, src in segments_with_content]
                unique_sources = list(set(content_sources))
                source_names = {
                    'wikimedia': 'Wikimedia',
                    'bing_images': 'Openverse (Gratis)',
                    'google_images': 'Openverse (Gratis) (legacy)',
                    'pexels_video': 'Pexels Video',
                    'leonardo': 'Leonardo AI',
                    'fal': 'Fal.ai',
                    'fal_ai': 'Fal.ai',
                    'recraft_ai': 'Recraft AI',
                    'recraft_compat_leonardo': 'Recraft AI (compat Leonardo)',
                    'google_ai': 'Google AI (Gemini)',
                    'vertex_imagen': 'Vertex AI (Imagen 4 Fast)'
                }
                sources_str = ', '.join([source_names.get(s, s) for s in unique_sources])
                self.log(f"      ✅ Todos los segmentos tienen contenido existente ({sources_str}) - Saltando generación")
                reused_count += group_size
                continue  # Saltar este grupo completo
            
            # Si algunos segmentos tienen contenido y otros no, generar solo para los que faltan
            if segments_with_content and segments_to_generate:
                group_size = len(segment_group)
                start_seg = sum(len(segment_groups[i]) for i in range(group_idx)) + 1
                end_seg = start_seg + group_size - 1
                seg_numbers = f"{start_seg}-{end_seg}" if group_size > 1 else str(start_seg)
                self.log(f"\n   📸 Grupo {group_idx+1}/{total_groups} (Segmentos {seg_numbers}): {fname}")
                self.log(f"      ⏭️ {len(segments_with_content)} segmento(s) tienen contenido existente - Generando para {len(segments_to_generate)} restante(s)")
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
                            self.log(f"      🎨 Estilo '{style}' aplicado al prompt (grupo actualizado)")
                            # Log del prompt original (primeros 150 caracteres)
                            self.log(f"      📝 Prompt original (grupo): {original_prompt[:150]}...")
                            # Log del prompt final (primeros 150 caracteres)
                            self.log(f"      📝 Prompt con estilo (grupo): {visual_prompt[:150]}...")

                    aspect_adjusted_prompt = self._apply_aspect_guidance_to_prompt(
                        visual_prompt,
                        is_vertical=is_vertical,
                        is_square=is_square,
                    )
                    if aspect_adjusted_prompt != visual_prompt and (is_vertical or is_square):
                        self.log("      📐 Prompt ajustado al encuadre del formato final")
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
                self.log(f"\n   📸 Grupo {group_idx+1}/{total_groups} (Segmentos {seg_numbers}): {fname}")
                
                if group_image_source in ['recraft_ai', 'recraft_compat_leonardo']:
                    source_name = "Recraft AI (reutilizada)"
                elif group_image_source == 'google_ai':
                    source_name = "Google AI (reutilizada)"
                elif group_image_source == 'vertex_imagen':
                    source_name = "Vertex AI Imagen 4 Fast (reutilizada)"
                elif group_image_source == 'leonardo':
                    source_name = "Leonardo AI (reutilizada)"
                elif group_image_source in {'fal_ai', 'fal'}:
                    source_name = "Fal.ai FLUX.1 schnell (reutilizada)"
                else:
                    source_name = "imagen existente (reutilizada)"
                
                self.log(f"      ✅ {source_name} - Compartida por {group_size} segmento(s)")
                
                for seg in segment_group:
                    seg['image_path'] = media_path
                    seg['image_source'] = 'existing'
                
                reused_count += group_size
                continue  # Saltar este grupo, ya tiene imagen
            elif not needs_regeneration and all_have_same_image and group_image_path and images_per_segment_ratio <= 1.0:
                # Cuando ratio es 1.0, forzar regeneración para evitar duplicados
                self.log(f"      🔄 Ratio 1.0 detectado: Forzando generación de imagen única para cada segmento")
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
            self.log(f"\n   📸 Grupo {group_idx+1}/{total_groups} (Segmentos {seg_numbers}): {fname}")
            
            # Generar sufijo único para evitar colisiones entre proyectos
            unique_suffix = f"_{int(time.time())}"
            
            # Flujo: fuentes manuales (si están activadas) + IA generativa seleccionada
            image_source = 'unknown'  # Inicializar image_source
            if not media_path:
                # PRIORIDAD 1: Openverse (Gratis) (compatibilidad usa variable legacy)
                if use_google_images and self.google_images_client and not test_mode:
                    try:
                        self.log(f"      🔍 Buscando en Openverse (Gratis): {fname}")
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
                                    self.log(f"         ✅ Imagen descargada de Openverse (Gratis)")
                                    generated_count += 1
                    except Exception as e:
                        self.log(f"         ⚠️ Error buscando en Openverse (Gratis): {e}")
                
                # PRIORIDAD 2: Wikimedia (si está habilitado y Openverse (Gratis) falló)
                if not media_path and use_wikimedia and self.wikimedia_client and not test_mode:
                    try:
                        self.log(f"      📚 Buscando en Wikimedia: {fname}")
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
                                    self.log(f"         ✅ Imagen descargada de Wikimedia")
                                    generated_count += 1
                    except Exception as e:
                        self.log(f"         ⚠️ Error buscando en Wikimedia: {e}")
                
                # PRIORIDAD 3: Generación IA (Google AI o Recraft)
                if not media_path:
                    if should_use_real:
                        self.log(f"      ⚠️ Búsqueda de imágenes reales falló, usando IA generativa")

                    # Determinar dimensiones
                    if is_square:
                        w, h = (1080, 1080)
                    elif is_vertical:
                        w, h = (1080, 1920)
                    else:
                        w, h = (1920, 1080)

                    provider_key = str(image_provider or 'auto').strip().lower()
                    negative_prompt = self._build_negative_prompt(visual_prompt)
                    use_vertex_imagen = provider_key in {
                        'vertex_imagen', 'vertex', 'vertex_ai', 'imagen_4_fast', 'imagen4_fast', 'imagen4'
                    }
                    use_google_ai = provider_key in {'google_ai', 'google', 'gemini'}

                    use_fal_primary = provider_key in {'fal', 'fal_ai'}
                    # Compatibilidad legacy: si viene "leonardo", usar wrapper Leonardo.
                    use_recraft_compat_leonardo = provider_key == 'leonardo'
                    use_recraft_primary = provider_key in {'auto', 'recraft', ''}

                    if provider_key == 'manual':
                        self.log("      ℹ️ Proveedor manual seleccionado; no se genera IA automática.")

                    # Google AI seleccionado explicitamente.
                    elif use_vertex_imagen:
                        if self.vertex_imagen_client and not test_mode and not vertex_quota_exhausted:
                            self.log(f"      [VertexImagen] Generando con Vertex AI (Imagen 4 Fast): {fname}")
                            if style:
                                self.log(f"      Prompt (estilo '{style}'): {visual_prompt[:200]}...")
                            image_content = self._run_network_resilient(
                                "generacion IA (Vertex Imagen)",
                                lambda: self.vertex_imagen_client.generate_image(
                                    visual_prompt, w, h, negative_prompt=negative_prompt, style=None
                                ),
                                max_attempts=4,
                                retry_on_empty=True
                            )
                            if image_content:
                                tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.png")
                                with open(tp, 'wb') as f:
                                    f.write(image_content)
                                media_path = tp
                                image_source = 'vertex_imagen'
                                self.log("         OK Imagen generada por Vertex AI (Imagen 4 Fast)")
                                generated_count += 1
                            elif self._looks_like_quota_error(getattr(self.vertex_imagen_client, 'last_error', None)):
                                vertex_quota_exhausted = True
                                self.log("      ⚠️ Vertex AI sin cuota en esta sesión. Se intentará Google AI para los grupos restantes.")
                        elif vertex_quota_exhausted:
                            self.log("      ⚠️ Vertex AI ya quedó sin cuota en esta sesión. Saltando al fallback Google AI.")
                        else:
                            self.log("      WARNING Vertex AI seleccionado pero no esta disponible (ADC, billing o cliente).")

                        if not media_path and self.google_ai_image_client and not test_mode and not google_quota_exhausted:
                            self.log("      🔁 Vertex AI falló. Intentando fallback con Google AI (Gemini API)...")
                            image_content = self._run_network_resilient(
                                "fallback IA (Google AI)",
                                lambda: self.google_ai_image_client.generate_image(
                                    visual_prompt, w, h, negative_prompt=negative_prompt, style=style
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
                                self.log("         ✅ Imagen generada por Google AI (fallback)")
                                generated_count += 1
                            elif self._looks_like_quota_error(getattr(self.google_ai_image_client, 'last_error', None)):
                                google_quota_exhausted = True
                                self.log("      ⚠️ Google AI también quedó sin cuota en esta sesión.")

                    elif use_google_ai:
                        if self.google_ai_image_client and not test_mode and not google_quota_exhausted:
                            self.log(f"      🤖 Generando con Google AI (Gemini API): {fname}")
                            if style:
                                self.log(f"      📝 Prompt (estilo '{style}'): {visual_prompt[:200]}...")
                            image_content = self._run_network_resilient(
                                "generación IA (Google AI)",
                                lambda: self.google_ai_image_client.generate_image(
                                    visual_prompt, w, h, negative_prompt=negative_prompt, style=style
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
                                self.log("         ✅ Imagen generada por Google AI")
                                generated_count += 1
                            elif self._looks_like_quota_error(getattr(self.google_ai_image_client, 'last_error', None)):
                                google_quota_exhausted = True
                                self.log("      ⚠️ Google AI sin cuota en esta sesión. Se intentará Vertex AI para los grupos restantes.")
                        elif google_quota_exhausted:
                            self.log("      ⚠️ Google AI ya quedó sin cuota en esta sesión. Saltando al fallback Vertex AI.")
                        else:
                            self.log("      ⚠️ Google AI seleccionado pero no está disponible (API key o cliente).")

                        if not media_path and self.vertex_imagen_client and not test_mode and not vertex_quota_exhausted:
                            self.log("      🔁 Google AI falló. Intentando fallback con Vertex AI (Imagen 4 Fast)...")
                            image_content = self._run_network_resilient(
                                "fallback IA (Vertex Imagen)",
                                lambda: self.vertex_imagen_client.generate_image(
                                    visual_prompt, w, h, negative_prompt=negative_prompt, style=None
                                ),
                                max_attempts=4,
                                retry_on_empty=True
                            )
                            if image_content:
                                tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.png")
                                with open(tp, 'wb') as f:
                                    f.write(image_content)
                                media_path = tp
                                image_source = 'vertex_imagen'
                                self.log("         ✅ Imagen generada por Vertex AI (fallback)")
                                generated_count += 1
                            elif self._looks_like_quota_error(getattr(self.vertex_imagen_client, 'last_error', None)):
                                vertex_quota_exhausted = True
                                self.log("      ⚠️ Vertex AI también quedó sin cuota en esta sesión.")

                    # Fal.ai, Recraft y wrappers de compatibilidad.
                    else:
                        # Si llega un valor desconocido, mantener fallback a Recraft.
                        if not use_fal_primary and not use_recraft_primary and not use_recraft_compat_leonardo:
                            use_recraft_primary = True

                        if use_fal_primary and self.fal_client and not test_mode:
                            self.log(f"      [Fal.ai] Generando con FLUX.1 schnell: {fname}")
                            u = self._run_network_resilient(
                                "generacion IA (Fal.ai)",
                                lambda: self.fal_client.generate_image(
                                    visual_prompt, w, h, negative_prompt=negative_prompt, style=style
                                ),
                                max_attempts=4,
                                retry_on_empty=True
                            )
                            if u:
                                image_content = self._download_binary_with_resume(u, timeout=30)
                                if image_content:
                                    tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.jpg")
                                    with open(tp, 'wb') as f:
                                        f.write(image_content)
                                    media_path = tp
                                    image_source = 'fal_ai'
                                    self.log("         OK Imagen generada por Fal.ai")
                                    generated_count += 1
                        elif use_fal_primary and not test_mode:
                            self.log("      WARNING Fal.ai seleccionado pero no esta disponible (SDK o API key).")

                        # Proveedor primario (Recraft real).
                        if use_recraft_primary and self.recraft_client and not test_mode:
                            self.log(f"      [Recraft] Generando con Recraft AI: {fname}")
                            if style:
                                self.log(f"      Prompt (estilo '{style}'): {visual_prompt[:200]}...")
                            recraft_result = self._run_network_resilient(
                                "generacion IA (Recraft)",
                                lambda: self.recraft_client.generate_image(
                                    prompt=visual_prompt,
                                    style=style or "Photorealism",
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

                        # Compatibilidad legacy (wrapper Leonardo -> Recraft).
                        if use_recraft_compat_leonardo and not media_path and self.leonardo_client and not test_mode:
                            self.log(f"      [RecraftCompat] Generando con Recraft AI (compat Leonardo): {fname}")
                            if style:
                                self.log(f"      Prompt (estilo '{style}'): {visual_prompt[:200]}...")
                            leo_kwargs = {}
                            if style:
                                leo_kwargs['model_name'] = style
                            u = self._run_network_resilient(
                                "generacion IA (Recraft wrapper Leonardo)",
                                lambda: self.leonardo_client.generate_image(
                                    visual_prompt, w, h, negative_prompt=negative_prompt, **leo_kwargs
                                ),
                                max_attempts=4,
                                retry_on_empty=True
                            )
                            if u:
                                image_content = self._download_binary_with_resume(u, timeout=30)
                                if image_content:
                                    tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.jpg")
                                    with open(tp, 'wb') as f:
                                        f.write(image_content)
                                    media_path = tp
                                    image_source = 'recraft_compat_leonardo'
                                    self.log("         OK Imagen generada por Recraft AI (compat Leonardo)")
                                    generated_count += 1

                        # Fallback cruzado entre Recraft y compat Leonardo.
                        if not media_path and not test_mode:
                            if use_recraft_primary and self.leonardo_client:
                                self.log("      Recraft fallo, intentando wrapper Leonardo...")
                                u = self._run_network_resilient(
                                    "fallback IA (wrapper Leonardo)",
                                    lambda: self.leonardo_client.generate_image(
                                        visual_prompt, w, h, negative_prompt=negative_prompt, model_name=style
                                    ),
                                    max_attempts=4,
                                    retry_on_empty=True
                                )
                                if u:
                                    image_content = self._download_binary_with_resume(u, timeout=30)
                                    if image_content:
                                        tp = os.path.join(str(media_dir), f"{fname}{unique_suffix}.jpg")
                                        with open(tp, 'wb') as f:
                                            f.write(image_content)
                                        media_path = tp
                                        image_source = 'recraft_compat_leonardo'
                                        self.log("         OK Imagen generada por Recraft AI (compat Leonardo)")
                                        generated_count += 1
                            elif use_recraft_compat_leonardo and self.recraft_client:
                                self.log("      Recraft (wrapper Leonardo) fallo, intentando Recraft directo...")
                                recraft_result = self._run_network_resilient(
                                    "fallback IA (Recraft)",
                                    lambda: self.recraft_client.generate_image(
                                        prompt=visual_prompt,
                                        style=style or "Photorealism",
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
                        if use_vertex_imagen:
                            self.log("      ERROR Vertex AI (Imagen 4 Fast) fallo")
                            self.log("      Posibles causas:")
                            self.log("         - ADC no configurado o expirado")
                            self.log("         - Billing deshabilitado en Google Cloud")
                            self.log("         - Vertex AI API sin permisos o sin cuota")
                            self.log("         - Contenido bloqueado por filtros")
                            self.log("         - Error de conexion o timeout")
                        elif use_google_ai:
                            self.log("      ❌ Google AI falló")
                            self.log("      💡 Posibles causas:")
                            self.log("         - API key inválida o sin cuota")
                            self.log("         - Modelo sin soporte de imagen")
                            self.log("         - Contenido bloqueado por filtros")
                            self.log("         - Error de conexión o timeout")
                        elif use_fal_primary:
                            self.log("      ERROR Fal.ai fallo")
                            self.log("      Posibles causas:")
                            self.log("         - FAL_KEY/FAL_API_KEY invalida o sin creditos")
                            self.log("         - SDK fal-client no disponible en el entorno")
                            self.log("         - Contenido bloqueado por filtros")
                            self.log("         - Error de conexion o timeout")
                        elif provider_key != 'manual':
                            self.log("      ❌ Recraft AI falló")
                            self.log("      💡 Posibles causas:")
                            self.log("         - API keys inválidas o sin créditos")
                            self.log("         - Contenido bloqueado por filtros")
                            self.log("         - Error de conexión o timeout")

                        if provider_key != 'manual':
                            self.log("      💡 SOLUCIÓN: Usa el modo 'Manual (Gratuito)' para generar prompts")
                            self.log("         o habilita Openverse (Gratis)/Wikimedia en las opciones")

                        # Detectar temas controvertidos en el prompt
                        controversial_keywords = ['war', 'guerra', 'battle', 'batalla', 'violence', 'violencia',
                                                 'weapon', 'arma', 'conflict', 'conflicto', 'death', 'muerte',
                                                 'crime', 'crimen', 'attack', 'ataque', 'kill', 'matar']
                        prompt_lower = visual_prompt.lower()
                        if any(keyword in prompt_lower for keyword in controversial_keywords):
                            self.log("      ⚠️ Tema sensible detectado - puede ser bloqueado por filtros")
                            self.log("      💡 Usa imágenes reales (Wikimedia/Openverse (Gratis)) o modo Manual")
            
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
                    self.log(f"      ✅ Imagen guardada: {os.path.basename(media_path)} (compartida por {group_size} segmentos)")
                else:
                    self.log(f"      ✅ Imagen guardada: {os.path.basename(media_path)}")
                
                success_count += group_size
            else:
                self.log(f"      ⚠️ No se generó imagen para el grupo: {fname}")
                # Marcar todos los segmentos del grupo como sin imagen
                for seg in segment_group:
                    seg['image_path'] = None
                failed_count += group_size
        
        # Resumen final
        self.log(f"\n✅ Generación de imágenes completada")
        self.log(f"   📊 Resumen:")
        self.log(f"      ✅ Generadas: {success_count} segmentos")
        self.log(f"      ♻️  Reutilizadas: {reused_count} segmentos")
        self.log(f"      ❌ Fallidas: {failed_count} segmentos")
        if interleave_images:
            self.log(f"      🔄 Modo intercalado: {skipped_count} segmentos quedaron vacíos para edición manual")
        if images_per_segment_ratio > 1.0:
            self.log(f"      🎯 Imágenes IA nuevas: {generated_count} (agrupación de vacíos activa)")
        
        # Si hay muchas fallas, sugerir modo manual
        if failed_count > total_segments * 0.5:  # Más del 50% fallaron
            self.log(f"\n⚠️ ADVERTENCIA: {failed_count} de {total_segments} segmentos no tienen imagen")
            self.log(f"   💡 RECOMENDACIÓN: Usa el modo 'Manual (Gratuito)' para generar prompts")
            self.log(f"      y copiarlos en servicios gratuitos como:")
            self.log(f"      • Gemini Veo (https://gemini.google.com/)")
            self.log(f"      • Bing Image Creator (https://www.bing.com/images/create)")
            self.log(f"      • Recraft AI (https://www.recraft.ai)")
            self.log(f"   📋 Selecciona 'Manual (Gratuito)' en el combo de proveedores")
        
        return storyboard_data






