import os
import sys
from pathlib import Path
from dotenv import load_dotenv

import facebook_uploader

def main():
    print("Probando subida a Facebook como DRAFT (borrador)...")
    
    video_path = "test.mp4"
    if not os.path.exists(video_path):
        print(f"Error: No se encontró un video para probar ({video_path}) en el directorio actual.")
        sys.exit(1)
            
    print(f"Usando video de prueba: {video_path}")
    
    title = "Test de Borrador Automático"
    description = "Test de subida vía Graph API para asegurar que se guarden los Reels como drafts y se obtenga el token correctamente."
    
    try:
        resultado = facebook_uploader.upload_video(
            video_path=video_path,
            title=title,
            description=description,
            video_state="DRAFT"
        )
        print("\n¡ÉXITO! El Reel se subió correctamente.")
        print(f"Video ID: {resultado.get('video_id')}")
        print(f"Estado en facebook: {resultado.get('status')}")
        print(f"Video State resultante: {resultado.get('video_state')}")
    except Exception as e:
        print("\nError durante la subida:")
        print(repr(e))

if __name__ == "__main__":
    main()
