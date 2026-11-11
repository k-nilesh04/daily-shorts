import os

os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import Config
from src.huggingface import HF_IMAGE_MODELS, HF_VIDEO_MODELS, generate_scenes


class HuggingFaceTests(unittest.TestCase):
    def test_config_accepts_huggingface_provider(self):
        cfg = Config(video_provider="huggingface")
        self.assertEqual(cfg.video_provider, "huggingface")

    @patch("src.huggingface._generate_video_clip", return_value=True)
    @patch("src.huggingface._hf_post")
    def test_generate_scenes_reuses_cached_clips(self, mock_post, mock_gen):
        cfg = Config(video_provider="huggingface", target_seconds=30)
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            # Pre-create a valid cached clip
            (work / "scene_01.mp4").write_bytes(b"x" * 2000)
            (work / "scene_02.mp4").write_bytes(b"x" * 2000)
            paths = generate_scenes(cfg, ["scene one", "scene two"], work)
            self.assertEqual(len(paths), 2)
            mock_gen.assert_not_called()

    @patch("src.huggingface._generate_video_clip")
    def test_generate_scenes_calls_video_gen_per_prompt(self, mock_gen):
        def create_clip(cfg, prompt, dest):
            dest.write_bytes(b"x" * 2000)
            return True

        mock_gen.side_effect = create_clip
        cfg = Config(video_provider="huggingface", target_seconds=30)
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            paths = generate_scenes(cfg, ["scene one", "scene two"], work)
            self.assertEqual(mock_gen.call_count, 2)
            self.assertEqual(len(paths), 2)

    @patch("src.huggingface._generate_video_clip", return_value=False)
    @patch("src.huggingface._generate_image", return_value=b"fake image bytes")
    @patch("src.huggingface._image_to_video")
    def test_falls_back_to_image_on_video_failure(self, mock_i2v, mock_img, mock_vid):
        def create_video(img_path, dest, duration, cfg):
            dest.write_bytes(b"x" * 2000)
            return True

        mock_i2v.side_effect = create_video
        cfg = Config(video_provider="huggingface", target_seconds=30)
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            paths = generate_scenes(cfg, ["scene one"], work)
            mock_img.assert_called_once()
            mock_i2v.assert_called_once()
            self.assertEqual(len(paths), 1)

    @patch("src.huggingface._generate_video_clip", return_value=False)
    @patch("src.huggingface._generate_image", return_value=None)
    def test_creates_placeholder_when_all_fail(self, mock_img, mock_vid):
        cfg = Config(video_provider="huggingface", target_seconds=30)
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            with patch("src.huggingface.subprocess.run") as mock_sub:

                def create_placeholder(cmd, **kwargs):
                    Path(cmd[-1]).write_bytes(b"placeholder")
                    return MagicMock(returncode=0)

                mock_sub.side_effect = create_placeholder
                paths = generate_scenes(cfg, ["scene one"], work)
                self.assertEqual(len(paths), 1)
                self.assertTrue(paths[0].is_file())

    def test_hf_models_lists_are_non_empty(self):
        self.assertTrue(len(HF_VIDEO_MODELS) > 0)
        self.assertTrue(len(HF_IMAGE_MODELS) > 0)


if __name__ == "__main__":
    unittest.main()
