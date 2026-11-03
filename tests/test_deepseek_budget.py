"""DeepSeek: clave desde archivo (DEEPSEEK_API_KEY_FILE) y presupuesto diario."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai import deepseek_client as ds
from infra.env_loader import _load_key_from_file


def respuesta(tin=1000, tout=500, texto="hola"):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"choices": [{"message": {"content": texto}}],
                           "usage": {"prompt_tokens": tin, "completion_tokens": tout}}
    return r


class ClaveDesdeArchivo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "api-key"

    def test_usa_el_archivo_si_no_hay_clave(self):
        self.file.write_text("sk-desde-archivo\n", encoding="utf-8")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY_FILE": str(self.file)}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            self.assertTrue(_load_key_from_file("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"))
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "sk-desde-archivo")

    def test_la_variable_directa_manda_sobre_el_archivo(self):
        self.file.write_text("sk-archivo", encoding="utf-8")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-directa", "DEEPSEEK_API_KEY_FILE": str(self.file)}):
            self.assertFalse(_load_key_from_file("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"))
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "sk-directa")

    def test_archivo_inexistente_o_vacio_no_rompe(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY_FILE": str(self.file)}):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            self.assertFalse(_load_key_from_file("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"))
            self.file.write_text("  \n", encoding="utf-8")
            self.assertFalse(_load_key_from_file("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"))
            self.assertNotIn("DEEPSEEK_API_KEY", os.environ)


class Presupuesto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.budget = Path(self.tmp.name) / "budget.json"
        env = {"DEEPSEEK_API_KEY": "sk-test", "DEEPSEEK_BUDGET_FILE": str(self.budget),
               "DEEPSEEK_DAILY_BUDGET_USD": "0.01", "DEEPSEEK_PRICE_IN_PER_M": "1", "DEEPSEEK_PRICE_OUT_PER_M": "2"}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_acumula_el_gasto_estimado(self):
        with patch.object(ds.requests, "post", return_value=respuesta(1000, 500)):
            self.assertEqual(ds.DeepSeekClient()._generate("p"), "hola")
        st = ds.budget_state()
        # (1000*1 + 500*2) / 1e6 = 0.002
        self.assertAlmostEqual(st["usd"], 0.002, places=6)
        self.assertEqual((st["requests"], st["input_tokens"], st["output_tokens"]), (1, 1000, 500))

    def test_al_llegar_al_tope_no_llama_a_la_api(self):
        self.budget.write_text(json.dumps({"date": ds._today(), "usd": 0.01, "requests": 5,
                                           "input_tokens": 1, "output_tokens": 1}), encoding="utf-8")
        with patch.object(ds.requests, "post") as post:
            self.assertIsNone(ds.DeepSeekClient()._generate("p"))
        post.assert_not_called()

    def test_un_dia_nuevo_parte_de_cero(self):
        self.budget.write_text(json.dumps({"date": "2000-01-01", "usd": 99.0, "requests": 9,
                                           "input_tokens": 1, "output_tokens": 1}), encoding="utf-8")
        self.assertEqual(ds.budget_state()["usd"], 0.0)
        self.assertFalse(ds.budget_exceeded())

    def test_tope_cero_lo_desactiva(self):
        self.budget.write_text(json.dumps({"date": ds._today(), "usd": 50.0, "requests": 1,
                                           "input_tokens": 1, "output_tokens": 1}), encoding="utf-8")
        with patch.dict(os.environ, {"DEEPSEEK_DAILY_BUDGET_USD": "0"}):
            self.assertFalse(ds.budget_exceeded())
            with patch.object(ds.requests, "post", return_value=respuesta()):
                self.assertEqual(ds.DeepSeekClient()._generate("p"), "hola")

    def test_archivo_corrupto_se_trata_como_vacio(self):
        self.budget.write_text("{no es json", encoding="utf-8")
        self.assertEqual(ds.budget_state()["usd"], 0.0)

    def test_una_respuesta_sin_usage_cuenta_la_llamada_sin_romper(self):
        r = respuesta()
        r.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        with patch.object(ds.requests, "post", return_value=r):
            self.assertEqual(ds.DeepSeekClient()._generate("p"), "ok")
        self.assertEqual(ds.budget_state()["requests"], 1)

    def test_con_el_tope_agotado_groq_ai_client_pasa_a_groq(self):
        from ai.groq_client import GroqAiClient
        self.budget.write_text(json.dumps({"date": ds._today(), "usd": 1.0, "requests": 1,
                                           "input_tokens": 1, "output_tokens": 1}), encoding="utf-8")
        c = GroqAiClient.__new__(GroqAiClient)
        c.provider_pref, c.groq_ready, c.client = "deepseek", True, MagicMock()
        c.deepseek = ds.DeepSeekClient()
        with patch.object(ds.requests, "post") as post, \
             patch.object(GroqAiClient, "_generate_groq", return_value="de groq"):
            self.assertEqual(c._generate("p"), "de groq")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
