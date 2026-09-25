"""Generate a cinematic cover frame for the first 0.7s of a YouTube Short.

The cover frame is a 9:16 vertical image with 1-3 words of text overlay,
designed to serve as a selectable thumbnail when uploading from mobile.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

_PROJECT_DIR = Path(__file__).resolve().parent

COVER_SIZE = (1080, 1920)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/bahnschrift.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/ARIALNB.TTF",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _get_cover_frame_config() -> dict[str, Any]:
    try:
        from channel_strategy import get_cover_frame_config
        return get_cover_frame_config()
    except ImportError:
        return {
            "enabled": True,
            "duration_seconds": 0.7,
            "word_count_min": 1,
            "word_count_max": 3,
            "word_examples": ["VANISHED", "ERASED", "TRAPPED", "THE BLAST", "LOST CITY"],
            "style": "cinematic high-contrast, centered subject, dark atmospheric background, vertical 9:16",
        }


def build_cover_image_prompt(topic: str, category: str, cover_text: str,
                             storyboard: Optional[dict] = None) -> str:
    config = _get_cover_frame_config()
    style_desc = config.get("style", "cinematic dark atmospheric")

    script_hint = ""
    if storyboard and storyboard.get("script"):
        script_hint = storyboard["script"][:300]

    return (
        f"Cinematic vertical 9:16 cover image for a dark historical documentary about: {topic}. "
        f"The word '{cover_text}' will be overlaid as text (DO NOT render any text in the image). "
        f"Single powerful central subject, dramatic backlighting, deep shadows, atmospheric haze, "
        f"high contrast, dark moody color palette, {style_desc}, "
        f"mobile-safe composition with subject centered in middle third, "
        f"leave generous negative space in the center-vertical area for text overlay, "
        f"no text, no logos, no watermarks, no UI, no modern objects, no anachronisms, "
        f"believable historical textures, archival documentary realism."
    )


def select_cover_text(topic: str, category: str, storyboard: Optional[dict] = None,
                      llm_suggestion: Optional[str] = None) -> str:
    if llm_suggestion:
        words = llm_suggestion.strip().split()
        if 1 <= len(words) <= 3:
            return llm_suggestion.strip().upper()

    config = _get_cover_frame_config()
    examples = config.get("word_examples", ["VANISHED", "ERASED", "THE BLAST"])

    # Con angulo elegido, sus cover_words mandan: 'HOW?' para un mecanismo,
    # 'FOUND' para un hallazgo. Antes salia 'THE CURSE' o 'NO SURVIVORS' por
    # una palabra suelta del tema, que es justo el encuadre que murio.
    try:
        from channel_strategy import archetype_cover_words, get_active_archetype
        arche = (storyboard or {}).get("format_archetype") if isinstance(storyboard, dict) else None
        words = archetype_cover_words(arche or get_active_archetype() or None) if (arche or get_active_archetype()) else []
        if words:
            return random.choice(words).upper()
    except Exception:
        pass

    lower_topic = (topic or "").lower()
    lower_cat = (category or "").lower()

    keyword_map = {
        "vanish": "VANISHED",
        "disappear": "VANISHED",
        "lost": "VANISHED",
        "erase": "ERASED",
        "destroy": "ERASED",
        "fall": "THE FALL",
        "collaps": "THE FALL",
        "trap": "TRAPPED",
        "siege": "TRAPPED",
        "explod": "THE BLAST",
        "eruption": "THE BLAST",
        "volcano": "THE BLAST",
        "earthquake": "THE BLAST",
        "tsunami": "THE FLOOD",
        "flood": "THE FLOOD",
        "fire": "THE FIRE",
        "burn": "THE FIRE",
        "curse": "THE CURSE",
        "betray": "BETRAYED",
        "doom": "DOOMED",
        "survivor": "NO SURVIVORS",
        "forgot": "FORGOTTEN",
        "buried": "BURIED SECRET",
        "secret": "BURIED SECRET",
        "signal": "THE SIGNAL",
        "legion": "LOST LEGION",
        "impossible": "IMPOSSIBLE",
        "escape": "NO ESCAPE",
        "war": "NO ESCAPE",
        "battle": "NO ESCAPE",
    }

    combined = f"{lower_topic} {lower_cat}"
    for keyword, text in keyword_map.items():
        if keyword in combined:
            return text

    return random.choice(examples)


def composite_cover_text(base_image: Image.Image, cover_text: str) -> Image.Image:
    img = base_image.copy().convert("RGBA")
    w, h = img.size

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    gradient_height = int(h * 0.4)
    for y_offset in range(gradient_height):
        alpha = int(180 * (y_offset / gradient_height))
        y_pos = h // 2 - gradient_height // 2 + y_offset
        draw.line([(0, y_pos), (w, y_pos)], fill=(0, 0, 0, alpha))

    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    for border_w in range(min(w, h) // 4):
        alpha = int(100 * (1 - border_w / (min(w, h) // 4)))
        vdraw.rectangle(
            [border_w, border_w, w - border_w - 1, h - border_w - 1],
            outline=(0, 0, 0, alpha),
        )
    img = Image.alpha_composite(img, vignette)
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    text = cover_text.upper().strip()

    max_text_width = int(w * 0.85)
    chosen_font = None
    chosen_size = 10

    for size in range(180, 60, -6):
        font = _get_font(size)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=max(3, size // 20))
        text_width = bbox[2] - bbox[0]
        if text_width <= max_text_width:
            chosen_font = font
            chosen_size = size
            break

    if chosen_font is None:
        chosen_font = _get_font(64)
        chosen_size = 64

    stroke_w = max(4, chosen_size // 16)

    center_x = w // 2
    center_y = h // 2

    draw.text(
        (center_x + 3, center_y + 3),
        text,
        font=chosen_font,
        fill=(0, 0, 0, 200),
        anchor="mm",
        stroke_width=stroke_w + 2,
        stroke_fill=(0, 0, 0, 180),
    )

    draw.text(
        (center_x, center_y),
        text,
        font=chosen_font,
        fill="#FFFFFF",
        anchor="mm",
        stroke_width=stroke_w,
        stroke_fill=(0, 0, 0, 220),
    )

    return img.convert("RGB")


def generate_cover_frame(
    topic: str,
    category: str,
    storyboard: Optional[dict] = None,
    output_dir: Optional[str] = None,
    image_gen_manager=None,
    image_provider: str = "auto",
    cover_text_override: Optional[str] = None,
    log_callback=None,
    media_base_dir: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    config = _get_cover_frame_config()
    # Sin corte por `enabled` (2026-09-23): la placa la decide el storyboard (video_opening). Si
    # un segmento la trae, es un proyecto viejo y se renderiza igual que antes; con el corte, al
    # apagarla en el Bible esos proyectos caian a un gradiente oscuro al re-renderizarlos.

    def _log(msg: str):
        if log_callback:
            try:
                log_callback(msg)
                return
            except Exception:
                pass
        print(msg)

    llm_cover_text = None
    if storyboard:
        llm_cover_text = storyboard.get("cover_text")

    cover_text = cover_text_override or select_cover_text(
        topic, category, storyboard, llm_suggestion=llm_cover_text
    )
    _log(f"   [Cover Frame] Text: {cover_text}")

    out_dir = Path(output_dir or str(_PROJECT_DIR / "generated_media"))
    out_dir.mkdir(parents=True, exist_ok=True)
    cover_image_path = out_dir / "cover_frame.png"

    prompt = build_cover_image_prompt(topic, category, cover_text, storyboard)

    base_image = None
    if image_gen_manager and hasattr(image_gen_manager, "generate_single_image"):
        _log(f"   [Cover Frame] Generating dedicated cover image via {image_provider}...")
        try:
            result_path = image_gen_manager.generate_single_image(
                prompt=prompt,
                width=COVER_SIZE[0],
                height=COVER_SIZE[1],
                output_path=str(out_dir / "cover_frame_base.png"),
                image_provider=image_provider,
                negative_prompt=(
                    "text, captions, subtitles, letters, numbers, watermark, logo, "
                    "signature, UI, modern objects, cartoon, anime, low quality, blurry"
                ),
            )
            if result_path and os.path.exists(result_path):
                base_image = Image.open(result_path).convert("RGBA")
                _log(f"   [Cover Frame] Base image generated: {os.path.basename(result_path)}")
        except Exception as exc:
            _log(f"   [Cover Frame] Image generation failed: {exc}")

    if base_image is None:
        _log("   [Cover Frame] Using first segment image as fallback...")
        if storyboard and storyboard.get("segments"):
            # Solo aceptamos archivos de imagen reales (no .mp4/.webm/etc).
            # PIL no puede abrir video, así que filtrar por extensión evita el
            # log "cannot identify image file 'X.mp4'" + caída al gradiente oscuro
            # cuando el usuario asignó un video al primer segmento (drag & drop).
            _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif", ".tiff", ".tif"}
            # Las rutas del storyboard suelen ser relativas al proyecto
            # ("project_media/segment_001.png"). Sin resolverlas, os.path.exists
            # falla desde el cwd y el cover cae al gradiente oscuro aunque haya
            # imagenes perfectamente usables.
            bases = [b for b in (media_base_dir, out_dir, Path.cwd()) if b]
            for seg in storyboard["segments"]:
                img_path = seg.get("image_path")
                if not img_path:
                    continue
                if not os.path.exists(str(img_path)):
                    for base in bases:
                        try:
                            candidato = Path(base) / str(img_path)
                        except Exception:
                            continue
                        if candidato.exists():
                            img_path = str(candidato)
                            break
                    else:
                        continue
                ext = os.path.splitext(str(img_path))[1].lower()
                if ext not in _IMAGE_EXTS:
                    _log(f"   [Cover Frame] Saltando {os.path.basename(str(img_path))} (no es imagen)")
                    continue
                try:
                    base_image = Image.open(str(img_path)).convert("RGBA")
                    _log(f"   [Cover Frame] Usando {os.path.basename(str(img_path))} como base")
                    break
                except Exception as exc:
                    _log(f"   [Cover Frame] No se pudo abrir {os.path.basename(str(img_path))}: {exc}")
                    continue

    if base_image is None:
        _log("   [Cover Frame] No base image available, creating dark gradient...")
        base_image = Image.new("RGBA", COVER_SIZE, (10, 10, 15, 255))
        draw = ImageDraw.Draw(base_image)
        for y in range(COVER_SIZE[1]):
            r = int(10 + 15 * (y / COVER_SIZE[1]))
            g = int(10 + 10 * (y / COVER_SIZE[1]))
            b = int(15 + 20 * (y / COVER_SIZE[1]))
            draw.line([(0, y), (COVER_SIZE[0], y)], fill=(r, g, b, 255))

    base_image = base_image.resize(COVER_SIZE, Image.LANCZOS)

    final_image = composite_cover_text(base_image, cover_text)
    final_image.save(str(cover_image_path), "PNG", quality=95)
    _log(f"   [Cover Frame] Saved: {cover_image_path}")

    return {
        "image_path": str(cover_image_path),
        "cover_text": cover_text,
        "duration": config.get("duration_seconds", 0.7),
    }


__all__ = [
    "generate_cover_frame",
    "build_cover_image_prompt",
    "select_cover_text",
    "composite_cover_text",
]
