import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
import reconcile as rec
from cover import cover_title, prepare

class Covers(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.cover=self.base/'cover.jpg'
        Image.new('RGB',(1080,1920),'#123145').save(self.cover)
        self.since=datetime(2026,11,19,tzinfo=timezone.utc)
        self.api=Mock()
        self.video={'snippet':{'channelId':rec.ACCOUNTS['lab'][1],'publishedAt':'2026-11-20T00:00:00Z'},
                    'status':{'uploadStatus':'processed','privacyStatus':'public'},
                    'processingDetails':{'processingStatus':'succeeded'}}
        self.api.videos.return_value.list.return_value.execute.return_value={'items':[self.video]}
        self.setter=self.api.thumbnails.return_value.set
        self.setter.return_value.execute.return_value={'items':[{'default':{}}]}
    def attach(self):
        return rec.attach(self.api,'lab','abcdefghijk',self.cover,self.since)
    def test_pending_processing(self):
        self.video['processingDetails']['processingStatus']='processing'
        self.assertEqual(self.attach(),'waiting_processing');self.setter.assert_not_called()
    def test_owner_and_date(self):
        self.video['snippet']['publishedAt']='2025-01-01T01:02:03Z'
        self.assertEqual(self.attach(),'before_rollout')
        self.video['snippet']['channelId']='another'
        with self.assertRaises(ValueError):self.attach()
        self.setter.assert_not_called()
    def test_receipt_retries_same_id_after_schedule_removal(self):
        (self.base/'enabled-at').write_text(self.since.isoformat())
        self.setter.return_value.execute.side_effect=[RuntimeError('temporary'),{'items':[{}]}]
        active=[('abcdefghijk',self.cover)]
        with patch.object(rec,'STATE',self.base),patch.object(rec,'account',return_value=self.api),patch.object(rec,'jobs',side_effect=lambda ch,since: list(active) if ch=='lab' else []),patch.object(sys,'argv',['reconcile']):
            with self.assertRaises(SystemExit):rec.main()
            active.clear()
            with sqlite3.connect(self.base/'receipts.sqlite') as db:db.execute('update covers set next_try=0')
            rec.main();rec.main()
            self.assertEqual([kw.kwargs['videoId'] for kw in self.setter.call_args_list],['abcdefghijk']*2)
            self.api.videos.return_value.insert.assert_not_called()
            with sqlite3.connect(self.base/'receipts.sqlite') as db:
                self.assertEqual(db.execute('select status from covers').fetchone()[0],'accepted')
    def test_renderer_cache_and_title_change(self):
        video=self.base/'fake.mp4';video.write_bytes(b'example')
        with patch('cover.frame',return_value=Image.new('RGB',(720,1280),'#31535b')) as frames:
            for title in ['A test','A test','Another test']:prepare('lab',video,title,self.cover)
            self.assertEqual(frames.call_count,2)
            with Image.open(self.cover) as im:self.assertEqual(im.size,(1080,1920))
        self.assertEqual(cover_title('One Ripple | Math Art'),'One Ripple')
        self.assertEqual(cover_title('Sunset ☁️ #shorts'),'Sunset')
        self.assertEqual(cover_title('These Clouds Are Just Noise ☁️ Sunset Sky #shorts'),'These Clouds Are Just Noise')

if __name__=='__main__':unittest.main()
