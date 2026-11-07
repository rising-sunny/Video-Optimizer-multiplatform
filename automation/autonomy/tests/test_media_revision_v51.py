import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import workflow_media_revision as r


def source_plan():
    sequence=[]
    durations=[82,80,115,78,103,81,157,98,128,69,85,153,27,130,122,142]
    cards={0:'Her wartime laboratory had wheels.',4:'Then, in 1914, France went to war.',
        6:'The War Ministry asked her about training radiographers and existing X-ray apparatus.',
        8:'Radiography cars already existed. She did not invent them.',
        11:'She worked to send them forward, with Irène and the medical teams.',
        14:'Science reaching people. That was her actual authority.'}
    for i,frames in enumerate(durations):
        row=dict(kind='card' if i in cards else 'color' if i==12 else 'media',seconds=frames/30,
                 text=cards.get(i,''),act='rise',motion='hold')
        if i==12:row.update(tag='break',act='break')
        sequence.append(row)
    return dict(project=dict(sequence=sequence,style=dict(grain=True,grade=True,vignette=True,bloom=False,sfx=True)),
        metadata={n:{f:'Existing factual paragraph.\n\nOld production notes.'}
                  for n,f in [('youtube','description'),('facebook','description'),('instagram','caption')]},
        music_title='Measured Paces')


def rows():
    return {title.replace('_',' '):dict(commons_title=title,type=kind,credit='Verified institution; Wikimedia Commons')
        for _,title,_,_,kind in r.SLOTS}


class Montage(unittest.TestCase):
    def test_changes_media_not_words_music_or_runtime_and_shows_every_source(self):
        original=source_plan();held=copy.deepcopy(original)
        revised=r.revised_plan(original,rows(),'2026-11-07',r.TOPIC)
        self.assertEqual(original,held)
        before=original['project']['sequence'];after=revised['project']['sequence']
        self.assertEqual([s['text'] for s in before if s['kind']=='card'],[s['text'] for s in after if s['kind']=='card'])
        self.assertEqual(round(sum(s['seconds'] for s in after)*30),1650)
        self.assertEqual(len(after),17)
        self.assertEqual(sum(a['type']=='image' for a in revised['assets']),7)
        self.assertEqual(len(revised['assets']),8)
        self.assertEqual({s['media'] for s in after if 'media' in s},set(range(8)))
        self.assertEqual(revised['music_title'],original['music_title'])
        self.assertEqual(sum(s.get('tag')=='break' and s['seconds']==.9 for s in after),1)
        self.assertEqual(sum(s.get('transition')=='burn' for s in after),3)

    def test_real_clip_excerpts_are_distinct_context_is_always_labelled_and_density_fits(self):
        plan=r.revised_plan(source_plan(),rows(),'2026-11-07',r.TOPIC)
        clips=[s for s in plan['project']['sequence'] if s.get('media')==7]
        self.assertEqual(len(clips),2)
        self.assertEqual(plan['assets'][7]['in'],2)
        self.assertEqual([s.get('offset',0) for s in clips],[0,7])
        for scene in plan['project']['sequence']:
            if scene.get('text'):self.assertLessEqual(len(scene['text'].split())/scene['seconds'],3.5)
            if 'media' in scene:
                self.assertEqual(scene['kind'],'overlay')
                self.assertEqual(scene['text'],plan['assets'][scene['media']]['label'])

    def test_missing_or_mistyped_archive_never_silently_falls_back_to_portraits(self):
        for change in ('missing','type'):
            catalogue=rows();key=r.SLOTS[3][1]
            if change=='missing':catalogue.pop(key)
            else:catalogue[key]['type']='video'
            with self.assertRaisesRegex(RuntimeError,'verified_xray_missing'):
                r.revised_plan(source_plan(),catalogue,'2026-11-07',r.TOPIC)


class Metadata(unittest.TestCase):
    def setUp(self):
        fake=types.ModuleType('documentary_media');fake.clean=lambda value:str(value)
        self.patcher=patch.dict(sys.modules,{'documentary_media':fake});self.patcher.start();self.addCleanup(self.patcher.stop)
        self.page=dict(pageid=123,title='File:Known.jpg',imageinfo=[dict(url='https://upload.wikimedia.org/a/Known.jpg',
            descriptionurl='https://commons.wikimedia.org/wiki/File:Known.jpg',size=100,
            extmetadata=dict(LicenseShortName=dict(value='Public domain'),Artist=dict(value='Actual creator'),Credit=dict(value='Actual collection')))])
    def parse(self,page):return r.official_rows(dict(query=dict(pages={'123':page})))
    def test_preserves_actual_metadata_and_creator(self):
        held=copy.deepcopy(self.page);row=self.parse(self.page)['File:Known.jpg']
        self.assertEqual(self.page,held);self.assertEqual(row['metadata'],self.page['imageinfo'][0])
        self.assertEqual(row['author'],'Actual creator');self.assertEqual(row['collection'],'Actual collection')
        self.assertIn('Actual creator',row['credit']);self.assertEqual(row['pageid'],123)
    def test_rejects_unverified_rights_hosts_size_and_missing_file(self):
        for change in ('rights','url','source','size','missing'):
            page=copy.deepcopy(self.page);info=page['imageinfo'][0]
            if change=='rights':info['extmetadata']['LicenseShortName']['value']='Unknown'
            if change=='url':info['url']='https://upload.wikimedia.org@evil.test/file.jpg'
            if change=='source':info['descriptionurl']='https://evil.test/fake'
            if change=='size':info['size']=25*1024*1024
            if change=='missing':page['pageid']=-1
            self.assertEqual(self.parse(page),{})


class RevisionBoundary(unittest.TestCase):
    def test_requires_exact_single_channel_request(self):
        request=dict(operation='generation_start_single',request_id=r.REQUEST_ID,channel=r.CHANNEL,topic=r.TOPIC)
        self.assertTrue(r.matches(request))
        for key in request:
            changed=dict(request);changed[key]='changed';self.assertFalse(r.matches(changed))

    def test_broker_is_not_launched_until_parent_binding_is_saved_and_enrolled(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);ident='a'*32;state=root/ident;state.mkdir()
            r.c.write(state/'request.json',dict(batch_id=ident))
            calls=[]
            class Broker:
                def index(self):return dict(requests={})
                def status(self,batch):return dict(state='accepted',batch_id=batch)
                def launch(self,work):calls.append(('launched',r.c.read(state/'request.json')))
            broker=Broker();broker.state=root
            def original(broker,request):broker.launch(lambda:None);return dict(state='accepted',batch_id=ident)
            jobs=types.ModuleType('workflow_jobs');jobs.enroll=lambda *a,**k:calls.append(('enrolled',r.c.read(state/'request.json')))
            request=dict(operation='generation_start_single',request_id=r.REQUEST_ID,channel=r.CHANNEL,topic=r.TOPIC)
            with patch.object(r,'inspect_parent',return_value=dict(version=r.VERSION)),patch.dict(sys.modules,{'workflow_jobs':jobs,'generation_service':types.SimpleNamespace(denied=lambda x:dict(error_code=x),safe_error=str)}):
                result=r.start(broker,request,original)
            self.assertEqual(result['batch_id'],ident);self.assertEqual([v[0] for v in calls],['enrolled','launched'])
            self.assertEqual(calls[1][1]['revision_of'],r.PARENT)

    def test_parent_verification_detects_a_counter_or_artifact_change(self):
        binding=dict(version=r.VERSION,batch_id=r.PARENT,video_sha256=r.VIDEO,approval_sha256=r.APPROVAL,files={'editorial-plan.json':'p'},ledger={'budget.json':'b'})
        with tempfile.TemporaryDirectory() as name:
            job=Path(name)
            def digest(path):return {'video.mp4':r.VIDEO,'approval.json':r.APPROVAL,'editorial-plan.json':'p'}[Path(path).name]
            with patch.object(r.c,'paths',return_value=(job,job)),patch.object(r.c,'digest',side_effect=digest),patch.object(r.c,'ledger',return_value=job/'ledger'),patch.object(r.c,'tree',return_value={'budget.json':'changed'}):
                with self.assertRaisesRegex(RuntimeError,'parent_changed'):r.verify_parent(binding)

    def test_new_evidence_review_is_one_call_with_residual_ceiling_and_always_restores_context(self):
        rt=types.ModuleType('deepseek_runtime');rt.LIMITS={'chat':10};rt.MAX_ESTIMATE=.20
        jobs=types.ModuleType('workflow_jobs');jobs.source_delivery=lambda *a:lambda *a:None
        binding=dict(residual_ceiling_usd=.148079)
        editorial=types.SimpleNamespace(external=lambda *a:None,music_evidence=lambda *a:None,prepare_media=lambda *a:None)
        held=dict(editorial.__dict__);old_limits=rt.LIMITS
        with tempfile.TemporaryDirectory() as name:
            job=Path(name)
            with patch.dict(sys.modules,{'deepseek_runtime':rt,'workflow_jobs':jobs}),patch.object(r,'verify_parent'),patch.object(r.c,'ledger',return_value=job):
                with self.assertRaisesRegex(RuntimeError,'simulated'):
                    with r.context(editorial,job,{'media_revision':binding},lambda:None):
                        self.assertEqual(rt.LIMITS,dict(chat=1,search=0,fetch=0,invocations=1,input_tokens=100000,output_tokens=2200))
                        self.assertEqual(rt.MAX_ESTIMATE,.148079)
                        raise RuntimeError('simulated')
            self.assertIs(rt.LIMITS,old_limits);self.assertEqual(rt.MAX_ESTIMATE,.20)
            self.assertEqual(editorial.__dict__,held)


if __name__=='__main__':unittest.main()
