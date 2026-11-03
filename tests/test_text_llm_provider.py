"""Proveedor de texto: Groq y/o DeepSeek detras de GroqAiClient (TEXT_LLM_PROVIDER)."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from ai import groq_client as gc
from ai.groq_client import GroqAiClient


def build(pref="auto", groq=None, deepseek=None):
    """Instancia armada a mano: sin red ni claves."""
    c = GroqAiClient.__new__(GroqAiClient)
    c.provider_pref = pref
    c.groq_ready = groq is not None
    c.client = groq or deepseek
    c.deepseek = deepseek
    return c


class ProveedorElegido(unittest.TestCase):
    def test_variable_invalida_cae_a_auto(self):
        for raw, esperado in (("", "auto"), ("basura", "auto"), ("DeepSeek", "deepseek"), (" groq ", "groq")):
            with patch.dict(os.environ, {"TEXT_LLM_PROVIDER": raw}):
                self.assertEqual(gc.text_llm_provider(), esperado)

    def test_orden_segun_preferencia(self):
        g, d = MagicMock(), MagicMock()
        self.assertEqual(build("auto", g, d)._provider_order(), ["groq", "deepseek"])
        self.assertEqual(build("deepseek", g, d)._provider_order(), ["deepseek", "groq"])
        self.assertEqual(build("groq", g, d)._provider_order(), ["groq"])

    def test_solo_los_proveedores_con_clave(self):
        d = MagicMock()
        self.assertEqual(build("auto", None, d)._provider_order(), ["deepseek"])
        self.assertEqual(build("groq", None, d)._provider_order(), [])

    def test_instancia_legacy_sin_groq_ready_usa_client_como_groq(self):
        c = GroqAiClient.__new__(GroqAiClient)
        c.client = MagicMock()
        self.assertEqual(c._provider_order(), ["groq"])


class Generacion(unittest.TestCase):
    def test_deepseek_recibe_el_mismo_system_prompt_que_groq(self):
        d = MagicMock()
        d._generate.return_value = "guion"
        c = build("deepseek", None, d)
        self.assertEqual(c._generate("p", max_tokens=900, task_type="script_quality"), "guion")
        kw = d._generate.call_args.kwargs
        self.assertEqual(kw["system"], gc.system_prompt_for("script_quality"))
        self.assertIn("Never refuse a historical documentary narration", kw["system"])
        self.assertEqual(kw["task_type"], "script_quality")

    def test_json_mode_valida_que_sea_un_objeto(self):
        d = MagicMock()
        d._generate.return_value = '{"ok": true}'
        self.assertEqual(json.loads(build("deepseek", None, d)._generate("p", json_mode=True)), {"ok": True})
        d._generate.return_value = "[1, 2]"
        self.assertIsNone(build("deepseek", None, d)._generate("p", json_mode=True))
        d._generate.return_value = '{"cortado'
        self.assertIsNone(build("deepseek", None, d)._generate("p", json_mode=True))

    def test_auto_usa_deepseek_si_groq_no_responde(self):
        g, d = MagicMock(), MagicMock()
        d._generate.return_value = "de deepseek"
        c = build("auto", g, d)
        with patch.object(GroqAiClient, "_generate_groq", return_value=None) as groq_call:
            self.assertEqual(c._generate("p"), "de deepseek")
        groq_call.assert_called_once()

    def test_deepseek_primero_y_groq_de_respaldo(self):
        g, d = MagicMock(), MagicMock()
        d._generate.return_value = None
        c = build("deepseek", g, d)
        with patch.object(GroqAiClient, "_generate_groq", return_value="de groq"):
            self.assertEqual(c._generate("p"), "de groq")

    def test_con_groq_que_responde_no_se_llama_a_deepseek(self):
        g, d = MagicMock(), MagicMock()
        with patch.object(GroqAiClient, "_generate_groq", return_value="de groq"):
            self.assertEqual(build("auto", g, d)._generate("p"), "de groq")
        d._generate.assert_not_called()

    def test_sin_ningun_proveedor_devuelve_none(self):
        c = build("auto")
        c.client = None
        self.assertIsNone(c._generate("p"))


class Inicializacion(unittest.TestCase):
    def _init(self, env):
        with patch.dict(os.environ, env, clear=False), \
             patch.object(gc, "GROQ_LIB_OK", False), \
             patch("ai.deepseek_client.requests"):
            for k in ("GROQ_API_KEY", "DEEPSEEK_API_KEY", "TEXT_LLM_PROVIDER"):
                if k not in env:
                    os.environ.pop(k, None)
            return GroqAiClient()

    def test_solo_deepseek_deja_client_verdadero(self):
        c = self._init({"DEEPSEEK_API_KEY": "sk-test"})
        self.assertTrue(c.client)                 # el resto del codigo hace `if x.client:`
        self.assertEqual(c._provider_order(), ["deepseek"])

    def test_sin_claves_client_queda_vacio(self):
        c = self._init({})
        self.assertFalse(c.client)
        self.assertEqual(c._provider_order(), [])

    def test_groq_forzado_ignora_deepseek(self):
        c = self._init({"DEEPSEEK_API_KEY": "sk-test", "TEXT_LLM_PROVIDER": "groq"})
        self.assertIsNone(c.deepseek)


if __name__ == "__main__":
    unittest.main()
