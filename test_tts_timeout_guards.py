# -*- coding: utf-8 -*-
"""Guardas: el TTS no puede colgar el ensamblaje para siempre.

BUG (2026-09-02): al ensamblar, la app quedo clavada en "Generando narracion
con la voz seleccionada" y no habia forma de salir. Causa: `communicate.save()`
de edge-tts abre un WebSocket contra Microsoft SIN timeout, y el dialogo modal
del handler se creo con `setCancelButton(None)`. Los reintentos que ya existian
no ayudaban, porque un cuelgue nunca lanza excepcion.

    .venv\\Scripts\\python.exe test_tts_timeout_guards.py
"""

import asyncio
import os
import shutil
import tempfile
import unittest

from tts_generator import TextToSpeechGenerator


class TimeoutPorLargoDelGuion(unittest.TestCase):

    def setUp(self):
        self.tts = TextToSpeechGenerator()

    def test_un_guion_corto_igual_tiene_piso(self):
        # Sin piso, un guion de 3 palabras daria un timeout de decimas y
        # cortaria peticiones sanas.
        t = self.tts._edge_tts_timeout_for("Nan Madol")
        self.assertEqual(t, self.tts.EDGE_TTS_MIN_TIMEOUT_S)

    def test_un_guion_largo_recibe_mas_tiempo(self):
        corto = self.tts._edge_tts_timeout_for("x" * 100)
        largo = self.tts._edge_tts_timeout_for("x" * 8000)
        self.assertGreater(largo, corto)

    def test_el_bloque_maximo_entra_con_margen(self):
        # 3500 chars es el tope por request que usa el chunking.
        t = self.tts._edge_tts_timeout_for("x" * 3500)
        self.assertGreater(t, 60)
        self.assertLess(t, 200, "un timeout enorme no arregla nada: vuelve a colgar")

    def test_guion_vacio_no_rompe(self):
        self.assertGreaterEqual(self.tts._edge_tts_timeout_for(""), 1)
        self.assertGreaterEqual(self.tts._edge_tts_timeout_for(None), 1)


class TimeoutEsRecuperable(unittest.TestCase):
    """El timeout tiene que disparar el reintento, no darse por vencido."""

    def test_asyncio_timeout_se_reconoce_por_tipo(self):
        # `str(asyncio.TimeoutError())` es la cadena VACIA: buscar la palabra
        # "timeout" en el mensaje no lo detecta nunca.
        self.assertEqual(str(asyncio.TimeoutError()), "")
        self.assertTrue(
            TextToSpeechGenerator._is_transient_edge_tts_error(asyncio.TimeoutError()),
            "el corte por timeout se trataba como error definitivo")

    def test_los_transitorios_de_siempre_siguen_andando(self):
        for msg in ("503 Service Unavailable", "connection reset", "no audio received"):
            self.assertTrue(
                TextToSpeechGenerator._is_transient_edge_tts_error(RuntimeError(msg)), msg)

    def test_un_error_de_parametros_no_se_reintenta(self):
        self.assertFalse(TextToSpeechGenerator._is_transient_edge_tts_error(
            RuntimeError("Verify that your parameters are correct")))


class UnCuelgueSeCorta(unittest.TestCase):
    """El caso real: el proveedor acepta la conexion y no responde nunca."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ttshang_")
        self.tts = TextToSpeechGenerator()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_que_nunca_vuelve_termina_cortado(self):
        import tts_generator

        class CommunicateColgado:
            def __init__(self, *a, **kw):
                pass

            async def save(self, filename):
                await asyncio.sleep(3600)   # jamas responde

        class ModuloFalso:
            Communicate = CommunicateColgado

        original = tts_generator.edge_tts
        tts_generator.edge_tts = ModuloFalso
        try:
            self.tts.EDGE_TTS_MIN_TIMEOUT_S = 0.4     # acelerar el test
            destino = os.path.join(self.tmp, "out.mp3")
            resultado = asyncio.run(
                self.tts._generate_edge_tts_narration(
                    "Nan Madol", destino, "en-US-AriaNeural", max_retries=1)
            )
            # Sin el arreglo esto no vuelve nunca; con el arreglo devuelve None
            # y el llamador puede caer a otro proveedor.
            self.assertIsNone(resultado)
        finally:
            tts_generator.edge_tts = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
