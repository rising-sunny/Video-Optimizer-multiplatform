import re

with open(r'g:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\timeline_segment_widget.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update signals
content = re.sub(
    r'    recraft_prompt_copy_requested = pyqtSignal\(int\).*?\n    recraft_negative_prompt_copy_requested = pyqtSignal\(int\).*?\n',
    r'    recraft_prompts_copy_requested = pyqtSignal(int)  # Emite cuando se solicita copiar los prompts Recraft\n',
    content,
    flags=re.MULTILINE
)

# 2. Update buttons layout
btn_old = r'''        self\.btn_copy_recraft_prompt = QPushButton\("Prompt"\)
.*?
        prompt_buttons_layout\.addWidget\(self\.btn_copy_recraft_negative\)'''
btn_new = '''        self.btn_copy_recraft_prompts = QPushButton("Copiar Prompts")
        self.btn_copy_recraft_prompts.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.btn_copy_recraft_prompts.setToolTip(
            "Copia el prompt y negative prompt Recraft de este segmento."
        )
        self.btn_copy_recraft_prompts.setMinimumHeight(24)
        self.btn_copy_recraft_prompts.setStyleSheet("""
            QPushButton {
                padding: 2px 8px;
                font-size: 8pt;
            }
        """)
        self.btn_copy_recraft_prompts.clicked.connect(self._on_copy_recraft_prompts_clicked)
        prompt_buttons_layout.addWidget(self.btn_copy_recraft_prompts)'''
content = re.sub(btn_old, btn_new, content, flags=re.MULTILINE | re.DOTALL)

# 3. Update drag target
drag_old = r'''            self\.btn_copy_recraft_prompt,
            self\.btn_copy_recraft_negative,'''
drag_new = '''            self.btn_copy_recraft_prompts,'''
content = re.sub(drag_old, drag_new, content, flags=re.MULTILINE)

# 4. Update handlers
handlers_old = r'''    def _on_copy_recraft_prompt_clicked\(self\):
        """Solicita copiar el prompt Recraft del segmento."""
        self\.clicked\.emit\(self\.index\)
        self\.recraft_prompt_copy_requested\.emit\(self\.index\)

    def _on_copy_recraft_negative_prompt_clicked\(self\):
        """Solicita copiar el negative prompt Recraft del segmento."""
        self\.clicked\.emit\(self\.index\)
        self\.recraft_negative_prompt_copy_requested\.emit\(self\.index\)'''
handlers_new = '''    def _on_copy_recraft_prompts_clicked(self):
        """Solicita copiar el prompt y negative prompt Recraft del segmento."""
        self.clicked.emit(self.index)
        self.recraft_prompts_copy_requested.emit(self.index)'''
content = re.sub(handlers_old, handlers_new, content, flags=re.MULTILINE)

# 5. Update context menu
menu_old = r'''        copy_recraft_prompt_action = menu\.addAction\("Copiar prompt Recraft"\)
        copy_recraft_prompt_action\.setToolTip\("Copia el prompt Recraft del segmento"\)
        copy_recraft_prompt_action\.triggered\.connect\(self\._on_copy_recraft_prompt_clicked\)
        copy_recraft_negative_action = menu\.addAction\("Copiar negative prompt Recraft"\)
        copy_recraft_negative_action\.setToolTip\("Copia el negative prompt Recraft del segmento"\)
        copy_recraft_negative_action\.triggered\.connect\(self\._on_copy_recraft_negative_prompt_clicked\)'''
menu_new = '''        copy_recraft_prompts_action = menu.addAction("Copiar prompts Recraft")
        copy_recraft_prompts_action.setToolTip("Copia el prompt y negative prompt Recraft del segmento")
        copy_recraft_prompts_action.triggered.connect(self._on_copy_recraft_prompts_clicked)'''
content = re.sub(menu_old, menu_new, content, flags=re.MULTILINE)

with open(r'g:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\timeline_segment_widget.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Patch applied to timeline_segment_widget.py")
