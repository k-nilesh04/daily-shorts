import os
os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import unittest
from unittest.mock import patch

from src.config import Config


class ConfigValidationTests(unittest.TestCase):
    def test_gemini_model_defaults_to_flash_lite_and_can_be_overridden(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": ""}):
            self.assertEqual(Config().gemini_model, "gemini-3.1-flash-lite")

        with patch.dict(os.environ, {"GEMINI_MODEL": "custom-model"}):
            self.assertEqual(Config().gemini_model, "custom-model")

    def test_omni_video_model_defaults_and_can_be_overridden(self):
        with patch.dict(os.environ, {"OMNI_MODEL": ""}):
            self.assertEqual(Config().omni_model, "gemini-omni-1.2-flash")

        with patch.dict(os.environ, {"OMNI_MODEL": "custom-video-model"}):
            self.assertEqual(Config().omni_model, "custom-video-model")

    def test_target_seconds_outside_30_60_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "TARGET_SECONDS"):
            Config(target_seconds=29)
        with self.assertRaisesRegex(ValueError, "TARGET_SECONDS"):
            Config(target_seconds=61)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "VIDEO_PROVIDER"):
            Config(video_provider="veo")

    def test_unknown_layout_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "LAYOUT"):
            Config(layout="wide")

    def test_privacy_status_is_restricted(self):
        Config(privacy_status="private")
        Config(privacy_status="unlisted")
        Config(privacy_status="public")
        with self.assertRaisesRegex(ValueError, "PRIVACY_STATUS"):
            Config(privacy_status="everyone")

    def test_negative_cost_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "AI_VIDEO_MAX_USD"):
            Config(ai_video_max_usd=-1)

    def test_json2video_key_does_not_switch_provider(self):
        with patch.dict(os.environ, {"VIDEO_PROVIDER": "", "JSON2VIDEO_API_KEY": "x"}):
            cfg = Config()
        self.assertEqual(cfg.video_provider, "gemini")

    def test_json2video_image_url_has_no_default(self):
        with patch.dict(os.environ, {"JSON2VIDEO_IMAGE_URL": ""}):
            cfg = Config()
        self.assertEqual(cfg.json2video_image_url, "")


if __name__ == "__main__":
    unittest.main()
