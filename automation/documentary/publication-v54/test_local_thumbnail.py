from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import publish_documentary as app
import documentary_youtube_core as core
from test_publish_documentary import AdapterTests

class LocalThumbnailTests(unittest.TestCase):
    def test_the_exact_final_jpeg_is_accepted_without_rewriting(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'cover.jpg';Image.new('RGB',(1672,936)).save(path,'JPEG')
            before=path.read_bytes();result=app.local_thumbnail(path,core.sha(path))
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(result['mimetype'],'image/jpeg');self.assertFalse(result['converted'])
    def test_changed_bytes_symlink_and_non_image_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'cover.jpg';Image.new('RGB',(1280,720)).save(path,'JPEG')
            expected=core.sha(path)
            with self.assertRaisesRegex(core.Blocked,'thumbnail_local_changed'):
                app.local_thumbnail(path,'0'*64)
            link=path.parent/'link.jpg';link.symlink_to(path)
            with self.assertRaisesRegex(core.Blocked,'symlink_rejected'):
                app.local_thumbnail(link,expected)
            path.write_bytes(b'not an image')
            with self.assertRaises(Exception):app.local_thumbnail(path,core.sha(path))
    def test_both_sources_cannot_be_selected(self):
        with patch('sys.stderr'),self.assertRaises(SystemExit):
            app.arguments(['--job-id','a'*32,'--approval-sha256','b'*64,'--thumbnail-url','https://example.org/a.png','--thumbnail-file','a.jpg','--inspect'])

class LocalAdapterTests(AdapterTests):
    def test_inspect_reads_local_thumbnail_without_credentials_or_publication(self):
        argv=self.fixture();argv=argv[:4]
        path=self.root/'cover.jpg';Image.new('RGB',(1280,720)).save(path,'JPEG')
        argv+=['--thumbnail-file',str(path),'--thumbnail-sha256',core.sha(path),'--inspect']
        before=path.read_bytes()
        with patch.object(core,'service') as service,patch.object(core,'main') as main,patch.object(core,'emit'):
            app.main(argv)
            service.assert_not_called();main.assert_not_called()
        self.assertFalse(app.PUBLICATIONS.exists())
        self.assertEqual(core.THUMBNAIL_URL,'sha256:'+core.sha(path))
        self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
