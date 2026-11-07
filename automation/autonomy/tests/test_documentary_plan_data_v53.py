import json
from pathlib import Path
import tempfile
import unittest
import workflow_inputs as w

class SavedPlan(unittest.TestCase):
    def test_exposes_only_bounded_saved_editorial_fields_without_validating_shape(self):
        with tempfile.TemporaryDirectory() as name:
            job=Path(name)/'manual-documentary'/'job'
            job.mkdir(parents=True)
            plan=dict(title='Skylab',segments=[dict(narration='Saved words',asset=0)],assets=[],
                private_configuration='should not be exported',description='https://example.test/?token=secret')
            path=job/'editorial-plan.json';path.write_text(json.dumps(plan));before=path.read_bytes()
            result=w.documentary_plan_data(job)
            self.assertEqual(result['segments'],plan['segments']);self.assertNotIn('private_configuration',result)
            self.assertNotIn('secret',result['description']);self.assertEqual(path.read_bytes(),before)
    def test_ignores_other_scopes_missing_and_oversize_files(self):
        with tempfile.TemporaryDirectory() as name:
            job=Path(name)/'manual-documentary'/'job';job.mkdir(parents=True)
            self.assertEqual(w.documentary_plan_data(job),{})
            (job/'editorial-plan.json').write_text('x'*60001)
            self.assertEqual(w.documentary_plan_data(job),{})
            other=Path(name)/'manual-catarsis'/'job';other.mkdir(parents=True)
            (other/'editorial-plan.json').write_text('{}')
            self.assertEqual(w.documentary_plan_data(other),{})

if __name__=='__main__':unittest.main()
