"""
Utilidades para cargar variables de entorno del proyecto.
"""

from pathlib import Path
from typing import Iterable, List

from dotenv import load_dotenv


def load_project_env(base_dir: Path | None = None, override: bool = False) -> List[Path]:
    """
    Carga .env y .env.txt si existen, priorizando rutas cercanas al proyecto.

    Retorna la lista de archivos cargados.
    """
    roots: Iterable[Path] = []
    if base_dir is not None:
        roots = [Path(base_dir)]
    else:
        roots = [Path(__file__).resolve().parent.parent, Path.cwd()]

    loaded: List[Path] = []
    seen = set()

    for root in roots:
        try:
            root = root.resolve()
        except Exception:
            root = Path(root)

        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)

        for filename in (".env", ".env.txt"):
            dotenv_path = root / filename
            if dotenv_path.exists():
                load_dotenv(dotenv_path=dotenv_path, override=override)
                loaded.append(dotenv_path)

    _load_key_from_file("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE")
    return loaded


def _load_key_from_file(key_name: str, file_var: str) -> bool:
    """Si `key_name` no esta definida y `file_var` apunta a un archivo, usa su contenido como clave.

    Sirve para claves que ya viven en un archivo privado (p. ej. la VPS guarda la de DeepSeek en
    ~/.config/video-deepseek/api-key) y no se quieren duplicar en el .env. Nunca imprime el valor.
    """
    import os
    if os.environ.get(key_name, "").strip():
        return False
    path = os.environ.get(file_var, "").strip()
    if not path:
        return False
    try:
        value = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not value:
        return False
    os.environ[key_name] = value
    return True
