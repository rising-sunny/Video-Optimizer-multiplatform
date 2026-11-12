import os, subprocess, tempfile, unittest
from pathlib import Path
from publish import instagram_uploader as iu


class TestEnsureInstagramSize(unittest.TestCase):
    def test_small_file_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.mp4"; p.write_bytes(b"x" * 1000)
            self.assertEqual(iu.ensure_instagram_size(str(p)), str(p))

    def test_large_file_is_reencoded(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "big.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30:duration=4",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-b:v", "20M", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", str(p)], check=True)
            old = iu.INSTAGRAM_MAX_UPLOAD_MB
            try:
                iu.INSTAGRAM_MAX_UPLOAD_MB = p.stat().st_size / 1_000_000 / 2
                out = iu.ensure_instagram_size(str(p))
            finally:
                iu.INSTAGRAM_MAX_UPLOAD_MB = old
            self.assertTrue(out.endswith("_ig.mp4"))
            self.assertLess(Path(out).stat().st_size, p.stat().st_size)


if __name__ == "__main__":
    unittest.main()
