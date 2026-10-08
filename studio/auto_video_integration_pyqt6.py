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

from studio.auto_video_generator_pyqt6_adapter import AutoVideoGeneratorPyQt6, VideoGenerationWorker
from channel.cost_calculator import CostCalculator

# La subida/publicación directa a YouTube fue removida de la GUI.

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("âš ï¸ pydub no disponible. La visualizaciÃ³n de forma de onda y recorte de audio no funcionarÃ¡.")

# Importar widgets extraÃ­dos
from studio.timeline_editor_window import TimelineEditorWindow
from studio.music_browser_dialog import MusicBrowserDialog
from studio.studio_project_manager import StudioProjectManager
from studio.studio_storyboard_handlers import StudioStoryboardHandlers
from studio.studio_image_handlers import StudioImageHandlers
from studio.studio_video_assembly_handlers import StudioVideoAssemblyHandlers
from ai.recraft_style_catalog import RECRAFT_STYLE_OPTIONS
from pipeline.thumbnail_pipeline import ThumbnailPipeline
from ai.groq_client import GroqAiClient


def get_channel_name(default: str = "this channel") -> str:
    """Nombre visible del canal, leido del Channel Bible.

    Import perezoso: este modulo se carga antes que el perfil en algunos flujos.
    """
    try:
        from channel.channel_strategy import get_channel_name as _real
        return _real(default)
    except Exception:
        return default


try:
    from pipeline.tts_generator import TextToSpeechGenerator as StandaloneTextToSpeechGenerator
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

from studio.studio_publishing_mixin import StudioPublishingMixin


from studio.studio_thumbnail_intelligence_mixin import StudioThumbnailIntelligenceMixin


from studio.studio_voice_mixin import StudioVoiceMixin


from studio.studio_ui_setup_mixin import StudioUiSetupMixin


class AutoVideoStudioTab(StudioUiSetupMixin, StudioVoiceMixin, StudioThumbnailIntelligenceMixin, StudioPublishingMixin, QWidget):
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
        from infra.worker_context import should_accept_worker_result

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
        candidate_bases.append(Path(__file__).resolve().parent.parent)

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
        if hasattr(self, 'category_combo'):
            self.category_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de categoria"))
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

        if hasattr(self, 'opening_style_combo'):
            self.opening_style_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de entrada del video"))

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

        if hasattr(self, 'cinematic_intensity_combo'):
            self.cinematic_intensity_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de intensidad cinematografica"))

        if hasattr(self, 'dynamism_combo'):
            self.dynamism_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de dinamismo"))
        if hasattr(self, 'blender_check'):
            self.blender_check.toggled.connect(
                lambda: self._trigger_config_auto_save("cambio de tomas 3D"))
        if hasattr(self, 'blender_quality_combo'):
            self.blender_quality_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de calidad 3D"))
        if hasattr(self, 'blender_environment_combo'):
            self.blender_environment_combo.currentIndexChanged.connect(
                lambda: self._trigger_config_auto_save("cambio de ambiente 3D"))

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

    def get_selected_opening_style(self):
        """ID estable de la entrada seleccionada en la GUI."""
        from pipeline.video_opening import OPENING_STYLE, normalize_opening_style
        if not hasattr(self, 'opening_style_combo'):
            return OPENING_STYLE
        return normalize_opening_style(self.opening_style_combo.currentData())

    def _on_opening_style_changed(self, _index=None):
        """Actualiza al instante la animacion y la descripcion de la entrada."""
        from pipeline.video_opening import opening_style_spec
        selected = self.get_selected_opening_style()
        spec = opening_style_spec(selected)
        if hasattr(self, 'opening_style_preview'):
            self.opening_style_preview.set_style(selected)
        if hasattr(self, 'opening_style_description'):
            self.opening_style_description.setText(spec['description'])

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
        root = Path(__file__).resolve().parent.parent
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
        root = Path(__file__).resolve().parent.parent
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
        start_dir = str(Path(__file__).resolve().parent.parent / "transition_overlays")
        if not os.path.isdir(start_dir):
            start_dir = str(Path(__file__).resolve().parent.parent)
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
        from infra.project_autoload import NEW_PROJECT_SENTINEL

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

        from infra.project_video_result import saved_video_result
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














    # Plataformas que aceptan miniatura propia. YouTube habilito las
    # miniaturas de Shorts el 2026-07-24; hasta entonces este modulo solo
    # tenia sentido para el vertical largo, y por eso estaba restringido.
    # El FORMATO de la miniatura lo decide `thumbnail_formats.resolve_format`
    # a partir de la plataforma: un Short la lleva 9:16 y un vertical largo
    # la lleva 16:9, porque ese va al feed normal de YouTube.
    THUMBNAIL_PLATFORMS = ('youtube_vertical', 'youtube_short')


    # Alias historico: el nombre viejo sugeria que solo servia para
    # watch time, que ya no es el caso.
    _is_watchtime_thumbnail_target = StudioThumbnailIntelligenceMixin._supports_custom_thumbnail





    # La plantilla estatica del super prompt vivia aca: 70 lineas clavadas en
    # 16:9 que ademas prohibian todo texto en la imagen. Nadie la leia (el
    # prompt real se arma en `claude_client.generate_thumbnail_super_prompt`),
    # asi que era documentacion que contradecia al codigo. Se elimino.









    # ------------------------------------------------------------------
    # Dispatch methods for LLM background threads
    # These are real bound methods on self (main-thread QObject), so PyQt6
    # automatically uses QueuedConnection when the signal crosses threads.
    # ------------------------------------------------------------------










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
                    from app.project_manager_v2 import ProjectManagerV2
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
                    from pipeline.storyboard_generator import prefer_in_memory_storyboard
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









    def show_subtitle_style_preview(self, _index=None):
        """Abre la ventana con las animaciones de ejemplo de cada estilo."""
        try:
            from studio.subtitle_style_preview_dialog import SubtitleStylePreviewDialog

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
            "Short vertical autónomo",
            "¿Generar un Short vertical 9:16 de 60–90 s que cuente la historia completa?\n\n"
            "Sale del guion del video 16:9 ya ensamblado, con imágenes nuevas en vertical y las reglas\n"
            "del canal (cifra o pregunta al abrir, sin 'mirá el video completo'). Es lo que YouTube distribuye;\n"
            "el 16:9 no tiene feed de Shorts.",
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
            from studio.auto_video_generator_pyqt6_adapter import VideoGenerationWorker
            self.current_worker = VideoGenerationWorker(self.generator, "generate_teaser")
            self.current_worker.set_params(
                long_video_storyboard=storyboard,
                language=language,
                voice_id=voice_id,
                disable_wikimedia=False,
                mode='standalone',
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
        if isinstance(result, dict) and result.get('segments'):
            try:
                from pipeline.cinematic_director import direct_storyboard
                level = (
                    self.cinematic_intensity_combo.currentData()
                    if hasattr(self, 'cinematic_intensity_combo') else 'auto'
                )
                preset = (
                    self.cinematic_preset_combo.currentText().lower()
                    if hasattr(self, 'cinematic_preset_combo') else 'auto'
                )
                direct_storyboard(result, level=level, preset=preset)
            except Exception as direction_error:
                self.log(f" [WARN] No se pudo preparar la direccion cinematografica: {direction_error}")
            # Composicion por escena: el timeline ya muestra que eligio el planificador.
            try:
                from pipeline.segment_layouts import plan_layouts
                plan_layouts(result, level=(
                    self.dynamism_combo.currentData() if hasattr(self, 'dynamism_combo') else 'off'))
            except Exception as layout_error:
                self.log(f" [WARN] No se pudo planificar la composicion: {layout_error}")
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

            # El cold open conserva el comportamiento de los proyectos previos.
            if hasattr(self, 'opening_style_combo'):
                self.opening_style_combo.setCurrentIndex(0)
            
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
            if hasattr(self, 'cinematic_intensity_combo'):
                self.cinematic_intensity_combo.setCurrentIndex(0)
            if hasattr(self, 'dynamism_combo'):
                self.dynamism_combo.setCurrentIndex(max(0, self.dynamism_combo.findData('moderate')))
            if hasattr(self, 'blender_check'):
                self.blender_check.setChecked(False)
            if hasattr(self, 'blender_quality_combo'):
                self.blender_quality_combo.setCurrentIndex(max(0, self.blender_quality_combo.findData('normal')))
            if hasattr(self, 'blender_environment_combo'):
                self.blender_environment_combo.setCurrentIndex(0)
            
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
