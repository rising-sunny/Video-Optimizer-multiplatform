"""Director IA: composicion cinematografica por escena decidida por un LLM.

Cuando el usuario elige "IA Director" como dinamismo, en vez de las reglas fijas
de `segment_layouts.plan_layouts`, un LLM (DeepSeek por defecto) lee cada escena
(narracion, prompt visual, tipo de medio y duracion) y decide, como un director
cinematografico, QUE composicion lleva cada escena y por que.

Seguridad: la salida del modelo se valida y se encaja en los limites de siempre
(primera/ultima a pantalla completa, presupuesto, sin repetir composicion seguida,
escenas bloqueadas intactas). Si el modelo no responde o devuelve algo ilegible,
se cae a las reglas (`plan_layouts`) sin interrumpir el render.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import MutableMapping
from typing import Any, Dict, List, Optional, Sequence

from infra.env_loader import load_project_env
from pipeline import segment_layouts as _sl

load_project_env()

AI_LAYOUTS = ("full", "split", "pip", "reveal", "punch_in", "triptych")
_MAX_NARRATION = 220
_MAX_VISUAL = 140

_PROMPT = """Eres el director cinematografico de un video. Decide la COMPOSICION de cada escena
para maximizar el impacto visual y narrativo, como un director/productor de cine real.

Escenas (numero | duracion | medio | narracion | descripcion visual):
{segments}

Composiciones posibles (elige UNA por escena):
- full: pantalla completa (una sola imagen/video, la escena normal).
- split: pantalla dividida (contrastar dos cosas: "vs", "mientras", "sin embargo").
- pip: retrato flotante (presentar a UNA persona, lugar u objeto/evidencia que se nombra).
- reveal: una segunda imagen entra sobre la primera (un giro o una revelacion).
- punch_in: cortes que se acercan a una sola imagen (climax, accion, momento intenso).
- triptych: tres paneles (enumeraciones: "tres causas", "varias", "primero/segundo/tercero").

Reglas:
- La primera y la ultima escena van SIEMPRE a full.
- No uses la misma composicion (que no sea full) en dos escenas consecutivas.
- Usa composicion solo donde de verdad aporta: como maximo {allowed} escenas.
- Decide segun el CONTENIDO de la narracion y del prompt visual, no por costumbre.

Responde SOLO con un JSON valido, sin markdown:
{{"scenes": [{{"scene": 1, "layout": "split", "reason": "contraste entre dos bandos"}}]}}
Incluye UNA entrada por cada escena (1..{count})."""


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _segment_lines(segments: Sequence[Any], descriptions: Optional[Dict[int, str]] = None) -> str:
    descriptions = descriptions or {}
    lines: List[str] = []
    for i, seg in enumerate(segments, start=1):
        if not isinstance(seg, MutableMapping):
            continue
        narration = _clean(seg.get("narration_text") or seg.get("text") or "")[:_MAX_NARRATION]
        visual = _clean(seg.get("visual_prompt") or "")[:_MAX_VISUAL]
        seen = _clean(descriptions.get(i - 1))[:_MAX_VISUAL]
        kind = "video" if _sl.is_video_path(seg.get("video_path")) else "imagen"
        duration = _sl._segment_duration(seg)
        line = f"#{i} | {duration:.1f}s | {kind} | {narration}"
        if seen:
            line += f" | visto: {seen}"
        elif visual:
            line += f" | visual: {visual}"
        lines.append(line)
    return "\n".join(lines)


_VISION_CHUNK = 10
_VISION_PROMPT = (
    "You receive several images, one per video scene, in order. For each, write a SHORT "
    "visual description (max 10 words, English) of subject, action, framing and mood. "
    'Return ONLY JSON: {"images": [{"description": "..."}, ...]} with one entry per image, in the same order.'
)


def _describe_media(segments: Sequence[Any], log: Any) -> Dict[int, str]:
    """Gemini vision: una descripcion compacta por segmento (imagen o cuadro del video).

    Una (o pocas) llamadas a Gemini para todas las escenas. Si no hay GEMINI_API_KEY
    o falla la vision, devuelve {} y el director sigue solo con texto.
    """
    if not os.getenv("GEMINI_API_KEY"):
        return {}
    from ai.gemini_vision import ask_images
    entries: List[tuple] = []  # (indice_0, bytes)
    for i, seg in enumerate(segments):
        if not isinstance(seg, MutableMapping):
            continue
        video = str(seg.get("video_path") or "").strip()
        image = str(seg.get("image_path") or seg.get("filename") or "").strip()
        try:
            if video and os.path.exists(video):
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    png = os.path.join(td, f"frame_{i}.png")
                    _sl.frame_grab(video, png, at=0.5)
                    with open(png, "rb") as fh:
                        entries.append((i, fh.read()))
            elif image and os.path.exists(image):
                with open(image, "rb") as fh:
                    entries.append((i, fh.read()))
        except Exception as exc:
            log(f"   [Director IA] sin vision en la escena {i + 1}: {' '.join(str(exc).split())[:80]}")
    if not entries:
        return {}

    out: Dict[int, str] = {}
    for k in range(0, len(entries), _VISION_CHUNK):
        chunk = entries[k:k + _VISION_CHUNK]
        try:
            raw = ask_images(_VISION_PROMPT, [b for _, b in chunk], json_mode=True, timeout=180)
            data = json.loads(raw)
        except Exception as exc:
            log(f"   [Director IA] vision no disponible ({' '.join(str(exc).split())[:120]}): sigo sin ver.")
            break
        items = data.get("images") or data.get("descriptions") or []
        for j, item in enumerate(items):
            if j >= len(chunk):
                break
            desc = _clean(item.get("description") if isinstance(item, dict) else item)
            if desc:
                out[chunk[j][0]] = desc
    return out


def _parse_plan(raw: Any, count: int) -> Dict[int, str]:
    """Del JSON del modelo a {indice_0: layout}. Tira si no se puede leer."""
    if isinstance(raw, str):
        raw = raw.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("la respuesta no es un objeto JSON")
    scenes = raw.get("scenes") or raw.get("segments")
    if not isinstance(scenes, list):
        raise ValueError("falta la lista 'scenes'")
    out: Dict[int, str] = {}
    for item in scenes:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("scene") or item.get("index")) - 1
        except (TypeError, ValueError):
            continue
        layout = _sl.normalize_layout(item.get("layout"))
        if 0 <= index < count and layout in AI_LAYOUTS:
            out[index] = layout
    if not out:
        raise ValueError("no se pudo leer ninguna escena del plan")
    return out


def _apply_plan(storyboard: MutableMapping[str, Any], segments: Sequence[Any],
                plan: Dict[int, str], allowed: int, level: str) -> Dict[str, int]:
    """Escribe `layout_plan` en cada escena respetando reglas y presupuesto."""
    count = len(segments)
    chosen = 0
    prev_layout = ""
    counts: Dict[str, int] = {"full": 0}

    for index, segment in enumerate(segments):
        if not isinstance(segment, MutableMapping):
            continue
        current = segment.get("layout_plan")
        locked = bool(isinstance(current, dict) and current.get("locked"))
        ai_layout = plan.get(index, "full")
        reason = "ai_director"

        # Primera/ultima, muy cortas o bloqueadas: pantalla completa (o lo fijado a mano).
        if locked:
            ai_layout = _sl.normalize_layout((current or {}).get("layout", "full"))
            reason = "locked"
        elif index in (0, count - 1) or segment.get("cover_frame") \
                or _sl._segment_duration(segment) < _sl.MIN_LAYOUT_SECONDS:
            ai_layout = "full"
            reason = "boundary" if index in (0, count - 1) else "short"
        # Presupuesto: sin cupo, todo lo que no sea full vuelve a full.
        elif ai_layout != "full" and chosen >= allowed:
            ai_layout = "full"
            reason = "budget"
        # No repetir la composicion consecutiva.
        elif ai_layout != "full" and ai_layout == prev_layout:
            ai_layout = "full"
            reason = "repeat"
        elif ai_layout != "full":
            chosen += 1

        plan_dict: Dict[str, Any] = {
            "version": _sl.LAYOUT_VERSION,
            "layout": ai_layout,
            "reason": reason,
            "tag": "",
            "locked": locked,
            "ai": True,
        }
        # La media extra elegida a mano sobrevive.
        if isinstance(current, dict) and current.get("extra_media"):
            plan_dict["extra_media"] = list(current["extra_media"])
        segment["layout_plan"] = plan_dict
        counts[ai_layout] = counts.get(ai_layout, 0) + 1
        prev_layout = ai_layout

    return counts


def direct_layouts_with_ai(
    storyboard: MutableMapping[str, Any],
    *,
    level: Any = "ai",
    log: Any = print,
    client: Any = None,
) -> Dict[str, Any]:
    """Composicion por escena con LLM; cae a `plan_layouts` si algo falla.

    `client` permite inyectar el LLM en tests. Por defecto usa `DeepSeekClient`.
    """
    segments = storyboard.get("segments") or []
    count = len(segments)

    # Sin DeepSeek configurado: las reglas (mismo presupuesto que 'ai').
    if client is None and not os.getenv("DEEPSEEK_API_KEY"):
        log("   [Director IA] sin DEEPSEEK_API_KEY: uso las reglas.")
        return _sl.plan_layouts(storyboard, level=level)

    try:
        if client is None:
            from ai.deepseek_client import DeepSeekClient
            client = DeepSeekClient()
        budget = float(_sl.DYNAMISM_SPECS.get(str(level), _sl.DYNAMISM_SPECS["high"])["budget"])
        # La primera y la ultima no cuentan para el presupuesto de composicion.
        eligible = max(0, count - 2)
        allowed = max(0, int(round(eligible * budget)))
        # Ojos (Gemini vision): que ve cada imagen/cuadro antes de dirigir.
        descriptions = _describe_media(segments, log)
        prompt = _PROMPT.format(
            segments=_segment_lines(segments, descriptions) or "(sin escenas)",
            allowed=allowed,
            count=count,
        )
        raw = client._generate(prompt, max_tokens=8000, task_type="script_quality", json_mode=True,
                               model="deepseek-chat")
        if not raw:
            raise RuntimeError("el modelo no respondio")
        plan = _parse_plan(raw, count)
    except Exception as exc:
        log(f"   [Director IA] no disponible ({' '.join(str(exc).split())[:140]}): uso las reglas.")
        return _sl.plan_layouts(storyboard, level=level)

    counts = _apply_plan(storyboard, segments, plan, allowed, str(level))
    summary = {
        "version": _sl.LAYOUT_VERSION,
        "level": str(level),
        "label": "IA Director",
        "segments": count,
        "counts": counts,
        "director": "ai",
    }
    storyboard["layout_direction"] = summary
    log(f"   Director IA: {_sl.plan_summary_text(summary)}")
    return summary
