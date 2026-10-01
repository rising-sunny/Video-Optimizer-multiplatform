# -*- coding: utf-8 -*-
"""Direccion de arte para los prompts de imagen de cada segmento.

Para que (2026-09-24). El usuario copia el prompt de cada segmento del editor de
timeline ("Copiar Prompts") y lo pega en una IA de imagen externa. Ese prompt
salia del armado para el proveedor interno (FLUX por defecto): refuerzos de
FLUX, sufijo de variacion, negative prompt en etiquetas, y un visual_prompt
escrito por el mismo modelo del guion en una sola pasada, con cada escena
eligiendo luz y paleta por su cuenta (azul marino, despues pizarra, despues
cobre) y sin los detalles que hacen creible una imagen historica.

Como funciona, en dos pasos:

  1. Biblia visual del video (una vez, desde el guion completo): epoca, lugar,
     clima y hora reales; aspecto DOCUMENTADO de cada personaje (a Nelson le
     falta el brazo derecho; nunca uso parche en el ojo); barcos, armas y
     edificios; la paleta del video en tres actos con colores nombrados; la
     camara y el look; y los mitos visuales que hay que evitar.
  2. Un plano por segmento: el momento EXACTO que narra ese segmento (la
     narracion ya verificada, no la version con errores), tamano de plano,
     angulo y lente, capas de profundidad, luz con fuente, direccion y
     temperatura, la paleta del acto, atmosfera, emocion y detalles de epoca.
     Los planos varian entre escenas (no siete primeros planos seguidos).

`compose_prompt` arma el texto final en prosa en ingles, por secciones, pensado
para IAs externas (ChatGPT, Gemini, Midjourney), con las zonas libres para el
texto de gancho (escena 1) y los subtitulos.

Se guarda en el storyboard (`visual_bible`) y en cada segmento (`art_direction`)
con una firma: si cambia la narracion o el visual_prompt del segmento, ese plano
se rehace. Funciones puras con el modelo inyectable; ver
`test_visual_art_direction.py`. VISUAL_ART_DIRECTION=0 vuelve al prompt viejo.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

VERSION = 2                  # 2: cada plano trae tambien su movimiento (prompt de video)
SHOTS_PER_CALL = 10          # planos por consulta al modelo (guiones largos van por tandas)

# Zonas que el video tapa con texto (video_opening.HOOK_ZONE y los subtitulos).
HOOK_ZONE_TEXT = {
    "9:16": "keep the upper band (roughly 12-36% from the top) as calm, uncluttered sky, haze or shadow "
            "for a headline; place the main subject in the middle and lower-middle of the frame",
    "16:9": "keep the upper band (roughly 8-42% from the top on the left or right third) calm and uncluttered "
            "for a headline",
}
SUBTITLE_TEXT = ("keep the lower quarter free of faces and key details (subtitles go there); nothing important "
                 "near the edges")

BASE_AVOID = ["any text, letters, captions, logos or watermarks", "modern objects or clothing",
              "extra or malformed fingers and limbs", "plastic CGI skin", "cartoonish exaggeration"]


def enabled() -> bool:
    return str(os.getenv("VISUAL_ART_DIRECTION", "1")).strip().lower() not in ("0", "false", "no", "off")


# ------------------------------------------------------------------ utilidades

def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def segment_narration(seg: Dict) -> str:
    for key in ("narration_text", "narration", "text"):
        val = (seg or {}).get(key)
        if isinstance(val, str) and val.strip():
            return _norm(val)
    return ""


def _signature(*parts: Any) -> str:
    import hashlib
    raw = "␞".join(_norm(p).lower() for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def bible_signature(storyboard: Dict) -> str:
    segs = (storyboard or {}).get("segments") or []
    return _signature((storyboard or {}).get("topic"), *[segment_narration(s) for s in segs])


def shot_signature(seg: Dict, bible_sig: str) -> str:
    return _signature(VERSION, segment_narration(seg), (seg or {}).get("visual_prompt"),
                      (seg or {}).get("motion_prompt"), bible_sig)


def segment_duration(seg: Dict) -> float:
    """Duracion del segmento en segundos (campo duration, o fin - inicio)."""
    seg = seg or {}
    for key in ("duration",):
        try:
            val = float(seg.get(key) or 0)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    for a, b in (("end", "start"), ("end_time", "start_time"), ("timestamp_end", "timestamp_start")):
        try:
            val = float(seg.get(a) or 0) - float(seg.get(b) or 0)
            if val > 0:
                return val
        except (TypeError, ValueError):
            continue
    return 0.0


def aspect_key(aspect: str) -> str:
    return "16:9" if str(aspect or "").strip() in ("16:9", "horizontal", "landscape") else (
        "1:1" if str(aspect or "").strip() == "1:1" else "9:16")


def _parse_obj(raw: Any) -> Optional[Dict]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if m:
            text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    chunk = text[start:end + 1]
    for candidate in (chunk, re.sub(r",\s*([}\]])", r"\1", chunk)):
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [_norm(v) for v in value if _norm(v)]
    return [_norm(v) for v in re.split(r"[;\n]", str(value or "")) if _norm(v)]


# ------------------------------------------------------------------ biblia visual

def build_bible_prompt(topic: str, script: str, style: str = "", aspect: str = "9:16",
                       scene_count: int = 0) -> str:
    look = style if style and style.lower() not in ("photorealism", "realistic image") else \
        "photorealistic cinematic film still (documentary reenactment, not illustration)"
    return f"""You are the director of photography and historical art director of a history video.
Topic: "{topic}". Format: {aspect_key(aspect)} {"vertical" if aspect_key(aspect) == "9:16" else "frame"}. Visual style: {look}.
The video has {scene_count} scenes; the narration below is fact-checked.

NARRATION:
{script}

Write the VISUAL BIBLE every image of this video must follow, so the images look like one film and are
historically right. Be specific and DOCUMENTED (use what historians and museums record; if unsure, stay generic):
- era and exact date; place; real weather, sea/terrain and time of day of the events (e.g. light winds and a heavy
  swell, gunsmoke haze by afternoon);
- each recurring person: age, rank and injuries AT THAT DATE, build, face, hair, exact period costume and
  insignia; and myths to AVOID (e.g. Nelson in 1805: Vice-Admiral, right arm amputated, right eye blind but normal
  looking, never an eyepatch). Double-check rank, age and injuries; omit a detail rather than guess it;
- key objects (ships, weapons, vehicles, buildings): documented colors, materials, markings;
- a palette arc in three acts across the scenes: for each act, which scenes, 3-4 named colors with hex codes, and
  the light (source, quality, color temperature in K);
- one camera/look for the whole film: camera, lens family, film stock/grain, grade;
- anachronisms and clichés to avoid.

Return ONLY this JSON:
{{"era": "...", "place": "...", "conditions": "...",
  "characters": [{{"name": "...", "appearance": "...", "costume": "...", "avoid": "..."}}],
  "objects": [{{"name": "...", "look": "..."}}],
  "palette_arc": [{{"act": "setup|confrontation|resolution", "scenes": "1-3", "colors": ["name #RRGGBB"], "light": "..."}}],
  "look": {{"camera": "...", "lens": "...", "film": "...", "grade": "..."}},
  "avoid": ["..."]}}"""


def parse_bible(raw: Any) -> Optional[Dict]:
    obj = _parse_obj(raw)
    if not obj or not (obj.get("era") or obj.get("palette_arc") or obj.get("characters")):
        return None
    obj.setdefault("characters", [])
    obj.setdefault("objects", [])
    obj.setdefault("palette_arc", [])
    obj.setdefault("look", {})
    obj["avoid"] = _as_list(obj.get("avoid"))
    return obj


def act_for_scene(bible: Dict, scene_no: int, total: int) -> Dict:
    """El acto de la paleta que le toca a una escena (por el rango 'scenes' o por tercios)."""
    acts = [a for a in (bible or {}).get("palette_arc") or [] if isinstance(a, dict)]
    for act in acts:
        m = re.match(r"\s*(\d+)\s*(?:-|–|to)\s*(\d+)", str(act.get("scenes") or ""))
        if m and int(m.group(1)) <= scene_no <= int(m.group(2)):
            return act
        if str(act.get("scenes") or "").strip() == str(scene_no):
            return act
    if not acts:
        return {}
    third = min(len(acts) - 1, int((scene_no - 1) * len(acts) / max(1, total)))
    return acts[third]


def _bible_brief(bible: Dict) -> str:
    """La biblia en texto compacto para el pedido de planos."""
    lines = [f"Era: {bible.get('era', '')}. Place: {bible.get('place', '')}. Conditions: {bible.get('conditions', '')}."]
    for c in bible.get("characters") or []:
        if isinstance(c, dict):
            lines.append(f"- {c.get('name')}: {c.get('appearance', '')}; costume: {c.get('costume', '')}"
                         + (f"; avoid: {c.get('avoid')}" if c.get("avoid") else ""))
    for o in bible.get("objects") or []:
        if isinstance(o, dict):
            lines.append(f"- {o.get('name')}: {o.get('look', '')}")
    for a in bible.get("palette_arc") or []:
        if isinstance(a, dict):
            lines.append(f"Act {a.get('act')} (scenes {a.get('scenes')}): colors {', '.join(_as_list(a.get('colors')))}; "
                         f"light {a.get('light', '')}")
    look = bible.get("look") or {}
    if look:
        lines.append("Look: " + "; ".join(f"{k} {v}" for k, v in look.items() if v))
    if bible.get("avoid"):
        lines.append("Avoid: " + "; ".join(bible["avoid"]))
    return "\n".join(lines)


# ------------------------------------------------------------------ planos

def build_shots_prompt(bible: Dict, narrations: Sequence[str], indices: Sequence[int], topic: str,
                       aspect: str = "9:16", existing: Optional[Dict[int, str]] = None,
                       motions: Optional[Dict[int, str]] = None) -> str:
    total = len(narrations)
    story = "\n".join(f"Scene {i + 1}: {t}" for i, t in enumerate(narrations))
    wanted = ", ".join(str(i + 1) for i in indices)
    hints = ""
    if existing:
        hints = "\nCurrent image ideas (keep a good idea, fix what is vague or wrong):\n" + "\n".join(
            f"Scene {i + 1}: {existing[i][:300]}" for i in indices if existing.get(i))
    if motions:
        hints += "\nCurrent motion ideas (keep a good idea):\n" + "\n".join(
            f"Scene {i + 1}: {motions[i][:200]}" for i in indices if motions.get(i))
    return f"""You are the director of photography of a history video about "{topic}" ({aspect_key(aspect)}).
Design ONE photographic still for each of these scenes: {wanted} (of {total}).

VISUAL BIBLE (follow it: same people, costumes, objects, palette arc and look in every scene):
{_bible_brief(bible)}

FULL NARRATION (each image must show the exact beat of ITS scene, as the viewer hears it):
{story}
{hints}
Rules:
- Show what the scene's narration says happened, never a claim it does not make. A rhetorical question becomes
  the most striking image of the subject.
- Vary shot sizes and angles across consecutive scenes (extreme wide, wide, medium, close-up, detail insert,
  over-the-shoulder, high/low angle); no two neighbors with the same framing.
- Scene 1 is the hook: the single most arresting, readable image of the video. A headline covers its upper
  third, so frame it medium or medium-wide with clear headroom (sky, haze or shadow), never an extreme close-up.
- Light must be physically plausible for the time and weather of that moment (source, direction, quality, K).
- Use the palette of the scene's act; name colors with hex codes.
- Put concrete period details on screen (insignia, rigging, weapons, materials), never modern ones.
- Depth: say what is in the foreground, midground and background.

Each still is also the FIRST FRAME of a 5-10 s AI video clip of that scene. Describe its motion:
- camera_move: ONE slow, smooth, physically plausible move with direction and speed (slow push-in, pull-back,
  lateral dolly, crane up/down, a few degrees of orbit; handheld drift only for tension). Scene 1: a slow
  push-in or gentle drift that keeps its headline band calm.
- subject_motion: small natural movement AI video renders well (breathing, a head turn, eyes narrowing, a hand
  tightening on a rail, a coat stirring in the wind). Never complex action: no fighting, running crowds,
  detailed hand gestures, walking toward the camera or talking.
- environment_motion: what moves around them and carries the life of the shot (drifting smoke, sails and flags
  in the wind, swell lifting the hull, embers, dust in light shafts, flickering lanterns).
- pace: slow, measured or urgent, matching the narration.
- sound: ambient effects only (creaking timbers, distant cannon, wind); no music, no voices.

Return ONLY this JSON:
{{"shots": [{{"scene": <number>, "moment": "<the exact beat shown, one sentence>",
  "subject": "<who/what, with appearance and costume from the bible>", "action": "<what they are doing>",
  "setting": "<place, weather, time of day>", "shot": "<shot size and angle>", "lens": "<focal length, aperture>",
  "depth": "<foreground; midground; background>", "lighting": "<key source and direction, quality, fill, color temperature>",
  "palette": ["name #RRGGBB"], "atmosphere": "<smoke, spray, dust, haze, particles>",
  "mood": "<emotion>", "details": "<period-accurate specifics visible in frame>", "avoid": ["<scene-specific mistakes>"],
  "camera_move": "...", "subject_motion": "...", "environment_motion": "...", "pace": "...", "sound": "..."}}]}}"""


def parse_shots(raw: Any, total: int) -> Dict[int, Dict]:
    """{indice_0: plano}. Ignora escenas fuera de rango o sin momento/sujeto."""
    obj = _parse_obj(raw)
    out: Dict[int, Dict] = {}
    for shot in (obj or {}).get("shots") or []:
        if not isinstance(shot, dict):
            continue
        try:
            idx = int(shot.get("scene")) - 1
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < total) or not (shot.get("moment") or shot.get("subject")):
            continue
        shot = dict(shot)
        shot["palette"] = _as_list(shot.get("palette"))
        shot["avoid"] = _as_list(shot.get("avoid"))
        out[idx] = shot
    return out


# ------------------------------------------------------------------ prompt final

def _clause(text: Any) -> str:
    """Frase sin puntuacion final, para unir con ';' o ','."""
    return _norm(text).rstrip(" .;,")


def _sentence(text: Any) -> str:
    t = _clause(text)
    return (t[0].upper() + t[1:] + ".") if t else ""


def _clean_avoid(item: Any) -> str:
    """'No bright colors; keep tones organic (e.g. ...)' -> 'bright colors'.

    Un "No ..." dentro de una lista de cosas a evitar (o de un negative prompt) es
    un doble negativo que confunde al modelo; la aclaracion despues del ';' tampoco suma.
    """
    text = re.sub(r"\s*\([^)]*\)", "", str(item or ""))
    text = re.split(r"\s*;\s*", text)[0]
    text = re.sub(r"^(?:no|avoid|don't|do not|never)\s+", "", text.strip(), flags=re.I)
    return _clause(text)


def _avoid_items(shot: Dict, bible: Dict, n_shot: int = 4, n_bible: int = 6) -> List[str]:
    """Lo que hay que evitar: lo de la escena, lo del video y lo de siempre, sin repetidos."""
    items: List[str] = []
    seen = set()
    for item in _as_list(shot.get("avoid"))[:n_shot] + list(bible.get("avoid") or [])[:n_bible] + BASE_AVOID:
        item = _clean_avoid(item)
        key = re.sub(r"[^a-z]+", " ", item.lower()).strip()
        if key and not any(key in k or k in key for k in seen):
            seen.add(key)
            items.append(item)
    return items


def compose_prompt(shot: Dict, bible: Dict, *, scene_no: int, total: int, aspect: str = "9:16",
                   style: str = "", is_opening: bool = False) -> str:
    """Prompt final en prosa, por secciones, para una IA de imagen externa."""
    ak = aspect_key(aspect)
    orientation = {"9:16": "Vertical 9:16", "16:9": "Horizontal 16:9", "1:1": "Square 1:1"}[ak]
    look = bible.get("look") or {}
    medium = style if style and style.lower() not in ("photorealism", "realistic image") else \
        "photorealistic cinematic film still, documentary reenactment"
    act = act_for_scene(bible, scene_no, total)
    palette = shot.get("palette") or _as_list(act.get("colors"))

    parts = [f"{orientation} {medium}."]
    if shot.get("moment"):
        parts.append(f"Scene: {_sentence(shot.get('moment'))}")
    if shot.get("subject"):
        parts.append(f"Subject: {_sentence(shot.get('subject'))}")
    if shot.get("action"):
        parts.append(f"Action: {_sentence(shot.get('action'))}")
    setting = _clause(shot.get("setting")) or ", ".join(
        p for p in (_clause(bible.get("place")), _clause(bible.get("era"))) if p)
    if setting:
        parts.append(f"Setting: {_sentence(setting)}")

    comp = [_clause(shot.get(k)) for k in ("shot", "lens", "depth")]
    if is_opening:
        comp.append(HOOK_ZONE_TEXT.get(ak, ""))
    if ak == "9:16":
        comp.append(SUBTITLE_TEXT)
    comp = [c for c in comp if c]
    if comp:
        parts.append("Composition: " + _sentence("; ".join(comp)))

    light = _clause(shot.get("lighting")) or _clause(act.get("light"))
    if light:
        parts.append(f"Lighting: {_sentence(light)}")
    if palette:
        parts.append("Color palette: " + ", ".join(_clause(c) for c in palette) + ".")
    atmo = "; ".join(p for p in (_clause(shot.get("atmosphere")),
                                 f"mood: {_clause(shot.get('mood'))}" if _clause(shot.get("mood")) else "") if p)
    if atmo:
        parts.append(f"Atmosphere: {_sentence(atmo)}")
    if shot.get("details"):
        parts.append(f"Period details: {_sentence(shot.get('details'))}")
    camera = "; ".join(_clause(look.get(k)) for k in ("camera", "lens", "film", "grade") if _clause(look.get(k)))
    if camera:
        parts.append(f"Camera and look: {_sentence(camera)}")
    parts.append("Avoid: " + "; ".join(_avoid_items(shot, bible)) + ".")
    return "\n".join(parts)


def negative_prompt(shot: Dict, bible: Dict) -> str:
    """Negative prompt en frases cortas (para las IAs que lo aceptan aparte)."""
    items = []
    for item in _avoid_items(shot, bible) + ["blurry", "low resolution", "oversaturated", "deformed hands"]:
        short = re.sub(r"\s*\([^)]*\)", "", item)          # sin aclaraciones entre parentesis
        short = re.split(r"\s+(?:like|such as|because|since)\s+", short)[0]
        short = _clause(short)
        if short and short.lower() not in (i.lower() for i in items):
            items.append(short)
    return ", ".join(items)


# ------------------------------------------------------------------ modelo

def default_llm(log: Callable = print) -> Callable[[str], Any]:
    """Gemini (sabe historia y escribe bien) -> Groq. Salta modelos sin cuota por un rato."""
    try:
        from ai.script_fact_check import _gemini_models, _cooling, _is_capacity_error, _UNAVAILABLE
    except Exception:
        _gemini_models, _cooling, _is_capacity_error, _UNAVAILABLE = (lambda: [], lambda n: False,
                                                                      lambda e: False, {})

    def ask(prompt: str) -> Any:
        if os.getenv("GEMINI_API_KEY"):
            from ai.gemini_vision import ask_images
            for model in _gemini_models():
                name = f"art:{model}"
                if _cooling(name):
                    continue
                for attempt in range(2):
                    try:
                        return ask_images(prompt, [], model=model, json_mode=True, timeout=150, temperature=0.6)
                    except Exception as exc:
                        text = str(exc)
                        if attempt == 0 and ("503" in text or "high demand" in text.lower()):
                            time.sleep(3)          # demanda alta: suele pasar en segundos
                            continue
                        if _is_capacity_error(exc):
                            _UNAVAILABLE[name] = time.time()
                        log(f"   [Arte] {model} no disponible: {' '.join(text.split())[:100]}")
                        break
        if os.getenv("GROQ_API_KEY"):
            from ai.groq_client import GroqAiClient
            return GroqAiClient()._generate(prompt, max_tokens=6000, task_type="script_quality", json_mode=True)
        return None
    return ask


# ------------------------------------------------------------------ orquestacion

def needs_work(storyboard: Dict, indices: Sequence[int]) -> bool:
    """Hace falta consultar al modelo para estos segmentos? (para mostrar espera en la UI)."""
    sb = storyboard or {}
    bible = sb.get("visual_bible") or {}
    bsig = bible_signature(sb)
    if not bible or bible.get("_signature") != bsig:
        return True
    segs = sb.get("segments") or []
    for i in indices:
        if 0 <= i < len(segs):
            art = segs[i].get("art_direction") or {}
            if art.get("_signature") != shot_signature(segs[i], bsig):
                return True
    return False


def ensure_art_direction(storyboard: Dict, indices: Sequence[int], *, llm: Optional[Callable] = None,
                         aspect: str = "9:16", style: str = "", log: Callable = print) -> List[int]:
    """Deja `visual_bible` y `art_direction` al dia para esos segmentos. Devuelve los listos.

    Muta el storyboard (y los dicts de segmentos que contiene). Si el modelo
    falla, devuelve los que ya estaban al dia y el llamador cae al prompt viejo.
    """
    sb = storyboard
    segs = sb.get("segments") or []
    narrations = [segment_narration(s) for s in segs]
    if not any(narrations):
        return []
    llm = llm or default_llm(log)
    topic = _norm(sb.get("topic") or sb.get("title"))
    bsig = bible_signature(sb)
    bible = sb.get("visual_bible") or {}
    if not bible or bible.get("_signature") != bsig:
        log("   [Arte] armando la biblia visual del video (epoca, personajes, paleta, luz)...")
        script = "\n".join(f"Scene {i + 1}: {t}" for i, t in enumerate(narrations) if t)
        try:
            bible = parse_bible(llm(build_bible_prompt(topic, script, style, aspect, len(segs))))
        except Exception as exc:
            log(f"   [Arte] no se pudo armar la biblia visual: {exc}")
            bible = None
        if not bible:
            return []
        bible["_signature"] = bsig
        bible["_version"] = VERSION
        sb["visual_bible"] = bible

    wanted = [i for i in indices if 0 <= i < len(segs) and narrations[i]]
    stale = [i for i in wanted
             if (segs[i].get("art_direction") or {}).get("_signature") != shot_signature(segs[i], bsig)]
    for start in range(0, len(stale), SHOTS_PER_CALL):
        batch = stale[start:start + SHOTS_PER_CALL]
        existing = {i: _norm(segs[i].get("visual_prompt")) for i in batch}
        motions = {i: _norm(segs[i].get("motion_prompt")) for i in batch if _norm(segs[i].get("motion_prompt"))}
        shots: Dict[int, Dict] = {}
        for attempt in range(2):     # una respuesta vacia o ilegible se reintenta una vez
            try:
                shots = parse_shots(llm(build_shots_prompt(bible, narrations, batch, topic, aspect, existing,
                                                           motions)), len(segs))
            except Exception as exc:
                log(f"   [Arte] no se pudieron disenar los planos {batch[0] + 1}-{batch[-1] + 1}: {exc}")
                shots = {}
            if shots:
                break
        for i in batch:
            if i in shots:
                shot = shots[i]
                shot["_signature"] = shot_signature(segs[i], bsig)
                segs[i]["art_direction"] = shot
    return [i for i in wanted
            if (segs[i].get("art_direction") or {}).get("_signature") == shot_signature(segs[i], bsig)]


def prompt_for_segment(storyboard: Dict, index: int, *, aspect: str = "9:16", style: str = "") -> Optional[Dict]:
    """{'prompt', 'negative_prompt'} para copiar, o None si el plano no esta al dia."""
    segs = (storyboard or {}).get("segments") or []
    bible = (storyboard or {}).get("visual_bible") or {}
    if not (0 <= index < len(segs)) or not bible:
        return None
    seg = segs[index]
    shot = seg.get("art_direction") or {}
    if shot.get("_signature") != shot_signature(seg, bible_signature(storyboard)):
        return None
    is_opening = index == 0 or bool(seg.get("hook_overlay"))
    return {
        "prompt": compose_prompt(shot, bible, scene_no=index + 1, total=len(segs), aspect=aspect,
                                 style=style, is_opening=is_opening),
        "negative_prompt": negative_prompt(shot, bible),
    }


# ------------------------------------------------------------------ video

VIDEO_AVOID = ["morphing or melting faces", "warping hands or extra fingers", "extra limbs", "flicker",
               "sudden cuts or scene changes", "text or subtitles on screen", "camera shake unless asked",
               "objects appearing or vanishing"]
DEFAULT_CAMERA_MOVE = "slow, smooth push-in over the whole clip"


def _duration_text(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "5-10 seconds"
    return f"about {max(3, int(round(seconds)))} seconds"


def motion_only(shot: Dict) -> str:
    """Solo movimiento: para animar la imagen del segmento (imagen a video)."""
    parts = [
        _sentence(shot.get("camera_move") or DEFAULT_CAMERA_MOVE),
        _sentence(shot.get("subject_motion")),
        _sentence(shot.get("environment_motion")),
        _sentence(f"pace: {_clause(shot.get('pace'))}") if _clause(shot.get("pace")) else "",
        "Keep the look, lighting and composition of the image; one continuous shot, no cuts.",
    ]
    return " ".join(p for p in parts if p)


def compose_video_prompt(shot: Dict, bible: Dict, *, scene_no: int, total: int, aspect: str = "9:16",
                         style: str = "", is_opening: bool = False, duration: float = 0.0) -> str:
    """Prompt de video (texto a video) en prosa por secciones, para una IA de video externa."""
    ak = aspect_key(aspect)
    orientation = {"9:16": "Vertical 9:16", "16:9": "Horizontal 16:9", "1:1": "Square 1:1"}[ak]
    medium = style if style and style.lower() not in ("photorealism", "realistic image") else \
        "photorealistic documentary reenactment"
    act = act_for_scene(bible, scene_no, total)
    palette = shot.get("palette") or _as_list(act.get("colors"))
    look = bible.get("look") or {}

    parts = [f"{orientation} cinematic video clip, {_duration_text(duration)}, one continuous shot, "
             f"{medium}, 24 fps film look."]
    frame = [_clause(shot.get("moment")), _clause(shot.get("subject")), _clause(shot.get("setting"))]
    framing = ", ".join(p for p in (_clause(shot.get("shot")), _clause(shot.get("lens"))) if p)
    if framing:
        frame.append(f"framing {framing}")
    frame = [f for f in frame if f]
    if frame:
        parts.append("Opening frame: " + _sentence("; ".join(frame)))
    parts.append(f"Camera: {_sentence(shot.get('camera_move') or DEFAULT_CAMERA_MOVE)}")
    if shot.get("subject_motion"):
        parts.append(f"Subject motion: {_sentence(shot.get('subject_motion'))}")
    if shot.get("environment_motion"):
        parts.append(f"Environment motion: {_sentence(shot.get('environment_motion'))}")
    light = _clause(shot.get("lighting")) or _clause(act.get("light"))
    color = "; ".join(p for p in (light, ("palette " + ", ".join(_clause(c) for c in palette)) if palette else "")
                      if p)
    if color:
        parts.append(f"Lighting and color: {_sentence(color + '; constant through the clip')}")
    if shot.get("pace"):
        parts.append(f"Pace: {_sentence(shot.get('pace'))}")
    zones = []
    if is_opening:
        zones.append("keep the upper band (12-36% from the top) calm for the first 2 seconds, a headline sits there")
    if ak == "9:16":
        zones.append("keep faces and key action out of the lower quarter (subtitles)")
    if zones:
        parts.append("Frame zones: " + _sentence("; ".join(zones)))
    sound = _clause(shot.get("sound"))
    parts.append("Sound (only if the tool generates audio): "
                 + _sentence((sound + "; " if sound else "") + "no dialogue, no narration, no music"))
    camera = "; ".join(_clause(look.get(k)) for k in ("film", "grade") if _clause(look.get(k)))
    if camera:
        parts.append(f"Look: {_sentence(camera)}")
    avoid = []
    seen = set()
    for item in VIDEO_AVOID + _avoid_items(shot, bible, n_shot=3, n_bible=4):
        key = item.lower()
        if key not in seen:
            seen.add(key)
            avoid.append(_clause(item))
    parts.append("Avoid: " + "; ".join(avoid) + ".")
    return "\n".join(parts)


def video_negative_prompt(shot: Dict, bible: Dict) -> str:
    items = ["morphing", "melting faces", "warped hands", "extra fingers", "extra limbs", "flicker", "jitter",
             "sudden cuts", "text", "subtitles", "watermark"]
    for item in negative_prompt(shot, bible).split(", "):
        if item and item.lower() not in (i.lower() for i in items):
            items.append(item)
    return ", ".join(items)


def fallback_video_prompt(seg: Dict, *, aspect: str = "9:16", is_opening: bool = False) -> Dict[str, str]:
    """Sin direccion de arte (modelo caido): prompt de video armado con lo que ya tiene el segmento."""
    ak = aspect_key(aspect)
    orientation = {"9:16": "Vertical 9:16", "16:9": "Horizontal 16:9", "1:1": "Square 1:1"}[ak]
    visual = _clause(re.sub(r"\b(?:vertical|horizontal)\s+\d+:\d+,?\s*", "", str((seg or {}).get("visual_prompt") or ""),
                            flags=re.I))
    motion = _clause((seg or {}).get("motion_prompt")) or DEFAULT_CAMERA_MOVE
    parts = [f"{orientation} cinematic video clip, {_duration_text(segment_duration(seg))}, one continuous shot, "
             "photorealistic documentary reenactment, 24 fps film look."]
    if visual:
        parts.append(f"Opening frame: {_sentence(visual[:900])}")
    parts.append(f"Motion: {_sentence(motion)}")
    if is_opening:
        parts.append("Frame zones: keep the upper band calm for the first 2 seconds (headline).")
    parts.append("Sound (only if the tool generates audio): ambient effects only; no dialogue, no narration, no music.")
    parts.append("Avoid: " + "; ".join(VIDEO_AVOID + BASE_AVOID) + ".")
    return {"prompt": "\n".join(parts), "motion_only": _sentence(motion) + " Keep the look of the image; no cuts.",
            "negative_prompt": "morphing, melting faces, warped hands, extra fingers, flicker, sudden cuts, text, "
                               "watermark, modern objects",
            "duration": segment_duration(seg)}


def video_prompt_for_segment(storyboard: Dict, index: int, *, aspect: str = "9:16",
                             style: str = "") -> Optional[Dict]:
    """{'prompt', 'motion_only', 'negative_prompt', 'duration'} para copiar, o None si el plano no esta al dia."""
    segs = (storyboard or {}).get("segments") or []
    bible = (storyboard or {}).get("visual_bible") or {}
    if not (0 <= index < len(segs)) or not bible:
        return None
    seg = segs[index]
    shot = seg.get("art_direction") or {}
    if shot.get("_signature") != shot_signature(seg, bible_signature(storyboard)):
        return None
    is_opening = index == 0 or bool(seg.get("hook_overlay"))
    duration = segment_duration(seg)
    return {
        "prompt": compose_video_prompt(shot, bible, scene_no=index + 1, total=len(segs), aspect=aspect,
                                       style=style, is_opening=is_opening, duration=duration),
        "motion_only": motion_only(shot),
        "negative_prompt": video_negative_prompt(shot, bible),
        "duration": duration,
    }


def video_clipboard_text(data: Dict, format_label: str) -> str:
    """Texto para el portapapeles: prompt completo, solo movimiento y negative."""
    dur = data.get("duration") or 0
    head = f"Formato: {format_label}" + (f" · Duracion del segmento: {dur:.1f} s" if dur else "")
    return (f"{head}\n\n"
            f"Prompt de video (texto a video):\n{data['prompt']}\n\n"
            f"Solo movimiento (imagen a video: anima la imagen de este segmento):\n{data['motion_only']}\n\n"
            f"Negative Prompt:\n{data['negative_prompt']}")


__all__ = [
    "compose_video_prompt", "video_negative_prompt", "fallback_video_prompt", "video_prompt_for_segment",
    "video_clipboard_text", "motion_only", "segment_duration",
    "enabled", "build_bible_prompt", "parse_bible", "act_for_scene", "build_shots_prompt", "parse_shots",
    "compose_prompt", "negative_prompt", "default_llm", "needs_work", "ensure_art_direction",
    "prompt_for_segment", "bible_signature", "shot_signature", "segment_narration",
]
