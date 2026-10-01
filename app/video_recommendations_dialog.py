# video_recommendations_dialog.py
"""
Diálogo para mostrar recomendaciones de videos generadas por el sistema inteligente.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QMessageBox, QProgressBar,
    QTextEdit, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
import os
from typing import Optional
import json


class VideoRecommendationsWorker(QThread):
    """Worker thread para generar recomendaciones de videos"""
    finished = pyqtSignal(list)  # Emite lista de recomendaciones
    error = pyqtSignal(str)  # Emite mensaje de error
    progress = pyqtSignal(str)  # Emite mensajes de progreso
    
    def __init__(self, category, language='es'):
        super().__init__()
        self.category = category
        self.language = language
    
    def run(self):
        """Ejecuta la generación de recomendaciones"""
        try:
            from app.video_recommender import VideoRecommender
            
            self.progress.emit(" Analizando tendencias de Google...")
            
            # Obtener configuración del canal si está disponible
            channel_id = os.getenv("YOUTUBE_CHANNEL_ID")
            channel_handle = os.getenv("YOUTUBE_CHANNEL_HANDLE")
            
            # Si hay handle, remover @ si existe
            if channel_handle and channel_handle.startswith('@'):
                channel_handle = channel_handle[1:]
            
            recommender = VideoRecommender(channel_id=channel_id, channel_handle=channel_handle)
            
            if channel_id or channel_handle:
                self.progress.emit(" Analizando tu canal de YouTube...")
            
            self.progress.emit(" Analizando videos populares en YouTube...")
            recommendations = recommender.get_recommendations(
                category=self.category,
                language=self.language,
                max_recommendations=15
            )
            
            if not recommendations:
                self.error.emit("No se pudieron generar recomendaciones. Verifica tus APIs configuradas.")
                return
            
            self.progress.emit(f" {len(recommendations)} recomendaciones generadas")
            self.finished.emit(recommendations)
            
        except Exception as e:
            import traceback
            error_msg = f"Error generando recomendaciones:\n{str(e)}\n\n{traceback.format_exc()}"
            self.error.emit(error_msg)


class VideoRecommendationsDialog(QDialog):
    """Diálogo para mostrar recomendaciones de videos"""
    
    def __init__(self, parent=None, category="general"):
        super().__init__(parent)
        self.category = category
        self.recommendations = []
        self.setWindowTitle(f" Recomendaciones de Videos - {category.title()}")
        self.setMinimumSize(900, 700)
        
        self.setup_ui()
        self.start_analysis()
    
    def get_channel_info(self) -> Optional[str]:
        """Obtiene información del canal configurado"""
        channel_id = os.getenv("YOUTUBE_CHANNEL_ID")
        channel_handle = os.getenv("YOUTUBE_CHANNEL_HANDLE")
        
        if channel_handle:
            return f"@{channel_handle}" if not channel_handle.startswith('@') else channel_handle
        elif channel_id:
            return f"Canal ID: {channel_id[:10]}..."
        
        return None
    
    def get_monetization_info(self) -> Optional[str]:
        """Obtiene información de monetización del canal"""
        try:
            from channel.youtube_channel_analyzer import YouTubeChannelAnalyzer
            
            channel_id = os.getenv("YOUTUBE_CHANNEL_ID")
            channel_handle = os.getenv("YOUTUBE_CHANNEL_HANDLE")
            
            if channel_handle and channel_handle.startswith('@'):
                channel_handle = channel_handle[1:]
            
            if not channel_id and not channel_handle:
                return None
            
            analyzer = YouTubeChannelAnalyzer(channel_id, channel_handle)
            gap = analyzer.get_monetization_gap_analysis()
            
            if gap.get('can_monetize', False):
                return f" CANAL MONETIZABLE | Suscriptores: {gap['subscribers']:,} | Horas: {gap['watch_hours']:.1f}"
            else:
                priority = gap.get('priority', 'both')
                priority_text = {
                    'subscribers': 'SUSCRIPTORES',
                    'watch_hours': 'HORAS DE VISUALIZACIÓN',
                    'both': 'AMBOS'
                }.get(priority, 'AMBOS')
                
                return (
                    f" META MONETIZACIÓN | Prioridad: {priority_text}\n"
                    f"Suscriptores: {gap['subscribers']:,}/{gap['subscribers_needed']:,} "
                    f"({gap['subscribers_progress']:.1f}%) | "
                    f"Horas: {gap['watch_hours']:.1f}/{gap['watch_hours_needed']:.0f} "
                    f"({gap['watch_hours_progress']:.1f}%)"
                )
        except Exception as e:
            return None
    
    def setup_ui(self):
        """Configura la interfaz del diálogo"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = QLabel(f" Recomendaciones Inteligentes para: {self.category.title()}")
        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setStyleSheet("color: #e67e22; padding: 10px;")
        layout.addWidget(header)
        
        # Información de monetización (si hay canal configurado)
        channel_info = self.get_channel_info()
        if channel_info:
            monetization_info = self.get_monetization_info()
            if monetization_info:
                monetization_label = QLabel(monetization_info)
                monetization_label.setStyleSheet("""
                    background-color: #1a3a2a;
                    color: #14a085;
                    font-weight: bold;
                    padding: 10px;
                    border-radius: 5px;
                    border: 1px solid #14a085;
                """)
                layout.addWidget(monetization_label)
        
        # Información
        info_label = QLabel(
            "El sistema analiza tendencias, competencia y tu canal para recomendarte\n"
            "los mejores temas de videos que te acerquen a la monetización."
        )
        info_label.setStyleSheet("color: #a0a0a0; padding: 5px;")
        layout.addWidget(info_label)
        
        # Barra de progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminado
        self.progress_bar.setVisible(True)
        layout.addWidget(self.progress_bar)
        
        # Área de scroll para recomendaciones
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                background-color: #1e1e1e;
            }
        """)
        
        self.recommendations_container = QWidget()
        self.recommendations_layout = QVBoxLayout(self.recommendations_container)
        self.recommendations_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.recommendations_layout.setSpacing(15)
        
        scroll.setWidget(self.recommendations_container)
        layout.addWidget(scroll, stretch=1)
        
        # Botones
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        self.close_btn = QPushButton(" Cerrar")
        self.close_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(self.close_btn)
        
        layout.addLayout(buttons_layout)
    
    def start_analysis(self):
        """Inicia el análisis de recomendaciones"""
        self.progress_bar.setVisible(True)
        self.close_btn.setEnabled(False)
        
        # Limpiar recomendaciones anteriores
        while self.recommendations_layout.count():
            item = self.recommendations_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Mostrar mensaje de carga
        loading_label = QLabel(" Analizando tendencias y generando recomendaciones...")
        loading_label.setStyleSheet("color: #a0a0a0; padding: 20px; font-size: 12pt;")
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recommendations_layout.addWidget(loading_label)
        
        # Crear worker
        self.worker = VideoRecommendationsWorker(self.category)
        self.worker.finished.connect(self.on_recommendations_ready)
        self.worker.error.connect(self.on_error)
        self.worker.progress.connect(lambda msg: print(f"   {msg}"))  # Log en consola
        self.worker.start()
    
    def on_recommendations_ready(self, recommendations):
        """Callback cuando las recomendaciones están listas"""
        self.progress_bar.setVisible(False)
        self.close_btn.setEnabled(True)
        self.recommendations = recommendations
        
        # Limpiar mensaje de carga
        while self.recommendations_layout.count():
            item = self.recommendations_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not recommendations:
            no_recs_label = QLabel("️ No se pudieron generar recomendaciones.")
            no_recs_label.setStyleSheet("color: #e74c3c; padding: 20px; font-size: 12pt;")
            no_recs_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.recommendations_layout.addWidget(no_recs_label)
            return
        
        # Mostrar cada recomendación
        for i, rec in enumerate(recommendations, 1):
            rec_widget = self.create_recommendation_widget(i, rec)
            self.recommendations_layout.addWidget(rec_widget)
        
        # Agregar stretch al final
        self.recommendations_layout.addStretch()
    
    def _normalize_text(self, text):
        """Normaliza texto que puede tener problemas de codificación UTF-8"""
        if not isinstance(text, str):
            return str(text)
        try:
            # Si tiene caracteres mal codificados, intentar corregirlos
            if 'Ã' in text or 'â' in text:
                try:
                    # Intentar decodificar como latin-1 y luego codificar en UTF-8
                    # Esto corrige el problema común de UTF-8 interpretado como latin-1
                    text = text.encode('latin-1').decode('utf-8')
                except:
                    # Si falla, intentar otras correcciones
                    try:
                        text = text.encode('utf-8', errors='ignore').decode('utf-8')
                    except:
                        pass
            return text
        except:
            return text
    
    def create_recommendation_widget(self, index, recommendation):
        """Crea un widget para mostrar una recomendación"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                padding: 15px;
            }
            QFrame:hover {
                border: 1px solid #0d7377;
                background-color: #333333;
            }
        """)
        layout = QVBoxLayout(frame)
        layout.setSpacing(10)
        
        # Header con título y score
        header_layout = QHBoxLayout()
        
        title = self._normalize_text(recommendation.get('title', 'Sin título'))
        title_label = QLabel(f"#{index}. {title}")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #ffffff;")
        title_label.setWordWrap(True)
        header_layout.addWidget(title_label, stretch=1)
        
        # Score
        final_score = recommendation.get('final_score', 0)
        score_label = QLabel(f" {final_score:.1f}/10")
        score_label.setStyleSheet("""
            QLabel {
                background-color: #27ae60;
                color: white;
                padding: 5px 10px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        header_layout.addWidget(score_label)
        
        layout.addLayout(header_layout)
        
        # Descripción
        description = self._normalize_text(recommendation.get('description', ''))
        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: #b0b0b0; padding: 5px;")
            layout.addWidget(desc_label)
        
        # Por qué podría ser viral
        why_viral = self._normalize_text(recommendation.get('why_viral', ''))
        if why_viral:
            viral_label = QLabel(f" {why_viral}")
            viral_label.setWordWrap(True)
            viral_label.setStyleSheet("color: #e67e22; padding: 5px; font-style: italic;")
            layout.addWidget(viral_label)
        
        # Ángulo único
        angle = self._normalize_text(recommendation.get('angle', ''))
        if angle:
            angle_label = QLabel(f" Ángulo único: {angle}")
            angle_label.setWordWrap(True)
            angle_label.setStyleSheet("color: #3498db; padding: 5px;")
            layout.addWidget(angle_label)
        
        # Keywords
        keywords = recommendation.get('keywords', [])
        if keywords:
            keywords_normalized = [self._normalize_text(kw) for kw in keywords[:5]]
            keywords_str = ", ".join(keywords_normalized)  # Mostrar máximo 5
            keywords_label = QLabel(f"️ Keywords: {keywords_str}")
            keywords_label.setWordWrap(True)
            keywords_label.setStyleSheet("color: #9b59b6; padding: 5px; font-size: 9pt;")
            layout.addWidget(keywords_label)
        
        # Métricas
        metrics_layout = QHBoxLayout()
        
        potential = recommendation.get('potential_views', 'N/A')
        metrics_layout.addWidget(QLabel(f" Potencial: {potential}"))
        
        trend_score = recommendation.get('trend_score', 0)
        metrics_layout.addWidget(QLabel(f" Tendencias: {trend_score:.1f}/10"))
        
        comp_score = recommendation.get('competition_score', 0)
        metrics_layout.addWidget(QLabel(f"️ Competencia: {comp_score:.1f}/10"))
        
        layout.addLayout(metrics_layout)
        
        # Botón para usar esta recomendación
        use_btn = QPushButton(" Usar esta Recomendación")
        use_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        use_btn.clicked.connect(lambda checked, rec=recommendation: self.use_recommendation(rec))
        layout.addWidget(use_btn)
        
        return frame
    
    def use_recommendation(self, recommendation):
        """Usa una recomendación para generar un video"""
        title = recommendation.get('title', '')
        
        reply = QMessageBox.question(
            self,
            "Usar Recomendación",
            f"¿Deseas generar un video con esta recomendación?\n\n"
            f"Título: {title}\n\n"
            f"Se abrirá el generador de videos con este tema.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Cerrar el diálogo y pasar el título al generador
            if self.parent():
                # Intentar establecer el tema en el input del generador
                if hasattr(self.parent(), 'topic_input'):
                    self.parent().topic_input.setText(title)
                elif hasattr(self.parent(), 'topic_combo'):
                    # Si hay un combo box, agregar el tema
                    self.parent().topic_combo.setCurrentText(title)
            
            self.accept()
    
    def on_error(self, error_msg):
        """Callback cuando hay un error"""
        self.progress_bar.setVisible(False)
        self.close_btn.setEnabled(True)
        
        # Limpiar mensaje de carga
        while self.recommendations_layout.count():
            item = self.recommendations_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        error_label = QLabel(f" {error_msg}")
        error_label.setWordWrap(True)
        error_label.setStyleSheet("color: #e74c3c; padding: 20px; font-size: 11pt;")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recommendations_layout.addWidget(error_label)

