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

    return loaded
