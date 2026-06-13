import re

content = open('daily_short_pipeline.py', 'r', encoding='utf-8').read()

patch = '''def create_output_dir() -> Path:
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


# ═══════════════════════════════════════════════════════════════════════════
# DEDUPLICACIÓN: recopilar títulos ya usados
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_title(title: str) -> str:
    """Normaliza un título para comparación (minúsculas, sin puntuación extra)."""
    import re
    t = title.lower().strip()
    t = re.sub(r'[^\\w\\s]', ' ', t)      # quitar puntuación
    t = re.sub(r'\\s+', ' ', t).strip()   # colapsar espacios
    
    # Remover stop-words comunes en inglés y español para mejorar la precisión de similitud (Jaccard)
    stop_words = {"the", "a", "an", "of", "in", "and", "to", "is", "for", "on", "with", "at", "by", "from", 
                  "el", "la", "los", "las", "un", "una", "de", "en", "y", "por", "con", "para", "su"}
    words = [w for w in t.split() if w not in stop_words]
    return " ".join(words)


def _titles_are_similar(title_a: str, title_b: str, threshold: float = 0.55) -> bool:
    """Compara dos títulos por similitud (Jaccard sobre palabras). Umbral por defecto 55%."""
    words_a = set(_normalize_title(title_a).split())
    words_b = set(_normalize_title(title_b).split())
    if not words_a or not words_b:
        return False
    intersection = words_a & words_b
    union = words_a | words_b
    similarity = len(intersection) / len(union)
    return similarity >= threshold


def find_similar_title(title: str, used_titles: list, threshold: float = 0.55) -> str | None:
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
        from youtube_channel_analyzer import YouTubeChannelAnalyzer
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

    return unique'''

start_idx = content.find('def create_output_dir() -> Path:')
end_idx = content.find('def detect_trends')

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + patch + '\n\n\n# ═══════════════════════════════════════════════════════════════════════════\n# PASO 1: DETECTAR TENDENCIAS\n# ═══════════════════════════════════════════════════════════════════════════\n\n' + content[end_idx:]
    open('daily_short_pipeline.py', 'w', encoding='utf-8').write(content)
    print('Fixed!')
else:
    print('Could not find start or end index')
