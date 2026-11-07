import json
from pathlib import Path
import tempfile
import unittest
import workflow_inputs

class ReviewDetails(unittest.TestCase):
    def test_original_positive_fields_and_provider_answer_are_exposed_without_inference(self):
        with tempfile.TemporaryDirectory() as name:
            job=Path(name)
            value=dict(approved=False,checks={'text_readable':True},findings=[],recommendation='block',platform_policy_checks={'youtube':{'copyright_and_music':True}})
            (job/'visual-review.json').write_text(json.dumps(value))
            raw='{"approved":true,"visual_platform_checks":{"youtube":{"community_guidelines":true}}}'
            rows=[dict(type='item.completed',item=dict(type='agent_message',text=raw)),dict(type='turn.completed')]
            (job/'visual-review-events.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            result=workflow_inputs.assessment_details(job)
            self.assertEqual(result['visual-review.json'],value)
            self.assertEqual(result['provider_visual']['original_response'],raw)
            self.assertTrue(result['provider_visual']['completed']);self.assertFalse(result['provider_visual']['failed'])
            self.assertEqual(json.loads((job/'visual-review.json').read_text()),value)
    def test_no_review_files_is_read_only_and_empty(self):
        with tempfile.TemporaryDirectory() as name:
            job=Path(name);self.assertEqual(workflow_inputs.assessment_details(job),{});self.assertEqual(list(job.iterdir()),[])

if __name__=='__main__':unittest.main()
