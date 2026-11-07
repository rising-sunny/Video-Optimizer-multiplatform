import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import workflow_motion_documentary as motion
import documentary_catarsis_render as renderer
import documentary_common as common

class OfficialFilms(unittest.TestCase):
    def record(self,title,size=5000000,license='Public domain'):
        return dict(pageid=1,title=title,videoinfo=[dict(size=size,width=1280,height=720,
            url='https://upload.wikimedia.org/original.webm',descriptionurl='https://commons.wikimedia.org/wiki/'+title,
            duration=1000,extmetadata=dict(LicenseShortName={'value':license},Artist={'value':'NASA'},
            ImageDescription={'value':'Original NASA X-15 programme'},DateTimeOriginal={'value':'2025'}),
            derivatives=[dict(src='https://upload.wikimedia.org/actual.360p.vp9.webm',type='video/webm',
                width=640,height=360,bandwidth=400000)])])
    def test_real_provider_rendition_and_license_are_required(self):
        payload={'query':{'pages':{'1':self.record(motion.FILMS[2],size=200000000)}}}
        rows=motion.film_rows(payload)
        self.assertEqual(len(rows),1);row=rows[0]
        self.assertEqual(row['url'],'https://upload.wikimedia.org/actual.360p.vp9.webm')
        self.assertTrue(row['evidence']['restored_copy'])
        self.assertEqual(row['source_url'],'https://commons.wikimedia.org/?curid=1')
        self.assertIsNone(row['size'])
        payload['query']['pages']['1']['videoinfo'][0]['extmetadata']['LicenseShortName']['value']='All rights reserved'
        self.assertEqual(motion.film_rows(payload),[])
    def test_small_period_original_keeps_actual_size_and_is_not_called_a_2025_recording(self):
        rows=motion.film_rows({'query':{'pages':{'1':self.record(motion.FILMS[0])}}})
        self.assertEqual(rows[0]['size'],5000000)
        self.assertFalse(rows[0]['evidence']['restored_copy'])
        self.assertIn('1962',rows[0]['evidence']['context_note'])
    def test_other_topics_do_not_fetch_or_select_new_media(self):
        self.assertIsNone(motion.prepare(Path('/missing'),dict(channel='stunning-revelations',topic='Skylab: 1973')))
        self.assertEqual(motion.brief(dict(topic='Other')), '')

class PlanNormalization(unittest.TestCase):
    def test_drop_unused_slots_remap_references_and_keep_narration_and_research(self):
        row=dict(id='M'+'1'*16,type='video',title=motion.FILMS[1],evidence={'restored_copy':True})
        value=dict(assets=[dict(type='image',label='unused',media_ids=['M'+'0'*16]),
                           dict(type='image',label='wrong upload-date interpretation',media_ids=[row['id']]),
                           dict(type='image',label='real photo',media_ids=['M'+'2'*16])],
            segments=[dict(asset=1,narration='Original unchanged text.')],thumbnail=dict(asset=2,text='X15'),research=[dict(url='https://nasa.gov/source')])
        before=copy.deepcopy(value)
        result=motion.normalize(value,dict(items=[row]),dict(channel='stunning-revelations',topic='X-15: flight'))
        self.assertEqual(value,before);self.assertEqual(len(result['assets']),2)
        self.assertEqual(result['segments'][0]['asset'],0);self.assertEqual(result['thumbnail']['asset'],1)
        self.assertEqual(result['segments'][0]['narration'],before['segments'][0]['narration'])
        self.assertEqual(result['assets'][0]['type'],'video');self.assertIn('restored copy (2025)',result['assets'][0]['label'])
        self.assertEqual(result['research'],before['research'])
        self.assertEqual(result['motion_profile'],motion.PROFILE)

class MotionEdit(unittest.TestCase):
    def fixture(self):
        assets=[dict(label='X-15 NASA programme '+str(i)) for i in range(11)]
        plan=dict(assets=assets,segments=[dict(asset=i%11,chapter='Chapter '+str(i//4)) for i in range(30)])
        pool=[dict(type='video' if i<3 else 'image',label=a['label'],sha256='source-'+str(i),
            original_asset=i,duration_seconds=1000 if i<3 else 0) for i,a in enumerate(assets)]
        return plan,pool,[20.0]*30
    def test_motion_has_substantial_real_clip_time_exact_frames_and_valid_excerpts(self):
        plan,pool,lengths=self.fixture();plan['motion_profile']=motion.PROFILE
        with patch.object(renderer,'relevance',return_value=3):shots=renderer.timeline(plan,lengths,pool)
        self.assertEqual(sum(s['frames'] for s in shots),18000)
        ratio=sum(s['frames'] for s in shots if s['type']=='video')/18000
        self.assertGreaterEqual(ratio,.35);self.assertLess(ratio,.75)
        self.assertEqual(shots[0]['asset'],0)
        for s in shots:
            if s['type']=='video':
                self.assertGreaterEqual(s['source_start'],30)
                self.assertLess(s['source_start']+s['duration_seconds'],1000)
        self.assertLessEqual(sum(s['transition']=='amber_leak' for s in shots),7)
    def test_existing_style_does_not_inherit_new_profile(self):
        plan,pool,lengths=self.fixture()
        with patch.object(renderer,'relevance',return_value=3):shots=renderer.timeline(plan,lengths,pool)
        self.assertEqual(sum(s['frames'] for s in shots),18000)
        first=next(s for s in shots if s['type']=='video')
        self.assertEqual(first['source_start'],0)
    def test_new_module_is_frozen(self):
        self.assertIn('workflow_motion_documentary.py',common.MODULES)

if __name__=='__main__':unittest.main()
