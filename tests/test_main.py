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

    @patch("src.main.script_gen.generate")
    @patch("src.main.argparse.ArgumentParser.parse_args", return_value=SimpleNamespace(upload=False))
    @patch("src.main.config.load", return_value=Config(upload=True))
    def test_upload_without_credentials_stops_before_generation(
            self, _load_config, _parse_args, generate_script):
        self.assertEqual(main(), 1)
        generate_script.assert_not_called()


if __name__ == "__main__":
    unittest.main()
