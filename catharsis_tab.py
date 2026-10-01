# -*- coding: utf-8 -*-
"""Pestana Catarsis: Short vertical de impacto, sin voz (motor: catharsis_editor).

Eliges medios (imagenes y videos, con o sin su audio), escribes las tarjetas o las propone la
IA con los hechos verificados, eliges musica y estilo. "Planificar escenas" crea la secuencia de
planos con el arco; despues cada plano se retoca (contenido, variante, duracion, transicion,
movimiento) antes de la vista previa y el render final en auto_videos/output.
"""

from __future__ import annotations

import copy
import json
import re
import time
import uuid
from pathlib import Path

from PyQt6.QtCore import QIODevice, QSaveFile, QSettings, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                             QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QMenu,
                             QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider,
                             QApplication, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import catharsis_editor as ce
from catharsis_media_input import (IMAGE_EXTENSIONS, MediaDropArea, MediaDropList, can_import,
                                  image_from_mime, local_paths, supported_file)
from catharsis_timeline import assignment_summary, media_slots, missing_slots, plan_timings, set_slot, slot_value, timecode
from catharsis_timeline_view import TimelineStrip

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "auto_videos" / "output"
PREVIEW_PATH = ROOT / "auto_videos" / "cache" / "catarsis_preview.mp4"
PROJECTS_DIR = ROOT / "projects" / "catarsis"

VARIANT_NAMES = {"color": "Color", "base": "B/N", "negative": "Negativo", "red": "Rojo", "hard": "Dos tonos",
                 "sketch": "Boceto"}
CARD_STYLES = {"center": "Centrada", "left": "Izquierda", "invert": "Papel", "red": "Roja", "word": "Palabra",
               "caption": "Firma"}
COLOR_NAMES = {"black": "Negro", "white": "Blanco", "red": "Rojo"}
TRANSITION_NAMES = {"cut": "Corte", "flash": "Destello", "glitch": "Glitch", "burn": "Film burn", "zoom": "Zoom"}
MOTION_NAMES = {"hold": "Quieto", "push": "Acercar", "pull": "Alejar", "punch": "Golpe", "shake": "Temblor",
                "ramp": "Rampa"}
KIND_NAMES = {"card": "Tarjeta", "media": "Medio", "color": "Color", "overlay": "Texto sobre imagen",
              "double": "Doble exposicion", "split": "Pantalla dividida", "impact": "Impact frame"}
MEDIA_KINDS = ("media", "overlay", "double", "split", "impact")
IMAGE_EFFECTS = {"kinetic": "Texto cinetico", "impact": "Impact frames", "grade": "Color por acto",
                 "bloom": "Resplandor", "double": "Doble exposicion", "split": "Pantalla dividida"}
RHYTHM_EFFECTS = {"ramps": "Rampas de velocidad", "drop": "Quiebre en la caida", "loop": "Loop perfecto",
                  "sfx": "Diseno sonoro"}


def _pixmap(img) -> QPixmap:
    img = img.convert("RGB")
    qimg = QImage(img.tobytes(), img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class _SequenceWorker(QThread):
    done = pyqtSignal(list, int, object, float)
    failed = pyqtSignal(str)

    def __init__(self, project):
        super().__init__()
        self.project = project

    def run(self):
        try:
            music, T = self.project.get("music"), self.project["seconds"]
            start = float(self.project.get("music_start") or 0.0)
            if music and self.project.get("music_auto", True):
                start = ce.find_music_start(music, T)[0]
            beats, drop = ce.music_analysis(music, T, start) if music else ([], None)
            seq = ce.auto_sequence(self.project, beats, seed=int(time.time()) % 1000, drop=drop,
                                   assign_media=self.project.get("auto_assign_media", False))
            self.done.emit(seq, len(beats), drop if self.project["style"].get("drop") else None, start)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _RenderWorker(QThread):
    line = pyqtSignal(str)
    progress = pyqtSignal(int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, project, out: Path, preview: bool, guides: bool = False):
        super().__init__()
        self.project, self.out, self.preview, self.guides = project, out, preview, guides

    def run(self):
        try:
            self.line.emit("Preparando los planos...")
            shots, marks = ce.build_shots(self.project, self.project["sequence"])
            self.line.emit(f"{len(shots)} planos, {marks['end']:.1f} s. Renderizando...")
            self.out.parent.mkdir(parents=True, exist_ok=True)
            style = self.project["style"]
            ce.render(shots, self.out, music=self.project.get("music") or None, break_span=marks["break"],
                      vignette=style.get("vignette", True), preview=self.preview, sfx=style.get("sfx", True),
                      loop=style.get("loop", True), guides=self.preview and self.guides,
                      music_start=float(self.project.get("music_start") or 0.0),
                      progress=lambda n, total: self.progress.emit(int(100 * n / max(total, 1))))
            self.done.emit(str(self.out))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _CardsWorker(QThread):
    line = pyqtSignal(str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, topic, perspective, language):
        super().__init__()
        self.args = (topic, perspective, language)

    def run(self):
        try:
            self.done.emit(ce.write_cards(*self.args, log=self.line.emit))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _CompositionWorker(QThread):
    ready = pyqtSignal(int, str, object, str)

    def __init__(self, revision, project, tasks, parent=None):
        super().__init__(parent)
        self.revision, self.project, self.tasks = revision, project, tasks

    def run(self):
        from catharsis_preview import composition_preview
        for key, spec, size in self.tasks:
            if self.isInterruptionRequested():
                return
            try:
                img = composition_preview(self.project, spec, size)
                qimg = QImage(img.tobytes(), img.width, img.height, img.width * 3,
                              QImage.Format.Format_RGB888).copy()
                self.ready.emit(self.revision, key, qimg, "")
            except Exception as exc:
                self.ready.emit(self.revision, key, None, str(exc))


class CatharsisTab(QWidget):
    def __init__(self, parent_gui=None, *, settings=None):
        super().__init__()
        self.parent_gui = parent_gui
        self.media: list[dict] = []
        self.sequence: list[dict] = []
        self.music_path = ""
        self.last_output = ""
        self._worker = None
        self._loading = False
        self._loading_project = False
        self._filling_cards = False
        self._cards_metadata = {}
        self._project_extra = {}
        self.current_project_path = None
        self._dirty = False
        self._settings = settings if settings is not None else QSettings("VideoOptimizer", "Catarsis")
        self._preview_revision = 0
        self._preview_worker = None
        self._closing = False
        self._player = None
        self._preview_video_stale = False
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(2000)
        self._autosave_timer.timeout.connect(self._auto_save)
        self._composition_timer = QTimer(self)
        self._composition_timer.setSingleShot(True)
        self._composition_timer.setInterval(300)
        self._composition_timer.timeout.connect(self._start_compositions)
        self._build_ui()
        self._connect_changes()
        QApplication.instance().aboutToQuit.connect(self._shutdown)
        QTimer.singleShot(0, self._restore_last_project)

    # ------------------------------------------------------------ interfaz
    def _build_ui(self):
        root = QHBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(self._texts_group())
        lv.addWidget(self._media_group())
        lv.addWidget(self._music_group())
        lv.addWidget(self._style_group())
        lv.addStretch()
        scroll = QScrollArea()
        scroll.setMinimumWidth(450)
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        split.addWidget(scroll)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(self._sequence_group(), 3)
        rv.addWidget(self._render_group(), 1)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        split.addWidget(right_scroll)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        split.setSizes([450, 900])

    def _texts_group(self):
        box = QGroupBox("Tema y tarjetas")
        form = QFormLayout(box)
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("Ej.: Oppenheimer y la prueba Trinity, 16 de julio de 1945")
        form.addRow("Tema:", self.topic)
        row = QHBoxLayout()
        self.perspective = QComboBox()
        self.perspective.addItem("Voz del personaje", "character")
        self.perspective.addItem("Voz del narrador", "narrator")
        self.perspective.setToolTip("Personaje: reflexion dramatizada desde un momento de su vida. "
                                   "Narrador: mirada externa que puede explicar consecuencias posteriores.")
        self.language = QComboBox()
        self.language.addItem("English", "en")
        self.language.addItem("Español", "es")
        self.ai_btn = QPushButton("Escribir con IA")
        self.ai_btn.setToolTip("La IA propone las tarjetas desde el tema y verifica los hechos; despues las editas.")
        self.ai_btn.clicked.connect(self._write_cards)
        for w in (self.perspective, self.language, self.ai_btn):
            row.addWidget(w)
        form.addRow("Voz:", row)
        self.opening = QLineEdit(ce.DEFAULT_CARDS["opening"])
        form.addRow("Pregunta inicial:", self.opening)
        self.lines = QPlainTextEdit()
        self.lines.setPlaceholderText("Una frase por linea: fechas, hechos, preguntas...")
        self.lines.setMinimumHeight(130)
        form.addRow("Frases:", self.lines)
        self.climax = QLineEdit(", ".join(ce.DEFAULT_CARDS["climax"]))
        self.climax.setToolTip("Palabras sueltas del climax, separadas por coma.")
        form.addRow("Climax:", self.climax)
        self.final = QPlainTextEdit()
        self.final.setPlaceholderText("La frase final (una por linea)")
        self.final.setMaximumHeight(64)
        form.addRow("Frase final:", self.final)
        self.end = QLineEdit()
        self.end.setPlaceholderText("Quien lo dijo y cuando, o la fuente")
        form.addRow("Firma:", self.end)
        return box

    def _media_group(self):
        box = QGroupBox("Imagenes y videos")
        v = QVBoxLayout(box)
        self.media_list = MediaDropList()
        self.media_list.media_dropped.connect(self._import_media_mime)
        self.media_list.paste_requested.connect(self._paste_media)
        self.media_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.media_list.customContextMenuRequested.connect(self._media_context_menu)
        self.media_list.setToolTip("Arrastra archivos de imagen o video. También puedes pegar una imagen copiada.")
        self.media_list.setIconSize(QSize(54, 96))
        self.media_list.setMinimumHeight(200)
        self.media_list.currentRowChanged.connect(self._load_media_props)
        v.addWidget(self.media_list)
        hint = QLabel("Arrastra imágenes o videos aquí · Clic derecho → Pegar · Ctrl+V")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = QHBoxLayout()
        for text, slot in (("Agregar imagenes...", lambda: self._add_media("image")),
                           ("Agregar videos...", lambda: self._add_media("video")),
                           ("Quitar", self._remove_media), ("Subir", lambda: self._move_media(-1)),
                           ("Bajar", lambda: self._move_media(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        self.m_x, self.m_y = self._spin(0, 1, 0.05, 0.5), self._spin(0, 1, 0.05, 0.5)
        self.m_zoom = self._spin(1, 6, 0.1, 1.0)
        self.m_in, self.m_out = self._spin(0, 36000, 0.1, 0), self._spin(0, 36000, 0.1, 0)
        self.m_audio = QCheckBox("Usar su audio")
        for fields in ((("Encuadre X", self.m_x), ("Y", self.m_y), ("Zoom", self.m_zoom)),
                       (("Video desde (s)", self.m_in), ("hasta (s)", self.m_out))):
            props = QHBoxLayout()
            for label, w in fields:
                props.addWidget(QLabel(label))
                props.addWidget(w)
                w.editingFinished.connect(self._save_media_props)
            if fields[0][1] is self.m_in:
                props.addWidget(self.m_audio)
            props.addStretch()
            v.addLayout(props)
        self.m_audio.toggled.connect(self._save_media_props)
        return box

    def _music_group(self):
        box = QGroupBox("Musica")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        self.music_edit = QLineEdit()
        self.music_edit.setReadOnly(True)
        self.music_edit.setPlaceholderText("Sin musica (pista apta para YouTube: CC BY o Biblioteca de Audio)")
        row.addWidget(self.music_edit, 1)
        for text, slot in (("Elegir archivo...", self._pick_music), ("Buscar en Jamendo...", self._jamendo),
                           ("Quitar", lambda: self._set_music(""))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        self.music_start = self._spin(0, 3600, 0.5, 0.0)
        self.music_start.setSuffix(" s")
        self.music_auto = QCheckBox("Auto: su caida en el quiebre")
        self.music_auto.setChecked(True)
        self.music_auto.setToolTip("Al armar la secuencia busca la caida mas fuerte de la pista y la toma desde "
                                   "donde esa caida coincide con el final del silencio.")
        for w in (QLabel("Desde el segundo"), self.music_start, self.music_auto):
            row.addWidget(w)
        row.addStretch()
        v.addLayout(row)
        return box

    def _style_group(self):
        box = QGroupBox("Estilo")
        form = QFormLayout(box)
        self.seconds = QSpinBox()
        self.seconds.setRange(20, 60)
        self.seconds.setValue(40)
        self.seconds.setSuffix(" s")
        form.addRow("Duracion:", self.seconds)
        self.speed, speed_row = self._slider(50, 200, 100)
        form.addRow("Velocidad de cortes:", speed_row)
        self.flashes, flash_row = self._slider(0, 200, 100)
        self.flashes.setToolTip("Cuantos destellos. El motor nunca pasa de 3 por segundo (fotosensibilidad).")
        form.addRow("Destellos:", flash_row)
        self.variant_checks = self._checks(VARIANT_NAMES, ce.DEFAULT_STYLE["variants"], cols=3)
        form.addRow("Variantes:", self.variant_checks[0])
        self.transition_checks = self._checks({k: TRANSITION_NAMES[k] for k in ("glitch", "burn", "zoom")},
                                              ce.DEFAULT_STYLE["transitions"])
        form.addRow("Transiciones:", self.transition_checks[0])
        self.effect_checks = self._checks({"grain": "Grano", "vignette": "Vineta", "shake": "Temblor"},
                                          ["grain", "vignette", "shake"])
        form.addRow("Efectos:", self.effect_checks[0])
        self.image_checks = self._checks(IMAGE_EFFECTS, list(IMAGE_EFFECTS), cols=3)
        form.addRow("Imagen:", self.image_checks[0])
        self.rhythm_checks = self._checks(RHYTHM_EFFECTS, list(RHYTHM_EFFECTS), cols=2)
        self.rhythm_checks[1]["drop"].setToolTip("El quiebre (silencio) termina justo en la caida de la musica.")
        self.rhythm_checks[1]["loop"].setToolTip("El ultimo cuadro es la pregunta inicial: el Short se repite "
                                                 "sin corte.")
        self.rhythm_checks[1]["sfx"].setToolTip("Whoosh, golpes, subida, pitido y boom sintetizados (sin derechos).")
        form.addRow("Ritmo y sonido:", self.rhythm_checks[0])
        samples = QTabWidget()
        image_gallery, self.variant_previews = self._gallery(VARIANT_NAMES)
        card_gallery, self.card_previews = self._gallery(CARD_STYLES)
        samples.addTab(image_gallery, "Imagen seleccionada")
        samples.addTab(card_gallery, "Tarjetas de texto")
        form.addRow("Muestras:", samples)
        note = QLabel("Composiciones de referencia. Movimiento, transiciones y sonido: usa Vista previa.")
        note.setWordWrap(True)
        form.addRow(note)
        return box

    def _gallery(self, names):
        panel = QWidget()
        grid = QGridLayout(panel)
        labels = {}
        for n, (key, name) in enumerate(names.items()):
            cell = QWidget()
            layout = QVBoxLayout(cell)
            picture = QLabel("Preparando…")
            picture.setFixedSize(72, 128)
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            picture.setWordWrap(True)
            picture.setStyleSheet("background:#141820;color:#d6dde7;border-radius:4px;")
            layout.addWidget(picture, 0, Qt.AlignmentFlag.AlignHCenter)
            caption = QLabel(name)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(caption)
            grid.addWidget(cell, n // 3, n % 3)
            labels[key] = picture
        return panel, labels

    def _sequence_group(self):
        box = QGroupBox("Editor de escenas · Catarsis")
        v = QVBoxLayout(box)
        v.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        top = QHBoxLayout()
        self.auto_btn = QPushButton("Planificar escenas")
        self.auto_btn.setToolTip("Calcula las escenas y sus duraciones a partir de las tarjetas, musica y estilo. "
                                "Puedes hacerlo antes de cargar archivos. Reemplaza el plan actual.")
        self.auto_btn.clicked.connect(self._auto_sequence)
        top.addWidget(self.auto_btn)
        top.addStretch()
        for text, slot in (("Subir", lambda: self._move_shot(-1)), ("Bajar", lambda: self._move_shot(1)),
                           ("Duplicar", self._duplicate_shot), ("Eliminar", self._delete_shot)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            top.addWidget(b)
        v.addLayout(top)
        self.auto_assign_check = QCheckBox("Asignar automáticamente los medios de la biblioteca al planificar")
        self.auto_assign_check.setToolTip("Reutiliza los archivos disponibles en varias escenas. "
                                         "Desactivado: crea espacios pendientes para asignarlos uno por uno.")
        v.addWidget(self.auto_assign_check)
        self.total_label = QLabel("Pulsa Planificar escenas para saber cuánto material necesitas.")
        self.total_label.setWordWrap(True)
        summary = QHBoxLayout()
        summary.addWidget(self.total_label, 1)
        self.pending_btn = QPushButton("Siguiente pendiente")
        self.pending_btn.setEnabled(False)
        self.pending_btn.clicked.connect(self._next_pending)
        summary.addWidget(self.pending_btn)
        v.addLayout(summary)
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setFixedHeight(86)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timeline = TimelineStrip()
        self.timeline.scene_selected.connect(self._select_timeline_scene)
        self.timeline_scroll.setWidget(self.timeline)
        v.addWidget(self.timeline_scroll)
        note = QLabel("Naranja: falta material · Clic en una escena para editarla. "
                      "Tiempos del plan; el render puede ajustar cortes de destellos.")
        note.setWordWrap(True)
        v.addWidget(note)
        self.table = QTableWidget(0, 9)
        self.table.setObjectName("catarsisScenes")
        self.table.setStyleSheet("""
            QTableWidget#catarsisScenes QPushButton { padding: 4px 6px; }
            QTableWidget#catarsisScenes QComboBox, QTableWidget#catarsisScenes QLineEdit,
            QTableWidget#catarsisScenes QDoubleSpinBox { padding: 4px; }
            QTableWidget#catarsisScenes QComboBox::drop-down { width: 16px; }
        """)
        self.table.setHorizontalHeaderLabels(["Plano", "Contenido", "Variante / estilo", "Segundos",
                                              "Transicion", "Movimiento", "Vista", "Inicio", "Fin"])
        for visual, logical in enumerate((6, 0, 7, 8, 3, 1, 2, 4, 5)):
            self.table.horizontalHeader().moveSection(self.table.horizontalHeader().visualIndex(logical), visual)
        self.table.setColumnWidth(6, 58)
        self.table.setIconSize(QSize(48, 85))
        self.table.verticalHeader().setDefaultSectionSize(92)
        self.table.setMinimumHeight(220)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 310)
        for col, width in ((0, 120), (2, 120), (3, 82), (4, 110), (5, 110), (7, 80), (8, 80)):
            self.table.setColumnWidth(col, width)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._card_text_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        v.addWidget(self.table)
        viewer = QHBoxLayout()
        self.viewer_stack = QStackedWidget()
        self.shot_preview = QLabel("Selecciona un plano\npara ver su composición")
        self.shot_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shot_preview.setWordWrap(True)
        self.shot_preview.setStyleSheet("background:#10141a;color:#d6dde7;")
        self.viewer_stack.addWidget(self.shot_preview)
        self.viewer_stack.setFixedSize(144, 256)
        viewer.addWidget(self.viewer_stack)
        controls = QVBoxLayout()
        self.shot_caption = QLabel("Las miniaturas se actualizan al editar los planos.")
        self.shot_caption.setWordWrap(True)
        controls.addWidget(self.shot_caption)
        still_btn = QPushButton("Ver composición del plano")
        still_btn.clicked.connect(self._show_composition)
        controls.addWidget(still_btn)
        self.play_btn = QPushButton("Reproducir / pausar vista previa")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_playback)
        controls.addWidget(self.play_btn)
        self.video_seek = QSlider(Qt.Orientation.Horizontal)
        self.video_seek.setEnabled(False)
        self.video_seek.sliderMoved.connect(lambda value: self._player and self._player.setPosition(value))
        controls.addWidget(self.video_seek)
        self.video_status = QLabel("Usa Vista previa para reproducir el montaje aquí.")
        self.video_status.setWordWrap(True)
        controls.addWidget(self.video_status)
        controls.addStretch()
        viewer.addLayout(controls, 1)
        v.addLayout(viewer)
        return box

    def _render_group(self):
        box = QGroupBox("Render")
        v = QVBoxLayout(box)
        v.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        row = QHBoxLayout()
        self.preview_btn = QPushButton("Vista previa")
        self.preview_btn.setToolTip("Rapida: 540x960 a 15 fps, para mirar el ritmo.")
        self.preview_btn.clicked.connect(lambda: self._render(preview=True))
        self.render_btn = QPushButton("Render final")
        self.render_btn.clicked.connect(lambda: self._render(preview=False))
        self.open_btn = QPushButton("Abrir video")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output)))
        save_btn, load_btn = QPushButton("Guardar proyecto..."), QPushButton("Abrir proyecto...")
        save_btn.clicked.connect(self._save_project)
        load_btn.clicked.connect(self._load_project)
        self.guides = QCheckBox("Guias de zona segura")
        self.guides.setToolTip("En la vista previa, marca en rojo lo que tapa la interfaz de Shorts.")
        for b in (self.preview_btn, self.guides, self.render_btn, self.open_btn):
            row.addWidget(b)
        v.addLayout(row)
        files = QHBoxLayout()
        files.addWidget(save_btn)
        files.addWidget(load_btn)
        v.addLayout(files)
        self.auto_save_check = QCheckBox("Guardar automáticamente después de cada paso y al editar")
        self.auto_save_check.setChecked(self._settings.value("auto_save", True, type=bool))
        self.auto_save_check.toggled.connect(self._auto_save_changed)
        v.addWidget(self.auto_save_check)
        self.save_status = QLabel("Proyecto sin guardar")
        self.save_status.setWordWrap(True)
        self.save_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.save_status)
        self.progress = QProgressBar()
        v.addWidget(self.progress)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        v.addWidget(self.log_box)
        return box

    # ------------------------------------------------------------ ayudas de interfaz
    @staticmethod
    def _spin(lo, hi, step, value):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(2)
        s.setValue(value)
        return s

    @staticmethod
    def _slider(lo, hi, value):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(value)
        label = QLabel(f"{value} %")
        s.valueChanged.connect(lambda v: label.setText(f"{v} %"))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(s, 1)
        h.addWidget(label)
        return s, row

    @staticmethod
    def _checks(names: dict, checked, cols: int = 0):
        row = QWidget()
        h = QGridLayout(row) if cols else QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        boxes = {}
        for n, (key, name) in enumerate(names.items()):
            cb = QCheckBox(name)
            cb.setChecked(key in checked)
            if cols:
                h.addWidget(cb, n // cols, n % cols)
            else:
                h.addWidget(cb)
            boxes[key] = cb
        if not cols:
            h.addStretch()
        return row, boxes

    def _effect_boxes(self) -> dict:
        return {**self.effect_checks[1], **self.image_checks[1], **self.rhythm_checks[1]}

    def log(self, msg: str):
        self.log_box.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")
        print(f"[catarsis] {msg}")

    def _busy(self, busy: bool):
        for b in (self.ai_btn, self.auto_btn, self.preview_btn, self.render_btn):
            b.setEnabled(not busy)

    def _connect_changes(self):
        self.topic.textChanged.connect(self._changed)
        for field in (self.opening, self.lines, self.climax, self.final, self.end):
            field.textChanged.connect(self._cards_changed)
        for combo in (self.perspective, self.language):
            combo.currentIndexChanged.connect(self._changed)
        for field in (self.seconds, self.speed, self.flashes, self.music_start):
            field.valueChanged.connect(self._changed)
        for cb in [self.music_auto, self.guides, self.auto_assign_check, *self.variant_checks[1].values(),
                   *self.transition_checks[1].values(), *self._effect_boxes().values()]:
            cb.toggled.connect(self._changed)
        self.media_list.currentRowChanged.connect(self._schedule_compositions)
        for field in (self.m_x, self.m_y, self.m_zoom, self.m_in, self.m_out):
            field.valueChanged.connect(self._save_media_props)

    def _cards_changed(self):
        if not self._filling_cards and not self._loading_project:
            self._cards_metadata.pop("fact_check", None)
            self._cards_metadata.pop("narrative_review", None)
        self._changed()

    def _changed(self, *_args):
        if self._loading_project or self._loading or self._closing:
            return
        self._dirty = True
        self._preview_video_stale = True
        if self._player:
            self.video_status.setText("Hay cambios: genera otra vista previa para verlos.")
        self.save_status.setText("Cambios pendientes" +
                                 (f" · {self.current_project_path.name}" if self.current_project_path else ""))
        if self.auto_save_check.isChecked():
            self._autosave_timer.start()
        self._schedule_compositions()

    def _auto_save_changed(self, enabled):
        self._settings.setValue("auto_save", enabled)
        if enabled:
            self._auto_save()
        else:
            self._autosave_timer.stop()

    def _write_project(self, path):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.project(), ensure_ascii=False, indent=2).encode("utf-8")
        output = QSaveFile(str(path))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(payload) != len(payload):
            output.cancelWriting()
            raise OSError(output.errorString())
        if not output.commit():
            raise OSError(output.errorString())
        self.current_project_path = path
        self._settings.setValue("last_project", str(path))
        self._settings.sync()
        self._dirty = False
        self._autosave_timer.stop()
        self.save_status.setText(f"Guardado {time.strftime('%H:%M:%S')} · {path.name}")
        self.save_status.setToolTip(str(path))

    def _auto_save(self):
        if self._loading_project or not self.auto_save_check.isChecked() or not self._dirty:
            return True
        name = re.sub(r"[^\w-]+", "_", self.topic.text().strip())[:40] or "catarsis"
        path = self.current_project_path or PROJECTS_DIR / f"{name}_{uuid.uuid4().hex[:10]}.json"
        try:
            self._write_project(path)
            return True
        except Exception as exc:
            self.save_status.setText("No se pudo guardar; los cambios siguen pendientes")
            self.log(f"Error de autoguardado: {exc}")
            return False

    def _restore_last_project(self):
        if self._closing or self._dirty or self.current_project_path:
            return
        path = self._settings.value("last_project", "")
        if path and Path(path).is_file():
            try:
                self.load_project(Path(path))
            except Exception as exc:
                self.log(f"No se pudo recuperar el ultimo proyecto: {exc}")
        self._schedule_compositions()

    def _schedule_compositions(self, *_args):
        if self._loading_project or self._closing:
            return
        self._preview_revision += 1
        if self._preview_worker:
            self._preview_worker.requestInterruption()
        self._composition_timer.start()

    def _selection_changed(self):
        self._show_composition()
        row = self._selected_shot()
        if row >= 0:
            s = self.sequence[row]
            start, end = plan_timings(self.sequence, ce.FPS)[row]
            pending = missing_slots(s, self.media)
            status = (f"Falta asignar {len(pending)} imagen(es) o video(s)." if pending else
                      "Composición sin movimiento")
            self.shot_caption.setText(f"Escena {row + 1} · {timecode(start)}–{timecode(end)} · {end - start:.3f} s\n"
                                      f"{KIND_NAMES.get(s.get('kind'), '')} · {status}")
            self.shot_preview.clear()
            self.shot_preview.setText("Asigna imagen o video\nen Contenido" if pending else "Actualizando…")
            self.timeline.select(row)
            self.timeline_scroll.ensureVisible(int(8 + start * self.timeline.pixels_per_second), 32, 40, 0)
        else:
            self.shot_preview.clear()
            self.shot_preview.setText("Selecciona un plano")
            self.timeline.select(-1)
        self._schedule_compositions()

    def _show_composition(self):
        if self._player:
            self._player.pause()
        self.viewer_stack.setCurrentWidget(self.shot_preview)

    def _start_compositions(self):
        if self._closing or self._loading_project or self._preview_worker is not None:
            return
        project = self.project()
        self._update_total()
        tasks = []
        row = self._selected_shot()
        if row >= 0 and not missing_slots(self.sequence[row], self.media):
            tasks.append(("selected", self.sequence[row], (144, 256)))
        elif row >= 0:
            self.shot_preview.clear()
            self.shot_preview.setText("Asigna imagen o video\nen Contenido")
        sample = self.opening.text().strip() or "CATARSIS"
        for style in CARD_STYLES:
            tasks.append(("card:" + style, {"kind": "card", "text": sample, "style": style,
                                           "seconds": 1}, (72, 128)))
        media_index = self.media_list.currentRow()
        if self.media:
            media_index = max(0, min(media_index, len(self.media) - 1))
            for variant in VARIANT_NAMES:
                tasks.append(("variant:" + variant, {"kind": "media", "media": media_index,
                              "variant": variant, "seconds": 1, "act": "rise"}, (72, 128)))
        else:
            for label in self.variant_previews.values():
                label.clear()
                label.setText("Agrega una imagen o video")
        for i, spec in enumerate(self.sequence):
            if not missing_slots(spec, self.media):
                tasks.append((f"row:{i}", spec, (48, 85)))
        worker = _CompositionWorker(self._preview_revision, project, copy.deepcopy(tasks), self)
        self._preview_worker = worker
        worker.ready.connect(self._composition_ready)
        worker.finished.connect(lambda: self._compositions_finished(worker))
        worker.start()

    def _composition_ready(self, revision, key, image, error):
        if revision != self._preview_revision or self._closing:
            return
        if key.startswith("row:"):
            row = int(key.split(":")[1])
            if row < self.table.rowCount():
                item = self.table.item(row, 6)
                item.setIcon(QIcon(QPixmap.fromImage(image)) if image is not None else QIcon())
                item.setToolTip(error or "Composición del plano")
            return
        label = (self.shot_preview if key == "selected" else
                 self.card_previews[key.split(":")[1]] if key.startswith("card:") else
                 self.variant_previews[key.split(":")[1]])
        label.clear()
        label.setToolTip(error)
        if image is None:
            label.setText("Sin vista previa\nRevisa el archivo")
        else:
            label.setPixmap(QPixmap.fromImage(image))

    def _compositions_finished(self, worker):
        revision = worker.revision
        self._preview_worker = None
        worker.deleteLater()
        if not self._closing and revision != self._preview_revision and not self._composition_timer.isActive():
            self._composition_timer.start()

    def _ensure_player(self):
        if self._player is not None:
            return
        self._using_vlc = False
        try:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PyQt6.QtMultimediaWidgets import QVideoWidget
            candidate = QMediaPlayer(self)
            if candidate.isAvailable():
                self._video_widget = QVideoWidget()
                self._audio_output = QAudioOutput(self)
                candidate.setAudioOutput(self._audio_output)
                candidate.setVideoOutput(self._video_widget)
                self._player = candidate
            else:
                candidate.deleteLater()
        except ImportError:
            pass
        if self._player is None:
            from catharsis_player import VlcPreviewPlayer
            self._video_widget = QWidget()
            self._video_widget.setStyleSheet("background:black;")
            self.viewer_stack.addWidget(self._video_widget)
            self._player = VlcPreviewPlayer(self._video_widget, self)
            self._using_vlc = True
        else:
            self.viewer_stack.addWidget(self._video_widget)
        self._player.durationChanged.connect(lambda n: self.video_seek.setRange(0, n))
        self._player.positionChanged.connect(self._video_position)
        self._player.errorOccurred.connect(lambda *_: self.video_status.setText(self._player.errorString()))

    def _video_position(self, position):
        if not self.video_seek.isSliderDown():
            self.video_seek.setValue(position)
        suffix = " · Hay cambios: genera otra vista previa" if self._preview_video_stale else ""
        self.video_status.setText(f"{position / 1000:.1f} / {self._player.duration() / 1000:.1f} s" + suffix)

    def _toggle_playback(self):
        if self._player:
            self.viewer_stack.setCurrentWidget(self._video_widget)
            if self._using_vlc:
                playing = self._player.is_playing()
            else:
                from PyQt6.QtMultimedia import QMediaPlayer
                playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            if playing:
                self._player.pause()
            else:
                self._player.play()

    def _shutdown(self):
        if self._closing:
            return
        self._auto_save()
        self._closing = True
        self._autosave_timer.stop()
        self._composition_timer.stop()
        if self._player:
            if self._using_vlc:
                self._player.close()
            else:
                self._player.stop()
        if self._preview_worker:
            self._preview_worker.requestInterruption()
            self._preview_worker.wait()

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ proyecto
    def project(self) -> dict:
        split = lambda text: [l.strip() for l in text.splitlines() if l.strip()]  # noqa: E731
        style = {"speed": self.speed.value() / 100, "flashes": self.flashes.value() / 100,
                 "variants": [k for k, cb in self.variant_checks[1].items() if cb.isChecked()],
                 "transitions": [k for k, cb in self.transition_checks[1].items() if cb.isChecked()]}
        style.update({k: cb.isChecked() for k, cb in self._effect_boxes().items()})
        return ce.normalize_project({
            **self._project_extra,
            "topic": self.topic.text().strip(), "perspective": self.perspective.currentData(),
            "language": self.language.currentData(), "seconds": self.seconds.value(),
            "cards": {**self._cards_metadata, "opening": self.opening.text().strip(), "lines": split(self.lines.toPlainText()),
                      "climax": [w.strip().upper() for w in self.climax.text().split(",") if w.strip()],
                      "final": split(self.final.toPlainText()), "end": self.end.text().strip()},
            "media": [dict(m) for m in self.media], "music": self.music_path or None,
            "music_start": self.music_start.value(), "music_auto": self.music_auto.isChecked(),
            "style": style, "sequence": self.sequence, "last_output": self.last_output,
            "preview_guides": self.guides.isChecked(), "auto_assign_media": self.auto_assign_check.isChecked()})

    def _save_project(self):
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w-]+", "_", self.topic.text().strip())[:40] or "catarsis"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", str(self.current_project_path or PROJECTS_DIR / f"{name}.json"),
                                              "Proyecto Catarsis (*.json)")
        if path:
            try:
                self._write_project(path)
                self.log(f"Proyecto guardado: {path}")
            except Exception as exc:
                self.log(f"No se pudo guardar el proyecto: {exc}")

    def _load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", str(PROJECTS_DIR), "Proyecto Catarsis (*.json)")
        if path:
            try:
                self.load_project(Path(path))
            except Exception as exc:
                self.log(f"No se pudo abrir el proyecto: {exc}")

    def load_project(self, path: Path):
        path = Path(path).resolve()
        p = ce.normalize_project(json.loads(path.read_text(encoding="utf-8")), path.parent)
        if not self._auto_save():
            raise OSError("El proyecto actual tiene cambios que no se pudieron guardar")
        self._autosave_timer.stop()
        self._loading_project = True
        try:
            self._project_extra = copy.deepcopy(p)
            cards, style = p["cards"], p["style"]
            self.topic.setText(p.get("topic", ""))
            self.perspective.setCurrentIndex(max(0, self.perspective.findData(p.get("perspective", "character"))))
            self.language.setCurrentIndex(max(0, self.language.findData(p.get("language", "en"))))
            self.seconds.setValue(int(round(p["seconds"])))
            self._fill_cards(cards)
            self.speed.setValue(int(style.get("speed", 1) * 100))
            self.flashes.setValue(int(style.get("flashes", 1) * 100))
            for group, key in ((self.variant_checks, "variants"), (self.transition_checks, "transitions")):
                for k, cb in group[1].items():
                    cb.setChecked(k in style.get(key, []))
            for k, cb in self._effect_boxes().items():
                cb.setChecked(bool(style.get(k, ce.DEFAULT_STYLE.get(k, True))))
            self.media = p["media"]
            self._set_music(p.get("music") or "")
            self.music_start.setValue(float(p.get("music_start") or 0.0))
            self.music_auto.setChecked(bool(p.get("music_auto", True)))
            self.sequence = p.get("sequence") or []
            self.auto_assign_check.setChecked(bool(p.get("auto_assign_media", False)))
            self._refresh_media()
            self._refresh_table()
            self.current_project_path = path
            self.last_output = p.get("last_output", "")
            self.open_btn.setEnabled(bool(self.last_output and Path(self.last_output).is_file()))
            self.guides.setChecked(bool(p.get("preview_guides", False)))
            self._dirty = False
            self._settings.setValue("last_project", str(path))
            self.save_status.setText(f"Proyecto abierto · {path.name}")
            self.save_status.setToolTip(str(path))
            if self._player:
                self._player.stop()
                self._player.setSource(QUrl())
                self.play_btn.setEnabled(False)
                self.video_seek.setEnabled(False)
                self.viewer_stack.setCurrentWidget(self.shot_preview)
        finally:
            self._loading_project = False
        self._schedule_compositions()
        self.log(f"Proyecto abierto: {path}")

    def _fill_cards(self, cards: dict):
        self._filling_cards = True
        self._cards_metadata = {k: copy.deepcopy(v) for k, v in cards.items()
                                if k not in ce.DEFAULT_CARDS}
        self.opening.setText(cards.get("opening", ""))
        self.lines.setPlainText("\n".join(cards.get("lines", [])))
        self.climax.setText(", ".join(cards.get("climax", [])))
        self.final.setPlainText("\n".join(cards.get("final", [])))
        self.end.setText(cards.get("end", ""))
        self._filling_cards = False

    # ------------------------------------------------------------ medios
    def _media_context_menu(self, position):
        menu = QMenu(self.media_list)
        paste = menu.addAction("Pegar imagen o archivos")
        paste.setShortcut(QKeySequence.StandardKey.Paste)
        paste.setEnabled(can_import(QApplication.clipboard().mimeData()))
        paste.triggered.connect(self._paste_media)
        menu.exec(self.media_list.viewport().mapToGlobal(position))

    def _paste_media(self):
        self._import_media_mime(QApplication.clipboard().mimeData())

    def _import_media_mime(self, mime):
        before = len(self.media)
        if mime is None:
            return []
        paths = local_paths(mime)
        if paths:
            self.add_media_files(paths)
            return list(range(before, len(self.media)))
        image = image_from_mime(mime)
        if image.isNull():
            self.log("No hay una imagen ni archivos compatibles para pegar. Usa Copiar imagen o copia el archivo.")
            return []
        try:
            if self.current_project_path:
                folder = self.current_project_path.parent / (self.current_project_path.stem + "_media")
            else:
                if not hasattr(self, "_clipboard_draft_id"):
                    self._clipboard_draft_id = uuid.uuid4().hex
                folder = PROJECTS_DIR / "media" / self._clipboard_draft_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"pegada_{uuid.uuid4().hex}.png"
            output = QSaveFile(str(path))
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            if not image.save(output, "PNG"):
                output.cancelWriting()
                raise OSError("No se pudo guardar la imagen del portapapeles")
            if not output.commit():
                raise OSError(output.errorString())
            self.add_media_files([str(path)], "image")
        except Exception as exc:
            self.log(f"No se pudo pegar la imagen: {exc}")
        return list(range(before, len(self.media)))

    def _add_media(self, kind: str):
        pattern = ("Imagenes (" + " ".join("*" + e for e in sorted(IMAGE_EXTENSIONS)) + ")" if kind == "image"
                   else "Videos (" + " ".join("*" + e for e in sorted(ce.VIDEO_EXT)) + ")")
        files, _ = QFileDialog.getOpenFileNames(self, "Agregar " + ("imagenes" if kind == "image" else "videos"),
                                                "", pattern)
        self.add_media_files(files, kind)

    def add_media_files(self, files, kind: str | None = None):
        added = 0
        for f in files:
            try:
                if not supported_file(f):
                    raise ValueError("archivo inexistente o formato no compatible")
                path = Path(f).resolve()
                media_kind = "video" if path.suffix.lower() in ce.VIDEO_EXT else "image"
                item = {"file": str(path), "type": media_kind, "focus": [0.5, 0.5], "zoom": 1.0}
                if media_kind == "video":
                    info = ce.media_info(str(path))
                    if not info.get("width") or not info.get("height"):
                        raise ValueError("el archivo no contiene una pista de video")
                    item.update({"in": 0.0, "out": round(info["duration"], 2), "audio": False})
                else:
                    from PIL import Image
                    with Image.open(path) as source:
                        source.verify()
            except Exception as exc:
                self.log(f"No se agregó {Path(f).name}: {exc}")
                continue
            self.media.append(item)
            added += 1
        if added:
            self._refresh_media()
            self.media_list.setCurrentRow(len(self.media) - 1)
            self._refresh_table()
            self.log(f"Medios agregados: {added}.")
            self._auto_save()
        return added

    def _remove_media(self):
        row = self.media_list.currentRow()
        if row < 0:
            return
        self.media.pop(row)
        # Preserve the plan: removed media leaves an explicit assignment slot.
        self._remap_media(lambda i: None if i == row else (i - 1 if i > row else i))
        self._refresh_media()
        self._refresh_table()

    def _move_media(self, delta: int):
        row = self.media_list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < len(self.media):
            return
        self.media[row], self.media[new] = self.media[new], self.media[row]
        self._remap_media(lambda i: {row: new, new: row}.get(i, i))
        self._refresh_media()
        self._refresh_table()
        self.media_list.setCurrentRow(new)

    def _remap_media(self, fn):
        """Los planos siguen a sus medios cuando cambia la lista. fn: indice viejo -> nuevo (None: se quito)."""
        for s in self.sequence:
            for slot in media_slots(s):
                index = slot_value(s, slot)
                set_slot(s, slot, fn(index) if type(index) is int else None)

    def _media_label(self, i: int, m: dict) -> str:
        tags = " · video" + (" · con audio" if m.get("audio") else "") if m.get("type") == "video" else ""
        return f"{i + 1}. {Path(m['file']).name}{tags}"

    def _refresh_media(self):
        current = self.media_list.currentRow()
        self.media_list.blockSignals(True)
        self.media_list.clear()
        for i, m in enumerate(self.media):
            item = QListWidgetItem(self._media_label(i, m))
            try:
                item.setIcon(QIcon(_pixmap(ce.media_thumbnail(m, (54, 96)))))
            except Exception as exc:
                item.setToolTip(f"Sin miniatura: {exc}")
            self.media_list.addItem(item)
        self.media_list.blockSignals(False)
        if self.media:
            self.media_list.setCurrentRow(min(max(current, 0), len(self.media) - 1))
            self._load_media_props(self.media_list.currentRow())
        self._changed()

    def _load_media_props(self, row: int):
        if not 0 <= row < len(self.media):
            return
        m = self.media[row]
        self._loading = True
        self.m_x.setValue(m.get("focus", [0.5, 0.5])[0])
        self.m_y.setValue(m.get("focus", [0.5, 0.5])[1])
        self.m_zoom.setValue(m.get("zoom", 1.0))
        is_video = m.get("type") == "video"
        for w in (self.m_in, self.m_out, self.m_audio):
            w.setEnabled(is_video)
        self.m_in.setValue(m.get("in", 0.0))
        self.m_out.setValue(m.get("out", 0.0))
        self.m_audio.setChecked(bool(m.get("audio")))
        self._loading = False

    def _save_media_props(self):
        row = self.media_list.currentRow()
        if self._loading or not 0 <= row < len(self.media):
            return
        m = self.media[row]
        m.update({"focus": [self.m_x.value(), self.m_y.value()], "zoom": self.m_zoom.value()})
        if m.get("type") == "video":
            m.update({"in": self.m_in.value(), "out": max(self.m_out.value(), self.m_in.value()),
                      "audio": self.m_audio.isChecked()})
            for s in self.sequence:   # los planos de este video siguen la casilla de audio
                if s.get("kind") == "media" and s.get("media") == row:
                    s["audio"] = m["audio"]
        item = self.media_list.item(row)
        item.setText(self._media_label(row, m))
        try:
            item.setIcon(QIcon(_pixmap(ce.media_thumbnail(m, (54, 96)))))
        except Exception:
            pass
        self._changed()

    # ------------------------------------------------------------ musica
    def _set_music(self, path: str):
        self.music_path = str(path or "")
        self.music_edit.setText(self.music_path)
        self._changed()

    def _pick_music(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir musica", "", "Audio (*.mp3 *.wav *.m4a *.ogg *.flac)")
        if path:
            self._set_music(path)

    def _jamendo(self):
        try:
            from music_browser_dialog import MusicBrowserDialog
            dlg = MusicBrowserDialog(self, log_callback=self.log)
            if dlg.exec() and getattr(dlg, "selected_music_path", None):
                self._set_music(dlg.selected_music_path)
                self.log("Musica de Jamendo: recuerda pegar su atribucion CC BY en la descripcion al publicar.")
        except Exception as exc:
            self.log(f"No se pudo abrir el buscador de Jamendo: {exc}")

    # ------------------------------------------------------------ IA
    def _write_cards(self):
        topic = self.topic.text().strip()
        if not topic:
            self.log("Escribe primero el tema.")
            return
        self._busy(True)
        self._worker = _CardsWorker(topic, self.perspective.currentData(), self.language.currentData())
        self._worker.line.connect(self.log)
        self._worker.done.connect(self._cards_done)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _cards_done(self, cards: dict):
        self._busy(False)
        self._fill_cards(cards)
        direction = cards.get("direction") or {}
        if direction:
            self.log(f"Perspectiva: {direction.get('speaker')}. Momento: {direction.get('moment')}")
            self.log(f"Conflicto: {direction.get('conflict')}")
            self.log(f"Giro: {direction.get('turn')}. Cierre: {direction.get('payoff')}")
        check = cards.get("fact_check") or {}
        review = cards.get("narrative_review") or {}
        needs_review = review.get("status") == "needs_review" or bool(check.get("remaining"))
        state = "Borrador para revisar" if needs_review else "Tarjetas listas"
        self.log(f"{state}. Verificacion de hechos: {check.get('status', 'sin verificar')}.")
        for issue in review.get("issues", []):
            self.log(f"  Revision narrativa: {issue}")
        for f in check.get("remaining", []):
            self.log(f"  Revisar: \"{f.get('quote')}\" ({f.get('verdict')}). Dato documentado: {f.get('correction')}")
        self._changed()
        self._auto_save()

    # ------------------------------------------------------------ secuencia
    def _auto_sequence(self):
        self._busy(True)
        music = " y buscando los golpes y la caida de la musica..." if self.music_path else "..."
        self.log("Armando el arco" + music)
        self._worker = _SequenceWorker(self.project())
        self._worker.done.connect(self._sequence_done)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _sequence_done(self, sequence: list, beats: int, drop, start: float):
        self._busy(False)
        self.music_start.setValue(start)
        if self.music_path and start:
            self.log(f"La musica arranca en el segundo {start:.1f} de la pista.")
        self.sequence = sequence
        self._refresh_table()
        self.log(f"Secuencia armada: {len(sequence)} planos" + (f", {beats} golpes de musica." if beats else "."))
        if drop:
            self.log(f"Caida de la musica en {drop:.1f} s: el quiebre termina ahi.")
        self._auto_save()

    def _combo(self, names: dict, value, on_change):
        c = QComboBox()
        c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        c.setMinimumContentsLength(8)
        for key, name in names.items():
            c.addItem(name, key)
        c.setCurrentIndex(max(0, c.findData(value)))
        c.currentIndexChanged.connect(lambda _i: (on_change(c.currentData()), self._changed()))
        return c

    def _refresh_table(self):
        selected = self.table.currentRow()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        media_names = {i: f"{i + 1}. {Path(m['file']).name}" for i, m in enumerate(self.media)}
        for row, spec in enumerate(self.sequence):
            self.table.insertRow(row)
            thumb = QTableWidgetItem()
            thumb.setFlags(thumb.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 6, thumb)
            kind = spec.get("kind", "media")
            tag = " (quiebre)" if spec.get("tag") == "break" else ""
            self.table.setItem(row, 0, QTableWidgetItem(f"#{row + 1} · {KIND_NAMES.get(kind, kind)}{tag}"))
            set_key = lambda key, s=spec: (lambda value: (s.__setitem__(key, value), self._update_total(), self._changed()))  # noqa: E731
            if kind == "card":
                self.table.setItem(row, 1, QTableWidgetItem(spec.get("text", "")))
                self.table.setCellWidget(row, 2, self._combo(CARD_STYLES, spec.get("style"), set_key("style")))
            elif kind == "color":
                self.table.setCellWidget(row, 1, self._combo(COLOR_NAMES, spec.get("color"), set_key("color")))
                self.table.setItem(row, 2, QTableWidgetItem("-"))
            else:
                self.table.setCellWidget(row, 1, self._media_cell(spec, media_names))
                self.table.setRowHeight(row, max(92, 38 * len(media_slots(spec)) +
                                                (48 if kind == "overlay" else 22)))
                if kind == "impact":
                    self.table.setItem(row, 2, QTableWidgetItem("-"))
                else:
                    self.table.setCellWidget(row, 2, self._combo(VARIANT_NAMES, spec.get("variant"),
                                                                 set_key("variant")))
            for col in (0, 2):
                item = self.table.item(row, col)
                if item is not None:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            secs = QDoubleSpinBox()
            secs.setDecimals(3)
            secs.setRange(1 / ce.FPS, max(600, float(spec.get("seconds", 1.0))))
            secs.setSingleStep(1 / ce.FPS)
            secs.setValue(float(spec.get("seconds", 1.0)))
            secs.setToolTip("Duración editable, en segundos. Inicio y fin se calculan a 30 cuadros por segundo.")
            secs.valueChanged.connect(lambda value, s=spec: self._set_duration(s, value))
            self.table.setCellWidget(row, 3, secs)
            self.table.setCellWidget(row, 4, self._combo(TRANSITION_NAMES, spec.get("transition", "cut"),
                                                         set_key("transition")))
            self.table.setCellWidget(row, 5, self._combo(MOTION_NAMES, spec.get("motion", "hold"), set_key("motion")))
        self.table.blockSignals(False)
        self._update_total()
        if self.sequence:
            self.table.selectRow(min(max(selected, 0), len(self.sequence) - 1))
        self._selection_changed()
        self._changed()

    def _media_cell(self, spec: dict, names: dict) -> QWidget:
        slots = media_slots(spec)
        cell = self._assignment_target(spec, slots[0])
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(3)
        missing = missing_slots(spec, self.media)
        for n, slot in enumerate(slots):
            target = self._assignment_target(spec, slot)
            h = QHBoxLayout(target)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(3)
            if len(slots) > 1:
                h.addWidget(QLabel(str(n + 1)))
            value = slot_value(spec, slot)
            choices = {None: "Sin asignar", **names}
            if slot in missing and value is not None:
                choices[value] = "Archivo no disponible"
            combo = self._combo(choices, value,
                                lambda v, s=spec, sl=slot: self._assign_slot(s, sl, v))
            combo.setToolTip("Elige un archivo de la biblioteca; puedes reutilizarlo en otras escenas.")
            h.addWidget(combo, 1)
            pick = QPushButton("Archivo…")
            pick.setToolTip("Asignar una imagen o video a este espacio")
            pick.clicked.connect(lambda _checked=False, s=spec, sl=slot: self._pick_scene_media(s, sl))
            h.addWidget(pick)
            paste = QPushButton("Pegar")
            paste.clicked.connect(lambda _checked=False, s=spec, sl=slot:
                                  self._import_scene_media(s, sl, QApplication.clipboard().mimeData()))
            h.addWidget(paste)
            layout.addWidget(target)
        if spec.get("kind") == "overlay":
            text = QLineEdit(spec.get("text", ""))
            text.textEdited.connect(lambda value, s=spec: (s.__setitem__("text", value), self._changed()))
            text.setToolTip("Texto que aparecerá sobre la imagen o el video")
            layout.addWidget(text)
        hint = QLabel("Arrastra aquí · clic derecho para pegar")
        hint.setStyleSheet("color:#64748b;font-size:10px;")
        layout.addWidget(hint)
        return cell

    def _assignment_target(self, spec, slot):
        target = MediaDropArea()
        target.media_dropped.connect(lambda mime: self._import_scene_media(spec, slot, mime))
        target.paste_requested.connect(lambda: self._import_scene_media(spec, slot, QApplication.clipboard().mimeData()))
        target.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        target.customContextMenuRequested.connect(lambda pos: self._scene_context_menu(target, pos, spec, slot))
        return target

    def _scene_context_menu(self, target, position, spec, slot):
        menu = QMenu(target)
        paste = menu.addAction("Pegar imagen o archivos en esta escena")
        paste.setEnabled(can_import(QApplication.clipboard().mimeData()))
        paste.triggered.connect(lambda: self._import_scene_media(spec, slot, QApplication.clipboard().mimeData()))
        clear = menu.addAction("Quitar asignación")
        clear.triggered.connect(lambda: (self._assign_slot(spec, slot, None), self._refresh_table()))
        menu.exec(target.mapToGlobal(position))

    def _pick_scene_media(self, spec, slot):
        pattern = "Imagenes y videos (" + " ".join("*" + e for e in sorted(IMAGE_EXTENSIONS | ce.VIDEO_EXT)) + ")"
        path, _ = QFileDialog.getOpenFileName(self, "Asignar imagen o video a la escena", "", pattern)
        if path:
            before = len(self.media)
            self.add_media_files([path])
            self._assign_imported(spec, slot, list(range(before, len(self.media))))

    def _import_scene_media(self, spec, slot, mime):
        self._assign_imported(spec, slot, self._import_media_mime(mime))

    def _assign_imported(self, spec, slot, indices):
        if not indices or not any(s is spec for s in self.sequence):
            return
        slots = media_slots(spec)
        destinations = slots[slots.index(slot):]
        # A multi-file drop can fill the remaining panels of a composite scene.
        for dest, index in zip(destinations, indices):
            self._set_shot_slot(spec, dest, index)
        if len(indices) > len(destinations):
            self.log("Los archivos adicionales quedaron en la biblioteca para asignarlos a otras escenas.")
        self._refresh_table()
        self.table.selectRow(next(i for i, s in enumerate(self.sequence) if s is spec))
        self._auto_save()

    def _set_shot_slot(self, spec, slot, index):
        set_slot(spec, slot, index)
        if slot == ("media", None) and spec.get("kind") == "media":
            valid = type(index) is int and 0 <= index < len(self.media)
            spec.update(offset=0.0, audio=bool(valid and self.media[index].get("audio")))

    def _assign_slot(self, spec, slot, index):
        self._set_shot_slot(spec, slot, index)
        self._update_total()
        row = next((i for i, s in enumerate(self.sequence) if s is spec), -1)
        if row >= 0:
            self.table.selectRow(row)
        self._selection_changed()
        self._changed()

    def _set_duration(self, spec, seconds):
        spec["seconds"] = max(1, round(seconds * ce.FPS)) / ce.FPS
        self._update_total()
        self._selection_changed()
        self._changed()

    def _update_total(self):
        info = assignment_summary(self.sequence, self.media)
        timings = plan_timings(self.sequence, ce.FPS)
        total = timings[-1][1] if timings else 0
        self.total_label.setText(
            f"{info['total']} escenas · {total:.3f} s en total\n"
            f"{info['visual']} requieren imagen/video: {info['complete']} completas · {len(info['pending'])} pendientes\n"
            f"{info['missing']} de {info['slots']} espacios por asignar · Puedes reutilizar archivos."
            if self.sequence else "Pulsa Planificar escenas para saber cuánto material necesitas.")
        self.pending_btn.setEnabled(bool(info["pending"]))
        self.table.blockSignals(True)
        for row, (start, end) in enumerate(timings):
            for col, seconds in ((7, start), (8, end)):
                item = QTableWidgetItem(timecode(seconds))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
            pending = info["pending"].get(row, [])
            slots = media_slots(self.sequence[row])
            status = f"Faltan {len(pending)}/{len(slots)}" if pending else ("Asignada" if slots else "Sin archivo")
            kind = KIND_NAMES.get(self.sequence[row].get("kind"), "")
            item = self.table.item(row, 0)
            if item:
                item.setText(f"#{row + 1} · {kind}\n{status}")
                item.setForeground(QColor("#a7540a") if pending else self.palette().text())
                item.setToolTip(f"Escena {row + 1} · {end - start:.3f} s\n{status}")
            thumb = self.table.item(row, 6)
            if thumb:
                thumb.setText("Falta\nmaterial" if pending else "")
                if pending:
                    thumb.setIcon(QIcon())
                    thumb.setToolTip("Asigna una imagen o video en Contenido")
        self.table.blockSignals(False)
        self.timeline.set_plan(timings, info["pending"], [s.get("kind") for s in self.sequence])

    def _next_pending(self):
        pending = list(assignment_summary(self.sequence, self.media)["pending"])
        if pending:
            current = self._selected_shot()
            row = next((i for i in pending if i > current), pending[0])
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 0))

    def _select_timeline_scene(self, row):
        if 0 <= row < len(self.sequence):
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 0))

    def _card_text_changed(self, item: QTableWidgetItem):
        row = item.row()
        if item.column() == 1 and 0 <= row < len(self.sequence) and self.sequence[row].get("kind") == "card":
            self.sequence[row]["text"] = item.text()
            self._changed()

    def _selected_shot(self) -> int:
        return self.table.currentRow() if 0 <= self.table.currentRow() < len(self.sequence) else -1

    def _move_shot(self, delta: int):
        row = self._selected_shot()
        new = row + delta
        if row < 0 or not 0 <= new < len(self.sequence):
            return
        self.sequence[row], self.sequence[new] = self.sequence[new], self.sequence[row]
        self._refresh_table()
        self.table.selectRow(new)

    def _duplicate_shot(self):
        row = self._selected_shot()
        if row >= 0:
            self.sequence.insert(row + 1, dict(copy.deepcopy(self.sequence[row]), tag=""))
            self._refresh_table()
            self.table.selectRow(row + 1)

    def _delete_shot(self):
        row = self._selected_shot()
        if row >= 0:
            self.sequence.pop(row)
            self._refresh_table()
            self.table.selectRow(min(row, len(self.sequence) - 1))

    # ------------------------------------------------------------ render
    def _render(self, preview: bool):
        if not self.sequence:
            self.log("Primero usa Planificar escenas.")
            return
        pending = assignment_summary(self.sequence, self.media)["pending"]
        if pending:
            first = next(iter(pending))
            self.table.selectRow(first)
            self.table.scrollToItem(self.table.item(first, 0))
            self.log(f"Falta asignar material en {len(pending)} escenas. Empieza por la escena {first + 1} "
                     "y usa Siguiente pendiente para completarlas.")
            return
        project = self.project()
        self._render_project_signature = json.dumps(project, sort_keys=True)
        if preview:
            out = PREVIEW_PATH
            if self._player:
                self._player.stop()
                self._player.setSource(QUrl())
                self.play_btn.setEnabled(False)
                self.video_seek.setEnabled(False)
        else:
            from infra.output_naming import build_video_filename
            out = OUTPUT_DIR / build_video_filename("catarsis", project.get("topic") or "catarsis")
        self._busy(True)
        self.progress.setValue(0)
        self._worker = _RenderWorker(project, out, preview, self.guides.isChecked())
        self._worker.line.connect(self.log)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.done.connect(lambda path: self._render_done(path, preview))
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _render_done(self, path: str, preview: bool):
        self._busy(False)
        stale = json.dumps(self.project(), sort_keys=True) != getattr(self, "_render_project_signature", "")
        self.last_output = path
        self.open_btn.setEnabled(True)
        self.log(("Vista previa lista: " if preview else "Video listo: ") + path)
        if preview:
            try:
                self._ensure_player()
                self._player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
                self.viewer_stack.setCurrentWidget(self._video_widget)
                self.play_btn.setEnabled(True)
                self.video_seek.setEnabled(True)
                self._player.play()
            except Exception as exc:
                self.log(f"No se pudo reproducir dentro de la app: {exc}. Usa Abrir video.")
        self._changed()
        self._preview_video_stale = stale
        self._auto_save()

    def _failed(self, msg: str):
        self._busy(False)
        self.log(f"Error: {msg}")
