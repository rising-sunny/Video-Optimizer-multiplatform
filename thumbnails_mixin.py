from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import json
from pathlib import Path
from PIL import Image
import threading
import time
from ui_workers import AnalysisWorker, ResearchWorker, TrendsWorker, SearchWorker
from recraft_style_catalog import RECRAFT_STYLE_OPTIONS

class ThumbnailsMixin:
    def create_thumbnails_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(18)

        # Grupo de configuración
        config_group = QGroupBox("Configuración de miniatura")
        config_layout = QVBoxLayout(config_group)

        # Proveedor de IA/Imágenes
        provider_layout = QHBoxLayout()
        provider_layout.addWidget(QLabel("Proveedor:"))
        self.thumb_provider_combo = QComboBox()
        self.thumb_provider_combo.addItems([
            "Recraft AI"
        ])
        provider_layout.addWidget(self.thumb_provider_combo)
        
        provider_layout.addStretch()
        config_layout.addLayout(provider_layout)

        # Estilo visual (cambia según el proveedor seleccionado)
        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("Estilo:"))
        self.thumb_style_combo = QComboBox()
        
        # Estilos oficiales de Recraft.
        self.recraft_styles = list(RECRAFT_STYLE_OPTIONS)
        # Mantener aliases legacy para rutas antiguas que aun consultan estos atributos.
        self.fal_styles = self.recraft_styles
        self.leonardo_styles = self.recraft_styles
        # Inicializar con estilos de Recraft
        self.thumb_style_combo.addItems(self.recraft_styles)
        style_layout.addWidget(self.thumb_style_combo)
        style_layout.addStretch()
        config_layout.addLayout(style_layout)

        # Opciones de texto overlay
        text_group = QGroupBox("Texto sobre imagen")
        text_layout = QVBoxLayout(text_group)

        self.add_text_overlay_check = QCheckBox("Agregar título sobre la imagen")
        self.add_text_overlay_check.setChecked(True)
        text_layout.addWidget(self.add_text_overlay_check)

        # Idioma del título
        text_lang_layout = QHBoxLayout()
        text_lang_layout.addWidget(QLabel("Idioma del Título:"))
        self.text_lang_combo = QComboBox()
        self.text_lang_combo.addItems(["Español", "English"])
        self.text_lang_combo.setCurrentText("Español")
        text_lang_layout.addWidget(self.text_lang_combo)
        text_lang_layout.addStretch()
        text_layout.addLayout(text_lang_layout)

        text_style_layout = QHBoxLayout()
        text_style_layout.addWidget(QLabel("Estilo de Texto:"))
        self.text_style_combo = QComboBox()
        self.text_style_combo.addItems([
            "Contraste alto", "Claro limpio", "Neón suave", "Rojo intenso"
        ])
        text_style_layout.addWidget(self.text_style_combo)
        text_style_layout.addStretch()
        text_layout.addLayout(text_style_layout)

        config_layout.addWidget(text_group)

        # Botones de generación y carga
        buttons_layout = QHBoxLayout()
        
        self.btn_generate_thumb = QPushButton("Generar miniatura")
        self.btn_generate_thumb.setObjectName("accent")
        self.btn_generate_thumb.clicked.connect(self.generate_thumbnail)
        buttons_layout.addWidget(self.btn_generate_thumb)

        self.btn_super_prompt = QPushButton("Super Prompt (IA externa)")
        self.btn_super_prompt.setToolTip(
            "Genera un prompt optimizado para pegar en Midjourney, DALL-E, Stable Diffusion, etc."
        )
        self.btn_super_prompt.clicked.connect(self.generate_super_prompt_for_external_ai)
        buttons_layout.addWidget(self.btn_super_prompt)

        # Botón para buscar imágenes reales (solo visible cuando se selecciona Openverse (Gratis) o Wikimedia)
        self.btn_search_real_images = QPushButton("Buscar imagen real")
        self.btn_search_real_images.setToolTip("Busca y selecciona una imagen real de Openverse (Gratis) o Wikimedia")
        self.btn_search_real_images.clicked.connect(self.open_real_image_search)
        self.btn_search_real_images.setVisible(False)  # Oculto por defecto
        buttons_layout.addWidget(self.btn_search_real_images)
        
        self.btn_load_thumb = QPushButton("Cargar miniatura")
        self.btn_load_thumb.setToolTip("Carga un thumbnail previamente generado por el script")
        self.btn_load_thumb.clicked.connect(self.load_thumbnail)
        buttons_layout.addWidget(self.btn_load_thumb)
        
        config_layout.addLayout(buttons_layout)
        
        # Conectar cambio de proveedor para mostrar/ocultar botón de búsqueda y actualizar estilos
        self.thumb_provider_combo.currentTextChanged.connect(self.on_thumb_provider_changed)

        layout.addWidget(config_group)
        
        # Preview
        preview_group = QGroupBox("Vista previa")
        preview_layout = QVBoxLayout(preview_group)
        
        self.thumb_preview = QLabel()
        self.thumb_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_preview.setMinimumSize(640, 360)
        self.thumb_preview.setObjectName("thumbPreview")
        self.thumb_preview.setText("La miniatura se mostrará aquí")
        preview_layout.addWidget(self.thumb_preview)
        
        # Botones de acción
        actions_layout = QHBoxLayout()
        
        btn_save = QPushButton("Guardar imagen")
        btn_save.clicked.connect(self.save_thumbnail)
        actions_layout.addWidget(btn_save)
        
        btn_add_text = QPushButton("Agregar texto o logo")
        btn_add_text.clicked.connect(self.add_text_to_thumbnail)
        actions_layout.addWidget(btn_add_text)
        
        btn_interactive_edit = QPushButton("Editor interactivo")
        btn_interactive_edit.clicked.connect(self.open_interactive_thumbnail_editor)
        btn_interactive_edit.setToolTip("Abre el editor interactivo para arrastrar y redimensionar el título")
        actions_layout.addWidget(btn_interactive_edit)
        
        actions_layout.addStretch()
        preview_layout.addLayout(actions_layout)
        
        layout.addWidget(preview_group)
        layout.addStretch()
        
        return tab

    def _load_real_image_as_thumbnail(self, image_path, source):
        """Carga una imagen real seleccionada como thumbnail"""
        try:
            # Redimensionar imagen a tamaño de thumbnail (1280x720 o mantener proporción)
            from PIL import Image
            img = Image.open(image_path)
            
            # Calcular nuevo tamaño manteniendo proporción
            target_size = (1280, 720)
            img.thumbnail(target_size, Image.Resampling.LANCZOS)
            
            # Guardar en directorio de thumbnails
            thumb_dir = Path("thumbnails_real")
            thumb_dir.mkdir(exist_ok=True)
            
            safe_topic = self.topic_input.text().strip()[:30] if self.topic_input.text().strip() else "thumbnail"
            safe_topic = "".join(c for c in safe_topic if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')
            
            raw_path = thumb_dir / f"thumb_{source}_{safe_topic}_{int(time.time())}_raw.jpg"
            img.save(raw_path, "JPEG", quality=95)
            
            self.last_raw_image_path = str(raw_path)
            self.last_title_used = self.topic_input.text().strip()
            
            # Aplicar texto si está activado
            final_path = raw_path
            if self.add_text_overlay_check.isChecked():
                final_path_str = str(thumb_dir / f"thumb_{source}_{safe_topic}_{int(time.time())}_final.jpg")
                style = self.text_style_combo.currentText()
                language = self.text_lang_combo.currentText()
                
                if self._add_text_to_image(str(raw_path), final_path_str, self.last_title_used, style, language):
                    final_path = Path(final_path_str)
                    self.log(f" Texto aplicado con estilo: {style} ({language})")
            
            # Mostrar en preview
            pixmap = QPixmap(str(final_path))
            scaled_pixmap = pixmap.scaled(640, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.thumb_preview.setPixmap(scaled_pixmap)
            
            self.log(f" Thumbnail {source} cargado: {final_path}")
            QMessageBox.information(self, "Imagen Cargada", 
                f"Imagen de {source.replace('_', ' ').title()} cargada exitosamente.\\n\\n"
                f"Puedes guardarla o añadir texto si lo deseas.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar imagen: {e}")
            import traceback
            traceback.print_exc()

    def generate_thumbnail(self):
        """Genera un thumbnail usando Recraft AI."""
        topic = self.topic_input.text().strip()
        category = self.category_combo.currentText()
        selected_style = self.thumb_style_combo.currentText()

        if not topic:
            QMessageBox.warning(self, "Entrada Vacia", "Ingresa un tema primero")
            return

        if not self.gemini_client:
            QMessageBox.critical(self, "Error", "Gemini Client no disponible")
            return

        # Verificar disponibilidad del backend Recraft
        if not (self.recraft_client and getattr(self.recraft_client, "api_key", None)):
            QMessageBox.critical(
                self,
                "Error",
                "Recraft no esta configurado.\\n\\n"
                "Configura la API key en el archivo .env:\\n"
                "- RECRAFT_API_KEY"
            )
            return

        self.log(f"Generando thumbnail: {topic}")
        self.btn_generate_thumb.setEnabled(False)
        self.btn_generate_thumb.setText("Generando...")
        self.log(f"Usando Recraft AI (Estilo: {selected_style})")
        self._execute_recraft_generation_thread(topic, category, selected_style, [])

    def _on_thumbnail_generated(self, worker, provider='', has_fallback=False):
        """Callback cuando se termina la generación"""
        # Solo habilitar el botón si no se activó el fallback
        if not (worker.error and has_fallback):
            self.btn_generate_thumb.setEnabled(True)
            self.btn_generate_thumb.setText("Generar miniatura")

        if worker.error and not has_fallback:
            # Error sin fallback disponible
            error_msg = f" Error {provider}: {worker.error}"
            self.log(error_msg)
            QMessageBox.critical(self, "Error", error_msg)
            self.thumb_preview.setText("Error en generación")
        elif not worker.error and worker.final_path:
            # Éxito
            self.log(" Thumbnail generado exitosamente")
            self._update_thumbnail_preview(worker.final_path)

    def _update_thumbnail_preview(self, image_path):
        """Actualiza el preview del thumbnail"""
        if not hasattr(self, 'thumb_preview') or self.thumb_preview is None:
            return
        temp_preview_path = None
        try:
            from PyQt6.QtGui import QPixmap

            if not image_path:
                self.thumb_preview.clear()
                self.thumb_preview.setText("La miniatura se mostrará aquí")
                return

            image_path = str(image_path)
            if not os.path.exists(image_path):
                self.thumb_preview.clear()
                self.thumb_preview.setText("Miniatura no encontrada")
                return

            if Path(image_path).suffix.lower() in {'.mp4', '.mov', '.avi', '.webm', '.mkv'}:
                self.thumb_preview.clear()
                self.thumb_preview.setText("Preview no disponible para video")
                return

            preview_path = image_path
            if self._looks_like_svg(image_path):
                temp_preview_path = self._rasterize_svg_to_png_temp(image_path)
                preview_path = temp_preview_path

            pixmap = QPixmap(preview_path)
            if pixmap.isNull():
                raise Exception("No se pudo cargar la imagen")

            # Escalar manteniendo aspecto
            scaled_pixmap = pixmap.scaled(
                self.thumb_preview.width(),
                self.thumb_preview.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            self.thumb_preview.setPixmap(scaled_pixmap)

        except Exception as e:
            self.log(f"️ Error mostrando preview: {e}")
            self.thumb_preview.setText(f"Error al cargar preview: {e}")
        finally:
            if temp_preview_path and os.path.exists(temp_preview_path):
                try:
                    os.remove(temp_preview_path)
                except Exception:
                    pass

    def save_thumbnail(self):
        """Guarda el thumbnail"""
        if not self.last_raw_image_path:
            QMessageBox.warning(self, "Sin Imagen", "No hay thumbnail para guardar")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Thumbnail", "", "PNG Image (*.png);;JPEG Image (*.jpg)"
        )

        if file_path:
            try:
                # Copiar el archivo
                import shutil
                shutil.copy2(self.last_raw_image_path, file_path)
                self.log(f" Thumbnail guardado: {file_path}")
                QMessageBox.information(self, "Éxito", f"Thumbnail guardado en:\\n{file_path}")
            except Exception as e:
                self.log(f" Error guardando: {e}")
                QMessageBox.critical(self, "Error", f"No se pudo guardar: {e}")

    def load_thumbnail(self):
        """Carga un thumbnail previamente generado"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Cargar Thumbnail", 
            "", 
            "Image Files (*.png *.jpg *.jpeg *.svg);;PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;SVG Image (*.svg);;All Files (*)"
        )
        
        if file_path:
            try:
                # Verificar que el archivo existe y es una imagen válida.
                # Si es SVG (incluso con extensión errónea), aceptarlo sin Pillow.
                from PIL import Image
                is_svg = self._looks_like_svg(file_path)
                if not is_svg:
                    with Image.open(file_path) as img:
                        img.verify()
                
                # Guardar la ruta
                self.last_raw_image_path = file_path
                if is_svg:
                    self.log("ℹ️ Archivo SVG detectado: se cargará con rasterización para preview/texto")
                
                # Intentar extraer el título del nombre del archivo
                # Los thumbnails generados suelen tener el formato: thumb_*_topic_*_final.*
                from pathlib import Path
                filename = Path(file_path).stem
                
                # Buscar el tema en el nombre del archivo (entre thumb_*_ y _*_final)
                # O usar el tema actual si está disponible
                if hasattr(self, 'topic_input') and self.topic_input.text().strip():
                    self.last_title_used = self.topic_input.text().strip()
                else:
                    # Intentar extraer del nombre del archivo
                    parts = filename.split('_')
                    # Buscar partes que parezcan un título (más de 3 caracteres, no números)
                    title_parts = [p for p in parts if len(p) > 3 and not p.isdigit() and p not in ['thumb', 'runway', 'leonardo', 'fal', 'final', 'raw', 'styled']]
                    if title_parts:
                        self.last_title_used = ' '.join(title_parts[:3])  # Tomar hasta 3 palabras
                    else:
                        self.last_title_used = "Título del Video"  # Título por defecto
                
                # Mostrar en el preview
                self._update_thumbnail_preview(file_path)
                
                self.log(f" Thumbnail cargado: {file_path}")
                self.log(f"   Título detectado: {self.last_title_used}")
                
                QMessageBox.information(
                    self, 
                    "Thumbnail Cargado", 
                    f"Thumbnail cargado exitosamente:\\n\\n{Path(file_path).name}\\n\\n"
                    f"Título: {self.last_title_used}\\n\\n"
                    f"Puedes añadir texto o modificarlo usando los botones de abajo."
                )
                
            except Exception as e:
                self.log(f" Error cargando thumbnail: {e}")
                QMessageBox.critical(
                    self, 
                    "Error", 
                    f"No se pudo cargar el thumbnail:\\n\\n{str(e)}\\n\\n"
                    f"Asegúrate de que es un archivo de imagen válido (PNG, JPG, JPEG o SVG)."
                )

    def add_text_to_thumbnail(self):
        """Permite reaplica texto al thumbnail generado con diferente estilo"""
        if not self.last_raw_image_path:
            QMessageBox.warning(self, "Sin Imagen",
                "No hay thumbnail cargado.\\nPrimero genera o carga un thumbnail.")
            return
        
        # Si no hay título usado, usar el tema actual o pedir uno
        if not hasattr(self, 'last_title_used') or not self.last_title_used:
            if hasattr(self, 'topic_input') and self.topic_input.text().strip():
                self.last_title_used = self.topic_input.text().strip()
            else:
                # Pedir el título al usuario
                from PyQt6.QtWidgets import QInputDialog
                title, ok = QInputDialog.getText(
                    self, 
                    "Título del Video", 
                    "Ingresa el título para el thumbnail:"
                )
                if ok and title.strip():
                    self.last_title_used = title.strip()
                else:
                    QMessageBox.warning(self, "Sin Título", "Se necesita un título para añadir texto al thumbnail.")
                    return

        # Diálogo para cambiar el estilo
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QComboBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Reaplica Texto al Thumbnail")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel(f"Imagen base: {Path(self.last_raw_image_path).name}"))
        layout.addWidget(QLabel(f"Texto: {self.last_title_used}"))
        layout.addWidget(QLabel("\\nSelecciona un nuevo estilo:"))

        style_combo = QComboBox()
        style_combo.addItems([
            "Contraste alto", "Claro limpio", "Neón suave", "Rojo intenso"
        ])
        style_combo.setCurrentText(self.text_style_combo.currentText())
        layout.addWidget(style_combo)

        def apply_new_style():
            style = style_combo.currentText()
            self.log(f" Reaplicando texto con estilo: {style}")

            # Determinar carpeta y extensión
            base_path = Path(self.last_raw_image_path)
            thumb_dir = base_path.parent
            safe_topic = "".join(c for c in self.last_title_used[:30] if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')

            # Crear nuevo path
            import time
            ext = base_path.suffix
            final_path_str = str(thumb_dir / f"{base_path.stem.replace('_raw', '')}_{int(time.time())}_styled{ext}")

            # Aplicar texto
            language = self.text_lang_combo.currentText()
            if self._add_text_to_image(self.last_raw_image_path, final_path_str, self.last_title_used, style, language):
                self.log(f" Texto reaplicado exitosamente")
                self._update_thumbnail_preview(final_path_str)
                dialog.accept()
            else:
                QMessageBox.critical(dialog, "Error", "No se pudo aplicar el texto")

        btn_apply = QPushButton("Aplicar estilo")
        btn_apply.clicked.connect(apply_new_style)
        layout.addWidget(btn_apply)

        dialog.exec()

    def open_interactive_thumbnail_editor(self):
        """Abre el editor interactivo de thumbnails"""
        if not self.last_raw_image_path:
            QMessageBox.warning(self, "Sin Imagen", 
                "No hay imagen base cargada.\\nPrimero genera o carga un thumbnail.")
            return
        
        try:
            from interactive_thumbnail_editor import InteractiveThumbnailEditor
            from PyQt6.QtWidgets import QDialog
            
            # Crear diálogo modal
            dialog = QDialog(self)
            dialog.setWindowTitle("Editor interactivo de miniaturas")
            dialog.setMinimumSize(1200, 800)
            dialog.resize(1400, 900)
            
            layout = QVBoxLayout(dialog)
            
            # Crear editor
            editor = InteractiveThumbnailEditor()
            editor.set_background_image(self.last_raw_image_path)
            
            # Si hay un título previo, usarlo
            if hasattr(self, 'last_title_used') and self.last_title_used:
                editor.text_input.setText(self.last_title_used)
                if editor.canvas.text_items:
                    editor.canvas.text_items[0].text = self.last_title_used
            
            # Conectar señal de thumbnail generado
            editor.thumbnail_generated.connect(self.on_interactive_thumbnail_generated)
            
            layout.addWidget(editor)
            
            # Botones de diálogo
            from PyQt6.QtWidgets import QDialogButtonBox
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Close
            )
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            
            # Ejecutar diálogo
            dialog.exec()
            
        except ImportError as e:
            QMessageBox.critical(self, "Error", 
                f"No se pudo importar el editor interactivo: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", 
                f"Error al abrir el editor interactivo: {e}")

    def on_interactive_thumbnail_generated(self, thumbnail_path):
        """Manejador para cuando se genera un thumbnail en el editor interactivo"""
        self.log(f" Thumbnail interactivo generado: {thumbnail_path}")

        # Actualizar preview
        self._update_thumbnail_preview(thumbnail_path)

        # Actualizar última imagen
        self.last_thumbnail_path = thumbnail_path

        # Mostrar mensaje de éxito
        QMessageBox.information(self, "Thumbnail Generado",
            f"Thumbnail interactivo guardado exitosamente en:\\n{thumbnail_path}")

    def generate_super_prompt_for_external_ai(self):
        """Genera [POSITIVE PROMPT] y [NEGATIVE PROMPT] listos para pegar en una IA externa."""
        topic = self.topic_input.text().strip() if hasattr(self, 'topic_input') else ""
        if not topic:
            QMessageBox.warning(self, "Sin tema", "Ingresa un tema primero.")
            return

        if not hasattr(self, 'claude_client') or not self.claude_client:
            QMessageBox.critical(self, "Error", "Claude client no disponible.")
            return

        category = self.category_combo.currentText() if hasattr(self, 'category_combo') else ""
        language = "es"
        if hasattr(self, 'text_lang_combo'):
            language = "en" if self.text_lang_combo.currentText() == "English" else "es"

        # Obtener fragmento del guion si está disponible
        script_excerpt = ""
        if hasattr(self, 'storyboard_data') and self.storyboard_data:
            script_excerpt = str(self.storyboard_data.get('script', ''))[:1200]
        elif hasattr(self, 'script_text') and self.script_text:
            script_excerpt = str(self.script_text)[:1200]

        self.btn_super_prompt.setEnabled(False)
        self.btn_super_prompt.setText("Generando...")

        def _run():
            return self.claude_client.generate_thumbnail_super_prompt(
                topic=topic,
                script_excerpt=script_excerpt,
                category=category,
                language=language,
            )

        def _on_done(result):
            self.btn_super_prompt.setEnabled(True)
            self.btn_super_prompt.setText("Super Prompt (IA externa)")
            if not result:
                QMessageBox.critical(self, "Error", "No se pudo generar el super prompt.")
                return
            self._show_super_prompt_dialog(result['positive'], result['negative'])

        import threading
        def _thread():
            result = _run()
            QTimer.singleShot(0, lambda: _on_done(result))

        threading.Thread(target=_thread, daemon=True).start()

    def _show_super_prompt_dialog(self, positive_prompt, negative_prompt):
        """Muestra un diálogo con el positive y negative prompt listos para copiar."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Super Prompt para IA externa")
        dialog.setMinimumSize(820, 600)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        layout.addWidget(QLabel(
            "<b>Copia estos prompts y pégalos en Midjourney, DALL-E, Stable Diffusion, etc.</b>"
        ))

        # — Positive Prompt —
        layout.addWidget(QLabel("<b>[POSITIVE PROMPT]</b>"))
        pos_edit = QTextEdit()
        pos_edit.setPlainText(positive_prompt)
        pos_edit.setReadOnly(True)
        pos_edit.setMinimumHeight(200)
        layout.addWidget(pos_edit)

        btn_copy_pos = QPushButton("Copiar Positive Prompt")
        btn_copy_pos.clicked.connect(
            lambda: (QApplication.clipboard().setText(pos_edit.toPlainText()),
                     btn_copy_pos.setText("Copiado!"),
                     QTimer.singleShot(1500, lambda: btn_copy_pos.setText("Copiar Positive Prompt")))
        )
        layout.addWidget(btn_copy_pos)

        # — Negative Prompt —
        layout.addWidget(QLabel("<b>[NEGATIVE PROMPT]</b>"))
        neg_edit = QTextEdit()
        neg_edit.setPlainText(negative_prompt)
        neg_edit.setReadOnly(True)
        neg_edit.setMinimumHeight(100)
        layout.addWidget(neg_edit)

        btn_copy_neg = QPushButton("Copiar Negative Prompt")
        btn_copy_neg.clicked.connect(
            lambda: (QApplication.clipboard().setText(neg_edit.toPlainText()),
                     btn_copy_neg.setText("Copiado!"),
                     QTimer.singleShot(1500, lambda: btn_copy_neg.setText("Copiar Negative Prompt")))
        )
        layout.addWidget(btn_copy_neg)

        # — Cerrar —
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)

        dialog.exec()

