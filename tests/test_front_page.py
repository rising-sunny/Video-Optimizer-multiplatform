# -*- coding: utf-8 -*-
"""Guardas de la portada del periodico 3D (pipeline/front_page)."""

import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from pipeline import front_page as fp


class TestTexts(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(fp.find_dateline("On June 28, 1914, two shots."), "JUNE 28, 1914")
        self.assertEqual(fp.find_dateline("El 28 de junio de 1914 hubo dos disparos."), "28 DE JUNIO DE 1914")
        self.assertEqual(fp.find_dateline("Nothing here", "It began in 1939."), "1939")
        self.assertEqual(fp.find_dateline("no date at all"), "")

    def test_headline_cleanup(self):
        self.assertEqual(fp.clean_headline("The Shot That Started WWI 🔥 #history #shorts"),
                         "THE SHOT THAT STARTED WWI")
        self.assertEqual(fp.clean_headline("Sarajevo: the day everything changed"), "THE DAY EVERYTHING CHANGED")
        self.assertEqual(fp.clean_headline("WWI | Sarajevo"), "SARAJEVO")
        self.assertEqual(fp.split_headline("ARCHDUKE ASSASSINATED"), "ARCHDUKE|ASSASSINATED")
        self.assertEqual(fp.split_headline("WAR"), "WAR")

    def test_headline_sources_in_order(self):
        sb = {"title": "The Shot That Started WWI", "topic": "Sarajevo 1914", "language": "en",
              "segments": [{"text": "On June 28, 1914, the Archduke was shot. Europe held its breath."}]}
        texts = fp.front_page_texts(sb, sb["segments"][0]["text"], tag="")
        self.assertEqual(texts["headline"], "THE SHOT THAT|STARTED WWI")
        self.assertEqual(texts["deck"], "On June 28, 1914, the Archduke was shot.")
        self.assertIn("JUNE 28, 1914", texts["dateline"])
        self.assertIn("Europe held its breath", texts["body"], "las columnas usan la narracion real")
        self.assertEqual(fp.front_page_texts(sb, "x", tag="caso cerrado")["headline"], "CASO CERRADO")
        self.assertIn("EDICION EXTRA", fp.front_page_texts(dict(sb, language="es"), "x")["dateline"])

    def test_masthead_is_the_channel_never_a_real_paper(self):
        self.assertEqual(fp.channel_masthead("stunning-revelations"), "Stunning Revelations")
        self.assertEqual(fp.channel_masthead("stunning-facts-of-history"), "Stunning Facts of History")


class TestDrawing(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.mkdtemp(prefix="front_page_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.photo = os.path.join(self.tmp, "photo.png")
        Image.new("RGB", (400, 300), (90, 90, 90)).save(self.photo)
        self.texts = {"headline": "ARCHDUKE|ASSASSINATED", "deck": "Shot in Sarajevo.",
                      "dateline": "JUNE 28, 1914  —  EXTRA EDITION", "caption": "", "body": "word " * 200,
                      "masthead": "Stunning Revelations"}

    def test_page_size(self):
        from PIL import Image
        out = fp.build_front_page(os.path.join(self.tmp, "p.png"), self.photo, self.texts)
        with Image.open(out) as page:
            self.assertEqual(page.size, (fp.W, fp.H))

    def test_cached_page_is_reused_untouched(self):
        """Si se reescribiera, cambiaria su fecha y la toma 3D se re-renderizaria (minutos)."""
        first = fp.cached_front_page(self.tmp, self.photo, self.texts)
        mtime = os.path.getmtime(first)
        time.sleep(1.1)
        again = fp.cached_front_page(self.tmp, self.photo, self.texts)
        self.assertEqual(first, again)
        self.assertEqual(os.path.getmtime(again), mtime)
        other = fp.cached_front_page(self.tmp, self.photo, dict(self.texts, headline="OTRO"))
        self.assertNotEqual(first, other)


if __name__ == "__main__":
    unittest.main(verbosity=2)
