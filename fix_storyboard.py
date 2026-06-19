import json
import re
from pathlib import Path

def main():
    sb_path = Path(r"C:\dev\Video-Optimizer-multiplatform\long_form\dyatlov_project\storyboard.json")
    with open(sb_path, "r", encoding="utf-8") as f:
        sb = json.load(f)
        
    text = sb["segments"][0]["text"]
    
    # Remove think tags
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    
    # Split into sentences
    sentences = [s.strip() + "." for s in text.split(".") if len(s.strip()) > 5]
    
    segments = []
    current_chunk = ""
    seg_id = 1
    
    for s in sentences:
        current_chunk += s + " "
        # If the chunk has roughly 20-35 words, save it as a segment
        if len(current_chunk.split()) >= 25:
            # Generate a varied visual prompt based on the chunk
            prompt = f"Cinematic historical documentary scene about The Dyatlov Pass Mystery, atmospheric, highly detailed, photorealistic, 4k. Context: {current_chunk[:50]}... no text, no writing, no watermarks"
            
            segments.append({
                "segment_id": seg_id,
                "text": current_chunk.strip(),
                "visual_prompt": prompt,
                "duration": 12.0
            })
            seg_id += 1
            current_chunk = ""
            
    if current_chunk.strip():
        segments.append({
            "segment_id": seg_id,
            "text": current_chunk.strip(),
            "visual_prompt": "Cinematic historical documentary scene about The Dyatlov Pass Mystery, snow, mystery, 4k, no text",
            "duration": 12.0
        })
        
    sb["segments"] = segments
    
    with open(sb_path, "w", encoding="utf-8") as f:
        json.dump(sb, f, indent=2, ensure_ascii=False)
        
    print(f"Storyboard reestructurado: {len(segments)} segmentos creados.")

if __name__ == "__main__":
    main()
