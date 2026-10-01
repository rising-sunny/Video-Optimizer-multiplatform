# -*- coding: utf-8 -*-
"""Guardas de la auditoria de veracidad del guion.

Hasta el 2026-09-03 el pipeline validaba tres cosas del guion -- que no fuera un
rechazo del LLM, que tuviera el largo pedido, y que hablara del tema -- y
NINGUNA miraba si lo que decia era cierto. El canal se apoya en cifras
("50 toneladas", "20.000 habitantes"), asi que un numero inventado en el gancho
es el error mas caro: es justo lo que la gente recuerda y comenta.

    .venv\\Scripts\\python.exe test_script_fact_guard.py
"""

import unittest

from ai import script_fact_guard as fg


class NormalizacionDeNumeros(unittest.TestCase):
    """El separador de miles cambia de idioma; hay que decidir por la FORMA."""

    def test_miles_en_ingles_y_en_espanol(self):
        self.assertEqual(fg.normalize_number("20,000"), 20000)
        self.assertEqual(fg.normalize_number("20.000"), 20000)
        self.assertEqual(fg.normalize_number("1,507,000"), 1507000)

    def test_decimales(self):
        self.assertEqual(fg.normalize_number("1.5"), 1.5)
        self.assertEqual(fg.normalize_number("2,9"), 2.9)

    def test_multiplicadores(self):
        self.assertEqual(fg.normalize_number("20 mil"), 20000)
        self.assertEqual(fg.normalize_number("1.5 million"), 1500000)
        self.assertEqual(fg.normalize_number("3 millones"), 3000000)

    def test_basura_no_rompe(self):
        for v in ("", None, "abc", "-"):
            self.assertIsNone(fg.normalize_number(v))


class ExtraccionDeAfirmaciones(unittest.TestCase):

    def test_distingue_anio_de_magnitud(self):
        claims = fg.extract_claims(
            "In 1453 the cannon fired stone balls of 270 kg.")
        tipos = {c.raw.strip(): c.kind for c in claims}
        self.assertEqual(tipos.get("1453"), "year")
        self.assertEqual(tipos.get("270"), "number")

    def test_un_numero_grande_con_unidad_no_es_anio(self):
        # "1080 metros" no es el anio 1080.
        claims = fg.extract_claims("El muro medía 1080 metros.")
        self.assertEqual([c.kind for c in claims], ["number"])

    def test_ignora_las_cifras_triviales(self):
        # "los 3 hermanos" no es una afirmacion que alguien vaya a discutir.
        self.assertEqual(fg.extract_claims("Eran 3 hermanos y 2 puertas."), [])

    def test_guarda_la_frase_de_cada_cifra(self):
        claims = fg.extract_claims("Primero nada. Cargaban bloques de 50 toneladas.")
        self.assertIn("50 toneladas", claims[0].sentence)


class ContrasteConLaInvestigacion(unittest.TestCase):

    CORPUS = [
        "Cahokia had a population of about 20,000 around 1100 AD.",
        "Monks Mound rises 30 metres and its base covers 5.6 hectares.",
    ]

    def test_una_cifra_respaldada_pasa(self):
        r = fg.audit_script("Cahokia held 20,000 people.", self.CORPUS)
        self.assertEqual(r.verdict, "ok")
        self.assertEqual(r.unsupported, [])

    def test_una_cifra_inventada_se_marca(self):
        r = fg.audit_script("Cahokia held 80,000 people.", self.CORPUS)
        self.assertEqual(r.verdict, "revisar")
        self.assertEqual([c.raw for c in r.unsupported], ["80,000"])

    def test_el_redondeo_normal_de_una_narracion_es_valido(self):
        # "unos 19.500" contra una fuente que dice 20.000: eso no es inventar.
        r = fg.audit_script("Vivian cerca de 19,500 personas.", self.CORPUS)
        self.assertEqual(r.unsupported, [])

    def test_un_anio_equivocado_no_tolera_redondeo(self):
        # 1453 y 1454 son hechos distintos: aca no hay margen.
        r = fg.audit_script("It happened in 1104.", self.CORPUS)
        self.assertEqual([c.raw for c in r.unsupported], ["1104"])
        self.assertEqual(r.verdict, "revisar")

    def test_un_anio_correcto_pasa(self):
        r = fg.audit_script("It happened in 1100.", self.CORPUS)
        self.assertEqual(r.unsupported, [])

    def test_un_anio_sin_respaldo_reprueba_aunque_el_resto_este_bien(self):
        guion = ("Cahokia held 20,000 people. Monks Mound rises 30 metres. "
                 "It was abandoned in 1610.")
        r = fg.audit_script(guion, self.CORPUS)
        self.assertGreaterEqual(r.coverage, 0.6)
        self.assertEqual(r.verdict, "revisar", "un anio inventado no puede pasar")

    def test_sin_investigacion_no_inventa_alarmas(self):
        # Misma regla que la validacion de tema: una alerta que suena siempre
        # no la mira nadie.
        r = fg.audit_script("Cahokia held 80,000 people.", [])
        self.assertEqual(r.verdict, "sin_investigacion")
        self.assertTrue(r.ok)

    def test_un_guion_sin_cifras_no_es_un_error(self):
        r = fg.audit_script("Una ciudad enorme junto al rio.", self.CORPUS)
        self.assertEqual(r.verdict, "sin_cifras")
        self.assertTrue(r.ok)

    def test_guion_vacio(self):
        self.assertEqual(fg.audit_script("", self.CORPUS).verdict, "sin_guion")


class MisteriosYTeorias(unittest.TestCase):
    """Lo que importa no es el TEMA sino que el guion respete la certeza.

    Un canal puede hablar de teorias sin problema; lo que no puede es
    presentarlas como hechos establecidos.
    """

    CORPUS_DUDOSO = [
        "The purpose of the structure is disputed; some researchers believe "
        "it was a temple.",
        "It is thought to date from around 1200, though the dating is debated.",
        "Some historians argue the site may have been abandoned suddenly.",
    ]

    def test_detecta_que_las_fuentes_matizan(self):
        b = fg.hedging_balance("x", self.CORPUS_DUDOSO)
        self.assertTrue(b["fuentes_matizan"])
        self.assertGreaterEqual(b["hedges_fuentes"], 3)

    def test_afirmar_en_seco_una_hipotesis_se_marca(self):
        guion = "The structure was a temple. It was abandoned suddenly in 1200."
        r = fg.audit_script(guion, self.CORPUS_DUDOSO)
        self.assertFalse(r.hedging["ok"])
        self.assertTrue(any("hipotesis" in w for w in r.warnings))
        self.assertEqual(r.verdict, "revisar")

    def test_el_mismo_guion_con_matiz_pasa(self):
        guion = ("Some researchers believe the structure was a temple. "
                 "It was abandoned around 1200.")
        r = fg.audit_script(guion, self.CORPUS_DUDOSO)
        self.assertTrue(r.hedging["ok"])

    def test_si_las_fuentes_no_matizan_no_se_exige_matiz(self):
        # Un hecho documentado se afirma sin rodeos, y esta bien.
        corpus = ["The battle took place on 16 November 1532 at Cajamarca."]
        r = fg.audit_script("The battle happened in 1532.", corpus)
        self.assertTrue(r.hedging["ok"])
        self.assertEqual(r.verdict, "ok")

    def test_cuenta_matices_en_los_dos_idiomas(self):
        self.assertGreaterEqual(fg.count_hedges("se cree que podria ser una teoria"), 3)
        self.assertGreaterEqual(fg.count_hedges("believed to be, may have been"), 2)


class InformeParaElLog(unittest.TestCase):

    def test_el_informe_nombra_la_cifra_y_su_frase(self):
        r = fg.audit_script("Cargaban bloques de 900 toneladas.",
                            ["The blocks weighed up to 50 tonnes."])
        lineas = "\n".join(fg.format_report(r))
        self.assertIn("FAIL", lineas)
        self.assertIn("900", lineas)
        self.assertIn("bloques", lineas)

    def test_el_caso_bueno_dice_cuantas_respaldo(self):
        r = fg.audit_script("50 tonnes each.", ["blocks of 50 tonnes"])
        lineas = "\n".join(fg.format_report(r))
        self.assertIn("[OK]", lineas)
        self.assertIn("1/1", lineas)

    def test_no_escupe_cincuenta_lineas(self):
        guion = " ".join("Dato %d000 unidades." % i for i in range(1, 30))
        r = fg.audit_script(guion, ["nada que coincida 7"])
        self.assertLessEqual(len(fg.format_report(r)), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
