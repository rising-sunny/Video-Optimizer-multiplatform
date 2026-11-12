"""Guardas de documentary_kit.hook_check con arranques reales del laboratorio de ganchos (2026-11-12)."""
import unittest

from documentary_kit import hook_check as hc

ISANDLWANA = ("January 22nd, 1879. A British regiment sets up camp at the base of a sphinx-shaped mountain in Southern Africa. "
              "Over 1,300 soldiers, veterans of four continents. By lunch, over 1,300 of them will be dead. "
              "Not from disease, not from accident, killed in combat by an enemy their commanding officer believed would run at the first shot. "
              "This is Isandlwana, the battle Britain spent 150 years trying to forget.")
DAMASCUS = ("How long can a city remember? West of the Syrian desert, a river comes down from the mountains and should vanish in the dust. "
            "It does not. The river spreads into an oasis and people learn to live inside that green. "
            "For centuries, those orchards fed the city. Apricot, walnut, water.")


def levels(f):
    return [lvl for lvl, _ in f]


class TestOpening(unittest.TestCase):
    def test_outlier_opening_passes(self):
        f = hc.check_opening(hc.sentences_from_text(ISANDLWANA), "20,000 Warriors. One Morning. Britain's Worst Military Disaster")
        self.assertNotIn('FAIL', levels(f))
        self.assertGreaterEqual(levels(f).count('OK'), 3)

    def test_poetic_opening_warns(self):
        f = hc.check_opening(hc.sentences_from_text(DAMASCUS), 'Is Damascus the Oldest Capital on Earth?')
        msgs = ' '.join(m for _, m in f)
        self.assertIn('Primera frase sin fecha', msgs)
        self.assertIn('Ninguna cifra', msgs)

    def test_meta_first_sentence_fails(self):
        f = hc.check_opening(hc.sentences_from_text('This is the story of the Karluk. In 1913 the ship sailed north.'), 'Karluk')
        self.assertIn('FAIL', levels(f))

    def test_timings_are_respected(self):
        # la cifra llega a los 50 s: no cuenta para la ventana de 40 s
        f = hc.check_opening([(0.0, 'A city by the sea.'), (50.0, 'Twelve ships came.')], 'A city')
        self.assertIn(('WARN', 'Ninguna cifra en los primeros 40 s (cuantas personas, cuanto tiempo, cuanto pesaba...).'), f)


class TestPackaging(unittest.TestCase):
    def test_title(self):
        self.assertIn('WARN', levels(hc.check_title('The Texas City Disaster: A Story Explained in Full Detail by Historians Today')))
        good = hc.check_title('The Last 77 Seconds of the Florida Learjet 60')
        self.assertEqual(levels(good), ['OK', 'OK'])

    def test_encyclopedia_colon(self):
        self.assertTrue(any('enciclopedia' in m for _, m in hc.check_title('Damascus: Burned, Conquered, and Still Lived In')))

    def test_thumbnail(self):
        self.assertEqual(levels(hc.check_thumbnail('589 DAYS', '28 Men Trapped in Antarctica')), ['OK'])
        self.assertIn('WARN', levels(hc.check_thumbnail('THE TEXAS CITY DISASTER OF 1947', 'The Texas City Disaster')))


if __name__ == '__main__':
    unittest.main()
