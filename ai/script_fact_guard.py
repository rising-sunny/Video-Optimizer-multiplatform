# -*- coding: utf-8 -*-
"""Auditoria de veracidad del guion contra la investigacion que lo origino.

Que problema resuelve. El pipeline ya validaba que el guion NO fuera un rechazo
del LLM, que tuviera el largo pedido y que hablara del tema. Ninguna de esas
tres mira si lo que DICE es cierto. Y el canal se apoya en cifras: los ganchos
son "50 toneladas", "20.000 habitantes", "385 kilometros". Un numero inventado
en el gancho es el error mas caro posible, porque es justo lo que la gente
recuerda y lo que aparece en los comentarios.

Como funciona. No se le pregunta al LLM si mintio -- eso es pedirle al mismo
modelo que se autocalifique. Se contrasta contra el corpus de investigacion que
el pipeline YA descargo (Wikipedia + busqueda) antes de escribir el guion:

  1. Se extraen las afirmaciones comprobables: cifras, magnitudes y anios.
  2. Cada una se busca en el corpus. Los anios exigen coincidencia exacta; las
     cantidades toleran el redondeo normal de una narracion ("unos 20.000"
     contra "19.870" es correcto, no un invento).
  3. Lo que no aparece en ninguna fuente se marca para revisar.

Y la parte que vale para misterios y teorias: no importa si el tema es un hecho
documentado o una hipotesis discutida; lo que importa es que el guion las
DISTINGA. Si las fuentes matizan ("se cree", "algunos investigadores",
"disputado") y el guion afirma en seco, se avisa. Un canal puede hablar de
teorias sin problema; lo que no puede es presentarlas como hechos.

Es puro: sin red, sin LLM, sin PIL. Ver `test_script_fact_guard.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence

# Tolerancia al redondeo de una narracion. "Casi 20.000" para una fuente que
# dice 19.870 es correcto; no vale marcarlo como invento.
NUMBER_TOLERANCE = 0.05

# Los anios NO toleran nada: 1453 y 1454 son hechos distintos.
YEAR_MIN, YEAR_MAX = 1000, 2100

# Debajo de esto no se audita: "los 3 hermanos", "una de las 2 puertas" son
# ruido, no afirmaciones que alguien vaya a discutir.
MIN_AUDITABLE_NUMBER = 10

# Porcentaje de cifras respaldadas a partir del cual el guion se da por bueno.
COVERAGE_OK = 0.70

_MULTIPLIERS = {
    "mil": 1_000, "thousand": 1_000, "k": 1_000,
    "millon": 1_000_000, "millones": 1_000_000, "million": 1_000_000,
    "billon": 1_000_000_000, "billion": 1_000_000_000,
}

# Marcadores de que una afirmacion es hipotesis y no hecho establecido.
HEDGE_MARKERS = (
    # espanol
    "se cree", "se piensa", "podria", "podrian", "quiza", "quizas", "tal vez",
    "algunos investigadores", "algunos historiadores", "se estima", "estiman",
    "hipotesis", "teoria", "teorias", "disputad", "debatid", "no se sabe",
    "probablemente", "al parecer", "segun algunos", "presuntamente", "supuest",
    # ingles
    "believed", "thought to", "may have", "might have", "could have",
    "some researchers", "some historians", "estimated", "hypothesis",
    "theory", "theories", "disputed", "debated", "unclear", "probably",
    "apparently", "allegedly", "presumably", "suggests", "argue",
)

# Unidades que convierten un numero en una MAGNITUD y no en un anio.
_UNIT_WORDS = (
    "kg", "kilos", "kilogramos", "toneladas", "tons", "tonnes", "ton",
    "metros", "meters", "metres", "m", "km", "kilometros", "kilometres",
    "kilometers", "millas", "miles", "hectareas", "hectares", "acres",
    "anios", "anos", "years", "siglos", "centuries", "dias", "days",
    "horas", "hours", "minutos", "minutes", "segundos", "seconds",
    "habitantes", "personas", "people", "soldados", "soldiers", "hombres",
    "men", "muertos", "dead", "islas", "islands", "islotes", "islets",
    "piedras", "stones", "bloques", "blocks", "pies", "feet", "ft",
)


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(texto or ""))
        if not unicodedata.combining(c)
    )


@dataclass
class Claim:
    """Una afirmacion comprobable extraida del guion."""

    kind: str          # "year" | "number"
    raw: str           # tal cual aparece
    value: float       # normalizado
    sentence: str      # la frase que la contiene
    supported: Optional[bool] = None
    matched_with: Optional[float] = None


@dataclass
class FactReport:
    claims: List[Claim] = field(default_factory=list)
    unsupported: List[Claim] = field(default_factory=list)
    coverage: float = 0.0
    verdict: str = "sin_investigacion"
    hedging: dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict in ("ok", "sin_investigacion", "sin_cifras")


# ------------------------------------------------------------------ numeros

def normalize_number(raw: str) -> Optional[float]:
    """Convierte '20,000' / '20.000' / '1.5' / '20 mil' a un float.

    El separador de miles cambia de idioma: en ingles '20,000' son veinte mil
    y en espanol lo son '20.000'. Se decide por la FORMA (grupos de tres
    digitos), no por el idioma, que no siempre se sabe.
    """
    texto = _sin_tildes(str(raw or "")).strip().lower()
    if not texto:
        return None

    multiplicador = 1
    for palabra, factor in _MULTIPLIERS.items():
        if re.search(r"\b%s\b" % re.escape(palabra), texto):
            multiplicador = factor
            texto = re.sub(r"\b%s\b" % re.escape(palabra), " ", texto)
            break

    texto = texto.replace(" ", "")
    m = re.search(r"\d[\d.,]*", texto)
    if not m:
        return None
    numero = m.group(0).rstrip(".,")

    # Grupos de exactamente tres digitos tras el separador => miles.
    if re.fullmatch(r"\d{1,3}(?:([.,])\d{3})+", numero):
        return float(re.sub(r"[.,]", "", numero)) * multiplicador
    # Un solo separador con 1-2 digitos detras => decimal.
    if re.fullmatch(r"\d+[.,]\d{1,2}", numero):
        return float(numero.replace(",", ".")) * multiplicador
    try:
        return float(re.sub(r"[.,]", "", numero)) * multiplicador
    except ValueError:
        return None


def _dividir_en_frases(texto: str) -> List[str]:
    partes = re.split(r"(?<=[.!?])\s+|\n+", str(texto or ""))
    return [p.strip() for p in partes if p.strip()]


def extract_claims(script: str) -> List[Claim]:
    """Saca del guion las cifras y anios que se pueden contrastar."""
    claims: List[Claim] = []
    for frase in _dividir_en_frases(script):
        plana = _sin_tildes(frase).lower()
        for m in re.finditer(r"\b\d[\d.,]*\b(?:\s*(?:mil|thousand|millones?|million|billion)\b)?",
                             plana):
            crudo = m.group(0)
            valor = normalize_number(crudo)
            if valor is None or valor < MIN_AUDITABLE_NUMBER:
                continue

            # .Anio o magnitud? Si detras viene una unidad, es magnitud.
            resto = plana[m.end():m.end() + 24].strip()
            unidad_detras = any(
                re.match(r"^%s\b" % re.escape(u), resto) for u in _UNIT_WORDS
            )
            es_anio = (
                not unidad_detras
                and float(valor).is_integer()
                and YEAR_MIN <= valor <= YEAR_MAX
                and "," not in crudo and "." not in crudo
            )
            claims.append(Claim(
                kind="year" if es_anio else "number",
                raw=crudo, value=float(valor), sentence=frase,
            ))
    return claims


def corpus_numbers(research_context: Optional[Iterable]) -> List[float]:
    """Todas las cifras que aparecen en la investigacion."""
    valores: List[float] = []
    for bloque in (research_context or []):
        texto = _sin_tildes(str(bloque or "")).lower()
        for m in re.finditer(r"\b\d[\d.,]*\b(?:\s*(?:mil|thousand|millones?|million|billion)\b)?",
                             texto):
            v = normalize_number(m.group(0))
            if v is not None:
                valores.append(float(v))
    return valores


def _respaldada(claim: Claim, valores: Sequence[float]) -> Optional[float]:
    for v in valores:
        if claim.kind == "year":
            if v == claim.value:
                return v
            continue
        if claim.value == 0:
            if v == 0:
                return v
            continue
        if abs(v - claim.value) / abs(claim.value) <= NUMBER_TOLERANCE:
            return v
    return None


# ----------------------------------------------------------------- matices

def count_hedges(texto: str) -> int:
    plana = _sin_tildes(texto).lower()
    return sum(plana.count(_sin_tildes(m)) for m in HEDGE_MARKERS)


def hedging_balance(script: str, research_context: Optional[Iterable]) -> dict:
    """.El guion distingue hipotesis de hecho, como lo hacen las fuentes?

    Sirve igual para historia documentada que para misterios o teorias: no se
    juzga el TEMA, se juzga si el guion respeta el grado de certeza de las
    fuentes. Si la investigacion esta llena de "se cree" y "algunos
    investigadores" y el guion afirma todo en seco, esta convirtiendo una
    hipotesis en un hecho.
    """
    corpus = " ".join(str(b or "") for b in (research_context or []))
    fuentes = count_hedges(corpus)
    guion = count_hedges(script)
    # Se exige matiz solo cuando las fuentes matizan de forma marcada.
    exige = fuentes >= 3
    return {
        "hedges_fuentes": fuentes,
        "hedges_guion": guion,
        "fuentes_matizan": exige,
        "ok": (not exige) or guion >= 1,
    }


# ------------------------------------------------------------------ informe

def audit_script(script: str, research_context: Optional[Iterable] = None) -> FactReport:
    """Audita el guion contra la investigacion. Nunca lanza."""
    report = FactReport()
    texto = str(script or "").strip()
    if not texto:
        report.verdict = "sin_guion"
        return report

    report.claims = extract_claims(texto)
    report.hedging = hedging_balance(texto, research_context)

    valores = corpus_numbers(research_context)
    if not valores:
        # Sin investigacion no se puede afirmar nada: callarse es mejor que
        # inventar una alarma. Es la misma regla que en la validacion de tema.
        report.verdict = "sin_investigacion"
        report.warnings.append(
            "no hay investigacion para contrastar: las cifras quedan sin verificar")
        if not report.hedging["ok"]:
            report.warnings.append("las fuentes matizan y el guion afirma en seco")
        return report

    if not report.claims:
        report.verdict = "sin_cifras"
        report.warnings.append("el guion no trae cifras verificables")
        return report

    for claim in report.claims:
        encontrado = _respaldada(claim, valores)
        claim.supported = encontrado is not None
        claim.matched_with = encontrado
        if not claim.supported:
            report.unsupported.append(claim)

    respaldadas = len(report.claims) - len(report.unsupported)
    report.coverage = respaldadas / float(len(report.claims))

    anios_sueltos = [c for c in report.unsupported if c.kind == "year"]
    if anios_sueltos:
        report.warnings.append(
            "anio(s) sin respaldo: " + ", ".join(sorted({c.raw for c in anios_sueltos})))
    cifras_sueltas = [c for c in report.unsupported if c.kind == "number"]
    if cifras_sueltas:
        report.warnings.append(
            "cifra(s) sin respaldo: " + ", ".join(sorted({c.raw for c in cifras_sueltas})))
    if not report.hedging["ok"]:
        report.warnings.append(
            "las fuentes presentan esto como hipotesis y el guion lo afirma como hecho")

    report.verdict = "ok" if (
        report.coverage >= COVERAGE_OK and not anios_sueltos and report.hedging["ok"]
    ) else "revisar"
    return report


def format_report(report: FactReport, max_lineas: int = 6) -> List[str]:
    """El informe en lineas listas para el log del ensamblaje."""
    lineas = []
    if report.verdict == "sin_guion":
        return ["  [--] Verificacion de datos: no hay guion"]
    if report.verdict == "sin_investigacion":
        lineas.append("  [--] Verificacion de datos: sin investigacion para contrastar")
    elif report.verdict == "sin_cifras":
        lineas.append("  [--] Verificacion de datos: el guion no trae cifras")
    elif report.verdict == "ok":
        lineas.append("  [OK] Datos: %d/%d cifras respaldadas por la investigacion"
                      % (len(report.claims) - len(report.unsupported), len(report.claims)))
    else:
        lineas.append("  [FAIL] Datos: solo %d/%d cifras respaldadas (%.0f%%)"
                      % (len(report.claims) - len(report.unsupported),
                         len(report.claims), report.coverage * 100))

    for claim in report.unsupported[:max_lineas]:
        lineas.append("         sin respaldo: %-10s -> %s" % (claim.raw, claim.sentence[:88]))
    if len(report.unsupported) > max_lineas:
        lineas.append("         (y %d mas)" % (len(report.unsupported) - max_lineas))
    for aviso in report.warnings:
        if not aviso.startswith(("anio(s)", "cifra(s)")):
            lineas.append("         %s" % aviso)
    return lineas


__all__ = [
    "Claim", "FactReport", "NUMBER_TOLERANCE", "COVERAGE_OK",
    "normalize_number", "extract_claims", "corpus_numbers",
    "count_hedges", "hedging_balance", "audit_script", "format_report",
]
