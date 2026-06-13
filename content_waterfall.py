import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Agregar directorio al path para poder importar módulos del proyecto
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# Configurar encoding para Windows
import io
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if isinstance(sys.stderr, io.TextIOWrapper):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    from claude_client import ClaudeAiClient
    from groq_client import GroqAiClient
except ImportError as e:
    print(f"Error importando clientes de IA: {e}")
    sys.exit(1)


def generate_waterfall_angles(base_topic: str, research_context: str = "") -> list:
    """
    Usa la IA para analizar el tema de un video largo y generar 3 ángulos 
    (sub-temas) específicos y altamente virales para Shorts.
    """
    print(f"\n🌊 Iniciando Content Waterfall para: '{base_topic}'")
    print("🧠 Analizando tema para extraer 3 ángulos virales...")

    prompt = f"""
    Actúa como un estratega de contenido viral para YouTube Shorts.
    Tenemos un video largo exitoso sobre el siguiente tema: "{base_topic}".
    {f"Contexto adicional: {research_context}" if research_context else ""}
    
    Tu objetivo es derivar 3 ideas EXACTAS para YouTube Shorts basadas en este tema. 
    Cada Short debe explorar un ángulo distinto del misterio o historia.
    
    REGLA ESTRICTA (The 10k+ Formula):
    Cada idea debe estar formulada de manera que permita un "Triple Gancho" (Sujeto + Número + Adjetivo).
    Ejemplos de buenos ángulos:
    - "Los 3 secretos más oscuros de..."
    - "El misterio inexplicable de X..."
    - "Por qué la historia te mintió sobre..."
    
    Devuelve ÚNICAMENTE un array en formato JSON puro con 3 strings, sin texto adicional, sin markdown.
    Ejemplo: ["El secreto oscuro de X", "3 datos aterradores de Y", "La verdad oculta sobre Z"]
    """

    client = ClaudeAiClient()
    response = client._generate(prompt)
    
    if not response:
        print("⚠️ Claude falló, intentando con Groq...")
        client = GroqAiClient()
        response = client._generate(prompt)

    if not response:
        print("❌ Error: No se pudo generar los ángulos con la IA.")
        return []

    # Limpiar respuesta
    clean_resp = response.strip()
    if clean_resp.startswith("```json"):
        clean_resp = clean_resp[7:]
    if clean_resp.startswith("```"):
        clean_resp = clean_resp[3:]
    if clean_resp.endswith("```"):
        clean_resp = clean_resp[:-3]
    
    try:
        angles = json.loads(clean_resp.strip())
        if isinstance(angles, list) and len(angles) >= 3:
            return angles[:3]
        else:
            print("⚠️ El formato JSON devuelto no es una lista de 3 elementos.")
    except Exception as e:
        print(f"❌ Error parseando JSON de la IA: {e}\nRespuesta cruda: {response}")
    
    return []


def run_pipeline_for_topic(topic: str, provider: str = None):
    """
    Ejecuta el pipeline de Shorts para un tema específico.
    """
    print(f"\n🚀 Ejecutando daily_short_pipeline para: '{topic}'")
    cmd = [sys.executable, "daily_short_pipeline.py", "--topic", topic]
    if provider:
        cmd.extend(["--provider", provider])
        
    try:
        subprocess.run(cmd, check=True)
        print(f"✅ Pipeline completado para: '{topic}'")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error ejecutando pipeline para '{topic}': {e}")


def main():
    parser = argparse.ArgumentParser(description="Automatización de Content Waterfall (Largo -> Corto)")
    parser.add_argument("--topic", type=str, help="Tema del video largo a partir del cual generar Shorts")
    parser.add_argument("--project", type=str, help="Ruta a un storyboard.json de un proyecto largo exitoso")
    parser.add_argument("--provider", type=str, default="fal", help="Proveedor de imágenes/video (ej: fal)")
    
    args = parser.parse_args()

    base_topic = args.topic
    research_context = ""

    if args.project:
        project_path = Path(args.project)
        if project_path.exists():
            try:
                with open(project_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    base_topic = data.get("topic", base_topic)
                    
                    # Intentar extraer contexto de investigación si existe
                    segments = data.get("segments", [])
                    research_texts = [seg.get("narration_text", "") for seg in segments[:5]]
                    research_context = " ".join(research_texts)[:1000] # Solo los primeros 1000 chars de contexto
            except Exception as e:
                print(f"Error leyendo proyecto: {e}")
                sys.exit(1)
        else:
            print(f"❌ Archivo no encontrado: {args.project}")
            sys.exit(1)

    if not base_topic:
        print("❌ Debes proporcionar un --topic o un archivo --project")
        sys.exit(1)

    angles = generate_waterfall_angles(base_topic, research_context)
    
    if not angles:
        print("❌ No se pudieron derivar los 3 ángulos. Abortando.")
        sys.exit(1)

    print("\n✅ Ángulos generados:")
    for i, angle in enumerate(angles, 1):
        print(f"  {i}. {angle}")

    print("\n⏳ Iniciando cascada de generación (3 Shorts)...")
    for angle in angles:
        run_pipeline_for_topic(angle, args.provider)

    print("\n🎉 Content Waterfall finalizado con éxito. Se han derivado 3 Shorts.")

if __name__ == "__main__":
    main()
