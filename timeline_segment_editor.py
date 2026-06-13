# timeline_segment_editor.py
"""
Editor detallado para un segmento individual del timeline.
ExtraÃ­do de timeline_editor_widget.py para mejorar la organizaciÃ³n del cÃ³digo.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QScrollArea, QGroupBox, QMessageBox, QLineEdit, QDoubleSpinBox,
    QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer


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
            'assigned_filename': self.filename_edit.text().strip()
        }

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

        self.start_spin.setValue(segment_data.get('start', 0))
        self.end_spin.setValue(segment_data.get('end', 0))
        self.text_edit.setPlainText(segment_data.get('text', ''))
        self.visual_edit.setPlainText(segment_data.get('visual_prompt', ''))
        self.motion_edit.setPlainText(segment_data.get('motion_prompt', '') or '')
        self.sfx_edit.setText(segment_data.get('sfx_tag', 'none'))
        self.overlay_edit.setText(segment_data.get('overlay_tag', 'none'))
        self.filename_edit.setText(segment_data.get('assigned_filename', ''))

        # Desbloquear señales
        self.start_spin.blockSignals(False)
        self.end_spin.blockSignals(False)
        self.text_edit.blockSignals(False)
        self.visual_edit.blockSignals(False)
        self.motion_edit.blockSignals(False)
        self.sfx_edit.blockSignals(False)
        self.overlay_edit.blockSignals(False)
        self.filename_edit.blockSignals(False)

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





