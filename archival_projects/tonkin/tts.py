"""Narracion por bloque con edge-tts (voz del repo, en-US-GuyNeural) y los limites de frase para el SRT."""
import asyncio, json, os, sys
import certifi
certifi.where = lambda: "/root/.ccr/ca-bundle.crt"   # CA del proxy del entorno (no se desactiva la verificacion)
import edge_tts
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from script import SCRIPT
VOICE, RATE = "en-US-GuyNeural", "-6%"

async def one(i, text):
    out, subs = f"tts/b{i:02d}.mp3", []
    if os.path.exists(out) and os.path.exists(out + ".json"):
        return
    c = edge_tts.Communicate(text, VOICE, rate=RATE, proxy=os.environ.get("HTTPS_PROXY"), boundary="SentenceBoundary")
    with open(out, "wb") as fh:
        async for ch in c.stream():
            if ch["type"] == "audio":
                fh.write(ch["data"])
            elif ch["type"] in ("SentenceBoundary", "WordBoundary"):
                subs.append({"start": ch["offset"] / 1e7, "dur": ch["duration"] / 1e7, "text": ch["text"]})
    json.dump(subs, open(out + ".json", "w"))

async def main():
    for i, item in enumerate(SCRIPT):
        if item[0] != "card":
            await one(i, item[0])
asyncio.run(main()); print("ok")
