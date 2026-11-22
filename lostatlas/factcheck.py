"""Verificacion de hechos de las preguntas del quiz, con Wikipedia como unica fuente de verdad.

Politica del repo: un Short con un dato falso NO se publica (el dia se salta). Como en ai/script_fact_check.py,
no se le pregunta al modelo que escribio la pista si miente; el juez solo ve la EVIDENCIA y debe copiar una cita
LITERAL que se comprueba por codigo contra el texto (si la cita no esta en la evidencia, el veredicto cae a "unsupported").

    evidence()        extractos de Wikipedia, con los parrafos que tocan lo afirmado
    judge()           DeepSeek revisa cada afirmacion: supported / unsupported / false (+ cita literal verificada)
    write_clues()     pistas escritas SOLO con la evidencia, con reglas duras (largo, sin dar la respuesta)
    verify()          todo junto: devuelve ok solo si TODAS las afirmaciones quedan respaldadas
"""
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path

import requests

from ai.deepseek_client import DeepSeekClient

WIKI_API = "https://en.wikipedia.org/w/api.php"
UA = "TheLostAtlasQuiz/1.0 (https://www.youtube.com/@TheLostAtlas-Trivia; educational quiz fact-checking)"
WIKI_CACHE = Path(__file__).parent / "data" / "wiki_cache"          # en .gitignore: respuestas de Wikipedia (30 dias)
_last = [0.0]


def _get(params):
    """GET con cache en disco, ~1 pedido/s y respeto de Retry-After. Wikipedia devuelve 429 ante rafagas:
    tratarlo como 'no hay evidencia' descartaba preguntas buenas, asi que se reintenta y, si no responde, se lanza el error."""
    WIKI_CACHE.mkdir(parents=True, exist_ok=True)
    f = WIKI_CACHE / (hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest() + ".json")
    if f.exists() and time.time() - f.stat().st_mtime < 30 * 86400:
        return json.loads(f.read_text())
    for attempt in range(7):
        wait = 1.0 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = requests.get(WIKI_API, params=params, headers={"User-Agent": UA}, timeout=25)
        if r.status_code == 429 or r.status_code >= 500:
            try:
                delay = float(r.headers.get("Retry-After", 0))
            except ValueError:
                delay = 0
            time.sleep(max(delay, 4 * (attempt + 1)))
            continue
        r.raise_for_status()
        data = r.json()
        f.write_text(json.dumps(data))
        return data
    raise RuntimeError("Wikipedia no respondio (429/5xx tras 7 intentos)")


def wiki_search(query, limit=2):
    data = _get({"action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json", "srprop": ""})
    return [x["title"] for x in (data.get("query") or {}).get("search") or [] if x.get("title")]


def wiki_extract(title):
    data = _get({"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title, "format": "json"})
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        return str(page.get("extract") or "")
    return ""


def year_in_lead(title, year, chars=6000):
    """El ano (con BC si es a. C.) aparece en la introduccion del articulo del evento: comprobacion deterministica."""
    txt = wiki_extract(title)[:chars]
    pat = rf"\b{abs(year)}\b" + (r"\s*(?:BC|BCE|B\.C\.)" if year < 0 else "")
    return bool(re.search(pat, txt))

EVID_CHARS = 9000
MAX_CLUE = 35
_client = None


def _llm():
    global _client
    if _client is None:
        _client = DeepSeekClient()
    return _client


def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _terms(text):
    return {w for w in norm(text).split() if len(w) >= 4 or w.isdigit()}


def evidence(queries, statements, max_titles=3):
    """Texto de evidencia (parrafos relevantes de los articulos hallados) y los titulos usados."""
    docs, titles = [], []
    for q in queries:
        found = wiki_search(q, limit=2)                  # los errores de red suben: no son "sin evidencia"
        for t in found:
            if t in titles:
                continue
            txt = wiki_extract(t)
            if txt:
                titles.append(t)
                docs.append((t, txt))
        if len(titles) >= max_titles:
            break
    want = set().union(*[_terms(s) for s in statements]) if statements else set()
    chosen, used = [], 0
    for t, txt in docs:
        paras = [p.strip() for p in re.split(r"\n+", txt) if len(p.strip()) > 40 and not p.strip().startswith("==")]
        lead, rest = paras[:3], paras[3:]
        scored = sorted(rest, key=lambda p: -len(_terms(p) & want))
        for p in lead + [p for p in scored if len(_terms(p) & want) >= 2]:
            if used + len(p) > EVID_CHARS:
                break
            chosen.append(f"[{t}] {p}")
            used += len(p)
    return "\n".join(chosen), titles


def _json(raw):
    if not raw:
        return None
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except Exception:
            return None


JUDGE_SYSTEM = "You are a meticulous, skeptical fact-checker. Output JSON only. Never use knowledge outside the evidence."


def judge(topic, statements, evid):
    """[{statement, verdict, quote, quote_found}] o None si el juez no respondio."""
    if not evid.strip():
        return None
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(statements))
    prompt = (
        "Check each STATEMENT about the topic below using ONLY the EVIDENCE (Wikipedia excerpts).\n"
        'Verdicts: "supported" (the evidence states it or it follows directly), "false" (the evidence contradicts it), '
        '"unsupported" (the evidence is silent or insufficient). Be strict: approximate or vague matches are "unsupported".\n'
        'For every "supported" you MUST include "quote": an exact sentence fragment copied verbatim from the EVIDENCE (max 220 chars).\n'
        'Return JSON: {"results":[{"id":1,"verdict":"supported|false|unsupported","quote":"..."}]}\n\n'
        f"TOPIC: {topic}\n\nSTATEMENTS:\n{numbered}\n\nEVIDENCE:\n{evid}"
    )
    data = _json(_llm()._generate(prompt, max_tokens=1200, task_type="script_quality", json_mode=True, system=JUDGE_SYSTEM))
    if not data or not isinstance(data.get("results"), list):
        return None
    by_id = {int(r.get("id", 0)): r for r in data["results"] if str(r.get("id", "")).isdigit()}
    nev = norm(evid)
    out = []
    for i, s in enumerate(statements):
        r = by_id.get(i + 1, {})
        verdict = str(r.get("verdict", "unsupported")).lower()
        quote = str(r.get("quote", ""))
        found = len(norm(quote)) >= 12 and norm(quote) in nev
        if verdict == "supported" and not found:
            verdict = "unsupported"                      # sin cita literal verificable no cuenta
        out.append(dict(statement=s, verdict=verdict, quote=quote, quote_found=found))
    return out


def verify(topic, statements, queries):
    """(ok, informe). ok solo si todas las afirmaciones estan respaldadas con cita literal comprobada."""
    evid, titles = evidence(queries, statements)
    res = judge(topic, statements, evid)
    if res is None:
        return False, dict(error="sin evidencia o sin respuesta del juez", titles=titles)
    return all(r["verdict"] == "supported" for r in res), dict(titles=titles, results=res)


def write_clues(entity, answer, kind, evid, forbidden, avoid_digits=None, notes=""):
    """3 pistas (de la mas dificil a la mas facil) escritas SOLO con la evidencia. [] si no cumplen las reglas."""
    guide = {
        "geo": 'Clue 3 should be "Capital: <city>" if it has a clear capital, BUT if the capital\'s name contains the answer (Oklahoma City, Mexico City, Panama City...) do NOT use a capital clue: use another verifiable fact. Clues 1-2: distinctive geography, nature, landmarks, history or culture. No demonyms.',
        "year": "Describe the event without stating its year. Clue 3 names the event plainly (e.g. 'RMS Titanic sinks').",
        "empire": "Describe the state without naming it. Clue 3 identifies it plainly (capital or its most famous ruler).",
    }[kind]
    prompt = (
        f"Write exactly 3 quiz clues for a short video about: {entity}.\n"
        f"Rules: English; each clue at most {MAX_CLUE} characters INCLUDING spaces; plain ASCII (no emoji, no curly quotes); ordered from hardest to easiest; "
        "every clue must be directly supported by the EVIDENCE; concrete verifiable facts, no vague superlatives unless the evidence states them; "
        f"never include any of these words in the clues: {', '.join(forbidden)}.\n{guide}\n{notes}\n"
        'Return JSON: {"clues":["...","...","..."]}\n\nEVIDENCE:\n' + evid
    )
    data = _json(_llm()._generate(prompt, max_tokens=300, task_type="script_quality", json_mode=True,
                                  system="You write precise quiz clues. Output JSON only."))
    clues = [re.sub(r"\s+", " ", str(c)).strip() for c in (data or {}).get("clues", [])]
    if len(clues) != 3 or len(set(clues)) != 3:
        return []
    for c in clues:
        if not c or len(c) > MAX_CLUE or not c.isascii():
            return []
        if any(norm(f) and re.search(r"(?<![a-z0-9])" + re.escape(norm(f)) + r"(?![a-z0-9])", norm(c)) for f in forbidden):
            return []                                              # palabra COMPLETA: "Indianapolis" no contiene "Indiana", "Oklahoma City" si contiene "Oklahoma"
        if avoid_digits and re.search(re.escape(str(avoid_digits)), c):
            return []
    return clues
