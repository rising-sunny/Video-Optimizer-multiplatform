import json
import re
from typing import Any, Dict, List, Optional
from thumbnail_formats import LANDSCAPE_16_9, resolve_format


DEFAULT_VARIANT_RECIPES = [
    {
        "id": "subject_left",
        "label": "A - Subject Left",
        "composition": "subject_left_text_right",
        "prompt_suffix": "close-up hero subject on the left third, open dark space on the right for hook text",
    },
    {
        "id": "subject_right",
        "label": "B - Subject Right",
        "composition": "subject_right_text_left",
        "prompt_suffix": "close-up hero subject on the right third, open dark space on the left for hook text",
    },
    {
        "id": "center_glow",
        "label": "C - Center Glow",
        "composition": "text_top_center",
        "prompt_suffix": "dramatic centered hero subject with atmospheric glow and negative space above",
    },
]

COMPOSITION_ALIASES = {
    "subject_left_text_right": "subject_left_text_right",
    "subject_left": "subject_left_text_right",
    "left_text_right": "subject_left_text_right",
    "left_subject_text_right": "subject_left_text_right",
    "subject_right_text_left": "subject_right_text_left",
    "subject_right": "subject_right_text_left",
    "right_text_left": "subject_right_text_left",
    "right_subject_text_left": "subject_right_text_left",
    "text_top_center": "text_top_center",
    "center_glow": "text_top_center",
    "subject_center": "text_top_center",
    "center_subject": "text_top_center",
    "subject_center_text_top": "text_top_center",
    "text_above_subject_center": "text_top_center",
    "top_text_center_subject": "text_top_center",
}

PROFILE_PRESETS = {
    "geopolitical_secret": {
        "label": "Geopolitical Secret",
        "keywords": (
            "uranium", "uranio", "nuclear", "classified", "secret", "cargo",
            "transfer", "shipment", "covert", "intel",
            "encubierta", "radiation",
        ),
        "palette": "danger_yellow_black",
        "default_hooks": ["SECRET CARGO", "HIDDEN TRANSFER", "CLASSIFIED MOVE"],
        "subject": "sealed classified cargo transfer",
        "concept": "classified transfer",
        "prompt_descriptor": "high-stakes geopolitical operation with covert logistics and a dangerous hidden payload",
        "preferred_compositions": [
            "subject_left_text_right",
            "subject_right_text_left",
            "text_top_center",
        ],
        "default_motifs": [
            "sealed containers",
            "armed escort silhouettes",
            "industrial floodlights",
        ],
    },
    "military_coverup": {
        "label": "Military Cover-Up",
        "keywords": (
            "submarine", "submarino", "kursk", "barents", "navy", "armada",
            "torpedo", "missile", "naval", "fleet", "sonar", "rescue",
        ),
        "palette": "cold_blue_red",
        "default_hooks": ["WHAT SANK?", "SEA COVER-UP", "DEADLY SILENCE"],
        "subject": "damaged submarine hull",
        "concept": "military cover-up",
        "prompt_descriptor": "naval disaster secrecy, freezing ocean atmosphere, damaged war machine, official silence",
        "preferred_compositions": [
            "subject_left_text_right",
            "subject_right_text_left",
            "text_top_center",
        ],
        "default_motifs": [
            "storm sea",
            "rescue lights",
            "damaged steel textures",
        ],
    },
    "science_incident": {
        "label": "Science Incident",
        "keywords": (
            "signal", "senal", "señal", "incident", "incidente",
            "experiment", "experimento", "lab", "laboratorio", "reactor",
            "anomaly", "anomalia", "anomalía", "physics", "fisica", "física",
            "sensor", "satellite", "satélite", "tunguska", "meteor", "asteroid",
            "comet", "impact", "explosion", "blast", "fireball", "cosmic", "airburst",
        ),
        "palette": "orange_cyan",
        "default_hooks": ["UNKNOWN SIGNAL", "WHAT HIT?", "THE INCIDENT"],
        "subject": "mysterious scientific anomaly",
        "concept": "unexplained incident",
        "prompt_descriptor": "scientific anomaly with eerie instrumentation glow and a central unexplained event",
        "preferred_compositions": [
            "text_top_center",
            "subject_left_text_right",
            "subject_right_text_left",
        ],
        "default_motifs": [
            "sensor lights",
            "radiant energy pattern",
            "control room glow",
        ],
    },
    "natural_disaster": {
        "label": "Natural Disaster",
        "keywords": (
            "earthquake", "terremoto", "quake", "tsunami", "magnitude",
            "richter", "epicenter", "epicentre", "aftershock", "aftershocks",
            "seismic", "fault line", "fault", "landslide", "landslides",
            "volcano", "volcanic", "eruption", "valdivia", "puyehue",
        ),
        "palette": "cold_blue_red",
        "default_hooks": ["WORLD SHOOK", "MEGA QUAKE", "FAULT LINE"],
        "subject": "towering tsunami wave over a collapsing coastline",
        "concept": "planet-shaking catastrophe",
        "prompt_descriptor": "cataclysmic seismic disaster with colossal scale, collapsing terrain, violent ocean force and survival-level urgency",
        "preferred_compositions": [
            "subject_left_text_right",
            "subject_right_text_left",
            "text_top_center",
        ],
        "default_motifs": [
            "towering wave wall",
            "fractured ground",
            "collapsed coastal city",
        ],
    },
    "historical_revelation": {
        "label": "Historical Revelation",
        "keywords": (
            "historical", "historico", "histórico", "archive",
            "archivo", "empire", "imperio", "reich", "ancient",
            "antiguo", "roman", "romano", "artifact", "artefacto", "manuscript",
            "manuscrito", "tomb", "tumba", "coronel",
        ),
        "palette": "orange_cyan",
        "default_hooks": ["HIDDEN FILES", "BURIED TRUTH", "LOST EVIDENCE"],
        "subject": "revealing historical artifact",
        "concept": "buried historical truth",
        "prompt_descriptor": "historic revelation with archival tension, dramatic artifact lighting and atmospheric shadows",
        "preferred_compositions": [
            "subject_right_text_left",
            "text_top_center",
            "subject_left_text_right",
        ],
        "default_motifs": [
            "aged documents",
            "artifact close-up",
            "dust-filled shafts of light",
        ],
    },
    "political_conspiracy": {
        "label": "Political Conspiracy",
        "keywords": (
            "president", "presidente", "putin", "government", "gobierno",
            "kremlin", "minister", "ministro", "meeting", "reunion", "reunión",
            "coup", "golpe", "political", "politico", "político", "senate",
            "senado", "white house", "cabinet",
        ),
        "palette": "danger_yellow_black",
        "default_hooks": ["SECRET ORDER", "WHO KNEW?", "CLOSED DOORS"],
        "subject": "tense closed-door political meeting",
        "concept": "political concealment",
        "prompt_descriptor": "political secrecy, tense leadership meeting, hidden agenda, cinematic shadows",
        "preferred_compositions": [
            "subject_left_text_right",
            "subject_right_text_left",
            "text_top_center",
        ],
        "default_motifs": [
            "silhouetted officials",
            "dark conference room",
            "single harsh spotlight",
        ],
    },
    "ancient_collapse": {
        "label": "Ancient Collapse",
        "keywords": (
            "sea peoples", "sea people", "bronze age", "late bronze", "ugarit",
            "hittite", "mycenae", "mycenaean", "levant", "mediterranean",
            "ramesses", "egypt", "pharaoh", "ancient invasion", "collapse",
        ),
        "palette": "orange_cyan",
        "default_hooks": ["SEA INVADERS", "BRONZE COLLAPSE", "WHO DESTROYED?"],
        "subject": "burning bronze age warship",
        "concept": "civilizational collapse",
        "prompt_descriptor": "apocalyptic bronze age collapse with raiders at sea, burning ports and mythic historical scale",
        "preferred_compositions": [
            "subject_left_text_right",
            "subject_right_text_left",
            "text_top_center",
        ],
        "default_motifs": [
            "stormy sea",
            "burning harbor",
            "bronze armor silhouettes",
        ],
    },
    "general_mystery": {
        "label": "General Mystery",
        "keywords": (),
        "palette": "danger_yellow_black",
        "default_hooks": ["THE SECRET", "WHAT HAPPENED?", "HIDDEN TRUTH"],
        "subject": "central mysterious subject",
        "concept": "hidden truth",
        "prompt_descriptor": "dark mystery reveal with one strong focal subject and atmospheric negative space",
        "preferred_compositions": [
            "subject_left_text_right",
            "text_top_center",
            "subject_right_text_left",
        ],
        "default_motifs": [
            "atmospheric darkness",
            "single focal light",
            "ominous depth",
        ],
    },
}


def _audiencia_del_canal() -> str:
    """Publico del canal, leido del Channel Bible y no cableado aca.

    Ver `channel_strategy.get_channel_audience_line`: esta linea entra en el
    prompt del LLM que disena la miniatura, asi que tenerla cableada como
    "mystery, conspiracies, unexplained events" equivalia a pedirle miniaturas
    del canal ANTERIOR, justo lo que el Bible del canal nuevo pone fuera de
    alcance.
    """
    try:
        from channel.channel_strategy import get_channel_audience_line
        return get_channel_audience_line()
    except Exception:
        return "general audience"


class ThumbnailIntelligence:
    WEAK_SINGLE_WORD_HOOKS = {
        "MYSTERY", "SECRET", "TRUTH", "ANCIENT", "HISTORY", "UNKNOWN", "INVASION", "UNCOVER",
    }
    GENERIC_HOOK_BLACKLIST = {
        "BREAKING NEWS", "GOOGLE NEWS", "TOP NEWS", "POP NEWS",
        "TRENDING NOW", "YOUTUBE SHORTS", "GOOGLE TRENDS",
    }

    def __init__(self, llm_client=None, log_callback=None, thumbnail_format=None):
        self.format = thumbnail_format or LANDSCAPE_16_9
        self.llm_client = llm_client
        self.log = log_callback or (lambda _msg: None)

    def generate_strategy(
        self,
        project_data: Dict[str, Any],
        style_hint: Optional[str] = None,
        enriched_context: Optional[Dict[str, Any]] = None,
        thumbnail_format=None,
    ) -> Dict[str, Any]:
        self.format = thumbnail_format or resolve_format(project_data=project_data)
        if not self.llm_client or not hasattr(self.llm_client, "_generate"):
            raise RuntimeError("Groq no está disponible para la estrategia de miniaturas hook.")
        context = self._extract_context(project_data)
        strategy = self._try_llm_strategy(context, style_hint, enriched_context)
        if isinstance(strategy, dict):
            try:
                return self._normalize_llm_strategy(
                    strategy, context, style_hint, enriched_context)
            except Exception as exc:
                # `_normalize_llm_strategy` exige 3 hooks, 3 recetas,
                # hero_subject, selected_scene_prompt y base_prompt: cinco
                # motivos distintos para abortar todo por un campo flojo.
                self.log(f"[WARN] Estrategia del LLM incompleta ({exc}); "
                         "se completa con la de respaldo.")
        else:
            self.log("[WARN] El LLM no devolvio una estrategia; "
                     "se usa la de respaldo.")
        self.log("[FALLBACK] Miniatura con estrategia de respaldo "
                 "(perfil inferido del tema y del enrichment).")
        return self._fallback_strategy(context, style_hint, enriched_context)

    def _extract_context(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        config = project_data.get("config", {}) or {}
        storyboard = project_data.get("storyboard", {}) or {}
        segments = project_data.get("segments") or storyboard.get("segments") or []

        topic = (
            config.get("topic")
            or project_data.get("topic")
            or project_data.get("title")
            or storyboard.get("topic")
            or "Untold mystery"
        )
        category = config.get("category") or project_data.get("category") or storyboard.get("category") or "Mystery"
        duration = config.get("duration") or project_data.get("duration") or storyboard.get("duration") or 0
        language = config.get("language") or project_data.get("language") or "en"
        script = storyboard.get("script") or project_data.get("script") or ""

        if not script and segments:
            parts = []
            for segment in segments[:12]:
                text = (
                    segment.get("text")
                    or segment.get("narration")
                    or segment.get("script")
                    or ""
                ).strip()
                if text:
                    parts.append(text)
            script = " ".join(parts)

        return {
            "topic": str(topic).strip(),
            "category": str(category).strip(),
            "duration": int(duration or 0),
            "language": str(language or "en").strip().lower(),
            "script": str(script or "").strip(),
            "script_excerpt": str(script or "").strip()[:1800],
        }

    def _try_llm_strategy(
        self,
        context: Dict[str, Any],
        style_hint: Optional[str],
        enriched_context: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not self.llm_client or not hasattr(self.llm_client, "_generate"):
            return None

        language = "English" if context["language"] == "en" else "Spanish"
        fmt = getattr(self, "format", None) or LANDSCAPE_16_9
        enriched_context = enriched_context or {}
        enrichment_brief = {
            "suggested_niche_profile": enriched_context.get("suggested_niche_profile"),
            "web_summary": enriched_context.get("web_summary"),
            "hero_subject": enriched_context.get("hero_subject"),
            "hero_frame": enriched_context.get("hero_frame"),
            "visual_motifs": enriched_context.get("visual_motifs"),
            "trend_hooks": enriched_context.get("trend_hooks"),
            "wow_directives": enriched_context.get("wow_directives"),
            "negative_constraints": enriched_context.get("negative_constraints"),
            "quality_tier": enriched_context.get("quality_tier"),
        }

        prompt = f"""
Return ONLY valid JSON.

You are designing a premium YouTube thumbnail strategy for a vertical watch-time video.
Video topic: {context['topic']}
Category: {context['category']}
Narration language: {language}
Duration seconds: {context['duration']}
Style hint: {style_hint or 'none'}

Context enrichment brief:
{json.dumps(enrichment_brief, ensure_ascii=True)}

Literal storyboard scene candidate:
{enriched_context.get('selected_scene_prompt') or 'none'}

Rules:
- {fmt.llm_brief}
- Audience: {_audiencia_del_canal()}.
- Use only the project topic, script excerpt, and enrichment brief provided here.
- Do not introduce external trends, web references, or prior project contamination.
- Hook text must be 1 to 3 words max.
- Text must create a curiosity gap, not summarize the whole video.
- Prioritize one strong hero subject and one mystery concept.
- Favor cinematic contrast, readable negative space, and high-end browse quality.
- Choose render_mode as either realistic_image or digital_illustration.
- Choose niche_profile as one of: geopolitical_secret, military_coverup, science_incident, natural_disaster, historical_revelation, political_conspiracy, ancient_collapse, general_mystery.
- Provide 3 variant_recipes with different compositions.
- Each variant_recipes composition must be EXACTLY one of:
  - subject_left_text_right
  - subject_right_text_left
  - text_top_center
- Do not invent composition aliases or new composition names.

Script excerpt:
\"\"\"
{context['script_excerpt']}
\"\"\"

JSON schema:
{{
  "impact_subject": "...",
  "hero_subject": "...",
  "hero_frame": "...",
  "selected_scene_prompt": "...",
  "mystery_concept": "...",
  "hook_candidates": ["...", "...", "..."],
  "selected_hook": "...",
  "niche_profile": "general_mystery",
  "palette": "danger_yellow_black|orange_cyan|cold_blue_red",
  "lighting": "...",
  "render_mode": "realistic_image",
  "quality_tier": "epic_cinematic",
  "visual_motifs": ["...", "...", "..."],
  "wow_directives": ["...", "...", "..."],
  "negative_constraints": ["...", "...", "..."],
  "reference_queries": ["...", "...", "..."],
  "base_prompt": "...",
  "variant_recipes": [
    {{
      "id": "subject_left",
      "label": "A - Subject Left",
      "composition": "subject_left_text_right",
      "prompt_suffix": "..."
    }}
  ]
}}
""".strip()

        try:
            raw = self.llm_client._generate(prompt, max_tokens=1600)
        except TypeError:
            try:
                raw = self.llm_client._generate(prompt)
            except Exception as exc:
                self.log(f"Thumbnail Intelligence LLM failed: {exc}")
                return None
        except Exception as exc:
            self.log(f"Thumbnail Intelligence LLM failed: {exc}")
            return None

        if not raw or (isinstance(raw, str) and raw.startswith("ERROR")):
            return None

        parsed = self._extract_json(raw)
        if isinstance(parsed, dict):
            self.log("Thumbnail Intelligence generated strategy with LLM")
        return parsed

    def _normalize_llm_strategy(
        self,
        strategy: Dict[str, Any],
        context: Dict[str, Any],
        style_hint: Optional[str],
        enriched_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        enriched_context = enriched_context or {}

        profile_key = str(strategy.get("niche_profile") or "").strip().lower()
        if profile_key not in PROFILE_PRESETS:
            raise RuntimeError("Groq devolvió un niche_profile inválido para miniaturas hook.")
        profile = self._get_profile_preset(profile_key)

        hook_candidates = []
        for hook in strategy.get("hook_candidates") or []:
            clean = self._clean_hook_text(hook)
            if clean and clean not in hook_candidates:
                hook_candidates.append(clean)
        if len(hook_candidates) < 3:
            raise RuntimeError("Groq no devolvió 3 hook_candidates válidos para miniaturas hook.")

        selected_hook = self._clean_hook_text(strategy.get("selected_hook"))
        if not selected_hook:
            selected_hook = hook_candidates[0]
        elif selected_hook not in hook_candidates:
            hook_candidates = [selected_hook] + [hook for hook in hook_candidates if hook != selected_hook]

        palette = str(strategy.get("palette") or "").strip()
        if palette not in {"danger_yellow_black", "orange_cyan", "cold_blue_red"}:
            raise RuntimeError("Groq devolvió una palette inválida para miniaturas hook.")

        render_mode = str(strategy.get("render_mode") or "").strip().lower()
        if render_mode not in {"realistic_image", "digital_illustration"}:
            raise RuntimeError("Groq devolvió un render_mode inválido para miniaturas hook.")

        variant_recipes = strategy.get("variant_recipes")
        if not isinstance(variant_recipes, list) or len(variant_recipes) < 3:
            raise RuntimeError("Groq no devolvió 3 variant_recipes válidas para miniaturas hook.")

        normalized_variants: List[Dict[str, str]] = []
        for recipe in variant_recipes[:3]:
            if not isinstance(recipe, dict):
                raise RuntimeError("Groq devolvió una variant_recipe inválida para miniaturas hook.")
            raw_composition = str(recipe.get("composition") or "").strip()
            composition = self._normalize_variant_composition(raw_composition)
            if not composition:
                raise RuntimeError(
                    f"Groq returned an invalid hook thumbnail composition: {raw_composition or 'empty'}."
                )
            normalized_variants.append(
                {
                    "id": str(recipe.get("id") or "").strip(),
                    "label": str(recipe.get("label") or "").strip(),
                    "composition": composition,
                    "prompt_suffix": str(recipe.get("prompt_suffix") or "").strip(),
                }
            )

        hero_subject = str(
            strategy.get("hero_subject")
            or strategy.get("impact_subject")
            or enriched_context.get("hero_subject")
            or ""
        ).strip()
        if not hero_subject:
            raise RuntimeError("Groq no devolvió hero_subject para miniaturas hook.")

        selected_scene_prompt = str(
            strategy.get("selected_scene_prompt")
            or enriched_context.get("selected_scene_prompt")
            or ""
        ).strip()
        if not selected_scene_prompt:
            raise RuntimeError("Groq no devolvió selected_scene_prompt para miniaturas hook.")

        base_prompt = str(strategy.get("base_prompt") or "").strip()
        if not base_prompt:
            raise RuntimeError("Groq no devolvió base_prompt para miniaturas hook.")

        return {
            "topic": context["topic"],
            "category": context["category"],
            "language": context["language"],
            "duration": context["duration"],
            "niche_profile": profile_key,
            "niche_label": str(profile.get("label") or profile_key.replace("_", " ").title()),
            "impact_subject": str(strategy.get("impact_subject") or hero_subject).strip(),
            "hero_subject": hero_subject,
            "hero_frame": str(
                strategy.get("hero_frame")
                or enriched_context.get("hero_frame")
                or ""
            ).strip(),
            "selected_scene_prompt": selected_scene_prompt,
            "mystery_concept": str(
                strategy.get("mystery_concept")
                or enriched_context.get("web_summary")
                or ""
            ).strip(),
            "hook_candidates": hook_candidates[:3],
            "selected_hook": selected_hook,
            "palette": palette,
            "lighting": str(strategy.get("lighting") or "").strip(),
            "render_mode": render_mode,
            "quality_tier": str(strategy.get("quality_tier") or "epic_cinematic").strip(),
            "visual_motifs": self._clean_string_list(strategy.get("visual_motifs")),
            "wow_directives": self._clean_string_list(strategy.get("wow_directives")),
            "negative_constraints": self._clean_string_list(strategy.get("negative_constraints")),
            "reference_queries": self._clean_string_list(strategy.get("reference_queries")),
            "reference_images": [],
            "web_summary": str(strategy.get("web_summary") or enriched_context.get("web_summary") or "").strip(),
            "base_prompt": base_prompt,
            "variant_recipes": normalized_variants,
            "preferred_compositions": list(profile.get("preferred_compositions") or []),
        }

    def _normalize_variant_composition(self, composition: Any) -> str:
        key = str(composition or "").strip().lower().replace("-", "_").replace(" ", "_")
        return COMPOSITION_ALIASES.get(key, "")

    def _fallback_strategy(
        self,
        context: Dict[str, Any],
        style_hint: Optional[str],
        enriched_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        enriched_context = enriched_context or {}
        profile_key = self._infer_niche_profile(context, enriched_context)
        profile = self._get_profile_preset(profile_key)
        hooks = self._merge_hook_candidates(
            enriched_context.get("trend_hooks"),
            profile.get("default_hooks"),
        )
        concept = str(enriched_context.get("web_summary") or profile.get("concept") or "hidden truth").strip()
        scene_prompt = str(enriched_context.get("selected_scene_prompt") or "").strip()
        subject = str(
            enriched_context.get("hero_subject")
            or profile.get("subject")
            or self._subject_from_topic(context["topic"])
        ).strip()
        hero_frame = str(
            enriched_context.get("hero_frame")
            or "single dominant hero subject, large in frame, dramatic negative space"
        ).strip()
        descriptor = str(profile.get("prompt_descriptor") or "dark mystery reveal")
        render_mode = "digital_illustration" if self._looks_illustrative(style_hint) else "realistic_image"
        visual_motifs = self._clean_string_list(
            enriched_context.get("visual_motifs")
            or profile.get("default_motifs")
            or []
        )
        wow_directives = self._clean_string_list(
            enriched_context.get("wow_directives")
            or [
                "cinematic scale",
                "premium movie-poster framing",
                "hyper-detailed textures",
                "dramatic rim light",
            ]
        )
        negative_constraints = self._clean_string_list(
            enriched_context.get("negative_constraints")
            or [
                "no generic stock look",
                "no cluttered background",
                "no weak focal point",
                "no busy collage",
            ]
        )
        reference_queries = self._sanitize_reference_queries(
            self._clean_string_list(enriched_context.get("reference_queries") or [context["topic"]]),
            context=context,
            profile_key=profile_key,
        )

        prompt_parts = [
            f"Cinematic YouTube thumbnail scene about {context['topic']}",
            f"literal scene anchor: {scene_prompt}" if scene_prompt else "",
            f"focus on {subject}",
            f"hero framing: {hero_frame}",
            f"theme of {concept}",
            descriptor,
            "single iconic moment",
            "must visibly include a topic-specific scene, not just a generic landscape",
            "high-end browse quality",
            "premium lighting",
            "mobile-first readability",
        ]
        if visual_motifs:
            prompt_parts.append(f"visual motifs: {', '.join(visual_motifs[:4])}")
        if wow_directives:
            prompt_parts.append(f"wow directives: {', '.join(wow_directives[:4])}")
        if reference_queries:
            prompt_parts.append(f"reference anchors: {', '.join(reference_queries[:3])}")
        prompt_parts.append("no text, no watermark, no logo")

        return {
            "niche_profile": profile_key,
            "impact_subject": subject,
            "hero_subject": subject,
            "hero_frame": hero_frame,
            "selected_scene_prompt": scene_prompt,
            "mystery_concept": concept,
            "hook_candidates": hooks,
            "selected_hook": hooks[0],
            "palette": str(profile.get("palette") or "danger_yellow_black"),
            "lighting": "cinematic glow with hard contrast",
            "render_mode": render_mode,
            "quality_tier": str(enriched_context.get("quality_tier") or "epic_cinematic"),
            "visual_motifs": visual_motifs,
            "wow_directives": wow_directives,
            "negative_constraints": negative_constraints,
            "reference_queries": reference_queries,
            "web_summary": str(enriched_context.get("web_summary") or ""),
            "base_prompt": ", ".join(part for part in prompt_parts if part),
            "variant_recipes": self._default_variant_recipes_for_profile(profile_key),
        }


    def _extract_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        if not raw_text:
            return None
        text = str(raw_text).strip().replace("```json", "").replace("```", "")
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

    def _subject_from_topic(self, topic: str) -> str:
        tokens = [token for token in re.split(r"[^A-Za-z0-9]+", topic) if token]
        if not tokens:
            return "central mysterious subject"
        return " ".join(tokens[:4]).lower()

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
        normalized = self._text_normalize(text)
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

        if not hooks:
            hooks = ["WORLD SHOOK", "MEGA QUAKE", "FAULT LINE"]

        deduped: List[str] = []
        for hook in hooks:
            clean = self._clean_hook_text(hook)
            if clean and clean not in deduped:
                deduped.append(clean)
        return deduped[:3] or ["WORLD SHOOK", "MEGA QUAKE", "FAULT LINE"]

    def _sanitize_reference_queries(
        self,
        queries: List[str],
        context: Dict[str, Any],
        profile_key: str,
    ) -> List[str]:
        cleaned = self._clean_string_list(queries)
        if not cleaned:
            return [str(context.get("topic") or "Untold mystery").strip()]

        combined = " ".join(str(context.get(key) or "") for key in ("topic", "category", "script"))
        if profile_key != "natural_disaster" and not self._is_natural_disaster_context(combined):
            return cleaned[:6]

        blocked_terms = (
            "classified", "cargo", "uranium", "nuclear", "shipment",
            "transfer", "weapon", "airport", "military",
        )
        filtered = [
            query for query in cleaned
            if not any(self._contains_phrase(query, blocked) for blocked in blocked_terms)
        ]
        return filtered[:6] or [str(context.get("topic") or "Untold mystery").strip()]


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
            return ["UNKNOWN SIGNAL", "WHAT HIT?", "THE INCIDENT"]
        return ["HIDDEN TRUTH", "WHAT HAPPENED?", "THE SECRET"]

    def _text_normalize(self, text: Any) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())).strip()

    def _contains_phrase(self, text: Any, phrase: str) -> bool:
        normalized_text = self._text_normalize(text)
        normalized_phrase = self._text_normalize(phrase)
        if not normalized_text or not normalized_phrase:
            return False
        return re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized_text) is not None


    def _clean_hook_text(self, text: Optional[str]) -> str:
        clean = re.sub(r"\s+", " ", str(text or "").strip())
        clean = re.sub(r"[^A-Za-z0-9?!. ]+", "", clean).upper()
        words = clean.split()
        if not words:
            return ""
        normalized = " ".join(words[:3]).strip()
        if normalized in self.GENERIC_HOOK_BLACKLIST:
            return ""
        return normalized

    def _looks_illustrative(self, style_hint: Optional[str]) -> bool:
        hint = str(style_hint or "").strip().lower()
        return any(
            token in hint
            for token in ("illustr", "poster", "graphic", "vector", "comic", "anime", "toon", "cartoon")
        )

    def _infer_niche_profile(
        self,
        context: Dict[str, Any],
        enriched_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        enriched_context = enriched_context or {}
        core_text = " ".join(
            str(value or "")
            for value in (
                context.get("topic"),
                context.get("category"),
                context.get("script"),
                enriched_context.get("web_summary"),
                enriched_context.get("selected_scene_prompt"),
                enriched_context.get("hero_subject"),
            )
        )
        support_text = " ".join(
            str(value or "")
            for value in (
                " ".join(str(item.get("title") or "") for item in enriched_context.get("visual_references") or []),
                " ".join(str(item) for item in enriched_context.get("reference_queries") or []),
                " ".join(str(item) for item in enriched_context.get("trend_hooks") or []),
            )
        )

        for profile_key in (
            "ancient_collapse",
            "natural_disaster",
            "geopolitical_secret",
            "military_coverup",
            "science_incident",
            "historical_revelation",
            "political_conspiracy",
        ):
            preset = self._get_profile_preset(profile_key)
            if any(self._contains_phrase(core_text, keyword) for keyword in preset.get("keywords", ())):
                return profile_key

        suggested = str(enriched_context.get("suggested_niche_profile") or "").strip().lower()
        if suggested in PROFILE_PRESETS:
            return suggested

        for profile_key in (
            "ancient_collapse",
            "natural_disaster",
            "geopolitical_secret",
            "military_coverup",
            "science_incident",
            "historical_revelation",
            "political_conspiracy",
        ):
            preset = self._get_profile_preset(profile_key)
            support_hits = [
                keyword
                for keyword in preset.get("keywords", ())
                if self._contains_phrase(support_text, keyword)
            ]
            if len(support_hits) >= 2:
                return profile_key

        return "general_mystery"

    def _get_profile_preset(self, profile_key: str) -> Dict[str, Any]:
        return PROFILE_PRESETS.get(profile_key, PROFILE_PRESETS["general_mystery"])

    def _default_variant_recipes_for_profile(self, profile_key: str) -> List[Dict[str, str]]:
        preferred_compositions = self._get_profile_preset(profile_key).get("preferred_compositions") or []
        composition_map = {recipe["composition"]: recipe for recipe in DEFAULT_VARIANT_RECIPES}
        ordered = []
        for composition in preferred_compositions:
            recipe = composition_map.get(composition)
            if recipe and recipe not in ordered:
                ordered.append(recipe.copy())

        for recipe in DEFAULT_VARIANT_RECIPES:
            if all(existing["id"] != recipe["id"] for existing in ordered):
                ordered.append(recipe.copy())

        return ordered[:3]

    def _clean_string_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        cleaned: List[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned[:6]

    def _merge_hook_candidates(self, *hook_groups: Any) -> List[str]:
        clean_hooks: List[str] = []
        for group in hook_groups:
            if isinstance(group, str):
                group = [group]
            if not isinstance(group, list):
                continue
            for hook in group:
                clean = self._clean_hook_text(hook)
                if clean and clean not in clean_hooks:
                    clean_hooks.append(clean)
        if not clean_hooks:
            clean_hooks = ["THE SECRET"]
        while len(clean_hooks) < 3:
            fallback = self._clean_hook_text(f"{clean_hooks[0]} {len(clean_hooks) + 1}")
            if fallback and fallback not in clean_hooks:
                clean_hooks.append(fallback)
            else:
                break
        return clean_hooks[:8]


