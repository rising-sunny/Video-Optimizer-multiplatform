"""Metadatos del largo: titulo (vidIQ), capitulos, respuestas (palabras clave), atribucion de las 5 pistas y miniatura."""
import json
import shutil
from pathlib import Path

from . import long_states as LS
from . import long_thumb

TITLE = "Can You Identify All 50 US States by Outline? (Easy to Impossible)"      # patron de vidIQ (puntaje 96) + promesa de niveles
TAGS = ["us states quiz", "us geography quiz", "guess the us state", "50 states quiz", "united states quiz", "us map quiz", "us states",
        "states by outline", "geography quiz", "easy to impossible", "us quiz", "usa quiz", "map quiz", "general knowledge quiz", "quiz"]


def _ts(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def chapters(tl):
    out = []
    for seg in tl.plan:
        if seg["kind"] == "tier":
            out.append((0 if not out else seg["start"], f"Level {seg['num']} - {seg['label']}"))
        elif seg["kind"] == "outro":
            out.append((seg["start"], "Your rank"))
    return out                                         # la intro (6 s) va dentro del primer capitulo: YouTube exige >= 10 s por capitulo


def build(tl, attribution, out_dir):
    out_dir = Path(out_dir)
    data = LS.load()
    answers = []
    for ti, (num, label, states) in enumerate(LS.TIERS):
        order = [st for (i, _n, _l, st) in LS.order() if i == ti]
        answers.append(f"Level {num} ({label}): " + ", ".join(order))
    music = []
    for s0, track, attr in attribution:
        music.append(attr.strip() + f"\n(used from {_ts(s0)})")
    ch = "\n".join(f"{_ts(t)} {name}" for t, name in chapters(tl))
    desc = ("Can you name all 50 US states from their outline alone? 5 levels, from Easy to Impossible: three clues and a countdown for each state, "
            "then see exactly where it is on the map. Comment your rank below 👇\n\n"
            f"CHAPTERS\n{ch}\n\n"
            "ANSWERS (spoilers)\n" + "\n".join(answers) + "\n\n"
            "Every frame is drawn by code over open data (no AI images). Questions are fact-checked against Wikipedia. "
            "Map data: Natural Earth (public domain).\n\n"
            "A new expedition every day: subscribe to The Lost Atlas.\n\n"
            "#usgeography #geographyquiz #50states")
    tags, total = [], 0
    for tg in TAGS:
        if total + len(tg) + 1 <= 480:
            tags.append(tg)
            total += len(tg) + 1
    verified = all(v.get("verified") is True for v in data.values()) and len(data) == 50
    meta = dict(title=TITLE, description=desc, tags=tags, category_id="27", is_short=False, topic="geography quiz: all 50 US states by outline",
                upload_channel="the-lost-atlas", channel_profile="the-lost-atlas", template="long-us-states",
                fact_check="verified" if verified else "pending", music_attribution="Music:\n" + "\n\n".join(music),
                chapters=[dict(t=t, name=n) for t, n in chapters(tl)])
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "project.json").write_text(json.dumps({"video_path": str((out_dir / "long.mp4").resolve()), "config": {"upload_channel": "the-lost-atlas"}}, indent=1), encoding="utf-8")
    long_thumb.make(out_dir / "thumbnail.jpg")
    shutil.copy(LS.OUT, out_dir / "questions.json")
    return meta
