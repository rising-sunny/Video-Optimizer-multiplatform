# api_status_dialog.py
"""
Diálogo para mostrar el estado detallado de todas las APIs
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QGroupBox, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

try:
    from api_status_checker import APIStatusChecker
    API_STATUS_CHECKER_AVAILABLE = True
except ImportError:
    APIStatusChecker = None
    API_STATUS_CHECKER_AVAILABLE = False


class APIStatusWorker(QThread):
    """Worker para verificar APIs en un thread separado"""
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str)
    
    def run(self):
        if not API_STATUS_CHECKER_AVAILABLE or not APIStatusChecker:
            self.finished.emit({})
            return
        
        checker = APIStatusChecker()
        results = {}
        
        # Mapeo de nombres de API a nombres de métodos.
        api_method_map = {
            "Recraft AI": "check_recraft",
            "Openverse (Gratis)": "check_bing_images",
            "Wikimedia": "check_wikimedia",
            "Google Gemini": "check_gemini",
            "Groq": "check_groq",
            "Perplexity": "check_perplexity",
            "OpenAI": "check_openai",
            "xAI Grok": "check_grok",
            "ElevenLabs": "check_elevenlabs",
            "Jamendo": "check_jamendo",
        }
        
        for api_name, method_name in api_method_map.items():
            self.progress.emit(f"Verificando {api_name}...")
            try:
                if hasattr(checker, method_name):
                    method = getattr(checker, method_name)
                    results[api_name] = method()
                else:
                    results[api_name] = {
                        "status": "error",
                        "message": f"Método '{method_name}' no encontrado en checker",
                        "credits": None,
                        "usage": None,
                        "account": None
                    }
            except Exception as e:
                results[api_name] = {
                    "status": "error",
                    "message": f"Excepción al verificar: {type(e).__name__}: {str(e)[:80]}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
        
        self.finished.emit(results)


class APIStatusDialog(QDialog):
    """Diálogo que muestra el estado de todas las APIs"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(" Estado de APIs")
        self.setMinimumSize(900, 700)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
            }
            QLabel {
                color: #ffffff;
            }
            QGroupBox {
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #0d7377;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0e8a8f;
            }
            QTableWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                gridline-color: #3d3d3d;
                alternate-background-color: #252525;
            }
            QTableWidget::item {
                background-color: #2d2d2d;
                color: #ffffff;
                padding: 4px;
            }
            QTableWidget::item:alternate {
                background-color: #252525;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #ffffff;
                padding: 8px;
                border: none;
            }
        """)
        
        self.results = {}
        self.worker = None
        
        self.setup_ui()
        self.start_checking()
    
    def setup_ui(self):
        """Crea la interfaz del diálogo"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Título
        title = QLabel(" Estado de APIs y Créditos")
        title.setStyleSheet("font-size: 18pt; font-weight: bold; color: #0d7377;")
        layout.addWidget(title)
        
        # Barra de progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_label = QLabel("Verificando APIs...")
        self.progress_label.setStyleSheet("color: #a0a0a0;")
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        
        # Tabla de resultados
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "API", "Estado", "Créditos", "Uso", "Cuenta"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Configurar colores alternos oscuros
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                alternate-background-color: #252525;
            }
            QTableWidget::item {
                color: #ffffff;
            }
            QTableWidget::item:selected {
                background-color: #0d7377;
                color: #ffffff;
            }
        """)
        layout.addWidget(self.table)
        
        # Botones
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        refresh_btn = QPushButton(" Actualizar")
        refresh_btn.clicked.connect(self.start_checking)
        button_layout.addWidget(refresh_btn)
        
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def start_checking(self):
        """Inicia la verificación de APIs"""
        if not API_STATUS_CHECKER_AVAILABLE or not APIStatusChecker:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", "Módulo api_status_checker no disponible")
            return
        
        self.progress_bar.show()
        self.progress_label.setText("Verificando APIs...")
        self.table.setRowCount(0)
        
        # Crear worker
        self.worker = APIStatusWorker()
        self.worker.progress.connect(self.progress_label.setText)
        self.worker.finished.connect(self.on_checking_finished)
        self.worker.start()
    
    def on_checking_finished(self, results):
        """Se llama cuando termina la verificación"""
        self.progress_bar.hide()
        self.progress_label.setText(f" Verificación completada - {len(results)} APIs verificadas")
        self.results = results
        
        # Llenar tabla
        self.table.setRowCount(len(results))
        
        row = 0
        for api_name, data in sorted(results.items()):
            # API Name
            api_item = QTableWidgetItem(api_name)
            api_item.setFlags(api_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, api_item)
            
            # Estado - Mejorar mensaje con más información
            status = data.get("status", "unknown")
            message = data.get("message", "")
            
            if status == "working":
                status_text = " Funcionando"
                if message and message != "API funcionando":
                    status_text += f" - {message}"
            elif status == "error":
                # Mostrar el mensaje de error real
                error_msg = message if message else "Error desconocido"
                status_text = f" Error: {error_msg[:50]}"
                if len(error_msg) > 50:
                    status_text += "..."
            elif status == "not_configured":
                status_text = "️ No configurada"
                if message:
                    status_text += f" - {message}"
            else:
                status_text = f" {status}"
            
            status_item = QTableWidgetItem(status_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            
            # Color según estado
            if status == "working":
                status_item.setForeground(QColor("#4caf50"))
            elif status == "error":
                status_item.setForeground(QColor("#f44336"))
            else:
                status_item.setForeground(QColor("#ff9800"))
            
            self.table.setItem(row, 1, status_item)
            
            # Créditos - Mejorar mensaje
            credits = data.get("credits", None)
            if credits and credits != "N/A" and credits != "No disponible":
                credits_text = str(credits)
            elif status == "not_configured":
                credits_text = "Configurar API Key en .env"
            elif status == "error":
                credits_text = "No disponible (ver error)"
            else:
                credits_text = "No disponible"
            
            credits_item = QTableWidgetItem(credits_text)
            credits_item.setFlags(credits_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if status == "not_configured":
                credits_item.setForeground(QColor("#ff9800"))
            elif status == "error":
                credits_item.setForeground(QColor("#f44336"))
            self.table.setItem(row, 2, credits_item)
            
            # Uso - Mejorar mensaje
            usage = data.get("usage", None)
            if usage and usage != "N/A" and usage != "No disponible":
                usage_text = str(usage)
            elif status == "not_configured":
                usage_text = "Configurar API Key primero"
            elif status == "error":
                usage_text = "No disponible (ver error)"
            else:
                usage_text = "No disponible en API"
            
            usage_item = QTableWidgetItem(usage_text)
            usage_item.setFlags(usage_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if status == "not_configured":
                usage_item.setForeground(QColor("#ff9800"))
            elif status == "error":
                usage_item.setForeground(QColor("#f44336"))
            self.table.setItem(row, 3, usage_item)
            
            # Cuenta - Mejorar mensaje
            account = data.get("account", None)
            if account and account != "N/A" and account != "No disponible":
                account_text = str(account)
            elif status == "not_configured":
                account_text = "Configurar API Key primero"
            elif status == "error":
                account_text = "No disponible (ver error)"
            else:
                account_text = "No disponible"
            
            account_item = QTableWidgetItem(account_text)
            account_item.setFlags(account_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if status == "not_configured":
                account_item.setForeground(QColor("#ff9800"))
            elif status == "error":
                account_item.setForeground(QColor("#f44336"))
            self.table.setItem(row, 4, account_item)
            
            row += 1
        
        # Ajustar altura de filas
        self.table.resizeRowsToContents()
