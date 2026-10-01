# -*- coding: utf-8 -*-
"""Guardas del recorte sobre la forma de onda.

BUG (2026-09-03): no se podia recortar con el mouse. Las barras solo se
dibujaban `if start_time > 0 or end_time < duration`, asi que en una pista
recien cargada (inicio 0, fin = duracion) no habia NINGUNA barra visible y no
habia nada que agarrar para empezar. Encima el margen de clic era de 5 px.

    .venv\\Scripts\\python.exe test_waveform_geometry.py

Sin Qt: la matematica vive en `waveform_geometry`.
"""

import unittest

from studio import waveform_geometry as wg

DUR = 300.0    # 5:00
ANCHO = 600    # 2 px por segundo


class ConversionTiempoPixel(unittest.TestCase):

    def test_ida_y_vuelta(self):
        for t in (0.0, 1.5, 150.0, 299.9, 300.0):
            x = wg.time_to_x(t, DUR, ANCHO)
            self.assertAlmostEqual(wg.x_to_time(x, DUR, ANCHO), t, delta=0.6)

    def test_los_extremos_caen_en_los_bordes(self):
        self.assertEqual(wg.time_to_x(0, DUR, ANCHO), 0)
        self.assertEqual(wg.time_to_x(DUR, DUR, ANCHO), ANCHO)

    def test_fuera_de_rango_se_recorta(self):
        self.assertEqual(wg.time_to_x(-5, DUR, ANCHO), 0)
        self.assertEqual(wg.time_to_x(9999, DUR, ANCHO), ANCHO)
        self.assertEqual(wg.x_to_time(-40, DUR, ANCHO), 0.0)
        self.assertEqual(wg.x_to_time(9999, DUR, ANCHO), DUR)

    def test_sin_duracion_no_divide_por_cero(self):
        self.assertEqual(wg.time_to_x(10, 0, ANCHO), 0)
        self.assertEqual(wg.x_to_time(10, 0, ANCHO), 0.0)
        self.assertEqual(wg.x_to_time(10, DUR, 0), 0.0)


class AgarrarLasBarras(unittest.TestCase):

    def test_una_pista_sin_recortar_igual_se_puede_agarrar(self):
        """El caso que no funcionaba: inicio 0, fin = duracion."""
        self.assertEqual(wg.hit_test(0, 0.0, DUR, DUR, ANCHO), "start")
        self.assertEqual(wg.hit_test(ANCHO, 0.0, DUR, DUR, ANCHO), "end")

    def test_el_margen_es_comodo(self):
        # Con 5 px era imposible acertar; ahora hay 12 a cada lado.
        self.assertGreaterEqual(wg.GRAB_TOLERANCE_PX, 10)
        sx = wg.time_to_x(100, DUR, ANCHO)
        self.assertEqual(wg.hit_test(sx + 9, 100.0, 200.0, DUR, ANCHO), "start")
        self.assertEqual(wg.hit_test(sx - 9, 100.0, 200.0, DUR, ANCHO), "start")

    def test_el_interior_devuelve_region(self):
        self.assertEqual(wg.hit_test(300, 100.0, 200.0, DUR, ANCHO), "region")

    def test_fuera_del_recorte_no_es_nada(self):
        self.assertIsNone(wg.hit_test(50, 100.0, 200.0, DUR, ANCHO))

    def test_con_las_barras_encimadas_gana_inicio(self):
        # Si ganara 'end', un recorte al minimo dejaria la barra de inicio
        # inalcanzable para siempre.
        self.assertEqual(wg.hit_test(200, 100.0, 100.2, DUR, ANCHO), "start")


class RangoValido(unittest.TestCase):

    def test_no_se_puede_invertir(self):
        inicio, fin = wg.clamp_range(200.0, 100.0, DUR)
        self.assertLess(inicio, fin)

    def test_respeta_un_largo_minimo(self):
        inicio, fin = wg.clamp_range(100.0, 100.0, DUR)
        self.assertGreaterEqual(fin - inicio, wg.MIN_SELECTION_S)

    def test_no_se_sale_de_la_pista(self):
        inicio, fin = wg.clamp_range(-50.0, 9999.0, DUR)
        self.assertEqual((inicio, fin), (0.0, DUR))

    def test_al_minimo_contra_el_final_se_corre_el_inicio(self):
        inicio, fin = wg.clamp_range(DUR, DUR, DUR)
        self.assertLessEqual(fin, DUR)
        # Con delta: 300.0 - 299.8 da 0.19999999999998863 en coma flotante.
        self.assertAlmostEqual(fin - inicio, wg.MIN_SELECTION_S, places=6)

    def test_pista_de_duracion_cero(self):
        self.assertEqual(wg.clamp_range(0, 10, 0), (0.0, 0.0))


class MoverElRecorteEntero(unittest.TestCase):

    def test_conserva_el_largo(self):
        inicio, fin = wg.move_region(100.0, 160.0, +25.0, DUR)
        self.assertAlmostEqual(fin - inicio, 60.0, places=6)
        self.assertAlmostEqual(inicio, 125.0, places=6)

    def test_al_chocar_con_el_final_se_frena_sin_encogerse(self):
        # Si se encogiera, arrastrar hasta el borde y volver devolveria un
        # recorte mas corto que el que se tenia.
        inicio, fin = wg.move_region(200.0, 260.0, +500.0, DUR)
        self.assertAlmostEqual(fin, DUR, places=6)
        self.assertAlmostEqual(fin - inicio, 60.0, places=6)

    def test_al_chocar_con_el_inicio_tampoco_se_encoge(self):
        inicio, fin = wg.move_region(50.0, 110.0, -500.0, DUR)
        self.assertAlmostEqual(inicio, 0.0, places=6)
        self.assertAlmostEqual(fin - inicio, 60.0, places=6)


class TextosDeLaInterfaz(unittest.TestCase):

    def test_formato_con_decima(self):
        self.assertEqual(wg.format_timecode(0), "0:00.0")
        self.assertEqual(wg.format_timecode(65.4), "1:05.4")
        self.assertEqual(wg.format_timecode(333.0), "5:33.0")

    def test_negativos_y_basura_no_rompen(self):
        self.assertEqual(wg.format_timecode(-10), "0:00.0")
        self.assertEqual(wg.format_timecode(None), "0:00.0")
        self.assertEqual(wg.format_timecode("x"), "0:00.0")

    def test_el_resumen_trae_las_tres_cifras(self):
        texto = wg.describe_selection(12.4, 95.0)
        self.assertIn("0:12.4", texto)
        self.assertIn("1:35.0", texto)
        self.assertIn("1:22.6", texto)   # la duracion del recorte


if __name__ == "__main__":
    unittest.main(verbosity=2)
