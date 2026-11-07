import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.config import Config
from src.main import main


class MainPipelineTests(unittest.TestCase):
    @patch("src.main.script_gen.generate")
    @patch("src.main.argparse.ArgumentParser.parse_args", return_value=SimpleNamespace(upload=False))
    @patch("src.main.config.load", return_value=Config(upload=True))
    def test_upload_without_credentials_stops_before_generation(
            self, _load_config, _parse_args, generate_script):
        self.assertEqual(main(), 1)
        generate_script.assert_not_called()


if __name__ == "__main__":
    unittest.main()
