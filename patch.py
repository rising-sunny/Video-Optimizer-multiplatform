import re

with open(r'g:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\timeline_editor_widget.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace body of copy_recraft_prompts_for_segment and remove the old negative prompt method
# We will just replace from 'def copy_recraft_prompts_for_segment(self, segment_index):' to the end of copy_recraft_negative_prompt_for_segment

pattern = re.compile(
    r'    def copy_recraft_prompts_for_segment\(self, segment_index\):\n'
    r'.*?    def copy_recraft_negative_prompt_for_segment\(self, segment_index\):\n'
    r'.*?        \)\n',
    re.DOTALL
)

new_text = """    def copy_recraft_prompts_for_segment(self, segment_index):
        \"\"\"Copia al portapapeles el prompt y negative prompt Recraft del segmento.\"\"\"
        prompt_data = self._resolve_recraft_prompt_for_segment(segment_index)
        prompt = (prompt_data or {}).get('prompt', '').strip()
        negative_prompt = (prompt_data or {}).get('negative_prompt', '').strip()
        
        if not prompt and not negative_prompt:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Sin prompts Recraft",
                f"El segmento #{segment_index + 1} no tiene un prompt ni negative prompt Recraft disponible con la configuración actual."
            )
            return

        text_to_copy = ""
        if prompt:
            text_to_copy += f"Prompt:\\n{prompt}\\n\\n"
        if negative_prompt:
            text_to_copy += f"Negative Prompt:\\n{negative_prompt}"
            
        self._copy_text_to_clipboard(
            text_to_copy.strip(),
            "Prompt y Negative Prompt Recraft",
            segment_index,
        )
"""

content = pattern.sub(new_text, content)

with open(r'g:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\timeline_editor_widget.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Patch applied to timeline_editor_widget.py")
