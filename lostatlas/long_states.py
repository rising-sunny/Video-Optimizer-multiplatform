"""Largo horizontal "Name All 50 US States by Outline (Easy to Impossible)": niveles y preguntas verificadas.

    python -u -m lostatlas.long_states --gen      # genera/verifica pistas (reanuda lo ya hecho); ~20 min la primera vez
Cada estado: 3 pistas (de la mas dificil a la mas facil) escritas solo con Wikipedia y verificadas por el juez con cita literal
(mismo motor que los Shorts diarios). Se guarda en lostatlas/long/us_states.json (versionado).
"""
import json
import random
import sys
from pathlib import Path

from . import daily_gen as dg

OUT = Path(__file__).parent / "long" / "us_states.json"
TIERS = [
    ("I", "Easy", ["Texas", "Florida", "California", "Alaska", "Hawaii", "Michigan", "Louisiana", "New York", "Maine", "Oklahoma"]),
    ("II", "Medium", ["Massachusetts", "Virginia", "Maryland", "Nevada", "Idaho", "Georgia", "Washington", "Minnesota", "Illinois", "Ohio"]),
    ("III", "Hard", ["Pennsylvania", "North Carolina", "South Carolina", "Kentucky", "Tennessee", "West Virginia", "Missouri", "Arizona", "New Mexico", "Oregon"]),
    ("IV", "Very Hard", ["Alabama", "Mississippi", "Arkansas", "Indiana", "Wisconsin", "Iowa", "New Jersey", "Connecticut", "Delaware", "Utah"]),
    ("V", "Impossible", ["Colorado", "Wyoming", "Kansas", "Nebraska", "South Dakota", "North Dakota", "Montana", "Vermont", "New Hampshire", "Rhode Island"]),
]


def order():
    """[(nivel_idx, numeral, nombre_nivel, estado)] en orden de juego (dentro de cada nivel, mezcla fija)."""
    rng = random.Random(50)
    out = []
    for i, (num, label, states) in enumerate(TIERS):
        s = states[:]
        rng.shuffle(s)
        out += [(i, num, label, st) for st in s]
    return out


def load():
    return json.loads(OUT.read_text()) if OUT.exists() else {}


def generate():
    done = load()
    for i, num, label, st in order():
        if st in done and done[st].get("verified"):
            continue
        forb = [st] + ([st.split()[-1]] if len(st.split()) > 1 and len(st.split()[-1]) > 4 else [])
        q = None
        for attempt in range(3):
            q = dg._verified_question(
                dict(state=st, tier=i, tier_label=label), st, st, "geo", [f"{st} (U.S. state)", f"{st} U.S. state"], forb,
                lambda clues, st=st: [f'About the U.S. state of {st}: "{c}"' for c in clues], log=lambda m: print(m, flush=True))
            if q:
                break
        if q:
            done[st] = q
            OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False))
        else:
            print(f"   !! {st}: sin pistas verificadas tras 3 intentos", flush=True)
    print(f"LISTO: {sum(1 for v in done.values() if v.get('verified'))}/50 verificados", flush=True)


if __name__ == "__main__":
    if "--gen" in sys.argv:
        generate()
