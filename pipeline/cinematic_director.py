"""Narrative-aware cinematic direction for storyboard segments.

The director is intentionally dependency-free. It produces a stable plan that
the FFmpeg and MoviePy renderers can interpret without calling an LLM again.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import MutableMapping
from typing import Any, Dict, Iterable, List, Sequence


DIRECTOR_VERSION = "cinematic_director_v1"
DEFAULT_LEVEL = "auto"

LEVEL_SPECS = {
    "auto": {"label": "Automatico", "strength": 0.68, "highlight_count": 3},
    "subtle": {"label": "Sutil", "strength": 0.38, "highlight_count": 2},
    "cinematic": {"label": "Cinematografico", "strength": 0.68, "highlight_count": 3},
    "epic": {"label": "Epico", "strength": 0.92, "highlight_count": 4},
}

_LEVEL_ALIASES = {
    "automatico": "auto",
    "automatic": "auto",
    "sutil": "subtle",
    "suave": "subtle",
    "cinematografico": "cinematic",
    "cinematico": "cinematic",
    "epico": "epic",
}

_ACTION_WORDS = {
    "attack", "battle", "blast", "collapse", "escape", "explosion", "fight",
    "fire", "invasion", "war", "ataque", "batalla", "colapso", "escape",
    "explosion", "fuego", "guerra", "invasion",
}
_MAP_WORDS = {
    "border", "city", "coast", "continent", "empire", "island", "map", "ocean",
    "route", "territory", "border", "ciudad", "costa", "continente", "imperio",
    "isla", "mapa", "oceano", "ruta", "territorio",
}
_EVIDENCE_WORDS = {
    "artifact", "document", "evidence", "inscription", "letter", "manuscript",
    "object", "relic", "ruin", "tomb", "artefacto", "documento", "evidencia",
    "inscripcion", "manuscrito", "objeto", "reliquia", "ruina", "tumba",
}
_MYSTERY_WORDS = {
    "dark", "disappear", "hidden", "mystery", "secret", "shadow", "unknown",
    "desapare", "misterio", "oculto", "oscuro", "secreto", "sombra",
}
_CALM_WORDS = {
    "beauty", "calm", "daily", "peace", "quiet", "serene", "tranquil",
    "belleza", "calma", "cotidiana", "paz", "sereno", "tranquilo",
}


def _ascii_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def normalize_cinematic_level(value: Any) -> str:
    key = _ascii_key(value).split(" ", 1)[0].strip("-_:()")
    if key in LEVEL_SPECS:
        return key
    return _LEVEL_ALIASES.get(key, DEFAULT_LEVEL)


def cinematic_level_label(value: Any) -> str:
    return LEVEL_SPECS[normalize_cinematic_level(value)]["label"]


def _tokens(text: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _ascii_key(text)))


def _contains(tokens: set[str], words: Iterable[str]) -> bool:
    return bool(tokens.intersection(words))


def _beat_indices(count: int, level: str) -> Dict[int, str]:
    if count <= 0:
        return {}
    last = count - 1
    candidates = [
        (0, "hook"),
        (int(round(last * 0.45)), "turn"),
        (int(round(last * 0.78)), "climax"),
        (last, "resolution"),
    ]
    wanted = LEVEL_SPECS[level]["highlight_count"]
    if wanted == 2:
        candidates = [candidates[0], candidates[2]]
    elif wanted == 3:
        candidates = candidates[:3]
    beats: Dict[int, str] = {}
    for index, role in candidates:
        beats.setdefault(index, role)
    return beats


def _opening_camera(opening_style: str) -> str:
    return {
        "map_zoom_v1": "map_dive",
        "artifact_reveal_v1": "macro_reveal",
        "before_after_v1": "lateral_reveal",
        "outcome_teaser_v1": "crash_zoom",
        "hook_overlay_v1": "depth_push",
    }.get(str(opening_style or ""), "depth_push")


def _camera_for(tokens: set[str], role: str, index: int, opening_style: str) -> str:
    if index == 0:
        return _opening_camera(opening_style)
    if _contains(tokens, _MAP_WORDS):
        return "map_dive"
    if _contains(tokens, _EVIDENCE_WORDS):
        return "macro_reveal"
    if _contains(tokens, _ACTION_WORDS) or role == "climax":
        return "crash_zoom"
    if role == "resolution":
        return "pull_back"
    if role == "turn":
        return "depth_push"
    if _contains(tokens, _CALM_WORDS):
        return "slow_drift"
    return "drift_left" if index % 2 else "drift_right"


def _atmosphere_for(tokens: set[str], strength: float, preset: str) -> str:
    if preset.startswith("minimal") or strength < 0.32:
        return "none"
    if _contains(tokens, {"fire", "explosion", "battle", "war", "fuego", "batalla", "guerra"}):
        return "embers"
    if _contains(tokens, {"storm", "rain", "sea", "ocean", "tormenta", "lluvia", "mar", "oceano"}):
        return "mist"
    if _contains(tokens, _EVIDENCE_WORDS | {"ancient", "desert", "antiguo", "desierto"}):
        return "dust"
    return "fine_grain" if strength >= 0.5 else "none"


def _lighting_for(tokens: set[str], role: str, strength: float) -> str:
    if strength < 0.45:
        return "none"
    if _contains(tokens, {"fire", "explosion", "fuego", "incendio"}):
        return "fire_flicker"
    if _contains(tokens, _EVIDENCE_WORDS | _MYSTERY_WORDS):
        return "reveal_pulse"
    if role in {"hook", "turn", "climax"}:
        return "soft_pulse"
    return "none"


def _lens_for(tokens: set[str], role: str, strength: float) -> str:
    if strength < 0.5:
        return "clean"
    if role == "hook" or _contains(tokens, _EVIDENCE_WORDS):
        return "focus_reveal"
    if role in {"turn", "climax"}:
        return "lens_breathing"
    return "cinematic_vignette"


def _sound_for(role: str, existing_tag: Any, strength: float) -> str:
    tag = str(existing_tag or "").strip()
    if tag and tag.lower() not in {"none", "no", "null"}:
        return tag
    if strength < 0.55:
        return "none"
    return {
        "hook": "cinematic impact",
        "turn": "riser whoosh",
        "climax": "deep cinematic hit",
        "resolution": "low atmospheric release",
    }.get(role, "none")


def build_cinematic_plan(
    segment: MutableMapping[str, Any],
    *,
    index: int,
    count: int,
    level: Any = DEFAULT_LEVEL,
    preset: Any = "auto",
    opening_style: str = "",
) -> Dict[str, Any]:
    """Build one stable, serializable direction plan."""
    selected_level = normalize_cinematic_level(level)
    spec = LEVEL_SPECS[selected_level]
    role = _beat_indices(count, selected_level).get(index, "bridge")
    base_strength = float(spec["strength"])
    role_weight = 1.0 if role in {"hook", "turn", "climax"} else 0.68
    if role == "resolution":
        role_weight = 0.58
    strength = round(max(0.0, min(1.0, base_strength * role_weight)), 2)
    text = segment.get("narration_text") or segment.get("text") or ""
    tokens = _tokens(text)
    preset_key = _ascii_key(preset)

    return {
        "version": DIRECTOR_VERSION,
        "level": selected_level,
        "role": role,
        "intensity": strength,
        "camera": _camera_for(tokens, role, index, opening_style),
        "atmosphere": _atmosphere_for(tokens, strength, preset_key),
        "lighting": _lighting_for(tokens, role, strength),
        "lens": _lens_for(tokens, role, strength),
        "sound": _sound_for(role, segment.get("sfx_tag"), strength),
        "locked": False,
    }


def direct_storyboard(
    storyboard: MutableMapping[str, Any],
    *,
    level: Any = DEFAULT_LEVEL,
    preset: Any = "auto",
    force: bool = False,
) -> Dict[str, Any]:
    """Attach plans to all segments and return a compact summary."""
    segments = storyboard.get("segments") or []
    selected_level = normalize_cinematic_level(level)
    opening = storyboard.get("opening") or {}
    opening_style = str(opening.get("style") or storyboard.get("opening_style") or "")
    counts: Dict[str, int] = {}

    for index, segment in enumerate(segments):
        if not isinstance(segment, MutableMapping):
            continue
        current = segment.get("cinematic_plan")
        if current and current.get("locked") and not force:
            plan = current
        else:
            plan = build_cinematic_plan(
                segment,
                index=index,
                count=len(segments),
                level=selected_level,
                preset=preset,
                opening_style=opening_style,
            )
            segment["cinematic_plan"] = plan
        camera = str(plan.get("camera") or "none")
        counts[camera] = counts.get(camera, 0) + 1

    summary = {
        "version": DIRECTOR_VERSION,
        "level": selected_level,
        "label": cinematic_level_label(selected_level),
        "segments": len(segments),
        "camera_counts": counts,
    }
    storyboard["cinematic_direction"] = summary
    return summary


def plan_summary(plan: MutableMapping[str, Any] | None) -> str:
    plan = plan or {}
    return "/".join(
        str(plan.get(key) or "none")
        for key in ("camera", "atmosphere", "lighting", "lens")
    )


def _fmt(value: float) -> str:
    return f"{float(value):.5f}"


def build_ffmpeg_motion_filter(
    plan: MutableMapping[str, Any] | None,
    frames: int,
    video_size: Sequence[int],
    *,
    supersample: int = 2,
) -> str:
    """Translate a direction plan to a smooth FFmpeg zoompan filter."""
    plan = plan or {}
    camera = str(plan.get("camera") or "depth_push")
    raw_strength = plan.get("intensity", 0.65)
    strength = max(0.0, min(1.0, float(0.65 if raw_strength is None else raw_strength)))
    width, height = int(video_size[0]), int(video_size[1])
    frame_count = max(1, int(frames))
    ss = max(1, int(supersample))
    p = "0" if frame_count <= 1 else f"(on/{frame_count - 1})"
    ease = f"(({p})*({p})*(3-2*({p})))"

    zoom_ranges = {
        "slow_drift": (1.15, 1.18 + 0.03 * strength),
        "drift_left": (1.16, 1.20 + 0.03 * strength),
        "drift_right": (1.16, 1.20 + 0.03 * strength),
        "depth_push": (1.12, 1.22 + 0.08 * strength),
        "macro_reveal": (1.30 + 0.08 * strength, 1.13),
        "lateral_reveal": (1.18, 1.22 + 0.04 * strength),
        "crash_zoom": (1.08, 1.28 + 0.16 * strength),
        "map_dive": (1.04, 1.32 + 0.18 * strength),
        "pull_back": (1.28 + 0.10 * strength, 1.12),
    }
    z0, z1 = zoom_ranges.get(camera, zoom_ranges["depth_push"])
    if camera == "crash_zoom":
        progress = f"min(1,({p})*2.35)"
        shaped = f"(({progress})*({progress})*(3-2*({progress})))"
    elif camera == "map_dive":
        shaped = f"(({p})*({p}))"
    else:
        shaped = ease

    breathing = ""
    if plan.get("lens") == "lens_breathing":
        breathing = f"+{_fmt(0.0025 + 0.0025 * strength)}*sin(2*PI*({p}))"
    zoom = f"{_fmt(z0)}+({_fmt(z1 - z0)})*{shaped}{breathing}"
    span = f"(iw-iw/zoom)"
    rise = f"(ih-ih/zoom)"
    if camera in {"drift_left", "lateral_reveal"}:
        x = f"{span}*(0.68-0.36*({ease}))"
        y = f"{rise}*0.50"
    elif camera == "drift_right":
        x = f"{span}*(0.32+0.36*({ease}))"
        y = f"{rise}*0.50"
    elif camera == "slow_drift":
        x = f"{span}*(0.46+0.08*({ease}))"
        y = f"{rise}*(0.53-0.06*({ease}))"
    else:
        x = f"{span}*0.50"
        y = f"{rise}*0.50"

    prefix = f"scale={width * ss}:{height * ss}:flags=bicubic," if ss > 1 else ""
    return (
        f"{prefix}zoompan=z='{zoom}':x='{x}':y='{y}'"
        f":d={frame_count}:s={width}x{height}"
    )


def build_ffmpeg_look_filter(
    plan: MutableMapping[str, Any] | None,
    duration: float,
    preset: Any = "auto",
) -> str:
    """Return a portable FFmpeg filter chain for grade, atmosphere and lens."""
    plan = plan or {}
    raw_strength = plan.get("intensity", 0.65)
    strength = max(0.0, min(1.0, float(0.65 if raw_strength is None else raw_strength)))
    preset_key = _ascii_key(preset)
    filters: List[str] = []

    if preset_key.startswith("noir"):
        filters.extend(["hue=s=0", f"eq=contrast={1.08 + 0.12 * strength:.3f}:brightness=-0.018"])
    elif preset_key.startswith("vintage"):
        filters.extend([
            "colorchannelmixer=.90:.08:.02:0:.04:.82:.08:0:.02:.12:.72",
            f"eq=contrast={1.02 + 0.06 * strength:.3f}:saturation=0.82:brightness=0.008",
        ])
    elif preset_key.startswith("action"):
        filters.append(f"eq=contrast={1.08 + 0.12 * strength:.3f}:saturation={1.02 + 0.12 * strength:.3f}:brightness=-0.012")
    elif not preset_key.startswith("minimal"):
        filters.append(f"eq=contrast={1.03 + 0.08 * strength:.3f}:saturation={0.98 + 0.05 * strength:.3f}:brightness=-0.008")

    atmosphere = str(plan.get("atmosphere") or "none")
    if atmosphere == "fine_grain":
        filters.append(f"noise=alls={2.0 + 3.0 * strength:.2f}:allf=t+u")
    elif atmosphere == "dust":
        filters.extend([
            f"noise=alls={3.0 + 4.0 * strength:.2f}:allf=t+u",
            "colorbalance=rs=.018:gs=.008:bs=-.018",
        ])
    elif atmosphere == "mist":
        filters.extend(["gblur=sigma=0.35", "eq=contrast=0.985:brightness=0.008"])
    elif atmosphere == "embers":
        filters.extend([
            f"noise=alls={3.5 + 4.0 * strength:.2f}:allf=t+u",
            "colorbalance=rs=.035:gs=.008:bs=-.030",
        ])

    lighting = str(plan.get("lighting") or "none")
    cycle = max(1.4, min(5.0, float(duration or 3.0) * 0.72))
    if lighting == "soft_pulse":
        filters.append(
            f"eq=brightness='0.004+{0.008 + 0.010 * strength:.4f}*sin(2*PI*t/{cycle:.3f})':eval=frame"
        )
    elif lighting == "reveal_pulse":
        filters.append(
            f"eq=brightness='-0.004+{0.014 + 0.014 * strength:.4f}*sin(PI*min(t/{max(0.8, cycle * 0.5):.3f},1))':eval=frame"
        )
    elif lighting == "fire_flicker":
        filters.append(
            f"eq=brightness='0.004+{0.010 + 0.014 * strength:.4f}*sin(2*PI*t*2.7)':saturation=1.04:eval=frame"
        )

    lens = str(plan.get("lens") or "clean")
    if lens in {"cinematic_vignette", "focus_reveal", "lens_breathing"}:
        angle = max(0.42, 0.66 - 0.16 * strength)
        filters.append(f"vignette=angle={angle:.3f}:eval=frame")
    if lens == "focus_reveal":
        filters.append(f"unsharp=5:5:{0.22 + 0.28 * strength:.3f}:3:3:0")

    return ",".join(filters)
