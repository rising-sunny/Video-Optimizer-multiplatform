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


class StudioVoiceMixin:
    def _create_tts_generator(self):
        """Crea el generador TTS sin depender del modulo pesado del pipeline."""
        if StandaloneTextToSpeechGenerator is not None:
            return StandaloneTextToSpeechGenerator()

        from pipeline.auto_video_generator_v2 import TextToSpeechGenerator
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
        from infra.video_config import VideoConfig
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
