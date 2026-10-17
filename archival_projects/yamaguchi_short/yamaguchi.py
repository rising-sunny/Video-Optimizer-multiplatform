"""Short Catarsis (Stunning Facts of History): Tsutomu Yamaguchi, sobreviviente de Hiroshima y Nagasaki. "A Tale of Two Cities" (War Dept. 1946), NARA 111-ADC-10038, USSBS USAF-11075."""
import subprocess, sys
from pathlib import Path
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
from PIL import Image, ImageDraw
from catharsis import catharsis_editor as ce
here = Path(__file__).resolve().parent
f = lambda n: str(here / n)
T, A, U = f("dl/TaleofTw1946_edit.mp4"), f("dl/111-adc-10038.mp4"), f("dl/USAF-11075.mp4")
V = lambda fn, a, z, fx=0.5, fy=0.5, zoom=1.0: {"file": fn, "in": a, "out": z, "focus": [fx, fy], "zoom": zoom}
P = lambda n, fx=0.5, fy=0.5: {"file": f(n), "focus": [fx, fy]}
project = {
    "topic": "Tsutomu Yamaguchi, survivor of Hiroshima and Nagasaki, August 1945", "perspective": "narrator", "language": "en", "seconds": 44,
    "cards": {
        "direction": {"speaker": "Narrador externo; sujeto focal: Tsutomu Yamaguchi, ingeniero de Mitsubishi",
                      "moment": "6 de agosto de 1945 en Hiroshima; 9 de agosto en Nagasaki; reconocimiento oficial en 2009",
                      "conflict": "Sobrevive a la bomba de Hiroshima a 3 km y vuelve herido a su ciudad",
                      "turn": "En Nagasaki, mientras le cuenta a su jefe lo de Hiroshima, cae la segunda bomba",
                      "payoff": "Vivio hasta los 93; en 2009 Japon lo reconocio como sobreviviente de ambas"},
        "opening": "He survived Hiroshima. Then he went home… to Nagasaki.",
        "lines": ["Tsutomu Yamaguchi, 29. He designed ships.", "August 6, 1945. Hiroshima. 8:15 a.m.",
                  "He went back for his name stamp.", "3 km from the blast.", "Eardrums burst. His left side burned.",
                  "Next day, he took the train home.", "Home was Nagasaki.", "August 9. Bandaged, he went to work.",
                  "He described Hiroshima to his boss.", "His boss called him crazy. Then: the flash."],
        "climax": ["HIROSHIMA", "NAGASAKI", "SURVIVOR"],
        "final": ["He lived to 93.", "In 2009, Japan officially recognized him: survivor of both."],
        "end": "Tsutomu Yamaguchi, 1916–2010"},
    "media": [
        V(T, 606.0, 613.0), V(T, 66.0, 79.0), V(T, 91.0, 101.0), V(T, 33.0, 57.0), V(T, 134.0, 147.0),     # 0 Mitsubishi, 1 B-29, 2 mapa, 3 nube Hiroshima, 4 arboles
        V(A, 64.0, 90.0), V(T, 514.5, 521.5), V(T, 613.0, 621.0), V(T, 103.0, 134.0), V(U, 402.0, 440.0),  # 5 tranvia, 6 mapa Japon, 7 Mitsubishi, 8 ruinas, 9 color
        V(T, 557.0, 583.0, 0.5, 0.4), V(T, 521.0, 533.0), V(A, 32.0, 52.0), V(T, 303.0, 313.0), V(U, 266.0, 300.0),  # 10 nube Nagasaki, 11 B-29, 12-13 domo, 14 color
        V(T, 642.0, 672.0), V(A, 216.0, 231.0),                                                               # 15 ruinas Nagasaki, 16 estacion
        P("cloud_still.png", 0.5, 0.4), P("dome_still.png"),                                                  # 17-18 impactos
    ],
    "music": str(here / "musica_yamaguchi.wav"), "music_start": 0.0, "music_auto": False,
    "style": {"speed": 1.2, "flashes": 1.0, "variants": ["base", "negative", "hard", "red", "sketch"],
              "transitions": ["glitch", "burn"]},
}
proj = ce.normalize_project(project)
ce._validate_generated_cards(proj["cards"])
# Los cortes siguen la grilla original (la pista ad hoc se compuso sobre ella: quiebre 33.7-35.17 s)
beats, drop = ce.music_analysis(str(here.parent / "trinity" / "rud.mp3"), proj["seconds"], 109.51)
seq = ce.auto_sequence(proj, beats, seed=1945, drop=drop)
L = proj["cards"]["lines"]
at = lambda text: next(i for i, s in enumerate(seq) if s.get("text") == text)
nxt = lambda k: next(i for i in range(k + 1, len(seq)) if seq[i]["kind"] == "media")
med = lambda m, d, variant, act, motion="push": {"kind": "media", "media": m, "variant": variant, "seconds": d, "motion": motion,
                                                 "transition": "cut", "offset": 0.0, "audio": False, "act": act}
plan = {L[0]: 0, L[1]: 1, L[2]: 2, L[3]: 3, L[4]: 4, L[5]: 5, L[6]: 6, L[7]: 7, L[8]: 8, L[9]: 9}
over = [s.get("text") for s in seq if s["kind"] == "overlay"]
for line in over:
    seq[at(line)].update(media=plan[line], variant="base", offset=0.0)
for line, m in plan.items():
    if line not in over:
        seq[nxt(at(line))].update(media=m, variant="base", offset=0.0)
op = next(i for i, s in enumerate(seq) if s["act"] == "open" and s["kind"] == "media")
seq[op] = {"kind": "double", "media": 3, "media2": 10, "variant": "base", "seconds": seq[op]["seconds"], "motion": "push", "transition": "cut", "act": "open"}
next(s for s in seq if s["kind"] == "split").update(medias=[3, 10, 15], variant="base")
db = next(i for i, s in enumerate(seq) if s["kind"] == "double" and s["act"] == "rise")
seq[db].update(media=8, media2=15, variant="base")
cyc = [3, 10, 8, 15, 12, 14, 4, 9, 1, 11, 13, 16]
for n, s in enumerate(s for s in seq if s["act"] == "climax" and s["kind"] == "media"):
    s["media"] = cyc[n % len(cyc)]; s["offset"] = 0.0
for n, s in enumerate(s for s in seq if s["kind"] == "impact"):
    s["media"] = (17, 18)[n % 2]
k = next(i for i, s in enumerate(seq) if s.get("tag") == "break") + 1
F = sum(s["seconds"] for s in seq[k:])
card = lambda text, st, d, kin=True: {"kind": "card", "text": text, "style": st, "seconds": d, "kinetic": kin, "transition": "cut", "motion": "hold", "act": "final"}
a, b = round(0.17 * F, 3), round(0.24 * F, 3)
seq[k:] = [med(10, a, "base", "final"), card(proj["cards"]["final"][0], "invert", b), med(12, a, "color", "final"),
           card(proj["cards"]["final"][1], "invert", b), card(proj["cards"]["end"], "caption", round(F - 2 * a - 2 * b - 0.6, 3), False),
           card(proj["cards"]["opening"], "center", 0.6, False)]
t, pts = 0.0, []
for s in seq:
    if s["act"] != "climax" or s["kind"] == "card":
        pts.append((f'{s["kind"][:4]} {s.get("media", s.get("medias", ""))} {(s.get("text") or "")[:10]}', t + min(0.35, s["seconds"] / 2)))
    t += s["seconds"]
print("caida", round(drop or 0, 2), "| planos", len(seq), "| total", round(t, 2))
if __name__ == "__main__":
    shots, marks = ce.build_shots(proj, seq)
    print("quiebre", [round(x, 2) for x in marks["break"]])
    out = here / "yamaguchi_final.mp4"
    ce.render(shots, out, music=proj["music"], break_span=marks["break"], sfx=True, loop=True, music_start=proj["music_start"])
    pts = pts[:40]
    sheet = Image.new("RGB", (180 * 10, 320 * ((len(pts) + 9) // 10)))
    for i, (key, tt) in enumerate(pts):
        raw = subprocess.run([ce._ffmpeg(), "-loglevel", "error", "-ss", f"{tt:.3f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=180:320", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if len(raw) >= 180 * 320 * 3:
            im = Image.frombytes("RGB", (180, 320), raw[:180 * 320 * 3]); ImageDraw.Draw(im).text((3, 3), f"{key} {tt:.1f}", fill=(255, 255, 0))
            sheet.paste(im, ((i % 10) * 180, (i // 10) * 320))
    sheet.save(here / "yamaguchi_sheet.png")
