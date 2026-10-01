import json
import re
from typing import Any, Dict, List, Optional
from thumbnail_formats import LANDSCAPE_16_9, resolve_format

try:
    from ai.research_search import RESEARCH_AVAILABLE, search_research_context
except Exception:
    RESEARCH_AVAILABLE = False
    search_research_context = None

try:
    from channel.trend_spotter import get_trending_topics
except Exception:
    get_trending_topics = None


class ThumbnailContextEnricher:
    """Collects optional web/research context for higher-intent thumbnail briefs."""

    GENERIC_TREND_TOKENS = {
        "news", "today", "trending", "trend", "report", "viral", "instagram",
        "cultural", "culture", "entertainment", "topics", "revista", "pop",
    }

    def __init__(
        self,
        llm_client=None,
        wikimedia_client=None,
        google_images_client=None,
        log_callback=None,
    ):
        self.llm_client = llm_client
        self.wikimedia_client = wikimedia_client
        self.google_images_client = google_images_client
        self.log = log_callback or (lambda _msg: None)

    def enrich_context(self, project_data: Dict[str, Any], style_hint: Optional[str] = None,
                       thumbnail_format=None) -> Dict[str, Any]:
        # El formato decide el encuadre que se le pide al LLM. Se guarda
        # en el objeto para no arrastrarlo por las tres capas de firmas
        # que hay hasta el prompt.
        self.format = thumbnail_format or resolve_format(project_data=project_data)
        context = self._extract_context(project_data)
        if not self.llm_client or not hasattr(self.llm_client, "_generate"):
            raise RuntimeError("Groq no está disponible para el análisis de miniaturas hook.")

        research_snippets: List[str] = []
        trend_signals: List[str] = []
        reference_queries: List[str] = []
        visual_references: List[Dict[str, Any]] = []
        selected_scene = None
        synthesis = self._synthesize_context(
            context=context,
            research_snippets=research_snippets,
            trend_signals=trend_signals,
            visual_references=visual_references,
            reference_queries=reference_queries,
            selected_scene=selected_scene,
            style_hint=style_hint,
        )

        if not synthesis:
            # `_fallback_synthesis` estaba escrito y no se llamaba desde
            # ningun lado: se prefiere un brief degradado a no tener
            # miniatura. Se avisa fuerte para que no pase inadvertido.
            self.log("[FALLBACK] El LLM no dio un brief usable; se arma uno "
                     "desde la investigacion y el storyboard.")
            synthesis = self._fallback_synthesis(
                context=context,
                research_snippets=research_snippets,
                trend_signals=trend_signals,
                visual_references=visual_references,
                reference_queries=reference_queries,
                selected_scene=selected_scene,
            )

        return {
            "context_topic": context.get("topic"),
            "context_category": context.get("category"),
            "region": context.get("region"),
            "storyboard_scene_candidates": list(context.get("scene_candidates") or []),
            "selected_scene_prompt": synthesis.get("selected_scene_prompt") or "",
            "selected_scene_text": "",
            "research_snippets": research_snippets,
            "trend_signals": trend_signals,
            "reference_queries": list(synthesis.get("reference_queries") or []),
            "visual_references": visual_references,
            **synthesis,
        }

    def _extract_context(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        config = project_data.get("config", {}) or {}
        storyboard = project_data.get("storyboard", {}) or {}
        segments = project_data.get("segments") or storyboard.get("segments") or []

        topic = (
            config.get("topic")
            or storyboard.get("topic")
            or project_data.get("topic")
            or project_data.get("title")
            or "Untold mystery"
        )
        category = (
            config.get("category")
            or storyboard.get("category")
            or project_data.get("category")
            or "Mystery"
        )
        language = str(config.get("language") or project_data.get("language") or "en").strip().lower()
        duration = int(config.get("duration") or project_data.get("duration") or 0)
        script = str(storyboard.get("script") or project_data.get("script") or "").strip()

        if not script and segments:
            script_parts = []
            for segment in segments[:12]:
                text = (
                    segment.get("text")
                    or segment.get("narration")
                    or segment.get("script")
                    or ""
                ).strip()
                if text:
                    script_parts.append(text)
            script = " ".join(script_parts)

        region = (
            str(config.get("target_region") or project_data.get("target_region") or "").strip().upper()
            or ("US" if language == "en" else "ES")
        )

        return {
            "topic": str(topic).strip(),
            "category": str(category).strip(),
            "language": language,
            "duration": duration,
            "script": script,
            "script_excerpt": script[:1800],
            "region": region,
            "scene_candidates": self._extract_storyboard_scene_candidates(
                segments=segments,
                topic=str(topic).strip(),
                category=str(category).strip(),
                script=str(script or "").strip(),
            ),
        }

    def _combined_context_text(self, context: Dict[str, Any]) -> str:
        return " ".join(
            str(context.get(key) or "")
            for key in ("topic", "category", "script", "script_excerpt")
        )

    def _is_natural_disaster_context(self, text: Any) -> bool:
        return any(
            self._contains_phrase(text, token)
            for token in (
                "earthquake", "terremoto", "quake", "tsunami", "magnitude",
                "richter", "epicenter", "epicentre", "aftershock", "seismic",
                "fault line", "fault", "landslide", "volcano", "volcanic",
                "eruption", "valdivia", "puyehue",
            )
        )

    def _natural_disaster_hooks(self, text: Any) -> List[str]:
        normalized = re.sub(r"\s+", " ", str(text or "").lower()).strip()
        hooks: List[str] = []

        minute_match = re.search(r"\b(\d{1,2})\s+(?:full\s+)?minutes?\b", normalized)
        if minute_match:
            minutes = int(minute_match.group(1))
            if 2 <= minutes <= 20:
                hooks.append(f"{minutes} MINUTES")

        if any(self._contains_phrase(normalized, token) for token in ("tsunami", "wave", "pacific ocean")):
            hooks.append("MEGA TSUNAMI")

        if any(self._contains_phrase(normalized, token) for token in ("volcano", "volcanic", "eruption", "ash cloud")):
            hooks.append("VOLCANO AWOKE")

        if any(
            self._contains_phrase(normalized, token)
            for token in ("earthquake", "quake", "seismic", "fault line", "magnitude", "epicenter", "aftershock")
        ):
            hooks.append("WORLD SHOOK")
            hooks.append("FAULT LINE")

        deduped: List[str] = []
        for hook in hooks:
            clean = str(hook or "").strip().upper()
            if clean and clean not in deduped:
                deduped.append(clean)
        return deduped[:3] or ["WORLD SHOOK", "MEGA QUAKE", "FAULT LINE"]

    # Cuando ningun keyword matchea, el perfil generico del canal. NO
    # 'general_mystery': el Channel Bible del canal nuevo pone los misterios
    # fuera de alcance, y ese perfil arrastra paleta y hooks de conspiracion.
    DEFAULT_NICHE_PROFILE = "historical_revelation"

    def _safe_profile_for_context(self, context: Dict[str, Any]) -> str:
        """Perfil de nicho que nunca viene vacio.

        `_fallback_profile_for_context` devuelve "" cuando no reconoce el tema,
        y su lista de keywords es toda del canal anterior (submarinos, meteoros,
        Sea Peoples). Un tema como 'Nan Madol' no matchea nada, y ese "" se
        colaba tal cual en el brief.
        """
        return self._fallback_profile_for_context(context) or self.DEFAULT_NICHE_PROFILE

    def _fallback_profile_for_context(self, context: Dict[str, Any]) -> str:
        combined = self._combined_context_text(context)
        if self._is_natural_disaster_context(combined):
            return "natural_disaster"
        if any(self._contains_phrase(combined, token) for token in ("bronze age", "sea peoples", "sea people", "ugarit", "hittite")):
            return "ancient_collapse"
        if any(
            self._contains_phrase(combined, token)
            for token in ("tunguska", "meteor", "asteroid", "comet", "fireball", "impact", "explosion", "blast", "cosmic", "airburst")
        ):
            return "science_incident"
        if any(self._contains_phrase(combined, token) for token in ("submarine", "kursk", "barents", "navy", "torpedo", "missile", "naval")):
            return "military_coverup"
        return ""

    def _sanitize_reference_queries(self, context: Dict[str, Any], queries: List[str]) -> List[str]:
        cleaned: List[str] = []
        for query in queries or []:
            text = self._simplify_query(query)
            if text and text not in cleaned:
                cleaned.append(text)

        if not self._is_natural_disaster_context(self._combined_context_text(context)):
            return cleaned[:5]

        blocked_terms = (
            "classified", "cargo", "uranium", "nuclear", "shipment",
            "transfer", "weapon", "airport", "military",
        )
        filtered = [
            query for query in cleaned
            if not any(self._contains_phrase(query, blocked) for blocked in blocked_terms)
        ]
        if filtered:
            return filtered[:5]
        return self._topic_specific_reference_queries(context)[:5] or cleaned[:5]


    def _synthesize_context(
        self,
        context: Dict[str, Any],
        research_snippets: List[str],
        trend_signals: List[str],
        visual_references: List[Dict[str, Any]],
        reference_queries: List[str],
        selected_scene: Optional[Dict[str, Any]],
        style_hint: Optional[str],
    ) -> Dict[str, Any]:
        llm_synthesis = self._synthesize_with_llm(
            context=context,
            research_snippets=research_snippets,
            trend_signals=trend_signals,
            visual_references=visual_references,
            reference_queries=reference_queries,
            selected_scene=selected_scene,
            style_hint=style_hint,
        )
        if llm_synthesis:
            return llm_synthesis
        self.log("[FALLBACK] Enrichment del LLM descartado; sigue con el de respaldo.")
        return None

    def _synthesize_with_llm(
        self,
        context: Dict[str, Any],
        research_snippets: List[str],
        trend_signals: List[str],
        visual_references: List[Dict[str, Any]],
        reference_queries: List[str],
        selected_scene: Optional[Dict[str, Any]],
        style_hint: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if not self.llm_client or not hasattr(self.llm_client, "_generate"):
            return None

        fmt = getattr(self, "format", None) or LANDSCAPE_16_9
        scene_candidates_text = "\n".join(
            (
                f"- Segment {item.get('index')}: "
                f"text={str(item.get('text') or '').strip()[:180]} | "
                f"visual_prompt={str(item.get('visual_prompt') or '').strip()[:260]}"
            )
            for item in (context.get("scene_candidates") or [])[:10]
        ) or "- none"

        prompt = f"""
Return ONLY valid JSON.

You are a world-class YouTube thumbnail strategist.
Your job is to make a long-form vertical video thumbnail feel premium, urgent, cinematic and highly clickable.

Video topic: {context['topic']}
Category: {context['category']}
Language: {context['language']}
Duration seconds: {context['duration']}
Style hint: {style_hint or 'none'}

Storyboard scene candidates:
{scene_candidates_text}

Script excerpt:
\"\"\"
{context.get('script_excerpt', '')}
\"\"\"

Rules:
- {fmt.llm_brief}
- Prioritize one hero subject, one dramatic moment, and one striking visual angle.
- The result must feel wow, not generic, not stock, not flat.
- Push cinematic scale, depth, atmosphere, micro-contrast and clear mobile readability.
- Use only the project topic, script, and scene candidates provided here.
- Do not use external trends, web references, or unrelated prior projects.
- Select the single best storyboard scene candidate as the literal anchor when possible.
- Suggest a niche profile among: geopolitical_secret, military_coverup, science_incident, natural_disaster, historical_revelation, political_conspiracy, ancient_collapse, general_mystery.

JSON schema:
{{
  "suggested_niche_profile": "natural_disaster",
  "web_summary": "1-2 sentences",
  "hero_subject": "main visual subject",
  "hero_frame": "short framing instruction",
  "selected_scene_prompt": "literal scene anchor for the image model",
  "visual_motifs": ["...", "...", "..."],
  "reference_queries": ["...", "...", "..."],
  "trend_hooks": ["...", "...", "..."],
  "wow_directives": ["...", "...", "..."],
  "negative_constraints": ["...", "...", "..."],
  "quality_tier": "epic_cinematic"
}}
        """.strip()

        try:
            raw = self.llm_client._generate(prompt, max_tokens=1400)
        except TypeError:
            try:
                raw = self.llm_client._generate(prompt)
            except Exception as exc:
                self.log(f"LLM thumbnail enrichment failed: {exc}")
                return None
        except Exception as exc:
            self.log(f"LLM thumbnail enrichment failed: {exc}")
            return None

        parsed = self._extract_json(raw)
        if not isinstance(parsed, dict):
            # Un reintento: el modelo es no determinista y el JSON roto es
            # transitorio. Barato comparado con perder la miniatura.
            self.log("[WARN] JSON del enrichment ilegible; reintentando una vez.")
            try:
                raw = self.llm_client._generate(prompt, max_tokens=1400)
                parsed = self._extract_json(raw)
            except Exception as exc:
                self.log(f"[WARN] Reintento del enrichment fallo: {exc}")
                parsed = None
            if not isinstance(parsed, dict):
                self.log("[WARN] El enrichment sigue sin JSON valido.")
                return None

        self.log("Thumbnail context enrichment produced a cinematic brief")
        suggested_profile = str(parsed.get("suggested_niche_profile") or "").strip().lower()
        if suggested_profile not in {
            "geopolitical_secret",
            "military_coverup",
            "science_incident",
            "natural_disaster",
            "historical_revelation",
            "political_conspiracy",
            "ancient_collapse",
            "general_mystery",
        }:
            # Tirar un brief entero porque UN enum vino distinto era el
            # camino mas comun al error fatal: el resto del brief
            # (hero_subject, motivos, escena) suele estar perfecto.
            reemplazo = self._safe_profile_for_context(context)
            self.log(f"[WARN] niche_profile '{suggested_profile}' fuera de la lista; "
                     f"se usa '{reemplazo}' y se conserva el resto del brief.")
            suggested_profile = reemplazo

        cleaned_queries = self._clean_list(parsed.get("reference_queries"))
        cleaned_hooks = self._clean_list(parsed.get("trend_hooks"))

        return {
            "suggested_niche_profile": suggested_profile,
            "web_summary": str(parsed.get("web_summary") or "").strip(),
            "hero_subject": str(parsed.get("hero_subject") or "").strip(),
            "hero_frame": str(parsed.get("hero_frame") or "").strip(),
            "selected_scene_prompt": str(parsed.get("selected_scene_prompt") or (selected_scene or {}).get("visual_prompt") or "").strip(),
            "visual_motifs": self._clean_list(parsed.get("visual_motifs")),
            "reference_queries": cleaned_queries,
            "trend_hooks": cleaned_hooks,
            "wow_directives": self._clean_list(parsed.get("wow_directives")),
            "negative_constraints": self._clean_list(parsed.get("negative_constraints")),
            "quality_tier": str(parsed.get("quality_tier") or "epic_cinematic").strip(),
        }

    def _fallback_synthesis(
        self,
        context: Dict[str, Any],
        research_snippets: List[str],
        trend_signals: List[str],
        visual_references: List[Dict[str, Any]],
        reference_queries: List[str],
        selected_scene: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        title_hints = [item.get("title", "") for item in visual_references if item.get("title")]
        scene_prompt = str((selected_scene or {}).get("visual_prompt") or "").strip()
        hero_subject = self._scene_subject_from_prompt(scene_prompt) or (title_hints[0] if title_hints else context["topic"])
        suggested_profile = self._safe_profile_for_context(context)

        return {
            "suggested_niche_profile": suggested_profile,
            "web_summary": research_snippets[0][:260] if research_snippets else "",
            "hero_subject": hero_subject,
            "hero_frame": "single dominant hero subject, large in frame, premium cinematic depth, strong negative space",
            "selected_scene_prompt": scene_prompt,
            "visual_motifs": [
                "storm-lit atmosphere",
                "hero silhouette",
                "high-contrast focal point",
                "volumetric haze",
            ],
            "reference_queries": self._sanitize_reference_queries(context, reference_queries[:3]),
            "trend_hooks": self._fallback_topic_hooks(context, suggested_profile),
            "wow_directives": [
                "cinematic scale",
                "dramatic rim light",
                "atmospheric depth",
                "hyper-detailed textures",
                "premium movie-poster framing",
            ],
            "negative_constraints": [
                "no generic stock look",
                "no cluttered background",
                "no weak focal point",
                "no tiny distant subject",
                "no busy collage",
            ],
            "quality_tier": "epic_cinematic",
        }

    def _simplify_query(self, query: Any) -> str:
        simplified = re.sub(r"\([^)]*\)", "", str(query or ""))
        simplified = re.sub(r"[^A-Za-z0-9' ]+", " ", simplified)
        simplified = re.sub(r"\s+", " ", simplified).strip()
        return " ".join(simplified.split()[:6])


    def _extract_storyboard_scene_candidates(
        self,
        segments: List[Dict[str, Any]],
        topic: str,
        category: str,
        script: str,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for index, segment in enumerate(segments[:24], 1):
            visual_prompt = str(
                segment.get("visual_prompt")
                or segment.get("image_prompt")
                or segment.get("visual_description")
                or ""
            ).strip()
            text = str(
                segment.get("text")
                or segment.get("narration")
                or segment.get("script")
                or ""
            ).strip()
            if not visual_prompt:
                continue
            candidates.append(
                {
                    "index": index,
                    "text": text,
                    "visual_prompt": visual_prompt,
                }
            )
        return candidates[:10]


    def _fallback_topic_hooks(self, context: Dict[str, Any], suggested_profile: str) -> List[str]:
        combined = " ".join(
            str(context.get(key) or "").lower()
            for key in ("topic", "category", "script")
        )

        if suggested_profile == "ancient_collapse" or any(self._contains_phrase(combined, token) for token in ("sea peoples", "bronze age")):
            return ["SEA INVADERS", "BRONZE COLLAPSE", "WHO DESTROYED?"]
        if suggested_profile == "natural_disaster" or self._is_natural_disaster_context(combined):
            return self._natural_disaster_hooks(combined)
        if suggested_profile == "science_incident" or any(
            self._contains_phrase(combined, token)
            for token in ("tunguska", "meteor", "asteroid", "comet", "fireball", "impact", "explosion", "blast", "cosmic", "airburst")
        ):
            return ["WHAT EXPLODED?", "COSMIC BLAST", "SKY FIREBALL"]
        if suggested_profile == "military_coverup" or any(self._contains_phrase(combined, token) for token in ("kursk", "submarine", "barents", "navy", "torpedo", "missile", "naval")):
            return ["WHAT SANK?", "SEA COVER-UP", "DEADLY SILENCE"]
        if suggested_profile == "geopolitical_secret" or any(self._contains_phrase(combined, token) for token in ("uranium", "classified cargo", "nuclear")):
            return ["SECRET CARGO", "CLASSIFIED MOVE", "HIDDEN TRANSFER"]
        if any(self._contains_phrase(combined, token) for token in ("signal", "anomaly", "incident", "laboratory")):
            return ["UNKNOWN SIGNAL", "THE INCIDENT", "WHAT HIT?"]
        return ["HIDDEN TRUTH", "WHAT HAPPENED?", "THE SECRET"]

    def _topic_specific_reference_queries(self, context: Dict[str, Any]) -> List[str]:
        combined = " ".join(
            str(context.get(key) or "").lower()
            for key in ("topic", "category", "script")
        )

        if self._is_natural_disaster_context(combined):
            if any(self._contains_phrase(combined, token) for token in ("valdivia", "1960", "southern chile", "puyehue")):
                return [
                    "Valdivia earthquake 1960",
                    "1960 Chile tsunami",
                    "Valdivia earthquake destruction",
                    "Puyehue eruption 1960",
                ]
            if any(self._contains_phrase(combined, token) for token in ("tsunami", "pacific", "wave")):
                return [
                    "historic tsunami wave destruction",
                    "earthquake coastline damage",
                    "fault line rupture aerial",
                    "seismic disaster aftermath",
                ]
            if any(self._contains_phrase(combined, token) for token in ("volcano", "volcanic", "eruption", "ash cloud")):
                return [
                    "historic volcanic eruption plume",
                    "volcanic ash cloud disaster",
                    "eruption aftermath aerial",
                    "lava flow destruction",
                ]
            return [
                "historic earthquake destruction",
                "seismic fault line rupture",
                "earthquake aftermath aerial",
                "tsunami devastation coastline",
            ]

        if any(self._contains_phrase(combined, token) for token in ("sea peoples", "bronze age", "medinet habu", "ugarit", "hittite")):
            return [
                "Sea Peoples bronze age",
                "Sea Peoples Medinet Habu relief",
                "Bronze Age collapse ruins",
                "Sea Peoples warship",
            ]

        if any(
            self._contains_phrase(combined, token)
            for token in ("tunguska", "meteor", "asteroid", "comet", "fireball", "impact", "explosion", "blast", "cosmic", "airburst")
        ):
            return [
                "Tunguska explosion 1908",
                "Tunguska devastation Siberia",
                "Evenki Siberia 1908",
                "Siberian taiga blast",
            ]

        if any(self._contains_phrase(combined, token) for token in ("kursk", "submarine", "barents", "navy", "torpedo", "missile", "naval")):
            return [
                "Kursk submarine wreck",
                "Russian submarine rescue barents",
                "naval disaster cold sea",
            ]

        if any(self._contains_phrase(combined, token) for token in ("uranium", "nuclear", "classified cargo")):
            return [
                "classified cargo transfer",
                "uranium shipment cold war",
                "secret military cargo airport",
            ]

        return []

    def _contains_phrase(self, text: Any, phrase: str) -> bool:
        normalized_text = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
        normalized_phrase = re.sub(r"[^a-z0-9]+", " ", str(phrase or "").lower()).strip()
        if not normalized_text or not normalized_phrase:
            return False
        return re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized_text) is not None

    def _scene_subject_from_prompt(self, prompt: str) -> str:
        clean = str(prompt or "").strip()
        if not clean:
            return ""
        first_chunk = clean.split(",")[0].strip()
        first_chunk = re.sub(
            r"^(cinematic|dramatic|epic|close up|close-up|wide|suspenseful|mysterious|intense|detailed)\s+",
            "",
            first_chunk,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", first_chunk).strip()


    def _clean_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        cleaned: List[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned[:6]

    def _extract_json(self, raw_text: Any) -> Optional[Dict[str, Any]]:
        text = str(raw_text or "").strip().replace("```json", "").replace("```", "")
        if not text:
            return None

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None

        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
