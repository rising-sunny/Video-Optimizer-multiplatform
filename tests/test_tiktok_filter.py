"""Filtro de normas de TikTok: lo que se retiro (Operation Northwoods) bloquea; la historia comun pasa."""
import unittest

from publish import tiktok_filter as tf

# El texto del Short que TikTok retiro el 2026-10-07 por "Normas de la comunidad".
NORTHWOODS = ("Operation Northwoods explained: the 1962 false flag plan to blame Cuba.\n\n"
              "In a TOP SECRET memo dated March 13, 1962, the US Joint Chiefs of Staff proposed pretexts to invade Cuba: "
              "\"We could blow up a US ship in Guantanamo Bay and blame Cuba.\" Funerals for \"mock-victims.\" "
              "A fake \"Communist Cuban terror campaign\" in Miami and even Washington. A staged airliner shootdown, "
              "with a drone destroyed \"by radio signal.\" Kennedy rejected it.\n\n"
              "#OperationNorthwoods #FalseFlag #Declassified #Conspiracy #ColdWar")


def rules(findings):
    return {f.rule for f in findings}


class Bloquea(unittest.TestCase):

    def test_el_short_retirado_de_northwoods(self):
        f = tf.review(description=NORTHWOODS)
        self.assertTrue(tf.blocks(f))
        self.assertTrue({"negacion", "conspiracion_violenta", "violencia_montada"} <= rules(f))
        self.assertEqual(f[0].level, tf.BLOCK, "lo que bloquea va primero")

    def test_el_hashtag_tambien_se_lee(self):
        f = tf.review(hashtags=["#FalseFlag"])
        self.assertTrue(tf.blocks(f))
        self.assertEqual(f[0].fields, ["hashtags"])

    def test_en_castellano(self):
        self.assertTrue(tf.blocks(tf.review(description="Fue una bandera falsa del gobierno")))

    def test_las_tarjetas_en_pantalla(self):
        project = {"cards": {"opening": "Who planned staged attacks on the United States?",
                             "lines": ["Blow up a US ship. Blame Cuba.", "Fake Cuban terror in Miami and Washington."],
                             "climax": ["PRETEXT", "BLAME", "INVADE"]}}
        f = tf.review_project(project)
        self.assertIn("violencia_montada", rules(f))
        self.assertIn("pantalla", f[0].fields)


class Pasa(unittest.TestCase):

    def test_historia_de_guerra_comun(self):
        f = tf.review(description="On August 6, 1945, an atomic bomb destroyed Hiroshima. #History #WW2")
        self.assertFalse(tf.blocks(f))
        self.assertEqual(f, [], "una sola palabra violenta es historia normal en #HistoryTok")

    def test_sputnik(self):
        texto = "On December 6, America's answer, the Vanguard rocket, rose about four feet and exploded."
        self.assertEqual(tf.review(description=texto), [])

    def test_actualidad_avisa_sin_bloquear(self):
        f = tf.review(description="Could Kaliningrad start World War 3? Russia warned of nuclear weapons. #WW3")
        self.assertFalse(tf.blocks(f))
        self.assertIn("crisis", rules(f))

    def test_mkultra_avisa_lsd_y_suicidio(self):
        f = tf.review(on_screen=["Subjects were given LSD without knowing.", "Officially, he jumped."],
                      hashtags=["#Conspiracy"])
        self.assertFalse(tf.blocks(f))
        self.assertTrue({"drogas", "autolesion", "conspiracion"} <= rules(f))

    def test_cada_hallazgo_dice_norma_y_correccion(self):
        for line in tf.report(tf.review(description=NORTHWOODS)):
            self.assertIn("Corrige:", line)

    def test_metadata_de_subida_incluye_la_narracion(self):
        f = tf.review_metadata({"title": "Northwoods", "description": "", "script_excerpt": "It was a false flag."})
        self.assertEqual(f[0].fields, ["narración"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
