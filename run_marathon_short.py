import os
import json
from pathlib import Path
from auto_video_generator_v2 import AutoVideoGenerator
from advanced_sfx_mixer import apply_advanced_sfx_to_video
from local_paths import BGM, SFX

BGM_PATH = BGM["marathon"]
SFX_PATHS = {k: str(v) for k, v in SFX.items()}

def save_storyboard(output_dir, sb_data):
    p = output_dir / "storyboard.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(sb_data, f, indent=2, ensure_ascii=False)

def main():
    generator = AutoVideoGenerator()
    
    # Directorio de trabajo
    output_dir = Path("daily_shorts") / "marathon_60s"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    topic = "The Battle of Marathon (490 BCE). Athenian hoplites vs Persian Empire. Epic charge. Focus on infantry and heroism."
    
    print("=========================================")
    print(" 1. GENERANDO GUION (MARATON)")
    print("=========================================")
    with open(output_dir / "storyboard.json", "r", encoding="utf-8") as f:
        sb = json.load(f)
    
    print("\n=========================================")
    print(" 2. GENERANDO IMAGENES (STABILITY CORE)")
    print("=========================================")
    # generator.generate_all_images_for_storyboard(
    #     storyboard_data=sb,
    #     platform="youtube_short",
    #     use_real_images=False,
    #     use_google_images=False,
    #     image_provider="google_ai",
    #     style="Photorealism",
    #     project_path=str(output_dir)
    # )
    
    print("\n=========================================")
    print(" 3. ENSAMBLAJE BASICO (MOTOR PRINCIPAL)")
    print("=========================================")
    # Patch de subtitulos dinamicos (Hormozi)
    from dynamic_subtitle_wrapper import patch_subtitle_generation
    patch_subtitle_generation(generator, subtitle_style="hormozi")
    
    res = generator.assemble_video_from_storyboard(
        storyboard_data=sb,
        platform="tiktok",
        apply_cinematic=True,
        subtitles_style="hormozi",
        manual_bgm_path=str(BGM_PATH),
        transition_type="Film Burn (Overlay)",
        transition_duration=0.25
    )
    
    raw_video_path = str(res) if isinstance(res, str) else (res.get('video_path') if isinstance(res, dict) else str(res))
    if not raw_video_path or not os.path.exists(raw_video_path):
        print(f"ERROR: El video base no se genero correctamente. res={res}")
        return
        
    print("\n=========================================")
    print(" 4. MEZCLA AVANZADA DE EFECTOS (PYDUB)")
    print("=========================================")
    final_output_path = raw_video_path.replace(".mp4", "_FINAL_MIX.mp4")
    
    apply_advanced_sfx_to_video(raw_video_path, sb, SFX_PATHS, final_output_path)
    
    print("\n*****************************************")
    print(f" VIDEO FINAL COMPLETADO: {final_output_path}")
    print("*****************************************")

if __name__ == "__main__":
    main()
