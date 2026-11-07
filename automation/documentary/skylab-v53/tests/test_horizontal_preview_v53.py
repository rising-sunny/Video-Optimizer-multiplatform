from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import workflow_preview as preview

class Preview(unittest.TestCase):
    def test_horizontal_is_not_stretched_to_portrait_and_samples_later_chapters(self):
        with tempfile.TemporaryDirectory() as root:
            job=Path(root)/'manual-documentary'/'job';job.mkdir(parents=True);(job/'video.mp4').write_bytes(b'original')
            response=types.SimpleNamespace(returncode=0,stdout=b'\xff\xd8sample')
            with patch.object(preview.subprocess,'run',return_value=response) as run:
                result=preview.frames(job)
            self.assertEqual(len(result),8)
            self.assertEqual([x['seconds'] for x in result],[4.,24.5,90.,180.,300.,420.,540.,590.])
            self.assertTrue(all('scale=640:360' in x.args[0] for x in run.call_args_list))
            self.assertEqual((job/'video.mp4').read_bytes(),b'original')
            self.assertTrue(all(x['quality_approval'] is False for x in result))
    def test_short_previews_keep_the_original_portrait_contract(self):
        with tempfile.TemporaryDirectory() as root:
            job=Path(root)/'manual-catarsis'/'batch'/'channel';job.mkdir(parents=True);(job/'video.mp4').write_bytes(b'original')
            with patch.object(preview.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=b'\xff\xd8sample')) as run:
                result=preview.frames(job)
            self.assertEqual(len(result),4)
            self.assertTrue(all('scale=360:640' in x.args[0] for x in run.call_args_list))

if __name__=='__main__':unittest.main()
