# auto_video_integration_pyqt6.py
"""
IntegraciÃ³n PyQt6 del Auto Video Generator con interfaz completa
de pipeline local: Storyboard, ImÃ¡genes y Ensamblaje.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QSlider, QCheckBox, QRadioButton,
    QButtonGroup, QGroupBox, QScrollArea, QProgressBar,
    QMessageBox, QFileDialog, QSpinBox, QDialog,
    QApplication, QDoubleSpinBox, QFrame, QLineEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt6.QtGui import QPixmap

import json
import os
import traceback
import time
from pathlib import Path

from auto_video_generator_pyqt6_adapter import AutoVideoGeneratorPyQt6, VideoGenerationWorker
from cost_calculator import CostCalculator

# La subida/publicación directa a YouTube fue removida de la GUI.

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("âš ï¸ pydub no disponible. La visualizaciÃ³n de forma de onda y recorte de audio no funcionarÃ¡.")

# Importar widgets extraÃ­dos
from timeline_editor_window import TimelineEditorWindow
from music_browser_dialog import MusicBrowserDialog
from studio_project_manager import StudioProjectManager
from studio_storyboard_handlers import StudioStoryboardHandlers
from studio_image_handlers import StudioImageHandlers
from studio_video_assembly_handlers import StudioVideoAssemblyHandlers
from recraft_style_catalog import RECRAFT_STYLE_OPTIONS
from thumbnail_pipeline import ThumbnailPipeline
from groq_client import GroqAiClient


def get_channel_name(default: str = "this channel") -> str:
    """Nombre visible del canal, leido del Channel Bible.

    Import perezoso: este modulo se carga antes que el perfil en algunos flujos.
    """
    try:
        from channel_strategy import get_channel_name as _real
        return _real(default)
    except Exception:
        return default


try:
    from tts_generator import TextToSpeechGenerator as StandaloneTextToSpeechGenerator
except ImportError:
    StandaloneTextToSpeechGenerator = None

# Nota: WaveformWidget y TimelineEditorWindow han sido movidos a mÃ³dulos separados
# para mejorar la organizaciÃ³n del cÃ³digo
# 
# REFACTORIZACIÃ“N:
# - waveform_widget.py: Widget para visualizar forma de onda de audio
# - timeline_editor_window.py: Ventana del editor de timeline
# - video_config.py: ConfiguraciÃ³n centralizada del sistema
# - music_browser_dialog.py: DiÃ¡logo para buscar y seleccionar mÃºsica de Jamendo
# - studio_project_manager.py: Gestor de proyectos extraÃ­do para mejorar organizaciÃ³n
# - studio_storyboard_handlers.py: Handlers de generaciÃ³n y manejo de storyboards


class _LlmThread(QThread):
    """QThread que ejecuta una función LLM y emite done(result) al terminar.

    A diferencia del patrón worker+moveToThread, aquí la señal 'done' pertenece
    al objeto QThread creado en el hilo principal.  Cuando run() llama a
    self.done.emit() desde el hilo de fondo, PyQt6 compara el hilo de emisión
    (fondo) con el thread affinity del receptor (hilo principal) y aplica
    QueuedConnection automáticamente — garantizando que el slot se ejecute en
    el hilo principal sin ninguna configuración extra.
    """
    done = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception:
            result = None
        self.done.emit(result)


# Alias de compatibilidad por si hay referencias residuales
_LlmTaskWorker = _LlmThread


class ThumbnailGenerationWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        project_root,
        project_data,
        llm_client=None,
        recraft_client=None,
        google_ai_image_client=None,
        vertex_imagen_client=None,
        fal_client=None,
        comfyui_image_client=None,
        google_images_client=None,
        wikimedia_client=None,
        style_hint=None,
    ):
        super().__init__()
        self.project_root = project_root
        self.project_data = project_data
        self.llm_client = llm_client
        self.recraft_client = recraft_client
        self.google_ai_image_client = google_ai_image_client
        self.vertex_imagen_client = vertex_imagen_client
        self.fal_client = fal_client
        self.comfyui_image_client = comfyui_image_client
        self.google_images_client = google_images_client
        self.wikimedia_client = wikimedia_client
        self.style_hint = style_hint

    def run(self):
        try:
            pipeline = ThumbnailPipeline(
                project_root=self.project_root,
                llm_client=self.llm_client,
                recraft_client=self.recraft_client,
                google_ai_image_client=self.google_ai_image_client,
                vertex_imagen_client=self.vertex_imagen_client,
                fal_client=self.fal_client,
                comfyui_image_client=self.comfyui_image_client,
                google_images_client=self.google_images_client,
                wikimedia_client=self.wikimedia_client,
                log_callback=self.progress.emit,
            )
            result = pipeline.generate_for_project(
                project_data=self.project_data,
                style_hint=self.style_hint,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))

class AutoVideoStudioTab(QWidget):
    """
    PestaÃ±a completa de Auto Video Studio con pipeline de 3 pasos:
    1. Generar Storyboard
    2. Generar ImÃ¡genes
    3. Ensamblar Video
    """

    # Señales para comunicación thread-safe
    _play_file_signal = pyqtSignal(str)
    _download_error_signal = pyqtSignal(str)
    _download_progress_signal = pyqtSignal(int)
    _publish_done_signal = pyqtSignal(dict)
    # El hilo de publicacion escribe en el panel a traves de esta senal (thread-safe).
    _publish_log_signal = pyqtSignal(str)
    LONG_HORIZONTAL_MIN_DURATION_SECONDS = 120
    LONG_HORIZONTAL_DEFAULT_DURATION_SECONDS = 1800
    DURATION_SLIDER_MAX_SECONDS = 7200
    SHORT_VERTICAL_MIN_DURATION_SECONDS = 30
    SHORT_VERTICAL_DEFAULT_DURATION_SECONDS = 60
    SHORT_VERTICAL_MAX_DURATION_SECONDS = 180
    LONG_VERTICAL_MIN_DURATION_SECONDS = 180
    LONG_VERTICAL_DEFAULT_DURATION_SECONDS = 600

    def __init__(self, parent_gui):
        super().__init__()
        self.parent_gui = parent_gui
        self.cost_calculator = CostCalculator()

        # Conectar seÃ±ales thread-safe
        self._play_file_signal.connect(self._play_local_file)
        self._download_error_signal.connect(self._on_download_error)
        self._publish_log_signal.connect(self.log)
        self._download_progress_signal.connect(self._on_download_progress)

        # Estado
        self.is_generating = False
        self.last_storyboard_data = None
        self.last_generated_video_data = None
        self.elevenlabs_voices = {}
        self.voice_load_thread = None
        self.current_worker = None
        self.current_thread = None
        self.thumbnail_worker = None
        self.thumbnail_thread = None
        self.auto_save_enabled = True
        self.selected_research_snippets = []  # Snippets de investigacion
        self._loading_project = False  # Guard para evitar auto-save durante carga de proyecto
        self._project_state_token = 0
        self._current_worker_project_token = None
        self._current_thumbnail_project_token = None
        self._current_thumbnail_project_path = None
        self.thumbnail_groq_client = None
        # Ruta del proyecto actual (si estÃ¡ cargado)
        self.current_project_path = None
        self.thumbnail_data = None
        self.thumbnail_variants = []
        self.thumbnail_strategy = None
        self.selected_thumbnail_path = None
        self._suppress_thumbnail_autosave = False

        # Crear generador adaptado
        self.generator = AutoVideoGeneratorPyQt6()

        # Conectar seÃ±ales del generador
        self.generator.log_signal.connect(self.log)
        self.generator.status_signal.connect(self.update_status)
        self.generator.error_signal.connect(self.show_error)

        # Crear gestor de proyectos
        self.project_manager = StudioProjectManager(self)

        # Crear handlers
        self.storyboard_handlers = StudioStoryboardHandlers(self)
        self.image_handlers = StudioImageHandlers(self)
        self.video_assembly_handlers = StudioVideoAssemblyHandlers(self)

        # Crear UI
        self.setup_ui()
        self._enforce_duration_policy_for_selected_platform(silent=True)

        # Conectar auto-guardado a controles de configuraciÃ³n
        self._connect_auto_save_signals()

        # Cargar voces de ElevenLabs
        self.load_elevenlabs_voices()

        # La carga del ultimo proyecto la maneja video_optimizer_pyqt6.py (load_last_project)

    @staticmethod
    def _normalize_project_path(project_path):
        """Normaliza rutas de proyecto para comparaciones robustas."""
        if not project_path:
            return None
        try:
            return os.path.normcase(os.path.realpath(str(project_path)))
        except Exception:
            return str(project_path)

    def _begin_project_load(self, project_path=None):
        """Activa modo carga y cancela callbacks/threads del proyecto previo."""
        self._project_state_token += 1
        self._loading_project = True
        self._current_worker_project_token = None
        self._current_thumbnail_project_token = None
        self._current_thumbnail_project_path = None

        if hasattr(self, '_config_auto_save_timer') and self._config_auto_save_timer:
            self._config_auto_save_timer.stop()

        try:
            self.cleanup_thread()
        except Exception:
            pass

        self.last_storyboard_data = None
        self.last_generated_video_data = None

        if hasattr(self, 'selected_music_path'):
            self.selected_music_path = None
        if hasattr(self, 'selected_music_metadata'):
            self.selected_music_metadata = None
        if hasattr(self, 'selected_music_label'):
            self.selected_music_label.setText("Pista seleccionada: Ninguna")
        if hasattr(self, 'restore_thumbnail_state'):
            self.restore_thumbnail_state(thumbnail_data=None, thumbnail_path=None)
        if hasattr(self, 'parent_gui'):
            if hasattr(self.parent_gui, 'last_raw_image_path'):
                self.parent_gui.last_raw_image_path = None
            if hasattr(self.parent_gui, 'last_thumbnail_path'):
                self.parent_gui.last_thumbnail_path = None
            if hasattr(self.parent_gui, '_update_thumbnail_preview'):
                self.parent_gui._update_thumbnail_preview(None)

        if hasattr(self, 'btn_generate_images'):
            self.btn_generate_images.setEnabled(False)
        if hasattr(self, 'btn_export_recraft_prompts'):
            self.btn_export_recraft_prompts.setEnabled(False)
        if hasattr(self, 'btn_assemble'):
            self.btn_assemble.setEnabled(False)
        if hasattr(self, 'btn_change_voice'):
            self.btn_change_voice.setEnabled(False)
        if hasattr(self, 'btn_open_timeline'):
            self.btn_open_timeline.setEnabled(False)

        return self._project_state_token

    def _end_project_load(self, token):
        """Desactiva modo carga si el token sigue vigente."""
        if token == self._project_state_token:
            self._loading_project = False

    def _is_project_context_current(self, project_path=None, token=None):
        """Verifica si un callback sigue perteneciendo al proyecto activo."""
        if token is not None and token != self._project_state_token:
            return False
        if project_path is None:
            return True
        return self._normalize_project_path(self.current_project_path) == self._normalize_project_path(project_path)

    def _bind_current_worker_to_project(self):
        """Ata el worker en curso al estado actual del proyecto."""
        self._current_worker_project_token = self._project_state_token
        # La ruta ademas del token: recargar el MISMO proyecto (cosa que hace
        # el propio flujo de generacion) cambia el token pero no la ruta.
        self._current_worker_project_path = self.current_project_path

    def _should_accept_current_worker_callback(self):
        """Descarta resultados asíncronos de un proyecto/estado obsoleto.

        Antes comparaba solo el token, y el flujo de generacion recarga el
        proyecto en el medio: el guion volvia, se lo daba por viejo y se
        tiraba, con el storyboard ya guardado en disco y todos los botones
        deshabilitados (2026-09-10, "El saqueo de Bagdad").
        """
        from worker_context import should_accept_worker_result

        aceptar, motivo = should_accept_worker_result(
            self._current_worker_project_token,
            self._project_state_token,
            getattr(self, '_current_worker_project_path', None),
            self.current_project_path,
        )
        if not aceptar:
            # A consola tambien: en el panel de la GUI el aviso se perdia
            # entre cientos de lineas y parecia que nada habia pasado.
            print(f"[Worker] Resultado descartado: {motivo}")
        elif motivo != "mismo estado de proyecto":
            print(f"[Worker] Resultado aceptado: {motivo}")
        return aceptar

    def _bind_thumbnail_worker_to_project(self):
        """Ata la generación de miniaturas al proyecto activo actual."""
        self._current_thumbnail_project_token = self._project_state_token
        self._current_thumbnail_project_path = self.current_project_path

    def _should_accept_thumbnail_callback(self):
        """Descarta miniaturas generadas para un proyecto/estado ya obsoleto."""
        return self._is_project_context_current(
            self._current_thumbnail_project_path,
            self._current_thumbnail_project_token,
        )

    def apply_loaded_project_storyboard(self, storyboard_data, auto_search_images=False):
        """Restaura storyboard desde proyecto sin disparar flujo de generación nueva."""
        self.last_storyboard_data = storyboard_data
        self.populate_review_panel(storyboard_data, auto_search_images=auto_search_images)

        self.btn_storyboard.setEnabled(True)
        if hasattr(self, 'btn_generate_images'):
            self.btn_generate_images.setEnabled(True)
        if hasattr(self, 'btn_export_recraft_prompts'):
            self.btn_export_recraft_prompts.setEnabled(True)
        if hasattr(self, 'btn_open_timeline'):
            self.btn_open_timeline.setEnabled(True)
        self._refresh_assemble_button_state()
        self._refresh_thumbnail_module_state()
        if hasattr(self, 'progress_bar') and self.progress_bar:
            self.progress_bar.hide()

        self.update_status("Proyecto cargado - Revisa y continúa")

    def _resolve_media_path_for_ui_state(self, raw_path):
        """Resuelve rutas relativas/absolutas para validar media disponible en UI."""
        if not raw_path:
            return None

        try:
            original = str(raw_path).strip()
        except Exception:
            return None

        if not original:
            return None

        if os.path.exists(original):
            return original

        candidate = Path(original)
        if candidate.is_absolute():
            return None

        candidate_bases = []
        if self.current_project_path:
            try:
                project_path = Path(self.current_project_path)
                candidate_bases.append(project_path.parent if project_path.suffix.lower() == '.json' else project_path)
            except Exception:
                pass

        candidate_bases.append(Path.cwd())
        candidate_bases.append(Path(__file__).resolve().parent)

        seen = set()
        for base in candidate_bases:
            try:
                normalized_base = str(base.resolve())
            except Exception:
                normalized_base = str(base)
            if normalized_base in seen:
                continue
            seen.add(normalized_base)

            try_path = base / candidate
            if try_path.exists():
                return str(try_path)

        return None

    def _get_segments_for_assembly_state(self):
        """Prioriza segmentos vivos del timeline para reflejar cambios manuales al instante."""
        try:
            if (
                hasattr(self, 'timeline_editor_window') and
                self.timeline_editor_window and
                getattr(self.timeline_editor_window, 'timeline_editor', None) and
                getattr(self.timeline_editor_window.timeline_editor, 'segments', None)
            ):
                return self.timeline_editor_window.timeline_editor.segments
        except Exception:
            pass

        if isinstance(self.last_storyboard_data, dict):
            return self.last_storyboard_data.get('segments') or []

        return []

    def _segment_has_available_visual_media(self, segment):
        """Determina si un segmento ya tiene media utilizable para ensamblar."""
        if not isinstance(segment, dict):
            return False

        image_deleted = bool(segment.get('image_deleted', False))
        video_path = self._resolve_media_path_for_ui_state(segment.get('video_path'))
        if video_path:
            return True

        image_path = self._resolve_media_path_for_ui_state(segment.get('image_path'))
        if image_path and not image_deleted:
            return True

        return False

    def _refresh_assemble_button_state(self, reason=None):
        """Actualiza el estado del botón de ensamblaje según storyboard + media actual."""
        if not hasattr(self, 'btn_assemble'):
            return False

        segments = self._get_segments_for_assembly_state()
        has_storyboard = bool(segments)
        available_media_segments = sum(
            1 for seg in segments if self._segment_has_available_visual_media(seg)
        )
        can_assemble = has_storyboard and available_media_segments > 0

        previous_state = self.btn_assemble.isEnabled()
        self.btn_assemble.setEnabled(can_assemble)

        if reason and can_assemble and not previous_state:
            self.log(
                f" Ensamblado habilitado: {available_media_segments} segmento(s) con imagen/video disponibles."
            )

        return can_assemble

    def _connect_auto_save_signals(self):
        """Conecta signals de auto-guardado a los controles de configuraciÃ³n"""
        # Durante el constructor lazy, el proxy del parent todavía devuelve
        # _Dummy. El QLineEdit real ya pertenece a este Studio tras setup_ui().
        topic_input = getattr(self, 'topic_input', None)
        if topic_input is not None and hasattr(topic_input, 'editingFinished'):
            topic_input.editingFinished.connect(
                lambda: self._trigger_config_auto_save('tema del nuevo proyecto')
                if not self.last_storyboard_data else None)
        # Conectar cambios en controles a auto-guardado
        if hasattr(self, 'platform_combo'):
            self.platform_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de formato de video"))

        if hasattr(self, 'lang_es') and hasattr(self, 'lang_en'):
            self.lang_es.toggled.connect(
                lambda: self._trigger_config_auto_save("cambio de idioma"))

        if hasattr(self, 'voice_combo'):
            self.voice_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de voz"))

        if hasattr(self, 'style_combo'):
            self.style_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de estilo visual"))

        # image_provider_combo ya conectado en _on_image_provider_changed()

        if hasattr(self, 'images_per_segment_spin'):
            self.images_per_segment_spin.valueChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de frecuencia de imÃ¡genes"))

        if hasattr(self, 'interleave_images_check'):
            self.interleave_images_check.stateChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de intercalado de imÃ¡genes"))

        if hasattr(self, 'visual_mode_group'):
            self.visual_mode_group.buttonClicked.connect(
                lambda: self._trigger_config_auto_save("cambio de modo visual"))

        if hasattr(self, 'cinematic_preset_combo'):
            self.cinematic_preset_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de preset cinematogrÃ¡fico"))

        if hasattr(self, 'transition_type_combo'):
            self.transition_type_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de tipo de transiciÃ³n"))

        if hasattr(self, 'transition_duration_spin'):
            self.transition_duration_spin.valueChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de duraciÃ³n de transiciÃ³n"))

        if hasattr(self, 'transition_sfx_check'):
            self.transition_sfx_check.toggled.connect(
                lambda: self._trigger_config_auto_save("cambio de sonido de transicion"))

        if hasattr(self, 'transition_sfx_combo'):
            self.transition_sfx_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de archivo de transicion"))

        if hasattr(self, 'duration_slider'):
            # Solo auto-guardar cuando se suelta el slider (no durante el arrastre)
            self.duration_slider.sliderReleased.connect(
                lambda: self._trigger_config_auto_save("cambio de duraciÃ³n"))

        # Conectar checkboxes de opciones
        if hasattr(self, 'subtitles_check'):
            self.subtitles_check.stateChanged.connect(
                lambda: self._trigger_config_auto_save("cambio en subtÃ­tulos"))

        if hasattr(self, 'music_check'):
            self.music_check.stateChanged.connect(
                lambda: self._trigger_config_auto_save("cambio en mÃºsica"))

        if hasattr(self, 'research_check'):
            self.research_check.stateChanged.connect(
                lambda: self._trigger_config_auto_save("cambio en investigaciÃ³n web"))

        if hasattr(self, 'cinematic_check'):
            self.cinematic_check.toggled.connect(
                lambda: self._trigger_config_auto_save("cambio en efectos cinematogrÃ¡ficos"))

        if hasattr(self, 'subtitle_style_combo'):
            self.subtitle_style_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de estilo de subtÃ­tulos"))

    def get_selected_video_format(self):
        """
        Retorna el formato de video seleccionado.
        Puede ser: 16:9, 9:16, 1:1, 16:9+1:1 (salida dual)
        o 16:9+1:1+9:16 (salida triple).
        Compatible con proyectos legacy guardados por plataforma.
        """
        if not hasattr(self, 'platform_combo'):
            return '16:9'

        data = self.platform_combo.currentData()
        if isinstance(data, dict):
            return data.get('video_format', '16:9')

        # Fallback legacy
        text = (self.platform_combo.currentText() or '').strip().lower()
        return self._legacy_platform_to_format(text)

    @staticmethod
    def _is_short_form_platform_key(platform_key: str) -> bool:
        return str(platform_key or '').strip().lower() in {'youtube_short', 'tiktok', 'reels'}

    def _build_output_profile(self, platform_key: str) -> dict:
        normalized = str(platform_key or 'youtube').strip().lower()
        profile_map = {
            'youtube': {'video_format': '16:9', 'platform': 'youtube', 'resolution': (1920, 1080)},
            'youtube_short': {'video_format': '9:16', 'platform': 'youtube_short', 'resolution': (1080, 1920)},
            'youtube_vertical': {'video_format': '9:16', 'platform': 'youtube_vertical', 'resolution': (1080, 1920)},
            'tiktok': {'video_format': '9:16', 'platform': 'tiktok', 'resolution': (1080, 1920)},
            'reels': {'video_format': '9:16', 'platform': 'reels', 'resolution': (1080, 1920)},
            'square': {'video_format': '1:1', 'platform': 'square', 'resolution': (1080, 1080)},
            'x': {'video_format': '1:1', 'platform': 'square', 'resolution': (1080, 1080)},
            'x_square': {'video_format': '1:1', 'platform': 'square', 'resolution': (1080, 1080)},
        }
        return profile_map.get(normalized, profile_map['youtube']).copy()

    def get_selected_output_profiles(self):
        """Retorna perfiles de salida solicitados por el usuario (uno o varios formatos)."""
        if hasattr(self, 'platform_combo'):
            data = self.platform_combo.currentData()
            if isinstance(data, dict):
                platforms = data.get('platforms')
                if isinstance(platforms, list) and platforms:
                    return [self._build_output_profile(platform_key) for platform_key in platforms]
                return [self._build_output_profile(data.get('platform', 'youtube'))]

        format_value = self.get_selected_video_format()
        legacy_platforms = {
            '16:9': ['youtube'],
            '9:16': ['youtube_short'],
            '1:1': ['square'],
            '16:9+1:1': ['youtube', 'square'],
            '16:9+1:1+9:16': ['youtube', 'square', 'youtube_short'],
        }.get(format_value, ['youtube'])
        return [self._build_output_profile(platform_key) for platform_key in legacy_platforms]

    def get_selected_video_formats(self):
        """Lista de formatos de salida seleccionados."""
        return [p.get('video_format', '16:9') for p in self.get_selected_output_profiles()]

    def get_selected_voice_rate(self) -> str:
        """Velocidad base del TTS. Siempre '+0%': la aceleración para Shorts
        se aplica automáticamente post-TTS con FFmpeg atempo."""
        return "+0%"


    def get_selected_platform_key(self):
        """
        Retorna la clave primaria de plataforma interna.
        Si hay varios formatos, usa el primero como base de generación.
        """
        profiles = self.get_selected_output_profiles()
        if not profiles:
            return 'youtube'
        return profiles[0].get('platform', 'youtube')

    def get_selected_resolution(self):
        """Retorna la resolución primaria esperada para la generación de assets."""
        profiles = self.get_selected_output_profiles()
        if not profiles:
            return (1920, 1080)
        return profiles[0].get('resolution', (1920, 1080))

    def _get_min_duration_for_selected_platform(self) -> int:
        """Retorna la duración mínima permitida según el formato seleccionado."""
        return int(self._get_duration_policy_for_selected_platform()['min'])

    def _get_default_duration_for_selected_platform(self) -> int:
        """Retorna la duración sugerida al cambiar de formato/plataforma."""
        platform_key = self.get_selected_platform_key()
        if platform_key == 'youtube':
            return int(self.LONG_HORIZONTAL_DEFAULT_DURATION_SECONDS)
        if platform_key == 'youtube_short':
            return int(self.SHORT_VERTICAL_DEFAULT_DURATION_SECONDS)
        if platform_key == 'youtube_vertical':
            return int(self.LONG_VERTICAL_DEFAULT_DURATION_SECONDS)
        return int(self._get_duration_policy_for_selected_platform()['min'])

    def _get_duration_policy_for_selected_platform(self) -> dict:
        """Devuelve la política de duración aplicable al formato/plataforma actual."""
        platform_key = self.get_selected_platform_key()
        if platform_key == 'youtube':
            return {
                'min': self.LONG_HORIZONTAL_MIN_DURATION_SECONDS,
                'max': self.DURATION_SLIDER_MAX_SECONDS,
                'tick': 60,
                'label': 'YouTube horizontal',
            }
        if platform_key == 'youtube_short':
            return {
                'min': self.SHORT_VERTICAL_MIN_DURATION_SECONDS,
                'max': self.SHORT_VERTICAL_MAX_DURATION_SECONDS,
                'tick': 15,
                'label': 'YouTube Shorts 9:16',
            }
        if platform_key == 'youtube_vertical':
            return {
                'min': self.LONG_VERTICAL_MIN_DURATION_SECONDS,
                'max': self.DURATION_SLIDER_MAX_SECONDS,
                'tick': 60,
                'label': 'YouTube vertical largo 9:16',
            }
        return {
            'min': 30,
            'max': self.DURATION_SLIDER_MAX_SECONDS,
            'tick': 30,
            'label': 'el formato seleccionado',
        }

    def clamp_duration_for_selected_platform(self, duration: int, sync_slider: bool = False,
                                             silent: bool = True) -> int:
        """Ajusta una duración a los límites válidos del formato seleccionado."""
        policy = self._get_duration_policy_for_selected_platform()
        try:
            requested_duration = int(duration)
        except Exception:
            requested_duration = int(policy['min'])

        clamped_duration = max(
            int(policy['min']),
            min(int(policy['max']), requested_duration)
        )

        if sync_slider and hasattr(self, 'duration_slider'):
            self.duration_slider.setMinimum(int(policy['min']))
            self.duration_slider.setMaximum(int(policy['max']))
            self.duration_slider.setTickInterval(int(policy['tick']))
            if int(self.duration_slider.value()) != clamped_duration:
                self.duration_slider.setValue(clamped_duration)
            if hasattr(self, 'duration_label'):
                self.duration_label.setText(f"{clamped_duration}s")

        if clamped_duration != requested_duration and not silent:
            minutes = clamped_duration // 60
            seconds = clamped_duration % 60
            duration_text = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
            self.log(
                f"ℹ️ Duración ajustada automáticamente a {clamped_duration}s ({duration_text}) "
                f"para {policy['label']}."
            )

        return clamped_duration

    def _enforce_duration_policy_for_selected_platform(self, silent: bool = False):
        """Sincroniza el slider con la política de duración del formato seleccionado."""
        if not hasattr(self, 'duration_slider'):
            return
        policy = self._get_duration_policy_for_selected_platform()
        current_value = int(self.duration_slider.value())
        requested_value = current_value
        if current_value < int(policy['min']) or current_value > int(policy['max']):
            requested_value = self._get_default_duration_for_selected_platform()
        self.clamp_duration_for_selected_platform(
            requested_value,
            sync_slider=True,
            silent=silent,
        )

    def _on_platform_selection_changed(self):
        """Aplica reglas de duración cuando cambia el formato de salida."""
        self._enforce_duration_policy_for_selected_platform()
        self._auto_configure_image_frequency()
        self._refresh_thumbnail_module_state()
        self.update_cost_display()

    def _auto_configure_image_frequency(self):
        """Auto-ajusta la frecuencia de imagenes segun el formato seleccionado.

        Para videos horizontales largos (15-60 min) sube automaticamente el ratio
        para que cada imagen cubra ~20-30 s de narracion, reduciendo la cantidad
        total de assets a generar sin sacrificar calidad visual.
        Videos cortos o verticales se dejan en 1 (una imagen por segmento).
        """
        if not hasattr(self, 'images_per_segment_spin'):
            return
        platform_key = self.get_selected_platform_key()
        if platform_key == 'youtube':
            # Video largo horizontal: sugerir 3 segmentos por imagen
            # (cada segmento ~6-8 s => ~18-24 s por imagen, cinematografico)
            self.images_per_segment_spin.setValue(3)
        else:
            # Formatos cortos / verticales: 1 imagen por segmento
            self.images_per_segment_spin.setValue(1)

    def _default_transition_sfx_path(self) -> str | None:
        root = Path(__file__).resolve().parent
        for candidate in (
            root / "transition_overlays" / "swoosh.wav",
            root / "swoosh.wav",
        ):
            if candidate.exists():
                return str(candidate)
        return None

    def _transition_sfx_display_name(self, path: str) -> str:
        name = os.path.splitext(os.path.basename(path or ""))[0]
        if name.lower() == "swoosh":
            return "Swoosh (wosh)"
        return name.replace("_", " ").replace("-", " ").title() or "Swoosh"

    def _populate_transition_sfx_combo(self, selected_path: str | None = None):
        if not hasattr(self, "transition_sfx_combo"):
            return
        combo = self.transition_sfx_combo
        current = selected_path or (combo.currentData() if combo.count() else None)
        combo.blockSignals(True)
        combo.clear()
        seen = set()
        root = Path(__file__).resolve().parent
        search_dirs = [root / "transition_overlays", root]
        for folder in search_dirs:
            if not folder.is_dir():
                continue
            for wav in sorted(folder.glob("*.wav")):
                key = str(wav.resolve())
                if key.lower() in seen:
                    continue
                seen.add(key.lower())
                combo.addItem(self._transition_sfx_display_name(str(wav)), key)
        if current and os.path.exists(current):
            abs_current = str(Path(current).resolve())
            idx = combo.findData(abs_current)
            if idx < 0:
                combo.addItem(
                    f"Personalizado: {os.path.basename(abs_current)}",
                    abs_current,
                )
                idx = combo.findData(abs_current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        elif combo.count() == 0:
            combo.addItem("Swoosh (wosh)", self._default_transition_sfx_path())
        combo.blockSignals(False)

    def _on_transition_sfx_toggled(self, enabled: bool):
        if hasattr(self, "transition_sfx_combo"):
            self.transition_sfx_combo.setEnabled(bool(enabled))
        if hasattr(self, "btn_pick_transition_sfx"):
            self.btn_pick_transition_sfx.setEnabled(bool(enabled))

    def _on_pick_transition_sfx(self):
        start_dir = str(Path(__file__).resolve().parent / "transition_overlays")
        if not os.path.isdir(start_dir):
            start_dir = str(Path(__file__).resolve().parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Elegir sonido de transicion",
            start_dir,
            "Audio (*.wav *.mp3 *.ogg);;WAV (*.wav);;Todos (*.*)",
        )
        if not path:
            return
        self._populate_transition_sfx_combo(selected_path=path)
        self._trigger_config_auto_save("archivo de transicion personalizado")

    def is_transition_sfx_enabled(self) -> bool:
        return bool(getattr(self, "transition_sfx_check", None) and self.transition_sfx_check.isChecked())

    def get_transition_sfx_path(self) -> str | None:
        if not self.is_transition_sfx_enabled():
            return None
        if hasattr(self, "transition_sfx_combo"):
            data = self.transition_sfx_combo.currentData()
            if data and os.path.exists(str(data)):
                return str(data)
        return self._default_transition_sfx_path()

    def _get_selected_image_provider_text(self):
        """Retorna el texto visible del proveedor de imágenes seleccionado."""
        if not hasattr(self, 'image_provider_combo'):
            return "Recraft AI"
        return (self.image_provider_combo.currentText() or "Recraft AI").strip()

    def _provider_supports_visual_styles(self, provider_text=None) -> bool:
        """Solo Recraft expone estilos visuales nativos en esta UI."""
        provider = str(provider_text or self._get_selected_image_provider_text()).strip().lower()
        return provider == "recraft ai"

    def get_selected_visual_style(self):
        """Retorna el estilo visual solo cuando aplica al proveedor actual."""
        if not hasattr(self, 'style_combo'):
            return None
        if not self._provider_supports_visual_styles():
            return None
        value = (self.style_combo.currentText() or "").strip()
        return value or None

    def _legacy_platform_to_format(self, value):
        value = (value or '').strip().lower()
        normalized = (
            value
            .replace('·', '+')
            .replace('|', '+')
            .replace('/', '+')
            .replace('_', '+')
            .replace(',', '+')
            .replace(' ', '')
        )
        tokens = [token for token in normalized.split('+') if token]
        token_set = set(tokens)

        triple_aliases = (
            '16:9+1:1+9:16',
            '16:9+9:16+1:1',
            'triple',
        )
        dual_aliases = ('16:9+1:1', 'dual', 'youtube+x', 'youtube_x', 'dual_youtube_x')
        has_horizontal = (
            ('16:9' in normalized)
            or ('horizontal' in normalized)
            or ('youtube' in token_set)
            or (normalized == 'youtube')
        )
        has_square = (
            ('1:1' in normalized)
            or ('square' in normalized)
            or (normalized in ('x', 'x_square'))
            or ('x' in token_set)
        )
        has_vertical = (
            ('9:16' in normalized)
            or ('vertical' in normalized)
            or ('short' in normalized)
            or ('reel' in normalized)
            or (normalized in ('tiktok', 'reels', '9:16'))
        )

        if value in triple_aliases or normalized in triple_aliases:
            return '16:9+1:1+9:16'
        if has_horizontal and has_square and has_vertical:
            return '16:9+1:1+9:16'

        if value in dual_aliases or normalized in dual_aliases:
            return '16:9+1:1'
        if has_horizontal and has_square:
            return '16:9+1:1'

        # Compatibilidad con nombres legacy de formato vertical y etiquetas antiguas del combo.
        if (
            value in ('youtube_short', 'tiktok', 'reels', '9:16')
            or '9:16' in normalized
            or 'vertical' in normalized
            or 'short' in normalized
            or 'reel' in normalized
        ):
            return '9:16'
        if (
            value in ('square', 'x_square', '1:1', 'x')
            or '1:1' in normalized
            or 'square' in normalized
            or ('x' in token_set)
        ):
            return '1:1'
        if '16:9' in normalized or 'horizontal' in normalized:
            return '16:9'
        return '16:9'

    def set_video_format(self, value):
        """
        Selecciona el combo de formato a partir de:
        - formato directo: 16:9 / 9:16 / 1:1 / 16:9+1:1 / 16:9+1:1+9:16
        - valores legacy de plataforma: youtube/9:16/tiktok/youtube_short/youtube_vertical
        """
        target_platform = str(value or '').strip().lower()
        for i in range(self.platform_combo.count()):
            data = self.platform_combo.itemData(i)
            if isinstance(data, dict) and str(data.get('platform', '')).strip().lower() == target_platform:
                self.platform_combo.setCurrentIndex(i)
                return True

        target_format = self._legacy_platform_to_format(value)
        for i in range(self.platform_combo.count()):
            data = self.platform_combo.itemData(i)
            if isinstance(data, dict) and data.get('video_format') == target_format:
                self.platform_combo.setCurrentIndex(i)
                return True
        return False

    def _on_image_provider_changed(self):
        """Activa estilos visuales solo cuando el proveedor seleccionado es Recraft."""
        current_style = self.style_combo.currentText() if self.style_combo.count() > 0 else None
        provider_text = self._get_selected_image_provider_text()
        supports_styles = self._provider_supports_visual_styles(provider_text)

        self.style_combo.blockSignals(True)
        self.style_combo.clear()
        self.style_combo.addItems(self.recraft_styles)

        # Restaurar estilo anterior si existe en la nueva lista
        if current_style:
            idx = self.style_combo.findText(current_style)
            if idx >= 0:
                self.style_combo.setCurrentIndex(idx)
        self.style_combo.blockSignals(False)

        self.style_combo.setEnabled(supports_styles)
        if hasattr(self, 'style_label'):
            self.style_label.setEnabled(supports_styles)

        if supports_styles:
            style_tooltip = "Estilos visuales nativos de Recraft."
        else:
            style_tooltip = (
                "Este proveedor no usa la lista de estilos de Recraft. "
                "El selector se desactiva para evitar confusiÃ³n."
            )
        self.style_combo.setToolTip(style_tooltip)
        if hasattr(self, 'style_label'):
            self.style_label.setToolTip(style_tooltip)

        self._trigger_config_auto_save("cambio de proveedor de imÃ¡genes")

    # ------------------------------------------------------------------
    #  Helpers para el combo de video + preset de canal Stunning-Revelations
    # ------------------------------------------------------------------
    def _get_selected_video_provider_text(self) -> str:
        """Devuelve el texto exacto seleccionado en el combo de proveedor de video."""
        if not hasattr(self, 'video_provider_combo'):
            return "Ninguno (imagen estatica + Ken Burns)"
        return (self.video_provider_combo.currentText() or "Ninguno (imagen estatica + Ken Burns)").strip()

    def _normalize_video_provider_key(self, provider_text=None) -> tuple:
        """
        Mapea el texto del combo a (video_provider, fal_model).

        video_provider:  'none' | 'fal' | 'runway'
        fal_model:       'kling' | 'kling-pro' | 'luma' | None
        """
        text = str(provider_text or self._get_selected_video_provider_text()).strip().lower()
        if not text or text.startswith('ninguno'):
            return ('none', None)
        if 'runway' in text:
            return ('runway', None)
        if 'kling' in text and 'pro' in text:
            return ('fal', 'kling-pro')
        if 'kling' in text:
            return ('fal', 'kling')
        if 'luma' in text:
            return ('fal', 'luma')
        return ('none', None)

    def _apply_mysteries_preset(self):
        """
        Aplica la configuracion recomendada para el canal @Stunning-Revelations.

        - Proveedor de imagen: FAL Flux dev (calidad alta con steps=28)
        - Proveedor de video : FAL Kling v1.5 Standard (I2V)
        - Formato            : 9:16 Vertical Largo (YouTube, >3 min) para maximizar watch time
        - Idioma             : Ingles (English) - audiencia global de canales de misterios
        - Estilo Recraft     : 'Realistic Image' (si esta disponible) para fotorealismo
        - Auto-save si se cambio algo para persistir la configuracion.
        """
        from PyQt6.QtWidgets import QMessageBox

        aplicados = []
        no_aplicados = []

        # 1) Proveedor de imagen -> FAL Flux dev
        try:
            if hasattr(self, 'image_provider_combo'):
                idx = self.image_provider_combo.findText("FAL - Flux dev (calidad)")
                if idx >= 0:
                    self.image_provider_combo.setCurrentIndex(idx)
                    aplicados.append("Imagen: FAL Flux dev")
                else:
                    no_aplicados.append("image_provider_combo no tiene 'FAL - Flux dev (calidad)'")
        except Exception as exc:
            no_aplicados.append(f"image_provider_combo: {exc}")

        # 2) Proveedor de video -> FAL Kling Standard (I2V)
        try:
            if hasattr(self, 'video_provider_combo'):
                idx = self.video_provider_combo.findText("FAL - Kling v1.5 Standard (I2V)")
                if idx >= 0:
                    self.video_provider_combo.setCurrentIndex(idx)
                    aplicados.append("Video: FAL Kling Standard (I2V)")
                else:
                    no_aplicados.append("video_provider_combo no tiene 'FAL - Kling v1.5 Standard (I2V)'")
        except Exception as exc:
            no_aplicados.append(f"video_provider_combo: {exc}")

        # 3) Formato -> 9:16 Vertical Largo (YouTube, >3 min)
        try:
            if hasattr(self, 'platform_combo'):
                target_idx = -1
                for i in range(self.platform_combo.count()):
                    label = self.platform_combo.itemText(i) or ''
                    if 'vertical largo' in label.lower():
                        target_idx = i
                        break
                if target_idx < 0:
                    # Fallback: Shorts verticales
                    for i in range(self.platform_combo.count()):
                        label = self.platform_combo.itemText(i) or ''
                        if '9:16' in label and 'vertical' in label.lower():
                            target_idx = i
                            break
                if target_idx >= 0:
                    self.platform_combo.setCurrentIndex(target_idx)
                    aplicados.append(f"Formato: {self.platform_combo.itemText(target_idx)}")
                else:
                    no_aplicados.append("platform_combo sin opcion vertical disponible")
        except Exception as exc:
            no_aplicados.append(f"platform_combo: {exc}")

        # 4) Idioma -> English
        try:
            if hasattr(self, 'lang_en') and self.lang_en is not None:
                self.lang_en.setChecked(True)
                aplicados.append("Idioma: English")
        except Exception as exc:
            no_aplicados.append(f"idioma: {exc}")

        # 5) Estilo Recraft -> Realistic Image (si el combo lo permite)
        try:
            if hasattr(self, 'style_combo') and self.style_combo.isEnabled():
                # El preset principal usa Flux, pero si el usuario cambia luego a Recraft,
                # queremos que el estilo por defecto sea fotorealista.
                for candidate in ("Realistic Image", "Photorealism", "Cinematic"):
                    idx = self.style_combo.findText(candidate)
                    if idx >= 0:
                        self.style_combo.setCurrentIndex(idx)
                        aplicados.append(f"Estilo visual: {candidate}")
                        break
        except Exception as exc:
            no_aplicados.append(f"style_combo: {exc}")

        # 6) Ratio imagenes por segmento -> 1 (una imagen por segmento,
        #    necesario para que cada segmento tenga su clip I2V)
        try:
            if hasattr(self, 'images_per_segment_spin'):
                self.images_per_segment_spin.setValue(1)
                aplicados.append("Frecuencia de imagenes: 1:1")
        except Exception:
            pass

        # --- Log resumen al panel de la app ---
        try:
            self.log("\n Preset aplicado: Misterios historicos (@Stunning-Revelations)")
            for item in aplicados:
                self.log(f"    {item}")
            if no_aplicados:
                self.log("   Avisos del preset:")
                for warn in no_aplicados:
                    self.log(f"      - {warn}")
            costo_est = (
                "   Costo estimado por Short 60s (~12 escenas x 5s):\n"
                "      - Imagenes: ~12 x $0.025 = $0.30 (Flux dev)\n"
                "      - Videos : ~12 x $0.475 = $5.70 (Kling Std 5s)\n"
                "      - Narracion/voz/mus. aparte\n"
                "      - TOTAL aprox. contenido visual IA: ~$6.00"
            )
            self.log(costo_est)
        except Exception:
            pass

        # --- Notificacion visual rapida ---
        try:
            QMessageBox.information(
                self,
                "Preset aplicado",
                "Configuracion 'Misterios historicos' cargada:\n\n"
                "- Imagen: FAL Flux dev\n"
                "- Video : FAL Kling v1.5 Standard (I2V)\n"
                "- Formato: 9:16 Vertical Largo\n"
                "- Idioma: English\n\n"
                "Coste estimado por Short 60s: ~$6 (12 escenas x 5s).\n"
                "Puedes ajustar manualmente cualquiera de estos parametros."
            )
        except Exception:
            pass

        # Persistir cambios si hay proyecto abierto
        self._trigger_config_auto_save("preset Misterios historicos aplicado")

    def _trigger_config_auto_save(self, reason=""):
        """Activa el auto-guardado cuando cambia la configuraciÃ³n"""
        if self._loading_project:
            return
        if self.auto_save_enabled and hasattr(self, 'project_manager'):
            # Usar QTimer para debounce de 2 segundos
            if not hasattr(self, '_config_auto_save_timer') or not self._config_auto_save_timer:
                from PyQt6.QtCore import QTimer
                self._config_auto_save_timer = QTimer()
                self._config_auto_save_timer.setSingleShot(True)
                self._config_auto_save_timer.timeout.connect(
                    lambda: self.project_manager.auto_save_project(f"despuÃ©s de {reason}")
                )

            # Reiniciar timer
            self._config_auto_save_timer.stop()
            self._config_auto_save_timer.start(2000)  # 2 segundos de delay

    def _save_last_project_path(self, project_path):
        """Guarda la ruta del Ãºltimo proyecto usado"""
        try:
            from pathlib import Path
            # Usar archivo local para mayor portabilidad
            config_file = Path("last_project_path.txt")
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(project_path or "")
        except Exception as e:
            print(f"âš ï¸ No se pudo guardar Ãºltimo proyecto: {e}")

    def _clear_last_project_path(self):
        """Olvida el último proyecto para que un 'Nuevo' no lo vuelva a abrir al reiniciar.

        Escribe una MARCA y no una cadena vacia: un archivo vacio no distingue
        "el usuario pidio empezar de cero" de "el puntero se perdio", y por esa
        confusion la app arrancaba sin proyecto y sin explicar por que.
        """
        from project_autoload import NEW_PROJECT_SENTINEL

        self._save_last_project_path(NEW_PROJECT_SENTINEL)
        print("[Project] Proyecto nuevo: no se reabrira el anterior al reiniciar")


    def _play_local_file(self, file_path):
        """Abre un archivo multimedia con el reproductor predeterminado del sistema."""
        try:
            if not file_path or not os.path.exists(file_path):
                self.log(f"️ Archivo no encontrado para reproducir: {file_path}")
                return

            if os.name == 'nt':
                os.startfile(file_path)  # type: ignore[attr-defined]
            else:
                import subprocess
                import sys
                if sys.platform == 'darwin':
                    subprocess.Popen(['open', file_path])
                else:
                    subprocess.Popen(['xdg-open', file_path])
        except Exception as e:
            self.log(f"️ No se pudo abrir el archivo: {e}")

    def play_generated_video(self):
        """Reproduce el último video ensamblado."""
        video_path = None

        from project_video_result import saved_video_result
        saved = saved_video_result(getattr(self, 'current_project_path', None))
        if saved:
            self.last_generated_video_data = saved

        if hasattr(self, 'last_generated_video_data') and self.last_generated_video_data:
            video_path = self.last_generated_video_data.get('video_path')

        if not video_path or not os.path.exists(video_path):
            from PyQt6.QtWidgets import QFileDialog
            start_dir = os.path.join(os.getcwd(), 'auto_videos', 'output')
            if not os.path.exists(start_dir):
                start_dir = os.getcwd()
            video_path, _ = QFileDialog.getOpenFileName(
                self,
                "Seleccionar video para reproducir",
                start_dir,
                "Archivos de video (*.mp4 *.avi *.mkv)"
            )

        if not video_path or not os.path.exists(video_path):
            return

        self.log(f" Reproduciendo video: {video_path}")
        self._play_file_signal.emit(video_path)

    def publish_video_to_platforms(self):
        """Sube el video ensamblado a las plataformas seleccionadas."""
        from PyQt6.QtCore import Qt
        
        do_youtube = self.chk_publish_youtube.isChecked()
        do_facebook = self.chk_publish_facebook.isChecked()
        do_instagram = self.chk_publish_instagram.isChecked()
        do_x = self.chk_publish_x.isChecked() if hasattr(self, 'chk_publish_x') else False

        publish_at_youtube = None
        if hasattr(self, 'chk_schedule_youtube') and self.chk_schedule_youtube.isChecked():
            dt = self.dt_schedule_youtube.dateTime()
            dt_utc = dt.toUTC()
            publish_at_youtube = dt_utc.toString(Qt.DateFormat.ISODate)

        publish_at_facebook = None
        if hasattr(self, 'chk_schedule_facebook') and self.chk_schedule_facebook.isChecked():
            dt = self.dt_schedule_facebook.dateTime()
            dt_utc = dt.toUTC()
            publish_at_facebook = dt_utc.toString(Qt.DateFormat.ISODate)

        if not (do_youtube or do_facebook or do_instagram or do_x):
            QMessageBox.warning(self, "Sin plataforma", "Selecciona al menos una plataforma para publicar.")
            return

        video_path = None
        if self.last_generated_video_data:
            video_path = self.last_generated_video_data.get('video_path')
        if not video_path or not os.path.exists(video_path):
            from PyQt6.QtWidgets import QFileDialog
            start_dir = os.path.join(os.getcwd(), 'auto_videos', 'output')
            if not os.path.exists(start_dir):
                start_dir = os.getcwd()
            video_path, _ = QFileDialog.getOpenFileName(
                self,
                "Seleccionar video a publicar",
                start_dir,
                "Archivos de video (*.mp4)"
            )

        if not video_path or not os.path.exists(video_path):
            return

        storyboard = getattr(self, 'last_storyboard_data', None)
        if not storyboard and hasattr(self, 'project_manager') and self.project_manager.current_project_data:
            storyboard = self.project_manager.current_project_data.get('storyboard', {})
        storyboard = storyboard or {}

        # Construir metadata desde el storyboard (mismos fallbacks que daily_short_pipeline)
        topic = storyboard.get('topic') or storyboard.get('title') or os.path.splitext(os.path.basename(video_path))[0]
        script = str(storyboard.get('script') or '').strip()
        preview = script[:300].strip()

        platform_key = getattr(self, 'get_selected_platform_key', lambda: 'youtube')()
        format_val = getattr(self, 'get_selected_video_format', lambda: '')()
        is_long = format_val == '16:9' or platform_key in ('youtube', '16:9') or (hasattr(self, 'duration_slider') and self.duration_slider.value() > 60)

        from studio_channel_controls import project_channel_config
        from channel_profiles import CHANNELS
        upload_channel = project_channel_config(self)['upload_channel']
        upload_channel_name = CHANNELS[upload_channel]['name']

        # -- Leer metadata del Metadata Studio si ya fue generada --
        youtube_meta = None
        facebook_meta = None
        instagram_meta = None
        try:
            main_window = self.window()
            mt = getattr(main_window, 'metadata_tab', None)
            if mt:
                yt_title = mt.yt_title.text().strip()
                yt_desc = mt.yt_description.toPlainText().strip()
                yt_tags_raw = mt.yt_tags.toPlainText().strip()
                if yt_title or yt_desc:
                    tags = [t.strip() for t in yt_tags_raw.replace('\n', ',').split(',') if t.strip()]
                    youtube_meta = {"title": yt_title, "description": yt_desc, "tags": tags}
                    self.log(f" ✅ Usando metadata del Metadata Studio: {yt_title}")
                fb_title = mt.fb_title.text().strip()
                fb_desc = mt.fb_description.toPlainText().strip()
                if fb_title or fb_desc:
                    facebook_meta = {"title": fb_title, "description": fb_desc}
                ig_title = mt.ig_title.text().strip()
                ig_desc = mt.ig_description.toPlainText().strip()
                if ig_title or ig_desc:
                    instagram_meta = {"title": ig_title, "description": ig_desc}
        except Exception as _e_mt:
            self.log(f" ⚠️ No se pudo leer del Metadata Studio: {_e_mt}")

        if storyboard.get('format_strategy') == 'micro_documentary' and self.current_project_path:
            from pathlib import Path
            pilot_folder = Path(self.current_project_path).parent
            pilot_metadata = pilot_folder / 'youtube_metadata.json'
            if pilot_metadata.exists():
                import json
                youtube_meta = json.loads(pilot_metadata.read_text(encoding='utf-8'))

        if youtube_meta:
            self.log(" ✅ Metadata del Metadata Studio lista para publicar.")
        else:
            # Si no hay metadata en el Metadata Studio, reconstruir el script desde segmentos
            if not preview:
                segs = storyboard.get('segments', [])
                if segs:
                    script_from_segs = ' '.join(
                        (s.get('text') or s.get('narration') or '').strip()
                        for s in segs if isinstance(s, dict)
                    ).strip()
                    preview = script_from_segs[:300]
                    if not topic or topic.lower() in (
                        "video", "video optimizer", "documentary", "short", "shorts",
                        "youtube", "facebook", "instagram", "reels", "content",
                        "proyecto", "project", "untitled", ""
                    ):
                        topic = os.path.splitext(os.path.basename(video_path))[0]
            self.log(" Generando metadatos SEO...")
            QApplication.processEvents()
            try:
                from groq_client import GroqAiClient
                import json
                groq = GroqAiClient()
                if not groq.client:
                    raise RuntimeError("Groq no disponible")
                prompt = f"""You are an expert YouTube SEO strategist for a documentary channel {upload_channel_name}.
Use only this channel identity for subscription calls to action and branded hashtags.
Preserve the topic and facts; never invent numbers or claims.
CURRENT VIDEO:
- Topic: {topic}
- Script preview: {preview}
- Format: {'LONG DOCUMENTARY (Horizontal 16:9)' if is_long else 'YOUTUBE SHORT (Vertical 9:16)'}

Generate a JSON object with:
1. \"title\": A highly clickable, documentary-style title. {'Around 50-60 chars.' if is_long else 'Max 50 chars with a hook.'} MUST include specific numbers or a strong hook.
2. \"description\": 3 short paragraphs. Paragraph 1 is a strong hook question. Paragraph 2 is context from the script. Paragraph 3 is a call to action. Include 3-5 relevant hashtags at the end.
3. \"tags\": An array of exactly 15 highly searched SEO tags for this specific topic. Mix broad and specific tags. {'DO NOT use #shorts' if is_long else 'Include #shorts'}

Respond ONLY with valid JSON."""
                response = groq._generate(prompt)
                text = response.strip()
                if text.startswith("```"): text = text.split("\n", 1)[-1]
                if text.endswith("```"): text = text.rsplit("```", 1)[0]
                text = text.strip()
                if not text.startswith("{"):
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start != -1 and end > start: text = text[start:end]
                youtube_meta = json.loads(text)
                self.log(f" Título generado: {youtube_meta.get('title')}")
            except Exception as e:
                self.log(f" Usando metadatos de respaldo ({e}).")
            if not youtube_meta or not isinstance(youtube_meta, dict):
                youtube_meta = {
                    "title": topic,
                    "description": (
                        f"{preview}\n\n#history #mystery #documentary" if is_long
                        else f"{preview}\n\n#history #mystery #shorts"
                    ),
                    "tags": ["history", "mystery", "documentary", "history channel", "StunningRevelations"] if is_long else ["history", "mystery", "conspiracy", "shorts", "StunningRevelations"],
                }
            if not facebook_meta:
                fb_description = (
                    f"{preview[:260]}\n\nWhat do you think really happened?\n\n#History #Mystery #StunningRevelations"
                    if preview else
                    f"The real story behind {topic}.\n\nWhat do you think really happened?\n\n#History #Mystery #StunningRevelations"
                )
                facebook_meta = {
                    "title": topic[:255],
                    "description": fb_description[:2200],
                }
            if not instagram_meta:
                ig_description = (
                    f"{preview[:320]}\n\nWhat do you think really happened?\n\n#stunningrevelations #history #mystery #reels #facts"
                    if preview else
                    f"The real story behind {topic}.\n\n#stunningrevelations #history #mystery #reels #facts"
                )
                instagram_meta = {
                    "title": topic[:120],
                    "description": ig_description[:2200],
                }
        platforms_str = ", ".join(
            p for p, v in [("YouTube", do_youtube), ("Facebook", do_facebook),
                           ("Instagram", do_instagram), ("X", do_x)] if v
        )
        self.log(f" Publicando en: {platforms_str}")
        self.btn_publish.setEnabled(False)
        self.btn_publish.setText("Publicando...")

        import threading
        import json
        import tempfile
        import shutil

        # Capturar variables para el closure
        _video_path = video_path
        from studio_channel_controls import project_channel_config
        from upload_metadata import metadata_for_channel
        youtube_meta = metadata_for_channel(youtube_meta, upload_channel)
        self.log(f" Canal de YouTube seleccionado: {youtube_meta['upload_channel']}")
        _youtube_meta = youtube_meta
        # Si el Metadata Studio no tiene campos propios de una red, se cae a
        # los de YouTube. Antes se guardaba None, `json.dump` escribia el
        # literal `null` en el archivo y el uploader reventaba con
        # "'NoneType' object has no attribute 'get'" (2026-09-09).
        _facebook_meta = facebook_meta or youtube_meta or {}
        _instagram_meta = instagram_meta or facebook_meta or youtube_meta or {}
        _x_meta = instagram_meta or facebook_meta or youtube_meta or {}
        _thumbnail_path = getattr(self, 'selected_thumbnail_path', None)
        _is_long = is_long
        _publish_at_youtube = publish_at_youtube
        _publish_at_facebook = publish_at_facebook

        def _do_upload():
            results = {}
            # Crear directorio de staging con SOLO el video correcto + metadata.
            # Esto evita que upload_from_metadata tome un .mp4 equivocado de un
            # directorio con múltiples videos previos.
            staging_dir = tempfile.mkdtemp(prefix="studio_publish_")
            try:
                from pathlib import Path
                staging = Path(staging_dir)

                # Enlace simbólico o copia del video correcto
                video_name = os.path.basename(_video_path)
                staged_video = staging / video_name
                try:
                    os.link(_video_path, str(staged_video))
                except OSError:
                    shutil.copy2(_video_path, str(staged_video))
                    
                # Enlace simbólico o copia del thumbnail si existe
                if _thumbnail_path and os.path.exists(_thumbnail_path):
                    ext = os.path.splitext(_thumbnail_path)[1]
                    staged_thumb = staging / f"thumbnail{ext}"
                    try:
                        os.link(_thumbnail_path, str(staged_thumb))
                    except OSError:
                        shutil.copy2(_thumbnail_path, str(staged_thumb))

                # Escribir metadata en el staging dir
                for fname, data in [
                    ("metadata.json", _youtube_meta),
                    ("youtube_metadata.json", _youtube_meta),
                    ("facebook_metadata.json", _facebook_meta),
                    ("instagram_metadata.json", _instagram_meta),
                    ("x_metadata.json", _x_meta),
                ]:
                    with open(staging / fname, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)

                from daily_short_pipeline import upload_to_facebook
                if do_youtube:
                    self.log(" Subiendo a YouTube...")
                    priv = "private" if _publish_at_youtube else "public"
                    try:
                        from youtube_uploader import upload_from_metadata as _yt_meta
                        results['youtube'] = _yt_meta(
                            output_dir=str(staging),
                            privacy_status=priv,
                            publish_at=_publish_at_youtube,
                        )
                    except Exception as yt_err:
                        self.log(f"️ YouTube error: {yt_err}")
                        results['youtube'] = None
                # Cada red en su propio try: sin esto, una excepcion de
                # Facebook o Instagram salta al except exterior y las redes
                # que venian DESPUES no se ejecutan nunca. Y esas excepciones
                # ocurren incluso con la publicacion ya hecha (el error 100 de
                # Facebook del 2026-09-03 llegaba despues de publicar el reel).
                if do_facebook:
                    self.log(" Subiendo a Facebook...")
                    try:
                        results['facebook'] = self._upload_facebook_via_vps(
                            staging, _video_path, _facebook_meta, is_long=_is_long, publish_at=_publish_at_facebook
                        )
                    except Exception as fb_err:
                        self.log(f"⚠ Facebook error: {fb_err}")
                        results['facebook'] = None
                if do_instagram:
                    self.log(" Subiendo a Instagram...")
                    try:
                        results['instagram'] = self._upload_instagram_via_vps(
                            staging, _video_path, _instagram_meta
                        )
                    except Exception as ig_err:
                        self.log(f"⚠ Instagram error: {ig_err}")
                        results['instagram'] = None
                if do_x:
                    self.log(" Subiendo a X...")
                    try:
                        from x_video_uploader import upload_from_metadata as _x_meta_up

                        # Si YouTube ya publico, se cita el short: X premia el
                        # video nativo, pero el enlace suma trafico al canal.
                        _yt = results.get('youtube') or {}
                        _yt_url = str(_yt.get('url') or '') if isinstance(_yt, dict) else ''

                        def _x_prog(enviado, total):
                            if total:
                                self.log(f"   X: {int(enviado / total * 100)}%")

                        results['x'] = _x_meta_up(
                            output_dir=str(staging), on_progress=_x_prog,
                            video_url=_yt_url,
                        )
                        self.log(f" X publicado: {results['x'].get('url')}")
                    except Exception as x_err:
                        # Igual que con Facebook: un fallo en una red no puede
                        # tumbar las publicaciones que ya salieron bien.
                        self.log(f"️ X error: {x_err}")
                        results['x'] = None
            except Exception as e:
                self.log(f" Error en publicación: {e}")
                import traceback
                traceback.print_exc()
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)
                self._publish_done_signal.emit(results)

        self._publish_done_signal.connect(self._on_publish_done, Qt.ConnectionType.SingleShotConnection)
        t = threading.Thread(target=_do_upload, daemon=True)
        t.start()

    def _upload_via_vps(self, platform: str, staging_dir, video_path: str, python_call: str,
                        fallback_fn=None) -> dict:
        """
        Shared VPS upload helper for Facebook and Instagram.
        Copies staging files + uploader scripts + .env.txt to a temp dir on the VPS,
        then runs python3 from there — no pre-installed deploy dir required.
        """
        import subprocess
        from dotenv import load_dotenv
        load_dotenv('.env.txt')

        ssh_host = os.getenv('VPS_SSH_HOST', '').strip()

        # VPS_UPLOAD_ENABLED=0 en .env: saltar el VPS sin borrar su config. Con
        # el VPS sin usar, cada plataforma esperaba 40s a un ssh que no
        # contestaba antes de caer al upload local (2026-09-15).
        if str(os.getenv('VPS_UPLOAD_ENABLED', '1') or '1').strip().lower() in ('0', 'false', 'no', 'off'):
            self.log(f"   VPS desactivado (VPS_UPLOAD_ENABLED=0): {platform} se sube desde esta PC")
            return fallback_fn() if fallback_fn else None

        if not ssh_host:
            self.log(f"️ VPS_SSH_HOST no configurado, intentando upload {platform} local...")
            return fallback_fn() if fallback_fn else None
        self.log(f"   Via VPS {ssh_host}...")

        video_basename = os.path.basename(video_path)
        safe_name = video_basename.replace('.mp4', '').replace(' ', '_')
        remote_tmp = f"/tmp/studio_{platform.lower()}_{safe_name}"

        # Scripts to ship alongside the video so the VPS doesn't need a pre-installed deploy
        local_scripts = [
            os.path.join(os.getcwd(), 'facebook_uploader.py'),
            os.path.join(os.getcwd(), 'instagram_uploader.py'),
            os.path.join(os.getcwd(), 'cloudinary_uploader.py'),
            os.path.join(os.getcwd(), 'env_loader.py'),
            os.path.join(os.getcwd(), '.env.txt'),
        ]

        try:
            # 1. Create remote temp dir. Con check=True el CalledProcessError
            # solo dice "returned non-zero exit status 255" y se pierde el
            # stderr de ssh, que es lo unico que explica QUE fallo (host caido,
            # clave rechazada, DNS). Paso el 2026-09-03: el VPS no respondia en
            # el puerto 22 y el log no lo decia.
            proc_mkdir = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                 ssh_host, f"mkdir -p {remote_tmp}"],
                capture_output=True, timeout=40
            )
            if proc_mkdir.returncode != 0:
                detalle = (proc_mkdir.stderr or b"").decode("utf-8", errors="ignore").strip()
                self.log(f"️ No se pudo conectar al VPS ({ssh_host}): "
                         f"{detalle[-220:] or 'exit %d sin detalle' % proc_mkdir.returncode}")
                if fallback_fn:
                    self.log(f"   [!] Fallando a upload local para {platform}...")
                    return fallback_fn()
                return None

            # 2. SCP staging dir contents (video + metadata JSONs)
            self.log(f"   Copiando video al VPS ({ssh_host})...")
            staging_files = [
                os.path.join(str(staging_dir), f)
                for f in os.listdir(str(staging_dir))
                if os.path.isfile(os.path.join(str(staging_dir), f))
            ]
            proc_scp = subprocess.run(
                ["scp"] + staging_files + [f"{ssh_host}:{remote_tmp}/"],
                capture_output=True, timeout=600
            )
            if proc_scp.returncode != 0:
                self.log(f"️ VPS SCP error: {proc_scp.stderr.decode('utf-8', errors='ignore')[-300:]}")
                if fallback_fn:
                    self.log(f"   [!] Fallando a upload local para {platform}...")
                    return fallback_fn()
                return None

            # 3. SCP uploader scripts + env file
            existing_scripts = [s for s in local_scripts if os.path.isfile(s)]
            if existing_scripts:
                subprocess.run(
                    ["scp"] + existing_scripts + [f"{ssh_host}:{remote_tmp}/"],
                    capture_output=True, timeout=60
                )
            self.log("   Archivos copiados al VPS.")

            # 4. Run the uploader from the temp dir (imports resolve locally)
            python_script = (
                "import sys, json, os\n"
                f"os.chdir({remote_tmp!r})\n"
                f"sys.path.insert(0, {remote_tmp!r})\n"
                f"{python_call}\n"
                "print(json.dumps(result or {}))\n"
            )
            ssh_cmd = f"python3 - <<'PYEOF'\n{python_script}PYEOF"
            proc = subprocess.run(
                ["ssh", ssh_host, ssh_cmd],
                capture_output=True, text=True, timeout=600
            )

            if proc.returncode != 0:
                stderr_tail = proc.stderr[-600:] if proc.stderr else ''
                self.log(f"️ VPS {platform} stderr: {stderr_tail}")
                if fallback_fn:
                    self.log(f"   [!] Fallando a upload local para {platform}...")
                    return fallback_fn()
                return None

            output = proc.stdout.strip().splitlines()
            json_line = next((l for l in reversed(output) if l.startswith('{')), None)
            if json_line:
                return json.loads(json_line)
            return {'status': 'uploaded'}

        except subprocess.TimeoutExpired:
            self.log(f"️ Timeout al subir a {platform} via VPS.")
            if fallback_fn:
                self.log(f"   [!] Fallando a upload local para {platform}...")
                return fallback_fn()
            return None
        except Exception as e:
            self.log(f"️ Error {platform} via VPS: {e}")
            import traceback
            traceback.print_exc()
            if fallback_fn:
                self.log(f"   [!] Fallando a upload local para {platform}...")
                return fallback_fn()
            return None
        finally:
            try:
                subprocess.run(
                    ["ssh", ssh_host, f"rm -rf {remote_tmp}"],
                    capture_output=True, timeout=20
                )
            except Exception:
                pass

    def _upload_facebook_via_vps(self, staging_dir, video_path: str, facebook_meta: dict,
                                  is_long: bool = False, publish_at: str = None) -> dict:
        upload_type = "video" if is_long else "reel"
        python_args = f"output_dir='.', video_state='PUBLISHED', upload_type='{upload_type}'"
        if publish_at:
            python_args += f", scheduled_publish_time='{publish_at}'"

        def _local_fallback():
            from facebook_uploader import upload_from_metadata
            from upload_progress import make_byte_progress_reporter
            return upload_from_metadata(
                output_dir=str(staging_dir),
                video_state='PUBLISHED',
                upload_type=upload_type,
                scheduled_publish_time=publish_at,
                on_progress=make_byte_progress_reporter("   Facebook: subiendo", self._publish_log_signal.emit),
            )

        return self._upload_via_vps(
            platform="Facebook",
            staging_dir=staging_dir,
            video_path=video_path,
            python_call=(
                "from facebook_uploader import upload_from_metadata\n"
                f"result = upload_from_metadata({python_args})"
            ),
            fallback_fn=_local_fallback,
        )

    def _upload_instagram_via_vps(self, staging_dir, video_path: str, instagram_meta: dict) -> dict:
        def _local_fallback():
            from instagram_uploader import upload_from_metadata
            from upload_progress import make_byte_progress_reporter
            # Sin esto el panel quedaba mudo desde "se sube desde esta PC" hasta el
            # resultado: Cloudinary + Meta procesando (hasta 5 min por intento).
            notify = self._publish_log_signal.emit
            return upload_from_metadata(
                output_dir=str(staging_dir), share_to_feed=True,
                on_progress=make_byte_progress_reporter("   Cloudinary", notify),
                on_status=lambda msg: notify(f"   Instagram: {msg}"),
            )

        return self._upload_via_vps(
            platform="Instagram",
            staging_dir=staging_dir,
            video_path=video_path,
            python_call=(
                "from instagram_uploader import upload_from_metadata\n"
                "result = upload_from_metadata(output_dir='.', share_to_feed=True)"
            ),
            fallback_fn=_local_fallback,
        )

    def _on_publish_done(self, results: dict):
        """Callback cuando terminan los uploads."""
        self.btn_publish.setEnabled(True)
        self.btn_publish.setText("Publicar video")
        for platform, result in results.items():
            if result:
                url = result.get('url') or result.get('permalink_url') or ''
                self.log(f" {platform.capitalize()} publicado{': ' + url if url else '.'}")
            else:
                self.log(f"️ {platform.capitalize()} falló.")

    def _on_download_error(self, error):
        """MÃ©todo stub para seÃ±al _download_error_signal (no se usa actualmente en AutoVideoStudioTab)"""
        pass

    def _on_download_progress(self, percentage):
        """MÃ©todo stub para seÃ±al _download_progress_signal (no se usa actualmente en AutoVideoStudioTab)"""
        pass

    def show_video_recommendations(self):
        """Muestra el diÃ¡logo de recomendaciones de videos"""
        try:
            from video_recommendations_dialog import VideoRecommendationsDialog
        except ImportError:
            QMessageBox.warning(
                self,
                "MÃ³dulo no disponible",
                "El mÃ³dulo video_recommendations_dialog.py no estÃ¡ disponible.\n"
                "AsegÃºrate de que el archivo estÃ© en el directorio del proyecto."
            )
            return

        # Obtener categorÃ­a actual o pedir al usuario
        category = self.category_combo.currentText() if hasattr(
            self, 'category_combo') else None

        if not category:
            # Pedir categorÃ­a al usuario
            from PyQt6.QtWidgets import QInputDialog
            category, ok = QInputDialog.getText(
                self,
                "Seleccionar TemÃ¡tica",
                "Ingresa la temÃ¡tica de tu canal:\n"
                "(Ej: historia, ciencia, tecnologÃ­a, misterios, etc.)"
            )
            if not ok or not category.strip():
                return
            category = category.strip()

        # Mostrar diÃ¡logo de recomendaciones
        dialog = VideoRecommendationsDialog(self, category)
        dialog.exec()

    def show_video_history(self):
        """Muestra el diÃ¡logo de historial de videos"""
        try:
            from video_history_dialog import VideoHistoryDialog
        except ImportError:
            QMessageBox.warning(
                self,
                "MÃ³dulo no disponible",
                "El mÃ³dulo video_history_dialog.py no estÃ¡ disponible.\n"
                "AsegÃºrate de que el archivo estÃ© en el directorio del proyecto."
            )
            return

        # Obtener el generador de videos
        generator = self.generator if hasattr(self, 'generator') else None

        if not generator:
            QMessageBox.warning(
                self,
                "Generador no disponible",
                "El generador de videos no estÃ¡ inicializado.\n"
                "Abre este diÃ¡logo despuÃ©s de generar al menos un video."
            )

        dialog = VideoHistoryDialog(self, generator)
        dialog.exec()

    def show_api_status(self):
        """Muestra el diÃ¡logo con el estado de todas las APIs"""
        try:
            from api_status_dialog import APIStatusDialog
            dialog = APIStatusDialog(self)
            dialog.exec()
        except ImportError as e:
            QMessageBox.warning(
    self, "Error", f"MÃ³dulo api_status_dialog no disponible: {e}")
        self.load_elevenlabs_voices()

    def __del__(self):
        """Destructor para limpiar recursos de audio"""
        try:
            # Detener mÃºsica si estÃ¡ reproduciÃ©ndose
            if hasattr(self, 'stop_music_preview'):
                try:
                    self.stop_music_preview()
                except:
                    pass
        except:
            pass

    def setup_ui(self):
        """Crea la interfaz de usuario"""
        # Layout principal con scroll
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        from studio_channel_controls import install_controls
        install_controls(self, main_layout)

        # Scroll area con scroll vertical y horizontal mejorado
        scroll = QScrollArea()
        # Permitir que el widget se ajuste al tamaÃ±o disponible
        scroll.setWidgetResizable(True)
        # Habilitar scroll horizontal cuando sea necesario
        scroll.setHorizontalScrollBarPolicy(
    Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Habilitar scroll vertical siempre
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)  # Sin borde
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                width: 14px;
                background: #f1f3f6;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical {
                background: #c7d1dc;
                min-height: 30px;
                border-radius: 7px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: #aebbc8;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                height: 14px;
                background: #f1f3f6;
                border-radius: 7px;
            }
            QScrollBar::handle:horizontal {
                background: #c7d1dc;
                min-width: 30px;
                border-radius: 7px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #aebbc8;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

        # Contenedor de contenido
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)

        # Header legacy removido para limpiar la interfaz.

        # ConfiguraciÃ³n de video
        config_group = self.create_config_section()
        content_layout.addWidget(config_group)

        # Costos
        cost_group = self.create_cost_section()
        content_layout.addWidget(cost_group)

        # Panel de control (3 botones)
        control_panel = self.create_control_panel()
        content_layout.addWidget(control_panel)

        # Sección de guión manual (IA externa)
        manual_prompt_panel = self.create_manual_prompt_section()
        content_layout.addWidget(manual_prompt_panel)

        # Panel de revisiÃ³n (editable)
        review_panel = self.create_review_panel()
        content_layout.addWidget(review_panel)

        # Miniaturas (9:16 para Shorts, 16:9 para vertical largo)
        thumbnail_panel = self.create_thumbnail_intelligence_section()
        content_layout.addWidget(thumbnail_panel)

        # Log
        log_group = self.create_log_section()
        content_layout.addWidget(log_group)

        # NO aÃ±adir stretch al final - permite scroll completo del contenido
        # content_layout.addStretch()  # Comentado para permitir scroll
        # completo

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def create_header(self):
        """Crea el header de la pestaÃ±a"""
        header = QGroupBox()
        layout = QVBoxLayout(header)

        title = QLabel("Auto Video Studio")
        title.setStyleSheet("font-size: 18pt; font-weight: 600; color: #1f2831;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Flujo: investigacion, guion, visuales, audio y ensamblaje."
        )
        subtitle.setStyleSheet("color: #6f7c89;")
        layout.addWidget(subtitle)

        # Indicador de estado
        self.status_label = QLabel("Listo")
        self.status_label.setStyleSheet("font-weight: 600; color: #1f2831;")
        layout.addWidget(self.status_label)

        # Barra de progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Modo indeterminado
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # BotÃ³n de estado de APIs
        api_status_btn = QPushButton("Estado de APIs")
        api_status_btn.setObjectName("accent")
        api_status_btn.clicked.connect(self.show_api_status)
        layout.addWidget(api_status_btn)

        # BotÃ³n de recomendaciones de videos
        self.recommend_btn = QPushButton("Recomendaciones")
        self.recommend_btn.setObjectName("warning")
        self.recommend_btn.setToolTip(
            "Obtiene ideas de videos segun tendencias y competencia."
        )
        self.recommend_btn.clicked.connect(self.show_video_recommendations)
        layout.addWidget(self.recommend_btn)

        # BotÃ³n de historial de videos
        self.history_btn = QPushButton("Historial de videos")
        self.history_btn.setToolTip(
            "Ver historial y estado de videos generados."
        )
        self.history_btn.setObjectName("info")
        self.history_btn.clicked.connect(self.show_video_history)
        layout.addWidget(self.history_btn)

        return header

    def create_config_section(self):
        """Crea la seccion de configuracion"""
        group = QGroupBox("Configuracion de video")
        layout = QVBoxLayout(group)

        # Tema
        topic_layout = QHBoxLayout()
        topic_layout.addWidget(QLabel("Tema:"))
        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText("Ej: La batalla de Cannas 216 AC")
        topic_layout.addWidget(self.topic_input)
        layout.addLayout(topic_layout)

        # Categoria
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Categoria:"))
        self.category_combo = QComboBox()
        # Las categorias son las del perfil del canal activo (su Bible), no una
        # lista fija: hasta 2026-09-21 arrancaba con esta lista en espanol y
        # solo cambiaba al restaurar un proyecto.
        try:
            from channel_strategy import get_all_category_names
            categorias = list(get_all_category_names())
        except Exception:
            categorias = []
        self.category_combo.addItems(categorias or [
            "Historia militar/guerras", "Historia antigua/civilizaciones",
            "Documentales", "Eventos naturales extremos",
            "Ciencia/Tecnologia actual", "Misterios con datos",
            "Conspiraciones verificables", "Actualidad cientifica",
        ])
        category_layout.addWidget(self.category_combo)
        category_layout.addStretch()
        layout.addLayout(category_layout)

        # Duracion
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("DuraciÃ³n:"))

        self.duration_slider = QSlider(Qt.Orientation.Horizontal)
        self.duration_slider.setMinimum(30)
        self.duration_slider.setMaximum(self.DURATION_SLIDER_MAX_SECONDS)
        self.duration_slider.setValue(self.LONG_HORIZONTAL_DEFAULT_DURATION_SECONDS)
        self.duration_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.duration_slider.setTickInterval(300)
        self.duration_slider.valueChanged.connect(self.update_cost_display)

        # Conectar para mostrar tooltip con el tiempo mientras se arrastra
        self.duration_slider.sliderPressed.connect(
            self.on_duration_slider_pressed)
        self.duration_slider.sliderMoved.connect(self.on_duration_slider_moved)
        self.duration_slider.sliderReleased.connect(
            self.on_duration_slider_released)

        duration_layout.addWidget(self.duration_slider, stretch=1)

        self.duration_label = QLabel(f"{self.LONG_HORIZONTAL_DEFAULT_DURATION_SECONDS}s")
        self.duration_slider.valueChanged.connect(
            lambda v: self.duration_label.setText(f"{v}s")
        )
        duration_layout.addWidget(self.duration_label)

        layout.addLayout(duration_layout)

        # Formato de video (aspect ratio)
        platform_layout = QHBoxLayout()
        platform_layout.addWidget(QLabel("Formato de video:"))

        self.platform_combo = QComboBox()
        self.platform_combo.addItem(
            "16:9 · Horizontal", {"video_format": "16:9", "platform": "youtube"}
        )
        self.platform_combo.addItem(
            "9:16 · Vertical (YouTube Shorts)", {"video_format": "9:16", "platform": "youtube_short"}
        )
        self.platform_combo.addItem(
            "9:16 · Vertical Largo (>3 min, YouTube)", {"video_format": "9:16", "platform": "youtube_vertical"}
        )
        self.platform_combo.addItem(
            "1:1 · Square (X)", {"video_format": "1:1", "platform": "square"}
        )
        self.platform_combo.addItem(
            "16:9 + 1:1 · YouTube + X",
            {"video_format": "16:9+1:1", "platform": "youtube", "platforms": ["youtube", "square"]}
        )
        self.platform_combo.addItem(
            "16:9 + 1:1 + 9:16 · YouTube + X + Shorts",
            {"video_format": "16:9+1:1+9:16", "platform": "youtube", "platforms": ["youtube", "square", "youtube_short"]}
        )
        self.platform_combo.setToolTip(
            "Selecciona el formato final del video antes de generar:\n"
            "• 16:9: Horizontal (YouTube)\n"
            "• 9:16: Vertical (YouTube Shorts, max 3 min; compatible con Reels/TikTok)\n"
            "• 9:16 Vertical Largo: vertical para YouTube de mas de 3 min, pensado para watch time\n"
            "• 1:1: Cuadrado (ideal para X)\n"
            "• 16:9 + 1:1: genera YouTube y X en la misma corrida\n"
            "• 16:9 + 1:1 + 9:16: genera YouTube, X y Shorts en la misma corrida"
        )
        self.platform_combo.setMaximumWidth(460)  # Limitar ancho
        self.platform_combo.currentIndexChanged.connect(self._on_platform_selection_changed)
        platform_layout.addWidget(self.platform_combo)
        platform_layout.addStretch()

        layout.addLayout(platform_layout)

        # Idioma
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("Idioma:"))

        self.lang_group = QButtonGroup()
        self.lang_es = QRadioButton("EspaÃ±ol")
        self.lang_en = QRadioButton("English")
        self.lang_es.setChecked(True)
        self.lang_group.addButton(self.lang_es)
        self.lang_group.addButton(self.lang_en)

        lang_layout.addWidget(self.lang_es)
        lang_layout.addWidget(self.lang_en)
        lang_layout.addStretch()

        layout.addLayout(lang_layout)

        # Voz
        voice_layout = QHBoxLayout()
        voice_layout.addWidget(QLabel("Voz:"))

        self.voice_combo = QComboBox()
        self.voice_combo.addItem("Cargando voces...")
        self.voice_combo.currentIndexChanged.connect(self.update_cost_display)
        self.voice_combo.setMaximumWidth(300)  # Limitar ancho
        voice_layout.addWidget(self.voice_combo, stretch=1)

        # BotÃ³n de preview de voz
        self.btn_preview_voice = QPushButton("Escuchar muestra")
        # Se habilitarÃ¡ cuando carguen las voces
        self.btn_preview_voice.setEnabled(False)
        self.btn_preview_voice.clicked.connect(self.preview_voice)
        self.btn_preview_voice.setMaximumWidth(150)
        voice_layout.addWidget(self.btn_preview_voice)

        self.btn_reload_voices = QPushButton("Recargar voces")
        self.btn_reload_voices.clicked.connect(self.reload_voices)
        self.btn_reload_voices.setMaximumWidth(130)
        voice_layout.addWidget(self.btn_reload_voices)

        layout.addLayout(voice_layout)

        # Estilo Recraft fijado a Photorealism — widget oculto para compatibilidad interna.
        self.recraft_styles = list(RECRAFT_STYLE_OPTIONS)
        self.fal_styles = self.recraft_styles
        self.leonardo_styles = self.recraft_styles

        self.style_combo = QComboBox()
        self.style_combo.addItems(self.recraft_styles)
        self.style_combo.setCurrentText("Photorealism")
        self.style_combo.setVisible(False)   # sin selector de estilo en la GUI

        # Proveedor de generaciÃ³n de imÃ¡genes
        image_provider_layout = QHBoxLayout()
        image_provider_layout.setSpacing(10)

        provider_label = QLabel("Proveedor de imagenes:")
        provider_label.setMinimumWidth(150)
        image_provider_layout.addWidget(provider_label)

        self.image_provider_combo = QComboBox()
        self.image_provider_combo.addItems([
            "Stability AI - Core (~$0.003)",
            "Stability AI - Ultra (~$0.008)",
            "Recraft AI",
            "FAL - Flux dev (calidad)",
            "FAL - Flux schnell (rapido)",
            "ComfyUI - FLUX Dev (alta calidad)",
            "ComfyUI - FLUX Schnell",
            "Manual (Gratuito)"
        ])
        self.image_provider_combo.setToolTip(
            "Selecciona el proveedor para generar imagenes:\n"
            "- Recraft AI: realistic_image, ~$0.04/img\n"
            "- FAL Flux dev: calidad superior, ~$0.025/img\n"
            "- FAL Flux schnell: rapido y barato, ~$0.003/img\n"
            "- ComfyUI FLUX Dev: alta calidad, 25 steps (requiere flux1-dev-fp8 en Vast.ai)\n"
            "- ComfyUI FLUX Schnell: rapido, 4 steps (COMFYUI_BASE_URL)\n"
            "- Stability Ultra: maxima calidad, ~$0.008/img (STABILITY_API_KEY)\n"
            "- Stability Core: buena calidad, ~$0.003/img (STABILITY_API_KEY)\n"
            "- Manual: genera prompts para usar externamente"
        )
        self.image_provider_combo.setMinimumWidth(200)
        self.image_provider_combo.currentIndexChanged.connect(self._on_image_provider_changed)
        image_provider_layout.addWidget(self.image_provider_combo)
        image_provider_layout.addStretch()

        layout.addLayout(image_provider_layout)
        self._on_image_provider_changed()

        # --- Proveedor de video (opcional: Image-to-Video con FAL Kling/Luma) ---
        video_provider_layout = QHBoxLayout()
        video_provider_layout.setSpacing(10)

        video_provider_label = QLabel("Proveedor de video:")
        video_provider_label.setMinimumWidth(150)
        video_provider_layout.addWidget(video_provider_label)

        self.video_provider_combo = QComboBox()
        self.video_provider_combo.addItems([
            "Ninguno (imagen estatica + Ken Burns)",
            "FAL - Kling v1.5 Standard (I2V)",
            "FAL - Kling v1.5 Pro (I2V)",
            "FAL - Luma Dream Machine (I2V)",
            "Runway Gen-3 / Veo",
        ])
        self.video_provider_combo.setToolTip(
            "Proveedor de video generativo (opcional):\n"
            "- Ninguno: usa solo la imagen estatica con Ken Burns (mas barato)\n"
            "- FAL Kling Standard: I2V con movimientos de camara, ~$0.48/clip 5s\n"
            "- FAL Kling Pro: I2V calidad alta, ~$0.95/clip 5s\n"
            "- FAL Luma: I2V optimo para particulas/fluidos, ~$0.50/clip 5s\n"
            "- Runway Gen-3: fallback T2V, requiere RUNWAYML_API_SECRET\n\n"
            "Nota: solo aplica a segmentos sin video asignado manualmente."
        )
        self.video_provider_combo.setMinimumWidth(200)
        video_provider_layout.addWidget(self.video_provider_combo)
        video_provider_layout.addStretch()

        layout.addLayout(video_provider_layout)

        # --- Preset rapido: Misterios historicos (@Stunning-Revelations) ---
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(10)
        preset_label = QLabel("Preset:")
        preset_label.setMinimumWidth(150)
        preset_layout.addWidget(preset_label)

        self.btn_preset_mysteries = QPushButton(" Preset de calidad (FAL Flux + Kling)")
        self.btn_preset_mysteries.setToolTip(
            "Configura el estudio para el canal @Stunning-Revelations:\n"
            "- Proveedor imagen: FAL Flux dev (calidad)\n"
            "- Proveedor video: FAL Kling Standard (I2V)\n"
            "- Prefijo de prompt: 'Historical mystery, cinematic lighting, 8k'\n"
            "- Estilo: Fotorealismo / moody atmosphere\n\n"
            "Ideal para generar Shorts diarios de misterios historicos."
        )
        self.btn_preset_mysteries.clicked.connect(self._apply_mysteries_preset)
        preset_layout.addWidget(self.btn_preset_mysteries)
        preset_layout.addStretch()

        layout.addLayout(preset_layout)

        # Ratio de imÃ¡genes por segmento (para reducir costos en videos largos)
        images_ratio_layout = QHBoxLayout()
        images_ratio_layout.setSpacing(10)  # Espaciado entre elementos

        freq_label = QLabel("Frecuencia de ImÃ¡genes:")
        freq_label.setMinimumWidth(150)
        images_ratio_layout.addWidget(freq_label)

        self.images_per_segment_spin = QSpinBox()
        self.images_per_segment_spin.setMinimum(1)
        self.images_per_segment_spin.setMaximum(10)
        self.images_per_segment_spin.setValue(1)
        self.images_per_segment_spin.setToolTip(
            "Controla cuÃ¡ntos segmentos comparten una misma imagen:\n"
            "â€¢ 1 = 1 imagen por segmento (comportamiento normal)\n"
            "â€¢ 2 = 1 imagen cada 2 segmentos (50% menos imÃ¡genes)\n"
            "â€¢ 3 = 1 imagen cada 3 segmentos (67% menos imÃ¡genes)\n"
            "â€¢ 4+ = MÃ¡s ahorro de costos para videos muy largos\n\n"
            "Ãštil para videos largos con muchos segmentos cortos.\n"
            "Cada imagen se mostrarÃ¡ durante mÃ¡s tiempo."
        )
        self.images_per_segment_spin.setFixedWidth(60)
        images_ratio_layout.addWidget(self.images_per_segment_spin)

        images_ratio_layout.addWidget(QLabel("segmentos por imagen"))
        images_ratio_layout.addStretch()

        layout.addLayout(images_ratio_layout)

        # Checkbox para intercalar imÃ¡genes IA con espacios vacÃ­os
        interleave_layout = QHBoxLayout()
        self.interleave_images_check = QCheckBox("Intercalar imagenes con espacios vacios")
        self.interleave_images_check.setChecked(False)
        self.interleave_images_check.setToolTip(
            "Genera imagenes solo en segmentos impares (1, 3, 5...).\n"
            "Los segmentos pares quedan vacios para completar manualmente\n"
            "desde el editor de timeline."
        )
        interleave_layout.addWidget(self.interleave_images_check)
        interleave_layout.addStretch()
        layout.addLayout(interleave_layout)

        # Modo visual
        visual_mode_layout = QHBoxLayout()
        visual_mode_layout.addWidget(QLabel("Modo Visual:"))

        self.visual_mode_group = QButtonGroup()
        self.visual_static = QRadioButton("EstÃ¡tico (Solo ImÃ¡genes)")
        self.visual_mixed = QRadioButton("Mixto (ImÃ¡genes + Videos)")
        self.visual_mixed.setChecked(True)
        self.visual_mode_group.addButton(self.visual_static)
        self.visual_mode_group.addButton(self.visual_mixed)
        self.visual_mode_group.buttonClicked.connect(self.update_cost_display)

        visual_mode_layout.addWidget(self.visual_static)
        visual_mode_layout.addWidget(self.visual_mixed)
        visual_mode_layout.addStretch()

        layout.addLayout(visual_mode_layout)

        # Nuevo: Efectos CinematogrÃ¡ficos
        cinematic_layout = QHBoxLayout()

        self.cinematic_check = QCheckBox("Efectos cinematograficos")
        self.cinematic_check.setChecked(True)
        self.cinematic_check.setToolTip(
            "Pan & Zoom dinÃ¡mico + Filtros contextuales + Transiciones inteligentes"
        )
        cinematic_layout.addWidget(self.cinematic_check)

        cinematic_layout.addWidget(QLabel("Preset:"))

        self.cinematic_preset_combo = QComboBox()
        self.cinematic_preset_combo.addItems([
            "Auto-Detect (Inteligente)",
            "Documentary (Suave)",
            "Action (Dinamico)",
            "Vintage (Sepia/B&W)",
            "Minimal (Limpio)",
            "Noir (Dramatico)"
        ])
        self.cinematic_preset_combo.setEnabled(
            self.cinematic_check.isChecked())
        self.cinematic_check.toggled.connect(
            lambda: self.cinematic_preset_combo.setEnabled(
                self.cinematic_check.isChecked())
        )
        self.cinematic_preset_combo.setToolTip(
            "Preset de efectos:\n"
            "â€¢ Auto: Detecta contexto y aplica efectos apropiados\n"
            "â€¢ Documentary: Pan suave + filtro cinematogrÃ¡fico\n"
            "â€¢ Action: Zoom rÃ¡pido + alto contraste\n"
            "â€¢ Vintage: Sepia/B&W para contenido histÃ³rico\n"
            "â€¢ Minimal: Solo movimientos, sin filtros\n"
            "â€¢ Noir: B&W + dramÃ¡tico para misterio/thriller"
        )
        self.cinematic_preset_combo.setMaximumWidth(250)  # Limitar ancho
        cinematic_layout.addWidget(self.cinematic_preset_combo)

        cinematic_layout.addStretch()

        # â† Corregido: aÃ±adir cinematic_layout
        layout.addLayout(cinematic_layout)

        # Nuevo: Transiciones Profesionales (tipo CapCut)
        transitions_layout = QHBoxLayout()

        transitions_label = QLabel("Transiciones:")
        transitions_layout.addWidget(transitions_label)

        self.transition_type_combo = QComboBox()
        self.transition_type_combo.addItems([
            "None (Direct Cut)",
            "Fade Smooth",
            "Crossfade",
            "Zoom Transition",
            "Slide Transition",
            "Blur Transition",
            "Dissolve",
            "Wipe",
            "Wipe Right",
            "Wipe Up",
            "Wipe Down",
            "Slide Right",
            "Slide Up",
            "Slide Down",
            "Fade to Black",
            "Fade to White",
            "Circle Open",
            "Circle Close",
            "Horizontal Open",
            "Horizontal Close",
            "Diagonal",
            "Squeeze H",
            "Squeeze V",
            "Digital Glitch",
            "RGB Split Glitch",
            "Data Mosh Glitch",
            "Film Burn (Overlay)",
        ])
        self.transition_type_combo.setCurrentIndex(1)  # Fade Smooth por defecto
        self.transition_type_combo.setToolTip(
            "Tipo de transicion entre escenas:\n"
            "- None: corte directo\n"
            "- Fade/Crossfade/Dissolve: transiciones suaves\n"
            "- Zoom/Slide/Wipe: transiciones de movimiento\n"
            "- Circle/Horizontal/Diagonal/Squeeze: transiciones geometricas\n"
            "- Digital/RGB/Data Mosh Glitch: efectos glitch estilo CapCut\n"
            "- Film Burn (Overlay): clip de video real superpuesto (light leak cinematografico)"
        )
        self.transition_type_combo.setMaximumWidth(250)
        transitions_layout.addWidget(self.transition_type_combo)

        transitions_layout.addWidget(QLabel("DuraciÃ³n:"))

        self.transition_duration_spin = QDoubleSpinBox()
        self.transition_duration_spin.setMinimum(0.1)
        self.transition_duration_spin.setMaximum(2.0)
        self.transition_duration_spin.setSingleStep(0.1)
        self.transition_duration_spin.setValue(0.5)  # 0.5 segundos por defecto
        self.transition_duration_spin.setSuffix(" s")
        self.transition_duration_spin.setToolTip(
            "DuraciÃ³n de la transiciÃ³n en segundos (0.1 - 2.0)")
        self.transition_duration_spin.setMinimumWidth(100)
        transitions_layout.addWidget(self.transition_duration_spin)

        transitions_layout.addStretch()

        layout.addLayout(transitions_layout)

        sfx_row = QHBoxLayout()
        self.transition_sfx_check = QCheckBox("Sonido de transicion")
        self.transition_sfx_check.setChecked(True)
        self.transition_sfx_check.setToolTip(
            "Agrega un whoosh/swoosh solo cuando cambia la imagen de escena.\n"
            "No se reproduce en cada frase del mismo still."
        )
        sfx_row.addWidget(self.transition_sfx_check)

        self.transition_sfx_combo = QComboBox()
        self.transition_sfx_combo.setMinimumWidth(180)
        self.transition_sfx_combo.setMaximumWidth(280)
        self.transition_sfx_combo.setToolTip("Archivo WAV usado en cada corte visual.")
        sfx_row.addWidget(self.transition_sfx_combo)

        self.btn_pick_transition_sfx = QPushButton("Elegir WAV...")
        self.btn_pick_transition_sfx.setMaximumWidth(120)
        self.btn_pick_transition_sfx.setToolTip("Usa un WAV propio (whoosh, riser, hit, etc.).")
        self.btn_pick_transition_sfx.clicked.connect(self._on_pick_transition_sfx)
        sfx_row.addWidget(self.btn_pick_transition_sfx)
        sfx_row.addStretch()
        layout.addLayout(sfx_row)

        self._populate_transition_sfx_combo()
        self.transition_sfx_check.toggled.connect(self._on_transition_sfx_toggled)
        self._on_transition_sfx_toggled(self.transition_sfx_check.isChecked())

        # Conectar cambios para actualizar preview automÃ¡ticamente
        # Nota: on_transition_changed no estÃ¡ implementado aÃºn, se puede agregar en el futuro
        # self.transition_type_combo.currentTextChanged.connect(
        #     self.on_transition_changed)
        # self.transition_duration_spin.valueChanged.connect(
        #     self.on_transition_changed)

        # Opciones adicionales - Reorganizado en mÃºltiples filas para reducir
        # ancho horizontal
        options_layout = QVBoxLayout()  # Cambiado a vertical

        # Primera fila: SubtÃ­tulos
        subtitles_row = QHBoxLayout()
        self.subtitles_check = QCheckBox("Subtitulos dinamicos")
        self.subtitles_check.setChecked(True)
        self.subtitles_check.stateChanged.connect(self.update_cost_display)
        self.subtitles_check.setToolTip(
            "SubtÃ­tulos palabra por palabra con animaciones")
        subtitles_row.addWidget(self.subtitles_check)

        # Selector de estilo de subtÃ­tulos
        subtitle_style_label = QLabel("Estilo:")
        subtitle_style_label.setEnabled(self.subtitles_check.isChecked())
        self.subtitles_check.stateChanged.connect(
            lambda: subtitle_style_label.setEnabled(
                self.subtitles_check.isChecked())
        )
        subtitles_row.addWidget(subtitle_style_label)

        self.subtitle_style_combo = QComboBox()
        self.subtitle_style_combo.addItems([
            "ðŸ”¥ Hormozi (Amarillo + Karaoke + Emojis)",
            "ðŸ’° MrBeast (Verde Pop + Emojis)",
            "ðŸ“± TikTok (Shake + Viral)",
            "PRO â€¢ CapCut Creator (Clean Pop)",
            "PRO â€¢ CapCut Kinetic (Bold Zoom)",
            "PRO â€¢ CapCut Focus (Center Highlight)",
            "PRO â€¢ CapCut Podcast (Lower Third)",
            "PRO â€¢ CapCut Luxury (Gold Editorial)",
            "ðŸŽ¨ Minimalista (Limpio)",
            "ðŸ“º Documental (ClÃ¡sico)",
            "ðŸŽ® Gaming/Streaming (Verde + Pop)",
            "ðŸ“° Noticiero (Profesional)",
            "ðŸŽ¬ CinematogrÃ¡fico (Elegante)",
            "ðŸ’œ NeÃ³n (Magenta + Shake)",
            "ðŸ•¹ï¸ Retro 80s (Cyan + Pop)",
            "ðŸ‘” Elegante (Refinado)",
            "ðŸ’¥ Bold/Impact (Impactante)",
            "ðŸ’€ Horror/Terror (Rojo + Shake)",
            "âŒ¨️ Typewriter (MÃ¡quina de escribir)",
            "ðŸ”¥ Fuego/Fire (Naranja + Bounce)",
            "️ Hielo/Ice (Azul helado)",
            "ðŸ’¢ Comic/Cartoon (Pop + Emojis)",
            "ðŸŽ¤ Karaoke Party (Magenta + Bounce)",
            "ðŸ’¬ WhatsApp/Chat (Verde chat)",
            "ðŸ¤– Glitch/Cyberpunk (Verde terminal)",
            "️ Manuscrito/Handwritten (Papel)",
            "ðŸŽµ Spotify/Music (Verde Spotify)",
            "ðŸŽ–️ Militar/Tactical (Naranja militar)",
        ])
        self.subtitle_style_combo.setEnabled(self.subtitles_check.isChecked())
        self.subtitles_check.stateChanged.connect(
            lambda: self.subtitle_style_combo.setEnabled(
                self.subtitles_check.isChecked())
        )
        self.subtitle_style_combo.setToolTip(
            "SubtÃ­tulos DinÃ¡micos Pro:\n"
            "â€¢ Animaciones palabra por palabra\n"
            "â€¢ Efecto karaoke (resaltado)\n"
            "â€¢ Emojis automÃ¡ticos contextuales\n"
            "â€¢ Quemados con FFmpeg (calidad perfecta)"
        )
        self.subtitle_style_combo.setMaximumWidth(300)  # Limitar ancho
        subtitles_row.addWidget(self.subtitle_style_combo)

        # Vista previa animada al elegir estilo. Se usa `activated` y NO
        # `currentIndexChanged`: el primero solo dispara cuando el usuario
        # toca el combo, asi que restaurar un proyecto no abre la ventana.
        self.subtitle_style_combo.activated.connect(
            self.show_subtitle_style_preview)

        self.btn_subtitle_preview = QPushButton("Ver ejemplos")
        self.btn_subtitle_preview.setToolTip(
            "Muestra una animacion de ejemplo de cada estilo de subtitulos, "
            "generada con el mismo motor que usa el video final.")
        self.btn_subtitle_preview.setMaximumWidth(120)
        self.btn_subtitle_preview.setEnabled(self.subtitles_check.isChecked())
        self.btn_subtitle_preview.clicked.connect(
            lambda: self.show_subtitle_style_preview(None))
        self.subtitles_check.stateChanged.connect(
            lambda: self.btn_subtitle_preview.setEnabled(
                self.subtitles_check.isChecked())
        )
        subtitles_row.addWidget(self.btn_subtitle_preview)

        subtitles_row.addStretch()
        options_layout.addLayout(subtitles_row)

        # Segunda fila: Checkboxes bÃ¡sicos
        checkboxes_row1 = QHBoxLayout()
        self.research_check = QCheckBox("Investigacion web")
        self.research_check.setChecked(True)
        checkboxes_row1.addWidget(self.research_check)

        self.auto_save_check = QCheckBox("Guardar automÃ¡ticamente despuÃ©s de cada paso")
        self.auto_save_check.setToolTip("Guarda automÃ¡ticamente el proyecto despuÃ©s de completar cada paso importante")
        self.auto_save_check.setChecked(True)
        self.auto_save_check.stateChanged.connect(self._on_auto_save_changed)
        QTimer.singleShot(100, self._sync_auto_save_state)
        checkboxes_row1.addWidget(self.auto_save_check)

        # BotÃ³n para abrir buscador de mÃºsica
        self.btn_music_browser = QPushButton("AÃ±adir musica")
        self.btn_music_browser.setToolTip(
            "Abre el buscador de mÃºsica para aÃ±adir pistas a la playlist (se reproducirÃ¡n en orden)")
        self.btn_music_browser.clicked.connect(self.show_music_browser)
        checkboxes_row1.addWidget(self.btn_music_browser)

        # BotÃ³n para limpiar mÃºsica
        self.btn_clear_music = QPushButton("Limpiar mÃºsica")
        self.btn_clear_music.setToolTip("Elimina la mÃºsica seleccionada")
        self.btn_clear_music.clicked.connect(self.clear_selected_music)
        checkboxes_row1.addWidget(self.btn_clear_music)

        # Label para mostrar la pista seleccionada
        self.selected_music_label = QLabel("Pista seleccionada: Ninguna")
        self.selected_music_label.setStyleSheet("color: #14a085; font-style: italic;")
        self.selected_music_label.setWordWrap(True)
        checkboxes_row1.addWidget(self.selected_music_label)

        checkboxes_row1.addStretch()
        options_layout.addLayout(checkboxes_row1)

        # Lista para almacenar mÃºsica seleccionada manualmente como playlist
        self.selected_music_paths = []
        self.selected_music_path = None  # Compatible backend point
        # Metadatos de la mÃºsica seleccionada
        self.selected_music_metadata = None

        options_layout.addStretch()
        layout.addLayout(options_layout)

        return group

    def create_cost_section(self):
        """Crea la secciÃ³n de costos"""
        group = QGroupBox("Estimacion de costos")
        layout = QVBoxLayout(group)

        # Resumen de costos
        summary_layout = QHBoxLayout()

        self.cost_label = QLabel("Costo total: $0.0000")
        self.cost_label.setStyleSheet(
            "font-size: 14pt; font-weight: bold; color: #14a085;")
        summary_layout.addWidget(self.cost_label)

        summary_layout.addStretch()

        self.time_label = QLabel("Tiempo estimado: ~0 min")
        self.time_label.setStyleSheet("font-weight: bold;")
        summary_layout.addWidget(self.time_label)

        layout.addLayout(summary_layout)

        # Nota del modo
        self.cost_note_label = QLabel("")
        self.cost_note_label.setStyleSheet(
            "color: #a0a0a0; font-style: italic;")
        layout.addWidget(self.cost_note_label)

        # Desglose
        self.cost_breakdown = QTextEdit()
        self.cost_breakdown.setReadOnly(True)
        self.cost_breakdown.setMaximumHeight(100)
        self.cost_breakdown.setStyleSheet(
            "background-color: #ffffff; color: #2f3b47; border: 1px solid #dde3e9; font-size: 9pt;")
        layout.addWidget(self.cost_breakdown)

        return group

    def create_control_panel(self):
        """Crea el panel de control con los 3 botones principales"""
        group = QGroupBox("Pipeline de generacion")
        layout = QHBoxLayout(group)

        # Paso 1: Storyboard
        self.btn_storyboard = QPushButton(
            "1. Generar storyboard")
        self.btn_storyboard.setObjectName("accent")
        self.btn_storyboard.setMinimumHeight(60)
        self.btn_storyboard.clicked.connect(self.generate_storyboard)
        layout.addWidget(self.btn_storyboard)

        # Paso 2: Generar imagenes
        self.btn_generate_images = QPushButton(
            "2. Generar imagenes")
        self.btn_generate_images.setObjectName("warning")
        self.btn_generate_images.setMinimumHeight(60)
        self.btn_generate_images.setEnabled(False)
        self.btn_generate_images.clicked.connect(self.generate_images)
        layout.addWidget(self.btn_generate_images)

        self.btn_export_recraft_prompts = QPushButton("TXT prompts Recraft")
        self.btn_export_recraft_prompts.setObjectName("info")
        self.btn_export_recraft_prompts.setMinimumHeight(60)
        self.btn_export_recraft_prompts.setEnabled(False)
        self.btn_export_recraft_prompts.setToolTip(
            "Exporta un TXT con los prompts finales que se enviarían a Recraft.\n\n"
            "Útil para pedir las imágenes manualmente si la API no está disponible."
        )
        self.btn_export_recraft_prompts.clicked.connect(self.export_recraft_prompts_txt)
        layout.addWidget(self.btn_export_recraft_prompts)

        # Paso 3: Ensamblar
        self.btn_assemble = QPushButton(
            "3. Ensamblar video")
        self.btn_assemble.setObjectName("success")
        self.btn_assemble.setMinimumHeight(60)
        self.btn_assemble.setEnabled(False)
        self.btn_assemble.clicked.connect(self.assemble_video)
        layout.addWidget(self.btn_assemble)

        # Boton adicional: generar teaser corto
        self.btn_generate_teaser = QPushButton("Generar teaser corto")
        self.btn_generate_teaser.setObjectName("warning")
        self.btn_generate_teaser.setMinimumHeight(50)
        self.btn_generate_teaser.setEnabled(False)
        self.btn_generate_teaser.setToolTip(
            "Genera un Short Teaser (30-60s) en formato vertical 9:16\n"
            "a partir del video largo ya generado.\n\n"
            "Requiere que el video principal ya estÃ© ensamblado."
        )
        self.btn_generate_teaser.clicked.connect(
            self.generate_short_teaser_manual)
        layout.addWidget(self.btn_generate_teaser)

        # Boton para reproducir el video generado localmente
        self.btn_play_video = QPushButton("Reproducir video")
        self.btn_play_video.setObjectName("accent")
        self.btn_play_video.setMinimumHeight(50)
        self.btn_play_video.setEnabled(False)
        self.btn_play_video.setToolTip(
            "Abre el último video generado con el reproductor predeterminado del sistema."
        )
        self.btn_play_video.clicked.connect(self.play_generated_video)
        layout.addWidget(self.btn_play_video)

        # Seccion de publicacion
        publish_label = QLabel("Publicar en:")
        publish_label.setStyleSheet("color: #aaa; font-size: 11px; margin-top: 6px;")
        layout.addWidget(publish_label)

        publish_checks_layout = QHBoxLayout()
        publish_checks_layout.setSpacing(6)
        self.chk_publish_youtube = QCheckBox("YouTube")
        self.chk_publish_facebook = QCheckBox("Facebook")
        self.chk_publish_instagram = QCheckBox("Instagram")
        self.chk_publish_x = QCheckBox("X")
        self.chk_publish_x.setToolTip(
            "Publica el video en X (Twitter) con las credenciales TWITTER_* del .env.\n"
            "Verificalas antes con: .venv\\Scripts\\python.exe x_video_uploader.py --check"
        )
        for chk in (self.chk_publish_youtube, self.chk_publish_facebook,
                    self.chk_publish_instagram, self.chk_publish_x):
            chk.setEnabled(True)
            chk.setStyleSheet("font-size: 11px;")
            publish_checks_layout.addWidget(chk)
        layout.addLayout(publish_checks_layout)
        
        # Schedule layout
        self.chk_schedule_youtube = QCheckBox("Programar (YT)")
        self.chk_schedule_youtube.setStyleSheet("font-size: 11px;")
        self.chk_schedule_youtube.setEnabled(True)
        
        from PyQt6.QtWidgets import QDateTimeEdit, QVBoxLayout
        from PyQt6.QtCore import QDateTime
        self.dt_schedule_youtube = QDateTimeEdit(QDateTime.currentDateTime().addDays(1))
        self.dt_schedule_youtube.setCalendarPopup(True)
        self.dt_schedule_youtube.setEnabled(False)
        self.dt_schedule_youtube.setStyleSheet("font-size: 11px;")
        self.chk_schedule_youtube.toggled.connect(self.dt_schedule_youtube.setEnabled)
        
        self.chk_schedule_facebook = QCheckBox("Programar (FB)")
        self.chk_schedule_facebook.setStyleSheet("font-size: 11px;")
        self.chk_schedule_facebook.setEnabled(True)
        
        self.dt_schedule_facebook = QDateTimeEdit(QDateTime.currentDateTime().addDays(1))
        self.dt_schedule_facebook.setCalendarPopup(True)
        self.dt_schedule_facebook.setEnabled(False)
        self.dt_schedule_facebook.setStyleSheet("font-size: 11px;")
        self.chk_schedule_facebook.toggled.connect(self.dt_schedule_facebook.setEnabled)

        schedule_vbox = QVBoxLayout()
        
        yt_row = QHBoxLayout()
        yt_row.addWidget(self.chk_schedule_youtube)
        yt_row.addWidget(self.dt_schedule_youtube)
        yt_row.addStretch()
        
        fb_row = QHBoxLayout()
        fb_row.addWidget(self.chk_schedule_facebook)
        fb_row.addWidget(self.dt_schedule_facebook)
        fb_row.addStretch()
        
        schedule_vbox.addLayout(yt_row)
        schedule_vbox.addLayout(fb_row)
        layout.addLayout(schedule_vbox)

        self.btn_publish = QPushButton("Publicar video")
        self.btn_publish.setObjectName("success")
        self.btn_publish.setMinimumHeight(44)
        self.btn_publish.setEnabled(True)
        self.btn_publish.setToolTip(
            "Sube el video generado a las plataformas seleccionadas.\n"
            "Requiere que el video ya esté ensamblado."
        )
        self.btn_publish.clicked.connect(self.publish_video_to_platforms)
        layout.addWidget(self.btn_publish)

        # Boton para cambiar voz de narracion
        self.btn_change_voice = QPushButton("Cambiar voz de narracion")
        self.btn_change_voice.setObjectName("info")
        self.btn_change_voice.setMinimumHeight(50)
        self.btn_change_voice.setEnabled(False)
        self.btn_change_voice.setToolTip(
            "Regenera el audio del video con una voz diferente.\n\n"
            "Permite cambiar la voz de narraciÃ³n sin tener que\n"
            "regenerar las imÃ¡genes ni el storyboard.\n\n"
            "Requiere que el proyecto ya estÃ© cargado."
        )
        self.btn_change_voice.clicked.connect(self.change_voice_narration)
        layout.addWidget(self.btn_change_voice)

        # Separador visual
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("background-color: #3d3d3d;")
        layout.addWidget(separator)

        # Botones de gestiÃ³n de proyectos
        projects_layout = QVBoxLayout()
        projects_layout.setSpacing(5)

        self.btn_load_project = QPushButton("Cargar proyecto")
        self.btn_load_project.setMinimumHeight(40)
        self.btn_load_project.setToolTip(
            "Carga un proyecto guardado para continuar desde donde quedaste")
        self.btn_load_project.clicked.connect(self.load_project)
        projects_layout.addWidget(self.btn_load_project)

        self.btn_manage_projects = QPushButton("Gestionar proyectos")
        self.btn_manage_projects.setMinimumHeight(40)
        self.btn_manage_projects.setToolTip(
            "Ver lista de proyectos, informaciÃ³n y eliminar proyectos")
        self.btn_manage_projects.clicked.connect(self.manage_projects)
        projects_layout.addWidget(self.btn_manage_projects)

        # Auto-guardado siempre habilitado
        self.auto_save_enabled = True

        layout.addLayout(projects_layout)

        return group

    def create_manual_prompt_section(self):
        """Crea la sección para generar guión manualmente con IA externa"""
        group = QGroupBox("Guión manual (IA externa)")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        info = QLabel(
            "Genera un prompt avanzado, cópialo a una IA externa (Claude, ChatGPT, etc.), "
            "y pega el JSON de respuesta aquí para procesarlo como storyboard."
        )
        info.setStyleSheet("color: #6f7c89; padding: 4px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Botones de acción
        btn_row = QHBoxLayout()

        self.btn_gen_prompt = QPushButton("Generar prompt")
        self.btn_gen_prompt.setObjectName("accent")
        self.btn_gen_prompt.setToolTip(
            "Genera un prompt avanzado basado en el tema, duración y fuentes\n"
            "de investigación seleccionadas en la pestaña Análisis."
        )
        self.btn_gen_prompt.clicked.connect(self._generate_manual_prompt)
        btn_row.addWidget(self.btn_gen_prompt)

        self.btn_copy_prompt = QPushButton("Copiar prompt")
        self.btn_copy_prompt.setEnabled(False)
        self.btn_copy_prompt.clicked.connect(self._copy_prompt_to_clipboard)
        btn_row.addWidget(self.btn_copy_prompt)

        self.btn_gen_json_internal = QPushButton("Generar JSON (IA interna)")
        self.btn_gen_json_internal.setObjectName("warning")
        self.btn_gen_json_internal.setToolTip(
            "Genera el JSON completo usando Groq en batches internos.\n"
            "Evita el límite de tokens de salida para videos largos.\n"
            "El resultado se coloca automáticamente en el área de abajo."
        )
        self.btn_gen_json_internal.clicked.connect(self._generate_json_internal)
        btn_row.addWidget(self.btn_gen_json_internal)

        self.btn_process_json = QPushButton("Procesar JSON")
        self.btn_process_json.setObjectName("success")
        self.btn_process_json.setEnabled(False)
        self.btn_process_json.setToolTip(
            "Procesa el JSON pegado: genera audio, crea segmentos y arma el storyboard."
        )
        self.btn_process_json.clicked.connect(self._process_manual_json)
        btn_row.addWidget(self.btn_process_json)

        layout.addLayout(btn_row)

        # Área de prompt generado (colapsada por defecto)
        self.manual_prompt_text = QTextEdit()
        self.manual_prompt_text.setReadOnly(True)
        self.manual_prompt_text.setPlaceholderText(
            "El prompt generado aparecerá aquí. Pulsa 'Generar prompt' para comenzar.")
        self.manual_prompt_text.setFixedHeight(150)
        self.manual_prompt_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e2e; color: #cdd6f4; "
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 11px; "
            "border: 1px solid #45475a; border-radius: 4px; padding: 6px; }")
        layout.addWidget(self.manual_prompt_text)

        # Separador
        sep_label = QLabel("⬇ Pega aquí el JSON que te devolvió la IA externa ⬇")
        sep_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep_label.setStyleSheet("color: #89b4fa; font-weight: bold; padding: 4px;")
        layout.addWidget(sep_label)

        # Área para pegar JSON
        self.manual_json_input = QTextEdit()
        self.manual_json_input.setPlaceholderText(
            '{\n  "title": "...",\n  "scenes": [\n    {\n'
            '      "narration": "...",\n      "visual_prompt": "...",\n'
            '      "sfx_tag": "none",\n      "overlay_tag": "none"\n'
            '    }\n  ]\n}')
        self.manual_json_input.setFixedHeight(150)
        self.manual_json_input.setStyleSheet(
            "QTextEdit { background-color: #1e1e2e; color: #a6e3a1; "
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 11px; "
            "border: 1px solid #45475a; border-radius: 4px; padding: 6px; }")
        self.manual_json_input.textChanged.connect(
            lambda: self.btn_process_json.setEnabled(
                len(self.manual_json_input.toPlainText().strip()) > 10))
        layout.addWidget(self.manual_json_input)

        return group

    def _generate_manual_prompt(self):
        """Genera el prompt avanzado para copiar a una IA externa"""
        topic = self.parent_gui.topic_input.text().strip()
        if not topic:
            QMessageBox.warning(self, "Sin tema",
                "Ingresa un tema en la pestaña Análisis primero.")
            return

        category = self.parent_gui.category_combo.currentText()
        duration = self.duration_slider.value()
        language = 'es' if self.lang_es.isChecked() else 'en'
        video_format = self.get_selected_video_format()

        # Obtener contexto de investigación pre-seleccionado
        research_context = []
        if hasattr(self.parent_gui, 'get_selected_research_context'):
            research_context = self.parent_gui.get_selected_research_context()

        # Generar el prompt
        if hasattr(self, 'generator') and self.generator:
            gen = self.generator._generator if hasattr(self.generator, '_generator') else self.generator
            prompt = gen.generate_manual_prompt_text(
                topic, category, duration, language=language,
                research_context=research_context,
                video_format=video_format,
                platform=self.get_selected_platform_key())
        else:
            prompt = (f"No se pudo generar el prompt: generador no disponible.\n"
                     f"Tema: {topic}\nCategoría: {category}\nDuración: {duration}s")

        self.manual_prompt_text.setPlainText(prompt)
        self.btn_copy_prompt.setEnabled(True)

        src_count = len(research_context)
        self.log(f" Prompt manual generado para: {topic} ({duration}s, {src_count} fuentes)")

    def _copy_prompt_to_clipboard(self):
        """Copia el prompt generado al portapapeles"""
        text = self.manual_prompt_text.toPlainText()
        if text:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.log(" Prompt copiado al portapapeles")

    def _generate_json_internal(self):
        """Genera el JSON completo de escenas via Groq en batches y lo coloca en el área de texto."""
        from PyQt6.QtCore import QThread, pyqtSignal

        topic = self.parent_gui.topic_input.text().strip()
        if not topic:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Sin tema", "Ingresa un tema en la pestaña Análisis primero.")
            return

        category = self.parent_gui.category_combo.currentText()
        duration = self.duration_slider.value()
        language = 'es' if self.lang_es.isChecked() else 'en'
        video_format = self.get_selected_video_format()
        platform = self.get_selected_platform_key()

        research_context = []
        if hasattr(self.parent_gui, 'get_selected_research_context'):
            research_context = self.parent_gui.get_selected_research_context()

        gen = None
        if hasattr(self, 'generator') and self.generator:
            gen = self.generator._generator if hasattr(self.generator, '_generator') else self.generator
        if not gen:
            self.log("  Error: generador no disponible para IA interna.")
            return

        self.btn_gen_json_internal.setEnabled(False)
        self.btn_gen_json_internal.setText("Generando JSON...")
        self.log(f" Generando JSON en batches para: {topic} ({duration}s)...")

        class _JsonBatchThread(QThread):
            done = pyqtSignal(object)
            progress = pyqtSignal(int, int)

            def __init__(self, generator, topic, category, duration, language,
                         research_context, video_format, platform):
                super().__init__()
                self._gen = generator
                self._topic = topic
                self._category = category
                self._duration = duration
                self._language = language
                self._research = research_context
                self._fmt = video_format
                self._platform = platform

            def run(self):
                try:
                    result = self._gen.generate_scenes_json_batched(
                        self._topic, self._category, self._duration,
                        language=self._language,
                        research_context=self._research,
                        video_format=self._fmt,
                        platform=self._platform,
                        progress_callback=lambda cur, tot: self.progress.emit(cur, tot)
                    )
                    self.done.emit(result)
                except Exception as e:
                    print(f"[JsonBatchThread] Error: {e}")
                    self.done.emit(None)

        self._json_batch_thread = _JsonBatchThread(
            gen, topic, category, duration, language,
            research_context, video_format, platform
        )

        def _on_progress(cur, tot):
            self.btn_gen_json_internal.setText(f"Generando batch {cur}/{tot}...")

        def _on_done(result):
            self.btn_gen_json_internal.setEnabled(True)
            self.btn_gen_json_internal.setText("Generar JSON (IA interna)")
            if not result:
                self.log("  Error: no se pudo generar el JSON.")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Error", "No se pudo generar el JSON. Revisa el log para más detalles.")
                return
            import json as _json
            try:
                json_str = _json.dumps(result, ensure_ascii=False, indent=2)
            except Exception as e:
                self.log(f"  Error serializando JSON: {e}")
                return
            self.manual_json_input.setPlainText(json_str)
            scene_count = len(result.get('scenes', []))
            self.log(f"  JSON generado: {scene_count} escenas. Revisa y pulsa 'Procesar JSON'.")

        self._json_batch_thread.progress.connect(_on_progress)
        self._json_batch_thread.done.connect(_on_done)
        self._json_batch_thread.start()

    def _process_manual_json(self):
        """Procesa el JSON pegado por el usuario como storyboard"""
        raw_json = self.manual_json_input.toPlainText().strip()
        if not raw_json:
            QMessageBox.warning(self, "JSON vacío",
                "Pega el JSON de respuesta de la IA externa primero.")
            return

        # Intentar parsear JSON
        import json
        try:
            try:
                import json_repair
                json_data = json_repair.repair_json(raw_json, return_objects=True)
            except ImportError:
                clean = raw_json.replace("```json", "").replace("```", "").strip()
                start = clean.find('{')
                end = clean.rfind('}') + 1
                if start >= 0 and end > start:
                    clean = clean[start:end]
                json_data = json.loads(clean)
        except Exception as e:
            QMessageBox.critical(self, "Error JSON",
                f"No se pudo parsear el JSON:\n{str(e)}\n\n"
                "Asegúrate de que sea un JSON válido con la estructura requerida.")
            return

        if not isinstance(json_data, dict) or 'scenes' not in json_data:
            QMessageBox.critical(self, "JSON inválido",
                "El JSON debe tener la clave 'scenes' con una lista de escenas.\n\n"
                'Estructura: {"title": "...", "scenes": [{...}]}')
            return

        scene_count = len(json_data.get('scenes', []))
        self.log(f" JSON manual recibido: {json_data.get('title', 'Sin título')} ({scene_count} escenas)")

        # Obtener parámetros
        language = 'es' if self.lang_es.isChecked() else 'en'
        selected_voice = self.voice_combo.currentText()
        voice_id = self.elevenlabs_voices.get(selected_voice, {}).get('id')

        # Deshabilitar botones durante procesamiento
        self.btn_process_json.setEnabled(False)
        self.btn_storyboard.setEnabled(False)
        self._show_progress_indicator()

        # Lanzar worker
        from auto_video_generator_pyqt6_adapter import VideoGenerationWorker
        self.current_worker = VideoGenerationWorker(self.generator, "manual_json")
        voice_rate = self.get_selected_voice_rate()
        # Calcular max_duration según plataforma: 180s solo para short-form vertical.
        platform_key = self.get_selected_platform_key()
        max_duration = 180.0 if self._is_short_form_platform_key(platform_key) else 0
        self.current_worker.set_params(
            json_data=json_data,
            voice_id=voice_id,
            language=language,
            rate=voice_rate,
            max_duration=max_duration
        )
        self._bind_current_worker_to_project()

        self.current_thread = QThread()
        self.current_worker.moveToThread(self.current_thread)
        self.current_thread.started.connect(self.current_worker.run)
        self.current_worker.finished.connect(self.on_storyboard_finished)
        self.current_worker.error.connect(self._on_manual_json_error)
        self.current_worker.progress.connect(self.log)
        self.current_thread.start()

    def _on_manual_json_error(self, error_msg):
        """Error al procesar JSON manual"""
        if not self._should_accept_current_worker_callback():
            self.log("️ Error de JSON manual obsoleto ignorado.")
            return
        self.btn_process_json.setEnabled(True)
        self.btn_storyboard.setEnabled(True)
        self._hide_progress_indicator()
        self.log(f" Error procesando JSON manual: {error_msg}")
        QMessageBox.critical(self, "Error", f"Error procesando JSON:\n{error_msg}")

    def create_review_panel(self):
        """Crea el panel de revisiÃ³n con botÃ³n para abrir Timeline Editor"""
        group = QGroupBox("Editor de timeline")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        info = QLabel(
            "Cuando ya exista storyboard, puedes abrir el timeline en una ventana separada.\n"
            "Desde ahi podras editar segmentos, reordenar clips y ajustar tiempos con mas espacio."
        )
        info.setStyleSheet("color: #6f7c89; padding: 8px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # BotÃ³n para abrir Timeline Editor en ventana separada
        self.btn_open_timeline = QPushButton("Abrir editor de timeline")
        self.btn_open_timeline.setObjectName("accent")
        self.btn_open_timeline.clicked.connect(self.open_timeline_editor)
        # Deshabilitado hasta que haya storyboard
        self.btn_open_timeline.setEnabled(False)
        layout.addWidget(self.btn_open_timeline)

        # Inicializar timeline_editor_window como None
        self.timeline_editor_window = None

        # Variable para recordar la voz a seleccionar cuando las voces estÃ©n cargadas
        self.pending_voice_selection = None

        return group

    def create_thumbnail_intelligence_section(self):
        """Panel de miniaturas: 9:16 para Shorts, 16:9 para vertical largo."""
        group = QGroupBox("Hook Thumbnail (Watch Time)")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        info = QLabel(
            "Genera automaticamente variantes 16:9 para videos verticales largos. "
            "El sistema analiza el guion, propone hooks de maximo 3 palabras y compone "
            "miniaturas listas para el wizard de subida."
        )
        info.setStyleSheet("color: #6f7c89; padding: 4px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        controls_row = QHBoxLayout()
        self.btn_generate_hook_thumbnails = QPushButton("Generar miniaturas hook")
        self.btn_generate_hook_thumbnails.setObjectName("accent")
        self.btn_generate_hook_thumbnails.clicked.connect(self.generate_watchtime_thumbnails)
        controls_row.addWidget(self.btn_generate_hook_thumbnails)

        self.thumbnail_variant_combo = QComboBox()
        self.thumbnail_variant_combo.setMinimumWidth(240)
        self.thumbnail_variant_combo.setEnabled(False)
        self.thumbnail_variant_combo.currentIndexChanged.connect(self._on_thumbnail_variant_changed)
        controls_row.addWidget(self.thumbnail_variant_combo)

        self.btn_open_selected_thumbnail = QPushButton("Abrir seleccionada")
        self.btn_open_selected_thumbnail.setEnabled(False)
        self.btn_open_selected_thumbnail.clicked.connect(self.open_selected_thumbnail)
        controls_row.addWidget(self.btn_open_selected_thumbnail)

        self.btn_generate_super_prompt = QPushButton("Generar Super Prompt (IA externa)")
        self.btn_generate_super_prompt.setToolTip(
            "Usa el LLM para generar el [POSITIVE PROMPT] y [NEGATIVE PROMPT] listos para "
            "pegar directamente en Midjourney, DALL-E, Stable Diffusion, etc."
        )
        self.btn_generate_super_prompt.clicked.connect(self.generate_super_prompt_for_external_ai)
        controls_row.addWidget(self.btn_generate_super_prompt)

        # Con esto tildado el prompt le pide a la IA externa que ESCRIBA el
        # titular en la imagen. Sin tildar, deja el hueco libre y el texto se
        # superpone despues con el compositor.
        self.chk_super_prompt_text = QCheckBox("La IA escribe el texto")
        self.chk_super_prompt_text.setChecked(True)
        self.chk_super_prompt_text.setToolTip(
            "Tildado: el prompt incluye el titular entre comillas y las directivas de\n"
            "tipografia para que la IA externa lo dibuje sobre la miniatura.\n"
            "Sin tildar: pide la imagen limpia y el texto se compone despues aca."
        )
        controls_row.addWidget(self.chk_super_prompt_text)
        
        self.btn_load_external_thumbnail = QPushButton("Cargar externa...")
        self.btn_load_external_thumbnail.setToolTip("Cargar miniatura generada en una IA externa para que se publique con el video.")
        self.btn_load_external_thumbnail.clicked.connect(self.load_external_thumbnail)
        controls_row.addWidget(self.btn_load_external_thumbnail)

        self.btn_add_text_to_thumbnail = QPushButton("Agregar texto al thumbnail")
        self.btn_add_text_to_thumbnail.setToolTip(
            "Superpone el texto del hook sobre la miniatura cargada o generada."
        )
        self.btn_add_text_to_thumbnail.setEnabled(False)
        self.btn_add_text_to_thumbnail.clicked.connect(self.add_text_to_loaded_thumbnail)
        controls_row.addWidget(self.btn_add_text_to_thumbnail)

        controls_row.addStretch()
        layout.addLayout(controls_row)

        self.thumbnail_status_label = QLabel("Disponible cuando el formato sea 9:16 vertical largo.")
        self.thumbnail_status_label.setStyleSheet("color: #1f2831; font-weight: 600;")
        self.thumbnail_status_label.setWordWrap(True)
        layout.addWidget(self.thumbnail_status_label)

        self.thumbnail_hook_label = QLabel("Hook seleccionado: -")
        self.thumbnail_hook_label.setStyleSheet("color: #6f7c89;")
        self.thumbnail_hook_label.setWordWrap(True)
        layout.addWidget(self.thumbnail_hook_label)

        self.thumbnail_preview = QLabel("La miniatura seleccionada se mostrara aqui")
        self.thumbnail_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_preview.setMinimumSize(360, 202)
        self.thumbnail_preview.setStyleSheet(
            "QLabel { background-color: #ffffff; border: 1px solid #dde3e9; "
            "border-radius: 6px; color: #6f7c89; }"
        )
        layout.addWidget(self.thumbnail_preview)

        self.thumbnail_panel = group
        self._refresh_thumbnail_module_state()
        return group

    # Plataformas que aceptan miniatura propia. YouTube habilito las
    # miniaturas de Shorts el 2026-07-24; hasta entonces este modulo solo
    # tenia sentido para el vertical largo, y por eso estaba restringido.
    # El FORMATO de la miniatura lo decide `thumbnail_formats.resolve_format`
    # a partir de la plataforma: un Short la lleva 9:16 y un vertical largo
    # la lleva 16:9, porque ese va al feed normal de YouTube.
    THUMBNAIL_PLATFORMS = ('youtube_vertical', 'youtube_short')

    def _supports_custom_thumbnail(self) -> bool:
        return self.get_selected_platform_key() in self.THUMBNAIL_PLATFORMS

    # Alias historico: el nombre viejo sugeria que solo servia para
    # watch time, que ya no es el caso.
    _is_watchtime_thumbnail_target = _supports_custom_thumbnail

    def _refresh_thumbnail_module_state(self):
        """Activa o desactiva el modulo segun el formato y el estado del proyecto."""
        is_watchtime_target = self._supports_custom_thumbnail()
        has_storyboard = bool(self.last_storyboard_data and self.last_storyboard_data.get('segments'))
        is_generating = bool(self.thumbnail_thread and self.thumbnail_thread.isRunning())
        recommended_variant_id = None
        recommended_reason = None
        niche_label = None
        if isinstance(self.thumbnail_data, dict):
            recommended_variant_id = self.thumbnail_data.get('recommended_variant_id')
            recommended_reason = self.thumbnail_data.get('recommended_reason')
            strategy = self.thumbnail_data.get('thumbnail_strategy') or {}
            niche_label = strategy.get('niche_label') or strategy.get('niche_profile')

        if hasattr(self, 'btn_generate_hook_thumbnails'):
            self.btn_generate_hook_thumbnails.setEnabled(
                is_watchtime_target and has_storyboard and not is_generating
            )

        if hasattr(self, 'thumbnail_variant_combo'):
            self.thumbnail_variant_combo.setEnabled(bool(self.thumbnail_variants))

        if hasattr(self, 'btn_open_selected_thumbnail'):
            self.btn_open_selected_thumbnail.setEnabled(bool(self.selected_thumbnail_path))

        if hasattr(self, 'btn_add_text_to_thumbnail'):
            self.btn_add_text_to_thumbnail.setEnabled(bool(self.selected_thumbnail_path))

        if not hasattr(self, 'thumbnail_status_label'):
            return

        if is_generating:
            self.thumbnail_status_label.setText("Generando variantes 16:9 con IA y composicion...")
        elif not is_watchtime_target:
            self.thumbnail_status_label.setText(
                "Este modulo se activa para '9:16 · Vertical (YouTube Shorts)' y "
                "'9:16 · Vertical Largo (>3 min, YouTube)'."
            )
        elif not has_storyboard:
            self.thumbnail_status_label.setText(
                "Genera o carga un storyboard antes de crear miniaturas hook."
            )
        elif self.thumbnail_variants:
            status_text = f"{len(self.thumbnail_variants)} variante(s) disponibles para este proyecto."
            if niche_label:
                status_text += f" Perfil detectado: {niche_label}."
            if recommended_variant_id:
                status_text += f" Recomendación automática activa: {recommended_variant_id}."
            if recommended_reason:
                status_text += f" {recommended_reason}"
            self.thumbnail_status_label.setText(status_text)
        else:
            self.thumbnail_status_label.setText(
                "Listo para generar variantes 16:9 orientadas a CTR y watch time."
            )

    def _resolve_current_project_root(self):
        if self.current_project_path and os.path.exists(self.current_project_path):
            return Path(self.current_project_path).resolve().parent

        if self.last_storyboard_data:
            self.auto_save_project("preparando miniaturas hook")
            if self.current_project_path and os.path.exists(self.current_project_path):
                return Path(self.current_project_path).resolve().parent
        return None

    def _get_thumbnail_project_payload(self):
        project_root = self._resolve_current_project_root()
        if not project_root:
            return None, None

        project_data = self.get_current_project_data()
        if not project_data:
            return None, None

        project_data.setdefault('config', {})
        project_data['config']['platform_key'] = self.get_selected_platform_key()
        project_data['config']['video_format'] = self.get_selected_video_format()
        return project_root, project_data

    def _get_thumbnail_generation_clients(self):
        gen = self.generator._generator if hasattr(self.generator, '_generator') else self.generator
        if not self.thumbnail_groq_client:
            try:
                self.thumbnail_groq_client = GroqAiClient()
            except Exception as exc:
                self.log(f"️ No se pudo inicializar Groq para miniaturas hook: {exc}")
                self.thumbnail_groq_client = None
        llm_client = self.thumbnail_groq_client
        recraft_client = getattr(gen, 'recraft_client', None)
        comfyui_image_client = getattr(gen, 'comfyui_image_client', None)
        return (
            llm_client,
            recraft_client,
            comfyui_image_client,
        )

    # La plantilla estatica del super prompt vivia aca: 70 lineas clavadas en
    # 16:9 que ademas prohibian todo texto en la imagen. Nadie la leia (el
    # prompt real se arma en `claude_client.generate_thumbnail_super_prompt`),
    # asi que era documentacion que contradecia al codigo. Se elimino.

    def generate_super_prompt_for_external_ai(self):
        """Llama al LLM para generar [POSITIVE PROMPT] y [NEGATIVE PROMPT] listos para copiar."""
        from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QMessageBox
        from PyQt6.QtCore import QTimer

        # Obtener datos del proyecto
        topic = ""
        if hasattr(self, 'parent_gui') and hasattr(self.parent_gui, 'topic_input'):
            topic = self.parent_gui.topic_input.text().strip()
        if not topic:
            project_data = self.get_current_project_data()
            if project_data:
                topic = project_data.get('config', {}).get('topic', '')
        if not topic:
            QMessageBox.warning(self, "Sin tema", "Ingresa un tema primero.")
            return

        # Obtener cliente LLM (claude_client o gemini_client)
        llm_client = None
        if hasattr(self, 'parent_gui'):
            llm_client = getattr(self.parent_gui, 'claude_client', None) or getattr(self.parent_gui, 'gemini_client', None)
        if not llm_client or not hasattr(llm_client, 'generate_thumbnail_super_prompt'):
            QMessageBox.critical(self, "Error", "Cliente LLM no disponible o no soporta generate_thumbnail_super_prompt.")
            return

        # Datos adicionales
        category = ""
        language = "es"
        if hasattr(self, 'parent_gui'):
            if hasattr(self.parent_gui, 'category_combo'):
                category = self.parent_gui.category_combo.currentText()
            if hasattr(self.parent_gui, 'language_combo'):
                language = "en" if "english" in self.parent_gui.language_combo.currentText().lower() else "es"

        script_excerpt = ""
        project_data = self.get_current_project_data()
        if project_data:
            storyboard = project_data.get('storyboard') or {}
            script_excerpt = str(storyboard.get('script', '') or '')[:1200]
            if not script_excerpt:
                segments = storyboard.get('segments', [])
                script_excerpt = " ".join(str(s.get('text', '')) for s in segments[:15])[:1200]

        # Deshabilitar botón mientras procesa
        self.btn_generate_super_prompt.setEnabled(False)
        self.btn_generate_super_prompt.setText("Generando...")

        # El formato manda: un Short necesita 9:16 y reglas de encuadre propias.
        from thumbnail_formats import resolve_format
        fmt = resolve_format(
            video_format=self.get_selected_video_format() if hasattr(self, 'get_selected_video_format') else None,
            platform=self.get_selected_platform_key() if hasattr(self, 'get_selected_platform_key') else None,
            project_data=project_data or {},
        )
        render_text = (
            self.chk_super_prompt_text.isChecked()
            if hasattr(self, 'chk_super_prompt_text') else True
        )
        self.log(f" Super prompt: formato {fmt.aspect_label}, "
                 f"texto {'dibujado por la IA' if render_text else 'superpuesto despues'}")

        def _run():
            return llm_client.generate_thumbnail_super_prompt(
                topic=topic,
                script_excerpt=script_excerpt,
                category=category,
                language=language,
                thumbnail_format=fmt,
                render_text=render_text,
            )

        def _on_done(result):
            self.btn_generate_super_prompt.setEnabled(True)
            self.btn_generate_super_prompt.setText("Generar Super Prompt (IA externa)")
            if not result:
                QMessageBox.critical(self, "Error", "No se pudo generar el super prompt.")
                return

            positive = result.get('positive', '')
            negative = result.get('negative', '')

            dialog = QDialog(self if not hasattr(self, 'parent_gui') else self.parent_gui)
            dialog.setWindowTitle("Super Prompt para IA externa")
            dialog.setMinimumSize(860, 620)
            layout = QVBoxLayout(dialog)
            layout.setSpacing(10)

            layout.addWidget(QLabel(
                f"<b>Miniatura {fmt.aspect_label} ({fmt.width}x{fmt.height}).</b> "
                "Copia estos prompts y pégalos en Recraft, gpt-image, Midjourney, Ideogram, etc."
            ))

            hook_text = result.get('text', '')
            if hook_text:
                etiqueta = ("La IA debe escribir este texto en la imagen:"
                            if render_text else
                            "Texto sugerido (se superpone después, no lo dibuja la IA):")
                layout.addWidget(QLabel(f"<b>{etiqueta}</b>"))
                hook_edit = QTextEdit()
                hook_edit.setPlainText(hook_text)
                hook_edit.setReadOnly(True)
                hook_edit.setMaximumHeight(52)
                layout.addWidget(hook_edit)

            # Un solo bloque: positivo + negativo juntos. Dos cuadros con dos
            # botones obligaban a pegar dos veces y se prestaba a llevarse solo
            # la mitad. Es editable por si querés retocarlo antes de copiar.
            from claude_client import build_copyable_prompt
            combinado = result.get('combined') or build_copyable_prompt(positive, negative)

            layout.addWidget(QLabel("<b>Prompt completo (positivo + negativo)</b>"))
            prompt_edit = QTextEdit()
            prompt_edit.setPlainText(combinado)
            prompt_edit.setMinimumHeight(330)
            layout.addWidget(prompt_edit)

            btn_copy = QPushButton("Copiar prompt completo")

            # El timer que restaura el texto vive DENTRO del dialogo: si el
            # usuario copia y cierra antes de 1.5s, un singleShot suelto
            # disparaba sobre un boton ya destruido -> "wrapped C/C++ object
            # of type QPushButton has been deleted" como excepcion fatal
            # (crash_log, 2026-09-10). Con el dialogo como padre, cerrar la
            # ventana mata el timer con ella.
            restore_timer = QTimer(dialog)
            restore_timer.setSingleShot(True)
            restore_timer.setInterval(1500)
            restore_timer.timeout.connect(lambda: btn_copy.setText("Copiar prompt completo"))

            def _copy_all():
                QApplication.clipboard().setText(prompt_edit.toPlainText())
                btn_copy.setText("Copiado!")
                restore_timer.start()
            btn_copy.clicked.connect(_copy_all)
            layout.addWidget(btn_copy)

            btn_close = QPushButton("Cerrar")
            btn_close.clicked.connect(dialog.accept)
            layout.addWidget(btn_close)

            dialog.exec()

        self._pending_super_prompt_cb = _on_done
        thread = _LlmThread(_run)
        thread.done.connect(self._dispatch_super_prompt)
        thread.start()
        self._super_prompt_thread = thread  # evitar GC

    def load_external_thumbnail(self):
        """Carga una miniatura externa y la añade como la variante seleccionada."""
        try:
            from PyQt6.QtWidgets import QFileDialog, QMessageBox
            import shutil
            import os
            import time

            if not getattr(self, 'current_project_path', None):
                QMessageBox.warning(self, "Sin proyecto", "Primero debes cargar o generar un proyecto para adjuntarle la miniatura.")
                return

            file_path, _ = QFileDialog.getOpenFileName(
                self, "Seleccionar miniatura externa", "", "Imágenes (*.png *.jpg *.jpeg *.webp)"
            )
            if not file_path:
                return

            # Crear directorio de proyecto y copiar la imagen
            project_dir = os.path.dirname(self.current_project_path)
            media_dir = os.path.join(project_dir, "project_media")
            os.makedirs(media_dir, exist_ok=True)
            
            ext = os.path.splitext(file_path)[1]
            
            # Verificar peso (límite 2MB para YouTube, apuntamos a < 1.9MB)
            MAX_BYTES = 1.9 * 1024 * 1024
            file_size = os.path.getsize(file_path)
            
            if file_size > MAX_BYTES:
                self.log(f" La miniatura supera los 2MB ({file_size/1024/1024:.2f}MB). Comprimiendo...")
                try:
                    from PIL import Image
                    dest_name = f"manual_thumbnail_{int(time.time())}.jpg"
                    dest_path = os.path.join(media_dir, dest_name)
                    with Image.open(file_path) as img:
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                        # Intentar guardar con calidad iterativa hasta que pese menos del máximo
                        quality = 90
                        img.save(dest_path, "JPEG", quality=quality)
                        while os.path.getsize(dest_path) > MAX_BYTES and quality > 30:
                            quality -= 10
                            img.save(dest_path, "JPEG", quality=quality)
                    self.log(f" Miniatura comprimida exitosamente a {os.path.getsize(dest_path)/1024/1024:.2f}MB")
                except ImportError:
                    self.log(" Advertencia: Pillow (PIL) no está instalado. No se pudo comprimir.")
                    dest_name = f"manual_thumbnail_{int(time.time())}{ext}"
                    dest_path = os.path.join(media_dir, dest_name)
                    shutil.copy2(file_path, dest_path)
                except Exception as e:
                    self.log(f" Error al comprimir miniatura: {e}. Se copiará original.")
                    dest_name = f"manual_thumbnail_{int(time.time())}{ext}"
                    dest_path = os.path.join(media_dir, dest_name)
                    shutil.copy2(file_path, dest_path)
            else:
                dest_name = f"manual_thumbnail_{int(time.time())}{ext}"
                dest_path = os.path.join(media_dir, dest_name)
                shutil.copy2(file_path, dest_path)

            # Inicializar thumbnail_data si no existe
            if not isinstance(getattr(self, 'thumbnail_data', None), dict):
                self.thumbnail_data = {}
            if not getattr(self, 'thumbnail_variants', None):
                self.thumbnail_variants = []

            # Crear variante manual
            variant_id = f"manual_{int(time.time())}"
            manual_variant = {
                'id': variant_id,
                'path': dest_path,
                'label': 'Miniatura Externa',
                'hook_text': 'Manual',
                'strategy_text': 'Cargada externamente por el usuario',
                'selection_score': 100.0
            }

            self.thumbnail_variants.append(manual_variant)
            self.thumbnail_data['thumbnail_variants'] = self.thumbnail_variants
            self.thumbnail_data['selected_variant_id'] = variant_id
            self.thumbnail_data['thumbnail_path'] = dest_path

            # Actualizar interfaz
            self._populate_thumbnail_variants(selected_variant_id=variant_id, selected_path=dest_path)
            
            if hasattr(self, 'thumbnail_status_label') and self.thumbnail_status_label:
                self.thumbnail_status_label.setText("Miniatura externa cargada y seleccionada para publicar.")
                self.thumbnail_status_label.setStyleSheet("color: #128249; font-weight: 600;")
                
            self.log(f" Miniatura externa cargada: {dest_name}")
            
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error al cargar miniatura", f"Ocurrió un error:\n\n{exc}")


    def add_text_to_loaded_thumbnail(self):
        """Abre un diálogo con sugerencias de texto optimizadas para CTR y las aplica al thumbnail."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                                     QComboBox, QPushButton, QMessageBox, QButtonGroup,
                                     QRadioButton, QGroupBox, QScrollArea, QWidget, QFrame)
        from PyQt6.QtCore import QTimer
        import os, time
        from pathlib import Path

        if not self.selected_thumbnail_path or not os.path.exists(self.selected_thumbnail_path):
            QMessageBox.warning(self, "Sin imagen", "Primero carga o genera una miniatura.")
            return

        parent_gui = getattr(self, 'parent_gui', None)
        if not parent_gui or not hasattr(parent_gui, '_add_text_to_image'):
            QMessageBox.critical(self, "Error", "Funcion de texto no disponible.")
            return

        # Recopilar datos del proyecto
        topic = ""
        if hasattr(parent_gui, 'topic_input'):
            topic = parent_gui.topic_input.text().strip()
        category = getattr(parent_gui, 'category_combo', None)
        category = category.currentText() if category else ""
        language = "es"
        if hasattr(parent_gui, 'language_combo'):
            language = "en" if "english" in parent_gui.language_combo.currentText().lower() else "es"

        script_excerpt = ""
        project_data = self.get_current_project_data()
        if project_data:
            storyboard = project_data.get('storyboard') or {}
            script_excerpt = str(storyboard.get('script', '') or '')[:800]
            if not script_excerpt:
                segs = storyboard.get('segments', [])
                script_excerpt = " ".join(str(s.get('text', '')) for s in segs[:10])[:800]

        emotional_hook = "shock"
        image_description = ""
        if hasattr(self, 'thumbnail_strategy') and isinstance(self.thumbnail_strategy, dict):
            emotional_hook = self.thumbnail_strategy.get('mystery_concept') or "shock"
            image_description = self.thumbnail_strategy.get('selected_scene_prompt') or ""
        elif self.thumbnail_variant_combo.currentIndex() >= 0:
            idx = self.thumbnail_variant_combo.currentIndex()
            if 0 <= idx < len(self.thumbnail_variants):
                image_description = self.thumbnail_variants[idx].get('strategy_text', '')

        llm_client = getattr(parent_gui, 'claude_client', None) or getattr(parent_gui, 'gemini_client', None)

        # --- Diálogo principal ---
        dialog = QDialog(parent_gui)
        dialog.setWindowTitle("Texto inteligente para thumbnail")
        dialog.setMinimumSize(560, 520)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        # Área de sugerencias (inicialmente con mensaje de carga)
        suggestions_group = QGroupBox("Sugerencias de texto (generadas por IA)")
        suggestions_layout = QVBoxLayout(suggestions_group)
        loading_label = QLabel("Analizando imagen y guion para generar sugerencias optimizadas para CTR...")
        loading_label.setStyleSheet("color: #6f7c89; font-style: italic;")
        loading_label.setWordWrap(True)
        suggestions_layout.addWidget(loading_label)
        layout.addWidget(suggestions_group)

        # Campo de texto personalizado
        custom_group = QGroupBox("O escribe tu propio texto")
        custom_layout = QVBoxLayout(custom_group)
        custom_edit = QLineEdit()
        custom_edit.setPlaceholderText("Texto personalizado en mayusculas (max 4 palabras)...")
        custom_layout.addWidget(custom_edit)
        layout.addWidget(custom_group)

        # Estilo e idioma
        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Estilo:"))
        style_combo = QComboBox()
        style_combo.addItems(["Contraste alto", "Claro limpio", "Neon suave", "Rojo intenso"])
        options_row.addWidget(style_combo)
        options_row.addSpacing(20)
        options_row.addWidget(QLabel("Idioma:"))
        lang_combo = QComboBox()
        lang_combo.addItems(["Espanol", "English"])
        if language == "en":
            lang_combo.setCurrentText("English")
        options_row.addWidget(lang_combo)
        options_row.addStretch()
        layout.addLayout(options_row)

        btn_row = QHBoxLayout()
        btn_apply = QPushButton("Aplicar texto al thumbnail")
        btn_apply.setObjectName("accent")
        btn_apply.setEnabled(False)
        btn_cancel = QPushButton("Cancelar")
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        btn_cancel.clicked.connect(dialog.reject)

        # Guardar la selección activa
        selected_text_holder = ['']
        radio_group = QButtonGroup(dialog)

        def _populate_suggestions(suggestions):
            # Limpiar el loading label
            loading_label.hide()

            if not suggestions:
                loading_label.setText("No se pudieron generar sugerencias. Usa el campo de texto personalizado.")
                loading_label.show()
                btn_apply.setEnabled(True)
                return

            for i, s in enumerate(suggestions):
                text = s.get('text', '').upper()
                technique = s.get('technique', '')
                why = s.get('why', '')

                frame = QFrame()
                frame.setFrameShape(QFrame.Shape.StyledPanel)
                frame.setStyleSheet("QFrame { background: #f8f9fb; border: 1px solid #dde3e9; border-radius: 6px; padding: 4px; }")
                frame_layout = QVBoxLayout(frame)
                frame_layout.setSpacing(2)
                frame_layout.setContentsMargins(8, 6, 8, 6)

                radio = QRadioButton(f"  {text}")
                radio.setStyleSheet("font-weight: bold; font-size: 13px;")
                radio_group.addButton(radio, i)
                frame_layout.addWidget(radio)

                tech_label = QLabel(f"Tecnica: {technique}")
                tech_label.setStyleSheet("color: #3a7bd5; font-size: 11px;")
                frame_layout.addWidget(tech_label)

                why_label = QLabel(why)
                why_label.setStyleSheet("color: #6f7c89; font-size: 11px;")
                why_label.setWordWrap(True)
                frame_layout.addWidget(why_label)

                suggestions_layout.addWidget(frame)

                def _on_radio_toggled(checked, t=text):
                    if checked:
                        selected_text_holder[0] = t
                        custom_edit.clear()
                        btn_apply.setEnabled(True)

                radio.toggled.connect(_on_radio_toggled)

            # Seleccionar la primera por defecto
            if radio_group.button(0):
                radio_group.button(0).setChecked(True)

        def _on_custom_text_changed(txt):
            if txt.strip():
                radio_group.setExclusive(False)
                for btn in radio_group.buttons():
                    btn.setChecked(False)
                radio_group.setExclusive(True)
                selected_text_holder[0] = txt.strip().upper()
                btn_apply.setEnabled(True)
            elif not any(b.isChecked() for b in radio_group.buttons()):
                btn_apply.setEnabled(False)

        custom_edit.textChanged.connect(_on_custom_text_changed)

        def _apply():
            final_text = custom_edit.text().strip().upper() or selected_text_holder[0]
            if not final_text:
                QMessageBox.warning(dialog, "Sin texto", "Selecciona una sugerencia o escribe tu propio texto.")
                return

            style = style_combo.currentText()
            lang_label = lang_combo.currentText()

            src = self.selected_thumbnail_path
            base = Path(src)
            out_path = str(base.parent / f"{base.stem}_text_{int(time.time())}.png")

            ok = parent_gui._add_text_to_image(src, out_path, final_text, style, lang_label)
            if not ok:
                QMessageBox.critical(dialog, "Error", "No se pudo aplicar el texto.")
                return

            variant_id = f"text_{int(time.time())}"
            idx = self.thumbnail_variant_combo.currentIndex()
            orig_label = "Miniatura"
            if 0 <= idx < len(self.thumbnail_variants):
                orig_label = self.thumbnail_variants[idx].get('label', 'Miniatura')

            new_variant = {
                'id': variant_id,
                'path': out_path,
                'label': f"{orig_label} + texto",
                'hook_text': final_text[:40],
                'strategy_text': f'Texto aplicado: {final_text}',
                'selection_score': 100.0,
            }
            self.thumbnail_variants.append(new_variant)
            if isinstance(getattr(self, 'thumbnail_data', None), dict):
                self.thumbnail_data['thumbnail_variants'] = self.thumbnail_variants

            self._populate_thumbnail_variants(selected_variant_id=variant_id, selected_path=out_path)

            if hasattr(self, 'thumbnail_status_label') and self.thumbnail_status_label:
                self.thumbnail_status_label.setText(f"Texto '{final_text}' aplicado. Nueva variante creada.")
                self.thumbnail_status_label.setStyleSheet("color: #128249; font-weight: 600;")

            self.log(f"Texto aplicado al thumbnail: {out_path}")
            dialog.accept()

        btn_apply.clicked.connect(_apply)
        dialog.show()

        # Generar sugerencias en background
        if llm_client and hasattr(llm_client, 'generate_thumbnail_text_suggestions'):
            from PyQt6.QtCore import QThread

            def _fetch():
                return llm_client.generate_thumbnail_text_suggestions(
                    topic=topic,
                    script_excerpt=script_excerpt,
                    category=category,
                    language=language,
                    emotional_hook=emotional_hook,
                    image_description=image_description,
                )

            self._pending_text_suggestions_cb = _populate_suggestions
            thread = _LlmThread(_fetch)
            thread.done.connect(self._dispatch_text_suggestions)
            thread.start()
            self._text_suggestions_thread = thread  # evitar GC
        else:
            loading_label.setText("LLM no disponible. Usa el campo de texto personalizado.")
            btn_apply.setEnabled(True)

    def generate_watchtime_thumbnails(self):
        """Genera las variantes de miniatura del proyecto activo.

        El formato sale de la plataforma elegida: 9:16 (1080x1920) para un
        Short, 16:9 para un vertical largo.
        """
        if not self._supports_custom_thumbnail():
            QMessageBox.information(
                self,
                "Formato no compatible",
                "Este modulo funciona con '9:16 · Vertical (YouTube Shorts)' y con\n"
                "'9:16 · Vertical Largo (>3 min, YouTube)'.\n\n"
                "El Short lleva miniatura 9:16 (1080x1920); el vertical largo la\n"
                "lleva 16:9, porque aparece en el feed normal de YouTube."
            )
            return

        if not (self.last_storyboard_data and self.last_storyboard_data.get('segments')):
            QMessageBox.warning(
                self,
                "Sin Storyboard",
                "Primero genera o carga un storyboard antes de crear miniaturas hook."
            )
            return

        project_root, project_data = self._get_thumbnail_project_payload()
        if not project_root or not project_data:
            QMessageBox.warning(
                self,
                "Proyecto no disponible",
                "No se pudo preparar la carpeta del proyecto para guardar las miniaturas."
            )
            return

        llm_client, recraft_client, comfyui_image_client = self._get_thumbnail_generation_clients()
        style_hint = self.style_combo.currentText() if hasattr(self, 'style_combo') else None

        if not (llm_client and getattr(llm_client, 'client', None)):
            QMessageBox.warning(
                self,
                "Groq no disponible",
                "Las miniaturas hook ahora requieren Groq para el análisis. Configura GROQ_API_KEY e inténtalo de nuevo."
            )
            return

        has_recraft = bool(recraft_client and getattr(recraft_client, 'api_key', None))
        has_comfyui = bool(comfyui_image_client and getattr(comfyui_image_client, 'available', False))
        if not (has_recraft or has_comfyui):
            QMessageBox.warning(
                self,
                "Proveedor no disponible",
                "Las miniaturas hook requieren Recraft o ComfyUI para generar la imagen base. Configura RECRAFT_API_KEY o COMFYUI_BASE_URL."
            )
            return

        if self.thumbnail_thread and self.thumbnail_thread.isRunning():
            self.log("️ Ya hay una generación de miniaturas hook en curso.")
            return

        self._bind_thumbnail_worker_to_project()
        self.thumbnail_worker = ThumbnailGenerationWorker(
            project_root=str(project_root),
            project_data=project_data,
            llm_client=llm_client,
            recraft_client=recraft_client,
            comfyui_image_client=comfyui_image_client,
            style_hint=style_hint,
        )
        self.thumbnail_thread = QThread()
        self.thumbnail_worker.moveToThread(self.thumbnail_thread)
        self.thumbnail_thread.started.connect(self.thumbnail_worker.run)
        self.thumbnail_worker.progress.connect(self._on_thumbnail_generation_progress)
        self.thumbnail_worker.finished.connect(self._on_thumbnail_generation_finished)
        self.thumbnail_worker.error.connect(self._on_thumbnail_generation_error)
        self.thumbnail_worker.finished.connect(self.thumbnail_thread.quit)
        self.thumbnail_worker.error.connect(self.thumbnail_thread.quit)
        self.thumbnail_thread.finished.connect(self.cleanup_thumbnail_thread)

        self._refresh_thumbnail_module_state()
        self.thumbnail_thread.start()

    def _on_thumbnail_generation_progress(self, message):
        if not self._should_accept_thumbnail_callback():
            return
        if message:
            self.log(message)
            if hasattr(self, 'thumbnail_status_label'):
                self.thumbnail_status_label.setText(message)

    def _on_thumbnail_generation_finished(self, result):
        if not self._should_accept_thumbnail_callback():
            self.log("️ Resultado de miniaturas hook obsoleto ignorado.")
            return
        self.thumbnail_data = result or {}
        self.thumbnail_strategy = (result or {}).get('thumbnail_strategy')
        self.thumbnail_variants = list((result or {}).get('thumbnail_variants') or [])

        selected_path = (result or {}).get('thumbnail_path')
        selected_variant_id = (result or {}).get('selected_variant_id')
        self._populate_thumbnail_variants(
            selected_variant_id=selected_variant_id,
            selected_path=selected_path,
            auto_save=False,
        )

        if self.thumbnail_strategy:
            hook_text = self.thumbnail_strategy.get('selected_hook') or '-'
            self.thumbnail_hook_label.setText(f"Hook seleccionado: {hook_text}")
            niche_label = self.thumbnail_strategy.get('niche_label') or self.thumbnail_strategy.get('niche_profile')
            if niche_label:
                self.log(f" Perfil detectado para miniatura: {niche_label}")

        recommended_variant_id = (result or {}).get('recommended_variant_id')
        recommended_reason = (result or {}).get('recommended_reason')
        if recommended_variant_id:
            self.log(f" Variante recomendada automáticamente: {recommended_variant_id}")
        if recommended_reason:
            self.log(f"   Motivo: {recommended_reason}")

        if selected_path:
            self._set_selected_thumbnail_path(selected_path, auto_save=False)

        if hasattr(self, 'parent_gui'):
            self.parent_gui.last_raw_image_path = selected_path
            self.parent_gui.last_thumbnail_path = selected_path
            if hasattr(self.parent_gui, '_update_thumbnail_preview') and selected_path:
                self.parent_gui._update_thumbnail_preview(selected_path)

        self.log(" Miniaturas hook generadas y asociadas al proyecto actual")
        if self.auto_save_enabled:
            self.auto_save_project("miniaturas hook generadas")
        self._refresh_thumbnail_module_state()

    def _on_thumbnail_generation_error(self, error):
        if not self._should_accept_thumbnail_callback():
            self.log("️ Error de miniaturas hook obsoleto ignorado.")
            return
        self.log(f" Error generando miniaturas hook: {error}")
        QMessageBox.critical(self, "Error", f"No se pudieron generar las miniaturas:\n\n{error}")
        self._refresh_thumbnail_module_state()

    # ------------------------------------------------------------------
    # Dispatch methods for LLM background threads
    # These are real bound methods on self (main-thread QObject), so PyQt6
    # automatically uses QueuedConnection when the signal crosses threads.
    # ------------------------------------------------------------------
    def _dispatch_super_prompt(self, result):
        cb = getattr(self, '_pending_super_prompt_cb', None)
        self._pending_super_prompt_cb = None
        if cb:
            cb(result)

    def _dispatch_text_suggestions(self, result):
        cb = getattr(self, '_pending_text_suggestions_cb', None)
        self._pending_text_suggestions_cb = None
        if cb:
            cb(result)

    def cleanup_thumbnail_thread(self):
        if self.thumbnail_thread:
            if self.thumbnail_thread.isRunning():
                self.thumbnail_thread.quit()
                if not self.thumbnail_thread.wait(5000):
                    self.thumbnail_thread.terminate()
                    self.thumbnail_thread.wait(2000)
            self.thumbnail_thread.deleteLater()
            self.thumbnail_thread = None
        if self.thumbnail_worker:
            self.thumbnail_worker.deleteLater()
            self.thumbnail_worker = None
        self._current_thumbnail_project_token = None
        self._current_thumbnail_project_path = None
        self._refresh_thumbnail_module_state()

    def _populate_thumbnail_variants(self, selected_variant_id=None, selected_path=None, auto_save=True):
        if not hasattr(self, 'thumbnail_variant_combo'):
            return

        self.thumbnail_variant_combo.blockSignals(True)
        self.thumbnail_variant_combo.clear()
        selected_index = -1
        recommended_variant_id = None
        if isinstance(self.thumbnail_data, dict):
            recommended_variant_id = self.thumbnail_data.get('recommended_variant_id')

        for index, variant in enumerate(self.thumbnail_variants):
            label = variant.get('label') or f"Variante {index + 1}"
            hook_text = variant.get('hook_text')
            if hook_text:
                label = f"{label} · {hook_text}"
            if recommended_variant_id and variant.get('id') == recommended_variant_id:
                label = f"{label}  Recomendada"
            self.thumbnail_variant_combo.addItem(label, variant)
            if selected_variant_id and variant.get('id') == selected_variant_id:
                selected_index = index
            elif selected_path and variant.get('path') == selected_path:
                selected_index = index

        if self.thumbnail_variants:
            if selected_index < 0:
                selected_index = 0
            self.thumbnail_variant_combo.setCurrentIndex(selected_index)
        else:
            self.thumbnail_variant_combo.setCurrentIndex(-1)
            self._update_studio_thumbnail_preview(None)
        self.thumbnail_variant_combo.blockSignals(False)

        if self.thumbnail_variants and selected_index >= 0:
            self._on_thumbnail_variant_changed(selected_index, auto_save=auto_save)

    def _on_thumbnail_variant_changed(self, index, auto_save=True):
        if index < 0 or index >= len(self.thumbnail_variants):
            return
        variant = self.thumbnail_variants[index]
        self._set_selected_thumbnail_path(variant.get('path'), auto_save=auto_save)
        hook_text = variant.get('hook_text') or "-"
        selection_score = variant.get('selection_score')
        recommendation_text = ""
        if isinstance(self.thumbnail_data, dict) and variant.get('id') == self.thumbnail_data.get('recommended_variant_id'):
            recommendation_text = " · recomendada para upload"
        if selection_score is not None:
            recommendation_text += f" · score {selection_score:.1f}"
        self.thumbnail_hook_label.setText(f"Hook seleccionado: {hook_text}{recommendation_text}")

        if isinstance(self.thumbnail_data, dict):
            self.thumbnail_data['selected_variant_id'] = variant.get('id')
            self.thumbnail_data['thumbnail_path'] = variant.get('path')

    def _set_selected_thumbnail_path(self, thumbnail_path, auto_save=True):
        self.selected_thumbnail_path = thumbnail_path
        self._update_studio_thumbnail_preview(thumbnail_path)
        self._refresh_thumbnail_module_state()
        if (not self._suppress_thumbnail_autosave) and auto_save and self.auto_save_enabled and self.current_project_path:
            self.auto_save_project("seleccion de miniatura")

    def _update_studio_thumbnail_preview(self, image_path):
        if not hasattr(self, 'thumbnail_preview'):
            return

        if not image_path or not os.path.exists(image_path):
            self.thumbnail_preview.setPixmap(QPixmap())
            self.thumbnail_preview.setText("La miniatura seleccionada se mostrara aqui")
            return

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.thumbnail_preview.setPixmap(QPixmap())
            self.thumbnail_preview.setText("No se pudo cargar la miniatura")
            return

        scaled = pixmap.scaled(
            self.thumbnail_preview.width(),
            self.thumbnail_preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.thumbnail_preview.setPixmap(scaled)
        self.thumbnail_preview.setText("")

    def open_selected_thumbnail(self):
        if not self.selected_thumbnail_path or not os.path.exists(self.selected_thumbnail_path):
            QMessageBox.information(self, "Sin miniatura", "No hay una miniatura seleccionada para abrir.")
            return
        try:
            os.startfile(self.selected_thumbnail_path)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo abrir", f"No se pudo abrir la miniatura:\n\n{exc}")

    def restore_thumbnail_state(self, thumbnail_data=None, thumbnail_path=None):
        self.thumbnail_data = thumbnail_data or {}
        self.thumbnail_strategy = self.thumbnail_data.get('thumbnail_strategy') if isinstance(self.thumbnail_data, dict) else None
        self.thumbnail_variants = list(self.thumbnail_data.get('thumbnail_variants') or []) if isinstance(self.thumbnail_data, dict) else []

        selected_variant_id = None
        if isinstance(self.thumbnail_data, dict):
            selected_variant_id = self.thumbnail_data.get('selected_variant_id')
            thumbnail_path = thumbnail_path or self.thumbnail_data.get('thumbnail_path')

        self.selected_thumbnail_path = thumbnail_path or None

        previous_suppression = self._suppress_thumbnail_autosave
        self._suppress_thumbnail_autosave = True
        try:
            self._populate_thumbnail_variants(
                selected_variant_id=selected_variant_id,
                selected_path=thumbnail_path,
                auto_save=False,
            )
            if thumbnail_path:
                self.selected_thumbnail_path = thumbnail_path
            self._refresh_thumbnail_module_state()
        finally:
            self._suppress_thumbnail_autosave = previous_suppression

    def open_timeline_editor(self):
        """Abre el Timeline Editor en una ventana separada"""
        try:
            if self._loading_project:
                return
            if not self.last_storyboard_data:
                QMessageBox.warning(
                    self,
                    "Sin Storyboard",
                    "Primero genera el storyboard."
                )
                return

            def _refresh_storyboard_from_project():
                if not (hasattr(self, 'current_project_path') and self.current_project_path):
                    return
                try:
                    from project_manager_v2 import ProjectManagerV2
                    project_data = ProjectManagerV2.load_project(self.current_project_path)
                except Exception:
                    return
                if not project_data:
                    return
                saved_storyboard = project_data.get('storyboard', {})
                if not (saved_storyboard and saved_storyboard.get('segments')):
                    return
                memory = getattr(self, 'last_storyboard_data', None)
                try:
                    from storyboard_generator import prefer_in_memory_storyboard
                    keep_memory = prefer_in_memory_storyboard(memory, saved_storyboard)
                except Exception:
                    keep_memory = bool(memory and len(memory.get('segments') or []) > len(saved_storyboard.get('segments') or []))
                if keep_memory:
                    print(
                        f"[Timeline] Conservando storyboard en memoria "
                        f"({len(memory.get('segments', []))} segs) en vez de disco "
                        f"({len(saved_storyboard.get('segments', []))} segs)"
                    )
                    return
                print(
                    f"[Timeline] Actualizando segmentos desde proyecto guardado "
                    f"({len(saved_storyboard.get('segments', []))} segmentos)"
                )
                saved_storyboard = self.project_manager._restore_media_paths(
                    self.current_project_path,
                    saved_storyboard
                )
                self.last_storyboard_data = saved_storyboard
                images_restored = sum(
                    1 for seg in saved_storyboard.get('segments', [])
                    if seg.get('image_path')
                )
                print(f"[Timeline] {images_restored} segmento(s) con imágenes restauradas")

            def _normalize_segments():
                if not (self.last_storyboard_data and self.last_storyboard_data.get('segments')):
                    return []
                normalized = []
                for seg in self.last_storyboard_data.get('segments', []):
                    item = seg.copy()
                    if 'text' not in item:
                        if 'narration_text' in item:
                            item['text'] = item['narration_text']
                        elif 'narration' in item:
                            item['text'] = item['narration']
                        else:
                            item['text'] = item.get('visual_prompt', 'Sin texto')
                    normalized.append(item)
                return normalized

            def _load_segments_deferred():
                if not (self.timeline_editor_window and getattr(self.timeline_editor_window, 'timeline_editor', None)):
                    return
                normalized = _normalize_segments()
                if not normalized:
                    return
                expected_project_path = getattr(self, 'current_project_path', None)
                expected_project_token = self._project_state_token
                if hasattr(self.timeline_editor_window, 'bind_to_project'):
                    self.timeline_editor_window.bind_to_project(expected_project_path)
                self.log(f"    Cargando {len(normalized)} segmentos en Timeline...")

                def _apply_loaded_segments(segs=normalized, expected_path=expected_project_path, expected_token=expected_project_token, window=self.timeline_editor_window):
                    if not self._is_project_context_current(expected_path, expected_token):
                        print(
                            "[Timeline] Omitiendo carga diferida de segmentos por token/ruta obsoletos: "
                            f"esperado={expected_path}"
                        )
                        return
                    current_project_path = getattr(self, 'current_project_path', None)
                    if expected_path and current_project_path:
                        try:
                            expected_norm = os.path.normcase(os.path.abspath(str(expected_path)))
                            current_norm = os.path.normcase(os.path.abspath(str(current_project_path)))
                        except Exception:
                            expected_norm = str(expected_path)
                            current_norm = str(current_project_path)
                        if expected_norm != current_norm:
                            print(
                                "[Timeline] Omitiendo carga diferida de segmentos: "
                                f"esperado={expected_path} actual={current_project_path}"
                            )
                            return
                    if hasattr(window, 'bind_to_project'):
                        window.bind_to_project(expected_path or current_project_path)
                    window.timeline_editor.load_segments(segs)

                QTimer.singleShot(
                    0,
                    _apply_loaded_segments
                )

            _refresh_storyboard_from_project()
            self._storyboard_just_generated = False

            # Si la ventana ya existe y está visible, actualizar datos y traerla al frente
            if self.timeline_editor_window and self.timeline_editor_window.isVisible():
                _load_segments_deferred()
                self.timeline_editor_window.raise_()
                self.timeline_editor_window.activateWindow()
                return

            # Crear nueva ventana si no existe o está cerrada
            self.log("Abriendo editor de timeline...")
            self.timeline_editor_window = TimelineEditorWindow(self)
            self.timeline_editor_window.timeline_editor.segments_modified.connect(self.on_timeline_modified)

            # Mostrar ventana primero, luego cargar segmentos en diferido
            self.timeline_editor_window.show()
            _load_segments_deferred()
            self.btn_open_timeline.setEnabled(True)
            self.log("Editor de timeline abierto correctamente")

        except Exception as e:
            error_msg = f"Error abriendo editor de timeline: {e}"
            print(f" {error_msg}")
            import traceback
            traceback.print_exc()
            self.log(f" {error_msg}")
            QMessageBox.critical(
                self,
                "Error al abrir editor de timeline",
                f"{error_msg}\n\nPuedes continuar trabajando con el storyboard.\n\n"
                f"Detalles técnicos:\n{traceback.format_exc()}"
            )
            if hasattr(self, 'btn_open_timeline'):
                self.btn_open_timeline.setEnabled(True)

    def on_timeline_modified(self, modified_segments):
        """Callback cuando se modifican segmentos en el timeline"""
        if self._loading_project:
            return
        sender = self.sender()
        if sender and hasattr(sender, 'get_bound_project_path'):
            sender_project_path = self._normalize_project_path(sender.get_bound_project_path())
            current_project_path = self._normalize_project_path(getattr(self, 'current_project_path', None))
            if sender_project_path and current_project_path and sender_project_path != current_project_path:
                self.log("️ Modificación de timeline obsoleta ignorada.")
                return
        if not self.last_storyboard_data:
            return

        # Actualizar el storyboard con los segmentos modificados
        self.last_storyboard_data['segments'] = modified_segments

        # Sincronizar tambiÃ©n con la ventana del Timeline Editor si estÃ¡
        # abierta
        if self.timeline_editor_window and self.timeline_editor_window.timeline_editor:
            # Asegurar que los segmentos en la ventana estÃ©n actualizados
            self.timeline_editor_window.timeline_editor.segments = modified_segments

        self.log("âœ… Timeline modificado - Cambios sincronizados")
        self._refresh_assemble_button_state()

        # Auto-guardar si estÃ¡ habilitado y hay un proyecto cargado
        if self.auto_save_enabled:
            self.auto_save_project("despuÃ©s de modificar Timeline Editor")

    def create_log_section(self):
        """Crea la secciÃ³n de log"""
        group = QGroupBox("Log de generacion")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        # Limitar altura mÃ¡xima para que no ocupe todo el espacio
        self.log_text.setMaximumHeight(300)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                color: #2f3b47;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9pt;
                border: 1px solid #dde3e9;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.log_text)

        # BotÃ³n de limpiar
        btn_clear = QPushButton("Limpiar log")
        btn_clear.clicked.connect(lambda: self.log_text.clear())
        layout.addWidget(btn_clear)

        return group

    def log(self, message):
        """Registra un mensaje en el log"""
        if hasattr(self, 'log_text') and self.log_text:
            self.log_text.append(message)
            # Scroll al final
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        else:
            # Si log_text aÃºn no existe, imprimir en consola
            print(message)

    def update_status(self, status):
        """Actualiza el estado en la barra de estado (si existe)"""
        if hasattr(self, 'parent_gui') and self.parent_gui and hasattr(self.parent_gui, 'statusBar'):
            self.parent_gui.statusBar().showMessage(status)

    def _show_progress_indicator(self):
        """Muestra indicador de progreso si existe en esta variante de UI."""
        if hasattr(self, 'progress_bar') and self.progress_bar:
            self.progress_bar.show()

    def _hide_progress_indicator(self):
        """Oculta indicador de progreso si existe en esta variante de UI."""
        if hasattr(self, 'progress_bar') and self.progress_bar:
            self.progress_bar.hide()

    def show_error(self, error):
        """Loguea un error del generador en el panel de logs (sin popup)."""
        self.log(f"️ Error: {error}")

    # ========== MÃ‰TODOS DE LÃ“GICA ==========

    def _create_tts_generator(self):
        """Crea el generador TTS sin depender del modulo pesado del pipeline."""
        if StandaloneTextToSpeechGenerator is not None:
            return StandaloneTextToSpeechGenerator()

        from auto_video_generator_v2 import TextToSpeechGenerator
        if TextToSpeechGenerator is None:
            raise RuntimeError("TextToSpeechGenerator no esta disponible.")
        return TextToSpeechGenerator()

    def _get_voice_fallback_catalog(self):
        """Recupera voces desde cache local o deja un fallback minimo."""
        try:
            tts = self._create_tts_generator()
            if hasattr(tts, 'get_cached_or_fallback_voices'):
                fallback_voices = tts.get_cached_or_fallback_voices()
                if fallback_voices:
                    return fallback_voices
        except Exception as e:
            self.log(f"️ No se pudo recuperar cache local de voces: {e}")

        return {
            "gTTS (Español)": {
                "id": "gtts_fallback",
                "name": "gTTS Español",
                "language": "es",
                "provider": "gtts",
            }
        }

    def _apply_voice_selection(self):
        """Reaplica la voz pendiente despues de refrescar el catalogo."""
        if not hasattr(self, 'pending_voice_selection') or not self.pending_voice_selection:
            return

        voice_name = self.pending_voice_selection
        if voice_name in self.elevenlabs_voices:
            index = self.voice_combo.findText(voice_name)
            if index >= 0:
                self.voice_combo.setCurrentIndex(index)
                self.log(f" Voz restaurada: {voice_name}")
            else:
                self.log(f"️ Voz '{voice_name}' no encontrada en el combo")
        else:
            self.log(f"️ Voz '{voice_name}' no disponible en las voces cargadas")

        self.pending_voice_selection = None

    def _set_voice_loader_busy(self, is_busy, placeholder=None):
        """Actualiza el estado visual del cargador de voces."""
        if hasattr(self, 'btn_reload_voices'):
            self.btn_reload_voices.setEnabled(not is_busy)
        if is_busy and hasattr(self, 'btn_preview_voice'):
            self.btn_preview_voice.setEnabled(False)
        if placeholder and hasattr(self, 'voice_combo'):
            current_text = self.voice_combo.currentText().strip() if self.voice_combo.count() else ""
            if self.voice_combo.count() == 0 or current_text in ("", "Cargando voces...", "Recargando voces..."):
                self.voice_combo.clear()
                self.voice_combo.addItem(placeholder)

    def reload_voices(self):
        """Permite reintentar la carga manualmente desde la UI."""
        self.load_elevenlabs_voices(force_reload=True)

    def load_elevenlabs_voices(self, force_reload=False):
        """Carga las voces de ElevenLabs, Edge-TTS y gTTS en segundo plano"""
        if self.voice_load_thread and self.voice_load_thread.isRunning():
            if force_reload:
                self.log(" Ya hay una carga de voces en curso...")
            return

        self._set_voice_loader_busy(True, "Recargando voces..." if force_reload else "Cargando voces...")
        owner = self

        # Crear un worker thread apropiado
        class VoiceLoaderWorker(QThread):
            voices_loaded = pyqtSignal(dict)
            error_occurred = pyqtSignal(str)
            status_update = pyqtSignal(str)

            def run(self):
                try:
                    self.status_update.emit(" Cargando voces disponibles...")
                    tts = owner._create_tts_generator()
                    voices = tts.get_available_voices() or {}
                    if not voices:
                        raise RuntimeError("No se encontraron voces disponibles.")

                    # Contar voces por proveedor
                    edge_count = sum(
    1 for v in voices.values() if v.get('provider') == 'edge-tts')
                    eleven_count = sum(
    1 for v in voices.values() if v.get('provider') == 'elevenlabs')
                    gtts_count = sum(
    1 for v in voices.values() if v.get('provider') == 'gtts')

                    if edge_count > 0:
                        self.status_update.emit(
                            f"âœ… {edge_count} voces Edge-TTS (gratis) cargadas")
                    if eleven_count > 0:
                        self.status_update.emit(
                            f"âœ… {eleven_count} voces ElevenLabs cargadas")
                    if gtts_count > 0:
                        self.status_update.emit(
                            f"âœ… {gtts_count} voces gTTS (gratis) cargadas")

                    self.voices_loaded.emit(voices)

                except Exception as e:
                    import traceback
                    error_details = f"{str(e)}\n{traceback.format_exc()}"
                    self.error_occurred.emit(error_details)

        # Crear e iniciar worker
        self.voice_load_thread = VoiceLoaderWorker()
        self.voice_load_thread.voices_loaded.connect(self.on_voices_loaded)
        self.voice_load_thread.error_occurred.connect(self.on_voices_error)
        self.voice_load_thread.status_update.connect(self.log)
        self.voice_load_thread.start()

    def on_voices_loaded(self, voices):
        """Callback cuando las voces se cargan exitosamente"""
        self._set_voice_loader_busy(False)
        if not voices:
            self.on_voices_error("No se encontraron voces disponibles.")
            return

        self.elevenlabs_voices = voices
        voice_names = list(voices.keys())

        self.voice_combo.clear()
        self.voice_combo.addItems(voice_names)

        # Aplicar voz pendiente si existe (despuÃ©s de cargar un proyecto)
        self._apply_voice_selection()

        # Contar voces por proveedor
        edge_count = sum(1 for v in voices.values()
                         if v.get('provider') == 'edge-tts')
        eleven_count = sum(1 for v in voices.values()
                           if v.get('provider') == 'elevenlabs')
        gtts_count = sum(1 for v in voices.values()
                         if v.get('provider') == 'gtts')

        self.log(f"âœ… {len(voices)} voces cargadas:")
        if edge_count > 0:
            self.log(f"   â€¢ {edge_count} voces Edge-TTS (gratis)")
        if eleven_count > 0:
            self.log(f"   â€¢ {eleven_count} voces ElevenLabs")
        if gtts_count > 0:
            self.log(f"   â€¢ {gtts_count} voces gTTS (gratis)")

        if eleven_count == 0:
            self.log(f"ðŸ’¡ Para usar voces de ElevenLabs:")
            self.log(
                f"   1. ObtÃ©n tu API key en: https://elevenlabs.io/app/settings/api-keys")
            self.log(
                f"   2. Agrega ELEVENLABS_API_KEY=tu_api_key en el archivo .env")
            self.log(f"   3. Reinicia la aplicaciÃ³n")

        # Habilitar botÃ³n de preview
        preview_available = any(
            v.get('provider') in ('edge-tts', 'elevenlabs')
            for v in voices.values()
        )
        self.btn_preview_voice.setEnabled(preview_available)

        self.update_cost_display()

    def preview_voice(self):
        """Reproduce una muestra de la voz seleccionada"""
        if not hasattr(self, 'elevenlabs_voices') or not self.elevenlabs_voices:
            QMessageBox.warning(self, "Muestra de voz", "Las voces aun no se han cargado. Espera un momento.")
            return
        
        selected_voice = self.voice_combo.currentText()
        if not selected_voice or selected_voice == "Cargando voces...":
            QMessageBox.warning(self, "Muestra de voz", "Selecciona una voz primero.")
            return
        
        voice_info = self.elevenlabs_voices.get(selected_voice)
        if not voice_info:
            QMessageBox.warning(self, "Muestra de voz", f"No se encontro informacion para la voz '{selected_voice}'.")
            return
        
        try:
            # Obtener el idioma seleccionado
            language = 'es' if self.lang_es.isChecked() else 'en'
            voice_id = voice_info.get('id')
            
            if not voice_id:
                QMessageBox.warning(self, "Muestra de voz", "La voz seleccionada no tiene un ID valido.")
                return
            
            # Texto de muestra segÃºn el idioma
            sample_texts = {
                'es': "Hola, esta es una muestra de la voz seleccionada. Â¿Te gusta cÃ³mo suena?",
                'en': "Hello, this is a sample of the selected voice. How do you like it?"
            }
            sample_text = sample_texts.get(language, sample_texts['es'])
            
            # Deshabilitar botÃ³n mientras se genera
            self.btn_preview_voice.setEnabled(False)
            self.btn_preview_voice.setText("Generando...")
            
            # Generar y reproducir la muestra
            tts = self._create_tts_generator()
            success = tts.play_voice_sample(voice_id, language)
            
            # Rehabilitar botÃ³n
            self.btn_preview_voice.setEnabled(True)
            self.btn_preview_voice.setText("Escuchar muestra")
            
            if not success:
                QMessageBox.warning(self, "Muestra de voz", "No se pudo reproducir la muestra de voz. Verifica que la voz sea valida.")
        
        except Exception as e:
            self.btn_preview_voice.setEnabled(True)
            self.btn_preview_voice.setText("Escuchar muestra")
            QMessageBox.critical(self, "Error en muestra de voz", f"Error al reproducir la muestra de voz:\n{str(e)}")

    def show_subtitle_style_preview(self, _index=None):
        """Abre la ventana con las animaciones de ejemplo de cada estilo."""
        try:
            from subtitle_style_preview_dialog import SubtitleStylePreviewDialog

            etiquetas = [self.subtitle_style_combo.itemText(i)
                         for i in range(self.subtitle_style_combo.count())]
            dialogo = SubtitleStylePreviewDialog(
                self, labels=etiquetas,
                current_label=self.subtitle_style_combo.currentText())
            if dialogo.exec() == QDialog.DialogCode.Accepted:
                elegido = dialogo.selected_label
                idx = self.subtitle_style_combo.findText(elegido)
                if idx >= 0 and idx != self.subtitle_style_combo.currentIndex():
                    self.subtitle_style_combo.setCurrentIndex(idx)
                    self.log(f" Estilo de subtitulos: {elegido}")
        except Exception as exc:
            self.log(f" No se pudo abrir la vista previa de subtitulos: {exc}")

    def get_subtitle_style_name(self):
        """Obtiene el nombre del estilo de subtÃ­tulos seleccionado"""
        if hasattr(self, 'subtitle_style_combo'):
            return self.subtitle_style_combo.currentText()
        return "ðŸ”¥ Hormozi (Amarillo + Karaoke + Emojis)"  # Valor por defecto

    def show_music_browser(self):
        """Muestra el diÃ¡logo de bÃºsqueda de mÃºsica"""
        try:
            self.log("ðŸŽµ Abriendo buscador de mÃºsica...")
            dialog = MusicBrowserDialog(self, log_callback=self.log)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Soporte multi-pista: el dialog puede devolver una lista (selected_music_paths)
                # o una pista única (selected_music_path) para compatibilidad con Jamendo.
                new_paths = list(getattr(dialog, 'selected_music_paths', None) or [])
                if not new_paths and getattr(dialog, 'selected_music_path', None):
                    new_paths = [dialog.selected_music_path]

                if new_paths:
                    if not hasattr(self, 'selected_music_paths'):
                        self.selected_music_paths = []
                    self.selected_music_paths.extend(new_paths)

                    # Mantener compatibility: primera pista como selected_music_path
                    if not self.selected_music_path:
                        self.selected_music_path = new_paths[0]
                        self.selected_music_metadata = dialog.selected_music_metadata

                    added_names = [os.path.basename(p) for p in new_paths]
                    self.log(f"✅ Música añadida: {', '.join(added_names)}")

                    # Actualizar label en la UI
                    if hasattr(self, 'selected_music_label'):
                        track_names = [os.path.basename(p) for p in self.selected_music_paths]
                        if len(track_names) == 1:
                            self.selected_music_label.setText(f"Pista seleccionada: {track_names[0]}")
                        else:
                            self.selected_music_label.setText(f"Playlist ({len(track_names)}): {', '.join(track_names)}")

                    # Aviso preventivo: YouTube Shorts >60s no acepta bien audio con copyright detectado.
                    try:
                        selected_source = ""
                        if isinstance(self.selected_music_metadata, dict):
                            selected_source = str(self.selected_music_metadata.get('source', '') or '').strip().lower()

                        output_profiles = self.get_selected_output_profiles() if hasattr(self, 'get_selected_output_profiles') else []
                        targets_youtube_short = any(
                            isinstance(profile, dict) and profile.get('platform') == 'youtube_short'
                            for profile in output_profiles
                        )

                        storyboard_duration = 0.0
                        if targets_youtube_short and isinstance(getattr(self, 'last_storyboard_data', None), dict):
                            segments = self.last_storyboard_data.get('segments', []) or []
                            try:
                                storyboard_duration = max(float(seg.get('end', 0) or 0) for seg in segments) if segments else 0.0
                            except Exception:
                                storyboard_duration = 0.0

                        if selected_source == 'jamendo' and targets_youtube_short and storyboard_duration > 60.0:
                            warn_msg = (
                                "YouTube Shorts over 60 seconds can reject copyright-detected music.\n\n"
                                "Jamendo music will be disabled automatically during export for this format.\n"
                                "Use a local track with rights if you want background music in this case."
                            )
                            self.log("️ Shorts >60s detectado: pista Jamendo se desactivará automáticamente al exportar.")
                            QMessageBox.information(self, "Jamendo en Shorts >60s", warn_msg)
                    except Exception:
                        pass

                    # Auto-guardar despuÃ©s de seleccionar mÃºsica
                    if self.auto_save_enabled and hasattr(self, 'project_manager'):
                        self.project_manager.auto_save_project("despuÃ©s de seleccionar mÃºsica")
                else:
                    self.log("âš ï¸ No se seleccionÃ³ mÃºsica")
            else:
                self.log("âš ï¸ SelecciÃ³n de mÃºsica cancelada")

        except Exception as e:
            error_msg = f"Error abriendo buscador de mÃºsica: {e}"
            print(f"âŒ {error_msg}")
            import traceback
            traceback.print_exc()
            self.log(f"âŒ {error_msg}")
            QMessageBox.critical(
                self,
                "Error al abrir buscador de mÃºsica",
                f"{error_msg}\n\nPuedes continuar usando mÃºsica automÃ¡tica o sin mÃºsica.\n\n"
                f"Detalles tÃ©cnicos:\n{traceback.format_exc()}"
            )

    def generate_short_teaser_manual(self):
        """Genera un short teaser manualmente a partir del video largo ya generado"""
        if not hasattr(self, 'last_generated_video_data') or not self.last_generated_video_data:
            QMessageBox.warning(
                self,
                "No hay video",
                "Primero debes ensamblar un video antes de generar el teaser."
            )
            return

        if not hasattr(self, 'last_storyboard_data') or not self.last_storyboard_data:
            QMessageBox.warning(
                self,
                "No hay storyboard",
                "No se encontrÃ³ el storyboard del video largo.\n"
                "El teaser requiere el storyboard para generar el contenido."
            )
            return

        reply = QMessageBox.question(
            self,
            "Generar teaser corto",
            "¿Deseas generar un teaser corto (30-60s) en formato vertical 9:16?\n\n"
            "El teaser se generara a partir del video largo ya ensamblado.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # Obtener parÃ¡metros del storyboard
            storyboard = self.last_storyboard_data
            language = storyboard.get('language', 'es')
            
            # Detectar idioma del script si estÃ¡ disponible
            script = storyboard.get('script', '')
            if script and len(script) > 0:
                script_sample = script[:100].lower()
                if any(word in script_sample for word in ['the', 'and', 'was', 'were', 'this', 'that', 'from']):
                    language = 'en'

            voice_id = storyboard.get('voice_id')
            if not voice_id:
                # Obtener voice_id de la voz seleccionada
                selected_voice = self.voice_combo.currentText()
                voice_id = self.elevenlabs_voices.get(selected_voice, {}).get('id')

            # Deshabilitar botÃ³n
            self.btn_generate_teaser.setEnabled(False)
            self.btn_generate_teaser.setText("Generando teaser...")
            if hasattr(self, 'progress_bar') and self.progress_bar:
                self.progress_bar.show()
            self.log("\nGenerando teaser corto...")

            # Crear worker para generar teaser
            from auto_video_generator_pyqt6_adapter import VideoGenerationWorker
            self.current_worker = VideoGenerationWorker(self.generator, "generate_teaser")
            self.current_worker.set_params(
                long_video_storyboard=storyboard,
                language=language,
                voice_id=voice_id,
                disable_wikimedia=False
            )
            self._bind_current_worker_to_project()

            # Asegurarse de que el thread anterior termine
            if self.current_thread and self.current_thread.isRunning():
                self.current_thread.quit()
                if not self.current_thread.wait(5000):
                    self.current_thread.terminate()
                    if not self.current_thread.wait(3000):
                        self.log("️ Thread anterior no terminó a tiempo, continuando...")

            # Conectar seÃ±ales
            def on_teaser_finished(result):
                if not self._should_accept_current_worker_callback():
                    self.log("️ Resultado de teaser obsoleto ignorado.")
                    return
                self.log("\nTeaser corto generado correctamente")
                if result.get('video_path'):
                    self.log(f"Teaser guardado en: {result['video_path']}")
                    # Actualizar last_generated_video_data con el teaser
                    if not self.last_generated_video_data:
                        self.last_generated_video_data = {}
                    self.last_generated_video_data['teaser_video_path'] = result['video_path']
                    self.last_generated_video_data['teaser_duration'] = result.get('duration')
                self.btn_generate_teaser.setEnabled(True)
                self.btn_generate_teaser.setText("Generar teaser corto")
                if hasattr(self, 'progress_bar') and self.progress_bar:
                    self.progress_bar.hide()
                self.cleanup_thread()

            def on_teaser_error(error):
                if not self._should_accept_current_worker_callback():
                    self.log("️ Error de teaser obsoleto ignorado.")
                    return
                self.log(f"\nâŒ Error generando teaser: {error}")
                QMessageBox.critical(self, "Error", f"Error generando teaser:\n{error}")
                self.btn_generate_teaser.setEnabled(True)
                self.btn_generate_teaser.setText("Generar teaser corto")
                if hasattr(self, 'progress_bar') and self.progress_bar:
                    self.progress_bar.hide()
                self.cleanup_thread()

            self.current_worker.finished.connect(on_teaser_finished)
            self.current_worker.error.connect(on_teaser_error)
            self.current_worker.progress.connect(self.log)

            # Ejecutar en thread
            self.current_thread = QThread()
            self.current_worker.moveToThread(self.current_thread)
            self.current_thread.started.connect(self.current_worker.run)
            self.current_thread.start()

        except Exception as e:
            self.log(f"\nâŒ Error iniciando generaciÃ³n de teaser: {e}")
            QMessageBox.critical(self, "Error", f"Error iniciando generaciÃ³n de teaser:\n{str(e)}")
            if hasattr(self, 'btn_generate_teaser'):
                self.btn_generate_teaser.setEnabled(True)
                self.btn_generate_teaser.setText("Generar teaser corto")
            if hasattr(self, 'progress_bar') and self.progress_bar:
                self.progress_bar.hide()
            import traceback
            traceback.print_exc()

    def change_voice_narration(self):
        """Cambia la voz de narraciÃ³n del proyecto actual"""
        from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QProgressDialog
        import asyncio

        # Verificar que hay un proyecto cargado
        if not hasattr(self, 'current_project_path') or not self.current_project_path:
            QMessageBox.warning(
                self,
                "No hay proyecto",
                "Primero debes cargar un proyecto antes de cambiar la voz.\n\n"
                "Ve a: Proyectos â†’ Cargar Proyecto"
            )
            return

        # Verificar que existe el storyboard
        if not hasattr(self, 'last_storyboard_data') or not self.last_storyboard_data:
            QMessageBox.warning(
                self,
                "No hay storyboard",
                "El proyecto no tiene un storyboard generado.\n"
                "No se puede cambiar la voz sin un script."
            )
            return

        # Obtener el script del storyboard
        script = self.last_storyboard_data.get('script', '')
        if not script or len(script) < 10:
            QMessageBox.warning(
                self,
                "Script vacÃ­o",
                "El proyecto no tiene un script vÃ¡lido para narrar."
            )
            return

        # Crear diÃ¡logo para seleccionar nueva voz
        dialog = QDialog(self)
        dialog.setWindowTitle("Cambiar voz de narracion")
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout(dialog)

        # InformaciÃ³n
        info_label = QLabel(
            f"Script actual: {len(script)} caracteres\n\n"
            "Selecciona la nueva voz para regenerar el audio:"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("padding: 10px; color: #2f3b47;")
        layout.addWidget(info_label)

        # ComboBox de voces
        voice_label = QLabel("Nueva voz de narracion:")
        layout.addWidget(voice_label)

        voice_combo = QComboBox()
        voice_combo.setMinimumHeight(40)

        # Agregar voces disponibles desde el diccionario de voces
        if hasattr(self, 'elevenlabs_voices') and self.elevenlabs_voices:
            voice_names = list(self.elevenlabs_voices.keys())
            voice_combo.addItems(voice_names)
        else:
            # Fallback: intentar obtener del combo principal
            for i in range(self.voice_combo.count()):
                voice_combo.addItem(self.voice_combo.itemText(i))

        # Seleccionar la voz actual si estÃ¡ disponible
        current_voice = self.voice_combo.currentText() if hasattr(self, 'voice_combo') else ""
        current_index = voice_combo.findText(current_voice)
        if current_index >= 0:
            voice_combo.setCurrentIndex(current_index)

        layout.addWidget(voice_combo)

        # Botones
        button_layout = QVBoxLayout()

        btn_generate = QPushButton("Regenerar audio con nueva voz")
        btn_generate.setMinimumHeight(45)
        btn_generate.setObjectName("accent")

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setMinimumHeight(40)

        button_layout.addWidget(btn_generate)
        button_layout.addWidget(btn_cancel)
        layout.addLayout(button_layout)

        # Conectar botones
        btn_cancel.clicked.connect(dialog.reject)

        def on_generate_clicked():
            # Obtener voz seleccionada ANTES de cerrar el diÃ¡logo
            selected_voice = voice_combo.currentText()
            voice_id = self.elevenlabs_voices.get(selected_voice, {}).get('id')

            if not voice_id:
                QMessageBox.warning(
                    self,
                    "Voz no vÃ¡lida",
                    f"No se pudo obtener el ID de la voz seleccionada: {selected_voice}"
                )
                return

            dialog.accept()

            # Iniciar generaciÃ³n en thread separado
            self._start_voice_regeneration(script, voice_id, selected_voice)

        btn_generate.clicked.connect(on_generate_clicked)

        dialog.exec()

    def _start_voice_regeneration(self, script, voice_id, selected_voice):
        """Inicia la regeneraciÃ³n de audio en un thread separado"""
        from PyQt6.QtCore import QThread, pyqtSignal
        from PyQt6.QtWidgets import QProgressDialog, QMessageBox
        import time
        from pathlib import Path

        # Preparar ruta de salida
        from video_config import VideoConfig
        audio_dir = VideoConfig.AUDIO_DIR
        audio_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        audio_filename = f"auto_{timestamp}.mp3"
        audio_path = audio_dir / audio_filename

        self.log(f"\nðŸŽ™ï¸ Regenerando audio con voz: {selected_voice}")
        self.log(f"   Voice ID: {voice_id}")
        self.log(f"   Script: {len(script)} caracteres")

        # Crear worker thread
        class AudioGeneratorWorker(QThread):
            finished = pyqtSignal(str)  # audio_path
            error = pyqtSignal(str)
            progress_update = pyqtSignal(str)
            progress_percent = pyqtSignal(int)  # 0-100

            def __init__(self, script, voice_id, audio_path):
                super().__init__()
                self.script = script
                self.voice_id = voice_id
                self.audio_path = str(audio_path)

            def run(self):
                try:
                    import asyncio
                    import edge_tts

                    self.progress_percent.emit(5)
                    self.progress_update.emit("ðŸŽ™ï¸ Conectando con Edge-TTS...")

                    async def generate():
                        self.progress_percent.emit(10)
                        self.progress_update.emit("ðŸ“ Preparando texto...")

                        communicate = edge_tts.Communicate(self.script, self.voice_id)

                        self.progress_percent.emit(20)
                        self.progress_update.emit("ðŸ”Š Generando audio (esto puede tardar)...")

                        # Edge-TTS no tiene callback de progreso, simulamos progreso
                        await communicate.save(self.audio_path)

                    # Crear nuevo event loop para este thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(generate())
                    finally:
                        loop.close()

                    self.progress_percent.emit(100)
                    self.progress_update.emit("âœ… Audio generado correctamente")
                    self.finished.emit(self.audio_path)

                except Exception as e:
                    self.error.emit(str(e))

        # Mostrar diÃ¡logo de progreso con porcentaje
        progress = QProgressDialog(
            "Regenerando audio con nueva voz...\nEsto puede tomar 1-2 minutos.",
            "Cancelar",
            0,
            100,
            self
        )
        progress.setWindowTitle("ðŸŽ™ï¸ Generando Audio")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(400)
        progress.setValue(0)
        progress.show()

        # Timer para simular progreso mientras se genera (Edge-TTS no tiene callbacks)
        from PyQt6.QtCore import QTimer
        self._progress_value = 20

        def simulate_progress():
            if self._progress_value < 90:
                self._progress_value += 2
                progress.setValue(self._progress_value)
                progress.setLabelText(f"Generando audio... {self._progress_value}%\nEsto puede tomar 1-2 minutos.")

        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(simulate_progress)
        self._progress_timer.start(1000)  # Cada segundo

        # Crear y configurar worker
        self._audio_worker = AudioGeneratorWorker(script, voice_id, audio_path)

        def on_finished(result_path):
            self._progress_timer.stop()
            progress.setValue(100)
            progress.close()
            self._on_audio_generation_finished(result_path, selected_voice, timestamp)

        def on_error(error_msg):
            self._progress_timer.stop()
            progress.close()
            self.log(f"âŒ Error generando audio: {error_msg}")
            QMessageBox.critical(
                self,
                "Error",
                f"Error al regenerar el audio:\n\n{error_msg}"
            )

        def on_progress(msg):
            self.log(f"   {msg}")

        self._audio_worker.finished.connect(on_finished)
        self._audio_worker.error.connect(on_error)
        self._audio_worker.progress_update.connect(on_progress)
        progress.canceled.connect(self._audio_worker.terminate)

        self._audio_worker.start()

    def _on_audio_generation_finished(self, audio_path, selected_voice, timestamp):
        """Callback cuando el audio se genera exitosamente"""
        from PyQt6.QtWidgets import QMessageBox
        from pathlib import Path
        import json

        audio_path = Path(audio_path)

        if not audio_path.exists():
            QMessageBox.critical(self, "Error", "No se generÃ³ el archivo de audio")
            return

        audio_size_mb = audio_path.stat().st_size / 1024 / 1024
        self.log(f"âœ… Audio generado: {audio_path.name} ({audio_size_mb:.2f} MB)")

        # ------------------------------------------------------------
        # RE-TRANSCRIPCIÃ“N AUTOMÃTICA PARA SINCRONIZACIÃ“N
        # ------------------------------------------------------------
        try:
            self.log("   ðŸ”„ Re-sincronizando segmentos con el nuevo audio...")
            
            # 1. Obtener idioma del proyecto actual
            language = 'es'
            if hasattr(self, 'last_storyboard_data') and self.last_storyboard_data:
                language = self.last_storyboard_data.get('language', 'es')
            
            # 2. Transcribir el nuevo audio
            if self.generator and self.generator.subtitle_gen:
                # Usar Whisper para obtener los nuevos timestamps exactos
                new_segments = self.generator.subtitle_gen.transcribe_audio(str(audio_path), language=language)
                
                if new_segments and hasattr(self, 'last_storyboard_data') and self.last_storyboard_data:
                    old_segments = self.last_storyboard_data.get('segments', [])
                    
                    self.log(f"      ðŸ“Š Segmentos antiguos: {len(old_segments)} | Nuevos: {len(new_segments)}")
                    
                    # 3. Mapear datos visuales a los nuevos segmentos
                    # Intentamos preservar las imÃ¡genes y videos asignados a cada parte del guion
                    
                    final_segments = []
                    for i, new_seg in enumerate(new_segments):
                        seg_data = new_seg.copy()
                        
                        # Asegurar campos clave
                        seg_data['segment_id'] = i + 1
                        seg_data['narration_text'] = new_seg.get('text', '')
                        seg_data['timestamp_start'] = new_seg.get('start', 0.0)
                        seg_data['duration'] = new_seg.get('end', 0.0) - new_seg.get('start', 0.0)
                        
                        # Intentar recuperar datos visuales del segmento correspondiente
                        if i < len(old_segments):
                            old_seg = old_segments[i]
                            # Copiar campos visuales importantes
                            for field in ['visual_prompt', 'image_path', 'image_source', 'video_path', 'video_source', 'assigned_filename', 'overlay_filename']:
                                if field in old_seg:
                                    seg_data[field] = old_seg[field]
                        else:
                            # Si hay mÃ¡s segmentos nuevos, intentar heredar del Ãºltimo
                            if old_segments:
                                seg_data['visual_prompt'] = old_segments[-1].get('visual_prompt', '')
                        
                        final_segments.append(seg_data)
                    
                    # Actualizar storyboard data
                    self.last_storyboard_data['segments'] = final_segments
                    self.log(f"      âœ… SincronizaciÃ³n completada: {len(final_segments)} segmentos actualizados")
                else:
                    self.log("      âš ï¸ No se pudieron generar nuevos segmentos o no hay datos previos")
            else:
                self.log("      âš ï¸ Generador de subtÃ­tulos no disponible")
                
        except Exception as e:
            self.log(f"   âš ï¸ Error en re-sincronizaciÃ³n: {e}")
            import traceback
            traceback.print_exc()

        # Actualizar proyecto JSON
        try:
            with open(self.current_project_path, 'r', encoding='utf-8') as f:
                project = json.load(f)

            # Crear backup
            backup_path = Path(self.current_project_path).parent / f"{Path(self.current_project_path).stem}_backup_{timestamp}.json"
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(project, f, ensure_ascii=False, indent=2)

            self.log(f"   ðŸ’¾ Backup creado: {backup_path.name}")

            # Actualizar configuraciÃ³n
            voice_id = self.elevenlabs_voices.get(selected_voice, {}).get('id', '')
            project['config']['audio_path'] = str(audio_path)
            project['config']['voice_id'] = voice_id
            project['config']['voice_name'] = selected_voice

            # TambiÃ©n actualizar last_storyboard_data
            if hasattr(self, 'last_storyboard_data') and self.last_storyboard_data:
                self.last_storyboard_data['audio_path'] = str(audio_path)
                self.last_storyboard_data['voice_id'] = voice_id
            
            # GUARDAR SEGMENTOS ACTUALIZADOS EN EL PROYECTO
            if hasattr(self, 'last_storyboard_data') and 'segments' in self.last_storyboard_data:
                project['segments'] = self.last_storyboard_data['segments']

            # Guardar proyecto actualizado
            with open(self.current_project_path, 'w', encoding='utf-8') as f:
                json.dump(project, f, ensure_ascii=False, indent=2)

            self.log(f"   âœ… Proyecto actualizado con nuevo audio")

        except Exception as e:
            self.log(f"âš ï¸ Error actualizando proyecto: {e}")

        # Preguntar si desea reensamblar el video
        reply = QMessageBox.question(
            self,
            "âœ… Audio Regenerado",
            f"Audio regenerado exitosamente con la voz: {selected_voice}\n\n"
            f"Archivo: {audio_path.name} ({audio_size_mb:.2f} MB)\n\n"
            "âš ï¸ NOTA: Si los subtÃ­tulos aparecen desfasados, es porque\n"
            "la nueva voz tiene diferente velocidad. En ese caso,\n"
            "desactiva los subtÃ­tulos o regenera el storyboard completo.\n\n"
            "Â¿Deseas reensamblar el video ahora con el nuevo audio?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Usar el botÃ³n de ensamblar existente
            if hasattr(self, 'assembly_handlers'):
                self.assembly_handlers.assemble_video()
            else:
                self.log("âš ï¸ Para reensamblar, usa el botÃ³n 'Ensamblar Video' manualmente")

    def on_voices_error(self, error_msg):
        """Callback cuando hay error cargando voces"""
        self._set_voice_loader_busy(False)
        self.log(f"âš ï¸ Error cargando voces: {error_msg}")
        self.elevenlabs_voices = self._get_voice_fallback_catalog()
        self.voice_combo.clear()
        self.voice_combo.addItems(list(self.elevenlabs_voices.keys()))
        self._apply_voice_selection()

        edge_count = sum(
            1 for v in self.elevenlabs_voices.values()
            if v.get('provider') == 'edge-tts'
        )
        if edge_count > 0:
            self.log(f" Se recuperaron {edge_count} voces Edge-TTS desde cache local.")
        else:
            self.log("ℹ️ Se dejo gTTS como fallback minimo. Puedes usar 'Recargar voces' para reintentar.")

        preview_available = any(
            v.get('provider') in ('edge-tts', 'elevenlabs')
            for v in self.elevenlabs_voices.values()
        )
        self.btn_preview_voice.setEnabled(preview_available)
        self.update_cost_display()

    def on_duration_slider_pressed(self):
        """Cuando se presiona el slider de duraciÃ³n"""
        # El tooltip se mostrarÃ¡ en sliderMoved
        pass

    def on_duration_slider_moved(self, value):
        """Cuando se mueve el slider de duraciÃ³n - mostrar tiempo sobre el slider"""
        from PyQt6.QtWidgets import QToolTip
        from PyQt6.QtCore import QPoint

        # Convertir segundos a formato legible
        minutes = value // 60
        seconds = value % 60
        if minutes > 0:
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{seconds}s"

        # Calcular posiciÃ³n del handle del slider
        min_val = self.duration_slider.minimum()
        max_val = self.duration_slider.maximum()
        ratio = (value - min_val) / (max_val -
                 min_val) if max_val > min_val else 0

        # Obtener posiciÃ³n del slider
        slider_pos = self.duration_slider.pos()
        slider_width = self.duration_slider.width()

        # Calcular posiciÃ³n X del handle (centrado en el handle)
        handle_pos_x = int(ratio * slider_width)

        # Convertir a coordenadas globales (arriba del slider)
        tooltip_pos = self.duration_slider.mapToGlobal(
            QPoint(handle_pos_x, -30))

        # Mostrar tooltip
        QToolTip.showText(
    tooltip_pos,
    time_str,
    self.duration_slider,
    self.duration_slider.rect(),
     2000)

    def on_duration_slider_released(self):
        """Cuando se suelta el slider de duraciÃ³n"""
        self._enforce_duration_policy_for_selected_platform()
        # Actualizar el label final y ocultar tooltip
        value = self.duration_slider.value()
        self.duration_label.setText(f"{value}s")
        from PyQt6.QtWidgets import QToolTip
        QToolTip.hideText()

    def update_cost_display(self):
        """Actualiza la visualizaciÃ³n de costos"""
        try:
            duration = max(
                int(self.duration_slider.value()),
                int(self._get_min_duration_for_selected_platform())
            )

            selected_voice = self.voice_combo.currentText()
            voice_info = self.elevenlabs_voices.get(selected_voice, {})
            use_eleven = (voice_info.get('provider') == 'elevenlabs')

            use_whisper = self.subtitles_check.isChecked()

            visual_mode = 'static' if self.visual_static.isChecked() else 'mixed'

            # Calcular costos
            result = self.cost_calculator.calculate_video_cost(
                duration, use_eleven, use_whisper, visual_mode=visual_mode
            )

            # Actualizar labels
            self.cost_label.setText(
                f"Costo Total: {result['total_cost_formatted']}")
            self.cost_note_label.setText(result['note'])

            time_min = result['costs']['processing']['time_minutes']
            self.time_label.setText(f"Tiempo: ~{time_min} min")

            # Actualizar desglose
            voice_srv = result['costs']['voice'].get('service', 'N/A')
            visuals_text = result['resources_used']['videos']

            breakdown = f"""ðŸ“Š Desglose:
â€¢ Voz ({voice_srv}): ${result['costs']['voice']['cost']:.4f}
â€¢ SubtÃ­tulos: ${result['costs']['subtitles']['cost']:.4f}
â€¢ Procesamiento: ${result['costs']['processing']['cost']:.4f}

ðŸ“¦ Recursos estimados:
â€¢ Palabras: {result['resources_used']['words']}
â€¢ Visuales: {visuals_text}
"""
            self.cost_breakdown.setPlainText(breakdown)

        except Exception as e:
            pass  # Fallar silenciosamente


    def _generate_audio_for_storyboard(self, storyboard_data):
        """Genera el audio de narraciÃ³n para un storyboard cargado manualmente"""
        return self.storyboard_handlers._generate_audio_for_storyboard(storyboard_data)

    def generate_storyboard(self):
        """Genera el storyboard (Paso 1)"""
        return self.storyboard_handlers.generate_storyboard()

    def on_storyboard_finished(self, result, auto_search_images=False):
        """Callback cuando el storyboard estÃ¡ listo

        Args:
            result: Datos del storyboard generado
            auto_search_images: Si True, busca imÃ¡genes automÃ¡ticamente por assigned_filename.
                               Ãštil al cargar proyectos guardados. Por defecto False.
        """
        if self._loading_project:
            self.apply_loaded_project_storyboard(result, auto_search_images=auto_search_images)
            return

        if not self._should_accept_current_worker_callback():
            self.log("️ Resultado de storyboard descartado: pertenece a otro proyecto o "
                     "a un estado anterior. Si el guion quedo guardado, abrilo con "
                     "'Abrir proyecto' y los botones se habilitan.")
            return

        self.log("\nâœ… PASO 1 COMPLETADO")
        # Flag para evitar que _sync_timeline_editor_to_storyboard sobreescriba
        # el nuevo storyboard con segmentos obsoletos del timeline anterior
        self._storyboard_just_generated = True
        if isinstance(result, dict) and not result.get('generated_at'):
            result['generated_at'] = time.time()
        self.last_storyboard_data = result
        segment_count = len((result or {}).get('segments') or [])
        print(f"[Storyboard] Aceptado en memoria: {segment_count} segmento(s)")
        self.log(f" Storyboard en memoria: {segment_count} segmento(s). Guardando proyecto...")

        # Poblar panel de revisiÃ³n
        self.populate_review_panel(
    result, auto_search_images=auto_search_images)

        # Habilitar botones
        self.btn_storyboard.setEnabled(True)
        # Habilitar generaciÃ³n de imÃ¡genes
        self.btn_generate_images.setEnabled(True)
        if hasattr(self, 'btn_export_recraft_prompts'):
            self.btn_export_recraft_prompts.setEnabled(True)
        if hasattr(self, 'btn_open_timeline'):
            # Habilitar botÃ³n de Timeline Editor
            self.btn_open_timeline.setEnabled(True)
        self._refresh_thumbnail_module_state()
        if hasattr(self, 'progress_bar') and self.progress_bar:
            self.progress_bar.hide()

        self.update_status("Storyboard listo - Revisa y edita si deseas")

        # Siempre persistir el storyboard nuevo. Si no, al abrir el timeline se
        # recarga el project.json anterior (p. ej. 3 escenas de rechazo).
        try:
            self.auto_save_project("Storyboard generado (forzado)")
        except Exception as save_error:
            print(f"[Storyboard] Error guardando proyecto: {save_error}")
            self.log(f" Error guardando el storyboard nuevo: {save_error}")
        self._storyboard_just_generated = True

        # Cleanup thread
        self.cleanup_thread()

    def on_storyboard_error(self, error):
        """Callback cuando hay error en storyboard"""
        if not self._should_accept_current_worker_callback():
            self.log("️ Error de storyboard obsoleto ignorado.")
            return
        return self.storyboard_handlers.on_storyboard_error(error)

    def populate_review_panel(self, storyboard_data, auto_search_images=False):
        """Puebla el Timeline Editor con los datos del storyboard

        Args:
            storyboard_data: Datos del storyboard
            auto_search_images: Si True, busca imÃ¡genes automÃ¡ticamente por assigned_filename.
                               Solo debe ser True al cargar proyectos guardados o despuÃ©s de generar imÃ¡genes.
                               Por defecto False para evitar asignar imÃ¡genes antiguas a storyboards nuevos.
        """
        return self.storyboard_handlers.populate_review_panel(storyboard_data, auto_search_images)

    def generate_images(self):
        """Genera todas las imagenes para el storyboard."""
        return self.image_handlers.generate_images()

    def export_recraft_prompts_txt(self):
        """Exporta un TXT con los prompts finales de Recraft."""
        return self.image_handlers.export_recraft_prompts_txt()

    def on_images_generated(self, result):
        """Callback cuando las imÃ¡genes estÃ¡n generadas"""
        if not self._should_accept_current_worker_callback():
            self.log("️ Resultado de generación de imágenes obsoleto ignorado.")
            return
        return self.image_handlers.on_images_generated(result)

    def on_images_error(self, error):
        """Callback cuando hay error generando imÃ¡genes"""
        if not self._should_accept_current_worker_callback():
            self.log("️ Error de generación de imágenes obsoleto ignorado.")
            return
        return self.image_handlers.on_images_error(error)

    def on_recraft_prompts_exported(self, result):
        """Callback cuando termina la exportación del TXT de prompts Recraft."""
        if not self._should_accept_current_worker_callback():
            self.log("️ Resultado de exportación de prompts obsoleto ignorado.")
            return
        return self.image_handlers.on_recraft_prompts_exported(result)

    def on_recraft_prompts_error(self, error):
        """Callback cuando falla la exportación del TXT de prompts Recraft."""
        if not self._should_accept_current_worker_callback():
            self.log("️ Error de exportación de prompts obsoleto ignorado.")
            return
        return self.image_handlers.on_recraft_prompts_error(error)

    def assemble_video(self):
        """Ensambla el video (Paso 2)"""
        return self.video_assembly_handlers.assemble_video()


    def on_assemble_finished(self, result):
        """Callback cuando el video estÃ¡ ensamblado"""
        if not self._should_accept_current_worker_callback():
            self.log("️ Resultado de ensamblaje obsoleto ignorado.")
            return
        return self.video_assembly_handlers.on_assemble_finished(result)

    def auto_save_project(self, reason=""):
        """Wrapper paramÃ©trico de save_project_to_path() que no interrumpe el flujo al usuario."""
        return self.project_manager.auto_save_project(reason)

    def _on_auto_save_changed(self):
        """Actualiza el estado cuando se cambia el checkbox de autoguardado"""
        self.auto_save_enabled = self.auto_save_check.isChecked()
        if self.auto_save_enabled:
            self.auto_save_project("autoguardado activado")

    def _sync_auto_save_state(self):
        """Sincroniza el estado inicial del checkbox"""
        if hasattr(self, 'auto_save_check'):
            self.auto_save_enabled = self.auto_save_check.isChecked()

    def clear_selected_music(self):
        """Limpia la playlist actual de musica seleccionada"""
        self.selected_music_paths = []
        self.selected_music_path = None
        self.selected_music_metadata = None
        if hasattr(self, 'selected_music_label'):
            self.selected_music_label.setText("Pista seleccionada: Ninguna")
        self.log("â„¹ï¸  MÃºsica de reproducciÃ³n limpiada.")

    def on_assemble_error(self, error):
        """Callback cuando hay error ensamblando video"""
        if not self._should_accept_current_worker_callback():
            self.log("️ Error de ensamblaje obsoleto ignorado.")
            return
        return self.video_assembly_handlers.on_assemble_error(error)

    def cleanup_thread(self):
        """Limpia el thread de forma segura"""
        if self.current_thread:
            if self.current_thread.isRunning():
                self.current_thread.quit()
                if not self.current_thread.wait(
                    5000):  # Esperar mÃ¡ximo 5 segundos
                    self.current_thread.terminate()
                    if not self.current_thread.wait(3000):
                        print("️ Thread no terminó a tiempo en cleanup")
            self.current_thread.deleteLater()
            self.current_thread = None

        if self.current_worker:
            self.current_worker.deleteLater()
            self.current_worker = None
        self._current_worker_project_token = None

    def save_project(self):
        """Guarda el estado actual del proyecto"""
        return self.project_manager.save_project()

    def auto_save_project(self, reason=""):
        """Auto-guarda el proyecto sin pedir confirmaciÃ³n"""
        return self.project_manager.auto_save_project(reason)

    def load_project(self):
        """Carga un proyecto guardado"""
        return self.project_manager.load_project()
    
    def get_current_project_data(self):
        """Obtiene datos del proyecto actual para metadata y contexto."""
        try:
            project_data = None
            
            # MÃ©todo 1: Intentar obtener del proyecto JSON cargado
            if hasattr(self, 'current_project_path') and self.current_project_path:
                if os.path.exists(self.current_project_path):
                    with open(self.current_project_path, 'r', encoding='utf-8') as f:
                        project_data = json.load(f)

            if project_data and not project_data.get('segments'):
                storyboard_segments = ((project_data.get('storyboard') or {}).get('segments') or [])
                if storyboard_segments:
                    project_data['segments'] = storyboard_segments
            
            # MÃ©todo 2: Si no hay segmentos en JSON, obtener del Timeline Editor
            if not project_data or not project_data.get('segments'):
                print("ðŸ”„ Proyecto JSON sin segmentos, intentando obtener del Timeline Editor...")
                timeline_data = self.get_data_from_timeline_editor()
                if timeline_data:
                    # Si tenemos datos del Timeline, conservar la configuraciÃ³n real del proyecto.
                    if project_data:
                        timeline_segments = timeline_data.get('segments') or []
                        if timeline_segments:
                            project_data['segments'] = timeline_segments
                            storyboard = project_data.get('storyboard')
                            if not isinstance(storyboard, dict):
                                storyboard = {}
                                project_data['storyboard'] = storyboard
                            storyboard['segments'] = timeline_segments

                        if not project_data.get('title') and timeline_data.get('title'):
                            project_data['title'] = timeline_data.get('title')
                        if not project_data.get('topic') and timeline_data.get('topic'):
                            project_data['topic'] = timeline_data.get('topic')
                    else:
                        project_data = timeline_data
                else:
                    project_data = None
            
            # ValidaciÃ³n final
            if not project_data:
                print("âŒ No se pudieron obtener datos del proyecto")
                return None
            
            segments = project_data.get('segments', [])
            if not segments or len(segments) == 0:
                print(f"âŒ Proyecto sin segmentos vÃ¡lidos: {len(segments)}")
                return None
            
            # Enriquecer datos del proyecto con el tÃ­tulo real
            if 'config' in project_data:
                config = project_data['config']

                # Compatibilidad con proyectos legacy: derivar formato desde platform.
                if not config.get('video_format'):
                    if config.get('platform_key'):
                        config['video_format'] = self._legacy_platform_to_format(config.get('platform_key'))
                    elif config.get('platform'):
                        config['video_format'] = self._legacy_platform_to_format(config.get('platform'))
                
                # Usar el topic real como tÃ­tulo principal
                if 'topic' in config and config['topic']:
                    project_data['title'] = config['topic']
                    project_data['topic'] = config['topic']
                elif 'title' in config and config['title']:
                    project_data['title'] = config['title']
                    project_data['topic'] = config['title']
                
                # Detectar y guardar el idioma del proyecto
                if 'language' in config:
                    project_data['language'] = config['language']
                    print(f"ðŸŒ Idioma detectado: {config['language']}")
                else:
                    # Intentar detectar idioma desde el contenido
                    project_data['language'] = self.detect_language_from_content(project_data)
                    print(f"ðŸ” Idioma inferido: {project_data['language']}")

                project_data['video_format'] = config.get(
                    'video_format',
                    self.get_selected_video_format() if hasattr(self, 'get_selected_video_format') else '16:9'
                )
            
            # Validar que tenga un tÃ­tulo real
            title = project_data.get('title', '')
            if not title or title == 'Timeline Editor Widget' or len(title.strip()) == 0:
                # Intentar obtener tÃ­tulo del primer segmento
                if segments and len(segments) > 0:
                    first_segment = segments[0]
                    if 'title' in first_segment and first_segment['title']:
                        project_data['title'] = first_segment['title']
                    elif 'text' in first_segment and first_segment['text']:
                        # Usar primeras palabras del texto como tÃ­tulo
                        text = first_segment['text']
                        project_data['title'] = text[:50] + "..." if len(text) > 50 else text
            
            # Log para depuraciÃ³n
            print(f"ðŸ“‹ Datos del proyecto obtenidos:")
            print(f"   - TÃ­tulo: {project_data.get('title', 'N/A')}")
            print(f"   - Segmentos: {len(segments)}")
            if hasattr(self, 'current_project_path'):
                print(f"   - Ruta: {self.current_project_path}")
            
            return project_data
            
        except Exception as e:
            print(f"âŒ Error obteniendo datos del proyecto: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_data_from_timeline_editor(self):
        """Obtiene datos del Timeline Editor cuando el JSON no tiene segmentos"""
        try:
            # Buscar el Timeline Editor en los componentes
            if hasattr(self, 'timeline_editor_window') and self.timeline_editor_window:
                current_project_path = self._normalize_project_path(getattr(self, 'current_project_path', None))
                bound_project_path = None
                if hasattr(self.timeline_editor_window, 'get_bound_project_path'):
                    bound_project_path = self._normalize_project_path(
                        self.timeline_editor_window.get_bound_project_path()
                    )
                if current_project_path and bound_project_path and current_project_path != bound_project_path:
                    print(
                        "️ Omitiendo lectura de Timeline Editor ajeno: "
                        f"timeline={bound_project_path} actual={current_project_path}"
                    )
                    return None

                # Obtener segmentos del Timeline Editor
                segments = []
                if hasattr(self.timeline_editor_window, 'timeline_editor') and self.timeline_editor_window.timeline_editor:
                    if hasattr(self.timeline_editor_window.timeline_editor, 'segments'):
                        segments = self.timeline_editor_window.timeline_editor.segments
                    elif hasattr(self.timeline_editor_window.timeline_editor, 'get_segments'):
                        segments = self.timeline_editor_window.timeline_editor.get_segments()
                
                if segments and len(segments) > 0:
                    # Crear estructura de proyecto con los segmentos del Timeline
                    project_data = {
                        'title': f'Proyecto con {len(segments)} segmentos',
                        'topic': f'Proyecto con {len(segments)} segmentos',
                        'segments': segments,
                        'config': {
                            'title': f'Proyecto con {len(segments)} segmentos'
                        }
                    }
                    print(f"âœ… Obtenidos {len(segments)} segmentos del Timeline Editor")
                    return project_data
            
            print("âŒ No se pudo acceder al Timeline Editor")
            return None
            
        except Exception as e:
            print(f"âŒ Error obteniendo datos del Timeline Editor: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def detect_language_from_content(self, project_data):
        """Detecta el idioma del proyecto desde el contenido"""
        try:
            # MÃ©todo 1: Analizar el texto de los segmentos
            segments = project_data.get('segments', [])
            if segments and len(segments) > 0:
                # Tomar texto del primer segmento para anÃ¡lisis
                first_segment = segments[0]
                text = first_segment.get('text', '') or first_segment.get('narrative_text', '')
                
                if text:
                    # Palabras clave en espaÃ±ol
                    spanish_keywords = ['el', 'la', 'los', 'las', 'de', 'del', 'en', 'un', 'una', 'con', 'por', 'para', 'que', 'como', 'mÃ¡s', 'muy', 'sin', 'pero', 'sus', 'este', 'esta', 'estos', 'estas']
                    
                    # Palabras clave en inglÃ©s
                    english_keywords = ['the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy', 'did', 'car', 'let', 'put', 'say', 'she', 'too', 'use']
                    
                    # Convertir a minÃºsculas y dividir en palabras
                    words = text.lower().split()
                    spanish_count = sum(1 for word in words if word in spanish_keywords)
                    english_count = sum(1 for word in words if word in english_keywords)
                    
                    if spanish_count > english_count:
                        return 'es'
                    elif english_count > spanish_count:
                        return 'en'
            
            # MÃ©todo 2: Analizar el tÃ­tulo del proyecto
            title = project_data.get('title', '')
            if title:
                # Caracteres especÃ­ficos del espaÃ±ol
                if any(char in title for char in ['Ã±', 'Ã¡', 'Ã©', 'Ã­', 'Ã³', 'Ãº', 'Ã¼', 'Â¿', 'Â¡']):
                    return 'es'
                
                # Palabras en espaÃ±ol comunes en tÃ­tulos
                spanish_title_words = ['misterios', 'historia', 'civilizaciÃ³n', 'antiguo', 'egipto', 'mexico', 'espaÃ±a', 'amÃ©rica', 'latino']
                if any(word in title.lower() for word in spanish_title_words):
                    return 'es'
            
            # MÃ©todo 3: Analizar el topic/storyboard
            if 'storyboard' in project_data:
                storyboard = project_data['storyboard']
                if 'topic' in storyboard:
                    topic = storyboard['topic'].lower()
                    if any(char in topic for char in ['Ã±', 'Ã¡', 'Ã©', 'Ã­', 'Ã³', 'Ãº']):
                        return 'es'
            
            # Default: espaÃ±ol (por ser el idioma principal del proyecto)
            return 'es'
            
        except Exception as e:
            print(f"âš ï¸ Error detectando idioma: {e}")
            return 'es'  # Default a espaÃ±ol

    def manage_projects(self):
        """Abre el diÃ¡logo de gestiÃ³n de proyectos"""
        return self.project_manager.manage_projects()

    def load_project_from_path(self, project_path):
        """Carga un proyecto desde una ruta especÃ­fica (usado por el diÃ¡logo de gestiÃ³n)"""
        return self.project_manager.load_project_from_path(project_path)

    def validate_project_files(self, project_data):
        """Valida que los archivos referenciados en el proyecto existan"""
        return self.project_manager.validate_project_files(project_data)

    def _copy_manual_media_to_project(self, storyboard_data):
        """Copia imÃ¡genes/videos manuales y actualiza rutas en los segmentos"""
        return self.project_manager._copy_manual_media_to_project(storyboard_data)

    def _copy_manual_media_files(self, project_path, storyboard_data):
        """Copia archivos de imÃ¡genes/videos a la carpeta del proyecto"""
        return self.project_manager._copy_manual_media_files(project_path, storyboard_data)

    def _restore_media_paths(self, project_path, storyboard_data):
        """Restaura rutas relativas a absolutas para imÃ¡genes/videos manuales"""
        return self.project_manager._restore_media_paths(project_path, storyboard_data)

    def reset_to_defaults(self):
        """Resetea todos los campos y configuraciones a sus valores por defecto"""
        try:
            # Deshabilitar auto-guardado temporalmente para evitar guardar durante el reset
            self.auto_save_enabled = False
            self._project_state_token += 1
            self._current_worker_project_token = None
            self._current_thumbnail_project_token = None
            self._current_thumbnail_project_path = None
            self._loading_project = False
            if hasattr(self, '_config_auto_save_timer') and self._config_auto_save_timer:
                self._config_auto_save_timer.stop()
            self.cleanup_thread()
            
            # Limpiar ruta del proyecto
            self.current_project_path = None
            self._storyboard_just_generated = False
            if hasattr(self, '_clear_last_project_path'):
                self._clear_last_project_path()
            
            # Limpiar datos del proyecto
            self.last_storyboard_data = None
            self.last_generated_video_data = None
            
            # Resetear estado de generaciÃ³n
            self.is_generating = False
            self.cleanup_thumbnail_thread()
            self.thumbnail_data = None
            self.thumbnail_strategy = None
            self.thumbnail_variants = []
            self.selected_thumbnail_path = None
            
            # Resetear duraciÃ³n por defecto de video largo horizontal
            if hasattr(self, 'duration_slider'):
                self.duration_slider.setValue(self.LONG_HORIZONTAL_DEFAULT_DURATION_SECONDS)
            
            # Resetear formato al primer item (16:9 horizontal)
            if hasattr(self, 'platform_combo'):
                self.platform_combo.setCurrentIndex(0)
            self._enforce_duration_policy_for_selected_platform(silent=True)
            
            # Resetear idioma a EspaÃ±ol
            if hasattr(self, 'lang_es') and hasattr(self, 'lang_en'):
                self.lang_es.setChecked(True)
                self.lang_en.setChecked(False)
            
            # Resetear voz (si hay voces cargadas, seleccionar la primera)
            if hasattr(self, 'voice_combo') and self.voice_combo.count() > 0:
                # Si solo tiene "Cargando voces...", dejarlo asÃ­
                if self.voice_combo.itemText(0) != "Cargando voces...":
                    self.voice_combo.setCurrentIndex(0)
            
            # Resetear estilo visual al primer estilo de Recraft.
            if hasattr(self, 'style_combo'):
                self.style_combo.setCurrentIndex(0)
            
            # Resetear proveedor de imÃ¡genes a Recraft (primer item).
            if hasattr(self, 'image_provider_combo'):
                self.image_provider_combo.setCurrentIndex(0)
            
            # Resetear frecuencia de imÃ¡genes a 1
            if hasattr(self, 'images_per_segment_spin'):
                self.images_per_segment_spin.setValue(1)
            
            # Resetear intercalar imÃ¡genes a False
            if hasattr(self, 'interleave_images_check'):
                self.interleave_images_check.setChecked(False)
            
            # Resetear modo visual a "Mixto"
            if hasattr(self, 'visual_mixed') and hasattr(self, 'visual_static'):
                self.visual_mixed.setChecked(True)
                self.visual_static.setChecked(False)
            
            # Resetear efectos cinematogrÃ¡ficos a True
            if hasattr(self, 'cinematic_check'):
                self.cinematic_check.setChecked(True)
            
            # Resetear preset cinematogrÃ¡fico a "ðŸŽ¥ Auto-Detect (Inteligente)" (primer item)
            if hasattr(self, 'cinematic_preset_combo'):
                self.cinematic_preset_combo.setCurrentIndex(0)
            
            # Resetear tipo de transiciÃ³n a "ðŸŒ… Fade Suave" (Ã­ndice 1, que es el segundo item)
            if hasattr(self, 'transition_type_combo'):
                self.transition_type_combo.setCurrentIndex(1)
            
            # Resetear duraciÃ³n de transiciÃ³n a 0.5 segundos
            if hasattr(self, 'transition_duration_spin'):
                self.transition_duration_spin.setValue(0.5)
            
            # Resetear subtÃ­tulos a True
            if hasattr(self, 'subtitles_check'):
                self.subtitles_check.setChecked(True)
            
            # Resetear estilo de subtÃ­tulos a "ðŸŽ¬ CinematogrÃ¡fico ClÃ¡sico" (primer item)
            if hasattr(self, 'subtitle_style_combo'):
                self.subtitle_style_combo.setCurrentIndex(0)
            
            # Resetear investigaciÃ³n web a True
            if hasattr(self, 'research_check'):
                self.research_check.setChecked(True)
            
            # Limpiar mÃºsica seleccionada
            if hasattr(self, 'selected_music_path'):
                self.selected_music_path = None
            if hasattr(self, 'selected_music_metadata'):
                self.selected_music_metadata = None
            if hasattr(self, 'selected_music_label'):
                self.selected_music_label.setText("Pista seleccionada: Ninguna")
            
            # Limpiar campos del parent_gui si existen
            if hasattr(self, 'parent_gui'):
                if hasattr(self.parent_gui, 'topic_input'):
                    self.parent_gui.topic_input.clear()
                if hasattr(self.parent_gui, 'category_combo'):
                    self.parent_gui.category_combo.setCurrentIndex(0)
                if hasattr(self.parent_gui, 'last_raw_image_path'):
                    self.parent_gui.last_raw_image_path = None
                if hasattr(self.parent_gui, 'last_thumbnail_path'):
                    self.parent_gui.last_thumbnail_path = None
            
            # Limpiar log
            if hasattr(self, 'log_text'):
                self.log_text.clear()
            
            # Resetear estado
            if hasattr(self, 'status_label'):
                self.status_label.setText("Listo")
            
            # Ocultar barra de progreso
            if hasattr(self, 'progress_bar'):
                self.progress_bar.hide()
            
            # Deshabilitar botones de generaciÃ³n
            if hasattr(self, 'btn_storyboard'):
                self.btn_storyboard.setEnabled(True)
            if hasattr(self, 'btn_generate_images'):
                self.btn_generate_images.setEnabled(False)
            if hasattr(self, 'btn_export_recraft_prompts'):
                self.btn_export_recraft_prompts.setEnabled(False)
            if hasattr(self, 'btn_assemble'):
                self.btn_assemble.setEnabled(False)
            if hasattr(self, 'btn_generate_teaser'):
                self.btn_generate_teaser.setEnabled(False)
            if hasattr(self, 'btn_play_video'):
                self.btn_play_video.setEnabled(False)

            if hasattr(self, 'thumbnail_variant_combo'):
                self.thumbnail_variant_combo.clear()
            if hasattr(self, 'thumbnail_hook_label'):
                self.thumbnail_hook_label.setText("Hook seleccionado: -")
            if hasattr(self, 'thumbnail_preview'):
                self._update_studio_thumbnail_preview(None)
            self._refresh_thumbnail_module_state()
            
            # Cerrar Timeline Editor si estÃ¡ abierto
            if hasattr(self, 'timeline_editor_window') and self.timeline_editor_window:
                try:
                    if self.timeline_editor_window.isVisible():
                        self.timeline_editor_window.close()
                    self.timeline_editor_window = None
                except:
                    pass
            
            # Deshabilitar botÃ³n de Timeline Editor
            if hasattr(self, 'btn_open_timeline'):
                self.btn_open_timeline.setEnabled(False)
            
            # Actualizar display de costos
            if hasattr(self, 'update_cost_display'):
                self.update_cost_display()
            
            self.log("Configuracion restaurada a valores por defecto")
            
        except Exception as e:
            self.log(f"âš ï¸ Error reseteando configuraciÃ³n: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.auto_save_enabled = True
            if hasattr(self, 'auto_save_check'):
                self.auto_save_check.blockSignals(True)
                self.auto_save_check.setChecked(True)
                self.auto_save_check.blockSignals(False)
