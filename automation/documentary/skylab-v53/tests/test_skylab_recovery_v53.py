import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import workflow_skylab_recovery as recovery
import documentary_common as common
from fixture_skylab_v53 import OBSERVED, CATALOGUE
from fixture_official_media_v53 import ACTUAL

FILM = dict(id='M'+('a'*16),type='video')
PHOTO = dict(id='M'+('b'*16),type='image')

class Curation(unittest.TestCase):
    def test_observed_provider_has_no_360p_webm_and_exact_480p_is_bounded(self):
        from documentary_media import binary_limit
        def fetch(url,limit):
            for row in ACTUAL:
                if ('prop=videoinfo' in url)==('prop=videoinfo' in row['request_url']):
                    return json.dumps(row['response']).encode()
            raise AssertionError(url)
        row=recovery.official_record(recovery.FILM,fetch)
        self.assertEqual(row['evidence']['chosen_derivative']['height'],480)
        self.assertEqual(binary_limit(row),160*1024*1024)
        changed=copy.deepcopy(row);changed['evidence']['file_title']='Different film'
        self.assertEqual(binary_limit(changed),120*1024*1024)
    def catalogue(self):return dict(items=CATALOGUE['items']+[FILM,PHOTO])
    def test_observed_overlong_plan_becomes_native_valid_with_relevant_used_visuals(self):
        original=copy.deepcopy(OBSERVED)
        with self.assertRaisesRegex(common.Failure,'shape_invalid'):common.validate_plan(original)
        result=recovery.curated(original,self.catalogue(),FILM,PHOTO)
        self.assertEqual(original,OBSERVED)
        self.assertEqual(len(result['segments']),29)
        self.assertLessEqual(len(result['assets']),24)
        self.assertGreaterEqual(len(result['assets']),18)
        self.assertEqual({s['asset'] for s in result['segments']},set(range(len(result['assets']))))
        self.assertEqual(sum(a['type']=='video' for a in result['assets']),2)
        narration=' '.join(s['narration'] for s in result['segments'])
        for wrong in ('quarter of a million','bring back five crewmen','astronauts stood','years of science'):
            self.assertNotIn(wrong,narration)
        self.assertIn('Weitz stood',narration)
        self.assertIn('no exterior movie',narration)
        self.assertEqual(result['research'],original['research'])
        self.assertNotIn('approval',result)
        common.validate_plan(result)
    def test_unoffered_resource_still_blocks(self):
        with self.assertRaisesRegex(RuntimeError,'media_not_offered'):
            recovery.curated(OBSERVED,CATALOGUE,FILM,PHOTO)
    def test_other_jobs_are_unchanged_without_io(self):
        with patch.object(recovery,'official_record',side_effect=AssertionError('network')):
            self.assertIs(recovery.prepare(Path('/missing/another-job'),OBSERVED,{},lambda:None),OBSERVED)
    def test_changed_original_or_existing_artifact_cannot_be_rewritten(self):
        with tempfile.TemporaryDirectory() as parent:
            job=Path(parent)/recovery.JOB;job.mkdir()
            task=dict(channel='stunning-revelations',topic='Skylab: 1973')
            changed=copy.deepcopy(OBSERVED);changed['title']='Changed'
            with self.assertRaisesRegex(RuntimeError,'original_plan_changed'):
                recovery.prepare(job,changed,task,lambda:None)
            (job/'video.mp4').write_bytes(b'original')
            with self.assertRaisesRegex(RuntimeError,'existing_artifact'):
                recovery.prepare(job,OBSERVED,task,lambda:None)
    def test_actual_official_derivative_and_explicit_license_required(self):
        def payload(license='Public domain',url='https://upload.wikimedia.org/actual.360p.vp9.webm'):
            return dict(query=dict(pages={'1':dict(pageid=1,title=recovery.FILM,videoinfo=[dict(
                descriptionurl='https://commons.wikimedia.org/wiki/File:actual',size=417478291,
                extmetadata=dict(LicenseShortName={'value':license},Artist={'value':'NASA'}),
                derivatives=[dict(src=url,height=360,type='video/webm',bandwidth=469000)])])}))
        row=recovery.official_record(recovery.FILM,lambda *args:json.dumps(payload()).encode())
        self.assertEqual(row['url'],'https://upload.wikimedia.org/actual.360p.vp9.webm')
        self.assertEqual(row['source_url'],'https://commons.wikimedia.org/?curid=1')
        self.assertIsNone(row['size'])
        actual=payload(url='//upload.wikimedia.org/actual.360p.vp9.webm')
        actual['query']['pages']['1']['videoinfo'][0]['derivatives'][0]['height']='360'
        row=recovery.official_record(recovery.FILM,lambda *args:json.dumps(actual).encode())
        self.assertTrue(row['url'].startswith('https://upload.wikimedia.org/'))
        for value in (payload('All rights reserved'),payload(url='https://unverified.example/clip.webm')):
            with self.assertRaisesRegex(RuntimeError,'official_media_unavailable'):
                recovery.official_record(recovery.FILM,lambda *args:json.dumps(value).encode())

if __name__=='__main__':unittest.main()
