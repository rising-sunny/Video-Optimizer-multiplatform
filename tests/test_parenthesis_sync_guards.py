# -*- coding: utf-8 -*-
"""Guardas: los parentesis ya no desfasan los subtitulos.

BUG (2026-09-10, "Operacion Gunnerside", 3:44): la narracion se desfasaba de
los subtitulos justo donde habia frases entre parentesis. Dos causas
encadenadas:

  1. El microdocumental pide al LLM las afirmaciones con una clase de certeza
     (`claims[].status`). El modelo FILTRO esas etiquetas a la narracion:
     "(established fact)", "(disputed claim)"... y el TTS las leia en voz alta.
  2. Edge-TTS lee un parentesis como inciso y frena antes y despues. MEDIDO: la
     misma frase de 10 palabras dura 3.48s sin parentesis y 4.18s con ellos,
     0.7s de pausa pura. Los videos largos no usan Whisper -- reparten el
     tiempo de cada segmento proporcionalmente por palabra -- y ese modelo
     ponderaba `.!?` y `,;:` pero NO los parentesis, asi que desde cada uno
     los subtitulos corrian adelantados.

    .venv\\Scripts\\python.exe test_parenthesis_sync_guards.py
"""

import unittest

from pipeline.dynamic_subtitles_generator import WhisperTimestampParser
from pipeline.micro_documentary import find_certainty_labels, strip_certainty_labels

_peso = WhisperTimestampParser._estimate_word_weight


class LasEtiquetasNoLleganALaNarracion(unittest.TestCase):

    CASOS_REALES = [
        "cells at Vemork, halting German output (established fact).",
        "security around all heavy-water facilities (plausible hypothesis).",
        "a year, buying the Allies crucial time (scholarly interpretation).",
        "successful sabotage mission of World War II (disputed claim).",
    ]

    def test_detecta_las_cuatro_del_guion_real(self):
        for frase in self.CASOS_REALES:
            self.assertEqual(len(find_certainty_labels(frase)), 1, frase)

    def test_las_saca_y_deja_la_puntuacion_prolija(self):
        limpio = strip_certainty_labels(self.CASOS_REALES[0])
        self.assertEqual(limpio, "cells at Vemork, halting German output.")
        self.assertNotIn("(", limpio)
        self.assertNotIn(" .", limpio)

    def test_un_parentesis_legitimo_se_conserva(self):
        # Solo se tocan las etiquetas de certeza, no cualquier inciso.
        frase = "Note the aside (which mattered) here."
        self.assertEqual(find_certainty_labels(frase), [])
        self.assertEqual(strip_certainty_labels(frase), frase)

    def test_corchetes_y_mayusculas_tambien(self):
        self.assertEqual(strip_certainty_labels("It fell [Disputed Claim]."), "It fell.")
        self.assertEqual(strip_certainty_labels("Cayo (hecho establecido)."), "Cayo.")

    def test_texto_vacio_no_rompe(self):
        self.assertEqual(strip_certainty_labels(""), "")
        self.assertEqual(find_certainty_labels(None), [])

    def test_el_prompt_lo_prohibe_explicitamente(self):
        import io

        fuente = io.open("pipeline/micro_documentary.py", encoding="utf-8", errors="replace").read()
        self.assertIn("NEVER write the status label itself into the narration", fuente)

    def test_la_validacion_del_guion_las_limpia(self):
        import io

        fuente = io.open("pipeline/micro_documentary.py", encoding="utf-8", errors="replace").read()
        self.assertIn("strip_certainty_labels(seg[\"text\"])", fuente)


class ElRepartoProporcionalSabeDeParentesis(unittest.TestCase):
    """El modelo de pesos tiene que reflejar la pausa que el TTS mete."""

    def test_abrir_parentesis_suma_pausa(self):
        self.assertGreater(_peso("(established"), _peso("established"))

    def test_cerrar_parentesis_suma_pausa(self):
        self.assertGreater(_peso("fact)"), _peso("fact"))

    def test_cerrar_seguido_de_punto_tambien(self):
        # El caso real: "(established fact)." -- el ')' no es el ultimo char.
        self.assertGreater(_peso("fact)."), _peso("fact."))

    def test_la_pausa_es_mayor_que_una_coma(self):
        # MEDIDO: 0.7s por el par, mas que un punto final.
        extra_parentesis = _peso("(word") - _peso("word")
        extra_coma = _peso("word,") - _peso("word")
        self.assertGreater(extra_parentesis, extra_coma)

    def test_una_palabra_normal_no_cambia(self):
        # El peso base de siempre no se toca: solo se suma en parentesis.
        self.assertAlmostEqual(_peso("output"), 6 ** 0.65, places=6)

    def test_el_par_de_parentesis_vale_cerca_de_dos_palabras(self):
        """Calibracion contra la medicion.

        0.7s de pausa a ~0.35s por palabra son ~2 palabras. Con el peso de
        una palabra media (~3 unidades), el par tiene que sumar ~5-6.
        """
        extra = (_peso("(established") - _peso("established")) + (_peso("fact)") - _peso("fact"))
        self.assertGreaterEqual(extra, 4.0)
        self.assertLessEqual(extra, 7.0)


class ElDesfaseSeCorrige(unittest.TestCase):
    """Con pesos, las palabras DESPUES del parentesis arrancan mas tarde."""

    def _reparto(self, palabras, duracion=10.0):
        pesos = [_peso(p) for p in palabras]
        total = sum(pesos)
        t, inicios = 0.0, []
        for w in pesos:
            inicios.append(t)
            t += duracion * w / total
        return dict(zip(palabras, inicios))

    def test_la_palabra_posterior_al_inciso_arranca_mas_tarde_que_sin_pesos(self):
        frase = "the raid halted output (established fact) buying time".split()
        con = self._reparto(frase)
        # Reparto ingenuo: mismos pesos pero ignorando los parentesis.
        sin_pesos = {p: i for p, i in zip(frase, [
            10.0 * sum(_peso(x.strip("()")) for x in frase[:k]) /
            sum(_peso(x.strip("()")) for x in frase) for k in range(len(frase))])}
        self.assertGreater(con["buying"], sin_pesos["buying"],
                           "tras el parentesis el subtitulo deberia esperar mas")


if __name__ == "__main__":
    unittest.main(verbosity=2)
