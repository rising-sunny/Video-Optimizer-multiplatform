import os
from ai.ai_factory import AIFactory
import sys
import platform as _platform
from infra.env_loader import load_project_env
load_project_env()
from infra.video_config import VideoConfig
import faulthandler as _faulthandler

# Evita fallos por UnicodeEncodeError en consolas Windows con codepage legacy.
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                _stream.reconfigure(errors="replace")
            except Exception:
                pass

# Captura fallos nativos que no pasan por sys.excepthook.
_FAULT_HANDLER_STREAM = None
try:
    _FAULT_HANDLER_STREAM = open("crash_faulthandler.log", "a", encoding="utf-8")
    _faulthandler.enable(file=_FAULT_HANDLER_STREAM, all_threads=True)
except Exception:
    _FAULT_HANDLER_STREAM = None

# En algunos equipos Windows, platform.system/machine/uname puede bloquearse
# por consultas WMI. Forzamos una implementación estable para el proceso.
if os.name == "nt":
    def _safe_platform_system():
        return "Windows"

    def _safe_platform_machine():
        return (
            os.environ.get("PROCESSOR_ARCHITECTURE")
            or os.environ.get("PROCESSOR_IDENTIFIER")
            or "AMD64"
        )

    def _safe_platform_uname():
        machine = _safe_platform_machine()
        try:
            return _platform.uname_result(
                "Windows",
                os.environ.get("COMPUTERNAME", ""),
                "",
                "",
                machine,
                machine,
            )
        except Exception:
            return ("Windows", os.environ.get("COMPUTERNAME", ""), "", "", machine, machine)

    _platform.system = _safe_platform_system
    _platform.machine = _safe_platform_machine
    _platform.uname = _safe_platform_uname

# --- CONFIGURAR FFMPEG Y FFPROBE ---
print("Configurando FFmpeg y ffprobe...")
try:
    # Usar el nuevo método que detecta automáticamente
    VideoConfig.ensure_ffmpeg_in_path()
    
    # Verificar que ffprobe esté disponible
    if VideoConfig.FFPROBE_BINARY_PATH and os.path.exists(VideoConfig.FFPROBE_BINARY_PATH):
        # Usar repr() para evitar problemas con caracteres especiales en rutas
        print(f"[OK] ffprobe detectado: {repr(VideoConfig.FFPROBE_BINARY_PATH)}")
    else:
        print("[!] ffprobe no encontrado - la validación de videos puede fallar")
        
except Exception as e:
    print(f"ERROR: No se pudo configurar FFmpeg: {e}")

# --- GLOBAL CRASH HANDLERS ---
# Capturar excepciones no manejadas para diagnosticar cierres silenciosos
import traceback as _tb
import threading as _threading
from datetime import datetime as _dt

def _crash_log(msg):
    """Escribe en crash_log.txt y stderr"""
    try:
        with open("crash_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\\n{'='*60}\\n")
            f.write(f"[{_dt.now().isoformat()}] {msg}\\n")
    except Exception:
        pass
    print(msg, file=sys.stderr)

def _global_excepthook(exc_type, exc_value, exc_tb):
    """Captura excepciones no manejadas (incluye crashes en signal/slot de Qt)"""
    tb_str = ''.join(_tb.format_exception(exc_type, exc_value, exc_tb))
    _crash_log(f"UNHANDLED EXCEPTION:\\n{tb_str}")

def _thread_excepthook(args):
    """Captura excepciones en threads"""
    tb_str = ''.join(_tb.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    _crash_log(f"THREAD CRASH [{args.thread}]:\\n{tb_str}")

sys.excepthook = _global_excepthook
_threading.excepthook = _thread_excepthook

# Torch/Whisper se cargan lazy (en background) para no bloquear la GUI.
# El WinError 1114 se maneja cargándolos en un thread daemon antes de que
# el usuario intente generar subtítulos por primera vez.
def _preload_torch_background():
    """Pre-carga torch+whisper en un thread daemon para evitar demora en startup."""
    try:
        import torch as _torch  # noqa: F401
        try:
            import whisper as _whisper  # noqa: F401
        except Exception:
            pass
    except Exception:
        pass

if os.name == "nt":
    import threading as _preload_threading
    _t = _preload_threading.Thread(target=_preload_torch_background, daemon=True, name="torch-preload")
    _t.start()

# PyQt6 imports
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QTextEdit, QLineEdit, QComboBox, QCheckBox,
    QRadioButton, QButtonGroup, QTabWidget, QScrollArea, QFrame,
    QProgressBar, QMessageBox, QFileDialog, QSpinBox, QGroupBox,
    QSizePolicy, QDialog, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QObject, QEvent
from PyQt6.QtGui import QFont, QPixmap, QIcon, QImage

import threading
import time
from pathlib import Path
from datetime import datetime
import webbrowser
from PIL import Image
import requests
import json


import sys

def global_exception_handler(exctype, value, traceback):
    import traceback as tb
    with open("crash_log.txt", "a") as f:
        f.write("=== FATAL EXCEPTION ===\n")
        f.write("".join(tb.format_exception(exctype, value, traceback)))
    sys.__excepthook__(exctype, value, traceback)

sys.excepthook = global_exception_handler

import threading
def custom_thread_excepthook(args):
    import traceback as tb
    with open("crash_log.txt", "a") as f:
        f.write(f"=== FATAL THREAD EXCEPTION in {args.thread.name} ===\n")
        f.write("".join(tb.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    
threading.excepthook = custom_thread_excepthook

def _load_recraft_style_options():
    """
    Carga el catálogo de estilos de Recraft con fallback seguro.
    En algunas ejecuciones sobre Google Drive/Windows el import puede fallar
    con OSError intermitente (Errno 22).
    """
    try:
        from ai.recraft_style_catalog import RECRAFT_STYLE_OPTIONS as _catalog_options
        return list(_catalog_options)
    except Exception as exc:
        print(
            f"️ No se pudo cargar recraft_style_catalog ({exc}). "
            "Usando estilos de respaldo.",
            file=sys.stderr,
        )
        return [
            "No style",
            "Any style",
            "Recraft V3 Raw",
            "Photorealism",
            "Illustration",
            "Vector art",
            "Icon",
            "Logo",
        ]


RECRAFT_STYLE_OPTIONS = _load_recraft_style_options()

MOJIBAKE_MARKERS = (
    "Ã", "Â", "â", "ðŸ", "", "Ð", "Ñ", "вЂ", "�"
)

# Mapa inverso de caracteres CP1252 "especiales" para recuperar bytes 0x80-0x9F.
_CP1252_CHAR_TO_BYTE = {}
for _b in range(0x80, 0xA0):
    try:
        _ch = bytes([_b]).decode("cp1252")
    except Exception:
        continue
    _CP1252_CHAR_TO_BYTE[_ch] = _b


def _mojibake_score(text):
    if not text:
        return 0
    score = 0
    for marker in MOJIBAKE_MARKERS:
        score += text.count(marker)
    # Controles C1 suelen aparecer en mojibake (ej. \x9d)
    score += sum(1 for ch in text if 0x80 <= ord(ch) <= 0x9F)
    return score


def _decode_utf8_from_mojibake_candidate(text):
    """Intenta reconstruir UTF-8 desde texto mojibake con mezcla latin1/cp1252."""
    if not text:
        return text

    # Estrategia 1: inversion directa latin-1.
    try:
        return text.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
    except Exception:
        pass

    # Estrategia 2: mapear chars CP1252 especiales a bytes 0x80-0x9F y luego latin-1 -> utf-8.
    try:
        rebuilt = []
        for ch in text:
            if ch in _CP1252_CHAR_TO_BYTE:
                rebuilt.append(chr(_CP1252_CHAR_TO_BYTE[ch]))
            else:
                rebuilt.append(ch)
        rebuilt_text = "".join(rebuilt)
        return rebuilt_text.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
    except Exception:
        return text


def fix_mojibake_text(text, max_passes=2):
    """Intenta reparar texto mojibake UTF-8 mal decodificado como latin/cp1252."""
    if not isinstance(text, str) or not text:
        return text

    current = text
    for _ in range(max_passes):
        if _mojibake_score(current) == 0:
            break

        best = current
        best_score = _mojibake_score(current)

        candidates = [
            _decode_utf8_from_mojibake_candidate(current),
        ]

        for candidate in candidates:
            candidate_score = _mojibake_score(candidate)
            if candidate_score < best_score:
                best = candidate
                best_score = candidate_score

        if best == current:
            break
        current = best

    return current


class _MojibakeRepairStream:
    """Corrige mensajes heredados mal decodificados antes de mostrarlos."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return self._stream.write(fix_mojibake_text(text, max_passes=3))

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _install_console_text_repair():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and not isinstance(stream, _MojibakeRepairStream):
            setattr(sys, stream_name, _MojibakeRepairStream(stream))


_install_console_text_repair()


def _repair_text_attr(obj, getter_name, setter_name):
    """Repara un atributo de texto de un objeto Qt si existe."""
    try:
        getter = getattr(obj, getter_name, None)
        setter = getattr(obj, setter_name, None)
        if not callable(getter) or not callable(setter):
            return
        original = getter()
        if not isinstance(original, str):
            return
        fixed = fix_mojibake_text(original)
        if fixed != original:
            setter(fixed)
    except Exception:
        pass


def repair_widget_texts(root_widget):
    """Repara textos mojibake en una jerarquia completa de widgets Qt."""
    if root_widget is None:
        return

    objects = [root_widget]
    try:
        objects.extend(root_widget.findChildren(QObject))
    except Exception:
        pass

    for obj in objects:
        _repair_text_attr(obj, "text", "setText")
        _repair_text_attr(obj, "title", "setTitle")
        _repair_text_attr(obj, "windowTitle", "setWindowTitle")
        _repair_text_attr(obj, "placeholderText", "setPlaceholderText")
        _repair_text_attr(obj, "toolTip", "setToolTip")
        _repair_text_attr(obj, "statusTip", "setStatusTip")
        _repair_text_attr(obj, "whatsThis", "setWhatsThis")

        if hasattr(obj, "count") and hasattr(obj, "itemText") and hasattr(obj, "setItemText"):
            try:
                for i in range(obj.count()):
                    text = obj.itemText(i)
                    fixed = fix_mojibake_text(text)
                    if fixed != text:
                        obj.setItemText(i, fixed)
            except Exception:
                pass

        if isinstance(obj, QTabWidget):
            try:
                for i in range(obj.count()):
                    tab_text = obj.tabText(i)
                    fixed = fix_mojibake_text(tab_text)
                    if fixed != tab_text:
                        obj.setTabText(i, fixed)
            except Exception:
                pass

        if hasattr(obj, "actions"):
            try:
                for action in obj.actions():
                    _repair_text_attr(action, "text", "setText")
                    _repair_text_attr(action, "toolTip", "setToolTip")
                    _repair_text_attr(action, "statusTip", "setStatusTip")
            except Exception:
                pass


class MojibakeRepairEventFilter(QObject):
    """Event filter para reparar textos al mostrarse widgets."""

    def eventFilter(self, obj, event):
        try:
            if event.type() in (
                QEvent.Type.Show,
                QEvent.Type.WindowActivate,
                QEvent.Type.Polish
            ):
                if isinstance(obj, QWidget):
                    repair_widget_texts(obj)
        except Exception:
            pass
        return False

# ========== IMPORTS DEL SISTEMA ==========
# auto_video_integration_v2 eliminado - ahora se usa auto_video_integration_pyqt6.py
AUTO_INTEGRATION_AVAILABLE = False

try:
    from auto_video_generator_v2 import AutoVideoGenerator, VideoConfig
    AUTO_VIDEO_AVAILABLE = True
    print("[OK] Auto Video Generator v2.0 (Contextual) cargado")
except ImportError as e:
    AUTO_VIDEO_AVAILABLE = False
    print(f"[!] Auto Video Generator no disponible: {e}")

try:
    from ai.gemini_ai_client import GeminiAiClient
    GEMINI_AVAILABLE = True
    print("[OK] LLM Client (Groq/Gemini) cargado")
except ImportError as e:
    GEMINI_AVAILABLE = False
    print(f"[!] LLM Client no disponible: {e}")

try:
    from ai.google_search_api import (
        search_google_trends,
        GOOGLE_API_KEY,
        GOOGLE_SEARCH_ENGINE_ID
    )
    GOOGLE_API_AVAILABLE = True
    print("[OK] Google Search APIs cargadas")
except ImportError as e:
    GOOGLE_API_AVAILABLE = False
    print(f"[!] Google Search APIs no disponibles: {e}")

try:
    from channel.trend_spotter import get_trending_topics, analyze_trends_for_video_ideas
    TRENDS_AVAILABLE = True
except ImportError as e:
    TRENDS_AVAILABLE = False
    print("[!] trend_spotter.py no encontrado. La sugerencia de tendencias fallará.")


# ========== WORKER THREADS ==========

# ========== ESTILOS CSS ==========
from thumbnails_mixin import ThumbnailsMixin
from ui_themes import THEMES, generate_stylesheet, load_theme_preference, save_theme_preference

# ========== LAZY TAB WRAPPER ==========
class LazyTabWrapper(QWidget):
    """Wrapper que difiere la creacion del widget real hasta que la pestana se muestra por primera vez.
    Muestra un indicador de carga mientras se crea el widget real."""

    tab_loaded = pyqtSignal(object)  # Emite el widget real al cargarlo

    def __init__(self, tab_name, factory_fn, parent_gui, attr_name=None, parent=None):
        """
        Args:
            tab_name: Nombre legible de la pestana (para el indicador de carga)
            factory_fn: Funcion que crea y retorna el widget real
            parent_gui: Referencia al VideoOptimizerGUI
            attr_name: Nombre del atributo en parent_gui donde guardar el widget (ej: 'auto_video_tab')
        """
        super().__init__(parent)
        self._tab_name = tab_name
        self._factory_fn = factory_fn
        self._parent_gui = parent_gui
        self._attr_name = attr_name
        self._initialized = False
        self._real_widget = None

        # Layout que contendra placeholder o widget real
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Crear placeholder de carga
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(40, 60, 40, 40)

        title = QLabel(f"{tab_name}")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(title)

        msg = QLabel("Cargando módulo...")
        msg.setObjectName("subtitle")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(msg)

        progress = QProgressBar()
        progress.setMaximum(0)  # Indeterminado
        progress.setFixedWidth(300)
        progress_container = QWidget()
        pc_layout = QHBoxLayout(progress_container)
        pc_layout.addStretch()
        pc_layout.addWidget(progress)
        pc_layout.addStretch()
        placeholder_layout.addWidget(progress_container)

        placeholder_layout.addStretch()

        self._placeholder = placeholder
        self._layout.addWidget(placeholder)

    def showEvent(self, event):
        """Se ejecuta al mostrar la pestana - carga lazy del widget real"""
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            # Usar QTimer.singleShot(0) para que el placeholder se pinte primero
            QTimer.singleShot(0, self._do_lazy_load)

    def _do_lazy_load(self):
        """Ejecuta la carga real del widget"""
        try:
            print(f" Carga lazy: {self._tab_name}...")
            self._real_widget = self._factory_fn()

            # Guardar referencia en parent_gui
            if self._attr_name and self._parent_gui:
                setattr(self._parent_gui, self._attr_name, self._real_widget)

            # Reemplazar placeholder con widget real
            self._layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None
            self._layout.addWidget(self._real_widget)

            # Reparar textos mojibake del widget recien cargado
            repair_widget_texts(self._real_widget)

            print(f" Carga lazy completada: {self._tab_name}")
            self.tab_loaded.emit(self._real_widget)

        except Exception as e:
            print(f"️ Error en carga lazy de {self._tab_name}: {e}")
            import traceback
            traceback.print_exc()

            # Mostrar error en lugar del placeholder
            self._layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None

            error_widget = QLabel(f"️ Error cargando {self._tab_name}:\\n\\n{str(e)}")
            error_widget.setWordWrap(True)
            error_widget.setStyleSheet("color: #ff6b6b; padding: 20px;")
            self._layout.addWidget(error_widget)

            # Guardar None como referencia
            if self._attr_name and self._parent_gui:
                setattr(self._parent_gui, self._attr_name, None)


# ========== CLASE PRINCIPAL GUI ==========
class VideoOptimizerGUI(QMainWindow, ThumbnailsMixin):
    """Interfaz gráfica PyQt6 del Video Optimizer Pro"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Optimizer Studio v4.0")
        
        # Obtener tamaño de pantalla disponible y ajustar ventana
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            available_geometry = screen.availableGeometry()
            screen_width = available_geometry.width()
            screen_height = available_geometry.height()
            
            # Tamaño deseado: 1400x900, pero ajustar si la pantalla es más pequeña
            desired_width = min(1400, int(screen_width * 0.9))
            desired_height = min(900, int(screen_height * 0.9))
            
            # Calcular posición centrada
            x = (screen_width - desired_width) // 2 + available_geometry.x()
            y = (screen_height - desired_height) // 2 + available_geometry.y()
            
            self.setGeometry(x, y, desired_width, desired_height)
        else:
            # Fallback si no se puede obtener información de pantalla
            self.setGeometry(100, 100, 1400, 900)
        
        # Establecer tamaño mínimo para que siempre se vean los controles
        self.setMinimumSize(800, 600)
        
        # Cargar ícono de la aplicación
        icon_path = Path("icon.ico")  # Primero intenta .ico
        if not icon_path.exists():
            icon_path = Path("icon.png")  # Si no existe, intenta .png
        
        if icon_path.exists():
            try:
                self.setWindowIcon(QIcon(str(icon_path)))
                print(f" Ícono cargado: {icon_path}")
            except Exception as e:
                print(f"[!] No se pudo cargar el ícono: {e}")
        else:
            print(" No se encontro archivo de icono (icon.ico o icon.png). Usando icono por defecto.")
        
        # Variables del sistema
        self.optimizer = None
        self.current_report = None
        self.is_analyzing = False
        self.ai_factory = AIFactory.get_instance()
        self.gemini_client = self.ai_factory.get_llm_client() if GEMINI_AVAILABLE else None
        # Fal.ai (modulo retirado, atributo requerido por thumbnail_pipeline)
        self.fal_client = None

        # Cliente Recraft
        self.recraft_client = None
        if AUTO_VIDEO_AVAILABLE:
            try:
                from ai.recraft_client import RecraftClient
                self.recraft_client = self.ai_factory.get_client('recraft')
                if self.recraft_client and getattr(self.recraft_client, "api_key", None):
                    print("[OK] Cliente Recraft inicializado")
                elif self.recraft_client:
                    print("[!] Cliente Recraft creado pero no inicializado (verifica RECRAFT_API_KEY)")
            except Exception as e:
                print(f"[!] No se pudo inicializar Recraft: {e}")

        # Auto Video Generator
        self.auto_video_generator = None  # Se inicializa después
        self.auto_video_integration = None
        
        self.last_raw_image_path = None
        self.last_title_used = None
        
        # Almacén para tendencias
        self.trend_ideas_widgets = []
        
        # Workers
        self.current_worker = None
        self._last_project_autoload_done = False
        self._last_project_autoload_path = None
        
        # Sistema de temas
        self.current_theme = load_theme_preference()
        
        # Crear interfaz
        self.setup_ui()
        
        # Inicializar componentes (después de crear UI para que log_text exista)
        self._initialize_components()
        
        # Aplicar estilos con el tema guardado
        self.apply_theme(self.current_theme)

        # Reparar textos con mojibake una vez al iniciar (con delay para que los widgets esten listos)
        QTimer.singleShot(500, lambda: repair_widget_texts(self))
        
        # Mensaje de bienvenida
        self.log("Video Optimizer Studio inicializado")
        self.log("Módulos cargados:")
        self.log(f"  - Auto Video Generator: {'Disponible' if AUTO_VIDEO_AVAILABLE else 'No disponible'}")
        self.log(f"  - Recraft (visuales): {'Disponible' if self.recraft_client else 'No disponible'}")
        self.log(f"  - Groq (texto/análisis): {'Disponible' if self.gemini_client else 'No disponible'}")
        self.log("  - Otros LLMs de texto: Desactivados")
        self.log(f"  - Google Search: {'Disponible' if GOOGLE_API_AVAILABLE else 'No disponible'}")
        self.log(f"  - Trends Spotter: {'Disponible' if TRENDS_AVAILABLE else 'No disponible'}")

        # Intentar cargar el último proyecto abierto automáticamente
        QTimer.singleShot(1000, self.load_last_project)

    @staticmethod
    def _normalize_project_path(project_path):
        """Normaliza rutas para comparar proyectos cargados."""
        if not project_path:
            return None
        try:
            return os.path.normcase(os.path.realpath(str(project_path)))
        except Exception:
            return str(project_path)

    def _load_last_project_once(self, widget=None):
        """Abre el proyecto con el que se estaba trabajando, una sola vez.

        Que abrir (puntero valido / "__NUEVO__" / puntero perdido -> proyecto
        mas reciente) lo decide project_autoload.decide_project_to_load. Aca
        solo se evita cargarlo dos veces y se deja rastro en el log: antes, un
        puntero roto devolvia en silencio y parecia que el proyecto se habia
        perdido (2026-09-04).
        """
        try:
            target_widget = widget or getattr(self, 'auto_video_tab', None)
            if not target_widget or not hasattr(target_widget, 'project_manager'):
                return False

            from infra.project_autoload import decide_project_to_load, list_recent_projects

            puntero = ""
            last_project_file = Path("last_project_path.txt")
            if last_project_file.exists():
                puntero = last_project_file.read_text(encoding='utf-8').strip()

            project_path, motivo = decide_project_to_load(puntero, list_recent_projects())
            if not project_path:
                self.log(f" Sin proyecto para abrir: {motivo}")
                return False

            normalized_path = self._normalize_project_path(project_path)
            current_project_path = self._normalize_project_path(
                getattr(target_widget, 'current_project_path', None)
            )

            if self._last_project_autoload_done and self._last_project_autoload_path == normalized_path:
                return False

            if current_project_path and current_project_path == normalized_path:
                self._last_project_autoload_done = True
                self._last_project_autoload_path = normalized_path
                return False

            self.log(f" Abriendo proyecto ({motivo}): {os.path.basename(os.path.dirname(project_path))}")
            target_widget.project_manager.load_project_from_path(project_path)
            self._last_project_autoload_done = True
            self._last_project_autoload_path = normalized_path
            return True
        except Exception as e:
            print(f"Error cargando último proyecto automáticamente: {e}")
            return False
    
    def load_last_project(self):
        """Intenta cargar el ultimo proyecto abierto.
        Si Auto Video Studio aun no se cargo (lazy), la carga se difiere
        a _on_auto_video_tab_loaded que se ejecuta cuando el usuario abre esa pestana."""
        try:
            # Si el tab aun no se cargo via lazy loading, el proyecto se cargara
            # automaticamente cuando el usuario abra la pestana (ver _on_auto_video_tab_loaded)
            if not (hasattr(self, 'auto_video_tab') and self.auto_video_tab):
                return
            self._load_last_project_once(self.auto_video_tab)
        except Exception as e:
            print(f"Error cargando último proyecto: {e}")


    def closeEvent(self, event):
        """Manejador de cierre de la aplicación"""
        try:
            # Guardar proyecto actual si existe
            if hasattr(self, 'auto_video_tab') and self.auto_video_tab:
                if hasattr(self.auto_video_tab, 'project_manager') and self.auto_video_tab.project_manager:
                    if hasattr(self.auto_video_tab, 'current_project_path') and self.auto_video_tab.current_project_path:
                        self.log(" Guardando proyecto antes de salir...")
                        self.auto_video_tab.project_manager.auto_save_project("al cerrar la aplicación")
                        
                        # Guardar ruta del último proyecto
                        try:
                            with open("last_project_path.txt", "w", encoding="utf-8") as f:
                                f.write(self.auto_video_tab.current_project_path)
                        except Exception as e:
                            print(f"Error guardando last_project_path.txt: {e}")
        except Exception as e:
            print(f"Error en closeEvent: {e}")
        
        event.accept()

    def _initialize_components(self):
        """Inicializa los componentes del sistema"""
        # Inicializar Auto Video Generator si está disponible
        if AUTO_VIDEO_AVAILABLE:
            try:
                # Nota: Necesitarás adaptar AutoVideoGenerator para PyQt6
                # Por ahora lo dejamos como placeholder
                pass
            except Exception as e:
                self.log(f"️ Error inicializando Auto Video Generator: {e}")
    
    def setup_ui(self):
        """Configura la interfaz principal"""
        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout principal
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Contenido principal (Tabs + Log)
        content_splitter = QWidget()
        content_layout = QHBoxLayout(content_splitter)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(14)
        
        # Tabs
        self.tabs = QTabWidget()
        self.create_tabs()
        content_layout.addWidget(self.tabs, stretch=7)
        
        # Panel de log
        log_panel = self.create_log_panel()
        content_layout.addWidget(log_panel, stretch=3)
        
        main_layout.addWidget(content_splitter)
    
    def create_header(self):
        """Crea el header de la aplicación"""
        header = QFrame()
        header.setObjectName("card")
        # Evitar recorte de tipografia en escalados/DPI altos.
        header.setMinimumHeight(118)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 12, 22, 12)
        layout.setSpacing(10)
        
        # Título
        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title = QLabel("Video Optimizer Studio")
        title.setObjectName("title")
        subtitle = QLabel("Flujo de trabajo para análisis, miniaturas y publicación")
        subtitle.setObjectName("subtitle")
        title.setContentsMargins(0, 0, 0, 0)
        subtitle.setContentsMargins(0, 0, 0, 0)
        
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        layout.addLayout(title_layout)
        
        layout.addStretch()
        
        # Botones de Proyecto
        btn_new_project = QPushButton("Nuevo proyecto")
        btn_new_project.setObjectName("success")
        btn_new_project.clicked.connect(self.new_project)
        btn_new_project.setToolTip("Crea un nuevo proyecto (el proyecto actual se guardará automáticamente)")
        
        btn_open_project = QPushButton("Abrir proyecto")
        btn_open_project.setObjectName("accent")
        btn_open_project.clicked.connect(self.open_project)
        btn_open_project.setToolTip("Abre un proyecto existente (el proyecto actual se guardará automáticamente)")
        
        layout.addWidget(btn_new_project)
        layout.addWidget(btn_open_project)
        
        # Botones de footer eliminados (Estado de APIs / Ayuda / Configuracion)
        
        return header
    
    def create_tabs(self):
        """Crea las pestanas principales (con carga lazy para las pesadas)"""
        # Tabs "Analisis" y "Miniaturas" eliminadas: funcionalidad integrada en Auto Video Studio

        # Tab 3: Auto Video Studio (PESADO - carga lazy)
        self.auto_video_tab = None
        if AUTO_VIDEO_AVAILABLE:
            def _create_auto_video_tab():
                from auto_video_integration_pyqt6 import AutoVideoStudioTab
                tab = AutoVideoStudioTab(self)
                print(" Auto Video Studio inicializado (lazy)")
                return tab
            self._auto_video_wrapper = LazyTabWrapper(
                "Auto Video Studio", _create_auto_video_tab,
                self, attr_name='auto_video_tab'
            )
            self._auto_video_wrapper.tab_loaded.connect(self._on_auto_video_tab_loaded)
            self.tabs.addTab(self._auto_video_wrapper, "Auto Video Studio")
        else:
            tab3 = QWidget()
            tab3_layout = QVBoxLayout(tab3)
            tab3_layout.addWidget(QLabel("Auto Video Studio - módulo no disponible"))
            self.tabs.addTab(tab3, "Auto Video Studio")
            self._auto_video_wrapper = None

        # Tab: Catarsis (Short vertical de impacto, sin voz). Carga lazy como Auto Video Studio.
        def _create_catharsis_tab():
            from catharsis_tab import CatharsisTab
            return CatharsisTab(self)
        self._catharsis_wrapper = LazyTabWrapper("Catarsis", _create_catharsis_tab, self, attr_name='catharsis_tab')
        self.tabs.addTab(self._catharsis_wrapper, "Catarsis")

        # Tab 4: Metadata Studio (ligero - carga inmediata)
        try:
            from platform_metadata_tab import PlatformMetadataTab
            self.metadata_tab = PlatformMetadataTab(self)
            self.tabs.addTab(self.metadata_tab, "Metadata")
            print(" Metadata Studio inicializado")
        except Exception as e:
            print(f"️ Error cargando Metadata Studio: {e}")
            import traceback
            traceback.print_exc()
            metadata_error_tab = QWidget()
            metadata_error_layout = QVBoxLayout(metadata_error_tab)
            error_label = QLabel(f"Error cargando Metadata Studio:\\n\\n{str(e)}")
            error_label.setWordWrap(True)
            error_label.setStyleSheet("color: #ff6b6b; padding: 20px;")
            metadata_error_layout.addWidget(error_label)
            self.tabs.addTab(metadata_error_tab, "Metadata")

        # La pestana "Daily Shorts" (daily_shorts_tab.py) se retiro el 2026-09-22:
        # nunca se usaba, se colgaba al cargar ("Loading voices...") y todo lo
        # que hacia lo cubre Auto Video Studio. El pipeline de abajo
        # (daily_short_pipeline.py) sigue: lo usan los microdocumentales y el CLI.

        # Conectar cambio de pestana para reparar mojibake en la pestana actual
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index):
        """Repara textos mojibake al cambiar de pestana"""
        current_widget = self.tabs.widget(index)
        if current_widget:
            QTimer.singleShot(100, lambda w=current_widget: repair_widget_texts(w))

    def _on_auto_video_tab_loaded(self, widget):
        """Callback cuando Auto Video Studio termina de cargarse via lazy loading"""
        # Cargar el ultimo proyecto si aún no se hizo desde el timer inicial.
        self._load_last_project_once(widget)

    # ------------------------------------------------------------------ #
    #  Propiedades proxy: topic_input, category_combo, auto_save_check   #
    #  viven en AutoVideoStudioTab pero otros modulos las buscan en      #
    #  parent_gui (VideoOptimizerGUI).                                   #
    # ------------------------------------------------------------------ #

    @property
    def topic_input(self):
        if self.auto_video_tab and hasattr(self.auto_video_tab, 'topic_input'):
            return self.auto_video_tab.topic_input
        # Fallback: dummy para evitar crash antes de que Studio cargue
        dummy = type('_Dummy', (), {'text': lambda self: '', 'setText': lambda self, t: None,
                                     'clear': lambda self: None, 'setPlaceholderText': lambda self, t: None})()
        return dummy

    @property
    def category_combo(self):
        if self.auto_video_tab and hasattr(self.auto_video_tab, 'category_combo'):
            return self.auto_video_tab.category_combo
        dummy = type('_Dummy', (), {'currentText': lambda self: 'Historia militar/guerras',
                                     'findText': lambda self, t: -1,
                                     'setCurrentIndex': lambda self, i: None})()
        return dummy

    def get_selected_research_context(self):
        """Proxy: retorna snippets de investigacion (lista vacia si no hay)."""
        if self.auto_video_tab and hasattr(self.auto_video_tab, 'selected_research_snippets'):
            return self.auto_video_tab.selected_research_snippets or []
        return []

    @property
    def auto_save_check(self):
        if self.auto_video_tab and hasattr(self.auto_video_tab, 'auto_save_check'):
            return self.auto_video_tab.auto_save_check
        dummy = type('_Dummy', (), {
            'isChecked': lambda self: False,
            'setChecked': lambda self, v: None,
            'setEnabled': lambda self, v: None,
            'setToolTip': lambda self, t: None,
        })()
        return dummy

    def create_log_panel(self):
        """Crea el panel de log"""
        panel = QFrame()
        panel.setObjectName("card")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        
        # Header
        header = QLabel("Actividad")
        header.setObjectName("panelTitle")
        layout.addWidget(header)
        
        # Log text
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("logView")
        layout.addWidget(self.log_text)
        
        # Botón de limpiar
        btn_clear = QPushButton("Limpiar")
        btn_clear.clicked.connect(lambda: self.log_text.clear())
        layout.addWidget(btn_clear)
        
        return panel
    
    # ========== MÉTODOS DE ANÁLISIS ==========
    
    
    
    
    # ========== MÉTODOS DE INVESTIGACIÓN ==========
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    # ========== MÉTODOS DE THUMBNAILS ==========
    
    


    def _execute_fal_generation_thread(self, topic, category, style, fallback_providers=[]):
        """Hilo para generar thumbnail con Fal.ai FLUX.1 schnell (con fallbacks automáticos)"""
        from PyQt6.QtCore import QThread, pyqtSignal
        import time

        class FalWorker(QThread):
            status_update = pyqtSignal(str)
            log_message = pyqtSignal(str)
            trigger_fallback = pyqtSignal(list, str, str, str)

            def __init__(self, parent, topic, category, style, fallback_list):
                super().__init__()
                self.parent = parent
                self.topic = topic
                self.category = category
                self.style = style
                self.fallback_list = fallback_list
                self.error = None
                self.final_path = None

            def run(self):
                try:
                    # Paso 1: Generar prompt con Claude (a través de gemini_client)
                    self.status_update.emit(" Groq creando prompt visual...")
                    prompt = self.parent.gemini_client.generate_thumbnail_prompt(
                        self.topic, self.category, self.style, provider='fal'
                    )
                    self.log_message.emit(f"    Prompt: {prompt[:60]}...")

                    self.status_update.emit(f" Enviando a Fal.ai FLUX.1 schnell...\\nPrompt: {prompt[:80]}...")
                    self.log_message.emit(f"    Generación rápida (schnell - ~2-5 segundos)...")

                    # Paso 2: Llamar a Fal.ai
                    # Usar dimensiones 16:9 estándar para thumbnails de YouTube
                    image_url = self.parent.fal_client.generate_image(
                        prompt=prompt, width=1344, height=768, style=self.style
                    )
                    
                    self.log_message.emit(f"    Respuesta de Fal.ai recibida")

                    if not image_url:
                        raise Exception("Fal.ai no devolvió una imagen")

                    print(f" Imagen Fal.ai generada: {image_url}")

                    # Paso 3: Descargar
                    self.status_update.emit("⬇️ Descargando imagen...")
                    try:
                        response = requests.get(image_url, timeout=30)
                        response.raise_for_status()
                    except requests.exceptions.Timeout:
                        raise Exception("Timeout descargando imagen de Fal.ai")
                    except requests.exceptions.ConnectionError:
                        raise Exception("Error de conexión descargando imagen de Fal.ai")

                    # Paso 4: Guardar RAW
                    thumb_dir = Path("thumbnails_fal")
                    thumb_dir.mkdir(exist_ok=True)
                    safe_topic = "".join(c for c in self.topic[:30] if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')

                    raw_path = thumb_dir / f"thumb_fal_{safe_topic}_{int(time.time())}_raw.jpg"

                    with open(raw_path, "wb") as f:
                        f.write(response.content)

                    self.parent.last_raw_image_path = str(raw_path)
                    self.parent.last_title_used = self.topic
                    self.log_message.emit(f" Thumbnail Fal.ai FLUX.1 schnell guardado: {raw_path}")

                    # Paso 5: Aplicar texto si está activado
                    final_path = raw_path
                    if self.parent.add_text_overlay_check.isChecked():
                        self.status_update.emit("️ Añadiendo texto...")
                        final_path_str = str(thumb_dir / f"thumb_fal_{safe_topic}_{int(time.time())}_final.jpg")
                        text_style = self.parent.text_style_combo.currentText()
                        language = self.parent.text_lang_combo.currentText()

                        if self.parent._add_text_to_image(str(raw_path), final_path_str, self.topic, text_style, language):
                            final_path = Path(final_path_str)
                            self.log_message.emit(f" Texto aplicado con estilo: {text_style} ({language})")

                    self.final_path = str(final_path)

                except Exception as e:
                    self.error = str(e)
                    import traceback
                    error_details = traceback.format_exc()
                    self.log_message.emit(f" Error en Fal.ai: {str(e)}")
                    self.log_message.emit(f"   Detalles: {error_details[:200]}...")
                    
                    # Si hay fallbacks disponibles, intentar con el siguiente
                    if self.fallback_list and not self.final_path:
                        next_provider = self.fallback_list[0]
                        remaining_fallbacks = self.fallback_list[1:]
                        self.log_message.emit(f"️ Fal.ai falló, activando fallback a {next_provider}...")
                        self.trigger_fallback.emit(remaining_fallbacks, self.topic, self.category, self.style)
                    else:
                        self.log_message.emit(f" Fal.ai falló y no hay más fallbacks disponibles")

        worker = FalWorker(self, topic, category, style, fallback_providers)
        worker.status_update.connect(self.thumb_preview.setText)
        worker.log_message.connect(self.log)
        worker.trigger_fallback.connect(self._trigger_next_fallback)
        worker.finished.connect(lambda: self._on_thumbnail_generated(worker, 'fal', len(fallback_providers) > 0))
        worker.start()

        self.current_thumbnail_worker = worker


    def _execute_recraft_generation_thread(self, topic, category, style, fallback_providers=[]):
        """Hilo para generar thumbnail con Recraft AI."""
        from PyQt6.QtCore import QThread, pyqtSignal
        import time

        class RecraftWorker(QThread):
            status_update = pyqtSignal(str)
            log_message = pyqtSignal(str)
            trigger_fallback = pyqtSignal(list, str, str, str)  # fallback_list, topic, category, style

            def __init__(self, parent, topic, category, style, fallback_list):
                super().__init__()
                self.parent = parent
                self.topic = topic
                self.category = category
                self.style = style
                self.fallback_list = fallback_list
                self.error = None
                self.final_path = None

            def run(self):
                try:
                    # Paso 1: Generar prompt con Gemini
                    self.status_update.emit(" Groq creando prompt visual...")
                    prompt = self.parent.gemini_client.generate_thumbnail_prompt(
                        self.topic, self.category, self.style, provider='recraft'
                    )
                    self.log_message.emit(f"    Prompt: {prompt[:60]}...")

                    self.status_update.emit(f" Enviando a Recraft AI...\\nPrompt: {prompt[:80]}...")

                    # Paso 2: Llamar a Recraft (vía cliente compat Fal/Leonardo)
                    recraft_client = self.parent.recraft_client

                    if not recraft_client:
                        raise Exception("Recraft API no está configurada")

                    image_url = recraft_client.generate_image(
                        prompt=prompt,
                        width=1344,
                        height=768,
                        style=self.style,
                    )
                    
                    self.log_message.emit("    Respuesta de Recraft recibida")

                    if not image_url:
                        raise Exception("Recraft AI no devolvió una imagen")

                    print(f" Imagen Recraft generada: {image_url}")

                    # Paso 3: Descargar
                    self.status_update.emit("⬇️ Descargando imagen...")
                    try:
                        response = requests.get(image_url, timeout=30)
                        response.raise_for_status()
                    except requests.exceptions.Timeout:
                        raise Exception("Timeout descargando imagen de Recraft AI")
                    except requests.exceptions.ConnectionError:
                        raise Exception("Error de conexión descargando imagen de Recraft AI")

                    # Paso 4: Guardar RAW
                    thumb_dir = Path("thumbnails_recraft")
                    thumb_dir.mkdir(exist_ok=True)
                    safe_topic = "".join(c for c in self.topic[:30] if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')

                    content_head = response.content[:4096].lower()
                    is_svg = b"<svg" in content_head
                    raw_ext = "svg" if is_svg else "png"
                    raw_path = thumb_dir / f"thumb_recraft_{safe_topic}_{int(time.time())}_raw.{raw_ext}"

                    with open(raw_path, "wb") as f:
                        f.write(response.content)

                    self.parent.last_raw_image_path = str(raw_path)
                    self.parent.last_title_used = self.topic
                    self.log_message.emit(f" Thumbnail Recraft guardado: {raw_path}")
                    if is_svg:
                        self.log_message.emit("    Recraft devolvió SVG; se rasterizará automáticamente al aplicar texto")

                    # Paso 5: Aplicar texto si está activado
                    final_path = raw_path
                    if self.parent.add_text_overlay_check.isChecked():
                        self.status_update.emit("️ Añadiendo texto...")
                        final_path_str = str(thumb_dir / f"thumb_recraft_{safe_topic}_{int(time.time())}_final.png")
                        style = self.parent.text_style_combo.currentText()
                        language = self.parent.text_lang_combo.currentText()

                        if self.parent._add_text_to_image(str(raw_path), final_path_str, self.topic, style, language):
                            final_path = Path(final_path_str)
                            self.log_message.emit(f" Texto aplicado con estilo: {style} ({language})")

                    self.final_path = str(final_path)

                except Exception as e:
                    self.error = str(e)
                    # Si hay fallbacks disponibles, intentar con el siguiente
                    if self.fallback_list and not self.final_path:
                        next_provider = self.fallback_list[0]
                        remaining_fallbacks = self.fallback_list[1:]
                        self.log_message.emit(f"️ Recraft AI falló, activando fallback a {next_provider}...")
                        self.trigger_fallback.emit(remaining_fallbacks, self.topic, self.category, self.style)
                    else:
                        self.log_message.emit(f" Recraft AI falló y no hay más fallbacks disponibles")

        worker = RecraftWorker(self, topic, category, style, fallback_providers)
        worker.status_update.connect(self.thumb_preview.setText)
        worker.log_message.connect(self.log)
        worker.trigger_fallback.connect(self._trigger_next_fallback)
        worker.finished.connect(lambda: self._on_thumbnail_generated(worker, 'recraft', len(fallback_providers) > 0))
        worker.start()

        # Guardar referencia al worker
        self.current_thumbnail_worker = worker


    def _trigger_next_fallback(self, remaining_fallbacks, topic, category, style):
        """Activa el siguiente proveedor en la lista de fallbacks"""
        if not remaining_fallbacks:
            return
        
        next_provider = remaining_fallbacks[0]
        remaining = remaining_fallbacks[1:]
        
        if next_provider == 'recraft':
            self.log("    Fallback a Recraft AI")
            self._execute_recraft_generation_thread(topic, category, style, remaining)
        elif next_provider == 'fal':
            self.log("    Fallback a Fal.ai")
            self._execute_fal_generation_thread(topic, category, style, remaining)

        # Si hay error pero hay fallback, el fallback ya fue activado en el worker
    
    


    def _looks_like_svg(self, image_path):
        """Detecta si un archivo parece SVG aunque tenga extensión incorrecta."""
        try:
            with open(image_path, "rb") as f:
                head = f.read(4096)
        except Exception:
            return False

        # Descartar formatos binarios por magic bytes antes de buscar texto SVG.
        # Evita falsos positivos cuando metadatos XMP/EXIF contienen "<svg".
        if head[:4] == b'\x89PNG':
            return False
        if head[:2] in (b'\xff\xd8', b'\xff\xe0', b'\xff\xe1'):  # JPEG / JFIF / EXIF
            return False
        if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
            return False
        if head[:4] in (b'GIF8', b'GIF9'):
            return False
        if head[:2] == b'BM':  # BMP
            return False

        # Solo si no es un formato binario conocido, buscar marcadores SVG
        text = head.lower()
        return b"<svg" in text or b"<?xml" in text

    def _rasterize_svg_to_png_temp(self, svg_path):
        """Convierte SVG a PNG temporal para poder procesarlo con Pillow."""
        import tempfile

        temp_png = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="thumb_svg_", delete=False
        )
        temp_png_path = temp_png.name
        temp_png.close()

        # Intento 1: cairosvg (si está instalado)
        try:
            import cairosvg

            cairosvg.svg2png(url=svg_path, write_to=temp_png_path)
            return temp_png_path
        except Exception:
            pass

        # Intento 2: QSvgRenderer de PyQt6
        try:
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QImage, QPainter
            from PyQt6.QtSvg import QSvgRenderer

            renderer = QSvgRenderer(svg_path)
            if not renderer.isValid():
                with open(svg_path, "rb") as f:
                    renderer = QSvgRenderer(f.read())
            if not renderer.isValid():
                raise Exception("QSvgRenderer no pudo leer el SVG")

            size = renderer.defaultSize()
            width = size.width() if size.width() > 0 else 1920
            height = size.height() if size.height() > 0 else 1080

            image = QImage(width, height, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)

            painter = QPainter(image)
            renderer.render(painter)
            painter.end()

            if not image.save(temp_png_path, "PNG"):
                raise Exception("No se pudo guardar PNG temporal desde SVG")
            return temp_png_path
        except Exception as e:
            try:
                os.remove(temp_png_path)
            except Exception:
                pass
            raise Exception(
                "El thumbnail generado es SVG y no se pudo convertir a PNG. "
                f"Detalle: {e}"
            )

    def _add_text_to_image(self, input_path, output_path, text, style_name="Contraste alto", language="Español"):
        """Renderiza texto sobre la imagen con efectos de thumbnail cinematográfico."""
        temp_raster_path = None
        try:
            from PIL import ImageDraw, ImageFont, ImageFilter

            # Traducir si es necesario
            display_text = text
            if language == "English" and self.gemini_client:
                try:
                    translated = self.gemini_client._generate(
                        f"Translate this video title from Spanish to English. Output ONLY the translation: '{text}'"
                    ).strip()
                    if translated and not translated.startswith("ERROR"):
                        display_text = translated
                        print(f" Texto traducido: {text} → {display_text}")
                except Exception as e:
                    print(f"️ Error traduciendo: {e}")

            print(f" Aplicando estilo '{style_name}' a: {display_text}")

            if self._looks_like_svg(input_path):
                print(f" Archivo SVG detectado (aunque extensión sea distinta): {input_path}")
                temp_raster_path = self._rasterize_svg_to_png_temp(input_path)
                input_path = temp_raster_path

            img = Image.open(input_path).convert("RGBA")
            W, H = img.size

            # ── ESTILOS ──────────────────────────────────────────────────────────
            # Filosofía: minimalismo. Sin glow. Sin stroke grueso.
            # Solo sombra difuminada para separar el texto del fondo,
            # y opcionalmente una placa semitransparente para legibilidad máxima.
            # ─────────────────────────────────────────────────────────────────────
            # fonts      fuentes a intentar en orden (preferir clean sobre condensed)
            # fill       color principal RGBA
            # stroke_px  0 = sin borde (minimalista), >0 = borde fino
            # stroke_col color del borde si stroke_px > 0
            # shadow_col color de sombra difuminada
            # shadow_off (dx, dy)
            # shadow_r   blur radius sombra
            # plate      True = placa semitransparente detrás del texto
            # plate_col  color RGBA de la placa
            # plate_pad  padding interno de la placa en px
            # ─────────────────────────────────────────────────────────────────────
            FONT_STACK = ["segoeuib.ttf", "calibrib.ttf", "ariblk.ttf", "arialbd.ttf"]

            STYLES = {
                # Blanco puro con sombra: el look más profesional/minimalista
                "Contraste alto": dict(
                    fonts=FONT_STACK,
                    fill=(255, 255, 255, 255),
                    stroke_px=0, stroke_col=(0, 0, 0, 0),
                    shadow_col=(0, 0, 0, 220), shadow_off=(4, 5), shadow_r=14,
                    plate=False,
                ),
                # Blanco sobre placa oscura translúcida — máxima legibilidad
                "Claro limpio": dict(
                    fonts=FONT_STACK,
                    fill=(255, 255, 255, 255),
                    stroke_px=0, stroke_col=(0, 0, 0, 0),
                    shadow_col=(0, 0, 0, 160), shadow_off=(2, 3), shadow_r=8,
                    plate=True, plate_col=(0, 0, 0, 145), plate_pad=22,
                ),
                # Amarillo brillante con borde negro fino — clásico YouTube sin exagerar
                "Neon suave": dict(
                    fonts=FONT_STACK,
                    fill=(255, 230, 18, 255),
                    stroke_px=2, stroke_col=(0, 0, 0, 255),
                    shadow_col=(0, 0, 0, 210), shadow_off=(4, 5), shadow_r=12,
                    plate=False,
                ),
                # Blanco sobre placa roja — urgencia/alerta, estilo noticia
                "Rojo intenso": dict(
                    fonts=FONT_STACK,
                    fill=(255, 255, 255, 255),
                    stroke_px=0, stroke_col=(0, 0, 0, 0),
                    shadow_col=(100, 0, 0, 200), shadow_off=(3, 4), shadow_r=10,
                    plate=True, plate_col=(190, 15, 15, 190), plate_pad=22,
                ),
            }

            st = STYLES.get(style_name, STYLES["Contraste alto"])

            # ── FUENTE ───────────────────────────────────────────────────────────
            font_size = int(H * 0.16)
            font = None
            for fname in st["fonts"]:
                try:
                    font = ImageFont.truetype(fname, font_size)
                    break
                except Exception:
                    continue
            if font is None:
                font = ImageFont.load_default()

            # ── TEXTO Y AJUSTE DE TAMAÑO ─────────────────────────────────────────
            final_text = display_text.upper()
            words = final_text.split()
            if len(words) > 4:
                mid = len(words) // 2
                final_text = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])

            max_w = int(W * 0.90)
            for _ in range(30):
                probe = Image.new("RGBA", (1, 1))
                pd = ImageDraw.Draw(probe)
                bb = pd.textbbox((0, 0), final_text, font=font, align="center")
                if (bb[2] - bb[0]) <= max_w:
                    break
                font_size = int(font_size * 0.92)
                for fname in st["fonts"]:
                    try:
                        font = ImageFont.truetype(fname, font_size)
                        break
                    except Exception:
                        continue

            # Medidas finales
            probe = Image.new("RGBA", (1, 1))
            pd = ImageDraw.Draw(probe)
            bb = pd.textbbox((0, 0), final_text, font=font, align="center")
            tw, th = bb[2] - bb[0], bb[3] - bb[1]

            # Posición: centrado horizontal, tercio inferior de la imagen
            x = (W - tw) // 2
            y = int(H * 0.60)

            # ── CAPAS DE EFECTO ──────────────────────────────────────────────────

            def _blank():
                return Image.new("RGBA", img.size, (0, 0, 0, 0))

            # 1. Sombra difuminada
            shadow_layer = _blank()
            shd = ImageDraw.Draw(shadow_layer)
            sr, sg, sb, sa = st["shadow_col"]
            sox, soy = st["shadow_off"]
            shd.text((x + sox, y + soy), final_text, font=font,
                     fill=(sr, sg, sb, sa), align="center")
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(st["shadow_r"]))

            # 2. Placa semitransparente (opcional)
            plate_layer = _blank()
            if st.get("plate"):
                pad = st["plate_pad"]
                pr, pg, pb, pa = st["plate_col"]
                pld = ImageDraw.Draw(plate_layer)
                pld.rounded_rectangle(
                    [x - pad, y - pad, x + tw + pad, y + th + pad],
                    radius=int(pad * 0.6),
                    fill=(pr, pg, pb, pa),
                )

            # 3. Texto con stroke nativo de Pillow
            text_layer = _blank()
            td = ImageDraw.Draw(text_layer)
            cr, cg, cb, ca = st["stroke_col"]
            fr, fg, fb, fa = st["fill"]
            td.text(
                (x, y), final_text, font=font,
                fill=(fr, fg, fb, fa),
                stroke_width=st["stroke_px"],
                stroke_fill=(cr, cg, cb, ca),
                align="center",
            )

            # ── COMPOSICIÓN FINAL ────────────────────────────────────────────────
            result = img.copy()
            for layer in (shadow_layer, plate_layer, text_layer):
                result = Image.alpha_composite(result, layer)

            result.convert("RGB").save(output_path, quality=96)
            return True

        except Exception as e:
            print(f" Error aplicando texto: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if temp_raster_path and os.path.exists(temp_raster_path):
                try:
                    os.remove(temp_raster_path)
                except Exception:
                    pass

    
    
    
    
    
    # ========== MÉTODOS DE AYUDA ==========
    
    def show_api_status(self):
        """Muestra el diálogo con el estado de todas las APIs"""
        try:
            from api_status_dialog import APIStatusDialog
            dialog = APIStatusDialog(self)
            dialog.exec()
        except ImportError as e:
            QMessageBox.warning(self, "Error", f"Módulo api_status_dialog no disponible: {e}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Error al mostrar estado de APIs: {e}")
    
    
    def apply_theme(self, theme_key):
        """Aplica un tema a la interfaz"""
        stylesheet = generate_stylesheet(theme_key)
        self.setStyleSheet(stylesheet)
        self.current_theme = theme_key
        save_theme_preference(theme_key)
    
    
    
    
    def _sync_auto_save_state(self):
        """Sincroniza el estado del checkbox con el Auto Video Studio Tab"""
        if getattr(self, 'auto_video_tab', None):
            self.auto_save_check.setChecked(self.auto_video_tab.auto_save_enabled)
        elif hasattr(self, 'auto_save_check'):
            self.auto_save_check.setEnabled(False)
    
    def _on_auto_save_changed(self, state):
        """Maneja el cambio del checkbox de auto-guardado"""
        if getattr(self, 'auto_video_tab', None):
            self.auto_video_tab.auto_save_enabled = (state == Qt.CheckState.Checked.value)
            # También sincronizar el checkbox del Auto Video Studio Tab si existe
            if hasattr(self.auto_video_tab, 'auto_save_check'):
                self.auto_video_tab.auto_save_check.setChecked(state == Qt.CheckState.Checked.value)
        elif hasattr(self, 'auto_save_check'):
            self.auto_save_check.setChecked(False)
            QMessageBox.warning(
                self,
                "Auto Video Studio no disponible",
                "El módulo Auto Video Studio no está disponible.\\n"
                "El auto-guardado solo está disponible en Auto Video Studio."
            )
    
    
    def new_project(self):
        """Crea un nuevo proyecto, guardando el actual primero si existe"""
        try:
            # Verificar si hay un proyecto actual con datos
            if self.auto_video_tab:
                # Guardar el proyecto actual si tiene datos
                if hasattr(self.auto_video_tab, 'project_manager'):
                    # Auto-guardar el proyecto actual
                    if hasattr(self.auto_video_tab, 'project_manager'):
                        self.auto_video_tab.project_manager.auto_save_project("antes de crear nuevo proyecto")
                        self.log(" Proyecto actual guardado automáticamente")
                
                # Limpiar el estado del proyecto actual
                self._reset_project_state()
                
                # Confirmar creación de nuevo proyecto
                reply = QMessageBox.question(
                    self,
                    "Nuevo Proyecto",
                    "¿Deseas crear un nuevo proyecto?\\n\\n"
                    "El proyecto anterior ha sido guardado automáticamente.\\n"
                    "Todos los campos se limpiarán para comenzar desde cero.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Resetear todos los campos a valores por defecto
                    if hasattr(self.auto_video_tab, 'reset_to_defaults'):
                        self.auto_video_tab.reset_to_defaults()
                    else:
                        # Fallback: limpiar campos básicos si el método no existe
                        if hasattr(self.auto_video_tab, 'current_project_path'):
                            self.auto_video_tab.current_project_path = None
                        if hasattr(self.auto_video_tab, 'last_storyboard_data'):
                            self.auto_video_tab.last_storyboard_data = None
                        if hasattr(self.auto_video_tab, 'last_generated_video_data'):
                            self.auto_video_tab.last_generated_video_data = None
                        if hasattr(self, 'topic_input'):
                            self.topic_input.clear()
                        if hasattr(self, 'category_combo'):
                            self.category_combo.setCurrentIndex(0)
                        if hasattr(self.auto_video_tab, 'log_text'):
                            self.auto_video_tab.log_text.clear()
                    
                    self.log(" Nuevo proyecto creado. Listo para comenzar.")
                    QMessageBox.information(
                        self,
                        "Nuevo Proyecto",
                        " Nuevo proyecto creado.\\n\\n"
                        "Todos los campos han sido reseteados a sus valores por defecto.\\n"
                        "Puedes comenzar a trabajar en tu nuevo proyecto."
                    )
            else:
                QMessageBox.warning(
                    self,
                    "Auto Video Studio no disponible",
                    "El módulo Auto Video Studio no está disponible.\\n"
                    "Los proyectos solo se pueden crear desde Auto Video Studio."
                )
        except Exception as e:
            error_msg = f"Error al crear nuevo proyecto: {e}"
            self.log(f" {error_msg}")
            QMessageBox.critical(self, "Error", error_msg)
            import traceback
            traceback.print_exc()
    
    def open_project(self):
        """Abre un proyecto existente, guardando el actual primero si existe"""
        try:
            if self.auto_video_tab:
                # Guardar el proyecto actual si tiene datos
                if (hasattr(self.auto_video_tab, 'current_project_path') and 
                    self.auto_video_tab.current_project_path):
                    # Auto-guardar el proyecto actual
                    if hasattr(self.auto_video_tab, 'project_manager'):
                        self.auto_video_tab.project_manager.auto_save_project("antes de abrir otro proyecto")
                        self.log(" Proyecto actual guardado automáticamente")
                
                # Usar el método de carga del Auto Video Studio Tab
                if hasattr(self.auto_video_tab, 'project_manager'):
                    self.auto_video_tab.project_manager.load_project()
                else:
                    QMessageBox.warning(
                        self,
                        "Error",
                        "No se pudo acceder al gestor de proyectos."
                    )
            else:
                QMessageBox.warning(
                    self,
                    "Auto Video Studio no disponible",
                    "El módulo Auto Video Studio no está disponible.\\n"
                    "Los proyectos solo se pueden abrir desde Auto Video Studio."
                )
        except Exception as e:
            error_msg = f"Error al abrir proyecto: {e}"
            self.log(f" {error_msg}")
            QMessageBox.critical(self, "Error", error_msg)
            import traceback
            traceback.print_exc()
    
    def _reset_project_state(self):
        """Resetea el estado del proyecto actual"""
        try:
            if self.auto_video_tab:
                # Deshabilitar auto-guardado temporalmente para evitar guardar durante el reset
                original_auto_save = getattr(self.auto_video_tab, 'auto_save_enabled', False)
                self.auto_video_tab.auto_save_enabled = False
                
                # Limpiar referencias al proyecto
                if hasattr(self.auto_video_tab, 'current_project_path'):
                    self.auto_video_tab.current_project_path = None
                
                # Restaurar auto-guardado
                self.auto_video_tab.auto_save_enabled = original_auto_save
        except Exception as e:
            print(f"️ Error reseteando estado del proyecto: {e}")
    
    def log(self, message):
        """Registra un mensaje en el log"""
        message = fix_mojibake_text(str(message))
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        
        self.log_text.append(log_message)
        
        # Scroll al final
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # También imprimir en consola
        print(message)
    
    def closeEvent(self, event):
        """Maneja el cierre de la aplicación principal - guarda proyectos antes de cerrar"""
        try:
            print("\\n[VideoOptimizerGUI] Cerrando aplicación, guardando proyectos...")
            
            # Guardar proyecto del Auto Video Studio si hay uno cargado
            if hasattr(self, 'auto_video_tab') and self.auto_video_tab:
                if hasattr(self.auto_video_tab, 'project_manager'):
                    try:
                        print("[VideoOptimizerGUI] Guardando proyecto del Auto Video Studio...")
                        if hasattr(self.auto_video_tab, 'project_manager'):
                            # Forzar guardado inmediato antes de cerrar
                            self.auto_video_tab.project_manager.auto_save_project("antes de cerrar aplicación")
                            print("[VideoOptimizerGUI]  Proyecto guardado correctamente")
                    except Exception as save_error:
                        print(f"[VideoOptimizerGUI] ️ Error guardando proyecto: {save_error}")
                        import traceback
                        traceback.print_exc()
            
            # Cerrar Timeline Editor si está abierto y guardar sus cambios
            if hasattr(self, 'auto_video_tab') and self.auto_video_tab:
                if hasattr(self.auto_video_tab, 'timeline_editor_window') and self.auto_video_tab.timeline_editor_window:
                    try:
                        # Cerrar el Timeline Editor (su closeEvent guardará automáticamente)
                        if self.auto_video_tab.timeline_editor_window.isVisible():
                            self.auto_video_tab.timeline_editor_window.close()
                    except Exception as timeline_error:
                        print(f"[VideoOptimizerGUI] ️ Error cerrando Timeline Editor: {timeline_error}")
            
            print("[VideoOptimizerGUI]  Cierre de aplicación completado")
        except Exception as e:
            print(f"[VideoOptimizerGUI] ️ Error en closeEvent: {e}")
            import traceback
            traceback.print_exc()
        finally:
            event.accept()


# ========== FUNCIÓN PRINCIPAL ==========
def main():
    """Función principal"""
    try:
        import sys
        import traceback
        
        print("=" * 60)
        print("[>>] Iniciando Video Optimizer Pro...")
        print("=" * 60)
        
        # Crear aplicación QApplication PRIMERO
        print("\n[..] Creando aplicacion QApplication...")
        app = QApplication(sys.argv)

        # Instalar reparador global de textos mojibake para toda la UI.
        app_mojibake_filter = MojibakeRepairEventFilter(app)
        app.installEventFilter(app_mojibake_filter)
        app._mojibake_filter_ref = app_mojibake_filter

        # Conectar el manager de Vast.ai a aboutToQuit (más fiable que atexit en PyQt).
        # Si VAST_AUTO_STOP_ON_EXIT=1, la instancia se detendrá al cerrar la app.
        try:
            from infra.vast_ai_instance_manager import get_default_vast_manager
            _vast_manager = get_default_vast_manager()
            _vast_manager.attach_to_qt_app(app)
            print(f"[..] Vast.ai manager conectado (enabled={_vast_manager.enabled})")
        except Exception as _vast_exc:
            print(f"[!] No se pudo conectar Vast.ai manager: {_vast_exc}")
        
        # Configurar fuente por defecto
        print("[..] Configurando fuente...")
        font = QFont("Segoe UI", 10)
        app.setFont(font)
        
        print("[..] Creando ventana principal...")
        try:
            window = VideoOptimizerGUI()
            repair_widget_texts(window)
            print("[OK] Ventana creada exitosamente")
        except Exception as e:
            print(f"[X] ERROR al crear ventana: {e}")
            import traceback
            traceback.print_exc()
            raise
        
        print("[..] Mostrando ventana...")
        try:
            # Asegurar que la ventana sea visible y esté al frente
            window.show()
            window.raise_()  # Traer al frente
            window.activateWindow()  # Activar la ventana
            
            # Asegurar que la ventana esté completamente visible en la pantalla
            screen = app.primaryScreen()
            if screen:
                available = screen.availableGeometry()  # Área sin barra de tareas
                window_rect = window.frameGeometry()
                
                # Ajustar posición si la ventana se sale de la pantalla
                new_x = window_rect.x()
                new_y = window_rect.y()
                
                # Verificar bordes
                if window_rect.right() > available.right():
                    new_x = available.right() - window_rect.width()
                if window_rect.bottom() > available.bottom():
                    new_y = available.bottom() - window_rect.height()
                if new_x < available.x():
                    new_x = available.x()
                if new_y < available.y():
                    new_y = available.y()
                
                # Si la ventana es más grande que la pantalla, ajustar tamaño
                if window_rect.width() > available.width():
                    window.resize(available.width(), window.height())
                if window_rect.height() > available.height():
                    window.resize(window.width(), available.height())
                
                # Mover a la posición corregida
                window.move(new_x, new_y)
            
            print("[OK] Ventana mostrada y ajustada a pantalla")
        except Exception as e:
            print(f"[X] ERROR al mostrar ventana: {e}")
            import traceback
            traceback.print_exc()
            raise
        
        print("[..] Iniciando event loop de PyQt6...")
        print("=" * 60)
        print("[OK] Aplicacion iniciada correctamente. La ventana deberia estar visible ahora.")
        print("=" * 60)
        
        # Ejecutar el event loop
        exit_code = app.exec()
        print(f"\n[OK] Event loop terminado con codigo: {exit_code}")

        if exit_code != 0:
            _crash_log(f"APP EXIT con código {exit_code} (posible crash silencioso)")

        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n[!] Interrumpido por el usuario (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"\n[X] ERROR FATAL durante inicializacion:")
        print(f"   Tipo: {type(e).__name__}")
        print(f"   Mensaje: {str(e)}")
        print("\nTraceback completo:")
        import traceback
        traceback.print_exc()
        
        # Mostrar mensaje de error en ventana si es posible
        try:
            # Intentar crear una QApplication mínima para mostrar el error
            if 'app' not in locals():
                error_app = QApplication(sys.argv)
            else:
                error_app = app
            
            from PyQt6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Error Fatal - Video Optimizer Pro")
            msg.setText(f"Error durante inicialización:\\n\\n{type(e).__name__}: {str(e)}")
            msg.setDetailedText(traceback.format_exc())
            msg.exec()
        except Exception as msg_error:
            print(f"[!] No se pudo mostrar diálogo de error: {msg_error}")

        input("\\nPresiona Enter para salir...")
        sys.exit(1)


if __name__ == "__main__":
    main()


