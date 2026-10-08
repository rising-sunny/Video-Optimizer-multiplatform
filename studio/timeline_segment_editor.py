# timeline_segment_editor.py
"""
Editor detallado para un segmento individual del timeline.
ExtraÃ­do de timeline_editor_widget.py para mejorar la organizaciÃ³n del cÃ³digo.
"""

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QScrollArea, QGroupBox, QMessageBox, QLineEdit, QDoubleSpinBox,
    QCheckBox, QComboBox, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from pipeline.segment_layouts import BLENDER_ENVIRONMENTS, LAYOUT_LABELS, LAYOUT_VERSION, normalize_layout


class SegmentEditor(QWidget):
    """
    Editor detallado para un segmento individual.
    Permite editar todos los campos del segmento.
    """
    
    saved = pyqtSignal(dict)  # Emite los datos guardados
    wikimedia_search_requested = pyqtSignal(dict)  # Emite cuando se solicita bÃºsqueda de Wikimedia con los datos del segmento
    openverse_images_search_requested = pyqtSignal(dict)  # Emite cuando se solicita bÃºsqueda de Openverse con los datos del segmento
    pexels_video_search_requested = pyqtSignal(dict)  # Emite cuando se solicita bÃºsqueda de videos de Pexels con los datos del segmento
    local_image_requested = pyqtSignal(dict)  # Emite cuando se solicita insertar imagen local
    clipboard_image_requested = pyqtSignal(dict)  # Emite cuando se solicita pegar una imagen desde el portapapeles
    local_video_requested = pyqtSignal(dict)  # Emite cuando se solicita insertar video local
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_segment = None
        self._auto_save_timer = None  # Timer para auto-guardado con debounce
        self._save_in_progress = False  # Evita re-entradas al guardar
        self.setup_ui()

    def _snapshot_editor_values(self):
        """Captura valores actuales del formulario para comparar/guardar."""
        return {
            'start': self.start_spin.value(),
            'end': self.end_spin.value(),
            'text': self.text_edit.toPlainText(),
            'visual_prompt': self.visual_edit.toPlainText(),
            'motion_prompt': self.motion_edit.toPlainText(),
            'sfx_tag': self.sfx_edit.text().strip() or 'none',
            'overlay_tag': self.overlay_edit.text().strip() or 'none',
            'assigned_filename': self.filename_edit.text().strip(),
            'hook_overlay': self._hook_snapshot(),
            'cinematic_plan': self._cinematic_plan_snapshot(),
            'layout_plan': self._layout_plan_snapshot(),
        }

    def _cinematic_plan_snapshot(self):
        current = (self.current_segment or {}).get('cinematic_plan') or {}
        locked = bool(self.cinematic_lock_check.isChecked())
        if not current and not locked:
            return None
        plan = dict(current)
        plan.update({
            'version': plan.get('version') or 'cinematic_director_v1',
            'camera': self.cinematic_camera_combo.currentData(),
            'atmosphere': self.cinematic_atmosphere_combo.currentData(),
            'lighting': self.cinematic_lighting_combo.currentData(),
            'lens': self.cinematic_lens_combo.currentData(),
            'intensity': round(float(self.cinematic_intensity_spin.value()), 2),
            'locked': locked,
        })
        if locked:
            plan['role'] = plan.get('role') or 'manual'
        return plan

    # --- Composicion de la escena (pipeline/segment_layouts) ------------------------
    def _layout_plan_snapshot(self):
        """`layout_plan` segun el formulario. 'Automatica' lo deja en manos del
        planificador (sin fijar); un tipo concreto lo fija para esta escena."""
        current = (self.current_segment or {}).get('layout_plan') or None
        choice = self.layout_combo.currentData()
        extra = list(self._layout_extra_media)
        if choice == 'auto':
            if current is None and not extra:
                return None
            plan = dict(current or {})
            if plan.get('locked'):
                plan['locked'] = False
        else:
            plan = dict(current or {})
            plan.update({
                'version': plan.get('version') or LAYOUT_VERSION,
                'layout': choice,
                'reason': 'manual',
                'tag': self.layout_tag_edit.text().strip().upper(),
                'locked': True,
            })
            if choice == 'blender_3d':
                plan['environment'] = self.layout_env_combo.currentData()
        if extra or 'extra_media' in plan:
            plan['extra_media'] = extra
        return plan

    def _layout_choice_changed(self, *_args):
        fixed = self.layout_combo.currentData() != 'auto'
        self.layout_tag_edit.setEnabled(fixed)
        self.layout_env_combo.setEnabled(self.layout_combo.currentData() == 'blender_3d')
        self._trigger_auto_save()

    def _refresh_layout_extra_label(self):
        if self._layout_extra_media:
            names = ", ".join(os.path.basename(p) for p in self._layout_extra_media)
            self.layout_extra_label.setText(f"Media extra: {names}")
        else:
            self.layout_extra_label.setText("Media extra: escenas vecinas o detalle")
        self.btn_layout_extra_clear.setEnabled(bool(self._layout_extra_media))

    def _choose_layout_extra_media(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Imagen extra para la composicion", "",
            "Imagenes (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._layout_extra_media = [os.path.abspath(path)]
            self._refresh_layout_extra_label()
            self._trigger_auto_save()

    def _clear_layout_extra_media(self):
        self._layout_extra_media = []
        self._refresh_layout_extra_label()
        self._trigger_auto_save()

    def _load_layout_plan(self, segment_data):
        plan = segment_data.get('layout_plan') or {}
        layout = normalize_layout(plan.get('layout'))
        auto_label = "Automatica (segun el guion)"
        if plan and not plan.get('locked'):
            now = LAYOUT_LABELS.get(layout, 'pantalla completa')
            if layout == 'blender_3d' and plan.get('environment'):
                now += f" - {BLENDER_ENVIRONMENTS.get(plan['environment'], plan['environment'])}"
            auto_label = f"Automatica (ahora: {now})"
        self.layout_combo.setItemText(0, auto_label)
        index = self.layout_combo.findData(layout) if plan.get('locked') else 0
        self.layout_combo.setCurrentIndex(index if index >= 0 else 0)
        env_index = self.layout_env_combo.findData(plan.get('environment') or 'auto')
        self.layout_env_combo.setCurrentIndex(env_index if env_index >= 0 else 0)
        self.layout_env_combo.setEnabled(bool(plan.get('locked')) and layout == 'blender_3d')
        self.layout_tag_edit.setText(str(plan.get('tag') or ''))
        self.layout_tag_edit.setEnabled(bool(plan.get('locked')))
        self._layout_extra_media = [str(p) for p in (plan.get('extra_media') or []) if p]
        self._refresh_layout_extra_label()

    def _cinematic_control_changed(self, *_args):
        if self.current_segment and not self.cinematic_lock_check.isChecked():
            self.cinematic_lock_check.blockSignals(True)
            self.cinematic_lock_check.setChecked(True)
            self.cinematic_lock_check.blockSignals(False)
        self._trigger_auto_save()

    # --- Texto de gancho (video_opening): solo en la escena 1 -------------------------
    @staticmethod
    def _is_opening_segment(segment_data):
        """La escena 1: la que trae el gancho, o la que arranca en 0 s (proyectos viejos sin el)."""
        if not isinstance(segment_data, dict) or segment_data.get('cover_frame'):
            return False
        if 'hook_overlay' in segment_data:
            return True
        try:
            return float(segment_data.get('start', 0) or 0) <= 0.05
        except (TypeError, ValueError):
            return False

    def _hook_snapshot(self):
        if not getattr(self, 'hook_group', None) or not self.hook_group.isVisible():
            return None
        text = self.hook_text_edit.text().strip().upper()
        return {'enabled': bool(self.hook_enabled_check.isChecked() and text), 'text': text,
                'duration': round(float(self.hook_duration_spin.value()), 2)}

    def _hook_changed(self, snap_hook):
        if snap_hook is None:
            return False
        cur = self.current_segment.get('hook_overlay') or {}
        return (bool(cur.get('enabled', False)) != snap_hook['enabled']
                or str(cur.get('text') or '').strip().upper() != snap_hook['text']
                or abs(float(cur.get('duration') or 0) - snap_hook['duration']) > 0.001)

    def _has_unsaved_changes(self):
        """Determina si hay diferencias reales entre UI y current_segment."""
        if not self.current_segment:
            return False

        snap = self._snapshot_editor_values()
        current_start = float(self.current_segment.get('start', 0.0) or 0.0)
        current_end = float(self.current_segment.get('end', 0.0) or 0.0)

        if abs(current_start - snap['start']) > 0.0001:
            return True
        if abs(current_end - snap['end']) > 0.0001:
            return True
        if str(self.current_segment.get('text', '')) != snap['text']:
            return True
        if str(self.current_segment.get('visual_prompt', '')) != snap['visual_prompt']:
            return True
        if str(self.current_segment.get('motion_prompt', '') or '') != snap['motion_prompt']:
            return True
        if str(self.current_segment.get('sfx_tag', 'none') or 'none') != snap['sfx_tag']:
            return True
        if str(self.current_segment.get('overlay_tag', 'none') or 'none') != snap['overlay_tag']:
            return True
        if str(self.current_segment.get('assigned_filename', '') or '') != snap['assigned_filename']:
            return True
        if (self.current_segment.get('cinematic_plan') or None) != snap['cinematic_plan']:
            return True
        if (self.current_segment.get('layout_plan') or None) != snap['layout_plan']:
            return True
        if self._hook_changed(snap['hook_overlay']):
            return True

        return False
    
    def setup_ui(self):
        """Configura la interfaz del editor"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header
        header = QLabel("Editor de segmento")
        header.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1f2831;")
        layout.addWidget(header)
        
        # Scroll area para el contenido
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(15)
        
        # Tiempos
        times_group = QGroupBox("Tiempos")
        times_layout = QHBoxLayout(times_group)
        
        times_layout.addWidget(QLabel("Inicio:"))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0, 3600)
        self.start_spin.setDecimals(2)
        self.start_spin.setSuffix(" s")
        self.start_spin.valueChanged.connect(self._trigger_auto_save)
        times_layout.addWidget(self.start_spin)

        times_layout.addWidget(QLabel("Fin:"))
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0, 3600)
        self.end_spin.setDecimals(2)
        self.end_spin.setSuffix(" s")
        self.end_spin.valueChanged.connect(self._trigger_auto_save)
        times_layout.addWidget(self.end_spin)
        
        content_layout.addWidget(times_group)
        
        # Texto de narraciÃ³n
        text_group = QGroupBox("Texto de narracion")
        text_layout = QVBoxLayout(text_group)
        
        self.text_edit = QTextEdit()
        self.text_edit.setMinimumHeight(100)
        self.text_edit.setPlaceholderText("Escribe el texto que se narrarÃ¡ en este segmento...")
        self.text_edit.textChanged.connect(self._trigger_auto_save)
        text_layout.addWidget(self.text_edit)
        
        content_layout.addWidget(text_group)

        # Texto de gancho (video_opening): arriba, grande, encima de la escena 1 desde el
        # cuadro 0. Reemplaza a la placa quieta de 0.7 s. Solo se muestra en la escena 1.
        self.hook_group = QGroupBox("Texto de gancho (primeros segundos)")
        hook_layout = QVBoxLayout(self.hook_group)
        hook_row = QHBoxLayout()
        self.hook_enabled_check = QCheckBox("Mostrar")
        self.hook_enabled_check.stateChanged.connect(self._trigger_auto_save)
        hook_row.addWidget(self.hook_enabled_check)
        self.hook_text_edit = QLineEdit()
        self.hook_text_edit.setMaxLength(24)
        self.hook_text_edit.setPlaceholderText("Ej: 50,000 TROOPS  (1-3 palabras; la cifra primero)")
        self.hook_text_edit.textChanged.connect(self._trigger_auto_save)
        hook_row.addWidget(self.hook_text_edit, 1)
        hook_row.addWidget(QLabel("Dura:"))
        self.hook_duration_spin = QDoubleSpinBox()
        self.hook_duration_spin.setRange(0.5, 4.0)
        self.hook_duration_spin.setSingleStep(0.1)
        self.hook_duration_spin.setDecimals(1)
        self.hook_duration_spin.setSuffix(" s")
        self.hook_duration_spin.setValue(1.8)
        self.hook_duration_spin.valueChanged.connect(self._trigger_auto_save)
        hook_row.addWidget(self.hook_duration_spin)
        hook_layout.addLayout(hook_row)
        hook_info = QLabel("Va arriba, grande y con contorno, encima de la escena en movimiento, "
                           "con la voz desde el cuadro 0. Sale de la cifra de las primeras frases del guion.")
        hook_info.setWordWrap(True)
        hook_info.setStyleSheet("color: #6f7c89; font-size: 8pt;")
        hook_layout.addWidget(hook_info)
        self.hook_group.setVisible(False)
        content_layout.addWidget(self.hook_group)

        # Prompt visual
        visual_group = QGroupBox("Prompt visual (imagen)")
        visual_layout = QVBoxLayout(visual_group)

        self.visual_edit = QTextEdit()
        self.visual_edit.setMinimumHeight(80)
        self.visual_edit.setPlaceholderText("Describe la escena visual (en inglés)...")
        self.visual_edit.textChanged.connect(self._trigger_auto_save)
        visual_layout.addWidget(self.visual_edit)

        content_layout.addWidget(visual_group)

        # Motion prompt (I2V)
        motion_group = QGroupBox("Motion Prompt (video I2V)")
        motion_layout = QVBoxLayout(motion_group)

        self.motion_edit = QTextEdit()
        self.motion_edit.setMinimumHeight(60)
        self.motion_edit.setMaximumHeight(80)
        self.motion_edit.setPlaceholderText(
            "Movimiento de cámara para FAL.AI I2V (opcional, en inglés).\n"
            "Ej: slow dramatic zoom, dust particles, cinematic pan"
        )
        self.motion_edit.textChanged.connect(self._trigger_auto_save)
        motion_layout.addWidget(self.motion_edit)

        motion_hint = QLabel("Si está vacío, se usa el prompt visual como fallback.")
        motion_hint.setStyleSheet("color: #6f7c89; font-size: 8pt;")
        motion_layout.addWidget(motion_hint)

        content_layout.addWidget(motion_group)

        cinematic_group = QGroupBox("Direccion cinematografica")
        cinematic_layout = QVBoxLayout(cinematic_group)
        cinematic_row = QHBoxLayout()

        self.cinematic_camera_combo = QComboBox()
        for label, value in (
            ("Push con profundidad", "depth_push"),
            ("Zoom de impacto", "crash_zoom"),
            ("Descenso cartografico", "map_dive"),
            ("Revelado macro", "macro_reveal"),
            ("Revelado lateral", "lateral_reveal"),
            ("Deriva lenta", "slow_drift"),
            ("Paneo izquierda", "drift_left"),
            ("Paneo derecha", "drift_right"),
            ("Retirada", "pull_back"),
        ):
            self.cinematic_camera_combo.addItem(label, value)
        cinematic_row.addWidget(QLabel("Camara:"))
        cinematic_row.addWidget(self.cinematic_camera_combo)

        self.cinematic_atmosphere_combo = QComboBox()
        for label, value in (
            ("Sin atmosfera", "none"),
            ("Grano fino", "fine_grain"),
            ("Polvo", "dust"),
            ("Niebla", "mist"),
            ("Brasas", "embers"),
        ):
            self.cinematic_atmosphere_combo.addItem(label, value)
        cinematic_row.addWidget(QLabel("Atmosfera:"))
        cinematic_row.addWidget(self.cinematic_atmosphere_combo)
        cinematic_layout.addLayout(cinematic_row)

        cinematic_row_2 = QHBoxLayout()
        self.cinematic_lighting_combo = QComboBox()
        for label, value in (
            ("Sin pulso", "none"),
            ("Pulso suave", "soft_pulse"),
            ("Pulso de revelado", "reveal_pulse"),
            ("Parpadeo de fuego", "fire_flicker"),
        ):
            self.cinematic_lighting_combo.addItem(label, value)
        cinematic_row_2.addWidget(QLabel("Luz:"))
        cinematic_row_2.addWidget(self.cinematic_lighting_combo)

        self.cinematic_lens_combo = QComboBox()
        for label, value in (
            ("Limpia", "clean"),
            ("Vineta", "cinematic_vignette"),
            ("Enfoque dramatico", "focus_reveal"),
            ("Respiracion de lente", "lens_breathing"),
        ):
            self.cinematic_lens_combo.addItem(label, value)
        cinematic_row_2.addWidget(QLabel("Lente:"))
        cinematic_row_2.addWidget(self.cinematic_lens_combo)
        cinematic_layout.addLayout(cinematic_row_2)

        cinematic_row_3 = QHBoxLayout()
        self.cinematic_intensity_spin = QDoubleSpinBox()
        self.cinematic_intensity_spin.setRange(0.0, 1.0)
        self.cinematic_intensity_spin.setSingleStep(0.05)
        self.cinematic_intensity_spin.setDecimals(2)
        self.cinematic_intensity_spin.setValue(0.65)
        cinematic_row_3.addWidget(QLabel("Intensidad:"))
        cinematic_row_3.addWidget(self.cinematic_intensity_spin)

        self.cinematic_lock_check = QCheckBox("Conservar direccion manual")
        self.cinematic_lock_check.setToolTip(
            "Impide que el director automatico reemplace estos valores al exportar."
        )
        cinematic_row_3.addWidget(self.cinematic_lock_check)
        cinematic_row_3.addStretch()
        cinematic_layout.addLayout(cinematic_row_3)
        for combo in (
            self.cinematic_camera_combo,
            self.cinematic_atmosphere_combo,
            self.cinematic_lighting_combo,
            self.cinematic_lens_combo,
        ):
            combo.currentIndexChanged.connect(self._cinematic_control_changed)
        self.cinematic_intensity_spin.valueChanged.connect(self._cinematic_control_changed)
        self.cinematic_lock_check.stateChanged.connect(self._trigger_auto_save)
        content_layout.addWidget(cinematic_group)

        # Composicion de la escena (pipeline/segment_layouts).
        layout_group = QGroupBox("Composicion de la escena")
        layout_box = QVBoxLayout(layout_group)
        layout_row = QHBoxLayout()
        self.layout_combo = QComboBox()
        self.layout_combo.addItem("Automatica (segun el guion)", "auto")
        for value, label in LAYOUT_LABELS.items():
            self.layout_combo.addItem(label, value)
        layout_row.addWidget(QLabel("Tipo:"))
        layout_row.addWidget(self.layout_combo, 1)
        layout_box.addLayout(layout_row)

        env_row = QHBoxLayout()
        self.layout_env_combo = QComboBox()
        for value, label in BLENDER_ENVIRONMENTS.items():
            self.layout_env_combo.addItem(label, value)
        self.layout_env_combo.setToolTip("Ambiente de la toma 3D de esta escena (solo con 'Toma 3D').")
        env_row.addWidget(QLabel("Ambiente 3D:"))
        env_row.addWidget(self.layout_env_combo, 1)
        layout_box.addLayout(env_row)

        tag_row = QHBoxLayout()
        self.layout_tag_edit = QLineEdit()
        self.layout_tag_edit.setMaxLength(40)
        self.layout_tag_edit.setPlaceholderText("Nombre del retrato flotante o titular del periodico (opcional)")
        tag_row.addWidget(QLabel("Rotulo / titular:"))
        tag_row.addWidget(self.layout_tag_edit, 1)
        layout_box.addLayout(tag_row)

        extra_row = QHBoxLayout()
        self._layout_extra_media = []
        self.layout_extra_label = QLabel()
        self.layout_extra_label.setStyleSheet("color: #334155; font-size: 9pt;")
        self.btn_layout_extra = QPushButton("Imagen extra...")
        self.btn_layout_extra.setToolTip(
            "Imagen para el segundo panel (dividida, reveal, retrato, triptico).\n"
            "Sin imagen extra se usan las escenas vecinas o un detalle de esta misma."
        )
        self.btn_layout_extra_clear = QPushButton("Quitar")
        extra_row.addWidget(self.layout_extra_label, 1)
        extra_row.addWidget(self.btn_layout_extra)
        extra_row.addWidget(self.btn_layout_extra_clear)
        layout_box.addLayout(extra_row)

        layout_info = QLabel("Automatica: la elige el guion segun el Dinamismo del Studio. "
                             "Si elegis un tipo, queda fijo para esta escena.")
        layout_info.setWordWrap(True)
        layout_info.setStyleSheet("color: #6f7c89; font-size: 8pt;")
        layout_box.addWidget(layout_info)

        self.layout_combo.currentIndexChanged.connect(self._layout_choice_changed)
        self.layout_env_combo.currentIndexChanged.connect(self._trigger_auto_save)
        self.layout_tag_edit.textChanged.connect(self._trigger_auto_save)
        self.btn_layout_extra.clicked.connect(self._choose_layout_extra_media)
        self.btn_layout_extra_clear.clicked.connect(self._clear_layout_extra_media)
        self._refresh_layout_extra_label()
        content_layout.addWidget(layout_group)

        # SFX
        sfx_group = QGroupBox("Efecto de sonido")
        sfx_layout = QVBoxLayout(sfx_group)
        
        self.sfx_edit = QLineEdit()
        self.sfx_edit.setPlaceholderText("Palabra clave para SFX (ej: thunder, footsteps) o 'none'")
        self.sfx_edit.textChanged.connect(self._trigger_auto_save)
        sfx_layout.addWidget(self.sfx_edit)
        
        content_layout.addWidget(sfx_group)
        
        # Overlay
        overlay_group = QGroupBox("Overlay/GIF")
        overlay_layout = QVBoxLayout(overlay_group)
        
        self.overlay_edit = QLineEdit()
        self.overlay_edit.setPlaceholderText("Palabra clave para overlay (ej: explosion, sparkles) o 'none'")
        self.overlay_edit.textChanged.connect(self._trigger_auto_save)
        overlay_layout.addWidget(self.overlay_edit)
        
        content_layout.addWidget(overlay_group)
        
        # Filename
        filename_group = QGroupBox("Nombre de archivo")
        filename_layout = QVBoxLayout(filename_group)
        
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("segment_001")
        self.filename_edit.textChanged.connect(self._trigger_auto_save)
        filename_layout.addWidget(self.filename_edit)
        
        info_label = QLabel("Este sera el nombre del archivo visual generado (sin extension).")
        info_label.setStyleSheet("color: #6f7c89; font-size: 8pt;")
        filename_layout.addWidget(info_label)
        
        content_layout.addWidget(filename_group)
        
        # Botones para buscar imÃ¡genes reales
        images_search_group = QGroupBox("Imagenes y video")
        images_search_layout = QVBoxLayout(images_search_group)
        
        # BotÃ³n para buscar imagen en Wikimedia
        self.btn_wikimedia_search = QPushButton("Buscar en Wikimedia")
        self.btn_wikimedia_search.setToolTip("Buscar y seleccionar una imagen de Wikimedia Commons para este segmento")
        self.btn_wikimedia_search.clicked.connect(self.on_wikimedia_search_clicked)
        images_search_layout.addWidget(self.btn_wikimedia_search)
        
        # BotÃ³n para insertar imagen local
        self.btn_local_image = QPushButton("Insertar imagen local")
        self.btn_local_image.setToolTip("Seleccionar una imagen desde tu PC")
        self.btn_local_image.clicked.connect(self.on_local_image_clicked)
        images_search_layout.addWidget(self.btn_local_image)

        self.btn_paste_clipboard_image = QPushButton("Pegar imagen del portapapeles")
        self.btn_paste_clipboard_image.setToolTip("Pega una imagen copiada desde el portapapeles en este segmento")
        self.btn_paste_clipboard_image.clicked.connect(self.on_clipboard_image_clicked)
        images_search_layout.addWidget(self.btn_paste_clipboard_image)

        # Checkbox para indicar que la imagen proviene de Gemini (quitar watermark)
        self.chk_gemini_strip = QCheckBox("Imagen de Gemini (quitar marca de agua)")
        self.chk_gemini_strip.setToolTip(
            "Si la imagen proviene de Gemini/Imagen, al insertarla se eliminara\n"
            "automaticamente el sparkle/watermark en la esquina inferior derecha."
        )
        self.chk_gemini_strip.setStyleSheet("color: #334155; font-size: 9pt;")
        images_search_layout.addWidget(self.chk_gemini_strip)
        
        # BotÃ³n para buscar imagen en Openverse Image Search
        self.btn_openverse_search = QPushButton("Buscar en Openverse")
        self.btn_openverse_search.setToolTip("Buscar y seleccionar una imagen real para este segmento\nUsa Openverse gratis por defecto (sin API key)")
        self.btn_openverse_search.clicked.connect(self.on_openverse_search_clicked)
        images_search_layout.addWidget(self.btn_openverse_search)
        
        # BotÃ³n para buscar video en Pexels
        self.btn_pexels_video_search = QPushButton("Buscar video en Pexels")
        self.btn_pexels_video_search.setToolTip("Buscar y seleccionar un video de Pexels para este segmento\nEl video se ajustarÃ¡ automÃ¡ticamente a la duraciÃ³n del segmento\nRequiere PEXELS_API_KEY en .env")
        self.btn_pexels_video_search.clicked.connect(self.on_pexels_video_search_clicked)
        images_search_layout.addWidget(self.btn_pexels_video_search)

        # BotÃ³n para insertar video local
        self.btn_local_video = QPushButton("Insertar video local")
        self.btn_local_video.setToolTip("Seleccionar un video desde tu PC")
        self.btn_local_video.clicked.connect(self.on_local_video_clicked)
        images_search_layout.addWidget(self.btn_local_video)
        
        info_images = QLabel("Usa fuentes externas para asignar imagenes o video al segmento.")
        info_images.setStyleSheet("color: #6f7c89; font-size: 8pt;")
        images_search_layout.addWidget(info_images)
        
        content_layout.addWidget(images_search_group)
        
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Iniciar vacÃ­o
        self.clear()
    
    def _trigger_auto_save(self):
        """Activa el auto-guardado automÃ¡tico despuÃ©s de un breve delay (debounce)"""
        if self._save_in_progress or not self.current_segment:
            return

        # Cancelar timer anterior si existe
        if self._auto_save_timer:
            self._auto_save_timer.stop()

        # Crear nuevo timer con delay de 1 segundo (debounce)
        self._auto_save_timer = QTimer()
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.timeout.connect(self.save_changes)
        self._auto_save_timer.start(1000)  # 1 segundo de delay

    def load_segment(self, segment_data):
        """Carga un segmento para editar"""
        print(f"[SegmentEditor] load_segment llamado con segmento #{segment_data.get('start', 0)}")

        # Cancelar auto-guardado pendiente del segmento previo antes de cambiar contexto.
        if self._auto_save_timer:
            self._auto_save_timer.stop()

        self.current_segment = segment_data.copy()

        # Bloquear seÃ±ales temporalmente para evitar auto-guardado al cargar
        self.start_spin.blockSignals(True)
        self.end_spin.blockSignals(True)
        self.text_edit.blockSignals(True)
        self.visual_edit.blockSignals(True)
        self.motion_edit.blockSignals(True)
        self.sfx_edit.blockSignals(True)
        self.overlay_edit.blockSignals(True)
        self.filename_edit.blockSignals(True)
        cinematic_widgets = (
            self.cinematic_camera_combo, self.cinematic_atmosphere_combo,
            self.cinematic_lighting_combo, self.cinematic_lens_combo,
            self.cinematic_intensity_spin, self.cinematic_lock_check,
            self.layout_combo, self.layout_tag_edit, self.layout_env_combo,
        )
        for widget in cinematic_widgets:
            widget.blockSignals(True)

        self._load_layout_plan(segment_data)
        self.start_spin.setValue(segment_data.get('start', 0))
        self.end_spin.setValue(segment_data.get('end', 0))
        self.text_edit.setPlainText(segment_data.get('text', ''))
        self.visual_edit.setPlainText(segment_data.get('visual_prompt', ''))
        self.motion_edit.setPlainText(segment_data.get('motion_prompt', '') or '')
        self.sfx_edit.setText(segment_data.get('sfx_tag', 'none'))
        self.overlay_edit.setText(segment_data.get('overlay_tag', 'none'))
        self.filename_edit.setText(segment_data.get('assigned_filename', ''))
        plan = segment_data.get('cinematic_plan') or {}
        for combo, key, fallback in (
            (self.cinematic_camera_combo, 'camera', 'depth_push'),
            (self.cinematic_atmosphere_combo, 'atmosphere', 'none'),
            (self.cinematic_lighting_combo, 'lighting', 'none'),
            (self.cinematic_lens_combo, 'lens', 'clean'),
        ):
            index = combo.findData(plan.get(key, fallback))
            combo.setCurrentIndex(index if index >= 0 else 0)
        self.cinematic_intensity_spin.setValue(float(plan.get('intensity', 0.65)))
        self.cinematic_lock_check.setChecked(bool(plan.get('locked', False)))

        # Texto de gancho: visible solo en la escena 1.
        es_arranque = self._is_opening_segment(segment_data)
        self.hook_group.setVisible(es_arranque)
        hook = segment_data.get('hook_overlay') or {}
        for w in (self.hook_enabled_check, self.hook_text_edit, self.hook_duration_spin):
            w.blockSignals(True)
        self.hook_enabled_check.setChecked(bool(hook.get('enabled', False)))
        self.hook_text_edit.setText(str(hook.get('text') or ''))
        self.hook_duration_spin.setValue(float(hook.get('duration') or 1.8))
        for w in (self.hook_enabled_check, self.hook_text_edit, self.hook_duration_spin):
            w.blockSignals(False)

        # Desbloquear señales
        self.start_spin.blockSignals(False)
        self.end_spin.blockSignals(False)
        self.text_edit.blockSignals(False)
        self.visual_edit.blockSignals(False)
        self.motion_edit.blockSignals(False)
        self.sfx_edit.blockSignals(False)
        self.overlay_edit.blockSignals(False)
        self.filename_edit.blockSignals(False)
        for widget in cinematic_widgets:
            widget.blockSignals(False)

        # IMPORTANTE: Habilitar el editor y todos sus controles
        self.setEnabled(True)
        self.start_spin.setEnabled(True)
        self.end_spin.setEnabled(True)
        self.text_edit.setEnabled(True)
        self.visual_edit.setEnabled(True)
        self.motion_edit.setEnabled(True)
        self.sfx_edit.setEnabled(True)
        self.overlay_edit.setEnabled(True)
        self.filename_edit.setEnabled(True)
        
        # Habilitar botones de bÃºsqueda
        if hasattr(self, 'btn_wikimedia_search'):
            self.btn_wikimedia_search.setEnabled(True)
        if hasattr(self, 'btn_openverse_search'):
            self.btn_openverse_search.setEnabled(True)
        if hasattr(self, 'btn_pexels_video_search'):
            self.btn_pexels_video_search.setEnabled(True)
        if hasattr(self, 'btn_local_image'):
            self.btn_local_image.setEnabled(True)
        if hasattr(self, 'btn_paste_clipboard_image'):
            self.btn_paste_clipboard_image.setEnabled(True)
        if hasattr(self, 'btn_local_video'):
            self.btn_local_video.setEnabled(True)
        
        # Asegurar que el widget sea visible
        self.setVisible(True)
        self.show()
        
        print(f"[SegmentEditor] Editor habilitado y visible. Segmento cargado: {segment_data.get('text', '')[:50]}...")
    
    def save_changes(self):
        """Guarda los cambios del segmento automÃ¡ticamente (sin confirmaciÃ³n)"""
        if not self.current_segment or self._save_in_progress:
            return

        # Evitar emisiones redundantes que generan bucles de sincronización.
        if not self._has_unsaved_changes():
            return

        self._save_in_progress = True
        try:
            snap = self._snapshot_editor_values()
            self.current_segment['start'] = snap['start']
            self.current_segment['end'] = snap['end']
            self.current_segment['text'] = snap['text']
            self.current_segment['visual_prompt'] = snap['visual_prompt']
            self.current_segment['motion_prompt'] = snap['motion_prompt']
            self.current_segment['sfx_tag'] = snap['sfx_tag']
            self.current_segment['overlay_tag'] = snap['overlay_tag']
            self.current_segment['assigned_filename'] = snap['assigned_filename']
            if snap['cinematic_plan'] is not None:
                self.current_segment['cinematic_plan'] = snap['cinematic_plan']
            if snap['layout_plan'] is not None:
                self.current_segment['layout_plan'] = snap['layout_plan']
            if snap['hook_overlay'] is not None:
                previo = self.current_segment.get('hook_overlay') or {}
                self.current_segment['hook_overlay'] = dict(previo, **snap['hook_overlay'],
                                                            edited_in_timeline=True)

            # IMPORTANTE: Preservar campos de video/imagen que no se editan aquÃ­
            # Estos campos se mantienen automÃ¡ticamente porque self.current_segment es una referencia
            # pero hacemos una copia explÃ­cita para asegurar que todos los campos se preserven
            updated_segment = self.current_segment.copy()

            # Emitir seÃ±al con todos los campos preservados
            self.saved.emit(updated_segment)
        finally:
            self._save_in_progress = False

        # No mostrar mensaje de confirmaciÃ³n - el guardado es automÃ¡tico y silencioso
    
    def clear(self):
        """Limpia el editor"""
        self.current_segment = None
        
        # Bloquear señales para evitar guardados durante la limpieza
        self.start_spin.blockSignals(True)
        self.end_spin.blockSignals(True)
        self.text_edit.blockSignals(True)
        self.visual_edit.blockSignals(True)
        self.motion_edit.blockSignals(True)
        self.sfx_edit.blockSignals(True)
        self.overlay_edit.blockSignals(True)
        self.filename_edit.blockSignals(True)

        self.start_spin.setValue(0)
        self.end_spin.setValue(0)
        self.text_edit.clear()
        self.visual_edit.clear()
        self.motion_edit.clear()
        self.sfx_edit.clear()
        self.overlay_edit.clear()
        self.filename_edit.clear()
        self.hook_group.setVisible(False)
        for widget in (self.layout_combo, self.layout_tag_edit, self.layout_env_combo):
            widget.blockSignals(True)
        self._load_layout_plan({})
        for widget in (self.layout_combo, self.layout_tag_edit, self.layout_env_combo):
            widget.blockSignals(False)

        # Desbloquear señales
        self.start_spin.blockSignals(False)
        self.end_spin.blockSignals(False)
        self.text_edit.blockSignals(False)
        self.visual_edit.blockSignals(False)
        self.motion_edit.blockSignals(False)
        self.sfx_edit.blockSignals(False)
        self.overlay_edit.blockSignals(False)
        self.filename_edit.blockSignals(False)

        # IMPORTANTE: Deshabilitar controles individuales, pero mantener el widget visible
        self.start_spin.setEnabled(False)
        self.end_spin.setEnabled(False)
        self.text_edit.setEnabled(False)
        self.visual_edit.setEnabled(False)
        self.motion_edit.setEnabled(False)
        self.sfx_edit.setEnabled(False)
        self.overlay_edit.setEnabled(False)
        self.filename_edit.setEnabled(False)
        
        # Deshabilitar botones de búsqueda
        if hasattr(self, 'btn_wikimedia_search'):
            self.btn_wikimedia_search.setEnabled(False)
        if hasattr(self, 'btn_openverse_search'):
            self.btn_openverse_search.setEnabled(False)
        if hasattr(self, 'btn_pexels_video_search'):
            self.btn_pexels_video_search.setEnabled(False)
        if hasattr(self, 'btn_local_image'):
            self.btn_local_image.setEnabled(False)
        if hasattr(self, 'btn_paste_clipboard_image'):
            self.btn_paste_clipboard_image.setEnabled(False)
        if hasattr(self, 'btn_local_video'):
            self.btn_local_video.setEnabled(False)

        # Mantener el panel activo para permitir lectura/edicion cuando se seleccione.
        self.setEnabled(True)
        self.setVisible(True)  # Asegurar que el widget sea visible
    
    def on_wikimedia_search_clicked(self):
        """Maneja el click en el botÃ³n de bÃºsqueda de Wikimedia"""
        if not self.current_segment:
            QMessageBox.warning(
                self,
                "Sin Segmento",
                "Primero selecciona un segmento del timeline para buscar una imagen."
            )
            return
        
        # Emitir seÃ±al con los datos del segmento actual
        self.wikimedia_search_requested.emit(self.current_segment)
    
    def on_openverse_search_clicked(self):
        """Maneja el click en el boton de busqueda de Openverse."""
        if not self.current_segment:
            QMessageBox.warning(
                self,
                "Sin Segmento",
                "Primero selecciona un segmento del timeline para buscar una imagen."
            )
            return
        
        # Emitir seÃ±al con los datos del segmento actual
        self.openverse_images_search_requested.emit(self.current_segment)
    
    def on_pexels_video_search_clicked(self):
        """Maneja el click en el botÃ³n de bÃºsqueda de videos de Pexels"""
        if not self.current_segment:
            QMessageBox.warning(
                self,
                "Sin Segmento",
                "Primero selecciona un segmento del timeline para buscar un video."
            )
            return
        
        # Emitir seÃ±al con los datos del segmento actual
        self.pexels_video_search_requested.emit(self.current_segment)
    
    def on_local_image_clicked(self):
        """Maneja el click en el botÃ³n de insertar imagen local"""
        if not self.current_segment:
            QMessageBox.warning(
                self,
                "Sin Segmento",
                "Primero selecciona un segmento del timeline para insertar una imagen."
            )
            return
        
        # Emitir seÃ±al con los datos del segmento actual
        self.local_image_requested.emit(self.current_segment)

    def on_clipboard_image_clicked(self):
        """Maneja el click en el boton de pegar imagen desde el portapapeles."""
        if not self.current_segment:
            QMessageBox.warning(
                self,
                "Sin Segmento",
                "Primero selecciona un segmento del timeline para pegar una imagen."
            )
            return

        self.clipboard_image_requested.emit(self.current_segment)

    def on_local_video_clicked(self):
        """Maneja el click en el botÃ³n de insertar video local"""
        if not self.current_segment:
            QMessageBox.warning(
                self,
                "Sin Segmento",
                "Primero selecciona un segmento del timeline para insertar un video."
            )
            return
        
        # Emitir seÃ±al con los datos del segmento actual
        self.local_video_requested.emit(self.current_segment)





