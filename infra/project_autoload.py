# -*- coding: utf-8 -*-
"""Que proyecto abrir al arrancar la app.

El problema (2026-09-04): `last_project_path.txt` quedo vacio y la app arranco
sin proyecto, sin decir nada. En el log no habia ni una linea sobre el intento,
asi que parecia que el proyecto se hubiera perdido.

El puntero se vacia a proposito al crear un proyecto nuevo -- para que reiniciar
no reabra el anterior -- pero un archivo vacio no distingue "el usuario pidio
empezar de cero" de "el puntero se perdio". Este modulo separa los dos casos:

    ruta valida   -> se abre esa
    NUEVO         -> el usuario pidio borron y cuenta nueva: no se abre nada
    vacio / rota  -> se cae al proyecto modificado mas recientemente

Es puro (sin Qt, sin disco salvo lo que se le pase): ver
`test_project_autoload.py`.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

# Marca explicita de "empece un proyecto nuevo, no reabras el anterior".
# Antes se escribia una cadena vacia, indistinguible de un puntero perdido.
NEW_PROJECT_SENTINEL = "__NUEVO__"


def decide_project_to_load(pointer_text: Optional[str],
                           recent_projects: Optional[List[str]] = None,
                           exists=os.path.exists) -> Tuple[Optional[str], str]:
    """Devuelve (ruta_a_abrir, motivo).

    `recent_projects` viene ordenada de mas reciente a mas antigua.
    `exists` se inyecta para poder testear sin tocar el disco.
    """
    texto = (pointer_text or "").strip()
    candidatos = [p for p in (recent_projects or []) if p]

    if texto == NEW_PROJECT_SENTINEL:
        return None, "el usuario pidio un proyecto nuevo"

    if texto and exists(texto):
        return texto, "ultimo proyecto usado"

    if texto:
        # Habia una ruta pero ya no existe: carpeta borrada, renombrada, o el
        # proyecto vivia en otra PC (este repo se sincroniza entre dos).
        for ruta in candidatos:
            if exists(ruta):
                return ruta, "el ultimo proyecto ya no existe; se abre el mas reciente"
        return None, "el ultimo proyecto ya no existe y no hay otros"

    for ruta in candidatos:
        if exists(ruta):
            return ruta, "no habia puntero; se abre el proyecto mas reciente"
    return None, "no hay proyectos para abrir"


def list_recent_projects(projects_dir: str = "projects", limit: int = 10) -> List[str]:
    """Los project.json existentes, del mas recientemente modificado al mas viejo."""
    try:
        raiz = os.path.abspath(projects_dir)
        if not os.path.isdir(raiz):
            return []
        encontrados = []
        for nombre in os.listdir(raiz):
            ruta = os.path.join(raiz, nombre, "project.json")
            if os.path.isfile(ruta):
                try:
                    encontrados.append((os.path.getmtime(ruta), ruta))
                except OSError:
                    continue
        encontrados.sort(reverse=True)
        return [ruta for _, ruta in encontrados[:limit]]
    except Exception:
        return []


__all__ = ["NEW_PROJECT_SENTINEL", "decide_project_to_load", "list_recent_projects"]
