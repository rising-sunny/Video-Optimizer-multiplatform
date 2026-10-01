"""
Utilidades para manejar errores de lectura/escritura en Google Drive.

Google Drive puede causar errores OSError [Errno 22] Invalid argument
cuando está sincronizando archivos o cuando hay accesos concurrentes.
Este módulo proporciona funciones con reintentos automáticos.
"""

import time
import shutil
import os
from pathlib import Path
from typing import Optional, Callable, Any
import functools


def retry_on_gdrive_error(
    max_retries: int = 3,
    delay: float = 0.5,
    backoff: float = 2.0,
    exceptions: tuple = (OSError,)
):
    """
    Decorador que reintenta una función si falla con errores típicos de Google Drive.

    Args:
        max_retries: Número máximo de reintentos
        delay: Delay inicial entre reintentos (segundos)
        backoff: Multiplicador del delay en cada reintento
        exceptions: Tupla de excepciones a capturar
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    # Solo reintentar en errores específicos de I/O
                    if hasattr(e, 'errno') and e.errno in (22, 5, 13):  # Invalid argument, I/O error, Permission denied
                        if attempt < max_retries:
                            time.sleep(current_delay)
                            current_delay *= backoff
                            continue
                    raise

            raise last_exception
        return wrapper
    return decorator


@retry_on_gdrive_error(max_retries=3, delay=0.3)
def safe_copy2(src: str | Path, dst: str | Path) -> str:
    """
    Copia un archivo con reintentos automáticos para Google Drive.

    Args:
        src: Ruta del archivo origen
        dst: Ruta del archivo destino

    Returns:
        Ruta del archivo destino
    """
    return shutil.copy2(src, dst)


@retry_on_gdrive_error(max_retries=3, delay=0.3)
def safe_read_file(filepath: str | Path, mode: str = 'r', encoding: str = 'utf-8') -> str | bytes:
    """
    Lee un archivo con reintentos automáticos para Google Drive.

    Args:
        filepath: Ruta del archivo
        mode: Modo de apertura ('r', 'rb', etc.)
        encoding: Encoding para modo texto

    Returns:
        Contenido del archivo
    """
    kwargs = {'mode': mode}
    if 'b' not in mode:
        kwargs['encoding'] = encoding

    with open(filepath, **kwargs) as f:
        return f.read()


@retry_on_gdrive_error(max_retries=3, delay=0.3)
def safe_write_file(filepath: str | Path, content: str | bytes, mode: str = 'w', encoding: str = 'utf-8') -> None:
    """
    Escribe un archivo con reintentos automáticos para Google Drive.

    Args:
        filepath: Ruta del archivo
        content: Contenido a escribir
        mode: Modo de apertura ('w', 'wb', etc.)
        encoding: Encoding para modo texto
    """
    kwargs = {'mode': mode}
    if 'b' not in mode:
        kwargs['encoding'] = encoding

    with open(filepath, **kwargs) as f:
        f.write(content)


def safe_import_module(module_name: str, max_retries: int = 3, delay: float = 0.5) -> Any:
    """
    Importa un módulo con reintentos automáticos para Google Drive.

    Args:
        module_name: Nombre del módulo a importar
        max_retries: Número máximo de reintentos
        delay: Delay entre reintentos

    Returns:
        El módulo importado
    """
    import importlib

    last_exception = None
    current_delay = delay

    for attempt in range(max_retries + 1):
        try:
            return importlib.import_module(module_name)
        except OSError as e:
            last_exception = e
            if hasattr(e, 'errno') and e.errno == 22:  # Invalid argument
                if attempt < max_retries:
                    print(f"   ️ Error leyendo módulo {module_name}, reintentando ({attempt + 1}/{max_retries})...")
                    time.sleep(current_delay)
                    current_delay *= 2
                    continue
            raise

    raise last_exception


# Alias cortos para uso común
copy2 = safe_copy2
read_file = safe_read_file
write_file = safe_write_file
import_module = safe_import_module
