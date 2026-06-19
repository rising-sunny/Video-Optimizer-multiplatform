import sys
from pydub import AudioSegment
from pathlib import Path

def main():
    tracks = [
        r"C:\Users\sunse\Downloads\ES_Consequences - Magnus Ludvigsson.mp3",
        r"C:\Users\sunse\Downloads\ES_Dark Shadow - Etienne Roussel.mp3",
        r"C:\Users\sunse\Downloads\ES_Unsolved Issues - Magnus Ludvigsson.mp3"
    ]
    
    print("Cargando pistas de audio...")
    combined = AudioSegment.empty()
    
    for t in tracks:
        audio = AudioSegment.from_file(t)
        # Crossfade between tracks to make it smooth (3 seconds crossfade)
        if len(combined) > 0:
            combined = combined.append(audio, crossfade=3000)
        else:
            combined += audio

    # We need about 15-16 minutes (900-960 seconds).
    # Let's see how long combined is.
    total_len_ms = len(combined)
    print(f"Duración de la mezcla base: {total_len_ms / 1000}s")
    
    target_ms = 16 * 60 * 1000  # 16 minutes
    
    final_audio = combined
    while len(final_audio) < target_ms:
        print("Looping track list to reach 16 minutes...")
        final_audio = final_audio.append(combined, crossfade=3000)
        
    out_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\long_form\dyatlov_project")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "master_bgm.mp3"
    
    print(f"Exportando pista maestra de {len(final_audio)/1000}s a {out_path} ...")
    final_audio.export(str(out_path), format="mp3")
    print("¡Hecho!")

if __name__ == "__main__":
    main()
