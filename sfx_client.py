# sfx_client.py - Versión mejorada sin warnings repetitivos
import os
import requests
from pathlib import Path

FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY")
SEARCH_URL = "https://freesound.org/apiv2/search/text/"
SOUND_DETAIL_URL = "https://freesound.org/apiv2/sounds/"

# Flag para mostrar warning solo una vez
_warning_shown = False

def find_and_download_sfx(tag, output_dir, max_duration_sec=10):
    """
    Busca el mejor SFX en Freesound, lo descarga y devuelve la ruta.
    
    Args:
        tag: Palabra clave para buscar (ej: "thunder", "ocean waves")
        output_dir: Directorio donde guardar el archivo
        max_duration_sec: Duración máxima del SFX en segundos
    
    Returns:
        str: Path al archivo descargado, o None si falla
    """
    global _warning_shown
    
    if not FREESOUND_API_KEY or FREESOUND_API_KEY == "tu_Client_Secret_de_Freesound_aqui":
        # Mostrar warning solo la primera vez
        if not _warning_shown:
            print("\n" + "="*70)
            print("️  EFECTOS DE SONIDO (SFX) DESACTIVADOS")
            print("="*70)
            print("Para activar efectos de sonido contextuales:")
            print("  1. Crear cuenta en: https://freesound.org/")
            print("  2. Obtener API key en: https://freesound.org/apiv2/apply/")
            print("  3. Añadir a .env: FREESOUND_API_KEY=tu_clave_aqui")
            print("  4. Reiniciar la aplicación")
            print("\nLos videos se generarán sin efectos de sonido (solo narración + música)")
            print("="*70 + "\n")
            _warning_shown = True
        return None

    print(f"       SFX: Buscando '{tag}'...")
    
    try:
        # 1. Buscar el sonido
        headers = {"Authorization": f"Token {FREESOUND_API_KEY}"}
        params = {
            "query": tag,
            "filter": f"duration:[0 TO {max_duration_sec}]",
            "sort": "rating_desc",  # Traer el mejor calificado
            "fields": "id,name,previews,download",
            "page_size": 1
        }
        
        response = requests.get(SEARCH_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        results = response.json().get("results")
        if not results:
            print(f"      ️ SFX: No encontrado para '{tag}'")
            return None
            
        sound_data = results[0]
        
        # 2. Obtener la URL de descarga (preview HQ MP3)
        download_url = sound_data.get("previews", {}).get("preview-hq-mp3")
        
        if not download_url:
            print(f"      ️ SFX: Sin preview HQ para '{tag}'")
            return None

        # 3. Descargar el archivo
        sfx_response = requests.get(download_url, headers=headers, timeout=15)
        sfx_response.raise_for_status()
        
        # 4. Guardar el archivo
        safe_tag = "".join(c for c in tag if c.isalnum() or c.isspace()).strip().replace(" ", "_")
        output_filename = f"sfx_{safe_tag}_{sound_data['id']}.mp3"
        output_path = Path(output_dir) / output_filename
        
        with open(output_path, "wb") as f:
            f.write(sfx_response.content)
            
        print(f"       SFX: '{sound_data.get('name', tag)}' descargado")
        return str(output_path)

    except requests.exceptions.Timeout:
        print(f"      ️ SFX: Timeout buscando '{tag}'")
        return None
    except requests.exceptions.RequestException as e:
        print(f"      ️ SFX: Error de API para '{tag}': {e}")
        return None
    except Exception as e:
        print(f"      ️ SFX: Error procesando '{tag}': {e}")
        return None


def get_sfx_status():
    """
    Retorna el estado del sistema de SFX.
    
    Returns:
        dict: {'enabled': bool, 'api_key_configured': bool, 'message': str}
    """
    api_key_configured = bool(
        FREESOUND_API_KEY and 
        FREESOUND_API_KEY != "tu_Client_Secret_de_Freesound_aqui"
    )
    
    return {
        'enabled': api_key_configured,
        'api_key_configured': api_key_configured,
        'message': 'SFX activado' if api_key_configured else 'SFX desactivado - API key no configurada'
    }


if __name__ == "__main__":
    print(" Freesound SFX Client")
    print("=" * 60)
    
    status = get_sfx_status()
    print(f"Estado: {status['message']}")
    
    if status['enabled']:
        print("\nProbando búsqueda de SFX...")
        result = find_and_download_sfx("thunder", "./test_output")
        if result:
            print(f" Test exitoso: {result}")
        else:
            print(" Test falló")
    else:
        print("\nPara activar SFX:")
        print("  1. Obtener API key: https://freesound.org/apiv2/apply/")
        print("  2. Añadir a .env: FREESOUND_API_KEY=tu_clave")