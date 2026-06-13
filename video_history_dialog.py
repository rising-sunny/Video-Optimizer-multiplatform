# video_history_dialog.py
"""
Diálogo para ver el historial de videos generados y generar shorts trailers.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QGroupBox, QTextEdit,
    QProgressBar, QSplitter, QWidget, QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon
from pathlib import Path
import json
from datetime import datetime


class TeaserGenerationWorker(QThread):
    """Worker para generar shorts teasers en segundo plano"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, generator, long_video_data, language='es', voice_id=None):
        super().__init__()
        self.generator = generator
        self.long_video_data = long_video_data
        self.language = language
        self.voice_id = voice_id
    
    def run(self):
        try:
            self.progress.emit(" Generando short teaser...")
            
            # Intentar obtener storyboard de los metadatos
            metadata_str = self.long_video_data.get('metadata', '{}')
            try:
                metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
            except:
                metadata = {}
            
            # Construir storyboard básico
            storyboard = {
                'topic': self.long_video_data.get('topic', 'Video'),
                'category': self.long_video_data.get('category', 'General'),
                'script': metadata.get('script', ''),
                'segments': metadata.get('segments', [])
            }
            
            # Si no hay script en metadatos, intentar leerlo del archivo de video
            if not storyboard['script']:
                video_path = Path(self.long_video_data.get('video_path', ''))
                if video_path.exists():
                    # Buscar archivo de script asociado (si existe)
                    script_path = video_path.parent / f"{video_path.stem}_script.txt"
                    if script_path.exists():
                        storyboard['script'] = script_path.read_text(encoding='utf-8')
            
            # Si aún no hay script, usar un script genérico basado en el título
            if not storyboard['script']:
                title = self.long_video_data.get('title', 'Video')
                storyboard['script'] = f"Este es un video sobre {title}. Descubre más detalles en el video completo."
            
            # Generar teaser
            voice_rate = storyboard.get('voice_rate', '+0%')
            result = self.generator.generate_short_teaser_from_long_video(
                long_video_storyboard=storyboard,
                language=self.language,
                voice_id=self.voice_id,
                disable_wikimedia=False,
                rate=voice_rate
            )
            
            if result:
                self.finished.emit(result)
            else:
                self.error.emit("No se pudo generar el teaser")
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")


class VideoHistoryDialog(QDialog):
    """Diálogo para ver historial de videos y generar teasers"""
    
    def __init__(self, parent=None, generator=None):
        super().__init__(parent)
        self.generator = generator
        self.setWindowTitle(" Historial de Videos - Gestión de Monetización")
        self.setMinimumSize(1000, 700)
        
        # Cargar registro
        try:
            from video_registry import VideoRegistry
            self.registry = VideoRegistry()
        except ImportError:
            QMessageBox.critical(self, "Error", "No se pudo cargar el sistema de registro de videos.")
            self.reject()
            return
        
        self.init_ui()
        self.load_videos()
        self.load_statistics()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Estadísticas en la parte superior
        stats_group = QGroupBox(" Estadísticas de Monetización")
        stats_layout = QVBoxLayout(stats_group)
        
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(120)
        self.stats_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #14a085;
                font-weight: bold;
                font-size: 10pt;
            }
        """)
        stats_layout.addWidget(self.stats_text)
        
        layout.addWidget(stats_group)
        
        # Tabs para diferentes vistas
        tabs = QTabWidget()
        
        # Tab 1: Todos los videos
        all_videos_tab = QWidget()
        all_videos_layout = QVBoxLayout(all_videos_tab)
        
        all_videos_layout.addWidget(QLabel(" Todos los Videos Generados"))
        
        self.videos_table = QTableWidget()
        self.videos_table.setColumnCount(8)
        self.videos_table.setHorizontalHeaderLabels([
            "ID", "Título", "Tipo", "Plataforma", "Duración", "Categoría", "Fecha", "Estado"
        ])
        self.videos_table.horizontalHeader().setStretchLastSection(True)
        self.videos_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.videos_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.videos_table.doubleClicked.connect(self.on_video_double_clicked)
        
        all_videos_layout.addWidget(self.videos_table)
        
        tabs.addTab(all_videos_tab, " Todos los Videos")
        
        # Tab 2: Videos largos sin teasers
        long_videos_tab = QWidget()
        long_videos_layout = QVBoxLayout(long_videos_tab)
        
        long_videos_layout.addWidget(QLabel(" Videos Largos Sin Shorts Trailers"))
        
        self.long_videos_table = QTableWidget()
        self.long_videos_table.setColumnCount(7)
        self.long_videos_table.setHorizontalHeaderLabels([
            "ID", "Título", "Duración", "Categoría", "Fecha", "Ruta", "Acción"
        ])
        self.long_videos_table.horizontalHeader().setStretchLastSection(True)
        self.long_videos_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.long_videos_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        long_videos_layout.addWidget(self.long_videos_table)
        
        tabs.addTab(long_videos_tab, " Generar Trailers")
        
        layout.addWidget(tabs)
        
        # Botones de acción
        buttons_layout = QHBoxLayout()
        
        self.btn_refresh = QPushButton(" Actualizar")
        self.btn_refresh.clicked.connect(self.load_videos)
        buttons_layout.addWidget(self.btn_refresh)
        
        self.btn_open_folder = QPushButton(" Abrir Carpeta de Videos")
        self.btn_open_folder.clicked.connect(self.open_videos_folder)
        buttons_layout.addWidget(self.btn_open_folder)
        
        buttons_layout.addStretch()
        
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.clicked.connect(self.accept)
        buttons_layout.addWidget(self.btn_close)
        
        layout.addLayout(buttons_layout)
    
    def load_statistics(self):
        """Carga y muestra estadísticas de monetización"""
        try:
            stats = self.registry.get_statistics()
            
            text = f"""
 ESTADÍSTICAS DE MONETIZACIÓN
            
Total de Videos: {stats['total_videos']} | Videos Largos: {stats['long_videos']} | Shorts/Teasers: {stats['shorts']}
Videos con Trailers: {stats['videos_with_teasers']} / {stats['long_videos']}

️ HORAS DE VISUALIZACIÓN:
Total Acumulado: {stats['total_watch_hours']:.2f} horas
Horas Necesarias: {stats['hours_needed_for_monetization']:.0f} horas
Horas Restantes: {stats['hours_remaining']:.2f} horas

 PROGRESO: {stats['monetization_progress']:.1f}% completado
            """.strip()
            
            self.stats_text.setPlainText(text)
        except Exception as e:
            self.stats_text.setPlainText(f"Error cargando estadísticas: {e}")
    
    def load_videos(self):
        """Carga la lista de videos"""
        try:
            # Cargar todos los videos
            all_videos = self.registry.get_all_videos(limit=100)
            self.videos_table.setRowCount(len(all_videos))
            
            for i, video in enumerate(all_videos):
                self.videos_table.setItem(i, 0, QTableWidgetItem(video.get('video_id', '')))
                self.videos_table.setItem(i, 1, QTableWidgetItem(video.get('title', 'Sin título')))
                self.videos_table.setItem(i, 2, QTableWidgetItem(video.get('video_type', '')))
                self.videos_table.setItem(i, 3, QTableWidgetItem(video.get('platform', '')))
                
                duration = video.get('duration')
                duration_str = f"{duration:.1f}s" if duration else "N/A"
                self.videos_table.setItem(i, 4, QTableWidgetItem(duration_str))
                
                self.videos_table.setItem(i, 5, QTableWidgetItem(video.get('category', '')))
                
                created_at = video.get('created_at', '')
                if created_at:
                    try:
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        date_str = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        date_str = str(created_at)
                else:
                    date_str = "N/A"
                self.videos_table.setItem(i, 6, QTableWidgetItem(date_str))
                
                self.videos_table.setItem(i, 7, QTableWidgetItem(video.get('status', 'generated')))
            
            self.videos_table.resizeColumnsToContents()
            
            # Cargar videos largos sin teasers
            long_videos = self.registry.get_long_videos_without_teasers()
            self.long_videos_table.setRowCount(len(long_videos))
            
            for i, video in enumerate(long_videos):
                self.long_videos_table.setItem(i, 0, QTableWidgetItem(video.get('video_id', '')))
                self.long_videos_table.setItem(i, 1, QTableWidgetItem(video.get('title', 'Sin título')))
                
                duration = video.get('duration')
                duration_str = f"{duration:.1f}s" if duration else "N/A"
                self.long_videos_table.setItem(i, 2, QTableWidgetItem(duration_str))
                
                self.long_videos_table.setItem(i, 3, QTableWidgetItem(video.get('category', '')))
                
                created_at = video.get('created_at', '')
                if created_at:
                    try:
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        date_str = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        date_str = str(created_at)
                else:
                    date_str = "N/A"
                self.long_videos_table.setItem(i, 4, QTableWidgetItem(date_str))
                
                video_path = video.get('video_path', '')
                try:
                    path_display = Path(video_path).name if video_path else "N/A"
                except:
                    path_display = "N/A"
                self.long_videos_table.setItem(i, 5, QTableWidgetItem(path_display))
                
                # Botón para generar teaser
                btn_generate = QPushButton(" Generar Teaser")
                btn_generate.clicked.connect(lambda checked, v=video: self.generate_teaser_for_video(v))
                self.long_videos_table.setCellWidget(i, 6, btn_generate)
            
            self.long_videos_table.resizeColumnsToContents()
            
            self.load_statistics()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error cargando videos: {e}")
    
    def generate_teaser_for_video(self, video_data):
        """Genera un short teaser para un video largo"""
        if not self.generator:
            QMessageBox.warning(self, "Error", "El generador de videos no está disponible.")
            return
        
        reply = QMessageBox.question(
            self,
            "Generar Short Teaser",
            f"¿Deseas generar un short teaser (30-60s) para el video:\n\n{video_data.get('title', 'Sin título')}?\n\n"
            "El teaser se generará en formato vertical 9:16 y se registrará automáticamente.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Crear worker para generar teaser
        worker = TeaserGenerationWorker(
            generator=self.generator,
            long_video_data=video_data,
            language=video_data.get('language', 'es')
        )
        
        worker.finished.connect(lambda result: self.on_teaser_generated(result, video_data.get('video_id')))
        worker.error.connect(lambda error: QMessageBox.critical(self, "Error", f"Error generando teaser: {error}"))
        worker.progress.connect(lambda msg: self.parent().log(msg) if hasattr(self.parent(), 'log') else None)
        
        worker.start()
        
        QMessageBox.information(
            self,
            "Generando Teaser",
            "El short teaser se está generando en segundo plano.\n"
            "Recibirás una notificación cuando esté listo."
        )
    
    def on_teaser_generated(self, result, parent_video_id):
        """Callback cuando se genera un teaser"""
        try:
            # Registrar el teaser
            video_id = self.registry.register_video(
                video_path=result['video_path'],
                video_type='teaser',
                title=result.get('title', 'Teaser'),
                topic=result.get('topic', ''),
                category=result.get('category', ''),
                platform='youtube_short',
                duration=result.get('duration'),
                resolution='1080x1920',
                language=result.get('language', 'es'),
                parent_video_id=parent_video_id,
                relation_type='teaser',
                metadata={'is_teaser': True}
            )
            
            QMessageBox.information(
                self,
                " Teaser Generado",
                f"Short teaser generado exitosamente:\n\n{result['video_path']}\n\n"
                f"ID: {video_id}\n\n"
                "El teaser ha sido registrado y vinculado al video largo."
            )
            
            # Recargar lista
            self.load_videos()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error registrando teaser: {e}")
    
    def on_video_double_clicked(self, index):
        """Abre información detallada del video al hacer doble clic"""
        row = index.row()
        video_id = self.videos_table.item(row, 0).text()
        
        video_data = self.registry.get_video(video_id)
        if not video_data:
            return
        
        # Mostrar información detallada
        info_text = f"""
VIDEO ID: {video_data.get('video_id')}
Título: {video_data.get('title', 'Sin título')}
Tipo: {video_data.get('video_type')}
Plataforma: {video_data.get('platform')}
Tema: {video_data.get('topic', 'N/A')}
Categoría: {video_data.get('category', 'N/A')}
Duración: {video_data.get('duration', 'N/A')} segundos
Resolución: {video_data.get('resolution', 'N/A')}
Idioma: {video_data.get('language', 'N/A')}
Ruta: {video_data.get('video_path', 'N/A')}
Estado: {video_data.get('status', 'generated')}
Vistas: {video_data.get('views', 0)}
Horas de Visualización: {video_data.get('watch_hours', 0.0):.2f}
Fecha: {video_data.get('created_at', 'N/A')}
        """.strip()
        
        QMessageBox.information(self, "Información del Video", info_text)
    
    def open_videos_folder(self):
        """Abre la carpeta de videos en el explorador"""
        import subprocess
        import platform as plat
        
        videos_dir = Path("auto_videos/output")
        if not videos_dir.exists():
            QMessageBox.warning(self, "Carpeta no encontrada", f"La carpeta {videos_dir} no existe.")
            return
        
        try:
            if plat.system() == "Windows":
                subprocess.Popen(f'explorer "{videos_dir.absolute()}"')
            elif plat.system() == "Darwin":  # macOS
                subprocess.Popen(["open", str(videos_dir.absolute())])
            else:  # Linux
                subprocess.Popen(["xdg-open", str(videos_dir.absolute())])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir la carpeta: {e}")

