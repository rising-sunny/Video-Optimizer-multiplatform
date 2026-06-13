#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Music Recommender v2.0 - Sistema de recomendaciÃ³n musical basado en Jamendo
Analiza guiones con IA para recomendar mÃºsica apropiada
"""

import os
import json
import requests
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Verificar disponibilidad de librerÃ­as
try:
    import groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    print("[WARN] Libreria 'groq' no encontrada. Groq no funcionara. (pip install groq)")

GEMINI_AVAILABLE = False
ANTHROPIC_AVAILABLE = False

# --- 1. ANALIZADOR DE GUIONES ---

def analyze_script(script_text: str) -> Dict:
    """
    Analiza el guion con IA para determinar categorÃ­a y sentimiento
    """
    print("\nðŸ“ Analizando guion para recomendaciÃ³n musical...")
    
    # Usar solo Groq para analisis IA; si no esta disponible, degradar a heuristica local.
    analysis = None
    
    if GROQ_AVAILABLE and os.getenv('GROQ_API_KEY'):
        print("ðŸ§  Usando Groq para anÃ¡lisis...")
        analysis = _analyze_with_groq(script_text)
    elif GEMINI_AVAILABLE and os.getenv('GEMINI_API_KEY'):
        print("ðŸ§  Usando Gemini para anÃ¡lisis...")
        analysis = _analyze_with_gemini(script_text)
    elif ANTHROPIC_AVAILABLE and os.getenv('ANTHROPIC_API_KEY'):
        print("ðŸ§  Usando Claude para anÃ¡lisis...")
        analysis = _analyze_with_claude(script_text)
    else:
        print("âš ï¸ NingÃºn servicio de IA disponible. Usando anÃ¡lisis bÃ¡sico...")
        analysis = _basic_analysis(script_text)
    
    if not analysis:
        print("âŒ No se pudo analizar el guion")
        return {"category": "General", "sentiment": 0.0, "confidence": 0.0}
    
    print(f"ðŸ“Š CategorÃ­a: {analysis.get('category', 'Unknown')}")
    print(f"ðŸ˜Š Sentimiento: {analysis.get('sentiment', 0.0)}")
    
    return analysis

def _analyze_with_groq(script_text: str) -> Optional[Dict]:
    """Analiza guion usando Groq"""
    try:
        client = groq.Groq(api_key=os.getenv('GROQ_API_KEY'))
        
        prompt = f"""
Analiza este guion y clasifÃ­calo para recomendaciÃ³n musical:

GUION:
{script_text[:2000]}

Responde ÃšNICAMENTE con JSON en este formato:
{{
    "category": "una de: [History, Science, Travel, Horror, Happy, General]",
    "sentiment": "nÃºmero entre -1.0 (muy negativo) y 1.0 (muy positivo)",
    "confidence": "nÃºmero entre 0.0 y 1.0",
    "keywords": ["lista", "de", "palabras", "clave"]
}}
"""
        
        response = client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        
        result = response.choices[0].message.content.strip()
        return json.loads(result)
        
    except Exception as e:
        print(f"âŒ Error con Groq: {e}")
        return None

def _analyze_with_gemini(script_text: str) -> Optional[Dict]:
    """Analiza guion usando Gemini"""
    try:
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f"""
Analiza este guion y clasifÃ­calo para recomendaciÃ³n musical:

GUION:
{script_text[:2000]}

Responde ÃšNICAMENTE con JSON en este formato:
{{
    "category": "una de: [History, Science, Travel, Horror, Happy, General]",
    "sentiment": "nÃºmero entre -1.0 (muy negativo) y 1.0 (muy positivo)",
    "confidence": "nÃºmero entre 0.0 y 1.0",
    "keywords": ["lista", "de", "palabras", "clave"]
}}
"""
        
        response = model.generate_content(prompt)
        result = response.text.strip()
        
        # Limpiar respuesta si contiene markdown
        if result.startswith("```json"):
            result = result.replace("```json", "").replace("```", "").strip()
        
        return json.loads(result)
        
    except Exception as e:
        print(f"âŒ Error con Gemini: {e}")
        return None

def _analyze_with_claude(script_text: str) -> Optional[Dict]:
    """Analiza guion usando Claude"""
    try:
        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        
        prompt = f"""
Analiza este guion y clasifÃ­calo para recomendaciÃ³n musical:

GUION:
{script_text[:2000]}

Responde ÃšNICAMENTE con JSON en este formato:
{{
    "category": "una de: [History, Science, Travel, Horror, Happy, General]",
    "sentiment": "nÃºmero entre -1.0 (muy negativo) y 1.0 (muy positivo)",
    "confidence": "nÃºmero entre 0.0 y 1.0",
    "keywords": ["lista", "de", "palabras", "clave"]
}}
"""
        
        response = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        result = response.content[0].text.strip()
        
        # Limpiar respuesta si contiene markdown
        if result.startswith("```json"):
            result = result.replace("```json", "").replace("```", "").strip()
        
        return json.loads(result)
        
    except Exception as e:
        print(f"âŒ Error con Claude: {e}")
        return None

def _basic_analysis(script_text: str) -> Dict:
    """AnÃ¡lisis bÃ¡sico sin IA"""
    text_lower = script_text.lower()
    
    # AnÃ¡lisis de palabras clave
    categories = {
        "History": ["history", "historia", "pasado", "ancient", "war", "battle"],
        "Science": ["science", "tecnologÃ­a", "technology", "future", "space", "research"],
        "Travel": ["travel", "viaje", "adventure", "explore", "journey", "trip"],
        "Horror": ["horror", "terror", "scary", "dark", "fear", "nightmare"],
        "Happy": ["happy", "feliz", "joy", "celebration", "love", "success"]
    }
    
    # Contar palabras por categorÃ­a
    category_scores = {}
    for category, keywords in categories.items():
        score = sum(1 for keyword in keywords if keyword in text_lower)
        category_scores[category] = score
    
    # Seleccionar categorÃ­a con mayor score
    best_category = max(category_scores, key=category_scores.get)
    confidence = min(category_scores[best_category] / 10.0, 1.0)
    
    # AnÃ¡lisis de sentimiento bÃ¡sico
    positive_words = ["happy", "good", "great", "love", "success", "wonderful", "amazing"]
    negative_words = ["sad", "bad", "terrible", "hate", "failure", "horrible", "awful"]
    
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)
    
    total_emotional = positive_count + negative_count
    if total_emotional > 0:
        sentiment = (positive_count - negative_count) / total_emotional
    else:
        sentiment = 0.0
    
    return {
        "category": best_category,
        "sentiment": sentiment,
        "confidence": confidence,
        "keywords": []
    }

# --- 2. MAPEO DE CATEGORÃAS A TAGS ---

def map_category_to_tags(category: str, sentiment: float = 0.0) -> List[str]:
    """
    Mapea categorÃ­a y sentimiento a tags de Jamendo
    """
    cat_lower = category.lower()
    
    # Tags base por categorÃ­a
    base_tags = {
        "history": ["classical", "orchestral", "cinematic", "dramatic"],
        "science": ["electronic", "ambient", "experimental", "futuristic"],
        "travel": ["pop", "upbeat", "summer", "feel-good"],
        "horror": ["dark", "ambient", "industrial", "cinematic"],
        "happy": ["pop", "upbeat", "happy", "celebration"],
        "general": ["ambient", "cinematic", "neutral"]
    }
    
    tags = base_tags.get(cat_lower, ["ambient", "cinematic"])
    
    # Ajustar por sentimiento
    if sentiment < -0.4 or any(x in cat_lower for x in ["horror", "history"]):
        tags.extend(["dark", "dramatic", "suspense"])
    elif sentiment > 0.4 or any(x in cat_lower for x in ["travel", "happy"]):
        tags.extend(["happy", "upbeat", "energetic"])
    else:
        tags.extend(["neutral", "balanced"])
    
    return tags

# --- 2.5 FUNCIONES DE COMPATIBILIDAD (usadas por storyboard_generator y auto_video_generator) ---

def analyze_narration(script_text: str):
    """
    Analiza la narraciÃ³n para determinar categorÃ­a y sentimiento.
    VersiÃ³n simplificada que no requiere Google Cloud.
    
    Returns:
        tuple: (category, sentiment) o (None, None) si falla
    """
    try:
        analysis = _basic_analysis(script_text)
        return analysis.get('category', None), analysis.get('sentiment', 0.0)
    except Exception as e:
        print(f"âš ï¸ Error en analyze_narration: {e}")
        return None, None

def map_ai_to_jamendo_tags(category: str, sentiment: float = 0.0) -> List[str]:
    """
    Alias de map_category_to_tags para compatibilidad.
    Mapea categorÃ­a y sentimiento a tags de Jamendo.
    """
    return map_category_to_tags(category, sentiment)

# --- 3. BÃšSQUEDA DE MÃšSICA JAMENDO ---

def extract_cc_license_code(license_url: str) -> str:
    """
    Extrae un codigo de licencia Creative Commons desde su URL.
    Ej: .../by-nc-nd/3.0/ -> CC BY-NC-ND
    """
    if not license_url:
        return "UNKNOWN"

    normalized = str(license_url).lower().strip()

    if "publicdomain/zero" in normalized or "/zero/" in normalized:
        return "CC0"

    ordered_codes = [
        "by-nc-nd",
        "by-nc-sa",
        "by-nc",
        "by-nd",
        "by-sa",
        "by",
    ]

    for code in ordered_codes:
        if f"/licenses/{code}/" in normalized:
            return f"CC {code.upper()}"

    return "UNKNOWN"


def is_youtube_safe_cc_license(license_url: str) -> bool:
    """
    Determina si una licencia CC es apta para publicarse en YouTube
    (respetando restricciones NC/ND cuando existan).
    """
    code = extract_cc_license_code(license_url)
    return code != "UNKNOWN"


def build_default_jamendo_share_url(track_id) -> str:
    """Construye URL publica de track en Jamendo si existe ID."""
    if track_id is None:
        return ""
    track_id_str = str(track_id).strip()
    if not track_id_str:
        return ""
    return f"https://www.jamendo.com/track/{track_id_str}"

def search_jamendo_api(tags, client_id, limit=1):
    """
    Llama a la API de Jamendo. VersiÃ³n robusta.
    """
    if not client_id or "TU_CLIENT_ID" in client_id:
        print("\nERROR: JAMENDO_CLIENT_ID no configurado.")
        return []
    
    # Limpiar ID por si acaso
    clean_id = client_id.strip()
    
    # Estrategia 1: BÃºsqueda Fuzzy (MÃ¡s flexible)
    tag_str = " ".join(tags)
    print(f"[Jamendo] Buscando: '{tag_str}'...")
    
    params = {
       "client_id": clean_id, 
       "format": "json", 
       "fuzzytags": tag_str,
       "limit": limit, 
       "include": "musicinfo"
       # Quitamos 'audioformat' y 'order' aquÃ­ para maximizar compatibilidad inicial
    }
    
    try:
        response = requests.get("https://api.jamendo.com/v3.0/tracks/", params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"âš ï¸ Jamendo API Error: {response.status_code} - {response.text}")
            return []

        data = response.json()
        results = data.get('results', [])
        
        # Estrategia 2: Fallback a bÃºsqueda estricta simple si falla la fuzzy
        if not results:
            print(f"[Jamendo] Sin resultados. Probando bÃºsqueda simple por tag: '{tags[0]}'")
            # Intentamos con el endpoint base sin filtros extraÃ±os, solo 1 tag
            params_fallback = {
                "client_id": clean_id,
                "format": "json",
                "tags": tags[0], # Tag estricto
                "limit": limit
            }
            res_fallback = requests.get("https://api.jamendo.com/v3.0/tracks/", params=params_fallback, timeout=15)
            if res_fallback.status_code == 200:
                results = res_fallback.json().get('results', [])

        if not results:
            print("âŒ Jamendo no devolviÃ³ pistas. Verifica tu Client ID.")
            return []
            
        tracks = []
        for tr in results:
            if tr.get('audio') and tr.get('license_ccurl'):
                track_id = tr.get('id')
                license_url = tr.get('license_ccurl', '')
                license_code = extract_cc_license_code(license_url)
                share_url = tr.get('shareurl') or build_default_jamendo_share_url(track_id)
                short_url = tr.get('shorturl', '')

                tracks.append({
                    "title": tr.get('name', 'Desconocido'),
                    "artist": tr.get('artist_name', 'Artista'),
                    "audio_url": tr['audio'],
                    "license_url": license_url,
                    "license_code": license_code,
                    "youtube_safe": is_youtube_safe_cc_license(license_url),
                    "attribution_required": license_code not in {"CC0", "UNKNOWN"},
                    "duration": tr.get('duration', 0),  # Duracion en segundos
                    "track_id": track_id,
                    "share_url": share_url,
                    "short_url": short_url,
                })
        return tracks
        
    except Exception as e:
        print(f"Error conexiÃ³n Jamendo: {e}")
        return []

def download_track(audio_url, save_path):
    """
    Descarga una pista de audio desde URL
    """
    try:
        print(f"ðŸ“¥ Descargando desde: {audio_url}")
        response = requests.get(audio_url, timeout=(10, 30), stream=True)
        
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print(f"âœ… Descargado: {save_path}")
            return save_path
        else:
            print(f"âŒ Error HTTP: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"âŒ Error descarga: {e}")
        return None

# --- 4. FUNCIÃ“N PRINCIPAL ---

def get_music_for_video(script_text: str, output_dir: str = None) -> Optional[str]:
    """
    FunciÃ³n principal: obtiene mÃºsica para un video
    """
    print("ðŸŽµ Iniciando recomendaciÃ³n musical...")
    
    # 1. Analizar guion
    analysis = analyze_script(script_text)
    
    # 2. Mapear a tags
    tags = map_category_to_tags(analysis['category'], analysis['sentiment'])
    
    # 3. Buscar mÃºsica
    jamendo_id = os.getenv('JAMENDO_CLIENT_ID', '')
    if not jamendo_id:
        print("âŒ JAMENDO_CLIENT_ID no configurado")
        return None
    
    tracks = search_jamendo_api(tags, jamendo_id, limit=5)
    
    if not tracks:
        print("âŒ No se encontraron pistas")
        return None
    
    # 4. Descargar la primera pista
    track = tracks[0]
    
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    
    filename = f"{track['artist']} - {track['title']}.mp3".replace('/', '_').replace('\\', '_')
    save_path = os.path.join(output_dir, filename)
    
    downloaded_path = download_track(track['audio_url'], save_path)
    
    if downloaded_path:
        print(f"ðŸŽ‰ MÃºsica descargada: {downloaded_path}")
        return downloaded_path
    else:
        print("âŒ FallÃ³ la descarga")
        return None

if __name__ == "__main__":
    # Ejemplo de uso
    script = """
    En este episodio exploramos los misterios de las antiguas civilizaciones, 
    descubriendo secretos ocultos y leyendas perdidas en el tiempo.
    """
    
    music_path = get_music_for_video(script)
    if music_path:
        print(f"âœ… MÃºsica lista: {music_path}")
    else:
        print("âŒ No se pudo obtener mÃºsica")
