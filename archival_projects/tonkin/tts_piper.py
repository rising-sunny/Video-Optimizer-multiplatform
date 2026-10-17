"""Narracion offline con Piper (en_US-ryan-high) cuando Edge TTS no responde: una frase por vez, para tener los
limites de frase del SRT. Escribe tts/bNN.mp3 y tts/bNN.mp3.json igual que tts.py."""
import json, os, re, subprocess, sys, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from script import SCRIPT
import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()
VOICE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "piper", "en_US-ryan-high.onnx")
from piper import PiperVoice
from piper.config import SynthesisConfig
voice = PiperVoice.load(VOICE)
cfg = SynthesisConfig(length_scale=1.18)
GAP = 0.42

def sentences(text):
    return [s for s in re.split(r"(?<=[.?!:])\s+(?=[A-Z0-9])", text.strip()) if s]

for i, item in enumerate(SCRIPT):
    if item[0] == "card":
        continue
    out = f"tts/b{i:02d}.mp3"
    if os.path.exists(out) and os.path.exists(out + ".json"):
        continue
    chunks, subs, t = [], [], 0.1
    sr = voice.config.sample_rate
    chunks.append(np.zeros(int(0.1 * sr), np.int16))
    for s in sentences(item[0]):
        pcm = np.concatenate([np.frombuffer(c.audio_int16_bytes, np.int16) for c in voice.synthesize(s, syn_config=cfg)])
        d = len(pcm) / sr
        subs.append({"start": round(t, 3), "dur": round(d, 3), "text": s})
        chunks += [pcm, np.zeros(int(GAP * sr), np.int16)]; t += d + GAP
    pcm = np.concatenate(chunks)
    wav = out[:-4] + ".wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
    subprocess.run([FF, "-v", "error", "-y", "-i", wav, "-b:a", "160k", out], check=True); os.remove(wav)
    json.dump(subs, open(out + ".json", "w")); print(i, round(t, 1))
