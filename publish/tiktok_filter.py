"""Filtro previo para TikTok, segun sus Normas de la comunidad (version del 24-09-2026).

TikTok modera primero con clasificadores automaticos que leen todo lo que acompana al video:
titulo, descripcion, hashtags, texto en pantalla y audio. No distinguen un documento
desclasificado de 1962 de una amenaza actual. 2026-10-07: el Short de Operation Northwoods
(#FalseFlag, "terror campaign", "staged attacks on the United States") se retiro por "Normas de
la comunidad" el mismo dia, mientras el carrusel del mismo tema, sin #FalseFlag, seguia arriba.

Dos niveles:
  bloquea  lo que las normas prohiben: riesgo de retiro y de falta en la cuenta.
  aviso    lo que TikTok suele dejar fuera del feed Para ti o mandar a revision.
La historia de guerras sola no bloquea (es lo normal en #HistoryTok); bloquea la mezcla de
marco conspirativo, "montaje" y violencia, que es como lee el clasificador una "false flag".

Uso: `python -m publish.tiktok_filter --texto "..."` (o --archivo, --proyecto, --metadata).
Las listas de terminos de abajo se pueden ampliar; cada regla dice que norma la respalda.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

BLOCK, WARN = "bloquea", "aviso"

# Terminos sobre texto normalizado (minusculas, hashtags separados: #FalseFlag -> "false flag").
FALSE_FLAG = (r"\bfalse[\s-]*flags?\b", r"\bbanderas?\s+falsas?\b", r"\binside\s+job\b",
              r"\bcrisis\s+actors?\b", r"\bhoax(?:es)?\b")
CONSPIRACY = (r"\bconspirac(?:y|ies)\b", r"\bconspiraci[oó]n(?:es)?\b", r"\bconspiranoi\w*",
              r"\bcover[\s-]?ups?\b", r"\bencubrimiento\b", r"\bthey\s+don'?t\s+want\s+you\s+to\s+know\b",
              r"\bno\s+quieren\s+que\s+(?:lo\s+)?sepas\b", r"\bdeep\s+state\b", r"\bnew\s+world\s+order\b",
              r"\billuminati\b", r"\bsecret\s+societ(?:y|ies)\b", r"\bsociedad(?:es)?\s+secretas?\b")
STAGED = (r"\bstag(?:e|ed|ing)\b", r"\bfake[ds]?\b", r"\bfabricat\w*", r"\bmock\b", r"\bfals[oa]s?\b",
          r"\bsimulad[oa]s?\b", r"\bmontad[oa]s?\b")
VIOLENCE = {
    "blow up": r"\bblow(?:s|n|ing)?\s+up\b|\bblew\s+up\b|\bvolar\s+(?:un|una|el|la)\b",
    "bomb": r"\bbomb(?:s|ed|ing)?\b|\bbomba(?:s|rdeo)?\b",
    "terror": r"\bterror(?:ism|ist|ists)?\b|\bterroris(?:mo|ta|tas)\b",
    "shoot down": r"\bshoot(?:s|ing)?\s+down\b|\bshot\s+down\b|\bshootdowns?\b|\bderrib\w+",
    "kill": r"\bkill(?:s|ed|ing)?\b|\bmurder\w*|\bmassacre\w*|\bmatar(?:on)?\b|\bmasacre\w*|\basesin\w+",
    "attack on": r"\battacks?\s+(?:on|against)\b|\batentados?\b|\bataques?\s+contra\b",
    "explode": r"\bexplod\w*|\bexplosi\w+",
    "invade": r"\binvad\w+|\binvasi\w+",
    "strike on": r"\bstrikes?\s+on\b",
    "execute": r"\bexecut(?:e|ed|ion|ions)\b|\bejecuci\w+",
}
CRISIS = (r"\bworld\s+war\s+(?:3|iii|three)\b", r"\bww\s?(?:3|iii)\b", r"\btercera\s+guerra\s+mundial\b",
          r"\bnuclear\s+(?:war|weapons?|strikes?|attack)\b", r"\bguerra\s+nuclear\b", r"\barmas?\s+nucleares?\b",
          r"\bnukes?\b")
EXTREMISM = (r"\bnazi(?:s|sm|smo)?\b", r"\bhitler\b", r"\bthird\s+reich\b", r"\bwaffen[\s-]?ss\b", r"\bss\s+officer\b",
             r"\bisis\b", r"\bal[\s-]?qaeda\b", r"\btaliban\b", r"\bkkk\b", r"\bku\s+klux\b")
GRAPHIC = (r"\bgore\b", r"\bcorpses?\b", r"\bdead\s+bodies\b", r"\bcad[aá]ver(?:es)?\b", r"\bdecapitat\w*",
           r"\bmutilat\w*", r"\bbloody\b")
SELF_HARM = (r"\bsuicid\w*", r"\bkilled\s+(?:him|her)self\b", r"\btook\s+(?:his|her)\s+own\s+life\b",
             r"\b(?:he|she)\s+jumped\b", r"\bjumped\s+to\s+(?:his|her)\s+death\b", r"\bse\s+lanz[oó]\b")
DRUGS = (r"\blsd\b", r"\bheroin[ae]?\b", r"\bcoca[ií]n[ae]\b", r"\bmeth(?:amphetamine)?\b", r"\boverdos\w*",
         r"\bsobredosis\b")

POLICIES = {
    "negacion": ("Desinformación: prohibidas las teorías que niegan hechos violentos documentados; "
                 "'false flag' es la etiqueta de esas teorías"),
    "conspiracion_violenta": "Desinformación: prohibidas las teorías conspirativas violentas o ligadas a violencia",
    "violencia_montada": ("Comportamientos violentos: ataques 'montados' contra un país o civiles se leen como "
                          "planificación de violencia, aunque sean historia"),
    "conspiracion": ("Feed Para ti: no elegibles las teorías infundadas que atribuyen hechos a grupos poderosos "
                     "u ocultos (el gobierno, una sociedad secreta)"),
    "violencia": "Comportamientos violentos: el clasificador cuenta el lenguaje violento junto",
    "crisis": "Desinformación en crisis: afirmaciones no verificadas sobre hechos en curso salen del feed o se revisan",
    "extremismo": "Organizaciones violentas y de odio: solo en contexto educativo, sin elogio ni símbolos",
    "explicito": "Contenido impactante y explícito",
    "autolesion": "Suicidio y autolesiones: TikTok es muy estricto con la muerte por mano propia",
    "drogas": "Drogas y sustancias reguladas: en contexto histórico se permite, pero el clasificador las marca",
}
FIXES = {
    "negacion": "Quita 'false flag' (también #FalseFlag). Atribuye al documento: 'a 1962 plan, declassified in 1997, proposed...'.",
    "conspiracion_violenta": ("No juntes el marco conspirativo con violencia: atribuye cada acto al documento "
                              "('the memo proposed'), saca #Conspiracy y deja las citas violentas solo dentro del video."),
    "violencia_montada": ("Di 'proposed fake incidents' o 'a pretext' sin repetir el acto violento en la misma frase; "
                          "fuera de la primera línea y de las tarjetas en pantalla."),
    "conspiracion": "Si está documentado, dilo ('declassified', 'Senate report') y usa #Declassified o #History en vez de #Conspiracy.",
    "violencia": "Suaviza la primera línea y las tarjetas; el detalle violento, mejor en el video o en una cita atribuida.",
    "crisis": "Plantéalo como pregunta, atribuye cada dato a una fuente con fecha y aclara que las imágenes son de archivo o ejercicios.",
    "extremismo": "Contexto histórico explícito (fecha y fuente) y nunca símbolos (esvástica, banderas) en portada o miniatura.",
    "explicito": "Evita describir cuerpos o heridas; TikTok limita o pone pantalla de aviso.",
    "autolesion": "Di 'died' o 'fell' sin describir el cómo; nunca 'he jumped' ni el método.",
    "drogas": "Nombra la sustancia una vez y en contexto ('the CIA tested LSD'); nada que parezca promoción.",
}
_ORDER = ("negacion", "conspiracion_violenta", "violencia_montada", "conspiracion", "violencia",
          "crisis", "extremismo", "explicito", "autolesion", "drogas")


@dataclass
class Finding:
    level: str
    rule: str
    fields: list = field(default_factory=list)
    matches: list = field(default_factory=list)

    @property
    def policy(self) -> str:
        return POLICIES[self.rule]

    @property
    def fix(self) -> str:
        return FIXES[self.rule]

    def line(self) -> str:
        donde = ", ".join(self.fields)
        que = ", ".join(f"'{m}'" for m in self.matches[:6])
        return f"{self.level.upper()} · {self.policy} ({donde}: {que}). Corrige: {self.fix}"


def _norm(text: Any) -> str:
    s = str(text or "").replace("’", "'").replace("‘", "'")
    # #FalseFlag -> "false flag", #WW3 -> "ww 3": el clasificador tambien lee los hashtags.
    s = re.sub(r"#(\w+)", lambda m: re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)", " ", m[1]), s)
    return " ".join(s.lower().split())


def _find(patterns: Iterable[str], text: str) -> list:
    hits = []
    for p in patterns:
        hits += [m.group(0) for m in re.finditer(p, text)]
    return hits


def _sentences(text: str) -> list:
    return [s for s in re.split(r"[.!?\n]+", text) if s.strip()]


def review(title: str = "", description: str = "", hashtags: Iterable[str] = (), on_screen: Iterable[str] = (),
           narration: str = "") -> list:
    """Hallazgos (mas graves primero) sobre todo lo que TikTok lee del post."""
    fields = {"título": _norm(title), "descripción": _norm(description),
              "hashtags": _norm(" ".join(f"#{str(h).lstrip('#')}" for h in hashtags or [])),
              "pantalla": _norm("\n".join(str(t) for t in on_screen or [])), "narración": _norm(narration)}
    found: dict = {}

    def add(rule, level, where, matches):
        f = found.setdefault(rule, Finding(level, rule))
        if where not in f.fields:
            f.fields.append(where)
        for m in matches:
            if m not in f.matches:
                f.matches.append(m)

    violent_kinds = set()
    for where, text in fields.items():
        if not text:
            continue
        for kind, pattern in VIOLENCE.items():
            if re.search(pattern, text):
                violent_kinds.add(kind)
    for where, text in fields.items():
        if not text:
            continue
        if hits := _find(FALSE_FLAG, text):
            add("negacion", BLOCK, where, hits)
        conspiracy = _find(CONSPIRACY, text)
        violent = [m.group(0) for p in VIOLENCE.values() for m in re.finditer(p, text)]
        if conspiracy and len(violent_kinds) >= 2:
            add("conspiracion_violenta", BLOCK, where, conspiracy + violent)
        elif conspiracy:
            add("conspiracion", WARN, where, conspiracy)
        if len(violent_kinds) >= 2:
            for s in _sentences(text):
                if _find(STAGED, s) and any(re.search(p, s) for p in VIOLENCE.values()):
                    add("violencia_montada", BLOCK, where, [" ".join(s.split()).strip(" \"'“”:,;")[:70]])
        if violent and len(violent_kinds) >= 2:      # una sola palabra ("exploded") es historia comun
            add("violencia", WARN, where, violent)
        for rule, patterns in (("crisis", CRISIS), ("extremismo", EXTREMISM), ("explicito", GRAPHIC),
                               ("autolesion", SELF_HARM), ("drogas", DRUGS)):
            if hits := _find(patterns, text):
                add(rule, WARN, where, hits)
    return sorted(found.values(), key=lambda f: (f.level != BLOCK, _ORDER.index(f.rule)))


def project_texts(project: dict) -> list:
    """Texto en pantalla de un proyecto Catarsis: tarjetas y frases sobre imagen."""
    cards = project.get("cards") or {}
    texts = [cards.get("opening"), *(cards.get("lines") or []), *(cards.get("climax") or []),
             *(cards.get("final") or []), cards.get("end")]
    texts += [s.get("text") for s in project.get("sequence") or [] if isinstance(s, dict)]
    return [str(t) for t in texts if t]


def review_project(project: dict) -> list:
    return review(on_screen=project_texts(project))


def review_metadata(meta: dict) -> list:
    """Metadata de subida (tiktok/instagram_metadata.json): titulo, descripcion, hashtags, guion."""
    on_screen = meta.get("on_screen_text") or []
    if isinstance(on_screen, str):
        on_screen = [on_screen]
    if isinstance(meta.get("cards"), dict):
        on_screen = list(on_screen) + project_texts({"cards": meta["cards"]})
    return review(title=meta.get("title", ""), description=meta.get("description", ""),
                  hashtags=meta.get("hashtags") or [], on_screen=on_screen, narration=meta.get("script_excerpt", ""))


def blocks(findings: Iterable[Finding]) -> bool:
    return any(f.level == BLOCK for f in findings)


def report(findings: Iterable[Finding]) -> list:
    return [f.line() for f in findings]


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Revisa un texto o proyecto contra las normas de TikTok antes de publicar")
    ap.add_argument("--texto", help="descripcion o texto del post")
    ap.add_argument("--titulo", default="")
    ap.add_argument("--archivo", help="archivo .txt con la descripcion")
    ap.add_argument("--proyecto", help="proyecto Catarsis (.json): revisa las tarjetas en pantalla")
    ap.add_argument("--metadata", help="tiktok_metadata.json / instagram_metadata.json")
    args = ap.parse_args(argv)
    findings: list = []
    try:
        if args.texto or args.archivo or args.titulo:
            texto = args.texto or (Path(args.archivo).read_text(encoding="utf-8") if args.archivo else "")
            findings += review(title=args.titulo, description=texto)
        if args.proyecto:
            findings += review_project(json.loads(Path(args.proyecto).read_text(encoding="utf-8")))
        if args.metadata:
            findings += review_metadata(json.loads(Path(args.metadata).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"ERROR: no se pudo leer el archivo ({exc})")
        return 1
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    for line in report(findings) or ["Sin hallazgos: nada de lo que las normas de TikTok suelen retirar."]:
        print(line)
    return 2 if blocks(findings) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
