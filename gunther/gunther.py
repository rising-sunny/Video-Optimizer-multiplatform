"""Short Catarsis (Stunning Facts of History): Henry Gunther, ultimo soldado estadounidense caido en la Primera Guerra Mundial (10:59, 11-11-1918). Archivo NARA 111-H (Signal Corps), Evening Star 11-11-1918 (LoC), musica Kevin MacLeod CC BY 4.0."""
import subprocess, sys
from pathlib import Path
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
from PIL import Image, ImageDraw
from catharsis import catharsis_editor as ce
here = Path(__file__).resolve().parent
f = lambda n: str(here / n)
sys.path.insert(0, str(here.parent))
from cards import GU
C = lambda n: f("clips/" + n + ".mp4")
V = lambda fn, a, z, fx=0.5, fy=0.5, zoom=1.0: {"file": fn, "in": a, "out": z, "focus": [fx, fy], "zoom": zoom}
P = lambda n, fx=0.5, fy=0.5: {"file": f(n), "focus": [fx, fy]}
MUSIC = str(here.parent / "music" / "Crusade - Heavy Industry.mp3")
project = {
    "topic": "Henry Gunther, the last American soldier killed in World War I, 10:59 a.m., November 11, 1918", "perspective": "narrator", "language": "en", "seconds": 44,
    "cards": GU,
    "media": [
        P("img/gunther_up.png", 0.5, 0.4), V(C("m01_w79"), 0, 2.2), V(C("m02_fog"), 0, 18), V(C("m03_shells"), 0, 46), V(C("m04_foxhole"), 0, 8),  # 0 Gunther, 1 79a Div, 2 niebla, 3 granadas, 4 trinchera
        P("img/headline_still.png", 0.5, 0.5), V(C("m06_map"), 0, 13), V(C("m07_march"), 0, 15), V(C("m08_artillery"), 0, 12), V(C("m09_foxguns"), 0, 30),  # 5 portada, 6 mapa, 7 marcha, 8 artilleria, 9 ametralladoras
        V(C("m10_burst"), 0, 10), V(C("m11_binoc"), 0, 12), V(C("m12_funeral"), 0, 40), V(C("m13_cheer"), 0, 16), V(C("m14_paris"), 0, 80),  # 10 estallido, 11 binoculares, 12 funeral, 13-14 celebracion
        V(C("m15_trench"), 0, 26), V(C("m16_soldiers"), 0, 22),                                                                                 # 15 tierra de nadie, 16 soldados
        P("img/gunther_up.png", 0.5, 0.4), P("img/headline_still.png", 0.5, 0.5),                                                                # 17-18 impactos
    ],
    "music": MUSIC, "music_start": 0.0, "music_auto": False,
    "style": {"speed": 1.2, "flashes": 1.0, "variants": ["base", "negative", "hard", "red", "sketch"],
              "transitions": ["glitch", "burn"]},
}
proj = ce.normalize_project(project)
ce._validate_generated_cards(proj["cards"])
# Los cortes siguen la grilla original (la pista ad hoc se compuso sobre ella: quiebre 33.7-35.17 s)
beats, drop = ce.music_analysis(MUSIC, proj["seconds"], 0.0)
seq = ce.auto_sequence(proj, beats, seed=1918, drop=drop)
L = proj["cards"]["lines"]
at = lambda text: next(i for i, s in enumerate(seq) if s.get("text") == text)
nxt = lambda k: next(i for i in range(k + 1, len(seq)) if seq[i]["kind"] == "media")
med = lambda m, d, variant, act, motion="push": {"kind": "media", "media": m, "variant": variant, "seconds": d, "motion": motion,
                                                 "transition": "cut", "offset": 0.0, "audio": False, "act": act}
plan = {L[0]: 0, L[1]: 1, L[2]: 2, L[3]: 15, L[4]: 7, L[5]: 5, L[6]: 8, L[7]: 9, L[8]: 11, L[9]: 3}
over = [s.get("text") for s in seq if s["kind"] == "overlay"]
for line in over:
    seq[at(line)].update(media=plan[line], variant="base", offset=0.0)
for line, m in plan.items():
    if line not in over:
        seq[nxt(at(line))].update(media=m, variant="base", offset=0.0)
op = next(i for i, s in enumerate(seq) if s["act"] == "open" and s["kind"] == "media")
seq[op] = {"kind": "double", "media": 3, "media2": 7, "variant": "base", "seconds": seq[op]["seconds"], "motion": "push", "transition": "cut", "act": "open"}
next(s for s in seq if s["kind"] == "split").update(medias=[3, 10, 15], variant="base")
db = next(i for i, s in enumerate(seq) if s["kind"] == "double" and s["act"] == "rise")
seq[db].update(media=8, media2=4, variant="base")
cyc = [3, 10, 8, 4, 16, 13, 9, 2, 6, 15, 1, 14]
for n, s in enumerate(s for s in seq if s["act"] == "climax" and s["kind"] == "media"):
    s["media"] = cyc[n % len(cyc)]; s["offset"] = 0.0
for n, s in enumerate(s for s in seq if s["kind"] == "impact"):
    s["media"] = (17, 18)[n % 2]
k = next(i for i, s in enumerate(seq) if s.get("tag") == "break") + 1
F = sum(s["seconds"] for s in seq[k:])
card = lambda text, st, d, kin=True: {"kind": "card", "text": text, "style": st, "seconds": d, "kinetic": kin, "transition": "cut", "motion": "hold", "act": "final"}
a, b = round(0.17 * F, 3), round(0.24 * F, 3)
seq[k:] = [med(14, a, "base", "final"), card(proj["cards"]["final"][0], "invert", b), med(12, a, "color", "final"),
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
    out = here / "gunther_final.mp4"
    ce.render(shots, out, music=proj["music"], break_span=marks["break"], sfx=True, loop=True, music_start=proj["music_start"])
    pts = pts[:40]
    sheet = Image.new("RGB", (180 * 10, 320 * ((len(pts) + 9) // 10)))
    for i, (key, tt) in enumerate(pts):
        raw = subprocess.run([ce._ffmpeg(), "-loglevel", "error", "-ss", f"{tt:.3f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=180:320", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if len(raw) >= 180 * 320 * 3:
            im = Image.frombytes("RGB", (180, 320), raw[:180 * 320 * 3]); ImageDraw.Draw(im).text((3, 3), f"{key} {tt:.1f}", fill=(255, 255, 0))
            sheet.paste(im, ((i % 10) * 180, (i // 10) * 320))
    sheet.save(here / "gunther_sheet.png")
