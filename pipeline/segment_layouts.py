"""Composicion por segmento: varias imagenes en pantalla, entradas animadas, cortes internos.

Tres partes, todas sin LLM:

- `plan_layouts()` decide que composicion lleva cada escena del storyboard (reglas
  sobre el texto, el papel narrativo y la duracion), igual que el director
  cinematografico decide la camara. Respeta lo fijado a mano en el timeline.
- `resolve_layout_sources()` elige de donde salen los paneles extra: media extra
  asignada a mano, las imagenes de las escenas vecinas o un detalle de la misma
  imagen. Nunca genera imagenes nuevas (cero costo de IA).
- `build_layout_graph()` traduce una composicion a un filtergraph de FFmpeg.

Y `frame_fit_filter()`, que encaja cualquier medio en el cuadro sin barras negras.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import MutableMapping
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pipeline.cinematic_director import (
    _EVIDENCE_WORDS, _ascii_key, _beat_indices, _tokens, clip_motion_frames,
)

LAYOUT_VERSION = "segment_layouts_v1"

LAYOUT_LABELS = {
    "full": "Pantalla completa",
    "split": "Pantalla dividida",
    "pip": "Retrato flotante",
    "reveal": "Reveal (entra la 2a imagen)",
    "punch_in": "Punch-in (planos de 1 imagen)",
    "triptych": "Triptico",
    "blender_3d": "Toma 3D (Blender)",
}
# Proyectos guardados con el nombre anterior de la toma 3D (solo existia la mesa).
_LAYOUT_ALIASES = {"blender_desk": "blender_3d"}
FFMPEG_LAYOUTS = frozenset({"split", "pip", "reveal", "punch_in", "triptych"})
# Si Blender no esta o falla, la toma 3D cae a esto (tambien usa una sola imagen).
BLENDER_FALLBACK_LAYOUT = "punch_in"

BLENDER_ENVIRONMENTS = {
    "auto": "Automatico (segun la escena)",
    "desk": "Mesa con fotos",
    "corkboard": "Tablero de evidencias",
    "crt_tv": "TV de tubo",
    "newspaper": "Periodico que gira",
}
_MYSTERY_STEMS = (
    "myster", "disappear", "vanish", "secret", "conspira", "murder", "killer", "suspect",
    "investigat", "unsolved", "clue", "detective", "crime", "misterio", "desapare", "secreto",
    "asesin", "sospech", "investiga", "pista", "crimen",
)
_NEWS_STEMS = (
    "announc", "declared", "headline", "newspaper", "news", "treaty", "signed",
    "assassinated", "anunci", "declaro", "titular", "periodico", "noticia", "tratado", "firmo",
)


def normalize_layout(value: Any) -> str:
    key = str(value or "").strip()
    return _LAYOUT_ALIASES.get(key, key)


def choose_environment(text: Any, is_video: bool = False, preferred: Any = "auto") -> str:
    """Ambiente 3D para una escena: el elegido a mano, o por reglas sobre el texto.

    Escena de video -> TV de tubo (es el unico ambiente que la reproduce);
    misterio o crimen -> tablero de evidencias; anuncio o noticia -> periodico;
    el resto -> la mesa con fotos.
    """
    key = str(preferred or "auto").strip().lower()
    if key in BLENDER_ENVIRONMENTS and key != "auto":
        return key
    if is_video:
        return "crt_tv"
    tokens = _tokens(text)
    if any(tok.startswith(stem) for tok in tokens for stem in _MYSTERY_STEMS):
        return "corkboard"
    if any(tok.startswith(stem) for tok in tokens for stem in _NEWS_STEMS):
        return "newspaper"
    return "desk"

DYNAMISM_SPECS = {
    # budget = maximo de escenas elegibles con composicion; long_shot_s = desde
    # cuantos segundos un plano quieto se considera largo y se le mete ritmo.
    "off": {"label": "Apagado", "budget": 0.0, "long_shot_s": None},
    "moderate": {"label": "Moderado", "budget": 0.40, "long_shot_s": 4.5},
    "high": {"label": "Alto", "budget": 0.70, "long_shot_s": 3.0},
    "ai": {"label": "IA Director", "budget": 0.70, "long_shot_s": 3.0},
}
DEFAULT_DYNAMISM = "off"
_DYNAMISM_ALIASES = {
    "apagado": "off", "none": "off", "no": "off", "false": "off",
    "moderado": "moderate", "medio": "moderate", "medium": "moderate",
    "alto": "high", "maximo": "high", "max": "high",
    "ia": "ai", "director": "ai", "ia director": "ai",
}

MIN_LAYOUT_SECONDS = 1.6     # por debajo, una composicion no se llega a leer
MIN_TRIPTYCH_SECONDS = 2.5
MIN_BLENDER_SECONDS = 2.5
ACCENT_HEX = "#CDB58A"       # el dorado del texto de gancho (video_opening.HOOK_GOLD)
CANVAS_HEX = "#0B0B10"

_COMPARISON_WORDS = {
    "versus", "vs", "while", "whereas", "meanwhile", "however", "instead", "unlike",
    "compared", "contrast", "mientras", "embargo", "cambio", "comparado", "contraste",
}
_ENUMERATION_WORDS = {
    "three", "four", "five", "several", "first", "second", "third", "tres", "cuatro",
    "cinco", "varios", "varias", "primero", "segundo", "tercero",
}
_NAME_STOP = {
    "the", "a", "an", "in", "on", "at", "by", "of", "and", "but", "when", "then", "this",
    "that", "these", "those", "his", "her", "their", "its", "it", "he", "she", "they", "we",
    "after", "before", "during", "while", "as", "for", "from", "with", "today", "now",
    "el", "la", "los", "las", "un", "una", "en", "de", "del", "y", "pero", "cuando", "este",
    "esta", "su", "sus", "tras", "durante", "con", "por", "para", "hoy",
}
_NAME_BAD = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre", "war", "guerra",
}
_NAME_PARTICLES = {"da", "de", "del", "di", "van", "von", "der", "la", "le", "bin", "ibn"}
# Lugares: "New Jersey", "San Francisco", "North Carolina", "United States"...
_PLACE_FIRST_WORDS = {
    "new", "san", "santa", "los", "las", "saint", "st", "fort", "port", "mount", "lake", "north",
    "south", "east", "west", "upper", "lower", "united", "great", "nueva", "nuevo", "puerto",
    "monte", "rio", "cape", "cabo", "isla", "sierra", "costa",
}
# "in Orange, New Jersey", "at Pearl Harbor", "from Buenos Aires": lo que sigue es un lugar.
_PLACE_PREPOSITIONS = {"in", "at", "from", "near", "across", "en", "desde", "cerca"}
_CAP_WORD = r"[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü'’\-]+"
_NAME_RE = re.compile(
    rf"{_CAP_WORD}(?:\s+(?:(?:{'|'.join(sorted(_NAME_PARTICLES))})\s+)?{_CAP_WORD}){{1,3}}"
)

_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
_VIDEO_EXT = (".mp4", ".mov", ".avi", ".webm", ".mkv", ".gif")


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def normalize_dynamism(value: Any) -> str:
    key = _ascii_key(value).split(" ", 1)[0].strip("-_:()")
    if key in DYNAMISM_SPECS:
        return key
    return _DYNAMISM_ALIASES.get(key, DEFAULT_DYNAMISM)


def _after_place_preposition(before: str) -> bool:
    """¿El nombre sigue a 'in/at/from...' (directo o tras otros lugares: 'in Orange, New Jersey')?

    'In June 1914, Archduke...' no cuenta: entre el 'In' y el nombre hay una fecha.
    """
    tokens = re.findall(r"[\wáéíóúñüÁÉÍÓÚÑÜ'’.-]+", before)
    for token in reversed(tokens):
        if token[:1].isupper() and not token.isdigit():
            continue                       # otro lugar de la cadena ("Orange,")
        return token.lower() in _PLACE_PREPOSITIONS
    return False


def extract_name_tag(text: Any) -> str:
    """Primer nombre propio de 2-4 palabras del texto, en mayusculas ('' si no hay).

    'In June 1914, Archduke Franz Ferdinand visited...' -> 'ARCHDUKE FRANZ FERDINAND'.
    Descarta meses, dias, 'World War' y LUGARES: en un short real 'in Orange, New
    Jersey' salio como retrato flotante rotulado NEW JERSEY sobre la cara de un
    aviso. Un rotulo equivocado es peor que ninguno.
    """
    text = str(text or "")
    for match in _NAME_RE.finditer(text):
        words = match.group(0).split()
        while words and words[0].lower() in _NAME_STOP:
            words = words[1:]
        capitalized = [w for w in words if w.lower() not in _NAME_PARTICLES]
        if len(capitalized) < 2:
            continue
        if any(w.lower().strip("'’-") in _NAME_BAD for w in words):
            continue
        if words[0].lower() in _PLACE_FIRST_WORDS:
            continue
        if _after_place_preposition(text[:match.start()]):
            continue
        return " ".join(words).upper()
    return ""


def _is_video_segment(segment: MutableMapping[str, Any]) -> bool:
    return bool(str(segment.get("video_path") or "").strip())


def _segment_duration(segment: MutableMapping[str, Any]) -> float:
    try:
        start = float(segment.get("start", 0) or 0)
        end = float(segment.get("end", start) or start)
        if end - start > 0.05:
            return end - start
        return float(segment.get("duration", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def layout_candidates(text: Any, role: str, duration: float, index: int, level: str,
                      is_video: bool = False) -> List[Tuple[str, int, str]]:
    """Composiciones posibles para una escena, de la mas fuerte a la mas debil.

    Cada una es (layout, prioridad, motivo). Prioridad 3 = la pide el contenido,
    2 = el papel narrativo, 1 = solo romper un plano largo (no aplica a un video:
    ya se mueve solo).
    """
    spec = DYNAMISM_SPECS[level]
    tokens = _tokens(text)
    out: List[Tuple[str, int, str]] = []
    if duration >= MIN_TRIPTYCH_SECONDS and tokens & _ENUMERATION_WORDS:
        out.append(("triptych", 3, "enumeration"))
    if tokens & _COMPARISON_WORDS:
        out.append(("split", 3, "comparison"))
    # El retrato flotante (pip) se retiro (2026-10): el rostro en circulo
    # molestaba y no aportaba. Se conserva el render para proyectos viejos.
    if role == "climax":
        out.append(("punch_in", 2, "climax"))
    if role == "turn":
        out.append(("reveal", 2, "turn"))
    long_shot = spec["long_shot_s"]
    if long_shot is not None and duration >= long_shot and not is_video:
        generic = ["punch_in", "reveal"] if index % 2 else ["reveal", "punch_in"]
        out.extend((name, 1, "long_shot") for name in generic)
    return out


def plan_layouts(
    storyboard: MutableMapping[str, Any],
    *,
    level: Any = DEFAULT_DYNAMISM,
    blender_shots: int = 0,
    environment: Any = "auto",
    force: bool = False,
) -> Dict[str, Any]:
    """Asigna `layout_plan` a cada escena y devuelve un resumen.

    Reglas fijas: la primera escena (la entrada, con su gancho) y la ultima (el
    cierre) van a pantalla completa; tambien las muy cortas. Nunca dos escenas
    seguidas con la misma composicion. `blender_shots` > 0 reserva esa cantidad
    de tomas 3D para los momentos fuertes; `environment` fija su ambiente
    ('auto' = segun cada escena, ver `choose_environment`).
    """
    segments = storyboard.get("segments") or []
    selected = normalize_dynamism(level)
    spec = DYNAMISM_SPECS[selected]
    count = len(segments)
    beats = _beat_indices(count, "cinematic")
    plans: List[Optional[Dict[str, Any]]] = [None] * count
    priority = [0] * count
    eligible: List[int] = []

    for index, segment in enumerate(segments):
        if not isinstance(segment, MutableMapping):
            continue
        current = segment.get("layout_plan")
        if isinstance(current, MutableMapping) and current.get("locked") and not force:
            plans[index] = dict(current, layout=normalize_layout(current.get("layout")))
            continue
        plans[index] = {"version": LAYOUT_VERSION, "layout": "full", "reason": "default",
                        "tag": "", "locked": False}
        # La media extra elegida a mano sobrevive aunque la composicion sea automatica.
        if isinstance(current, MutableMapping) and current.get("extra_media"):
            plans[index]["extra_media"] = list(current["extra_media"])
        duration = _segment_duration(segment)
        if (selected == "off" or index in (0, count - 1) or segment.get("cover_frame")
                or duration < MIN_LAYOUT_SECONDS):
            continue
        eligible.append(index)
        role = str((segment.get("cinematic_plan") or {}).get("role") or beats.get(index, "bridge"))
        text = segment.get("narration_text") or segment.get("text") or ""
        prev_layout = (plans[index - 1] or {}).get("layout") if index else None
        for layout, prio, reason in layout_candidates(text, role, duration, index, selected,
                                                      is_video=_is_video_segment(segment)):
            if layout == prev_layout:
                continue
            plans[index].update(layout=layout, reason=reason,
                                tag=extract_name_tag(text) if reason == "person" else "")
            priority[index] = prio
            break

    # Presupuesto: sobran composiciones -> se quitan primero las que solo rompian
    # un plano largo, y entre iguales las del final (el arranque retiene mas).
    allowed = int(round(len(eligible) * spec["budget"]))
    chosen = [i for i in eligible if plans[i]["layout"] != "full" and not plans[i].get("locked")]
    for index in sorted(chosen, key=lambda i: (priority[i], -i))[:max(0, len(chosen) - allowed)]:
        plans[index].update(layout="full", reason="budget", tag="")

    # Tomas 3D: los momentos fuertes primero (climax, giro), despues lo mas largo.
    # Las fijadas a mano en el timeline cuentan dentro del cupo (si no, un short
    # terminaba con dos tomas: la elegida a mano y otra del planificador).
    blender_shots = int(blender_shots) - sum(
        1 for plan in plans if plan and plan.get("locked") and plan.get("layout") == "blender_3d")
    if blender_shots > 0 and selected != "off":
        ranked = sorted(
            (i for i in eligible if not plans[i].get("locked")
             and _segment_duration(segments[i]) >= MIN_BLENDER_SECONDS),
            key=lambda i: ({"climax": 0, "turn": 1}.get(beats.get(i, ""), 2),
                           -_segment_duration(segments[i])),
        )
        for index in ranked[:int(blender_shots)]:
            segment = segments[index]
            plans[index].update(
                layout="blender_3d", reason="hero_3d", tag="",
                environment=choose_environment(segment.get("narration_text") or segment.get("text"),
                                               _is_video_segment(segment), environment),
            )

    counts: Dict[str, int] = {}
    for index, segment in enumerate(segments):
        if plans[index] is None:
            continue
        segment["layout_plan"] = plans[index]
        name = plans[index]["layout"]
        counts[name] = counts.get(name, 0) + 1
    summary = {
        "version": LAYOUT_VERSION,
        "level": selected,
        "label": spec["label"],
        "segments": count,
        "counts": counts,
    }
    storyboard["layout_direction"] = summary
    return summary


def plan_summary_text(summary: MutableMapping[str, Any]) -> str:
    counts = dict(summary.get("counts") or {})
    full = counts.pop("full", 0)
    if not counts:
        return f"todas a pantalla completa ({full})"
    parts = ", ".join(f"{LAYOUT_LABELS.get(k, k).lower()} {v}" for k, v in sorted(counts.items()))
    return f"{sum(counts.values())} de {summary.get('segments', 0)} escenas con composicion ({parts})"


# ---------------------------------------------------------------------------
# Fuentes de los paneles
# ---------------------------------------------------------------------------

LAYOUT_EXTRA_SOURCES = {"split": 1, "reveal": 1, "pip": 1, "triptych": 2, "blender_3d": 6}
# Detalles de la misma imagen cuando no hay otra: (centro x, centro y, zoom).
DETAIL_CROPS = ((0.5, 0.36, 2.0), (0.32, 0.55, 2.2), (0.68, 0.45, 2.2))


def is_image_path(path: Any) -> bool:
    return str(path or "").lower().endswith(_IMAGE_EXT)


def is_video_path(path: Any) -> bool:
    return str(path or "").lower().endswith(_VIDEO_EXT)


def _neighbor_order(index: int, count: int, layout: str) -> List[int]:
    """Split mira hacia atras (contraste con lo que se acaba de ver); reveal hacia
    adelante (anticipa la escena siguiente, que despues entra a pantalla completa)."""
    first, second = (1, -1) if layout == "reveal" else (-1, 1)
    order = []
    for step in range(1, count):
        for sign in (first, second):
            j = index + sign * step
            if 0 <= j < count:
                order.append(j)
    return order


def resolve_layout_sources(clips: List[MutableMapping[str, Any]]) -> None:
    """Completa `layout_sources` en cada clip con composicion (in place).

    Orden: media extra asignada a mano (`layout_plan.extra_media`, ya resuelta a
    rutas existentes) -> imagenes o videos de escenas vecinas -> detalles de la
    misma escena. El retrato flotante usa directamente un detalle: muestra de
    cerca a quien o que se nombra en la escena. La toma 3D solo toma imagenes
    (salvo la TV, que reproduce el video de la propia escena).
    """
    media = [str(c.get("filename") or "") if (is_image_path(c.get("filename"))
                                              or is_video_path(c.get("filename"))) else ""
             for c in clips]
    images = [m if is_image_path(m) else "" for m in media]
    for index, clip in enumerate(clips):
        plan = clip.get("layout_plan") or {}
        layout = normalize_layout(plan.get("layout"))
        need = LAYOUT_EXTRA_SOURCES.get(layout, 0)
        main = media[index]
        if not need or not main:
            continue
        pool = images if layout == "blender_3d" else media
        sources: List[Dict[str, Any]] = []
        seen = {os.path.normcase(main)}
        for path in plan.get("extra_media") or []:
            if path and os.path.exists(str(path)) and os.path.normcase(str(path)) not in seen:
                sources.append({"path": str(path)})
                seen.add(os.path.normcase(str(path)))
        if layout != "pip":
            for j in _neighbor_order(index, len(clips), layout):
                if len(sources) >= need:
                    break
                other = pool[j]
                if other and os.path.normcase(other) not in seen:
                    sources.append({"path": other})
                    seen.add(os.path.normcase(other))
        for crop in DETAIL_CROPS:
            if len(sources) >= need or layout == "blender_3d":
                break
            sources.append({"path": main, "detail": crop})
        clip["layout_sources"] = sources[:need]


# ---------------------------------------------------------------------------
# Encaje en el cuadro
# ---------------------------------------------------------------------------

BLUR_FILL_TOLERANCE = 0.12


def aspect_mismatch(src_size: Sequence[int], out_size: Sequence[int]) -> float:
    """Diferencia relativa de aspecto (0 = iguales)."""
    sw, sh = max(1, int(src_size[0])), max(1, int(src_size[1]))
    ow, oh = max(1, int(out_size[0])), max(1, int(out_size[1]))
    src, out = sw / sh, ow / oh
    return abs(src - out) / out


def needs_blur_fill(src_size: Optional[Sequence[int]], out_size: Sequence[int]) -> bool:
    return bool(src_size) and aspect_mismatch(src_size, out_size) > BLUR_FILL_TOLERANCE


def frame_fit_filter(src_size: Optional[Sequence[int]], out_size: Sequence[int]) -> str:
    """Cadena de FFmpeg que lleva el medio al cuadro completo, sin barras negras.

    - Sin tamano (no se pudo medir): encaje con barras, como era antes.
    - Aspecto parecido (<=12%): recorte minimo (antes quedaban franjas finas).
    - Muy distinto (una foto horizontal en un short): fondo = la misma imagen
      desenfocada, frente = la imagen entera. El desenfoque se hace a 1/4 de
      resolucion: el mismo resultado, a una fraccion del costo por cuadro.
    """
    w, h = int(out_size[0]), int(out_size[1])
    if not src_size:
        # Sin medir el medio no se recorta a ciegas: se encaja como antes.
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    if not needs_blur_fill(src_size, out_size):
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    bw, bh = max(2, (w // 4) // 2 * 2), max(2, (h // 4) // 2 * 2)
    return (
        "split[ff_a][ff_b];"
        f"[ff_a]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
        f"gblur=sigma=9,eq=brightness=-0.10:saturation=0.85,scale={w}:{h},setsar=1[ff_bg];"
        f"[ff_b]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[ff_fg];"
        "[ff_bg][ff_fg]overlay=(W-w)/2:(H-h)/2"
    )


# ---------------------------------------------------------------------------
# Filtergraphs
# ---------------------------------------------------------------------------

def _hex_ffmpeg(hex_color: str) -> str:
    return "0x" + hex_color.lstrip("#").upper()


def _ease_out(t0: float, dur: float) -> str:
    """Ease-out cubico en funcion de t, para overlay x/y."""
    return f"(1-pow(1-clip((t-{t0:.3f})/{dur:.3f},0,1),3))"


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


def _kb_panel(inp: str, out: str, w: int, h: int, frames: int, fps: float,
              motion: Tuple[float, float, Tuple[float, float], Tuple[float, float]],
              detail: Optional[Sequence[float]] = None, supersample: int = 2,
              fit_src_size: Optional[Sequence[int]] = None) -> str:
    """Ken Burns de un still dentro de un panel w x h, a `fps`.

    Por defecto 'cover' (llena el panel recortando). Con `fit_src_size` muestra
    la imagen entera sobre su propio fondo desenfocado (`frame_fit_filter`).
    """
    z0, z1, c0, c1 = motion
    n = max(1, int(frames))
    p = "0" if n <= 1 else f"(on/{n - 1})"
    e = f"(({p})*({p})*(3-2*({p})))"
    cx = f"({c0[0]:.3f}+({c1[0] - c0[0]:.3f})*{e})"
    cy = f"({c0[1]:.3f}+({c1[1] - c0[1]:.3f})*{e})"
    pre = ""
    if detail:
        fx, fy, z = (float(v) for v in detail)
        pre = f"crop=iw/{z:.3f}:ih/{z:.3f}:(iw-iw/{z:.3f})*{fx:.3f}:(ih-ih/{z:.3f})*{fy:.3f},"
    ss = max(1, int(supersample))
    if fit_src_size:
        fill = frame_fit_filter(fit_src_size, (w * ss, h * ss))
    else:
        fill = f"scale={w * ss}:{h * ss}:force_original_aspect_ratio=increase,crop={w * ss}:{h * ss}"
    return (
        f"[{inp}]{pre}{fill},setsar=1,"
        f"zoompan=z='{z0:.4f}+({z1 - z0:.4f})*{e}'"
        f":x='clip({cx}*iw-iw/zoom/2,0,iw-iw/zoom)':y='clip({cy}*ih-ih/zoom/2,0,ih-ih/zoom)'"
        f":d={n}:s={w}x{h}:fps={float(fps):g}[{out}]"
    )


_PANEL_MOTIONS = (
    (1.00, 1.10, (0.50, 0.45), (0.50, 0.42)),   # push
    (1.10, 1.14, (0.40, 0.50), (0.60, 0.50)),   # deriva a la derecha
    (1.10, 1.14, (0.60, 0.50), (0.40, 0.50)),   # deriva a la izquierda
    (1.12, 1.00, (0.50, 0.40), (0.50, 0.45)),   # retirada
)


def _font(size: int):
    from PIL import ImageFont
    for path in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def render_inset_png(source: Dict[str, Any], out_path: str, diameter: int) -> int:
    """Recorte circular con aro y sombra suave (PIL, con antialias). Devuelve el lado del PNG."""
    from PIL import Image, ImageDraw, ImageFilter
    ring = max(4, diameter // 36)
    pad = max(16, diameter // 11)
    full = diameter + 2 * pad
    img = Image.open(source["path"]).convert("RGB")
    if source.get("box"):
        # Cuadrado centrado en la cara (pipeline.face_focus), normalizado.
        x0, y0, x1, y1 = (float(v) for v in source["box"])
        img = img.crop((int(x0 * img.width), int(y0 * img.height),
                        int(x1 * img.width), int(y1 * img.height)))
    elif source.get("detail"):
        fx, fy, z = (float(v) for v in source["detail"])
        cw, ch = img.width / z, img.height / z
        left, top = (img.width - cw) * fx, (img.height - ch) * fy
        img = img.crop((int(left), int(top), int(left + cw), int(top + ch)))
    side = min(img.size)
    top = int((img.height - side) * 0.25)   # sin cara detectada: mas arriba que el centro
    img = img.crop(((img.width - side) // 2, top, (img.width - side) // 2 + side, top + side))
    face = diameter - 2 * ring
    img = img.resize((face, face), Image.LANCZOS)

    canvas = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    shadow = Image.new("L", (full, full), 0)
    ImageDraw.Draw(shadow).ellipse((pad, pad + ring, pad + diameter, pad + diameter + ring), fill=150)
    canvas.paste(Image.new("RGBA", (full, full), (0, 0, 0, 255)), (0, 0),
                 shadow.filter(ImageFilter.GaussianBlur(max(4, pad // 3))))

    def disc(size: int, box: Tuple[int, int, int, int], canvas_size: int):
        mask = Image.new("L", (canvas_size * 4,) * 2, 0)
        ImageDraw.Draw(mask).ellipse(tuple(v * 4 for v in box), fill=255)
        return mask.resize((canvas_size,) * 2, Image.LANCZOS)

    canvas.paste(Image.new("RGBA", (full, full), (245, 240, 228, 255)), (0, 0),
                 disc(full, (pad, pad, pad + diameter, pad + diameter), full))
    canvas.paste(img, (pad + ring, pad + ring), disc(face, (0, 0, face, face), face))
    canvas.save(out_path)
    return full


def render_tag_png(text: str, out_path: str, font_px: int, accent_hex: str = ACCENT_HEX) -> Tuple[int, int]:
    """Rotulo: texto oscuro sobre una placa del color de acento. Devuelve (ancho, alto)."""
    from PIL import Image, ImageDraw
    font = _font(font_px)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    pad_x, pad_y = int(font_px * 0.45), int(font_px * 0.28)
    w, h = (right - left) + 2 * pad_x, (bottom - top) + 2 * pad_y
    accent = tuple(int(accent_hex.lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=max(4, font_px // 6), fill=accent + (245,))
    draw.text((pad_x - left, pad_y - top), text, font=font, fill=(20, 17, 13, 255))
    img.save(out_path)
    return w, h


def _video_panel(inp: str, out: str, w: int, h: int, fps: float, *, stretch: float = 1.0,
                 interpolate: bool = False, zoom: float = 1.0,
                 focus: Sequence[float] = (0.5, 0.5)) -> str:
    """Un video dentro de un panel w x h: recorte 'cover', sin Ken Burns (ya se mueve).

    `stretch` > 1 ralentiza el tramo con movimiento para que cubra la escena
    (ver `video_motion.input_window`), con interpolacion si FFmpeg la trae.
    """
    rate = f"{float(fps):g}"
    pre = ""
    if stretch > 1.001:
        pre = f"setpts={stretch:.6f}*PTS,"
        if interpolate:
            pre += f"minterpolate=fps={rate}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
    zw, zh = _even(w * zoom), _even(h * zoom)
    fx, fy = float(focus[0]), float(focus[1])
    return (f"[{inp}]{pre}fps={rate},scale={zw}:{zh}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:(iw-{w})*{fx:.3f}:(ih-{h})*{fy:.3f},setsar=1[{out}]")


def frame_grab(video: str, out_png: str, at: float = 1.0) -> str:
    """Un cuadro del video como imagen (para el recorte circular del retrato)."""
    import subprocess
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{max(0.0, at):.2f}", "-i", video,
                    "-frames:v", "1", out_png], capture_output=True, timeout=60,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if not os.path.exists(out_png):
        raise RuntimeError(f"no se pudo extraer un cuadro de {os.path.basename(video)}")
    return out_png


class NoFaceFound(ValueError):
    """El retrato de una persona no tiene una cara clara para centrar el circulo."""


def input_args(spec: Dict[str, Any]) -> List[str]:
    """Los `-i` (con su ventana de tiempo, si es video) de una composicion, en orden."""
    args: List[str] = []
    for item in spec["inputs"]:
        args += list(item)
    return args


def build_layout_graph(
    layout: str,
    *,
    main: str,
    sources: Sequence[Dict[str, Any]],
    duration: float,
    size: Sequence[int],
    fps: float,
    temp_dir: str,
    index: int = 0,
    tag: str = "",
    accent_hex: str = ACCENT_HEX,
    main_size: Optional[Sequence[int]] = None,
    video_windows: Optional[Dict[str, Tuple[float, float, float]]] = None,
    interpolate: bool = False,
    require_face: bool = False,
) -> Dict[str, Any]:
    """Filtergraph de FFmpeg para una composicion. La escena y los paneles pueden
    ser imagenes o videos.

    - `main_size` (ancho, alto del medio principal) permite al punch-in mostrarlo
      entero y no acercar mas de lo que su resolucion aguanta.
    - `video_windows[ruta] = (desde, largo, estirar)`: el tramo con movimiento de
      cada video (`video_motion.input_window`). Sin dato se usa desde 0.
    - `interpolate`: ralentizar con `minterpolate` (si FFmpeg lo trae).
    - `require_face`: el retrato flotante es de una persona: el circulo se centra
      en su cara, y si no hay una cara clara lanza `NoFaceFound`.

    Devuelve {'inputs': [[args de -i]], 'graph': str} con la salida etiquetada
    `[lay]`, de `size` y a `fps`. El que llama recorta con `-t duration` y agrega
    look, fundido o Film Burn detras de `[lay]` (ver `input_args`).
    """
    if layout not in FFMPEG_LAYOUTS:
        raise ValueError(f"composicion sin filtergraph: {layout}")
    w, h = int(size[0]), int(size[1])
    vertical = h >= w
    duration = float(duration)
    frames = clip_motion_frames(duration, fps)
    rate = f"{float(fps):g}"
    accent = _hex_ffmpeg(accent_hex)
    canvas = f"color=c={_hex_ffmpeg(CANVAS_HEX)}:s={w}x{h}:r={rate}:d={duration + 1:.3f}[base]"
    srcs = list(sources) or [{"path": main, "detail": DETAIL_CROPS[0]}]
    windows = dict(video_windows or {})
    inputs: List[List[str]] = []
    stretch_of: Dict[str, float] = {}
    parts: List[str] = []

    def add_input(path: str) -> str:
        if is_video_path(path):
            start, length, stretch = windows.get(path, (0.0, duration + 0.5, 1.0))
            inputs.append(["-ss", f"{start:.3f}", "-t", f"{length + 0.1:.3f}", "-i", path])
        else:
            stretch = 1.0
            inputs.append(["-i", path])
        label = f"{len(inputs) - 1}:v"
        stretch_of[label] = stretch
        return label

    def panel(src: Dict[str, Any], inp: str, out: str, pw: int, ph: int,
              motion: Tuple[float, float, Tuple[float, float], Tuple[float, float]]) -> str:
        if is_video_path(src["path"]):
            detail = src.get("detail")
            zoom, focus = (float(detail[2]), detail[:2]) if detail else (1.0, (0.5, 0.5))
            return _video_panel(inp, out, pw, ph, fps, stretch=stretch_of.get(inp, 1.0),
                                interpolate=interpolate, zoom=zoom, focus=focus)
        return _kb_panel(inp, out, pw, ph, frames, fps, motion, src.get("detail"))

    main_in = add_input(main)
    main_src = {"path": main}

    if layout == "punch_in":
        total = int(round(duration * float(fps)))
        # Primer plano: la escena ENTERA (con fondo desenfocado si no llena el
        # cuadro). Los cortes acercan, pero sin ampliar la fuente mas de ~2.4x:
        # en una foto de archivo de 700 px un zoom fijo de 1.7 queda borroso.
        cover = 1.0
        if main_size:
            cover = max(w / max(1, int(main_size[0])), h / max(1, int(main_size[1])))
        cap = max(1.0, 2.4 / cover)
        medium, close = min(1.30, cap), min(1.62, cap)
        # Sin margen de zoom el plano medio y el cerrado saldrian iguales.
        shots = 2 if duration < 3.2 or cap < 1.15 else 3
        ladder = ([(1.00, 1.05, (0.50, 0.45), True), (close, close * 1.04, (0.50, 0.40), False)]
                  if shots == 2 else
                  [(1.00, 1.05, (0.50, 0.45), True), (medium, medium * 1.04, (0.38, 0.45), False),
                   (close, close * 1.04, (0.62, 0.38), False)])
        margin = _even(min(w, h) * 0.022)
        cw, ch = w + 2 * margin, h + 2 * margin
        cuts = [int(round(total * k / shots)) for k in range(shots + 1)]
        labels = []
        if is_video_path(main):
            # El video sigue corriendo; la "camara" corta de plano: cada plano es
            # su tramo del MISMO video (trim por cuadros, la suma es exacta).
            pre = _video_panel(main_in, "pv", cw, ch, fps, stretch=stretch_of[main_in],
                               interpolate=interpolate).rsplit("scale=", 1)[0]
            parts.append(pre + f"split={shots}" + "".join(f"[pi{k}]" for k in range(shots)))
        else:
            parts.append(f"[{main_in}]split={shots}" + "".join(f"[pi{k}]" for k in range(shots)))
        for k, (z0, z1, c, whole) in enumerate(ladder):
            n = max(1, cuts[k + 1] - cuts[k])
            if is_video_path(main):
                fill = (frame_fit_filter(main_size, (cw, ch)) if whole else
                        f"scale={_even(cw * z0)}:{_even(ch * z0)}:force_original_aspect_ratio=increase,"
                        f"crop={cw}:{ch}:(iw-{cw})*{c[0]:.3f}:(ih-{ch})*{c[1]:.3f}")
                chain = (f"[pi{k}]trim=start_frame={cuts[k]}:end_frame={cuts[k] + n},"
                         f"setpts=PTS-STARTPTS,{fill}")
            else:
                # Cada plano dura EXACTO su parte (sin cuadro extra): el concat suma.
                chain = _kb_panel(f"pi{k}", f"pk{k}", cw, ch, n, fps,
                                  (z0, z1, c, c), fit_src_size=main_size if whole else None
                                  ).rsplit("[", 1)[0]
            if k:
                chain += (f",crop={w}:{h}:x='{margin}+{margin * 0.8:.1f}*sin(t*55)*exp(-t*7)'"
                          f":y='{margin}+{margin * 0.65:.1f}*cos(t*47)*exp(-t*7)'"
                          f",fade=t=in:st=0:d=0.12:color=white")
            else:
                chain += f",crop={w}:{h}:{margin}:{margin}"
            parts.append(chain + f",setsar=1[pk{k}]")
            labels.append(f"[pk{k}]")
        parts.append("".join(labels) + f"concat=n={shots}:v=1:a=0[lay]")
        return {"inputs": inputs, "graph": ";".join(parts)}

    if layout in ("split", "reveal"):
        div = _even(min(w, h) * 0.015)
        pw, ph = (w, _even((h - div) / 2)) if vertical else (_even((w - div) / 2), h)
        second = srcs[0]
        parts.append(canvas)
        divider = (f"color=c={accent}:s={w if vertical else div}x{div if vertical else h}"
                   f":r={rate}:d={duration + 1:.3f}[div]")
        if layout == "split":
            parts.append(panel(main_src, main_in, "pa", pw, ph, _PANEL_MOTIONS[0]))
            parts.append(panel(second, add_input(second["path"]), "pb", pw, ph,
                               _PANEL_MOTIONS[1 + index % 2]))
            parts.append(divider)
            if vertical:
                parts += [
                    f"[base][pa]overlay=x='-{w}*(1-{_ease_out(0, 0.45)})':y=0[b1]",
                    f"[b1][pb]overlay=x='{w}*(1-{_ease_out(0.12, 0.45)})':y={ph + div}[b2]",
                    f"[b2][div]overlay=x='-{w}*(1-{_ease_out(0.3, 0.3)})':y={ph}[lay]",
                ]
            else:
                parts += [
                    f"[base][pa]overlay=x=0:y='-{h}*(1-{_ease_out(0, 0.45)})'[b1]",
                    f"[b1][pb]overlay=x={pw + div}:y='{h}*(1-{_ease_out(0.12, 0.45)})'[b2]",
                    f"[b2][div]overlay=x={pw}:y='-{h}*(1-{_ease_out(0.3, 0.3)})'[lay]",
                ]
        else:
            t0, d = max(0.8, duration * 0.42), 0.5
            e = _ease_out(t0, d)
            parts.append(panel(main_src, main_in, "pa", w, h, _PANEL_MOTIONS[0]))
            parts.append(panel(second, add_input(second["path"]), "pb", pw, ph,
                               _PANEL_MOTIONS[1 + index % 2]))
            parts.append(divider)
            if vertical:
                parts += [
                    f"[base][pa]overlay=x=0:y='-{h // 4}*{e}'[b1]",
                    f"[b1][div]overlay=x=0:y='{h}-{h - ph}*{e}'[b2]",
                    f"[b2][pb]overlay=x=0:y='{h}-{h - ph - div}*{e}'[lay]",
                ]
            else:
                parts += [
                    f"[base][pa]overlay=x='-{w // 4}*{e}':y=0[b1]",
                    f"[b1][div]overlay=x='{w}-{w - pw}*{e}':y=0[b2]",
                    f"[b2][pb]overlay=x='{w}-{w - pw - div}*{e}':y=0[lay]",
                ]
        return {"inputs": inputs, "graph": ";".join(parts)}

    if layout == "triptych":
        gap = _even(min(w, h) * 0.022)
        if vertical:
            sw, sh = w, _even((h - 4 * gap) / 3)
        else:
            sw, sh = _even((w - 4 * gap) / 3), h
        panels = [main_src] + srcs[:2]
        while len(panels) < 3:
            panels.append({"path": main, "detail": DETAIL_CROPS[len(panels)]})
        parts.append(canvas)
        prev = "base"
        for k, src in enumerate(panels):
            inp = main_in if k == 0 else add_input(src["path"])
            parts.append(panel(src, inp, f"t{k}", sw, sh, _PANEL_MOTIONS[k % len(_PANEL_MOTIONS)]))
            e = _ease_out(0.18 * k, 0.45)
            out = "lay" if k == 2 else f"tb{k}"
            sign = "-" if k % 2 == 0 else ""
            if vertical:
                parts.append(f"[{prev}][t{k}]overlay=x='{sign}{w}*(1-{e})':y={gap + k * (sh + gap)}[{out}]")
            else:
                parts.append(f"[{prev}][t{k}]overlay=x={gap + k * (sw + gap)}:y='{sign}{h}*(1-{e})'[{out}]")
            prev = out
        return {"inputs": inputs, "graph": ";".join(parts)}

    # pip: escena de fondo + recorte circular que entra + rotulo opcional.
    diameter = _even(min(w, h) * (0.40 if vertical else 0.34))
    inset_src = dict(srcs[0])
    if is_video_path(inset_src["path"]):
        start = windows.get(inset_src["path"], (0.0, 0.0, 1.0))[0]
        inset_src["path"] = frame_grab(inset_src["path"], os.path.join(temp_dir, f"grab_{index:03d}.png"),
                                        start + 0.5)
    if require_face:
        # El retrato de una persona va centrado en SU cara. Recortar a ciegas
        # mostro el hombro de un oficial (la cara estaba a la izquierda).
        from pipeline.face_focus import portrait_box
        box = portrait_box(inset_src["path"])
        if box is None:
            raise NoFaceFound(f"sin una cara clara en {os.path.basename(inset_src['path'])}")
        inset_src["box"] = box
    inset_path = os.path.join(temp_dir, f"inset_{index:03d}.png")
    side = render_inset_png(inset_src, inset_path, diameter)
    margin = _even(min(w, h) * 0.035)
    ix = w - side - margin
    iy = _even(h * 0.13) if vertical else margin
    parts.append(panel(main_src, main_in, "bg", w, h, _PANEL_MOTIONS[1 + index % 2]))
    inset_in = add_input(inset_path)
    parts.append(f"[{inset_in}]format=rgba,loop=loop={frames}:size=1,setpts=N/{rate}/TB,"
                 f"fade=t=in:st=0.35:d=0.3:alpha=1[ins]")
    parts.append(f"[bg][ins]overlay=x='{ix}+(1-{_ease_out(0.35, 0.5)})*{side + margin}':y={iy}[p1]")
    if tag:
        tag_path = os.path.join(temp_dir, f"tag_{index:03d}.png")
        tw, th = render_tag_png(tag, tag_path, _even(min(w, h) * 0.042), accent_hex)
        tx = max(margin, w - margin - tw)
        tag_in = add_input(tag_path)
        parts.append(f"[{tag_in}]format=rgba,loop=loop={frames}:size=1,setpts=N/{rate}/TB,"
                     f"fade=t=in:st=0.75:d=0.3:alpha=1[tg]")
        parts.append(f"[p1][tg]overlay=x='{tx}+(1-{_ease_out(0.75, 0.4)})*{margin * 2}':"
                     f"y={iy + side - margin // 2}[lay]")
    else:
        parts[-1] = parts[-1].rsplit("[", 1)[0] + "[lay]"
    return {"inputs": inputs, "graph": ";".join(parts)}
