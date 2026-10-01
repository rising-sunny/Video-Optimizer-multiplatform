import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from dynamic_subtitle_wrapper import DynamicSubtitleWrapper
from dynamic_subtitles_generator import DynamicSubtitleEngine


class TestDynamicSubtitlesSmoke(unittest.TestCase):
    def test_burned_subtitles_are_visible_on_output_frame(self):
        ffmpeg = shutil.which("ffmpeg") or r"C:\ffmpeg-7.1.1-full_build\bin\ffmpeg.EXE"
        if not ffmpeg or not Path(ffmpeg).exists():
            self.skipTest("FFmpeg no disponible para smoke test de subtitulos")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_video = tmp_path / "base.mp4"
            ass_path = tmp_path / "subs.ass"
            burned_video = tmp_path / "burned.mp4"
            base_frame = tmp_path / "base.png"
            burned_frame = tmp_path / "burned.png"

            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=1080x1920:d=2:r=30",
                    str(base_video),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            wrapper = DynamicSubtitleWrapper(style="capcut")
            wrapper.generate_ass_from_segments(
                [{"start": 0.0, "end": 2.0, "text": "Visible subtitle smoke test"}],
                str(ass_path),
                video_width=1080,
                video_height=1920,
            )

            self.assertTrue(
                DynamicSubtitleEngine.burn_subtitles_with_ffmpeg(
                    str(base_video),
                    str(ass_path),
                    str(burned_video),
                    1080,
                    1920,
                )
            )
            self.assertTrue(burned_video.exists())

            for video_path, frame_path in ((base_video, base_frame), (burned_video, burned_frame)):
                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-ss",
                        "1.0",
                        "-i",
                        str(video_path),
                        "-frames:v",
                        "1",
                        "-update",
                        "1",
                        str(frame_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )

            base_bright = self._count_subtitle_like_pixels(base_frame)
            burned_bright = self._count_subtitle_like_pixels(burned_frame)

            self.assertEqual(base_bright, 0)
            self.assertGreater(
                burned_bright,
                3000,
                "El frame quemado no muestra suficientes pixeles brillantes en la zona de subtitulos",
            )

    @staticmethod
    def _count_subtitle_like_pixels(image_path: Path) -> int:
        image = Image.open(image_path)
        crop = image.crop((0, int(image.size[1] * 0.6), image.size[0], image.size[1]))
        count = 0
        for y in range(crop.size[1]):
            for x in range(crop.size[0]):
                r, g, b, *_ = crop.getpixel((x, y))
                if r > 200 and g > 160:
                    count += 1
        return count


if __name__ == "__main__":
    unittest.main()
