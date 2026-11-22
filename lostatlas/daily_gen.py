"""Generador diario de preguntas VERIFICADAS para The Lost Atlas (geo / year / empire).

Cada pregunta: entidad candidata -> evidencia de Wikipedia -> pistas escritas solo con esa evidencia -> segundo paso de
verificacion independiente (el juez ve las pistas ya escritas) -> solo entra si TODO queda respaldado con cita literal.
Si no se logran N preguntas verificadas, lanza NotEnough y el dia se salta (politica del repo).
"""
import json
import random
import re
from pathlib import Path

from . import factcheck as fc
from .hist import _features  # noqa: F401  (descarga bajo demanda)

DATA = Path(__file__).parent / "data"
PER_VIDEO = 5
MAX_TRIES_PER_SLOT = 4

# Polities del dataset historical-basemaps: nombres EXACTOS del archivo del ano indicado (verificados al elegirlos).
EMPIRES = [
    # (etiqueta, map_year, select, nota en el mapa, consulta Wikipedia)
    ("Achaemenid Empire", "bc500", {"NAME": ["Achaemenid Empire"]}, "c. 500 B.C.", "Achaemenid Empire"),
    ("Empire of Alexander", "bc323", {"NAME": ["Empire of Alexander"]}, "323 B.C.", "Alexander the Great empire Macedonian Empire"),
    ("Roman Empire", 100, {"NAME": ["Roman Empire"]}, "c. 100 A.D.", "Roman Empire"),
    ("Han Dynasty", 100, {"NAME": ["Han"]}, "c. 100 A.D.", "Han dynasty"),
    ("Parthian Empire", 100, {"NAME": ["Parthian Empire"]}, "c. 100 A.D.", "Parthian Empire"),
    ("Gupta Empire", 400, {"NAME": ["Gupta Empire"]}, "c. 400 A.D.", "Gupta Empire"),
    ("Abbasid Caliphate", 800, {"NAME": ["Abbasid Caliphate"]}, "c. 800 A.D.", "Abbasid Caliphate"),
    ("Tang Dynasty", 800, {"NAME": ["Tang Empire"]}, "c. 800 A.D.", "Tang dynasty"),
    ("Tibetan Empire", 800, {"NAME": ["Tibetan Empire"]}, "c. 800 A.D.", "Tibetan Empire"),
    ("Carolingian Empire", 800, {"NAME": ["Carolingian Empire"]}, "c. 800 A.D.", "Carolingian Empire"),
    ("Song Dynasty", 1000, {"NAME": ["Song Empire"]}, "c. 1000 A.D.", "Song dynasty"),
    ("Fatimid Caliphate", 1000, {"NAME": ["Fatimid Caliphate"]}, "c. 1000 A.D.", "Fatimid Caliphate"),
    ("Mongol Empire", 1279, {"SUBJECTO": ["Mongol Empire"]}, "1279 A.D.", "Mongol Empire"),
    ("Mali Empire", 1279, {"NAME": ["Mali"]}, "1279 A.D.", "Mali Empire"),
    ("Timurid Empire", 1400, {"NAME": ["Timurid Empire"]}, "c. 1400 A.D.", "Timurid Empire"),
    ("Inca Empire", 1530, {"NAME": ["Inca Empire"]}, "1530 A.D.", "Inca Empire"),
    ("Ming Dynasty", 1530, {"NAME": ["Ming Chinese Empire"]}, "1530 A.D.", "Ming dynasty"),
    ("Ottoman Empire", 1600, {"NAME": ["Ottoman Empire"]}, "1600 A.D.", "Ottoman Empire"),
    ("Safavid Empire", 1600, {"NAME": ["Safavid Empire"]}, "1600 A.D.", "Safavid Iran"),
    ("Mughal Empire", 1700, {"NAME": ["Mughal Empire"]}, "1700 A.D.", "Mughal Empire"),
    ("Viceroyalty of New Spain", 1700, {"NAME": ["Viceroyalty of New Spain"]}, "1700 A.D.", "Viceroyalty of New Spain"),
    ("Qing Dynasty", 1783, {"NAME": ["Qing Empire"]}, "1783 A.D.", "Qing dynasty"),
    ("Russian Empire", 1815, {"NAME": ["Russian Empire"]}, "1815 A.D.", "Russian Empire"),
    ("British Raj", 1914, {"NAME": ["British Raj"]}, "1914 A.D.", "British Raj"),
]
GEO_QUERY = {"Georgia": "Georgia (country)", "Republic of Serbia": "Serbia", "The Bahamas": "The Bahamas", "United Republic of Tanzania": "Tanzania",
             "Republic of the Congo": "Republic of the Congo", "Democratic Republic of the Congo": "Democratic Republic of the Congo", "Ivory Coast": "Ivory Coast",
             "eSwatini": "Eswatini", "Guinea Bissau": "Guinea-Bissau", "Macedonia": "North Macedonia", "United States of America": "United States"}
GEO_SKIP = {"Antarctica", "Vatican", "Jersey", "Guernsey", "Isle of Man", "Monaco", "San Marino", "Liechtenstein", "Andorra", "Nauru", "Tuvalu", "Palau",
            "Marshall Islands", "Federated States of Micronesia", "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines", "Antigua and Barbuda",
            "Barbados", "Grenada", "Dominica", "Seychelles", "Maldives", "Malta", "Bahrain", "Singapore", "Comoros", "Mauritius", "Sao Tome and Principe", "Kiribati",
            "Tonga", "Samoa", "Cape Verde", "Brunei", "Vanuatu", "Solomon Islands", "East Timor", "Kosovo", "Fiji",
            # territorios de soberania disputada: el quiz no debe tomar partido
            "Taiwan", "Northern Cyprus", "Somaliland", "Western Sahara", "Palestine"}


class NotEnough(Exception):
    pass


def _state(path):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {"geo": {}, "year": {}, "empire": {}}


def _cool(used, key, today_ord, days):
    last = used.get(key)
    return last is None or today_ord - last >= days


def _geo_pool():
    d = json.loads((DATA / "ne_50m_countries.geojson").read_text(encoding="utf-8"))
    out = []
    for f in d["features"]:
        p = f["properties"]
        if p.get("TYPE") not in ("Sovereign country", "Country") or p["ADMIN"] in GEO_SKIP or p.get("CONTINENT", "").startswith("Seven"):
            continue
        if (p.get("POP_EST") or 0) < 300_000:
            continue
        out.append((p["ADMIN"], p.get("CONTINENT")))
    return out


def _verified_question(base, entity, answer, kind, queries, forbidden, statements_for, avoid_digits=None, log=print):
    """Escribe pistas (con evidencia) y las verifica. Devuelve la pregunta o None."""
    for attempt in range(2):
        try:
            evid, titles = fc.evidence(queries, [entity, answer])
        except Exception as e:
            log(f"   {entity}: Wikipedia no disponible ({str(e)[:80]}); se omite sin descartar el dato")
            return None
        if not evid:
            log(f"   sin evidencia para {entity}")
            return None
        clues = fc.write_clues(entity, answer, kind, evid, forbidden, avoid_digits,
                               notes="" if attempt == 0 else "Previous attempt was rejected: use only facts stated explicitly in the evidence, shorter and simpler.")
        if not clues:
            continue
        ok, rep = fc.verify(entity, statements_for(clues), queries)
        bad = [r["statement"] for r in rep.get("results", []) if r["verdict"] != "supported"]
        log(f"   {entity}: {'OK' if ok else 'RECHAZADA'} {clues}" + (f" | falla: {bad[:2]}" if bad else ""))
        if ok:
            q = dict(base, clues=clues, verified=True, verified_by="wikipedia+deepseek", wiki=rep["titles"])
            return q
    return None


def gen_geo(n, state, today_ord, rng, log=print):
    pool = _geo_pool()
    rng.shuffle(pool)
    pool = [c for c in pool if _cool(state["geo"], c[0], today_ord, 60)]
    out, conts = [], {}
    for name, cont in pool:
        if len(out) >= n:
            break
        if conts.get(cont, 0) >= 2:
            continue
        q = GEO_QUERY.get(name, name)
        question = _verified_question(
            dict(country=name), name, name, "geo", [q, f"{q} country"], [name, name.split()[-1]],
            lambda clues, name=name: [f'About the country {name}: "{c}"' for c in clues], log=log)
        if question:
            out.append(question)
            conts[cont] = conts.get(cont, 0) + 1
    if len(out) < n:
        raise NotEnough(f"geo: solo {len(out)}/{n} verificadas")
    return out


def gen_empire(n, state, today_ord, rng, log=print):
    pool = [e for e in EMPIRES if _cool(state["empire"], e[0], today_ord, 25)]
    rng.shuffle(pool)
    out = []
    for label, map_year, select, note, wq in pool:
        if len(out) >= n:
            break
        word = label.replace("Empire", "").replace("Dynasty", "").replace("Caliphate", "").strip()
        forb = [label] + ([word] if len(word) > 3 else [])
        question = _verified_question(
            dict(country=label, map_year=map_year, select=select, note=note, labels=True, max_km=99999, near_deg=75,
                 caption=f"The world, {note}  Borders approximate."),
            label, label, "empire", [wq, label],
            forb, lambda clues, label=label: [f'About the {label}: "{c}"' for c in clues], log=log)
        if question:
            out.append(question)
    if len(out) < n:
        raise NotEnough(f"empire: solo {len(out)}/{n} verificadas")
    for i, q in enumerate(out):
        q["caption"] = f"Fig. {i + 1}.  {q['caption']}"
    return out


def _propose_events(k, avoid):
    prompt = (f"List {k} famous, unambiguous historical events that a general audience can recognise. Each must have ONE widely agreed year "
              "(use a negative number for BC). Vary eras and regions (ancient, medieval, early modern, modern; not only Europe). "
              f"Do not repeat or closely resemble these: {sorted(avoid)[:60]}.\n"
              'Return JSON: {"events":[{"title":"Wikipedia article title","year":1453}]}')
    data = fc._json(fc._llm()._generate(prompt, max_tokens=900, json_mode=True, system="You are a careful historian. Output JSON only."))
    return [(str(e["title"]), int(e["year"])) for e in (data or {}).get("events", []) if isinstance(e.get("year"), int) and e.get("title")]


def gen_year(n, state, today_ord, rng, log=print):
    used = set(state["year"])
    out, tried = [], set()
    for round_ in range(3):
        for title, year in _propose_events(n * 3, used | tried):
            if len(out) >= n:
                break
            tried.add(title)
            if title in used:
                continue
            bc = year < 0
            ytxt = f"{abs(year)} BC" if bc else str(year)
            try:
                if not fc.year_in_lead(title, year):
                    log(f"   {title} ({ytxt}): el ano no aparece en la introduccion del articulo, descartada")
                    continue
            except Exception as e:
                log(f"   {title}: Wikipedia no disponible ({str(e)[:80]}), se omite")
                continue
            question = _verified_question(
                dict(year=year, title=title), title, title, "year", [title], [str(abs(year))],
                lambda clues, title=title, ytxt=ytxt: [f'The event "{title}" took place in {ytxt}.'] + [f'About "{title}": "{c}"' for c in clues],
                avoid_digits=abs(year), log=log)
            if question:
                question["title"] = re.sub(r"\s*\(.*?\)\s*", " ", title).strip()
                out.append(question)
        if len(out) >= n:
            break
    if len(out) < n:
        raise NotEnough(f"year: solo {len(out)}/{n} verificadas")
    out.sort(key=lambda q: q["year"])                                  # cronologico: de lo antiguo a lo reciente (BC es negativo)
    return out


GEN = {"geo": gen_geo, "year": gen_year, "empire": gen_empire}


def build_day(template, state_path, today_ord, seed, n=PER_VIDEO, log=print):
    state = _state(state_path)
    rng = random.Random(seed)
    qs = GEN[template](n, state, today_ord, rng, log)
    return qs


def mark_used(state_path, template, questions, today_ord):
    st = _state(state_path)
    for q in questions:
        key = q["country"] if template in ("geo", "empire") else q["title"]
        st[template][key] = today_ord
    Path(state_path).write_text(json.dumps(st, indent=1, ensure_ascii=False))
