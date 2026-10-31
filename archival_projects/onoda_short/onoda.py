"""Short Catarsis (Stunning Facts of History): Hiroo Onoda, Lubang 1944-1974. Filmaciones del US Army 1944-45 (NARA 111-ADC) y Universal Newsreel 1945."""
import subprocess, sys
from pathlib import Path
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
from PIL import Image, ImageDraw
from catharsis import catharsis_editor as ce
here = Path(__file__).resolve().parent
f = lambda n: str(here / n)
M, L, I, U, S = (f("dl/111-adc-5176.mp4"), f("dl/111-adc-5180.mp4"), f("dl/111-adc-2929.mp4"),
                 f("dl/1945-08-23_Japanese_Surrender.mpeg"), f("dl/111-adc-9888.mp4"))
V = lambda fn, a, z, fx=0.5, fy=0.5, zoom=1.0: {"file": fn, "in": a, "out": z, "focus": [fx, fy], "zoom": zoom}
P = lambda n, fx=0.5, fy=0.5: {"file": f(n), "focus": [fx, fy]}
project = {
    "topic": "Hiroo Onoda, the Japanese soldier who kept fighting until 1974", "perspective": "narrator", "language": "en", "seconds": 44,
    "cards": {
        "direction": {"speaker": "Narrador externo; sujeto focal: el teniente Hiroo Onoda en la isla de Lubang",
                      "moment": "Diciembre de 1944 a marzo de 1974",
                      "conflict": "Ordenes de no rendirse nunca; no cree en los panfletos que anuncian el fin de la guerra",
                      "turn": "Un viajero japones lo encuentra en 1974, pero solo acepta la orden de su antiguo comandante",
                      "payoff": "Su mayor viaja a Lubang y lo releva; entrega espada y fusil tras 29 anos, con un costo humano real"},
        "opening": "World War II ended in 1945. He surrendered in 1974.",
        "lines": ["December 1944. Lubang Island, the Philippines.", "Lt. Hiroo Onoda, 22. Intelligence officer.",
                  "His orders: never surrender. Stay alive.", "August 1945. Japan surrendered.",
                  "Leaflets announced peace. He called them fakes.", "Years passed. His men surrendered or died.",
                  "1972: his last comrade was shot.", "1974: a young traveler found him.",
                  "He refused. Only his commander could relieve him.", "March 9, 1974. His old major arrived."],
        "climax": ["ORDERS", "LOYALTY", "SURRENDER"],
        "final": ["He handed over his sword, rifle and 500 rounds.", "29 years. He allegedly killed up to 30 islanders."],
        "end": "Hiroo Onoda, 1922–2014"},
    "media": [
        V(I, 163.0, 186.0), V(M, 343.0, 362.0), V(U, 50.0, 62.0), V(S, 336.0, 400.0), V(L, 384.0, 432.0),   # 0 desembarco, 1 soldados, 2 oficiales, 3 firma, 4 panfletos
        V(L, 357.0, 373.0), V(I, 512.0, 541.0), V(I, 222.0, 262.0), V(M, 438.0, 468.0), V(U, 16.0, 32.0),  # 5 calendario, 6 selva, 7 bote, 8 salen de la selva, 9 avion
        V(M, 117.0, 170.0), V(S, 6.0, 24.0), V(M, 320.0, 340.0), V(L, 288.0, 312.0), V(S, 306.0, 320.0),   # 10 globos, 11 Missouri, 12 rostros, 13 aviones, 14 delegacion
        V(M, 375.0, 392.0), V(M, 27.0, 70.0),                                                                # 15 leen panfletos, 16 pancarta en japones
        P("sign_still.png"), P("face_still.png"),                                                            # 17-18 impactos
    ],
    "music": str(here / "musica_onoda.wav"), "music_start": 0.0, "music_auto": False,
    "style": {"speed": 1.2, "flashes": 1.0, "variants": ["base", "negative", "hard", "red", "sketch"],
              "transitions": ["glitch", "burn"]},
}
proj = ce.normalize_project(project)
ce._validate_generated_cards(proj["cards"])
# Los cortes siguen la grilla original (la pista ad hoc se compuso sobre ella: quiebre 33.7-35.17 s)
beats, drop = ce.music_analysis(str(here.parent / "trinity" / "rud.mp3"), proj["seconds"], 109.51)
seq = ce.auto_sequence(proj, beats, seed=1974, drop=drop)
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
seq[op] = {"kind": "double", "media": 3, "media2": 8, "variant": "base", "seconds": seq[op]["seconds"], "motion": "push", "transition": "cut", "act": "open"}
next(s for s in seq if s["kind"] == "split").update(medias=[11, 6, 8], variant="base")
db = next(i for i, s in enumerate(seq) if s["kind"] == "double" and s["act"] == "rise")
seq[db].update(media=6, media2=12, variant="base")
cyc = [8, 3, 12, 4, 6, 14, 10, 1, 15, 13, 16, 5]
for n, s in enumerate(s for s in seq if s["act"] == "climax" and s["kind"] == "media"):
    s["media"] = cyc[n % len(cyc)]; s["offset"] = 0.0
for n, s in enumerate(s for s in seq if s["kind"] == "impact"):
    s["media"] = (17, 18)[n % 2]
k = next(i for i, s in enumerate(seq) if s.get("tag") == "break") + 1
F = sum(s["seconds"] for s in seq[k:])
card = lambda text, st, d, kin=True: {"kind": "card", "text": text, "style": st, "seconds": d, "kinetic": kin, "transition": "cut", "motion": "hold", "act": "final"}
a, b = round(0.17 * F, 3), round(0.24 * F, 3)
seq[k:] = [med(14, a, "base", "final"), card(proj["cards"]["final"][0], "invert", b), med(6, a, "color", "final"),
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
    out = here / "onoda_final.mp4"
    ce.render(shots, out, music=proj["music"], break_span=marks["break"], sfx=True, loop=True, music_start=proj["music_start"])
    pts = pts[:40]
    sheet = Image.new("RGB", (180 * 10, 320 * ((len(pts) + 9) // 10)))
    for i, (key, tt) in enumerate(pts):
        raw = subprocess.run([ce._ffmpeg(), "-loglevel", "error", "-ss", f"{tt:.3f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=180:320", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if len(raw) >= 180 * 320 * 3:
            im = Image.frombytes("RGB", (180, 320), raw[:180 * 320 * 3]); ImageDraw.Draw(im).text((3, 3), f"{key} {tt:.1f}", fill=(255, 255, 0))
            sheet.paste(im, ((i % 10) * 180, (i // 10) * 320))
    sheet.save(here / "onoda_sheet.png")
