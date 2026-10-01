# -*- coding: utf-8 -*-
"""Titulo, descripcion y hashtags de Facebook (e Instagram) guiados por la investigacion de YouTube.

Por que (2026-09-22):
  - Facebook no tiene campo de tags. Lo que indexa y lo que ve la gente es el titulo
    (videos de pagina), el arranque de la descripcion (lo visible antes de "Ver mas",
    ~125 caracteres) y los hashtags. Esos son los tres campos que se optimizan aca.
  - El reel de Hannibal del 22-09 salio con '#History #Mystery #StunningRevelations':
    la marca del OTRO canal (la pagina es Stunning Facts of History) y 'misterio', que
    la Biblia descarto (Bronze Age 'mystery' = 9 vistas). La descripcion ademas cortaba
    a mitad de palabra ('...every s') porque el respaldo recortaba el guion a 260/280.
  - Facebook no expone datos de busqueda por API: la investigacion es la de YouTube
    (autocompletado + videos que rankean, ver youtube_tags/youtube_titles). Es un proxy
    de lo que la gente busca sobre el tema, no una medicion de Facebook.

De donde sale la investigacion (research_inputs):
  1. Si YouTube se publico antes en la misma tanda, el Studio deja lo que YouTube ya
     investigo en metadata['research'] (research_from_youtube): mismo titulo y palabra
     clave en las dos redes, sin gastar cuota de nuevo.
  2. Si no hubo YouTube, se investiga aca igual que en youtube_uploader.
  3. Sin youtube_tags (el VPS no lo tiene), igual se limpian hashtags y marca.

Modo del titulo (como en YouTube): 'optimize' usa el investigado; 'suggest' (el titulo
lo escribio el usuario en el Metadata Studio) lo deja y reporta la alternativa.

Instagram (2026-09-22, prepare_instagram_metadata): el mismo motor. No tiene campo de
titulo: el caption arranca con el titulo, asi que la primera linea ya es la palabra clave.

Ver `test_facebook_metadata.py` y `test_instagram_metadata.py`.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Callable, Iterable, Optional

MAX_HASHTAGS = 5
MAX_RESEARCH_HASHTAGS = 3
MAX_HASHTAG_CHARS = 24
FEED_VISIBLE_CHARS = 125          # lo que Facebook muestra antes de "Ver mas"
MAX_DESCRIPTION_CHARS = 2200      # el mismo tope que aplica facebook_uploader
CATEGORY_HASHTAG = "History"

# Cebo generico, plataformas ajenas o angulos que el canal descarto: no suman alcance.
BANNED_HASHTAGS = {
    "mystery", "mysteries", "unsolved", "shorts", "youtubeshorts", "short", "reels", "reel",
    "fbreels", "fyp", "foryou", "foryoupage", "viral", "trending", "explore", "explorepage",
}
# Tags de la investigacion demasiado genericos para ser hashtag propio (#History ya va).
_GENERIC = {"history", "documentary", "documentaries", "facts", "education", "educational"}
_OWN_BRAND_RE = re.compile(r"^stunning(?:factsofhistory|revelations)$", re.I)
_SMALL = {"of", "the", "a", "an", "and", "in", "on", "at", "to", "for", "by", "from", "with"}
_UPPER_WORDS = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii", "xiv", "xv", "xvi",
                "ww1", "ww2", "wwi", "wwii", "ad", "bc", "bce", "uss", "hms", "usa", "uk", "ussr", "nasa"}
_HASHTAG_LINE_RE = re.compile(r"^(?:#\w+[\s,]*)+$", re.UNICODE)


def _ascii(text: Any) -> str:
    t = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _tokens(text: str) -> set[str]:
    """Palabras con contenido, sin posesivo ni plural simple ('Pompeii's casts' -> pompeii, cast)."""
    out = set()
    for w in re.findall(r"[0-9a-z]+(?:'s)?", _ascii(text).lower()):
        w = w[:-2] if w.endswith("'s") else w
        if w in _SMALL or len(w) < 2:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def brand_hashtag(brand: str) -> str:
    """'Stunning Facts of History' -> 'StunningFactsofHistory' (la convencion que ya usa el canal)."""
    return re.sub(r"[^0-9A-Za-z]", "", _ascii(brand))


def hashtag_from_phrase(phrase: str) -> Optional[str]:
    """'kaiten torpedo' -> 'KaitenTorpedo'. None si es muy larga, sin letras o de mas de 3 palabras."""
    words = re.findall(r"[0-9A-Za-z]+", _ascii(phrase).replace("'s ", " ").replace("'", ""))
    content = [w for w in words if w.lower() not in _SMALL]
    if not content or len(content) > 3:
        return None
    parts = []
    for w in words:
        if w.lower() in _UPPER_WORDS:
            parts.append(w.upper())
        elif w.isupper() and len(w) > 1:
            parts.append(w)
        else:
            parts.append(w[:1].upper() + w[1:])
    tag = "".join(parts)
    if not re.search(r"[A-Za-z]", tag) or len(tag) > MAX_HASHTAG_CHARS:
        return None
    return tag


def split_trailing_hashtags(description: str) -> tuple[str, list[str]]:
    """Separa el bloque final de hashtags del cuerpo. Los hashtags dentro de una frase se quedan."""
    lines = str(description or "").rstrip().split("\n")
    tags: list[str] = []
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if not _HASHTAG_LINE_RE.match(last):
            break
        tags = re.findall(r"#(\w+)", last, re.UNICODE) + tags
        lines.pop()
    return "\n".join(lines).rstrip(), tags


_ABBREVIATIONS = {"st", "mt", "mr", "mrs", "ms", "dr", "vs", "no", "gen", "lt", "col", "capt", "cpt", "sgt",
                  "jr", "sr", "fr", "ft", "approx", "ca", "c", "etc", "e.g", "i.e", "u.s", "u.k"}


def _sentence_ends(text: str) -> list[int]:
    """Posiciones de fin de oracion, sin contar 'St. Bernard', 'Dr. X' ni iniciales ('J. Smith')."""
    ends = []
    for m in re.finditer(r"[.?!…](?=[\s\"')”]|$)", text):
        if m.group(0) == ".":
            word = re.search(r"([\w.]+)$", text[:m.start()])
            w = word.group(1).lower() if word else ""
            if w in _ABBREVIATIONS or (len(w) == 1 and w.isalpha()):
                continue
        ends.append(m.end())
    return ends


def trim_at_boundary(text: str, max_chars: int) -> str:
    """Recorta en fin de oracion (o de palabra, con '...'), nunca a mitad de palabra."""
    t = str(text or "").strip()
    if len(t) <= max_chars:
        return t
    ends = [e for e in _sentence_ends(t) if e <= max_chars]
    if ends and ends[-1] >= max_chars * 0.5:
        return t[:ends[-1]].rstrip()
    cut = t[:max_chars]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(" ,;:-") + "…"


def repair_truncated_lead(body: str, min_len: int = 200) -> tuple[str, bool]:
    """El respaldo viejo recortaba el guion a 260/280 caracteres ('...rations every s') y ese
    texto quedo guardado en el Metadata Studio. Si el PRIMER parrafo es largo, no termina en
    puntuacion y le siguen otros, se corta en su ultimo fin de oracion."""
    paras = str(body or "").split("\n\n")
    lead = paras[0].rstrip()
    if len(paras) < 2 or len(lead) < min_len or lead[-1:] in ".?!…\"')”»":
        return body, False
    fixed = trim_at_boundary(lead, len(lead) - 1)
    return "\n\n".join([fixed] + paras[1:]), fixed != lead


def keyword_in_view(body: str, keyword: str = "", subject: str = "",
                    visible: int = FEED_VISIBLE_CHARS) -> bool:
    """El sujeto (o la palabra clave completa) aparece antes de 'Ver mas'."""
    head = _tokens(str(body or "")[:visible])
    subject_toks = _tokens(subject)
    if subject_toks and subject_toks <= head:
        return True
    kw_toks = _tokens(keyword)
    return bool(kw_toks) and kw_toks <= head


def is_proper_noun_in(word: str, text: str) -> bool:
    """La palabra aparece con mayuscula en medio de una oracion (nombre propio, no 'Recovered'
    al empezar la frase). Sin texto para comparar, no se descarta."""
    if not text:
        return True
    for m in re.finditer(r"\b" + re.escape(word) + r"\b", _ascii(text), re.I):
        if not m.group(0)[:1].isupper():
            continue
        before = _ascii(text)[:m.start()].rstrip(" \t")
        if before and before[-1] not in ".!?:\"'(\n“":
            return True
    return False


def build_hashtags(*, keyword: str = "", research_tags: Iterable[str] = (),
                   draft_hashtags: Iterable[str] = (), brand: str = "", subject: str = "",
                   source_text: str = "", max_n: int = MAX_HASHTAGS) -> list[str]:
    """Hasta max_n hashtags: palabra clave y tags investigados (hasta 3), #History, los del
    borrador que valgan, y la marca de la pagina siempre al final.

    Un tag investigado de UNA palabra solo entra si es el sujeto/la palabra clave o un
    nombre propio del guion: con un guion corto, 'Recovered' (inicio de frase) salia
    como '#Recovered' en la primera prueba (22-09)."""
    own = brand_hashtag(brand)
    subject_toks = _tokens(subject)
    anchor = subject_toks | _tokens(keyword)
    covered: set[str] = set()
    with_subject = 0
    out: list[str] = []
    seen: set[str] = set()
    budget = max_n - (1 if own else 0)

    def add(tag: Optional[str]) -> bool:
        if not tag or len(out) >= budget:
            return False
        k = tag.lower()
        if k in seen or k in BANNED_HASHTAGS or _OWN_BRAND_RE.match(k) or (own and k == own.lower()):
            return False
        seen.add(k)
        out.append(tag)
        return True

    # Sujeto amplio primero (#Hannibal, #Pompeii: los que la gente sigue), despues la
    # palabra clave y los tags. Cada uno tiene que sumar una palabra nueva, y como mucho
    # 2 repiten el sujeto (la primera prueba dio #HannibalArmy #Hannibal #HannibalBarca).
    # Un hashtag es una afirmacion sobre el video: cada palabra de un tag investigado tiene
    # que estar en el guion (la competencia dio '#RomanArmy' para Hannibal, cartagines).
    corpus = _tokens(source_text) | anchor
    research_added = 0
    for i, phrase in enumerate([subject, keyword, *research_tags]):
        if research_added >= MAX_RESEARCH_HASHTAGS:
            break
        if not phrase or normalize_phrase(phrase) in _GENERIC:
            continue
        if i >= 2 and source_text and not _tokens(phrase) <= corpus:
            continue
        words = [w for w in normalize_phrase(phrase).split() if w not in _SMALL]
        if len(words) == 1 and not (_tokens(words[0]) & anchor) and not is_proper_noun_in(words[0], source_text):
            continue
        toks = _tokens(phrase)
        has_subject = bool(subject_toks) and subject_toks <= toks
        if not toks or toks <= covered or (has_subject and with_subject >= 2):
            continue
        if add(hashtag_from_phrase(phrase)):
            research_added += 1
            covered |= toks
            with_subject += has_subject
    add(CATEGORY_HASHTAG)
    for tag in draft_hashtags:
        add(re.sub(r"\W", "", str(tag or "")))
    if own:
        out.append(own)
    return out


def normalize_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z ]+", " ", _ascii(text).lower())).strip()


def _writing_issues(title: str, keyword: str = "") -> list[str]:
    """Redaccion rota (youtube_titles.readability_issues); sin el modulo (VPS), nada."""
    try:
        from publish.youtube_titles import readability_issues
    except Exception:
        return []
    return readability_issues(title, keyword)


def optimize_facebook_metadata(meta: dict[str, Any], *, research_title: str = "", keyword: str = "",
                               subject: str = "", research_tags: Iterable[str] = (), brand: str = "",
                               title_mode: str = "optimize", platform: str = "facebook") -> dict[str, Any]:
    """Pura: arma titulo, descripcion y hashtags. Devuelve {title, title_original, title_changed,
    description, hashtags, hashtags_dropped, hook_added, keyword, summary}.

    platform='instagram': el caption es titulo + descripcion (instagram_uploader._compose_caption),
    asi que el titulo ya es la primera linea visible y el tope de 2200 incluye al titulo."""
    original_title = str(meta.get("title") or "").strip()
    research_title = str(research_title or "").strip()
    title, changed = original_title, False
    # Trafalgar (2026-09-24): Facebook tenia "How Nelson Won Trafalgar Against a Bigger Fleet" y lo
    # piso con el de YouTube, "Nelson Trafalgar how the victory secured British seas". Un titulo
    # investigado mal redactado no reemplaza a uno que se lee bien.
    rejected_research = ""
    if research_title and original_title and _writing_issues(research_title, keyword) \
            and not _writing_issues(original_title, keyword):
        rejected_research, research_title = research_title, ""
    if research_title and research_title != original_title and (title_mode == "optimize" or not original_title):
        title, changed = research_title, True

    body, draft_tags = split_trailing_hashtags(str(meta.get("description") or ""))
    body, lead_repaired = repair_truncated_lead(body)
    source_text = f"{meta.get('topic') or ''}\n{title}\n{meta.get('script_excerpt') or ''}\n{body}"
    hook_added = False
    if platform != "instagram" and title and (keyword or subject) and not keyword_in_view(body, keyword, subject):
        body = f"{title}\n\n{body}".strip() if body else title
        hook_added = True

    tags = build_hashtags(keyword=keyword, research_tags=research_tags, draft_hashtags=draft_tags,
                          brand=brand, subject=subject, source_text=source_text)
    tag_line = " ".join("#" + t for t in tags)
    room = MAX_DESCRIPTION_CHARS - (len(tag_line) + 2 if tag_line else 0)
    if platform == "instagram" and title:
        room -= len(title) + 2
    if len(body) > room:
        body = trim_at_boundary(body, room)
    description = f"{body}\n\n{tag_line}".strip() if tag_line else body

    kept = {t.lower() for t in tags}
    dropped = [t for t in dict.fromkeys(draft_tags) if t.lower() not in kept]
    parts = [f"titulo '{title}'" + (f" <- antes '{original_title}'" if changed and original_title else "")]
    if title_mode == "suggest" and research_title and research_title != original_title:
        parts.append(f"titulo del usuario se mantiene; alternativa investigada: '{research_title}'")
    if rejected_research:
        parts.append(f"no se uso el titulo investigado '{rejected_research}' (mal redactado)")
    parts.append("hashtags " + (tag_line or "(ninguno)"))
    if dropped:
        parts.append("quitados: " + " ".join("#" + t for t in dropped))
    if hook_added:
        parts.append("se antepuso el titulo: el tema no aparecia antes de 'Ver mas'")
    if lead_repaired:
        parts.append("se reparo el primer parrafo (venia cortado a mitad de palabra)")
    if keyword:
        parts.append(f"palabra clave '{keyword}'")
    return {"title": title, "title_original": original_title, "title_changed": changed,
            "description": description, "hashtags": tags, "hashtags_dropped": dropped,
            "hook_added": hook_added, "lead_repaired": lead_repaired, "keyword": keyword,
            "summary": " | ".join(parts)}


# ----------------------------------------------------------------------------
# De donde sale la investigacion
# ----------------------------------------------------------------------------
def research_from_youtube(result: Any) -> Optional[dict[str, Any]]:
    """Lo que youtube_uploader ya investigo para este video, listo para metadata['research']."""
    if not isinstance(result, dict):
        return None
    title = str(result.get("title_sent") or "").strip()
    tags = [str(t) for t in (result.get("tags_sent") or []) if str(t).strip()]
    if not title and not tags:
        return None
    title_research = result.get("title_research") or {}
    tag_research = result.get("tag_research") or {}
    return {"title": title,
            "keyword": title_research.get("keyword") or tag_research.get("main_keyword") or "",
            "subject": result.get("research_subject") or "",
            "tags": tags, "from": "youtube"}


def _research_enabled() -> bool:
    return str(os.getenv("FACEBOOK_SEO_RESEARCH", "1")).strip().lower() not in ("0", "false", "no", "off")


def research_inputs(meta: dict[str, Any], *, brand: str = "", is_long: bool = False,
                    log: Callable[[str], None] = print) -> dict[str, Any]:
    """{research_title, keyword, subject, research_tags, source}."""
    r = meta.get("research") or {}
    if r.get("title") or r.get("tags"):
        return {"research_title": r.get("title") or "", "keyword": r.get("keyword") or "",
                "subject": r.get("subject") or "", "research_tags": list(r.get("tags") or []),
                "source": "investigacion de YouTube (misma tanda)"}
    topic = str(meta.get("topic") or meta.get("title") or "").strip()
    if not topic or not _research_enabled():
        return {"source": "sin investigacion"}
    try:
        from publish.youtube_tags import gather_research, research_tags
        from publish.youtube_titles import optimize_title
    except ImportError:
        return {"source": "sin investigacion (modulos no disponibles)"}
    draft = str(meta.get("title") or "").strip()
    script = str(meta.get("script_excerpt") or meta.get("description") or "")
    research = gather_research(topic, draft, script, log=log)
    mode = "suggest" if str(meta.get("title_mode") or "optimize") == "suggest" else "optimize"
    title_report = optimize_title(topic, script, draft, research=research, is_short=not is_long,
                                  archetype=str(meta.get("format_archetype") or ""), mode=mode, log=log)
    tag_report = research_tags(topic, title_report.get("title") or draft, script, draft_tags=[],
                               brand_tag=brand.lower(), own_channel_names=[brand] if brand else [],
                               log=log, research=research)
    best = next((c["title"] for c in title_report.get("candidates") or [] if c.get("valid")), "")
    return {"research_title": (best if mode == "suggest" else title_report.get("title")) or "",
            "keyword": research.get("keyword") or "", "subject": research.get("subject") or "",
            "research_tags": list(tag_report.get("tags") or []), "source": "investigacion propia"}


def prepare_facebook_metadata(meta: dict[str, Any], *, brand: str = "", is_long: bool = False,
                              log: Callable[[str], None] = print, platform: str = "facebook") -> dict[str, Any]:
    """Investigacion (reusada o propia) + optimize_facebook_metadata. Nunca lanza por la
    investigacion: sin ella igual limpia hashtags y marca."""
    try:
        inputs = research_inputs(meta, brand=brand, is_long=is_long, log=log)
    except Exception as exc:
        inputs = {"source": f"investigacion no disponible ({type(exc).__name__}: {str(exc)[:120]})"}
    report = optimize_facebook_metadata(
        meta, research_title=inputs.get("research_title", ""), keyword=inputs.get("keyword", ""),
        subject=inputs.get("subject", ""), research_tags=inputs.get("research_tags", ()),
        brand=brand, title_mode=str(meta.get("title_mode") or "optimize"), platform=platform)
    report["source"] = inputs.get("source", "")
    report["summary"] += f" | fuente: {report['source']}"
    # Para que la red siguiente (Instagram despues de Facebook) no vuelva a investigar.
    if inputs.get("research_title") or inputs.get("research_tags"):
        report["research"] = {"title": inputs.get("research_title", ""), "keyword": inputs.get("keyword", ""),
                              "subject": inputs.get("subject", ""), "tags": list(inputs.get("research_tags") or []),
                              "from": inputs.get("source", "")}
    return report


def prepare_instagram_metadata(meta: dict[str, Any], *, brand: str = "", is_long: bool = False,
                               log: Callable[[str], None] = print) -> dict[str, Any]:
    """Lo mismo para Instagram: primera linea del caption (= titulo), cuerpo y hashtags."""
    return prepare_facebook_metadata(meta, brand=brand, is_long=is_long, log=log, platform="instagram")


def research_for_next_platform(*results: Any) -> Optional[dict[str, Any]]:
    """La investigacion ya hecha en esta tanda: la de YouTube o, si no hubo, la de Facebook."""
    for res in results:
        found = research_from_youtube(res)
        if found:
            return found
        if isinstance(res, dict) and isinstance(res.get("research_used"), dict):
            return res["research_used"]
    return None
