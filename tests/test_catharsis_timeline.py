"""Regressions for planning before importing files and incomplete scene assignments."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from catharsis import catharsis_editor as ce
from catharsis.catharsis_timeline import assignment_summary, media_slots, plan_timings, slot_value


class TimelinePlanTest(unittest.TestCase):
    def test_plan_without_files_has_variable_durations_and_all_visual_slots(self):
        project = ce.normalize_project({"media": [], "seconds": 40,
                                        "cards": {"lines": ["A date", "A decision", "A consequence"]}})
        before = copy.deepcopy(project)
        with patch.object(ce, "media_info", side_effect=AssertionError("No files to probe")):
            sequence = ce.auto_sequence(project)
        self.assertEqual(project, before)
        self.assertGreater(len(set(s["seconds"] for s in sequence)), 3)
        self.assertTrue({"card", "media", "double", "split"} <= {s["kind"] for s in sequence})
        self.assertTrue(all(slot_value(s, slot) is None for s in sequence for slot in media_slots(s)))
        self.assertEqual(sequence, json.loads(json.dumps(sequence)))
        info = assignment_summary(sequence, [])
        self.assertEqual(len(info["pending"]), info["visual"])
        self.assertGreater(info["slots"], info["visual"])

    def test_planning_option_preserves_legacy_auto_assignment(self):
        project = ce.normalize_project({"media": [{"file": "example.png"}]})
        assigned = ce.auto_sequence(project)
        manual = ce.auto_sequence(project, assign_media=False)
        self.assertTrue(all(slot_value(s, sl) == 0 for s in assigned for sl in media_slots(s)))
        self.assertTrue(all(slot_value(s, sl) is None for s in manual for sl in media_slots(s)))

    def test_summary_counts_scenes_and_composite_slots_and_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            present = Path(folder) / "present.png"
            present.touch()
            media = [{"file": str(present)}, {"file": str(present.with_name("missing.png"))}]
            sequence = [{"kind": "card"}, {"kind": "color"}, {"kind": "media", "media": 0},
                        {"kind": "double", "media": 0, "media2": None},
                        {"kind": "split", "medias": [0, 1, None]}]
            info = assignment_summary(sequence, media)
            self.assertEqual((info["total"], info["visual"], info["complete"], info["slots"], info["missing"]),
                             (5, 3, 1, 6, 3))
            self.assertEqual(set(info["pending"]), {3, 4})

    def test_missing_reference_cannot_silently_wrap_to_another_file(self):
        project = ce.normalize_project({"media": [{"file": "example.png"}]})
        for spec in ({"kind": "media", "media": None}, {"kind": "media", "media": 2},
                     {"kind": "double", "media": 0, "media2": None},
                     {"kind": "split", "medias": [0, None, 0]}):
            with self.subTest(spec=spec), self.assertRaisesRegex(ValueError, "Escena 1: falta asignar"):
                ce.build_shots(project, [dict(spec, seconds=1)])

    def test_display_times_follow_render_frame_rounding(self):
        sequence = [{"kind": "color", "color": "black", "seconds": s} for s in (.11, .235, .067)]
        timings = plan_timings(sequence, ce.FPS)
        with patch.object(ce, "limit_flashes", side_effect=lambda shots: shots):
            shots, marks = ce.build_shots(ce.normalize_project({"media": []}), sequence)
        frame = 0
        for shot, (start, end) in zip(shots, timings):
            self.assertEqual(round(start * ce.FPS), frame)
            frame += shot.frames
            self.assertEqual(round(end * ce.FPS), frame)
        self.assertEqual(timings[-1][1], marks["end"])


if __name__ == "__main__":
    unittest.main()
