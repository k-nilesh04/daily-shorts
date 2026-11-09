import os
os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config import Config
from src.main import _prepare_work_dir, _validate_narration_duration, main


class NarrationDurationTests(unittest.TestCase):
    def test_long_narration_is_rejected_before_paid_video_generation(self):
        with self.assertRaisesRegex(RuntimeError, "Narration is 69.4s"):
            _validate_narration_duration(69.4, 45)

    def test_narration_at_requested_duration_is_accepted(self):
        _validate_narration_duration(45, 45)

    def test_overrun_within_limit_is_accepted(self):
        _validate_narration_duration(47.1, 45)

    def test_overrun_beyond_fifty_seconds_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "maximum allowed.*50s"):
            _validate_narration_duration(50.1, 45)

    def test_narration_never_exceeds_fifty_seconds(self):
        _validate_narration_duration(50, 45)
        with self.assertRaisesRegex(RuntimeError, "maximum allowed.*50s"):
            _validate_narration_duration(50.1, 45)

    def test_underlength_narration_is_accepted_with_warning(self):
        # Under-length narration no longer blocks the run; it just produces a
        # shorter video.
        _validate_narration_duration(35, 45)

    def test_narration_just_inside_underrun_tolerance_is_accepted(self):
        _validate_narration_duration(38.3, 45)

    def test_empty_narration_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "empty"):
            _validate_narration_duration(0, 45)


class WorkDirectoryTests(unittest.TestCase):
    def test_prepare_work_dir_keeps_cached_scenes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            (work / "scenes").mkdir()
            cached = work / "scenes" / "scene_01.mp4"
            cached.write_bytes(b"cached scene")
            (work / "voice.mp3").write_bytes(b"stale voice")
            (work / "render").mkdir()
            (work / "render" / "seg_00.mp4").write_bytes(b"stale render")

            _prepare_work_dir(work)

            self.assertEqual(cached.read_bytes(), b"cached scene")
            self.assertFalse((work / "voice.mp3").exists())
            self.assertFalse((work / "render").exists())


class MainPipelineTests(unittest.TestCase):
    def test_upload_without_credentials_fails_before_any_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cfg = Config(
                upload=True,
                target_seconds=45,
                dry_run=True,
                work_dir=root / "work",
                output_dir=root / "output",
                history_file=root / "data" / "history.json",
            )
            with patch("src.main.config.load", return_value=cfg), \
                    patch("src.main.argparse.ArgumentParser.parse_args",
                          return_value=SimpleNamespace(upload=False)), \
                    patch("src.main.script_gen.generate") as generate_mock:
                with self.assertRaisesRegex(RuntimeError, "YT_CLIENT_ID"):
                    main()

            generate_mock.assert_not_called()
            self.assertFalse((root / "output" / "meta.json").exists())

    def test_upload_verifies_credentials_before_paid_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cfg = Config(
                upload=True,
                target_seconds=45,
                dry_run=True,
                yt_client_id="client-id",
                yt_client_secret="client-secret",
                yt_refresh_token="refresh-token",
                work_dir=root / "work",
                output_dir=root / "output",
                history_file=root / "data" / "history.json",
            )
            with patch("src.main.config.load", return_value=cfg), \
                    patch("src.main.argparse.ArgumentParser.parse_args",
                          return_value=SimpleNamespace(upload=False)), \
                    patch("src.main.youtube.verify") as verify_mock, \
                    patch("src.main.script_gen.generate",
                          return_value={"script": "story", "topic": "topic",
                                        "title": "Title", "description": "Description",
                                        "scene_prompts": ["p1", "p2", "p3"]}), \
                    patch("src.main.tts.synthesize", return_value=(45.0, [])), \
                    patch("src.main.video_gen.generate_scenes"), \
                    patch("src.main.render.build"), \
                    patch("src.main.youtube.upload", return_value="video-id") as upload_mock:
                self.assertEqual(main(), 0)

            verify_mock.assert_called_once_with(cfg)
            upload_mock.assert_called_once()
            self.assertTrue(cfg.history_file.is_file())


if __name__ == "__main__":
    unittest.main()
