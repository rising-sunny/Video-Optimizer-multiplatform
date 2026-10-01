# -*- coding: utf-8 -*-
"""Guardas: la categoria elegida en la GUI cambia de verdad la persona del guion.

Hasta 2026-09-21 el mapeo categoria -> perfil de tono solo reconocia palabras
en espanol ("misterio", "desastre", "historia"). Los perfiles de canal nombran
las categorias en ingles, asi que "Historical Disasters" y "Historical
Mysteries" caian en 'documentary' como todo lo demas: la categoria no hacia
nada mas que aparecer en el prompt.

    .venv\\Scripts\\python.exe test_tone_profile.py
"""

import unittest

from ai.tone_profile import (PROFILE_DOCUMENTARY, PROFILE_DRAMATIC_FACTUAL, PROFILE_MYSTERY,
                          get_tone_profile_for_category)


class CategoriasDelCanalNuevo(unittest.TestCase):
    """daily_shorts/channel_strategy_profile.json (Stunning Facts of History)."""

    def test_guerra_y_civilizaciones_son_documental(self):
        for cat in ("War & Military History", "Ancient Civilizations & Empires",
                    "Turning Points & Political History", "Science & Technology in History"):
            self.assertEqual(get_tone_profile_for_category(cat), PROFILE_DOCUMENTARY, cat)

    def test_desastres_historicos_son_dramatico_factual(self):
        self.assertEqual(get_tone_profile_for_category("Historical Disasters"), PROFILE_DRAMATIC_FACTUAL)


class CategoriasDelCanalViejo(unittest.TestCase):
    """channel_profiles/stunning-revelations.json."""

    def test_military_history_y_archaeology_son_documental(self):
        self.assertEqual(get_tone_profile_for_category("Military History"), PROFILE_DOCUMENTARY)
        self.assertEqual(get_tone_profile_for_category("Archaeology"), PROFILE_DOCUMENTARY)

    def test_historical_mysteries_es_misterio(self):
        self.assertEqual(get_tone_profile_for_category("Historical Mysteries"), PROFILE_MYSTERY)


class LoDeSiempreSigueIgual(unittest.TestCase):

    def test_espanol(self):
        self.assertEqual(get_tone_profile_for_category("Misterios"), PROFILE_MYSTERY)
        self.assertEqual(get_tone_profile_for_category("Eventos naturales extremos"), PROFILE_DRAMATIC_FACTUAL)
        self.assertEqual(get_tone_profile_for_category("Historia militar/guerras"), PROFILE_DOCUMENTARY)

    def test_vacio_o_desconocido_es_documental(self):
        # El perfil que prohibe inventar: el default seguro.
        self.assertEqual(get_tone_profile_for_category(""), PROFILE_DOCUMENTARY)
        self.assertEqual(get_tone_profile_for_category(None), PROFILE_DOCUMENTARY)
        self.assertEqual(get_tone_profile_for_category("Cocina"), PROFILE_DOCUMENTARY)

    def test_el_sentimiento_de_la_musica_usa_el_perfil_y_no_nombres_en_espanol(self):
        import io
        fuente = io.open("pipeline/storyboard_generator.py", encoding="utf-8", errors="replace").read()
        self.assertNotIn('category in ["Misterios", "Paranormal", "Conspiraciones"]', fuente)
        self.assertIn('self._get_tone_profile_for_category(category) == "mystery"', fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
