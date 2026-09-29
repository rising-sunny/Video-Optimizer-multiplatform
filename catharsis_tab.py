# -*- coding: utf-8 -*-
"""Pestana Catarsis: Short vertical de impacto, sin voz (motor: catharsis_editor).

Eliges medios (imagenes y videos, con o sin su audio), escribes las tarjetas o las propone la
IA con los hechos verificados, eliges musica y estilo. "Armar automatico" crea la secuencia de
planos con el arco; despues cada plano se retoca (contenido, variante, duracion, transicion,
movimiento) antes de la vista previa y el render final en auto_videos/output.
"""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                             QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider,
                             QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import catharsis_editor as ce

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
            seq = ce.auto_sequence(self.project, beats, seed=int(time.time()) % 1000, drop=drop)
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


class CatharsisTab(QWidget):
    def __init__(self, parent_gui=None):
        super().__init__()
        self.parent_gui = parent_gui
        self.media: list[dict] = []
        self.sequence: list[dict] = []
        self.music_path = ""
        self.last_output = ""
        self._worker = None
        self._loading = False
        self._build_ui()

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
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        split.addWidget(scroll)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(self._sequence_group(), 3)
        rv.addWidget(self._render_group(), 1)
        split.addWidget(right)
        split.setSizes([620, 700])

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
        self.media_list = QListWidget()
        self.media_list.setIconSize(QSize(54, 96))
        self.media_list.setMinimumHeight(200)
        self.media_list.currentRowChanged.connect(self._load_media_props)
        v.addWidget(self.media_list)
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
        self.variant_checks = self._checks(VARIANT_NAMES, ce.DEFAULT_STYLE["variants"])
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
        return box

    def _sequence_group(self):
        box = QGroupBox("Secuencia de planos")
        v = QVBoxLayout(box)
        top = QHBoxLayout()
        self.auto_btn = QPushButton("Armar automatico")
        self.auto_btn.setToolTip("Arma el arco (apertura, subida, climax, quiebre y cierre) con tus medios y tarjetas.")
        self.auto_btn.clicked.connect(self._auto_sequence)
        top.addWidget(self.auto_btn)
        self.total_label = QLabel("Sin secuencia todavia.")
        top.addWidget(self.total_label, 1)
        for text, slot in (("Subir", lambda: self._move_shot(-1)), ("Bajar", lambda: self._move_shot(1)),
                           ("Duplicar", self._duplicate_shot), ("Eliminar", self._delete_shot)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            top.addWidget(b)
        v.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Plano", "Contenido", "Variante / estilo", "Segundos",
                                              "Transicion", "Movimiento"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 130), (2, 120), (3, 90), (4, 110), (5, 110)):
            self.table.setColumnWidth(col, width)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._card_text_changed)
        v.addWidget(self.table)
        return box

    def _render_group(self):
        box = QGroupBox("Render")
        v = QVBoxLayout(box)
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
        for b in (self.preview_btn, self.guides, self.render_btn, self.open_btn, save_btn, load_btn):
            row.addWidget(b)
        v.addLayout(row)
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

    # ------------------------------------------------------------ proyecto
    def project(self) -> dict:
        split = lambda text: [l.strip() for l in text.splitlines() if l.strip()]  # noqa: E731
        style = {"speed": self.speed.value() / 100, "flashes": self.flashes.value() / 100,
                 "variants": [k for k, cb in self.variant_checks[1].items() if cb.isChecked()],
                 "transitions": [k for k, cb in self.transition_checks[1].items() if cb.isChecked()]}
        style.update({k: cb.isChecked() for k, cb in self._effect_boxes().items()})
        return ce.normalize_project({
            "topic": self.topic.text().strip(), "perspective": self.perspective.currentData(),
            "language": self.language.currentData(), "seconds": self.seconds.value(),
            "cards": {"opening": self.opening.text().strip(), "lines": split(self.lines.toPlainText()),
                      "climax": [w.strip().upper() for w in self.climax.text().split(",") if w.strip()],
                      "final": split(self.final.toPlainText()), "end": self.end.text().strip()},
            "media": [dict(m) for m in self.media], "music": self.music_path or None,
            "music_start": self.music_start.value(), "music_auto": self.music_auto.isChecked(),
            "style": style, "sequence": self.sequence})

    def _save_project(self):
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w-]+", "_", self.topic.text().strip())[:40] or "catarsis"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", str(PROJECTS_DIR / f"{name}.json"),
                                              "Proyecto Catarsis (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.project(), ensure_ascii=False, indent=2), encoding="utf-8")
            self.log(f"Proyecto guardado: {path}")

    def _load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", str(PROJECTS_DIR), "Proyecto Catarsis (*.json)")
        if path:
            self.load_project(Path(path))

    def load_project(self, path: Path):
        p = ce.normalize_project(json.loads(path.read_text(encoding="utf-8")), path.parent)
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
        self._refresh_media()
        self._refresh_table()
        self.log(f"Proyecto abierto: {path}")

    def _fill_cards(self, cards: dict):
        self.opening.setText(cards.get("opening", ""))
        self.lines.setPlainText("\n".join(cards.get("lines", [])))
        self.climax.setText(", ".join(cards.get("climax", [])))
        self.final.setPlainText("\n".join(cards.get("final", [])))
        self.end.setText(cards.get("end", ""))

    # ------------------------------------------------------------ medios
    def _add_media(self, kind: str):
        pattern = ("Imagenes (*.jpg *.jpeg *.png *.webp *.bmp)" if kind == "image"
                   else "Videos (" + " ".join("*" + e for e in sorted(ce.VIDEO_EXT)) + ")")
        files, _ = QFileDialog.getOpenFileNames(self, "Agregar " + ("imagenes" if kind == "image" else "videos"),
                                                "", pattern)
        self.add_media_files(files, kind)

    def add_media_files(self, files, kind: str):
        for f in files:
            item = {"file": str(f), "type": kind, "focus": [0.5, 0.5], "zoom": 1.0}
            if kind == "video":
                info = ce.media_info(str(f))
                item.update({"in": 0.0, "out": round(info["duration"], 2), "audio": False})
            self.media.append(item)
        self._refresh_media()
        if files:
            self.media_list.setCurrentRow(len(self.media) - 1)

    def _remove_media(self):
        row = self.media_list.currentRow()
        if row < 0:
            return
        self.media.pop(row)
        # los planos que usaban ese medio se quitan; los de los medios siguientes se corren uno
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
        kept = []
        for s in self.sequence:
            if s.get("kind") in MEDIA_KINDS:
                for key in ("media", "media2"):
                    if key in s:
                        s[key] = fn(s[key])
                if "medias" in s:
                    s["medias"] = [x for x in map(fn, s["medias"]) if x is not None]
                if None in (s.get("media", 0), s.get("media2", 0)) or len(s.get("medias", (0, 0))) < 2:
                    continue   # el plano se quedo sin su medio
            kept.append(s)
        self.sequence = kept

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

    # ------------------------------------------------------------ musica
    def _set_music(self, path: str):
        self.music_path = str(path or "")
        self.music_edit.setText(self.music_path)

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
        check = cards.get("fact_check") or {}
        self.log(f"Tarjetas listas. Verificacion de hechos: {check.get('status', 'sin verificar')}.")
        for f in check.get("remaining", []):
            self.log(f"  Revisar: \"{f.get('quote')}\" ({f.get('verdict')}). Dato documentado: {f.get('correction')}")

    # ------------------------------------------------------------ secuencia
    def _auto_sequence(self):
        if not self.media:
            self.log("Agrega al menos una imagen o un video.")
            return
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

    def _combo(self, names: dict, value, on_change):
        c = QComboBox()
        for key, name in names.items():
            c.addItem(name, key)
        c.setCurrentIndex(max(0, c.findData(value)))
        c.currentIndexChanged.connect(lambda _i: on_change(c.currentData()))
        return c

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        media_names = {i: f"{i + 1}. {Path(m['file']).name}" for i, m in enumerate(self.media)}
        for row, spec in enumerate(self.sequence):
            self.table.insertRow(row)
            kind = spec.get("kind", "media")
            tag = " (quiebre)" if spec.get("tag") == "break" else ""
            self.table.setItem(row, 0, QTableWidgetItem(KIND_NAMES.get(kind, kind) + tag))
            set_key = lambda key, s=spec: (lambda value: (s.__setitem__(key, value), self._update_total()))  # noqa: E731
            if kind == "card":
                self.table.setItem(row, 1, QTableWidgetItem(spec.get("text", "")))
                self.table.setCellWidget(row, 2, self._combo(CARD_STYLES, spec.get("style"), set_key("style")))
            elif kind == "color":
                self.table.setCellWidget(row, 1, self._combo(COLOR_NAMES, spec.get("color"), set_key("color")))
                self.table.setItem(row, 2, QTableWidgetItem("-"))
            else:
                self.table.setCellWidget(row, 1, self._media_cell(spec, media_names))
                if kind == "impact":
                    self.table.setItem(row, 2, QTableWidgetItem("-"))
                else:
                    self.table.setCellWidget(row, 2, self._combo(VARIANT_NAMES, spec.get("variant"),
                                                                 set_key("variant")))
            for col in (0, 2):
                item = self.table.item(row, col)
                if item is not None:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            secs = self._spin(0.03, 20, 0.05, float(spec.get("seconds", 1.0)))
            secs.valueChanged.connect(set_key("seconds"))
            self.table.setCellWidget(row, 3, secs)
            self.table.setCellWidget(row, 4, self._combo(TRANSITION_NAMES, spec.get("transition", "cut"),
                                                         set_key("transition")))
            self.table.setCellWidget(row, 5, self._combo(MOTION_NAMES, spec.get("motion", "hold"), set_key("motion")))
        self.table.blockSignals(False)
        self._update_total()

    def _media_cell(self, spec: dict, names: dict) -> QWidget:
        """Contenido de un plano con medios: el medio (dos en la doble exposicion, varios en la pantalla
        dividida) y, en el texto sobre imagen, la frase."""
        cell = QWidget()
        h = QHBoxLayout(cell)
        h.setContentsMargins(0, 0, 0, 0)
        if spec.get("kind") == "split":
            for k, value in enumerate(spec.get("medias") or []):
                h.addWidget(self._combo(names, value, lambda v, s=spec, k=k: s["medias"].__setitem__(k, v)))
        else:
            combo = self._combo(names, spec.get("media"), lambda v, s=spec: self._set_shot_media(s, v))
            if spec.get("kind") == "overlay":
                combo.setMaximumWidth(150)   # el espacio es para la frase
            h.addWidget(combo)
            if spec.get("kind") == "double":
                h.addWidget(self._combo(names, spec.get("media2"), lambda v, s=spec: s.__setitem__("media2", v)))
        if spec.get("kind") == "overlay":
            text = QLineEdit(spec.get("text", ""))
            text.textEdited.connect(lambda value, s=spec: s.__setitem__("text", value))
            h.addWidget(text, 1)
        return cell

    def _set_shot_media(self, spec: dict, index: int):
        """Otro medio para el plano: toma la casilla de audio de ese video y arranca desde su inicio."""
        spec["media"] = index
        if spec.get("kind") == "media":
            spec.update(offset=0.0, audio=bool(self.media[index].get("audio")))

    def _update_total(self):
        total = sum(float(s.get("seconds", 0)) for s in self.sequence)
        self.total_label.setText(f"{len(self.sequence)} planos, {total:.1f} s" if self.sequence
                                 else "Sin secuencia todavia.")

    def _card_text_changed(self, item: QTableWidgetItem):
        row = item.row()
        if item.column() == 1 and 0 <= row < len(self.sequence) and self.sequence[row].get("kind") == "card":
            self.sequence[row]["text"] = item.text()

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
            self.log("Primero arma la secuencia (Armar automatico).")
            return
        project = self.project()
        if preview:
            out = PREVIEW_PATH
        else:
            from output_naming import build_video_filename
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
        self.last_output = path
        self.open_btn.setEnabled(True)
        self.log(("Vista previa lista: " if preview else "Video listo: ") + path)
        if preview:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _failed(self, msg: str):
        self._busy(False)
        self.log(f"Error: {msg}")
