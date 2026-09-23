# -*- coding: utf-8 -*-
"""Tendencias para el Studio: que esta pegando afuera, que efemerides vienen, y temas listos.

Fuentes (todas de lectura):
  1. YouTube Data API: shorts de historia mas vistos publicados en los ultimos N dias
     (varias consultas del nicho, filtro ingles/ruido). Es lo que el 2026-09-21
     revelo los tres formatos que concentran los millones.
  2. Wikipedia: articulos mas vistos, filtrados a historia (una serie o estreno
     nuevo mueve la atencion: "The Odyssey", "Lizzie Borden"...).
  3. Efemerides de las proximas semanas (anniversaries.json), con angulo y gancho.
  4. Lo medido en el propio canal (performance_snapshot.json), para etiquetar.

Salida: un informe (`build_report`) con muestras, patrones y una lista de temas
propuestos {topic, archetype, category, date, why}, listos para cargar en el
Studio con un clic. Si Groq esta configurado, ademas propone temas nuevos a
partir del muestreo; si no, quedan los heuristicos.

    .venv\\Scripts\\python.exe trend_report.py            # 30 dias, 45 dias de efemerides
    .venv\\Scripts\\python.exe trend_report.py --sin-llm

Puro y testeable donde importa: ver `test_trend_report.py`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent
ANNIVERSARIES_PATH = ROOT / "anniversaries.json"
REPORT_PATH = ROOT / "daily_shorts" / "trend_report.json"

NICHE_QUERIES = (
    "ancient civilization facts", "lost city discovered", "ww2 facts", "medieval history facts",
    "ancient egypt facts", "roman empire facts", "archaeologists found", "cold war secret",
    "history shorts", "military history",
)
_JUNK_RE = re.compile(r"countryball|nfl|wwe|roblox|\bcod\b|marvel|minecraft|fortnite|anime|vs\.? usa|russia vs|karaoke|lyrics|"
                      r"chips|recipe|football|cricket|trailer|\bsong\b|wrestl|celebrity|\bipl\b|\bnba\b", re.I)
_HISTORY_RE = re.compile(
    r"\b(battle|war|empire|ancient|century|king|queen|dynasty|siege|bc|bce|ad|roman|egypt|medieval|viking|"
    r"ww2|ww1|world war|cold war|revolution|pharaoh|castle|legion|archaeolog|civilization|historical|"
    r"emperor|sultan|crusade|napoleon|hitler|stalin|caesar|odyssey|troy|sparta|inca|maya|aztec|mongol)\b", re.I)


# ----------------------------------------------------------------------------
# Puro
# ----------------------------------------------------------------------------
def is_english(title: str, threshold: float = 0.9) -> bool:
    t = title or ""
    return bool(t) and sum(ch.isascii() for ch in t) / len(t) >= threshold


def is_niche(title: str) -> bool:
    return is_english(title) and not _JUNK_RE.search(title or "")


def looks_historical(title: str) -> bool:
    return bool(_HISTORY_RE.search(title or ""))


def duration_band(seconds: float) -> str:
    s = float(seconds or 0)
    return "<=15s" if s <= 15 else "16-40s" if s <= 40 else "41-70s" if s <= 70 else "71-120s" if s <= 120 else ">120s"


def load_anniversaries(path: Path = ANNIVERSARIES_PATH) -> list[dict[str, Any]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    events = data.get("events") if isinstance(data, dict) else data
    return [e for e in (events or []) if isinstance(e, dict) and e.get("date") and e.get("title")]


def upcoming_anniversaries(events: Iterable[dict[str, Any]], today: Optional[_dt.date] = None,
                           days_ahead: int = 45) -> list[dict[str, Any]]:
    """Efemerides entre hoy y hoy+N, con la fecha real de este/proximo ano y los dias que faltan."""
    today = today or _dt.date.today()
    out = []
    for e in events:
        try:
            mm, dd = (int(x) for x in str(e["date"]).split("-"))
        except (ValueError, KeyError, TypeError):
            continue
        for year in (today.year, today.year + 1):
            try:
                when = _dt.date(year, mm, dd)
            except ValueError:
                continue
            delta = (when - today).days
            if 0 <= delta <= days_ahead:
                row = dict(e)
                row["when"] = when.isoformat()
                row["days_left"] = delta
                yr = e.get("year")
                if isinstance(yr, int) and yr > 0:
                    row["anniversary"] = year - yr
                out.append(row)
                break
    out.sort(key=lambda r: r["days_left"])
    return out


def summarize_patterns(rows: list[dict[str, Any]], top_n: int = 40) -> dict[str, Any]:
    """Patrones del muestreo externo: angulos, bandas de duracion, canales que repiten."""
    from performance_feedback import classify_archetype

    top = sorted(rows, key=lambda r: -int(r.get("views") or 0))[:top_n]
    by_arch: dict[str, dict[str, Any]] = {}
    by_band: dict[str, int] = {}
    channels: dict[str, int] = {}
    for r in top:
        a = classify_archetype(r.get("title", ""))
        g = by_arch.setdefault(a, {"n": 0, "views": 0, "examples": []})
        g["n"] += 1
        g["views"] += int(r.get("views") or 0)
        if len(g["examples"]) < 3:
            g["examples"].append(f"{(r.get('title') or '')[:60]} ({int(r.get('views') or 0):,})")
        by_band[duration_band(r.get("duration", 0))] = by_band.get(duration_band(r.get("duration", 0)), 0) + 1
        ch = r.get("channel") or ""
        if ch:
            channels[ch] = channels.get(ch, 0) + 1
    return {
        "sample_size": len(rows),
        "top_n": len(top),
        "by_archetype": dict(sorted(by_arch.items(), key=lambda kv: -kv[1]["views"])),
        "by_duration": dict(sorted(by_band.items(), key=lambda kv: -kv[1])),
        "repeat_channels": [c for c, n in sorted(channels.items(), key=lambda kv: -kv[1]) if n >= 2][:8],
    }


def heuristic_proposals(anniversaries: list[dict[str, Any]], wiki_titles: list[str],
                        patterns: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    """Temas sin LLM: efemerides con su gancho, y Wikipedia historica como 'atencion presente'."""
    out = []
    for e in anniversaries[:limit]:
        out.append({
            "topic": e["title"],
            "archetype": e.get("angle") or "scale_event",
            "category": e.get("category") or "",
            "date": e.get("when"),
            "days_left": e.get("days_left"),
            "hook": e.get("hook") or "",
            "why": f"efemeride en {e.get('days_left')} dias" + (f" ({e['anniversary']} anos)" if e.get("anniversary") else ""),
            "source": "anniversary",
        })
    for t in wiki_titles[:6]:
        out.append({"topic": t, "archetype": "discovery" if looks_historical(t) else "scale_event", "category": "",
                    "date": None, "days_left": None, "hook": "",
                    "why": "entre los articulos mas vistos de Wikipedia esta semana (atencion presente)", "source": "wikipedia"})
    return out[:limit + 6]


def merge_proposals(*lists: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Une propuestas sin duplicar temas (por texto normalizado); conserva el orden de llegada."""
    seen, out = set(), []
    for lst in lists:
        for p in lst or []:
            key = re.sub(r"[^a-z0-9]+", " ", str(p.get("topic") or "").lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def format_report(report: dict[str, Any]) -> str:
    lines = [f"TENDENCIAS ({report.get('generated_at')})"]
    pat = report.get("patterns") or {}
    if pat.get("by_archetype"):
        lines.append(f"  YouTube nicho, top {pat.get('top_n')} de {pat.get('sample_size')} shorts ({report.get('window_days')} dias):")
        for a, g in pat["by_archetype"].items():
            lines.append(f"    - {a:12s} n={g['n']:2d}  {g['views']:>12,} vistas  ej: {g['examples'][0] if g['examples'] else ''}")
        lines.append("    duraciones: " + ", ".join(f"{k} x{v}" for k, v in pat.get("by_duration", {}).items()))
    if report.get("wikipedia"):
        lines.append("  Wikipedia (historia, mas vistos): " + ", ".join(report["wikipedia"][:8]))
    if report.get("anniversaries"):
        lines.append("  Efemerides:")
        for e in report["anniversaries"][:8]:
            lines.append(f"    - {e['when']} (en {e['days_left']} d) {e['title']} [{e.get('angle')}]")
    if report.get("proposals"):
        lines.append("  TEMAS PROPUESTOS:")
        for p in report["proposals"][:14]:
            fecha = f" {p['date']}" if p.get("date") else ""
            lines.append(f"    - [{p.get('archetype')}]{fecha} {p['topic']} -- {p.get('why', '')}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Red
# ----------------------------------------------------------------------------
def sample_youtube_niche(days: int = 30, queries: Iterable[str] = NICHE_QUERIES, per_query: int = 12,
                         log=print) -> list[dict[str, Any]]:
    import time
    from googleapiclient.discovery import build
    from youtube_uploader import _get_credentials

    yt = build("youtube", "v3", credentials=_get_credentials(interactive=False))
    after = (_dt.datetime.utcnow() - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: dict[str, set] = {}
    for q in queries:
        for attempt in range(3):
            try:
                r = yt.search().list(q=q, part="id", type="video", order="viewCount", publishedAfter=after,
                                     videoDuration="short", relevanceLanguage="en", regionCode="US",
                                     maxResults=per_query).execute()
                for it in r.get("items", []):
                    ids.setdefault(it["id"]["videoId"], set()).add(q)
                break
            except Exception as exc:
                if attempt == 2:
                    log(f"[Tendencias] consulta '{q}' fallo: {exc}")
                time.sleep(2)
    vids = []
    keys = list(ids)
    for i in range(0, len(keys), 50):
        try:
            vids += yt.videos().list(id=",".join(keys[i:i + 50]), part="snippet,statistics,contentDetails").execute()["items"]
        except Exception as exc:
            log(f"[Tendencias] detalle de videos fallo: {exc}")
    rows = []
    for v in vids:
        sn = v.get("snippet", {})
        title = sn.get("title", "")
        if not is_niche(title):
            continue
        m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", (v.get("contentDetails") or {}).get("duration", ""))
        dur = (int(m.group(1) or 0) * 60 + int(m.group(2) or 0)) if m else 0
        rows.append({"video_id": v["id"], "title": title, "channel": sn.get("channelTitle", ""),
                     "published": (sn.get("publishedAt") or "")[:10], "duration": dur,
                     "views": int((v.get("statistics") or {}).get("viewCount") or 0),
                     "likes": int((v.get("statistics") or {}).get("likeCount") or 0),
                     "queries": sorted(ids.get(v["id"], []))})
    rows.sort(key=lambda r: -r["views"])
    return rows


def wikipedia_history_trending(max_results: int = 60) -> list[str]:
    try:
        from trend_spotter import get_wikipedia_trending
        titles = get_wikipedia_trending(max_results=max_results) or []
    except Exception:
        titles = []
    return [t for t in titles if looks_historical(t)]


def llm_proposals(rows: list[dict[str, Any]], patterns: dict[str, Any], anniversaries: list[dict[str, Any]],
                  snapshot: Optional[dict[str, Any]] = None, client=None, limit: int = 10) -> list[dict[str, Any]]:
    """Groq propone temas nuevos para ESTE canal a partir del muestreo. Vacio si no hay cliente."""
    try:
        if client is None:
            from groq_client import GroqAiClient
            client = GroqAiClient()
        if not getattr(client, "client", None):
            return []
        from channel_strategy import get_format_archetypes, get_all_category_names, get_channel_audience_line
        from micro_documentary import _json_generate
    except Exception:
        return []
    hist = [r for r in rows if looks_historical(r.get("title", ""))] or rows
    top = [f"- {r['title'][:80]} ({r['views']:,} views, {r['duration']}s)" for r in hist[:30]]
    arche = [f"{a['id']}: {a.get('description', '')}" for a in get_format_archetypes()]
    rec = ((snapshot or {}).get("recommendations") or {})
    avoid = "; ".join(x.get("label", "") for x in rec.get("avoid", []))
    prompt = f"""You program a documented-history YouTube Shorts channel ({get_channel_audience_line()}).
Categories: {get_all_category_names()}.
Narrative angles (id: meaning): {arche}.
Measured on OUR channel -- avoid: {avoid or 'nothing measured yet'}.

These history shorts are the most viewed of the last 30 days on YouTube (external, not ours):
{chr(10).join(top)}

Upcoming anniversaries we could ride: {[(e['when'], e['title']) for e in anniversaries[:8]]}

Propose {limit} NEW video topics for our channel that ride these patterns without copying titles.
HARD RULES:
- Only REAL, well-documented events, sites, people or mechanisms (Wikipedia-level documentation). Never invent a
  person, an object, an age, a number or a find. If you are not sure a detail is documented, choose another topic.
- The topic is a plain subject line (e.g. "Roman concrete: why it hardens in seawater"). Never prefix it with the
  angle name: "Mechanism of...", "Human story of...", "Discovery of...", "Scale event:" are forbidden.
- Numbers must be the documented ones; round only as historians do.
- Mention an anniversary ONLY if the topic IS that event or is directly about it; otherwise cite the external
  title it rides. Do not force anniversaries.
- No mystery/paranormal framing; no modern disaster as the only angle.
Return JSON: {{"proposals": [{{"topic": "...", "archetype": "<one id>",
"category": "<one of the categories>", "hook": "first spoken sentence, <=14 words, a number or a how/why question, no date opener",
"why": "the specific external title or anniversary it rides"}}]}}"""
    try:
        data = _json_generate(client, prompt)
    except Exception:
        return []
    out = []
    valid_arch = {a["id"] for a in get_format_archetypes()}
    for p in (data or {}).get("proposals", []) if isinstance(data, dict) else []:
        if not isinstance(p, dict) or not p.get("topic"):
            continue
        topic = re.sub(r"^(mechanism|discovery|human story|scale event)( of| behind|:)?\s*", "", str(p["topic"]).strip(), flags=re.I).strip()
        if not topic:
            continue
        out.append({"topic": topic, "archetype": p.get("archetype") if p.get("archetype") in valid_arch else "scale_event",
                    "category": str(p.get("category") or ""), "date": None, "days_left": None,
                    "hook": str(p.get("hook") or ""), "why": str(p.get("why") or ""), "source": "llm"})
    return out[:limit]


def build_report(days: int = 30, days_ahead: int = 45, with_llm: bool = True, with_youtube: bool = True,
                 log=print, today: Optional[_dt.date] = None) -> dict[str, Any]:
    rows = []
    if with_youtube:
        log(f"[Tendencias] YouTube: shorts de historia mas vistos, {days} dias...")
        try:
            rows = sample_youtube_niche(days=days, log=log)
            log(f"[Tendencias]   {len(rows)} shorts del nicho")
        except Exception as exc:
            log(f"[Tendencias]   YouTube omitido: {exc}")
    wiki = wikipedia_history_trending()
    log(f"[Tendencias] Wikipedia: {len(wiki)} articulos historicos entre los mas vistos")
    ann = upcoming_anniversaries(load_anniversaries(), today=today, days_ahead=days_ahead)
    log(f"[Tendencias] Efemerides en {days_ahead} dias: {len(ann)}")
    patterns = summarize_patterns(rows) if rows else {}
    snapshot = {}
    try:
        from channel_strategy import get_performance_snapshot
        snapshot = get_performance_snapshot()
    except Exception:
        pass
    proposals = heuristic_proposals(ann, wiki, patterns)
    if with_llm and rows:
        log("[Tendencias] Groq: proponiendo temas nuevos...")
        llm = llm_proposals(rows, patterns, ann, snapshot)
        log(f"[Tendencias]   {len(llm)} propuestas")
        proposals = merge_proposals(llm, proposals)
    report = {
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "window_days": days,
        "youtube_sample": rows[:60],
        "patterns": patterns,
        "wikipedia": wiki[:20],
        "anniversaries": ann,
        "proposals": proposals,
    }
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dias", type=int, default=30)
    ap.add_argument("--efemerides", type=int, default=45, help="dias hacia adelante")
    ap.add_argument("--sin-llm", action="store_true")
    ap.add_argument("--sin-youtube", action="store_true")
    args = ap.parse_args(argv)
    rep = build_report(days=args.dias, days_ahead=args.efemerides, with_llm=not args.sin_llm, with_youtube=not args.sin_youtube)
    print()
    print(format_report(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
