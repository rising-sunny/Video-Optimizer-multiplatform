import copy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import documentary_common as common
import workflow_documentary_brief as brief

TASK=dict(channel='stunning-revelations',topic='Skylab: The two-stage rescue of 1973',minutes=10)

class Evidence(unittest.TestCase):
    def modules(self,images=20,clips=3,available=3):
        sources=types.ModuleType('documentary_sources')
        seen=[]
        def fetch(folder,url,**kw):
            seen.append(url)
            return dict(state='available' if len(seen)<=available else 'unavailable',url=url,content='actual retrieved record')
        sources.fetch_source=fetch
        catalog=types.ModuleType('documentary_catalog');catalog.VERSION='real-catalog-version'
        class Catalog:
            def __init__(self,*a):self.calls=[]
            def attempt(self,provider,query,fn):self.calls.append((provider,query));fn()
            def archive(self,query):pass
            def commons(self,query):pass
            def result(self):return dict(version=catalog.VERSION,queries=self.calls,items=[
                dict(id='M'+format(i,'016x'),type='image' if i<images else 'video') for i in range(images+clips)])
        catalog.Catalog=Catalog
        media=types.ModuleType('documentary_media');media.fetch=lambda *a,**k:None
        return {'documentary_sources':sources,'documentary_catalog':catalog,'documentary_media':media},seen
    def test_other_topics_do_not_fetch_or_change_existing_jobs(self):
        task=dict(TASK,topic='Operation Chrome Dome in 1961')
        self.assertIsNone(brief.prepare(Path('/missing'),task));self.assertEqual(brief.brief(task),'')
        plan={};self.assertIs(brief.validate(plan,{},task),plan)
    def test_fetches_actual_primary_evidence_and_discovers_moving_sources_first(self):
        modules,seen=self.modules()
        with tempfile.TemporaryDirectory() as name,patch.dict(sys.modules,modules):
            folder=Path(name);result=brief.prepare(folder,TASK)
            catalog=common.read(folder/'media-catalog.json');proof=common.read(folder/'production-brief-v53.json')
            self.assertEqual(set(result),set(brief.SOURCES));self.assertEqual(seen,list(brief.SOURCES))
            self.assertEqual([x[0] for x in catalog['queries'][:3]],['internet_archive']*3)
            self.assertEqual(proof['offered_photographs'],20);self.assertEqual(proof['offered_video_sources'],3)
            self.assertTrue(proof['original_model_limits_preserved'])
    def test_insufficient_primary_sources_blocks_before_planning(self):
        modules,_=self.modules(available=1)
        with tempfile.TemporaryDirectory() as name,patch.dict(sys.modules,modules),self.assertRaisesRegex(common.Failure,'primary_evidence_missing'):
            brief.prepare(Path(name),TASK)
    def test_weak_catalog_does_not_silently_fall_back_to_repetitive_images_only(self):
        for images,clips in [(20,1),(12,5),(14,2)]:
            modules,_=self.modules(images=images,clips=clips)
            with self.subTest(images=images,clips=clips),tempfile.TemporaryDirectory() as name,patch.dict(sys.modules,modules),self.assertRaisesRegex(common.Failure,'archive_variety_missing'):
                brief.prepare(Path(name),TASK)

class Selection(unittest.TestCase):
    def test_source_alias_requires_actual_api_page_id_and_preserves_provenance(self):
        canonical='https://commons.wikimedia.org/wiki/File:Verified.jpg'
        row=dict(id='old',provider='commons',source_url=canonical,url='https://upload.wikimedia.org/Verified.jpg',
            license_url=canonical,author='NASA',evidence={'file_title':'File:Verified.jpg'})
        catalog={'items':[row]};brief.compact_sources(catalog,{})
        self.assertEqual(row['source_url'],canonical)
        brief.compact_sources(catalog,{'File:Verified.jpg':123})
        self.assertEqual(row['source_url'],'https://commons.wikimedia.org/?curid=123')
        self.assertEqual(row['evidence']['canonical_source_url'],canonical)
        self.assertEqual(row['author'],'NASA');self.assertRegex(row['id'],r'^M[a-f0-9]{16}$')
    def fixture(self):
        rows=[dict(id='M'+format(i,'016x'),type='image' if i<16 else 'video') for i in range(18)]
        plan=dict(title=brief.TITLE,assets=[dict(media_ids=[r['id']]) for r in rows],segments=[dict(asset=i) for i in range(18)])
        return plan,dict(items=rows)
    def test_all_distinct_selected_resources_are_actually_referenced(self):
        plan,catalog=self.fixture();before=copy.deepcopy(plan)
        self.assertIs(brief.validate(plan,catalog,TASK),plan);self.assertEqual(plan,before)
    def test_duplicate_unused_or_missing_moving_source_is_rejected(self):
        for change in ('duplicate','unused','one_video','title'):
            plan,catalog=self.fixture()
            if change=='duplicate':plan['assets'][1]['media_ids']=plan['assets'][0]['media_ids']
            if change=='unused':plan['segments'].pop()
            if change=='one_video':catalog['items'][-1]['type']='image'
            if change=='title':plan['title']='Unrelated title'
            with self.subTest(change=change),self.assertRaises(common.Failure):brief.validate(plan,catalog,TASK)
    def test_new_module_is_frozen_with_other_documentary_sources(self):
        self.assertIn('workflow_documentary_brief.py',common.MODULES)

if __name__=='__main__':unittest.main()
