# -*- coding: utf-8 -*-
"""Decidir si el resultado de un worker sigue perteneciendo al proyecto activo.

El bug (2026-09-10, "El saqueo de Bagdad"): se genero el guion, quedo guardado
en disco con 19 segmentos, y sin embargo "Abrir editor de timeline" siguio
deshabilitado. En el panel de la GUI decia "Resultado de storyboard obsoleto
ignorado".

Por que. El descarte se basaba en un TOKEN que se incrementa con cada carga de
proyecto -- y el propio flujo de generacion carga el proyecto (a veces dos
veces, como muestra el log). Asi que el worker arrancaba con el token N, la
generacion guardaba y recargaba el MISMO proyecto (token N+2), y al volver el
resultado se lo comparaba contra N+2, se lo daba por viejo y se tiraba.

El token protege de algo real: que un guion generado para el proyecto A
aterrice sobre el proyecto B si el usuario cambio de proyecto mientras tanto.
Pero recargar el mismo proyecto no es cambiar de proyecto. La decision correcta
es por RUTA: si el worker se lanzo para la misma ruta que esta activa ahora, el
resultado vale aunque el token haya cambiado.

Puro y testeable: ver `test_worker_context.py`.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple


def _norm(path: Optional[str]) -> str:
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(str(path)))


def should_accept_worker_result(
    worker_token: Optional[int],
    current_token: int,
    worker_project_path: Optional[str],
    current_project_path: Optional[str],
) -> Tuple[bool, str]:
    """Devuelve (aceptar, motivo).

    - Mismo token: aceptar (el caso normal, nada cambio).
    - Token distinto pero misma ruta de proyecto: aceptar; el proyecto se
      recargo en el medio, no se cambio por otro.
    - Token distinto y ruta distinta (o sin ruta con la que comparar):
      descartar; el resultado es de otro proyecto o de un estado anterior.
    """
    if worker_token is not None and worker_token == current_token:
        return True, "mismo estado de proyecto"

    ruta_worker = _norm(worker_project_path)
    ruta_actual = _norm(current_project_path)
    if ruta_worker and ruta_actual and ruta_worker == ruta_actual:
        return True, "el proyecto se recargo pero es el mismo"

    if not ruta_worker and not ruta_actual:
        return False, "sin proyecto con el que comparar"
    return False, "el resultado pertenece a otro proyecto"


__all__ = ["should_accept_worker_result"]
