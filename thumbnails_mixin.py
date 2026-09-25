from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import json
from pathlib import Path
from PIL import Image
import threading
import time
from recraft_style_catalog import RECRAFT_STYLE_OPTIONS

class ThumbnailsMixin:


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
            script_excerpt = str(self.storyboard_data.get('script', ''))[:12000]
        elif hasattr(self, 'script_text') and self.script_text:
            script_excerpt = str(self.script_text)[:12000]

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
