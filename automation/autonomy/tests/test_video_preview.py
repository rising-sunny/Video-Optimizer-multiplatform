from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'modules'))
import workflow_preview as preview

class Preview(unittest.TestCase):
    def test_extracts_only_fixed_video_frames_without_writing_job_files(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);video=folder/'video.mp4';video.write_bytes(b'existing video')
            with patch.object(preview.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=b'\xff\xd8image')) as run:
                images=preview.frames(folder)
            self.assertEqual(len(images),4);self.assertFalse(images[0]['quality_approval'])
            self.assertEqual(list(folder.iterdir()),[video])
            self.assertEqual(run.call_args.args[0][-1],'-');self.assertNotIn('-y',run.call_args.args[0])

    def test_unstable_video_or_non_image_output_does_not_return_misbound_frames(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);(folder/'video.mp4').write_bytes(b'existing video')
            with patch.object(preview.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=b'not an image')):
                self.assertEqual(preview.frames(folder),[])
            with patch.object(preview.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=b'\xff\xd8image')),patch.object(preview.c,'digest',side_effect=['old','changed']):
                self.assertEqual(preview.frames(folder),[])

if __name__=='__main__':unittest.main()
