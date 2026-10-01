# -*- coding: utf-8 -*-
"""Tests de script_fact_check: verificacion de hechos del guion antes de la voz.

Regresion: el short de Trafalgar (2026-09-23) salio publicado diciendo que el
Victory mato a Villeneuve (lo capturaron; el que murio fue Nelson) y con una
"advertencia de Collingwood" inventada. Sin red: Wikipedia, jueces y reescritor
son funciones falsas inyectadas.
"""

import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import script_fact_check as sfc

ROOT = Path(__file__).resolve().parent.parent

TOPIC = "How Nelson Won Trafalgar Against a Bigger Fleet"
TRAFALGAR = [
    "How did Admiral Nelson break a numerically superior fleet using unconventional tactics on October 21 1805?",
    "At 12:45 PM, Nelson ordered his ships to sail perpendicular, forming a daring double‑column that smashed the Franco‑Spanish line.",
    "Within forty minutes, the British flagship Victory fired the fatal shot that killed Admiral Villeneuve, sealing the British triumph.",
    "Nelson ignored Admiral Collingwood’s warning, choosing to engage despite rough seas, a gamble that paid off.",
    "Weeks before, Napoleon pressured the combined fleet to break British blockade, forcing them into a risky Atlantic sortie.",
    "The victory ended French naval dominance, secured British control of the seas for a century, and prevented invasion.",
    "Trafalgar’s legacy reshaped global trade routes, inspired naval tactics worldwide, and cemented Nelson as Britain’s immortal hero.",
]

VILLENEUVE_FIX = ("Within forty minutes the enemy line was shattered; Admiral Villeneuve was captured aboard his "
                  "flagship, sealing the British triumph.")
COLLINGWOOD_FIX = "Nelson chose to attack in light winds, leading one column while Collingwood led the other, a gamble that paid off."


def judge_reply(problems, checked_ok=()):
    claims = [{"scene": n, "quote": q, "verdict": "ok"} for n, q in checked_ok]
    claims += problems
    return json.dumps({"claims": claims})


class FakeJudge:
    """Juez falso: marca Villeneuve (falso) y Collingwood (inventado) mientras sigan en el texto."""

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        problems = []
        if "killed Admiral Villeneuve" in prompt:
            problems.append({"scene": 3, "quote": "fired the fatal shot that killed Admiral Villeneuve",
                             "verdict": "false",
                             "correction": "Villeneuve was captured and died in 1806; Nelson was killed.",
                             "source": "Battle of Trafalgar"})
        if "Collingwood's warning" in prompt:
            problems.append({"scene": 4, "quote": "Nelson ignored Admiral Collingwood's warning",
                             "verdict": "unsupported", "correction": "No record of such a warning.",
                             "source": "Battle of Trafalgar"})
        return judge_reply(problems, checked_ok=[(1, "October 21 1805")]), [
            {"title": "wikipedia.org", "uri": "https://en.wikipedia.org/wiki/Battle_of_Trafalgar"}]


def fake_rewriter(prompt):
    scenes = []
    if "Scene 3" in prompt.split("SCENES TO FIX:")[-1]:
        scenes.append({"scene": 3, "narration": VILLENEUVE_FIX})
    if "Scene 4" in prompt.split("SCENES TO FIX:")[-1]:
        scenes.append({"scene": 4, "narration": COLLINGWOOD_FIX})
    return json.dumps({"scenes": scenes})


def no_http(url, params):
    raise AssertionError("no deberia pedir nada a la red")


def fake_wiki(pages):
    """http_get falso: search devuelve titulos segun palabras clave, extracts el texto."""
    calls = []

    def http_get(url, params):
        calls.append(dict(params))
        if params.get("list") == "search":
            q = params["srsearch"].lower()
            hits = [t for t, (keys, _) in pages.items() if any(k in q for k in keys)]
            return {"query": {"search": [{"title": t} for t in hits[: int(params.get("srlimit", 1))]]}}
        title = params["titles"]
        return {"query": {"pages": {"1": {"title": title, "extract": pages.get(title, ((), ""))[1]}}}}

    http_get.calls = calls
    return http_get


BATTLE_TEXT = (
    "The Battle of Trafalgar was a naval engagement that took place on 21 October 1805 between the Royal Navy "
    "and the combined fleets of the French and Spanish navies during the War of the Third Coalition.\n"
    "== Battle ==\n"
    "Villeneuve's flagship Bucentaure was dismasted and Villeneuve was captured; he was taken to England and, "
    "after his release, died at Rennes in April 1806.\n"
    "Nelson was shot by a marksman aboard Redoutable and died later that afternoon aboard Victory, "
    "after being told the battle was won.\n"
    "The harbour of Gibraltar and the grain trade of the region were discussed at length in later reports, "
    "with long tables of tonnage and customs duties that say nothing about the battle itself.\n"
)


def storyboard(texts=TRAFALGAR, report=None):
    sb = {"topic": TOPIC, "language": "en", "script": " ".join(texts),
          "segments": [{"segment_id": i, "narration_text": t, "text": t} for i, t in enumerate(texts)]}
    if report is not None:
        sb["fact_check"] = report
    return sb


class Base(unittest.TestCase):
    def setUp(self):
        sfc._UNAVAILABLE.clear()
        self._env = mock.patch.dict(os.environ, {"SCRIPT_FACT_CHECK": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()


class LaFirmaYElTexto(Base):
    def test_signature_ignores_segmentation_spacing_and_dashes(self):
        a = sfc.script_signature(["Villeneuve was captured.", "Nelson   died."])
        b = sfc.script_signature(["Villeneuve was captured. Nelson died."])
        c = sfc.script_signature(["Villeneuve was captured.‑ Nelson died."])
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertNotEqual(a, sfc.script_signature(["Villeneuve was killed. Nelson died."]))

    def test_storyboard_texts_prefers_segments_then_script(self):
        self.assertEqual(sfc.storyboard_texts(storyboard())[2], sfc._norm_space(TRAFALGAR[2]))
        self.assertEqual(sfc.storyboard_texts({"script": "Solo guion."}), ["Solo guion."])
        self.assertEqual(sfc.storyboard_texts({}), [])

    def test_scene_text_reads_llm_and_storyboard_keys(self):
        self.assertEqual(sfc.scene_text({"narration": " a  b "}), "a b")
        self.assertEqual(sfc.scene_text({"narration_text": "x"}), "x")
        self.assertEqual(sfc.scene_text({"text": "y"}), "y")
        self.assertEqual(sfc.scene_text("z"), "z")


class LaEvidencia(Base):
    def test_entities_skip_months_demonyms_and_titles(self):
        ents = sfc.key_entities(TRAFALGAR, TOPIC, limit=6)
        low = [e.lower() for e in ents]
        self.assertIn("villeneuve", low)
        self.assertIn("collingwood", low)
        for bad in ("british", "october", "pm nelson", "franco-spanish", "admiral villeneuve"):
            self.assertNotIn(bad, low)

    def test_topic_names_are_the_proper_nouns_of_the_title(self):
        # "Won", "Fleet" van con mayuscula en el titulo pero no son nombres propios.
        self.assertEqual(sfc.topic_names(TOPIC, TRAFALGAR), ["Nelson", "Trafalgar"])
        self.assertEqual(sfc.topic_queries(TOPIC, TRAFALGAR)[0], "Nelson Trafalgar")

    def test_person_searches_are_anchored_to_the_topic(self):
        # "Villeneuve" suelto trae al piloto de F1.
        http = fake_wiki({"Battle of Trafalgar": (("trafalgar",), BATTLE_TEXT)})
        sfc.gather_documents(TOPIC, TRAFALGAR, "en", http_get=http, log=lambda m: None)
        searches = [c["srsearch"] for c in http.calls if c.get("list") == "search"]
        self.assertIn("Nelson Trafalgar", searches)
        self.assertTrue(any(s.startswith("Villeneuve ") and "Trafalgar" in s for s in searches), searches)
        self.assertNotIn("Villeneuve", searches)

    def test_passages_keep_what_the_script_talks_about(self):
        text = sfc.select_passages([("Battle of Trafalgar", BATTLE_TEXT)], TRAFALGAR, max_chars=600)
        self.assertIn("Villeneuve was captured", text)
        self.assertNotIn("customs duties", text)
        self.assertTrue(text.startswith("[Wikipedia: Battle of Trafalgar]"))

    def test_research_context_is_part_of_the_evidence(self):
        docs = sfc.gather_documents(TOPIC, TRAFALGAR, "en", research_context=["Villeneuve surrendered Bucentaure."],
                                    http_get=fake_wiki({}), log=lambda m: None)
        self.assertEqual(docs["documents"][-1][0], "investigacion del pipeline")

    def test_wikipedia_down_is_not_fatal(self):
        def down(url, params):
            raise RuntimeError("HTTP 429")
        docs = sfc.gather_documents(TOPIC, TRAFALGAR, "en", http_get=down, log=lambda m: None)
        self.assertEqual(docs["documents"], [])


class ElJuez(Base):
    def test_claims_format_keeps_only_problems_and_counts_all(self):
        raw = judge_reply([{"scene": 3, "quote": "killed Admiral Villeneuve", "verdict": "false",
                            "correction": "captured"}], checked_ok=[(1, "October 21 1805"), (2, "double")])
        findings, checked = sfc.parse_findings(raw, TRAFALGAR)
        self.assertEqual(checked, 3)
        self.assertEqual([(f["scene"], f["verdict"]) for f in findings], [(3, "false")])

    def test_legacy_problems_format_still_reads(self):
        raw = json.dumps({"claims_checked": 9, "problems": [{"scene": 4, "quote": "Collingwood's warning",
                                                            "verdict": "unsupported"}]})
        findings, checked = sfc.parse_findings(raw, TRAFALGAR)
        self.assertEqual((checked, findings[0]["scene"]), (9, 4))

    def test_quote_wins_over_a_wrong_scene_number(self):
        raw = judge_reply([{"scene": 6, "quote": "the fatal shot that killed Admiral Villeneuve", "verdict": "false"}])
        findings, _ = sfc.parse_findings(raw, TRAFALGAR)
        self.assertEqual(findings[0]["scene"], 3)

    def test_scene_numbers_are_relative_to_the_chunk(self):
        # En un guion largo el tramo 2 empieza en la escena 101: el juez responde 102.
        raw = judge_reply([{"scene": 102, "quote": "zzz no esta", "verdict": "false"}])
        findings, _ = sfc.parse_findings(raw, ["a", "b", "c"], first_scene=101)
        self.assertEqual(findings[0]["scene"], 2)

    def test_unreadable_reply_is_none(self):
        self.assertIsNone(sfc.parse_findings("lo siento, no puedo", TRAFALGAR))
        self.assertIsNone(sfc.parse_findings('{"claims": "x"}', TRAFALGAR))

    def test_prompt_asks_for_every_claim_and_the_kinds_of_errors(self):
        p = sfc.build_verify_prompt(TRAFALGAR, TOPIC, "EVIDENCE")
        for must in ("who died, was killed, captured", "invented", "including the correct ones",
                     "Google Search", "EVIDENCE", "Scene 3:"):
            self.assertIn(must, p)
        self.assertIn("your own knowledge", sfc.build_verify_prompt(TRAFALGAR, TOPIC, "", grounded=False))
        self.assertIn("Check ONLY scene(s) 3, 4", sfc.build_verify_prompt(TRAFALGAR, TOPIC, "", focus=[4, 3]))

    def test_falls_back_to_next_judge_and_cools_down_the_dead_one(self):
        calls = []

        def dead(prompt):
            calls.append("dead")
            raise RuntimeError("Gemini HTTP 429: quota")

        judge = FakeJudge()
        judges = [("dead", dead, True), ("ok", judge, False)]
        ev = lambda chunk: {"text": "", "sources": []}
        texts = sfc.scene_texts(TRAFALGAR)
        r1 = sfc.verify_texts(texts, TOPIC, evidence_fn=ev, judges=judges, log=lambda m: None)
        r2 = sfc.verify_texts(texts, TOPIC, evidence_fn=ev, judges=judges, log=lambda m: None)
        self.assertEqual(r1["judge"], "ok")
        self.assertEqual(calls, ["dead"])        # la segunda vez ni se intenta
        self.assertEqual({f["scene"] for f in r2["findings"]}, {3, 4})

    def test_no_judge_answering_means_unchecked(self):
        bad = lambda p: ("no json", [])
        r = sfc.verify_texts(TRAFALGAR, TOPIC, evidence_fn=lambda c: {"text": ""},
                             judges=[("bad", bad, False)], log=lambda m: None)
        self.assertIsNone(r["judge"])

    def test_focus_ignores_problems_outside_the_rewritten_scenes(self):
        r = sfc.verify_texts(sfc.scene_texts(TRAFALGAR), TOPIC, evidence_fn=lambda c: {"text": ""},
                             judges=[("j", FakeJudge(), False)], log=lambda m: None, focus=[4])
        self.assertEqual([f["scene"] for f in r["findings"]], [4])

    def test_long_scripts_are_checked_in_chunks_with_global_numbers(self):
        texts = ["filler words here " * 30] * 40 + [TRAFALGAR[2]]
        judge = FakeJudge()
        r = sfc.verify_texts(texts, TOPIC, evidence_fn=lambda c: {"text": ""},
                             judges=[("j", judge, False)], log=lambda m: None)
        self.assertGreater(len(judge.prompts), 1)
        self.assertEqual([f["scene"] for f in r["findings"]], [41])


class LaReparacion(Base):
    def test_repair_guard(self):
        old = TRAFALGAR[2]
        self.assertEqual(sfc.accept_repair(old, "")[0], False)
        self.assertEqual(sfc.accept_repair(old, old)[0], False)
        self.assertEqual(sfc.accept_repair(old, "Villeneuve was captured.")[0], False)   # demasiado corta
        self.assertEqual(sfc.accept_repair(old, VILLENEUVE_FIX)[0], True)

    def test_short_scenes_get_absolute_slack(self):
        # Cannae (2026-09-25): "reparacion descartada (largo 25 vs 17 palabras)" tres veces y la
        # subida quedo frenada por "At noon". La voz se genera despues: 8 palabras mas no rompen nada.
        old = "At noon, Hannibal's cavalry smashed the Roman rear, while his infantry held the center, sealing the trap."
        new = ("Hannibal's cavalry swept around and smashed into the Roman rear, while his deliberately weak "
               "center gave way and drew the legions deep into the trap.")
        self.assertEqual((sfc._words(old), sfc._words(new)), (17, 25))
        self.assertEqual(sfc.accept_repair(old, new), (True, ""))
        self.assertFalse(sfc.accept_repair(old, " ".join(["word"] * 40))[0])
        f = [{"scene": 1, "quote": "At noon", "verdict": "unsupported", "correction": "time unknown"}]
        self.assertIn("(17 words; write 10-27)", sfc.build_repair_prompt([old], f, "Cannae"))

    def test_repair_prompt_narrates_instead_of_explaining(self):
        f = [{"scene": 3, "quote": "killed Admiral Villeneuve", "verdict": "false", "correction": "captured"}]
        p = sfc.build_repair_prompt(TRAFALGAR, f, TOPIC)
        self.assertIn("Never mention the error", p)
        self.assertIn("Scene 3 (", p)
        self.assertNotIn("SECOND ATTEMPT", p)
        self.assertIn("SECOND ATTEMPT", sfc.build_repair_prompt(TRAFALGAR, f, TOPIC, conservative=True))
        # el ejemplo del prompt no puede ser de un tema real que despues se copie tal cual
        self.assertNotIn("musket ball struck Nelson", p)

    def test_parse_repairs(self):
        self.assertEqual(sfc.parse_repairs('```json\n{"scenes": [{"scene": "3", "narration": " a  b "}]}\n```'),
                         {3: "a b"})
        self.assertEqual(sfc.parse_repairs("nada"), {})


class ElCasoTrafalgar(Base):
    """El guion que salio publicado tiene que salir corregido antes de la voz."""

    def run_check(self, scenes=None, rewriter=fake_rewriter, judge=None, **kw):
        judge = judge or FakeJudge()
        scenes = scenes if scenes is not None else [{"narration": t, "visual_prompt": f"v{i}"}
                                                    for i, t in enumerate(TRAFALGAR)]
        out, report = sfc.fact_check_scenes(scenes, TOPIC, language="en", generate_fn=rewriter,
                                            judges=[("fake", judge, True)], http_get=fake_wiki({}),
                                            log=lambda m: None, **kw)
        return out, report, judge

    def test_false_and_invented_claims_are_rewritten_and_reverified(self):
        out, report, judge = self.run_check()
        self.assertEqual(report["status"], "corrected")
        self.assertEqual(out[2]["narration"], VILLENEUVE_FIX)
        self.assertEqual(out[3]["narration"], COLLINGWOOD_FIX)
        self.assertEqual(out[0]["narration"], sfc._norm_space(TRAFALGAR[0]))   # lo demas no se toca
        self.assertEqual(out[2]["visual_prompt"], "v2")
        self.assertEqual({c["scene"] for c in report["corrections"]}, {3, 4})
        self.assertEqual(report["remaining"], [])
        self.assertEqual(report["signature"], sfc.script_signature([s["narration"] for s in out]))
        self.assertIn("Check ONLY scene(s) 3, 4", judge.prompts[-1])      # re-verificacion enfocada
        self.assertIn("https://en.wikipedia.org/wiki/Battle_of_Trafalgar", report["sources"])

    def test_storyboard_segments_keep_both_text_keys_in_sync(self):
        out, report, _ = self.run_check(scenes=storyboard()["segments"])
        self.assertEqual(out[2]["narration_text"], VILLENEUVE_FIX)
        self.assertEqual(out[2]["text"], VILLENEUVE_FIX)
        self.assertNotIn("narration", out[2])

    def test_rejected_repair_leaves_it_blocked(self):
        short = lambda p: json.dumps({"scenes": [{"scene": 3, "narration": "Villeneuve lived."},
                                                 {"scene": 4, "narration": "Collingwood."}]})
        out, report, _ = self.run_check(rewriter=short)
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual({f["scene"] for f in report["remaining"]}, {3, 4})
        self.assertIn("killed Admiral Villeneuve", out[2]["narration"])

    def test_later_rounds_rewrite_conservatively(self):
        prompts = []

        def stubborn(prompt):
            # cada ronda cambia una palabra pero sigue diciendo que mataron a Villeneuve
            prompts.append(prompt)
            word = ["deadly", "final", "lethal"][len(prompts) - 1]
            return json.dumps({"scenes": [{"scene": 3, "narration": TRAFALGAR[2].replace("fatal", word)}]})

        out, report, _ = self.run_check(rewriter=stubborn)
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(len(prompts), sfc.MAX_REPAIR_ROUNDS)
        self.assertNotIn("SECOND ATTEMPT", prompts[0])
        self.assertIn("SECOND ATTEMPT", prompts[1])

    def test_misleading_only_does_not_block(self):
        def judge(prompt):
            return judge_reply([{"scene": 6, "quote": "prevented invasion", "verdict": "misleading",
                                 "correction": "Napoleon had abandoned the invasion in August 1805."}]), []
        out, report, _ = self.run_check(judge=judge, rewriter=lambda p: "{}")
        self.assertEqual(report["status"], "verified_with_notes")

    def test_clean_script_is_verified_without_rewriting(self):
        def judge(prompt):
            return judge_reply([], checked_ok=[(1, "October 21 1805")]), []

        def rewriter(prompt):
            raise AssertionError("no hay nada que reescribir")
        out, report, _ = self.run_check(judge=judge, rewriter=rewriter)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["claims_checked"], 1)

    def test_no_judge_is_unchecked_and_disabled_is_disabled(self):
        _, report = sfc.fact_check_scenes(TRAFALGAR, TOPIC, judges=[], http_get=no_http, log=lambda m: None)
        self.assertEqual(report["status"], "unchecked")
        with mock.patch.dict(os.environ, {"SCRIPT_FACT_CHECK": "0"}):
            _, report = sfc.fact_check_scenes(TRAFALGAR, TOPIC, judges=[("x", FakeJudge(), True)],
                                              http_get=no_http, log=lambda m: None)
        self.assertEqual(report["status"], "disabled")

    def test_verify_only_does_not_rewrite(self):
        out, report, _ = self.run_check(repair=False, rewriter=lambda p: 1 / 0)
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(report["corrections"], [])
        self.assertEqual({f["scene"] for f in report["remaining"]}, {3, 4})


class LaSubida(Base):
    def report_for(self, texts, status="verified", remaining=()):
        return {"status": status, "signature": sfc.script_signature(texts), "remaining": list(remaining),
                "found": list(remaining), "judge": "fake", "claims_checked": 5}

    def test_current_verified_report_passes_without_rechecking(self):
        sb = storyboard(report=self.report_for(sfc.storyboard_texts(storyboard())))
        ok, _, msg = sfc.upload_gate(sb, verify_fn=lambda s: self.fail("no deberia re-verificar"))
        self.assertTrue(ok)
        self.assertIn("[OK]", msg)

    def test_edited_narration_is_checked_again(self):
        sb = storyboard(report=self.report_for(["otro texto viejo"]))
        seen = []
        bad = {"scene": 3, "quote": "killed Admiral Villeneuve", "verdict": "false", "correction": "captured"}

        def verify(s):
            seen.append(True)
            return {"status": "needs_review", "remaining": [bad], "found": [bad],
                    "signature": sfc.script_signature(sfc.storyboard_texts(s))}
        ok, _, msg = sfc.upload_gate(sb, verify_fn=verify)
        self.assertEqual(seen, [True])
        self.assertFalse(ok)
        self.assertIn("killed Admiral Villeneuve", msg)
        self.assertIn("FALSO", msg)
        self.assertEqual(sb["fact_check"]["status"], "needs_review")     # queda guardado

    def test_old_project_without_report_is_verified_and_blocked(self):
        # El proyecto de Trafalgar tal cual quedo publicado.
        sb = storyboard()

        def verify(s):
            return sfc.verify_storyboard(s, judges=[("fake", FakeJudge(), True)], http_get=fake_wiki({}),
                                         log=lambda m: None)
        ok, report, msg = sfc.upload_gate(sb, verify_fn=verify)
        self.assertFalse(ok)
        self.assertIn("Villeneuve", msg)
        self.assertIn("Collingwood", msg)

    def test_no_judge_does_not_block_but_says_so(self):
        ok, _, msg = sfc.upload_gate(storyboard(), verify_fn=lambda s: {"status": "unchecked"})
        self.assertTrue(ok)
        self.assertIn("revisalo a mano", msg)

    def test_needs_review_report_blocks_even_if_current(self):
        texts = sfc.storyboard_texts(storyboard())
        bad = {"scene": 4, "quote": "Collingwood's warning", "verdict": "unsupported", "correction": ""}
        sb = storyboard(report=self.report_for(texts, "needs_review", [bad]))
        ok, _, msg = sfc.upload_gate(sb, verify_fn=lambda s: self.fail("no deberia re-verificar"))
        self.assertFalse(ok)
        self.assertIn("INVENTADO", msg)


class ElCableado(unittest.TestCase):
    """Que el verificador este enchufado donde tiene que estar."""

    def _src(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_every_path_checks_facts_before_the_voice(self):
        src = self._src("storyboard_generator.py")
        body = src[src.index("    def process_manual_json("):src.index("    def generate_storyboard_data(")]
        self.assertLess(body.index("self._fact_check_scenes("), body.index("self.tts.generate_narration("))
        self.assertIn('"fact_check": fact_report', body)
        classic = src[src.index("    def generate_storyboard_data("):]
        self.assertLess(classic.index("self._fact_check_scenes(_frases"),
                        classic.index("audio_path = self.tts.generate_narration("))
        self.assertLess(classic.index("self._fact_check_scenes(\n                        _frases_retry"),
                        classic.index("retry_audio_path = self.tts.generate_narration("))
        self.assertEqual(src.count("topic=topic,\n            research_context=research_context,"), 2)

    def test_length_retry_no_longer_asks_for_invented_specifics(self):
        src = self._src("storyboard_generator.py")
        self.assertNotIn("hora exacta, magnitud, velocidad, víctimas", src)
        self.assertNotIn("Sobrevivientes/testigos con nombre y testimonio", src)
        self.assertIn("una frase", src)

    def test_studio_publish_is_gated(self):
        src = self._src("auto_video_integration_pyqt6.py")
        body = src[src.index("    def publish_video_to_platforms("):]
        self.assertLess(body.index("self._fact_check_gate(storyboard)"), body.index("youtube_meta = None"))
        self.assertIn("_sync_timeline_editor_to_storyboard()", body[:body.index("self._fact_check_gate(")])

    def test_daily_pipeline_upload_is_gated(self):
        src = self._src("daily_short_pipeline.py")
        body = src[src.index("def run_pipeline("):]
        self.assertLess(body.index("upload_gate(storyboard"), body.index("upload_result = upload_to_youtube("))

    def test_checklist_reports_facts(self):
        from production_checklist import run_pre_publish_checklist
        sb = storyboard()
        sb["fact_check"] = {"status": "corrected", "signature": sfc.script_signature(sfc.storyboard_texts(sb)),
                            "corrections": [{}], "judge": "fake"}
        checks = {c["check"]: c for c in run_pre_publish_checklist(sb)}
        self.assertTrue(checks["facts_verified"]["passed"])
        sb["segments"][2]["narration_text"] = sb["segments"][2]["text"] = "texto editado despues"
        checks = {c["check"]: c for c in run_pre_publish_checklist(sb)}
        self.assertFalse(checks["facts_verified"]["passed"])


class ElTitulo(Base):
    """Cannae (2026-09-25): el guion corregido decia que 86.000 pelearon; el titulo seguia '86,000 Dead'."""

    NARR = ["About 86,000 Romans and allies fought at Cannae in 216 BC against Hannibal's army.",
            "Hannibal's cavalry swept around the flanks while his center gave way and drew the legions in."]
    TITLE = "86,000 Dead: Hannibal's Cannae Masterstroke"

    def judge(self, prompt):
        problems = []
        if "86,000 Dead" in prompt:
            problems.append({"scene": 3, "quote": "86,000 Dead", "verdict": "false",
                             "correction": "About 86,000 fought; 50,000-70,000 were killed."})
        return judge_reply(problems), []

    def test_title_is_checked_labelled_and_corrected(self):
        prompts = []

        def rewriter(prompt):
            prompts.append(prompt)
            return json.dumps({"scenes": [{"scene": 3, "narration": "50,000 Romans Fell: Hannibal's Cannae Masterstroke"}]})

        out, report = sfc.fact_check_scenes([{"narration": t} for t in self.NARR], "Cannae", title=self.TITLE,
                                            generate_fn=rewriter, judges=[("j", self.judge, True)],
                                            http_get=fake_wiki({}), log=lambda m: None)
        self.assertEqual(report["title"], "50,000 Romans Fell: Hannibal's Cannae Masterstroke")
        self.assertEqual(report["title_original"], self.TITLE)
        self.assertEqual(report["status"], "corrected")
        self.assertEqual(len(out), 2)                                   # el titulo no es una escena
        self.assertEqual(report["signature"], sfc.script_signature(self.NARR))
        self.assertIn("Scene 3 (VIDEO TITLE", prompts[0])
        self.assertIn("at most 70", prompts[0])
        lines = "\n".join(sfc.format_report(report))
        self.assertIn("titulo [FALSO]", lines)
        self.assertIn("titulo corregido", lines)

    def test_an_unrepaired_title_does_not_block_the_upload(self):
        long_title = json.dumps({"scenes": [{"scene": 3, "narration": "x" * 120}]})
        _, report = sfc.fact_check_scenes([{"narration": t} for t in self.NARR], "Cannae", title=self.TITLE,
                                          generate_fn=lambda p: long_title, judges=[("j", self.judge, True)],
                                          http_get=fake_wiki({}), log=lambda m: None)
        self.assertEqual(report["title"], self.TITLE)
        self.assertNotEqual(report["status"], "needs_review")
        self.assertEqual(report["remaining"][0]["scene_label"], "titulo")

    def test_judge_scene_is_kept_when_it_contains_the_quote(self):
        raw = judge_reply([{"scene": 3, "quote": "86,000", "verdict": "false", "correction": "x"}])
        findings, _ = sfc.parse_findings(raw, self.NARR + [self.TITLE])
        self.assertEqual(findings[0]["scene"], 3)                       # no se muda a la escena 1

    def test_storyboard_passes_the_title_and_uses_the_corrected_one(self):
        src = (ROOT / "storyboard_generator.py").read_text(encoding="utf-8")
        body = src[src.index("    def process_manual_json("):src.index("    def generate_storyboard_data(")]
        self.assertIn("title=str(json_data.get('title') or '')", body)
        self.assertIn("json_data['title'] = fact_report[\"title\"]", body)


class FakeCLI:
    """subprocess.run falso para el Claude CLI: registra el comando y responde un JSON."""

    def __init__(self, result="", is_error=False, returncode=0):
        self.calls = []
        self.payload = json.dumps({"type": "result", "is_error": is_error, "result": result})
        self.returncode = returncode

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return mock.Mock(stdout=self.payload, stderr="", returncode=self.returncode)


class ElJuezClaudeCLI(Base):
    """El Claude CLI de la PC como juez (con busqueda web) y como reescritor."""

    def setUp(self):
        super().setUp()
        self._cli = mock.patch.object(sfc, "claude_cli_path", return_value=r"C:\npm\claude.cmd")
        self._cli.start()

    def tearDown(self):
        self._cli.stop()
        super().tearDown()

    def test_headless_call_with_web_tools_prompt_on_stdin_and_clean_env(self):
        cli = FakeCLI(result='{"claims": []}')
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "http://proxy", "CLAUDE_CODE_OAUTH_SCOPES": "x",
                                          "GROQ_API_KEY": "k"}):
            out = sfc.run_claude_cli("PROMPT " * 3000, tools=sfc.CLAUDE_WEB_TOOLS, runner=cli)
        self.assertEqual(out, '{"claims": []}')
        cmd, kw = cli.calls[0]
        for flag in ("-p", "--output-format", "json", "--no-session-persistence", "--strict-mcp-config"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")
        self.assertEqual(cmd[cmd.index("--tools") + 1:cmd.index("--tools") + 3], ["WebSearch", "WebFetch"])
        self.assertIn("--allowedTools", cmd)
        self.assertTrue(kw["input"].startswith("PROMPT"))                  # por stdin, no por argumento
        self.assertFalse(any(len(c) > 1000 for c in cmd))
        self.assertNotIn("ANTHROPIC_BASE_URL", kw["env"])
        self.assertNotIn("CLAUDE_CODE_OAUTH_SCOPES", kw["env"])
        self.assertIn("GROQ_API_KEY", kw["env"])
        self.assertNotEqual(os.path.abspath(kw["cwd"]), str(ROOT))          # sin el CLAUDE.md del proyecto

    def test_low_effort_by_default_and_configurable(self):
        cli = FakeCLI(result="{}")
        sfc.run_claude_cli("x", runner=cli)
        cmd = cli.calls[0][0]
        self.assertEqual(cmd[cmd.index("--effort") + 1], "low")
        with mock.patch.dict(os.environ, {"FACT_CHECK_CLAUDE_EFFORT": "medium"}):
            sfc.run_claude_cli("x", runner=cli)
        cmd = cli.calls[1][0]
        self.assertEqual(cmd[cmd.index("--effort") + 1], "medium")

    def test_a_new_nuance_after_rewriting_does_not_start_another_round(self):
        rounds = []

        def judge(prompt):
            if "Check ONLY" not in prompt:
                return judge_reply([{"scene": 3, "quote": "killed Admiral Villeneuve", "verdict": "false",
                                     "correction": "captured"}]), []
            return judge_reply([{"scene": 3, "quote": "Within forty minutes", "verdict": "misleading",
                                 "correction": "timing is approximate"}]), []

        def rewriter(prompt):
            rounds.append(prompt)
            return json.dumps({"scenes": [{"scene": 3, "narration": VILLENEUVE_FIX}]})

        out, report = sfc.fact_check_scenes([{"narration": t} for t in TRAFALGAR], TOPIC, generate_fn=rewriter,
                                            judges=[("j", judge, True)], http_get=fake_wiki({}),
                                            log=lambda m: None)
        self.assertEqual(len(rounds), 1)
        self.assertEqual(report["status"], "corrected")
        self.assertEqual([f["verdict"] for f in report["remaining"]], ["misleading"])

    def test_rewriting_runs_without_tools(self):
        cli = FakeCLI(result="{}")
        sfc.run_claude_cli("x", runner=cli)
        cmd = cli.calls[0][0]
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertNotIn("--allowedTools", cmd)

    def test_not_logged_in_is_a_clear_error_that_cools_the_judge_down(self):
        cli = FakeCLI(result="Not logged in · Please run /login", is_error=True, returncode=1)
        with self.assertRaises(RuntimeError) as ctx:
            sfc.run_claude_cli("x", runner=cli)
        self.assertIn("/login", str(ctx.exception))
        self.assertTrue(sfc._is_capacity_error(ctx.exception))

    def test_claude_is_the_first_judge_and_searches_only_as_needed(self):
        # 2026-09-25: con Gemini primero, cada verificacion esperaba a que fallaran sus modelos sin cuota.
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g", "GROQ_API_KEY": "k", "FACT_CHECK_CLAUDE": "1",
                                          "FACT_CHECK_GEMINI_MODELS": "m1,m2"}):
            judges = sfc.default_judges()
        self.assertEqual([n for n, _, _ in judges], ["claude-cli+web", "m1+google", "m2+google", "m1+wikipedia",
                                                     "m2+wikipedia", "groq+wikipedia"])
        self.assertEqual(judges[0][2], "as_needed")
        p = sfc.build_verify_prompt(["x"], "t", "EVIDENCE", grounded="as_needed")
        self.assertIn("Run a web search ONLY for a specific claim you cannot settle", p)
        self.assertNotIn("AND web search", p)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": "k", "FACT_CHECK_CLAUDE": "0"}):
            self.assertNotIn("claude-cli+web", [n for n, _, _ in sfc.default_judges()])

    def test_claude_judges_when_gemini_is_out_of_quota(self):
        def gemini(prompt):
            raise RuntimeError("Gemini HTTP 429: quota")

        judge = FakeJudge()
        with mock.patch.object(sfc, "run_claude_cli", side_effect=lambda p, **k: judge(p)[0]) as cli:
            judges = [("m1+google", gemini, True), ("claude-cli+web", sfc.claude_judge, True)]
            r = sfc.verify_texts(sfc.scene_texts(TRAFALGAR), TOPIC, evidence_fn=lambda c: {"text": ""},
                                 judges=judges, log=lambda m: None)
        self.assertEqual(r["judge"], "claude-cli+web")
        self.assertEqual(cli.call_args.kwargs["tools"], sfc.CLAUDE_WEB_TOOLS)
        self.assertEqual({f["scene"] for f in r["findings"]}, {3, 4})

    def test_verify_only_report_lists_each_problem_once(self):
        bad = {"scene": 3, "quote": "killed Admiral Villeneuve", "verdict": "false", "correction": "captured"}
        lines = sfc.format_report({"status": "needs_review", "judge": "claude-cli+web", "found": [bad],
                                   "remaining": [bad], "corrections": []})
        self.assertEqual(sum("killed Admiral Villeneuve" in l for l in lines), 1)

    def test_rewriter_tries_claude_first(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g", "FACT_CHECK_CLAUDE": "1"}), \
                mock.patch.object(sfc, "run_claude_cli", return_value='{"scenes": []}') as cli, \
                mock.patch("gemini_vision.ask_images") as gemini:
            groq = mock.Mock(return_value="groq")
            out = sfc.default_rewriter(fallback=groq, log=lambda m: None)("prompt")
        self.assertEqual(out, '{"scenes": []}')
        gemini.assert_not_called()
        groq.assert_not_called()
        self.assertEqual(cli.call_args.kwargs.get("tools", ()), ())

    def test_rewriter_falls_back_when_claude_is_down(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "FACT_CHECK_CLAUDE": "1"}), \
                mock.patch.object(sfc, "run_claude_cli", side_effect=RuntimeError("Claude CLI: usage limit")):
            groq = mock.Mock(return_value="groq")
            self.assertEqual(sfc.default_rewriter(fallback=groq, log=lambda m: None)("prompt"), "groq")
        self.assertTrue(sfc._cooling("rewrite:claude-cli"))


if __name__ == "__main__":
    unittest.main()
