# -*- coding: utf-8 -*-
"""Tags de YouTube: investigados (no inventados) y bien insertados.

Lo que se encontro el 2026-09-22 mirando los tags GUARDADOS en los 33 videos del
canal (Data API):
  - 6 videos sin ningun tag.
  - Un tag gigante: 'Shorts Great Zimbabwe Great Zimbabwe history Shona Dry stone...'
    (el campo del Metadata Studio se partia solo por comas).
  - Hashtags como tags: '#shorts', 'AncientHistory', 'Baghdad1258', 'MongolCatapults'.
  - Relleno: ['documentary', 'history'] (el microdocumental los escribia fijos).
  - El uploader recortaba `tags[:500]` = 500 TAGS, no 500 caracteres, y metia
    'Shorts' primero en cada short.
  - Todos los tags salian de un LLM al que se le pedia "15 tags muy buscados",
    sin ningun dato de busqueda.

Este modulo tiene dos partes:

1. `finalize_youtube_tags(tags)` -- la puerta final por la que pasa todo lo que se
   sube (cualquier camino). Puro.

2. `research_tags(topic, title, script, ...)` -- lo que hacen vidIQ/TubeBuddy:
     palabra clave principal y entidades del guion
     -> autocompletado de YouTube (lo que la gente escribe = demanda)
     -> tags de los videos que rankean para esa busqueda (consenso, ponderado por vistas)
     -> filtros: marcas ajenas, homonimos ('hannibal lecter'), basura, relevancia
        contra el guion
     -> puntaje, con la evidencia de cada tag.
   Las fuentes de red se inyectan (`suggest_fn`, `competitor_fn`) para testear sin red.

    .venv\\Scripts\\python.exe youtube_tags.py "Hannibal crossing the Alps"   # prueba en vivo

Ver `test_youtube_tags.py`.
"""

from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from typing import Any, Callable, Iterable, Optional

# YouTube: 500 caracteres para la lista entera; las comas entre tags cuentan, y un
# tag con espacios cuenta como si llevara comillas (+2).
YOUTUBE_TAGS_MAX_CHARS = 500
MAX_TAG_CHARS = 60           # mas largo que esto es un bloque pegado, no un tag
MAX_TAG_WORDS = 7

_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "by", "with", "from", "into", "vs",
    "is", "was", "were", "are", "be", "how", "why", "what", "when", "who", "did", "does", "do", "that",
    "this", "his", "her", "its", "their", "it", "he", "she", "they", "we", "you", "i", "as", "after",
    "before", "about", "over", "under", "de", "la", "el", "los", "las", "del", "y", "en", "un", "una",
}
# Tags que no describen el video o que YouTube ignora (el #Shorts va en titulo/descripcion).
_JUNK_TAGS = {
    "shorts", "short", "youtube shorts", "yt shorts", "shorts video", "video", "videos", "viral", "fyp",
    "trending", "subscribe", "reaction", "trailer", "gameplay", "game", "games", "funny", "meme", "memes",
    "full episode", "full episodes", "watch", "new", "2024", "2025", "2026", "facts", "history shorts",
}
_ALLOWED_CHARS = re.compile(r"[^0-9a-z'&\- ]+")
# Juegos y franquicias que aparecen en los tags de la competencia de historia militar
# ('world of warships' se colo en Kaiten por consenso de canales el 2026-09-22).
_MEDIA_RE = re.compile(
    r"\b(world of (warships|tanks|warplanes)|war thunder|total war|hearts of iron|battlefield|call of duty|"
    r"age of empires|assassin'?s creed|civilization (v|vi|vii)|company of heroes|enlisted|gameplay|"
    r"minecraft|fortnite|roblox|netflix|trailer|movie|film)\b")


def _fold(text: str) -> str:
    """minusculas, sin tildes (Çatalhöyük -> catalhoyuk)."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


def normalize_tag(tag: Any) -> str:
    """Forma canonica de un tag: sin '#', sin simbolos raros, espacios simples, minusculas."""
    t = _fold(str(tag or "")).replace("#", " ").replace("_", " ")
    # CamelCase de hashtag -> palabras ('AncientHistory' ya viene en minusculas aca, se
    # separa antes de doblar en `split_tag_field`)
    t = _ALLOWED_CHARS.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip(" -'")


def _uncamel(text: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(text or ""))


def split_tag_field(value: Any) -> list[str]:
    """Acepta lista o texto (comas, saltos de linea, punto y coma, o '#hashtags')."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    out: list[str] = []
    for item in items:
        text = str(item or "")
        if "#" in text and "," not in text:
            parts = [p for p in text.split("#") if p.strip()]
        else:
            parts = re.split(r"[,\n;]+", text)
        for p in parts:
            p = _uncamel(p.strip())
            if p:
                out.append(p)
    return out


def counted_length(tags: Iterable[str]) -> int:
    """Largo como lo cuenta YouTube: comas entre tags y +2 por tag con espacios."""
    tags = list(tags)
    if not tags:
        return 0
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + (len(tags) - 1)


def finalize_youtube_tags(tags: Any, max_chars: int = YOUTUBE_TAGS_MAX_CHARS,
                          drop: Iterable[str] = ()) -> list[str]:
    """La puerta final: limpia, deduplica, conserva el orden y respeta el presupuesto.

    - Separa bien (comas, saltos, hashtags) y saca '#', '<', '>'.
    - Descarta bloques pegados (> MAX_TAG_CHARS o > MAX_TAG_WORDS) y basura
      ('shorts', 'viral', 'video'...).
    - Deduplica sin distinguir mayusculas/tildes, conservando el PRIMERO: el orden
      es el de relevancia, no alfabetico.
    - Agrega mientras entre en `max_chars` contado a la YouTube; si uno no entra,
      prueba con los siguientes (mas cortos).
    """
    banned = _JUNK_TAGS | {normalize_tag(d) for d in drop}
    seen: set[str] = set()
    out: list[str] = []
    for raw in split_tag_field(tags):
        tag = normalize_tag(raw)
        if len(tag) < 2 or tag in banned or tag in seen:
            continue
        if len(tag) > MAX_TAG_CHARS or len(tag.split()) > MAX_TAG_WORDS:
            continue
        if counted_length(out + [tag]) > max_chars:
            continue
        seen.add(tag)
        out.append(tag)
    return out


# ----------------------------------------------------------------------------
# Investigacion
# ----------------------------------------------------------------------------
_ENTITY_RE = re.compile(
    r"\b([A-Z][\w'\-]+(?:\s+(?:of|the|de|del|la|von|van|al|el)\s+[A-Z][\w'\-]+|\s+[A-Z][\w'\-]+)*)")
_WEAK_STARTERS = {"The", "In", "On", "At", "It", "He", "She", "They", "This", "That", "When", "But", "And",
                  "A", "An", "By", "For", "Its", "His", "Her", "Their", "After", "Before", "As", "One", "Two",
                  "How", "Why", "What", "Who", "There", "Then", "Now", "Today", "Yet", "Still", "Even", "El",
                  "La", "Los", "Las", "En", "Un", "Una"}


def _depossess(word: str) -> str:
    return re.sub(r"'s?$", "", word)


def _stem(word: str) -> str:
    """Plural ingles simple: 'submarines' -> 'submarine', 'casts' -> 'cast' ('pass' queda)."""
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def content_tokens(text: str) -> list[str]:
    """Palabras con contenido (sin stopwords, sin posesivos, sin numeros sueltos, sin plural)."""
    out = []
    for w in normalize_tag(text).split():
        w = _depossess(w)
        if len(w) > 1 and w not in _STOPWORDS and not w.isdigit():
            out.append(_stem(w))
    return out


def extract_entities(title: str, script: str, limit: int = 6) -> list[str]:
    """Nombres propios del GUION (y el tema), por frecuencia; el titulo solo suma peso.

    No se extraen del titulo por mayusculas: un titulo en Title Case ("Rations
    Across the Alps") no distingue nombres propios de palabras comunes.
    """
    counts: dict[str, float] = {}
    title_folded = normalize_tag(title)
    # "Little St. Bernard" no se corta en el punto de la abreviatura.
    script = re.sub(r"\b(St|Mt|Ft|Dr|Gen|Adm|Col|Lt|Sgt)\.\s", r"\1 ", script or "")
    for m in _ENTITY_RE.finditer(script):
        words = m.group(1).strip().split()
        while words and words[0] in _WEAK_STARTERS:
            words = words[1:]
        if not words:
            continue
        key = " ".join(_depossess(w) for w in normalize_tag(" ".join(words)).split())
        key = re.sub(r"\s+", " ", key).strip()
        if len(key) < 3 or key in _STOPWORDS or key.isdigit():
            continue
        counts[key] = counts.get(key, 0.0) + (3.0 if key in title_folded else 1.0)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0].split())))
    return [k for k, _ in ranked[:limit]]


def _clean_query(text: str) -> str:
    """Tema/titulo -> consulta: sin coletilla, sin fechas ni numeros, sin posesivos."""
    core = re.split(r"[:|\u2014\u2013(]|\s-\s", str(text or ""))[0]
    core = normalize_tag(core)
    words = [_depossess(w) for w in core.split()]
    words = [w for w in words if w and not re.fullmatch(r"\d[\d ]*|bc|bce|ad|ce", w)]
    # Solo el articulo inicial: 'crossing of the alps' es lo que la gente escribe.
    while words and words[0] in {"the", "a", "an", "el", "la", "los", "las"}:
        words = words[1:]
    return " ".join(words)


def subject_token(topic: str, title: str = "") -> str:
    """El sujeto del video: el primer nombre propio del tema ('kaiten', 'castle bravo', 'pompeii');
    si el tema no tiene, su primera palabra con contenido."""
    for source in (topic, title):
        for m in _ENTITY_RE.finditer(source or ""):
            words = m.group(1).strip().split()
            while words and words[0] in _WEAK_STARTERS:
                words = words[1:]
            key = " ".join(_depossess(w) for w in normalize_tag(" ".join(words)).split()).strip()
            if len(key) >= 3 and not key.isdigit() and key not in _STOPWORDS:
                return key
    for source in (topic, title):
        words = [_depossess(w) for w in normalize_tag(_clean_query(source)).split() if w not in _STOPWORDS]
        if words:
            return words[0]
    return ""


def subject_context_words(subject: str, script: str, window: int = 6, limit: int = 2) -> list[str]:
    """Palabras que definen al sujeto en el guion: 'The Kaiten was a manned torpedo' -> manned, torpedo."""
    if not subject or not script:
        return []
    words = normalize_tag(script).split()
    subj = subject.split()
    for i in range(len(words) - len(subj) + 1):
        if [_depossess(w) for w in words[i:i + len(subj)]] == subj:
            after = [_depossess(w) for w in words[i + len(subj):i + len(subj) + window]]
            picked = [w for w in after if w not in _STOPWORDS and len(w) > 3 and not w.isdigit()]
            return picked[:limit]
    return []


def seed_queries(topic: str, title: str, entities: list[str], limit: int = 10, script: str = "") -> list[str]:
    """Consultas semilla para el autocompletado.

    Tema, titulo y entidades del guion, mas el SUJETO combinado con una palabra que lo
    desambigua: el autocompletado de 'kaiten' esta tomado por un videojuego; el de
    'kaiten torpedo' / 'kaiten suicide' / 'kaiten history' devuelve lo que se busca
    sobre el tema real.
    """
    seeds: list[str] = []

    def add(q: str) -> None:
        words = q.split()[:5]                      # un tema largo se acorta, no se descarta
        while words and words[-1] in _STOPWORDS:
            words = words[:-1]
        q = " ".join(words).strip()
        if q and len(q) >= 3 and q not in seeds:
            seeds.append(q)

    subject = subject_token(topic, title)
    for q in [_clean_query(topic), _clean_query(title)] + list(entities[:3]):
        add(q)
    if subject:
        for w in subject_context_words(subject, script):
            add(f"{subject} {w}")
        extra = [t for t in content_tokens(f"{topic} {title}") if t not in subject.split()]
        for w in extra[:2]:
            add(f"{subject} {w}")
        add(f"{subject} history")
    return seeds[:limit]


def pick_main_keyword(suggestions: dict[str, float], corpus: set[str], fallback: str,
                      subject: str = "") -> str:
    """La busqueda principal: una sugerencia REAL del autocompletado, relevante al guion.

    Entre las sugerencias cuyas palabras estan todas en el guion/tema, gana la de
    mejor rango ponderada por especificidad (2-5 palabras): 'hannibal crossing the
    alps' antes que 'hannibal' (ambiguo: Lecter) o que una frase de 7 palabras.
    """
    best, best_score = "", 0.0
    subj_toks = set(content_tokens(subject)) if subject else set()

    def valid(sug: str) -> bool:
        toks = content_tokens(sug)
        return bool(toks) and all(t in corpus for t in toks) and not _MEDIA_RE.search(sug)

    naming_subject = [s for s in suggestions if valid(s) and len(s.split()) >= 2
                      and subj_toks and subj_toks <= set(content_tokens(s))]
    pool = naming_subject or list(suggestions)
    for sug in pool:
        rank_score = suggestions[sug]
        toks = content_tokens(sug)
        if not valid(sug):
            continue
        if _MEDIA_RE.search(sug):
            continue
        n = len(sug.split())
        specificity = {1: 0.3, 2: 0.9, 3: 1.0, 4: 1.0, 5: 0.9}.get(n, 0.6)   # 1 palabra = ambigua
        score = rank_score * specificity
        if subj_toks and subj_toks <= set(toks):
            score *= 1.6                           # nombra al sujeto del video
        if score > best_score:
            best, best_score = sug, score
    return best or fallback


def main_keyword(topic: str, title: str, entities: list[str]) -> str:
    """Sin red: el tema limpio si nombra una entidad del guion; si no, la entidad principal."""
    for source in (topic, title):
        core = _clean_query(source)
        if core and any(e in core or core in e for e in entities[:3]):
            return core
    return entities[0] if entities else _clean_query(topic or title)


def _suggest_rank_score(rank: int, total: int = 10) -> float:
    return max(0.1, (total - rank) / float(total))


def gather_research(topic: str, title: str = "", script: str = "", *,
                    suggest_fn: Optional[Callable[[str], list[str]]] = None,
                    competitor_fn: Optional[Callable[[str], list[dict[str, Any]]]] = None,
                    log: Callable[[str], None] = print) -> dict[str, Any]:
    """La investigacion de palabras clave, una sola vez por video (tags Y titulo la usan).

    Devuelve {keyword, subject, entities, corpus, suggestions {texto: puntaje},
    suggest_ranks {texto: rango}, competitors [{title, channel, views, tags}], sources_ok}.
    Cuesta ~101 unidades de cuota (1 search + 1 videos.list); el autocompletado es gratis.
    """
    suggest_fn = suggest_fn or youtube_autocomplete
    competitor_fn = competitor_fn or competitor_videos
    corpus = set(content_tokens(f"{topic} {title} {script}"))
    entities = extract_entities(title, f"{topic}. {script}")
    sources_ok = {"autocomplete": False, "competitors": False}
    suggestions: dict[str, float] = {}
    ranks: dict[str, int] = {}
    for seed in seed_queries(topic, title, entities, script=script):
        try:
            sugs = suggest_fn(seed) or []
            sources_ok["autocomplete"] = sources_ok["autocomplete"] or bool(sugs)
        except Exception as exc:
            log(f"   [Investigacion] autocompletado fallo para '{seed}': {exc}")
            sugs = []
        for rank, sug in enumerate(sugs[:10]):
            key = normalize_tag(sug)
            if len(key) < 3:
                continue
            score = _suggest_rank_score(rank)
            if score > suggestions.get(key, 0.0):
                suggestions[key] = score
                ranks[key] = rank + 1
    subject = subject_token(topic, title)
    keyword = pick_main_keyword(suggestions, corpus, main_keyword(topic, title, entities), subject=subject)
    try:
        competitors = competitor_fn(keyword) or []
        sources_ok["competitors"] = bool(competitors)
    except Exception as exc:
        log(f"   [Investigacion] busqueda de competencia fallo: {exc}")
        competitors = []
    return {"keyword": keyword, "subject": subject, "entities": entities, "corpus": corpus,
            "suggestions": suggestions, "suggest_ranks": ranks, "competitors": competitors,
            "sources_ok": sources_ok}


def research_tags(topic: str, title: str = "", script: str = "", draft_tags: Any = None, *,
                  suggest_fn: Optional[Callable[[str], list[str]]] = None,
                  competitor_fn: Optional[Callable[[str], list[dict[str, Any]]]] = None,
                  brand_tag: str = "", own_channel_names: Iterable[str] = (),
                  max_chars: int = YOUTUBE_TAGS_MAX_CHARS, log: Callable[[str], None] = print,
                  research: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Tags con evidencia. Devuelve {tags, main_keyword, evidence, summary, sources_ok}.

    suggest_fn(query)    -> sugerencias del autocompletado de YouTube, en orden.
    competitor_fn(query) -> [{title, channel, views, tags}] de los videos que rankean.
    research             -> lo de gather_research() si ya se hizo (no se repite la cuota).
    """
    if research is None:
        research = gather_research(topic, title, script, suggest_fn=suggest_fn,
                                   competitor_fn=competitor_fn, log=log)
    corpus = research["corpus"]
    entities = research["entities"]
    subject = research["subject"]
    keyword = research["keyword"]
    sources_ok = research["sources_ok"]
    cands: dict[str, dict[str, Any]] = {}

    def cand(tag: str) -> Optional[dict[str, Any]]:
        key = normalize_tag(tag)
        if len(key) < 3 or key in _JUNK_TAGS or len(key) > MAX_TAG_CHARS or len(key.split()) > MAX_TAG_WORDS:
            return None
        return cands.setdefault(key, {"suggest": 0.0, "suggest_rank": None, "channels": set(), "views": 0,
                                      "weight": 0.0, "draft": False})

    # 1) Autocompletado: demanda real.
    for key, score in research["suggestions"].items():
        c = cand(key)
        if c is not None and score > c["suggest"]:
            c["suggest"], c["suggest_rank"] = score, research["suggest_ranks"].get(key)

    # 2) Competencia: los videos que rankean para la palabra clave.
    competitor_channels: set[str] = set()
    for v in research["competitors"]:
        ch = normalize_tag(v.get("channel", ""))
        if ch:
            competitor_channels.add(ch)
        w = math.log10(float(v.get("views") or 0) + 10.0)
        for t in split_tag_field(v.get("tags") or []):
            c = cand(t)
            if c is None:
                continue
            if ch not in c["channels"]:
                c["channels"].add(ch)
                c["weight"] += w
                c["views"] += int(v.get("views") or 0)

    # 3) Borrador (LLM / Metadata Studio / microdoc): candidatos de baja prioridad.
    for t in split_tag_field(draft_tags):
        c = cand(t)
        if c is not None:
            c["draft"] = True

    # 4) Filtros y puntaje.
    own = {normalize_tag(n) for n in own_channel_names if n}
    entity_set = {e for e in entities if len(e.split()) == 1}
    brands = {b for b in competitor_channels if len(b) >= 4} - own
    keyword_tokens = set(content_tokens(keyword))
    scored = []
    for tag, c in cands.items():
        toks = content_tokens(tag)
        if not toks:
            continue
        if any(b and (b in tag or tag in b) for b in brands):
            continue                                   # 'history hit youtube', 'oversimplified'
        if _MEDIA_RE.search(tag):
            continue                                   # 'world of warships', 'total war rome 2'
        in_corpus = sum(1 for t in toks if t in corpus)
        # Todas las palabras en el guion/tema. Excepcion: consenso FUERTE de la
        # competencia (3+ canales) con la mitad de las palabras en el guion. Con 2
        # canales se colaba 'hannibal lecter' al buscar 'hannibal' a secas.
        strong = len(c["channels"]) >= 3
        if in_corpus < len(toks) and not (strong and in_corpus * 2 >= len(toks)):
            continue
        # Una palabra suelta solo si es un nombre propio completo del guion o el sujeto:
        # 'blast', 'castle', 'bikini', 'japanese' no traen a nadie a este video.
        if len(toks) == 1 and len(tag.split()) <= 2 and tag not in entity_set and tag != subject:
            continue
        consensus = len(c["channels"]) >= 2
        score = (1.5 * c["suggest"]
                 + 1.0 * min(1.0, c["weight"] / 6.0)
                 + (0.4 if consensus else 0.0)
                 + (0.25 if c["draft"] else 0.0)
                 + (0.5 if keyword_tokens and keyword_tokens <= set(toks) else 0.0))
        if tag == keyword:
            score += 10.0
        scored.append((score, tag, c))
    scored.sort(key=lambda x: (-x[0], len(x[1])))

    # Casi-duplicados gastan presupuesto sin sumar busquedas: 'japanese submarine' /
    # 'japanese submarines', 'roman empire' / 'the roman empire', 'alps crossing' /
    # 'crossing the alps'. Se queda el de mejor puntaje (mismas palabras, sin plural).
    seen_keys: set = set()
    deduped = []
    for item in scored:
        key = frozenset(content_tokens(item[1]))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
    scored = deduped

    ordered = [t for _, t, _ in scored]
    if keyword and keyword not in ordered:
        ordered.insert(0, keyword)
    # La marca propia tiene lugar reservado: se completa el resto y ella va al final.
    brand = normalize_tag(brand_tag) if brand_tag else ""
    reserve = (len(brand) + (2 if " " in brand else 0) + 1) if brand else 0
    tags = finalize_youtube_tags([t for t in ordered if t != brand], max_chars=max_chars - reserve)
    if brand:
        tags = finalize_youtube_tags(tags + [brand], max_chars=max_chars)

    evidence = {}
    for score, tag, c in scored:
        if tag in tags:
            evidence[tag] = {"score": round(score, 2), "suggest_rank": c["suggest_rank"],
                             "competitor_channels": len(c["channels"]), "competitor_views": c["views"],
                             "draft": c["draft"]}
    n_sug = sum(1 for e in evidence.values() if e["suggest_rank"])
    n_comp = sum(1 for e in evidence.values() if e["competitor_channels"])
    n_draft = sum(1 for e in evidence.values() if e["draft"] and not e["suggest_rank"] and not e["competitor_channels"])
    summary = (f"{len(tags)} tags ({counted_length(tags)}/{max_chars}) | palabra clave: '{keyword}' | "
               f"autocompletado {n_sug}, competencia {n_comp}, solo borrador {n_draft}")
    return {"tags": tags, "main_keyword": keyword, "entities": entities, "evidence": evidence,
            "summary": summary, "sources_ok": sources_ok}


# ----------------------------------------------------------------------------
# Fuentes de red
# ----------------------------------------------------------------------------
def youtube_autocomplete(query: str, lang: str = "en", timeout: int = 15) -> list[str]:
    """Sugerencias del buscador de YouTube (el mismo endpoint que usa el navegador)."""
    import requests
    r = requests.get("https://suggestqueries.google.com/complete/search",
                     params={"client": "firefox", "ds": "yt", "q": query, "hl": lang}, timeout=timeout)
    data = json.loads(r.text)
    return [str(s) for s in (data[1] if isinstance(data, list) and len(data) > 1 else [])]


def competitor_videos(query: str, max_results: int = 15) -> list[dict[str, Any]]:
    """Top de busqueda en YouTube para la palabra clave, con tags y vistas (Data API, ~101 unidades)."""
    from googleapiclient.discovery import build
    from youtube_uploader import _get_credentials

    yt = build("youtube", "v3", credentials=_get_credentials(interactive=False))
    r = yt.search().list(q=query, part="id", type="video", order="relevance", relevanceLanguage="en",
                         maxResults=max_results).execute()
    ids = [i["id"]["videoId"] for i in r.get("items", []) if i.get("id", {}).get("videoId")]
    if not ids:
        return []
    vids = yt.videos().list(id=",".join(ids), part="snippet,statistics").execute().get("items", [])
    def _thumb(sn):
        th = sn.get("thumbnails") or {}
        return ((th.get("medium") or th.get("high") or th.get("default") or {}).get("url")) or ""
    return [{"video_id": v.get("id", ""), "title": v["snippet"].get("title", ""),
             "channel": v["snippet"].get("channelTitle", ""),
             "views": int((v.get("statistics") or {}).get("viewCount") or 0),
             "tags": v["snippet"].get("tags") or [], "thumbnail": _thumb(v["snippet"])} for v in vids]


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('Uso: youtube_tags.py "tema" ["titulo"]')
        return 2
    topic = argv[0]
    title = argv[1] if len(argv) > 1 else topic
    rep = research_tags(topic, title, script=topic)
    print(rep["summary"])
    for t in rep["tags"]:
        e = rep["evidence"].get(t, {})
        print(f"  {t:45s} autocompl#{e.get('suggest_rank') or '-':<3} canales={e.get('competitor_channels', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
