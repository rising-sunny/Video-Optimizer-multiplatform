import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from comfyui_image_client import ComfyUiImageClient


class _FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload = payload
        self.content = content or (json.dumps(payload).encode("utf-8") if payload is not None else b"")
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        return _FakeResponse({"prompt_id": "prompt-123"})

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params, timeout))
        if url.endswith("/history/prompt-123"):
            return _FakeResponse({
                "prompt-123": {
                    "outputs": {
                        "9": {
                            "images": [
                                {"filename": "ComfyUI_00001.png", "subfolder": "", "type": "output"}
                            ]
                        }
                    }
                }
            })
        if url.endswith("/view"):
            return _FakeResponse(content=b"fake-png-bytes")
        return _FakeResponse({})


class ComfyUiImageClientTests(unittest.TestCase):
    def test_generate_image_renders_workflow_and_downloads_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workflow_dir = root / "workflows"
            workflow_dir.mkdir()
            (workflow_dir / "presets.json").write_text(
                json.dumps({
                    "presets": {
                        "unit_test": {
                            "workflow": "unit_test.json",
                            "fields": {
                                "prompt": "6.inputs.text",
                                "negative_prompt": "7.inputs.text",
                                "width": "5.inputs.width",
                                "height": "5.inputs.height",
                                "seed": "3.inputs.seed",
                                "batch_size": "5.inputs.batch_size",
                                "filename_prefix": "9.inputs.filename_prefix",
                            },
                        }
                    }
                }),
                encoding="utf-8",
            )
            (workflow_dir / "unit_test.json").write_text(
                json.dumps({
                    "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
                    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1, "height": 1, "batch_size": 1}},
                    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI"}},
                }),
                encoding="utf-8",
            )

            output_path = root / "out.png"
            fake_session = _FakeSession()
            client = ComfyUiImageClient(
                base_url="http://comfy.local",
                workflow_dir=workflow_dir,
                timeout_seconds=5,
                session=fake_session,
            )

            with patch("comfyui_image_client.time.sleep"):
                result = client.generate_image(
                    prompt="cinematic castle",
                    width=1080,
                    height=1920,
                    output_path=str(output_path),
                    negative_prompt="modern city",
                    seed=42,
                    preset="unit_test",
                )

            self.assertEqual(result, str(output_path))
            self.assertEqual(output_path.read_bytes(), b"fake-png-bytes")
            queued_workflow = fake_session.posts[0][1]["prompt"]
            self.assertEqual(queued_workflow["6"]["inputs"]["text"], "cinematic castle")
            self.assertEqual(queued_workflow["7"]["inputs"]["text"], "modern city")
            self.assertEqual(queued_workflow["5"]["inputs"]["width"], 1080)
            self.assertEqual(queued_workflow["5"]["inputs"]["height"], 1920)
            self.assertEqual(queued_workflow["3"]["inputs"]["seed"], 42)
            self.assertEqual(queued_workflow["9"]["inputs"]["filename_prefix"], "out")


if __name__ == "__main__":
    unittest.main()
