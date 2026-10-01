import unittest
from channel_profiles import CHANNELS, DEFAULT_CHANNEL
from upload_metadata import metadata_for_channel


class UploadMetadataTests(unittest.TestCase):
    def test_both_destinations_branding_and_links(self):
        for channel, tag in [(DEFAULT_CHANNEL, 'StunningFactsofHistory'),
                             ('stunning-revelations', 'StunningRevelations')]:
            metadata = {
                'title': 'Gunnerside | Stunning Revelations',
                'description': 'Subscribe to @Stunning-Revelations and Stunning Facts of History!\n'
                               '#StunningRevelations #StunningFactsofHistory\n'
                               'https://www.youtube.com/c/StunningRevelations\n'
                               'https://youtube.com/@StunningFactsofHistory\n'
                               'Source: https://www.nia.no/en/the-operations/',
                'tags': ['Gunnerside', 'StunningRevelations', 'Stunning Facts of History'],
                'is_short': False,
            }
            result = metadata_for_channel(metadata, channel)
            self.assertIn(CHANNELS[channel]['name'], result['description'])
            self.assertIn('#' + tag, result['description'])
            self.assertIn('https://www.youtube.com/' + CHANNELS[channel]['name'], result['description'])
            self.assertIn('Source: https://www.nia.no/en/the-operations/', result['description'])
            self.assertEqual(result['tags'][0], 'Gunnerside')
            self.assertEqual(len(result['tags']), 2)
            self.assertFalse(result['is_short'])
            self.assertEqual(result['upload_channel'], channel)
            self.assertEqual(metadata['title'], 'Gunnerside | Stunning Revelations')
            self.assertEqual(result, metadata_for_channel(result, channel))

    def test_topic_and_attribution_are_preserved(self):
        metadata = {'title': 'Operation Gunnerside: The Heavy Water Raid',
                    'description': 'Norway, 1943.\nCredits: Stunning Revelations\nSource: British Pathé',
                    'tags': ['Norway', '1943'], 'is_short': False}
        result = metadata_for_channel(metadata, DEFAULT_CHANNEL)
        for field in ('title', 'description', 'tags', 'is_short'):
            self.assertEqual(result[field], metadata[field])


if __name__ == '__main__':
    unittest.main()
