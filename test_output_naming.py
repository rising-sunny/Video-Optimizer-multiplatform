# -*- coding: utf-8 -*-
"""Guardas del nombre de archivo de los videos exportados.

Antes salian como `youtube_short_1788485267.mp4`: un timestamp Unix ilegible.
Con varios videos del mismo dia era imposible saber cual era cual sin abrirlos.

    .venv\\Scripts\\python.exe test_output_naming.py
"""

import datetime
import re
import unittest

from output_naming import MAX_SLUG_LEN, build_video_filename, slugify_topic

CUANDO = datetime.datetime(2026, 9, 3, 16, 15, 42)


class SlugDelTema(unittest.TestCase):

    def test_un_tema_normal(self):
        self.assertEqual(slugify_topic("Cahokia"), "cahokia")

    def test_saca_tildes_y_enies(self):
        # El proyecto ya perdio tiempo con cp1252 en rutas y consolas.
        s = slugify_topic("Caral: las seis pirámides del valle de Supe")
        self.assertTrue(s.isascii(), s)
        self.assertIn("piramides", s)

    def test_saca_las_palabras_vacias(self):
        s = slugify_topic("The Fall of the Roman Empire")
        self.assertNotIn("_of_", "_" + s + "_")
        self.assertIn("roman", s)
        self.assertIn("empire", s)

    def test_no_deja_caracteres_ilegales_en_windows(self):
        s = slugify_topic('Halifax: 1917 <explosion> / "el ancla" | ?')
        self.assertFalse(re.search(r'[\\/:*?"<>|]', s), s)

    def test_respeta_el_largo_maximo(self):
        s = slugify_topic("La explosión de Halifax de mil novecientos diecisiete "
                          "y el ancla que voló tres kilómetros y medio")
        self.assertLessEqual(len(s), MAX_SLUG_LEN)

    def test_corta_por_palabra_no_por_letra(self):
        s = slugify_topic("Constantinopla mil cuatrocientos cincuenta y tres canon Orban")
        self.assertFalse(s.endswith("_"))
        # Ninguna palabra del slug puede ser un pedazo cortado.
        for palabra in s.split("_"):
            self.assertGreater(len(palabra), 1, s)

    def test_un_tema_de_solo_stopwords_no_queda_vacio(self):
        # "The Wall" es todo stopwords + una palabra; y "The The" es el caso
        # extremo: mejor devolver algo que un nombre sin tema.
        self.assertTrue(slugify_topic("The Wall"))
        self.assertTrue(slugify_topic("The The"))

    def test_una_palabra_larguisima_igual_da_algo(self):
        s = slugify_topic("Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch")
        self.assertTrue(s)
        self.assertLessEqual(len(s), MAX_SLUG_LEN)

    def test_tema_vacio_devuelve_vacio(self):
        for v in ("", None, "   ", "!!!"):
            self.assertEqual(slugify_topic(v), "")


class NombreCompleto(unittest.TestCase):

    def test_lleva_plataforma_fecha_y_tema(self):
        n = build_video_filename("youtube_short", "Cahokia", when=CUANDO)
        self.assertEqual(n, "youtube_short_20260903_161542_cahokia.mp4")

    def test_la_fecha_es_legible_no_un_epoch(self):
        n = build_video_filename("youtube_short", "Cahokia", when=CUANDO)
        self.assertIn("20260903", n)
        self.assertNotRegex(n, r"_1\d{9}_", "quedo un timestamp Unix")

    def test_ordena_cronologicamente_dentro_de_la_plataforma(self):
        antes = build_video_filename("youtube_short", "b",
                                     when=datetime.datetime(2026, 9, 3, 8, 0, 0))
        despues = build_video_filename("youtube_short", "a",
                                       when=datetime.datetime(2026, 9, 3, 20, 0, 0))
        self.assertLess(antes, despues, "el orden alfabetico no respeta la hora")

    def test_sin_tema_sigue_siendo_valido(self):
        n = build_video_filename("youtube_short", "", when=CUANDO)
        self.assertEqual(n, "youtube_short_20260903_161542.mp4")

    def test_dos_videos_del_mismo_tema_no_colisionan(self):
        a = build_video_filename("youtube_short", "Caral",
                                 when=datetime.datetime(2026, 9, 3, 16, 15, 10))
        b = build_video_filename("youtube_short", "Caral",
                                 when=datetime.datetime(2026, 9, 3, 16, 15, 40))
        self.assertNotEqual(a, b, "sin segundos, dos videos del mismo minuto chocan")

    def test_la_plataforma_se_limpia(self):
        n = build_video_filename("YouTube Short!", "Caral", when=CUANDO)
        self.assertTrue(n.startswith("youtube_short_"), n)

    def test_sin_plataforma_no_queda_un_nombre_raro(self):
        n = build_video_filename("", "Caral", when=CUANDO)
        self.assertTrue(n.startswith("video_"), n)

    def test_el_nombre_entero_es_seguro_en_windows(self):
        n = build_video_filename("youtube_short",
                                 'Halifax: 1917 <explosión> / "el ancla"', when=CUANDO)
        self.assertFalse(re.search(r'[\\/:*?"<>|]', n), n)
        self.assertTrue(n.isascii(), n)
        self.assertTrue(n.endswith(".mp4"))

    def test_no_se_pasa_de_largo(self):
        # Estos archivos viven en carpetas anidadas y ademas se copian a
        # staging temporales: Windows corta en 260.
        n = build_video_filename(
            "youtube_short",
            "La explosión de Halifax de 1917 y el ancla que voló tres kilómetros y medio "
            "sobre la ciudad arrasada", when=CUANDO)
        self.assertLess(len(n), 100, n)


if __name__ == "__main__":
    unittest.main(verbosity=2)
