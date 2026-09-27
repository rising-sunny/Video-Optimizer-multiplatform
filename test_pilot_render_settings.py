import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from pilot_render_settings import pilot_render_settings


class PilotRenderSettingsTests(unittest.TestCase):
    def test_saved_selections_reach_assembler(self):
        with tempfile.TemporaryDirectory(suffix='.json') as tmp:
            root = Path(tmp)
            (root / 'music.mp3').touch()
            config = {'selected_music_path': 'music.mp3', 'music_enabled': False,
                      'transition_type': 'Film Burn (Overlay)', 'transition_duration': .25,
                      'cinematic_enabled': True, 'cinematic_preset': 'Noir (Dramatico)',
                      'cinematic_intensity': 'epic',
                      'subtitles_enabled': False, 'transition_sfx_enabled': False}
            settings = pilot_render_settings(config, {'transition_type': 'Fade Smooth'}, root)
            self.assertEqual(settings['manual_bgm_path'], str((root / 'music.mp3').resolve()))
            self.assertTrue(settings['apply_cinematic'])
            self.assertEqual(settings['cinematic_preset'], 'noir (dramatico)')
            self.assertEqual(settings['cinematic_intensity'], 'epic')
            from daily_short_pipeline import assemble_video
            generator = Mock()
            generator.assemble_video_from_storyboard.return_value = None
            with patch('dynamic_subtitle_wrapper.patch_subtitle_generation'):
                assemble_video({'_generator': generator, 'segments': []}, root,
                               pregenerate_images=False, assembly_options=settings)
            params = generator.assemble_video_from_storyboard.call_args.kwargs
            for key, value in settings.items():
                self.assertEqual(params[key], value)
            self.assertEqual(params['transition_type'], 'Film Burn (Overlay)')
            self.assertEqual(params['transition_duration'], .25)

    def test_noir_is_forced_instead_of_auto(self):
        from cinematic_effects import filter_for_preset, FilterType
        self.assertEqual(filter_for_preset('Noir (Dramatico)'), FilterType.NOIR)
        self.assertIsNone(filter_for_preset('Auto-Detect (Inteligente)'))


if __name__ == '__main__':
    unittest.main()
