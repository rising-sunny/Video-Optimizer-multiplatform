# -*- coding: utf-8 -*-
"""Traducir el progreso en bytes de los uploaders a lineas legibles para el panel.

Los uploaders (Cloudinary, Facebook) llaman `on_progress(enviado, total)` muchas
veces por segundo. El panel de la GUI no quiere 300 lineas: quiere "Cloudinary:
25%... 50%... 75%... 100%". Puro y testeable: ver `test_upload_progress.py`.
"""

from __future__ import annotations

from typing import Callable, Optional


def make_byte_progress_reporter(label: str, notify: Callable[[str], None],
                                step_percent: int = 25) -> Callable[[int, int], None]:
    """Devuelve un `on_progress(enviado, total)` que avisa cada `step_percent`.

    - Avisa al arrancar (0%), en cada cruce de escalon y al llegar a 100%.
    - Nunca repite un escalon ni avisa dos veces el 100%.
    - Con total desconocido (0) avisa solo el arranque.
    """
    step = max(1, min(100, int(step_percent)))
    state = {"last": -1}

    def on_progress(sent: int, total: int) -> None:
        try:
            sent = max(0, int(sent or 0))
            total = max(0, int(total or 0))
        except (TypeError, ValueError):
            return
        if total <= 0:
            bucket = 0          # total desconocido: solo se avisa el arranque
        else:
            pct = min(100, sent * 100 // total)
            bucket = 100 if pct >= 100 else (pct // step) * step
        if bucket <= state["last"]:
            return
        state["last"] = bucket
        size = f" ({total / 1_000_000:.1f} MB)" if total > 0 and bucket == 0 else ""
        try:
            notify(f"{label}: {bucket}%{size}")
        except Exception:
            pass

    return on_progress


__all__ = ["make_byte_progress_reporter"]
