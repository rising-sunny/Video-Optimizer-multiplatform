#!/usr/bin/env python3
"""
daily_short_pipeline.py — Pipeline automatizado para producir Shorts diarios.

Flujo:
  1. Detecta temas trending (Google Trends + IA)
  2. Cruza tendencias con las categorías del canal
  3. Selecciona la mejor idea
  4. Genera storyboard (guión + audio + timing + prompts visuales)
  5. Ensambla el video final con subtítulos
  6. Genera thumbnail optimizado
  7. Genera metadata para YouTube (título, descripción, tags)
  8. Deja todo listo para subir manualmente

Uso:
  python daily_short_pipeline.py                  # Genera 1 Short automático
  python daily_short_pipeline.py --count 3        # Genera 3 Shorts
  python daily_short_pipeline.py --topic "..."    # Fuerza un tema específico
  python daily_short_pipeline.py --voice "..."    # Especifica voz TTS
  python daily_short_pipeline.py --list-voices    # Lista voces disponibles

  # Preset FAL.AI (Flux dev + Kling Std I2V) para @Stunning-Revelations:
  python daily_short_pipeline.py --provider fal
  python daily_short_pipeline.py --provider fal --count 3

  # Control manual por proveedor:
  python daily_short_pipeline.py --image-provider flux_schnell
  python daily_short_pipeline.py --image-provider flux_dev --video-provider fal \\
                                  --fal-video-model kling-pro
  python daily_short_pipeline.py --video-provider runway
"""

import sys
import os
import json
import argparse
import time
import re
import unicodedata
from pathlib import Path
from datetime import datetime

# ── Configurar encoding para Windows ──────────────────────────────────────
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

# ── Agregar directorio del proyecto al path ───────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# ── Cargar variables de entorno ───────────────────────────────────────────
from infra.env_loader import load_project_env
load_project_env()

# ── Configurar FFmpeg ─────────────────────────────────────────────────────
from infra.video_config import VideoConfig
try:
    VideoConfig.ensure_ffmpeg_in_path()
except Exception as e:
    print(f"️ FFmpeg no configurado: {e}")

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DEL CANAL (cargada desde channel strategy profile)
# ═══════════════════════════════════════════════════════════════════════════

from channel.channel_strategy import (
    get_channel_name,


    get_channel_strategy,
    get_shorts_rules,
    get_all_category_names,
    get_categories_by_priority,
    build_category_weight_map,
    validate_duration,
    validate_hook,
)

_strategy = get_channel_strategy()
_identity = _strategy.get("channel_identity", {})
_shorts = get_shorts_rules()
_tts = _strategy.get("tts", {})

CHANNEL_CONFIG = {
    "channel_id": _identity.get("channel_id", "UC66EnGiys6V3gKe-J0XD-_Q"),
    "channel_handle": _identity.get("channel_handle", "this-channel"),
    "language": _identity.get("language", "en"),
    "categories": get_all_category_names(),
    "target_duration": _shorts.get("target_duration", 50),
    "visual_style": _strategy.get("visual_style", "Photorealism"),
    "subtitle_style": _strategy.get("subtitle_style", "capcut"),
    "transition_type": _strategy.get("transition_type", "Fade Smooth"),
    "transition_duration": _strategy.get("transition_duration", 0.3),
    "default_voice": _tts.get("default_voice", "en-US-GuyNeural"),
    "tts_rate": _tts.get("rate", "+5%"),
    "trend_regions": _identity.get("trend_regions", ["US", "GB", "GLOBAL"]),
}

# Categorías que mejor funcionan (derivadas del perfil de estrategia)
BEST_PERFORMING_CATEGORIES = [
    c["name"] for c in get_categories_by_priority()
]


def refresh_channel_config():
    """Refresh imported CLI defaults when the GUI switches channel."""
    strategy = get_channel_strategy()
    identity = strategy.get('channel_identity', {})
    tts = strategy.get('tts', {})
    CHANNEL_CONFIG.update(
        channel_id=identity.get('channel_id', ''), channel_handle=identity.get('channel_handle', 'this-channel'),
        language=identity.get('language', 'en'), categories=get_all_category_names(),
        target_duration=get_shorts_rules().get('target_duration', 50),
        visual_style=strategy.get('visual_style', 'Photorealism'), subtitle_style=strategy.get('subtitle_style', 'capcut'),
        transition_type=strategy.get('transition_type', 'Fade Smooth'), transition_duration=strategy.get('transition_duration', 0.3),
        default_voice=tts.get('default_voice', 'en-US-GuyNeural'), tts_rate=tts.get('rate', '+5%'),
        trend_regions=identity.get('trend_regions', ['US', 'GB', 'GLOBAL']))
    BEST_PERFORMING_CATEGORIES[:] = [c['name'] for c in get_categories_by_priority()]

EDITORIAL_FOCUS_KEYWORDS = {
    "history",
    "historical",
    "ancient",
    "civilization",
    "empire",
    "war",
    "battle",
    "declassified",
    "military",
    "secret",
    "secrets",
    "conspiracy",
    "cover up",
    "mystery",
    "mysterious",
    "unexplained",
    "unsolved",
    "ufo",
    "ufos",
    "alien",
    "paranormal",
    "haunted",
    "ghost",
    "occult",
    "ritual",
    "disappearance",
    "secret society",
    "lost city",
    "artifact",
    "voynich",
    "roswell",
    "dyatlov",
    # Natural disasters & extreme events
    "earthquake",
    "volcanic",
    "eruption",
    "tsunami",
    "flood",
    "catastrophe",
    "disaster",
    "krakatoa",
    "pompeii",
    "tunguska",
    "tambora",
    "vesuvius",
    "santorini",
    "lisbon",
    "famine",
    "plague",
    "extinction",
    # Lost civilizations
    "cahokia",
    "hittites",
    "minoans",
    "nabateans",
    "carthage",
    "angkor",
    "gobekli tepe",
    "sea peoples",
    "indus valley",
    "sumer",
    "assyria",
}

EDITORIAL_BLOCKED_KEYWORDS = {
    "health",
    "medical",
    "medicine",
    "diet",
    "fitness",
    "wellness",
    "therapy",
    "vaccine",
    "hospital",
    "celebrity",
    "celeb",
    "actor",
    "actress",
    "singer",
    "album",
    "movie",
    "film",
    "tv",
    "series",
    "showbiz",
    "entertainment",
    "gossip",
    "sports",
    "sport",
    "football",
    "soccer",
    "basketball",
    "baseball",
    "tennis",
    "olympics",
    "athlete",
    "tournament",
    "match",
    "science",
    "scientific",
    "technology",
    "tech",
    "breakthrough",
    "smartphone",
    "app",
    "gadget",
}

EDITORIAL_FALLBACK_IDEAS = [
    {
        "title": "The Roswell Incident: 7 Facts Still Unexplained",
        "category": "UFOs & Paranormal",
        "justification": "Tema evergreen de alto interés dentro del enfoque misterio-UFO del canal.",
    },
    {
        "title": "The Dyatlov Pass Case: 6 Clues Still Unsolved",
        "category": "Mysteries & Unexplained",
        "justification": "Caso histórico y misterioso con enorme potencial evergreen para Shorts.",
    },
    {
        "title": "The Voynich Manuscript: 5 Secrets No One Solved",
        "category": "Ancient History & Civilizations",
        "justification": "Combina historia, misterio y conspiración ligera, alineado con la línea editorial.",
    },
]

# ── Cargar datos de rendimiento del canal ────────────────────────────────
CHANNEL_PERFORMANCE_PATH = PROJECT_DIR / "daily_shorts" / "channel_performance.json"
CHANNEL_PERFORMANCE = {}
try:
    if CHANNEL_PERFORMANCE_PATH.exists():
        with open(CHANNEL_PERFORMANCE_PATH, "r", encoding="utf-8") as _f:
            CHANNEL_PERFORMANCE = json.load(_f)
except Exception:
    pass

# ═══════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════════════════

def log(msg: str, level: str = "INFO"):
    """Logging con timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "ℹ️", "OK": "", "WARN": "️", "ERROR": "", "STEP": ""}.get(level, "  ")
    print(f"[{ts}] {prefix} {msg}")


def create_output_dir() -> Path:
    """Crea directorio de salida para el Short de hoy."""
    today = datetime.now().strftime("%Y-%m-%d")
    base = PROJECT_DIR / "daily_shorts" / today
    # Si ya existe, agregar sufijo incremental
    output_dir = base
    counter = 1
    while output_dir.exists():
        output_dir = base.parent / f"{today}_{counter}"
        counter += 1
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


STORYBOARD_FILENAME = "storyboard.json"
PIPELINE_STATE_FILENAME = "pipeline_state.json"
LEGACY_METADATA_FILENAME = "metadata.json"
YOUTUBE_METADATA_FILENAME = "youtube_metadata.json"
FACEBOOK_METADATA_FILENAME = "facebook_metadata.json"
INSTAGRAM_METADATA_FILENAME = "instagram_metadata.json"


def _safe_read_json(path: Path) -> dict | None:
    """Lee un JSON y devuelve None si el archivo no existe o no es válido."""
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _storyboard_for_disk(storyboard: dict, output_dir: Path) -> dict:
    """Devuelve una versión JSON-safe del storyboard para persistir drafts."""

    skip = object()

    def _clean(value):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value

        if isinstance(value, Path):
            return str(value)

        if isinstance(value, datetime):
            return value.isoformat()

        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                if key == "_generator":
                    continue
                normalized = _clean(item)
                if normalized is skip:
                    continue
                cleaned[key] = normalized
            return cleaned

        if isinstance(value, (list, tuple)):
            cleaned = []
            for item in value:
                normalized = _clean(item)
                if normalized is skip:
                    continue
                cleaned.append(normalized)
            return cleaned

        if isinstance(value, set):
            cleaned = []
            for item in value:
                normalized = _clean(item)
                if normalized is skip:
                    continue
                cleaned.append(normalized)
            return cleaned

        # Cualquier objeto complejo del runtime (clientes, locks, threads, etc.)
        # no debe persistirse en storyboard.json.
        return skip

    serializable = _clean(storyboard or {})
    if not isinstance(serializable, dict):
        serializable = {}
    serializable["_project_path"] = str(output_dir)
    return serializable


def save_storyboard(output_dir: Path, storyboard: dict) -> Path:
    """Guarda el storyboard del draft en disco."""
    output_dir = Path(output_dir)
    storyboard_path = output_dir / STORYBOARD_FILENAME
    payload = _storyboard_for_disk(storyboard, output_dir)
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return storyboard_path


def load_storyboard(output_dir: Path) -> dict | None:
    """Carga el storyboard persistido para un draft."""
    output_dir = Path(output_dir)
    data = _safe_read_json(output_dir / STORYBOARD_FILENAME)
    if not data:
        return None
    data["_project_path"] = str(output_dir)
    return data


def load_idea(output_dir: Path) -> dict | None:
    """Carga la idea seleccionada para un draft."""
    output_dir = Path(output_dir)
    return _safe_read_json(output_dir / "idea.json")


def _resolve_output_media_path(output_dir: Path, raw_path: str | None) -> Path | None:
    """Resuelve rutas de media guardadas en el storyboard de Daily Shorts."""
    if not raw_path:
        return None

    try:
        candidate = Path(str(raw_path))
    except Exception:
        return None

    if candidate.is_absolute():
        return candidate if candidate.exists() else None

    candidate_paths = [output_dir / candidate]
    if len(candidate.parts) == 1:
        candidate_paths.extend([
            output_dir / "project_media" / candidate.name,
            output_dir / "images" / candidate.name,
            output_dir / "videos" / candidate.name,
        ])

    for path in candidate_paths:
        if path.exists():
            return path
    return None


def get_storyboard_visual_status(storyboard: dict | None, output_dir: Path) -> dict:
    """Calcula cuántos segmentos del storyboard ya tienen visual asignado."""
    output_dir = Path(output_dir)
    segments = (storyboard or {}).get("segments", []) or []

    missing_segments = []
    ready_segments = 0

    for idx, seg in enumerate(segments, start=1):
        has_visual = False

        if seg.get("image_deleted", False):
            has_visual = True
        else:
            for field in ("video_path", "image_path"):
                resolved = _resolve_output_media_path(output_dir, seg.get(field))
                if resolved:
                    has_visual = True
                    break

        if has_visual:
            ready_segments += 1
        else:
            missing_segments.append(idx)

    total_segments = len(segments)
    return {
        "total_segments": total_segments,
        "ready_segments": ready_segments,
        "missing_segments_count": len(missing_segments),
        "missing_segments": missing_segments,
        "is_complete": total_segments > 0 and ready_segments == total_segments,
    }


def _compute_draft_status(visual_status: dict, has_summary: bool = False,
                          has_video: bool = False) -> str:
    """Resume el estado del draft en una etiqueta simple para UI."""
    if has_summary:
        return "completed"
    if has_video:
        return "video_ready"

    total_segments = visual_status.get("total_segments", 0)
    ready_segments = visual_status.get("ready_segments", 0)
    missing_segments = visual_status.get("missing_segments_count", 0)

    if total_segments <= 0:
        return "draft"
    if missing_segments == 0:
        return "images_ready"
    if ready_segments > 0:
        return "images_partial"
    return "storyboard_ready"


def save_pipeline_state(output_dir: Path, status: str | None = None,
                        idea: dict | None = None, storyboard: dict | None = None,
                        video_path: str | None = None, metadata: dict | None = None,
                        note: str | None = None, extra: dict | None = None) -> dict:
    """Guarda un snapshot liviano del estado del draft para poder reanudarlo."""
    output_dir = Path(output_dir)
    state_path = output_dir / PIPELINE_STATE_FILENAME
    existing = _safe_read_json(state_path) or {}

    current_storyboard = storyboard if storyboard is not None else load_storyboard(output_dir)
    visual_status = get_storyboard_visual_status(current_storyboard, output_dir) if current_storyboard else {
        "total_segments": 0,
        "ready_segments": 0,
        "missing_segments_count": 0,
        "missing_segments": [],
        "is_complete": False,
    }

    has_summary = (output_dir / "summary.json").exists()
    resolved_video_path = video_path or existing.get("video_path")
    resolved_status = status or _compute_draft_status(
        visual_status,
        has_summary=has_summary,
        has_video=bool(resolved_video_path),
    )

    now_iso = datetime.now().isoformat()
    idea_data = idea or load_idea(output_dir) or {}
    storyboard_topic = (current_storyboard or {}).get("topic", "")
    storyboard_category = (current_storyboard or {}).get("category", "")
    storyboard_subtitle_style = (current_storyboard or {}).get("_subtitle_style")

    state = {
        "created_at": existing.get("created_at") or now_iso,
        "updated_at": now_iso,
        "status": resolved_status,
        "topic": idea_data.get("title") or existing.get("topic") or storyboard_topic or output_dir.name,
        "category": idea_data.get("category") or existing.get("category") or storyboard_category,
        "output_dir": str(output_dir),
        "storyboard_path": str(output_dir / STORYBOARD_FILENAME) if (output_dir / STORYBOARD_FILENAME).exists() else None,
        "summary_path": str(output_dir / "summary.json") if has_summary else None,
        "video_path": resolved_video_path,
        "metadata_ready": bool(metadata) or any(
            (output_dir / filename).exists()
            for filename in (
                LEGACY_METADATA_FILENAME,
                YOUTUBE_METADATA_FILENAME,
                FACEBOOK_METADATA_FILENAME,
                INSTAGRAM_METADATA_FILENAME,
            )
        ),
        "segments_total": visual_status["total_segments"],
        "segments_ready": visual_status["ready_segments"],
        "segments_missing": visual_status["missing_segments_count"],
        "missing_segments": visual_status["missing_segments"],
        "note": note if note is not None else existing.get("note", ""),
        "subtitle_style": storyboard_subtitle_style or existing.get("subtitle_style"),
    }

    if extra:
        state.update(extra)

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    return state


def get_draft_state(output_dir: Path) -> dict:
    """Obtiene una vista consolidada del draft para mostrarlo en la UI."""
    output_dir = Path(output_dir)
    saved_state = _safe_read_json(output_dir / PIPELINE_STATE_FILENAME) or {}
    summary = _safe_read_json(output_dir / "summary.json") or {}
    idea = load_idea(output_dir) or {}
    storyboard = load_storyboard(output_dir)

    has_summary = bool(summary)
    video_path = summary.get("video_path") or saved_state.get("video_path")
    visual_status = get_storyboard_visual_status(storyboard, output_dir) if storyboard else {
        "total_segments": 0,
        "ready_segments": 0,
        "missing_segments_count": 0,
        "missing_segments": [],
        "is_complete": False,
    }
    status = _compute_draft_status(
        visual_status,
        has_summary=has_summary,
        has_video=bool(video_path),
    )

    return {
        "created_at": saved_state.get("created_at") or summary.get("generated_at") or "",
        "updated_at": saved_state.get("updated_at") or summary.get("generated_at") or "",
        "status": status,
        "topic": summary.get("topic") or idea.get("title") or saved_state.get("topic") or output_dir.name,
        "category": summary.get("category") or idea.get("category") or saved_state.get("category") or "",
        "output_dir": str(output_dir),
        "video_path": video_path,
        "segments_total": visual_status["total_segments"],
        "segments_ready": visual_status["ready_segments"],
        "segments_missing": visual_status["missing_segments_count"],
        "missing_segments": visual_status["missing_segments"],
        "metadata_ready": bool(summary.get("metadata")) or bool(summary.get("platform_metadata")) or saved_state.get("metadata_ready", False),
        "has_summary": has_summary,
        "note": saved_state.get("note", ""),
        "subtitle_style": saved_state.get("subtitle_style") or (storyboard or {}).get("_subtitle_style"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# DEDUPLICACIÓN: recopilar títulos ya usados
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_title(title: str) -> str:
    """Normaliza un título para comparación (minúsculas, sin puntuación extra)."""
    import re
    t = title.lower().strip()
    t = re.sub(r'[^\w\s]', ' ', t)      # quitar puntuación
    t = re.sub(r'\s+', ' ', t).strip()   # colapsar espacios
    
    # Remover stop-words comunes en inglés y español para mejorar la precisión de similitud (Jaccard)
    stop_words = {"the", "a", "an", "of", "in", "and", "to", "is", "for", "on", "with", "at", "by", "from", 
                  "el", "la", "los", "las", "un", "una", "de", "en", "y", "por", "con", "para", "su"}
    words = [w for w in t.split() if w not in stop_words]
    return " ".join(words)


def _titles_are_similar(title_a: str, title_b: str, threshold: float = 0.40) -> bool:
    """Compara dos títulos por similitud (Jaccard sobre palabras). Umbral estricto por defecto 40%."""
    words_a = set(_normalize_title(title_a).split())
    words_b = set(_normalize_title(title_b).split())
    if not words_a or not words_b:
        return False
    intersection = words_a & words_b
    union = words_a | words_b
    similarity = len(intersection) / len(union)
    return similarity >= threshold


def find_similar_title(title: str, used_titles: list, threshold: float = 0.40) -> str | None:
    """Devuelve el primer titulo similar encontrado o None si no hay coincidencias."""
    if not title or not used_titles:
        return None

    for used in used_titles:
        if _titles_are_similar(title, used, threshold=threshold):
            return used
    return None


def get_used_titles() -> list:
    """
    Recopila todos los títulos ya usados desde dos fuentes:
      1. Summaries locales en daily_shorts/
      2. Proyectos manuales de /projects/
      3. Videos publicados en el canal de YouTube
    Devuelve una lista de strings (títulos).
    """
    titles = []

    # ── Fuente 1: summaries locales ──────────────────────────────────────
    shorts_dir = PROJECT_DIR / "daily_shorts"
    if shorts_dir.exists():
        for summary_file in shorts_dir.rglob("summary.json"):
            try:
                import json
                with open(summary_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                topic = data.get("topic") or ""
                meta_title = (data.get("metadata") or {}).get("title") or ""
                # Agregar ambos si difieren
                if topic:
                    titles.append(topic)
                if meta_title and _normalize_title(meta_title) != _normalize_title(topic):
                    titles.append(meta_title)
            except Exception:
                continue

    # ── Fuente 1b: proyectos manuales en Auto Video Studio ────────────────
    projects_dir = PROJECT_DIR / "projects"
    if projects_dir.exists():
        for storyboard_file in projects_dir.rglob("storyboard.json"):
            try:
                import json
                with open(storyboard_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                topic = data.get("topic") or ""
                meta_title = data.get("title") or ""
                if topic: titles.append(topic)
                if meta_title and _normalize_title(meta_title) != _normalize_title(topic):
                    titles.append(meta_title)
            except Exception:
                continue

    # ── Fuente  2: videos del canal de YouTube ────────────────────────────
    try:
        from channel.youtube_channel_analyzer import YouTubeChannelAnalyzer
        analyzer = YouTubeChannelAnalyzer(
            channel_id=CHANNEL_CONFIG.get("channel_id"),
            channel_handle=CHANNEL_CONFIG.get("channel_handle"),
        )
        videos = analyzer.get_channel_videos(max_results=200)
        for v in videos:
            t = v.get("title", "").strip()
            if t:
                titles.append(t)
    except Exception as e:
        log(f"No se pudieron obtener videos del canal: {e}", "WARN")

    # Deduplicar manteniendo orden
    seen = set()
    unique = []
    for t in titles:
        key = _normalize_title(t)
        if key and key not in seen:
            seen.add(key)
            unique.append(t)

    return unique


# ═══════════════════════════════════════════════════════════════════════════
# PASO 1: DETECTAR TENDENCIAS
# ═══════════════════════════════════════════════════════════════════════════

# Override legacy title matching above with a stricter topic-aware heuristic.
_TITLE_STOP_WORDS = {
    "the", "a", "an", "of", "in", "and", "to", "is", "for", "on", "with", "at", "by", "from",
    "el", "la", "los", "las", "un", "una", "de", "en", "y", "por", "con", "para", "su",
    "that", "this", "these", "those", "than", "what", "why", "how", "into", "over", "under",
}

_TITLE_HOOK_WORDS = {
    "top", "best", "worst", "deadliest", "powerful", "most", "secret", "hidden", "haunting",
    "untold", "reveal", "uncover", "truth", "fact", "story", "shocking", "stronger",
}


def _stem_title_token(token: str) -> str:
    """Reduce variaciones frecuentes para comparar familias tematicas."""
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith(("ss", "us", "is", "ous")):
        return token[:-1]
    return token


def _title_tokens(title: str, ignore_hook_words: bool = False) -> list[str]:
    """Tokeniza y normaliza un titulo para comparar su tema central."""
    text = unicodedata.normalize("NFKD", str(title or "").lower())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    tokens = []
    for raw_token in text.split():
        if raw_token.isdigit() and len(raw_token) < 4:
            continue
        token = _stem_title_token(raw_token)
        if not token or token in _TITLE_STOP_WORDS:
            continue
        if ignore_hook_words and token in _TITLE_HOOK_WORDS:
            continue
        tokens.append(token)
    return tokens


def _title_ngrams(tokens: list[str], size: int = 2) -> set[tuple[str, ...]]:
    """Genera n-gramas consecutivos para detectar frases nucleares compartidas."""
    if len(tokens) < size:
        return set()
    return {tuple(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


def _append_title_candidate(target: list[str], value) -> None:
    """Agrega un posible titulo si el valor es un string util."""
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            target.append(cleaned)


def _extract_title_candidates_from_payload(data: dict | None) -> list[str]:
    """Extrae titulos/temas desde summary, idea o pipeline_state."""
    if not isinstance(data, dict):
        return []

    titles = []
    _append_title_candidate(titles, data.get("topic"))
    _append_title_candidate(titles, data.get("title"))

    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        _append_title_candidate(titles, metadata.get("title"))

    platform_metadata = data.get("platform_metadata")
    if isinstance(platform_metadata, dict):
        for payload in platform_metadata.values():
            if isinstance(payload, dict):
                _append_title_candidate(titles, payload.get("title"))

    idea = data.get("idea")
    if isinstance(idea, dict):
        _append_title_candidate(titles, idea.get("topic"))
        _append_title_candidate(titles, idea.get("title"))

    storyboard = data.get("storyboard")
    if isinstance(storyboard, dict):
        _append_title_candidate(titles, storyboard.get("topic"))
        _append_title_candidate(titles, storyboard.get("title"))

    return titles


def _normalize_title(title: str) -> str:
    """Normaliza un titulo a sus tokens centrales."""
    tokens = _title_tokens(title, ignore_hook_words=True)
    if not tokens:
        tokens = _title_tokens(title, ignore_hook_words=False)
    return " ".join(tokens)


def _titles_are_similar(title_a: str, title_b: str, threshold: float = 0.40) -> bool:
    """Compara dos titulos usando overlap de tema y Jaccard como respaldo."""
    normalized_a = _normalize_title(title_a)
    normalized_b = _normalize_title(title_b)
    if not normalized_a or not normalized_b:
        return False
    if normalized_a == normalized_b:
        return True

    core_tokens_a = _title_tokens(title_a, ignore_hook_words=True)
    core_tokens_b = _title_tokens(title_b, ignore_hook_words=True)
    core_set_a = set(core_tokens_a)
    core_set_b = set(core_tokens_b)

    if core_set_a and core_set_b:
        shared_core = core_set_a & core_set_b
        overlap = len(shared_core) / min(len(core_set_a), len(core_set_b))
        if len(shared_core) >= 2 and overlap >= 0.50:
            return True

        if _title_ngrams(core_tokens_a, size=2) & _title_ngrams(core_tokens_b, size=2):
            return True

    words_a = core_set_a or set(_title_tokens(title_a, ignore_hook_words=False))
    words_b = core_set_b or set(_title_tokens(title_b, ignore_hook_words=False))
    if not words_a or not words_b:
        return False

    intersection = words_a & words_b
    union = words_a | words_b
    similarity = len(intersection) / len(union)
    return similarity >= threshold


def find_similar_title(title: str, used_titles: list, threshold: float = 0.40) -> str | None:
    """Devuelve el primer titulo similar encontrado o None si no hay coincidencias."""
    if not title or not used_titles:
        return None

    for used in used_titles:
        if _titles_are_similar(title, used, threshold=threshold):
            return used
    return None


def get_used_titles() -> list:
    """
    Recopila todos los titulos ya usados desde:
      1. Shorts terminados y drafts persistidos en daily_shorts/
      2. Proyectos manuales en /projects/
      3. Videos publicados en el canal de YouTube
    """
    titles = []

    shorts_dir = PROJECT_DIR / "daily_shorts"
    if shorts_dir.exists():
        for json_name in ("summary.json", "idea.json", PIPELINE_STATE_FILENAME):
            for state_file in shorts_dir.rglob(json_name):
                try:
                    data = _safe_read_json(state_file) or {}
                    titles.extend(_extract_title_candidates_from_payload(data))
                except Exception:
                    continue

    projects_dir = PROJECT_DIR / "projects"
    if projects_dir.exists():
        for storyboard_file in projects_dir.rglob("storyboard.json"):
            try:
                data = _safe_read_json(storyboard_file) or {}
                titles.extend(_extract_title_candidates_from_payload(data))
            except Exception:
                continue

    try:
        from channel.youtube_channel_analyzer import YouTubeChannelAnalyzer
        analyzer = YouTubeChannelAnalyzer(
            channel_id=CHANNEL_CONFIG.get("channel_id"),
            channel_handle=CHANNEL_CONFIG.get("channel_handle"),
        )
        videos = analyzer.get_channel_videos(max_results=200)
        for video in videos:
            _append_title_candidate(titles, video.get("title"))
    except Exception as e:
        log(f"No se pudieron obtener videos del canal: {e}", "WARN")

    seen = set()
    unique = []
    for title in titles:
        key = _normalize_title(title)
        if key and key not in seen:
            seen.add(key)
            unique.append(title)

    return unique


def detect_trends(ai_client) -> list:
    """Obtiene temas trending de múltiples regiones."""
    log("Detectando tendencias globales...", "STEP")

    from channel.trend_spotter import get_trending_topics

    all_trends = []
    for region in CHANNEL_CONFIG["trend_regions"]:
        try:
            topics = get_trending_topics(region=region, ai_client=ai_client)
            if topics:
                log(f"  {region}: {len(topics)} tendencias encontradas")
                all_trends.extend(topics)
        except Exception as e:
            log(f"  {region}: falló ({e})", "WARN")

    # Deduplicar manteniendo orden
    seen = set()
    unique = []
    for t in all_trends:
        key = t.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(t.strip())

    log(f"Total tendencias únicas: {len(unique)}", "OK")
    return unique


# ═══════════════════════════════════════════════════════════════════════════
# PASO 2: GENERAR IDEAS DE VIDEO
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_editorial_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s/&-]+", " ", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _editorial_keyword_match(text: str, keyword: str) -> bool:
    normalized_text = _normalize_editorial_text(text)
    normalized_keyword = _normalize_editorial_text(keyword)
    if not normalized_text or not normalized_keyword:
        return False
    if " " in normalized_keyword or "/" in normalized_keyword or "&" in normalized_keyword:
        return normalized_keyword in normalized_text
    return normalized_keyword in set(normalized_text.split())


def _idea_matches_editorial_focus(idea: dict) -> tuple[bool, str]:
    title = str((idea or {}).get("title", ""))
    category = str((idea or {}).get("category", ""))
    justification = str((idea or {}).get("justification", ""))
    combined = " ".join(part for part in (title, category, justification) if part).strip()

    for keyword in EDITORIAL_BLOCKED_KEYWORDS:
        if _editorial_keyword_match(combined, keyword):
            return False, f"bloqueado por enfoque no deseado: {keyword}"

    for keyword in EDITORIAL_FOCUS_KEYWORDS:
        if _editorial_keyword_match(combined, keyword):
            return True, ""

    return False, "no encaja con historia/conspiraciones/misterios/ufos/paranormal"


def _filter_ideas_by_editorial_focus(ideas: list) -> list:
    filtered = []
    for idea in ideas or []:
        allowed, reason = _idea_matches_editorial_focus(idea)
        if allowed:
            filtered.append(idea)
        else:
            log(f"  Descartada (linea editorial): {idea.get('title', 'Sin título')}", "WARN")
            log(f"       motivo: {reason}")
    return filtered


def _pick_editorial_fallback(used_titles: list = None) -> dict:
    for fallback in EDITORIAL_FALLBACK_IDEAS:
        similar_title = find_similar_title(fallback["title"], used_titles)
        if not similar_title:
            return dict(fallback)
    raise ValueError(
        "No se pudieron generar ideas nuevas dentro de la línea editorial y todos los respaldos "
        "también duplican videos existentes."
    )

def generate_video_ideas(trends: list, ai_client, used_titles: list = None) -> list:
    """Cruza tendencias con categorías del canal para generar ideas."""
    log("Generando ideas de video con IA...", "STEP")

    from channel.trend_spotter import analyze_trends_for_video_ideas

    ideas_result = analyze_trends_for_video_ideas(
        trends_list=trends,
        categories=CHANNEL_CONFIG["categories"],
        ai_client=ai_client,
        channel_performance=CHANNEL_PERFORMANCE,
        used_titles=used_titles,
    )

    if "error" in ideas_result:
        log(f"Error generando ideas: {ideas_result['error']}", "ERROR")
        return []

    ideas = ideas_result.get("ideas", [])
    ideas = _filter_ideas_by_editorial_focus(ideas)
    log(f"Ideas generadas: {len(ideas)}", "OK")

    for i, idea in enumerate(ideas, 1):
        log(f"  {i}. {idea.get('title', 'Sin título')} [{idea.get('category', '?')}]")

    return ideas


# ═══════════════════════════════════════════════════════════════════════════
# PASO 3: SELECCIONAR MEJOR IDEA
# ═══════════════════════════════════════════════════════════════════════════

def select_best_idea(ideas: list, forced_topic: str = None,
                     used_titles: list = None) -> dict:
    """Selecciona la mejor idea evitando temas ya usados."""
    if forced_topic:
        similar_title = find_similar_title(forced_topic, used_titles)
        if similar_title:
            log(f"El tema manual '{forced_topic}' es similar a '{similar_title}', pero lo saltaremos.", "WARNING")
            pass
        log(f"Usando tema forzado: {forced_topic}", "STEP")
        return {
            "title": forced_topic,
            "category": "General",
            "justification": "Tema seleccionado manualmente por el usuario.",
        }

    if not ideas:
        fallback = _pick_editorial_fallback(used_titles)
        log("No hay ideas disponibles, usando tema de respaldo unico", "WARN")
        return fallback

    ideas = _filter_ideas_by_editorial_focus(ideas)
    if not ideas:
        fallback = _pick_editorial_fallback(used_titles)
        log("Todas las ideas quedaron fuera de la linea editorial; usando respaldo unico", "WARN")
        return fallback

    if used_titles:
        filtered = []
        for idea in ideas:
            title = idea.get("title", "")
            similar_title = find_similar_title(title, used_titles)
            if similar_title:
                log(f"  Descartada (similar a existente): {title}", "WARN")
                log(f"       similar a: {similar_title}")
            else:
                filtered.append(idea)

        if filtered:
            ideas = filtered
            log(f"  {len(ideas)} ideas pasan el filtro de deduplicacion", "OK")
        else:
            fallback = _pick_editorial_fallback(used_titles)
            log("Todas las ideas eran similares; usando un fallback unico", "WARN")
            return fallback

    unique_ideas = []
    for idea in ideas:
        title = idea.get("title", "")
        is_dup_internal = False
        for accepted in unique_ideas:
            if _titles_are_similar(title, accepted.get("title", "")):
                log(f"  Descartada (duplicado interno): {title}", "WARN")
                is_dup_internal = True
                break
        if not is_dup_internal:
            unique_ideas.append(idea)
    ideas = unique_ideas if unique_ideas else ideas

    top_cats = CHANNEL_PERFORMANCE.get("best_performing_categories", [])
    strategy_weight = build_category_weight_map()

    if top_cats or strategy_weight:
        cat_scores = {}
        for i, cat in enumerate(top_cats):
            cat_scores[cat["name"].lower()] = len(top_cats) - i

        def idea_score(idea):
            cat = idea.get("category", "").lower()
            score = 0
            for cat_name, cat_val in cat_scores.items():
                if cat in cat_name or cat_name in cat:
                    score = cat_val
                    break
            for sw_name, sw_val in strategy_weight.items():
                if cat in sw_name.lower() or sw_name.lower() in cat:
                    score += sw_val
                    break
            title = idea.get("title", "")
            if any(c.isdigit() for c in title):
                score += 1
            if ":" in title:
                score += 1
            return score

        ideas.sort(key=idea_score, reverse=True)

    best = ideas[0]
    log(f"Idea seleccionada: {best.get('title', 'Sin titulo')} [{best.get('category', '?')}]", "OK")
    return best



# ═══════════════════════════════════════════════════════════════════════════
# PASO 4: GENERAR STORYBOARD (guión + audio + timing)
# ═══════════════════════════════════════════════════════════════════════════

def generate_storyboard(idea: dict, voice_id: str = None,
                        bgm_path: str = None, visual_style: str = None,
                        subtitle_style: str = None) -> dict:
    """Genera el storyboard completo: guión, audio, segmentos con timing."""
    log(f"Generando storyboard para: {idea['title']}", "STEP")

    from pipeline.auto_video_generator_v2 import AutoVideoGenerator

    generator = AutoVideoGenerator(parent_window=None)

    # Activar subtítulos dinámicos (necesario para que assemble los aplique)
    effective_subtitle = subtitle_style or CHANNEL_CONFIG["subtitle_style"]
    try:
        from pipeline.dynamic_subtitle_wrapper import patch_subtitle_generation
        patch_subtitle_generation(generator, effective_subtitle)
        log(f"  Subtítulos dinámicos activados (estilo: {effective_subtitle})", "OK")
    except Exception as e:
        log(f"  Subtítulos dinámicos no disponibles: {e}", "WARN")

    topic = idea["title"]
    category = idea.get("category", "History")
    voice = voice_id or CHANNEL_CONFIG["default_voice"]

    # Si hay BGM manual, no buscar música automática
    auto_music = not bgm_path

    style = visual_style or CHANNEL_CONFIG["visual_style"]

    storyboard = generator.generate_storyboard_data(
        topic=topic,
        category=category,
        platform="youtube_short",
        custom_duration=CHANNEL_CONFIG["target_duration"],
        voice_id=voice,
        find_auto_music=auto_music,
        style=style,
        language=CHANNEL_CONFIG["language"],
        rate=CHANNEL_CONFIG["tts_rate"],
    )

    if not storyboard:
        log("Error generando storyboard", "ERROR")
        return None

    script = storyboard.get("script", "")
    segments = storyboard.get("segments", [])
    audio = storyboard.get("audio_path", "")

    log(f"  Guión: {len(script)} caracteres", "OK")
    log(f"  Segmentos: {len(segments)}", "OK")
    log(f"  Audio: {audio}", "OK")

    # Inyectar topic/category para que thumbnail y metadata los usen
    storyboard["topic"] = topic
    storyboard["category"] = category
    storyboard["_subtitle_style"] = effective_subtitle

    # BGM manual si fue proporcionado
    if bgm_path:
        storyboard["_manual_bgm_path"] = bgm_path

    # Guardar referencia al generador para reusar en assembly
    storyboard["_generator"] = generator

    return storyboard


def prepare_short_draft(topic: str = None, voice_id: str = None,
                        bgm_path: str = None, visual_style: str = None,
                        subtitle_style: str = None,
                        output_dir: Path = None) -> tuple[Path, dict, dict]:
    """Crea un draft persistente listo para generar imágenes más tarde."""
    output_dir = Path(output_dir) if output_dir else create_output_dir()

    from ai.ai_factory import AIFactory

    ai_client = AIFactory.get_instance().get_llm_client()
    used_titles = get_used_titles()

    if topic:
        ideas = []
    else:
        trends = detect_trends(ai_client)
        ideas = generate_video_ideas(trends, ai_client, used_titles=used_titles)

    idea = select_best_idea(ideas, forced_topic=topic, used_titles=used_titles)
    idea_path = output_dir / "idea.json"
    with open(idea_path, "w", encoding="utf-8") as f:
        json.dump(idea, f, indent=2, ensure_ascii=False)

    storyboard = generate_storyboard(
        idea,
        voice_id=voice_id,
        bgm_path=bgm_path,
        visual_style=visual_style,
        subtitle_style=subtitle_style,
    )
    if not storyboard:
        raise RuntimeError("Could not generate storyboard")

    storyboard["_project_path"] = str(output_dir)
    save_storyboard(output_dir, storyboard)
    save_pipeline_state(
        output_dir,
        status="storyboard_ready",
        idea=idea,
        storyboard=storyboard,
        note="Generate Images to create the visuals for this draft.",
    )
    return output_dir, idea, storyboard


def generate_images_for_draft(output_dir: Path, storyboard: dict,
                              image_provider: str = "auto",
                              visual_style: str = None,
                              platform: str = "youtube_short") -> tuple[dict, dict]:
    """Genera o reanuda imágenes para un draft persistido en Daily Shorts."""
    output_dir = Path(output_dir)
    working_storyboard = storyboard or {}
    working_storyboard["_project_path"] = str(output_dir)

    generator = working_storyboard.pop("_generator", None)
    if not generator:
        from pipeline.auto_video_generator_v2 import AutoVideoGenerator
        generator = AutoVideoGenerator(parent_window=None)


    raw_style = CHANNEL_CONFIG.get("visual_style", "Photorealism")
    if isinstance(raw_style, list):
        import random
        resolved_style = random.choice(raw_style)
    else:
        resolved_style = raw_style
    style = visual_style or resolved_style

    try:
        # --- MIXED MEDIA INTEGRATION ---
        try:
            from media.mixed_media_acquisition import acquire_youtube_mixed_media
            # if we are long form, maybe disable mixed media or adapt it.
            # actually, let's just disable it if it's long form so it doesn't crop vertically
            if platform == "youtube_short":
                working_storyboard = acquire_youtube_mixed_media(working_storyboard, output_dir)
        except Exception as e:
            print(f"Mixed media failed: {e}")
            
        working_storyboard = generator.generate_all_images_for_storyboard(
            storyboard_data=working_storyboard,
            platform=platform,
            use_real_images=True,
            use_google_images=True,
            image_provider=image_provider,
            style=style,
            project_path=str(output_dir),
        )
    except Exception:
        working_storyboard["_project_path"] = str(output_dir)
        save_storyboard(output_dir, working_storyboard)
        save_pipeline_state(
            output_dir,
            storyboard=working_storyboard,
            extra={
                "image_provider": image_provider,
                "visual_style": style,
            },
        )
        raise

    working_storyboard["_project_path"] = str(output_dir)
    save_storyboard(output_dir, working_storyboard)
    state = save_pipeline_state(
        output_dir,
        storyboard=working_storyboard,
        note=(
            "Resume Generate Images to complete the pending segments."
            if get_storyboard_visual_status(working_storyboard, output_dir).get("missing_segments_count", 0) > 0
            else "Images are ready for Generate Short."
        ),
        extra={
            "image_provider": image_provider,
            "visual_style": style,
        },
    )
    return working_storyboard, state


# ═══════════════════════════════════════════════════════════════════════════
# PASO 5: ENSAMBLAR VIDEO
# ═══════════════════════════════════════════════════════════════════════════

def assemble_video(storyboard: dict, output_dir: Path,
                    image_provider: str = "auto",
                    video_provider: str = "none",
                    fal_video_model: str = "kling",
                    visual_style: str = None,
                    subtitle_style: str = None,
                    transition_type: str = None,
                    transition_duration: float = None,
                    pregenerate_images: bool = True,
                    strict_existing_visuals: bool = False,
                    platform: str = "youtube_short",
                    assembly_options: dict = None) -> str:
    """Ensambla el video final con imágenes, audio y subtítulos."""
    log("Ensamblando video final...", "STEP")

    output_dir = Path(output_dir)
    if strict_existing_visuals:
        from infra.project_media_paths import prepare_existing_media
        prepare_existing_media(storyboard, output_dir)
    generator = storyboard.pop("_generator", None)
    manual_bgm = storyboard.pop("_manual_bgm_path", None)
    storyboard["_project_path"] = str(output_dir)

    if not generator:
        from pipeline.auto_video_generator_v2 import AutoVideoGenerator
        generator = AutoVideoGenerator(parent_window=None)

    # RE-PARCHEAR SUBTÍTULOS AQUÍ:
    effective_subtitle = subtitle_style or CHANNEL_CONFIG.get("subtitle_style", "capcut")
    try:
        from pipeline.dynamic_subtitle_wrapper import patch_subtitle_generation
        patch_subtitle_generation(generator, subtitle_style=effective_subtitle)
    except Exception as e:
        log(f"No se pudieron re-configurar subtítulos dinámicos: {e}", "WARN")

    if manual_bgm:
        log(f"  BGM manual: {manual_bgm}", "INFO")

    # Resolver valores: CLI > CHANNEL_CONFIG > defaults
    effective_subtitle = subtitle_style or CHANNEL_CONFIG.get("subtitle_style", "capcut")
    storyboard["_subtitle_style"] = effective_subtitle
    effective_transition = transition_type or CHANNEL_CONFIG.get("transition_type", "Fade Smooth")
    effective_trans_dur = transition_duration if transition_duration is not None else CHANNEL_CONFIG.get("transition_duration", 0.3)
    storyboard["_transition_type"] = effective_transition
    storyboard["_transition_duration"] = effective_trans_dur

    log(f"  Image provider: {image_provider}", "INFO")
    if video_provider and video_provider != "none":
        modelo_str = f" ({fal_video_model})" if video_provider == "fal" else ""
        log(f"  Video provider: {video_provider}{modelo_str} (I2V por segmento)", "INFO")
    else:
        log(f"  Video provider: none (imagen estatica + Ken Burns)", "INFO")
    log(f"  Subtitle style: {effective_subtitle}", "INFO")
    log(f"  Transition: {effective_transition} ({effective_trans_dur}s)", "INFO")

    # Pre-generar imágenes con el provider seleccionado ANTES de ensamblar.
    # assemble_video_from_storyboard no usa image_provider internamente;
    # genera_all_images_for_storyboard sí lo respeta (Recraft, Fal, etc.)
    # y escribe image_path en cada segmento para que el ensamblador las use.
    raw_style = CHANNEL_CONFIG.get("visual_style", "Photorealism")
    if isinstance(raw_style, list):
        import random
        resolved_style = random.choice(raw_style)
    else:
        resolved_style = raw_style
    style = visual_style or resolved_style
    log(f"  Visual style: {style}", "INFO")
    if pregenerate_images:
        try:
            # --- MIXED MEDIA INTEGRATION ---
            try:
                from media.mixed_media_acquisition import acquire_youtube_mixed_media
                storyboard = acquire_youtube_mixed_media(storyboard, output_dir)
            except Exception as e:
                print(f"Mixed media failed: {e}")
                
            storyboard = generator.generate_all_images_for_storyboard(
                storyboard_data=storyboard,
                platform="youtube_short",
                use_real_images=True,
                use_google_images=True,
                image_provider=image_provider,
                style=style,
                project_path=str(output_dir),
            )
            storyboard["_project_path"] = str(output_dir)
            save_storyboard(output_dir, storyboard)
            save_pipeline_state(
                output_dir,
                storyboard=storyboard,
                extra={
                    "image_provider": image_provider,
                    "visual_style": style,
                },
            )
            log("  Imágenes pre-generadas correctamente", "OK")
        except Exception as e:
            storyboard["_project_path"] = str(output_dir)
            save_storyboard(output_dir, storyboard)
            save_pipeline_state(
                output_dir,
                storyboard=storyboard,
                extra={
                    "image_provider": image_provider,
                    "visual_style": style,
                },
            )
            log(f"  Error pre-generando imágenes: {e}", "WARN")
            log("  El ensamblador generará las imágenes con su flujo por defecto", "WARN")
    elif strict_existing_visuals:
        log("  Ensamblado estricto: usando solo imágenes ya guardadas en el draft", "INFO")

    render_params = dict(
        storyboard_data=storyboard,
        platform=platform,
        add_subtitles=True,
        subtitle_style=effective_subtitle,
        add_overlays=True,
        apply_cinematic=False,
        transition_type=effective_transition,
        transition_duration=effective_trans_dur,
        use_real_images=True,
        use_google_images=True,
        image_provider=image_provider,
        video_provider=video_provider,
        fal_video_model=fal_video_model,
        manual_bgm_path=manual_bgm,
        allow_visual_regeneration=not strict_existing_visuals,
    )

    render_params.update(assembly_options or {})
    result = generator.assemble_video_from_storyboard(**render_params)

    if not result or not result.get("video_path"):
        log("Error ensamblando video", "ERROR")
        return None

    video_path = result["video_path"]
    storyboard["_project_path"] = str(output_dir)
    save_storyboard(output_dir, storyboard)

    # El render vive UNA sola vez, en auto_videos/output (Google Drive) con el
    # tema en el nombre. Antes se copiaba aca como short_HHMMSS.mp4 porque los
    # uploaders buscaban "el primer mp4 de la carpeta"; ahora leen la ruta
    # registrada (ver output_video_locator.find_output_video).
    save_pipeline_state(output_dir, storyboard=storyboard, video_path=str(video_path))

    log(f"Video generado: {video_path}", "OK")
    return str(video_path)


# ═══════════════════════════════════════════════════════════════════════════
# PASO 6: GENERAR THUMBNAIL
# ═══════════════════════════════════════════════════════════════════════════

def generate_thumbnail(storyboard: dict, output_dir: Path) -> str:
    """Genera thumbnail optimizado para el Short."""
    log("Generando thumbnail...", "STEP")

    try:
        from pipeline.thumbnail_pipeline import ThumbnailPipeline
        from ai.groq_client import GroqAiClient

        groq = GroqAiClient()

        # Intentar cargar clientes de imagen disponibles
        recraft_client = None
        try:
            from ai.recraft_client import RecraftClient
            recraft_client = RecraftClient()
        except Exception:
            pass
        comfyui_image_client = None
        try:
            from ai.comfyui_image_client import ComfyUiImageClient
            comfyui_image_client = ComfyUiImageClient(log_callback=lambda msg: log(msg, "INFO"))
        except Exception:
            pass

        pipeline = ThumbnailPipeline(
            project_root=str(output_dir),
            llm_client=groq,
            recraft_client=recraft_client,
            comfyui_image_client=comfyui_image_client,
        )

        project_data = {
            "topic": storyboard.get("topic", ""),
            "category": storyboard.get("category", ""),
            "script": storyboard.get("script", ""),
        }

        result = pipeline.generate_for_project(project_data)

        if result and result.get("thumbnail_path"):
            import shutil
            thumb_src = result["thumbnail_path"]
            thumb_dst = output_dir / "thumbnail.jpg"
            shutil.copy2(thumb_src, thumb_dst)
            log(f"Thumbnail generado: {thumb_dst}", "OK")
            return str(thumb_dst)

    except Exception as e:
        log(f"Thumbnail falló: {e}", "WARN")

    return None


# ═══════════════════════════════════════════════════════════════════════════
# PASO 7: GENERAR METADATA PARA YOUTUBE
# ═══════════════════════════════════════════════════════════════════════════









































# ═══════════════════════════════════════════════════════════════════════════
# PASO 8: GUARDAR RESUMEN
# ═══════════════════════════════════════════════════════════════════════════

def save_summary(output_dir: Path, idea: dict, video_path: str,
                 thumbnail_path: str, metadata: dict, storyboard: dict,
                 facebook_metadata: dict | None = None,
                 instagram_metadata: dict | None = None):
    """Guarda un resumen del Short generado."""
    output_dir = Path(output_dir)
    platform_metadata = {
        "youtube": metadata or {},
        "facebook": facebook_metadata or _safe_read_json(output_dir / FACEBOOK_METADATA_FILENAME) or {},
        "instagram": instagram_metadata or _safe_read_json(output_dir / INSTAGRAM_METADATA_FILENAME) or {},
    }
    summary = {
        "generated_at": datetime.now().isoformat(),
        "topic": idea.get("title", ""),
        "category": idea.get("category", ""),
        "justification": idea.get("justification", ""),
        "video_path": video_path,
        "thumbnail_path": thumbnail_path,
        "metadata": metadata,
        "platform_metadata": platform_metadata,
        "script": storyboard.get("script", ""),
        "segments_count": len(storyboard.get("segments", [])),
        "audio_path": storyboard.get("audio_path", ""),
    }

    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    save_pipeline_state(
        output_dir,
        status="completed",
        idea=idea,
        storyboard=storyboard,
        video_path=video_path,
        metadata=metadata,
        note="",
        extra={"platform_metadata": platform_metadata},
    )

    log(f"Resumen guardado: {summary_path}", "OK")


# ═══════════════════════════════════════════════════════════════════════════
# LISTAR VOCES DISPONIBLES
# ═══════════════════════════════════════════════════════════════════════════

def list_voices():
    """Muestra las voces TTS disponibles."""
    from pipeline.tts_generator import TextToSpeechGenerator
    tts = TextToSpeechGenerator()
    voices = tts.get_available_voices()

    print("\n️ Voces disponibles:\n")
    english_voices = {k: v for k, v in voices.items() if "en-" in k.lower() or "english" in str(v).lower()}
    other_voices = {k: v for k, v in voices.items() if k not in english_voices}

    print("── English voices ──")
    for vid, info in sorted(english_voices.items()):
        name = info.get("name", vid) if isinstance(info, dict) else str(info)
        print(f"  {vid}: {name}")

    if other_voices:
        print(f"\n── Other voices ({len(other_voices)} available) ──")
        for vid, info in sorted(list(other_voices.items())[:20]):
            name = info.get("name", vid) if isinstance(info, dict) else str(info)
            print(f"  {vid}: {name}")
        if len(other_voices) > 20:
            print(f"  ... y {len(other_voices) - 20} más")


def list_subtitle_styles():
    """Muestra los estilos de subtítulos disponibles."""
    try:
        from pipeline.dynamic_subtitles_generator import SubtitleStyle
        styles = SubtitleStyle.STYLES
        print(f"\n Estilos de subtítulos disponibles ({len(styles)}):\n")
        for key in sorted(styles.keys()):
            s = styles[key]
            anim = s.get('animation', 'none')
            karaoke = "" if s.get('karaoke') else ""
            emojis = "" if s.get('emojis') else ""
            print(f"  {key:20s} {s['name']:30s} anim={anim:8s} karaoke={karaoke} emojis={emojis}")
        print(f"\n  Estilo actual en CHANNEL_CONFIG: {CHANNEL_CONFIG.get('subtitle_style', '?')}")
        print(f"  Uso: --subtitle-style <nombre>\n")
    except Exception as e:
        print(f"Error listando estilos: {e}")


def list_transitions():
    """Muestra las transiciones disponibles."""
    transitions = [
        ("None (Direct Cut)", "Corte directo, sin transición"),
        ("Fade Smooth", "Fundido suave entre escenas"),
        ("Crossfade", "Fundido cruzado"),
        ("Zoom Transition", "Zoom in/out"),
        ("Slide Transition", "Deslizamiento a la izquierda"),
        ("Slide Right", "Deslizamiento a la derecha"),
        ("Slide Up", "Deslizamiento hacia arriba"),
        ("Slide Down", "Deslizamiento hacia abajo"),
        ("Blur Transition", "Desenfoque entre escenas"),
        ("Dissolve", "Disolución"),
        ("Wipe", "Barrido a la izquierda"),
        ("Wipe Right", "Barrido a la derecha"),
        ("Wipe Up", "Barrido hacia arriba"),
        ("Wipe Down", "Barrido hacia abajo"),
        ("Fade to Black", "Fundido a negro"),
        ("Fade to White", "Fundido a blanco"),
        ("Circle Open", "Apertura circular (iris)"),
        ("Circle Close", "Cierre circular (iris)"),
        ("Horizontal Open", "Apertura horizontal desde centro"),
        ("Horizontal Close", "Cierre horizontal hacia centro"),
        ("Diagonal", "Barrido diagonal"),
        ("Squeeze H", "Compresión horizontal"),
        ("Squeeze V", "Compresión vertical"),
        ("Digital Glitch", "Glitch digital (pixelización)"),
        ("RGB Split Glitch", "Separación de canales RGB"),
        ("Data Mosh Glitch", "Corrupción de datos"),
    ]
    print(f"\n Transiciones disponibles ({len(transitions)}):\n")
    for name, desc in transitions:
        print(f"  {name:25s} {desc}")
    print(f"\n  Transición actual en CHANNEL_CONFIG: {CHANNEL_CONFIG.get('transition_type', '?')}")
    print(f"  Uso: --transition '<nombre>' --transition-duration 0.5\n")


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

def upload_to_youtube(output_dir: Path, privacy_status: str = "private",
                      publish_at: str = None) -> dict:
    """
    Paso 9: Sube el video generado a YouTube.

    Args:
        publish_at: ISO 8601 datetime for scheduled publishing (e.g. "2026-04-10T18:00:00Z").

    Returns:
        dict con video_id, url, status o None si falla.
    """
    if publish_at:
        log(f"Subiendo video a YouTube (programado: {publish_at})...", "STEP")
    else:
        log("Subiendo video a YouTube...", "STEP")
    try:
        from publish.youtube_uploader import upload_from_metadata

        def _progress(sent, total):
            if total:
                pct = int(sent / total * 100)
                log(f"  Upload: {pct}% ({sent // (1024*1024)}MB / {total // (1024*1024)}MB)", "INFO")

        result = upload_from_metadata(
            output_dir=str(output_dir),
            privacy_status=privacy_status,
            publish_at=publish_at,
            on_progress=_progress,
        )

        log(f"Video subido: {result['url']}", "OK")
        if publish_at:
            log(f"Programado para: {publish_at}", "OK")
        else:
            log(f"Estado: {result['status']} ({privacy_status})", "OK")
        if result.get("thumbnail_set"):
            log("Thumbnail personalizado establecido", "OK")
        elif result.get("thumbnail_error"):
            log(f"Thumbnail falló: {result['thumbnail_error']}", "WARN")

        return result

    except Exception as e:
        log(f"Upload a YouTube falló: {e}", "WARN")
        import traceback
        traceback.print_exc()
        return None


def upload_to_facebook(output_dir: Path, video_state: str = "PUBLISHED",
                       publish_at: str | None = None) -> dict:
    """
    Publish the generated short to a Facebook Page Reel.

    Returns:
        dict with video_id, url, status or None if it fails.
    """
    requested_state = str(video_state or "PUBLISHED").upper()
    scheduled_publish_time = str(publish_at or "").strip() or None
    if requested_state == "DRAFT":
        scheduled_publish_time = None
    state_label = "SCHEDULED" if scheduled_publish_time else requested_state
    log(f"Subiendo video a Facebook Page ({state_label})...", "STEP")
    try:
        from publish.facebook_uploader import upload_from_metadata

        def _progress(sent, total):
            if total:
                pct = int(sent / total * 100)
                log(f"  Upload: {pct}% ({sent // (1024*1024)}MB / {total // (1024*1024)}MB)", "INFO")

        result = upload_from_metadata(
            output_dir=str(output_dir),
            video_state=state_label,
            scheduled_publish_time=scheduled_publish_time,
            on_progress=_progress,
        )

        if scheduled_publish_time:
            log(f"Facebook Reel programado para: {scheduled_publish_time}", "OK")
        elif result.get("url"):
            log(f"Facebook Reel publicado: {result['url']}", "OK")
        else:
            log(f"Facebook Reel subido con estado: {result.get('status', state_label)}", "OK")
        if result.get("permalink_url") and not result.get("url"):
            log(f"Facebook Reel link: {result['permalink_url']}", "OK")
        page_name = result.get("page_name")
        if page_name:
            log(f"Página: {page_name}", "OK")
        return result

    except Exception as e:
        log(f"Upload a Facebook falló: {e}", "WARN")
        import traceback
        traceback.print_exc()
        return None


def upload_to_instagram(output_dir: Path, publish_at: str = None, share_to_feed: bool = True) -> dict:
    """
    Publish the generated short to Instagram Reels, or queue it for VPS scheduling.

    Returns:
        dict with media_id, url, status or None if it fails.
    """
    output_dir = Path(output_dir)
    if publish_at:
        log("Programando Instagram Reel en cola VPS...", "STEP")
        try:
            from publish.vps_publish_scheduler import enqueue_job

            instagram_metadata = (
                _safe_read_json(output_dir / INSTAGRAM_METADATA_FILENAME)
                or _safe_read_json(output_dir / FACEBOOK_METADATA_FILENAME)
                or _safe_read_json(output_dir / LEGACY_METADATA_FILENAME)
                or {}
            )
            title = str(instagram_metadata.get("title") or output_dir.name).strip() or output_dir.name
            job = enqueue_job(
                folder=output_dir,
                title=title,
                publish_at=publish_at,
                instagram=True,
                origin="daily_short_pipeline",
            )
            log(f"Instagram Reel encolado para VPS: {publish_at}", "OK")
            return {
                "job_id": job.get("id"),
                "status": "queued_on_vps",
                "scheduled": True,
                "publish_at": publish_at,
                "url": None,
                "permalink_url": None,
            }
        except Exception as e:
            log(f"Programación de Instagram en VPS falló: {e}", "WARN")
            import traceback
            traceback.print_exc()
            return None

    log("Subiendo video a Instagram Reel...", "STEP")
    try:
        from publish.instagram_uploader import upload_from_metadata

        def _progress(sent, total):
            if total:
                pct = int(sent / total * 100)
                log(f"  Upload: {pct}% ({sent // (1024*1024)}MB / {total // (1024*1024)}MB)", "INFO")

        result = upload_from_metadata(
            output_dir=str(output_dir),
            share_to_feed=share_to_feed,
            on_progress=_progress,
        )

        if result.get("url"):
            log(f"Instagram Reel publicado: {result['url']}", "OK")
        else:
            log(f"Instagram Reel subido con estado: {result.get('status', 'published')}", "OK")
        username = result.get("instagram_username")
        if username:
            log(f"Cuenta: @{username}", "OK")
        return result

    except Exception as e:
        log(f"Upload a Instagram falló: {e}", "WARN")
        import traceback
        traceback.print_exc()
        return None


def upload_to_x_pipeline(output_dir: Path, youtube_url: str = None) -> bool:
    """Sube una publicación a X (Twitter) con el enlace de YouTube y el thumbnail."""
    log("Iniciando upload promocional a X...", "INFO")
    try:
        from publish.x_uploader import upload_image_to_x, post_tweet
        
        # Cargar metadata
        meta_path = output_dir / "youtube_metadata.json"
        if not meta_path.exists():
            log("No se encontró youtube_metadata.json para extraer el título.", "WARN")
            return False
            
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
            
        title = meta.get("title", "Nuevo Video")
        description = meta.get("description", "")
        # Generar texto dinámico con LLM
        from ai.groq_client import GroqAiClient
        groq = GroqAiClient()
        if groq.client:
            prompt = f"""You are a master social media copywriter for a dark historical mystery channel.
Given the following YouTube video title and description, write a striking 2-line tweet in English to promote the video.
It MUST be highly engaging, use 1-2 emojis, and end with 'Watch the full video here 👇'.
Do not use hashtags. Do not use quotes around the text. Do not output anything else but the tweet.

Title: {title}
Description: {description[:500]}
"""
            try:
                tweet_text = groq._generate(prompt).strip()
                # Limpiar comillas si el LLM las agregó
                if tweet_text.startswith('"') and tweet_text.endswith('"'):
                    tweet_text = tweet_text[1:-1]
                tweet_text += f"\n{youtube_url or 'https://youtube.com/@Stunning_Rev'}"
            except Exception as e:
                log(f"Groq tweet generation failed: {e}", "WARN")
                tweet_text = f"🚨 {title}\n\nWatch the full mystery here 👇\n{youtube_url or 'https://youtube.com/@Stunning_Rev'}"
        else:
            tweet_text = f"🚨 {title}\n\nWatch the full mystery here 👇\n{youtube_url or 'https://youtube.com/@Stunning_Rev'}"
            
        # Buscar thumbnail
        thumbnail_path = None
        for file in output_dir.iterdir():
            if file.name.startswith("thumbnail") and file.suffix in [".png", ".jpg", ".jpeg"]:
                thumbnail_path = str(file)
                break
                
        media_id = None
        if thumbnail_path:
            media_id = upload_image_to_x(thumbnail_path)
            
        success = post_tweet(tweet_text, media_id=media_id)
        if success:
            log("¡Tweet promocional publicado con éxito!", "INFO")
            return True
        else:
            log("Falló la publicación del Tweet.", "WARN")
            return False
            
    except Exception as e:
        log(f"Upload a X falló: {e}", "WARN")
        return False

def run_pipeline(topic: str = None, voice_id: str = None, upload: bool = False,
                 privacy_status: str = "private", publish_at: str = None,
                 bgm_path: str = None,
                 image_provider: str = "auto",
                 video_provider: str = "none",
                 fal_video_model: str = "kling",
                 visual_style: str = None,
                 subtitle_style: str = None, transition_type: str = None,
                 transition_duration: float = None,
                 assembly_options: dict = None) -> dict:
    """
    Ejecuta el pipeline completo para generar un Short.

    `assembly_options` va directo a `assemble_video_from_storyboard` (p. ej.
    dynamism='high', blender_shots=True, blender_quality='normal',
    blender_environment='newspaper'). Por defecto, el ensamblaje de siempre.

    Returns:
        dict con video_path, thumbnail_path, metadata, output_dir
        o None si falló.
    """
    start_time = time.time()

    print("\n" + "═" * 60)
    print(f"   DAILY SHORT PIPELINE — {get_channel_name()}")
    print("═" * 60 + "\n")

    # ── Inicializar IA ────────────────────────────────────────────────
    log("Inicializando clientes de IA...", "STEP")
    from ai.ai_factory import AIFactory
    ai_client = AIFactory.get_instance().get_llm_client()

    # ── Crear directorio de salida ────────────────────────────────────
    output_dir = create_output_dir()
    log(f"Directorio de salida: {output_dir}", "OK")

    # ── Recopilar títulos ya usados (canal + locales) ─────────────────
    log("Recopilando títulos ya usados (deduplicación)...", "STEP")
    used_titles = get_used_titles()
    if used_titles:
        log(f"  {len(used_titles)} títulos existentes cargados", "OK")
    else:
        log("  No se encontraron títulos previos", "INFO")

    # ── Paso 1: Tendencias ────────────────────────────────────────────
    if topic:
        trends = []
        ideas = []
    else:
        trends = detect_trends(ai_client)
        # ── Paso 2: Ideas ────────────────────────────────────────────
        ideas = generate_video_ideas(trends, ai_client, used_titles=used_titles)

    # ── Paso 3: Seleccionar idea ──────────────────────────────────────
    try:
        idea = select_best_idea(ideas, forced_topic=topic, used_titles=used_titles)
    except ValueError as e:
        log(str(e), "ERROR")
        return None

    # Guardar idea seleccionada
    idea_path = output_dir / "idea.json"
    with open(idea_path, "w", encoding="utf-8") as f:
        json.dump(idea, f, indent=2, ensure_ascii=False)

    # ── Paso 3.5: Pre-generation checklist ────────────────────────────
    try:
        from publish.production_checklist import run_pre_generation_checklist, format_checklist
        pre_gen = run_pre_generation_checklist(idea, daily_shorts_dir=PROJECT_DIR / "daily_shorts")
        log(format_checklist(pre_gen, "Pre-Generation Checklist"), "INFO")
        if any(not r["passed"] for r in pre_gen):
            log("Pre-generation checks have warnings — proceeding anyway", "WARN")
    except Exception as e:
        log(f"Pre-generation checklist skipped: {e}", "WARN")

    # ── Paso 4: Storyboard ────────────────────────────────────────────
    storyboard = generate_storyboard(idea, voice_id=voice_id, bgm_path=bgm_path,
                                     visual_style=visual_style,
                                     subtitle_style=subtitle_style)
    if not storyboard:
        log("Pipeline abortado: no se pudo generar storyboard", "ERROR")
        return None
    storyboard["_project_path"] = str(output_dir)
    save_storyboard(output_dir, storyboard)
    save_pipeline_state(output_dir, status="storyboard_ready", idea=idea, storyboard=storyboard)

    # ── Paso 5: Ensamblar video ───────────────────────────────────────
    video_path = assemble_video(storyboard, output_dir, image_provider=image_provider,
                               video_provider=video_provider,
                               fal_video_model=fal_video_model,
                               visual_style=visual_style,
                               subtitle_style=subtitle_style,
                               transition_type=transition_type,
                               transition_duration=transition_duration,
                               assembly_options=assembly_options)
    if not video_path:
        log("Pipeline abortado: no se pudo ensamblar video", "ERROR")
        return None
    save_pipeline_state(output_dir, status="video_ready", idea=idea, storyboard=storyboard,
                        video_path=video_path)

    # ── Paso 6: Thumbnail ─────────────────────────────────────────────
    thumbnail_path = None
    log("Omitiendo thumbnail en Daily Shorts (no es necesario para Shorts verticales)", "INFO")

    # ── Paso 7: Metadata ──────────────────────────────────────────────
    metadata, facebook_metadata, instagram_metadata = generate_platform_metadata(storyboard, output_dir)

    # ── Paso 7.5: Pre-publish checklist ───────────────────────────────
    try:
        from publish.production_checklist import run_pre_publish_checklist, format_checklist
        pre_pub = run_pre_publish_checklist(storyboard, video_path=video_path, metadata=metadata)
        log(format_checklist(pre_pub, "Pre-Publish Checklist"), "INFO")
        failed = [r for r in pre_pub if not r["passed"]]
        if failed:
            log(f"Pre-publish: {len(failed)} check(s) failed — review before uploading", "WARN")
    except Exception as e:
        log(f"Pre-publish checklist skipped: {e}", "WARN")

    # ── Paso 8: Resumen ───────────────────────────────────────────────
    save_summary(output_dir, idea, video_path, thumbnail_path, metadata, storyboard,
                 facebook_metadata=facebook_metadata,
                 instagram_metadata=instagram_metadata)

    # ── Paso 8.5: Hechos verificados (script_fact_check) ──────────────
    # Nada con afirmaciones falsas o inventadas se sube (Trafalgar 2026-09-23).
    if upload:
        try:
            from ai.script_fact_check import upload_gate
            facts_ok, _fc_report, _fc_msg = upload_gate(storyboard, log=lambda m: log(m, "INFO"))
            save_storyboard(output_dir, storyboard)   # deja el informe junto al proyecto
            if facts_ok:
                log(_fc_msg, "INFO")
            else:
                log("Hechos: la narracion tiene afirmaciones falsas o inventadas. NO se sube:\n" + _fc_msg,
                    "ERROR")
                upload = False
        except Exception as e:
            log(f"Verificacion de hechos omitida: {e}", "WARN")

    # ── Paso 9: Upload a YouTube (opcional) ───────────────────────────
    upload_result = None
    if upload:
        upload_result = upload_to_youtube(output_dir, privacy_status=privacy_status,
                                          publish_at=publish_at)
                                          
    # ── Paso 10: Upload a X (Twitter) ──────────────────────────────
    if upload and upload_result and upload_result.get("status") in ["uploaded", "published", "scheduled"]:
        youtube_url = upload_result.get("url")
        upload_to_x_pipeline(output_dir, youtube_url)

    # ── Resultado ─────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print("\n" + "=" * 60)
    print("  SHORT GENERADO EXITOSAMENTE")
    print("=" * 60)
    print(f"  Carpeta:    {output_dir}")
    print(f"  Video:      {video_path}")
    if thumbnail_path:
        print(f"  Thumbnail:  {thumbnail_path}")
    print(f"  Titulo:     {metadata.get('title', '?')}")
    print(f"  Tiempo:     {minutes}m {seconds}s")
    print(f"  YT meta:    {output_dir / YOUTUBE_METADATA_FILENAME}")
    print(f"  FB meta:    {output_dir / FACEBOOK_METADATA_FILENAME}")
    print(f"  IG meta:    {output_dir / INSTAGRAM_METADATA_FILENAME}")
    if upload_result:
        print(f"  YouTube:    {upload_result.get('url', '?')}")
        print(f"  Estado:     {upload_result.get('status', '?')} ({privacy_status})")
    else:
        if not upload:
            print("  Sube el video a YouTube Studio manualmente")
            print("     Copia titulo, descripcion y tags desde youtube_metadata.json")
    print("=" * 60 + "\n")

    return {
        "video_path": video_path,
        "thumbnail_path": thumbnail_path,
        "metadata": metadata,
        "facebook_metadata": facebook_metadata,
        "output_dir": str(output_dir),
        "upload_result": upload_result,
    }


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=f"Pipeline automatizado para generar Shorts diarios — {get_channel_name()}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--topic", "-t", type=str, default=None,
                        help="Forzar un tema específico (omite detección de tendencias)")
    parser.add_argument("--count", "-c", type=int, default=1,
                        help="Cantidad de Shorts a generar (default: 1)")
    parser.add_argument("--voice", "-v", type=str, default=None,
                        help="ID de voz TTS (ej: en-US-GuyNeural)")
    parser.add_argument("--bgm", type=str, default=None,
                        help="Ruta a archivo de audio para música de fondo (mp3/wav)")
    parser.add_argument("--image-provider", type=str, default="auto",
                        choices=[
                            "auto", "recraft", "fal", "flux_dev", "flux_schnell",
                            "google_ai", "comfy_schnell", "comfy_sdxl", "comfy_dev",
                        ],
                        help=(
                            "Proveedor de generacion de imagenes. "
                            "'flux_dev' = FAL Flux dev (calidad, $0.025/img). "
                            "'flux_schnell' = FAL Flux schnell (rapido, $0.003/img). "
                            "'comfy_schnell' = ComfyUI/Vast.ai FLUX Schnell (4 steps, rapido). "
                            "'comfy_dev' = ComfyUI/Vast.ai FLUX Dev (25 steps, alta calidad). "
                            "'comfy_sdxl' = ComfyUI/Vast.ai SDXL para lineart/coloring. "
                            "'fal' = alias legacy (usa FLUX schnell). "
                            "Default: auto/recraft."
                        ))
    parser.add_argument("--video-provider", type=str, default="none",
                        choices=["none", "fal", "runway"],
                        help=(
                            "Proveedor de video (opcional, I2V). "
                            "'fal' usa Kling/Luma (image-to-video) con la imagen generada previamente. "
                            "'runway' usa Gen-3/Veo (text-to-video). "
                            "Default: none (imagen estatica + Ken Burns)."
                        ))
    parser.add_argument("--fal-video-model", type=str, default="kling",
                        choices=["kling", "kling-pro", "luma"],
                        help=(
                            "Modelo de video en FAL (solo aplica si --video-provider=fal). "
                            "'kling' = v1.5 Standard (~$0.48/5s). "
                            "'kling-pro' = v1.5 Pro (~$0.95/5s). "
                            "'luma' = Dream Machine (~$0.50/5s). "
                            "Default: kling."
                        ))
    parser.add_argument("--provider", type=str, default=None,
                        choices=["fal"],
                        help=(
                            "Preset rapido de proveedores. "
                            "'--provider fal' equivale a '--image-provider flux_dev "
                            "--video-provider fal --fal-video-model kling' "
                            "(pensado para @Stunning-Revelations)."
                        ))
    parser.add_argument("--style", type=str, default=None,
                        help="Estilo visual de Recraft (ej: Photorealism, Illustration, Noir)")
    parser.add_argument("--upload", "-u", action="store_true",
                        help="Subir automáticamente a YouTube después de generar")
    parser.add_argument("--privacy", type=str, default="private",
                        choices=["private", "unlisted", "public"],
                        help="Estado de privacidad del video (default: private)")
    parser.add_argument("--schedule", action="store_true",
                        help="Programar publicación en horario óptimo (2PM ET, L-S)")
    parser.add_argument("--publish-at", type=str, default=None,
                        help="Programar publicación en fecha/hora específica (ISO 8601, ej: 2026-04-10T18:00:00Z)")
    parser.add_argument("--subtitle-style", type=str, default=None,
                        help="Estilo de subtítulos (ej: hormozi, mrbeast, tiktok, horror, glitch, military, etc.)")
    parser.add_argument("--transition", type=str, default=None,
                        help="Tipo de transición (ej: 'Fade Smooth', 'Circle Open', 'Squeeze H', etc.)")
    parser.add_argument("--transition-duration", type=float, default=None,
                        help="Duración de transición en segundos (0.1-2.0)")
    parser.add_argument("--dynamism", choices=["off", "moderate", "high"], default="off",
                        help="Composicion por escena (pantalla dividida, retrato, punch-in...)")
    parser.add_argument("--blender", action="store_true",
                        help="Toma 3D con Blender en el momento fuerte (tarda minutos)")
    parser.add_argument("--blender-quality", choices=["draft", "normal", "high"], default="normal")
    parser.add_argument("--blender-env", choices=["auto", "desk", "corkboard", "crt_tv", "newspaper"],
                        default="auto", help="Ambiente de la toma 3D (auto = segun la escena)")
    parser.add_argument("--list-voices", action="store_true",
                        help="Listar voces TTS disponibles y salir")
    parser.add_argument("--list-subtitle-styles", action="store_true",
                        help="Listar estilos de subtítulos disponibles y salir")
    parser.add_argument("--list-transitions", action="store_true",
                        help="Listar transiciones disponibles y salir")

    from channel.channel_profiles import CHANNELS, DEFAULT_CHANNEL, select_channel
    parser.add_argument('--channel', choices=list(CHANNELS), default=DEFAULT_CHANNEL)
    args = parser.parse_args()
    select_channel(args.channel)
    from channel.channel_strategy import get_channel_strategy
    if get_channel_strategy().get('production_policy', {}).get('shorts_campaign_enabled') is False:
        parser.error('Este canal está en piloto microdocumentary. Usa long_form_builder.py --format micro_documentary --channel ' + args.channel)

    if args.list_voices:
        list_voices()
        return

    if args.list_subtitle_styles:
        list_subtitle_styles()
        return

    if args.list_transitions:
        list_transitions()
        return

    # --- Resolver preset '--provider' ---------------------------------
    # '--provider fal' es un atajo para configurar el stack completo de
    # FAL.AI (Flux dev + Kling Standard I2V) sin tener que pasar 3 flags.
    # Respeta valores explicitos del usuario si los pasa tambien.
    if args.provider == "fal":
        if args.image_provider in (None, "auto"):
            args.image_provider = "flux_dev"
        if args.video_provider in (None, "none"):
            args.video_provider = "fal"
        # fal_video_model ya tiene default 'kling', no hace falta tocarlo

    # Normalizar: 'fal' legacy (image) sigue funcionando como alias de flux_schnell
    if args.image_provider == "fal":
        args.image_provider = "flux_schnell"

    # Resolve scheduling
    do_upload = args.upload or args.schedule or args.publish_at
    if args.publish_at:
        base_publish_at = args.publish_at
    elif args.schedule:
        base_publish_at = "__auto__"
    else:
        base_publish_at = None

    results = []
    for i in range(args.count):
        if args.count > 1:
            print(f"\n{'━' * 60}")
            print(f"  Generando Short {i + 1} de {args.count}")
            print(f"{'━' * 60}")

        # For batch scheduling, offset each short by 1 day
        if base_publish_at == "__auto__":
            from publish.youtube_uploader import get_next_optimal_publish_time
            publish_at = get_next_optimal_publish_time(slot_index=i)
        else:
            publish_at = base_publish_at

        result = run_pipeline(topic=args.topic, voice_id=args.voice,
                              upload=do_upload, privacy_status=args.privacy,
                              publish_at=publish_at,
                              bgm_path=args.bgm, image_provider=args.image_provider,
                              video_provider=args.video_provider,
                              fal_video_model=args.fal_video_model,
                              visual_style=args.style,
                              subtitle_style=args.subtitle_style,
                              transition_type=args.transition,
                              transition_duration=args.transition_duration,
                              assembly_options=dict(
                                  dynamism=args.dynamism, blender_shots=args.blender,
                                  blender_quality=args.blender_quality,
                                  blender_environment=args.blender_env))
        if result:
            results.append(result)

    # Resumen final
    if args.count > 1:
        print(f"\n{'═' * 60}")
        print(f"   RESUMEN: {len(results)}/{args.count} Shorts generados")
        print(f"{'═' * 60}")
        for r in results:
            print(f"   {r['metadata'].get('title', '?')}")
            print(f"      {r['output_dir']}")
        print()


if __name__ == "__main__":
    main()


# Import tardio para evitar import circular: este modulo define todo primero.
from pipeline.daily_short_metadata import (
    generate_youtube_metadata, generate_facebook_metadata, generate_instagram_metadata,
    generate_platform_metadata, generate_metadata,
)
