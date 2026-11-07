import copy
import unittest
from deepseek_review import compact_evidence

class Compact(unittest.TestCase):
    def test_all_facts_restrictions_links_and_selected_music_are_retained(self):
        value={'editorial-plan.json':{'segments':[{'narration':'Unchanged complete narration.'}]},
            'factual_source_excerpts':{'https://nasa.gov/source':{'text':'Full fetched source without truncation.'}},
            'music-selection.json':{'tracks':[{'recording_id':'selected'}]},
            'music-license-evidence.json':{'policy':{'covered_channel':'stunning-revelations'},
                'tracks':[{'recording_id':'unused'},{'recording_id':'selected','license':'actual provider account scope'}],
                'full_receipt_sha256':'pinned'},
            'license-1.json':{'record':{'source_url':'https://commons.wikimedia.org/?curid=1',
                'source_rights':{'Restrictions':{'value':'<b>No commercial reuse</b>. See <a href="https://example.org/a?x=1&amp;y=2">terms</a>.'},
                'Copyrighted':{'value':'True'},'Artist':{'value':'<span>Complete Author Name</span>'}}},
                'full_receipt_sha256':'original-hash'}}
        before=copy.deepcopy(value);result=compact_evidence(value)
        self.assertEqual(value,before)
        for key in ('editorial-plan.json','factual_source_excerpts','music-selection.json'):
            self.assertEqual(result[key],value[key])
        self.assertEqual(result['music-license-evidence.json']['tracks'],[value['music-license-evidence.json']['tracks'][1]])
        rights=result['license-1.json']['record']['source_rights']
        self.assertEqual(rights['Restrictions']['text'],'No commercial reuse . See terms .')
        self.assertEqual(rights['Restrictions']['links'],['https://example.org/a?x=1&y=2'])
        self.assertEqual(rights['Artist']['text'],'Complete Author Name')
        self.assertEqual(rights['Copyrighted']['text'],'True')
        self.assertEqual(result['license-1.json']['full_receipt_sha256'],'original-hash')
    def test_unknown_music_selection_never_drops_catalogue_tracks(self):
        value={'music-license-evidence.json':{'tracks':[{'recording_id':'retain'}]}}
        self.assertEqual(compact_evidence(value),value)

if __name__=='__main__':unittest.main()
