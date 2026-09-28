# -*- coding: utf-8 -*-
"""Formato "Catarsis": Short vertical de impacto, sin voz.

Tarjetas de texto, imagenes, videos y musica con cortes secos al ritmo. La tension sube
(preguntas, cortes cada vez mas rapidos, destellos) y se suelta de golpe (silencio, una imagen
quieta, la frase final). Es el lenguaje de los monologos finales de Evangelion, hecho con
material propio: nada de clips, musica ni tipografia de la serie (Content ID los reclama).

Un proyecto (JSON) tiene: tarjetas, medios (imagenes y videos, con o sin su audio), musica,
estilo y la secuencia de planos. auto_sequence() arma el arco; la pestana Catarsis de la app
deja retocar cada plano antes del render. Los guiones viejos (images/opening/lines...) se leen.

Efectos (se prenden en el estilo): texto cinetico y texto sobre imagen, impact frames de anime,
color por acto y resplandor, doble exposicion, pantalla dividida, rampas de velocidad, quiebre
en la caida de la musica, loop perfecto, zonas seguras de Shorts y diseno sonoro sintetizado
(sin derechos: whoosh, golpes, subida, pitido y boom).

    .venv\\Scripts\\python.exe catharsis_editor.py examples\\catharsis_oppenheimer.json --images carpeta --music pista.mp3

Seguridad: como mucho 3 destellos por segundo (WCAG 2.3.1 / prueba de Harding). Los cambios
bruscos de luz de a 2 cuadros pueden provocar crisis en personas fotosensibles.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import textwrap
from collections import deque
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS, SR = 1080, 1920, 30, 44100
PAPER, INK, RED = (242, 240, 234), (8, 8, 8), (186, 14, 22)
FONT_CANDIDATES = (
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
)
CONDENSE = 0.72   # serif pesada y angosta, como las tarjetas de Evangelion
SAFE_W = 0.78     # ancho maximo del texto: lejos de los botones de la derecha (Shorts)
SAFE_Y = 0.45     # centro vertical del texto: por encima del titulo y el canal de abajo

# Arco, como fraccion de la duracion total: apertura, subida, climax, quiebre y cierre.
OPENING, RISE_END, CLIMAX_END, BREAK_END = 0.12, 0.62, 0.80, 0.84
FLASH_FRAMES = 2
MAX_FLASHES_PER_SECOND = 3
FLASH_DELTA = 100          # salto de luminancia media (0-255) que cuenta como destello
FADE_OUT_FRAMES = 18
KINETIC_FRAMES = 6         # el texto entra agrandado y desenfocado y se asienta en estos cuadros
TRANSITION_FRAMES = {"glitch": 5, "burn": 14, "zoom": 4}
MIN_CLIP_AUDIO = 0.4       # segundos: un plano mas corto no lleva el audio de su video
AUDIO_HOLD = 1.2           # en la subida, un video con su audio dura al menos esto (si no, no se oye)
RAMP_HOLD = 0.9            # y uno con rampa de velocidad, esto (si no, la rampa no se ve)
MIN_MEDIA = 0.45           # segundos de imagen por frase en la subida, como minimo
LOOP_CARD = 0.6            # el loop cierra con la pregunta inicial, igual al primer cuadro
DROP_AT = 0.80             # una pista larga se toma desde donde su caida quede en este punto del video

VARIANTS = ("color", "base", "negative", "red", "hard", "sketch")
TRANSITIONS = ("cut", "flash", "glitch", "burn", "zoom")
MOTIONS = ("hold", "push", "pull", "punch", "shake", "ramp")
KINDS = ("card", "media", "overlay", "double", "split", "impact", "color")
COLORS = {"black": (0, 0, 0), "white": PAPER, "red": RED}
GRADES = {"rise": (0.90, 0.97, 1.10), "climax": (1.12, 0.80, 0.78), "final": (1.05, 1.0, 0.92)}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
DEFAULT_STYLE = {"speed": 1.0, "flashes": 1.0, "variants": ["base", "negative", "sketch", "red", "hard"],
                 "transitions": ["glitch", "burn"], "grain": True, "vignette": True, "shake": True,
                 "kinetic": True, "impact": True, "grade": True, "bloom": True, "double": True, "split": True,
                 "ramps": True, "drop": True, "loop": True, "sfx": True}
DEFAULT_CARDS = {"opening": "Who am I?", "lines": [], "climax": ["WHO", "AM", "I"], "final": [], "end": ""}


@dataclass
class Shot:
    frames: int
    image: Image.Image             # cuadro fijo; en un video, su primer cuadro
    motion: str = "hold"           # hold | push | pull | punch | shake | ramp
    grain: bool = True
    red: bool = False              # destello rojo saturado: cuenta siempre como destello
    tag: str = ""                  # "break": el quiebre, donde la musica se calla
    clip: Optional[dict] = None    # video: {"file", "start", "variant", "focus", "zoom", "act", "ramp"...}
    transition: str = "cut"        # como entra el plano: cut | glitch | burn | zoom
    audio: Optional[tuple] = None  # (archivo, segundo) si suena el audio del video
    role: str = ""                 # card | word | media | overlay | impact | color (para el sonido)
    act: str = ""                  # open | rise | climax | break | final
    kinetic: bool = False          # el texto entra: se agranda, se enfoca y deja eco
    text_layer: Optional[Image.Image] = None   # texto sobre imagen (RGBA), animado aparte


# ---------------------------------------------------------------- tarjetas de texto
@lru_cache(maxsize=64)
def _font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_layer(text: str, size: int, fill) -> Image.Image:
    font = _font(size)
    left, top, right, bottom = font.getbbox(text)
    layer = Image.new("RGBA", (right - left + 8, bottom - top + 8), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((4 - left, 4 - top), text, font=font, fill=fill)
    return layer.resize((max(1, int(layer.width * CONDENSE)), layer.height), Image.LANCZOS)


def _fit_line(text: str, max_w: int, size: int, fill) -> Image.Image:
    layer = _text_layer(text, size, fill)
    while layer.width > max_w and size > 24:
        size = int(size * 0.92)
        layer = _text_layer(text, size, fill)
    return layer


def text_card(text: str, style: str = "center") -> Image.Image:
    """Tarjeta 1080x1920 dentro de la zona segura de Shorts. Estilos: center, left, invert
    (negro sobre papel), red, word (una palabra enorme) y caption (chica)."""
    bg, fg = (0, 0, 0), PAPER
    if style == "invert":
        bg, fg = PAPER, INK
    elif style == "red":
        bg = RED
    img = Image.new("RGB", (W, H), bg)
    max_w = int(W * SAFE_W)
    if style == "word":
        layer = _fit_line(text.upper(), max_w, 820, fg)
        img.paste(layer, ((W - layer.width) // 2, int(H * SAFE_Y - layer.height / 2)), layer)
        return img
    width = 28 if style == "caption" else 14
    lines = [l for part in text.split("\n") for l in (textwrap.wrap(part, width) or [""])]
    size = {"caption": 72, "left": 220}.get(style, 210 if len(lines) <= 2 else 150)
    layers = [_fit_line(l, max_w, size, fg) for l in lines]
    gap = size // 4
    y = int(H * SAFE_Y - (sum(l.height for l in layers) + gap * (len(layers) - 1)) / 2)
    if style == "left":
        y = int(H * 0.28)
    for layer in layers:
        x = int(W * 0.08) if style == "left" else (W - layer.width) // 2
        img.paste(layer, (x, y), layer)
        y += layer.height + gap
    return img


def overlay_layer(text: str) -> Image.Image:
    """Texto blanco (RGBA) para ir encima de una imagen o un video, en la zona segura, con un halo
    oscuro que lo separa del fondo: se lee sobre cualquier tono (el texto invertido se perdia en los grises)."""
    mask = text_card(text, "center").convert("L")
    m = np.asarray(mask, dtype=np.float32) / 255.0
    halo = np.clip(np.asarray(mask.filter(ImageFilter.GaussianBlur(24)), dtype=np.float32) / 255.0 * 2.5, 0, 1) * 0.72
    alpha = m + halo * (1.0 - m)                     # texto blanco "sobre" el halo negro
    rgb = m[..., None] * np.asarray(PAPER, dtype=np.float32) / np.maximum(alpha, 1e-6)[..., None]
    return Image.fromarray(np.dstack([rgb, alpha * 255.0]).clip(0, 255).astype(np.uint8), "RGBA")


# ---------------------------------------------------------------- imagenes y videos
def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


@lru_cache(maxsize=256)
def media_info(path: str) -> dict:
    """Duracion, tamano y si tiene audio, leidos de la salida de `ffmpeg -i`."""
    err = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True,
                         text=True, errors="replace").stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    size = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", err)
    return {"duration": (int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3])) if dur else 0.0,
            "width": int(size[1]) if size else 0, "height": int(size[2]) if size else 0,
            "audio": bool(re.search(r"Stream #.*Audio:", err))}


def frame_image(path: Path, focus=(0.5, 0.5), zoom: float = 1.0) -> Image.Image:
    """Recorte vertical 1080x1920 (en color) centrado en `focus` (0-1) con `zoom`."""
    im = Image.open(path).convert("RGB")
    scale = max(W / im.width, H / im.height) * max(zoom, 1.0)
    cw, ch = W / scale, H / scale   # zona de la foto que llena el cuadro
    left = min(max(focus[0] * im.width - cw / 2, 0), im.width - cw)
    top = min(max(focus[1] * im.height - ch / 2, 0), im.height - ch)
    return im.resize((W, H), Image.LANCZOS, box=(left, top, left + cw, top + ch))


def iter_video_frames(path, start: float, count: int, focus=(0.5, 0.5), zoom: float = 1.0,
                      size=(W, H)) -> Iterator[Image.Image]:
    """Cuadros de un video a 30 fps, recortados a vertical. Si el video se acaba, repite el ultimo."""
    info = media_info(str(path))
    w, h = size
    iw, ih = info["width"] or w, info["height"] or h
    scale = max(w / iw, h / ih) * max(zoom, 1.0)
    sw, sh = max(w, round(iw * scale)), max(h, round(ih * scale))
    left = int(min(max(focus[0] * sw - w / 2, 0), sw - w))
    top = int(min(max(focus[1] * sh - h / 2, 0), sh - h))
    cmd = [_ffmpeg(), "-loglevel", "error", "-ss", f"{max(start, 0):.3f}", "-i", str(path),
           "-frames:v", str(count), "-vf", f"fps={FPS},scale={sw}:{sh},crop={w}:{h}:{left}:{top}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    last, frame_bytes, sent = None, w * h * 3, 0
    try:
        while sent < count:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            last = Image.frombytes("RGB", (w, h), raw)
            sent += 1
            yield last
    finally:
        proc.stdout.close()
        proc.wait()
    while sent < count:
        sent += 1
        yield last if last is not None else Image.new("RGB", (w, h), (0, 0, 0))


def iter_clip_frames(path, start: float, count: int, focus=(0.5, 0.5), zoom: float = 1.0,
                     ramp: bool = False) -> Iterator[Image.Image]:
    """Como iter_video_frames; con ramp=True el clip va lento (0.4x) el 60 % del plano y de golpe
    rapido (2.5x) el resto. Los cuadros intermedios de la camara lenta se mezclan."""
    if not ramp:
        yield from iter_video_frames(path, start, count, focus, zoom)
        return
    slow, pos, positions = int(count * 0.6), 0.0, []
    for i in range(count):
        positions.append(pos)
        pos += 0.4 if i < slow else 2.5
    src = iter_video_frames(path, start, int(math.ceil(positions[-1])) + 2, focus, zoom)
    index, cur = 0, next(src)
    nxt = next(src, cur)
    for p in positions:
        while index + 1 <= int(p):
            cur, nxt, index = nxt, next(src, nxt), index + 1
        frac = p - int(p)
        yield cur if frac < 0.05 else Image.blend(cur, nxt, frac)


def _contrast(img: Image.Image, cutoff: float = 1.0, max_gain: float = 2.5) -> Image.Image:
    """Autocontraste con tope de ganancia (y el mismo estiramiento en los tres canales, asi no cambia el
    tono): un cuadro casi parejo, como un destello o un cielo, no se estira hasta mostrar los bloques de
    la compresion del video."""
    hist = np.asarray(img.histogram(), dtype=np.float64).reshape(-1, 256).sum(0)
    cum = np.cumsum(hist) / max(hist.sum(), 1.0)
    lo, hi = float(np.searchsorted(cum, cutoff / 100)), float(np.searchsorted(cum, 1 - cutoff / 100))
    span = max(hi - lo, 1.0)
    out = min(255.0, span * max_gain)
    base = lo * (255.0 - out) / max(255.0 - span, 1.0)   # un cuadro claro sigue claro
    lut = np.clip(base + (np.arange(256) - lo) * out / span, 0, 255).astype(np.uint8).tolist()
    return img.point(lut * len(img.getbands()))


def _sketch(gray: Image.Image) -> Image.Image:
    """Lapiz sobre papel: division de la imagen por su negativo desenfocado (color dodge)."""
    base = np.asarray(gray, dtype=np.float32)
    blur = np.asarray(ImageOps.invert(gray).filter(ImageFilter.GaussianBlur(10)), dtype=np.float32)
    lines = np.clip(base * 255.0 / np.maximum(255.0 - blur, 1.0), 0, 255)
    lines = np.where(lines > 232, 255.0, lines * 0.8)
    paper = np.asarray(PAPER, dtype=np.float32) / 255.0
    return Image.fromarray((lines[..., None] * paper).astype(np.uint8), "RGB")


def variant(img: Image.Image, kind: str) -> Image.Image:
    """color, base (B/N contrastado), negative, red, hard (dos tonos) o sketch."""
    if kind == "color":
        return _contrast(img.convert("RGB"))
    g = _contrast(img.convert("L"))
    if kind == "negative":
        return ImageOps.invert(g).convert("RGB")
    if kind == "red":
        return ImageOps.colorize(g, black=(0, 0, 0), white=(255, 46, 40))
    if kind == "hard":
        return g.point(lambda v: 255 if v > 118 else 0).convert("RGB")
    if kind == "sketch":
        return _sketch(g)
    return g.convert("RGB")


def grade(img: Image.Image, act: str) -> Image.Image:
    """Color por acto: frio en la subida, rojo en el climax, calido y limpio en la catarsis."""
    mult = GRADES.get(act)
    if not mult:
        return img
    arr = np.asarray(img, dtype=np.float32) * np.asarray(mult, dtype=np.float32)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def bloom(img: Image.Image, strength: float = 0.45) -> Image.Image:
    """Resplandor: las luces altas se desenfocan y se suman (mezcla screen)."""
    small = img.resize((W // 4, H // 4), Image.BILINEAR)
    lum = np.asarray(small.convert("L"), dtype=np.float32)
    mask = np.clip((lum - 170.0) / 85.0, 0, 1)[..., None]
    glow = Image.fromarray((np.asarray(small, dtype=np.float32) * mask).astype(np.uint8))
    glow = np.asarray(glow.filter(ImageFilter.GaussianBlur(9)).resize((W, H), Image.BILINEAR), np.float32) * strength
    base = np.asarray(img, dtype=np.float32)
    return Image.fromarray(np.clip(255.0 - (255.0 - base) * (255.0 - glow) / 255.0, 0, 255).astype(np.uint8))


def impact_image(img: Image.Image, seed: int = 0) -> Image.Image:
    """Impact frame de anime: dos tonos invertidos y lineas de velocidad hacia el centro."""
    g = _contrast(img.convert("L"), cutoff=2)
    thr = min(180, max(70, int(np.median(np.asarray(g)))))   # la silueta se separa aunque la foto sea clara u oscura
    base = ImageOps.invert(g.point(lambda v: 255 if v > thr else 0)).convert("RGB")
    draw, rng = ImageDraw.Draw(base), random.Random(seed)
    cx, cy = W / 2, H * SAFE_Y
    for _ in range(90):
        a = rng.uniform(0, 2 * math.pi)
        r0, r1 = rng.uniform(0.28, 0.45) * H, 1.2 * H
        draw.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)), (cx + r1 * math.cos(a), cy + r1 * math.sin(a))],
                  fill=(0, 0, 0), width=rng.randint(2, 9))
    return base


def double_image(a: Image.Image, b: Image.Image) -> Image.Image:
    """Doble exposicion: la segunda imagen entra desde arriba y se funde (screen) con la primera."""
    fa = np.asarray(a, dtype=np.float32)
    fb = np.asarray(b, dtype=np.float32) * np.linspace(1.0, 0.25, H, dtype=np.float32)[:, None, None]
    return Image.fromarray(np.clip(255.0 - (255.0 - fa) * (255.0 - fb) / 255.0, 0, 255).astype(np.uint8))


def split_image(images: list, gap: int = 14) -> Image.Image:
    """Pantalla dividida: 2 o 3 franjas horizontales (el centro de cada imagen) con un filo negro."""
    n = max(1, len(images))
    band = (H - gap * (n - 1)) // n
    out = Image.new("RGB", (W, H), (0, 0, 0))
    for k, img in enumerate(images):
        top = (H - band) // 2
        out.paste(img.crop((0, top, W, top + band)), (0, k * (band + gap)))
    return out


def _guide_mask() -> np.ndarray:
    """Zonas que tapa la interfaz de Shorts: arriba, abajo (titulo y canal) y botones a la derecha."""
    mask = np.zeros((H, W, 1), dtype=np.float32)
    mask[: int(H * 0.08)] = 0.3
    mask[int(H * 0.80):] = 0.3
    mask[int(H * 0.45): int(H * 0.80), int(W * 0.86):] = 0.3
    return mask


def media_thumbnail(item: dict, size=(180, 320)) -> Image.Image:
    """Miniatura vertical de un medio del proyecto (para la lista de la pestana)."""
    return _still_of(item).resize(size, Image.BILINEAR)


def _still_of(m: dict) -> Image.Image:
    focus, zoom = tuple(m.get("focus", (0.5, 0.5))), m.get("zoom", 1.0)
    if m.get("type") == "video":
        return next(iter_video_frames(m["file"], float(m.get("in", 0.0)), 1, focus, zoom))
    return frame_image(Path(m["file"]), focus, zoom)


# ---------------------------------------------------------------- ritmo
def music_analysis(path, seconds: float, start: float = 0.0):
    """Golpes de la musica y su caida (tomandola desde `start`): el mayor salto de energia entre el
    55 % y el 92 % del video. Sin analisis, (lista vacia, None): los cortes quedan a tiempo fijo."""
    try:
        import librosa
        y, sr = librosa.load(str(path), sr=22050, mono=True, offset=float(start or 0.0), duration=seconds + 1)
        _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        hop = 512
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
        w = max(1, int(sr / hop))
        cs = np.concatenate([[0.0], np.cumsum(rms)])
        idx = np.arange(w, len(rms) - w)
        drop = None
        if len(idx):
            score = (cs[idx + w] - cs[idx]) / w - (cs[idx] - cs[idx - w]) / w
            times = idx * hop / sr
            ok = (times >= 0.55 * seconds) & (times <= 0.92 * seconds)
            if ok.any():
                j = int(np.argmax(np.where(ok, score, -np.inf)))
                if score[j] > 0.25 * float(rms.max()):
                    drop = float(times[j])
        return [float(b) for b in beats], drop
    except Exception as exc:
        print(f"[catarsis] sin analisis de musica ({exc}); cortes a tiempo fijo")
        return [], None


def music_beats(path, seconds: float) -> list[float]:
    return music_analysis(path, seconds)[0]


def find_music_start(path, seconds: float):
    """Pistas largas (la Biblioteca de Audio trae temas de 2 a 5 minutos): desde donde tomarla para que
    su caida mas fuerte quede en DROP_AT del video, sin arrancar en una introduccion casi muda.
    Devuelve (inicio, caida en la pista); sin caida clara que entre, (0.0, None)."""
    try:
        import librosa
        y, sr = librosa.load(str(path), sr=22050, mono=True)
    except Exception as exc:
        print(f"[catarsis] no se pudo analizar la pista ({exc}); se usa desde el inicio")
        return 0.0, None
    hop, target = 512, DROP_AT * seconds
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    w = max(1, int(sr / hop))
    idx = np.arange(w, len(rms) - 2 * w)
    if not len(idx):
        return 0.0, None
    cs = np.concatenate([[0.0], np.cumsum(rms)])
    score = (cs[idx + w] - 2 * cs[idx] + cs[idx - w]) / w           # energia del segundo siguiente - la del anterior
    times = idx * hop / sr
    starts = times - target
    ok = (starts >= 0) & (starts + seconds <= len(y) / sr)
    first = np.clip((starts * sr / hop).astype(int), 0, len(rms) - 2 * w)
    opening = (cs[first + 2 * w] - cs[first]) / (2 * w)             # los 2 s con que arrancaria el video
    score = np.where(opening < 0.35 * float(np.median(rms)), score * 0.3, score)
    if not ok.any():
        return 0.0, None
    j = int(np.argmax(np.where(ok, score, -np.inf)))
    if score[j] <= 0.25 * float(rms.max()):
        return 0.0, None
    return round(float(starts[j]), 2), float(times[j])


def _snap_cuts(durations: list[float], start: float, beats: list[float], tol: float = 0.14) -> list[float]:
    """Mueve cada corte interno al golpe mas cercano (si esta a menos de `tol` s)."""
    if not beats or len(durations) < 2:
        return durations
    cuts = np.cumsum([start] + list(durations))
    for i in range(1, len(cuts) - 1):
        near = min(beats, key=lambda b: abs(b - cuts[i]))
        lo, hi = cuts[i - 1] + 2 / FPS, cuts[i + 1] - 2 / FPS
        if abs(near - cuts[i]) <= tol and lo < near < hi:
            cuts[i] = near
    return [float(d) for d in np.diff(cuts)]


def _phase_bounds(T: float, drop: Optional[float] = None):
    """(fin de apertura, fin de subida, fin del climax, fin del quiebre) en segundos. Con la caida
    de la musica, el quiebre termina justo ahi: la catarsis arranca con el golpe."""
    bounds = (OPENING * T, RISE_END * T, CLIMAX_END * T, BREAK_END * T)
    if drop:   # el climax y el quiebre conservan su largo; la subida se estira o se acorta
        c_end = drop - (BREAK_END - CLIMAX_END) * T
        r_end = c_end - (CLIMAX_END - RISE_END) * T
        if r_end - bounds[0] >= 6.0 and drop <= T - 3.0:
            return bounds[0], r_end, c_end, drop
    return bounds


# ---------------------------------------------------------------- proyecto y arco
def normalize_project(data: dict, base_dir=None, seconds=None) -> dict:
    """Proyecto completo a partir de uno nuevo o de un guion viejo (images/opening/lines...)."""
    p = json.loads(json.dumps(data))
    base = Path(base_dir) if base_dir else None
    if "media" not in p:
        p["media"] = [dict(m) for m in p.pop("images", [])]
    for m in p["media"]:
        f = Path(m["file"])
        if base is not None and not f.is_absolute():
            m["file"] = str(base / f)
        m.setdefault("type", "video" if f.suffix.lower() in VIDEO_EXT else "image")
    cards = p.setdefault("cards", {})
    for key, default in DEFAULT_CARDS.items():
        if key in p:
            cards.setdefault(key, p.pop(key))
        cards.setdefault(key, list(default) if isinstance(default, list) else default)
    p["style"] = {**DEFAULT_STYLE, **(p.get("style") or {})}
    if seconds:
        p["seconds"] = float(seconds)
    p.setdefault("seconds", 40.0)
    return p


def _reading_time(line: str) -> float:
    return min(2.4, max(0.8, 0.5 + 0.22 * len(line.split())))


def _style_for(line: str, i: int) -> str:
    if line.rstrip().endswith("?"):
        return "center"
    if any(ch.isdigit() for ch in line):
        return "left"
    return ("center", "invert")[i % 2]


def auto_sequence(project: dict, beats=(), seed: int = 7, drop: Optional[float] = None) -> list[dict]:
    """El arco automatico, como lista de planos editables (lo que muestra la pestana)."""
    rng = random.Random(seed)
    T, cards, style, media = float(project["seconds"]), project["cards"], project["style"], project["media"]
    if not media:
        raise ValueError("Agrega al menos una imagen o un video.")
    variants = [v for v in style.get("variants") or [] if v in VARIANTS] or ["base"]
    speed = min(2.0, max(0.5, float(style.get("speed", 1.0))))
    flashes = min(2.0, max(0.0, float(style.get("flashes", 1.0))))
    extra_tr = [t for t in style.get("transitions") or [] if t in ("glitch", "burn", "zoom")]
    on = {k: bool(style.get(k, DEFAULT_STYLE.get(k))) for k in DEFAULT_STYLE if isinstance(DEFAULT_STYLE[k], bool)}
    motions = ["push", "hold", "punch"] + (["shake"] if on["shake"] else []) + (["ramp"] if on["ramps"] else [])
    first = "base" if "base" in variants else variants[0]
    sketch = "sketch" if "sketch" in variants else first
    open_end, rise_end, climax_end, break_end = _phase_bounds(T, drop if on["drop"] else None)
    seq: list[dict] = []
    ramped: set = set()

    def span(m):
        return float(m.get("out") or media_info(m["file"])["duration"] or 0) - float(m.get("in", 0.0))

    def add(spec, act, **extra):
        spec.update(extra)
        spec.setdefault("transition", "cut")
        spec.setdefault("motion", "hold")
        spec["act"] = act
        seq.append(spec)
        return spec

    def card(text, st, d, act, kinetic=on["kinetic"]):
        return add({"kind": "card", "text": text, "style": st, "seconds": d, "kinetic": kinetic}, act)

    def shot(i, kind, d, act, motion="hold", transition="cut"):
        m = media[i % len(media)]
        video = m.get("type") == "video"
        loud = video and bool(m.get("audio"))
        if on["ramps"] and video and not loud and act == "rise" and i % len(media) not in ramped:
            motion = "ramp"   # camara lenta que de golpe acelera (la primera vez que aparece cada video)
            ramped.add(i % len(media))
        elif motion == "ramp" and (loud or d < 0.5):
            motion = "push"   # con rampa el audio del clip se desfasaria; y en un plano corto no se nota
        offset = round(rng.uniform(0, max(span(m) - d, 0)), 2) if video else 0.0
        return add({"kind": "media", "media": i % len(media), "variant": kind, "seconds": d, "motion": motion,
                    "transition": transition, "offset": offset, "audio": bool(m.get("audio"))}, act)

    def color(name, d, act, tag=""):
        return add({"kind": "color", "color": name, "seconds": d, "tag": tag}, act)

    def pick_tr(p):
        return rng.choice(extra_tr) if extra_tr and rng.random() < p else "cut"

    # 1. Apertura. Con loop, el primer cuadro ya es la pregunta (y el ultimo tambien).
    lead = 0.0 if on["loop"] else 0.5
    if lead:
        color("black", lead, "open")
    card_d = max(1.6, open_end * 0.45)
    card(cards.get("opening") or DEFAULT_CARDS["opening"], "center", card_d, "open",
         kinetic=on["kinetic"] and not on["loop"])
    shot(0, first, max(0.8, open_end - lead - card_d), "open", "push")

    # 2. Subida: frase, imagen(es) y cada tanto un destello; las imagenes duran cada vez menos.
    lines = [l for l in cards.get("lines") or [] if str(l).strip()]
    if not lines:   # sin frases la subida es solo de imagenes, una cada ~1.2 s (si no, el climax se la comeria)
        lines = [""] * max(3, int((rise_end - open_end) / 1.2))
    rise = rise_end - sum(s["seconds"] for s in seq)
    every = max(1, round(3 / flashes)) if flashes > 0 else 0
    flash_s = FLASH_FRAMES / FPS
    reserve = (0.9 if on["double"] and len(media) >= 2 else 0) + (0.8 if on["split"] and len(media) >= 3 else 0)
    fixed = (len(lines) // every if every else 0) * flash_s + reserve
    reading = [_reading_time(l) if l else 0.0 for l in lines]
    budget = rise - sum(reading) - fixed
    if lines and budget < MIN_MEDIA * len(lines):      # guion largo: tarjetas mas cortas, nunca bajo 0.7 s
        k = max(0.7 * len(lines), rise - MIN_MEDIA * len(lines) - fixed) / sum(reading)
        reading = [max(0.7, r * k) for r in reading]
        budget = max(MIN_MEDIA * len(lines), rise - sum(reading) - fixed)
    per_line = 2 if speed >= 1.4 else 1
    slope = min(0.9, 0.75 * speed)
    weights = [1.0 - slope * i / max(len(lines) - 1, 1) for i in range(len(lines))]
    rise_start, rise_from = sum(s["seconds"] for s in seq), len(seq)
    for i, line in enumerate(lines):
        share = budget * weights[i] / sum(weights)
        if line and on["kinetic"] and i % 3 == 1 and not line.rstrip().endswith("?"):
            # una de cada tres frases va encima de la imagen, no en tarjeta
            add({"kind": "overlay", "media": (i + 1) % len(media), "variant": variants[i % len(variants)],
                 "text": line, "seconds": reading[i] + share, "motion": "push", "kinetic": True}, "rise")
        else:
            if line:
                card(line, _style_for(line, i), reading[i], "rise")
            for j in range(per_line):
                n = i * per_line + j
                shot(n + 1, variants[n % len(variants)], share / per_line, "rise", rng.choice(motions), pick_tr(0.4))
        if on["split"] and len(media) >= 3 and i == len(lines) // 3:
            add({"kind": "split", "medias": [k % len(media) for k in (1, 2, 3)],
                 "variant": first, "seconds": 0.8, "transition": "zoom"}, "rise")
        if on["double"] and len(media) >= 2 and i == (2 * len(lines)) // 3:
            add({"kind": "double", "media": 0, "media2": 1, "variant": first, "seconds": 0.9,
                 "motion": "push", "transition": pick_tr(0.5)}, "rise")
        if every and (i + 1) % every == 0:
            color("red" if i % 2 == 0 else "white", flash_s, "rise")
    rise_media = [s for s in seq[rise_from:] if s["kind"] == "media"]
    hold = lambda s: (0.0 if media[s["media"]].get("type") != "video" else  # noqa: E731
                      AUDIO_HOLD if s["audio"] else RAMP_HOLD if s["motion"] == "ramp" else 0.0)
    need = {id(s): hold(s) for s in rise_media if hold(s)}
    if need:   # el tiempo que ganan los videos con audio y las rampas lo ceden los demas, hasta 0.2 s cada uno
        held = [s for s in rise_media if id(s) in need]
        quiet = [s for s in rise_media if id(s) not in need]
        extra = sum(max(0.0, need[id(s)] - s["seconds"]) for s in held)
        spare = sum(max(0.0, s["seconds"] - 0.2) for s in quiet)
        for s in quiet:
            s["seconds"] -= max(0.0, s["seconds"] - 0.2) * (min(1.0, extra / spare) if spare else 0.0)
        for s in held:
            s["seconds"] = max(s["seconds"], need[id(s)])
            used = s["seconds"] * (1.24 if s["motion"] == "ramp" else 1.0)   # la rampa consume 1.24x de video
            s["offset"] = round(min(s["offset"], max(span(media[s["media"]]) - used, 0)), 2)
    snapped = _snap_cuts([s["seconds"] for s in seq[rise_from:]], rise_start, list(beats))
    for s, d in zip(seq[rise_from:], snapped):
        s["seconds"] = round(d, 3)

    # 3. Climax: palabras sueltas (con impact frame antes), primeros planos y destellos.
    words = [w for w in cards.get("climax") or [] if str(w).strip()] or DEFAULT_CARDS["climax"]
    photos = [k for k, m in enumerate(media) if m.get("type") != "video"] or list(range(len(media)))
    climax = max(climax_end - sum(s["seconds"] for s in seq), 1.0)   # un guion muy largo no se come el climax
    t, k = 0.0, 0
    hi, lo = max(3, round(6 / speed)), max(2, round(3 / speed))
    while t < climax - 1e-6:
        d = min(max(lo, round(hi - (hi - lo) * t / climax)) / FPS, climax - t)
        step = k % 4
        if step == 0:
            if on["impact"] and (k // 4) % 2 == 0 and climax - t - d > 3 / FPS:
                add({"kind": "impact", "media": rng.choice(photos), "seconds": 3 / FPS}, "climax")
                t += 3 / FPS
            card(words[(k // 4) % len(words)], "word", d, "climax", kinetic=False)["motion"] = "punch"
        elif step == 2 and rng.random() < min(1.0, flashes):
            color(rng.choice(("white", "red")), d, "climax")
        elif step == 3:
            shot(k, sketch, d, "climax", "punch")
        else:
            dark = [v for v in variants if v in ("negative", "red", "hard")] or variants
            shot(rng.randrange(len(media)), rng.choice(dark), d, "climax",
                 "shake" if on["shake"] else "punch", pick_tr(0.3))
        t, k = t + d, k + 1

    # 4. Quiebre: papel en blanco y la musica muda (termina en la caida, si se detecto).
    color("white", max(break_end - sum(s["seconds"] for s in seq), 0.8), "break", tag="break")

    # 5. Cierre: el boceto que se aleja, la frase final, la firma y (con loop) la pregunta inicial.
    final = [l for l in cards.get("final") or [] if str(l).strip()]
    tail = LOOP_CARD if on["loop"] else 0.0
    rest = max(T - sum(s["seconds"] for s in seq) - tail, 3.0)
    shot(0, sketch, rest * 0.22, "final", "pull")
    for line in final:
        card(line, "invert", rest * 0.56 / max(len(final), 1), "final")
    card(cards.get("end") or "", "caption", max(0.8, T - sum(s["seconds"] for s in seq) - tail), "final", kinetic=False)
    if on["loop"]:
        card(cards.get("opening") or DEFAULT_CARDS["opening"], "center", tail, "final", kinetic=False)
    return seq


# ---------------------------------------------------------------- planos
def build_shots(project: dict, sequence: list[dict]):
    """Planos listos para el render a partir de la secuencia (automatica o retocada)."""
    media, style = project["media"], project["style"]
    on = {k: bool(style.get(k, True)) for k in ("grain", "grade", "bloom")}
    raw: dict = {}
    done: dict = {}

    def still(i: int, kind: str) -> Image.Image:
        key = (i % len(media), kind)
        if key not in raw:
            raw[key] = variant(_still_of(media[key[0]]), kind)
        return raw[key]

    def finish(key, img: Image.Image, act: str, glow: bool = True) -> Image.Image:
        """Color por acto y resplandor, una sola vez por imagen fija."""
        k = (key, act, glow)
        if k not in done:
            out = grade(img, act) if on["grade"] else img
            done[k] = bloom(out) if on["bloom"] and glow else out
        return done[k]

    shots: list[Shot] = []
    t, prev = 0.0, 0
    for n, spec in enumerate(sequence):
        t += float(spec.get("seconds", 0))
        frames = round(t * FPS) - prev
        if frames <= 0:
            continue
        prev += frames
        kind, motion, act = spec.get("kind"), spec.get("motion", "hold"), spec.get("act", "")
        transition, vkind = spec.get("transition", "cut"), spec.get("variant", "base")
        i = int(spec.get("media", 0)) % len(media) if media else 0
        common = {"motion": motion, "act": act, "kinetic": bool(spec.get("kinetic"))}
        if kind == "card":
            shot = Shot(frames, text_card(str(spec.get("text", "")), spec.get("style", "center")), grain=False,
                        red=spec.get("style") == "red", role="word" if spec.get("style") == "word" else "card",
                        **common)
        elif kind == "color":
            name = spec.get("color", "black")
            shot = Shot(frames, Image.new("RGB", (W, H), COLORS.get(name, (0, 0, 0))), grain=False,
                        red=name == "red", tag=spec.get("tag", ""), role="color", **common)
        elif kind == "double":
            j = int(spec.get("media2", i + 1)) % len(media)
            base = finish(("d", i, j, vkind), double_image(still(i, vkind), still(j, vkind)), act)
            shot = Shot(frames, base, grain=on["grain"], role="media", **common)
        elif kind == "split":
            ids = [int(x) % len(media) for x in spec.get("medias") or [i]]
            base = finish(("s", tuple(ids), vkind), split_image([still(x, vkind) for x in ids]), act, glow=False)
            shot = Shot(frames, base, grain=on["grain"], role="media", **common)
        elif kind == "impact":
            shot = Shot(frames, impact_image(still(i, "base"), seed=n), grain=False, role="impact", **common)
        else:
            m = media[i]
            if m.get("type") == "video":
                start = float(m.get("in", 0.0)) + float(spec.get("offset", 0.0))
                focus, zoom = tuple(m.get("focus", (0.5, 0.5))), m.get("zoom", 1.0)
                clip = {"file": m["file"], "start": start, "variant": vkind, "focus": focus, "zoom": zoom,
                        "act": act, "grade": on["grade"], "bloom": on["bloom"], "ramp": motion == "ramp"}
                first = _finish_frame(variant(next(iter_video_frames(m["file"], start, 1, focus, zoom)), vkind), clip)
                shot = Shot(frames, first, grain=on["grain"], red=vkind == "red", clip=clip, role="media", **common)
                if spec.get("audio") and frames / FPS >= MIN_CLIP_AUDIO and motion != "ramp":
                    shot.audio = (m["file"], start)
            else:
                shot = Shot(frames, finish(("m", i, vkind), still(i, vkind), act), grain=on["grain"],
                            red=vkind == "red", role="media", **common)
            if kind == "overlay":   # el texto va encima; si el medio es un video, sigue corriendo debajo
                shot.role, shot.text_layer = "overlay", overlay_layer(str(spec.get("text", "")))
        if transition == "flash" and shot.frames > FLASH_FRAMES + 1:
            shot.frames -= FLASH_FRAMES
            if shot.audio:
                shot.audio = (shot.audio[0], shot.audio[1] + FLASH_FRAMES / FPS)
            shots.append(Shot(FLASH_FRAMES, Image.new("RGB", (W, H), PAPER), grain=False, role="color", act=act))
        elif transition in TRANSITION_FRAMES:
            shot.transition = transition
        shots.append(shot)

    shots = limit_flashes(shots)
    start, brk = 0, None
    for s in shots:   # el quiebre se mide despues del limitador, que puede atrasar su corte
        if s.tag == "break":
            brk = (start / FPS, (start + s.frames) / FPS)
            break
        start += s.frames
    return shots, {"break": brk, "end": sum(s.frames for s in shots) / FPS}


def _finish_frame(img: Image.Image, clip: dict) -> Image.Image:
    out = grade(img, clip.get("act", "")) if clip.get("grade") else img
    return bloom(out) if clip.get("bloom") else out


def plan(script: dict, images_dir, seconds: float, beats=(), seed: int = 7):
    """Atajo del arco automatico completo: (planos, marcas)."""
    project = normalize_project(script, images_dir, seconds)
    return build_shots(project, auto_sequence(project, beats, seed))


def limit_flashes(shots: list[Shot]) -> list[Shot]:
    """Como mucho MAX_FLASHES_PER_SECOND destellos en cualquier segundo. Si un corte haria el
    cuarto, se atrasa hasta que se libere el segundo; si el plano es tan corto que no llega,
    se funde con el anterior. La duracion total no cambia."""
    lumas: dict[int, float] = {}

    def luma(img: Image.Image) -> float:
        if id(img) not in lumas:
            lumas[id(img)] = float(np.asarray(img.convert("L").resize((54, 96))).mean())
        return lumas[id(img)]

    out: list[Shot] = []
    recent: deque = deque()
    frame = 0
    for shot in shots:
        shot = replace(shot)
        if out:
            prev = out[-1]
            jump = abs(luma(shot.image) - luma(prev.image))
            if jump >= FLASH_DELTA or shot.red or prev.red:
                while recent and frame - recent[0] >= FPS:
                    recent.popleft()
                if len(recent) >= MAX_FLASHES_PER_SECOND:
                    wait = recent[0] + FPS - frame
                    if shot.frames - wait < 2:
                        prev.frames += shot.frames
                        frame += shot.frames
                        continue
                    prev.frames += wait
                    shot.frames -= wait
                    if shot.clip:
                        shot.clip = dict(shot.clip, start=shot.clip["start"] + wait / FPS)
                    if shot.audio:
                        shot.audio = (shot.audio[0], shot.audio[1] + wait / FPS)
                    frame += wait
                    recent.popleft()
                recent.append(frame)
        out.append(shot)
        frame += shot.frames
    return out


# ---------------------------------------------------------------- IA: tarjetas
CARDS_PROMPT = """You write the on-screen text cards of a 40-second vertical video with NO narration voice.
Style: an inner monologue at a breaking point, like the final episodes of Neon Genesis Evangelion:
short lines, questions, repetition, tension that breaks at the end.
Subject: <<TOPIC>>
Perspective: <<WHO>>
Language of the cards: <<LANGUAGE>>

Rules:
- Every fact (date, place, number, event, name) must be documented history. Never invent events,
  numbers or quotes.
- Use a quote only if it is real and attributable to that person; otherwise write a reflective line.
- "lines": 7 to 10 cards, each 2 to 8 words. Mix 2 or 3 facts (date, place, number), short
  statements and 2 or 3 questions. The tension grows toward the end.
- "climax": exactly 3 single words, uppercase, that break the tension (for example WHO / AM / I).
- "final": 1 or 2 cards with the release: a real quote if one exists, or the documented outcome.
- "end": who said the quote and when, or the figure's name and the year.
- "opening": one short question that opens the video.

Return ONLY this JSON:
{"opening": "...", "lines": ["..."], "climax": ["...", "...", "..."], "final": ["..."], "end": "..."}"""
PERSPECTIVES = {"character": "first person: the historical figure speaks to themself",
                "narrator": "third person: a narrator speaks about the figure"}
LANGUAGES = {"en": "English", "es": "Spanish"}


def parse_cards(raw) -> dict:
    """Tarjetas desde la respuesta del modelo (tolera ```json, comas de mas y texto alrededor)."""
    text = str(raw or "")
    body = text[text.find("{"): text.rfind("}") + 1] if "{" in text else "{}"
    try:
        data = json.loads(body)
    except ValueError:
        try:
            from json_repair import repair_json
            data = json.loads(repair_json(body))
        except Exception:
            data = {}
    cards = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_CARDS.items()}
    for key in ("opening", "end"):
        if isinstance(data.get(key), str):
            cards[key] = data[key].strip()
    for key in ("lines", "climax", "final"):
        if isinstance(data.get(key), list):
            cards[key] = [str(x).strip() for x in data[key] if str(x).strip()]
    cards["climax"] = [w.upper() for w in cards["climax"]][:4] or list(DEFAULT_CARDS["climax"])
    return cards


def write_cards(topic: str, perspective: str = "character", language: str = "en", *,
                generate_fn: Optional[Callable[[str], str]] = None, check: bool = True, log=print) -> dict:
    """La IA propone las tarjetas desde un tema; con check=True pasan por script_fact_check
    (el mismo verificador de los guiones narrados), que corrige lo falso o inventado."""
    if generate_fn is None:
        from ai_factory import AIFactory
        client = AIFactory.get_instance().get_llm_client()
        generate_fn = lambda prompt: client._generate(prompt, max_tokens=1500)  # noqa: E731
    prompt = (CARDS_PROMPT.replace("<<TOPIC>>", topic.strip())
              .replace("<<WHO>>", PERSPECTIVES.get(perspective, PERSPECTIVES["character"]))
              .replace("<<LANGUAGE>>", LANGUAGES.get(language, "English")))
    log("IA: escribiendo las tarjetas...")
    cards = parse_cards(generate_fn(prompt))
    if not cards["lines"]:
        raise RuntimeError("La IA no devolvio tarjetas utiles; prueba de nuevo o escribelas a mano.")
    if not check:
        return cards
    from script_fact_check import fact_check_scenes, scene_text
    texts = [cards["opening"]] + cards["lines"] + cards["final"]
    log("Verificando hechos (puede tardar un minuto)...")
    fixed, report = fact_check_scenes(texts, topic, language=language, log=log)
    fixed = [scene_text(s) for s in fixed]
    if len(fixed) == len(texts):
        n = len(cards["lines"])
        cards["opening"], cards["lines"], cards["final"] = fixed[0], fixed[1:1 + n], fixed[1 + n:]
    cards["fact_check"] = {"status": report.get("status"),
                           "remaining": [{"quote": f.get("quote"), "verdict": f.get("verdict"),
                                          "correction": f.get("correction")} for f in report.get("remaining", [])]}
    return cards


# ---------------------------------------------------------------- sonido
def _noise_band(n: int, lo: float, hi: float, rng) -> np.ndarray:
    from scipy.signal import butter, lfilter
    b, a = butter(2, [lo / (SR / 2), hi / (SR / 2)], "band")
    return lfilter(b, a, rng.normal(0, 1, n)).astype(np.float32)


def _sweep(n: int, f0: float, f1: float) -> np.ndarray:
    f = np.linspace(f0, f1, n, dtype=np.float64)
    return np.sin(2 * np.pi * np.cumsum(f) / SR).astype(np.float32)


def sfx_track(shots: list[Shot], T: float, seed: int = 5) -> np.ndarray:
    """Diseno sonoro sintetizado (sin derechos): whoosh que termina en los cortes marcados, golpe
    grave en las palabras del climax y los impact frames, subida antes del quiebre, pitido de oido
    en el silencio y boom cuando arranca la catarsis."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int((T + 3) * SR), dtype=np.float32)

    def put(sig, at):
        i0 = int(at * SR)
        if i0 < 0:
            sig, i0 = sig[-i0:], 0
        end = min(len(out), i0 + len(sig))
        if end > i0:
            out[i0:end] += sig[: end - i0]

    n = int(0.35 * SR)
    tt = np.linspace(0, 1, n, dtype=np.float32)
    whoosh = _noise_band(n, 400, 4000, rng) * (tt ** 2) * np.where(tt > 0.85, (1 - tt) / 0.15, 1) * 0.5
    n = int(0.45 * SR)
    tt = np.arange(n, dtype=np.float32) / SR
    hit = _sweep(n, 62, 32) * np.exp(-tt * 9) * 1.0
    hit[: int(0.006 * SR)] += _noise_band(int(0.006 * SR), 1500, 8000, rng) * 0.5
    t, prev = 0.0, None
    for s in shots:
        d = s.frames / FPS
        if s.tag == "break":
            n = int(1.6 * SR)
            tt = np.linspace(0, 1, n, dtype=np.float32)
            put((_noise_band(n, 300, 6000, rng) * 0.4 + _sweep(n, 180, 1400) * 0.25) * tt ** 2.5, t - 1.6)
            n = int(d * SR)
            env = np.minimum(1, np.minimum(np.arange(n) / (0.15 * SR), (n - np.arange(n)) / (0.25 * SR)))
            put(np.sin(2 * np.pi * 6200 * np.arange(n) / SR).astype(np.float32) * 0.05 * env.astype(np.float32), t)
            n = int(2.4 * SR)
            tt = np.arange(n, dtype=np.float32) / SR
            put(_sweep(n, 46, 26) * np.exp(-tt * 1.8) * 1.1 + _noise_band(n, 30, 200, rng) * np.exp(-tt * 3) * 0.4,
                t + d)
        elif s.role in ("word", "impact") and prev != "impact":
            put(hit, t)
        elif s.transition in ("glitch", "burn", "zoom") or (s.role in ("media", "overlay") and s.act == "rise"
                                                            and d >= 0.35 and rng.random() < 0.5):
            put(whoosh, t - 0.3)
        prev = s.role
        t += d
    peak = float(np.max(np.abs(out))) or 1.0
    return out * (0.8 / peak)


def _audio_graph(shots: list[Shot], music, break_span, T: float, first_index: int, sfx_path=None, loop=False,
                 music_start: float = 0.0):
    """Entradas y filtro de audio: la musica baja (sidechain) cuando suena el audio de un video y
    el diseno sonoro se suma encima; un limitador evita que sature."""
    inputs, chains, labels, idx, t = [], [], [], first_index, 0.0
    for s in shots:
        if s.audio and media_info(str(s.audio[0]))["audio"]:
            inputs += ["-ss", f"{s.audio[1]:.3f}", "-t", f"{s.frames / FPS:.3f}", "-i", str(s.audio[0])]
            ms = int(round(t * 1000))
            chains.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms}[c{idx}]")
            labels.append(f"[c{idx}]")
            idx += 1
        t += s.frames / FPS
    if labels:   # relleno hasta el final: sidechaincompress corta la musica cuando se acaba su control
        mix = (f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest"
               if len(labels) > 1 else f"{labels[0]}anull")
        chains.append(f"{mix},apad=whole_dur={T:.3f}[clips]")
    if music:
        inputs += (["-ss", f"{music_start:.3f}"] if music_start else []) + ["-i", str(music)]
        mute = (f",volume=enable='between(t,{break_span[0]:.2f},{break_span[1]:.2f})':volume=0"
                if break_span else "")
        chains.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo{mute}[mus]")
        idx += 1
    if sfx_path:
        inputs += ["-i", str(sfx_path)]
        chains.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[sfx]")
    bed = None
    if labels and music:
        chains += ["[clips]asplit=2[sc][cl]",
                   "[mus][sc]sidechaincompress=threshold=0.02:ratio=12:attack=10:release=400[duck]",
                   "[duck][cl]amix=inputs=2:normalize=0:duration=longest[bed]"]
        bed = "[bed]"
    elif labels or music:
        bed = "[clips]" if labels else "[mus]"
    if bed and sfx_path:
        chains.append(f"{bed}[sfx]amix=inputs=2:normalize=0:duration=longest[mix]")
    elif bed or sfx_path:
        chains.append(f"{bed or '[sfx]'}anull[mix]")
    else:
        return [], None
    fade = 0.4 if loop else 1.5
    chains.append(f"[mix]alimiter=limit=0.95,afade=t=in:st=0:d=0.05,"
                  f"afade=t=out:st={max(T - fade, 0):.2f}:d={fade}[aout]")
    return inputs, ";".join(chains)


# ---------------------------------------------------------------- render
def _burn_frames() -> list[np.ndarray]:
    """Cuadros del film burn de transition_overlays/ (vacio si no esta)."""
    folder = Path(__file__).resolve().parent / "transition_overlays"
    clips = sorted(p for p in folder.glob("*") if p.suffix.lower() in VIDEO_EXT) if folder.is_dir() else []
    if not clips:
        return []
    return [np.asarray(f, dtype=np.float32) for f in iter_video_frames(clips[0], 0.0, TRANSITION_FRAMES["burn"])]


def _zoomed(img: Image.Image, scale: float, dx: int = 0, dy: int = 0) -> Image.Image:
    if abs(scale - 1.0) < 1e-3 and not (dx or dy):
        return img
    w, h = round(img.width / scale), round(img.height / scale)
    left = int(min(max((img.width - w) // 2 + dx, 0), img.width - w))
    top = int(min(max((img.height - h) // 2 + dy, 0), img.height - h))
    return img.crop((left, top, left + w, top + h)).resize(img.size, Image.BILINEAR)


def _moved(img: Image.Image, motion: str, i: int, n: int, rng) -> Image.Image:
    cut = 0.6 * max(n - 1, 1)   # rampa: se arrastra el 60 % del plano y despues se dispara
    ramp = 1.0 + 0.02 * i / cut if i < cut else 1.02 + 0.10 * (i - cut) / max(n - 1 - cut, 1)
    scale = {"push": 1.0 + 0.06 * i / max(n - 1, 1), "pull": 1.06 - 0.06 * i / max(n - 1, 1),
             "punch": 1.12 if i < 2 else (1.05 if i < 4 else 1.0), "shake": 1.05, "ramp": ramp}.get(motion, 1.0)
    dx, dy = (rng.integers(-16, 17, 2) if motion == "shake" else (0, 0))
    return _zoomed(img, scale, int(dx), int(dy))


def _kinetic(img: Image.Image, i: int, echo: Optional[Image.Image]) -> Image.Image:
    """Texto que entra: agrandado y desenfocado, se asienta y deja una estela del cuadro anterior."""
    ease = 1 - (1 - min(1.0, i / (KINETIC_FRAMES - 1))) ** 3
    out = _zoomed(img, 1.25 - 0.25 * ease)
    radius = 6 * (1 - ease)
    if radius > 0.3:
        out = out.filter(ImageFilter.GaussianBlur(radius))
    return Image.blend(out, echo, 0.3) if echo is not None else out


def _zoom_blur(arr: np.ndarray) -> np.ndarray:
    """Desenfoque de zoom: el golpe se ve en movimiento."""
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    acc = arr.copy()
    for s in (1.03, 1.06, 1.09):
        acc += np.asarray(_zoomed(img, s), dtype=np.float32)
    return acc / 4


def render(shots: list[Shot], out: Path, music=None, break_span=None, *, vignette: bool = True,
           preview: bool = False, progress: Optional[Callable[[int, int], None]] = None, seed: int = 11,
           sfx: bool = False, loop: bool = False, guides: bool = False, music_start: float = 0.0) -> Path:
    """Cuadros de Python -> FFmpeg por tuberia (un solo proceso), con musica, audio de los videos y
    diseno sonoro. preview=True: 15 fps y 540x960; guides=True marca las zonas que tapa Shorts."""
    total = sum(s.frames for s in shots)
    T, step = total / FPS, (2 if preview else 1)
    out = Path(out)
    sfx_path = None
    if sfx:
        from scipy.io import wavfile
        sfx_path = out.with_suffix(".sfx.wav")
        wavfile.write(sfx_path, SR, (sfx_track(shots, T) * 32767).astype(np.int16))
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS // step), "-i", "-"]
    audio_inputs, graph = _audio_graph(shots, music, break_span, T, first_index=1, sfx_path=sfx_path, loop=loop,
                                       music_start=music_start)
    cmd += audio_inputs + ["-map", "0:v"]
    if graph:
        cmd += ["-filter_complex", graph, "-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    if preview:
        cmd += ["-vf", "scale=540:960"]
    cmd += ["-t", f"{T:.3f}", "-c:v", "libx264", "-preset", "veryfast" if preview else "medium",
            "-crf", "26" if preview else "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]

    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 12, (6, H // 2, W // 2)).astype(np.float32)
    grain = [np.repeat(np.repeat(n, 2, 0), 2, 1)[..., None] for n in noise]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    shade = (1.0 - 0.42 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2)[..., None]
    guide = _guide_mask() if guides else None
    burn = _burn_frames() if any(s.transition == "burn" for s in shots) else []
    glitch = None
    if any(s.transition == "glitch" for s in shots):
        from glitch_transitions import GlitchIntensity, GlitchTransitionEngine, GlitchTransitionType
        glitch = (GlitchTransitionEngine((W, H)), GlitchIntensity.EXTREME,
                  [GlitchTransitionType.RGB_SPLIT, GlitchTransitionType.BLOCK_GLITCH,
                   GlitchTransitionType.DIGITAL_GLITCH, GlitchTransitionType.SCAN_LINES])

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frame = 0
    try:
        for shot in shots:
            clip = None
            if shot.clip:
                c = shot.clip
                clip = iter_clip_frames(c["file"], c["start"], shot.frames, c["focus"], c["zoom"], c.get("ramp", False))
            kind = glitch[2][rng.integers(len(glitch[2]))] if glitch and shot.transition == "glitch" else None
            echo = layer_echo = None
            for i in range(shot.frames):
                raw = next(clip) if clip else None   # el video avanza aunque la vista previa salte cuadros
                n = frame + i
                if n % step:
                    continue
                src = _finish_frame(variant(raw, shot.clip["variant"]), shot.clip) if clip else shot.image
                if shot.kinetic and shot.text_layer is None and i < KINETIC_FRAMES:
                    src = echo = _kinetic(src, i, echo)
                motion = "punch" if shot.transition == "zoom" and i < TRANSITION_FRAMES["zoom"] else shot.motion
                arr = np.asarray(_moved(src, motion, i, shot.frames, rng), dtype=np.float32)
                if (motion == "punch" or shot.role == "word") and i < 2:
                    arr = _zoom_blur(arr)
                if shot.text_layer is not None:   # texto blanco con halo encima de la imagen o el video
                    layer = shot.text_layer
                    if shot.kinetic and i < KINETIC_FRAMES:
                        layer = layer_echo = _kinetic(layer, i, layer_echo)
                    rgba = np.asarray(layer, dtype=np.float32)
                    a = rgba[..., 3:4] / 255.0
                    arr = arr * (1.0 - a) + rgba[..., :3] * a
                if kind is not None and i < TRANSITION_FRAMES["glitch"]:
                    progress_i = 0.5 + 0.5 * i / TRANSITION_FRAMES["glitch"]
                    arr = glitch[0].apply_glitch_transition(np.clip(arr, 0, 255).astype(np.uint8), progress_i, kind,
                                                            glitch[1]).astype(np.float32)
                if shot.transition == "burn" and i < len(burn):
                    arr = 255.0 - (255.0 - arr) * (255.0 - burn[i]) / 255.0   # mezcla "screen"
                if shot.grain:
                    arr = (arr * shade if vignette else arr) + grain[rng.integers(len(grain))]
                if not loop and n >= total - FADE_OUT_FRAMES:
                    arr = arr * ((total - n) / FADE_OUT_FRAMES)
                if guide is not None:
                    arr = arr * (1 - guide) + guide * np.asarray((255, 0, 0), dtype=np.float32)
                proc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
                if progress and n % 15 == 0:
                    progress(n, total)
            frame += shot.frames
    finally:
        proc.stdin.close()
        code = proc.wait()
        if sfx_path is not None:
            sfx_path.unlink(missing_ok=True)
        if code != 0:
            raise RuntimeError(f"FFmpeg fallo al escribir {out}")
    if progress:
        progress(total, total)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Formato Catarsis: Short vertical de impacto, sin voz.")
    ap.add_argument("project", help="proyecto o guion de tarjetas (JSON)")
    ap.add_argument("--images", help="carpeta de los medios con ruta relativa (por defecto, la del JSON)")
    ap.add_argument("--music", help="pista de musica apta para YouTube (reemplaza la del proyecto)")
    ap.add_argument("--music-start", help="segundo de la pista desde el que suena, o 'auto' (su caida en el quiebre)")
    ap.add_argument("--seconds", type=float, help="duracion total (por defecto la del proyecto, o 40)")
    ap.add_argument("--auto", action="store_true", help="rearmar la secuencia aunque el proyecto traiga una")
    ap.add_argument("--preview", action="store_true", help="vista previa rapida (540x960, 15 fps)")
    ap.add_argument("--guides", action="store_true", help="marcar las zonas que tapa Shorts (vista previa)")
    ap.add_argument("--out", default="catarsis.mp4")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    path = Path(a.project)
    project = normalize_project(json.loads(path.read_text(encoding="utf-8")), a.images or path.parent, a.seconds)
    style, music = project["style"], a.music or project.get("music")
    start = a.music_start if a.music_start is not None else project.get("music_start", 0.0)
    if music and str(start).lower() == "auto":
        start = find_music_start(music, project["seconds"])[0]
    start = float(start or 0.0)
    beats, drop = music_analysis(music, project["seconds"], start) if music else ([], None)
    sequence = project.get("sequence") if project.get("sequence") and not a.auto else None
    sequence = sequence or auto_sequence(project, beats, seed=a.seed, drop=drop)
    shots, marks = build_shots(project, sequence)
    render(shots, Path(a.out), music=music, break_span=marks["break"], vignette=style.get("vignette", True),
           preview=a.preview, sfx=style.get("sfx", True), loop=style.get("loop", True), guides=a.guides,
           music_start=start)
    caida = f", caida en {drop:.1f} s" if drop else ""
    print(f"[catarsis] listo: {a.out} ({marks['end']:.1f} s, {len(shots)} planos, {len(beats)} golpes{caida})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
