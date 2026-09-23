# auto_video_generator_pyqt6_adapter.py
"""
Adaptador PyQt6 para AutoVideoGenerator que permite usar el generador
sin modificar su código original, redirigiendo los logs a señales Qt.
"""

from PyQt6.QtCore import QObject, pyqtSignal
import socket
import time
from auto_video_generator_v2 import AutoVideoGenerator as OriginalGenerator


class AutoVideoGeneratorPyQt6(QObject):
    """
    Wrapper de AutoVideoGenerator que emite señales PyQt6 para logging.
    Esto permite usar el generador original sin modificarlo.
    """
    
    # Señales para comunicación con la GUI
    log_signal = pyqtSignal(str)  # Emite mensajes de log
    progress_signal = pyqtSignal(int)  # Emite progreso (0-100)
    status_signal = pyqtSignal(str)  # Emite estado actual
    error_signal = pyqtSignal(str)  # Emite errores
    
    def __init__(self):
        super().__init__()
        
        # Crear instancia original del generador (acepta parent_window como parámetro)
        self._generator = OriginalGenerator(parent_window=None)
        
        # Reemplazar el método log con nuestro wrapper
        self._generator.log = self._log_wrapper
    
    def _log_wrapper(self, message):
        """Wrapper que convierte llamadas a log() en señales Qt"""
        try:
            # Emitir la señal de log
            self.log_signal.emit(message)

            # También imprimir en consola (opcional)
            print(message, flush=True)

            # Detectar cambios de estado basados en el mensaje
            if "PASO 1" in message or "STORYBOARD" in message:
                self.status_signal.emit("Generando Storyboard...")
            elif "PASO 2" in message or "ENSAMBLANDO" in message:
                self.status_signal.emit("Ensamblando Video...")
            elif "" in message and "COMPLETADO" in message:
                self.status_signal.emit("Completado")
            elif "" in message or "ERROR" in message:
                self.error_signal.emit(message)
        except Exception as e:
            # Nunca dejar que un error en logging mate el proceso
            print(f"[_log_wrapper error: {e}] {message}")
    
    # ========== MÉTODOS PROXY ==========
    # Estos métodos simplemente llaman a los métodos originales
    
    def generate_storyboard(self, *args, **kwargs):
        """Proxy para generate_storyboard_data con mapeo de parámetros"""
        # Mapear duration_seconds -> custom_duration si existe
        if 'duration_seconds' in kwargs:
            kwargs['custom_duration'] = kwargs.pop('duration_seconds')
        
        # Filtrar parámetros no soportados por generate_storyboard_data
        supported_params = {
            'topic', 'category', 'platform', 'custom_duration', 
            'voice_id', 'find_auto_music', 'style', 'language',
            'pre_research_snippets', 'rate', 'format_archetype'
        }
        
        # Remover parámetros no soportados
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in supported_params}
        
        return self._generator.generate_storyboard_data(*args, **filtered_kwargs)
    
    def assemble_video_from_storyboard(self, *args, **kwargs):
        """Proxy para assemble_video_from_storyboard"""
        return self._generator.assemble_video_from_storyboard(*args, **kwargs)
    
    def process_manual_json(self, *args, **kwargs):
        """Proxy para process_manual_json"""
        return self._generator.process_manual_json(*args, **kwargs)

    def get_recraft_prompt_for_segment(self, *args, **kwargs):
        """Proxy para resolver prompt Recraft por segmento."""
        return self._generator.get_recraft_prompt_for_segment(*args, **kwargs)
    
    # Exponer propiedades importantes del generador original
    @property
    def gemini_client(self):
        return self._generator.gemini_client
    
    @property
    def runway_client(self):
        return self._generator.runway_client
    
    @property
    def leonardo_client(self):
        return self._generator.leonardo_client
    
    @property
    def tts_generator(self):
        """Alias para acceder al TTS (en el original se llama 'tts')"""
        return self._generator.tts
    
    @property
    def tts(self):
        """Acceso directo al TTS"""
        return self._generator.tts


class VideoGenerationWorker(QObject):
    """
    Worker para ejecutar la generación de video en un thread separado.
    Esto evita bloquear la GUI durante operaciones largas.
    """
    
    # Señales del worker
    finished = pyqtSignal(dict)  # Emite resultado cuando termina
    error = pyqtSignal(str)  # Emite error si falla
    progress = pyqtSignal(str)  # Emite mensajes de progreso
    
    def __init__(self, generator, operation_type):
        super().__init__()
        self.generator = generator
        self.operation_type = operation_type
        self.params = {}
    
    def set_params(self, **kwargs):
        """Configura los parámetros para la operación"""
        self.params = kwargs

    def _is_transient_network_error(self, message: str) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False
        markers = (
            "connection reset",
            "connection aborted",
            "connection refused",
            "connection timed out",
            "network is unreachable",
            "temporary failure in name resolution",
            "name or service not known",
            "max retries exceeded",
            "remote end closed connection",
            "no route to host",
            "timeout",
            "timed out",
            "dns",
            "socket",
            "connection error",
        )
        return any(marker in text for marker in markers)

    def _has_internet_connection(self, timeout_seconds: float = 2.0) -> bool:
        probes = (("1.1.1.1", 53), ("8.8.8.8", 53))
        for host, port in probes:
            try:
                conn = socket.create_connection((host, port), timeout=timeout_seconds)
                conn.close()
                return True
            except OSError:
                continue
        return False

    def _wait_for_reconnection(self, timeout_seconds: int = 90, interval_seconds: int = 3) -> bool:
        deadline = time.time() + max(1, int(timeout_seconds))
        while time.time() < deadline:
            if self._has_internet_connection():
                return True
            time.sleep(max(1, int(interval_seconds)))
        return False

    def _run_with_network_resume(self, operation_callable, operation_label: str, max_attempts: int = 4,
                                 retry_on_none: bool = False):
        attempts = max(1, int(max_attempts))
        for attempt in range(1, attempts + 1):
            try:
                result = operation_callable()
            except Exception as e:
                transient = self._is_transient_network_error(str(e)) or not self._has_internet_connection()
                if transient and attempt < attempts:
                    self.progress.emit(
                        f"️ Conexión interrumpida durante {operation_label} "
                        f"(intento {attempt}/{attempts}). Esperando reconexión..."
                    )
                    if self._wait_for_reconnection():
                        self.progress.emit(f" Conexión restablecida. Reanudando {operation_label}...")
                        continue
                    self.progress.emit(" No se restableció internet a tiempo. Se detiene la operación.")
                raise

            if result:
                return result

            if not retry_on_none:
                return result

            if attempt < attempts:
                if not self._has_internet_connection():
                    self.progress.emit(
                        f"️ Sin internet durante {operation_label} "
                        f"(intento {attempt}/{attempts}). Esperando reconexión..."
                    )
                    if self._wait_for_reconnection():
                        self.progress.emit(f" Conexión restablecida. Reanudando {operation_label}...")
                        continue
                    self.progress.emit(" No se restableció internet a tiempo. Se detiene la operación.")
                    return result

                # Reintento ligero para caídas transitorias del proveedor (aunque internet local siga activa).
                if attempt == 1:
                    self.progress.emit(f" Reintentando {operation_label} por respuesta vacía...")
                    time.sleep(2)
                    continue

            return result

        return None
    
    def run(self):
        """Ejecuta la operación en el thread"""
        try:
            if self.operation_type == "storyboard":
                result = self._run_with_network_resume(
                    lambda: self.generator.generate_storyboard(**self.params),
                    operation_label="generación de storyboard",
                    max_attempts=4,
                    retry_on_none=True
                )
            elif self.operation_type == "assemble":
                result = self.generator.assemble_video_from_storyboard(**self.params)
            elif self.operation_type == "manual_json":
                result = self.generator.process_manual_json(**self.params)
            elif self.operation_type == "generate_images":
                # Nueva operación: generar todas las imágenes
                result = self._run_with_network_resume(
                    lambda: self.generator._generator.generate_all_images_for_storyboard(**self.params),
                    operation_label="generación de imágenes",
                    max_attempts=4,
                    retry_on_none=True
                )
            elif self.operation_type == "export_recraft_prompts":
                result = self._run_with_network_resume(
                    lambda: self.generator._generator.export_recraft_prompts_to_txt(**self.params),
                    operation_label="exportaciÃ³n de prompts Recraft",
                    max_attempts=4,
                    retry_on_none=True
                )
            elif self.operation_type == "generate_teaser":
                # Nueva operación: generar short teaser
                result = self.generator._generator.generate_short_teaser_from_long_video(**self.params)
            elif self.operation_type == "assemble_multi":
                import copy

                params = dict(self.params or {})
                platforms = list(params.pop("platforms", []) or [])
                storyboard_data = params.pop("storyboard_data", None)
                if not platforms:
                    raise ValueError("No se definieron plataformas para ensamblaje múltiple")
                if not isinstance(storyboard_data, dict):
                    raise ValueError("storyboard_data inválido para ensamblaje múltiple")

                shared_storyboard = copy.deepcopy(storyboard_data)
                results = []
                total = len(platforms)
                for idx, platform_name in enumerate(platforms, start=1):
                    self.progress.emit(
                        f" Ensamblando formato {platform_name} ({idx}/{total})..."
                    )
                    call_params = dict(params)
                    call_params["platform"] = platform_name
                    if idx > 1:
                        # Evitar teaser duplicado al correr múltiples formatos.
                        call_params["generate_short_teaser"] = False
                    part_result = self.generator.assemble_video_from_storyboard(
                        storyboard_data=shared_storyboard,
                        **call_params
                    )
                    if not part_result:
                        raise Exception(f"No se pudo ensamblar formato {platform_name}")
                    part_result["platform"] = platform_name
                    results.append(part_result)

                primary = results[0]
                primary["video_paths_by_platform"] = {
                    item.get("platform", f"format_{i+1}"): item.get("video_path")
                    for i, item in enumerate(results)
                }
                primary["multi_format_results"] = results
                result = primary
            else:
                raise ValueError(f"Operación desconocida: {self.operation_type}")
            
            if result:
                self.finished.emit(result)
            else:
                # Mensaje más específico según el tipo de operación
                if self.operation_type == "generate_teaser":
                    self.error.emit("No se pudo generar el Short Teaser. Verifica que Claude CLI esté funcionando correctamente y revisa los logs para más detalles.")
                else:
                    self.error.emit("La operación no devolvió resultados")
                
        except Exception as e:
            import traceback as tb
            error_str = str(e).lower()
            
            # Detectar errores de cuotas agotadas
            if "quota" in error_str or "cuota" in error_str or "agotada" in error_str:
                if self.operation_type == "generate_teaser":
                    self.error.emit(
                        " Error: Cuotas de Claude API agotadas\n\n"
                        "Las cuotas de tu plan de Claude se han agotado. "
                        "Las cuotas se repondrán automáticamente en unas horas. "
                        "Por favor, intenta más tarde.\n\n"
                        "Mientras tanto, puedes usar el botón ' Preparar Short Teaser para YouTube' "
                        "si ya tienes un teaser generado anteriormente."
                    )
                else:
                    self.error.emit(
                        f" Error: Cuotas de Claude API agotadas\n\n"
                        f"Las cuotas de tu plan de Claude se han agotado. "
                        f"Las cuotas se repondrán automáticamente en unas horas.\n\n"
                        f"Error original: {str(e)}"
                    )
            else:
                error_msg = f"{str(e)}\n\n{tb.format_exc()}"
                self.error.emit(error_msg)

# ========== EJEMPLO DE USO ==========
"""
# En tu GUI PyQt6:

class MyGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Crear el generador adaptado
        self.generator = AutoVideoGeneratorPyQt6()
        
        # Conectar señales
        self.generator.log_signal.connect(self.on_log)
        self.generator.status_signal.connect(self.on_status_change)
        self.generator.error_signal.connect(self.on_error)
        
    def on_log(self, message):
        # Mostrar en el log de la GUI
        self.log_text.append(message)
    
    def on_status_change(self, status):
        # Actualizar label de estado
        self.status_label.setText(status)
    
    def on_error(self, error):
        # Mostrar mensaje de error
        QMessageBox.critical(self, "Error", error)
    
    def generate_video(self):
        # Crear worker
        self.worker = VideoGenerationWorker(self.generator, "storyboard")
        self.worker.set_params(
            topic="Misterios Antiguos",
            category="Historia",
            duration_seconds=60,
            # ... más parámetros
        )
        
        # Conectar señales del worker
        self.worker.finished.connect(self.on_generation_complete)
        self.worker.error.connect(self.on_generation_error)
        
        # Ejecutar en thread
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.thread.start()
"""
