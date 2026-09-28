# -*- coding: utf-8 -*-
"""Formato "Catarsis": Short vertical de impacto, sin voz.

Tarjetas de texto, imagenes y musica con cortes secos al ritmo. La tension sube (preguntas,
cortes cada vez mas rapidos, destellos) y se suelta de golpe (silencio, una imagen quieta,
la frase final). Es el lenguaje de los monologos finales de Evangelion, hecho con material
propio: nada de clips, musica ni tipografia de la serie (Content ID los reclama).

Entrada: un guion de tarjetas (JSON, ver examples/catharsis_oppenheimer.json), la carpeta con
las imagenes que nombra y una pista de musica apta para YouTube (CC BY / BY-SA o Biblioteca
de Audio). Salida: mp4 1080x1920 a 30 fps.

    .venv\\Scripts\\python.exe catharsis_editor.py examples\\catharsis_oppenheimer.json --images carpeta --music pista.mp3

Seguridad: como mucho 3 destellos por segundo (WCAG 2.3.1 / prueba de Harding). Los cambios
bruscos de luz de a 2 cuadros pueden provocar crisis en personas fotosensibles.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import textwrap
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

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


@dataclass
class Shot:
    frames: int
    image: Image.Image
    motion: str = "hold"   # hold | push | pull | punch | shake
    grain: bool = True
    red: bool = False      # destello rojo saturado: cuenta siempre como destello
    tag: str = ""          # "break": el quiebre, donde la musica se calla


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


# ---------------------------------------------------------------- imagenes
def frame_image(path: Path, focus=(0.5, 0.5), zoom: float = 1.0) -> Image.Image:
    """Recorte vertical 1080x1920 en blanco y negro, centrado en `focus` (0-1) con `zoom`."""
    im = Image.open(path).convert("L")
    scale = max(W / im.width, H / im.height) * max(zoom, 1.0)
    cw, ch = W / scale, H / scale   # zona de la foto que llena el cuadro
    left = min(max(focus[0] * im.width - cw / 2, 0), im.width - cw)
    top = min(max(focus[1] * im.height - ch / 2, 0), im.height - ch)
    return im.resize((W, H), Image.LANCZOS, box=(left, top, left + cw, top + ch))


def _sketch(gray: Image.Image) -> Image.Image:
    """Lapiz sobre papel: division de la imagen por su negativo desenfocado (color dodge)."""
    base = np.asarray(gray, dtype=np.float32)
    blur = np.asarray(ImageOps.invert(gray).filter(ImageFilter.GaussianBlur(10)), dtype=np.float32)
    lines = np.clip(base * 255.0 / np.maximum(255.0 - blur, 1.0), 0, 255)
    lines = np.where(lines > 232, 255.0, lines * 0.8)
    paper = np.asarray(PAPER, dtype=np.float32) / 255.0
    return Image.fromarray((lines[..., None] * paper).astype(np.uint8), "RGB")


def variant(gray: Image.Image, kind: str) -> Image.Image:
    """base (B/N contrastado), negative, red, hard (dos tonos) o sketch."""
    g = ImageOps.autocontrast(gray, cutoff=1)
    if kind == "negative":
        return ImageOps.invert(g).convert("RGB")
    if kind == "red":
        return ImageOps.colorize(g, black=(0, 0, 0), white=(255, 46, 40))
    if kind == "hard":
        return g.point(lambda v: 255 if v > 118 else 0).convert("RGB")
    if kind == "sketch":
        return _sketch(g)
    return g.convert("RGB")


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
    cuts = np.cumsum([start] + durations)
    for i in range(1, len(cuts) - 1):
        near = min(beats, key=lambda b: abs(b - cuts[i]))
        lo, hi = cuts[i - 1] + 2 / FPS, cuts[i + 1] - 2 / FPS
        if abs(near - cuts[i]) <= tol and lo < near < hi:
            cuts[i] = near
    return list(np.diff(cuts))


# ---------------------------------------------------------------- plan
def _reading_time(line: str) -> float:
    return min(2.4, max(0.8, 0.5 + 0.22 * len(line.split())))


def _style_for(line: str, i: int) -> str:
    if line.rstrip().endswith("?"):
        return "center"
    if any(ch.isdigit() for ch in line):
        return "left"
    return ("center", "invert")[i % 2]


def plan(script: dict, images_dir: Path, seconds: float, beats=(), seed: int = 7):
    """Lista de planos del arco y marcas de tiempo {rise, climax, break: (ini, fin), end}."""
    rng = random.Random(seed)
    T = float(seconds)
    pics = [frame_image(Path(images_dir) / p["file"], tuple(p.get("focus", (0.5, 0.5))), p.get("zoom", 1.0))
            for p in script.get("images", [])]
    if not pics:
        raise ValueError("El guion no nombra imagenes (campo 'images').")
    cache: dict = {}

    def pic(i: int, kind: str) -> Image.Image:
        key = (i % len(pics), kind)
        if key not in cache:
            cache[key] = variant(pics[key[0]], kind)
        return cache[key]

    black, white = Image.new("RGB", (W, H), (0, 0, 0)), Image.new("RGB", (W, H), PAPER)
    red_frame = Image.new("RGB", (W, H), RED)
    timeline: list[list] = []   # [segundos, imagen, movimiento, grano, rojo, marca]

    def add(d, img, motion="hold", grain=True, red=False, tag=""):
        timeline.append([d, img, motion, grain, red, tag])

    # 1. Apertura: negro, la primera pregunta y una imagen que se acerca.
    t_open = OPENING * T
    card = max(1.6, t_open * 0.45)
    add(0.5, black, grain=False)
    add(card, text_card(script.get("opening", "Who am I?")), grain=False)
    add(max(0.8, t_open - 0.5 - card), pic(0, "base"), "push")

    # 2. Subida: frase, imagen y cada tanto un destello; las imagenes duran cada vez menos.
    lines = script.get("lines", [])
    rise = (RISE_END - OPENING) * T
    reading = [_reading_time(l) for l in lines]
    flashes = len(lines) // 3
    budget = rise - sum(reading) - flashes * FLASH_FRAMES / FPS
    if budget < 0.3 * len(lines):          # guion largo: se acortan las tarjetas, nunca bajo 0.7 s
        k = max(0.7 * len(lines), rise - 0.3 * len(lines) - flashes * FLASH_FRAMES / FPS) / max(sum(reading), 1e-6)
        reading = [max(0.7, r * k) for r in reading]
        budget = max(0.3 * len(lines), rise - sum(reading) - flashes * FLASH_FRAMES / FPS)
    weights = [1.0 - 0.75 * i / max(len(lines) - 1, 1) for i in range(len(lines))]
    rise_start = sum(s[0] for s in timeline)
    rise_items = []
    for i, line in enumerate(lines):
        rise_items.append([reading[i], text_card(line, _style_for(line, i)), "hold", False, False, ""])
        kind = ("base", "negative", "sketch", "red", "hard")[i % 5]
        motion = rng.choice(("push", "hold", "punch"))
        rise_items.append([budget * weights[i] / sum(weights), pic(i + 1, kind), motion, True, False, ""])
        if (i + 1) % 3 == 0:
            flash_red = i % 2 == 0
            rise_items.append([FLASH_FRAMES / FPS, red_frame if flash_red else white, "hold", False, flash_red, ""])
    snapped = _snap_cuts([it[0] for it in rise_items], rise_start, list(beats))
    for it, d in zip(rise_items, snapped):
        it[0] = d
    timeline += rise_items
    climax_start = sum(s[0] for s in timeline)

    # 3. Climax: palabras sueltas, primeros planos y destellos; los cortes se aceleran de 6 a 3 cuadros.
    words = script.get("climax") or ["WHO", "AM", "I"]
    climax, t, k = (CLIMAX_END - RISE_END) * T, 0.0, 0
    while t < climax - 1e-6:
        frames = max(3, round(6 - 3 * t / climax))
        d = min(frames / FPS, climax - t)
        step = k % 4
        if step == 0:
            add(d, text_card(words[(k // 4) % len(words)], "word"), "punch", grain=False)
        elif step == 1:
            add(d, pic(rng.randrange(len(pics)), rng.choice(("negative", "red", "hard"))), "shake")
        elif step == 2:
            flash_red = rng.random() < 0.5
            add(d, red_frame if flash_red else white, grain=False, red=flash_red)
        else:
            add(d, pic(k, "sketch"), "punch")
        t, k = t + d, k + 1

    # 4. Quiebre: papel en blanco y la musica muda.
    add((BREAK_END - CLIMAX_END) * T, white, grain=False, tag="break")
    b1 = sum(s[0] for s in timeline)

    # 5. Cierre: el boceto que se aleja, la frase final y la firma.
    final, rest = script.get("final", []), max(T - b1, 3.0)
    sketch_d = rest * 0.22
    line_d = rest * 0.56 / max(len(final), 1)
    add(sketch_d, pic(0, "sketch"), "pull")
    for line in final:
        add(line_d, text_card(line, "invert"), grain=False)
    add(max(0.8, T - sum(s[0] for s in timeline)), text_card(script.get("end", ""), "caption"), grain=False)

    shots = limit_flashes(_to_frames(timeline))
    start, brk = 0, None
    for s in shots:   # el quiebre se mide despues del limitador, que puede atrasar su corte
        if s.tag == "break":
            brk = (start / FPS, (start + s.frames) / FPS)
            break
        start += s.frames
    marks = {"rise": rise_start, "climax": climax_start, "break": brk, "end": sum(s.frames for s in shots) / FPS}
    return shots, marks


def _to_frames(timeline) -> list[Shot]:
    shots, t, prev = [], 0.0, 0
    for d, img, motion, grain, red, tag in timeline:
        t += d
        frames = round(t * FPS) - prev
        if frames > 0:
            shots.append(Shot(frames, img, motion, grain, red, tag))
            prev += frames
    return shots


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
        shot = Shot(shot.frames, shot.image, shot.motion, shot.grain, shot.red, shot.tag)
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
                    frame += wait
                    recent.popleft()
                recent.append(frame)
        out.append(shot)
        frame += shot.frames
    return out


# ---------------------------------------------------------------- render
def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


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


def render(shots: list[Shot], out: Path, music=None, break_span=None, seed: int = 11) -> Path:
    """Cuadros de Python -> FFmpeg por tuberia (un solo proceso), con la musica mezclada."""
    total = sum(s.frames for s in shots)
    T = total / FPS
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if music:
        cmd += ["-i", str(music)]
    cmd += ["-map", "0:v"]
    if music:
        af = ["afade=t=in:st=0:d=0.3", f"afade=t=out:st={max(T - 1.5, 0):.2f}:d=1.5"]
        if break_span:
            af.insert(0, f"volume=enable='between(t,{break_span[0]:.2f},{break_span[1]:.2f})':volume=0")
        cmd += ["-map", "1:a", "-af", ",".join(af), "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{T:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]

    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 12, (6, H // 2, W // 2)).astype(np.float32)
    grain = [np.repeat(np.repeat(n, 2, 0), 2, 1)[..., None] for n in noise]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vignette = (1.0 - 0.42 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2)[..., None]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frame = 0
    try:
        for shot in shots:
            for i in range(shot.frames):
                arr = np.asarray(_moved(shot.image, shot.motion, i, shot.frames, rng), dtype=np.float32)
                if shot.grain:
                    arr = arr * vignette + grain[rng.integers(len(grain))]
                if frame >= total - FADE_OUT_FRAMES:
                    arr = arr * ((total - frame) / FADE_OUT_FRAMES)
                proc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
                frame += 1
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"FFmpeg fallo al escribir {out}")
    return Path(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Formato Catarsis: Short vertical de impacto, sin voz.")
    ap.add_argument("script", help="guion de tarjetas (JSON)")
    ap.add_argument("--images", required=True, help="carpeta con las imagenes que nombra el guion")
    ap.add_argument("--music", help="pista de musica apta para YouTube")
    ap.add_argument("--seconds", type=float, help="duracion total (por defecto la del guion, o 40)")
    ap.add_argument("--out", default="catarsis.mp4")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    script = json.loads(Path(a.script).read_text(encoding="utf-8"))
    seconds = a.seconds or script.get("seconds") or 40
    beats = music_beats(a.music, seconds) if a.music else []
    shots, marks = plan(script, Path(a.images), seconds, beats, seed=a.seed)
    render(shots, Path(a.out), music=a.music, break_span=marks["break"])
    print(f"[catarsis] listo: {a.out} ({marks['end']:.1f} s, {len(shots)} planos, {len(beats)} golpes de musica)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
