# -*- coding: utf-8 -*-
"""Guardas de la persistencia de opciones del proyecto.

BUG (2026-09-03): al cerrar y reabrir la app, tres opciones volvian al valor por
defecto -- proveedor de imagenes, preset cinematografico y estilo de subtitulos
dinamicos. El proyecto se restauraba bien en todo lo demas, asi que parecia
aleatorio.

Eran tres causas distintas:

  1. `hasattr(self, 'image_provider_combo')` en vez de
     `hasattr(self.studio_tab, ...)`. `self` es el gestor de proyectos y NO
     tiene esos widgets, asi que el guard daba falso SIEMPRE y se escribia el
     default en vez de la seleccion. Comprobado en tres project.json seguidos:
     todos con 'Auto (Inteligente)' pese a haber elegido 'Manual (Gratuito)'.
  2. `subtitle_style` no se escribia en una de las tres rutas de guardado, y
     en otra se guardaba None si los subtitulos estaban apagados.
  3. El estilo visual se restauraba ANTES que el proveedor, y cambiar el
     proveedor vacia y repuebla `style_combo`: lo restaurado se perdia.

Estos tests son estaticos (leen el codigo) porque las alternativas exigen
levantar Qt entero. Cubren la CLASE de error, no un caso puntual.

    .venv\\Scripts\\python.exe test_project_config_persistence.py
"""

import io
import re
import unittest

FUENTE = io.open("studio_project_manager.py", encoding="utf-8", errors="replace").read()

# Opciones que el usuario espera encontrar tal como las dejo.
CLAVES_ESPERADAS = (
    "image_provider",
    "cinematic_enabled",
    "cinematic_preset",
    "cinematic_intensity",
    "subtitle_style",
    "subtitles_enabled",
    "style",
    "visual_mode",
    "transition_type",
    "opening_style",
)


class ElGuardMiraElObjetoCorrecto(unittest.TestCase):
    """La causa #1: hasattr(self, ...) sobre widgets que viven en studio_tab."""

    def test_ningun_hasattr_pregunta_por_el_objeto_equivocado(self):
        # Busca: se LEE self.studio_tab.<w> pero se PREGUNTA hasattr(self, '<w>')
        sospechosos = []
        for m in re.finditer(
                r"self\.studio_tab\.(\w+)\.[\w()]+.{0,160}?hasattr\(\s*\n?\s*self,\s*'(\w+)'\)",
                FUENTE, re.S):
            if m.group(1) == m.group(2):
                linea = FUENTE[:m.start()].count("\n") + 1
                sospechosos.append("linea %d: hasattr(self, %r)" % (linea, m.group(2)))
        self.assertEqual(
            sospechosos, [],
            "el guard mira 'self' pero el widget vive en 'self.studio_tab', "
            "asi que siempre escribe el valor por defecto:\n  " + "\n  ".join(sospechosos))

    def test_los_widgets_conocidos_se_leen_de_studio_tab(self):
        for widget in ("image_provider_combo", "cinematic_check",
                       "cinematic_preset_combo", "cinematic_intensity_combo",
                       "subtitle_style_combo"):
            usos = re.findall(r"hasattr\(\s*\n?\s*(self(?:\.studio_tab)?),\s*'%s'\)" % widget,
                              FUENTE)
            self.assertTrue(usos, "no se comprueba %s en ningun lado" % widget)
            for objeto in usos:
                self.assertEqual(objeto, "self.studio_tab",
                                 "hasattr(%s, '%s') mira el objeto equivocado"
                                 % (objeto, widget))


class TodasLasRutasGuardanLoMismo(unittest.TestCase):
    """La causa #2: hay tres rutas de guardado y una omitia una clave."""

    def _rutas(self):
        """Los bloques donde se arma o actualiza el dict `config`."""
        # Ruta A y C construyen el dict literal; la B asigna config['clave'].
        literales = [m.start() for m in re.finditer(r"'subtitles_enabled':", FUENTE)]
        asignaciones = [m.start() for m in re.finditer(r"config\['subtitles_enabled'\]", FUENTE)]
        return literales + asignaciones

    def test_hay_mas_de_una_ruta_de_guardado(self):
        # Si algun dia queda una sola, este test sobra y hay que borrarlo.
        self.assertGreaterEqual(len(self._rutas()), 2)

    def test_el_estilo_de_subtitulos_se_guarda_en_todas(self):
        # Era la clave que faltaba: se perdia segun por donde pasara el
        # auto-guardado.
        literales = len(re.findall(r"'subtitle_style':", FUENTE))
        asignaciones = len(re.findall(r"config\['subtitle_style'\]", FUENTE))
        self.assertGreaterEqual(
            literales + asignaciones, len(self._rutas()),
            "alguna ruta de guardado no escribe subtitle_style")

    def test_ninguna_clave_esperada_quedo_sin_guardar(self):
        for clave in CLAVES_ESPERADAS:
            presente = ("'%s':" % clave) in FUENTE or ("config['%s']" % clave) in FUENTE
            self.assertTrue(presente, "no se guarda la opcion %r" % clave)


class OrdenDeRestauracion(unittest.TestCase):
    """La causa #3: el proveedor repuebla el combo de estilo."""

    def test_el_estilo_visual_se_restaura_despues_del_proveedor(self):
        # Ojo con el matcheo: "style_combo" es subcadena de
        # "subtitle_style_combo" y sin el lookbehind este test da un falso
        # positivo apuntando a la linea equivocada.
        pos_proveedor = re.search(
            r"image_provider_combo\.setCurrentIndex", FUENTE).start()
        pos_estilo = re.search(
            r"(?<!subtitle_)style_combo\.setCurrentIndex", FUENTE).start()
        self.assertLess(
            pos_proveedor, pos_estilo,
            "el estilo se restaura antes que el proveedor; cambiar el proveedor "
            "vacia style_combo y borra lo restaurado")

    def test_el_estilo_de_subtitulos_no_depende_de_que_esten_activados(self):
        # Antes estaba anidado dentro de `if config.get('subtitles_enabled')`:
        # con los subtitulos apagados no se restauraba, y al encenderlos
        # aparecia el estilo por defecto.
        bloque = re.search(
            r"subtitles_check\.setChecked.{0,700}?subtitle_style_combo\.setCurrentIndex",
            FUENTE, re.S)
        self.assertIsNotNone(bloque, "no se encontro la restauracion del estilo")
        self.assertNotIn("if config.get('subtitles_enabled'):", bloque.group(0),
                         "el estilo sigue anidado bajo subtitles_enabled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
