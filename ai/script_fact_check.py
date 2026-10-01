# -*- coding: utf-8 -*-
"""Verificacion de hechos del guion ANTES de generar la voz.

Por que existe (2026-09-24). El short de Trafalgar salio publicado diciendo que
"el Victory disparo el tiro que mato al almirante Villeneuve". Villeneuve no
murio en la batalla: lo capturaron y murio en 1806; el que murio fue Nelson.
El mismo guion inventaba una "advertencia de Collingwood" y daba por hecho que
la batalla "evito la invasion" (Napoleon ya la habia abandonado en agosto).

Nada lo freno porque:
  - el prompt ya decia "NO inventes", y el modelo invento igual;
  - `script_fact_guard` solo compara CIFRAS y ANIOS contra la investigacion,
    y "X mato a Y" no tiene numeros; ademas solo escribe en el log;
  - el reintento de largo pide agregar "hora exacta, victimas, testigos", o sea
    invita a inventar justo despues de la auditoria;
  - el optimizador de titulos toma el guion como verdad.

Como funciona. No se le pregunta al modelo que escribio el guion si mintio:

  1. Evidencia: se bajan de Wikipedia los articulos del tema y de las personas y
     lugares que nombra el guion, y se eligen los parrafos que tocan lo que el
     guion afirma (mas la investigacion que el pipeline ya tenia).
  2. Juez: Gemini con Google Search (busca de verdad en la web) revisa CADA
     afirmacion (quien hizo que, quien murio o fue capturado, fechas, horas,
     cifras, citas, causas y consecuencias) contra esa evidencia. Si Gemini no
     responde (cuota, red), juzga Groq contra los mismos parrafos de Wikipedia.
  3. Reparacion: las frases con problemas se reescriben con el dato documentado,
     manteniendo el largo de cada escena (la voz todavia no existe).
  4. Se vuelve a verificar. Lo que siga mal queda en `needs_review` y la subida
     lo frena (`upload_gate`) hasta que alguien lo corrija.

El informe queda en el storyboard (`storyboard["fact_check"]`) con una firma del
texto narrado: si despues se edita la narracion en el timeline, la firma deja
de coincidir y la subida vuelve a verificar.

Funciones puras con la red y los modelos inyectables. Ver
`test_script_fact_check.py`. SCRIPT_FACT_CHECK=0 lo apaga (no recomendado).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

REPORT_VERSION = 1
MAX_REPAIR_ROUNDS = 3        # desde la 2a ronda se reescribe en conservador (sin horas, cifras ni "mientras")
CHUNK_WORDS = 900            # un juez revisa mejor tramos cortos que un guion largo entero
EVIDENCE_CHARS = 12000       # parrafos de referencia por tramo
MAX_ARTICLES = 5
REPAIR_MIN_RATIO = 0.6       # la escena reparada no puede encogerse/estirarse de mas
REPAIR_MAX_RATIO = 1.45      # (el largo total del short importa)...
REPAIR_SLACK_WORDS = 10      # ...pero en escenas cortas unas palabras mas no cambian nada: Cannae
                             # (2026-09-25) descarto 3 veces "25 vs 17 palabras" y la subida quedo
                             # frenada. La voz se genera DESPUES, con el texto ya corregido.
REPAIR_MIN_WORDS = 6
TITLE_LABEL = "VIDEO TITLE"
TITLE_MAX_CHARS = 70          # el titulo se verifica y corrige con la narracion (Cannae: "86,000 Dead")

# "false" y "unsupported" frenan la subida; "misleading" se corrige si se puede
# pero no bloquea (suele ser matiz: "evito la invasion" -> "acabo con la amenaza").
BLOCKING = ("false", "unsupported")
VERDICTS = ("false", "unsupported", "misleading")

WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
USER_AGENT = "VideoOptimizer-factcheck/1.0 (history shorts; contact via repo owner)"

_STOP = set("""
the a an and or but of in on at to for from by with as is was were be been are it its this that these those
his her their our your my he she they we you i not no than then so such into over under after before during
while when where which who whom whose what why how all any each few more most other some own same very can
will just also only even ever still yet about above below between through against among within without
el la los las un una unos unas y o pero de del en a al por para con como es fue fueron ser sido son su sus
este esta estos estas ese esa esos esas lo le les se que quien cual cuando donde porque sin sobre entre
tras durante mientras mas muy ya aun tambien solo hasta desde contra
""".split())


# ------------------------------------------------------------------ utilidades

def enabled() -> bool:
    return str(os.getenv("SCRIPT_FACT_CHECK", "1")).strip().lower() not in ("0", "false", "no", "off")


def _plain(text: Any) -> str:
    t = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in t if not unicodedata.combining(c))


def _norm_space(text: Any) -> str:
    t = str(text or "").replace("‐", "-").replace("‑", "-").replace("’", "'")
    return re.sub(r"\s+", " ", t).strip()


def scene_text(scene: Any) -> str:
    """Narracion de una escena o segmento, venga del JSON del LLM o del storyboard."""
    if isinstance(scene, str):
        return _norm_space(scene)
    if not isinstance(scene, dict):
        return ""
    for key in ("narration", "narration_text", "text", "script"):
        val = scene.get(key)
        if isinstance(val, str) and val.strip():
            return _norm_space(val)
    return ""


def scene_texts(scenes: Iterable) -> List[str]:
    return [scene_text(s) for s in (scenes or [])]


def script_signature(texts: Iterable[str]) -> str:
    """Firma del texto narrado. No depende de como se partan las escenas."""
    joined = _plain(" ".join(t for t in texts if t)).lower()
    joined = re.sub(r"[^a-z0-9]+", " ", joined).strip()
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def storyboard_texts(storyboard: Dict) -> List[str]:
    """Narracion actual de un storyboard: segmentos (lo que se edita en el timeline) o guion."""
    segs = [scene_text(s) for s in (storyboard or {}).get("segments") or []]
    segs = [s for s in segs if s]
    if segs:
        return segs
    script = _norm_space((storyboard or {}).get("script"))
    return [script] if script else []


def _words(text: str) -> int:
    return len([w for w in str(text or "").split() if w])


# ------------------------------------------------------------------ evidencia

# Palabras con mayuscula que NO son algo que buscar: meses, dias, gentilicios,
# horas. Sin esto "British", "October" y "PM Nelson" salian como personajes.
_NOT_ENTITIES = set("""
january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday am pm bc ad bce ce
enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre
lunes martes miercoles jueves viernes sabado domingo
british english french spanish german italian roman romans greek greeks russian american americans
japanese chinese dutch portuguese ottoman persian egyptian egyptians allied allies soviet
franco-spanish anglo-french franco-prussian
britanico britanicos frances franceses espanol espanoles aleman alemanes romano romanos griego griegos
how why what when where who which did does do is was were the this that
""".split())

# Titulos que se sacan para buscar a la persona ("Admiral Villeneuve" -> "Villeneuve").
_TITLES = set("""
admiral vice-admiral general king queen emperor empress captain commander lord sir saint st president
prince princess duke pharaoh consul senator colonel major lieutenant sergeant pope bishop tsar czar sultan
almirante rey reina emperador emperatriz capitan comandante presidente principe princesa duque faraon papa
""".split())


def _clean_name(name: str) -> str:
    words = [w for w in name.split() if _plain(w).lower() not in _NOT_ENTITIES]
    while len(words) > 1 and _plain(words[0]).lower() in _TITLES:
        words = words[1:]
    return " ".join(words)


def key_entities(texts: Sequence[str], topic: str = "", limit: int = 4) -> List[str]:
    """Nombres propios del guion (personas, barcos, lugares), por frecuencia.

    "Nelson", "Villeneuve", "Collingwood": se buscan en Wikipedia ademas del
    tema, porque los errores suelen estar en lo que le paso a cada persona.
    """
    counts: Dict[str, int] = {}
    first_seen: Dict[str, int] = {}
    topic_words = set(_terms(topic))
    order = 0
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
            tokens = re.findall(r"[A-Za-zÀ-ÿ][\w'\-À-ÿ]*", sentence)
            run: List[str] = []
            for i, tok in enumerate(tokens + [""]):
                low_tok = _plain(tok).lower()
                cap = (bool(tok) and tok[0].isupper() and low_tok not in _STOP
                       and low_tok not in _NOT_ENTITIES)
                # la primera palabra de la frase solo cuenta si sigue otro nombre propio
                if cap and i == 0 and not (len(tokens) > 1 and tokens[1][:1].isupper()):
                    cap = False
                if cap:
                    run.append(re.sub(r"'s$", "", tok.strip("'")))
                    continue
                if run:
                    name = _clean_name(" ".join(run))
                    name_terms = set(_terms(name))
                    if len(name) > 3 and not (name_terms and name_terms <= topic_words):
                        counts[name] = counts.get(name, 0) + 1
                        first_seen.setdefault(name, order)
                        order += 1
                    run = []
    ranked = sorted(counts, key=lambda n: (-counts[n], first_seen[n]))
    out: List[str] = []
    for name in ranked:
        if any(name.lower() in o.lower() or o.lower() in name.lower() for o in out):
            continue
        out.append(name)
        if len(out) >= limit:
            break
    return out


def topic_queries(topic: str, texts: Sequence[str]) -> List[str]:
    """Busquedas del tema para Wikipedia.

    Un titulo de video ("How Nelson Won Trafalgar Against a Bigger Fleet") busca
    mal: trae "HMS Victory". Las palabras del tema que el guion escribe con
    mayuscula en mitad de frase son los nombres propios ("Nelson Trafalgar"), y
    esa busqueda si trae "Battle of Trafalgar".
    """
    names = topic_names(topic, texts)
    queries = []
    if names:
        queries.append(" ".join(names))
    if topic and topic.strip():
        queries.append(topic.strip())
    return queries


def topic_names(topic: str, texts: Sequence[str]) -> List[str]:
    """Palabras del tema que el guion usa siempre con mayuscula: los nombres propios.

    En un titulo todo va con mayuscula ("Won", "Fleet"), asi que se mira el
    guion: "Trafalgar" nunca aparece en minuscula, "fleet" si.
    """
    caps, lower = set(), set()
    for text in texts:
        for tok in re.findall(r"[A-Za-zÀ-ÿ][\w\-À-ÿ]*", text or ""):
            low = _plain(re.sub(r"'s$", "", tok)).lower()
            (caps if tok[0].isupper() else lower).add(low)
    out = []
    for w in re.findall(r"[\w\-]+", topic or ""):
        low = _plain(w).lower()
        if low in caps and low not in lower and low not in _NOT_ENTITIES and low not in _STOP:
            out.append(w)
    return list(dict.fromkeys(out))


_WIKI_CACHE: Dict[Tuple, Any] = {}
_LAST_REQUEST = [0.0]


def _http_get_json(url: str, params: Dict, timeout: int = 20) -> Dict:
    """GET con cache, pausa entre pedidos y reintento ante 429 (Wikipedia limita rafagas)."""
    import requests
    key = (url, tuple(sorted(params.items())))
    if key in _WIKI_CACHE:
        return _WIKI_CACHE[key]
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        wait = 0.35 - (time.time() - _LAST_REQUEST[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST[0] = time.time()
        try:
            r = requests.get(url, params=params, timeout=timeout,
                             headers={"User-Agent": USER_AGENT, "Api-User-Agent": USER_AGENT})
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            _WIKI_CACHE[key] = data
            return data
        except Exception as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_exc or RuntimeError("Wikipedia no respondio")


def wiki_search(query: str, lang: str = "en", limit: int = 2,
                http_get: Callable = _http_get_json) -> List[str]:
    data = http_get(WIKI_API.format(lang=lang), {
        "action": "query", "list": "search", "srsearch": query, "srlimit": limit,
        "format": "json", "srprop": ""})
    return [x.get("title", "") for x in (data.get("query") or {}).get("search") or [] if x.get("title")]


def wiki_extract(title: str, lang: str = "en", http_get: Callable = _http_get_json) -> str:
    data = http_get(WIKI_API.format(lang=lang), {
        "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
        "titles": title, "format": "json"})
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        return str(page.get("extract") or "")
    return ""


def _terms(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _plain(text).lower())
            if (len(w) >= 4 or w.isdigit()) and w not in _STOP]


def select_passages(documents: Sequence[Tuple[str, str]], texts: Sequence[str],
                    max_chars: int = EVIDENCE_CHARS) -> str:
    """Parrafos de las fuentes que mas tocan lo que dice el guion.

    documents = [(titulo, texto)]. Puntaje = terminos del guion presentes en el
    parrafo, pesados por rareza (un termino que esta en todos los parrafos no
    distingue nada). Siempre entra la entradilla del primer articulo.
    """
    script_terms = set(_terms(" ".join(texts)))
    paragraphs: List[Tuple[str, int, str]] = []   # (titulo, posicion, texto)
    for title, doc in documents:
        for pos, para in enumerate(re.split(r"\n+", doc or "")):
            para = para.strip()
            if len(para) < 80 or para.startswith("=="):
                continue
            paragraphs.append((title, pos, para))
    if not paragraphs:
        return ""
    df: Dict[str, int] = {}
    para_terms = []
    for _, _, para in paragraphs:
        ts = set(_terms(para)) & script_terms
        para_terms.append(ts)
        for t in ts:
            df[t] = df.get(t, 0) + 1
    n = len(paragraphs)
    scores = []
    for i, ts in enumerate(para_terms):
        score = sum(math.log(1 + n / df[t]) for t in ts)
        scores.append(score)
    chosen = {0} if paragraphs[0][1] <= 1 else set()
    budget = max_chars - (len(paragraphs[0][2]) if chosen else 0)
    for i in sorted(range(n), key=lambda i: -scores[i]):
        if scores[i] <= 0 or i in chosen:
            continue
        if len(paragraphs[i][2]) > budget:
            continue
        chosen.add(i)
        budget -= len(paragraphs[i][2])
        if budget < 200:
            break
    blocks, last_title = [], None
    for i in sorted(chosen):
        title, _, para = paragraphs[i]
        if title != last_title:
            blocks.append(f"[Wikipedia: {title}]")
            last_title = title
        blocks.append(para)
    return "\n".join(blocks)


def gather_documents(topic: str, texts: Sequence[str], language: str = "en",
                     research_context: Optional[Iterable] = None,
                     http_get: Callable = _http_get_json, log: Callable = print) -> Dict[str, Any]:
    """Articulos de Wikipedia del tema y de los nombres propios del guion (una vez por guion)."""
    langs = ["en"] if language == "en" else [language or "es", "en"]
    documents: List[Tuple[str, str]] = []
    sources: List[str] = []
    seen = set()
    tq = topic_queries(topic, texts)
    # Un nombre suelto busca mal ("Villeneuve" -> el piloto de F1): va con el tema.
    anchor = " ".join(topic_names(topic, texts)) or (tq[-1] if tq else "")
    queries = [(q, 2 if i == 0 else 1) for i, q in enumerate(tq)] + \
              [(f"{e} {anchor}".strip(), 1) for e in key_entities(texts, topic)]
    failures = 0
    for lang in langs:
        for query, limit in queries:
            if len(documents) >= MAX_ARTICLES or failures >= 3:
                break
            try:
                titles = wiki_search(query, lang, limit=limit, http_get=http_get)
            except Exception as exc:
                failures += 1
                log(f"   [Hechos] Wikipedia ({lang}) no respondio a '{query}': {str(exc)[:80]}")
                continue
            for title in titles:
                if (lang, title) in seen or len(documents) >= MAX_ARTICLES:
                    continue
                seen.add((lang, title))
                try:
                    extract = wiki_extract(title, lang, http_get=http_get)
                except Exception:
                    failures += 1
                    continue
                if extract:
                    documents.append((title, extract))
                    sources.append(f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}")
        if documents:
            break
    research = [str(r) for r in (research_context or []) if str(r or "").strip()]
    if research:
        documents.append(("investigacion del pipeline", "\n".join(research)))
    return {"documents": documents, "sources": sources}


def gather_evidence(topic: str, texts: Sequence[str], language: str = "en",
                    research_context: Optional[Iterable] = None,
                    http_get: Callable = _http_get_json, log: Callable = print,
                    max_chars: int = EVIDENCE_CHARS) -> Dict[str, Any]:
    docs = gather_documents(topic, texts, language, research_context, http_get=http_get, log=log)
    docs["text"] = select_passages(docs["documents"], texts, max_chars=max_chars)
    return docs


# ------------------------------------------------------------------ juez

def build_verify_prompt(texts: Sequence[str], topic: str, evidence_text: str,
                        first_scene: int = 1, grounded: Any = True,
                        focus: Optional[Sequence[int]] = None,
                        labels: Optional[Dict[int, str]] = None) -> str:
    """grounded: True (buscar en la web), "as_needed" (buscar solo lo que no se resuelve con los
    parrafos y el conocimiento: el Claude CLI decide cuando buscar y cada busqueda suma segundos)
    o False (sin busqueda)."""
    labels = labels or {}
    scenes = "\n".join(
        f"Scene {first_scene + i}{' (' + labels[first_scene + i] + ')' if first_scene + i in labels else ''}: {t}"
        for i, t in enumerate(texts) if t)
    title_rule = ""
    if TITLE_LABEL in labels.values():
        title_rule = ("\nThe item marked VIDEO TITLE is the video's title: check it against history too. A title may "
                      "simplify, but a number, outcome or claim in it must be true.\n")
    if grounded == "as_needed":
        lookup = ("Use the reference passages and your knowledge of well-established history first. Run a web "
                  "search ONLY for a specific claim you cannot settle confidently that way (at most 3 searches); "
                  "prefer encyclopedias and academic sources.")
    elif grounded:
        lookup = ("Use the reference passages AND web search (Google Search or your search tool); prefer "
                  "encyclopedias and academic sources.")
    else:
        lookup = "Use the reference passages and your own knowledge of well-established history."
    focus_rule = ""
    if focus:
        listed = ", ".join(str(n) for n in sorted(focus))
        focus_rule = (f"\nCheck ONLY scene(s) {listed}: they were just rewritten. The other scenes are context "
                      f"and were already verified; do not report problems in them.\n")
    return f"""You are the fact-checker of a history video channel. Below is the narration of a video about
"{topic}", split into numbered scenes. Find the statements a well-informed historian would call wrong.

Check every factual statement: who did what; who died, was killed, captured or survived, and how;
dates, times and numbers; places; the order of events; cause and effect; quotes, orders and warnings
attributed to people; consequences ("this ended / prevented / caused X").

Classify each problem:
- "false": contradicted by reliable sources (e.g. it says a ship killed a commander who was in fact captured and died later).
- "unsupported": a specific detail that looks INVENTED: no source records anything like it (a made-up quote,
  warning, dialogue, named witness or event). A detail you could not confirm quickly but that sources commonly
  report (an approximate time, a widely cited figure) is NOT unsupported.
- "misleading": a real fact seriously distorted: a popular myth presented as fact, a wrong cause, or events in the
  wrong order in a way that changes the story.

Report only what matters to a viewer: a wrong person, outcome, date, number or place, or an invented event or
quote. Do NOT flag: rhetorical questions, dramatic wording, reasonable rounding ("about 20,000"), fair
simplifications, points where historians disagree, nuances of wording, or claims explicitly framed as
legend/belief/theory ("some believe", "legend says") when that legend or theory really exists. {lookup}
{focus_rule}{title_rule}
REFERENCE PASSAGES:
{evidence_text or "(none found)"}

NARRATION:
{scenes}

List EVERY factual statement you checked, one entry each, including the correct ones (verdict "ok"), so
none is skipped. Return ONLY this JSON (no markdown):
{{"claims": [{{"scene": <scene number>, "quote": "<exact words from that scene>",
              "verdict": "ok|false|unsupported|misleading",
              "correction": "<for problems only: the documented fact, one sentence>",
              "source": "<for problems only: source title or URL>"}}]}}"""


def _parse_json_obj(raw: Any) -> Optional[Dict]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if m:
            text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        try:
            obj = json.loads(re.sub(r",\s*([}\]])", r"\1", text[start:end + 1]))
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def _locate(quote: str, texts: Sequence[str]) -> int:
    """Escena (1-based) que contiene la cita, o 0."""
    q = _plain(quote).lower()
    q = re.sub(r"[^a-z0-9 ]+", "", q).strip()
    if len(q) < 6:
        return 0
    for i, t in enumerate(texts, start=1):
        if q in re.sub(r"[^a-z0-9 ]+", "", _plain(t).lower()):
            return i
    return 0


def parse_findings(raw: Any, texts: Sequence[str], judge: str = "",
                   first_scene: int = 1) -> Optional[Tuple[List[Dict], int]]:
    """Lee la respuesta del juez. None si no se pudo leer (-> probar otro juez).

    El juez numera las escenas como se las mostro el prompt (desde first_scene);
    lo devuelto usa posiciones 1..len(texts) dentro de `texts`.
    """
    obj = _parse_json_obj(raw)
    if obj is None:
        return None
    # "claims" = todas las afirmaciones con su veredicto (lo que pide el prompt);
    # "problems" = solo las malas (formato viejo, se sigue aceptando).
    items = obj.get("claims") if "claims" in obj else obj.get("problems", [])
    if not isinstance(items, list):
        return None
    findings: List[Dict] = []
    checked = 0
    for p in items:
        if not isinstance(p, dict):
            continue
        checked += 1
        verdict = str(p.get("verdict") or "").strip().lower()
        if verdict not in VERDICTS:
            continue
        quote = _norm_space(p.get("quote"))
        try:
            scene = int(p.get("scene")) - (first_scene - 1)
        except (TypeError, ValueError):
            scene = 0
        # La cita manda cuando el juez numera mal; pero si la escena que dijo el juez contiene la
        # cita, se respeta (el titulo y la escena 1 pueden compartir "86,000").
        in_judged = 1 <= scene <= len(texts) and _locate(quote, [texts[scene - 1]]) == 1
        located = 0 if in_judged else _locate(quote, texts)
        if located:
            scene = located
        if not (1 <= scene <= len(texts)):
            continue
        findings.append({
            "scene": scene, "quote": quote, "verdict": verdict,
            "correction": _norm_space(p.get("correction")),
            "source": _norm_space(p.get("source"))[:200], "judge": judge,
        })
    if "claims" not in obj:
        try:
            checked = int(obj.get("claims_checked") or 0)
        except (TypeError, ValueError):
            checked = 0
    return findings, checked


# Gemini a probar, en orden. Cada modelo tiene su propia cuota diaria gratuita y la
# busqueda de Google tiene otra aparte (2026-09-24: la busqueda se agoto y las
# consultas sin busqueda seguian andando). Configurable: FACT_CHECK_GEMINI_MODELS.
DEFAULT_GEMINI_MODELS = "gemini-3.5-flash,gemini-2.5-flash,gemini-3.1-flash-lite"

# Juez que respondio 429/503 -> no se lo vuelve a intentar por un rato.
_UNAVAILABLE: Dict[str, float] = {}
COOLDOWN_SECONDS = 15 * 60


def _gemini_models() -> List[str]:
    raw = os.getenv("FACT_CHECK_GEMINI_MODELS", DEFAULT_GEMINI_MODELS)
    return [m.strip() for m in raw.split(",") if m.strip()]


def _is_capacity_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(k in text for k in ("429", "503", "quota", "high demand", "rate limit", "resource_exhausted",
                                   "not logged in", "usage limit", "limit reached", "credit balance",
                                   "timed out", "no encontrado"))


def _cooling(name: str) -> bool:
    t = _UNAVAILABLE.get(name)
    return bool(t) and (time.time() - t) < COOLDOWN_SECONDS


def gemini_judge(prompt: str, model: Optional[str] = None) -> Tuple[str, List[Dict]]:
    from ai.gemini_vision import ask_grounded
    return ask_grounded(prompt, model=model)


def gemini_plain_judge(prompt: str, model: Optional[str] = None) -> Tuple[str, List[Dict]]:
    from ai.gemini_vision import ask_images
    return ask_images(prompt, [], model=model, json_mode=True, timeout=150), []


def groq_judge(prompt: str) -> Tuple[str, List[Dict]]:
    from ai.groq_client import GroqAiClient
    client = GroqAiClient()
    # 8000: gpt-oss-120b gasta tokens razonando y con 4000 la respuesta llegaba truncada.
    raw = client._generate(prompt, max_tokens=8000, task_type="script_quality", json_mode=True)
    return raw or "", []


# ------------------------------------------------------------------ Claude CLI local

CLAUDE_WEB_TOOLS = ("WebSearch", "WebFetch")


def claude_cli_path() -> str:
    """El Claude Code CLI de esta PC (CLAUDE_CLI_PATH en .env, o `claude` en el PATH)."""
    import shutil
    path = str(os.getenv("CLAUDE_CLI_PATH") or "").strip()
    if path and os.path.exists(path):
        return path
    return shutil.which("claude") or ""


def claude_cli_enabled() -> bool:
    flag = str(os.getenv("FACT_CHECK_CLAUDE", "1")).strip().lower()
    return flag not in ("0", "false", "no", "off") and bool(claude_cli_path())


def run_claude_cli(prompt: str, *, tools: Sequence[str] = (), model: Optional[str] = None,
                   timeout: int = 300, runner: Optional[Callable] = None,
                   effort: Optional[str] = None) -> str:
    """Una consulta al Claude CLI en modo no interactivo. Devuelve el texto de la respuesta.

    - El prompt va por stdin: la linea de comandos de Windows se corta en ~8000
      caracteres y la evidencia de Wikipedia ya los supera.
    - Solo las herramientas pedidas (busqueda web para juzgar, ninguna para reescribir),
      sin MCP, sin guardar la sesion, y desde una carpeta temporal para no cargar el
      CLAUDE.md ni la memoria de este proyecto.
    - Entorno limpio de ANTHROPIC_*/CLAUDE_CODE*: si el Studio se abrio desde una sesion
      de Claude, esas variables apuntan al proxy de esa sesion y el CLI queda "Not logged in".
    Usa la cuenta de Claude de la PC (su limite de uso). Lanza RuntimeError si falla.
    """
    import subprocess
    import tempfile
    exe = claude_cli_path()
    if not exe:
        raise RuntimeError("Claude CLI no encontrado (CLAUDE_CLI_PATH)")
    cmd = [exe, "-p", "--output-format", "json", "--model",
           model or os.getenv("FACT_CHECK_CLAUDE_MODEL", "sonnet"),
           "--no-session-persistence", "--strict-mcp-config", "--tools", *(list(tools) or [""])]
    # Razonamiento bajo por defecto (2026-09-25, medido con el guion de Trafalgar): juez 50.7 s ->
    # 11.8 s (y encontro 5 problemas contra 3), reescritura 9.6 s -> 3.7 s. Con los parrafos de
    # Wikipedia en el prompt no necesita pensar a fondo ni salir a buscar.
    effort = effort if effort is not None else os.getenv("FACT_CHECK_CLAUDE_EFFORT", "low")
    if effort:
        cmd += ["--effort", effort]
    if tools:
        cmd += ["--allowedTools", *tools]
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("ANTHROPIC_", "CLAUDE_CODE", "CLAUDECODE"))}
    run = runner or subprocess.run
    try:
        proc = run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                   cwd=tempfile.gettempdir(), env=env)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timed out ({timeout} s)")
    try:
        data = json.loads(proc.stdout or "")
    except (json.JSONDecodeError, TypeError):
        raise RuntimeError(f"Claude CLI sin respuesta legible: {(proc.stderr or proc.stdout or '')[:200]}")
    result = str(data.get("result") or "")
    if data.get("is_error") or proc.returncode:
        hint = " (abri una terminal, corre `claude` y despues `/login`)" if "log" in result.lower() else ""
        raise RuntimeError(f"Claude CLI: {result[:200]}{hint}")
    return result


def claude_judge(prompt: str) -> Tuple[str, List[Dict]]:
    """Juez: Claude CLI con busqueda web (verifica en la web, como Gemini + Google)."""
    return run_claude_cli(prompt, tools=CLAUDE_WEB_TOOLS), []


def default_rewriter(fallback: Optional[Callable[[str], Any]] = None,
                     log: Callable = print) -> Callable[[str], Any]:
    """Quien reescribe las escenas: Claude CLI, despues Gemini, y si no responde, `fallback`
    (el cliente Groq del pipeline) o Groq directo."""
    def rewrite(prompt: str) -> Any:
        # Claude CLI primero (sin herramientas: reescribir no necesita buscar).
        if claude_cli_enabled() and not _cooling("rewrite:claude-cli"):
            try:
                return run_claude_cli(prompt)
            except Exception as exc:
                if _is_capacity_error(exc):
                    _UNAVAILABLE["rewrite:claude-cli"] = time.time()
                log(f"   [Hechos] reescritura con Claude CLI no disponible: {' '.join(str(exc).split())[:140]}")
        if os.getenv("GEMINI_API_KEY"):
            from ai.gemini_vision import ask_images
            for model in _gemini_models():
                name = f"rewrite:{model}"
                if _cooling(name):
                    continue
                try:
                    return ask_images(prompt, [], model=model, json_mode=True, timeout=150)
                except Exception as exc:
                    if _is_capacity_error(exc):
                        _UNAVAILABLE[name] = time.time()
                    log(f"   [Hechos] reescritura con {model} no disponible: {' '.join(str(exc).split())[:110]}")
        if fallback:
            return fallback(prompt)
        if os.getenv("GROQ_API_KEY"):
            from ai.groq_client import GroqAiClient
            return GroqAiClient()._generate(prompt, max_tokens=8000, task_type="script_quality",
                                            json_mode=True)
        return None
    return rewrite


def default_judges() -> List[Tuple[str, Callable, bool]]:
    """(nombre, funcion, usa_busqueda_web), del mejor al peor. El primero que responda juzga.

    1. Claude CLI de esta PC (2026-09-25: prioridad por pedido del usuario; con Gemini primero
       cada verificacion esperaba a que fallaran sus tres modelos sin cuota). Usa los parrafos
       de Wikipedia y busca en la web solo lo que no puede resolver. Usa la cuenta de Claude
       del usuario. FACT_CHECK_CLAUDE=0 lo saca;
    2. Gemini + Google Search (gratis mientras haya cuota);
    3. Gemini sin busqueda + parrafos de Wikipedia;
    4. Groq + Wikipedia (siempre hay cuota; mas flojo, a veces marca como falso algo cierto).
    """
    from functools import partial
    judges: List[Tuple[str, Callable, Any]] = []
    models = _gemini_models() if os.getenv("GEMINI_API_KEY") else []
    if claude_cli_enabled():
        judges.append(("claude-cli+web", claude_judge, "as_needed"))
    judges += [(f"{m}+google", partial(gemini_judge, model=m), True) for m in models]
    judges += [(f"{m}+wikipedia", partial(gemini_plain_judge, model=m), False) for m in models]
    if os.getenv("GROQ_API_KEY"):
        judges.append(("groq+wikipedia", groq_judge, False))
    return judges


def _chunks(texts: Sequence[str], max_words: int = CHUNK_WORDS) -> List[Tuple[int, List[str]]]:
    """[(indice_0_de_la_primera_escena, textos)] sin partir escenas."""
    out, cur, start, words = [], [], 0, 0
    for i, t in enumerate(texts):
        w = _words(t)
        if cur and words + w > max_words:
            out.append((start, cur))
            cur, start, words = [], i, 0
        cur.append(t)
        words += w
    if cur:
        out.append((start, cur))
    return out


def verify_texts(texts: Sequence[str], topic: str, *, evidence_fn: Callable,
                 judges: Sequence[Tuple[str, Callable, bool]], log: Callable = print,
                 focus: Optional[Sequence[int]] = None,
                 labels: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """Revisa el guion por tramos. focus = escenas (1-based) a revisar; el resto es contexto.

    judge=None si ningun juez respondio.
    """
    findings: List[Dict] = []
    checked, used, sources = 0, [], []
    focus_set = set(focus or [])
    for start, chunk in _chunks(texts):
        chunk_scenes = set(range(start + 1, start + len(chunk) + 1))
        chunk_focus = sorted(chunk_scenes & focus_set) if focus_set else None
        if focus_set and not chunk_focus:
            continue
        evidence = evidence_fn(chunk)
        sources.extend(s for s in evidence.get("sources", []) if s not in sources)
        verdict = None
        for name, fn, grounded in judges:
            if _cooling(name):
                continue
            prompt = build_verify_prompt(chunk, topic, evidence.get("text", ""),
                                         first_scene=start + 1, grounded=grounded, focus=chunk_focus,
                                         labels=labels)
            try:
                raw, web = fn(prompt)
            except Exception as exc:
                if _is_capacity_error(exc):
                    _UNAVAILABLE[name] = time.time()
                log(f"   [Hechos] juez {name} no disponible: {' '.join(str(exc).split())[:110]}")
                continue
            parsed = parse_findings(raw, chunk, judge=name, first_scene=start + 1)
            if parsed is None:
                log(f"   [Hechos] juez {name} devolvio algo ilegible; pruebo el siguiente")
                continue
            chunk_findings, n = parsed
            for f in chunk_findings:
                f["scene"] += start
            if chunk_focus:
                chunk_findings = [f for f in chunk_findings if f["scene"] in chunk_focus]
            findings.extend(chunk_findings)
            checked += n
            used.append(name)
            for w in web or []:
                uri = w.get("uri") if isinstance(w, dict) else str(w)
                if uri and uri not in sources:
                    sources.append(uri)
            verdict = True
            break
        if verdict is None:
            return {"judge": None, "findings": findings, "checked": checked, "sources": sources}
    return {"judge": "+".join(dict.fromkeys(used)) or None, "findings": findings,
            "checked": checked, "sources": sources}


# ------------------------------------------------------------------ reparacion

def build_repair_prompt(texts: Sequence[str], findings: Sequence[Dict], topic: str,
                        language: str = "en", conservative: bool = False,
                        visuals: Optional[Dict[int, str]] = None,
                        labels: Optional[Dict[int, str]] = None) -> str:
    """visuals = {escena: prompt de imagen actual}: si viene, se pide tambien el prompt corregido
    (si no, la imagen seguiria mostrando el dato falso: el Victory matando a Villeneuve)."""
    lang = "English" if (language or "en").startswith("en") else "Spanish"
    by_scene: Dict[int, List[Dict]] = {}
    for f in findings:
        by_scene.setdefault(f["scene"], []).append(f)
    blocks = []
    for scene in sorted(by_scene):
        text = texts[scene - 1]
        lo, hi = repair_word_range(_words(text))
        if (labels or {}).get(scene) == TITLE_LABEL:
            lines = [f'Scene {scene} (VIDEO TITLE: a true, punchy YouTube title of at most {TITLE_MAX_CHARS} '
                     f'characters; keep a number only if it is right): "{text}"']
        else:
            lines = [f'Scene {scene} ({_words(text)} words; write {lo}-{hi}): "{text}"']
        for f in by_scene[scene]:
            fix = f" -> documented fact: {f['correction']}" if f.get("correction") else ""
            lines.append(f'  - {f["verdict"]}: "{f["quote"]}"{fix}')
        if visuals and visuals.get(scene):
            lines.append(f'  Image prompt: "{visuals[scene]}"')
        blocks.append("\n".join(lines))
    context = " ".join(texts)
    visual_rule = visual_field = ""
    if visuals and any(visuals.get(n) for n in by_scene):
        visual_rule = ("For each scene that has an Image prompt, also return it corrected: same style, format and\n"
                       "length, changing only what showed the wrong fact so the image matches the new narration.\n\n")
        visual_field = ', "visual_prompt": "<corrected image prompt>"'
    careful = ("""
SECOND ATTEMPT: these scenes were already rewritten and still had problems. Now write them more generally:
keep only facts you are sure of, drop exact times, numbers and simultaneity ("while", "as", "at the same
moment"), and do not add any new detail.
""" if conservative else "")
    return f"""You are the narrator-writer of a history video about "{topic}". A fact-checker found errors.
Rewrite ONLY the scenes listed below so every statement is true:
- false: replace it with the documented fact given.
- unsupported: remove the invented detail, or replace it with a documented one. Never invent a new specific
  (quote, exact time, name, number) to fill the gap.
- misleading: state it accurately (for example "ended any threat of invasion" instead of "prevented invasion"
  when the invasion plan had already been abandoned).

How to write it:
- Change as little as possible: fix the wrong words and keep the rest of the sentence.
- When the false claim IS the heart of the scene, replace it with the most dramatic TRUE fact about the same
  moment, taken from the correction.
- If a time, date or number was wrong, prefer removing it over replacing it with another precise one, unless
  the correction states it clearly.
- Narrate the true fact directly. Never mention the error, never write "in fact", "actually", "contrary to",
  "though X had not", and never explain the correction.
- Same language ({lang}), same storytelling energy, same role in the story, roughly the same number of words
  per scene (within 20%). Do not change the other scenes.
{careful}
FULL NARRATION (context only):
{context}

SCENES TO FIX:
{chr(10).join(blocks)}

{visual_rule}Return ONLY JSON: {{"scenes": [{{"scene": <number>, "narration": "<corrected narration>"{visual_field}}}]}}"""


def parse_repairs(raw: Any) -> Dict[int, str]:
    obj = _parse_json_obj(raw)
    out: Dict[int, str] = {}
    for item in (obj or {}).get("scenes") or []:
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("scene"))
        except (TypeError, ValueError):
            continue
        text = _norm_space(item.get("narration"))
        if text:
            out[n] = text
    return out


def parse_visual_repairs(raw: Any) -> Dict[int, str]:
    """{escena: prompt de imagen corregido} de la misma respuesta de reparacion."""
    obj = _parse_json_obj(raw)
    out: Dict[int, str] = {}
    for item in (obj or {}).get("scenes") or []:
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("scene"))
        except (TypeError, ValueError):
            continue
        text = _norm_space(item.get("visual_prompt"))
        if text:
            out[n] = text
    return out


def accept_repair(old: str, new: str, max_chars: int = 0) -> Tuple[bool, str]:
    """La reparacion no puede romper la escena: vacia, identica o de largo muy distinto.

    max_chars: tope de caracteres (el titulo); en ese caso no se mira el rango de palabras."""
    if not new:
        return False, "vacia"
    if _norm_space(new) == _norm_space(old):
        return False, "sin cambios"
    if max_chars:
        return (True, "") if len(new) <= max_chars else (False, f"titulo de {len(new)} caracteres")
    ow, nw = max(1, _words(old)), _words(new)
    lo, hi = repair_word_range(ow)
    if nw < lo or nw > hi:
        return False, f"largo {nw} vs {ow} palabras (se acepta {lo}-{hi})"
    return True, ""


def repair_word_range(words: int) -> Tuple[int, int]:
    """Palabras aceptables para una escena reparada de `words` palabras."""
    lo = min(int(words * REPAIR_MIN_RATIO), max(REPAIR_MIN_WORDS, words - REPAIR_SLACK_WORDS // 2))
    hi = max(int(words * REPAIR_MAX_RATIO), words + REPAIR_SLACK_WORDS)
    return max(1, min(lo, words)), hi


# ------------------------------------------------------------------ orquestacion

def _problems(findings: Sequence[Dict]) -> List[Dict]:
    return [f for f in findings if f.get("verdict") in VERDICTS]


def _blocking(findings: Sequence[Dict]) -> List[Dict]:
    return [f for f in findings if f.get("verdict") in BLOCKING]


def _write_back(scenes: Sequence, texts: Sequence[str], visuals: Optional[Dict[int, str]] = None) -> List:
    out = []
    for i, (scene, text) in enumerate(zip(scenes, texts), start=1):
        if isinstance(scene, dict):
            s = dict(scene)
            if visuals and visuals.get(i) and isinstance(s.get("visual_prompt"), str):
                s["visual_prompt"] = visuals[i]
            touched = False
            for key in ("narration", "narration_text", "text"):
                if isinstance(s.get(key), str) and s.get(key).strip():
                    s[key] = text
                    touched = True
            if not touched:
                s["narration"] = text
            out.append(s)
        else:
            out.append(text)
    return out


def fact_check_scenes(scenes: Sequence, topic: str, *, language: str = "en",
                      research_context: Optional[Iterable] = None,
                      generate_fn: Optional[Callable[[str], Any]] = None,
                      judges: Optional[Sequence[Tuple[str, Callable, bool]]] = None,
                      http_get: Callable = _http_get_json,
                      repair: bool = True, log: Callable = print,
                      title: str = "") -> Tuple[List, Dict[str, Any]]:
    """Verifica (y repara) la narracion. Devuelve (escenas, informe). Nunca lanza.

    generate_fn(prompt) -> texto: el modelo que reescribe (Groq). judges: ver
    default_judges(). repair=False solo verifica (para la subida: la voz ya existe).

    title: el titulo del video se juzga y repara junto con la narracion (Cannae 2026-09-25:
    el guion corregido decia que 86.000 pelearon y el titulo seguia "86,000 Dead"). Queda en
    report["title"]. No entra en la firma ni frena la subida: se corrige en el Studio de metadatos.
    """
    scenes = list(scenes or [])
    texts = scene_texts(scenes)
    n_scenes = len(texts)
    title = _norm_space(title)
    labels: Dict[int, str] = {}
    if title:
        texts = texts + [title]
        labels[n_scenes + 1] = TITLE_LABEL
    report: Dict[str, Any] = {
        "version": REPORT_VERSION, "status": "unchecked", "judge": None,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "claims_checked": 0,
        "found": [], "corrections": [], "remaining": [], "sources": [],
        "signature": script_signature(texts[:n_scenes]),
        "title": title, "title_original": title,
    }
    if not enabled():
        report["status"] = "disabled"
        return scenes, report
    if not any(texts):
        report["status"] = "empty"
        return scenes, report
    judges = list(judges if judges is not None else default_judges())
    if not judges:
        log("   [Hechos] no hay juez disponible (faltan GEMINI_API_KEY y GROQ_API_KEY)")
        return scenes, report

    docs: Dict[str, Any] = {}

    def evidence_fn(chunk: Sequence[str]) -> Dict:
        # Los articulos se bajan una vez (del guion original); los parrafos se eligen por tramo.
        if not docs:
            try:
                docs.update(gather_documents(topic, texts, language, research_context,
                                             http_get=http_get, log=log))
            except Exception as exc:
                log(f"   [Hechos] sin evidencia de Wikipedia: {exc}")
                docs.update({"documents": [], "sources": []})
        return {"sources": docs["sources"],
                "text": select_passages(docs["documents"], chunk)}

    try:
        result = verify_texts(texts, topic, evidence_fn=evidence_fn, judges=judges, log=log, labels=labels)
    except Exception as exc:
        log(f"   [Hechos] no se pudo verificar: {exc}")
        return scenes, report
    report["sources"] = result["sources"][:20]
    if not result["judge"]:
        return scenes, report
    report["judge"] = result["judge"]
    report["claims_checked"] = result["checked"]
    found = _label_findings(_problems(result["findings"]), labels)
    report["found"] = [dict(f) for f in found]
    if not found:
        report["status"] = "verified"
        return scenes, report

    current = list(texts)
    pending = found
    visuals = {i: _norm_space(s.get("visual_prompt")) for i, s in enumerate(scenes, start=1)
               if isinstance(s, dict) and str(s.get("visual_prompt") or "").strip()}
    new_visuals: Dict[int, str] = {}
    if repair and generate_fn is None:
        generate_fn = default_rewriter(log=log)
    if repair:
        for round_no in range(1, MAX_REPAIR_ROUNDS + 1):
            try:
                raw = generate_fn(build_repair_prompt(current, pending, topic, language,
                                                       conservative=round_no >= 2,
                                                       visuals={**visuals, **new_visuals}, labels=labels))
            except Exception as exc:
                log(f"   [Hechos] la reparacion fallo: {exc}")
                break
            repairs = parse_repairs(raw)
            visual_repairs = parse_visual_repairs(raw)
            flagged = {f["scene"] for f in pending}
            changed = []
            for n in sorted(flagged):
                is_title = labels.get(n) == TITLE_LABEL
                ok, why = accept_repair(current[n - 1], repairs.get(n, ""),
                                        max_chars=TITLE_MAX_CHARS if is_title else 0)
                if not ok:
                    log(f"   [Hechos] {'titulo' if is_title else f'escena {n}'}: reparacion descartada ({why})")
                    continue
                report["corrections"].append({
                    "scene": n, "before": current[n - 1], "after": repairs[n], "round": round_no,
                    **({"scene_label": "titulo"} if is_title else {}),
                    "reasons": [f"{f['verdict']}: {f['correction'] or f['quote']}"
                                for f in pending if f["scene"] == n],
                })
                current[n - 1] = repairs[n]
                if visual_repairs.get(n) and n in visuals:
                    new_visuals[n] = visual_repairs[n]
                    report["corrections"][-1]["visual_prompt"] = visual_repairs[n]
                changed.append(n)
            if not changed:
                break
            untouched = [f for f in pending if f["scene"] not in changed]
            try:
                again = verify_texts(current, topic, evidence_fn=evidence_fn, judges=judges, log=log,
                                     focus=changed, labels=labels)
            except Exception as exc:
                log(f"   [Hechos] no se pudo re-verificar: {exc}")
                again = {"judge": None}
            if not again.get("judge"):
                # sin juez para confirmar: lo corregido se queda, lo que no se toco sigue pendiente
                pending = untouched
                break
            pending = untouched + _label_findings(_problems(again["findings"]), labels)
            # Otra ronda solo si quedan afirmaciones falsas o inventadas: un juez estricto
            # encuentra un matiz "enganoso" nuevo en cada re-verificacion y las rondas se
            # multiplicaban (Trafalgar: 3 rondas, 241 s). Los matices quedan como notas.
            if not _blocking(pending):
                break
    report["remaining"] = [dict(f) for f in pending]
    report["signature"] = script_signature(current[:n_scenes])
    if title:
        report["title"] = current[n_scenes]
    if _blocking([f for f in pending if f.get("scene_label") != "titulo"]):
        report["status"] = "needs_review"
    elif report["corrections"]:
        report["status"] = "corrected"
    else:
        report["status"] = "verified_with_notes"
    return _write_back(scenes, current[:n_scenes], new_visuals), report


def _label_findings(findings: List[Dict], labels: Dict[int, str]) -> List[Dict]:
    for f in findings:
        if labels.get(f.get("scene")) == TITLE_LABEL:
            f["scene_label"] = "titulo"
    return findings


def verify_storyboard(storyboard: Dict, *, judges=None, http_get: Callable = _http_get_json,
                      log: Callable = print) -> Dict[str, Any]:
    """Solo verifica (no repara) la narracion actual de un storyboard."""
    texts = storyboard_texts(storyboard)
    topic = str((storyboard or {}).get("topic") or (storyboard or {}).get("title") or "")
    _, report = fact_check_scenes(texts, topic, language=str((storyboard or {}).get("language") or "en"),
                                  judges=judges, http_get=http_get, repair=False, log=log)
    return report


# ------------------------------------------------------------------ subida

def report_is_current(storyboard: Dict) -> bool:
    report = (storyboard or {}).get("fact_check") or {}
    return bool(report) and report.get("signature") == script_signature(storyboard_texts(storyboard))


def upload_gate(storyboard: Dict, *, verify_fn: Optional[Callable[[Dict], Dict]] = None,
                log: Callable = print) -> Tuple[bool, Dict[str, Any], str]:
    """.Se puede subir? (ok, informe, mensaje).

    Usa el informe guardado si corresponde al texto actual; si no existe o la
    narracion cambio desde entonces, verifica de nuevo (sin reparar: la voz ya
    existe). Frena si quedan afirmaciones falsas o inventadas. Si no hay juez
    disponible no frena, pero lo dice.
    """
    if not enabled():
        return True, {"status": "disabled"}, "verificacion de hechos desactivada (SCRIPT_FACT_CHECK=0)"
    report = (storyboard or {}).get("fact_check") or {}
    if not report_is_current(storyboard) or report.get("status") in ("unchecked", None):
        report = (verify_fn or (lambda sb: verify_storyboard(sb, log=log)))(storyboard)
        if isinstance(storyboard, dict) and report.get("status") not in ("unchecked", "disabled", "empty"):
            storyboard["fact_check"] = report
    status = report.get("status")
    if status == "unchecked":
        return True, report, "no se pudo verificar el guion (sin juez disponible): revisalo a mano"
    if status == "needs_review":
        pending = _blocking(report.get("remaining") or []) or _blocking(report.get("found") or [])
        return False, report, "\n".join(format_problems(pending))
    return True, report, status_line(report)


# ------------------------------------------------------------------ informe

_LABEL = {"false": "FALSO", "unsupported": "INVENTADO", "misleading": "ENGANOSO"}


def format_problems(findings: Sequence[Dict], limit: int = 8) -> List[str]:
    lines = []
    for f in list(findings)[:limit]:
        fix = f" -> {f['correction']}" if f.get("correction") else ""
        where = f.get("scene_label") or f"escena {f['scene']}"
        lines.append(f"{where} [{_LABEL.get(f['verdict'], f['verdict'])}] \"{f['quote'][:90]}\"{fix}")
    if len(findings) > limit:
        lines.append(f"(y {len(findings) - limit} mas)")
    return lines


def status_line(report: Dict) -> str:
    status = report.get("status")
    judge = report.get("judge") or "-"
    if status == "verified":
        return f"[OK] Hechos verificados ({report.get('claims_checked', 0)} afirmaciones, juez {judge})"
    if status == "corrected":
        return f"[OK] Hechos corregidos: {len(report.get('corrections') or [])} escena(s) reescritas y re-verificadas (juez {judge})"
    if status == "verified_with_notes":
        return f"[OK] Hechos verificados con matices pendientes (juez {judge})"
    if status == "needs_review":
        return f"[FAIL] Quedan afirmaciones falsas o inventadas (juez {judge}); la subida queda frenada"
    if status == "disabled":
        return "[--] Verificacion de hechos desactivada (SCRIPT_FACT_CHECK=0)"
    if status == "empty":
        return "[--] Verificacion de hechos: no hay narracion"
    return "[WARN] No se pudo verificar los hechos (sin juez disponible); revisa el guion a mano"


def format_report(report: Dict) -> List[str]:
    lines = [status_line(report)]
    found = report.get("found") or []
    # Solo verificacion (subida): sin correcciones, lo pendiente ES lo encontrado; se lista una vez.
    if not report.get("corrections") and found == (report.get("remaining") or []):
        found = []
    for f in found:
        lines.append("   encontrado: " + format_problems([f])[0])
    for c in report.get("corrections") or []:
        lines.append(f"   {c.get('scene_label') or 'escena ' + str(c['scene'])} corregid{'o' if c.get('scene_label') else 'a'}:")
        lines.append(f"     antes:   {c['before'][:160]}")
        lines.append(f"     despues: {c['after'][:160]}")
    for f in report.get("remaining") or []:
        lines.append("   PENDIENTE: " + format_problems([f])[0])
    return lines


__all__ = [
    "enabled", "scene_text", "scene_texts", "script_signature", "storyboard_texts",
    "key_entities", "select_passages", "gather_evidence", "build_verify_prompt",
    "parse_findings", "verify_texts", "build_repair_prompt", "parse_repairs",
    "accept_repair", "fact_check_scenes", "verify_storyboard", "report_is_current",
    "upload_gate", "format_problems", "status_line", "format_report", "default_judges",
]
