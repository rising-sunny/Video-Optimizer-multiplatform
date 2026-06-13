from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import json
from pathlib import Path
from PIL import Image
import threading
import time
from ui_workers import AnalysisWorker, ResearchWorker, TrendsWorker, SearchWorker

class AnalysisMixin:
    def create_analysis_tab(self):
        """Crea la pestaña de análisis"""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)
        
        # Scroll area para todo el contenido
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)
        
        # Sección de análisis manual
        manual_group = QGroupBox("Análisis de tema")
        manual_layout = QVBoxLayout(manual_group)
        manual_layout.setSpacing(8)
        
        # Tema
        topic_layout = QHBoxLayout()
        topic_layout.addWidget(QLabel("Tema:"))
        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText("Ej: El misterio de las pirámides de Egipto")
        topic_layout.addWidget(self.topic_input)
        manual_layout.addLayout(topic_layout)
        
        # Categoría
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Categoría:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "Eventos naturales extremos", "Ciencia/Tecnología actual",
            "Historia antigua/civilizaciones", "Historia militar/guerras",
            "Misterios con datos", "Conspiraciones verificables",
            "Actualidad científica", "Documentales"
        ])
        category_layout.addWidget(self.category_combo)
        category_layout.addStretch()
        manual_layout.addLayout(category_layout)
        
        # Botones de acción
        actions_layout = QHBoxLayout()
        
        self.btn_analyze = QPushButton("Analizar tema")
        self.btn_analyze.setObjectName("accent")
        self.btn_analyze.clicked.connect(self.analyze_topic)
        actions_layout.addWidget(self.btn_analyze)
        
        self.btn_research = QPushButton(" Investigar tema")
        self.btn_research.setObjectName("success")
        self.btn_research.setToolTip(
            "Busca información en Wikipedia y DuckDuckGo.\\n"
            "Selecciona los resultados relevantes antes de generar el guión."
        )
        self.btn_research.clicked.connect(self.research_topic)
        actions_layout.addWidget(self.btn_research)
        
        manual_layout.addLayout(actions_layout)
        layout.addWidget(manual_group)
        
        # Resultados del análisis (colapsable, solo visible cuando hay contenido)
        results_group = QGroupBox("Resultado del análisis")
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(8, 8, 8, 8)
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setFixedHeight(120)
        results_layout.addWidget(self.results_text)
        
        layout.addWidget(results_group)
        
        # Sección de resultados de investigación
        research_group = QGroupBox("Resultados de investigación (selecciona los relevantes para el guión)")
        research_layout = QVBoxLayout(research_group)
        research_layout.setContentsMargins(8, 8, 8, 8)
        research_layout.setSpacing(6)
        
        # Botones de selección arriba de la lista
        research_top_bar = QHBoxLayout()
        self.research_status_label = QLabel("Escribe un tema y pulsa 'Investigar tema' para buscar fuentes.")
        self.research_status_label.setObjectName("subtitle")
        self.research_status_label.setWordWrap(True)
        research_top_bar.addWidget(self.research_status_label, 1)
        
        self.btn_select_all_research = QPushButton("Seleccionar todos")
        self.btn_select_all_research.clicked.connect(self._select_all_research)
        self.btn_select_all_research.setEnabled(False)
        self.btn_select_all_research.setFixedWidth(130)
        research_top_bar.addWidget(self.btn_select_all_research)
        
        self.btn_deselect_all_research = QPushButton("Deseleccionar todos")
        self.btn_deselect_all_research.clicked.connect(self._deselect_all_research)
        self.btn_deselect_all_research.setEnabled(False)
        self.btn_deselect_all_research.setFixedWidth(140)
        research_top_bar.addWidget(self.btn_deselect_all_research)
        
        research_layout.addLayout(research_top_bar)
        
        self.research_results_list = QListWidget()
        self.research_results_list.setMinimumHeight(120)
        self.research_results_list.setMaximumHeight(250)
        self.research_results_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.research_results_list.setWordWrap(True)
        self.research_results_list.setStyleSheet("""
            QListWidget::item { 
                padding: 6px; 
                border-bottom: 1px solid #333; 
            }
        """)
        research_layout.addWidget(self.research_results_list)
        
        layout.addWidget(research_group)
        
        # Estado interno de investigación
        self.research_results_data = []
        self.selected_research_snippets = []
        
        # Checkbox para auto-guardado
        self.auto_save_check = QCheckBox("Guardar automáticamente después de cada paso")
        self.auto_save_check.setToolTip("Guarda automáticamente el proyecto después de completar cada paso importante")
        self.auto_save_check.stateChanged.connect(self._on_auto_save_changed)
        QTimer.singleShot(100, self._sync_auto_save_state)
        layout.addWidget(self.auto_save_check)
        
        # Seccion "Ideas y tendencias" eliminada (redundante)
        
        scroll.setWidget(scroll_content)
        tab_layout.addWidget(scroll)
        
        return tab

    def analyze_topic(self):
        """Analiza un tema con IA"""
        topic = self.topic_input.text().strip()
        category = self.category_combo.currentText()
        
        if not topic:
            QMessageBox.warning(self, "Entrada Vacía", "Por favor ingresa un tema")
            return
        
        if not self.gemini_client:
            QMessageBox.critical(self, "Error", "Gemini AI no está disponible")
            return
        
        if self.current_worker and self.current_worker.isRunning():
            QMessageBox.warning(self, "Ocupado", "Ya hay un análisis en curso")
            return
        
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText("Analizando...")
        self.results_text.clear()
        
        self.log(f" Iniciando análisis de: {topic}")
        
        # Crear worker
        self.current_worker = AnalysisWorker(topic, category, self.gemini_client)
        self.current_worker.finished.connect(self.on_analysis_finished)
        self.current_worker.error.connect(self.on_analysis_error)
        self.current_worker.progress.connect(self.log)
        self.current_worker.start()

    def on_analysis_finished(self, data):
        """Callback cuando termina el análisis"""
        self.btn_analyze.setEnabled(True)
        self.btn_analyze.setText("Analizar tema")
        
        # Mostrar resultados
        result_text = f"TÍTULO SUGERIDO:\\n{data.get('title', 'N/A')}\\n\\n"
        result_text += f"DESCRIPCIÓN:\\n{data.get('description', 'N/A')}\\n\\n"
        result_text += f"TAGS:\\n{', '.join(data.get('tags', []))}"
        
        self.results_text.setPlainText(result_text)
        self.log(" Análisis completado")

    def on_analysis_error(self, error_msg):
        """Callback cuando hay error en el análisis"""
        self.btn_analyze.setEnabled(True)
        self.btn_analyze.setText("Analizar tema")
        
        self.log(f" Error en análisis: {error_msg}")
        QMessageBox.critical(self, "Error", f"Error en análisis: {error_msg}")

    def research_topic(self):
        """Busca información sobre el tema en fuentes externas"""
        topic = self.topic_input.text().strip()
        if not topic:
            QMessageBox.warning(self, "Entrada Vacía", "Por favor ingresa un tema para investigar")
            return
        
        if hasattr(self, '_research_worker') and self._research_worker and self._research_worker.isRunning():
            QMessageBox.warning(self, "Ocupado", "Ya hay una búsqueda en curso")
            return
        
        self.btn_research.setEnabled(False)
        self.btn_research.setText("Buscando...")
        self.research_results_list.clear()
        self.research_results_data = []
        self.selected_research_snippets = []
        self.research_status_label.setText("Buscando en Wikipedia y DuckDuckGo...")
        
        self.log(f" Investigando tema: {topic}")
        
        self._research_worker = ResearchWorker(topic, language='es')
        self._research_worker.finished.connect(self.on_research_finished)
        self._research_worker.error.connect(self.on_research_error)
        self._research_worker.progress.connect(self.log)
        self._research_worker.start()

    def on_research_finished(self, results):
        """Callback cuando termina la búsqueda de investigación"""
        self.btn_research.setEnabled(True)
        self.btn_research.setText(" Investigar tema")
        self.research_results_data = results
        self.research_results_list.clear()
        
        for i, result in enumerate(results):
            source = result.get('source', '?')
            title = result.get('title', 'Sin título')
            snippet = result.get('snippet', '')
            url = result.get('url', '')
            
            display_text = f"[{source}] {title}\\n{snippet}"
            if url:
                display_text += f"\\n {url}"
            
            item = QListWidgetItem(display_text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.research_results_list.addItem(item)
        
        try:
            self.research_results_list.itemChanged.disconnect(self._on_research_item_changed)
        except TypeError:
            pass
        self.research_results_list.itemChanged.connect(self._on_research_item_changed)
        
        self.btn_select_all_research.setEnabled(True)
        self.btn_deselect_all_research.setEnabled(True)
        self.research_status_label.setText(
            f"Se encontraron {len(results)} resultados. Selecciona los relevantes para el guión."
        )
        self.log(f" Investigación completada: {len(results)} resultados encontrados")

    def on_research_error(self, error_msg):
        """Callback cuando hay error en la investigación"""
        self.btn_research.setEnabled(True)
        self.btn_research.setText(" Investigar tema")
        self.research_status_label.setText(f"Error: {error_msg}")
        self.log(f" Error en investigación: {error_msg}")

    def _on_research_item_changed(self, item):
        """Actualiza la lista de snippets seleccionados cuando cambia un checkbox"""
        self._update_selected_research()

    def _update_selected_research(self):
        """Recalcula los snippets seleccionados"""
        self.selected_research_snippets = []
        selected_count = 0
        for i in range(self.research_results_list.count()):
            item = self.research_results_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                idx = item.data(Qt.ItemDataRole.UserRole)
                if idx is not None and idx < len(self.research_results_data):
                    data = self.research_results_data[idx]
                    snippet_text = (
                        f"Título: {data.get('title', '')}\\n"
                        f"Snippet: {data.get('full_text', data.get('snippet', ''))}\\n"
                        f"URL: {data.get('url', '')}"
                    )
                    self.selected_research_snippets.append(snippet_text)
                    selected_count += 1
        
        self.research_status_label.setText(
            f"{selected_count} de {len(self.research_results_data)} resultados seleccionados"
        )

    def _select_all_research(self):
        """Selecciona todos los resultados de investigación"""
        self.research_results_list.blockSignals(True)
        for i in range(self.research_results_list.count()):
            self.research_results_list.item(i).setCheckState(Qt.CheckState.Checked)
        self.research_results_list.blockSignals(False)
        self._update_selected_research()

    def _deselect_all_research(self):
        """Deselecciona todos los resultados de investigación"""
        self.research_results_list.blockSignals(True)
        for i in range(self.research_results_list.count()):
            self.research_results_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.research_results_list.blockSignals(False)
        self._update_selected_research()

    def get_selected_research_context(self):
        """Retorna los snippets seleccionados como contexto para generación de guión"""
        return self.selected_research_snippets if self.selected_research_snippets else []

    def show_video_recommendations(self):
        """Muestra el diálogo de recomendaciones de videos"""
        try:
            from video_recommendations_dialog import VideoRecommendationsDialog
        except ImportError:
            QMessageBox.warning(
                self,
                "Módulo no disponible",
                "El módulo video_recommendations_dialog.py no está disponible.\\n"
                "Asegúrate de que el archivo esté en el directorio del proyecto."
            )
            return
        
        # Obtener categoría del combo box
        category = self.category_combo.currentText() if hasattr(self, 'category_combo') else None
        
        if not category:
            # Pedir categoría al usuario si no hay una seleccionada
            from PyQt6.QtWidgets import QInputDialog
            category, ok = QInputDialog.getText(
                self,
                "Seleccionar Temática",
                "Ingresa la temática de tu canal:\\n"
                "(Ej: historia, ciencia, tecnología, misterios, etc.)"
            )
            if not ok or not category.strip():
                return
            category = category.strip()
        
        # Mostrar diálogo de recomendaciones
        dialog = VideoRecommendationsDialog(self, category)
        dialog.exec()

    def search_trends(self):
        """Busca tendencias en Google/YouTube"""
        topic = self.topic_input.text().strip()
        
        if not topic:
            QMessageBox.warning(self, "Entrada Vacía", "Por favor ingresa un tema")
            return
        
        if not GOOGLE_API_AVAILABLE:
            QMessageBox.critical(self, "Error", "Google Search API no disponible")
            return
        
        # Preguntar qué buscar
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Seleccionar Fuente")
        dialog.setText("¿Dónde deseas buscar?")
        btn_youtube = dialog.addButton("YouTube", QMessageBox.ButtonRole.YesRole)
        btn_google = dialog.addButton("Google", QMessageBox.ButtonRole.NoRole)
        dialog.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        
        clicked = dialog.clickedButton()
        if clicked == btn_youtube:
            search_type = "YouTube"
        elif clicked == btn_google:
            search_type = "Google"
        else:
            return
        
        self.log(f" Buscando en {search_type}: {topic}")
        
        # Crear worker
        self.current_worker = SearchWorker(topic, search_type)
        self.current_worker.finished.connect(self.on_search_finished)
        self.current_worker.error.connect(self.on_search_error)
        self.current_worker.progress.connect(self.log)
        self.current_worker.start()

    def on_search_finished(self, results):
        """Callback cuando termina la búsqueda"""
        result_text = "\\n".join(results)
        self.results_text.setPlainText(result_text)
        self.log(f" Búsqueda completada: {len(results)} resultados")

    def on_search_error(self, error_msg):
        """Callback cuando hay error en búsqueda"""
        self.log(f" Error en búsqueda: {error_msg}")
        QMessageBox.critical(self, "Error", f"Error en búsqueda: {error_msg}")

    def refresh_trends(self):
        """Refresca las tendencias automáticas"""
        if not TRENDS_AVAILABLE:
            QMessageBox.critical(self, "Error", "Trends Spotter no está disponible")
            return
        
        if not self.gemini_client:
            QMessageBox.critical(self, "Error", "Gemini AI no está disponible")
            return
        
        if self.current_worker and self.current_worker.isRunning():
            QMessageBox.warning(self, "Ocupado", "Ya hay un proceso en curso")
            return
        
        self.btn_refresh_trends.setEnabled(False)
        self.btn_refresh_trends.setText(" Cargando...")
        
        # Limpiar contenedor
        self.clear_trends_container()
        loading_label = QLabel("Obteniendo tendencias de Google y analizando con IA... (Paso 1/2)")
        loading_label.setObjectName("subtitle")
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.trends_layout.addWidget(loading_label)
        
        self.log(" Refrescando tendencias...")
        
        # Obtener contexto del usuario si está disponible
        user_categories = None
        if hasattr(self, 'category_combo') and self.category_combo.currentText():
            cat = self.category_combo.currentText()
            if cat and cat != "General":
                user_categories = [cat, "Viral", "Curiosidades"]
        
        if hasattr(self, 'topic_input') and self.topic_input.text():
            topic = self.topic_input.text().strip()
            if topic:
                if user_categories:
                    user_categories.insert(0, topic)
                else:
                    user_categories = [topic, "Viral", "Tendencias"]

        # Crear worker con categorías personalizadas
        self.current_worker = TrendsWorker(self.gemini_client, categories=user_categories)
        self.current_worker.finished.connect(self.on_trends_finished)
        self.current_worker.error.connect(self.on_trends_error)
        self.current_worker.progress.connect(self.log)
        self.current_worker.start()

