"""Short Catarsis (Stunning Revelations): Operation Northwoods (1962). Memo JCS (desclasificado 1997), noticieros Universal 1962,
Prelinger y Biblioteca del Congreso (dominio publico)."""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
from PIL import Image, ImageDraw
from catharsis import catharsis_editor as ce
here = Path(__file__).resolve().parent
f = lambda n: str(here / n)
FOC = json.load(open(here / "pg" / "focus.json"))
PG = lambda n, zoom=None: {"file": f(f"pg/{n}.png"), "focus": FOC[n][:2], "zoom": zoom or FOC[n][2]}
V = lambda fn, a, z, fx=0.5, fy=0.5, zoom=1.0: {"file": f(fn), "in": a, "out": z, "focus": [fx, fy], "zoom": zoom}
RT, CC, JET, MIA = "vid/red_threat.mpeg", "vid/cuban_crisis.mpeg", "vid/jet_national.mpeg", "vid/miami_1955.mp4"
project = {
    "topic": "Operation Northwoods: the 1962 Joint Chiefs plan to stage attacks and blame Cuba",
    "perspective": "narrator", "language": "en", "seconds": 50,
    "cards": {
        "direction": {"speaker": "Narrador externo; sujeto focal: el memo Northwoods del Estado Mayor Conjunto",
                      "moment": "13 de marzo de 1962, con el desenlace en 1997",
                      "conflict": "Un plan secreto para fabricar ataques y culpar a Cuba como pretexto de invasion",
                      "turn": "El plan incluia un avion de pasajeros falso con estudiantes y un dron destruido por radio",
                      "payoff": "Lo firmo la cupula militar de EE. UU.; Kennedy lo rechazo y estuvo oculto 35 anos"},
        "opening": "Who planned staged attacks on the United States?",
        "lines": ["March 13, 1962. Top secret.", "Code name: Northwoods.", "Goal: a pretext to invade Cuba.",
                  "Blow up a US ship. Blame Cuba.", "Then hold funerals for mock victims.",
                  "Fake Cuban terror in Miami and Washington.", "A staged airliner shootdown over Cuba.",
                  "Passengers: a group of college students.", "Over Cuba, a drone would explode.",
                  "A helpful wave of national indignation."],
        "climax": ["PRETEXT", "BLAME", "INVADE"],
        "final": ["It came from America's own Joint Chiefs.", "Kennedy said no. Secret until 1997."],
        "end": "Operation Northwoods, 1962. Archive films are illustrative"},
    "media": [
        PG("topsecret"), PG("northwoods"), PG("subject"), PG("ship"), PG("funerals"),   # 0-4
        PG("terror"), PG("airliner"), PG("students"), PG("drone"), PG("indignation"),   # 5-9
        PG("signature"),                                                                                   # 10
        V(CC, 51.5, 56.0), V(CC, 57.5, 66.0, 0.45),                     # 11-12 portaaviones y destructores (1962)
        V(CC, 98.0, 102.5, 0.5), V(CC, 113.0, 123.0, 0.5),              # 13 tropas, 14 Cuba: carteles
        V(CC, 124.0, 128.0, 0.42), V(CC, 160.0, 186.0),                 # 15 Castro, 16 fotos de reconocimiento
        V(CC, 145.5, 153.0, 0.5),                                       # 17 jet de reconocimiento
        V(JET, 0.3, 2.6, 0.45), V(JET, 51.5, 53.8, 0.5),                # 18-19 avion de pasajeros
        V(JET, 10.0, 18.5, 0.5), V(MIA, 54.0, 66.0, 0.5),               # 20 Miami Beach, 21 Miami
        V(RT, 53.0, 70.0, 0.48, 0.42), V(RT, 75.0, 90.0, 0.48, 0.42),   # 22-23 Kennedy (22 oct 1962)
        {"file": f("loc/jfk_jcs.tif"), "focus": [0.6, 0.5]},            # 24 Kennedy con el Estado Mayor Conjunto (1961)
        {"file": f("loc/gitmo_aerial.tif"), "focus": [0.25, 0.6]},      # 25 bahia de Guantanamo (1963)
        {"file": f("jfk_jcs_still.png"), "focus": [0.6, 0.5]},          # 26 foto para impact frames
        {"file": f("gitmo_guards_still.png"), "focus": [0.5, 0.5]},     # 27 foto para impact frames
    ],
    "music": str(here.parent / "trinity" / "rud.mp3"), "music_start": 104.71, "music_auto": False,   # find_music_start(rud, 50): caida en 144.7 s
    "style": {"speed": 1.0, "flashes": 1.0, "variants": ["base", "negative", "hard", "red", "sketch"],
              "transitions": ["glitch", "burn"]},
}
proj = ce.normalize_project(project)
ce._validate_generated_cards(proj["cards"])
beats, drop = ce.music_analysis(proj["music"], proj["seconds"], proj["music_start"])
seq = ce.auto_sequence(proj, beats, seed=62, drop=drop)
L = proj["cards"]["lines"]
at = lambda text: next(i for i, s in enumerate(seq) if s.get("text") == text)
nxt = lambda k: next(i for i in range(k + 1, len(seq)) if seq[i]["kind"] == "media")
med = lambda m, d, variant, act, motion="push": {"kind": "media", "media": m, "variant": variant, "seconds": d, "motion": motion,
                                                 "transition": "cut", "offset": 0.0, "audio": False, "act": act}
def to_card(text, style, m, variant):
    k = at(text); s = seq[k]; c = round(min(ce._reading_time(text), s["seconds"] - 0.45), 3)
    seq[k:k + 1] = [{"kind": "card", "text": text, "style": style, "seconds": c, "kinetic": True, "transition": "cut", "motion": "hold", "act": "rise"},
                    med(m, round(s["seconds"] - c, 3), variant, "rise")]
# frase -> (pagina del memo como evidencia, video de archivo)
plan = {L[0]: (0, 25), L[1]: (1, None), L[2]: (2, 13), L[3]: (3, 11), L[4]: (4, None), L[5]: (5, 21),
        L[6]: (6, 17), L[7]: (7, 18), L[8]: (8, 19), L[9]: (9, 22)}
over = [s.get("text") for s in seq if s["kind"] == "overlay"]
for line in over:
    if line == L[7]:
        seq[at(line)].update(media=18, variant="base", offset=0.0)       # sobre el avion de pasajeros
    else:
        to_card(line, "center", plan[line][0], "color")
for line in plan:                                                        # tarjetas algo mas cortas: la prueba se alcanza a ver
    if line == L[7]:
        continue
    k = at(line); c = seq[k]["seconds"]; new = round(max(1.15, c * 0.78), 3)
    seq[k]["seconds"] = new; seq[nxt(k)]["seconds"] = round(seq[nxt(k)]["seconds"] + c - new, 3)
for line, (pg, vid) in plan.items():
    if line == L[7]:
        continue
    k = nxt(at(line)); seq[k].update(media=pg, variant="color", offset=0.0, motion="push")   # color: el marcador rojo
    d = seq[k]["seconds"]
    if vid is not None and d >= 0.9:                                     # la pagina y despues el archivo
        p = round(max(0.45, d * 0.5), 3)
        seq[k]["seconds"] = p
        seq.insert(k + 1, med(vid, round(d - p, 3), "base", "rise", "hold"))
op = next(i for i, s in enumerate(seq) if s["act"] == "open" and s["kind"] == "media")
seq[op] = {"kind": "double", "media": 0, "media2": 22, "variant": "base", "seconds": seq[op]["seconds"], "motion": "push",
           "transition": "cut", "act": "open"}
next(s for s in seq if s["kind"] == "split").update(medias=[3, 12, 25], variant="base")
db = next(i for i, s in enumerate(seq) if s["kind"] == "double" and s["act"] == "rise")
seq[db].update(media=16, media2=9, variant="base")
cyc = [12, 3, 14, 6, 13, 5, 17, 8, 15, 0, 16, 9]
for n, s in enumerate(s for s in seq if s["act"] == "climax" and s["kind"] == "media"):
    s["media"] = cyc[n % len(cyc)]; s["offset"] = 0.0
for n, s in enumerate(s for s in seq if s["kind"] == "impact"):
    s["media"] = (26, 27)[n % 2]
k = next(i for i, s in enumerate(seq) if s.get("tag") == "break") + 1
F = sum(s["seconds"] for s in seq[k:])
card = lambda text, st, d, kin=True: {"kind": "card", "text": text, "style": st, "seconds": d, "kinetic": kin,
                                      "transition": "cut", "motion": "hold", "act": "final"}
a, b = round(0.17 * F, 3), round(0.24 * F, 3)
seq[k:] = [med(24, a, "base", "final"), card(proj["cards"]["final"][0], "invert", b), med(23, a, "base", "final"),
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
    out = here / "nw_final.mp4"
    ce.render(shots, out, music=proj["music"], break_span=marks["break"], sfx=True, loop=True, music_start=proj["music_start"])
    pts = pts[:40]
    sheet = Image.new("RGB", (180 * 10, 320 * ((len(pts) + 9) // 10)))
    for i, (key, tt) in enumerate(pts):
        raw = subprocess.run([ce._ffmpeg(), "-loglevel", "error", "-ss", f"{tt:.3f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=180:320", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if len(raw) >= 180 * 320 * 3:
            im = Image.frombytes("RGB", (180, 320), raw[:180 * 320 * 3]); ImageDraw.Draw(im).text((3, 3), f"{key} {tt:.1f}", fill=(255, 255, 0))
            sheet.paste(im, ((i % 10) * 180, (i // 10) * 320))
    sheet.save(here / "nw_sheet.png")
