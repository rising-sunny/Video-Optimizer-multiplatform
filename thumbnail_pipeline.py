import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from thumbnail_compositor import ThumbnailCompositor
from thumbnail_context_enricher import ThumbnailContextEnricher
from thumbnail_intelligence import ThumbnailIntelligence

try:
    from thumbnail_quality_validator import validate_thumbnail as _validate_thumb_quality
    _QUALITY_VALIDATOR_AVAILABLE = True
except Exception:
    _QUALITY_VALIDATOR_AVAILABLE = False


class ThumbnailPipeline:
    CURIOSITY_TOKENS = {
        "WHAT", "WHY", "HOW", "WHO", "SECRET", "HIDDEN", "CLASSIFIED", "UNKNOWN",
        "MYSTERY", "FILES", "SIGNAL", "COVERUP", "COVER", "SANK", "INCIDENT",
        "CARGO", "TRUTH", "MOVE", "TRANSFER", "INSIDE", "SILENCE", "DEADLY",
        "HIT", "MISSING", "BURIED", "EXPOSED", "SEA", "SILENT", "EXPLODED",
        "BLAST", "COSMIC", "IMPACT", "FIREBALL", "TSUNAMI", "QUAKE",
        "SHOOK", "FAULT", "MEGA", "MINUTES", "VOLCANO", "ERUPTION",
    }
    GENERIC_TOKENS = {
        "VIDEO", "STORY", "HISTORY", "DOCUMENTARY", "ANALYSIS", "REPORT",
        "PROJECT", "OPERATION", "TIMELINE", "SUMMARY",
    }
    WEAK_SINGLE_WORD_HOOKS = {"MYSTERY", "SECRET", "TRUTH", "ANCIENT", "UNKNOWN", "INVASION", "UNCOVER"}
    PROFILE_SCORING = {
        "geopolitical_secret": {
            "preferred_palette": "danger_yellow_black",
            "preferred_compositions": [
                "subject_left_text_right",
                "subject_right_text_left",
                "text_top_center",
            ],
            "boost_tokens": {"SECRET", "CARGO", "CLASSIFIED", "TRANSFER", "HIDDEN"},
            "avoid_tokens": {"STORY", "HISTORY"},
        },
        "military_coverup": {
            "preferred_palette": "cold_blue_red",
            "preferred_compositions": [
                "subject_left_text_right",
                "subject_right_text_left",
                "text_top_center",
            ],
            "boost_tokens": {"SANK", "SEA", "DEADLY", "SILENCE", "COVER", "WHAT"},
            "avoid_tokens": {"FILES", "STORY"},
        },
        "science_incident": {
            "preferred_palette": "orange_cyan",
            "preferred_compositions": [
                "text_top_center",
                "subject_left_text_right",
                "subject_right_text_left",
            ],
            "boost_tokens": {"UNKNOWN", "SIGNAL", "INCIDENT", "HIT", "EXPOSED", "EXPLODED", "BLAST", "COSMIC", "IMPACT", "FIREBALL"},
            "avoid_tokens": {"HISTORY", "REPORT", "SEA", "SANK", "CARGO"},
        },
        "natural_disaster": {
            "preferred_palette": "cold_blue_red",
            "preferred_compositions": [
                "subject_left_text_right",
                "subject_right_text_left",
                "text_top_center",
            ],
            "boost_tokens": {"TSUNAMI", "QUAKE", "SHOOK", "FAULT", "MINUTES", "MEGA", "VOLCANO", "ERUPTION"},
            "avoid_tokens": {"SECRET", "CARGO", "FILES", "ORDER", "CLASSIFIED"},
        },
        "historical_revelation": {
            "preferred_palette": "orange_cyan",
            "preferred_compositions": [
                "subject_right_text_left",
                "text_top_center",
                "subject_left_text_right",
            ],
            "boost_tokens": {"HIDDEN", "BURIED", "FILES", "TRUTH", "LOST"},
            "avoid_tokens": {"INCIDENT", "SIGNAL"},
        },
        "political_conspiracy": {
            "preferred_palette": "danger_yellow_black",
            "preferred_compositions": [
                "subject_left_text_right",
                "subject_right_text_left",
                "text_top_center",
            ],
            "boost_tokens": {"SECRET", "ORDER", "WHO", "KNEW", "CLOSED", "DOORS"},
            "avoid_tokens": {"HISTORY", "DOCUMENTARY"},
        },
        "ancient_collapse": {
            "preferred_palette": "orange_cyan",
            "preferred_compositions": [
                "subject_left_text_right",
                "subject_right_text_left",
                "text_top_center",
            ],
            "boost_tokens": {"SEA", "WHO", "LOST", "RUIN", "INVADERS"},
            "avoid_tokens": {"REPORT", "SUMMARY"},
        },
        "general_mystery": {
            "preferred_palette": "danger_yellow_black",
            "preferred_compositions": [
                "subject_left_text_right",
                "text_top_center",
                "subject_right_text_left",
            ],
            "boost_tokens": {"HIDDEN", "SECRET", "WHAT", "UNKNOWN"},
            "avoid_tokens": {"SUMMARY", "REPORT"},
        },
    }
    COMMON_NEGATIVE_TERMS = [
        "text overlay",
        "garbled letters",
        "misspelled words",
        "watermark",
        "signature",
        "logo",
        "subtitle burn-in",
        "tiny distant subject",
        "busy collage",
        "flat lighting",
        "studio portrait",
        "stock photo look",
        "muddy colors",
        "over-smoothed skin",
        "plastic CGI look",
        "cartoon style",
        "anime",
        "chibi",
        "cute",
        "deformed anatomy",
        "extra fingers",
        "extra limbs",
        "duplicate faces",
        "symmetrical boring composition",
        "centered face no negative space",
        "low contrast washed out",
        "pastel colors",
        "neon colors",
        "pure saturated red",
        "modern clothing in historical scene",
        "wristwatch",
        "smartphone",
        "plastic props",
        "dark underexposed image",
        "blown out highlights",
    ]

    # Super-prompt: reglas de composicion cuantitativas inyectadas en CADA
    # prompt de thumbnail 16:9. Derivadas de mediciones reales sobre canales
    # con CTR >5% vs canales estancados. Ver thumbnail_quality_validator.py
    # para los umbrales objetivo que estas reglas buscan satisfacer.
    SUPER_PROMPT_COMPOSITION_RULES = [
        # Regla de tercios y ubicacion de sujeto
        "rule of thirds composition, dominant subject anchored in the LEFT third of the frame (x 0-33%), face or focal action occupying ~35-45% of image height",
        "subject eyes slightly above the horizontal midline, direct eye contact with viewer or looking off-frame toward the emotional hook",
        "upper-right third kept visually calm (sky, smoke, dust, darkness) as negative space for a later text overlay",
        # Luminancia y contraste (targets cuantitativos)
        "overall mean luminance in the 100-150 range (never dark underexposed, never washed out)",
        "LEFT third clearly brighter than the RIGHT third by ~20+ luminance points: warm key light on the subject, cooler and darker background on the right",
        "at least 55% of visible fine detail and high-contrast edges concentrated in the LEFT third (the subject lives there)",
        # Paleta dirigida (warm dominance)
        "warm dominant palette: burnt orange, amber, sepia, firelight tones (#6b4a2e to #c0562a range), cool desaturated teal or charcoal only as background counter",
        "average red channel stronger than average blue channel by 15+ points (warm temperature signature)",
        "high tonal range: no single luminance bin over 25% of pixels, real deep shadows and real highlights",
        # Iluminacion cinematografica
        "cinematic three-point lighting: warm rim light on subject (sunset, firelight, oil lamp, explosion glow), cool ambient background, atmospheric haze or smoke for depth",
        "shallow depth of field, foreground subject sharp, midground softly blurred, background with volumetric haze",
        # Emocion visible
        "readable emotion on the central figure: dilated pupils, tense jaw, sweat, dust on face, 1000-yard stare or mid-gasp expression",
        # Era y realismo
        "photoreal cinematic style, 50mm lens look, subtle film grain, not AI-smooth, not plastic, not digital painting",
        "every visible element (weapons, uniforms, props, architecture) strictly period-accurate to the story era; zero anachronisms",
    ]

    def __init__(
        self,
        project_root: str,
        llm_client=None,
        recraft_client=None,
        google_ai_image_client=None,
        vertex_imagen_client=None,
        fal_client=None,
        comfyui_image_client=None,
        google_images_client=None,
        wikimedia_client=None,
        log_callback=None,
    ):
        self.project_root = Path(project_root)
        self.raw_dir = self.project_root / "thumbnails" / "raw"
        self.final_dir = self.project_root / "thumbnails" / "final"
        self.log = log_callback or (lambda _msg: None)
        self.llm_client = llm_client
        self.intelligence = ThumbnailIntelligence(llm_client=llm_client, log_callback=self.log)
        self.context_enricher = ThumbnailContextEnricher(
            llm_client=llm_client,
            wikimedia_client=wikimedia_client,
            google_images_client=google_images_client,
            log_callback=self.log,
        )
        self.compositor = ThumbnailCompositor(log_callback=self.log)
        self.recraft_client = recraft_client
        self.google_ai_image_client = google_ai_image_client
        self.vertex_imagen_client = vertex_imagen_client
        self.fal_client = fal_client
        self.comfyui_image_client = comfyui_image_client

    def generate_for_project(self, project_data: Dict[str, Any], style_hint: Optional[str] = None) -> Dict[str, Any]:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.final_dir.mkdir(parents=True, exist_ok=True)

        if not self.llm_client or not hasattr(self.llm_client, "_generate"):
            raise RuntimeError("Groq no está disponible para analizar miniaturas hook.")
        has_image_provider = any(
            client and hasattr(client, "generate_image")
            for client in (
                self.recraft_client,
                self.google_ai_image_client,
                self.fal_client,
                self.comfyui_image_client,
            )
        )
        if not has_image_provider:
            raise RuntimeError("No hay proveedor disponible para generar miniaturas hook.")

        enriched_context = self.context_enricher.enrich_context(project_data, style_hint=style_hint)
        strategy = self.intelligence.generate_strategy(
            project_data,
            style_hint=style_hint,
            enriched_context=enriched_context,
        )
        timestamp = int(time.time())
        variants = []

        for index, recipe in enumerate(strategy.get("variant_recipes", [])[:3]):
            hook_candidates = strategy.get("hook_candidates") or [strategy.get("selected_hook") or "THE SECRET"]
            hook_text = hook_candidates[min(index, len(hook_candidates) - 1)]
            raw_path = self.raw_dir / f"thumb_{timestamp}_{recipe['id']}_raw.png"
            final_path = self.final_dir / f"thumb_{timestamp}_{recipe['id']}_final.png"
            prompt = self._build_prompt(strategy, recipe)
            negative_prompt = self._build_negative_prompt(strategy)

            generated_base, provider = self._generate_base_image(
                prompt=prompt,
                output_path=raw_path,
                render_mode=strategy.get("render_mode", "realistic_image"),
                subject_hint=strategy.get("impact_subject", ""),
                palette=strategy.get("palette", "danger_yellow_black"),
                negative_prompt=negative_prompt,
                quality_tier=strategy.get("quality_tier", "epic_cinematic"),
                recraft_style=style_hint,
                reference_images=strategy.get("reference_images") or [],
            )
            self.compositor.compose_thumbnail(
                base_image_path=str(generated_base),
                output_path=str(final_path),
                hook_text=hook_text,
                palette_name=strategy.get("palette", "danger_yellow_black"),
                composition=recipe.get("composition", "subject_left_text_right"),
                kicker_text=self._build_kicker_text(strategy),
                quality_tier=strategy.get("quality_tier", "epic_cinematic"),
            )

            # Validacion cuantitativa post-generacion (luminancia, tercios,
            # paleta, histograma). El score alimenta _select_best_variant
            # para priorizar miniaturas que realmente cumplen los targets
            # de alto CTR, no solo la que tiene el mejor hook textual.
            quality_report = self._evaluate_variant_quality(final_path)

            variants.append(
                {
                    "id": recipe.get("id"),
                    "label": recipe.get("label"),
                    "composition": recipe.get("composition"),
                    "hook_text": hook_text,
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "path": str(final_path),
                    "raw_path": str(generated_base),
                    "provider": provider,
                    "quality_report": quality_report,
                }
            )

        selected_variant = self._select_best_variant(variants, strategy)
        recommended_variant_id = selected_variant["id"] if selected_variant else None
        recommended_reason = " | ".join((selected_variant or {}).get("selection_reasons", [])[:3]) if selected_variant else ""

        for variant in variants:
            variant["is_recommended"] = bool(recommended_variant_id and variant.get("id") == recommended_variant_id)

        if selected_variant:
            strategy["selected_hook"] = selected_variant.get("hook_text") or strategy.get("selected_hook")

        return {
            "thumbnail_path": selected_variant["path"] if selected_variant else None,
            "selected_variant_id": selected_variant["id"] if selected_variant else None,
            "recommended_variant_id": recommended_variant_id,
            "recommended_thumbnail_path": selected_variant["path"] if selected_variant else None,
            "recommended_reason": recommended_reason,
            "thumbnail_strategy": strategy,
            "thumbnail_enrichment": enriched_context,
            "thumbnail_variants": variants,
            "generated_at": timestamp,
        }

    def _select_best_variant(self, variants: List[Dict[str, Any]], strategy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not variants:
            return None

        selected_hook = str(strategy.get("selected_hook") or "").strip().upper()
        best_variant = None
        best_score = None

        for variant in variants:
            score, reasons = self._score_variant(variant, strategy, selected_hook=selected_hook)
            variant["selection_score"] = score
            variant["selection_reasons"] = reasons

            if best_variant is None or score > best_score:
                best_variant = variant
                best_score = score

        if best_variant:
            self.log(
                f"Recommended thumbnail variant: {best_variant.get('label', best_variant.get('id', 'N/A'))} "
                f"(score {best_variant.get('selection_score', 0):.1f})"
            )
        return best_variant

    def _score_variant(
        self,
        variant: Dict[str, Any],
        strategy: Dict[str, Any],
        selected_hook: str,
    ) -> Tuple[float, List[str]]:
        hook_text = str(variant.get("hook_text") or "").strip().upper()
        composition = str(variant.get("composition") or "").strip().lower()
        hook_tokens = self._tokenize(hook_text)
        topic_tokens = self._tokenize(strategy.get("topic"))
        mystery_tokens = self._tokenize(strategy.get("mystery_concept"))
        profile_key = str(strategy.get("niche_profile") or "general_mystery").strip().lower()
        profile_scoring = self.PROFILE_SCORING.get(profile_key, self.PROFILE_SCORING["general_mystery"])
        preferred_compositions = list(
            strategy.get("preferred_compositions") or profile_scoring.get("preferred_compositions") or []
        )

        score = 0.0
        reasons: List[str] = []
        word_count = len(hook_tokens)
        char_count = len(hook_text.replace(" ", ""))

        if word_count == 2:
            score += 24
            reasons.append("hook de 2 palabras: muy legible")
        elif word_count == 3:
            score += 22
            reasons.append("hook de 3 palabras: buen curiosity gap")
        elif word_count == 1:
            score += 10
            reasons.append("hook de 1 palabra: impacto inmediato")
        else:
            penalty = 12 * abs(word_count - 3)
            score -= penalty
            reasons.append("hook demasiado largo para feed")

        if 8 <= char_count <= 18:
            score += 10
            reasons.append("longitud visual compacta")
        elif 5 <= char_count <= 24:
            score += 5

        curiosity_hits = sorted({token for token in hook_tokens if token in self.CURIOSITY_TOKENS})
        if curiosity_hits:
            curiosity_score = min(18, 6 * len(curiosity_hits))
            score += curiosity_score
            reasons.append(f"alto curiosity gap ({', '.join(curiosity_hits[:2]).lower()})")

        generic_hits = [token for token in hook_tokens if token in self.GENERIC_TOKENS]
        if generic_hits:
            score -= min(8, 4 * len(set(generic_hits)))
            reasons.append("hook demasiado descriptivo/generico")

        if word_count == 1 and hook_tokens and hook_tokens[0] in self.WEAK_SINGLE_WORD_HOOKS:
            score -= 14
            reasons.append("hook demasiado generico para thumbnail premium")

        profile_hits = sorted({token for token in hook_tokens if token in set(profile_scoring.get("boost_tokens") or set())})
        if profile_hits:
            profile_score = min(12, 4 * len(profile_hits))
            score += profile_score
            reasons.append(f"encaja con perfil {profile_key.replace('_', ' ')}")

        profile_avoid = sorted({token for token in hook_tokens if token in set(profile_scoring.get("avoid_tokens") or set())})
        if profile_avoid:
            score -= min(10, 5 * len(profile_avoid))
            reasons.append("hook poco alineado con el nicho")

        if hook_text.endswith("?") or hook_tokens[:1] and hook_tokens[0] in {"WHAT", "WHY", "HOW", "WHO"}:
            score += 5
            reasons.append("abre una pregunta implicita")

        if selected_hook and hook_text == selected_hook:
            score += 12
            reasons.append("coincide con el hook principal del brief")

        concept_overlap = (set(hook_tokens) & set(mystery_tokens)) - {"THE", "A", "AN"}
        if concept_overlap:
            score += min(8, 4 * len(concept_overlap))
            reasons.append("ancla bien el concepto de misterio")

        topic_overlap = (set(hook_tokens) & set(topic_tokens)) - {"THE", "A", "AN"}
        if topic_overlap:
            score += min(4, 2 * len(topic_overlap))

        if composition in preferred_compositions:
            composition_rank = preferred_compositions.index(composition)
            composition_bonus = max(4, 10 - (composition_rank * 3))
            score += composition_bonus
            reasons.append(f"composicion alineada al perfil {profile_key.replace('_', ' ')}")

        if composition in {"subject_left_text_right", "subject_right_text_left"}:
            score += 14
            reasons.append("composicion lateral ideal para thumbnail")
            if composition == "subject_left_text_right":
                score += 2
        elif composition == "text_top_center":
            score += 7
            reasons.append("composicion centrada usable pero menos fuerte")
            if word_count >= 3:
                score -= 2
        else:
            score += 3

        palette = str(strategy.get("palette") or "").strip().lower()
        if palette in {"danger_yellow_black", "orange_cyan", "cold_blue_red"}:
            score += 4
        if palette and palette == str(profile_scoring.get("preferred_palette") or "").strip().lower():
            score += 6
            reasons.append("paleta correcta para el nicho")

        provider = str(variant.get("provider") or "").strip().lower()
        if provider in {"vertex_imagen", "google_ai", "recraft"}:
            score += 4

        # Bonus cuantitativo: score tecnico del validador de pixels.
        # Peso alto (hasta +30) porque si la miniatura falla los targets
        # de luminancia/composicion, ningun hook textual la salva.
        quality_report = variant.get("quality_report") or {}
        q_score = float(quality_report.get("total_score") or 0.0)
        if q_score > 0:
            quality_bonus = (q_score / 100.0) * 30.0
            score += quality_bonus
            verdict = quality_report.get("verdict", "unknown")
            if verdict == "excellent":
                reasons.append(f"calidad visual excelente ({q_score:.0f}/100)")
            elif verdict == "good":
                reasons.append(f"calidad visual buena ({q_score:.0f}/100)")
            elif verdict == "weak":
                reasons.append(f"calidad visual debil ({q_score:.0f}/100)")
            elif verdict == "poor":
                reasons.append(f"calidad visual pobre ({q_score:.0f}/100)")
                score -= 10  # penalizacion extra

        return score, reasons

    def _tokenize(self, text: Any) -> List[str]:
        clean = re.sub(r"[^A-Za-z0-9?!. ]+", " ", str(text or "").upper())
        return [token for token in clean.split() if token]

    def _evaluate_variant_quality(self, image_path: Path) -> Dict[str, Any]:
        """Corre el validador cuantitativo sobre una miniatura ya compuesta.

        Devuelve un dict con 'total_score' 0-100, 'verdict', 'passes' y
        'suggestions'. Si el validador no esta disponible o la imagen no
        existe, devuelve un dict neutro con score=0 y verdict='unknown'
        (no se rompe el pipeline). El score es usado como bonus en
        _score_variant para priorizar miniaturas que cumplen los targets.
        """
        if not _QUALITY_VALIDATOR_AVAILABLE:
            return {"total_score": 0.0, "verdict": "unknown", "passes": {}, "suggestions": []}
        try:
            path_str = str(image_path)
            if not Path(path_str).is_file():
                return {"total_score": 0.0, "verdict": "missing", "passes": {}, "suggestions": []}
            report = _validate_thumb_quality(path_str)
            verdict = report.get("verdict", "unknown")
            score = float(report.get("total_score", 0.0))
            self.log(
                f"Thumbnail quality score: {score:.1f}/100 ({verdict}) "
                f"[{report.get('passed_count', 0)}/{report.get('total_checks', 0)} checks]"
            )
            suggestions = report.get("suggestions") or []
            if suggestions and verdict in ("weak", "poor"):
                for s in suggestions[:3]:
                    self.log(f"  -> {s}")
            return {
                "total_score": score,
                "verdict": verdict,
                "passes": report.get("passes", {}),
                "metrics": report.get("metrics", {}),
                "suggestions": suggestions,
            }
        except Exception as e:
            self.log(f"[quality] validacion de thumbnail fallo: {e}")
            return {"total_score": 0.0, "verdict": "error", "passes": {}, "suggestions": []}

    def _build_prompt(self, strategy: Dict[str, Any], recipe: Dict[str, Any]) -> str:
        parts = []
        # 1. Contexto de la historia y sujeto
        for item in (
            strategy.get("base_prompt"),
            f"literal scene anchor: {strategy.get('selected_scene_prompt')}" if strategy.get("selected_scene_prompt") else "",
            f"hero subject: {strategy.get('hero_subject')}" if strategy.get("hero_subject") else "",
            f"hero frame: {strategy.get('hero_frame')}" if strategy.get("hero_frame") else "",
            self._list_clause("visual motifs", strategy.get("visual_motifs")),
            self._list_clause("wow directives", strategy.get("wow_directives")),
            self._reference_clause(strategy.get("reference_images")),
            self._list_clause("reference anchors", strategy.get("reference_queries")),
            strategy.get("web_summary"),
            recipe.get("prompt_suffix"),
        ):
            clean = str(item or "").strip()
            if clean:
                parts.append(clean)

        # 2. Super-prompt: reglas de composicion cuantitativas (CTR-optimized).
        # Estas reglas son las mismas que valida thumbnail_quality_validator.py
        # post-generacion, asi que el modelo y el validador estan alineados.
        parts.extend(self.SUPER_PROMPT_COMPOSITION_RULES)

        # 3. Constraints finales (formato + prohibiciones hard)
        parts.extend([
            "horizontal 16:9 YouTube thumbnail, 1920x1080",
            "high-end browse image with one dominant subject and clear negative space in the upper right",
            "must visibly show topic-specific iconography or action from the story",
            "no text inside the image, no watermark, no logo, no subtitles (text is added in post-production)",
        ])
        return ", ".join(parts)

    def _build_negative_prompt(self, strategy: Dict[str, Any]) -> str:
        negatives = []
        for term in self.COMMON_NEGATIVE_TERMS:
            if term not in negatives:
                negatives.append(term)
        for term in strategy.get("negative_constraints") or []:
            clean = str(term or "").strip()
            if clean and clean not in negatives:
                negatives.append(clean)
        for term in ("generic landscape only", "empty scenery without topic anchors"):
            if term not in negatives:
                negatives.append(term)
        return ", ".join(negatives)

    def _generate_base_image(
        self,
        prompt: str,
        output_path: Path,
        render_mode: str,
        subject_hint: str,
        palette: str,
        negative_prompt: str,
        quality_tier: str,
        recraft_style: Optional[str],
        reference_images: List[Dict[str, Any]],
    ) -> Tuple[Path, str]:
        del subject_hint, reference_images

        selected_style = str(
            recraft_style
            or ("Photorealism" if str(render_mode or "").strip().lower() == "realistic_image" else "Illustration")
        ).strip()

        style_hint = self._provider_style_hint(render_mode, quality_tier, palette)
        for provider_name in self._build_provider_order(render_mode, quality_tier):
            candidate = self._try_generate_with_provider(
                provider_name=provider_name,
                prompt=prompt,
                output_path=output_path,
                negative_prompt=negative_prompt,
                style_hint=selected_style or style_hint,
            )
            if candidate and Path(candidate).exists():
                self.log(f"Thumbnail base generated with {provider_name}: {Path(candidate).name}")
                return Path(candidate), provider_name

        raise RuntimeError("Ningun proveedor devolvio una imagen valida para miniaturas hook.")

    def _build_provider_order(self, render_mode: str, quality_tier: str) -> List[str]:
        render_mode = str(render_mode or "").strip().lower()
        quality_tier = str(quality_tier or "").strip().lower()

        if render_mode == "digital_illustration":
            return ["recraft", "google_ai", "fal", "comfy_schnell"]

        if any(token in quality_tier for token in ("epic", "premium", "max", "ultra")):
            return ["google_ai", "recraft", "fal", "comfy_schnell"]

        return ["recraft", "google_ai", "fal", "comfy_schnell"]

    def _provider_style_hint(self, render_mode: str, quality_tier: str, palette: str) -> str:
        style_parts = []
        if render_mode == "digital_illustration":
            style_parts.append("premium cinematic illustration")
        else:
            style_parts.append("photorealistic cinematic still")

        if palette == "orange_cyan":
            style_parts.append("warm orange vs cool cyan split tone")
        elif palette == "cold_blue_red":
            style_parts.append("cold blue with emergency red accents")
        else:
            style_parts.append("danger yellow with deep black contrast")

        if quality_tier:
            style_parts.append(str(quality_tier).replace("_", " "))
        return ", ".join(style_parts)

    def _try_generate_with_provider(
        self,
        provider_name: str,
        prompt: str,
        output_path: Path,
        negative_prompt: str,
        style_hint: str,
    ) -> Optional[Path]:
        if provider_name == "google_ai" and self.google_ai_image_client:
            image_bytes = self.google_ai_image_client.generate_image(
                prompt=prompt,
                width=1280,
                height=720,
                negative_prompt=negative_prompt,
                style=style_hint,
            )
            return self._write_image_bytes(image_bytes, output_path)

        if provider_name == "recraft" and self.recraft_client and hasattr(self.recraft_client, "generate_image"):
            result = self.recraft_client.generate_image(
                prompt=prompt,
                style="realistic_image" if "photo" in style_hint or "realistic" in style_hint else "digital_illustration",
                width=1280,
                height=720,
                negative_prompt=negative_prompt,
                output_path=str(output_path),
            )
            if isinstance(result, dict):
                path_value = result.get("path")
                if path_value and Path(path_value).exists():
                    return Path(path_value)
                if result.get("url"):
                    return self._download_image(result["url"], output_path)
            elif isinstance(result, str):
                if result.startswith(("http://", "https://")):
                    return self._download_image(result, output_path)
                if Path(result).exists():
                    return Path(result)
            return None

        if provider_name == "fal" and self.fal_client and hasattr(self.fal_client, "generate_image"):
            result = self.fal_client.generate_image(
                prompt=prompt,
                width=1280,
                height=720,
                negative_prompt=negative_prompt,
                style=style_hint,
            )
            if isinstance(result, str) and result.startswith(("http://", "https://")):
                return self._download_image(result, output_path)

        if provider_name == "comfy_schnell" and self.comfyui_image_client and hasattr(self.comfyui_image_client, "generate_image"):
            result = self.comfyui_image_client.generate_image(
                prompt=prompt,
                width=1280,
                height=720,
                output_path=str(output_path),
                negative_prompt=negative_prompt,
                style=style_hint,
                preset="thumbnail_16x9_schnell",
            )
            if isinstance(result, str) and Path(result).exists():
                return Path(result)

        return None

    def _write_image_bytes(self, image_bytes: Optional[bytes], output_path: Path) -> Optional[Path]:
        if not image_bytes:
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return output_path

    def _download_reference_image(self, reference_images: List[Dict[str, Any]], output_path: Path) -> Optional[Path]:
        for item in reference_images or []:
            for url in (item.get("thumbnail"), item.get("url"), item.get("context")):
                if not url:
                    continue
                downloaded = self._download_image(str(url), output_path)
                if downloaded and downloaded.exists():
                    return downloaded
        return None

    def _download_image(self, url: str, output_path: Path) -> Optional[Path]:
        try:
            response = requests.get(url, timeout=45)
            response.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
            return output_path
        except Exception as exc:
            self.log(f"Could not download thumbnail image: {exc}")
            return None

    def _list_clause(self, label: str, values: Any) -> str:
        if not isinstance(values, list):
            return ""
        cleaned = [str(item or "").strip() for item in values if str(item or "").strip()]
        if not cleaned:
            return ""
        return f"{label}: {', '.join(cleaned[:4])}"

    def _reference_clause(self, reference_images: Any) -> str:
        if not isinstance(reference_images, list):
            return ""
        titles = []
        for item in reference_images[:3]:
            title = str((item or {}).get("title") or "").strip()
            if title and title not in titles:
                titles.append(title)
        if not titles:
            return ""
        return f"reference visual anchors: {', '.join(titles)}"

    def _build_kicker_text(self, strategy: Dict[str, Any]) -> str:
        profile_labels = {
            "ancient_collapse": "BRONZE AGE",
            "military_coverup": "NAVAL COVER-UP",
            "geopolitical_secret": "CLASSIFIED MOVE",
            "science_incident": "UNEXPLAINED EVENT",
            "historical_revelation": "BURIED HISTORY",
            "political_conspiracy": "CLOSED DOORS",
        }

        profile_key = str(strategy.get("niche_profile") or "").strip().lower()
        concept = str(strategy.get("mystery_concept") or "").strip()
        tokens = [
            token.upper()
            for token in re.findall(r"[A-Za-z0-9']+", concept)
            if token.lower() not in {"the", "from", "with", "that", "this", "your", "and", "for", "into"}
        ]
        candidate = " ".join(tokens[:3]).strip()

        if 6 <= len(candidate) <= 24:
            return candidate
        if profile_key in profile_labels:
            return profile_labels[profile_key]
        return str(strategy.get("niche_label") or "").upper()[:24]
