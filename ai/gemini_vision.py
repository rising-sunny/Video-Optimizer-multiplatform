# -*- coding: utf-8 -*-
"""Vision con Gemini (REST): mirar imagenes y devolver texto/JSON.

Por que Gemini (2026-09-23): la clave de Groq ya no tiene modelos de vision
(Llama 4 Scout/Maverick devuelven 404 model_not_found) y GEMINI_API_KEY ya esta
en el .env. La clave va en el header `x-goog-api-key`, nunca en la URL (la URL
termina en logs y tracebacks).

    from ai.gemini_vision import ask_images
    ask_images("Read the headline text.", [jpeg_bytes])
"""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Iterable, Optional

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")


def available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def to_jpeg(image, max_side: int = 1280) -> bytes:
    """PIL.Image o bytes -> JPEG (lado mayor <= max_side)."""
    from PIL import Image
    im = Image.open(io.BytesIO(image)) if isinstance(image, (bytes, bytearray)) else image
    im = im.convert("RGB")
    if max(im.size) > max_side:
        scale = max_side / float(max(im.size))
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def ask_images(prompt: str, images: Iterable, *, model: Optional[str] = None, json_mode: bool = False,
               timeout: int = 90, temperature: float = 0) -> str:
    """Una consulta con varias imagenes. Lanza RuntimeError con el error de la API (sin la clave)."""
    import requests
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY no configurada")
    parts = [{"text": prompt}]
    for img in images:
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": base64.b64encode(to_jpeg(img)).decode()}})
    config = {"temperature": temperature}
    if json_mode:
        config["responseMimeType"] = "application/json"
    r = requests.post(API_URL.format(model=model or DEFAULT_MODEL),
                      headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                      data=json.dumps({"contents": [{"parts": parts}], "generationConfig": config}),
                      timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini sin respuesta util: {str(data)[:200]}")


def ask_grounded(prompt: str, *, model: Optional[str] = None, timeout: int = 150) -> tuple:
    """Consulta de texto con Google Search activado (grounding).

    Devuelve (texto, fuentes) donde fuentes = [{"title", "uri"}] de las paginas
    que Gemini consulto. Con la herramienta de busqueda activa la API no acepta
    responseMimeType JSON: el JSON se pide en el prompt y se lee con parse_json.
    Lanza RuntimeError (sin la clave) si la API falla o no hay cuota (429).
    """
    import requests
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY no configurada")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0}}
    r = requests.post(API_URL.format(model=model or DEFAULT_MODEL),
                      headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                      data=json.dumps(body), timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    try:
        cand = data["candidates"][0]
        text = "".join(p.get("text", "") for p in cand["content"]["parts"]).strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini sin respuesta util: {str(data)[:200]}")
    sources = []
    for chunk in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
        web = chunk.get("web") or {}
        if web.get("uri"):
            sources.append({"title": web.get("title", ""), "uri": web["uri"]})
    return text, sources


def parse_json(text: str):
    """JSON de una respuesta (tolera ```json ... ```)."""
    t = str(text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0]
    start = min([i for i in (t.find("["), t.find("{")) if i >= 0] or [0])
    return json.loads(t[start:])
