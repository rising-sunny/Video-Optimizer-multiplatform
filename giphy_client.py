# giphy_client.py
import os
import requests
from pathlib import Path

GIPHY_API_KEY = os.getenv("GIPHY_API_KEY")
# Usamos el endpoint de "stickers" porque tienen fondo transparente
SEARCH_URL = "https://api.giphy.com/v1/stickers/search"

def find_and_download_gif(tag, output_dir):
    """
    Busca el mejor sticker (GIF transparente) en GIPHY, lo descarga y devuelve la ruta.
    """
    if not GIPHY_API_KEY or GIPHY_API_KEY == "tu_api_key_de_giphy_aqui":
        print("   ️ GIPHY: GIPHY_API_KEY no configurada en .env")
        return None

    print(f"   [GIPHY] Buscando sticker: '{tag}'...")
    
    try:
        params = {
            "api_key": GIPHY_API_KEY,
            "q": tag,
            "limit": 1,
            "rating": "g",
            "lang": "es",
            "bundle": "messaging_non_clips"
        }
        
        response = requests.get(SEARCH_URL, params=params)
        response.raise_for_status()
        
        results = response.json().get("data")
        if not results:
            print(f"   [GIPHY] No se encontraron stickers para '{tag}'")
            return None
            
        sticker_data = results[0]
        
        # Obtener la URL del GIF (usamos 'fixed_height' para un tamaño predecible)
        download_url = sticker_data.get("images", {}).get("fixed_height", {}).get("url")
        
        if not download_url:
            print(f"   [GIPHY] El sticker encontrado no tiene URL válida.")
            return None

        # Descargar el archivo
        gif_response = requests.get(download_url)
        gif_response.raise_for_status()
        
        # Guardar el archivo
        safe_tag = "".join(c for c in tag if c.isalnum()).strip()
        output_filename = f"overlay_{safe_tag}_{sticker_data['id']}.gif"
        output_path = Path(output_dir) / output_filename
        
        with open(output_path, "wb") as f:
            f.write(gif_response.content)
            
        print(f"   [GIPHY] Descargado: {output_filename}")
        return str(output_path)

    except requests.exceptions.RequestException as e:
        print(f"   [GIPHY] Error de API GIPHY: {e}")
        return None
    except Exception as e:
        print(f"   [GIPHY] Error procesando GIF: {e}")
        return None