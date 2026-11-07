import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config import Config
from google.genai import errors
from src.video_gen import estimate_cost_usd, generate_scenes


class VideoGenerationTests(unittest.TestCase):
    def test_cost_estimate_uses_max_fifteen_second_clips(self):
        self.assertAlmostEqual(estimate_cost_usd(3), 3.15)

    @patch("src.video_gen.genai.Client")
    def test_budget_guard_rejects_before_calling_provider(self, client_factory):
        cfg = Config(target_seconds=60, ai_video_key="test-key", ai_video_max_usd=3.25)
        prompts = ["scene 1", "scene 2", "scene 3", "scene 4"]
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "Refusing paid AI video generation"):
                generate_scenes(cfg, prompts, Path(temp_dir))
        client_factory.assert_not_called()

    @patch("src.video_gen.genai.Client")
    def test_generates_scene_files_sequentially(self, client_factory):
        cfg = Config(target_seconds=45, ai_video_key="test-key", ai_video_max_usd=3.25)
        payload = base64.b64encode(b"fake mp4 data").decode("ascii")
        client = client_factory.return_value
        client.interactions.create.return_value = SimpleNamespace(
            output_video=SimpleNamespace(data=payload))

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(cfg, ["first scene", "second scene", "third scene"],
                                    Path(temp_dir))
            self.assertEqual(len(paths), 3)
            self.assertEqual([path.read_bytes() for path in paths],
                             [b"fake mp4 data"] * 3)

        self.assertEqual(client_factory.call_count, 3)
        calls = client.interactions.create.call_args_list
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(call.kwargs["model"], "gemini-omni-1.2-flash")
            self.assertEqual(call.kwargs["response_format"]["aspect_ratio"], "9:16")
            self.assertEqual(call.kwargs["response_format"]["resolution"], "720p")
            self.assertIn("15-second", call.kwargs["input"])

    @patch("src.video_gen.time.sleep")
    @patch("src.video_gen.genai.Client")
    def test_retries_rate_limited_scene_with_backoff(self, client_factory, sleep):
        cfg = Config(target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25)
        client = client_factory.return_value
        rate_limited = errors.ClientError(
            429, {"error": {"message": "rate exceeded", "status": "RESOURCE_EXHAUSTED"}})
        payload = base64.b64encode(b"fake mp4 data").decode("ascii")
        response = SimpleNamespace(output_video=SimpleNamespace(data=payload))
        client.interactions.create.side_effect = [rate_limited, response, response]

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        self.assertEqual(len(paths), 2)
        self.assertEqual(client.interactions.create.call_count, 3)
        sleep.assert_called_once_with(30)

    @patch("src.video_gen.time.sleep")
    @patch("src.video_gen.genai.Client")
    def test_reports_persistent_rate_limit_actionably(self, client_factory, sleep):
        cfg = Config(target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25)
        client = client_factory.return_value
        client.interactions.create.side_effect = errors.ClientError(
            429, {"error": {"message": "rate exceeded", "status": "RESOURCE_EXHAUSTED"}})

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "Check the project's Gemini Omni rate limits"):
                generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        self.assertEqual(client.interactions.create.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60, 120])


if __name__ == "__main__":
    unittest.main()
