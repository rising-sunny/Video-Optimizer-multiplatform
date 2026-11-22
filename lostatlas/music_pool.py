"""Rotacion diaria de musica de The Lost Atlas: una pista distinta cada dia (Incompetech, CC BY 4.0).

Un reclamo de Content ID sobre un tema se resuelve poniendolo en lostatlas/data/music/claims.json (lista de titulos):
deja de rotar. Con 12 pistas y un tema por dia, cada una suena una vez cada 12 dias: la exposicion por tema es baja.
"""
import json
from pathlib import Path

POOL = ["Zanzibar", "Spy Glass", "Deadly Roulette", "Sauropod Spotting", "Secret of Tiki Island", "Hard Boiled",
        "Allada", "Journey To Ascend", "Rainbows", "Lord of the Land", "Teller of the Tales", "Mischief Maker"]
CLAIMS = Path(__file__).parent / "data" / "music" / "claims.json"


def available():
    claimed = set(json.loads(CLAIMS.read_text())) if CLAIMS.exists() else set()
    return [t for t in POOL if t not in claimed] or POOL


def pick(day_ordinal, offset=0):
    """Pista del dia. `offset` > 0 elige otra (reintentos tras un QA fallido)."""
    pool = available()
    return pool[(day_ordinal + offset) % len(pool)]
