import json
import tempfile
import unittest
from pathlib import Path
from infra.project_video_result import saved_video_result


class ProjectVideoResultTests(unittest.TestCase):
    def test_committed_render_wins_over_old_nested_reference(self):
        with tempfile.TemporaryDirectory(suffix='.json') as tmp:
            root = Path(tmp)
            (root / 'new.mp4').touch()
            (root / 'old.mp4').touch()
            project = root / 'project.json'
            project.write_text(json.dumps({'video_path': 'new.mp4', 'generated_video_data': {'video_path': 'old.mp4'}}))
            self.assertEqual(saved_video_result(project)['video_path'], str((root / 'new.mp4').resolve()))

    def test_no_search_of_unrelated_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'unrelated.mp4').touch()
            project = root / 'project.json'
            project.write_text('{}')
            self.assertIsNone(saved_video_result(project))


if __name__ == '__main__':
    unittest.main()
