import os
import sys
import json
from pathlib import Path

sys.path.insert(0, r'c:\dev\Video-Optimizer-multiplatform')
from groq_client import GroqAiClient
from recraft_client import RecraftClient

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print("Generando paquete de post para el VPS...")
    
    groq = GroqAiClient()
    tweet_text = "In 1587, 115 English settlers vanished from Roanoke Island without a trace. Their homes were dismantled, and no bodies were ever found. The only clue left behind? The word 'CROATOAN' carved into a wooden post 🌫️🌳.\n\n#History #Mystery #Roanoke"
    image_prompt = "A highly detailed, photorealistic, cinematic shot of an abandoned wooden fort in a dense, foggy forest at dusk. The word CROATOAN is deeply carved into a large tree trunk in the foreground. Eerie lighting, mysterious atmosphere, no people."
    
    print(f"Texto generado:\n{tweet_text}\n")
    
    # Save text to vps folder
    vps_folder = Path(r"C:\dev\Video-Optimizer-multiplatform\vps_x_bot")
    with open(vps_folder / "roanoke_text.txt", "w", encoding="utf-8") as f:
        f.write(tweet_text)
        
    # Generate image
    print("Contactando a Recraft...")
    recraft = RecraftClient()
    image_path = str(vps_folder / "roanoke_image.png")
    
    result = recraft.generate_image(
        prompt=image_prompt,
        style="photorealism",
        width=1536,
        height=1024,
        output_path=image_path
    )
    
    if result and os.path.exists(image_path):
        print(f"¡Post generado con éxito! Archivos guardados en: {vps_folder}")
    else:
        print("Fallo al generar la imagen.")

if __name__ == "__main__":
    main()
