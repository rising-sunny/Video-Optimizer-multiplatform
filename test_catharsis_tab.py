"""GUI persistence and composition-preview regressions, without user projects or settings."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton
from PIL import Image

import catharsis_editor as ce
import catharsis_tab as ct
from catharsis_preview import composition_preview
from catharsis_media_input import can_import
from catharsis_timeline import assignment_summary, media_slots, plan_timings, slot_value


class CatarsisGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        self.folder_patch = patch.object(ct, "PROJECTS_DIR", self.root / "projects")
        self.folder_patch.start()
        self.tab = ct.CatharsisTab(settings=self.settings)
        self.tab._autosave_timer.setInterval(30)

    def tearDown(self):
        self.tab.close()
        self.app.processEvents()
        self.folder_patch.stop()
        self.tmp.cleanup()

    def wait_for(self, predicate, seconds=8):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(predicate())

    def data(self):
        return json.loads(self.tab.current_project_path.read_text(encoding="utf-8"))

    def test_debounce_disable_and_reenable_keep_one_project(self):
        self.tab.topic.setText("Mi catarsis")
        self.tab.lines.setPlainText("Una frase\nOtra frase")
        self.wait_for(lambda: self.tab.current_project_path is not None)
        path = self.tab.current_project_path
        self.assertEqual(self.data()["cards"]["lines"], ["Una frase", "Otra frase"])
        self.tab.auto_save_check.setChecked(False)
        self.tab.topic.setText("Otro titulo del mismo proyecto")
        QTest.qWait(70)
        self.assertEqual(self.data()["topic"], "Mi catarsis")
        self.tab.auto_save_check.setChecked(True)
        self.assertEqual(path, self.tab.current_project_path)
        self.assertEqual(self.data()["topic"], "Otro titulo del mismo proyecto")
        self.assertEqual(len(list((self.root / "projects").glob("*.json"))), 1)

    def test_restore_is_read_only_and_resumes_same_file(self):
        self.tab.topic.setText("Recuperar")
        self.tab._cards_done({**ce.DEFAULT_CARDS, "opening": "Mi pregunta",
                              "direction": {"speaker": "Narrador"}})
        path = self.tab.current_project_path
        original = path.read_bytes()
        self.tab.close()
        self.tab = ct.CatharsisTab(settings=self.settings)
        self.wait_for(lambda: self.tab.current_project_path == path)
        self.assertEqual(self.tab.opening.text(), "Mi pregunta")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(self.tab._dirty)
        self.tab.lines.setPlainText("Un cambio")
        self.tab._auto_save()
        self.assertEqual(self.data()["cards"]["direction"]["speaker"], "Narrador")

    def test_switch_saves_old_then_does_not_overwrite_new_on_load(self):
        self.tab.topic.setText("Anterior")
        self.tab._auto_save()
        old = self.tab.current_project_path
        self.tab.lines.setPlainText("Pendiente")
        new = self.root / "other.json"
        payload = json.dumps(ce.normalize_project({"topic": "Siguiente", "media": []}))
        new.write_text(payload, encoding="utf-8")
        self.tab.load_project(new)
        self.assertEqual(json.loads(old.read_text(encoding="utf-8"))["cards"]["lines"], ["Pendiente"])
        self.assertEqual(new.read_text(encoding="utf-8"), payload)
        self.assertFalse(self.tab._autosave_timer.isActive())

    def test_save_failure_keeps_file_and_pending_edits(self):
        self.tab.topic.setText("Original")
        self.tab._auto_save()
        path = self.tab.current_project_path
        original = path.read_bytes()
        self.tab.topic.setText("Cambio")
        with patch.object(ct, "QSaveFile") as save:
            save.return_value.open.return_value = False
            save.return_value.errorString.return_value = "disk unavailable"
            self.assertFalse(self.tab._auto_save())
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(self.tab._dirty)
        self.assertIn("pendientes", self.tab.save_status.text())

    def test_shot_edits_reorder_and_media_properties_are_saved(self):
        image = self.root / "frame.png"
        Image.new("RGB", (120, 200), "orange").save(image)
        self.tab.add_media_files([str(image)], "image")
        self.tab.sequence = [{"kind": "card", "text": "Antes", "seconds": 1, "style": "center"},
                             {"kind": "media", "media": 0, "variant": "base", "seconds": 2}]
        self.tab._refresh_table()
        self.tab.table.item(0, 1).setText("Despues")
        self.tab.table.cellWidget(0, 3).setValue(1.5)
        self.tab.m_zoom.setValue(1.4)
        self.tab.table.selectRow(0)
        self.tab._move_shot(1)
        self.tab._auto_save()
        data = self.data()
        self.assertEqual(data["sequence"][1]["text"], "Despues")
        self.assertEqual(data["sequence"][1]["seconds"], 1.5)
        self.assertEqual(data["media"][0]["zoom"], 1.4)

    def test_close_flushes_pending_changes(self):
        self.tab.topic.setText("Al cerrar")
        self.tab.close()
        self.assertEqual(self.data()["topic"], "Al cerrar")

    def test_preview_worker_displays_latest_text_and_row_thumbnails(self):
        self.tab.auto_save_check.setChecked(False)
        self.tab.sequence = [{"kind": "card", "text": "OLD", "style": "red", "seconds": 1}]
        self.tab._refresh_table()
        self.tab._composition_timer.stop()
        self.tab._start_compositions()
        self.tab.table.item(0, 1).setText("NEW")
        self.wait_for(lambda: self.tab.shot_preview.pixmap() is not None
                      and not self.tab.table.item(0, 6).icon().isNull()
                      and self.tab._preview_worker is None, seconds=15)
        expected = composition_preview(self.tab.project(), self.tab.sequence[0])
        self.assertEqual(self.tab.shot_preview.pixmap().toImage(), ct._pixmap(expected).toImage())
        self.assertIsNotNone(self.tab.card_previews["center"].pixmap())

    def test_overlay_style_and_missing_media_previews(self):
        image = self.root / "frame.png"
        Image.new("RGB", (180, 320), (120, 140, 160)).save(image)
        project = ce.normalize_project({"media": [{"file": str(image)}],
                                        "style": {"grain": False, "grade": False, "bloom": False}})
        spec = {"kind": "overlay", "text": "HELLO", "media": 0, "variant": "color", "seconds": 1}
        overlay = composition_preview(project, spec)
        plain = composition_preview(project, dict(spec, kind="media"))
        self.assertNotEqual(overlay.tobytes(), plain.tobytes())
        red = composition_preview(project, dict(spec, kind="media", variant="red"))
        self.assertNotEqual(plain.tobytes(), red.tobytes())
        image.unlink()
        with self.assertRaises(Exception):
            composition_preview(project, spec)

    def test_embedded_video_plays_seeks_and_marks_later_edits(self):
        self.tab.auto_save_check.setChecked(False)
        clip = self.root / "preview.mp4"
        subprocess.run([ce._ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=blue:size=90x160:rate=15", "-t", "2", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
        self.tab._render_project_signature = json.dumps(self.tab.project(), sort_keys=True)
        self.tab._render_done(str(clip), True)
        self.assertIsNotNone(self.tab._player)
        self.wait_for(lambda: self.tab._player.duration() > 0)
        self.assertEqual(self.tab._player.errorString(), "")
        self.assertFalse(self.tab._preview_video_stale)
        self.assertIs(self.tab.viewer_stack.currentWidget(), self.tab._video_widget)
        self.tab._player.pause()
        self.tab._player.setPosition(800)
        self.wait_for(lambda: abs(self.tab._player.position() - 800) < 100)
        self.tab.opening.setText("Edited after render")
        self.assertTrue(self.tab._preview_video_stale)
        self.tab._show_composition()
        self.assertIs(self.tab.viewer_stack.currentWidget(), self.tab.shot_preview)

    def test_drop_mixed_files_keeps_originals_and_skips_bad_inputs(self):
        image = self.root / "foto con espacios.PNG"
        Image.new("RGB", (40, 60), "orange").save(image)
        video = self.root / "clip.mp4"
        subprocess.run([ce._ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=blue:size=90x160:rate=15", "-t", "0.4", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
        bad = self.root / "broken.jpg"
        bad.write_bytes(b"not an image")
        text = self.root / "document.txt"
        text.write_text("Not a supported medium")
        originals = {path: path.read_bytes() for path in (image, video, bad, text)}
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in originals])
        # File-copy data sometimes also supplies an icon. Import the files, not the icon.
        mime.setImageData(QImage(5, 5, QImage.Format.Format_RGB32))
        actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
        enter = QDragEnterEvent(QPoint(4, 4), actions, mime, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.tab.media_list.viewport(), enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(4, 4), actions, mime, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.tab.media_list.viewport(), drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(drop.dropAction(), Qt.DropAction.CopyAction)
        self.assertEqual([m["type"] for m in self.tab.media], ["image", "video"])
        self.assertGreater(self.tab.media[1]["out"], 0)
        self.assertEqual(self.tab.media_list.count(), 2)
        self.assertIn("broken.jpg", self.tab.log_box.toPlainText())
        self.assertEqual(len(self.data()["media"]), 2)
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data)
        move_only = QDropEvent(QPointF(4, 4), Qt.DropAction.MoveAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.tab.media_list.dropEvent(move_only)
        self.assertFalse(move_only.isAccepted())
        self.assertEqual(len(self.tab.media), 2)

    def test_ctrl_v_image_is_durable_transparent_and_restored(self):
        image = QImage(30, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor(20, 80, 150, 120))
        mime = QMimeData()
        mime.setImageData(image)
        with patch.object(ct.QApplication, "clipboard") as clipboard:
            clipboard.return_value.mimeData.return_value = mime
            QTest.keyClick(self.tab.media_list, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(self.tab.media), 1)
        asset = Path(self.tab.media[0]["file"])
        self.assertTrue(asset.is_relative_to(self.root / "projects"))
        self.assertEqual(QImage(str(asset)).pixelColor(0, 0), image.pixelColor(0, 0))
        project = self.tab.current_project_path
        self.tab.close()
        self.tab = ct.CatharsisTab(settings=self.settings)
        self.wait_for(lambda: self.tab.current_project_path == project)
        self.assertEqual(self.tab.media[0]["file"], str(asset))
        self.assertTrue(asset.is_file())

    def test_context_menu_pastes_beside_manually_saved_project(self):
        project = self.root / "manual.json"
        self.tab._write_project(project)
        mime = QMimeData()
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        mime.setImageData(image)
        def select_paste(menu, position):
            action = menu.actions()[0]
            self.assertTrue(action.isEnabled())
            self.assertIn("Pegar", action.text())
            action.trigger()
        with patch.object(ct.QApplication, "clipboard") as clipboard, patch.object(ct.QMenu, "exec", select_paste):
            clipboard.return_value.mimeData.return_value = mime
            self.tab._media_context_menu(QPoint(5, 5))
        self.assertEqual(Path(self.tab.media[0]["file"]).parent, self.root / "manual_media")
        self.assertEqual(self.tab.current_project_path, project)

    def test_remote_url_is_not_imported_and_raw_image_does_not_force_autosave(self):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/image.png")])
        self.assertFalse(can_import(mime))
        self.tab._import_media_mime(mime)
        self.assertFalse(self.tab.media)
        self.tab.auto_save_check.setChecked(False)
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        mime.setImageData(image)
        self.assertTrue(can_import(mime))
        self.tab._import_media_mime(mime)
        self.assertTrue(Path(self.tab.media[0]["file"]).is_file())
        self.assertIsNone(self.tab.current_project_path)

    def test_clipboard_write_failure_does_not_add_broken_media(self):
        mime = QMimeData()
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        mime.setImageData(image)
        with patch.object(ct, "QSaveFile") as save:
            save.return_value.open.return_value = False
            save.return_value.errorString.return_value = "disk unavailable"
            self.tab._import_media_mime(mime)
        self.assertFalse(self.tab.media)
        self.assertIn("No se pudo pegar", self.tab.log_box.toPlainText())

    def test_planner_works_before_import_and_blocks_incomplete_render(self):
        self.tab.auto_save_check.setChecked(False)
        self.tab.lines.setPlainText("A date\nA decision\nA consequence")
        self.tab.auto_btn.click()
        self.wait_for(lambda: bool(self.tab.sequence) and self.tab.auto_btn.isEnabled())
        summary = assignment_summary(self.tab.sequence, [])
        self.assertGreater(summary["visual"], 0)
        self.assertIn(f"{summary['visual']} requieren", self.tab.total_label.text())
        self.assertIn(f"{len(summary['pending'])} pendientes", self.tab.total_label.text())
        self.assertTrue(all(slot_value(s, sl) is None for s in self.tab.sequence for sl in media_slots(s)))
        with patch.object(ct, "_RenderWorker") as worker:
            self.tab._render(preview=True)
            worker.assert_not_called()
        self.assertIn("Falta asignar material", self.tab.log_box.toPlainText())
        self.assertEqual(self.tab.table.currentRow(), next(iter(summary["pending"])))

    def test_scene_drop_fills_image_and_video_panels_and_saves_exact_durations(self):
        image = self.root / "still.png"
        Image.new("RGB", (40, 60), "orange").save(image)
        video = self.root / "clip.mp4"
        subprocess.run([ce._ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=blue:size=90x160:rate=15", "-t", "0.4", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
        spec = {"kind": "double", "media": None, "media2": None, "seconds": 1.237}
        self.tab.sequence = [{"kind": "card", "text": "BEFORE", "seconds": .5}, spec]
        self.tab._refresh_table()
        before = plan_timings(self.tab.sequence)
        target = self.tab.table.cellWidget(1, 1)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in (image, video)])
        actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
        enter = QDragEnterEvent(QPoint(4, 4), actions, mime, Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(target, enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(4, 4), actions, mime, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(target, drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(drop.dropAction(), Qt.DropAction.CopyAction)
        self.assertEqual((spec["media"], spec["media2"]), (0, 1))
        self.assertEqual([m["type"] for m in self.tab.media], ["image", "video"])
        self.assertEqual(plan_timings(self.tab.sequence), before)
        self.assertEqual(assignment_summary(self.tab.sequence, self.tab.media)["pending"], {})
        self.assertEqual(self.data()["sequence"][1]["seconds"], 1.237)
        self.assertEqual(self.data()["sequence"][1]["media2"], 1)

    def test_scene_clipboard_paste_and_clear_keep_scene_and_timing(self):
        spec = {"kind": "overlay", "media": None, "text": "A DECISION", "seconds": 2.5}
        self.tab.sequence = [spec]
        self.tab._refresh_table()
        mime = QMimeData()
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        mime.setImageData(image)
        target = self.tab.table.cellWidget(0, 1)
        with patch.object(ct.QApplication, "clipboard") as clipboard:
            clipboard.return_value.mimeData.return_value = mime
            QTest.keyClick(target, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(spec["media"], 0)
        self.assertEqual(spec["seconds"], 2.5)
        self.assertEqual(self.data()["sequence"][0]["media"], 0)
        target = self.tab.table.cellWidget(0, 1)
        def clear(menu, position):
            menu.actions()[1].trigger()
        with patch.object(ct.QMenu, "exec", clear):
            self.tab._scene_context_menu(target, QPoint(4, 4), spec, ("media", None))
        self.assertIsNone(spec["media"])
        self.assertEqual(spec["seconds"], 2.5)
        combo = self.tab.table.cellWidget(0, 1).findChild(QComboBox)
        self.assertIsNone(combo.currentData())
        self.assertEqual(len(self.tab.sequence), 1)

    def test_scene_file_button_and_reuse_from_library(self):
        image = self.root / "still.png"
        Image.new("RGB", (40, 60), "orange").save(image)
        self.tab.sequence = [{"kind": "media", "media": None, "seconds": 1.5},
                             {"kind": "media", "media": None, "seconds": .5}]
        self.tab._refresh_table()
        button = next(b for b in self.tab.table.cellWidget(0, 1).findChildren(QPushButton)
                      if b.text() == "Archivo…")
        with patch.object(ct.QFileDialog, "getOpenFileName", return_value=(str(image), "")):
            button.click()
        self.assertEqual(self.tab.sequence[0]["media"], 0)
        combo = self.tab.table.cellWidget(1, 1).findChild(QComboBox)
        combo.setCurrentIndex(combo.findData(0))
        self.assertEqual(self.tab.sequence[1]["media"], 0)
        self.assertEqual(len(self.tab.media), 1)
        self.assertEqual(assignment_summary(self.tab.sequence, self.tab.media)["complete"], 2)
        self.assertEqual(self.tab.sequence[1]["seconds"], .5)

    def test_removing_library_file_preserves_all_scene_slots_and_durations(self):
        for name in ("a", "b", "c"):
            path = self.root / f"{name}.png"
            Image.new("RGB", (40, 60), "orange").save(path)
            self.tab.add_media_files([str(path)])
        self.tab.sequence = [{"kind": "media", "media": 1, "seconds": 1},
                             {"kind": "double", "media": 0, "media2": 1, "seconds": 2},
                             {"kind": "split", "medias": [0, 1, 2], "seconds": 3}]
        self.tab._refresh_table()
        before = plan_timings(self.tab.sequence)
        self.tab.media_list.setCurrentRow(1)
        self.tab._remove_media()
        self.assertEqual(len(self.tab.sequence), 3)
        self.assertEqual(plan_timings(self.tab.sequence), before)
        self.assertIsNone(self.tab.sequence[0]["media"])
        self.assertIsNone(self.tab.sequence[1]["media2"])
        self.assertEqual(self.tab.sequence[2]["medias"], [0, None, 1])
        self.assertEqual(len(assignment_summary(self.tab.sequence, self.tab.media)["pending"]), 3)
        self.tab._auto_save()
        self.assertEqual(self.data()["sequence"][2]["medias"], [0, None, 1])

    def test_times_and_timeline_selection_update_after_edit_and_reorder(self):
        self.tab.auto_save_check.setChecked(False)
        self.tab.sequence = [{"kind": "card", "text": "FIRST", "seconds": 1.5},
                             {"kind": "media", "media": None, "seconds": .5}]
        self.tab._refresh_table()
        self.assertEqual(self.tab.table.item(1, 7).text(), "00:01.500")
        self.tab.table.cellWidget(0, 3).setValue(2.5)
        self.assertEqual(self.tab.table.item(1, 7).text(), "00:02.500")
        self.assertEqual(self.tab.table.item(1, 8).text(), "00:03.000")
        QTest.mouseClick(self.tab.timeline, Qt.MouseButton.LeftButton, pos=QPoint(214, 40))
        self.assertEqual(self.tab.table.currentRow(), 1)
        self.tab._move_shot(-1)
        self.assertEqual(self.tab.table.item(0, 7).text(), "00:00.000")
        self.assertEqual(self.tab.table.item(1, 7).text(), "00:00.500")
        self.assertEqual(self.tab.table.item(1, 8).text(), "00:03.000")
        self.assertIn("0.500 s", self.tab.shot_caption.text())

    def test_pending_plan_and_auto_assignment_option_restore(self):
        self.tab.sequence = [{"kind": "split", "medias": [None, None, None], "seconds": .8}]
        self.tab.auto_assign_check.setChecked(True)
        self.tab._refresh_table()
        self.tab._auto_save()
        project = self.tab.current_project_path
        self.tab.close()
        self.tab = ct.CatharsisTab(settings=self.settings)
        self.wait_for(lambda: self.tab.current_project_path == project)
        self.assertEqual(self.tab.sequence[0]["medias"], [None, None, None])
        self.assertTrue(self.tab.auto_assign_check.isChecked())
        self.assertIn("3 de 3 espacios por asignar", self.tab.total_label.text())


if __name__ == "__main__":
    unittest.main()
