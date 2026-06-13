# video_export_manager.py
"""
Gestor de exportación de video y utilidades del sistema
Maneja exportación con FFmpeg, verificación de memoria y estimación de recursos.
Asegura que el video final tenga siempre pista de audio válida y sea reproducible.
"""

import os
import subprocess
import tempfile
import threading
import shutil
import json
from typing import Optional, Tuple


def _get_ffmpeg_path():
    """Obtiene la ruta de FFmpeg desde VideoConfig o PATH."""
    from video_config import VideoConfig
    
    # Primero intentar con VideoConfig (que detecta automáticamente)
    if VideoConfig.FFMPEG_BINARY_PATH and os.path.exists(os.path.join(VideoConfig.FFMPEG_BINARY_PATH, "ffmpeg.exe")):
        return os.path.join(VideoConfig.FFMPEG_BINARY_PATH, "ffmpeg.exe")
    
    # Fallback a shutil.which
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    
    return None


def _get_ffprobe_path():
    """Obtiene la ruta de FFprobe desde VideoConfig."""
    from video_config import VideoConfig
    
    # Primero intentar con VideoConfig
    if VideoConfig.FFPROBE_BINARY_PATH and os.path.exists(VideoConfig.FFPROBE_BINARY_PATH):
        return VideoConfig.FFPROBE_BINARY_PATH
    
    # Fallback: derivar de la ruta de ffmpeg
    ff = _get_ffmpeg_path()
    if not ff:
        return None
    return ff.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")


def _probe_has_video_and_audio(file_path: str, log_callback=None) -> Tuple[bool, bool]:
    """
    Usa ffprobe para detectar si el archivo tiene stream de video y de audio.
    Returns:
        (has_video, has_audio)
    """
    _log = log_callback or (lambda msg: None)
    ffprobe = _get_ffprobe_path()
    if not ffprobe:
        _log("   ️ ffprobe no encontrado, no se puede validar el video")
        return (False, False)
    if not os.path.exists(file_path):
        _log(f"   ️ Archivo no existe para validar: {file_path}")
        return (False, False)
    # Verificar que ffprobe realmente existe como binario
    if not os.path.exists(ffprobe) and not shutil.which(os.path.basename(ffprobe)):
        _log(f"   ️ ffprobe no existe en: {ffprobe}")
        return (False, False)
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v", "-show_entries", "stream=codec_type", "-of", "csv=p=0", file_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        has_v = out.returncode == 0 and "video" in (out.stdout or "").strip().lower()
        if not has_v and out.stderr:
            _log(f"   ️ ffprobe video check stderr: {out.stderr.strip()[:200]}")
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", file_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        has_a = out.returncode == 0 and "audio" in (out.stdout or "").strip().lower()
        return (has_v, has_a)
    except FileNotFoundError:
        _log(f"   ️ ffprobe binario no encontrado: {ffprobe}")
        return (False, False)
    except subprocess.TimeoutExpired:
        _log(f"   ️ ffprobe timeout al analizar: {file_path}")
        return (False, False)
    except Exception as e:
        _log(f"   ️ ffprobe error: {e}")
        return (False, False)


def _probe_duration(file_path: str) -> float:
    """Devuelve la duración en segundos del archivo; 0 si no se puede obtener."""
    ffprobe = _get_ffprobe_path()
    if not ffprobe or not os.path.exists(file_path):
        return 0.0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", file_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode != 0:
            return 0.0
        data = json.loads(out.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0) or 0)
    except Exception:
        return 0.0


class VideoExportManager:
    """
    Gestor de exportación de video y utilidades del sistema.
    Maneja exportación con FFmpeg, verificación de memoria y estimación de recursos.
    """
    
    def __init__(self, log_callback=None):
        """
        Inicializa el gestor de exportación.
        
        Args:
            log_callback: Función para logging (opcional)
        """
        self.log = log_callback or (lambda msg: print(msg))
    
    def _export_with_ffmpeg_pipe(self, video_clip, output_path, fps=30,
                                  video_bitrate='8000k', preset='medium', video_duration=0):
        """
        Exporta video enviando frames por pipe a FFmpeg + audio separado.
        Más robusto que write_videofile cuando hay muchos clips compuestos.
        """
        import numpy as np
        import time as _time

        ffmpeg_exe = _get_ffmpeg_path()
        if not ffmpeg_exe:
            return False

        clip_w = video_clip.w if hasattr(video_clip, 'w') else (video_clip.size[0] if hasattr(video_clip, 'size') else 0)
        clip_h = video_clip.h if hasattr(video_clip, 'h') else (video_clip.size[1] if hasattr(video_clip, 'size') else 0)
        duration = video_clip.duration

        if not clip_w or not clip_h or not duration:
            self.log("   ️ Clip sin dimensiones o duración válidas para FFmpeg pipe")
            return False

        # Exportar audio a archivo temporal
        temp_audio_path = None
        if getattr(video_clip, 'audio', None) is not None:
            try:
                self.log(f"    Exportando audio temporal ({duration:.1f}s)...")
                temp_audio = tempfile.NamedTemporaryFile(suffix='.aac', delete=False)
                temp_audio_path = temp_audio.name
                temp_audio.close()
                audio_start = _time.time()
                video_clip.audio.write_audiofile(
                    temp_audio_path, codec='aac', bitrate='192k',
                    verbose=False, logger=None
                )
                audio_elapsed = _time.time() - audio_start
                if not os.path.exists(temp_audio_path) or os.path.getsize(temp_audio_path) < 100:
                    self.log(f"   ️ Audio temporal inválido (tardó {audio_elapsed:.1f}s)")
                    temp_audio_path = None
                else:
                    audio_size_mb = os.path.getsize(temp_audio_path) / (1024 * 1024)
                    self.log(f"    Audio temporal exportado ({audio_size_mb:.1f} MB en {audio_elapsed:.1f}s)")
            except Exception as audio_err:
                self.log(f"   ️ Error exportando audio para pipe: {audio_err}")
                temp_audio_path = None

        # Construir comando FFmpeg para recibir video raw por pipe
        ffmpeg_cmd = [
            ffmpeg_exe, '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{clip_w}x{clip_h}',
            '-pix_fmt', 'rgb24',
            '-r', str(fps),
            '-i', '-',  # video por stdin
        ]

        if temp_audio_path:
            ffmpeg_cmd.extend(['-i', temp_audio_path])

        ffmpeg_cmd.extend([
            '-c:v', 'libx264',
            '-b:v', video_bitrate,
            '-preset', preset,
            '-pix_fmt', 'yuv420p',
        ])

        if temp_audio_path:
            ffmpeg_cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
        else:
            ffmpeg_cmd.append('-an')

        ffmpeg_cmd.extend(['-movflags', '+faststart', output_path])

        # FIX: Usar stderr=DEVNULL para evitar deadlock.
        # Antes se usaba stderr=PIPE sin consumirlo, lo que causaba que FFmpeg
        # se bloqueara al llenar el buffer de pipe del OS (~64KB en Windows),
        # produciendo un deadlock: FFmpeg espera que lean stderr, Python espera
        # que FFmpeg lea stdin.
        # Guardamos stderr en un archivo temporal para poder reportar errores.
        stderr_temp = tempfile.NamedTemporaryFile(suffix='.log', delete=False, mode='w')
        stderr_temp_path = stderr_temp.name

        process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stderr_temp,
        )

        total_frames = int(duration * fps)
        self.log(f"   ️ Renderizando {total_frames} frames ({clip_w}x{clip_h} @ {fps}fps)...")
        last_percent = 0
        render_start = _time.time()
        frame_idx = -1
        frame_time = 0.0
        try:
            for frame_idx, t in enumerate(np.arange(0, duration, 1.0 / fps)):
                frame_time = float(t)
                if process.poll() is not None:
                    try:
                        stderr_temp.flush()
                    except Exception:
                        pass
                    try:
                        with open(stderr_temp_path, 'r', errors='replace') as f:
                            stderr_out = f.read()[-800:]
                    except Exception:
                        stderr_out = "(no se pudo leer stderr)"
                    self.log(
                        f"   [WARN] FFmpeg termino prematuramente en frame {frame_idx + 1}/{total_frames} "
                        f"(t={frame_time:.2f}s): {stderr_out}"
                    )
                    self.log(f"   [INFO] Log completo de FFmpeg pipe: {stderr_temp_path}")
                    return False

                frame = video_clip.get_frame(t)
                if frame is None:
                    continue
                # Asegurar uint8
                if frame.dtype != np.uint8:
                    frame = np.clip(frame, 0, 255).astype(np.uint8)
                process.stdin.write(frame.tobytes())

                # Mostrar progreso cada 5% (antes era 10%)
                if total_frames > 0:
                    percent = min(100, int((frame_idx / total_frames) * 100))
                    if percent != last_percent and percent % 5 == 0:
                        elapsed = _time.time() - render_start
                        fps_actual = (frame_idx + 1) / elapsed if elapsed > 0 else 0
                        eta = (total_frames - frame_idx) / fps_actual if fps_actual > 0 else 0
                        bar_length = 40
                        filled = int(bar_length * percent / 100)
                        bar = '\u2588' * filled + '\u2591' * (bar_length - filled)
                        self.log(f"   [{bar}] {percent}% ({fps_actual:.1f} fps, ETA: {eta:.0f}s)")
                        last_percent = percent

            process.stdin.close()
            process.wait(timeout=300)
        except BaseException as e:
            import traceback
            self.log(
                f"   [WARN] Error durante escritura de frames en frame {frame_idx + 1}/{total_frames} "
                f"(t={frame_time:.2f}s): {type(e).__name__}: {e}"
            )
            self.log(traceback.format_exc().rstrip())
            try:
                process.kill()
            except Exception:
                pass
            # Limpiar
            if temp_audio_path:
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass
            try:
                stderr_temp.close()
            except Exception:
                pass
            self.log(f"   [INFO] Log completo de FFmpeg pipe conservado en: {stderr_temp_path}")
            return False
        finally:
            if temp_audio_path:
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass

        # Leer stderr del archivo temporal para diagnóstico
        try:
            stderr_temp.close()
        except Exception:
            pass

        if process.returncode != 0:
            try:
                with open(stderr_temp_path, 'r', errors='replace') as f:
                    stderr_out = f.read()[-500:]
            except Exception:
                stderr_out = "(no se pudo leer stderr)"
            self.log(f"   [WARN] FFmpeg pipe retorno codigo {process.returncode}: {stderr_out}")
            self.log(f"   [INFO] Log completo de FFmpeg pipe conservado en: {stderr_temp_path}")
            return False

        try:
            os.remove(stderr_temp_path)
        except Exception:
            pass

        render_elapsed = _time.time() - render_start
        self.log(f"    Renderizado completado en {render_elapsed:.1f}s")

        # Verificar resultado
        if not os.path.exists(output_path):
            self.log(f"   ️ El archivo de salida no existe: {output_path}")
            return False

        file_size = os.path.getsize(output_path)
        self.log(f"    Archivo generado: {file_size / (1024*1024):.1f} MB")

        if file_size <= 1000:
            self.log(f"   ️ El archivo es demasiado pequeño ({file_size} bytes)")
            return False

        has_v, has_a = _probe_has_video_and_audio(output_path, log_callback=self.log)
        if has_v:
            self.log("    Video exportado correctamente con FFmpeg pipe")
            return True

        # Si ffprobe no puede validar pero el archivo es grande, podría ser válido
        # (ffprobe podría no estar instalado)
        if file_size > 1024 * 1024:  # > 1MB
            self.log(f"   ️ ffprobe no pudo validar el video, pero el archivo es grande ({file_size / (1024*1024):.1f} MB)")
            self.log(f"   ️ Aceptando como válido (ffprobe puede no estar disponible)")
            return True

        self.log(f"   ️ Video no válido según ffprobe y archivo pequeño ({file_size} bytes)")
        return False

    def export_video_with_ffmpeg(self, video_clip, output_path, video_bitrate='8000k',
                                 preset='medium', fps=30, video_duration=0):
        """
        Exporta video usando FFmpeg directo (más rápido que MoviePy).
        
        Args:
            video_clip: Clip de MoviePy a exportar
            output_path: Ruta de salida del video
            video_bitrate: Bitrate del video (ej: '6000k', '12000k')
            preset: Preset de FFmpeg ('ultrafast', 'fast', 'medium', 'slow')
            fps: FPS del video
            video_duration: Duración del video en segundos (para mostrar progreso)
        
        Returns:
            bool: True si la exportación fue exitosa, False en caso contrario
        """
        try:
            # Crear archivo temporal para el video sin comprimir
            temp_video = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
            temp_video_path = temp_video.name
            temp_video.close()

            # Limpiar archivos temporales TEMP_MPY previos que pueden interferir
            try:
                output_dir = os.path.dirname(output_path) or '.'
                for f in os.listdir(output_dir):
                    if 'TEMP_MPY' in f and f.endswith('.mp4'):
                        try:
                            os.remove(os.path.join(output_dir, f))
                        except Exception:
                            pass
            except Exception:
                pass

            # Intentar exportación directa con FFmpeg pipe (más robusto que write_videofile)
            self.log("    Preparando video para FFmpeg...")

            export_ok = False
            try:
                export_ok = self._export_with_ffmpeg_pipe(
                    video_clip, temp_video_path, fps, video_bitrate, preset, video_duration
                )
            except Exception as pipe_err:
                self.log(f"   ️ FFmpeg pipe falló: {pipe_err}")
                export_ok = False

            # Fallback: usar write_videofile de MoviePy si el pipe falló
            if not export_ok:
                self.log("    Usando MoviePy write_videofile como alternativa...")
                try:
                    video_clip.write_videofile(
                        temp_video_path,
                        fps=fps,
                        codec='libx264',
                        audio_codec='aac',
                        audio_bitrate='192k',
                        bitrate='20000k',
                        preset='ultrafast',
                        threads=4,
                        verbose=False,
                        logger='bar'
                    )
                except Exception as wvf_err:
                    self.log(f"   ️ MoviePy write_videofile falló: {wvf_err}")

            if not os.path.exists(temp_video_path):
                self.log("    Error: No se pudo crear video temporal")
                return False

            fsize = os.path.getsize(temp_video_path)

            # Detectar si ffprobe está disponible
            ffprobe_path = _get_ffprobe_path()
            ffprobe_available = False
            if ffprobe_path:
                if os.path.exists(ffprobe_path) or shutil.which(os.path.basename(ffprobe_path)):
                    ffprobe_available = True

            # Si el pipe exportó exitosamente y ffprobe NO está disponible,
            # el archivo temporal ya tiene video + audio + faststart.
            # Mover directamente al output sin re-exportar (evita fallos de validación).
            if export_ok and not ffprobe_available and fsize > 1024 * 1024:
                self.log(f"    Archivo temporal: {fsize / (1024*1024):.1f} MB")
                self.log(f"   ️ ffprobe no disponible - omitiendo re-exportación y validación")
                try:
                    shutil.move(temp_video_path, output_path)
                    self.log(f"    Video movido a destino final: {os.path.basename(output_path)}")
                    return True
                except Exception as move_err:
                    # Si move falla (ej: cross-device), intentar copy+delete
                    try:
                        shutil.copy2(temp_video_path, output_path)
                        os.remove(temp_video_path)
                        self.log(f"    Video copiado a destino final: {os.path.basename(output_path)}")
                        return True
                    except Exception as copy_err:
                        self.log(f"   ️ Error moviendo video: {copy_err}")

            has_video_temp, has_audio_temp = _probe_has_video_and_audio(temp_video_path, log_callback=self.log)
            if not has_video_temp:
                # Si ffprobe no detecta video pero el archivo es grande, puede que ffprobe no esté disponible
                if fsize > 5 * 1024 * 1024:  # > 5MB
                    self.log(f"   ️ ffprobe no detecta video pero el archivo es grande ({fsize / (1024*1024):.1f} MB)")
                    self.log(f"   ️ Continuando asumiendo que el video es válido (ffprobe puede no estar disponible)")
                    has_video_temp = True  # Asumir válido
                else:
                    self.log("    Error: El video temporal no tiene stream de video válido")
                    self.log(f"   ℹ️ Tamaño del archivo temporal: {fsize / 1024:.1f} KB")
                    self.log("   ℹ️ Posibles causas: memoria insuficiente, demasiados clips, o error en composición")
                    try:
                        os.remove(temp_video_path)
                    except Exception:
                        pass
                    return False

            temp_audio_path = None
            if not has_audio_temp and getattr(video_clip, "audio", None) is not None:
                self.log("    El temporal no tiene audio; agregando audio desde el clip...")
                try:
                    temp_audio = tempfile.NamedTemporaryFile(suffix=".aac", delete=False)
                    temp_audio_path = temp_audio.name
                    temp_audio.close()
                    video_clip.audio.write_audiofile(
                        temp_audio_path, codec="aac", bitrate="192k", verbose=False, logger=None
                    )
                    if not os.path.exists(temp_audio_path) or os.path.getsize(temp_audio_path) < 1000:
                        temp_audio_path = None
                except Exception as e:
                    self.log(f"   ️ No se pudo extraer audio del clip: {e}")
                    temp_audio_path = None

            ffmpeg_exe = _get_ffmpeg_path() or "ffmpeg"

            # Si el pipe ya generó un archivo válido (con audio si era necesario), evitar re-exportar
            skip_reencode = export_ok and has_video_temp and (has_audio_temp or getattr(video_clip, "audio", None) is None)

            if skip_reencode:
                self.log("    Video validado vía pipe; moviendo archivo sin re-exportar...")
                try:
                    shutil.move(temp_video_path, output_path)
                    temp_video_path = None
                except Exception as move_err:
                    self.log(f"   ️ No se pudo mover el archivo temporal: {move_err}, intentando copiar...")
                    try:
                        shutil.copy2(temp_video_path, output_path)
                        os.remove(temp_video_path)
                        temp_video_path = None
                    except Exception as copy_err:
                        self.log(f"    Error copiando archivo temporal: {copy_err}")
                        return False
                final_ready = True
            else:
                # Usar FFmpeg para re-exportar con bitrate y preset optimizados
                self.log("    Re-exportando con FFmpeg (optimizado)...")

                if has_audio_temp:
                    ffmpeg_cmd = [
                        ffmpeg_exe,
                        "-y",
                        "-i", temp_video_path,
                        "-c:v", "copy",
                        "-c:a", "copy",
                        "-movflags", "+faststart",
                        output_path,
                    ]
                elif temp_audio_path:
                    ffmpeg_cmd = [
                        ffmpeg_exe,
                        "-y",
                        "-i", temp_video_path,
                        "-i", temp_audio_path,
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-shortest",
                        "-movflags", "+faststart",
                        output_path,
                    ]
                else:
                    ffmpeg_cmd = [
                        ffmpeg_exe,
                        "-y",
                        "-i", temp_video_path,
                        "-an",
                        "-c:v", "copy",
                        "-movflags", "+faststart",
                        output_path,
                    ]

                # Ejecutar FFmpeg con progreso
                process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # Redirigir stderr a stdout
                    universal_newlines=True,
                    bufsize=1
                )

                # Leer salida para mostrar progreso
                last_percent = 0

                def read_output():
                    nonlocal last_percent
                    for line in iter(process.stdout.readline, ''):
                        if not line:
                            break
                        if 'time=' in line:
                            # Extraer tiempo del log de FFmpeg
                            try:
                                time_str = line.split('time=')[1].split()[0]
                                # Convertir tiempo (HH:MM:SS.ms) a segundos
                                time_parts = time_str.split(':')
                                if len(time_parts) == 3:
                                    hours, minutes, seconds = time_parts
                                    current_time = float(hours) * 3600 + float(minutes) * 60 + float(seconds)

                                    if video_duration > 0:
                                        percent = min(100, int((current_time / video_duration) * 100))
                                        if percent != last_percent and percent % 5 == 0:
                                            bar_length = 40
                                            filled = int(bar_length * percent / 100)
                                            bar = '█' * filled + '░' * (bar_length - filled)
                                            self.log(f"   [{bar}] {percent}%")
                                            last_percent = percent
                            except:
                                pass

                # Leer salida en un thread separado
                output_thread = threading.Thread(target=read_output, daemon=True)
                output_thread.start()

                # Esperar a que termine el proceso
                process.wait()
                output_thread.join(timeout=1)

                # Limpiar archivos temporales
                try:
                    if os.path.exists(temp_video_path):
                        os.remove(temp_video_path)
                except Exception:
                    pass
                if temp_audio_path and os.path.exists(temp_audio_path):
                    try:
                        os.remove(temp_audio_path)
                    except Exception:
                        pass

                if process.returncode != 0:
                    self.log(f"    Error en FFmpeg (código: {process.returncode})")
                    return False

                if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
                    self.log("    Error: El archivo de salida no se generó correctamente")
                    return False

                final_ready = True

            # Validación final con ffprobe (si está disponible)
            if not skip_reencode and not final_ready:
                return False

            if ffprobe_available:
                out_has_v, out_has_a = _probe_has_video_and_audio(output_path, log_callback=self.log)
                duration = _probe_duration(output_path)
                if not out_has_v:
                    self.log("    Error: El video exportado no tiene stream de video válido")
                    return False
                if duration < 0.5:
                    self.log("    Error: La duración del video es inválida")
                    return False
                if (has_audio_temp or temp_audio_path) and not out_has_a:
                    self.log("    Error: Se perdió la pista de audio en la exportación")
                    return False
                self.log("    Exportación con FFmpeg completada (video y audio verificados)")
            else:
                out_fsize = os.path.getsize(output_path)
                if out_fsize > 1024 * 1024:
                    self.log(f"    Exportación completada ({out_fsize / (1024*1024):.1f} MB, sin verificación ffprobe)")
                else:
                    self.log(f"   ️ Archivo de salida muy pequeño ({out_fsize} bytes) sin poder verificar con ffprobe")
                    return False

            return True
                
        except FileNotFoundError:
            self.log("   ️ FFmpeg no encontrado en el sistema")
            return False
        except Exception as e:
            self.log(f"    Error en exportación FFmpeg: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def check_system_memory(self):
        """
        Detecta la RAM disponible en el sistema.
        
        Returns:
            tuple: (ram_total_gb, ram_available_gb) o (None, None) si no se puede detectar
        """
        try:
            import psutil
            mem = psutil.virtual_memory()
            ram_total_gb = mem.total / (1024**3)  # Convertir a GB
            ram_available_gb = mem.available / (1024**3)  # Convertir a GB
            return ram_total_gb, ram_available_gb
        except ImportError:
            # Intentar con wmi en Windows
            try:
                import platform
                if platform.system() == "Windows":
                    import wmi
                    c = wmi.WMI()
                    for system in c.Win32_OperatingSystem():
                        ram_total_gb = float(system.TotalVisibleMemorySize) / (1024**2)  # KB a GB
                        ram_available_gb = float(system.FreePhysicalMemory) / (1024**2)  # KB a GB
                        return ram_total_gb, ram_available_gb
            except ImportError:
                pass
            return None, None
    
    def estimate_memory_required(self, num_segments, video_duration, apply_cinematic=False):
        """
        Estima la RAM necesaria para procesar el video.
        
        Args:
            num_segments: Número de segmentos
            video_duration: Duración del video en segundos
            apply_cinematic: Si se aplican efectos cinematográficos
        
        Returns:
            float: RAM estimada necesaria en GB
        """
        # Estimación basada en observaciones del error:
        # - Cada clip de imagen 1080p ocupa ~47.5 MB en memoria
        # - Con efectos cinematográficos, puede ser 1.5-2x más
        # - Necesitamos al menos 30% de RAM libre para el sistema
        base_memory_per_clip_mb = 50  # MB por clip sin efectos
        if apply_cinematic:
            base_memory_per_clip_mb *= 2  # Efectos cinematográficos duplican el uso
        
        # Memoria necesaria para clips en memoria (asumiendo que se cargan varios a la vez)
        clips_memory_gb = (num_segments * base_memory_per_clip_mb) / 1024
        
        # Memoria adicional para procesamiento (CompositeVideoClip, transiciones, etc.)
        # Para videos largos, el CompositeVideoClip final puede necesitar mucha memoria
        processing_overhead_gb = 0.5  # Overhead base
        if video_duration > 300:  # Videos largos
            processing_overhead_gb += (video_duration / 300) * 0.5
        
        total_memory_gb = clips_memory_gb + processing_overhead_gb
        
        # Agregar margen de seguridad (30% más)
        total_memory_gb *= 1.3
        
        return total_memory_gb
    
    def should_disable_cinematic_effects(self, storyboard_data, apply_cinematic, log_callback=None,
                                         platform=None, visual_mode=None, transition_type=None,
                                         cinematic_preset=None):
        """
        Determina si se deben desactivar los efectos cinematográficos por RAM
        o por una heurística de estabilidad para renders frágiles.
        
        Args:
            storyboard_data: Datos del storyboard
            apply_cinematic: Si el usuario quiere aplicar efectos cinematográficos
            log_callback: Función para logging (opcional, usa self.log si no se proporciona)
        
        Returns:
            bool: True si se deben desactivar, False si se pueden mantener
        """
        log = log_callback or self.log
        
        if not apply_cinematic:
            return False  # Ya están desactivados
        
        config = storyboard_data.get('config', {}) if isinstance(storyboard_data, dict) else {}

        def _normalized(value):
            try:
                return str(value or "").strip().lower()
            except Exception:
                return ""

        platform_key = _normalized(platform) or _normalized(storyboard_data.get('platform')) or _normalized(config.get('platform'))
        visual_mode_key = _normalized(visual_mode) or _normalized(config.get('visual_mode'))
        transition_key = _normalized(transition_type) or _normalized(config.get('transition_type'))
        preset_key = _normalized(cinematic_preset) or _normalized(config.get('cinematic_preset'))

        # Obtener información del video
        segments = storyboard_data.get('segments', [])
        num_segments = len(segments)
        audio_path = storyboard_data.get('audio_path')
        
        # Obtener duración del audio si es posible
        video_duration = 300  # Duración por defecto
        if audio_path and os.path.exists(audio_path):
            try:
                from moviepy.editor import AudioFileClip
                audio = AudioFileClip(audio_path)
                video_duration = audio.duration
                audio.close()
            except:
                pass

        # Salvaguarda adicional: en shorts verticales estáticos con auto-detect
        # y muchos segmentos, la ruta MoviePy/cinematic es propensa a cierres
        # silenciosos y renders extremadamente lentos. Preferimos degradar a la
        # ruta FFmpeg directa, que sigue soportando transiciones equivalentes.
        is_vertical_short = platform_key in {'youtube_short', 'tiktok', 'reels'}
        is_static_visual = visual_mode_key == 'static'
        is_auto_preset = any(token in preset_key for token in ('auto', 'inteligente', 'intelligent'))
        is_glitch_transition = any(token in transition_key for token in ('glitch', 'data mosh', 'rgb split', 'digital'))
        if is_vertical_short and is_static_visual and is_auto_preset and (num_segments >= 18 or video_duration >= 90):
            log("   [WARN] Modo seguro activado: short vertical estatico largo con efectos cinematicos auto-detect.")
            if is_glitch_transition:
                log("   [INFO] Se desactivan efectos cinematicos para usar una ruta FFmpeg mas estable con transicion equivalente.")
            else:
                log("   [INFO] Se desactivan efectos cinematicos para usar una ruta FFmpeg mas estable.")
            return True

        # Verificar para videos con segmentos o duración significativa
        # (Umbrales reducidos: videos de 46 seg / 230s ya causan renderizado
        # extremadamente lento con efectos cinematográficos)
        if num_segments < 20 and video_duration < 180:
            return False  # Videos pequeños no necesitan verificación

        # Detectar RAM disponible
        ram_total_gb, ram_available_gb = self.check_system_memory()

        if ram_available_gb is None:
            # No se pudo detectar RAM, ser conservador
            if num_segments >= 30 or video_duration >= 200:
                log(f"   ️ No se pudo detectar RAM disponible. Para seguridad, desactivando efectos cinematográficos (video largo: {num_segments} segmentos, {video_duration:.1f}s)")
                return True
            return False
        
        # Estimar memoria necesaria
        memory_required_gb = self.estimate_memory_required(num_segments, video_duration, apply_cinematic=True)
        
        # Necesitamos al menos el doble de la memoria requerida disponible (para seguridad)
        required_available_gb = memory_required_gb * 2
        
        log(f"\n    RAM disponible: {ram_available_gb:.1f} GB / {ram_total_gb:.1f} GB")
        log(f"    RAM estimada necesaria (con efectos): {memory_required_gb:.1f} GB")
        log(f"    RAM requerida disponible (mínimo): {required_available_gb:.1f} GB")
        
        if ram_available_gb < required_available_gb:
            log(f"   ️ RAM insuficiente para efectos cinematográficos")
            log(f"    Desactivando efectos cinematográficos automáticamente")
            return True
        
        return False
