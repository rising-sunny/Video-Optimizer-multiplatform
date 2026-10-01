# studio_image_handlers.py
"""
Handlers para la generación y manejo de imágenes en AutoVideoStudioTab
"""

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QMessageBox
import os
from pathlib import Path

from studio.auto_video_generator_pyqt6_adapter import VideoGenerationWorker


# Mapping label de la combo box → provider_key interno. Centralizado aquí para
# que cualquier código (generación, copia de prompts, exports) lo reuse y no
# se desincronice.
IMAGE_PROVIDER_LABEL_TO_KEY = {
    "Recraft AI": "recraft",
    "FAL - Flux dev (calidad)": "flux_dev",
    "FAL - Flux schnell (rapido)": "flux_schnell",
    "ComfyUI - FLUX Dev (alta calidad)": "comfy_dev",
    "ComfyUI - FLUX Schnell": "comfy_schnell",
    "Fal.ai (FLUX.1 schnell)": "flux_schnell",     # legacy/compat
    "Fal.ai (FLUX.1 schnell) ⚡": "flux_schnell",  # legacy/compat
    "Google AI (Gemini API)": "google_ai",
    "Stability AI - Ultra (~$0.008)": "stability_ultra",
    "Stability AI - Core (~$0.003)": "stability_core",
    "Manual (Gratuito)": "manual",
    "Manual (Gratuito) - Gemini Veo/Copilot/etc.": "manual",
}


def resolve_image_provider_key(label_or_combo, default="recraft"):
    """Convierte un label de combobox (o el combobox mismo) a su provider_key.

    Acepta:
      - str: el label tal cual aparece en la combo box
      - QComboBox: se lee `currentText()` automáticamente
      - None / vacío: devuelve el default
    """
    if label_or_combo is None:
        return default
    if hasattr(label_or_combo, "currentText"):
        label = label_or_combo.currentText() or ""
    else:
        label = str(label_or_combo or "")
    label = label.strip()
    if not label:
        return default
    return IMAGE_PROVIDER_LABEL_TO_KEY.get(label, default)


class StudioImageHandlers:
    """Helper class para manejar handlers de generación de imágenes de AutoVideoStudioTab"""

    def __init__(self, studio_tab):
        """Inicializa el handler con una referencia a AutoVideoStudioTab"""
        self.studio_tab = studio_tab

    def generate_images(self):
        """Genera todas las imágenes para el storyboard (Paso 1.5)"""
        if not self.studio_tab.last_storyboard_data:
            QMessageBox.warning(self.studio_tab, "Sin Storyboard",
                              "Primero genera el storyboard (Paso 1)")
            return

        # Verificar si se seleccionó modo manual
        image_provider_text = self.studio_tab.image_provider_combo.currentText(
        ) if hasattr(self.studio_tab, 'image_provider_combo') else "Recraft AI"

        self.studio_tab.log(f"\n{'='*50}")
        self.studio_tab.log(f"️ PASO 1.5: GENERANDO IMÁGENES")
        self.studio_tab.log(f"   Proveedor seleccionado: {image_provider_text}")
        self.studio_tab.log(f"{'='*50}\n")

        if "Manual" in image_provider_text:
            # Modo manual: generar prompts en lugar de imágenes
            self.studio_tab.log(" Modo Manual: Generando prompts para servicios gratuitos...")
            self.generate_manual_image_prompts()
            return

        # Obtener configuración
        platform = self.studio_tab.get_selected_platform_key() if hasattr(self.studio_tab, 'get_selected_platform_key') else self.studio_tab.platform_combo.currentText()
        video_format = self.studio_tab.get_selected_video_format() if hasattr(self.studio_tab, 'get_selected_video_format') else '16:9'
        resolution = self.studio_tab.get_selected_resolution() if hasattr(self.studio_tab, 'get_selected_resolution') else (1920, 1080)
        # Obtener opciones de imágenes reales
        # Openverse (Gratis) y Wikimedia ahora son manuales (desde Timeline Editor)
        use_google_images = False  # Manual desde Timeline Editor
        use_wikimedia = False  # Manual desde Timeline Editor
        enable_real_images_mix = False  # No usar mezcla inteligente
        use_real_images = False  # No usar Pexels/Pixabay
        disable_wikimedia = False  # No deshabilitar Wikimedia

        # Obtener proveedor seleccionado
        image_provider_text = self.studio_tab.image_provider_combo.currentText(
        ) if hasattr(self.studio_tab, 'image_provider_combo') else "Recraft AI"

        self.studio_tab.log(f"\n{'='*50}")
        self.studio_tab.log(f"️ PASO 1.5: GENERANDO IMÁGENES")
        self.studio_tab.log(f"   Proveedor IA: {image_provider_text}")
        self.studio_tab.log(f"   Formato: {video_format} ({resolution[0]}x{resolution[1]})")
        self.studio_tab.log(f"    Openverse (Gratis)/Wikimedia: Manual (usa botones  y  en Timeline Editor)")
        if "Manual" not in image_provider_text:
            self.studio_tab.log(f"    IA Generativa: SÍ (proveedor seleccionado)")
        self.studio_tab.log(f"{'='*50}\n")

        # Deshabilitar botones
        self.studio_tab.btn_storyboard.setEnabled(False)
        self.studio_tab.btn_generate_images.setEnabled(False)
        if hasattr(self.studio_tab, 'btn_export_recraft_prompts'):
            self.studio_tab.btn_export_recraft_prompts.setEnabled(False)
        self.studio_tab._show_progress_indicator()

        # Crear worker para generar imágenes
        self.studio_tab.current_worker = VideoGenerationWorker(
            self.studio_tab.generator, "generate_images")
        # Mapear texto del combo a valor del proveedor (helper centralizado).
        image_provider_value = resolve_image_provider_key(
            image_provider_text, default="recraft"
        )

        # --- Proveedor de VIDEO (opcional, para I2V con Kling/Luma o Runway) ---
        video_provider_value = "none"
        fal_video_model = None
        try:
            if hasattr(self.studio_tab, '_normalize_video_provider_key'):
                video_provider_value, fal_video_model = self.studio_tab._normalize_video_provider_key()
        except Exception as exc:
            self.studio_tab.log(f"   Video provider: fallback a 'none' por error: {exc}")
            video_provider_value, fal_video_model = ("none", None)

        if video_provider_value and video_provider_value != "none":
            modelo_str = f" ({fal_video_model})" if fal_video_model else ""
            self.studio_tab.log(
                f"    Proveedor VIDEO: {video_provider_value}{modelo_str} (I2V se aplicara tras generar las imagenes)"
            )
        else:
            self.studio_tab.log(
                "    Proveedor VIDEO: ninguno (se usara imagen estatica + Ken Burns)"
            )

        # Persistir seleccion en el studio_tab para que pasos posteriores
        # (ensamblado/pipeline de video) puedan leerla sin consultar el combo.
        try:
            self.studio_tab.selected_video_provider = video_provider_value
            self.studio_tab.selected_fal_video_model = fal_video_model
        except Exception:
            pass

        # En Google AI se preservan las imágenes IA ya asignadas para
        # rellenar solo segmentos vacíos y respetar grupos compartidos.
        preserve_existing_ai = image_provider_value == "google_ai"
        if preserve_existing_ai:
            self.studio_tab.log(
                "   ️ Modo rellenar vacíos: se conservarán las imágenes IA existentes y sus grupos compartidos"
            )
        else:
            # LIMPIEZA: Eliminar todas las imágenes IA previas antes de generar nuevas
            # Conservar imágenes manuales (Bing, Wikimedia, YouTube, etc.)
            self._cleanup_old_ai_images()

        # Obtener ratio de imágenes por segmento
        images_per_segment_ratio = self.studio_tab.images_per_segment_spin.value(
        ) if hasattr(self.studio_tab, 'images_per_segment_spin') else 1.0

        # Obtener opción de intercalado
        interleave_images = self.studio_tab.interleave_images_check.isChecked() if hasattr(
            self.studio_tab, 'interleave_images_check') else False

        if images_per_segment_ratio > 1.0:
            total_segments = len(self.studio_tab.last_storyboard_data.get('segments', []))
            estimated_images = (
                total_segments + images_per_segment_ratio - 1) // images_per_segment_ratio
            savings = int((1 - estimated_images / total_segments)
                          * 100) if total_segments > 0 else 0
            self.studio_tab.log(
                f"    Agrupación activada: {total_segments} segmentos  ~{estimated_images} imágenes (~{savings}% ahorro)")
        
        if interleave_images:
            total_segments = len(self.studio_tab.last_storyboard_data.get('segments', []))
            estimated_images = (total_segments + 1) // 2  # Mitad redondeada hacia arriba
            self.studio_tab.log(
                f"    Modo intercalado activado: ~{estimated_images} imágenes IA, ~{total_segments - estimated_images} espacios vacíos")

        # Obtener estilo seleccionado solo cuando aplica al proveedor actual.
        style = self.studio_tab.get_selected_visual_style() if hasattr(
            self.studio_tab, 'get_selected_visual_style'
        ) else None
        if style:
            self.studio_tab.log(f"    Estilo visual: {style}")
        else:
            self.studio_tab.log("    Estilo visual: desactivado para este proveedor")
        
        self.studio_tab.current_worker.set_params(
            storyboard_data=self.studio_tab.last_storyboard_data,
            platform=platform,
            use_wikimedia=use_wikimedia,
            disable_wikimedia=disable_wikimedia,
            use_real_images=use_real_images,
            use_google_images=use_google_images,
            enable_real_images_mix=enable_real_images_mix,
            image_provider=image_provider_value,
            video_provider=video_provider_value,
            fal_video_model=fal_video_model,
            images_per_segment_ratio=images_per_segment_ratio,
            interleave_images=interleave_images,
            style=style,
            regenerate_prompts=True,  # Regenerar prompts con el nuevo estilo para garantizar que se aplique correctamente
            project_path=self.studio_tab.current_project_path,
        )
        if hasattr(self.studio_tab, '_bind_current_worker_to_project'):
            self.studio_tab._bind_current_worker_to_project()

        # Asegurarse de que el thread anterior termine antes de crear uno nuevo
        if self.studio_tab.current_thread and self.studio_tab.current_thread.isRunning():
            self.studio_tab.log(" Esperando que termine el proceso anterior...")
            self.studio_tab.current_thread.quit()
            if not self.studio_tab.current_thread.wait(5000):  # Esperar máximo 5 segundos
                self.studio_tab.log("️ Forzando terminación del thread anterior...")
                self.studio_tab.current_thread.terminate()
                self.studio_tab.current_thread.wait()

        # Conectar señales
        self.studio_tab.current_worker.finished.connect(self.studio_tab.on_images_generated)
        self.studio_tab.current_worker.error.connect(self.studio_tab.on_images_error)
        self.studio_tab.current_worker.progress.connect(self.studio_tab.log)

        # Ejecutar en thread
        self.studio_tab.current_thread = QThread()
        self.studio_tab.current_worker.moveToThread(self.studio_tab.current_thread)
        self.studio_tab.current_thread.started.connect(self.studio_tab.current_worker.run)
        self.studio_tab.current_thread.start()

    def _get_recraft_export_style(self):
        """Obtiene el estilo Recraft seleccionado en la UI."""
        if hasattr(self.studio_tab, 'style_combo') and self.studio_tab.style_combo.count() > 0:
            style_value = (self.studio_tab.style_combo.currentText() or "").strip()
            if style_value:
                return style_value
        return "Photorealism"

    def _build_recraft_export_default_path(self):
        """Propone una ruta por defecto para el TXT de prompts."""
        base_name = None
        target_dir = Path.cwd()

        if getattr(self.studio_tab, 'current_project_path', None):
            project_path = Path(self.studio_tab.current_project_path)
            if project_path.parent.exists():
                target_dir = project_path.parent
                base_name = project_path.parent.name

        if not base_name and self.studio_tab.last_storyboard_data:
            base_name = str(self.studio_tab.last_storyboard_data.get('topic') or "").strip()

        safe_name = "".join(
            c for c in (base_name or "storyboard")[:60]
            if c.isalnum() or c in (" ", "-", "_", "(", ")")
        ).strip().replace(" ", "_")
        safe_name = safe_name or "storyboard"
        return target_dir / f"recraft_prompts_{safe_name}.txt"

    def _restore_image_action_buttons(self):
        """Restaura el estado base de los botones del flujo de imágenes."""
        has_storyboard = bool(self.studio_tab.last_storyboard_data)
        self.studio_tab.btn_storyboard.setEnabled(True)
        if hasattr(self.studio_tab, 'btn_generate_images'):
            self.studio_tab.btn_generate_images.setEnabled(has_storyboard)
        if hasattr(self.studio_tab, 'btn_export_recraft_prompts'):
            self.studio_tab.btn_export_recraft_prompts.setEnabled(has_storyboard)
        if hasattr(self.studio_tab, 'btn_open_timeline'):
            self.studio_tab.btn_open_timeline.setEnabled(has_storyboard)

    def export_recraft_prompts_txt(self):
        """Exporta un TXT con los prompts finales que usaría Recraft."""
        if not self.studio_tab.last_storyboard_data:
            QMessageBox.warning(
                self.studio_tab,
                "Sin Storyboard",
                "Primero genera el storyboard (Paso 1)"
            )
            return

        from PyQt6.QtWidgets import QFileDialog

        default_path = self._build_recraft_export_default_path()
        output_path, _ = QFileDialog.getSaveFileName(
            self.studio_tab,
            "Guardar TXT de prompts Recraft",
            str(default_path),
            "Archivos de texto (*.txt);;Todos los archivos (*.*)"
        )
        if not output_path:
            return

        platform = self.studio_tab.get_selected_platform_key() if hasattr(
            self.studio_tab, 'get_selected_platform_key'
        ) else self.studio_tab.platform_combo.currentText()
        video_format = self.studio_tab.get_selected_video_format() if hasattr(
            self.studio_tab, 'get_selected_video_format'
        ) else '16:9'
        resolution = self.studio_tab.get_selected_resolution() if hasattr(
            self.studio_tab, 'get_selected_resolution'
        ) else (1920, 1080)
        images_per_segment_ratio = self.studio_tab.images_per_segment_spin.value(
        ) if hasattr(self.studio_tab, 'images_per_segment_spin') else 1.0
        interleave_images = self.studio_tab.interleave_images_check.isChecked() if hasattr(
            self.studio_tab, 'interleave_images_check'
        ) else False
        style = self._get_recraft_export_style()

        self.studio_tab.log(f"\n{'='*50}")
        self.studio_tab.log(" EXPORTANDO TXT DE PROMPTS RECRAFT")
        self.studio_tab.log(f"   Destino: {output_path}")
        self.studio_tab.log(f"   Formato: {video_format} ({resolution[0]}x{resolution[1]})")
        self.studio_tab.log(f"   Estilo Recraft: {style}")
        self.studio_tab.log(f"   Ratio imágenes/segmento: {images_per_segment_ratio}")
        self.studio_tab.log(f"   Intercalado: {'Sí' if interleave_images else 'No'}")
        self.studio_tab.log(f"{'='*50}\n")

        self.studio_tab.btn_storyboard.setEnabled(False)
        self.studio_tab.btn_generate_images.setEnabled(False)
        if hasattr(self.studio_tab, 'btn_export_recraft_prompts'):
            self.studio_tab.btn_export_recraft_prompts.setEnabled(False)
        self.studio_tab._show_progress_indicator()

        self.studio_tab.current_worker = VideoGenerationWorker(
            self.studio_tab.generator,
            "export_recraft_prompts"
        )
        self.studio_tab.current_worker.set_params(
            storyboard_data=self.studio_tab.last_storyboard_data,
            platform=platform,
            output_path=output_path,
            images_per_segment_ratio=images_per_segment_ratio,
            interleave_images=interleave_images,
            style=style,
            regenerate_prompts=True,
            project_path=self.studio_tab.current_project_path,
        )
        if hasattr(self.studio_tab, '_bind_current_worker_to_project'):
            self.studio_tab._bind_current_worker_to_project()

        if self.studio_tab.current_thread and self.studio_tab.current_thread.isRunning():
            self.studio_tab.log(" Esperando que termine el proceso anterior...")
            self.studio_tab.current_thread.quit()
            if not self.studio_tab.current_thread.wait(5000):
                self.studio_tab.log("️ Forzando terminación del thread anterior...")
                self.studio_tab.current_thread.terminate()
                self.studio_tab.current_thread.wait()

        self.studio_tab.current_worker.finished.connect(self.studio_tab.on_recraft_prompts_exported)
        self.studio_tab.current_worker.error.connect(self.studio_tab.on_recraft_prompts_error)
        self.studio_tab.current_worker.progress.connect(self.studio_tab.log)

        self.studio_tab.current_thread = QThread()
        self.studio_tab.current_worker.moveToThread(self.studio_tab.current_thread)
        self.studio_tab.current_thread.started.connect(self.studio_tab.current_worker.run)
        self.studio_tab.current_thread.start()

    def on_images_generated(self, result):
        """Callback cuando las imágenes están generadas"""
        self.studio_tab.log(f"\n PASO 1.5 COMPLETADO")
        self.studio_tab.log(f"️ {len(result.get('segments', []))} segmentos procesados")

        # IMPORTANTE: Asegurar que todos los segmentos tengan image_path
        # guardado
        segments = result.get('segments', [])
        unique_image_paths = set()
        for seg in segments:
            image_path = seg.get('image_path')
            if image_path:
                # Convertir a ruta absoluta para asegurar persistencia
                if not os.path.isabs(image_path):
                    from pathlib import Path
                    abs_path = Path(image_path).resolve()
                    if abs_path.exists():
                        seg['image_path'] = str(abs_path)
                        self.studio_tab.log(
                            f"    Ruta de imagen convertida a absoluta: {os.path.basename(image_path)}")
                # Verificar que la imagen existe
                if not os.path.exists(seg['image_path']):
                    self.studio_tab.log(
                        f"   ️ Advertencia: Imagen no encontrada en {seg['image_path']}")
                else:
                    unique_image_paths.add(os.path.abspath(seg['image_path']))
            else:
                self.studio_tab.log(
                    f"   ️ Segmento sin image_path: {seg.get('assigned_filename', 'desconocido')}")
        segments_with_image = sum(1 for seg in segments if seg.get('image_path'))
        self.studio_tab.log(
            f"    Segmentos con imagen: {segments_with_image}/{len(segments)} | imágenes únicas: {len(unique_image_paths)}")

        # Actualizar storyboard con imágenes generadas
        self.studio_tab.last_storyboard_data = result

        # IMPORTANTE: Si hay un proyecto activo, copiar imágenes IA a la carpeta del proyecto inmediatamente
        if self.studio_tab.current_project_path and os.path.exists(self.studio_tab.current_project_path):
            self.studio_tab.log(f"\n Copiando imágenes IA generadas a la carpeta del proyecto...")
            from pathlib import Path
            import shutil
            
            project_path_obj = Path(self.studio_tab.current_project_path)
            project_dir = project_path_obj.parent
            project_name = project_path_obj.stem
            
            # Usar formato nuevo: project_media dentro de la carpeta del proyecto
            media_dir = project_dir / "project_media"
            media_dir.mkdir(exist_ok=True)
            
            copied_count = 0
            ai_sources = {
                'fal_ai', 'fal', 'leonardo', 'leonardo_ai',
                'recraft_ai', 'recraft_compat_leonardo', 'google_ai', 'vertex_imagen',
                'comfy_flux_schnell', 'comfy_flux_dev', 'comfy_sdxl', 'existing'
            }
            manual_sources = {
                'wikimedia', 'bing_images', 'google_images', 'pexels_video',
                'wikimedia_video', 'internet_archive', 'youtube'
            }
            # Mantener mapeo para no duplicar copias cuando varios segmentos comparten la misma imagen.
            source_to_relpath = {}

            for segment_number, seg in enumerate(segments, start=1):
                image_source = seg.get('image_source', '')
                image_path = seg.get('image_path', '')
                assigned_filename = seg.get('assigned_filename', '')
                
                # Solo copiar imágenes IA generadas (no manuales)
                is_ai_generated = image_source in ai_sources
                
                # IMPORTANTE: Solo copiar si el segmento NO tiene imagen manual
                has_manual_image = image_source in manual_sources
                
                if is_ai_generated and not has_manual_image and image_path and os.path.exists(image_path):
                    source_path = Path(image_path)
                    source_resolved = None
                    try:
                        source_resolved = str(source_path.resolve())
                    except:
                        source_resolved = str(source_path)

                    # Si esta imagen ya se copió para otro segmento, reutilizar misma ruta relativa.
                    if source_resolved in source_to_relpath:
                        seg['image_path'] = source_to_relpath[source_resolved]
                        if not seg.get('image_source'):
                            seg['image_source'] = image_source
                        continue

                    # Si la imagen ya está dentro de media_dir, no copiar de nuevo
                    try:
                        media_dir_resolved = str(media_dir.resolve())
                        if source_resolved.startswith(media_dir_resolved):
                            # Ya está en project_media, solo actualizar ruta a relativa
                            rel_filename = source_path.name
                            rel_path = f"project_media/{rel_filename}"
                            seg['image_path'] = rel_path
                            source_to_relpath[source_resolved] = rel_path
                            if not seg.get('image_source'):
                                seg['image_source'] = image_source
                            continue
                    except:
                        pass

                    # Generar nombre usando formato project_segment_XXX.ext para facilitar restauración
                    source_ext = source_path.suffix.lower() if source_path.suffix else '.jpg'
                    if source_ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                        source_ext = '.jpg'

                    # Usar formato: project_segment_XXX.ext (más fácil de restaurar)
                    filename = f"project_segment_{segment_number:03d}{source_ext}"
                    dest_path = media_dir / filename

                    # Si ya existe, agregar hash para evitar sobrescribir
                    if dest_path.exists():
                        import hashlib
                        hash_suffix = hashlib.md5(str(image_path).encode()).hexdigest()[:8]
                        name_part = Path(filename).stem
                        ext = Path(filename).suffix
                        filename = f"{name_part}_{hash_suffix}{ext}"
                        dest_path = media_dir / filename

                    # Copiar archivo (solo si no es el mismo)
                    if str(source_path.resolve()) != str(dest_path.resolve()):
                        shutil.copy2(source_path, dest_path)
                        copied_count += 1

                        # Actualizar ruta en el segmento (relativa al proyecto)
                        # Formato: project_media/filename
                        rel_path = f"project_media/{filename}"
                        seg['image_path'] = rel_path
                        source_to_relpath[source_resolved] = rel_path
                        # Asegurar que image_source esté guardado
                        if not seg.get('image_source'):
                            seg['image_source'] = image_source
                        self.studio_tab.log(f"    Copiada: {os.path.basename(image_path)} -> {filename}")
            
            if copied_count > 0:
                self.studio_tab.log(f" {copied_count} imagen(es) IA copiada(s) a: {media_dir}")
                self.studio_tab.log(f"    Las imágenes se guardaron en el proyecto y se restaurarán al abrirlo")

        # Auto-guardar ANTES de abrir el Timeline (que recarga desde disco)
        # para que las image_path queden persistidas en project.json
        self.studio_tab.last_storyboard_data = result
        if self.studio_tab.auto_save_enabled and self.studio_tab.current_project_path:
            self.studio_tab.auto_save_project("después de generar imágenes")

        # Actualizar Timeline Editor con las imágenes (SÍ buscar imágenes
        # porque ya fueron generadas)
        self.studio_tab.populate_review_panel(result, auto_search_images=True)

        # Habilitar botón de ensamblar
        self._restore_image_action_buttons()
        self.studio_tab._refresh_assemble_button_state()
        self.studio_tab._hide_progress_indicator()

        self.studio_tab.cleanup_thread()

    def on_images_error(self, error):
        """Callback cuando falla la generación de imágenes."""
        self.studio_tab.log(f"\n ERROR generando imágenes:\n{error}")
        self._restore_image_action_buttons()
        self.studio_tab._hide_progress_indicator()
        self.studio_tab.cleanup_thread()
        QMessageBox.critical(
            self.studio_tab,
            "Error generando imágenes",
            str(error),
        )

    def on_recraft_prompts_exported(self, result):
        """Callback cuando el TXT de prompts Recraft fue exportado."""
        jobs = result.get('jobs', [])
        output_path = result.get('output_path', '')
        skipped_segments = result.get('skipped_segments', [])

        self.studio_tab.log("\n TXT de prompts Recraft exportado")
        self.studio_tab.log(f"   Archivo: {output_path}")
        self.studio_tab.log(f"   Prompts exportados: {len(jobs)}")
        if skipped_segments:
            self.studio_tab.log(
                f"   Segmentos omitidos por media existente: {', '.join(str(num) for num in skipped_segments)}"
            )

        self._restore_image_action_buttons()
        self.studio_tab._hide_progress_indicator()
        self.studio_tab.cleanup_thread()

        QMessageBox.information(
            self.studio_tab,
            "TXT exportado",
            f" TXT de prompts Recraft guardado.\n\n"
            f"Archivo: {output_path}\n"
            f"Prompts exportados: {len(jobs)}"
        )

    def on_recraft_prompts_error(self, error):
        """Callback cuando falla la exportación del TXT de prompts Recraft."""
        self.studio_tab.log(f"\n ERROR exportando TXT de prompts Recraft:\n{error}")
        self._restore_image_action_buttons()
        self.studio_tab._hide_progress_indicator()
        self.studio_tab.cleanup_thread()
        QMessageBox.critical(
            self.studio_tab,
            "Error exportando TXT",
            str(error),
        )

    def _cleanup_old_ai_images(self):
        """Elimina todas las imágenes IA previas del proyecto antes de generar nuevas.
        Conserva imágenes manuales (Bing, Wikimedia, YouTube, etc.)."""
        if not self.studio_tab.current_project_path:
            return

        from pathlib import Path

        project_path_obj = Path(self.studio_tab.current_project_path)
        project_dir = project_path_obj.parent
        media_dir = project_dir / "project_media"

        if not media_dir.exists():
            return

        ai_sources = [
            'fal_ai', 'fal', 'leonardo', 'leonardo_ai',
            'recraft_ai', 'recraft_compat_leonardo', 'google_ai', 'vertex_imagen',
            'comfy_flux_schnell', 'comfy_flux_dev', 'comfy_sdxl', 'existing'
        ]
        segments = self.studio_tab.last_storyboard_data.get('segments', [])
        deleted_count = 0

        for seg in segments:
            image_source = seg.get('image_source', '')
            image_path = seg.get('image_path', '')

            if image_source not in ai_sources:
                continue

            # Eliminar archivo físico
            if image_path:
                try:
                    file_path = Path(image_path)
                    if not file_path.is_absolute():
                        file_path = project_dir / image_path
                    if file_path.exists():
                        file_path.unlink()
                        deleted_count += 1
                except Exception as e:
                    print(f"   ️ Error eliminando {image_path}: {e}")

            # Limpiar datos del segmento para que se regenere
            if 'image_path' in seg:
                del seg['image_path']
            if 'image_source' in seg:
                del seg['image_source']
            if 'image_deleted' in seg:
                del seg['image_deleted']

        # También eliminar archivos project_segment_* huérfanos en media_dir
        # que no estén referenciados por segmentos manuales (evita colisiones de nombre)
        manual_files = set()
        for seg in segments:
            img = seg.get('image_path', '')
            if img:
                manual_files.add(Path(img).name)

        for f in media_dir.glob("project_segment_*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in ['.jpg', '.jpeg', '.png', '.webp']:
                continue
            if f.name not in manual_files:
                try:
                    f.unlink()
                    deleted_count += 1
                except Exception:
                    pass

        if deleted_count > 0:
            self.studio_tab.log(f"️ {deleted_count} imagen(es) IA anteriores eliminadas de {media_dir.name}")
        else:
            self.studio_tab.log(f"️ No había imágenes IA anteriores que eliminar")

    def generate_manual_image_prompts(self):
        """Genera prompts con códigos únicos para generación manual de imágenes"""
        if not self.studio_tab.last_storyboard_data:
            QMessageBox.warning(self, "Sin Storyboard",
                              "Primero genera el storyboard (Paso 1)")
            return

        self.studio_tab.log(f"\n{'='*50}")
        self.studio_tab.log(f" GENERANDO PROMPTS PARA GENERACIÓN MANUAL")
        self.studio_tab.log(f"{'='*50}\n")

        segments = self.studio_tab.last_storyboard_data.get('segments', [])
        if not segments:
            QMessageBox.warning(
    self,
    "Sin Segmentos",
     "No hay segmentos en el storyboard")
            return

        topic = self.studio_tab.last_storyboard_data.get('topic', 'Unknown')
        category = self.studio_tab.last_storyboard_data.get('category', 'general')
        aspect_settings = self._get_manual_prompt_aspect_settings()

        # Generar códigos únicos para cada segmento
        from datetime import datetime
        segment_codes = {}
        for i, seg in enumerate(segments, 1):
            code = f"SEG{i:03d}"
            segment_codes[code] = {
                'segment_number': i,
                'filename': seg.get('assigned_filename', f"segment_{i:02d}.png")
            }

        manual_prompts = {
            "project_info": {
                "topic": topic,
                "category": category,
                "total_segments": len(segments),
                "generated_at": datetime.now().isoformat(),
                "video_format": aspect_settings["video_format"],
                "resolution": aspect_settings["resolution_label"],
                "segment_codes": segment_codes,
                "instructions": [
                    "1. Cada prompt tiene un código único al inicio: [SEG001], [SEG002], etc.",
                    "2. Copia el prompt completo (incluyendo el código) al servicio gratuito",
                    "3. Genera la imagen",
                    "4. Al descargar, renombra la imagen con el código: SEG001.png, SEG002.png, etc.",
                    "5. Usa el ratio/formato indicado en este proyecto para mantener coherencia visual",
                    "6. O simplemente carga las imágenes y el sistema las mapeará automáticamente"
                ]
            },
            "services": {
                "gemini_veo": {
                    "name": "Google Gemini Veo",
                    "url": "https://gemini.google.com/",
                    "free": True,
                    "instructions": [
                        "1. Ve a https://gemini.google.com/",
                        "2. Busca la opción de generación de imágenes (si está disponible)",
                        "3. Copia el prompt completo (incluye el código [SEGXXX])",
                        "4. Pega y genera",
                        "5. Descarga y renombra según el código (ej: SEG001.png)"
                    ]
                },
                "bing_image_creator": {
                    "name": "Microsoft Bing Image Creator",
                    "url": "https://www.bing.com/images/create",
                    "free": True,
                    "instructions": [
                        "1. Ve a https://www.bing.com/images/create",
                        "2. Inicia sesión con tu cuenta Microsoft (gratis)",
                        "3. Copia el prompt completo (incluye [SEGXXX])",
                        "4. Genera y descarga",
                        "5. Renombra según el código"
                    ]
                },
                "recraft_ai": {
                    "name": "Recraft AI (Plan Gratuito)",
                    "url": "https://recraft.ai/",
                    "free": True,
                    "instructions": [
                        "1. Ve a https://recraft.ai/ y crea cuenta gratuita",
                        "2. Ve a 'Generate Image' o 'Image Generation'",
                        "3. Pega el prompt optimizado para Recraft",
                        "4. Selecciona estilo (realistic, vector, illustration, etc.)",
                        f"5. Selecciona ratio {aspect_settings['service_ratio']}",
                        "6. Genera y descarga la imagen",
                        "7. Renómbrala según el código del segmento (ej: SEG001.png)"
                    ]
                },
                "huggingface": {
                    "name": "Hugging Face Spaces",
                    "url": "https://huggingface.co/spaces",
                    "free": True,
                    "instructions": [
                        "1. Ve a https://huggingface.co/spaces",
                        "2. Busca 'Stable Diffusion' o 'Flux'",
                        "3. Pega el prompt genérico",
                        "4. Genera y descarga"
                    ]
                }
            },
            "segments": []
        }

        # Generar prompts para cada segmento
        for seg in segments:
            seg_num = seg.get(
    'segment_number', len(
        manual_prompts["segments"]) + 1)
            code = f"SEG{seg_num:03d}"
            narrative = seg.get('narration_text', seg.get('text', ''))
            visual_prompt = seg.get('visual_prompt', '')

            # Si no hay visual_prompt, generar uno básico desde narrative
            if not visual_prompt and narrative:
                # Usar primeros 100 caracteres como fallback
                visual_prompt = narrative[:100]

            # Generar prompts optimizados CON el código incluido
            gemini_prompt = f"[{code}] {self._optimize_prompt_for_gemini(visual_prompt, narrative, category)}"
            bing_prompt = f"[{code}] {self._optimize_prompt_for_bing(visual_prompt, narrative, category)}"
            recraft_prompt = f"[{code}] {self._optimize_prompt_for_recraft(visual_prompt, narrative, category)}"
            generic_prompt = f"[{code}] {self._optimize_prompt_generic(visual_prompt, narrative, category)}"

            manual_prompts["segments"].append({
                "segment_code": code,
                "segment_number": seg_num,
                "filename": seg.get('assigned_filename', f"segment_{seg_num:02d}.png"),
                "timestamp": f"{seg.get('start_time', 0):.1f}s - {seg.get('end_time', 0):.1f}s",
                "duration": seg.get('duration', 0),
                "narrative_text": narrative,
                "prompts": {
                    "gemini_veo": gemini_prompt,
                    "bing_image_creator": bing_prompt,
                    "recraft_ai": recraft_prompt,
                    "generic": generic_prompt
                },
                "quick_copy": {
                    "prompt_only": visual_prompt,
                    "prompt_with_code": gemini_prompt
                }
            })

        self.studio_tab.log(
            f" {len(manual_prompts['segments'])} prompts generados con códigos únicos")

        # Mostrar diálogo con prompts
        self.show_manual_prompts_dialog(manual_prompts)
    def _get_manual_prompt_aspect_settings(self):
        """Devuelve guía de aspect ratio para prompts manuales según el formato actual."""
        video_format = (
            self.studio_tab.get_selected_video_format()
            if hasattr(self.studio_tab, 'get_selected_video_format')
            else '16:9'
        )
        resolution = (
            self.studio_tab.get_selected_resolution()
            if hasattr(self.studio_tab, 'get_selected_resolution')
            else (1920, 1080)
        )

        if video_format == '9:16':
            return {
                "video_format": "9:16",
                "resolution_label": f"{resolution[0]}x{resolution[1]}",
                "service_ratio": "9:16 (1080x1920 o similar)",
                "prompt_prefix": "Vertical portrait image for 9:16 video",
                "prompt_tail": (
                    "vertical portrait composition, optimized for smartphone framing, "
                    "subject centered, leave clean lower-third space for subtitles, no embedded text, no cameras, no UI"
                ),
            }

        if video_format == '1:1':
            return {
                "video_format": "1:1",
                "resolution_label": f"{resolution[0]}x{resolution[1]}",
                "service_ratio": "1:1 (1080x1080 o similar)",
                "prompt_prefix": "Square still image",
                "prompt_tail": (
                    "square 1:1 composition, centered framing, balanced negative space, no embedded text"
                ),
            }

        return {
            "video_format": "16:9",
            "resolution_label": f"{resolution[0]}x{resolution[1]}",
            "service_ratio": "16:9 (1920x1080 o similar)",
            "prompt_prefix": "Cinematic 16:9 image",
            "prompt_tail": (
                "16:9 cinematic composition, balanced wide framing, no embedded text"
            ),
        }
    def _optimize_prompt_for_gemini(self, base_prompt, narrative, category):
        """Optimiza prompt específicamente para Gemini Veo"""
        # Gemini Veo funciona mejor con prompts descriptivos y cinematográficos
        aspect = self._get_manual_prompt_aspect_settings()
        return (
            f"{aspect['prompt_prefix']}, {base_prompt}, professional photography, dramatic lighting, "
            f"high quality, 4K resolution, documentary style, {aspect['prompt_tail']}"
        )
    def _optimize_prompt_for_bing(self, base_prompt, narrative, category):
        """Optimiza prompt para Bing Image Creator (DALL-E 3)"""
        # Bing funciona mejor con prompts más directos
        aspect = self._get_manual_prompt_aspect_settings()
        return f"{base_prompt}, cinematic, professional, high quality, {aspect['prompt_tail']}"
    def _optimize_prompt_for_recraft(self, base_prompt, narrative, category):
        """Optimiza prompt específicamente para Recraft AI"""
        # Recraft funciona bien con prompts descriptivos y estilos explícitos.
        style_hint = "Photorealism"  # Por defecto
        aspect = self._get_manual_prompt_aspect_settings()

        if category.lower() in ['historia', 'history']:
            style_hint = "Photorealism, cinematic composition"
        elif category.lower() in ['ciencia', 'science']:
            style_hint = "Realistic image, modern"
        elif category.lower() in ['paranormal', 'misterios', 'mysteries', 'conspiraciones']:
            style_hint = "Digital illustration/Noir"

        return (
            f"{base_prompt}, style: {style_hint}, professional quality, high resolution, "
            f"{aspect['prompt_tail']}, detailed"
        )
    def _optimize_prompt_generic(self, base_prompt, narrative, category):
        """Prompt genérico que funciona en la mayoría de servicios"""
        aspect = self._get_manual_prompt_aspect_settings()
        return f"{base_prompt}, cinematic, professional, high quality, {aspect['prompt_tail']}, detailed"
    def show_manual_prompts_dialog(self, manual_prompts):
        """Muestra diálogo con prompts y códigos para copiar"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QTabWidget, QWidget, QMessageBox, QFileDialog
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QFont, QColor
        import json

        dialog = QDialog(self)
        dialog.setWindowTitle(" Prompts para Generación Manual de Imágenes")
        dialog.setMinimumSize(1600, 900)
        dialog.resize(1800, 1000)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QTabWidget::pane {
                background-color: #1a1a1a;
                border: 1px solid #333333;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #ffffff;
                padding: 10px 20px;
                border: 1px solid #333333;
            }
            QTabBar::tab:selected {
                background-color: #3d3d3d;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #444444;
            }
            QPushButton {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #444444;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QTextEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header con información del proyecto
        project_info = manual_prompts["project_info"]
        header = QLabel(f"""
        <b style="color: #ffffff;">Proyecto:</b> <span style="color: #ffffff;">{project_info['topic']}</span> (<span style="color: #ffffff;">{project_info['category']}</span>)<br>
        <b style="color: #ffffff;">Total de segmentos:</b> <span style="color: #ffffff;">{project_info['total_segments']}</span><br>
        <b style="color: #ffffff;">Generado:</b> <span style="color: #ffffff;">{project_info['generated_at'][:19]}</span>
        """)
        header.setStyleSheet(
            "background-color: #2d2d2d; padding: 10px; border-radius: 5px; color: #ffffff;")
        layout.addWidget(header)

        # Instrucciones
        instructions_text = "<br>".join(project_info['instructions'])
        instructions = QLabel(
            f"<b style='color: #14a085;'>Instrucciones:</b><br><span style='color: #ffffff;'>{instructions_text}</span>")
        instructions.setWordWrap(True)
        instructions.setStyleSheet(
            "background-color: #1a3a2a; color: #ffffff; padding: 10px; border-radius: 5px;")
        layout.addWidget(instructions)

        # Tabs: Tabla de segmentos y JSON completo
        tabs = QTabWidget()

        # Tab 1: Tabla de segmentos
        table_tab = QWidget()
        table_layout = QVBoxLayout(table_tab)

        # Tabla con segmentos
        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels([
            "Código", "Segmento", "Timestamp", "Servicio", "Prompt", "Copiar", "Subir Imagen"
        ])

        # Estilos oscuros para la tabla
        table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                color: #ffffff;
                gridline-color: #333333;
                border: 1px solid #333333;
            }
            QTableWidget::item {
                background-color: #1a1a1a;
                color: #ffffff;
                padding: 5px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #2d4a5f;
                color: #ffffff;
            }
            QTableWidget::item:alternate {
                background-color: #252525;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #333333;
                font-weight: bold;
            }
            QTableWidget QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 15px;
            }
            QTableWidget QScrollBar::handle:vertical {
                background-color: #444444;
                min-height: 20px;
            }
            QTableWidget QScrollBar::handle:vertical:hover {
                background-color: #555555;
            }
            QTableWidget QScrollBar:horizontal {
                background-color: #1a1a1a;
                height: 15px;
            }
            QTableWidget QScrollBar::handle:horizontal {
                background-color: #444444;
                min-width: 20px;
            }
            QTableWidget QScrollBar::handle:horizontal:hover {
                background-color: #555555;
            }
        """)

        # Llenar tabla
        for seg_data in manual_prompts["segments"]:
            # Crear una fila por cada servicio
            for service_key, service_name in [
                ("gemini_veo", "Gemini Veo"),
                ("bing_image_creator", "Bing Creator"),
                ("recraft_ai", "Recraft AI"),
                ("generic", "Genérico")
            ]:
                row = table.rowCount()
                table.insertRow(row)

                # Código (columna 0) - solo en la primera fila del segmento
                if service_key == "gemini_veo":
                    code_item = QTableWidgetItem(seg_data["segment_code"])
                    code_item.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                    # Verde oscuro para destacar
                    code_item.setBackground(QColor(40, 100, 40))
                    code_item.setForeground(
                        QColor(255, 255, 255))  # Texto blanco
                    table.setItem(row, 0, code_item)
                else:
                    # Vacío para otras filas
                    table.setItem(row, 0, QTableWidgetItem(""))

                # Segmento (columna 1) - solo en la primera fila
                if service_key == "gemini_veo":
                    seg_item = QTableWidgetItem(
                        f"Segmento {seg_data['segment_number']}")
                    seg_item.setForeground(QColor(255, 255, 255))
                    table.setItem(row, 1, seg_item)
                    timestamp_item = QTableWidgetItem(seg_data["timestamp"])
                    timestamp_item.setForeground(QColor(200, 200, 200))
                    table.setItem(row, 2, timestamp_item)
                else:
                    table.setItem(row, 1, QTableWidgetItem(""))
                    table.setItem(row, 2, QTableWidgetItem(""))

                # Servicio (columna 3)
                service_item = QTableWidgetItem(service_name)
                # Azul claro para servicios
                service_item.setForeground(QColor(180, 200, 255))
                table.setItem(row, 3, service_item)

                # Prompt (columna 4) - mostrar completo
                prompt_text = seg_data["prompts"][service_key]
                prompt_item = QTableWidgetItem(prompt_text)
                # Tooltip con prompt completo
                prompt_item.setToolTip(prompt_text)
                # Permitir que el texto se ajuste en múltiples líneas
                prompt_item.setTextAlignment(
    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                # Texto gris claro para mejor legibilidad
                prompt_item.setForeground(QColor(220, 220, 220))
                table.setItem(row, 4, prompt_item)

                # Botón copiar (columna 5)
                copy_btn = QPushButton(" Copiar")
                copy_btn.setMaximumWidth(100)
                copy_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2d2d2d;
                        color: #ffffff;
                        border: 1px solid #444444;
                        padding: 5px;
                        border-radius: 3px;
                    }
                    QPushButton:hover {
                        background-color: #3d3d3d;
                        border: 1px solid #555555;
                    }
                """)
                copy_btn.clicked.connect(
                    lambda checked, prompt=prompt_text: self.copy_to_clipboard(
                        prompt)
                )
                table.setCellWidget(row, 5, copy_btn)

                # Botón subir imagen (columna 6) - solo en la primera fila del
                # segmento (Gemini Veo)
                if service_key == "gemini_veo":
                    upload_btn = QPushButton(" Subir Imagen")
                    upload_btn.setMaximumWidth(120)
                    upload_btn.setStyleSheet("""
                        QPushButton {
                            background-color: #3498db;
                            color: white;
                            font-weight: bold;
                            padding: 5px;
                            border-radius: 3px;
                        }
                        QPushButton:hover {
                            background-color: #2980b9;
                        }
                    """)
                    upload_btn.clicked.connect(
                        lambda checked, seg_code=seg_data["segment_code"], seg_num=seg_data['segment_number']:
                        self.upload_image_for_segment(
                            seg_code, seg_num, manual_prompts)
                    )
                    table.setCellWidget(row, 6, upload_btn)
                else:
                    # Para otras filas, dejar vacío o mostrar un indicador
                    table.setItem(row, 6, QTableWidgetItem(""))

        # Configurar anchos de columnas
        table.setColumnWidth(0, 100)  # Código
        table.setColumnWidth(1, 120)  # Segmento
        table.setColumnWidth(2, 150)  # Timestamp
        table.setColumnWidth(3, 150)  # Servicio
        # Prompt - mucho más ancho para ver todo el texto
        table.setColumnWidth(4, 800)
        table.setColumnWidth(5, 100)  # Copiar
        table.setColumnWidth(6, 120)  # Subir Imagen

        # Permitir ajuste de altura de filas según contenido
        table.resizeRowsToContents()

        # Hacer que las columnas sean ajustables
        header = table.horizontalHeader()
        header.setSectionResizeMode(
    4, QHeaderView.ResizeMode.Interactive)  # Prompt ajustable
        header.setStretchLastSection(False)
        table.setAlternatingRowColors(True)

        # Asegurar que todas las celdas tengan texto visible
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is None:
                    # Crear item vacío con estilo oscuro
                    empty_item = QTableWidgetItem("")
                    empty_item.setForeground(QColor(255, 255, 255))
                    table.setItem(row, col, empty_item)
                elif item.foreground().color() == QColor(0, 0, 0):  # Si es negro, cambiarlo a blanco
                    item.setForeground(QColor(255, 255, 255))
        table_layout.addWidget(table)

        tabs.addTab(table_tab, " Tabla de Prompts")

        # Tab 2: JSON completo
        json_tab = QWidget()
        json_layout = QVBoxLayout(json_tab)

        json_label = QLabel(
            "JSON completo con todos los prompts (útil para referencia o scripts):")
        json_label.setStyleSheet("color: #ffffff;")
        json_layout.addWidget(json_label)

        json_text = QTextEdit()
        json_text.setReadOnly(True)
        json_text.setFont(QFont("Consolas", 9))
        json_text.setPlainText(
    json.dumps(
        manual_prompts,
        indent=2,
         ensure_ascii=False))
        json_layout.addWidget(json_text)

        copy_json_btn = QPushButton(" Copiar JSON Completo")
        copy_json_btn.clicked.connect(
            lambda: self.copy_to_clipboard(
    json.dumps(
        manual_prompts,
        indent=2,
         ensure_ascii=False))
        )
        json_layout.addWidget(copy_json_btn)

        tabs.addTab(json_tab, " JSON Completo")

        layout.addWidget(tabs)

        # Botones de acción
        buttons = QHBoxLayout()

        export_json_btn = QPushButton(" Guardar JSON en Archivo")
        export_json_btn.clicked.connect(
    lambda: self.export_manual_prompts_json(manual_prompts))
        buttons.addWidget(export_json_btn)

        load_images_btn = QPushButton(" Cargar Imágenes Generadas")
        load_images_btn.clicked.connect(
    lambda: self.load_manual_images(manual_prompts))
        buttons.addWidget(load_images_btn)

        buttons.addStretch()

        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(close_btn)

        layout.addLayout(buttons)

        dialog.exec()
    def copy_to_clipboard(self, text):
        """Copia texto al portapapeles"""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.studio_tab.log(f" Prompt copiado al portapapeles")
        QMessageBox.information(
    self, "Copiado", "Prompt copiado al portapapeles")
    def export_manual_prompts_json(self, manual_prompts):
        """Exporta los prompts manuales a un archivo JSON"""
        from PyQt6.QtWidgets import QFileDialog
        import json

        topic = manual_prompts["project_info"]["topic"]
        safe_topic = "".join(c for c in topic[:30] if c.isalnum() or c in (
            ' ', '-', '_')).replace(' ', '_')

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar Prompts Manuales",
            f"manual_prompts_{safe_topic}.json",
            "Archivos JSON (*.json);;Todos los archivos (*.*)"
        )

        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(manual_prompts, f, indent=2, ensure_ascii=False)
                self.studio_tab.log(f" JSON guardado en: {filename}")
                QMessageBox.information(
    self, "Guardado", f"JSON guardado exitosamente:\n\n{filename}")
            except Exception as e:
                QMessageBox.critical(
    self, "Error", f"Error guardando JSON:\n{e}")
    def load_manual_images(self, manual_prompts):
        """Carga imágenes generadas manualmente y las mapea a segmentos"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from pathlib import Path

        # Diálogo para seleccionar carpeta con imágenes
        folder = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta con imágenes generadas",
            ""
        )

        if not folder:
            return

        # Buscar imágenes por código o por nombre
        folder_path = Path(folder)
        mapped_images = {}
        found_count = 0

        self.studio_tab.log(f"\n Buscando imágenes en: {folder}")

        for seg_data in manual_prompts["segments"]:
            code = seg_data["segment_code"]
            filename = seg_data["filename"]

            # Buscar por código (ej: SEG001.png, SEG001.jpg, etc.)
            found = False
            for ext in ['.png', '.jpg', '.jpeg', '.webp']:
                code_file = folder_path / f"{code}{ext}"
                if code_file.exists():
                    mapped_images[code] = str(code_file)
                    found = True
                    found_count += 1
                    self.studio_tab.log(f"    {code}: {code_file.name}")
                    break

            # Si no se encontró por código, buscar por filename
            if not found:
                for ext in ['.png', '.jpg', '.jpeg', '.webp']:
                    if filename.endswith(ext):
                        filename_file = folder_path / filename
                    else:
                        filename_file = folder_path / f"{filename}{ext}"

                    if filename_file.exists():
                        mapped_images[code] = str(filename_file)
                        found = True
                        found_count += 1
                        self.studio_tab.log(
                            f"    {code}: {filename_file.name} (por filename)")
                        break

        # Asignar imágenes a segmentos
        if mapped_images:
            self.assign_manual_images_to_segments(
                mapped_images, manual_prompts)
            QMessageBox.information(
                self,
                "Imágenes Cargadas",
                f" Se mapearon {found_count} imágenes a sus segmentos correspondientes\n\n"
                f"Imágenes encontradas: {found_count}/{len(manual_prompts['segments'])}"
            )
        else:
            QMessageBox.warning(
                self,
                "Sin Imágenes",
                "No se encontraron imágenes con los códigos esperados.\n\n"
                "Asegúrate de que las imágenes estén renombradas como:\n"
                "SEG001.png, SEG002.png, etc.\n\n"
                "O que tengan los nombres de archivo originales del storyboard."
            )
    def upload_image_for_segment(
    self,
    segment_code,
    segment_number,
     manual_prompts):
        """Permite subir una imagen específica para un segmento"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from pathlib import Path

        # Diálogo para seleccionar archivo de imagen
        image_file, _ = QFileDialog.getOpenFileName(
            self,
            f"Subir imagen para {segment_code} (Segmento {segment_number})",
            "",
            "Imágenes (*.png *.jpg *.jpeg *.webp);;Todos los archivos (*.*)"
        )

        if not image_file:
            return

        # Verificar que el archivo existe
        if not os.path.exists(image_file):
            QMessageBox.warning(
    self, "Error", f"El archivo no existe:\n{image_file}")
            return

        # Mapear la imagen al segmento
        mapped_images = {segment_code: image_file}

        # Asignar la imagen al segmento
        self.assign_manual_images_to_segments(mapped_images, manual_prompts)

        QMessageBox.information(
            self,
            "Imagen Subida",
            f" Imagen subida exitosamente para {segment_code}\n\n"
            f"Archivo: {os.path.basename(image_file)}"
        )
    def assign_manual_images_to_segments(self, mapped_images, manual_prompts):
        """Asigna las imágenes mapeadas a los segmentos del storyboard"""
        if not self.studio_tab.last_storyboard_data:
            return

        segments = self.studio_tab.last_storyboard_data.get('segments', [])
        assigned_count = 0

        for seg in segments:
            seg_num = seg.get('segment_number', 0)
            code = f"SEG{seg_num:03d}"

            if code in mapped_images:
                image_path = mapped_images[code]
                seg['image_path'] = image_path
                assigned_count += 1
                self.studio_tab.log(
                    f"    Imagen asignada a segmento {seg_num}: {os.path.basename(image_path)}")

        # Actualizar timeline (SÍ buscar imágenes porque fueron asignadas
        # manualmente)
        self.studio_tab.populate_review_panel(
    self.studio_tab.last_storyboard_data,
     auto_search_images=True)
        self.studio_tab.log(f"\n {assigned_count} imágenes asignadas a segmentos")


