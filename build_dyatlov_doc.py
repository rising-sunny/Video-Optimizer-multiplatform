import sys
import json
import os
from pathlib import Path

sys.path.append(r"C:\dev\Video-Optimizer-multiplatform")
from daily_short_pipeline import generate_images_for_draft, assemble_video
from advanced_sfx_mixer import apply_advanced_sfx_to_video

def main():
    print("=== INICIANDO CONSTRUCCION DE DOCUMENTAL LARGO ===")
    
    draft_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\long_form\dyatlov_project")
    sb_path = draft_dir / "storyboard.json"
    
    if not sb_path.exists():
        print(f"ERROR: No se encontró el storyboard en {sb_path}")
        return
        
    with open(sb_path, "r", encoding="utf-8") as f:
        sb = json.load(f)
        
    # Forzamos formato horizontal
    sb["platform"] = "youtube_long"
    # 1. Generar audio (TTS)
    from tts_generator import TextToSpeechGenerator
    tts = TextToSpeechGenerator()
    full_text = " ".join([seg["text"] for seg in sb["segments"]])
    
    temp_media_dir = draft_dir / "temp" / "generated_media"
    temp_media_dir.mkdir(parents=True, exist_ok=True)
    tts_out = temp_media_dir / "voz.mp3"
    
    print("1. Generando voz en off...")
    if not tts_out.exists():
        tts.generate_narration(full_text, str(tts_out), voice_id="es-ES-AlvaroNeural")
    sb["audio_path"] = str(tts_out)
    
    # 2. Generar/Verificar imágenes
    # Set image names
    for i, seg in enumerate(sb["segments"]):
        seg["assigned_filename"] = f"seg_{i+1}"
        seg["overlay_tag"] = "none"
        seg["image_path"] = str(draft_dir / "project_media" / f"seg_{i+1}.png")
        
    # We will use "auto" which falls back to DALL-E or default
    generate_images_for_draft(draft_dir, sb, image_provider="google_images", visual_style="Photorealism", platform="youtube_long")
    
    # Music
    master_bgm = r"C:\dev\Video-Optimizer-multiplatform\long_form\dyatlov_project\master_bgm.mp3"
    sb["_manual_bgm_path"] = master_bgm
    
    sb["script"] = full_text
    
    # 2. Assemble Video
    print("2. Ensamblando video base...")
    assemble_video(
        sb, 
        draft_dir, 
        transition_type="Film Burn (0.3s)", 
        visual_style="Photorealism",
        platform="youtube_long"
    )
    
    # 3. SFX
    mp4_files = list(draft_dir.glob("short_*.mp4"))
    if not mp4_files:
        mp4_files = list(draft_dir.glob("youtube_long*.mp4")) # depending on naming
    if not mp4_files:
        print("ERROR: No se encontró el video generado.")
        return
        
    mp4_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    latest = mp4_files[0]
    final_out = draft_dir / "DYATLOV_DOCUMENTARY.mp4"
    
    print(f"3. Aplicando SFX maestro a {latest}...")
    apply_advanced_sfx_to_video(
        str(latest),
        sb,
        {"swoosh": r"C:\Users\sunse\Downloads\ES_Swooshes, Whoosh, Classic, Fast, No Bass 03 - Epidemic Sound.mp3"},
        str(final_out)
    )
    
    print(f"¡DOCUMENTAL TERMINADO! -> {final_out}")

if __name__ == "__main__":
    main()
