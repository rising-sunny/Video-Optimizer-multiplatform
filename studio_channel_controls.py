"""Channel and microdocumentary controls for Auto Video Studio."""
import json
import html
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                            QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QTabWidget,
                            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QTextBrowser,
                            QSplitter, QProgressBar)

from channel.channel_profiles import CHANNELS, DEFAULT_CHANNEL, active_channel, select_channel


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
    from channel.channel_strategy import get_format_archetypes
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
    from channel.channel_strategy import pick_archetype_auto, archetype_label
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
        from studio_categories import get_studio_category_names, MYSTERY_CATEGORY, MYSTERY_DESCRIPTION
        combo = parent.category_combo
        previous = combo.currentText()
        blocked = combo.blockSignals(True)
        combo.clear()
        combo.addItems(get_studio_category_names())
        combo.setItemData(combo.findText(MYSTERY_CATEGORY), MYSTERY_DESCRIPTION, Qt.ItemDataRole.ToolTipRole)
        combo.setCurrentIndex(max(0, combo.findText(previous)))
        combo.blockSignals(blocked)
        if not blocked and combo.currentText() != previous:
            combo.currentTextChanged.emit(combo.currentText())
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
        from channel.channel_strategy import set_active_archetype
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
    tab.btn_trends.setToolTip('Demanda reciente en YouTube: vistas por día, varios canales y videos que respaldan cada tema')
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
        from pipeline.micro_documentary import resolve_image_provider
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
                from pipeline.micro_documentary import write_json, validate_packaging, runtime_plan
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
        from pipeline.micro_documentary import build, write_json, validate_packaging
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
            from infra.project_media_paths import normalize_project_path
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
            from channel import performance_feedback as pf
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
        from channel import performance_feedback as pf
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

    def __init__(self, options=None, force_refresh=False, parent=None):
        super().__init__(parent)
        self.options = dict(options or {})
        self.force_refresh = force_refresh

    def run(self):
        try:
            from channel import trend_report
            self.done.emit(trend_report.build_report(log=self.line.emit, force_refresh=self.force_refresh, **self.options))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def apply_proposal_to_studio(tab, proposal):
    """Carga tema + categoria + angulo de una propuesta en el formulario del Studio."""
    parent = getattr(tab, 'parent_gui', None)
    topic_widget = getattr(tab, 'topic_input', None) or getattr(parent, 'topic_input', None)
    if topic_widget is not None and hasattr(topic_widget, 'setText'):
        topic_widget.setText(str(proposal.get('topic') or ''))
    cat = str(proposal.get('category') or '')
    combo = getattr(tab, 'category_combo', None)
    if combo is None and parent is not None:
        combo = getattr(parent, 'category_combo', None)
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


def studio_trend_options(tab):
    """Read widgets on the GUI thread; workers receive a plain immutable snapshot."""
    parent = getattr(tab, 'parent_gui', None)
    combo = getattr(tab, 'category_combo', None)
    if combo is None:
        combo = getattr(parent, 'category_combo', None)
    category = combo.currentText() if combo is not None else ''
    es = getattr(tab, 'lang_es', None)
    en = getattr(tab, 'lang_en', None)
    language = 'es' if es is not None and es.isChecked() else 'en'
    if es is None and en is None:
        from channel.channel_strategy import get_channel_strategy
        language = get_channel_strategy().get('channel_identity', {}).get('language', 'en')
    platform = getattr(tab, 'platform_combo', None)
    data = platform.currentData() if platform is not None else None
    text = platform.currentText().lower() if platform is not None else ''
    if isinstance(data, dict):
        short = data.get('platform') in {'youtube_short', 'tiktok', 'reels'}
    else:
        short = ('short' in text or 'tiktok' in text or 'reels' in text or
                 ('9:16' in text and 'largo' not in text and 'long' not in text))
    return dict(category=category, language=language, region='MX' if language == 'es' else 'US',
                video_format='short' if short else 'long', days=30)


class _TrendItem(QTableWidgetItem):
    def __lt__(self, other):
        left, right = self.data(Qt.ItemDataRole.UserRole + 1), other.data(Qt.ItemDataRole.UserRole + 1)
        if left is not None and right is not None:
            return left < right
        return super().__lt__(other)


class TrendsDialog(QDialog):
    COLS = ("Tema / ángulo propuesto", "Prioridad", "Señal", "Vistas/día¹", "Canales", "En 7 días", "Categoría")

    def __init__(self, tab, report, parent=None):
        super().__init__(parent or tab)
        self.tab = tab
        self.proposals = []
        self.editorial_ideas = []
        available = self.screen().availableGeometry()
        self.resize(min(1250, available.width() - 40), min(790, available.height() - 70))
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        context = report.get('context') or studio_trend_options(tab)
        from studio_categories import get_studio_category_names
        self.category_filter = QComboBox()
        self.category_filter.addItem('Todas las categorías', '')
        for name in get_studio_category_names():
            self.category_filter.addItem(name, name)
        if context.get('category') and self.category_filter.findData(context['category']) < 0:
            self.category_filter.addItem(context['category'], context['category'])
        self.format_filter = QComboBox()
        self.format_filter.addItem('Videos >3 min', 'long')
        self.format_filter.addItem('Cortos ≤3 min', 'short')
        self.language_filter = QComboBox()
        self.language_filter.addItem('English', 'en')
        self.language_filter.addItem('Español', 'es')
        self.region_filter = QComboBox()
        for code, name in [('US', 'Estados Unidos'), ('GB', 'Reino Unido'), ('MX', 'México'), ('ES', 'España'), ('CL', 'Chile')]:
            self.region_filter.addItem(name, code)
        self.days_filter = QComboBox()
        for days in (7, 14, 30):
            self.days_filter.addItem(f'{days} días', days)
        for combo, key, default in [(self.category_filter, 'category', ''), (self.format_filter, 'video_format', 'long'),
                                    (self.language_filter, 'language', 'en'), (self.region_filter, 'region', 'US')]:
            combo.setCurrentIndex(max(0, combo.findData(context.get(key, default))))
            controls.addWidget(combo)
        self.days_filter.setCurrentIndex(max(0, self.days_filter.findData(report.get('window_days', 30))))
        controls.addWidget(self.days_filter)
        self.btn_refresh = QPushButton('Actualizar YouTube')
        self.btn_refresh.setToolTip('Consulta de nuevo y consume cuota de YouTube Data API. Al abrir se reutilizan muestras de menos de 6 horas.')
        self.btn_refresh.clicked.connect(lambda: open_trends(tab, options=self.options(), dialog=self, force_refresh=True))
        controls.addWidget(self.btn_refresh)
        layout.addLayout(controls)
        self.progress_label = QLabel()
        self.progress_label.setWordWrap(True)
        self.progress_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)
        self.progress_label.hide()
        self.progress_bar.hide()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.warning_label)
        self.tabs = QTabWidget()
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.calendar_table = QTableWidget(0, 4)
        self.calendar_table.setHorizontalHeaderLabels(('Tema', 'Fecha', 'Categoría', 'Motivo editorial'))
        for table in (self.table, self.calendar_table):
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setStyleSheet('QTableWidget::item { padding: 4px; }')
            table.verticalHeader().setDefaultSectionSize(35)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            table.itemSelectionChanged.connect(self.show_evidence)
            table.doubleClicked.connect(lambda _i: self.use_selected())
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 360)
        self.calendar_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.calendar_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.table, 'Señales de YouTube')
        self.tabs.addTab(self.calendar_table, 'Calendario · sin validar')
        self.tabs.currentChanged.connect(self.show_evidence)
        self.evidence_view = QTextBrowser()
        self.evidence_view.setOpenExternalLinks(True)
        self.evidence_view.setMinimumHeight(150)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.evidence_view)
        splitter.setSizes([340, 230])
        layout.addWidget(splitter, 1)
        footnote = QLabel('¹ Promedio desde publicación; crecimiento actual solo con dos mediciones. Cortos: filtro por duración, orientación sin verificar. '
                          'País: resultados disponibles allí, no vistas por país. Prioridad comparativa; no garantiza vistas.')
        footnote.setWordWrap(True)
        layout.addWidget(footnote)
        buttons = QHBoxLayout()
        self.btn_use = QPushButton('Usar tema (tema + categoria + angulo)')
        self.btn_use.clicked.connect(self.use_selected)
        buttons.addWidget(self.btn_use)
        btn_close = QPushButton('Cerrar')
        btn_close.clicked.connect(self.reject)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)
        self.load_report(report)

    def options(self):
        return dict(category=self.category_filter.currentData(), language=self.language_filter.currentData(),
                    region=self.region_filter.currentData(), video_format=self.format_filter.currentData(),
                    days=self.days_filter.currentData())

    def set_busy(self, busy):
        self.btn_refresh.setEnabled(not busy)
        self.btn_refresh.setText('Consultando…' if busy else 'Actualizar YouTube')
        self.progress_label.setVisible(busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.show_progress('Conectando con YouTube…')
        for combo in (self.category_filter, self.format_filter, self.language_filter, self.region_filter, self.days_filter):
            combo.setEnabled(not busy)

    def show_progress(self, message):
        self.progress_label.setText(str(message).removeprefix('[Tendencias]').strip())

    def load_report(self, report):
        self.report = report
        self.proposals = list(report.get('proposals') or [])
        self.editorial_ideas = list(report.get('editorial_ideas') or [])
        self.tabs.setCurrentIndex(0)
        self.setWindowTitle(f"Oportunidades en YouTube ({report.get('generated_at', '')})")
        yt = report.get('youtube') or {}
        c = report.get('context') or {}
        stamp = yt.get('sampled_at') or ''
        if stamp:
            from channel.youtube_trend_signals import timestamp
            captured = timestamp(stamp)
            if captured:
                stamp = captured.astimezone().strftime('%d/%m/%Y %H:%M')
        scope = f"{c.get('category') or 'Todas las categorías'} · {c.get('language', 'en').upper()}/{c.get('region', 'US')} · {report.get('window_days', 30)} días"
        qualified = yt.get('qualified_topics', 0)
        demand_label = f"{qualified} {'tema' if qualified == 1 else 'temas'} con demanda reciente"
        recovered = yt.get('refresh_failed') and yt.get('cached')
        partial_label = (' · resultado anterior' if recovered else
                         ' · muestra parcial' if yt.get('errors') and yt.get('sample_size') else '')
        source_label = (' · conservada; no se pudo actualizar' if recovered else
                        ' · guardada (menos de 6 horas)' if yt.get('cached') else ' · consultada en YouTube')
        self.status_label.setText(f"{yt.get('sample_size', len(report.get('youtube_sample') or []))} videos únicos · "
                                  f"{demand_label} · {scope}{partial_label}"
                                  + (f"\nMuestra: {stamp}{source_label}" if stamp else ''))
        warnings = list(yt.get('errors') or [])
        if not self.proposals:
            warnings.append('La consulta no pudo completarse. Pulsa Actualizar YouTube para volver a intentar.' if yt.get('errors') else
                            'No hay temas con evidencia de YouTube en esta consulta. Prueba una ventana de más días o cambia los filtros.')
        elif not yt.get('qualified_topics'):
            warnings.append('No se encontró suficiente demanda reciente en varios canales. Las señales disponibles están por validar.')
        self.warning_label.setText('\n'.join(warnings))
        self.warning_label.setVisible(bool(warnings))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.proposals))
        for r, p in enumerate(self.proposals):
            values = (p.get('topic', ''), p.get('score'), p.get('signal') or 'Sin verificar', p.get('views_per_day'),
                      p.get('channel_count'), p.get('recent_count'), p.get('category', ''))
            for col, value in enumerate(values):
                numeric = col in (1, 3, 4, 5)
                text = f'{value:,}' if numeric and value is not None else '—' if value is None else str(value)
                item = _TrendItem(text)
                item.setData(Qt.ItemDataRole.UserRole, r)
                if numeric:
                    item.setData(Qt.ItemDataRole.UserRole + 1, value if value is not None else -1)
                item.setToolTip((p.get('topic', '') + '\n' if col == 0 else '') + p.get('why', '')
                                + ('\n' + report.get('methodology', '') if col == 1 else ''))
                if p.get('qualified') and col in (1, 2):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(r, col, item)
        # Rank order from the report is the default. Manual sorts keep their original proposal identity.
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.DescendingOrder)
        self.table.setSortingEnabled(True)
        self.calendar_table.setRowCount(len(self.editorial_ideas))
        for r, p in enumerate(self.editorial_ideas):
            for col, value in enumerate((p.get('topic', ''), p.get('date') or '', p.get('category', ''), p.get('why', ''))):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.calendar_table.setItem(r, col, item)
        self.tabs.setTabText(0, f'Señales de YouTube ({len(self.proposals)})')
        self.tabs.setTabText(1, f'Calendario · sin validar ({len(self.editorial_ideas)})')
        if self.table.rowCount():
            self.table.selectRow(0)
        self.show_evidence()

    def selected_proposal(self):
        if self.tabs.currentIndex() == 1:
            row = self.calendar_table.currentRow()
            return self.editorial_ideas[row] if 0 <= row < len(self.editorial_ideas) else None
        row = self.table.currentRow()
        item = self.table.item(row, 0)
        idx = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return self.proposals[idx] if isinstance(idx, int) and 0 <= idx < len(self.proposals) else None

    def show_evidence(self):
        p = self.selected_proposal()
        self.btn_use.setEnabled(p is not None)
        if not p:
            self.evidence_view.setPlainText('Selecciona un tema para ver sus videos, fechas y métricas.\n\n' + (getattr(self, 'report', {}).get('methodology') or ''))
            return
        esc = html.escape
        body = f"<h3>{esc(str(p.get('topic') or ''))}</h3><p>{esc(str(p.get('why') or 'Sin demanda de YouTube verificada.'))}</p>"
        body += f"<p>Ángulo: {esc(str(p.get('archetype') or 'auto'))}" + (f" · Gancho: {esc(p['hook'])}" if p.get('hook') else '') + '</p>'
        evidence = p.get('evidence') or []
        if evidence:
            body += '<table cellpadding="5"><tr><th>Video / canal</th><th>Publicado</th><th>Vistas</th><th>Promedio/día</th><th>Ritmo medido/día</th></tr>'
            from urllib.parse import quote
            for v in evidence[:12]:
                url = 'https://www.youtube.com/watch?v=' + quote(str(v.get('video_id') or ''), safe='')
                measured = v.get('measured_views_per_day')
                rate = f'{measured:,.0f} ({v.get("measurement_hours", 0):.0f} h)' if measured is not None else 'Sin segunda medición'
                body += (f'<tr><td><a href="{esc(url, quote=True)}">{esc(str(v.get("title") or ""))}</a><br>{esc(str(v.get("channel") or ""))}</td>'
                         f'<td>{esc(str(v.get("published") or "")[:10])}</td><td>{v.get("views", 0):,}</td>'
                         f'<td>{v.get("views_per_day", 0):,.0f}</td><td>{rate}</td></tr>')
            body += '</table>'
        else:
            body += '<p>Idea editorial: no se ha comprobado su demanda en YouTube.</p>'
        if getattr(self, 'report', {}).get('methodology'):
            body += '<p>' + esc(self.report['methodology']) + '</p>'
        self.evidence_view.setHtml(body)

    def use_selected(self):
        p = self.selected_proposal()
        if p is None:
            return
        apply_proposal_to_studio(self.tab, p)
        self.accept()


def open_trends(tab, *, options=None, dialog=None, force_refresh=False):
    """Boton 'Tendencias': informe en un hilo y dialogo con temas cargables."""
    worker = getattr(tab, '_trends_worker', None)
    if worker is not None and worker.isRunning():
        tab.log("Tendencias: ya se esta calculando...")
        return
    btn = getattr(tab, 'btn_trends', None)
    if btn is not None:
        btn.setEnabled(False)
        btn.setText('Buscando…')
    if dialog is not None:
        dialog.set_busy(True)

    def _restore():
        if btn is not None:
            btn.setEnabled(True)
            btn.setText('Tendencias')
        if dialog is not None:
            dialog.set_busy(False)

    def _done(report):
        _restore()
        from channel import trend_report
        for ln in trend_report.format_report(report).splitlines()[:12]:
            tab.log(ln)
        if dialog is not None:
            dialog.load_report(report)
        else:
            dlg = TrendsDialog(tab, report, parent=tab)
            tab._trends_dialog = dlg
            dlg.show()

    def _failed(msg):
        _restore()
        tab.log(f"Tendencias: no se pudo calcular ({msg})")
        if dialog is not None:
            dialog.warning_label.setText('No se pudo actualizar. Se conserva la muestra anterior. ' + msg)
            dialog.warning_label.show()

    worker = _TrendsWorker(options=options if options is not None else studio_trend_options(tab), force_refresh=force_refresh, parent=tab)
    worker.line.connect(tab.log)
    if dialog is not None:
        worker.line.connect(dialog.show_progress)
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
