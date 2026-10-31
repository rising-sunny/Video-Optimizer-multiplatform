"""Short Catarsis (Stunning Revelations): Operation Sea-Spray, San Francisco, 20-27 sept. 1950. Archivo: filme de Defensa Civil 1951 (FCDA), peliculas caseras Prelinger (SF anos 40), audiencias del Senado 1977; musica Kevin MacLeod CC BY 4.0."""
import subprocess, sys
from pathlib import Path
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
from PIL import Image, ImageDraw
from catharsis import catharsis_editor as ce
here = Path(__file__).resolve().parent
f = lambda n: str(here / n)
sys.path.insert(0, str(here.parent))
from cards import SS
C = lambda n: f("clips/" + n + ".mp4")
V = lambda fn, a, z, fx=0.5, fy=0.5, zoom=1.0: {"file": fn, "in": a, "out": z, "focus": [fx, fy], "zoom": zoom}
P = lambda n, fx=0.5, fy=0.5: {"file": f(n), "focus": [fx, fy]}
MUSIC = str(here.parent / "music" / "Invariance.mp3")
project = {
    "topic": "Operation Sea-Spray, the 1950 secret U.S. Navy bacteria spraying over San Francisco", "perspective": "narrator", "language": "en", "seconds": 44,
    "cards": SS,
    "media": [
        V(C("m00_ggship"), 0, 24), V(C("m11_docks"), 0, 16), V(C("m02_germs"), 0, 6.7), V(C("m03_gg"), 0, 28), V(C("m06_spray"), 0, 3.2, 0.3, 0.5),   # 0 bahia, 1 muelles, 2 cultivos, 3 Golden Gate, 4 aerosol
        V(C("m05_map"), 0, 5.5), V(C("m13_street"), 0, 5.6), V(C("m07_toddler"), 0, 18), V(C("m08_ward"), 0, 9), V(C("m09_stretcher"), 3.3, 6),  # 5 mapa, 6 calle, 7 nino, 8 sala, 9 camilla
        V(C("m18_above"), 0, 14), V(C("m16_sickman"), 0, 5.5), V(C("m12_family"), 0, 30), V(C("m14_city"), 0, 3.2), V(C("m10_bed"), 0, 5.5),  # 10 nubes, 11 enfermo, 12 familia, 13 ciudad, 14 cama
        V(C("m15_freighter"), 0, 12), V(C("m17_crowd"), 0, 8),                                                                                 # 15 carguero, 16 hospital
        P("img/passage_still.png", 0.5, 0.5), P("img/cover_still.png", 0.5, 0.5),                                                             # 17-18 documentos
    ],
    "music": MUSIC, "music_start": 153.5, "music_auto": False,
    "style": {"speed": 1.2, "flashes": 1.0, "variants": ["base", "negative", "hard", "red", "sketch"],
              "transitions": ["glitch", "burn"]},
}
proj = ce.normalize_project(project)
ce._validate_generated_cards(proj["cards"])
# Los cortes siguen la grilla original (la pista ad hoc se compuso sobre ella: quiebre 33.7-35.17 s)
beats, drop = ce.music_analysis(MUSIC, proj["seconds"], 153.5)
seq = ce.auto_sequence(proj, beats, seed=1950, drop=drop)
L = proj["cards"]["lines"]
at = lambda text: next(i for i, s in enumerate(seq) if s.get("text") == text)
nxt = lambda k: next(i for i in range(k + 1, len(seq)) if seq[i]["kind"] == "media")
med = lambda m, d, variant, act, motion="push": {"kind": "media", "media": m, "variant": variant, "seconds": d, "motion": motion,
                                                 "transition": "cut", "offset": 0.0, "audio": False, "act": act}
plan = {L[0]: 0, L[1]: 1, L[2]: 2, L[3]: 4, L[4]: 5, L[5]: 6, L[6]: 7, L[7]: 8, L[8]: 9, L[9]: 18}
over = [s.get("text") for s in seq if s["kind"] == "overlay"]
for line in over:
    seq[at(line)].update(media=plan[line], variant="base", offset=0.0)
for line, m in plan.items():
    if line not in over:
        seq[nxt(at(line))].update(media=m, variant="base", offset=0.0)
op = next(i for i, s in enumerate(seq) if s["act"] == "open" and s["kind"] == "media")
seq[op] = {"kind": "double", "media": 3, "media2": 4, "variant": "base", "seconds": seq[op]["seconds"], "motion": "push", "transition": "cut", "act": "open"}
next(s for s in seq if s["kind"] == "split").update(medias=[3, 10, 15], variant="base")
db = next(i for i, s in enumerate(seq) if s["kind"] == "double" and s["act"] == "rise")
seq[db].update(media=8, media2=14, variant="base")
cyc = [3, 4, 2, 6, 16, 11, 13, 5, 0, 15, 9, 1]
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
    out = here / "seaspray_final.mp4"
    ce.render(shots, out, music=proj["music"], break_span=marks["break"], sfx=True, loop=True, music_start=proj["music_start"])
    pts = pts[:40]
    sheet = Image.new("RGB", (180 * 10, 320 * ((len(pts) + 9) // 10)))
    for i, (key, tt) in enumerate(pts):
        raw = subprocess.run([ce._ffmpeg(), "-loglevel", "error", "-ss", f"{tt:.3f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=180:320", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if len(raw) >= 180 * 320 * 3:
            im = Image.frombytes("RGB", (180, 320), raw[:180 * 320 * 3]); ImageDraw.Draw(im).text((3, 3), f"{key} {tt:.1f}", fill=(255, 255, 0))
            sheet.paste(im, ((i % 10) * 180, (i // 10) * 320))
    sheet.save(here / "seaspray_sheet.png")
