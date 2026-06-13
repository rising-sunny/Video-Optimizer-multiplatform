# google_search_api.py
import os
import googleapiclient.discovery
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Cargamos las claves desde el .env
# (Asegúrate de que video_optimizer_gui_v3_2.py haya cargado load_dotenv() primero)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID")

def search_youtube_trends(query, max_results=10):
    """
    Busca los videos más vistos en YouTube para una consulta.
    """
    if not GOOGLE_API_KEY:
        print("️ No se ha configurado GOOGLE_API_KEY en .env")
        return ["Error: API Key de Google no configurada."]

    try:
        youtube = build('youtube', 'v3', developerKey=GOOGLE_API_KEY)
        
        request = youtube.search().list(
            part='snippet',
            q=query,
            type='video',
            order='viewCount',  # Ordenar por más vistas
            maxResults=max_results
        )
        
        response = request.execute()
        
        results = []
        for item in response.get('items', []):
            title = item['snippet']['title']
            channel = item['snippet']['channelTitle']
            video_id = item['id']['videoId']
            url = f"https://www.youtube.com/watch?v={video_id}"
            
            results.append(f"• Título: {title}\n  Canal: {channel}\n  URL: {url}\n")
        
        return results if results else ["No se encontraron resultados en YouTube."]
        
    except HttpError as e:
        print(f" Error en API de YouTube: {e}")
        return [f"Error en API de YouTube: {e.content.decode('utf-8')}"]
    except Exception as e:
        print(f" Error desconocido en YouTube: {e}")
        return [f"Error: {e}"]

def search_google_trends(query, max_results=10):
    """
    Busca las páginas más relevantes en Google para una consulta.
    """
    if not GOOGLE_API_KEY or not GOOGLE_SEARCH_ENGINE_ID:
        print("️ No se ha configurado GOOGLE_API_KEY o GOOGLE_SEARCH_ENGINE_ID en .env")
        return ["Error: API Key o Search Engine ID no configurados."]
        
    try:
        service = build('customsearch', 'v1', developerKey=GOOGLE_API_KEY)
        
        res = service.cse().list(
            q=query,
            cx=GOOGLE_SEARCH_ENGINE_ID,
            num=max_results
        ).execute()
        
        results = []
        for item in res.get('items', []):
            title = item['title']
            snippet = item['snippet'].replace('\n', ' ')
            url = item['link']
            
            results.append(f"• Título: {title}\n  Snippet: {snippet}\n  URL: {url}\n")
            
        return results if results else ["No se encontraron resultados en Google."]

    except HttpError as e:
        print(f" Error en API de Google Search: {e}")
        return [f"Error en API de Google Search: {e.content.decode('utf-8')}"]
    except Exception as e:
        print(f" Error desconocido en Google Search: {e}")
        return [f"Error: {e}"]