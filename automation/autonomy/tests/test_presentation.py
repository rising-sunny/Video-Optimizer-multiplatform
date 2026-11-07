import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'modules'))
import workflow_common as c
import workflow_presentation as presentation
import workflow_readable as readable


class Display(unittest.TestCase):
    def test_long_reviewed_cards_fit_pixel_bounds_without_rewriting(self):
        samples=['Her wartime laboratory had wheels.',
            'The War Ministry asked her about training radiographers and existing X-ray apparatus.',
            'She worked to send them forward, with Irène and the medical teams.']
        for text in samples:
            font,lines,size,gap,height=readable.layout(text)
            self.assertEqual(' '.join(lines),' '.join(text.split()))
            self.assertGreaterEqual(size,96);self.assertLessEqual(height,870)
            self.assertTrue(all(font.getlength(line)<=920 for line in lines))
            self.assertEqual(readable.card(text).size,(1080,1920))

    def test_labels_are_large_and_fit_lower_panel(self):
        text='Marie Curie, photograph by Henri Manuel, c. 1920'
        font,lines,size,gap,height=readable.layout(text,caption=True)
        self.assertGreaterEqual(size,64);self.assertLessEqual(height,410)
        self.assertEqual(' '.join(lines),text)
        self.assertEqual(readable.caption(text).getbbox(),(0,1380,1080,1851))

    def test_renderer_labels_every_source_but_keeps_stored_plan_and_native_functions(self):
        editor=types.ModuleType('presentation_test_editor')
        exec('def text_card(*a):pass\ndef overlay_layer(*a):pass\ndef build_shots(project,sequence):\n return sequence',editor.__dict__)
        originals=(editor.text_card,editor.overlay_layer,editor.build_shots)
        plan=dict(assets=[dict(label='Marie Curie, 1903')],project=dict(sequence=[dict(kind='media',media=0,text='Existing shorter label'),dict(kind='card',text='Exact fact')]))
        before=copy.deepcopy(plan)
        with readable.renderer(editor,plan):
            rendered=editor.build_shots({},plan['project']['sequence'])
            self.assertEqual(rendered[0]['kind'],'overlay');self.assertEqual(rendered[0]['text'],'Marie Curie, 1903')
            self.assertEqual(rendered[1],plan['project']['sequence'][1])
        self.assertEqual(before,plan);self.assertEqual(originals,(editor.text_card,editor.overlay_layer,editor.build_shots))


class Eligibility(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ident='a'*32;self.channel=c.CHANNELS[0]
        self.state=self.root/'state/catarsis'/self.ident;self.state.mkdir(parents=True)
        self.job=self.root/'runtime/manual-catarsis'/self.ident/self.channel;self.job.mkdir(parents=True)
        self.ledger=self.root/'ledger';self.ledger.mkdir()
        c.write(self.state/'request.json',dict(publication_allowed=False,topics={self.channel:'original topic'}))
        c.write(self.state/'status.json',dict(state='blocked'))
        (self.job/'video.mp4').write_bytes(b'original video');sha=c.digest(self.job/'video.mp4')
        c.write(self.job/'qa.json',dict(technical_checks_passed=True,sha256=sha))
        c.write(self.job/'visual-review.json',dict(approved=False,video_sha256=sha,checks=dict(text_readable=False,context_labels=False,images_inspected=True,framing=True)))
        c.write(self.job/'deepseek-text-review.json',dict(approved=True,checks=dict(facts_supported=True,licenses_and_full_credits=True)))
        c.write(self.ledger/'budget.json',dict(pending=None,counts=dict(chat=8,invocations=4)))
        (self.ledger/'vision-old.claimed').write_text('preserved')
        c.write(self.ledger/'handoff-positive.json',dict(approved=True))
        sequence=[dict(kind='card',text='Exact approved sentence.'),dict(kind='media',media=0)]
        c.write(self.job/'editorial-plan.json',dict(project=dict(sequence=sequence),assets=[dict(label='Marie Curie, 1903')]))
        c.write(self.job/'project.json',dict(sequence=sequence))
        patches=[patch.object(c,'STATE',self.root/'state'),patch.object(c,'RUNTIME',self.root/'runtime'),
            patch.object(c,'ledger',return_value=self.ledger),patch.object(presentation,'text_cache',return_value=self.ledger/'handoff-positive.json'),
            patch.dict(sys.modules,{'generation_worker':types.SimpleNamespace(preflight=lambda:None),
                'catarsis_selection':types.SimpleNamespace(task_channels=lambda task:(self.channel,))})]
        for p in patches:p.start();self.addCleanup(p.stop)

    def test_full_text_budget_is_not_reset_or_used_for_display_revision(self):
        before=c.tree(self.root);item=presentation.inspect(self.ident)
        self.assertEqual(item['budget']['counts'],dict(chat=8,invocations=4))
        self.assertEqual(before,c.tree(self.root));self.assertEqual(item['failed_checks'],['context_labels','text_readable'])

    def test_observer_only_queues_an_eligible_presentation_correction(self):
        import workflow_jobs as jobs
        self.assertTrue(jobs.retry_allowed(self.job,'visual_or_editorial_review_failed'))
        (self.state/(presentation.NAME+'.claim')).write_text('used')
        self.assertFalse(jobs.retry_allowed(self.job,'visual_or_editorial_review_failed'))

    def test_factual_or_framing_failure_cannot_use_this_revision(self):
        path=self.job/'visual-review.json';data=c.read(path);data['checks']['framing']=False;c.write(path,data)
        with self.assertRaisesRegex(RuntimeError,'display_only'):presentation.inspect(self.ident)

    def test_old_negative_review_and_video_must_match_actual_qa(self):
        (self.job/'video.mp4').write_bytes(b'changed without QA')
        with self.assertRaisesRegex(RuntimeError,'exact_video_qa'):presentation.inspect(self.ident)

    def test_no_additional_visual_allowance_is_granted(self):
        (self.ledger/'vision-second.claimed').write_text('preserved')
        with self.assertRaisesRegex(RuntimeError,'visual_budget_exhausted'):presentation.inspect(self.ident)
        self.assertEqual(len(list(self.ledger.glob('vision-*.claimed'))),2)

    def test_local_revision_claim_is_never_replayed(self):
        (self.state/(presentation.NAME+'.claim')).write_text('used')
        with self.assertRaisesRegex(RuntimeError,'already_attempted'):presentation.inspect(self.ident)

    def test_uncertain_provider_request_does_not_resume(self):
        c.write(self.ledger/'budget.json',dict(pending=dict(kind='chat'),counts=dict(chat=8,invocations=4)))
        with self.assertRaisesRegex(RuntimeError,'ambiguous_provider_request'):presentation.inspect(self.ident)


if __name__=='__main__':unittest.main()
