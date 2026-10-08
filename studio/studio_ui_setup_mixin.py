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


class StudioUiSetupMixin:
    def setup_ui(self):
        """Crea la interfaz de usuario"""
        # Layout principal con scroll
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        from studio.studio_channel_controls import install_controls
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
        from studio.studio_categories import get_studio_category_names, MYSTERY_CATEGORY, MYSTERY_DESCRIPTION
        self.category_combo.addItems(get_studio_category_names())
        self.category_combo.setItemData(self.category_combo.findText(MYSTERY_CATEGORY),
                                        MYSTERY_DESCRIPTION, Qt.ItemDataRole.ToolTipRole)
        category_layout.addWidget(self.category_combo)
        category_layout.addStretch()
        layout.addLayout(category_layout)
        category_hint = QLabel(MYSTERY_DESCRIPTION)
        category_hint.setWordWrap(True)
        category_hint.setVisible(self.category_combo.currentText() == MYSTERY_CATEGORY)
        self.category_combo.currentTextChanged.connect(
            lambda name: category_hint.setVisible(name == MYSTERY_CATEGORY))
        layout.addWidget(category_hint)

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

        # Entrada cinematografica: la animacion se dibuja en vivo (tipo GIF)
        # y el ID elegido viaja hasta el storyboard y el ensamblado final.
        from studio.opening_style_preview import OpeningStylePreview
        from pipeline.video_opening import OPENING_STYLE_CHOICES, OPENING_STYLE_SPECS

        opening_layout = QHBoxLayout()
        opening_layout.setSpacing(18)
        opening_controls = QVBoxLayout()
        opening_controls.setSpacing(7)

        opening_label = QLabel("Entrada del video:")
        opening_label.setStyleSheet("font-weight: 600; color: #1f2831;")
        opening_controls.addWidget(opening_label)

        self.opening_style_combo = QComboBox()
        for style_id in OPENING_STYLE_CHOICES:
            self.opening_style_combo.addItem(OPENING_STYLE_SPECS[style_id]["label"], style_id)
        self.opening_style_combo.setMaximumWidth(330)
        self.opening_style_combo.setToolTip(
            "Define el guion, los dos primeros prompts visuales y el movimiento de los primeros segundos."
        )
        opening_controls.addWidget(self.opening_style_combo)

        self.opening_style_description = QLabel()
        self.opening_style_description.setWordWrap(True)
        self.opening_style_description.setMaximumWidth(420)
        self.opening_style_description.setStyleSheet("color: #5d6873;")
        opening_controls.addWidget(self.opening_style_description)
        opening_controls.addStretch()

        self.opening_style_preview = OpeningStylePreview()
        opening_layout.addLayout(opening_controls)
        opening_layout.addWidget(
            self.opening_style_preview,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        opening_layout.addStretch()
        layout.addLayout(opening_layout)

        self.opening_style_combo.currentIndexChanged.connect(self._on_opening_style_changed)
        self._on_opening_style_changed()

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

        cinematic_layout.addWidget(QLabel("Nivel:"))
        self.cinematic_intensity_combo = QComboBox()
        self.cinematic_intensity_combo.addItem("Automatico", "auto")
        self.cinematic_intensity_combo.addItem("Sutil", "subtle")
        self.cinematic_intensity_combo.addItem("Cinematografico", "cinematic")
        self.cinematic_intensity_combo.addItem("Epico", "epic")
        self.cinematic_intensity_combo.setMaximumWidth(170)
        self.cinematic_intensity_combo.setEnabled(self.cinematic_check.isChecked())
        self.cinematic_intensity_combo.setToolTip(
            "Controla cuantos momentos destacados reciben camara, atmosfera, "
            "iluminacion, lente y acentos sonoros de alto impacto."
        )
        self.cinematic_check.toggled.connect(self.cinematic_intensity_combo.setEnabled)
        cinematic_layout.addWidget(self.cinematic_intensity_combo)

        cinematic_layout.addStretch()

        # â† Corregido: aÃ±adir cinematic_layout
        layout.addLayout(cinematic_layout)

        # Composicion por escena (pipeline/segment_layouts) + tomas 3D opcionales.
        dynamism_layout = QHBoxLayout()
        dynamism_layout.addWidget(QLabel("Dinamismo:"))
        self.dynamism_combo = QComboBox()
        self.dynamism_combo.addItem("Apagado", "off")
        self.dynamism_combo.addItem("Moderado", "moderate")
        self.dynamism_combo.addItem("Alto", "high")
        self.dynamism_combo.setCurrentIndex(1)
        self.dynamism_combo.setMaximumWidth(150)
        self.dynamism_combo.setToolTip(
            "Composicion por escena, elegida segun el guion:\n"
            "- Pantalla dividida (comparaciones)\n"
            "- Retrato flotante con rotulo (personas nombradas, evidencia)\n"
            "- Triptico (enumeraciones)\n"
            "- Punch-in: 2-3 planos de la misma imagen (climax, planos largos)\n"
            "- Reveal: la imagen siguiente entra a mitad de escena\n"
            "Usa las imagenes que ya tenes (vecinas o detalles): no genera imagenes nuevas.\n"
            "Moderado: hasta 40% de las escenas. Alto: hasta 70%. Se ajusta por escena en el timeline."
        )
        dynamism_layout.addWidget(self.dynamism_combo)

        from pipeline.blender_shots import QUALITY_PRESETS, find_blender
        blender_exe = find_blender()
        self.blender_check = QCheckBox("Tomas 3D con Blender")
        self.blender_quality_combo = QComboBox()
        for key, spec in QUALITY_PRESETS.items():
            self.blender_quality_combo.addItem(spec["label"], key)
        self.blender_quality_combo.setCurrentIndex(self.blender_quality_combo.findData("normal"))
        self.blender_quality_combo.setMaximumWidth(120)
        if blender_exe:
            self.blender_check.setToolTip(
                "Una toma 3D en el momento fuerte del video (dos en documentales largos):\n"
                "las fotos sobre una mesa, con luz, sombras y foco que baja hasta la protagonista.\n"
                f"Blender: {blender_exe}\n"
                "Tarda minutos por toma en esta PC (Borrador ~1.6 s por cuadro, Normal ~3 s);\n"
                "queda en cache y re-ensamblar no la vuelve a renderizar."
            )
        else:
            self.blender_check.setToolTip(
                "No se encontro Blender. Instalalo o defini BLENDER_PATH en .env\n"
                "(ruta completa a blender.exe)."
            )
        self.blender_quality_combo.setToolTip(
            "Calidad del render 3D: mas calidad = mas minutos.\n"
            "El tablero de evidencias usa Normal como minimo (en Borrador el hilo sale serruchado).")

        from pipeline.segment_layouts import BLENDER_ENVIRONMENTS
        self.blender_environment_combo = QComboBox()
        for key, label in BLENDER_ENVIRONMENTS.items():
            self.blender_environment_combo.addItem(label, key)
        self.blender_environment_combo.setMaximumWidth(230)
        self.blender_environment_combo.setToolTip(
            "Ambiente de la toma 3D. Automatico elige por escena:\n"
            "- Escena de video -> TV de tubo (reproduce el video)\n"
            "- Misterio o crimen -> Tablero de evidencias (~10 min por 3.5 s)\n"
            "- Anuncio o noticia -> Periodico que gira (titulo del video en portada)\n"
            "- El resto -> Mesa con fotos\n"
            "Se puede cambiar por escena en el timeline."
        )

        def _sync_blender_controls(*_args):
            usable = bool(blender_exe) and self.dynamism_combo.currentData() != "off"
            self.blender_check.setEnabled(usable)
            self.blender_quality_combo.setEnabled(usable and self.blender_check.isChecked())
            self.blender_environment_combo.setEnabled(usable and self.blender_check.isChecked())

        self.dynamism_combo.currentIndexChanged.connect(_sync_blender_controls)
        self.blender_check.toggled.connect(_sync_blender_controls)
        _sync_blender_controls()
        dynamism_layout.addWidget(self.blender_check)
        dynamism_layout.addWidget(self.blender_quality_combo)
        dynamism_layout.addWidget(self.blender_environment_combo)
        dynamism_layout.addStretch()
        layout.addLayout(dynamism_layout)

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
        self.btn_generate_teaser = QPushButton("Short vertical (autónomo, 60–90 s)")
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
        self.chk_publish_tiktok = QCheckBox("TikTok")
        self.chk_publish_tiktok.setToolTip(
            "NO publica: deja el video como borrador en tu bandeja de TikTok y te manda\n"
            "el titulo y la descripcion por Telegram para pegarlos al terminarlo en la app.\n"
            "Primera vez: .venv\\Scripts\\python.exe tiktok_uploader.py --auth\n"
            "Verificar:   .venv\\Scripts\\python.exe tiktok_uploader.py --check"
        )
        for chk in (self.chk_publish_youtube, self.chk_publish_facebook,
                    self.chk_publish_instagram, self.chk_publish_x, self.chk_publish_tiktok):
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
                platform=self.get_selected_platform_key(),
                opening_style=self.get_selected_opening_style())
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
                         research_context, video_format, platform, opening_style):
                super().__init__()
                self._gen = generator
                self._topic = topic
                self._category = category
                self._duration = duration
                self._language = language
                self._research = research_context
                self._fmt = video_format
                self._platform = platform
                self._opening_style = opening_style

            def run(self):
                try:
                    result = self._gen.generate_scenes_json_batched(
                        self._topic, self._category, self._duration,
                        language=self._language,
                        research_context=self._research,
                        video_format=self._fmt,
                        platform=self._platform,
                        opening_style=self._opening_style,
                        progress_callback=lambda cur, tot: self.progress.emit(cur, tot)
                    )
                    self.done.emit(result)
                except Exception as e:
                    print(f"[JsonBatchThread] Error: {e}")
                    self.done.emit(None)

        self._json_batch_thread = _JsonBatchThread(
            gen, topic, category, duration, language,
            research_context, video_format, platform, self.get_selected_opening_style()
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
        from studio.auto_video_generator_pyqt6_adapter import VideoGenerationWorker
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
