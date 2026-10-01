# -*- coding: utf-8 -*-
"""Guardas del "Super Prompt (IA externa)".

BUG (2026-09-03): el prompt le pedia al LLM un `short_text` de 2-3 palabras,
reservaba espacio en la imagen para el... y en la regla 12 ordenaba
"NO text in the image". La palabra se calculaba, no se devolvia a la GUI y la
miniatura volvia de la IA externa con un hueco vacio. Ademas todo estaba clavado
en 16:9, asi que para un Short pedia una imagen apaisada.

    .venv\\Scripts\\python.exe test_thumbnail_superprompt.py

No necesita red: se le enchufa un `_generate` falso al cliente.
"""

import unittest
import json
from types import SimpleNamespace
from unittest.mock import Mock

from ai.claude_client import ClaudeAiClient
from thumbnail_formats import LANDSCAPE_16_9, SHORT_9_16


def cliente_con(respuesta):
    """ClaudeAiClient sin __init__ (no toca red ni API keys)."""
    cli = object.__new__(ClaudeAiClient)
    cli._generate = lambda prompt, **kw: respuesta
    cli._ultimo_prompt = None
    return cli


def cliente_espia():
    """Devuelve (cliente, caja) donde caja['prompt'] guarda lo que se le pidio."""
    caja = {}
    cli = object.__new__(ClaudeAiClient)

    def fake(prompt, **kw):
        caja["prompt"] = prompt
        return RESPUESTA_OK

    cli._generate = fake
    return cli, caja


def art_response(hook="20,000 PEOPLE", scene="photoreal cinematic thumbnail of an immense earthen mound with a tiny human for scale",
                 evidence="", **overrides):
    direction = dict(font_family="editorial_sans", finish="matte_ink", base_color="#F1E6CC",
                     accent_color="#EFC891", background_color="#14222B", number_layout="hero",
                     tracking="optical", evidence_quote=evidence, visual_anchor=scene,
                     reason="Letras claras y tonos calidos relacionados con la luz de la escena.")
    direction.update(overrides)
    return (f"[TEXT]{hook}[ART DIRECTION]{json.dumps(direction)}"
            f"[POSITIVE PROMPT]{scene}[NEGATIVE PROMPT]misspelled words, garbled glyphs, modern clothing")


RESPUESTA_OK = art_response()

# El modelo devuelve esto la mitad de las veces: bloques PEGADOS a la etiqueta.
RESPUESTA_SIN_SALTOS = art_response(scene="photoreal thumbnail of an immense earthen mound")

# El LLM se olvida de meter el hook en el prompt positivo.
RESPUESTA_SIN_HOOK_EN_PROMPT = art_response()


class DevuelveElTexto(unittest.TestCase):

    def test_el_hook_vuelve_a_la_gui(self):
        # Antes se calculaba y se tiraba: la funcion devolvia solo positive y
        # negative, asi que nadie sabia que palabra habia elegido el LLM.
        res = cliente_con(RESPUESTA_OK).generate_thumbnail_super_prompt(
            "Cahokia", thumbnail_format=SHORT_9_16)
        self.assertEqual(res["text"], "20,000 PEOPLE")

    def test_parsea_aunque_no_haya_saltos_de_linea(self):
        """El fallo real: el regex exigia \\n despues de la etiqueta."""
        res = cliente_con(RESPUESTA_SIN_SALTOS).generate_thumbnail_super_prompt(
            "Cahokia", thumbnail_format=SHORT_9_16)
        self.assertEqual(res["text"], "20,000 PEOPLE")
        self.assertIn("photoreal thumbnail", res["positive"])
        self.assertNotIn("[NEGATIVE PROMPT]", res["positive"],
                         "el prompt positivo se trago las otras etiquetas")
        self.assertIn("garbled glyphs", res["negative"])

    def test_el_hook_se_normaliza_a_mayusculas_sin_comillas(self):
        res = cliente_con(art_response(hook='"veinte mil"')
                          ).generate_thumbnail_super_prompt("t", thumbnail_format=SHORT_9_16)
        self.assertEqual(res["text"], "VEINTE MIL")


class RespuestasIncompletas(unittest.TestCase):

    def test_reintenta_el_corte_de_la_captura_sin_disfrazarlo_con_un_negativo(self):
        cli = cliente_con("")
        cli._generate = Mock(side_effect=[
            '[TEXT]HOW[POSITIVE PROMPT]"HOW" rendered in bold condensed wedge-',
            RESPUESTA_OK,
        ])
        res = cli.generate_thumbnail_super_prompt("Naval cannon", thumbnail_format=SHORT_9_16)
        self.assertEqual(res["text"], "20,000 PEOPLE")
        self.assertIn("photoreal cinematic thumbnail", res["combined"])
        self.assertNotIn("wedge-", res["combined"])
        budgets = [c.kwargs["max_tokens"] for c in cli._generate.call_args_list]
        self.assertEqual(len(budgets), 2)
        self.assertGreater(budgets[0], 1400)
        self.assertGreater(budgets[1], budgets[0])

    def test_no_devuelve_un_resultado_copiable_si_ambos_intentos_fallan(self):
        for broken in (
            '[TEXT]CANNON[POSITIVE PROMPT]a cannon at sea',
            '[TEXT]CANNON[POSITIVE PROMPT]a cannon[NEGATIVE PROMPT]',
            '[TEXT]CANNON[POSITIVE PROMPT]bold wedge-[NEGATIVE PROMPT]blur',
            None,
        ):
            with self.subTest(response=broken):
                cli = cliente_con(broken)
                cli._generate = Mock(return_value=broken)
                self.assertIsNone(cli.generate_thumbnail_super_prompt("Naval cannon"))
                self.assertEqual(cli._generate.call_count, 2)

    def test_how_tampoco_se_acepta_si_lo_elige_el_llm(self):
        cli = cliente_con("")
        cli._generate = Mock(side_effect=[
            art_response(hook="HOW?", scene="cannon on a ship"),
            RESPUESTA_OK,
        ])
        self.assertEqual(cli.generate_thumbnail_super_prompt("Naval cannon")["text"], "20,000 PEOPLE")
        self.assertEqual(cli._generate.call_count, 2)

    def test_groq_rechaza_length_aunque_el_texto_tenga_los_tres_bloques(self):
        from ai.groq_client import GroqAiClient
        client = GroqAiClient.__new__(GroqAiClient)
        client.model_cursors = {}
        client._get_models_for_task = lambda task: ["first", "second"]
        create = Mock(side_effect=[
            SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="length", message=SimpleNamespace(content=RESPUESTA_OK))]),
            SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content="complete response"))]),
        ])
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        self.assertEqual(client._generate("prompt", task_type="script_quality"), "complete response")
        self.assertEqual(create.call_count, 2)


class LaIaEscribeElTexto(unittest.TestCase):

    def test_el_hook_queda_citado_en_el_prompt(self):
        res = cliente_con(RESPUESTA_OK).generate_thumbnail_super_prompt(
            "Cahokia", thumbnail_format=SHORT_9_16, render_text=True)
        self.assertIn('"20,000 PEOPLE"', res["positive"])

    def test_si_el_llm_olvida_el_hook_se_agrega_igual(self):
        """Red de seguridad: sin el hook en el prompt, la IA nunca lo escribe."""
        res = cliente_con(RESPUESTA_SIN_HOOK_EN_PROMPT).generate_thumbnail_super_prompt(
            "Cahokia", thumbnail_format=SHORT_9_16, render_text=True)
        self.assertIn('"20,000 PEOPLE"', res["positive"])
        self.assertIn("semibold", res["positive"].lower(),
                      "se agrego el hook pero sin decir como dibujarlo")

    def test_el_prompt_al_llm_pide_dibujar_el_texto(self):
        cli, caja = cliente_espia()
        cli.generate_thumbnail_super_prompt("Cahokia", thumbnail_format=SHORT_9_16,
                                            render_text=True)
        p = caja["prompt"]
        self.assertIn("TEXT RENDERING", p)
        self.assertIn("MUST draw this text", p)
        self.assertNotIn("NO text in the image", p,
                         "seguia prohibiendo el texto que acaba de pedir")


class SinTextoSeDejaElHueco(unittest.TestCase):

    def test_el_prompt_al_llm_prohibe_el_texto(self):
        cli, caja = cliente_espia()
        cli.generate_thumbnail_super_prompt("Cahokia", thumbnail_format=SHORT_9_16,
                                            render_text=False)
        p = caja["prompt"]
        self.assertIn("TEXT RENDERING: none", p)
        self.assertIn("any text, letters", p, "el negativo no prohibe texto")
        self.assertNotIn("MUST draw this text", p)

    def test_no_se_le_pega_el_hook_al_prompt(self):
        res = cliente_con(RESPUESTA_SIN_HOOK_EN_PROMPT).generate_thumbnail_super_prompt(
            "Cahokia", thumbnail_format=SHORT_9_16, render_text=False)
        self.assertNotIn('"20,000 PEOPLE"', res["positive"])
        # pero el hook sigue disponible para superponerlo despues
        self.assertEqual(res["text"], "20,000 PEOPLE")


class UnSoloTextoParaCopiar(unittest.TestCase):
    """El dialogo mostraba dos cuadros con dos botones: se pegaba la mitad."""

    def test_el_combinado_trae_las_dos_partes(self):
        res = cliente_con(RESPUESTA_OK).generate_thumbnail_super_prompt(
            "Cahokia", thumbnail_format=SHORT_9_16)
        combinado = res["combined"]
        self.assertIn("photoreal cinematic thumbnail", combinado)
        self.assertIn("garbled glyphs", combinado)
        self.assertIn("Do NOT include:", combinado)

    def test_el_hook_sobrevive_al_combinar(self):
        # Si al unir se pierde la palabra entre comillas, la IA no la escribe.
        res = cliente_con(RESPUESTA_OK).generate_thumbnail_super_prompt(
            "Cahokia", thumbnail_format=SHORT_9_16, render_text=True)
        self.assertIn('"20,000 PEOPLE"', res["combined"])

    def test_sin_negativo_no_agrega_la_linea(self):
        from ai.claude_client import build_copyable_prompt
        self.assertEqual(build_copyable_prompt("un prompt", ""), "un prompt")
        self.assertEqual(build_copyable_prompt("un prompt", "   "), "un prompt")

    def test_normaliza_los_saltos_del_llm(self):
        # El LLM devuelve el positivo partido en varias lineas; pegado asi en
        # algunas herramientas se corta en el primer salto.
        from ai.claude_client import build_copyable_prompt
        salida = build_copyable_prompt("linea uno\nlinea dos\n\nlinea tres", "malo")
        self.assertIn("linea uno linea dos linea tres", salida)
        self.assertEqual(salida.count("\n\n"), 1, "solo el separador del negativo")


class TitularEnInglesSinTildes(unittest.TestCase):
    """BUG (2026-09-03): se pidio "6 PIRAMIDES" y la IA dibujo "6 PIRAMIDAS".

    Los generadores de imagen se equivocan con los acentos. Ademas el canal es
    en ingles y el titular salia en el idioma del combo de la GUI.
    """

    def test_las_tildes_se_quitan_del_hook(self):
        from ai.claude_client import _ascii_hook
        self.assertEqual(_ascii_hook("6 Pirámides"), "6 PIRAMIDES")
        self.assertEqual(_ascii_hook('"Año Cero"'), "ANO CERO")
        self.assertEqual(_ascii_hook("  50   toneladas  "), "50 TONELADAS")

    def test_el_hook_parseado_queda_en_ascii(self):
        res = cliente_con(art_response(hook='6 PIRÁMIDES')
                          ).generate_thumbnail_super_prompt("Caral", thumbnail_format=SHORT_9_16)
        self.assertEqual(res["text"], "6 PIRAMIDES")
        self.assertTrue(res["text"].isascii())

    def test_se_le_pide_al_llm_ingles_y_ascii(self):
        cli, caja = cliente_espia()
        cli.generate_thumbnail_super_prompt("Caral", thumbnail_format=SHORT_9_16)
        p = caja["prompt"]
        self.assertIn("ALWAYS IN ENGLISH", p)
        self.assertIn("no accents", p)

    def test_las_directivas_tambien_lo_exigen(self):
        for fmt in (SHORT_9_16, LANDSCAPE_16_9):
            d = " ".join(fmt.text_render_directives("X"))
            self.assertIn("ENGLISH", d)
            self.assertIn("no accents", d)


class TipografiaConImpactoMedido(unittest.TestCase):
    """Historia: la primera version salio con Impact, contorno grueso y 80% del ancho; se paso
    al extremo minimo (6% de alto, peso medio, espaciado amplio, sombra suave) y en la miniatura
    del caballo mongol (2026-09-23) el generador dejo el texto en 2.6% de alto, peso regular:
    mas chico que las 31 miniaturas con texto de los shorts de historia mas vistos. Ahora sale
    del plan medido (thumbnail_typography): negrita condensada, 7-8% para rotulos, la cifra mas
    grande. El acabado es ahora de cartel cinematografico, sin borde grueso ni sombra dura."""

    def test_negrita_condensada_pero_no_impact(self):
        d = " ".join(SHORT_9_16.text_render_directives("100 KILOMETERS"))
        self.assertIn("NOT Impact", d)
        self.assertIn("bold condensed", d)
        self.assertIn("NOT a thin or light weight", d)
        self.assertNotIn("generous letter spacing --", d)
        self.assertNotIn("small and restrained", d)

    def test_acabado_cinematografico_sin_borde_de_pegatina(self):
        d = " ".join(SHORT_9_16.text_render_directives("100 KILOMETERS"))
        self.assertIn("no thick outline", d)
        self.assertIn("no hard offset drop shadow", d)
        self.assertIn("no bevel, no extruded 3D", d)
        self.assertIn("optical kerning", d)

    def test_la_cifra_va_sola_y_mas_grande(self):
        d = " ".join(SHORT_9_16.text_render_directives("100 KILOMETERS"))
        self.assertIn('line 1 "100" -- cap height 11.0%', d)
        self.assertIn('line 2 "KILOMETERS" -- cap height 8.0%', d)

    def test_nunca_llega_al_borde(self):
        import re
        d = " ".join(SHORT_9_16.text_render_directives("THE MONGOL HORSE ARMY"))
        ancho = int(re.search(r"spans about (\d+)% of the frame width", d).group(1))
        self.assertLessEqual(ancho, 86)

    def test_el_texto_no_entra_en_la_zona_recortada(self):
        # En el resultado real arranco al 5%, dentro del 7.8% que recorta la
        # grilla: se le comia el borde superior a las letras.
        d = " ".join(SHORT_9_16.text_render_directives("X"))
        self.assertIn("nothing above 11%", d)
        self.assertGreater(0.11, SHORT_9_16.ui_reserved_top,
                           "el piso del texto tiene que estar por debajo del recorte")

    def test_sin_texto_concreto_pasa_la_formula(self):
        d = " ".join(SHORT_9_16.text_render_directives())
        self.assertIn("if the text starts with a number, put the number ALONE", d)
        self.assertIn("{short_text}", d)


class NoEsElRetratoGenericoDeIa(unittest.TestCase):
    """BUG (2026-09-03): toda miniatura salia igual -- una persona centrada,
    de frente, mirando a camara. No era culpa del LLM: las reglas lo PEDIAN
    ("face occupying 40-55% of image width", "direct eye contact with viewer",
    "readable emotion on the central figure").
    """

    def test_ya_no_se_pide_cara_ni_contacto_visual(self):
        for fmt in (SHORT_9_16, LANDSCAPE_16_9):
            reglas = " ".join(fmt.composition_rules).lower()
            self.assertNotIn("direct eye contact with viewer", reglas, fmt.key)
            self.assertNotIn("readable emotion on the central figure", reglas, fmt.key)
            self.assertNotIn("face or focal action occupying", reglas, fmt.key)

    def test_el_sujeto_es_la_cosa_historica(self):
        for fmt in (SHORT_9_16, LANDSCAPE_16_9):
            reglas = " ".join(fmt.composition_rules)
            self.assertIn("HISTORICAL THING ITSELF", reglas, fmt.key)
            self.assertIn("a human face is NOT the default subject", reglas, fmt.key)

    def test_la_persona_solo_da_escala(self):
        for fmt in (SHORT_9_16, LANDSCAPE_16_9):
            reglas = " ".join(fmt.composition_rules).lower()
            self.assertIn("gives scale", reglas.replace("exists only to give scale", "gives scale"))
            self.assertIn("never facing the camera", reglas, fmt.key)
            self.assertIn("never posed", reglas, fmt.key)

    def test_se_prohibe_explicitamente_el_cliche(self):
        for fmt in (SHORT_9_16, LANDSCAPE_16_9):
            reglas = " ".join(fmt.composition_rules).lower()
            self.assertIn("no person centred and staring at the camera", reglas)
            self.assertIn("no studio-lit model pose", reglas)

    def test_el_prompt_ofrece_tipos_de_plano(self):
        cli, caja = cliente_espia()
        cli.generate_thumbnail_super_prompt("Caral", thumbnail_format=SHORT_9_16)
        p = caja["prompt"]
        self.assertIn("shot_type", p)
        for tipo in ("scale", "detail", "aerial", "aftermath", "moment"):
            self.assertIn(tipo, p)

    def test_la_emocion_se_expresa_con_la_escena_no_con_la_cara(self):
        cli, caja = cliente_espia()
        cli.generate_thumbnail_super_prompt("Caral", thumbnail_format=SHORT_9_16)
        p = caja["prompt"]
        self.assertIn("express it through the SCENE, not through a face", p)
        self.assertNotIn("widened eyes, open mouth", p)

    def test_el_negativo_incluye_el_retrato_posado(self):
        cli, caja = cliente_espia()
        cli.generate_thumbnail_super_prompt("Caral", thumbnail_format=SHORT_9_16)
        p = caja["prompt"]
        self.assertIn("centered person facing camera", p)
        self.assertIn("posed portrait", p)


class ConsciencaDelFormato(unittest.TestCase):

    def _prompt_para(self, fmt):
        cli, caja = cliente_espia()
        cli.generate_thumbnail_super_prompt("Cahokia", thumbnail_format=fmt)
        return caja["prompt"]

    def test_un_short_pide_vertical_y_no_apaisado(self):
        p = self._prompt_para(SHORT_9_16)
        self.assertIn("9:16", p)
        self.assertIn("1080x1920", p)
        self.assertNotIn("1920x1080", p)
        self.assertNotIn("LEFT third", p, "regla de 16:9 en un prompt vertical")

    def test_el_apaisado_sigue_pidiendo_16_9(self):
        p = self._prompt_para(LANDSCAPE_16_9)
        self.assertIn("16:9", p)
        self.assertIn("LEFT third", p)

    def test_sin_formato_no_cambia_el_comportamiento_historico(self):
        cli, caja = cliente_espia()
        cli.generate_thumbnail_super_prompt("Cahokia")
        self.assertIn("16:9", caja["prompt"])


class DirectivasDeTipografia(unittest.TestCase):

    def test_el_vertical_protege_la_franja_que_tapa_youtube(self):
        # La banda util medida en la grilla real es 7.8% - 71.3%: arriba manda
        # el recorte 2:3, abajo el titulo que YouTube superpone en movil.
        d = " ".join(SHORT_9_16.text_render_directives("X"))
        self.assertIn("no text below 71%", d)
        self.assertIn("nothing above 11%", d)

    def test_el_apaisado_manda_el_texto_al_tercio_derecho(self):
        d = " ".join(LANDSCAPE_16_9.text_render_directives("X"))
        self.assertIn("RIGHT third", d)

    def test_siempre_pide_la_palabra_exacta_y_ninguna_otra(self):
        for fmt in (SHORT_9_16, LANDSCAPE_16_9):
            d = " ".join(fmt.text_render_directives("50 TONS"))
            self.assertIn('"50 TONS"', d)
            self.assertIn("no other words", d)
            self.assertIn("ALL CAPS", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
