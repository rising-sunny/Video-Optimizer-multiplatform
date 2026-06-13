#!/usr/bin/env python3
"""
Script de inicio universal - Video Optimizer Pro
Sistema de entornos virtuales locales con registro
Funciona en cualquier PC desde Google Drive
"""

import sys
import os
import subprocess
import platform
import socket
import hashlib
import uuid
import json
import shutil
import datetime
import re
from pathlib import Path

IS_WINDOWS = os.name == "nt"
PLATFORM_NAME = "Windows" if IS_WINDOWS else platform.system()


def _configure_console_encoding():
    """Evita UnicodeEncodeError en consolas Windows legacy."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                try:
                    stream.reconfigure(errors="replace")
                except Exception:
                    pass

    # Forzar UTF-8 para procesos hijo.
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"


_configure_console_encoding()

# Colores para terminal
if IS_WINDOWS:
    try:
        import colorama
        colorama.init()
    except ImportError:
        pass

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


CRITICAL_RUNTIME_IMPORTS = (
    "torch",
    "whisper",
    "dotenv",
    "PyQt6",
    "groq",
    "edge_tts",
)

PRECISE_SHORT_SUBTITLE_WHISPER_SPEC = "openai-whisper==20250625"
PRECISE_SHORT_SUBTITLE_TORCH_SPEC_LEGACY = "torch==2.4.1"
PRECISE_SHORT_SUBTITLE_TORCH_SPEC_MODERN = "torch>=2.9.0,<3"


def get_python_version_info(python_exe):
    """Obtiene version de Python como tupla (major, minor, micro) y texto."""
    try:
        result = subprocess.run(
            [str(python_exe), "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return None, None

        version_text = (result.stdout or result.stderr or "").strip()
        match = re.search(r"Python\s+(\d+)\.(\d+)\.(\d+)", version_text)
        if not match:
            return None, version_text

        version = tuple(int(part) for part in match.groups())
        return version, version_text
    except Exception:
        return None, None


def get_precise_short_subtitle_packages(python_exe):
    """Resuelve versiones compatibles de Whisper/Torch segun el Python del venv."""
    package_specs = {
        "whisper": PRECISE_SHORT_SUBTITLE_WHISPER_SPEC,
        "torch": PRECISE_SHORT_SUBTITLE_TORCH_SPEC_LEGACY,
    }

    version, _ = get_python_version_info(python_exe)
    if version and version[0] == 3 and version[1] >= 13:
        package_specs["torch"] = PRECISE_SHORT_SUBTITLE_TORCH_SPEC_MODERN

    return package_specs


def probe_missing_python_modules(python_exe, modules):
    """Devuelve los módulos faltantes/importables con el Python indicado."""
    module_list = [str(module).strip() for module in (modules or []) if str(module).strip()]
    if not module_list:
        return []

    probe_script = r"""
import importlib
import json
import sys

missing = []
for module_name in sys.argv[1:]:
    try:
        importlib.import_module(module_name)
    except Exception:
        missing.append(module_name)

print(json.dumps(missing))
"""

    try:
        result = subprocess.run(
            [str(python_exe), "-c", probe_script, *module_list],
            capture_output=True,
            text=True,
            timeout=20
        )
        if result.returncode != 0:
            return module_list

        payload = (result.stdout or "").strip().splitlines()
        if not payload:
            return module_list

        parsed = json.loads(payload[-1])
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return module_list
    except Exception:
        return module_list


def ensure_precise_short_subtitle_dependencies(venv_python):
    """Instala/verifica Whisper y Torch como requisito estándar para shorts."""
    package_specs_by_module = get_precise_short_subtitle_packages(venv_python)
    missing_modules = probe_missing_python_modules(
        venv_python,
        package_specs_by_module.keys()
    )

    if not missing_modules:
        print(f"{Colors.OKGREEN} Dependencias de sincronización precisa ya disponibles{Colors.ENDC}")
        return True

    package_specs = [
        package_specs_by_module[module]
        for module in missing_modules
        if module in package_specs_by_module
    ]

    if not package_specs:
        return True

    print(f"{Colors.OKCYAN} Reparando dependencias críticas para shorts...{Colors.ENDC}")
    print(f"{Colors.OKCYAN}   Faltan módulos: {', '.join(missing_modules)}{Colors.ENDC}")
    print(f"{Colors.OKCYAN}   Instalando: {', '.join(package_specs)}{Colors.ENDC}\n")

    try:
        process = subprocess.Popen(
            [str(venv_python), "-m", "pip", "install", "--prefer-binary", *package_specs],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        while True:
            output_line = process.stdout.readline()
            if output_line == '' and process.poll() is not None:
                break
            if output_line:
                print(output_line.rstrip())
                sys.stdout.flush()

        return_code = process.poll()
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, process.args)

        remaining_missing = probe_missing_python_modules(
            venv_python,
            package_specs_by_module.keys()
        )
        if remaining_missing:
            print(f"{Colors.FAIL} No se pudieron dejar listas las dependencias críticas: {', '.join(remaining_missing)}{Colors.ENDC}")
            return False

        print(f"\n{Colors.OKGREEN} Dependencias críticas para shorts reparadas correctamente{Colors.ENDC}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"\n{Colors.FAIL} Error instalando dependencias críticas para shorts{Colors.ENDC}")
        print(f"{Colors.WARNING}   Código de error: {e.returncode}{Colors.ENDC}")
        print(f"{Colors.WARNING}   Intenta manualmente: {venv_python} -m pip install --prefer-binary {' '.join(package_specs)}{Colors.ENDC}")
        return False
    except Exception as e:
        print(f"\n{Colors.FAIL} Error inesperado reparando dependencias críticas para shorts{Colors.ENDC}")
        print(f"{Colors.WARNING}   {type(e).__name__}: {e}{Colors.ENDC}")
        return False


def python_version_priority(version):
    """Asigna prioridad a versiones compatibles con el proyecto."""
    if not version or version[0] != 3:
        return -100

    minor = version[1]
    if minor == 11:
        return 300
    if minor == 12:
        return 250
    if minor == 10:
        return 200
    if minor > 12:
        return 50 - minor  # 3.13+ funciona como fallback, no preferido
    return 100


def probe_precise_subtitle_runtime(venv_python, project_root):
    """Verifica si el entorno puede hacer sincronizacion precisa para shorts."""
    probe_script = r"""
import json
import os
import shutil
import sys

project_root = sys.argv[1] if len(sys.argv) > 1 else ""
if project_root and project_root not in sys.path:
    sys.path.insert(0, project_root)

def _importable(module_name):
    try:
        __import__(module_name)
        return True
    except Exception:
        return False

def _resolve_binary(name, configured_dir=None, configured_binary=None):
    candidates = []
    if configured_binary:
        candidates.append(configured_binary)
    if configured_dir:
        if os.path.isdir(configured_dir):
            exe_name = name + (".exe" if os.name == "nt" else "")
            candidates.append(os.path.join(configured_dir, exe_name))
        else:
            candidates.append(configured_dir)

    which_path = shutil.which(name)
    if which_path:
        candidates.append(which_path)

    if os.name == "nt":
        common_dirs = [
            os.getenv("FFMPEG_PATH"),
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
            r"C:\Program Files\ffmpeg-2025-11-06-git-222127418b-full_build\bin",
        ]
        for directory in common_dirs:
            if directory:
                candidates.append(os.path.join(directory, f"{name}.exe"))

    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.exists(normalized):
            return normalized
    return None

configured_dir = None
configured_probe = None
try:
    from video_config import VideoConfig
    configured_dir = getattr(VideoConfig, "FFMPEG_BINARY_PATH", None)
    configured_probe = getattr(VideoConfig, "FFPROBE_BINARY_PATH", None)
except Exception:
    pass

ffmpeg_path = _resolve_binary("ffmpeg", configured_dir=configured_dir)
ffprobe_path = _resolve_binary("ffprobe", configured_dir=configured_dir, configured_binary=configured_probe)

status = {
    "whisper_module": _importable("whisper"),
    "torch_module": _importable("torch"),
    "ffmpeg_path": ffmpeg_path,
    "ffprobe_path": ffprobe_path,
}
missing = []
if not status["whisper_module"]:
    missing.append("whisper")
if not status["torch_module"]:
    missing.append("torch")
if not ffmpeg_path:
    missing.append("ffmpeg")
if not ffprobe_path:
    missing.append("ffprobe")
status["missing"] = missing
status["ready"] = not missing
print(json.dumps(status, ensure_ascii=False))
"""

    try:
        result = subprocess.run(
            [str(venv_python), "-c", probe_script, str(project_root)],
            capture_output=True,
            text=True,
            timeout=20
        )
        if result.returncode != 0:
            return {
                "ready": False,
                "missing": ["runtime_probe"],
                "error": (result.stderr or result.stdout or "").strip(),
            }

        payload = (result.stdout or "").strip().splitlines()
        if not payload:
            return {"ready": False, "missing": ["runtime_probe_empty"]}
        return json.loads(payload[-1])
    except Exception as e:
        return {
            "ready": False,
            "missing": ["runtime_probe_exception"],
            "error": str(e),
        }


def print_precise_subtitle_runtime_report(runtime_status):
    """Muestra si el arranque quedo listo para shorts con subtitulos."""
    print(f"{Colors.OKCYAN}️ Verificando sincronización precisa para shorts...{Colors.ENDC}")
    if runtime_status.get("ready"):
        print(f"{Colors.OKGREEN} Shorts con subtítulos: sincronización precisa disponible{Colors.ENDC}")
        print(f"{Colors.OKCYAN}   ffmpeg: {runtime_status.get('ffmpeg_path')}{Colors.ENDC}")
        print(f"{Colors.OKCYAN}   ffprobe: {runtime_status.get('ffprobe_path')}{Colors.ENDC}\n")
        return

    missing = ", ".join(runtime_status.get("missing") or ["dependencias desconocidas"])
    print(f"{Colors.WARNING}️ Shorts con subtítulos: sincronización precisa NO lista{Colors.ENDC}")
    print(f"{Colors.WARNING}   Faltan: {missing}{Colors.ENDC}")
    print(
        f"{Colors.WARNING}   La app bloqueará exports de shorts con subtítulos "
        f"hasta que esto esté reparado.{Colors.ENDC}\n"
    )


def print_header():
    """Muestra header"""
    print(
        f"\n{Colors.HEADER}{Colors.BOLD}"
        "================================================================\n"
        "Video Optimizer Pro - Inicio Automatico\n"
        "================================================================"
        f"{Colors.ENDC}\n"
    )
def get_project_root():
    """Obtiene la raÃ­z del proyecto (funciona incluso en Google Drive)"""
    return Path(__file__).parent.absolute()

def get_pc_id():
    """Genera un ID Ãºnico para esta PC"""
    try:
        hostname = socket.gethostname()
        # Obtener MAC address de forma mÃ¡s robusta
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff) 
                       for i in range(0, 8*6, 8)][::-1])
        
        # Crear hash Ãºnico pero legible
        unique_string = f"{hostname}_{mac}"
        pc_hash = hashlib.md5(unique_string.encode()).hexdigest()[:8]
        
        # Limpiar hostname para usar en el ID
        clean_hostname = hostname.replace(' ', '_').replace('.', '_')
        return f"PC_{clean_hostname}_{pc_hash}"
    except Exception:
        # Fallback si hay error
        return f"PC_{socket.gethostname()}_{hashlib.md5(str(uuid.getnode()).encode()).hexdigest()[:8]}"

def get_local_venv_path(pc_id):
    """Obtiene la ruta del venv local para esta PC"""
    if IS_WINDOWS:
        base_path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base_path / "venvs" / f"video_optimizer_{pc_id}"
    else:
        return Path.home() / ".local" / "venvs" / f"video_optimizer_{pc_id}"


def get_current_venv_path():
    """Detecta el venv actual si este launcher ya corre dentro de uno."""
    candidates = []

    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        candidates.append(Path(virtual_env))

    if sys.executable:
        python_path = Path(sys.executable)
        if python_path.exists() and python_path.parent.name.lower() in {"scripts", "bin"}:
            candidates.append(python_path.parent.parent)

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate

        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)

        try:
            if candidate.exists() and (candidate / "pyvenv.cfg").exists():
                return candidate
        except Exception:
            continue

    return None

def update_registry(project_root, pc_id, venv_path):
    """Actualiza el registro de PCs en Google Drive"""
    registry_file = project_root / ".venv_registry.json"
    
    # Leer registro existente
    if registry_file.exists():
        try:
            with open(registry_file, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        except Exception:
            registry = {}
    else:
        registry = {}
    
    # Actualizar info de esta PC
    now = datetime.datetime.now().isoformat()
    pc_info = registry.get(pc_id, {})
    
    registry[pc_id] = {
        "hostname": socket.gethostname(),
        "venv_path": str(venv_path),
        "first_run": pc_info.get("first_run", now),
        "last_run": now,
        "platform": PLATFORM_NAME,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    }
    
    # Guardar registro
    try:
        with open(registry_file, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"{Colors.WARNING}âš   No se pudo actualizar el registro: {e}{Colors.ENDC}")
        return False

def find_winpython():
    """Busca WinPython en ubicaciones comunes"""
    if not IS_WINDOWS:
        return None
    
    possible_locations = [
        Path("C:/Scripts/WPy64-312101"),
        Path("C:/Scripts"),
        Path("C:/WinPython"),
        Path("D:/WinPython"),
        Path("C:/PortableApps/WinPython"),
        Path("D:/PortableApps/WinPython"),
        Path("C:/Programs/WinPython"),
        Path("D:/Programs/WinPython"),
        Path.home() / "WinPython",
        Path.home() / "Desktop" / "WinPython",
        Path.home() / "Documents" / "WinPython",
        Path("G:/Mi unidad/WinPython"),
        Path("G:/Mi unidad/PortableApps/WinPython"),
        Path("E:/WinPython"),
        Path("F:/WinPython"),
    ]
    
    for winpython_dir in possible_locations:
        if winpython_dir.exists():
            # Buscar python.exe directamente
            python_exe = winpython_dir / "python.exe"
            if python_exe.exists():
                return python_exe
            
            # Buscar carpeta "python" dentro
            python_dir = winpython_dir / "python"
            if python_dir.exists() and python_dir.is_dir():
                python_exe = python_dir / "python.exe"
                if python_exe.exists():
                    return python_exe
            
            # Buscar en subdirectorios
            for subdir in winpython_dir.iterdir():
                if subdir.is_dir() and ("python" in subdir.name.lower() or "winpython" in subdir.name.lower() or "wpy" in subdir.name.lower()):
                    python_exe = subdir / "python.exe"
                    if python_exe.exists():
                        return python_exe
                    
                    python_subdir = subdir / "python"
                    if python_subdir.exists() and python_subdir.is_dir():
                        python_exe = python_subdir / "python.exe"
                        if python_exe.exists():
                            return python_exe
                    
                    for python_subdir in subdir.iterdir():
                        if python_subdir.is_dir() and "python" in python_subdir.name.lower():
                            python_exe = python_subdir / "python.exe"
                            if python_exe.exists():
                                return python_exe
    
    return None

def get_python_executable():
    """Obtiene el ejecutable de Python (WinPython, sistema, o sys.executable)
    IMPORTANTE: NO usa venvs existentes, solo Python base del sistema"""

    # En Windows, priorizar versiones compatibles via launcher "py"
    if IS_WINDOWS:
        for preferred in ["3.11", "3.12", "3.10"]:
            try:
                result = subprocess.run(
                    ["py", f"-{preferred}", "-c", "import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    python_path = Path(result.stdout.strip())
                    if python_path.exists():
                        version, _ = get_python_version_info(python_path)
                        if version and python_version_priority(version) >= 200:
                            print(f"{Colors.OKGREEN}Python {preferred} encontrado: {python_path}{Colors.ENDC}")
                            return python_path
            except Exception:
                pass

        # Rutas estandares por usuario actual
        for minor in ["311", "312", "310"]:
            python_path = Path.home() / "AppData" / "Local" / "Programs" / "Python" / f"Python{minor}" / "python.exe"
            if python_path.exists():
                version, version_text = get_python_version_info(python_path)
                if version and python_version_priority(version) >= 200:
                    print(f"{Colors.OKGREEN}Python {version_text} encontrado: {python_path}{Colors.ENDC}")
                    return python_path

    # Intentar WinPython
    winpython = find_winpython()
    if winpython:
        version, version_text = get_python_version_info(winpython)
        if version:
            print(f"{Colors.OKGREEN}WinPython encontrado ({version_text}): {winpython}{Colors.ENDC}")
            return winpython

    fallback_candidates = []

    # Verificar si sys.executable es un Python base (no de un venv)
    if sys.executable:
        python_path = Path(sys.executable)
        if python_path.exists():
            python_str = str(python_path).lower()
            if "venv" not in python_str and "virtualenv" not in python_str:
                version, version_text = get_python_version_info(python_path)
                if version and python_version_priority(version) >= 200:
                    print(f"{Colors.OKGREEN}Python del sistema encontrado: {python_path}{Colors.ENDC}")
                    return python_path
                if version:
                    fallback_candidates.append((python_version_priority(version), python_path, version_text))

    # Buscar python en PATH (pero no venvs)
    try:
        cmd = "where" if IS_WINDOWS else "which"
        result = subprocess.run(
            [cmd, "python"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for python_path_str in result.stdout.strip().split('\n'):
                python_path_str = python_path_str.strip()
                if not python_path_str:
                    continue
                python_path = Path(python_path_str)
                if not python_path.exists():
                    continue
                python_str = str(python_path).lower()
                if "venv" in python_str or "virtualenv" in python_str:
                    continue
                version, version_text = get_python_version_info(python_path)
                if version and python_version_priority(version) >= 200:
                    print(f"{Colors.OKGREEN}Python encontrado en PATH: {python_path}{Colors.ENDC}")
                    return python_path
                if version:
                    fallback_candidates.append((python_version_priority(version), python_path, version_text))
    except Exception:
        pass

    # Ultimo recurso: buscar python3
    try:
        cmd = "where" if IS_WINDOWS else "which"
        result = subprocess.run(
            [cmd, "python3"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for python_path_str in result.stdout.strip().split('\n'):
                python_path_str = python_path_str.strip()
                if not python_path_str:
                    continue
                python_path = Path(python_path_str)
                if not python_path.exists():
                    continue
                python_str = str(python_path).lower()
                if "venv" in python_str or "virtualenv" in python_str:
                    continue
                version, version_text = get_python_version_info(python_path)
                if version and python_version_priority(version) >= 200:
                    print(f"{Colors.OKGREEN}Python3 encontrado: {python_path}{Colors.ENDC}")
                    return python_path
                if version:
                    fallback_candidates.append((python_version_priority(version), python_path, version_text))
    except Exception:
        pass

    # Fallback final: usar algun Python disponible aunque sea 3.13+
    if fallback_candidates:
        fallback_candidates.sort(key=lambda item: item[0], reverse=True)
        _, python_path, version_text = fallback_candidates[0]
        print(f"{Colors.WARNING}Usando Python no preferido ({version_text}): {python_path}{Colors.ENDC}")
        print(f"{Colors.WARNING}Recomendado: Python 3.11 o 3.12 para maxima compatibilidad{Colors.ENDC}")
        return python_path

    return None
def validate_venv(venv_path):
    """Valida que el entorno virtual funcione correctamente"""
    if IS_WINDOWS:
        python_exe = venv_path / "Scripts" / "python.exe"
        pip_exe = venv_path / "Scripts" / "pip.exe"
    else:
        python_exe = venv_path / "bin" / "python"
        pip_exe = venv_path / "bin" / "pip"
    
    # Verificar que el ejecutable existe
    if not python_exe.exists():
        return False, f"El ejecutable de Python no existe en: {python_exe}"
    
    # Verificar que pip existe
    if not pip_exe.exists():
        return False, f"pip no encontrado en: {pip_exe}"
    
    # Intentar ejecutar Python del venv
    try:
        result = subprocess.run(
            [str(python_exe), "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            # Verificar tambiÃ©n pip
            try:
                pip_result = subprocess.run(
                    [str(pip_exe), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if pip_result.returncode == 0:
                    return True, None
                else:
                    return False, f"pip no funciona: {pip_result.stderr[:200] if pip_result.stderr else 'Error desconocido'}"
            except Exception as pip_e:
                return False, f"Error al validar pip: {str(pip_e)[:200]}"
        else:
            error_msg = result.stderr[:200] if result.stderr else result.stdout[:200] if result.stdout else 'Error desconocido'
            return False, f"Error al ejecutar Python: {error_msg}"
            
    except FileNotFoundError:
        return False, f"Python del venv no se puede ejecutar (ruta incorrecta): {python_exe}"
    except subprocess.TimeoutExpired:
        return False, "Timeout al validar venv (mÃ¡s de 10 segundos)"
    except PermissionError:
        return False, f"Sin permisos para ejecutar: {python_exe}"
    except Exception as e:
        return False, f"Error inesperado al validar venv: {type(e).__name__}: {str(e)[:200]}"

def create_venv(venv_path, python_exe):
    """Crea un nuevo entorno virtual"""
    print(f"{Colors.OKBLUE}ðŸ“¦ Creando entorno virtual en: {venv_path}{Colors.ENDC}")
    print(f"{Colors.OKCYAN}   Usando Python: {python_exe}{Colors.ENDC}")
    
    # Verificar que Python existe
    if not Path(python_exe).exists():
        print(f"{Colors.FAIL}âŒ Python no encontrado en: {python_exe}{Colors.ENDC}")
        return False
    
    # Crear directorio padre si no existe
    try:
        venv_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"{Colors.OKCYAN}   Directorio creado: {venv_path.parent}{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}âŒ Error al crear directorio: {e}{Colors.ENDC}")
        return False
    
    print(f"{Colors.OKCYAN}   Creando entorno virtual (esto puede tardar unos segundos)...{Colors.ENDC}")
    print(f"{Colors.OKCYAN}   VerÃ¡s el progreso a continuaciÃ³n:{Colors.ENDC}\n")
    
    try:
        import sys
        import time
        
        # Usar Popen para mostrar salida en tiempo real
        process = subprocess.Popen(
            [str(python_exe), "-m", "venv", str(venv_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
            universal_newlines=True
        )
        
        # Leer y mostrar salida lÃ­nea por lÃ­nea
        last_activity = datetime.datetime.now()
        timeout_seconds = 120  # 2 minutos timeout
        
        while True:
            output_line = process.stdout.readline()
            if output_line == '' and process.poll() is not None:
                break
            if output_line:
                # Mostrar la lÃ­nea
                print(f"   {output_line.rstrip()}")
                sys.stdout.flush()  # Forzar escritura inmediata
                last_activity = datetime.datetime.now()
            else:
                # Verificar timeout
                elapsed = (datetime.datetime.now() - last_activity).total_seconds()
                if elapsed > timeout_seconds:
                    print(f"\n{Colors.WARNING}âš   Timeout al crear entorno virtual (mÃ¡s de {timeout_seconds} segundos){Colors.ENDC}")
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return False
                time.sleep(0.1)  # PequeÃ±a pausa
        
        # Obtener cÃ³digo de salida
        return_code = process.poll()
        if return_code != 0:
            # Leer cualquier salida restante
            remaining_output = process.stdout.read()
            if remaining_output:
                print(remaining_output)
            raise subprocess.CalledProcessError(return_code, process.args)
        
        # Verificar que el venv se creÃ³ correctamente
        print(f"\n{Colors.OKCYAN}   Verificando que el venv se creÃ³ correctamente...{Colors.ENDC}")
        venv_python = get_venv_python(venv_path)
        if venv_python.exists():
            print(f"{Colors.OKGREEN}âœ… Entorno virtual creado exitosamente{Colors.ENDC}")
            print(f"{Colors.OKCYAN}   UbicaciÃ³n: {venv_path}{Colors.ENDC}")
            return True
        else:
            print(f"{Colors.FAIL}âŒ El entorno virtual se creÃ³ pero el ejecutable no existe{Colors.ENDC}")
            print(f"{Colors.WARNING}   Ruta esperada: {venv_python}{Colors.ENDC}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"{Colors.FAIL}âŒ Timeout al crear entorno virtual (mÃ¡s de 2 minutos){Colors.ENDC}")
        print(f"{Colors.WARNING}   Esto puede indicar un problema con Python o el sistema{Colors.ENDC}")
        return False
        
    except subprocess.CalledProcessError as e:
        print(f"{Colors.FAIL}âŒ Error al crear entorno virtual{Colors.ENDC}")
        print(f"{Colors.WARNING}   CÃ³digo de error: {e.returncode}{Colors.ENDC}")
        
        # Mostrar detalles del error
        if hasattr(e, 'stdout') and e.stdout:
            error_output = e.stdout if isinstance(e.stdout, str) else e.stdout.decode('utf-8', errors='ignore')
            print(f"\n{Colors.FAIL}ðŸ“‹ Detalles del error:{Colors.ENDC}")
            print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
            for line in error_output.strip().split('\n'):
                if line.strip():
                    print(f"   {line}")
            print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        
        # Verificar si el mÃ³dulo venv estÃ¡ disponible
        try:
            test_result = subprocess.run(
                [str(python_exe), "-m", "venv", "--help"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if test_result.returncode != 0:
                print(f"\n{Colors.WARNING}âš   El mÃ³dulo 'venv' no estÃ¡ disponible en este Python{Colors.ENDC}")
                print(f"{Colors.OKCYAN}   Intenta usar Python 3.10+ o instala python3-venv{Colors.ENDC}")
        except:
            pass
        
        return False
        
    except Exception as e:
        print(f"{Colors.FAIL}âŒ Error inesperado al crear entorno virtual{Colors.ENDC}")
        print(f"{Colors.WARNING}   Tipo: {type(e).__name__}{Colors.ENDC}")
        print(f"{Colors.WARNING}   Mensaje: {str(e)}{Colors.ENDC}")
        
        import traceback
        print(f"\n{Colors.FAIL}ðŸ“‹ Traceback completo:{Colors.ENDC}")
        print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        traceback.print_exc()
        print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        
        return False

def get_venv_python(venv_path):
    """Obtiene el ejecutable de Python del venv"""
    if IS_WINDOWS:
        return venv_path / "Scripts" / "python.exe"
    else:
        return venv_path / "bin" / "python"

def ensure_dependencies(venv_python, project_root):
    """Asegura que las dependencias estÃ©n instaladas"""
    requirements = project_root / "requirements.txt"
    
    if not requirements.exists():
        print(f"{Colors.WARNING}âš   requirements.txt no encontrado{Colors.ENDC}")
        return True
    
    print(f"{Colors.OKBLUE}ðŸ“¥ Instalando dependencias...{Colors.ENDC}")
    print(f"{Colors.OKCYAN}   Esto puede tardar varios minutos la primera vez{Colors.ENDC}")
    print(f"{Colors.OKCYAN}   Por favor, ten paciencia...{Colors.ENDC}\n")
    
    try:
        # Primero actualizar pip
        print(f"{Colors.OKCYAN}ðŸ”„ Actualizando pip...{Colors.ENDC}")
        result = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            if lines:
                print(f"{Colors.OKGREEN}âœ… pip actualizado{Colors.ENDC}\n")
        
        # Leer requirements.txt para mostrar quÃ© se va a instalar
        print(f"{Colors.OKCYAN}ðŸ“‹ Paquetes a instalar:{Colors.ENDC}")
        try:
            with open(requirements, 'r', encoding='utf-8') as f:
                packages = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
                for pkg in packages[:10]:  # Mostrar primeros 10
                    print(f"   â€¢ {pkg}")
                if len(packages) > 10:
                    print(f"   ... y {len(packages) - 10} mÃ¡s")
        except Exception as e:
            print(f"{Colors.WARNING}   (No se pudo leer requirements.txt: {e}){Colors.ENDC}")
        
        print(f"\n{Colors.OKCYAN}ðŸ“¦ Instalando paquetes (esto puede tardar varios minutos)...{Colors.ENDC}")
        print(f"{Colors.OKCYAN}   VerÃ¡s el progreso a continuaciÃ³n:{Colors.ENDC}\n")
        
        # Instalar dependencias
        import sys
        import time
        
        process = subprocess.Popen(
            [str(venv_python), "-m", "pip", "install", "--prefer-binary", "-r", str(requirements)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Leer y mostrar salida lÃ­nea por lÃ­nea en tiempo real
        print(f"{Colors.OKCYAN}   [Progreso en tiempo real - se mostrarÃ¡ actividad cada 30 segundos]{Colors.ENDC}\n")
        last_activity = datetime.datetime.now()
        last_progress_message = datetime.datetime.now()
        timeout_seconds = 600  # 10 minutos sin actividad = problema
        progress_interval = 30  # Mostrar mensaje de progreso cada 30 segundos
        
        try:
            while True:
                output_line = process.stdout.readline()
                if output_line == '' and process.poll() is not None:
                    break
                if output_line:
                    print(output_line.rstrip())
                    sys.stdout.flush()
                    last_activity = datetime.datetime.now()
                    last_progress_message = datetime.datetime.now()
                else:
                    elapsed_since_progress = (datetime.datetime.now() - last_progress_message).total_seconds()
                    if elapsed_since_progress >= progress_interval:
                        elapsed_total = (datetime.datetime.now() - last_activity).total_seconds()
                        if process.poll() is None:
                            print(f"{Colors.OKCYAN}   [â³ Procesando... {int(elapsed_total)}s transcurridos - el proceso sigue activo]{Colors.ENDC}")
                            sys.stdout.flush()
                            last_progress_message = datetime.datetime.now()
                    
                    elapsed = (datetime.datetime.now() - last_activity).total_seconds()
                    if elapsed > timeout_seconds:
                        print(f"\n{Colors.WARNING}âš   Sin actividad por {timeout_seconds} segundos{Colors.ENDC}")
                        print(f"{Colors.WARNING}   El proceso puede estar colgado. Verificando...{Colors.ENDC}")
                        if process.poll() is None:
                            print(f"{Colors.WARNING}   El proceso sigue corriendo, esperando mÃ¡s tiempo...{Colors.ENDC}")
                            last_activity = datetime.datetime.now()
                        else:
                            break
                    time.sleep(0.1)
            
            return_code = process.poll()
            if return_code != 0:
                remaining_output = process.stdout.read()
                if remaining_output:
                    print(remaining_output)
                raise subprocess.CalledProcessError(return_code, process.args)
                
        except KeyboardInterrupt:
            print(f"\n{Colors.WARNING}âš   InstalaciÃ³n interrumpida por el usuario{Colors.ENDC}")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise
        
        if not ensure_precise_short_subtitle_dependencies(venv_python):
            return False

        print(f"\n{Colors.OKGREEN}âœ… Dependencias instaladas/actualizadas exitosamente{Colors.ENDC}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\n{Colors.FAIL}âŒ Error al instalar dependencias{Colors.ENDC}")
        print(f"{Colors.WARNING}   CÃ³digo de error: {e.returncode}{Colors.ENDC}")
        
        if hasattr(e, 'stdout') and e.stdout:
            error_output = e.stdout if isinstance(e.stdout, str) else e.stdout.decode('utf-8', errors='ignore')
            print(f"\n{Colors.FAIL}ðŸ“‹ Detalles del error:{Colors.ENDC}")
            print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
            
            error_lines = error_output.strip().split('\n')
            if len(error_lines) > 30:
                print(f"{Colors.OKCYAN}   (Mostrando Ãºltimas 30 lÃ­neas de {len(error_lines)} lÃ­neas totales){Colors.ENDC}\n")
                for line in error_lines[-30:]:
                    print(f"   {line}")
            else:
                for line in error_lines:
                    print(f"   {line}")
            
            print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        
        print(f"\n{Colors.OKCYAN}ðŸ’¡ Sugerencias:{Colors.ENDC}")
        print(f"   1. Verifica tu conexiÃ³n a internet")
        print(f"   2. Intenta ejecutar manualmente:")
        print(f"      {venv_python} -m pip install -r {requirements}")
        print(f"   3. Revisa los detalles del error arriba para mÃ¡s informaciÃ³n")
        
        return False
    
    except FileNotFoundError:
        print(f"\n{Colors.FAIL}âŒ Python del venv no encontrado: {venv_python}{Colors.ENDC}")
        print(f"{Colors.WARNING}   El entorno virtual puede estar corrupto{Colors.ENDC}")
        return False
    
    except Exception as e:
        print(f"\n{Colors.FAIL}âŒ Error inesperado al instalar dependencias{Colors.ENDC}")
        print(f"{Colors.WARNING}   Tipo de error: {type(e).__name__}{Colors.ENDC}")
        print(f"{Colors.WARNING}   Mensaje: {str(e)}{Colors.ENDC}")
        
        import traceback
        print(f"\n{Colors.FAIL}ðŸ“‹ Traceback completo:{Colors.ENDC}")
        print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        traceback.print_exc()
        print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        
        return False

def find_best_registered_venv(project_root):
    """Busca el mejor venv ya registrado para este hostname."""
    registry_file = project_root / ".venv_registry.json"
    if not registry_file.exists():
        return None

    try:
        with open(registry_file, 'r', encoding='utf-8') as f:
            registry = json.load(f)
    except Exception:
        return None

    if not isinstance(registry, dict):
        return None

    hostname = socket.gethostname().lower()
    username = os.environ.get("USERNAME", "").lower()
    candidates = []

    for registered_pc_id, info in registry.items():
        if not isinstance(info, dict):
            continue
        if info.get("hostname", "").lower() != hostname:
            continue

        venv_path_raw = info.get("venv_path")
        if not venv_path_raw:
            continue

        venv_path = Path(venv_path_raw)
        venv_python = get_venv_python(venv_path)
        if not venv_python.exists():
            continue

        version, version_text = get_python_version_info(venv_python)
        if not version:
            continue

        user_bonus = 20 if (username and username in str(venv_path).lower()) else 0
        score = python_version_priority(version) + user_bonus
        last_run = info.get("last_run", "")
        candidates.append((score, last_run, registered_pc_id, venv_path, version_text))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = candidates[0]
    return {
        "pc_id": best[2],
        "venv_path": best[3],
        "version_text": best[4]
    }

def show_registry_info(project_root):
    """Muestra informaciÃ³n del registro de PCs"""
    registry_file = project_root / ".venv_registry.json"
    
    if not registry_file.exists():
        return
    
    try:
        with open(registry_file, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        
        if registry:
            print(f"\n{Colors.OKCYAN}ðŸ“‹ PCs registradas: {len(registry)}{Colors.ENDC}")
            for pc_id, info in registry.items():
                print(f"   â€¢ {info.get('hostname', 'Unknown')} ({info.get('platform', 'Unknown')})")
    except Exception:
        pass

def main():
    """FunciÃ³n principal"""
    skip_deps = "--skip-deps" in sys.argv or "--fast" in sys.argv

    print_header()
    
    # Obtener raÃ­z del proyecto
    project_root = get_project_root()
    print(f"{Colors.OKCYAN}ðŸ“ Proyecto: {project_root}{Colors.ENDC}\n")
    
    # Identificar PC
    pc_id = get_pc_id()
    detected_pc_id = pc_id
    current_venv_path = get_current_venv_path()

    # Elegir el mejor venv ya registrado para esta PC (evita duplicados y versiones no compatibles)
    venv_path = get_local_venv_path(pc_id)
    best_registered = find_best_registered_venv(project_root)
    if best_registered:
        if best_registered["venv_path"] != venv_path:
            print(f"{Colors.OKCYAN}ðŸ”„ Reutilizando venv registrada: {best_registered['venv_path']}{Colors.ENDC}")
            print(f"{Colors.OKCYAN}   Python detectado en esa venv: {best_registered['version_text']}{Colors.ENDC}")
        pc_id = best_registered["pc_id"]
        venv_path = best_registered["venv_path"]

    if current_venv_path:
        is_current_venv_valid, _ = validate_venv(current_venv_path)
        if is_current_venv_valid:
            if current_venv_path != venv_path:
                print(f"{Colors.OKCYAN}ðŸ”„ Reutilizando venv actual del launcher: {current_venv_path}{Colors.ENDC}")
            pc_id = detected_pc_id
            venv_path = current_venv_path

    print(f"{Colors.OKCYAN}ðŸ–¥  PC identificada: {pc_id}{Colors.ENDC}\n")
    print(f"{Colors.OKCYAN}ðŸ“‚ Venv local: {venv_path}{Colors.ENDC}\n")
    
    # Verificar Python disponible
    python_exe = get_python_executable()
    if python_exe:
        print(f"{Colors.OKGREEN}âœ… Python disponible: {python_exe}{Colors.ENDC}\n")
    else:
        print(f"{Colors.FAIL}âŒ No se encontrÃ³ Python (ni WinPython ni sistema){Colors.ENDC}")
        print(f"{Colors.WARNING}   Por favor, instala Python o WinPython{Colors.ENDC}")
        sys.exit(1)
    
    # Verificar que estamos en el directorio correcto
    print(f"{Colors.OKCYAN}ðŸ” Verificando archivos del proyecto...{Colors.ENDC}")
    if not (project_root / "video_optimizer_pyqt6.py").exists():
        print(f"{Colors.FAIL}âŒ Error: video_optimizer_pyqt6.py no encontrado en {project_root}{Colors.ENDC}")
        print(f"{Colors.WARNING}   AsegÃºrate de ejecutar este script desde la raÃ­z del proyecto{Colors.ENDC}")
        sys.exit(1)
    print(f"{Colors.OKGREEN}âœ… Archivos del proyecto verificados{Colors.ENDC}\n")
    
    # Verificar si el venv existe y funciona
    print(f"{Colors.OKCYAN}ðŸ” Verificando entorno virtual...{Colors.ENDC}")
    venv_exists = venv_path.exists()
    venv_valid = False
    
    if venv_exists:
        print(f"{Colors.OKCYAN}   Venv encontrado, validando...{Colors.ENDC}")
        is_valid, error_msg = validate_venv(venv_path)
        if is_valid:
            venv_valid = True
            print(f"{Colors.OKGREEN}âœ… Entorno virtual encontrado y funcional{Colors.ENDC}\n")
        else:
            print(f"{Colors.WARNING}âš   Entorno virtual encontrado pero no funciona{Colors.ENDC}")
            print(f"{Colors.WARNING}   RazÃ³n: {error_msg}{Colors.ENDC}")
            print(f"{Colors.OKCYAN}   Eliminando venv roto...{Colors.ENDC}")
            
            # Eliminar venv roto
            try:
                shutil.rmtree(venv_path)
                print(f"{Colors.OKGREEN}âœ… Venv roto eliminado{Colors.ENDC}\n")
            except Exception as e:
                print(f"{Colors.FAIL}âŒ Error al eliminar venv: {e}{Colors.ENDC}")
                print(f"{Colors.WARNING}   Por favor, elimÃ­nalo manualmente: {venv_path}{Colors.ENDC}")
                sys.exit(1)
    else:
        print(f"{Colors.OKCYAN}   Venv no encontrado, se crearÃ¡ uno nuevo{Colors.ENDC}\n")
    
    # Crear venv si no existe o estÃ¡ roto
    if not venv_valid:
        print(f"{Colors.OKBLUE}ðŸ“¦ Creando nuevo entorno virtual...{Colors.ENDC}")
        if "--auto" in sys.argv or "-a" in sys.argv:
            if not create_venv(venv_path, python_exe):
                sys.exit(1)
        else:
            response = input(f"{Colors.OKCYAN}Â¿Crear entorno virtual en {venv_path}? (S/n): {Colors.ENDC}")
            
            if response.lower() in ['', 's', 'si', 'sÃ­', 'y', 'yes']:
                if not create_venv(venv_path, python_exe):
                    sys.exit(1)
            else:
                print(f"{Colors.FAIL}âŒ Se requiere un entorno virtual para continuar{Colors.ENDC}")
                sys.exit(1)
    
    # Actualizar registro
    print(f"{Colors.OKCYAN}ðŸ“ Actualizando registro de PCs...{Colors.ENDC}")
    update_registry(project_root, pc_id, venv_path)
    print(f"{Colors.OKGREEN}âœ… Registro actualizado{Colors.ENDC}\n")
    
    # Mostrar info del registro
    show_registry_info(project_root)
    
    # Obtener Python del venv
    print(f"{Colors.OKCYAN}ðŸ” Verificando Python del venv...{Colors.ENDC}")
    venv_python = get_venv_python(venv_path)
    
    if not venv_python.exists():
        print(f"{Colors.FAIL}âŒ Python del entorno virtual no encontrado: {venv_python}{Colors.ENDC}")
        sys.exit(1)
    print(f"{Colors.OKGREEN}âœ… Python del venv verificado: {venv_python}{Colors.ENDC}\n")
    
    # Verificar/instalar dependencias
    # Comprobar si los paquetes criticos estan instalados antes de permitir --skip-deps
    deps_installed = False
    if skip_deps and venv_valid:
        try:
            missing_critical_modules = probe_missing_python_modules(
                venv_python,
                CRITICAL_RUNTIME_IMPORTS
            )
            deps_installed = (len(missing_critical_modules) == 0)
        except Exception:
            deps_installed = False
        if deps_installed:
            print(f"{Colors.WARNING}âš  Omitiendo instalaciÃ³n de dependencias (--skip-deps){Colors.ENDC}\n")
        else:
            print(f"{Colors.WARNING}--skip-deps ignorado: faltan paquetes criticos en el venv{Colors.ENDC}")
            try:
                if missing_critical_modules:
                    print(f"{Colors.WARNING}   Módulos faltantes: {', '.join(missing_critical_modules)}{Colors.ENDC}")
            except Exception:
                pass

    if not (skip_deps and deps_installed):
        print(f"{Colors.OKBLUE}ðŸ“¦ Iniciando instalaciÃ³n de dependencias...{Colors.ENDC}\n")
        ensure_dependencies(venv_python, project_root)

    runtime_status = probe_precise_subtitle_runtime(venv_python, project_root)
    print_precise_subtitle_runtime_report(runtime_status)

    # Ejecutar video_optimizer_pyqt6.py con el Python del venv
    main_script = project_root / "video_optimizer_pyqt6.py"
    
    if not main_script.exists():
        print(f"{Colors.FAIL}âŒ video_optimizer_pyqt6.py no encontrado en: {main_script}{Colors.ENDC}")
        sys.exit(1)
    
    print(f"\n{Colors.HEADER}{Colors.BOLD}ðŸš€ Iniciando aplicaciÃ³n...{Colors.ENDC}\n")
    
    # Ejecutar video_optimizer_pyqt6.py
    try:
        # Construir lista de argumentos, filtrando flags del launcher
        launcher_flags = {'--auto', '-a', '--skip-deps', '--fast'}
        args = [str(venv_python), str(main_script)] + [arg for arg in sys.argv[1:] if arg not in launcher_flags]
        
        print(f"{Colors.OKCYAN}ðŸ“ Ejecutando: {' '.join(args)}{Colors.ENDC}\n")
        
        # En Windows, usar subprocess.run para mejor manejo de rutas con espacios
        if IS_WINDOWS:
            os.chdir(str(project_root))  # Cambiar al directorio del proyecto
            child_env = os.environ.copy()
            # Evita errores UnicodeEncodeError en consolas Windows con codepage legacy.
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUTF8"] = "1"
            # Ejecutar sin capturar salida para que se vea en tiempo real
            # Esto es importante para aplicaciones GUI que deben mostrar su propia ventana
            result = subprocess.run(
                args, 
                check=False,
                cwd=str(project_root),
                env=child_env
            )            # 0 = cierre normal
            if result.returncode == 0:
                print(f"\n{Colors.OKGREEN}[OK] Aplicacion cerrada correctamente{Colors.ENDC}")
                sys.exit(0)
            elif result.returncode == 1:
                print(f"\n{Colors.FAIL}[ERROR] La aplicacion termino con error (codigo: 1){Colors.ENDC}")
                crash_log = project_root / "crash_log.txt"
                if crash_log.exists():
                    try:
                        print(f"{Colors.WARNING}[TIP] Revisa crash_log.txt para el traceback mas reciente{Colors.ENDC}")
                    except Exception:
                        pass
                sys.exit(1)
            else:
                print(f"\n{Colors.FAIL}[ERROR] La aplicacion termino con codigo de error: {result.returncode}{Colors.ENDC}")
                print(f"{Colors.WARNING}[TIP] Revisa los mensajes anteriores para mas detalles{Colors.ENDC}")
                sys.exit(result.returncode)
        else:
            # En Unix/Linux, usar os.execv
            os.execv(str(venv_python), args)
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}âš  Interrumpido por el usuario{Colors.ENDC}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.FAIL}âŒ Error al ejecutar: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}âš   Interrumpido por el usuario{Colors.ENDC}")
        sys.exit(0)





