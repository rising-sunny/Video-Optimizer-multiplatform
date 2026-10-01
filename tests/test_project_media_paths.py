import tempfile
import unittest
from pathlib import Path
from infra.project_media_paths import project_directory, prepare_existing_media


class ProjectMediaPathsTests(unittest.TestCase):
    def test_json_directory_and_project_file_resolve_same_media(self):
        with tempfile.TemporaryDirectory(suffix='.json') as tmp:
            root = Path(tmp)
            (root / 'project.json').write_text('{}')
            (root / 'project_media').mkdir()
            (root / 'project_media' / 'clip.mp4').touch()
            for hint in (root, root / 'project.json'):
                self.assertEqual(project_directory(hint), root.resolve())
                sb = {'segments': [{'video_path': 'project_media/clip.mp4'}]}
                prepare_existing_media(sb, hint)
                self.assertEqual(sb['segments'][0]['video_path'], str((root / 'project_media/clip.mp4').resolve()))

    def test_missing_media_stops_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'segmentos 1'):
                prepare_existing_media({'segments': [{'image_path': 'missing.png'}]}, tmp)

    def test_intentionally_deleted_image_remains_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepare_existing_media({'segments': [{'image_deleted': True}]}, tmp)


if __name__ == '__main__':
    unittest.main()
