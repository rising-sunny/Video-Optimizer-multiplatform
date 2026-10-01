"""Exercise disk persistence and the actual Studio debounce without loading AI clients."""
import ast
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QLineEdit, QCheckBox, QRadioButton, QComboBox
from PyQt6.QtTest import QTest
from studio_project_manager import StudioProjectManager
from project_manager_v2 import ProjectManagerV2
from channel_profiles import select_channel, active_channel, DEFAULT_CHANNEL
from studio_channel_controls import PilotDialog, open_pilot
from test_studio_channel_controls import StudioStub
from test_micro_documentary import package
from studio_categories import MYSTERY_CATEGORY


def studio_method(name):
    tree = ast.parse(Path('auto_video_integration_pyqt6.py').read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'AutoVideoStudioTab')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<studio-method>', 'exec'), namespace)
    return namespace[name]


class AutosaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        select_channel(DEFAULT_CHANNEL)

    def test_lazy_constructor_binds_real_topic_field_while_parent_is_dummy(self):
        # The parent proxy only resolves to Studio AFTER its constructor returns.
        dummy = type('_Dummy', (), {'text': lambda self: ''})()
        editor = QLineEdit()
        trigger = Mock()
        tab = SimpleNamespace(parent_gui=SimpleNamespace(topic_input=dummy),
                              topic_input=editor, last_storyboard_data=None,
                              _trigger_config_auto_save=trigger)
        studio_method('_connect_auto_save_signals')(tab)
        editor.setText('New project topic')
        editor.editingFinished.emit()
        trigger.assert_called_once_with('tema del nuevo proyecto')
        editor.deleteLater()

    def test_changing_category_triggers_configuration_autosave(self):
        combo = QComboBox()
        combo.addItems(["War & Military History", MYSTERY_CATEGORY])
        trigger = Mock()
        tab = SimpleNamespace(category_combo=combo, _trigger_config_auto_save=trigger)
        studio_method('_connect_auto_save_signals')(tab)
        combo.setCurrentText(MYSTERY_CATEGORY)
        trigger.assert_called_once_with('cambio de categoria')
        combo.deleteLater()

    def test_named_draft_creates_folder_and_updates_without_storyboard_for_both_channels(self):
        for channel in (DEFAULT_CHANNEL, 'stunning-revelations'):
            with self.subTest(channel=channel), TemporaryDirectory() as tmp:
                select_channel(channel)
                tab = SimpleNamespace(parent_gui=SimpleNamespace(topic_input=SimpleNamespace(text=lambda: 'New topic'),
                    category_combo=SimpleNamespace(currentText=lambda: MYSTERY_CATEGORY)),
                    current_project_path=None, last_storyboard_data=None, last_generated_video_data=None,
                    platform_combo=SimpleNamespace(currentText=lambda: '16:9'),
                    duration_slider=SimpleNamespace(value=lambda: 270), lang_es=SimpleNamespace(isChecked=lambda: False),
                    style_combo=SimpleNamespace(currentText=lambda: 'Photorealism'), log=lambda message: None,
                    channel_combo=SimpleNamespace(currentData=lambda: channel))
                manager = StudioProjectManager(tab)
                manager._sync_timeline_editor_to_storyboard = Mock()
                manager._storyboard_is_unusable = lambda storyboard: False
                manager._get_thumbnail_snapshot = lambda: (None, {})
                manager._sync_selected_music_state = Mock()
                manager._sync_thumbnail_state = Mock()
                manager._persist_selected_music_for_project = lambda path, data: data
                manager._persist_thumbnail_state_for_project = lambda path, data: data
                with patch.object(ProjectManagerV2, 'PROJECTS_DIR', Path(tmp)), patch.object(ProjectManagerV2, '_dir_ensured', False):
                    self.assertTrue(manager.auto_save_project('new draft'))
                    path = Path(tab.current_project_path)
                    self.assertTrue(path.exists())
                    saved = json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(saved['config']['channel_profile'], channel)
                    self.assertEqual(saved['config']['topic'], 'New topic')
                    self.assertEqual(saved['config']['category'], MYSTERY_CATEGORY)
                    tab.duration_slider.value = lambda: 290
                    self.assertTrue(manager.auto_save_project('changed duration'))
                    self.assertEqual(tab.current_project_path, str(path))
                    self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['config']['duration'], 290)
                    self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['storyboard'], {})
                    self.assertEqual(manager.validate_project_files(ProjectManagerV2.load_project(str(path))), [])

    def test_full_load_of_empty_and_legacy_null_storyboards_for_both_channels(self):
        for channel in (DEFAULT_CHANNEL, 'stunning-revelations'):
            for storyboard in ({}, None):
                with self.subTest(channel=channel, storyboard=storyboard), TemporaryDirectory() as tmp:
                    path = Path(tmp) / 'project.json'
                    path.write_text(json.dumps({'config': {'topic': 'Draft topic', 'channel_profile': channel,
                        'category': MYSTERY_CATEGORY,
                        'duration': 270, 'language': 'en', 'platform_key': 'youtube', 'style': 'Photorealism'},
                        'storyboard': storyboard, 'progress': {'storyboard_done': False}}), encoding='utf-8')
                    tab = StudioStub()
                    tab.parent_gui = SimpleNamespace(topic_input=QLineEdit(), category_combo=QComboBox())
                    tab.lang_es = QRadioButton()
                    tab.subtitles_check = QCheckBox()
                    tab.style_combo = QComboBox()
                    tab.style_combo.addItem('Photorealism')
                    tab.last_storyboard_data = None
                    tab.last_generated_video_data = None
                    manager = StudioProjectManager(tab)
                    manager._storyboard_is_unusable = lambda value: False
                    manager._sync_thumbnail_state = Mock()
                    with patch('studio_project_manager.QMessageBox.critical') as critical, patch('studio_project_manager.QMessageBox.warning') as warning:
                        manager.load_project_from_path(str(path))
                    critical.assert_not_called()
                    warning.assert_not_called()
                    self.assertEqual(tab.current_project_path, str(path))
                    self.assertEqual(tab.parent_gui.topic_input.text(), 'Draft topic')
                    self.assertEqual(tab.parent_gui.category_combo.currentText(), MYSTERY_CATEGORY)
                    self.assertEqual(tab.duration_slider.value(), 270)
                    self.assertEqual(active_channel(), channel)
                    self.assertTrue(any('Proyecto cargado exitosamente' in line for line in tab.events))
                    tab.close()

    def test_debounce_saves_without_a_project_path(self):
        manager = SimpleNamespace(auto_save_project=Mock())
        tab = SimpleNamespace(_loading_project=False, auto_save_enabled=True, project_manager=manager, current_project_path=None)
        trigger = studio_method('_trigger_config_auto_save')
        trigger(tab, 'new project setting')
        trigger(tab, 'another change')
        QTest.qWait(2200)
        manager.auto_save_project.assert_called_once()
        tab._config_auto_save_timer.stop()

    def test_pilot_editor_autosaves_and_restores_incomplete_json(self):
        tab = StudioStub()
        with TemporaryDirectory() as tmp:
            dialog = PilotDialog(tab, tmp, 'Coronel', 'stunning-revelations')
            data = package()
            data.update(channel='stunning-revelations', topic='Coronel', target_runtime_seconds=270, effective_wpm=120)
            dialog.editor.setPlainText(json.dumps(data))
            QTest.qWait(550)
            original = (Path(tmp) / 'experiment.json').read_text(encoding='utf-8')
            self.assertEqual(json.loads(original)['hook'], data['hook'])
            incomplete = '{"topic": "Coronel",'
            dialog.editor.setPlainText(incomplete)
            dialog.reject()  # Flush even before debounce expires.
            self.assertEqual((Path(tmp) / 'experiment.json').read_text(encoding='utf-8'), original)
            reopened = PilotDialog(tab, tmp, 'Coronel', 'stunning-revelations')
            self.assertEqual(reopened.editor.toPlainText(), incomplete)
            reopened.reject()
        tab.close()

    def test_open_pilot_flushes_studio_before_reading_project(self):
        tab = StudioStub()
        tab.parent_gui = SimpleNamespace(topic_input=SimpleNamespace(text=lambda: 'Coronel'))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'project.json'
            path.write_text('{}')
            tab.current_project_path = str(path)
            tab.auto_save_project = Mock(return_value=True)
            with patch('studio_channel_controls.QFileDialog.getExistingDirectory') as chooser, patch('studio_channel_controls.PilotDialog') as dialog:
                def create(*args):
                    tab.auto_save_project.assert_called_once_with('antes de continuar el piloto')
                    self.assertEqual(args[1], Path(tmp).resolve())
                    return Mock()
                dialog.side_effect = create
                open_pilot(tab)
                chooser.assert_not_called()
                dialog.assert_called_once()
        tab.close()

    def test_generate_new_pilot_creates_folder_and_starts_without_picker(self):
        tab = StudioStub()
        tab.parent_gui = SimpleNamespace(topic_input=SimpleNamespace(text=lambda: 'New topic'))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'project.json'
            def autosave(reason):
                path.write_text('{}')
                tab.current_project_path = str(path)
                return True
            tab.auto_save_project = autosave
            with patch('studio_channel_controls.QFileDialog.getExistingDirectory') as chooser, patch('studio_channel_controls.PilotDialog') as factory:
                factory.return_value.exec.side_effect = self.app.processEvents
                open_pilot(tab, generate=True)
                chooser.assert_not_called()
                factory.return_value.run_stage.assert_called_once_with(False, False)
                self.assertEqual(factory.call_args.args[1], Path(tmp).resolve())
        tab.close()

    def test_microdoc_reuses_the_autosaved_config_draft(self):
        from micro_documentary import build, write_json
        from test_micro_documentary import FakeClient
        with TemporaryDirectory() as tmp:
            write_json(Path(tmp) / 'project.json', {'config': {'topic': 'Coronel', 'channel_profile': 'stunning-revelations'}, 'storyboard': {}})
            result = build('Coronel', tmp, channel='stunning-revelations', client=FakeClient([package()]))
            self.assertEqual(result['status'], 'awaiting_editorial_review')
            self.assertTrue((Path(tmp) / 'project.json').exists())


if __name__ == '__main__':
    unittest.main()
