import copy
import json
import tempfile
import unittest
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import channel_profiles as channels
import channel_strategy
import micro_documentary as micro
from microdoc_analytics import normalize, diagnose, compare_pilots


def package():
    hook = 'Britain sent two cruisers into the Pacific. Within hours both ships would sink.'
    opening = hook + ' ' + ' '.join(['Stakes and essential historical orientation.'] * 9)
    thumbs = [{'prompt': f'Cruiser silhouette at dusk, composition {i}', 'text': 'BRITAIN LOST'} for i in range(3)]
    return {'title_variants': ['The Day Britain Lost at Coronel', 'Two Cruisers Entered. Neither Returned.', 'Britain Misjudged the Pacific Battle'],
            'selected_title': 'The Day Britain Lost at Coronel', 'thumbnail_variants': thumbs,
            'selected_thumbnail_concept': thumbs[0], 'hook': hook, 'first_30_seconds': opening,
            'opening_visual': 'One cruiser silhouette in a dark Pacific sea',
            'claims': [{'claim': 'Two British cruisers sank.', 'source': 'Source to review', 'status': 'established_fact'}]}


def script_for(data):
    segments = [{'text': data['hook'], 'visual_prompt': 'Cruiser silhouette'},
                {'text': data['first_30_seconds'][len(data['hook']):].strip(), 'visual_prompt': 'Consequence at sea'}]
    remaining = 540 - sum(len(s['text'].split()) for s in segments)
    for i in range(15):
        count = remaining // (15-i)
        text = f'Event{i} ' + ' '.join(['historical'] * (count-1))
        segments.append({'text': text, 'visual_prompt': 'Evidence image'})
        remaining -= count
    return {'segments': segments}


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def _generate(self, prompt, **kwargs):
        self.calls.append(prompt)
        return json.dumps(next(self.responses))


class MicroTests(unittest.TestCase):
    def tearDown(self):
        channels.select_channel(channels.DEFAULT_CHANNEL)

    def test_truncated_json_regenerates_a_complete_response(self):
        client = MagicMock()
        client._generate.side_effect = ['{"segments":[{"text":"unfinished', json.dumps({'segments': [{'text': 'Complete ending'}]})]
        result = micro._json_generate(client, 'Generate the storyboard')
        self.assertEqual(result['segments'][0]['text'], 'Complete ending')
        self.assertEqual(client._generate.call_count, 2)
        self.assertTrue(client._generate.call_args.kwargs['json_mode'])
        self.assertIn('COMPLETE object', client._generate.call_args.args[0])

    def test_invalid_json_stops_with_a_clear_error(self):
        client = MagicMock()
        client._generate.return_value = '{"unfinished'
        with self.assertRaisesRegex(RuntimeError, 'propuesta guardada se conserva'):
            micro._json_generate(client, 'Generate')
        self.assertEqual(client._generate.call_count, 3)

    def test_groq_json_mode_rejects_token_truncation_and_falls_back(self):
        from groq_client import GroqAiClient
        client = GroqAiClient.__new__(GroqAiClient)
        client.client = MagicMock()
        client.model_cursors = {}
        client._get_models_for_task = lambda task: ['first', 'second']
        truncated = types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason='length', message=types.SimpleNamespace(content='{"unfinished'))])
        complete = types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason='stop', message=types.SimpleNamespace(content='{"complete":true}'))])
        client.client.chat.completions.create.side_effect = [truncated, complete]
        result = client._generate('JSON object', task_type='script_quality', json_mode=True)
        self.assertEqual(json.loads(result), {'complete': True})
        calls = client.client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].kwargs['response_format'], {'type': 'json_object'})
        self.assertEqual(calls[1].kwargs['model'], 'second')

    def test_channel_switch_does_not_modify_legacy_profile(self):
        before = channels.load_profile(channels.DEFAULT_CHANNEL)
        channels.select_channel('stunning-revelations')
        self.assertEqual(channel_strategy.get_channel_name(), 'Stunning Revelations')
        self.assertEqual(channels.token_path().name, 'token_stunning-revelations.json')
        channels.select_channel(channels.DEFAULT_CHANNEL)
        self.assertEqual(channel_strategy.get_channel_strategy(), before)
        self.assertEqual(channels.token_path().name, 'token.json')

    def test_runtime_and_invalid_targets(self):
        self.assertEqual(micro.runtime_plan()['word_budget'], 540)
        self.assertEqual(micro.runtime_plan(270, 140)['word_budget'], 630)
        for value in [60, 400, float('nan')]:
            with self.assertRaises(ValueError):
                micro.runtime_plan(value)

    def test_preflight_rejects_missing_or_misleading_structure(self):
        self.assertEqual(micro.validate_packaging(package()), [])
        for field, value in [('hook', 'Welcome back to the channel.'), ('claims', []), ('title_variants', ['One']), ('first_30_seconds', 'An unrelated opening')]:
            bad = package()
            bad[field] = value
            self.assertTrue(micro.validate_packaging(bad), field)

    def test_approval_is_two_stage_and_reuses_packaging_and_script(self):
        p = package()
        client = FakeClient([p, script_for(p)])
        with tempfile.TemporaryDirectory() as tmp:
            first = micro.build('Coronel', tmp, channel='stunning-revelations', approve=True, client=client)
            self.assertEqual(first['status'], 'awaiting_editorial_review')
            self.assertFalse((Path(tmp) / 'storyboard.json').exists())
            built = micro.build('Coronel', tmp, channel='stunning-revelations', approve=True, client=client)
            self.assertEqual(built['manifest']['script_word_count'], 540)
            self.assertEqual(built['manifest']['estimated_runtime_seconds'], 270)
            self.assertEqual(len(client.calls), 2)
            micro.build('Coronel', tmp, channel='stunning-revelations', approve=True, client=client)
            self.assertEqual(len(client.calls), 2)
            sb = json.loads((Path(tmp) / 'storyboard.json').read_text())
            self.assertEqual(sb['video_format'], '16:9')
            self.assertEqual(sb['channel_profile'], 'stunning-revelations')
            self.assertTrue(sb['segments'][0]['visual_prompt'].startswith(p['opening_visual']))
            with self.assertRaises(ValueError):
                micro.build('Coronel', tmp, channel=channels.DEFAULT_CHANNEL, approve=True, client=client)

    def test_invalid_script_revised_without_dropping_ending(self):
        p = package()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = micro.prepare('Coronel', tmp, client=FakeClient([p]))
            valid = script_for(p)
            bad = copy.deepcopy(valid)
            bad['segments'] = bad['segments'][:4]
            client = FakeClient([bad, valid])
            sb = micro.make_storyboard(manifest, client)
            self.assertEqual(sb['segments'][-1]['text'], valid['segments'][-1]['text'])
            self.assertEqual(len(client.calls), 2)

    def test_approved_opening_is_inserted_without_model_copying_it(self):
        p = package()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = micro.prepare('Coronel', tmp, client=FakeClient([p]))
            body = script_for(p)
            body['segments'] = body['segments'][2:]
            storyboard = micro.make_storyboard(manifest, FakeClient([body]), diagnostics_dir=tmp)
            self.assertTrue(storyboard['script'].startswith(p['first_30_seconds']))
            self.assertEqual(len(storyboard['script'].split()), 540)
            self.assertEqual(storyboard['script'].count(p['hook']), 1)
            self.assertTrue(json.loads((Path(tmp) / 'script_preflight.json').read_text())['passed'])

    def test_failed_script_reports_reasons_instead_of_truncated_draft(self):
        p = package()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = micro.prepare('Coronel', tmp, client=FakeClient([p]))
            too_short = {'segments': [{'text': 'A short ending.', 'visual_prompt': 'Historical evidence'}]}
            with self.assertRaisesRegex(ValueError, 'Duración estimada') as error:
                micro.make_storyboard(manifest, FakeClient([too_short] * 3), diagnostics_dir=tmp)
            self.assertNotIn('Revise this draft', str(error.exception))
            diagnostic = json.loads((Path(tmp) / 'script_preflight.json').read_text())
            self.assertFalse(diagnostic['passed'])
            self.assertEqual(len(diagnostic['attempts']), 3)

    def test_refuses_overwriting_an_unrelated_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'project.json').write_text('{}')
            with self.assertRaises(ValueError):
                micro.build('Topic', tmp, client=FakeClient([]))

    def test_analytics_missing_metrics_and_locale(self):
        row = normalize({'Video title': 'A', 'Duration': '4:30', 'Impressions': '1,547.00', 'Average percentage viewed (%)': '53,01'})
        self.assertEqual(row['duration_seconds'], 270)
        self.assertEqual(row['impressions'], 1547)
        self.assertEqual(row['average_percentage_viewed'], 53.01)
        self.assertEqual(diagnose(row)['diagnosis'], 'insufficient_evidence')
        good = diagnose({'ctr_percent': 9.68, 'average_percentage_viewed': 53.01, 'views': 24, 'impressions': 217})
        self.assertTrue(good['tentative'])
        self.assertEqual(good['diagnosis'], 'topic_audience_distribution_candidate')
        self.assertIsNone(good['pilot_heuristics']['retention_30s_65_percent'])

    def test_pilot_comparison_preserves_unknowns(self):
        comparison = compare_pilots([{'experiment_id': '1', 'metrics': {'ctr_percent': 2}}, {'experiment_id': '2', 'metrics': {'ctr_percent': 4}}])
        self.assertEqual(comparison['pilots'][1]['delta_from_previous_pilot']['ctr_percent'], 2)
        self.assertIsNone(comparison['pilots'][1]['impression_change_since_previous_snapshot'])

    def test_wrong_youtube_identity_blocks_insert(self):
        import youtube_uploader
        youtube = MagicMock()
        youtube.channels.return_value.list.return_value.execute.return_value = {'items': [{'id': 'wrong-channel'}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(youtube_uploader, 'get_youtube_service', return_value=youtube):
            path = Path(tmp) / 'video.mp4'
            path.write_bytes(b'fake')
            with self.assertRaisesRegex(RuntimeError, 'no corresponde'):
                youtube_uploader.upload_video(str(path), 'Title', channel_profile='stunning-revelations')
        youtube.videos.assert_not_called()

    def test_assembly_routes_horizontal_and_keeps_studio_edits(self, manual=False):
        p = package()
        client = FakeClient([p, script_for(p)])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            micro.build('Coronel', out, client=client)
            micro.build('Coronel', out, client=client, approve=True)
            project = json.loads((out / 'project.json').read_text())
            project['config']['custom_option'] = 'keep'
            if manual:
                project['config']['image_provider'] = 'Manual (Gratuito)'
                (out / 'manual.jpg').write_bytes(b'fixture')
                for segment in project['storyboard']['segments']:
                    segment['image_path'] = 'manual.jpg'
            project['storyboard']['segments'][-1]['text'] += ' Preserved ending.'
            micro.write_json(out / 'project.json', project)
            pipeline = types.ModuleType('daily_short_pipeline')
            pipeline.generate_images_for_draft = MagicMock(side_effect=lambda out, sb, **kw: (sb, {}))
            pipeline.assemble_video = MagicMock(return_value=str(out / 'pilot.mp4'))
            pipeline.save_storyboard = lambda out, sb: micro.write_json(out / 'storyboard.json', sb)
            probe = MagicMock(stdout=json.dumps({'format': {'duration': '271'}, 'streams': [{'width': 1920, 'height': 1080}]}))
            with patch.dict('sys.modules', {'daily_short_pipeline': pipeline}), patch('long_form_builder._run_tts', return_value=out / 'audio.mp3'), patch('subprocess.run', return_value=probe):
                result = micro.build('Coronel', out, approve=True, assemble=True, client=client)
            self.assertEqual(result['status'], 'assembled')
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(pipeline.assemble_video.call_args.kwargs['platform'], 'youtube_long')
            if manual:
                pipeline.generate_images_for_draft.assert_not_called()
                self.assertEqual(pipeline.assemble_video.call_args.kwargs['image_provider'], 'manual')
                self.assertTrue(pipeline.assemble_video.call_args.kwargs['strict_existing_visuals'])
            final_project = json.loads((out / 'project.json').read_text())
            self.assertEqual(final_project['config']['custom_option'], 'keep')
            self.assertTrue(final_project['storyboard']['script'].endswith('Preserved ending.'))
            self.assertTrue(final_project['progress']['video_assembled'])
            self.assertEqual(final_project['generated_video_data']['video_path'], str(out / 'pilot.mp4'))

    def test_manual_assembly_never_calls_image_generation(self):
        self.test_assembly_routes_horizontal_and_keeps_studio_edits(manual=True)

    def test_manual_missing_images_stops_before_tts(self):
        p = package()
        client = FakeClient([p, script_for(p)])
        with tempfile.TemporaryDirectory() as tmp:
            micro.build('Coronel', tmp, client=client)
            with patch('long_form_builder._run_tts') as tts:
                with self.assertRaisesRegex(ValueError, 'Modo manual: faltan'):
                    micro.build('Coronel', tmp, approve=True, assemble=True, client=client, image_provider='manual')
                tts.assert_not_called()

    def test_actual_narration_out_of_range_stops_before_image_cost(self):
        p = package()
        client = FakeClient([p, script_for(p)])
        with tempfile.TemporaryDirectory() as tmp:
            micro.build('Coronel', tmp, client=client)
            pipeline = types.ModuleType('daily_short_pipeline')
            pipeline.generate_images_for_draft = MagicMock()
            pipeline.assemble_video = MagicMock()
            pipeline.save_storyboard = lambda out, sb: micro.write_json(out / 'storyboard.json', sb)
            def too_long(sb, *args):
                sb['segments'][-1]['end'] = 401
                return Path(tmp) / 'audio.mp3'
            with patch.dict('sys.modules', {'daily_short_pipeline': pipeline}), patch('long_form_builder._run_tts', side_effect=too_long):
                with self.assertRaisesRegex(ValueError, 'Actual narration'):
                    micro.build('Coronel', tmp, approve=True, assemble=True, client=client)
            pipeline.generate_images_for_draft.assert_not_called()
            pipeline.assemble_video.assert_not_called()


if __name__ == '__main__':
    unittest.main()
