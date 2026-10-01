# -*- coding: utf-8 -*-
"""Guardas de las vistas previas de estilos de subtitulos.

La previa se genera con el MISMO `DynamicSubtitleEngine` que usa el pipeline.
Una previa dibujada aparte se desincroniza del motor real en la primera
modificacion, y entonces miente justo cuando mas confias en ella. Estos tests
protegen esa union y la frase de ejemplo.

    .venv\\Scripts\\python.exe test_subtitle_style_preview.py

Los que necesitan FFmpeg se saltean solos si no esta.
"""

import os
import shutil
import tempfile
import unittest

from studio import subtitle_style_preview as sp

FFMPEG = shutil.which("ffmpeg") or r"C:\ffmpeg-7.1.1-full_build\bin\ffmpeg.exe"
FFMPEG_OK = bool(FFMPEG and os.path.exists(FFMPEG))


class FraseDeEjemplo(unittest.TestCase):

    def test_cada_palabra_trae_su_timing(self):
        segs = sp.sample_segments()
        palabras = segs[0]["words"]
        self.assertEqual(len(palabras), len(sp.SAMPLE_TEXT.split()))
        for w in palabras:
            self.assertIn("word", w)
            self.assertLess(w["start"], w["end"])

    def test_las_palabras_van_en_orden_y_sin_huecos(self):
        palabras = sp.sample_segments()[0]["words"]
        for anterior, siguiente in zip(palabras, palabras[1:]):
            self.assertAlmostEqual(anterior["end"], siguiente["start"], places=2)

    def test_dura_lo_pedido(self):
        segs = sp.sample_segments(duration=4.0)
        self.assertAlmostEqual(segs[0]["end"], 4.0, places=2)
        self.assertAlmostEqual(segs[0]["words"][-1]["end"], 4.0, places=1)

    def test_las_palabras_largas_duran_mas(self):
        # Repartir en partes iguales haria que el karaoke se viera falso:
        # '20,000' tiene que durar mas que 'in'.
        palabras = {w["word"]: w["end"] - w["start"]
                    for w in sp.sample_segments()[0]["words"]}
        self.assertGreater(palabras["20,000"], palabras["in"])

    def test_texto_vacio_no_rompe(self):
        self.assertEqual(sp.sample_segments(""), [])
        self.assertEqual(sp.sample_segments("   "), [])

    def test_la_frase_tiene_una_cifra(self):
        # Los ganchos del canal son numericos; la previa deberia mostrar como
        # se ve un numero, que es lo que mas se usa.
        self.assertTrue(any(c.isdigit() for c in sp.SAMPLE_TEXT))


class NombreYCache(unittest.TestCase):

    def test_un_archivo_por_estilo(self):
        self.assertNotEqual(sp.preview_filename("hormozi"),
                            sp.preview_filename("mrbeast"))

    def test_el_nombre_es_seguro_y_estable(self):
        n = sp.preview_filename("CapCut Focus/Pro")
        self.assertTrue(n.endswith(".gif"))
        self.assertNotIn("/", n)
        self.assertEqual(n, sp.preview_filename("CapCut Focus/Pro"))

    def test_la_version_invalida_la_cache(self):
        # Al cambiar el motor de subtitulos hay que poder tirar las previas
        # viejas sin que el usuario borre nada a mano.
        a = sp.preview_filename("hormozi", version="v1")
        b = sp.preview_filename("hormozi", version="v2")
        self.assertNotEqual(a, b)

    def test_estilo_vacio_no_rompe(self):
        self.assertTrue(sp.preview_filename("").endswith(".gif"))


class RutaDeAssParaFfmpeg(unittest.TestCase):
    """El filtro `subtitles` de FFmpeg interpreta ':' como separador."""

    def test_escapa_la_unidad_de_windows(self):
        escapada = sp._ass_para_ffmpeg(r"C:\temp\muestra.ass")
        self.assertNotIn("\\t", escapada)
        self.assertIn("C\\:", escapada)
        self.assertNotIn("\\\\", escapada)


class DescripcionDelEstilo(unittest.TestCase):

    def test_menciona_fuente_y_animacion(self):
        d = sp.describe_style("hormozi")
        self.assertIn("Impact", d)
        self.assertIn("bounce", d)

    def test_avisa_del_karaoke_solo_si_lo_tiene(self):
        self.assertIn("karaoke", sp.describe_style("hormozi"))
        self.assertNotIn("karaoke", sp.describe_style("capcut_podcast"))

    def test_un_estilo_inexistente_no_rompe(self):
        self.assertIsInstance(sp.describe_style("no_existe"), str)


class ElMotorEsElMismoQueElDelVideo(unittest.TestCase):
    """Si la previa dejara de usar el motor real, empezaria a mentir."""

    def test_usa_dynamic_subtitle_engine(self):
        import io

        fuente = io.open("studio/subtitle_style_preview.py", encoding="utf-8").read()
        self.assertIn("from pipeline.dynamic_subtitles_generator import DynamicSubtitleEngine",
                      fuente)
        self.assertIn("generate_from_segments", fuente)

    def test_renderiza_a_la_resolucion_real_del_short(self):
        # Los tamanos de fuente de cada estilo estan calibrados sobre
        # 1080x1920: renderizar chico deformaria las proporciones.
        self.assertEqual((sp.RENDER_W, sp.RENDER_H), (1080, 1920))

    def test_la_clave_sale_de_la_misma_regla_del_pipeline(self):
        from pipeline.dynamic_subtitle_wrapper import normalize_subtitle_style

        for etiqueta in ("PRO • CapCut Focus (Center Highlight)",
                         "🔥 Hormozi (Amarillo + Karaoke + Emojis)"):
            self.assertEqual(sp.style_key_from_label(etiqueta),
                             normalize_subtitle_style(etiqueta))


@unittest.skipUnless(FFMPEG_OK, "requiere FFmpeg")
class GeneracionReal(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="subprevtest_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_genera_un_gif_valido(self):
        from pathlib import Path

        ruta = sp.build_preview("hormozi", cache_dir=Path(self.tmp), force=True)
        self.assertIsNotNone(ruta, "no se genero la vista previa")
        self.assertTrue(os.path.getsize(ruta) > 2000, "el GIF salio vacio")
        with open(ruta, "rb") as fh:
            self.assertEqual(fh.read(3), b"GIF")

    def test_la_segunda_vez_usa_la_cache(self):
        from pathlib import Path

        carpeta = Path(self.tmp)
        primera = sp.build_preview("tiktok", cache_dir=carpeta, force=True)
        marca = os.path.getmtime(primera)
        segunda = sp.build_preview("tiktok", cache_dir=carpeta)
        self.assertEqual(primera, segunda)
        self.assertEqual(marca, os.path.getmtime(segunda), "regenero pudiendo cachear")

    def test_un_estilo_inexistente_cae_al_de_por_defecto_sin_romper(self):
        from pathlib import Path

        ruta = sp.build_preview("no_existe_este_estilo", cache_dir=Path(self.tmp),
                                force=True)
        self.assertIsNotNone(ruta)


if __name__ == "__main__":
    unittest.main(verbosity=2)
