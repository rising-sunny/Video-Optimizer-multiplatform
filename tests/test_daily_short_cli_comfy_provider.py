import sys
import unittest
from unittest.mock import patch

from pipeline import daily_short_pipeline


class DailyShortCliComfyProviderTests(unittest.TestCase):
    def test_cli_accepts_comfy_schnell_provider(self):
        argv = ["pipeline/daily_short_pipeline.py", "--image-provider", "comfy_schnell", "--count", "0"]
        with patch.object(sys, "argv", argv):
            daily_short_pipeline.main()

    def test_cli_accepts_comfy_sdxl_provider(self):
        argv = ["pipeline/daily_short_pipeline.py", "--image-provider", "comfy_sdxl", "--count", "0"]
        with patch.object(sys, "argv", argv):
            daily_short_pipeline.main()


if __name__ == "__main__":
    unittest.main()
