# -*- coding: utf-8 -*-
"""Guardas: un guion recien generado no se tira por una recarga del proyecto.

BUG (2026-09-10, "El saqueo de Bagdad"): se genero el guion, quedo en disco
con 19 segmentos, y "Abrir editor de timeline" siguio deshabilitado. El
callback comparaba solo un TOKEN que se incrementa con cada carga de proyecto,
y el propio flujo de generacion recarga el proyecto (dos veces, segun el log).
El resultado volvia contra un token mas nuevo, se lo daba por obsoleto y se
descartaba. En consola no quedaba rastro.

    .venv\\Scripts\\python.exe test_worker_context.py
"""

import unittest

from infra.worker_context import should_accept_worker_result

P = r"C:\dev\proj\Bagdad\project.json"
OTRO = r"C:\dev\proj\Gunnerside\project.json"


class AceptarResultado(unittest.TestCase):

    def test_mismo_token_acepta(self):
        ok, _ = should_accept_worker_result(3, 3, P, P)
        self.assertTrue(ok)

    def test_el_caso_del_bug_recarga_del_mismo_proyecto(self):
        """Token cambiado por dos recargas, misma ruta: hay que aceptar."""
        ok, motivo = should_accept_worker_result(3, 5, P, P)
        self.assertTrue(ok, "el guion del proyecto activo se descarto por una recarga")
        self.assertIn("mismo", motivo)

    def test_otro_proyecto_se_descarta(self):
        # Lo que el token protege de verdad: un guion del proyecto A no puede
        # aterrizar sobre el proyecto B.
        ok, motivo = should_accept_worker_result(3, 5, OTRO, P)
        self.assertFalse(ok)
        self.assertIn("otro proyecto", motivo)

    def test_la_ruta_se_compara_normalizada(self):
        # Windows: mayusculas y barras distintas son la misma ruta.
        ok, _ = should_accept_worker_result(
            3, 5, r"c:/dev/proj/bagdad/project.json", P)
        self.assertTrue(ok)

    def test_sin_rutas_y_token_distinto_se_descarta(self):
        # Sin proyecto no hay con que comparar: comportamiento de siempre.
        ok, _ = should_accept_worker_result(3, 5, None, None)
        self.assertFalse(ok)

    def test_worker_sin_token_pero_misma_ruta_acepta(self):
        ok, _ = should_accept_worker_result(None, 5, P, P)
        self.assertTrue(ok)

    def test_siempre_da_un_motivo(self):
        for args in ((3, 3, P, P), (3, 5, P, P), (3, 5, OTRO, P), (3, 5, None, None)):
            _, motivo = should_accept_worker_result(*args)
            self.assertTrue(motivo.strip(), args)


class ElTimerDelDialogoNoSobreviveAlDialogo(unittest.TestCase):
    """crash_log (2026-09-10): singleShot sobre un boton ya destruido."""

    def test_el_timer_tiene_al_dialogo_como_padre(self):
        import io

        fuente = io.open("studio/auto_video_integration_pyqt6.py", encoding="utf-8",
                         errors="replace").read()
        self.assertIn("restore_timer = QTimer(dialog)", fuente)
        self.assertNotIn(
            'QTimer.singleShot(1500, lambda: btn_copy.setText("Copiar prompt completo"))',
            fuente, "volvio el singleShot suelto que reventaba al cerrar el dialogo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
