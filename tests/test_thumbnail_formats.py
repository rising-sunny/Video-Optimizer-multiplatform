# -*- coding: utf-8 -*-
"""Guardas del formato de miniatura (16:9 vs 9:16).

BUG (2026-09-02): todo el subsistema de thumbnails estaba clavado en 16:9.
Pedir una miniatura para un Short devolvia una imagen 1280x720: YouTube la
recorta al centro y se pierde la mitad del encuadre. Ademas el texto se dibujaba
en coordenadas de 1280x720 y el validador media el TERCIO IZQUIERDO, que en
vertical no es donde vive el sujeto.

    .venv\\Scripts\\python.exe test_thumbnail_formats.py

Los tests que necesitan Pillow se saltean solos si no esta.
"""

import os
import shutil
import tempfile
import unittest

from publish import thumbnail_formats as tf

try:
    from PIL import Image
    from thumbnail_compositor import ThumbnailCompositor
    from publish.thumbnail_quality_validator import validate_thumbnail, _analyze_pixels
    PIL_OK = True
except Exception:
    PIL_OK = False


class ResolucionDeFormato(unittest.TestCase):
    """De que formato es la miniatura de este proyecto."""

    def test_el_formato_explicito_manda(self):
        self.assertIs(tf.resolve_format(project_data={"video_format": "9:16"}), tf.SHORT_9_16)
        self.assertIs(tf.resolve_format(project_data={"video_format": "16:9"}), tf.LANDSCAPE_16_9)

    def test_la_plataforma_tambien_alcanza(self):
        self.assertIs(tf.resolve_format(project_data={"platform": "youtube_short"}), tf.SHORT_9_16)
        self.assertIs(tf.resolve_format(project_data={"platform": "reels"}), tf.SHORT_9_16)

    def test_el_vertical_largo_lleva_miniatura_apaisada(self):
        """Un 9:16 de mas de 3 minutos NO es un Short.

        Va al feed normal de YouTube, donde la miniatura sigue siendo 16:9.
        Resolver por aspect ratio le daba una miniatura vertical que nadie ve
        asi: la plataforma tiene que ganarle al formato del video.
        """
        proyecto = {"config": {"video_format": "9:16", "platform_key": "youtube_vertical"}}
        self.assertIs(tf.resolve_format(project_data=proyecto), tf.LANDSCAPE_16_9)

    def test_lee_el_formato_dentro_de_config(self):
        """La GUI escribe el formato en project_data['config'], no en la raiz.

        Mirando solo la raiz, un proyecto de Short bien etiquetado devolvia
        16:9 igual.
        """
        proyecto = {"config": {"video_format": "9:16", "platform_key": "youtube_short"}}
        self.assertIs(tf.resolve_format(project_data=proyecto), tf.SHORT_9_16)

    def test_el_short_de_la_gui_de_punta_a_punta(self):
        # Exactamente el payload que arma `_get_thumbnail_project_payload`.
        proyecto = {
            "config": {"platform_key": "youtube_short", "video_format": "9:16"},
            "storyboard": {"segments": [{"text": "Nan Madol"}]},
        }
        fmt = tf.resolve_format(project_data=proyecto)
        self.assertIs(fmt, tf.SHORT_9_16)
        self.assertEqual(fmt.size, (1080, 1920))

    def test_la_duracion_es_el_ultimo_recurso(self):
        self.assertIs(tf.resolve_format(project_data={"duration": 80}), tf.SHORT_9_16)
        self.assertIs(tf.resolve_format(project_data={"duration": 900}), tf.LANDSCAPE_16_9)

    def test_una_etiqueta_explicita_le_gana_a_la_duracion(self):
        # Un teaser de 80s marcado como long-form es raro pero valido; la
        # etiqueta es mas confiable que inferir del reloj.
        self.assertIs(
            tf.resolve_format(project_data={"video_format": "16:9", "duration": 80}),
            tf.LANDSCAPE_16_9,
        )

    def test_sin_datos_no_cambia_el_comportamiento_historico(self):
        # Un default nuevo no deberia mover en silencio las miniaturas de los
        # videos largos que ya funcionaban.
        self.assertIs(tf.resolve_format(project_data={}), tf.LANDSCAPE_16_9)
        self.assertIs(tf.resolve_format(), tf.LANDSCAPE_16_9)

    def test_basura_no_rompe(self):
        self.assertIs(tf.resolve_format(project_data={"duration": "ochenta"}), tf.LANDSCAPE_16_9)
        self.assertIs(tf.get_format("no_existe"), tf.LANDSCAPE_16_9)


class GeometriaDelFormato(unittest.TestCase):

    def test_el_short_es_vertical_1080x1920(self):
        # El bug: se le pedia 1280x720 al proveedor de imagen incluso para un
        # Short.
        self.assertEqual(tf.SHORT_9_16.size, (1080, 1920))
        self.assertTrue(tf.SHORT_9_16.is_vertical)
        self.assertAlmostEqual(tf.SHORT_9_16.aspect_ratio, 9 / 16.0, places=3)

    def test_el_apaisado_no_se_movio(self):
        self.assertEqual(tf.LANDSCAPE_16_9.size, (1280, 720))
        self.assertFalse(tf.LANDSCAPE_16_9.is_vertical)

    def test_las_cajas_apaisadas_son_las_historicas(self):
        """El rendering 16:9 tiene que quedar identico al de antes.

        Estas eran las coordenadas cableadas en `compose_thumbnail`. Si el
        refactor a fracciones las corre, los thumbnails de long-form cambian
        sin que nadie lo haya pedido.
        """
        f = tf.LANDSCAPE_16_9
        self.assertEqual(f.text_box_pixels("subject_left_text_right"), (720, 120, 1230, 620))
        self.assertEqual(f.text_box_pixels("subject_right_text_left"), (50, 120, 560, 620))
        self.assertEqual(f.text_box_pixels("text_top_center"), (120, 40, 1160, 260))

    def test_la_grilla_recorta_el_9_16_a_2_3(self):
        """MEDIDO en la grilla real de YouTube el 2026-09-02.

        Tarjeta 186x278 (movil) y 214x321 (desktop) = 2:3 exacto, sobre una
        fuente 405x720 = 9:16, con object-fit: cover y object-position 50% 50%.
        O sea: recorte centrado que se come 150 px arriba y 150 px abajo de un
        1080x1920.
        """
        f = tf.SHORT_9_16
        alto_visible = f.width * 3 / 2.0          # 2:3 a partir del ancho
        recorte_por_lado = (f.height - alto_visible) / 2.0
        self.assertAlmostEqual(recorte_por_lado, 150.0, places=1)
        self.assertAlmostEqual(
            f.ui_reserved_top, recorte_por_lado / f.height, places=3,
            msg="ui_reserved_top tiene que ser el recorte real de la grilla")

    def test_el_texto_vertical_cae_en_la_banda_visible(self):
        """La banda util medida es y 7.8% - 71.3%.

        Arriba manda el recorte 2:3 de la grilla; abajo, ese mismo recorte MAS
        el titulo y las vistas que se superponen en movil desde el 75.2% de la
        tarjeta. La caja de arriba empezaba en y=0.05 y le comian el borde.
        """
        f = tf.SHORT_9_16
        tope = f.height * f.ui_reserved_top
        piso = f.height * (1 - f.ui_reserved_bottom)
        self.assertGreater(f.ui_reserved_top, 0)
        self.assertGreater(f.ui_reserved_bottom, 0)
        for nombre in f.text_boxes:
            _, arriba, _, abajo = f.text_box_pixels(nombre)
            self.assertGreaterEqual(
                arriba, tope,
                "la caja '%s' empieza en y=%d, dentro del %.1f%% que recorta la "
                "grilla (y<%d)" % (nombre, arriba, f.ui_reserved_top * 100, tope))
            self.assertLessEqual(
                abajo, piso,
                "la caja '%s' termina en y=%d, sobre la franja que tapa o recorta "
                "YouTube (y>%d)" % (nombre, abajo, piso))

    def test_el_apaisado_no_pierde_nada_por_recorte(self):
        # El titular de un video largo va DEBAJO de la imagen, no encima.
        self.assertEqual(tf.LANDSCAPE_16_9.ui_reserved_top, 0.0)
        self.assertEqual(tf.LANDSCAPE_16_9.ui_reserved_bottom, 0.0)

    def test_toda_caja_cae_dentro_del_lienzo(self):
        for f in tf.FORMATS.values():
            for nombre in f.text_boxes:
                izq, arr, der, ab = f.text_box_pixels(nombre)
                self.assertTrue(0 <= izq < der <= f.width, (f.key, nombre))
                self.assertTrue(0 <= arr < ab <= f.height, (f.key, nombre))

    def test_los_nombres_apaisados_del_llm_no_rompen_en_vertical(self):
        # El LLM sigue devolviendo 'subject_left_text_right'; en vertical no
        # significa nada, pero tiene que caer en una caja valida igual.
        f = tf.SHORT_9_16
        for nombre in ("subject_left_text_right", "subject_right_text_left",
                       "text_top_center", "cualquier_cosa", None, ""):
            self.assertIn(f.resolve_composition(nombre), f.text_boxes)


class ReglasDeEncuadre(unittest.TestCase):
    """Las reglas que van al prompt del generador de imagenes."""

    def test_el_short_no_pide_sujeto_a_la_izquierda(self):
        # "sujeto en el tercio izquierdo, aire arriba a la derecha" es la
        # convencion de 16:9. En vertical el ojo baja: pedir eso desperdiciaba
        # el encuadre y chocaba con la franja inferior.
        reglas = " ".join(tf.SHORT_9_16.composition_rules).lower()
        self.assertNotIn("left third", reglas)
        self.assertNotIn("upper-right third", reglas)
        self.assertIn("2:3", reglas)          # el recorte real de la grilla
        self.assertIn("title and view count", reglas)

    def test_el_apaisado_conserva_su_regla_de_tercios(self):
        reglas = " ".join(tf.LANDSCAPE_16_9.composition_rules).lower()
        self.assertIn("left third", reglas)

    def test_los_dos_formatos_comparten_luz_paleta_y_epoca(self):
        # Lo que no depende del encuadre no se duplica ni se pierde.
        for clave in ("three-point lighting", "period-accurate", "film grain"):
            for f in tf.FORMATS.values():
                self.assertIn(clave, " ".join(f.composition_rules), (f.key, clave))

    def test_el_constraint_de_tamano_dice_el_formato_correcto(self):
        self.assertIn("9:16", tf.SHORT_9_16.prompt_constraint)
        self.assertIn("1080x1920", tf.SHORT_9_16.prompt_constraint)
        self.assertIn("16:9", tf.LANDSCAPE_16_9.prompt_constraint)

    def test_el_brief_al_llm_avisa_del_recorte_y_de_la_banda_util(self):
        brief = tf.SHORT_9_16.llm_brief
        self.assertIn("2:3", brief)
        self.assertIn("71%", brief)


@unittest.skipUnless(PIL_OK, "requiere Pillow")
class CompositorPorFormato(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="thumbfmt_")
        self.base = os.path.join(self.tmp, "base.png")
        Image.new("RGB", (1600, 900), (120, 80, 50)).save(self.base)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _render(self, fmt):
        salida = os.path.join(self.tmp, "out_%s.png" % fmt.key)
        ThumbnailCompositor().compose_thumbnail(
            base_image_path=self.base,
            output_path=salida,
            hook_text="STONE CITY",
            palette_name="orange_cyan",
            composition="subject_left_text_right",
            kicker_text="1180 AD",
            quality_tier="epic_cinematic",
            thumbnail_format=fmt,
        )
        return salida

    def test_el_lienzo_sale_en_el_tamano_del_formato(self):
        for fmt in tf.FORMATS.values():
            with Image.open(self._render(fmt)) as img:
                self.assertEqual(img.size, fmt.size, fmt.key)

    def test_sin_formato_sigue_saliendo_apaisado(self):
        # Compatibilidad: el llamador viejo no pasa formato.
        salida = os.path.join(self.tmp, "default.png")
        ThumbnailCompositor().compose_thumbnail(
            base_image_path=self.base, output_path=salida, hook_text="X",
            palette_name="orange_cyan", composition="text_top_center",
        )
        with Image.open(salida) as img:
            self.assertEqual(img.size, (1280, 720))

    def test_el_placeholder_tambien_respeta_el_formato(self):
        salida = os.path.join(self.tmp, "ph.png")
        ThumbnailCompositor().create_placeholder_background(
            salida, "orange_cyan", "NAN MADOL", thumbnail_format=tf.SHORT_9_16)
        with Image.open(salida) as img:
            self.assertEqual(img.size, tf.SHORT_9_16.size)


@unittest.skipUnless(PIL_OK, "requiere Pillow")
class ValidadorPorEje(unittest.TestCase):
    """El validador medIa siempre el tercio izquierdo.

    Una miniatura vertical bien hecha (sujeto arriba, fondo oscuro abajo) daba
    delta ~0 sobre el eje horizontal y se la puntuaba mal.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="thumbval_")
        # Vertical correcta: mitad de arriba clara y con detalle, abajo oscura.
        img = Image.new("RGB", (270, 480), (20, 16, 12))
        for y in range(0, 160):
            for x in range(270):
                v = 200 if (x // 3) % 2 == 0 else 120
                img.putpixel((x, y), (v, int(v * 0.7), int(v * 0.4)))
        self.vertical = os.path.join(self.tmp, "vert.png")
        img.save(self.vertical)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_el_eje_sale_del_formato(self):
        rep = validate_thumbnail(self.vertical, thumbnail_format=tf.SHORT_9_16)
        self.assertEqual(rep["metrics"]["axis"], "y")

    def test_sin_formato_el_eje_se_deduce_de_la_imagen(self):
        # `validate_thumbnail` tambien se llama a mano desde la consola.
        rep = validate_thumbnail(self.vertical)
        self.assertEqual(rep["metrics"]["axis"], "y")

    def test_medir_un_vertical_con_la_regla_apaisada_lo_castiga(self):
        """Este es el test con dientes: con el eje viejo la miniatura reprueba."""
        with Image.open(self.vertical) as img:
            img.load()
            bien = _analyze_pixels(img, axis="y")
            mal = _analyze_pixels(img, axis="x")

        self.assertGreaterEqual(
            bien["subject_calm_delta"], 20,
            "midiendo por el eje correcto el sujeto tiene que destacar")
        self.assertLess(
            mal["subject_calm_delta"], 20,
            "sobre el eje horizontal esta misma imagen no muestra separacion: "
            "eso es lo que castigaba a los verticales correctos")
        self.assertGreaterEqual(bien["subject_edge_ratio"], 0.55)
        self.assertLess(mal["subject_edge_ratio"], 0.55)

    def test_las_sugerencias_hablan_del_eje_correcto(self):
        rep = validate_thumbnail(self.vertical, thumbnail_format=tf.SHORT_9_16)
        texto = " ".join(rep["suggestions"])
        self.assertNotIn("izquierdo", texto)
        self.assertNotIn("derecho", texto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
