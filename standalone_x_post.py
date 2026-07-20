import os
import sys
from pathlib import Path

# Agregar el root al sys path
sys.path.insert(0, r'c:\dev\Video-Optimizer-multiplatform')
from recraft_client import RecraftClient
import x_uploader

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print("Iniciando generación de post exclusivo para X...")
    
    # Text and prompt designed perfectly for the channel
    tweet_text = "In 1872, the Mary Celeste was found drifting in the Atlantic. Not a single soul was aboard, but the cargo was untouched and a half-eaten meal sat on the captain's table 🍽️. Where did they go? 🚢🌊\n\n#History #Mystery #MaryCeleste"
    
    image_prompt = "A highly detailed, photorealistic, cinematic shot of the ghost ship Mary Celeste drifting endlessly in a foggy, eerie Atlantic ocean at dusk. Dark, atmospheric lighting, moody clouds, hyper-detailed wooden ship structure, no sails, feeling of abandonment and mystery."
    
    print(f"Texto: {tweet_text}")
    print("Contactando a Recraft...")
    recraft = RecraftClient()
    image_path = "exclusive_x_image.png"
    
    # 1536x1024 is a valid 3:2 landscape format, great for Twitter
    result = recraft.generate_image(
        prompt=image_prompt,
        style="photorealism",
        width=1536,
        height=1024,
        output_path=image_path
    )
    
    if not result or not os.path.exists(image_path):
        print("Fallo al generar la imagen con Recraft.")
        return
        
    print(f"Imagen exclusiva generada en {image_path}")
    
    # Subir y publicar en X
    print("Subiendo a X...")
    media_id = x_uploader.upload_image_to_x(image_path)
    
    if media_id:
        print("Publicando tweet...")
        success = x_uploader.post_tweet(tweet_text, media_id=media_id)
        if success:
            print("¡Post exitoso! Revisa la cuenta de @Stunning_Rev")
        else:
            print("Fallo al publicar el tweet.")
    else:
        print("Fallo al subir la imagen a X.")
        
    # Clean up
    if os.path.exists(image_path):
        os.remove(image_path)

if __name__ == "__main__":
    main()
