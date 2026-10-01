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


class StudioThumbnailIntelligenceMixin:
    def _supports_custom_thumbnail(self) -> bool:
        return self.get_selected_platform_key() in self.THUMBNAIL_PLATFORMS


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
            script_excerpt = str(storyboard.get('script', '') or '')[:12000]
            if not script_excerpt:
                segments = storyboard.get('segments', [])
                script_excerpt = " ".join(str(s.get('text', '')) for s in segments)[:12000]

        # Deshabilitar botón mientras procesa
        self.btn_generate_super_prompt.setEnabled(False)
        self.btn_generate_super_prompt.setText("Generando...")

        # El formato manda: un Short necesita 9:16 y reglas de encuadre propias.
        from publish.thumbnail_formats import resolve_format
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

        # El angulo del guion manda la composicion del thumbnail (mecanismo ->
        # el objeto en proceso; hallazgo -> la pieza in situ...).
        _sb = self.last_storyboard_data if isinstance(getattr(self, 'last_storyboard_data', None), dict) else {}
        _arche = _sb.get('format_archetype') or ''
        if not _arche:
            try:
                from studio.studio_channel_controls import project_channel_config
                _cfg_arche = project_channel_config(self).get('format_archetype')
                _arche = _cfg_arche if _cfg_arche and _cfg_arche != 'auto' else ''
            except Exception:
                _arche = ''

        # Investigacion (thumbnail_research): miniaturas que compiten para la palabra clave,
        # acento de color que las diferencia y un texto que COMPLEMENTA al titulo.
        _title_for_brief = ""
        try:
            _mt = getattr(self.window(), 'metadata_tab', None)
            _title_for_brief = _mt.yt_title.text().strip() if _mt else ""
        except Exception:
            _title_for_brief = ""
        _title_for_brief = _title_for_brief or str(_sb.get('title') or topic)
        _script_full = str(_sb.get('script') or script_excerpt or '')
        _brief_holder = {}

        def _run():
            brief = None
            if os.getenv("THUMBNAIL_RESEARCH", "1").strip().lower() not in ("0", "false", "no", "off"):
                try:
                    from publish.thumbnail_research import build_thumbnail_brief
                    brief = build_thumbnail_brief(topic, _title_for_brief, _script_full,
                                                  archetype=_arche or "", log=lambda m: None,
                                                  thumbnail_format=fmt)
                except Exception as exc:
                    brief = {"error": f"{type(exc).__name__}: {exc}"}
            _brief_holder["brief"] = brief
            return llm_client.generate_thumbnail_super_prompt(
                topic=topic,
                script_excerpt=_script_full[:12000],
                category=category,
                language=language,
                thumbnail_format=fmt,
                render_text=render_text,
                format_archetype=_arche or None,
                research_brief=brief if brief and not brief.get("error") else None,
            )

        def _on_done(result):
            self.btn_generate_super_prompt.setEnabled(True)
            self.btn_generate_super_prompt.setText("Generar Super Prompt (IA externa)")
            _brief = _brief_holder.get("brief") or {}
            if _brief.get("error"):
                self.log(f" Miniatura: investigacion no disponible ({_brief['error']}); prompt con valores por defecto.")
            elif _brief:
                self.log(f" Miniatura (investigacion): palabra clave '{_brief.get('keyword')}'")
                for _n in _brief.get("differentiation", []):
                    self.log(f"   - {_n}")
                if _brief.get("text_options"):
                    self.log("   - texto: " + ", ".join(f"{o['text']} ({o['why']})" for o in _brief["text_options"][:4]))
                _ct = _brief.get("competitor_text")
                if _ct:
                    self.log(f"   - texto de la competencia: {_ct['with_text']}/{_ct['n']} con texto, "
                             f"{int(_ct.get('heavy_share', 0) * 100)}% en negrita, "
                             f"{int(_ct.get('outline_or_box_share', 0) * 100)}% con contorno o caja")
            if not result:
                QMessageBox.critical(self, "Error", "No se pudo generar el super prompt.")
                return
            # El texto pedido: al elegir la miniatura se compara con lo que el generador escribio.
            self._last_thumbnail_text = result.get('text') or ''
            _direction = result.get('art_direction') or {}
            if _direction.get('reason'):
                self.log(f"   - Direccion elegida para '{self._last_thumbnail_text}': {_direction['reason']}")

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
            from ai.claude_client import build_copyable_prompt
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
        if auto_save:
            self._check_thumbnail_text_async(thumbnail_path)
        if (not self._suppress_thumbnail_autosave) and auto_save and self.auto_save_enabled and self.current_project_path:
            self.auto_save_project("seleccion de miniatura")


    def _check_thumbnail_text_async(self, thumbnail_path):
        """Lee la miniatura elegida con vision (thumbnail_typography.check_thumbnail_text) y avisa
        en el panel si el texto es chico, fino, sin contorno, ilegible a 190 px o mal escrito.
        Nunca bloquea: corre en un hilo y se apaga con THUMBNAIL_TEXT_CHECK=0."""
        if not thumbnail_path or not os.path.exists(thumbnail_path):
            return
        if str(os.getenv("THUMBNAIL_TEXT_CHECK", "1")).strip().lower() in ("0", "false", "no", "off"):
            return
        try:
            from ai import gemini_vision
            if not gemini_vision.available():
                return
        except ImportError:
            return
        key = (thumbnail_path, os.path.getmtime(thumbnail_path))
        if getattr(self, '_thumb_text_checked', None) == key:
            return
        self._thumb_text_checked = key
        expected = getattr(self, '_last_thumbnail_text', '') or ''
        notify = self._publish_log_signal.emit

        def _run():
            try:
                from PIL import Image
                from publish.thumbnail_typography import check_thumbnail_text
                with open(thumbnail_path, "rb") as fh:
                    data = fh.read()
                with Image.open(thumbnail_path) as im:
                    vertical = im.height > im.width
                res = check_thumbnail_text(data, lambda p, ims: gemini_vision.ask_images(p, ims),
                                           expected=expected, vertical=vertical)
                if not res.get("text"):
                    notify(f" Miniatura: {res['verdict']} ({'; '.join(res['warnings'])})")
                    return
                notify(f" Miniatura: texto '{res['text']}' -> {res['verdict']}"
                       + (f" (alto de letra {res['cap_pct']}%)" if res.get('cap_pct') is not None else ""))
                for w in res.get("warnings", []):
                    notify(f"   - {w}")
            except Exception as exc:
                notify(f" Miniatura: no se pudo revisar el texto ({type(exc).__name__}: {str(exc)[:120]})")

        import threading
        threading.Thread(target=_run, daemon=True).start()


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
