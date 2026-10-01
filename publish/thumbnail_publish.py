# -*- coding: utf-8 -*-
"""Miniatura de publicacion: prepararla, subirla con reintentos, informar y verificarla despues.

Por que (2026-09-22, "a veces el thumbnail no aparece"):
  - El selector aceptaba .webp; el staging lo copiaba como thumbnail.webp y el
    uploader solo buscaba thumbnail.png/.jpg/.jpeg: se publicaba SIN miniatura y
    sin decir nada. Y si llegaba, iba etiquetada image/png siendo WebP.
  - Si thumbnails.set fallaba, el uploader lo imprimia en la consola; el panel
    decia "YouTube publicado" igual.
  - Se pedia la miniatura en el mismo instante en que termina la subida, sin
    reintento: un error transitorio de YouTube en ese momento la perdia.
  - No quedaba registro de QUE miniatura se mando, asi que un caso raro (Gunnerside
    muestra una miniatura que no esta en ningun proyecto) no se puede auditar.

Verificado en vivo el mismo dia: en este canal los Shorts SI muestran la miniatura
personalizada en canal/busqueda (Hannibal '250KG LOAD', Catalhoyuk '7K PEOPLE'),
con bordes difuminados; en el feed de Shorts YouTube nunca la usa.

    .venv\\Scripts\\python.exe thumbnail_publish.py VIDEO_ID ruta\\miniatura.jpg   # verificar

Ver `test_thumbnail_publish.py`.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any, Callable, Optional

YOUTUBE_API_THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024
THUMBNAIL_GLOBS = ("thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png", "thumbnail.webp",
                   "thumb.jpg", "thumb.jpeg", "thumb.png", "thumb.webp")
RETRY_WAITS = (8, 20)          # segundos entre intentos de thumbnails.set
MIN_SHORT_SIDE = 640           # YouTube pide 640 px en el lado corto como minimo


def find_staged_thumbnail(folder) -> Optional[Path]:
    """La miniatura de una carpeta de publicacion, en cualquier formato que acepte el selector."""
    folder = Path(folder)
    for name in THUMBNAIL_GLOBS:
        p = folder / name
        if p.is_file():
            return p
    for p in sorted(folder.glob("*.*")):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and "thumb" in p.stem.lower():
            return p
    return None


def prepare_for_youtube(image_path, out_dir=None, max_bytes: int = YOUTUBE_API_THUMBNAIL_MAX_BYTES,
                        log: Callable[[str], None] = lambda m: None, jpeg_only: bool = False) -> dict[str, Any]:
    """Deja la miniatura en un formato que la API acepta: JPEG o PNG reales, <= 2 MB.

    Detecta el formato por el CONTENIDO (no la extension): WebP, HEIC renombrado,
    PNG con alfa, etc. se convierten a JPEG. Devuelve {path, mimetype, width, height,
    bytes, converted, warnings}. Lanza ValueError si la imagen no se puede abrir.
    jpeg_only: la portada de Instagram (cover_url) solo admite JPEG; un PNG tambien se convierte.
    """
    from PIL import Image

    src = Path(image_path)
    if not src.is_file():
        raise ValueError(f"la miniatura no existe: {src}")
    warnings: list[str] = []
    with Image.open(src) as img:
        fmt = (img.format or "").upper()
        width, height = img.size
        if min(width, height) < MIN_SHORT_SIDE:
            warnings.append(f"{width}x{height}: menos de {MIN_SHORT_SIDE} px en el lado corto (YouTube la puede rechazar)")
        size = src.stat().st_size
        if fmt in (("JPEG",) if jpeg_only else ("JPEG", "PNG")) and size <= max_bytes:
            return {"path": str(src), "mimetype": "image/jpeg" if fmt == "JPEG" else "image/png",
                    "width": width, "height": height, "bytes": size, "converted": False, "warnings": warnings}
        base = img.convert("RGB")
    dest_dir = Path(out_dir) if out_dir else src.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (src.stem + "_youtube.jpg")
    reason = f"formato {fmt or 'desconocido'}" if fmt not in ("JPEG", "PNG") else f"{size / 1048576:.2f} MB"
    for quality in (92, 88, 84, 80, 75, 70, 65, 60, 55):
        base.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)
        if dest.stat().st_size <= max_bytes:
            break
    else:
        scaled = base
        while dest.stat().st_size > max_bytes and scaled.width > 320:
            scaled = scaled.resize((scaled.width * 8 // 10, scaled.height * 8 // 10))
            scaled.save(dest, "JPEG", quality=80, optimize=True, progressive=True)
        width, height = scaled.size
    log(f"   Miniatura convertida a JPEG ({reason} -> {dest.stat().st_size / 1048576:.2f} MB)")
    return {"path": str(dest), "mimetype": "image/jpeg", "width": width, "height": height,
            "bytes": dest.stat().st_size, "converted": True, "warnings": warnings}


def classify_thumbnail_error(exc: BaseException) -> tuple[bool, str]:
    """(reintentar?, explicacion para el panel)."""
    text = str(exc)
    status = getattr(getattr(exc, "resp", None), "status", None)
    low = text.lower()
    if status == 403 or "forbidden" in low or "permission" in low:
        return False, ("YouTube no permite miniaturas personalizadas a esta cuenta (403). "
                       "Verifica el canal por telefono en youtube.com/verify.")
    if status == 400 or "invalidimage" in low or "mediabodyrequired" in low:
        return False, "YouTube rechazo la imagen (400: formato o tamano invalido)."
    if status == 429 or "ratelimit" in low or "quota" in low:
        return False, "limite de cuota/velocidad de YouTube (429); se puede poner mas tarde en Studio."
    if status in (404, 409, 500, 502, 503, 504) or "videonotfound" in low or "timeout" in low or "connection" in low:
        return True, f"error transitorio de YouTube ({status or type(exc).__name__})"
    return True, f"{type(exc).__name__}: {text[:160]}"


def set_thumbnail_with_retry(youtube, video_id: str, prepared: dict[str, Any], *,
                             media_factory=None, sleep=time.sleep, waits=RETRY_WAITS,
                             on_status: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    """thumbnails.set con reintentos para errores transitorios. Devuelve {ok, attempts, error, response}."""
    if media_factory is None:
        from googleapiclient.http import MediaFileUpload

        def media_factory(path, mimetype):
            return MediaFileUpload(path, mimetype=mimetype)
    attempts = 0
    last_error = ""
    for wait in (0,) + tuple(waits):
        if wait:
            on_status(f"Miniatura: reintento en {wait} s ({last_error})")
            sleep(wait)
        attempts += 1
        try:
            resp = youtube.thumbnails().set(
                videoId=video_id, media_body=media_factory(prepared["path"], prepared["mimetype"])).execute()
            return {"ok": True, "attempts": attempts, "error": None, "response": resp}
        except Exception as exc:
            retry, last_error = classify_thumbnail_error(exc)
            if not retry:
                break
    return {"ok": False, "attempts": attempts, "error": last_error, "response": None}


# ----------------------------------------------------------------------------
# Verificacion posterior: lo que YouTube MUESTRA contra el archivo local
# ----------------------------------------------------------------------------
def _ahash(img, n: int = 16) -> list[bool]:
    g = img.convert("L").resize((n, n))
    px = list(g.getdata())
    mean = sum(px) / len(px)
    return [p > mean for p in px]


def _distance(a, b) -> float:
    return sum(x != y for x, y in zip(a, b)) / max(1, len(a))


def served_matches_local(served, local, threshold: float = 0.22) -> tuple[bool, float]:
    """Compara la miniatura servida con la local. Para un Short vertical, YouTube sirve
    un 16:9 con la miniatura al CENTRO y bordes difuminados: se compara el centro."""
    lw, lh = local.size
    sw, sh = served.size
    if lh > lw and sw > sh:                      # local vertical, servida horizontal
        panel_w = int(sh * lw / lh)
        left = (sw - panel_w) // 2
        served = served.crop((left, 0, left + panel_w, sh))
    d = _distance(_ahash(served), _ahash(local))
    return d <= threshold, round(d, 3)


def verify_served_thumbnail(video_id: str, local_path, fetch=None) -> dict[str, Any]:
    """Baja la miniatura que YouTube muestra y la compara con la local (puede tardar minutos en propagar)."""
    from PIL import Image

    if fetch is None:
        import requests

        def fetch(url):
            r = requests.get(url, timeout=20)
            return r.content if r.status_code == 200 else None
    raw = fetch(f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg") or \
        fetch(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
    if not raw:
        return {"checked": False, "match": None, "distance": None, "reason": "YouTube no sirvio la miniatura"}
    served = Image.open(io.BytesIO(raw)).convert("RGB")
    with Image.open(local_path) as im:
        ok, d = served_matches_local(served, im.convert("RGB"))
    return {"checked": True, "match": ok, "distance": d,
            "reason": "coincide" if ok else "YouTube muestra otra imagen (o todavia no propago)"}


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("Uso: thumbnail_publish.py VIDEO_ID ruta/miniatura")
        return 2
    rep = verify_served_thumbnail(argv[0], argv[1])
    print(rep)
    return 0 if rep.get("match") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
