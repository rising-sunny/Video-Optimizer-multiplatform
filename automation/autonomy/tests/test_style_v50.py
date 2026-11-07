import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import workflow_readable as readable
import workflow_style_revision as revision


def intervals(sequence):
    at=0.;rows=[]
    for scene in sequence:
        end=at+scene['seconds']
        if scene.get('kind')!='card':rows.append((round(at*30),round(end*30),scene))
        at=end
    return rows


class Presentation(unittest.TestCase):
    def setUp(self):
        self.project=json.loads(Path(__file__).with_name('curie-final-project.json').read_text())

    def test_curie_actual_text_time_and_archive_intervals_are_preserved(self):
        sequence=self.project['sequence'];before=copy.deepcopy(sequence)
        display=readable.sequence_for_display(sequence)
        self.assertEqual(sequence,before)
        self.assertEqual(intervals(sequence),intervals(display))
        self.assertEqual(round(sum(s['seconds'] for s in display)*30),1650)
        old=' '.join(s['text'] for s in sequence if s['kind']=='card').split()
        new=' '.join(s['text'] for s in display if s['kind']=='card').split()
        self.assertEqual(old,new)
        cards=[s for s in display if s['kind']=='card']
        self.assertEqual(len(cards),11)
        self.assertTrue(all(s['kinetic'] for s in cards))
        self.assertEqual({s['style'] for s in cards},{'left','center'})
        self.assertTrue(all(len(s['text'].split())/s['seconds']<=3.5 for s in cards))

    def test_actual_cards_use_serif_pixel_fitting_and_visible_safe_glyphs(self):
        from PIL import ImageChops,Image
        for scene in readable.sequence_for_display(self.project['sequence']):
            if scene['kind']!='card':continue
            font,wrapped,size,gap,height=readable.layout(scene['text'],style=scene['style'])
            self.assertIn('Serif',font.getname()[0]);self.assertEqual(font.getname()[1],'Bold')
            self.assertLessEqual(len(wrapped),3)
            image=readable.card(scene['text'],scene['style'])
            box=ImageChops.difference(image,Image.new('RGB',image.size)).getbbox()
            self.assertIsNotNone(box);self.assertGreaterEqual(box[0],70)
            self.assertLessEqual(box[2],1010);self.assertGreaterEqual(box[1],300)
            self.assertLessEqual(box[3],1400)

    def test_variants_are_not_silently_replaced(self):
        center=readable.card('Science reaches people.','center')
        left=readable.card('Science reaches people.','left')
        self.assertNotEqual(center.tobytes(),left.tobytes())
        self.assertEqual(readable.card('Science.','invert').getpixel((0,0)),(242,240,234))
        self.assertEqual(readable.card('Science.','red').getpixel((0,0)),(186,14,22))
        self.assertNotEqual(readable.card('Science.','word').tobytes(),readable.card('Science.').tobytes())
        with self.assertRaisesRegex(RuntimeError,'style_unknown'):readable.card('Text','unknown')

    def test_short_or_explicit_word_cards_preserve_their_text_and_variant(self):
        sequence=[dict(kind='card',seconds=.8,text='SCIENCE',style='word'),dict(kind='color',seconds=.9,tag='break')]
        display=readable.sequence_for_display(sequence)
        self.assertEqual(display[0]['style'],'word');self.assertEqual(display[0]['text'],'SCIENCE')
        self.assertEqual(display[1],sequence[1])

    def test_caption_remains_visible_beneath_the_archival_panel(self):
        from PIL import ImageChops,Image
        image=readable.caption('Marie and Pierre Curie in their laboratory, 1896')
        alpha=image.getchannel('A');self.assertEqual(alpha.getpixel((540,1000)),0)
        self.assertGreater(alpha.getpixel((540,1450)),240)
        self.assertGreater(sum(x>220 for x in image.convert('L').crop((0,1380,1080,1850)).tobytes()),1000)

    def test_actual_private_render_namespace_gets_crisp_entries_and_is_restored(self):
        from PIL import Image
        native={}
        exec('def _kinetic(image,index,echo):\n raise AssertionError("old blurred entrance used")\ndef render():\n return _kinetic\n',native)
        original_render=native['render'];old_kinetic=native['_kinetic']
        def style_wrapper(original_render):
            def render():return original_render()
            return render
        editor=types.ModuleType('style_editor')
        exec('def text_card(*args):pass\ndef overlay_layer(*args):pass\ndef build_shots(project,sequence):return sequence\n',editor.__dict__)
        editor.render=style_wrapper(original_render);editor._kinetic=old_kinetic
        scales=[]
        def zoom(image,scale):scales.append(scale);return image
        editor._zoomed=zoom
        image=Image.new('RGB',(1080,1920),'white');echo=Image.new('RGB',image.size,'red')
        with readable.renderer(editor,dict(assets=[])):
            kinetic=editor.render()
            for index in range(6):self.assertEqual(kinetic(image,index,echo).tobytes(),image.tobytes())
            self.assertAlmostEqual(scales[0],1.035);self.assertEqual(scales[-1],1)
            self.assertTrue(all(1<=s<=1.035 for s in scales))
        self.assertIs(editor._kinetic,old_kinetic);self.assertIs(editor.render(),old_kinetic)


class RevisionScope(unittest.TestCase):
    def test_only_the_exact_new_user_revision_request_matches(self):
        request=dict(operation='generation_start_single',request_id=revision.REQUEST_ID,channel=revision.CHANNEL,topic=revision.TOPIC)
        self.assertTrue(revision.matches(request))
        for key,value in (('channel','stunning-revelations'),('topic','different subject'),('operation','generation_start')):
            changed=dict(request);changed[key]=value;self.assertFalse(revision.matches(changed))
        self.assertFalse(revision.matches(dict(request,publication_allowed=True)))

    def test_review_uses_new_bound_claim_root_without_replacing_original(self):
        original_root=Path('/original-ledger')
        def workspace(folder):return original_root
        namespace={'workspace':workspace}
        exec('def visual(folder,images,documentary=False,quota_recovery=None):\n return workspace(folder)\n',namespace)
        original=namespace['visual'];fake=types.ModuleType('deepseek_review');fake.visual=original
        job=Path('/the-exact-job');new_root=Path('/new-style-assessment')
        with patch.dict(sys.modules,{'deepseek_review':fake}):
            with revision.revision_vision(job,new_root):
                self.assertEqual(fake.visual(job,['actual-frame.jpg']),new_root)
                with self.assertRaisesRegex(RuntimeError,'one_visual_only'):fake.visual(job,['actual-frame.jpg'])
            self.assertIs(fake.visual,original)
            self.assertEqual(fake.visual(job,[]),original_root)

    def test_review_rejects_another_job_or_a_documentary(self):
        fake=types.ModuleType('deepseek_review')
        def visual(folder,images,documentary=False,quota_recovery=None):return None
        fake.visual=visual
        with patch.dict(sys.modules,{'deepseek_review':fake}):
            with revision.revision_vision(Path('/exact'),Path('/new')):
                with self.assertRaisesRegex(RuntimeError,'one_visual_only'):fake.visual(Path('/wrong'),[])
            with revision.revision_vision(Path('/exact'),Path('/new')):
                with self.assertRaisesRegex(RuntimeError,'one_visual_only'):fake.visual(Path('/exact'),[],documentary=True)

    def test_existing_authorization_is_idempotent_without_generation_or_claim_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/(revision.NAME+'-auth.json')).write_text('{}')
            fake=types.ModuleType('generation_service');fake.denied=lambda code:dict(state='blocked',error_code=code);fake.safe_error=str
            pub=types.ModuleType('publication_service');pub.controls=lambda:{}
            jobs=types.ModuleType('workflow_jobs');jobs.frozen_sources=lambda:{};jobs.PYTHON='/python'
            history=types.ModuleType('history_data');history.timestamp=lambda:'now'
            broker=types.SimpleNamespace(status=lambda ident:dict(state='ready',batch_id=ident))
            request=dict(operation='generation_start_single',request_id=revision.REQUEST_ID,channel=revision.CHANNEL,topic=revision.TOPIC)
            with patch.dict(sys.modules,{'generation_service':fake,'publication_service':pub,'workflow_jobs':jobs,'history_data':history}),patch.object(revision.c,'paths',return_value=(root,root/'job')),patch.object(revision,'inspect',side_effect=AssertionError('must not inspect or rerun')):
                self.assertEqual(revision.start(broker,request),dict(state='ready',batch_id=revision.BATCH))


if __name__=='__main__':unittest.main()
