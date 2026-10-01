from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from publish.thumbnail_formats import LANDSCAPE_16_9

# La API de datos de YouTube (thumbnails.set) corta en 2 MB EXACTOS y responde
# "Media larger than: 2097152". Ojo: NO son los 50 MB que admite el uploader web
# de Studio; ese limite es de la interfaz, no de la API. Un PNG de 1080x1920 con
# foto pesa ~2.7 MB, o sea que TODA miniatura vertical generada lo pasaba.
YOUTUBE_API_THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024

# Escalones de calidad JPEG. Se baja de a poco: preferimos 2 MB a q75 antes que
# 400 KB a q40, porque la miniatura se juzga a simple vista.
_JPEG_QUALITY_STEPS = (92, 85, 78, 70, 62, 55)

# Piso de ancho al reducir. Por debajo de esto la miniatura se ve borrosa en la
# grilla y ya no vale la pena seguir achicando.
_MIN_THUMBNAIL_WIDTH = 320


def fit_for_youtube_api(image_path, max_bytes: int = YOUTUBE_API_THUMBNAIL_MAX_BYTES,
                        log=None):
    """Devuelve una ruta de miniatura que entre en el limite de la API.

    Si el archivo ya entra, se devuelve tal cual. Si no, se reencoda a JPEG
    bajando calidad y, como ultimo recurso, reduciendo tamano. Se conserva la
    resolucion mientras se pueda: 1080x1920 esta muy por debajo del maximo de
    YouTube, lo que sobra son bytes de PNG sin comprimir.

    Devuelve (ruta, mimetype). Nunca lanza: ante cualquier problema devuelve el
    original y que el llamador reporte el error real de la API.
    """
    decir = log or (lambda _m: None)
    try:
        origen = Path(image_path)
        if not origen.is_file():
            return str(origen), "image/png"

        peso = origen.stat().st_size
        if peso <= max_bytes:
            sufijo = origen.suffix.lower()
            return str(origen), ("image/jpeg" if sufijo in (".jpg", ".jpeg") else "image/png")

        decir(f"   [thumb] {origen.name} pesa {peso/1048576:.2f} MB y la API corta en "
              f"{max_bytes/1048576:.0f} MB; se recomprime a JPEG.")
        with Image.open(origen) as img:
            base = img.convert("RGB")
            destino = origen.with_name(origen.stem + "_api.jpg")

            for calidad in _JPEG_QUALITY_STEPS:
                base.save(destino, "JPEG", quality=calidad, optimize=True,
                          progressive=True)
                nuevo = destino.stat().st_size
                if nuevo <= max_bytes:
                    decir(f"   [thumb] OK a calidad {calidad}: "
                          f"{nuevo/1048576:.2f} MB ({destino.name})")
                    return str(destino), "image/jpeg"

            # Ultimo recurso: bajar resolucion manteniendo el aspecto. Se itera
            # hasta que entre o hasta el piso de ancho: cortar a un numero fijo
            # de intentos dejaba archivos patologicos por encima del limite y
            # devolvia el original, o sea que no arreglaba nada.
            escalada = base
            while escalada.width > _MIN_THUMBNAIL_WIDTH:
                escalada = escalada.resize(
                    (max(1, escalada.width * 8 // 10), max(1, escalada.height * 8 // 10)),
                    Image.Resampling.LANCZOS)
                escalada.save(destino, "JPEG", quality=80, optimize=True, progressive=True)
                nuevo = destino.stat().st_size
                if nuevo <= max_bytes:
                    decir(f"   [thumb] OK reduciendo a {escalada.width}x{escalada.height}: "
                          f"{nuevo/1048576:.2f} MB")
                    return str(destino), "image/jpeg"

            # Piso alcanzado: mejor un JPEG chico y feo que un envio rechazado.
            escalada.save(destino, "JPEG", quality=45, optimize=True, progressive=True)
            nuevo = destino.stat().st_size
            if nuevo <= max_bytes:
                decir(f"   [thumb] OK al minimo ({escalada.width}x{escalada.height}, q45): "
                      f"{nuevo/1048576:.2f} MB")
                return str(destino), "image/jpeg"

        decir(f"   [thumb] [WARN] No se logro bajar de {max_bytes/1048576:.0f} MB; "
              "se sube el original y la API decidira.")
        return str(origen), "image/png"
    except Exception as exc:
        decir(f"   [thumb] [WARN] No se pudo recomprimir la miniatura: {exc}")
        return str(image_path), "image/png"


class ThumbnailCompositor:
    # Default historico. La geometria real la manda `thumbnail_formats`: un
    # Short necesita 1080x1920 y cajas de texto distintas, no esto rotado.
    SIZE = (1280, 720)
    HEADLINE_FONT_CANDIDATES = [
        "C:/Windows/Fonts/bahnschrift.ttf",
        "C:/Windows/Fonts/ARIALNB.TTF",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/ariblk.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    KICKER_FONT_CANDIDATES = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/bahnschrift.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    FONT_CANDIDATES = [
        "C:/Windows/Fonts/bahnschrift.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/ariblk.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]

    PALETTES = {
        "danger_yellow_black": {
            "accent": "#FFD400",
            "secondary": "#111111",
            "overlay": "#000000",
        },
        "orange_cyan": {
            "accent": "#FF8C1A",
            "secondary": "#14E0FF",
            "overlay": "#07141B",
        },
        "cold_blue_red": {
            "accent": "#4CC9FF",
            "secondary": "#FF4B5C",
            "overlay": "#09111A",
        },
    }

    def __init__(self, log_callback=None, thumbnail_format=None):
        self.log = log_callback or (lambda _msg: None)
        self.format = thumbnail_format or LANDSCAPE_16_9

    def _resolve_format(self, thumbnail_format=None):
        return thumbnail_format or self.format or LANDSCAPE_16_9

    def create_placeholder_background(self, output_path: str, palette_name: str, subject_hint: str = "",
                                      thumbnail_format=None) -> str:
        fmt = self._resolve_format(thumbnail_format)
        accent, secondary, overlay = self._palette_colors(palette_name)
        image = Image.new("RGB", fmt.size, overlay)
        draw = ImageDraw.Draw(image)

        W, H = fmt.size
        for index in range(H):
            ratio = index / max(1, H - 1)
            r = int(overlay[0] * (1.0 - ratio) + secondary[0] * ratio)
            g = int(overlay[1] * (1.0 - ratio) + secondary[1] * ratio)
            b = int(overlay[2] * (1.0 - ratio) + secondary[2] * ratio)
            draw.line([(0, index), (W, index)], fill=(r, g, b))

        # Las manchas de luz se definen en fracciones del lienzo: con las
        # coordenadas fijas de 1280x720 quedaban en la esquina de un 1080x1920.
        def box(l, t, r_, b_):
            return (int(l * W), int(t * H), int(r_ * W), int(b_ * H))

        glow = Image.new("RGBA", fmt.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse(box(0.141, 0.167, 0.547, 0.861), fill=accent + (100,))
        glow_draw.ellipse(box(0.484, 0.125, 0.922, 0.917), fill=secondary + (60,))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=44))
        image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")

        light_sweep = Image.new("RGBA", fmt.size, (0, 0, 0, 0))
        light_draw = ImageDraw.Draw(light_sweep)
        light_draw.polygon(
            [(0, 0), (int(0.39 * W), 0), (int(0.84 * W), H), (int(0.41 * W), H)],
            fill=accent + (28,),
        )
        light_sweep = light_sweep.filter(ImageFilter.GaussianBlur(radius=52))
        image = Image.alpha_composite(image.convert("RGBA"), light_sweep).convert("RGB")

        if subject_hint:
            overlay_draw = ImageDraw.Draw(image)
            font = self._get_font(34)
            overlay_draw.text((56, 48), subject_hint[:36].upper(), font=font, fill=(255, 255, 255, 120))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, "PNG")
        return output_path

    def compose_thumbnail(
        self,
        base_image_path: str,
        output_path: str,
        hook_text: str,
        palette_name: str,
        composition: str,
        kicker_text: Optional[str] = None,
        quality_tier: Optional[str] = None,
        thumbnail_format=None,
    ) -> str:
        fmt = self._resolve_format(thumbnail_format)
        image = Image.open(base_image_path).convert("RGB")
        image = self._fit_cover(image, fmt.size)
        image = self._grade(image, palette_name)
        image = self._apply_vignette(image)
        image = self._apply_finish(image, quality_tier)

        canvas = image.convert("RGBA")
        accent, secondary, overlay = self._palette_colors(palette_name)
        text_layer = Image.new("RGBA", fmt.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(text_layer)

        hook_text = (hook_text or "THE SECRET").strip().upper()
        kicker_text = (kicker_text or "").strip().upper()

        # La caja sale del formato, en fracciones. Antes estaba en pixeles de
        # 1280x720: en vertical el texto caia fuera del lienzo o encima de la
        # franja que YouTube tapa con el titulo del Short.
        text_box = fmt.text_box_pixels(composition)
        alignment = fmt.text_alignment(composition)

        panel_shadow = Image.new("RGBA", fmt.size, (0, 0, 0, 0))
        panel_shadow_draw = ImageDraw.Draw(panel_shadow)
        shadow_box = (
            text_box[0] + 10,
            text_box[1] + 14,
            text_box[2] + 10,
            text_box[3] + 14,
        )
        panel_shadow_draw.rounded_rectangle(shadow_box, radius=34, fill=(0, 0, 0, 96))
        panel_shadow = panel_shadow.filter(ImageFilter.GaussianBlur(radius=20))
        canvas = Image.alpha_composite(canvas, panel_shadow)

        panel = Image.new("RGBA", fmt.size, (0, 0, 0, 0))
        panel_draw = ImageDraw.Draw(panel)
        panel_draw.rounded_rectangle(text_box, radius=34, fill=overlay + (166,), outline=(255, 255, 255, 38), width=2)
        accent_bar_width = 170 if alignment == "left" else 220
        accent_bar_left = text_box[0] + 30 if alignment == "left" else int((text_box[0] + text_box[2] - accent_bar_width) / 2)
        accent_bar_box = (
            accent_bar_left,
            text_box[1] + 24,
            accent_bar_left + accent_bar_width,
            text_box[1] + 34,
        )
        panel_draw.rounded_rectangle(accent_bar_box, radius=5, fill=accent + (210,))
        panel = panel.filter(ImageFilter.GaussianBlur(radius=0.35))
        canvas = Image.alpha_composite(canvas, panel)

        if kicker_text:
            kicker_font, kicker_value = self._fit_single_line_text(
                draw,
                kicker_text,
                max_width=max(140, text_box[2] - text_box[0] - 20),
                # El kicker es el unico texto de tamano fijo (el titular se
                # auto-ajusta a la caja). Escala con el ancho del lienzo, si no
                # en vertical queda ilegible en la grilla de Shorts.
                start_size=int(28 * fmt.width / 1280.0 * (1.35 if fmt.is_vertical else 1.0)),
                min_size=int(18 * fmt.width / 1280.0 * (1.35 if fmt.is_vertical else 1.0)),
                role="kicker",
            )
            kicker_x = text_box[0] + 26 if alignment == "left" else (text_box[0] + text_box[2]) // 2
            kicker_y = max(24, text_box[1] - 48)
            self._draw_tracked_text(
                draw=draw,
                text=kicker_value,
                position=(kicker_x, kicker_y),
                font=kicker_font,
                fill=accent,
                tracking=max(1, int(kicker_font.size * 0.08)),
                align=alignment,
                anchor="lm" if alignment == "left" else "mm",
                shadow_fill=(0, 0, 0, 140),
                shadow_offset=2,
            )

        hook_font, lines = self._fit_text(draw, hook_text, text_box, role="headline")
        stroke_width = max(2, int(hook_font.size * 0.022))
        shadow_offset = max(2, int(hook_font.size * 0.03))
        line_boxes = [
            draw.textbbox((0, 0), line, font=hook_font, stroke_width=stroke_width)
            for line in lines
        ]
        line_heights = [max(1, box[3] - box[1]) for box in line_boxes]
        line_gap = max(10, int(hook_font.size * 0.08))
        total_height = sum(line_heights) + max(0, len(lines) - 1) * line_gap
        current_y = int(text_box[1] + max(0, (text_box[3] - text_box[1] - total_height) / 2))
        for index, line in enumerate(lines):
            color = accent if index == 0 else (246, 243, 236)
            box = line_boxes[index]
            line_width = max(1, box[2] - box[0])
            line_height = line_heights[index]
            if alignment == "center":
                x = int(text_box[0] + max(0, (text_box[2] - text_box[0] - line_width) / 2))
            else:
                x = int(text_box[0] + 34)
            y = int(current_y)
            draw.text(
                (x + shadow_offset, y + shadow_offset),
                line,
                font=hook_font,
                fill=(0, 0, 0, 115),
                stroke_fill=(0, 0, 0, 90),
                stroke_width=max(1, stroke_width - 1),
            )
            draw.text(
                (x, y),
                line,
                font=hook_font,
                fill=color,
                stroke_fill=(8, 10, 14),
                stroke_width=stroke_width,
            )
            current_y += line_height + line_gap

        canvas = Image.alpha_composite(canvas, text_layer)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, "PNG", quality=95)
        return output_path

    def _fit_cover(self, image: Image.Image, size: Tuple[int, int]) -> Image.Image:
        src_w, src_h = image.size
        dst_w, dst_h = size
        src_ratio = src_w / max(1, src_h)
        dst_ratio = dst_w / max(1, dst_h)
        if src_ratio > dst_ratio:
            new_height = dst_h
            new_width = int(new_height * src_ratio)
        else:
            new_width = dst_w
            new_height = int(new_width / max(0.0001, src_ratio))
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        left = max(0, int((new_width - dst_w) / 2))
        top = max(0, int((new_height - dst_h) / 2))
        return image.crop((left, top, left + dst_w, top + dst_h))

    def _grade(self, image: Image.Image, palette_name: str) -> Image.Image:
        accent, secondary, overlay = self._palette_colors(palette_name)
        image = ImageEnhance.Contrast(image).enhance(1.22)
        image = ImageEnhance.Color(image).enhance(1.24)
        tint = Image.new("RGBA", image.size, secondary + (26,))
        image = Image.alpha_composite(image.convert("RGBA"), tint).convert("RGB")
        image = ImageEnhance.Sharpness(image).enhance(1.18)
        glow = Image.new("RGBA", image.size, accent + (18,))
        image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")
        return image

    def _apply_vignette(self, image: Image.Image) -> Image.Image:
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((-120, -80, image.size[0] + 120, image.size[1] + 80), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=80))
        dark = Image.new("RGB", image.size, (0, 0, 0))
        return Image.composite(image, dark, Image.eval(mask, lambda value: 255 - int(value * 0.55)))

    def _apply_finish(self, image: Image.Image, quality_tier: Optional[str]) -> Image.Image:
        quality = str(quality_tier or "").strip().lower()

        bloom = image.filter(ImageFilter.GaussianBlur(radius=10))
        image = Image.blend(image, bloom, 0.12 if "epic" in quality or "premium" in quality else 0.08)

        noise = Image.effect_noise(image.size, 10 if "epic" in quality or "premium" in quality else 6)
        noise = noise.convert("L")
        grain = Image.new("RGBA", image.size, (255, 255, 255, 0))
        grain.putalpha(Image.eval(noise, lambda value: int(value * 0.10)))
        image = Image.alpha_composite(image.convert("RGBA"), grain).convert("RGB")

        image = ImageEnhance.Contrast(image).enhance(1.05)
        image = ImageEnhance.Sharpness(image).enhance(1.08)
        return image

    def _fit_single_line_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        max_width: int,
        start_size: int,
        min_size: int,
        role: str = "kicker",
    ):
        value = str(text or "").strip().upper()
        words = value.split()
        if not words:
            return self._get_font(start_size, role=role), ""

        font_size = start_size
        while font_size >= min_size:
            font = self._get_font(font_size, role=role)
            probe = " ".join(words)
            width = draw.textbbox((0, 0), probe, font=font, stroke_width=2)[2]
            if width <= max_width:
                return font, probe
            if len(words) > 1:
                words = words[:-1]
                continue
            font_size -= 2
        return self._get_font(min_size, role=role), " ".join(words[:2])

    def _fit_text(self, draw: ImageDraw.ImageDraw, text: str, box: Tuple[int, int, int, int], role: str = "headline"):
        max_width = max(120, box[2] - box[0] - 50)
        max_height = max(80, box[3] - box[1] - 40)

        for size in range(120, 52, -4):
            font = self._get_font(size, role=role)
            lines = self._wrap_text(draw, text, font, max_width)
            line_height = int(size * 0.98)
            total_height = len(lines) * line_height
            widths = [
                draw.textbbox((0, 0), line, font=font, stroke_width=max(2, int(size * 0.022)))[2]
                for line in lines
            ]
            if widths and max(widths) <= max_width and total_height <= max_height:
                return font, lines

        fallback_font = self._get_font(52, role=role)
        return fallback_font, self._wrap_text(draw, text, fallback_font, max_width)

    def _wrap_text(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int):
        words = text.split()
        lines = []
        current = []
        for word in words:
            probe = " ".join(current + [word]).strip()
            width = draw.textbbox((0, 0), probe, font=font)[2]
            if current and width > max_width:
                lines.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            lines.append(" ".join(current))
        return lines or [text]


    def _draw_tracked_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        position,
        font,
        fill,
        tracking: int,
        align: str,
        anchor: str,
        shadow_fill,
        shadow_offset: int,
    ):
        value = str(text or "").strip()
        if not value:
            return

        chars = list(value)
        widths = []
        for char in chars:
            if char == " ":
                widths.append(max(8, tracking * 3))
                continue
            box = draw.textbbox((0, 0), char, font=font)
            widths.append(max(1, box[2] - box[0]) + tracking)
        total_width = max(0, sum(widths) - tracking)

        x, y = position
        if anchor == "mm":
            cursor_x = int(x - total_width / 2)
        elif anchor == "rm":
            cursor_x = int(x - total_width)
        else:
            cursor_x = int(x)

        baseline_y = int(y)
        for index, char in enumerate(chars):
            advance = widths[index]
            if char == " ":
                cursor_x += advance
                continue
            draw.text((cursor_x + shadow_offset, baseline_y + shadow_offset), char, font=font, fill=shadow_fill)
            draw.text((cursor_x, baseline_y), char, font=font, fill=fill)
            cursor_x += advance

    def _get_font(self, size: int, role: str = "headline"):
        if role == "kicker":
            font_candidates = self.KICKER_FONT_CANDIDATES + self.FONT_CANDIDATES
        else:
            font_candidates = self.HEADLINE_FONT_CANDIDATES + self.FONT_CANDIDATES
        seen = set()
        ordered_candidates = []
        for font_path in font_candidates:
            if font_path not in seen:
                ordered_candidates.append(font_path)
                seen.add(font_path)
        for font_path in ordered_candidates:
            if Path(font_path).exists():
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _palette_colors(self, palette_name: str):
        palette = self.PALETTES.get(palette_name, self.PALETTES["danger_yellow_black"])
        return (
            ImageColor.getrgb(palette["accent"]),
            ImageColor.getrgb(palette["secondary"]),
            ImageColor.getrgb(palette["overlay"]),
        )
