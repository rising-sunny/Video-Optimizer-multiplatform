# -*- coding: utf-8 -*-
"""Guardas de la apertura automatica de proyecto al arrancar.

BUG (2026-09-04): la app arranco sin el proyecto en el que se estaba
trabajando. `last_project_path.txt` estaba vacio (0 bytes) y el codigo hacia
`return` en silencio: en todo el log de arranque no habia UNA linea sobre el
intento, asi que parecia que el proyecto se hubiera perdido.

La raiz es que una cadena vacia significaba dos cosas incompatibles:
"el usuario pidio empezar de cero" y "el puntero se perdio".

    .venv\\Scripts\\python.exe test_project_autoload.py
"""

import os
import shutil
import tempfile
import unittest

from infra.project_autoload import (
    NEW_PROJECT_SENTINEL,
    decide_project_to_load,
    list_recent_projects,
)

VIEJO = r"C:\proj\Cahokia\project.json"
RECIENTE = r"C:\proj\Caral\project.json"
OTRO = r"C:\proj\Aksum\project.json"


def existe_solo(*rutas):
    disponibles = set(rutas)
    return lambda p: p in disponibles


class QueProyectoAbrir(unittest.TestCase):

    def test_el_puntero_valido_manda(self):
        ruta, motivo = decide_project_to_load(
            VIEJO, [RECIENTE, VIEJO], exists=existe_solo(VIEJO, RECIENTE))
        self.assertEqual(ruta, VIEJO)
        self.assertIn("ultimo proyecto", motivo)

    def test_proyecto_nuevo_no_reabre_nada(self):
        # Es el motivo por el que el puntero se limpia: pedir "Nuevo" y
        # reiniciar no puede devolverte el proyecto anterior.
        ruta, motivo = decide_project_to_load(
            NEW_PROJECT_SENTINEL, [RECIENTE], exists=existe_solo(RECIENTE))
        self.assertIsNone(ruta)
        self.assertIn("nuevo", motivo)

    def test_puntero_vacio_cae_al_mas_reciente(self):
        """El caso que fallaba: puntero perdido y la app no intentaba nada."""
        ruta, motivo = decide_project_to_load(
            "", [RECIENTE, VIEJO], exists=existe_solo(RECIENTE, VIEJO))
        self.assertEqual(ruta, RECIENTE)
        self.assertIn("mas reciente", motivo)

    def test_puntero_ausente_tambien_cae_al_mas_reciente(self):
        ruta, _ = decide_project_to_load(
            None, [RECIENTE], exists=existe_solo(RECIENTE))
        self.assertEqual(ruta, RECIENTE)

    def test_una_ruta_borrada_cae_al_siguiente_que_exista(self):
        # Pasa al renombrar una carpeta, o entre las dos PCs que sincronizan
        # este repo.
        ruta, motivo = decide_project_to_load(
            VIEJO, [RECIENTE, OTRO], exists=existe_solo(RECIENTE, OTRO))
        self.assertEqual(ruta, RECIENTE)
        self.assertIn("ya no existe", motivo)

    def test_sin_candidatos_no_inventa_nada(self):
        ruta, motivo = decide_project_to_load("", [], exists=existe_solo())
        self.assertIsNone(ruta)
        self.assertTrue(motivo)

    def test_siempre_da_un_motivo_para_el_log(self):
        # Que el arranque NUNCA sea silencioso es la mitad del arreglo.
        casos = [
            (VIEJO, [VIEJO]), (NEW_PROJECT_SENTINEL, []), ("", [RECIENTE]),
            (None, []), ("   ", [VIEJO]),
        ]
        for puntero, candidatos in casos:
            _, motivo = decide_project_to_load(
                puntero, candidatos, exists=existe_solo(VIEJO, RECIENTE))
            self.assertTrue(motivo and motivo.strip(), (puntero, candidatos))

    def test_los_espacios_no_confunden_al_centinela(self):
        ruta, _ = decide_project_to_load(
            "  %s  " % NEW_PROJECT_SENTINEL, [RECIENTE], exists=existe_solo(RECIENTE))
        self.assertIsNone(ruta)


class ListadoDeProyectos(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="autoload_")
        self.raiz = os.path.join(self.tmp, "projects")
        os.makedirs(self.raiz)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _crear(self, nombre, mtime):
        carpeta = os.path.join(self.raiz, nombre)
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, "project.json")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("{}")
        os.utime(ruta, (mtime, mtime))
        return ruta

    def test_ordena_del_mas_reciente_al_mas_viejo(self):
        self._crear("viejo", 1000)
        nuevo = self._crear("nuevo", 9000)
        medio = self._crear("medio", 5000)
        listado = list_recent_projects(self.raiz)
        self.assertEqual(listado[:2], [nuevo, medio])

    def test_ignora_carpetas_sin_project_json(self):
        os.makedirs(os.path.join(self.raiz, "vacia"))
        self._crear("bueno", 1000)
        listado = list_recent_projects(self.raiz)
        self.assertEqual(len(listado), 1)

    def test_una_carpeta_inexistente_no_rompe(self):
        self.assertEqual(list_recent_projects(os.path.join(self.tmp, "no_existe")), [])

    def test_respeta_el_limite(self):
        for i in range(8):
            self._crear("p%d" % i, 1000 + i)
        self.assertEqual(len(list_recent_projects(self.raiz, limit=3)), 3)


class LaGuiEntraPorLaDecision(unittest.TestCase):
    """Limpieza 2026-09-14: el fix del 2026-09-04 estaba en un metodo que nadie llamaba.

    `auto_video_integration_pyqt6._load_last_project` usaba `decide_project_to_load`,
    pero la GUI arranca por `video_optimizer_pyqt6._load_last_project_once`, que leia
    el puntero directo y volvia en silencio si la ruta no existia: el fallback al
    proyecto mas reciente nunca corria. Esta guarda mira el camino real.
    """

    def _fuente(self, nombre):
        with open(nombre, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def test_el_arranque_real_usa_decide_project_to_load(self):
        fuente = self._fuente("video_optimizer_pyqt6.py")
        inicio = fuente.index("def _load_last_project_once(")
        fin = fuente.index("    def ", inicio + 10)  # siguiente metodo
        cuerpo = fuente[inicio:fin]
        self.assertIn("decide_project_to_load(", cuerpo)
        self.assertIn("list_recent_projects()", cuerpo)
        self.assertIn("Sin proyecto para abrir", cuerpo, "un puntero roto tiene que dejar rastro en el log")

    def test_no_vuelve_el_metodo_que_nadie_llamaba(self):
        fuente = self._fuente("auto_video_integration_pyqt6.py")
        self.assertNotIn("def _load_last_project(self)", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
