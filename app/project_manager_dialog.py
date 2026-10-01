# project_manager_dialog.py
"""
Diálogo para gestionar proyectos guardados
Permite ver lista, información detallada, eliminar y abrir proyectos
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QTextEdit, QGroupBox, QSplitter, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from datetime import datetime
from pathlib import Path
import os

from app.project_manager_v2 import ProjectManagerV2


class ProjectManagerDialog(QDialog):
    """Diálogo para gestionar proyectos guardados"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(" Gestión de Proyectos")
        self.setMinimumSize(900, 600)
        self.selected_project_path = None
        
        self.setup_ui()
        self.refresh_projects_list()
    
    def setup_ui(self):
        """Crea la interfaz del diálogo"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Título
        title = QLabel(" Gestión de Proyectos Guardados")
        title.setStyleSheet("font-size: 16pt; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        # Splitter principal: Lista a la izquierda, Detalles a la derecha
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Panel izquierdo: Lista de proyectos
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        list_label = QLabel("Proyectos Guardados:")
        list_label.setStyleSheet("font-weight: bold; color: #ffffff;")
        left_layout.addWidget(list_label)
        
        # Tabla de proyectos
        self.projects_table = QTableWidget()
        self.projects_table.setColumnCount(3)
        self.projects_table.setHorizontalHeaderLabels(["Tema", "Fecha", "Progreso"])
        self.projects_table.horizontalHeader().setStretchLastSection(True)
        self.projects_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.projects_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.projects_table.itemSelectionChanged.connect(self.on_project_selected)
        self.projects_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                gridline-color: #3d3d3d;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #0d7377;
            }
            QHeaderView::section {
                background-color: #1a1a1a;
                color: #ffffff;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
        """)
        left_layout.addWidget(self.projects_table)
        
        # Botones de acción
        buttons_layout = QHBoxLayout()
        
        self.btn_refresh = QPushButton(" Actualizar")
        self.btn_refresh.clicked.connect(self.refresh_projects_list)
        buttons_layout.addWidget(self.btn_refresh)
        
        self.btn_delete = QPushButton("️ Eliminar")
        self.btn_delete.setStyleSheet("background-color: #e74c3c;")
        self.btn_delete.clicked.connect(self.delete_selected_project)
        self.btn_delete.setEnabled(False)
        buttons_layout.addWidget(self.btn_delete)
        
        buttons_layout.addStretch()
        
        self.btn_open = QPushButton(" Abrir Proyecto")
        self.btn_open.setStyleSheet("background-color: #0d7377; font-weight: bold;")
        self.btn_open.clicked.connect(self.accept)
        self.btn_open.setEnabled(False)
        buttons_layout.addWidget(self.btn_open)
        
        left_layout.addLayout(buttons_layout)
        
        # Panel derecho: Detalles del proyecto
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        details_label = QLabel("Detalles del Proyecto:")
        details_label.setStyleSheet("font-weight: bold; color: #ffffff;")
        right_layout.addWidget(details_label)
        
        # Área de detalles
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        self.details_text.setPlaceholderText("Selecciona un proyecto para ver sus detalles...")
        right_layout.addWidget(self.details_text)
        
        # Agregar paneles al splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
        
        # Botones de cierre
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.clicked.connect(self.reject)
        close_layout.addWidget(self.btn_close)
        
        layout.addLayout(close_layout)
    
    def refresh_projects_list(self):
        """Actualiza la lista de proyectos"""
        projects = ProjectManagerV2.list_projects()
        
        self.projects_table.setRowCount(len(projects))
        
        for row, project in enumerate(projects):
            # Tema
            topic_item = QTableWidgetItem(project.get('topic', 'Sin título'))
            topic_item.setData(Qt.ItemDataRole.UserRole, project.get('path'))
            self.projects_table.setItem(row, 0, topic_item)
            
            # Fecha
            created = project.get('created', '')
            if created:
                try:
                    dt = datetime.fromisoformat(created)
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = created[:16] if len(created) > 16 else created
            else:
                date_str = "N/A"
            self.projects_table.setItem(row, 1, QTableWidgetItem(date_str))
            
            # Progreso
            progress = project.get('progress', {})
            progress_parts = []
            if progress.get('storyboard_done'):
                progress_parts.append(" Storyboard")
            if progress.get('images_done'):
                progress_parts.append("️ Imágenes")
            if progress.get('video_assembled'):
                progress_parts.append(" Video")
            if progress.get('published'):
                progress_parts.append(" Publicado")
            
            progress_text = ", ".join(progress_parts) if progress_parts else "Nuevo"
            self.projects_table.setItem(row, 2, QTableWidgetItem(progress_text))
        
        # Ajustar columnas
        self.projects_table.resizeColumnsToContents()
        self.projects_table.horizontalHeader().setStretchLastSection(True)
    
    def on_project_selected(self):
        """Cuando se selecciona un proyecto"""
        selected_items = self.projects_table.selectedItems()
        if not selected_items:
            self.btn_open.setEnabled(False)
            self.btn_delete.setEnabled(False)
            self.details_text.clear()
            self.selected_project_path = None
            return
        
        # Obtener ruta del proyecto seleccionado
        row = selected_items[0].row()
        topic_item = self.projects_table.item(row, 0)
        project_path = topic_item.data(Qt.ItemDataRole.UserRole)
        
        if not project_path:
            return
        
        self.selected_project_path = project_path
        self.btn_open.setEnabled(True)
        self.btn_delete.setEnabled(True)
        
        # Cargar y mostrar detalles
        project_data = ProjectManagerV2.load_project(project_path)
        if project_data:
            self.show_project_details(project_data, project_path)
        else:
            self.details_text.setText(" Error cargando detalles del proyecto")
    
    def show_project_details(self, project_data, project_path):
        """Muestra los detalles del proyecto seleccionado"""
        config = project_data.get('config', {})
        progress = project_data.get('progress', {})
        storyboard = project_data.get('storyboard', {})
        
        # Información básica
        details = []
        details.append(" INFORMACIÓN GENERAL")
        details.append("=" * 50)
        details.append(f"Tema: {config.get('topic', 'N/A')}")
        details.append(f"Categoría: {config.get('category', 'N/A')}")
        details.append(f"Plataforma: {config.get('platform', 'N/A')}")
        details.append(f"Duración: {config.get('duration', 'N/A')}s")
        details.append(f"Idioma: {config.get('language', 'N/A')}")
        details.append(f"Estilo: {config.get('style', 'N/A')}")
        details.append("")
        
        # Fecha de creación
        created = project_data.get('created', '')
        if created:
            try:
                dt = datetime.fromisoformat(created)
                created_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                created_str = created
        else:
            created_str = "N/A"
        details.append(f" Creado: {created_str}")
        
        # Tamaño del archivo
        try:
            file_size = os.path.getsize(project_path)
            size_mb = file_size / (1024 * 1024)
            details.append(f" Tamaño: {size_mb:.2f} MB")
        except:
            details.append(" Tamaño: N/A")
        details.append("")
        
        # Progreso
        details.append(" PROGRESO")
        details.append("=" * 50)
        details.append(f" Storyboard: {'Completado' if progress.get('storyboard_done') else 'Pendiente'}")
        details.append(f" Imágenes: {'Completado' if progress.get('images_done') else 'Pendiente'}")
        details.append(f" Video Ensamblado: {'Completado' if progress.get('video_assembled') else 'Pendiente'}")
        details.append(f" Publicado: {'Completado' if progress.get('published') else 'Pendiente'}")
        details.append("")
        
        # Storyboard
        segments = storyboard.get('segments', [])
        if segments:
            details.append(" STORYBOARD")
            details.append("=" * 50)
            details.append(f"Segmentos: {len(segments)}")
            script = storyboard.get('script', '')
            if script:
                script_preview = script[:200] + "..." if len(script) > 200 else script
                details.append(f"Script (preview): {script_preview}")
            audio_path = storyboard.get('audio_path', '')
            if audio_path:
                exists = "" if os.path.exists(audio_path) else ""
                details.append(f"Audio: {exists} {audio_path}")
            details.append("")
        
        # Recursos
        details.append(" RECURSOS")
        details.append("=" * 50)
        thumbnail_path = project_data.get('thumbnail_path')
        if thumbnail_path:
            exists = "" if os.path.exists(thumbnail_path) else ""
            details.append(f"Thumbnail: {exists} {thumbnail_path}")
        else:
            details.append("Thumbnail: No guardado")
        
        music_path = project_data.get('music_path')
        if music_path:
            exists = "" if os.path.exists(music_path) else ""
            details.append(f"Música: {exists} {music_path}")
        else:
            details.append("Música: No seleccionada")
        
        details.append("")
        details.append(f" Ubicación: {project_path}")
        
        self.details_text.setText("\n".join(details))
    
    def delete_selected_project(self):
        """Elimina el proyecto seleccionado"""
        if not self.selected_project_path:
            return
        
        reply = QMessageBox.question(
            self,
            "Eliminar Proyecto",
            f"¿Estás seguro de que deseas eliminar este proyecto?\n\n"
            f"Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Usar el nuevo sistema que elimina toda la carpeta del proyecto
                success = ProjectManagerV2.delete_project(self.selected_project_path)
                if success:
                    QMessageBox.information(self, "Éxito", "Proyecto eliminado exitosamente")
                    self.refresh_projects_list()
                    self.selected_project_path = None
                    self.btn_open.setEnabled(False)
                    self.btn_delete.setEnabled(False)
                    self.details_text.clear()
                else:
                    QMessageBox.critical(self, "Error", "No se pudo eliminar el proyecto")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo eliminar el proyecto:\n\n{str(e)}")
    
    def get_selected_project_path(self):
        """Retorna la ruta del proyecto seleccionado"""
        return self.selected_project_path









