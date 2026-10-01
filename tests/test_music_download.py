# -*- coding: utf-8 -*-
"""Tests de music_recommender.download_audio: descarga robusta de temas de Jamendo.

Regresion (2026-09-24): en el buscador de musica, la forma de onda fallo por DNS
("Failed to resolve prod-1.storage.jamendo.com") y la vista previa se corto al 21%
("Read timed out"). Sin reintentos, sin reanudar y bajando el mismo archivo dos
veces a la vez. Sin red: http_get es falso.
"""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from media import music_recommender as mr

ROOT = Path(__file__).resolve().parent.parent
URL = "https://prod-1.storage.jamendo.com/?trackid=1509464&format=mp31&from=abc"
DATA = bytes(range(256)) * 400          # ~100 KB


class FakeResponse:
    def __init__(self, status, body, cut_after=None, headers=None):
        self.status_code = status
        self._body = body
        self._cut = cut_after
        self.headers = {"content-length": str(len(body))}
        self.headers.update(headers or {})

    def iter_content(self, chunk_size=65536):
        sent = 0
        for i in range(0, len(self._body), 8192):
            if self._cut is not None and sent >= self._cut:
                raise mr.requests.exceptions.ReadTimeout("Read timed out.")
            chunk = self._body[i:i + 8192]
            sent += len(chunk)
            yield chunk


class FakeServer:
    """Guion de respuestas por intento; registra URL y Range de cada pedido."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, stream=True, timeout=None, headers=None):
        rng = (headers or {}).get("Range")
        self.calls.append((url, rng))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(url, rng)


def full(url, rng):
    return FakeResponse(200, DATA)


def partial(cut):
    return lambda url, rng: FakeResponse(200, DATA, cut_after=cut)


def resume(url, rng):
    start = int(rng.split("=")[1].rstrip("-"))
    return FakeResponse(206, DATA[start:])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "track.mp3")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.dest, "rb") as f:
            return f.read()


class LaDescarga(Base):
    def test_dns_failure_then_success(self):
        server = FakeServer([mr.requests.exceptions.ConnectionError("Failed to resolve"), full])
        self.assertEqual(mr.download_audio(URL, self.dest, http_get=server, sleep=lambda s: None), self.dest)
        self.assertEqual(self.read(), DATA)

    def test_read_timeout_resumes_with_range_instead_of_restarting(self):
        server = FakeServer([partial(8192 * 3), resume])
        pct = []
        mr.download_audio(URL, self.dest, http_get=server, sleep=lambda s: None, progress=pct.append)
        self.assertEqual(self.read(), DATA)
        self.assertIsNone(server.calls[0][1])
        self.assertEqual(server.calls[1][1], f"bytes={8192 * 3}-")
        self.assertEqual(pct[-1], 100)
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_server_ignoring_range_restarts_cleanly(self):
        server = FakeServer([partial(8192 * 2), full])     # responde 200 entero pese al Range
        mr.download_audio(URL, self.dest, http_get=server, sleep=lambda s: None)
        self.assertEqual(self.read(), DATA)

    def test_falls_back_to_the_mp3l_mirror(self):
        err = mr.requests.exceptions.ConnectionError("Failed to resolve")
        server = FakeServer([err, err, full])
        mr.download_audio(URL, self.dest, http_get=server, sleep=lambda s: None)
        self.assertTrue(server.calls[2][0].startswith("https://mp3l.jamendo.com/?trackid=1509464&format=mp31"))
        self.assertIsNone(server.calls[2][1])              # otro servidor: sin mezclar bytes
        self.assertEqual(self.read(), DATA)

    def test_gives_up_with_the_last_error_and_no_half_file(self):
        err = mr.requests.exceptions.ConnectionError("Failed to resolve")
        server = FakeServer([err, err, err, err])
        with self.assertRaises(RuntimeError) as ctx:
            mr.download_audio(URL, self.dest, http_get=server, sleep=lambda s: None)
        self.assertIn("Failed to resolve", str(ctx.exception))
        self.assertFalse(os.path.exists(self.dest))

    def test_cancel(self):
        server = FakeServer([full])
        self.assertIsNone(mr.download_audio(URL, self.dest, http_get=server, cancelled=lambda: True))
        self.assertFalse(os.path.exists(self.dest))

    def test_existing_complete_file_is_reused_unless_told_not_to(self):
        with open(self.dest, "wb") as f:
            f.write(b"old track")
        self.assertEqual(mr.download_audio(URL, self.dest, http_get=FakeServer([])), self.dest)
        self.assertEqual(self.read(), b"old track")
        mr.download_audio(URL, self.dest, http_get=FakeServer([full]), reuse_existing=False)
        self.assertEqual(self.read(), DATA)

    def test_two_simultaneous_requests_download_once(self):
        calls = []

        def slow(url, stream=True, timeout=None, headers=None):
            calls.append(url)
            time.sleep(0.2)
            return FakeResponse(200, DATA)

        results = []
        threads = [threading.Thread(target=lambda: results.append(
            mr.download_audio(URL, self.dest, http_get=slow))) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [self.dest, self.dest])

    def test_mirrors(self):
        self.assertEqual(mr.jamendo_mirrors(URL)[1], "https://mp3l.jamendo.com/?trackid=1509464&format=mp31")
        self.assertEqual(mr.jamendo_mirrors("https://x/file.mp3"), ["https://x/file.mp3"])


def shadowed_imports(path):
    """Funciones que usan un nombre importado a nivel de modulo antes de re-importarlo adentro.

    El import local lo vuelve variable local de TODA la funcion: usarlo antes da
    UnboundLocalError ("cannot access local variable 'shutil'..."), que solo
    aparece cuando alguien pasa por esa rama.
    """
    import ast
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    module_names = set()
    for n in tree.body:
        if isinstance(n, ast.Import):
            module_names |= {a.asname or a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            module_names |= {a.asname or a.name for a in n.names}
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

    def own_scope(nodes):
        out, stack = [], list(nodes)
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(c for c in ast.iter_child_nodes(node) if not isinstance(c, nested))
        return out

    problems = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        own = own_scope(fn.body)
        blocks = [lst for node in [fn] + own for field in ("body", "orelse", "finalbody")
                  for lst in [getattr(node, field, None)] if isinstance(lst, list)]
        safe = {}      # nombre -> ids de nodos donde ese nombre ya fue importado localmente
        shadowed = set()
        for node in own:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for a in node.names:
                name = a.asname or (a.name.split(".")[0] if isinstance(node, ast.Import) else a.name)
                if name not in module_names:
                    continue
                shadowed.add(name)
                block = next(lst for lst in blocks if node in lst)
                after = block[block.index(node) + 1:]
                safe.setdefault(name, set()).update(id(n) for n in own_scope(after))
        for n in own:
            if isinstance(n, ast.Name) and n.id in shadowed and id(n) not in safe.get(n.id, set()):
                problems.append(f"{Path(path).name}:{n.lineno} {fn.name} usa '{n.id}' fuera del bloque "
                                f"de su import local (UnboundLocalError en esa rama)")
    return problems


class ElCableado(unittest.TestCase):
    def _src(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_no_function_shadows_a_module_import(self):
        # Regresion: "Seleccionar Musica" con recorte -> "cannot access local variable 'shutil'".
        files = ["music_browser_dialog.py", "media/music_recommender.py", "music_license.py",
                 "auto_video_integration_pyqt6.py", "timeline_editor_widget.py", "storyboard_generator.py",
                 "daily_short_pipeline.py", "auto_video_generator_v2.py", "ai/script_fact_check.py",
                 "ai/visual_art_direction.py", "facebook_uploader.py", "instagram_uploader.py", "youtube_uploader.py"]
        problems = [p for f in files for p in shadowed_imports(ROOT / f)]
        self.assertEqual(problems, [])

    def test_fixed_paths_always_download_fresh(self):
        # temp_bgm.mp3 es una ruta fija: sin esto un video se quedaba con la musica del anterior
        src = self._src("media/music_recommender.py")
        body = src[src.index("def download_track("):]
        self.assertIn("reuse_existing=False", body[:body.index("\ndef ")])

    def test_dialog_preview_and_waveform_share_the_robust_download(self):
        src = self._src("music_browser_dialog.py")
        self.assertEqual(src.count("from media.music_recommender import download_audio"), 2)
        self.assertNotIn("requests.get(audio_url, timeout=(10, 15), stream=True)", src)
        self.assertIn("WaveformWorker(track, self._preview_cache_path(track))", src)


if __name__ == "__main__":
    unittest.main()
