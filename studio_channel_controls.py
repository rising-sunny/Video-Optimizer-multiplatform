"""Channel and microdocumentary controls for Auto Video Studio."""
import json
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                            QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QTabWidget,
                            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)

from channel_profiles import CHANNELS, DEFAULT_CHANNEL, active_channel, select_channel


def project_channel_config(tab):
    combo = getattr(tab, 'channel_combo', None)
    strategy = getattr(tab, 'format_strategy_combo', None)
    arche = getattr(tab, 'archetype_combo', None)
    return {"channel_profile": getattr(tab, "_editorial_channel", active_channel()),
            "upload_channel": combo.currentData() if combo else DEFAULT_CHANNEL,
            "format_strategy": strategy.currentData() if strategy else "traditional",
            "format_archetype": (arche.currentData() if arche else None) or "auto"}


def populate_archetype_combo(tab):
    """'Auto' + los angulos del perfil editorial activo (Bible.format_archetypes)."""
    combo = getattr(tab, 'archetype_combo', None)
    if combo is None:
        return
    from channel_strategy import get_format_archetypes
    current = combo.currentData() or "auto"
    combo.blockSignals(True)
    combo.clear()
    combo.addItem('Ángulo: auto (según datos)', 'auto')
    for a in get_format_archetypes():
        combo.addItem(a.get('label_es') or a.get('name') or a['id'], a['id'])
    idx = combo.findData(current)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    combo.blockSignals(False)


def resolve_archetype_for_topic(tab, topic, category=""):
    """Lo que el guion va a usar: el elegido, o el 'auto' resuelto por datos + tema."""
    from channel_strategy import pick_archetype_auto, archetype_label
    combo = getattr(tab, 'archetype_combo', None)
    chosen = (combo.currentData() if combo else None) or "auto"
    if chosen == "auto":
        chosen = pick_archetype_auto(topic, category)
        how = "auto"
    else:
        how = "elegido"
    if chosen and hasattr(tab, 'log'):
        tab.log(f"Ángulo narrativo ({how}): {archetype_label(chosen)}")
    return chosen or ""


def set_editorial_channel(tab, key, reason=""):
    """El perfil con el que se ESCRIBE el guion (categorias, ganchos, titulos, tono).

    Distinto del destino de publicacion: un proyecto ya escrito conserva el
    perfil con el que se escribio aunque se publique en otro canal. Repuebla el
    combo de categorias, que es lo unico visible de este perfil en la GUI.
    """
    if key not in CHANNELS:
        raise ValueError(f"Unknown channel: {key}")
    changed = getattr(tab, '_editorial_channel', None) != key or active_channel() != key
    tab._editorial_channel = key
    select_channel(key)
    parent = getattr(tab, 'parent_gui', None)
    if parent and hasattr(parent, 'category_combo'):
        from channel_strategy import get_all_category_names
        parent.category_combo.clear()
        parent.category_combo.addItems(get_all_category_names())
    populate_archetype_combo(tab)
    if changed and hasattr(tab, 'log'):
        tab.log(f"Perfil editorial: {CHANNELS[key]['name']}" + (f" ({reason})" if reason else ""))
    return changed


def project_has_script(tab) -> bool:
    memory = getattr(tab, 'last_storyboard_data', None)
    return bool(isinstance(memory, dict) and memory.get('segments')) and bool(getattr(tab, 'current_project_path', None))


def sync_editorial_before_writing(tab, isolated=False):
    """Antes de escribir un guion NUEVO, el perfil editorial es el del canal destino.

    BUG (2026-09-21): `select_channel` es global. Abrir un proyecto viejo de
    Stunning Revelations lo dejaba activo, y cada proyecto NUEVO heredaba su
    perfil en silencio: desde el 8-9 todos los guiones para Stunning Facts of
    History se escribieron con las categorias, ganchos y tono del canal viejo,
    sin ningun control visible que lo mostrara.
    """
    if isolated or not project_has_script(tab):
        key = getattr(tab, '_upload_channel', None) or active_channel()
        return set_editorial_channel(tab, key, "proyecto nuevo: se escribe para el canal destino")
    return False


def restore_channel_config(tab, config):
    if not hasattr(tab, 'channel_combo'):
        return
    key = config.get('channel_profile', DEFAULT_CHANNEL)
    if key not in CHANNELS:
        raise ValueError(f"Unknown saved channel: {key}")
    destination = config.get('upload_channel', key)
    if destination not in CHANNELS:
        raise ValueError(f'Unknown upload channel: {destination}')
    tab._upload_channel = destination
    for combo, value in ((tab.channel_combo, destination), (tab.format_strategy_combo, config.get('format_strategy', 'traditional'))):
        combo.blockSignals(True)
        combo.setCurrentIndex(max(0, combo.findData(value)))
        combo.blockSignals(False)
    set_editorial_channel(tab, key, "perfil guardado en el proyecto")
    arche = getattr(tab, 'archetype_combo', None)
    if arche is not None:
        idx = arche.findData(config.get('format_archetype') or 'auto')
        arche.blockSignals(True)
        arche.setCurrentIndex(idx if idx >= 0 else 0)
        arche.blockSignals(False)
    # Al reabrir un proyecto ya escrito, el angulo activo vuelve a ser el suyo
    # (cover frame y thumbnail lo leen aunque no se regenere el guion).
    try:
        from channel_strategy import set_active_archetype
        saved = config.get('format_archetype')
        set_active_archetype(saved if saved and saved != 'auto' else "")
    except Exception:
        pass


def install_controls(tab, layout):
    row = QHBoxLayout()
    row.addWidget(QLabel('Publicar en YouTube:'))
    tab._editorial_channel = active_channel()
    tab._upload_channel = active_channel()
    tab.channel_combo = QComboBox()
    for key, profile in CHANNELS.items():
        tab.channel_combo.addItem(profile['name'], key)
    tab.channel_combo.setCurrentIndex(tab.channel_combo.findData(active_channel()))
    row.addWidget(tab.channel_combo)
    tab.format_strategy_combo = QComboBox()
    tab.format_strategy_combo.addItem('Flujo habitual', 'traditional')
    tab.format_strategy_combo.addItem('Microdocumental · 16:9 · 4–5 min', 'micro_documentary')
    row.addWidget(tab.format_strategy_combo)
    tab.archetype_combo = QComboBox()
    tab.archetype_combo.setToolTip('Cómo se cuenta el tema. "auto" lo elige por las palabras del tema y lo medido en Rendimiento.')
    populate_archetype_combo(tab)
    tab.archetype_combo.currentIndexChanged.connect(
        lambda _i: hasattr(tab, 'auto_save_project') and tab.auto_save_project('cambio de ángulo'))
    row.addWidget(tab.archetype_combo)
    button = QPushButton('Preparar / abrir piloto…')
    row.addWidget(button)
    tab.btn_performance = QPushButton('Rendimiento')
    tab.btn_performance.setToolTip('Mide YouTube + Facebook (30 dias) y actualiza lo que el guion sabe que funciona')
    tab.btn_performance.clicked.connect(lambda: refresh_performance(tab))
    row.addWidget(tab.btn_performance)
    tab.btn_trends = QPushButton('Tendencias')
    tab.btn_trends.setToolTip('Shorts de historia mas vistos del mes, Wikipedia y efemerides: temas listos con angulo y fecha')
    tab.btn_trends.clicked.connect(lambda: open_trends(tab))
    row.addWidget(tab.btn_trends)
    layout.addLayout(row)

    def change_channel():
        previous = tab._upload_channel
        if hasattr(tab, 'btn_publish') and tab.btn_publish.text() == 'Publicando...':
            tab.channel_combo.blockSignals(True)
            tab.channel_combo.setCurrentIndex(tab.channel_combo.findData(previous))
            tab.channel_combo.blockSignals(False)
            QMessageBox.information(tab, 'Publicación en curso', 'Espera a que termine la publicación para cambiar su destino.')
            return
        key = tab.channel_combo.currentData()
        tab._upload_channel = key
        # Sin guion todavia, el perfil editorial acompana al destino: lo que se
        # va a escribir es para ESE canal. Con guion, se conserva (ver arriba).
        if not project_has_script(tab):
            set_editorial_channel(tab, key, "sigue al destino hasta que haya guion")
        if hasattr(tab, 'auto_save_project'):
            tab.auto_save_project('cambio de canal de publicación')
        tab.log(f"Destino de publicación: {CHANNELS[key]['name']}")

    def change_format():
        if tab.format_strategy_combo.currentData() == 'micro_documentary' and hasattr(tab, 'platform_combo'):
            tab.platform_combo.setCurrentIndex(0)
            tab.duration_slider.setValue(270)
            tab.lang_en.setChecked(True)

    tab.channel_combo.currentIndexChanged.connect(change_channel)
    tab.format_strategy_combo.currentIndexChanged.connect(change_format)
    button.clicked.connect(lambda: open_pilot(tab))


class PilotWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class PilotDialog(QDialog):
    def __init__(self, tab, out, topic, channel):
        super().__init__(tab)
        self.tab, self.out, self.topic, self.channel = tab, Path(out), topic, channel
        self.worker = None
        self.editorial = {}
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self.save_editor_draft)
        self.setWindowTitle(f'Piloto microdocumental — {CHANNELS[channel]["name"]}')
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Revisa fuentes, certeza histórica, título, miniatura y apertura. Puedes editar el JSON antes de aprobar.'))
        tabs = QTabWidget()
        self.review = QTextEdit()
        self.review.setReadOnly(True)
        self.editor = QTextEdit()
        tabs.addTab(self.review, 'Propuesta editorial')
        tabs.addTab(self.editor, 'Editar propuesta (JSON)')
        layout.addWidget(tabs)
        self.editor.textChanged.connect(self.refresh_review)
        self.editor.textChanged.connect(lambda: self.autosave_timer.start(400))
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel('Proveedor de imágenes para ensamblar:'))
        self.provider = QComboBox()
        self.provider.addItem('Manual — usar mis imágenes y videos', 'manual')
        for value in ('flux_dev', 'flux_schnell', 'recraft', 'comfy_schnell', 'comfy_sdxl', 'comfy_dev', 'stability_core', 'stability_ultra', 'auto', 'google_ai'):
            self.provider.addItem(value, value)
        from micro_documentary import resolve_image_provider
        saved_config = {}
        if (self.out / 'project.json').exists():
            saved_config = json.loads((self.out / 'project.json').read_text(encoding='utf-8')).get('config', {})
        studio_provider = getattr(tab, 'image_provider_combo', None)
        chosen_provider = studio_provider.currentText() if studio_provider is not None else saved_config.get('image_provider')
        self.provider.setCurrentIndex(self.provider.findData(resolve_image_provider(chosen_provider)))
        provider_row.addWidget(self.provider)
        provider_row.addStretch()
        layout.addLayout(provider_row)
        self.image_help = QLabel()
        self.image_help.setWordWrap(True)
        layout.addWidget(self.image_help)
        def explain_images():
            self.image_help.setText('Modo manual: crea el guion y pulsa Cargar en Studio para añadir tus imágenes o videos. Ensamblar no genera imágenes y comprueba que estén asignadas.' if self.provider.currentData() == 'manual' else 'El proveedor seleccionado completará las imágenes al ensamblar.')
        self.provider.currentIndexChanged.connect(explain_images)
        explain_images()
        row = QHBoxLayout()
        layout.addLayout(row)
        self.buttons = []
        for label, fn in [('Importar contexto JSON', self.import_editorial), ('Generar propuesta', lambda: self.run_stage(False, False)), ('Aprobar y crear guion', lambda: self.run_stage(True, False)), ('Ensamblar piloto', lambda: self.run_stage(True, True)), ('Cargar en Studio', self.load_studio)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.buttons.append(b)
        path = self.out / 'experiment.json'
        draft_path = self.out / 'editorial_draft.txt'
        if draft_path.exists() and (not path.exists() or draft_path.stat().st_mtime_ns > path.stat().st_mtime_ns):
            self.editor.setPlainText(draft_path.read_text(encoding='utf-8'))
        elif path.exists():
            self.editor.setPlainText(path.read_text(encoding='utf-8'))

    def save_editor_draft(self):
        """Preserve unfinished JSON too, without corrupting the runnable manifest."""
        self.autosave_timer.stop()
        text = self.editor.toPlainText()
        if not text.strip():
            return
        try:
            self.out.mkdir(parents=True, exist_ok=True)
            draft = self.out / 'editorial_draft.txt'
            temporary = draft.with_suffix('.tmp')
            temporary.write_text(text, encoding='utf-8')
            temporary.replace(draft)
            try:
                manifest = json.loads(text)
            except ValueError:
                return
            if isinstance(manifest, dict) and manifest.get('channel') == self.channel and manifest.get('topic') == self.topic:
                from micro_documentary import write_json, validate_packaging, runtime_plan
                try:
                    runtime_plan(manifest['target_runtime_seconds'], manifest['effective_wpm'])
                    if validate_packaging(manifest, manifest['effective_wpm']):
                        return
                except (KeyError, ValueError, TypeError):
                    return
                write_json(self.out / 'experiment.json', manifest)
        except OSError as exc:
            self.tab.log(f'No se pudo autoguardar la propuesta: {exc}')

    def refresh_review(self):
        try:
            data = json.loads(self.editor.toPlainText())
            lines = [f"{data['topic']} — {data['target_runtime_seconds'] / 60:g} min, 16:9", '', 'TÍTULOS']
            lines.extend(('[Elegido] ' if title == data['selected_title'] else '• ') + title for title in data['title_variants'])
            lines.extend(['', 'MINIATURAS'])
            for concept in data['thumbnail_variants']:
                lines.append(('[Elegida] ' if concept == data['selected_thumbnail_concept'] else '• ') + concept['prompt'] + '\nTexto: ' + concept.get('text', ''))
            lines.extend(['', 'GANCHO', data['hook'], '', 'PRIMEROS 30 SEGUNDOS', data['first_30_seconds'], '', 'VISUAL DE APERTURA', data['opening_visual'], '', 'AFIRMACIONES Y FUENTES — requieren revisión'])
            lines.extend(f"• {claim['claim']} [{claim['status']}]\n  {claim['source']}" for claim in data['claims'])
            if data.get('script_word_count'):
                lines.extend(['', f"Guion: {data['script_word_count']} palabras; estimación {data['estimated_runtime_seconds']:.0f}s."])
            lines.extend(['', f"Estado: {data['status']}"])
            self.review.setPlainText('\n'.join(lines))
        except (ValueError, KeyError, TypeError):
            self.review.setPlainText('Genera una propuesta o corrige el JSON editorial para ver la revisión.')

    def import_editorial(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Contexto editorial y fuentes', '', 'JSON (*.json)')
        if filename:
            try:
                self.editorial = json.loads(Path(filename).read_text(encoding='utf-8'))
            except Exception as exc:
                QMessageBox.warning(self, 'JSON inválido', str(exc))

    def run_stage(self, approve, assemble):
        from micro_documentary import build, write_json, validate_packaging
        try:
            self.save_editor_draft()
            if approve:
                manifest = json.loads(self.editor.toPlainText())
                if manifest['channel'] != self.channel or manifest['topic'] != self.topic:
                    raise ValueError('El tema y canal deben coincidir con este piloto.')
                errors = validate_packaging(manifest, manifest['effective_wpm'])
                if errors:
                    raise ValueError('; '.join(errors))
                write_json(self.out / 'experiment.json', manifest)
            seconds = min(330, max(210, self.tab.duration_slider.value()))
            provider = self.provider.currentData()
            archetype = resolve_archetype_for_topic(self.tab, self.topic)
            self.worker = PilotWorker(lambda: build(self.topic, self.out, channel=self.channel, seconds=seconds, editorial=self.editorial, approve=approve, assemble=assemble, image_provider=provider, format_archetype=archetype), self)
            for button in self.buttons:
                button.setEnabled(False)
            self.editor.setReadOnly(True)
            self.worker.result.connect(self.completed)
            self.worker.failed.connect(lambda error: QMessageBox.warning(self, 'Piloto detenido', error))
            self.worker.finished.connect(self.unlock)
            self.worker.start()
        except Exception as exc:
            QMessageBox.warning(self, 'Revisa la propuesta', str(exc))

    def completed(self, result):
        self.editor.setPlainText(json.dumps(result['manifest'], indent=2, ensure_ascii=False))
        self.tab.log(f"Piloto: {result['status']} — {self.out}")
        if result.get('status') == 'assembled' and result.get('video_path'):
            from project_media_paths import normalize_project_path
            path = self.out / 'project.json'
            if normalize_project_path(getattr(self.tab, 'current_project_path', None)) == normalize_project_path(path):
                # Restore the committed render, narration timings and button state
                # together, before another autosave can write the old result back.
                self.tab.load_project_from_path(str(path))

    def unlock(self):
        for button in self.buttons:
            button.setEnabled(True)
        self.editor.setReadOnly(False)

    def load_studio(self):
        self.save_editor_draft()
        path = self.out / 'project.json'
        if path.exists():
            self.tab.load_project_from_path(str(path))
            self.accept()
        else:
            QMessageBox.information(self, 'Falta guion', 'Aprueba la propuesta y crea el guion primero.')

    def reject(self):
        if self.worker and self.worker.isRunning():
            return
        self.save_editor_draft()
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            self.save_editor_draft()
            super().closeEvent(event)


class _PerformanceWorker(QThread):
    """Corre performance_feedback.run() sin congelar la GUI."""
    line = pyqtSignal(str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, days=30, parent=None):
        super().__init__(parent)
        self.days = days

    def run(self):
        try:
            import performance_feedback as pf
            snap = pf.run(days=self.days, log=self.line.emit)
            self.done.emit(snap)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def refresh_performance(tab, days=30):
    """Boton 'Rendimiento': snapshot YT+FB -> daily_shorts/performance_snapshot.json -> prompt."""
    worker = getattr(tab, '_performance_worker', None)
    if worker is not None and worker.isRunning():
        tab.log("Rendimiento: ya se esta midiendo...")
        return
    btn = getattr(tab, 'btn_performance', None)
    if btn is not None:
        btn.setEnabled(False)
        btn.setText('Midiendo…')

    def _done(snap):
        import performance_feedback as pf
        for ln in pf.format_summary(snap).splitlines():
            tab.log(ln)
        tab.log("Rendimiento: el proximo guion ya lee estas conclusiones (bloque WHAT IS WORKING NOW).")
        _restore()

    def _failed(msg):
        tab.log(f"Rendimiento: no se pudo medir ({msg})")
        _restore()

    def _restore():
        if btn is not None:
            btn.setEnabled(True)
            btn.setText('Rendimiento')

    worker = _PerformanceWorker(days=days, parent=tab)
    worker.line.connect(tab.log)
    worker.done.connect(_done)
    worker.failed.connect(_failed)
    tab._performance_worker = worker
    worker.start()


class _TrendsWorker(QThread):
    line = pyqtSignal(str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def run(self):
        try:
            import trend_report
            self.done.emit(trend_report.build_report(log=self.line.emit))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def apply_proposal_to_studio(tab, proposal):
    """Carga tema + categoria + angulo de una propuesta en el formulario del Studio."""
    parent = getattr(tab, 'parent_gui', None)
    topic_widget = getattr(tab, 'topic_input', None) or getattr(parent, 'topic_input', None)
    if topic_widget is not None and hasattr(topic_widget, 'setText'):
        topic_widget.setText(str(proposal.get('topic') or ''))
    cat = str(proposal.get('category') or '')
    combo = getattr(parent, 'category_combo', None) if parent is not None else None
    if cat and combo is not None:
        idx = combo.findText(cat)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    arche = getattr(tab, 'archetype_combo', None)
    if arche is not None:
        idx = arche.findData(proposal.get('archetype') or 'auto')
        arche.setCurrentIndex(idx if idx >= 0 else 0)
    if hasattr(tab, 'log'):
        gancho = f" | gancho: {proposal['hook']}" if proposal.get('hook') else ""
        tab.log(f"Tendencias: cargado '{proposal.get('topic')}' [{proposal.get('archetype')}]{gancho}")


class TrendsDialog(QDialog):
    COLS = ("Tema", "Angulo", "Categoria", "Fecha", "Por que", "Gancho sugerido")

    def __init__(self, tab, report, parent=None):
        super().__init__(parent or tab)
        self.tab = tab
        self.proposals = list(report.get('proposals') or [])
        self.setWindowTitle(f"Tendencias ({report.get('generated_at', '')})")
        self.resize(1100, 520)
        layout = QVBoxLayout(self)
        pat = report.get('patterns') or {}
        resumen = []
        for a, g in (pat.get('by_archetype') or {}).items():
            resumen.append(f"{a}: {g['n']} videos / {g['views']:,} vistas")
        layout.addWidget(QLabel("YouTube nicho (30 dias, top 40): " + " · ".join(resumen[:5]) if resumen else "Sin muestreo de YouTube"))
        self.table = QTableWidget(len(self.proposals), len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, p in enumerate(self.proposals):
            values = (p.get('topic', ''), p.get('archetype', ''), p.get('category', ''), p.get('date') or '',
                      p.get('why', ''), p.get('hook', ''))
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda _i: self.use_selected())
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.btn_use = QPushButton('Usar tema (tema + categoria + angulo)')
        self.btn_use.clicked.connect(self.use_selected)
        buttons.addWidget(self.btn_use)
        btn_close = QPushButton('Cerrar')
        btn_close.clicked.connect(self.reject)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)

    def selected_proposal(self):
        row = self.table.currentRow()
        return self.proposals[row] if 0 <= row < len(self.proposals) else None

    def use_selected(self):
        p = self.selected_proposal()
        if p is None:
            return
        apply_proposal_to_studio(self.tab, p)
        self.accept()


def open_trends(tab):
    """Boton 'Tendencias': informe en un hilo y dialogo con temas cargables."""
    worker = getattr(tab, '_trends_worker', None)
    if worker is not None and worker.isRunning():
        tab.log("Tendencias: ya se esta calculando...")
        return
    btn = getattr(tab, 'btn_trends', None)
    if btn is not None:
        btn.setEnabled(False)
        btn.setText('Buscando…')

    def _restore():
        if btn is not None:
            btn.setEnabled(True)
            btn.setText('Tendencias')

    def _done(report):
        _restore()
        import trend_report
        for ln in trend_report.format_report(report).splitlines()[:12]:
            tab.log(ln)
        dlg = TrendsDialog(tab, report, parent=tab)
        tab._trends_dialog = dlg
        dlg.show()

    def _failed(msg):
        _restore()
        tab.log(f"Tendencias: no se pudo calcular ({msg})")

    worker = _TrendsWorker(parent=tab)
    worker.line.connect(tab.log)
    worker.done.connect(_done)
    worker.failed.connect(_failed)
    tab._trends_worker = worker
    worker.start()


def open_pilot(tab, *, generate=False):
    if tab.is_generating:
        QMessageBox.information(tab, 'Proceso activo', 'Espera a que termine la generación actual.')
        return
    topic_input = getattr(tab, 'topic_input', None) or tab.parent_gui.topic_input
    topic = topic_input.text().strip()
    if not topic:
        QMessageBox.information(tab, 'Tema requerido', 'Ingresa el tema antes de generar el storyboard.')
        return
    # Flush the Studio/timeline state before the dialog reads project.json.
    timer = getattr(tab, '_config_auto_save_timer', None)
    if timer:
        timer.stop()
    # The normal project autosaver also creates the folder for a new draft.
    if tab.auto_save_project('antes de continuar el piloto') is False:
        QMessageBox.warning(tab, 'Autoguardado pendiente', 'No se pudo guardar el proyecto actual. Revisa el registro antes de continuar.')
        return
    project_path = getattr(tab, 'current_project_path', None)
    if not project_path or not Path(project_path).is_file():
        QMessageBox.warning(tab, 'Proyecto no disponible', 'No se pudo crear automáticamente la carpeta del proyecto. Revisa el registro.')
        return
    out = Path(project_path).resolve().parent
    path = Path(out) / 'experiment.json'
    channel = project_channel_config(tab)['channel_profile']
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if manifest['channel'] != channel:
                raise ValueError('Selecciona primero el canal al que pertenece este piloto.')
            if manifest['topic'] != topic:
                raise ValueError('Este proyecto contiene un piloto de otro tema. Usa Nuevo proyecto para comenzar otro video.')
        except Exception as exc:
            QMessageBox.warning(tab, 'Piloto incompatible', str(exc))
            return
    dialog = PilotDialog(tab, out, topic, channel)
    if generate and not path.exists() and not (out / 'editorial_draft.txt').exists():
        QTimer.singleShot(0, lambda: dialog.run_stage(False, False))
    dialog.exec()
