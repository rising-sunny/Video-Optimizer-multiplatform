"""Empaqueta un Short de The Lost Atlas para publish.youtube_uploader.upload_from_metadata.

Mismo formato que codeart/make_short.py: la carpeta queda con metadata.json (titulo, descripcion, tags,
atribuciones) + project.json (video_path y upload_channel). No sube nada: eso es lostatlas/upload.py.
"""
import json
from pathlib import Path

CHANNEL = "the-lost-atlas"

# Titulos: patrones de vidIQ (generate_titles, type=short, 2026-11-22, puntaje 82-98) sobre competidores reales del nicho.
# Se descartaron los que afirman estadisticas que no podemos respaldar ("Only 1% can...").
# Palabras clave (keyword research): "guess the country by outline" (vol 62, competencia 32), "history trivia" (+87 %, comp 31),
# "ancient history quiz" (comp 23), "geography quiz" (130 mil busquedas/mes).
TEMPLATES = {
    "geo": dict(
        titles=["Guess The Country Challenge: Are You A Geography Expert? 🧠 #shorts",
                "Guess The Country Before Time Runs Out! ⏱️ #challenge #shorts",
                "Guess The Country By Outline In 5 Seconds! ⏱️ #geographyquiz #shorts",
                "How Many Countries Can You Identify? 🗺️ #trivia #geography",
                "5 Seconds To Guess The Country! ⏳ #geographyquiz #challenge",
                "Think You Know Geography? Prove It! 🌍 #quiz #shorts",
                "Can You Guess All 5 Countries By Outline? 🌍🧠 #geography #quiz"],
        hook="Guess the country by outline: 5 rounds, 3 clues each and 5 seconds on the clock.",
        topic="geography quiz: guess the country by outline",
        hashtags="#geographyquiz #quiz #shorts",
        tags=["guess the country by outline", "guess the country", "guess the country by shape", "guess the country by map", "guess the country quiz",
              "geography quiz", "geography trivia", "world geography quiz", "geography challenge", "country quiz", "map quiz"]),
    "year": dict(
        titles=["Can You Beat the Clock? Guess the Historic Year ⏱️ #history #games",
                "How Well Do You Know History? | Guess the Year #historyquiz #shorts",
                "Can You Get 5/5? Guess the Year of These Events ⏳ #history #trivia",
                "The 5-Second History Challenge: Guess the Year #history #challenge",
                "Guess the Year Before the Odometer Stops! 🕰️ #history #shorts",
                "Guess the Year: History Edition #history #trivia #shorts",
                "Test Your Knowledge: Guess the Historic Year #historytrivia #shorts"],
        hook="History trivia: guess the year of 5 famous events from 3 clues before the odometer locks.",
        topic="history quiz: guess the year",
        hashtags="#historytrivia #historyquiz #shorts",
        tags=["history trivia", "history quiz", "guess the year", "history trivia quiz", "ancient history quiz", "world history quiz", "historical events",
              "history challenge", "history general knowledge quiz"]),
    "empire": dict(
        titles=["Only a genius gets 5/5 on this map quiz 🧠 #history #geography #quiz",
                "Can you guess these empires before the timer? ⏱️ #history #map #quiz",
                "Think you know world history? Prove it. 🔥 #history #quiz #geography",
                "How well do you know history? 🗺️ #history #quiz #shorts",
                "Guess the Empire: History Quiz Edition ⌛ #history #quiz #map",
                "Beat the 5-second countdown: History Quiz ⌛ #history #geography #quiz",
                "Can you name all 5 empires? 🌍 #history #quiz #geography",
                "Identify the empire from the map 🗺️ #history #quiz #shorts"],
        hook="History trivia: name the empire from a historical map, a date and 3 clues.",
        topic="history quiz: guess the empire from a historical map",
        hashtags="#historyquiz #history #shorts",
        tags=["guess the empire", "history trivia", "history quiz", "historical maps", "ancient history quiz", "ancient empires", "map quiz", "world history quiz",
              "history trivia quiz"]),
}
BASE_TAGS = ["quiz", "trivia", "general knowledge quiz", "brain test", "can you guess", "shorts"]


def _answers_line(template, questions):
    if template == "year":
        items = [f'{q["title"]} ({abs(q["year"])}{" BC" if q["year"] < 0 else ""})' for q in questions]
    else:
        items = [q["country"] for q in questions]
    return "Answers (spoilers): " + ", ".join(items)


def build_metadata(template, questions, music_attribution=None, extra_attribution=None, day_index=0):
    t = TEMPLATES[template]
    n = len(questions)
    title = t["titles"][day_index % len(t["titles"])]
    verified = all(q.get("verified") is True for q in questions)
    body = (f"{t['hook']}\nHow many did you get? Comment your score below 👇\n\n"
            + _answers_line(template, questions) + "\n\n"
            "Every frame is drawn by code over open data (no AI images). "
            + ("Questions are fact-checked against Wikipedia. " if verified else "")
            + ("Historical borders are approximate.\n\n" if template == "empire" else "\n\n")
            + "A new expedition every day: subscribe to The Lost Atlas.")
    attribution = "\n\n".join(a.strip() for a in (music_attribution, extra_attribution) if a and a.strip())
    description = body + "\n\n" + t["hashtags"]
    tags, total = [], 0
    for tg in t["tags"] + BASE_TAGS:
        if tg not in tags and total + len(tg) + 1 <= 480:
            tags.append(tg)
            total += len(tg) + 1
    meta = dict(title=title[:100], description=description, tags=tags, category_id="27", is_short=True, topic=t["topic"],
                upload_channel=CHANNEL, channel_profile=CHANNEL, template=template,
                fact_check="verified" if verified else "pending")
    if attribution:
        meta["music_attribution"] = attribution          # el uploader lo inserta antes de los hashtags, sin recortarlo
    return meta


def write_package(folder, mp4, template, questions, music_attribution=None, extra_attribution=None, day_index=0):
    folder = Path(folder)
    meta = build_metadata(template, questions, music_attribution, extra_attribution, day_index)
    (folder / "metadata.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (folder / "project.json").write_text(json.dumps({"video_path": str(Path(mp4).resolve()), "config": {"upload_channel": CHANNEL}}, indent=1), encoding="utf-8")
    return meta
