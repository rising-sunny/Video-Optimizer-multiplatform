import unittest

from ai.claude_client import (
    ClaudeAiClient,
    is_llm_refusal,
    minimum_script_words,
    script_is_too_short,
)
from ai.research_search import (
    _match_is_relevant,
    _relevance_tokens,
    _simplify_query,
    topic_search_queries,
)
from pipeline.storyboard_generator import (
    StoryboardGenerator,
    script_matches_topic,
    topic_needs_localization,
    prefer_in_memory_storyboard,
    storyboard_is_unusable,
    topics_are_same_project,
)


USER_REFUSAL = (
    "I'm sorry, but I can't fulfill that request."
    "Don't forget to subscribe to Stunning Revelations for more fascinating content."
)


class ScriptQualityGuardTests(unittest.TestCase):
    def test_detects_user_refusal_plus_cta(self):
        self.assertTrue(is_llm_refusal(USER_REFUSAL))
        self.assertTrue(is_llm_refusal("I'm sorry, but I can't fulfill that request."))
        self.assertFalse(
            is_llm_refusal(
                "In 2038 BC Shu-Sin ordered a wall called Muriq-Tidnim to keep the Tidnum at bay."
            )
        )

    def test_long_form_rejects_nineteen_words(self):
        self.assertGreaterEqual(minimum_script_words(1800), 200)
        self.assertTrue(script_is_too_short(USER_REFUSAL, 1800))
        self.assertTrue(script_is_too_short("word " * 19, 1800))
        self.assertFalse(script_is_too_short("word " * 1400, 1800))

    def test_does_not_append_cta_to_refusal(self):
        client = ClaudeAiClient.__new__(ClaudeAiClient)
        result = client._maybe_append_cta(
            "I'm sorry, but I can't fulfill that request.",
            language="en",
        )
        self.assertNotIn("Don't forget to subscribe", result)

    def test_appends_cta_to_real_script(self):
        client = ClaudeAiClient.__new__(ClaudeAiClient)
        body = "In 2038 BC Shu-Sin ordered a wall. " * 8
        result = client._maybe_append_cta(body, language="en")
        self.assertIn("Don't forget to subscribe", result)

    def test_topic_queries_prefer_akkadian_name(self):
        queries = topic_search_queries("Muriq-Tidnim (Muro amorrita)")
        self.assertIn("Muriq-Tidnim", queries)
        self.assertIn("Shu-Sin", queries)
        self.assertLess(queries.index("Muriq-Tidnim"), queries.index("Muro amorrita"))
        self.assertEqual(_simplify_query("Muriq-Tidnim (Muro amorrita)"), "Muriq-Tidnim")

    def test_topic_queries_try_the_subject_before_the_colon_and_normalize_typography(self):
        # Cannae (2026-09-25): el titulo con U+2011 y U+202F no encontraba el articulo y el guion
        # se escribio sin investigacion (6.000 cartagineses, los Apeninos, dos consules muertos).
        queries = topic_search_queries("The Battle of Cannae: Hannibal's double‑envelopment in 216 BC")
        self.assertEqual(queries[:3], ["The Battle of Cannae: Hannibal's double-envelopment in 216 BC",
                                       "The Battle of Cannae", "Battle of Cannae"])
        self.assertFalse(any("‑" in q or " " in q for q in queries))
        self.assertIn("Stamford Bridge", topic_search_queries("Stamford Bridge - the last Viking battle"))

    def test_new_topic_detaches_from_previous_project(self):
        from studio.studio_project_manager import StudioProjectManager

        class FakeTab:
            def __init__(self):
                self.current_project_path = r"C:\dev\old\project.json"
                self.last_storyboard_data = {
                    "topic": "La explosión del Krakatoa",
                    "script": "In 1883 Krakatoa exploded.",
                    "segments": [{"text": "In 1883 Krakatoa exploded."}],
                }
                self._storyboard_just_generated = False
                self.timeline_editor_window = None

            def log(self, _msg):
                pass

        tab = FakeTab()
        manager = StudioProjectManager(tab)
        forked = manager.prepare_isolated_project_for_topic("Muriq-Tidnim (Muro amorrita)")
        self.assertTrue(forked)
        self.assertIsNone(tab.current_project_path)
        self.assertTrue(tab._storyboard_just_generated)

        tab.current_project_path = r"C:\dev\muriq\project.json"
        tab.last_storyboard_data = {
            "topic": "Muriq-Tidnim (Muro amorrita)",
            "script": "Shu-Sin built Muriq-Tidnim to hold the Tidnum.",
            "segments": [{"text": "Shu-Sin built Muriq-Tidnim to hold the Tidnum."}],
        }
        self.assertFalse(
            manager.prepare_isolated_project_for_topic("Amorite Wall / Muriq-Tidnim")
        )
        self.assertEqual(tab.current_project_path, r"C:\dev\muriq\project.json")

        tab.last_storyboard_data = {
            "topic": "Muriq-Tidnim (Muro amorrita)",
            "script": USER_REFUSAL,
            "segments": [{"text": "I'm sorry, but I can't fulfill that request."}],
        }
        self.assertTrue(manager.prepare_isolated_project_for_topic("Muriq-Tidnim (Muro amorrita)"))
        self.assertIsNone(tab.current_project_path)
        self.assertIsNone(tab.last_storyboard_data)

    def test_storyboard_rejects_refusal_script(self):
        generator = StoryboardGenerator(log_callback=lambda _: None)
        reason = generator._unusable_script_reason(USER_REFUSAL, 1800)
        self.assertTrue(reason)
        self.assertIn("rechazo", reason.lower())

    def test_topics_same_project_aliases(self):
        self.assertTrue(
            topics_are_same_project(
                "Muriq-Tidnim (Muro amorrita)",
                "Amorite Wall / Muriq-Tidnim, Shu-Sin, Ur III",
            )
        )
        self.assertFalse(
            topics_are_same_project("Muriq-Tidnim (Muro amorrita)", "Isandlwana 1879")
        )
        self.assertFalse(storyboard_is_unusable({"segments": [{"text": "Shu-Sin built a wall."}]}))
        self.assertTrue(
            storyboard_is_unusable(
                {
                    "script": USER_REFUSAL,
                    "segments": [{"text": "I'm sorry,"}, {"text": "but I can't fulfill that request."}],
                }
            )
        )
        self.assertFalse(storyboard_is_unusable({"segments": []}))

    def test_prefers_memory_over_disk_refusal(self):
        memory = {
            "generated_at": 200,
            "script": "In 2038 BC Shu-Sin ordered a wall called Muriq-Tidnim.",
            "segments": [{"text": "In 2038 BC Shu-Sin ordered a wall called Muriq-Tidnim."}] * 80,
        }
        disk = {
            "generated_at": 100,
            "script": USER_REFUSAL,
            "segments": [
                {"text": "I'm sorry,"},
                {"text": "but I can't fulfill that request."},
                {"text": "Don't forget to subscribe to Stunning Revelations for more fascinating content."},
            ],
        }
        self.assertTrue(prefer_in_memory_storyboard(memory, disk))
        self.assertFalse(prefer_in_memory_storyboard(disk, memory))

    def test_process_manual_json_rejects_refusal_scenes(self):
        logs = []
        generator = StoryboardGenerator(log_callback=logs.append)
        result = generator.process_manual_json(
            {
                "title": "Muriq-Tidnim",
                "scenes": [
                    {"narration": "I'm sorry, but I can't fulfill that request."},
                    {"narration": "Don't forget to subscribe to Stunning Revelations for more fascinating content."},
                    {"narration": "I'm sorry, but I can't fulfill that request."},
                ],
            },
            language="en",
        )
        self.assertIsNone(result)
        self.assertTrue(any("rechazo" in str(line).lower() or "I can't" in str(line) for line in logs))


class WikipediaRelevanceGuardTests(unittest.TestCase):
    """Wikipedia SIEMPRE devuelve algo, aunque no tenga nada que ver.

    Caso real (2026-08-26): buscar "El Nucleo del Demonio" en la Wikipedia
    inglesa devuelve "2021 in Latin music". El pipeline lo aceptaba, DuckDuckGo
    venia rate-limited, y el guion entero salio sobre musica latina con el
    titulo "The Devil's Core: Latin Music's 2021 Global Surge". Ningun paso
    fallo: por eso hace falta validar que el articulo hable del tema.
    """

    def test_rejects_the_latin_music_article(self):
        self.assertFalse(_match_is_relevant(
            "El Nucleo del Demonio", "2021 in Latin music",
            "This article lists notable events in Latin music during 2021.",
        ))

    def test_rejects_madagascar_for_paperclip(self):
        self.assertFalse(_match_is_relevant(
            "Operacion Paperclip", "Battle of Madagascar",
            "The Battle of Madagascar was a campaign fought in 1942.",
        ))

    def test_accepts_the_spanish_article(self):
        self.assertTrue(_match_is_relevant(
            "El Nucleo del Demonio", "Nucleo del demonio",
            "El nucleo del demonio fue una esfera de plutonio.",
        ))

    def test_accepts_exact_english_title(self):
        self.assertTrue(_match_is_relevant(
            "Demon core", "Demon core",
            "The demon core was a sphere of plutonium.",
        ))

    def test_acronym_matches_via_summary(self):
        """MH370 no comparte palabras con el titulo, pero el resumen lo nombra."""
        self.assertTrue(_match_is_relevant(
            "MH370", "Malaysia Airlines Flight 370",
            "Malaysia Airlines Flight 370 (MH370) disappeared on 8 March 2014.",
        ))

    def test_accents_and_articles_do_not_matter(self):
        self.assertEqual(
            _relevance_tokens("El Núcleo del Demonio"),
            _relevance_tokens("nucleo demonio"),
        )

    def test_empty_topic_does_not_block(self):
        self.assertTrue(_match_is_relevant("", "Cualquier cosa", ""))


class TopicLocalizationTests(unittest.TestCase):
    """El tema se escribe en espanol y el guion sale en ingles.

    Sin llevar el tema al idioma del guion, la investigacion busca en la
    Wikipedia inglesa una frase en espanol (que devuelve cualquier cosa) y la
    validacion de tema marcaria deriva siempre.
    """

    def test_spanish_topics_need_localization(self):
        for topic in ("El Núcleo del Demonio",
                      "¿Quiénes fueron los Pueblos del Mar?",
                      "la expedición del régimen Nazi al Himalaya",
                      # Sin acentos ni articulos: el detector tiene que leer las
                      # palabras de contenido ("incendio", "guerra", "misterio").
                      "Neron Incendio Roma",
                      "Guerra Ruso-japonesa",
                      "Misterio del Triangulo de las Bermudas"):
            self.assertTrue(topic_needs_localization(topic, "en"), topic)

    def test_english_topics_do_not(self):
        for topic in ("Demon core", "MH370", "Operation Paperclip",
                      "Did Carthage Reach America?", "Hunga Tonga eruption 2022"):
            self.assertFalse(topic_needs_localization(topic, "en"), topic)

    def test_spanish_script_needs_no_localization(self):
        self.assertFalse(topic_needs_localization("El Núcleo del Demonio", "es"))

    def test_empty_topic_is_safe(self):
        self.assertFalse(topic_needs_localization("", "en"))


class ScriptTopicDriftTests(unittest.TestCase):
    """El guion tiene que hablar del tema pedido.

    Caso real: pedido "El Nucleo del Demonio", salio "The Devil's Core: Latin
    Music's 2021 Global Surge" y nada lo detecto hasta ver el video.
    """

    def test_lee_la_narracion_este_donde_este(self):
        """BUG 2026-09-01: 'Nan Madol' se marco como deriva estando bien.

        El LLM devuelve la clave `narration`; el validador leia solo
        `narration_text`/`text`, o sea validaba contra un guion VACIO y el unico
        texto que quedaba era el titulo. Con el titulo solo, cualquier guion
        correcto cuyo titulo no repita el tema salta como error -- y una alarma
        que suena siempre no la mira nadie.
        """
        from pipeline.storyboard_generator import scene_narration_text

        escenas = [
            {"narration": "In 1180 AD, the Saudeleur dynasty began building Nan Madol."},
            {"narration_text": "Workers hauled basalt blocks up to 50 tons."},
            {"text": "By 1628 the dynasty fell."},
            {"narration": "   "},
        ]
        textos = [scene_narration_text(s) for s in escenas]
        self.assertEqual(textos[3], "")
        texto_guion = " ".join(t for t in textos if t)
        self.assertIn("Nan Madol", texto_guion)

        ok, detalle = script_matches_topic(
            "Nan Madol", "The Stone City That Defied the Ocean", texto_guion
        )
        self.assertTrue(ok, "falso positivo: %s" % detalle)

    def test_narracion_vacia_no_se_valida(self):
        # Sin texto, lo unico comparable es el titulo: eso no alcanza para
        # afirmar deriva. Mejor no opinar que dar una alarma falsa.
        self.assertTrue(script_matches_topic("Nan Madol", "", "")[0])

    def test_catches_the_latin_music_drift(self):
        ok, detalle = script_matches_topic(
            "Demon core",
            "The Devil's Core: Latin Music's 2021 Global Surge",
            "In 2021 Latin music surged worldwide, with reggaeton artists breaking records.",
        )
        self.assertFalse(ok)
        self.assertIn("demon", detalle)

    def test_accepts_the_right_script(self):
        ok, _ = script_matches_topic(
            "Demon core", "The Demon Core: 1945's Deadliest Sphere",
            "In 1945 a plutonium sphere at Los Alamos killed two scientists.",
        )
        self.assertTrue(ok)

    def test_hook_titles_that_never_name_the_subject(self):
        """El titulo es un gancho; el cuerpo del guion nombra el tema."""
        ok, _ = script_matches_topic(
            "Operation Paperclip", "1,600 Nazi Scientists Got New Passports",
            "After the war the United States moved 1,600 German scientists "
            "under Operation Paperclip.",
        )
        self.assertTrue(ok)

    def test_long_headline_topics_are_not_flagged(self):
        """Los temas del canal son titulares largos: exigir cobertura marcaba
        como deriva 12 de 139 guiones correctos."""
        ok, _ = script_matches_topic(
            "The Carrington Event: The Day the Sun Almost Ended Civilization",
            "1859: The Sky Caught Fire",
            "In 1859 the sun erupted violently. Richard Carrington witnessed a "
            "huge solar flare that set telegraph lines alight.",
        )
        self.assertTrue(ok)

    def test_partial_entity_name_is_enough(self):
        ok, _ = script_matches_topic(
            "Malaysia Airlines Flight 370", "239 People, 0 Wreckage",
            "Flight 370 vanished from radar on 8 March 2014 with 239 people aboard.",
        )
        self.assertTrue(ok)

    def test_empty_inputs_do_not_block(self):
        self.assertTrue(script_matches_topic("", "t", "s")[0])
        self.assertTrue(script_matches_topic("Demon core", "", "")[0])


class RetentionStructurePromptTests(unittest.TestCase):
    """El prompt tiene que ordenar carga util primero y contexto despues.

    Medido en las curvas de retencion reales del canal (2026-08-27): el hook
    aguanta (1.20 a los 6.5s) y entre el segundo 6 y el 20 se va el 35% de la
    audiencia -- justo donde los guiones ponian el contexto pre-evento. El
    propio prompt lo pedia: "CONTEXTO PRE-EVENTO" era el angulo numero 1 de la
    lista para llegar al minimo de palabras.

    Esto valida que la instruccion siga en el prompt, no que el LLM la cumpla.
    """

    @classmethod
    def setUpClass(cls):
        gen = StoryboardGenerator()
        cls.prompt = gen.generate_manual_prompt_text(
            "Chelyabinsk meteor", "Cosmic Threats", 90,
            language="en", platform="youtube_short", video_format="9:16",
        )

    def test_orders_payload_before_context(self):
        self.assertIn("ESTRUCTURA DE RETENCIÓN", self.prompt)
        self.assertIn("PROHIBIDO en las escenas 1-3", self.prompt)

    def test_pre_event_context_is_marked_as_late(self):
        """El contexto pre-evento no puede volver a quedar como angulo temprano."""
        i = self.prompt.find("CONTEXTO PRE-EVENTO")
        self.assertGreater(i, 0, "desaparecio el angulo de contexto pre-evento")
        # La marca [DESPUES] va inmediatamente antes, en la misma linea.
        inicio_linea = self.prompt.rfind(chr(10), 0, i)
        linea = self.prompt[inicio_linea:i]
        self.assertIn("DESPU", linea,
                      "el contexto pre-evento quedo sin marcar como tardio")

    def test_early_angles_exist(self):
        self.assertIn("[TEMPRANO]", self.prompt)
        temprano = self.prompt.find("[TEMPRANO]")
        despues = self.prompt.find("[DESPU")
        self.assertLess(temprano, despues,
                        "los angulos tempranos tienen que listarse primero")

    def test_long_form_is_not_affected(self):
        """La regla es de Shorts; el long-form puede construir contexto."""
        gen = StoryboardGenerator()
        largo = gen.generate_manual_prompt_text(
            "Chelyabinsk meteor", "Cosmic Threats", 600,
            language="en", platform="youtube", video_format="16:9",
        )
        self.assertNotIn("PROHIBIDO en las escenas 1-3", largo)


if __name__ == "__main__":
    unittest.main()
