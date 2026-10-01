# -*- coding: utf-8 -*-
"""Guardas: cada video generado existe UNA vez, en auto_videos/output (Google Drive).

Situacion previa (2026-09-14): el pipeline CLI y los microdocumentales copiaban
el render dentro de la carpeta del proyecto (short_HHMMSS.mp4 / <TEMA>_DOCUMENTARY.mp4)
porque los cuatro uploaders buscaban "el primer *.mp4 de la carpeta". Resultado:
cada video dos veces (434 MB solo en Gunnerside) y, en long_form/, una copia en C:.

    .venv\\Scripts\\python.exe test_output_video_location.py
"""

import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from publish.output_video_locator import find_output_video, newest_video_in, recorded_video_path


def _touch(path: Path, mtime=None):
    path.write_bytes(b"\x00" * 16)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class LaRutaRegistradaManda(unittest.TestCase):

    def test_pipeline_state_apunta_al_render_afuera_de_la_carpeta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "biblioteca").mkdir()
            render = _touch(root / "biblioteca" / "youtube_short_20260914_tema.mp4")
            draft = root / "draft"; draft.mkdir()
            (draft / "pipeline_state.json").write_text(json.dumps({"video_path": str(render)}), encoding="utf-8")
            self.assertEqual(find_output_video(draft), str(render.resolve()))
            self.assertEqual(list(draft.glob("*.mp4")), [], "no hace falta ninguna copia adentro")

    def test_project_json_del_studio_tambien_sirve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render = _touch(root / "render.mp4")
            proj = root / "Tema_20260914.json"; proj.mkdir()
            (proj / "project.json").write_text(
                json.dumps({"generated_video_data": {"video_path": str(render)}}), encoding="utf-8")
            self.assertEqual(find_output_video(proj), str(render.resolve()))

    def test_ruta_relativa_se_resuelve_contra_la_carpeta(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "exports").mkdir()
            _touch(proj / "exports" / "final.mp4")
            (proj / "project.json").write_text(json.dumps({"video_path": "exports/final.mp4"}), encoding="utf-8")
            self.assertEqual(recorded_video_path(proj), str((proj / "exports" / "final.mp4").resolve()))

    def test_ruta_registrada_pero_borrada_no_se_devuelve(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "pipeline_state.json").write_text(json.dumps({"video_path": str(proj / "ya_no_esta.mp4")}), encoding="utf-8")
            self.assertIsNone(recorded_video_path(proj))
            self.assertIsNone(find_output_video(proj))

    def test_json_roto_no_rompe(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "pipeline_state.json").write_text("{esto no es json", encoding="utf-8")
            self.assertIsNone(recorded_video_path(proj))


class CompatibilidadConDraftsViejos(unittest.TestCase):

    def test_sin_registro_toma_el_mp4_de_adentro(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            viejo = _touch(proj / "short_101010.mp4")
            self.assertEqual(find_output_video(proj), str(viejo.resolve()))

    def test_con_varios_toma_el_mas_reciente_no_el_primero(self):
        # Antes: videos[0], o sea el que tocara segun el orden del filesystem.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            ahora = time.time()
            _touch(proj / "a_short_100000.mp4", ahora - 300)
            nuevo = _touch(proj / "z_short_120000.mp4", ahora)
            _touch(proj / "m_short_110000.mp4", ahora - 100)
            self.assertEqual(newest_video_in(proj), str(nuevo.resolve()))

    def test_carpeta_vacia_da_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_output_video(tmp))


class ElPipelineYaNoCopia(unittest.TestCase):
    """assemble_video devuelve el render tal cual y deja la ruta en pipeline_state."""

    def test_assemble_video_no_deja_copia_en_el_draft(self):
        from daily_short_pipeline import assemble_video

        with tempfile.TemporaryDirectory(suffix=".json") as tmp:
            root = Path(tmp)
            (root / "afuera").mkdir()
            render = _touch(root / "afuera" / "youtube_long_20260914_tema.mp4")
            draft = root / "draft"; draft.mkdir()
            generator = Mock()
            generator.assemble_video_from_storyboard.return_value = {"video_path": str(render)}
            with patch("dynamic_subtitle_wrapper.patch_subtitle_generation"):
                devuelto = assemble_video({"_generator": generator, "segments": []}, draft, pregenerate_images=False)
            self.assertEqual(devuelto, str(render))
            self.assertEqual(list(draft.glob("*.mp4")), [], "volvio la copia short_HHMMSS.mp4 dentro del draft")
            state = json.loads((draft / "pipeline_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state.get("video_path"), str(render))
            self.assertEqual(find_output_video(draft), str(render.resolve()))


class LasFuentesNoVuelvenAtras(unittest.TestCase):

    def _src(self, name):
        return io.open(name, encoding="utf-8", errors="replace").read()

    def test_daily_short_pipeline_sin_copia(self):
        self.assertNotIn('f"short_{datetime.now().strftime', self._src("daily_short_pipeline.py"))

    def test_long_form_builder_sin_copia(self):
        self.assertNotIn("_DOCUMENTARY.mp4", self._src("long_form_builder.py"))

    def test_los_cuatro_uploaders_usan_el_localizador(self):
        for name in ("publish/youtube_uploader.py", "publish/facebook_uploader.py", "publish/instagram_uploader.py", "publish/x_video_uploader.py"):
            fuente = self._src(name)
            self.assertIn("find_output_video", fuente, name)
            self.assertNotIn("videos[0]", fuente, name + " volvio a adivinar el primer mp4 de la carpeta")


if __name__ == "__main__":
    unittest.main(verbosity=2)
