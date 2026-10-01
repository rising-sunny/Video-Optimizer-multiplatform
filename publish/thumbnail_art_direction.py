"""Direccion contextual de miniaturas externas: el LLM decide; Python valida y compone.

La escena nunca contiene instrucciones tipograficas. Un unico bloque de texto se
construye con las decisiones del modelo y los limites geometricos del formato.
El plan de titulos superpuestos en video no cambia.
"""
from __future__ import annotations

import json
import re
import unicodedata

from publish.thumbnail_typography import contrast_ratio, plan_typography


# Anchos aproximados para ajustar renglones, no medidas de una fuente instalada.
LETTERFORMS = {
    "wedge_serif": ("sculpted capitals with short wedge serifs, gently flared stems and open counters", 0.68),
    "humanist_serif": ("humanist serif capitals with softly bracketed serifs, moderate stroke contrast and open counters", 0.70),
    "editorial_sans": ("editorial sans-serif capitals with subtly tapered terminals, balanced proportions and open counters", 0.64),
    "geometric_sans": ("geometric sans-serif capitals with precise circular counters and clean, squared terminals", 0.68),
}
FINISHES = {
    "matte_ink": "matte ink finish with an almost imperceptible fine grain inside the letters",
    "clean_print": "smooth matte print finish with clean, sharply defined silhouettes",
    "letterpress": "subtle letterpress ink texture within solid letter silhouettes, no physical embossing",
}


def contextual_composition_rules(fmt, render_text=True):
    """Las reglas heredadas de color/lente no deben anular el contexto elegido."""
    rules = []
    for rule in fmt.composition_rules:
        if rule.startswith(("warm dominant palette", "average red channel", "overall mean luminance")):
            continue
        if rule.startswith("cinematic three-point lighting"):
            rule = "cinematic lighting motivated by the actual setting and materials; no automatic firelight, sunset or teal backdrop"
        elif rule.startswith("shallow depth of field"):
            rule = "depth of field must keep all elements needed to explain the headline clearly visible"
        elif rule.startswith("photoreal cinematic style"):
            rule = "photoreal cinematic style, lens appropriate to the chosen shot, subtle film grain, not plastic or digital painting"
        rule = rule.replace("warm key light", "context-appropriate key light")
        rules.append(rule)
    if render_text and fmt.is_vertical:
        from publish.thumbnail_typography import adapt_composition_rules
        rules = adapt_composition_rules(rules, plan_typography("X", fmt, zone=(0.13, 0.34)))
    return rules


def art_direction_brief(fmt) -> str:
    zone = "y 13%-34%, with every glyph below y 13%" if fmt.is_vertical else "the RIGHT third, y 20%-80%"
    return f"""CONTEXTUAL ART DIRECTION (decide before writing the scene):
Choose the headline AND the visible scene together. Research text_options are candidates, not commands.
Prioritize relevance to the central mechanism/event, a useful detail beyond the title, and a clear visual
connection. A number appearing somewhere in the script is not enough. If the hook describes two columns
of ships, show the two formations visibly; a lone cannon cannot communicate that hook. This is an example,
not a scene to reuse. For an abstract property or quantity, show its cause, consequence or a clear scale cue.
Copy a short supporting quote from the supplied script into evidence_quote (empty only when no script).
In visual_anchor briefly explain which visible feature of your scene makes the headline understandable.
This is a design explanation, not a second scene or a quote: paraphrases and short noun phrases are valid.
Before returning, check that this feature is actually shown in POSITIVE PROMPT. If it is missing, revise
the scene or choose another headline; do not claim a connection that only exists in this explanation.

Choose ONE font_family based on era, subject, mood and scene materials, not a universal preset:
wedge_serif (monumental or carved forms), humanist_serif (human, archival or organic character),
editorial_sans (mechanisms and tension), geometric_sans (precision and ordered structures).
These are options for YOUR decision, NEVER alternatives to forward to the image generator.
Choose finish: matte_ink, clean_print or letterpress. Substantial semibold strokes, no heavy block lettering.
Choose base_color, accent_color and background_color as explicit #RRGGBB colors related to the scene's
light/materials; ivory, chalk, muted warm or cool tints are possibilities, NOT fixed defaults.
Both text colors must have contrast >= 4.5:1 against background_color; use a calm background.
No obligatory yellow number or white caption. accent_color may equal base_color for a unified title.
Choose number_layout=inline or hero according to meaning and composition, not merely because a number exists.
Choose tracking=optical or slightly_open; no cramped letters, no excessive tracking.
Keep the entire text in {zone}; the application will calculate line sizes and exact positions.
Give reason as one short Spanish sentence explaining how the letters, colors and scene support the hook.

The [POSITIVE PROMPT] contains ONLY the fully resolved SCENE: subject, action, framing, scene palette,
lighting, materials, period details. NO headline, letters, text styling, font choices or text layout there.
Do not include the headline in straight or curly quotes there. The application adds TEXT RENDERING once.
Never put the headline, its number or any other writing ON an object of the scene (no sign, plank, plaque,
banner, tablet, carving or inscription bearing text): the title is the only text in the image.
The application adds the lettering only when text rendering is enabled.
Return [ART DIRECTION] as a JSON object with exactly these fields:
font_family, finish, base_color, accent_color, background_color, number_layout, tracking,
evidence_quote, visual_anchor, reason. No markdown fences, no unresolved choices.
"""


def _fold(value):
    # Espacios y guiones tipograficos no cambian la evidencia ni el ancla visible.
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", str(value)).casefold()))


def readable_color(color, background):
    """Cambio minimo hacia luz/sombra; conserva la familia cromatica del modelo."""
    if contrast_ratio(color, background) >= 4.5:
        return color
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    for step in range(1, 101):
        amount = step / 100
        for end in (255, 0):
            candidate = "#" + "".join(f"{round(c + (end - c) * amount):02X}" for c in rgb)
            if contrast_ratio(candidate, background) >= 4.5:
                return candidate
    raise ValueError("no se pudo resolver el contraste")


def validate_direction(direction, scene, script):
    """Valida estructura y evidencia, no intenta inferir semantica por coincidencia textual."""
    if not isinstance(direction, dict):
        raise ValueError("ART DIRECTION debe ser un objeto JSON")
    for field, choices in (("font_family", LETTERFORMS), ("finish", FINISHES),
                           ("number_layout", ("inline", "hero")), ("tracking", ("optical", "slightly_open"))):
        if direction.get(field) not in choices:
            raise ValueError(f"decision invalida: {field}")
    for field in ("base_color", "accent_color", "background_color"):
        if not isinstance(direction.get(field), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", direction[field]):
            raise ValueError(f"color invalido: {field}")
    evidence = direction.get("evidence_quote")
    if not isinstance(evidence, str) or (script and (not evidence.strip() or _fold(evidence) not in _fold(script))):
        raise ValueError("evidence_quote debe citar literalmente el guion suministrado")
    anchor = direction.get("visual_anchor")
    # El modelo puede describir "two formations" como "dos columnas navales".
    # Ni el substring ni contar palabras comprueban la coherencia visual.
    # Esta explicacion es metadato; nunca se anexa a la escena para forzar una coincidencia.
    if not isinstance(anchor, str) or not anchor.strip():
        raise ValueError("visual_anchor debe explicar el elemento visible que apoya el titular")
    if not isinstance(direction.get("reason"), str) or not direction["reason"].strip():
        raise ValueError("falta el motivo de la direccion artistica")


_TYPOGRAPHY_RE = re.compile(r'\b(typeface|typography|lettering|font|serif|kerning|cap height|text block)\b', re.I)

# Texto DENTRO de la escena: el generador lo dibuja y compite con el titular. Caso real
# (Agincourt, 2026-09-24): "a wooden plank bearing the bold number 9,000 carved in medieval
# block letters" -> la miniatura salio con el 9,000 dos veces, titulo y tabla tallada.
# "a letter sealed with wax" (el objeto, en singular) no entra.
_SCENE_TEXT_RE = re.compile(
    r'\b(letters|inscri\w+|numerals?|digits?|text|writing|written|words|calligraph\w*|'
    r'sign(?:board)?s? reading|reads|reading ["“])', re.I)


def _hook_numbers(hook):
    """Cifras del titular normalizadas ('9,000' -> '9000')."""
    return {re.sub(r"[,.\s]", "", n) for n in re.findall(r"\d[\d,.\s]*\d|\d", hook or "")}


def strip_scene_typography(scene, hook=""):
    """Quita de la escena la tipografia y todo texto que el generador dibujaria.

    La escena nunca lleva tipografia ni texto: la app agrega el titulo una sola vez
    (compile_title). Antes una sola palabra ("serif", "lettering") descartaba la
    respuesta entera, y dos intentos asi dejaban al usuario sin super prompt
    (2026-09-24). Se quita el fragmento (separado por coma) que:
      - habla de tipografia, o describe texto visible (letters, inscription, sign reading...);
      - repite el titular entre comillas.
    Si el fragmento solo menciona la cifra del titular ("a line of 9,000 archers"),
    se saca la cifra y se conserva el resto. Devuelve (escena_limpia, quitados).
    """
    parts = [p.strip() for p in re.split(r",\s*(?!\d{3}\b)", scene or "") if p.strip()]
    title = _fold(hook.strip('"“”')) if hook else ""
    numbers = _hook_numbers(hook)
    kept, removed = [], []
    for part in parts:
        quoted = re.findall(r'["“”]([^"“”]+)["“”]', part)
        if (_TYPOGRAPHY_RE.search(part) or _SCENE_TEXT_RE.search(part)
                or (title and any(_fold(q) == title for q in quoted))):
            removed.append(part)
            continue
        if numbers:
            def _drop(m):
                return "" if re.sub(r"[,.\s]", "", m.group(0)) in numbers else m.group(0)
            stripped = re.sub(r"\b(?:the\s+)?(?:number\s+)?\d[\d,.]*\d\b|\b\d\b", _drop, part)
            stripped = re.sub(r"\s{2,}", " ", stripped).strip()
            if stripped != part:
                removed.append(f"cifra del titular en: {part}")
                if len(stripped.split()) >= 2:
                    kept.append(stripped)
                continue
        kept.append(part)
    return ", ".join(kept), removed


def parse_art_response(result, script=""):
    match = re.fullmatch(
        r'\s*\[TEXT\]\s*(.*?)\[ART DIRECTION\]\s*(.*?)'
        r'\[POSITIVE PROMPT\]\s*(.*?)\[NEGATIVE PROMPT\]\s*(.*?)\s*',
        result or "", re.DOTALL,
    )
    if not match:
        raise ValueError("respuesta incompleta: se requieren los cuatro bloques")
    hook, raw, scene, negative = (part.strip() for part in match.groups())
    if not hook or not scene or not negative or any(
            s.endswith(("-", "\u2011", "\u2013", "\u2014")) for s in (scene, negative)):
        raise ValueError("respuesta vacia o cortada")
    direction = json.loads(raw)
    validate_direction(direction, scene, script)
    for field in ("base_color", "accent_color"):
        direction[field] = readable_color(direction[field], direction["background_color"])
    # No anexar otro estilo a una escena que ya trae uno (incluye comillas curvas):
    # se quitan los fragmentos con tipografia o con el titular; si casi no queda escena, se rechaza.
    clean, removed = strip_scene_typography(scene, hook)
    if removed:
        total = len([p for p in re.split(r",\s*(?!\d{3}\b)", scene) if p.strip()])
        whole = [r for r in removed if not r.startswith("cifra del titular")]
        if len(clean) < 120 or len(whole) > max(2, total * 0.4):
            words = sorted({m.lower() for p in removed
                            for m in _TYPOGRAPHY_RE.findall(p) + _SCENE_TEXT_RE.findall(p)})
            reason = ("el positivo debe contener solo la escena, sin tipografia" if words
                      else "el titular debe ir solo en TEXT, no repetido en la escena")
            raise ValueError(
                f"{reason} (remove {', '.join(words) or 'the quoted headline'} from POSITIVE PROMPT: "
                f"'{removed[0][:120]}'; the application adds the title itself)")
        scene = clean
        direction["scene_cleanup"] = removed
    if re.search(r'\b(choose|decide|select)\b', scene, re.I):
        raise ValueError("resolver todas las decisiones: no enviar choose/decide/select al generador de imagen")
    return hook, direction, scene, negative


def compile_title(hook, fmt, direction):
    """Un solo estilo resuelto, con color y geometria verificables."""
    font, glyph_width = LETTERFORMS[direction["font_family"]]
    if direction["tracking"] == "slightly_open":
        glyph_width += 0.04
    zone = (0.13, 0.34) if fmt.is_vertical else (0.20, 0.80)
    # Preservar la frase como unidad si el numero no es el protagonista.
    plan = plan_typography(hook, fmt, zone=zone, glyph_width=glyph_width,
                           number_hero=direction["number_layout"] == "hero")
    lines = plan["lines"]
    from publish.thumbnail_typography import MIN_CAP_PCT
    if any(ln["cap_pct"] < MIN_CAP_PCT[plan["kind"]] for ln in lines):
        raise ValueError("titular demasiado largo para letras legibles: elegir una frase mas corta")
    # La altura de las letras, no la del bloque, define el borde superior seguro.
    gap = 1.0 if fmt.is_vertical else 1.5
    total = sum(ln["cap_pct"] for ln in lines) + gap * max(0, len(lines) - 1)
    y = zone[0] * 100 + ((zone[1] - zone[0]) * 100 - total) / 2
    specs = []
    for i, ln in enumerate(lines):
        color = direction["accent_color"] if ln["role"] == "hero" else direction["base_color"]
        pixels = f" ({round(y / 100 * fmt.height)} px)" if fmt.is_vertical else ""
        specs.append(f'line {i + 1} "{ln["text"]}" in {color}, cap height {ln["cap_pct"]:.1f}% '
                     f'of frame height, actual glyph top y {y:.1f}%{pixels}')
        y += ln["cap_pct"] + gap
    placement = ("horizontally centered, every glyph entirely within y 13%-34%; nothing above 13%; no text below 71%"
                 if fmt.is_vertical else "in the RIGHT third, every glyph entirely within y 20%-80%")
    tracking = "optical kerning" if direction["tracking"] == "optical" else "slightly open optical spacing"
    directives = (
        f'render exactly these words and nothing else: "{hook}"; ENGLISH, plain ASCII, ALL CAPS, no accents',
        f'ONE coherent title: {font}; substantial semibold strokes, moderate width, {tracking}, letters never touching',
        f'{FINISHES[direction["finish"]]}; no thick outline, no hard offset drop shadow, no bevel, no extruded 3D, no glow, no WordArt',
        "; ".join(specs),
        f'{placement}; keep the background behind the title calm at {direction["background_color"]}; '
        'use this background value rather than a visible border to separate the letters',
        'straight front-facing title plane, all letters visible, no cropping or overlap with the subject; '
        'no other words, captions, subtitles, watermarks or invented glyphs; the headline appears ONLY ONCE, '
        'as this title: no numbers or words carved, painted, written or printed on any object in the scene '
        '(no signs, plaques, banners, tablets or inscriptions)',
    )
    return ", ".join(directives)
