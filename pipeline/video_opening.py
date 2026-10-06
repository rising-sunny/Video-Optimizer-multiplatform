# -*- coding: utf-8 -*-
"""Arranque del video: la escena 1 en movimiento, la voz desde el cuadro 0 y el texto de gancho encima.

Por que (2026-09-23): cada video arrancaba con una PLACA quieta de 0.7 s (cover frame) con una
palabra ('FEEDING' en el short de Hannibal), un 'ding' y SIN voz: la narracion se corria 0.7 s
para alinearla. Medido en los primeros 4 s de los 20 shorts de historia mas vistos del mes
(`trend_report.json`, 400K-10M vistas):
  - 18/20 tienen sonido antes de 0.3 s (la mitad en 0.0 s);
  - solo 3/20 estan quietos en el primer medio segundo;
  - el primer corte cae a ~1.8 s (mediana; 6/20 ni cortan en 4 s), no a 0.7 s;
  - 9 de los 12 medidos con vision tienen texto en el primer cuadro.
La placa existia "para servir de miniatura al subir desde el celular": ya no hace falta, la app
pone la miniatura sola en YouTube, Facebook (/thumbnails) e Instagram (cover_url).

El arranque nuevo ('hook_overlay_v1', por defecto; se configura en el Channel Bible, `hook_overlay`):
  1. sin placa: el segmento 0 es la primera escena y la voz arranca en 0.0 s;
  2. acercamiento con salida rapida (ease-out) en el primer clip: movimiento desde el cuadro 0;
  3. el primer plano dura al menos ~1.8 s (se toma tiempo del segundo clip si hace falta);
  4. el texto de gancho (la cifra del arranque del guion: '50,000 TROOPS', '100 KM A DAY') va
     ENCIMA del video en movimiento, con serif editorial, marfil, acento metal mate,
     espaciado optico y un degradado de contraste suave; sin contorno de pegatina.
El segmento 0 guarda `hook_overlay` {enabled, text, duration}: el timeline editor lo muestra y
lo deja editar. El storyboard guarda `opening` {style, ...} para medir despues (performance_feedback
agrupa por estilo de arranque). Los proyectos viejos con placa siguen renderizando igual.

Ver `test_video_opening.py`.
"""

from __future__ import annotations

import re
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

OPENING_STYLE = "hook_overlay_v1"
MAP_ZOOM_STYLE = "map_zoom_v1"
ARTIFACT_REVEAL_STYLE = "artifact_reveal_v1"
BEFORE_AFTER_STYLE = "before_after_v1"
OUTCOME_TEASER_STYLE = "outcome_teaser_v1"
LEGACY_STYLE = "cover_card"
PLAIN_STYLE = "plain"

# IDs estables: se guardan en el proyecto y alimentan el informe de rendimiento.
# El cold open conserva el ID historico para que los proyectos existentes sigan
# siendo comparables con los nuevos.
OPENING_STYLE_SPECS = {
    OPENING_STYLE: {
        "label": "Cold open cinematográfico",
        "short_label": "Cold open",
        "description": "Empieza en el instante de mayor impacto y entra directo a la historia.",
        "motion": "fast_push_in",
        "motion_amount": 0.12,
        "min_first_shot_seconds": 1.8,
        "prompt": (
            "Opening shot: the highest-stakes moment already in progress, immediate visual impact, "
            "dynamic cinematic composition, no establishing preamble"
        ),
        "followup_prompt": (
            "Second opening shot: reveal the immediate factual context behind the action while preserving "
            "momentum, a complementary angle rather than a repeated establishing shot"
        ),
        "narrative": (
            "Open in the middle of the most consequential documented action or decision. The first sentence "
            "must state a concrete stake, danger or irreversible consequence; give essential context only "
            "after the viewer is inside the event."
        ),
    },
    MAP_ZOOM_STYLE: {
        "label": "Zoom cartográfico",
        "short_label": "Mapa",
        "description": "Viaja desde el territorio hasta el punto exacto donde comienza la historia.",
        "motion": "map_dive",
        "motion_amount": 0.32,
        "min_first_shot_seconds": 2.2,
        "prompt": (
            "Opening shot: a richly detailed cinematic historical map centered on the exact location "
            "of the story, terrain and coastlines readable through shape alone, a luminous destination "
            "marker, designed for a rapid camera dive, no written labels"
        ),
        "followup_prompt": (
            "Second opening shot: ground-level arrival at the exact mapped location, matching its geography, "
            "era and weather, with a human-scale subject that begins the documented event"
        ),
        "narrative": (
            "Open by naming the exact documented place and why that location mattered. Move from geographic "
            "scale to the people or event on the ground in the second sentence. Do not narrate camera movement "
            "and do not say that a map is appearing."
        ),
    },
    ARTIFACT_REVEAL_STYLE: {
        "label": "Artefacto revelado",
        "short_label": "Artefacto",
        "description": "Un objeto emerge de la oscuridad y revela la escala de la historia.",
        "motion": "artifact_reveal",
        "motion_amount": 0.20,
        "min_first_shot_seconds": 2.0,
        "prompt": (
            "Opening shot: extreme macro view of the story's most meaningful physical artifact, "
            "emerging from darkness under a narrow museum-quality beam of light, tactile material, "
            "dust in the air, composed for a dramatic pull-back reveal"
        ),
        "followup_prompt": (
            "Second opening shot: the same documented object, structure or physical evidence in its original "
            "historical context and scale, visually connecting the detail to the larger story"
        ),
        "narrative": (
            "Open with a real physical object, structure or piece of evidence and immediately state what it "
            "reveals about the story. If no specific artifact is documented, use the most concrete verified "
            "site or physical evidence; never invent an object for the hook."
        ),
    },
    BEFORE_AFTER_STYLE: {
        "label": "Antes y después temporal",
        "short_label": "Antes / después",
        "description": "El mismo encuadre conecta dos epocas mediante un barrido temporal.",
        "motion": "era_wipe",
        "motion_amount": 0.12,
        "min_first_shot_seconds": 2.4,
        "prompt": (
            "Opening shot: one perfectly aligned location shown across two eras in a seamless split-time "
            "composition, ruins on one side and the historically reconstructed place at its peak on the "
            "other, matched camera angle and architecture, designed for a lateral time-wipe"
        ),
        "followup_prompt": (
            "Second opening shot: complete the temporal comparison from the same visual axis, emphasizing one "
            "specific documented change in architecture, landscape, power or daily life"
        ),
        "narrative": (
            "Open with a sharp, factual contrast between the same place, institution or subject at two "
            "documented moments. The first two sentences must name what changed and the time separating both "
            "states; if an exact span is uncertain, do not invent one."
        ),
    },
    OUTCOME_TEASER_STYLE: {
        "label": "Teaser del desenlace",
        "short_label": "Desenlace",
        "description": "Muestra un destello del momento culminante antes de volver al comienzo.",
        "motion": "outcome_punch",
        "motion_amount": 0.20,
        "min_first_shot_seconds": 1.6,
        "prompt": (
            "Opening shot: a spoiler-free flash-forward to the story's climactic consequence, the decisive "
            "moment frozen at peak tension, bold silhouette and immediate stakes, cinematic contrast, "
            "designed as a brief future glimpse before the story begins"
        ),
        "followup_prompt": (
            "Second opening shot: return to the documented starting point before the climax, quieter but tense, "
            "with the causal detail that begins the chain of events"
        ),
        "narrative": (
            "Open with a verified consequence or climactic outcome, without a false spoiler or invented quote. "
            "The second sentence must pivot back to the documented origin of the chain of events, creating a "
            "clear flash-forward and rewind structure."
        ),
    },
}
OPENING_STYLE_CHOICES = tuple(OPENING_STYLE_SPECS)
DEFAULTS = {
    "enabled": True,
    "duration_seconds": 1.8,          # el texto de gancho, hasta ~el primer corte
    "min_first_shot_seconds": 1.8,    # mediana del primer corte en los ganadores
    "push_in_zoom": 0.12,             # acercamiento del primer clip (ease-out)
    "fade_out_seconds": 0.25,
}
MIN_OTHER_SHOT_SECONDS = 0.8

HOOK_FONT = "Georgia"
HOOK_USABLE_WIDTH = 0.80
HOOK_ZONE = {"vertical": (0.12, 0.36), "landscape": (0.08, 0.42)}
HOOK_IVORY = "#F2EBDD"
HOOK_GOLD = "#CDB58A"
HOOK_INK = "#101820"
TOP_CLEAR_HINT = ("Composition: main subject in the middle and lower part of the frame; "
                  "the top third is calm, uncluttered background (sky, haze or shadow) for a headline")
NO_TEXT_HINT = "no text, no writing, no signs, no captions, no watermarks"


# ----------------------------------------------------------------------------
# Configuracion
# ----------------------------------------------------------------------------
def get_opening_config(bible: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if bible is None:
        try:
            from channel.channel_strategy import get_channel_strategy
            bible = get_channel_strategy()
        except Exception:
            bible = {}
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in ((bible or {}).get("hook_overlay") or {}).items() if k in DEFAULTS})
    return cfg


def normalize_opening_style(style: str = "") -> str:
    """Devuelve un ID moderno valido; vacio y valores viejos conservan el cold open."""
    candidate = str(style or "").strip()
    aliases = {
        "cold_open": OPENING_STYLE,
        "map_zoom": MAP_ZOOM_STYLE,
        "artifact_reveal": ARTIFACT_REVEAL_STYLE,
        "before_after": BEFORE_AFTER_STYLE,
        "outcome_teaser": OUTCOME_TEASER_STYLE,
    }
    candidate = aliases.get(candidate, candidate)
    return candidate if candidate in OPENING_STYLE_SPECS else OPENING_STYLE


def opening_style_spec(style: str = "") -> dict[str, Any]:
    """Copia defensiva de la receta visual de una apertura."""
    return dict(OPENING_STYLE_SPECS[normalize_opening_style(style)])


def is_modern_opening(style: str = "") -> bool:
    return str(style or "") in OPENING_STYLE_SPECS


def opening_script_instructions(style: str = OPENING_STYLE, language: str = "es",
                                include_visuals: bool = False) -> str:
    """Brief narrativo compartido por los generadores automatico, batched y manual."""
    selected = normalize_opening_style(style)
    spec = opening_style_spec(selected)
    narration_language = "English" if str(language or "").lower() == "en" else "Spanish"
    visual_block = ""
    if include_visuals:
        visual_block = f"""
VISUAL HANDOFF FOR THE FIRST TWO SCENES:
- Scene 1 visual_prompt: {spec['prompt']}.
- Scene 2 visual_prompt: {spec['followup_prompt']}.
- Both visuals must depict facts supported by the topic/script, obey the requested era and aspect ratio,
  and end with the global no-text suffix. Never invent an artifact, location, date or outcome to fit the style.
"""
    return f"""
SELECTED VIDEO OPENING: {spec['label']} ({selected})
This choice is structural, not decorative. Shape the spoken opening and the first two scenes around it.
- Narration language: {narration_language}.
- First 8-12 seconds: {spec['narrative']}
- Start the narration on frame zero. Do not add a title-card pause, production note, camera direction,
  editing instruction, or phrases such as "we see", "the camera shows" or "on this map".
- Keep every claim factual and supported. The opening style never authorizes invented evidence or drama.
- After the opening beat, continue naturally into the normal chronology and tone of the documentary.
{visual_block}""".strip()


# ----------------------------------------------------------------------------
# El texto de gancho
# ----------------------------------------------------------------------------
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _opening_sentences(script: str, n: int = 2) -> str:
    return " ".join(_SENTENCE_RE.split(str(script or "").strip())[:n])


def pick_hook_text(script: str, llm_text: str = "", archetype: str = "") -> tuple[str, str]:
    """(texto, por que). Primero la cifra con su sustantivo en las 2 primeras frases (lo que se
    esta diciendo en ese momento), despues en el arranque del guion, despues la sugerencia del LLM
    si el guion la respalda. Nunca inventa: todo sale del guion (text_options)."""
    try:
        from publish.thumbnail_research import text_options
    except Exception:
        text_options = None
    research = {"keyword": "", "suggestions": {}, "corpus": set()}
    if text_options:
        for source, where in ((_opening_sentences(script), "las primeras frases"),
                              (str(script or "")[:600], "el arranque del guion")):
            for opt in text_options("", source, research, archetype, max_chars=18):
                if "cifra" in opt["why"]:
                    return opt["text"], f"cifra de {where}"
    cand = re.sub(r"[^0-9A-Za-z,' -]", "", str(llm_text or "")).strip().upper()
    if cand and 1 <= len(cand.split()) <= 3:
        script_low = str(script or "").lower()
        if all(w.lower().strip(",'") in script_low for w in cand.split() if len(w) > 2):
            return cand, "texto de portada del LLM, respaldado por el guion"
    return "", "sin cifra ni texto respaldado: quedan los subtitulos"


# ----------------------------------------------------------------------------
# Decidir el arranque (lo llama el storyboard)
# ----------------------------------------------------------------------------
def apply_opening(segments: list[dict[str, Any]], *, script: str, topic: str = "", category: str = "",
                  llm_cover_text: str = "", archetype: str = "", bible: Optional[dict[str, Any]] = None,
                  opening_style_id: str = OPENING_STYLE,
                  log: Callable[[str], None] = print) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Devuelve (segmentos, opening). Por defecto: texto de gancho en el segmento 0, sin placa.
    La placa vieja solo si `hook_overlay.enabled` es false y `cover_frame.enabled` es true."""
    cfg = get_opening_config(bible)
    if cfg["enabled"] and segments:
        selected_style = normalize_opening_style(opening_style_id)
        spec = opening_style_spec(selected_style)
        text, why = pick_hook_text(script, llm_cover_text, archetype)
        hook = None
        if text:
            hook = {"enabled": True, "text": text, "duration": float(cfg["duration_seconds"]),
                    "source": why, "style": selected_style}
            segments[0]["hook_overlay"] = hook
        # Los dos primeros visuales expresan entrada + transicion narrativa. Se
        # anade una sola vez porque un proyecto puede reabrirse varias veces.
        def enrich_prompt(segment: dict[str, Any], directions: list[str]) -> None:
            vp = str(segment.get("visual_prompt") or "")
            additions = [direction for direction in directions if direction not in vp]
            if not additions:
                return
            base = vp.rstrip(" .")
            if base.lower().endswith(NO_TEXT_HINT):
                base = base[:-len(NO_TEXT_HINT)].rstrip(" .,;")
            parts = [part for part in (base, *additions, NO_TEXT_HINT) if part]
            segment["visual_prompt"] = ". ".join(parts)

        enrich_prompt(segments[0], [spec["prompt"], TOP_CLEAR_HINT])
        if len(segments) > 1 and isinstance(segments[1], dict):
            enrich_prompt(segments[1], [spec["followup_prompt"]])
        if text:
            log(f"   [Arranque] {spec['short_label']}; texto de gancho '{text}' ({why}), "
                f"{cfg['duration_seconds']}s")
        else:
            log(f"   [Arranque] {spec['short_label']}; {why}")
        return segments, {"style": selected_style, "label": spec["label"], "hook": hook,
                          "motion": spec["motion"],
                          "min_first_shot_seconds": float(spec["min_first_shot_seconds"]),
                          "motion_amount": float(spec["motion_amount"]),
                          # Compatibilidad con storyboards hook_overlay_v1 previos.
                          "push_in_zoom": float(spec["motion_amount"])}

    cover_cfg = (bible if bible is not None else _bible()).get("cover_frame") or {}
    if cover_cfg.get("enabled", False) and segments is not None:
        from pipeline.cover_frame_generator import select_cover_text
        cover_text = select_cover_text(topic, category, llm_suggestion=llm_cover_text or None)
        dur = float(cover_cfg.get("duration_seconds", 0.7))
        for seg in segments:
            seg["start"] = float(seg.get("start", 0) or 0) + dur
            seg["end"] = float(seg.get("end", 0) or 0) + dur
        segments.insert(0, {
            "start": 0.0, "end": dur, "text": "", "narration_text": "",
            "visual_prompt": f"Cinematic dark vertical cover frame for: {topic}",
            "sfx_tag": "none", "overlay_tag": "none", "assigned_filename": "cover_frame",
            "cover_frame": True, "cover_text": cover_text,
        })
        log(f"   [Cover Frame] Inserted: '{cover_text}' ({dur}s)")
        return segments, {"style": LEGACY_STYLE, "cover_text": cover_text, "duration": dur}
    return segments, {"style": PLAIN_STYLE}


def _bible() -> dict[str, Any]:
    try:
        from channel.channel_strategy import get_channel_strategy
        return get_channel_strategy() or {}
    except Exception:
        return {}


def opening_style(storyboard: dict[str, Any]) -> str:
    """El estilo de arranque de un storyboard (tambien de los viejos, que no lo guardaban)."""
    op = (storyboard or {}).get("opening") or {}
    if op.get("style"):
        return str(op["style"])
    segs = (storyboard or {}).get("segments") or []
    if segs and isinstance(segs[0], dict) and segs[0].get("cover_frame"):
        return LEGACY_STYLE
    if (storyboard or {}).get("cover_frame"):
        return LEGACY_STYLE
    return PLAIN_STYLE


def get_hook_overlay(storyboard: dict[str, Any]) -> Optional[dict[str, Any]]:
    """El texto de gancho a dibujar, o None. Manda lo del segmento 0 (lo que se edito en el
    timeline, incluso apagado); si el segmento se reconstruyo, lo del storyboard."""
    segs = (storyboard or {}).get("segments") or []
    first = segs[0] if segs and isinstance(segs[0], dict) else {}
    if first.get("cover_frame"):
        return None
    hook = first.get("hook_overlay")
    if hook is None:
        op = (storyboard or {}).get("opening") or {}
        hook = op.get("hook") if is_modern_opening(op.get("style")) else None
    if not isinstance(hook, dict) or not hook.get("enabled", True) or not str(hook.get("text") or "").strip():
        return None
    op_style = ((storyboard or {}).get("opening") or {}).get("style")
    return {"text": str(hook["text"]).strip().upper(),
            "duration": max(0.5, float(hook.get("duration") or DEFAULTS["duration_seconds"])),
            "style": normalize_opening_style(hook.get("style") or op_style)}


# ----------------------------------------------------------------------------
# Primer plano y movimiento (los usa el ensamblado)
# ----------------------------------------------------------------------------
def enforce_min_first_shot(clips: list[dict[str, Any]], min_first: float = DEFAULTS["min_first_shot_seconds"],
                           min_other: float = MIN_OTHER_SHOT_SECONDS) -> float:
    """Alarga el primer clip hasta `min_first` tomando tiempo del segundo (que no baja de
    `min_other`). La duracion total no cambia. Devuelve los segundos movidos."""
    if len(clips) < 2 or clips[0].get("is_cover") or clips[1].get("_vsplit_chain"):
        return 0.0
    d0, d1 = float(clips[0].get("duration") or 0), float(clips[1].get("duration") or 0)
    give = min(max(0.0, min_first - d0), max(0.0, d1 - min_other))
    if give <= 0.01:
        return 0.0
    clips[0]["duration"] = round(d0 + give, 3)
    clips[1]["duration"] = round(d1 - give, 3)
    if "timestamp_start" in clips[1]:
        clips[1]["timestamp_start"] = round(float(clips[1]["timestamp_start"] or 0) + give, 3)
    return round(give, 3)


def push_in_filter(frames: int, width: int, height: int, zoom: float = DEFAULTS["push_in_zoom"],
                   fps: float = 30) -> str:
    """zoompan con salida rapida: el mayor movimiento en el cuadro 0, frenando hacia el final.
    (El movimiento por defecto arranca lento y los primeros 0.5 s se ven quietos.)
    `fps` = el del video; zoompan sale a 25 por defecto y a 30 repite cuadros."""
    n = max(2, int(frames))
    p = f"(on/{n - 1})"
    return (f"zoompan=z='1+{zoom:.4f}*(1-(1-{p})*(1-{p}))'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={int(width)}x{int(height)}"
            f":fps={float(fps):g}")


def opening_motion_filter(frames: int, width: int, height: int,
                          style: str = OPENING_STYLE, amount: Optional[float] = None,
                          fps: float = 30) -> str:
    """Movimiento FFmpeg distintivo para la primera imagen de cada entrada."""
    selected = normalize_opening_style(style)
    spec = opening_style_spec(selected)
    strength = float(spec["motion_amount"] if amount is None else amount)
    n = max(2, int(frames))
    p = f"(on/{n - 1})"
    size = f"d={n}:s={int(width)}x{int(height)}:fps={float(fps):g}"
    center = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"

    if selected == MAP_ZOOM_STYLE:
        z = f"1+{strength:.4f}*(1-(1-{p})*(1-{p})*(1-{p}))"
        return f"zoompan=z='{z}':{center}:{size}"
    if selected == ARTIFACT_REVEAL_STYLE:
        z = f"1+{strength:.4f}*(1-{p})*(1-{p})"
        return f"zoompan=z='{z}':{center}:{size}"
    if selected == BEFORE_AFTER_STYLE:
        z = f"1+{strength:.4f}"
        x = f"(iw-iw/zoom)*(1-{p})"
        return f"zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':{size}"
    if selected == OUTCOME_TEASER_STYLE:
        z = f"1+{strength * 0.45:.4f}+{strength * 0.55:.4f}*(1-(1-{p})*(1-{p}))"
        return f"zoompan=z='{z}':{center}:{size}"
    return push_in_filter(n, width, height, strength, fps=fps)


# ----------------------------------------------------------------------------
# El texto de gancho como evento ASS
# ----------------------------------------------------------------------------
def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ass_time(seconds: float) -> str:
    cs = int(round(max(0.0, seconds) * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


class _Fmt:
    def __init__(self, width: int, height: int):
        self.width, self.height = int(width), int(height)
        self.is_vertical = self.height > self.width


@lru_cache(maxsize=1)
def _hook_font():
    """Fuente instalada y metricas reales; sin descargar ni redistribuir fuentes del sistema."""
    from PIL import ImageFont
    candidates = (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/georgia.ttf",
        Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),
        Path("/Library/Fonts/Georgia.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    )
    for path in candidates:
        if path.is_file():
            font = ImageFont.truetype(str(path), 1000)
            cap = font.getbbox("H")[3] - font.getbbox("H")[1]
            # libass normaliza Fontsize por ascenso+descenso, no por el em de Pillow.
            return font.getname()[0], font, cap, sum(font.getmetrics())
    return "serif", None, 680.0, 1100.0


def hook_plan(hook: dict[str, Any], width: int, height: int,
              palette: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from publish.thumbnail_typography import plan_typography
    fmt = _Fmt(width, height)
    kind = "vertical" if fmt.is_vertical else "landscape"
    plan = plan_typography(hook["text"], fmt, palette, usable_width=HOOK_USABLE_WIDTH,
                           zone=HOOK_ZONE[kind], glyph_width=0.90)
    family, font, cap, line_height = _hook_font()
    for ln in plan["lines"]:
        target = (8.0 if ln["role"] == "hero" else 5.5) if fmt.is_vertical else (
            11.0 if ln["role"] == "hero" else 8.0)
        if len(plan["lines"]) == 1:
            target = 6.2 if fmt.is_vertical else 9.0
        # Georgia usa cifras de estilo antiguo: su alto no coincide con el de H.
        # Medir la linea evita que los numeros queden menores que el tamano previsto.
        ink_height = max(1, font.getbbox(ln["text"])[3] - font.getbbox(ln["text"])[1]) if font else cap
        advance = font.getlength(ln["text"]) / ink_height if font else len(ln["text"]) * 0.95
        tracking_ratio = 0.075
        cap_px = min(target / 100 * height,
                     width * HOOK_USABLE_WIDTH / max(1, advance + tracking_ratio * (len(ln["text"]) - 1)))
        ln.update(cap_pct=cap_px / height * 100, font_size=cap_px * line_height / ink_height,
                  spacing=cap_px * tracking_ratio, color=HOOK_GOLD if ln["role"] == "hero" else HOOK_IVORY)
    # Limitar tambien la altura de la caja tipografica en formatos horizontales.
    available = (HOOK_ZONE[kind][1] - HOOK_ZONE[kind][0]) * height
    used = sum(ln["font_size"] for ln in plan["lines"]) + height * 0.008 * (len(plan["lines"]) - 1)
    if used > available:
        scale = available / used
        for ln in plan["lines"]:
            for key in ("font_size", "spacing", "cap_pct"):
                ln[key] *= scale
    plan.update(font=family, zone=HOOK_ZONE[kind], base_color=HOOK_IVORY, accent=HOOK_GOLD)
    return plan


def _ass_literal(text):
    return " ".join(str(text).split()).replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")


def hook_ass_lines(hook: dict[str, Any], width: int, height: int,
                   palette: Optional[dict[str, Any]] = None,
                   fade_out: float = DEFAULTS["fade_out_seconds"]) -> tuple[str, str]:
    """Estilo Hook y eventos: contraste gradual, sombra difusa, filete y titulo editorial."""
    plan = hook_plan(hook, width, height, palette)
    lines = plan["lines"]
    top = plan["zone"][0] * height
    duration = max(0.01, float(hook["duration"]))
    fade_ms = round(min(max(0, fade_out), duration * 0.3) * 1000)
    motion_ms = round(min(0.45, duration * 0.4) * 1000)
    selected_style = normalize_opening_style(hook.get("style"))
    fade = f"\\fad(0,{fade_ms})"  # legible desde el cuadro 0
    style = (f"Style: Hook,{plan['font']},100,{_ass_color(HOOK_IVORY)},&H00FFFFFF,"
             f"{_ass_color(HOOK_INK)},{_ass_color(HOOK_INK)},0,0,0,0,100,100,0,0,1,0,0,8,40,40,0,1")

    def event(layer, tags, text):
        return f"Dialogue: {layer},{_ass_time(0)},{_ass_time(duration)},Hook,,0,0,0,,{{{tags}}}{text}"

    ink = _ass_color(HOOK_INK)
    events, titles = [], []
    bottom = top + sum(ln["font_size"] for ln in lines) + height * 0.008 * max(0, len(lines) - 1)
    # Vigneta superior: sin caja ni corte visible; termina antes de invadir el sujeto.
    scrim_bottom = min(height * 0.48, bottom + height * 0.065)
    for i in range(64):
        y0, y1 = round(scrim_bottom * i / 64), round(scrim_bottom * (i + 1) / 64)
        progress = max(0, ((y0 + y1) / 2 - top) / max(1, scrim_bottom - top))
        opacity = 0.55 * (1 - progress * progress * (3 - 2 * progress))
        alpha = round(255 * (1 - opacity))
        # Recorte rectangular (sin antialias de borde) sobre un dibujo completo:
        # evita juntas claras entre bandas al renderizar a otra resolucion.
        tags = (f"\\an7\\pos(0,0)\\bord0\\shad0\\p1\\1c{ink}\\alpha&H{alpha:02X}&"
                f"\\clip(0,{y0},{width},{y1}){fade}")
        events.append(event(8, tags, f"m 0 0 l {width} 0 {width} {height} 0 {height}"))
    y = top
    for ln in lines:
        cap_px = ln["cap_pct"] / 100 * height
        x = width // 2
        if selected_style == BEFORE_AFTER_STYLE:
            placement = f"\\an8\\move({x - width * 0.025:.1f},{y:.1f},{x},{y:.1f},0,{motion_ms})"
        elif selected_style == ARTIFACT_REVEAL_STYLE:
            placement = (f"\\an8\\pos({x},{y:.1f})\\fscx108\\fscy108"
                         f"\\t(0,{motion_ms},\\fscx100\\fscy100)")
        elif selected_style == OUTCOME_TEASER_STYLE:
            placement = (f"\\an8\\pos({x},{y:.1f})\\fscx116\\fscy116"
                         f"\\t(0,{motion_ms},\\fscx100\\fscy100)")
        elif selected_style == MAP_ZOOM_STYLE:
            placement = (f"\\an8\\pos({x},{y:.1f})\\fsp0"
                         f"\\t(0,{motion_ms},\\fsp{ln['spacing']:.2f})")
        else:
            placement = f"\\an8\\move({x},{y + height * 0.004:.1f},{x},{y:.1f},0,{motion_ms})"
        spacing = "" if selected_style == MAP_ZOOM_STYLE else f"\\fsp{ln['spacing']:.2f}"
        common = f"{placement}\\q2\\fs{ln['font_size']:.2f}{spacing}{fade}"
        text = _ass_literal(ln["text"])
        events.append(event(9, f"{common}\\1c{ink}\\3c{ink}\\alpha&H99&"
                            f"\\bord{cap_px * 0.012:.2f}\\blur{cap_px * 0.060:.2f}\\shad1", text))
        titles.append(event(10, f"{common}\\1c{_ass_color(ln['color'])}\\bord0\\shad0\\blur0", text))
        y += ln["font_size"] + height * 0.008
    # Filete corto: acento de diseño, sin palabras adicionales ni simbolos.
    half = width * 0.055
    rule_y, thickness = round(bottom + height * 0.008), max(1, round(height * 0.001))
    events.append(event(9, f"\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c{_ass_color(HOOK_GOLD)}{fade}",
                        f"m {round(width/2-half)} {rule_y} l {round(width/2+half)} {rule_y} "
                        f"{round(width/2+half)} {rule_y+thickness} {round(width/2-half)} {rule_y+thickness}"))
    return style, "\n".join(events + titles)


def append_hook_to_ass(ass_text: str, hook: Optional[dict[str, Any]], width: int, height: int,
                       palette: Optional[dict[str, Any]] = None) -> str:
    """Actualiza solo el gancho, tambien en ASS guardados con el estilo anterior."""
    if not hook:
        return ass_text
    style, dialogue = hook_ass_lines(hook, width, height, palette)
    lines = []
    for line in ass_text.splitlines():
        if re.match(r"Style:\s*Hook,", line):
            continue
        if line.startswith("Dialogue:"):
            fields = line.split(",", 9)
            if len(fields) == 10 and fields[3].strip() == "Hook":
                continue
        lines.append(line)
    out, style_done = [], False
    for ln in lines:
        out.append(ln)
        if not style_done and ln.startswith("Style:"):
            out.append(style)
            style_done = True
    if not style_done:                       # sin estilos (raro): se arma la seccion
        return standalone_hook_ass(hook, width, height, palette)
    text = "\n".join(out).rstrip("\n") + "\n" + dialogue + "\n"
    return text


def standalone_hook_ass(hook: dict[str, Any], width: int, height: int,
                        palette: Optional[dict[str, Any]] = None) -> str:
    """Un .ass solo con el gancho (para videos sin subtitulos)."""
    style, dialogue = hook_ass_lines(hook, width, height, palette)
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {int(width)}\nPlayResY: {int(height)}\n"
            f"ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"{style}\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"{dialogue}\n")
