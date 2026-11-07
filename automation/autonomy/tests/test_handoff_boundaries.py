import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'modules'))
from workflow_handoff import metadata_closures
from workflow_preparation import normalized_fields
import workflow_common as c


class MetadataBoundaries(unittest.TestCase):
    def raw(self):
        return ('{"channel":"historical","metadata":{"youtube":{"title":"Exact title",'
            '"description":"A URL https://example.org/license and exact credit"},"tags":["history"]},'
            '"facebook":{"description":"Exact Facebook credit"}},'
            '"instagram":{"caption":"Exact Instagram credit"}},'
            '"thumbnail":{"media":0,"text":"Exact thumbnail"}}')

    def test_two_recognized_metadata_closes_preserve_all_texts_and_credits(self):
        result,changes=metadata_closures(self.raw())
        self.assertEqual(set(result['metadata']),{'youtube','facebook','instagram'})
        self.assertEqual(result['metadata']['youtube']['tags'],['history'])
        self.assertEqual(result['metadata']['youtube']['description'],'A URL https://example.org/license and exact credit')
        self.assertEqual(result['metadata']['facebook']['description'],'Exact Facebook credit')
        self.assertEqual(result['metadata']['instagram']['caption'],'Exact Instagram credit')
        self.assertEqual(changes[0]['count'],2)

    def test_unrelated_suffixes_and_duplicate_keys_are_rejected(self):
        bad=[self.raw()+' arbitrary text',self.raw().replace('"history"]','"history"],"tags":[]'),
             '{"x":1},"instagram":{"caption":"fake"}}',self.raw().replace('"instagram"','"unrelated"')]
        for text in bad:
            with self.subTest(text=text[-100:]),self.assertRaises(ValueError):metadata_closures(text)

    def test_key_names_inside_strings_are_not_structural_boundaries(self):
        text=self.raw().replace('Exact title','Text with \\"tags\\": data inside')
        result,_=metadata_closures(text)
        self.assertIn('"tags"',result['metadata']['youtube']['title'])

    def test_actual_complete_provider_response_is_recovered_without_new_tokens(self):
        fixture=Path(__file__).with_name('curie-metadata-boundaries.txt')
        if not fixture.exists():fixture=Path(__file__).resolve().parents[1]/'observed/curie-repaired-raw.txt'
        result,_=metadata_closures(fixture.read_text().strip())
        self.assertEqual(result['channel'],'stunning-facts-of-history')
        self.assertEqual(result['music_title'],'Measured Paces')
        self.assertEqual(result['metadata']['youtube']['tags'][0],'Marie Curie')
        self.assertEqual(len(result['project']['sequence']),16)


class NativeFields(unittest.TestCase):
    def test_context_overlay_and_actual_publisher_link_are_normalized_without_changing_track_or_card(self):
        with tempfile.TemporaryDirectory() as name:
            job=Path(name);(job/'publisher.html').write_text('actual publisher evidence')
            c.write(job/'music-input.json',dict(tracks=[dict(title='Measured Paces',isrc='USUAN1100164',license_url='https://creativecommons.org/licenses/by/4.0/')]))
            c.write(job/'music-license-evidence.json',dict(template_url='https://incompetech.com/music/royalty-free/index.html?isrc=OTHER',
                tracks=[dict(title='Measured Paces',isrc='USUAN1100164')],evidence_files={'publisher.html':c.digest(job/'publisher.html')}))
            value=dict(assets=[dict(role='context',label='Solvay Conference, 1927')],music_title='Measured Paces',
                music_license_url='https://creativecommons.org/licenses/by/4.0/',project=dict(sequence=[dict(kind='media',media=0,text='Solvay Conference, 1927 — later context'),dict(kind='card',text='Exact narrative')]))
            before=c.tree(job);result=normalized_fields(job,value)
            self.assertEqual(result['music_title'],value['music_title'])
            self.assertEqual(result['music_license_url'],'https://incompetech.com/music/royalty-free/index.html?isrc=USUAN1100164')
            self.assertEqual(result['project']['sequence'][0]['kind'],'overlay')
            self.assertEqual(result['project']['sequence'][1],value['project']['sequence'][1])
            self.assertEqual(before,c.tree(job))
            (job/'publisher.html').write_text('tampered')
            with self.assertRaisesRegex(RuntimeError,'publisher_receipt_changed'):normalized_fields(job,value)


if __name__=='__main__':unittest.main()
