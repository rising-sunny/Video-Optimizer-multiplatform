import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QComboBox, QSlider, QRadioButton, QPushButton
from channel_profiles import active_channel, DEFAULT_CHANNEL, select_channel
from studio_channel_controls import (install_controls, restore_channel_config, project_channel_config,
                                     PilotDialog, sync_editorial_before_writing)


class StudioStub(QWidget):
    def __init__(self):
        super().__init__()
        self.is_generating = False
        self.current_project_path = None
        self.platform_combo = QComboBox()
        self.platform_combo.addItem('16:9')
        self.duration_slider = QSlider()
        self.duration_slider.setRange(30, 7200)
        self.lang_en = QRadioButton()
        self.events = []
        install_controls(self, QVBoxLayout(self))

    def log(self, message):
        self.events.append(message)


class ChannelGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        select_channel(DEFAULT_CHANNEL)

    def setUp(self):
        self.settings_dir = TemporaryDirectory()
        self.addCleanup(self.settings_dir.cleanup)

    def test_selection_and_project_restore(self):
        tab = StudioStub()
        restore_channel_config(tab, {'channel_profile': 'stunning-revelations', 'format_strategy': 'micro_documentary'})
        # Con guion escrito, cambiar el destino NO cambia el perfil con el que se escribio.
        tab.last_storyboard_data = {'segments': [{'text': 'ya escrito'}]}
        tab.current_project_path = str(Path(self.settings_dir.name) / 'project.json')
        tab.channel_combo.setCurrentIndex(tab.channel_combo.findData(DEFAULT_CHANNEL))
        config = project_channel_config(tab)
        self.assertEqual(config['upload_channel'], DEFAULT_CHANNEL)
        self.assertEqual(config['channel_profile'], 'stunning-revelations')
        self.assertEqual(config['format_strategy'], 'micro_documentary')
        restore_channel_config(tab, config)
        self.assertEqual(tab.channel_combo.currentData(), DEFAULT_CHANNEL)
        self.assertEqual(active_channel(), 'stunning-revelations')
        tab.close()

    def _with_parent(self, tab):
        """El combo de categorias vive en la ventana principal (parent_gui)."""
        parent = QWidget()
        parent.category_combo = QComboBox()
        tab.parent_gui = parent
        self.addCleanup(parent.close)
        return parent

    def test_un_proyecto_nuevo_se_escribe_para_el_canal_destino(self):
        """BUG 2026-09-21: desde el 8-9 todos los guiones del canal nuevo se escribieron
        con el perfil editorial del viejo (select_channel es global y quedaba pegado)."""
        tab = StudioStub()
        parent = self._with_parent(tab)
        # Se abrio un proyecto viejo de Stunning Revelations...
        restore_channel_config(tab, {'channel_profile': 'stunning-revelations', 'upload_channel': DEFAULT_CHANNEL})
        self.assertEqual(active_channel(), 'stunning-revelations')
        self.assertIn('Historical Mysteries', [parent.category_combo.itemText(i) for i in range(parent.category_combo.count())])
        # ...y ahora se va a escribir un guion NUEVO (sin storyboard) para el canal destino.
        tab.last_storyboard_data = None
        tab.current_project_path = None
        self.assertTrue(sync_editorial_before_writing(tab))
        self.assertEqual(active_channel(), DEFAULT_CHANNEL)
        self.assertEqual(project_channel_config(tab)['channel_profile'], DEFAULT_CHANNEL)
        categorias = [parent.category_combo.itemText(i) for i in range(parent.category_combo.count())]
        self.assertIn('War & Military History', categorias)
        self.assertNotIn('Historical Mysteries', categorias)
        self.assertTrue(any('Perfil editorial' in e for e in tab.events))
        tab.close()

    def test_un_proyecto_con_guion_conserva_su_perfil(self):
        tab = StudioStub()
        self._with_parent(tab)
        restore_channel_config(tab, {'channel_profile': 'stunning-revelations', 'upload_channel': DEFAULT_CHANNEL})
        tab.last_storyboard_data = {'segments': [{'text': 'x'}]}
        tab.current_project_path = str(Path(self.settings_dir.name) / 'project.json')
        self.assertFalse(sync_editorial_before_writing(tab))
        self.assertEqual(active_channel(), 'stunning-revelations')
        # Salvo que el tema cambie y el proyecto se aisle: entonces es un proyecto nuevo.
        self.assertTrue(sync_editorial_before_writing(tab, isolated=True))
        self.assertEqual(active_channel(), DEFAULT_CHANNEL)
        tab.close()

    def test_sin_guion_el_combo_de_destino_arrastra_al_editorial(self):
        tab = StudioStub()
        parent = self._with_parent(tab)
        tab.last_storyboard_data = None
        tab.channel_combo.setCurrentIndex(tab.channel_combo.findData('stunning-revelations'))
        self.assertEqual(active_channel(), 'stunning-revelations')
        self.assertEqual(project_channel_config(tab)['channel_profile'], 'stunning-revelations')
        tab.channel_combo.setCurrentIndex(tab.channel_combo.findData(DEFAULT_CHANNEL))
        self.assertEqual(active_channel(), DEFAULT_CHANNEL)
        self.assertIn('War & Military History', [parent.category_combo.itemText(i) for i in range(parent.category_combo.count())])
        tab.close()

    def test_publishing_cannot_change_destination(self):
        tab = StudioStub()
        tab.btn_publish = QPushButton('Publicando...')
        with patch('studio_channel_controls.QMessageBox.information'):
            tab.channel_combo.setCurrentIndex(1)
        self.assertEqual(tab.channel_combo.currentData(), DEFAULT_CHANNEL)
        tab.close()

    def test_dialog_constructs_and_has_explicit_stages(self):
        tab = StudioStub()
        with TemporaryDirectory() as tmp:
            dialog = PilotDialog(tab, Path(tmp), 'Coronel', 'stunning-revelations')
            labels = [button.text() for button in dialog.buttons]
            self.assertIn('Aprobar y crear guion', labels)
            self.assertIn('Ensamblar piloto', labels)
            self.assertFalse((Path(tmp) / 'experiment.json').exists())
            dialog.close()
        tab.close()

    def test_pilot_inherits_manual_images_from_studio(self):
        tab = StudioStub()
        tab.image_provider_combo = QComboBox()
        tab.image_provider_combo.addItem('Manual (Gratuito)')
        with TemporaryDirectory() as tmp:
            dialog = PilotDialog(tab, tmp, 'Coronel', 'stunning-revelations')
            self.assertEqual(dialog.provider.currentData(), 'manual')
            self.assertIn('no genera imágenes', dialog.image_help.text())
            dialog.close()
        tab.close()

    def test_destination_change_keeps_timeline_and_autosaves(self):
        tab = StudioStub()
        tab.btn_open_timeline = QPushButton()
        tab.last_storyboard_data = {'segments': [{'text': 'Complete', 'image_path': 'visual.png', 'duration': 8}]}
        storyboard = tab.last_storyboard_data
        tab.timeline_editor_window = QWidget()
        editor = tab.timeline_editor_window
        tab.current_project_path = str(Path(self.settings_dir.name) / 'project.json')
        original_path = tab.current_project_path
        tab.auto_save_project = lambda reason: Path(tab.current_project_path).write_text(
            json.dumps({'config': project_channel_config(tab), 'storyboard': tab.last_storyboard_data}), encoding='utf-8')
        tab.duration_slider.setValue(123)
        tab.channel_combo.setCurrentIndex(tab.channel_combo.findData('stunning-revelations'))
        self.assertEqual(tab.current_project_path, original_path)
        self.assertIs(tab.last_storyboard_data, storyboard)
        self.assertIs(tab.timeline_editor_window, editor)
        self.assertTrue(tab.btn_open_timeline.isEnabled())
        self.assertEqual(tab.duration_slider.value(), 123)
        saved = json.loads(Path(original_path).read_text(encoding='utf-8'))
        self.assertEqual(saved['config']['upload_channel'], 'stunning-revelations')
        self.assertEqual(saved['storyboard'], storyboard)
        tab.channel_combo.setCurrentIndex(tab.channel_combo.findData(DEFAULT_CHANNEL))
        self.assertIs(tab.last_storyboard_data, storyboard)
        self.assertEqual(tab.current_project_path, original_path)
        tab.close()

    def test_upload_destination_overrides_legacy_metadata(self):
        from youtube_uploader import upload_from_metadata
        folder = Path(self.settings_dir.name)
        (folder / 'video.mp4').touch()
        (folder / 'project.json').write_text(json.dumps({'config': {'upload_channel': DEFAULT_CHANNEL}}), encoding='utf-8')
        for explicit, expected in [(None, DEFAULT_CHANNEL), ('stunning-revelations', 'stunning-revelations')]:
            metadata = {'channel_profile': 'stunning-revelations', 'is_short': False}
            if explicit:
                metadata['upload_channel'] = explicit
            with patch('youtube_uploader._load_upload_metadata', return_value=metadata), \
                 patch('youtube_uploader._archive_upload_result'), \
                 patch('youtube_uploader.upload_video', return_value={'video_id': 'test', 'url': 'test', 'status': 'ok'}) as upload:
                upload_from_metadata(folder)
                self.assertEqual(upload.call_args.kwargs['channel_profile'], expected)


if __name__ == '__main__':
    unittest.main()
