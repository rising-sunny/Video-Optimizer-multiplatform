import os
import json
import math
from pathlib import Path

# Try to use existing clients if possible
import sys
sys.path.append(r"C:\dev\Video-Optimizer-multiplatform")
from gemini_ai_client import GeminiAiClient

def generate_long_form_storyboard(topic: str, duration_minutes: int, language: str = 'es', output_dir: Path = None):
    print(f"Iniciando generación de documental de formato largo ({duration_minutes} min) sobre: {topic}")
    
    client = GeminiAiClient() # Using Gemini for large context
    
    # We need approx 2250 words total, split into 5 chapters = 450 words per chapter
    # 450 words / 30 words per segment = 15 segments per chapter
    chapters = [
        "Capítulo 1: El Inicio (Introducción y planteamiento del misterio)",
        "Capítulo 2: El Descubrimiento (Detalles de los hallazgos inexplicables)",
        "Capítulo 3: Las Teorías Iniciales (Explicaciones lógicas y sus fallas)",
        "Capítulo 4: Lo Inexplicable (Elementos extraños: radiación, luces, fuerzas mayores)",
        "Capítulo 5: El Legado (Conclusión y el misterio perdurable)"
    ]
    
    all_paragraphs = []
    
    for i, chap in enumerate(chapters):
        print(f"Generando {chap} ...")
        script_prompt = f"""
Escribe SOLO el texto de la voz en off para el {chap} de un documental sobre "{topic}".
Idioma: {language}.

REGLAS ESTRICTAS:
1. Este capítulo DEBE tener exactamente 450 palabras en total.
2. Divide el texto estructuralmente en EXACTAMENTE 15 párrafos cortos.
3. Cada párrafo debe tener entre 25 y 35 palabras.
4. NO uses formato de obra de teatro, ni acotaciones, ni la palabra "Narrador:". SOLO el texto a locutar.
5. Separa cada párrafo con una línea en blanco (doble salto de línea).
6. NADA de introducciones o confirmaciones, devuelve SOLO el guion.
"""
        raw_script = client._generate(script_prompt, max_tokens=8192, task_type="script_quality")
        pars = [p.strip() for p in raw_script.split('\n\n') if len(p.strip()) > 10 and not p.lower().startswith('nota:') and not p.lower().startswith('aquí tienes')]
        all_paragraphs.extend(pars)
        
    print(f"Guion total generado: {len(all_paragraphs)} párrafos.")
    
    # 2. Generate Visual Prompts for the paragraphs
    segments = []
    
    batch_size = 10
    for i in range(0, len(all_paragraphs), batch_size):
        batch = all_paragraphs[i:i+batch_size]
        print(f"Generando prompts visuales para segmentos {i+1} a {i+len(batch)}...")
        
        batch_text = ""
        for j, p in enumerate(batch):
            batch_text += f"SEGMENTO {i+j+1}:\nTexto: {p}\n\n"
            
        visual_prompt_req = f"""
Tengo los siguientes {len(batch)} segmentos de texto del guion de un documental sobre "{topic}".
Para cada segmento, diseña un "visual_prompt" en INGLÉS detallado para generar una imagen con IA que acompañe ese texto.

REGLAS DEL VISUAL PROMPT:
1. Debe ser un prompt descriptivo en INGLÉS.
2. Calidad cinematográfica, fotorrealista. Ej: "Shot on 35mm lens, atmospheric lighting, moody, historical documentary style".
3. SIEMPRE terminar con "no text, no writing, no watermarks, no signs".
4. Debes devolver tu respuesta EXCLUSIVAMENTE como un arreglo JSON válido con la siguiente estructura:

[
  {{
    "text": "<el texto original exacto>",
    "visual_prompt": "<tu prompt en inglés>"
  }}
]

AQUÍ ESTÁN LOS SEGMENTOS:
{batch_text}
"""
        try:
            raw_json = client._generate(visual_prompt_req, max_tokens=8192, task_type="script_quality")
            if "```json" in raw_json:
                raw_json = raw_json.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_json:
                raw_json = raw_json.split("```")[1].split("```")[0].strip()
                
            batch_data = json.loads(raw_json)
            for j, item in enumerate(batch_data):
                segments.append({
                    "segment_id": i + j + 1,
                    "text": item.get("text", batch[j]),
                    "visual_prompt": item.get("visual_prompt", f"Cinematic historical documentary scene about {topic}, atmospheric, no text"),
                    "duration": 12.0
                })
        except Exception as e:
            print(f"Error parseando el JSON del batch {i}: {e}")
            for j, p in enumerate(batch):
                segments.append({
                    "segment_id": i + j + 1,
                    "text": p,
                    "visual_prompt": f"Cinematic historical documentary scene about {topic}, atmospheric, highly detailed, photorealistic, 4k, no text",
                    "duration": 12.0
                })
                
    storyboard = {
        "topic": topic,
        "category": "history",
        "storyboard_format": "long_form_16_9",
        "segments": segments
    }
    
    if output_dir:
        out_path = Path(output_dir) / "storyboard.json"
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(storyboard, f, indent=2, ensure_ascii=False)
        print(f"Storyboard guardado en {out_path}")
        
    return storyboard

if __name__ == "__main__":
    out_dir = Path(r"C:\dev\Video-Optimizer-multiplatform\long_form\dyatlov_project")
    out_dir.mkdir(parents=True, exist_ok=True)
    generate_long_form_storyboard("El Incidente del Paso Diátlov (The Dyatlov Pass Mystery)", 15, "es", out_dir)
