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


class StudioPublishingMixin:
    def _fact_check_gate(self, storyboard) -> bool:
        """True si se puede publicar. Frena si la narracion tiene afirmaciones falsas o inventadas.

        Usa el informe guardado en el storyboard si corresponde al texto actual; si no,
        verifica (en un hilo, con un dialogo de espera: tarda 20-60 s). Ante problemas
        muestra cuales son y deja elegir: cancelar (por defecto) o publicar igual.
        """
        try:
            from ai import script_fact_check as sfc
        except Exception as exc:
            self.log(f" Verificacion de hechos no disponible: {exc}")
            return True
        if not storyboard or not sfc.storyboard_texts(storyboard):
            return True
        had_current = sfc.report_is_current(storyboard)

        import threading
        from PyQt6.QtWidgets import QApplication, QProgressDialog
        box, logs = {}, []

        def _work():
            box['gate'] = sfc.upload_gate(storyboard, log=logs.append)

        worker = threading.Thread(target=_work, daemon=True)
        dlg = None
        if not had_current:
            self.log(" Verificando los hechos del guion antes de publicar...")
            dlg = QProgressDialog("Verificando los hechos del guion (Wikipedia + juez externo)...",
                                  None, 0, 0, self)
            dlg.setWindowTitle("Verificacion de hechos")
            dlg.setMinimumDuration(0)
            dlg.show()
        worker.start()
        while worker.is_alive():
            QApplication.processEvents()
            worker.join(0.05)
        if dlg is not None:
            dlg.close()
        for line in logs:
            self.log(line)
        ok, report, message = box.get('gate', (True, {}, 'sin resultado'))
        if not had_current and report.get('status') not in (None, 'unchecked', 'disabled', 'empty'):
            try:
                self.save_project()     # deja el informe guardado en el proyecto
            except Exception:
                pass
        if ok:
            self.log(f" {message}")
            return True
        self.log(" ⛔ Publicacion frenada: la narracion tiene afirmaciones falsas o inventadas:")
        for line in message.splitlines():
            self.log(f"    {line}")
        box_msg = QMessageBox(self)
        box_msg.setIcon(QMessageBox.Icon.Warning)
        box_msg.setWindowTitle("Hechos sin verificar")
        box_msg.setText("La narracion de este video tiene afirmaciones falsas o inventadas.\n"
                        "Corregilas en el timeline (y regenera la voz) antes de publicar.")
        box_msg.setDetailedText(message)
        btn_cancel = box_msg.addButton("Cancelar publicacion", QMessageBox.ButtonRole.RejectRole)
        btn_force = box_msg.addButton("Publicar igual", QMessageBox.ButtonRole.DestructiveRole)
        box_msg.setDefaultButton(btn_cancel)
        box_msg.exec()
        if box_msg.clickedButton() is btn_force:
            self.log(" ATENCION: publicado igual pese a la verificacion de hechos (decision del usuario).")
            return True
        return False


    def _music_for_publish(self, storyboard):
        """La musica que tiene el video a publicar (None = sin musica)."""
        video_data = getattr(self, 'last_generated_video_data', None) or {}
        if 'music_used' in video_data:
            return video_data.get('music_used')     # lo que el ensamblador mezclo de verdad
        pm = getattr(self, 'project_manager', None)
        project_data = getattr(pm, 'current_project_data', None) or {}
        return (getattr(self, 'selected_music_metadata', None) or project_data.get('music_metadata')
                or (storyboard or {}).get('music_data'))


    def _music_license_gate(self, storyboard):
        """(se puede publicar, atribucion en ingles) segun la licencia de la musica.

        Frena con aviso si el tema es NC/ND (no sirve para video) o de un artista que ya
        genero un reclamo de Content ID (daily_shorts/music_claims.json). Ver music_license.
        """
        try:
            from publish import music_license as ml
        except Exception as exc:
            self.log(f" Verificacion de licencia de musica no disponible: {exc}")
            return True, ""
        music = self._music_for_publish(storyboard)
        try:
            verdict = ml.check_music_for_upload(music, client_id=os.getenv('JAMENDO_CLIENT_ID', ''))
        except Exception as exc:
            self.log(f" No se pudo verificar la licencia de la musica: {exc}")
            return True, ""
        status = verdict.get('status')
        title = (music or {}).get('title', '') if isinstance(music, dict) else ''
        if status == 'none':
            self.log(" Musica: el video no tiene musica de fondo.")
            return True, ""
        if status == 'local':
            self.log(f" Musica: archivo local '{title}' (asegurate de tener los derechos).")
            return True, ""
        if status == 'ok':
            self.log(f" Musica: '{title}' ({verdict.get('license_code')}) apta; la atribucion va a la descripcion.")
            return True, verdict.get('attribution', '')
        reason = verdict.get('reason') or 'licencia no apta'
        self.log(f" ⛔ Musica con riesgo de reclamo: '{title}': {reason}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Musica con riesgo de copyright")
        box.setText(f"La musica de este video ('{title}') puede generar un reclamo o bloqueo en YouTube:\n\n"
                    f"{reason}\n\nCambia la musica (Buscador de Musica o Musica Local) y reensambla.")
        btn_cancel = box.addButton("Cancelar publicacion", QMessageBox.ButtonRole.RejectRole)
        btn_force = box.addButton("Publicar igual", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(btn_cancel)
        box.exec()
        if box.clickedButton() is btn_force:
            self.log(" ATENCION: publicado igual pese al riesgo de la musica (decision del usuario).")
            return True, verdict.get('attribution', '')
        return False, ""


    def publish_video_to_platforms(self):
        """Sube el video ensamblado a las plataformas seleccionadas."""
        from PyQt6.QtCore import Qt
        
        do_youtube = self.chk_publish_youtube.isChecked()
        do_facebook = self.chk_publish_facebook.isChecked()
        do_instagram = self.chk_publish_instagram.isChecked()
        do_x = self.chk_publish_x.isChecked() if hasattr(self, 'chk_publish_x') else False
        # TikTok no publica: deja un borrador en la bandeja y manda el texto por Telegram.
        do_tiktok = self.chk_publish_tiktok.isChecked() if hasattr(self, 'chk_publish_tiktok') else False

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

        if not (do_youtube or do_facebook or do_instagram or do_x or do_tiktok):
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

        # La narracion que se verifica abajo es la del timeline (con lo editado a mano).
        _pm = getattr(self, 'project_manager', None)
        if _pm is not None and hasattr(_pm, '_sync_timeline_editor_to_storyboard'):
            try:
                _pm._sync_timeline_editor_to_storyboard()
            except Exception:
                pass
        storyboard = getattr(self, 'last_storyboard_data', None)
        if not storyboard and hasattr(self, 'project_manager') and self.project_manager.current_project_data:
            storyboard = self.project_manager.current_project_data.get('storyboard', {})
        storyboard = storyboard or {}

        # Hechos verificados (script_fact_check): no se publica una narracion con
        # afirmaciones falsas o inventadas (Trafalgar 2026-09-23: "el Victory mato a
        # Villeneuve"). Si el informe no existe o se edito la narracion, se verifica ahora.
        if not self._fact_check_gate(storyboard):
            return
        # Musica: licencia apta para video (sin NC/ND ni artistas reclamados) y su atribucion.
        _music_ok, _music_attribution = self._music_license_gate(storyboard)
        if not _music_ok:
            return

        # Construir metadata desde el storyboard (mismos fallbacks que daily_short_pipeline)
        topic = storyboard.get('topic') or storyboard.get('title') or os.path.splitext(os.path.basename(video_path))[0]
        script = str(storyboard.get('script') or '').strip()
        preview = script[:300].strip()

        platform_key = getattr(self, 'get_selected_platform_key', lambda: 'youtube')()
        format_val = getattr(self, 'get_selected_video_format', lambda: '')()
        is_long = format_val == '16:9' or platform_key in ('youtube', '16:9') or (hasattr(self, 'duration_slider') and self.duration_slider.value() > 60)

        from studio.studio_channel_controls import project_channel_config
        from channel.channel_profiles import CHANNELS
        upload_channel = project_channel_config(self)['upload_channel']
        upload_channel_name = CHANNELS[upload_channel]['name']

        # -- Leer metadata del Metadata Studio si ya fue generada --
        youtube_meta = None
        facebook_meta = None
        instagram_meta = None
        # 'suggest' si el titulo lo eligio el usuario (Metadata Studio / piloto aprobado);
        # 'optimize' si lo invento el LLM al publicar. Ver youtube_titles.
        title_mode = "optimize"
        fb_title_mode = "optimize"      # idem para Facebook (facebook_metadata)
        ig_title_mode = "optimize"      # idem para Instagram
        try:
            main_window = self.window()
            mt = getattr(main_window, 'metadata_tab', None)
            if mt:
                yt_title = mt.yt_title.text().strip()
                yt_desc = mt.yt_description.toPlainText().strip()
                yt_tags_raw = mt.yt_tags.toPlainText().strip()
                if yt_title or yt_desc:
                    from publish.youtube_tags import split_tag_field
                    tags = split_tag_field(yt_tags_raw)
                    youtube_meta = {"title": yt_title, "description": yt_desc, "tags": tags}
                    title_mode = "suggest"
                    self.log(f" ✅ Usando metadata del Metadata Studio: {yt_title}")
                fb_title = mt.fb_title.text().strip()
                fb_desc = mt.fb_description.toPlainText().strip()
                if fb_title or fb_desc:
                    facebook_meta = {"title": fb_title, "description": fb_desc}
                    if fb_title:
                        fb_title_mode = "suggest"
                ig_title = mt.ig_title.text().strip()
                ig_desc = mt.ig_description.toPlainText().strip()
                if ig_title or ig_desc:
                    instagram_meta = {"title": ig_title, "description": ig_desc}
                    if ig_title:
                        ig_title_mode = "suggest"
        except Exception as _e_mt:
            self.log(f" ⚠️ No se pudo leer del Metadata Studio: {_e_mt}")

        if storyboard.get('format_strategy') == 'micro_documentary' and self.current_project_path:
            from pathlib import Path
            pilot_folder = Path(self.current_project_path).parent
            pilot_metadata = pilot_folder / 'youtube_metadata.json'
            if pilot_metadata.exists():
                import json
                youtube_meta = json.loads(pilot_metadata.read_text(encoding='utf-8'))
                title_mode = "suggest"

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
                from ai.groq_client import GroqAiClient
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
            from publish.upload_metadata import channel_brand as _channel_brand
            _brand_tag = _channel_brand(upload_channel).replace(' ', '')
            if not youtube_meta or not isinstance(youtube_meta, dict):
                youtube_meta = {
                    "title": topic,
                    "description": (
                        f"{preview}\n\n#history #documentary" if is_long
                        else f"{preview}\n\n#history #shorts"
                    ),
                    "tags": [topic],  # la investigacion (youtube_tags) completa al subir
                }
            from publish.facebook_metadata import trim_at_boundary
            if not facebook_meta:
                _fb_preview = trim_at_boundary(script or preview, 260)
                fb_description = (
                    f"{_fb_preview}\n\nWhat do you think really happened?\n\n#History"
                    if _fb_preview else
                    f"The real story behind {topic}.\n\nWhat do you think really happened?\n\n#History"
                )
                facebook_meta = {
                    "title": topic[:255],
                    "description": fb_description[:2200],
                }
            if not instagram_meta:
                # Hashtags investigados y la marca de la cuenta real los pone instagram_uploader.
                _ig_preview = trim_at_boundary(script or preview, 320)
                ig_description = (
                    f"{_ig_preview}\n\nWhat do you think really happened?\n\n#History"
                    if _ig_preview else
                    f"The real story behind {topic}.\n\n#History"
                )
                instagram_meta = {
                    "title": topic[:120],
                    "description": ig_description[:2200],
                }
        platforms_str = ", ".join(
            p for p, v in [("YouTube", do_youtube), ("Facebook", do_facebook),
                           ("Instagram", do_instagram), ("X", do_x),
                           ("TikTok (borrador)", do_tiktok)] if v
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
        from studio.studio_channel_controls import project_channel_config
        from publish.upload_metadata import metadata_for_channel
        youtube_meta = metadata_for_channel(youtube_meta, upload_channel)
        # Contexto para investigar tags contra el guion real (youtube_tags.research_tags).
        youtube_meta.setdefault('topic', topic)
        youtube_meta.setdefault('script_excerpt', (script or preview or '')[:4000])
        youtube_meta.setdefault('title_mode', title_mode)
        youtube_meta.setdefault('format_archetype', storyboard.get('format_archetype') or '')
        self.log(f" Canal de YouTube seleccionado: {youtube_meta['upload_channel']}")
        _youtube_meta = youtube_meta
        # Si el Metadata Studio no tiene campos propios de una red, se cae a
        # los de YouTube. Antes se guardaba None, `json.dump` escribia el
        # literal `null` en el archivo y el uploader reventaba con
        # "'NoneType' object has no attribute 'get'" (2026-09-09).
        _facebook_meta = dict(facebook_meta or youtube_meta or {})
        _facebook_meta['title_mode'] = fb_title_mode
        _facebook_meta['topic'] = topic
        _facebook_meta['script_excerpt'] = (script or preview or '')[:4000]
        _facebook_meta['format_archetype'] = storyboard.get('format_archetype') or ''
        _instagram_meta = dict(instagram_meta or facebook_meta or youtube_meta or {})
        _instagram_meta['title_mode'] = (ig_title_mode if instagram_meta else
                                         fb_title_mode if facebook_meta else title_mode)
        _instagram_meta['topic'] = topic
        _instagram_meta['script_excerpt'] = (script or preview or '')[:4000]
        _instagram_meta['format_archetype'] = storyboard.get('format_archetype') or ''
        # Cada uploader la pega al final de la descripcion ya optimizada (music_license).
        for _meta in (_youtube_meta, _facebook_meta, _instagram_meta):
            _meta['music_attribution'] = _music_attribution or ''
        # La pagina de Facebook y la cuenta de Instagram del canal elegido (claves con sufijo del
        # canal en .env.txt; sin ellas, las globales). 2026-09-27: publicaba en el otro canal.
        _facebook_meta['upload_channel'] = upload_channel
        _instagram_meta['upload_channel'] = upload_channel
        _x_meta = instagram_meta or facebook_meta or youtube_meta or {}
        # TikTok parte del texto de Instagram (vertical, con hashtags): tiktok_uploader lo
        # pule con facebook_metadata y le pone la marca de la cuenta real de TikTok.
        _tiktok_meta = dict(_instagram_meta)
        _tiktok_meta['upload_channel'] = upload_channel
        _thumbnail_path = getattr(self, 'selected_thumbnail_path', None)
        if _thumbnail_path and os.path.exists(_thumbnail_path):
            self.log(f" Miniatura a publicar: {os.path.basename(_thumbnail_path)}")
        elif _thumbnail_path:
            self.log(f" ATENCION: la miniatura seleccionada ya no existe ({_thumbnail_path}); el video sale sin ella.")
        else:
            self.log(" ATENCION: no hay miniatura seleccionada; YouTube usara un fotograma.")
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
                    ("tiktok_metadata.json", _tiktok_meta),
                ]:
                    with open(staging / fname, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)

                from pipeline.daily_short_pipeline import upload_to_facebook
                if do_youtube:
                    self.log(" Subiendo a YouTube...")
                    priv = "private" if _publish_at_youtube else "public"
                    try:
                        from publish.youtube_uploader import upload_from_metadata as _yt_meta
                        results['youtube'] = _yt_meta(
                            output_dir=str(staging),
                            privacy_status=priv,
                            publish_at=_publish_at_youtube,
                            on_status=self._publish_log_signal.emit,
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
                        # Mismo titulo y palabra clave que YouTube, sin volver a investigar.
                        from publish.facebook_metadata import research_from_youtube
                        _fb_research = research_from_youtube(results.get('youtube'))
                        if _fb_research:
                            _facebook_meta['research'] = _fb_research
                            with open(staging / "facebook_metadata.json", "w", encoding="utf-8") as f:
                                json.dump(_facebook_meta, f, ensure_ascii=False, indent=2)
                    except Exception as fb_seo_err:
                        self.log(f"   Facebook: no se pudo reusar la investigacion de YouTube ({fb_seo_err})")
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
                        # La investigacion ya hecha en esta tanda (YouTube o, si no, Facebook).
                        from publish.facebook_metadata import research_for_next_platform
                        _ig_research = research_for_next_platform(results.get('youtube'), results.get('facebook'))
                        if _ig_research:
                            _instagram_meta['research'] = _ig_research
                            with open(staging / "instagram_metadata.json", "w", encoding="utf-8") as f:
                                json.dump(_instagram_meta, f, ensure_ascii=False, indent=2)
                    except Exception as ig_seo_err:
                        self.log(f"   Instagram: no se pudo reusar la investigacion ({ig_seo_err})")
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
                        from publish.x_video_uploader import upload_from_metadata as _x_meta_up

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
                # Ultimo a proposito: la primera vez abre el navegador para conectar la
                # cuenta y espera hasta 5 min; asi no demora a las demas redes.
                if do_tiktok:
                    self.log(" Enviando a TikTok (borrador a tu bandeja)...")
                    try:
                        from publish.facebook_metadata import research_for_next_platform
                        _tt_research = research_for_next_platform(results.get('youtube'), results.get('facebook'))
                        if _tt_research:
                            _tiktok_meta['research'] = _tt_research
                            with open(staging / "tiktok_metadata.json", "w", encoding="utf-8") as f:
                                json.dump(_tiktok_meta, f, ensure_ascii=False, indent=2)
                    except Exception as tt_seo_err:
                        self.log(f"   TikTok: no se pudo reusar la investigacion ({tt_seo_err})")
                    try:
                        from publish.tiktok_uploader import upload_from_metadata as _tt_up
                        from publish.upload_progress import make_byte_progress_reporter
                        _tt_notify = self._publish_log_signal.emit
                        results['tiktok'] = _tt_up(
                            output_dir=str(staging),
                            on_progress=make_byte_progress_reporter("   TikTok: subiendo", _tt_notify),
                            on_status=lambda msg: _tt_notify(f"   TikTok: {msg}"),
                        )
                    except Exception as tt_err:
                        self.log(f"⚠ TikTok error: {tt_err}")
                        results['tiktok'] = None
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
            # Los paquetes van completos (con __init__.py) para que los imports
            # `from publish.facebook_uploader import ...` resuelvan en el VPS.
            for pkg_name in ('infra', 'ai', 'media', 'channel', 'publish'):
                pkg_dir = os.path.join(os.getcwd(), pkg_name)
                if os.path.isdir(pkg_dir):
                    subprocess.run(
                        ["scp", "-r", pkg_dir, f"{ssh_host}:{remote_tmp}/"],
                        capture_output=True, timeout=180
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
            from publish.facebook_uploader import upload_from_metadata
            from publish.upload_progress import make_byte_progress_reporter
            notify = self._publish_log_signal.emit
            return upload_from_metadata(
                output_dir=str(staging_dir),
                video_state='PUBLISHED',
                upload_type=upload_type,
                scheduled_publish_time=publish_at,
                on_progress=make_byte_progress_reporter("   Facebook: subiendo", notify),
                on_status=lambda msg: notify(f"   Facebook: {msg}"),
            )

        return self._upload_via_vps(
            platform="Facebook",
            staging_dir=staging_dir,
            video_path=video_path,
            python_call=(
                "from publish.facebook_uploader import upload_from_metadata\n"
                f"result = upload_from_metadata({python_args})"
            ),
            fallback_fn=_local_fallback,
        )


    def _upload_instagram_via_vps(self, staging_dir, video_path: str, instagram_meta: dict) -> dict:
        def _local_fallback():
            from publish.instagram_uploader import upload_from_metadata
            from publish.upload_progress import make_byte_progress_reporter
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
                "from publish.instagram_uploader import upload_from_metadata\n"
                "result = upload_from_metadata(output_dir='.', share_to_feed=True)"
            ),
            fallback_fn=_local_fallback,
        )


    def _on_publish_done(self, results: dict):
        """Callback cuando terminan los uploads."""
        self.btn_publish.setEnabled(True)
        self.btn_publish.setText("Publicar video")
        try:
            if hasattr(self, 'project_manager') and self.project_manager.record_publish_results(results):
                self.log(" Publicacion registrada en el proyecto (ids por red).")
        except Exception as exc:
            self.log(f" No se pudo registrar la publicacion en el proyecto: {exc}")
        for platform, result in results.items():
            if result and platform == 'tiktok':
                # No es una publicacion: el video espera en la bandeja de TikTok.
                cuenta = f" ({result['account']})" if result.get('account') else ''
                self.log(f" TikTok: borrador en tu bandeja{cuenta}. Terminalo en la app y publicalo.")
                if result.get('telegram_sent'):
                    self.log("   Titulo y descripcion enviados por Telegram.")
                else:
                    self.log(f"   ATENCION: no llegaron por Telegram ({result.get('telegram_error')}). "
                             f"Titulo: {result.get('title_sent')} | Descripcion: {result.get('description_sent')}")
            elif result:
                url = result.get('url') or result.get('permalink_url') or ''
                # En que cuenta salio: publicar en la del otro canal no se nota hasta mirar la red.
                cuenta = result.get('page_name') or (f"@{result['instagram_username']}"
                                                     if result.get('instagram_username') else '')
                self.log(f" {platform.capitalize()} publicado{' en ' + cuenta if cuenta else ''}"
                         f"{': ' + url if url else '.'}")
                if result.get('thumbnail_error'):
                    donde = {"youtube": "YouTube Studio",
                             "instagram": "la app de Instagram (Editar > portada)"}.get(platform, "Meta Business Suite")
                    self.log(f"   ATENCION: la miniatura NO se puso ({result['thumbnail_error']}). "
                             f"Se puede subir a mano en {donde}.")
            else:
                self.log(f"️ {'TikTok' if platform == 'tiktok' else platform.capitalize()} falló.")


    def _on_download_error(self, error):
        """MÃ©todo stub para seÃ±al _download_error_signal (no se usa actualmente en AutoVideoStudioTab)"""
        pass


    def _on_download_progress(self, percentage):
        """MÃ©todo stub para seÃ±al _download_progress_signal (no se usa actualmente en AutoVideoStudioTab)"""
        pass


    def show_video_recommendations(self):
        """Muestra el diÃ¡logo de recomendaciones de videos"""
        try:
            from app.video_recommendations_dialog import VideoRecommendationsDialog
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
            from app.video_history_dialog import VideoHistoryDialog
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
            from app.api_status_dialog import APIStatusDialog
            dialog = APIStatusDialog(self)
            dialog.exec()
        except ImportError as e:
            QMessageBox.warning(
    self, "Error", f"MÃ³dulo api_status_dialog no disponible: {e}")
        self.load_elevenlabs_voices()
