import json
from pathlib import Path

STYLESHEET = """
QMainWindow {
    background-color: #0b0e14;
}

QWidget {
    background-color: transparent;
    color: #e2e8f0;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 10pt;
}

QLabel {
    color: #e2e8f0;
    background: transparent;
}

QLabel#title {
    font-size: 26pt;
    font-weight: 800;
    color: #ffffff;
    padding-bottom: 10px;
}

QLabel#subtitle {
    font-size: 11pt;
    color: #94a3b8;
}

QLabel#errorText {
    color: #f87171;
    font-weight: bold;
}

QLabel#successText {
    color: #4ade80;
    font-weight: bold;
}

QFrame#videoPreview {
    background-color: #000000;
    border-radius: 6px;
    border: 1px solid #1e293b;
}

QFrame#card {
    background-color: #151a22;
    border: 1px solid #1e293b;
    border-radius: 12px;
    padding: 20px;
}

QPushButton {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 10px 18px;
    font-size: 10pt;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #334155;
    border-color: #475569;
}

QPushButton:pressed {
    background-color: #0f172a;
}

QPushButton#accent {
    background-color: #00e5ff;
    color: #000000;
    font-weight: 700;
    border: none;
    border-radius: 6px;
    padding: 12px 24px;
}

QPushButton#accent:hover {
    background-color: #33eeff;
}

QPushButton#success {
    background-color: #a855f7;
    color: #ffffff;
    font-weight: 700;
    border: none;
    border-radius: 6px;
    padding: 12px 24px;
}

QPushButton#success:hover {
    background-color: #b975f8;
}

QPushButton:disabled {
    background-color: #0f172a;
    color: #475569;
    border-color: #1e293b;
}

QLineEdit, QTextEdit, QComboBox, QSpinBox {
    background-color: #0f172a;
    color: #f8fafc;
    border: 1px solid #1e293b;
    border-radius: 6px;
    padding: 10px;
    selection-background-color: #00e5ff;
    selection-color: #000000;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #00e5ff;
    background-color: #151a22;
}

QComboBox::drop-down {
    border: none;
    padding-right: 10px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #94a3b8;
    margin-right: 8px;
}

QTabWidget::pane {
    border: 1px solid #1e293b;
    border-radius: 8px;
    background-color: #151a22;
    top: -1px;
}

QTabBar::tab {
    background-color: transparent;
    color: #94a3b8;
    padding: 12px 24px;
    border: none;
    font-weight: 600;
    font-size: 11pt;
    border-bottom: 2px solid transparent;
    margin-right: 4px;
}

QTabBar::tab:selected {
    color: #00e5ff;
    border-bottom: 2px solid #00e5ff;
}

QTabBar::tab:hover:!selected {
    color: #e2e8f0;
    border-bottom: 2px solid #334155;
}

QCheckBox, QRadioButton {
    color: #e2e8f0;
    spacing: 10px;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 20px;
    height: 20px;
    border: 2px solid #334155;
    border-radius: 4px;
    background-color: #0f172a;
}

QRadioButton::indicator {
    border-radius: 10px;
}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #00e5ff;
    border-color: #00e5ff;
}

QProgressBar {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 6px;
    text-align: center;
    color: #ffffff;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a855f7, stop:1 #00e5ff);
    border-radius: 5px;
}

QScrollBar:vertical {
    background-color: transparent;
    width: 14px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #334155;
    border-radius: 7px;
    min-height: 30px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QGroupBox {
    border: 1px solid #1e293b;
    border-radius: 8px;
    margin-top: 18px;
    padding-top: 14px;
    font-weight: 600;
    background-color: rgba(21, 26, 34, 0.4);
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: #00e5ff;
    background-color: #0b0e14;
    border-radius: 4px;
}
"""


# ========== SISTEMA DE TEMAS ==========
THEMES = {
    'editorial': {
        'name': 'Editorial (blanco/aireado)',
        'main_bg': '#f8f8f6',
        'widget_bg': '#f8f8f6',
        'card_bg': '#ffffff',
        'text_primary': '#1f2831',
        'text_secondary': '#6f7c89',
        'button_bg': '#f3f5f7',
        'button_hover': '#ebeff3',
        'accent': '#365f87',
        'accent_hover': '#2f5478',
        'success': '#3f6d59',
        'success_hover': '#355d4c',
        'input_bg': '#ffffff',
        'input_border': '#d7dee5',
        'input_focus': '#7f98b2',
        'tab_bg': '#f1f4f7',
        'tab_selected': '#ffffff',
        'tab_hover': '#eaedf1',
        'border': '#dde3e9',
        'scrollbar_bg': '#f1f4f7',
        'scrollbar_handle': '#c6d0da',
        'scrollbar_handle_hover': '#aebac6',
        'disabled_bg': '#f2f4f6',
        'disabled_text': '#9ca8b4',
    },
    'oscuro': {
        'name': 'Oscuro Minimal',
        'main_bg': '#121417',
        'widget_bg': '#121417',
        'card_bg': '#1b1f24',
        'text_primary': '#e8eaed',
        'text_secondary': '#9aa4af',
        'button_bg': '#222831',
        'button_hover': '#2b333d',
        'accent': '#3f7db3',
        'accent_hover': '#4f8dc3',
        'success': '#3a7d64',
        'success_hover': '#46906f',
        'input_bg': '#161b21',
        'input_border': '#2f3842',
        'input_focus': '#4a90d0',
        'tab_bg': '#11151a',
        'tab_selected': '#1b2129',
        'tab_hover': '#202731',
        'border': '#2b333d',
        'scrollbar_bg': '#11151a',
        'scrollbar_handle': '#2b333d',
        'scrollbar_handle_hover': '#394552',
        'disabled_bg': '#15181c',
        'disabled_text': '#626d78',
    },
    'claro': {
        'name': 'Claro Minimal',
        'main_bg': '#f3f5f7',
        'widget_bg': '#f3f5f7',
        'card_bg': '#ffffff',
        'text_primary': '#1f2933',
        'text_secondary': '#6b7785',
        'button_bg': '#e7ebef',
        'button_hover': '#dbe2e9',
        'accent': '#2d6ea3',
        'accent_hover': '#245d8c',
        'success': '#2f7a5f',
        'success_hover': '#28694f',
        'input_bg': '#ffffff',
        'input_border': '#c4ced8',
        'input_focus': '#2d6ea3',
        'tab_bg': '#eef2f6',
        'tab_selected': '#ffffff',
        'tab_hover': '#e5ebf1',
        'border': '#d6dde5',
        'scrollbar_bg': '#eef2f6',
        'scrollbar_handle': '#c5cfda',
        'scrollbar_handle_hover': '#aebac8',
        'disabled_bg': '#f0f2f5',
        'disabled_text': '#9aa6b2',
    },
    'azul': {
        'name': 'Azul Grafito',
        'main_bg': '#101923',
        'widget_bg': '#101923',
        'card_bg': '#172433',
        'text_primary': '#e5edf5',
        'text_secondary': '#98aec2',
        'button_bg': '#203246',
        'button_hover': '#2a3e54',
        'accent': '#4d84b6',
        'accent_hover': '#5a95c7',
        'success': '#3e7f73',
        'success_hover': '#4a9083',
        'input_bg': '#152131',
        'input_border': '#2a3e54',
        'input_focus': '#5a95c7',
        'tab_bg': '#0f1822',
        'tab_selected': '#1a293a',
        'tab_hover': '#223345',
        'border': '#2b3f53',
        'scrollbar_bg': '#0f1822',
        'scrollbar_handle': '#2b3f53',
        'scrollbar_handle_hover': '#3a546d',
        'disabled_bg': '#141c26',
        'disabled_text': '#617287',
    },
    'verde': {
        'name': 'Verde Oliva',
        'main_bg': '#111815',
        'widget_bg': '#111815',
        'card_bg': '#1a2520',
        'text_primary': '#e6ece8',
        'text_secondary': '#9bac9f',
        'button_bg': '#223029',
        'button_hover': '#2b3b33',
        'accent': '#4f8a63',
        'accent_hover': '#5f9b74',
        'success': '#3f7a56',
        'success_hover': '#4a8a63',
        'input_bg': '#16211c',
        'input_border': '#2b3b33',
        'input_focus': '#5f9b74',
        'tab_bg': '#101713',
        'tab_selected': '#1c2922',
        'tab_hover': '#25352d',
        'border': '#2a3a31',
        'scrollbar_bg': '#101713',
        'scrollbar_handle': '#2a3a31',
        'scrollbar_handle_hover': '#384d42',
        'disabled_bg': '#151d18',
        'disabled_text': '#65766c',
    },
    'púrpura': {
        'name': 'Ciruela Suave',
        'main_bg': '#17141a',
        'widget_bg': '#17141a',
        'card_bg': '#231f28',
        'text_primary': '#ece7f2',
        'text_secondary': '#a89db5',
        'button_bg': '#2f2936',
        'button_hover': '#3a3243',
        'accent': '#76618d',
        'accent_hover': '#86739d',
        'success': '#5f7e68',
        'success_hover': '#6f8f78',
        'input_bg': '#1f1a24',
        'input_border': '#3a3243',
        'input_focus': '#86739d',
        'tab_bg': '#161219',
        'tab_selected': '#2a2431',
        'tab_hover': '#342d3d',
        'border': '#3b3344',
        'scrollbar_bg': '#161219',
        'scrollbar_handle': '#3b3344',
        'scrollbar_handle_hover': '#4d4259',
        'disabled_bg': '#1b1720',
        'disabled_text': '#746883',
    },
    'naranja': {
        'name': 'Terracota Suave',
        'main_bg': '#1a1411',
        'widget_bg': '#1a1411',
        'card_bg': '#26201c',
        'text_primary': '#efe8e2',
        'text_secondary': '#b6a69a',
        'button_bg': '#332a24',
        'button_hover': '#3f342d',
        'accent': '#9d6947',
        'accent_hover': '#af7a55',
        'success': '#6f7f5a',
        'success_hover': '#7f9068',
        'input_bg': '#221c18',
        'input_border': '#3c312a',
        'input_focus': '#af7a55',
        'tab_bg': '#191310',
        'tab_selected': '#28211d',
        'tab_hover': '#332a24',
        'border': '#3c312a',
        'scrollbar_bg': '#191310',
        'scrollbar_handle': '#3c312a',
        'scrollbar_handle_hover': '#4d3f36',
        'disabled_bg': '#1f1915',
        'disabled_text': '#7f7066',
    },
}


def generate_stylesheet(theme_key='editorial'):
    """Genera un stylesheet basado en el tema seleccionado"""
    if theme_key not in THEMES:
        theme_key = 'editorial'
    
    theme = THEMES[theme_key]
    
    return f"""
QMainWindow {{
    background-color: {theme['main_bg']};
}}

QWidget {{
    background-color: {theme['widget_bg']};
    color: {theme['text_primary']};
    font-family: 'Segoe UI', 'Noto Sans', sans-serif;
    font-size: 10pt;
}}

QLabel {{
    color: {theme['text_primary']};
    background: transparent;
}}

QLabel#title {{
    font-size: 20pt;
    font-weight: 600;
    font-family: 'Georgia', 'Times New Roman', serif;
    color: {theme['text_primary']};
}}

QLabel#subtitle {{
    font-size: 9pt;
    color: {theme['text_secondary']};
}}

QLabel#panelTitle {{
    font-size: 11pt;
    font-weight: 600;
    color: {theme['text_secondary']};
}}

QFrame#card {{
    background-color: {theme['card_bg']};
    border: 1px solid {theme['border']};
    border-radius: 12px;
    padding: 18px;
}}

QFrame#headerSeparator {{
    background-color: {theme['border']};
    border: none;
    min-width: 1px;
    max-width: 1px;
    margin: 6px 10px;
}}

QPushButton {{
    background-color: {theme['button_bg']};
    color: {theme['text_primary']};
    border: 1px solid {theme['border']};
    border-radius: 6px;
    padding: 9px 16px;
    min-height: 32px;
    font-size: 10pt;
}}

QPushButton:hover {{
    background-color: {theme['button_hover']};
}}

QPushButton:pressed {{
    background-color: {theme['tab_selected']};
}}

QPushButton#accent {{
    background-color: {theme['accent']};
    border-color: {theme['accent']};
    color: #ffffff;
    font-weight: 600;
}}

QPushButton#accent:hover {{
    background-color: {theme['accent_hover']};
    border-color: {theme['accent_hover']};
}}

QPushButton#success {{
    background-color: {theme['success']};
    border-color: {theme['success']};
    color: #ffffff;
    font-weight: 600;
}}

QPushButton#success:hover {{
    background-color: {theme['success_hover']};
    border-color: {theme['success_hover']};
}}

QPushButton:disabled {{
    background-color: {theme['disabled_bg']};
    color: {theme['disabled_text']};
    border-color: {theme['disabled_bg']};
}}

QLineEdit, QTextEdit, QComboBox, QSpinBox {{
    background-color: {theme['input_bg']};
    color: {theme['text_primary']};
    border: 1px solid {theme['input_border']};
    border-radius: 6px;
    padding: 7px;
}}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {theme['input_focus']};
}}

QComboBox::drop-down {{
    background: transparent;
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {theme['card_bg']};
    color: {theme['text_primary']};
    border: 1px solid {theme['border']};
    selection-background-color: {theme['accent']};
    selection-color: #ffffff;
}}

QTabWidget::pane {{
    border: 1px solid {theme['border']};
    border-radius: 8px;
    margin-top: 8px;
    background-color: {theme['card_bg']};
}}

QTabBar::tab {{
    background-color: {theme['tab_bg']};
    color: {theme['text_secondary']};
    border: 1px solid transparent;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 9px 18px;
    margin-right: 4px;
    min-height: 30px;
}}

QTabBar::tab:selected {{
    background-color: {theme['tab_selected']};
    color: {theme['text_primary']};
    border-color: {theme['border']};
    border-bottom-color: {theme['tab_selected']};
}}

QTabBar::tab:hover {{
    background-color: {theme['tab_hover']};
}}

QCheckBox, QRadioButton {{
    color: {theme['text_primary']};
    spacing: 6px;
}}

QCheckBox#trendIdea {{
    padding: 4px 0px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {theme['border']};
    border-radius: 3px;
    background-color: {theme['input_bg']};
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {theme['accent']};
    border-color: {theme['accent']};
}}

QProgressBar {{
    background-color: {theme['input_bg']};
    border: 1px solid {theme['border']};
    border-radius: 6px;
    text-align: center;
    color: {theme['text_primary']};
}}

QProgressBar::chunk {{
    background-color: {theme['accent']};
    border-radius: 5px;
}}

QScrollBar:vertical {{
    background-color: {theme['scrollbar_bg']};
    width: 10px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background-color: {theme['scrollbar_handle']};
    border-radius: 5px;
    min-height: 20px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {theme['scrollbar_handle_hover']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QGroupBox {{
    border: 1px solid {theme['border']};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {theme['text_secondary']};
}}

QTextEdit#logView {{
    background-color: {theme['main_bg']};
    border: 1px solid {theme['border']};
    border-radius: 6px;
    font-family: 'Consolas', 'Cascadia Mono', 'Courier New', monospace;
    font-size: 9pt;
}}

QLabel#thumbPreview {{
    border: 1px dashed {theme['border']};
    border-radius: 8px;
    background-color: {theme['input_bg']};
    color: {theme['text_secondary']};
    padding: 10px;
}}

/* --- Editor de Segmentos --- */
TimelineSegment {{
    background-color: {theme['card_bg']};
    border: 1px solid {theme['border']};
    border-radius: 8px;
}}

TimelineSegment[state="selected"] {{
    background-color: {theme['button_hover']};
    border: 2px solid {theme['accent']};
}}

TimelineSegment[state="checked"] {{
    background-color: {theme['input_bg']};
    border: 2px solid {theme['input_focus']};
}}

TimelineSegment[state="drop_target"] {{
    background-color: {theme['button_hover']};
    border: 2px dashed {theme['success']};
}}

TimelineSegment QLabel#segmentNumber {{
    background-color: {theme['button_bg']};
    color: {theme['text_primary']};
    padding: 3px 8px;
    border-radius: 3px;
    font-weight: bold;
    font-size: 11pt;
    border: 1px solid {theme['border']};
}}

TimelineSegment QLabel#segmentText {{
    color: {theme['text_primary']};
    font-size: 9pt;
    padding: 4px;
    background-color: {theme['input_bg']};
    border-radius: 3px;
    border: 1px solid {theme['border']};
}}

TimelineSegment QLabel#segmentImage {{
    background-color: {theme['input_bg']};
    border: 1px solid {theme['border']};
    border-radius: 6px;
    color: {theme['text_secondary']};
    font-size: 9pt;
}}

GroupedSegmentsWidget QLabel#groupedImage {{
    background-color: {theme['input_bg']};
    border: 1px solid {theme['border']};
    border-radius: 6px;
    color: {theme['text_secondary']};
    font-size: 9pt;
}}

GroupedSegmentsWidget QLabel#groupedBadge {{
    background-color: {theme['button_bg']};
    color: {theme['accent']};
    border: 1px solid {theme['border']};
    border-radius: 4px;
    padding: 3px 6px;
    font-size: 8pt;
    font-weight: bold;
}}
"""



def load_theme_preference():
    """Carga la preferencia de tema guardada"""
    default_theme = 'editorial'
    config_path = Path("gui_config.json")
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                theme = config.get('theme', default_theme)
                # Migración de valor heredado del default previo.
                if theme == 'oscuro':
                    return default_theme
                if theme in THEMES:
                    return theme
        except Exception as e:
            print(f"️ Error cargando preferencia de tema: {e}")
    return default_theme


def save_theme_preference(theme_key):
    """Guarda la preferencia de tema"""
    config_path = Path("gui_config.json")
    try:
        config = {}
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        config['theme'] = theme_key
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"️ Error guardando preferencia de tema: {e}")


