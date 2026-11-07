from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import patch,Mock
import workflow_jobs as jobs

class Resume(unittest.TestCase):
    def test_narration_base_reaches_real_quality_stage_without_fake_frame_approval(self):
        with tempfile.TemporaryDirectory() as parent:
            folder=Path(parent);(folder/'video.mp4').write_bytes(b'base')
            worker=types.ModuleType('documentary_worker')
            worker.dependencies=Mock(return_value={});worker.calibrate=Mock(return_value={})
            worker.quality=Mock();worker.approve=Mock()
            common=types.ModuleType('documentary_common');common.MODULES=()
            task={'horizontal_style':'documentary-catarsis-v31'}
            with patch.dict(sys.modules,{'documentary_worker':worker,'documentary_common':common}),patch.object(jobs.c,'read',return_value={'passed':True,'video_sha256':'hash'}),patch.object(jobs.c,'digest',return_value='hash'):
                jobs.run_documentary(folder,task,'existing-job',lambda:None)
            worker.quality.assert_called_once()
            self.assertEqual(worker.quality.call_args.args[-1],[])
            worker.approve.assert_called_once()
    def test_other_formats_still_require_saved_sheets(self):
        with tempfile.TemporaryDirectory() as parent:
            folder=Path(parent);(folder/'video.mp4').write_bytes(b'base')
            worker=types.ModuleType('documentary_worker');worker.dependencies=Mock(return_value={});worker.calibrate=Mock(return_value={});worker.quality=Mock()
            common=types.ModuleType('documentary_common');common.MODULES=()
            with patch.dict(sys.modules,{'documentary_worker':worker,'documentary_common':common}),patch.object(jobs.c,'read',return_value={'passed':True,'video_sha256':'hash'}),patch.object(jobs.c,'digest',return_value='hash'),self.assertRaisesRegex(RuntimeError,'saved_review_frames_missing'):
                jobs.run_documentary(folder,{},'existing-job',lambda:None)
            worker.quality.assert_not_called()
    def test_failed_quality_cannot_reach_approval(self):
        with tempfile.TemporaryDirectory() as parent:
            folder=Path(parent);(folder/'video.mp4').write_bytes(b'base')
            worker=types.ModuleType('documentary_worker');worker.dependencies=Mock(return_value={});worker.calibrate=Mock(return_value={})
            worker.quality=Mock(side_effect=RuntimeError('actual_review_failed'));worker.approve=Mock()
            common=types.ModuleType('documentary_common');common.MODULES=()
            with patch.dict(sys.modules,{'documentary_worker':worker,'documentary_common':common}),patch.object(jobs.c,'read',return_value={'passed':True,'video_sha256':'hash'}),patch.object(jobs.c,'digest',return_value='hash'),self.assertRaisesRegex(RuntimeError,'actual_review_failed'):
                jobs.run_documentary(folder,{'horizontal_style':'documentary-catarsis-v31'},'existing-job',lambda:None)
            worker.approve.assert_not_called()

if __name__=='__main__':unittest.main()
