# text_correction_engine.py
"""
Motor de corrección de texto para guiones generados por IA.
Especializado en corregir errores comunes de transcripción y nombres específicos.
"""

import re
from typing import Dict, List
import json

def _safe_print(message: str):
    """Imprime sin romper en consolas con codificación limitada (ej. cp1252)."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode('ascii', errors='replace').decode('ascii'))

class TextCorrectionEngine:
    """
    Motor especializado en corregir errores comunes en guiones generados por IA.
    Enfocado en nombres propios, términos técnicos y errores de transcripción.
    """
    
    def __init__(self):
        # Diccionario de correcciones específicas
        self.corrections = {
            # Nombres propios y términos históricos
            "Globo Fugue": "Fu-Go",
            "Fugo balloons": "Fu-Go balloons",
            "Fugo balloon": "Fu-Go balloon",
            "Bombers' Globo Fugue": "Fu-Go balloon bombs",
            
            # Errores comunes de transcripción
            "in sendiri": "incendiary",
            "in sendiri bombs": "incendiary bombs",
            "anti-person album": "anti-personnel bomb",
            "anti-person album intended": "anti-personnel bomb intended",
            "journey point one": "journey. One",
            "journey point one of": "journey. One of",
            
            # Errores gramaticales comunes
            "a lesson only had": "a lesson that had",
            "World War 2": "World War II",
            "World war II": "World War II",
            "world war II": "World War II",
            
            # Términos técnicos específicos
            "Bombas globo Fu-Go": "Fu-Go balloon bombs",
            "globo Fu-Go": "Fu-Go balloon",
            "balloon bombs designed to start fires": "balloon bombs designed to start fires",
            
            # Correcciones de puntuación
            "journey point one of the most": "journey. One of the most",
            "journey point one of": "journey. One of",
        }
        
        # Patrones regex para correcciones más complejas
        self.pattern_corrections = [
            # Corregir variaciones de Fu-Go
            (r'\bFugo\s+balloons?\b', 'Fu-Go balloons'),
            (r'\bGlobo\s+Fugue\b', 'Fu-Go'),
            (r'\bBombers\'\s+Globo\s+Fugue\b', 'Fu-Go balloon bombs'),
            
            # Corregir errores de transcripción
            (r'\bin\s+sendiri\b', 'incendiary'),
            (r'\banti-person\s+album\b', 'anti-personnel bomb'),
            (r'\bjourney\s+point\s+one\b', 'journey. One'),
            
            # Corregir World War
            (r'\bWorld\s+War\s+2\b', 'World War II'),
            (r'\bworld\s+war\s+II\b', 'World War II'),

            # Limpieza de artefactos no narrativos
            (r'(?i)\b(?:chapter|cap[ií]tulo)\s*\d+\s*[:\-–]\s*', ''),
            (r'(?i)\bhashtags?\b', ''),
            (r'(?<!\w)#\w+', ''),
            (r'(?im)^\s*#{1,6}\s+.*$', ''),
        ]
    
    def correct_text(self, text: str) -> str:
        """
        Aplica correcciones a un texto dado.
        
        Args:
            text: Texto a corregir
            
        Returns:
            Texto corregido
        """
        corrected_text = text
        
        # Aplicar correcciones directas (reemplazos exactos)
        for incorrect, correct in self.corrections.items():
            corrected_text = corrected_text.replace(incorrect, correct)
        
        # Aplicar correcciones con patrones regex
        for pattern, replacement in self.pattern_corrections:
            corrected_text = re.sub(pattern, replacement, corrected_text, flags=re.IGNORECASE)

        corrected_text = re.sub(r'\s+([,.;:!?])', r'\1', corrected_text)
        corrected_text = re.sub(r'\s+', ' ', corrected_text).strip()

        return corrected_text
    
    def correct_segment(self, segment: Dict) -> Dict:
        """
        Corrige el texto de un segmento completo.
        
        Args:
            segment: Diccionario del segmento con texto y campos relacionados.
            
        Returns:
            Segmento con texto corregido
        """
        corrected_segment = segment.copy()

        for field in ('text', 'narration_text', 'narration'):
            if field not in segment:
                continue

            original_text = segment.get(field) or ""
            corrected_text = self.correct_text(original_text)

            if corrected_text != original_text:
                corrected_segment[field] = corrected_text
                if field != 'text' and str(corrected_segment.get('text', '')).strip() == str(original_text).strip():
                    corrected_segment['text'] = corrected_text
                _safe_print(f"[OK] [{field}] '{str(original_text)[:50]}...' -> '{corrected_text[:50]}...'")

        return corrected_segment
    
    def correct_segments(self, segments: List[Dict]) -> List[Dict]:
        """
        Corrige una lista completa de segmentos.
        
        Args:
            segments: Lista de segmentos
            
        Returns:
            Lista de segmentos corregidos
        """
        corrected_segments = []
        corrections_count = 0
        
        for i, segment in enumerate(segments):
            corrected_segment = self.correct_segment(segment)
            corrected_segments.append(corrected_segment)
            
            # Contar correcciones
            changed = any(
                segment.get(field) != corrected_segment.get(field)
                for field in ('text', 'narration_text', 'narration')
            )
            if changed:
                corrections_count += 1
        
        _safe_print(f"[INFO] Se corrigieron {corrections_count} de {len(segments)} segmentos")
        return corrected_segments
    
    def correct_project_file(self, file_path: str, output_path: str = None) -> bool:
        """
        Corrige un archivo JSON de proyecto completo.
        
        Args:
            file_path: Ruta del archivo JSON original
            output_path: Ruta del archivo corregido (opcional)
            
        Returns:
            True si se corrigió exitosamente
        """
        try:
            # Cargar archivo JSON
            with open(file_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            # Determinar si es una lista de segmentos o un proyecto completo
            if isinstance(project_data, list):
                # Es una lista de segmentos
                corrected_data = self.correct_segments(project_data)
            else:
                # Es un proyecto completo con posibles segmentos anidados
                corrected_data = self._correct_project_structure(project_data)
            
            # Guardar archivo corregido
            if output_path is None:
                output_path = file_path.replace('.json', '_corrected.json')
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(corrected_data, f, indent=2, ensure_ascii=False)
            
            _safe_print(f"[SAVE] Archivo corregido guardado: {output_path}")
            return True
            
        except Exception as e:
            _safe_print(f"[ERROR] Error corrigiendo archivo: {e}")
            return False
    
    def _correct_project_structure(self, project_data: Dict) -> Dict:
        """
        Corrige segmentos dentro de una estructura de proyecto completa.
        """
        corrected_project = project_data.copy()
        
        # Buscar y corregir segmentos en diferentes ubicaciones posibles
        if 'segments' in corrected_project:
            corrected_project['segments'] = self.correct_segments(corrected_project['segments'])

        return corrected_project
    
    
    def list_corrections(self):
        """Muestra todas las correcciones configuradas."""
        _safe_print("[LIST] Correcciones configuradas:")
        for incorrect, correct in self.corrections.items():
            _safe_print(f"  '{incorrect}' -> '{correct}'")


if __name__ == "__main__":
    # Ejemplo de uso
    corrector = TextCorrectionEngine()
    corrector.list_corrections()
    
    # Corregir archivo de ejemplo
    _safe_print("\n[RUN] Corrigiendo archivo de ejemplo...")
    corrector.correct_project_file("C:/Users/sunse/Downloads/Fu-Go.json")
