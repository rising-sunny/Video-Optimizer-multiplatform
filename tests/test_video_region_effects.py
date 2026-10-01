import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QProgressDialog, QPushButton, QListWidgetItem
from infra.video_config import VideoConfig
from video_region_effects import effect_graph, export_command, preview_frame, video_size
from video_region_editor import RegionCanvas, VideoRegionEditor, export_region_copy


class VideoRegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        VideoConfig.ensure_ffmpeg_in_path()
        cls.app = QApplication.instance() or QApplication([])
        cls.temp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.temp.name) / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=10',
                        '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', '-c:v', 'libx264',
                        '-c:a', 'aac', str(cls.source)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_effects_real_export_and_audio(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        for mode in ['cover', 'blur', 'remove']:
            with self.subTest(mode=mode):
                edit = {'mode': mode, 'rect': [.7, .05, .2, .2]}
                self.assertTrue(preview_frame(self.source, .2, edit).startswith(b'\x89PNG'))
                output = export_region_copy(self.source, edit)
                self.assertEqual(video_size(output), (320, 240))
                result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', output],
                                        capture_output=True, check=True)
                streams = json.loads(result.stdout)['streams']
                self.assertEqual({s['codec_type'] for s in streams}, {'audio', 'video'})
                self.assertAlmostEqual(float(streams[0]['duration']), 1, delta=.15)
                self.assertNotEqual(Path(output), self.source)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_cover_pixels_and_original_unchanged(self):
        original, edited = QPixmap(), QPixmap()
        original.loadFromData(preview_frame(self.source, 0))
        edited.loadFromData(preview_frame(self.source, 0, {'mode': 'cover', 'rect': [.7, .05, .2, .2]}))
        self.assertEqual(edited.toImage().pixelColor(768, 100), QColor('black'))
        self.assertEqual(edited.toImage().pixelColor(100, 100), original.toImage().pixelColor(100, 100))

    def test_letterbox_selection_and_clamping(self):
        pixmap = QPixmap(400, 300)
        pixmap.fill(Qt.GlobalColor.gray)
        canvas = RegionCanvas(pixmap)
        canvas.resize(800, 300)
        canvas.show()
        self.app.processEvents()
        # Image occupies x=200..600. Black bars must not be selectable.
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(150, 150))
        self.assertIsNone(canvas.selection)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(500, 30))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(580, 90))
        for actual, expected in zip(canvas.selection, [.75, .1, .2, .2]):
            self.assertAlmostEqual(actual, expected)
        canvas.close()

    def test_invalid_region_and_edge_removal(self):
        for rect in [[0, 0, 0, .2], [.9, .1, .2, .2], [float('nan'), 0, .2, .2]]:
            with self.assertRaises(ValueError):
                effect_graph({'mode': 'cover', 'rect': rect}, 320, 240)
        with self.assertRaises(ValueError):
            effect_graph({'mode': 'remove', 'rect': [.8, 0, .2, .2]}, 320, 240)
        for mode in ['cover', 'blur']:
            self.assertTrue(preview_frame(self.source, 0, {'mode': mode, 'rect': [.8, 0, .2, .2]}))

    def test_editor_accepts_region(self):
        edit = {'mode': 'blur', 'rect': [.7, .05, .2, .2]}
        dialog = VideoRegionEditor(self.source, .2, edit)
        dialog.use_region()
        self.assertEqual(dialog.edit, edit)
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)

    def test_cancel_export_removes_partial_copy(self):
        edit = {'mode': 'cover', 'rect': [.7, .05, .2, .2]}
        args, output = export_command(self.source, edit)
        args.insert(args.index('-i'), '-re')
        def cancel():
            for widget in self.app.topLevelWidgets():
                if isinstance(widget, QProgressDialog) and widget.isVisible():
                    widget.findChild(QPushButton).click()
        with patch('video_region_editor.export_command', return_value=(args, output)):
            QTimer.singleShot(150, cancel)
            with self.assertRaisesRegex(RuntimeError, 'cancelada'):
                export_region_copy(self.source, edit)
        self.assertFalse(output.exists())
        self.assertTrue(self.source.exists())

    def test_switching_youtube_video_clears_effect_and_preview(self):
        from youtube_video_search_dialog import YouTubeVideoSearchDialog
        with patch.object(YouTubeVideoSearchDialog, 'load_previous_results'), \
             patch.object(YouTubeVideoSearchDialog, '_start_frame_extraction'):
            dialog = YouTubeVideoSearchDialog()
            for url in ['first', 'second']:
                item = QListWidgetItem(url)
                item.setData(Qt.ItemDataRole.UserRole, {'url': url, 'duration': 10})
                dialog.results_list.addItem(item)
            dialog.results_list.setCurrentRow(0)
            dialog.region_edit = {'mode': 'cover', 'rect': [.7, .05, .2, .2]}
            dialog.current_video_path = str(self.source)
            dialog.results_list.setCurrentRow(1)
            self.assertIsNone(dialog.region_edit)
            self.assertIsNone(dialog.current_video_path)
            self.assertFalse(dialog.region_clear_btn.isEnabled())
            dialog.close()


if __name__ == '__main__':
    unittest.main()
