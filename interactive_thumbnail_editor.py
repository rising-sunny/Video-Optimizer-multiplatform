# interactive_thumbnail_editor.py
"""
Editor Interactivo de Thumbnails con Drag & Resize
-------------------------------------------------
Permite editar la posición y tamaño del título en thumbnails usando el mouse.
Características:
- Arrastrar título con mouse
- Redimensionar título
- Guías de alineación punteadas (centro horizontal/vertical)
- Vista previa en tiempo real
- Estilos de texto personalizables
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QComboBox, QSlider, QGroupBox, QColorDialog, QFontDialog,
    QSpinBox, QCheckBox, QFrame, QSizePolicy, QLineEdit
)
from PyQt6.QtCore import (
    Qt, QRect, QPoint, QSize, pyqtSignal, QTimer, QPointF
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPixmap, QMouseEvent,
    QPolygonF, QPainterPath, QLinearGradient, QRadialGradient
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import json
from pathlib import Path
import math


class DraggableTextItem:
    """Representa un elemento de texto arrastrable y redimensionable"""
    
    def __init__(self, text="", x=100, y=100, font_size=48, color=(255, 255, 255)):
        self.text = text
        self.x = x
        self.y = y
        self.font_size = font_size
        self.color = color
        self.width = 200  # Ancho inicial
        self.height = 60   # Alto inicial
        self.rotation = 0
        self.shadow_offset = 3
        self.shadow_color = (0, 0, 0, 180)
        self.outline_width = 2
        self.outline_color = (0, 0, 0)
        
    def get_rect(self):
        """Obtiene el rectángulo del elemento"""
        return QRect(self.x, self.y, self.width, self.height)
    
    def contains_point(self, point):
        """Verifica si un punto está dentro del elemento"""
        return self.get_rect().contains(point)
    
    def get_resize_handle(self, point):
        """Obtiene el handle de redimensionamiento en el punto dado"""
        rect = self.get_rect()
        handle_size = 8
        
        handles = {
            'top_left': QRect(rect.left(), rect.top(), handle_size, handle_size),
            'top_right': QRect(rect.right() - handle_size, rect.top(), handle_size, handle_size),
            'bottom_left': QRect(rect.left(), rect.bottom() - handle_size, handle_size, handle_size),
            'bottom_right': QRect(rect.right() - handle_size, rect.bottom() - handle_size, handle_size, handle_size),
            'top': QRect(rect.center().x() - handle_size//2, rect.top(), handle_size, handle_size),
            'bottom': QRect(rect.center().x() - handle_size//2, rect.bottom() - handle_size, handle_size, handle_size),
            'left': QRect(rect.left(), rect.center().y() - handle_size//2, handle_size, handle_size),
            'right': QRect(rect.right() - handle_size, rect.center().y() - handle_size//2, handle_size, handle_size),
        }
        
        for handle_name, handle_rect in handles.items():
            if handle_rect.contains(point):
                return handle_name
        return None
    
    def resize(self, handle, delta):
        """Redimensiona el elemento según el handle y el delta"""
        if handle in ['top_left']:
            self.x += delta.x()
            self.y += delta.y()
            self.width -= delta.x()
            self.height -= delta.y()
        elif handle in ['top_right']:
            self.y += delta.y()
            self.width += delta.x()
            self.height -= delta.y()
        elif handle in ['bottom_left']:
            self.x += delta.x()
            self.width -= delta.x()
            self.height += delta.y()
        elif handle in ['bottom_right']:
            self.width += delta.x()
            self.height += delta.y()
        elif handle in ['top']:
            self.y += delta.y()
            self.height -= delta.y()
        elif handle in ['bottom']:
            self.height += delta.y()
        elif handle in ['left']:
            self.x += delta.x()
            self.width -= delta.x()
        elif handle in ['right']:
            self.width += delta.x()
        
        # Tamaño mínimo
        self.width = max(50, self.width)
        self.height = max(20, self.height)


class ThumbnailCanvas(QWidget):
    """Canvas interactivo para editar thumbnails"""
    
    # Señales
    text_changed = pyqtSignal(str)
    position_changed = pyqtSignal(int, int)
    size_changed = pyqtSignal(int, int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 450)
        self.setMouseTracking(True)
        
        # Imagen de fondo
        self.background_image = None
        self.background_pixmap = None
        
        # Elementos de texto
        self.text_items = []
        self.selected_item = None
        self.dragging = False
        self.resizing = False
        self.resize_handle = None
        self.drag_start_pos = None
        self.item_start_pos = None
        self.item_start_size = None
        
        # Guías de alineación
        self.show_guides = True
        self.snap_to_guides = True
        self.guide_threshold = 10
        
        # Estilos
        self.setStyleSheet("background-color: #2a2a2a; border: 2px solid #444;")
        
        # Timer para preview
        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self.update_preview)
        self.preview_timer.setSingleShot(True)
        
    def set_background_image(self, image_path):
        """Establece la imagen de fondo"""
        try:
            self.background_image = Image.open(image_path)
            self.update_background_pixmap()
            self.update()
        except Exception as e:
            print(f"Error cargando imagen: {e}")
    
    def update_background_pixmap(self):
        """Actualiza el pixmap de fondo"""
        if self.background_image:
            # Convertir PIL Image a QPixmap
            img_rgb = self.background_image.convert('RGB')
            w, h = img_rgb.size
            data = img_rgb.tobytes('raw', 'RGB')
            
            qimg = QImage(data, w, h, QImage.Format.Format_RGB888)
            self.background_pixmap = QPixmap.fromImage(qimg)
    
    def add_text_item(self, text="Título"):
        """Añade un nuevo elemento de texto"""
        item = DraggableTextItem(
            text=text,
            x=self.width() // 2 - 100,
            y=self.height() // 2 - 30,
            font_size=48,
            color=(255, 255, 0)  # Amarillo por defecto
        )
        self.text_items.append(item)
        self.selected_item = item
        self.update()
        return item
    
    def get_center_guides(self):
        """Obtiene las líneas guía del centro"""
        if not self.background_pixmap:
            return None, None
        
        center_x = self.width() // 2
        center_y = self.height() // 2
        
        return center_x, center_y
    
    def snap_to_guides_if_enabled(self, pos):
        """Ajusta posición a las guías si está habilitado"""
        if not self.snap_to_guides or not self.selected_item:
            return pos
        
        center_x, center_y = self.get_center_guides()
        if center_x is None:
            return pos
        
        # Snap horizontal
        item_center_x = self.selected_item.x + self.selected_item.width // 2
        if abs(item_center_x - center_x) < self.guide_threshold:
            pos.setX(center_x - self.selected_item.width // 2)
        
        # Snap vertical
        item_center_y = self.selected_item.y + self.selected_item.height // 2
        if abs(item_center_y - center_y) < self.guide_threshold:
            pos.setY(center_y - self.selected_item.height // 2)
        
        return pos
    
    def paintEvent(self, event):
        """Evento de pintado"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Fondo
        painter.fillRect(self.rect(), QColor(42, 42, 42))
        
        # Imagen de fondo
        if self.background_pixmap:
            # Escalar imagen para que quepa
            scaled_pixmap = self.background_pixmap.scaled(
                self.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            
            # Centrar imagen
            x = (self.width() - scaled_pixmap.width()) // 2
            y = (self.height() - scaled_pixmap.height()) // 2
            painter.drawPixmap(x, y, scaled_pixmap)
        
        # Dibujar guías
        if self.show_guides:
            self.draw_guides(painter)
        
        # Dibujar elementos de texto
        for item in self.text_items:
            self.draw_text_item(painter, item)
        
        # Dibujar selección y handles
        if self.selected_item:
            self.draw_selection(painter, self.selected_item)
    
    def draw_guides(self, painter):
        """Dibuja las líneas guía"""
        center_x, center_y = self.get_center_guides()
        if center_x is None:
            return
        
        # Configurar estilo de línea punteada
        pen = QPen(QColor(255, 255, 255, 100), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        
        # Línea vertical central
        painter.drawLine(center_x, 0, center_x, self.height())
        
        # Línea horizontal central
        painter.drawLine(0, center_y, self.width(), center_y)
        
        # Marcar centro con un círculo pequeño
        painter.setBrush(QBrush(QColor(255, 255, 255, 150)))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawEllipse(center_x - 3, center_y - 3, 6, 6)
    
    def draw_text_item(self, painter, item):
        """Dibuja un elemento de texto"""
        # Configurar fuente
        font = QFont("Arial", item.font_size, QFont.Weight.Bold)
        painter.setFont(font)
        
        # Sombra
        if item.shadow_offset > 0:
            shadow_color = QColor(*item.shadow_color)
            painter.setPen(shadow_color)
            shadow_rect = item.get_rect().translated(item.shadow_offset, item.shadow_offset)
            painter.drawText(shadow_rect, Qt.AlignmentFlag.AlignCenter, item.text)
        
        # Contorno
        if item.outline_width > 0:
            outline_color = QColor(*item.outline_color)
            painter.setPen(QPen(outline_color, item.outline_width))
            painter.drawText(item.get_rect(), Qt.AlignmentFlag.AlignCenter, item.text)
        
        # Texto principal
        text_color = QColor(*item.color)
        painter.setPen(text_color)
        painter.drawText(item.get_rect(), Qt.AlignmentFlag.AlignCenter, item.text)
    
    def draw_selection(self, painter, item):
        """Dibuja la selección y handles de redimensionamiento"""
        # Rectángulo de selección
        pen = QPen(QColor(100, 200, 255), 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(Qt.GlobalColor.transparent))
        painter.drawRect(item.get_rect())
        
        # Handles de redimensionamiento
        handle_color = QColor(100, 200, 255)
        painter.setBrush(QBrush(handle_color))
        painter.setPen(QPen(handle_color.darker(), 1))
        
        rect = item.get_rect()
        handle_size = 8
        
        handles = [
            (rect.left(), rect.top()),  # top_left
            (rect.right() - handle_size, rect.top()),  # top_right
            (rect.left(), rect.bottom() - handle_size),  # bottom_left
            (rect.right() - handle_size, rect.bottom() - handle_size),  # bottom_right
            (rect.center().x() - handle_size//2, rect.top()),  # top
            (rect.center().x() - handle_size//2, rect.bottom() - handle_size),  # bottom
            (rect.left(), rect.center().y() - handle_size//2),  # left
            (rect.right() - handle_size, rect.center().y() - handle_size//2),  # right
        ]
        
        for x, y in handles:
            painter.drawRect(x, y, handle_size, handle_size)
    
    def mousePressEvent(self, event):
        """Evento de presión del mouse"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            
            # Verificar si se hace clic en algún elemento
            for item in reversed(self.text_items):  # Reverso para priorizar elementos superiores
                if item.contains_point(pos):
                    self.selected_item = item
                    
                    # Verificar si se hace clic en un handle de redimensionamiento
                    handle = item.get_resize_handle(pos)
                    if handle:
                        self.resizing = True
                        self.resize_handle = handle
                        self.item_start_size = (item.width, item.height)
                    else:
                        self.dragging = True
                        self.item_start_pos = (item.x, item.y)
                    
                    self.drag_start_pos = pos
                    self.update()
                    return
            
            # Si no se hizo clic en ningún elemento, deseleccionar
            self.selected_item = None
            self.update()
    
    def mouseMoveEvent(self, event):
        """Evento de movimiento del mouse"""
        pos = event.position().toPoint()
        
        # Actualizar cursor
        if self.selected_item:
            handle = self.selected_item.get_resize_handle(pos)
            if handle:
                # Cursor de redimensionamiento
                cursors = {
                    'top_left': Qt.CursorShape.SizeFDiagCursor,
                    'top_right': Qt.CursorShape.SizeBDiagCursor,
                    'bottom_left': Qt.CursorShape.SizeBDiagCursor,
                    'bottom_right': Qt.CursorShape.SizeFDiagCursor,
                    'top': Qt.CursorShape.SizeVerCursor,
                    'bottom': Qt.CursorShape.SizeVerCursor,
                    'left': Qt.CursorShape.SizeHorCursor,
                    'right': Qt.CursorShape.SizeHorCursor,
                }
                self.setCursor(cursors.get(handle, Qt.CursorShape.ArrowCursor))
            elif self.selected_item.contains_point(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        
        # Procesar dragging
        if self.dragging and self.selected_item and self.drag_start_pos:
            delta = pos - self.drag_start_pos
            new_pos = QPoint(self.item_start_pos[0] + delta.x(), self.item_start_pos[1] + delta.y())
            
            # Snap a guías si está habilitado
            new_pos = self.snap_to_guides_if_enabled(new_pos)
            
            self.selected_item.x = new_pos.x()
            self.selected_item.y = new_pos.y()
            
            self.position_changed.emit(self.selected_item.x, self.selected_item.y)
            self.update()
        
        # Procesar resizing
        elif self.resizing and self.selected_item and self.drag_start_pos:
            delta = pos - self.drag_start_pos
            self.selected_item.resize(self.resize_handle, delta)
            
            self.size_changed.emit(self.selected_item.width, self.selected_item.height)
            self.update()
    
    def mouseReleaseEvent(self, event):
        """Evento de liberación del mouse"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.resizing = False
            self.resize_handle = None
            self.drag_start_pos = None
            self.item_start_pos = None
            self.item_start_size = None
    
    def update_preview(self):
        """Actualiza el preview (llamado por timer)"""
        self.update()
    
    def get_thumbnail_image(self):
        """Genera la imagen final del thumbnail"""
        if not self.background_image:
            return None
        
        # Crear copia de la imagen de fondo
        final_image = self.background_image.copy()
        draw = ImageDraw.Draw(final_image)
        
        # Calcular escala si la imagen fue redimensionada en el canvas
        if self.background_pixmap:
            canvas_scale_x = self.background_pixmap.width() / self.background_image.width
            canvas_scale_y = self.background_pixmap.height() / self.background_image.height
        else:
            canvas_scale_x = canvas_scale_y = 1.0
        
        # Dibujar elementos de texto
        for item in self.text_items:
            # Escalar coordenadas al tamaño real de la imagen
            real_x = int(item.x / canvas_scale_x)
            real_y = int(item.y / canvas_scale_y)
            real_width = int(item.width / canvas_scale_x)
            real_height = int(item.height / canvas_scale_y)
            real_font_size = int(item.font_size / canvas_scale_x)
            
            # Intentar cargar fuente
            try:
                font_paths = [
                    "C:/Windows/Fonts/impact.ttf",
                    "C:/Windows/Fonts/arialbd.ttf",
                    "C:/Windows/Fonts/ariblk.ttf",
                ]
                font = None
                for font_path in font_paths:
                    try:
                        font = ImageFont.truetype(font_path, real_font_size)
                        break
                    except:
                        continue
                
                if not font:
                    font = ImageFont.load_default()
            
                # Sombra
                if item.shadow_offset > 0:
                    shadow_offset = int(item.shadow_offset / canvas_scale_x)
                    shadow_color = (*item.shadow_color[:3], item.shadow_color[3] if len(item.shadow_color) > 3 else 180)
                    draw.text(
                        (real_x + shadow_offset, real_y + shadow_offset),
                        item.text,
                        font=font,
                        fill=shadow_color,
                        anchor="mm"
                    )
                
                # Texto principal
                text_color = (*item.color, 255) if len(item.color) == 3 else item.color
                draw.text(
                    (real_x + real_width // 2, real_y + real_height // 2),
                    item.text,
                    font=font,
                    fill=text_color,
                    anchor="mm"
                )
            
            except Exception as e:
                print(f"Error dibujando texto: {e}")
        
        return final_image


class InteractiveThumbnailEditor(QWidget):
    """Widget principal del editor interactivo de thumbnails"""
    
    # Señales
    thumbnail_generated = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.current_image_path = None
        
    def setup_ui(self):
        """Configura la interfaz"""
        layout = QVBoxLayout(self)
        
        # Canvas principal
        self.canvas = ThumbnailCanvas()
        layout.addWidget(self.canvas, 1)
        
        # Panel de controles
        controls_panel = self.create_controls_panel()
        layout.addWidget(controls_panel)
        
        # Conectar señales
        self.canvas.position_changed.connect(self.on_position_changed)
        self.canvas.size_changed.connect(self.on_size_changed)
    
    def create_controls_panel(self):
        """Crea el panel de controles"""
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        
        # Controles de texto
        text_group = QGroupBox(" Controles de Texto")
        text_layout = QVBoxLayout(text_group)
        
        # Texto
        text_input_layout = QHBoxLayout()
        text_input_layout.addWidget(QLabel("Texto:"))
        self.text_input = QLineEdit("TÍTULO DEL VIDEO")
        self.text_input.textChanged.connect(self.on_text_changed)
        text_input_layout.addWidget(self.text_input)
        text_layout.addLayout(text_input_layout)
        
        # Tamaño de fuente
        font_size_layout = QHBoxLayout()
        font_size_layout.addWidget(QLabel("Tamaño:"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(12, 200)
        self.font_size_spin.setValue(48)
        self.font_size_spin.valueChanged.connect(self.on_font_size_changed)
        font_size_layout.addWidget(self.font_size_spin)
        font_size_layout.addStretch()
        text_layout.addLayout(font_size_layout)
        
        # Color
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.color_button = QPushButton("")
        self.color_button.clicked.connect(self.choose_color)
        color_layout.addWidget(self.color_button)
        self.color_label = QLabel("#FFFF00")
        color_layout.addWidget(self.color_label)
        color_layout.addStretch()
        text_layout.addLayout(color_layout)
        
        # Opciones de guía
        guides_group = QGroupBox(" Guías de Alineación")
        guides_layout = QVBoxLayout(guides_group)
        
        self.show_guides_check = QCheckBox("Mostrar guías punteadas")
        self.show_guides_check.setChecked(True)
        self.show_guides_check.toggled.connect(self.on_guides_toggled)
        guides_layout.addWidget(self.show_guides_check)
        
        self.snap_guides_check = QCheckBox("Ajustar automático a guías")
        self.snap_guides_check.setChecked(True)
        self.snap_guides_check.toggled.connect(self.on_snap_toggled)
        guides_layout.addWidget(self.snap_guides_check)
        
        # Botones de acción
        actions_layout = QHBoxLayout()
        
        btn_add_text = QPushButton(" Añadir Texto")
        btn_add_text.clicked.connect(self.add_text_item)
        actions_layout.addWidget(btn_add_text)
        
        btn_delete_text = QPushButton("️ Eliminar Seleccionado")
        btn_delete_text.clicked.connect(self.delete_selected_text)
        actions_layout.addWidget(btn_delete_text)
        
        btn_generate = QPushButton(" Generar Thumbnail Final")
        btn_generate.clicked.connect(self.generate_final_thumbnail)
        btn_generate.setObjectName("accent")
        actions_layout.addWidget(btn_generate)
        
        text_layout.addLayout(actions_layout)
        
        layout.addWidget(text_group)
        layout.addWidget(guides_group)
        
        return panel
    
    def set_background_image(self, image_path):
        """Establece la imagen de fondo"""
        self.current_image_path = image_path
        self.canvas.set_background_image(image_path)
        
        # Añadir primer texto si no hay elementos
        if not self.canvas.text_items:
            self.add_text_item()
    
    def add_text_item(self):
        """Añade un nuevo elemento de texto"""
        text = self.text_input.text() or "TÍTULO"
        item = self.canvas.add_text_item(text)
        
        # Actualizar controles con las propiedades del nuevo elemento
        self.font_size_spin.setValue(item.font_size)
        self.update_color_display(item.color)
    
    def delete_selected_text(self):
        """Elimina el elemento de texto seleccionado"""
        if self.canvas.selected_item and self.canvas.selected_item in self.canvas.text_items:
            self.canvas.text_items.remove(self.canvas.selected_item)
            self.canvas.selected_item = None
            self.canvas.update()
    
    def on_text_changed(self, text):
        """Manejador de cambio de texto"""
        if self.canvas.selected_item:
            self.canvas.selected_item.text = text
            self.canvas.update()
    
    def on_font_size_changed(self, size):
        """Manejador de cambio de tamaño de fuente"""
        if self.canvas.selected_item:
            self.canvas.selected_item.font_size = size
            self.canvas.update()
    
    def on_position_changed(self, x, y):
        """Manejador de cambio de posición"""
        # Actualizar UI si es necesario
        pass
    
    def on_size_changed(self, width, height):
        """Manejador de cambio de tamaño"""
        # Actualizar UI si es necesario
        pass
    
    def choose_color(self):
        """Abre el diálogo de selección de color"""
        color = QColorDialog.getColor()
        if color.isValid():
            rgb = (color.red(), color.green(), color.blue())
            if self.canvas.selected_item:
                self.canvas.selected_item.color = rgb
            self.update_color_display(rgb)
            self.canvas.update()
    
    def update_color_display(self, color):
        """Actualiza la visualización del color"""
        if isinstance(color, (tuple, list)) and len(color) >= 3:
            hex_color = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}".upper()
            self.color_label.setText(hex_color)
            self.color_button.setStyleSheet(f"background-color: {hex_color};")
    
    def on_guides_toggled(self, checked):
        """Manejador de toggle de guías"""
        self.canvas.show_guides = checked
        self.canvas.update()
    
    def on_snap_toggled(self, checked):
        """Manejador de toggle de snap"""
        self.canvas.snap_to_guides = checked
        self.canvas.update()
    
    def generate_final_thumbnail(self):
        """Genera el thumbnail final"""
        if not self.current_image_path:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", "No hay imagen de fondo cargada")
            return
        
        try:
            # Generar imagen final
            final_image = self.canvas.get_thumbnail_image()
            
            if final_image:
                # Guardar imagen
                from pathlib import Path
                import time
                
                output_dir = Path("thumbnails_interactive")
                output_dir.mkdir(exist_ok=True)
                
                timestamp = int(time.time())
                output_path = output_dir / f"interactive_thumbnail_{timestamp}.png"
                
                final_image.save(output_path, "PNG", quality=95)
                
                # Emitir señal
                self.thumbnail_generated.emit(str(output_path))
                
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Éxito", f"Thumbnail guardado en:\n{output_path}")
            
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error generando thumbnail: {e}")


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    editor = InteractiveThumbnailEditor()
    editor.setWindowTitle("Editor Interactivo de Thumbnails")
    editor.resize(1000, 700)
    editor.show()
    
    sys.exit(app.exec())
