import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
import chat_package as p
import chat_receiver as r

class TechnicalQATests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);(self.folder/'video.mp4').write_bytes(b'fixture')
        Image.new('RGB',(1080,1920),'black').save(self.folder/'thumbnail.jpg')
        self.data={'format':{'duration':'53'},'streams':[
            {'codec_type':'video','codec_name':'h264','width':1080,'height':1920,'pix_fmt':'yuv420p','avg_frame_rate':'30/1'},
            {'codec_type':'audio','codec_name':'aac','sample_rate':'44100','channels':2}]}
    def qa(self,decode_code=0):
        with patch.object(r.subprocess,'run',side_effect=[Mock(returncode=0,stdout=json.dumps(self.data)),Mock(returncode=decode_code)]) as run:
            result=r.technical_qa(self.folder)
            self.assertIn('-xerror',run.call_args_list[-1].args[0])
            return result
    def test_full_decode_and_format_pass(self):
        result=self.qa();self.assertTrue(result['technical_checks_passed'])
        self.assertEqual(result['sha256'],p.digest(self.folder/'video.mp4'))
    def test_decode_error_prevents_approval(self):
        with self.assertRaisesRegex(p.InvalidPackage,'video_decode_failed'):self.qa(1)
    def test_missing_audio_is_rejected(self):
        self.data['streams'].pop()
        with self.assertRaisesRegex(p.InvalidPackage,'audio_stream_required'):self.qa()
    def test_wrong_size_is_rejected(self):
        self.data['streams'][0]['width']=1920
        with self.assertRaisesRegex(p.InvalidPackage,'video_format_invalid'):self.qa()
    def test_wrong_duration_is_rejected(self):
        self.data['format']['duration']='3'
        with self.assertRaisesRegex(p.InvalidPackage,'video_duration_invalid'):self.qa()

if __name__=='__main__':unittest.main(verbosity=2)
