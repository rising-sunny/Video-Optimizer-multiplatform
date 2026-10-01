# -*- coding: utf-8 -*-
"""Guardas del arranque del video (video_opening).

2026-09-23: cada short arrancaba con una placa quieta de 0.7 s ('FEEDING' en Hannibal), un
'ding' y SIN voz (la narracion se corria 0.7 s). Los 20 shorts de historia mas vistos del mes:
18/20 con sonido antes de 0.3 s, 3/20 quietos en el primer medio segundo, primer corte ~1.8 s,
9/12 con texto en el primer cuadro. Ahora: sin placa, voz en 0.0 s, acercamiento desde el
cuadro 0, primer plano >= 1.8 s y el texto de gancho arriba, encima de la escena 1.

    .venv\\Scripts\\python.exe test_video_opening.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import video_opening as vo

HANNIBAL = ("How did Hannibal sustain 50,000 troops and war elephants across the frozen Alps without modern "
            "supply lines? He relied on 30,000 oxen, each carrying up to 250 kilograms of grain.")
BIBLE_NEW = {"hook_overlay": {"enabled": True, "duration_seconds": 1.8}, "cover_frame": {"enabled": False}}
BIBLE_OLD = {"hook_overlay": {"enabled": False}, "cover_frame": {"enabled": True, "duration_seconds": 0.7}}


def _segs():
    return [{"start": 0.0, "end": 1.2, "text": "How did Hannibal sustain 50,000 troops", "visual_prompt": "A general on a horse"},
            {"start": 1.2, "end": 4.0, "text": "He relied on 30,000 oxen", "visual_prompt": "Oxen in the snow"}]


class ElTextoDeGancho(unittest.TestCase):

    def test_la_cifra_de_lo_que_se_esta_diciendo(self):
        self.assertEqual(vo.pick_hook_text(HANNIBAL)[0], "50,000 TROOPS")

    def test_con_ritmo(self):
        self.assertEqual(vo.pick_hook_text("Mongol riders covered 100 kilometers a day. They never stopped.")[0],
                         "100 KM A DAY")

    def test_sin_cifra_usa_el_texto_del_llm_solo_si_el_guion_lo_respalda(self):
        guion = "The kaiten was a manned torpedo. Pilots volunteered knowing there was no way back."
        self.assertEqual(vo.pick_hook_text(guion, llm_text="MANNED TORPEDO")[0], "MANNED TORPEDO")
        self.assertEqual(vo.pick_hook_text(guion, llm_text="VANISHED")[0], "", "la palabra de placa vieja no esta en el guion")


class LaDecision(unittest.TestCase):

    def test_hay_cinco_entradas_cinematograficas(self):
        self.assertEqual(len(vo.OPENING_STYLE_CHOICES), 5)
        self.assertEqual(vo.OPENING_STYLE_CHOICES[0], vo.OPENING_STYLE)
        self.assertEqual(
            set(vo.OPENING_STYLE_CHOICES),
            {vo.OPENING_STYLE, vo.MAP_ZOOM_STYLE, vo.ARTIFACT_REVEAL_STYLE,
             vo.BEFORE_AFTER_STYLE, vo.OUTCOME_TEASER_STYLE},
        )

    def test_cada_entrada_modifica_el_primer_prompt_y_guarda_su_receta(self):
        for style in vo.OPENING_STYLE_CHOICES:
            segs, op = vo.apply_opening(
                _segs(), script=HANNIBAL, bible=BIBLE_NEW,
                opening_style_id=style, log=lambda m: None,
            )
            spec = vo.opening_style_spec(style)
            self.assertEqual(op["style"], style)
            self.assertEqual(op["motion"], spec["motion"])
            self.assertIn(spec["prompt"], segs[0]["visual_prompt"])
            self.assertTrue(segs[0]["visual_prompt"].endswith(vo.NO_TEXT_HINT))
            self.assertIn(spec["followup_prompt"], segs[1]["visual_prompt"])
            self.assertTrue(segs[1]["visual_prompt"].endswith(vo.NO_TEXT_HINT))
            self.assertEqual(segs[0]["hook_overlay"]["style"], style)

    def test_un_estilo_desconocido_vuelve_al_cold_open(self):
        self.assertEqual(vo.normalize_opening_style("inventado"), vo.OPENING_STYLE)

    def test_las_cinco_recetas_tienen_aperturas_narrativas_distintas(self):
        blocks = [vo.opening_script_instructions(style, language="es")
                  for style in vo.OPENING_STYLE_CHOICES]
        self.assertEqual(len(set(blocks)), 5)
        for style, block in zip(vo.OPENING_STYLE_CHOICES, blocks):
            self.assertIn(style, block)
            self.assertIn(vo.opening_style_spec(style)["narrative"], block)
            self.assertIn("Narration language: Spanish", block)
            self.assertIn("factual and supported", block)

    def test_el_prompt_json_estructura_guion_y_dos_primeros_visuales(self):
        from storyboard_generator import StoryboardGenerator
        generator = StoryboardGenerator(log_callback=lambda m: None)
        for style in vo.OPENING_STYLE_CHOICES:
            prompt = generator.generate_manual_prompt_text(
                "Caral", "Historia", 60, language="es", video_format="9:16",
                platform="youtube_short", opening_style=style,
            )
            spec = vo.opening_style_spec(style)
            self.assertIn(f"SELECTED VIDEO OPENING: {spec['label']} ({style})", prompt)
            self.assertIn(f"Scene 1 visual_prompt: {spec['prompt']}", prompt)
            self.assertIn(f"Scene 2 visual_prompt: {spec['followup_prompt']}", prompt)

    def test_por_defecto_no_hay_placa_y_la_escena_1_arranca_en_0(self):
        segs, op = vo.apply_opening(_segs(), script=HANNIBAL, bible=BIBLE_NEW, log=lambda m: None)
        self.assertEqual(len(segs), 2, "no se inserta ningun segmento de placa")
        self.assertEqual(segs[0]["start"], 0.0, "la voz y la escena 1 arrancan en 0.0 s")
        self.assertFalse(any(s.get("cover_frame") for s in segs))
        self.assertEqual(segs[0]["hook_overlay"]["text"], "50,000 TROOPS")
        self.assertEqual(segs[0]["hook_overlay"]["duration"], 1.8)
        self.assertEqual(op["style"], vo.OPENING_STYLE)
        self.assertIn(vo.TOP_CLEAR_HINT, segs[0]["visual_prompt"], "la imagen deja arriba lugar para el texto")

    def test_la_placa_vieja_solo_si_se_apaga_el_gancho(self):
        with patch("cover_frame_generator.select_cover_text", return_value="FEEDING"):
            segs, op = vo.apply_opening(_segs(), script=HANNIBAL, bible=BIBLE_OLD, log=lambda m: None)
        self.assertTrue(segs[0]["cover_frame"])
        self.assertEqual(segs[1]["start"], 0.7)
        self.assertEqual(op["style"], vo.LEGACY_STYLE)

    def test_el_bible_real_trae_el_arranque_nuevo(self):
        import json
        with open("daily_shorts/channel_strategy_profile.json", encoding="utf-8") as fh:
            b = json.load(fh)
        self.assertTrue(b["hook_overlay"]["enabled"])
        self.assertFalse(b["cover_frame"]["enabled"])
        self.assertTrue(vo.get_opening_config(b)["enabled"])

    def test_estilo_de_proyectos_viejos_y_nuevos(self):
        self.assertEqual(vo.opening_style({"opening": {"style": vo.OPENING_STYLE}}), vo.OPENING_STYLE)
        self.assertEqual(vo.opening_style({"segments": [{"cover_frame": True}]}), vo.LEGACY_STYLE)
        self.assertEqual(vo.opening_style({"segments": [{"start": 0}]}), vo.PLAIN_STYLE)


class ElGanchoADibujar(unittest.TestCase):

    def test_manda_lo_editado_en_el_timeline(self):
        sb = {"opening": {"style": vo.OPENING_STYLE, "hook": {"enabled": True, "text": "50,000 TROOPS"}},
              "segments": [{"hook_overlay": {"enabled": True, "text": "30,000 oxen", "duration": 2.2}}]}
        self.assertEqual(vo.get_hook_overlay(sb), {
            "text": "30,000 OXEN", "duration": 2.2, "style": vo.OPENING_STYLE,
        })

    def test_apagado_en_el_timeline_no_se_dibuja(self):
        sb = {"opening": {"style": vo.OPENING_STYLE, "hook": {"enabled": True, "text": "50,000 TROOPS"}},
              "segments": [{"hook_overlay": {"enabled": False, "text": "50,000 TROOPS"}}]}
        self.assertIsNone(vo.get_hook_overlay(sb))

    def test_si_el_segmento_se_reconstruyo_queda_el_del_storyboard(self):
        sb = {"opening": {"style": vo.OPENING_STYLE, "hook": {"enabled": True, "text": "50,000 TROOPS", "duration": 1.8}},
              "segments": [{"start": 0}]}
        self.assertEqual(vo.get_hook_overlay(sb)["text"], "50,000 TROOPS")

    def test_un_proyecto_viejo_con_placa_no_suma_gancho(self):
        self.assertIsNone(vo.get_hook_overlay({"segments": [{"cover_frame": True, "hook_overlay": {"text": "X"}}]}))


class PrimerPlanoYMovimiento(unittest.TestCase):

    def test_el_primer_plano_llega_a_1_8_s(self):
        clips = [{"duration": 1.2, "timestamp_start": 0.0}, {"duration": 3.0, "timestamp_start": 1.2}]
        moved = vo.enforce_min_first_shot(clips)
        self.assertEqual(moved, 0.6)
        self.assertEqual((clips[0]["duration"], clips[1]["duration"]), (1.8, 2.4))
        self.assertEqual(clips[1]["timestamp_start"], 1.8)

    def test_el_segundo_no_baja_de_0_8_s(self):
        clips = [{"duration": 0.9}, {"duration": 1.2}]
        vo.enforce_min_first_shot(clips)
        self.assertEqual(clips[1]["duration"], 0.8)
        self.assertAlmostEqual(clips[0]["duration"] + clips[1]["duration"], 2.1)

    def test_no_toca_placas_ni_cadenas(self):
        self.assertEqual(vo.enforce_min_first_shot([{"duration": 0.7, "is_cover": True}, {"duration": 3}]), 0.0)
        self.assertEqual(vo.enforce_min_first_shot([{"duration": 1.0}, {"duration": 3, "_vsplit_chain": ["a"]}]), 0.0)
        self.assertEqual(vo.enforce_min_first_shot([{"duration": 2.5}, {"duration": 3}]), 0.0)

    def test_acercamiento_con_salida_rapida(self):
        f = vo.push_in_filter(90, 1080, 1920, 0.12)
        self.assertIn("z='1+0.1200*(1-(1-(on/89))*(1-(on/89)))'", f)
        self.assertIn("d=90:s=1080x1920", f)

    def test_cada_entrada_tiene_un_movimiento_ffmpeg_distinto(self):
        filters = {
            style: vo.opening_motion_filter(90, 1080, 1920, style)
            for style in vo.OPENING_STYLE_CHOICES
        }
        self.assertEqual(len(set(filters.values())), 5)
        self.assertTrue(all(value.startswith("zoompan=") for value in filters.values()))
        self.assertIn("iw-iw/zoom", filters[vo.BEFORE_AFTER_STYLE])


class ElEventoASS(unittest.TestCase):
    HOOK = {"text": "50,000 TROOPS", "duration": 1.8}

    def test_tamanos_colores_y_posicion_del_plan(self):
        style, dlg = vo.hook_ass_lines(self.HOOK, 1080, 1920)
        self.assertIn(vo._ass_color(vo.HOOK_GOLD), dlg)
        self.assertIn(vo._ass_color(vo.HOOK_IVORY), dlg)
        self.assertIn("\\an8\\move(540,", dlg, "arriba, centrado, movimiento sutil")
        self.assertIn("\\fad(0,250)", dlg)
        titles = [line for line in dlg.splitlines() if line.startswith("Dialogue: 10,")]
        self.assertEqual(len(titles), 2)
        self.assertTrue(all("0:00:00.00,0:00:01.80,Hook," in line for line in titles))
        self.assertTrue(all("\\bord0\\shad0" in line for line in titles))
        self.assertNotIn("Arial Narrow", style)
        self.assertIn(vo._hook_font()[0], style)

    def test_el_titulo_cabe_en_el_ancho_con_espaciado_real(self):
        family, font, cap, line_height = vo._hook_font()
        if font is None:
            self.skipTest("sin fuente medible")
        for width, height in ((1080, 1920), (1920, 1080), (720, 1280)):
            for text in ("VICTORY", "50,000 TROOPS", "100 KM A DAY", "EXTRAORDINARY"):
                plan = vo.hook_plan({"text": text}, width, height)
                for ln in plan["lines"]:
                    span = font.getlength(ln["text"]) * ln["font_size"] / line_height
                    span += ln["spacing"] * (len(ln["text"]) - 1)
                    self.assertLessEqual(span, width * vo.HOOK_USABLE_WIDTH + 1)

    def test_todas_las_capas_terminan_con_el_gancho_y_no_hay_placa_solida(self):
        _, dlg = vo.hook_ass_lines({"text": "VICTORY", "duration": 0.5}, 1080, 1920)
        self.assertTrue(all(
            ",0:00:00.00,0:00:00.50,Hook," in line for line in dlg.splitlines()))
        scrim = [line for line in dlg.splitlines() if line.startswith("Dialogue: 8,")]
        self.assertTrue(all("\\clip(" in line and "\\alpha&H" in line for line in scrim))
        self.assertIn("\\fad(0,150)", dlg)

    def test_se_agrega_al_ass_de_subtitulos_una_sola_vez(self):
        base = ("[Script Info]\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name\n"
                "Style: Default,Arial,80\n\n[Events]\nFormat: Layer\nDialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,hola\n")
        out = vo.append_hook_to_ass(base, self.HOOK, 1080, 1920)
        lines = out.splitlines()
        self.assertEqual(lines[lines.index("Style: Default,Arial,80") + 1][:11], "Style: Hook")
        self.assertTrue(lines[-1].startswith("Dialogue: 10,"))
        self.assertEqual(vo.append_hook_to_ass(out, self.HOOK, 1080, 1920), out)

    def test_al_reensamblar_actualiza_un_ass_con_el_estilo_viejo(self):
        narration = "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,How did Nelson"
        old = ("[V4+ Styles]\nStyle: Default,Arial,80\nStyle: Hook,Arial Narrow,200\n"
               "[Events]\n" + narration + "\n"
               "Dialogue: 10,0:00:00.00,0:00:01.80,Hook,,0,0,0,,OLD TITLE\n")
        out = vo.append_hook_to_ass(old, {"text": "VICTORY", "duration": 1.8}, 1080, 1920)
        self.assertIn(narration, out)
        self.assertNotIn("Arial Narrow", out)
        self.assertNotIn("OLD TITLE", out)
        self.assertEqual(out.count("Style: Hook,"), 1)
        self.assertEqual(vo.append_hook_to_ass(out, {"text": "VICTORY", "duration": 1.8}, 1080, 1920), out)

    @unittest.skipUnless(shutil.which("ffmpeg"), "sin ffmpeg")
    def test_render_real_cifra_editorial_sin_contorno_grueso(self):
        import numpy as np
        from PIL import Image
        work = Path(tempfile.mkdtemp(prefix="hooktest_"))
        try:
            (work / "h.ass").write_text(vo.standalone_hook_ass({"text": "100 KILOMETERS", "duration": 1.0},
                                                               1080, 1920), encoding="utf-8")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=0.5",
                            "-vf", "subtitles=h.ass", "-frames:v", "1", "o.png"], cwd=str(work), check=True, timeout=60)
            a = np.asarray(Image.open(work / "o.png").convert("RGB")).astype(int)
            fill = (np.abs(a[:, :, 0] - 0xCD) < 12) & (np.abs(a[:, :, 1] - 0xB5) < 12) & (np.abs(a[:, :, 2] - 0x8A) < 12)
            fill[int(1920 * 0.28):] = False  # excluir el filete dorado bajo el titulo
            ys = np.where(fill.any(axis=1))[0]
            cap_pct = (ys.max() - ys.min() + 1) / 1920 * 100
            target = vo.hook_plan({"text": "100 KILOMETERS"}, 1080, 1920)["lines"][0]["cap_pct"]
            self.assertAlmostEqual(cap_pct, target, delta=0.6)
            self.assertLess(ys.min() / 1920, 0.20, "arriba, en la zona del texto")
        finally:
            shutil.rmtree(work, ignore_errors=True)


class ElTimeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_la_escena_1_muestra_y_guarda_el_gancho(self):
        from timeline_segment_editor import SegmentEditor
        ed = SegmentEditor()
        guardados = []
        ed.saved.connect(guardados.append)
        seg = dict(_segs()[0], hook_overlay={"enabled": True, "text": "50,000 TROOPS", "duration": 1.8,
                                             "source": "cifra"}, assigned_filename="segment_001")
        ed.load_segment(seg)
        self.assertFalse(ed.hook_group.isHidden())
        self.assertEqual(ed.hook_text_edit.text(), "50,000 TROOPS")
        ed.hook_text_edit.setText("30,000 oxen")
        ed.hook_duration_spin.setValue(2.2)
        ed.save_changes()
        h = guardados[-1]["hook_overlay"]
        self.assertEqual((h["text"], h["duration"], h["enabled"], h["source"]), ("30,000 OXEN", 2.2, True, "cifra"))

    def test_otras_escenas_no_lo_muestran(self):
        from timeline_segment_editor import SegmentEditor
        ed = SegmentEditor()
        ed.load_segment(_segs()[1])
        self.assertTrue(ed.hook_group.isHidden())


class LaMedicion(unittest.TestCase):

    def test_el_informe_compara_los_arranques(self):
        from channel import performance_feedback as pf
        by = {"cover_card": {"n": 20, "median_engaged_pct": 55.0, "takeoff_rate": 0.3},
              "hook_overlay_v1": {"n": 9, "median_engaged_pct": 62.0, "takeoff_rate": 0.44}}
        txt = pf.compare_openings(by)
        self.assertIn("el gancho retiene mas (+7.0 puntos)", txt)
        by["hook_overlay_v1"]["n"] = 3
        self.assertIn("todavia pocos videos", pf.compare_openings(by))
        self.assertIsNone(pf.compare_openings({"cover_card": by["cover_card"]}))

    def test_cada_video_lleva_su_arranque(self):
        from channel import performance_feedback as pf
        rows = pf.enrich_rows([{"video_id": "v1", "title": "Hannibal", "views": 400, "engaged_views": 250}],
                              [{"folder": "p", "topic": "Hannibal", "youtube_video_id": "v1",
                                "opening": vo.OPENING_STYLE, "format_archetype": "", "category": ""}], "youtube")
        self.assertEqual(rows[0]["opening"], vo.OPENING_STYLE)


class Cableado(unittest.TestCase):

    def _src(self, name):
        with open(name, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def test_el_storyboard_usa_el_arranque_nuevo_en_todos_los_caminos(self):
        s = self._src("storyboard_generator.py")
        self.assertEqual(s.count("apply_opening("), 3)
        self.assertNotIn('"cover_frame": True,', s, "la placa solo la inserta video_opening (modo viejo)")
        self.assertIn('"opening": opening_data,', s)

    def test_el_ensamblado_dibuja_el_gancho_y_arma_el_primer_plano(self):
        s = self._src("auto_video_generator_v2.py")
        self.assertEqual(s.count("self._add_hook_to_ass(ass_path, storyboard_data, res)"), 2)
        self.assertGreaterEqual(s.count("self._burn_hook_only("), 3)
        self.assertIn("_vo.enforce_min_first_shot(", s)
        self.assertIn("_vo.is_modern_opening(", s)
        self.assertIn("opening_motion_filter", s)
        self.assertIn("if clip_data.get('opening_push_in'):", s)

    def test_la_gui_guarda_y_envia_la_entrada_elegida(self):
        ui = self._src("auto_video_integration_pyqt6.py")
        projects = self._src("studio_project_manager.py")
        handler = self._src("studio_storyboard_handlers.py")
        self.assertIn("self.opening_style_combo = QComboBox()", ui)
        self.assertIn("OpeningStylePreview", ui)
        self.assertIn("'opening_style': self.studio_tab.get_selected_opening_style()", projects)
        self.assertIn("opening_style=opening_style", handler)

    def test_timeline_y_checklist(self):
        self.assertIn("self.hook_label", self._src("timeline_segment_widget.py"))
        self.assertIn('"opening_hook_present"', self._src("publish/production_checklist.py"))


class LosProyectosViejos(unittest.TestCase):
    """Con la placa apagada en el Bible, un proyecto viejo que la trae se re-renderiza igual:
    generate_cover_frame cortaba por `enabled` y lo mandaba a un gradiente oscuro."""

    def test_la_placa_de_un_proyecto_viejo_sigue_usando_su_imagen(self):
        from PIL import Image
        import cover_frame_generator as cfg_gen
        tmp = tempfile.mkdtemp(prefix="oldcover_")
        try:
            proj = os.path.join(tmp, "proj")
            os.makedirs(os.path.join(proj, "project_media"))
            Image.new("RGB", (400, 700), (120, 40, 30)).save(os.path.join(proj, "project_media", "seg1.png"))
            out = os.path.join(tmp, "out")
            os.makedirs(out)
            with patch("channel.channel_strategy.get_cover_frame_config", return_value={"enabled": False}):
                res = cfg_gen.generate_cover_frame(
                    topic="x", category="", storyboard={"segments": [{"image_path": "project_media/seg1.png"}]},
                    output_dir=out, cover_text_override="TEST", log_callback=lambda m: None, media_base_dir=proj)
            self.assertIsNotNone(res, "la placa del proyecto viejo no puede desaparecer")
            self.assertTrue(os.path.exists(res["image_path"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
