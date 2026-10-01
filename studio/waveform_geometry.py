# -*- coding: utf-8 -*-
"""Matematica del recorte sobre la forma de onda.

Vive fuera de `waveform_widget.py` para poder testearla sin levantar Qt: son
las cuentas que deciden si una barra se puede agarrar, donde queda al soltarla
y que texto se muestra. Ver `test_waveform_geometry.py`.

El bug que motivo separarlo (2026-09-03): las barras de recorte solo se
dibujaban `if start_time > 0 or end_time < duration`. En una pista recien
cargada (inicio 0, fin = duracion) no habia ninguna barra visible, asi que no
habia nada que agarrar para empezar a recortar. Y el margen de clic era de 5
pixeles, invisible en la practica.
"""

from __future__ import annotations

from typing import Optional, Tuple

# Margen de agarre alrededor de cada barra. 5 px era imposible de acertar;
# 12 es comodo con mouse y sigue permitiendo agarrar el interior si las dos
# barras estan cerca.
GRAB_TOLERANCE_PX = 12

# Recorte minimo. Sin esto, arrastrar una barra sobre la otra deja un recorte
# de cero segundos que despues rompe el export.
MIN_SELECTION_S = 0.20


def time_to_x(t: float, duration: float, width: int) -> int:
    """Segundo -> pixel."""
    if duration <= 0 or width <= 0:
        return 0
    fraccion = max(0.0, min(float(t) / float(duration), 1.0))
    return int(round(fraccion * width))


def x_to_time(x: float, duration: float, width: int) -> float:
    """Pixel -> segundo, siempre dentro de la pista."""
    if duration <= 0 or width <= 0:
        return 0.0
    fraccion = max(0.0, min(float(x) / float(width), 1.0))
    return fraccion * float(duration)


def hit_test(x: float, start_time: float, end_time: float, duration: float,
             width: int, tolerance: int = GRAB_TOLERANCE_PX) -> Optional[str]:
    """Que agarro el usuario: 'start', 'end', 'region' o None.

    Con las dos barras encimadas gana la de INICIO por poco margen, para que
    arrastrarla siempre sea posible: si ganara la de fin, un recorte al minimo
    dejaria la de inicio inalcanzable.
    """
    if duration <= 0 or width <= 0:
        return None
    sx = time_to_x(start_time, duration, width)
    ex = time_to_x(end_time, duration, width)

    d_start = abs(x - sx)
    d_end = abs(x - ex)
    if d_start <= tolerance and d_start <= d_end:
        return "start"
    if d_end <= tolerance:
        return "end"
    if sx < x < ex:
        return "region"
    return None


def clamp_range(start_time: float, end_time: float, duration: float,
                min_len: float = MIN_SELECTION_S) -> Tuple[float, float]:
    """Deja el rango dentro de la pista y con un largo minimo util."""
    if duration <= 0:
        return 0.0, 0.0
    largo_min = min(float(min_len), float(duration))
    inicio = max(0.0, min(float(start_time), float(duration)))
    fin = max(0.0, min(float(end_time), float(duration)))
    if fin < inicio:
        inicio, fin = fin, inicio
    if fin - inicio < largo_min:
        fin = inicio + largo_min
        if fin > duration:
            fin = float(duration)
            inicio = max(0.0, fin - largo_min)
    return inicio, fin


def move_region(start_time: float, end_time: float, delta_s: float,
                duration: float) -> Tuple[float, float]:
    """Desplaza el recorte entero conservando su largo.

    Al chocar con un borde se frena, en vez de encogerse: si se encogiera,
    arrastrar hasta el final y volver devolveria un recorte mas corto que el
    que se tenia.
    """
    largo = float(end_time) - float(start_time)
    if largo <= 0 or duration <= 0:
        return clamp_range(start_time, end_time, duration)
    inicio = float(start_time) + float(delta_s)
    inicio = max(0.0, min(inicio, float(duration) - largo))
    return inicio, inicio + largo


def format_timecode(segundos: float) -> str:
    """mm:ss.d — con decima porque los recortes se ajustan finos."""
    try:
        s = max(0.0, float(segundos))
    except (TypeError, ValueError):
        s = 0.0
    minutos = int(s // 60)
    resto = s - minutos * 60
    return "%d:%04.1f" % (minutos, resto)


def describe_selection(start_time: float, end_time: float) -> str:
    """La linea que resume el recorte para la interfaz."""
    largo = max(0.0, float(end_time) - float(start_time))
    return "Inicio %s   ->   Fin %s   |   Duracion %s" % (
        format_timecode(start_time), format_timecode(end_time),
        format_timecode(largo))


__all__ = [
    "GRAB_TOLERANCE_PX", "MIN_SELECTION_S",
    "time_to_x", "x_to_time", "hit_test", "clamp_range", "move_region",
    "format_timecode", "describe_selection",
]
