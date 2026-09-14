# -*- coding: utf-8 -*-
"""Guardas: varios recortes del mismo video de YouTube no se pisan.

BUG (2026-09-04): agregar un recorte de un video a un segmento funcionaba, pero
sacar OTRO fragmento del MISMO video rompia. Dos causas encadenadas:

  1. La descarga se guardaba como `youtube_<hash>_<titulo>.mp4`, un nombre que
     depende solo del VIDEO, no del tramo.
  2. Al recortar se hacia `os.replace(temp, descargado)`: el recorte PISABA la
     descarga completa.

Resultado: el segundo recorte partia de un archivo que ya era el primer clip
(pedir 40-60s de un clip de 10s no da nada), o al re-descargar encima el
segmento que YA apuntaba a ese archivo cambiaba de contenido en silencio.

    .venv\\Scripts\\python.exe test_youtube_clip_naming.py
"""

import re
import unittest

from output_naming import build_clip_filename

VID = "dQw4w9WgXcQ"
TITULO = "Leningrad: the Road of Life"


class UnArchivoPorRecorte(unittest.TestCase):

    def test_dos_tramos_del_mismo_video_dan_nombres_distintos(self):
        """El corazon del bug."""
        a = build_clip_filename(VID, TITULO, 10.0, 20.0)
        b = build_clip_filename(VID, TITULO, 40.0, 60.0)
        self.assertNotEqual(a, b)

    def test_el_mismo_tramo_da_el_mismo_nombre(self):
        # Reutilizable como cache: volver a pedir el mismo recorte no
        # deberia recodificar.
        a = build_clip_filename(VID, TITULO, 10.0, 20.0)
        b = build_clip_filename(VID, TITULO, 10.0, 20.0)
        self.assertEqual(a, b)

    def test_distingue_centesimas(self):
        # Dos recortes que empiezan en 10.20 y 10.25 son distintos.
        a = build_clip_filename(VID, TITULO, 10.20, 20.0)
        b = build_clip_filename(VID, TITULO, 10.25, 20.0)
        self.assertNotEqual(a, b)

    def test_videos_distintos_no_colisionan(self):
        a = build_clip_filename("aaaaaaaaaaa", TITULO, 0.0, 10.0)
        b = build_clip_filename("bbbbbbbbbbb", TITULO, 0.0, 10.0)
        self.assertNotEqual(a, b)

    def test_el_nombre_lleva_el_id_para_reconocerlo(self):
        self.assertIn(VID, build_clip_filename(VID, TITULO, 1.0, 2.0))

    def test_los_sufijos_separan_las_variantes(self):
        # trim y loop derivan del mismo tramo pero no son el mismo archivo.
        base = build_clip_filename(VID, TITULO, 0.0, 8.0)
        trim = build_clip_filename(VID, TITULO, 0.0, 8.0, suffix="trim")
        loop = build_clip_filename(VID, TITULO, 0.0, 8.0, suffix="loop")
        self.assertEqual(len({base, trim, loop}), 3)

    def test_ordena_por_tramo_dentro_del_video(self):
        # El relleno con ceros hace que el listado quede en orden temporal.
        nombres = sorted(build_clip_filename(VID, TITULO, s, s + 5)
                         for s in (100.0, 9.0, 45.0))
        self.assertIn("00009", nombres[0])


class NombreSeguro(unittest.TestCase):

    def test_sin_caracteres_ilegales_en_windows(self):
        n = build_clip_filename(VID, 'Leningrado: "el camino" / 1941 <?>', 1.0, 2.0)
        self.assertFalse(re.search(r'[\\/:*?"<>|]', n), n)
        self.assertTrue(n.isascii(), n)

    def test_sin_tildes(self):
        n = build_clip_filename(VID, "El cañón de Orbán, Constantinopla", 1.0, 2.0)
        self.assertTrue(n.isascii(), n)
        self.assertIn("canon", n)

    def test_no_se_pasa_de_largo(self):
        n = build_clip_filename(VID, "T" * 300, 1.0, 2.0)
        self.assertLess(len(n), 100, n)

    def test_sin_id_ni_titulo_igual_da_algo_usable(self):
        n = build_clip_filename("", "", 0.0, 0.0)
        self.assertTrue(n.endswith(".mp4"))
        self.assertGreater(len(n), 8)

    def test_termina_en_mp4(self):
        self.assertTrue(build_clip_filename(VID, TITULO, 1.0, 2.0).endswith(".mp4"))


class LaDescargaNoSeToca(unittest.TestCase):
    """El clip nunca puede compartir nombre con la descarga completa."""

    def test_el_clip_no_pisa_el_nombre_de_la_descarga(self):
        descarga = "youtube_%d_%s.mp4" % (hash(VID) % 100000, "Leningrad")
        for inicio, fin in ((0.0, 10.0), (10.0, 20.0), (0.0, 0.0)):
            self.assertNotEqual(build_clip_filename(VID, TITULO, inicio, fin), descarga)

    def test_los_temporales_llevan_extension_que_ffmpeg_entienda(self):
        """BUG (2026-09-08): el temporal se llamaba `<clip>.part`.

        ffmpeg deduce el formato de salida por la EXTENSION, asi que con
        `.part` abortaba: "Unable to choose an output format for '...part';
        use a standard extension for the filename". El recorte fallaba entero
        y el dialogo caia a "Se mantendra el video completo".
        """
        import io
        import re

        fuente = io.open("youtube_video_search_dialog.py", encoding="utf-8",
                         errors="replace").read()
        temporales = re.findall(r'temp_output_path\s*=\s*\w+\s*\+\s*"([^"]+)"', fuente)
        self.assertTrue(temporales, "no se encontro ningun temporal por concatenacion")
        for sufijo in temporales:
            self.assertTrue(
                sufijo.endswith((".mp4", ".mov", ".mkv", ".webm")),
                "el temporal termina en %r y ffmpeg no puede deducir el formato" % sufijo)

    def test_el_codigo_ya_no_sobrescribe_la_descarga(self):
        import io

        fuente = io.open("youtube_video_search_dialog.py", encoding="utf-8",
                         errors="replace").read()
        self.assertNotIn("os.replace(temp_output_path, downloaded_path)", fuente,
                         "volvio a aparecer el os.replace que pisaba la descarga")
        self.assertIn("source_path = downloaded_path", fuente,
                      "se perdio la cache de solo lectura de la descarga")


if __name__ == "__main__":
    unittest.main(verbosity=2)
