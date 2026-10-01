#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Music Recommender v2.0 - Sistema de recomendaciÃ³n musical basado en Jamendo
Analiza guiones con IA para recomendar mÃºsica apropiada
"""

import os
import re
import json
import time
import threading
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
    """Apta para un video de YouTube: solo CC0, CC BY y CC BY-SA (ver music_license)."""
    from music_license import license_code, license_problem
    return license_problem(license_code(license_url)) is None


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
    Busca pistas en Jamendo que se puedan usar en un video de YouTube.

    Solo CC BY / CC BY-SA (ccnc=false, ccnd=false): NC no se puede monetizar y
    ND no se puede sincronizar con imagen (Creative Commons lo considera obra
    derivada). Tambien descarta los artistas que ya generaron reclamos de
    Content ID (daily_shorts/music_claims.json). Ver music_license.py.
    Cada pista trae `attribution_text` (ingles) para la descripcion.
    """
    from music_license import JAMENDO_SAFE_PARAMS, filter_tracks

    if not client_id or "TU_CLIENT_ID" in client_id:
        print("\nERROR: JAMENDO_CLIENT_ID no configurado.")
        return []

    clean_id = client_id.strip()
    # Se piden de mas: los artistas bloqueados se descartan despues.
    fetch = max(int(limit or 1) * 4, 20)
    fetch = min(fetch, 200)

    tag_str = " ".join(tags)
    print(f"[Jamendo] Buscando (solo CC BY / CC BY-SA): '{tag_str}'...")

    params = {
        "client_id": clean_id,
        "format": "json",
        "fuzzytags": tag_str,
        "limit": fetch,
        "include": "musicinfo licenses",
        **JAMENDO_SAFE_PARAMS,
    }

    try:
        results = []
        # Jamendo a veces devuelve 0 resultados de forma pasajera: un reintento.
        for attempt in range(2):
            response = requests.get("https://api.jamendo.com/v3.0/tracks/", params=params, timeout=20)
            if response.status_code != 200:
                print(f"[Jamendo] Error de API: {response.status_code} - {response.text[:200]}")
                return []
            results = response.json().get('results', [])
            if results:
                break
            time.sleep(1.0)

        # Fallback: busqueda simple por un solo tag (mismos filtros de licencia).
        if not results and tags:
            print(f"[Jamendo] Sin resultados. Probando busqueda simple por tag: '{tags[0]}'")
            params_fallback = {
                "client_id": clean_id,
                "format": "json",
                "tags": tags[0],
                "limit": fetch,
                "include": "licenses",
                **JAMENDO_SAFE_PARAMS,
            }
            res_fallback = requests.get("https://api.jamendo.com/v3.0/tracks/", params=params_fallback, timeout=15)
            if res_fallback.status_code == 200:
                results = res_fallback.json().get('results', [])

        if not results:
            print("[Jamendo] No devolvio pistas aptas para video (CC BY / CC BY-SA).")
            return []

        tracks = []
        for tr in results:
            if not (tr.get('audio') and tr.get('license_ccurl')):
                continue
            track_id = tr.get('id')
            license_url = tr.get('license_ccurl', '')
            tracks.append({
                "title": tr.get('name', 'Desconocido'),
                "artist": tr.get('artist_name', 'Artista'),
                "artist_id": tr.get('artist_id', ''),
                "audio_url": tr['audio'],
                "license_url": license_url,
                "license_code": extract_cc_license_code(license_url),
                "content_id_free": tr.get('content_id_free'),
                "duration": tr.get('duration', 0),  # Duracion en segundos
                "track_id": track_id,
                "share_url": tr.get('shareurl') or build_default_jamendo_share_url(track_id),
                "short_url": tr.get('shorturl', ''),
                "source": "jamendo",
            })

        kept, dropped = filter_tracks(tracks)
        if dropped:
            reasons = sorted({why for _, why in dropped})
            print(f"[Jamendo] Descartadas {len(dropped)} pista(s): {'; '.join(reasons)[:200]}")
        return kept[:max(1, int(limit or 1))]

    except Exception as e:
        print(f"Error conexion Jamendo: {e}")
        return []

_DOWNLOAD_LOCKS = {}
_DOWNLOAD_LOCKS_GUARD = threading.Lock()


def jamendo_mirrors(url):
    """La URL original y el espejo mp3l.jamendo.com del mismo tema y formato.

    prod-1.storage.jamendo.com a veces no resuelve (DNS) o entrega a goteo; el
    espejo sirve el mismo archivo (2026-09-24: 3.1 MB en 2.6 s contra 6.1 s).
    """
    urls = [url] if url else []
    m = re.search(r"trackid=(\d+)", str(url or ""))
    if m:
        fmt = re.search(r"format=(\w+)", str(url or ""))
        alt = f"https://mp3l.jamendo.com/?trackid={m.group(1)}&format={fmt.group(1) if fmt else 'mp31'}"
        if alt not in urls:
            urls.append(alt)
    return urls


def download_audio(url, dest, progress=None, cancelled=None, attempts=4, timeout=(10, 30),
                   http_get=None, sleep=time.sleep, reuse_existing=True):
    """Descarga robusta de un audio: reintenta, reanuda y prueba el espejo.

    - Cortes de DNS/conexion y lecturas lentas ("Read timed out") se reintentan;
      lo ya bajado se reanuda con Range en vez de empezar de cero.
    - Intentos: original, original (reanuda), espejo, espejo (reanuda).
    - Un solo download por archivo: si la forma de onda y la vista previa piden
      el mismo tema a la vez, el segundo espera y usa el archivo del primero.
    - Se baja a `dest + ".part"` y se renombra al terminar: nunca queda un mp3
      cortado con el nombre final.

    progress(pct) y cancelled() son opcionales. reuse_existing=False baja de nuevo
    aunque el archivo exista (rutas fijas como temp_bgm.mp3: si no, un video se
    quedaria con la musica del anterior). Devuelve dest, None si se cancelo, o
    lanza RuntimeError con el ultimo error.
    """
    http_get = http_get or requests.get
    key = os.path.abspath(dest)
    with _DOWNLOAD_LOCKS_GUARD:
        lock = _DOWNLOAD_LOCKS.setdefault(key, threading.Lock())
    with lock:
        if not reuse_existing and os.path.exists(dest):
            os.remove(dest)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            if progress:
                progress(100)
            return dest
        part = dest + ".part"
        mirrors = jamendo_mirrors(url)
        plan = [mirrors[0], mirrors[0]] + ([mirrors[1], mirrors[1]] if len(mirrors) > 1 else [mirrors[0]] * 2)
        part_src = None
        last_error = None
        for attempt, src in enumerate(plan[:max(1, attempts)]):
            if part_src != src and os.path.exists(part):
                os.remove(part)                     # otro servidor: no se mezclan bytes
            have = os.path.getsize(part) if os.path.exists(part) else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            try:
                response = http_get(src, stream=True, timeout=timeout, headers=headers)
                if response.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {response.status_code}")
                if have and response.status_code == 200:
                    have = 0                        # el servidor ignoro el Range: de cero
                part_src = src
                length = int(response.headers.get("content-length") or 0)
                total = have + length if length else 0
                done = have
                with open(part, "ab" if have else "wb") as f:
                    for chunk in response.iter_content(chunk_size=65536):
                        if cancelled and cancelled():
                            return None
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            progress(min(99, int(done * 100 / total)))
                if total and done < total:
                    raise RuntimeError(f"descarga incompleta ({done}/{total} bytes)")
                if done <= 0:
                    raise RuntimeError("descarga vacia")
                os.replace(part, dest)
                if progress:
                    progress(100)
                return dest
            except Exception as exc:
                last_error = exc
                if part_src is None:
                    part_src = src
                print(f"[Jamendo] intento {attempt + 1} fallo ({type(exc).__name__}: {str(exc)[:120]}); reintentando")
                if attempt + 1 < min(len(plan), max(1, attempts)):
                    sleep(min(2 * (attempt + 1), 6))
        raise RuntimeError(f"No se pudo descargar el audio de Jamendo: {last_error}")


def download_track(audio_url, save_path):
    """Descarga una pista de audio (con reintentos, reanudacion y espejo). None si falla."""
    try:
        print(f"[Jamendo] Descargando: {audio_url}")
        path = download_audio(audio_url, save_path, reuse_existing=False)
        print(f"[Jamendo] Descargado: {save_path}")
        return path
    except Exception as e:
        print(f"[Jamendo] Error de descarga: {e}")
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
        output_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
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
