"""Empaqueta un Short de The Lost Atlas para publish.youtube_uploader.upload_from_metadata.

Mismo formato que codeart/make_short.py: la carpeta queda con metadata.json (titulo, descripcion, tags,
atribuciones) + project.json (video_path y upload_channel). No sube nada: eso es lostatlas/upload.py.
"""
import json
from pathlib import Path

CHANNEL = "the-lost-atlas"

TEMPLATES = {
    "geo": dict(
        title="Name These {n} Countries in 5 Seconds Each 🌍 | Geography Quiz #shorts",
        hook="Can you name the country from its outline and three clues?",
        topic="geography quiz: guess the country",
        tags=["geography quiz", "guess the country", "country quiz", "world geography", "map quiz"]),
    "year": dict(
        title="Guess the Year of These {n} Historic Events ⏳ | History Quiz #shorts",
        hook="Can you guess the year before the last drum locks into place?",
        topic="history quiz: guess the year",
        tags=["history quiz", "guess the year", "history trivia", "historical events", "world history"]),
    "empire": dict(
        title="Name the Empire From the Map 🗺️ | History Quiz #shorts",
        hook="Can you name the empire from a map, a date and three clues?",
        topic="history quiz: guess the empire",
        tags=["history quiz", "guess the empire", "ancient empires", "historical maps", "world history"]),
}
BASE_TAGS = ["quiz", "trivia", "general knowledge", "brain test", "can you guess", "shorts"]
HASHTAGS = {"geo": "#shorts #quiz #geography #trivia", "year": "#shorts #quiz #history #trivia", "empire": "#shorts #quiz #history #maps"}


def build_metadata(template, questions, music_attribution=None, extra_attribution=None):
    t = TEMPLATES[template]
    n = len(questions)
    title = t["title"].format(n=n)
    verified = all(q.get("verified") is True for q in questions)
    body = (f"{t['hook']} {n} rounds, 5 seconds each. Comment your score below 👇\n\n"
            "Every frame of this quiz is drawn by code over open data (no AI images). "
            + ("Questions are fact-checked. " if verified else "")
            + ("Historical borders are approximate.\n\n" if template == "empire" else "\n\n")
            + "New expedition every day: subscribe to The Lost Atlas.")
    attribution = "\n\n".join(a.strip() for a in (music_attribution, extra_attribution) if a and a.strip())
    description = body + "\n\n" + HASHTAGS[template]
    tags, total = [], 0
    for tg in t["tags"] + BASE_TAGS:
        if tg not in tags and total + len(tg) + 1 <= 480:
            tags.append(tg)
            total += len(tg) + 1
    meta = dict(title=title[:100], description=description, tags=tags, category_id="27", is_short=True, topic=t["topic"],
                upload_channel=CHANNEL, channel_profile=CHANNEL, template=template,
                fact_check="pending" if not all(q.get("verified") is True for q in questions) else "verified")
    if attribution:
        meta["music_attribution"] = attribution          # el uploader lo inserta antes de los hashtags, sin recortarlo
    return meta


def write_package(folder, mp4, template, questions, music_attribution=None, extra_attribution=None):
    folder = Path(folder)
    meta = build_metadata(template, questions, music_attribution, extra_attribution)
    (folder / "metadata.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (folder / "project.json").write_text(json.dumps({"video_path": str(Path(mp4).resolve()), "config": {"upload_channel": CHANNEL}}, indent=1), encoding="utf-8")
    return meta
