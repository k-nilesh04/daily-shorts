import os

os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from google.genai import errors

from src.config import Config
from src.video_gen import _write_manifest, estimate_cost_usd, generate_scenes


def _ready_client(client_factory, content: bytes = b"fake mp4 data"):
    encoded = base64.b64encode(content).decode("ascii")
    client = client_factory.return_value
    client.interactions.create.return_value = SimpleNamespace(
        output_video=SimpleNamespace(data=encoded)
    )
    return client


class VideoGenerationTests(unittest.TestCase):
    def test_cost_estimate_uses_max_fifteen_second_clips(self):
        self.assertAlmostEqual(estimate_cost_usd(3), 3.15)

    @patch("src.video_gen.time.sleep")
    @patch("src.video_gen.requests.get")
    @patch("src.video_gen.requests.post")
    def test_json2video_renders_and_downloads_vertical_movie(self, post, get, sleep):
        cfg = Config(
            target_seconds=30,
            video_provider="json2video",
            json2video_key="test-key",
            json2video_image_url="https://example.com/image.jpg",
        )
        post.return_value.json.return_value = {"project": "project-id"}
        status_response = MagicMock()
        status_response.json.side_effect = [
            {"movie": {"status": "pending"}},
            {"movie": {"status": "done", "url": "https://example.com/video.mp4"}},
        ]
        media_response = MagicMock(content=b"rendered mp4")
        get.side_effect = [status_response, status_response, media_response]

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(
                cfg, ["first scene", "second scene"], Path(temp_dir), text="Short title"
            )
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].read_bytes(), b"rendered mp4")

        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["headers"], {"x-api-key": "test-key"})
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["resolution"], "instagram-story")
        self.assertEqual(payload["scenes"][0]["duration"], 30)
        # Only the background image is rendered; captions are added by FFmpeg,
        # so no fixed title text is baked into the video.
        self.assertEqual(
            payload["scenes"][0]["elements"],
            [
                {"type": "image", "src": "https://example.com/image.jpg"},
            ],
        )
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args_list[0].kwargs["params"], {"project": "project-id"})
        sleep.assert_called_once_with(3)

    @patch("src.video_gen.requests.post")
    def test_json2video_requires_api_key(self, post):
        cfg = Config(target_seconds=30, video_provider="json2video")
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "JSON2VIDEO_API_KEY is required"):
                generate_scenes(cfg, ["first", "second"], Path(temp_dir))
        post.assert_not_called()

    @patch("src.video_gen.requests.post")
    def test_json2video_requires_image_url(self, post):
        cfg = Config(
            target_seconds=30,
            video_provider="json2video",
            json2video_key="test-key",
            json2video_image_url="",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "JSON2VIDEO_IMAGE_URL"):
                generate_scenes(cfg, ["first", "second"], Path(temp_dir))
        post.assert_not_called()

    @patch("src.video_gen.requests.post")
    def test_json2video_rejects_bad_api_key_actionably(self, post):
        cfg = Config(
            target_seconds=30,
            video_provider="json2video",
            json2video_key="bad-key",
            json2video_image_url="https://example.com/image.jpg",
        )
        response = MagicMock(status_code=401)
        response.json.return_value = {"error": "unauthorized"}
        post.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "401 Client Error", response=response
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "JSON2VIDEO_API_KEY"):
                generate_scenes(cfg, ["first", "second"], Path(temp_dir))

    @patch("src.video_gen.requests.get")
    @patch("src.video_gen.requests.post")
    def test_json2video_render_error_is_reported(self, post, get):
        cfg = Config(
            target_seconds=30,
            video_provider="json2video",
            json2video_key="test-key",
            json2video_image_url="https://example.com/image.jpg",
        )
        post.return_value.json.return_value = {"project": "project-id"}
        status_response = MagicMock()
        status_response.json.return_value = {
            "movie": {"status": "error", "message": "invalid image URL"},
        }
        get.return_value = status_response

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "invalid image URL"):
                generate_scenes(cfg, ["first", "second"], Path(temp_dir))

    @patch("src.video_gen.genai.Client")
    def test_budget_guard_rejects_before_calling_provider(self, client_factory):
        cfg = Config(
            target_seconds=60, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        prompts = ["scene 1", "scene 2", "scene 3", "scene 4"]
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "Refusing paid AI video generation"):
                generate_scenes(cfg, prompts, Path(temp_dir))
        client_factory.assert_not_called()

    @patch("src.video_gen.genai.Client")
    def test_generates_scene_files_sequentially(self, client_factory):
        cfg = Config(
            target_seconds=45, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        _ready_client(client_factory)

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(
                cfg, ["first scene", "second scene", "third scene"], Path(temp_dir)
            )
            self.assertEqual(len(paths), 3)
            self.assertEqual([path.read_bytes() for path in paths], [b"fake mp4 data"] * 3)

        self.assertEqual(client_factory.call_count, 3)
        calls = client_factory.return_value.interactions.create.call_args_list
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(call.kwargs["model"], "gemini-omni-1.2-flash")
            self.assertLessEqual(call.kwargs["timeout"], 60)
            self.assertEqual(call.kwargs["response_format"]["aspect_ratio"], "9:16")
            self.assertEqual(call.kwargs["response_format"]["resolution"], "720p")
            self.assertIn("15-second", call.kwargs["input"])
            self.assertNotIn("Pixar", call.kwargs["input"])
            self.assertNotIn("Disney", call.kwargs["input"])

    @patch("src.video_gen.genai.Client")
    def test_uses_configured_video_model(self, client_factory):
        cfg = Config(
            target_seconds=30,
            ai_video_key="test-key",
            ai_video_max_usd=3.25,
            omni_model="custom-video-model",
        )
        _ready_client(client_factory)

        with tempfile.TemporaryDirectory() as temp_dir:
            generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        call = client_factory.return_value.interactions.create.call_args_list[0]
        self.assertEqual(call.kwargs["model"], "custom-video-model")

    @patch("src.video_gen.time.sleep")
    @patch("src.video_gen.genai.Client")
    def test_retries_transient_provider_errors(self, client_factory, sleep):
        cfg = Config(
            target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        client = client_factory.return_value
        unavailable = errors.ServerError(
            503, {"error": {"message": "temporarily unavailable", "status": "UNAVAILABLE"}}
        )
        payload = base64.b64encode(b"fake mp4 data").decode("ascii")
        response = SimpleNamespace(output_video=SimpleNamespace(data=payload))
        client.interactions.create.side_effect = [unavailable, response, response]

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        self.assertEqual(len(paths), 2)
        self.assertEqual(client.interactions.create.call_count, 3)
        sleep.assert_called_once_with(30)

    @patch("src.video_gen.genai.Client")
    def test_reports_invalid_model_actionably(self, client_factory):
        cfg = Config(
            target_seconds=30,
            ai_video_key="test-key",
            ai_video_max_usd=3.25,
            omni_model="no-such-model",
        )
        client_factory.return_value.interactions.create.side_effect = errors.ClientError(
            404, {"error": {"message": "model not found", "status": "NOT_FOUND"}}
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "no-such-model.*OMNI_MODEL"):
                generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

    @patch("src.video_gen.genai.Client")
    def test_decodes_base64_with_line_breaks(self, client_factory):
        cfg = Config(target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25)
        client = client_factory.return_value
        encoded = base64.b64encode(b"wrapped payload").decode("ascii")
        wrapped = "\n".join(encoded[i : i + 4] for i in range(0, len(encoded), 4))
        client.interactions.create.return_value = SimpleNamespace(
            output_video=SimpleNamespace(data=wrapped)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))
            self.assertEqual(paths[0].read_bytes(), b"wrapped payload")

    @patch("src.video_gen.genai.Client")
    def test_reuses_cached_scenes_for_the_same_prompts(self, client_factory):
        cfg = Config(target_seconds=45, ai_video_key="test-key", ai_video_max_usd=3.25)
        client = _ready_client(client_factory)
        prompts = ["first scene", "second scene", "third scene"]

        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            first = generate_scenes(cfg, prompts, work)
            calls = client.interactions.create.call_count
            second = generate_scenes(cfg, prompts, work)

        self.assertEqual(calls, 3)
        self.assertEqual([path.name for path in second], [path.name for path in first])
        self.assertEqual(client.interactions.create.call_count, 3)

    @patch("src.video_gen.genai.Client")
    def test_regenerates_only_missing_scenes(self, client_factory):
        cfg = Config(target_seconds=45, ai_video_key="test-key", ai_video_max_usd=3.25)
        client = _ready_client(client_factory)
        prompts = ["first scene", "second scene", "third scene"]

        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            generate_scenes(cfg, prompts, work)
            (work / "scene_02.mp4").unlink()
            paths = generate_scenes(cfg, prompts, work)
            self.assertTrue(all(path.is_file() for path in paths))

        self.assertEqual(client.interactions.create.call_count, 4)

    @patch("src.video_gen.genai.Client")
    def test_budget_guard_only_charges_for_missing_scenes(self, client_factory):
        cfg = Config(target_seconds=45, ai_video_key="test-key", ai_video_max_usd=1.1)
        client = _ready_client(client_factory)
        prompts = ["first scene", "second scene", "third scene"]

        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            (work / "scene_01.mp4").write_bytes(b"cached")
            (work / "scene_02.mp4").write_bytes(b"cached")
            _write_manifest(work, cfg, prompts)

            paths = generate_scenes(cfg, prompts, work)

        self.assertEqual(len(paths), 3)
        self.assertEqual(client.interactions.create.call_count, 1)

    @patch("src.video_gen.genai.Client")
    def test_regenerates_when_prompts_change(self, client_factory):
        cfg = Config(target_seconds=45, ai_video_key="test-key", ai_video_max_usd=3.25)
        client = _ready_client(client_factory)

        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            generate_scenes(cfg, ["one", "two", "three"], work)
            generate_scenes(cfg, ["four", "five", "six"], work)

        self.assertEqual(client.interactions.create.call_count, 6)

    @patch("src.video_gen.subprocess.run")
    @patch("src.video_gen.genai.Client")
    def test_dry_run_uses_placeholders_without_calling_provider(self, client_factory, run_ffmpeg):
        cfg = Config(target_seconds=30, dry_run=True, ai_video_max_usd=0)

        def create_placeholder(command, **kwargs):
            Path(command[-1]).write_bytes(b"placeholder clip")
            return subprocess.CompletedProcess(command, 0)

        run_ffmpeg.side_effect = create_placeholder
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))
            self.assertEqual(len(paths), 2)
            self.assertEqual(
                [path.read_bytes() for path in paths], [b"placeholder clip", b"placeholder clip"]
            )
        client_factory.assert_not_called()
        self.assertEqual(run_ffmpeg.call_count, 2)

    @patch("src.video_gen.time.sleep")
    @patch("src.video_gen.genai.Client")
    def test_polls_until_interaction_has_video(self, client_factory, sleep):
        cfg = Config(
            target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        pending = SimpleNamespace(id="interaction-1", status="in_progress")
        payload = base64.b64encode(b"fake mp4 data").decode("ascii")
        ready = SimpleNamespace(
            status="completed",
            output_video=SimpleNamespace(data=payload),
        )
        client = client_factory.return_value
        client.interactions.create.return_value = pending
        client.interactions.get.return_value = ready

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        self.assertEqual(len(paths), 2)
        self.assertEqual(client.interactions.get.call_count, 2)
        self.assertEqual(client.interactions.get.call_args.kwargs["timeout"], 60)
        sleep.assert_called_with(5)

    @patch("src.video_gen.time.monotonic", side_effect=[0, 0, 1])
    @patch("src.video_gen.genai.Client")
    def test_polling_stops_at_generation_deadline(self, client_factory, _monotonic):
        cfg = Config(
            target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        client = client_factory.return_value
        client.interactions.create.return_value = SimpleNamespace(
            id="interaction-1", status="in_progress"
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("src.video_gen.MAX_GENERATION_WAIT_SECONDS", 0.1),
        ):
            with self.assertRaisesRegex(TimeoutError, "did not finish within 0.1 seconds"):
                generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        client.interactions.create.assert_called_once()
        client.interactions.get.assert_not_called()

    @patch("src.video_gen.time.sleep")
    @patch("src.video_gen.genai.Client")
    def test_retries_rate_limited_scene_with_backoff(self, client_factory, sleep):
        cfg = Config(
            target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        client = client_factory.return_value
        rate_limited = errors.ClientError(
            429, {"error": {"message": "rate exceeded", "status": "RESOURCE_EXHAUSTED"}}
        )
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
    def test_honors_provider_retry_delay(self, client_factory, sleep):
        cfg = Config(
            target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        client = client_factory.return_value
        rate_limited = errors.ClientError(
            429,
            {
                "error": {
                    "message": "rate exceeded",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "45s",
                        }
                    ],
                }
            },
        )
        payload = base64.b64encode(b"fake mp4 data").decode("ascii")
        response = SimpleNamespace(output_video=SimpleNamespace(data=payload))
        client.interactions.create.side_effect = [rate_limited, response, response]

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        self.assertEqual(len(paths), 2)
        sleep.assert_called_once_with(45.0)

    @patch("src.video_gen.time.sleep")
    @patch("src.video_gen.genai.Client")
    def test_caps_provider_retry_delay(self, client_factory, sleep):
        cfg = Config(
            target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        client = client_factory.return_value
        client.interactions.create.side_effect = errors.ClientError(
            429,
            {
                "error": {
                    "message": "rate exceeded",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "9999s",
                        }
                    ],
                }
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "after 4 attempts"):
                generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        self.assertEqual([call.args[0] for call in sleep.call_args_list], [120, 120, 120])

    @patch("src.video_gen.time.sleep")
    @patch("src.video_gen.genai.Client")
    def test_reports_persistent_rate_limit_actionably(self, client_factory, sleep):
        cfg = Config(
            target_seconds=30, ai_video_key="test-key", ai_video_max_usd=3.25, dry_run=False
        )
        client = client_factory.return_value
        client.interactions.create.side_effect = errors.ClientError(
            429, {"error": {"message": "rate exceeded", "status": "RESOURCE_EXHAUSTED"}}
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                RuntimeError,
                "HTTP 429: rate exceeded.*Check the project's Gemini Omni rate limits",
            ):
                generate_scenes(cfg, ["first scene", "second scene"], Path(temp_dir))

        self.assertEqual(client.interactions.create.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60, 120])


if __name__ == "__main__":
    unittest.main()
