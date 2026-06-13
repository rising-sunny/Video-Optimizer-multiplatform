"""
Tests para video_generation_manager.py y fal_ai_client.py (video)
Verifica: orden de modelos, truncado de prompts, fallback entre modelos/proveedores,
integracion fal.ai video, y cost_calculator.
"""

import unittest
from unittest.mock import MagicMock, patch, call
from pathlib import Path
import tempfile
import os

from video_generation_manager import VideoGenerationManager


class MockTaskOutput:
    """Simula el output de un task de Runway."""
    def __init__(self, url="https://fake.runway.com/video.mp4"):
        self.output = MagicMock()
        self.output.url = url

    def wait_for_task_output(self):
        return self


# =====================================================================
# Runway tests
# =====================================================================

class TestModelOrder(unittest.TestCase):
    """Verifica que veo3.1_fast sea el primer modelo intentado."""

    def test_veo31_fast_is_first_model_tried(self):
        """El primer modelo debe ser veo3.1_fast (mejor relacion calidad/precio)."""
        logs = []
        mock_client = MagicMock()
        mock_client.text_to_video.create.return_value = MockTaskOutput()

        mgr = VideoGenerationManager(
            log_callback=logs.append,
            runway_client=mock_client,
        )

        with patch("video_generation_manager.requests") as mock_requests:
            mock_requests.get.return_value.content = b"fake_video_data"
            out = os.path.join(tempfile.gettempdir(), "test_video.mp4")
            result = mgr.generate_video_with_runway("a cat in space", out)

        mock_client.text_to_video.create.assert_called_once()
        call_kwargs = mock_client.text_to_video.create.call_args
        self.assertEqual(call_kwargs.kwargs['model'], 'veo3.1_fast')
        self.assertIsNotNone(result)


class TestPromptTruncation(unittest.TestCase):
    """Verifica que prompts largos se truncan correctamente."""

    def test_short_prompt_not_truncated(self):
        logs = []
        mock_client = MagicMock()
        mock_client.text_to_video.create.return_value = MockTaskOutput()
        mgr = VideoGenerationManager(log_callback=logs.append, runway_client=mock_client)

        short_prompt = "A beautiful sunset over the ocean"
        with patch("video_generation_manager.requests") as mock_requests:
            mock_requests.get.return_value.content = b"fake"
            out = os.path.join(tempfile.gettempdir(), "test_short.mp4")
            mgr.generate_video_with_runway(short_prompt, out)

        sent_prompt = mock_client.text_to_video.create.call_args.kwargs['prompt_text']
        self.assertEqual(sent_prompt, short_prompt)

    def test_long_prompt_truncated_to_max_1000_chars(self):
        logs = []
        mock_client = MagicMock()
        mock_client.text_to_video.create.return_value = MockTaskOutput()
        mgr = VideoGenerationManager(log_callback=logs.append, runway_client=mock_client)

        long_prompt = ("word " * 300).strip()
        self.assertGreater(len(long_prompt), 1000)

        with patch("video_generation_manager.requests") as mock_requests:
            mock_requests.get.return_value.content = b"fake"
            out = os.path.join(tempfile.gettempdir(), "test_long.mp4")
            mgr.generate_video_with_runway(long_prompt, out)

        sent_prompt = mock_client.text_to_video.create.call_args.kwargs['prompt_text']
        self.assertLessEqual(len(sent_prompt), 1000)
        self.assertTrue(sent_prompt.endswith('word'))


class TestModelFallback(unittest.TestCase):

    def test_falls_back_to_next_model_on_not_available(self):
        logs = []
        mock_client = MagicMock()

        def side_effect(**kwargs):
            if kwargs.get('model') == 'veo3.1_fast':
                raise Exception("Model not available for your account")
            return MockTaskOutput()

        mock_client.text_to_video.create.side_effect = side_effect
        mgr = VideoGenerationManager(log_callback=logs.append, runway_client=mock_client)

        with patch("video_generation_manager.requests") as mock_requests:
            mock_requests.get.return_value.content = b"fake"
            out = os.path.join(tempfile.gettempdir(), "test_fallback.mp4")
            result = mgr.generate_video_with_runway("test prompt", out)

        self.assertIsNotNone(result)
        self.assertEqual(mock_client.text_to_video.create.call_count, 2)
        self.assertEqual(
            mock_client.text_to_video.create.call_args_list[1].kwargs['model'], 'veo3.1')

    def test_all_models_fail_returns_none(self):
        logs = []
        mock_client = MagicMock()
        mock_client.text_to_video.create.side_effect = Exception("Model not available")
        mgr = VideoGenerationManager(log_callback=logs.append, runway_client=mock_client)

        out = os.path.join(tempfile.gettempdir(), "test_all_fail.mp4")
        result = mgr.generate_video_with_runway("test", out)

        self.assertIsNone(result)
        self.assertEqual(mock_client.text_to_video.create.call_count, 5)

    def test_non_availability_error_raises_immediately(self):
        logs = []
        mock_client = MagicMock()
        mock_client.text_to_video.create.side_effect = Exception("Rate limit exceeded")
        mgr = VideoGenerationManager(log_callback=logs.append, runway_client=mock_client)

        out = os.path.join(tempfile.gettempdir(), "test_error.mp4")
        result = mgr.generate_video_with_runway("test", out)

        self.assertIsNone(result)
        self.assertEqual(mock_client.text_to_video.create.call_count, 1)


class TestNoRunwayClient(unittest.TestCase):

    def test_returns_none_without_client(self):
        mgr = VideoGenerationManager()
        result = mgr.generate_video_with_runway("test", "/tmp/out.mp4")
        self.assertIsNone(result)

    def test_leonardo_disabled(self):
        logs = []
        mgr = VideoGenerationManager(log_callback=logs.append)
        self.assertIsNone(mgr.generate_video_with_leonardo_motion("img.png", "/tmp/out.mp4"))


class TestAspectRatio(unittest.TestCase):

    def test_horizontal_ratio(self):
        mock_client = MagicMock()
        mock_client.text_to_video.create.return_value = MockTaskOutput()
        mgr = VideoGenerationManager(runway_client=mock_client)

        with patch("video_generation_manager.requests") as mock_req:
            mock_req.get.return_value.content = b"fake"
            out = os.path.join(tempfile.gettempdir(), "test_h.mp4")
            mgr.generate_video_with_runway("test", out, is_vertical=False)

        self.assertEqual(mock_client.text_to_video.create.call_args.kwargs['ratio'], '1280:720')

    def test_vertical_ratio(self):
        mock_client = MagicMock()
        mock_client.text_to_video.create.return_value = MockTaskOutput()
        mgr = VideoGenerationManager(runway_client=mock_client)

        with patch("video_generation_manager.requests") as mock_req:
            mock_req.get.return_value.content = b"fake"
            out = os.path.join(tempfile.gettempdir(), "test_v.mp4")
            mgr.generate_video_with_runway("test", out, is_vertical=True)

        self.assertEqual(mock_client.text_to_video.create.call_args.kwargs['ratio'], '720:1280')


# =====================================================================
# Fal.ai video tests
# =====================================================================

class TestFalVideoInManager(unittest.TestCase):
    """Verifica que el manager delega correctamente a fal_client."""

    def test_fal_video_delegates_to_client(self):
        """generate_video_with_fal debe llamar fal_client.generate_video."""
        mock_fal = MagicMock()
        mock_fal.client_available = True
        mock_fal.generate_video.return_value = "/tmp/ok.mp4"

        mgr = VideoGenerationManager(
            fal_client=mock_fal,
            fal_available=True,
        )
        result = mgr.generate_video_with_fal("cinematic ocean", "/tmp/out.mp4", is_vertical=True)

        self.assertEqual(result, "/tmp/ok.mp4")
        mock_fal.generate_video.assert_called_once_with(
            prompt="cinematic ocean",
            output_path="/tmp/out.mp4",
            is_vertical=True,
            duration=4,
            image_url=None,
            preferred_model=None,
        )

    def test_fal_video_returns_none_without_client(self):
        mgr = VideoGenerationManager(fal_client=None, fal_available=False)
        result = mgr.generate_video_with_fal("test", "/tmp/out.mp4")
        self.assertIsNone(result)

    def test_fal_video_returns_none_on_exception(self):
        mock_fal = MagicMock()
        mock_fal.client_available = True
        mock_fal.generate_video.side_effect = Exception("network error")

        mgr = VideoGenerationManager(fal_client=mock_fal, fal_available=True)
        result = mgr.generate_video_with_fal("test", "/tmp/out.mp4")
        self.assertIsNone(result)


class TestFalAiClientVideo(unittest.TestCase):
    """Tests para FalAiClient.generate_video directamente."""

    def _make_client(self, logs=None):
        """Crea un FalAiClient con fal_client mockeado."""
        with patch("fal_ai_client.fal_client") as mock_fal_mod:
            # Forzar import y patchear
            from fal_ai_client import FalAiClient
            client = FalAiClient.__new__(FalAiClient)
            client.log_callback = (logs.append if logs else None)
            client.model_id = "fal-ai/flux/schnell"
            client.api_key = "fake-key"
            client.api_key_id = None
            client.api_key_secret = None
            client.client_available = True
            client.last_error = None
            return client, mock_fal_mod

    def test_generate_video_success(self):
        logs = []
        client, mock_fal_mod = self._make_client(logs)
        mock_fal_mod.subscribe.return_value = {"video": {"url": "https://fal.ai/video.mp4"}}

        out = os.path.join(tempfile.gettempdir(), "test_fal_video.mp4")

        with patch("fal_ai_client.fal_client", mock_fal_mod), \
             patch("fal_ai_client.requests") as mock_requests:
            mock_requests.get.return_value.content = b"fake_video"
            result = client.generate_video("ocean waves", out)

        self.assertEqual(result, out)
        mock_fal_mod.subscribe.assert_called_once()
        call_args = mock_fal_mod.subscribe.call_args
        self.assertIn("prompt", call_args.kwargs.get("arguments", call_args[1].get("arguments", {})))

    def test_generate_video_no_client(self):
        from fal_ai_client import FalAiClient
        client = FalAiClient.__new__(FalAiClient)
        client.client_available = False
        client.last_error = None
        client.log_callback = None

        result = client.generate_video("test", "/tmp/out.mp4")
        self.assertIsNone(result)

    def test_generate_video_empty_prompt(self):
        logs = []
        client, _ = self._make_client(logs)
        result = client.generate_video("", "/tmp/out.mp4")
        self.assertIsNone(result)

    def test_extract_video_url_formats(self):
        """Verifica que _extract_video_url maneja varios formatos de respuesta."""
        from fal_ai_client import FalAiClient
        client = FalAiClient.__new__(FalAiClient)

        # Formato {"video": {"url": "..."}}
        self.assertEqual(
            client._extract_video_url({"video": {"url": "https://a.com/v.mp4"}}),
            "https://a.com/v.mp4")

        # Formato {"video": "url_string"}
        self.assertEqual(
            client._extract_video_url({"video": "https://a.com/v.mp4"}),
            "https://a.com/v.mp4")

        # Formato {"videos": [{"url": "..."}]}
        self.assertEqual(
            client._extract_video_url({"videos": [{"url": "https://a.com/v.mp4"}]}),
            "https://a.com/v.mp4")

        # Formato {"video_url": "..."}
        self.assertEqual(
            client._extract_video_url({"video_url": "https://a.com/v.mp4"}),
            "https://a.com/v.mp4")

        # Formato vacio
        self.assertIsNone(client._extract_video_url({}))
        self.assertIsNone(client._extract_video_url(None))


# =====================================================================
# Fallback cascade tests
# =====================================================================

class TestFallbackCascade(unittest.TestCase):

    def test_default_prefers_fal_over_runway(self):
        """Sin proveedor preferido, fal.ai debe intentarse primero (mas barato)."""
        logs = []
        mock_fal = MagicMock()
        mock_fal.client_available = True
        mock_fal.generate_video.return_value = "/tmp/fal_ok.mp4"

        mock_runway = MagicMock()

        mgr = VideoGenerationManager(
            log_callback=logs.append,
            fal_client=mock_fal,
            fal_available=True,
            runway_client=mock_runway,
        )

        with patch.object(mgr, 'generate_video_with_fal', return_value="/tmp/fal_ok.mp4") as mock_fal_gen, \
             patch.object(mgr, 'generate_video_with_runway') as mock_runway_gen:
            result = mgr.generate_video_with_fallback("test", "/tmp/out.mp4")

        self.assertEqual(result, "/tmp/fal_ok.mp4")
        mock_fal_gen.assert_called_once()
        mock_runway_gen.assert_not_called()

    def test_fal_fails_falls_back_to_runway(self):
        """Si fal.ai falla, debe caer a Runway."""
        logs = []
        mock_fal = MagicMock()
        mock_fal.client_available = True
        mock_runway = MagicMock()

        mgr = VideoGenerationManager(
            log_callback=logs.append,
            fal_client=mock_fal,
            fal_available=True,
            runway_client=mock_runway,
        )

        with patch.object(mgr, 'generate_video_with_fal', return_value=None) as mock_fal_gen, \
             patch.object(mgr, 'generate_video_with_runway', return_value="/tmp/runway_ok.mp4") as mock_runway_gen:
            result = mgr.generate_video_with_fallback("test", "/tmp/out.mp4")

        self.assertEqual(result, "/tmp/runway_ok.mp4")
        mock_fal_gen.assert_called_once()
        mock_runway_gen.assert_called_once()

    def test_runway_preferred_tries_runway_first(self):
        logs = []
        mock_runway = MagicMock()
        mgr = VideoGenerationManager(log_callback=logs.append, runway_client=mock_runway)

        with patch.object(mgr, 'generate_video_with_runway', return_value="/tmp/ok.mp4") as mock_gen:
            result = mgr.generate_video_with_fallback(
                "test", "/tmp/out.mp4", preferred_provider='runway')

        self.assertEqual(result, "/tmp/ok.mp4")
        mock_gen.assert_called_once()


# =====================================================================
# Cost calculator tests
# =====================================================================

class TestCostCalculator(unittest.TestCase):

    def test_fal_cheaper_than_runway(self):
        from cost_calculator import CostCalculator
        calc = CostCalculator()
        fal_cost = calc.calculate_video_cost(120, True, True, 'mixed', 'fal')
        runway_cost = calc.calculate_video_cost(120, True, True, 'mixed', 'runway')

        fal_total = float(fal_cost['total_cost_formatted'].replace('$', ''))
        runway_total = float(runway_cost['total_cost_formatted'].replace('$', ''))

        self.assertLess(fal_total, runway_total)

    def test_fal_label_in_note(self):
        from cost_calculator import CostCalculator
        calc = CostCalculator()
        result = calc.calculate_video_cost(60, False, False, 'mixed', 'fal')
        self.assertIn('Fal.ai', result['note'])

    def test_runway_label_in_note(self):
        from cost_calculator import CostCalculator
        calc = CostCalculator()
        result = calc.calculate_video_cost(60, False, False, 'mixed', 'runway')
        self.assertIn('Runway', result['note'])

    def test_static_mode_unchanged(self):
        from cost_calculator import CostCalculator
        calc = CostCalculator()
        result = calc.calculate_video_cost(60, False, False, 'static')
        self.assertIn('Recraft', result['resources_used']['videos'])

    def test_compare_shows_three_modes(self):
        from cost_calculator import CostCalculator
        calc = CostCalculator()
        comparison = calc.compare_configurations(120)
        text = comparison['comparison_text']
        self.assertIn('ESTÁTICO', text)
        self.assertIn('Fal.ai', text)
        self.assertIn('Runway', text)


if __name__ == '__main__':
    unittest.main()
