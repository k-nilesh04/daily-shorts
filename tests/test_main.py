import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.config import Config
from src.main import _validate_narration_duration, main


class MainPipelineTests(unittest.TestCase):
    def test_long_narration_is_rejected_before_paid_video_generation(self):
        with self.assertRaisesRegex(RuntimeError, "Narration is 69.4s"):
            _validate_narration_duration(69.4, 45)

    def test_narration_at_requested_duration_is_accepted(self):
        _validate_narration_duration(45, 45)

    def test_small_tts_overrun_is_accepted_within_scene_duration(self):
        _validate_narration_duration(45.8, 45)

    def test_overrun_beyond_tolerance_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "maximum allowed.*47s"):
            _validate_narration_duration(47.1, 45)

    def test_narration_never_exceeds_youtube_shorts_limit(self):
        _validate_narration_duration(60, 60)
        with self.assertRaisesRegex(RuntimeError, "maximum allowed.*60s"):
            _validate_narration_duration(60.1, 60)

    @patch("src.main.youtube.upload")
    @patch("src.main.render.build")
    @patch("src.main.video_gen.generate_scenes")
    @patch("src.main.tts.synthesize", return_value=(45.0, []))
    @patch("src.main.script_gen.generate", return_value={"script": "story", "scene_prompts": ["p1", "p2", "p3"]})
    @patch("src.main.argparse.ArgumentParser.parse_args", return_value=SimpleNamespace(upload=False))
    @patch("src.main.config.load", return_value=Config(upload=True, target_seconds=45, dry_run=True))
    def test_upload_without_credentials_bypasses_upload(
            self, _load_config, _parse_args, _script, _tts, _video, _render, upload_mock):
        self.assertEqual(main(), 0)
        upload_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
