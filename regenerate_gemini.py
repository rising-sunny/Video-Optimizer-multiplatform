import sys, json, os
from pathlib import Path

ROOT = Path(r"C:\dev\Video-Optimizer-multiplatform")
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

draft_dir = ROOT / "daily_shorts" / "2026-06-16"
sb_path = draft_dir / "storyboard.json"

# Update storyboard.json
with open(sb_path, "r", encoding="utf-8") as f:
    sb = json.load(f)

media_dir = draft_dir / "project_media"

# Ya no sobreescribo el bgm path ni las imagenes porque build_baltic_draft lo hizo
# sb["segments"][0]["image_path"] = str(media_dir / "cover.png")
# for i in range(1, 8):
#     sb["segments"][i]["image_path"] = str(media_dir / f"seg{i}.png")
sb["_manual_bgm_path"] = r"C:\Users\sunse\Downloads\ES_Bitterness - Max Anson.mp3"

from daily_short_pipeline import assemble_video

print("Ensamblando base...")
assemble_video(
    storyboard=sb,
    output_dir=draft_dir,
    subtitle_style="hormozi",
    pregenerate_images=False,
    strict_existing_visuals=True,
    transition_type="Film Burn"
)

print("Aplicando SFX...")
from advanced_sfx_mixer import apply_advanced_sfx_to_video

mp4_files = list(draft_dir.glob("short_*.mp4"))
mp4_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
if mp4_files:
    latest_short = mp4_files[0]
    out_final = draft_dir / "BALTIC_FINAL_GEMINI.mp4"
    apply_advanced_sfx_to_video(
        str(latest_short), 
        sb,
        {"swoosh": r"C:\Users\sunse\Downloads\ES_Swooshes, Whoosh, Classic, Fast, No Bass 03 - Epidemic Sound.mp3"},
        str(out_final)
    )
    print(f"Finalizado: {out_final}")
else:
    print("No se encontro short base!")
