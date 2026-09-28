# -*- coding: utf-8 -*-
"""Formato "Catarsis": Short vertical de impacto, sin voz.

Tarjetas de texto, imagenes, videos y musica con cortes secos al ritmo. La tension sube
(preguntas, cortes cada vez mas rapidos, destellos) y se suelta de golpe (silencio, una imagen
quieta, la frase final). Es el lenguaje de los monologos finales de Evangelion, hecho con
material propio: nada de clips, musica ni tipografia de la serie (Content ID los reclama).

Un proyecto (JSON) tiene: tarjetas, medios (imagenes y videos, con o sin su audio), musica,
estilo y la secuencia de planos. auto_sequence() arma el arco; la pestana Catarsis de la app
deja retocar cada plano (orden, duracion, variante, transicion, movimiento) antes del render.
Los guiones viejos (images/opening/lines...) se siguen leyendo.

    .venv\\Scripts\\python.exe catharsis_editor.py examples\\catharsis_oppenheimer.json --images carpeta --music pista.mp3

Seguridad: como mucho 3 destellos por segundo (WCAG 2.3.1 / prueba de Harding). Los cambios
bruscos de luz de a 2 cuadros pueden provocar crisis en personas fotosensibles.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import textwrap
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1080, 1920, 30
PAPER, INK, RED = (242, 240, 234), (8, 8, 8), (186, 14, 22)
FONT_CANDIDATES = (
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
)
CONDENSE = 0.72  # serif pesada y angosta, como las tarjetas de Evangelion

# Arco, como fraccion de la duracion total: apertura, subida, climax, quiebre y cierre.
OPENING, RISE_END, CLIMAX_END, BREAK_END = 0.12, 0.62, 0.80, 0.84
FLASH_FRAMES = 2
MAX_FLASHES_PER_SECOND = 3
FLASH_DELTA = 100          # salto de luminancia media (0-255) que cuenta como destello
FADE_OUT_FRAMES = 18
TRANSITION_FRAMES = {"glitch": 5, "burn": 14, "zoom": 4}
MIN_CLIP_AUDIO = 0.4       # segundos: un plano mas corto no lleva el audio de su video
AUDIO_HOLD = 1.2           # en la subida, un video con su audio dura al menos esto (si no, no se oye)

VARIANTS = ("color", "base", "negative", "red", "hard", "sketch")
TRANSITIONS = ("cut", "flash", "glitch", "burn", "zoom")
MOTIONS = ("hold", "push", "pull", "punch", "shake")
COLORS = {"black": (0, 0, 0), "white": PAPER, "red": RED}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
DEFAULT_STYLE = {"speed": 1.0, "flashes": 1.0, "variants": ["base", "negative", "sketch", "red", "hard"],
                 "transitions": ["glitch", "burn"], "grain": True, "vignette": True, "shake": True}
DEFAULT_CARDS = {"opening": "Who am I?", "lines": [], "climax": ["WHO", "AM", "I"], "final": [], "end": ""}


@dataclass
class Shot:
    frames: int
    image: Image.Image             # cuadro fijo; en un video, su primer cuadro
    motion: str = "hold"           # hold | push | pull | punch | shake
    grain: bool = True
    red: bool = False              # destello rojo saturado: cuenta siempre como destello
    tag: str = ""                  # "break": el quiebre, donde la musica se calla
    clip: Optional[dict] = None    # video: {"file", "start", "variant", "focus", "zoom"}
    transition: str = "cut"        # como entra el plano: cut | glitch | burn | zoom
    audio: Optional[tuple] = None  # (archivo, segundo) si suena el audio del video


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
    """Tarjeta 1080x1920. Estilos: center, left (grande arriba a la izquierda), invert
    (negro sobre papel), red, word (una palabra que llena el ancho) y caption (chica)."""
    bg, fg = (0, 0, 0), PAPER
    if style == "invert":
        bg, fg = PAPER, INK
    elif style == "red":
        bg = RED
    img = Image.new("RGB", (W, H), bg)
    if style == "word":
        layer = _fit_line(text.upper(), int(W * 0.9), 820, fg)
        img.paste(layer, ((W - layer.width) // 2, (H - layer.height) // 2), layer)
        return img
    width = 28 if style == "caption" else 14
    lines = [l for part in text.split("\n") for l in (textwrap.wrap(part, width) or [""])]
    size = {"caption": 72, "left": 220}.get(style, 210 if len(lines) <= 2 else 150)
    layers = [_fit_line(l, int(W * 0.86), size, fg) for l in lines]
    gap = size // 4
    y = (H - sum(l.height for l in layers) - gap * (len(layers) - 1)) // 2
    if style == "left":
        y = int(H * 0.30)
    for layer in layers:
        x = int(W * 0.08) if style == "left" else (W - layer.width) // 2
        img.paste(layer, (x, y), layer)
        y += layer.height + gap
    return img


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
        return ImageOps.autocontrast(img.convert("RGB"), cutoff=1)
    g = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    if kind == "negative":
        return ImageOps.invert(g).convert("RGB")
    if kind == "red":
        return ImageOps.colorize(g, black=(0, 0, 0), white=(255, 46, 40))
    if kind == "hard":
        return g.point(lambda v: 255 if v > 118 else 0).convert("RGB")
    if kind == "sketch":
        return _sketch(g)
    return g.convert("RGB")


def media_thumbnail(item: dict, size=(180, 320)) -> Image.Image:
    """Miniatura vertical de un medio del proyecto (para la lista de la pestana)."""
    focus, zoom = tuple(item.get("focus", (0.5, 0.5))), item.get("zoom", 1.0)
    if item.get("type") == "video":
        img = next(iter_video_frames(item["file"], float(item.get("in", 0.0)), 1, focus, zoom))
    else:
        img = frame_image(Path(item["file"]), focus, zoom)
    return img.resize(size, Image.BILINEAR)


# ---------------------------------------------------------------- ritmo
def music_beats(path, seconds: float) -> list[float]:
    """Golpes de la musica (librosa). Sin analisis, los cortes quedan a tiempo fijo."""
    try:
        import librosa
        y, sr = librosa.load(str(path), sr=22050, mono=True, duration=seconds + 1)
        _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        return [float(b) for b in beats]
    except Exception as exc:
        print(f"[catarsis] sin analisis de ritmo ({exc}); cortes a tiempo fijo")
        return []


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


def auto_sequence(project: dict, beats=(), seed: int = 7) -> list[dict]:
    """El arco automatico, como lista de planos editables (lo que muestra la pestana)."""
    rng = random.Random(seed)
    T, cards, style, media = float(project["seconds"]), project["cards"], project["style"], project["media"]
    if not media:
        raise ValueError("Agrega al menos una imagen o un video.")
    variants = [v for v in style.get("variants") or [] if v in VARIANTS] or ["base"]
    speed = min(2.0, max(0.5, float(style.get("speed", 1.0))))
    flashes = min(2.0, max(0.0, float(style.get("flashes", 1.0))))
    extra_tr = [t for t in style.get("transitions") or [] if t in ("glitch", "burn", "zoom")]
    motions = ["push", "hold", "punch"] + (["shake"] if style.get("shake", True) else [])
    first = "base" if "base" in variants else variants[0]
    sketch = "sketch" if "sketch" in variants else first
    seq: list[dict] = []

    def card(text, st, d):
        seq.append({"kind": "card", "text": text, "style": st, "seconds": d, "transition": "cut", "motion": "hold"})

    def span(m):
        return float(m.get("out") or media_info(m["file"])["duration"] or 0) - float(m.get("in", 0.0))

    def shot(i, kind, d, motion="hold", transition="cut"):
        m = media[i % len(media)]
        offset = round(rng.uniform(0, max(span(m) - d, 0)), 2) if m.get("type") == "video" else 0.0
        seq.append({"kind": "media", "media": i % len(media), "variant": kind, "seconds": d, "motion": motion,
                    "transition": transition, "offset": offset, "audio": bool(m.get("audio"))})

    def color(name, d, tag=""):
        seq.append({"kind": "color", "color": name, "seconds": d, "transition": "cut", "motion": "hold", "tag": tag})

    def pick_tr(p):
        return rng.choice(extra_tr) if extra_tr and rng.random() < p else "cut"

    # 1. Apertura: negro, la primera pregunta y una imagen que se acerca.
    t_open = OPENING * T
    card_d = max(1.6, t_open * 0.45)
    color("black", 0.5)
    card(cards.get("opening") or DEFAULT_CARDS["opening"], "center", card_d)
    shot(0, first, max(0.8, t_open - 0.5 - card_d), "push")

    # 2. Subida: frase, imagen(es) y cada tanto un destello; las imagenes duran cada vez menos.
    lines = [l for l in cards.get("lines") or [] if str(l).strip()]
    rise = (RISE_END - OPENING) * T
    every = max(1, round(3 / flashes)) if flashes > 0 else 0
    n_flash = len(lines) // every if every else 0
    flash_s = FLASH_FRAMES / FPS
    reading = [_reading_time(l) for l in lines]
    budget = rise - sum(reading) - n_flash * flash_s
    if lines and budget < 0.3 * len(lines):      # guion largo: tarjetas mas cortas, nunca bajo 0.7 s
        k = max(0.7 * len(lines), rise - 0.3 * len(lines) - n_flash * flash_s) / sum(reading)
        reading = [max(0.7, r * k) for r in reading]
        budget = max(0.3 * len(lines), rise - sum(reading) - n_flash * flash_s)
    per_line = 2 if speed >= 1.4 else 1
    slope = min(0.9, 0.75 * speed)
    weights = [1.0 - slope * i / max(len(lines) - 1, 1) for i in range(len(lines))]
    rise_start = sum(s["seconds"] for s in seq)
    rise_items_start = len(seq)
    for i, line in enumerate(lines):
        card(line, _style_for(line, i), reading[i])
        for j in range(per_line):
            n = i * per_line + j
            d = budget * weights[i] / sum(weights) / per_line
            shot(n + 1, variants[n % len(variants)], d, rng.choice(motions), pick_tr(0.4))
        if every and (i + 1) % every == 0:
            color("red" if i % 2 == 0 else "white", flash_s)
    rise_media = [s for s in seq[rise_items_start:] if s["kind"] == "media"]
    loud = [s for s in rise_media if s["audio"] and media[s["media"]].get("type") == "video"]
    if loud:   # el tiempo que ganan los videos con audio lo ceden los demas planos, hasta 0.2 s cada uno
        extra = sum(max(0.0, AUDIO_HOLD - s["seconds"]) for s in loud)
        quiet = [s for s in rise_media if s not in loud]
        spare = sum(max(0.0, s["seconds"] - 0.2) for s in quiet)
        for s in quiet:
            s["seconds"] -= max(0.0, s["seconds"] - 0.2) * (min(1.0, extra / spare) if spare else 0.0)
        for s in loud:
            s["seconds"] = max(s["seconds"], AUDIO_HOLD)
            s["offset"] = round(min(s["offset"], max(span(media[s["media"]]) - s["seconds"], 0)), 2)
    snapped = _snap_cuts([s["seconds"] for s in seq[rise_items_start:]], rise_start, list(beats))
    for s, d in zip(seq[rise_items_start:], snapped):
        s["seconds"] = round(d, 3)

    # 3. Climax: palabras sueltas, primeros planos y destellos; los cortes se aceleran.
    words = [w for w in cards.get("climax") or [] if str(w).strip()] or DEFAULT_CARDS["climax"]
    climax, t, k = (CLIMAX_END - RISE_END) * T, 0.0, 0
    hi, lo = max(3, round(6 / speed)), max(2, round(3 / speed))
    while t < climax - 1e-6:
        d = min(max(lo, round(hi - (hi - lo) * t / climax)) / FPS, climax - t)
        step = k % 4
        if step == 0:
            card(words[(k // 4) % len(words)], "word", d)
            seq[-1]["motion"] = "punch"
        elif step == 2 and rng.random() < min(1.0, flashes):
            color(rng.choice(("white", "red")), d)
        elif step == 3:
            shot(k, sketch, d, "punch")
        else:
            dark = [v for v in variants if v in ("negative", "red", "hard")] or variants
            shot(rng.randrange(len(media)), rng.choice(dark), d, "shake" if "shake" in motions else "punch",
                 pick_tr(0.3))
        t, k = t + d, k + 1

    # 4. Quiebre: papel en blanco y la musica muda.
    color("white", (BREAK_END - CLIMAX_END) * T, tag="break")

    # 5. Cierre: el boceto que se aleja, la frase final y la firma.
    final = [l for l in cards.get("final") or [] if str(l).strip()]
    rest = max(T - sum(s["seconds"] for s in seq), 3.0)
    shot(0, sketch, rest * 0.22, "pull")
    for line in final:
        card(line, "invert", rest * 0.56 / max(len(final), 1))
    card(cards.get("end") or "", "caption", max(0.8, T - sum(s["seconds"] for s in seq)))
    return seq


# ---------------------------------------------------------------- planos
def build_shots(project: dict, sequence: list[dict]):
    """Planos listos para el render a partir de la secuencia (automatica o retocada)."""
    media, style = project["media"], project["style"]
    grain_on = bool(style.get("grain", True))
    stills: dict = {}

    def still(i: int, kind: str) -> Image.Image:
        if (i, kind) not in stills:
            m = media[i]
            stills[(i, kind)] = variant(frame_image(Path(m["file"]), tuple(m.get("focus", (0.5, 0.5))),
                                                    m.get("zoom", 1.0)), kind)
        return stills[(i, kind)]

    shots: list[Shot] = []
    t, prev = 0.0, 0
    for spec in sequence:
        t += float(spec.get("seconds", 0))
        frames = round(t * FPS) - prev
        if frames <= 0:
            continue
        prev += frames
        kind, motion = spec.get("kind"), spec.get("motion", "hold")
        transition = spec.get("transition", "cut")
        if kind == "card":
            shot = Shot(frames, text_card(str(spec.get("text", "")), spec.get("style", "center")), motion, grain=False)
        elif kind == "color":
            name = spec.get("color", "black")
            shot = Shot(frames, Image.new("RGB", (W, H), COLORS.get(name, (0, 0, 0))), motion, grain=False,
                        red=name == "red", tag=spec.get("tag", ""))
        else:
            i = int(spec.get("media", 0)) % len(media)
            m, vkind = media[i], spec.get("variant", "base")
            focus, zoom = tuple(m.get("focus", (0.5, 0.5))), m.get("zoom", 1.0)
            if m.get("type") == "video":
                start = float(m.get("in", 0.0)) + float(spec.get("offset", 0.0))
                first_frame = variant(next(iter_video_frames(m["file"], start, 1, focus, zoom)), vkind)
                shot = Shot(frames, first_frame, motion, grain=grain_on, red=vkind == "red",
                            clip={"file": m["file"], "start": start, "variant": vkind, "focus": focus, "zoom": zoom})
                if spec.get("audio") and frames / FPS >= MIN_CLIP_AUDIO:
                    shot.audio = (m["file"], start)
            else:
                shot = Shot(frames, still(i, vkind), motion, grain=grain_on, red=vkind == "red")
        if transition == "flash" and shot.frames > FLASH_FRAMES + 1:
            shot.frames -= FLASH_FRAMES
            if shot.audio:
                shot.audio = (shot.audio[0], shot.audio[1] + FLASH_FRAMES / FPS)
            shots.append(Shot(FLASH_FRAMES, Image.new("RGB", (W, H), PAPER), grain=False))
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
        shot = Shot(shot.frames, shot.image, shot.motion, shot.grain, shot.red, shot.tag, shot.clip,
                    shot.transition, shot.audio)
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


# ---------------------------------------------------------------- render
def _moved(img: Image.Image, motion: str, i: int, n: int, rng) -> Image.Image:
    scale = {"push": 1.0 + 0.06 * i / max(n - 1, 1), "pull": 1.06 - 0.06 * i / max(n - 1, 1),
             "punch": 1.12 if i < 2 else (1.05 if i < 4 else 1.0), "shake": 1.05}.get(motion, 1.0)
    if scale == 1.0:
        return img
    w, h = round(W / scale), round(H / scale)
    dx, dy = (rng.integers(-16, 17, 2) if motion == "shake" else (0, 0))
    left = int(min(max((W - w) // 2 + dx, 0), W - w))
    top = int(min(max((H - h) // 2 + dy, 0), H - h))
    return img.crop((left, top, left + w, top + h)).resize((W, H), Image.BILINEAR)


def _burn_frames() -> list[np.ndarray]:
    """Cuadros del film burn de transition_overlays/ (vacio si no esta)."""
    folder = Path(__file__).resolve().parent / "transition_overlays"
    clips = sorted(p for p in folder.glob("*") if p.suffix.lower() in VIDEO_EXT) if folder.is_dir() else []
    if not clips:
        return []
    return [np.asarray(f, dtype=np.float32) for f in iter_video_frames(clips[0], 0.0, TRANSITION_FRAMES["burn"])]


def _audio_graph(shots: list[Shot], music, break_span, T: float, first_index: int):
    """Entradas y filtro de audio: la musica baja (sidechain) cuando suena el audio de un video."""
    inputs, chains, labels, idx, t = [], [], [], first_index, 0.0
    for s in shots:
        if s.audio and media_info(str(s.audio[0]))["audio"]:
            inputs += ["-ss", f"{s.audio[1]:.3f}", "-t", f"{s.frames / FPS:.3f}", "-i", str(s.audio[0])]
            ms = int(round(t * 1000))
            chains.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms}[c{idx}]")
            labels.append(f"[c{idx}]")
            idx += 1
        t += s.frames / FPS
    if labels:
        chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[clips]"
                      if len(labels) > 1 else f"{labels[0]}anull[clips]")
    if music:
        inputs += ["-i", str(music)]
        mute = (f",volume=enable='between(t,{break_span[0]:.2f},{break_span[1]:.2f})':volume=0"
                if break_span else "")
        chains.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo{mute}[mus]")
    if not labels and not music:
        return [], None
    if labels and music:
        chains += ["[clips]asplit=2[sc][cl]",
                   "[mus][sc]sidechaincompress=threshold=0.02:ratio=12:attack=10:release=400[duck]",
                   "[duck][cl]amix=inputs=2:normalize=0:duration=first[mix]"]
    else:
        chains.append(f"[{'clips' if labels else 'mus'}]anull[mix]")
    chains.append(f"[mix]afade=t=in:st=0:d=0.3,afade=t=out:st={max(T - 1.5, 0):.2f}:d=1.5[aout]")
    return inputs, ";".join(chains)


def render(shots: list[Shot], out: Path, music=None, break_span=None, *, vignette: bool = True,
           preview: bool = False, progress: Optional[Callable[[int, int], None]] = None,
           seed: int = 11) -> Path:
    """Cuadros de Python -> FFmpeg por tuberia (un solo proceso), con la musica y el audio de los
    videos. preview=True: 15 fps y 540x960, para mirar el ritmo rapido antes del render final."""
    total = sum(s.frames for s in shots)
    T, step = total / FPS, (2 if preview else 1)
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS // step), "-i", "-"]
    audio_inputs, graph = _audio_graph(shots, music, break_span, T, first_index=1)
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
                clip = iter_video_frames(c["file"], c["start"], shot.frames, c["focus"], c["zoom"])
            kind = glitch[2][rng.integers(len(glitch[2]))] if glitch and shot.transition == "glitch" else None
            for i in range(shot.frames):
                raw = next(clip) if clip else None   # el video avanza aunque la vista previa salte cuadros
                if (frame + i) % step:
                    continue
                src = variant(raw, shot.clip["variant"]) if clip else shot.image
                motion = "punch" if shot.transition == "zoom" and i < TRANSITION_FRAMES["zoom"] else shot.motion
                arr = np.asarray(_moved(src, motion, i, shot.frames, rng), dtype=np.float32)
                if kind is not None and i < TRANSITION_FRAMES["glitch"]:
                    progress_i = 0.5 + 0.5 * i / TRANSITION_FRAMES["glitch"]
                    arr = glitch[0].apply_glitch_transition(arr.astype(np.uint8), progress_i, kind,
                                                            glitch[1]).astype(np.float32)
                if shot.transition == "burn" and i < len(burn):
                    arr = 255.0 - (255.0 - arr) * (255.0 - burn[i]) / 255.0   # mezcla "screen"
                if shot.grain:
                    arr = (arr * shade if vignette else arr) + grain[rng.integers(len(grain))]
                n = frame + i
                if n >= total - FADE_OUT_FRAMES:
                    arr = arr * ((total - n) / FADE_OUT_FRAMES)
                proc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
                if progress and n % 15 == 0:
                    progress(n, total)
            frame += shot.frames
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"FFmpeg fallo al escribir {out}")
    if progress:
        progress(total, total)
    return Path(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Formato Catarsis: Short vertical de impacto, sin voz.")
    ap.add_argument("project", help="proyecto o guion de tarjetas (JSON)")
    ap.add_argument("--images", help="carpeta de los medios con ruta relativa (por defecto, la del JSON)")
    ap.add_argument("--music", help="pista de musica apta para YouTube (reemplaza la del proyecto)")
    ap.add_argument("--seconds", type=float, help="duracion total (por defecto la del proyecto, o 40)")
    ap.add_argument("--auto", action="store_true", help="rearmar la secuencia aunque el proyecto traiga una")
    ap.add_argument("--preview", action="store_true", help="vista previa rapida (540x960, 15 fps)")
    ap.add_argument("--out", default="catarsis.mp4")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    path = Path(a.project)
    project = normalize_project(json.loads(path.read_text(encoding="utf-8")), a.images or path.parent, a.seconds)
    music = a.music or project.get("music")
    beats = music_beats(music, project["seconds"]) if music else []
    sequence = project.get("sequence") if project.get("sequence") and not a.auto else None
    sequence = sequence or auto_sequence(project, beats, seed=a.seed)
    shots, marks = build_shots(project, sequence)
    render(shots, Path(a.out), music=music, break_span=marks["break"],
           vignette=project["style"].get("vignette", True), preview=a.preview)
    print(f"[catarsis] listo: {a.out} ({marks['end']:.1f} s, {len(shots)} planos, {len(beats)} golpes de musica)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
