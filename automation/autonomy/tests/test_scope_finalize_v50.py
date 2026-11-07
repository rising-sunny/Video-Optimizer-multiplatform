import copy
import sys
import types
import unittest
from unittest.mock import patch
import workflow_style_finalize as scope

VISUAL={'images_inspected','text_readable','framing','motion_or_intentional_stills','context_labels','intentional_black_and_static_only','thumbnail'}
PLATFORMS=('youtube','facebook','instagram')

class Scope(unittest.TestCase):
    def setUp(self):
        self.raw=dict(approved=False,checks={k:True for k in VISUAL},findings=[],suggestions=[scope.LIMITATION],visual_platform_checks={p:dict(community_guidelines=True,non_misleading_context=True) for p in PLATFORMS})
        self.qa=dict(technical_checks_passed=True,sha256=scope.VIDEO,checks={k:True for k in ('full_decode','audible_no_clipping','av_duration','duration')})
        fake=types.ModuleType('deepseek_review');fake.VISUAL=VISUAL;fake.PLATFORMS=PLATFORMS
        p=patch.dict(sys.modules,{'deepseek_review':fake});p.start();self.addCleanup(p.stop)
    def test_scope_resolution_is_explicitly_controller_owned_and_preserves_raw_false(self):
        before=copy.deepcopy(self.raw);decision=scope.resolved(self.raw,self.qa)
        self.assertEqual(self.raw,before);self.assertFalse(self.raw['approved']);self.assertTrue(decision['approved'])
        self.assertFalse(decision['resolution']['original_provider_approved']);self.assertEqual(decision['resolution']['new_visual_ai_requests'],0)
        self.assertEqual(decision['checks'],self.raw['checks']);self.assertEqual(decision['visual_platform_checks'],self.raw['visual_platform_checks'])
    def test_failed_or_missing_visual_or_platform_check_never_qualifies(self):
        for change in ('failed_visual','missing_visual','failed_platform','missing_platform'):
            raw=copy.deepcopy(self.raw)
            if change=='failed_visual':raw['checks']['text_readable']=False
            if change=='missing_visual':raw['checks'].pop('images_inspected')
            if change=='failed_platform':raw['visual_platform_checks']['youtube']['community_guidelines']=False
            if change=='missing_platform':raw.pop('visual_platform_checks')
            with self.subTest(change=change),self.assertRaisesRegex(RuntimeError,'not_unanimous'):scope.resolved(raw,self.qa)
    def test_any_real_finding_or_other_limitation_stays_blocked(self):
        for field,value in [('findings',[dict(severity='blocking',message='actual defect')]),('suggestions',['Something else is missing'])]:
            raw=copy.deepcopy(self.raw);raw[field]=value
            with self.assertRaisesRegex(RuntimeError,'not_unanimous'):scope.resolved(raw,self.qa)
    def test_wrong_video_or_failed_full_av_check_stays_blocked(self):
        for field in ('full_decode','audible_no_clipping','av_duration','duration'):
            qa=copy.deepcopy(self.qa);qa['checks'][field]=False
            with self.assertRaisesRegex(RuntimeError,'not_unanimous'):scope.resolved(self.raw,qa)
        qa=dict(self.qa,sha256='another video')
        with self.assertRaisesRegex(RuntimeError,'not_unanimous'):scope.resolved(self.raw,qa)

if __name__=='__main__':unittest.main()
